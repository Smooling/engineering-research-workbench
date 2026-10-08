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


def save_draft(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    draft = {
        "id": "draft-" + uuid.uuid4().hex[:10],
        "tool": tool,
        "args": args,
        "status": "pending",
        "created": datetime.now().isoformat(timespec="seconds"),
        "result": None,
    }
    with _LOCK:
        path = _draft_path(draft["id"])
        path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
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
        _draft_path(draft_id).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        return d


def confirm_draft(draft_id: str) -> dict[str, Any]:
    """用户确认草稿 → 以 direct 模式真正执行写操作。"""
    with _LOCK:
        d = _load_draft(draft_id)
    if d.get("status") != "pending":
        raise ValueError(f"草稿 {draft_id} 已处理（{d.get('status')}）")
    result = execute(str(d.get("tool")), d.get("args") or {}, {"write_mode": "direct"})
    return _finish_draft(draft_id, "confirmed" if result.get("ok") else "failed", result)


def reject_draft(draft_id: str) -> dict[str, Any]:
    return _finish_draft(draft_id, "rejected", None)


# ---------- 工具实现 ----------

def _t_kb_search(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("query 不能为空")
    kind = str(args.get("kind") or "").strip() or None
    limit = max(1, min(int(args.get("limit") or 8), 20))
    rows = store.list_docs(kind=kind, query=query)[:limit]
    return {"count": len(rows), "items": [{
        "id": r.get("id"), "title": r.get("title"), "kind": r.get("kind"),
        "project": ", ".join(r.get("projects") or ([r.get("project")] if r.get("project") else [])),
        "excerpt": r.get("excerpt", ""),
    } for r in rows]}


def _t_kb_read(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(args.get("doc_id") or "").strip()
    if not doc_id:
        raise ValueError("doc_id 不能为空")
    doc = store.get_doc(doc_id)  # 不存在抛 FileNotFoundError → execute 统一转 ok=False
    return {"id": doc["id"], "title": doc.get("title"), "kind": doc.get("kind"),
            "projects": doc.get("projects") or [], "body": _clip(doc.get("body"), _MAX_BODY_CHARS)}


def _t_kb_create_entry(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    kind = str(args.get("kind") or "note").strip()
    if kind not in store.kind_dir_map():
        raise ValueError(f"kind 须为 {'/'.join(store.kind_dir_map())}，当前 {kind}")
    title = str(args.get("title") or "").strip()
    validation = kb_naming.validate_title(kind, title)
    if not validation["ok"]:
        return {"ok": False, "error": "命名校验未通过，请修正后重试", "validation": validation}
    # 查重先行：同题条目已存在 → 拒绝创建，提示走增补
    dup = [r for r in store.list_docs(kind=kind, query=title) if str(r.get("title") or "").strip() == title]
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
    marks = kb_naming.category_mark(kind, title)
    for m in marks:  # 类别词推断的内置标记去重合并
        if m not in payload["kind_marks"]:
            payload["kind_marks"].append(m)
    if ctx.get("write_mode") == "direct":
        doc = store.create_doc(kind, payload)
        return {"ok": True, "doc_id": doc["id"], "title": doc.get("title"), "validation": validation}
    draft = save_draft("kb_create_entry", {"kind": kind, **payload})
    return {"pending": True, "draft_id": draft["id"], "message": "建档草稿已生成，等待用户确认后写入知识库",
            "draft": {"tool": "kb_create_entry", "kind": kind, "title": title}, "validation": validation}


def _t_kb_update_entry(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(args.get("doc_id") or "").strip()
    if not doc_id:
        raise ValueError("doc_id 不能为空")
    doc = store.get_doc(doc_id)
    body = str(args.get("body") or "")
    append = bool(args.get("append"))
    if append:
        body = str(doc.get("body") or "").rstrip() + "\n\n" + body.strip() + "\n"
        args = {**args, "body": body, "append": False}
    if not body.strip():
        raise ValueError("body 不能为空（注意：更新为整体覆盖，须发送全文）")
    if ctx.get("write_mode") == "direct":
        updated = store.update_doc(doc_id, {"body": body})
        return {"ok": True, "doc_id": doc_id, "title": updated.get("title"), "updated": updated.get("updated")}
    draft = save_draft("kb_update_entry", args)
    return {"pending": True, "draft_id": draft["id"], "message": "更新草稿已生成，等待用户确认后写入（覆盖正文）",
            "draft": {"tool": "kb_update_entry", "doc_id": doc_id, "title": doc.get("title"), "append": append}}


def _t_lit_context(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    from . import literature
    paper_id = str(args.get("paper_id") or ctx.get("paper_id") or "").strip()
    if not paper_id:
        raise ValueError("paper_id 不能为空（未提供且当前上下文无文献）")
    item = literature.get_item(paper_id)
    try:
        note = _clip(literature.get_note(paper_id), _MAX_BODY_CHARS)
    except Exception:
        note = ""
    anns = literature.get_annotations(paper_id)
    return {"paper": {k: item.get(k) for k in ("id", "title", "authors", "year", "venue", "doi", "reading_status", "tags")},
            "annotation_count": len(anns), "note": note}


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
    if ctx.get("write_mode") == "direct":
        cur = str(literature.get_note(paper_id) or "")
        next_body = content if mode == "replace" else (cur.rstrip() + "\n\n" + content + "\n" if cur.strip() else content + "\n")
        literature.save_note(paper_id, next_body)
        return {"ok": True, "paper_id": paper_id, "title": item.get("title"), "mode": mode}
    draft = save_draft("lit_note_write", {"paper_id": paper_id, "content": content, "mode": mode})
    return {"pending": True, "draft_id": draft["id"], "message": "文献笔记写入草稿已生成，等待用户确认",
            "draft": {"tool": "lit_note_write", "paper_id": paper_id, "title": item.get("title"), "mode": mode}}


_TOOL_IMPL: dict[str, Callable[[dict, dict], dict]] = {
    "kb_search": _t_kb_search,
    "kb_read": _t_kb_read,
    "kb_create_entry": _t_kb_create_entry,
    "kb_update_entry": _t_kb_update_entry,
    "lit_context": _t_lit_context,
    "lit_note_write": _t_lit_note_write,
}

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
            "limit": {"type": "integer", "description": "返回条数，默认 8，最大 20"},
        }, "required": ["query"]},
        "write": False,
    },
    "kb_read": {
        "description": "按 doc_id 读取一个知识库条目的完整正文。",
        "params": {"type": "object", "properties": {
            "doc_id": {"type": "string", "description": "条目 id，如 note-20260924162227-5c3cbd"},
        }, "required": ["doc_id"]},
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
        }, "required": ["kind", "title", "body"]},
        "write": True,
    },
    "kb_update_entry": {
        "description": "更新已有条目。body 为整体覆盖，须发送全文；不确定全文时先用 kb_read 读原文，或用 append=true 在末尾追加。confirm 模式下仅生成草稿。",
        "params": {"type": "object", "properties": {
            "doc_id": {"type": "string"},
            "body": {"type": "string", "description": "append=false 时为覆盖全文；append=true 时为要追加的片段"},
            "append": {"type": "boolean", "description": "true=在原正文末尾追加，默认 false 覆盖"},
        }, "required": ["doc_id", "body"]},
        "write": True,
    },
    "lit_context": {
        "description": "读取一篇文献的上下文：元数据（题名/作者/年份/DOI/状态）、现有笔记全文、批注数量。阅读中问答与写笔记前应先调用。",
        "params": {"type": "object", "properties": {
            "paper_id": {"type": "string", "description": "文献 id；当前上下文有文献时可省略"},
        }},
        "write": False,
    },
    "lit_note_write": {
        "description": "把内容写入文献笔记（与编辑器里「文献笔记」同一份正文）。mode=append 追加到末尾（默认），mode=replace 整体替换。confirm 模式下仅生成草稿。",
        "params": {"type": "object", "properties": {
            "paper_id": {"type": "string", "description": "文献 id；当前上下文有文献时可省略"},
            "content": {"type": "string", "description": "Markdown 内容"},
            "mode": {"type": "string", "enum": ["append", "replace"]},
        }, "required": ["content"]},
        "write": True,
    },
}


