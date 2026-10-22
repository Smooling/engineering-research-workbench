"""工作台类工具 —— 项目、待办、检索、关系图、活动流与索引维护。"""

from __future__ import annotations

from typing import Any

from . import constraints as C
from .bridge import Workbench
from .protocol import arr, b, fail, i, ok, s, tool

PROJECT_STATUS_ENUM = ["进行中", "暂停", "完成", "归档"]
TODO_PRIORITY_ENUM = ["高", "普通", "低"]

COMMON_FREEZE_NOTE = "只读工具，不会改动任何磁盘内容。"


def _limit(raw: Any, default: int, lo: int, hi: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


# ------------------------------------------------------------------ 工具实现

def t_info(wb: Workbench, args: dict[str, Any]) -> Any:
    data = wb.info()
    return {
        **data,
        "server": {"name": C.SERVER_NAME, "version": C.SERVER_VERSION,
                   "workbench_version_expected": C.WORKBENCH_VERSION_EXPECTED},
        "kind_dirs": {k: v["dir"] for k, v in C.KINDS.items()},
        "_tip": "首次会话建议先调用 kb_constraints（topic=storage / naming）读取存放与命名规则。",
    }


def t_workspace_tree(wb: Workbench, args: dict[str, Any]) -> Any:
    return wb.tree(max_depth=_limit(args.get("max_depth"), 3, 1, 8),
                   max_entries=_limit(args.get("max_entries"), 400, 50, 1800))


def t_list_projects(wb: Workbench, args: dict[str, Any]) -> Any:
    items = wb.list_projects()
    status = str(args.get("status") or "").strip()
    if status:
        items = [x for x in items if str(x.get("status")) == status]
    return {"total": len(items), "items": items,
            "layout": C.PROJECT_LAYOUT,
            "_tip": "条目归属项目时请使用这里返回的 `name`，不要凭空拼项目名。"}


def t_project_detail(wb: Workbench, args: dict[str, Any]) -> Any:
    ref = str(args.get("project") or "").strip()
    if not ref:
        return fail("缺少项目标识", "给出项目 `name` 或 `project_id`。")
    record = wb.resolve_project(ref)
    files = wb.project_files(ref, max_depth=_limit(args.get("max_depth"), 3, 1, 6))
    docs: list[dict[str, Any]] = []
    todos: list[dict[str, Any]] = []
    if args.get("include_entries", True):
        listed = wb.list_entries(project=ref, page=1, page_size=_limit(args.get("entry_limit"), 50, 1, 100))
        docs = listed["items"]
    if args.get("include_todos", True):
        todos = [t for t in wb.list_todos(include_done=False)
                 if str(t.get("project") or "") == str(record.get("name") or "")]
    return {"project": record, "files": files, "entries": docs, "open_todos": todos}


def t_create_project(wb: Workbench, args: dict[str, Any]) -> Any:
    name = str(args.get("name") or "").strip()
    if not name:
        return fail("缺少项目名", "给出 `name`。")
    status = str(args.get("status") or "进行中").strip()
    if status not in PROJECT_STATUS_ENUM:
        return fail(f"非法状态 `{status}`", "可选：" + " / ".join(PROJECT_STATUS_ENUM))
    existing = [p for p in wb.list_projects() if str(p.get("name")) == name]
    if existing:
        if not args.get("allow_existing"):
            return {"created": False, "existing": existing[0],
                    "_hint": "同名项目已存在；如需复用请直接使用其 project_id，或传 allow_existing=true 幂等复用。"}
        return {"created": False, "reused": True, "project": existing[0],
                "layout_created": [], "_hint": "同名项目已存在，按幂等处理，未重复新建。"}
    record = wb.create_project(name, str(args.get("description") or ""), status)
    return {"created": True, "project": record, "layout_created": C.PROJECT_LAYOUT}


def t_update_project(wb: Workbench, args: dict[str, Any]) -> Any:
    ref = str(args.get("project") or "").strip()
    if not ref:
        return fail("缺少项目标识", "给出项目 `name` 或 `project_id`。")
    record = wb.resolve_project(ref)
    payload: dict[str, Any] = {}
    for key in ("name", "description", "status"):
        if args.get(key) not in (None, ""):
            payload[key] = args[key]
    if not payload:
        return {"updated": False, "project": record, "_hint": "没有传入任何可更新字段。"}
    updated = wb.update_project(str(record.get("project_id")), payload)
    return {"updated": True, "project": updated}


def t_list_todos(wb: Workbench, args: dict[str, Any]) -> Any:
    items = wb.list_todos(include_done=bool(args.get("include_done", True)))
    ref = str(args.get("project") or "").strip()
    if ref:
        items = [x for x in items if str(x.get("project") or "") == ref]
    overdue_only = bool(args.get("overdue_only", False))
    if overdue_only:
        # v261019 · 逾期口径与 /api/todos 同源（日期-only 视为当天 23:59 截止）
        items = [x for x in items if x.get("overdue")]
    return {"total": len(items), "items": items}


def t_create_todo(wb: Workbench, args: dict[str, Any]) -> Any:
    title = str(args.get("title") or "").strip()
    if not title:
        return fail("缺少待办标题", "给出 `title`。")
    priority = str(args.get("priority") or "普通").strip()
    if priority not in TODO_PRIORITY_ENUM:
        return fail(f"非法优先级 `{priority}`", "可选：" + " / ".join(TODO_PRIORITY_ENUM))
    item = wb.create_todo({
        "title": title, "project": str(args.get("project") or "").strip(),
        "due": str(args.get("due") or "").strip(), "priority": priority,
        "done": bool(args.get("done", False)),
    })
    return {"created": True, "todo": item,
            "_tip": "待办存放于 System/todos.json；逾期收口请用 summary/journal 条目沉淀结论。"}


def t_update_todo(wb: Workbench, args: dict[str, Any]) -> Any:
    todo_id = str(args.get("todo_id") or "").strip()
    if not todo_id:
        return fail("缺少 todo_id", "先用 todo_list 取回待办 id。")
    payload: dict[str, Any] = {}
    for key in ("title", "project", "due", "priority"):
        if args.get(key) not in (None, ""):
            payload[key] = args[key]
    if args.get("done") is not None:
        payload["done"] = bool(args["done"])
    if args.get("force") is not None:
        payload["force"] = bool(args["force"])
    if not payload:
        return fail("没有可更新字段", "至少传入 title / project / due / priority / done 之一。")
    try:
        item = wb.update_todo(todo_id, payload)
    except ValueError as exc:  # OverdueError：逾期完成需显式确认
        return fail(str(exc), "确认仍要完成后重试，并传 `force: true`。")
    return {"updated": True, "todo": item}


def t_search(wb: Workbench, args: dict[str, Any]) -> Any:
    query = str(args.get("query") or "").strip()
    if not query:
        return fail("缺少检索词", "给出 `query`。")
    hits = wb.search(query, limit=_limit(args.get("limit"), 20, 1, 60))
    return {"query": query, "count": len(hits), "hits": hits,
            "_tip": "命中条目请用 kb_get_entry 读取全文，不要凭摘要下结论。"}


def t_graph(wb: Workbench, args: dict[str, Any]) -> Any:
    doc_id = str(args.get("doc_id") or "").strip()
    if doc_id:
        return wb.graph_neighborhood(doc_id, depth=_limit(args.get("depth"), 1, 1, 3))
    return wb.graph_overview(limit=_limit(args.get("limit"), 80, 5, 200))


def t_dashboard(wb: Workbench, args: dict[str, Any]) -> Any:
    return wb.dashboard()


def t_external_edits(wb: Workbench, args: dict[str, Any]) -> Any:
    """外部直接改动巡检：哪些条目被改过却没有记录（IDE/脚本绕过 MCP 直接写文件）。

    `record=true` 会把它们记成活动事件（写操作，受「外部接入」授权约束）。
    """
    import core_api

    return core_api.external_edits(record=bool(args.get("record")), limit=int(args.get("limit") or 200))


def t_activity(wb: Workbench, args: dict[str, Any]) -> Any:
    """活动日志（修改记录）。可按条目 id 或事件类型过滤，看清"谁在什么时候改了什么"。"""
    import core_api

    return core_api.activity_events(int(args.get("days") or 7),
                                    ref=str(args.get("ref") or "").strip(),
                                    types=[str(x) for x in (args.get("types") or []) if str(x).strip()],
                                    limit=int(args.get("limit") or 100))
    out = core_api.activity_events(days, ref=ref, types=types, limit=int(args.get("limit") or 100))
    return out

def t_export_bibtex(wb: Workbench, args: dict[str, Any]) -> Any:
    ids = args.get("ids") if isinstance(args.get("ids"), list) else None
    ids = [str(x).strip() for x in (ids or []) if str(x).strip()] or None
    data = wb.export_bibtex(ids)
    # 注意：底层导出结果里含名为 `content` 的字段（BibTeX 文本），
    # 与 MCP 结果信封的 `content` 键同名，必须在这里显式包一层，
    # 否则会被 server 误判为已是信封而原样外泄。
    return ok({
        "ok": bool(data.get("ok")),
        "count": data.get("count"),
        "path": data.get("path"),
        "bibtex": data.get("content") or "",
        "_hint": "BibTeX 已写入上述 path；`bibtex` 为同样内容的字符串，可直接复制使用。",
    })


def t_index_status(wb: Workbench, args: dict[str, Any]) -> Any:
    data = wb.index_status()
    return {
        "schema_version": data.get("schema_version"),
        "workspace_schema_version": data.get("workspace_schema_version"),
        "fts_tokenizer": data.get("fts_tokenizer"),
        "last_sync": data.get("last_sync"),
        "counts": data.get("counts"),
        "path_relative": "System/Cache",
        "_reminder": C.SOURCE_OF_TRUTH_RULE,
    }


def t_reindex(wb: Workbench, args: dict[str, Any]) -> Any:
    if not args.get("confirm"):
        return {"reindexed": False, "preview": wb.index_status(),
                "_hint": "重建索引会扫描全库 Markdown 并刷新 System/Cache；确认请传 confirm=true。"}
    data = wb.reindex()
    return {"reindexed": True, "status": {"last_sync": data.get("last_sync"), "counts": data.get("counts")}}


HANDLERS = {
    "ws_external_edits": t_external_edits,
    "ws_info": t_info,
    "ws_tree": t_workspace_tree,
    "ws_list_projects": t_list_projects,
    "ws_project_detail": t_project_detail,
    "ws_create_project": t_create_project,
    "ws_update_project": t_update_project,
    "todo_list": t_list_todos,
    "todo_create": t_create_todo,
    "todo_update": t_update_todo,
    "kb_search": t_search,
    "kb_graph": t_graph,
    "ws_dashboard": t_dashboard,
    "ws_activity": t_activity,
    "lit_export_bibtex": t_export_bibtex,
    "ws_index_status": t_index_status,
    "ws_reindex": t_reindex,
}


TOOLS = [
    tool("ws_external_edits", "外部直接改动巡检",
         "列出「文件被改过但没有对应记录」的条目——IDE/脚本绕过 MCP 直接写 .md 的情况。"
         "record=true 会把它们记成活动事件（写操作，受外部接入授权约束）。",
         {"record": b("把发现的改动记进活动日志"), "limit": i("最多返回条数", default=200)},
         read_only=False),
    tool("ws_info", "工作台总览",
         "返回 Workspace 根路径、目录骨架、六类条目落盘目录与索引状态。" + COMMON_FREEZE_NOTE,
         {}, read_only=True),
    tool("ws_tree", "查看目录树",
         "列出 Workspace 目录树（受深度与条数上限保护）。" + COMMON_FREEZE_NOTE,
         {"max_depth": i("目录深度", default=3, minimum=1, maximum=8),
          "max_entries": i("最多节点数", default=400, minimum=50, maximum=1800)},
         read_only=True),
    tool("ws_list_projects", "列出项目",
         "列出 Projects 注册表：项目 id、名称、状态、条目/里程碑/未完成待办计数。" + COMMON_FREEZE_NOTE,
         {"status": s("按状态过滤", enum=PROJECT_STATUS_ENUM)}, read_only=True),
    tool("ws_project_detail", "查看项目详情",
         "按项目名或 project_id 返回项目记录、标准子目录文件树、关联条目与未完成待办。" + COMMON_FREEZE_NOTE,
         {"project": s("项目名或 project_id"),
          "max_depth": i("文件树深度", default=3, minimum=1, maximum=6),
          "entry_limit": i("最多返回的关联条目数", default=50, minimum=1, maximum=100),
          "include_entries": b("是否附带关联条目", default=True),
          "include_todos": b("是否附带未完成待办", default=True)},
         ["project"], read_only=True),
    tool("ws_create_project", "创建项目",
         "创建项目并生成标准子目录（" + " / ".join(C.PROJECT_LAYOUT) + "）。",
         {"name": s("项目名（目录安全名）"),
          "description": s("项目简介"),
          "status": s("项目状态", enum=PROJECT_STATUS_ENUM, default="进行中"),
          "allow_existing": b("同名项目已存在时仍强行新建")},
         ["name"], destructive=False),
    tool("ws_update_project", "更新项目",
         "更新项目名称、简介或状态。",
         {"project": s("项目名或 project_id"),
          "name": s("新项目名"),
          "description": s("新简介"),
          "status": s("新状态", enum=PROJECT_STATUS_ENUM)},
         ["project"], destructive=False),
    tool("todo_list", "列出待办",
         "读取 System/todos.json 中的待办，可按项目过滤或只看逾期未完成项。" + COMMON_FREEZE_NOTE,
         {"project": s("按项目名过滤"),
          "include_done": b("是否包含已完成", default=True),
          "overdue_only": b("只看已逾期且未完成")},
         read_only=True),
    tool("todo_create", "创建待办",
         "新增一条待办到 System/todos.json。截止时间可选到分（`YYYY-MM-DD HH:MM`）。",
         {"title": s("待办标题"),
          "project": s("归属项目名"),
          "due": s("截止时间，`YYYY-MM-DD`（当天 23:59 截止）或 `YYYY-MM-DD HH:MM`"),
          "priority": s("优先级", enum=TODO_PRIORITY_ENUM, default="普通"),
          "done": b("是否已完成")},
         ["title"], destructive=False),
    tool("todo_update", "更新待办",
         "更新待办标题、项目、截止时间、优先级或完成状态。逾期待办标记完成需 `force: true` 二次确认。",
         {"todo_id": s("待办 id，形如 todo-3f9a1c2b7d"),
          "title": s("新标题"),
          "project": s("新归属项目名"),
          "due": s("新截止时间，`YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM`"),
          "priority": s("新优先级", enum=TODO_PRIORITY_ENUM),
          "done": b("是否完成"),
          "force": b("已逾期待办标记完成时传 true（等价于界面上的二次确认）")},
         ["todo_id"], destructive=False),
    tool("kb_search", "全库检索",
         "跨知识条目、待办、会话做统一检索。" + COMMON_FREEZE_NOTE,
         {"query": s("检索词"),
          "limit": i("返回条数上限", default=20, minimum=1, maximum=60)},
         ["query"], read_only=True),
    tool("kb_graph", "知识关系图",
         "给 doc_id 返回该条目邻域关系图；不给则返回全库关系总览。" + COMMON_FREEZE_NOTE,
         {"doc_id": s("中心条目 id；留空则返回全库关系总览"),
          "depth": i("邻域深度", default=1, minimum=1, maximum=3),
          "limit": i("总览模式节点上限", default=80, minimum=5, maximum=200)},
         read_only=True),
    tool("ws_dashboard", "工作台仪表盘",
         "返回条目、项目、待办、活动等聚合统计。" + COMMON_FREEZE_NOTE,
         {}, read_only=True),
    tool("ws_activity", "查看活动流",
         "读取 System/activity.jsonl 的活动事件（按天回溯）。" + COMMON_FREEZE_NOTE,
         {"days": i("回溯天数", default=7, minimum=1, maximum=400)},
         read_only=True),
    tool("lit_export_bibtex", "导出 BibTeX",
         "导出文献条目的 BibTeX；不传 ids 则导出全部。" + COMMON_FREEZE_NOTE,
         {"ids": arr("限定导出的条目 id 列表；留空导出全部")},
         read_only=True),
    tool("ws_index_status", "索引状态",
         "返回 System/Cache SQLite 索引的版本、最后同步时间与计数。" + COMMON_FREEZE_NOTE,
         {}, read_only=True),
    tool("ws_reindex", "重建索引",
         "全量扫描 Markdown 重建派生索引；默认先返回预览，需 confirm=true 才执行。",
         {"confirm": b("确认执行重建")},
         destructive=False),
]
