# 报告导出（`report-export`）

把知识库条目整理成**可交付文档**：**DOCX**（零第三方依赖）、**HTML**（浏览器打印即成 PDF）、**Markdown**。

## 三种格式分别怎么来

| 格式 | 实现 | 为什么这么做 |
| --- | --- | --- |
| **DOCX** | 纯标准库写 OOXML（`zipfile` + 手写 `word/document.xml` / `styles.xml`） | 工作台跑在**用户的** Python 上，那里不保证有 `python-docx`（本机实测没有）。`.docx` 本质是装 XML 的 ZIP，标准库足够写出 Word / WPS / LibreOffice 都能正常打开的文档——插件「丢进去就能用」，不需要用户装任何东西 |
| **HTML** | 同一份内容 + 打印样式，路径可加 `?print=1` 自动唤起打印 | **PDF 就是它**：浏览器「打印 → 另存为 PDF」，中文与字体交给系统，效果比任何纯 Python 方案都好，同样零依赖 |
| **Markdown** | 原文拼装 | 便于再加工：贴进别的工具、进版本库、被 diff |

## 用法

1. 「设置 → 插件」里启用本插件（默认不启用）；
2. 侧栏进 **报告导出**：选范围（某个项目 / 某一类条目 / 全部）→ 勾选是否收录正文与元信息 → **预览范围** 看清单 → 导出；
3. 导出文件落在 `Workspace/Plugins/report-export/exports/`，页面直接给下载链接；
   要 PDF 就点「打印 / 另存为 PDF」。

Agent 侧有两个工具：`p_report-export__list_scopes`（列范围）、`p_report-export__export_report`（按范围导出并返回文件路径）。

## 数据从哪来

一律走 `core_api` 的**只读窗口**（`entries/entry/projects/kind_labels/kind_order`），与前端 `/api/docs`、
`/api/projects` **同一套查询实现**（实测同源同量：199/199、分页跨界一致）。

**不直接读 `Workspace/Knowledge/*.md`**：那是核心的数据结构，绕过索引会看到过期或半写状态（PLUGIN_SPEC §6 隔离），
而且会让插件偷偷依赖核心的内部布局。

## 边界与已知取舍

- 正文的 Markdown 只做**能读懂的降级**（标题 / 列表 / 引用 / 代码块 / 段落 / 表格行），不还原富文本；
  要保真就用 HTML 或 Markdown 格式。图片不嵌入（报告里以链接文字出现）。
- 单份报告最多 500 条（`max_entries` 上限），避免手滑把整库导出到卡死。
- 导出是**只写自己命名空间**的动作（`Workspace/Plugins/report-export/exports/`），不改任何知识条目，
  因此它的工具不是"写工具"，不走内核的草稿确认闸门。
- 下载接口做路径安全校验：只允许导出目录内的文件，拒绝 `..`、绝对路径与子目录。
- 导出的 DOCX 里标题用 `w:eastAsia="宋体"`：Word/WPS 认这套，Linux 上的 LibreOffice 会用系统替代字体。

## 它同时是一个示例

本插件是「新插件长什么样」的第二个完整例子（第一个是 `plugins/.template/`）：

- 后端只用 `ctx.routes` / `ctx.mcp.tool` / `ctx.storage` / `ctx.config_read|write` / `ctx.log`，
  加上 `ctx.raw()`——**这是内核为「插件产出文件」新加的接缝**（下载、导出、图表都用它）；
- 前端只用 `ERWPanels` / `erwFetch` / `ERWToast`，样式全部落在 `[data-plugin="report-export"]` 里；
- **内核源码里没有本插件的任何痕迹**（`grep` 得到 0 命中），加它没有改一行内核逻辑。
