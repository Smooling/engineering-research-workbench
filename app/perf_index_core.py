from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import activity, store
from . import perf_index_db as db
from .perf_index_db import (
    SCHEMA_VERSION, WORKSPACE_SCHEMA_VERSION, SYNC_INTERVAL_SECONDS, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE,
    DEFAULT_GRAPH_LIMIT, MAX_GRAPH_LIMIT, OVERVIEW_GRAPH_LIMIT, _LOCK, _connect, _db_path,
    _ensure_schema_marker, _init_db, _json_list, _loads_list, _root,
)

_READY_ROOTS: set[str] = set()
_STATUS: dict[str, dict[str, Any]] = {}
_SYNC_TIMES: dict[str, float] = {}
_SYNCING: set[str] = set()
_WORKER_LOCK = threading.Lock()
_STOP = threading.Event()
_WORKER: threading.Thread | None = None


def ensure_ready() -> None:
    """Read paths never wait for a periodic filesystem scan."""
    root = _root()
    key = str(root)
    if key in _READY_ROOTS and not _db_path(root).exists():
        _READY_ROOTS.discard(key)
        _STATUS.pop(key, None)
        _SYNC_TIMES.pop(key, None)
    if key not in _READY_ROOTS:
        initialize()


def start_background_sync() -> None:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER and _WORKER.is_alive():
            return
        _STOP.clear()
        def run():
            while not _STOP.wait(SYNC_INTERVAL_SECONDS):
                try:
                    sync()
                except Exception as exc:
                    key = str(_root())
                    _STATUS[key] = {**_STATUS.get(key, {}), "last_error": str(exc)}
        _WORKER = threading.Thread(target=run, name="workbench-index-sync", daemon=True)
        _WORKER.start()


def stop_background_sync() -> None:
    _STOP.set()
    worker = _WORKER
    if worker and worker is not threading.current_thread():
        worker.join(timeout=5)

def initialize(force: bool = False) -> dict[str, Any]:
    with _LOCK:
        _ensure_schema_marker()
        with _connect() as conn:
            # v260923 · _init_db 返回是否发生 schema 迁移（如 attachment 补列），
            # 迁移后旧行 attachment 为空，需强制重索引回填
            if _init_db(conn):
                force = True
            pending = conn.execute("SELECT value FROM meta WHERE key='index_rebuild_required'").fetchone()
            if pending and pending[0] == "1":
                force = True
        result = sync(force=force)
        _READY_ROOTS.add(str(_root()))
    start_background_sync()
    return result


#: 版本/快照条目的 frontmatter 标记（v261009.57）
_VARIANT_MARK = "variant_of:"


