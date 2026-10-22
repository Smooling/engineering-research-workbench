"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
A10 验收：把「全局 window.fetch 猴子补丁」换成运行期接缝后，行为是否等价。

用真浏览器验证四条被中间件接管的路径 + 两条结构性断言：
1. 文档分页：pager 出现、点「下一页」后列表内容变化且页码前进（走 /api/docs 分页+拆封）
2. 图谱状态：/api/graph 的 meta 仍经事件流到 .perf-graph-status
3. 全局搜索：/api/search 仍可用（abort 路径）
4. 结构性断言：window.fetch 未被替换；window.erwFetch 存在
"""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8799"
EXE = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
FAILS: list[str] = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  · {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE if Path(EXE).is_file() else None, headless=True)
    pg = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
    errors: list[str] = []
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    docs_calls: list[str] = []
    pg.on("request", lambda r: docs_calls.append(r.url) if "/api/docs?" in r.url else None)

    pg.goto(f"{BASE}/#notes", wait_until="networkidle", timeout=30000)
    pg.wait_for_timeout(1000)

    # 4. 结构性断言
    check("window.fetch 未被替换",
          "workbenchPerformanceFetch" not in pg.evaluate("() => window.fetch.toString()"),
          pg.evaluate("() => window.fetch.toString()")[:50])
    check("window.erwFetch 接缝存在", pg.evaluate("() => typeof window.erwFetch === 'function'"))

    # 1. 分页
    pager_before = pg.eval_on_selector(".perf-doc-pager", "e => e.innerText") if pg.query_selector(".perf-doc-pager") else ""
    check("分页器已渲染", bool(pager_before), pager_before.replace("\n", " ")[:60])
    check("分页请求带 paged=1", any("paged=1" in u for u in docs_calls),
          next((u for u in docs_calls if "paged=1" in u), "")[-60:])
    first_before = pg.eval_on_selector("#doc-list", "e => e.innerText.slice(0,80)")
    advanced = False
    if pg.query_selector('[data-perf-page="next"]:not([disabled])'):
        pg.click('[data-perf-page="next"]')
        pg.wait_for_timeout(1200)
        first_after = pg.eval_on_selector("#doc-list", "e => e.innerText.slice(0,80)")
        advanced = first_after != first_before
        check("点「下一页」后列表内容变化", advanced, f"页码行={pg.eval_on_selector('.perf-doc-pager','e=>e.innerText').replace(chr(10),' ')[:40]}")
    else:
        check("存在可点的下一页按钮", False, pager_before.replace("\n", " ")[:60])

    # 2. 图谱状态
    pg.goto(f"{BASE}/#graph", wait_until="networkidle", timeout=30000)
    pg.wait_for_timeout(1800)
    status = pg.eval_on_selector(".perf-graph-status", "e => e.innerText") if pg.query_selector(".perf-graph-status") else ""
    check("图谱状态条出现（graphMeta 事件仍通）", "当前加载" in status, status.replace("\n", " ")[:60])

    # 3. 全局搜索
    pg.goto(f"{BASE}/#notes", wait_until="networkidle", timeout=30000)
    pg.wait_for_timeout(600)
    pg.evaluate("() => document.querySelector('#global-search-btn')?.click()")
    pg.wait_for_timeout(500)
    pg.fill("#global-search-input", "质心")
    pg.wait_for_timeout(1500)
    results = pg.eval_on_selector("#global-search-results", "e => e.innerText") if pg.query_selector("#global-search-results") else ""
    check("全局搜索返回结果", "质心" in results or len(results.strip()) > 10, results.replace("\n", " ")[:70])

    check("全程无 console error", not errors, str(errors[:2]))
    b.close()

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（A10 接缝化后行为等价）")
