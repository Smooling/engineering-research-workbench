"""夹具：笔记多版本 / 分支 / 来源追踪 / 合并归档（v261009.41）。

覆盖：
① 基条与来源；② 外部工具（MCP）按标题自动归族；③ 分叉期间写入先留一版；
④ 来源变化（ui→mcp）也留版本；⑤ 按 H2 小节合并；⑥ 归档到 System/Versions/<base>/archived/（可追溯）；
⑦ 从归档取回；⑧ 实验编号不会被当版本（防误合并）；⑨ 活动日志带来源。

**完全隔离**：monkeypatch `app.config.get_app/get_all` 把 workspace 指到临时目录，不碰真实知识库。

用法：`python tests/kernel/test_versions.py`
"""
import importlib
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BASE = Path(tempfile.mkdtemp(prefix="erwver-"))
from app import config as C  # noqa: E402

_orig_get_app, _orig_get_all = C.get_app, C.get_all


def _fake_get_app():
    cfg = dict(_orig_get_app() or {})
    cfg["workspace"] = str(BASE)
    return cfg


def _fake_get_all():
    data = dict(_orig_get_all() or {})
    data["workspace"] = str(BASE)
    return data


_orig_root = C.workspace_root
C.workspace_root = lambda: BASE
C.get_app, C.get_all = _fake_get_app, _fake_get_all

from app import activity, external_edits, store, versions, workspace  # noqa: E402
from app import external_access  # noqa: E402

#: 外部接入授权在仓库 config/ 下（不在临时工作区）——夹具必须还原它
AUTH = ROOT / "config" / "external-access.json"
_auth_before = AUTH.read_bytes() if AUTH.is_file() else None

workspace.reset_runtime_state()

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


