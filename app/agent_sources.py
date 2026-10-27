"""Answer-scoped provenance. Internal spans never travel to a model provider.

Spans are produced when context is assembled, transformed with that context, and
captured at the transport boundary. Reading a panel never reads current content
to manufacture a historical snapshot.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
import threading
from contextlib import contextmanager
from . import agent_memory as brain

SCHEMA_VERSION = 1
MAX_RECORD_BYTES = 12 * 1024 * 1024
WIRE_KEYS = {"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content"}


def schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS source_runs(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_requests(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,session_id TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS source_requests_run ON source_requests(run_id);
        CREATE TABLE IF NOT EXISTS source_views(message_id TEXT PRIMARY KEY,session_id TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS source_views_session ON source_views(session_id);
    """)


def digest(value):
    return hashlib.sha256(brain.encode(value).encode()).hexdigest()


def wire(messages):
    return [{k: v for k, v in m.items() if k in WIRE_KEYS} for m in messages]


def public_message(message):
    value = copy.deepcopy(message)
    value.pop("evidence", None)
    value.pop("_context_sources", None)
    value.pop("context_text", None)
    for ref in value.get("refs", []):
        ref.pop("_source_block", None)
    return value


def source(item, channel, *, entity_type="doc", text="", location=None):
    if entity_type == "paper" and item.get("doc_id"):
        entity_type = "doc"
    identifier = str(item.get("doc_id") or item.get("id") or "")
    if entity_type == "page":
        identifier = str(item.get("paper_id") or identifier or item.get("view") or "当前页面")
    return {"entity_key": entity_type + ":" + identifier, "entity_id": identifier,
            "entity_type": entity_type, "title": str(item.get("title") or ("长期记忆 · " + str(item.get("content") or "")[:40] if entity_type == "memory" else "当前页面 / 选区"))[:240],
            "kind": "memory" if entity_type == "memory" else str(item.get("kind") or ("page" if entity_type == "page" else "literature" if entity_type == "paper" else "note")),
            "scope": item.get("scope") or "", "memory_kind": item.get("kind") if entity_type == "memory" else "",
            "projects": item.get("projects") or [], "tags": item.get("tags") or [], "status": item.get("status") or "",
            "version": str(item.get("version") or item.get("revision") or (item.get("updated") if entity_type == "memory" else "") or digest(text)),
            "updated": item.get("updated") or "", "paper_id": item.get("paper_id") or "",
            "location": location or {}, "channel": channel}


def span(meta, text, start=0, *, encoding="text", path=None):
    return {"source": copy.deepcopy(meta), "start": start, "end": start + len(text), "encoding": encoding,
            **({"path": path} if path is not None else {})}


def move(spans, offset, *, channel=None):
    result = copy.deepcopy(spans)
    for block in result:
        block["start"] += offset
        block["end"] += offset
        if channel:
            block["source"]["origin_channel"] = block["source"]["channel"]
            block["source"]["channel"] = channel
    return result


def slice_spans(spans, start, end):
    result = []
    for block in spans:
        a, b = max(start, block["start"]), min(end, block["end"])
        if a < b:
            result.append({**copy.deepcopy(block), "start": a - start, "end": b - start,
                           "partial": block.get("partial", False) or a != block["start"] or b != block["end"]})
    return result


def json_message(data, paths):
    """Serialize with offsets from structure, including repeated/escaped text."""
    parts, blocks, pos = [], [], 0
    indexed = {}
    for block in paths:
        indexed.setdefault(tuple(block["path"]), []).append(block)
    def emit(text):
        nonlocal pos
        parts.append(text)
        pos += len(text)
    def visit(value, path):
        if isinstance(value, dict):
            emit("{")
            for i, (key, child) in enumerate(value.items()):
                if i:
                    emit(",")
                emit(brain.encode(str(key)) + ":")
                visit(child, (*path, key))
            emit("}")
        elif isinstance(value, list):
            emit("[")
            for i, child in enumerate(value):
                if i:
                    emit(",")
                visit(child, (*path, i))
            emit("]")
        else:
            encoded = brain.encode(value)
            if path in indexed and isinstance(value, str) and value:
                for block in indexed[path]:
                    a, b = block.get("relative", [0, len(value)])
                    b = min(b, len(value))
                    if a >= b:
                        continue
                    start = pos + len(brain.encode(value[:a])) - 1
                    end = pos + len(brain.encode(value[:b])) - 1
                    blocks.append({**copy.deepcopy(block), "start": start, "end": end, "encoding": "json",
                                   "partial": block.get("partial", False) or b < block.get("relative", [0, len(value)])[1]})
            emit(encoded)
    visit(data, ())
    return {"role": "tool", "content": "".join(parts), "_sources": blocks}


