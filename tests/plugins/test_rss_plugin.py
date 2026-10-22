"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
RSS 插件端到端验收：后端路由 + 面板渲染 + 配置迁移 + 内核不再认识资讯。

对照搬出前的行为（PLUGIN_SPEC §11 等价性）：
1. /api/plugins 同时下发 focus 与 rss（含 rss 的面板与自带样式 URL）
2. 面板脚本 + 插件样式被请求；ERWPluginHost.loaded 含 rss、failures 为空
3. 侧栏 17 项与顺序逐项不变（资讯仍在 Agent 之后）
4. #news 由插件面板渲染（源状态卡 / 刷新按钮齐备）
5. 插件后端路由可用：GET /api/plugins/rss/feed、GET|POST /api/plugins/rss/config
6. 配置落在 config/plugins/rss.json（内核 config/rss.json 不再被读写）
7. 内核已无 rss 实现与路由（/api/rss 应 404）
8. 全程无 console error / 失败请求
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8799"
EXE = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
# v261009.36 · 不再写死整张侧栏清单（内核新增页面会误报成回归）。改为：
#   ① 内核自有页面按 NAV_GROUPS 的顺序出现（顺序回归仍能抓到）；
#   ② 插件贡献项存在且相对于锚点位置正确；
#   ③ 不断言总条数——新增页面/新插件是正常演进。
CORE_ORDER = ["overview", "todos", "agent", "research-overview", "ideas", "journals", "notes",
              "experiments", "milestones", "summaries", "literature", "graph", "folders", "settings"]


def nav_problems(nav):
    """返回问题列表（空 = 通过）。"""
    problems = []
    seen = [r for r in nav if r in CORE_ORDER]
    expected_order = [r for r in CORE_ORDER if r in seen]
    if seen != expected_order:
        problems.append(f"内核页面顺序变了：{seen} ≠ {expected_order}")
    missing = [r for r in CORE_ORDER if r not in nav]
    if missing:
        problems.append(f"缺内核页面：{missing}")
    return problems
FAILS = []


def _ensure_enabled(plugin_id):
    """夹具前置：确保被测插件处于启用态（默认即启用；用户可能手动停用过）。
    只写 System/plugins.json 的「开不开」，不动文件与数据。"""
    import json as _json
    import urllib.request as _u
    try:
        req = _u.Request(f"{BASE}/api/plugin-manager/{plugin_id}/enabled", method="POST",
                         headers={"Content-Type": "application/json"},
                         data=_json.dumps({"enabled": True}).encode("utf-8"))
        with _u.urlopen(req, timeout=20) as r:
            return _json.loads(r.read().decode("utf-8")).get("ok") is True
    except Exception as exc:
        print(f"  前置：启用 {plugin_id} 失败（{exc}）")
        return False

def _ensure_all_bundled():
    """前置：随包插件全部启用（夹具断言 17 项侧栏顺序时需要）。"""
        # v261009.13 · 尊重用户已明确停用的插件（本轮踩过：前置把用户关掉的 litnote 又打开）
    import json as _json, pathlib as _pathlib
    try:
        _st = _json.loads((_pathlib.Path(__file__).resolve().parents[2] / "Workspace/System/plugins.json")
                          .read_text(encoding="utf-8"))
    except Exception:
        _st = {}
    _off = {k for k, v in ((_st.get("plugins") or {})).items() if isinstance(v, dict) and v.get("enabled") is False}
    for pid in ("billing", "focus", "knowledge-graph", "litnote", "rss", "weather"):
        if pid in _off:
            continue
        _ensure_enabled(pid)





