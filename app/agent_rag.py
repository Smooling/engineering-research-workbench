"""Configurable embeddings and a disposable, versioned document vector index.

Markdown remains authoritative. Credentials stay outside the synced workspace.
Updates are manual unless explicitly enabled; keyword search never calls a model.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import agent_memory as brain, config, indexer

DEFAULTS = {"mode": "keyword", "base_url": "", "model": "", "dimensions": 0,
            "chunk_chars": 1600, "overlap_chars": 200, "batch_size": 16, "include_pdf": False,
            "realtime_updates": False, "scheduled_updates": False, "update_interval_minutes": 60,
            "update_debounce_seconds": 15}
_LOCK = threading.RLock()
_JOBS: dict[str, dict] = {}
_QUERY_CACHE: dict[tuple, tuple] = {}


def _config_path():
    return config.CONFIG_DIR / "agent-rag.json"


def settings(private=False):
    with _LOCK:
        try:
            saved = json.loads(_config_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        result = {**DEFAULTS, **{k: saved[k] for k in DEFAULTS if k in saved}}
        result["api_key" if private else "has_api_key"] = saved.get("api_key", "") if private else bool(saved.get("api_key"))
        return result


def save_settings(data):
    with _LOCK:
        value = settings(private=True)
        for key in DEFAULTS:
            if key in data:
                value[key] = data[key]
        value["mode"] = str(value["mode"])
        if value["mode"] not in ("keyword", "semantic", "hybrid"):
            raise ValueError("检索模式须为 keyword / semantic / hybrid")
        value["base_url"] = str(value["base_url"]).strip().rstrip("/")
        value["model"] = str(value["model"]).strip()
        if value["base_url"]:
            url = urlsplit(value["base_url"])
            if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("Base URL 须为不含凭据、查询串的 HTTP(S) 地址")
        if len(value["model"]) > 200:
            raise ValueError("模型名称过长")
        for key, low, high in (("dimensions", 0, 8192), ("chunk_chars", 256, 8000), ("overlap_chars", 0, 2000), ("batch_size", 1, 64), ("update_interval_minutes", 5, 10080), ("update_debounce_seconds", 5, 300)):
            value[key] = int(value[key])
            if not low <= value[key] <= high:
                raise ValueError(f"{key} 超出范围 {low}–{high}")
        if value["overlap_chars"] >= value["chunk_chars"]:
            raise ValueError("分块重叠须小于分块长度")
        value["include_pdf"] = value["include_pdf"] is True
        for key in ("realtime_updates", "scheduled_updates"):
            value[key] = value[key] is True
        if "api_key" in data and str(data["api_key"]).strip():
            value["api_key"] = str(data["api_key"]).strip()
        if data.get("clear_api_key") is True:
            value["api_key"] = ""
        brain.atomic_json(_config_path(), value)
        _QUERY_CACHE.clear()
        return settings()


def _fingerprint(opts):
    keys = ("base_url", "model", "dimensions", "chunk_chars", "overlap_chars", "include_pdf")
    return hashlib.sha256(brain.encode({k: opts[k] for k in keys}).encode()).hexdigest()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward an Authorization header to another origin.


def _embed(texts, opts):
    if not opts["base_url"] or not opts["model"]:
        raise ValueError("请先配置并保存 Embedding Base URL 和模型名称")
    endpoint = opts["base_url"]
    if not endpoint.endswith("/embeddings"):
        endpoint += "/embeddings"
    payload = {"model": opts["model"], "input": texts, "encoding_format": "float"}
    if opts["dimensions"]:
        payload["dimensions"] = opts["dimensions"]
    headers = {"Content-Type": "application/json"}
    if opts.get("api_key"):
        headers["Authorization"] = "Bearer " + opts["api_key"]
    request = Request(endpoint, json.dumps(payload).encode(), headers, method="POST")
    try:
        with build_opener(_NoRedirect).open(request, timeout=60) as response:
            raw = response.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise ValueError("Embedding 响应过大")
        rows = json.loads(raw)["data"]
    except HTTPError as exc:
        raise ValueError(f"Embedding 接口返回 HTTP {exc.code}；请检查地址、模型和密钥") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("无法连接 Embedding 接口或请求超时") from None
    except (ValueError, KeyError, TypeError):
        raise ValueError("Embedding 响应须包含 data 数组及 embedding 向量") from None
    if not isinstance(rows, list) or len(rows) != len(texts):
        raise ValueError("Embedding 返回数量与输入分块数量不一致")
    ordered = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("index")) is not int or row["index"] in ordered:
            raise ValueError("Embedding 返回 index 缺失或重复")
        vector = row.get("embedding")
        if not isinstance(vector, list) or not 1 <= len(vector) <= 8192 or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
            raise ValueError("Embedding 返回的向量无效")
        norm = math.sqrt(sum(v * v for v in vector))
        if not math.isfinite(norm) or norm <= 0:
            raise ValueError("Embedding 返回的向量须为有限非零向量")
        ordered[row["index"]] = [v / norm for v in vector]
    if set(ordered) != set(range(len(texts))):
        raise ValueError("Embedding 返回 index 与输入不对应")
    result = [ordered[i] for i in range(len(texts))]
    if len({len(v) for v in result}) != 1 or (opts["dimensions"] and len(result[0]) != opts["dimensions"]):
        raise ValueError("Embedding 向量维数与配置不一致")
    return result


def test_connection():
    opts = settings(private=True)
    vector = _embed(["Embedding connection test"], opts)[0]
    return {"ok": True, "dimensions": len(vector), "model": opts["model"]}


@contextmanager
def _connection(root=None):
    path = (root or brain.root()) / "rag.sqlite"
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS chunks(generation TEXT,id TEXT,doc_id TEXT,kind TEXT,source TEXT,text TEXT,embedding TEXT,PRIMARY KEY(generation,id));
          CREATE INDEX IF NOT EXISTS chunks_generation ON chunks(generation,kind);
        """)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _manifest(conn):
    row = conn.execute("SELECT value FROM meta WHERE key='active'").fetchone()
    return json.loads(row[0]) if row else {}


