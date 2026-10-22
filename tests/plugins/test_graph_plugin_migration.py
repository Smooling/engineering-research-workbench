# -*- coding: utf-8 -*-
"""A16 · 知识图谱可视化「插件化」迁移等价性验收（真 Chrome，不截图）。

迁移前：web/v260922-research-pages.js 里的两个 IIFE（图引擎 + 总览迷你图）靠**克隆替换内核画布**
        并反向约定全局变量（window.__knowledgeGraphEngineVersion 等）来接管。
迁移后：plugins/knowledge-graph/（纯前端插件）通过内核渲染接管接缝 window.ERWGraphRenderers 注册，
        内核渲染图谱页时把 #main 交给它的 mount(host)；插件缺席时内核只给启用提示（v261009.18 起不再自带兜底渲染）。

验收口径（对应 REFACTOR_PLAN A16）：
  A. 路由/接口不变：图谱页与总览页照旧渲染，数据仍来自 /api/graph、/api/graph/overview
  B. 能力等价：大图布局（节点数）、筛选联动、搜索定位、节点预览（Markdown 经内核接缝）、导出弹窗
  C. 分离干净：插件缺席（脚本请求被拦）→ 内核不画图、只给「请启用插件」提示、0 console error
  D. 宿主契约：插件经 /api/plugins 下发 panel_url/panel_style_url；启停走 /api/plugin-manager/<id>/enabled
  E. 顺手修掉的两处漂移（属**有意的行为改进**，需在报告里显式标注）：
     ① 引擎自带标签表缺 experiment → 节点侧栏/搜索回落英文；
     ② 同表缺 experiment → 「仅知识条目」把实验条目一起取消勾选。
"""
import os
import re
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ERW_BASE", "http://127.0.0.1:8799")
PLUGIN_ID = "knowledge-graph"

CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# 内核绘制计数：app.js 的 drawGraph 先 canvas.getContext('2d')；插件引擎的画布在取上下文前
# 已带 dataset.optimizedGraph='1'，故这两个条件能区分出「内核自己画的那次」。
COUNTER = """
window.__kernDraws = 0;
const __origGetContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
  if (type === '2d' && this.id === 'graph-canvas' && this.dataset.optimizedGraph !== '1') window.__kernDraws++;
  return __origGetContext.call(this, type, ...rest);
};
"""

PIXELS = """
(sel) => {
  const c = document.querySelector(sel);
  if (!c) return { found: false };
  const ctx = c.getContext('2d');
  if (!ctx) return { found: true, ctx: false };
  const d = ctx.getImageData(0, 0, c.width, c.height).data;
  let n = 0;
  for (let i = 3; i < d.length; i += 4) if (d[i] > 8) n++;
  return { found: true, ctx: true, w: c.width, h: c.height, painted: n,
           token: c._graphRenderToken === undefined ? null : c._graphRenderToken,
           optimized: c.dataset.optimizedGraph || null,
           modern: c.dataset.modernOverviewGraph || null };
}
"""

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


