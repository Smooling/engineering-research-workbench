"""engineering-research-workbench 的 MCP 服务器。

零第三方依赖：仅使用标准库实现 MCP stdio 协议，并通过 :mod:`mcp.bridge`
复用工作台自身的 ``app`` 包，使 Agent 的写入与界面操作在落盘语义上完全一致
（原子写入、删除进回收站、活动日志、项目注册表、SQLite 索引同步）。

启动方式（工作项根目录下）：``python -m mcp.server``
"""

from __future__ import annotations

__all__ = ["bridge", "constraints", "naming", "protocol", "tools_knowledge", "tools_workspace"]
