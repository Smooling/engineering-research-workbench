"""__NAME__ · 插件后端（模板）

这是**能直接跑**的最小后端：注册两个 HTTP 路由、一个 Agent 工具、读写自己的配置。
照它改就行——插件只通过 `ctx`（与 `core_api`）接触内核，**不需要、也不应该修改内核代码**。

改名前先读同目录 `README.md`；自动改名用 `python tools/new_plugin.py <id>`。

`register(ctx)` 里可用的接缝（完整清单见 `docs/PLUGIN_SPEC.md` §6.1）：
- `ctx.routes.get/post/...(相对路径, handler)` → 自动挂到 `/api/plugins/__ID__/…`
- `ctx.mcp.tool(裸名, spec, handler)` → 对 Agent 暴露为 `p_<id>__<裸名>`；`spec` 里写
  `"write": True` 的写工具会**自动**走内核的草稿确认闸门，插件不用自己实现确认流
- `ctx.config_read()/config_write()` → `config/plugins/__ID__.json`
- `ctx.storage.system / .workspace / .cache_db` → 只有自己的命名空间（I5）
- `ctx.events.on("llm.usage", cb)` → 订阅内核广播（可选）
- `ctx.log(msg)` → 带插件前缀的日志

路由 handler 签名：`handler(request) -> dict | list`，其中
`request = {"method", "path", "query": {k: [v, ...]}, "body": {...}}`。
**别抛异常当控制流**：异常会让该请求返回 500（只影响这一次请求），要表达"不可用"就直接返回。
"""

from __future__ import annotations

import time

#: 插件自己的配置默认值；用户改过的值存在 config/plugins/__ID__.json
DEFAULT_CONFIG = {
    "greeting": "你好",
}


def register(ctx):
    """内核加载插件时调用一次；这里注册的东西会随「停用插件」一起消失（不用自己清理）。"""

    def config() -> dict:
        cfg = dict(DEFAULT_CONFIG)
        loaded = ctx.config_read({})
        if isinstance(loaded, dict):
            cfg.update({k: v for k, v in loaded.items() if k in DEFAULT_CONFIG})
        return cfg

    # ---- HTTP 路由：只写相对路径，内核负责加 /api/plugins/__ID__/ 前缀与命名空间隔离 ----
    def route_hello(request):
        name = str((request["query"].get("name") or [""])[0]) or ctx.id
        return {
            "ok": True,
            "plugin": ctx.id,
            "greeting": f"{config()['greeting']}，{name}",
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def route_get_config(request):
        return config()

    def route_set_config(request):
        body = request.get("body") or {}
        cfg = config()
        if "greeting" in body:
            cfg["greeting"] = str(body["greeting"])
        ctx.config_write(cfg)
        return cfg

    ctx.routes.get("hello", route_hello)
    ctx.routes.get("config", route_get_config)
    ctx.routes.post("config", route_set_config)

    # ---- Agent 工具：读工具直接可用；写工具由内核统一走草稿确认流 ----
    # 注意 handler 签名：内核用 `handler(args, call_ctx)` 调用（call_ctx 里有人设/写模式等调用上下文），
    # 少写一个参数会在 Agent 调用时报 TypeError——只用一个参数时也要保留第二个形参。
    def tool_ping(args, call_ctx=None):
        return {"pong": True, "plugin": ctx.id, "note": str((args or {}).get("note") or "")}

    ctx.mcp.tool("ping", {
        "description": "示例工具：回一个 pong，用来确认插件工具已接入 Agent",
        "parameters": {
            "type": "object",
            "properties": {"note": {"type": "string", "description": "随便写点什么，会原样返回"}},
        },
    }, tool_ping)

    ctx.log(f"__NAME__ 插件已注册（/api/plugins/{ctx.id}/hello|config）")
