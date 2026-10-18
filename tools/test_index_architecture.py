"""Architecture regressions using disposable workspaces and real SQLite queries."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config, indexer, store, workspace, agent_tools, literature
from app import perf_index_core as core, perf_index_db as db


class IndexArchitectureTests(unittest.TestCase):
    def test_unmodified_draft_creates_no_files_activity_or_index_rows(self):
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(store.activity, 'record') as record:
            draft = store.prepare_doc('note', {'project':'Not yet created'})
            self.assertTrue(draft['draft'])
            self.assertEqual(draft['path'], '')
            self.assertIn('## 摘要', draft['body'])
            record.assert_not_called()
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(indexer.list_docs('note'), [])
        saved = indexer.create_doc('note', {'title':'Edited draft', 'body':draft['body']+'\nNew result'})
        self.assertFalse(saved.get('draft', False))
        self.assertEqual(len(indexer.list_docs('note')), 1)
        self.assertTrue((self.root / saved['path']).is_file())

    def test_draft_respects_custom_template_and_explicit_empty_body(self):
        with patch.object(store, 'kind_template', return_value='# {{title}}\nDate: {{date}}\n'):
            draft = store.prepare_doc('note', {'title':'Customized'})
        self.assertIn('# Customized', draft['body'])
        self.assertNotIn('{{date}}', draft['body'])
        literature_draft = store.prepare_doc('literature', {})
        self.assertIn('```bibtex', literature_draft['body'])
        self.assertIn('@article', literature_draft['bibtex'])
        saved = indexer.create_doc('note', {'title':'Empty on purpose', 'body':''})
        self.assertEqual(saved['body'].strip(), '')

    def setUp(self):
        core.stop_background_sync()
        self.temp = tempfile.TemporaryDirectory(prefix="erw-index-tests-")
        self.data = Path(self.temp.name)
        self.saved = {name: getattr(config, name) for name in
                      ("ROOT", "CONFIG_DIR", "SECRET_PATH", "LEGACY_SECRET_PATH", "_cache")}
        config.ROOT = self.data
        config.CONFIG_DIR = self.data / "config"
        config.SECRET_PATH = config.CONFIG_DIR / "secret.json"
        config.LEGACY_SECRET_PATH = config.CONFIG_DIR / "secrets.json"
        config.CONFIG_DIR.mkdir()
        (config.CONFIG_DIR / "app.json").write_text(json.dumps({
            "workspace": "Workspace", "workspace_migration": {"enabled": False},
            "llm": {"enabled": False},
        }), encoding="utf-8")
        config._cache = {}
        workspace.reset_runtime_state()
        self.root = workspace.ensure_workspace()
        indexer.initialize()

    def tearDown(self):
        core.stop_background_sync()
        workspace.reset_runtime_state()
        for name, value in self.saved.items():
            setattr(config, name, value)
        self.temp.cleanup()

    def doc(self, title="Alpha", body="", **kwargs):
        return indexer.create_doc("note", {"title": title, "body": body, **kwargs})

    def edges(self):
        with db._connect() as con:
            return {tuple(row) for row in con.execute("SELECT source,target,relation FROM graph_edges")}

    def test_import_does_not_load_or_migrate_config(self):
        code = "import sys; sys.path.insert(0, sys.argv[1]); from app import indexer, config; assert not config._cache"
        subprocess.run([sys.executable, "-c", code, str(ROOT)], cwd=self.data, check=True)

    def test_workspace_initialization_is_cached_and_resettable(self):
        with patch.object(Path, "mkdir", side_effect=AssertionError("repeated mkdir")):
            self.assertEqual(workspace.ensure_workspace(), self.root)
        workspace.reset_runtime_state()
        self.assertTrue(workspace.ensure_workspace().is_dir())

    def test_chinese_short_body_search_and_literal_wildcards(self):
        doc = self.doc(body="padding " * 100 + " 稀疏 100%_cache")
        self.assertEqual(indexer.list_docs(query="稀疏", paged=True)["total"], 1)
        self.assertEqual(indexer.search_docs("稀疏")[0]["id"], doc["id"])
        self.assertEqual(indexer.list_docs(query="100%_cache", paged=True)["total"], 1)
        self.assertEqual(indexer.list_docs(query="does-not-exist", paged=True)["total"], 0)

    def test_crud_updates_fts_and_attachment_immediately(self):
        doc = self.doc(body="olduniqueterm")
        pdf = self.root / "Knowledge" / "Attachments" / "paper.pdf"
        pdf.write_bytes(b"test fixture")
        indexer.update_doc(doc["id"], {"body": "newuniqueterm", "attachment": str(pdf)})
        self.assertFalse(indexer.search_docs("olduniqueterm"))
        self.assertEqual(indexer.search_docs("newuniqueterm")[0]["id"], doc["id"])
        self.assertEqual(indexer.get_doc(doc["id"])["attachment"], str(pdf))
        indexer.delete_doc(doc["id"])
        self.assertFalse(indexer.search_docs("newuniqueterm"))

    def test_incremental_graph_handles_creation_rename_and_delete_fallback(self):
        source = self.doc("Source", "[[Target]] [[Future]]")
        with patch.object(core, "_rebuild_graph_edges", side_effect=AssertionError("full rebuild")):
            target = self.doc("Target", tags=["first"])
            future = self.doc("Future")
            self.assertIn((source["id"], target["id"], "wikilink"), self.edges())
            self.assertIn((source["id"], future["id"], "wikilink"), self.edges())
            duplicate = self.doc("Target")
            indexer.update_doc(duplicate["id"], {"title": "Renamed"})
            self.assertIn((source["id"], target["id"], "wikilink"), self.edges())
            indexer.update_doc(target["id"], {"tags": ["second"]})
            self.assertNotIn((target["id"], "tag:first", "tag"), self.edges())
            self.assertIn((target["id"], "tag:second", "tag"), self.edges())
            result = indexer.delete_docs([target["id"], "missing", future["id"]])
            self.assertEqual(result["deleted"], [target["id"], future["id"]])
            self.assertEqual(result["failed"][0]["id"], "missing")
            self.assertFalse(any(e[1] in {target["id"], future["id"]} for e in self.edges()))
        before = self.edges()
        indexer.sync(force=True)
        self.assertEqual(before, self.edges())

    def test_external_changes_reconcile_without_read_path_scans(self):
        doc = self.doc(body="beforeexternal")
        path = self.root / doc["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("beforeexternal", "afterexternal"), encoding="utf-8")
        with patch.object(core, "_doc_paths", side_effect=AssertionError("read scanned files")):
            self.assertEqual(indexer.list_docs(paged=True)["total"], 1)
            self.assertTrue(indexer.search_docs("beforeexternal"))
        indexer.sync(immediate=True)
        self.assertTrue(indexer.search_docs("afterexternal"))
        self.assertFalse(indexer.search_docs("beforeexternal"))

    def test_readers_do_not_wait_for_scan_writer_lock(self):
        self.doc()
        started, release = threading.Event(), threading.Event()
        original = core._doc_paths
        def blocked(root=None):
            started.set()
            if not release.wait(5):
                raise RuntimeError("test scan timed out")
            yield from original(root)
        errors = []
        def scan():
            try:
                indexer.sync(immediate=True)
            except Exception as exc:
                errors.append(exc)
        with patch.object(core, "_doc_paths", blocked):
            thread = threading.Thread(target=scan)
            thread.start()
            try:
                self.assertTrue(started.wait(2))
                self.assertEqual(indexer.list_docs(paged=True)["total"], 1)
                self.assertTrue(indexer.status()["sync_running"])
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(errors)

    def test_agent_writes_are_visible_to_index_queries(self):
        result = agent_tools._t_kb_create_entry({"kind": "note", "title": "知识-方法-稀疏重构", "body": "agentunique"}, {"write_mode": "direct"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(indexer.search_docs("agentunique")[0]["id"], result["doc_id"])
        agent_tools._t_kb_update_entry({"doc_id": result["doc_id"], "body": "agentupdated"}, {"write_mode": "direct"})
        self.assertTrue(indexer.search_docs("agentupdated"))

    def test_literature_batch_uses_index_metadata_without_reading_bodies(self):
        doc = indexer.create_doc("literature", {"title": "New title", "authors": "New author"})
        rows = [{"doc_id": doc["id"], "title": "Stale title"}]
        with patch.object(store, "_doc_from_path", side_effect=AssertionError("list read a body")):
            literature._join_doc_meta_batch(rows)
        self.assertEqual(rows[0]["title"], "New title")
        self.assertEqual(rows[0]["authors"], "New author")

    def test_connection_closes_and_list_sort_uses_index(self):
        with db._connect() as con:
            plans = [str(r[3]) for r in con.execute("EXPLAIN QUERY PLAN SELECT * FROM documents ORDER BY pinned DESC, COALESCE(NULLIF(updated,''),created) DESC,id DESC LIMIT 50")]
        with self.assertRaises(sqlite3.ProgrammingError):
            con.execute("SELECT 1")
        self.assertFalse(any("TEMP B-TREE" in plan for plan in plans), plans)

    def test_rebuild_preserves_old_snapshot_until_commit(self):
        self.doc(body="snapshotunique")
        entered, release = threading.Event(), threading.Event()
        original = core._doc_paths
        errors = []
        def blocked(root=None):
            entered.set()
            release.wait(5)
            yield from original(root)
        def rebuild():
            try:
                indexer.rebuild()
            except Exception as exc:
                errors.append(exc)
        with patch.object(core, "_doc_paths", blocked):
            thread = threading.Thread(target=rebuild)
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(indexer.search_docs("snapshotunique"))
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(errors)
        self.assertTrue(indexer.search_docs("snapshotunique"))

    def test_schema_upgrade_and_interrupted_rebuild_recover(self):
        self.doc(body="migrationunique")
        core.stop_background_sync()
        with db._connect() as con:
            con.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
            con.execute("UPDATE documents_fts SET rowid=rowid+100")
        db._SCHEMA_READY.pop(str(db._db_path()), None)
        with db._connect() as con:
            self.assertTrue(db._init_db(con))
            self.assertEqual(con.execute("SELECT COUNT(*) FROM documents_fts").fetchone()[0], 0)
        # Simulate restarting after schema migration but before indexing files.
        core._READY_ROOTS.discard(str(self.root))
        indexer.initialize()
        self.assertTrue(indexer.search_docs("migrationunique"))
        with db._connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM documents_fts f JOIN documents d ON f.rowid=d.rowid AND f.doc_id=d.id").fetchone()[0], 1)

    def test_related_dictionary_reused_until_document_change(self):
        self.doc(title="稀疏重构", tags=["稀疏"])
        self.assertTrue(store.match_related("本页讨论稀疏重构方法的应用"))
        with patch.object(indexer, "document_metadata", side_effect=AssertionError("reloaded dictionary")):
            self.assertTrue(store.match_related("本页讨论稀疏重构方法的应用"))
        self.doc(title="图谱索引")
        self.assertTrue(store.match_related("图谱索引用于关联文档"))

    def test_malformed_external_todos_keep_last_good_index(self):
        from app import todos
        todo = todos.create({"title": "Preserve me"})
        indexer.refresh_todos()
        (self.root / "System" / "todos.json").write_text('{"partial":', encoding="utf-8")
        indexer.sync(immediate=True)
        self.assertEqual(indexer.list_todos()[0]["id"], todo["id"])

    def test_project_name_and_id_edits_replace_or_clear_associations(self):
        from app import projects
        first = projects.create_project("First")
        second = projects.create_project("Second")
        doc = self.doc(projects=["First"])
        self.assertEqual(doc["project_ids"], [first["id"]])
        updated = indexer.update_doc(doc["id"], {"project": "Second"})
        self.assertEqual(updated["project_ids"], [second["id"]])
        updated = indexer.update_doc(doc["id"], {"projects": []})
        self.assertEqual(updated["project_ids"], [])
        self.assertEqual(updated["projects"], [])
        updated = indexer.update_doc(doc["id"], {"project_id": first["id"]})
        self.assertEqual(updated["projects"], ["First"])
        self.assertIn((doc["id"], "project:" + first["id"], "project"), self.edges())

    def test_file_is_reconciled_after_failed_index_write(self):
        doc = self.doc(body="beforefailure")
        with patch.object(core, "_index_path_conn", side_effect=sqlite3.OperationalError("simulated write failure")):
            with self.assertRaises(sqlite3.OperationalError):
                indexer.update_doc(doc["id"], {"body": "afterfailure"})
        self.assertIn("afterfailure", (self.root / doc["path"]).read_text(encoding="utf-8"))
        indexer.sync(immediate=True)
        self.assertTrue(indexer.search_docs("afterfailure"))
        self.assertFalse(indexer.search_docs("beforefailure"))


class _WithoutFts5(db._Connection):
    """Keep real SQLite transactions/queries but model Android's absent module."""

    def execute(self, sql, *args, **kwargs):
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("create virtual table") and "using fts5(" in normalized:
            raise sqlite3.OperationalError("no such module: fts5")
        return super().execute(sql, *args, **kwargs)


