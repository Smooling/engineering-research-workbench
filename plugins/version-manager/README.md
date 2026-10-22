# 版本管理（version-manager）

同一笔记的不同版本：**查看版本族 → 批量清理快照 / Agent 自动确认 / 按小节合并 → 归档 / 取回**。

- 入口：侧栏「系统 → 版本」（停用本插件则入口消失）
- 后端：`backend.py`（路由 `/api/plugins/version-manager/*`；工具 `versions` / `auto_merge_versions` / `merge_versions` / `archive_versions`）
- 前端：`web/panel.js` + `web/panel.css`
- 权限：`ui:panel`、`config:own`、**`llm:use`**（自动确认会调用已配置的模型；可用 `strategy="rule"` 跳过模型）

## 为什么数据模型不在这里

版本与来源**必须在内核的写入收口点**（`store.create_doc` / `store.update_doc`）处理，否则
界面、内核 Agent、MCP、插件四条写入路径里总有漏网的。所以：

| 归内核 | 归本插件 |
| --- | --- |
| 契约字段（`variant_of` / `variant_label` / `has_variants` / `origin_*`） | 页面与交互（族列表、对照、挑小节、归档/取回按钮） |
| 写入时记来源、分叉/冲突时先留一版 | 本插件自己的 HTTP 路由与 Agent 工具 |
| 版本逻辑引擎 `app/versions.py`（归族、分节合并、归档区） | —— |
| MCP 侧同名工具（`mcp/` 是内核侧） | —— |

本插件只经 `core_api` 的版本窗口读写（`version_overview` / `variant_family` / `merge_variants` /
`auto_merge_variants` / `archive_variants` / `restore_variant`），符合 I3（插件只许 `from core_api import …`）。

## 批量清理

版本页左侧顶部有「批量清理」卡片：一次扫描所有版本族，把快照分成两类——

- **内容一致**（与基条正文完全相同，通常是外部写入只改了来源/元数据）：可直接归档；
- **有改动**（写入前的内容，通常是外部工具改动正文时留下的旧版）：可逐族打开对照，也可确认后一键归档。

「归档全部 N 个…」适合定期清理：快照会移到 `System/Versions/<基条>/archived/`，基条内容不变，
随时可在族详情「③ 已归档」里取回。列表每行也会标出「有改动 / 内容一致」，方便挑着处理。

> 合并时「合并后把被替换的版本一并归档」现在**默认勾选**，避免处理完又堆一批快照。

## Agent 自动确认

左侧选一族后，② 区顶部有「✦ Agent 自动确认」：

1. 内核把**有改动的小节**分批（每批 3 节、每节截 350 字）交给设置里已配置的模型，要求它逐节选来源
   （候选版本 id 或空字符串=保留基准）并给一句理由；批次并发执行，失败会自动重试。
2. 页面把建议填进每一节的「来源」选择器并打上 `Agent` 标记，顶部横幅汇总「采用 N 处 / 保留基准 M 处」，
   展开可看逐节理由。
3. 确认无误后点原来的「应用」写回基条；勾选「直接应用」则一步完成（仍记录 `doc_merge` 活动与来源）。

模型不可用（未启用/没填 Key/网关异常）或某批始终没有返回结果时，**自动回退**到「最近更新优先」规则，
并在横幅里注明 `rule-fallback`；命令行/外部 Agent 可用 `strategy="rule"` 显式走规则、不产生模型调用。
