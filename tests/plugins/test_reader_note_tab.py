"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
文献笔记「编辑界面」验收（SCOPE §2.2 的另一半）。

1. 阅读区 tab 由内核（信息/批注/AI）+ 插件（笔记）共同组成
2. 打开真实 PDF 后，插件贡献的「笔记」tab 在，点开出现编辑器（不是内核代码渲染的）
3. 读到的正文与核心路由一致；保存后核心路由也能读到（同一份数据）
4. 「AI 整理」把内容交给阅读器的 AI tab（内核能力由插件经上下文调用）
5. 插件停用 → 「笔记」tab 消失（优雅退化），阅读器其余 tab 不受影响
6. 内核已无 note()/saveNote()/笔记 tab 实现
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8799"
EXE = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  · {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def get(path, timeout=30):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload, timeout=30):
    req = urllib.request.Request(BASE + path, method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps(payload).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _user_plugin_state():
    """用户当前在设置里的启停选择（夹具只读它，不覆盖用户的选择）。"""
    try:
        return (json.loads((ROOT / "Workspace" / "System" / "plugins.json").read_text(encoding="utf-8")).get("plugins") or {})
    except Exception:
        return {}


READER_WAS_ENABLED = (_user_plugin_state().get("literature-reader") or {}).get("enabled", True)


def ensure_all():
    # v261009.13 · 尊重用户已明确停用的插件（本轮踩过：前置把用户关掉的插件又打开）。
    # v261009.17 · 文献笔记/阅读区 AI 已并入「文献阅读工作区」：本夹具的主题插件就是它。
    _off = {k for k, v in _user_plugin_state().items() if isinstance(v, dict) and v.get("enabled") is False}
    # 主题插件（文献阅读工作区）必须开着——它现在同时提供阅读区 + 笔记 tab + AI tab
    if (_user_plugin_state().get("literature-reader") or {}).get("enabled") is False or \
            not _user_plugin_state().get("literature-reader"):
        post("/api/plugin-manager/literature-reader/enabled", {"enabled": True})
    for pid in ("billing", "floating-assist", "focus", "knowledge-graph", "rss", "weather"):
        if pid in _off:   # 其它插件：用户停用的就不强开
            continue
        try:
            post(f"/api/plugin-manager/{pid}/enabled", {"enabled": True})
        except Exception as exc:
            print(f"  前置：启用 {pid} 失败（{exc}）")


ensure_all()

print("== 1. 插件面板与 route ==")
tools = {t["name"] for t in get("/api/agent/tools")}
check("文献工具仍在（插件工具包未受影响）", "p_literature-reader__context" in tools)
lit = get("/api/literature?page_size=1")
items = lit.get("items") or []
check("文献库有可打开的条目", bool(items), f"{len(items)} 条")
paper_id = items[0]["id"] if items else ""
core_note = ""
if paper_id:
    core_note = get(f"/api/literature/{paper_id}/note").get("content", "")
    plug_note = get(f"/api/plugins/literature-reader/note?paper_id={paper_id}").get("content", "")
    check("插件路由与核心路由读到同一份笔记", plug_note == core_note, f"{len(core_note)} 字")

print("\n== 2. 浏览器：阅读区 tab ==")
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE if Path(EXE).is_file() else None, headless=True)
    pg = b.new_context(viewport={"width": 1500, "height": 950}).new_page()
    errs, bad, bad_status = [], [], []
    ai_ok = True   # LLM 可用性（配额用尽时置 False：那条 4xx 属环境原因，不计入闸门）
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("requestfailed", lambda r: bad.append(r.url))
    # 记下 4xx/5xx 的 URL：只报「有 console error」而不给 URL 无法定位（本轮踩过）
    pg.on("response", lambda r: bad_status.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    pg.goto(f"{BASE}/#literature", wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(1500)
    # 阅读器入口：window.ERWLiterature.start()（库里选一篇 → 打开 PDF）
    pg.evaluate("() => window.ERWLiterature && window.ERWLiterature.start()")
    opened = False
    try:
        pg.wait_for_selector("[data-paper]", timeout=20000)
        pg.click("[data-paper]", timeout=8000)
        opened = True
    except Exception as exc:
        print("  打开文献失败：", str(exc)[:70])
    pg.wait_for_timeout(3500)
    check("文献阅读器已打开", opened and bool(pg.query_selector("#lit-side")))
    # PDF 真的渲染出来了（证明本地 PDF.js 生效，而不是只打开了空壳）
    pdf = pg.evaluate("""() => ({
        canvases: document.querySelectorAll('#lit-pages canvas').length,
        pagesText: ((document.querySelector('#lit-pages') || {}).innerText || '').slice(0, 60),
        pdfjsLocal: !!window.__pdfjsLocal,
        lib: !!(window.pdfjsLib && window.pdfjsLib.version),
        version: window.pdfjsLib ? window.pdfjsLib.version : '',
    })""")
    check("PDF.js 从本地 vendor 加载（不依赖 CDN）", pdf["pdfjsLocal"] and pdf["lib"], str(pdf))
    check("PDF 渲染出画布", pdf["canvases"] > 0, f"{pdf['canvases']} 个 canvas；页面区文本：{pdf['pagesText'][:40]}")
    tabs = pg.evaluate("() => Array.from(document.querySelectorAll('#lit-side [data-tab]')).map(e => e.dataset.tab)")
    check("阅读区 tab 行存在", bool(tabs), str(tabs))
    check("内核 tab 仍在（信息/批注/AI）", {"info", "annotations", "ai"} <= set(tabs), str(tabs))
    check("插件贡献的「笔记」tab 出现", "notes" in tabs, str(tabs))

    if "notes" in tabs:
        pg.click('#lit-side [data-tab="notes"]')
        pg.wait_for_selector("[data-ln-note]", timeout=20000)
        pg.wait_for_timeout(600)
        info = pg.evaluate("""() => {
            const ta = document.querySelector('[data-ln-note]');
            return {hasTa: !!ta, value: ta ? ta.value.length : -1,
                    hasImg: !!document.querySelector('[data-ln-img]'),
                    hasAi: !!document.querySelector('[data-ln-ai]'),
                    hasSave: !!document.querySelector('[data-ln-save]')};
        }""")
        check("插件渲染出笔记编辑器（textarea + 插入图片 + AI 整理 + 保存）",
              info["hasTa"] and info["hasImg"] and info["hasAi"] and info["hasSave"], str(info))
        check("编辑器载入了现有笔记正文", info["value"] == len(core_note), f"{info['value']} 字 / 核心 {len(core_note)} 字")
        # 保存一次（加一行再还原）
        marker = "\n\n<!-- 验收标记 -->\n"
        pg.fill("[data-ln-note]", core_note + marker)
        pg.click("[data-ln-save]")
        pg.wait_for_timeout(1500)
        saved = get(f"/api/literature/{paper_id}/note").get("content", "")
        check("「保存笔记」经插件路由写进同一份正文", "验收标记" in saved, f"{len(saved)} 字")
        if paper_id:
            post(f"/api/plugins/literature-reader/note", {"paper_id": paper_id, "content": core_note})
        check("验收后已还原", get(f"/api/literature/{paper_id}/note").get("content", "") == core_note)
        # AI 整理：把内容交给阅读器的 AI tab。
        # 先探测一次 assist：LLM 配额用尽（上游 429 → 内核 400）时**跳过**这一步并说明，
        # 否则环境条件会被误报成迁移回归（本轮真遇到：配额到 13:59:58 才重置）。
        ai_ok, ai_why = True, ""
        try:
            post("/api/agent/assist", {"action": "polish", "text": "探测"})
        except Exception as exc:
            msg = str(exc)
            ai_ok = False
            ai_why = ("配额/环境原因跳过：" + msg[:120])
        if ai_ok:
            pg.click("[data-ln-ai]")
            pg.wait_for_timeout(1200)
            ai = pg.evaluate("""() => {
                const active = document.querySelector('#lit-side [data-tab].active');
                const body = document.querySelector('#lit-side-body');
                return {tab: active ? active.dataset.tab : '', text: body ? body.innerText.slice(0, 60) : ''};
            }""")
            check("「AI 整理」切到阅读器的 AI tab（内核能力由插件经上下文调用）", ai["tab"] == "ai", str(ai))
        else:
            # 仍要验证 tab 切换（不依赖 LLM）：点「笔记」tab 的 AI 整理应把面板切到 ai
            pg.click("[data-ln-ai]")
            pg.wait_for_timeout(800)
            ai = pg.evaluate("""() => (document.querySelector('#lit-side [data-tab].active')||{}).dataset?.tab || ''""")
            check("「AI 整理」仍切到 AI tab（LLM 不可用时也切）", ai == "ai", f"tab={ai}｜{ai_why}")
            print(f"  SKIP LLM 调用断言：{ai_why}")

    # 环境原因（LLM 配额）导致的 assist 4xx 不计入闸门，但要在输出里点名
    errs_judged = [e for e in errs if not (not ai_ok and "400" in e)]
    status_judged = [s for s in bad_status if not (not ai_ok and "/api/agent/assist" in s)]
    if not ai_ok:
        print("  说明：LLM 配额用尽，已把 /api/agent/assist 的 400 排除在闸门之外")
    check("全程无 console error", not errs_judged,
          str(errs_judged[:2]) + ("｜4xx: " + str(status_judged[:3]) if status_judged else ""))
    check("全程无失败请求", not bad, str(bad[:2]))
    check("全程无 4xx/5xx 响应", not status_judged, str(status_judged[:3]))

    print("\n== 3. 三块能力同属一个插件：先断言都在，再停用整块 ==")
    merged = pg.evaluate("""() => ({
        avail: !!window.ERWReader?.available?.(),
        readerTab: [...document.querySelectorAll('#lit-side [data-tab]')].map(e => e.dataset.tab),
        ai: window.ERWReaderAssist?.get?.()?.tabId || '',
    })""")
    check("合并后三块能力都在同一插件里（阅读区 + 笔记 tab + AI tab）",
          merged["avail"] and {"info", "annotations", "notes", "ai"} <= set(merged["readerTab"]) and merged["ai"] == "ai",
          str(merged))
    post("/api/plugin-manager/literature-reader/enabled", {"enabled": False})
    pg.reload(wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(2500)
    pg.goto(f"{BASE}/#literature", wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(2000)
    off = pg.evaluate("""() => ({
        avail: !!window.ERWReader?.available?.(),
        entry: !!document.querySelector('#open-lit-workspace'),
        rows: document.querySelectorAll('[data-doc-id]').length,
        tabs: [...document.querySelectorAll('#lit-side [data-tab]')].map(e => e.dataset.tab),
    })""")
    check("停用后阅读区不可用（无接管者、入口不出现）", not off["avail"] and not off["entry"], str(off))
    check("停用后没有残留的阅读区 tab", not off["tabs"], str(off["tabs"]))
    check("停用后文献列表页照常可用", off["rows"] > 0, f"行数={off['rows']}")
    post("/api/plugin-manager/literature-reader/enabled", {"enabled": bool(READER_WAS_ENABLED)})
    b.close()

print("\n== 4. 内核已无笔记 tab 实现；阅读区已整体搬进插件 ==")
reader = ROOT / "plugins" / "literature-reader" / "web" / "panel.js"
litjs = reader.read_text(encoding="utf-8")
check("阅读区（插件）无 note()/saveNote()/uploadNoteImage 实现",
      "async function note(" not in litjs and "function saveNote(" not in litjs
      and "uploadNoteImage" not in litjs)
check("阅读区仍保留 insertAtCursor（批注加入笔记等核心流程用）", "function insertAtCursor(" in litjs)
check("阅读区不再硬编码 data-tab=\"notes\"", 'data-tab="notes"' not in litjs)
check("合并后的插件声明了两个 readerTab（笔记 + AI）",
      (ROOT / "plugins" / "literature-reader" / "web" / "panel.js").read_text(encoding="utf-8").count("readerTab") >= 2)
check("阅读区已搬出内核（web/literature.js 与 literature.css 都不在了）",
      not (ROOT / "web" / "literature.js").exists() and not (ROOT / "web" / "literature.css").exists())
check("阅读区走阅读接管接缝注册（ERWReader）", "ERWReader" in litjs and "literature-reader" in litjs)

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（文献笔记的编辑界面已由插件提供；阅读器只提供扩展点）")