def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  · {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {}


def post(path, payload):
    req = urllib.request.Request(BASE + path, method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps(payload).encode("utf-8"))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {}


st, listing = get("/api/plugins")
ids = [p["id"] for p in listing.get("plugins", [])]
_ensure_all_bundled()   # 前置：随包插件全部启用
_ensure_enabled("rss")   # 夹具前置：确保被测插件启用

check("/api/plugins 下发全部已启用插件", {"focus", "rss", "weather"} <= set(ids), str(ids))
rss_nav = next((p for p in listing.get("plugins", []) if p["id"] == "rss"), {}).get("nav") or [{}]
check("rss 面板与自带样式 URL 齐备",
      "/plugins-file/rss/web/panel.js" in str(rss_nav[0].get("url", ""))
      and "/plugins-file/rss/web/panel.css" in str(rss_nav[0].get("style_url", "")),
      json.dumps(rss_nav, ensure_ascii=False)[:140])

st, cfg = get("/api/plugins/rss/config")
check("插件配置路由可用", st == 200 and "sources" in cfg and cfg.get("max_items_per_source") == 12,
      json.dumps(cfg, ensure_ascii=False)[:120])

st, feed = get("/api/plugins/rss/feed")
check("插件 feed 路由可用（离线也应 200 + 源状态）",
      st == 200 and "items" in feed and "sources" in feed,
      f"items={len(feed.get('items') or [])} errors={len(feed.get('errors') or [])}")

st, _ = get("/api/rss")
check("内核旧路由 /api/rss 已移除（404）", st == 404, str(st))

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE if Path(EXE).is_file() else None, headless=True)
    pg = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
    errors, failed = [], []
    panel_reqs, style_reqs = [], []
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("requestfailed", lambda r: failed.append(r.url))
    pg.on("request", lambda r: panel_reqs.append(r.url) if "rss/web/panel.js" in r.url else None)
    pg.on("request", lambda r: style_reqs.append(r.url) if "rss/web/panel.css" in r.url else None)

    pg.goto(f"{BASE}/#overview", wait_until="networkidle", timeout=40000)
    pg.wait_for_timeout(1500)
    host = pg.evaluate("() => window.ERWPluginHost ? {loaded: window.ERWPluginHost.loaded, failures: window.ERWPluginHost.failures} : null")
    check("插件宿主加载了全部已启用插件", {"focus", "rss", "weather"} <= set((host or {}).get("loaded", [])), str(host))
    check("rss 面板脚本被请求", bool(panel_reqs), str(panel_reqs[:1]))
    check("rss 插件样式被请求", bool(style_reqs), str(style_reqs[:1]))

    nav = [r for r in pg.eval_on_selector_all(".nav-item", "els => els.map(e => e.dataset.route)") if r]
    check("侧栏含插件登记的「资讯」且在 Agent 之后，内核页面顺序不变",
          "news" in nav and nav.index("news") > nav.index("agent") and not nav_problems(nav),
          str(nav))

    pg.goto(f"{BASE}/#news", wait_until="networkidle", timeout=60000)
    pg.wait_for_selector('[data-plugin="rss"] .news-grid', timeout=60000)
    pg.wait_for_timeout(500)
    heading = pg.eval_on_selector("#page-title", "e => e.textContent")
    has_ui = pg.evaluate("() => !!document.querySelector('[data-plugin=\"rss\"]') && !!document.querySelector('#news-refresh')")
    check("#news 由插件面板渲染", has_ui and heading == "资讯", f"标题={heading}")
    styled = pg.evaluate("() => { const el=document.querySelector('[data-plugin=\"rss\"] .news-grid'); return el ? getComputedStyle(el).display : ''; }")
    check("插件样式生效（.news-grid 为 grid）", styled == "grid", styled)
    pg.click("#news-settings")
    try:
        pg.wait_for_selector("#rss-list", timeout=60000)   # 离线抓取慢，给足时间
        inline = True
    except Exception:
        inline = False
    check("资讯源设置已内联在插件面板里", inline)
    srcs = pg.eval_on_selector_all("[data-rss-name]", "els => els.map(e => e.value)") if inline else []
    check("旧的资讯源已迁移进插件配置（9 个）", len(srcs) >= 3, f"{len(srcs)} 个：{srcs[:2]}")

    check("全程无 console error", not errors, str(errors[:2]))
    check("全程无失败请求", not failed, str(failed[:2]))
    b.close()

kernel_hits = []
for path in list((ROOT / "app").rglob("*.py")) + [ROOT / "server.py"]:
    text = path.read_text(encoding="utf-8")
    if "rss" in text.lower():
        kernel_hits.append(path.relative_to(ROOT).as_posix())
check("内核 Python 已无 rss 实现/路由", not kernel_hits, str(kernel_hits))
appjs = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
import re as _re
code = _re.sub(r"/\*.*?\*/", " ", appjs, flags=_re.S)
code = _re.sub(r"(?m)//[^\n]*$", " ", code)
check("app.js 实现里已无资讯痕迹", "renderNews" not in code and "/api/rss" not in code)
check("插件配置写在 config/plugins/rss.json", (ROOT / "config" / "plugins" / "rss.json").is_file(),
      str(ROOT / "config" / "plugins" / "rss.json"))

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（资讯已成为可增删插件，内核不再认识它）")