def status():
    with _connection() as conn:
        manifest = _manifest(conn)
    with _LOCK:
        job = dict(_JOBS.get(str(brain.root()), {}))
    job.pop("cancel", None)
    from . import agent_rag_updates
    return {"settings": settings(), "index": {**manifest, "ready": bool(manifest.get("chunks")) and manifest.get("fingerprint") == _fingerprint(settings()),
            "stale": bool(manifest) and manifest.get("fingerprint") != _fingerprint(settings())}, "job": job, "updates": agent_rag_updates.status()}


def _version(doc):
    return hashlib.sha256(brain.encode({k: doc.get(k) for k in ("id", "title", "kind", "projects", "tags", "body")}).encode()).hexdigest()


def _split(text, size, overlap):
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary > start:
                end = boundary + 1
        if text[start:end].strip():
            yield start, end, text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def _sources(opts):
    # Full Markdown bodies, never just the list endpoint's short excerpts.
    for meta in indexer.document_metadata():
        try:
            doc = indexer.get_doc(meta["id"])
        except FileNotFoundError:
            continue
        yield {"doc_id": doc["id"], "title": doc.get("title", ""), "kind": doc.get("kind", ""), "path": doc.get("path", ""),
               "version": _version(doc), "type": "markdown", "project": ", ".join(doc.get("projects") or [])}, str(doc.get("body") or "")
    if opts["include_pdf"]:
        from . import literature
        from pypdf import PdfReader
        # The registry API supports pagination; don't silently index only page 1.
        page = 1
        while True:
            batch = literature.list_items(page=page, page_size=200)
            items = batch.get("items", [])
            for item in items:
                try:
                    path = literature.pdf_path(item["id"])
                except (FileNotFoundError, ValueError):
                    continue
                if not path.is_file():
                    continue
                stamp = f"{path.stat().st_size}:{path.stat().st_mtime_ns}"
                reader = PdfReader(path)
                for number, pdf_page in enumerate(reader.pages, 1):
                    yield {"doc_id": item.get("doc_id") or item["id"], "paper_id": item["id"], "title": item.get("title", ""), "kind": "literature", "path": path.name,
                           "type": "pdf", "page": number, "version": stamp}, pdf_page.extract_text() or ""
            if not items or page * 200 >= batch.get("total", len(items)):
                break
            page += 1


def build_index(background=True, reason="manual"):
    opts = settings(private=True)
    if not opts["base_url"] or not opts["model"]:
        raise ValueError("请先保存 Embedding 接口配置")
    root = brain.root()
    key = str(root)
    with _LOCK:
        if _JOBS.get(key, {}).get("state") in ("running", "cancelling"):
            raise ValueError("索引构建正在执行")
        job = {"state": "running", "reason": reason, "started_at": time.time(), "sources": 0, "chunks": 0, "embedded": 0, "reused": 0, "empty_sources": 0, "error": "", "cancel": threading.Event()}
        _JOBS[key] = job
    if background:
        threading.Thread(target=_build, args=(opts, root, job), name="rag-index", daemon=True).start()
    else:
        _build(opts, root, job)
    return status()


def cancel_build():
    with _LOCK:
        job = _JOBS.get(str(brain.root()))
        if job and job["state"] == "running":
            job["state"] = "cancelling"
            job["cancel"].set()
    return status()


