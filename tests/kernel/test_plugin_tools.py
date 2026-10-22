"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
插件工具接线验收（§8 ② + I10 + 写工具的草稿确认闸门）。

1. 已启用插件注册的读/写工具都出现在 Agent 工具面
2. 读工具经 execute() 直接执行；handler 异常只影响该次调用；人设白名单生效
3. **写工具在 confirm 模式下只生成草稿、不执行**（插件拿不到 save_draft，闸门必须在内核侧）
4. confirm_draft 以 direct 模式执行插件写工具；reject_draft 不执行
5. direct 模式下写工具直接执行
6. 未加载插件时工具不出现（不存在「注册了却不可用」的入口）
7. HTTP 面 /api/agent/tools 能看到插件工具（含 write 标记）
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / ".scratch" / "verify" / "plugins-tools"
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

write_plugin("tooled", {
    "id": "tooled", "name": "Tooled", "version": "1.0.0", "api_version": 1,
    "kind": "inprocess", "distribution": "optional", "default_enabled": True,
    "entry": "backend.py", "mcp_tools": ["now", "boom", "save_it"],
}, '''
WRITES = []


def register(ctx):
    def now(args, call_ctx):
        return {"now": "2026-10-09", "got": args}

    def boom(args, call_ctx):
        raise RuntimeError("工具故意炸")

    def save_it(args, call_ctx):
        WRITES.append(args)
        return {"saved": args}

    ctx.mcp.tool("now", {"description": "返回当前日期", "parameters": {"type": "object", "properties": {}}}, now)
    ctx.mcp.tool("boom", {"description": "会抛异常"}, boom)
    ctx.mcp.tool("save_it", {"description": "写工具（须经草稿确认）", "write": True}, save_it)
''')

sys.path.insert(0, str(ROOT))
from app import agent_tools as T  # noqa: E402
from core.plugins import loader as L  # noqa: E402
from core.plugins import runtime as RT  # noqa: E402

kernel_tools = list(T.TOOL_NAMES)

print("== 1. 加载前：插件工具不存在 ==")
RT.set_current(None)
check("未加载时插件工具为空", T.plugin_tool_meta() == {}, str(T.plugin_tool_meta()))
check("未加载时全量工具 = 内核工具", list(T.all_tool_names()) == kernel_tools)
st = T.execute("p_tooled__now", {}, {})
check("未加载时调用插件工具 → 未知工具", st.get("ok") is False and "未知工具" in str(st.get("error")), str(st)[:70])

print("\n== 2. 加载夹具插件（含写工具）==")
res = L.load(roots=[("user", FIX)], workspace=FIX, core_version="v261009.0")
meta = T.plugin_tool_meta()
names = list(T.all_tool_names())
check("读工具与写工具都进入工具面", {"p_tooled__now", "p_tooled__boom", "p_tooled__save_it"} <= set(names), str(names))
check("写工具的 write 标记为真", meta.get("p_tooled__save_it", {}).get("write") is True)
check("is_write_tool 认得插件写工具", T.is_write_tool("p_tooled__save_it") and not T.is_write_tool("p_tooled__now"))
check("加载记录里说明写工具走草稿确认流", any("草稿确认流" in n for n in res.notes), str([n for n in res.notes if "写工具" in n])[:120])

print("\n== 3. 读工具调用 ==")
r = T.execute("p_tooled__now", {"x": 1}, {})
check("插件读工具可调用且带 plugin 字段", r.get("ok") is True and r.get("plugin") == "tooled" and r.get("got") == {"x": 1},
      json.dumps(r, ensure_ascii=False)[:110])
r2 = T.execute("p_tooled__boom", {}, {})
check("handler 抛异常只影响该次调用", r2.get("ok") is False and "插件工具失败（tooled）" in str(r2.get("error")),
      str(r2.get("error"))[:80])
r3 = T.execute("p_tooled__now", {}, {"tools": ["kb_search"]})
check("人设白名单能限制插件工具", r3.get("ok") is False and "未授权" in str(r3.get("error")), str(r3.get("error"))[:60])

