from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import shutil
import uuid
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .workspace import ensure_workspace, ensure_project
from . import activity, config
from . import versions as _versions
from core.contracts import kinds as contracts
from core.contracts import naming as contract_naming
from core.contracts import validate as contract_validate

# v261009 · 契约单源：kind→目录/标签/状态机/日期字段一律取 core/contracts/kinds.py。
# 历史上 store、mcp/constraints、kb_naming 三处各留一份副本且已漂移，本模块不再自留。

# v3 · 自定义知识类型：内置类型一律取 core/contracts/kinds.py，仅自定义类型叠加在 config 上。
_CUSTOM_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")

def _knowledge_cfg() -> dict[str, Any]:
    raw = config.get_app().get("knowledge_types") or {}
    return raw if isinstance(raw, dict) else {}


def allowed_marks() -> set[str]:
    """当前合法的分类标记 id：契约内置的 10 个 + 设置页自定义的（config/app.json）。

    自定义标记由用户在「设置 → 知识条目 → 分类标记」添加，id 形如 `mark_xxx`；
    core 不读配置，所以这里把配置里的 id 作为额外放行集合交给写入校验。
    """
    ids = {str(m["id"]) for m in contracts.MARK_IDS}
    rows = config.get_app().get("classification_marks")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                mark_id = str(row.get("id") or "").strip()
                if mark_id:
                    ids.add(mark_id)
    return ids


def mark_catalog() -> dict[str, Any]:
    """设置页「内置模板」数据：内置标记的 id/图案/颜色/用途 + 上限与默认集合。"""
    return {
        "limit": contracts.MARK_LIMIT,
        "defaults": list(contracts.MARK_DEFAULT_IDS),
        "templates": [
            {
                "id": str(m["id"]),
                "icon": str(m["icon"]),
                "label": str(m["label"]),
                "color": str(m.get("color") or "#4a6fa5"),
                "hint": contracts.MARK_TEMPLATE_HINTS.get(str(m["id"]), ""),
            }
            for m in contracts.MARK_IDS
        ],
    }

def custom_kind_records() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set(contracts.kind_dir_map())
    for raw in (_knowledge_cfg().get("custom") or []):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("id") or "").strip().lower()
        if not _CUSTOM_KIND_RE.fullmatch(kind) or kind in seen:
            continue
        label = str(raw.get("label") or kind).strip()[:32] or kind
        icon = str(raw.get("icon") or "◆").strip()[:4] or "◆"
        statuses = [str(x).strip()[:24] for x in (raw.get("statuses") or []) if str(x).strip()]
        if not statuses:
            statuses = ["草稿", "进行中", "完成", "已归档"]
        template = str(raw.get("template") or "").replace("\r\n", "\n")
        out.append({
            "id": kind,
            "label": label,
            "icon": icon,
            "statuses": list(dict.fromkeys(statuses))[:12],
            "template": template,
            "hidden": bool(raw.get("hidden", False)),
        })
        seen.add(kind)
    return out

def knowledge_type_registry() -> list[dict[str, Any]]:
    cfg = _knowledge_cfg()
    hidden = {str(x) for x in (cfg.get("hidden") or [])}
    custom = {x["id"]: x for x in custom_kind_records()}
    # 内置七类的默认顺序与侧栏一致：实验在里程碑之前（侧栏 NAV_GROUPS 也是这个次序）。
    # 此前这里漏了 experiment，导致「设置 → 知识条目」看不到实验、无法与其它类型一并管理。
    default_order = ["idea", "journal", "note", "experiment", "milestone", "summary", "literature", *custom.keys()]
    order = [str(x) for x in (cfg.get("order") or []) if str(x)]
    if not order:
        order = list(default_order)
    else:
        # 旧配置的 order 可能缺后来新增的内置类型（如 experiment）。按 default_order 的
        # 相对位置补齐，而不是一律追加到末尾——否则实验会排到「文献」之后。
        for i, kind in enumerate(default_order):
            if kind in order:
                continue
            prev = next((k for k in reversed(default_order[:i]) if k in order), None)
            order.insert(order.index(prev) + 1 if prev else 0, kind)
        order = list(dict.fromkeys([*order, *custom.keys()]))
    rows: list[dict[str, Any]] = []
    builtin_icons = {"idea":"✦","journal":"▤","note":"▧","experiment":"⚗","milestone":"⚑","summary":"▣","literature":"◫"}
    for kind in order:
        if kind in contracts.kind_dir_map():
            rows.append({
                "id": kind, "label": contracts.kind_label_map()[kind], "icon": builtin_icons[kind],
                "statuses": list(contracts.kind_statuses(kind)), "builtin": True,
                "hidden": kind in hidden, "template": kind_template(kind),
                "default_template": kind_default_template(kind),
            })
        elif kind in custom:
            rows.append({**custom[kind], "builtin": False, "hidden": bool(custom[kind].get("hidden")) or kind in hidden,
                         "template": kind_template(kind), "default_template": kind_default_template(kind)})
    return rows

def kind_dir_map() -> dict[str, str]:
    out = dict(contracts.kind_dir_map())
    for row in custom_kind_records():
        out[row["id"]] = f"Knowledge/Custom/{row['id']}"
    return out

def kind_label_map() -> dict[str, str]:
    out = dict(contracts.kind_label_map())
    for row in custom_kind_records():
        out[row["id"]] = row["label"]
    return out

def kind_statuses(kind: str) -> list[str]:
    base = contracts.kind_statuses(kind)
    if base:
        return list(base)
    for row in custom_kind_records():
        if row["id"] == kind:
            return list(row["statuses"])
    return []

def all_statuses() -> dict[str, list[str]]:
    return {kind: kind_statuses(kind) for kind in kind_dir_map()}

