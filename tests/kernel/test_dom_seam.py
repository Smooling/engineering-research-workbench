"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
A9 验收：ERWDom 共享接缝的契约 + 观察者驱动的装饰仍然生效。

1. observer 实例恰好 1 个；订阅方数量 = web/ 与 plugins/ 里 ERWDom.onChildList( 的调用处数（自维护）
2. 作用域：注册 root=#main 的订阅方，改动 #main 内会触发、改动侧栏不触发
3. 按帧合并：一帧内多次变更只回调一次
4. 隔离：某个订阅方抛异常不影响其它订阅方
5. 装饰仍在：文档分页器（performance 补丁）与图谱状态条（graph 补丁）——两者都靠该接缝触发
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
    pg = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
    errors = []
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.goto(f"{BASE}/#notes", wait_until="networkidle", timeout=40000)
    pg.wait_for_timeout(1500)

    seam = pg.evaluate("() => ({observers: window.ERWDom.observerCount(), subscribers: window.ERWDom.subscriberCount()})")
    check("observer 实例恰好 1 个", seam.get("observers") == 1, str(seam))
    # v261009.18 · 期望值改为**自维护**：数一遍 web/ 与 plugins/ 里 ERWDom.onChildList( 的调用处，
    # 与运行期 subscriberCount() 比对（写死 7 会在观察点搬走/新增时假失败——本轮真踩过）。
    import re as _re
    from pathlib import Path as _Path
    _root = _Path(__file__).resolve().parents[2]
    _files = sorted((_root / "web").glob("*.js")) + sorted((_root / "plugins").glob("*/web/*.js"))
    _expected = sum(len(_re.findall(r"ERWDom\.onChildList\(", f.read_text(encoding="utf-8")))
                    for f in _files if f.name != "dom-seam.js")  # 接缝自身不计数
    check(f"{_expected} 处文档级观察已全部接上接缝（自维护期望值）",
          seam.get("subscribers") == _expected, f"subscribers={seam.get('subscribers')} expected={_expected}")

    # 2/3/4：用一个自建订阅方测契约（不影响真实订阅方）
    probe = pg.evaluate("""async () => {
        const hits = {inside: 0, outside: 0, thrower: 0, other: 0, coalesced: 0};
        window.ERWDom.onChildList(() => { hits.inside++; }, {root: '#main'});
        window.ERWDom.onChildList(() => { hits.outside++; }, {root: '#sidebar-nav'});
        window.ERWDom.onChildList(() => { hits.thrower++; throw new Error('故意炸'); });
        window.ERWDom.onChildList(() => { hits.other++; });
        const frame = () => new Promise(r => setTimeout(r, 120));
        // 阶段 A：只改侧栏 —— #main 作用域的订阅方不该被唤醒
        const nav = document.querySelector('#sidebar-nav');
        if (nav) { const s = document.createElement('span'); s.className = 'seam-nav-probe'; nav.appendChild(s); }
        await frame();
        hits.sidebarOnly = {inside: hits.inside, outside: hits.outside};
        if (nav) document.querySelectorAll('.seam-nav-probe').forEach(e => e.remove());
        // 阶段 B：一帧内连续 3 次改 #main —— 应合并成 1 次
        const before = hits.inside;
        const main = document.querySelector('#main');
        for (let i = 0; i < 3; i++) {
            const d = document.createElement('div');
            d.className = 'seam-probe';
            main.appendChild(d);
        }
        await frame();
        hits.coalesced = hits.inside - before;
        document.querySelectorAll('.seam-probe').forEach(e => e.remove());
        return hits;
    }""")
    sidebar_only = probe.get("sidebarOnly") or {}
    check("作用域生效：改侧栏不唤醒 #main 作用域的订阅方",
          sidebar_only.get("inside") == 0 and sidebar_only.get("outside", 0) >= 1, json.dumps(sidebar_only))
    check("一帧内多次变更被合并为一次回调", probe.get("coalesced") == 1, f"coalesced={probe.get('coalesced')}")
    check("抛异常的订阅方被隔离，其它订阅方照常触发", probe.get("other", 0) >= 1, json.dumps(probe))

    # 5：接缝驱动的装饰仍在（分页器 / 图谱状态条）
    pager = pg.query_selector(".perf-doc-pager")
    check("文档分页器仍由接缝驱动出现", bool(pager), pager.inner_text().replace("\n", " ")[:50] if pager else "")
    pg.goto(f"{BASE}/#graph", wait_until="networkidle", timeout=40000)
    pg.wait_for_timeout(2000)
    status = pg.eval_on_selector(".perf-graph-status", "e => e.innerText") if pg.query_selector(".perf-graph-status") else ""
    check("图谱状态条仍由接缝驱动出现", "当前加载" in status, status.replace("\n", " ")[:50])

    check("全程无 console error（含故意抛异常的订阅方）", not errors, str(errors[:2]))
    b.close()

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（观察点已收敛为 1 个实例，契约与装饰均等价）")
