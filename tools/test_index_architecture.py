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
from app import activity


class IndexArchitectureTests(unittest.TestCase):
    def test_unified_literature_preserves_missing_pdf_records_and_binds_in_place(self):
        document = indexer.create_doc("literature", {"title": "原始文献", "body": "# 原笔记\n\n真实内容与引用 [[Alpha]]", "authors": "原作者", "projects": ["研究项目"]})
        paper = literature.item_for_document(document["id"])
        self.assertFalse(paper["pdf_available"])
        self.assertEqual(literature.list_items(pdf="missing")["total"], 1)
        source = self.root / "test.pdf"
        source.write_bytes(b"%PDF-1.4\n% disposable import fixture\n")
        linked = literature.import_pdf("原论文.pdf", source, {"bind_paper_id": paper["id"]})
        self.assertEqual(linked["id"], paper["id"])
        self.assertEqual(linked["doc_id"], document["id"])
        self.assertTrue(linked["pdf_available"])
        self.assertEqual(literature.get_note(linked["id"]).strip(), document["body"].strip())
        self.assertEqual(literature.list_items()["total"], 1)
        self.assertEqual(literature.list_items(pdf="available")["total"], 1)
        self.assertEqual(literature.list_items(pdf="missing")["total"], 0)
        literature.update_item(linked["id"], {"authors": "修改后的作者", "projects": [], "favorite": True, "reading_status": "已读", "url": "https://example.invalid/source", "added_date": "2026-10-21"})
        saved = indexer.get_doc(document["id"])
        self.assertEqual(saved["authors"], "修改后的作者")
        self.assertEqual(saved["projects"], [])
        self.assertEqual(saved["status"], "已精读")
        self.assertTrue(saved["pinned"])
        self.assertEqual(literature.item_for_document(document["id"])["id"], paper["id"])
        before = set(literature._pdf_dir().iterdir())
        with self.assertRaises(ValueError):
            literature.import_pdf("duplicate.pdf", source, {"bind_paper_id": paper["id"]})
        self.assertEqual(set(literature._pdf_dir().iterdir()), before)

    def test_literature_note_revision_rejects_overwrite_without_losing_draft(self):
        import hashlib
        document = indexer.create_doc("literature", {"title": "笔记并发测试", "body": "原笔记"})
        paper = literature.item_for_document(document["id"])
        original = literature.get_note(paper["id"])
        revision = hashlib.sha256(original.encode()).hexdigest()
        first = literature.save_note(paper["id"], "新笔记", revision)
        with self.assertRaises(ValueError):
            literature.save_note(paper["id"], "旧客户端的草稿", revision)
        self.assertEqual(literature.get_note(paper["id"]).strip(), "新笔记")
        literature.save_note(paper["id"], "再更新", first["revision"])
        self.assertEqual(literature.get_note(paper["id"]).strip(), "再更新")

    def test_literature_note_replacement_preserves_legacy_bibtex_metadata(self):
        bib = '@article{original, title={Original source}}'
        document = indexer.create_doc("literature", {"title": "原始文献", "body": f"# 阅读笔记\n\n```bibtex\n{bib}\n```\n\n原文摘记"})
        path = self.root / document["path"]
        meta, body = store._frontmatter_parse(path.read_text(encoding="utf-8"))
        meta.pop("bibtex", None)
        path.write_text(store._frontmatter_dump(meta) + body, encoding="utf-8")
        paper = literature.item_for_document(document["id"])
        literature.save_note(paper["id"], "# AI 整理后的新笔记")
        self.assertEqual(literature.get_item(paper["id"])["bibtex"], bib)
        self.assertEqual(literature.get_note(paper["id"]).strip(), "# AI 整理后的新笔记")
        literature.update_item(paper["id"], {"bibtex": "@article{updated}"})
        self.assertEqual(literature.get_note(paper["id"]).strip(), "# AI 整理后的新笔记")
        self.assertEqual(literature.get_item(paper["id"])["bibtex"], "@article{updated}")

    def test_milestone_schedule_roundtrip_validation_and_clear(self):
        from app import milestones
        doc = indexer.create_doc("milestone", {"title": "跨月实验阶段", "projects": ["测试项目"], "body": "验收条件保持不变", "start_date": "2026-10-25", "due": "2026-11-20", "progress": 37.5})
        self.assertEqual(doc["progress"], 37.5)
        path = self.root / doc["path"]
        original = path.read_bytes()
        for payload in ({"due": "2026-10-01"}, {"start_date": "2026-02-30"}, {"progress": -1}, {"progress": 101}, {"progress": float("nan")}, {"progress": True}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                indexer.update_doc(doc["id"], payload)
            self.assertEqual(path.read_bytes(), original, "invalid plans must not overwrite Markdown")
        indexer.update_doc(doc["id"], {"title": "修改标题"})
        self.assertEqual(indexer.get_doc(doc["id"])["progress"], 37.5)
        cleared = indexer.update_doc(doc["id"], {"start_date": "", "progress": None})
        self.assertEqual(cleared["start_date"], "")
        self.assertIsNone(cleared["progress"])
        self.assertEqual(cleared["body"].strip(), "验收条件保持不变")
        planned = milestones.plan()["items"][0]
        self.assertIsNone(planned["progress"])
        self.assertNotIn("body", planned)
        indexer.update_doc(doc["id"], {"due": ""})
        self.assertEqual(milestones.plan()["items"][0]["due"], "")

    def test_milestone_plan_includes_all_pages_and_legacy_points(self):
        from app import milestones
        directory = self.root / "Knowledge/Milestones"
        for number in range(205):
            meta = {"id": f"plan-{number}", "kind": "milestone", "title": f"测试节点 {number}", "due": "2026-11-01", "status": "计划", "projects": ["合成评测项目"]}
            (directory / f"plan-{number}.md").write_text(store._frontmatter_dump(meta) + "# 测试\n", encoding="utf-8")
        indexer.sync(immediate=True)
        self.assertEqual(len(indexer.list_docs("milestone", page_size=200)), 200)
        plan = milestones.plan()
        self.assertEqual(plan["total"], 205)
        self.assertEqual(plan["unavailable"], 0)
        self.assertEqual(len({d["id"] for d in plan["items"]}), 205)
        self.assertTrue(all(d["start_date"] == "" and d["progress"] is None for d in plan["items"]))
        indexer.delete_doc("plan-204")
        self.assertEqual(milestones.plan()["total"], 204)

    def test_retrieval_prioritizes_exact_source_over_newer_project_matches(self):
        title = "物理信息引导思维树搜索的大模型负荷转供方法"
        source = indexer.create_doc("literature", {"title": "文献-" + title, "body": "世界模型使用确定性物理求解器更新状态。", "projects": [title]})
        indexer.update_doc(source["id"], {"updated": "2000-01-01"})
        for i in range(12):
            indexer.create_doc("literature", {"title": f"文献-同项目其他资料{i}", "body": "其他研究内容", "projects": [title]})
        result = indexer.retrieve_docs(title, kind="literature", limit=8)
        self.assertEqual(result["total"], 13)
        self.assertEqual(result["items"][0]["id"], source["id"])
        self.assertEqual(indexer.resolve_doc("[[文献-" + title + "|组会原文]]")["id"], source["id"])
        self.assertEqual(indexer.resolve_doc(title)["id"], source["id"])
        self.assertEqual(indexer.resolve_doc(source["id"])["id"], source["id"])
        self.assertEqual(indexer.retrieve_docs(source["id"])["items"][0]["id"], source["id"])
        self.assertEqual(agent_tools.execute("kb_read", {"title": "文献-" + title})["id"], source["id"])
        with self.assertRaises(FileNotFoundError):
            indexer.resolve_doc("不存在的引用")

    def test_retrieval_splits_concepts_and_prefers_content_over_project_only(self):
        self.doc("项目导航", projects=["世界模型 world model"])
        wanted = self.doc("世界模型", body="world model 用于规划；确定性求解器负责状态计算。")
        result = indexer.retrieve_docs("世界模型 world model", limit=8)
        self.assertEqual(result["items"][0]["id"], wanted["id"])
        self.assertIn("world", result["terms"])
        self.assertEqual(indexer.retrieve_docs("职责 求解器")["items"][0]["id"], wanted["id"])
        self.assertTrue(indexer.retrieve_docs("\"world\" OR 'model' OR")['items'])

    def test_activity_index_deduplicates_imports_and_preserves_legacy_multiplicity(self):
        path = self.root / 'System/activity.jsonl'
        event = {'timestamp':'2026-10-01T09:00:00', 'type':'doc_update', 'ref':'old', 'weight':3}
        line = json.dumps(event) + '\n'
        path.write_text(line * 2, encoding='utf-8')
        indexer.sync(immediate=True)
        legacy = activity.list_events(root=self.root)
        activity.record('doc_create', timestamp='2026-10-02T09:00:00', weight=2, root=self.root)
        imported = activity.list_events(root=self.root)[-1]
        with path.open('a', encoding='utf-8') as target:
            for item in [*legacy, imported, imported]:
                target.write(json.dumps(item) + '\n')
        indexer.sync(immediate=True)
        with db._connect() as conn:
            self.assertEqual(conn.execute('SELECT SUM(count) FROM activity_daily').fetchone()[0], 8)
        indexer.sync(force=True)
        with db._connect() as conn:
            self.assertEqual(conn.execute('SELECT SUM(count) FROM activity_daily').fetchone()[0], 8)

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

    def test_mcp_bridge_loads_and_updates_through_index(self):
        from mcp.bridge import Workbench
        from app import versions
        bridge = Workbench()
        doc = bridge.create_entry('note', {'title': 'MCP merge regression', 'body': 'mcpbefore'},
                                  origin=versions.origin('mcp', 'kb_create_entry'))
        bridge.update_entry(doc['id'], {'body': 'mcpafter'},
                            origin=versions.origin('mcp', 'kb_update_entry'))
        self.assertTrue(bridge.search('mcpafter'))
        self.assertFalse(bridge.search('mcpbefore'))
        self.assertEqual(bridge.get_entry(doc['id'])['origin_surface'], 'mcp')

    def test_store_delete_moves_file_to_trash(self):
        doc = self.doc(body='trashregression')
        source = self.root / doc['path']
        store.delete_doc(doc['id'])
        self.assertFalse(source.exists())
        self.assertTrue(list((self.root / 'System/Trash').rglob('*-' + source.name)))

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
        read = agent_tools._t_kb_read({"doc_id": result["doc_id"]}, {})
        update = agent_tools._t_kb_update_entry({"doc_id": result["doc_id"], "body": "agentupdated", "expected_version": read["version"]}, {"write_mode": "direct"})
        self.assertTrue(update["ok"], update)
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

    def test_paper_title_project_keeps_full_name_and_single_association(self):
        from app import projects
        name = "Two-stage fine-tuning of large language models for distribution network service restoration via CoT reasoning"
        project = projects.create_project(name)
        doc = self.doc(projects=[name])
        projects.ensure_registry()
        self.assertEqual(project["name"], name)
        self.assertEqual(indexer.get_doc(doc["id"])["projects"], [name])
        self.assertEqual(indexer.get_doc(doc["id"])["project_ids"], [project["id"]])
        self.assertEqual([p["name"] for p in indexer.project_records()], [name])
        self.assertTrue((self.root / "Projects" / name).is_dir())
        self.assertFalse((self.root / "Projects" / name[:100]).exists())

    def test_file_is_reconciled_after_failed_index_write(self):
        doc = self.doc(body="beforefailure")
        with patch.object(core, "_index_path_conn", side_effect=sqlite3.OperationalError("simulated write failure")):
            with self.assertRaises(sqlite3.OperationalError):
                indexer.update_doc(doc["id"], {"body": "afterfailure"})
        self.assertIn("afterfailure", (self.root / doc["path"]).read_text(encoding="utf-8"))
        indexer.sync(immediate=True)
        self.assertTrue(indexer.search_docs("afterfailure"))
        self.assertFalse(indexer.search_docs("beforefailure"))


if __name__ == "__main__":
    unittest.main()
