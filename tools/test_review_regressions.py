"""2026-10-26 FR-01/03--09 regressions, using disposable data and real HTTP.

Set ERW_FUNCTIONAL_UI=1 to exercise annotation drafts in a real Edge browser.
FR-02 metadata concurrency is deliberately outside this fix.
"""
from __future__ import annotations

import hashlib
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.request import Request, urlopen

from tools import test_functional_regressions as functional_tests
from app import config, indexer, literature, projects, todos

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jR1sAAAAASUVORK5CYII=")


class ReviewRegressionTests(unittest.TestCase):
    setUp = functional_tests.FunctionalRegressionTests.setUp
    tearDown = functional_tests.FunctionalRegressionTests.tearDown
    http = functional_tests.FunctionalRegressionTests.http
    request = functional_tests.FunctionalRegressionTests.request

    def paper(self, name="paper.pdf", content=b"%PDF-1.4\nfirst original content\n"):
        source = self.root / name
        source.write_bytes(content)
        return literature.import_pdf(name, source)

    def assert_downloads(self, paper, expected):
        for path in (f'/api/literature/{paper["id"]}/pdf', f'/api/docs/{paper["doc_id"]}/attachment'):
            with urlopen(self.base + path) as response:
                self.assertEqual(hashlib.sha256(response.read()).hexdigest(), expected)

    def direct_paper(self, title="直接附件批注", content=b"%PDF-1.4\ndirect annotation PDF\n"):
        source = self.root / (uuid.uuid4().hex + ".pdf")
        source.write_bytes(content)
        doc = indexer.create_doc("literature", {"title": title, "attachment": source.name, "body": "原阅读笔记"})
        return literature.item_for_document(doc["id"])

    def screenshot_annotation(self, paper_id, comment="必须保留的截图批注"):
        return literature.save_annotation(paper_id, {"type": "rect", "selection_kind": "area", "page": 3,
            "comment": comment, "rects": [[.1, .1, .4, .2]],
            "preview_data_url": "data:image/png;base64," + base64.b64encode(PNG).decode()})

    def historical_registration(self, content=b"%PDF-1.4\nhistorical registration\n"):
        direct = self.direct_paper("历史 UUID 登记", content)
        annotation = self.screenshot_annotation(direct["id"])
        old_path = literature.annotation_path(direct["id"])
        literature.rebuild_registry(direct["doc_id"])
        # Recreate the pre-fix registry layout without using the recovery API.
        data = literature._load_registry()
        paper = next(x for x in data["items"] if x["doc_id"] == direct["doc_id"])
        paper["id"] = uuid.uuid4().hex
        literature._save_registry(data)
        return direct, paper, annotation, old_path

    def test_annotation_registration_retains_identity_single_full_repeat_and_fresh_process(self):
        with self.http():
            for single in (True, False):
                with self.subTest(single=single):
                    direct = self.direct_paper()
                    annotation = self.screenshot_annotation(direct["id"])
                    original = literature.annotation_path(direct["id"]).read_bytes()
                    digest = literature._file_sha256(literature.pdf_path(direct["id"]))
                    literature.update_item(direct["id"], {"last_page": 3, "page_count": 4})
                    for payload in ({"doc_id": direct["doc_id"]} if single else {}, {}, {"doc_id": direct["doc_id"]}):
                        status, _ = self.request('/api/literature/rebuild', payload)
                        self.assertEqual(status, 200)
                        _, registered = self.request('/api/literature/document/' + direct["doc_id"])
                        self.assertEqual(registered["id"], direct["id"])
                        self.assertEqual((registered["last_page"], registered["page_count"]), (3, 4))
                        status, annotations = self.request('/api/literature/' + registered["id"] + '/annotations?page=3')
                        self.assertEqual(status, 200)
                        self.assertEqual(annotations, [annotation])
                        self.assertEqual(literature.annotation_path(direct["id"]).read_bytes(), original)
                        self.assert_downloads(registered, digest)
                        with urlopen(self.base + '/workspace-file/' + annotation["preview_path"]) as image:
                            self.assertEqual(image.read(), PNG)
                    code = '''
import json, sys
from pathlib import Path
from app import config, indexer, literature
config.ROOT = Path(sys.argv[1])
config.CONFIG_DIR = config.ROOT / "config"
config.SECRET_PATH = config.CONFIG_DIR / "secret.json"
config.LEGACY_SECRET_PATH = config.CONFIG_DIR / "secrets.json"
config._cache = {}
indexer.initialize()
paper = literature.item_for_document(sys.argv[2])
print(json.dumps({"id": paper["id"], "annotations": literature.get_annotations(paper["id"]),
                  "last_page": paper["last_page"], "note": literature.get_note(paper["id"]).strip()}))
'''
                    restarted = subprocess.run([sys.executable, '-c', code, str(self.data), direct["doc_id"]],
                        cwd=functional_tests.ROOT, check=True, capture_output=True, text=True, encoding="utf-8")
                    restored = json.loads(restarted.stdout)
                    self.assertEqual(restored, {"id": direct["id"], "annotations": [annotation],
                                               "last_page": 3, "note": "原阅读笔记"})

    def test_annotation_registration_does_not_overwrite_existing_storage_filename(self):
        direct = self.direct_paper()
        annotation = self.screenshot_annotation(direct["id"])
        source = literature.pdf_path(direct["id"])
        conflict = literature._pdf_dir() / f'{direct["id"]}-{source.name}'
        conflict.write_bytes(b'%PDF-1.4\nunrelated existing storage file\n')
        before = conflict.read_bytes()
        literature.rebuild_registry(direct["doc_id"])
        registered = literature.item_for_document(direct["doc_id"])
        self.assertEqual(registered["id"], direct["id"])
        self.assertEqual(conflict.read_bytes(), before)
        self.assertEqual(literature.pdf_path(registered["id"]).read_bytes(), source.read_bytes())
        self.assertEqual(literature.get_annotations(registered["id"]), [annotation])

    def test_historical_annotation_recovery_merges_ids_preserves_previews_and_alias_edits(self):
        direct, paper, annotation, legacy = self.historical_registration()
        current = dict(annotation, comment="新 ID 下后保存的意见")
        added = dict(annotation, id="current-only", no=2, comment="新 ID 的另一条批注", preview_path="")
        target = literature.annotation_path(paper["id"])
        target.write_text(json.dumps([current, added]), encoding="utf-8")
        extra = dict(annotation, id="legacy-only", comment="旧 ID 的另一条批注", preview_path="")
        legacy.write_text(json.dumps([annotation, extra]), encoding="utf-8")
        legacy_bytes = legacy.read_bytes()
        with self.http():
            status, recovered = self.request('/api/literature/' + paper["id"] + '/annotations')
            self.assertEqual(status, 200)
            self.assertEqual({a["id"] for a in recovered}, {annotation["id"], "current-only", "legacy-only"})
            self.assertEqual(next(a for a in recovered if a["id"] == annotation["id"])["comment"], current["comment"])
            self.assertEqual(len({a["no"] for a in recovered}), 3)
            self.assertEqual(literature.get_annotations(direct["id"]), recovered)
            self.assertFalse(legacy.exists())
            backup = list((target.parent / "Legacy").glob("*.json"))
            self.assertEqual(len(backup), 1)
            self.assertEqual(backup[0].read_bytes(), legacy_bytes)
            with urlopen(self.base + '/workspace-file/' + annotation["preview_path"]) as response:
                self.assertEqual(response.read(), PNG)
            status, copied = self.request('/api/literature/note-image-copy',
                {"paper_id": paper["id"], "preview_path": annotation["preview_path"]})
            self.assertEqual(status, 201)
            self.assertEqual((self.root / copied["path"]).read_bytes(), PNG)
            status, edited = self.request('/api/literature/' + direct["id"] + '/annotations',
                {"id": annotation["id"], "comment": "通过旧窗口修改"})
            self.assertEqual(status, 201)
            self.assertEqual(edited["preview_path"], annotation["preview_path"])
            self.assertEqual(literature.annotation_path(direct["id"]), target)
            with urlopen(Request(self.base + '/api/literature/' + direct["id"] + '/annotations/legacy-only', method='DELETE')) as response:
                self.assertEqual(response.status, 200)
            for _ in range(2):
                self.request('/api/literature/rebuild', {})
                config.reload_all()
                indexer.rebuild()
                self.assertEqual({a["id"] for a in literature.get_annotations(paper["id"])}, {annotation["id"], "current-only"})
            self.assertEqual(len(list((target.parent / "Legacy").glob("*.json"))), 1)
            self.assertEqual((self.root / copied["path"]).read_bytes(), PNG)

    def test_historical_annotation_recovery_from_missing_or_empty_target(self):
        for empty in (True, False):
            direct, paper, annotation, _ = self.historical_registration()
            target = literature.annotation_path(paper["id"])
            if empty:
                target.write_text('[]', encoding='utf-8')
            self.assertEqual(literature.get_annotations(paper["id"]), [annotation])
            self.assertEqual(literature.get_annotations(direct["id"]), [annotation])

    def test_historical_annotation_recovery_failure_is_retryable_without_data_loss(self):
        direct, paper, annotation, legacy = self.historical_registration()
        original = legacy.read_bytes()
        target = literature.annotation_path(paper["id"])
        with patch.object(literature, '_write_annotations', side_effect=OSError('injected write failure')):
            with self.assertRaises(OSError):
                literature.get_annotations(paper["id"])
        self.assertEqual(legacy.read_bytes(), original)
        self.assertFalse(target.exists())
        real_replace = Path.replace

        def failed_archive(path, destination):
            if path == legacy:
                raise PermissionError('injected archive failure')
            return real_replace(path, destination)

        with patch.object(Path, 'replace', failed_archive), self.assertRaises(PermissionError):
            literature.get_annotations(direct["id"])
        self.assertEqual(legacy.read_bytes(), original)
        self.assertEqual(json.loads(target.read_text(encoding='utf-8')), [annotation])
        self.assertEqual(literature.get_annotations(paper["id"]), [annotation])
        literature.delete_annotation(paper["id"], annotation["id"])
        self.assertEqual(literature.get_annotations(direct["id"]), [])

    def test_historical_annotation_recovery_rejects_corrupt_source_without_overwriting(self):
        _, paper, annotation, legacy = self.historical_registration()
        target = literature.annotation_path(paper["id"])
        target.write_text(json.dumps([annotation]), encoding='utf-8')
        before = target.read_bytes()
        legacy.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            literature.get_annotations(paper["id"])
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(legacy.read_text(encoding='utf-8'), '{broken')

    def test_historical_annotation_alias_requests_share_one_store_during_recovery(self):
        direct, paper, annotation, _ = self.historical_registration()
        with self.http():
            def save(pair):
                paper_id, comment = pair
                return self.request('/api/literature/' + paper_id + '/annotations', {"comment": comment})
            with ThreadPoolExecutor(max_workers=2) as pool:
                saved = list(pool.map(save, [(direct["id"], "旧窗口"), (paper["id"], "新窗口")]))
            self.assertTrue(all(status == 201 for status, _ in saved))
            rows = literature.get_annotations(paper["id"])
            self.assertEqual({a["id"] for a in rows}, {annotation["id"], *[a["id"] for _, a in saved]})
            self.assertEqual(literature.get_annotations(direct["id"]), rows)

    def test_migration_updates_all_references_and_preserves_download_hashes(self):
        paper = self.paper()
        before = literature.pdf_path(paper["id"]).read_bytes()
        shared = indexer.create_doc("literature", {"title": "共享引用", "attachment": paper["attachment"]})
        with self.http():
            status, result = self.request('/api/literature/storage', {"pdf_dir": "RelocatedPDFs", "move_existing": True})
            self.assertEqual(status, 200)
            self.assertEqual(result["updated"], 2)
            self.assert_downloads(paper, hashlib.sha256(before).hexdigest())
            self.assertTrue(indexer.get_doc(shared["id"])["attachment"].startswith("RelocatedPDFs/"))
            indexer.rebuild()
            self.assert_downloads(paper, hashlib.sha256(before).hexdigest())

    def test_migration_reuses_identical_and_rejects_different_content_before_writes(self):
        paper = self.paper()
        old = literature._pdf_dir()
        target = self.root / "destination"
        target.mkdir()
        dest = target / paper["stored_filename"]
        dest.write_bytes(b"%PDF-1.4\ndifferent PDF\n")
        original = indexer.get_doc(paper["doc_id"])
        config_before = (config.CONFIG_DIR / "app.json").read_bytes()
        with self.http():
            for move in (True, False):
                status, _ = self.request('/api/literature/storage', {"pdf_dir": "destination", "move_existing": move})
                self.assertEqual(status, 400)
                self.assertEqual(literature._pdf_dir(), old)
                self.assertEqual(indexer.get_doc(paper["doc_id"])["revision"], original["revision"])
                self.assertEqual((config.CONFIG_DIR / "app.json").read_bytes(), config_before)
                self.assert_downloads(paper, paper["sha256"])
            dest.write_bytes((old / paper["stored_filename"]).read_bytes())
            status, result = self.request('/api/literature/storage', {"pdf_dir": "destination"})
            self.assertEqual(status, 200)
            self.assertEqual(result["skipped"], 1)
            self.assert_downloads(paper, paper["sha256"])

    def test_migration_failures_restore_documents_config_and_originals(self):
        papers = [self.paper(), self.paper("second.pdf", b"%PDF-1.4\nsecond\n")]
        old = literature._pdf_dir()
        originals = {self.root / indexer.get_doc(p["doc_id"])["path"]: indexer.get_doc(p["doc_id"])["revision"] for p in papers}
        app_before = (config.CONFIG_DIR / "app.json").read_bytes()
        real_update, real_save = indexer.update_doc, config.save_app
        calls = []

        def fail_update(*args, **kwargs):
            calls.append(1)
            result = real_update(*args, **kwargs)
            if len(calls) == 2:
                raise OSError("injected document failure after writing")
            return result

        def fail_config(*args, **kwargs):
            real_save(*args, **kwargs)
            raise OSError("injected configuration failure after writing")

        def interrupted_copy(src, dest):
            dest.write(src.read(8))
            raise InterruptedError("injected interrupted copy")

        scenarios = [patch.object(literature.shutil, "copyfileobj", side_effect=interrupted_copy),
                     patch.object(indexer, "update_doc", side_effect=fail_update),
                     patch.object(config, "save_app", side_effect=fail_config)]
        for i, failure in enumerate(scenarios):
            with self.subTest(failure=i), failure:
                with self.assertRaises(OSError):
                    literature.set_pdf_dir(f"failed-{i}")
            self.assertEqual(literature._pdf_dir(), old)
            self.assertEqual((config.CONFIG_DIR / "app.json").read_bytes(), app_before)
            self.assertEqual(list((self.root / f"failed-{i}").glob("*.pdf")), [])
            for paper in papers:
                self.assertEqual(literature._file_sha256(literature.pdf_path(paper["id"])), paper["sha256"])
                doc = indexer.get_doc(paper["doc_id"])
                self.assertEqual(doc["revision"], originals[self.root / doc["path"]])

    def test_migration_unwritable_destination_leaves_source_usable(self):
        paper = self.paper()
        old = literature._pdf_dir()
        target = self.root / "unwritable"
        real_open = Path.open

        def denied(path, mode="r", *args, **kwargs):
            if path.parent == target and mode == "xb":
                raise PermissionError("injected read-only destination")
            return real_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", denied), self.assertRaises(PermissionError):
            literature.set_pdf_dir(str(target))
        self.assertEqual(literature._pdf_dir(), old)
        self.assertEqual(literature._file_sha256(literature.pdf_path(paper["id"])), paper["sha256"])

    def test_shared_pdf_rebuild_is_safe_single_full_and_repeated(self):
        shared = self.root / "shared.pdf"
        shared.write_bytes(b"%PDF-1.4\nshared original\n")
        docs = [indexer.create_doc("literature", {"title": f"共享 {i}", "attachment": shared.name}) for i in range(2)]
        annotations = [self.screenshot_annotation("entry-" + doc["id"], f"共享 PDF 的独立批注 {i}") for i, doc in enumerate(docs)]
        literature.rebuild_registry(docs[0]["id"])
        self.assertTrue(shared.exists())
        expected = literature._file_sha256(shared)
        for single in (docs[0]["id"], "", ""):
            literature.rebuild_registry(single)
            for doc, annotation in zip(docs, annotations):
                item = literature.item_for_document(doc["id"])
                self.assertTrue(item["pdf_available"])
                self.assertEqual(literature._file_sha256(literature.pdf_path(item["id"])), expected)
                self.assertEqual(literature.get_annotations(item["id"]), [annotation])
        self.assertEqual(len(list(literature._pdf_dir().glob("*.pdf"))), 2)

    def test_rebuild_does_not_match_unrelated_attachment_by_basename(self):
        paper = self.paper()
        other = self.root / "other"
        other.mkdir()
        source = other / paper["stored_filename"]
        source.write_bytes(b"%PDF-1.4\nunrelated content\n")
        doc = indexer.create_doc("literature", {"title": "不同文件", "attachment": str(source)})
        literature.rebuild_registry(doc["id"])
        item = literature.item_for_document(doc["id"])
        self.assertEqual(literature.pdf_path(item["id"]).read_bytes(), source.read_bytes())
        self.assertEqual(literature._file_sha256(literature.pdf_path(paper["id"])), paper["sha256"])

    def test_reading_position_survives_reload_and_rebuild_for_all_entry_paths(self):
        direct = self.root / "direct.pdf"
        direct.write_bytes(b"%PDF-1.4\ndirect\n")
        doc = indexer.create_doc("literature", {"title": "直接附件", "attachment": direct.name})
        empty = indexer.create_doc("literature", {"title": "待补充"})
        bound = literature.import_pdf("bound.pdf", direct, {"bind_paper_id": "entry-" + empty["id"]})
        papers = [literature.item_for_document(doc["id"]), self.paper(), bound]
        with self.http():
            for paper in papers:
                status, _ = self.request('/api/literature/' + paper["id"], {"last_page": 3, "page_count": 4})
                self.assertEqual(status, 200)
            config.reload_all()
            indexer.rebuild()
            for paper in papers:
                _, item = self.request('/api/literature/' + paper["id"])
                self.assertEqual((item["last_page"], item["page_count"]), (3, 4))
                self.assertTrue(item["pdf_available"])
        literature.rebuild_registry(doc["id"])
        item = literature.item_for_document(doc["id"])
        self.assertEqual((item["last_page"], item["page_count"]), (3, 4))

    def test_pinned_and_favorite_agree_in_both_directions(self):
        paper = self.paper()
        with self.http():
            for value in (True, False, True, False):
                self.request('/api/literature/' + paper["id"], {"favorite": not value})
                self.request('/api/docs/' + paper["doc_id"], {"pinned": value})
                _, item = self.request('/api/literature/' + paper["id"])
                _, rows = self.request('/api/literature')
                self.assertEqual(item["favorite"], value)
                self.assertEqual(rows["items"][0]["favorite"], value)
                self.request('/api/literature/' + paper["id"], {"favorite": not value})
                self.assertEqual(indexer.get_doc(paper["doc_id"])["pinned"], not value)

    def test_invalid_project_updates_have_no_side_effects(self):
        record = projects.create_project("校验前项目")
        projects.create_project("已有项目")
        doc = indexer.create_doc("note", {"title": "关联笔记", "projects": [record["name"]]})
        todos.create({"title": "关联待办", "project_id": record["id"], "project": record["name"]})
        files = [self.root / doc["path"], projects._registry_path(), projects._todos_path()]
        original = {p: p.read_bytes() for p in files}
        with self.http():
            for invalid in ({"name": "不应生效", "status": "INVALID"}, {"name": "已有项目"},
                            {"name": "不应生效", "display_name": "x" * 33}):
                status, _ = self.request('/api/projects/' + record["id"], invalid)
                self.assertEqual(status, 400)
                self.assertTrue((self.root / "Projects" / record["name"]).is_dir())
                self.assertFalse((self.root / "Projects" / "不应生效").exists())
                for path, content in original.items():
                    self.assertEqual(path.read_bytes(), content)
                self.assertEqual(indexer.get_doc(doc["id"])["projects"], [record["name"]])

    def test_project_write_failure_rolls_back_directory_documents_tasks_registry(self):
        record = projects.create_project("原项目")
        doc = indexer.create_doc("note", {"title": "关联笔记", "projects": [record["name"]]})
        todos.create({"title": "任务", "project_id": record["id"], "project": record["name"]})
        files = [self.root / doc["path"], projects._registry_path(), projects._todos_path()]
        original = {p: p.read_bytes() for p in files}
        real_save, real_todos = projects._save_registry, projects._save_todos

        def failed_save(items):
            real_save(items)
            raise OSError("injected registry commit failure")

        def failed_todos(items):
            real_todos(items)
            raise OSError("injected task file failure")

        for failure in (patch.object(projects, "_save_registry", side_effect=failed_save),
                        patch.object(projects, "_save_todos", side_effect=failed_todos),
                        patch.object(Path, "rename", side_effect=PermissionError("injected directory failure"))):
            with failure, self.assertRaises(OSError):
                projects.update_project(record["id"], {"name": "新项目"})
            self.assertTrue((self.root / "Projects" / record["name"]).is_dir())
            self.assertFalse((self.root / "Projects" / "新项目").exists())
            for path, content in original.items():
                self.assertEqual(path.read_bytes(), content)
            indexer.sync(immediate=True)
            self.assertEqual(indexer.get_doc(doc["id"])["projects"], [record["name"]])

    @unittest.skipUnless(os.environ.get("ERW_FUNCTIONAL_UI") == "1", "set ERW_FUNCTIONAL_UI=1")
    def test_annotation_registration_lifecycle_browser(self):
        from pypdf import PdfWriter
        source = self.root / "lifecycle.pdf"
        writer = PdfWriter()
        for _ in range(4):
            writer.add_blank_page(width=595, height=842)
        writer.write(source)
        content = source.read_bytes()
        direct = self.direct_paper("设置页登记批注", content)
        annotation = self.screenshot_annotation(direct["id"])
        _, historical, old_annotation, _ = self.historical_registration(content)
        with self.http():
            subprocess.run(["node", str(functional_tests.ROOT / "tools/literature_lifecycle_ui_check.js"), self.base,
                direct["doc_id"], direct["id"], annotation["id"], historical["id"], old_annotation["id"]],
                cwd=functional_tests.ROOT, check=True, timeout=120)

    @unittest.skipUnless(os.environ.get("ERW_FUNCTIONAL_UI") == "1", "set ERW_FUNCTIONAL_UI=1")
    def test_annotation_draft_browser(self):
        from pypdf import PdfWriter
        source = self.root / "browser.pdf"
        writer = PdfWriter()
        for _ in range(4):
            writer.add_blank_page(width=595, height=842)
        writer.write(source)
        paper = literature.import_pdf(source.name, source)
        other = literature.import_pdf("other.pdf", source)
        annotations = [literature.save_annotation(paper["id"], {"type": "note", "page": 1,
                       "comment": f"saved {i}", "rects": [[.1, .1, .4, .2]]}) for i in range(2)]
        with self.http():
            subprocess.run(["node", str(functional_tests.ROOT / "tools/review_regression_ui_check.js"), self.base,
                            paper["id"], other["id"], *[a["id"] for a in annotations]],
                           cwd=functional_tests.ROOT, check=True, timeout=120)


if __name__ == "__main__":
    unittest.main()