def builtin_kind_default_template(kind: str) -> str:
    if kind == "idea":
        return "# {{title}}\n\n## 想法\n\n\n## 为什么值得记录\n\n\n## 下一步\n\n- [ ] \n"
    if kind == "journal":
        return "# {{title}}\n\n## 实验目的\n\n\n## 实验配置\n\n\n## 实验结果\n\n\n## 结论\n\n"
    if kind == "note":
        return "# {{title}}\n\n## 摘要\n\n\n## 正文\n\n\n## 关联\n\n"
    if kind == "milestone":
        return "# {{title}}\n\n## 目标\n\n\n## 验收条件\n\n- [ ] \n\n## 进展记录\n\n"
    if kind == "summary":
        return "# {{title}}\n\n## 本阶段完成\n\n\n## 结果与产出\n\n\n## 问题与经验\n\n\n## 下一阶段\n\n- [ ] \n"
    if kind == "literature":
        return "# {{title}}\n\n## BibTeX\n\n```bibtex\n{{bibtex}}\n```\n\n## 核心结论\n\n\n## 方法与数据\n\n\n## 与当前研究的关系\n\n\n## 摘录与批注\n\n"
    return "# {{title}}\n\n## 要点\n\n\n## 正文\n\n\n## 关联\n\n"


def kind_default_template(kind: str) -> str:
    if kind in contracts.kind_dir_map():
        return builtin_kind_default_template(kind)
    for row in custom_kind_records():
        if row["id"] == kind:
            return str(row.get("template") or "") or builtin_kind_default_template("note")
    return builtin_kind_default_template("note")


def kind_template(kind: str) -> str:
    cfg = _knowledge_cfg()
    overrides = cfg.get("templates") if isinstance(cfg.get("templates"), dict) else {}
    if kind in overrides:
        return str(overrides.get(kind) or "")
    return kind_default_template(kind)


def cleanup_deleted_mark(mark_id: str) -> dict[str, Any]:
    mark_id = str(mark_id or "").strip()
    if not mark_id:
        return {"ok": True, "updated": 0}
    updated = 0
    for kind, path in _iter_docs():
        text = path.read_text(encoding="utf-8")
        meta, body = _frontmatter_parse(text)
        marks = meta.get("kind_marks") or []
        if isinstance(marks, str):
            marks = [x.strip() for x in re.split(r"[,，]", marks) if x.strip()]
        if mark_id not in marks:
            continue
        meta["kind_marks"] = []
        meta["updated"] = _now()
        with _LOCK:
            _atomic_write(path, _frontmatter_dump(meta) + body.rstrip() + "\n")
        updated += 1
    return {"ok": True, "updated": updated, "mark_id": mark_id}


DATE_FIELDS = contracts.DATE_FIELDS

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")

# ---------------------------------------------------------------- 关联段 → 关系类型
# 「关联」段的小标题（H3）与行内标签（`- 标签：`）共同决定 WikiLink 的关系类型；
# 未命中任何映射的链接退化为通用 `wikilink`，历史条目无需改动即可获得类型化边。
# 映射表唯一声明处：core/contracts/kinds.py（store 只做转发）。
RELATION_GENERIC = contracts.RELATION_GENERIC
RELATION_SECTIONS = contracts.RELATION_SECTIONS
RELATION_LABELS = contracts.RELATION_LABELS
RELATION_LABELS_DISPLAY = contracts.RELATION_LABELS_DISPLAY

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")


def _inline_label_role(line: str) -> str:
    """行内 `- 标签：内容` 的标签映射（历史条目多用这种写法）。"""
    text = line.lstrip("-*•· \t").strip()
    if not text:
        return ""
    for sep in ("：", ":"):
        if sep in text:
            label = text.split(sep, 1)[0].strip().strip("*").strip()
            role = RELATION_LABELS.get(label)
            if role:
                return role
            break
    return ""


def iter_body_links(body: str) -> list[tuple[str, str]]:
    """解析正文，返回 ``[(token, role)]``；role 由所属小标题或行内标签决定。

    - 小标题命中 ``RELATION_SECTIONS`` → 该小节内所有链接用该关系类型；
    - 行内标签命中 ``RELATION_LABELS`` → 覆盖所属小节的关系类型；
    - 都不命中 → ``wikilink``（通用显式引用）。
    """
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    section_role = RELATION_GENERIC
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            section_role = RELATION_SECTIONS.get(heading.group(1).strip(), RELATION_GENERIC)
            continue
        if "[[" not in line:
            continue
        role = _inline_label_role(line) or section_role
        for token in WIKILINK_RE.findall(line):
            token = str(token).strip()
            if not token:
                continue
            item = (token, role)
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out

BIBTEX_BLOCK_RE = re.compile(r"```bibtex\s*\n(.*?)```", re.S | re.I)
_LOCK = threading.RLock()


