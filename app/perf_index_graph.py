from __future__ import annotations

from collections import deque
import sqlite3
from datetime import datetime
from typing import Any

from . import store
from .perf_index_core import (
    DEFAULT_GRAPH_LIMIT, MAX_GRAPH_LIMIT, OVERVIEW_GRAPH_LIMIT, _connect, _init_db, _registry, _root, _row_doc, ensure_ready,
)
from .perf_index_query import get_doc

def _project_virtuals(conn: sqlite3.Connection, doc_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not doc_ids:
        return {}
    placeholders = ",".join("?" for _ in doc_ids)
    rows = conn.execute(
        f"SELECT DISTINCT project_name,project_id FROM document_projects WHERE doc_id IN ({placeholders})",
        list(doc_ids),
    ).fetchall()
    registry = {str(x.get("id") or ""): x for x in _registry()}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row["project_name"] or "")
        pid = str(row["project_id"] or "")
        key = pid or name
        if not key:
            continue
        rec = registry.get(pid, {})
        out["project:" + key] = {
            "id": "project:" + key, "label": name or str(rec.get("name") or key), "kind": "project",
            "virtual": True, "project_id": pid, "status": str(rec.get("status") or ""),
        }
    return out


def _tag_virtuals(conn: sqlite3.Connection, doc_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not doc_ids:
        return {}
    placeholders = ",".join("?" for _ in doc_ids)
    rows = conn.execute(
        f"SELECT DISTINCT tag FROM document_tags WHERE doc_id IN ({placeholders})", list(doc_ids)
    ).fetchall()
    return {
        "tag:" + str(r["tag"]): {"id": "tag:" + str(r["tag"]), "label": str(r["tag"]), "kind": "tag", "virtual": True}
        for r in rows if str(r["tag"] or "").strip()
    }


def graph(limit: int = DEFAULT_GRAPH_LIMIT) -> dict[str, Any]:
    ensure_ready()
    limit = max(1, min(MAX_GRAPH_LIMIT, int(limit or DEFAULT_GRAPH_LIMIT)))
    with _connect() as conn:
        _init_db(conn)
        total = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY COALESCE(NULLIF(updated,''),created) DESC LIMIT ?", (limit,)
        ).fetchall()
        docs = [_row_doc(r) for r in rows]
        ids = {str(d["id"]) for d in docs}
        virtuals = {}
        virtuals.update(_project_virtuals(conn, ids)); virtuals.update(_tag_virtuals(conn, ids))
        allowed = ids | set(virtuals)
        edges = []
        if ids:
            placeholders = ",".join("?" for _ in ids)
            for row in conn.execute(
                f"SELECT source,target,relation FROM graph_edges WHERE source IN ({placeholders})",
                list(ids),
            ):
                if str(row["target"]) in allowed:
                    edges.append({"source": row["source"], "target": row["target"], "relation": row["relation"]})
    nodes = [
        {
            "id": d["id"], "label": d["title"] or d["id"], "kind": d["kind"],
            "project": d["project"], "projects": d["projects"], "project_id": d["project_id"],
            "project_ids": d["project_ids"], "tags": d["tags"], "status": d["status"],
            "updated": d["updated"], "virtual": False,
        }
        for d in docs
    ] + list(virtuals.values())
    return {
        "nodes": nodes, "edges": edges,
        "meta": {"total_documents": total, "shown_documents": len(docs), "limit": limit, "truncated": total > len(docs)},
    }


def graph_overview(limit: int = OVERVIEW_GRAPH_LIMIT) -> dict[str, Any]:
    return graph(max(20, min(120, int(limit or OVERVIEW_GRAPH_LIMIT))))


