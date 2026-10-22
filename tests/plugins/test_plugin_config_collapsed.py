"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
验收：插件配置区默认收成**一行**，需要改再展开。

1. 默认态：配置区高度≈一行（≤34px），**没有** textarea，也没有发起配置请求
2. 展开：点一下 → 拉取配置、出现 JSON 编辑器、显示内容
3. 收起：再点「收起」→ 回到一行，且摘要变成单行 JSON（说明已读取）
4. 保存：改一个值保存 → 落盘、**自动收回一行**、摘要反映新值
5. 无配置接口的插件（focus）本来就是一行说明
6. 0 console error / 0 失败请求
"""
import json
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

    state = pg.evaluate("""() => {
        const box = document.querySelector('[data-plugin-card="weather"] .pm-config');
        const toggle = box.querySelector('[data-config-toggle]');
        const r = box.getBoundingClientRect();
        return {
          hasToggle: !!toggle,
          height: Math.round(r.height),
          hasTextarea: !!box.querySelector('[data-config-json]'),
          summary: (box.querySelector('.pm-row-main') || {}).textContent || '',
          hint: (box.querySelector('.pm-row-action') || {}).textContent || '',
          toggleHeight: toggle ? Math.round(toggle.getBoundingClientRect().height) : -1,
        };
    }""")
    check("默认态：配置区只有一个可点的一行", state["hasToggle"] and not state["hasTextarea"], json.dumps(state, ensure_ascii=False))
    check("默认态：只有一行（行高≤34px，整块只多出区块内边距）",
          0 < state["toggleHeight"] <= 34 and 0 <= state["height"] - state["toggleHeight"] <= 14,
          f"整块 {state['height']}px = 行 {state['toggleHeight']}px + 内边距 {state['height'] - state['toggleHeight']}px")
    check("默认态：尚未拉取配置（摘要提示展开后读取）", "展开后读取" in state["summary"], state["summary"][:40])
    check("默认态：没有发起配置请求", len(cfg_calls) == 0, str(cfg_calls[:2]))

    # 展开
    pg.click('[data-plugin-card="weather"] [data-config-toggle]')
    pg.wait_for_selector('[data-plugin-card="weather"] [data-config-json]', timeout=20000)
    pg.wait_for_timeout(700)
    opened = pg.evaluate("""() => {
        const box = document.querySelector('[data-plugin-card="weather"] .pm-config');
        const ta = box.querySelector('[data-config-json]');
        return {height: Math.round(box.getBoundingClientRect().height), value: ta.value.slice(0, 60),
                hasButtons: !!box.querySelector('[data-config-save]') && !!box.querySelector('[data-config-reload]')};
    }""")
    check("展开：出现编辑器与按钮", opened["hasButtons"] and "location" in opened["value"], opened["value"].replace("\n", " ")[:50])
    check("展开：高度明显变大（>150px）", opened["height"] > 150, f"{opened['height']}px")
    check("展开：这次才请求配置", len(cfg_calls) >= 1, str(cfg_calls[-1:]))

    # 收起
    # v261009.7 · 收起改为点同一行（大「收起」按钮已去掉）
    pg.click('[data-plugin-card="weather"] [data-config-toggle]')
    pg.wait_for_timeout(500)
    closed = pg.evaluate("""() => {
        const box = document.querySelector('[data-plugin-card="weather"] .pm-config');
        return {height: Math.round(box.getBoundingClientRect().height),
                hasTextarea: !!box.querySelector('[data-config-json]'),
                summary: (box.querySelector('.pm-row-main') || {}).textContent || ''};
    }""")
    check("收起：回到一行且编辑器消失", 0 < closed["height"] <= 45 and not closed["hasTextarea"],
          f"整块 {closed['height']}px（= 一行 31px + 区块内边距）")
    check("收起：摘要变成单行 JSON（已读取）", "location" in closed["summary"], closed["summary"][:60])

    # 保存（改一个值）→ 自动收起
    pg.click('[data-plugin-card="weather"] [data-config-toggle]')
    pg.wait_for_selector('[data-plugin-card="weather"] [data-config-json]', timeout=20000)
    pg.wait_for_timeout(400)
    original = json.loads(pg.eval_on_selector('[data-plugin-card="weather"] [data-config-json]', "e => e.value"))
    edited = dict(original)
    edited["timezone"] = "Asia/Tokyo"
    pg.fill('[data-plugin-card="weather"] [data-config-json]', json.dumps(edited, ensure_ascii=False, indent=2))
    pg.click('[data-plugin-card="weather"] [data-config-save]')
    pg.wait_for_timeout(2200)
    after = pg.evaluate("""() => {
        const box = document.querySelector('[data-plugin-card="weather"] .pm-config');
        return {height: Math.round(box.getBoundingClientRect().height),
                hasTextarea: !!box.querySelector('[data-config-json]'),
                summary: (box.querySelector('.pm-row-main') || {}).textContent || ''};
    }""")
    check("保存后自动收回一行", 0 < after["height"] <= 45 and not after["hasTextarea"],
          f"整块 {after['height']}px（= 一行 31px + 区块内边距）")
    check("摘要反映新值", "Tokyo" in after["summary"], after["summary"][:80])
    saved = pg.evaluate("""async () => (await (window.erwFetch||fetch)('/api/plugins/weather/config')).json()""")
    check("确实落盘", saved.get("timezone") == "Asia/Tokyo", json.dumps(saved, ensure_ascii=False)[:80])
    # 还原
    pg.evaluate("""async (cfg) => { await (window.erwFetch||fetch)('/api/plugins/weather/config',
        {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(cfg)}); }""", original)

    focus = pg.evaluate("""() => {
        const box = document.querySelector('[data-plugin-card="focus"] .pm-config');
        return {height: Math.round(box.getBoundingClientRect().height), text: box.innerText.replace(/\\n/g,' ').slice(0,80)};
    }""")
    check("无配置接口的插件本来就是一行", 0 < focus["height"] <= 45 and "界面里" in focus["text"], json.dumps(focus, ensure_ascii=False))

    check("全程无 console error", not errs, str(errs[:2]))
    check("全程无失败请求", not bad, str(bad[:2]))
    b.close()

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（插件配置默认一条目，需要修改再展开）")