def document_revision(text: str) -> str:
    """Include metadata and body, independent of timestamp precision."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RevisionConflict(ValueError):
    def __init__(self, current: dict[str, Any]):
        super().__init__("条目已被其他客户端修改，请比较当前值后重新合并保存")
        self.current = current


def milestone_status_class(raw: Any) -> str:
    # Unknown/custom labels remain visible and count as pending/planned.
    value = str(raw or "").strip()
    if value in ("完成", "已完成"):
        return "done"
    if value in ("受阻", "阻塞"):
        return "blocked"
    return "active" if value == "进行中" else "planned"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def _slug(text: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", (text or "").strip(), flags=re.UNICODE)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:64] or "untitled"


def _quote_yaml(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _frontmatter_dump(meta: dict[str, Any]) -> str:
    lines = ["---"]
    ordered = contracts.FRONTMATTER_ORDER
    seen = set()
    for key in ordered + sorted(meta.keys()):
        if key in seen or key not in meta:
            continue
        seen.add(key)
        value = meta[key]
        if value is None:
            continue
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, list):
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {_quote_yaml(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _frontmatter_parse(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.S)
    if not match:
        return {}, text
    meta: dict[str, Any] = {}
    for raw in match.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or ":" not in raw:
            continue
        key, raw_value = raw.split(":", 1)
        key, raw_value = key.strip(), raw_value.strip()
        if not key:
            continue
        if raw_value.lower() in ("true", "false"):
            meta[key] = raw_value.lower() == "true"
        elif raw_value.startswith("[") and raw_value.endswith("]"):
            try:
                meta[key] = json.loads(raw_value)
            except Exception:
                meta[key] = []
        elif raw_value.startswith('"') or raw_value.startswith("'"):
            try:
                meta[key] = json.loads(raw_value) if raw_value.startswith('"') else raw_value.strip("'")
            except Exception:
                meta[key] = raw_value.strip('"\'')
        else:
            try:
                meta[key] = int(raw_value)
            except Exception:
                meta[key] = raw_value
    body = text[match.end():]
    return meta, body


def _normalize_projects(meta: dict[str, Any]) -> dict[str, Any]:
    raw = meta.get("projects")
    values: list[str] = []
    if isinstance(raw, list):
        values = [str(x).strip() for x in raw if str(x).strip()]
    elif isinstance(raw, str):
        values = [x.strip() for x in re.split(r"[,，]", raw) if x.strip()]
    legacy = str(meta.get("project") or "").strip()
    if legacy and legacy not in values:
        values.insert(0, legacy)
    # de-duplicate while preserving order
    dedup: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value); dedup.append(value)
    meta["projects"] = dedup
    meta["project"] = dedup[0] if dedup else ""
    # v261008.2 · 归属清空时同步清掉镜像的 id 字段，否则索引仍会按项目归属计入
    # （`document_projects` 同时看 project_name 与 project_id，只清名字会留下幽灵归属）
    if not dedup:
        meta["project_id"] = ""
        meta["project_ids"] = []
    return meta


def _kind_path(kind: str) -> Path:
    dirs = kind_dir_map()
    if kind not in dirs:
        raise ValueError(f"Unknown kind: {kind}")
    return ensure_workspace() / dirs[kind]


def _iter_docs(kinds: list[str] | None = None):
    target_kinds = kinds or list(kind_dir_map())
    for kind in target_kinds:
        root = _kind_path(kind)
        root.mkdir(parents=True, exist_ok=True)
        for path in sorted(root.glob("*.md")):
            yield kind, path


def _doc_from_path(kind: str, path: Path, include_body: bool = True, root: Path | None = None) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    meta, body = _frontmatter_parse(text)
    meta.setdefault("id", path.stem)
    meta.setdefault("kind", kind)
    meta.setdefault("title", path.stem)
    meta.setdefault("status", (kind_statuses(kind) or ["草稿"])[0])
    meta.setdefault("project", "")
    meta.setdefault("projects", [])
    meta.setdefault("tags", [])
    if kind == "milestone":
        meta.setdefault("start_date", "")
        meta.setdefault("due", "")
        meta.setdefault("progress", None)
        if meta["progress"] is not None:
            try:
                progress = float(meta["progress"])
                meta["progress"] = progress if math.isfinite(progress) and 0 <= progress <= 100 else None
            except (TypeError, ValueError):
                meta["progress"] = None
    if isinstance(meta.get("kind_marks"), str):
        meta["kind_marks"] = [x.strip() for x in re.split(r"[,，]", meta["kind_marks"]) if x.strip()]
    if not isinstance(meta.get("kind_marks"), list):
        meta["kind_marks"] = []
    meta["kind_marks"] = [str(x).strip() for x in meta["kind_marks"] if str(x).strip()]
    _normalize_projects(meta)
    if isinstance(meta.get("tags"), str):
        meta["tags"] = [t.strip() for t in meta["tags"].split(",") if t.strip()]
    doc = dict(meta)
    doc["revision"] = document_revision(text)
    if kind == "milestone":
        doc["status_class"] = milestone_status_class(doc.get("status"))
    doc["filename"] = path.name
    # v261009.36 · 热路径优化：调用方可传入 root，避免**每条文档**都走一次 ensure_workspace()。
    # 实测 200 条文档时它占 /api/docs 的 0.77s（ensure_workspace 每次会做 ~24 次 mkdir + stat）。
    doc["path"] = str(path.relative_to(root if root is not None else ensure_workspace())).replace("\\", "/")
    doc["excerpt"] = _excerpt(body)
    if include_body:
        doc["body"] = body
    if kind == "literature":
        bib = BIBTEX_BLOCK_RE.search(body)
        doc["bibtex"] = str(meta["bibtex"] or "") if "bibtex" in meta else (bib.group(1).strip() if bib else "")
    return doc


def _excerpt(body: str, limit: int = 180) -> str:
    cleaned = re.sub(r"```.*?```", " ", body, flags=re.S)
    cleaned = re.sub(r"!\[[^\]]*\]\([^\)]*\)", " ", cleaned)
    cleaned = re.sub(r"[#>*_`\-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit]


_EN_STOPWORDS = {
    "the", "a", "an", "in", "on", "of", "for", "and", "or", "to", "with", "by", "from", "as", "at",
    "is", "are", "be", "been", "was", "were", "that", "this", "it", "its", "into", "than", "then",
    "there", "here", "we", "our", "not", "can", "will", "would", "which", "when", "where", "how",
    "what", "who", "their", "them", "these", "those", "over", "under", "between", "within",
    "without", "through", "during", "before", "after", "based", "using", "via", "etc", "novel",
}  # v260930d · M5 英文虚词停用表：文献标题拆词后大量介词/冠词会误命中页面文本


def _title_terms(title: str, kind: str) -> list[str]:
    """v260930d · M5 从条目标题提取匹配候选词：知识类取名称段（去掉 知识-<类别>- 前缀），
    其他类去掉单段前缀。文献类论文原题只整题参与、不拆词——论文名单词（detection 等）
    与页面文本撞词太常见，噪声远大于信号；整题命中仅发生在"页面正来自这篇文献"时，才是真相关。"""
    t = str(title or "").strip()
    if not t:
        return []
    name = t
    if kind == "note" and t.startswith("知识-"):
        parts = t.split("-")
        if len(parts) >= 3:
            name = "-".join(parts[2:])
    else:
        for prefix in ("总结-", "灵感-", "日志-", "里程碑-", "文献-", "知识-"):
            if t.startswith(prefix):
                name = t[len(prefix):]
                break
    name = name.strip()
    if not name:
        return []
    terms = [name]
    if kind != "literature":  # 非文献类才拆词补充短词候选
        for w in re.split(r"[\s/、,，;；()（）]+", name):
            w = w.strip()
            lw = w.lower()
            if lw in _EN_STOPWORDS:
                continue
            if re.fullmatch(r"[A-Za-z]+", w) and len(w) < 4 and not w.isupper():
                continue  # 短英文介词/冠词排除；全大写缩写（SCR/CW）保留
            if len(w) >= 2 and w not in terms:
                terms.append(w)
    return terms


def _term_in_text(term: str, low_text: str) -> bool:
    """v260930i · 英文纯字母词按整词匹配（SCR 不得命中 description），容忍简单词形变化
    （filters/filtering/estimated 这类 s/es/ed/ing 后缀），中文/混合词保留子串。"""
    tl = term.lower()
    if tl.isascii() and tl.isalpha():
        stem = tl[:-1] if tl.endswith("e") else tl  # estimate → estimated/estimates/estimating
        return re.search(rf"(?<![a-z0-9]){re.escape(stem)}e?(?:s|es|ed|ing)?(?![a-z0-9])", low_text) is not None
    return tl in low_text


_RELATED_CACHE: tuple[tuple[str, int], list] | None = None


def match_related(page_text: str, limit: int = 8) -> list[dict[str, Any]]:
    """v260930d · M5 阅读中知识关联：把页面正文与全库条目的标题名称段/标签做文本匹配，
    返回本页出现过的知识条目（纯字符串匹配，不依赖 LLM）。命中按权重降序：
    整名称段命中 > 长 token > 多 token；返回 hits 供前端高亮。
    v260930i · 抗噪：英文整词匹配 + 最低相关门槛（整段命中必进；否则需 score≥4 或 ≥2 个独立命中）。"""
    text = str(page_text or "")
    if len(text.strip()) < 4:
        return []
    low = text.lower()
    from . import indexer
    global _RELATED_CACHE
    state = indexer.status()
    key = (state["path"], state["documents_version"])
    if _RELATED_CACHE is None or _RELATED_CACHE[0] != key:
        entries = []
        for doc in indexer.document_metadata():
            candidates = _title_terms(doc.get("title"), doc["kind"])
            n_title = len(candidates)
            for tag in doc.get("tags") or []:
                term = str(tag).strip()
                if len(term) >= 2 and term not in candidates:
                    candidates.append(term)
            entries.append((doc, candidates, n_title))
        _RELATED_CACHE = (key, entries)
    scored: dict[str, dict[str, Any]] = {}
    for doc, candidates, n_title in _RELATED_CACHE[1]:
        kind = doc["kind"]
        hits: list[str] = []
        score = 0
        full = False
        for i, term in enumerate(candidates):
            tl = term.lower()
            if tl and _term_in_text(term, low):
                hits.append(term)
                # v260930d · 权重：整名称段命中强加权；标题 token 按词长；tags 命中为弱信号（半权）
                if i == 0:
                    full = True
                    score += 50 + len(term) // 2
                elif i < n_title:
                    score += len(term)
                else:
                    score += max(1, len(term) // 2)
        if not hits:
            continue
        if len(hits) >= 2:
            score += 2
        if not full and score < 4 and len(hits) < 2:  # v260930i · 单个弱命中不足以构成关联
            continue
        scored[doc["id"]] = {
            "id": doc["id"], "title": doc.get("title"), "kind": kind,
            "kind_marks": doc.get("kind_marks") or [], "excerpt": doc.get("excerpt", ""),
            "hits": hits[:4], "score": score,
        }
    out = sorted(scored.values(), key=lambda x: (-x["score"], x["kind"] != "note", str(x["title"])))  # v260930d · 同分时知识条目优先（M5 场景主体是术语解释）
    for x in out:
        x.pop("score", None)
    return out[:max(1, min(int(limit or 8), 20))]


def list_docs(kind: str | None = None, query: str = "", status: str = "", project: str = "", mark: str = "") -> list[dict[str, Any]]:
    kinds = [kind] if kind else None
    q = query.strip().lower()
    labels = kind_label_map()
    root = ensure_workspace()          # v261009.36 · 循环外取一次（原来每条文档各取一次）
    out = []
    for k, path in _iter_docs(kinds):
        doc = _doc_from_path(k, path, include_body=False, root=root)
        if status and doc.get("status") != status:
            continue
        if project and project not in (doc.get("projects") or ([doc.get("project")] if doc.get("project") else [])):
            continue
        marks = doc.get("kind_marks") or []
        if mark and mark not in marks:
            continue
        if q:
            try:
                _, full_body = _frontmatter_parse(path.read_text(encoding="utf-8"))
            except Exception:
                full_body = ""
            hay = " ".join([
                str(doc.get("title", "")), str(doc.get("excerpt", "")), " ".join(doc.get("projects", [])),
                " ".join(doc.get("tags", [])), " ".join(str(labels.get(m, m)) for m in marks),
                str(doc.get("authors", "")), str(doc.get("venue", "")),
                str(doc.get("doi", "")), str(doc.get("cite_key", "")), full_body,
            ]).lower()
            if q not in hay:
                continue
        out.append(doc)
    out.sort(key=lambda d: str(d.get("updated") or d.get("created") or ""), reverse=True)
    return out


def get_doc(doc_id: str) -> dict[str, Any]:
    for kind, path in _iter_docs():
        try:
            meta, _ = _frontmatter_parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("id") == doc_id or path.stem == doc_id:
            return _doc_from_path(kind, path, include_body=True)
    raise FileNotFoundError(doc_id)


def get_docs_by_ids(doc_ids) -> dict[str, dict[str, Any]]:
    """v260929 · 批量按 id 取 doc：一次目录遍历按 stem 预筛、仅命中文件读盘（O(N) 次读取），
    替代逐条 get_doc 的 O(N×M) 全库扫描；stem 未命中再按 get_doc 兜底（几乎不触发）。"""
    id_set = {str(x) for x in (doc_ids or []) if str(x)}
    out: dict[str, dict[str, Any]] = {}
    if not id_set:
        return out
    hit: dict[str, tuple[str, Path]] = {}
    for kind, path in _iter_docs():
        if path.stem in id_set and path.stem not in hit:
            hit[path.stem] = (kind, path)
    for doc_id, (kind, path) in hit.items():
        try:
            out[doc_id] = _doc_from_path(kind, path, include_body=True)
        except Exception:
            pass
    for doc_id in id_set - set(out):
        try:
            out[doc_id] = get_doc(doc_id)
        except Exception:
            pass
    return out


def resolve_attachment(meta: dict[str, Any]) -> Path | None:
    """v260923 · 解析文献 PDF 附件路径：绝对路径直接用，相对路径相对 Workspace。
    仅接受 .pdf 且文件真实存在，其余一律视为无附件。"""
    raw = str(meta.get("attachment") or "").strip().strip('"').strip("'")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = ensure_workspace() / raw
    try:
        path = path.resolve()
    except OSError:
        return None
    if path.suffix.lower() != ".pdf" or not path.is_file():
        return None
    return path


def attachment_file(doc_id: str) -> Path | None:
    """v260923 · 取指定文献的 PDF 附件文件（不存在或配置无效时返回 None）。"""
    from . import indexer
    return resolve_attachment(indexer.get_doc(doc_id))


def _make_default_body(kind: str, title: str, payload: dict[str, Any]) -> str:
    """正文骨架：内置类型走契约单源 core/contracts/kinds.py；自定义类型 / 配置模板覆盖走 kind_template（v3 自定义知识类型）。"""
    overrides = _knowledge_cfg().get("templates")
    overridden = isinstance(overrides, dict) and str(kind) in overrides
    if overridden or kind not in contracts.kind_dir_map():
        template = kind_template(kind)
        bibtex = payload.get("bibtex") or contracts.DEFAULT_BIBTEX
        return (
            template
            .replace("{{title}}", title)
            .replace("{{date}}", _today())
            .replace("{{bibtex}}", str(bibtex).strip())
            .rstrip() + "\n"
        )
    return contracts.default_body(kind, title, payload)


def _enforce_write(kind: str, payload: dict[str, Any], *, partial: bool = False, title: str = "") -> None:
    """写入前的字段硬校验（v261009 · P16 根因修复）。

    这些规则原先只写在文档里、写入期零校验，于是库里真的出现了越界 status 与越界标记。
    现在两条写入路径（HTTP 的 store 与 MCP 工具层）都过这里。
    `level=error` 直接拒写；warn 级只提示，不阻断。
    """
    issues = contract_validate.validate_write(
        kind, payload, partial=partial, title=title, allowed_marks=allowed_marks(),
    )
    if contract_validate.errors(issues):
        raise ValueError("字段校验未通过：" + contract_validate.summarize(issues))


def prepare_doc(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build an editor draft without files, events or index entries."""
    if kind not in kind_dir_map():
        raise ValueError("Invalid kind")
    title = str(payload.get("title") or f"未命名{kind_label_map().get(kind, kind)}").strip()
    # 契约强制的标记在此补齐（两条写入路径一致；此前只有 MCP 侧补，HTTP 侧不补）
    payload = {**payload, "kind_marks": contract_naming.derive_marks(kind, title, payload.get("kind_marks"))}
    _enforce_write(kind, payload, title=title)
    doc_id = f"{kind}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    now = _now()
    meta: dict[str, Any] = {
        "id": doc_id,
        "kind": kind,
        "title": title,
        "created": now,
        "updated": now,
        "status": payload.get("status") or (kind_statuses(kind) or ["草稿"])[0],
        "project": payload.get("project") or "",
        "projects": payload.get("projects") or [],
        "project_id": payload.get("project_id") or "",
        "project_ids": payload.get("project_ids") or [],
        "tags": payload.get("tags") or [],
        "kind_marks": payload.get("kind_marks") or [],
        "pinned": bool(payload.get("pinned", False)),
    }
    date_field = DATE_FIELDS.get(kind)
    if date_field:
        meta[date_field] = payload.get(date_field) or _today()
    if kind == "milestone":
        meta.update(normalize_milestone_schedule({"due": _today(), **payload}))
    if kind == "summary":
        meta["summary_type"] = payload.get("summary_type") or "阶段总结"
    if kind == "literature":
        for key in ("authors", "year", "venue", "doi", "url", "cite_key", "attachment"):
            meta[key] = payload.get(key) or ""
        if not meta["cite_key"]:
            meta["cite_key"] = _slug(title).replace("-", "_")[:48]
    _normalize_projects(meta)
    body = str(payload["body"]) if payload.get("body") is not None else _make_default_body(kind, title, payload)
    bibtex = BIBTEX_BLOCK_RE.search(body) if kind == "literature" else None
    citation = str(payload["bibtex"] or "") if "bibtex" in payload else (bibtex.group(1).strip() if bibtex else "")
    return {**meta, "body": body, "path": "", "draft": True,
            "bibtex": citation}


