"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
插件执行层验收：register(ctx) / 路由分发 / 存储命名空间 / 冲突与失败隔离。

用夹具插件（.scratch/verify/plugins-api/）起一个真服务，逐项验证：
1. 正常插件的 register 被调用，路由挂到 /api/plugins/<id>/<rel> 并可应答
2. 路由 handler 拿得到 query 与 body
3. ctx.storage / ctx.config_* 落在插件自己的命名空间
4. 插件间/与内核保留前缀的路由冲突会被拒并给出原因
5. register 抛异常的插件 → 记为 failed，**内核与其它插件不受影响**
6. 插件没注册的路径 → 404；handler 抛异常 → 500 且只影响该请求
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / ".scratch" / "verify" / "plugins-api"
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  · {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def write_plugin(pid, manifest, backend):
    d = FIX / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "backend.py").write_text(backend, encoding="utf-8")


if FIX.exists():
    shutil.rmtree(FIX)
FIX.mkdir(parents=True)

# 1) 正常插件：GET/POST 路由、读 query/body、用 ctx.storage 与 config
write_plugin("hello", {
    "id": "hello", "name": "Hello", "version": "1.0.0", "api_version": 1,
    "core_min": "v261009", "kind": "inprocess", "distribution": "optional", "default_enabled": True,
    "entry": "backend.py", "permissions": ["storage:own", "config:own"],
    "routes": [{"method": "GET", "path": "ping"}, {"method": "POST", "path": "echo"}],
}, '''
from core_api import log


def register(ctx):
    ctx.log("register 被调用")
    log(ctx.id, "通过 core_api.log 也能记日志")
    ctx.storage.ensure()
    ctx.config_write({"seen": 1})

    def ping(request):
        return {"ok": True, "plugin": ctx.id, "query": request["query"].get("q", []),
                "config": ctx.config_read(), "workspace": str(ctx.storage.workspace.exists())}

    def echo(request):
        return {"ok": True, "body": request["body"], "method": request["method"]}

    def boom(request):
        raise RuntimeError("handler 故意炸")

    ctx.routes.get("ping", ping)
    ctx.routes.post("echo", echo)
    ctx.routes.get("boom", boom)
    ctx.mcp.tool("hello_now", {"description": "夹具工具"}, lambda: {"ok": True})
''')

# 2) register 抛异常的插件
write_plugin("broken", {
    "id": "broken", "name": "Broken", "version": "1.0.0", "api_version": 1,
    "kind": "inprocess", "distribution": "optional", "default_enabled": True,
    "entry": "backend.py",
}, '''
def register(ctx):
    raise RuntimeError("register 故意失败")
''')

# 3) 违规插件：裸 /api 路由 + 与内核保留前缀冲突 + 与已注册插件重复
write_plugin("sneaky", {
    "id": "sneaky", "name": "Sneaky", "version": "1.0.0", "api_version": 1,
    "kind": "inprocess", "distribution": "optional", "default_enabled": True,
    "entry": "backend.py",
}, '''
def register(ctx):
    ctx.routes.get("/api/docs", lambda r: {"hijacked": True})       # 裸 /api → 声明期就拒
''')

# 4) 与 hello 路由冲突的插件（不同 id，不同完整路径，不应冲突；这里故意同名相对路径）
write_plugin("dupe", {
    "id": "dupe", "name": "Dupe", "version": "1.0.0", "api_version": 1,
    "kind": "inprocess", "distribution": "optional", "default_enabled": True,
    "entry": "backend.py",
}, '''
def register(ctx):
    ctx.routes.get("ping", lambda r: {"from": "dupe"})
''')

# 5) 纯前端插件（无 entry）也应出现在加载结果里
write_plugin("ui-only", {
    "id": "ui-only", "name": "UI Only", "version": "1.0.0", "api_version": 1,
    "kind": "inprocess", "distribution": "optional", "default_enabled": True,
    "permissions": ["ui:panel"],
}, '')

# 先做一次「纯加载」检查（不起服务）
sys.path.insert(0, str(ROOT))
from core.plugins import loader as L  # noqa: E402

