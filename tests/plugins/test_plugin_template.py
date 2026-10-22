"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
夹具：插件模板 + 脚手架 —— 「照模板做一个插件，不改内核任何一行」的端到端验证。

回答四个问题（PLUGIN_SPEC §13）：
1. 内核是否预留了接入基础（丢进目录就能用）；
2. 模板是否让新插件无需修改内核；
3. 新插件是否不需要动原先的内核 UI；
4. 内核的改动是否会一次废掉所有插件（这里用「插件侧零引用」+ 契约接缝回归来守）。

用法：`$env:PYTHONIOENCODING='utf-8'; python tests/plugins/test_plugin_template.py`
会往 Workspace/config 里写一小段示例数据（插件的配置），结束时**校验清干净**。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.plugins import manifest as M  # noqa: E402

ID = "tmplcheck"
NAME = "模板自检插件"
DESC = "模板夹具生成，验完即删"
PASS: list[str] = []
FAIL: list[str] = []

#: 夹具会经内核写到的真实路径（结束前必须清干净）
TOUCHED = [
    ROOT / "config" / "plugins" / f"{ID}.json",
    ROOT / "Workspace" / "System" / "Plugins" / ID,
    ROOT / "Workspace" / "Plugins" / ID,
    ROOT / "Workspace" / "System" / "Cache" / f"{ID}.sqlite",
]
#: 启用会往这里写一条记录：夹具必须**按原样恢复**（不能只删自己的键，那是人家的文件）
PLUGINS_JSON = ROOT / "Workspace" / "System" / "plugins.json"


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "tools" / "new_plugin.py"), *args],
                          cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, method="POST",
                                 headers={"Content-Type": "application/json"},
                                 data=json.dumps(payload).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def http_status(url: str) -> int:
    """只取状态码，不抛异常（用来断言"未启用时路由确实不存在"）。"""
    import urllib.error
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return int(e.code)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob("*")) if p.is_file()}


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="erwtmpl-"))
    root = base / "plugins"
    root.mkdir(parents=True)
    httpd = None
    saved_plugins_json = PLUGINS_JSON.read_bytes() if PLUGINS_JSON.is_file() else None
    try:
        print("① 脚手架：从模板生成一个新插件（先临时后原子）")
        p = run(ID, "--name", NAME, "--desc", DESC, "--root", str(root))
        check("①-1 退出码 0", p.returncode == 0, (p.stdout + p.stderr)[-300:])
        target = root / ID
        check("①-2 目录已生成且名 = id", target.is_dir())
        files = sorted(str(x.relative_to(target)).replace("\\", "/") for x in target.rglob("*") if x.is_file())
        check("①-3 五个文件齐备",
              files == ["README.md", "backend.py", "plugin.json", "web/panel.css", "web/panel.js"], str(files))
        check("①-4 没有留下临时目录",
              not (root / ".staging").exists() and not (root / f".new-{ID}").exists(),
              str(sorted(p.name for p in root.iterdir())))

        print("② 占位符全部替换、清单合法、UTF-8 无 BOM")
        leftovers = []
        for f in target.rglob("*"):
            if f.is_file():
                text = f.read_text(encoding="utf-8")
                leftovers += [f"{f.name}:{t}" for t in M.__dict__.get("TOKENS", ()) if t in text]
        blob = "\n".join(f.read_text(encoding="utf-8") for f in target.rglob("*") if f.is_file())
        check("②-1 没有残留占位符",
              all(t not in blob for t in ("__ID__", "__NAME__", "__DESC__", "__ICON__", "__CORE_MIN__")),
              str(leftovers[:5]))
        check("②-2 替换成了正确的 id 与名字", ID in blob and NAME in blob)
        raw = (target / "plugin.json").read_bytes()
        check("②-3 plugin.json 无 BOM", not raw.startswith(b"\xef\xbb\xbf"))
        data, issues = M.load_manifest(target)
        issues = list(issues) + list(M.validate(data, plugin_dir=target))
        check("②-4 通过安装期同一套校验（0 error）", not M.errors(issues),
              str(M.errors(issues)))
        check("②-5 id 与目录名一致（P018 不会触发）", (data or {}).get("id") == ID)

        print("③ 安全性：拒绝非法 id / 拒绝覆盖 / dry-run 不落盘")
        p = run("Bad_ID", "--root", str(root))
        check("③-1 非法 id 退出码 2", p.returncode == 2, str(p.returncode))
        before = snapshot(target)
        p = run(ID, "--name", NAME, "--root", str(root))
        check("③-2 已存在时拒绝覆盖（退出码 2）", p.returncode == 2, str(p.returncode))
        check("③-3 原目录一个字节没动", snapshot(target) == before)
        p = run("dryrunpkg", "--root", str(root), "--dry-run")
        check("③-4 dry-run 退出码 0 且不落盘",
              p.returncode == 0 and not (root / "dryrunpkg").exists(), p.stdout[-200:])
        p = run("forcepkg", "--root", str(root))
        (root / "forcepkg" / "mine.txt").write_text("旧内容", encoding="utf-8")
        p = run("forcepkg", "--name", "重做", "--root", str(root), "--force")
        backups = sorted(x.name for x in root.glob(".backup-forcepkg-*"))
        check("③-5 --force 把旧目录整体挪到 .backup-*（不删不合并）",
              p.returncode == 0 and len(backups) == 1, str(backups))
        check("③-6 备份里保留旧文件", backups and (root / backups[0] / "mine.txt").is_file())
        check("③-7 新目录里没有旧文件（未合并）", not (root / "forcepkg" / "mine.txt").exists())
        shutil.rmtree(root / "forcepkg", ignore_errors=True)
        for b in root.glob(".backup-*"):
            shutil.rmtree(b, ignore_errors=True)

        print("④ 零内核改动：内核源码里不该出现这个插件的任何痕迹")
        kernel_files = [ROOT / "server.py", ROOT / "core_api.py"]
        for pat in ("web/*.js", "web/*.html", "web/*.json", "core/**/*.py", "app/*.py", "mcp/*.py"):
            kernel_files += [p for p in ROOT.glob(pat) if p.is_file()]
        hits = []
        for f in kernel_files:
            text = f.read_text(encoding="utf-8", errors="replace")
            if ID in text or NAME in text:
                hits.append(str(f.relative_to(ROOT)))
        check("④-1 内核源码零引用（id 与显示名都没出现）", not hits, str(hits))
        check("④-2 生成的文件只在插件目录内", not any(
            x for x in ROOT.joinpath("plugins").glob(f"{ID}*")))

        print("⑤ 端到端：真服务器加载这个插件（ERW_PLUGINS_ROOTS 指向临时根）")
        os.environ["ERW_PLUGINS_ROOTS"] = str(root)
        import server

        port = free_port()
        httpd, _cfg, url = server.build_server(port_override=port, auto_open_browser=False)
        th = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        th.start()

        wait_ready(url)
        detail = get(f"{url}/api/plugins?detail=1")
        rows = {x["id"]: x for x in detail["plugins"]}
        check("⑤-1 插件被发现且可用", rows.get(ID, {}).get("state") == "available", str(sorted(rows)))
        check("⑤-2 导航项与面板信息下发", rows.get(ID, {}).get("nav_labels") == [NAME], str(rows.get(ID)))
        check("⑤-3 权限被识别为已知权限",
              all(p.get("id") in ("ui:panel", "storage:own", "config:own")
                  for p in rows.get(ID, {}).get("permissions", [])), str(rows.get(ID, {}).get("permissions")))
        check("⑤-4 有配置接口（路由里声明了 config）", rows.get(ID, {}).get("has_config_route") is True)
        check("⑤-5 默认未启用（default_enabled:false）", rows.get(ID, {}).get("enabled") is False,
              str(rows.get(ID, {}).get("enabled")))
        check("⑤-6 未启用时后端路由不注册（不会偷偷生效）",
              http_status(f"{url}/api/plugins/{ID}/hello") == 404)

        print("⑥ 启用它（走设置页同一条接口），随后路由/工具/配置全部到位")
        enabled = post(f"{url}/api/plugin-manager/{ID}/enabled", {"enabled": True})
        check("⑥-1 启用接口返回 ok", enabled.get("ok") is True, str(enabled))
        hello = get(f"{url}/api/plugins/{ID}/hello?name={quote('夹具')}")
        check("⑥-2 路由可用且带命名空间前缀",
              hello.get("ok") is True and hello.get("plugin") == ID and "夹具" in hello.get("greeting", ""),
              str(hello))

        cfg_path = ROOT / "config" / "plugins" / f"{ID}.json"
        saved = post(f"{url}/api/plugins/{ID}/config", {"greeting": "模板夹具问候"})
        check("⑥-3 配置写入插件自己的配置文件",
              cfg_path.is_file() and saved.get("greeting") == "模板夹具问候", str(saved))
        check("⑥-4 配置回读一致", get(f"{url}/api/plugins/{ID}/config").get("greeting") == "模板夹具问候")

        tools = get(f"{url}/api/agent/tools")
        items = tools if isinstance(tools, list) else (tools.get("tools") or tools.get("items") or [])
        names = [t.get("name") or t.get("id") or "" for t in items]
        check("⑥-5 Agent 工具带 p_<id>__ 前缀接入", f"p_{ID}__ping" in names,
              str([n for n in names if "tmpl" in n.lower()] or names[:6]))

        print("⑦ 真浏览器：新插件的页面/设置 tab 都能用，且没动内核 UI")
        ui = browser_checks(url)
        for name, ok, detail_text in ui:
            check(name, ok, detail_text)

        print("⑨ 装不上的插件必须在设置页如实可见（不能只让 CLI 知道）")
        p = run("toonewkernel", "--name", "要求过高", "--root", str(root), "--core-min", "v999999")
        check("⑨-1 生成成功（清单本身合法）", p.returncode == 0, (p.stdout + p.stderr)[-200:])
        preview = get(f"{url}/api/plugins?detail=1")
        rows2 = {x["id"]: x for x in preview["plugins"]}
        bad = rows2.get("toonewkernel", {})
        check("⑨-2 预览里能看到它且状态为 rejected", bad.get("state") == "rejected", str(bad)[:200])
        check("⑨-3 理由写明内核版本过低", "内核版本" in str(bad.get("reason", "")), str(bad.get("reason"))[:120])
        plain2 = get(f"{url}/api/plugins")
        check("⑨-4 普通清单不把它交给脚本宿主（不加载装不上的插件）",
              all(x["id"] != "toonewkernel" for x in plain2["plugins"]),
              str([x["id"] for x in plain2["plugins"]]))
        tmpl_core_min = json.loads((target / "plugin.json").read_text(encoding="utf-8"))["core_min"]
        check("⑨-5 模板默认 core_min = 当前内核版本（不会要求未发布内核）",
              tmpl_core_min == (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
              f"模板={tmpl_core_min} 内核={(ROOT / 'VERSION').read_text(encoding='utf-8').strip()}")
    finally:
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        os.environ.pop("ERW_PLUGINS_ROOTS", None)
        # System/plugins.json 是用户的文件：按开始时的原样恢复（不是只删自己那条）
        if saved_plugins_json is None:
            PLUGINS_JSON.unlink(missing_ok=True)
        else:
            PLUGINS_JSON.write_bytes(saved_plugins_json)
        for path in TOUCHED:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                path.unlink(missing_ok=True)
        shutil.rmtree(base, ignore_errors=True)

    print("⑧ 收尾：夹具写过的路径全部清干净")
    left = [str(p.relative_to(ROOT)) for p in TOUCHED if p.exists()]
    check("⑧-1 无残留（config/ 与 Workspace/）", not left, str(left))
    check("⑧-2 仓库 plugins/ 没被污染",
          not any(ROOT.joinpath("plugins").glob(f"{ID}*"))
          and not (ROOT / "plugins" / ".staging").exists())
    now_json = PLUGINS_JSON.read_bytes() if PLUGINS_JSON.is_file() else None
    check("⑧-3 System/plugins.json 已按原样恢复", now_json == saved_plugins_json,
          f"before={len(saved_plugins_json or b'')}B after={len(now_json or b'')}B")

    total = len(PASS) + len(FAIL)
    print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


def wait_ready(url: str, tries: int = 60) -> None:
    import time
    for _ in range(tries):
        try:
            get(f"{url}/api/plugins")
            return
        except Exception:
            time.sleep(0.25)


def browser_checks(url: str) -> list[tuple[str, bool, str]]:
    """用真浏览器点一遍新插件的页面与设置 tab；同时验证 data-plugin 作用域真的生效。"""
    out: list[tuple[str, bool, str]] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [("⑥-0 playwright 可用", False, "pip install playwright")]

    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe if Path(exe).is_file() else None, headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 950}).new_page()
        errs: list[str] = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.goto(f"{url}/#settings", wait_until="networkidle", timeout=60000)
        page.wait_for_selector("#settings-panel", timeout=30000)

        tabs = page.eval_on_selector_all("[data-set-tab]", "els => els.map(e => e.dataset.setTab)")
        out.append(("⑥-1 设置页出现插件自己的 tab", ID in tabs, str(tabs)))
        page.click(f'[data-set-tab="{ID}"]')
        page.wait_for_timeout(400)
        panel = page.eval_on_selector("#settings-panel", """e => ({
            plugin: e.dataset.plugin || '', text: e.innerText.slice(0, 60) })""")
        out.append(("⑥-2 插件 tab 渲染出来", "设置" in panel["text"], str(panel)))
        out.append(("⑥-3 设置容器带 data-plugin（样式作用域）", panel["plugin"] == ID, str(panel)))

        # 切回内核 tab：属性必须被清掉（插件 CSS 不许泄漏到内核页面）
        page.click('[data-set-tab="general"]')
        page.wait_for_timeout(300)
        general = page.eval_on_selector("#settings-panel", "e => e.dataset.plugin || ''")
        out.append(("⑥-4 切回内核 tab 后 data-plugin 被清掉", general == "", repr(general)))

        # 导航页
        routes = page.eval_on_selector_all("[data-route]", "els => els.map(e => e.dataset.route)")
        out.append(("⑥-5 侧栏出现插件导航项", ID in routes, str([r for r in routes if "tmpl" in r] or routes[:8])))
        page.click(f'[data-route="{ID}"]')
        page.wait_for_selector(f'#main[data-plugin="{ID}"]', timeout=15000)
        card = page.eval_on_selector("#main", """e => ({
            has: !!e.querySelector('.tp-card'),
            plugin: e.dataset.plugin || '',
            border: getComputedStyle(e.querySelector('.tp-out')).borderTopWidth,
            kinds: (e.querySelector('#tp-kinds') || {}).textContent || '',
        })""")
        out.append(("⑥-6 插件页面渲染在主区", card["has"], str(card)))
        out.append(("⑥-7 主区带 data-plugin", card["plugin"] == ID, str(card)))
        # [data-plugin="<id>"] 作用域内的规则真的生效（旧内核拿不到该属性 → 这里会是 0px）
        out.append(("⑥-8 插件 CSS 按 data-plugin 作用域生效", card["border"] not in ("0px", ""),
                    f"borderTopWidth={card['border']}"))
        out.append(("⑥-9 用到了内核只读契约 ERWContract", "类别" in card["kinds"], card["kinds"][:80]))

        # 调自己的后端
        page.click("#tp-call")
        page.wait_for_timeout(900)
        body = page.inner_text("#tp-out")
        out.append(("⑥-10 页面调自己的 HTTP 路由成功", ID in body and "ok" in body, body[:120]))

        # 导航回内核页面：属性也要清掉
        page.click('[data-route="overview"]')
        page.wait_for_timeout(800)
        stale = page.eval_on_selector("#main", "e => e.dataset.plugin || ''")
        out.append(("⑥-11 回内核页面后 data-plugin 被清掉", stale == "", repr(stale)))
        out.append(("⑥-12 0 console error", not errs, str(errs[:3])))
        browser.close()
    return out


if __name__ == "__main__":
    raise SystemExit(main())
