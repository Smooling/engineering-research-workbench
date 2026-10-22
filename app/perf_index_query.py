from __future__ import annotations

import sqlite3
import re
from datetime import date, timedelta
from typing import Any

from . import config, store
from . import perf_index_core as core
from . import perf_index_db as db
from .perf_index_core import (
    DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, _connect, _init_db, _registry, _root,
    _row_doc, remove_doc, ensure_ready, status,
)

def _fts_clause(query: str) -> tuple[str, list[Any]]:
    q = str(query or "").strip()
    if not q:
        return "", []
    like = "%" + q.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    tokenizer = db._SCHEMA_READY.get(str(db._db_path()), db._FTS_TOKENIZER)
    if len(q) >= 3 and tokenizer == "trigram":
        phrase = '"' + q.replace('"', '""') + '"'
        return (
            " AND (d.id IN (SELECT doc_id FROM documents_fts WHERE documents_fts MATCH ?) "
            "OR lower(d.title) LIKE ? ESCAPE '\\' OR lower(d.excerpt) LIKE ? ESCAPE '\\')",
            [phrase, like, like],
        )
    return (
        " AND d.id IN (SELECT doc_id FROM documents_fts f WHERE "
        "lower(f.title) LIKE ? ESCAPE '\\' OR lower(f.body) LIKE ? ESCAPE '\\' "
        "OR lower(f.tags) LIKE ? ESCAPE '\\' OR lower(f.projects) LIKE ? ESCAPE '\\')",
        [like, like, like, like],
    )


