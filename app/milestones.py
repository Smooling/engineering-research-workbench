"""Complete planning snapshot from existing milestone Markdown; no separate task store."""
from __future__ import annotations

from . import store
from .perf_index_core import ensure_ready, _connect, _root


def plan() -> dict:
    ensure_ready()
    with _connect() as conn:
        rows = conn.execute("SELECT path FROM documents WHERE kind='milestone' ORDER BY due,id").fetchall()
    items, unavailable = [], 0
    for row in rows:
        try:
            # Planning metadata belongs to Markdown. Reading it here avoids a schema
            # migration and keeps the full chart independent of document pagination.
            doc = store._doc_from_path("milestone", _root() / row["path"], include_body=False)
        except (OSError, ValueError):
            unavailable += 1
            continue
        items.append({key: doc[key] for key in (
            "id", "kind", "title", "status", "project", "projects", "due", "start_date",
            "progress", "excerpt", "updated", "created", "revision", "status_class",
        ) if key in doc})
    return {"items": items, "total": len(items), "unavailable": unavailable}