def normalize_milestone_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    """An optional start makes a milestone a planned phase; never infer dates/progress."""
    result: dict[str, Any] = {}
    for key, label in (("start_date", "开始日期"), ("due", "截止日期")):
        raw = str(payload.get(key) or "").strip()
        try:
            if raw and (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) or date.fromisoformat(raw).isoformat() != raw):
                raise ValueError
        except ValueError:
            raise ValueError(f"{label}须为有效的 YYYY-MM-DD 日期") from None
        result[key] = raw
    if result["start_date"] and result["due"] and result["start_date"] > result["due"]:
        raise ValueError("截止日期不能早于开始日期")
    progress = payload.get("progress")
    if progress is None or progress == "":
        result["progress"] = None
    else:
        try:
            number = float(progress)
            if isinstance(progress, bool) or not math.isfinite(number) or not 0 <= number <= 100:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("完成进度须为 0–100 的数字，或留空") from None
        result["progress"] = round(number, 1)
    return result


def create_doc(kind: str, payload: dict[str, Any], origin: dict[str, str] | None = None,
               _skip_versioning: bool = False) -> dict[str, Any]:
    """新建条目。`origin` 记录来源（ui/agent/mcp/plugin/cli + 工具名 + 外部客户端名）。"""
    meta = prepare_doc(kind, payload)
    body = meta.pop("body")
    for key in ("path", "draft"):
        meta.pop(key)
    if kind != "literature":
        meta.pop("bibtex", None)
    doc_id, title, now = meta["id"], meta["title"], meta["created"]
    # v261009.41 · 来源追踪 + 版本归族（写入收口点：界面 / Agent / MCP / 插件四条路径一视同仁）
    _origin = dict(origin or _versions.origin("cli"))
    meta.update({k: v for k, v in _origin.items() if v})
    # 显式 variant_of **永远生效**（数据本身）；`_skip_versioning` 只跳过"按标题自动归族"
    variant_of = str(payload.get("variant_of") or "").strip()
    if variant_of:
        meta["variant_of"] = variant_of
        meta["variant_label"] = str(payload.get("variant_label") or "").strip() or "副本"
    elif not _skip_versioning:
        base = _versions.find_same_signature(kind, title, exclude_id=doc_id)
        if base:
            meta["variant_of"] = base
            meta["variant_label"] = _versions.label_from_title(title, kind=kind) or "副本"
    if meta.get("variant_of"):
        # v261009.45 · 这条**分支的创建时间**（开分支工具会给；自动归族时取此刻）。
        # 必须在这里（写文件之前）—— 放到文件写完后再 setdefault 是无效的（实测踩到）。
        meta["variant_at"] = str(payload.get("variant_at") or "").strip() or now
    for project_name in meta.get("projects", []):
        ensure_project(project_name)
    path = _kind_path(kind) / f"{doc_id}.md"
    with _LOCK:
        _atomic_write(path, _frontmatter_dump(meta) + body.rstrip() + "\n")
    activity.record("doc_create", ref=doc_id, kind=kind, title=title,
                    project=str(meta.get("project") or ""),
                    source=_versions.describe_origin(meta))
    if meta.get("variant_of"):
        # v261009.45 · 这条分支的**创建时间**（开分支工具会给；自动归族时取此刻）
        meta.setdefault("variant_at", str(payload.get("variant_at") or "") or now)
    if meta.get("variant_of"):        # 变体一落地就给基条打标记（mark 自身走 _skip_versioning，无递归）
        _versions.mark_base_forked(str(meta["variant_of"]), True)
    return _doc_from_path(kind, path, include_body=True)


