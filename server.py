from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from app import config
from app import rss as rss_service
from app import store
from app import todos
from app import weather
from app import workspace
from app import agent
from app import projects
from app import indexer

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


def json_bytes(data) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


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
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    server_version = "Workbench/260922-perf"

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
        q = parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
                return self.handle_api_get(path, q)
            if path.startswith("/workspace-file/"):
                return self.serve_workspace_file(path[len("/workspace-file/"):])
            return self.serve_static(path)
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
            payload = self.read_json()
            return self.handle_api_post(path, payload)
        except FileNotFoundError as e:
            self.send_json({"error": "not_found", "message": str(e)}, 404)
        except ValueError as e:
            self.send_json({"error": "bad_request", "message": str(e)}, 400)
        except Exception as e:
            self.send_json({"error": type(e).__name__, "message": str(e)}, 500)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/projects/"):
                project_id = unquote(path.split("/api/projects/", 1)[1])
                result = projects.delete_project(project_id)
                indexer.sync(force=True)
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
            if path.startswith("/api/agent/sessions/"):
                session_id = unquote(path.split("/api/agent/sessions/", 1)[1])
                return self.send_json(agent.delete_session(session_id))
            self.send_json({"error": "not_found"}, 404)
        except FileNotFoundError as e:
            self.send_json({"error": "not_found", "message": str(e)}, 404)
        except Exception as e:
            self.send_json({"error": type(e).__name__, "message": str(e)}, 500)

    def handle_api_get(self, path, q):
        if path == "/api/health":
            return self.send_json({
                "ok": True,
                "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
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
        if path == "/api/docs":
            kind = (q.get("kind") or [""])[0] or None
            query = (q.get("q") or [""])[0]
            status = (q.get("status") or [""])[0]
            project = (q.get("project") or [""])[0]
            mark = (q.get("mark") or [""])[0]
            page = _q_int(q, "page", 1, 1, 1_000_000)
            page_size = _q_int(q, "page_size", indexer.DEFAULT_PAGE_SIZE, 1, indexer.MAX_PAGE_SIZE)
            paged = (q.get("paged") or ["0"])[0] == "1"
            return self.send_json(indexer.list_docs(
                kind, query, status, project, mark,
                page=page, page_size=page_size, paged=paged,
            ))
        if path.startswith("/api/docs/"):
            doc_id = unquote(path.split("/api/docs/", 1)[1])
            return self.send_json(indexer.get_doc(doc_id))
        if path == "/api/statuses":
            return self.send_json(store.all_statuses())
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
        if path == "/api/weather":
            force = (q.get("force") or ["0"])[0] == "1"
            return self.send_json(weather.current(force=force))
        if path == "/api/weather/geocode":
            name = (q.get("name") or [""])[0]
            return self.send_json(weather.geocode(name))
        if path == "/api/rss":
            force = (q.get("force") or ["0"])[0] == "1"
            return self.send_json(rss_service.fetch(force))
        if path == "/api/search":
            query = (q.get("q") or [""])[0]
            limit = _q_int(q, "limit", 60, 1, 120)
            return self.send_json(indexer.search_all(query, limit))
        if path == "/api/agent/sessions":
            return self.send_json(agent.list_sessions())
        if path.startswith("/api/agent/sessions/"):
            session_id = unquote(path.split("/api/agent/sessions/", 1)[1])
            return self.send_json(agent.get_session(session_id))
        return self.send_json({"error": "not_found"}, 404)

    def handle_api_post(self, path, payload):
        if path == "/api/config/app":
            return self.send_json(config.save_app(payload))
        if path == "/api/config/rss":
            return self.send_json(config.save_rss(payload))
        if path == "/api/system/index/rebuild":
            return self.send_json(indexer.rebuild())
        if path == "/api/system/reload":
            data = config.reload_all()
            workspace.reset_runtime_state()
            root = workspace.ensure_workspace(run_migration=False)
            rss_service.clear_cache()
            weather.clear_cache()
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
            )
            indexer.sync(force=True)
            return self.send_json(result)
        if path == "/api/project-records":
            result = projects.create_project(
                str(payload.get("name") or ""),
                str(payload.get("description") or ""),
                str(payload.get("status") or "进行中"),
            )
            indexer.sync(force=True)
            return self.send_json(result, 201)
        if path.startswith("/api/projects/"):
            project_id = unquote(path.split("/api/projects/", 1)[1])
            result = projects.update_project(project_id, payload)
            indexer.sync(force=True)
            return self.send_json(result)
        if path == "/api/workspace/migrate":
            legacy = workspace.migrate_legacy(workspace.ensure_workspace(), force_scan=True)
            project_migration = projects.ensure_registry()
            index_state = indexer.rebuild()
            return self.send_json({"legacy": legacy, "projects": project_migration, "index": index_state})
        if path == "/api/workspace/open":
            return self.send_json(workspace.open_path(str(payload.get("path") or "")))
        if path == "/api/docs":
            normalized = indexer.normalize_project_payload(payload)
            doc = store.create_doc(str(normalized.get("kind") or "note"), normalized)
            doc = indexer.apply_doc_project_ids(doc, normalized)
            indexer.index_doc_path(str(doc.get("path") or ""))
            return self.send_json(doc, 201)
        if path.startswith("/api/docs/"):
            doc_id = unquote(path.split("/api/docs/", 1)[1])
            existing = indexer.get_doc(doc_id)
            normalized = indexer.normalize_project_payload({**existing, **payload})
            doc = indexer.update_doc(doc_id, normalized)
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
        if path == "/api/literature/export-bibtex":
            return self.send_json(indexer.export_bibtex(payload.get("ids") or []))
        if path == "/api/agent/sessions":
            return self.send_json(agent.create_session(str(payload.get("title") or "")), 201)
        if path == "/api/agent/session/rename":
            return self.send_json(agent.rename_session(str(payload.get("id") or ""), str(payload.get("title") or "")))
        if path == "/api/agent/assets":
            return self.send_json(agent.save_image(str(payload.get("data_url") or ""), str(payload.get("name") or "image.png")))
        if path == "/api/retrieval/search":
            return self.send_json(indexer.retrieve(
                str(payload.get("query") or ""), payload.get("options") or {},
            ))
        if path == "/api/retrieval/embedding/status":
            return self.send_json(indexer.embedding_status(str(payload.get("model") or "")))
        if path == "/api/retrieval/embedding/test":
            return self.send_json(indexer.test_embedding_connection())
        if path == "/api/retrieval/embedding/rebuild":
            return self.send_json(indexer.rebuild_embeddings(
                str(payload.get("model") or ""),
                bool(payload.get("force", False)),
                int(payload.get("batch_size") or 32),
            ))
        if path == "/api/agent/send":
            return self.send_json(agent.send_message(
                str(payload.get("session_id") or ""), str(payload.get("message") or ""),
                payload.get("refs") or [], payload.get("images") or [], str(payload.get("request_preset") or ""),
                payload.get("retrieval") or {},
            ))
        if path == "/api/agent/test":
            return self.send_json(agent.test_connection())
        if path == "/api/todos":
            normalized = indexer.normalize_project_payload(payload)
            item = todos.create(normalized)
            item = indexer.apply_todo_project_id(item, normalized)
            indexer.refresh_todos()
            return self.send_json(item, 201)
        if path.startswith("/api/todos/"):
            todo_id = unquote(path.split("/api/todos/", 1)[1])
            current = next((x for x in indexer.list_todos() if x.get("id") == todo_id), None)
            if current is None:
                raise FileNotFoundError(todo_id)
            normalized = indexer.normalize_project_payload({**current, **payload})
            item = todos.update(todo_id, normalized)
            item = indexer.apply_todo_project_id(item, normalized)
            indexer.refresh_todos()
            return self.send_json(item)
        return self.send_json({"error": "not_found"}, 404)

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


def main():
    workspace.ensure_workspace()
    if _project_registry_needs_migration():
        projects.ensure_registry()
    index_state = indexer.initialize(force=False)
    cfg = config.get_app()
    host = str(cfg.get("host") or "127.0.0.1")
    port = int(cfg.get("port") or 8765)
    server = WorkbenchHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"Engineering Research Workbench running at {url}")
    print(f"Workspace: {workspace.ensure_workspace()}")
    print(f"Index: {index_state.get('counts', {}).get('documents', 0)} docs · {index_state.get('path', '')}")
    if cfg.get("auto_open_browser", True):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    restart_requested = False
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        restart_requested = bool(getattr(server, "restart_requested", False))
        server.server_close()
    if restart_requested:
        print("Restarting service...")
        os.execv(sys.executable, [sys.executable] + sys.argv)


if __name__ == "__main__":
    main()
