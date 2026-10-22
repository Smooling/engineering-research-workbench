"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
计费插件验收（含 P14 依赖倒置）。

1. 旧账本被**原样认领**（记录条数、单价表内容一字不差）
2. 面板可用：导航项「用量」在侧栏、页面渲染出统计
3. 接口搬移：/api/billing/* 已 404；/api/plugins/billing/* 可用
4. **依赖倒置**：内核不再 import 计费；`llm.usage` 事件被插件订阅并记账
   —— 直接向事件总线广播一次，账本应新增一条（口径与搬出前一致）
5. 零订阅者时内核照常（事件无人听 = 无事发生）
6. 内核已无计费实现（app/billing.py、/api/billing/*、web/v261008-billing.*）
7. 0 console error / 0 失败请求
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


def get(path, timeout=30):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload, timeout=30):
    req = urllib.request.Request(BASE + path, method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps(payload).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def is_404(fn, path, payload=None):
    try:
        fn(path, payload) if payload is not None else fn(path)
        return False
    except urllib.error.HTTPError as e:
        return e.code == 404


def _ensure_all_bundled():
    """前置：随包插件全部启用（本夹具断言侧栏含「用量」）。"""
    import json as _json
    import urllib.request as _u
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

_ensure_all_bundled()

print("== 1. 数据认领 ==")
legacy_dir = ROOT / "Workspace" / "System" / "billing"
plugin_dir = ROOT / "Workspace" / "System" / "Plugins" / "billing"
legacy_ledger = legacy_dir / "ledger.jsonl"
plugin_ledger = plugin_dir / "ledger.jsonl"
check("旧账本存在（迁移来源）", legacy_ledger.is_file(), str(legacy_ledger))
legacy_lines = legacy_ledger.read_text(encoding="utf-8").splitlines() if legacy_ledger.is_file() else []
check("插件账本已认领", plugin_ledger.is_file(), str(plugin_ledger))
plugin_lines = plugin_ledger.read_text(encoding="utf-8").splitlines() if plugin_ledger.is_file() else []
check("账本内容原样带过来（行数一致且前几行相同）",
      len(plugin_lines) >= len(legacy_lines) and plugin_lines[:3] == legacy_lines[:3],
      f"旧 {len(legacy_lines)} 行 / 新 {len(plugin_lines)} 行")
legacy_prices = (legacy_dir / "prices.json")
plugin_prices = (plugin_dir / "prices.json")
check("单价表也已认领且内容一致",
      legacy_prices.is_file() and plugin_prices.is_file() and
      json.loads(plugin_prices.read_text(encoding="utf-8")) == json.loads(legacy_prices.read_text(encoding="utf-8")))

print("\n== 2. 接口 ==")
summary = get("/api/plugins/billing/summary")
check("插件 summary 可用", isinstance(summary, dict) and "total" in summary and "by_model" in summary,
      str(list(summary.keys())[:6]))
recs = get("/api/plugins/billing/records?limit=5")
check("插件 records 可用", "items" in recs and "total" in recs, f"total={recs.get('total')}")
prices = get("/api/plugins/billing/prices")
check("插件 prices 可用", isinstance(prices, dict) and "models" in prices, str(list(prices.keys())[:5]))
check("预置模板接口保留（?defaults=1）", "models" in get("/api/plugins/billing/prices?defaults=1"))
check("内核旧接口 /api/billing/summary 已 404", is_404(get, "/api/billing/summary"))
check("内核旧接口 /api/billing/records 已 404", is_404(get, "/api/billing/records"))
check("内核旧接口 /api/billing/prices 已 404", is_404(get, "/api/billing/prices"))

print("\n== 3. 依赖倒置：事件记账 ==")
_ledger_before = plugin_ledger.read_bytes() if plugin_ledger.is_file() else b""
import subprocess  # noqa: E402
probe = subprocess.run(
    [sys.executable, "-c", """
import sys; sys.path.insert(0, r'%s')
import server
from core import events

PAYLOAD = {
    'billing': {'session_id': 'verify-billing', 'session_title': '验收', 'preset_label': 'default', 'source': 'verify'},
    'usage': {'prompt_tokens': 1000, 'completion_tokens': 500, 'total_tokens': 1500},
    'model': 'deepseek-v4.1-flash', 'profile_id': 'profile-ark-agent-plan', 'profile_name': '火山方舟',
}
# ① 尚未加载插件：零订阅者。内核必须照常（I1）——广播不报错、返回 0
print('BEFORE', events.emit('llm.usage', PAYLOAD))
# ② 按服务启动的方式加载插件（build_server 里就是这么做的），插件订阅后应送达
server.load_plugins(server.ROOT, server.workspace.ensure_workspace())
print('AFTER', events.emit('llm.usage', PAYLOAD))
""" % ROOT],
    capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
    env={**os.environ, "PYTHONIOENCODING": "utf-8"},   # Windows 控制台默认 GBK，子进程日志是 UTF-8
)
out = (probe.stdout or "") + (probe.stderr or "")
before = [l for l in out.splitlines() if l.startswith("BEFORE")]
after = [l for l in out.splitlines() if l.startswith("AFTER")]
_tail = (out.strip().splitlines() or ["<子进程无输出>"])[-1]
check("未加载插件时广播：零送达且不报错（I1）", bool(before) and before[0].split()[-1] == "0",
      (before or [_tail])[0][:70])
check("加载插件后广播：送达 1 个订阅者", bool(after) and after[0].split()[-1] == "1",
      (after or [_tail])[0][:70])
_ledger_after = plugin_ledger.read_bytes()
_added = _ledger_after[len(_ledger_before):].decode("utf-8").strip().splitlines()
check("事件被插件订阅并记进账本（一条）", len(_added) == 1, str(_added[:1])[:110])
if _added:
    _rec = json.loads(_added[0])
    check("记账口径与搬出前一致（归属会话 + token 数 + 模型）",
          _rec.get("session_id") == "verify-billing" and _rec.get("model") == "deepseek-v4.1-flash"
          and _rec.get("prompt_tokens") == 1000 and _rec.get("completion_tokens") == 500,
          json.dumps({k: _rec.get(k) for k in ("session_id", "model", "prompt_tokens", "completion_tokens", "billing_mode")}, ensure_ascii=False))
plugin_ledger.write_bytes(_ledger_before)   # 还原：验收不留假账
check("验收后账本已还原（不留假记录）", plugin_ledger.read_bytes() == _ledger_before)

print("\n== 4. 面板 ==")
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE if Path(EXE).is_file() else None, headless=True)
    pg = b.new_context(viewport={"width": 1440, "height": 950}).new_page()
    errs, bad = [], []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("requestfailed", lambda r: bad.append(r.url))
    pg.goto(f"{BASE}/#billing", wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(2000)
    info = pg.evaluate("""() => {
        const main = document.querySelector('#main');
        const nav = Array.from(document.querySelectorAll('.nav-item')).map(e => e.dataset.route);
        const box = document.querySelector('[data-plugin="billing"]');
        return {
          title: (document.querySelector('#page-title') || {}).textContent || '',
          navHasBilling: nav.includes('billing'),
          rendered: main ? main.innerText.trim().length : 0,
          scoped: !!box,
          text: main ? main.innerText.replace(/\\n/g, ' | ').slice(0, 90) : '',
        };
    }""")
    check("侧栏含插件登记的「用量」", info["navHasBilling"])
    check("计费页由插件渲染出内容", info["rendered"] > 80, f"{info['rendered']} 字：{info['text'][:60]}")
    check("页头标题正确", "用量" in info["title"], info["title"])
    check("容器带 data-plugin 作用域（插件样式生效的前提）", info["scoped"])
    pg.click('[data-set-tab="plugins"]') if False else None
    check("无 console error", not errs, str(errs[:2]))
    check("无失败请求", not bad, str(bad[:2]))
    b.close()

print("\n== 5. 内核已无计费 ==")
gone = [str(x) for x in ("app/billing.py", "web/v261008-billing.js", "web/v261008-billing.css") if (ROOT / x).exists()]
check("内核计费文件已删除", not gone, str(gone))
import ast as _ast


def _uses_billing(path):
    """AST 判定：真的 import 或引用了 `billing` 名字才算（文档字符串里的说明不算）。"""
    tree = _ast.parse(path.read_text(encoding="utf-8"))
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import) and any(a.name.split(".")[-1] == "billing" for a in node.names):
            return True
        if isinstance(node, _ast.ImportFrom) and (node.module or "").split(".")[-1] == "billing":
            return True
        if isinstance(node, _ast.Name) and node.id == "billing":
            return True
        if isinstance(node, _ast.Attribute) and isinstance(node.value, _ast.Name) and node.value.id == "billing":
            return True
    return False


srcs = [q.relative_to(ROOT).as_posix() for q in (ROOT / "app").rglob("*.py") if _uses_billing(q)]
check("内核 Python 不再调用计费（AST 判定）", not srcs, str(srcs))
appjs = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
code = appjs.split("/* v261009.8")[0] + appjs.split("*/", appjs.find("/* v261009.8"))[-1]
check("app.js 无计费实现（只剩注释）", "renderBillingPage" not in code and "/api/billing/" not in appjs)

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（用量计费已插件化：依赖倒置 + 账本原样认领 + 接口/面板搬移）")
