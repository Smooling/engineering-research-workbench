# -*- coding: utf-8 -*-
"""v261008.2 · 结构性迁移：`知识-实验-…`（note + 实验类别词）→ `实验-…`（kind=experiment）。

背景：实验原本只是 `note` 的一个类别词，与知识笔记混在同一目录、同一路由、同一状态机里，
"整理与新增实验报告"为此变得别扭。v261008.2 起实验升格为**独立类型**：

| 维度 | 迁移前 | 迁移后 |
| --- | --- | --- |
| kind | `note` | `experiment` |
| 目录 | `Knowledge/Notes/` | `Knowledge/Experiments/` |
| 前缀 | `知识-实验-` | `实验-` |
| 状态机 | 草稿/整理中/稳定/已归档 | 计划/进行中/完成/受阻/已归档 |
| 日期字段 | 无 | `record_date`（执行日期） |
| 标记 | 需手写 `experiment` | 自动补 ⚗ |

本脚本做三件事（幂等，可反复运行）：

1. 逐条迁移：改 `kind`、移动文件、标题改前缀、同步 H1、按旧状态映射新状态、补 ⚗ 标记；
2. 同步交叉引用：全库把按旧标题写的 WikiLink 改写成新标题（`id` 不变，按 id 的引用不受影响）；
3. 重建派生索引并复核（打印每条迁移后的命名校验结果）。

用法：
  python tools/kb_migrate_experiments.py --dry-run   # 只读，打印迁移计划
  python tools/kb_migrate_experiments.py --apply     # 执行迁移并重建索引
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.config  # noqa: E402,F401  必须先加载 config：否则 workspace↔config 循环导入会炸
from app import config, indexer, store  # noqa: E402
from mcp import naming  # noqa: E402

#: 旧状态 → 新状态机（实验：计划/进行中/完成/受阻/已归档）
STATUS_MAP = {
    "草稿": "计划",
    "整理中": "进行中",
    "稳定": "完成",
    "已归档": "已归档",
}
SKIP_MARKER = "-实验-"


def collect(notes_dir: Path) -> list[dict]:
    """找出所有还是 note 的 `知识-实验-…` 条目。"""
    plan: list[dict] = []
    if not notes_dir.is_dir():
        return plan
    for path in sorted(notes_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, _body = store._frontmatter_parse(text)
        if str(meta.get("kind") or "") != "note":
            continue
        title = str(meta.get("title") or "")
        if SKIP_MARKER not in title or not title.startswith("知识-"):
            continue
        seg = naming.split_segments(title, "note")
        if seg["category"] != "实验" or not seg["name"]:
            continue
        doc_id = str(meta.get("id") or path.stem)
        new_title = f"实验-{seg['name']}{seg['note']}"
        projects = [str(p) for p in (meta.get("projects") or []) if str(p)]
        if not projects and meta.get("project"):
            projects = [str(meta["project"])]
        marks = [str(m) for m in (meta.get("kind_marks") or []) if str(m)]
        if "experiment" not in marks:
            marks.append("experiment")
        status = STATUS_MAP.get(str(meta.get("status") or ""), "完成")
        plan.append({
            "doc_id": doc_id, "path": path, "old_title": title, "new_title": new_title,
            "projects": projects, "kind_marks": marks, "status": status,
            "issues": naming.validate_title("experiment", new_title, kind_marks=marks, projects=projects),
        })
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_migrate_experiments.py",
                                     description="把 `知识-实验-…` 迁移为 kind=experiment 的 `实验-…`")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只打印迁移计划，不落盘")
    group.add_argument("--apply", action="store_true", help="执行迁移并重建索引")
    args = parser.parse_args(argv)

    # 干跑只读：用 workspace_root() 取路径，不触发 ensure_workspace() 建目录
    workspace = config.workspace_root()
    notes_dir = workspace / "Knowledge" / "Notes"
    experiments_dir = workspace / "Knowledge" / "Experiments"
    plan = collect(notes_dir)

    print(f"待迁移条目：{len(plan)} 条")
    blocked = 0
    for item in plan:
        errors = [x for x in item["issues"] if x["level"] == "error"]
        warns = [x for x in item["issues"] if x["level"] == "warn"]
        flag = "OK  " if not errors else "ERR "
        if errors:
            blocked += 1
        print(f"  {flag}{item['old_title']}")
        print(f"      → {item['new_title']}  [{item['status']}] 项目 {'、'.join(item['projects']) or '（无）'}")
        for issue in errors:
            print(f"      ! {issue['code']} {issue['message']}")
        for issue in warns:
            print(f"      ~ {issue['code']} {issue['message']}")
    if blocked:
        print(f"\n有 {blocked} 条迁移后仍报 error，已中止（请先修标题或项目归属）。")
        return 1
    if not plan:
        print("没有需要迁移的条目（可能已迁移完成）。")
        return 0
    if args.dry_run:
        print("\n干跑结束：未改动任何文件。加 --apply 执行迁移。")
        return 0

    workspace = store.ensure_workspace()
    experiments_dir = workspace / "Knowledge" / "Experiments"
    experiments_dir.mkdir(parents=True, exist_ok=True)
    migrated, refs_total = [], 0
    for item in plan:
        doc = store.change_kind(
            item["doc_id"], "experiment", item["new_title"],
            status=item["status"], kind_marks=item["kind_marks"],
        )
        new_path = experiments_dir / item["path"].name
        refs = naming.rewrite_references(workspace, item["old_title"], item["new_title"], exclude=new_path)
        refs_total += len(refs)
        migrated.append((item, doc, len(refs)))
        print(f"  已迁移 {doc['id']} → {doc['path']}（引用改写 {len(refs)} 处）")

    print(f"\n迁移完成：{len(migrated)} 条，交叉引用改写 {refs_total} 处。")
    print("重建派生索引 …")
    state = indexer.initialize(force=True)
    counts = state.get("counts", {})
    print(f"  索引：{counts}")

    remaining = collect(notes_dir)
    print(f"复核：仍为 note 的 `知识-实验-…` 条目 = {len(remaining)} 条（期望 0）")
    print("复核：命名校验（迁移后标题）")
    for item, doc, _refs in migrated:
        issues = naming.validate_title("experiment", str(doc.get("title") or ""),
                                       kind_marks=doc.get("kind_marks") or [], projects=item["projects"])
        errors = [x for x in issues if x["level"] == "error"]
        print(f"  {'OK  ' if not errors else 'ERR '}{doc.get('title')}")
    return 0 if not remaining else 1


if __name__ == "__main__":
    raise SystemExit(main())