def update_doc(doc_id: str, payload: dict[str, Any], origin: dict[str, str] | None = None,
               _skip_versioning: bool = False, now: str = "") -> dict[str, Any]:
    """更新条目。`origin` 同 create_doc；**分叉/冲突时先留一版**（见 app/versions.py）。

    `now` 由调用方给出写入时间（缺省取本机当前秒）：索引层在写入锁内已算过一次时间，
    再传进来可让同一次写入在文件与返回值里保持同一时刻，也便于测试冻结时钟。
    """
    doc = get_doc(doc_id)
    kind = doc["kind"]
    # 可写字段的唯一声明处在 core/contracts/kinds.py（UPDATE_FIELDS）；body 走正文分支
    allowed = set(contracts.UPDATE_FIELDS) - {"body"}
    incoming = {k: v for k, v in payload.items() if k in allowed}
    _enforce_write(kind, incoming, partial=True, title=str(incoming.get("title") or doc.get("title") or ""))
    # v261009.41 · 分叉/冲突时先留一版（用户选定：只在分叉/冲突/归档时留版本，日常编辑仍覆盖式）
    _origin = dict(origin or _versions.origin("cli"))
    _prev_surface = str(doc.get("origin_surface") or "").strip()
    _new_surface = str(_origin.get("origin_surface") or "").strip()
    _forked = bool(doc.get("has_variants"))          # O(1)：基条上的标记，由内核在分叉/归档时维护
    # 冲突 = 写入来源变了。两种情况都算：
    #   ① 上一次写入者已知且与本次不同；
    #   ② 上一次写入者**未知**（历史条目从没记过 origin_*）而本次是**外部/代理写入**
    #      （agent / mcp / plugin / cli）——"外部 Agent 改了既有笔记"必须留下可追溯的版本。
    #      界面自己保存（ui）不算冲突，否则每改一条历史笔记都会凭空多一版。
    _conflict = bool(_new_surface) and (
        (_prev_surface != _new_surface and bool(_prev_surface))
        or (not _prev_surface and _new_surface != "ui"))
    if (not _skip_versioning) and (not _versions.is_variant(doc)) and (_forked or _conflict):
        _versions.snapshot_before_write(
            doc, reason="分叉期间保留写入前内容" if _forked else f"来源变化 {_prev_surface}->{_new_surface}")
    path = ensure_workspace() / doc["path"]
    text = path.read_text(encoding="utf-8")
    meta, body = _frontmatter_parse(text)
    for key in allowed:
        if key in payload:
            meta[key] = payload[key]
    meta["updated"] = now or _now()
    meta.update({k: v for k, v in _origin.items() if v})   # v261009.41 · 记录本次写入者
    if "body" in payload:
        body = str(payload.get("body") or "")
    if kind == "literature" and "bibtex" in payload:
        bib = str(payload.get("bibtex") or "").strip()
        block = f"```bibtex\n{bib}\n```" if bib else "```bibtex\n\n```"
        if BIBTEX_BLOCK_RE.search(body):
            body = BIBTEX_BLOCK_RE.sub(lambda _m: block, body, count=1)
        else:
            body = f"## BibTeX\n\n{block}\n\n" + body
    _normalize_projects(meta)
    for project_name in meta.get("projects", []):
        ensure_project(project_name)
    with _LOCK:
        _atomic_write(path, _frontmatter_dump(meta) + body.rstrip() + "\n")
    activity.record("doc_update", ref=doc_id, kind=kind, title=str(meta.get("title") or doc_id),
                    project=str(meta.get("project") or ""),
                    source=_versions.describe_origin(meta))   # v261009.41 · 谁写的（界面/Agent/MCP/插件）
    return _doc_from_path(kind, path, include_body=True)


