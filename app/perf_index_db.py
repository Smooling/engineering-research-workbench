from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from . import workspace

SCHEMA_VERSION=2
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

def _root() -> Path:
    return workspace.ensure_workspace(run_migration=False)


def _db_path() -> Path:
    path = _root() / "System" / "Cache" / "index.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


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


def _init_db(conn: sqlite3.Connection) -> None:
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
            cite_key TEXT NOT NULL DEFAULT ''
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
            PRIMARY KEY(doc_id, token),
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

        CREATE TABLE IF NOT EXISTS rag_units (
            unit_id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            level TEXT NOT NULL,
            ordinal INTEGER NOT NULL DEFAULT 0,
            heading_path TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            embedding_text TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            updated TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_rag_units_doc ON rag_units(doc_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_rag_units_level ON rag_units(level);

        CREATE TABLE IF NOT EXISTS rag_embeddings (
            unit_id TEXT NOT NULL,
            model_key TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            dim INTEGER NOT NULL DEFAULT 0,
            norm REAL NOT NULL DEFAULT 0,
            vector BLOB NOT NULL,
            updated TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(unit_id, model_key),
            FOREIGN KEY(unit_id) REFERENCES rag_units(unit_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_rag_embeddings_model ON rag_embeddings(model_key);

        CREATE TABLE IF NOT EXISTS todos_index (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            done INTEGER NOT NULL DEFAULT 0,
            project TEXT NOT NULL DEFAULT '',
            project_id TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT '',
            due TEXT NOT NULL DEFAULT '',
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
        """
    )

    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if not row or int(row[0] or 0) != SCHEMA_VERSION:
        conn.execute(
            "INSERT INTO meta(key,value) VALUES('schema_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )

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
    elif not _FTS_TOKENIZER:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='documents_fts'"
        ).fetchone()
        text = str(sql[0] if sql else "")
        _FTS_TOKENIZER = "trigram" if "trigram" in text else "unicode61"

    rag_fts_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rag_units_fts'"
    ).fetchone()
    if not rag_fts_exists:
        tokenizer = "trigram" if _FTS_TOKENIZER == "trigram" else "unicode61"
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE rag_units_fts USING fts5("
                "unit_id UNINDEXED, doc_id UNINDEXED, title, heading, text, tokenize='" + tokenizer + "')"
            )
        except sqlite3.OperationalError:
            conn.execute(
                "CREATE VIRTUAL TABLE rag_units_fts USING fts5("
                "unit_id UNINDEXED, doc_id UNINDEXED, title, heading, text, tokenize='unicode61')"
            )
    conn.commit()
