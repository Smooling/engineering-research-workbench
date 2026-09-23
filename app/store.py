from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import shutil
import uuid
import threading
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .workspace import ensure_workspace, ensure_project
from . import activity, config

BUILTIN_KIND_DIR = {
    "idea": "Knowledge/Ideas",
    "journal": "Knowledge/Journals",
    "note": "Knowledge/Notes",
    "milestone": "Knowledge/Milestones",
    "summary": "Knowledge/Summaries",
    "literature": "Knowledge/Literature",
}

BUILTIN_KIND_LABEL = {
    "idea": "灵感",
    "journal": "研究日志",
    "note": "笔记",
    "milestone": "里程碑",
    "summary": "工作总结",
    "literature": "文献",
}

BUILTIN_STATUSES = {
    "idea": ["待整理", "探索中", "已采纳", "已归档"],
    "journal": ["记录", "复盘", "已归档"],
    "note": ["草稿", "整理中", "稳定", "已归档"],
    "milestone": ["计划", "进行中", "受阻", "完成"],
    "summary": ["草稿", "已定稿", "已归档"],
    "literature": ["待阅读", "阅读中", "已精读", "已归档"],
}

def kind_dir_map() -> dict[str, str]:
    return dict(BUILTIN_KIND_DIR)


def kind_label_map() -> dict[str, str]:
    return dict(BUILTIN_KIND_LABEL)


def kind_statuses(kind: str) -> list[str]:
    return list(BUILTIN_STATUSES.get(kind, []))


def all_statuses() -> dict[str, list[str]]:
    return dict(BUILTIN_STATUSES)

DATE_FIELDS = {
    "journal": "record_date",
    "milestone": "due",
    "summary": "record_date",
    "literature": "added_date",
}

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
BIBTEX_BLOCK_RE = re.compile(r"```bibtex\s*\n(.*?)```", re.S | re.I)
_LOCK = threading.RLock()


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
    ordered = [
        "id", "kind", "title", "created", "updated", "status", "project", "projects", "tags",
        "kind_marks", "record_date", "due", "added_date", "summary_type", "pinned", "authors", "year",
        "venue", "doi", "url", "cite_key"
    ]
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


def _doc_from_path(kind: str, path: Path, include_body: bool = True) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    meta, body = _frontmatter_parse(text)
    meta.setdefault("id", path.stem)
    meta.setdefault("kind", kind)
    meta.setdefault("title", path.stem)
    meta.setdefault("status", (kind_statuses(kind) or ["草稿"])[0])
    meta.setdefault("project", "")
    meta.setdefault("projects", [])
    meta.setdefault("tags", [])
    if isinstance(meta.get("kind_marks"), str):
        meta["kind_marks"] = [x.strip() for x in re.split(r"[,，]", meta["kind_marks"]) if x.strip()]
    if not isinstance(meta.get("kind_marks"), list):
        meta["kind_marks"] = []
    meta["kind_marks"] = [str(x).strip() for x in meta["kind_marks"] if str(x).strip()]
    _normalize_projects(meta)
    if isinstance(meta.get("tags"), str):
        meta["tags"] = [t.strip() for t in meta["tags"].split(",") if t.strip()]
    doc = dict(meta)
    doc["filename"] = path.name
    doc["path"] = str(path.relative_to(ensure_workspace())).replace("\\", "/")
    doc["excerpt"] = _excerpt(body)
    if include_body:
        doc["body"] = body
    if kind == "literature":
        bib = BIBTEX_BLOCK_RE.search(body)
        doc["bibtex"] = bib.group(1).strip() if bib else ""
    return doc


