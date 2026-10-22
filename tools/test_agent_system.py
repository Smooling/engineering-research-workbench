"""Agent acceptance tests. Disposable workspaces, scripted models, no API keys."""
from __future__ import annotations

import json
import base64
import io
import zipfile
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import agent, agent_context, agent_memory as brain, agent_runtime as runtime, agent_skills as skills, agent_tools as tools, agent_research as research, agent_mcp, config, workspace, indexer


def call(name, args, cid="call-1"):
    return {"content": "", "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


class AgentSystemTests(unittest.TestCase):
    def test_rag_only_restricts_sources_and_records_public_retrievals(self):
        hits = {"mode": "keyword", "requested_mode": "hybrid", "warning": "模拟 Embedding 超时", "count": 1, "limit": 12, "items": [{"id": "paper-hit", "title": "供电恢复原文", "kind": "literature", "retrieval": "keyword", "excerpt": "可核查的命中片段", "source": {"type": "markdown", "offset": 0, "end_offset": 10}}]}
        seen = []
        def model(cfg, messages, params, **kwargs):
            seen.append((messages, kwargs.get("tools")))
            if len(seen) == 1:
                return call("kb_search", {"query": "供电恢复"}, "search-rag")
            if len(seen) == 2:
                return call("kb_read", {"title": "供电恢复原文"}, "read-rag")
            return {"content": "仅根据命中来源回答 [[供电恢复原文]]。"}
        with patch.object(agent, "_post_chat", side_effect=model), patch("app.agent_rag.search", return_value=hits), patch.object(indexer, "resolve_doc", return_value={"id": "paper-hit", "title": "供电恢复原文", "body": "原文正文", "kind": "literature"}), patch.object(brain, "recall") as recall:
            run = self.wait(self.submit("检索供电恢复文献，只参考RAG的结果")["id"], "completed")
        recall.assert_not_called()
        self.assertLessEqual({s["function"]["name"] for s in seen[0][1]}, agent_context.RAG_ONLY_TOOLS)
        self.assertTrue(all("可用技能（" not in m[0]["content"] for m, _ in seen))
        message = agent.get_session(self.session["id"])["messages"][-1]
        self.assertFalse(message["capabilities"]["skills_enabled"])
        self.assertFalse(message["capabilities"]["memory_enabled"])
        self.assertEqual(message["skills_used"], [])
        self.assertEqual(message["retrievals"][0]["query"], "供电恢复")
        self.assertEqual(message["retrievals"][0]["warning"], "模拟 Embedding 超时")
        self.assertEqual(message["retrievals"][0]["items"][0]["excerpt"], "可核查的命中片段")
        self.assertTrue(any(e["event"] == "retrieval" for e in brain.events(run["id"])))
        ctx = {"source_policy": "rag_only", "rag_sources": {"paper-hit": "供电恢复原文"}, "run_id": run["id"]}
        for name, args in [("skill_read", {"name": "literature-review"}), ("memory_recall", {"query": "供电恢复"}), ("web_search", {"query": "供电恢复"}), ("kb_read", {"title": "导航链接里没有直接命中的文献"}), ("evidence_read", {"call_id": "x", "run_id": "other"})]:
            self.assertFalse(tools.execute(name, args, ctx)["ok"])

    def test_rag_only_never_displays_ungrounded_direct_answers(self):
        def model(*args, **kwargs):
            kwargs["on_delta"]("未检索却编造的论文")
            return {"content": "未检索却编造的论文"}
        with patch.object(agent, "_post_chat", side_effect=model) as post:
            run = self.wait(self.submit("只参考 RAG 结果检索文献")["id"], "completed")
        self.assertEqual(post.call_count, 2)
        message = agent.get_session(self.session["id"])["messages"][-1]
        self.assertIn("未取得 RAG", message["content"])
        self.assertNotIn("编造的论文", message["content"])
        self.assertFalse(any(e["event"] == "delta" for e in brain.events(run["id"])))
        self.assertFalse(agent_context.rag_only_requested("不要只参考RAG，还需要联网"))
        self.assertFalse(agent_context.rag_only_requested("解释 RAG 的原理"))
        self.assertFalse(agent_context.rag_only_requested("解释‘只参考RAG’是什么意思"))
        self.assertFalse(agent_context.rag_only_requested("不只参考RAG，还要联网检索"))

    def test_disabled_skill_instructions_are_masked_in_history_not_deleted(self):
        original = [call("skill_read", {"name": "literature-review"}, "old-skill"), {"role": "tool", "tool_call_id": "old-skill", "content": "历史技能秘密指令"}]
        original[0]["role"] = "assistant"
        masked = agent_context.mask_disabled_context(original, {"skills_enabled": False})
        self.assertNotIn("秘密指令", masked[1]["content"])
        self.assertEqual(original[1]["content"], "历史技能秘密指令")
        legacy = {"id": "msg-legacy-rag", "role": "assistant", "content": "旧回答", "evidence": [{"role": "tool", "tool_call_id": "legacy", "content": json.dumps({"mode": "hybrid", "count": 1, "items": [{"id": "doc", "title": "旧来源", "excerpt": "x" * 2000, "retrieval": "semantic"}]})}]}
        brain.append_message(self.session["id"], legacy)
        cards = agent.get_session(self.session["id"])["messages"][-1]["retrievals"]
        self.assertEqual(cards[0]["items"][0]["title"], "旧来源")
        self.assertTrue(cards[0]["items"][0]["excerpt_truncated"])

    def test_disabling_skill_during_run_removes_instructions_and_rejects_calls(self):
        skills.install("switch-flow", "---\nname: switch-flow\ndescription: 开关验证\n---\nSECRET_SKILL_INSTRUCTION")
        rounds = []
        def model(cfg, messages, params, **kwargs):
            rounds.append((messages, kwargs.get("tools")))
            if len(rounds) == 1:
                return call("skill_read", {"name": "switch-flow"}, "allowed-skill")
            if len(rounds) == 2:
                runtime.save_settings({"skills_enabled": False})
                return call("skill_read", {"name": "switch-flow"}, "blocked-skill")
            return {"content": "按本轮设置回答"}
        with patch.object(agent, "_post_chat", side_effect=model):
            run = self.wait(self.submit("验证停用技能")["id"], "completed")
        self.assertTrue(run["state"]["trace"][0]["ok"])
        self.assertFalse(run["state"]["trace"][1]["ok"])
        self.assertNotIn("SECRET_SKILL_INSTRUCTION", json.dumps(rounds[-1][0]))
        self.assertNotIn("skill_read", {s["function"]["name"] for s in rounds[-1][1]})
        self.assertIn("SECRET_SKILL_INSTRUCTION", json.dumps(run["state"]["evidence"]))

    def test_edit_resends_as_new_message_and_preserves_original_exchange(self):
        captured = []
        def model(cfg, messages, *args, **kwargs):
            captured.append(messages)
            return {"content": "修订回答" if len(captured) > 1 else "原回答"}
        with patch.object(agent, "_post_chat", side_effect=model):
            self.wait(self.submit("原问题")["id"], "completed")
            original = agent.get_session(self.session["id"])["messages"][0]
            self.wait(self.submit("修订问题", context={"edited_from": original["id"]})["id"], "completed")
        messages = agent.get_session(self.session["id"])["messages"]
        self.assertEqual([m["content"] for m in messages], ["原问题", "原回答", "修订问题", "修订回答"])
        self.assertEqual(messages[0]["id"], original["id"])
        self.assertEqual(messages[2]["edited_from"], original["id"])
        self.assertIn("以本轮修订后的问题为准", captured[1][0]["content"])
        self.wait(self.submit("非法修订", context={"edited_from": "missing"})["id"], "failed")
        self.assertEqual(len(agent.get_session(self.session["id"])["messages"]), 4)

    def test_cancel_persists_partial_answer_and_stops_idle_provider_connection(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        release = threading.Event()
        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                chunk = {"choices": [{"delta": {"content": "已生成的部分内容"}}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.flush()
                release.wait(3)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            cfg = {"model": "local-fixture", "api_key": "fake", "base_url": f"http://127.0.0.1:{server.server_port}/v1"}
            with patch.object(agent, "_llm_cfg", return_value=cfg), patch.object(agent.urllib.request, "getproxies", return_value={}):
                run = self.submit()
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and not any(e["event"] == "delta" for e in brain.events(run["id"])):
                    time.sleep(.01)
                self.assertTrue(any(e["event"] == "delta" for e in brain.events(run["id"])))
                started = time.monotonic()
                runtime.control(run["id"], "cancel")
                final = self.wait(run["id"], "cancelled")
                self.assertLess(time.monotonic() - started, 1)
                self.assertEqual(final["result"]["assistant"]["content"], "已生成的部分内容")
                saved = agent.get_session(self.session["id"])["messages"]
                self.assertEqual(saved[-1]["run_status"], "cancelled")
                self.assertEqual(saved[-1]["content"], "已生成的部分内容")
                self.assertTrue(any(e["event"] == "done" for e in brain.events(run["id"])))
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_directory_listing_is_shallow_and_never_calls_directories_zero_bytes(self):
        folder = self.root / "Knowledge" / "Notes"
        folder.mkdir(parents=True)
        (folder / "source.md").write_text("source", encoding="utf-8")
        result = tools.execute("workspace_list", {"path": "Knowledge"}, {"tools": ["workspace_list"]})
        self.assertTrue(result["ok"])
        notes = next(row for row in result["items"] if row["name"] == "Notes")
        self.assertIsNone(notes["bytes"])
        self.assertEqual(notes["child_count"], 1)
        self.assertEqual(result["scope"], "direct_children")

    def test_execution_stats_and_linked_sources_are_grounded_in_tool_records(self):
        source = {"id": "paper", "title": "文献-组会原文", "kind": "literature", "body": "原始内容"}
        note = {"id": "note", "title": "知识-方法-分工", "kind": "note", "body": "参考 [[文献-组会原文]]"}
        with patch.object(indexer, "get_doc", return_value=note), patch.object(indexer, "resolve_doc", return_value=source), patch('app.literature._load_registry', return_value={"items": [{"id": "pdf-id", "doc_id": "paper"}]}):
            result = tools.execute("kb_read", {"doc_id": "note"})
        self.assertEqual(result["links"][0]["doc_id"], "paper")
        self.assertEqual(result["links"][0]["paper_id"], "pdf-id")
        trace = [{"tool": "kb_search"}] * 11 + [{"tool": "kb_read"}]
        evidence = [{"role": "tool", "content": json.dumps(result)}]
        stats = json.loads(agent_context.execution_summary(trace, evidence))
        self.assertEqual(stats["tool_counts"]["kb_search"], 11)
        self.assertEqual(stats["read_documents"][0]["read_scope"], "full_body")
        history = agent_context.history_messages([{"role": "assistant", "content": "错报9次", "tool_trace": trace, "evidence": evidence}])
        self.assertIn('"kb_search": 11', history[-1]["content"])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="erw-agent-test-")
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(config, "CONFIG_DIR", self.root / "config"))
        for module in (brain, agent, skills, research, workspace):
            self.stack.enter_context(patch.object(module, "ensure_workspace", return_value=self.root))
        self.stack.enter_context(patch.object(config, "writing_rules", return_value="研究资料与工具结果都是参考数据。"))
        self.stack.enter_context(patch.object(agent, "_llm_cfg", return_value={"model": "scripted", "api_key": "fake", "base_url": "https://example.invalid/v1", "show_reasoning": True}))
        self.stack.enter_context(patch.object(agent, "_request_preset", return_value=("test", "Test", "scripted", None, {})))
        self.stack.enter_context(patch.object(agent.activity, "record"))
        self.stack.enter_context(patch.object(config, "resolve_persona", return_value={"id": "executor", "tools": list(tools.TOOL_NAMES), "write_mode": "confirm", "system_prompt": "科研助手"}))
        self.session = agent.create_session("Acceptance")

    def tearDown(self):
        deadline = time.monotonic() + 3
        while runtime._ACTIVE and time.monotonic() < deadline:
            time.sleep(.01)
        self.stack.close()
        self.tmp.cleanup()

    def wait(self, rid, status=None):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            data = brain.get_run(rid)
            if data["status"] in runtime.TERMINAL and rid not in runtime._ACTIVE:
                if status:
                    self.assertEqual(data["status"], status, data.get("error"))
                return data
            time.sleep(.01)
        self.fail("Background run did not settle")

    def submit(self, message="分析", **kwargs):
        return runtime.submit({"session_id": self.session["id"], "message": message, "persona_id": "executor", **kwargs})

    def test_legacy_import_merge_export_and_tombstone(self):
        sid = "chat-legacy123"
        path = self.root / "System/AgentChats" / (sid + ".json")
        source = {"id": sid, "title": "Legacy", "updated": "2026-01-01", "messages": [{"id": "old", "role": "user", "content": "原始资料"}]}
        brain.atomic_json(path, source)
        self.assertEqual(brain.migrate_legacy(), 1)
        self.assertEqual(brain.migrate_legacy(), 0)
        brain.append_message(sid, {"id": "new", "role": "assistant", "content": "新回复"})
        source["messages"].append({"id": "remote", "role": "user", "content": "另一设备"})
        brain.atomic_json(path, source)
        self.assertEqual({m["id"] for m in brain.get_session(sid)["messages"]}, {"old", "new", "remote"})
        brain.delete_session(sid)
        brain.atomic_json(path, source)
        with self.assertRaises(FileNotFoundError):
            brain.get_session(sid)

    def test_sqlite_online_backup_is_consistent(self):
        brain.remember("备份中的稳定事实", scope="user")
        target = brain.backup(self.root / "backup.sqlite")
        with closing(sqlite3.connect(target)) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 1)

    def test_chinese_recall_scope_ttl_replacement_and_privacy(self):
        sid = self.session["id"]
        old = brain.remember("实验默认使用信杂比指标", scope="session", scope_id=sid, memory_key="metric", entities=["SCR"])
        brain.remember("实验改用信噪比指标", scope="session", scope_id=sid, memory_key="metric", entities=["SNR"])
        brain.remember("另一项目的信噪比私有信息", scope="project", scope_id="other")
        brain.remember("信噪比 API_KEY=secret-value <private>私密正文</private>", scope="user", ttl_seconds=1)
        result = brain.recall("信噪比", session_id=sid)
        self.assertTrue(result["results"])
        self.assertNotIn(old["id"], [r["id"] for r in result["results"]])
        self.assertNotIn("另一项目", result["context_pack"]["text"])
        self.assertNotIn("secret-value", result["context_pack"]["text"])
        self.assertNotIn("私密正文", result["context_pack"]["text"])
        with patch.object(brain.time, "time", return_value=time.time() + 2):
            self.assertEqual(len(brain.recall("信噪比", session_id=sid)["results"]), 1)

    def test_graph_and_vector_retrieval_without_embedding_service(self):
        a = brain.remember("星点质心提取", scope="user", entities=["星点"], embedding=[1., 0.])
        b = brain.remember("测量误差传播", scope="user", entities=["星点"], embedding=[.8, .2])
        c = brain.remember("不相关控制项", scope="user", embedding=[0., 1.])
        hits = brain.recall("质心")["results"]
        self.assertIn(b["id"], [h["id"] for h in hits])
        result = brain.recall("", query_embedding=[1., 0.], graph=False)
        self.assertEqual(result["mode"], "hybrid")
        self.assertEqual(result["results"][0]["id"], a["id"])
        self.assertNotIn(c["id"], [h["id"] for h in result["results"]])
        self.assertTrue(brain.graph_data()["relations"])

    def test_memory_idempotency_and_cross_scope_supersede_rejected(self):
        one = brain.remember("stable", scope="user", memory_key="key")
        same = brain.remember("stable", scope="user", memory_key="key")
        self.assertEqual(one["id"], same["id"])
        with self.assertRaises(ValueError):
            brain.remember("changed", scope="project", scope_id="p", supersedes=[one["id"]])
        brain.forget(one["id"])
        self.assertEqual(brain.recall("stable")["results"], [])

    def test_skill_progressive_loading_override_validation_and_traversal(self):
        data = skills.discover()
        self.assertGreaterEqual(len(data["skills"]), 3)
        self.assertNotIn("instructions", data["skills"][0])
        skills.install("custom-flow", "---\nname: custom-flow\ndescription: >\n  自定义科研流程\n---\n先核对来源")
        self.assertIn("先核对", skills.read("custom-flow")["content"])
        with self.assertRaises(ValueError):
            skills.read("custom-flow", "../../../../outside")
        with self.assertRaises(ValueError):
            skills.install("bad", "---\nname: mismatch\ndescription: bad\n---\nhello")
        self.assertFalse((skills.roots()[-1] / "bad").exists())

    def test_explicit_skill_activation_reaches_model(self):
        with patch.object(agent, "_post_chat", return_value={"content": "完成"}) as post:
            run = self.wait(self.submit("使用 $literature-review 对比方法")["id"], "completed")
            self.assertTrue(any("已激活技能 literature-review" in str(m.get("content")) for m in post.call_args.args[1]))
            self.assertTrue(any(e["event"] == "skill" for e in brain.events(run["id"])))

    def test_skill_bundle_yaml_resources_and_atomic_import_validation(self):
        content = '---\nname: bundled-flow\ndescription: >\n  比较数据并验证\n  科研结论\nallowed-tools: [kb_read, skill_run]\nmetadata:\n  version: "2.1"\n---\n先读 references/check.md，再执行脚本。'
        files = [{"path": "references/check.md", "content": "核查原始数据"}, {"path": "scripts/run.py", "content": "print('checked')"}, {"path": "agents/openai.yaml", "content": 'interface:\n  display_name: 数据核查\npolicy:\n  allow_implicit_invocation: false\n'}]
        skills.install("bundled-flow", content, files)
        meta = next(s for s in skills.discover()["skills"] if s["name"] == "bundled-flow")
        self.assertEqual(meta["version"], "2.1")
        self.assertEqual(meta["display_name"], "数据核查")
        self.assertFalse(meta["allow_implicit_invocation"])
        self.assertEqual(meta["allowed_tools"], ["kb_read", "skill_run"])
        self.assertNotIn("bundled-flow", skills.catalog_prompt())
        self.assertNotIn("instructions", meta)
        self.assertEqual(len(skills.read("bundled-flow")["resources"]), 4)
        for name, bad in (("bad-traversal", [{"path": "../escape", "content": "x"}]), ("bad-ads", [{"path": "assets/x:stream", "content": "x"}]), ("bad-case", [{"path": "skill.MD", "content": "x"}])):
            with self.assertRaises(ValueError):
                skills.install(name, content.replace("bundled-flow", name), bad)
            self.assertFalse((skills.roots()[-1] / name).exists())
        for yaml in ('name: duplicate\nname: duplicate\ndescription: x', 'name: alias\ndescription: &a [*a]'):
            with self.assertRaises(ValueError):
                skills._yaml(yaml)

    def test_zip_skill_import_and_rejected_links_and_duplicate_paths(self):
        def zipped(entries):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as archive:
                for name, content in entries:
                    archive.writestr(name, content)
            return base64.b64encode(data.getvalue()).decode()
        content = "---\nname: zipped-flow\ndescription: ZIP 导入\n---\n核对来源"
        package = [("zipped-flow/SKILL.md", content), ("zipped-flow/assets/template.md", "# 标题")]
        self.assertEqual(skills.install_zip(zipped(package))["file_count"], 2)
        self.assertEqual(skills.read("zipped-flow", "assets/template.md")["content"], "# 标题")
        for entry in ("../escape", "zipped-flow/../../escape", "C:/escape", "zipped-flow/assets/CON.txt", "another/SKILL.md"):
            with self.assertRaises(ValueError):
                skills.install_zip(zipped([*package, (entry, "x")]))
        with self.assertRaises(ValueError):
            skills.install_zip(zipped([("SKILL.md", content.replace("zipped-flow", "case-flow")), ("skill.MD", "duplicate")]))

    def test_explicit_only_skill_runtime_and_implicit_negative_controls(self):
        content = "---\nname: manual-flow\ndescription: 仅明确调用\n---\n按来源解释"
        skills.install("manual-flow", content, [{"path": "agents/openai.yaml", "content": "policy:\n  allow_implicit_invocation: false\n"}])
        self.assertFalse(tools.execute("skill_read", {"name": "manual-flow"}, {})["ok"])
        with patch.object(agent, "_post_chat", return_value={"content": "直接回答"}):
            run = self.wait(self.submit("今天你好")["id"], "completed")
        self.assertFalse(brain.get_run(run["id"])["state"].get("active_skills"))
        with patch.object(agent, "_post_chat", return_value={"content": "按工作流程回答"}):
            self.wait(self.submit("使用 $manual-flow 核查")["id"], "completed")
        used = agent.get_session(self.session["id"])["messages"][-1]["skills_used"]
        self.assertEqual(used[0]["reason"], "explicit")
        self.assertNotIn("instructions", used[0])
        with patch.object(agent, "_post_chat", side_effect=[call("skill_read", {"name": "evidence-audit"}), {"content": "核查完成"}]):
            self.wait(self.submit("核查笔记是否符合原文")["id"], "completed")
        used = agent.get_session(self.session["id"])["messages"][-1]["skills_used"]
        self.assertEqual(used[0]["name"], "evidence-audit")
        self.assertEqual(used[0]["reason"], "implicit")
        self.assertIn("SKILL.md", used[0]["resources"])

    def test_skill_scripts_activation_args_and_pinned_version(self):
        skills.install("script-flow", "---\nname: script-flow\ndescription: 计算核对\n---\n执行 scripts/run.py", [{"path": "scripts/run.py", "content": "print('checked')"}])
        ctx = {"tools": list(tools.TOOL_NAMES)}
        self.assertFalse(tools.execute("skill_run", {"name": "script-flow", "path": "scripts/run.py"}, ctx)["ok"])
        self.assertTrue(tools.execute("skill_read", {"name": "script-flow"}, ctx)["ok"])
        with patch.object(research, "python_run", return_value={"ok": True, "stdout": "checked"}) as execute:
            result = tools.execute("skill_run", {"name": "script-flow", "path": "scripts/run.py", "args": ["--input", "/input/example.csv"]}, ctx)
        self.assertTrue(result["ok"])
        self.assertIn("sys.argv", execute.call_args.args[0]["code"])
        self.assertIn("/input/example.csv", execute.call_args.args[0]["code"])
        self.assertEqual(ctx["active_skills"]["script-flow"]["script_runs"], 1)
        (skills.roots()[-1] / "script-flow/scripts/run.py").write_text("changed", encoding="utf-8")
        self.assertIn("已变化", tools.execute("skill_run", {"name": "script-flow", "path": "scripts/run.py"}, ctx)["error"])

    def test_repeating_identical_tools_pauses_without_extra_calls(self):
        with patch.object(agent, "_post_chat", side_effect=lambda *a, **kw: call("workspace_list", {}, "repeat-" + str(time.monotonic_ns()))), patch.object(research, "workspace_path", return_value=self.root):
            run = self.wait(self.submit("检查文件")["id"], "paused")
        trace = run["state"]["trace"]
        self.assertEqual(len(trace), 5)
        self.assertEqual(sum(t["ok"] for t in trace), 3)
        self.assertIn("节省模型消耗", agent.get_session(self.session["id"])["messages"][-1]["interruption"])

    def test_active_skill_context_survives_compaction_as_reference_message(self):
        workflow = {"role": "user", "content": agent_context.SKILL_CONTEXT_PREFIX + "\n核对原文后再作答"}
        messages = [{"role": "system", "content": "用户要求优先"}, workflow]
        for i in range(12):
            messages += [{"role": "user", "content": str(i) + "历史资料" * 200}, {"role": "assistant", "content": "历史答复" * 200}]
        messages.append({"role": "user", "content": "请核查结论"})
        compacted, info = agent_context.compact(messages, 4000)
        self.assertTrue(info)
        self.assertEqual(compacted[1], workflow)
        self.assertEqual(compacted[-1]["content"], "请核查结论")
        self.assertNotIn("核对原文", compacted[0]["content"])

    def test_skill_http_package_install_resources_and_pagination(self):
        from http.server import ThreadingHTTPServer
        from server import Handler
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, body):
            with urlopen(Request(f"http://127.0.0.1:{server.server_port}/api/agent/skills/{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}), timeout=5) as response:
                return json.load(response)
        try:
            content = "---\nname: http-skill\ndescription: API 技能\n---\n按需读取参考"
            request("install", {"content": content, "files": [{"path": "references/test.md", "content": "abcdefghij"}]})
            self.assertEqual(len(request("resources", {"name": "http-skill"})["files"]), 2)
            page = request("read", {"name": "http-skill", "path": "references/test.md", "offset": 3, "limit": 4})
            self.assertEqual(page["content"], "defg")
            self.assertEqual(page["next_offset"], 7)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

    def test_default_executor_gains_skill_authoring_but_custom_allowlist_survives(self):
        old_default = [name for name in tools.TOOL_NAMES if name != "skill_install"]
        cleaned = config._clean_personas([{"id": "executor", "tools": old_default}])
        self.assertIn("skill_install", next(p for p in cleaned if p["id"] == "executor")["tools"])
        cleaned = config._clean_personas([{"id": "executor", "tools": ["kb_read", "skill_read"]}])
        self.assertEqual(next(p for p in cleaned if p["id"] == "executor")["tools"], ["kb_read", "skill_read"])

    def test_readable_titles_preserve_canonical_tool_identifiers(self):
        identifier, revision = "note-5bda17e4f5bdec7d44", "rev-07c435d9788f4602836ec4b331f07865"
        value = {"id": identifier, "title": "物理状态计算与模型决策", "revision_id": revision, "stored_filename": ""}
        names = agent_context.reference_names(value)
        self.assertNotIn("", names)
        answer = f"已更新 {identifier}；撤销见 {revision}。示例：{{\"results\":[3,5]}}"
        expected = agent_context.display_text(answer, names)
        self.assertNotIn(identifier, expected)
        self.assertNotIn(revision, expected)
        self.assertIn('{"results":[3,5]}', expected)
        for split in range(len(answer) + 1):
            chunks = []
            stream = agent_context.TitleStream(names, chunks.append)
            stream.feed(answer[:split]); stream.feed(answer[split:]); stream.flush()
            self.assertEqual("".join(chunks), expected)
            self.assertNotIn("note-", "".join(chunks))
        chunks = []
        stream = agent_context.TitleStream(names, chunks.append)
        for char in answer:
            stream.feed(char)
        stream.flush()
        self.assertEqual("".join(chunks), expected)
        evidence = [{"role": "tool", "content": json.dumps(value)}, {"role": "assistant", "content": answer}]
        self.assertEqual(agent_context.response_parts({"evidence": evidence})[0]["content"], expected)
        self.assertIn(identifier, evidence[0]["content"])
        self.assertTrue(agent_context.requests_internal_ids("请给出内部编号和 revision_id"))
        self.assertFalse(agent_context.requests_internal_ids("不要显示内部编号"))

    def test_streaming_and_reload_show_titles_but_evidence_keeps_ids(self):
        identifier = "note-5bda17e4f5bdec7d44"
        doc = {"id": identifier, "title": "物理状态计算与模型决策", "kind": "note", "body": "来源正文"}
        replies = iter([call("kb_read", {"doc_id": identifier}, "read-title"), {"content": f"已核对 {identifier}。"}])
        def scripted(*args, **kwargs):
            reply = next(replies)
            if reply.get("content") and kwargs.get("on_delta"):
                for char in reply["content"]:
                    kwargs["on_delta"](char)
            return reply
        with patch.object(indexer, "get_doc", return_value=doc), patch.object(agent, "_post_chat", side_effect=scripted):
            run = self.wait(self.submit("核对来源")["id"], "completed")
        message = agent.get_session(self.session["id"])["messages"][-1]
        self.assertIn(doc["title"], message["content"])
        self.assertNotIn(identifier, message["content"])
        raw = brain.get_session(self.session["id"])["messages"][-1]
        self.assertIn(identifier, json.dumps(raw["evidence"]))
        result = json.loads(raw["evidence"][1]["content"])
        self.assertEqual(result["citation"], f"[[{doc['title']}]]")
        events = brain.events(run["id"])
        self.assertNotIn(identifier, "".join(e["data"].get("text", "") for e in events if e["event"] == "delta"))

    def test_skill_switches_filter_catalog_and_deny_disabled_execution(self):
        runtime.save_settings({"disabled_skills": ["literature-review"]})
        self.assertFalse(next(item for item in skills.discover()["skills"] if item["name"] == "literature-review")["enabled"])
        self.assertNotIn("literature-review", skills.catalog_prompt())
        self.assertFalse(tools.execute("skill_read", {"name": "literature-review"})["ok"])
        self.assertTrue(skills.read("literature-review")["content"], "Disabled instructions remain viewable in skill management")
        runtime.save_settings({"skills_enabled": False})
        with patch.object(agent, "_post_chat", return_value={"content": "普通回答"}) as post:
            self.wait(self.submit("$knowledge-curation 整理资料")["id"], "completed")
        self.assertNotIn("已激活技能", post.call_args.args[1][0]["content"])
        exposed = {item["function"]["name"] for item in post.call_args.kwargs["tools"]}
        self.assertNotIn("skill_read", exposed)
        self.assertNotIn("skill_run", exposed)

    def test_rag_switch_stops_recall_and_tools_but_preserves_explicit_references(self):
        runtime.save_settings({"rag_enabled": False, "memory_enabled": False})
        doc = {"id": "doc", "title": "用户引用", "kind": "note", "body": "主动提供的实验依据"}
        with patch.object(brain, "recall") as recall, patch.object(indexer, "get_doc", return_value=doc), patch.object(agent, "_post_chat", return_value={"content": "基于引用回答"}) as post:
            self.wait(self.submit(refs=["doc"])["id"], "completed")
            recall.assert_not_called()
        self.assertIn("主动提供的实验依据", post.call_args.args[1][0]["content"])
        names = {item["function"]["name"] for item in post.call_args.kwargs["tools"]}
        self.assertTrue(runtime.RAG_TOOLS.isdisjoint(names))
        self.assertIn("pdf_read", names)
        self.assertFalse(tools.execute("kb_search", {"query": "实验"})["ok"])
        self.assertFalse(tools.execute("memory_recall", {"query": "实验"})["ok"])

    def test_rag_and_memory_switches_are_independent_and_quote_survives_history(self):
        runtime.save_settings({"rag_enabled": False, "memory_enabled": True})
        brain.remember("长期记忆实验口径", scope="user")
        with patch.object(agent, "_post_chat", return_value={"content": "继续分析"}) as post:
            self.wait(self.submit(context={"quote_text": "引用 AI 的第一段\n\n引用 AI 的第二段"})["id"], "completed")
        names = {item["function"]["name"] for item in post.call_args.kwargs["tools"]}
        self.assertIn("memory_recall", names)
        self.assertNotIn("kb_search", names)
        message = agent.get_session(self.session["id"])["messages"][-2]
        self.assertIn("引用 AI 的第二段", message["quote_text"])
        self.assertIn("引用 AI 的第二段", agent_context.history_messages([message])[0]["content"])
        runtime.save_settings({"rag_enabled": True, "memory_enabled": False})
        self.assertFalse(tools.execute("memory_remember", {"content": "不应存储"})["ok"])
        with patch.object(brain, "recall") as recall, patch.object(agent, "_post_chat", return_value={"content": "普通回答"}) as post:
            self.wait(self.submit()["id"], "completed")
            recall.assert_not_called()
        names = {item["function"]["name"] for item in post.call_args.kwargs["tools"]}
        self.assertIn("kb_search", names)
        self.assertTrue(runtime.MEMORY_TOOLS.isdisjoint(names))

    def test_feature_settings_merge_concurrently_and_validate_limits(self):
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(runtime.save_settings, [{"skills_enabled": False}, {"rag_enabled": False}]))
        options = runtime.settings()
        self.assertFalse(options["skills_enabled"])
        self.assertFalse(options["rag_enabled"])
        updated = runtime.save_settings({"rag_top_k": 1000, "rag_context_chars": 1000000})
        self.assertEqual(updated["rag_top_k"], 20)
        self.assertEqual(updated["rag_context_chars"], 32000)
        with self.assertRaises(ValueError):
            runtime.save_settings({"disabled_skills": "literature-review"})

    def test_math_dollar_notation_does_not_activate_unknown_skill(self):
        with patch.object(agent, "_post_chat", return_value={"content": "数学说明"}):
            self.wait(self.submit("解释 $x$ 和 $y$ 的关系")["id"], "completed")

    def test_native_loop_records_full_evidence_and_next_turn_replays_it(self):
        with patch.object(indexer, "get_doc", return_value={"id": "doc", "title": "Title", "body": "精确观测值 0.12345"}), patch.object(agent, "_post_chat", side_effect=[call("kb_read", {"doc_id": "doc"}), {"content": "已读取"}, {"content": "已核对"}]) as post:
            first = self.wait(self.submit()["id"], "completed")
            self.assertEqual(first["state"]["trace"][0]["args"], {"doc_id": "doc"})
            self.wait(self.submit("继续核对精确值")["id"], "completed")
            text = json.dumps(post.call_args.args[1], ensure_ascii=False)
            self.assertIn("精确观测值 0.12345", text)
            self.assertIn('"role": "tool"', text)
            evidence = research.execute("evidence_read", {"run_id": first["id"], "call_id": "call-1"}, {"session_id": self.session["id"]})
            self.assertIn("0.12345", evidence["content"])

    def test_intermediate_answers_survive_completion_history_and_public_run(self):
        first = {**call("memory_recall", {"query": "方法"}), "content": "## 核心方法\n先训练适配器。", "reasoning_content": "private-thought"}
        second = {**call("plan_update", {"steps": [{"step": "完成比较", "status": "completed"}]}, "call-2"), "content": "| 方法 | 差异 |\n| --- | --- |\n| LoRA | 低秩适配 |"}
        def scripted(*args, on_delta=None, **kwargs):
            message = responses.pop(0)
            if on_delta:
                on_delta(message["content"])
            return message
        responses = [first, second, {"content": "任务已完成。"}]
        with patch.object(agent, "_post_chat", side_effect=scripted):
            run = self.wait(self.submit()["id"], "completed")
        expected = [{"round": 1, "content": first["content"]}, {"round": 2, "content": second["content"]}]
        for message in (run["result"]["assistant"], agent.get_session(self.session["id"])["messages"][-1], runtime.public_run(run)["result"]["assistant"]):
            self.assertEqual(message["content"], "任务已完成。")
            self.assertEqual(message["response_parts"], expected)
            self.assertNotIn("private-thought", json.dumps(message["response_parts"]))
        events = [e["data"] for e in brain.events(run["id"]) if e["event"] == "response"]
        self.assertEqual([e["content"] for e in events], [first["content"], second["content"], "任务已完成。"])
        self.assertEqual([e["intermediate"] for e in events], [True, True, False])

    def test_old_chat_recovers_public_answers_without_reexecuting_model(self):
        message = {"role": "assistant", "content": "完成", "evidence": [
            {"role": "assistant", "content": "", "reasoning_content": "hidden"},
            {"role": "tool", "content": "raw evidence"},
            {"role": "assistant", "content": '公开分析\n```json\n{"tool":"plan_update","args":{}}\n```'},
            {"role": "assistant", "content": '```json\n{"tool":"kb_read","args":{}}\n```'},
        ]}
        brain.append_message(self.session["id"], message)
        with patch.object(agent, "_post_chat") as post:
            restored = agent.get_session(self.session["id"])["messages"][-1]
            self.assertEqual(restored["response_parts"], [{"round": 2, "content": "公开分析"}])
            post.assert_not_called()
        self.assertEqual(agent_context.public_text('```json\n{"result":42}\n```'), '```json\n{"result":42}\n```')

    def test_public_answers_preserved_across_budget_resume_without_duplication(self):
        runtime.save_settings({"max_steps": 1})
        first = {**call("memory_recall", {"query": "研究"}), "content": "阶段结论"}
        with patch.object(agent, "_post_chat", side_effect=[first, {"content": "完成"}]):
            run = self.wait(self.submit()["id"], "paused")
            runtime.control(run["id"], "resume")
            final = self.wait(run["id"], "completed")
        self.assertEqual(final["result"]["assistant"]["response_parts"], [{"round": 1, "content": "阶段结论"}])

    def test_draft_checkpoint_approve_resume_does_not_duplicate_user_or_write(self):
        with patch.object(agent, "_post_chat", side_effect=[call("memory_remember", {"content": "研究指标使用 SCR", "source": "用户要求", "scope": "user"}), {"content": "已完成记忆写入"}]) as post:
            run = self.wait(self.submit()["id"], "waiting_approval")
            rid = run["id"]
            self.assertEqual(post.call_count, 1)
            self.assertEqual(brain.list_memories(), [])
            with self.assertRaises(ValueError):
                runtime.control(rid, "resume")
            draft_id = run["state"]["waiting_drafts"][0]
            tools.confirm_draft(draft_id)
            runtime.control(rid, "resume")
            final = self.wait(rid, "completed")
            self.assertEqual(len(brain.list_memories()), 1)
            messages = agent.get_session(self.session["id"])["messages"]
            self.assertEqual(sum(m["role"] == "user" for m in messages), 1)
            self.assertTrue(all(m["run_status"] == "completed" for m in messages if m.get("run_id") == rid and m["role"] == "assistant"))
            self.assertEqual(final["state"]["waiting_drafts"], [])
            tool_messages = [m for m in post.call_args.args[1] if m["role"] == "tool"]
            self.assertEqual(json.loads(tool_messages[-1]["content"])["status"], "confirmed")

    def test_reject_draft_resume_reports_rejection(self):
        with patch.object(agent, "_post_chat", side_effect=[call("memory_remember", {"content": "不会写入", "source": "test"}), {"content": "用户拒绝，已跳过"}]):
            run = self.wait(self.submit()["id"], "waiting_approval")
            tools.reject_draft(run["state"]["waiting_drafts"][0])
            runtime.control(run["id"], "resume")
            self.wait(run["id"], "completed")
            self.assertEqual(brain.list_memories(session_id=self.session["id"]), [])

    def test_text_fallback_preserves_canonical_evidence(self):
        def scripted(cfg, messages, params, tools=None, on_delta=None):
            if tools:
                raise ValueError("LLM API HTTP 400: unsupported tools")
            self.assertIn("当接口不支持原生函数调用时使用文本协议", messages[0]["content"])
            if not any(m.get("content", "").startswith("工具结果：") for m in messages if isinstance(m.get("content"), str)):
                return {"content": '```json\n{"tool":"memory_recall","args":{"query":"科研"}}\n```'}
            self.assertFalse(any(m.get("role") == "tool" for m in messages))
            return {"content": "完成"}
        with patch.object(agent, "_post_chat", side_effect=scripted):
            run = self.wait(self.submit()["id"], "completed")
            self.assertEqual(run["state"]["protocol"], "text")
            self.assertTrue(any(m.get("role") == "tool" for m in run["state"]["evidence"]))

    def test_round_budget_pauses_then_resumes_checkpoint(self):
        runtime.save_settings({"max_steps": 1})
        with patch.object(agent, "_post_chat", side_effect=[call("memory_recall", {"query": "科研"}), {"content": "继续完成"}]):
            run = self.wait(self.submit()["id"], "paused")
            runtime.control(run["id"], "resume")
            final = self.wait(run["id"], "completed")
            self.assertEqual(len(final["state"]["trace"]), 1)

    def test_restart_recovery_marks_interrupted_and_resumes(self):
        run = brain.create_run(self.session["id"], {"message": "恢复", "persona_id": "executor"})
        brain.update_run(run["id"], status="running")
        runtime._RECOVERED.discard(str(brain.db_path()))
        runtime.recover()
        self.assertEqual(brain.get_run(run["id"])["status"], "interrupted")
        with patch.object(agent, "_post_chat", return_value={"content": "恢复完成"}):
            runtime.control(run["id"], "resume")
            self.wait(run["id"], "completed")

    def test_uncertain_tool_reservation_is_not_reexecuted(self):
        run = brain.create_run(self.session["id"], {"message": "x"})
        self.assertIsNone(brain.begin_tool(run["id"], "id", "memory_remember", {"content": "x"}))
        result = brain.begin_tool(run["id"], "id", "memory_remember", {"content": "x"})
        self.assertTrue(result["uncertain"])
        brain.finish_tool(run["id"], "id", {"ok": True, "id": "saved"})
        self.assertEqual(brain.begin_tool(run["id"], "id", "memory_remember", {"content": "x"}), {"ok": True, "id": "saved"})
        self.assertFalse(brain.begin_tool(run["id"], "id", "memory_remember", {})["ok"])

    def test_active_session_prevents_concurrent_runs(self):
        one = brain.create_run(self.session["id"], {"message": "one"})
        with self.assertRaises(ValueError):
            brain.create_run(self.session["id"], {"message": "two"})
        brain.update_run(one["id"], status="paused")
        self.assertTrue(brain.create_run(self.session["id"], {"message": "two"}))

    def test_stop_signal_prevents_followup_tool(self):
        reached, release = threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            reached.set()
            release.wait(2)
            return call("memory_recall", {"query": "never execute"})
        with patch.object(agent, "_post_chat", side_effect=blocked):
            run = self.submit()
            self.assertTrue(reached.wait(2))
            runtime.control(run["id"], "cancel")
            release.set()
            final = self.wait(run["id"], "cancelled")
            self.assertEqual(final["state"]["trace"], [])

    def test_stream_cancellation_is_not_converted_to_network_failure(self):
        class Response:
            status = 200
            will_close = True
            def readline(self):
                return b'data: {"choices":[{"delta":{"content":"one"}}]}\n'
        conn = SimpleNamespace(request=lambda *a, **k: None, getresponse=lambda: Response(), close=lambda: None)
        def cancelled(_):
            raise runtime.Suspended("cancelled")
        with patch.object(agent.urllib.request, "getproxies", return_value={}), patch.object(agent, "_pool_get", return_value=(conn, False)):
            with self.assertRaises(runtime.Suspended):
                agent._stream_chat({"api_key": "fake", "base_url": "https://example.invalid/v1"}, {}, 10, cancelled)

    def test_schema_and_empty_tool_allowlist_deny_execution(self):
        self.assertFalse(tools.execute("memory_recall", {"query": "x"}, {"tools": []})["ok"])
        self.assertFalse(tools.execute("kb_read", {"doc_id": 12})["ok"])
        self.assertFalse(tools.execute("web_search", {})["ok"])

    def test_paginated_read_and_optimistic_update_conflicts(self):
        document = {"id": "doc", "title": "Title", "body": "a" * 13000 + "END"}
        with patch.object(indexer, "get_doc", side_effect=lambda _: dict(document)), patch.object(indexer, "update_doc", side_effect=lambda _, update: document.update(update) or dict(document)):
            first = tools.execute("kb_read", {"doc_id": "doc"})
            self.assertEqual(first["next_offset"], 12000)
            self.assertTrue(tools.execute("kb_read", {"doc_id": "doc", "offset": 12000})["body"].endswith("END"))
            draft = tools.execute("kb_update_entry", {"doc_id": "doc", "body": "replacement"})
            document["body"] = "human changed it"
            resolved = tools.confirm_draft(draft["draft_id"])
            self.assertEqual(resolved["status"], "failed")
            self.assertEqual(document["body"], "human changed it")

    def test_parallel_confirmation_executes_once(self):
        draft = tools.execute("memory_remember", {"content": "one write", "source": "test", "scope": "user"}, {"session_id": self.session["id"]})
        results = []
        def confirm():
            try:
                return tools.confirm_draft(draft["draft_id"])["status"]
            except ValueError:
                return "already handled"
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda _: confirm(), range(4)))
        self.assertEqual(results.count("confirmed"), 1)
        self.assertEqual(len(brain.list_memories()), 1)

    def test_revision_rollback_requires_current_version(self):
        doc = {"id": "doc", "title": "Title", "body": "before"}
        with patch.object(indexer, "get_doc", side_effect=lambda _: dict(doc)), patch.object(indexer, "update_doc", side_effect=lambda _, data: doc.update(data) or dict(doc)):
            version = tools.execute("kb_read", {"doc_id": "doc"})["version"]
            write = tools.execute("kb_update_entry", {"doc_id": "doc", "body": "after", "expected_version": version}, {"write_mode": "direct"})
            result = tools.execute("kb_rollback", {"revision_id": write["revision_id"]}, {"write_mode": "direct"})
            self.assertTrue(result["ok"])
            self.assertEqual(doc["body"], "before")

    def test_context_compaction_preserves_tool_pairing_and_budget(self):
        messages = [{"role": "system", "content": "goal"}]
        for i in range(20):
            messages.extend([{"role": "user", "content": "request"}, {"role": "assistant", "content": None, "tool_calls": [{"id": str(i)}]}, {"role": "tool", "tool_call_id": str(i), "content": "x" * 2000}])
        packed, info = agent_context.compact(messages, 3000)
        self.assertTrue(info)
        self.assertLessEqual(agent_context.estimate_tokens(packed), 3000)
        ids = {c["id"] for m in packed for c in m.get("tool_calls", [])}
        self.assertTrue(all(m["tool_call_id"] in ids for m in packed if m["role"] == "tool"))

    def test_workspace_boundaries_and_code_fail_closed(self):
        (self.root / "System").mkdir(exist_ok=True)
        for path in ("System/private.json", "Knowledge/../System/private.json", "../../private", ""):
            with self.assertRaises((ValueError, IndexError)):
                research.workspace_path(path)
        result = tools.execute("python_run", {"code": "print(1)"})
        self.assertFalse(result["ok"])
        self.assertIn("启用", result["error"])
        with self.assertRaises(ValueError):
            research._public_url("http://127.0.0.1/secret")

    def test_mcp_configuration_requires_explicit_tool_allowlist(self):
        servers = agent_mcp.validate_servers([{"name": "papers", "url": "http://localhost:9000/mcp", "enabled": True, "tools": ["search"], "read_only_tools": ["search"], "headers_env": {"Authorization": "PAPER_AUTH"}}])
        with patch.object(runtime, "settings", return_value={**runtime.DEFAULTS, "mcp_servers": servers}), patch.object(agent_mcp, "_rpc", side_effect=[{}, {}, {"tools": [{"name": "search", "inputSchema": {"type": "object"}}, {"name": "delete"}]}]):
            result = agent_mcp.discover()
            self.assertEqual(len(result["tools"]), 1)
            self.assertFalse(agent_mcp.is_write(result["tools"][0]["function"]["name"]))
        agent_mcp.validate_servers([])

    def test_real_http_mcp_json_initialize_and_multiline_sse_tool(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        seen = []
        class MCPHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                seen.append((data["method"], self.headers.get("Mcp-Session-Id")))
                if data["method"] == "notifications/initialized":
                    self.send_response(202)
                    self.end_headers()
                    return
                if data["method"] == "initialize":
                    result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture", "version": "1"}}
                elif data["method"] == "tools/list":
                    result = {"tools": [{"name": "search", "description": "papers", "inputSchema": {"type": "object"}}]}
                else:
                    result = {"content": [{"type": "text", "text": "sourced result"}]}
                body = {"jsonrpc": "2.0", "id": data["id"], "result": result}
                if data["method"] == "tools/call":
                    raw = b"\n".join(b"data: " + line.encode() for line in json.dumps(body, indent=2).splitlines()) + b"\n\n"
                    content_type = "text/event-stream"
                else:
                    raw = json.dumps(body).encode()
                    content_type = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Mcp-Session-Id", "fixture-session")
                self.end_headers()
                self.wfile.write(raw)
        server = ThreadingHTTPServer(("127.0.0.1", 0), MCPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            runtime.save_settings({"mcp_servers": [{"name": "fixture", "url": f"http://127.0.0.1:{server.server_port}/mcp", "enabled": True, "tools": ["search"], "read_only_tools": ["search"]}]})
            result = agent_mcp.discover()
            self.assertEqual(result["errors"], [])
            name = result["tools"][0]["function"]["name"]
            response = tools.execute(name, {}, {"tools": [name]})
            self.assertTrue(response["ok"], response)
            self.assertEqual(response["content"][0]["text"], "sourced result")
            self.assertIsNone(seen[0][1])
            self.assertTrue(all(session == "fixture-session" for _, session in seen[1:]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
            agent_mcp.validate_servers([])

    def test_code_runner_constructs_container_without_network_or_secrets(self):
        captured = {}
        (self.root / "Resources").mkdir()
        (self.root / "Resources/data.csv").write_text("x,y\n1,2\n", encoding="utf-8")
        def process(command, **kwargs):
            captured["command"] = command
            kwargs["stdout"].write(b"3\n")
            return SimpleNamespace(returncode=0, poll=lambda: 0)
        runtime.save_settings({"code_enabled": True})
        with patch.object(research.shutil, "which", return_value="docker"), patch.object(research.subprocess, "run", return_value=SimpleNamespace(returncode=0)), patch.object(research.subprocess, "Popen", side_effect=process):
            result = research.python_run({"code": "print(3)", "files": ["Resources/data.csv"]}, {})
            self.assertEqual(result["stdout"], "3\n")
            cmd = captured["command"]
            for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--user=65534:65534", "--memory=256m", "--pull=never"):
                self.assertIn(flag, cmd)
            self.assertNotIn("--env", cmd)
            self.assertEqual(cmd[-4:], ["python", "-I", "-B", "/input/main.py"])

    def test_literature_replace_detects_changes_since_draft(self):
        from app import literature
        note = {"body": "original"}
        with patch.object(literature, "get_item", return_value={"id": "paper", "title": "Paper"}), patch.object(literature, "get_note", side_effect=lambda _: note["body"]), patch.object(literature, "get_annotations", return_value=[]), patch.object(literature, "save_note", side_effect=lambda _, body: note.update(body=body)):
            draft = tools.execute("lit_note_write", {"paper_id": "paper", "content": "replacement", "mode": "replace"})
            note["body"] = "human edited"
            result = tools.confirm_draft(draft["draft_id"])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(note["body"], "human edited")

    def test_pdf_reader_reports_pages_without_inventing_scanned_text(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest("pypdf not installed")
        from app import literature
        path = self.root / "paper.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        writer.add_blank_page(width=300, height=300)
        with path.open("wb") as output:
            writer.write(output)
        with patch.object(literature, "pdf_path", return_value=path):
            result = tools.execute("pdf_read", {"paper_id": "paper", "page": 2})
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["total_pages"], 2)
            self.assertEqual(result["pages"], [{"page": 2, "text": ""}])

    def test_failed_run_retry_keeps_one_user_message(self):
        with patch.object(agent, "_post_chat", side_effect=[ValueError("LLM API HTTP 429: retry later"), {"content": "retried"}]):
            run = self.wait(self.submit()["id"], "failed")
            runtime.control(run["id"], "retry")
            self.wait(run["id"], "completed")
            self.assertEqual(sum(m["role"] == "user" for m in agent.get_session(self.session["id"])["messages"]), 1)

    def test_sse_terminal_snapshot_cannot_close_without_done_or_error(self):
        from server import WorkbenchHTTPServer, Handler
        server = WorkbenchHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for status in ("completed", "waiting_approval", "failed", "missing"):
                run = brain.create_run(self.session["id"], {"message": "race"})
                result = {"ok": True, "assistant": {"role": "assistant", "content": "已持久化的结果"}}
                valid = status in ("completed", "waiting_approval")
                brain.update_run(run["id"], status="completed" if status == "missing" else status, result=result if valid else None, error="真实模型错误" if status == "failed" else "")
                # Reproduce a terminal snapshot observed before its event is appended.
                with patch.object(runtime, "submit", return_value=runtime.public_run(brain.get_run(run["id"]))):
                    req = Request(f"http://127.0.0.1:{server.server_port}/api/agent/send", data=b'{}', headers={"Content-Type": "application/json"})
                    with urlopen(req, timeout=5) as response:
                        self.assertEqual(response.headers["X-Agent-Run-ID"], run["id"])
                        body = response.read().decode()
                self.assertEqual(body.count("event: done"), int(valid))
                self.assertEqual(body.count("event: error"), int(not valid))
                self.assertIn("真实模型错误" if status == "failed" else "未取得保存的回复" if status == "missing" else "已持久化的结果", body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_real_sse_transports_retrievals_capabilities_and_skill_events(self):
        from http.server import ThreadingHTTPServer
        from server import Handler
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            run = brain.create_run(self.session["id"], {"message": "transport"})
            result = {"assistant": {"role": "assistant", "content": "结果"}}
            for event, data in [("capabilities", {"capabilities": {"skills_enabled": False}}), ("retrieval", {"query": "供电恢复", "count": 12}), ("skill", {"name": "example"}), ("done", result)]:
                brain.event(run["id"], event, data)
            brain.update_run(run["id"], status="completed", result=result)
            with patch.object(runtime, "submit", return_value=runtime.public_run(brain.get_run(run["id"]))):
                request = Request(f"http://127.0.0.1:{server.server_port}/api/agent/send", data=b'{}', headers={"Content-Type": "application/json"})
                with urlopen(request, timeout=5) as response:
                    body = response.read().decode("utf-8")
            for event in ("capabilities", "retrieval", "skill", "done"):
                self.assertIn("event: " + event, body)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

    def test_http_background_jobs_events_and_sse_disconnect(self):
        from server import WorkbenchHTTPServer, Handler
        server = WorkbenchHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        def request(path, payload=None):
            req = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=5) as response:
                return response.status, json.load(response)
        try:
            with patch.object(agent, "_post_chat", return_value={"content": "HTTP 完成"}):
                status, run = request("/api/agent/runs", {"session_id": self.session["id"], "message": "HTTP", "persona_id": "executor"})
                self.assertEqual(status, 202)
                self.wait(run["id"], "completed")
                _, events = request(f"/api/agent/runs/{run['id']}/events?after=0")
                self.assertTrue(any(e["event"] == "done" for e in events))
                _, replay = request(f"/api/agent/runs/{run['id']}/events?after={events[-1]['seq']}")
                self.assertEqual(replay, [])
            first = {**call("memory_recall", {"query": "HTTP"}), "content": "中途的完整分析"}
            with patch.object(agent, "_post_chat", side_effect=[first, {"content": "任务已完成"}]):
                req = Request(base + "/api/agent/send", data=json.dumps({"session_id": self.session["id"], "message": "多轮 SSE"}).encode(), headers={"Content-Type": "application/json"})
                with urlopen(req, timeout=5) as response:
                    frames = response.read().decode()
                self.assertIn("event: response\n", frames)
                self.assertIn('"intermediate": true', frames)
                self.assertIn('"response_parts": [{"round": 1, "content": "中途的完整分析"}]', frames)
            release, started = threading.Event(), threading.Event()
            def blocked(*args, **kwargs):
                started.set()
                release.wait(2)
                return {"content": "断线仍完成"}
            with patch.object(agent, "_post_chat", side_effect=blocked):
                req = Request(base + "/api/agent/send", data=json.dumps({"session_id": self.session["id"], "message": "SSE", "persona_id": "executor"}).encode(), headers={"Content-Type": "application/json"})
                with urlopen(req, timeout=5) as response:
                    self.assertEqual(response.readline().strip(), b"event: run")
                    info = json.loads(response.readline()[6:])
                self.assertTrue(started.wait(2))
                with ThreadPoolExecutor(6) as reads:
                    snapshots = list(reads.map(lambda _: request("/api/agent/sessions")[1], range(12)))
                self.assertTrue(all(any(s["id"] == self.session["id"] for s in rows) for rows in snapshots))
                release.set()
                self.wait(info["run_id"], "completed")
                self.assertEqual(agent.get_session(self.session["id"])["messages"][-1]["content"], "断线仍完成")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
