"""前端冒烟 —— 逐个走查页面路由，断言「能渲染、无报错、接缝在、首屏不拉重库」。

    python tools/ui_smoke.py                      # 默认 http://127.0.0.1:8765
    python tools/ui_smoke.py --base-url http://127.0.0.1:8799 --json
    python tools/ui_smoke.py --strict             # playwright 缺失时也算失败

为什么需要它（docs/REFACTOR_PLAN.md P29）：后端有 `tools/kb_smoke.py`、装配层有
`tools/web_check.py`，但**页面能不能点开**此前没有任何自动闸门——`17682ce` 那次
「一个补丁的语法错误直接打掉整个 PDF 工作区」正是这类事故。本脚本只读 DOM/控制台/网络，
**不截图**（文本优先，见 AGENTS.md：图片 token 只与像素面积相关，能文本判断就别截图）。

断言：
1. 首屏能加载，标题非空，**无 console error、无失败请求**；
2. `web/app.js` 里 `NAV_GROUPS` 声明的**每个路由**都挂得上、点得开、能渲染出内容
   （期望路由从 app.js 本身解析，不另抄一份清单）；
3. 首屏**不请求** mathjax / mermaid（A1 的按需加载是硬约束，回归了要立刻知道）；
4. `window.erwVendor` 按需加载器在；
5. base 依赖的补丁接缝（`window.ERW*`）都真的就位。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "web" / "app.js"

#: 首屏出现即视为「按需加载回归」的重型库
HEAVY_LIBS = ("mathjax", "mermaid")


def assembled_js() -> list[Path]:
    """本次装配真正加载的业务 JS（读 web/manifest.json，而不是磁盘上所有文件）。

    这样「要求某个接缝存在」只会要求**已装配模块真正消费**的那些：
    把某个功能模块从装配里摘掉时，它的接缝就不再被要求（§6.7「内核零插件可跑」）。
    """
    try:
        manifest = json.loads((ROOT / "web" / "manifest.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for item in manifest.get("js", []):
        path = ROOT / "web" / item["file"]
        if path.is_file():
            out.append(path)
    return out


def seam_report() -> tuple[list[str], list[str], list[str]]:
    """已装配模块的接缝自洽性（静态）：返回 (消费, 提供, 缺失)。

    判据是**装配自洽**而不是「运行期一定已赋值」：`window.ERWCurrentDoc` 这类是**状态型**
    接缝（打开条目后才赋值），首屏为空是正常的；而「某模块消费了一个没人提供的接缝」
    无论运行期状态如何都是装配错误。提供方按整份装配汇总（跨模块提供也算数）。

    v261009.14 · **插件前端脚本也算装配的一部分**：阅读区搬进 plugins/literature-reader 之后，
    `window.ERWLiterature` / `window.ERWCapture` 由插件提供、悬浮球（内核模块）消费；
    内核只认 `window.ERWReader` 注册表，不认识具体插件，故依赖方向仍然成立。
    """
    consumed: set[str] = set()
    provided: set[str] = set()
    scripts = list(assembled_js())
    # 点目录（如 plugins/.template 模板）不是插件：与 registry.discover 同一规则，不参与接缝统计
    scripts += sorted(p for p in (ROOT / "plugins").glob("*/web/*.js")
                      if not p.parent.parent.name.startswith(".")) if (ROOT / "plugins").is_dir() else []
    for path in scripts:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        text = re.sub(r"(?m)//[^\n]*$", " ", text)
        for symbol in re.findall(r"window\.(ERW[\w$]*)", text):
            (provided if re.search(rf"window\.{re.escape(symbol)}\s*=", text) else consumed).add(symbol)
    return sorted(consumed), sorted(provided), sorted(consumed - provided)


def declared_routes() -> list[str]:
    """从 web/app.js 的 NAV_GROUPS 解析路由 id（单一来源，不另抄清单）。"""
    text = APP_JS.read_text(encoding="utf-8")
    m = re.search(r"NAV_GROUPS\s*=\s*\[(.*?)\n\s*\];", text, re.S)
    if not m:
        return []
    out: list[str] = []
    for line in m.group(1).splitlines():
        for route in re.findall(r"\['([a-z0-9-]+)',", line):
            if route not in out:
                out.append(route)
    return out


def find_browser() -> str | None:
    """优先复用机器上已有的浏览器（不强制 `playwright install`）。"""
    import os
    import shutil

    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ]
    env = os.environ.get("ERW_BROWSER") or os.environ.get("CHROME_PATH")
    if env and Path(env).is_file():
        return env
    for cand in candidates:
        if Path(cand).is_file():
            return cand
    return shutil.which("chrome") or shutil.which("msedge") or shutil.which("google-chrome")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="前端冒烟（只读 DOM/控制台/网络，不截图）")
    ap.add_argument("--base-url", default="http://127.0.0.1:8765")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="playwright 缺失时也判失败")
    ap.add_argument("--timeout", type=int, default=30000, help="单次导航超时 ms")
    args = ap.parse_args(argv)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        msg = "SKIP 未安装 playwright（pip install playwright 即可；浏览器可复用系统已有的 Chrome/Edge）"
        print(json.dumps({"skipped": True, "reason": msg}, ensure_ascii=False) if args.json else msg)
        return 1 if args.strict else 0

    routes = declared_routes()
    fails: list[str] = []
    notes: list[str] = [f"app.js 声明 {len(routes)} 个路由"]

    with sync_playwright() as p:
        exe = find_browser()
        launch_kwargs = {"headless": True}
        if exe:
            launch_kwargs["executable_path"] = exe
            notes.append(f"浏览器：{exe}")
        else:
            notes.append("浏览器：playwright 自带")
        browser = p.chromium.launch(**launch_kwargs)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()

        first_requests: list[str] = []
        console: list[str] = []
        failed_reqs: list[str] = []
        page.on("request", lambda r: first_requests.append(r.url))
        page.on("console", lambda m: console.append(f"[{m.type}] {m.text}") if m.type == "error" else None)
        page.on("requestfailed", lambda r: failed_reqs.append(f"{r.url} :: {r.failure}"))

        page.goto(args.base_url + "/", wait_until="networkidle", timeout=args.timeout)
        page.wait_for_timeout(800)
        title = page.title()

        if not title.strip():
            fails.append("首页标题为空（页面没渲染出来）")
        heavy = [u for u in first_requests if any(h in u.lower() for h in HEAVY_LIBS)]
        if heavy:
            fails.append(f"首屏请求了重型库（按需加载回归）：{heavy}")
        consumed, provided, missing_seams = seam_report()
        if missing_seams:
            fails.append(f"装配不自洽：这些接缝被消费但已装配模块里没有提供方 {missing_seams}")
        notes.append(f"装配自洽性：消费 {len(consumed)} 个 ERW* 接缝，提供 {len(provided)} 个，缺失 {len(missing_seams)} 个")
        if not page.evaluate("() => !!window.erwVendor && typeof window.erwVendor.load === 'function'"):
            fails.append("window.erwVendor 按需加载器缺失")
        if not page.evaluate("() => typeof window.erwFetch === 'function'"):
            fails.append("window.erwFetch 接缝缺失（分页/图谱限流/搜索取消会静默失效）")
        if "workbenchPerformanceFetch" in page.evaluate("() => window.fetch.toString()"):
            fails.append("window.fetch 被全局替换了（P14 红线：补丁将无法摘除）")
        dom_seam = page.evaluate(
            "() => window.ERWDom ? {observers: window.ERWDom.observerCount(), subscribers: window.ERWDom.subscriberCount()} : null"
        )
        if not dom_seam:
            fails.append("window.ERWDom 共享 DOM 变更接缝缺失（A9：不应各自新建整树 observer）")
        else:
            if int(dom_seam.get("observers") or 0) != 1:
                fails.append(f"ERWDom observer 实例数应为 1，实际 {dom_seam.get('observers')}")
            if int(dom_seam.get("subscribers") or 0) < 5:
                fails.append(f"ERWDom 订阅方过少（{dom_seam.get('subscribers')}）——补丁可能没接上接缝")
            notes.append(f"DOM 变更接缝：1 个 observer / {dom_seam.get('subscribers')} 个订阅方")

        # 面板注册表（§6.3）：按**声明的能力**分类核对
        #   render      → 导航面板：必须在侧栏里，且必须点得开
        #   slot        → 槽位面板：必须挂到对应槽位
        #   settingsTab → 设置页 tab：必须出现在设置页，且**不该**在侧栏多出一项
        panels = page.evaluate(
            "() => (window.ERWPanels && window.ERWPanels.list ? window.ERWPanels.list() : [])"
            ".map(p => ({id: p.id, slot: p.slot || '', render: typeof p.render === 'function', "
            "tab: p.settingsTab ? (p.settingsTab.id || p.id) : '', "
            "rtab: p.readerTab ? (p.readerTab.id || p.id) : ''}))"
        )
        if not page.evaluate("() => !!window.ERWPanels && typeof window.ERWPanels.register === 'function'"):
            fails.append("window.ERWPanels 面板注册表缺失（§6.3：功能无法自行登记导航与页面）")
        nav_panels = [str(p["id"]) for p in panels if p["render"]]
        slot_panels = [(str(p["id"]), str(p["slot"])) for p in panels if p.get("slot")]
        tab_panels = [(str(p["id"]), str(p["tab"])) for p in panels if p.get("tab")]
        reader_tabs = [(str(p["id"]), str(p["rtab"])) for p in panels if p.get("rtab")]
        nav_routes = [r for r in page.eval_on_selector_all(".nav-item", "els => els.map(e => e.dataset.route)") if r]
        for pid in nav_panels:
            if pid not in nav_routes:
                fails.append(f"导航面板 {pid} 已登记但未出现在侧栏导航里")
        for pid, slot in slot_panels:
            if not page.query_selector(f'[data-erw-slot="{slot}"] [data-plugin="{pid}"]'):
                fails.append(f"槽位面板 {pid} 未挂载到槽位 {slot}")
        for pid, tab in tab_panels + reader_tabs:
            if pid in nav_routes:
                fails.append(f"{pid} 只贡献 tab（设置页/阅读区），却也在侧栏导航里多出了一项")
        if tab_panels:
            try:
                page.goto(f"{args.base_url}/#settings", wait_until="domcontentloaded", timeout=args.timeout)
                page.wait_for_selector("#settings-panel", timeout=args.timeout)
                page.wait_for_timeout(400)
                tab_ids = page.eval_on_selector_all("[data-set-tab]", "els => els.map(e => e.dataset.setTab)")
                for pid, tab in tab_panels:
                    if tab not in tab_ids:
                        fails.append(f"设置页 tab「{tab}」（{pid} 贡献）没出现在设置页：{tab_ids}")
                # 贡献的 tab 必须点得开、渲染出内容
                for pid, tab in tab_panels:
                    if tab in tab_ids:
                        page.click(f'[data-set-tab="{tab}"]')
                        page.wait_for_timeout(700)
                        panel_len = page.eval_on_selector("#settings-panel", "e => e.innerText.trim().length")
                        if panel_len < 20:
                            fails.append(f"设置页 tab「{tab}」渲染为空（{panel_len} 字）")
            except Exception as exc:
                fails.append(f"设置页 tab 走查失败：{exc}")
        notes.append(f"面板注册表：导航 {nav_panels}；槽位 {slot_panels}；"
                     f"设置页 tab {[t for _, t in tab_panels]}；阅读区 tab {[t for _, t in reader_tabs]}")

        rendered: dict[str, str] = {}
        # 走查清单 = 内核声明的路由 + 导航面板（槽位面板没有页面，不在此列）
        walk_routes = routes + [p for p in nav_panels if p not in routes]
        for route in walk_routes:
            before = len(console)
            try:
                page.goto(f"{args.base_url}/#{route}", wait_until="domcontentloaded", timeout=args.timeout)
                page.wait_for_timeout(600)
                info = page.evaluate(
                    """() => {
                        const main = document.querySelector('#main');
                        const active = document.querySelector('.nav-item.active');
                        return {
                          len: main ? main.innerText.trim().length : 0,
                          active: active ? (active.dataset.route || '') : '',
                          heading: (document.querySelector('#page-title') || {}).textContent || '',
                        };
                    }"""
                )
            except Exception as exc:  # 路由渲染异常不该中断整轮
                fails.append(f"路由 {route} 打开失败：{exc}")
                continue
            rendered[route] = info["heading"] or route
            if info["len"] < 20:
                fails.append(f"路由 {route} 渲染内容过少（{info['len']} 字符）")
            if info["active"] and info["active"] != route:
                fails.append(f"路由 {route} 高亮错位到 {info['active']}")
            new_errors = console[before:]
            if new_errors:
                fails.append(f"路由 {route} 有 console error：{new_errors[:2]}")

        if console:
            fails.append(f"console 出现 {len(console)} 条 error：{console[:3]}")
        if failed_reqs:
            fails.append(f"{len(failed_reqs)} 个请求失败：{failed_reqs[:3]}")

        browser.close()

    report = {
        "base_url": args.base_url,
        "title": title,
        "routes_checked": len(walk_routes),
        "route_headings": rendered,
        "heavy_libs_on_first_screen": heavy,
        "console_errors": console,
        "failed_requests": failed_reqs,
        "fails": fails,
        "notes": notes,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for n in notes:
            print(f"  - {n}")
        print(f"  页面标题：{title}")
        for route, heading in rendered.items():
            print(f"  ok  #{route:<18} {heading}")
        if fails:
            print(f"\n发现 {len(fails)} 个问题：")
            for f in fails:
                print(f"  [x] {f}")
        else:
            print(f"\n前端冒烟通过：首屏干净、{len(walk_routes)} 个路由全部可渲染、接缝齐备、首屏未拉重型库")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