def is_variant_file(path: Path) -> bool:
    """这个 .md 是不是"版本/快照条目"（只读文件头，不做完整解析）。

    版本条目**不进索引**：它们是"历史"，只在「版本」页里出现（那一页走文件层 `store.list_docs`）。
    这样工作总结/笔记等列表与检索都不会再看到一堆残留版本（用户反馈）。
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(1200)
    except OSError:
        return False
    if not head.startswith("---"):
        return False
    end = head.find("\n---", 3)
    return _VARIANT_MARK in (head[:end] if end > 0 else head)


def _doc_paths(root: Path | None = None) -> Iterable[tuple[str, Path, os.stat_result]]:
    root = root or _root()
    for kind, rel in store.kind_dir_map().items():
        folder = root / rel
        folder.mkdir(parents=True, exist_ok=True)
        try:
            with os.scandir(folder) as entries:
                listing = list(entries)
        except OSError:
            listing = []
        for entry in sorted(listing, key=lambda e: e.name):
            if not entry.name.lower().endswith(".md") or not entry.is_file(follow_symlinks=False):
                continue
            path = Path(entry.path)
            if is_variant_file(path):        # 版本/快照 → 不入库（列表/检索/计数都看不到）
                continue
            try:
                yield kind, path, entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue


def _relative(path: Path, root: Path | None = None) -> str:
    return path.relative_to(root or _root()).as_posix()


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


def _affected_sources(conn: sqlite3.Connection, keys: set[str]) -> set[str]:
    if not keys:
        return set()
    marks = ",".join("?" for _ in keys)
    return {str(r[0]) for r in conn.execute(
        f"SELECT DISTINCT doc_id FROM document_links WHERE token_key IN ({marks})", list(keys))}


def _remove_doc_conn(conn: sqlite3.Connection, doc_id: str, update_graph: bool = True) -> None:
    row = conn.execute("SELECT rowid,title_key FROM documents WHERE id=?", (doc_id,)).fetchone()
    affected = _affected_sources(conn, {doc_id.casefold(), str(row[1])}) if row and update_graph else set()
    if row:
        conn.execute("DELETE FROM documents_fts WHERE rowid=?", (row[0],))
    conn.execute("DELETE FROM graph_edges WHERE source=? OR target=?", (doc_id, doc_id))
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    if affected:
        _refresh_graph_edges(conn, affected - {doc_id})


def _index_path_conn(conn: sqlite3.Connection, kind: str, path: Path, root: Path | None = None, update_graph: bool = True) -> str:
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
    rel = _relative(path, root)
    previous = conn.execute("SELECT title_key FROM documents WHERE id=?", (doc_id,)).fetchone()
    keys = {doc_id.casefold(), title.strip().casefold()}
    if previous:
        keys.add(str(previous[0]))

    existing = conn.execute("SELECT id FROM documents WHERE path=?", (rel,)).fetchone()
    if existing and str(existing[0]) != doc_id:
        _remove_doc_conn(conn, str(existing[0]), update_graph=update_graph)
    existing_path = conn.execute("SELECT path FROM documents WHERE id=?", (doc_id,)).fetchone()
    if existing_path and str(existing_path[0]) != rel:
        # Keep the rowid when the same document moves to a different path.
        conn.execute("UPDATE documents SET path=? WHERE id=?", (rel, doc_id))

    conn.execute(
        """
        INSERT INTO documents(
            id,path,kind,title,status,created,updated,mtime_ns,size,excerpt,
            due,record_date,added_date,pinned,project,projects_json,project_id,
            project_ids_json,tags_json,kind_marks_json,authors,year,venue,doi,url,cite_key,attachment
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            path=excluded.path,kind=excluded.kind,title=excluded.title,status=excluded.status,
            created=excluded.created,updated=excluded.updated,mtime_ns=excluded.mtime_ns,
            size=excluded.size,excerpt=excluded.excerpt,due=excluded.due,
            record_date=excluded.record_date,added_date=excluded.added_date,pinned=excluded.pinned,
            project=excluded.project,projects_json=excluded.projects_json,project_id=excluded.project_id,
            project_ids_json=excluded.project_ids_json,tags_json=excluded.tags_json,
            kind_marks_json=excluded.kind_marks_json,authors=excluded.authors,year=excluded.year,
            venue=excluded.venue,doi=excluded.doi,url=excluded.url,cite_key=excluded.cite_key,
            attachment=excluded.attachment
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
            str(meta.get("attachment") or ""),
        ),
    )
    conn.execute("UPDATE documents SET title_key=? WHERE id=?", (title.strip().casefold(), doc_id))
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
    # v261008.2 · (token, role)：关系类型由「关联」段小标题或行内标签推导（见 store.iter_body_links）
    links = store.iter_body_links(body)
    conn.executemany(
        "INSERT OR IGNORE INTO document_links(doc_id,token,role,token_key) VALUES(?,?,?,?)",
        [(doc_id, token, role, token.casefold()) for token, role in links],
    )
    rowid = conn.execute("SELECT rowid FROM documents WHERE id=?", (doc_id,)).fetchone()[0]
    if previous:
        conn.execute("DELETE FROM documents_fts WHERE rowid=?", (rowid,))
    searchable_body = "\n".join([body, *(str(meta.get(k) or "") for k in ("authors", "venue", "doi", "cite_key", "year"))])
    conn.execute(
        "INSERT INTO documents_fts(rowid,doc_id,title,body,tags,projects) VALUES(?,?,?,?,?,?)",
        (rowid, doc_id, title, searchable_body, " ".join(tags), " ".join(projects)),
    )
    if update_graph:
        _refresh_graph_edges(conn, {doc_id} | _affected_sources(conn, keys))
    return doc_id


