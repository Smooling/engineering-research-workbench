"""标题命名校验与建议 —— 全库**唯一**的一份实现。

规则数据来自 ``core/contracts/kinds.py``；本模块只把规则变成可执行的检查，
所有结论都能对应到规则码（T000–T022）。

历史上这里有两套实现且结论互相矛盾：MCP 走 ``mcp/naming.py``（T000–T022），
应用内 Agent 走 ``app/kb_naming.py``（精简且过期，对 ``experiment`` 直接放行）。
v261009 起合并为本模块：HTTP 侧 Agent 工具与 MCP 工具层都调它，
``experiment`` 在两条路径上得到同一结论。

纯函数模块：不触碰磁盘，也不 import ``app`` / ``mcp``。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from . import kinds as C

CJK = r"\u4e00-\u9fff\u3400-\u4dbf"
LATIN = r"A-Za-z0-9"

_PREFIX_SPLIT = re.compile(r"^([^-]+)-")
_FULLWIDTH_PAREN = re.compile(r"（[^（）]*）")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _issue(code: str, level: str, message: str, fix: str = "") -> dict[str, str]:
    out = {"code": code, "level": level, "message": message}
    if fix:
        out["fix"] = fix
    return out


def first_h1(body: str) -> str:
    """取正文首个 H1 的文本（跳过 HTML 注释）。"""
    text = _HTML_COMMENT.sub("", body or "")
    m = _H1.search(text)
    return m.group(1).strip() if m else ""


def display_width(text: str) -> int:
    """标题显示宽度（半角当量）：CJK 全角字符计 2，拉丁字符/数字/半角符号计 1。

    行宽与截断按此口径判定，而不是按 `len()`——「实验-星特朗 NexStar 6 SLT 配件档位实测（W1）」
    按字符数是 30，按显示宽度是 44，后者才对应它在列表里占的宽度。
    """
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(text or ""))


def split_segments(title: str, kind: str) -> dict[str, Any]:
    """把标题拆成 前缀 / 类别 / 名称 / 补充说明。"""
    raw = (title or "").strip()
    out: dict[str, Any] = {"raw": raw, "prefix": "", "category": "", "name": "", "note": ""}
    if not raw:
        return out
    note = ""
    m = re.search(r"（[^（）]*）\s*$", raw)
    if m:
        note = m.group(0)
        raw_head = raw[: m.start()].strip()
    else:
        raw_head = raw
    out["note"] = note
    parts = raw_head.split("-", 2)
    out["prefix"] = parts[0] if parts else ""
    if len(parts) >= 3:
        out["category"] = parts[1]
        out["name"] = parts[2].strip()
    elif len(parts) == 2:
        out["name"] = parts[1].strip()
    return out


def expected_prefix(kind: str) -> str:
    return str(C.KINDS.get(kind, {}).get("prefix") or "")


def allowed_prefixes(kind: str) -> list[str]:
    """该类型全部合法前缀（`prefixes` 未声明时退化为单 `prefix`）。"""
    spec = C.KINDS.get(kind, {})
    out = [str(x) for x in (spec.get("prefixes") or []) if str(x)]
    primary = str(spec.get("prefix") or "")
    if primary and primary not in out:
        out.insert(0, primary)
    return out


_EXP_NUMBER_EXEMPT: set[str] = {str(x) for x in getattr(C, "EXPERIMENT_NUMBER_EXEMPT_PROJECTS", [])}


def _exp_number_exempt(projects: Iterable[str] | None) -> bool:
    """实验编号规范只适用于有编号体系的课题；命中豁免清单的项目返回 True。"""
    if not projects:
        return False
    if isinstance(projects, str):
        projects = [projects]
    return any(str(p) in _EXP_NUMBER_EXEMPT for p in projects)


def validate_title(
    kind: str,
    title: str,
    *,
    kind_marks: Iterable[str] | None = None,
    body: str | None = None,
    projects: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    """校验标题是否符合命名规范，返回问题清单（空列表 = 通过）。"""
    issues: list[dict[str, str]] = []
    spec = C.KINDS.get(kind)
    if spec is None:
        return [_issue("T000", "error", f"未知条目类型 `{kind}`", "取值限定为 " + " / ".join(C.KIND_ORDER))]

    raw = (title or "").strip()
    if not raw:
        return [_issue("T001", "error", "标题为空", f"应写作 `{spec['prefix']}<名称>`")]

    seg = split_segments(raw, kind)
    prefix, name, note = seg["prefix"], seg["name"], seg["note"]

    if prefix in C.CATEGORY_WORD_ALIASES:
        issues.append(_issue(
            "T004", "error", f"前缀 `{prefix}-` 已废弃（历史「归类-」并入「知识-<类别>-」）",
            f"改为 `{C.CATEGORY_WORD_ALIASES[prefix]}-<类别>-{name or '<名称>'}`",
        ))
    elif f"{prefix}-" not in allowed_prefixes(kind):
        allowed = " / ".join(f"`{p}`" for p in allowed_prefixes(kind))
        issues.append(_issue(
            "T002", "error", f"`{kind}` 条目前缀应为 {allowed}，当前为 `{prefix}-`",
            f"改为 `{spec['prefix']}{name or '<名称>'}`",
        ))

    if not name:
        issues.append(_issue("T008", "error", "名称段为空", f"补写名称：`{spec['prefix']}<类别>-<名称>`"))

    words = [c["word"] for c in C.CATEGORY_WORDS]
    if spec["category_word"]:
        cat = seg["category"]
        if not cat:
            issues.append(_issue(
                "T005", "error", "`知识-` 条目缺少类别词（有且仅有一个）",
                "在名称前插入 " + " / ".join(f"`{w}`" for w in words),
            ))
        elif cat not in words:
            issues.append(_issue(
                "T006", "error", f"未知类别词 `{cat}`", "取值限定为 " + " / ".join(f"`{w}`" for w in words),
            ))
        elif name.startswith(cat):
            issues.append(_issue(
                "T009", "warn", f"名称段重复了类别词 `{cat}`",
                f"去掉名称开头的 `{cat}`：`{spec['prefix']}{cat}-{name[len(cat):].strip() or '<名称>'}`",
            ))
        if cat and kind_marks:
            marks = {str(m) for m in kind_marks}
            expected = next((c["mark"] for c in C.CATEGORY_WORDS if c["word"] == cat), "")
            if expected and expected not in marks:
                issues.append(_issue(
                    "T018", "error", f"类别词 `{cat}` 要求 `kind_marks` 含 `{expected}`，当前为 {sorted(marks)}",
                    f"把 `{expected}` 加入 kind_marks（可多选叠加）",
                ))
    else:
        hit = next((w for w in words if w in prefix or w in (seg["category"] or "")), "")
        if hit:
            issues.append(_issue(
                "T007", "error", f"`{kind}` 条目标题不应出现类别词 `{hit}`",
                f"改为 `{spec['prefix']}{name or '<名称>'}`",
            ))

    for ch in C.FORBIDDEN_TITLE_CHARS:
        if ch in raw:
            issues.append(_issue("T010", "error", f"标题含禁用字符 `{ch}`", "书名号/方括号一律去掉，改用半角括号或空格"))

    if raw.count("（") != raw.count("）"):
        issues.append(_issue("T013", "error", "全角括号未成对闭合", "补充说明须用**全角**括号 `（…）` 包裹且闭合"))

    name_part = name if name else raw
    verbatim = bool(spec.get("title_verbatim"))
    # T011：外文/中文文献题名照抄原文，不改造中拉丁间距
    if not verbatim and (re.search(rf"[{CJK}][{LATIN}]", name_part) or re.search(rf"[{LATIN}][{CJK}]", name_part)):
        issues.append(_issue("T011", "warn", "中文与拉丁字母/数字之间缺少半角空格", "如 `U-Net 系深度网络`、`GEO 单帧经典检测 1.3`"))
    if re.search(r"[ \u3000]{2,}", name_part):
        issues.append(_issue("T012", "warn", "名称段存在连续多余空格", "压缩为单个半角空格"))

    if re.search(r"\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}|(?<!\d)\d{8}(?!\d)", raw):
        if kind in {"journal", "milestone", "idea", "summary"}:
            issues.append(_issue(
                "T014", "warn", "标题含日期",
                "`日志-` 类标题不写日期（日期由 `record_date` 与 `id` 承载）；其他类型也只写事件本身",
            ))

    # T015：类别词已声明唯一族（`知识-<类别>-` 且类别词合法）或题名照抄原文（文献）时不再提示
    declared_single_family = bool(spec["category_word"]) and seg["category"] in words
    if (not declared_single_family and not spec.get("title_verbatim")
            and re.search(r"[\u4e00-\u9fff]\s*[与和]\s*[\u4e00-\u9fff]", name_part)
            and re.search(r"[-_—]", name_part) is None):
        issues.append(_issue(
            "T015", "warn", "疑似「A 与 B」式跨族合写标题",
            "一篇只讲一个知识点或一个族；确需并列请确认二者同族",
        ))

    # T016：外文文献题名保留原文（`title_verbatim`），不视为夹带小写英文词
    if (not spec["category_word"] and not spec.get("title_verbatim")
            and re.search(r"(?<![A-Za-z])[a-z]{3,}(?![A-Za-z])", name_part)):
        issues.append(_issue("T016", "warn", "名称段夹带小写英文词", "改用中文术语，如 `report` → `报告`"))

    # T020：`实验` 类别词已升格为独立条目类型（kind=experiment）
    if seg["category"] == "实验":
        issues.append(_issue(
            "T020", "error", "`实验` 类别词已废弃：实验已升格为独立类型 `experiment`",
            f"改用 `{C.KINDS.get('experiment', {}).get('prefix', '实验-')}<实验内容>（编号）`，"
            "存量条目用 `kb_change_kind` 迁移",
        ))

    # T017：实验类条目须写明实验编号；无编号规范的课题（见 EXPERIMENT_NUMBER_EXEMPT_PROJECTS）豁免
    if kind == "experiment" or seg["category"] == "实验" or (note and re.search(r"\d", note)):
        if (not re.search(r"[\d一二三四五六七八九十]", name_part + note)
                and not _exp_number_exempt(projects)):
            issues.append(_issue("T017", "warn", "实验类条目未写明实验编号", "在名称段或全角括号中补编号，如 `质心算法对比（4.1）`"))

    # T021/T022：标题长度（显示宽度，半角当量）。`文献-` 题名照抄原文，豁免长度上限。
    if not spec.get("title_verbatim"):
        width = display_width(raw)
        limit = int(getattr(C, "TITLE_WIDTH_LIMIT", 60) or 60)
        if width > limit:
            issues.append(_issue(
                "T021", "error", f"标题过长：{width} 半角当量 > 上限 {limit}",
                "把限定语/适用范围/并列项移入正文摘要或 `tags`，标题只留「是什么（+ 编号）」",
            ))
        else:
            warn_at = int((getattr(C, "TITLE_WIDTH_WARN", {}) or {}).get(kind, 36))
            if width > warn_at:
                issues.append(_issue(
                    "T022", "warn", f"标题偏长：{width} 半角当量 > 建议 {warn_at}",
                    "同类条目大多在建议值内；如非必要，把补充信息移入摘要",
                ))

    if body is not None:
        h1 = first_h1(body)
        if h1 and h1 != raw:
            issues.append(_issue(
                "T019", "error", f"title 与正文首个 H1 不一致（H1: `{h1}`）",
                "两者必须完全一致：`kb_update_entry` 传 title 时同步改 H1",
            ))
    return issues


def suggest_title(kind: str, name: str, category: str = "", note: str = "") -> str:
    """按规范拼出建议标题。"""
    spec = C.KINDS.get(kind) or {}
    prefix = str(spec.get("prefix") or "")
    clean = (name or "").strip().strip("-").strip()
    if spec.get("category_word"):
        cat = category if category in [c["word"] for c in C.CATEGORY_WORDS] else ""
        for c in C.CATEGORY_WORDS:
            if clean.startswith(c["word"]):
                clean = clean[len(c["word"]):].strip(" -")
                cat = cat or c["word"]
        head = f"{prefix}{cat}-{clean}" if cat else f"{prefix}{clean}"
    else:
        head = f"{prefix}{clean}"
    tail = note.strip()
    if tail and not tail.startswith("（"):
        tail = f"（{tail.strip('（）()')}）"
    return head + tail


def validate_entry(doc: dict[str, Any]) -> list[dict[str, str]]:
    """校验一条已入库条目（标题 + 正文 H1 + 标记一致性）。"""
    kind = str(doc.get("kind") or "")
    marks = doc.get("kind_marks") or []
    if isinstance(marks, str):
        marks = [marks]
    body = doc.get("body") if doc.get("body") is not None else None
    projects = doc.get("projects") or ([doc["project"]] if doc.get("project") else [])
    return validate_title(kind, str(doc.get("title") or ""), kind_marks=marks, body=body, projects=projects)


def replace_h1(body: str, new_title: str) -> tuple[str, bool]:
    """把正文首个 H1 替换为新标题，返回 (新正文, 是否改动)。"""
    text = body or ""
    m = _H1.search(_HTML_COMMENT.sub("", text)) if _H1.search(text) else None
    if not m:
        return (f"# {new_title}\n\n{text.lstrip()}", True)
    start, end = m.span()
    if m.group(1).strip() == new_title.strip():
        return text, False
    return text[:start] + f"# {new_title}" + text[end:], True


# ---------------------------------------------------------------- 标记推导（两条写入路径共用）

def derive_marks(kind: str, title: str, marks: Iterable[str] | None = None) -> list[str]:
    """按契约补齐 kind_marks：

    - ``知识-<类别>-`` 的类别词决定内置标记（模型类条目不再沿用 ``method``）；
    - 契约 `required_marks` 强制的标记自动补齐（如 ``experiment`` 固定带 ⚗）。
    """
    out = [str(m).strip() for m in (marks or []) if str(m).strip()]
    seg = split_segments(title, kind)
    expected = next((c["mark"] for c in C.CATEGORY_WORDS if c["word"] == seg["category"]), "")
    if expected and expected not in out:
        out.append(expected)
    if kind == "note" and expected == "model" and "method" in out:
        out.remove("method")
    for mark in C.required_marks(kind):
        if mark not in out:
            out.append(mark)
    return out


def issues_summary(issues: Iterable[dict[str, str]]) -> dict[str, Any]:
    """把 issue 列表压成 ``{ok, errors, warnings}``（应用内 Agent 工具沿用的形状）。"""
    items = list(issues)
    errors = [str(x.get("message") or "") for x in items if x.get("level") == "error"]
    warnings = [str(x.get("message") or "") for x in items if x.get("level") != "error"]
    return {"ok": not errors, "errors": errors, "warnings": warnings}
