"""Provenance acceptance with real outbound HTTP/SSE and disposable workspaces."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import threading
import time
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from tools import test_agent_system as fixture
from app import agent, agent_context, agent_sources as sources, agent_memory as brain, agent_runtime as runtime, agent_research as research, indexer


class SourcesTests(unittest.TestCase):
    wait = fixture.AgentSystemTests.wait
    submit = fixture.AgentSystemTests.submit

    def setUp(self):
        fixture.AgentSystemTests.setUp(self)
        self.calls = []
        self.script = lambda payload, index: {"content": "参见 [[缓存笔记]]。"}
        self.docs = {"note-cache": {"id": "note-cache", "title": "缓存笔记", "kind": "note", "projects": ["缓存研究"], "tags": ["方法"], "body": "状态改变后，应废弃旧缓存。\n保留引号 \" 与反斜杠 \\ 和中文。"}}
        self.stack.enter_context(patch.object(indexer, "get_doc", side_effect=lambda key: copy.deepcopy(self.docs[key]) if key in self.docs else (_ for _ in ()).throw(FileNotFoundError(key))))
        self.stack.enter_context(patch.object(agent.urllib.request, "getproxies", return_value={}))
        test = self

        class Model(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                test.calls.append(copy.deepcopy(payload))
                result = test.script(payload, len(test.calls))
                if isinstance(result, int):
                    self.send_response(result)
                    self.end_headers()
                    self.wfile.write(b'{"error":{"message":"scripted fallback"}}')
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream" if payload.get("stream") else "application/json")
                self.end_headers()
                try:
                    if payload.get("stream"):
                        delta = {**result}
                        if delta.get("tool_calls"):
                            delta["tool_calls"] = [{**call, "index": i} for i, call in enumerate(delta["tool_calls"])]
                        self.wfile.write(("data: " + json.dumps({"choices": [{"delta": delta}]}, ensure_ascii=False) + "\n\ndata: [DONE]\n\n").encode())
                    else:
                        self.wfile.write(json.dumps({"choices": [{"message": result}]}, ensure_ascii=False).encode())
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        self.model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
        self.model.daemon_threads = True
        self.model_thread = threading.Thread(target=self.model.serve_forever, daemon=True)
        self.model_thread.start()
        self.cfg = {"model": "scripted", "api_key": "fake", "base_url": f"http://127.0.0.1:{self.model.server_port}/v1", "show_reasoning": True}
        self.stack.enter_context(patch.object(agent, "_llm_cfg", return_value=self.cfg))
        runtime.save_settings({"auto_recall": False, "skills_enabled": False})

    def tearDown(self):
        self.model.shutdown()
        self.model.server_close()
        self.model_thread.join(2)
        fixture.AgentSystemTests.tearDown(self)

    def complete(self, **payload):
        run = self.wait(self.submit(**payload)["id"], "completed")
        answer = run["result"]["assistant"]
        view = sources.message_view(self.session["id"], answer["id"])
        return run, answer, view

    def all_fragments(self, view):
        return [block for row in view["sources"] for block in sources.message_view(self.session["id"], view["message_id"], row["source_id"])["snapshots"]]

    def assert_manifest_matches_http(self, run):
        with brain.connection() as conn:
            requests = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM source_requests WHERE run_id=? ORDER BY rowid", (run["id"],))]
        self.assertEqual(len(requests), len(self.calls))
        for request, actual in zip(requests, self.calls):
            self.assertEqual(request["messages_digest"], sources.digest(actual["messages"]))
            for block in request["blocks"]:
                content = actual["messages"][block["message_index"]]["content"]
                self.assertEqual(content[block["start"]:block["end"]], block["wire_text"])
            self.assertFalse(any(k.startswith("_") for message in actual["messages"] for k in message))
            self.assertNotIn("source_blocks", json.dumps(actual))

    def test_workspace_read_snapshot_survives_file_change_evidence_and_history(self):
        path = self.root / "Resources/qa-source.txt"
        path.parent.mkdir(parents=True)
        text = '跳过前缀 QA-FILE-SOURCE-73\n引号 "、反斜杠 \\ 与中文。尾部未发送'
        path.write_text(text, encoding="utf-8-sig")
        offset, limit = 5, 36
        def script(payload, index):
            if index == 1:
                return fixture.call("workspace_read", {"path": "Resources/./qa-source.txt", "offset": offset, "limit": limit}, "read-file")
            if index == 2:
                path.write_text("后来改写", encoding="utf-8")
                return fixture.call("evidence_read", {"call_id": "read-file"}, "file-evidence")
            return {"content": "已核对 [[Resources/qa-source.txt]]。"}
        self.script = script
        run, answer, view = self.complete()
        self.assertEqual(view["source_summary"]["recording_status"], "complete")
        self.assertEqual(view["source_summary"]["counts_by_kind"], {"file": 1})
        self.assertEqual(view["source_summary"]["cited_source_count"], 1)
        row = view["sources"][0]
        self.assertEqual(row["entity_key"], "file:Resources/qa-source.txt")
        self.assertEqual(set(row["channels"]), {"read", "history"})
        fragments = self.all_fragments(view)
        original = next(b for b in fragments if b["channel"] == "read")
        self.assertEqual(original["text"], text[offset:offset + limit])
        self.assertEqual(original["version"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(original["location"], {"path": "Resources/qa-source.txt", "offset": offset, "end_offset": offset + limit})
        self.assertIn("QA-FILE-SOURCE-73", json.dumps(self.calls[1], ensure_ascii=False))
        self.assert_manifest_matches_http(run)
        path.unlink()
        self.calls.clear()
        self.script = lambda payload, index: {"content": "根据历史文件继续核对。"}
        run2, _, view2 = self.complete(message="继续核对文件")
        self.assertEqual(view2["source_summary"]["provided_source_count"], 1)
        self.assertEqual(view2["source_summary"]["recording_status"], "complete")
        self.assertTrue(all(b["channel"] == "history" for b in self.all_fragments(view2)))
        self.assertEqual(sources.message_view(self.session["id"], answer["id"]), view)
        self.assertEqual(fragments, self.all_fragments(view))
        self.assert_manifest_matches_http(run2)

    def test_pdf_read_records_real_extracted_pages_and_current_file_version(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        from app import literature
        path = self.root / "source.pdf"
        writer = PdfWriter()
        for text in ("QA-PDF-SOURCE-73 page one", "page two evidence"):
            page = writer.add_blank_page(width=300, height=300)
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = stream
        writer.write(path)
        self.stack.enter_context(patch.object(literature, "ensure_workspace", return_value=self.root))
        with patch.object(literature, "_ensure_doc_entry", return_value=""):
            paper = literature.import_pdf("source.pdf", path, {"title": "PDF 来源验证"})
        stored = literature.pdf_path(paper["id"])
        # The registry hash is deliberately stale after replacement.
        stored.write_bytes(stored.read_bytes() + b"\n% later version\n")
        version = hashlib.sha256(stored.read_bytes()).hexdigest()
        self.assertNotEqual(version, paper["sha256"])
        self.script = lambda payload, index: fixture.call("pdf_read", {"paper_id": paper["id"], "page": 1, "count": 2}, "read-pdf") if index == 1 else {"content": "参见 [[PDF 来源验证]]。"}
        run, _, view = self.complete()
        self.assertEqual(view["source_summary"]["recording_status"], "complete")
        self.assertEqual(view["source_summary"]["counts_by_kind"], {"literature": 1})
        self.assertEqual(view["source_summary"]["cited_source_count"], 1)
        self.assertEqual(view["sources"][0]["paper_id"], paper["id"])
        fragments = self.all_fragments(view)
        self.assertEqual([b["location"]["page"] for b in fragments], [1, 2])
        self.assertEqual([b["text"] for b in fragments], ["QA-PDF-SOURCE-73 page one", "page two evidence"])
        self.assertTrue(all(b["version"] == version and b["provided"] for b in fragments))
        self.assertIn("QA-PDF-SOURCE-73", json.dumps(self.calls[1]))
        self.assert_manifest_matches_http(run)
        stored.unlink()
        self.assertEqual(fragments, self.all_fragments(view))

    def test_file_compaction_and_http_fallback_keep_actual_sent_fragments(self):
        path = self.root / "Resources/large.txt"
        path.parent.mkdir(parents=True)
        path.write_text("QA-FILE-SOURCE-73\n" + "正文含引号和转义。" * 3000 + "TAIL_NOT_SENT", encoding="utf-8")
        runtime.save_settings({"context_tokens": 5200})
        def script(payload, index):
            if index == 1:
                return fixture.call("workspace_read", {"path": "Resources/large.txt", "limit": 24000}, "large-file")
            if index == 2:
                return 400
            return {"content": "已阅读文件。"}
        self.script = script
        run, _, view = self.complete()
        fragments = [b for b in self.all_fragments(view) if b["provided"]]
        self.assertEqual(view["source_summary"]["recording_status"], "complete")
        self.assertEqual(view["source_summary"]["provided_source_count"], 1)
        self.assertTrue(any(b["partial"] for b in fragments))
        self.assertTrue(all("TAIL_NOT_SENT" not in b["text"] for b in fragments))
        self.assertEqual([r["status"] for r in view["requests"]], ["responded", "failed", "responded"])
        self.assert_manifest_matches_http(run)

    def test_missing_read_metadata_and_unadapted_web_fetch_report_incomplete(self):
        cases = [
            ("workspace_read", {"path": "Resources/old.txt", "content": "QA-FILE-SOURCE-73"}),
            ("pdf_read", {"paper_id": "old-pdf", "pages": [{"page": 1, "text": "QA-PDF-SOURCE-73"}]}),
            ("web_fetch", {"url": "https://example.invalid", "content": "未适配网页正文"}),
        ]
        for name, result in cases:
            with self.subTest(tool=name):
                self.session = agent.create_session("Incomplete " + name)
                self.calls.clear()
                self.script = lambda payload, index: fixture.call(name, {}, "unadapted") if index == 1 else {"content": "已核对。"}
                with patch("app.agent_tools.execute", return_value={"ok": True, **result}):
                    run, _, view = self.complete()
                self.assertEqual(view["source_summary"]["recording_status"], "incomplete")
                self.assertTrue(any(name in w for w in view["warnings"]))
                self.assertTrue(any(m["role"] == "tool" for m in self.calls[-1]["messages"]))
                self.assert_manifest_matches_http(run)

    def test_empty_file_and_scanned_pdf_do_not_invent_sources(self):
        results = [
            ("workspace_read", {"path": "Resources/empty.txt", "content": "", "version": "empty-version"}),
            ("pdf_read", {"paper_id": "scan", "version": "scan-version", "pages": [{"page": 1, "text": ""}]}),
        ]
        for name, result in results:
            with self.subTest(tool=name):
                message = sources.tool_message(name, {}, result, "empty")
                self.assertEqual(sources.capture([message]), [])
                self.assertNotIn("_source_incomplete", message)

    def test_manual_page_memory_deduplicate_and_preserve_sent_fragment(self):
        brain.remember("缓存研究使用状态哈希。", scope="user")
        runtime.save_settings({"auto_recall": True})
        run, answer, view = self.complete(message="缓存研究", refs=["note-cache"], context={"doc_id": "note-cache", "selection": "应废弃旧缓存。"})
        self.assertEqual(view["source_summary"]["recording_status"], "complete")
        self.assertEqual(view["source_summary"]["provided_source_count"], 2)
        self.assertEqual(view["source_summary"]["cited_source_count"], 1)
        note = next(s for s in view["sources"] if s["entity_id"] == "note-cache")
        self.assertEqual(set(note["channels"]), {"manual", "page"})
        self.assertEqual(note["tags"], ["方法"])
        fragments = self.all_fragments(view)
        self.assertTrue(any("状态改变后" in b["text"] for b in fragments))
        self.assertTrue(any("应废弃旧缓存。" in b["text"] for b in fragments))
        self.assert_manifest_matches_http(run)
        self.docs["note-cache"]["body"] = "后来改写的内容"
        self.assertEqual(fragments, self.all_fragments(sources.message_view(self.session["id"], answer["id"])))

    def test_rag_read_multiple_versions_and_explicit_citations_only(self):
        hit = {"mode": "keyword", "items": [{"id": "note-cache", "title": "缓存笔记", "kind": "note", "excerpt": "状态哈希用于缓存。", "source": {"offset": 9}}]}
        def script(payload, index):
            if index == 1:
                return fixture.call("kb_search", {"query": "缓存"}, "search")
            if index == 2:
                return fixture.call("kb_read", {"doc_id": "note-cache", "offset": 3, "limit": 12}, "read")
            return {"content": "参见 [[note-cache|缓存方法]]。\n`[[不存在]]`\n```\n[[假的来源]]\n```\n[1]"}
        self.script = script
        with patch("app.agent_rag.search", return_value=hit):
            run, answer, view = self.complete()
        self.assertEqual(view["source_summary"]["provided_source_count"], 1)
        self.assertEqual(view["source_summary"]["cited_source_count"], 1)
        self.assertEqual(view["unresolved_citations"], [])
        self.assertEqual(view["sources"][0]["snapshot_count"], 2)
        self.assertEqual(set(view["sources"][0]["channels"]), {"rag", "read"})
        self.assert_manifest_matches_http(run)
        self.assertIn(self.docs["note-cache"]["body"][3:15], [s["text"] for s in self.all_fragments(view)])

    def test_stream_and_tool_protocol_fallback_attempts_are_distinct(self):
        self.script = lambda payload, index: 400 if payload.get("tools") else {"content": "[[缓存笔记]]"}
        run, answer, view = self.complete(refs=["note-cache"])
        self.assertEqual([r["status"] for r in view["requests"]], ["failed", "failed", "responded"])
        self.assertEqual(len({r["id"] for r in view["requests"]}), 3)
        self.assertEqual(view["requests"][-1]["protocol"], "text")
        self.assertEqual(view["source_summary"]["provided_source_count"], 1)
        self.assert_manifest_matches_http(run)

    def test_compaction_preserves_actual_fragments_and_cuts_unprovided_tail(self):
        self.docs["note-cache"]["body"] = "开头证据。" * 6000 + "TAIL_NOT_SENT"
        self.script = lambda payload, index: fixture.call("kb_read", {"doc_id": "note-cache", "limit": 24000}, "read-big") if index == 1 else {"content": "[[缓存笔记]]"}
        runtime.save_settings({"context_tokens": 5200})
        run, answer, view = self.complete()
        fragments = [s for s in self.all_fragments(view) if s["provided"]]
        self.assertTrue(any(s["partial"] for s in fragments))
        self.assertTrue(all("TAIL_NOT_SENT" not in s["text"] for s in fragments))
        self.assertTrue(any(e["event"] == "compaction" for e in brain.events(run["id"])))
        self.assert_manifest_matches_http(run)

    def test_paused_answer_frozen_and_history_carryover(self):
        run, answer, view = self.complete(refs=["note-cache"])
        previous = copy.deepcopy(view)
        self.calls.clear()
        self.script = lambda payload, index: {"content": "[[缓存笔记]]"}
        run2, answer2, view2 = self.complete(message="继续核对缓存")
        self.assertEqual(sources.message_view(self.session["id"], answer["id"]), previous)
        self.assertIn("history", view2["sources"][0]["channels"])
        self.assert_manifest_matches_http(run2)

    def test_waiting_approval_then_resume_does_not_change_old_answer(self):
        self.script = lambda payload, index: fixture.call("kb_create_entry", {"kind": "note", "title": "知识-方法-缓存验证", "body": "abc"}, "write") if index == 1 else {"content": "已继续完成 [[缓存笔记]]"}
        with patch.object(indexer, "list_docs", return_value=[]):
            run = self.wait(self.submit(refs=["note-cache"])["id"], "waiting_approval")
        old = run["result"]["assistant"]
        before = sources.message_view(self.session["id"], old["id"])
        from app import agent_tools
        agent_tools.reject_draft(run["state"]["waiting_drafts"][0])
        runtime.control(run["id"], "resume")
        result = self.wait(run["id"], "completed")
        self.assertNotEqual(result["result"]["assistant"]["id"], old["id"])
        self.assertEqual(sources.message_view(self.session["id"], old["id"]), before)
        self.assert_manifest_matches_http(result)

    def test_evidence_read_and_memory_tool_have_precise_nested_escaped_spans(self):
        brain.remember("缓存包含引号 \"、反斜杠 \\ 和换行\n第二行。", scope="user")
        def script(payload, index):
            if index == 1:
                return fixture.call("memory_recall", {"query": "缓存"}, "memory")
            if index == 2:
                return fixture.call("evidence_read", {"call_id": "memory", "offset": 10, "limit": 6000}, "evidence")
            return {"content": "已核对。"}
        self.script = script
        run, answer, view = self.complete()
        self.assertEqual(view["source_summary"]["provided_source_count"], 1)
        self.assertEqual(view["source_summary"]["recording_status"], "complete")
        self.assertEqual(set(view["sources"][0]["channels"]), {"memory", "history"})
        self.assert_manifest_matches_http(run)

    def test_citation_ambiguity_and_codes_do_not_create_false_citations(self):
        self.docs["other"] = {**self.docs["note-cache"], "id": "other"}
        self.script = lambda payload, index: {"content": "[[缓存笔记]]\n`[[note-cache]]`\n```md\n[[other]]\n```\n[1]"}
        _, _, view = self.complete(refs=["note-cache", "other"])
        self.assertEqual(view["source_summary"]["cited_source_count"], 0)
        self.assertEqual(view["unresolved_citations"], ["缓存笔记"])

    def test_portable_projection_restore_sqlite_backup_and_ownership(self):
        run, answer, view = self.complete(refs=["note-cache"])
        path = self.root / "System/AgentChats" / (self.session["id"] + ".json")
        exported = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(exported["source_archive"]["views"])
        backup = brain.backup(self.root / "copy.sqlite")
        with closing(sqlite3.connect(backup)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM source_views").fetchone()[0], 1)
        with brain.connection() as conn:
            conn.execute("DELETE FROM source_views")
            conn.execute("DELETE FROM source_requests")
        brain.save_session(exported)
        brain.save_session(exported, merge=True)
        self.assertEqual(sources.message_view(self.session["id"], answer["id"]), view)
        other = agent.create_session()
        with self.assertRaises(FileNotFoundError):
            sources.message_view(other["id"], answer["id"])
        source_id = view["sources"][0]["source_id"]
        with self.assertRaises(FileNotFoundError):
            sources.message_view(self.session["id"], answer["id"], source_id, "src-foreign")
        brain.delete_session(self.session["id"])
        with self.assertRaises(FileNotFoundError):
            sources.message_view(self.session["id"], answer["id"])
        with self.assertRaises(FileNotFoundError):
            sources.run_view(run["id"])

    def test_legacy_is_read_only_and_never_uses_current_document(self):
        brain.append_message(self.session["id"], {"id": "legacy-answer", "role": "assistant", "content": "[[缓存笔记]]", "evidence": [{"role": "tool", "content": json.dumps({"mode": "keyword", "items": [{"id": "note-cache", "title": "缓存笔记", "excerpt": "旧时代片段"}]})}]})
        with patch.object(indexer, "get_doc", side_effect=AssertionError("不得读取最新版")):
            view = sources.message_view(self.session["id"], "legacy-answer")
            self.assertEqual(view, sources.message_view(self.session["id"], "legacy-answer"))
        self.assertEqual(view["source_summary"]["recording_status"], "incomplete")
        self.assertEqual(view["source_summary"]["provided_source_count"], 0)
        with brain.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM source_views").fetchone()[0], 0)

    def test_capture_failure_cannot_repeat_tool_side_effect(self):
        self.script = lambda payload, index: fixture.call("plan_update", {"steps": [{"step": "核对", "status": "completed"}]}, "plan") if index == 1 else {"content": "完成"}
        with patch.object(sources, "tool_message", side_effect=OSError("模拟快照保存失败")):
            run, _, view = self.complete()
        self.assertEqual(len(run["state"]["trace"]), 1)
        self.assertEqual(view["source_summary"]["recording_status"], "incomplete")
        self.assertEqual(len(self.calls), 2)

    def test_text_protocol_tool_context_uses_final_transport_offsets(self):
        def script(payload, index):
            if payload.get("tools"):
                return 400
            if index == 3:
                return {"content": '```json\n' + json.dumps({"tool": "kb_read", "args": {"doc_id": "note-cache"}}) + '\n```'}
            return {"content": "[[缓存笔记]]"}
        self.script = script
        run, _, view = self.complete()
        self.assertEqual(view["source_summary"]["provided_source_count"], 1)
        self.assertTrue(any(m["content"].startswith("工具结果：") for m in self.calls[-1]["messages"] if isinstance(m.get("content"), str)))
        self.assert_manifest_matches_http(run)

    def test_memory_switch_removes_automatic_pack_from_next_request(self):
        brain.remember("缓存的秘密口径。", scope="user")
        runtime.save_settings({"auto_recall": True})
        def script(payload, index):
            if index == 1:
                runtime.save_settings({"memory_enabled": False})
                return fixture.call("plan_update", {"steps": [{"step": "核对", "status": "completed"}]}, "plan")
            return {"content": "完成"}
        self.script = script
        run, _, _ = self.complete(message="缓存")
        self.assertIn("秘密口径", self.calls[0]["messages"][0]["content"])
        self.assertNotIn("秘密口径", self.calls[1]["messages"][0]["content"])
        self.assert_manifest_matches_http(run)

    def test_real_cancel_freezes_unknown_inflight_request_then_resume(self):
        entered, release = threading.Event(), threading.Event()
        def script(payload, index):
            if index == 1:
                entered.set()
                release.wait(3)
            return {"content": "[[缓存笔记]]"}
        self.script = script
        run = self.submit(refs=["note-cache"])
        self.assertTrue(entered.wait(3))
        runtime.control(run["id"], "pause")
        paused = self.wait(run["id"], "paused")
        old = sources.message_view(self.session["id"], paused["result"]["assistant"]["id"])
        release.set()
        runtime.control(run["id"], "resume")
        resumed = self.wait(run["id"], "completed")
        self.assertEqual(sources.message_view(self.session["id"], paused["result"]["assistant"]["id"]), old)
        self.assert_manifest_matches_http(resumed)

    def test_late_provider_callbacks_cannot_reopen_or_change_sealed_recording(self):
        run = brain.create_run(self.session["id"], {"message": "stop"})
        messages = [{"role": "user", "content": "stop"}]
        recorder = sources.Recorder(run["id"], self.session["id"], messages, "tools")
        request_id = recorder.start({"messages": messages})
        recorder.close()
        before = sources.run_view(run["id"])
        recorder.finish(request_id, "responded")
        with self.assertRaises(runtime.Suspended):
            recorder.start({"messages": messages})
        self.assertEqual(sources.run_view(run["id"]), before)
        self.assertEqual(before["requests"][0]["status"], "unknown")
        brain.update_run(run["id"], status="cancelled")

    def test_canonical_id_citation_survives_display_title_masking(self):
        identifier = "note-1234567890abcdef"
        self.docs[identifier] = {**self.docs["note-cache"], "id": identifier}
        self.docs["note-cache"]["title"] = self.docs[identifier]["title"]
        self.script = lambda payload, index: {"content": f"[[{identifier}|缓存依据]]"}
        _, answer, view = self.complete(refs=[identifier, "note-cache"])
        self.assertEqual(view["source_summary"]["cited_source_count"], 1)
        self.assertEqual(next(s for s in view["sources"] if s["cited"])["entity_id"], identifier)
        self.assertNotIn(identifier, answer["content"])

    def test_large_manual_context_budget_and_structural_duplicate_spans(self):
        for i in range(4):
            self.docs[f"large-{i}"] = {"id": f"large-{i}", "title": f"大段资料 {i}", "kind": "note", "body": str(i) * 24000}
        runtime.save_settings({"context_tokens": 200000})
        run, _, view = self.complete(refs=[f"large-{i}" for i in range(4)])
        self.assertEqual(view["source_summary"]["provided_source_count"], 4)
        blocks = self.all_fragments(view)
        self.assertLess(len(blocks[-1]["text"]), len(blocks[0]["text"]))
        self.assert_manifest_matches_http(run)
        meta = sources.source(self.docs["note-cache"], "read", text="same")
        message = sources.json_message({"first": "same", "second": "same"}, [{"path": ["second"], "source": meta}])
        block = sources.capture([message])[0]
        self.assertGreater(block["start"], message["content"].index('"second"'))

    def test_summary_compaction_tracks_only_the_extracted_prefix(self):
        text = "有来源的历史内容。" * 700
        meta = sources.source(self.docs["note-cache"], "history", text=text)
        messages = [{"role": "system", "content": "规则"}, {"role": "user", "content": text, "_sources": [sources.span(meta, text)]},
                    {"role": "assistant", "content": "历史回答"}, {"role": "user", "content": "当前问题"}]
        packed, compaction = agent_context.compact(messages, 2048)
        self.assertTrue(compaction)
        blocks = sources.capture(packed)
        self.assertTrue(blocks)
        self.assertLessEqual(len(blocks[0]["text"]), 220)
        self.assertTrue(blocks[0]["partial"])

    def test_real_sse_emits_sources_updated_and_lightweight_message(self):
        from server import WorkbenchHTTPServer, Handler
        api = WorkbenchHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=api.serve_forever, daemon=True)
        thread.start()
        try:
            req = Request(f"http://127.0.0.1:{api.server_port}/api/agent/send", data=json.dumps({"session_id": self.session["id"], "message": "缓存", "refs": ["note-cache"]}).encode(), headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=8) as response:
                frames = response.read().decode()
            self.assertIn("event: sources_updated", frames)
            self.assertIn('"source_summary"', frames)
            self.assertNotIn('"_sources"', frames)
            public = agent.get_session(self.session["id"])
            self.assertNotIn('"evidence"', json.dumps(public))
            self.assertNotIn('"_context_sources"', json.dumps(public))
            self.assertNotIn('"context_text"', json.dumps(public))
        finally:
            api.shutdown();api.server_close();thread.join(2)

    def test_get_endpoints_are_scoped_and_do_not_rewrite_files(self):
        from server import WorkbenchHTTPServer, Handler
        run, answer, view = self.complete(refs=["note-cache"])
        api = WorkbenchHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=api.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{api.server_port}"
        path = f"/api/agent/sessions/{self.session['id']}/messages/{answer['id']}/sources"
        try:
            before = (self.root / "System/AgentChats" / (self.session["id"] + ".json")).read_bytes()
            with urlopen(base + path) as response:
                self.assertEqual(json.load(response), view)
            with urlopen(base + path + "/" + view["sources"][0]["source_id"]) as response:
                self.assertTrue(json.load(response)["snapshots"])
            with self.assertRaises(HTTPError) as error:
                urlopen(base + path + "/foreign")
            self.assertEqual(error.exception.code, 404)
            self.assertEqual(before, (self.root / "System/AgentChats" / (self.session["id"] + ".json")).read_bytes())
            self.assert_manifest_matches_http(run)
        finally:
            api.shutdown();api.server_close();thread.join(2)


if __name__ == "__main__":
    unittest.main()
