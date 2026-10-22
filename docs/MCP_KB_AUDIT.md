# kb_* MCP 工具审计（v261009.50）

审计方式：**静态清单 + 参数一致性 + 隔离工作区里逐个真调用**（不是"看代码觉得没问题"）。
复现：`.scratch/tmp/_audit_kb_tools_inventory.py`（清单）与 `_audit_kb_tools_behavior.py`（逐个调用）。

## 一、清单（13 个 kb 工具）

| 工具 | 读写 | 作用 | 关键参数 |
| --- | --- | --- | --- |
| `kb_constraints` | 读 | 读知识库硬约束（存放/命名/同步/类型矩阵/字段契约/标记/关系/playbook） | `topic` |
| `kb_create_entry` | **写** | 新建条目（按 `core.contracts` 的 CREATE_FIELDS 取参，含 `variant_of`/`variant_label`） | `kind` + 字段 |
| `kb_get_entry` | 读 | 读一条（附校验块） | `doc_id` |
| `kb_list_entries` | 读 | 过滤 + 分页列举 | `kind/query/status/project/mark/tag/unowned/sort/page/page_size` |
| `kb_search` | 读 | 全文检索（跨 doc/todo/literature 等来源，带排序） | `query/limit` |
| `kb_update_entry` | **写** | 更新正文与字段（非法值会被拒写并给出可选值） | `doc_id` + 字段 |
| `kb_rename_entry` | **写** | 改名（同步 H1 与全库交叉引用，`dry_run` 可预览） | `doc_id/new_title/dry_run/...` |
| `kb_change_kind` | **写** | 改挂到另一 kind（id/created 不变，目录随动，可 dry-run） | `doc_id/new_kind/...` |
| `kb_delete_entry` | **写** | 删除进回收站（默认先返回预览） | `doc_id/confirm` |
| `kb_check_entries` | 读 | 命名规范批量体检（可限定一条/一类） | `doc_id/kind/limit/check_h1` |
| `kb_variants` | 读 | 版本族：基条 + 各版本（含**每条分支的时间**）+ 已归档 | `doc_id` |
| `kb_branch_entry` | **写** | 开一条分支（复制内容，记 `variant_of`/`variant_label`/**`variant_at`**） | `doc_id/label/title/body` |
| `kb_merge_variants` | **写** | 按 H2 小节合并（`picks`），记 `doc_merge` 活动 | `base_id/picks/archive_merged` |
| `kb_archive_variants` | **写** | 归档版本到 `System/Versions/<基条>/archived/` | `base_id/variant_ids` |

> 另：`kb_*` 之外还有 `ws_*`（工作区/项目/待办/活动/**外部改动巡检**）与 `todo_*`、`lit_export_bibtex`。
> 写工具一律在 `mcp/server.py` 的 `WRITE_TOOLS` 里登记，受「设置 → 外部接入 → 允许外部 MCP 客户端写入知识库」约束。

## 二、发现并修掉的 bug（3 个，都是"真调用"抓出来的）

| # | 问题 | 根因 | 影响 |
| --- | --- | --- | --- |
| A | **`kb_list_entries` 完全不可用**，报 `TypeError: list_docs() got an unexpected keyword argument` | bridge 把 `sort` 传给了索引层 `list_docs`，而它**不接受** `sort` | 工具一调就崩（`kb_check_entries` 同源，也崩） |
| B | **`kb_check_entries` 完全不可用** | 同上（它也列举条目） | 命名体检工具直接报错 |
| C | **版本族 4 个工具返回被双重包装**：MCP 客户端拿到 `{"content":[{"text":"{\"content\":…}"}]}` | handler 自己调了 `ok(...)`/`fail(...)`，`handle_tools_call` 又包一层 | 客户端要解析两层 JSON；`kb_variants` 的结果取不到 `variants`（我第一遍审计就被它骗了） |

修法：
- A/B：`bridge.list_entries` 只传索引层支持的参数（`kind/query/status/project/mark/tag/unowned`），**`sort` 在本地做**；
- C：在包装层做**幂等包装** `_wrap(result)` —— 已经是 MCP 信封就原样返回（不改每个 handler，未来新工具也免踩）。

修复后**逐个真调用 13/13 全绿**（唯一 RAISE 是故意放的"不存在的工具"对照用例）。

## 三、功能重叠评估（结论：**没有该删的重复工具**，但有 3 组需要说清边界）

| 组合 | 是否重复 | 边界 |
| --- | --- | --- |
| `kb_rename_entry` ↔ `kb_update_entry{title}` | 否 | 改名会**同步 H1 与全库交叉引用**、带规范校验与 `dry_run`；`update_entry` 只改字段，不做引用同步。**改标题一律用 rename**（硬约束 §二.3） |
| `kb_change_kind` ↔ `create_entry` + `delete_entry` | 否 | 迁移保留 `id`/`created`、目录随动、可同步引用，是**结构性迁移**的唯一安全路径 |
| `kb_delete_entry` ↔ `kb_archive_variants` | 否 | 前者把**条目**移入 `System/Trash/`，后者把**版本**移入 `System/Versions/<基条>/archived/`，目标与语义都不同 |
| **`kb_branch_entry` ↔ `kb_create_entry{variant_of,variant_label}`** | **部分重叠** | `create_entry` 也能建变体（CREATE_FIELDS 里有 `variant_of`/`variant_label`）。`branch_entry` 多做三件事：**复制源正文/kind/tags**、**自动生成标签**、**写 `variant_at`（分支时间）**。建议：开分支一律用 `kb_branch_entry`（保证归族 + 有时间），`create_entry` 的 `variant_of` 视为底层入口 |
| **`kb_search` ↔ `kb_list_entries{query}`** | **部分重叠** | `search` 是**跨来源的相关性排序检索**（doc/todo/literature…）；`list_entries` 是**枚举 + 过滤 + 分页**。建议：找东西用 `search`，列清单用 `list_entries`；`list_entries` 的 `query` 仅作同库粗过滤 |
| `kb_constraints` ↔ `kb_check_entries` | 否 | 前者给**规则原文**，后者**按规则体检并定位问题**（谁不合规、改法） |
| `kb_variants` ↔ `kb_get_entry` | 否 | 前者是**族视图**（跨条目），后者单条 |

## 四、仍存在的小瑕疵（未改，供决定）

1. `kb_merge_variants` 接受 `doc_id` 作为 `base_id` 的别名、`kb_branch_entry` 接受 `source_id` 作为 `doc_id` 的别名，
   但**schema 里没声明**这两个别名 → 客户端看不见（功能正常，属于"宽容输入"）。要不要声明或去掉？
2. 参数一致性检查里 `kb_create_entry`/`kb_update_entry` 的"声明未用"是**误报**：它们按 `core.contracts` 的字段表
   批量取参，静态扫描看不到（审计脚本里已注明）。
3. `kb_delete_entry` 默认先返回预览（`confirm=true` 才执行），而 `kb_archive_variants` 直接执行——
   破坏性操作的口径不完全一致，可考虑统一为"预览优先"。

## 五、复跑方式

```powershell
python .scratch/tmp/_audit_kb_tools_inventory.py     # 清单 + 参数一致性
python .scratch/tmp/_audit_kb_tools_behavior.py      # 隔离工作区里逐个真调用（13 个 kb 工具）
python -m mcp.server --selftest                      # 工具面统计与自检
```
