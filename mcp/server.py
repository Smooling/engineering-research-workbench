"""MCP stdio 服务入口 —— 暴露工程科研工作台的知识库约束与操作工具。

运行：在工作项根目录执行 ``python -m mcp.server``（或直接 ``python mcp/server.py``）。
"""

from __future__ import annotations

import copy
import json
import sys
import traceback
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # 支持 `python mcp/server.py` 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from mcp.server import main as _main  # type: ignore[no-redef]

    raise SystemExit(_main())

from . import constraints as C  # noqa: E402
from .bridge import Workbench, WorkbenchError  # noqa: E402
from .protocol import (  # noqa: E402
    DEFAULT_PROTOCOL_VERSION,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    SUPPORTED_PROTOCOL_VERSIONS,
    RpcError,
    StdioTransport,
    ok,
    resource,
)
from .tools_knowledge import HANDLERS as KB_HANDLERS, MARK_ENUM, TOOLS as KB_TOOLS  # noqa: E402
from .tools_workspace import HANDLERS as WS_HANDLERS, TOOLS as WS_TOOLS  # noqa: E402

ALL_TOOLS = KB_TOOLS + WS_TOOLS
HANDLERS = {**KB_HANDLERS, **WS_HANDLERS}

#: 插件工具名前缀（与内核 Agent 面一致）：`p_<插件id>__<工具名>`
PLUGIN_TOOL_PREFIX = "p_"
_PLUGIN_LOAD_TRIED = False
_PLUGIN_FINGERPRINT: str | None = None


def _enabled_fingerprint() -> str:
    """已启用插件的指纹（id 集合）。工作台里启停插件后指纹会变。

    判定用**内核同一份逻辑** `registry.effective_enabled`：有记录按记录，
    没有记录按 manifest 的 `default_enabled`——只读 plugins.json 会漏掉
    "随包附属、默认开、尚未产生记录"的插件（如 version-manager），把它的工具误过滤掉（实测踩到）。
    """
    try:
        from app import config
        from core.plugins import registry as plugin_registry

        workspace = config.workspace_root()
        install = plugin_registry.read_install_state(workspace)
        candidates, _ = plugin_registry.discover()
        ids = [pid for pid, cand in candidates.items()
               if plugin_registry.effective_enabled(cand, install)]
        return ",".join(sorted(ids))
    except Exception:                   # noqa: BLE001
        return ""


def _ensure_plugin_runtime() -> None:
    """确保插件运行时在**本进程**与当前启用集合一致（MCP 是独立进程，默认没跑过 loader）。

    - 首次调用加载一次；
    - 之后每次比对**启用指纹**，变了就重载 → 工作台里启用/停用插件后，
      MCP 侧下次 `tools/list` 就能看到（不必重启 MCP 服务）；
    - MCP 只借插件的**工具**，不跑它们的后台任务：加载后立刻停调度器，
      否则备份插件这类定时任务会在 MCP 进程里再跑一份。
    """
    global _PLUGIN_LOAD_TRIED, _PLUGIN_FINGERPRINT
    fingerprint = _enabled_fingerprint()
    if _PLUGIN_LOAD_TRIED and fingerprint == _PLUGIN_FINGERPRINT:
        return
    _PLUGIN_LOAD_TRIED = True
    try:
        from core.plugins import loader as plugin_loader

        plugin_loader.load(enabled_only=True)
        from core.plugins import jobs as plugin_jobs

        plugin_jobs.shutdown()          # 只借工具，不跑定时任务
        _PLUGIN_FINGERPRINT = fingerprint
    except Exception:                   # noqa: BLE001 —— 插件加载失败不影响内核工具面
        _PLUGIN_FINGERPRINT = fingerprint