def _node_for_id(conn: sqlite3.Connection, node_id: str) -> dict[str, Any] | None:
    if node_id.startswith("tag:"):
        tag = node_id[4:]
        return {"id": node_id, "label": tag, "kind": "tag", "virtual": True, "selectable": False}
    if node_id.startswith("project:"):
        key = node_id[len("project:"):]
        for rec in _registry():
            if str(rec.get("id") or "") == key or str(rec.get("name") or "") == key:
                return {
                    "id": node_id, "label": str(rec.get("name") or key), "kind": "project", "virtual": True,
                    "project_id": str(rec.get("id") or ""), "status": str(rec.get("status") or ""), "selectable": False,
                }
        row = conn.execute(
            "SELECT project_name,project_id FROM document_projects WHERE project_id=? OR project_name=? LIMIT 1",
            (key, key),
        ).fetchone()
        if row:
            return {"id": node_id, "label": str(row["project_name"] or key), "kind": "project", "virtual": True, "selectable": False}
        return {"id": node_id, "label": key, "kind": "project", "virtual": True, "selectable": False}
    row = conn.execute("SELECT * FROM documents WHERE id=?", (node_id,)).fetchone()
    if not row:
        return None
    d = _row_doc(row)
    return {
        "id": d["id"], "label": d["title"], "kind": d["kind"], "project": d["project"],
        "projects": d["projects"], "project_id": d["project_id"], "project_ids": d["project_ids"],
        "tags": d["tags"], "status": d["status"], "updated": d["updated"], "virtual": False,
        "selectable": True, "excerpt": d["excerpt"],
    }


def graph_neighborhood(root_id: str, depth: int = 1) -> dict[str, Any]:
    ensure_ready()
    depth = 2 if int(depth or 1) >= 2 else 1
    with _connect() as conn:
        _init_db(conn)
        dist = {root_id: 0}; q = deque([root_id]); edges_seen: set[tuple[str, str, str]] = set()
        while q:
            cur = q.popleft()
            if dist[cur] >= depth:
                continue
            rows = conn.execute(
                "SELECT source,target,relation FROM graph_edges WHERE source=? OR target=?", (cur, cur)
            ).fetchall()
            for row in rows:
                a, b, rel = str(row["source"]), str(row["target"]), str(row["relation"])
                edges_seen.add((a, b, rel))
                nxt = b if a == cur else a
                if nxt not in dist:
                    dist[nxt] = dist[cur] + 1; q.append(nxt)
        items = []
        for node_id, d in sorted(dist.items(), key=lambda x: x[1]):
            node = _node_for_id(conn, node_id)
            if node:
                items.append({**node, "distance": d})
    return {
        "root": root_id, "depth": depth, "items": items,
        "edges": [{"source": a, "target": b, "relation": r} for a, b, r in sorted(edges_seen)],
    }