def _rebuild_graph_edges(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM graph_edges")
    _insert_graph_edges(conn)


def _refresh_graph_edges(conn: sqlite3.Connection, doc_ids: set[str]) -> None:
    ids = list(doc_ids)
    for start in range(0, len(ids), 400):
        batch = ids[start:start + 400]
        marks = ",".join("?" for _ in batch)
        conn.execute(f"DELETE FROM graph_edges WHERE source IN ({marks})", batch)
        _insert_graph_edges(conn, batch)


def _insert_graph_edges(conn: sqlite3.Connection, doc_ids: list[str] | None = None) -> None:
    args = doc_ids or []
    where = " WHERE doc_id IN (" + ",".join("?" for _ in args) + ")" if doc_ids is not None else ""
    conn.execute(
        "INSERT OR IGNORE INTO graph_edges SELECT doc_id,'project:' || "
        "COALESCE(NULLIF(project_id,''),project_name),'project' FROM document_projects" + where,
        args,
    )
    conn.execute("INSERT OR IGNORE INTO graph_edges SELECT doc_id,'tag:' || tag,'tag' FROM document_tags" + where, args)
    # v261008.2 + v3 · 链接边：target 由 id/token_key 归一化解析，relation 取 role（缺省 wikilink）
    _link_targets = (
        "SELECT doc_id AS source, COALESCE(NULLIF(l.role,''),'wikilink') AS role, COALESCE("
        "(SELECT id FROM documents WHERE id=l.token),"
        "(SELECT id FROM documents WHERE title_key=l.token_key ORDER BY updated DESC,id DESC LIMIT 1)"
        ") AS target FROM document_links l"
    )
    # 类型化边（依据知识 / 使用数据 / 引用文献 / 同系列 / 环节链 / 产出汇总）
    conn.execute(
        "INSERT OR IGNORE INTO graph_edges(source,target,relation) "
        "SELECT source,target,role FROM (" + _link_targets + where + ") "
        "WHERE target IS NOT NULL AND source<>target",
        args,
    )
    # 兼容通用边：只认 `wikilink` 的旧消费方（含前端默认筛选）继续可用
    conn.execute(
        "INSERT OR IGNORE INTO graph_edges(source,target,relation) "
        "SELECT source,target,'wikilink' FROM (" + _link_targets + where + ") "
        "WHERE target IS NOT NULL AND source<>target AND role<>'wikilink'",
        args,
    )


def _todos_path(root: Path | None = None) -> Path:
    return (root or _root()) / "System" / "todos.json"


def _sync_todos_conn(conn: sqlite3.Connection, force: bool = False, root: Path | None = None) -> bool:
    path = _todos_path(root)
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
        except (OSError, ValueError):
            # An external editor may be replacing JSON. Keep the last good index.
            return False
    conn.execute("DELETE FROM todos_index")
    conn.executemany(
        """
        INSERT OR REPLACE INTO todos_index(
            id,title,done,project,project_id,priority,due,completed_at,created,updated
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                str(x.get("id") or ""), str(x.get("title") or ""), 1 if x.get("done") else 0,
                str(x.get("project") or ""), str(x.get("project_id") or ""),
                str(x.get("priority") or ""), str(x.get("due") or ""),
                str(x.get("completed_at") or ""),
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


def _activity_path(root: Path | None = None) -> Path:
    return (root or _root()) / "System" / "activity.jsonl"


def _reset_activity_conn(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM activity_daily")
    conn.execute("DELETE FROM activity_seen")
    conn.execute("DELETE FROM activity_legacy")
    conn.execute(
        "INSERT INTO meta(key,value) VALUES('activity_offset','0') "
        "ON CONFLICT(key) DO UPDATE SET value='0'"
    )


def _sync_activity_conn(conn: sqlite3.Connection, force: bool = False, root: Path | None = None) -> bool:
    path = _activity_path(root)
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
            if not raw.endswith(b"\n"):
                # Retry an incomplete append on the next pass.
                f.seek(-len(raw), 1)
                break
            try:
                item = json.loads(raw.decode("utf-8-sig"))
                if not isinstance(item, dict):
                    continue
                ts = str(item.get("timestamp") or "")
                typ = str(item.get("type") or "activity")
                day = datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
                count = max(1, int(item.get("weight") or 1))
            except Exception:
                continue
            identity = item.get("id")
            if not identity:
                sha = activity.fingerprint(item)
                old_count = conn.execute("SELECT count FROM activity_legacy WHERE fingerprint=?", (sha,)).fetchone()
                occurrence = int(old_count[0]) + 1 if old_count else 1
                conn.execute("INSERT OR REPLACE INTO activity_legacy VALUES(?,?)", (sha, occurrence))
                identity = activity.legacy_id(sha, occurrence)
            if not isinstance(identity, str):
                continue
            if not conn.execute("INSERT OR IGNORE INTO activity_seen VALUES(?)", (identity,)).rowcount:
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


def sync(force: bool = False, *, immediate: bool = False) -> dict[str, Any]:
    root = _root()
    key = str(root)
    now_mono = time.monotonic()
    last = _SYNC_TIMES.get(key, 0)
    if not force and not immediate and last and now_mono - last < SYNC_INTERVAL_SECONDS:
        return status(sync_first=False)
    with _LOCK:
        now_mono = time.monotonic()
        last = _SYNC_TIMES.get(key, 0)
        if not force and not immediate and last and now_mono - last < SYNC_INTERVAL_SECONDS:
            return status(sync_first=False)
        _SYNCING.add(key)
        try:
            _scan(root, force)
        finally:
            _SYNCING.discard(key)
    return status(sync_first=False)


def _scan(root: Path, force: bool, reset: bool = False) -> None:
    key = str(root)
    with _connect(root) as conn:
        force = _init_db(conn) or force
        pending = conn.execute("SELECT value FROM meta WHERE key='index_rebuild_required'").fetchone()
        force = force or bool(pending and pending[0] == "1")
        if reset:
            for table in ("documents_fts", "documents", "graph_edges", "todos_index", "activity_daily", "activity_seen", "activity_legacy"):
                conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM meta WHERE key IN ('activity_offset','todos_signature')")
        existing = {
            str(r["path"]): (str(r["id"]), int(r["mtime_ns"]), int(r["size"]))
            for r in conn.execute("SELECT id,path,mtime_ns,size FROM documents")
        }
        seen: set[str] = set()
        changed_docs = 0
        failed_docs = 0
        skipped: list[str] = []
        for kind, path, st in _doc_paths(root):
            rel = _relative(path, root)
            seen.add(rel)
            old = existing.get(rel)
            if force or not old or old[1] != int(st.st_mtime_ns) or old[2] != int(st.st_size):
                try:
                    _index_path_conn(conn, kind, path, root, update_graph=not force)
                    changed_docs += 1
                except (OSError, UnicodeError) as exc:
                    # v261008.2 · 不再静默丢弃：跳过的文件必须能在索引状态里看到
                    failed_docs += 1
                    skipped.append(f"{kind}:{rel}: {type(exc).__name__}: {exc}")
                    continue
        removed = 0
        for rel, (doc_id, _, _) in existing.items():
            if rel not in seen:
                _remove_doc_conn(conn, doc_id, update_graph=not force)
                removed += 1
        if force:
            _rebuild_graph_edges(conn)
            if not failed_docs:
                conn.execute("DELETE FROM meta WHERE key='index_rebuild_required'")
        todo_changed = _sync_todos_conn(conn, force=force, root=root)
        activity_changed = _sync_activity_conn(conn, force=force, root=root)
        db._LAST_SYNC_ISO = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO meta(key,value) VALUES('last_sync',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (db._LAST_SYNC_ISO,),
        )
        conn.commit()
        _refresh_status(conn, root, changed=bool(changed_docs or removed or todo_changed or activity_changed or force),
                        docs_changed=bool(changed_docs or removed or force))
        if skipped:
            _STATUS[key] = {**_STATUS.get(key, {}), "skipped": skipped}
    db._LAST_SYNC_MONO = time.monotonic()
    _SYNC_TIMES[key] = db._LAST_SYNC_MONO

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
        raise ValueError("Document path must be an existing Markdown file in a knowledge directory")
    with _LOCK:
        with _connect(root) as conn:
            _init_db(conn)
            _index_path_conn(conn, kind, path, root)
            _sync_activity_conn(conn, root=root)
            conn.commit()
            _refresh_status(conn, root)
    return status(sync_first=False)


def remove_doc(doc_id: str) -> None:
    if not doc_id:
        return
    root = _root()
    with _LOCK:
        with _connect(root) as conn:
            _init_db(conn)
            _remove_doc_conn(conn, doc_id)
            _sync_activity_conn(conn, root=root)
            conn.commit()
            _refresh_status(conn, root)


def refresh_todos() -> None:
    root = _root()
    with _LOCK:
        with _connect(root) as conn:
            _init_db(conn)
            _sync_todos_conn(conn, force=True, root=root)
            _sync_activity_conn(conn, root=root)
            conn.commit()
            _refresh_status(conn, root, docs_changed=False)


def rebuild() -> dict[str, Any]:
    root = _root()
    with _LOCK:
        _ensure_schema_marker()
        _SYNCING.add(str(root))
        try:
            _scan(root, force=True, reset=True)
            _READY_ROOTS.add(str(root))
        finally:
            _SYNCING.discard(str(root))
    start_background_sync()
    return status(sync_first=False)


def status(sync_first: bool = True) -> dict[str, Any]:
    if sync_first:
        ensure_ready()
    root = _root()
    key = str(root)
    if key not in _STATUS:
        with _connect() as conn:
            _init_db(conn)
            _refresh_status(conn, root, changed=False)
    result = dict(_STATUS[key])
    result["counts"] = dict(result["counts"])
    result["sync_running"] = key in _SYNCING
    return result


def _refresh_status(conn: sqlite3.Connection, root: Path, changed: bool = True, docs_changed: bool = True) -> None:
    key = str(root)
    previous = _STATUS.get(key, {})
    counts = {
        "documents": int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]),
        "edges": int(conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]),
        "todos": int(conn.execute("SELECT COUNT(*) FROM todos_index").fetchone()[0]),
        "activity_days": int(conn.execute("SELECT COUNT(DISTINCT date) FROM activity_daily").fetchone()[0]),
    }
    last = conn.execute("SELECT value FROM meta WHERE key='last_sync'").fetchone()
    try:
        db_size = _db_path(root).stat().st_size
    except OSError:
        db_size = 0
    _STATUS[key] = {
        "ok": True,
        "path": str(_db_path(root)),
        "schema_version": SCHEMA_VERSION,
        "workspace_schema_version": WORKSPACE_SCHEMA_VERSION,
        "fts_tokenizer": db._FTS_TOKENIZER,
        "last_sync": str(last[0]) if last else db._LAST_SYNC_ISO,
        "db_size": db_size,
        "counts": counts,
        "version": int(previous.get("version", 0)) + int(changed),
        "documents_version": int(previous.get("documents_version", 0)) + int(changed and docs_changed),
    }


def _row_doc(row: sqlite3.Row, check_attachment: bool = True) -> dict[str, Any]:
    projects = _loads_list(row["projects_json"])
    project_ids = _loads_list(row["project_ids_json"])
    tags = _loads_list(row["tags_json"])
    marks = _loads_list(row["kind_marks_json"])
    # v260923 · 文献 PDF 附件：仅当路径指向真实存在的 .pdf 时才打附件标记（stat 检查，无内容读取）
    att = str(row["attachment"] or "") if "attachment" in row.keys() else ""
    att_ok = False
    if check_attachment and att.strip():
        att_path = Path(att)
        if not att_path.is_absolute():
            att_path = _root() / att
        att_ok = att_path.suffix.lower() == ".pdf" and att_path.is_file()
    doc = {
        "id": row["id"], "path": row["path"], "filename": Path(row["path"]).name,
        "kind": row["kind"], "title": row["title"], "status": row["status"],
        "created": row["created"], "updated": row["updated"], "excerpt": row["excerpt"],
        "due": row["due"], "record_date": row["record_date"], "added_date": row["added_date"],
        "pinned": bool(row["pinned"]), "project": row["project"], "projects": projects,
        "project_id": row["project_id"], "project_ids": project_ids, "tags": tags,
        "kind_marks": marks, "authors": row["authors"], "year": row["year"],
        "venue": row["venue"], "doi": row["doi"], "url": row["url"], "cite_key": row["cite_key"],
        "attachment": att, "attachment_exists": att_ok,
    }

    if doc["kind"] == "milestone":
        doc["status_class"] = store.milestone_status_class(doc["status"])
    from .evidence import describe
    doc["evidence"] = describe(doc)
    return doc


def _registry() -> list[dict[str, Any]]:
    path = _root() / "System" / "projects.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [dict(x) for x in data if isinstance(x, dict)] if isinstance(data, list) else []
    except Exception:
        return []