def plugin_tool_catalog() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """已启用插件注册的 MCP 工具：返回 (tools/list 条目, {对外名: plugin_tool})。

    **插件停用则其工具不出现**（`runtime` 里只有已启用插件）——这正是"按插件拆分"的落点。
    """
    _ensure_plugin_runtime()
    try:
        from core.plugins import runtime as plugin_runtime

        specs = plugin_runtime.tool_specs() or {}
        tools = plugin_runtime.tools() or {}
    except Exception:                   # noqa: BLE001
        return [], {}
    # **按当前启用集合过滤**：运行时可能还留着上次加载的插件（loader 未必清空注册表），
    # 只信 `System/plugins.json` 里的启用集合——"插件停用则其工具不出现"就落在这里。
    enabled = {x for x in _enabled_fingerprint().split(",") if x}
    entries = []
    kept: dict[str, Any] = {}
    for name, spec in sorted(specs.items()):
        owner = ""
        try:
            owner = str(plugin_runtime.plugin_of(name) or "")
        except Exception:               # noqa: BLE001
            owner = ""
        if owner and enabled and owner not in enabled:
            continue
        entries.append({
            "name": name,
            "description": str((spec or {}).get("description") or ""),
            "inputSchema": (spec or {}).get("params") or {"type": "object", "properties": {}},
            # `write` 一并带出来（判断写授权要用；不放进 tools/list 输出即可）
            "_write": bool((spec or {}).get("write")),
        })
        if name in tools:
            kept[name] = tools[name]
    return entries, kept


def _mark_ids() -> list[str]:
    """内置标记 + 设置页自定义标记（MCP 过滤参数 enum 随配置动态刷新）。"""
    ids = list(MARK_ENUM)
    try:
        from app import config as app_config

        rows = app_config.get_app().get("classification_marks") or []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                mark_id = str(row.get("id") or "").strip()
                if mark_id:
                    ids.append(mark_id)
    except Exception:  # app 不可用时退回内置集合
        pass
    return list(dict.fromkeys(ids))


def all_tools() -> list[dict[str, Any]]:
    """当前 MCP 工具面：内核工具 + 已启用插件的工具（内部字段 `_write` 不外发）。"""
    entries, _ = plugin_tool_catalog()
    public = [{k: v for k, v in e.items() if not k.startswith("_")} for e in entries]
    tools = copy.deepcopy(KB_TOOLS) + WS_TOOLS + public
    # v261020 · 自定义分类标记：`kb_list_entries(mark=…)` 的 enum 按当前配置刷新
    try:
        marks = _mark_ids()
        for spec in tools:
            if spec.get("name") != "kb_list_entries":
                continue
            props = (spec.get("inputSchema") or {}).get("properties") or {}
            if isinstance(props.get("mark"), dict):
                props["mark"]["enum"] = marks
    except Exception:  # noqa: BLE001 —— 工具面不因标记配置异常而失败
        pass
    return tools

INSTRUCTIONS = (
    "插件提供的工具（名字形如 p_<插件id>__<工具>）**只在该插件启用时出现**："
    "插件停用后它的工具会从工具列表里消失（可在工作台「设置 → 插件」里启停）。\n\n"
    "这是「工程科研工作台」（engineering-research-workbench）的 Agent 接口。\n"
    "工作台的 Markdown + frontmatter 是唯一事实来源，System/Cache 中的 SQLite 索引只是可重建的派生物。\n"
    "工作约定：\n"
    "1. 会话开始先调用 kb_constraints（至少 topic=storage 与 topic=naming）读取存放规则与命名规范；\n"
    "2. 建档前用 kb_search / kb_list_entries 查重，用 ws_list_projects 确认项目归属，不要凭空拼项目名；\n"
    "3. 一切写入都走 kb_create_entry / kb_update_entry / kb_rename_entry / kb_delete_entry，不要手写 frontmatter 落盘；\n"
    "4. 命名规范是硬约束：`level=error` 的校验项会导致工具拒绝写入；\n"
    "5. 改名必须用 kb_rename_entry，它会同步 title/H1/交叉引用并只追加一次 doc_update 事件；\n"
    "6. 收尾用 kb_check_entries 复核，必要时 ws_reindex 重建索引。"
)

