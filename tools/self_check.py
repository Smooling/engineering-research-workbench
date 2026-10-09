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

from app import agent, config, rss, search, store, todos, workspace  # noqa: E402


def ok(name: str):
    print(f"[OK] {name}")


def main() -> int:
    original_app_path = ROOT / "config" / "app.json"
    original_text = original_app_path.read_text(encoding="utf-8")
    temp = Path(tempfile.mkdtemp(prefix="erw-self-check-"))
    try:
        cfg = config.get_app()
        cfg["workspace"] = str(temp / "Workspace")
        cfg.setdefault("workspace_migration", {})["enabled"] = False
        cfg.setdefault("llm", {})["api_key_env"] = "WORKBENCH_SELF_CHECK_KEY"
        os.environ["WORKBENCH_SELF_CHECK_KEY"] = "self-check-secret"
        config.save_app(cfg)

        public = config.get_public()
        assert public["app"]["llm"]["api_key_env"] == "WORKBENCH_SELF_CHECK_KEY" and public["app"]["llm"]["has_api_key"] is True
        assert "api_key" not in config.get_app()["llm"]
        assert not (ROOT / "config" / "secrets.json").exists()
        ok("Environment-variable API key; no local secret storage")

        ws = workspace.ensure_workspace()
        assert (ws / "Knowledge/Notes").exists() and (ws / "System/AgentChats/Attachments").exists()
        ok("Workspace auto-create")

        p = workspace.create_project("SelfCheck")
        assert (ws / p["path"] / "Experiments").exists()
        ok("Project scaffold")

        idea = store.create_doc("idea", {"title": "Self check idea", "projects": ["SelfCheck", "SecondProject"], "tags": ["GraphTag", "Shared"]})
        note = store.create_doc("note", {"title": "Self check note", "projects": ["SelfCheck", "SecondProject"], "tags": ["GraphTag"], "body": "# Note\n\n[[Self check idea]]\n\n$$E=mc^2$$\n"})
        summary = store.create_doc("summary", {"title": "Self check summary", "project": "SelfCheck", "body": "# Summary\n\n[[Self check note]]\n"})
        assert store.get_doc(note["id"])["title"] == "Self check note"
        assert store.list_docs("note", query="E=mc^2")
        assert "SecondProject" in store.get_doc(note["id"])["projects"]
        assert store.list_docs("note", project="SecondProject")
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
        experiment = store.create_doc("experiment", {"title": "Self check experiment"})
        assert experiment["status"] == "计划" and "## 实验目的" in experiment["body"]
        assert (ws / "Knowledge/Custom/experiment" / f"{experiment['id']}.md").exists()
        assert store.list_docs("experiment")[0]["id"] == experiment["id"]
        ok("Custom knowledge type registry + template + status + storage")

        lit = store.create_doc("literature", {"title": "Self check paper", "bibtex": "@article{selfcheck, title={Self Check}}"})
        lit = store.update_doc(lit["id"], {"body": lit["body"], "bibtex": "@article{selfcheck, title={Self Check \\LaTeX}, year={2026}}"})
        assert "year={2026}" in lit["bibtex"]
        bib = store.export_bibtex([lit["id"]])
        assert bib["count"] == 1 and "@article{selfcheck" in bib["content"]
        ok("Literature + BibTeX export")

        nb = store.graph_neighborhood(idea["id"], 2)
        ids = {x["id"] for x in nb["items"]}
        assert note["id"] in ids and summary["id"] in ids
        bundle = store.build_bundle(idea["id"], [note["id"], summary["id"]])
        assert "Self check summary" in bundle
        g = store.graph()
        assert any(n["id"] == "tag:GraphTag" for n in g["nodes"])
        assert any(n["id"] == "project:SecondProject" for n in g["nodes"])
        tag_edges = [e for e in g["edges"] if e["relation"] == "tag" and "tag:GraphTag" in (e["source"], e["target"])]
        assert len(tag_edges) >= 2
        tag_bundle = store.build_bundle("tag:GraphTag", [idea["id"], note["id"]], active_node_ids=["tag:GraphTag", idea["id"], note["id"]], relations=tag_edges)
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
        found = search.search_all("Self check")
        assert any(x["source"] == "doc" for x in found) and any(x["source"] == "chat" for x in found)

        # Exercise the OpenAI-compatible payload path without any network call.
        llm_cfg = config.get_app()
        os.environ["WORKBENCH_SELF_CHECK_KEY"] = "mock-key"
        llm_cfg["llm"] = {**llm_cfg.get("llm", {}), "enabled": True, "base_url": "https://example.invalid/v1", "api_key_env": "WORKBENCH_SELF_CHECK_KEY", "show_reasoning": True, "model": "mock-model", "protocol": "chat_completions", "temperature": None, "max_output_tokens": 0, "request_presets": [{"id":"default","label":"默认（不附加参数）","params":{}},{"id":"qwen-low","label":"Qwen · 低思考","params":{"enable_thinking":True,"thinking_budget":1024}},{"id":"qwen-off","label":"Qwen · 无思考","params":{"enable_thinking":False}},{"id":"high","label":"高思考","params":{"reasoning_effort":"high","model":"must-not-overwrite"}}], "default_request_preset":"default"}
        config.save_app(llm_cfg)
        captured = {}
        original_http = agent._http_json
        def fake_http(url, payload, api_key, timeout=120, method="POST"):
            captured.update({"url": url, "payload": payload, "api_key": api_key, "method": method})
            return {"choices": [{"message": {"content": "mock answer", "reasoning_content": "mock reasoning"}}]}
        agent._http_json = fake_http
        try:
            sent = agent.send_message(chat["id"], "请结合引用分析", [note["id"]], [chat_image["path"]], "high")
            assert sent["assistant"]["content"] == "mock answer" and sent["assistant"]["reasoning"] == "mock reasoning"
            assert captured["url"].endswith("/chat/completions") and captured["api_key"] == "mock-key"
            assert any(isinstance(m.get("content"), list) for m in captured["payload"]["messages"] if m.get("role") == "user")
            assert "Self check note" in captured["payload"]["messages"][0]["content"]
            assert captured["payload"]["reasoning_effort"] == "high"
            assert captured["payload"]["model"] == "mock-model"
            assert sent["assistant"]["request_preset"] == "high"

            cfg_r = config.get_app()
            cfg_r["llm"]["protocol"] = "responses"
            config.save_app(cfg_r)
            def fake_responses(url, payload, api_key, timeout=120, method="POST"):
                captured.update({"url": url, "payload": payload, "api_key": api_key, "method": method})
                return {"output": [{"type":"reasoning","summary":[{"type":"summary_text","text":"responses reasoning"}]},{"content": [{"type": "output_text", "text": "responses answer"}]}]}
            agent._http_json = fake_responses
            sent2 = agent.send_message(chat["id"], "第二轮", [], [])
            assert sent2["assistant"]["content"] == "responses answer" and sent2["assistant"]["reasoning"] == "responses reasoning" and captured["url"].endswith("/responses")
        finally:
            agent._http_json = original_http
        agent.delete_session(chat["id"])
        ok("Global search + Agent multimodal + dynamic request presets")

        cfg2 = config.get_app()
        cfg2["academic_profile"] = {
            "degree_name": "博士进度",
            "start_date": "2026-09-01",
            "expected_end_date": "2030-06-30",
            "weekly_goal_days": 5,
            "graduation_conditions": [{"label": "论文", "current": 1, "target": 2, "unit": "篇"}],
        }
        config.save_app(cfg2)
        dash = store.dashboard()
        assert dash["academic"]["configured"] and dash["academic"]["conditions_total"] == 1
        assert len(dash["activity"]["days"]) >= 390 and dash["activity"]["events_month"] >= 1
        assert any(x["name"] == "SelfCheck" and x["docs"] >= 3 for x in dash.get("project_stats", []))
        ok("Academic dashboard + research heatmap + project pulse")

        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        assert "heatmap-month-select" in app_js and "data-row" in app_js and "--boundary-y" in app_js
        assert "data-graph-kind" in app_js and "data-graph-relation" in app_js and "timeline-3d-viewport" in app_js
        assert "_graphRenderToken" in app_js and "selectedId" in app_js
        assert "标签1, 标签2, 标签3" in app_js and "key==='s'" in app_js
        assert "renderAgent" in app_js and "request_preset" in app_js and "/api/agent/send" in app_js and "/api/search" in app_js
        assert "overview-new-project" in app_js and "openEditorProjectPicker" in app_js and "api_key_env" in app_js
        assert "agent-thinking" in app_js and "模型思考过程" in app_js and "点击空白处恢复全图" in app_js
        assert "global-search-btn" in index and "agent-layout" in styles and "graph-filter-grid" in styles
        assert "graph-preview" in app_js and "graph-fit" in app_js and "_graphResetView" in app_js
        assert "milestone-preview" in app_js and "showMilestonePreview" in app_js
        assert "data-set-tab=\"service\"" in app_js and "svc-host" in app_js and "svc-workspace" in app_js
        assert "data-set-tab=\"knowledge\"" in app_js and "openKnowledgeTypeEditor" in app_js and "/api/knowledge-types" in app_js
        assert "graph-wrap.preview-open" in styles and "overflow-wrap:anywhere" in styles
        assert "mermaid.render" in app_js and "data-focus-preset" in app_js
        ok("Graph filters/highlight + Ctrl+S + dynamic Agent mode UI")

        sample = b"<?xml version='1.0'?><rss><channel><item><title>Paper A</title><link>https://example.test/a</link><pubDate>2026-09-20</pubDate><description>Summary</description></item></channel></rss>"
        parsed = rss._parse_feed(sample, "Local", 5)
        assert parsed and parsed[0]["title"] == "Paper A"
        urls = rss._candidate_urls({"url":"https://rss.arxiv.org/rss/cs.AI"}, 8)
        assert any("export.arxiv.org/api/query" in x for x in urls)
        ok("RSS parser + arXiv fallback strategy")

        subprocess.run([sys.executable, "-m", "compileall", "-q", str(ROOT / "app"), str(ROOT / "server.py")], check=True)
        node = shutil.which("node")
        if node:
            subprocess.run([node, "--check", str(ROOT / "web" / "app.js")], check=True)
            ok("JavaScript syntax")
        ok("Python syntax")
        print("\nSelf check passed.")
        return 0
    finally:
        original_app_path.write_text(original_text, encoding="utf-8")
        os.environ.pop("WORKBENCH_SELF_CHECK_KEY", None)
        config.reload_all()
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