def tool_message(name, args, result, call_id):
    paths = []
    coverage_error = ""
    def add(item, path, field, channel, *, entity_type="doc", location=None):
        text = str(item.get(field) or "")
        if not text:
            return
        meta = source(item, channel, entity_type=entity_type, text=text, location=location)
        meta["call_id"] = call_id
        paths.append({"path": [*path, field], "source": meta})
    if result.get("ok") is not False:
        if name == "kb_search":
            for i, hit in enumerate(result.get("items") or []):
                add({**hit, "version": (hit.get("source") or {}).get("version") or hit.get("version")}, ["items", i], "excerpt", "rag", location=hit.get("source"))
        elif name == "kb_read":
            add(result, [], "body", "read", location={"offset": args.get("offset", 0), "read_scope": result.get("read_scope")})
        elif name == "workspace_read":
            path = result.get("path")
            if path and isinstance(result.get("content"), str) and result.get("version"):
                offset = max(0, int(result.get("offset", args.get("offset")) or 0))
                add({**result, "id": path, "title": path, "kind": "file"}, [], "content", "read", entity_type="file",
                    location={"path": path, "offset": offset, "end_offset": offset + len(result["content"])})
            else:
                coverage_error = "文件读取结果缺少路径、正文或版本，无法精确记录来源：workspace_read"
        elif name == "pdf_read":
            paper_id = result.get("paper_id")
            pages = result.get("pages")
            if paper_id and result.get("version") and isinstance(pages, list):
                for i, page in enumerate(pages):
                    if not isinstance(page, dict) or not isinstance(page.get("text"), str) or not page.get("page"):
                        coverage_error = "PDF 读取结果缺少页码或正文，无法精确记录来源：pdf_read"
                        continue
                    add({**result, "id": paper_id, "text": page["text"], "kind": "literature"}, ["pages", i], "text", "read", entity_type="paper",
                        location={"page": page["page"], "offset": 0, "end_offset": len(page["text"])})
            else:
                coverage_error = "PDF 读取结果缺少文献标识、页内容或版本，无法精确记录来源：pdf_read"
        elif name == "memory_recall":
            for i, hit in enumerate(result.get("results") or []):
                add(hit, ["results", i], "content", "memory", entity_type="memory")
            # The context pack repeats these results, so record its actual bytes too.
            pack = result.get("context_pack") or {}
            for block in pack.get("source_blocks") or []:
                paths.append({"path": ["context_pack", "text"], "relative": [block["start"], block["end"]], "source": {**block["source"], "call_id": call_id}})
        elif name == "lit_context":
            paper = result.get("paper") or {}
            meta = source({**paper, "paper_id": paper.get("id"), "version": result.get("note_version")}, "read", entity_type="paper", text=result.get("note", ""), location={"offset": args.get("note_offset", 0)})
            paths.append({"path": ["note"], "source": {**meta, "call_id": call_id}})
        elif name == "evidence_read":
            for block in result.get("_evidence_sources", []):
                paths.append({"path": ["content"], "relative": [block["start"], block["end"]], "source": {**block["source"], "channel": "history", "call_id": call_id}, "partial": block.get("partial", False)})
    clean = copy.deepcopy(result)
    clean.pop("_evidence_sources", None)
    clean.pop("_source_incomplete", None)
    if isinstance(clean.get("context_pack"), dict):
        clean["context_pack"].pop("source_blocks", None)
    message = json_message(clean, paths)
    message["tool_call_id"] = call_id
    if name in {"web_search", "web_fetch", "web_read"} or name.startswith("mcp_"):
        message["_source_incomplete"] = "此工具尚无精确来源适配：" + name
    if coverage_error:
        message["_source_incomplete"] = coverage_error
    if result.get("_source_incomplete"):
        message["_source_incomplete"] = result["_source_incomplete"]
    return message