def build_bundle(
    root_id: str,
    selected_ids: list[str],
    title: str = "",
    active_node_ids: list[str] | None = None,
    relations: list[dict[str, Any]] | None = None,
) -> str:
    ensure_ready()
    with _connect() as conn:
        _init_db(conn)
        root_node = _node_for_id(conn, str(root_id or ""))
        if not root_node:
            raise ValueError("图谱核心节点不存在")
        docs_to_include: list[str] = []
        seen: set[str] = set()
        if not root_node.get("virtual"):
            docs_to_include.append(str(root_id)); seen.add(str(root_id))
        for doc_id in selected_ids or []:
            doc_id = str(doc_id or "")
            if not doc_id or doc_id in seen or doc_id.startswith(("tag:", "project:")):
                continue
            if conn.execute("SELECT 1 FROM documents WHERE id=?", (doc_id,)).fetchone():
                seen.add(doc_id); docs_to_include.append(doc_id)
        active = set(str(x) for x in (active_node_ids or []) if str(x))
        if not active:
            active = set(docs_to_include) | {str(root_id)}
        active.add(str(root_id)); active.update(docs_to_include)
        relation_rows: list[dict[str, str]] = []
        if relations is not None:
            for raw in relations:
                source = str(raw.get("source") or ""); target = str(raw.get("target") or "")
                relation = str(raw.get("relation") or "")
                if not source or not target or source not in active or target not in active:
                    continue
                valid = conn.execute(
                    "SELECT 1 FROM graph_edges WHERE relation=? AND "
                    "((source=? AND target=?) OR (source=? AND target=?)) LIMIT 1",
                    (relation, source, target, target, source),
                ).fetchone()
                if valid:
                    relation_rows.append({"source": source, "target": target, "relation": relation})
        elif active:
            placeholders = ",".join("?" for _ in active)
            args = list(active) + list(active)
            rows = conn.execute(
                f"SELECT source,target,relation FROM graph_edges "
                f"WHERE source IN ({placeholders}) AND target IN ({placeholders})",
                args,
            ).fetchall()
            relation_rows = [dict(r) for r in rows]
        node_map: dict[str, dict[str, Any]] = {}
        for node_id in active:
            node = _node_for_id(conn, node_id)
            if node:
                node_map[node_id] = node
    root_label = str(root_node.get("label") or root_id)
    root_kind = str(root_node.get("kind") or "")
    bundle_title = str(title or "").strip() or f"{root_label} · 关联资料汇总"
    root_desc = f"{store.kind_label_map().get(root_kind, root_kind)}：{root_label}" if root_node.get("virtual") else f"[[{root_label}]]"
    lines = [
        f"# {bundle_title}", "", f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"> 核心节点：{root_desc}", "> 关系索引仅包含生成时知识图谱当前可见的节点类别与关系类型。", "", "## 关系索引", "",
    ]
    relation_label = {"wikilink": "引用", "tag": "标签", "project": "项目"}
    if relation_rows:
        for edge in relation_rows:
            a = node_map.get(edge["source"], {"label": edge["source"]})
            b = node_map.get(edge["target"], {"label": edge["target"]})
            lines.append(f"- {a.get('label')} → {b.get('label')} `{relation_label.get(edge['relation'], edge['relation'])}`")
    else:
        lines.append("- 当前所选内容在当前图谱筛选条件下没有可见关系边。")
    lines.extend(["", "---", ""])
    for idx, doc_id in enumerate(docs_to_include, 1):
        doc = get_doc(doc_id)
        projects = doc.get("projects") or ([doc.get("project")] if doc.get("project") else [])
        body = str(doc.get("body") or "")
        if hasattr(store, "_bundle_body"):
            body = store._bundle_body(body)
        lines.extend([
            f"## {idx}. {doc.get('title')}", "", f"- 类型：{store.kind_label_map().get(doc.get('kind'), doc.get('kind'))}",
            f"- 项目：{', '.join(projects) or '—'}", f"- 状态：{doc.get('status') or '—'}", f"- 标签：{', '.join(doc.get('tags') or []) or '—'}", "",
            body.strip(), "", "---", "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def export_bibtex(ids: list[str] | None = None) -> dict[str, Any]:
    ensure_ready()
    selected = list(dict.fromkeys(str(x) for x in (ids or []) if str(x)))
    with _connect() as conn:
        _init_db(conn)
        if selected:
            placeholders = ",".join("?" for _ in selected)
            rows = conn.execute(
                f"SELECT id,path,kind,title FROM documents WHERE id IN ({placeholders})", selected,
            ).fetchall()
        else:
            rows = conn.execute("SELECT id,path,kind,title FROM documents WHERE kind='literature' ORDER BY updated DESC").fetchall()
    blocks: list[str] = []
    missing: list[dict[str, str]] = []
    by_id = {str(row["id"]): row for row in rows}
    selected = selected or list(by_id)
    for doc_id in selected:
        row = by_id.get(doc_id)
        if row is None:
            missing.append({"id": doc_id, "title": "", "reason": "not_found"})
            continue
        if row["kind"] != "literature":
            missing.append({"id": doc_id, "title": row["title"], "reason": "not_literature"})
            continue
        path = _root() / str(row["path"])
        try:
            # Match the document reader: explicit empty metadata must suppress
            # legacy body citations, while missing metadata may fall back.
            doc = store._doc_from_path("literature", path, include_body=False)
            bib = doc["bibtex"].strip()
            if bib:
                blocks.append(bib)
            else:
                missing.append({"id": doc_id, "title": row["title"], "reason": "missing_bibtex"})
        except Exception:
            missing.append({"id": doc_id, "title": row["title"], "reason": "read_failed"})
    content = "\n\n".join(blocks).strip() + ("\n" if blocks else "")
    out_root = _root() / "Knowledge" / "Exports" / "BibTeX"
    out_root.mkdir(parents=True, exist_ok=True)
    filename = f"literature-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.bib"
    path = out_root / filename
    path.write_text(content, encoding="utf-8")
    return {"ok": True, "count": len(blocks), "selected_count": len(selected), "exported_count": len(blocks),
            "missing": missing, "content": content, "path": str(path.relative_to(_root())).replace("\\", "/")}
