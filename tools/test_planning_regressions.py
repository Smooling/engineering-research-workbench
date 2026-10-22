"""Disposable real HTTP/SQLite/Markdown regressions for Agent research plans.

ERW_PLANNING_UI=1 also runs the actual browser against this test server.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from urllib.request import Request, urlopen
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import activity, agent, agent_memory, agent_runtime, agent_tools, config, indexer, milestones, store
from tools import test_functional_regressions as fixtures


class PlanningRegressionTests(unittest.TestCase):
    setUp = fixtures.FunctionalRegressionTests.setUp
    tearDown = fixtures.FunctionalRegressionTests.tearDown
    http = fixtures.FunctionalRegressionTests.http
    request = fixtures.FunctionalRegressionTests.request

    def milestone(self, **changes):
        return indexer.create_doc("milestone", {"title": "里程碑-阶段-修订保护", "body": "PLAN-BODY-42",
            "start_date": "2026-11-01", "due": "2026-11-15", "progress": 35,
            "status": "进行中", "projects": ["排期项目"], **changes})

    def test_same_second_revision_rejects_stale_http_and_has_no_side_effects(self):
        doc = self.milestone()
        with self.http(), patch("app.perf_index_runtime.datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 21, 12, 0, 0)
            status, first = self.request("/api/docs/" + doc["id"], {"due": "2026-11-28", "expected_revision": doc["revision"]})
            self.assertEqual(status, 200)
            status, second = self.request("/api/docs/" + doc["id"], {"progress": 64.5, "expected_revision": first["revision"]})
            self.assertEqual(status, 200)
            self.assertEqual(first["updated"], second["updated"])
            self.assertNotEqual(first["revision"], second["revision"])
            path = self.root / doc["path"]
            contents, events = path.read_bytes(), activity._path().read_bytes()
            status, conflict = self.request("/api/docs/" + doc["id"], {"due": "2026-11-15", "progress": 90, "expected_revision": doc["revision"]})
            self.assertEqual(status, 409)
            self.assertEqual(conflict["error"], "revision_conflict")
            self.assertEqual(conflict["current"]["due"], "2026-11-28")
            self.assertEqual(conflict["current"]["progress"], 64.5)
            self.assertEqual(path.read_bytes(), contents)
            self.assertEqual(activity._path().read_bytes(), events)
            self.assertEqual(conflict["current"]["body"].strip(), "PLAN-BODY-42")
        self.assertEqual(milestones.plan()["items"][0]["revision"], second["revision"])

    def test_parallel_api_writers_compare_revision_inside_write_lock(self):
        doc = self.milestone()
        barrier = threading.Barrier(2)
        def write(change):
            barrier.wait(timeout=5)
            return self.request("/api/docs/" + doc["id"], {**change, "expected_revision": doc["revision"]})
        with self.http(), ThreadPoolExecutor(2) as pool:
            results = list(pool.map(write, [{"due": "2026-11-29"}, {"progress": 64.5}]))
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        saved = indexer.get_doc(doc["id"])
        self.assertEqual(saved["body"].strip(), "PLAN-BODY-42")

    def test_external_or_sync_metadata_and_body_changes_invalidate_snapshot(self):
        doc = self.milestone()
        path = self.root / doc["path"]
        for key, value in (("due", "2026-12-01"), ("body", "同步后的正文"), ("projects", ["同步项目"])):
            old = indexer.get_doc(doc["id"])
            meta, body = store._frontmatter_parse(path.read_text(encoding="utf-8"))
            if key == "body":
                body = value
            else:
                meta[key] = value
            path.write_text(store._frontmatter_dump(meta) + body, encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(store.RevisionConflict):
                indexer.update_doc(doc["id"], {"progress": 90, "expected_revision": old["revision"]})
            self.assertEqual(path.read_bytes(), before)

    def test_status_aliases_share_plan_list_dashboard_and_agent_semantics(self):
        states = {"完成": "done", "已完成": "done", "进行中": "active", "受阻": "blocked", "阻塞": "blocked", "自定义状态": "planned"}
        docs = [self.milestone(title="里程碑-" + raw, status=raw, due="2026-10-01", start_date="") for raw in states]
        with self.http():
            _, dashboard = self.request("/api/dashboard")
            _, rows = self.request("/api/docs?kind=milestone")
            _, plan = self.request("/api/milestones/plan")
        project = next(item for item in dashboard["project_stats"] if item["name"] == "排期项目")
        self.assertEqual(project["open_milestones"], 4)
        self.assertEqual(sum(row["status_class"] == "done" for row in rows), 2)
        for doc in docs:
            row = next(item for item in plan["items"] if item["id"] == doc["id"])
            self.assertEqual(row["status_class"], states[doc["status"]])
            read = agent_tools.execute("kb_read", {"doc_id": doc["id"]})
            self.assertEqual(read["status_class"], row["status_class"])
            self.assertEqual(read["revision"], row["revision"])

    def test_agent_create_preview_approval_once_and_undated_default(self):
        args = {"kind": "milestone", "title": "里程碑-Agent 阶段", "body": "PLAN-BODY-42", "start_date": "2026-11-01",
                "due": "2026-11-15", "progress": 35, "status": "进行中", "projects": ["排期项目"]}
        pending = agent_tools.execute("kb_create_entry", args)
        self.assertTrue(pending["pending"], pending)
        self.assertEqual(milestones.plan()["total"], 0)
        draft = agent_tools._load_draft(pending["draft_id"])
        self.assertEqual(draft["args"]["start_date"], args["start_date"])
        self.assertEqual(next(row for row in draft["changes"] if row["field"] == "due")["after"], args["due"])
        result = agent_tools.confirm_draft(draft["id"])
        self.assertEqual(result["status"], "confirmed", result)
        with self.assertRaises(ValueError):
            agent_tools.confirm_draft(draft["id"])
        self.assertEqual(milestones.plan()["total"], 1)
        saved = indexer.get_doc(result["result"]["doc_id"])
        for key in ("start_date", "due", "progress", "status", "projects"):
            self.assertEqual(saved[key], args[key])
        pending = agent_tools.execute("kb_create_entry", {"kind": "milestone", "title": "里程碑-待排期", "body": "尚未安排"})
        result = agent_tools.confirm_draft(pending["draft_id"])
        saved = indexer.get_doc(result["result"]["doc_id"])
        self.assertEqual(saved["due"], "")
        self.assertIn("待排期", result["result"]["user_message"])

    def test_agent_reject_and_bad_schema_schedule_never_write(self):
        base = {"kind": "milestone", "title": "里程碑-无效计划", "body": "不应创建"}
        invalid = [{"due": "2026-02-29"}, {"start_date": "2026-11-16", "due": "2026-11-15"},
                   {"progress": True}, {"progress": -1}, {"progress": 101}, {"progress": float("nan")},
                   {"unknown_schedule": "ignored?"}, {"projects": [42]}, {"status": " "}]
        for change in invalid:
            result = agent_tools.execute("kb_create_entry", {**base, **change})
            self.assertFalse(result["ok"], result)
            self.assertEqual(agent_tools.list_drafts(), [])
        draft = agent_tools.execute("kb_create_entry", base)
        agent_tools.reject_draft(draft["draft_id"])
        with self.assertRaises(ValueError):
            agent_tools.confirm_draft(draft["draft_id"])
        self.assertEqual(milestones.plan()["total"], 0)

    def test_agent_partial_plan_update_preserves_body_and_rejects_stale_draft(self):
        doc = self.milestone()
        read = agent_tools.execute("kb_read", {"doc_id": doc["id"]})
        pending = agent_tools.execute("kb_update_entry", {"doc_id": doc["id"], "progress": 64.5, "expected_revision": read["revision"]})
        self.assertTrue(pending["pending"], pending)
        self.assertEqual(agent_tools._load_draft(pending["draft_id"])["changes"], [{"field": "progress", "before": 35, "after": 64.5}])
        current = indexer.update_doc(doc["id"], {"due": "2026-11-29", "expected_revision": doc["revision"]})
        failed = agent_tools.confirm_draft(pending["draft_id"])
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["result"]["conflict"])
        self.assertEqual(indexer.get_doc(doc["id"])["revision"], current["revision"])
        pending = agent_tools.execute("kb_update_entry", {"doc_id": doc["id"], "progress": 64.5, "expected_revision": current["revision"]})
        confirmed = agent_tools.confirm_draft(pending["draft_id"])
        self.assertEqual(confirmed["status"], "confirmed", confirmed)
        saved = indexer.get_doc(doc["id"])
        self.assertEqual((saved["due"], saved["progress"], saved["body"].strip()), ("2026-11-29", 64.5, "PLAN-BODY-42"))
        with self.assertRaises(ValueError):
            agent_tools.confirm_draft(pending["draft_id"])
        missing_version = agent_tools.execute("kb_update_entry", {"doc_id": doc["id"], "progress": 80})
        self.assertFalse(missing_version["ok"])

    def test_manual_plan_cannot_overwrite_approved_agent_changes(self):
        doc = self.milestone()
        pending = agent_tools.execute("kb_update_entry", {"doc_id": doc["id"], "due": "2026-11-29", "expected_revision": doc["revision"]})
        confirmed = agent_tools.confirm_draft(pending["draft_id"])
        self.assertEqual(confirmed["status"], "confirmed")
        with self.assertRaises(store.RevisionConflict):
            indexer.update_doc(doc["id"], {"progress": 60, "expected_revision": doc["revision"]})
        saved = indexer.get_doc(doc["id"])
        direct = agent_tools.execute("kb_update_entry", {"doc_id": doc["id"], "progress": None,
            "start_date": "", "projects": [], "status": "已完成", "expected_revision": saved["revision"]}, {"write_mode": "direct"})
        self.assertTrue(direct["ok"], direct)
        saved = indexer.get_doc(doc["id"])
        self.assertEqual(saved["projects"], [])
        self.assertIsNone(saved["progress"])
        self.assertEqual(saved["status_class"], "done")

    def test_invalid_agent_updates_do_not_create_drafts_or_touch_plan(self):
        doc = self.milestone()
        path = self.root / doc["path"]
        original, events = path.read_bytes(), activity._path().read_bytes()
        for fields in ({"due": "2026-02-29"}, {"due": "2026-10-01"}, {"progress": True},
                       {"progress": 101}, {"progress": float("nan")}, {"status": " "},
                       {"projects": [42]}, {"unsupported_field": "ignore?"}, {"append": True}, {}):
            result = agent_tools.execute("kb_update_entry", {"doc_id": doc["id"], "expected_revision": doc["revision"], **fields})
            self.assertFalse(result["ok"], result)
            self.assertEqual(agent_tools.list_drafts(), [])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(activity._path().read_bytes(), events)

    def test_real_model_http_sse_approval_and_resume_create_one_phase(self):
        calls = []
        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(request)
                has_created = any(call.get("function", {}).get("name") == "kb_create_entry"
                                  for message in request["messages"] for call in message.get("tool_calls", []))
                delta = {"content": "已生成排期草稿，请核对日期后确认。"} if has_created else {"tool_calls": [{"index": 0,
                    "id": "call-plan", "type": "function", "function": {"name": "kb_create_entry", "arguments": json.dumps({
                        "kind": "milestone", "title": "里程碑-HTTP 合成排期", "body": "PLAN-BODY-42", "start_date": "2026-11-01",
                        "due": "2026-11-15", "progress": 35, "status": "进行中", "projects": ["排期项目"]})}}]}
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                data = {"id": "synthetic-plan", "choices": [{"index": 0, "delta": delta, "finish_reason": "stop" if has_created else "tool_calls"}]}
                self.wfile.write(("data: " + json.dumps(data) + "\n\ndata: [DONE]\n\n").encode())

        provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        try:
            cfg = config.get_app()
            cfg["llm"].update(enabled=True, active_profile_id="test-local", profiles=[{"id": "test-local", "name": "合成模型",
                "base_url": f"http://127.0.0.1:{provider.server_port}/v1", "api_key": "fake-test-key", "timeout": 10,
                "request_presets": [{"id": "default", "label": "合成", "model": "synthetic", "params": {}}], "default_request_preset": "default"}])
            config.save_app(cfg)
            agent_runtime.save_settings({"auto_recall": False, "memory_enabled": False, "skills_enabled": False, "web_enabled": False})
            with self.http():
                _, session = self.request("/api/agent/sessions", {"title": "排期审批"})
                request = Request(self.base + "/api/agent/send", data=json.dumps({"session_id": session["id"], "persona_id": "executor", "message": "创建阶段排期"}).encode(), headers={"Content-Type": "application/json"})
                with urlopen(request, timeout=20) as response:
                    stream = response.read().decode()
                    run_id = response.headers["X-Agent-Run-ID"]
                self.assertIn("event: done", stream)
                self.assertEqual(milestones.plan()["total"], 0)
                draft = agent_tools.list_drafts()[0]
                _, confirmed = self.request("/api/agent/drafts/" + draft["id"] + "/confirm", {})
                self.assertEqual(confirmed["status"], "confirmed", confirmed)
                self.assertEqual(self.request("/api/agent/drafts/" + draft["id"] + "/confirm", {})[0], 400)
                self.request("/api/agent/runs/" + run_id + "/resume", {})
                deadline = time.monotonic() + 10
                while run_id in agent_runtime._ACTIVE and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(agent_memory.get_run(run_id)["status"], "completed")
                self.assertEqual(milestones.plan()["total"], 1)
                plan = milestones.plan()["items"][0]
                self.assertEqual((plan["start_date"], plan["due"], plan["progress"], plan["status"]), ("2026-11-01", "2026-11-15", 35, "进行中"))
                self.assertEqual(sum(message["role"] == "user" for message in agent.get_session(session["id"])["messages"]), 1)
                self.assertGreaterEqual(len(calls), 2)
        finally:
            provider.shutdown()
            provider.server_close()
            thread.join()

    def test_actual_browser_plan_conflict_merge_and_agent_preview(self):
        doc = self.milestone()
        pending = agent_tools.execute("kb_update_entry", {"doc_id": doc["id"], "progress": 64.5, "expected_revision": doc["revision"]})
        self.assertTrue(pending["pending"], pending)
        if os.environ.get("ERW_PLANNING_UI") == "1":
            # Exercise the complete snapshot beyond the 50-item document page.
            for number in range(54):
                self.milestone(title=f"里程碑-分页样例 {number}", status="已完成" if number % 2 else "计划",
                               **({"start_date": "", "due": "2026-10-01"} if number == 1 else {}))
            session = agent.create_session("排期草稿预览")
            agent_memory.append_message(session["id"], {"role": "assistant", "content": "请核对排期字段后确认。",
                "drafts": [{"draft_id": pending["draft_id"], "tool": "kb_update_entry", "summary": doc["title"]}]})
            with self.http():
                subprocess.run(["node", str(ROOT / "tools/planning_regression_ui_check.js"), self.base, doc["id"], pending["draft_id"], session["id"]],
                               cwd=ROOT, check=True, timeout=120)


if __name__ == "__main__":
    unittest.main()
