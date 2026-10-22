from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import socket
import sys
import threading
import time
import webbrowser
import tempfile
from functools import wraps
from contextlib import nullcontext
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import urlopen

from app import config
from app import external_access
from app import versions
from app import store
from app import todos
from app import workspace
from app import agent
from app import agent_tools  # v260930 · M1 Agent 工具调用层
from app import agent_memory, agent_runtime, agent_skills, agent_mcp, agent_rag
from app import projects
from app import milestones
from app import indexer
from app.paths import ASSET_ROOT, DATA_ROOT
from app import literature
from app import scratch  # v261008 · 操作临时空间 .scratch
from app import sync_service
from app.sync_engine import mutation_lock, CHUNK

# v260923 · 打包 exe 后：只读资源（web/、VERSION）在 PyInstaller 解压目录；可写数据在 exe 同级
ROOT = DATA_ROOT
WEB = ASSET_ROOT / "web"


def serialized_write(fn):
    @wraps(fn)
    def call(self, *args, **kwargs):
        path = args[0] if args else urlparse(self.path).path
        # Agent/lookup requests can wait on external APIs; never lock during those waits.
        locked = not path.startswith(("/api/sync/", "/api/agent/", "/api/literature/lookup"))
        with mutation_lock if locked else nullcontext():
            return fn(self, *args, **kwargs)
    return call


def json_bytes(data) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _batch_ids(payload) -> list[str]:
    ids = payload.get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > 1000:
        raise ValueError("请选择 1–1000 条记录")
    if any(not isinstance(key, str) or not key.strip() for key in ids):
        raise ValueError("记录编号无效")
    return list(dict.fromkeys(ids))


def _delete_documents(ids: list[str]) -> dict:
    return indexer.delete_docs(ids)


