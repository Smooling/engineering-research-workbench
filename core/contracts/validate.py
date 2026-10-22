"""写入期字段校验 —— status / kind_marks / 日期字段 / 未声明字段。

**为什么需要它**：这些规则原先只写在文档里，写入期零校验（REFACTOR_PLAN P16），
于是真的产生了脏数据——实测 `idea.status=进行中`（该类型状态机没有这一项）、
两条条目的 `kind_marks` 含 `知识-方法` 与 `术语清单`（都不在 10 个合法标记内）。
`python -m core.doctor` 能把它们查出来，本模块负责**不让新的进来**。

规则码用 `F` 前缀（字段），与 `naming.py` 的 `T` 前缀（标题）区分。
问题项形状与 naming 一致：`{code, level, message, fix?}`。

纯函数：不碰磁盘。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from . import kinds as C
from . import naming

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: 正文与信封之外、由 store 特殊处理的键（不参与「未声明字段」判定）
_SPECIAL_FIELDS = {"body", "bibtex"}


def _issue(code: str, level: str, message: str, fix: str = "") -> dict[str, str]:
    out = {"code": code, "level": level, "message": message}
    if fix:
        out["fix"] = fix
    return out


def validate_write(
    kind: str,
    payload: dict[str, Any],
    *,
    partial: bool = False,
    title: str = "",
    allowed_marks: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    """校验一次写入的字段（创建或更新）。

    ``partial=True`` 表示「更新」语义：只校验 payload 里**实际出现**的键，
    不要求法定日期齐备（未出现的字段保持不变）。

    ``allowed_marks``：调用方额外放行的标记 id（设置页自定义分类标记）。
    内置标记始终合法；自定义标记由 ``config/app.json`` 的 ``classification_marks``
    声明，由 app 层传入（core 不读配置）。

    返回问题清单（空 = 通过）。`level=error` 必须拒写。
    """
    issues: list[dict[str, str]] = []
    spec = C.KINDS.get(kind)
    if spec is None:
        return [_issue("F001", "error", f"未知条目类型 `{kind}`", "取值限定为 " + " / ".join(C.KIND_ORDER))]

    data = {k: v for k, v in (payload or {}).items() if k not in _SPECIAL_FIELDS}

    # F002 · status 必须在该类型的状态机内
    # milestone 例外（上游 de31add 语义）：`store.milestone_status_class` 把 已完成/阻塞 当作
    # 完成/受阻的别名，未知标签也按「计划中」照常展示——排期允许自定义状态，故只提示不拒写。
    status = str(data.get("status") or "").strip()
    allowed = C.kind_statuses(kind)
    if status and allowed and status not in allowed:
        issues.append(_issue(
            "F002", "warn" if kind == "milestone" else "error",
            f"`{kind}` 的 status=`{status}` 不在状态机内",
            "可选：" + " / ".join(f"`{s}`" for s in allowed),
        ))

    # F003 · kind_marks 必须是合法标记 id（内置契约标记 + 设置页自定义标记）
    valid_marks = {str(m["id"]) for m in C.MARK_IDS}
    if allowed_marks:
        valid_marks |= {str(m).strip() for m in allowed_marks if str(m).strip()}
    marks = [str(m).strip() for m in (data.get("kind_marks") or []) if str(m).strip()]
    bad_marks = [m for m in marks if m not in valid_marks]
    if bad_marks:
        issues.append(_issue(
            "F003", "error", f"kind_marks 含非法标记 {bad_marks}",
            "可选：" + " / ".join(sorted(valid_marks)),
        ))

    # F004 · 契约强制标记（如 experiment 固定带 ⚗）
    # 建档路径由 store / MCP 工具自动补齐（naming.derive_marks），因此这里不报错；
    # 更新路径若**显式**传了 kind_marks 却漏掉强制标记，就会真的把不变量改坏 → 拒写。
    if partial and "kind_marks" in data:
        missing = [m for m in C.required_marks(kind) if m not in marks]
        if missing:
            issues.append(_issue(
                "F004", "error", f"`{kind}` 必须携带标记 {missing}",
                "更新 kind_marks 时请包含它（建档路径会自动补齐）",
            ))

    # F005 · 法定日期字段：格式与适用性
    date_field = C.DATE_FIELDS.get(kind)
    if date_field:
        raw = str(data.get(date_field) or "").strip()
        if raw and not DATE_RE.match(raw):
            issues.append(_issue(
                "F005", "error", f"`{date_field}`=`{raw}` 不是 YYYY-MM-DD 格式", "如 `2026-10-09`",
            ))
        if not partial and not raw:
            issues.append(_issue(
                "F005", "warn", f"`{kind}` 缺法定日期 `{date_field}`", "store 会兜底为当天；建议显式给出",
            ))
    else:
        stray = [f for f in ("record_date", "due", "added_date") if str(data.get(f) or "").strip()]
        if stray:
            issues.append(_issue(
                "F006", "warn", f"`{kind}` 不使用日期字段，但传入了 {stray}",
                "idea/note 无日期字段（见契约 DATE_FIELDS）",
            ))

    # F007 · 未声明字段：不在字段序、不在 CREATE/UPDATE 白名单、也不在已知历史键中
    declared = set(C.FRONTMATTER_ORDER) | {"project_id", "project_ids", "attachment"}
    unknown = sorted(k for k in data if k not in declared)
    if unknown:
        issues.append(_issue(
            "F007", "warn", f"未声明字段 {unknown}",
            "字段契约见 kb_constraints topic=schema；扩展字段请用 `x-<plugin>-*` 命名",
        ))

    return issues


def errors(issues: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return [i for i in issues if i.get("level") == "error"]


def summarize(issues: Iterable[dict[str, str]]) -> str:
    """把 error 级问题压成一行可读消息（供 ValueError 用）。"""
    return "；".join(f"{i['code']} {i['message']}" for i in errors(issues))
