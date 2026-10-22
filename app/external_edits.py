"""外部改动巡检（v261009.49）

**问题**：Markdown 是唯一事实来源，但外部工具（IDE Agent、脚本、编辑器）可以直接写 `.md`——
那条路绕过写入收口点，于是**没有活动事件、没有来源、没有版本**，用户会以为"改了却没记录"。

**判据**（不需要新状态）：条目文件的改动时间**晚于**该条目最后一次活动事件的时间。
内核每次写入都会同时更新文件并记事件，所以"文件更新而事件没跟上"就是外部直接改动。

`record=True` 时把这些改动写成 `doc_external_edit` 活动事件（来源标注「工作区外部改动」），
这样它们会出现在「版本」页的**修改记录**里，用户至少知道"这份稿子被外部改过"。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

#: 文件时间比事件时间晚多少才算"外部改动"（容忍同一秒内的写入顺序与文件系统精度）
TOLERANCE_SECONDS = 2


def _last_event_times() -> dict[str, str]:
    from app import activity

    out: dict[str, str] = {}
    for event in activity.list_events():
        ref = str(event.get("ref") or "")
        stamp = str(event.get("timestamp") or "")
        if ref and stamp > out.get(ref, ""):
            out[ref] = stamp
    return out


def untracked(*, days: int = 7, limit: int = 100) -> list[dict[str, Any]]:
    """工作区里**不在知识库内**、但最近被改过的 .md（如临时稿、外部工具产物）。

    这类文件没有 frontmatter/id，工作台**不跟踪**它们——列出来只是让用户知道
    "这些改动不会出现在任何记录里"（用户反馈的两份开题报告就属于这种）。
    """
    from app import workspace

    root = workspace.ensure_workspace()
    cutoff = datetime.now().timestamp() - max(1, int(days)) * 86400
    rows: list[dict[str, Any]] = []
    for item in root.rglob("*.md"):
        rel = str(item.relative_to(root))
        if rel.startswith(("System", "Trash")) or rel.startswith("Knowledge"):
            continue
        try:
            stat = item.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff:
            continue
        head = item.read_text(encoding="utf-8", errors="replace")[:400]
        rows.append({"path": rel, "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                     "size": stat.st_size, "in_kb": 'id:' in head and head.startswith("---")})
    rows.sort(key=lambda r: str(r["mtime"]), reverse=True)
    return rows[:max(1, int(limit))]


def scan(*, record: bool = False, limit: int = 200, days: int = 7) -> dict[str, Any]:
    """列出（并可选记录）被外部直接改动的条目；另附**库外文件**清单。"""
    from app import activity, store, workspace

    root = workspace.ensure_workspace()
    last = _last_event_times()
    rows: list[dict[str, Any]] = []
    for doc in store.list_docs():
        rel = str(doc.get("path") or "")
        if not rel:
            continue
        path = root / rel
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        stamp = str(doc.get("updated") or "")
        reference = max([x for x in (last.get(str(doc.get("id") or ""), ""), stamp) if x] or [""])
        if not reference:
            continue
        try:
            ref_dt = datetime.fromisoformat(reference)
        except ValueError:
            continue
        if (mtime - ref_dt).total_seconds() <= TOLERANCE_SECONDS:
            continue
        rows.append({"id": doc.get("id"), "title": doc.get("title"), "kind": doc.get("kind"),
                     "path": rel, "mtime": mtime.isoformat(timespec="seconds"),
                     "updated": stamp, "last_event": last.get(str(doc.get("id") or ""), ""),
                     "has_origin": bool(doc.get("origin_surface")),
                     "origin": str(doc.get("origin_surface") or "")})
    rows.sort(key=lambda r: str(r["mtime"]), reverse=True)
    rows = rows[:max(1, int(limit))]
    if record:
        for row in rows:
            try:
                activity.record("doc_external_edit", ref=str(row["id"]), kind=str(row["kind"] or ""),
                                title=str(row["title"] or ""),
                                source=f"工作区外部改动（未经界面/MCP，可能是外部工具或同步）· 文件时间 {row['mtime'][:16].replace('T', ' ')}",
                                detail={"path": row["path"], "mtime": row["mtime"],
                                        "last_event": row["last_event"]})
            except Exception:      # noqa: BLE001 —— 记录失败不影响巡检结果
                pass
    outside = untracked(days=days, limit=50)
    return {"count": len(rows), "recorded": bool(record), "tolerance_seconds": TOLERANCE_SECONDS,
            "items": rows, "untracked_count": len(outside), "untracked": outside}