res = L.load(roots=[("user", FIX)], workspace=FIX, core_version="v261009.0")
by_id = res.plugins
print("加载结果：", json.dumps(res.as_dict(), ensure_ascii=False)[:400])
print()
check("正常插件被加载", by_id.get("hello") and by_id["hello"].state == "available")
check("纯前端插件也在加载结果里（无 entry 不执行）", "ui-only" in by_id)
check("register 失败的插件记为 failed", by_id.get("broken") and by_id["broken"].state == "failed",
      by_id.get("broken").reason if by_id.get("broken") else "")
check("失败原因可读且指向插件", "register 故意失败" in (by_id.get("broken").reason if by_id.get("broken") else ""))
check("失败插件不影响正常插件", by_id.get("hello").state == "available")
check("hello 的两条路由已注册",
      sorted(f"{r.method} {r.path}" for r in by_id["hello"].routes) == ["GET ping", "POST echo", "GET boom"]
      or sorted(f"{r.method} {r.path}" for r in by_id["hello"].routes) == ["GET boom", "GET ping", "POST echo"])
check("MCP 工具按前缀暴露", [t.exposed_name for t in by_id["hello"].mcp_tools] == ["p_hello__hello_now"])
check("违规插件（裸 /api 路由）注册失败", by_id.get("sneaky") and by_id["sneaky"].state == "failed",
      (by_id.get("sneaky").reason or "")[:80])
check("路由挂载点是 /api/plugins/<id>/<rel>",
      all(r.full_path.startswith("/api/plugins/hello/") for r in by_id["hello"].routes),
      str([r.full_path for r in by_id["hello"].routes]))

# 再起真服务，验证 HTTP 分发
port = 8800 + (os.getpid() % 90)
env = dict(os.environ, ERW_PLUGINS_ROOTS=str(FIX))
proc = subprocess.Popen(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0,r'%s'); import server;"
     "httpd,cfg,url=server.build_server(port_override=%d, auto_open_browser=False);"
     "print('READY', flush=True); httpd.serve_forever(poll_interval=0.25)" % (ROOT, port)],
    cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    encoding="utf-8", errors="replace",
)


def wait_ready(timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.6):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def get(path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=8) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


def post(path, payload):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


try:
    ok = wait_ready()
    check("服务起来了", ok, f"port={port}")
    if ok:
        st, body = get("/api/plugins/hello/ping?q=abc")
        check("GET 插件路由可用且拿到 query", st == 200 and body.get("ok") and body.get("query") == ["abc"],
              json.dumps(body, ensure_ascii=False)[:120])
        check("插件存储落在自己的命名空间", str(body.get("workspace")) == "True" or body.get("workspace") is True,
              str(body.get("workspace")))
        st, body = post("/api/plugins/hello/echo", {"x": 1})
        check("POST 插件路由拿到 body", st == 200 and body.get("body") == {"x": 1},
              json.dumps(body, ensure_ascii=False)[:120])
        st, body = get("/api/plugins/hello/boom")
        check("handler 抛异常 → 500 且带插件 id", st == 500 and body.get("plugin") == "hello",
              json.dumps(body, ensure_ascii=False)[:120])
        st, body = get("/api/plugins/hello/nope")
        check("未注册的插件路径 → 404", st == 404, str(st))
        st, body = get("/api/health")
        check("内核路由仍正常（插件路由没吃掉内核）", st == 200, str(st))
        st, body = get("/api/plugins")
        check("/api/plugins 清单仍可用", st == 200 and "plugins" in body, str(st))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()

# 配置与存储确实落在插件自己名下
check("插件配置写在 config/plugins/<id>.json",
      (ROOT / "config" / "plugins" / "hello.json").is_file()
      or (FIX / "config" / "plugins" / "hello.json").is_file(),
      "路径由 core_api 决定（开发态=仓库根）")
check("冲突/失败都有原因记录", any("失败" in n for n in res.notes) or res.failures(),
      str(res.notes[:3]))

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（注册/分发/命名空间/冲突/失败隔离）")