def _q_int(q, key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int((q.get(key) or [str(default)])[0])
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _project_registry_needs_migration() -> bool:
    root = workspace.ensure_workspace(run_migration=False)
    registry = root / "System" / "projects.json"
    schema = root / "System" / "schema.json"
    if not registry.exists() or not schema.exists():
        return True
    try:
        data = json.loads(schema.read_text(encoding="utf-8"))
        return int(data.get("workspace_schema_version") or 0) < indexer.WORKSPACE_SCHEMA_VERSION
    except Exception:
        return True


class WorkbenchHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32  # Asset loading and bootstrap reads arrive together.
    # v260923v · Windows 上 allow_reuse_address=1(SO_REUSEADDR) 允许第二个进程静默重复绑定同一端口，
    # 曾导致旧实例/开发服务与新实例同端口打架、前端 bundle 版本错乱。Windows 改为独占绑定；
    # Unix 上该标志仅用于绕过 TIME_WAIT，保留 True 方便开发时快速重启。
    allow_reuse_address = (sys.platform != "win32")

    def server_close(self):
        from app import agent_rag_updates
        agent_rag_updates.stop()
        super().server_close()
        sync_service.stop()
        indexer.stop_background_sync()


class Handler(BaseHTTPRequestHandler):
    server_version = "Workbench/260922-perf"

    @property
    def sync_engine(self):
        return getattr(self.server, "sync_engine", None) or sync_service.get()

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/sync/blob":
            return self.send_json({"error": "not_found"}, 404)
        try:
            q = parse_qs(parsed.query)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= CHUNK:
                raise ValueError("附件分块大小无效")
            result = self.sync_engine.receive_blob(q["hash"][0], self.rfile.read(length), int(q["offset"][0]), int(q["total"][0]))
            self.send_json(result)
        except (ValueError, KeyError) as exc:
            self.send_json({"message": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            self.send_json({"message": str(exc)}, 500)

    def log_message(self, fmt, *args):
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def send_json(self, data, status=200):
        body = json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_raw(self, raw):
        """v261009.23 · 原样响应：插件用 `ctx.raw(...)` 返回的字节直接写回（下载/导出/HTML 预览）。

        Content-Disposition 用 `filename*=UTF-8''…` 编码：报告文件名是中文，用裸 filename=
        在部分浏览器上会乱码。
        """
        from urllib.parse import quote

        self.send_response(int(getattr(raw, "status", 200) or 200))
        self.send_header("Content-Type", getattr(raw, "content_type", "") or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw.body)))
        self.send_header("Cache-Control", "no-store")
        name = str(getattr(raw, "filename", "") or "")
        if name:
            self.send_header("Content-Disposition",
                             f"attachment; filename*=UTF-8''{quote(name)}")
        self.end_headers()
        self.wfile.write(raw.body)

    def _send_agent_stream(self, payload):  # v260930k · 方案 A：Agent 对话 SSE 流式端点。
        """Replay durable background events using the existing chat SSE contract.
        A disconnected viewer leaves the job running; cancellation is explicit.
        """
        run = agent_runtime.submit(payload)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")  # v260930m · SSE 用短连接：done 后关闭，前端 EOF 立即到达（keep-alive 会让 read() 永久挂起、UI 卡「停止」）
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("X-Agent-Run-ID", run["id"])
        self.end_headers()

        def emit(event: str, data, seq=None) -> None:
            try:
                event_id = f"id: {seq}\n" if seq is not None else ""
                self.wfile.write(f"event: {event}\n{event_id}data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                raise  # The background job continues after this viewer disconnects.

        try:
            emit("run", {"run_id": run["id"], "session_id": run["session_id"]})
            cursor = 0
            terminal_sent = False
            heartbeat = time.monotonic()
            while True:
                batch = agent_memory.events(run["id"], cursor)
                for item in batch:
                    cursor = item["seq"]
                    if item["event"] in ("round", "delta", "response", "tool", "done", "error", "plan", "status", "compaction", "skill", "retrieval", "capabilities"):
                        emit(item["event"], item["data"], item["seq"])
                        terminal_sent |= item["event"] in ("done", "error")
                current = agent_memory.get_run(run["id"])
                if current["status"] in agent_runtime.TERMINAL and not batch:
                    # Status/result can commit between the events query and this
                    # snapshot, before the worker appends its final event.
                    if not terminal_sent and (current.get("result") or {}).get("assistant"):
                        emit("done", current["result"])
                    elif not terminal_sent and current["status"] == "failed":
                        emit("error", {"message": current.get("error") or "任务执行失败", "run_id": run["id"]})
                    elif not terminal_sent and current["status"] in ("paused", "cancelled", "interrupted"):
                        emit("error", {"message": "任务已暂停或停止，可在任务中心查看并继续", "run_id": run["id"]})
                    elif not terminal_sent:
                        emit("error", {"message": "任务已结束，但未取得保存的回复，请查看任务记录", "run_id": run["id"]})
                    break
                if time.monotonic() - heartbeat > 10:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    heartbeat = time.monotonic()
                time.sleep(.1)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # 客户端已断开：无需再写
        except Exception as e:
            try:
                emit("error", {"message": str(e)})
            except Exception:
                pass


    def send_text(self, text, content_type="text/plain; charset=utf-8", status=200):
        body = text.encode("utf-8") if isinstance(text, str) else text
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or "0")
        if length > 32 * 1024 * 1024:
            raise ValueError("Request too large")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        q = parse_qs(parsed.query, keep_blank_values=True)  # v260930i · 保留空值参数：/api/agent/drafts?status= 依赖空串表示「全量」，否则被解析为未传而回退 pending，导致重启后草稿已确认状态无法校准
        try:
            if path.startswith("/api/"):
                if path.startswith("/api/plugins/"):  # v261009 · §6.3 插件路由（查表分发）
                    return self.handle_plugin_route("GET", path, q)
                return self.handle_api_get(path, q)
            if path.startswith("/workspace-file/"):
                return self.serve_workspace_file(path[len("/workspace-file/"):])
            if path.startswith("/plugins-file/"):
                return self.serve_plugin_file(path[len("/plugins-file/"):])
            if path.startswith("/manual-file/"):   # v261009.30 · 使用手册的图片等资源
                return self.serve_manual_file(path[len("/manual-file/"):])
            return self.serve_static(path)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return  # Window reload/exit can cancel a response in flight.
        except FileNotFoundError as e:
            self.send_json({"error": "not_found", "message": str(e)}, 404)
        except ValueError as e:
            self.send_json({"error": "bad_request", "message": str(e)}, 400)
        except Exception as e:
            self.send_json({"error": type(e).__name__, "message": str(e)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/literature/import":
                with mutation_lock:
                    return self.handle_literature_import()
            # v261009.4 · 插件管理（内核自己的接口，用独立命名空间以免和插件路由撞车）：
            #   POST /api/plugin-manager/<id>/enabled  {enabled: bool}
            if path.startswith("/api/plugin-manager/"):
                parts = [p for p in path[len("/api/plugin-manager/"):].split("/") if p]
                if len(parts) == 2 and parts[1] == "enabled":
                    payload = self.read_json()
                    res = self.set_plugin_enabled(unquote(parts[0]), bool(payload.get("enabled")))
                    return self.send_json(res, 404 if res.get("error") == "not_found" else 200)
                return self.send_json({"error": "not_found", "message": "路径应为 /api/plugin-manager/<id>/enabled"}, 404)
            if path.startswith("/api/plugins/"):  # v261009 · 插件路由
                return self.handle_plugin_route("POST", path, parse_qs(parsed.query, keep_blank_values=True),
                                                self.read_json())
            payload = self.read_json()
            return self.handle_api_post(path, payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except store.RevisionConflict as e:
            self.send_json({"error": "revision_conflict", "message": str(e), "current": e.current}, 409)
        except FileNotFoundError as e:
            self.send_json({"error": "not_found", "message": str(e)}, 404)
        except ValueError as e:
            self.send_json({"error": "bad_request", "message": str(e)}, 400)
        except Exception as e:
            self.send_json({"error": type(e).__name__, "message": str(e)}, 500)

    @serialized_write
    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/plugins/"):  # v261009 · 插件路由
                return self.handle_plugin_route("DELETE", path, parse_qs(parsed.query, keep_blank_values=True))
            if path.startswith("/api/projects/"):
                project_id = unquote(path.split("/api/projects/", 1)[1])
                result = projects.delete_project(project_id)
                indexer.sync(immediate=True)
                return self.send_json(result)
            if path.startswith("/api/docs/"):
                doc_id = unquote(path.split("/api/docs/", 1)[1])
                result = indexer.delete_doc(doc_id)
                return self.send_json(result)
            if path.startswith("/api/todos/"):
                todo_id = unquote(path.split("/api/todos/", 1)[1])
                result = todos.delete(todo_id)
                indexer.refresh_todos()
                return self.send_json(result)
            if path.startswith("/api/literature/") and "/annotations/" in path:
                tail = path.split("/api/literature/",1)[1]
                paper_id, annotation_id = tail.split("/annotations/",1)
                return self.send_json(literature.delete_annotation(unquote(paper_id), unquote(annotation_id)))
            if path.startswith("/api/literature/"):
                paper_id = unquote(path.split("/api/literature/",1)[1])
                return self.send_json(literature.delete_item(paper_id))
            if path.startswith("/api/agent/sessions/"):
                session_id = unquote(path.split("/api/agent/sessions/", 1)[1])
                return self.send_json(agent.delete_session(session_id))
            self.send_json({"error": "not_found"}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except FileNotFoundError as e:
            self.send_json({"error": "not_found", "message": str(e)}, 404)
        except Exception as e:
            self.send_json({"error": type(e).__name__, "message": str(e)}, 500)

    def handle_api_get(self, path, q):
        if path.startswith("/api/sync/"):
            engine = self.sync_engine
            if path == "/api/sync/status":
                return self.send_json(engine.status())
            if path == "/api/sync/manifest":
                scopes = q.get("scopes", [""])[0]
                return self.send_json(engine.manifest(scopes.split(",") if scopes else None))
            if path == "/api/sync/blob-info":
                return self.send_json(engine.blob_info(q.get("hash", [""])[0]))
            if path == "/api/sync/conflict":
                return self.send_json(engine.conflict_detail(q.get("key", [""])[0]))
            if path == "/api/sync/blob":
                source = engine._blob_path(q.get("hash", [""])[0])
                size = source.stat().st_size
                offset = int(q.get("offset", ["0"])[0])
                if not 0 <= offset <= size:
                    raise ValueError("附件断点无效")
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size - offset))
                self.end_headers()
                with source.open("rb") as handle:
                    handle.seek(offset)
                    while chunk := handle.read(CHUNK):
                        self.wfile.write(chunk)
                return
        if path == "/api/health":
            return self.send_json({
                "ok": True,
                "version": _core_version(),
                "index": indexer.status(),
            })
        if path == "/api/config":
            return self.send_json(config.get_public())
        if path == "/api/workspace/info":
            info = workspace.workspace_info()
            info["index"] = indexer.status()
            return self.send_json(info)
        if path == "/api/workspace/tree":
            full = (q.get("full") or ["0"])[0] == "1"
            return self.send_json(workspace.tree() if full else indexer.workspace_tree_root())
        if path == "/api/workspace/children":
            rel = (q.get("path") or [""])[0]
            return self.send_json(indexer.workspace_children(rel))
        if path == "/api/system/index":
            return self.send_json(indexer.status())
        if path == "/api/milestones/plan":
            return self.send_json(milestones.plan())
        if path == "/api/docs":
            kind = (q.get("kind") or [""])[0] or None
            query = (q.get("q") or [""])[0]
            status = (q.get("status") or [""])[0]
            project = (q.get("project") or [""])[0]
            mark = (q.get("mark") or [""])[0]
            tag = (q.get("tag") or [""])[0]
            unowned = (q.get("unowned") or ["0"])[0] == "1"
            page = _q_int(q, "page", 1, 1, 1_000_000)
            page_size = _q_int(q, "page_size", indexer.DEFAULT_PAGE_SIZE, 1, indexer.MAX_PAGE_SIZE)
            paged = (q.get("paged") or ["0"])[0] == "1"
            return self.send_json(indexer.list_docs(
                kind, query, status, project, mark, tag=tag, unowned=unowned,
                page=page, page_size=page_size, paged=paged,
            ))
        if path == "/api/docs/resolve":
            return self.send_json(indexer.resolve_doc((q.get("target") or [""])[0]))
        if path == "/api/docs/draft":
            return self.send_json(store.prepare_doc((q.get("kind") or ["note"])[0], {}))
        # v260923 · 文献 PDF 附件下载：/api/docs/<id>/attachment，路径须置于 /api/docs/ 泛匹配之前
        if path.startswith("/api/docs/") and path.endswith("/attachment"):
            doc_id = unquote(path[len("/api/docs/"):-len("/attachment")])
            att = store.attachment_file(doc_id)
            if not att:
                return self.send_json({"error": "not_found", "message": "附件未配置或文件不存在"}, 404)
            content = att.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'inline; filename="{quote(att.name)}"')
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "private, max-age=60")
            self.end_headers()
            self.wfile.write(content)
            return
        if path.startswith("/api/docs/"):
            doc_id = unquote(path.split("/api/docs/", 1)[1])
            return self.send_json(indexer.get_doc(doc_id))
        if path == "/api/statuses":
            return self.send_json(store.all_statuses())
        if path == "/api/external-access":   # v261009.38 · 外部接入授权（谁能改知识库）
            return self.send_json(external_access.current())
        if path == "/api/manual":            # v261009.30 · 使用手册章节列表
            return self.send_json({"chapters": manual_chapters()})
        if path.startswith("/api/manual/"):
            chapter = manual_chapter(unquote(path[len("/api/manual/"):]))
            if chapter is None:
                return self.send_json({"error": "not_found", "message": "没有这一章"}, 404)
            return self.send_json(chapter)
        if path == "/api/plugins":  # v261009 · §6.3：内核下发「可用且启用」的插件及其面板入口
            # ?detail=1 → 插件预览（设置页的插件管理页用）：多带状态/权限/路由/工具/配置接口等
            detail = (q.get("detail") or [""])[0] in ("1", "true", "yes")
            return self.send_json(self.plugin_payload(detail=detail))
        if path == "/api/knowledge-types":
            return self.send_json(store.knowledge_type_registry())
        if path == "/api/knowledge-marks":  # v261020 · 分类标记：内置模板 / 默认集合 / 上限
            return self.send_json(store.mark_catalog())
        if path == "/api/projects":
            return self.send_json(indexer.project_names())
        if path == "/api/project-records":
            return self.send_json(indexer.project_records())
        if path == "/api/dashboard":
            return self.send_json(indexer.dashboard())
        if path == "/api/graph/overview":
            limit = _q_int(q, "limit", indexer.OVERVIEW_GRAPH_LIMIT, 20, 120)
            return self.send_json(indexer.graph_overview(limit))
        if path == "/api/graph":
            limit = _q_int(q, "limit", indexer.DEFAULT_GRAPH_LIMIT, 20, indexer.MAX_GRAPH_LIMIT)
            return self.send_json(indexer.graph(limit))
        if path == "/api/graph/neighborhood":
            root = (q.get("root") or [""])[0]
            depth = _q_int(q, "depth", 1, 1, 2)
            return self.send_json(indexer.graph_neighborhood(root, depth))
        if path == "/api/todos":
            return self.send_json(indexer.list_todos())
        if path == "/api/search":
            query = (q.get("q") or [""])[0]
            limit = _q_int(q, "limit", 60, 1, 120)
            return self.send_json(indexer.search_all(query, limit))
        if path == "/api/literature":
            return self.send_json(literature.list_items(
                (q.get("q") or [""])[0], (q.get("status") or [""])[0], (q.get("category") or [""])[0],
                _q_int(q, "page", 1, 1, 1000000), _q_int(q, "page_size", 60, 10, 200),
                (q.get("mark") or [""])[0], (q.get("pdf") or [""])[0],
            ))
        if path == "/api/literature/storage":  # v260929 · 设置页：PDF 存放目录概况
            return self.send_json(literature.storage_info())
        if path.startswith("/api/literature/document/"):
            return self.send_json(literature.item_for_document(unquote(path[len("/api/literature/document/"):])))
        if path.startswith("/api/literature/") and path.endswith("/annotations"):
            paper_id = unquote(path.split("/api/literature/",1)[1].rsplit("/annotations",1)[0])
            page_raw = (q.get("page") or [""])[0]
            return self.send_json(literature.get_annotations(paper_id, int(page_raw) if page_raw else None))
        if path.startswith("/api/literature/") and path.endswith("/note"):
            paper_id = unquote(path.split("/api/literature/",1)[1].rsplit("/note",1)[0])
            content = literature.get_note(paper_id)
            return self.send_json({"content": content, "revision": hashlib.sha256(content.encode("utf-8")).hexdigest()})
        if path.startswith("/api/literature/") and path.endswith("/pdf"):
            paper_id = unquote(path.split("/api/literature/",1)[1].rsplit("/pdf",1)[0])
            return self.serve_file_range(literature.pdf_path(paper_id), "application/pdf")
        if path.startswith("/api/literature/"):
            paper_id = unquote(path.split("/api/literature/",1)[1])
            return self.send_json(literature.get_item(paper_id))
        if path == "/api/agent/system":
            agent_runtime.recover()
            return self.send_json({"settings": agent_runtime.settings(), "brain": agent_memory.statistics(), "skills": agent_skills.discover()})
        if path == "/api/agent/rag":
            return self.send_json(agent_rag.status())
        if path == "/api/agent/skills":
            return self.send_json(agent_skills.discover())
        if path == "/api/agent/memories":
            return self.send_json(agent_memory.list_memories(session_id=str((q.get("session_id") or [""])[0]), project_id=str((q.get("project_id") or [""])[0]), include_inactive=str((q.get("all") or [""])[0]) == "1"))
        if path == "/api/agent/memory/graph":
            return self.send_json(agent_memory.graph_data(session_id=str((q.get("session_id") or [""])[0]), project_id=str((q.get("project_id") or [""])[0])))
        if path == "/api/agent/runs":
            agent_runtime.recover()
            return self.send_json([agent_runtime.public_run(r) for r in agent_memory.list_runs(str((q.get("session_id") or [""])[0]))])
        if path.startswith("/api/agent/runs/"):
            tail = path.split("/api/agent/runs/", 1)[1]
            if tail.endswith("/events"):
                return self.send_json(agent_memory.events(tail[:-len("/events")], _q_int(q, "after", 0, 0, 1000000000)))
            return self.send_json(agent_runtime.public_run(agent_memory.get_run(tail)))
        if path == "/api/agent/sessions":
            return self.send_json(agent.list_sessions())
        if path.startswith("/api/agent/sessions/"):
            session_id = unquote(path.split("/api/agent/sessions/", 1)[1])
            return self.send_json(agent.get_session(session_id))
        if path == "/api/agent/tools":  # v260930 · M1 工具清单：前端人设编辑器/悬浮球按白名单展示
            return self.send_json(agent_tools.list_tool_meta())
        if path == "/api/agent/drafts":  # v260930 · M1 待确认草稿列表（默认 pending，?status= 全量）
            return self.send_json(agent_tools.list_drafts(str((q.get("status") or ["pending"])[0])))
        return self.send_json({"error": "not_found"}, 404)

    @serialized_write
    def handle_api_post(self, path, payload):
        if path == "/api/external-access":
            return self.send_json(external_access.save(payload if isinstance(payload, dict) else {}))
        if path.startswith("/api/sync/"):
            engine = self.sync_engine
            actions = {
                "/api/sync/config": lambda: engine.configure(payload),
                "/api/sync/test": lambda: engine.test_connection(payload.get("url")),
                "/api/sync/run": lambda: engine.launch(),
                "/api/sync/check": lambda: engine.launch(check_only=True),
                "/api/sync/apply": lambda: engine.apply_many(payload.get("changes")),
                "/api/sync/preferences": lambda: engine.save_preferences(payload),
                "/api/sync/guard": lambda: engine.guard_editor(payload.get("client"), payload.get("doc_id"), payload.get("dirty")),
                "/api/sync/resolve": lambda: engine.resolve(payload),
            }
            if path in actions:
                return self.send_json(actions[path]())
            return self.send_json({"error": "not_found"}, 404)
        if path == "/api/config/app":
            return self.send_json(config.save_app(payload))
        if path == "/api/knowledge-marks/cleanup":
            result = store.cleanup_deleted_mark(str(payload.get("mark_id") or ""))
            indexer.rebuild()
            return self.send_json(result)
        if path == "/api/system/index/rebuild":
            return self.send_json(indexer.rebuild())
        if path == "/api/system/reload":
            data = config.reload_all()
            workspace.reset_runtime_state()
            root = workspace.ensure_workspace(run_migration=False)
            if data.get("app", {}).get("workspace_migration", {}).get("enabled", True):
                migration = workspace.migrate_legacy(root, force_scan=True)
            else:
                migration = {"skipped": True, "reason": "workspace migration disabled"}
            project_migration = projects.ensure_registry()
            index_state = indexer.rebuild()
            return self.send_json({
                "ok": True,
                "message": "所有配置、缓存与 Workspace 已重新载入",
                "config": config.get_public(),
                "migration": migration,
                "project_migration": project_migration,
                "index": index_state,
            })
        if path == "/api/system/restart":
            self.send_json({"ok": True, "message": "服务正在快速重启"})
            setattr(self.server, "restart_requested", True)
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/api/workspace/folder":
            result = workspace.create_folder(str(payload.get("path") or ""))
            return self.send_json(result)
        if path == "/api/workspace/project":
            result = projects.create_project(
                str(payload.get("name") or ""),
                str(payload.get("description") or ""),
                str(payload.get("status") or "进行中"),
                display_name=str(payload.get("display_name") or ""),
            )
            return self.send_json(result)
        if path == "/api/project-records":
            result = projects.create_project(
                str(payload.get("name") or ""),
                str(payload.get("description") or ""),
                str(payload.get("status") or "进行中"),
                display_name=str(payload.get("display_name") or ""),
            )
            return self.send_json(result, 201)
        if path.startswith("/api/projects/"):
            project_id = unquote(path.split("/api/projects/", 1)[1])
            result = projects.update_project(project_id, payload)
            indexer.sync(immediate=True)
            return self.send_json(result)
        if path == "/api/workspace/migrate":
            legacy = workspace.migrate_legacy(workspace.ensure_workspace(), force_scan=True)
            project_migration = projects.ensure_registry()
            index_state = indexer.rebuild()
            return self.send_json({"legacy": legacy, "projects": project_migration, "index": index_state})
        if path == "/api/workspace/open":
            return self.send_json(workspace.open_path(str(payload.get("path") or "")))
        if path == "/api/workspace/open-with":  # v261008 · 笔记页「打开原文件」：选择 VS Code / Typora 打开 md
            return self.send_json(workspace.open_file_with(
                str(payload.get("path") or ""), str(payload.get("editor") or "")))
        if path == "/api/docs/batch-delete":
            return self.send_json(_delete_documents(_batch_ids(payload)))
        if path == "/api/docs":
            normalized = indexer.normalize_project_payload(payload)
            doc = store.create_doc(str(normalized.get("kind") or "note"), normalized,
                            origin=versions.origin("ui", "doc_create"))
            doc = indexer.apply_doc_project_ids(doc, normalized)
            indexer.index_doc_path(str(doc.get("path") or ""))
            return self.send_json(doc, 201)
        if path.startswith("/api/docs/"):
            doc_id = unquote(path.split("/api/docs/", 1)[1])
            existing = indexer.get_doc(doc_id)
            normalized = indexer.normalize_project_payload({**existing, **payload})
            doc = indexer.update_doc(doc_id, normalized, origin=versions.origin("ui", "doc_save"))
            return self.send_json(doc)
        if path == "/api/assets":
            return self.send_json(store.save_asset(str(payload.get("data_url") or ""), str(payload.get("name") or "image.png")))
        if path == "/api/graph/bundle":
            root = str(payload.get("root") or "")
            ids = payload.get("selected_ids") or []
            content = indexer.build_bundle(
                root, ids, str(payload.get("title") or ""),
                payload.get("active_node_ids") or [], payload.get("relations"),
            )
            return self.send_json({"ok": True, "content": content})
        if path == "/api/graph/bundle/save":
            return self.send_json(store.save_bundle(str(payload.get("filename") or "knowledge-bundle.md"), str(payload.get("content") or "")))
        if path == "/api/literature/export-bibtex":  # v260929 · 修复上游错位：此路由须在 POST 分发且先于 /api/literature/ 泛匹配，否则落入 update_item 报 404
            return self.send_json(indexer.export_bibtex(payload.get("ids") or []))
        if path == "/api/literature/rebuild":  # v260929 · 真值归一：以文献 md 为准重建 library 关联/登记；doc_id 传入时仅处理该条目（徽章点击自动登记）
            return self.send_json(literature.rebuild_registry(str(payload.get("doc_id") or "")))
        if path == "/api/literature/lookup":  # v260929 · 自动填写：DOI/arXiv 编号联网抓取元数据
            return self.send_json(literature.lookup_metadata(str(payload.get("identifier") or "")))
        if path == "/api/literature/storage":  # v260929 · 设置页：修改 PDF 存放目录（可迁移现有 PDF）；v260929f · 支持笔记图片目录
            if "note_images_dir" in payload and "pdf_dir" not in payload and "move_existing" not in payload:
                return self.send_json(literature.set_note_images_dir(str(payload.get("note_images_dir") or "")))
            out = literature.set_pdf_dir(str(payload.get("pdf_dir") or ""), bool(payload.get("move_existing", True)))
            if "note_images_dir" in payload:
                out.update(literature.set_note_images_dir(str(payload.get("note_images_dir") or "")))
            return self.send_json(out)
        if path == "/api/literature/note-image":  # v260929f · 笔记插图 / 批注截图入笔记：图片落盘到笔记图片目录
            return self.send_json(literature.save_note_image(
                str(payload.get("paper_id") or ""), str(payload.get("data_url") or "")), 201)
        if path == "/api/literature/note-image-copy":  # v260929w · 批注截图入笔记：把 Previews 缩略图复制到笔记图片目录
            return self.send_json(literature.copy_preview_to_note_images(
                str(payload.get("paper_id") or ""), str(payload.get("preview_path") or "")), 201)
        if path == "/api/literature/open-folder":  # v260929 · 设置页：文件管理器打开 PDF 目录
            return self.send_json(literature.open_folder())
        if path.startswith("/api/literature/") and path.endswith("/annotations"):
            paper_id = unquote(path.split("/api/literature/",1)[1].rsplit("/annotations",1)[0])
            return self.send_json(literature.save_annotation(paper_id, payload), 201)
        if path.startswith("/api/literature/") and path.endswith("/note"):
            paper_id = unquote(path.split("/api/literature/",1)[1].rsplit("/note",1)[0])
            return self.send_json(literature.save_note(paper_id, str(payload.get("content") or ""), payload.get("expected_revision")))
        if path.startswith("/api/literature/"):
            paper_id = unquote(path.split("/api/literature/",1)[1])
            return self.send_json(literature.update_item(paper_id, payload))
        if path == "/api/agent/settings":
            return self.send_json(agent_runtime.save_settings(payload))
        if path == "/api/agent/rag/settings":
            return self.send_json(agent_rag.save_settings(payload))
        if path == "/api/agent/rag/test":
            return self.send_json(agent_rag.test_connection())
        if path == "/api/agent/rag/index":
            return self.send_json(agent_rag.build_index(), 202)
        if path == "/api/agent/rag/cancel":
            return self.send_json(agent_rag.cancel_build())
        if path == "/api/agent/rag/clear":
            return self.send_json(agent_rag.clear_index())
        if path == "/api/agent/rag/search":
            return self.send_json(agent_rag.search(payload.get("query", ""), kind=payload.get("kind"), limit=payload.get("limit")))
        if path == "/api/agent/skills/install":
            return self.send_json(agent_skills.install(str(payload.get("name") or ""), str(payload.get("content") or ""), payload.get("files")), 201)
        if path == "/api/agent/skills/import":
            return self.send_json(agent_skills.install_zip(payload.get("base64")), 201)
        if path == "/api/agent/skills/resources":
            return self.send_json(agent_skills.diagnostics(str(payload.get("name") or "")))
        if path == "/api/agent/skills/read":
            return self.send_json(agent_skills.read(str(payload.get("name") or ""), str(payload.get("path") or "SKILL.md"), payload.get("offset", 0), payload.get("limit", 12000)))
        if path == "/api/agent/mcp/refresh":
            return self.send_json(agent_mcp.discover())
        if path == "/api/agent/memory/remember":
            allowed = {k: payload[k] for k in ("scope", "scope_id", "namespace", "kind", "importance", "ttl_seconds", "memory_key", "supersedes", "entities", "relations", "embedding") if k in payload}
            return self.send_json(agent_memory.remember(str(payload.get("content") or ""), source=payload.get("source") or {"type": "user"}, **allowed), 201)
        if path == "/api/agent/memory/recall":
            allowed = {k: payload[k] for k in ("namespace", "session_id", "project_id", "limit", "max_chars", "query_embedding", "graph") if k in payload}
            return self.send_json(agent_memory.recall(str(payload.get("query") or ""), **allowed))
        if path == "/api/agent/memory/forget":
            return self.send_json(agent_memory.forget(str(payload.get("id") or "")))
        if path == "/api/agent/backup":
            destination = agent_memory.root() / "Backups" / ("brain-" + time.strftime("%Y%m%d-%H%M%S") + ".sqlite")
            agent_memory.backup(destination)
            relative = destination.relative_to(workspace.ensure_workspace()).as_posix()
            return self.send_json({"ok": True, "path": relative, "url": "/workspace-file/" + relative})
        if path == "/api/agent/runs":
            return self.send_json(agent_runtime.submit(payload), 202)
        if path.startswith("/api/agent/runs/"):
            tail = path.split("/api/agent/runs/", 1)[1]
            run_id, _, action = tail.partition("/")
            return self.send_json(agent_runtime.control(run_id, action))
        if path == "/api/agent/sessions":
            return self.send_json(agent.create_session(str(payload.get("title") or "")), 201)
        if path == "/api/agent/session/rename":
            return self.send_json(agent.rename_session(str(payload.get("id") or ""), str(payload.get("title") or "")))
        if path == "/api/agent/session/archive":  # v260930n · 会话归档/取消归档（删除复用已有 DELETE /api/agent/sessions/<id>，移入 Trash）
            return self.send_json(agent.archive_session(str(payload.get("id") or ""), bool(payload.get("archived"))))
        if path == "/api/agent/assets":
            return self.send_json(agent.save_image(str(payload.get("data_url") or ""), str(payload.get("name") or "image.png")))
        if path == "/api/agent/send":
            return self._send_agent_stream(payload)  # v260930k · 方案 A：SSE 流式转发（delta/round/done/error），前端逐字渲染，长回答不再整体超时
        if path.startswith("/api/agent/drafts/"):  # v260930 · M1 写工具草稿确认流：confirm 落盘 / reject 拒绝
            tail = path.split("/api/agent/drafts/", 1)[1]
            if tail.endswith("/confirm"):
                return self.send_json(agent_tools.confirm_draft(tail[: -len("/confirm")]))
            if tail.endswith("/reject"):
                return self.send_json(agent_tools.reject_draft(tail[: -len("/reject")]))
            raise FileNotFoundError(path)
        if path == "/api/agent/assist":  # v260929 · PDF 阅读区 AI 助手：选中内容的翻译/总结/整理/笔记润色/自定义；v260929c · image 截图多模态
            return self.send_json(agent.assist(
                str(payload.get("action") or ""), str(payload.get("text") or ""),
                str(payload.get("instruction") or ""), str(payload.get("image") or ""),
            ))
        if path == "/api/agent/test":
            return self.send_json(agent.test_connection())
        if path == "/api/kb/related":  # v260930d · M5 阅读中知识关联：页面正文匹配知识库条目（纯文本匹配，零 LLM 依赖）
            return self.send_json({"items": store.match_related(str(payload.get("page_text") or ""))})
        if path == "/api/todos/batch-delete":
            result = todos.delete_many(_batch_ids(payload), completed_only=payload.get("completed_only") is True)
            indexer.refresh_todos()
            return self.send_json(result)
        if path == "/api/todos":
            normalized = indexer.normalize_project_payload(todos.validate_payload(payload))
            item = todos.create(normalized)
            indexer.refresh_todos()
            return self.send_json(item, 201)
        if path.startswith("/api/todos/"):
            todo_id = unquote(path.split("/api/todos/", 1)[1])
            current = next((x for x in indexer.list_todos() if x.get("id") == todo_id), None)
            if current is None:
                raise FileNotFoundError(todo_id)
            normalized = indexer.normalize_project_update(current, todos.validate_payload(payload, partial=True))
            # v261019 · 完成时间限制：逾期仍可完成，但必须显式确认（force=true），
            # 前端据此弹二次确认；返回 409 让调用方区分「逾期需确认」与真正的参数错误。
            try:
                item = todos.update(todo_id, normalized)
            except todos.OverdueError as exc:
                indexer.refresh_todos()
                return self.send_json(
                    {"error": "overdue", "requires_confirm": True, "message": str(exc), "todo": current}, 409
                )
            indexer.refresh_todos()
            return self.send_json(item)
        return self.send_json({"error": "not_found"}, 404)


    def handle_literature_import(self):
        ctype = self.headers.get("Content-Type") or ""
        if "application/pdf" not in ctype and "application/octet-stream" not in ctype:
            raise ValueError("PDF import requires application/pdf")
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > 512 * 1024 * 1024:
            raise ValueError("PDF size must be between 1 byte and 512 MB")
        filename = unquote(self.headers.get("X-Filename") or "paper.pdf")
        fd, tmp_name = tempfile.mkstemp(prefix="erw-pdf-", suffix=".pdf")
        try:
            with os.fdopen(fd, "wb") as out:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk: break
                    out.write(chunk); remaining -= len(chunk)
            if remaining:
                raise ValueError("PDF 上传未完成，请重试")
            binding = unquote(self.headers.get("X-Bind-Paper") or "")
            item = literature.import_pdf(filename, Path(tmp_name), {"bind_paper_id": binding} if binding else None)
            return self.send_json(item, 201)
        finally:
            try: os.unlink(tmp_name)
            except OSError: pass

    def serve_file_range(self, target: Path, content_type: str):
        if not target.exists(): raise FileNotFoundError(str(target))
        size = target.stat().st_size
        start, end, status = 0, max(0, size - 1), 200
        rng = self.headers.get("Range") or ""
        if rng.startswith("bytes="):
            spec = rng[6:].split(",",1)[0]
            left, right = spec.split("-",1)
            if left: start = max(0, min(size - 1, int(left)))
            if right: end = max(start, min(size - 1, int(right)))
            else: end = min(size - 1, start + 4 * 1024 * 1024 - 1)
            status = 206
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "private, max-age=3600")
        if status == 206: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with target.open("rb") as f:
            f.seek(start); remaining = length
            while remaining:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk: break
                self.wfile.write(chunk); remaining -= len(chunk)

    def serve_static(self, path):
        rel = "index.html" if path in ("", "/") else unquote(path.lstrip("/"))
        target = (WEB / rel).resolve()
        if WEB.resolve() not in target.parents and target != WEB.resolve():
            return self.send_json({"error": "forbidden"}, 403)
        if not target.exists() or not target.is_file():
            target = WEB / "index.html"
        content = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def plugin_payload(self, detail: bool = False):
        """内核下发给前端的插件清单（§6.3）。实现见模块级 build_plugin_payload（便于单测）。

        detail=True 用于设置页的「插件」页（预览：状态/权限/路由/工具/配置接口）。
        """
        return build_plugin_payload(ROOT, workspace.ensure_workspace(), detail=detail)

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> dict:
        """启停插件：写 `System/plugins.json`（**不删文件、不动数据**），然后热重载插件集合。

        热重载是安全的：`loader.load()` 每次都在新的路由表/工具表上重新执行 `register(ctx)`，
        插件不持有跨加载的全局状态；且单个插件失败不会影响内核（实测由 plugin_check 与
        verify_plugin_manager 覆盖）。
        """
        from core.plugins import registry as plugin_registry

        workspace_dir = workspace.ensure_workspace()
        candidates, _notes = plugin_registry.discover(plugin_roots(ROOT))
        if plugin_id not in candidates:
            return {"error": "not_found", "message": f"未知插件：{plugin_id}"}
        plugin_registry.write_install_state(workspace_dir, plugin_id, enabled)
        self.plugin_reload()
        return {"ok": True, "id": plugin_id, "enabled": bool(enabled),
                "restart_recommended": False,
                "note": "已生效；前端刷新页面后侧栏与面板会同步（插件停用不删除任何文件与数据）"}

    def plugin_reload(self) -> dict:
        result = load_plugins(ROOT, workspace.ensure_workspace())
        return result

    def handle_plugin_route(self, method, path, q, body=None):
        """插件路由分发（§6.3）：只查已加载插件的路由表，未知路径 404。

        handler 抛异常时返回 500 **只影响该次请求**，错误信息带插件 id（I4）。
        """
        from core.plugins import loader as plugin_loader
        from core.plugins import runtime as plugin_runtime
        from core.plugins.context import RawResponse

        result = plugin_runtime.current()
        if result is None:
            return self.send_json({"error": "not_ready", "message": "插件尚未加载"}, 503)
        status, payload = plugin_loader.dispatch(result, method, path, q, body)
        if isinstance(payload, RawResponse):   # v261009.23 · 插件产出文件：原样写回，不做 JSON 包装
            return self.send_raw(payload)
        return self.send_json(payload, status)

    def serve_plugin_file(self, rel):
        """提供插件自带的静态资源（面板脚本/样式）。**只允许插件目录内的文件**（§7.4 路径安全）。"""
        from core.plugins import registry as plugin_registry

        raw = unquote(rel).replace("\\", "/").lstrip("/")
        pid, _, sub = raw.partition("/")
        if not pid or not sub:
            return self.send_json({"error": "bad_request", "message": "路径应形如 <plugin_id>/<相对路径>"}, 400)
        candidates, _notes = plugin_registry.discover(plugin_roots(ROOT))
        candidate = candidates.get(pid)
        if candidate is None:
            raise FileNotFoundError(f"未知插件：{pid}")
        base = Path(candidate.dir).resolve()
        target = (base / sub).resolve()
        if base != target and base not in target.parents:
            return self.send_json({"error": "forbidden", "message": "插件资源只能取插件目录内的文件"}, 403)
        if not target.is_file():
            raise FileNotFoundError(str(target))
        content = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def serve_workspace_file(self, rel):
        root = workspace.ensure_workspace().resolve()
        target = (root / unquote(rel)).resolve()
        if root not in target.parents and target != root:
            return self.send_json({"error": "forbidden"}, 403)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(str(target))
        content = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "private, max-age=60")
        self.end_headers()
        self.wfile.write(content)

    def serve_manual_file(self, rel):
        """使用手册的图片等资源（`docs/manual/**`）。**只允许手册目录内的文件**（路径安全）。"""
        root = manual_dir().resolve()
        target = (root / unquote(rel)).resolve()
        if root not in target.parents:
            return self.send_json({"error": "forbidden", "message": "只允许取 docs/manual/ 内的文件"}, 403)
        if not target.is_file():
            raise FileNotFoundError(str(target))
        content = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.end_headers()
        self.wfile.write(content)


