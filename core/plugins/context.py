"""插件上下文（`ctx`）—— `register(ctx)` 拿到的那个对象。

对应 PLUGIN_SPEC §6 的命名空间隔离与 REFACTOR_PLAN §6.3 的扩展点：

| 扩展点 | ctx 上的入口 | 命名空间约束 |
| --- | --- | --- |
| HTTP 路由 | `ctx.routes.get/post/delete(rel, handler)` | 相对路径；内核挂到 `/api/plugins/<id>/` 下，**禁止**注册裸 `/api/*` |
| MCP 工具 | `ctx.mcp.tool(name, spec, handler)` | 裸名；对外名由内核加 `p_<id>__` |
| 存储 | `ctx.storage` | 只给插件自己的路径对象（I5） |
| 配置 | `ctx.config_read()/config_write()` | `config/plugins/<id>.json` |
| 事件订阅 | `ctx.events.on(name, cb)` | 订阅内核广播（如 `llm.usage`），返回退订函数；不需在 manifest 里声明 |
| 后台任务 | `ctx.jobs.add(name, cb, every_minutes=…)` | 内核调度、状态与日志；**插件不要自己起线程**（热重载会留下幽灵线程） |
| 日志 | `ctx.log(msg)` | 自动带插件前缀 |

**尚未实现**（不假装有）：`ctx.search.addSection`（往检索结果里加分区）、`process` 执行层（独立进程插件）。
要用再加，并同步 PLUGIN_SPEC §6.2 的能力矩阵。

路由处理器签名：`handler(request) -> dict | list`，其中
`request = {"method", "path", "query": {k: [v, ...]}, "body": {...}}`。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import core_api

REL_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


class PluginContractError(RuntimeError):
    """插件违反命名空间/扩展点契约（§6.3、§7.7）。"""


@dataclass
class Route:
    method: str
    path: str          # 插件内相对路径，如 "forecast"
    handler: Callable[[dict], Any]
    plugin_id: str = ""

    @property
    def full_path(self) -> str:
        return f"/api/plugins/{self.plugin_id}/{self.path}".rstrip("/")


@dataclass
class McpTool:
    name: str          # 裸名，如 "weather_now"
    spec: dict
    handler: Callable[..., Any]
    plugin_id: str = ""

    @property
    def exposed_name(self) -> str:
        return f"p_{self.plugin_id}__{self.name}"


@dataclass
class PluginStorage:
    """插件只能拿到**自己命名空间内**的路径（I5）。"""
    plugin_id: str
    plugin_dir: Path = field(default_factory=lambda: Path("."))

    @property
    def cache_db(self) -> Path:
        return core_api.cache_db(self.plugin_id)

    @property
    def workspace(self) -> Path:
        return core_api.workspace_dir(self.plugin_id)

    @property
    def system(self) -> Path:
        return core_api.system_dir(self.plugin_id)

    @property
    def config(self) -> Path:
        return core_api.config_path(self.plugin_id)

    def ensure(self) -> None:
        for path in (self.workspace, self.system):
            path.mkdir(parents=True, exist_ok=True)


class RouteTable:
    """收集插件声明的路由；路径合法性在**声明时**就校验（早失败、错误信息可执行）。"""

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self.routes: list[Route] = []

    def _add(self, method: str, path: str, handler: Callable[[dict], Any]) -> Route:
        if not callable(handler):
            raise PluginContractError(f"路由 {path} 的 handler 不可调用")
        rel = str(path or "").strip().strip("/")
        if not rel:
            raise PluginContractError("路由路径不能为空")
        if path.startswith("/") or rel.startswith("api/"):
            raise PluginContractError(
                f"路由 `{path}` 必须是相对路径且不得写 `api/`；内核会挂到 "
                f"`/api/plugins/{self.plugin_id}/` 下"
            )
        if not REL_PATH_RE.match(rel) or ".." in rel.split("/"):
            raise PluginContractError(f"路由 `{path}` 含非法字符或路径穿越")
        route = Route(method=method, path=rel, handler=handler, plugin_id=self.plugin_id)
        if any(r.method == route.method and r.path == route.path for r in self.routes):
            raise PluginContractError(f"路由 {method} {rel} 重复声明")
        self.routes.append(route)
        return route

    def get(self, path: str, handler): return self._add("GET", path, handler)
    def post(self, path: str, handler): return self._add("POST", path, handler)
    def put(self, path: str, handler): return self._add("PUT", path, handler)
    def patch(self, path: str, handler): return self._add("PATCH", path, handler)
    def delete(self, path: str, handler): return self._add("DELETE", path, handler)


class McpRegistry:
    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self.tools: list[McpTool] = []

    def tool(self, name: str, spec: dict, handler: Callable[..., Any]) -> McpTool:
        raw = str(name or "").strip()
        if not raw or not re.match(r"^[a-z][a-z0-9_]*$", raw):
            raise PluginContractError(f"MCP 工具名 `{name}` 不合法（小写字母开头，只含小写字母/数字/下划线）")
        if raw.startswith("p_") or "__" in raw:
            raise PluginContractError(f"MCP 工具名 `{name}` 不要自带前缀；对外名由内核加 `p_{self.plugin_id}__`")
        if not callable(handler):
            raise PluginContractError(f"工具 {name} 的 handler 不可调用")
        tool = McpTool(name=raw, spec=dict(spec or {}), handler=handler, plugin_id=self.plugin_id)
        if any(t.name == raw for t in self.tools):
            raise PluginContractError(f"MCP 工具 `{raw}` 重复声明")
        self.tools.append(tool)
        return tool


class EventTable:
    """`ctx.events` —— 订阅内核广播的事实（§6.3；实现见 `core/events.py`）。

    与路由/工具不同，**订阅不需要在 manifest 里声明**：它不对外暴露任何东西（不占命名空间、
    不被前端发现），只是插件在 `register(ctx)` 期间挂上回调。停用插件即不再收到广播。
    """

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self.subscriptions: list[str] = []   # 已订阅的事件名（体检/诊断用）

    def on(self, name: str, callback: Callable[[dict], Any]) -> Callable[[], None]:
        from core import events as _events

        off = _events.on(name, callback)
        self.subscriptions.append(str(name))

        def unsubscribe() -> None:
            off()
            if name in self.subscriptions:
                self.subscriptions.remove(str(name))

        return unsubscribe


@dataclass
class RawResponse:
    """插件路由的**原样响应**：二进制/HTML/CSV 这类不能当 JSON 发出去的东西。

    用法（插件侧）：`return ctx.raw(data, content_type="application/pdf", filename="x.pdf")`。
    内核的 `dispatch` 见到它就**不做 JSON 包装**，直接把字节与头写回浏览器——
    这是「插件产出文件」这一类插件的通用出口（报告导出、备份下载、图表导出…）。
    """

    body: bytes
    content_type: str = "application/octet-stream"
    filename: str = ""
    status: int = 200


class PluginContext:
    """`register(ctx)` 的参数。插件只能通过它接触内核（§6）。"""

    def __init__(self, plugin_id: str, manifest: dict, plugin_dir: Path,
                 scheduler=None) -> None:
        from . import jobs as _jobs

        self.id = plugin_id
        self.manifest = dict(manifest or {})
        self.dir = Path(plugin_dir)
        self.api_version = int(self.manifest.get("api_version") or core_api.API_VERSION)
        self.routes = RouteTable(plugin_id)
        self.mcp = McpRegistry(plugin_id)
        self.storage = PluginStorage(plugin_id, self.dir)
        self.events = EventTable(plugin_id)
        # 调度器由 loader 装配（本轮唯一的那个）；没有它时 jobs.add 会明确报错，而不是静默丢弃
        self.jobs = _jobs.JobTable(plugin_id, scheduler or _jobs.current() or _jobs.replace())

    # ---- 便捷方法（插件最常用的几件事）----
    def log(self, message: str) -> None:
        core_api.log(self.id, message)

    def raw(self, body: bytes | str, *, content_type: str = "application/octet-stream",
            filename: str = "", status: int = 200) -> RawResponse:
        """原样响应：`raw` 内容直接写回浏览器（`str` 按 UTF-8 编码）。见 `RawResponse`。"""
        data = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        return RawResponse(body=data, content_type=content_type, filename=str(filename or ""),
                           status=int(status or 200))

    def config_read(self, default: dict | None = None) -> dict:
        return core_api.read_config(self.id, default)

    def config_write(self, data: dict) -> None:
        core_api.write_config(self.id, data)

    def json_response(self, data: Any) -> Any:
        """显式声明返回 JSON（当前直接返回 dict/list 即可，保留为语义化写法）。"""
        return data

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "api_version": self.api_version,
            "routes": [f"{r.method} {r.full_path}" for r in self.routes.routes],
            "mcp_tools": [t.exposed_name for t in self.mcp.tools],
            "storage": {
                "cache_db": str(self.storage.cache_db),
                "workspace": str(self.storage.workspace),
                "system": str(self.storage.system),
                "config": str(self.storage.config),
            },
        }


def json_safe(value: Any) -> Any:
    """把插件返回值压成可 JSON 序列化的形状（不可序列化时退化为字符串）。"""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)
