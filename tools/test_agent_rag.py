"""Semantic RAG acceptance: disposable data and local fake embeddings only."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import agent_rag as rag, agent_rag_updates as updates, agent_memory as brain, agent_runtime as runtime, agent_tools, config, indexer, literature


class RagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="erw-rag-test-")
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(brain, "ensure_workspace", return_value=self.root))
        self.stack.enter_context(patch.object(config, "CONFIG_DIR", self.root / "local-config"))
        self.docs = {
            "adapter": {"id": "adapter", "title": "Low rank adaptation", "kind": "note", "projects": ["Research"], "path": "Knowledge/Notes/adapter.md", "body": "Tune a small adapter instead of all parameters.\n" * 12},
            "control": {"id": "control", "title": "Weather observations", "kind": "journal", "body": "Observe rain and clouds."},
        }
        def get_doc(key):
            if key not in self.docs:
                raise FileNotFoundError(key)
            return copy.deepcopy(self.docs[key])
        self.stack.enter_context(patch.object(indexer, "get_doc", side_effect=get_doc))
        self.stack.enter_context(patch.object(indexer, "document_metadata", side_effect=lambda: list(self.docs.values())))
        self.stack.enter_context(patch.object(indexer, "sync"))
        self.stack.enter_context(patch.object(updates, "source_stamp", side_effect=lambda opts: rag._version({"body": json.dumps(self.docs, sort_keys=True)})))
        self.stack.enter_context(patch.object(indexer, "retrieve_docs", side_effect=lambda query, kind=None, limit=8: {"items": [d for d in self.docs.values() if (not kind or d["kind"] == kind) and query.lower() in (d["title"] + d["body"]).lower()][:limit]}))
        self.stack.enter_context(patch.object(literature, "ensure_workspace", return_value=self.root))
        self.calls = []
        self.response_mode = "valid"
        test = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                test.calls.append((self.path, dict(self.headers), data))
                if test.response_mode == "http":
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b"provider-secret-body")
                    return
                if test.response_mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "/leaked-credentials")
                    self.end_headers()
                    return
                rows = []
                for i, text in enumerate(data["input"]):
                    vector = [1., 0., 0.] if "adapter" in text or "省参数" in text else [0., 1., 0.]
                    if test.response_mode == "nan":
                        vector = [float("nan"), 0., 1.]
                    if test.response_mode == "zero":
                        vector = [0., 0., 0.]
                    if test.response_mode == "dimensions":
                        vector += [0.]
                    rows.append({"index": i if test.response_mode != "duplicate" else 0, "embedding": vector})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"data": list(reversed(rows))}).encode())
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        rag.save_settings({"base_url": f"http://127.0.0.1:{self.server.server_port}/v1", "model": "fake-embedding", "api_key": "fake-private-key", "mode": "hybrid", "chunk_chars": 256, "overlap_chars": 32, "dimensions": 3})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.stack.close()
        self.tmp.cleanup()

    def build(self):
        status = rag.build_index(background=False)
        self.assertEqual(status["job"]["state"], "completed", status["job"].get("error"))
        return status

    def test_configuration_keeps_key_private_preserves_blank_and_validates(self):
        public = rag.save_settings({"api_key": "", "model": "fake-embedding"})
        self.assertTrue(public["has_api_key"])
        self.assertNotIn("api_key", public)
        self.assertNotIn("fake-private-key", json.dumps(rag.status()))
        self.assertFalse((brain.root() / "agent-rag.json").exists())
        for invalid in ({"overlap_chars": 256}, {"dimensions": 9000}, {"base_url": "https://user:pass@example.invalid"}, {"mode": "unknown"}):
            with self.assertRaises(ValueError):
                rag.save_settings(invalid)
        self.assertTrue(rag.save_settings({"clear_api_key": True})["has_api_key"] is False)

    def test_connection_uses_saved_endpoint_auth_and_single_short_input(self):
        self.assertEqual(rag.test_connection()["dimensions"], 3)
        path, headers, data = self.calls[0]
        self.assertEqual(path, "/v1/embeddings")
        self.assertEqual(headers["Authorization"], "Bearer fake-private-key")
        self.assertEqual(data["dimensions"], 3)
        self.assertLess(len(data["input"][0]), 50)
        for mode in ("http", "redirect", "nan", "zero", "dimensions"):
            self.response_mode = mode
            with self.assertRaises(ValueError) as error:
                rag.test_connection()
            self.assertNotIn("provider-secret-body", str(error.exception))
            self.assertNotIn("fake-private-key", str(error.exception))
        self.assertFalse(any(path == "/leaked-credentials" for path, _, _ in self.calls))

    def test_clear_vectors_preserves_documents_memory_and_disables_auto_updates(self):
        self.build()
        memory = brain.remember("稳定的科研偏好", scope="user", source={"type": "user"})
        rag.save_settings({"realtime_updates": True, "scheduled_updates": True})
        calls = len(self.calls)
        result = rag.clear_index()
        self.assertFalse(result["index"]["ready"])
        self.assertFalse(result["settings"]["realtime_updates"])
        self.assertFalse(result["settings"]["scheduled_updates"])
        self.assertTrue(result["settings"]["has_api_key"])
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(len(self.docs), 2)
        self.assertIn(memory["id"], [m["id"] for m in brain.recall("科研偏好")["results"]])
        with rag._connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 0)
        self.assertEqual(updates.tick(now=1000, background=False), "disabled")
        self.assertGreater(self.build()["index"]["chunks"], 0)

    def test_live_updates_debounce_coalesce_and_reuse_without_retry_loop(self):
        rag.save_settings({"realtime_updates": True, "update_debounce_seconds": 15})
        self.assertEqual(updates.tick(now=1000, background=False), "waiting")
        self.docs["adapter"]["body"] += " changed once"
        self.assertEqual(updates.tick(now=1005, background=False), "waiting")
        self.docs["adapter"]["body"] += " changed twice"
        self.assertEqual(updates.tick(now=1010, background=False), "waiting")
        self.assertFalse(self.calls)
        self.assertEqual(updates.tick(now=1025, background=False), "realtime")
        count = len(self.calls)
        self.assertEqual(updates.tick(now=1050, background=False), "waiting")
        self.assertEqual(len(self.calls), count)
        self.docs["adapter"]["body"] += " update"
        updates.tick(now=1060, background=False)
        self.assertEqual(updates.tick(now=1075, background=False), "realtime")
        self.assertGreater(rag.status()["job"]["reused"], 0)
        self.response_mode = "http"
        self.docs["adapter"]["body"] += " failure"
        updates.tick(now=1080, background=False); updates.tick(now=1095, background=False)
        count = len(self.calls)
        self.assertEqual(rag.status()["job"]["state"], "failed")
        self.assertEqual(updates.tick(now=10000, background=False), "waiting")
        self.assertEqual(len(self.calls), count)

    def test_scheduled_updates_persist_due_time_skip_busy_and_respect_switches(self):
        rag.save_settings({"scheduled_updates": True, "update_interval_minutes": 5})
        self.assertEqual(updates.tick(now=1000, background=False), "waiting")
        self.assertEqual(updates.status()["next_scheduled_at"], 1300)
        self.assertEqual(updates.tick(now=1299, background=False), "waiting")
        self.assertEqual(updates.tick(now=1300, background=False), "scheduled")
        count = len(self.calls)
        self.assertEqual(updates.tick(now=1600, background=False), "scheduled")
        self.assertEqual(len(self.calls), count, "Unchanged scheduled runs spend no embedding calls")
        runtime.save_settings({"rag_enabled": False})
        self.assertEqual(updates.tick(now=2000, background=False), "inactive")
        runtime.save_settings({"rag_enabled": True})
        rag.save_settings({"mode": "keyword"})
        self.assertEqual(updates.tick(now=2000, background=False), "inactive")
        rag.save_settings({"mode": "hybrid"})
        with rag._LOCK:
            rag._JOBS[str(brain.root())] = {"state": "running"}
        self.assertEqual(updates.tick(now=2000, background=False), "busy")
        with self.assertRaises(ValueError):
            rag.clear_index()
        rag._JOBS.pop(str(brain.root()), None)

    def test_build_semantic_lookup_provenance_kind_filter_and_tool_integration(self):
        result = self.build()
        self.assertGreater(result["index"]["chunks"], 2)
        self.assertEqual(result["index"]["dimensions"], 3)
        # Chinese question has no literal overlap with either English document.
        found = agent_tools.execute("kb_search", {"query": "省参数的方法"})
        self.assertTrue(found["ok"])
        item = found["items"][0]
        self.assertEqual(item["id"], "adapter")
        self.assertEqual(item["retrieval"], "semantic")
        source = item["source"]
        self.assertEqual(source["path"], "Knowledge/Notes/adapter.md")
        self.assertIn(self.docs["adapter"]["body"][source["offset"]:source["end_offset"]], item["excerpt"])
        calls = len(self.calls)
        self.assertEqual(rag.search("省参数的方法", kind="journal")["items"], [])
        self.assertEqual(len(self.calls), calls, "Repeated queries reuse a bounded query cache")
        runtime.save_settings({"rag_top_k": 1})
        self.assertLessEqual(rag.search("省参数的方法")["count"], 1)

    def test_configured_recall_count_drives_defaults_across_all_modes_and_tools(self):
        self.docs = {f"doc-{i}": {"id": f"doc-{i}", "kind": "note", "title": f"adapter 方法 {i}", "body": "An adapter uses fewer parameters."} for i in range(15)}
        runtime.save_settings({"rag_top_k": 12})
        rag.save_settings({"mode": "keyword"})
        self.assertEqual(rag.search("adapter")["count"], 12)
        result = agent_tools.execute("kb_search", {"query": "adapter"})
        self.assertEqual(result["count"], 12)
        self.assertEqual(result["limit"], 12)
        self.assertIsNone(result["requested_limit"])
        self.assertEqual(agent_tools.execute("kb_search", {"query": "adapter", "limit": 5})["count"], 5)
        self.assertEqual(agent_tools.execute("kb_search", {"query": "adapter", "limit": 99})["count"], 12)
        specs = agent_tools.openai_specs(["kb_search", "memory_recall"])
        for spec in specs:
            self.assertEqual(spec["function"]["parameters"]["properties"]["limit"]["default"], 12)
        self.assertNotIn("默认 8", agent_tools.text_protocol_prompt(["kb_search"]))
        for i in range(15):
            brain.remember(f"adapter 实验方法 {i}", scope="user")
        self.assertEqual(len(brain.recall("adapter")["results"]), 12)
        self.assertEqual(len(agent_tools.execute("memory_recall", {"query": "adapter"})["results"]), 12)
        self.build()
        for mode in ("semantic", "hybrid"):
            rag.save_settings({"mode": mode})
            self.assertEqual(rag.search("adapter")["count"], 12)
            self.assertEqual(agent_tools.execute("kb_search", {"query": "adapter"})["count"], 12)
        runtime.save_settings({"rag_top_k": 3})
        self.assertEqual(rag.search("adapter")["count"], 3)
        self.assertEqual(agent_tools.openai_specs(["kb_search"])[0]["function"]["parameters"]["properties"]["limit"]["default"], 3)

    def test_incremental_build_reuses_vectors_and_removes_deleted_sources(self):
        first = self.build()
        count = len(self.calls)
        second = self.build()
        self.assertEqual(second["job"]["reused"], first["index"]["chunks"])
        self.assertEqual(len(self.calls), count)
        self.docs["adapter"]["body"] += "A new paragraph."
        changed = self.build()
        self.assertGreater(changed["job"]["reused"], 0)
        self.assertLess(changed["job"]["embedded"], changed["index"]["chunks"])
        del self.docs["adapter"]
        self.assertEqual(rag.search("省参数的方法")["items"], [])
        third = self.build()
        self.assertEqual(third["index"]["sources"], 1)
        self.assertEqual(third["index"]["chunks"], 1)

    def test_changed_sources_filtered_and_failed_or_cancelled_build_retains_index(self):
        first = self.build()["index"]
        self.docs["adapter"]["body"] += "Changed evidence"
        self.assertEqual(rag.search("省参数的方法")["items"], [])
        self.response_mode = "http"
        failed = rag.build_index(background=False)
        self.assertEqual(failed["job"]["state"], "failed")
        self.assertEqual(failed["index"]["generation"], first["generation"])
        self.response_mode = "valid"
        original = rag._embed
        def cancelling(texts, options):
            vectors = original(texts, options)
            rag.cancel_build()
            return vectors
        with patch.object(rag, "_embed", side_effect=cancelling):
            cancelled = rag.build_index(background=False)
        self.assertEqual(cancelled["job"]["state"], "cancelled")
        self.assertEqual(cancelled["index"]["generation"], first["generation"])
        with rag._connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(DISTINCT generation) FROM chunks").fetchone()[0], 1)

    def test_mode_and_switches_do_not_spend_embeddings_without_ready_index(self):
        rag.save_settings({"mode": "keyword"})
        self.assertEqual(rag.search("adapter")["mode"], "keyword")
        self.assertFalse(self.calls)
        rag.save_settings({"mode": "hybrid"})
        self.assertIn("warning", rag.search("adapter"))
        self.assertFalse(self.calls)
        rag.save_settings({"mode": "semantic"})
        with self.assertRaisesRegex(ValueError, "索引"):
            rag.search("adapter")
        self.build()
        rag.save_settings({"model": "another-model"})
        self.assertTrue(rag.status()["index"]["stale"])
        with self.assertRaisesRegex(ValueError, "索引"):
            rag.search("adapter")
        runtime.save_settings({"rag_enabled": False})
        count = len(self.calls)
        with self.assertRaisesRegex(ValueError, "关闭"):
            rag.search("adapter")
        self.assertEqual(len(self.calls), count)

    def test_pdf_index_keeps_page_citations_and_skips_empty_pages(self):
        rag.save_settings({"include_pdf": True, "mode": "semantic"})
        pdf = self.root / "paper.pdf"
        pdf.write_bytes(b"fake-pdf")
        pages = [SimpleNamespace(extract_text=lambda: ""), SimpleNamespace(extract_text=lambda: "An adapter reduces training parameters.")]
        item = {"id": "paper-1", "doc_id": "paper-note", "title": "PDF paper"}
        with patch.object(literature, "list_items", return_value={"items": [item], "total": 1}), patch.object(literature, "pdf_path", return_value=pdf), patch("pypdf.PdfReader", return_value=SimpleNamespace(pages=pages)):
            built = self.build()
            self.assertEqual(built["job"]["empty_sources"], 1)
            hits = rag.search("省参数的方法", kind="literature")["items"]
            self.assertEqual(hits[0]["source"]["page"], 2)
            self.assertEqual(hits[0]["source"]["paper_id"], "paper-1")
            pdf.write_bytes(b"modified-pdf")
            self.assertEqual(rag.search("省参数的方法", kind="literature")["items"], [])

    def test_real_http_routes_and_background_index_lifecycle(self):
        runtime.save_settings({"rag_top_k": 12})
        self.docs.update({f"http-{i}": {"id": f"http-{i}", "kind": "note", "title": f"adapter 方法 {i}", "body": "An adapter uses fewer parameters."} for i in range(14)})
        from server import Handler
        app_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=app_server.serve_forever, daemon=True)
        thread.start()
        def request(path, body=None):
            data = json.dumps(body).encode() if body is not None else None
            with urlopen(Request(f"http://127.0.0.1:{app_server.server_port}/api/agent/rag" + path, data=data, headers={"Content-Type": "application/json"}), timeout=5) as response:
                return json.load(response)
        try:
            self.assertNotIn("api_key", request("")["settings"])
            self.assertEqual(request("/test", {})["dimensions"], 3)
            request("/settings", {"mode": "semantic"})
            request("/index", {})
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                status = request("")
                if status["job"]["state"] not in ("running", "cancelling"):
                    break
                time.sleep(.01)
            self.assertEqual(status["job"]["state"], "completed")
            self.assertEqual(request("/search", {"query": "省参数的方法"})["items"][0]["id"], "adapter")
            self.assertEqual(request("/search", {"query": "省参数的方法"})["count"], 12, "HTTP omitted limit must use configured recall size")
            self.assertFalse(request("/clear", {})["index"]["ready"])
        finally:
            app_server.shutdown()
            app_server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
