"""插件运行期状态 —— 当前已加载的插件集合（进程级单例）。

`loader.load()` 结束时把结果登记到这里；消费者（HTTP 路由分发、内置 Agent 的工具面、
健康面板）只读这里，避免各自持有副本或反向依赖 `server.py`。

**只读约定**：外部只调 `current()` / `tools()` / `route_map()`，不要自己 set 一个手搓的
`LoadResult`（唯一写入点是 `loader.load()`）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - 仅为类型提示，避免运行期循环导入
    from .loader import LoadResult

_current: "LoadResult | None" = None


def set_current(result: "LoadResult | None") -> None:
    global _current
    _current = result


def current() -> "LoadResult | None":
    return _current


def is_loaded() -> bool:
    return _current is not None


def tools() -> dict[str, Any]:
    """已启用插件注册的 MCP 工具：`{对外名: McpTool}`（未加载时为空表）。"""
    result = _current
    if result is None:
        return {}
    return {tool.exposed_name: tool for tool in result.mcp_tools}


def tool_specs() -> dict[str, dict]:
    """`{对外名: 工具规格}`，供内置 Agent 的工具清单/协议提示复用。"""
    return {name: dict(tool.spec or {}) for name, tool in tools().items()}


def plugin_of(tool_name: str) -> str:
    tool = tools().get(tool_name)
    return tool.plugin_id if tool else ""


def route_map() -> dict:
    result = _current
    return result.route_map if result is not None else {}


def summary() -> dict:
    """健康面板/诊断用的一行式摘要。"""
    result = _current
    if result is None:
        return {"loaded": False, "plugins": [], "routes": 0, "tools": 0, "failures": []}
    return {
        "loaded": True,
        "plugins": list(result.order),
        "routes": len(result.route_map),
        "tools": len(result.mcp_tools),
        "failures": result.failures(),
        "notes": list(result.notes),
    }
