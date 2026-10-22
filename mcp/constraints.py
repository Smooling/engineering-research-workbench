"""MCP 侧约束入口 —— 契约数据已迁至 ``core/contracts/kinds.py``（单一事实来源）。

本模块只是再导出的门面：``mcp/tools_knowledge.py``、``mcp/tools_workspace.py``、
``mcp/server.py``、``mcp/naming.py`` 继续 ``from . import constraints as C`` 即可，
调用点无需改动。规则文本与矩阵**不要再写在这里**——要改契约请改 ``core/contracts/kinds.py``。
"""

from __future__ import annotations

from core.contracts.kinds import *  # noqa: F401,F403  —— 门面：全部契约名称原样导出