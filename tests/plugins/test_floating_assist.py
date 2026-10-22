# -*- coding: utf-8 -*-
"""悬浮球 AI 助手插件（plugins/floating-assist）验收（真 Chrome，不截图）。

验的性质：悬浮球及其全部附属 UI 随插件启停——启用时悬浮球挂在**内核浮层槽位**里、
面板/关联知识/人设编辑器可用；停用时悬浮球与设置页人设 tab 一起消失，且**内核不报错**
（内核只在有 `window.ERWFabTimeline` 时渲染工具轨迹块）。
"""
import os
import re
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ERW_BASE", "http://127.0.0.1:8799")
BLOCK = os.environ.get("ERW_BLOCK_FAB", r".*/plugins-file/floating-assist/.*")
CANDS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("  [OK]   " if ok else "  [FAIL] ") + name + ("  " + detail if detail else ""))


def find_browser():
    env = os.environ.get("ERW_BROWSER") or os.environ.get("CHROME_PATH")
    if env and Path(env).is_file():
        return env
    for c in CANDS:
        if Path(c).is_file():
            return c
    return shutil.which("chrome") or shutil.which("msedge")


SNAP = """
() => {
  const ball = document.querySelector('#erw-fab-ball');
  const host = document.querySelector('[data-erw-slot="overlay"]');
  return {
    ball: !!ball,
    ballInSlot: !!(ball && host && host.contains(ball)),
    ballInBody: !!(ball && ball.parentElement === document.body),
    timeline: typeof window.ERWFabTimeline,
    toast: typeof window.ERWToast,
    home: typeof window.ERWHome,
    personaHost: !!document.querySelector('#erw-persona-host'),
  };
}
"""


def settings_persona_tab(pg):
    """设置页是否有人设 tab；有则点开并看是否渲染出编辑器。"""
    pg.goto(f"{BASE}/#settings", wait_until="load")
    pg.wait_for_timeout(1200)
    pg.evaluate("""() => {
      const tab = [...document.querySelectorAll('[data-set-tab]')].find(b => b.dataset.setTab === 'llm');
      if (tab) tab.click();
    }""")
    pg.wait_for_timeout(1500)
    tabs = pg.evaluate("() => [...document.querySelectorAll('[data-set-tab]')].map(b => b.dataset.setTab)")
    has = "personas" in tabs
    if has:
        pg.evaluate("""() => {
          const t = [...document.querySelectorAll('[data-set-tab]')].find(b => b.dataset.setTab === 'personas');
          if (t) t.click();
        }""")
        pg.wait_for_timeout(1500)
    rendered = pg.evaluate("""() => ({
      rows: document.querySelectorAll('[data-pe-row]').length,
      save: !!document.querySelector('#pe-save'),
      kicker: (document.body.innerText || '').includes('AI 助手人设'),
    })""")
    return tabs, has, rendered


def main():
    with sync_playwright() as p:
        exe = find_browser()
        kw = {"headless": True}
        if exe:
            kw["executable_path"] = exe
        browser = p.chromium.launch(**kw)

        # ---------- 1. 启用 ----------
        print("1) 启用悬浮球插件")
        pg = browser.new_page(viewport={"width": 1440, "height": 900})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(f"{BASE}/#overview", wait_until="load")
        pg.wait_for_timeout(2000)
        st = pg.evaluate(SNAP)
        check("悬浮球存在", st["ball"])
        check("悬浮球挂在内核浮层槽位里（不是直接塞 body）", st["ballInSlot"] and not st["ballInBody"],
              f"inSlot={st['ballInSlot']} inBody={st['ballInBody']}")
        check("ERWFabTimeline 已提供（Agent 消息的工具轨迹块）", st["timeline"] == "object", st["timeline"])
        check("ERWToast 由内核提供", st["toast"] == "function", st["toast"])

        pg.click("#erw-fab-ball")
        pg.wait_for_timeout(1200)
        panel = pg.evaluate("""() => {
          const p = document.querySelector('#erw-fab-panel');
          return {
            open: !!p && !p.hidden,
            related: !!document.querySelector('#fab-related'),
            persona: !!document.querySelector('#fab-persona'),
            direct: !!document.querySelector('#fab-write-direct'),
            history: !!document.querySelector('#fab-history'),
            shot: !!document.querySelector('#fab-shot-page'),
          };
        }""")
        check("点悬浮球打开面板", panel["open"])
        check("面板含本页关联知识宿主", panel["related"])
        check("面板含人设下拉 / 写模式开关 / 历史 / 截图入口",
              all([panel["persona"], panel["direct"], panel["history"], panel["shot"]]), str(panel))

        tabs, has_tab, rendered = settings_persona_tab(pg)
        check("设置页出现「AI 助手人设」tab（由插件贡献）", has_tab, f"tabs={tabs}")
        check("人设编辑器渲染出内容", rendered["save"] or rendered["rows"] > 0, str(rendered))
        check("启用态无 console error", not errs, "; ".join(errs[:2]))
        pg.close()

        # ---------- 2. 停用（脚本被拦） ----------
        print("2) 停用悬浮球插件（脚本被拦）")
        pg2 = browser.new_page(viewport={"width": 1440, "height": 900})
        pg2.route(re.compile(BLOCK), lambda route: route.abort())
        errs2 = []
        pg2.on("console", lambda m: errs2.append(m.text) if m.type == "error" else None)
        pg2.goto(f"{BASE}/#overview", wait_until="load")
        pg2.wait_for_timeout(1800)
        off = pg2.evaluate(SNAP)
        check("停用后没有悬浮球", not off["ball"])
        check("停用后 ERWFabTimeline 不存在（内核走空值保护）", off["timeline"] == "undefined", off["timeline"])
        check("停用后内核仍提供 ERWToast", off["toast"] == "function", off["toast"])
        tabs2, has_tab2, _ = settings_persona_tab(pg2)
        check("停用后设置页没有人设 tab", not has_tab2, f"tabs={tabs2}")
        check("停用后没有人设宿主残留", not pg2.evaluate("() => !!document.querySelector('#erw-persona-host')"))
        real = [e for e in errs2 if "ERR_FAILED" not in e and "ERR_BLOCKED" not in e and "floating-assist" not in e]
        check("除被拦插件脚本外无 console error", not real, "; ".join(real[:2]))
        pg2.close()

        browser.close()

    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} 通过")
    for name, _, detail in bad:
        print(f"  - {name}  {detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
