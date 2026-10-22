"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
验收本轮两个改动：
① 笔记卡片的时间标签默认右对齐（有/无项目名都贴右）
② 插件页在**旧后端**（无 detail 字段）上明确报「请重启工作台」，勾选框禁用并说明原因；
   在新后端上照常可用。
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

    # ---------- ① 笔记日期右对齐 ----------
    pg = b.new_context(viewport={"width": 1440, "height": 950}).new_page()
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto(f"{BASE}/#notes", wait_until="networkidle", timeout=60000)
    pg.wait_for_selector(".doc-item", timeout=40000)
    pg.wait_for_timeout(900)
    geo = pg.evaluate("""() => {
        const rows = Array.from(document.querySelectorAll('.doc-item .doc-projects')).slice(0, 12);
        const out = [];
        for (const row of rows) {
            const date = row.querySelector('.badge.mono');
            if (!date) continue;
            const proj = row.querySelector('.badge.accent');
            const rr = row.getBoundingClientRect(), dr = date.getBoundingClientRect();
            out.push({
                hasProject: !!proj,
                gapRight: Math.round(rr.right - dr.right),   // 距行右缘
                rowWidth: Math.round(rr.width),
            });
        }
        return out;
    }""")
    check("笔记列表里存在带时间标签的卡片", len(geo) > 0, f"{len(geo)} 张")
    if geo:
        worst = max(x["gapRight"] for x in geo)
        with_proj = [x for x in geo if x["hasProject"]]
        without = [x for x in geo if not x["hasProject"]]
        check("时间标签贴右（距行右缘 ≤ 2px）", worst <= 2, f"最大 {worst}px，样本 {len(geo)}")
        check("有项目名的卡片也贴右", all(x["gapRight"] <= 2 for x in with_proj) if with_proj else True,
              f"{len(with_proj)} 张，最大 {max([x['gapRight'] for x in with_proj], default=0)}px")
        check("无项目名的卡片同样贴右（此前会落左）", all(x["gapRight"] <= 2 for x in without) if without else True,
              f"{len(without)} 张，最大 {max([x['gapRight'] for x in without], default=0)}px")
    check("笔记页无 console error", not errs, str(errs[:2]))
    pg.close()

    # ---------- ② 旧后端：把 detail 请求改写到精简清单 ----------
    pg2 = b.new_context(viewport={"width": 1440, "height": 950}).new_page()
    errs2 = []
    pg2.on("console", lambda m: errs2.append(m.text) if m.type == "error" else None)

    def strip_detail(route):
        route.continue_(url=route.request.url.replace("?detail=1", ""))

    pg2.route("**/api/plugins?detail=1", strip_detail)
    pg2.goto(f"{BASE}/#settings", wait_until="networkidle", timeout=60000)
    pg2.wait_for_selector("#settings-panel", timeout=30000)
    pg2.click('[data-set-tab="plugins"]')
    pg2.wait_for_selector('[data-plugin-card="weather"]', timeout=30000)
    pg2.wait_for_timeout(900)
    old = pg2.evaluate("""() => {
        const box = document.querySelector('[data-plugin-card="weather"]');
        const list = document.querySelector('#pm-list');
        const box2 = box.querySelector('input[type=checkbox]');
        return {
          banner: /后端版本较旧/.test(list.innerText),
          bannerText: (list.innerText.match(/后端版本较旧[^\\n]*/) || [''])[0],
          toggleDisabled: !!box2 && box2.disabled,
          toggleTitle: box2 ? box2.closest('label').title : '',
          saysRestart: /重启工作台/.test(box.innerText),
          misleading: /未声明|无后端接口|未注册工具/.test(box.innerText),
        };
    }""")
    check("旧后端：页面顶部报「后端版本较旧」", old["banner"], old["bannerText"][:40])
    check("旧后端：明确要求重启工作台", old["saysRestart"])
    check("旧后端：启用勾选框被禁用且说明原因", old["toggleDisabled"] and "重启" in old["toggleTitle"], old["toggleTitle"])
    check("旧后端：不再显示「未声明 / 无后端接口 / 未注册工具」这类误导信息", not old["misleading"])
    check("旧后端：无 console error", not errs2, str(errs2[:2]))
    pg2.close()

    # ---------- ③ 新后端：照常可用 ----------
    pg3 = b.new_context(viewport={"width": 1440, "height": 950}).new_page()
    errs3 = []
    pg3.on("console", lambda m: errs3.append(m.text) if m.type == "error" else None)
    pg3.goto(f"{BASE}/#settings", wait_until="networkidle", timeout=60000)
    pg3.wait_for_selector("#settings-panel", timeout=30000)
    pg3.click('[data-set-tab="plugins"]')
    pg3.wait_for_selector('[data-plugin-card="weather"]', timeout=30000)
    pg3.wait_for_timeout(1000)
    # v261009.7 · 权限/路由/槽位都在「详情」里，先展开再断言
    pg3.click('[data-plugin-card="weather"] [data-plugin-detail]')
    pg3.wait_for_timeout(500)
    new = pg3.evaluate("""() => {
        const box = document.querySelector('[data-plugin-card="weather"]');
        const cb = box.querySelector('input[type=checkbox]');
        return {
          banner: /后端版本较旧/.test(document.querySelector('#pm-list').innerText),
          checked: !!cb && cb.checked, enabled: !cb.disabled,
          perms: /net:http/.test(box.innerText), routes: /GET current/.test(box.innerText),
          slot: /槽位 topbar/.test(box.innerText),
          collapsedOk: !!box.querySelector('[data-config-toggle]')
            && box.querySelector('.pm-config').getBoundingClientRect().height <= 45,
        };
    }""")
    check("新后端：无「版本较旧」提示", not new["banner"])
    check("新后端：默认启用被正确勾选且可点", new["checked"] and new["enabled"], json.dumps(new))
    check("新后端：权限/路由/槽位都显示", new["perms"] and new["routes"] and new["slot"], json.dumps(new))
    check("新后端：配置区默认收成一行（要改再展开）", new["collapsedOk"], json.dumps(new, ensure_ascii=False)[:90])
    check("新后端：无 console error", not errs3, str(errs3[:2]))
    pg3.close()
    b.close()

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（时间标签右对齐；插件页对旧后端如实报「需重启」且不误导）")