class WithoutFts5Tests(IndexArchitectureTests):
    def setUp(self):
        unavailable = patch.object(db, "_Connection", _WithoutFts5)
        unavailable.start()
        self.addCleanup(unavailable.stop)
        super().setUp()

    def test_search_survives_reopen_and_rebuild_without_fts5(self):
        doc = self.doc(body="padding " * 100 + " Android 全文验证 100%_cache")
        self.assertEqual(indexer.status()["fts_tokenizer"], "like")
        for query in ("全文验证", "全文", "Android", "100%_cache"):
            self.assertEqual(indexer.search_docs(query)[0]["id"], doc["id"])
            self.assertEqual(indexer.list_docs(query=query, paged=True)["total"], 1)
        db._SCHEMA_READY.pop(str(db._db_path()), None)
        indexer.initialize()
        self.assertEqual(indexer.status()["fts_tokenizer"], "like")
        indexer.rebuild()
        self.assertEqual(indexer.search_docs("全文验证")[0]["id"], doc["id"])

    def test_missing_search_table_is_rebuilt_from_existing_markdown(self):
        doc = self.doc(body="recover-from-incomplete-first-start")
        with db._connect() as con:
            con.execute("DROP TABLE documents_fts")
        db._SCHEMA_READY.pop(str(db._db_path()), None)
        indexer.initialize()
        self.assertEqual(indexer.search_docs("incomplete-first-start")[0]["id"], doc["id"])


if __name__ == "__main__":
    unittest.main()
