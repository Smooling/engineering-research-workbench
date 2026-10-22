from __future__ import annotations

import json
import hashlib
import re
import threading
import uuid
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import workspace_root

_LOCK = threading.RLock()
_CACHE: OrderedDict = OrderedDict()


def _path(root: Path | None = None) -> Path:
    return (root if root is not None else workspace_root()) / "System" / "activity.jsonl"


def fingerprint(event: dict[str, Any]) -> str:
    value = {k: v for k, v in event.items() if k != "id"}
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def legacy_id(sha: str, occurrence: int) -> str:
    # Keep repeated identical actions in old logs, while identifying shared copies
    # consistently on every device. Never assign random IDs to old history.
    return f"legacy-{sha}-{occurrence}"


def validate_event(event: Any) -> None:
    if not isinstance(event, dict):
        raise ValueError("科研活动记录格式无效")
    identity = event.get("id")
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}|legacy-[a-f0-9]{64}-[1-9][0-9]{0,11}", identity):
        raise ValueError("科研活动 ID 无效")
    if identity.startswith("legacy-") and identity != legacy_id(fingerprint(event), int(identity.rsplit("-", 1)[1])):
        raise ValueError("历史科研活动校验失败")
    try:
        datetime.fromisoformat(str(event["timestamp"]).replace("Z", "+00:00"))
        if not isinstance(event.get("weight", 1), int) or event.get("weight", 1) < 1:
            raise ValueError()
    except (KeyError, ValueError, TypeError, OverflowError):
        raise ValueError("科研活动日期或权重无效") from None


def _signature(path: Path):
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size, stat.st_ino
    except FileNotFoundError:
        return None


def _events_locked(path: Path) -> dict[str, dict[str, Any]]:
    key, signature = str(path.resolve()), _signature(path)
    cached = _CACHE.get(key)
    if cached and cached[0] == signature:
        _CACHE.move_to_end(key)
        return cached[1]
    events, occurrences = {}, {}
    if signature is not None:
        with path.open("rb") as source:
            for raw in source:
                if not raw.endswith(b"\n"):
                    break  # Retry incomplete appends when the writer finishes.
                try:
                    event = json.loads(raw.decode("utf-8-sig"))
                    if not isinstance(event, dict):
                        continue
                    if not event.get("id"):
                        sha = fingerprint(event)
                        occurrences[sha] = occurrences.get(sha, 0) + 1
                        event["id"] = legacy_id(sha, occurrences[sha])
                    validate_event(event)
                    identity = event["id"]
                    if identity in events and events[identity] != event:
                        raise RuntimeError(f"科研活动 ID 对应不同内容：{identity}")
                    events[identity] = event
                except (ValueError, TypeError, UnicodeError):
                    continue
    _CACHE[key] = (signature, events)
    _CACHE.move_to_end(key)
    while len(_CACHE) > 8:
        _CACHE.popitem(last=False)
    return events


def _append_locked(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as target:
        # Isolate a truncated last line from the next valid action.
        target.seek(0, 2)
        if target.tell():
            target.seek(-1, 2)
            if target.read(1) != b"\n":
                target.write(b"\n")
                _CACHE.pop(str(path.resolve()), None)
        target.write("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events).encode("utf-8"))


def record(event_type: str, *, ref: str = "", kind: str = "", title: str = "", project: str = "", weight: int = 1, timestamp: str | None = None, source: str = "", detail: dict | None = None, root: Path | None = None) -> None:
    """Append one lightweight research-activity event.

    This file is intentionally append-only. A failed activity write must never block
    the primary operation (saving a note, finishing a task, etc.).

    v261009.41 · `source`：谁写的（「工作台界面 · doc_save」「外部 MCP 客户端 · kb_update_entry · …」），
    由 `app/versions.describe_origin` 生成；`detail`：结构化细节（合并记了哪些小节等）。
    空值不写入该字段（向后兼容）。
    """
    event = {
        "id": uuid.uuid4().hex,
        "timestamp": timestamp or datetime.now().isoformat(timespec="seconds"),
        "type": str(event_type or "activity"),
        "ref": str(ref or ""),
        "kind": str(kind or ""),
        "title": str(title or ""),
        "project": str(project or ""),
        "weight": max(1, int(weight or 1)),
    }
    if str(source or "").strip():
        event["source"] = str(source).strip()
    if detail:
        event["detail"] = detail
    try:
        with _LOCK:
            path = _path(root)
            _append_locked(path, [event])
            _CACHE.pop(str(path.resolve()), None)
    except Exception:
        # Activity analytics are secondary; never make the research workflow fail.
        return


def merge_events(events: list[dict[str, Any]], *, root: Path | None = None) -> int:
    """Append the missing part of a union; importing never records a new action."""
    with _LOCK:
        path = _path(root)
        known, pending = _events_locked(path), {}
        for event in events:
            validate_event(event)
            identity = event["id"]
            previous = pending.get(identity, known.get(identity))
            if previous is not None and previous != event:
                raise ValueError("科研活动为追加记录，不能覆盖已有活动")
            if previous is None:
                pending[identity] = dict(event)
        if pending:
            _append_locked(path, list(pending.values()))
            if str(path.resolve()) in _CACHE:
                known.update(pending)
                _CACHE[str(path.resolve())] = (_signature(path), known)
        return len(pending)


def list_events(since: date | None = None, *, root: Path | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        return [dict(e) for e in _events_locked(_path(root)).values()
                if since is None or datetime.fromisoformat(str(e["timestamp"]).replace("Z", "+00:00")).date() >= since]
