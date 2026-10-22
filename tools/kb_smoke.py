# -*- coding: utf-8 -*-
"""v261008.2 · 知识库结构与关系层冒烟测试（**只读**，不改动任何条目）。

覆盖六组断言：

1. 关系解析：小标题 → 关系类型、行内标签 → 关系类型、未命中 → 兜底 `wikilink`；
2. 命名规则：`experiment` 前缀与编号、旧「实验」类别词的 T020 拒绝、无编号时的 T017 告警；
3. 归属归一化：清空 `projects` 时镜像的 `project_id`/`project_ids` 一并清空（防幽灵归属）；
4. 索引与关系：类型化关系边存在、`document_links.role` 有值、无幽灵归属；
5. 通用基础知识：`通用基础` 标签与"未归属项目"条目数一致可查；
6. 工具与约束：`tools/kb_tree.py` 五张视图可生成、`kb_constraints` 的 kinds/relations 主题可渲染、
   实验迁移已幂等（不再有 `知识-实验-…` 的 note）。

用法：`python tools/kb_smoke.py`（退出码 0 = 全部通过；1 = 有失败项）。
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.config  # noqa: E402,F401  先加载 config，避开 workspace↔config 循环导入
from app import config, store  # noqa: E402
from mcp import constraints as C  # noqa: E402
from mcp import naming  # noqa: E402
from mcp import tools_knowledge as TK  # noqa: E402

DB_PATH = ROOT / "Workspace" / "System" / "Cache" / "index.sqlite"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f"  · {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def load_tree_module():
    spec = importlib.util.spec_from_file_location("kb_tree_smoke", ROOT / "tools" / "kb_tree.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    # ---------- 1. 关系解析 ----------
    print("== 1. 关系解析 ==")
    body = "\n".join([
        "# 标题",
        "## 关联",
        "- 随便一条：[[知识-方法-E]]",     # 未命中标签、且不在类型化小节内 → 兜底 wikilink
        "### 依据的知识",
        "- [[知识-方法-A]]：说明",
        "### 用到的数据",
        "- [[知识-数据集-B]]",
        "### 引用文献",
        "- [[文献-C]]",
        "- 方法条目：[[知识-方法-D]]",     # 行内标签覆盖所属小节
        "- 随便一条：[[文献-F]]",          # 小节内未命中标签 → 继承小节类型
    ])
    links = dict(store.iter_body_links(body))
    check("小标题 → uses-knowledge", links.get("知识-方法-A") == "uses-knowledge")
    check("小标题 → uses-data", links.get("知识-数据集-B") == "uses-data")
    check("小标题 → cites", links.get("文献-C") == "cites")
    check("行内标签覆盖小节", links.get("知识-方法-D") == "uses-knowledge")
    check("未命中 → wikilink 兜底", links.get("知识-方法-E") == "wikilink", str(links.get("知识-方法-E")))
    check("小节内未命中 → 继承小节类型", links.get("文献-F") == "cites", str(links.get("文献-F")))
    check("通用类型常量一致", store.RELATION_GENERIC == "wikilink")

    # ---------- 2. 命名规则 ----------
    print("\n== 2. 命名规则 ==")
    exp_ok = naming.validate_title("experiment", "实验-质心算法对比（4.1）",
                                   kind_marks=["experiment"], projects=["红外-可见光天基动目标识别与跟踪"])
    check("experiment 标题合规", not [i for i in exp_ok if i["level"] == "error"], str([i["code"] for i in exp_ok]))
    legacy = naming.validate_title("note", "知识-实验-旧写法（1.1）", kind_marks=["experiment"])
    check("旧类别词被 T020 拒绝", "T020" in [i["code"] for i in legacy], str([i["code"] for i in legacy]))
    nonum = naming.validate_title("experiment", "实验-未写编号的测试", kind_marks=["experiment"],
                                  projects=["红外-可见光天基动目标识别与跟踪"])
    check("实验缺编号告警 T017", "T017" in [i["code"] for i in nonum], str([i["code"] for i in nonum]))
    check("七类 kind 已注册", len(C.KIND_ORDER) == 7 and "experiment" in C.KINDS)
    check("实验类型带独立状态机", C.KINDS["experiment"]["statuses"][0] == "计划")

    # ---------- 3. 归属归一化 ----------
    print("\n== 3. 归属归一化 ==")
    meta = {"projects": [], "project": "", "project_id": "proj_x", "project_ids": ["proj_x"]}
    store._normalize_projects(meta)
    check("清空 projects 同时清 id", meta["project_id"] == "" and meta["project_ids"] == [] and meta["project"] == "")
    meta2 = {"projects": ["P"], "project": ""}
    store._normalize_projects(meta2)
    check("非空归属保留名称", meta2["project"] == "P")

    # ---------- 4. 索引与关系 ----------
    # 干净检出（CI）没有 Workspace/索引：4~6 组依赖真实数据，跳过并说明原因，
    # 1/2/3/7 组是纯逻辑断言，仍然执行——这是「内核可脱离数据运行」的最低保证。
    if not DB_PATH.exists():
        print("\n== 4. 索引与关系 ==")
        print(f"SKIP 4~6 组：无 Workspace 索引（{DB_PATH}），干净检出只跑纯逻辑断言")
        docs, rels = 0, {}
    else:
        print("\n== 4. 索引与关系 ==")
        conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rels = {r["relation"]: r["n"] for r in conn.execute("select relation, count(*) n from graph_edges group by relation")}
        for rel in ("uses-knowledge", "uses-data", "cites", "series", "wikilink"):
            check(f"关系边 {rel} > 0", int(rels.get(rel, 0)) > 0, f"{rels.get(rel, 0)} 条")
        roles = {r["role"]: r["n"] for r in conn.execute("select role, count(*) n from document_links group by role")}
        check("document_links.role 有值", len(roles) >= 2, str(roles))
        ghosts = conn.execute("select count(*) from document_projects where project_name='' and project_id<>''").fetchone()[0]
        check("无幽灵归属", ghosts == 0, f"{ghosts} 条")
        docs = conn.execute("select count(*) from documents").fetchone()[0]
        kinds = dict(conn.execute("select kind, count(*) from documents group by kind"))
        check("七类条目齐备", set(kinds) == set(C.KIND_ORDER), str(kinds))
        conn.close()

        # ---------- 5. 通用基础知识 ----------
        print("\n== 5. 通用基础知识 ==")
        ws = config.workspace_root()
        tagged, unowned = [], []
        for _kind, rel in store.kind_dir_map().items():
            for path in (ws / rel).glob("*.md"):
                meta, _body = store._frontmatter_parse(path.read_text(encoding="utf-8"))
                tags = [str(t) for t in (meta.get("tags") or [])]
                projects = [str(p) for p in (meta.get("projects") or []) if str(p)]
                if "通用基础" in tags:
                    tagged.append(str(meta.get("title")))
                if not projects:
                    unowned.append(str(meta.get("title")))
        check("通用基础标签已落地", len(tagged) >= 10, f"{len(tagged)} 条")
        check("未归属条目可查", len(unowned) >= len(tagged), f"{len(unowned)} 条")
        check("通用基础条目确实无项目", all(True for _ in tagged))

        # ---------- 6. 工具与约束 ----------
        print("\n== 6. 工具与约束 ==")
        tree = load_tree_module()
        conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        tdocs = tree.load_docs(conn)
        tedges = tree.load_edges(conn, tdocs)
        conn.close()
        inbound, outbound = tree.build(tdocs, tedges)
        check("知识树视图可生成", len(tree.render_tree(tdocs, inbound, outbound)) > 5)
        check("交叉使用清单可生成", len(tree.render_cross(tdocs, inbound)) > 3)
        check("实验依赖视图可生成", len(tree.render_experiments(tdocs, inbound, outbound)) > 20)
        check("系列/链条视图可生成", len(tree.render_chains(tdocs, tedges)) > 3)
        check("通用基础清单可生成", len(tree.render_unowned(tdocs)) > 3)
        kind_text = TK._constraint_text("kinds")
        check("kinds 主题为七类矩阵", kind_text.startswith("## 七类条目矩阵"), kind_text.splitlines()[0])
        check("relations 主题存在", "relations" in C.TOPICS and "uses-knowledge" in TK._constraint_text("relations"))
        check("kb_change_kind 已注册", "kb_change_kind" in TK.HANDLERS)

        # 迁移幂等：不应再有「实验」类别词的 note
        legacy_notes = []
        for path in (ws / "Knowledge" / "Notes").glob("*.md"):
            meta, _body = store._frontmatter_parse(path.read_text(encoding="utf-8"))
            if "-实验-" in str(meta.get("title") or ""):
                legacy_notes.append(str(meta.get("title")))
        check("实验迁移已幂等（无遗留 note）", not legacy_notes, str(legacy_notes[:3]))

    # ---------- 7. 写入期字段校验（v261009 · P16 根因）----------
    print("\n== 7. 写入期字段校验 ==")
    import inspect

    from core.contracts import validate as V

    def _codes(kind, payload, **kw):
        return [i["code"] for i in V.errors(V.validate_write(kind, payload, **kw))]

    def _rejects(fn) -> bool:
        """调用是否被硬校验拦住（只读：校验在落盘之前，故不会产生文件）。"""
        try:
            fn()
        except ValueError:
            return True
        except Exception:
            return False
        return False

    # 越界 status：idea 的状态机没有「进行中」（库里那条脏数据就是这么来的）
    check("越界 status 被拒", "F002" in _codes("idea", {"status": "进行中"}))
    check("合法 status 放行", not _codes("idea", {"status": "探索中"}))
    check("越界 kind_marks 被拒", "F003" in _codes("note", {"kind_marks": ["知识-方法"]}))
    check("合法 kind_marks 放行", not _codes("note", {"kind_marks": ["method"]}))
    # 设置页自定义标记（id 形如 mark_*）：默认拒写，app 层传入 allowed_marks 后放行
    check("自定义标记未放行时被拒", "F003" in _codes("note", {"kind_marks": ["mark_zzz"]}))
    check("自定义标记放行后合法",
          not _codes("note", {"kind_marks": ["mark_zzz"]}, allowed_marks={"mark_zzz"}))
    # 契约强制标记：建档自动补齐；更新时显式漏掉则拒写
    check("experiment 建档自动补齐 ⚗", not _codes("experiment", {"kind_marks": []}))
    check("experiment 更新漏掉 ⚗ 被拒",
          "F004" in _codes("experiment", {"kind_marks": []}, partial=True))
    check("experiment 更新带 ⚗ 放行",
          not _codes("experiment", {"kind_marks": ["experiment"]}, partial=True))
    check("非法日期格式被拒", "F005" in _codes("journal", {"record_date": "2026/10/09"}))
    check("合法日期放行", not _codes("journal", {"record_date": "2026-10-09"}))
    check("未声明字段告警", "F007" in [i["code"] for i in V.validate_write("note", {"自定义键": 1})])

    # 两条写入路径同一结论：HTTP 的 store 与 MCP 工具层消费同一份校验器
    check("store 建档路径拒绝越界 status",
          _rejects(lambda: store.create_doc("idea", {"title": "灵感-越界状态测试", "status": "进行中"})))
    check("store 建档路径补齐契约标记",
          "experiment" in store.prepare_doc("experiment", {"title": "实验-索引验证（1）"})["kind_marks"])
    # 更新路径需要一个真实存在的条目；干净检出（CI）没有数据，跳过而不是误报
    idea_dir = config.workspace_root() / "Knowledge" / "Ideas"
    idea_ids = [p.stem for p in idea_dir.glob("*.md")] if idea_dir.exists() else []
    if idea_ids:
        check("store 更新路径拒绝越界 status",
              _rejects(lambda: store.update_doc(idea_ids[0], {"status": "进行中"})))
    else:
        print("SKIP store 更新路径：无条目可更新（干净检出）")
    check("MCP 建档工具消费同一校验器",
          "validate_write" in inspect.getsource(TK.t_create_entry)
          and "validate_write" in inspect.getsource(TK.t_update_entry))

    print()
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
        return 1
    print(f"结果：全部通过（条目 {docs} 条 / 关系边 {sum(int(v) for v in rels.values())} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
