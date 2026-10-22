"""内核索引层：结构迁移与（后续的）索引维护工具。

`core/index/migrations/` 是索引结构的版本化迁移清单，`core/index/migrate.py` 是编排器。
本包不依赖 `app`：`app/perf_index_db.py` 反向从 ``migrate.TARGET_VERSION`` 读取当前版本。
"""