def _sync_h1(body: str, title: str) -> str:
    """把正文首个 H1 改为给定标题（``title``/H1 必须一致）。"""
    lines = (body or "").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            lines[i] = f"# {title}"
            return "\n".join(lines)
    return f"# {title}\n\n" + (body or "").lstrip("\n")


def change_kind(
    doc_id: str,
    new_kind: str,
    new_title: str = "",
    *,
    status: str = "",
    kind_marks: list[str] | None = None,
) -> dict[str, Any]:
    """v261008.2 · 把条目改挂到另一类 kind（目录随动、H1 同步）。

    结构性迁移专用：`id` 与 `created` 保持不变，仅 `kind`/`title`/`status`/`updated` 等变化；
    跨条目引用由调用方（工具层/迁移脚本）用 `naming.rewrite_references` 同步。
    """
    if new_kind not in kind_dir_map():
        raise ValueError(f"Invalid kind: {new_kind}")
    doc = get_doc(doc_id)
    old_kind = str(doc.get("kind") or "")
    if old_kind == new_kind:
        raise ValueError(f"条目已是 {new_kind} 类型")
    src = ensure_workspace() / doc["path"]
    meta, body = _frontmatter_parse(src.read_text(encoding="utf-8"))
    title = str(new_title or meta.get("title") or doc_id).strip()
    meta["kind"] = new_kind
    meta["title"] = title
    meta["updated"] = _now()
    allowed = kind_statuses(new_kind)
    if status and (not allowed or status in allowed):
        meta["status"] = status
    elif allowed and str(meta.get("status") or "") not in allowed:
        meta["status"] = allowed[0]
    if kind_marks is not None:
        merged = [str(m).strip() for m in kind_marks if str(m).strip()]
        if merged:
            meta["kind_marks"] = merged
    date_field = DATE_FIELDS.get(new_kind)
    if date_field and not meta.get(date_field):
        meta[date_field] = _today()
    body = _sync_h1(body, title)
    dst = _kind_path(new_kind) / src.name
    with _LOCK:
        dst.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(dst, _frontmatter_dump(meta) + body.rstrip() + "\n")
        if dst.resolve() != src.resolve():
            src.unlink()
    activity.record("doc_update", ref=doc_id, kind=new_kind, title=title,
                    project=str(meta.get("project") or ""))
    return _doc_from_path(new_kind, dst, include_body=True)


