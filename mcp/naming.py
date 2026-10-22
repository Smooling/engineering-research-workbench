"""MCP 侧命名工具 —— 校验逻辑已迁至 ``core/contracts/naming.py``（单一实现）。

本模块保留两件事：

1. 再导出校验/建议/替换 H1 等纯函数，历史调用点（``mcp/tools_knowledge.py``）无需改动；
2. 磁盘侧的全库引用扫描与改写（``scan_references`` / ``rewrite_references``）——
   它们要遍历 ``Workspace/`` 下的 Markdown，不属于纯契约。

要改命名规则请改 ``core/contracts/kinds.py``（规则数据）与 ``core/contracts/naming.py``（校验逻辑）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.contracts.naming import (  # noqa: F401  —— 门面再导出
    CJK,
    LATIN,
    allowed_prefixes,
    derive_marks,
    display_width,
    expected_prefix,
    first_h1,
    issues_summary,
    replace_h1,
    split_segments,
    suggest_title,
    validate_entry,
    validate_title,
)


def scan_references(root: Path, needle: str, *, exclude: Path | None = None) -> list[dict[str, Any]]:
    """在 Workspace 下的 Markdown 中查找旧标题的引用位置。"""
    if not needle.strip():
        return []
    hits: list[dict[str, Any]] = []
    for path in root.rglob("*.md"):
        if exclude is not None and path.resolve() == exclude.resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        count = text.count(needle)
        if count:
            hits.append({
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "count": count,
            })
    return sorted(hits, key=lambda x: x["path"])


def rewrite_references(root: Path, old: str, new: str, *, exclude: Path | None = None) -> list[dict[str, Any]]:
    """把全库旧标题引用改写为新标题，返回被改写的文件清单。"""
    if not old.strip() or old == new:
        return []
    changed: list[dict[str, Any]] = []
    for hit in scan_references(root, old, exclude=exclude):
        path = root / hit["path"]
        try:
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace(old, new), encoding="utf-8")
            changed.append(hit)
        except Exception:
            continue
    return changed
