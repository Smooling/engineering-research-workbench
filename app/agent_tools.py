"""v260930 · M1 Agent 工具调用层：工具注册表与实现。

设计要点：
- 只读工具（kb_search / kb_read / lit_context）直接执行；
- 写工具（kb_create_entry / kb_update_entry / lit_note_write）受 write_mode 控制：
  confirm（默认）→ 生成草稿返回 draft_id，待用户经 /api/agent/drafts/<id>/confirm 确认后落盘；
  direct → 立即执行。命名校验 error 级在两种模式下都拒写。
- 草稿落盘 System/AgentChats/Drafts/<id>.json，进程重启不丢失。
"""

from __future__ import annotations

import json
import hashlib
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import kb_naming, store

_MAX_RESULT_CHARS = 8000
_MAX_BODY_CHARS = 12000
WRITE_MODES = ("confirm", "direct")

_LOCK = threading.RLock()


def _clip(text: Any, limit: int = _MAX_RESULT_CHARS) -> str:
    s = str(text or "")
    return s if len(s) <= limit else s[:limit] + f"\n…(截断，原文 {len(s)} 字符)"


# ---------- 草稿 ----------

def _drafts_root() -> Path:
    from .workspace import ensure_workspace  # v260930d · 延迟导入：打断 config(模块级 reload_all)→agent_tools→workspace 循环
    root = ensure_workspace() / "System" / "AgentChats" / "Drafts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _draft_path(draft_id: str) -> Path:
    if not re.fullmatch(r"draft-[a-f0-9]{10}", draft_id or ""):
        raise ValueError("Invalid draft id")
    return _drafts_root() / f"{draft_id}.json"


def save_draft(tool: str, args: dict[str, Any], ctx: dict | None = None, *, changes: list[dict] | None = None) -> dict[str, Any]:
    draft = {
        "id": "draft-" + uuid.uuid4().hex[:10],
        "tool": tool,
        "args": args,
        "status": "pending",
        "created": datetime.now().isoformat(timespec="seconds"),
        "result": None,
        "context": {k: v for k, v in (ctx or {}).items() if k in ("session_id", "project_id", "run_id", "tools")},
    }
    if changes is not None:
        draft["changes"] = changes
    with _LOCK:
        path = _draft_path(draft["id"])
        from . import agent_memory
        agent_memory.atomic_json(path, draft)
        agent_memory.save_draft(draft)
    return draft


