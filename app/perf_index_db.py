from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from . import workspace
from core.index import migrate as index_migrate

#: 索引结构版本 = 迁移清单里的最大目标版本（唯一来源：core/index/migrations）。
#: v261009 起不再在这里写死数字——原先有 5 处版本号各自演进（REFACTOR_PLAN §5.5.1）。
SCHEMA_VERSION = index_migrate.TARGET_VERSION
WORKSPACE_SCHEMA_VERSION=3
SYNC_INTERVAL_SECONDS=30.0
DEFAULT_PAGE_SIZE=50
MAX_PAGE_SIZE=200
DEFAULT_GRAPH_LIMIT=300
MAX_GRAPH_LIMIT=500
OVERVIEW_GRAPH_LIMIT=80
_LOCK=threading.RLock()
_LAST_SYNC_MONO=0.0
_LAST_SYNC_ISO=""
_FTS_TOKENIZER=""
_SCHEMA_READY: dict[str, str] = {}
_SCHEMA_LOCK = threading.RLock()


class _Connection(sqlite3.Connection):
    """A transaction scope also owns and closes its connection."""

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def _root() -> Path:
    return workspace.ensure_workspace(run_migration=False)


def _db_path(root: Path | None = None) -> Path:
    return (root or _root()) / "System" / "Cache" / "index.sqlite"