def delete_doc(doc_id: str) -> dict:
    doc = get_doc(doc_id)
    path = ensure_workspace() / doc["path"]
    trash = ensure_workspace() / "System" / "Trash" / doc["kind"]
    trash.mkdir(parents=True, exist_ok=True)
    target = trash / f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{path.name}"
    with _LOCK:
        shutil.move(str(path), str(target))
    activity.record("doc_delete", ref=doc_id, kind=doc.get("kind", ""), title=doc.get("title", doc_id), project=doc.get("project", ""))
    return {"ok": True}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_asset(data_url: str, original_name: str = "image.png") -> dict[str, Any]:
    match = re.match(r"^data:([\w.+-]+/[\w.+-]+);base64,(.+)$", data_url, flags=re.S)
    if not match:
        raise ValueError("Invalid data URL")
    mime, raw = match.groups()
    allowed = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
    if mime not in allowed:
        raise ValueError("仅支持 PNG / JPEG / WebP / GIF 图片")
    blob = base64.b64decode(raw, validate=True)
    if len(blob) > 15 * 1024 * 1024:
        raise ValueError("Image exceeds 15 MB")
    signatures = {
        "image/png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
        "image/webp": lambda b: len(b) > 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP",
        "image/gif": lambda b: b.startswith((b"GIF87a", b"GIF89a")),
    }
    if not signatures[mime](blob):
        raise ValueError("图片内容与 MIME 类型不匹配")
    ext = allowed[mime]
    date_dir = datetime.now().strftime("%Y/%m")
    root = ensure_workspace() / "Knowledge" / "Attachments" / date_dir
    root.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}{ext}"
    path = root / filename
    with _LOCK:
        path.write_bytes(blob)
    rel = str(path.relative_to(ensure_workspace())).replace("\\", "/")
    # Documents live directly under Knowledge/<Kind>, so this is portable in Obsidian/VS Code.
    markdown_rel = "../Attachments/" + "/".join(rel.split("/")[2:])
    return {
        "ok": True,
        "path": rel,
        "url": "/workspace-file/" + rel,
        "markdown": f"![{Path(original_name).stem}]({markdown_rel})",
        "size": len(blob),
    }


def _bundle_body(body: str) -> str:
    # A knowledge bundle is stored two levels below Knowledge/. Make image links portable.
    body = re.sub(r"\(/workspace-file/Knowledge/Attachments/([^\)]+)\)", r"(../../Attachments/\1)", body)
    body = body.replace("(../Attachments/", "(../../Attachments/")
    return body.strip()

def save_bundle(filename: str, content: str) -> dict:
    root = ensure_workspace() / "Knowledge" / "Exports" / "KnowledgeBundles"
    root.mkdir(parents=True, exist_ok=True)
    name = _slug(Path(filename or "knowledge-bundle").stem) + ".md"
    path = root / name
    if path.exists():
        path = root / f"{path.stem}-{datetime.now().strftime('%H%M%S')}.md"
    with _LOCK:
        _atomic_write(path, content)
    activity.record("knowledge_export", ref=path.name, kind="bundle", title=path.stem)
    return {"ok": True, "path": str(path.relative_to(ensure_workspace())).replace("\\", "/")}


def _date_only(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except Exception:
        try:
            return date.fromisoformat(raw[:10])
        except Exception:
            return None


def _academic_progress(profile: dict[str, Any], today: date) -> dict[str, Any]:
    start = _date_only(profile.get("start_date"))
    end = _date_only(profile.get("expected_end_date"))
    data: dict[str, Any] = {
        "degree_name": str(profile.get("degree_name") or "学业进度"),
        "start_date": start.isoformat() if start else "",
        "expected_end_date": end.isoformat() if end else "",
        "configured": bool(start and end and end > start),
        "percent": 0.0,
        "elapsed_days": 0,
        "remaining_days": 0,
        "weekly_goal_days": max(1, min(7, int(profile.get("weekly_goal_days") or 5))),
    }
    if data["configured"]:
        total = max(1, (end - start).days)
        elapsed = (today - start).days
        data["elapsed_days"] = max(0, elapsed)
        data["remaining_days"] = max(0, (end - today).days)
        data["percent"] = round(max(0.0, min(100.0, elapsed / total * 100.0)), 1)
    conditions = []
    for item in profile.get("graduation_conditions") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "未命名条件").strip()
        try:
            current = float(item.get("current") or 0)
            target = float(item.get("target") or 0)
        except Exception:
            current, target = 0.0, 0.0
        conditions.append({
            "label": label,
            "current": current,
            "target": target,
            "unit": str(item.get("unit") or ""),
            "percent": round(max(0.0, min(100.0, current / target * 100.0)), 1) if target > 0 else 0.0,
            "done": bool(target > 0 and current >= target),
        })
    data["graduation_conditions"] = conditions
    data["conditions_done"] = sum(1 for x in conditions if x["done"])
    data["conditions_total"] = len(conditions)
    return data