def clear_index():
    """Remove derived vectors transactionally; authoritative documents survive.

    Disable automatic rebuilds, so a cleared index stays cleared until requested.
    SQLite's schema remains as an empty container; VACUUM reclaims vector pages.
    """
    key = str(brain.root())
    with _LOCK:
        if _JOBS.get(key, {}).get("state") in ("running", "cancelling", "clearing"):
            raise ValueError("请先取消并等待当前索引任务结束，再清除向量数据库")
        _JOBS[key] = {"state": "clearing"}
        try:
            save_settings({"realtime_updates": False, "scheduled_updates": False})
            with _connection() as conn:
                conn.execute("DELETE FROM chunks")
                conn.execute("DELETE FROM meta")
                conn.commit()
                conn.execute("VACUUM")
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            _QUERY_CACHE.clear()
            _JOBS[key] = {"state": "cleared", "sources": 0, "chunks": 0, "embedded": 0, "reused": 0}
        except BaseException:
            _JOBS[key] = {"state": "failed", "error": "清除索引未完成，请稍后重试"}
            raise
    from . import agent_rag_updates
    agent_rag_updates.reset()
    return status()


def _build(opts, root, job):
    generation = uuid.uuid4().hex
    def check():
        if brain.root() != root or job["cancel"].is_set():
            raise InterruptedError("已取消索引构建")
    try:
        # Pick up edits/imports made outside the application before enumerating.
        indexer.sync(immediate=True)
        from .agent_rag_updates import source_stamp
        observed = source_stamp(opts)
        with _connection(root) as conn:
            old = _manifest(conn)
            conn.execute("DELETE FROM chunks WHERE generation<>?", (old.get("generation", ""),))
            conn.commit()  # Discard staging rows left by a previous process exit.
            # Reuse unchanged chunks only with the same model and chunk configuration.
            reusable = {}
            if old.get("fingerprint") == _fingerprint(opts):
                reusable = {r["id"]: r["embedding"] for r in conn.execute("SELECT id,embedding FROM chunks WHERE generation=?", (old["generation"],))}
            pending = []
            dimensions = old.get("dimensions", 0) if reusable else 0
            def flush():
                nonlocal dimensions
                if not pending:
                    return
                check()
                vectors = _embed([r[5] for r in pending], opts)
                check()
                if dimensions and dimensions != len(vectors[0]):
                    raise ValueError("模型返回的维数发生变化，请改用新模型名称后重建索引")
                dimensions = len(vectors[0])
                conn.executemany("INSERT INTO chunks VALUES(?,?,?,?,?,?,?)", [(*r, brain.encode(v)) for r, v in zip(pending, vectors)])
                job["embedded"] += len(pending)
                pending.clear()
                conn.commit()
            for source, text in _sources(opts):
                check()
                job["sources"] += 1
                if not text.strip():
                    job["empty_sources"] += 1
                for start, end, body in _split(text, opts["chunk_chars"], opts["overlap_chars"]):
                    check()
                    if job["chunks"] >= 100000:
                        raise ValueError("索引超过 100000 个分块，请缩减资料或调大分块长度")
                    citation = {**source, "offset": start, "end_offset": end}
                    embedding_text = source["title"] + "\n" + body
                    identity = {k: citation.get(k) for k in ("doc_id", "type", "paper_id", "page", "offset", "end_offset")}
                    chunk_id = hashlib.sha256(brain.encode(identity).encode() + embedding_text.encode()).hexdigest()
                    row = (generation, chunk_id, source["doc_id"], source["kind"], brain.encode(citation), embedding_text)
                    if chunk_id in reusable:
                        conn.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?,?)", (*row, reusable[chunk_id]))
                        job["reused"] += 1
                    else:
                        pending.append(row)
                    job["chunks"] += 1
                    if len(pending) >= opts["batch_size"]:
                        flush()
            flush()
            check()
            manifest = {"generation": generation, "fingerprint": _fingerprint(opts), "model": opts["model"], "dimensions": dimensions,
                        "chunks": job["chunks"], "sources": job["sources"], "built_at": brain.now(), "built_epoch": time.time(), "source_stamp": observed}
            conn.execute("INSERT OR REPLACE INTO meta VALUES('active',?)", (brain.encode(manifest),))
            conn.execute("DELETE FROM chunks WHERE generation<>?", (generation,))
        job["state"] = "completed"
    except Exception as exc:
        job["state"] = "cancelled" if isinstance(exc, InterruptedError) else "failed"
        # Never copy provider bodies, keys, or user text into status/error logs.
        job["error"] = str(exc).replace(opts.get("api_key") or "\0", "[redacted]")[:500]
        with _connection(root) as conn:
            conn.execute("DELETE FROM chunks WHERE generation=?", (generation,))


