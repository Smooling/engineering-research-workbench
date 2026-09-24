from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import store
from . import perf_index_db as db
from .perf_index_db import (
    SCHEMA_VERSION, WORKSPACE_SCHEMA_VERSION, SYNC_INTERVAL_SECONDS, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE,
    DEFAULT_GRAPH_LIMIT, MAX_GRAPH_LIMIT, OVERVIEW_GRAPH_LIMIT, _LOCK, _FTS_TOKENIZER, _connect, _db_path,
    _ensure_schema_marker, _init_db, _json_list, _loads_list, _root,
)

def initialize(force: bool = False) -> dict[str, Any]:
    _ensure_schema_marker()
    with _LOCK:
        with _connect() as conn:
            _init_db(conn)
    return sync(force=force)


def _doc_paths() -> Iterable[tuple[str, Path]]:
    root = _root()
    for kind, rel in store.kind_dir_map().items():
        folder = root / rel
        folder.mkdir(parents=True, exist_ok=True)
        try:
            paths = sorted(folder.glob("*.md"))
        except OSError:
            paths = []
        for path in paths:
            if path.is_file():
                yield kind, path


def _relative(path: Path) -> str:
    return str(path.relative_to(_root())).replace("\\", "/")


def _rag_sections(body: str) -> list[tuple[list[str], str]]:
    lines = str(body or "").splitlines()
    stack: list[tuple[int, str]] = []
    path: list[str] = []
    buf: list[str] = []
    out: list[tuple[list[str], str]] = []
    fence = chr(96) * 3
    in_fence = False

    def flush() -> None:
        nonlocal buf
        text = "\n".join(buf).strip()
        if text:
            out.append((list(path), text))
        buf = []

    for line in lines:
        if line.lstrip().startswith(fence):
            in_fence = not in_fence
            buf.append(line)
            continue
        match = None if in_fence else re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            path = [item[1] for item in stack]
        else:
            buf.append(line)
    flush()
    return out or [([], str(body or "").strip())]


def _rag_blocks(text: str) -> list[str]:
    lines = str(text or "").splitlines()
    out: list[str] = []
    buf: list[str] = []
    fence = chr(96) * 3
    in_fence = False

    def flush() -> None:
        nonlocal buf
        block = "\n".join(buf).strip()
        if block:
            out.append(block)
        buf = []

    for line in lines:
        if line.lstrip().startswith(fence):
            in_fence = not in_fence
            buf.append(line)
            continue
        if not in_fence and not line.strip():
            flush()
        else:
            buf.append(line)
    flush()
    return out


def _rag_chunks(text: str, target_chars: int = 1800, max_chars: int = 3200) -> list[str]:
    blocks = _rag_blocks(text)
    if not blocks:
        return []
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for block in blocks:
        extra = len(block) + (2 if buf else 0)
        if buf and size + extra > max_chars:
            chunks.append("\n\n".join(buf).strip())
            buf, size = [], 0
        if len(block) > max_chars and not buf:
            # Preserve fenced code, equations and tables as indivisible semantic blocks.
            if block.lstrip().startswith(chr(96) * 3) or "$" in block or ("|" in block and "\n" in block):
                chunks.append(block)
                continue
            sentences = re.split(r"(?<=[。！？.!?])\s*", block)
            for sentence in sentences:
                if not sentence:
                    continue
                if buf and size + len(sentence) > max_chars:
                    chunks.append("\n\n".join(buf).strip())
                    buf, size = [], 0
                buf.append(sentence)
                size += len(sentence)
            continue
        buf.append(block)
        size += extra
        if size >= target_chars:
            chunks.append("\n\n".join(buf).strip())
            buf, size = [], 0
    if buf:
        chunks.append("\n\n".join(buf).strip())
    return [x for x in chunks if x]


def _rag_unit_id(doc_id: str, level: str, heading: str, ordinal: int) -> str:
    raw = f"{doc_id}|{level}|{heading}|{ordinal}".encode("utf-8")
    return "rag-" + hashlib.sha1(raw).hexdigest()[:20]


