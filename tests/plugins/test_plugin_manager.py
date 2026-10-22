"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
设置 → 插件 验收。

1. 设置页出现「插件」tab（由 web/plugin-manager.js 自登记，app.js 无分支）
2. 预览接口 `/api/plugins?detail=1` 给出状态/权限/路由/面板/工具/依赖/配置接口
3. 页面列出全部插件，权限带中文说明、路由与面板可见
4. 配置读写：改 weather.location → 落盘到 config/plugins/weather.json → 能读回
5. 没有配置接口的插件如实说明（focus），不产生 404 噪音
6. 启停：停用 rss → /api/plugins 不再下发 rss、侧栏「资讯」消失；重新启用 → 恢复
7. 启用/停用只写 System/plugins.json，不删插件目录与数据
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


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  · {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload):
    req = urllib.request.Request(BASE + path, method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps(payload).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def is_404(fn, path, payload):
    try:
        fn(path, payload)
        return False
    except urllib.error.HTTPError as e:
        return e.code == 404


print("== 1. 预览接口 ==")
detail = get("/api/plugins?detail=1")
by_id = {p["id"]: p for p in detail["plugins"]}
check("预览接口返回全部插件", {"focus", "rss", "weather"} <= set(by_id), str(sorted(by_id)))
w = by_id["weather"]
check("含状态与启停意图", w["state"] == "available" and w["enabled"] is True, f"{w['state']}/{w['enabled']}")
check("权限带中文说明", any(p["id"] == "net:http" and "网络" in p["label"] for p in w["permissions"]),
      str([p["id"] for p in w["permissions"]]))
check("含路由 / 面板 / 工具 / 依赖字段",
      all(k in w for k in ("routes", "nav_labels", "mcp_tools", "dependencies", "has_config_route")))
check("槽位插件被标出（weather）", w["slot_only"] is True and by_id["rss"]["slot_only"] is False)
check("有配置接口的插件给出 config_url",
      w["has_config_route"] is True and w["config_url"].endswith("/api/plugins/weather/config"))
check("无配置接口的插件标为 false（focus）", by_id["focus"]["has_config_route"] is False)

print("\n== 2. 页面 ==")
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE if Path(EXE).is_file() else None, headless=True)
    pg = b.new_context(viewport={"width": 1440, "height": 950}).new_page()
    errs, bad, calls = [], [], []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("requestfailed", lambda r: bad.append(r.url))
    pg.on("response", lambda r: calls.append((r.status, r.url)) if "/api/plugins" in r.url and r.status >= 400 else None)

    pg.goto(f"{BASE}/#settings", wait_until="networkidle", timeout=60000)
    pg.wait_for_selector("#settings-panel", timeout=30000)
    tabs = pg.eval_on_selector_all("[data-set-tab]", "els => els.map(e => e.dataset.setTab)")
    check("设置页出现「插件」tab", "plugins" in tabs, str(tabs))

    pg.click('[data-set-tab="plugins"]')
    pg.wait_for_selector('[data-plugin-card="weather"]', timeout=30000)
    pg.wait_for_timeout(1200)
    cards = pg.eval_on_selector_all("[data-plugin-card]", "els => els.map(e => e.dataset.pluginCard)")
    check("列出全部插件卡片", {"focus", "rss", "weather"} <= set(cards), str(cards))
    # v261009.7 · 卡片默认只留一行「版本」：权限/路由/面板/目录都在「详情」里，先展开
    for cid in cards:
        btn = pg.query_selector(f'[data-plugin-card="{cid}"] [data-plugin-detail]')
        if btn:
            btn.click()
    pg.wait_for_timeout(500)
    card_text = {cid: pg.eval_on_selector(f'[data-plugin-card="{cid}"]', "e => e.innerText") for cid in cards}
    check("卡片显示权限说明与路由", "net:http" in card_text["weather"] and "GET current" in card_text["weather"],
          card_text["weather"][:70].replace("\n", " | "))
    check("卡片显示面板与版本", "天气" in card_text["weather"] and "1.0.0" in card_text["weather"])
    check("focus 的配置区如实说明（不报错）", "界面里" in card_text["focus"] or "不需要配置" in card_text["focus"],
          card_text["focus"][-60:].replace("\n", " | "))
    check("无配置接口的插件没有产生 4xx 请求", not calls, str(calls[:2]))
    # v261009.6 · 配置区默认收起：先展开再断言编辑器
    pg.click('[data-plugin-card="weather"] [data-config-toggle]')
    pg.wait_for_selector('[data-plugin-card="weather"] [data-config-json]', timeout=20000)
    check("展开后有 JSON 编辑器可改 weather 配置",
          bool(pg.query_selector('[data-plugin-card="weather"] [data-config-json]')))

    print("\n== 3. 配置读写（走插件自己的接口）==")
    ta = pg.query_selector('[data-plugin-card="weather"] [data-config-json]')
    original = json.loads(ta.input_value())
    edited = dict(original)
    edited["location"] = "配置页验收地点"
    edited["latitude"] = 31.23
    ta.fill(json.dumps(edited, ensure_ascii=False, indent=2))
    pg.click('[data-plugin-card="weather"] [data-config-save]')
    pg.wait_for_timeout(2000)
    saved = get("/api/plugins/weather/config")
    check("保存后插件配置真的落盘", saved.get("location") == "配置页验收地点" and saved.get("latitude") == 31.23,
          json.dumps(saved, ensure_ascii=False)[:90])
    disk = json.loads((ROOT / "config" / "plugins" / "weather.json").read_text(encoding="utf-8"))
    check("落盘位置是 config/plugins/weather.json", disk.get("location") == "配置页验收地点")
    # 还原
    post("/api/plugins/weather/config", original)
    check("已还原天气配置", get("/api/plugins/weather/config").get("location") == original.get("location"))

    print("\n== 4. 启停 ==")
    before_ids = [x["id"] for x in get("/api/plugins")["plugins"]]
    check("停用前清单含 rss", "rss" in before_ids, str(before_ids))
    res = post("/api/plugin-manager/rss/enabled", {"enabled": False})
    check("停用接口返回 ok", res.get("ok") is True, str(res)[:80])
    after_ids = [x["id"] for x in get("/api/plugins")["plugins"]]
    check("停用后清单不再含 rss", "rss" not in after_ids, str(after_ids))
    check("停用只改开不开：插件目录仍在", (ROOT / "plugins" / "rss" / "plugin.json").is_file())
    check("停用不动数据：资讯缓存仍在", (ROOT / "Workspace" / "System" / "Plugins" / "rss" / "cache.json").is_file())
    state = json.loads((ROOT / "Workspace" / "System" / "plugins.json").read_text(encoding="utf-8"))
    check("System/plugins.json 记录了停用", state["plugins"]["rss"]["enabled"] is False, json.dumps(state["plugins"]["rss"], ensure_ascii=False))
    res = post("/api/plugin-manager/rss/enabled", {"enabled": True})
    check("重新启用", res.get("ok") is True and "rss" in [x["id"] for x in get("/api/plugins")["plugins"]],
          str([x["id"] for x in get("/api/plugins")["plugins"]]))
    check("未知插件返回 404", is_404(post, "/api/plugin-manager/nope/enabled", {"enabled": True}))

    print("\n== 5. 浏览器侧 ==")
    pg.reload(wait_until="networkidle", timeout=60000)
    pg.wait_for_selector("#settings-panel", timeout=30000)
    nav = pg.eval_on_selector_all(".nav-item", "els => els.map(e => e.dataset.route)")
    check("恢复后侧栏仍含「资讯」", "news" in nav, str(nav))
    check("全程无 console error", not errs, str(errs[:2]))
    check("全程无失败请求", not bad, str(bad[:2]))
    b.close()


print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（设置里的插件预览/配置/启停均可用，且内核不认识任何具体插件）")