RESOURCES: list[dict[str, Any]] = [
    resource(f"workbench://constraints/{topic}", f"constraints-{topic}",
             f"{C.SERVER_NAME} 约束：{desc}", f"工作台约束主题 `{topic}`：{desc}")
    for topic, desc in C.TOPICS.items()
]
RESOURCES.append(resource(
    "workbench://rules/naming-source", "naming-rule-source",
    "知识库条目命名规范（原始规则文档）",
    "`.trae/rules/知识库条目命名规范.md` 的原文，命名约束的权威出处。"))
RESOURCES.append(resource(
    "workbench://workspace/layout", "workspace-layout",
    "Workspace 目录骨架",
    "Workspace 与项目标准子目录、System 文件语义。"))

PROMPTS: list[dict[str, Any]] = [
    {
        "name": "kb-capture",
        "title": "按规范沉淀一条知识",
        "description": "引导 Agent 先读约束、再查重、再按命名规范建档，最后复核。",
        "arguments": [
            {"name": "content", "description": "要沉淀的内容原文或要点", "required": True},
            {"name": "kind", "description": "预期条目类型：" + " / ".join(C.KIND_ORDER), "required": False},
        ],
    },
    {
        "name": "kb-audit",
        "title": "知识库命名体检与整改",
        "description": "扫描全库命名合规问题并逐条给出改名方案。",
        "arguments": [{"name": "kind", "description": "限定条目类型，留空为全部", "required": False}],
    },
]


# ------------------------------------------------------------------ 请求处理

def _protocol_version(params: dict[str, Any]) -> str:
    asked = str(params.get("protocolVersion") or "")
    return asked if asked in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION


def handle_initialize(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocolVersion": _protocol_version(params),
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
            "prompts": {"listChanged": False},
            "logging": {},
        },
        "serverInfo": {"name": C.SERVER_NAME, "version": C.SERVER_VERSION,
                       "title": f"{C.SERVER_NAME} MCP（工作台 {C.WORKBENCH_VERSION_EXPECTED}）"},
        "instructions": INSTRUCTIONS,
    }


#: 会改知识库的 MCP 工具（v261009.38 起受「外部接入授权」约束，默认关闭）
WRITE_TOOLS = frozenset({"kb_create_entry", "kb_update_entry", "kb_rename_entry",
                         "kb_change_kind", "kb_delete_entry",
                         "kb_merge_variants", "kb_archive_variants",
                         "kb_branch_entry",
                         "ws_external_edits"})


def _wrap(result: Any) -> dict[str, Any]:
    """把 handler 的返回包成 MCP 信封——**已经包过就不重复包**。

    版本族那几个 handler（v261009.45 起）自己调了 `ok(...)`/`fail(...)`，而这里又会包一层
    → MCP 客户端拿到嵌套 JSON（实测 `kb_variants` 返回的是 `{"content":[{"text":"{\"content\":…}"}]}`）。
    与其改每个 handler，不如在包装层做幂等判断：已经是信封就原样返回。
    """
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        return result
    from .protocol import ok as _ok

    return _ok(result)


def handle_tools_call(wb: Workbench, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name") or "")
    raw_args = params.get("arguments")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}

    # ① 插件工具（只含已启用插件；停用即消失）
    plugin_entries, plugin_tools = plugin_tool_catalog()
    plugin_tool = plugin_tools.get(name)
    if plugin_tool is not None:
        spec = next((e for e in plugin_entries if e["name"] == name), None) or {}
        if _is_write_tool(name, spec):
            from app import external_access

            allowed, reason = external_access.allowed("mcp_write")
            if not allowed:
                return {"content": [{"type": "text", "text": f"[未授权] {reason}"}], "isError": True}
        try:
            result = plugin_tool.handler(args, {}) or {}
        except Exception as exc:  # noqa: BLE001
            return {"content": [{"type": "text", "text": f"[错误] 插件工具 {name} 执行失败：{exc}"}],
                    "isError": True}
        return _wrap(result)

    # ② 内核工具
    handler = HANDLERS.get(name)
    if handler is None:
        available = sorted(set(HANDLERS) | set(plugin_tools))
        raise RpcError(METHOD_NOT_FOUND, f"未知工具 `{name}`", {"available": available})
    if _is_write_tool(name):
        from app import external_access

        # 注意别用 `ok` 当变量名：本模块从 protocol 导入了 `ok()`，遮蔽它会让成功路径直接崩
        allowed, reason = external_access.allowed("mcp_write")
        if not allowed:
            return {"content": [{"type": "text", "text": f"[未授权] {reason}"}], "isError": True}
    try:
        result = handler(wb, args)
    except WorkbenchError as exc:
        return {"content": [{"type": "text", "text": f"[错误] {exc}"}], "isError": True}
    except FileNotFoundError as exc:
        return {"content": [{"type": "text", "text": f"[错误] 目标不存在：{exc}"}], "isError": True}
    except Exception as exc:  # noqa: BLE001
        detail = traceback.format_exc(limit=6)
        return {"content": [{"type": "text", "text": f"[错误] {type(exc).__name__}: {exc}\n{detail}"}],
                "isError": True}
    return _wrap(result)