print("\n== 4. 写工具：confirm 只出草稿、不执行 ==")
mod = sys.modules["erw_plugin_tooled"]
mod.WRITES.clear()
pending = T.execute("p_tooled__save_it", {"v": 1}, {"write_mode": "confirm"})
check("confirm 模式返回 pending + draft_id", pending.get("pending") is True and str(pending.get("draft_id", "")).startswith("draft-"),
      json.dumps(pending, ensure_ascii=False)[:110])
check("**草稿阶段没有真的执行**（插件未被调用）", mod.WRITES == [], str(mod.WRITES))
check("草稿记录了插件归属", (pending.get("draft") or {}).get("plugin") == "tooled")

print("\n== 5. 确认 / 拒绝 ==")
confirmed = T.confirm_draft(pending["draft_id"])
check("确认后真正执行了插件写工具", confirmed.get("status") == "confirmed" and mod.WRITES == [{"v": 1}], str(mod.WRITES))
pending2 = T.execute("p_tooled__save_it", {"v": 2}, {"write_mode": "confirm"})
T.reject_draft(pending2["draft_id"])
check("拒绝后不执行", mod.WRITES == [{"v": 1}], str(mod.WRITES))
direct = T.execute("p_tooled__save_it", {"v": 3}, {"write_mode": "direct"})
check("direct 模式直接执行", direct.get("ok") is True and mod.WRITES[-1] == {"v": 3}, str(mod.WRITES))

print("\n== 6. HTTP 面（/api/agent/tools）==")
port = 8900 + (os.getpid() % 80)
env = dict(os.environ, ERW_PLUGINS_ROOTS=str(FIX))
proc = subprocess.Popen(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0,r'%s'); import server;"
     "httpd,cfg,url=server.build_server(port_override=%d, auto_open_browser=False);"
     "httpd.serve_forever(poll_interval=0.25)" % (ROOT, port)],
    cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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


try:
    ok = wait_ready()
    check("服务起来了", ok, f"port={port}")
    if ok:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/agent/tools", timeout=10) as r_:
            tools = json.loads(r_.read().decode("utf-8"))
        got = {t["name"]: t for t in tools}
        check("/api/agent/tools 含插件读写工具",
              {"p_tooled__now", "p_tooled__save_it"} <= set(got), str([n for n in got if n.startswith("p_")]))
        check("写工具在清单里带 write=true", got.get("p_tooled__save_it", {}).get("write") is True)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()

print("\n== 7. 真实插件：每个工具的 handler 都要符合内核调用约定 ==")
# 来历：内核用 `handler(args, call_ctx)` 调（app/agent_tools.py:362）；插件若只写 `def tool_x(args)`，
# Agent 真调用时才 TypeError。上面第 3 节的合成插件签名是对的，所以**发现不了真实插件踩坑**
# （本轮 report-export / backup-snapshot / milestone-calendar 三个插件都踩了）。
# 这里用 `signature.bind({}, {})` 做静态判定：精确、零副作用（不执行读工具就不必担心导出/备份被真跑）。
import inspect  # noqa: E402
import sys as _sys  # noqa: E402

import server as _server  # noqa: E402

_sys.path.insert(0, str(ROOT / "tests" / "support"))
from fixture_cleanup import restore_many, snap_many  # noqa: E402

# 装载**全部**插件会执行它们的 register()，而 register() 里 `ctx.storage.ensure()` 会合法地
# 创建插件自己的命名空间目录——夹具负责把本次新增的（以及原本就是空的）目录还原掉，别留在用户 Workspace 里。
_ns_roots = [ROOT / "Workspace" / "System" / "Plugins", ROOT / "Workspace" / "Plugins"]
_ns_before = snap_many([p for root in _ns_roots if root.is_dir() for p in root.iterdir() if p.is_dir()])

# 安全闸门：装载**全部**插件会执行它们的 register()——backup-snapshot 的自动任务 run_on_start=True，
# 不拦住就会在检查期间真的往用户 Workspace 里打一份快照。先临时把它的自动开关关掉，事后按原样恢复。
_cfg_path = ROOT / "config" / "plugins" / "backup-snapshot.json"
_cfg_before = _cfg_path.read_bytes() if _cfg_path.is_file() else None
_cfg_path.parent.mkdir(parents=True, exist_ok=True)
_cfg_path.write_text(json.dumps({"auto_enabled": False}, ensure_ascii=False, indent=2), encoding="utf-8")

