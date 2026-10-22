"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
验收：插件卡片与配置区都默认一行；详情/配置按需展开，展开后点同一行即可收起。

1. 卡片默认只有一行「版本」：无 pm-detail 可见内容、无权限/路由行
2. 点「详情」→ 出现权限/路由/工具/依赖/面板/目录；再点 → 收起
3. 配置行：未展开一行、0 请求；点开 → 编辑器（**没有**大「收起」按钮）；点同一行 → 收起
4. 卡片整体高度对比：默认 vs 详情展开
5. 0 console error / 0 失败请求
"""
import os
import sys
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
    pg = b.new_context(viewport={"width": 1440, "height": 950}).new_page()
    errs, bad, cfg_calls = [], [], []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("requestfailed", lambda r: bad.append(r.url))
    pg.on("request", lambda r: cfg_calls.append(r.url) if "/api/plugins/" in r.url and "/config" in r.url else None)

    pg.goto(f"{BASE}/#settings", wait_until="networkidle", timeout=60000)
    pg.wait_for_selector("#settings-panel", timeout=30000)
    pg.click('[data-set-tab="plugins"]')
    pg.wait_for_selector('[data-plugin-card="weather"]', timeout=30000)
    pg.wait_for_timeout(1200)

    base = pg.evaluate("""() => {
        const card = document.querySelector('[data-plugin-card="weather"]');
        const detail = card.querySelector('.pm-detail');
        const row = card.querySelector('[data-plugin-detail]');
        return {
          cardHeight: Math.round(card.getBoundingClientRect().height),
          detailHidden: !!detail && detail.hidden,
          detailText: detail ? detail.innerText.trim().length : -1,
          rowText: row ? row.innerText.replace(/\\n/g,' ') : '',
          rowHeight: row ? Math.round(row.getBoundingClientRect().height) : -1,
          hasPermVisible: /net:http/.test(card.innerText),
        };
    }""")
    check("卡片默认只有一行「版本」", base["rowHeight"] > 0 and base["rowHeight"] <= 34, f"行高 {base['rowHeight']}px")
    check("默认不显示权限/路由（在详情里）", base["detailHidden"] and not base["hasPermVisible"], base["rowText"][:50])
    check("默认行文案是版本 + 详情", "1.0.0" in base["rowText"] and "详情" in base["rowText"], base["rowText"][:60])

    pg.click('[data-plugin-card="weather"] [data-plugin-detail]')
    pg.wait_for_timeout(400)
    opened = pg.evaluate("""() => {
        const card = document.querySelector('[data-plugin-card="weather"]');
        const detail = card.querySelector('.pm-detail');
        return {cardHeight: Math.round(card.getBoundingClientRect().height),
                detailHidden: detail.hidden, hasPerm: /net:http/.test(card.innerText),
                hasRoutes: /GET current/.test(card.innerText), hasDir: /plugins\\\\weather/.test(card.innerText),
                action: card.querySelector('[data-plugin-detail] .pm-row-action').textContent};
    }""")
    check("详情展开后显示权限/路由/目录", not opened["detailHidden"] and opened["hasPerm"] and opened["hasRoutes"] and opened["hasDir"],
          opened["action"])
    check("卡片变高（详情占位）", opened["cardHeight"] > base["cardHeight"], f"{base['cardHeight']} → {opened['cardHeight']}px")
    pg.click('[data-plugin-card="weather"] [data-plugin-detail]')
    pg.wait_for_timeout(300)
    again = pg.evaluate("""() => { const c = document.querySelector('[data-plugin-card="weather"]');
        return {hidden: c.querySelector('.pm-detail').hidden, h: Math.round(c.getBoundingClientRect().height)}; }""")
    check("再点一次收起详情", again["hidden"] and again["h"] == base["cardHeight"], f"{again['h']}px")

    # 配置行
    cfg0 = pg.evaluate("""() => {
        const box = document.querySelector('[data-plugin-card="weather"] .pm-config');
        const row = box.querySelector('[data-config-toggle]');
        return {h: Math.round(box.getBoundingClientRect().height), rowH: row ? Math.round(row.getBoundingClientRect().height) : -1,
                action: row ? row.querySelector('.pm-row-action').textContent : ''};
    }""")
    check("配置默认一行、动作是「读取并展开」", cfg0["rowH"] > 0 and cfg0["rowH"] <= 34 and "展开" in cfg0["action"],
          f"{cfg0['h']}px / {cfg0['action']}")
    check("未展开时不请求配置", len(cfg_calls) == 0, str(cfg_calls[:1]))

    pg.click('[data-plugin-card="weather"] [data-config-toggle]')
    pg.wait_for_selector('[data-plugin-card="weather"] [data-config-json]', timeout=20000)
    pg.wait_for_timeout(600)
    exp = pg.evaluate("""() => {
        const box = document.querySelector('[data-plugin-card="weather"] .pm-config');
        return {hasEditor: !!box.querySelector('[data-config-json]'),
                hasBigCollapse: !!box.querySelector('[data-config-close]'),
                action: box.querySelector('[data-config-toggle] .pm-row-action').textContent,
                buttons: Array.from(box.querySelectorAll('.pm-config-actions button')).map(b => b.innerText),
                h: Math.round(box.getBoundingClientRect().height)};
    }""")
    check("展开后出现编辑器", exp["hasEditor"], exp["action"])
    check("**没有**大的「收起」按钮（改为点同一行收起）", not exp["hasBigCollapse"] and exp["buttons"] == ["重新读取", "保存配置"],
          str(exp["buttons"]))
    check("展开态该行动作变成「收起」", "收起" in exp["action"], exp["action"])

    pg.click('[data-plugin-card="weather"] [data-config-toggle]')
    pg.wait_for_timeout(400)
    col = pg.evaluate("""() => {
        const box = document.querySelector('[data-plugin-card="weather"] .pm-config');
        return {hasEditor: !!box.querySelector('[data-config-json]'),
                rowH: Math.round(box.querySelector('[data-config-toggle]').getBoundingClientRect().height),
                summary: box.querySelector('.pm-row-main').textContent};
    }""")
    check("点同一行即收起，回到一行", not col["hasEditor"] and col["rowH"] <= 34, f"{col['rowH']}px")
    check("收起后摘要显示已读取的 JSON", "location" in col["summary"], col["summary"][:50])

    check("全程无 console error", not errs, str(errs[:2]))
    check("全程无失败请求", not bad, str(bad[:2]))
    b.close()

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（卡片与配置都默认一行；详情与配置点同一行展开/收起）")