def _replace_rag_units_conn(
    conn: sqlite3.Connection,
    doc_id: str,
    title: str,
    body: str,
    projects: list[str],
    tags: list[str],
    updated: str,
) -> None:
    conn.execute("DELETE FROM rag_units_fts WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM rag_units WHERE doc_id=?", (doc_id,))

    sections = _rag_sections(body)
    heading_outline = " > ".join(path[-1] for path, _ in sections if path)[:2200]
    project_text = ", ".join(projects)
    tag_text = ", ".join(tags)
    units: list[tuple[str, str, int, str, str, str, str, str]] = []

    doc_text = str(body or "").strip()
    if len(doc_text) > 3600:
        doc_text = doc_text[:2400] + "\n…\n" + doc_text[-900:]
    doc_embedding = (
        f"文档：{title}\n项目：{project_text or '未归属'}\n标签：{tag_text or '无'}\n"
        f"目录：{heading_outline or '无'}\n\n{doc_text}"
    )
    doc_hash = hashlib.sha1(doc_embedding.encode("utf-8")).hexdigest()
    units.append((_rag_unit_id(doc_id, "document", "", 0), "document", 0, "", doc_text, doc_embedding, doc_hash, updated))

    ordinal = 1
    for heading_path, section_text in sections:
        heading = " > ".join(heading_path[-4:])
        section_for_embedding = section_text
        if len(section_for_embedding) > 7000:
            section_for_embedding = section_for_embedding[:4400] + "\n…\n" + section_for_embedding[-1800:]
        section_embedding = (
            f"文档：{title}\n项目：{project_text or '未归属'}\n标签：{tag_text or '无'}\n"
            f"章节：{heading or '正文'}\n\n{section_for_embedding}"
        )
        section_hash = hashlib.sha1(section_embedding.encode("utf-8")).hexdigest()
        units.append((_rag_unit_id(doc_id, "section", heading, ordinal), "section", ordinal, heading, section_text, section_embedding, section_hash, updated))
        ordinal += 1

        chunks = _rag_chunks(section_text)
        if len(chunks) <= 1 and len(section_text) <= 2200:
            continue
        for chunk_index, chunk in enumerate(chunks):
            chunk_heading = heading + (f" · 片段{chunk_index + 1}" if heading else f"片段{chunk_index + 1}")
            chunk_embedding = (
                f"文档：{title}\n项目：{project_text or '未归属'}\n标签：{tag_text or '无'}\n"
                f"章节：{heading or '正文'}\n\n{chunk}"
            )
            chunk_hash = hashlib.sha1(chunk_embedding.encode("utf-8")).hexdigest()
            units.append((_rag_unit_id(doc_id, "chunk", heading, ordinal), "chunk", ordinal, chunk_heading, chunk, chunk_embedding, chunk_hash, updated))
            ordinal += 1

    conn.executemany(
        """
        INSERT INTO rag_units(unit_id,doc_id,level,ordinal,heading_path,text,embedding_text,content_hash,updated)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        [(unit_id, doc_id, level, ord_no, heading, text, emb, digest, upd)
         for unit_id, level, ord_no, heading, text, emb, digest, upd in units],
    )
    conn.executemany(
        "INSERT INTO rag_units_fts(unit_id,doc_id,title,heading,text) VALUES(?,?,?,?,?)",
        [(unit_id, doc_id, title, heading, text)
         for unit_id, level, ord_no, heading, text, emb, digest, upd in units],
    )


def ensure_rag_units(force: bool = False) -> dict[str, int]:
    with _LOCK:
        with _connect() as conn:
            _init_db(conn)
            if force:
                conn.execute("DELETE FROM rag_units_fts")
                conn.execute("DELETE FROM rag_units")
            rows = conn.execute(
                """
                SELECT d.id,d.title,d.projects_json,d.tags_json,d.updated,f.body
                FROM documents d
                JOIN documents_fts f ON f.doc_id=d.id
                LEFT JOIN rag_units ru ON ru.doc_id=d.id AND ru.level='document'
                WHERE ru.unit_id IS NULL
                ORDER BY d.updated DESC
                """
            ).fetchall()
            rebuilt = 0
            for row in rows:
                _replace_rag_units_conn(
                    conn,
                    str(row["id"]),
                    str(row["title"] or row["id"]),
                    str(row["body"] or ""),
                    _loads_list(row["projects_json"]),
                    _loads_list(row["tags_json"]),
                    str(row["updated"] or ""),
                )
                rebuilt += 1
            conn.commit()
            count = int(conn.execute("SELECT COUNT(*) FROM rag_units").fetchone()[0])
    return {"documents_rebuilt": rebuilt, "units": count}


def _project_pairs(meta: dict[str, Any]) -> list[tuple[str, str]]:
    names = _json_list(meta.get("projects"))
    legacy_name = str(meta.get("project") or "").strip()
    if legacy_name and legacy_name not in names:
        names.insert(0, legacy_name)
    ids = _json_list(meta.get("project_ids"))
    legacy_id = str(meta.get("project_id") or "").strip()
    if legacy_id and legacy_id not in ids:
        ids.insert(0, legacy_id)
    size = max(len(names), len(ids))
    out: list[tuple[str, str]] = []
    for i in range(size):
        name = names[i] if i < len(names) else ""
        pid = ids[i] if i < len(ids) else ""
        pair = (name, pid)
        if pair not in out and (name or pid):
            out.append(pair)
    return out


def _remove_doc_conn(conn: sqlite3.Connection, doc_id: str) -> None:
    conn.execute("DELETE FROM rag_units_fts WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM rag_units WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM documents_fts WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM graph_edges WHERE source=? OR target=?", (doc_id, doc_id))
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))


def _index_path_conn(conn: sqlite3.Connection, kind: str, path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    meta, body = store._frontmatter_parse(text)
    doc_id = str(meta.get("id") or path.stem)
    title = str(meta.get("title") or path.stem)
    status = str(meta.get("status") or ((store.kind_statuses(kind) or ["草稿"])[0]))
    created = str(meta.get("created") or "")
    updated = str(meta.get("updated") or created)
    project_pairs = _project_pairs(meta)
    projects = [name for name, _ in project_pairs if name]
    project_ids = [pid for _, pid in project_pairs if pid]
    legacy_project = str(meta.get("project") or (projects[0] if projects else ""))
    legacy_project_id = str(meta.get("project_id") or (project_ids[0] if project_ids else ""))
    tags = _json_list(meta.get("tags"))
    marks = _json_list(meta.get("kind_marks"))
    st = path.stat()
    rel = _relative(path)

    existing = conn.execute("SELECT id FROM documents WHERE path=?", (rel,)).fetchone()
    if existing and str(existing[0]) != doc_id:
        _remove_doc_conn(conn, str(existing[0]))
    existing_path = conn.execute("SELECT path FROM documents WHERE id=?", (doc_id,)).fetchone()
    if existing_path and str(existing_path[0]) != rel:
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.execute("DELETE FROM documents_fts WHERE doc_id=?", (doc_id,))

    conn.execute(
        """
        INSERT INTO documents(
            id,path,kind,title,status,created,updated,mtime_ns,size,excerpt,
            due,record_date,added_date,pinned,project,projects_json,project_id,
            project_ids_json,tags_json,kind_marks_json,authors,year,venue,doi,url,cite_key
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            path=excluded.path,kind=excluded.kind,title=excluded.title,status=excluded.status,
            created=excluded.created,updated=excluded.updated,mtime_ns=excluded.mtime_ns,
            size=excluded.size,excerpt=excluded.excerpt,due=excluded.due,
            record_date=excluded.record_date,added_date=excluded.added_date,pinned=excluded.pinned,
            project=excluded.project,projects_json=excluded.projects_json,project_id=excluded.project_id,
            project_ids_json=excluded.project_ids_json,tags_json=excluded.tags_json,
            kind_marks_json=excluded.kind_marks_json,authors=excluded.authors,year=excluded.year,
            venue=excluded.venue,doi=excluded.doi,url=excluded.url,cite_key=excluded.cite_key
        """,
        (
            doc_id, rel, kind, title, status, created, updated, int(st.st_mtime_ns), int(st.st_size),
            store._excerpt(body), str(meta.get("due") or ""), str(meta.get("record_date") or ""),
            str(meta.get("added_date") or ""), 1 if meta.get("pinned") else 0, legacy_project,
            json.dumps(projects, ensure_ascii=False), legacy_project_id,
            json.dumps(project_ids, ensure_ascii=False), json.dumps(tags, ensure_ascii=False),
            json.dumps(marks, ensure_ascii=False), str(meta.get("authors") or ""),
            str(meta.get("year") or ""), str(meta.get("venue") or ""), str(meta.get("doi") or ""),
            str(meta.get("url") or ""), str(meta.get("cite_key") or ""),
        ),
    )
    conn.execute("DELETE FROM document_projects WHERE doc_id=?", (doc_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO document_projects(doc_id,project_name,project_id) VALUES(?,?,?)",
        [(doc_id, name, pid) for name, pid in project_pairs],
    )
    conn.execute("DELETE FROM document_tags WHERE doc_id=?", (doc_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO document_tags(doc_id,tag) VALUES(?,?)",
        [(doc_id, tag) for tag in tags],
    )
    conn.execute("DELETE FROM document_marks WHERE doc_id=?", (doc_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO document_marks(doc_id,mark) VALUES(?,?)",
        [(doc_id, mark) for mark in marks],
    )
    conn.execute("DELETE FROM document_links WHERE doc_id=?", (doc_id,))
    links = []
    for token in store.WIKILINK_RE.findall(body):
        token = str(token).strip()
        if token and token not in links:
            links.append(token)
    conn.executemany(
        "INSERT OR IGNORE INTO document_links(doc_id,token) VALUES(?,?)",
        [(doc_id, token) for token in links],
    )
    conn.execute("DELETE FROM documents_fts WHERE doc_id=?", (doc_id,))
    conn.execute(
        "INSERT INTO documents_fts(doc_id,title,body,tags,projects) VALUES(?,?,?,?,?)",
        (doc_id, title, body, " ".join(tags), " ".join(projects)),
    )
    _replace_rag_units_conn(conn, doc_id, title, body, projects, tags, updated)
    return doc_id


def _rebuild_graph_edges(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM graph_edges")
    project_rows = conn.execute(
        "SELECT doc_id,project_name,project_id FROM document_projects"
    ).fetchall()
    for row in project_rows:
        key = str(row["project_id"] or row["project_name"] or "").strip()
        if key:
            conn.execute(
                "INSERT OR IGNORE INTO graph_edges(source,target,relation) VALUES(?,?,?)",
                (row["doc_id"], "project:" + key, "project"),
            )
    tag_rows = conn.execute("SELECT doc_id,tag FROM document_tags").fetchall()
    for row in tag_rows:
        tag = str(row["tag"] or "").strip()
        if tag:
            conn.execute(
                "INSERT OR IGNORE INTO graph_edges(source,target,relation) VALUES(?,?,?)",
                (row["doc_id"], "tag:" + tag, "tag"),
            )
    by_id = {str(r[0]) for r in conn.execute("SELECT id FROM documents")}
    by_title: dict[str, str] = {}
    for row in conn.execute("SELECT id,title FROM documents ORDER BY updated DESC"):
        key = str(row["title"] or "").strip().casefold()
        if key and key not in by_title:
            by_title[key] = str(row["id"])
    for row in conn.execute("SELECT doc_id,token FROM document_links"):
        source = str(row["doc_id"])
        token = str(row["token"] or "").strip()
        target = token if token in by_id else by_title.get(token.casefold())
        if target and target != source:
            conn.execute(
                "INSERT OR IGNORE INTO graph_edges(source,target,relation) VALUES(?,?,?)",
                (source, target, "wikilink"),
            )


def _todos_path() -> Path:
    return _root() / "System" / "todos.json"


def _sync_todos_conn(conn: sqlite3.Connection, force: bool = False) -> bool:
    path = _todos_path()
    try:
        st = path.stat()
        signature = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        signature = "missing"
    old = conn.execute("SELECT value FROM meta WHERE key='todos_signature'").fetchone()
    if not force and old and str(old[0]) == signature:
        return False
    items: list[dict[str, Any]] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                items = [x for x in data if isinstance(x, dict)]
        except Exception:
            items = []
    conn.execute("DELETE FROM todos_index")
    conn.executemany(
        """
        INSERT OR REPLACE INTO todos_index(
            id,title,done,project,project_id,priority,due,created,updated
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                str(x.get("id") or ""), str(x.get("title") or ""), 1 if x.get("done") else 0,
                str(x.get("project") or ""), str(x.get("project_id") or ""),
                str(x.get("priority") or ""), str(x.get("due") or ""),
                str(x.get("created") or ""), str(x.get("updated") or ""),
            )
            for x in items if str(x.get("id") or "")
        ],
    )
    conn.execute(
        "INSERT INTO meta(key,value) VALUES('todos_signature',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (signature,),
    )
    return True