def _scratch_boot_cleanup() -> None:
    """v261008 · 启动时初始化并清理操作临时空间 .scratch/，失败不影响服务启动。"""
    try:
        scratch.ensure()
        result = scratch.clean(scratch.resolve_retention_days())
        if result["deleted"]:
            print(f"[scratch] {scratch.summarize(result)}")
    except Exception as exc:  # 临时空间异常绝不应阻断工作台启动
        print(f"[scratch] 跳过清理：{type(exc).__name__}: {exc}")


def plugin_roots(root):
    """插件扫描根：默认随包库 + 用户库；`ERW_PLUGINS_ROOTS` 可覆盖（`|` 分隔，测试/便携用）。"""
    from core.plugins import registry as plugin_registry

    env = os.environ.get("ERW_PLUGINS_ROOTS", "").strip()
    if env:
        out = []
        for i, item in enumerate([x for x in env.split("|") if x.strip()]):
            out.append(("bundled" if i == 0 else "user", Path(item.strip()).resolve()))
        return out
    return plugin_registry.default_roots(root, asset_root=ASSET_ROOT)


#: 插件加载结果（进程级）：`build_server()` 里填充，请求分发时查表
PLUGINS = {"result": None}


def _core_version() -> str:
    """`VERSION` 文件里的内核版本（读不到就空串，插件侧按「无版本约束」处理）。

    统一走 `core.plugins.manifest.read_core_version`：它**去掉 UTF-8 BOM**。
    带 BOM 时 `core_min` 比较会全线失败，所有插件被误判为「内核版本过低」而阻塞
    （实测：服务启动后插件路由全 404，而 CLI 因另有一处去 BOM 看起来正常）。
    """
    from core.plugins import manifest as plugin_manifest

    return plugin_manifest.read_core_version(ASSET_ROOT)


