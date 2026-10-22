"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
验收：① 点「资讯源设置」立刻出设置（不再等一整轮抓取）② 点源筛选立刻生效
③ 强制刷新真能抓到新内容 ④ 全页 0 console error。"""
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8799"
EXE = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  · {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE if Path(EXE).is_file() else None, headless=True)
    pg = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
    errs, bad = [], []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("requestfailed", lambda r: bad.append(r.url))
    feeds = []
    pg.on("response", lambda r: feeds.append(r.url) if "/api/plugins/rss/feed" in r.url else None)

    pg.goto(f"{BASE}/#news", wait_until="networkidle", timeout=60000)
    pg.wait_for_selector('[data-plugin="rss"] .news-grid', timeout=60000)
    pg.wait_for_timeout(1500)
    cards = pg.eval_on_selector_all(".news-card", "els => els.length")
    check("资讯页有内容", cards > 0, f"{cards} 张卡片")

    # ① 设置：从点击到出现设置面板的耗时（关键：不应触发抓取）
    before = len(feeds)
    t0 = time.time()
    pg.click("#news-settings")
    pg.wait_for_selector("#rss-list", timeout=15000)
    dt = (time.time() - t0) * 1000
    rows = pg.eval_on_selector_all("[data-rss-name]", "els => els.length")
    check(f"点「资讯源设置」立刻出设置（{dt:.0f} ms）", dt < 1500, f"{dt:.0f} ms, {rows} 个源")
    check("展开设置没有触发抓取请求", len(feeds) == before, f"新增 {len(feeds) - before} 个 feed 请求")
    check("设置里能列出全部源并带添加/保存", rows >= 3 and pg.query_selector("#rss-add") and pg.query_selector("#rss-save"),
          f"{rows} 源")
    # 关键：设置必须真的**看得见**（曾渲染在 72 张卡片下面，屏幕上什么也看不到）
    vis = pg.evaluate("""() => {
        const panel = document.querySelector('#rss-settings-panel');
        const grid = document.querySelector('[data-plugin="rss"] .news-grid');
        if (!panel) return null;
        const r = panel.getBoundingClientRect();
        return {
          inViewport: r.top < window.innerHeight && r.bottom > 0,
          aboveGrid: grid ? (panel.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING) > 0 : null,
          top: Math.round(r.top), height: Math.round(r.height), winH: window.innerHeight,
        };
    }""")
    check("设置面板在视口内（不需要滚动就能看到）", bool(vis and vis["inViewport"]), str(vis))
    check("设置面板在资讯列表上方", bool(vis and vis["aboveGrid"]), str(vis))

    # ② 源筛选：应立刻重绘、不抓取
    before = len(feeds)
    t0 = time.time()
    pick = pg.query_selector('#main .rss-status[data-news-src]:not([data-news-src=""])')
    if pick:
        pick.click()
        pg.wait_for_timeout(300)
        dt2 = (time.time() - t0) * 1000
        meta = pg.eval_on_selector("#main .row-meta", "e => e.innerText")
        check(f"点源筛选立刻生效（{dt2:.0f} ms）", "只看" in meta, meta[:40])
        check("筛选没有触发抓取请求", len(feeds) == before, f"新增 {len(feeds) - before} 个")
        pg.evaluate("() => localStorage.removeItem('newsFilter')")
    else:
        check("源状态卡可点", False, "没找到可选源")

    # ③ 强制刷新：真抓取
    before = len(feeds)
    pg.click("#news-refresh")
    pg.wait_for_timeout(500)
    btn = pg.eval_on_selector("#news-refresh", "e => e.innerText")
    print(f"  刷新按钮即时状态：{btn}")
    pg.wait_for_function("() => !document.querySelector('#news-refresh').disabled", timeout=180000)
    pg.wait_for_timeout(800)
    info = pg.evaluate("""() => {
        const box = document.querySelector('[data-plugin="rss"]');
        const t = box ? box.innerText : '';
        return {
          cards: box ? box.querySelectorAll('.news-card').length : 0,
          stale: /当前显示缓存内容/.test(t),
          failed: /全部获取失败/.test(t),
          meta: (t.match(/[^\\n]*(最近抓取|缓存更新)[^\\n]*/) || [''])[0].slice(0, 40),
        };
    }""")
    check("强制刷新没有触发抓取请求", len(feeds) > before, f"新增 {len(feeds) - before} 个")
    check("刷新后仍显示内容且不是全失败", info["cards"] > 0 and not info["failed"], str(info))
    print(f"  刷新结果：{info}")

    check("全程无 console error", not errs, str(errs[:2]))
    check("全程无失败请求", not bad, str(bad[:2]))
    b.close()

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（设置秒开且在视口内可见、筛选零延迟、强制刷新真能抓到新内容）")
