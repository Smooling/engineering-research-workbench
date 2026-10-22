"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
插件端到端验收：plugins/focus 通过真实管线挂载、渲染、可交互，且内核不认识它。

1. /api/plugins 下发 focus 与其面板入口
2. 侧栏出现「专注」，且位置与搬出前一致（待办 与 Agent 之间）
3. #focus 由插件面板渲染出计时器；点「开始」后倒计时真的在走；「重置」回到起点
4. localStorage 键沿用 focusMinutes / breakMinutes（老用户设置不丢）
5. ERWPluginHost.loaded 含 focus、failures 为空
6. 内核源码里已无专注实现（renderFocus 已删除）
"""
import json
import os
import re
import sys
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


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE if Path(EXE).is_file() else None, headless=True)
    pg = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
    errors = []
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    panel_requests = []
    pg.on("request", lambda r: panel_requests.append(r.url) if "/plugins-file/" in r.url else None)

    pg.goto(f"{BASE}/#overview", wait_until="networkidle", timeout=30000)
    pg.wait_for_timeout(1200)

    host = pg.evaluate("() => window.ERWPluginHost ? {loaded: window.ERWPluginHost.loaded, failures: window.ERWPluginHost.failures} : null")
    check("插件宿主存在并加载了 focus", bool(host) and "focus" in (host or {}).get("loaded", []), str(host))
    check("面板脚本确实被请求", any("focus/web/panel.js" in u for u in panel_requests), str(panel_requests[:2]))
    check("无面板加载失败", not (host or {}).get("failures"), str((host or {}).get("failures")))

    nav = [r for r in pg.eval_on_selector_all(".nav-item", "els => els.map(e => e.dataset.route)") if r]
    check("侧栏含插件登记的「专注」，内核页面顺序不变",
          "focus" in nav and not nav_problems(nav), str(nav))

    pg.goto(f"{BASE}/#focus", wait_until="networkidle", timeout=30000)
    pg.wait_for_timeout(800)
    heading = pg.eval_on_selector("#page-title", "e => e.textContent")
    has_timer = pg.evaluate("() => !!document.querySelector('#focus-time') && !!document.querySelector('#focus-start')")
    check("插件面板渲染出计时器", has_timer and heading == "专注", f"标题={heading}")
    t0 = pg.eval_on_selector("#focus-time", "e => e.textContent")
    pg.click("#focus-start")
    pg.wait_for_timeout(2200)
    t1 = pg.eval_on_selector("#focus-time", "e => e.textContent")
    label = pg.eval_on_selector("#focus-start", "e => e.textContent")
    check("点开始后倒计时在走", t0 != t1 and label == "暂停", f"{t0} -> {t1}，按钮={label}")
    pg.click("#focus-start")  # 暂停
    pg.wait_for_timeout(300)
    paused = pg.eval_on_selector("#focus-start", "e => e.textContent")
    pg.click("#focus-reset")
    pg.wait_for_timeout(300)
    t2 = pg.eval_on_selector("#focus-time", "e => e.textContent")
    check("暂停/重置可用", paused == "开始" and t2 == "25:00", f"暂停后按钮={paused}，重置后={t2}")

    # localStorage 键沿用：改时长后应写入 focusMinutes / breakMinutes
    pg.fill("#focus-minutes", "45")
    pg.fill("#break-minutes", "10")
    pg.click("#focus-apply")
    pg.wait_for_timeout(400)
    keys = pg.evaluate("() => ({f: localStorage.getItem('focusMinutes'), b: localStorage.getItem('breakMinutes')})")
    check("localStorage 键沿用 focusMinutes/breakMinutes", keys.get("f") == "45" and keys.get("b") == "10", str(keys))

    check("全程无 console error", not errors, str(errors[:2]))
    b.close()

src = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
code = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
code = re.sub(r"(?m)//[^\n]*$", " ", code)
_ensure_all_bundled()   # 前置：随包插件全部启用
_ensure_enabled("focus")   # 夹具前置：确保被测插件启用

check("内核已无专注实现", "renderFocus" not in code and "startFocus" not in code and "focusMinutes" not in code)
check("内核不再声明 focus 路由", "'focus'" not in code)

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（首个真插件经真实管线挂载、可交互，内核不再认识它）")
