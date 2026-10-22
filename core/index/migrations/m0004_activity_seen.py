"""0004 · 新增 activity_seen 表（同步引擎按活动 id 去重）。

背景：v261019 起「记录」同步按活动 id 合并两端历史，导入去重需要一张 seen 表
（`app/perf_index_core.py` 用它 INSERT OR IGNORE / DELETE）。该表原先只在上游分支的
建表语句里出现，本地迁移清单缺失，导致合并后同步路径报 `no such table: activity_seen`。

索引整体是派生数据（可从 `Workspace/System/activity.jsonl` 重建），这里只做结构变更。
"""

from __future__ import annotations

import sqlite3

ID = "0004"
TITLE = "新增 activity_seen / activity_legacy 表（同步去重）"
FROM_VERSION = 4
TO_VERSION = 5

TABLES = {
    "activity_seen": "CREATE TABLE IF NOT EXISTS activity_seen (id TEXT PRIMARY KEY)",
    "activity_legacy": "CREATE TABLE IF NOT EXISTS activity_legacy (fingerprint TEXT PRIMARY KEY, count INTEGER NOT NULL)",
}


def _exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def apply(conn: sqlite3.Connection) -> bool:
    changed = False
    for name, ddl in TABLES.items():
        if not _exists(conn, name):
            conn.execute(ddl)
            changed = True
    return changed  # 幂等；新建库由 DDL 直接建出


def verify(conn: sqlite3.Connection) -> tuple[bool, str]:
    missing = [name for name in TABLES if not _exists(conn, name)]
    return not missing, ("activity 去重表齐备" if not missing else f"缺少：{missing}")


def rollback(conn: sqlite3.Connection) -> bool:
    for name in TABLES:
        if _exists(conn, name):
            conn.execute(f"DROP TABLE {name}")
    return True
