"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
天气插件端到端验收：顶栏槽位 + 设置模态 + 配置迁移 + 内核不再认识天气。

1. /api/plugins 下发 weather（槽位面板，带 panel/style URL）
2. 顶栏槽位容器存在，且里面画出了插件自己的 [data-plugin="weather"] 卡片
3. 插件样式生效（status-dot 为 7px 圆点）
4. 点卡片弹出插件自己的设置模态（地点/经纬度/时区/启用 + 搜索坐标 + 保存并刷新）
5. 设置已从内核 app.json 的 weather 段迁移进 config/plugins/weather.json
6. 保存改动能落盘；插件路由 /current /config 可用；离线时降级不报 500
7. 内核：/api/weather 404、app/*.py 无 weather、index.html 只剩槽位没有硬编码卡片
8. 全程 0 console error / 0 失败请求
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
        with urllib.request.urlopen(BASE + path, timeout=25) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {}


def post(path, payload):
    req = urllib.request.Request(BASE + path, method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps(payload).encode("utf-8"))
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {}


st, listing = get("/api/plugins")
weather = next((p for p in listing.get("plugins", []) if p["id"] == "weather"), None)
_ensure_all_bundled()   # 前置：随包插件全部启用
_ensure_enabled("weather")   # 夹具前置：确保被测插件启用

check("插件清单含 weather", weather is not None, str([p["id"] for p in listing.get("plugins", [])]))
nav = (weather or {}).get("nav") or [{}]
check("weather 面板与样式 URL 齐备",
      "/plugins-file/weather/web/panel.js" in str(nav[0].get("url", ""))
      and "/plugins-file/weather/web/panel.css" in str(nav[0].get("style_url", "")),
      json.dumps(nav[0], ensure_ascii=False)[:130])

st, cfg = get("/api/plugins/weather/config")
check("插件配置路由可用", st == 200 and "location" in cfg, json.dumps(cfg, ensure_ascii=False)[:110])
check("已从内核 app.json 迁移天气设置（地点非默认空值）", bool(cfg.get("location")), str(cfg.get("location")))

st, _ = get("/api/weather")
check("内核旧路由 /api/weather 已移除（404）", st == 404, str(st))

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE if Path(EXE).is_file() else None, headless=True)
    pg = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
    errors, failed = [], []
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("requestfailed", lambda r: failed.append(r.url))
    pg.goto(f"{BASE}/#overview", wait_until="networkidle", timeout=45000)
    pg.wait_for_selector('#topbar-slot [data-plugin="weather"] .weather-pill', timeout=45000)
    pg.wait_for_timeout(1500)

    slot = pg.evaluate("""() => {
        const host = document.querySelector('#topbar-slot');
        const box = document.querySelector('#topbar-slot [data-plugin="weather"]');
        const pill = box && box.querySelector('.weather-pill');
        const dot = box && box.querySelector('.status-dot');
        return {
          hostFound: !!host,
          boxFound: !!box,
          pillFound: !!pill,
          text: pill ? (pill.querySelector('.weather-text') || {}).textContent : null,
          dotSize: dot ? getComputedStyle(dot).width : null,
          dotRadius: dot ? getComputedStyle(dot).borderRadius : null,
        };
    }""")
    check("顶栏槽位容器存在", slot.get("hostFound"))
    check("插件把自己的卡片画进了槽位", slot.get("boxFound") and slot.get("pillFound"))
    check("卡片文本已填充（离线时降级显示）", bool(str(slot.get("text") or "").strip()), str(slot.get("text")))
    check("插件样式生效（status-dot 7px 圆点）",
          slot.get("dotSize") == "7px" and "50%" in str(slot.get("dotRadius")), str(slot))

    pg.click('#topbar-slot [data-plugin="weather"] .weather-pill')
    pg.wait_for_selector("#w-location", timeout=20000)
    fields = pg.evaluate("() => ({loc: !!document.querySelector('#w-location'), lat: !!document.querySelector('#w-lat'), "
                         "lon: !!document.querySelector('#w-lon'), tz: !!document.querySelector('#w-tz'), "
                         "en: !!document.querySelector('#w-enabled'), geo: !!document.querySelector('#weather-geocode'), "
                         "save: !!document.querySelector('#weather-save')})")
    check("点卡片弹出插件自己的设置模态", all(fields.values()), str(fields))
    pg.fill("#w-location", "天津市南开区（插件验收）")
    pg.click("#weather-save")
    pg.wait_for_timeout(2500)
    st, saved = get("/api/plugins/weather/config")
    check("保存落盘到插件配置", str(saved.get("location", "")).startswith("天津市南开区（插件验收）"), str(saved.get("location")))
    # 还原
    post("/api/plugins/weather/config", {"location": cfg.get("location")})

    check("全程无 console error", not errors, str(errors[:2]))
    check("全程无失败请求", not failed, str(failed[:2]))
    b.close()

hits = [p.relative_to(ROOT).as_posix() for p in (ROOT / "app").rglob("*.py") if "weather" in p.read_text(encoding="utf-8").lower()]
check("内核 Python 已无天气实现/路由", not hits, str(hits))
html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("index.html 只剩槽位、无硬编码天气卡片", "weather-pill" not in html and 'data-erw-slot="topbar"' in html)
check("插件配置写在 config/plugins/weather.json", (ROOT / "config" / "plugins" / "weather.json").is_file())

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（天气已成为可增删插件，内核不再认识它）")
