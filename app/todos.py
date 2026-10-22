from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from .workspace import ensure_workspace, ensure_project
from . import activity

_LOCK = threading.RLock()


class OverdueError(ValueError):
    """逾期拦截：过了截止点仍要完成，必须由调用方显式确认（`force=True`）。"""

#: 输入侧的严格写法：日期-only 或日期 + 时分（页面 `dueFromInputs()` 用空格分隔）。
DUE_RE = re.compile(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?")

#: `due` 允许的写法。日期-only 表示「当天 23:59 前完成」；带时间表示精确到分的截止点。
_DUE_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")
_DATE_ONLY = ("%Y-%m-%d", "%Y/%m/%d")


def _path() -> Path:
    return ensure_workspace() / "System" / "todos.json"


def _load() -> list[dict[str, Any]]:
    p = _path()
    if not p.exists():
        p.write_text("[]", encoding="utf-8")
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def normalize_due(raw: Any) -> str:
    """把用户输入归一到 ``YYYY-MM-DD`` 或 ``YYYY-MM-DD HH:MM``；无法识别时原样返回。

    兼容旧数据与外部客户端（MCP / 手写 JSON）：只认日期时保持 ``YYYY-MM-DD``，
    带时分时统一成 ``YYYY-MM-DD HH:MM``（``datetime-local`` 的 ``T`` 也收）。
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    for fmt in _DUE_FORMATS:
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    for fmt in _DATE_ONLY:
        try:
            return datetime.strptime(text[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


def parse_due(raw: Any) -> datetime | None:
    """解析截止点。日期-only 视为当天 23:59（当天结束前完成都不算逾期）。"""
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in _DUE_FORMATS:
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    for fmt in _DATE_ONLY:
        try:
            day = datetime.strptime(text[:10], fmt).date()
            return datetime.combine(day, time(23, 59))
        except ValueError:
            continue
    return None


def is_overdue(item: dict[str, Any], now: datetime | None = None) -> bool:
    """未完成且已过截止点。已完成的不算逾期（保留完成时的实际记录）。"""
    if item.get("done"):
        return False
    due = parse_due(item.get("due"))
    return bool(due and due < (now or datetime.now()))


def _decorate(item: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    return {**item, "overdue": is_overdue(item, now)}


def list_todos() -> list[dict[str, Any]]:
    with _LOCK:
        items = _load()
    now = datetime.now()
    return sorted(
        (_decorate(x, now) for x in items),
        key=lambda x: (bool(x.get("done")), x.get("due") or "9999-99-99", x.get("created") or ""),
    )


def validate_payload(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """Validate before any writes. Omitted create fields keep their old defaults.

    Empty/null due explicitly clears the deadline; other editable task fields
    require their declared types. Existing invalid records must be corrected on
    update, never silently removed or coerced.
    """
    if not isinstance(payload, dict):
        raise ValueError("待办输入必须是 JSON 对象")
    result = dict(payload)
    if not partial:
        for key, default in (("title", "新任务"), ("due", date.today().isoformat()),
                             ("priority", "普通"), ("done", False)):
            result.setdefault(key, default)
    if "title" in result:
        title = result["title"]
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title：标题必须是非空字符串")
        result["title"] = title.strip()
    if "due" in result:
        due = result["due"]
        if due is None or due == "":
            result["due"] = ""
        else:
            # v261022.9 · 本地口径保留「日期 + 可选时分」：界面 dueFromInputs() 会写 `YYYY-MM-DD HH:MM`。
            # 上游只收纯日期，直接照搬会让带时间的待办全部 400；但格式仍须严格（`2026-1-01` 这类
            # 宽松写法 strptime 能过、页面却不认，属无效输入）。
            if not isinstance(due, str) or not DUE_RE.fullmatch(due.strip()):
                raise ValueError("due：日期必须是有效的 YYYY-MM-DD 或 YYYY-MM-DD HH:MM，或留空")
            normalized = normalize_due(due)
            if parse_due(normalized) is None:
                raise ValueError("due：日期必须是有效的 YYYY-MM-DD 或 YYYY-MM-DD HH:MM，或留空")
            result["due"] = normalized
    if "priority" in result:
        if not isinstance(result["priority"], str) or result["priority"] not in ("普通", "紧急", "高", "低"):
            raise ValueError("priority：优先级必须是普通、紧急、高或低")
    if "done" in result and not isinstance(result["done"], bool):
        raise ValueError("done：完成状态必须是布尔值")
    return result


def create(payload: dict[str, Any]) -> dict[str, Any]:
    payload = validate_payload(payload)
    now = datetime.now().isoformat(timespec="seconds")
    project = str(payload.get("project") or "").strip()
    item = {
        "id": "todo-" + uuid.uuid4().hex[:10],
        "title": payload["title"],
        "project": project,
        "project_id": str(payload.get("project_id") or ""),
        "due": payload["due"],
        "priority": payload["priority"],
        "done": payload["done"],
        "completed_at": now if payload["done"] else "",
        "created": now,
        "updated": now,
    }
    ensure_project(project)
    with _LOCK:
        items = _load(); items.append(item); _save(items)
    activity.record("todo_create", ref=item["id"], kind="todo", title=item["title"], project=item["project"])
    return _decorate(item)


def update(todo_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = validate_payload(payload, partial=True)
    with _LOCK:
        items = _load()
        for item in items:
            if item.get("id") == todo_id:
                validated = validate_payload({**item, **payload})
                was_done = bool(item.get("done"))
                for key in ("title", "project", "project_id", "due", "priority", "done"):
                    if key in payload:
                        item[key] = validated[key]
                item["due"] = normalize_due(item.get("due"))
                done = bool(item.get("done"))
                item["done"] = done
                # 逾期拦截：只在「未完成 → 完成」这一跳生效；恢复待办/改其它字段不受影响。
                if done and not was_done and is_overdue({**item, "done": False}) and not payload.get("force"):
                    due = str(item.get("due") or "")
                    raise OverdueError(
                        f"该待办已过截止时间（{due}），确认仍要标记完成？"
                        f"（确认后会把完成时间记为现在，可重试并带 force=true）"
                    )
                # 完成时间限制：完成时落 completed_at；恢复待办时清空，避免残留旧完成时间。
                if done and not was_done:
                    item["completed_at"] = datetime.now().isoformat(timespec="seconds")
                elif not done:
                    item["completed_at"] = ""
                ensure_project(str(item.get("project") or ""))
                item["updated"] = datetime.now().isoformat(timespec="seconds")
                _save(items)
                event_type = "todo_done" if (not was_done and done) else "todo_update"
                activity.record(event_type, ref=item["id"], kind="todo", title=str(item.get("title") or ""), project=str(item.get("project") or ""))
                return _decorate(item)
    raise FileNotFoundError(todo_id)


def delete(todo_id: str) -> dict[str, Any]:
    with _LOCK:
        items = _load()
        new_items = [x for x in items if x.get("id") != todo_id]
        if len(new_items) == len(items):
            raise FileNotFoundError(todo_id)
        _save(new_items)
    return {"ok": True}


def delete_many(ids: list[str], *, completed_only: bool = False) -> dict[str, Any]:
    """Delete an explicit selection; completed-only cleanup rechecks under the lock."""
    with _LOCK:
        items = _load()
        by_id = {item.get("id"): item for item in items}
        deleted = [key for key in dict.fromkeys(ids)
                   if key in by_id and (not completed_only or by_id[key].get("done"))]
        failed = [{"id": key, "message": "待办不存在" if key not in by_id else "待办尚未完成，已保留"}
                  for key in dict.fromkeys(ids) if key not in deleted]
        if deleted:
            removed = set(deleted)
            _save([item for item in items if item.get("id") not in removed])
    return {"deleted": deleted, "failed": failed}