def load_plugins(root, workspace_dir) -> dict:
    """启动时加载插件并执行 register(ctx)（§4.2 拓扑顺序；单插件失败不影响内核）。"""
    from core.plugins import loader as plugin_loader

    version = _core_version()
    result = plugin_loader.load(roots=plugin_roots(root), workspace=workspace_dir, core_version=version)
    PLUGINS["result"] = result
    for note in result.notes:
        print(f"[plugins] {note}")
    if result.order:
        print(f"[plugins] 已加载 {len(result.order)} 个：{' → '.join(result.order)}")
    for failure in result.failures():
        print(f"[plugins] 失败：{failure['id']} —— {failure['reason']}", file=sys.stderr)
    return result.as_dict()


def build_plugin_payload(root, workspace_dir, detail: bool = False) -> dict:
    """前端插件清单（§6.3）：只含「已校验可用 且 生效启用」的插件与其面板入口。

    「开不开」的判定在 `core.plugins.registry.effective_enabled`：`System/plugins.json`
    有记录用记录，没有记录用 manifest 的 `default_enabled`（随包附属默认开、可选默认关）。

    `detail=True` 时**额外**给出「插件预览」所需的只读信息（设置页的插件管理页用）：
    名称/简介、权限（带中文说明）、路由、面板、工具、依赖、是否有配置接口、是否为槽位面板等。
    这些字段对宿主无害（宿主只读 id/nav），所以同一接口按 `?detail=1` 区分即可。
    """
    from core.plugins import manifest as plugin_manifest
    from core.plugins import registry as plugin_registry

    roots = plugin_roots(root)
    # §5「安装」的用户可见入口之一：打开设置页的插件页时先把 plugins/ 下的单文件包解包
    # （PLUGIN_SPEC §2），结果作为结构化清单下发给前端展示。只在 detail（设置页）执行；
    # 普通页面加载走只读 discover，不写盘。
    install_rows: list[dict] = []
    if detail:
        install_rows = [o.as_dict() for o in plugin_registry.install_packages(roots, workspace=workspace_dir)]
    candidates, notes = plugin_registry.discover(roots)
    # v261009.22 · 预览必须用**真实**内核版本解析：此前传空串会把 core_min 检查跳过，
    # 于是 core_min 不匹配的插件在设置页显示「可用」，启用后却被加载器拒载（静默失效）。
    core_version = _core_version()
    summary = plugin_registry.resolve(candidates, core_version)
    install = plugin_registry.read_install_state(workspace_dir)
    out = []
    for pid, cand in sorted(candidates.items()):
        manifest = cand.manifest or {}
        enabled = plugin_registry.effective_enabled(cand, install)
        # v261009.22 · 设置页（detail）必须**如实列出装不上的插件**及其原因（rejected/blocked/conflict）——
        # 此前一律跳过，于是 core_min 不匹配或缺依赖的插件在页面上完全消失，用户只看到"还没发现任何插件"，
        # 而 CLI 却能报出原因。普通清单（无 detail，供脚本宿主加载）仍只给「可用且启用」，免得前端去加载装不上的插件。
        if cand.state != "available":
            if not detail:
                continue
        elif not detail and not enabled:
            continue
        nav = []
        def asset_url(rel: str) -> str:
            """插件资源 URL，带**缓存键**（文件 mtime）。

            内核自己的 JS/CSS 由装配清单的 `v` 参数充当缓存键（`app.js?v=…`）；插件资源此前
            没有，浏览器可能一直用旧的面板脚本——改了插件前端、刷新却还是旧行为。这里按文件
            mtime 拼 `?v=`：文件一变键就变，浏览器必然重新取。
            """
            target = Path(cand.dir) / rel
            try:
                stamp = int(target.stat().st_mtime)
            except OSError:
                stamp = 0
            return f"/plugins-file/{pid}/{rel}?v={stamp}"

        for item in manifest.get("nav") or []:
            if not isinstance(item, dict) or not item.get("mount"):
                continue
            entry = {
                "id": str(item.get("id") or pid),
                "label": str(item.get("label") or pid),
                "icon": str(item.get("icon") or ""),
                "url": asset_url(str(item["mount"]).lstrip("/")),
            }
            if item.get("style"):  # 插件自带样式（须按 §2 以 [data-plugin="<id>"] 作用域）
                entry["style_url"] = asset_url(str(item["style"]).lstrip("/"))
            if item.get("slot"):
                entry["slot"] = str(item["slot"])
            nav.append(entry)
        row = {"id": pid, "version": cand.version, "source": cand.source,
               "distribution": manifest.get("distribution") or "",
               "nav": nav}
        # v261009.12 · 没有导航页的 UI（只贡献阅读区/设置页 tab、或只是槽位组件）：
        # 宿主也按这个字段加载面板脚本，否则插件前端永远不会被注册（如 litnote 的阅读区「笔记」tab）。
        panel = manifest.get("panel")
        if isinstance(panel, dict) and panel.get("mount"):
            row["panel_url"] = asset_url(str(panel["mount"]).lstrip("/"))
            if panel.get("style"):
                row["panel_style_url"] = asset_url(str(panel["style"]).lstrip("/"))
        if detail:
            perms = [str(p) for p in (manifest.get("permissions") or [])]
            routes = []
            for route in manifest.get("routes") or []:
                if isinstance(route, dict) and route.get("path"):
                    routes.append(f"{str(route.get('method') or 'GET').upper()} {route['path']}")
            tools = [str(t) for t in (manifest.get("mcp_tools") or [])]
            has_config = any(str(r).endswith(" config") for r in routes)
            row.update({                "name": str(manifest.get("name") or pid),
                "description": str(manifest.get("description") or ""),
                "kind": str(manifest.get("kind") or ""),
                "core_min": str(manifest.get("core_min") or ""),
                "state": cand.state,
                "enabled": enabled,
                "default_enabled": bool(manifest.get("default_enabled", False)),
                "permissions": [{"id": p, "label": plugin_manifest.KNOWN_PERMISSIONS.get(p, "未知权限")} for p in perms],
                "routes": routes,
                "mcp_tools": tools,
                "dependencies": [str(d) for d in (manifest.get("dependencies") or [])],
                "has_config_route": has_config,
                "config_url": f"/api/plugins/{pid}/config" if has_config else "",
                "nav_labels": [n["label"] for n in nav],
                "slot_only": bool(nav) and all(n.get("slot") for n in nav),
                # v261009.27 · 插件自己在 plugin.json 里声明的「演示预览」：内核只负责呈现，不认识具体插件
                # （摘要 / 功能点 / 哪里能找到它 / 截图；截图 URL 带缓存键，图片改了必然重新取）
                # 只在**真有内容**时下发：空对象在 JS 里是真值，会把"没声明预览"的插件也画出一行
                "preview": _plugin_preview(manifest, asset_url) or None,
                "dir": str(cand.dir),
                "blocked_by": list((summary.get("blocked") or {}).get(pid) or []),
                "reason": str(cand.reason or ""),
                "fix": str(cand.fix or ""),
                "issues": [dict(i) for i in (cand.issues or [])],
                "shadowed": str(cand.shadowed or ""),
                "state_label": plugin_registry.STATE_LABELS.get(cand.state, cand.state),
            })
        out.append(row)
    return {"plugins": out, "notes": notes, "core_version": core_version, "install": install_rows}