def _connect(root: Path | None = None) -> sqlite3.Connection:
    path = _db_path(root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with _SCHEMA_LOCK:
            _SCHEMA_READY.pop(str(path), None)
    conn = sqlite3.connect(path, timeout=30.0, factory=_Connection)
    conn.db_path = str(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def checkpoint(truncate: bool = True) -> dict:
    """关库前把 WAL 并回主库并截断（v261009 · A3）。

    长驻服务不关库时 WAL 会持续增长——实测 `index.sqlite-wal` 曾累积到 **21.4 MB**
    （比库体量还大），而库文件本身 80% 是空闲页。关库时 checkpoint(TRUNCATE)
    把这两项一起收拾干净；`python -m core.index.maintain` 可随时手动执行同一动作。
    """
    path = _db_path()
    if not path.is_file():
        return {"skipped": True, "reason": "索引库尚未建立"}
    mode = "TRUNCATE" if truncate else "PASSIVE"
    conn = sqlite3.connect(str(path), timeout=5.0)
    try:
        busy, log_pages, done = conn.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        return {"mode": mode, "busy": busy, "wal_pages": log_pages, "checkpointed": done}
    except sqlite3.Error as exc:
        return {"error": str(exc)}
    finally:
        conn.close()


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("[") and raw.endswith("]"):
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    return [str(x).strip() for x in data if str(x).strip()]
            except Exception:
                pass
        return [x.strip() for x in re.split(r"[,，]", raw) if x.strip()]
    return []


def _loads_list(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(str(raw))
        if isinstance(value, list):
            return [str(x) for x in value]
    except Exception:
        pass
    return []


def _ensure_schema_marker() -> None:
    path = _root() / "System" / "schema.json"
    current: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                current = data
        except Exception:
            current = {}
    changed = False
    if int(current.get("workspace_schema_version") or 0) < WORKSPACE_SCHEMA_VERSION:
        current["workspace_schema_version"] = WORKSPACE_SCHEMA_VERSION
        changed = True
    if int(current.get("index_schema_version") or 0) != SCHEMA_VERSION:
        current["index_schema_version"] = SCHEMA_VERSION
        changed = True
    if changed or not path.exists():
        current["updated"] = datetime.now().isoformat(timespec="seconds")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def _init_db(conn: sqlite3.Connection) -> bool:
    global _FTS_TOKENIZER
    with _SCHEMA_LOCK:
        path = conn.db_path
        if path in _SCHEMA_READY:
            _FTS_TOKENIZER = _SCHEMA_READY[path]
            return False
        return _initialize_schema(conn)


def _initialize_schema(conn: sqlite3.Connection) -> bool:
    global _FTS_TOKENIZER
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL DEFAULT '',
            updated TEXT NOT NULL DEFAULT '',
            mtime_ns INTEGER NOT NULL DEFAULT 0,
            size INTEGER NOT NULL DEFAULT 0,
            excerpt TEXT NOT NULL DEFAULT '',
            due TEXT NOT NULL DEFAULT '',
            record_date TEXT NOT NULL DEFAULT '',
            added_date TEXT NOT NULL DEFAULT '',
            pinned INTEGER NOT NULL DEFAULT 0,
            project TEXT NOT NULL DEFAULT '',
            projects_json TEXT NOT NULL DEFAULT '[]',
            project_id TEXT NOT NULL DEFAULT '',
            project_ids_json TEXT NOT NULL DEFAULT '[]',
            tags_json TEXT NOT NULL DEFAULT '[]',
            kind_marks_json TEXT NOT NULL DEFAULT '[]',
            authors TEXT NOT NULL DEFAULT '',
            year TEXT NOT NULL DEFAULT '',
            venue TEXT NOT NULL DEFAULT '',
            doi TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            cite_key TEXT NOT NULL DEFAULT '',
            attachment TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_documents_kind_updated ON documents(kind, updated DESC);
        CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
        CREATE INDEX IF NOT EXISTS idx_documents_due ON documents(kind, due);
        CREATE INDEX IF NOT EXISTS idx_documents_updated ON documents(updated DESC);

        CREATE TABLE IF NOT EXISTS document_projects (
            doc_id TEXT NOT NULL,
            project_name TEXT NOT NULL DEFAULT '',
            project_id TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(doc_id, project_name, project_id),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_document_projects_name ON document_projects(project_name);
        CREATE INDEX IF NOT EXISTS idx_document_projects_id ON document_projects(project_id);

        CREATE TABLE IF NOT EXISTS document_tags (
            doc_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            PRIMARY KEY(doc_id, tag),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_document_tags_tag ON document_tags(tag);

        CREATE TABLE IF NOT EXISTS document_marks (
            doc_id TEXT NOT NULL,
            mark TEXT NOT NULL,
            PRIMARY KEY(doc_id, mark),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_document_marks_mark ON document_marks(mark);

        CREATE TABLE IF NOT EXISTS document_links (
            doc_id TEXT NOT NULL,
            token TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'wikilink',
            PRIMARY KEY(doc_id, token, role),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS graph_edges (
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            relation TEXT NOT NULL,
            PRIMARY KEY(source, target, relation)
        );
        CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_relation ON graph_edges(relation);

        CREATE TABLE IF NOT EXISTS todos_index (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            done INTEGER NOT NULL DEFAULT 0,
            project TEXT NOT NULL DEFAULT '',
            project_id TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT '',
            due TEXT NOT NULL DEFAULT '',
            completed_at TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL DEFAULT '',
            updated TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_todos_done_due ON todos_index(done, due);
        CREATE INDEX IF NOT EXISTS idx_todos_project ON todos_index(project_id, project);

        CREATE TABLE IF NOT EXISTS activity_daily (
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(date, type)
        );
        -- v261022.0 · 上游同步引擎：按活动 id 去重（合并两端历史时不重复累计）+ 旧日志指纹计数
        CREATE TABLE IF NOT EXISTS activity_seen (id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS activity_legacy (fingerprint TEXT PRIMARY KEY, count INTEGER NOT NULL);
        """
    )

    # v261009 · 版本化迁移交给 core/index/migrate（原先四段内联 if：没有声明、没有验证、
    # 没有回滚、没有备份，出问题只能删库重建）。迁移是幂等的，新建库走上面的 DDL 后此处为 no-op。
    disk_version = index_migrate.guard_disk_version(conn, SCHEMA_VERSION)  # 磁盘版本高于代码 → 拒写
    result = index_migrate.apply(conn)
    upgraded = bool(result["changed"]) or disk_version != SCHEMA_VERSION
    # v3 · 归一化链接查询与列表排序：补 title_key / token_key 列与排序索引（幂等；迁移框架外的前向增列）。
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(documents)")}
    if "title_key" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN title_key TEXT NOT NULL DEFAULT ''")
        upgraded = True
    link_cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(document_links)")}
    if "token_key" not in link_cols:
        conn.execute("ALTER TABLE document_links ADD COLUMN token_key TEXT NOT NULL DEFAULT ''")
        upgraded = True
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_documents_title_key ON documents(title_key, updated DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_links_token_key ON document_links(token_key, doc_id);
        CREATE INDEX IF NOT EXISTS idx_documents_order ON documents(pinned DESC, COALESCE(NULLIF(updated,''),created) DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_documents_kind_order ON documents(kind, pinned DESC, COALESCE(NULLIF(updated,''),created) DESC, id DESC);
    """)

    fts_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents_fts'"
    ).fetchone()
    if not fts_exists:
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE documents_fts USING fts5("
                "doc_id UNINDEXED, title, body, tags, projects, tokenize='trigram')"
            )
            _FTS_TOKENIZER = "trigram"
        except sqlite3.OperationalError:
            conn.execute(
                "CREATE VIRTUAL TABLE documents_fts USING fts5("
                "doc_id UNINDEXED, title, body, tags, projects, tokenize='unicode61')"
            )
            _FTS_TOKENIZER = "unicode61"
    else:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='documents_fts'"
        ).fetchone()
        text = str(sql[0] if sql else "")
        _FTS_TOKENIZER = "trigram" if "trigram" in text else "unicode61"
    if upgraded:
        # Older FTS rowids were independent of documents.rowid. initialize()
        # reparses files once to establish the mapping and normalized columns.
        conn.execute("DELETE FROM documents_fts")
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('index_rebuild_required','1')")
    conn.commit()
    _SCHEMA_READY[conn.db_path] = _FTS_TOKENIZER
    return upgraded
