from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ROOT, get_app, workspace_root
from . import activity

_LOCK = threading.RLock()
_MIGRATION_CHECKED = False

WORKSPACE_LAYOUT = [
    "Knowledge/Ideas",
    "Knowledge/Journals",
    "Knowledge/Notes",
    "Knowledge/Milestones",
    "Knowledge/Summaries",
    "Knowledge/Literature",
    "Knowledge/Literature/PDF",
    "Knowledge/Literature/Annotations",
    "Knowledge/Literature/Notes",
    "Knowledge/Literature/Index",
    "Knowledge/Literature/Previews",
    "Knowledge/Attachments",
    "Knowledge/Exports/KnowledgeBundles",
    "Knowledge/Exports/BibTeX",
    "Projects",
    "Resources",
    "System/Trash",
    "System/Cache",
    "System/AgentChats/Attachments",
    "System/AgentChats/Trash",
]

PROJECT_LAYOUT = [
    "Notes", "Experiments", "Data", "Results", "Figures", "Manuscript", "References"
]

LEGACY_RELATIVE = {
    "data/research_os/ideas": "Knowledge/Ideas",
    "data/research_os/notes": "Knowledge/Notes",
    "data/research_os/milestones": "Knowledge/Milestones",
    "data/research_os/summaries": "Knowledge/Summaries",
    "data/research_os/assets": "Knowledge/Attachments/Legacy",
    "data/research_logs": "Knowledge/Journals",
    "data/summary_cards": "Knowledge/Literature/Legacy",
    "data/files": "Resources/LegacyFiles",
    "data/folders": "Resources/LegacyFolders",
}


def ensure_workspace(run_migration: bool = True) -> Path:
    global _MIGRATION_CHECKED
    with _LOCK:
        root = workspace_root()
        root.mkdir(parents=True, exist_ok=True)
        for rel in WORKSPACE_LAYOUT:
            (root / rel).mkdir(parents=True, exist_ok=True)
        _write_workspace_readme(root)
        # Legacy discovery can scan sibling projects and should never run on every CRUD call.
        # Run it once per process; Reload / manual rescan call migrate_legacy explicitly.
        if run_migration and not _MIGRATION_CHECKED and get_app().get("workspace_migration", {}).get("enabled", True):
            _MIGRATION_CHECKED = True
            migrate_legacy(root)
        return root


def reset_runtime_state() -> None:
    global _MIGRATION_CHECKED
    with _LOCK:
        _MIGRATION_CHECKED = False


def _write_workspace_readme(root: Path) -> None:
    path = root / "README.md"
    if path.exists():
        return
    path.write_text(
        "# Workspace\n\n"
        "本目录由科研工作台自动管理。核心科研 Markdown 位于 `Knowledge/`，"
        "项目工程目录位于 `Projects/`，普通附件与外部资源位于 `Resources/`。\n\n"
        "建议直接用 Git/同步工具备份整个 Workspace。\n",
        encoding="utf-8",
    )


def ensure_project(name: str) -> Path | None:
    name = str(name or "").strip()
    if not name:
        return None
    # Prevent path traversal and accidental nested project creation via metadata.
    safe = name.replace("\\", "-").replace("/", "-").replace("..", "-").strip(" .")[:100]
    if not safe:
        return None
    root = ensure_workspace() / "Projects" / safe
    root.mkdir(parents=True, exist_ok=True)
    for rel in PROJECT_LAYOUT:
        (root / rel).mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {safe}\n\n"
            "本目录由科研工作台自动创建。研究知识本体仍保存在 `Workspace/Knowledge/`，"
            "这里用于实验、数据、结果、图件、稿件和参考资料等工程文件。\n",
            encoding="utf-8",
        )
    return root


def _candidate_roots() -> list[Path]:
    roots = [ROOT]
    parent = ROOT.parent
    try:
        for child in parent.iterdir():
            if not child.is_dir() or child.resolve() == ROOT.resolve():
                continue
            n = child.name.lower()
            if "academic-workbench" in n or "research-workbench" in n or "科研" in child.name:
                roots.append(child)
    except OSError:
        pass
    out, seen = [], set()
    for r in roots:
        try: key = str(r.resolve())
        except OSError: key = str(r)
        if key not in seen:
            seen.add(key); out.append(r)
    return out


def detect_legacy_sources() -> list[dict[str, str]]:
    found = []
    current_ws = workspace_root().resolve()
    for base in _candidate_roots():
        for rel, dest in LEGACY_RELATIVE.items():
            src = base / rel
            try:
                if src.exists() and current_ws not in src.resolve().parents and src.resolve() != current_ws:
                    found.append({"source": str(src), "destination": dest})
            except OSError:
                continue
    return found


