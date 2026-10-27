"""Local agent brain inspired by CortexDB's scoped memory and source context packs.

SQLite is the transactional runtime store. AgentChats JSON files are portable
session projections for existing backup/sync clients, never copies of the WAL.
No CortexDB code is vendored; this is a Python implementation of the data model.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .workspace import ensure_workspace

_LOCK = threading.RLock()
_READY: set[str] = set()
_IMPORT_STATS: dict[str, tuple[int, int, int]] = {}
SCHEMA_VERSION = 1
SCOPES = ("global", "user", "project", "session")
KINDS = ("fact", "preference", "procedure", "decision", "episode")


def now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def root() -> Path:
    path = ensure_workspace() / "System" / "Agent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return root() / "brain.sqlite"


@contextmanager
def connection():
    path = db_path()
    with _LOCK:
        fresh = not path.exists()
        conn = sqlite3.connect(path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        if fresh or str(path) not in _READY:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,payload TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),ordinal INTEGER NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id,ordinal);
                CREATE TABLE IF NOT EXISTS imports(path TEXT PRIMARY KEY,digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),status TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT '{}',updated TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS runs_session ON runs(session_id,updated);
                CREATE UNIQUE INDEX IF NOT EXISTS runs_active_session ON runs(session_id) WHERE status IN ('queued','running','pausing');
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL REFERENCES runs(id),kind TEXT NOT NULL,payload TEXT NOT NULL,created TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_run ON events(run_id,seq);
                CREATE TABLE IF NOT EXISTS tool_calls(run_id TEXT NOT NULL REFERENCES runs(id),call_id TEXT NOT NULL,name TEXT NOT NULL,args TEXT NOT NULL,status TEXT NOT NULL,result TEXT,PRIMARY KEY(run_id,call_id));
                CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY,namespace TEXT NOT NULL,scope TEXT NOT NULL,scope_id TEXT NOT NULL,memory_key TEXT NOT NULL,kind TEXT NOT NULL,content TEXT NOT NULL,source TEXT NOT NULL,importance REAL NOT NULL,expires REAL,status TEXT NOT NULL,embedding TEXT,created TEXT NOT NULL,updated TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS memories_scope ON memories(namespace,scope,scope_id,status);
                CREATE UNIQUE INDEX IF NOT EXISTS memories_current_key ON memories(namespace,scope,scope_id,memory_key) WHERE status='active';
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(id UNINDEXED,text,tokenize='unicode61');
                CREATE TABLE IF NOT EXISTS relations(memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,subject TEXT NOT NULL,predicate TEXT NOT NULL,object TEXT NOT NULL,PRIMARY KEY(memory_id,subject,predicate,object));
                CREATE INDEX IF NOT EXISTS relations_subject ON relations(subject);
                CREATE INDEX IF NOT EXISTS relations_object ON relations(object);
                CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            """)
            conn.execute("INSERT OR REPLACE INTO metadata VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
            from . import agent_sources
            agent_sources.schema(conn)
            conn.commit()
            _READY.add(str(path))
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def validate_session_id(session_id: str) -> str:
    if not re.fullmatch(r"chat-[a-zA-Z0-9_-]{6,80}", session_id or ""):
        raise ValueError("Invalid session id")
    return session_id


def _session(conn, session_id: str, include_deleted=False) -> dict:
    row = conn.execute("SELECT payload,deleted FROM sessions WHERE id=?", (validate_session_id(session_id),)).fetchone()
    if not row or (row["deleted"] and not include_deleted):
        raise FileNotFoundError(session_id)
    data = json.loads(row["payload"])
    data["messages"] = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM messages WHERE session_id=? ORDER BY ordinal,id", (session_id,))]
    return data


def save_session(data: dict, *, export=True, merge=False) -> dict:
    sid = validate_session_id(str(data.get("id") or ""))
    with _LOCK, connection() as conn:
        old = conn.execute("SELECT deleted FROM sessions WHERE id=?", (sid,)).fetchone()
        if old and old[0]:
            raise ValueError("会话已删除")
        payload = {k: v for k, v in data.items() if k not in ("messages", "source_archive")}
        conn.execute("INSERT INTO sessions(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (sid, encode(payload)))
        ordinal = conn.execute("SELECT COALESCE(MAX(ordinal),-1)+1 FROM messages WHERE session_id=?", (sid,)).fetchone()[0] if merge else 0
        if not merge:
            conn.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        for idx, message in enumerate(data.get("messages") or []):
            if not isinstance(message, dict) or message.get("role") not in ("user", "assistant", "system", "tool"):
                raise ValueError("无效的会话消息")
            msg = dict(message)
            msg.setdefault("id", "msg-" + hashlib.sha256((sid + str(idx) + encode(msg)).encode()).hexdigest()[:20])
            conn.execute("INSERT INTO messages VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (msg["id"], sid, ordinal + idx, encode(msg)))
        from . import agent_sources
        agent_sources.restore(conn, sid, data.get("source_archive"))
        result = _session(conn, sid)
    if export:
        with _LOCK:
            _export_session(get_session(sid, migrate=False))
    return result


def _export_session(data: dict) -> None:
    path = ensure_workspace() / "System" / "AgentChats" / (data["id"] + ".json")
    with _LOCK:
        from . import agent_sources
        with connection() as conn:
            data = {**data, "source_archive": agent_sources.archive(conn, data["id"])}
        atomic_json(path, data)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with connection() as conn:
            conn.execute("INSERT OR REPLACE INTO imports VALUES(?,?)", (str(path), digest))
        stat = path.stat()
        _IMPORT_STATS[str(path)] = (stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)


def migrate_legacy() -> int:
    """Idempotently merge legacy and sync-delivered JSON by stable message IDs."""
    imported = 0
    directory = ensure_workspace() / "System" / "AgentChats"
    for path in directory.glob("chat-*.json"):
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)
            if _IMPORT_STATS.get(str(path)) == signature:
                continue
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            with connection() as conn:
                row = conn.execute("SELECT digest FROM imports WHERE path=?", (str(path),)).fetchone()
                tombstone = conn.execute("SELECT deleted FROM sessions WHERE id=?", (path.stem,)).fetchone()
            if (row and row[0] == digest) or (tombstone and tombstone[0]):
                _IMPORT_STATS[str(path)] = signature
                continue
            data = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(data, dict) or data.get("id") != path.stem or not isinstance(data.get("messages"), list):
                continue
            with _LOCK:
                try:
                    current = get_session(path.stem, migrate=False)
                    if str(current.get("updated", "")) > str(data.get("updated", "")):
                        data = {**data, **{k: v for k, v in current.items() if k != "messages"}}
                except FileNotFoundError:
                    pass
                save_session(data, export=False, merge=True)
                with connection() as conn:
                    conn.execute("INSERT OR REPLACE INTO imports VALUES(?,?)", (str(path), digest))
                _IMPORT_STATS[str(path)] = signature
            imported += 1
        except (ValueError, OSError, TypeError):
            continue
    return imported


def get_session(session_id: str, *, migrate=True) -> dict:
    if migrate:
        migrate_legacy()
    with connection() as conn:
        return _session(conn, session_id)


def list_sessions() -> list[dict]:
    migrate_legacy()
    with connection() as conn:
        rows = conn.execute("SELECT s.payload,(SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS count,(SELECT json_extract(m.payload,'$.content') FROM messages m WHERE m.session_id=s.id ORDER BY ordinal DESC,id DESC LIMIT 1) AS preview FROM sessions s WHERE deleted=0").fetchall()
        result = []
        for row in rows:
            data = json.loads(row["payload"])
            result.append({**data, "message_count": row["count"], "preview": str(row["preview"] or "")[:160]})
    return sorted(result, key=lambda item: item.get("updated", ""), reverse=True)


def append_message(session_id: str, message: dict) -> dict:
    with _LOCK:
        data = get_session(session_id)
        if not any(m.get("id") == message.get("id") for m in data["messages"]):
            data["messages"].append(message)
        data["updated"] = now()
        data["archived"] = False
        if data.get("title") in ("", "新对话") and message.get("role") == "user":
            data["title"] = str(message.get("content") or "图片分析")[:36]
        return save_session(data)


def delete_session(session_id: str) -> dict:
    with _LOCK:
        data = get_session(session_id)
        with connection() as conn:
            if conn.execute("SELECT 1 FROM runs WHERE session_id=? AND status IN ('queued','running','pausing')", (session_id,)).fetchone():
                raise ValueError("请先停止正在执行的任务")
            conn.execute("UPDATE sessions SET deleted=1 WHERE id=?", (session_id,))
        target = ensure_workspace() / "System" / "AgentChats"
        atomic_json(target / "Trash" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + session_id + ".json"), data)
        (target / (session_id + ".json")).unlink(missing_ok=True)
    return {"ok": True}


def create_run(session_id: str, payload: dict) -> dict:
    run = {"id": "run-" + uuid.uuid4().hex, "session_id": session_id, "status": "queued", "created": now(), "updated": now(), "request": payload, "error": "", "result": None}
    try:
        with connection() as conn:
            _session(conn, session_id)
            conn.execute("INSERT INTO runs(id,session_id,status,payload,updated) VALUES(?,?,?,?,?)", (run["id"], session_id, "queued", encode(run), run["updated"]))
    except sqlite3.IntegrityError as exc:
        raise ValueError("此会话已有执行中的任务") from exc
    event(run["id"], "status", {"status": "queued"})
    return run


def get_run(run_id: str) -> dict:
    with connection() as conn:
        row = conn.execute("SELECT payload,state FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise FileNotFoundError(run_id)
    return {**json.loads(row["payload"]), "state": json.loads(row["state"])}


def list_runs(session_id="", limit=50) -> list[dict]:
    with connection() as conn:
        rows = conn.execute("SELECT payload FROM runs WHERE (?='' OR session_id=?) ORDER BY updated DESC LIMIT ?", (session_id, session_id, max(1, min(int(limit), 200)))).fetchall()
    return [json.loads(row[0]) for row in rows]


def update_run(run_id: str, *, state=None, **fields) -> dict:
    with _LOCK, connection() as conn:
        row = conn.execute("SELECT payload,state FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise FileNotFoundError(run_id)
        run = {**json.loads(row[0]), **fields, "updated": now()}
        conn.execute("UPDATE runs SET status=?,payload=?,state=?,updated=? WHERE id=?", (run["status"], encode(run), encode(state) if state is not None else row[1], run["updated"], run_id))
    return run


def event(run_id: str, kind: str, payload: dict) -> int:
    with connection() as conn:
        cur = conn.execute("INSERT INTO events(run_id,kind,payload,created) VALUES(?,?,?,?)", (run_id, kind, encode(payload), now()))
        return int(cur.lastrowid)


def events(run_id: str, after=0, limit=200) -> list[dict]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?", (run_id, max(0, int(after)), max(1, min(int(limit), 1000)))).fetchall()
    return [{"seq": r["seq"], "event": r["kind"], "data": json.loads(r["payload"]), "created": r["created"]} for r in rows]


def begin_tool(run_id: str, call_id: str, name: str, args: dict) -> dict | None:
    """Reserve before side effects. An uncertain interrupted call is never replayed."""
    with _LOCK, connection() as conn:
        row = conn.execute("SELECT status,result,name,args FROM tool_calls WHERE run_id=? AND call_id=?", (run_id, call_id)).fetchone()
        if row:
            if row["name"] != name or json.loads(row["args"]) != args:
                return {"ok": False, "error": "call_id 已用于不同参数，请使用新的工具调用 id"}
            if row["status"] == "done":
                return json.loads(row["result"])
            return {"ok": False, "uncertain": True, "error": "上次工具执行被中断，结果未知。请先读取目标核对，避免重复写入。"}
        conn.execute("INSERT INTO tool_calls VALUES(?,?,?,?,?,NULL)", (run_id, call_id, name, encode(args), "started"))
    return None


def finish_tool(run_id: str, call_id: str, result: dict) -> None:
    with connection() as conn:
        conn.execute("UPDATE tool_calls SET status='done',result=? WHERE run_id=? AND call_id=?", (encode(result), run_id, call_id))


def save_draft(draft: dict) -> dict:
    with connection() as conn:
        conn.execute("INSERT OR REPLACE INTO drafts VALUES(?,?)", (draft["id"], encode(draft)))
    return draft


def redact(text: str) -> str:
    text = re.sub(r"<private>.*?</private>", "[private omitted]", str(text), flags=re.I | re.S)
    text = re.sub(r"(?i)(api[_-]?key|authorization|password|secret|token)\s*[:=]\s*[\"']?[^\s\"',}]+", r"\1=[redacted]", text)
    return re.sub(r"\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}", "[credential omitted]", text)


def terms(text: str) -> list[str]:
    parts = re.findall(r"[a-zA-Z0-9_]{2,}|[\u3400-\u9fff]+", str(text).casefold())
    tokens = []
    for p in parts:
        tokens.append(p)
        if re.search(r"[\u3400-\u9fff]", p):
            tokens.extend(p[i:i + 2] for i in range(len(p) - 1))
    return list(dict.fromkeys(tokens))[:8192]


def _vector(value) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not 1 <= len(value) <= 8192:
        raise ValueError("embedding 必须是 1–8192 维数组")
    result = [float(v) for v in value]
    if not all(math.isfinite(v) for v in result) or not any(result):
        raise ValueError("embedding 必须为有限非零向量")
    return result


def remember(content: str, *, scope="session", scope_id="", namespace="research", kind="fact", source=None, importance=.5, ttl_seconds=0, memory_key="", supersedes=None, entities=None, relations=None, embedding=None) -> dict:
    content = redact(content).strip()
    if not content or len(content) > 32000:
        raise ValueError("记忆正文须为 1–32000 字符")
    if scope not in SCOPES or kind not in KINDS:
        raise ValueError("无效的记忆作用域或类型")
    if scope in ("session", "project") and not str(scope_id).strip():
        raise ValueError("会话/项目记忆需要 scope_id")
    if scope in ("global", "user"):
        scope_id = "local" if scope == "user" else ""
    key = str(memory_key or hashlib.sha256(content.encode()).hexdigest())[:200]
    vector = _vector(embedding)
    timestamp = now()
    mid = "mem-" + uuid.uuid4().hex
    with _LOCK, connection() as conn:
        old = conn.execute("SELECT * FROM memories WHERE namespace=? AND scope=? AND scope_id=? AND memory_key=? AND status='active'", (namespace, scope, scope_id, key)).fetchone()
        if old and old["content"] == content:
            return _memory(old)
        replaced = list(supersedes or []) + ([old["id"]] if old else [])
        for rid in replaced:
            row = conn.execute("SELECT namespace,scope,scope_id FROM memories WHERE id=?", (rid,)).fetchone()
            if not row or tuple(row) != (namespace, scope, scope_id):
                raise ValueError("只能替代同一作用域中的记忆")
            conn.execute("UPDATE memories SET status='superseded',updated=? WHERE id=?", (timestamp, rid))
        expires = time.time() + max(0, int(ttl_seconds)) if int(ttl_seconds) > 0 else None
        conn.execute("INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (mid, namespace, scope, scope_id, key, kind, content, encode(source or {}), max(0., min(1., float(importance))), expires, "active", encode(vector) if vector else None, timestamp, timestamp))
        conn.execute("INSERT INTO memory_fts VALUES(?,?)", (mid, " ".join(terms(content))))
        for entity in (entities or [])[:64]:
            name = str(entity.get("name") if isinstance(entity, dict) else entity).strip()[:160]
            if name:
                conn.execute("INSERT OR IGNORE INTO relations VALUES(?,?,?,?)", (mid, mid, "about", name))
        for rel in (relations or [])[:128]:
            triple = [str(rel.get(k) or "").strip()[:160] for k in ("subject", "predicate", "object")]
            if all(triple):
                conn.execute("INSERT OR IGNORE INTO relations VALUES(?,?,?,?)", (mid, *triple))
        return _memory(conn.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone())


def _memory(row) -> dict:
    data = dict(row)
    data["source"] = json.loads(data["source"])
    data.pop("embedding", None)
    return data


def list_memories(*, namespace="research", session_id="", project_id="", include_inactive=False, limit=100) -> list[dict]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM memories WHERE namespace=? AND (scope IN ('global','user') OR (scope='session' AND scope_id=?) OR (scope='project' AND scope_id=?)) AND (? OR (status='active' AND (expires IS NULL OR expires>?))) ORDER BY updated DESC LIMIT ?", (namespace, session_id, project_id, int(include_inactive), time.time(), max(1, min(int(limit), 500)))).fetchall()
    return [_memory(row) for row in rows]


def forget(memory_id: str) -> dict:
    with connection() as conn:
        cur = conn.execute("UPDATE memories SET status='forgotten',updated=? WHERE id=?", (now(), memory_id))
    if not cur.rowcount:
        raise FileNotFoundError(memory_id)
    return {"ok": True, "id": memory_id}


def recall(query: str, *, namespace="research", session_id="", project_id="", limit=None, max_chars=8000, query_embedding=None, graph=True) -> dict:
    from .agent_runtime import settings
    maximum = settings()["rag_top_k"]
    limit = max(1, min(int(limit) if limit is not None else maximum, maximum))
    tokens = terms(query)[:48]
    vector = _vector(query_embedding)
    max_chars = max(256, min(int(max_chars), 32000))
    candidates: dict[str, Any] = {}
    scores: dict[str, float] = {}
    where = "namespace=? AND status='active' AND (expires IS NULL OR expires>?) AND (scope IN ('global','user') OR (scope='session' AND scope_id=?) OR (scope='project' AND scope_id=?))"
    params = (namespace, time.time(), session_id, project_id)
    with connection() as conn:
        if tokens:
            expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in tokens)
            rows = conn.execute("SELECT m.* FROM memories m JOIN memory_fts f ON f.id=m.id WHERE memory_fts MATCH ? AND " + where + " ORDER BY bm25(memory_fts) LIMIT 80", (expression, *params)).fetchall()
            for rank, row in enumerate(rows):
                candidates[row["id"]] = row
                scores[row["id"]] = 1. / (60 + rank + 1)
        if vector:
            rows = conn.execute("SELECT * FROM memories WHERE " + where + " AND embedding IS NOT NULL LIMIT 10000", params).fetchall()
            norm = math.sqrt(sum(v * v for v in vector))
            ranked = []
            for row in rows:
                other = json.loads(row["embedding"])
                if len(other) == len(vector):
                    cosine = sum(a * b for a, b in zip(vector, other)) / (norm * math.sqrt(sum(v * v for v in other)))
                    if cosine > 0:
                        ranked.append((cosine, row))
            for rank, (_, row) in enumerate(sorted(ranked, key=lambda p: p[0], reverse=True)[:80]):
                candidates[row["id"]] = row
                scores[row["id"]] = scores.get(row["id"], 0.) + 1. / (60 + rank + 1)
        if graph and candidates:
            seeds = sorted(scores, key=scores.get, reverse=True)[:5]
            marks = ",".join("?" for _ in seeds)
            rows = conn.execute(f"SELECT DISTINCT m.* FROM memories m JOIN relations r ON r.memory_id=m.id WHERE {where} AND r.object IN (SELECT object FROM relations WHERE memory_id IN ({marks}) AND predicate='about') LIMIT 40", (*params, *seeds)).fetchall()
            for row in rows:
                if row["id"] not in candidates:
                    candidates[row["id"]] = row
                    scores[row["id"]] = .5 / 61
    ordered = sorted(candidates, key=lambda mid: scores[mid] * (1 + .15 * candidates[mid]["importance"]), reverse=True)
    hits, chunks, size, source_blocks = [], [], 0, []
    for mid in ordered[:max(1, min(int(limit), 30))]:
        item = _memory(candidates[mid])
        text = f"[MEM {mid}] ({item['scope']}/{item['kind']}) {item['content']}\n来源: {encode(item['source'])}"
        remaining = max_chars - size
        if remaining < 128:
            break
        text = text[:remaining]
        from . import agent_sources
        source_blocks.append(agent_sources.span(agent_sources.source(item, "memory", entity_type="memory", text=text), text, sum(len(c) + 2 for c in chunks)))
        chunks.append(text)
        size += len(text) + 2
        hits.append({**item, "rank": len(hits) + 1, "score": round(scores[mid], 8)})
    return {"query": query, "mode": "hybrid" if vector else "lexical_graph", "limit": limit, "count": len(hits), "results": hits, "context_pack": {"text": "\n\n".join(chunks), "source_blocks": source_blocks, "sources": [{"id": h["id"], "source": h["source"]} for h in hits], "chars": min(size, max_chars)}}


def graph_data(**filters) -> dict:
    items = list_memories(**filters)
    ids = [item["id"] for item in items]
    edges = []
    if ids:
        with connection() as conn:
            marks = ",".join("?" for _ in ids)
            edges = [dict(r) for r in conn.execute(f"SELECT * FROM relations WHERE memory_id IN ({marks})", ids)]
    return {"memories": items, "relations": edges}


def statistics() -> dict:
    with connection() as conn:
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("sessions", "messages", "runs", "events", "memories", "relations", "tool_calls")}
    return {"schema_version": SCHEMA_VERSION, "backend": "sqlite", "retrieval": "FTS5 + graph + optional supplied vectors", "counts": counts}


def backup(destination: Path) -> Path:
    """SQLite online backup includes committed WAL pages in one consistent file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with connection() as source:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    return destination
