"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
路径安全验收：用**未归一化**的原始请求行测插件资源路由，确认越界被拒。

http.client 会把 path 原样发送（不像 Invoke-WebRequest 会先归一化 `..`），
所以能真正打到服务端的路径检查上。
"""
import http.client
import sys
from urllib.parse import urlparse

# 既能收「端口」（手跑时的老习惯），也能收运行器给的 `http://host:port`
_arg = sys.argv[1] if len(sys.argv) > 1 else "8799"
if _arg.startswith("http"):
    _u = urlparse(_arg)
    HOST, PORT = _u.hostname or "127.0.0.1", int(_u.port or 80)
else:
    HOST, PORT = "127.0.0.1", int(_arg)

# 没有服务时跳过而不是误报失败：完整档由 tools/run_tests.py 起临时服务并传入 URL，
# --no-server（CI 的纯逻辑档）下这里应安静跳过。
import socket

try:
    socket.create_connection((HOST, PORT), timeout=2).close()
except OSError:
    print(f"SKIP 需要工作台服务 {HOST}:{PORT}（用 tools/run_tests.py 完整档会自动起）")
    raise SystemExit(0)

CASES = [
    # (路径, 期望状态, 说明)
    ("/plugins-file/focus/web/panel.js", 200, "正常面板脚本"),
    ("/plugins-file/focus/plugin.json", 200, "插件自己的清单（在插件目录内，允许）"),
    ("/plugins-file/focus/../focus/web/panel.js", 200, "归一化后仍在插件目录内"),
    ("/plugins-file/focus/../../server.py", 403, "越出插件目录"),
    ("/plugins-file/focus/..%2f..%2fserver.py", 403, "编码的 ../ 穿越"),
    ("/plugins-file/focus/%2e%2e/%2e%2e/app/store.py", 403, "编码的 .. 目录"),
    ("/plugins-file/focus/web/../../../../Windows/win.ini", 403, "多次穿越到系统文件"),
    ("/plugins-file/nope/x.js", 404, "未知插件"),
    ("/plugins-file/focus", 400, "缺少子路径"),
    ("/plugins-file/", 400, "缺少插件 id"),
]
FAILS = []
for path, want, name in CASES:
    conn = http.client.HTTPConnection(HOST, PORT, timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read(200)
        got = resp.status
    finally:
        conn.close()
    leaked = b"import" in body and b"def " in body  # 粗略判断是否泄漏了服务端源码
    ok = (got == want) and not leaked
    print(("PASS " if ok else "FAIL ") + f"{name}：{path} → {got}（期望 {want}）"
          + ("  ⚠ 疑似泄漏源码" if leaked else ""))
    if not ok:
        FAILS.append(name)

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（插件资源只能取插件目录内的文件）")
