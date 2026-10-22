"""v260930 · M1 Agent 工具调用层：工具注册表与实现。

设计要点：
- 只读工具（kb_search / kb_read）直接执行；
- 写工具（kb_create_entry / kb_update_entry）受 write_mode 控制：
  confirm（默认）→ 生成草稿返回 draft_id，待用户经 /api/agent/drafts/<id>/confirm 确认后落盘；
  direct → 立即执行。命名校验 error 级在两种模式下都拒写。
- 草稿落盘 System/AgentChats/Drafts/<id>.json，进程重启不丢失。
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import store
from . import versions as _versions
from core.contracts import kinds as contracts
from core.contracts import naming

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
    }
    if changes is not None:
        draft["changes"] = changes
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
    from . import indexer
    rows = indexer.list_docs(kind=kind, query=query, page_size=limit)
    return {"count": len(rows), "items": [{
        "id": r.get("id"), "title": r.get("title"), "kind": r.get("kind"),
        "project": ", ".join(r.get("projects") or ([r.get("project")] if r.get("project") else [])),
        "excerpt": r.get("excerpt", ""),
    } for r in rows]}


def _t_kb_read(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(args.get("doc_id") or "").strip()
    from . import indexer
    # v261022.9 · 上游 de31add：支持按 title 定位、正文分页、返回 revision 与排期字段
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
    issues = naming.validate_title(kind, title, projects=[str(x) for x in (args.get("projects") or []) if str(x)])
    validation = naming.issues_summary(issues)
    if not validation["ok"]:
        return {"ok": False, "error": "命名校验未通过，请修正后重试", "validation": validation,
                "issues": issues}
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
    # v261009 · P5 缺口补齐：Agent 建档此前不收状态与日期字段，导致 journal/summary/experiment/
    # milestone/literature 缺法定日期；现按契约放行（日期字段由 store.create_doc 兜底为当天）。
    for key in ("status", "record_date", "due", "added_date", "summary_type"):
        if str(args.get(key) or "").strip():
            payload[key] = str(args[key]).strip()
    # v261022.9 · 上游 de31add：milestone 的结构化排期（start_date/due/progress/status）
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
    payload["kind_marks"] = naming.derive_marks(kind, title, payload["kind_marks"])
    if ctx.get("write_mode") == "direct":
        doc = indexer.create_doc(kind, payload, origin=_versions.origin("agent", "kb_create_entry"))
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
        # v261022.9 · 保留本地来源追踪（store 写入收口点按 origin 记录「谁写的」）
        updated = indexer.update_doc(doc_id, payload, origin=_versions.origin("agent", "kb_update_entry"))
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


_TOOL_IMPL: dict[str, Callable[[dict, dict], dict]] = {
    "kb_search": _t_kb_search,
    "kb_read": _t_kb_read,
    "kb_create_entry": _t_kb_create_entry,
    "kb_update_entry": _t_kb_update_entry,
}

TOOL_NAMES = tuple(_TOOL_IMPL)

# ---------- 工具规格（OpenAI function calling） ----------

# v261009 · 契约单源：core.contracts 不依赖 app，可在模块级安全求值。
# （原先用字面量规避 store→workspace→config→agent_tools 的循环导入，代价是 Agent 侧
# 永远看不到新增类型——experiment 就是这样被漏掉的。）
_KIND_ENUM = list(contracts.KIND_ORDER)
_CATEGORY_ENUM = [str(c["word"]) for c in contracts.CATEGORY_WORDS]
_MARK_ENUM = [str(m["id"]) for m in contracts.MARK_IDS]


def _all_mark_ids() -> list[str]:
    """内置标记 + 设置页自定义标记（工具 schema 的 enum 随配置动态刷新）。"""
    ids = list(_MARK_ENUM)
    try:
        from . import config as _config

        rows = _config.get_app().get("classification_marks") or []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                mark_id = str(row.get("id") or "").strip()
                if mark_id:
                    ids.append(mark_id)
    except Exception:  # 配置不可用时退回内置集合
        pass
    return list(dict.fromkeys(ids))

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
        "description": "在知识库新建条目。标题必须符合命名规范：知识类为「知识-<类别>-<名称>」，类别词取 架构/方法/模型/原理/数据集；实验独立成类，用 kind=experiment 且标题为「实验-<实验内容>（编号）」；其他类型前缀为 总结-/灵感-/日志-/里程碑-/文献-。校验不通过会返回错误清单，须修正后重试。同名条目已存在时会拒绝并提示改用 kb_update_entry。confirm 模式下仅生成草稿，由用户确认后写入。",
        "params": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": _KIND_ENUM, "description": "条目类型，术语/原理笔记用 note，一次具体实验用 experiment"},
            "title": {"type": "string", "description": "合规标题，如「知识-原理-信杂比 SCR」「实验-质心算法对比（4.1）」"},
            "body": {"type": "string", "description": "Markdown 正文；知识类建议含 摘要/原理/公式/场景/失效模式/关联 分节"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签，可选"},
            "projects": {"type": "array", "items": {"type": "string"}, "description": "归属项目名，可选"},
            "kind_marks": {"type": "array", "items": {"type": "string"}, "enum": _MARK_ENUM,
                           "description": "分类标记 id，可选；类别词对应的标记与实验的 ⚗ 会自动补齐"},
            "status": {"type": "string", "description": "状态，取值须在该类型的状态机内（可选，缺省取首个状态）；milestone 建议计划、进行中、受阻或完成，兼容已完成"},
            "record_date": {"type": "string", "description": "journal/summary/experiment 的记录日期 YYYY-MM-DD（可选，缺省当天）"},
            "start_date": {"type": "string", "description": "仅 milestone：阶段开始日期 YYYY-MM-DD；空字符串表示单一节点"},
            "due": {"type": "string", "description": "仅 milestone：截止日期 YYYY-MM-DD；省略或空字符串表示待排期，不默认当天"},
            "progress": {"type": ["number", "null"], "description": "仅 milestone：完成进度 0–100，一位小数；null 为未设置"},
            "added_date": {"type": "string", "description": "仅 literature：收录日期 YYYY-MM-DD"},
            "summary_type": {"type": "string", "description": "仅 summary：阶段总结/里程碑总结等"},
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

}


def _plugin_tool(name: str):
    """按对外名取插件工具（未加载/未启用时返回 None）。"""
    from core.plugins import runtime as plugin_runtime

    return plugin_runtime.tools().get(str(name or "").strip())


def plugin_tool_meta() -> dict[str, dict[str, Any]]:
    """已启用插件注册的工具（v261009 · §8 ②）：`{对外名: {description, params, write}}`。

    插件未启用/未加载时返回空表 —— 也就是「未启用则工具不出现」（I10 的反面：
    不允许出现「注册了却不可用」的入口）。
    """
    from core.plugins import runtime as plugin_runtime

    out: dict[str, dict[str, Any]] = {}
    for name, spec in plugin_runtime.tool_specs().items():
        out[name] = {
            "description": str(spec.get("description") or f"插件工具 {name}"),
            "params": spec.get("parameters") if isinstance(spec.get("parameters"), dict) else {"type": "object", "properties": {}},
            "write": bool(spec.get("write")),
            "plugin": plugin_runtime.plugin_of(name),
        }
    return out


def all_tool_meta() -> dict[str, dict[str, Any]]:
    """内核工具 + 插件工具的统一视图（顺序：内核在前，插件按加载顺序）。

    v261020 · `kb_create_entry.kind_marks` 的 enum 在这里按当前配置动态刷新，
    这样设置页新增的自定义标记也能被 Agent 选用（静态 `_MARK_ENUM` 只是兜底）。
    """
    merged = copy.deepcopy(_TOOL_META)
    merged.update(plugin_tool_meta())
    try:
        merged["kb_create_entry"]["params"]["properties"]["kind_marks"]["enum"] = _all_mark_ids()
    except Exception:  # 工具结构被插件改坏时不影响其它工具
        pass
    return merged


def all_tool_names() -> tuple[str, ...]:
    return tuple(all_tool_meta())


def openai_specs(allowed: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    meta = all_tool_meta()
    names = [n for n in (allowed or all_tool_names()) if n in meta]
    return [{"type": "function", "function": {"name": n, "description": meta[n]["description"], "parameters": meta[n]["params"]}} for n in names]


def text_protocol_prompt(allowed: list[str] | tuple[str, ...] | None = None) -> str:
    """文本协议兜底：端点不支持 function calling 时，让模型用固定 JSON 块调用工具。"""
    meta = all_tool_meta()
    names = [n for n in (allowed or all_tool_names()) if n in meta]
    lines = ["你可以调用以下工具（当接口不支持原生函数调用时使用文本协议）："]
    for n in names:
        lines.append(f"- {n}: {meta[n]['description']}")
    lines.append(
        "\n需要调用工具时，只输出一个 JSON 代码块，格式：\n"
        "```json\n{\"tool\": \"工具名\", \"args\": {参数对象}}\n```\n"
        "每次只调用一个工具，等系统返回工具结果后再继续。得到足够信息后，直接输出最终回答（不要再带工具调用块）。"
    )
    return "\n".join(lines)


def is_write_tool(name: str) -> bool:
    return bool(all_tool_meta().get(name, {}).get("write"))


def list_tool_meta() -> list[dict[str, Any]]:
    """GET /api/agent/tools · 工具元信息清单（供前端展示与人设白名单编辑）。"""
    return [
        {"name": n, "description": m["description"], "params": m["params"], "write": m["write"],
         **({"plugin": m["plugin"]} if m.get("plugin") else {})}
        for n, m in all_tool_meta().items()
    ]


def execute(name: str, args: dict[str, Any] | None, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """统一工具执行入口：异常转 {"ok": False, "error": ...} 交回模型自行修正，不向循环层抛出。"""
    name = str(name or "").strip()
    args = args if isinstance(args, dict) else {}
    ctx = ctx if isinstance(ctx, dict) else {}
    ctx.setdefault("write_mode", "confirm")
    if ctx["write_mode"] not in WRITE_MODES:
        ctx["write_mode"] = "confirm"
    # v261022.9 · 上游 execute() 用到的模块在此按需导入（本地把它们放在函数内，
    # 是为了避开 agent_tools ↔ agent_runtime 的模块级循环导入）。
    from . import agent_mcp, agent_research
    impl = _TOOL_IMPL.get(name)
    if impl is None:
        # v261009 · §8 ②：插件工具（p_<id>__<tool>）走插件注册的 handler，异常同样只影响本次调用
        plugin_tool = _plugin_tool(name)
        if plugin_tool is not None:
            allowed = ctx.get("tools")
            if isinstance(allowed, (list, tuple)) and allowed and name not in allowed:
                return {"ok": False, "error": f"当前人设未授权工具 {name}，可用：{'、'.join(str(t) for t in allowed)}"}
            # v261009 · 插件写工具由**内核**统一走草稿确认流（插件拿不到 save_draft）：
            # confirm 模式先生成草稿，用户确认后 confirm_draft 以 direct 模式再进来执行。
            if is_write_tool(name) and ctx.get("write_mode") != "direct":
                draft = save_draft(name, args)
                return {
                    "pending": True, "draft_id": draft["id"],
                    "message": f"{plugin_tool.plugin_id} 插件的写操作草稿已生成，等待用户确认后执行",
                    "draft": {"tool": name, "plugin": plugin_tool.plugin_id, "args": args},
                }
            t0 = time.time()
            try:
                result = plugin_tool.handler(args, ctx) or {}
            except Exception as e:
                return {"ok": False, "error": f"插件工具失败（{plugin_tool.plugin_id}）：{type(e).__name__}: {e}"}
            if not isinstance(result, dict):
                result = {"result": result}
            result.setdefault("ok", True)
            result["plugin"] = plugin_tool.plugin_id
            result["tool_ms"] = int((time.time() - t0) * 1000)
            return result
        return {"ok": False, "error": f"未知工具 {name}，可用：{'、'.join(all_tool_names())}"}
    allowed = ctx.get("tools")
    if isinstance(allowed, (list, tuple)) and allowed and name not in allowed:  # v260930 · M3 人设白名单：不在名单内直接拒绝
        return {"ok": False, "error": f"当前人设未授权工具 {name}，可用：{'、'.join(str(t) for t in allowed)}"}
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
                if "enum" in rule:
                    # 数组型参数的 enum 约束的是**每一项**（如 kind_marks 的标记白名单），
                    # 不是整个列表本身；按整体比较会把 `[]` 或任何列表都判成越界。
                    values = value if isinstance(value, list) and rule.get("items", {}).get("type") == "string" else [value]
                    if any(item not in rule["enum"] for item in values):
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
    result["tool_ms"] = int((time.time() - t0) * 1000)
    return result
