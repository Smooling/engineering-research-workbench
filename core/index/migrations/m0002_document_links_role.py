"""0002 · document_links 增加 role 列（v261008.2 类型化关系层）。

背景：正文「关联」小节的小标题/行内标签决定关系类型（uses-knowledge / uses-data /
cites / series / chain-prev / chain-next / produces / 兜底 wikilink），
``document_links`` 主键由 ``(doc_id, token)`` 扩为 ``(doc_id, token, role)``。

该表是**纯派生数据**（由 Markdown 正文重新解析即可重建），所以迁移策略是
DROP + 重建，而不是逐行 UPDATE —— 重建后由索引器回填 role。
"""

from __future__ import annotations

import sqlite3

ID = "0002"
TITLE = "document_links 增加 role 列（主键扩为 doc_id+token+role）"
FROM_VERSION = 2
TO_VERSION = 3

_DDL = (
    "CREATE TABLE document_links ("
    "doc_id TEXT NOT NULL, token TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'wikilink', "
    "PRIMARY KEY(doc_id, token, role), "
    "FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE)"
)


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {str(r[1]) for r in conn.execute("PRAGMA table_info(document_links)")}


def apply(conn: sqlite3.Connection) -> bool:
    if "role" in _columns(conn):
        return False  # 幂等
    conn.execute("DROP TABLE IF EXISTS document_links")
    conn.execute(_DDL)
    return True


def verify(conn: sqlite3.Connection) -> tuple[bool, str]:
    cols = _columns(conn)
    if "role" not in cols:
        return False, "document_links.role 缺失"
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='document_links'"
    ).fetchone()
    if sql and "role" not in str(sql[0]):
        return False, "document_links 主键未含 role"
    return True, "document_links.role 存在（主键含 role）"


def rollback(conn: sqlite3.Connection) -> bool:
    """回退到无 role 的结构（同样是 DROP+重建；role 信息由重新解析 Markdown 可再得）。"""
    if "role" not in _columns(conn):
        return False
    conn.execute("DROP TABLE IF EXISTS document_links")
    conn.execute(
        "CREATE TABLE document_links ("
        "doc_id TEXT NOT NULL, token TEXT NOT NULL, "
        "PRIMARY KEY(doc_id, token), "
        "FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE)"
    )
    return True