def _activity_path() -> Path:
    return _root() / "System" / "activity.jsonl"


def _reset_activity_conn(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM activity_daily")
    conn.execute(
        "INSERT INTO meta(key,value) VALUES('activity_offset','0') "
        "ON CONFLICT(key) DO UPDATE SET value='0'"
    )


def _sync_activity_conn(conn: sqlite3.Connection, force: bool = False) -> bool:
    path = _activity_path()
    if not path.exists():
        if force:
            _reset_activity_conn(conn)
        return False
    size = path.stat().st_size
    old = conn.execute("SELECT value FROM meta WHERE key='activity_offset'").fetchone()
    offset = int(old[0]) if old and str(old[0]).isdigit() else 0
    if force or size < offset:
        _reset_activity_conn(conn)
        offset = 0
    if size == offset:
        return False
    changed = False
    with path.open("rb") as f:
        f.seek(offset)
        while True:
            raw = f.readline()
            if not raw:
                break
            try:
                item = json.loads(raw.decode("utf-8"))
                if not isinstance(item, dict):
                    continue
                ts = str(item.get("timestamp") or "")
                typ = str(item.get("type") or "activity")
                day = datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
                count = max(1, int(item.get("weight") or 1))
            except Exception:
                continue
            conn.execute(
                """
                INSERT INTO activity_daily(date,type,count) VALUES(?,?,?)
                ON CONFLICT(date,type) DO UPDATE SET count=count+excluded.count
                """,
                (day, typ, count),
            )
            changed = True
        offset = f.tell()
    conn.execute(
        "INSERT INTO meta(key,value) VALUES('activity_offset',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(offset),),
    )
    return changed


def sync(force: bool = False) -> dict[str, Any]:
    now_mono = time.monotonic()
    if not force and db._LAST_SYNC_MONO and now_mono - db._LAST_SYNC_MONO < SYNC_INTERVAL_SECONDS:
        return status(sync_first=False)
    with _LOCK:
        now_mono = time.monotonic()
        if not force and db._LAST_SYNC_MONO and now_mono - db._LAST_SYNC_MONO < SYNC_INTERVAL_SECONDS:
            return status(sync_first=False)
        with _connect() as conn:
            _init_db(conn)
            existing = {
                str(r["path"]): (str(r["id"]), int(r["mtime_ns"]), int(r["size"]))
                for r in conn.execute("SELECT id,path,mtime_ns,size FROM documents")
            }
            seen: set[str] = set()
            changed_docs = 0
            for kind, path in _doc_paths():
                try:
                    st = path.stat()
                except OSError:
                    continue
                rel = _relative(path)
                seen.add(rel)
                old = existing.get(rel)
                if force or not old or old[1] != int(st.st_mtime_ns) or old[2] != int(st.st_size):
                    try:
                        _index_path_conn(conn, kind, path)
                        changed_docs += 1
                    except (OSError, UnicodeError):
                        continue
            removed = 0
            for rel, (doc_id, _, _) in existing.items():
                if rel not in seen:
                    _remove_doc_conn(conn, doc_id)
                    removed += 1
            if changed_docs or removed or force:
                _rebuild_graph_edges(conn)
            _sync_todos_conn(conn, force=force)
            _sync_activity_conn(conn, force=force)
            db._LAST_SYNC_ISO = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO meta(key,value) VALUES('last_sync',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (db._LAST_SYNC_ISO,),
            )
            conn.commit()
        db._LAST_SYNC_MONO = time.monotonic()
    return status(sync_first=False)


def index_doc_path(path_value: str | Path) -> dict[str, Any]:
    root = _root().resolve()
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if root != path and root not in path.parents:
        raise ValueError("Path escapes Workspace")
    kind = ""
    for k, rel in store.kind_dir_map().items():
        folder = (root / rel).resolve()
        if path.parent == folder:
            kind = k
            break
    if not kind or not path.exists():
        return sync(force=True)
    with _LOCK:
        with _connect() as conn:
            _init_db(conn)
            _index_path_conn(conn, kind, path)
            _rebuild_graph_edges(conn)
            _sync_activity_conn(conn)
            conn.commit()
    return status(sync_first=False)


def remove_doc(doc_id: str) -> None:
    if not doc_id:
        return
    with _LOCK:
        with _connect() as conn:
            _init_db(conn)
            _remove_doc_conn(conn, doc_id)
            _rebuild_graph_edges(conn)
            _sync_activity_conn(conn)
            conn.commit()


def refresh_todos() -> None:
    with _LOCK:
        with _connect() as conn:
            _init_db(conn)
            _sync_todos_conn(conn, force=True)
            _sync_activity_conn(conn)
            conn.commit()


def rebuild() -> dict[str, Any]:
    with _LOCK:
        path = _db_path()
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(path) + suffix).unlink(missing_ok=True)
            except OSError:
                pass
        db._LAST_SYNC_MONO = 0.0
    return initialize(force=True)


