"""0001 · documents 补 attachment 列（v260923）。

背景：文献 PDF 附件路径原先无处存放，v260923 起写入 frontmatter 的 ``attachment``，
索引表随之补列；补列后旧行该字段为空，需要一次全量重索引回填（由调用方强制）。
"""

from __future__ import annotations

import sqlite3

ID = "0001"
TITLE = "documents 增加 attachment 列"
FROM_VERSION = 1
TO_VERSION = 2


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {str(r[1]) for r in conn.execute("PRAGMA table_info(documents)")}


def apply(conn: sqlite3.Connection) -> bool:
    if "attachment" in _columns(conn):
        return False  # 幂等：新库 DDL 已自带该列
    conn.execute("ALTER TABLE documents ADD COLUMN attachment TEXT NOT NULL DEFAULT ''")
    return True


def verify(conn: sqlite3.Connection) -> tuple[bool, str]:
    ok = "attachment" in _columns(conn)
    return ok, "documents.attachment 存在" if ok else "documents.attachment 缺失"


def rollback(conn: sqlite3.Connection) -> bool:
    """回退到无该列的结构。SQLite ≥3.35 支持 DROP COLUMN；更老版本返回 False 由调用方报错。"""
    if "attachment" not in _columns(conn):
        return False
    try:
        conn.execute("ALTER TABLE documents DROP COLUMN attachment")
    except sqlite3.OperationalError:
        return False
    return True