def _is_write_tool(name: str, spec: dict[str, Any] | None = None) -> bool:
    """是不是写工具：内核写工具看名单；插件写工具看它注册时的 `write` 标记。"""
    if name in WRITE_TOOLS:
        return True
    # 目录条目里的内部字段叫 `_write`（不随 tools/list 外发）；插件注册时的原始键是 `write`
    return bool((spec or {}).get("write") or (spec or {}).get("_write"))

def _constraint_body(topic: str) -> str:
    from .tools_knowledge import _constraint_text

    return _constraint_text(topic)


def handle_resources_read(wb: Workbench, params: dict[str, Any]) -> dict[str, Any]:
    uri = str(params.get("uri") or "")
    prefix = "workbench://constraints/"
    if uri.startswith(prefix):
        topic = uri[len(prefix):]
        if topic not in C.TOPICS:
            raise RpcError(INVALID_PARAMS, f"未知约束主题 `{topic}`", {"available": list(C.TOPICS)})
        return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": _constraint_body(topic)}]}
    if uri == "workbench://rules/naming-source":
        path = wb.repo_root / ".trae" / "rules" / "知识库条目命名规范.md"
        if not path.exists():
            raise RpcError(INVALID_PARAMS, "规则原文不存在", {"path": str(path)})
        return {"contents": [{"uri": uri, "mimeType": "text/markdown",
                              "text": path.read_text(encoding="utf-8")}]}
    if uri == "workbench://workspace/layout":
        text = _constraint_body("storage") + "\n\n" + _constraint_body("kinds")
        return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}
    raise RpcError(INVALID_PARAMS, f"未知资源 `{uri}`")


