from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from . import agent, config, store
from . import perf_index_core as core
from .perf_index_core import (
    DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, _connect, _init_db, _registry, _root,
    _row_doc, remove_doc, sync, status,
)

def _fts_clause(query: str) -> tuple[str, list[Any]]:
    q = str(query or "").strip()
    if not q:
        return "", []
    like = f"%{q.casefold()}%"
    if len(q) >= 3 or core._FTS_TOKENIZER != "trigram":
        phrase = '"' + q.replace('"', '""') + '"'
        return (
            " AND (d.id IN (SELECT doc_id FROM documents_fts WHERE documents_fts MATCH ?) "
            "OR lower(d.title) LIKE ? OR lower(d.excerpt) LIKE ?)",
            [phrase, like, like],
        )
    return (
        " AND EXISTS (SELECT 1 FROM documents_fts f WHERE f.doc_id=d.id AND "
        "(lower(f.title) LIKE ? OR lower(f.body) LIKE ? OR lower(f.tags) LIKE ? OR lower(f.projects) LIKE ?))",
        [like, like, like, like],
    )


def list_docs(
    kind: str | None = None,
    query: str = "",
    status: str = "",
    project: str = "",
    mark: str = "",
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    paged: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    sync()
    page = max(1, int(page or 1))
    page_size = max(1, min(MAX_PAGE_SIZE, int(page_size or DEFAULT_PAGE_SIZE)))
    where = ["1=1"]
    params: list[Any] = []
    if kind:
        where.append("d.kind=?"); params.append(kind)
    if status:
        where.append("d.status=?"); params.append(status)
    if project:
        where.append(
            "EXISTS (SELECT 1 FROM document_projects dp WHERE dp.doc_id=d.id AND (dp.project_name=? OR dp.project_id=?))"
        ); params.extend([project, project])
    if mark:
        where.append("EXISTS (SELECT 1 FROM document_marks dm WHERE dm.doc_id=d.id AND dm.mark=?)")
        params.append(mark)
    extra, extra_params = _fts_clause(query)
    sql_where = " AND ".join(where) + extra
    params.extend(extra_params)
    with _connect() as conn:
        _init_db(conn)
        total = int(conn.execute(f"SELECT COUNT(*) FROM documents d WHERE {sql_where}", params).fetchone()[0])
        rows = conn.execute(
            f"SELECT d.* FROM documents d WHERE {sql_where} "
            "ORDER BY d.pinned DESC, COALESCE(NULLIF(d.updated,''),d.created) DESC, d.id DESC LIMIT ? OFFSET ?",  # v260924i · 置顶条目排头显示
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    items = [_row_doc(r) for r in rows]
    if not paged:
        return items
    pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "next_page": page + 1 if page < pages else None,
        "prev_page": page - 1 if page > 1 else None,
    }


def get_doc(doc_id: str) -> dict[str, Any]:
    sync()
    with _connect() as conn:
        _init_db(conn)
        row = conn.execute("SELECT path,kind FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        sync(force=True)
        with _connect() as conn:
            _init_db(conn)
            row = conn.execute("SELECT path,kind FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise FileNotFoundError(doc_id)
    path = _root() / str(row["path"])
    if not path.exists():
        remove_doc(doc_id)
        raise FileNotFoundError(doc_id)
    return store._doc_from_path(str(row["kind"]), path, include_body=True)


def search_docs(query: str, limit: int = 60) -> list[dict[str, Any]]:
    sync()
    q = str(query or "").strip()
    if not q:
        return []
    limit = max(1, min(200, int(limit or 60)))
    like = f"%{q.casefold()}%"
    with _connect() as conn:
        _init_db(conn)
        rows: list[sqlite3.Row] = []
        if len(q) >= 3 or core._FTS_TOKENIZER != "trigram":
            phrase = '"' + q.replace('"', '""') + '"'
            try:
                rows = conn.execute(
                    """
                    SELECT d.* FROM documents_fts f
                    JOIN documents d ON d.id=f.doc_id
                    WHERE documents_fts MATCH ?
                    ORDER BY d.pinned DESC, bm25(documents_fts), COALESCE(NULLIF(d.updated,''),d.created) DESC
                    LIMIT ?
                    """,
                    (phrase, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            rows = conn.execute(
                """
                SELECT d.* FROM documents d
                JOIN documents_fts f ON f.doc_id=d.id
                WHERE lower(f.title) LIKE ? OR lower(f.body) LIKE ?
                   OR lower(f.tags) LIKE ? OR lower(f.projects) LIKE ?
                ORDER BY d.pinned DESC, COALESCE(NULLIF(d.updated,''),d.created) DESC  -- v260924k · 搜索结果同样置顶优先
                LIMIT ?
                """,
                (like, like, like, like, limit),
            ).fetchall()
    return [_row_doc(r) for r in rows]


def project_names() -> list[str]:
    sync()
    names = {str(x.get("name") or "").strip() for x in _registry() if str(x.get("name") or "").strip()}
    with _connect() as conn:
        _init_db(conn)
        names.update(str(r[0]).strip() for r in conn.execute("SELECT DISTINCT project_name FROM document_projects") if str(r[0]).strip())
    project_root = _root() / "Projects"
    try:
        names.update(p.name for p in project_root.iterdir() if p.is_dir())
    except OSError:
        pass
    return sorted(names, key=str.casefold)


def project_records() -> list[dict[str, Any]]:
    sync()
    records = _registry()
    with _connect() as conn:
        _init_db(conn)
        doc_rows = conn.execute(
            """
            SELECT dp.project_id,dp.project_name,COUNT(DISTINCT d.id) AS docs,
                   SUM(CASE WHEN d.kind='milestone' THEN 1 ELSE 0 END) AS milestones,
                   MAX(COALESCE(NULLIF(d.updated,''),d.created)) AS last_updated
            FROM document_projects dp JOIN documents d ON d.id=dp.doc_id
            GROUP BY dp.project_id,dp.project_name
            """
        ).fetchall()
        todo_rows = conn.execute(
            """
            SELECT project_id,project, SUM(CASE WHEN done=0 THEN 1 ELSE 0 END) AS open_todos,
                   MAX(COALESCE(NULLIF(updated,''),created)) AS last_updated
            FROM todos_index GROUP BY project_id,project
            """
        ).fetchall()
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for row in doc_rows:
        stat = {"docs": int(row["docs"] or 0), "milestones": int(row["milestones"] or 0), "last_updated": str(row["last_updated"] or "")}
        if row["project_id"]: by_id[str(row["project_id"])] = stat
        if row["project_name"]: by_name[str(row["project_name"])] = stat
    todo_by_id: dict[str, dict[str, Any]] = {}
    todo_by_name: dict[str, dict[str, Any]] = {}
    for row in todo_rows:
        stat = {"open_todos": int(row["open_todos"] or 0), "last_updated": str(row["last_updated"] or "")}
        if row["project_id"]: todo_by_id[str(row["project_id"])] = stat
        if row["project"]: todo_by_name[str(row["project"])] = stat
    out = []
    known = set()
    for rec0 in records:
        rec = dict(rec0)
        pid = str(rec.get("id") or "")
        name = str(rec.get("name") or "")
        known.add(name)
        ds = by_id.get(pid) or by_name.get(name) or {}
        ts = todo_by_id.get(pid) or todo_by_name.get(name) or {}
        rec["docs"] = int(ds.get("docs") or 0)
        rec["milestones"] = int(ds.get("milestones") or 0)
        rec["open_todos"] = int(ts.get("open_todos") or 0)
        rec["last_updated"] = max(
            str(rec.get("updated") or rec.get("created") or ""),
            str(ds.get("last_updated") or ""),
            str(ts.get("last_updated") or ""),
        )
        out.append(rec)
    for name in project_names():
        if name in known:
            continue
        ds = by_name.get(name) or {}; ts = todo_by_name.get(name) or {}
        out.append({
            "id": "", "name": name, "description": "", "status": "进行中", "created": "", "updated": "",
            "docs": int(ds.get("docs") or 0), "milestones": int(ds.get("milestones") or 0),
            "open_todos": int(ts.get("open_todos") or 0),
            "last_updated": max(str(ds.get("last_updated") or ""), str(ts.get("last_updated") or "")),
        })
    return sorted(out, key=lambda x: (str(x.get("last_updated") or ""), str(x.get("name") or "")), reverse=True)


def list_todos() -> list[dict[str, Any]]:
    sync()
    with _connect() as conn:
        _init_db(conn)
        rows = conn.execute(
            "SELECT * FROM todos_index ORDER BY done ASC, CASE WHEN due='' THEN 1 ELSE 0 END, due ASC, updated DESC"
        ).fetchall()
    return [
        {
            "id": r["id"], "title": r["title"], "done": bool(r["done"]), "project": r["project"],
            "project_id": r["project_id"], "priority": r["priority"], "due": r["due"],
            "created": r["created"], "updated": r["updated"],
        }
        for r in rows
    ]


def _activity_payload(today_obj: date, days: int = 400) -> dict[str, Any]:
    start = today_obj - timedelta(days=max(30, days - 1))
    with _connect() as conn:
        _init_db(conn)
        rows = conn.execute(
            "SELECT date,type,count FROM activity_daily WHERE date>=? AND date<=? ORDER BY date",
            (start.isoformat(), today_obj.isoformat()),
        ).fetchall()
        total_activity = int(conn.execute("SELECT COALESCE(SUM(count),0) FROM activity_daily").fetchone()[0])
        if total_activity == 0:
            seed_rows = conn.execute(
                """
                SELECT substr(created,1,10) AS day,'doc_create' AS type,COUNT(*) AS count
                FROM documents WHERE created!='' GROUP BY substr(created,1,10)
                UNION ALL
                SELECT substr(updated,1,10) AS day,'doc_update' AS type,COUNT(*) AS count
                FROM documents WHERE updated!='' AND substr(updated,1,10)<>substr(created,1,10)
                GROUP BY substr(updated,1,10)
                """
            ).fetchall()
            rows = list(rows) + list(seed_rows)
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = str(row[0])
        if day < start.isoformat() or day > today_obj.isoformat():
            continue
        typ = str(row[1]); count = int(row[2] or 0)
        item = buckets.setdefault(day, {"date": day, "count": 0, "breakdown": {}})
        item["count"] += count
        item["breakdown"][typ] = item["breakdown"].get(typ, 0) + count
    out = []
    cursor = start
    while cursor <= today_obj:
        key = cursor.isoformat()
        out.append(buckets.get(key, {"date": key, "count": 0, "breakdown": {}}))
        cursor += timedelta(days=1)
    month = today_obj.strftime("%Y-%m")
    month_rows = [x for x in out if x["date"].startswith(month)]
    by_date = {x["date"]: x["count"] for x in out}
    streak = 0; cursor = today_obj
    while cursor >= start and by_date.get(cursor.isoformat(), 0) > 0:
        streak += 1; cursor -= timedelta(days=1)
    longest = 0; run = 0
    for x in out:
        if x["count"] > 0:
            run += 1; longest = max(longest, run)
        else:
            run = 0
    month_totals: dict[str, dict[str, int]] = {}
    for x in out:
        m = month_totals.setdefault(x["date"][:7], {"events": 0, "active_days": 0})
        m["events"] += x["count"]
        if x["count"] > 0: m["active_days"] += 1
    return {
        "start": start.isoformat(), "end": today_obj.isoformat(), "days": out,
        "active_days_month": sum(1 for x in month_rows if x["count"] > 0),
        "events_month": sum(x["count"] for x in month_rows), "current_streak": streak,
        "longest_streak": longest,
        "month_totals": [{"month": k, **v} for k, v in sorted(month_totals.items())],
    }


def dashboard() -> dict[str, Any]:
    sync()
    today_obj = date.today(); today = today_obj.isoformat()
    with _connect() as conn:
        _init_db(conn)
        counts = {str(r["kind"]): int(r["n"]) for r in conn.execute("SELECT kind,COUNT(*) AS n FROM documents GROUP BY kind")}
        recent: dict[str, list[dict[str, Any]]] = {}
        for kind, key in (("idea","ideas"),("journal","journals"),("note","notes"),("summary","summaries"),("literature","literature")):
            rows = conn.execute(
                "SELECT * FROM documents WHERE kind=? ORDER BY COALESCE(NULLIF(updated,''),created) DESC LIMIT 3",
                (kind,),
            ).fetchall()
            recent[key] = [_row_doc(r) for r in rows]
        start = (today_obj - timedelta(days=183)).isoformat(); end = (today_obj + timedelta(days=183)).isoformat()
        ms_rows = conn.execute(
            "SELECT * FROM documents WHERE kind='milestone' AND due>=? AND due<=? ORDER BY due ASC",
            (start, end),
        ).fetchall()
        milestones = [_row_doc(r) for r in ms_rows]
        stat_rows = conn.execute(
            """
            SELECT dp.project_name,COUNT(DISTINCT d.id) AS docs,
                   SUM(CASE WHEN d.kind='milestone' AND d.status<>'完成' THEN 1 ELSE 0 END) AS open_milestones,
                   SUM(CASE WHEN d.kind='literature' THEN 1 ELSE 0 END) AS literature,
                   SUM(CASE WHEN d.kind IN ('note','journal','idea') THEN 1 ELSE 0 END) AS notes,
                   MAX(COALESCE(NULLIF(d.updated,''),d.created)) AS last_updated
            FROM document_projects dp JOIN documents d ON d.id=dp.doc_id
            WHERE dp.project_name<>'' GROUP BY dp.project_name
            """
        ).fetchall()
        todo_rows = conn.execute(
            """
            SELECT project,SUM(CASE WHEN done=0 THEN 1 ELSE 0 END) AS open_todos,
                   MAX(COALESCE(NULLIF(updated,''),created)) AS last_updated
            FROM todos_index WHERE project<>'' GROUP BY project
            """
        ).fetchall()
    doc_stats = {str(r["project_name"]): r for r in stat_rows}
    todo_stats = {str(r["project"]): r for r in todo_rows}
    project_stats = []
    for name in project_names():
        d = doc_stats.get(name); t = todo_stats.get(name)
        project_stats.append({
            "name": name,
            "docs": int(d["docs"] if d else 0),
            "open_todos": int(t["open_todos"] if t else 0),
            "open_milestones": int(d["open_milestones"] if d else 0),
            "literature": int(d["literature"] if d else 0),
            "notes": int(d["notes"] if d else 0),
            "last_updated": max(str(d["last_updated"] if d else ""), str(t["last_updated"] if t else "")),
        })
    project_stats.sort(key=lambda x: (x["last_updated"], x["name"]), reverse=True)
    profile = config.get_app().get("academic_profile") or {}
    return {
        "counts": counts,
        "recent": recent,
        "upcoming_milestones": milestones,
        "today": today,
        "projects": project_names(),
        "project_records": project_records(),
        "project_stats": project_stats,
        "academic": store._academic_progress(profile, today_obj),
        "activity": _activity_payload(today_obj),
        "index": status(sync_first=False),
    }


def search_all(query: str, limit: int = 60) -> list[dict[str, Any]]:
    q = str(query or "").strip()
    if not q:
        return []
    limit = max(1, min(120, int(limit or 60)))
    results: list[dict[str, Any]] = []
    for d in search_docs(q, limit):
        results.append({
            "source": "doc", "id": d["id"], "kind": d["kind"], "title": d["title"],
            "excerpt": d["excerpt"], "project": ", ".join(d["projects"]), "projects": d["projects"],
            "updated": d["updated"],
        })
        if len(results) >= limit:
            return results
    like = f"%{q.casefold()}%"
    with _connect() as conn:
        _init_db(conn)
        rows = conn.execute(
            """
            SELECT * FROM todos_index
            WHERE lower(title) LIKE ? OR lower(project) LIKE ? OR lower(priority) LIKE ? OR lower(due) LIKE ?
            ORDER BY updated DESC LIMIT ?
            """,
            (like, like, like, like, max(0, limit - len(results))),
        ).fetchall()
    for t in rows:
        results.append({
            "source": "todo", "id": t["id"], "kind": "todo", "title": t["title"],
            "excerpt": f"{t['project'] or '未归属项目'} · 截止 {t['due'] or '—'}", "project": t["project"],
            "updated": t["updated"],
        })
        if len(results) >= limit:
            return results
    q_lower = q.casefold()
    for s in agent.list_sessions():
        if len(results) >= limit:
            break
        title = str(s.get("title") or ""); preview = str(s.get("preview") or "")
        transcript = ""
        try:
            full = agent.get_session(str(s.get("id") or ""))
            transcript = " ".join(
                str(m.get("content") or "") for m in (full.get("messages") or []) if isinstance(m, dict)
            )
        except Exception:
            pass
        if q_lower not in (title + " " + preview + " " + transcript).casefold():
            continue
        excerpt = preview
        if q_lower not in excerpt.casefold() and transcript:
            pos = transcript.casefold().find(q_lower)
            excerpt = transcript[max(0, pos - 60):pos + 140] if pos >= 0 else transcript[:180]
        results.append({
            "source": "chat", "id": s.get("id"), "kind": "agent", "title": title,
            "excerpt": excerpt, "project": "", "updated": s.get("updated", ""),
        })
    results.sort(key=lambda x: str(x.get("updated") or ""), reverse=True)
    return results[:limit]
