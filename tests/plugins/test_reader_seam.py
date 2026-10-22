# -*- coding: utf-8 -*-
"""阅读区接缝 `window.ERWReader` 的契约验收（真 Chrome，只读，不改用户设置）。

契约（app.js §6.3，v261009.13）：
  1. 有接管者时：`ERWReader.available()` 为真、文献列表页出现「PDF 阅读工作区」入口、点得开、
     `context()` 能给出当前文献上下文；
  2. **没有接管者时**（脚本被拦）：入口**不出现**，`ERWReader.open()` 抛一条能看懂的提示，
     文献列表页本身照常可用（这是「关掉插件就不给用阅读区」的核心性质）。
"""
import os
import re
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ERW_BASE", "http://127.0.0.1:8799")
# 阅读区已搬进 plugins/literature-reader/：拦它的 panel.js 即模拟「插件未启用/未加载」
BLOCK_READER = os.environ.get("ERW_BLOCK_READER", r".*/plugins-file/literature-reader/.*")

CANDIDATES = [
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
    for c in CANDIDATES:
        if Path(c).is_file():
            return c
    return shutil.which("chrome") or shutil.which("msedge")


def main():
    with sync_playwright() as p:
        exe = find_browser()
        kwargs = {"headless": True}
        if exe:
            kwargs["executable_path"] = exe
        browser = p.chromium.launch(**kwargs)

        # ---------- 1. 有接管者 ----------
        print("1) 有阅读区接管者")
        pg = browser.new_page(viewport={"width": 1440, "height": 900})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(f"{BASE}/#literature", wait_until="load")
        pg.wait_for_timeout(1500)
        info = pg.evaluate("""() => ({
            available: !!window.ERWReader?.available?.(),
            ids: (window.ERWReader?.list?.() || []).map(r => r.id),
            button: !!document.querySelector('#open-lit-workspace'),
            exportBib: !!document.querySelector('#export-bib'),
            listRows: document.querySelectorAll('[data-doc-id]').length,
        })""")
        check("接缝报告有接管者", info["available"], f"ids={info['ids']}")
        check("列表页出现阅读区入口", info["button"])
        check("内核导出 BibTeX 入口不受影响", info["exportBib"])
        check("文献列表本身可用", info["listRows"] > 0, f"行数={info['listRows']}")

        if info["button"]:
            pg.click("#open-lit-workspace")
            pg.wait_for_timeout(1500)
            shell = pg.evaluate("""() => ({ shell: !!document.querySelector('.lit-shell'), litApi: !!window.ERWLiterature })""")
            check("点入口能进阅读区（shell 渲染）", shell["shell"])
            # 工作区壳渲染后**还要打开一篇文献**才会出现右侧 tab 与上下文
            pg.wait_for_selector("[data-paper]", timeout=20000)
            pg.click("[data-paper]", timeout=15000)
            pg.wait_for_timeout(3000)
            shell = pg.evaluate("""() => ({
                tabs: [...document.querySelectorAll('#lit-side [data-tab]')].map(e => e.dataset.tab),
                pdfCanvas: document.querySelectorAll('canvas').length,
                ctx: window.ERWReader?.context?.() || null,
            })""")
            check("阅读区 tab 就绪", {"info", "annotations", "ai"} <= set(shell["tabs"]), f"tabs={shell['tabs']}")
            check("PDF 画布已渲染", shell["pdfCanvas"] > 0, f"canvas={shell['pdfCanvas']}")
            check("context() 接缝可用（悬浮球/笔记插件依赖它）",
                  bool(shell["ctx"] and shell["ctx"].get("paper_id")), f"ctx={str(shell['ctx'])[:80]}")
        check("有接管者时 0 console error", not errs, "; ".join(errs[:2]))
        pg.close()

        # ---------- 2. 无接管者：入口消失 + 明确提示 ----------
        print("2) 无接管者（阅读区脚本被拦）")
        pg2 = browser.new_page(viewport={"width": 1440, "height": 900})
        pg2.route(re.compile(BLOCK_READER), lambda route: route.abort())
        errs2 = []
        pg2.on("console", lambda m: errs2.append(m.text) if m.type == "error" else None)
        pg2.goto(f"{BASE}/#literature", wait_until="load")
        pg2.wait_for_timeout(1500)
        off = pg2.evaluate("""() => ({
            available: !!window.ERWReader?.available?.(),
            button: !!document.querySelector('#open-lit-workspace'),
            rows: document.querySelectorAll('[data-doc-id]').length,
            exportBib: !!document.querySelector('#export-bib'),
        })""")
        check("接缝报告无接管者", not off["available"])
        check("阅读区入口不出现", not off["button"])
        check("文献列表页照常可用（核心不依赖阅读区）", off["rows"] > 0 and off["exportBib"],
              f"行数={off['rows']} bib={off['exportBib']}")
        msg = pg2.evaluate("""async () => {
            try { await window.ERWReader.open(); return 'NO-THROW' } catch (e) { return String(e.message || e) }
        }""")
        check("无接管者时给明确提示（不是静默失败）", "阅读区不可用" in msg and "插件" in msg, msg)
        real_errs = [e for e in errs2 if "ERR_FAILED" not in e and "ERR_BLOCKED" not in e
                     and "literature-reader" not in e]   # 被拦插件自身引发的宿主诊断不算失败
        check("除被拦脚本外无 console error", not real_errs, "; ".join(real_errs[:2]))
        pg2.close()

        browser.close()

    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} 通过")
    for name, _, detail in bad:
        print(f"  - {name}  {detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