def status(sync_first: bool = True) -> dict[str, Any]:
    if sync_first:
        sync()
    with _LOCK:
        with _connect() as conn:
            _init_db(conn)
            counts = {
                "documents": int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]),
                "edges": int(conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]),
                "todos": int(conn.execute("SELECT COUNT(*) FROM todos_index").fetchone()[0]),
                "activity_days": int(conn.execute("SELECT COUNT(DISTINCT date) FROM activity_daily").fetchone()[0]),
            }
            last = conn.execute("SELECT value FROM meta WHERE key='last_sync'").fetchone()
    try:
        db_size = _db_path().stat().st_size
    except OSError:
        db_size = 0
    return {
        "ok": True,
        "path": str(_db_path()),
        "schema_version": SCHEMA_VERSION,
        "workspace_schema_version": WORKSPACE_SCHEMA_VERSION,
        "fts_tokenizer": db._FTS_TOKENIZER,
        "last_sync": str(last[0]) if last else db._LAST_SYNC_ISO,
        "db_size": db_size,
        "counts": counts,
    }


def _row_doc(row: sqlite3.Row) -> dict[str, Any]:
    projects = _loads_list(row["projects_json"])
    project_ids = _loads_list(row["project_ids_json"])
    tags = _loads_list(row["tags_json"])
    marks = _loads_list(row["kind_marks_json"])
    return {
        "id": row["id"], "path": row["path"], "filename": Path(row["path"]).name,
        "kind": row["kind"], "title": row["title"], "status": row["status"],
        "created": row["created"], "updated": row["updated"], "excerpt": row["excerpt"],
        "due": row["due"], "record_date": row["record_date"], "added_date": row["added_date"],
        "pinned": bool(row["pinned"]), "project": row["project"], "projects": projects,
        "project_id": row["project_id"], "project_ids": project_ids, "tags": tags,
        "kind_marks": marks, "authors": row["authors"], "year": row["year"],
        "venue": row["venue"], "doi": row["doi"], "url": row["url"], "cite_key": row["cite_key"],
    }


def _registry() -> list[dict[str, Any]]:
    path = _root() / "System" / "projects.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [dict(x) for x in data if isinstance(x, dict)] if isinstance(data, list) else []
    except Exception:
        return []