def _excerpt(body: str, limit: int = 180) -> str:
    cleaned = re.sub(r"```.*?```", " ", body, flags=re.S)
    cleaned = re.sub(r"!\[[^\]]*\]\([^\)]*\)", " ", cleaned)
    cleaned = re.sub(r"[#>*_`\-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit]


def list_docs(kind: str | None = None, query: str = "", status: str = "", project: str = "", mark: str = "") -> list[dict[str, Any]]:
    kinds = [kind] if kind else None
    q = query.strip().lower()
    labels = kind_label_map()
    out = []
    for k, path in _iter_docs(kinds):
        doc = _doc_from_path(k, path, include_body=False)
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


def _make_default_body(kind: str, title: str, payload: dict[str, Any]) -> str:
    if kind == "idea":
        return f"# {title}\n\n## 想法\n\n\n## 为什么值得记录\n\n\n## 下一步\n\n- [ ] \n"
    if kind == "journal":
        return f"# {title}\n\n## 今日进展\n\n\n## 关键发现\n\n\n## 问题与阻塞\n\n\n## 下一步\n\n- [ ] \n"
    if kind == "note":
        return f"# {title}\n\n## 摘要\n\n\n## 正文\n\n\n## 关联\n\n"
    if kind == "milestone":
        return f"# {title}\n\n## 目标\n\n\n## 验收条件\n\n- [ ] \n\n## 进展记录\n\n"
    if kind == "summary":
        return f"# {title}\n\n## 本阶段完成\n\n\n## 结果与产出\n\n\n## 问题与经验\n\n\n## 下一阶段\n\n- [ ] \n"
    if kind == "literature":
        bibtex = payload.get("bibtex") or "@article{cite_key,\n  title = {},\n  author = {},\n  year = {}\n}"
        return (
            f"# {title}\n\n"
            "## BibTeX\n\n"
            f"```bibtex\n{bibtex.strip()}\n```\n\n"
            "## 核心结论\n\n\n"
            "## 方法与数据\n\n\n"
            "## 与当前研究的关系\n\n\n"
            "## 摘录与批注\n\n"
        )
    return f"# {title}\n\n## 要点\n\n\n## 正文\n\n\n## 关联\n\n"


def create_doc(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind not in kind_dir_map():
        raise ValueError("Invalid kind")
    title = str(payload.get("title") or f"未命名{kind_label_map().get(kind, kind)}").strip()
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
        "tags": payload.get("tags") or [],
        "kind_marks": payload.get("kind_marks") or [],
        "pinned": bool(payload.get("pinned", False)),
    }
    date_field = DATE_FIELDS.get(kind)
    if date_field:
        meta[date_field] = payload.get(date_field) or _today()
    if kind == "summary":
        meta["summary_type"] = payload.get("summary_type") or "阶段总结"
    if kind == "literature":
        for key in ("authors", "year", "venue", "doi", "url", "cite_key"):
            meta[key] = payload.get(key) or ""
        if not meta["cite_key"]:
            meta["cite_key"] = _slug(title).replace("-", "_")[:48]
    _normalize_projects(meta)
    body = payload.get("body") or _make_default_body(kind, title, payload)
    for project_name in meta.get("projects", []):
        ensure_project(project_name)
    path = _kind_path(kind) / f"{doc_id}.md"
    with _LOCK:
        _atomic_write(path, _frontmatter_dump(meta) + body.rstrip() + "\n")
    activity.record("doc_create", ref=doc_id, kind=kind, title=title, project=str(meta.get("project") or ""))
    return _doc_from_path(kind, path, include_body=True)


def update_doc(doc_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc = get_doc(doc_id)
    kind = doc["kind"]
    path = ensure_workspace() / doc["path"]
    text = path.read_text(encoding="utf-8")
    meta, body = _frontmatter_parse(text)
    allowed = {
        "title", "status", "project", "projects", "tags", "kind_marks", "pinned", "record_date", "due", "added_date",
        "summary_type", "authors", "year", "venue", "doi", "url", "cite_key"
    }
    for key in allowed:
        if key in payload:
            meta[key] = payload[key]
    meta["updated"] = _now()
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
    activity.record("doc_update", ref=doc_id, kind=kind, title=str(meta.get("title") or doc_id), project=str(meta.get("project") or ""))
    return _doc_from_path(kind, path, include_body=True)


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


def projects() -> list[str]:
    vals = set()
    for doc in list_docs():
        for project_name in doc.get("projects") or ([doc.get("project")] if doc.get("project") else []):
            if str(project_name).strip():
                vals.add(str(project_name).strip())
    project_root = ensure_workspace() / "Projects"
    for p in project_root.iterdir():
        if p.is_dir():
            vals.add(p.name)
    return sorted(vals, key=str.lower)


def graph() -> dict[str, Any]:
    docs = list_docs()
    by_id = {d["id"]: d for d in docs}
    by_title: dict[str, str] = {}
    for d in docs:
        by_title.setdefault(str(d.get("title", "")).strip().lower(), d["id"])
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    edge_seen: set[tuple[str, str, str]] = set()
    virtual_seen: set[str] = set()

    def add_virtual(node_id: str, label: str, kind: str) -> None:
        if node_id in virtual_seen:
            return
        virtual_seen.add(node_id)
        nodes.append({"id": node_id, "label": label, "kind": kind, "virtual": True})

    def add_edge(source: str, target: str, relation: str) -> None:
        key = tuple(sorted((source, target))) + (relation,)
        if key in edge_seen:
            return
        edge_seen.add(key)
        edges.append({"source": source, "target": target, "relation": relation})

    for d in docs:
        projects_list = d.get("projects") or ([d.get("project")] if d.get("project") else [])
        tags = [str(t).strip() for t in (d.get("tags") or []) if str(t).strip()]
        nodes.append({
            "id": d["id"], "label": d.get("title") or d["id"], "kind": d["kind"],
            "project": d.get("project") or "", "projects": projects_list, "tags": tags,
            "status": d.get("status") or "", "updated": d.get("updated") or "", "virtual": False,
        })
        for project_name in projects_list:
            project_name = str(project_name).strip()
            if not project_name:
                continue
            pid = "project:" + project_name
            add_virtual(pid, project_name, "project")
            add_edge(d["id"], pid, "project")
        for tag in tags:
            tid = "tag:" + tag
            add_virtual(tid, tag, "tag")
            add_edge(d["id"], tid, "tag")

    for d in docs:
        try:
            full = get_doc(d["id"])
        except FileNotFoundError:
            continue
        for ref in WIKILINK_RE.findall(full.get("body", "")):
            token = ref.strip()
            target = by_id.get(token, {}).get("id") if token in by_id else by_title.get(token.lower())
            if not target or target == d["id"]:
                continue
            add_edge(d["id"], target, "wikilink")
    return {"nodes": nodes, "edges": edges}


def graph_neighborhood(root_id: str, depth: int = 1) -> dict[str, Any]:
    depth = 2 if int(depth) >= 2 else 1
    g = graph()
    adjacency: dict[str, set[str]] = {}
    for e in g["edges"]:
        adjacency.setdefault(e["source"], set()).add(e["target"])
        adjacency.setdefault(e["target"], set()).add(e["source"])
    dist = {root_id: 0}
    q = deque([root_id])
    while q:
        cur = q.popleft()
        if dist[cur] >= depth:
            continue
        for nxt in adjacency.get(cur, set()):
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                q.append(nxt)
    node_map = {n["id"]: n for n in g["nodes"]}
    items = []
    for node_id, d in sorted(dist.items(), key=lambda x: (x[1], node_map.get(x[0], {}).get("label", ""))):
        node = node_map.get(node_id)
        if not node:
            continue
        if node.get("virtual"):
            items.append({**node, "distance": d, "selectable": False})
        else:
            doc = get_doc(node_id)
            items.append({**node, "distance": d, "selectable": True, "excerpt": doc.get("excerpt", "")})
    return {"root": root_id, "depth": depth, "items": items}


def build_bundle(root_id: str, selected_ids: list[str], title: str = "", active_node_ids: list[str] | None = None, relations: list[dict[str, Any]] | None = None) -> str:
    g = graph()
    node_map = {n["id"]: n for n in g["nodes"]}
    root_node = node_map.get(root_id)
    if not root_node:
        raise ValueError("图谱核心节点不存在")

    docs_to_include: list[str] = []
    seen: set[str] = set()
    # A concrete Markdown root is always included. Virtual tag/project roots are relation anchors only.
    if not root_node.get("virtual"):
        docs_to_include.append(root_id); seen.add(root_id)
    for item in selected_ids or []:
        if item in seen or item not in node_map or node_map[item].get("virtual"):
            continue
        try:
            get_doc(item)
        except FileNotFoundError:
            continue
        seen.add(item); docs_to_include.append(item)

    active_ids = set(active_node_ids or [])
    if not active_ids:
        active_ids = set(docs_to_include) | {root_id}
    active_ids.add(root_id)
    for doc_id in docs_to_include:
        active_ids.add(doc_id)

    valid_edges = {(e["source"], e["target"], e["relation"]) for e in g["edges"]}
    relation_rows: list[dict[str, str]] = []
    if relations is not None:
        for e in relations:
            key = (str(e.get("source") or ""), str(e.get("target") or ""), str(e.get("relation") or ""))
            reverse = (key[1], key[0], key[2])
            if (key in valid_edges or reverse in valid_edges) and key[0] in active_ids and key[1] in active_ids:
                relation_rows.append({"source": key[0], "target": key[1], "relation": key[2]})
    else:
        relation_rows = [e for e in g["edges"] if e["source"] in active_ids and e["target"] in active_ids]

    root_label = root_node.get("label") or root_id
    root_kind = root_node.get("kind") or ""
    bundle_title = title.strip() or f"{root_label} · 关联资料汇总"
    root_desc = f"{kind_label_map().get(root_kind, root_kind)}：{root_label}" if root_node.get("virtual") else f"[[{root_label}]]"
    lines = [
        f"# {bundle_title}", "",
        f"> 生成时间：{_now()}",
        f"> 核心节点：{root_desc}",
        "> 关系索引仅包含生成时知识图谱当前可见的节点类别与关系类型。", "",
        "## 关系索引", "",
    ]
    relation_label = {"wikilink": "引用", "tag": "标签", "project": "项目"}
    if relation_rows:
        for e in relation_rows:
            a = node_map.get(e["source"], {"label": e["source"]})
            b = node_map.get(e["target"], {"label": e["target"]})
            lines.append(f"- {a.get('label')} → {b.get('label')} `{relation_label.get(e['relation'], e['relation'])}`")
    else:
        lines.append("- 当前所选内容在当前图谱筛选条件下没有可见关系边。")
    lines.extend(["", "---", ""])

    for idx, doc_id in enumerate(docs_to_include, 1):
        doc = get_doc(doc_id)
        projects_list = doc.get("projects") or ([doc.get("project")] if doc.get("project") else [])
        lines.extend([
            f"## {idx}. {doc.get('title')}", "",
            f"- 类型：{kind_label_map().get(doc.get('kind'), doc.get('kind'))}",
            f"- 项目：{', '.join(projects_list) or '—'}",
            f"- 状态：{doc.get('status') or '—'}",
            f"- 标签：{', '.join(doc.get('tags') or []) or '—'}", "",
            _bundle_body(doc.get("body", "")), "", "---", ""
        ])
    return "\n".join(lines).rstrip() + "\n"



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


def export_bibtex(ids: list[str] | None = None) -> dict[str, Any]:
    docs = list_docs("literature")
    selected = set(ids or [])
    blocks = []
    for summary in docs:
        if selected and summary["id"] not in selected:
            continue
        doc = get_doc(summary["id"])
        bib = doc.get("bibtex", "").strip()
        if bib:
            blocks.append(bib)
    content = "\n\n".join(blocks).strip() + ("\n" if blocks else "")
    root = ensure_workspace() / "Knowledge" / "Exports" / "BibTeX"
    root.mkdir(parents=True, exist_ok=True)
    filename = f"literature-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bib"
    path = root / filename
    with _LOCK:
        _atomic_write(path, content)
    activity.record("bibtex_export", ref=path.name, kind="literature", title=f"BibTeX export ({len(blocks)})")
    return {
        "ok": True, "count": len(blocks), "content": content,
        "path": str(path.relative_to(ensure_workspace())).replace("\\", "/"),
    }


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