def handle_prompts_get(wb: Workbench, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name") or "")
    args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    if name == "kb-capture":
        kind = str(args.get("kind") or "未指定")
        content = str(args.get("content") or "")
        text = (
            "请把下面的内容按工作台规范沉淀成知识条目。\n\n"
            f"预期条目类型：{kind}\n预期内容：\n{content}\n\n"
            "执行步骤：\n"
            "1. kb_constraints（topic=naming、topic=kinds）确认前缀、类别词与命名规则；\n"
            "2. kb_search 查重，避免重复建档；\n"
            "3. ws_list_projects 确认 projects 归属；\n"
            "4. kb_create_entry（先给 name + category，让工具生成规范标题），再 kb_update_entry 补正文；\n"
            "5. kb_check_entries 复核命名与 title/H1 一致性。"
        )
        return {"description": "按规范沉淀一条知识条目", "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
    if name == "kb-audit":
        kind = str(args.get("kind") or "")
        text = (
            "请对知识库做一次命名规范体检与整改。\n\n"
            f"限定条目类型：{kind or '全部'}\n\n"
            "执行步骤：\n"
            "1. kb_constraints（topic=naming、topic=sync）读取命名与改名同步要求；\n"
            "2. kb_check_entries（check_h1=true）产出问题清单；\n"
            "3. 对每条问题给出规范标题，用 kb_rename_entry（先 dry_run=true 看影响面）逐条修正；\n"
            "4. 汇总：合规率、已修正条目、仍需人工确认的条目。"
        )
        return {"description": "知识库命名体检与整改", "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
    raise RpcError(INVALID_PARAMS, f"未知提示 `{name}`", {"available": [p["name"] for p in PROMPTS]})


def dispatch(wb: Workbench, msg: dict[str, Any]) -> dict[str, Any] | None:
    """返回响应体；通知类消息返回 None。"""
    method = str(msg.get("method") or "")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        return handle_initialize(params)
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": all_tools()}
    if method == "tools/call":
        return handle_tools_call(wb, params)
    if method == "resources/list":
        return {"resources": RESOURCES}
    if method == "resources/templates/list":
        return {"resourceTemplates": []}
    if method == "resources/read":
        return handle_resources_read(wb, params)
    if method == "prompts/list":
        return {"prompts": PROMPTS}
    if method == "prompts/get":
        return handle_prompts_get(wb, params)
    if method == "logging/setLevel":
        return {}
    if method == "completion/complete":
        return {"completion": {"values": [], "total": 0, "hasMore": False}}
    raise RpcError(METHOD_NOT_FOUND, f"未实现的方法 `{method}`")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return _selftest()
    transport = StdioTransport(sys.stdin.buffer, sys.stdout.buffer)
    sys.stdout = sys.stderr  # 保证协议通道不被任何 stray print 污染
    wb = Workbench()
    while True:
        try:
            msg = transport.read()
        except RpcError as exc:
            transport.write({"jsonrpc": "2.0", "id": None, "error": exc.to_dict()})
            continue
        if msg is None:
            break
        if isinstance(msg, list):  # 兼容被包裹的批处理
            for item in msg:
                _serve_one(transport, wb, item)
            continue
        _serve_one(transport, wb, msg)
    return 0


def _serve_one(transport: StdioTransport, wb: Workbench, msg: Any) -> None:
    if not isinstance(msg, dict):
        return
    msg_id = msg.get("id")
    is_notification = "id" not in msg
    try:
        result = dispatch(wb, msg)
    except RpcError as exc:
        if not is_notification:
            transport.write({"jsonrpc": "2.0", "id": msg_id, "error": exc.to_dict()})
        return
    except Exception as exc:  # noqa: BLE001
        if not is_notification:
            transport.write({"jsonrpc": "2.0", "id": msg_id, "error": {
                "code": INTERNAL_ERROR, "message": str(exc),
                "data": traceback.format_exc(limit=6)}})
        return
    if result is None or is_notification:
        return
    transport.write({"jsonrpc": "2.0", "id": msg_id, "result": result})


def _selftest() -> int:
    """离线自检：不启动 stdio，直接校验工具表与约束资源。"""
    problems: list[str] = []
    kernel_tools = KB_TOOLS + WS_TOOLS
    plugin_entries, _ = plugin_tool_catalog()
    checked = kernel_tools + plugin_entries
    names = [t["name"] for t in checked]
    if len(names) != len(set(names)):
        problems.append("工具名存在重复")
    for t in kernel_tools:
        if t["name"] not in HANDLERS:
            problems.append(f"工具 `{t['name']}` 缺少实现")
        schema = t["inputSchema"]
        for key in schema.get("required", []):
            if key not in schema["properties"]:
                problems.append(f"工具 `{t['name']}` 的必填参数 `{key}` 未在 properties 中声明")
    for h in HANDLERS:
        if h not in names:
            problems.append(f"实现 `{h}` 未在工具表登记")
    for topic in C.TOPICS:
        try:
            _constraint_body(topic)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"约束主题 `{topic}` 渲染失败：{exc}")
    print(json.dumps({"server": C.SERVER_NAME, "version": C.SERVER_VERSION,
                      "tools": len(checked), "kernel_tools": len(kernel_tools),
        "plugin_tools": len(plugin_entries), "resources": len(RESOURCES),
                      "prompts": len(PROMPTS), "topics": list(C.TOPICS),
                      "problems": problems, "ok": not problems},
                     ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