real = L.load(roots=_server.plugin_roots(ROOT), workspace=ROOT / "Workspace",
              core_version=_server._core_version(), enabled_only=False)
check("真实插件集装得起来（含默认不启用的可选插件）", len(real.order) >= 8, str(real.order))
bad_sig = []
for tool in real.mcp_tools:
    sig = inspect.signature(tool.handler)
    try:
        sig.bind({}, {})
    except TypeError as exc:
        bad_sig.append(f"{tool.exposed_name}{sig} → {exc}")
check("全部插件工具都能按 (args, call_ctx) 调用",
      not bad_sig, "；".join(bad_sig)[:260])
check("工具对外名都带 p_<id>__ 前缀",
      all(t.exposed_name.startswith(f"p_{t.plugin_id}__") for t in real.mcp_tools),
      str([t.exposed_name for t in real.mcp_tools]))
after_load = {t.exposed_name for t in real.mcp_tools}
meta_all = {m["name"]: m for m in T.list_tool_meta()}
check("真实插件的工具都进了元信息面（供人设白名单）",
      after_load <= set(meta_all), str(sorted(after_load - set(meta_all))))
check("write 标记与实际一致",
      all(bool(meta_all[n].get("write")) == T.is_write_tool(n) for n in after_load),
      str({n: (meta_all.get(n, {}).get("write"), T.is_write_tool(n)) for n in after_load}))
# 后台任务：真实插件集里注册的任务必须在调度器里可见（且这里立刻停掉，别真跑）
from core.plugins import jobs as _jobs  # noqa: E402

declared_jobs = {j["plugin"]: j["name"] for j in (_jobs.current().as_list() if _jobs.current() else [])}
check("插件注册的后台任务可见（backup-snapshot 的 auto）",
      declared_jobs.get("backup-snapshot") == "auto", str(declared_jobs))
_snap_dir = ROOT / "Workspace" / "System" / "Plugins" / "backup-snapshot" / "snapshots"
_snaps_before = {p.name for p in _snap_dir.glob("snapshot-*.zip")} if _snap_dir.is_dir() else set()
_jobs.shutdown()
check("检查结束即停掉调度器（不留后台线程）", _jobs.current() is None)


def _restore_cfg(path, before, tries=6, wait=0.25):
    """还原/删除备份插件配置。Windows 上另一个进程（比如 run_tests 起的临时服务）可能短暂持有
    该文件句柄 → 直接 unlink 会 PermissionError（实测踩到），这里重试几次再放弃并如实报告。"""
    import time as _time
    last = None
    for _ in range(tries):
        try:
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(before)
            return None
        except PermissionError as exc:          # 文件被占用：等一下再试
            last = exc
            _time.sleep(wait)
    return last


_cfg_err = _restore_cfg(_cfg_path, _cfg_before)
check("备份插件配置已按原样恢复",
      (_cfg_path.read_bytes() if _cfg_path.is_file() else None) == _cfg_before,
      f"被别的进程占用，重试 6 次仍失败：{_cfg_err}")
_snaps_after = {p.name for p in _snap_dir.glob("snapshot-*.zip")} if _snap_dir.is_dir() else set()
check("检查期间没有产生快照", _snaps_after == _snaps_before,
      f"before={sorted(_snaps_before)} after={sorted(_snaps_after)}")

# 还原插件命名空间：删本次新增文件；原先不存在或原本为空的目录整体删掉
for root in _ns_roots:
    if root.is_dir():
        for child in root.iterdir():
            if child.is_dir() and str(child) not in _ns_before:
                _ns_before[str(child)] = (False, set())
_restored = restore_many(_ns_before)
_kept = {k: v for k, v in _restored.items() if v}
check("插件命名空间已还原（不留本次新增文件/空目录）", not _kept, str(_kept))

RT.set_current(None)
print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（插件写工具已由内核统一走草稿确认，不再有绕过确认的落盘口子）")
