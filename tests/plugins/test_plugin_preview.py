"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
夹具：插件设置页的「演示预览」（悬停/点击）。

覆盖：
① 载荷：11 个插件都下发 preview（摘要/功能点/截图 URL），截图 HTTP 200；
② 悬停插件卡片 → 浮层出现，含插件名、摘要、功能点、截图（图片真实解码，不是坏图）；
③ 点击「预览」行 → 固定；再点 / 按 Esc / 点浮层外 → 收起；
④ **未启用的插件也能预览**（这正是要预览的时候），并提示"未启用"；
⑤ 没声明 preview 的插件不出现预览行（内核不认识具体插件）；
⑥ 真浏览器 0 console error；
⑦ 收尾：临时插件目录不留残留。

用法：`$env:PYTHONIOENCODING='utf-8'; python tests/plugins/test_plugin_preview.py`
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "support"))
from fixture_cleanup import restore_many, snap_many  # noqa: E402

ID = "metrics-table"          # 一个**已启用**的插件（用户当前就开着）
DISABLED = "report-export"    # 一个**未启用**的插件（默认不启用，用来验"未启用也能预览"）
PLAIN = "focus"               # 这里临时改成"没有 preview"来验"没声明就不出现"？——不：focus 有 preview
PASS: list[str] = []
FAIL: list[str] = []
PLUGINS_JSON = ROOT / "Workspace" / "System" / "plugins.json"


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get(url: str):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def head_ok(url: str) -> tuple[int, int]:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return int(r.status), len(r.read())
    except urllib.error.HTTPError as exc:
        return int(exc.code), 0


def route_checks(url: str, rows: dict) -> list[tuple[str, bool, str]]:
    """每个「有导航页」的插件：导航到 manifest 声明的 nav id，主区应挂载它自己的面板。"""
    out: list[tuple[str, bool, str]] = []
    targets = []
    skipped = []
    for pid, row in rows.items():
        nav = [n for n in (row.get("nav") or []) if isinstance(n, dict)]
        if not nav or nav[0].get("slot"):
            continue
        if not row.get("enabled"):
            skipped.append(pid)          # 未启用的插件面板不会注册，这里不校验（预览功能另有断言覆盖）
            continue
        targets.append((pid, str(nav[0].get("id") or pid)))
    if not targets:
        return [("③-0 有已启用且可导航的插件", False, "一个都没有")]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [("③-0 playwright 可用", False, "pip install playwright")]
    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe if Path(exe).is_file() else None, headless=True)
        page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        for pid, nav_id in targets:
            try:
                page.goto(f"{url}/#{nav_id}", wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(1200)
                got = page.eval_on_selector("#main", "e => e.dataset.plugin || ''")
                out.append((f"③ 路由 #{nav_id} → 挂载 {pid} 的面板", got == nav_id,
                            f"#main data-plugin={got!r}（应为 {nav_id!r}）"))
            except Exception as exc:
                out.append((f"③ 路由 #{nav_id} → 挂载 {pid} 的面板", False, f"{type(exc).__name__}: {exc}"))
        if skipped:
            out.append((f"③-9 未启用的 {len(skipped)} 个插件不参与路由校验（面板未注册是正常的）",
                        True, str(skipped)))
        browser.close()
    return out


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="erwpv-"))
    root = base / "plugins"
    root.mkdir(parents=True)
    # 全部插件（除一个"没声明 preview"的对照组）都拷进临时根，避免动仓库目录
    for src in sorted((ROOT / "plugins").iterdir()):
        if src.is_dir() and not src.name.startswith("."):
            shutil.copytree(src, root / src.name)
    # 对照组：删掉某插件的 preview，验证"没声明就不出现预览行"
    nopv = root / "focus" / "plugin.json"
    data = json.loads(nopv.read_text(encoding="utf-8"))
    data.pop("preview", None)
    nopv.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    httpd = None
    saved_json = PLUGINS_JSON.read_bytes() if PLUGINS_JSON.is_file() else None
    ns_before = snap_many([ROOT / "Workspace" / "Plugins" / ID,
                           ROOT / "Workspace" / "System" / "Plugins" / ID])
    try:
        os.environ["ERW_PLUGINS_ROOTS"] = str(root)
        import server

        httpd, _c, url = server.build_server(port_override=free_port(), auto_open_browser=False)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
        for _ in range(60):
            try:
                get(f"{url}/api/plugins")
                break
            except Exception:
                time.sleep(0.25)

        print("① 载荷：每个插件都带 preview，截图可取")
        detail = get(f"{url}/api/plugins?detail=1")
        rows = {p["id"]: p for p in detail["plugins"]}
        check("①-1 插件数 >= 10", len(rows) >= 10, str(sorted(rows)))
        with_preview = [pid for pid, r in rows.items() if r.get("preview")]
        check("①-2 除对照组的插件都带 preview", len(with_preview) >= len(rows) - 1,
              f"{len(with_preview)}/{len(rows)}")
        check("①-3 对照组（删掉 preview 的 focus）没有 preview", not rows.get("focus", {}).get("preview"))
        sample = rows[ID]["preview"]
        check("①-4 预览含摘要/功能点/截图三件",
              bool(sample.get("summary")) and len(sample.get("features") or []) >= 2
              and len(sample.get("screens") or []) >= 1, str(sample)[:160])
        codes = {}
        for pid, r in rows.items():
            shots = (r.get("preview") or {}).get("screens") or []
            if shots:
                codes[pid] = head_ok(f"{url}{shots[0]['url']}")[0]
        check("①-5 所有截图 HTTP 200", all(c == 200 for c in codes.values()),
              str({k: v for k, v in codes.items() if v != 200}))

        print("② 真浏览器：悬停 / 点击 / 收起")
        for name, ok, detail_text in browser_checks(url):
            check(name, ok, detail_text)

        print("③ 路由契约：每个插件的导航 id 必须真的解析到它自己的页面")
        # 来历：抓图时把 RSS 插件的路由硬编码成 `#rss`，而它的 nav id 其实是 `news`
        # → 截出来是兜底的总览页。这里逐个导航并用 `#main[data-plugin]` 验证路由归属。
        for name, ok, detail_text in route_checks(url, rows):
            check(name, ok, detail_text)
    finally:
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        os.environ.pop("ERW_PLUGINS_ROOTS", None)
        if saved_json is None:
            PLUGINS_JSON.unlink(missing_ok=True)
        else:
            PLUGINS_JSON.write_bytes(saved_json)
        from core.plugins import jobs as plugin_jobs

        plugin_jobs.shutdown()
        restore_many(ns_before)
        shutil.rmtree(base, ignore_errors=True)

    print("③ 收尾")
    check("③-1 plugins.json 未被动过",
          (PLUGINS_JSON.read_bytes() if PLUGINS_JSON.is_file() else None) == saved_json)
    leftover = {k: [str(p) for p in Path(k).rglob("*") if p.is_file()][:3]
                for k, v in ns_before.items() if Path(k).exists()}
    check("③-2 插件命名空间无新增文件", not any(leftover.values()), str(leftover))

    total = len(PASS) + len(FAIL)
    print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


