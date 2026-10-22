"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
夹具：单文件包（`.zip`）解包 —— `docs/PLUGIN_SPEC.md` §2 六条规则 + 只读保证 + 路径安全。

用法：`$env:PYTHONIOENCODING='utf-8'; python tests/plugins/test_zip_unpack.py`
全部在临时目录里跑，不碰仓库 plugins/ 与用户的 Workspace。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.plugins import registry as R  # noqa: E402
from core.plugins import unpack as U  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    if cond:
        print(f"  PASS {name}")
    else:
        print(f"  FAIL {name}" + (f"   ← {detail}" if detail else ""))


def manifest(pid: str, ver: str, **kw) -> dict:
    data = {
        "id": pid, "name": pid, "version": ver, "api_version": 1,
        "kind": "inprocess", "distribution": "bundled", "default_enabled": False,
        "permissions": ["ui:panel"],
        "nav": [{"id": pid, "label": pid, "mount": "web/panel.js"}],
    }
    data.update(kw)
    return data


def make_zip(path: Path, *, pid: str = "zpkg", ver: str = "1.0.0",
             at_root: bool = True, extra: dict | None = None, **manifest_kw) -> Path:
    files = {
        "plugin.json": json.dumps(manifest(pid, ver, **manifest_kw), ensure_ascii=False),
        "web/panel.js": f"// {pid} {ver}\n",
        "readme.txt": "hello",
    }
    if not at_root:  # 清单埋进子目录（违反规则 2）
        files = {f"{pid}/{k}": v for k, v in files.items()}
    files.update(extra or {})
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def snapshot(root: Path) -> dict:
    """目录快照（相对路径 → 内容哈希/标记），用于断言「一个字节都没动」。"""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        out[rel] = hashlib_of(p) if p.is_file() else "<dir>"
    return out