# ---------------------------------------------------------------- 使用手册（内核自带文档）
#: 手册目录：`docs/manual/`（Markdown + img/ 截图）。在工作台里由 `web/manual.js` 渲染，
#: 因此它**不依赖任何插件**——零插件时也能读。
MANUAL_SUBDIR = ("docs", "manual")


def manual_dir() -> Path:
    return ASSET_ROOT.joinpath(*MANUAL_SUBDIR)


def manual_chapters() -> list[dict]:
    """手册章节目录（README 放最前，其余按文件名排序）。读不到就返回空表，不抛异常。"""
    root = manual_dir()
    if not root.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(root.glob("*.md")):
        title = path.stem
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
        except OSError:
            continue
        out.append({"id": path.stem, "title": title, "file": path.name,
                    "bytes": path.stat().st_size})
    out.sort(key=lambda c: (c["id"] != "README", c["id"]))
    return out


def manual_chapter(chapter_id: str) -> dict | None:
    """按 id 读一章（id = 文件名去 `.md`）。只允许手册目录内的 md，路径安全在此收口。"""
    cid = str(chapter_id or "").strip()
    if not cid or ".." in cid or "/" in cid or "\\" in cid:
        return None
    root = manual_dir().resolve()
    target = (root / f"{cid}.md").resolve()
    if root not in target.parents or not target.is_file():
        return None
    text = target.read_text(encoding="utf-8")
    title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), cid)
    return {"id": cid, "title": title, "markdown": text, "bytes": len(text.encode("utf-8"))}