def _same_file(src: Path, dest: Path) -> bool:
    try:
        if src.stat().st_size != dest.stat().st_size:
            return False
        # Hash small/medium knowledge files; for large resources size+mtime is enough.
        if src.stat().st_size <= 8 * 1024 * 1024:
            def digest(p: Path):
                h=hashlib.sha256()
                with p.open('rb') as f:
                    for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
                return h.digest()
            return digest(src) == digest(dest)
        return int(src.stat().st_mtime) == int(dest.stat().st_mtime)
    except OSError:
        return False


def migrate_legacy(root: Path | None = None, force_scan: bool = False) -> dict[str, Any]:
    """Incremental, non-destructive migration.

    It scans known legacy directories on each startup, but only copies files that do not
    exist at the destination (or when a collision is detected, saves a timestamped copy).
    The source is never deleted.
    """
    root = root or workspace_root()
    marker = root / "System" / "migration.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    previous: dict[str, Any] = {}
    if marker.exists():
        try: previous = json.loads(marker.read_text(encoding="utf-8"))
        except Exception: previous = {}

    copied: list[dict[str, str]] = []
    sources = detect_legacy_sources()
    copy_enabled = bool(get_app().get("workspace_migration", {}).get("copy_legacy_data", True))
    if copy_enabled:
        for item in sources:
            src = Path(item["source"])
            dest = root / item["destination"]
            dest.mkdir(parents=True, exist_ok=True)
            files = [src] if src.is_file() else [x for x in src.rglob("*") if x.is_file() and not x.is_symlink()]
            for source_file in files:
                try:
                    rel = source_file.name if src.is_file() else str(source_file.relative_to(src))
                    target = dest / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        if _same_file(source_file, target):
                            continue
                        # Never overwrite user data. Keep a collision copy next to the target.
                        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                        target = target.with_name(f"{target.stem}-migrated-{stamp}{target.suffix}")
                    shutil.copy2(source_file, target)
                    copied.append({"from": str(source_file), "to": str(target)})
                except Exception:
                    continue

    history = previous.get("history", []) if isinstance(previous.get("history"), list) else []
    record = {
        "performed_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "incremental-copy" if copy_enabled else "scan-only",
        "sources_found": len(sources),
        "copied_count": len(copied),
        "copied": copied[:500],
    }
    history.append({k: record[k] for k in ("performed_at", "sources_found", "copied_count")})
    record["history"] = history[-30:]
    tmp_marker = marker.with_suffix(".tmp")
    tmp_marker.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_marker.replace(marker)
    return record


def migration_status() -> dict[str, Any]:
    root = workspace_root()
    marker = root / "System" / "migration.json"
    if marker.exists():
        try: return json.loads(marker.read_text(encoding="utf-8"))
        except Exception: pass
    return {"performed_at": None, "copied_count": 0, "copied": [], "sources_found": 0}


def _safe_under_workspace(rel: str) -> Path:
    root = ensure_workspace().resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes Workspace")
    return target


def create_folder(rel: str) -> dict:
    path = _safe_under_workspace(rel)
    path.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": str(path.relative_to(ensure_workspace())).replace("\\", "/")}


def create_project(name: str) -> dict:
    p = ensure_project(name)
    if not p:
        raise ValueError("项目名称不能为空")
    activity.record("project_create", ref=p.name, kind="project", title=p.name, project=p.name)
    return {"ok": True, "name": p.name, "path": str(p.relative_to(ensure_workspace())).replace("\\", "/")}


def tree(max_depth: int = 6, max_entries: int = 1800) -> dict:
    root = ensure_workspace()
    count = 0

    def walk(path: Path, depth: int) -> dict:
        nonlocal count
        node = {"name": path.name if path != root else "Workspace", "path": "" if path == root else str(path.relative_to(root)).replace("\\", "/"), "type": "dir" if path.is_dir() else "file"}
        if path.is_file():
            try:
                stat = path.stat(); node["size"] = stat.st_size; node["modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
            except OSError: pass
            return node
        if depth >= max_depth or count >= max_entries:
            node["truncated"] = True; return node
        children = []
        try: items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError: items = []
        for item in items:
            if item.name.startswith(".") or item.is_symlink():
                continue
            count += 1
            if count > max_entries:
                node["truncated"] = True; break
            children.append(walk(item, depth + 1))
        node["children"] = children
        return node
    return walk(root, 0)


def open_path(rel: str = "") -> dict:
    path = _safe_under_workspace(rel)
    if not path.exists(): raise FileNotFoundError(str(path))
    target = path if path.is_dir() else path.parent
    if sys.platform.startswith("win"):
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin": subprocess.Popen(["open", str(target)])
    else: subprocess.Popen(["xdg-open", str(target)])
    return {"ok": True, "path": str(target)}


def workspace_info() -> dict:
    root = ensure_workspace()
    return {
        "root": str(root),
        "relative": str(root.relative_to(ROOT)) if ROOT in root.parents or root == ROOT else str(root),
        "migration": migration_status(),
        "legacy_sources": detect_legacy_sources(),
        "layout": WORKSPACE_LAYOUT,
        "project_layout": PROJECT_LAYOUT,
    }
