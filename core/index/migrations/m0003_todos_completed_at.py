"""0003 · todos_index 增加 completed_at 列（完成时间限制）。

背景：待办完成时间（`completed_at`）原先无处存放，导致「什么时候完成的」不可追溯。
`System/todos.json` 自本次起写入该字段；索引表随之补列。

索引整体是派生数据（由 `todos.json` 重新解析即可重建），所以补列后旧行该字段为空，
由索引器在下次 `refresh_todos()` / `sync()` 时回填——这里只做结构变更。
"""

from __future__ import annotations

import sqlite3

ID = "0003"
TITLE = "todos_index 增加 completed_at 列"
FROM_VERSION = 3
TO_VERSION = 4


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {str(r[1]) for r in conn.execute("PRAGMA table_info(todos_index)")}


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='todos_index'"
    ).fetchone()
    return bool(row)


def apply(conn: sqlite3.Connection) -> bool:
    if not _table_exists(conn):
        return False  # 表还没建：全新库由 DDL 直接建出带该列的结构
    if "completed_at" in _columns(conn):
        return False  # 幂等
    conn.execute("ALTER TABLE todos_index ADD COLUMN completed_at TEXT NOT NULL DEFAULT ''")
    return True


def verify(conn: sqlite3.Connection) -> tuple[bool, str]:
    if not _table_exists(conn):
        return True, "todos_index 尚未建表（建表语句自带 completed_at）"
    ok = "completed_at" in _columns(conn)
    return ok, "todos_index.completed_at 存在" if ok else "todos_index.completed_at 缺失"


def rollback(conn: sqlite3.Connection) -> bool:
    """回退到无该列的结构。SQLite ≥3.35 支持 DROP COLUMN；更老版本返回 False 由调用方报错。

    表不存在或列已不存在时视为「无需回退」，返回 True——否则在只有部分结构的旧库上
    回退会被误判成「不可逆」而中断整条回退链。
    """
    if not _table_exists(conn) or "completed_at" not in _columns(conn):
        return True
    try:
        conn.execute("ALTER TABLE todos_index DROP COLUMN completed_at")
    except sqlite3.OperationalError:
        return False
    return True