def _plugin_preview(manifest: dict, asset_url) -> dict:
    """把 manifest 里的 `preview` 整理成前端可渲染的形状（只做形状校验，坏数据不抛异常）。

    约定（PLUGIN_SPEC §3）：`preview = {summary, features[], where, screens[]}`——
    **由插件自己声明**，内核不知道任何具体插件；缺了就是没有预览，列表照常可用。
    """
    raw = manifest.get("preview")
    if not isinstance(raw, dict):
        return {}
    # 形状不对就当没有：**不要把字符串当数组迭代**（"不是数组" 会变成 ['不','是','数','组']）
    raw_features = raw.get("features")
    features = ([str(f).strip() for f in raw_features if str(f).strip()]
                if isinstance(raw_features, list) else [])
    raw_screens = raw.get("screens")
    screens = []
    for shot in (raw_screens if isinstance(raw_screens, list) else []):
        rel = str(shot or "").strip().lstrip("/")
        if rel and ".." not in rel.split("/"):
            screens.append({"rel": rel, "url": asset_url(rel)})
    out = {
        "summary": str(raw.get("summary") or "").strip(),
        "features": features[:8],
        "where": str(raw.get("where") or "").strip(),
        "screens": screens[:4],
    }
    return out if (out["summary"] or out["features"] or out["screens"]) else {}