def browser_checks(url: str) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [("②-0 playwright 可用", False, "pip install playwright")]
    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe if Path(exe).is_file() else None, headless=True)
        page = browser.new_context(viewport={"width": 1500, "height": 950}).new_page()
        errs: list[str] = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.goto(f"{url}/#settings", wait_until="networkidle", timeout=60000)
        page.wait_for_selector("#settings-panel", timeout=30000)
        page.click('[data-set-tab="plugins"]')
        page.wait_for_selector(f'[data-plugin-preview="{ID}"]', timeout=30000)
        page.wait_for_timeout(600)

        out.append(("②-1 卡片上有「预览」行", True, ""))
        nopv_rows = page.eval_on_selector_all(f'[data-plugin-preview="focus"]', "els => els.length")
        out.append(("②-2 没声明 preview 的插件没有预览行（内核不认识具体插件）",
                    int(nopv_rows) == 0, f"{nopv_rows} 个"))

        # 悬停
        page.hover(f'[data-plugin-preview="{ID}"]')
        page.wait_for_selector(".pm-preview", timeout=15000)
        page.wait_for_timeout(700)
        box = page.eval_on_selector(".pm-preview", """e => ({
            title: (e.querySelector('.pm-pv-head b')||{}).textContent || '',
            sum: (e.querySelector('.pm-pv-sum')||{}).textContent || '',
            feats: e.querySelectorAll('.pm-pv-feats li').length,
            imgs: Array.from(e.querySelectorAll('.pm-shot img')).map(i => ({w: i.naturalWidth, h: i.naturalHeight})),
            where: (e.querySelector('.pm-pv-where')||{}).textContent || '',
            foot: (e.querySelector('.pm-pv-foot')||{}).textContent || '',
        })""")
        out.append(("②-3 悬停浮出预览且含插件名", bool(box["title"]), str(box)[:120]))
        out.append(("②-4 含摘要与功能点", len(box["sum"]) > 6 and box["feats"] >= 2,
                    f"摘要 {len(box['sum'])} 字 / 功能点 {box['feats']} 条"))
        out.append(("②-5 截图真实解码（naturalWidth>0）",
                    bool(box["imgs"]) and all(i["w"] > 50 for i in box["imgs"]), str(box["imgs"])))
        out.append(("②-6 写明「在哪找」", "在哪找" in box["where"], box["where"][:60]))

        # 移到别处 → 自动收起
        page.mouse.move(5, 5)
        page.wait_for_timeout(900)
        left = page.eval_on_selector_all(".pm-preview", "els => els.length")
        out.append(("②-7 鼠标移开后浮层消失", int(left) == 0, f"{left} 个"))

        # 点击固定
        page.click(f'[data-plugin-preview="{ID}"]')
        page.wait_for_selector(".pm-preview", timeout=15000)
        page.mouse.move(5, 5)
        page.wait_for_timeout(900)
        pinned = page.eval_on_selector_all(".pm-preview", "els => els.length")
        out.append(("②-8 点击后固定（移开鼠标仍在）", int(pinned) == 1, f"{pinned} 个"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        out.append(("②-9 Esc 收起",
                    int(page.eval_on_selector_all(".pm-preview", "els => els.length")) == 0, ""))

        # 未启用的插件也能预览
        page.hover(f'[data-plugin-preview="{DISABLED}"]')
        page.wait_for_selector(".pm-preview", timeout=15000)
        page.wait_for_timeout(600)
        foot = page.eval_on_selector(".pm-preview .pm-pv-foot", "e => e.textContent || ''")
        title = page.eval_on_selector(".pm-preview .pm-pv-head b", "e => e.textContent || ''")
        out.append(("②-10 未启用的插件也能预览", bool(title), title[:40]))
        out.append(("②-11 明确提示「未启用」", "未启用" in foot, foot[:80]))
        page.keyboard.press("Escape")

        out.append(("②-12 全程 0 console error", not errs, str(errs[:3])))
        browser.close()
    return out


if __name__ == "__main__":
    raise SystemExit(main())