def _research_activity(docs: list[dict[str, Any]], todo_items: list[dict[str, Any]], today: date, days: int = 400) -> dict[str, Any]:
    from datetime import timedelta

    start = today - timedelta(days=max(30, days - 1))
    buckets: dict[str, dict[str, Any]] = {}

    def add(day: date | None, category: str, weight: int = 1):
        if not day or day < start or day > today:
            return
        key = day.isoformat()
        row = buckets.setdefault(key, {"date": key, "count": 0, "breakdown": {}})
        w = max(1, int(weight or 1))
        row["count"] += w
        row["breakdown"][category] = row["breakdown"].get(category, 0) + w

    events = activity.list_events(start)
    logged: set[tuple[str, str, str]] = set()
    for event in events:
        day = _date_only(event.get("timestamp"))
        typ = str(event.get("type") or "activity")
        ref = str(event.get("ref") or "")
        if day:
            logged.add((ref, day.isoformat(), typ))
        add(day, typ, int(event.get("weight") or 1))

    # Seed historical data from Markdown metadata so a new install is not an empty heatmap.
    for doc in docs:
        ref = str(doc.get("id") or "")
        created = _date_only(doc.get("created"))
        updated = _date_only(doc.get("updated"))
        if created and (ref, created.isoformat(), "doc_create") not in logged:
            add(created, "doc_create")
        if updated and updated != created and (ref, updated.isoformat(), "doc_update") not in logged:
            add(updated, "doc_update")

    for item in todo_items:
        ref = str(item.get("id") or "")
        created = _date_only(item.get("created"))
        updated = _date_only(item.get("updated"))
        if created and (ref, created.isoformat(), "todo_create") not in logged:
            add(created, "todo_create")
        if updated and updated != created and (ref, updated.isoformat(), "todo_update") not in logged:
            add(updated, "todo_update")

    rows = []
    d = start
    while d <= today:
        key = d.isoformat()
        rows.append(buckets.get(key, {"date": key, "count": 0, "breakdown": {}}))
        d += timedelta(days=1)

    current_month = today.strftime("%Y-%m")
    month_rows = [x for x in rows if x["date"].startswith(current_month)]
    active_days = sum(1 for x in month_rows if x["count"] > 0)
    month_events = sum(x["count"] for x in month_rows)

    streak = 0
    cursor = today
    by_date = {x["date"]: x["count"] for x in rows}
    while cursor >= start and by_date.get(cursor.isoformat(), 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)

    longest = 0
    run = 0
    for x in rows:
        if x["count"] > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0

    month_totals: dict[str, dict[str, int]] = {}
    for x in rows:
        month = x["date"][:7]
        m = month_totals.setdefault(month, {"events": 0, "active_days": 0})
        m["events"] += x["count"]
        if x["count"] > 0:
            m["active_days"] += 1

    return {
        "start": start.isoformat(),
        "end": today.isoformat(),
        "days": rows,
        "active_days_month": active_days,
        "events_month": month_events,
        "current_streak": streak,
        "longest_streak": longest,
        "month_totals": [{"month": k, **v} for k, v in sorted(month_totals.items())],
    }


def dashboard() -> dict[str, Any]:
    from . import todos as todo_store

    docs = list_docs()
    kinds: dict[str, list[dict[str, Any]]] = {}
    for d in docs:
        kinds.setdefault(d["kind"], []).append(d)
    today_obj = date.today()
    today = today_obj.isoformat()
    upcoming = sorted(
        [d for d in kinds.get("milestone", []) if d.get("due") and d.get("status") != "完成"],
        key=lambda d: d.get("due", "9999-99-99"),
    )[:8]
    todo_items = todo_store.list_todos()
    project_names = projects()
    project_stats = []
    for name in project_names:
        project_docs = [d for d in docs if name in (d.get("projects") or ([d.get("project")] if d.get("project") else []))]
        project_todos = [t for t in todo_items if str(t.get("project") or "").strip() == name and not t.get("done")]
        project_milestones = [d for d in project_docs if d.get("kind") == "milestone"]
        timestamps = [str(d.get("updated") or d.get("created") or "") for d in project_docs]
        timestamps += [str(t.get("updated") or t.get("created") or "") for t in todo_items if str(t.get("project") or "").strip() == name]
        last_updated = max([x for x in timestamps if x], default="")
        project_stats.append({
            "name": name,
            "docs": len(project_docs),
            "open_todos": len(project_todos),
            "milestones": len(project_milestones),
            "literature": sum(1 for d in project_docs if d.get("kind") == "literature"),
            "notes": sum(1 for d in project_docs if d.get("kind") in {"note", "journal", "idea"}),
            "last_updated": last_updated,
        })
    project_stats.sort(key=lambda x: (x.get("last_updated") or "", x.get("name") or ""), reverse=True)
    profile = config.get_app().get("academic_profile") or {}
    return {
        "counts": {k: len(v) for k, v in kinds.items()},
        "recent": {
            "ideas": kinds.get("idea", [])[:3],
            "journals": kinds.get("journal", [])[:3],
            "notes": kinds.get("note", [])[:3],
            "summaries": kinds.get("summary", [])[:3],
            "literature": kinds.get("literature", [])[:3],
        },
        "upcoming_milestones": upcoming,
        "today": today,
        "projects": project_names,
        "project_stats": project_stats,
        "academic": _academic_progress(profile, today_obj),
        "activity": _research_activity(docs, todo_items, today_obj),
    }


# ---------------------------------------------------------------- 跨模块公开 API（v261009）
# 索引/查询层原先直接调用下面的私有实现，私有签名一改就会连带破掉上层；
# 这里给出稳定入口，跨模块调用一律走它。

def doc_from_path(kind: str, path: Path, include_body: bool = True) -> dict[str, Any]:
    """读单个条目文件为 doc 字典（公开入口，供索引层使用）。"""
    return _doc_from_path(kind, path, include_body=include_body)


def academic_progress(profile: dict[str, Any], today: date) -> dict[str, Any]:
    """学业进度摘要（公开入口，供索引/仪表盘层使用）。"""
    return _academic_progress(profile, today)