def build_server(port_override: int | None = None, auto_open_browser: bool | None = None):
    """初始化 workspace/索引并绑定 HTTP 服务。供 main() 与桌面客户端 client.py 共用。

    port_override：端口被占用时由调用方传入空闲端口。
    auto_open_browser：桌面窗口模式传 False，避免额外打开系统浏览器。
    """
    config.init()  # v261009 · 配置初始化由入口显式触发（原先在 config 模块 import 期执行）
    workspace.ensure_workspace()
    load_plugins(ROOT, workspace.ensure_workspace())  # v261009 · §6：启动时加载插件并注册扩展点
    _scratch_boot_cleanup()
    if _project_registry_needs_migration():
        projects.ensure_registry()
    index_state = indexer.initialize(force=False)
    cfg = config.get_app()
    host = str(cfg.get("host") or "127.0.0.1")
    port = int(port_override or cfg.get("port") or 8765)
    server = WorkbenchHTTPServer((host, port), Handler)
    from app import agent_rag_updates
    agent_rag_updates.start()
    sync_service.get()
    url = f"http://{host}:{port}"
    print(f"Engineering Research Workbench running at {url}")
    print(f"Workspace: {workspace.ensure_workspace()}")
    print(f"Index: {index_state.get('counts', {}).get('documents', 0)} docs · {index_state.get('path', '')}")
    open_browser = cfg.get("auto_open_browser", True) if auto_open_browser is None else auto_open_browser
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    return server, cfg, url


