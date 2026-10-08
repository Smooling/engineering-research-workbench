"""v261008 · 操作临时数据空间 `.scratch/`：本地专用、永不入库、按保留期自动清理。

三条边界（缺一不可）：

1. 不入版本库：`.gitignore` 采用白名单模式（`*` 兜底 + `!` 逐项放行），并额外显式声明
   `/.scratch/`，任何临时产物都不会被 `git add -A` 带走；
2. 不入同步：Syncthing 只同步 `Workspace/`（该目录下有 `.stfolder` 与 `.stignore`），
   `.scratch/` 位于其外，不会被带到其他机器；
3. 不进知识库：不写 frontmatter、不参与索引，与 `Workspace/` 六类条目和 `Projects/` 数据无关。

目录骨架（缺失时自动重建）：

- `tmp/`     通用临时文件：下载物、一次性中间产物、外部命令输出
- `verify/`  一次性验证脚本与探针
- `preview/` 截图、离屏渲染、预览产物
- `logs/`    临时日志抓取（工作台自身的 `workbench.log` 不在这里）

清理语义：

- 只删 `.scratch/` 内部的文件，按 mtime 判定「过期」——早于保留期截止点的才删；
- 骨架目录、根下 `README.md` / `.gitkeep` 永不被删；
- 删空后回收空目录并重建骨架，保证空间始终可用。

已知边界：`.scratch/` 不会被工作台 HTTP 服务暴露（静态服务只覆盖 `web/` 与 `Workspace/`），
需要浏览器打开、且要与 API 同源的预览页仍应放在 `web/` 下。
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .paths import DATA_ROOT

SCRATCH_NAME = ".scratch"
SCRATCH_DIR = DATA_ROOT / SCRATCH_NAME

#: 骨架目录，清理时保留，缺失时重建
SKELETON_DIRS = ("tmp", "verify", "preview", "logs")

#: 骨架根下永不删除的文件名
PROTECTED_NAMES = frozenset({"README.md", ".gitkeep"})

DEFAULT_RETENTION_DAYS = 7

#: 保留期环境变量（优先于默认值，便于临时改口径而无需改代码）
RETENTION_ENV = "ERW_SCRATCH_RETENTION_DAYS"

SECONDS_PER_DAY = 86400

__all__ = [
    "SCRATCH_DIR",
    "SKELETON_DIRS",
    "PROTECTED_NAMES",
    "DEFAULT_RETENTION_DAYS",
    "RETENTION_ENV",
    "resolve_retention_days",
    "ensure",
    "clean",
    "stats",
    "summarize",
    "human_size",
]


def _safe_target() -> Path:
    """校验并返回清理目标，确保它确实是数据根目录下的 `.scratch/`，避免误删。"""
    target = SCRATCH_DIR.resolve()
    root = DATA_ROOT.resolve()
    if target.name != SCRATCH_NAME:
        raise RuntimeError(f"清理目标名不是 {SCRATCH_NAME}：{target}")
    if target.parent != root:
        raise RuntimeError(f"清理目标不在数据根目录下：{target}（root={root}）")
    return target


def resolve_retention_days() -> int:
    """保留期解析：环境变量 `ERW_SCRATCH_RETENTION_DAYS` > 模块默认值。"""
    raw = os.environ.get(RETENTION_ENV, "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return DEFAULT_RETENTION_DAYS


def ensure() -> Path:
    """确保 `.scratch/` 骨架目录存在，返回其绝对路径（幂等）。"""
    target = _safe_target()
    target.mkdir(parents=True, exist_ok=True)
    for name in SKELETON_DIRS:
        (target / name).mkdir(exist_ok=True)
    return target


def _iter_files(target: Path) -> list[Path]:
    """列出目录内所有文件与符号链接（不跟随目录符号链接，避免越界）。"""
    found: list[Path] = []
    for path in target.rglob("*"):
        try:
            if path.is_file() or path.is_symlink():
                found.append(path)
        except OSError:
            continue
    return found


def _entry_mtime(path: Path, fallback: float) -> float:
    """取 mtime；断链等无法 stat 的条目按「已过期」处理（unlink 只删链接本身）。"""
    try:
        return path.stat().st_mtime
    except OSError:
        return fallback


def _prune_empty_dirs(target: Path) -> int:
    """自底向上回收空目录，返回删除数量（骨架目录随后由 ensure() 重建）。"""
    removed = 0
    dirs = sorted((p for p in target.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True)
    for path in dirs:
        if path.is_symlink():
            continue
        try:
            if any(path.iterdir()):
                continue
            path.rmdir()
            removed += 1
        except OSError:
            continue
    return removed


def clean(
    retention_days: int | None = None,
    *,
    dry_run: bool = False,
    now: float | None = None,
) -> dict[str, Any]:
    """按保留期清理 `.scratch/`，返回结构化结果。

    - `retention_days`：保留天数，`None` 时取 `resolve_retention_days()`；`0` 表示清空（保留骨架与受保护文件）。
    - `dry_run`：只统计不落盘。
    - `now`：注入当前时间（测试用）。
    """
    target = _safe_target()
    days = resolve_retention_days() if retention_days is None else max(0, int(retention_days))
    result: dict[str, Any] = {
        "dir": str(target),
        "retention_days": days,
        "dry_run": dry_run,
        "deleted": [],
        "errors": [],
        "kept": 0,
        "freed_bytes": 0,
        "dirs_removed": 0,
    }
    if not target.is_dir():
        return result

    reference = time.time() if now is None else float(now)
    cutoff = reference - days * SECONDS_PER_DAY

    for path in _iter_files(target):
        if path.parent == target and path.name in PROTECTED_NAMES:
            result["kept"] += 1
            continue
        if _entry_mtime(path, cutoff - 1.0) >= cutoff:
            result["kept"] += 1
            continue
        try:
            size = 0 if path.is_symlink() else path.stat().st_size
        except OSError:
            size = 0
        relative = path.relative_to(target).as_posix()
        if dry_run:
            result["deleted"].append(relative)
            result["freed_bytes"] += size
            continue
        try:
            path.unlink()
        except OSError as exc:
            result["errors"].append(f"{relative}: {exc}")
            continue
        result["deleted"].append(relative)
        result["freed_bytes"] += size

    if not dry_run:
        result["dirs_removed"] = _prune_empty_dirs(target)
        ensure()
    return result


def stats() -> dict[str, Any]:
    """统计当前占用情况：文件数、字节数、最旧/最新 mtime、按子目录汇总。"""
    target = _safe_target()
    info: dict[str, Any] = {
        "dir": str(target),
        "exists": target.is_dir(),
        "files": 0,
        "bytes": 0,
        "oldest": None,
        "newest": None,
        "by_dir": {},
    }
    if not info["exists"]:
        return info
    oldest: float | None = None
    newest: float | None = None
    for path in _iter_files(target):
        try:
            stat_result = path.stat()
        except OSError:
            continue
        relative = path.relative_to(target)
        bucket = relative.parts[0] if len(relative.parts) > 1 else "(根)"
        slot = info["by_dir"].setdefault(bucket, {"files": 0, "bytes": 0})
        slot["files"] += 1
        slot["bytes"] += stat_result.st_size
        info["files"] += 1
        info["bytes"] += stat_result.st_size
        oldest = stat_result.st_mtime if oldest is None else min(oldest, stat_result.st_mtime)
        newest = stat_result.st_mtime if newest is None else max(newest, stat_result.st_mtime)
    info["oldest"] = oldest
    info["newest"] = newest
    return info


def human_size(size: int | float) -> str:
    """人类可读的体量：B / KB / MB / GB。"""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def summarize(result: dict[str, Any]) -> str:
    """把 `clean()` 结果压成一行中文摘要（启动日志与 CLI 共用）。"""
    verb = "将删除" if result.get("dry_run") else "已删除"
    parts = [
        f"{verb} {len(result.get('deleted', []))} 个过期临时文件（{human_size(result.get('freed_bytes', 0))}）",
        f"保留 {result.get('kept', 0)} 个",
        f"保留期 {result.get('retention_days', 0)} 天",
    ]
    if result.get("dirs_removed"):
        parts.append(f"回收空目录 {result['dirs_removed']} 个")
    errors = result.get("errors") or []
    if errors:
        parts.append(f"失败 {len(errors)} 个")
    return "；".join(parts)
