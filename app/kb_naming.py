"""v260930 · 知识库条目命名规范校验（M1 工具调用层配套）。

规则来源：.trae/rules/知识库条目命名规范.md。
供 Agent 建档工具在落盘前做硬校验：error 级问题拒绝写入（返回给模型让其修正后重试），
warn 级问题仅提示（随草稿一起展示给用户，用户确认时可自行改名）。

标题结构：<前缀>-<类别>-<名称> 或 <前缀>-<类别>-<名称>（补充说明）。
"""

from __future__ import annotations

import re
from typing import Any

# 前缀表：kind → 要求的标题前缀（知识库条目命名规范 §二）
KIND_PREFIX = {
    "note": "知识-",
    "summary": "总结-",
    "idea": "灵感-",
    "journal": "日志-",
    "milestone": "里程碑-",
    "literature": "文献-",
}

# 类别词表：仅 note（知识）类条目使用（命名规范 §三）
NOTE_CATEGORIES = ("架构", "方法", "模型", "原理", "实验", "数据集")

# 类别词 → kind_marks 内置标记 id（命名规范 §五）
CATEGORY_TO_MARK = {
    "架构": "architecture",
    "方法": "method",
    "模型": "model",
    "原理": "principle",
    "实验": "experiment",
    "数据集": "data",
}

FORBIDDEN_CHARS = ("《", "》", "[", "]")

# 中英文之间应保留半角空格：中文紧贴拉丁字母/数字（T011）
_CN_NEXT_TO_LATIN = re.compile(r"[\u4e00-\u9fff][A-Za-z0-9]|[A-Za-z0-9][\u4e00-\u9fff]")
# 实验编号：全角括号包裹的 <数字>.<数字>（如 （4.1）），允许字母后缀
_EXP_NO = re.compile(r"（\d+\.\d+[a-z]?）")
# 日志类标题不应出现日期（日期由 frontmatter 承载）
_DATE_LIKE = re.compile(r"\d{4}[年/-]\d{1,2}|\d{1,2}月\d{1,2}日")


def _split_tail(title: str) -> tuple[str, str]:
    """拆掉末尾全角括号补充说明，返回 (主体, 补充说明)。"""
    if title.endswith("）") and title.count("（") >= 1:
        idx = title.rfind("（")
        return title[:idx], title[idx:]
    return title, ""


def validate_title(kind: str, title: str) -> dict[str, Any]:
    """校验条目标题。返回 {"ok": bool, "errors": [...], "warnings": [...]}。
    ok=False 表示存在 error 级问题，调用方必须拒写。"""
    title = str(title or "").strip()
    errors: list[str] = []
    warnings: list[str] = []
    if not title:
        return {"ok": False, "errors": ["标题为空"], "warnings": []}

    body, tail = _split_tail(title)
    prefix = KIND_PREFIX.get(kind)
    if prefix is None:
        return {"ok": True, "errors": [], "warnings": [f"未知条目类型 {kind}，跳过命名校验"]}

    # E01 · 前缀缺失或错误
    if not body.startswith(prefix):
        want = "知识-<类别>-<名称>" if kind == "note" else prefix + "<名称>"
        errors.append(f"E01 标题必须以「{prefix}」开头，结构为 {want}")
        body_after = body
    else:
        body_after = body[len(prefix):]

    # 禁用符（书名号、方括号）在任何位置都拒绝
    for ch in FORBIDDEN_CHARS:
        if ch in title:
            errors.append(f"E04 标题含禁用符「{ch}」，请改用全角括号或直接删除")

    if kind == "note":
        # 知识类：拆 <类别>-<名称>
        seg = body_after.split("-", 1)
        category = seg[0].strip() if seg else ""
        name = seg[1].strip() if len(seg) > 1 else ""
        if category not in NOTE_CATEGORIES:
            errors.append(f"E02 知识类标题须为 知识-<类别>-<名称>，类别词取 {'/'.join(NOTE_CATEGORIES)}，当前为「{category or '缺失'}」")
        else:
            if not name:
                errors.append(f"E02 知识类标题缺少名称段：知识-{category}-<名称>")
            # E05 · 名称段重复类别词：不得含本类别词（如 知识-实验-…对比实验），也不得夹带其他类别词作分段（如 知识-原理-方法-跟踪）
            if name:
                if category in name:
                    errors.append(f"E05 名称段不得重复类别词「{category}」，如「知识-实验-…对比实验」应写作「知识-实验-…对比」")
                else:
                    stray = [w for w in re.split(r"[-－\s]", name) if w in NOTE_CATEGORIES and w != category]
                    if stray:
                        errors.append(f"E05 名称段夹带了其他类别词（{'、'.join(stray)}），一篇条目有且仅有一个类别词")
            # W04 · 实验类须带编号（编号体系仅红外课题强制，此处降为提示）
            if category == "实验" and not _EXP_NO.search(title):
                warnings.append("W04 实验类条目建议在补充说明中写实验编号，如「…（4.1）」")
            # W02 · 疑似跨族合写（启发式：名称段出现顿号/与/和并列第二个知识点）
            if name and re.search(r"[与和]|、", name):
                warnings.append(f"W02 名称段「{name}」疑似跨族合写，一篇条目只讲一个知识点或一个族")
    else:
        name = body_after
        # W03 · 非知识类名称段只用中文术语，不夹小写英文词（文献题名照抄原文，豁免）
        if kind != "literature":
            low = re.findall(r"[a-z]{2,}", name)
            if low:
                warnings.append(f"W03 非「知识-」类条目名称段应使用中文术语，不夹小写英文词：{'、'.join(low[:3])}")
        if kind == "journal":
            # W05 · 日志类标题不写日期
            if _DATE_LIKE.search(title):
                warnings.append("W05 日志类标题不写日期，日期由 frontmatter 的 record_date 承载")

    # W01 · 中文与拉丁字母/数字之间保留半角空格（文献题名照抄原文，豁免）
    if kind != "literature" and _CN_NEXT_TO_LATIN.search(body):
        warnings.append("W01 中文与拉丁字母/数字之间应保留半角空格，如「GEO 高度」「CW 相对运动」")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def category_mark(kind: str, title: str) -> list[str]:
    """从标题推断 kind_marks 补充（类别词 → 内置标记）。推断不出时返回空表。"""
    if kind != "note":
        return []
    body, _ = _split_tail(str(title or "").strip())
    if body.startswith("知识-"):
        seg = body[len("知识-"):].split("-", 1)
        if seg and seg[0] in CATEGORY_TO_MARK:
            return [CATEGORY_TO_MARK[seg[0]]]
    return []