def api(path, method="GET", body=None):
    import json
    import urllib.request
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    with sync_playwright() as p:
        exe = find_browser()
        kwargs = {"headless": True}
        if exe:
            kwargs["executable_path"] = exe
        print(f"浏览器：{exe or 'playwright 自带'}\n")
        browser = p.chromium.launch(**kwargs)

        # ================= 1. 插件在场：图谱页能力等价 =================
        print("1) #graph · 插件接管（能力等价）")
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script(COUNTER)
        errors, failed = [], []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("requestfailed", lambda r: failed.append(r.url))
        page.goto(BASE + "/#graph", wait_until="load")
        page.wait_for_function(
            "() => !!window.__knowledgeGraphEngine && "
            "(document.querySelector('#graph-canvas')||{}).dataset?.optimizedGraph === '1'",
            timeout=25000)
        page.wait_for_timeout(400)
        st = page.evaluate(PIXELS, "#graph-canvas")
        info = page.evaluate("""() => ({
            registered: (window.ERWGraphRenderers?.list?.() || []).map(r => r.id),
            nodes: window.__knowledgeGraphEngine.graph?.nodes?.length ?? -1,
            edges: window.__knowledgeGraphEngine.graph?.edges?.length ?? -1,
            experimentLabel: window.ERWContract?.kindLabel?.('experiment') ?? null,
            toolbar: !!document.querySelector('#graph-smart-toolbar'),
            panelCss: [...document.styleSheets].some(s => (s.href||'').includes('knowledge-graph')),
        })""")
        check("插件已注册到接管表", PLUGIN_ID in info["registered"], f"registered={info['registered']}")
        check("插件已接管画布", st.get("optimized") == "1", f"optimizedGraph={st.get('optimized')}")
        check("内核没有重复绘制", page.evaluate("() => window.__kernDraws") == 0,
              f"内核取 2d 上下文次数={page.evaluate('() => window.__kernDraws')}")
        check("大图布局已渲染", info["nodes"] > 300, f"nodes={info['nodes']} edges={info['edges']}")
        check("画布非空", st.get("painted", 0) > 5000, f"painted={st.get('painted')}px")
        check("插件工具栏已注入", info["toolbar"])
        check("插件样式表已加载", info["panelCss"])
        check("契约标签可用（实验）", info["experimentLabel"] == "实验", f"={info['experimentLabel']}")

        # 筛选联动（改写内核控件后仍生效）
        before = info["nodes"]
        page.evaluate("""() => {
          const cb = document.querySelector('[data-graph-kind]');
          cb.checked = false; cb.dispatchEvent(new Event('change', {bubbles: true}));
        }""")
        page.wait_for_timeout(300)
        after = page.evaluate("() => window.__knowledgeGraphEngine.graph?.nodes?.length ?? -1")
        check("筛选联动生效", after < before, f"{before} → {after}")

        # 「仅知识条目」现在包含实验（迁移前的漂移已修）
        page.evaluate("() => document.querySelector('#graph-filter-docs')?.click()")
        page.wait_for_timeout(200)
        exp_checked = page.evaluate(
            "() => document.querySelector('[data-graph-kind=\"experiment\"]')?.checked ?? null")
        check("「仅知识条目」含实验条目（修掉的漂移）", exp_checked is True, f"experiment.checked={exp_checked}")
        exp_node = page.evaluate("""() => {
          const n = (window.__knowledgeGraphEngine.graph?.nodes||[]).find(x => x.kind === 'experiment');
          return n ? { id: String(n.id), label: n.label } : null;
        }""")

        # 搜索定位 + 节点预览（Markdown 走内核 ERWMarkdown 接缝）
        page.evaluate("() => document.querySelector('#graph-filter-all')?.click()")
        page.wait_for_timeout(200)
        target = page.evaluate("""() => {
          const nodes = (window.__knowledgeGraphEngine.graph?.nodes||[]).filter(n => !n.virtual && n.kind !== 'tag' && n.kind !== 'project');
          return nodes.length ? { id: String(nodes[0].id), label: nodes[0].label } : null;
        }""")
        if target:
            page.evaluate("(id) => window.__knowledgeGraphEngine.selectNode(id, false)", target["id"])
            page.wait_for_timeout(1200)
            prev = page.evaluate("""() => ({
                title: document.querySelector('#graph-preview-title')?.textContent || '',
                bodyHtml: (document.querySelector('#graph-preview-body')?.innerHTML || '').length,
                sideTitle: document.querySelector('#graph-node-title')?.textContent || '',
                bundleEnabled: !document.querySelector('#graph-bundle')?.disabled,
            })""")
            check("选中节点 → 侧栏标题更新", prev["sideTitle"] == target["label"],
                  f"{prev['sideTitle']!r} vs {target['label']!r}")
            check("节点预览 Markdown 已渲染", prev["bodyHtml"] > 50
                  and '<' in page.evaluate("() => document.querySelector('#graph-preview-body')?.innerHTML || ''"),
                  f"bodyHtml={prev['bodyHtml']}")
            check("导出按钮已解禁", prev["bundleEnabled"])
            # 导出弹窗（内核 #modal-* 容器复用）
            page.evaluate("() => window.__knowledgeGraphEngine.openBundle()")
            page.wait_for_timeout(400)
            bundle = page.evaluate("""() => ({
                open: !document.querySelector('#modal-backdrop')?.classList.contains('hidden'),
                title: document.querySelector('#modal-title')?.textContent || '',
                items: document.querySelectorAll('#modal-body .bundle-item').length,
            })""")
            check("导出弹窗可打开", bundle["open"] and bundle["title"] == "整理关联 Markdown",
                  f"title={bundle['title']!r} items={bundle['items']}")
            page.evaluate("() => document.querySelector('#modal-backdrop')?.classList.add('hidden')")
        else:
            check("找得到可预览节点", False, "图谱里没有非虚拟节点")

        # 2D/3D 切换 + 一轮交互后内核仍不插手
        page.evaluate("""() => {
          document.querySelectorAll('[data-gview]').forEach(b => b.click());
          document.querySelectorAll('[data-graph-kind]').forEach(c => { c.checked = !c.checked; c.dispatchEvent(new Event('change', {bubbles: true})); });
          document.querySelector('#graph-filter-all')?.click();
        }""")
        page.wait_for_timeout(600)
        check("一轮交互后内核绘制次数仍为 0", page.evaluate("() => window.__kernDraws") == 0,
              f"={page.evaluate('() => window.__kernDraws')}")
        check("图谱页无 console error", not errors, "; ".join(errors[:3]))
        check("图谱页无失败请求", not failed, "; ".join(failed[:3]))
        page.close()

        # ================= 2. 插件缺席：内核**不再**兜底绘制，只给启用提示 =================
        print("2) #graph · 插件缺席（脚本请求被拦 → 不画图，只给提示）")
        page2 = browser.new_page(viewport={"width": 1440, "height": 900})
        page2.add_init_script(COUNTER)
        page2.route(re.compile(r".*/plugins-file/knowledge-graph/.*"), lambda route: route.abort())
        err2, fail2 = [], []
        page2.on("console", lambda m: err2.append(m.text) if m.type == "error" else None)
        page2.on("requestfailed", lambda r: fail2.append(r.url))
        page2.goto(BASE + "/#graph", wait_until="load")
        page2.wait_for_timeout(1500)
        reg2 = page2.evaluate("() => (window.ERWGraphRenderers?.list?.() || []).map(r => r.id)")
        off = page2.evaluate("""() => ({
            hint: (document.querySelector('#main')?.innerText || '').includes('知识图谱不可用'),
            hasCanvas: !!document.querySelector('#graph-canvas'),
            hasFilters: document.querySelectorAll('[data-graph-kind]').length,
            kernDraws: window.__kernDraws,
        })""")
        check("接管表为空（插件未加载）", reg2 == [], f"registered={reg2}")
        check("没有画布（内核不再自带渲染器）", not off["hasCanvas"] and not off["hasFilters"], str(off))
        check("内核一次都没画（旧的螺旋兜底图已删除）", off["kernDraws"] == 0, f"kernDraws={off['kernDraws']}")
        check("给出明确的启用提示", off["hint"], "页面文字里没有『知识图谱不可用』")
        real_err2 = [e for e in err2 if "ERR_FAILED" not in e and "ERR_BLOCKED" not in e
                     and PLUGIN_ID not in e]   # 被拦插件自身引发的宿主诊断不算失败
        real_fail2 = [u for u in fail2 if f"plugins-file/{PLUGIN_ID}" not in u]
        check("除被拦插件资源外无 console error", not real_err2, "; ".join(real_err2[:3]))
        check("除被拦插件资源外无失败请求", not real_fail2, "; ".join(real_fail2[:3]))
        page2.close()

        # ================= 3. 总览迷你图 =================
        print("3) #research-overview · 迷你知识关系图")
        page3 = browser.new_page(viewport={"width": 1440, "height": 900})
        err3 = []
        page3.on("console", lambda m: err3.append(m.text) if m.type == "error" else None)
        page3.goto(BASE + "/#research-overview", wait_until="load")
        page3.wait_for_function(
            "() => !!window.__overviewKnowledgeGraph && "
            "(document.querySelector('#overview-graph')||{}).dataset?.modernOverviewGraph === '1'",
            timeout=25000)
        page3.wait_for_timeout(400)
        st3 = page3.evaluate(PIXELS, "#overview-graph")
        check("迷你图由插件接管", st3.get("modern") == "1", f"modernOverviewGraph={st3.get('modern')}")
        check("迷你图画布非空", st3.get("painted", 0) > 300, f"painted={st3.get('painted')}px")
        check("总览页无 console error", not err3, "; ".join(err3[:3]))
        # 迷你图点节点 → 跳到图谱页并定位（OverviewGraph.nodes / openFullGraph 是插件内部字段）
        page3.evaluate("""() => {
          const inst = window.__overviewKnowledgeGraph;
          const n = (inst?.nodes || []).find(x => x && !x.virtual);
          if (n) inst.openFullGraph(String(n.id));
        }""")
        page3.wait_for_timeout(1500)
        jumped = page3.evaluate("() => ({ hash: location.hash, engine: !!window.__knowledgeGraphEngine })")
        check("迷你图可跳转图谱页", jumped["hash"] == "#graph" and jumped["engine"],
              f"hash={jumped['hash']} engine={jumped['engine']}")
        page3.close()

        # ================= 4. 宿主契约：禁用 → 兜底，再启用还原 =================
        print("4) 宿主契约 · /api/plugin-manager 启停")
        plugins_file = Path(__file__).resolve().parents[2] / "Workspace" / "System" / "plugins.json"

        def enabled_map():
            """只看「开不开」的语义快照：updated 时间戳本来就会变，不能按字节比对。"""
            data = api("/api/plugins")
            try:
                import json as _json
                raw = _json.loads(plugins_file.read_text(encoding="utf-8"))
            except Exception:
                raw = {"plugins": {}}
            return ({k: bool(v.get("enabled")) for k, v in (raw.get("plugins") or {}).items()
                     if k != PLUGIN_ID}, data.get("version"))

        before_map, _ = enabled_map()
        try:
            api(f"/api/plugin-manager/{PLUGIN_ID}/enabled", "POST", {"enabled": False})
            flags_off = api("/api/plugins")
            off = [x for x in (flags_off.get("plugins") or []) if x.get("id") == PLUGIN_ID]
            check("禁用后 /api/plugins 不再下发该插件", not off, f"命中 {len(off)} 条")
            page4 = browser.new_page(viewport={"width": 1440, "height": 900})
            page4.add_init_script(COUNTER)
            page4.goto(BASE + "/#graph", wait_until="load")
            page4.wait_for_timeout(1500)
            off4 = page4.evaluate("""() => ({
                canvas: !!document.querySelector('#graph-canvas'),
                hint: (document.querySelector('#main')?.innerText || '').includes('知识图谱不可用'),
                kernDraws: window.__kernDraws,
            })""")
            check("禁用后不画图（内核无渲染器）", not off4["canvas"] and off4["kernDraws"] == 0, str(off4))
            check("禁用后给启用提示", off4["hint"], "页面没有『知识图谱不可用』提示")
            page4.close()
        finally:
            api(f"/api/plugin-manager/{PLUGIN_ID}/enabled", "POST", {"enabled": True})
            flags_on = api("/api/plugins")
            on = [x for x in (flags_on.get("plugins") or []) if x.get("id") == PLUGIN_ID]
            check("重新启用后插件回到下发列表", bool(on))
            after_map, _ = enabled_map()
            same = after_map == before_map
            check("其余插件的启停状态未被这次验收改动", same,
                  "一致" if same else f"差异：{ {k: (before_map.get(k), after_map.get(k)) for k in set(before_map) | set(after_map) if before_map.get(k) != after_map.get(k)} }")

        browser.close()

    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} 通过")
    if bad:
        print("未通过项：")
        for name, _, detail in bad:
            print(f"  - {name}  {detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
