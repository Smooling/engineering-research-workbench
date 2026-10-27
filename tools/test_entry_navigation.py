"""Stable document type conversion and real-browser navigation regressions."""
from itertools import permutations
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import activity, indexer, store
from app import perf_index_runtime as runtime
from tools import test_functional_regressions as fixtures


class EntryNavigationTests(unittest.TestCase):
    setUp = fixtures.FunctionalRegressionTests.setUp
    tearDown = fixtures.FunctionalRegressionTests.tearDown
    http = fixtures.FunctionalRegressionTests.http
    request = fixtures.FunctionalRegressionTests.request

    def entry(self, kind="idea", **changes):
        return indexer.create_doc(kind, {"title": "用缓存减少重复计算", "body": "正文与代码\n\n```python\nx = 1\n```\n\n![图](../Attachments/example.png)",
            "tags": ["缓存", "算法"], "projects": ["项目甲", "项目乙"], "pinned": True, **changes})

    def test_all_six_conversions_preserve_identity_content_and_references(self):
        for source, target in permutations(["idea", "note", "summary"], 2):
            with self.subTest(source=source, target=target):
                doc = self.entry(source, title=source + " 转 " + target)
                reference = indexer.create_doc("note", {"title": "指向 " + doc["id"], "body": f'[[{doc["id"]}]] [[{doc["title"]}]]'})
                converted = indexer.convert_doc_kind(doc["id"], {"kind": target, "expected_revision": doc["revision"]})
                for field in ("id", "title", "body", "created", "tags", "projects", "project_ids", "pinned", "kind_marks"):
                    self.assertEqual(converted[field], doc[field], field)
                self.assertEqual(converted["kind"], target)
                self.assertFalse((self.root / doc["path"]).exists())
                self.assertTrue((self.root / converted["path"]).exists())
                self.assertEqual(Path(converted["path"]).name, Path(doc["path"]).name)
                self.assertEqual(indexer.resolve_doc(doc["id"])["kind"], target)
                self.assertEqual(indexer.resolve_doc(doc["title"])["id"], doc["id"])
                graph = indexer.graph()
                self.assertEqual(next(node["kind"] for node in graph["nodes"] if node["id"] == doc["id"]), target)
                self.assertTrue(any(edge["source"] == reference["id"] and edge["target"] == doc["id"] for edge in graph["edges"]))
                self.assertNotIn(doc["id"], [item["id"] for item in indexer.list_docs(source)])
                self.assertIn(doc["id"], [item["id"] for item in indexer.list_docs(target)])
                self.assertEqual(converted["type_history"][-1]["from"], source)
                self.assertEqual(converted["type_history"][-1]["to"], target)
                self.assertIn(converted["status"], store.kind_statuses(target))
                indexer.rebuild()
                self.assertEqual(indexer.get_doc(doc["id"])["kind"], target)
                self.assertEqual(indexer.get_doc(doc["id"])["type_history"], converted["type_history"])

    def test_roundtrip_history_status_mapping_and_summary_defaults(self):
        original = self.entry(status="探索中")
        first = indexer.convert_doc_kind(original["id"], {"kind": "summary", "expected_revision": original["revision"]})
        self.assertEqual(first["summary_type"], "阶段总结")
        self.assertEqual(first["record_date"], original["created"][:10])
        self.assertEqual(first["type_history"][0]["previous_status"], "探索中")
        self.assertEqual(first["status"], "草稿")
        second = indexer.convert_doc_kind(original["id"], {"kind": "note", "expected_revision": first["revision"]})
        self.assertEqual(second["status"], "草稿")
        self.assertEqual(len(second["type_history"]), 2)
        self.assertEqual(second["created"], original["created"])
        events = [json.loads(line) for line in activity._path().read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(event["type"] == "doc_type_change" for event in events), 2)
        before = (self.root / second["path"]).read_bytes(), activity._path().read_bytes()
        same = indexer.convert_doc_kind(second["id"], {"kind": "note", "expected_revision": second["revision"]})
        self.assertEqual(same["revision"], second["revision"])
        self.assertEqual(before, ((self.root / second["path"]).read_bytes(), activity._path().read_bytes()))

    def test_http_rejects_special_types_invalid_inputs_and_stale_revisions(self):
        doc = self.entry()
        original = (self.root / doc["path"]).read_bytes(), activity._path().read_bytes()
        with self.http():
            endpoint = "/api/docs/" + doc["id"] + "/convert-kind"
            for target in ["literature", "milestone", "journal", "custom", "", None, [], {}]:
                self.assertEqual(self.request(endpoint, {"kind": target, "expected_revision": doc["revision"]})[0], 400)
            self.assertEqual(self.request(endpoint, {"kind": "note"})[0], 400)
            self.assertEqual(self.request(endpoint, {"kind": "note", "expected_revision": "stale"})[0], 409)
            self.assertEqual(self.request("/api/docs/" + doc["id"], {"kind": "note"})[0], 400)
            self.assertEqual(original, ((self.root / doc["path"]).read_bytes(), activity._path().read_bytes()))
            for special in ["literature", "milestone", "journal"]:
                other = self.entry(special)
                self.assertEqual(self.request("/api/docs/" + other["id"] + "/convert-kind", {"kind": "note", "expected_revision": other["revision"]})[0], 400)
            status, converted = self.request(endpoint, {"kind": "note", "expected_revision": doc["revision"]})
            self.assertEqual(status, 200)
            self.assertEqual(self.request("/api/docs/" + doc["id"], {"body": "stale write", "expected_revision": doc["revision"]})[0], 409)
            self.assertEqual(indexer.get_doc(doc["id"])["body"], converted["body"])

    def test_collision_and_move_or_index_failures_do_not_lose_original(self):
        doc = self.entry()
        source = self.root / doc["path"]
        destination = store._kind_path("note") / source.name
        original, events = source.read_bytes(), activity._path().read_bytes()
        destination.write_text("existing file", encoding="utf-8")
        with self.assertRaises(ValueError):
            indexer.convert_doc_kind(doc["id"], {"kind": "note", "expected_revision": doc["revision"]})
        self.assertEqual(destination.read_text(encoding="utf-8"), "existing file")
        destination.unlink()
        with patch.object(Path, "rename", side_effect=PermissionError("file busy")), self.assertRaises(PermissionError):
            indexer.convert_doc_kind(doc["id"], {"kind": "note", "expected_revision": doc["revision"]})
        self.assertEqual(source.read_bytes(), original)
        with patch.object(runtime, "index_doc_path", side_effect=RuntimeError("index failed")), self.assertRaises(RuntimeError):
            indexer.convert_doc_kind(doc["id"], {"kind": "note", "expected_revision": doc["revision"]})
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(destination.exists())
        self.assertEqual(activity._path().read_bytes(), events)
        self.assertEqual(indexer.get_doc(doc["id"])["kind"], "idea")

    def test_parallel_converters_allow_only_one_revision(self):
        doc = self.entry()
        with self.http(), ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda kind: self.request("/api/docs/" + doc["id"] + "/convert-kind",
                {"kind": kind, "expected_revision": doc["revision"]}), ["note", "summary"]))
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        current = indexer.get_doc(doc["id"])
        self.assertEqual(len(current["type_history"]), 1)
        self.assertEqual(current["body"], doc["body"])
        self.assertFalse((self.root / doc["path"]).exists())

    @unittest.skipUnless(os.environ.get("ERW_ENTRY_UI") == "1", "requires browser opt-in")
    def test_actual_browser_conversion_and_navigation(self):
        with self.http():
            subprocess.run(["node", str(ROOT / "tools/entry_navigation_ui_check.js"), self.base], cwd=ROOT, check=True, timeout=180)


if __name__ == "__main__":
    unittest.main()