def _load_draft(draft_id: str) -> dict[str, Any]:
    path = _draft_path(draft_id)
    if not path.exists():
        raise FileNotFoundError(draft_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("draft 文件损坏")
    return data


def list_drafts(status: str = "pending") -> list[dict[str, Any]]:
    out = []
    with _LOCK:
        for path in _drafts_root().glob("draft-*.json"):
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not status or d.get("status") == status:
                out.append(d)
    out.sort(key=lambda x: str(x.get("created") or ""), reverse=True)
    return out


def _finish_draft(draft_id: str, status: str, result: Any) -> dict[str, Any]:
    with _LOCK:
        d = _load_draft(draft_id)
        if d.get("status") != "pending":
            raise ValueError(f"草稿 {draft_id} 已处理（{d.get('status')}）")
        d["status"] = status
        d["result"] = result
        d["updated"] = datetime.now().isoformat(timespec="seconds")
        from . import agent_memory
        agent_memory.atomic_json(_draft_path(draft_id), d)
        agent_memory.save_draft(d)
        return d


def confirm_draft(draft_id: str) -> dict[str, Any]:
    """用户确认草稿 → 以 direct 模式真正执行写操作。"""
    from .sync_engine import mutation_lock
    with mutation_lock, _LOCK:
        d = _load_draft(draft_id)
        if d.get("status") != "pending":
            raise ValueError(f"草稿 {draft_id} 已处理（{d.get('status')}）")
        # Persist reservation before side effects; a crash leaves an explicit
        # uncertain state rather than permitting an automatic duplicate write.
        from . import agent_memory
        d["status"] = "executing"
        agent_memory.atomic_json(_draft_path(draft_id), d)
        agent_memory.save_draft(d)
        result = execute(str(d.get("tool")), d.get("args") or {}, {**d.get("context", {}), "write_mode": "direct", "confirmed": True})
        d.update(status="confirmed" if result.get("ok") else "failed", result=result, updated=datetime.now().isoformat(timespec="seconds"))
        agent_memory.atomic_json(_draft_path(draft_id), d)
        agent_memory.save_draft(d)
        return d


def reject_draft(draft_id: str) -> dict[str, Any]:
    return _finish_draft(draft_id, "rejected", None)


# ---------- 工具实现 ----------

def _t_kb_search(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("query 不能为空")
    kind = str(args.get("kind") or "").strip() or None
    from .agent_runtime import settings
    maximum = settings()["rag_top_k"]
    limit = max(1, min(int(args.get("limit") or maximum), maximum))
    from . import agent_rag
    result = agent_rag.search(query, kind=kind, limit=limit)
    from . import literature
    papers = {p.get("doc_id"): p for p in literature._load_registry().get("items", []) if p.get("doc_id")}
    from .evidence import describe
    for item in result.get("items", []):
        item["evidence"] = item.get("evidence") or describe(item)
        paper = papers.get(item["id"])
        if paper:
            item["paper_id"] = paper["id"]
        item["display_title"] = item.get("title") or "未命名条目"
        item["citation"] = f"[[{item['display_title']}]]"
    result["scope"] = "ranked_top_k"
    result["limit"] = limit
    result["configured_limit"] = maximum
    result["requested_limit"] = args.get("limit")
    result["note"] = "返回相关候选节选，不等于已读全文；未进入前列不代表资料不存在。可用 kb_read 的 doc_id 或 title 直接打开引用来源。"
    return result


def _t_kb_read(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(args.get("doc_id") or "").strip()
    from . import indexer
    if not doc_id and not str(args.get("title") or "").strip():
        raise ValueError("请提供 doc_id 或准确的条目 title")
    doc = indexer.get_doc(doc_id) if doc_id else indexer.resolve_doc(args["title"])
    body = str(doc.get("body") or "")
    offset = max(0, int(args.get("offset") or 0))
    limit = max(1, min(int(args.get("limit") or _MAX_BODY_CHARS), 24000))
    from . import literature
    papers = {p.get("doc_id"): p for p in literature._load_registry().get("items", []) if p.get("doc_id")}
    links = []
    for target in list(dict.fromkeys(re.findall(r"\[\[([^\]\n]+)\]\]", body[offset:offset + limit])))[:24]:
        try:
            linked = indexer.resolve_doc(target)
            links.append({"title": linked["title"], "display_title": linked["title"], "citation": f"[[{linked['title']}]]", "doc_id": linked["id"], "kind": linked["kind"], "paper_id": papers.get(linked["id"], {}).get("id")})
        except (FileNotFoundError, ValueError):
            links.append({"title": target, "resolved": False})
    return {"id": doc["id"], "title": doc.get("title"), "display_title": doc.get("title"), "citation": f"[[{doc.get('title') or '未命名条目'}]]", "kind": doc.get("kind"), "paper_id": papers.get(doc["id"], {}).get("id"), "links": links,
            "projects": doc.get("projects") or [],
            "tags": doc.get("tags") or [], "updated": doc.get("updated") or "",
            **{key: doc[key] for key in ("start_date", "due", "progress", "status", "status_class", "revision") if key in doc},
            "body": body[offset:offset + limit],
            "version": hashlib.sha256(body.encode()).hexdigest(), "total_chars": len(body), "read_scope": "full_body" if offset == 0 and len(body) <= limit else "body_slice",
            "next_offset": offset + limit if offset + limit < len(body) else None,
            "user_message": f"已读取《{doc.get('title') or '知识条目'}》" + ("的完整正文。" if offset == 0 and len(body) <= limit else "的正文节选。")}


def _t_kb_create_entry(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    kind = str(args.get("kind") or "note").strip()
    if kind not in store.kind_dir_map():
        raise ValueError(f"kind 须为 {'/'.join(store.kind_dir_map())}，当前 {kind}")
    title = str(args.get("title") or "").strip()
    validation = kb_naming.validate_title(kind, title)
    if not validation["ok"]:
        return {"ok": False, "error": "命名校验未通过，请修正后重试", "validation": validation}
    # 查重先行：同题条目已存在 → 拒绝创建，提示走增补
    from . import indexer
    dup = [r for r in indexer.list_docs(kind=kind, query=title, page_size=200) if str(r.get("title") or "").strip() == title]
    if dup:
        return {"ok": False, "error": f"同名条目已存在（{dup[0]['id']}），请改用 kb_update_entry 增补而非重复建档",
                "duplicates": [{"id": r.get("id"), "title": r.get("title")} for r in dup]}
    payload = {
        "title": title,
        "body": str(args.get("body") or ""),
        "tags": [str(x) for x in (args.get("tags") or []) if str(x).strip()][:12],
        "projects": [str(x) for x in (args.get("projects") or []) if str(x).strip()][:6],
        "kind_marks": [str(x) for x in (args.get("kind_marks") or []) if str(x).strip()][:6],
    }
    schedule_keys = {"start_date", "due", "progress"}
    if kind != "milestone" and schedule_keys & args.keys():
        raise ValueError("排期字段仅支持 milestone 条目")
    if "status" in args:
        if not args["status"].strip():
            raise ValueError("status 不能为空")
        payload["status"] = args["status"].strip()
    changes = None
    if kind == "milestone":
        # An undated Agent milestone is explicitly unscheduled, never 'today'.
        payload.update(store.normalize_milestone_schedule({"due": "", **args}))
        payload.setdefault("status", "计划")
        changes = [{"field": key, "before": None, "after": payload.get(key)}
                   for key in ("start_date", "due", "progress", "status", "projects", "body", "tags", "kind_marks")]
    marks = kb_naming.category_mark(kind, title)
    for m in marks:  # 类别词推断的内置标记去重合并
        if m not in payload["kind_marks"]:
            payload["kind_marks"].append(m)
    if ctx.get("write_mode") == "direct":
        doc = indexer.create_doc(kind, payload)
        return {"ok": True, "doc_id": doc["id"], "title": doc.get("title"),
                "plan": {key: doc.get(key) for key in ("start_date", "due", "progress", "status", "projects", "revision", "status_class")} if kind == "milestone" else None,
                "user_message": f"已创建《{doc.get('title') or title}》。" + ("尚未设置截止日期，仍待排期。" if kind == "milestone" and not doc.get("due") else ""), "validation": validation}
    draft = save_draft("kb_create_entry", {"kind": kind, **payload}, ctx, changes=changes)
    return {"pending": True, "draft_id": draft["id"], "message": "建档草稿已生成，等待用户确认后写入知识库",
            "draft": {"tool": "kb_create_entry", "kind": kind, "title": title}, "validation": validation}


def _t_kb_update_entry(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    if args.get("append") and "body" not in args:
        raise ValueError("append 需要提供 body")
    doc_id = str(args.get("doc_id") or "").strip()
    if not doc_id:
        raise ValueError("doc_id 不能为空")
    from . import indexer
    doc = indexer.get_doc(doc_id)
    metadata = {key: args[key] for key in ("start_date", "due", "progress", "status", "projects") if key in args}
    expected_revision = args.get("expected_revision")
    if metadata and not expected_revision:
        raise ValueError("修改排期或元数据需要先 kb_read，再提供其 revision 作为 expected_revision")
    if expected_revision and expected_revision != doc.get("revision"):
        return {"ok": False, "conflict": True, "error": "条目排期或内容已变化，请重新读取后生成草稿", "current": doc}
    if doc.get("kind") != "milestone" and {"start_date", "due", "progress"} & metadata.keys():
        raise ValueError("排期字段仅支持 milestone 条目")
    if "status" in metadata:
        if not metadata["status"].strip():
            raise ValueError("status 不能为空")
        metadata["status"] = metadata["status"].strip()
    if {"start_date", "due", "progress"} & metadata.keys():
        normalized = store.normalize_milestone_schedule({**doc, **metadata})
        metadata.update({key: normalized[key] for key in metadata if key in normalized})
    if not metadata and "body" not in args:
        raise ValueError("请提供正文或实际需要修改的计划字段")
    original = str(doc.get("body") or "")
    version = hashlib.sha256(original.encode()).hexdigest()
    expected = str(args.get("expected_version") or "")
    if expected and expected != version:
        return {"ok": False, "conflict": True, "title": doc.get("title"), "error": "条目已变化，请重新读取正文后生成更新", "version": version}
    body = str(args.get("body") or "")
    append = bool(args.get("append"))
    if "body" in args and ctx.get("write_mode") == "direct" and not append and not expected:
        return {"ok": False, "error": "整体覆盖需要 kb_read 返回的 expected_version；也可使用 append=true"}
    if append:
        body = str(doc.get("body") or "").rstrip() + "\n\n" + body.strip() + "\n"
        args = {**args, "body": body, "append": False}
    if "body" in args and not body.strip() and not ctx.get("allow_empty_restore"):
        raise ValueError("body 不能为空（注意：更新为整体覆盖，须发送全文）")
    payload = {**metadata, **({"body": body} if "body" in args else {})}
    if expected_revision:
        payload["expected_revision"] = expected_revision
    if ctx.get("write_mode") == "direct":
        from . import agent_memory
        revision_id = "rev-" + uuid.uuid4().hex
        revision = {"id": revision_id, "doc_id": doc_id, "before": original, "after_version": hashlib.sha256(body.encode()).hexdigest(), "created": agent_memory.now()}
        if "body" in args:
            agent_memory.atomic_json(agent_memory.root() / "Revisions" / (revision_id + ".json"), revision)
        updated = indexer.update_doc(doc_id, payload)
        return {"ok": True, "doc_id": doc_id, "title": updated.get("title") or doc.get("title"), "updated": updated.get("updated"),
                "revision": updated.get("revision"), **({"revision_id": revision_id} if "body" in args else {}),
                "plan": {key: updated.get(key) for key in ("start_date", "due", "progress", "status", "projects", "revision", "status_class")} if doc.get("kind") == "milestone" else None,
                "user_message": f"已更新《{updated.get('title') or doc.get('title') or '知识条目'}》。" + ("原正文已保存，可从修订记录撤销。" if "body" in args else "正文保持不变。")}
    draft_args = {**args, **metadata, "expected_version": version}
    if doc.get("revision"):
        draft_args["expected_revision"] = doc["revision"]
    changes = [{"field": key, "before": doc.get(key), "after": value} for key, value in payload.items() if key != "expected_revision"]
    draft = save_draft("kb_update_entry", draft_args, ctx, changes=changes)
    return {"pending": True, "draft_id": draft["id"], "message": "更新草稿已生成，等待用户确认后写入",
            "draft": {"tool": "kb_update_entry", "doc_id": doc_id, "title": doc.get("title"), "append": append}}


def _t_lit_context(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    from . import literature
    paper_id = str(args.get("paper_id") or ctx.get("paper_id") or "").strip()
    if not paper_id:
        raise ValueError("paper_id 不能为空（未提供且当前上下文无文献）")
    item = literature.get_item(paper_id)
    try:
        full_note = str(literature.get_note(paper_id) or "")
    except Exception:
        full_note = ""
    offset = max(0, int(args.get("note_offset") or 0))
    note = full_note[offset:offset + _MAX_BODY_CHARS]
    anns = literature.get_annotations(paper_id)
    return {"paper": {k: item.get(k) for k in ("id", "doc_id", "title", "authors", "year", "venue", "doi", "reading_status", "tags")},
            "annotation_count": len(anns), "note": note, "note_version": hashlib.sha256(full_note.encode()).hexdigest(),
            "note_total_chars": len(full_note), "note_next_offset": offset + _MAX_BODY_CHARS if offset + _MAX_BODY_CHARS < len(full_note) else None}


def _t_lit_note_write(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    from . import literature
    paper_id = str(args.get("paper_id") or ctx.get("paper_id") or "").strip()
    if not paper_id:
        raise ValueError("paper_id 不能为空（未提供且当前上下文无文献）")
    content = str(args.get("content") or "").strip()
    if not content:
        raise ValueError("content 不能为空")
    mode = str(args.get("mode") or "append")
    if mode not in ("append", "replace"):
        raise ValueError("mode 须为 append 或 replace")
    item = literature.get_item(paper_id)  # 校验条目存在（含 doc_id 关联）
    cur = str(literature.get_note(paper_id) or "")
    version = hashlib.sha256(cur.encode()).hexdigest()
    expected = str(args.get("expected_version") or "")
    if mode == "replace" and expected and expected != version:
        return {"ok": False, "conflict": True, "error": "文献笔记已变化，请重新 lit_context 后更新", "version": version}
    if ctx.get("write_mode") == "direct":
        if mode == "replace" and not expected:
            return {"ok": False, "error": "替换笔记需要 lit_context 返回的 expected_version"}
        next_body = content if mode == "replace" else (cur.rstrip() + "\n\n" + content + "\n" if cur.strip() else content + "\n")
        from . import agent_memory
        rid = "rev-" + uuid.uuid4().hex
        agent_memory.atomic_json(agent_memory.root() / "Revisions" / (rid + ".json"), {"id": rid, "type": "literature", "paper_id": paper_id, "before": cur, "after_version": hashlib.sha256(next_body.encode()).hexdigest(), "created": agent_memory.now()})
        literature.save_note(paper_id, next_body)
        return {"ok": True, "paper_id": paper_id, "title": item.get("title"), "mode": mode, "revision_id": rid,
                "user_message": f"已更新《{item.get('title') or '当前文献'}》的笔记，原内容已保存，可从修订记录撤销。"}
    draft = save_draft("lit_note_write", {"paper_id": paper_id, "content": content, "mode": mode, "expected_version": version}, ctx)
    return {"pending": True, "draft_id": draft["id"], "message": "文献笔记写入草稿已生成，等待用户确认",
            "draft": {"tool": "lit_note_write", "paper_id": paper_id, "title": item.get("title"), "mode": mode}}


def _t_rollback(args, ctx):
    from . import agent_memory, indexer
    rid = str(args.get("revision_id") or "")
    if not re.fullmatch(r"rev-[a-f0-9]{32}", rid):
        raise ValueError("无效修订 id")
    item = json.loads((agent_memory.root() / "Revisions" / (rid + ".json")).read_text(encoding="utf-8"))
    if item.get("type") == "literature":
        if not str(item["before"]).strip():
            from . import literature
            current = str(literature.get_note(item["paper_id"]) or "")
            if hashlib.sha256(current.encode()).hexdigest() != item["after_version"]:
                return {"ok": False, "conflict": True, "error": "文献笔记已变化，无法恢复"}
            if ctx.get("write_mode") != "direct":
                draft = save_draft("kb_rollback", args, ctx)
                return {"pending": True, "draft_id": draft["id"]}
            literature.save_note(item["paper_id"], "")
            return {"ok": True, "paper_id": item["paper_id"]}
        return _t_lit_note_write({"paper_id": item["paper_id"], "content": item["before"], "mode": "replace", "expected_version": item["after_version"]}, ctx)
    return _t_kb_update_entry({"doc_id": item["doc_id"], "body": item["before"], "expected_version": item["after_version"]}, {**ctx, "allow_empty_restore": True})


_TOOL_IMPL: dict[str, Callable[[dict, dict], dict]] = {
    "kb_search": _t_kb_search,
    "kb_read": _t_kb_read,
    "kb_create_entry": _t_kb_create_entry,
    "kb_update_entry": _t_kb_update_entry,
    "lit_context": _t_lit_context,
    "lit_note_write": _t_lit_note_write,
}

# Research module only imports workspace/memory lazily, preserving config's
# initialization order (config -> agent_tools -> store).
from . import agent_research
_TOOL_IMPL.update({name: (lambda args, ctx, n=name: agent_research.execute(n, args, ctx)) for name in agent_research.META})
_TOOL_IMPL["kb_rollback"] = _t_rollback
TOOL_NAMES = tuple(_TOOL_IMPL)

# ---------- 工具规格（OpenAI function calling） ----------

# v260930d · 六类 kind 用字面量：模块级求值 store.kind_dir_map() 会触发循环导入
# （导入链 store→workspace→config(模块级 reload_all)→agent_tools→store 部分初始化）；六类由命名规范固定，增类时须同步此处
_KIND_ENUM = ["note", "idea", "journal", "milestone", "summary", "literature"]

_TOOL_META: dict[str, dict[str, Any]] = {
    "kb_search": {
        "description": "在本地知识库中按关键词检索条目（标题/正文/标签/项目全字段）。建档前必须先用它查重。",
        "params": {"type": "object", "properties": {
            "query": {"type": "string", "description": "检索关键词"},
            "kind": {"type": "string", "enum": _KIND_ENUM, "description": "可选：限定条目类型"},
            "limit": {"type": "integer", "description": "省略时使用用户设置的最多召回条数；仅任务明确需要更少结果时指定，不能超过用户上限"},
        }, "required": ["query"]},
        "write": False,
    },
    "kb_read": {
        "description": "按 doc_id 或准确 title 读取知识库正文，支持分页。返回来源 links 的 doc_id/paper_id，可继续读取原文；当前页面没有挂载文献不影响读取库内资料。",
        "params": {"type": "object", "properties": {
            "doc_id": {"type": "string", "description": "内部定位 ID，原样用于工具调用；对用户使用条目标题或 citation"},
            "title": {"type": "string", "description": "准确的条目标题；已知引用标题但没有 ID 时使用"},
            "offset": {"type": "integer", "description": "正文字符偏移，用于完整分页读取"},
            "limit": {"type": "integer", "description": "每页字符数，最大 24000"},
        }},
        "write": False,
    },
    "kb_create_entry": {
        "description": "在知识库新建条目。标题必须符合命名规范：知识类为「知识-<类别>-<名称>」，类别词取 架构/方法/模型/原理/实验/数据集；其他类型前缀为 总结-/灵感-/日志-/里程碑-/文献-。校验不通过会返回错误清单，须修正后重试。同名条目已存在时会拒绝并提示改用 kb_update_entry。confirm 模式下仅生成草稿，由用户确认后写入。",
        "params": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": _KIND_ENUM, "description": "条目类型，术语/原理笔记用 note"},
            "title": {"type": "string", "description": "合规标题，如「知识-原理-信杂比 SCR」"},
            "body": {"type": "string", "description": "Markdown 正文；知识类建议含 摘要/原理/公式/场景/失效模式/关联 分节"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签，可选"},
            "projects": {"type": "array", "items": {"type": "string"}, "description": "归属项目名，可选"},
            "kind_marks": {"type": "array", "items": {"type": "string"}, "description": "分类标记 id，可选"},
            "start_date": {"type": "string", "description": "milestone 阶段开始日期 YYYY-MM-DD；空字符串表示单一节点"},
            "due": {"type": "string", "description": "milestone 截止日期 YYYY-MM-DD；省略或空字符串表示待排期，不默认当天"},
            "progress": {"type": ["number", "null"], "description": "milestone 完成进度 0–100，一位小数；null 为未设置"},
            "status": {"type": "string", "description": "状态；milestone 建议计划、进行中、受阻或完成；兼容已完成"},
        }, "required": ["kind", "title", "body"], "additionalProperties": False},
        "write": True,
    },
    "kb_update_entry": {
        "description": "更新已有条目或结构化里程碑排期。仅发送改动字段；排期/状态/项目修改必须先 kb_read 并提供 expected_revision。省略 body 保留正文，body 为整体覆盖时须发送全文和 expected_version，或 append=true 追加。confirm 模式生成字段旧值→新值草稿，确认后写入。",
        "params": {"type": "object", "properties": {
            "doc_id": {"type": "string"},
            "body": {"type": "string", "description": "append=false 时为覆盖全文；append=true 时为要追加的片段"},
            "append": {"type": "boolean", "description": "true=在原正文末尾追加，默认 false 覆盖"},
            "expected_version": {"type": "string", "description": "kb_read 的 version；整体覆盖时必须提供，防止覆盖并发修改"},
            "expected_revision": {"type": "string", "description": "kb_read 返回的 revision，覆盖元数据和正文；排期/状态/项目修改必填"},
            "start_date": {"type": "string", "description": "milestone 开始日期 YYYY-MM-DD；空字符串清空"},
            "due": {"type": "string", "description": "milestone 截止日期 YYYY-MM-DD；空字符串清空"},
            "progress": {"type": ["number", "null"], "description": "milestone 进度 0–100；null 清空"},
            "status": {"type": "string", "description": "保留自定义状态；完成与已完成具有相同语义"},
            "projects": {"type": "array", "items": {"type": "string"}, "description": "项目名称；空列表清除关联"},
        }, "required": ["doc_id"], "additionalProperties": False},
        "write": True,
    },
    "lit_context": {
        "description": "读取一篇文献的上下文：元数据（题名/作者/年份/DOI/状态）、现有笔记全文、批注数量。阅读中问答与写笔记前应先调用。",
        "params": {"type": "object", "properties": {
            "paper_id": {"type": "string", "description": "文献 id；当前上下文有文献时可省略"},
            "note_offset": {"type": "integer", "description": "笔记正文字符偏移，用于完整分页读取"},
        }},
        "write": False,
    },
    "lit_note_write": {
        "description": "把内容写入文献笔记（与编辑器里「文献笔记」同一份正文）。mode=append 追加到末尾（默认），mode=replace 整体替换。confirm 模式下仅生成草稿。",
        "params": {"type": "object", "properties": {
            "paper_id": {"type": "string", "description": "文献 id；当前上下文有文献时可省略"},
            "content": {"type": "string", "description": "Markdown 内容"},
            "mode": {"type": "string", "enum": ["append", "replace"]},
            "expected_version": {"type": "string", "description": "替换笔记时必须提供 lit_context 返回的 note_version"},
        }, "required": ["content"]},
        "write": True,
    },
}

_TOOL_META.update(agent_research.META)
_TOOL_META["kb_rollback"] = agent_research.meta("恢复一次知识条目更新前的内容；有版本冲突时拒绝，支持草稿确认。", {"revision_id": {"type": "string"}}, ["revision_id"], True)


def openai_specs(allowed: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    import copy
    from . import agent_mcp
    from .agent_runtime import settings
    names = [n for n in (TOOL_NAMES if allowed is None else allowed) if n in _TOOL_META]
    specs = [{"type": "function", "function": {"name": n, "description": _TOOL_META[n]["description"], "parameters": copy.deepcopy(_TOOL_META[n]["params"])}} for n in names]
    maximum = settings()["rag_top_k"]
    for spec in specs:
        if spec["function"]["name"] in {"kb_search", "memory_recall"}:
            spec["function"]["parameters"]["properties"]["limit"].update(minimum=1, maximum=maximum, default=maximum, description=f"省略时按用户设置最多召回 {maximum} 条；仅明确需要更少结果时指定。上限不是保证命中数量。")
    return specs + [s for s in agent_mcp.specs() if allowed is None or s["function"]["name"] in allowed]


def text_protocol_prompt(allowed: list[str] | tuple[str, ...] | None = None) -> str:
    """文本协议兜底：端点不支持 function calling 时，让模型用固定 JSON 块调用工具。"""
    names = [n for n in (TOOL_NAMES if allowed is None else allowed) if n in _TOOL_META]
    lines = ["你可以调用以下工具（当接口不支持原生函数调用时使用文本协议）："]
    if any(n in {"kb_search", "memory_recall"} for n in names):
        from .agent_runtime import settings
        lines.append(f"检索默认使用用户设置的最多 {settings()['rag_top_k']} 条。默认省略 limit；仅任务确需更少结果时指定。")
    for n in names:
        lines.append(f"- {n}: {_TOOL_META[n]['description']}")
    lines.append(
        "\n需要调用工具时，只输出一个 JSON 代码块，格式：\n"
        "```json\n{\"tool\": \"工具名\", \"args\": {参数对象}}\n```\n"
        "每次只调用一个工具，等系统返回工具结果后再继续。得到足够信息后，直接输出最终回答（不要再带工具调用块）。"
    )
    return "\n".join(lines)


def is_write_tool(name: str) -> bool:
    return bool(_TOOL_META.get(name, {}).get("write"))


def list_tool_meta() -> list[dict[str, Any]]:
    """GET /api/agent/tools · 工具元信息清单（供前端展示与人设白名单编辑）。"""
    from . import agent_mcp
    return [{"name": n, "description": m["description"], "params": m["params"], "write": m["write"]} for n, m in _TOOL_META.items()] + [{"name": s["function"]["name"], "description": s["function"]["description"], "params": s["function"]["parameters"], "write": agent_mcp.is_write(s["function"]["name"])} for s in agent_mcp.specs()]


def execute(name: str, args: dict[str, Any] | None, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """统一工具执行入口：异常转 {"ok": False, "error": ...} 交回模型自行修正，不向循环层抛出。"""
    name = str(name or "").strip()
    args = args if isinstance(args, dict) else {}
    ctx = ctx if isinstance(ctx, dict) else {}
    ctx.setdefault("write_mode", "confirm")
    if ctx.get("source_policy") == "rag_only":
        from . import agent_context
        if name not in agent_context.RAG_ONLY_TOOLS:
            return {"ok": False, "error": "用户要求本轮只参考 RAG，不允许技能、记忆、联网、写入或其他数据工具"}
        if name == "kb_read":
            target = str(args.get("doc_id") or args.get("title") or "").strip().removeprefix("[[").removesuffix("]]").split("|", 1)[0]
            hits = ctx.get("rag_sources", {})
            titles = set(hits.values()) | {title.removeprefix("文献-") for title in hits.values()}
            if target not in hits and target not in titles:
                return {"ok": False, "error": "本轮只参考 RAG；请先检索命中此条目，再读取正文。导航笔记里的链接不等于该文献已独立命中。"}
        if name == "evidence_read" and args.get("run_id") and args["run_id"] != ctx.get("run_id"):
            return {"ok": False, "error": "本轮只参考当前 RAG 证据，不读取其他任务的历史结果"}
    if ctx["write_mode"] not in WRITE_MODES:
        ctx["write_mode"] = "confirm"
    impl = _TOOL_IMPL.get(name)
    if name.startswith("mcp_"):
        from . import agent_mcp
        impl = lambda a, c: agent_mcp.execute(name, a)
    if impl is None:
        return {"ok": False, "error": f"未知工具 {name}，可用：{'、'.join(TOOL_NAMES)}"}
    allowed = ctx.get("tools")
    if isinstance(allowed, (list, tuple)) and name not in allowed:
        return {"ok": False, "error": f"当前人设未授权工具 {name}，可用：{'、'.join(str(t) for t in allowed)}"}
    from . import agent_runtime
    options = agent_runtime.settings()
    if not options["rag_enabled"] and name in agent_runtime.RAG_TOOLS:
        return {"ok": False, "error": "RAG 已关闭，请在 RAG 设置中启用知识检索"}
    if not options["memory_enabled"] and name in agent_runtime.MEMORY_TOOLS:
        return {"ok": False, "error": "记忆已关闭，请在输入框下方开启记忆"}
    if name in {"skill_read", "skill_run", "skill_install"}:
        if not options["skills_enabled"] or str(args.get("name") or "") in options["disabled_skills"]:
            return {"ok": False, "error": "该技能已停用，请在技能页启用"}
    t0 = time.time()
    try:
        # Central schema validation also covers model endpoints without strict
        # function calling; type errors become repairable tool results.
        meta = _TOOL_META.get(name)
        if meta:
            properties = meta["params"].get("properties", {})
            if meta["params"].get("additionalProperties") is False:
                unknown = args.keys() - properties.keys()
                if unknown:
                    raise ValueError("不支持的参数：" + "、".join(sorted(unknown)))
            for key in meta["params"].get("required", []):
                if key not in args:
                    raise ValueError(f"缺少必填参数 {key}")
            for key, value in args.items():
                rule = properties.get(key, {})
                expected = rule.get("type")
                types = {"string": str, "integer": int, "number": (int, float), "array": list, "object": dict, "boolean": bool, "null": type(None)}
                allowed_types = expected if isinstance(expected, list) else [expected]
                if expected and not any(t in types and isinstance(value, types[t]) and not (t in ("integer", "number") and isinstance(value, bool)) for t in allowed_types):
                    raise ValueError(f"参数 {key} 需要 {expected}")
                if isinstance(value, list) and rule.get("items", {}).get("type") == "string" and any(not isinstance(item, str) for item in value):
                    raise ValueError(f"参数 {key} 的每项必须是字符串")
                if "enum" in rule and value not in rule["enum"]:
                    raise ValueError(f"参数 {key} 不在允许值中")
        write = is_write_tool(name) if meta else agent_mcp.is_write(name)
        if write and ctx["write_mode"] != "direct" and (name in agent_research.META or name.startswith("mcp_") or name == "kb_rollback"):
            draft = save_draft(name, args, ctx)
            return {"ok": True, "pending": True, "draft_id": draft["id"], "draft": {"title": str(args.get("content") or name)[:80]}, "message": "等待确认后执行"}
        if write:
            from .sync_engine import mutation_lock
            with mutation_lock:
                result = impl(args, ctx) or {}
        else:
            result = impl(args, ctx) or {}
    except store.RevisionConflict as e:
        return {"ok": False, "conflict": True, "error": str(e), "current": e.current}
    except FileNotFoundError as e:
        return {"ok": False, "error": f"目标不存在：{e}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    result.setdefault("ok", True)
    title = result.get("title") or (result.get("draft") or {}).get("title")
    if title and name.startswith(("kb_", "lit_")):
        result["display_title"] = title
        result["citation"] = f"[[{title}]]"
        result["presentation_hint"] = "对用户使用 display_title/citation/user_message；内部编号、版本散列和修订号只用于工具调用。"
    result["tool_ms"] = int((time.time() - t0) * 1000)
    return result