try:
    print("① 基条 + 界面来源")
    base = store.create_doc("note", {"title": "知识-方法-版本测试",
                                     "body": "## 摘要\n基线摘要\n\n## 方法\n基线方法\n"},
                            origin=versions.origin("ui", "doc_save"))
    check("①-1 基条写入且记来源", base["origin_surface"] == "ui", str(base.get("origin_surface")))
    check("①-2 基条不是变体", not versions.is_variant(base))

    print("② MCP 塞进同签名不同版 → 自动归族")
    v2 = store.create_doc("note", {"title": "知识-方法-版本测试（v2）",
                                   "body": "## 摘要\nMCP 改过的摘要\n\n## 方法\nMCP 方法\n"},
                          origin=versions.origin("mcp", "kb_create_entry", "Claude Desktop"))
    check("②-1 自动归到基条", v2.get("variant_of") == base["id"], str(v2.get("variant_of")))
    check("②-2 版本标签取自标题", v2.get("variant_label") == "v2", str(v2.get("variant_label")))
    check("②-3 来源含 MCP 客户端名",
          v2.get("origin_surface") == "mcp" and v2.get("origin_client") == "Claude Desktop",
          versions.describe_origin(v2))
    check("②-4 族计数正确", versions.family(base["id"])["count"] == 2)
    check("②-5 基条有 has_variants 标记", bool(store.get_doc(base["id"]).get("has_variants")))

    print("③ 分叉期间写入 → 先留一版")
    before = len(versions.family(base["id"])["variants"])
    store.update_doc(base["id"], {"body": "## 摘要\n界面改的摘要\n\n## 方法\n界面方法\n"},
                     origin=versions.origin("ui", "doc_save"))
    fam = versions.family(base["id"])
    check("③-1 自动多留一版", len(fam["variants"]) == before + 1, f"{before} → {len(fam['variants'])}")
    snaps = [v for v in fam["variants"] if str(v.get("origin_tool") or "").startswith("snapshot")]
    check("③-2 快照保留写入前内容",
          any("基线摘要" in (store.get_doc(v["id"]).get("body") or "") for v in snaps))

    print("④ 来源变化（ui → mcp）也算冲突")
    n0 = len(versions.family(base["id"])["variants"])
    store.update_doc(base["id"], {"body": "## 摘要\nMCP 再改\n\n## 方法\nMCP 方法\n"},
                     origin=versions.origin("mcp", "kb_update_entry", "Claude Desktop"))
    fam4 = versions.family(base["id"])
    # v261009.56 起：每族只保留**一个**自动快照——再次冲突时覆盖它，而不是再堆一版
    check("④-1 来源变化仍会留版本，且不再堆新条目",
          len(fam4["variants"]) == n0
          and any("界面改的摘要" in (store.get_doc(v["id"]).get("body") or "") for v in fam4["variants"]),
          f"版本数 {n0} → {len(fam4['variants'])}")

    print("⑤ 按小节合并")
    sections = [s["heading"] for s in versions.split_sections(store.get_doc(base["id"])["body"])]
    check("⑤-1 切出 H2 小节", "摘要" in sections and "方法" in sections, str(sections))
    merged, replaced = versions.merge_bodies(store.get_doc(base["id"])["body"], {"摘要": v2["id"]},
                                             {v2["id"]: store.get_doc(v2["id"])["body"]})
    check("⑤-2 只替换被挑中的小节", replaced == ["摘要"], str(replaced))
    check("⑤-3 结果同时含两版内容", "MCP 改过的摘要" in merged and "MCP 方法" in merged)
    store.update_doc(base["id"], {"body": merged}, origin=versions.origin("ui", "merge_variants"))
    check("⑤-4 合并结果落盘", "MCP 改过的摘要" in store.get_doc(base["id"])["body"])

    print("⑥ 归档（保留可追溯）")
    ids = [v["id"] for v in versions.family(base["id"])["variants"]]
    out = versions.archive_variants(base["id"], ids, {"tool": "archive_variants"})
    check("⑥-1 归档条数", len(out["archived"]) == len(ids), str(out))
    check("⑥-2 族里没有活版本", not versions.family(base["id"])["variants"])
    check("⑥-3 基条标记已清", not store.get_doc(base["id"]).get("has_variants"))
    check("⑥-4 归档副本文件存在",
          all((versions.archived_dir(base["id"]) / a["file"]).is_file() for a in out["archived"]))
    check("⑥-5 清单记了来源与时间",
          all(row.get("origin") and row.get("archived_at") for row in versions.archived_index(base["id"])))

    print("⑦ 从归档取回")
    restored = versions.restore_variant(base["id"], out["archived"][0]["file"])
    check("⑦-1 取回仍是同一族", restored["entry"].get("variant_of") == base["id"])

    print("⑧ 实验编号不会被当版本")
    e1 = store.create_doc("experiment", {"title": "实验-编号保护（2.2）", "body": "## 结果\nA\n"},
                          origin=versions.origin("ui"))
    e2 = store.create_doc("experiment", {"title": "实验-编号保护（2.3）", "body": "## 结果\nB\n"},
                          origin=versions.origin("ui"))
    check("⑧-1 两条实验没被并族", not e1.get("variant_of") and not e2.get("variant_of"))

    print("⑨ 活动日志带来源")
    events = [e for e in activity.list_events() if e.get("ref") == base["id"]]
    check("⑨-1 事件里有 source 字段", any("外部 MCP 客户端" in str(e.get("source") or "") for e in events),
          str([e.get("source") for e in events][:3]))

    print("⑩ 分支时间 + 开分支 + 合并记录")
    _live = versions.family(base["id"])["variants"]
    check("⑩-0 活着的分支都带创建时间（含 ⑦ 取回的那条）",
          bool(_live) and all(store.get_doc(v["id"]).get("variant_at") for v in _live),
          str([store.get_doc(v["id"]).get("variant_at") for v in _live])[:120])

    br = versions.create_branch(base["id"], label="v9", origin_info=versions.origin("mcp", "kb_branch_entry"))
    check("⑩-1 开分支复制内容且记 variant_at / variant_of",
          bool(br["entry"].get("variant_at")) and br["entry"].get("variant_of") == base["id"]
          and br["entry"].get("variant_label") == "v9", str(br)[:140])
    fam_now = versions.family(base["id"])
    check("⑩-2 族视图带出每条分支的时间",
          bool(fam_now.get("times")) and all(v["id"] in fam_now["times"] for v in fam_now["variants"]),
          str(list((fam_now.get("times") or {}).keys()))[:120])

    merged = versions.merge_family(base["id"], {"摘要": br["entry"]["id"]},
                                   origin_info=versions.origin("mcp", "kb_merge_variants"))
    check("⑩-3 合并返回 merged_at 与参与版本",
          bool(merged.get("merged_at")) and br["entry"]["id"] in (merged.get("merged_from") or []),
          str(merged)[:160])
    events = [e for e in activity.list_events() if e.get("type") == "doc_merge"]
    check("⑩-4 活动日志记了 doc_merge（含时间/小节/来源）",
          bool(events) and (events[-1].get("detail") or {}).get("merged_at")
          and (events[-1].get("detail") or {}).get("merged_from"),
          str(events[-1])[:170] if events else "（无 doc_merge 事件）")

    print("⑫ 历史条目（从没记过 origin_*）被外部 Agent 改 → 必须留版本 + 记来源")
    legacy = store.create_doc("note", {"title": "知识-方法-历史条目", "body": "## 摘要\n旧内容\n"},
                              origin={"origin_surface": "", "origin_tool": "",
                                      "origin_client": "", "origin_at": ""},
                              _skip_versioning=True)
    check("⑫-1 造出的历史条目确实没有来源字段", not store.get_doc(legacy["id"]).get("origin_surface"))
    external_access.save({"mcp_write": True})
    from mcp import server as MS   # noqa: E402  （⑫ 在 ⑪ 之前，这里自带导入）
    from mcp.bridge import Workbench   # noqa: E402

    wb2 = Workbench()
    MS.handle_tools_call(wb2, {"name": "kb_update_entry",
                               "arguments": {"doc_id": legacy["id"],
                                             "body": "## 摘要\n外部 Agent 改过\n"}})
    legacy_fam = versions.family(legacy["id"])
    check("⑫-2 外部写入历史条目会先留一版（出现分支）",
          len(legacy_fam["variants"]) == 1 and bool(store.get_doc(legacy["id"]).get("has_variants")),
          f"变体 {len(legacy_fam['variants'])} 个")
    snap = store.get_doc(legacy_fam["variants"][0]["id"]) if legacy_fam["variants"] else {}
    check("⑫-3 留下的那版是写入前内容", "旧内容" in (snap.get("body") or ""), (snap.get("body") or "")[:40])
    check("⑫-4 基条记下了这次外部写入的来源",
          store.get_doc(legacy["id"]).get("origin_surface") == "mcp",
          str(store.get_doc(legacy["id"]).get("origin_surface")))
    ui_doc = store.create_doc("note", {"title": "知识-方法-历史条目-界面改", "body": "## 摘要\nA\n"},
                              origin={"origin_surface": "", "origin_tool": "",
                                      "origin_client": "", "origin_at": ""},
                              _skip_versioning=True)
    store.update_doc(ui_doc["id"], {"body": "## 摘要\n界面自己改\n"}, origin=versions.origin("ui", "doc_save"))
    check("⑫-5 界面自己保存历史条目不凭空多一版（避免噪音）",
          len(versions.family(ui_doc["id"])["variants"]) == 0)
    external_access.save({"mcp_write": False})

    print("⑬ 外部直接改文件（绕过界面/MCP）→ 巡检能发现并记录")
    direct = store.create_doc("note", {"title": "知识-方法-直接改文件", "body": "## 摘要\n原始\n"},
                              origin=versions.origin("ui"))
    direct_path = workspace.ensure_workspace() / direct["path"]
    import time as _time

    _time.sleep(2.5)                      # 让文件时间晚于最后一次事件（判据有 2 秒容忍）
    direct_path.write_text(direct_path.read_text(encoding="utf-8") + "\n外部工具直接加的段落\n",
                           encoding="utf-8")
    found = external_edits.scan(record=False)
    hit = [r for r in found["items"] if r["id"] == direct["id"]]
    check("⑬-1 巡检发现「文件被改过但没有记录」", bool(hit), f"共 {found['count']} 条")
    recorded = external_edits.scan(record=True)
    events = [e for e in activity.list_events() if e.get("type") == "doc_external_edit"
              and e.get("ref") == direct["id"]]
    check("⑬-2 记录成 doc_external_edit（来源标注工作区外部改动）",
          bool(events) and "工作区外部改动" in str(events[-1].get("source") or ""),
          str(events[-1].get("source")) if events else "（无事件）")
    check("⑬-3 巡检也会列出库外文件（不在知识库里的 .md）",
          "untracked" in recorded and isinstance(recorded["untracked"], list))

    print("⑭ 删除型改动也能应用（挑中的版本缺该小节）")
    del_base = store.create_doc("note", {"title": "知识-方法-删除语义",
                                         "body": "## 摘要\n甲\n\n## 待删除节\n乙\n"},
                                origin=versions.origin("ui"))
    del_variant = versions.create_branch(del_base["id"], label="v-del",
                                         body="## 摘要\n甲\n",
                                         origin_info=versions.origin("mcp", "kb_branch_entry"))
    merged_body, changed = versions.merge_bodies(
        store.get_doc(del_base["id"])["body"], {"待删除节": del_variant["entry"]["id"]},
        {del_variant["entry"]["id"]: store.get_doc(del_variant["entry"]["id"])["body"]})
    check("⑭-1 合并结果里去掉了该小节", "待删除节" not in merged_body, merged_body[:60])
    check("⑭-2 返回值标明该节被删除", any("删除" in c for c in changed), str(changed))

    print("⑪ MCP 面：开分支工具（受外部接入授权约束）")
    import json as _json

    from mcp import server as MS
    from mcp.bridge import Workbench

    wb = Workbench()
    external_access.save({"mcp_write": False})
    denied = MS.handle_tools_call(wb, {"name": "kb_branch_entry",
                                       "arguments": {"doc_id": base["id"], "label": "mcp-b1"}})
    check("⑪-1 未授权时开分支被拦",
          denied.get("isError") is True and "未授权" in _json.dumps(denied, ensure_ascii=False),
          _json.dumps(denied, ensure_ascii=False)[:140])
    external_access.save({"mcp_write": True})
    allowed = MS.handle_tools_call(wb, {"name": "kb_branch_entry",
                                        "arguments": {"doc_id": base["id"], "label": "mcp-b1"}})
    body_text = _json.dumps(allowed, ensure_ascii=False)
    check("⑪-2 授权后开分支成功且返回创建时间",
          allowed.get("isError") is not True and "mcp-b1" in body_text and "variant_at" in body_text,
          body_text[:170])
    listed = MS.handle_tools_call(wb, {"name": "kb_variants", "arguments": {"doc_id": base["id"]}})
    check("⑪-3 MCP 族视图也带每条分支的时间",
          "variant_at" in _json.dumps(listed, ensure_ascii=False), _json.dumps(listed, ensure_ascii=False)[:140])
    external_access.save({"mcp_write": False})

finally:
    C.get_app, C.get_all = _orig_get_app, _orig_get_all
    C.workspace_root = _orig_root
    if _auth_before is None:
        AUTH.unlink(missing_ok=True)
    else:
        AUTH.write_bytes(_auth_before)
    workspace.reset_runtime_state()
    shutil.rmtree(BASE, ignore_errors=True)

total = len(PASS) + len(FAIL)
print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
raise SystemExit(1 if FAIL else 0)