def compact_tool(message, limit=1500):
    """Keep valid JSON and recompute leaf offsets after structural truncation."""
    try:
        data = json.loads(message["content"])
    except (ValueError, TypeError):
        message["content"] = str(message["content"])[:limit]
        message["_sources"] = slice_spans(message.get("_sources", []), 0, limit)
        message["_source_incomplete"] = "旧工具结果无法结构化压缩"
        return
    def clip(value, size):
        if isinstance(value, str):
            return value[:size]
        if isinstance(value, list):
            return [clip(child, size) for child in value[:max(1, size // 150)]]
        if isinstance(value, dict):
            return {k: clip(v, size) for k, v in value.items()}
        return value
    size = 800
    while True:
        clipped = clip(data, size)
        rendered = json_message(clipped, message.get("_sources", []))
        if len(rendered["content"]) <= limit or size <= 16:
            break
        size //= 2
    for block in rendered["_sources"]:
        block["partial"] = True
    message.update(content=rendered["content"], _sources=rendered["_sources"])


def _put(conn, table, key, value, *extra):
    raw = brain.encode(value)
    if len(raw.encode()) > MAX_RECORD_BYTES:
        raise ValueError("来源记录超过单次 12 MB 上限")
    if table == "source_runs":
        conn.execute("INSERT OR REPLACE INTO source_runs VALUES(?,?)", (key, raw))
    elif table == "source_requests":
        conn.execute("INSERT OR REPLACE INTO source_requests VALUES(?,?,?,?)", (key, *extra, raw))


def _run(conn, run_id):
    row = conn.execute("SELECT payload FROM source_runs WHERE id=?", (run_id,)).fetchone()
    return json.loads(row[0]) if row else {"schema_version": SCHEMA_VERSION, "run_id": run_id, "revision": 0, "candidates": [], "errors": []}


def _update(run_id, change):
    if not run_id:
        return
    with brain._LOCK, brain.connection() as conn:
        data = _run(conn, run_id)
        change(conn, data)
        data["revision"] += 1
        _put(conn, "source_runs", run_id, data)
        requests = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM source_requests WHERE run_id=? ORDER BY rowid", (run_id,))]
        summary = build_view(data, requests)["source_summary"]
    brain.event(run_id, "sources_updated", {"run_id": run_id, "revision": data["revision"], "source_summary": summary})


def incomplete(run_id, reason):
    try:
        _update(run_id, lambda conn, data: data["errors"].append(str(reason)[:300]) if str(reason)[:300] not in data["errors"] else None)
    except Exception:
        pass  # Reporting a provenance failure must never repeat a tool action.


def retrieved(run_id, message):
    try:
        blocks = capture([message])
        def change(conn, data):
            known = {b["snapshot_id"] for b in data["candidates"]}
            data["candidates"].extend(b for b in blocks if b["snapshot_id"] not in known)
            if message.get("_source_incomplete"):
                data["errors"].append(message["_source_incomplete"])
        _update(run_id, change)
    except Exception as exc:
        incomplete(run_id, exc)


def capture(messages):
    blocks = []
    for index, message in enumerate(messages):
        content = message.get("content") or ""
        if isinstance(content, list):
            content = next((p.get("text", "") for p in content if p.get("type") == "text"), "")
        for block in message.get("_sources", []):
            start, end = block["start"], block["end"]
            if not 0 <= start < end <= len(content):
                raise ValueError("来源片段位置失效，未记录为已提供")
            text = content[start:end]
            decoded = text
            if block.get("encoding") == "json":
                try:
                    decoded = json.loads('"' + text + '"')
                except ValueError:
                    # An extractive summary can contain half an escaped leaf.
                    # Preserve exact bytes and label its representation explicitly.
                    decoded = text
            payload = {**block["source"], "text": decoded, "wire_text": text,
                       "encoding": block.get("encoding", "text"), "partial": block.get("partial", False),
                       "representation": block.get("representation") or ("partial" if block.get("partial") else "full")}
            payload["snapshot_id"] = "src-" + digest({k: payload[k] for k in ("entity_key", "version", "location", "text", "wire_text", "encoding", "partial")})[:32]
            blocks.append({**payload, "message_index": index, "start": start, "end": end})
    return blocks


class Recorder:
    """One instance per model step; each physical HTTP attempt gets its own ID."""
    def __init__(self, run_id, session_id, messages, protocol, step=0):
        self.run_id, self.session_id = run_id, session_id
        self.protocol, self.blocks = protocol, capture(messages)
        self.errors = [m["_source_incomplete"] for m in messages if m.get("_source_incomplete")]
        self.current = ""
        self.step = step
        self.lock = threading.RLock()
        self.closed = False
        self.statuses = {}

    def start(self, payload):
        with self.lock:
            if self.closed:
                from .agent_runtime import Suspended
                raise Suspended("cancelled")
            return self._start(payload)

    def _start(self, payload):
        request_id = "req-" + uuid.uuid4().hex
        self.current = request_id
        self.statuses[request_id] = "prepared"
        value = {"id": request_id, "created": brain.now(), "status": "prepared", "protocol": self.protocol,
                 "step": self.step,
                 "stream": bool(payload.get("stream")), "blocks": self.blocks,
                 "messages_digest": digest(payload["messages"]), "errors": self.errors}
        try:
            def change(conn, data):
                prior = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM source_requests WHERE run_id=?", (self.run_id,))]
                value["attempt"] = 1 + sum(r.get("step") == self.step for r in prior)
                _put(conn, "source_requests", request_id, value, self.run_id, self.session_id)
            _update(self.run_id, change)
        except Exception as exc:
            incomplete(self.run_id, exc)
        return request_id

    def finish(self, request_id, status, error=""):
        with self.lock:
            if not self.closed:
                self._finish(request_id, status, error)

    def _finish(self, request_id, status, error=""):
        self.statuses[request_id] = status
        try:
            def change(conn, data):
                row = conn.execute("SELECT payload FROM source_requests WHERE id=?", (request_id,)).fetchone()
                if row:
                    value = json.loads(row[0])
                    value.update(status=status, error=str(error)[:300])
                    value["initiated" if status == "requested" else "finished"] = brain.now()
                    _put(conn, "source_requests", request_id, value, self.run_id, self.session_id)
            _update(self.run_id, change)
        except Exception as exc:
            incomplete(self.run_id, exc)

    def close(self):
        # The run worker seals recording before saving a cancelled answer. A
        # provider thread returning later must not write into a resumed run (or
        # a workspace that has already been closed).
        with self.lock:
            if self.closed:
                return
            self.closed = True
            for request_id, status in list(self.statuses.items()):
                if status in ("prepared", "requested"):
                    self._finish(request_id, "unknown", "请求等待已停止，无法确认供应商是否完成处理")


@contextmanager
def attempt(recorder, payload):
    """Prepared is persisted before I/O; initiated is recorded after write returns.

    A network/cancellation error leaves delivery unknown. HTTP errors are known
    responses and get their own failed attempt, including stream/tool fallback.
    """
    request_id = recorder.start(payload) if recorder else ""
    def sent():
        if recorder:
            recorder.finish(request_id, "requested")
    try:
        yield sent
    except BaseException as exc:
        if recorder:
            status = "failed" if re.search(r"LLM API HTTP \d{3}", str(exc)) else "unknown"
            recorder.finish(request_id, status, str(exc))
        raise
    else:
        if recorder:
            recorder.finish(request_id, "responded")


def citations(text):
    # Fenced/inline code and escaped examples do not establish citations.
    text = str(text or "")
    text = re.sub(r"<(pre|code|script|style)\b[^>]*>[\s\S]*?</\1\s*>", "", text, flags=re.I)
    text = re.sub(r"<!--([\s\S]*?)(?:-->|$)", "", text)
    lines, fence = [], ""
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
            continue
        if not fence and not re.match(r"^(?: {4}|\t)", line):
            lines.append(line)
    text = re.sub(r"(`+)([\s\S]*?)\1", "", "\n".join(lines))
    wiki = [m.group(1).split("|", 1)[0].strip().split("#", 1)[0] for m in re.finditer(r"(?<!\\)\[\[([^\]\n]+)\]\]", text)]
    for label, target in re.findall(r"(?<!!)\[([^\]\n]+)\]\(([^)\s]+)\)", text):
        from urllib.parse import unquote
        if target.startswith(("/api/docs/", "/docs/")):
            wiki.append(unquote(target.rsplit("/", 1)[-1]).split("#", 1)[0])
    return set(wiki)


def build_view(data, requests, text="", *, legacy=False):
    groups = {}
    for block in data.get("candidates", []):
        groups.setdefault(block["entity_key"], {**{k: v for k, v in block.items() if k not in ("text", "wire_text", "start", "end", "message_index")}, "snapshots": {}, "provided": False, "cited": False, "channels": [], "request_ids": []})
        groups[block["entity_key"]]["snapshots"][block["snapshot_id"]] = {**block, "provided": False, "request_ids": []}
    for request in requests:
        for block in request.get("blocks", []):
            key = block["entity_key"]
            row = groups.setdefault(key, {**{k: v for k, v in block.items() if k not in ("text", "wire_text", "start", "end", "message_index")}, "snapshots": {}, "provided": False, "cited": False, "channels": [], "request_ids": []})
            sent = request["status"] in ("requested", "responded", "failed")
            row["provided"] |= sent
            if request["id"] not in row["request_ids"]:
                row["request_ids"].append(request["id"])
            if block["channel"] not in row["channels"]:
                row["channels"].append(block["channel"])
            snap = row["snapshots"].setdefault(block["snapshot_id"], {**block, "provided": False, "request_ids": []})
            for field in ("title", "kind", "projects", "tags", "status", "paper_id"):
                if block.get(field):
                    row[field] = block[field]
            if block["channel"] not in snap.setdefault("channels", []):
                snap["channels"].append(block["channel"])
            if block.get("call_id") and block["call_id"] not in snap.setdefault("call_ids", []):
                snap["call_ids"].append(block["call_id"])
            snap["provided"] |= sent
            if request["id"] not in snap["request_ids"]:
                snap["request_ids"].append(request["id"])
    targets = citations(text)
    ambiguous = []
    for target in targets:
        matches = [r for r in groups.values() if r["provided"] and target in (r["entity_id"], r["title"])]
        if len(matches) == 1:
            matches[0]["cited"] = True
        else:
            ambiguous.append(target)
    rows = list(groups.values())
    for i, row in enumerate(rows):
        row["source_id"] = "source-" + digest(row["entity_key"])[:24]
        row["number"] = i + 1
        row["snapshots"] = list(row["snapshots"].values())
        row["request_states"] = []
        seen = False
        for number, request in enumerate(requests, 1):
            blocks = [b for b in request.get("blocks", []) if b["entity_key"] == row["entity_key"]]
            seen |= bool(blocks)
            if seen:
                row["request_states"].append({"request_id": request["id"], "number": number, "status": request["status"],
                                              "representations": sorted({b.get("representation", "partial" if b.get("partial") else "full") for b in blocks}) or ["omitted"]})
    errors = list(dict.fromkeys(data.get("errors", []) + [e for r in requests for e in r.get("errors", [])]))
    if any(r["status"] in ("prepared", "unknown") for r in requests):
        errors.append("存在尚未确认发送或完成状态的请求；未将这些请求的片段标为已确认提供。")
    kinds = {}
    for row in rows:
        if row["provided"]:
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    summary = {"schema_version": SCHEMA_VERSION, "revision": data.get("revision", 0),
               "recording_status": "incomplete" if legacy or errors else "complete",
               "provided_source_count": sum(r["provided"] for r in rows), "cited_source_count": sum(r["cited"] for r in rows), "counts_by_kind": kinds}
    return {"schema_version": SCHEMA_VERSION, "run_id": data.get("run_id", ""), "source_summary": summary,
            "sources": rows, "requests": [{k: v for k, v in r.items() if k != "blocks"} for r in requests],
            "unresolved_citations": ambiguous, "warnings": errors + (["旧记录缺少实际发送范围，以下仅为留存的历史资料，不能确认已提供。"] if legacy else [])}


def run_view(run_id):
    run = brain.get_run(run_id)
    brain.get_session(run["session_id"], migrate=False)  # tombstones deny access
    with brain.connection() as conn:
        data = _run(conn, run_id)
        requests = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM source_requests WHERE run_id=? ORDER BY rowid", (run_id,))]
    view = build_view(data, requests, run.get("state", {}).get("partial_answer", ""))
    view["session_id"] = run["session_id"]
    return view


def freeze(session_id, message, answer_text=None):
    """Persist before exporting message/event. Resuming creates a new frozen view."""
    run_id = message.get("run_id")
    if not run_id:
        message["source_summary"] = {"schema_version": 1, "revision": 0, "recording_status": "incomplete"}
        return
    try:
        brain.get_session(session_id, migrate=False)
        # Resolve against all answer parts, using the same provided snapshots.
        with brain.connection() as conn:
            data = _run(conn, run_id)
            requests = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM source_requests WHERE run_id=? ORDER BY rowid", (run_id,))]
            answer = str(message.get("content") or "") if answer_text is None else str(answer_text)
            view = build_view(data, requests, answer)
            final_request_id = requests[-1]["id"] if requests and answer.strip() and message.get("run_status") != "waiting_approval" else ""
            view.update(session_id=session_id, message_id=message["id"], frozen=True, final_request_id=final_request_id)
            raw = brain.encode(view)
            if len(raw.encode()) > MAX_RECORD_BYTES:
                raise ValueError("回答来源快照超过 12 MB 上限")
            conn.execute("INSERT OR IGNORE INTO source_views VALUES(?,?,?)", (message["id"], session_id, raw))
        message["source_summary"] = view["source_summary"]
    except Exception as exc:
        incomplete(run_id, exc)
        message["source_summary"] = {"schema_version": 1, "revision": 0, "recording_status": "incomplete"}


def message_view(session_id, message_id, source_id="", snapshot_id=""):
    session = brain.get_session(session_id)
    message = next((m for m in session["messages"] if m.get("id") == message_id and m.get("role") == "assistant"), None)
    if not message:
        raise FileNotFoundError("回答不存在")
    with brain.connection() as conn:
        row = conn.execute("SELECT payload FROM source_views WHERE session_id=? AND message_id=?", (session_id, message_id)).fetchone()
    if row:
        view = json.loads(row[0])
    else:
        # Read only: no writes and no current knowledge lookups for legacy data.
        candidates = []
        for item in message.get("evidence", []):
            candidates.extend(capture([item]))
        if not candidates:
            calls = {}
            for item in message.get("evidence", []):
                for call in item.get("tool_calls", []):
                    calls[call.get("id")] = call.get("function") or {}
                if item.get("role") != "tool":
                    continue
                try:
                    result = json.loads(item.get("content") or "{}")
                    fn = calls.get(item.get("tool_call_id"), {})
                    name = fn.get("name") or ("kb_search" if result.get("mode") in ("keyword", "hybrid", "semantic") else "kb_read" if result.get("id") and "body" in result else "")
                    args = json.loads(fn.get("arguments") or "{}")
                    candidates.extend(capture([tool_message(name, args, result, item.get("tool_call_id", ""))]))
                except (ValueError, TypeError, AttributeError):
                    continue
            user = next((m for m in reversed(session["messages"][:session["messages"].index(message)]) if m.get("role") == "user"), {})
            if user.get("context_text"):
                meta = source({"id": user.get("id"), "title": "历史引用资料（条目归属未完整记录）", "kind": "page"}, "history", entity_type="legacy", text=user["context_text"])
                candidates.extend(capture([{"content": user["context_text"], "_sources": [span(meta, user["context_text"])]}]))
        view = build_view({"candidates": candidates}, [], legacy=True)
        view.update(session_id=session_id, message_id=message_id, frozen=True)
    if source_id:
        source_row = next((s for s in view["sources"] if s["source_id"] == source_id), None)
        if not source_row:
            raise FileNotFoundError("来源不属于此回答")
        if snapshot_id:
            block = next((s for s in source_row["snapshots"] if s["snapshot_id"] == snapshot_id), None)
            if not block:
                raise FileNotFoundError("片段不属于此来源")
            return block
        return source_row
    result = copy.deepcopy(view)
    for source_row in result["sources"]:
        source_row["snapshot_count"] = len(source_row.pop("snapshots"))
    return result


def archive(conn, session_id):
    return {"schema_version": 1, "views": [json.loads(r[0]) for r in conn.execute("SELECT payload FROM source_views WHERE session_id=?", (session_id,))]}


def restore(conn, session_id, bundle):
    if not isinstance(bundle, dict) or bundle.get("schema_version") != 1:
        return
    for view in bundle.get("views", []):
        mid = view.get("message_id")
        if view.get("session_id") != session_id or not conn.execute("SELECT 1 FROM messages WHERE id=? AND session_id=?", (mid, session_id)).fetchone():
            continue
        raw = brain.encode(view)
        if len(raw.encode()) <= MAX_RECORD_BYTES:
            conn.execute("INSERT OR IGNORE INTO source_views VALUES(?,?,?)", (mid, session_id, raw))
