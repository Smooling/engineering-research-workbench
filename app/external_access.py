"""外部接入授权（v261009.38）——**谁可以改知识库**。

背景：内核自带的 Agent 写工具走草稿闸门，但**外部通道**此前没有闸门：
`mcp/` 的 5 个写工具直写知识库（文档已如实写明）。本模块给外部接入一个**默认拒绝、显式授权**的开关。

设置存 `config/external-access.json`（独立小文件，不动 `app.json` 的既有结构）：

```json
{ "mcp_write": false, "plugin_write": true }
```

- `mcp_write`（默认 **false**）：允许 MCP / 外部 AI 客户端写入知识库（建、改、改名、改挂、删除）；
- `plugin_write`（默认 **true**）：允许**插件**通过 `core_api.entry_update` 写条目正文/字段。
  关掉它 = "只读工作台"（插件仍可写自己的命名空间与配置，只是不碰知识库）。

只读操作永远允许；授权只影响写入。文件损坏/缺失时按**保守值**处理并如实说明。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import DATA_ROOT

ROOT = DATA_ROOT
CONFIG_PATH = ROOT / "config" / "external-access.json"

DEFAULTS: dict[str, bool] = {"mcp_write": False, "plugin_write": True}

#: 文案与风险提示（设置页直接展示，避免"开关是干什么的"要靠猜）
LABELS: dict[str, dict[str, str]] = {
    "mcp_write": {
        "label": "允许外部 MCP 客户端写入知识库",
        "detail": "打开后，MCP 客户端（IDE / 外部 Agent）可新建、修改、改名、改挂、删除条目，"
                  "**不经过界面上的草稿确认**。默认关闭（只读）。",
        "risk": "外部客户端可绕过草稿闸门直接改数据；请只在受信任的客户端里打开。",
    },
    "plugin_write": {
        "label": "允许插件写入知识库",
        "detail": "插件通过 core_api.entry_update 改条目正文/字段（如文献阅读区把批注写进笔记）。"
                  "关闭后插件只能写自己的命名空间与配置。",
        "risk": "关闭会影响依赖写入的插件功能（例如「批注加入笔记」会失败）。",
    },
}


def _read_raw() -> tuple[dict[str, Any], str]:
    """返回 (数据, 说明)。读不到/坏了都返回保守默认值，并带上原因。"""
    if not CONFIG_PATH.is_file():
        return dict(DEFAULTS), "配置文件不存在，按默认值（只读）处理"
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return dict(DEFAULTS), f"配置读取失败（{type(exc).__name__}），按默认值（只读）处理"
    if not isinstance(data, dict):
        return dict(DEFAULTS), "配置不是对象，按默认值（只读）处理"
    return data, ""


def current() -> dict[str, Any]:
    """当前授权状态（含默认值补齐、文案与说明），供设置页展示。"""
    raw, note = _read_raw()
    flags = {key: bool(raw.get(key, default)) for key, default in DEFAULTS.items()}
    return {
        "flags": flags,
        "defaults": dict(DEFAULTS),
        "items": [
            {"id": key, "value": flags[key], **LABELS[key]}
            for key in DEFAULTS
        ],
        "path": str(CONFIG_PATH),
        "note": note,
        "mcp_write_effective": flags["mcp_write"],
        "plugin_write_effective": flags["plugin_write"],
    }


def allowed(scope: str) -> tuple[bool, str]:
    """`scope` 取 `mcp_write` / `plugin_write`。返回 (是否允许, 拒绝原因)。"""
    if scope not in DEFAULTS:
        return True, ""
    state = current()
    if state["flags"].get(scope):
        return True, ""
    label = LABELS.get(scope, {}).get("label", scope)
    return False, (f"外部写入未授权：{label} = 关闭。"
                   f"去「设置 → 外部接入」打开；配置在 {CONFIG_PATH}")


def save(payload: dict[str, Any]) -> dict[str, Any]:
    """只接受已知开关（布尔），其余忽略；原子写。"""
    raw, _note = _read_raw()
    flags = {key: bool(raw.get(key, default)) for key, default in DEFAULTS.items()}
    changed: list[str] = []
    for key in DEFAULTS:
        if key in payload:
            value = bool(payload[key])
            if value != flags[key]:
                changed.append(f"{key}: {flags[key]} → {value}")
            flags[key] = value
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(flags, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    out = current()
    out["changed"] = changed
    return out