def list_docs(
    kind: str | None = None,
    query: str = "",
    status: str = "",
    project: str = "",
    mark: str = "",
    tag: str = "",
    unowned: bool = False,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    paged: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    ensure_ready()
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
    # v261008.2 · 标签筛选（此前只能靠全文搜索命中）与「未归属项目（通用基础）」筛选
    if tag:
        where.append("EXISTS (SELECT 1 FROM document_tags dt WHERE dt.doc_id=d.id AND dt.tag=?)")
        params.append(tag)
    if unowned:
        where.append(
            "NOT EXISTS (SELECT 1 FROM document_projects dp WHERE dp.doc_id=d.id "
            "AND (dp.project_name<>'' OR dp.project_id<>''))"
        )
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
    ensure_ready()
    with _connect() as conn:
        _init_db(conn)
        row = conn.execute("SELECT path,kind FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise FileNotFoundError(doc_id)
    path = _root() / str(row["path"])
    if not path.exists():
        remove_doc(doc_id)
        raise FileNotFoundError(doc_id)
    doc = store.doc_from_path(str(row["kind"]), path, include_body=True)
    from .evidence import describe
    doc["evidence"] = describe(doc)
    return doc


def resolve_doc(target: str) -> dict[str, Any]:
    """Resolve a citation by ID or exact title, independently of list pagination."""
    target = str(target or "").strip().removeprefix("[[").removesuffix("]]")
    target = target.split("|", 1)[0].split("#", 1)[0].strip()
    if not target or len(target) > 1000:
        raise ValueError("引用须为有效的条目 ID 或标题")
    ensure_ready()
    with _connect() as conn:
        rows = conn.execute("SELECT id FROM documents WHERE id=? OR title=? COLLATE NOCASE", (target, target)).fetchall()
        if not rows:
            rows = conn.execute("SELECT id FROM documents WHERE title=? COLLATE NOCASE", ("文献-" + target,)).fetchall()
    if not rows:
        raise FileNotFoundError("未找到对应条目：" + target)
    if len(rows) > 1:
        raise ValueError("存在同名条目，请使用条目 ID 引用")
    return get_doc(rows[0]["id"])


def retrieval_terms(query: str) -> list[str]:
    # Spaces separate concepts, rather than making one impossible FTS phrase.
    raw = re.findall(r"[a-zA-Z0-9_]+(?:[-.][a-zA-Z0-9_]+)*|[\u3400-\u9fff]+", query)
    terms = []
    for token in raw:
        parts = re.split(r"(?:如何|为什么|是什么|怎样|以及|是否|和|与|的)", token) if re.search(r"[\u3400-\u9fff]", token) else [token]
        terms.extend(part for part in parts if len(part) >= 2 and part not in {"什么", "哪些", "一个", "这个"})
    return list(dict.fromkeys(t.casefold() for t in terms))[:24]


def retrieve_docs(query: str, kind: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Rank research evidence; ordinary document lists retain their sort order."""
    ensure_ready()
    query = str(query or "").strip()
    limit = max(1, min(int(limit), 200))
    terms = retrieval_terms(query)
    if not query:
        return {"items": [], "total": 0, "terms": terms}
    with _connect() as conn:
        direct = conn.execute("SELECT * FROM documents WHERE id=?" + (" AND kind=?" if kind else ""), [query, kind] if kind else [query]).fetchone()
        if direct:
            return {"items": [_row_doc(direct)], "total": 1, "terms": terms}
        tokenizer = db._SCHEMA_READY.get(str(db._db_path()), db._FTS_TOKENIZER)
        phrase = lambda text: '"' + text.replace('"', '""') + '"'
        parts = list(dict.fromkeys([query.casefold(), *terms]))
        params = []
        kind_clause = " AND d.kind=?" if kind else ""
        rank_params = []
        if tokenizer == "trigram" and all(len(p) >= 3 for p in parts):
            match = " OR ".join(phrase(p) for p in parts)
            source = "documents_fts f JOIN documents d ON d.id=f.doc_id"
            where = "documents_fts MATCH ?" + kind_clause
            params = [match] + ([kind] if kind else [])
            rank = "bm25(documents_fts,0,12,1,3,0.02)"
        else:
            source = "documents_fts f JOIN documents d ON d.id=f.doc_id"
            clauses = []
            for part in parts:
                like = "%" + part.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                clauses.append("(lower(f.title) LIKE ? ESCAPE '\\' OR lower(f.body) LIKE ? ESCAPE '\\' OR lower(f.tags) LIKE ? ESCAPE '\\' OR lower(f.projects) LIKE ? ESCAPE '\\')")
                params.extend([like] * 4)
            where = "(" + " OR ".join(clauses) + ")" + kind_clause
            params += [kind] if kind else []
            weights = []
            for part in parts:
                weights.append("CASE WHEN instr(lower(f.title),?)>0 THEN 12 ELSE 0 END + CASE WHEN instr(lower(f.body),?)>0 THEN 1 ELSE 0 END + CASE WHEN instr(lower(f.tags),?)>0 THEN 3 ELSE 0 END")
                rank_params.extend([part] * 3)
            rank = "-(" + " + ".join(weights) + ")"
        # Exact title wins even if hundreds of papers carry that project name.
        exact = "CASE WHEN lower(d.title)=? OR lower(d.title)=? OR d.id=? THEN 0 ELSE 1 END"
        exact_params = [query.casefold(), "文献-" + query.casefold(), query]
        total = conn.execute(f"SELECT COUNT(*) FROM {source} WHERE {where}", params).fetchone()[0]
        rows = conn.execute(f"SELECT d.*, {rank} AS retrieval_score FROM {source} WHERE {where} ORDER BY {exact}, retrieval_score, d.id LIMIT ?", [*rank_params, *params, *exact_params, limit]).fetchall()
    return {"items": [_row_doc(r) for r in rows], "total": total, "terms": terms}


def search_docs(query: str, limit: int = 60) -> list[dict[str, Any]]:
    ensure_ready()
    q = str(query or "").strip()
    if not q:
        return []
    limit = max(1, min(200, int(limit or 60)))
    with _connect() as conn:
        _init_db(conn)
        rows: list[sqlite3.Row] = []
        tokenizer = db._SCHEMA_READY.get(str(db._db_path()), db._FTS_TOKENIZER)
        if len(q) >= 3 and tokenizer == "trigram":
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
        else:
            clause, params = _fts_clause(q)
            rows = conn.execute(
                "SELECT d.* FROM documents d WHERE 1=1" + clause +
                " ORDER BY d.pinned DESC, COALESCE(NULLIF(d.updated,''),d.created) DESC,d.id DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
    return [_row_doc(r) for r in rows]


def get_docs_by_ids(doc_ids, include_body: bool = False) -> dict[str, dict[str, Any]]:
    ensure_ready()
    ids = list(dict.fromkeys(str(x) for x in doc_ids if str(x)))
    out = {}
    with _connect() as conn:
        _init_db(conn)
        for start in range(0, len(ids), 400):
            batch = ids[start:start + 400]
            marks = ",".join("?" for _ in batch)
            for row in conn.execute(f"SELECT * FROM documents WHERE id IN ({marks})", batch):
                if include_body:
                    doc = store._doc_from_path(str(row["kind"]), _root() / str(row["path"]))
                else:
                    doc = _row_doc(row, check_attachment=False)
                out[str(row["id"])] = doc
    return out


def document_metadata() -> list[dict[str, Any]]:
    ensure_ready()
    with _connect() as conn:
        _init_db(conn)
        return [_row_doc(row, check_attachment=False) for row in conn.execute("SELECT * FROM documents")]


def project_names() -> list[str]:
    ensure_ready()
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
    ensure_ready()
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
    ensure_ready()
    with _connect() as conn:
        _init_db(conn)
        rows = conn.execute(
            "SELECT * FROM todos_index ORDER BY done ASC, CASE WHEN due='' THEN 1 ELSE 0 END, due ASC, updated DESC"
        ).fetchall()
    from .todos import is_overdue  # 逾期口径与 /api/todos 同源，避免两处各算一份
    out = []
    for r in rows:
        item = {
            "id": r["id"], "title": r["title"], "done": bool(r["done"]), "project": r["project"],
            "project_id": r["project_id"], "priority": r["priority"], "due": r["due"],
            "completed_at": (r["completed_at"] if "completed_at" in r.keys() else ""),
            "created": r["created"], "updated": r["updated"],
        }
        item["overdue"] = is_overdue(item)
        out.append(item)
    return out


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
    ensure_ready()
    today_obj = date.today(); today = today_obj.isoformat()
    with _connect() as conn:
        _init_db(conn)
        conn.create_function("milestone_state", 1, store.milestone_status_class)
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
                   SUM(CASE WHEN d.kind='milestone' AND milestone_state(d.status)<>'done' THEN 1 ELSE 0 END) AS open_milestones,
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
        "academic": store.academic_progress(profile, today_obj),
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
    # v261009 · 惰性导入：索引查询层不在导入期就拖进 LLM/会话层（P12 层级倒置）。
    from . import agent
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