def _is_address_in_use(exc: OSError) -> bool:
    """Recognize the Windows and POSIX forms of a bind collision."""
    return getattr(exc, "winerror", None) == 10048 or getattr(exc, "errno", None) in (98, 10048)


def _bind_host(host: str) -> str:
    # 0.0.0.0 is a bind address, not a useful browser/probe address.
    return "127.0.0.1" if host in ("", "0.0.0.0") else host


def _port_available(host: str, port: int) -> bool:
    """Check the configured port before initializing the full application."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((host, int(port)))
        return True
    except OSError:
        return False


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((_bind_host(host), 0))
        return int(probe.getsockname()[1])


def _existing_workbench_url(host: str, port: int, expected_index: Path) -> str | None:
    """Return a healthy same-workspace service URL, if one already owns the port."""
    url = f"http://{_bind_host(host)}:{int(port)}"
    try:
        with urlopen(url + "/api/health", timeout=1.5) as response:
            health = json.load(response)
        if not isinstance(health, dict):
            return None
        index_path = health.get("index", {}).get("path")
        if not health.get("ok") or not index_path:
            return None
        same = os.path.normcase(os.path.abspath(str(index_path))) == os.path.normcase(os.path.abspath(str(expected_index)))
        return url if same else None
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _preferred_server_port(host: str, configured_port: int) -> int:
    """Share the desktop client's last working port when it had to fall back."""
    try:
        from app.paths import DATA_ROOT
        saved = json.loads((DATA_ROOT / "desktop-service.json").read_text(encoding="utf-8"))
        port = int(saved["port"])
        if (saved.get("host") == host and saved.get("configured_port") == configured_port
                and 1 <= port <= 65535):
            return port
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return configured_port


def _remember_server_port(host: str, configured_port: int, port: int) -> None:
    """Persist fallback choice so run.bat and the desktop EXE find one server."""
    try:
        from app.paths import DATA_ROOT
        target = DATA_ROOT / "desktop-service.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"host": host, "configured_port": configured_port,
                                         "port": int(port)}), encoding="utf-8")
        temporary.replace(target)
    except OSError as exc:
        print(f"Could not save the selected service port: {exc}")


def _start_or_reuse_server():
    """Plan startup without producing a noisy second-server bind traceback.

    ``run.bat`` is often launched while the workbench is already running. In
    that case opening the existing same-workspace service is the intended
    behavior. An unrelated process on the configured port gets a fresh port.
    """
    config.init()
    from app.config import workspace_root
    expected_index = workspace_root() / "System" / "Cache" / "index.sqlite"
    cfg = config.get_app()
    host = str(cfg.get("host") or "127.0.0.1")
    configured_port = int(cfg.get("port") or 8765)
    preferred_port = _preferred_server_port(host, configured_port)
    if not _port_available(host, preferred_port):
        existing = _existing_workbench_url(host, preferred_port, expected_index)
        if existing:
            print(f"已有同一工作区服务在运行，打开 {existing}")
            if cfg.get("auto_open_browser", True):
                threading.Timer(0.1, lambda: webbrowser.open(existing)).start()
            return None
        fallback = _free_port(host)
        print(f"端口 {preferred_port} 已被其他程序占用，改用空闲端口 {fallback}")
        preferred_port = fallback
    try:
        started = build_server(port_override=preferred_port)
    except OSError as exc:
        # A race between the probe and bind should have the same friendly
        # fallback as a port occupied before startup.
        if not _is_address_in_use(exc):
            raise
        fallback = _free_port(host)
        print(f"端口 {preferred_port} 在启动时被占用，改用空闲端口 {fallback}")
        started = build_server(port_override=fallback)
    server = started[0]
    _remember_server_port(host, configured_port, server.server_address[1])
    return started


def main():
    started = _start_or_reuse_server()
    if started is None:
        return
    server, _cfg, _url = started
    restart_requested = False
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        restart_requested = bool(getattr(server, "restart_requested", False))
        server.server_close()
        # v261009 · A3：关库前 checkpoint，避免 -wal 无限增长（实测曾累积到 21.4 MB）
        try:
            info = indexer.checkpoint()
            if info.get("wal_pages"):
                print(f"Index WAL checkpointed: {info['wal_pages']} pages")
        except Exception as exc:  # 关库收尾失败不应阻断退出
            print(f"Index checkpoint skipped: {exc}", file=sys.stderr)
    if restart_requested:
        print("Restarting service...")
        if getattr(sys, "frozen", False):
            # v260923 · 打包后多线程进程内 os.execv 不可靠，改为拉起新 exe 进程后退出
            import subprocess
            subprocess.Popen([sys.executable])
            sys.exit(0)
        os.execv(sys.executable, [sys.executable] + sys.argv)


if __name__ == "__main__":
    main()
