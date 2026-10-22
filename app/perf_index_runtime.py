from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from . import activity, store, workspace
from . import versions
from .perf_index_db import _connect, _init_db, _root, _LOCK
from .perf_index_core import (
    _registry, _todos_path, index_doc_path, ensure_ready, sync,
    _remove_doc_conn, _affected_sources, _refresh_graph_edges, _sync_activity_conn, _refresh_status,
)

def normalize_project_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload or {})
    records = _registry()
    by_id = {str(x.get("id") or ""): x for x in records if str(x.get("id") or "")}
    by_name = {str(x.get("name") or "").casefold(): x for x in records if str(x.get("name") or "")}
    raw_ids = out.get("project_ids")
    if not isinstance(raw_ids, list):
        raw_ids = [out.get("project_id")] if out.get("project_id") else []
    ids = [str(x).strip() for x in raw_ids if str(x or "").strip()]
    raw_names = out.get("projects")
    if not isinstance(raw_names, list):
        raw_names = [out.get("project")] if out.get("project") else []
    names = [str(x).strip() for x in raw_names if str(x or "").strip()]
    resolved_ids: list[str] = []
    resolved_names: list[str] = []
    for pid in ids:
        rec = by_id.get(pid)
        if rec and pid not in resolved_ids:
            resolved_ids.append(pid)
            name = str(rec.get("name") or "").strip()
            if name and name not in resolved_names:
                resolved_names.append(name)
    for name in names:
        rec = by_name.get(name.casefold())
        if rec:
            pid = str(rec.get("id") or "").strip()
            canonical = str(rec.get("name") or name).strip()
            if pid and pid not in resolved_ids:
                resolved_ids.append(pid)
            if canonical and canonical not in resolved_names:
                resolved_names.append(canonical)
        elif name not in resolved_names:
            resolved_names.append(name)
    out["project_ids"] = resolved_ids
    out["project_id"] = resolved_ids[0] if resolved_ids else ""
    out["projects"] = resolved_names
    out["project"] = resolved_names[0] if resolved_names else ""
    return out


