from __future__ import annotations

import base64
import shutil
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import agent, config, indexer, store, todos, workspace  # noqa: E402


def ok(name: str):
    print(f"[OK] {name}")


def load_plugin_module(plugin_id: str, filename: str):
    """按路径加载插件模块（插件不在 sys.path 上，也不该被内核 import）。"""
    import importlib.util

    path = ROOT / "plugins" / plugin_id / filename
    spec = importlib.util.spec_from_file_location(f"selfcheck_{plugin_id}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    original_config = {name: getattr(config, name) for name in
                       ("ROOT", "CONFIG_DIR", "SECRET_PATH", "LEGACY_SECRET_PATH", "_cache")}
    temp = Path(tempfile.mkdtemp(prefix="erw-self-check-"))
    config.ROOT = temp
    config.CONFIG_DIR = temp / "config"
    config.SECRET_PATH = config.CONFIG_DIR / "secret.json"
    config.LEGACY_SECRET_PATH = config.CONFIG_DIR / "secrets.json"
    config._cache = {}
    workspace.reset_runtime_state()
    try:
        # v261009 · Agent 配置已迁移为 profile + config/secret.json 模型。
        # Self-check writes profiles only inside its isolated configuration directory.
        cfg = config.get_public()["app"]
        cfg["workspace"] = str(temp / "Workspace")
        cfg.setdefault("workspace_migration", {})["enabled"] = False
        llm = cfg.setdefault("llm", {})
        llm["enabled"] = False
        llm["active_profile_id"] = "self-check-profile"
        llm["profiles"] = [{
            "id": "self-check-profile",
            "name": "Self Check",
            "base_url": "https://example.invalid/v1",
            "api_key": "self-check-secret",
            "headers": {"X-Self-Check": "1"},
            "timeout": 120,
            "max_output_tokens": 0,
            "temperature": None,
            "show_reasoning": True,
            "default_request_preset": "default",
            "request_presets": [{"id": "default", "label": "默认", "model": "mock-model", "temperature": None, "params": {}}],
        }]
        config.save_app(cfg)

        public = config.get_public()
        public_llm = public["app"]["llm"]
        assert public_llm["has_api_key"] is True and public_llm["api_key_source"] == "config/secret.json"
        assert public_llm["active_profile_id"] == "self-check-profile"
        assert all("api_key" not in p for p in public_llm.get("profiles", []))
        runtime_profile = config.get_active_llm_profile_runtime()
        assert runtime_profile["api_key"] == "self-check-secret"
        assert runtime_profile["headers"].get("X-Self-Check") == "1"
        assert "api_key" not in config.get_app()["llm"]
        ok("Profile-based local secret storage + public key redaction")

        ws = workspace.ensure_workspace()
        assert (ws / "Knowledge/Notes").exists() and (ws / "System/AgentChats/Attachments").exists()
        ok("Workspace auto-create")

        p = workspace.create_project("SelfCheck")
        assert (ws / p["path"] / "Experiments").exists()
        ok("Project scaffold")

        idea = indexer.create_doc("idea", {"title": "Self check idea", "projects": ["SelfCheck", "SecondProject"], "tags": ["GraphTag", "Shared"]})
        note = indexer.create_doc("note", {"title": "Self check note", "projects": ["SelfCheck", "SecondProject"], "tags": ["GraphTag"], "body": "# Note\n\n[[Self check idea]]\n\n$$E=mc^2$$\n"})
        summary = indexer.create_doc("summary", {"title": "Self check summary", "project": "SelfCheck", "body": "# Summary\n\n[[Self check note]]\n"})
        assert indexer.get_doc(note["id"])["title"] == "Self check note"
        assert indexer.list_docs("note", query="E=mc^2")
        assert "SecondProject" in indexer.get_doc(note["id"])["projects"]
        assert indexer.list_docs("note", project="SecondProject")
        ok("Markdown CRUD + multi-project + full-text search")

        cfg_types = config.get_app()
        cfg_types["knowledge_types"] = {
            "order": ["idea", "note", "experiment", "milestone", "literature", "journal", "summary"],
            "hidden": ["journal", "summary"],
            "custom": [{
                "id": "experiment", "label": "实验记录", "icon": "⚗",
                "statuses": ["计划", "进行中", "完成"],
                "template": "# {{title}}\n\n## 实验目的\n\n## 实验结果\n",
            }],
        }
        config.save_app(cfg_types)
        registry = store.knowledge_type_registry()
        exp_type = next(x for x in registry if x["id"] == "experiment")
        assert exp_type["label"] == "实验记录" and exp_type["statuses"] == ["计划", "进行中", "完成"]
        assert next(x for x in registry if x["id"] == "journal")["hidden"] is True
        experiment = indexer.create_doc("experiment", {"title": "Self check experiment"})
        assert experiment["status"] == "计划" and "## 实验目的" in experiment["body"]
        assert (ws / "Knowledge/Custom/experiment" / f"{experiment['id']}.md").exists()
        assert indexer.list_docs("experiment")[0]["id"] == experiment["id"]
        cfg_templates = config.get_app()
        cfg_templates["knowledge_types"]["templates"] = {"note": "# {{title}}\n\n## 自定义模板\n"}
        cfg_templates["classification_marks"] = [
            {"id": "knowledge", "icon": "◈", "label": "知识", "color": "#2a9d8f"},
            {"id": "method", "icon": "⚒", "label": "方法", "color": "#e76f51"},
            {"id": "experiment", "icon": "⚗", "label": "实验", "color": "#d1569a"},
        ]
        config.save_app(cfg_templates)
        templated = indexer.create_doc("note", {"title": "Template override"})
        assert "## 自定义模板" in templated["body"]
        assert store.kind_default_template("note") != store.kind_template("note")
        marked = indexer.update_doc(note["id"], {"kind_marks": ["knowledge", "method"]})
        assert marked["kind_marks"] == ["knowledge", "method"]
        cleaned = store.cleanup_deleted_mark("knowledge")
        assert cleaned["updated"] >= 1 and indexer.get_doc(note["id"])["kind_marks"] == []
        assert store.kind_label_map()["journal"] == "实验记录"
        ok("Custom knowledge type registry + templates + classification cleanup")

        lit = indexer.create_doc("literature", {"title": "Self check paper", "bibtex": "@article{selfcheck, title={Self Check}}"})
        lit = indexer.update_doc(lit["id"], {"body": lit["body"], "bibtex": "@article{selfcheck, title={Self Check \\LaTeX}, year={2026}}"})
        assert "year={2026}" in lit["bibtex"]
        bib = indexer.export_bibtex([lit["id"]])
        assert bib["count"] == 1 and "@article{selfcheck" in bib["content"]
        ok("Literature + BibTeX export")

        nb = indexer.graph_neighborhood(idea["id"], 2)
        ids = {x["id"] for x in nb["items"]}
        assert note["id"] in ids and summary["id"] in ids
        bundle = indexer.build_bundle(idea["id"], [note["id"], summary["id"]])
        assert "Self check summary" in bundle
        g = indexer.graph()
        assert any(n["id"] == "tag:GraphTag" for n in g["nodes"])
        assert any(n["id"] == "project:SecondProject" for n in g["nodes"])
        tag_edges = [e for e in g["edges"] if e["relation"] == "tag" and "tag:GraphTag" in (e["source"], e["target"])]
        assert len(tag_edges) >= 2
        tag_bundle = indexer.build_bundle("tag:GraphTag", [idea["id"], note["id"]], active_node_ids=["tag:GraphTag", idea["id"], note["id"]], relations=tag_edges)
        assert "GraphTag" in tag_bundle and "Self check note" in tag_bundle
        ok("Graph wikilink + tag/project relations + filtered bundle")

        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 24).decode()
        asset = store.save_asset("data:image/png;base64," + png, "shot.png")
        assert asset["markdown"].startswith("![shot](../Attachments/")
        chat_image = agent.save_image("data:image/png;base64," + png, "agent.png")
        assert chat_image["path"].startswith("System/AgentChats/Attachments/")
        ok("Image validation + agent vision attachments")

        todo = todos.create({"title": "Self check todo", "project": "SelfCheck"})
        assert todo["due"]
        todos.update(todo["id"], {"done": True})
        ok("Todo default date")

        chat = agent.create_session("Self check chat")
        assert agent.get_session(chat["id"])["title"] == "Self check chat"
        found = indexer.search_all("Self check")
        assert any(x["source"] == "doc" for x in found) and any(x["source"] == "chat" for x in found)

        # Exercise the current profile-based OpenAI-compatible payload path without any network call.
        llm_cfg = config.get_public()["app"]
        llm_cfg["llm"]["enabled"] = True
        llm_cfg["llm"]["active_profile_id"] = "self-check-profile"
        llm_cfg["llm"]["profiles"] = [{
            "id": "self-check-profile",
            "name": "Self Check",
            "base_url": "https://example.invalid/v1",
            "api_key": "mock-key",
            "headers": {"X-Self-Check": "1"},
            "timeout": 120,
            "max_output_tokens": 0,
            "temperature": None,
            "show_reasoning": True,
            "default_request_preset": "default",
            "request_presets": [
                {"id":"default","label":"默认（不附加参数）","model":"mock-model","temperature":None,"params":{}},
                {"id":"qwen-low","label":"Qwen · 低思考","model":"mock-model","temperature":None,"params":{"enable_thinking":True,"thinking_budget":1024}},
                {"id":"qwen-off","label":"Qwen · 无思考","model":"mock-model","temperature":None,"params":{"enable_thinking":False}},
                {"id":"high","label":"高思考","model":"mock-model","temperature":None,"params":{"reasoning_effort":"high","model":"must-not-overwrite"}},
            ],
        }]
        config.save_app(llm_cfg)
        captured = {}
        original_http = agent._http_json
        def fake_http(url, payload, api_key, timeout=120, method="POST", extra_headers=None):
            captured.update({"url": url, "payload": payload, "api_key": api_key, "method": method, "headers": extra_headers or {}})
            return {"choices": [{"message": {"content": "mock answer", "reasoning_content": "mock reasoning"}}]}
        agent._http_json = fake_http
        try:
            sent = agent.send_message(chat["id"], "请结合引用分析", [note["id"]], [chat_image["path"]], "high")
            assert sent["assistant"]["content"] == "mock answer" and sent["assistant"]["reasoning"] == "mock reasoning"
            assert captured["url"].endswith("/chat/completions") and captured["api_key"] == "mock-key"
            assert captured["headers"].get("X-Self-Check") == "1"
            assert any(isinstance(m.get("content"), list) for m in captured["payload"]["messages"] if m.get("role") == "user")
            assert "Self check note" in captured["payload"]["messages"][0]["content"]
            assert captured["payload"]["reasoning_effort"] == "high"
            assert captured["payload"]["model"] == "mock-model"  # params 中的 model 不得覆盖模式模型
            assert sent["assistant"]["request_preset"] == "high"
        finally:
            agent._http_json = original_http
        agent.delete_session(chat["id"])
        ok("Global search + Agent multimodal + profile presets + custom headers")

        cfg2 = config.get_app()
        cfg2["academic_profile"] = {
            "degree_name": "博士进度",
            "start_date": "2026-09-01",
            "expected_end_date": "2030-06-30",
            "weekly_goal_days": 5,
            "graduation_conditions": [{"label": "论文", "current": 1, "target": 2, "unit": "篇"}],
        }
        config.save_app(cfg2)
        dash = indexer.dashboard()
        assert dash["academic"]["configured"] and dash["academic"]["conditions_total"] == 1
        assert len(dash["activity"]["days"]) >= 390 and dash["activity"]["events_month"] >= 1
        assert any(x["name"] == "SelfCheck" and x["docs"] >= 3 for x in dash.get("project_stats", []))
        ok("Academic dashboard + research heatmap + project pulse")

        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        milestone_timeline = (ROOT / "web" / "v261014-milestone-timeline.js").read_text(encoding="utf-8")
        assert "heatmap-month-select" in app_js and "data-row" in app_js and "--boundary-y" in app_js
        assert "data-graph-kind" in app_js and "data-graph-relation" in app_js and "ERWMilestoneTimeline" in app_js
        graph_js = (ROOT / "web" / "v260922-graph-performance.js").read_text(encoding="utf-8")
        assert "ERWKnowledgeGraph.mount" in app_js and "selectedId" in graph_js
        # v261009 · 旧 placeholder 文案已不再是稳定接口；这里只验证 Ctrl/Cmd+S 保存钩子仍存在。
        assert "key==='s'" in app_js and "doc-save" in app_js
        agent_client_js = (ROOT / "web" / "agent-client.js").read_text(encoding="utf-8")
        assert "renderAgent" in app_js and "request_preset" in app_js and "/api/search" in app_js
        assert "/api/agent/send" in agent_client_js and "agent-client.js" in index
        assert "overview-new-project" in app_js and "openEditorProjectPicker" in app_js and "api_key_env" in app_js
        assert "agent-thinking" in app_js and "agent-reasoning" in app_js
        assert "global-search-btn" in index and "agent-layout" in styles and "graph-filter-grid" in styles
        assert "graph-preview" in app_js and "graph-fit" in app_js and "clearFocus" in graph_js
        assert "milestone-density-timeline" in milestone_timeline and "collisionComponents" in milestone_timeline and "ResizeObserver" in milestone_timeline
        assert "v261014-milestone-timeline.js" in index
        assert "milestoneTimelineHtml" in app_js and "showMilestonePreview" not in app_js
        assert "data-set-tab=\"service\"" in app_js and "svc-host" in app_js and "svc-workspace" in app_js
        assert "data-set-tab=\"knowledge\"" in app_js and "openKnowledgeTypeEditor" in app_js and "/api/knowledge-types" in app_js
        assert "classificationMarksConfig" in app_js and "/api/knowledge-marks/cleanup" in app_js
        assert "添加条目" not in app_js and "journal:'实验记录'" in app_js
        assert "graph-wrap.preview-open" in styles and "overflow-wrap:anywhere" in styles
        assert "mermaid.render" in app_js and "ERWPanels" in app_js
        ok("Graph filters/highlight + Ctrl+S + dynamic Agent mode UI")

        # v261009 · 资讯与专注已搬成插件：对应实现改到插件文件里查
        plugin_rss = load_plugin_module("rss", "backend.py")
        sample = b"<?xml version='1.0'?><rss><channel><item><title>Paper A</title><link>https://example.test/a</link><pubDate>2026-09-20</pubDate><description>Summary</description></item></channel></rss>"
        parsed = plugin_rss._parse_feed(sample, "Local", 5)
        assert parsed and parsed[0]["title"] == "Paper A"
        urls = plugin_rss._candidate_urls({"url": "https://rss.arxiv.org/rss/cs.AI"}, 8)
        assert any("export.arxiv.org/api/query" in x for x in urls)
        ok("RSS parser + arXiv fallback strategy（插件 plugins/rss）")

        focus_panel = (ROOT / "plugins" / "focus" / "web" / "panel.js").read_text(encoding="utf-8")
        assert "data-focus-preset" in focus_panel and "ERWPanels.register" in focus_panel
        ok("专注计时已成为插件并自登记面板（plugins/focus）")

        subprocess.run([sys.executable, "-m", "compileall", "-q", str(ROOT / "app"), str(ROOT / "server.py")], check=True)
        node = shutil.which("node")
        if node:
            subprocess.run([node, "--check", str(ROOT / "web" / "app.js")], check=True)
            ok("JavaScript syntax")
        ok("Python syntax")
        print("\nSelf check passed.")
        return 0
    finally:
        indexer.stop_background_sync()
        workspace.reset_runtime_state()
        for name, value in original_config.items():
            setattr(config, name, value)
        os.environ.pop("WORKBENCH_SELF_CHECK_KEY", None)
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