def _keyword(query, kind, limit):
    rows = indexer.retrieve_docs(query, kind=kind or None, limit=limit)["items"]
    return [{"id": r["id"], "title": r.get("title", ""), "kind": r.get("kind", ""), "project": ", ".join(r.get("projects") or []),
             "excerpt": r.get("excerpt", ""), "source": {"doc_id": r["id"], "path": r.get("path", ""), "type": "markdown"}, "retrieval": "keyword", "evidence": r.get("evidence") or {}} for r in rows]


def search(query, kind=None, limit=None):
    from .agent_runtime import settings as runtime_settings
    if not runtime_settings()["rag_enabled"]:
        raise ValueError("RAG 已关闭")
    query = str(query).strip()
    if not query or len(query) > 8000:
        raise ValueError("检索问题须为 1–8000 字符")
    maximum = runtime_settings()["rag_top_k"]
    limit = max(1, min(int(limit) if limit is not None else maximum, maximum))
    opts = settings(private=True)
    mode = opts["mode"]
    keywords = _keyword(query, kind, limit) if mode != "semantic" else []
    if mode == "keyword":
        return {"mode": mode, "count": len(keywords), "limit": limit, "items": keywords}
    try:
        with _connection() as conn:
            conn.execute("BEGIN")
            manifest = _manifest(conn)
            if not manifest or manifest["fingerprint"] != _fingerprint(opts) or not manifest.get("chunks"):
                raise ValueError("语义索引尚未建立或配置已改变，请在 RAG 设置中构建索引")
            rows = conn.execute("SELECT * FROM chunks WHERE generation=?" + (" AND kind=?" if kind else ""), (manifest["generation"], kind) if kind else (manifest["generation"],)).fetchall()
        cache_key = (_fingerprint(opts), query)
        with _LOCK:
            cached = _QUERY_CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] < 300:
            vector = cached[1]
        else:
            vector = _embed([query], opts)[0]
            with _LOCK:
                if len(_QUERY_CACHE) >= 128:
                    _QUERY_CACHE.pop(next(iter(_QUERY_CACHE)))
                _QUERY_CACHE[cache_key] = (time.monotonic(), vector)
        if len(vector) != manifest["dimensions"]:
            raise ValueError("查询与索引的向量维数不同，请重建索引")
        scored = []
        for row in rows:
            other = json.loads(row["embedding"])
            score = sum(a * b for a, b in zip(vector, other))
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        hits, checked, seen, scopes = [], {}, set(), {}
        for score, row in scored:
            source = json.loads(row["source"])
            doc_id = row["doc_id"]
            if doc_id in seen:
                continue
            if source["type"] == "markdown":
                if doc_id not in checked:
                    try:
                        doc = indexer.get_doc(doc_id)
                        checked[doc_id] = _version(doc)
                        from .evidence import describe
                        scopes[doc_id] = describe(doc)
                    except FileNotFoundError:
                        checked[doc_id] = None
                if checked[doc_id] != source["version"]:
                    continue  # Deleted/modified sources must not be cited as current evidence.
            else:
                from . import literature
                try:
                    stat = literature.pdf_path(source["paper_id"]).stat()
                    if source["version"] != f"{stat.st_size}:{stat.st_mtime_ns}":
                        continue
                except (FileNotFoundError, ValueError):
                    continue
            seen.add(doc_id)
            hits.append({"id": doc_id, "title": source["title"], "kind": row["kind"], "excerpt": row["text"], "project": source.get("project", ""),
                         "score": round(score, 6), "source": source, "retrieval": "semantic", "evidence": scopes.get(doc_id) or {"level": "pdf", "label": "有 PDF 全文", "has_pdf": source.get("type") == "pdf", "declared": False}})
            if len(hits) >= limit:
                break
        if mode == "semantic":
            return {"mode": mode, "count": len(hits), "limit": limit, "items": hits}
        # RRF on document IDs: matching by both routes beats matching only one.
        merged = {}
        for group in (keywords, hits):
            for rank, item in enumerate(group, 1):
                key = item["id"]
                prior = merged.get(key, {})
                merged[key] = {**prior, **item, "rrf": prior.get("rrf", 0) + 1 / (60 + rank)}
        results = sorted(merged.values(), key=lambda item: item["rrf"], reverse=True)[:limit]
        return {"mode": mode, "count": len(results), "limit": limit, "items": results}
    except ValueError as exc:
        if mode == "semantic":
            raise
        return {"mode": "keyword", "requested_mode": mode, "warning": str(exc), "count": len(keywords), "limit": limit, "items": keywords}
