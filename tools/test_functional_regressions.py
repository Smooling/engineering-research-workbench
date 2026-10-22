"""Real HTTP regressions for the 2026-10-21 functional issue report.

Set ERW_FUNCTIONAL_UI=1 (with Playwright in NODE_PATH) to also check the real
dashboard response in the full application. All data lives in a temp directory.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import activity, indexer, store, todos
from server import Handler
from tools import test_index_architecture as architecture_tests


class FunctionalRegressionTests(unittest.TestCase):
    # Reuse only the disposable config/workspace lifecycle, not its test cases.
    setUp = architecture_tests.IndexArchitectureTests.setUp
    tearDown = architecture_tests.IndexArchitectureTests.tearDown

    @contextmanager
    def http(self):
        class QuietHandler(Handler):
            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.base = f"http://127.0.0.1:{server.server_port}"
        try:
            yield
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def request(self, path, payload=None):
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        request = Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            response = urlopen(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_bibtex_metadata_batch_unicode_and_multiline(self):
        with self.http():
            ids, citations = [], []
            for i in range(12):
                bib = f"@article{{qa{i},\n  title={{中文研究 {i}}},\n  year={{2026}}\n}}"
                status, doc = self.request("/api/docs", {"kind": "literature", "title": f"样例 {i}",
                                                       "bibtex": bib, "body": "# 阅读笔记"})
                self.assertEqual(status, 201)
                ids.append(doc["id"])
                citations.append(bib)
            status, result = self.request("/api/literature/export-bibtex", {"ids": ids})
        self.assertEqual(status, 200)
        self.assertEqual(result["selected_count"], 12)
        self.assertEqual(result["exported_count"], 12)
        self.assertEqual(result["count"], 12)
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["content"], "\n\n".join(citations) + "\n")
        self.assertEqual((self.root / result["path"]).read_text(encoding="utf-8"), result["content"])

    def test_bibtex_legacy_conflict_explicit_clear_and_missing(self):
        old = "@article{legacy_old,title={Old}}"
        new = "@article{current_new,title={新引用}}"
        body = f"```bibtex\n{old}\n```"
        legacy = indexer.create_doc("literature", {"title": "旧文献", "body": body})
        path = self.root / legacy["path"]
        meta, text = store._frontmatter_parse(path.read_text(encoding="utf-8"))
        meta.pop("bibtex", None)
        path.write_text(store._frontmatter_dump(meta) + text, encoding="utf-8")
        conflict = indexer.create_doc("literature", {"title": "冲突", "bibtex": new, "body": body})
        cleared = indexer.create_doc("literature", {"title": "已清空", "bibtex": "", "body": body})
        empty = indexer.create_doc("literature", {"title": "无引用", "body": "笔记"})
        note = indexer.create_doc("note", {"title": "非文献"})
        ids = [legacy["id"], conflict["id"], cleared["id"], empty["id"], "gone", note["id"]]
        with self.http():
            status, result = self.request("/api/literature/export-bibtex", {"ids": ids + [ids[0]]})
            _, missing = self.request("/api/literature/export-bibtex", {"ids": [cleared["id"]]})
        self.assertEqual(status, 200)
        self.assertEqual(result["selected_count"], 6)
        self.assertEqual(result["content"], old + "\n\n" + new + "\n")
        self.assertEqual(result["count"], 2)
        self.assertEqual([(x["id"], x["reason"]) for x in result["missing"]], [
            (cleared["id"], "missing_bibtex"), (empty["id"], "missing_bibtex"),
            ("gone", "not_found"), (note["id"], "not_literature")])
        self.assertEqual(missing["count"], 0)
        self.assertEqual(missing["content"], "")
        # No explicit selection retains the existing export-all API behavior.
        self.assertEqual(indexer.export_bibtex()["selected_count"], 4)

    def invalid_todo_payloads(self):
        return [
            ({"title": value}, "title") for value in ("", "   ", None, 1, [], {})
        ] + [
            ({"due": value}, "due") for value in ("2026-99-99", "2026-02-29", "20261021", "2026-1-01", " ", True, 123, [])
        ] + [
            ({"priority": value}, "priority") for value in ("unexpected", "", None, [], 1)
        ] + [
            ({"done": value}, "done") for value in ("false", "true", 0, 1, None, [])
        ]

    def test_bibtex_read_failure_is_reported(self):
        from app import perf_index_graph
        doc = indexer.create_doc("literature", {"title": "暂不可读取", "bibtex": "@article{test}"})
        with patch.object(perf_index_graph.store, "_doc_from_path", side_effect=OSError("unavailable")):
            result = indexer.export_bibtex([doc["id"]])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["missing"], [{"id": doc["id"], "title": doc["title"], "reason": "read_failed"}])

    def test_todo_create_rejects_invalid_without_writes_or_activity(self):
        todos.create({"title": "保留的任务"})
        original = todos._path().read_bytes()
        events = activity._path().read_bytes()
        with self.http():
            for invalid, field in self.invalid_todo_payloads():
                with self.subTest(payload=invalid):
                    status, result = self.request("/api/todos", {"title": "有效标题", "project": "不能创建的项目", **invalid})
                    self.assertEqual(status, 400)
                    self.assertIn(field, result["message"])
                    self.assertEqual(todos._path().read_bytes(), original)
                    self.assertEqual(activity._path().read_bytes(), events)
            status, _ = self.request("/api/todos", [])
            self.assertEqual(status, 400)
        self.assertFalse((self.root / "Projects" / "不能创建的项目").exists())

    def test_todo_update_rejects_invalid_and_preserves_original(self):
        item = todos.create({"title": "原任务", "due": "2028-02-29", "priority": "高"})
        indexer.refresh_todos()
        original = todos._path().read_bytes()
        events = activity._path().read_bytes()
        with self.http():
            for invalid, field in self.invalid_todo_payloads():
                with self.subTest(payload=invalid):
                    status, result = self.request("/api/todos/" + item["id"], {"title": "不能保存的改名", **invalid})
                    self.assertEqual(status, 400)
                    self.assertIn(field, result["message"])
                    self.assertEqual(todos._path().read_bytes(), original)
                    self.assertEqual(activity._path().read_bytes(), events)

    def test_todo_defaults_clear_date_priorities_and_completion(self):
        with self.http():
            status, default = self.request("/api/todos", {})
            self.assertEqual(status, 201)
            self.assertEqual((default["title"], default["due"], default["priority"], default["done"]),
                             ("新任务", date.today().isoformat(), "普通", False))
            for priority in ("普通", "紧急", "高", "低"):
                for due in ("", None, "2028-02-29"):
                    status, item = self.request("/api/todos", {"title": "  修剪标题  ", "due": due, "priority": priority})
                    self.assertEqual(status, 201)
                    self.assertEqual(item["title"], "修剪标题")
                    self.assertEqual(item["due"], due or "")
                    for done in (True, False):
                        status, updated = self.request("/api/todos/" + item["id"], {"done": done})
                        self.assertEqual(status, 200)
                        self.assertIs(updated["done"], done)
                        self.assertEqual(updated["due"], due or "")
            _, updated = self.request("/api/todos/" + default["id"], {"due": None})
            self.assertEqual(updated["due"], "")
            _, updated = self.request("/api/todos/" + default["id"], {"title": "  新标题  "})
            self.assertEqual(updated["title"], "新标题")

    def test_invalid_legacy_todo_requires_repair_and_is_never_deleted(self):
        item = todos.create({"title": "历史任务"})
        rows = todos._load()
        rows[0]["due"] = "2026-99-99"
        todos._save(rows)
        original = todos._path().read_bytes()
        with self.assertRaisesRegex(ValueError, "due"):
            todos.update(item["id"], {"done": True})
        self.assertEqual(todos._path().read_bytes(), original)
        repaired = todos.update(item["id"], {"due": "", "done": True})
        self.assertEqual(repaired["due"], "")
        self.assertTrue(repaired["done"])

    def test_dashboard_project_counts_and_real_response_ui(self):
        from app import projects
        names = ("部分完成", "共享项目", "全部完成", "没有节点")
        for name in names:
            projects.create_project(name)
        for i in range(12):
            indexer.create_doc("milestone", {"title": f"共享节点 {i}", "projects": list(names[:2]),
                                             "status": "完成" if i < 6 else "进行中", "due": "2026-10-21"})
        for i in range(2):
            indexer.create_doc("milestone", {"title": f"完成节点 {i}", "projects": [names[2]], "status": "完成"})
        with self.http():
            status, dashboard = self.request("/api/dashboard")
            _, records = self.request("/api/project-records")
            _, plan = self.request("/api/milestones/plan")
            self.assertEqual(status, 200)
            stats = {x["name"]: x for x in dashboard["project_stats"]}
            counts = {x["name"]: x["milestones"] for x in records}
            for name, total, pending in zip(names, (12, 12, 2, 0), (6, 6, 0, 0)):
                self.assertEqual(stats[name]["open_milestones"], pending)
                self.assertEqual(counts[name], total)
                linked = [x for x in plan["items"] if name in x["projects"]]
                self.assertEqual(len(linked), total)
                self.assertEqual(sum(x["status"] != "完成" for x in linked), pending)
            self.assertEqual(dashboard["counts"]["milestone"], 14)
            self.assertEqual(plan["total"], 14)
            if os.environ.get("ERW_FUNCTIONAL_UI") == "1":
                subprocess.run(["node", str(ROOT / "tools/functional_regression_ui_check.js"), self.base],
                               cwd=ROOT, check=True, timeout=90)


if __name__ == "__main__":
    unittest.main()
