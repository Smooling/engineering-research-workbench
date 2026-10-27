from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .workspace import ensure_workspace, ensure_project

_LOCK = threading.RLock()
PROJECT_STATUSES = ["进行中", "暂停", "完成", "归档"]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _registry_path() -> Path:
    return ensure_workspace() / "System" / "projects.json"


def _todos_path() -> Path:
    return ensure_workspace() / "System" / "todos.json"


def _atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_registry() -> list[dict[str, Any]]:
    path = _registry_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _save_registry(items: list[dict[str, Any]]) -> None:
    _atomic_json(_registry_path(), items)


def _new_id() -> str:
    return "proj_" + uuid.uuid4().hex[:12]


def _safe_name(name: str) -> str:
    value = str(name or "").strip()
    value = value.replace("\\", "-").replace("/", "-").replace("..", "-").strip(" .")[:128]
    if not value:
        raise ValueError("项目名称不能为空")
    return value


def _frontmatter(text: str) -> tuple[list[str], str] | None:
    if not text.startswith("---"):
        return None
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.S)
    if not m:
        return None
    return m.group(1).splitlines(), text[m.end():]


def _meta_from_lines(lines: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw in lines:
        if ":" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split(":", 1)
        key, value = key.strip(), value.strip()
        if not key:
            continue
        if value.startswith("[") and value.endswith("]"):
            try:
                out[key] = json.loads(value)
                continue
            except Exception:
                pass
        if value.startswith('"') and value.endswith('"'):
            try:
                out[key] = json.loads(value)
                continue
            except Exception:
                pass
        out[key] = value.strip("'\"")
    return out


def _replace_meta_lines(lines: list[str], updates: dict[str, Any]) -> list[str]:
    result = list(lines)
    index: dict[str, int] = {}
    for i, raw in enumerate(result):
        if ":" in raw and not raw.lstrip().startswith("#"):
            index[raw.split(":", 1)[0].strip()] = i
    for key, value in updates.items():
        if isinstance(value, list):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = json.dumps(str(value), ensure_ascii=False)
        line = f"{key}: {rendered}"
        if key in index:
            result[index[key]] = line
        else:
            result.append(line)
    return result


def _doc_project_names(meta: dict[str, Any]) -> list[str]:
    raw = meta.get("projects")
    values: list[str] = []
    if isinstance(raw, list):
        values.extend(str(x).strip() for x in raw if str(x).strip())
    elif isinstance(raw, str):
        values.extend(x.strip() for x in re.split(r"[,，]", raw) if x.strip())
    legacy = str(meta.get("project") or "").strip()
    if legacy and legacy not in values:
        values.insert(0, legacy)
    return list(dict.fromkeys(values))


def _doc_project_ids(meta: dict[str, Any]) -> list[str]:
    raw = meta.get("project_ids")
    values: list[str] = []
    if isinstance(raw, list):
        values.extend(str(x).strip() for x in raw if str(x).strip())
    elif isinstance(raw, str):
        values.extend(x.strip() for x in re.split(r"[,，]", raw) if x.strip())
    legacy = str(meta.get("project_id") or "").strip()
    if legacy and legacy not in values:
        values.insert(0, legacy)
    return list(dict.fromkeys(values))


def _iter_markdown() -> list[Path]:
    root = ensure_workspace() / "Knowledge"
    return [p for p in root.rglob("*.md") if p.is_file() and "Exports" not in p.parts]


def _load_todos() -> list[dict[str, Any]]:
    p = _todos_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_todos(items: list[dict[str, Any]]) -> None:
    _atomic_json(_todos_path(), items)


def _record_for_name(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    key = str(name or "").strip().casefold()
    return next((x for x in items if str(x.get("name") or "").casefold() == key), None)


def _record_for_id(items: list[dict[str, Any]], project_id: str) -> dict[str, Any] | None:
    return next((x for x in items if x.get("id") == project_id), None)


def ensure_registry() -> dict[str, Any]:
    """Create/repair the project registry and migrate legacy name-based associations.

    The migration is additive and idempotent. Markdown keeps the old `project`/`projects`
    names for backward compatibility, while `project_id`/`project_ids` become the stable keys.
    """
    with _LOCK:
        root = ensure_workspace()
        items = _load_registry()
        changed = False
        now = _now()

        known_names: list[str] = []
        project_root = root / "Projects"
        project_root.mkdir(parents=True, exist_ok=True)
        known_names.extend(p.name for p in project_root.iterdir() if p.is_dir())

        docs_cache: list[tuple[Path, list[str], str, dict[str, Any]]] = []
        for path in _iter_markdown():
            try:
                parsed = _frontmatter(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not parsed:
                continue
            lines, body = parsed
            meta = _meta_from_lines(lines)
            docs_cache.append((path, lines, body, meta))
            known_names.extend(_doc_project_names(meta))

        todos = _load_todos()
        known_names.extend(str(x.get("project") or "").strip() for x in todos if str(x.get("project") or "").strip())

        for raw_name in known_names:
            name = str(raw_name or "").strip()
            if not name or _record_for_name(items, name):
                continue
            ensure_project(name)
            items.append({
                "id": _new_id(),
                "name": name,
                "description": "",
                "status": "进行中",
                "created": now,
                "updated": now,
            })
            changed = True

        # Repair malformed/old records.
        seen_ids: set[str] = set()
        for item in items:
            if not item.get("id") or item.get("id") in seen_ids:
                item["id"] = _new_id(); changed = True
            seen_ids.add(str(item["id"]))
            item["name"] = _safe_name(str(item.get("name") or "未命名项目"))
            if "description" not in item:
                item["description"] = ""; changed = True
            if item.get("status") not in PROJECT_STATUSES:
                item["status"] = "进行中"; changed = True
            if not item.get("created"):
                item["created"] = now; changed = True
            if not item.get("updated"):
                item["updated"] = item["created"]; changed = True

        if changed or not _registry_path().exists():
            _save_registry(items)

        by_name = {str(x["name"]).casefold(): x for x in items}
        migrated_docs = 0
        for path, lines, body, meta in docs_cache:
            names = _doc_project_names(meta)
            ids = _doc_project_ids(meta)
            resolved: list[str] = []
            for pid in ids:
                if _record_for_id(items, pid) and pid not in resolved:
                    resolved.append(pid)
            for name in names:
                rec = by_name.get(name.casefold())
                if rec and rec["id"] not in resolved:
                    resolved.append(rec["id"])
            desired = {"project_id": resolved[0] if resolved else "", "project_ids": resolved}
            if _doc_project_ids(meta) != resolved or str(meta.get("project_id") or "") != desired["project_id"]:
                new_lines = _replace_meta_lines(lines, desired)
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text("---\n" + "\n".join(new_lines) + "\n---\n\n" + body.lstrip("\n"), encoding="utf-8")
                tmp.replace(path)
                migrated_docs += 1

        migrated_todos = 0
        for item in todos:
            name = str(item.get("project") or "").strip()
            rec = by_name.get(name.casefold()) if name else None
            desired = rec["id"] if rec else ""
            if str(item.get("project_id") or "") != desired:
                item["project_id"] = desired
                migrated_todos += 1
        if migrated_todos:
            _save_todos(todos)

        return {"ok": True, "projects": len(items), "migrated_docs": migrated_docs, "migrated_todos": migrated_todos}


def list_projects() -> list[dict[str, Any]]:
    ensure_registry()
    items = _load_registry()
    docs: list[tuple[dict[str, Any], Path]] = []
    for path in _iter_markdown():
        try:
            parsed = _frontmatter(path.read_text(encoding="utf-8"))
            if not parsed:
                continue
            meta = _meta_from_lines(parsed[0])
            docs.append((meta, path))
        except Exception:
            continue
    todos = _load_todos()
    for rec in items:
        pid = str(rec.get("id") or "")
        name = str(rec.get("name") or "")
        related = [(m, p) for m, p in docs if pid in _doc_project_ids(m) or name in _doc_project_names(m)]
        related_todos = [x for x in todos if x.get("project_id") == pid or str(x.get("project") or "") == name]
        timestamps = [str(m.get("updated") or m.get("created") or "") for m, _ in related]
        timestamps += [str(x.get("updated") or x.get("created") or "") for x in related_todos]
        timestamps.append(str(rec.get("updated") or rec.get("created") or ""))
        rec["last_updated"] = max((x for x in timestamps if x), default="")
        rec["docs"] = len(related)
        rec["open_todos"] = sum(1 for x in related_todos if not x.get("done"))
        rec["milestones"] = sum(1 for m, _ in related if str(m.get("kind") or "") == "milestone")
    return sorted(items, key=lambda x: (str(x.get("last_updated") or ""), str(x.get("name") or "")), reverse=True)


def create_project(name: str, description: str = "", status: str = "进行中", display_name: str = "") -> dict[str, Any]:
    display_name = str(display_name or "").strip()
    if len(display_name) > 32:
        raise ValueError("项目显示简称不能超过 32 个字符")
    with _LOCK:
        ensure_registry()
        safe = _safe_name(name)
        items = _load_registry()
        if _record_for_name(items, safe):
            raise ValueError("已存在同名项目，请编辑现有项目")
        ensure_project(safe)
        now = _now()
        rec = {
            "id": _new_id(), "name": safe, "description": str(description or "").strip(),
            "status": status if status in PROJECT_STATUSES else "进行中",
            "created": now, "updated": now, "display_name": display_name,
        }
        items.append(rec); _save_registry(items)
        return {"ok": True, **rec, "path": f"Projects/{safe}"}


def update_project(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .sync_engine import mutation_lock
    with mutation_lock:
        return _update_project(project_id, payload)


def _update_project(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    display_name = str(payload.get("display_name") or "").strip()
    if "display_name" in payload and len(display_name) > 32:
        raise ValueError("项目显示简称不能超过 32 个字符")
    if "status" in payload and str(payload.get("status") or "") not in PROJECT_STATUSES:
        raise ValueError("无效项目状态")
    with _LOCK:
        ensure_registry()
        items = _load_registry()
        rec = _record_for_id(items, project_id)
        if not rec:
            raise FileNotFoundError(project_id)
        old_name = str(rec.get("name") or "")
        new_name = _safe_name(str(payload.get("name") if "name" in payload else old_name))
        other = _record_for_name(items, new_name)
        if other and other.get("id") != project_id:
            raise ValueError("已存在同名项目")

        old_dir = ensure_workspace() / "Projects" / old_name
        new_dir = ensure_workspace() / "Projects" / new_name
        project_root = (ensure_workspace() / "Projects").resolve()
        if old_dir.resolve().parent != project_root or new_dir.resolve().parent != project_root:
            raise ValueError("项目目录必须位于 Workspace/Projects 内")
        renamed = False
        backups: dict[Path, bytes | None] = {}
        if new_name != old_name:
            if new_dir.exists() and new_dir.resolve() != old_dir.resolve():
                raise ValueError("目标项目目录已存在")
            # Snapshot before the first mutation so a failed multi-file update
            # restores exact document revisions, task data and the registry.
            for path in [*_iter_markdown(), _todos_path(), _registry_path()]:
                backups[path] = path.read_bytes() if path.exists() else None
        if "description" in payload:
            rec["description"] = str(payload.get("description") or "").strip()
        if "display_name" in payload:
            rec["display_name"] = display_name
        if "status" in payload:
            rec["status"] = str(payload["status"])
        rec["updated"] = _now()
        old_exists = old_dir.exists()
        try:
            if new_name != old_name:
                if old_exists:
                    old_dir.rename(new_dir)
                    renamed = True
                else:
                    new_dir.mkdir()
                    renamed = True
                    ensure_project(new_name)
                _rename_legacy_associations(project_id, old_name, new_name)
                rec["name"] = new_name
            _save_registry(items)
        except Exception:
            for path, original in backups.items():
                if original is None:
                    path.unlink(missing_ok=True)
                elif not path.exists() or path.read_bytes() != original:
                    path.write_bytes(original)
            if renamed:
                if old_exists:
                    new_dir.rename(old_dir)
                else:
                    # This directory was exclusively created by this attempt.
                    if new_dir.resolve().parent != project_root:
                        raise ValueError("无法恢复项目目录：路径已改变")
                    shutil.rmtree(new_dir)
            raise
        return {"ok": True, **rec}


def delete_project(project_id: str) -> dict[str, Any]:
    with _LOCK:
        ensure_registry()
        items = _load_registry()
        rec = _record_for_id(items, project_id)
        if not rec:
            raise FileNotFoundError(project_id)
        name = str(rec.get("name") or "")
        _remove_associations(project_id, name)
        project_dir = ensure_workspace() / "Projects" / name
        if project_dir.exists():
            trash = ensure_workspace() / "System" / "Trash" / "Projects"
            trash.mkdir(parents=True, exist_ok=True)
            dest = trash / f"{name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            shutil.move(str(project_dir), str(dest))
        _save_registry([x for x in items if x.get("id") != project_id])
        return {"ok": True, "id": project_id, "name": name}


def _rename_legacy_associations(project_id: str, old_name: str, new_name: str) -> None:
    for path in _iter_markdown():
        try:
            parsed = _frontmatter(path.read_text(encoding="utf-8"))
            if not parsed:
                continue
            lines, body = parsed; meta = _meta_from_lines(lines)
            ids = _doc_project_ids(meta); names = _doc_project_names(meta)
            if project_id not in ids and old_name not in names:
                continue
            names = [new_name if x == old_name else x for x in names]
            names = list(dict.fromkeys(names))
            updates = {"project": names[0] if names else "", "projects": names, "project_id": ids[0] if ids else project_id, "project_ids": ids or [project_id]}
            new_lines = _replace_meta_lines(lines, updates)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text("---\n" + "\n".join(new_lines) + "\n---\n\n" + body.lstrip("\n"), encoding="utf-8"); tmp.replace(path)
        except Exception:
            raise
    todos = _load_todos(); changed = False
    for item in todos:
        if item.get("project_id") == project_id or str(item.get("project") or "") == old_name:
            item["project_id"] = project_id; item["project"] = new_name; item["updated"] = _now(); changed = True
    if changed: _save_todos(todos)


def _remove_associations(project_id: str, name: str) -> None:
    for path in _iter_markdown():
        try:
            parsed = _frontmatter(path.read_text(encoding="utf-8"))
            if not parsed: continue
            lines, body = parsed; meta = _meta_from_lines(lines)
            ids = [x for x in _doc_project_ids(meta) if x != project_id]
            names = [x for x in _doc_project_names(meta) if x != name]
            if len(ids) == len(_doc_project_ids(meta)) and len(names) == len(_doc_project_names(meta)):
                continue
            updates = {"project": names[0] if names else "", "projects": names, "project_id": ids[0] if ids else "", "project_ids": ids}
            new_lines = _replace_meta_lines(lines, updates)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text("---\n" + "\n".join(new_lines) + "\n---\n\n" + body.lstrip("\n"), encoding="utf-8"); tmp.replace(path)
        except Exception:
            continue
    todos = _load_todos(); changed = False
    for item in todos:
        if item.get("project_id") == project_id or str(item.get("project") or "") == name:
            item["project_id"] = ""; item["project"] = ""; item["updated"] = _now(); changed = True
    if changed: _save_todos(todos)
