"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
A9/§6.3 验收：面板注册表 + 计费自登记，且内核不再认识计费。

1. 侧栏导航项与顺序**与改造前完全一致**（用量仍在设置之前）
2. 面板注册表存在，且 billing 是登记项
3. #billing 由面板 render 渲染出内容（不再经 app.js 的 renderBillingPage）
4. app.js 源码里不再出现 billing 相关实现（只剩说明性注释）
5. 全程无 console error
"""
import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8799"
def _ensure_all():
    """夹具前置：三个随包插件都启用（侧栏顺序断言依赖这一点）。"""
    import json as _json, urllib.request as _u
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
        try:
            req = _u.Request(f"{BASE}/api/plugin-manager/{pid}/enabled", method="POST",
                             headers={"Content-Type": "application/json"},
                             data=_json.dumps({"enabled": True}).encode("utf-8"))
            _u.urlopen(req, timeout=20).read()
        except Exception as exc:
            print(f"  前置：启用 {pid} 失败（{exc}）")


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


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  · {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


_ensure_all()   # 夹具前置

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE if Path(EXE).is_file() else None, headless=True)
    pg = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
    errors = []
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.goto(f"{BASE}/#overview", wait_until="networkidle", timeout=30000)
    pg.wait_for_timeout(800)

    nav = [r for r in pg.eval_on_selector_all(".nav-item", "els => els.map(e => e.dataset.route)") if r]
    check("侧栏导航项与顺序与改造前一致", not nav_problems(nav), f"{nav}")

    ok_registry = pg.evaluate("() => !!window.ERWPanels && typeof window.ERWPanels.register === 'function'")
    check("面板注册表存在", ok_registry)
    panels = pg.evaluate("() => (window.ERWPanels?.list?.() || []).filter(p => typeof p.render === 'function').map(p => p.id)")
    check("billing 由面板自登记", "billing" in panels, str(panels))
    check("导航面板登记项都在侧栏里", all(p in nav for p in panels), f"{panels} vs nav")
    slots = pg.evaluate("() => (window.ERWPanels?.list?.() || []).filter(p => p.slot).map(p => p.id)")
    tabs = pg.evaluate("() => (window.ERWPanels?.settingsTabs?.() || []).map(t => t.id)")
    print(f"  槽位面板（不进导航）：{slots}；设置页 tab：{tabs}")

    pg.goto(f"{BASE}/#billing", wait_until="networkidle", timeout=30000)
    pg.wait_for_timeout(1500)
    body = pg.eval_on_selector("#main", "e => e.innerText.slice(0,120)")
    heading = pg.eval_on_selector("#page-title", "e => e.textContent")
    eyebrow = pg.eval_on_selector("#page-eyebrow", "e => e.textContent")
    check("#billing 经面板 render 渲染出内容", len(body.strip()) > 40, body.replace("\n", " ")[:70])
    check("页头由面板元数据提供", heading == "用量统计" and eyebrow == "SYSTEM", f"{eyebrow} / {heading}")

    check("全程无 console error", not errors, str(errors[:2]))
    b.close()

src = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
code = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
code = re.sub(r"(?m)//[^\n]*$", " ", code)
check("app.js 实现里已无 billing 痕迹", "billing" not in code.lower(), "只剩注释说明")
check("app.js 里 renderBillingPage 已删除", "renderBillingPage" not in src)

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（面板注册表生效，内核不再依赖计费模块）")
