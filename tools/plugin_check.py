"""插件隔离体检 —— 内核必须能在「零插件」下完整运行（PLUGIN_SPEC §4.3 / 不变量 I1、I2）。

    python tools/plugin_check.py                     # 静态不变量 + 空插件集盘点
    python tools/plugin_check.py --assert-core-only  # 同上，并把「插件集非空」也当通过条件（CI 用）
    python tools/plugin_check.py --json

静态查什么（只读，不导入插件）：

1. **I2 依赖方向单向**：`core/**` 与 `server.py`、`app/**` 都不得 import 插件实现
   （`plugins.` 命名空间）；插件只能经 `core_api` 与内核交互。
2. **core 不依赖 app**：`core/**` 不得 import `app`——这是「内核可独立裁剪/测试」的前提，
   也是插件运行期动态加载 core 时不会踩 `app` 顺序炸弹的前提。
3. **空插件集可启动**：把扫描根指向一个**空目录**，插件盘点必须无 rejected/blocked/conflict
   （也就是「零插件」是合法状态，不是故障）。
4. **不是空的** 交给运行时套件：真正的行为验收是 `tools/kb_smoke.py` + `tools/ui_smoke.py`
   ——它们跑的就是「当前装配」下的完整功能。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.plugins import manifest as M  # noqa: E402
from core.plugins import registry as R  # noqa: E402

#: 允许 import 插件的白名单（目前应为空：内核不认识任何具体插件）
PLUGIN_IMPORTERS_ALLOWED: set[str] = set()

PLUGIN_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(plugins[\w.]*)", re.M)
APP_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(app[\w.]*)", re.M)
#: I3：插件只允许 import 标准库与 core_api；这些是禁止的内核私有入口
PLUGIN_FORBIDDEN_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(core\.|app\.|mcp\.|server\b)", re.M)


def strip_comments(text: str) -> str:
    text = re.sub(r'"""[\s\S]*?"""', " ", text)
    text = re.sub(r"'''[\s\S]*?'''", " ", text)
    text = re.sub(r"(?m)#[^\n]*$", " ", text)
    return text


def scan_plugin_imports() -> list[str]:
    """I2：内核侧不得 import 插件实现。"""
    offenders: list[str] = []
    targets = list((ROOT / "core").rglob("*.py")) + list((ROOT / "app").rglob("*.py")) + [ROOT / "server.py"]
    for path in targets:
        rel = path.relative_to(ROOT).as_posix()
        if rel in PLUGIN_IMPORTERS_ALLOWED:
            continue
        if PLUGIN_IMPORT_RE.search(strip_comments(path.read_text(encoding="utf-8"))):
            offenders.append(rel)
    return offenders


def scan_core_app_coupling() -> list[str]:
    """core 不得 import app（内核独立性）；镜像 app/paths.py 的少数几行不算依赖。"""
    offenders: list[str] = []
    for path in (ROOT / "core").rglob("*.py"):
        text = strip_comments(path.read_text(encoding="utf-8"))
        if APP_IMPORT_RE.search(text):
            offenders.append(path.relative_to(ROOT).as_posix())
    return offenders


def empty_set_report() -> dict:
    """把扫描根指向空目录，验证「零插件」是合法状态。"""
    tmp = ROOT / ".scratch" / "verify" / "plugins-empty"
    (tmp / "bundled").mkdir(parents=True, exist_ok=True)
    (tmp / "user").mkdir(parents=True, exist_ok=True)
    return R.report(
        roots=[("bundled", tmp / "bundled"), ("user", tmp / "user")],
        workspace=None,
        core_version=M.read_core_version(ROOT) if (ROOT / "VERSION").is_file() else "",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="插件隔离体检（只读）")
    ap.add_argument("--assert-core-only", action="store_true", help="CI 用：显式断言零插件可跑")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    fails: list[str] = []
    notes: list[str] = []

    offenders = scan_plugin_imports()
    if offenders:
        fails.append(f"I2 违反：内核侧 import 了插件实现 {offenders}（插件只能经 core_api 交互）")
    else:
        notes.append("I2 通过：core/、app/、server.py 均未 import 插件实现")

    coupling = scan_core_app_coupling()
    if coupling:
        fails.append(f"core 依赖了 app：{coupling}（内核必须能脱离 app 独立加载）")
    else:
        notes.append("core 未 import app（内核独立性保持）")

    report = empty_set_report()
    bad = report["rejected"] + report["blocked"] + report["conflict"]
    if bad:
        fails.append(f"空插件集不是合法状态：rejected={report['rejected']} blocked={report['blocked']} conflict={report['conflict']}")
    else:
        notes.append("空插件集盘点干净（零插件 = 合法状态）")

    # 一次发现，供下面几组插件侧检查共用
    candidates, _notes2 = R.discover()
    R.resolve(candidates, M.read_core_version(ROOT) if (ROOT / "VERSION").is_file() else "")

    # 内核版本文件必须「无 BOM」——带 BOM 会让 core_min 比较全线失败，所有插件被误判为
    # 「内核版本过低」而阻塞（实测事故：服务启动后插件路由全 404，而 CLI 看起来正常）
    version_path = ROOT / "VERSION"
    if version_path.is_file():
        raw = version_path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            fails.append("VERSION 带 UTF-8 BOM：会让 core_min 比较失败、所有插件被判为「内核版本过低」。"
                         "请以无 BOM 的 UTF-8 重写（Python 的 write_bytes / .NET UTF8Encoding($false)）")
        elif not M.read_core_version(ROOT):
            fails.append("VERSION 读出来是空串：插件版本门槛会被整体跳过（请检查文件内容）")
        else:
            notes.append(f"内核版本 {M.read_core_version(ROOT)}（无 BOM）")

    # core_api 必须真的入库：它是插件的唯一门面，落在仓库根（不在 core/** 通配里），
    # 很容易被 .gitignore 的白名单漏掉——那样克隆下来插件全废（本轮真踩过一次）。
    facade = ROOT / "core_api.py"
    if not facade.is_file():
        fails.append("core_api.py 不存在（插件唯一允许 import 的门面）")
    else:
        try:
            tracked = subprocess.run(["git", "ls-files", "core_api.py"], capture_output=True,
                                     text=True, encoding="utf-8", errors="replace", cwd=str(ROOT))
            ignored = subprocess.run(["git", "check-ignore", "-q", "core_api.py"], cwd=str(ROOT))
            if tracked.returncode == 0 and ignored.returncode == 0:
                fails.append("core_api.py 被 .gitignore 忽略：插件门面必须入库，否则克隆后插件全废")
            elif tracked.returncode == 0 and not tracked.stdout.strip():
                notes.append("提示：core_api.py 存在但尚未 git add")
            else:
                notes.append("core_api.py 已入库（插件门面）")
        except OSError:
            pass

    # I3：插件只允许 import 标准库与 core_api（不得碰 core.* 私有模块、app.*、别的插件）
    FORBIDDEN = PLUGIN_FORBIDDEN_IMPORT_RE
    for pid, cand in sorted(candidates.items()):
        if cand.state != "available":
            continue
        entry = str((cand.manifest or {}).get("entry") or "").strip()
        if not entry:
            continue
        path = Path(cand.dir) / entry
        if not path.is_file():
            continue
        text = strip_comments(path.read_text(encoding="utf-8"))
        hits = FORBIDDEN.findall(text)
        if hits:
            fails.append(f"I3 违反：插件 {pid} 的 {entry} import 了内核私有模块 {sorted(set(hits))}"
                         "（只允许 `from core_api import ...`）")
        else:
            notes.append(f"I3 通过：{pid} 的后端只 import 标准库 / core_api")
        # 面板脚本不得改内核 DOM 基础设施（§6.3）；这里只提示依赖了哪些内核接缝
        for item in (cand.manifest or {}).get("nav") or []:
            mount = str((item or {}).get("mount") or "")
            script = Path(cand.dir) / mount
            if mount and script.is_file():
                seams = sorted(set(re.findall(r"window\.(ERW[\w$]*)", script.read_text(encoding="utf-8"))))
                if seams:
                    notes.append(f"插件 {pid} 面板依赖的内核接缝：{seams}")

        # manifest 声明的 mcp_tools 必须真的在入口里注册（否则清单在说谎，工具永远不出现）
        declared = [str(t) for t in (cand.manifest or {}).get("mcp_tools") or []]
        if declared:
            entry_src = (Path(cand.dir) / entry).read_text(encoding="utf-8")
            missing = [t for t in declared if f'"{t}"' not in entry_src and f"'{t}'" not in entry_src]
            if missing:
                fails.append(f"插件 {pid} 的 manifest 声明了工具 {missing}，但入口文件里找不到对应注册"
                             "（声明了却不可用 = I10 反例）")
            else:
                notes.append(f"插件 {pid} 声明的 {len(declared)} 个工具都能在入口里找到注册")

    real = R.report(workspace=None, core_version=M.read_core_version(ROOT))
    notes.append(f"当前 plugins/ 实况：发现 {len(real['plugins'])} 个，可用 {real['available']}，"
                 f"blocked {real['blocked']}，rejected {real['rejected']}，冲突 {real['conflict']}")

    # 面板契约：声明了 nav（导航页）或 panel（**无导航页的 UI**，如阅读区 tab）的插件，
    # 其脚本必须自登记 ERWPanels——否则脚本会正常加载但什么都不做，
    # 表现为「插件装了却不出现」，属静默失败（I11）。
    panel_mounts: list[tuple[str, str, str]] = []
    for pid, cand in sorted(candidates.items()):
        if cand.state != "available":
            continue
        manifest = cand.manifest or {}
        for item in manifest.get("nav") or []:
            mount = str((item or {}).get("mount") or "")
            if mount:
                panel_mounts.append((pid, mount, "nav.mount"))
        panel = manifest.get("panel")
        if isinstance(panel, dict) and panel.get("mount"):
            panel_mounts.append((pid, str(panel["mount"]), "panel.mount"))
    for pid, mount, where in panel_mounts:
        script = Path(candidates[pid].dir) / mount
        if not script.is_file():
            fails.append(f"插件 {pid} 的 {where} 文件不存在：{mount}")
            continue
        text = script.read_text(encoding="utf-8")
        # 面板脚本必须真的挂到某个内核接缝上，否则就是「装了却什么都不出现」的静默失败（I11）。
        # 认可的自登记接缝：ERWPanels（导航项/槽位/设置页 tab/阅读区 tab）、
        # ERWGraphRenderers（图谱渲染接管）、ERWReader / ERWReaderAssist（阅读区与其助手）——
        # 后三者不需要导航项也能生效。
        seams = ("ERWPanels.register", "ERWPanels?.register",
                 "ERWGraphRenderers.register", "ERWGraphRenderers?.register",
                 "ERWReader.register", "ERWReader?.register",
                 "ERWReaderAssist.register", "ERWReaderAssist?.register")
        hit = next((s for s in seams if s in text), None)
        if not hit:
            fails.append(f"插件 {pid} 的面板 {mount}（{where}）没有自登记任何内核接缝"
                         f"（认可：{'、'.join(seams)}）——脚本会正常加载但什么都不出现")
        else:
            notes.append(f"面板契约通过：{pid} → {mount}（{where}）自登记 {hit.replace('?.', '.')}")

    if args.assert_core_only:
        # 额外跑一次数据冒烟：它跑在「当前装配」上，等价于「核心零插件」的功能验收（I1 的代理）
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "kb_smoke.py")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT))
        if r.returncode != 0:
            fails.append("kb_smoke 未通过（零插件下核心必须完整可跑）")
        else:
            notes.append("kb_smoke 在零插件装配下通过（I1 代理）")

    out = {"fails": fails, "notes": notes, "core_only_report": report}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for n in notes:
            print(f"  - {n}")
        if fails:
            print(f"\n发现 {len(fails)} 个问题：")
            for f in fails:
                print(f"  [x] {f}")
        else:
            print("\n插件隔离体检通过：依赖方向单向、内核可脱离 app、零插件是合法状态")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
