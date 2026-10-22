"""索引库维护 —— WAL checkpoint 与 VACUUM（回收空闲页）。

    python -m core.index.maintain                    # 只看统计（只读，默认）
    python -m core.index.maintain --checkpoint       # WAL 截断（回收 -wal 文件）
    python -m core.index.maintain --vacuum           # 回收空闲页（先备份）
    python -m core.index.maintain --vacuum --no-backup

**为什么需要**：实测（2026-10-09）索引库文件 35.70 MB，而 `dbstat` 逐对象求和只有
**7.19 MB 活数据**——`PRAGMA freelist_count` 显示 **7299/9139 页是空闲页（80%，28.51 MB）**，
另有 21.39 MB 的 `-wal` 未 checkpoint。也就是说「索引瘦身」的真正收益在**维护**，
而不是方案 §5.5.3 原先假设的「删可推导边 / 砍 FTS 列」：那两项加起来不到 1 MB
（`tag`+`project` 边 1356 行 ≈ 0.25 MB；FTS 的 title/body/tags/projects 四列 ≈ 0.8 MB）。

安全性：索引库是**纯派生数据**（事实来源是 `Workspace/` 的 Markdown，随时可 `ws_reindex` 重建），
VACUUM/checkpoint 不改变任何内容语义；仍按约定**先备份**（`System/Backups/`）。
VACUUM 需要独占访问，工作台正在运行时会因锁失败——此时请先停服务。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from . import migrate as index_migrate


def stats(db_path: Path) -> dict:
    """只读统计：活数据 / 空闲页 / WAL 体积。"""
    out: dict = {"db": str(db_path), "exists": db_path.is_file()}
    if not out["exists"]:
        return out
    wal = Path(str(db_path) + "-wal")
    out["file_bytes"] = db_path.stat().st_size
    out["wal_bytes"] = wal.stat().st_size if wal.is_file() else 0
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        free = conn.execute("PRAGMA freelist_count").fetchone()[0]
        out.update({
            "page_size": page_size,
            "page_count": page_count,
            "freelist_count": free,
            "live_bytes": (page_count - free) * page_size,
            "free_bytes": free * page_size,
            "free_ratio": (free / page_count) if page_count else 0.0,
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
        })
    except sqlite3.Error as exc:
        out["error"] = str(exc)
    finally:
        conn.close()
    return out


def checkpoint(db_path: Path, *, truncate: bool = True) -> dict:
    """把 WAL 内容并回主库；truncate=True 时把 -wal 截断到 0 字节。"""
    mode = "TRUNCATE" if truncate else "PASSIVE"
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        busy, log, checkpointed = conn.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        return {"mode": mode, "busy": busy, "wal_pages": log, "checkpointed": checkpointed}
    finally:
        conn.close()


def vacuum(db_path: Path, *, backup: bool = True) -> dict:
    """VACUUM 重建库文件，回收空闲页。需要独占访问（工作台运行时会被锁挡住）。"""
    before = stats(db_path)
    if before.get("free_bytes", 0) < 1024 * 1024 and before.get("free_ratio", 0) < 0.05:
        return {"skipped": True, "reason": "空闲页很少，无需 VACUUM", "before": before}
    result: dict = {"before": before}
    if backup:
        path = index_migrate.backup_db(db_path, label="pre-vacuum")
        result["backup"] = str(path) if path else ""
    # isolation_level=None：VACUUM 不能在事务里执行
    conn = sqlite3.connect(str(db_path), timeout=15.0, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("VACUUM")
    except sqlite3.OperationalError as exc:
        result["error"] = f"{exc}（VACUUM 需要独占访问；工作台在运行时请先停服务）"
        return result
    finally:
        conn.close()
    after = stats(db_path)
    result["after"] = after
    result["reclaimed_bytes"] = before.get("file_bytes", 0) - after.get("file_bytes", 0)
    return result


def _default_db() -> Path:
    return index_migrate._default_db()


def _fmt(n: int | float | None) -> str:
    return f"{(n or 0) / 1048576:.2f} MB"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="索引库维护（默认只读统计）")
    ap.add_argument("--db", help="index.sqlite 路径（默认按 config/app.json）")
    ap.add_argument("--checkpoint", action="store_true", help="执行 WAL checkpoint(TRUNCATE)")
    ap.add_argument("--vacuum", action="store_true", help="执行 VACUUM（先备份）")
    ap.add_argument("--no-backup", action="store_true", help="VACUUM 前不备份（不建议）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    db_path = Path(args.db).resolve() if args.db else _default_db()
    if not db_path.is_file():
        print(f"找不到索引库：{db_path}", file=sys.stderr)
        return 1

    out: dict = {"stats": stats(db_path)}
    if args.checkpoint:
        out["checkpoint"] = checkpoint(db_path)
        out["stats_after"] = stats(db_path)
    if args.vacuum:
        out["vacuum"] = vacuum(db_path, backup=not args.no_backup)
        out["stats_after_vacuum"] = stats(db_path)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    s = out["stats"]
    print(f"索引库：{s['db']}")
    print(f"  文件 {_fmt(s.get('file_bytes'))} · WAL {_fmt(s.get('wal_bytes'))} · "
          f"活数据 {_fmt(s.get('live_bytes'))} · 空闲页 {_fmt(s.get('free_bytes'))}"
          f"（{100 * s.get('free_ratio', 0):.0f}%）· journal={s.get('journal_mode')}")
    if "checkpoint" in out:
        cp = out["checkpoint"]
        print(f"  checkpoint({cp['mode']})：busy={cp['busy']} wal_pages={cp['wal_pages']} "
              f"已回写={cp['checkpointed']} → WAL 现在 {_fmt(out['stats_after'].get('wal_bytes'))}")
    if "vacuum" in out:
        v = out["vacuum"]
        if v.get("skipped"):
            print(f"  VACUUM 跳过：{v['reason']}")
        elif v.get("error"):
            print(f"  VACUUM 失败：{v['error']}")
            return 1
        else:
            print(f"  备份：{v.get('backup') or '（未备份）'}")
            print(f"  VACUUM：{_fmt(v['before'].get('file_bytes'))} → "
                  f"{_fmt(v['after'].get('file_bytes'))}，回收 {_fmt(v.get('reclaimed_bytes'))}")
    if not args.checkpoint and not args.vacuum:
        print("  提示：这是只读统计；--checkpoint 回收 WAL，--vacuum 回收空闲页（需独占访问）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