def openai_specs(allowed: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    names = [n for n in (allowed or TOOL_NAMES) if n in _TOOL_META]
    return [{"type": "function", "function": {"name": n, "description": _TOOL_META[n]["description"], "parameters": _TOOL_META[n]["params"]}} for n in names]


def text_protocol_prompt(allowed: list[str] | tuple[str, ...] | None = None) -> str:
    """文本协议兜底：端点不支持 function calling 时，让模型用固定 JSON 块调用工具。"""
    names = [n for n in (allowed or TOOL_NAMES) if n in _TOOL_META]
    lines = ["你可以调用以下工具（当接口不支持原生函数调用时使用文本协议）："]
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
    return [{"name": n, "description": m["description"], "params": m["params"], "write": m["write"]} for n, m in _TOOL_META.items()]


def execute(name: str, args: dict[str, Any] | None, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """统一工具执行入口：异常转 {"ok": False, "error": ...} 交回模型自行修正，不向循环层抛出。"""
    name = str(name or "").strip()
    args = args if isinstance(args, dict) else {}
    ctx = ctx if isinstance(ctx, dict) else {}
    ctx.setdefault("write_mode", "confirm")
    if ctx["write_mode"] not in WRITE_MODES:
        ctx["write_mode"] = "confirm"
    impl = _TOOL_IMPL.get(name)
    if impl is None:
        return {"ok": False, "error": f"未知工具 {name}，可用：{'、'.join(TOOL_NAMES)}"}
    allowed = ctx.get("tools")
    if isinstance(allowed, (list, tuple)) and allowed and name not in allowed:  # v260930 · M3 人设白名单：不在名单内直接拒绝
        return {"ok": False, "error": f"当前人设未授权工具 {name}，可用：{'、'.join(str(t) for t in allowed)}"}
    t0 = time.time()
    try:
        result = impl(args, ctx) or {}
    except FileNotFoundError as e:
        return {"ok": False, "error": f"目标不存在：{e}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    result.setdefault("ok", True)
    result["tool_ms"] = int((time.time() - t0) * 1000)
    return result
