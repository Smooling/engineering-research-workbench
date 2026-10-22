"""索引结构迁移框架（REFACTOR_PLAN §5.5.2）。

原先的升级步骤是内联在 ``app/perf_index_db._init_db()`` 里的四段 if：没有声明、
没有验证、没有回滚、没有备份，出问题只能删库重建（``initialize(force=True)``）。

本框架把每一步变成一个可审计的迁移文件：

- ``core/index/migrations/NNNN_*.py``，每个声明 ``ID / TITLE / FROM_VERSION / TO_VERSION``
  与 ``apply(conn) -> bool``（返回是否真的改了）、``verify(conn) -> (ok, detail)``、``rollback(conn) -> bool``；
- ``core/index/migrate.py`` 负责编排：读当前版本 → 列待执行 → **默认 dry-run** →
  备份 → 执行 → 验证；`--apply` 才落盘，`--rollback` 可逆。

三条硬约定：
1. **迁移必须幂等**：``apply`` 先探测现状再动手（新建库走 DDL 已是当前结构，迁移应为 no-op）。
2. **只碰派生数据**：索引库整体可重建，因此允许 DROP/重建；事实来源永远是 ``Workspace/`` 的 Markdown。
3. **版本单一入口**：目标版本 = 最大 ``TO_VERSION``（``migrate.TARGET_VERSION``），
   ``app/perf_index_db.SCHEMA_VERSION`` 从它读，不再各写一份。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

ApplyFn = Callable[[sqlite3.Connection], bool]
VerifyFn = Callable[[sqlite3.Connection], "tuple[bool, str]"]
RollbackFn = Callable[[sqlite3.Connection], bool]


@dataclass(frozen=True)
class Migration:
    id: str
    title: str
    from_version: int
    to_version: int
    apply: ApplyFn
    verify: VerifyFn
    rollback: RollbackFn

    def as_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title,
            "from_version": self.from_version, "to_version": self.to_version,
        }


def _build_registry() -> list[Migration]:
    from . import m0001_documents_attachment as m1
    from . import m0002_document_links_role as m2
    from . import m0003_todos_completed_at as m3
    from . import m0004_activity_seen as m4

    out: list[Migration] = []
    for mod in (m1, m2, m3, m4):
        out.append(Migration(
            id=mod.ID, title=mod.TITLE,
            from_version=mod.FROM_VERSION, to_version=mod.TO_VERSION,
            apply=mod.apply, verify=mod.verify, rollback=mod.rollback,
        ))
    out.sort(key=lambda m: m.to_version)
    return out


#: 按 to_version 升序的迁移清单
REGISTRY: list[Migration] = _build_registry()

#: 索引结构的当前版本（唯一来源）
TARGET_VERSION: int = max((m.to_version for m in REGISTRY), default=0)

#: 已知的历史版本（含迁移起点），供 CLI 展示
KNOWN_VERSIONS: dict[int, str] = {
    1: "最初结构（documents 无 attachment、document_links 无 role）",
    2: "v260923 · documents 增加 attachment",
    3: "v261008.2 · document_links 增加 role（类型化关系）",
    4: "v261019 · todos_index 增加 completed_at（完成时间限制）",
    5: "v261022 · 新增 activity_seen（同步按活动 id 去重）",
}