def hashlib_of(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="erwzip-"))
    try:
        root = base / "plugins"
        ws = base / "Workspace"
        root.mkdir(parents=True)
        ws.mkdir(parents=True)

        print("① 正常解包：包 → plugins/<id>/，且随后只读发现能看到它")
        make_zip(root / "zpkg-1.0.0.zip")
        outcomes = U.unpack_all(root, workspace=ws)
        o = outcomes[0]
        check("①-1 action=unpacked", o.action == "unpacked", o.reason)
        check("①-2 目录名 = manifest id（规则 3）", (root / "zpkg").is_dir())
        check("①-3 内容解出", (root / "zpkg" / "web" / "panel.js").is_file())
        check("①-4 标记文件写入", (root / "zpkg" / U.MARKER).is_file())
        check("①-5 包文件保留（不删用户文件）", (root / "zpkg-1.0.0.zip").is_file())
        check("①-6 无临时目录残留", not list(root.glob(f"{U.TEMP_PREFIX}*")))
        cands, notes = R.discover([("user", root)])
        check("①-7 只读发现认到它且 available",
              cands.get("zpkg") is not None and cands["zpkg"].state == "available",
              str({k: v.state for k, v in cands.items()}))

        print("② 规则 2 一包一插件：清单不在包根 → 拒收，不留目录")
        make_zip(root / "nested-1.0.0.zip", pid="nested", at_root=False)
        o = U.install_package(root / "nested-1.0.0.zip", root, workspace=ws)
        check("②-1 action=rejected", o.action == "rejected", o.action)
        check("②-2 提到「包根」", "包根" in o.reason, o.reason)
        check("②-3 没有留下目录", not (root / "nested").exists())

        print("③ 规则 3：落点由 manifest id 决定，与包文件名无关")
        make_zip(root / "totally-different-name-2.1.0.zip", pid="rightid", ver="2.1.0")
        o = U.install_package(root / "totally-different-name-2.1.0.zip", root, workspace=ws)
        check("③-1 目录 = manifest id", (root / "rightid").is_dir(), o.reason)
        check("③-2 没有按文件名建目录", not (root / "totally-different-name").exists())

        print("④ manifest 校验不过 → 拒收（复用同一套校验器）")
        make_zip(root / "badid-1.0.0.zip", pid="Bad_ID")
        o = U.install_package(root / "badid-1.0.0.zip", root, workspace=ws)
        check("④-1 action=rejected", o.action == "rejected", o.action)
        check("④-2 带 P002 码", "P002" in o.reason, o.reason)
        check("④-3 没有留下目录", not (root / "Bad_ID").exists())

        print("⑤ 解出的内容有缺件 → 拒收（panel.mount 指向的文件不存在）")
        with zipfile.ZipFile(root / "missing-1.0.0.zip", "w") as z:
            z.writestr("plugin.json", json.dumps(manifest("missing", "1.0.0")))
        o = U.install_package(root / "missing-1.0.0.zip", root, workspace=ws)
        check("⑤-1 action=rejected", o.action == "rejected", o.action)
        check("⑤-2 指出文件不存在（P016/P020）", "P01" in o.reason or "P02" in o.reason, o.reason)
        check("⑤-3 没有留下目录", not (root / "missing").exists())

        print("⑥ 规则 4 版本替换不合并：旧目录整体进回收站")
        (root / "zpkg" / "old-only.txt").write_text("v1 only", encoding="utf-8")
        make_zip(root / "zpkg-2.0.0.zip", ver="2.0.0")
        o = U.install_package(root / "zpkg-2.0.0.zip", root, workspace=ws)
        check("⑥-1 action=upgraded", o.action == "upgraded", f"{o.action} {o.reason}")
        check("⑥-2 新版本已就位", "2.0.0" in (root / "zpkg" / "web" / "panel.js").read_text(encoding="utf-8"))
        check("⑥-3 旧文件没有被合并进来", not (root / "zpkg" / "old-only.txt").exists())
        trash = ws / "System" / "Trash" / "plugins" / "zpkg-1.0.0"
        check("⑥-4 旧版整体在回收站", trash.is_dir(), str(trash))
        check("⑥-5 回收站里保留了旧文件", (trash / "old-only.txt").is_file())
        check("⑥-6 标记版本已更新", json.loads((root / "zpkg" / U.MARKER).read_text(encoding="utf-8"))["version"] == "2.0.0")

        print("⑦ 幂等：同一个包再扫一次 → current，不写盘")
        before = snapshot(root / "zpkg")
        o = U.install_package(root / "zpkg-2.0.0.zip", root, workspace=ws)
        check("⑦-1 action=current", o.action == "current", f"{o.action} {o.reason}")
        check("⑦-2 目录快照未变", snapshot(root / "zpkg") == before)

        print("⑧ 规则 5 不覆盖用户手放目录")
        hand = root / "handmade"
        hand.mkdir()
        (hand / "plugin.json").write_text(json.dumps(manifest("handmade", "0.9.0"), ensure_ascii=False), encoding="utf-8")
        (hand / "mine.txt").write_text("这是我手放的", encoding="utf-8")
        before = snapshot(hand)
        make_zip(root / "handmade-1.0.0.zip", pid="handmade", ver="1.0.0")
        o = U.install_package(root / "handmade-1.0.0.zip", root, workspace=ws)
        check("⑧-1 action=conflict", o.action == "conflict", f"{o.action} {o.reason}")
        check("⑧-2 手放目录一个字节没动", snapshot(hand) == before)
        check("⑧-3 提示「不是由 zip 解出」", "不是由 zip 解出" in o.reason, o.reason)

        print("⑨ 升级但没有工作区 → 拒改（规则 4 的兜底）")
        make_zip(root / "handmade-2.0.0.zip", pid="handmade", ver="2.0.0")
        # 先给 handmade 打上标记，模拟「解出来的旧版」
        (hand / U.MARKER).write_text(json.dumps({"id": "handmade", "version": "0.9.0"}), encoding="utf-8")
        before = snapshot(hand)
        o = U.install_package(root / "handmade-2.0.0.zip", root, workspace=None)
        check("⑨-1 action=conflict", o.action == "conflict", f"{o.action} {o.reason}")
        check("⑨-2 提到回收站/覆盖", "回收站" in o.reason, o.reason)
        check("⑨-3 目录未变", snapshot(hand) == before)

        print("⑩ 规则 6 路径安全：`..` 穿越 / 绝对路径 / 符号链接")
        outside = base / "evil.txt"
        with zipfile.ZipFile(root / "slip-1.0.0.zip", "w") as z:
            z.writestr("plugin.json", json.dumps(manifest("slip", "1.0.0")))
            z.writestr("../evil.txt", "pwned")
        o = U.install_package(root / "slip-1.0.0.zip", root, workspace=ws)
        check("⑩-1 穿越包被拒", o.action == "rejected", o.action)
        check("⑩-2 提到 .. 穿越", "穿越" in o.reason, o.reason)
        check("⑩-3 根目录外没有落地文件", not outside.exists() and not (base / "evil.txt").exists())
        check("⑩-4 没有留下目录", not (root / "slip").exists())

        with zipfile.ZipFile(root / "abs-1.0.0.zip", "w") as z:
            z.writestr("plugin.json", json.dumps(manifest("abs", "1.0.0")))
            z.writestr("C:/Windows/Temp/evil2.txt", "pwned")
        o = U.install_package(root / "abs-1.0.0.zip", root, workspace=ws)
        check("⑩-5 盘符绝对路径被拒", o.action == "rejected" and "绝对路径" in o.reason, o.reason)

        with zipfile.ZipFile(root / "link-1.0.0.zip", "w") as z:
            z.writestr("plugin.json", json.dumps(manifest("link", "1.0.0")))
            z.writestr("web/panel.js", "// x")
            info = zipfile.ZipInfo("escape")
            info.external_attr = (0o120777 << 16)  # symlink
            z.writestr(info, "target")
        o = U.install_package(root / "link-1.0.0.zip", root, workspace=ws)
        check("⑩-6 符号链接条目被拒", o.action == "rejected" and "符号链接" in o.reason, o.reason)

        print("⑪ 防 zip 炸弹：条目数上限（临时收紧后验，不改常量默认值）")
        saved = U.MAX_ENTRIES
        try:
            U.MAX_ENTRIES = 2
            make_zip(root / "bomb-1.0.0.zip", pid="bomb", ver="1.0.0")
            o = U.install_package(root / "bomb-1.0.0.zip", root, workspace=ws)
            check("⑪-1 action=rejected", o.action == "rejected", o.action)
            check("⑪-2 提到上限", "上限" in o.reason, o.reason)
        finally:
            U.MAX_ENTRIES = saved

        print("⑫ 僵尸临时目录：超时清理 + 不被当成插件")
        stale = root / f"{U.TEMP_PREFIX}ghost-9.9.9"
        stale.mkdir()
        (stale / "junk.txt").write_text("x", encoding="utf-8")
        old = time.time() - (U.STALE_TEMP_HOURS + 1) * 3600
        os.utime(stale, (old, old))
        U.unpack_all(root, workspace=ws)  # 有包在 → 触发扫描与清理
        check("⑫-1 僵尸临时目录被清掉", not stale.exists())
        cands, _ = R.discover([("user", root)])
        check("⑫-2 临时目录不会被当成插件", not any(c.startswith(U.TEMP_PREFIX) for c in cands))

        print("⑬ 只读根不动：随包库里的包只给提示")
        ro = base / "bundled"
        ro.mkdir()
        make_zip(ro / "ro-1.0.0.zip", pid="ro", ver="1.0.0")
        saved_access = U.os.access
        try:
            U.os.access = lambda *a, **k: False
            outcomes = U.unpack_all(ro, workspace=ws)
        finally:
            U.os.access = saved_access
        check("⑬-1 只读根给 conflict", outcomes and outcomes[0].action == "conflict", str(outcomes))
        check("⑬-2 提到只读", "只读" in outcomes[0].reason, outcomes[0].reason)
        check("⑬-3 没有写盘", not (ro / "ro").exists())

        print("⑭ 只读保证：discover/report 结构上不可能写盘（审计工具不该装东西）")
        ro2 = base / "auditroot"
        ro2.mkdir()
        make_zip(ro2 / "audit-1.0.0.zip", pid="audit", ver="1.0.0")
        before = snapshot(ro2)
        R.discover([("user", ro2)])                       # 只读发现
        R.report(roots=[("user", ro2)], workspace=ws)      # 只读盘点
        check("⑭-1 discover/report 不写盘", snapshot(ro2) == before)
        outcomes = R.install_packages([("user", ro2)], workspace=ws)
        check("⑭-2 只有显式 install_packages 才解包",
              (ro2 / "audit").is_dir() and outcomes[0].action == "unpacked", str(outcomes))
        check("⑭-3 结果带结构化字段（供设置页渲染）",
              set(outcomes[0].as_dict()) >= {"file", "id", "version", "action", "action_label", "reason"})

        print("⑮ CLI 入口：--install 才安装，默认只读")
        import subprocess
        ro3 = base / "cliroot"
        ro3.mkdir()
        make_zip(ro3 / "cli-1.0.0.zip", pid="clipkg", ver="1.0.0")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        p1 = subprocess.run([sys.executable, "-m", "core.plugins", "list", "--plugins-root", str(ro3)],
                            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", env=env)
        check("⑮-1 默认 list 不安装", not (ro3 / "clipkg").exists(), p1.stdout[-120:])
        p2 = subprocess.run([sys.executable, "-m", "core.plugins", "list", "--install",
                             "--plugins-root", str(ro3)],
                            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", env=env)
        check("⑮-2 --install 解包并列出", (ro3 / "clipkg").is_dir() and "clipkg" in p2.stdout, p2.stdout[-200:])
        check("⑮-3 --install 提示里说明已解包", "已解包安装" in p2.stdout, p2.stdout[-200:])

        print("⑯ 失败隔离：一个坏包不影响同目录的好包")
        bad = base / "mixed"
        bad.mkdir()
        (bad / "broken-1.0.0.zip").write_bytes(b"this is not a zip at all")
        make_zip(bad / "good-1.0.0.zip", pid="goodpkg", ver="1.0.0")
        outcomes = U.unpack_all(bad, workspace=ws)
        by = {o.file: o for o in outcomes}
        check("⑯-1 坏包 rejected", by["broken-1.0.0.zip"].action == "rejected", by["broken-1.0.0.zip"].reason)
        check("⑯-2 好包照常装上", by["good-1.0.0.zip"].action == "unpacked" and (bad / "goodpkg").is_dir())

        print("⑰ 与 doctor 的交叉检查：插件回收站不能被判成「回收站目录漂移」")
        from core.contracts import kinds as C
        from core.doctor import Report, check_workspace_hygiene
        check("⑰-1 升级确实建了插件回收站（System/Trash/plugins/）",
              (ws / "System" / "Trash" / "plugins").is_dir())
        check("⑰-2 契约里声明了 plugins 命名空间", "plugins" in C.TRASH_EXTRA, str(C.TRASH_EXTRA))
        rep = Report()
        check_workspace_hygiene(ws, rep)
        drift = [i for i in rep.items if "回收站目录漂移" in i["check"]]
        check("⑰-3 doctor 认这条（检查确实跑了）", len(drift) == 1, str(drift))
        check("⑰-4 plugins 不算漂移", bool(drift) and drift[0]["count"] == 0, str(drift))
        # 反向：真的野目录仍要被抓到（别把检查改废）
        (ws / "System" / "Trash" / "bogus_ns").mkdir(parents=True, exist_ok=True)
        rep2 = Report()
        check_workspace_hygiene(ws, rep2)
        drift2 = [i for i in rep2.items if "回收站目录漂移" in i["check"]][0]
        check("⑰-5 真野目录仍被抓到", drift2["count"] == 1 and "bogus_ns" in drift2["detail"], str(drift2))
        shutil.rmtree(ws / "System" / "Trash" / "bogus_ns", ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    total = len(PASS) + len(FAIL)
    print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
