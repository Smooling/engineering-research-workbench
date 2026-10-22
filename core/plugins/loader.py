"""插件加载器 —— 执行 `register(ctx)` 并收集扩展点（PLUGIN_SPEC §4.2 顺序、§6 隔离、§7 冲突）。

**本模块是「执行层」**：与 `registry.py`（只发现/校验）分开，好处是校验可以在安装前、
CLI 里、测试夹具上安全地跑，而执行只在服务启动时发生。

隔离不变量在这里落地：

- **I4 单插件失败不影响内核与其它插件**：每个插件独立 `try/except`；失败记为 `failed`
  + 可读原因（I11），继续下一个；已注册成功的插件保持可用。
- **I9 加载顺序无关**：按拓扑顺序注册（前提插件先注册），但任何插件都不因顺序而崩。
- **I3 插件只依赖 core_api**：加载器把 `core_api` 放进 `sys.modules` 供插件 import；
  插件 import 内核私有模块不会在这里被拦（静态检查由 `tools/plugin_check.py` 负责内核侧，
  插件侧目前靠约定 + 审核，见模块末尾说明）。
- **§7.7 冲突检查**：路由/工具前缀与**内核已有路由**或**已注册插件**重复 → 该路由被拒
  （记原因），不影响该插件的其它路由。
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import manifest as M
from . import jobs
from . import registry as R
from . import runtime
from .context import McpTool, PluginContext, PluginContractError, RawResponse, Route, json_safe


@dataclass
class LoadedPlugin:
    id: str
    dir: Path
    source: str
    manifest: dict
    ctx: PluginContext | None = None
    state: str = "available"      # available | failed
    reason: str = ""
    routes: list[Route] = field(default_factory=list)
    mcp_tools: list[McpTool] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "source": self.source, "dir": str(self.dir), "state": self.state,
            "reason": self.reason,
            "routes": [f"{r.method} {r.full_path}" for r in self.routes],
            "mcp_tools": [t.exposed_name for t in self.mcp_tools],
        }


@dataclass
class LoadResult:
    plugins: dict[str, LoadedPlugin] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def route_map(self) -> dict[tuple[str, str], Route]:
        """(METHOD, 完整路径) → Route，供 HTTP 分发直接查表。"""
        out: dict[tuple[str, str], Route] = {}
        for plugin in self.plugins.values():
            for route in plugin.routes:
                out[(route.method, route.full_path)] = route
        return out

    @property
    def mcp_tools(self) -> list[McpTool]:
        return [t for p in self.plugins.values() for t in p.mcp_tools]

    def failures(self) -> list[dict]:
        return [{"id": p.id, "reason": p.reason} for p in self.plugins.values() if p.state == "failed"]

    def as_dict(self) -> dict:
        return {
            "order": self.order,
            "plugins": [self.plugins[pid].as_dict() for pid in self.order],
            "failures": self.failures(),
            "notes": self.notes,
            "routes": [f"{m} {p}" for (m, p) in sorted(self.route_map)],
            "mcp_tools": [t.exposed_name for t in self.mcp_tools],
        }


def _import_entry(candidate: R.PluginCandidate, entry: str):
    """从文件路径加载插件入口模块（名字唯一，避免与内核模块撞名）。"""
    path = Path(candidate.dir) / entry
    mod_name = f"erw_plugin_{candidate.id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载入口 {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return module


def load(
    *,
    roots: list[tuple[str, Path]] | None = None,
    workspace: Path | None = None,
    core_version: str = "",
    enabled_only: bool = True,
) -> LoadResult:
    """按拓扑顺序加载「可用且启用」的插件，执行它们的 `register(ctx)`。

    顺带完成 §5 的「安装」动作：先把各根下的 `*.zip` 单文件包解包成 `plugins/<id>/`
    （PLUGIN_SPEC §2），再扫描加载——所以「把包丢进 plugins/」在服务启动时就生效。
    """
    result = LoadResult()
    for outcome in R.install_packages(roots, workspace=workspace):
        result.notes.append(outcome.note())
    candidates, notes = R.discover(roots)
    result.notes.extend(notes)
    R.resolve(candidates, core_version)
    install = R.read_install_state(workspace) if workspace else {"plugins": {}}

    # 拓扑顺序（registry.resolve 已经算好，这里重算一次保证只看可加载项）
    order, _cycle = R._blocked_within_cycles(candidates)

    # 后台任务：**先停旧调度器再建新的**——热重载/停用插件时，旧任务的线程必须立刻不再被调度
    scheduler = jobs.replace()

    for pid in order:
        cand = candidates[pid]
        if cand.state != "available":
            continue
        if enabled_only and not R.effective_enabled(cand, install):
            continue
        plugin = LoadedPlugin(id=pid, dir=Path(cand.dir), source=cand.source,
                              manifest=dict(cand.manifest or {}))
        result.plugins[pid] = plugin
        result.order.append(pid)

        entry = str((cand.manifest or {}).get("entry") or "").strip()
        if not entry:
            continue  # 纯前端插件：没有后端要执行

        ctx = PluginContext(pid, cand.manifest or {}, Path(cand.dir), scheduler=scheduler)
        try:
            module = _import_entry(cand, entry)
            register = getattr(module, "register", None)
            if not callable(register):
                raise PluginContractError("入口模块没有 register(ctx) 函数")
            register(ctx)
        except Exception as exc:  # I4：单插件失败不影响内核与其它插件
            plugin.state = "failed"
            plugin.reason = f"{type(exc).__name__}: {exc}"
            result.notes.append(f"插件 {pid} 注册失败（内核与其它插件不受影响）：{plugin.reason}")
            if not isinstance(exc, PluginContractError):
                traceback.print_exc()
            continue

        plugin.ctx = ctx
        # §7.7 冲突检查：路由**声明期**已强制相对路径（裸 /api/* 会被 RouteTable 直接拒），
        # 且完整路径天然带 `/api/plugins/<id>/` 前缀，所以与内核路由不可能撞。
        # 这里只防插件之间撞：同 (METHOD, 完整路径) 已在别处注册 → 拒该条并记原因。
        accepted: list[Route] = []
        taken = {(r.method, r.full_path) for p in result.plugins.values() for r in p.routes}
        for route in ctx.routes.routes:
            key = (route.method, route.full_path)
            if key in taken:
                result.notes.append(f"插件 {pid} 的路由 {route.method} {route.full_path} 与已注册路由冲突，已拒绝")
                continue
            accepted.append(route)
            taken.add(key)
        plugin.routes = accepted
        # 工具：读工具直接接入内置 Agent；**写工具也接入，但由内核统一走草稿确认流**
        # （`app/agent_tools.execute` 在 write_mode != direct 时先生成草稿，确认后才执行）——
        # 插件自己拿不到 save_draft，所以这道闸门必须在内核侧，不能指望插件自觉。
        plugin.mcp_tools = list(ctx.mcp.tools)
        write_tools = [t.name for t in plugin.mcp_tools if bool((t.spec or {}).get("write"))]
        if write_tools:
            result.notes.append(f"插件 {pid} 注册了写工具 {write_tools}（调用时由内核走草稿确认流）")

        # 后台任务：声明一致性只提示不拦（manifest 的 `jobs` 是给人看的清单，真正生效的是 register 里的注册）
        declared = {str(j.get("id") or "") for j in ((cand.manifest or {}).get("jobs") or [])
                    if isinstance(j, dict)}
        if ctx.jobs.names:
            result.notes.append(f"插件 {pid} 注册了后台任务 {ctx.jobs.names}（内核调度，见 core/plugins/jobs.py）")
            undeclared = [n for n in ctx.jobs.names if n not in declared]
            if undeclared:
                result.notes.append(f"插件 {pid} 的任务 {undeclared} 没在 plugin.json 的 jobs 里声明"
                                    f"（建议补上，便于用户在设置页看到它）")

    if scheduler.jobs:
        scheduler.start()

    runtime.set_current(result)
    return result


def dispatch(result: LoadResult, method: str, path: str, query: dict, body: dict | None = None):
    """按路由表分发一次插件请求。返回 (状态码, 载荷)。

    handler 抛异常 → 500 且**只影响该次请求**，错误信息带插件 id（便于排障），
    内核继续服务。handler 返回 `ctx.raw(...)`（`RawResponse`）时**不做 JSON 包装**，
    由 HTTP 层原样写回——插件产出文件（下载、导出、图表）靠它。
    """
    route = result.route_map.get((method.upper(), path))
    if route is None:
        return 404, {"error": "not_found", "message": f"插件没有该路由：{method} {path}"}
    request = {"method": method.upper(), "path": path, "query": query, "body": body or {}}
    try:
        payload = route.handler(request)
    except Exception as exc:
        return 500, {"error": type(exc).__name__, "plugin": route.plugin_id,
                     "message": str(exc)}
    if isinstance(payload, RawResponse):
        return payload.status, payload
    return 200, json_safe(payload if payload is not None else {"ok": True})
