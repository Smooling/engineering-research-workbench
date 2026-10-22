# -*- coding: utf-8 -*-
"""v261008.2 · 知识树与交叉使用清单生成器。

从派生索引 `Workspace/System/Cache/index.sqlite` **只读**读出条目与类型化关系，
产出四张视图：

1. 知识树：按类别词分层，按「被几个实验交叉使用」分档；
2. 交叉使用清单：同一知识被 ≥2 个实验共用的明细（回答"哪些实验交叉使用同一知识"）；
3. 实验依赖视图：每个实验依据的知识 / 用到的数据 / 同系列 / 环节链 / 产出汇总；
4. 通用基础清单：未归属任何项目（跨项目通用）的条目。

用法：
  python tools/kb_tree.py                     # 全部视图，输出到 stdout
  python tools/kb_tree.py --section cross     # 只看交叉使用清单
  python tools/kb_tree.py --out "Workspace/Knowledge/Exports/KnowledgeTree/知识树.md"
  python tools/kb_tree.py --min-shared 3      # 只列被 ≥3 个实验共用的知识

数据是派生的：改完 Markdown（或迁完条目）先跑 `ws_reindex` 再生成。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "Workspace" / "System" / "Cache" / "index.sqlite"

CATEGORY_ORDER = ["架构", "方法", "模型", "原理", "数据集"]
UNCATEGORIZED = "（无类别词）"
KIND_LABELS = {
    "idea": "灵感", "journal": "研究日志", "note": "笔记", "experiment": "实验",
    "milestone": "里程碑", "summary": "工作总结", "literature": "文献",
}
REL_LABELS = {
    "uses-knowledge": "依据的知识", "uses-data": "用到的数据", "cites": "引用文献",
    "series": "同系列", "chain-prev": "上一环节", "chain-next": "下一环节",
    "produces": "产出汇总", "wikilink": "显式引用",
}


def load_docs(conn: sqlite3.Connection) -> dict[str, dict]:
    docs: dict[str, dict] = {}
    for row in conn.execute(
        "SELECT id,kind,title,status,projects_json,kind_marks_json,path FROM documents"
    ):
        try:
            projects = json.loads(row["projects_json"] or "[]")
        except Exception:
            projects = []
        docs[str(row["id"])] = {
            "id": str(row["id"]), "kind": str(row["kind"]), "title": str(row["title"]),
            "status": str(row["status"] or ""), "projects": [str(p) for p in projects if str(p)],
            "path": str(row["path"] or ""),
        }
    return docs


def load_edges(conn: sqlite3.Connection, docs: dict[str, dict]) -> list[tuple[str, str, str]]:
    """只保留文档↔文档的边（丢掉 tag:/project: 虚拟节点）。"""
    out = []
    for row in conn.execute("SELECT source,target,relation FROM graph_edges"):
        source, target, rel = str(row["source"]), str(row["target"]), str(row["relation"])
        if source in docs and target in docs:
            out.append((source, target, rel))
    return out


def is_experiment(doc: dict) -> bool:
    """迁移前后都成立：kind=experiment，或老式 `知识-实验-…`/`实验-…` 标题。"""
    if doc["kind"] == "experiment":
        return True
    title = doc["title"]
    return title.startswith("知识-实验-") or title.startswith("实验-")


def category_of(doc: dict) -> str:
    if doc["kind"] != "note":
        return ""
    for word in CATEGORY_ORDER:
        if f"-{word}-" in doc["title"]:
            return word
    return UNCATEGORIZED


def short(title: str, limit: int = 46) -> str:
    return title if len(title) <= limit else title[: limit - 1] + "…"


def build(docs: dict[str, dict], edges: list[tuple[str, str, str]]):
    inbound: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    outbound: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for source, target, rel in edges:
        if rel == "wikilink":  # 保底类型：只在没有类型化边时兜底统计
            continue
        inbound[target][rel].append(source)
        outbound[source][rel].append(target)
    return inbound, outbound


def render_tree(docs, inbound, outbound, min_shared: int = 2) -> list[str]:
    lines = ["## 一、知识树（类别 → 被实验使用情况）", ""]
    knowledge = [d for d in docs.values() if d["kind"] == "note"]
    experiments = {d["id"]: d for d in docs.values() if is_experiment(d)}
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for doc in knowledge:
        by_cat[category_of(doc)].append(doc)

    for cat in CATEGORY_ORDER + [UNCATEGORIZED]:
        group = by_cat.get(cat) or []
        if not group:
            continue
        rows = []
        for doc in group:
            users = [experiments[x] for x in inbound[doc["id"]].get("uses-knowledge", []) if x in experiments]
            rows.append((doc, users))
        rows.sort(key=lambda item: (-len(item[1]), item[0]["title"]))
        shared = [x for x in rows if len(x[1]) >= min_shared]
        single = [x for x in rows if len(x[1]) == 1]
        unused = [x for x in rows if not x[1]]
        lines.append(f"### {cat}（{len(group)} 条 · 交叉使用 {len(shared)} · 单实验 {len(single)} · 未被实验引用 {len(unused)}）")
        lines.append("")
        for label, bucket in ((f"交叉使用（≥{min_shared} 个实验）", shared), ("单实验使用", single), ("暂未被实验引用", unused)):
            if not bucket:
                continue
            lines.append(f"- **{label}**")
            for doc, users in bucket:
                if users:
                    names = "、".join(short(u["title"], 24) for u in users[:6])
                    extra = f" 等 {len(users)} 个" if len(users) > 6 else ""
                    lines.append(f"  - {short(doc['title'])}  ← {names}{extra}")
                else:
                    lines.append(f"  - {short(doc['title'])}")
        lines.append("")
    return lines


def render_cross(docs, inbound, min_shared: int = 2) -> list[str]:
    experiments = {d["id"]: d for d in docs.values() if is_experiment(d)}
    rows = []
    for doc_id, rels in inbound.items():
        doc = docs.get(doc_id)
        if not doc or doc["kind"] != "note":
            continue
        users = [experiments[x] for x in rels.get("uses-knowledge", []) if x in experiments]
        if len(users) >= min_shared:
            rows.append((doc, users))
    rows.sort(key=lambda item: (-len(item[1]), item[0]["title"]))
    lines = [f"## 二、交叉使用清单（同一知识被 ≥{min_shared} 个实验共用，共 {len(rows)} 条）", ""]
    if not rows:
        lines += [f"当前没有满足 ≥{min_shared} 的知识条目。", ""]
        return lines
    for doc, users in rows:
        projects = "、".join(doc["projects"]) or "未归属项目（通用基础）"
        lines.append(f"- **{doc['title']}**（{projects}）— {len(users)} 个实验：")
        for user in users:
            lines.append(f"  - {user['title']}｜{user['status']}")
    lines.append("")
    return lines


def render_experiments(docs, inbound, outbound) -> list[str]:
    experiments = sorted(
        (d for d in docs.values() if is_experiment(d)),
        key=lambda d: d["title"],
    )
    lines = [f"## 三、实验依赖视图（{len(experiments)} 个实验）", ""]
    for doc in experiments:
        lines.append(f"### {doc['title']}")
        meta = [f"状态 {doc['status'] or '—'}"]
        if doc["projects"]:
            meta.append("项目 " + "、".join(doc["projects"]))
        lines.append("  " + " · ".join(meta))
        outs = outbound.get(doc["id"], {})
        ins = inbound.get(doc["id"], {})
        for rel in ("uses-knowledge", "uses-data", "cites", "series", "chain-prev", "chain-next", "produces"):
            targets = [docs[x]["title"] for x in outs.get(rel, []) if x in docs]
            if targets:
                lines.append(f"- {REL_LABELS[rel]}：" + "；".join(short(t, 52) for t in targets))
        used_by = [docs[x]["title"] for x in ins.get("uses-knowledge", []) if x in docs]
        if used_by:
            lines.append("- 被以下条目引为依据：" + "；".join(short(t, 52) for t in used_by))
        lines.append("")
    return lines


def render_unowned(docs) -> list[str]:
    rows = sorted(
        (d for d in docs.values() if not d["projects"]),
        key=lambda d: (d["kind"], d["title"]),
    )
    lines = [f"## 四、通用基础候选（未归属任何项目，共 {len(rows)} 条）", ""]
    for doc in rows:
        lines.append(f"- [{KIND_LABELS.get(doc['kind'], doc['kind'])}] {doc['title']}")
    lines.append("")
    return lines


def render_chains(docs, edges) -> list[str]:
    """把 chain-next / series 边连成的链条与系列列出来。"""
    next_map = defaultdict(list)
    prev_ids = set()
    series = defaultdict(set)
    for source, target, rel in edges:
        if rel == "chain-next":
            next_map[source].append(target)
            prev_ids.add(target)
        elif rel == "series":
            series[source].add(target)
            series[target].add(source)
    lines = ["## 五、实验链条与系列", ""]
    roots = [d for d in docs.values() if is_experiment(d) and d["id"] not in prev_ids
             and (next_map.get(d["id"]) or [])]
    if roots:
        lines.append("### 环节链（上一环节 → 下一环节）")
        for root in sorted(roots, key=lambda d: d["title"]):
            chain, seen, cur = [root["title"]], {root["id"]}, next_map.get(root["id"], [None])[0]
            while cur and cur in docs and cur not in seen:
                chain.append(docs[cur]["title"])
                seen.add(cur)
                nxt = next_map.get(cur) or []
                cur = nxt[0] if nxt else None
            lines.append("- " + " → ".join(short(t, 40) for t in chain))
        lines.append("")
    if series:
        lines.append("### 系列分组")
        seen: set[str] = set()
        for start in sorted(series, key=lambda x: docs.get(x, {}).get("title", "")):
            if start in seen:
                continue
            stack, group = [start], []
            while stack:
                node = stack.pop()
                if node in seen:
                    continue
                seen.add(node)
                group.append(node)
                stack.extend(series.get(node, ()))
            if len(group) >= 2:
                titles = "、".join(short(docs[x]["title"], 34) for x in group if x in docs)
                lines.append(f"- {titles}")
        lines.append("")
    if not roots and not series:
        lines.append("当前没有 `chain-next` / `series` 关系边；在「关联」段用 `### 上一环节` / `### 同系列实验` 登记后重建索引即可。")
        lines.append("")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_tree.py", description="知识树与交叉使用清单生成器（只读派生索引）")
    parser.add_argument("--section", default="all", choices=["all", "tree", "cross", "experiments", "unowned", "chains"])
    parser.add_argument("--min-shared", type=int, default=2, help="「交叉使用」的入度阈值，默认 2")
    parser.add_argument("--out", default="", help="输出文件路径（相对仓库根或绝对路径）；缺省打印到 stdout")
    args = parser.parse_args(argv)

    if not DB_PATH.exists():
        print(f"索引不存在：{DB_PATH}\n请先重建索引（工作台启动会自动同步，或跑 ws_reindex）。", file=sys.stderr)
        return 1
    try:
        conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        docs = load_docs(conn)
        edges = load_edges(conn, docs)
        conn.close()
    except sqlite3.Error as exc:
        print(f"读取索引失败：{exc}", file=sys.stderr)
        return 1

    inbound, outbound = build(docs, edges)
    header = [
        "# 知识树与交叉使用清单（自动生成）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} · 数据源：`Workspace/System/Cache/index.sqlite`（派生数据）",
        f"> 条目 {len(docs)} 条 · 文档间关系边 {len(edges)} 条 · 由 `tools/kb_tree.py` 生成，改完条目重建索引后重新生成即可。",
        "",
    ]
    sections: list[str] = []
    if args.section in ("all", "tree"):
        sections += render_tree(docs, inbound, outbound, args.min_shared)
    if args.section in ("all", "cross"):
        sections += render_cross(docs, inbound, args.min_shared)
    if args.section in ("all", "experiments"):
        sections += render_experiments(docs, inbound, outbound)
    if args.section in ("all", "unowned"):
        sections += render_unowned(docs)
    if args.section in ("all", "chains"):
        sections += render_chains(docs, edges)

    text = "\n".join(header + sections).rstrip() + "\n"
    if args.out:
        target = Path(args.out)
        if not target.is_absolute():
            target = ROOT / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"已生成：{target}（{len(text)} 字符）")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