def apply_doc_project_ids(doc: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    path_value = str(doc.get("path") or "")
    if not path_value:
        return doc
    root = _root().resolve()
    path = (root / path_value).resolve()
    if root != path and root not in path.parents:
        raise ValueError("Path escapes Workspace")
    if not path.exists():
        return doc
    normalized = normalize_project_payload(payload)
    try:
        text = path.read_text(encoding="utf-8")
        meta, body = store._frontmatter_parse(text)
        meta["project"] = normalized.get("project") or ""
        meta["projects"] = normalized.get("projects") or []
        meta["project_id"] = normalized.get("project_id") or ""
        meta["project_ids"] = normalized.get("project_ids") or []
        store._atomic_write(path, store._frontmatter_dump(meta) + body.rstrip() + "\n")
        return store._doc_from_path(str(meta.get("kind") or doc.get("kind") or "note"), path, include_body=True)
    except Exception:
        return doc


def apply_todo_project_id(item: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_project_payload(payload)
    path = _todos_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(data, list):
            data = []
        changed = False
        for row in data:
            if isinstance(row, dict) and row.get("id") == item.get("id"):
                row["project"] = normalized.get("project") or ""
                row["project_id"] = normalized.get("project_id") or ""
                changed = True
                break
        if changed:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
    except Exception:
        pass
    return {**item, "project": normalized.get("project") or "", "project_id": normalized.get("project_id") or ""}


def normalize_project_update(existing: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Explicit edits replace old associations; untouched associations persist."""
    merged = {**existing, **payload}
    names_changed = "project" in payload or "projects" in payload
    ids_changed = "project_id" in payload or "project_ids" in payload
    if names_changed and not ids_changed:
        merged.pop("project_id", None)
        merged.pop("project_ids", None)
    if ids_changed and not names_changed:
        merged.pop("project", None)
        merged.pop("projects", None)
    if "project" in payload and "projects" not in payload:
        merged["projects"] = [payload["project"]] if payload["project"] else []
    if "project_id" in payload and "project_ids" not in payload:
        merged["project_ids"] = [payload["project_id"]] if payload["project_id"] else []
    return normalize_project_payload(merged)


def _safe_workspace_path(rel: str) -> Path:
    root = _root().resolve()
    target = (root / str(rel or "")).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes Workspace")
    return target


def _tree_node(path: Path, include_children: bool = False) -> dict[str, Any]:
    root = _root().resolve()
    node = {
        "name": path.name if path != root else "Workspace",
        "path": "" if path == root else str(path.relative_to(root)).replace("\\", "/"),
        "type": "dir" if path.is_dir() else "file",
    }
    if path.is_file():
        try:
            st = path.stat()
            node["size"] = st.st_size
            node["modified"] = datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
        except OSError:
            pass
        return node
    node["lazy"] = True
    if include_children:
        children = []
        try:
            items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
        except OSError:
            items = []
        for item in items:
            if item.name.startswith(".") or item.is_symlink():
                continue
            children.append(_tree_node(item, include_children=False))
        node["children"] = children
        node["child_count"] = len(children)
    return node


def workspace_tree_root() -> dict[str, Any]:
    return _tree_node(_root().resolve(), include_children=True)


def workspace_children(rel: str = "") -> dict[str, Any]:
    path = _safe_workspace_path(rel)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if not path.is_dir():
        raise ValueError("Path is not a directory")
    return _tree_node(path, include_children=True)


def create_doc(kind: str, payload: dict[str, Any], origin: dict[str, str] | None = None) -> dict[str, Any]:
    ensure_ready()
    with _LOCK:
        doc = store.create_doc(kind, normalize_project_payload(payload), origin=origin)
        index_doc_path(str(doc["path"]))
        return doc


def update_doc(doc_id: str, payload: dict[str, Any], origin: dict[str, str] | None = None) -> dict[str, Any]:
    """更新条目（**索引层入口**）。

    v261009.47 · 这里**改为委派给 `store.update_doc`**：此前它自己解析 frontmatter、自己 `_atomic_write`，
    于是**绕过了写入收口点**——来源记录与"分叉/冲突时先留一版"都不会发生。
    界面保存（`server.py` 走 `indexer.update_doc`）与 MCP 的 `kb_update_entry` 都在这条路上，
    所以"外部 Agent 改了既有笔记却没有修改记录和分支"就是这么来的（用户反馈）。
    现在：写入一律走 store（单一写入路径），本函数只负责同步索引。
    """
    sync()
    with _connect() as conn:
        _init_db(conn)
        row = conn.execute("SELECT path,kind FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        sync(force=True)
        with _connect() as conn:
            _init_db(conn)
            row = conn.execute("SELECT path,kind FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise FileNotFoundError(doc_id)
    path = _root() / str(row["path"])
    kind = str(row["kind"])
    # v261022.9 · 修订保护（上游 de31add）：写入前比对 expected_revision，
    # 过期写入抛 RevisionConflict（HTTP 409 / Agent 转冲突结果），文件与活动日志零副作用。
    text = path.read_text(encoding="utf-8")
    if "expected_revision" in payload:
        expected = payload["expected_revision"]
        if not isinstance(expected, str) or not expected:
            raise ValueError("expected_revision 必须是读取条目时返回的修订号")
        if expected != store.document_revision(text):
            raise store.RevisionConflict(store._doc_from_path(kind, path, include_body=True, root=_root()))

    # 走唯一写入路径：契约校验、来源记录、分叉/冲突留版、活动日志都在 store 里
    if any(key in payload for key in ("project", "projects", "project_id", "project_ids")):
        existing = store._doc_from_path(kind, path, include_body=False, root=_root())
        normalized = normalize_project_update(existing, payload)
        payload = {**payload, **{key: normalized[key] for key in
                                ("project", "projects", "project_id", "project_ids")}}
    # 排期字段归一（上游）：起止日期格式、先后顺序与 0–100 进度在写入前校验
    if kind == "milestone" and {"start_date", "due", "progress"} & payload.keys():
        existing = store._doc_from_path(kind, path, include_body=False, root=_root())
        schedule = store.normalize_milestone_schedule({**existing, **payload})
        payload = {**payload, **{key: schedule[key] for key in ("start_date", "due", "progress")}}
    doc = store.update_doc(doc_id, payload, origin=origin,
                           now=datetime.now().isoformat(timespec="seconds"))
    index_doc_path(path)
    return store._doc_from_path(kind, path, include_body=True, root=_root())


def delete_doc(doc_id: str) -> dict[str, Any]:
    result = delete_docs([doc_id])
    if result["failed"]:
        failure = result["failed"][0]
        if failure.get("error") == "FileNotFoundError":
            raise FileNotFoundError(doc_id)
        raise OSError(failure["message"])
    return {"ok": True}


def delete_docs(doc_ids: list[str]) -> dict[str, Any]:
    """Move an explicit selection to Trash, updating graph dependencies once."""
    ensure_ready()
    root = _root()
    deleted, failed, keys = [], [], set()
    with _LOCK:
        with _connect(root) as conn:
            _init_db(conn)
            for doc_id in dict.fromkeys(doc_ids):
                row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
                try:
                    if not row:
                        raise FileNotFoundError(doc_id)
                    path = root / str(row["path"])
                    trash = root / "System" / "Trash" / str(row["kind"])
                    trash.mkdir(parents=True, exist_ok=True)
                    target = trash / f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}-{path.name}"
                    shutil.move(str(path), str(target))
                except (OSError, ValueError) as exc:
                    failed.append({"id": doc_id, "message": str(exc), "error": type(exc).__name__})
                    continue
                keys.update((doc_id.casefold(), str(row["title_key"])))
                _remove_doc_conn(conn, doc_id, update_graph=False)
                deleted.append(doc_id)
                activity.record("doc_delete", ref=doc_id, kind=str(row["kind"]), title=str(row["title"] or doc_id), project=str(row["project"] or ""))
            if deleted:
                _refresh_graph_edges(conn, _affected_sources(conn, keys) - set(deleted))
                _sync_activity_conn(conn, root=root)
                conn.commit()
                _refresh_status(conn, root)
    return {"deleted": deleted, "failed": failed}
