"""索引迁移编排器 —— 默认 dry-run，`--apply` 才落盘，执行前自动备份。

    python -m core.index.migrate                                  # 只看计划（dry-run）
    python -m core.index.migrate --apply                          # 备份 → 执行 → 验证
    python -m core.index.migrate --rollback                       # 反向回退（同样先备份）
    python -m core.index.migrate --db <path> --json

设计要点（对应 REFACTOR_PLAN §5.5.1/§5.5.2）：

- **单一版本入口**：``migrations.TARGET_VERSION`` 是索引结构版本，``app/perf_index_db``
  的 ``SCHEMA_VERSION`` 从它读；磁盘版本高于代码版本时**拒绝写入**（防旧 exe 污染新数据）。
- **可逆**：每个迁移都有 ``rollback``；不可逆时返回 False 并明确报错，不假装成功。
- **幂等**：``apply`` 探测现状，重复执行不产生变化（``changed`` 为空）。
- **备份**：用 SQLite 自己的 backup API（WAL 下也得到一致快照），落在
  ``Workspace/System/Backups/<时间戳>-index-pre-<目标版本>.sqlite``。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from . import migrations as M

#: 便捷再导出：消费者（如 app/perf_index_db.py）通常只 import 本模块
TARGET_VERSION = M.TARGET_VERSION
REGISTRY = M.REGISTRY
KNOWN_VERSIONS = M.KNOWN_VERSIONS


class MigrationError(RuntimeError):
    """迁移前置条件不满足（如磁盘版本高于代码版本、回退不可逆）。"""


# ---------------------------------------------------------------- 版本读写

def current_version(conn: sqlite3.Connection) -> int:
    """读库内 ``meta.schema_version``；表或键缺失都视为 0（全新库）。"""
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except sqlite3.Error:
        return 0
    try:
        return int(row[0]) if row and row[0] is not None else 0
    except (TypeError, ValueError):
        return 0


def set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT INTO meta(key,value) VALUES('schema_version',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(version),),
    )


def guard_disk_version(conn: sqlite3.Connection, target: int = M.TARGET_VERSION) -> int:
    """磁盘版本高于代码版本 → 抛错（用旧代码打开新库会把结构改坏）。"""
    disk = current_version(conn)
    if disk > target:
        raise MigrationError(
            f"索引库版本 {disk} 高于本代码支持的 {target}：请升级程序后再打开该 Workspace"
            f"（旧版本写入会破坏新结构）。库路径见 --db。"
        )
    return disk


# ---------------------------------------------------------------- 计划

def pending(conn: sqlite3.Connection) -> list[M.Migration]:
    disk = current_version(conn)
    return [m for m in M.REGISTRY if m.to_version > disk]


def plan(conn: sqlite3.Connection) -> dict:
    disk = current_version(conn)
    steps = pending(conn)
    return {
        "db": "",
        "current_version": disk,
        "target_version": M.TARGET_VERSION,
        "current_label": M.KNOWN_VERSIONS.get(disk, "未知"),
        "pending": [m.as_dict() for m in steps],
        "up_to_date": not steps,
        "needs_reindex": bool(steps),  # 结构变了 → 旧行需回填，调用方应强制全量重索引
    }


# ---------------------------------------------------------------- 备份

def backup_db(db_path: Path, *, backups_dir: Path | None = None, label: str = "") -> Path | None:
    """用 SQLite backup API 做一致快照；库不存在时返回 None。"""
    if not db_path.is_file():
        return None
    target_dir = backups_dir or (db_path.parent.parent / "Backups")
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    out = target_dir / f"{stamp}{suffix}.sqlite"
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(out))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return out


# ---------------------------------------------------------------- 执行 / 回退

def apply(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    verify: bool = True,
) -> dict:
    """执行待办迁移。返回 ``{applied:[...], changed:[...], skipped:[...], verify:[...]}``。

    调用方负责事务与备份（服务内启动时用 ``dry_run=False`` 且不备份；
    CLI ``--apply`` 会先备份）。
    """
    result: dict = {"applied": [], "changed": [], "skipped": [], "verify": [], "dry_run": dry_run}
    steps = pending(conn)
    if dry_run:
        result["applied"] = [m.id for m in steps]
        return result
    for mig in steps:
        try:
            changed = bool(mig.apply(conn))
        except sqlite3.Error as exc:
            raise MigrationError(f"迁移 {mig.id}（{mig.title}）执行失败：{exc}") from exc
        (result["changed"] if changed else result["skipped"]).append(mig.id)
        result["applied"].append(mig.id)
        set_version(conn, mig.to_version)
    if steps:
        set_version(conn, M.TARGET_VERSION)
    if verify:
        for mig in M.REGISTRY:
            ok, detail = mig.verify(conn)
            result["verify"].append({"id": mig.id, "ok": ok, "detail": detail})
        bad = [v for v in result["verify"] if not v["ok"]]
        if bad:
            raise MigrationError("迁移后验证未通过：" + json.dumps(bad, ensure_ascii=False))
    return result


def rollback(conn: sqlite3.Connection, *, to_version: int, dry_run: bool = False) -> dict:
    """回退到指定版本（按 to_version 降序逐个 rollback）。不可逆时抛错。"""
    disk = current_version(conn)
    if to_version >= disk:
        return {"rolled_back": [], "note": f"当前已是 {disk}，无需回退到 {to_version}"}
    steps = [m for m in reversed(M.REGISTRY) if m.to_version > to_version and m.to_version <= disk]
    result: dict = {"rolled_back": [], "dry_run": dry_run}
    if dry_run:
        result["would_rollback"] = [m.id for m in steps]
        return result
    for mig in steps:
        if not mig.rollback(conn):
            raise MigrationError(f"迁移 {mig.id} 不可回退（SQLite 版本可能过低，或结构已被外部改动）")
        result["rolled_back"].append(mig.id)
        set_version(conn, mig.from_version)
    return result


# ---------------------------------------------------------------- CLI

def _default_db() -> Path:
    root = Path(__file__).resolve().parents[2]
    cfg = root / "config" / "app.json"
    ws = "Workspace"
    if cfg.is_file():
        try:
            ws = str(json.loads(cfg.read_text(encoding="utf-8")).get("workspace") or "Workspace")
        except Exception:
            pass
    base = Path(ws)
    if not base.is_absolute():
        base = root / base
    return base / "System" / "Cache" / "index.sqlite"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="索引结构迁移（默认 dry-run）")
    ap.add_argument("--db", help="index.sqlite 路径（默认按 config/app.json）")
    ap.add_argument("--apply", action="store_true", help="真正执行（先备份）")
    ap.add_argument("--rollback", action="store_true", help="回退到 --to 指定的版本（先备份）")
    ap.add_argument("--to", type=int, default=1, help="--rollback 的目标版本（默认 1）")
    ap.add_argument("--no-backup", action="store_true", help="执行时不备份（不建议）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    db_path = Path(args.db).resolve() if args.db else _default_db()
    if not db_path.is_file():
        print(f"找不到索引库：{db_path}（全新安装无需迁移）", file=sys.stderr)
        return 0

    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        disk = guard_disk_version(conn)
        info = plan(conn)
        info["db"] = str(db_path)

        if args.rollback:
            if not args.no_backup:
                info["backup"] = str(backup_db(db_path, label=f"pre-rollback-to-{args.to}") or "")
            info["rollback"] = rollback(conn, to_version=args.to, dry_run=not args.apply)
            if args.apply:
                conn.commit()
            print(json.dumps(info, ensure_ascii=False, indent=2) if args.json else _render_rollback(info, args))
            return 0

        if args.apply and info["pending"]:
            if not args.no_backup:
                info["backup"] = str(backup_db(db_path, label=f"pre-v{M.TARGET_VERSION}") or "")
            info["result"] = apply(conn)
            conn.commit()
            info["after"] = plan(conn)
        else:
            info["result"] = apply(conn, dry_run=True)

        print(json.dumps(info, ensure_ascii=False, indent=2) if args.json else _render(info, args))
        return 0
    except MigrationError as exc:
        print(f"迁移中止：{exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def _render(info: dict, args) -> str:
    lines = [
        f"索引库：{info['db']}",
        f"当前版本：{info['current_version']}（{info['current_label']}） → 目标 {info['target_version']}",
    ]
    if info["up_to_date"]:
        lines.append("无需迁移：结构已是最新。")
        return "\n".join(lines)
    lines.append("待执行迁移：")
    for step in info["pending"]:
        lines.append(f"  - {step['id']} {step['title']}（v{step['from_version']} → v{step['to_version']}）")
    if not args.apply:
        lines.append("\n这是 dry-run，未改动任何东西；加 --apply 执行（会先备份到 System/Backups/）。")
        return "\n".join(lines)
    lines.append(f"\n已备份：{info.get('backup') or '（未备份）'}")
    res = info.get("result", {})
    lines.append(f"实际改动：{res.get('changed') or '无（已是最新结构）'}；跳过：{res.get('skipped') or '无'}")
    for v in res.get("verify", []):
        lines.append(f"  验证 {'OK ' if v['ok'] else 'FAIL'} {v['id']} {v['detail']}")
    lines.append(f"迁移后版本：{info.get('after', {}).get('current_version')}")
    lines.append("提示：结构变更后旧行需回填，服务启动时会强制全量重索引。")
    return "\n".join(lines)


def _render_rollback(info: dict, args) -> str:
    rb = info.get("rollback", {})
    lines = [f"索引库：{info['db']}", f"当前版本：{info['current_version']}，回退目标 {args.to}"]
    if not args.apply:
        lines.append(f"dry-run：将回退 {rb.get('would_rollback') or '无'}")
        lines.append("加 --apply 执行（会先备份）。")
    else:
        lines.append(f"已备份：{info.get('backup') or '（未备份）'}")
        lines.append(f"已回退：{rb.get('rolled_back') or rb.get('note')}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
