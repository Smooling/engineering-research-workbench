# 工程科研工作台 · 精简与插件化重构方案

> 依据：2026-10-09 对仓库代码与 `Workspace/` 真实数据的三份只读审计（路由全表、前端 218 文件全表、数据契约程序化 diff + SQLite 只读实测），复现脚本留在 `.scratch/tmp/audit_*.py`。
> 每条结论附 `file:line` 或实测值；无法从代码断定的标「待确认」，不猜。
> 目标：把工作台收敛成「科研数据梳理与汇总」内核，其余功能以可增删插件形式存在，且插件不得影响内核。
>
> **v3.1（本轮）**：① RAG 分支已推送 origin 并核验（`git ls-remote` 返回 `refs/heads/feature/rag-v261009 = ee4dd86`，48 文件 / 5120 行），「只存在于本机」的风险解除；② **D8 已定：以 `feature/slim-workbench-v261009` 为内核基线**（A0 的定基线部分完成）；③ 新增 [docs/SCOPE.md](SCOPE.md)——**定位与功能分层的权威定义**（§4.2 已与之对齐，§8-D1 移交为 SCOPE §4 的 D-A～D-D）；④ 新增 [docs/PLUGIN_SPEC.md](PLUGIN_SPEC.md)——**插件打包/安装/依赖规范**（统一插件库、单文件包、前提插件与级联停用、安装启停流程、权限校验）。
> **v3.2（本轮定案）**：全部开放项已裁定——插件包用 `.zip` 且**自动解包到每插件独立文件夹**（PLUGIN_SPEC §2/§12）；文献**阅读进核心、笔记进附属**；数据先做成可汇总表、分析用插件；报告默认 Markdown+BibTeX、DOCX/PDF 导出做插件。**尚未实现的全部功能集中在 [SCOPE §6 未来规划](SCOPE.md)**（阶段 1 地基 → 阶段 2 拆插件 → 阶段 3 数据表化 → 阶段 4 插件生态 → 阶段 5 RAG 回归）。
> **本次更新（v3）**：① **更正上一版结论——RAG 并没有「丢失」**：完整实现已提交在独立分支 `feature/rag-v261009@ee4dd86`（本轮已推送 origin）；`tools/kb_smoke.py`、`tools/shot_page.py`、`tools/shot_prep.py`、`tools/rag_check.py`、`web/v261009-rag.css` 同样都在 git 里。当前分支看不到它们属于**基线不一致**，不是数据丢失（§1.4 与 §3-P24 / P26 已改写）。上一版误判的原因：只在当前分支跑了 `git log -- rag/*`，没加 `--all`。
> ② 新增 §1.4 分支拓扑与 P27–P30（分支发散、读操作需写权限、本分支验证工具缺席、上游并行分支重复投入）。③ §4 精简方案按当前分支实测数值重排优先级，并补 A0 / A13 / A14。
> **v2 回顾**：RAG 定为「不进内核」（现确认它本就独立在一条分支上）；已摘除悬空 `kb_retrieve`（工具数 26 → 25）；`.gitignore` 已放行 `mcp/`、`plugins/`。

---

## 0. 摘要

三件事按顺序做，每件都能独立验收：

| 步骤 | 要解决的问题 | 核心动作 | 收益 |
| --- | --- | --- | --- |
| **① 精简** | 功能面已超出「数据梳理与汇总」；前端 13 个补丁文件靠加载顺序互相覆盖 | 划内核边界，把非内核功能移出核心启动路径 | 首屏资源 8.2 MB → < 1 MB；补丁 3987 行 → 主题模块 |
| **② 契约归一** | 同一套规则 3 处实现、2 套校验、5 处版本号；已产生越界 status、越界 mark、幽灵项目节点 | 单一契约源 + 生成物 + 体检/迁移框架 | 消灭「同一数据两套规则」 |
| **③ 插件化** | 新功能只能改核心 | 固化 manifest/扩展点/隔离不变量 | 内核零插件可跑，插件可自由增删 |
| **④ RAG 出核**（已落地） | RAG 在内核里已不存在 | ✅ 悬空 `kb_retrieve` 已摘除（工具数 26 → 25）；RAG 完整实现保留在 `feature/rag-v261009`，161 MB 本地数据仍在 | 内核不背 RAG 的依赖与体积，需要时按插件或按分支取回 |

**代码体量实测（当前分支 `feature/slim-workbench-v261009`，VERSION v261008.1）**

| 层 | 文件数 | 行数 | 体积 |
| --- | --- | --- | --- |
| 根 Python（`server.py` + `client.py` 等） | 3 | 938 | 50 KB |
| `app/`（HTTP 后端 + 数据层） | 24 | 7876 | 356 KB |
| `mcp/`（stdio MCP 服务，本版起首次入库） | 8 | 2207 | 107 KB |
| `tools/`（运维脚本） | 4 | 389 | 21 KB |
| `web/` 非 vendor 代码 | 23 | ≈6.7k | 617 KB |
| — 基础 5 文件 | 5 | 2703 | 348 KB |
| — 版本化补丁 | 18 | **4042** | 269 KB |
| `web/vendor/`（本地专用，占前端体积 92%） | 193 | 27888 | **8.2 MB** |
| 路由 | — | **82 条 `/api` 路由分支**（GET 34 / POST 40 / DELETE 8）+ `/workspace-file` 与静态兜底 ≈ **84 个端点** | — |

**数据现状实测**

| 项 | 值 |
| --- | --- |
| 知识条目 | **199 条**（Notes 90 / Literature 67 / Experiments 25 / Journals 6 / Ideas 4 / Summaries 4 / Milestones 3），与索引 `documents` 199 行一致；另有 1 个 md 在 `Knowledge/Exports/` 不参与索引 |
| 关系边 | `document_links` 395（可解析 393 / 不可解析 2）、`graph_edges` 1854 |
| 状态文件 | `projects.json` 4 项目、`todos.json` 3 条、`activity.jsonl` **946 行**、`AgentChats/` 102 文件（69 草稿 + 24 回收） |
| 派生数据 | `index.sqlite` 35.7 MB + `-wal` **21.4 MB**（长期未 checkpoint）、损坏的冲突副本 6.8 MB |
| RAG 本地数据（**非孤儿**，属 RAG 分支的运行期产物） | `.rag/` 权重 **92 MB** + `Cache/rag.sqlite` **69.2 MB**；源码在 `feature/rag-v261009`（§1.4） |
| 同步冲突残留 | 5 个（`activity`/`migration`×2/`chat`/`index` 各一） |

---

## 1. 现状 · 架构

### 1.1 运行时拓扑

```text
                    ┌─────────────────────────── 浏览器 SPA（无构建步骤）──────────────────────────┐
                    │ web/index.html  手写装配：CSS :11-22、JS :105-115，全部 defer，顺序有语义     │
                    │   导航不是 HTML：index.html:51 只留空 <nav>，条目由 app.js:49-60 NAV_GROUPS 生成│
                    │   vendor 8.2 MB：mermaid 2.57 + mathjax 2.11 + pdfjs 3.36（:35-39 无条件 defer）│
                    └───────────────────────────────────┬───────────────────────────────────────┘
                                                        │ JSON HTTP（≈85 条路由）
                    ┌───────────────────────────────────▼───────────────────────────────────────┐
                    │ server.py · ThreadingHTTPServer（单进程，stdlib-only，647 行）              │
                    │   GET :191→handle_api_get · POST :208→handle_api_post                      │
                    │   DELETE :223 内联分发（无 handle_api_delete）                              │
                    │   唯一 SSE：POST /api/agent/send                                            │
                    │   文件服务：/workspace-file/<rel> · 静态+SPA 兜底 · PDF Range               │
                    └───┬───────────────────┬───────────────────────┬───────────────────────────┘
                        │                   │                       │
              ┌─────────▼─────────┐ ┌───────▼────────┐ ┌────────────▼───────────────┐
              │ app/ 数据与业务层  │ │ app/ 派生索引层 │ │ app/ Agent 层               │
              │ store(1190)       │ │ indexer(9,门面) │ │ agent(1004)                │
              │ workspace(380)    │ │ perf_index_db   │ │ agent_tools(420)           │
              │ config(666)       │ │  core(505)      │ │ billing(602)               │
              │ projects(546)     │ │  query(483)     │ │                            │
              │ literature(830)   │ │  runtime(211)   │ │                            │
              │ todos(90) rss(166)│ │  graph(270)     │ │                            │
              │ weather(109) ...  │ │ SQLite 9 表     │ │                            │
              └─────────┬─────────┘ └────────┬───────┘ └────────────────────────────┘
                        │                    │
                        ▼                    ▼
              Workspace/（唯一事实来源）    System/Cache/（派生，可重建）
              Markdown + frontmatter        index.sqlite 35.7 MB + WAL

              ※ 语义检索 RAG 已不在核心路径：内核里没有 _rag_* 代理、没有 /api/rag/*、
                web/ 里没有 v261009-rag.css；rag/ 只剩 __pycache__。残留见 §3-P24。

                    ┌───────────────────────────────────────────────────────────────────────────┐
                    │ mcp/ · stdio MCP 服务（面向外部 Agent，26 个工具）                           │
                    │   bridge.py:37 惰性 import app.{activity,config,indexer,projects,search,   │
                    │   store,todos,workspace} —— 复用同一套读写，不重实现文件层（286 行门面）     │
                    │   constraints.py + naming.py —— 但**契约与校验是另写一套**（见 §3-P1/P2）    │
                    │   ⚠ kb_retrieve 仍注册，但 rag.client 已被删 → 调用即 ModuleNotFoundError    │
                    └───────────────────────────────────────────────────────────────────────────┘
```

### 1.2 打包与路径边界（决定插件能放哪）

| 事实 | 证据 | 对插件化的含义 |
| --- | --- | --- |
| onefile 打包，入口 `client.py` | `build_client.bat:19` | 内核是单进程 |
| `web/` 以 data 形式**打进 exe** | `ResearchWorkbench.spec:8` | 插件前端资源**不能**放 `web/`，必须从磁盘加载 |
| `app/` 冻结进 PYZ 归档 | `spec:17` | 插件后端**不能**是冻结包内模块，必须运行期从 `plugins/` 动态载入 |
| `DATA_ROOT` = exe 同级；`ASSET_ROOT` = 解压目录 | `app/paths.py:16-23` | 插件根应挂 `DATA_ROOT` → 开发态与便携 exe 共用一套 |
| 原生外壳持有窗口状态与 WebView profile | `client.py:23,75,93,115-125,148-153` | `window-state.json` 不属前端，不经 HTTP |

**结论**：插件目录必须是 `DATA_ROOT/plugins/<id>/`，由运行期 `importlib` 从文件路径加载；任何「把插件写进 `app/` 或 `web/`」的方案在打包后都不可用。

### 1.3 功能面清单（按路由数排序，当前分支实测）

| 功能 | 路由数 | 主要代码 | 使用痕迹（2026-10-09） |
| --- | --- | --- | --- |
| 文献与 PDF 工作区 | **20** | `literature.py`(830)、`web/literature.js`(658 行)、vendor/pdfjs | 67 条文献、56 篇 PDF 入库 |
| Agent 对话 | **14** | `agent.py`(1004)、`agent_tools.py`(420)、`web/v260930-floating-agent.js`(1145 行) | `agent_chat` 66；会话 102 文件 |
| 知识条目 CRUD | 9 | `store.py`(1190)、`perf_index_query/runtime/core` | `doc_update` 707 / `doc_create` 142 行 |
| 系统维护与本地文件 | 7 | `workspace.py`、`projects.py`、`config.py` | — |
| 项目 | 6 | `projects.py`(546) | 4 个项目 |
| 工作区信息与仪表盘 | 6 | `workspace.py`、`perf_index_*` | — |
| 知识图谱 | 5 | `perf_index_graph.py`(270)、`v260922-graph-performance.js`(307 行) | 依赖 mermaid 2.57 MB |
| 计费 | 5 | `billing.py`(602)、`v261008-billing.js`(212 行) | 账本 57 行，最后写入 10-08 14:23 |
| Todo | 4 | `todos.py`(90) | 3 条待办 |
| 配置 | 3 | `config.py` | — |
| 关键词检索 | 1 | `perf_index_query.search_all`（中文 bigram FTS，含 loose 兜底） | — |
| 天气 | 2 | `weather.py`(109) | weather.json 最后写入 **10-09 12:42（在用）** |
| RSS 资讯 | 1 | `rss.py`(166) | rss_cache 最后写入 **10-09 09:10（在用）** |
| ~~语义检索 RAG~~ | ~~2~~ | **不在本分支**：源码在 `feature/rag-v261009`（见 §1.4）；`mcp` 侧悬空工具已摘除（P23） | 本地仍有 `.rag/` 92 MB + `rag.sqlite` 69.2 MB（§3-P24） |
| **专注计时** | **0** | **只有前端**：`app.js:482-499` + localStorage `focusMinutes/breakMinutes` | 无模块、无路由 → 最易插件化 |

### 1.4 分支拓扑（决定「精简哪条线」，v3 新增）

工作区只有一个，但 git 里有多条并行分支：**AI 助手线、RAG 线、精简线各占一条**，所以「当前工作台包含什么」取决于在哪条分支上。

| 分支 | HEAD | VERSION | 相对当前 HEAD（该分支独有 / 落后） | 内容 |
| --- | --- | --- | --- | --- |
| `feature/slim-workbench-v261009`（**当前**） | cacdaad | v261008.1 | — | 精简线：近 5 次提交全是 UI 紧凑化（标题栏 64px、sticky 偏移、compact layout、PDF 恢复修复）+ 本轮 `kb_retrieve` 摘除 / 白名单 / 方案文档 |
| `feature/ai-assistant-v260930` | ba77ddc | v261008.2 | 2 / 20 | AI 助手线（悬浮球、Agent 工具链、计费） |
| `feature/rag-v261009` | **ee4dd86** | v261008.2 | 3 / 20 | **RAG 完整实现**：`rag/*.py` + 7 份 eval 报告 + `tools/rag_check.py` + `web/v261009-rag.css`；**已于 v3.1 推送 origin** |
| `fix/ai-assistant-pr5-review` | d637ef3 | — | 0 / 1 | 当前分支的基点（HEAD 的父提交） |
| `main` / `origin/main` / `upstream/main` | 97bdbe2 / 2f63af6 / 9a164f7 | — | 落后 **204** | 发布主线，久未合并 |
| `upstream/*` 并行分支 | — | — | — | `feature/rag-recall-v2`、`test/rag-hybrid-retrieval`、**`feature/custom-knowledge-types`**（与 §8-D2「插件能否注册新 kind」直接相关） |

三条要点：

1. **RAG 是「另一条分支」，不是「被删掉的功能」**：它从未合入当前分支；`.rag/`(92 MB) 与 `Cache/rag.sqlite`(69.2 MB) 是它的运行期产物（被 gitignore，跨分支共用同一工作区所以一直留着）。
2. **精简的基线必须先定义**：在 `slim-workbench` 上做精简，就意味着暂时放弃 AI 助手线的 2 个提交与 RAG 分支的 3 个提交；而 `main` 已落后 204 个提交。目前没有人回答「哪条线是内核基线」（见 P27）。
3. **上游在做重叠的事**：`feature/rag-recall-v2`、`test/rag-hybrid-retrieval`、`feature/custom-knowledge-types` —— 动手前先对齐上游（见 P30）。

---

## 2. 现状 · 数据结构

### 2.1 知识条目（唯一事实来源）

- 位置：`Workspace/Knowledge/<KindDir>/<id>.md`，扁平存放，文件名即 `<id>.md`。
- 实测：**199 条**，与索引 `documents` 199 行一致（另有 1 个 md 在 `Knowledge/Exports/`，不参与索引）。
- 契约（`kb_constraints topic=schema`）：字段序 22 项 `id, kind, title, created, updated, status, project, projects, tags, kind_marks, record_date, due, added_date, summary_type, pinned, authors, year, venue, doi, url, cite_key`；`id/kind/created` 不可变；CREATE vs UPDATE 差集 = `{attachment}`；`attachment` **只在 UPDATE 列表、不在字段序**（契约自身不一致）。
- 写入顺序 `store.py:207-211` 与 `mcp/constraints.py:230-233` 逐项相等；**未列入的键靠 `sorted(meta.keys())` 兜底**（`store.py:213`）——`project_id`/`project_ids` 正是靠这条才没被丢。
- 七类矩阵（`topic=kinds`）：每类独立目录、标题前缀、状态机、日期字段、正文骨架。
  > **v3 更正（实测）**：上一版此处写「`store.kind_dir_map()` 与 `mcp.constraints.KINDS` 程序比对完全相等」，**实际不相等**——本分支 `store.py` 只有 6 类（无 `experiment`），而 `mcp/` 已是 7 类。这正是「基线未对齐」的直接证据（见 §4.0 与 `5d753b4`）。
  > **v261009 起**：两者都由 `core/contracts/kinds.py` 派生，相等由「单一事实来源」保证，不再是人工比对结论。
- status 词表按 kind 分（7 组）；`kind_marks` 10 个合法 id，实测分布 knowledge 85 / synthesis 7 / method 109 / question 7 / thinking 11 / architecture 15 / experiment 34 / data 19 / model 19 / principle 17。

**真实样本**（`Workspace/Knowledge/Experiments/note-20260923111042-bb9210.md:1-15`）：

```yaml
id: "note-20260923111042-bb9210"      # ← id 前缀是 note
kind: "experiment"                     # ← 声明自己是 experiment
title: "实验-GEO 单帧经典检测（1.3g）"   # ← 标题前缀是 实验-
project: "红外-可见光天基动目标识别与跟踪"
projects: ["红外-可见光天基动目标识别与跟踪"]
record_date: "2026-10-08"
project_id: "proj_a0af8ee9d4db"        # ← 契约里没有这两个字段
project_ids: ["proj_a0af8ee9d4db"]
```

**关系层**：不写 `relations` 字段，正文「关联」小节的 WikiLink 决定关系类型（`依据的知识`→uses-knowledge、`用到的数据`→uses-data、`引用文献`→cites、`同系列实验`→series、`上一环节`/`下一环节`→chain-prev/chain-next、`产出与汇总`→produces，未命中记 `wikilink`）；`store.py:77-132` 与 `mcp/constraints.py:267-284` 的 8 类关系程序比对相等；物化到 `document_links`（395 行），解析策略先 id 精确后 title.casefold（`perf_index_core.py:188-198`）。

### 2.2 System 状态文件

| 文件 | 结构 | 字段 | 写入方 |
| --- | --- | --- | --- |
| `System/projects.json` | JSON 数组（4 条） | `id, name, description, status, created, updated` | `projects.py:22-34,48-49` |
| `System/todos.json` | JSON 数组（3 条） | `id,title,project,due,priority,done,created,updated`（**`project_id` 仅 1/3 条有**） | `todos.py:32-36`；`project_id` 另由 `perf_index_runtime.py:77-97` 写 |
| `System/activity.jsonl` | 追加型 JSONL，**946 行** / 228 KB，无 BOM | 全行字段并集**恰为 7 个**：`timestamp,type,ref,kind,title,project,weight`；5 类：`doc_update 707 / doc_create 142 / agent_chat 66 / doc_delete 27 / todo_create 3`；代码可发但从未出现：`knowledge_export`/`bibtex_export`/`project_create`/`todo_update`/`todo_done` | `activity.py:20-42`（唯一写入点） |
| `System/schema.json` | 对象 | `workspace_schema_version:3, index_schema_version:3, updated` | `perf_index_db.py:77-98` |
| `System/migration.json` | 对象 | `performed_at, mode, sources_found, copied_count, copied[], history[]`（留末 30，当前全 0）；另有 2 个 sync-conflict 副本 + 1 个 `migration-冲突-*.json` | `workspace.py:172-225` |
| `System/AgentChats/` | 目录（102 文件） | `chat-<hex12>.json`：`{id,title,created,updated,messages[]}`；消息字段 `id,role,content,created,refs,images,request_preset,…`——**`refs`/`images` 是字符串化 JSON**；会话级 `archived` **只读不写**（静默回退 False） | `agent.py:35-50` |
| `System/billing/` | JSON + JSONL | `prices.json`（`schema_version:1, currency, unit, fx, models{}, plans{}`）、`ledger.jsonl`（**57 行 / 19 字段**，只增不改） | `billing.py:109-130,191-220,402` |

### 2.3 派生索引（SQLite，`System/Cache/index.sqlite`）

**表族与实测行数**（DDL `perf_index_db.py:101-213`；`trigger` 数 = 0）

| 表 | 实测行 | 关键列 / 索引 |
| --- | --- | --- |
| `meta` | 5 键 | `schema_version=3`、`last_sync`、`todos_signature`、`activity_offset`、`fts_backfill_pending` |
| `documents` | **199** | 27 列；4 索引（kind+updated、status、kind+due、updated） |
| `document_projects` | **178** | `doc_id, project_name, project_id`，2 索引 |
| `document_tags` | **1178** | 1 索引 |
| `document_marks` | **325** | 1 索引 |
| `document_links` | **395** | `doc_id, token, role`；role：wikilink 222 / uses-knowledge 52 / cites 50 / series 32 / uses-data 25 / produces 7 / chain-prev 4 / chain-next 3 |
| `graph_edges` | **1854** | 无 FK；tag 1178 + wikilink 325 + project 178 + typed 边… |
| `todos_index` | 3 | 2 索引（`done,due` / `project_id,project`） |
| `activity_daily` | 30 | `PK(date,type)`，无显式索引 |
| `documents_fts` | **199** | FTS5 `(doc_id UNINDEXED, title, body, tags, projects, seg)`，`seg` 存中文 bigram，**只有 `seg` 真正参与检索** |

- **版本号散落 5 处独立演进**：`perf_index_db.py:13-14`(3/3)、`System/schema.json`(3/3)、`config.py:20`(=2)、`billing.py:31`(=1)、`rag.sqlite meta`(=1，属 RAG 分支)；`schema.json` 与库内 `meta.schema_version` **互不校验**。另：`VERSION` 本身也按分支分叉（本分支 v261008.1 / 两条兄弟分支 v261008.2，见 §1.4）。
- **无通用迁移**：4 条迁移路径内联在 `_init_db`——① 版本号覆写；② `documents` 缺列 → `ALTER TABLE ADD COLUMN` 并触发全量重建（`:220-224`）；③ `document_links` 缺 `role` → **DROP 后重建**（`:226-236`）；④ FTS 分词器变更 → **DROP `documents_fts` 重建** + `fts_backfill_pending`（`:238-263`）。唯一「重建」是删库文件后 `initialize(force=True)`（`perf_index_core.py:430-439`）。
- **磁盘实测**：`index.sqlite` 35.7 MB + `index.sqlite-wal` **21.4 MB**（长期未 checkpoint，比库体量还大）；`index-冲突-Moxise_Win11.sqlite` 6.8 MB（**已损坏到无法打开**）；`rag.sqlite` 69.2 MB（RAG 分支的向量库，见 §1.4）。
- **读操作需要写权限**（v3 实测）：`perf_index_*` 每次建连都跑一遍 `_init_db`，所以连纯查询也要写库；在服务占库的情况下 `indexer.search_all()` 直接抛 `OperationalError: attempt to write a readonly database` —— 只读消费者（测试、只读 MCP、审计脚本）因此都用不了，只能改用 `?mode=ro` 的裸 sqlite 连接绕开（见 P28）。
- 物理隔离：`Workspace/.stignore` 仅一行 `System/Cache/`。

### 2.4 其它持久化

| 载体 | 结构要点 | 备注 |
| --- | --- | --- |
| `config/app.json` | `app_name/subtitle/host/port/auto_open_browser/workspace`、`weather.*`(5)、`ui.*`(6)、`academic_profile.*`(5)、`workspace_migration.*`(2)、`llm.{enabled,system_prompt,vision_enabled,assist,personas[]}` | **`literature.*` 段未进 `DEFAULT_APP_CONFIG`**（`config.py:85-124`），而 `literature.py:31,49` 读 `pdf_dir`/`note_images_dir` |
| `config/secret.json` | `{schema_version:2, active_profile_id, profiles[], migrated_at}`；profile 19 字段含 `base_url/api_key/headers/timeout/...` | 遗留 `config/secrets.json` 仍被两处按不同语义读（`config.py:140-167` 注环境变量、`:19,311` 读 legacy api_key） |
| `config/rss.json` | `{sources[]×9, max_items_per_source:12}` | 契约默认仅 3 源（`config.py:126-133`） |
| `Knowledge/Literature/Index/library.json` | `{version:1, items[56]}`；item 含 `doc_id,title,…,bibtex,reading_status,categories,tags,projects,favorite,filename,sha256,page_count,last_page` | **`categories`/`tags`/`projects`/`favorite` 存的是 Python repr 字符串**（`"[]"`、`"['S 学习阶段文献',…]"`、`"False"`）；`reading_status` 词表 `未读/在读/已读` 与 frontmatter 的 `待阅读/阅读中/已精读/已归档` **是第三套词表** |
| `System/Cache/weather.json` | TTL **600 s**；`{timestamp,key,data{…}}`，`key` 里重复存了一份配置 | `weather.py:25,58,105-108` |
| `System/Cache/rss_cache.json` | `{timestamp,updated,items[72],sources,errors,stale,…}` | 失败时用 stale 覆盖但不落盘（`rss.py:161-165`） |
| `window-state.json` | `{maximized,width,height}` | **唯一生产者与消费者都是 `client.py`**（`:23,75,93,153`），不经 HTTP |
| `.rag/models` | 模型权重 **92 MB** | RAG 分支的模型目录（源码在 `feature/rag-v261009`，见 §1.4） |

---

## 3. 结构问题清单（每条都有证据）

| # | 问题 | 证据 | 后果 |
| --- | --- | --- | --- |
| **P1** | **同一套契约 3 处实现**：`store.py`（kind→目录/前缀/状态机/日期/骨架）、`mcp/constraints.py`（同矩阵文本副本）、`kb_naming.py`（**精简且过期**副本） | `store.py:26,36,46,69`；`mcp/constraints.py:25,103`；`kb_naming.py:16-23` | 任一处更新，另两处漂移 |
| **P2** | **两套命名校验且规则互相矛盾**：MCP 走 `mcp/naming.py`（T000–T022）；应用内 Agent 走 `kb_naming.py`，对 `experiment` 直接放行 | `kb_naming.py:66-68`「未知条目类型 experiment，跳过命名校验」；`kb_naming.py:26` 认「实验」类别词 vs `mcp/naming.py:194-199` 判 `T020 error` | 同一条目两层结论可能相反；Agent 可用任意标题建实验条目，且 `category_mark` 对非 note 返回空（`:126-129`）→ 缺契约强制的 `experiment` 标记 |
| **P3** | **id 前缀与 kind 脱钩且不可修**：契约称 `id={kind}-{ts}-{hex6}`，实际 25 条 experiment 的 id 全是 `note-*`；`kb_change_kind` 明确「id/created 不变」 | §2.1 样本；`mcp/bridge.py:104-108` | 以 id 前缀推断类型的一切逻辑都错 |
| **P4** | **一个项目关系存 4 个字段**：`project`/`projects`（名）+ `project_id`/`project_ids`（id），后两者不在契约；索引里另有 `documents.project/project_id/projects_json/project_ids_json` 4 列 + `document_projects` 三元组 | 样本 `:8-9,14-15`；`perf_index_db.py:125-128,144-152` | 冗余 + 同步面扩大 |
| **P5** | **Agent 建档能力缺口**：只读 `kind/title/body/tags/projects/kind_marks`，不收 `status/record_date/due/added_date`；MCP 版支持 | `agent_tools.py:205-211`、spec `:316-325` vs `mcp/README.md:132-143` | 经 Agent 建的 journal/summary/experiment/milestone/literature **缺法定日期**；spec 类别词仍含已废弃「实验」（`:317`） |
| **P6** | **派生数据散落与不可回滚**：5 处版本号；`document_links`/`documents_fts` 迁移是 DROP 重建；无 down-migration；损坏的冲突副本 6.8 MB 常驻 | §2.3 各条 | 升级无单一入口；迁移不可回滚 |
| **P7** | **前端靠加载顺序互相覆盖**：13 个补丁 3987 行 > 基础 2992 行；`index.html:105-115` 手写顺序 | `web/index.html`；实测行数 | 无法按功能增删；一处顺序错就坏 |
| **P8** | **文档口径落后于代码**：`mcp/README.md:7` 写 24 工具、`:81` 写「六类条目矩阵」，实际 26 工具 / 7 类 | 同上 | 规范文档不再可作事实来源 |
| **P9** | **`rag/` 已经是事实上的「可插拔组件」**：它独立成进程（8770）、独立库（`rag.sqlite`）、独立模型目录（`.rag/`）、缺包即降级，且**现独立在 `feature/rag-v261009` 分支上**（已推送 origin） | `git ls-tree -r feature/rag-v261009`；`server.py` 早已没有 `_rag_*` | 插件化不必从零发明——这套形态就是模板；但「靠分支承载可选功能」也说明缺少插件机制 |
| **P10** | **临时空间无上限**：`.scratch` 已 6465 文件（上轮实测 253.7 MB，其中 `pycache` 4284 文件、35.7 MB index 快照）；启动清理未触发（`workbench.log` 停在 10-08 16:12 → 工作台进程未重启） | 实测 | 需体积上限 + 目录白名单，不只按时间清理 |
| **P11** | **死代码 / 半死代码**：`app/project_bridge.py`(52 行) 全仓零引用；`app/search.py`(43 行) 只被 `mcp/bridge.py:37`、`tools/self_check.py:14` 用，**server.py 不用** | 内容级 grep | 阅读成本与误改风险 |
| **P12** | **层级倒置**：`perf_index_query.py:7` 导入期依赖整个 `agent`（LLM）模块，只为 `:460/:466` 调 `agent.list_sessions()`；并跨模块调私有函数 `store._doc_from_path`(`:135`)、`store._academic_progress`(`:411/:420`) | 同上 | 索引查询层拖进 LLM 层，无法独立裁剪/测试 |
| **P13** | **导入期副作用**：`config.py:665-666` 在模块作用域跑 `load_secrets()` + `reload_all()`，后者在迁移路径会**写盘** `secret.json`/`app.json`（`:495,:509`） | 同上 | `from app import *` 即可读写用户配置 |
| **P14** | **base 与补丁互相硬依赖**：`app.js:585` 消费 `window.ERWFabTimeline`、`app.js:1307` 消费 `window.ERWBilling`、billing 在 `app.js:59/67/169/1305-1308` 硬编码；`v260922-performance.js:24` **全局替换 `window.fetch`** 且排在 `app.js` 之前（`:105` vs `:106`）；两个 canvas 先画后弃（`app.js:693/1261` vs 补丁 `:181/:332`）；`localStorage.graphKinds/graphRelations` 由 base 与补丁各写一次 | 同上 | 计费/悬浮球/图谱**无法在不改 base 的前提下摘除** → 插件化前必须先做钩子倒置 |
| **P15** | **归属有两条互不覆盖的写入路径 → 已造成不一致**：HTTP 写全 4 字段（`server.py:467-475,550-562` → `perf_index_runtime.py:67-70`），MCP **完全不写** `project_id`（`mcp/tools_knowledge.py:205,226-227` → `store.py:596-597`） | `document_projects` 实测 2 行 name 有/id 空；`perf_index_core.py:174` 用 `key = project_id or project_name` 建图 → **同一项目在图上是两个节点** | 图谱/筛选/统计口径分裂（幽灵节点） |
| **P16** | **status 与 kind_marks 写入期零校验，已产生越界数据** | `idea.status = 进行中`（词表只有 待整理/探索中/已采纳/已归档，`store.py:40`）；`kind_marks` 出现 `术语清单`、`知识-方法`（不在 `mcp/constraints.py:163-174` 的 10 个 id 内） | 状态机与标记表只是文档 |
| **P17** | **索引里有大量可推导数据与死列**：`graph_edges` 1854 行中 tag 1178 = `document_tags` 行数、project 178 = `document_projects` 行数，typed 边还额外插一条通用镜像边（故 wikilink 325 = 222 + 103）；`documents_fts` 的 `title/body/tags/projects` 四列**写入后无人读** | `perf_index_core.py:207-211`、`perf_index_query.py:39,175-178` | 索引体积与写放大；同一正文在 md / FTS / excerpt 存三份 |
| **P18** | **同一指标两套计数口径**：`activity_daily.doc_create=199`（按 `weight` 求和，`perf_index_core.py:301-310`）vs `activity.jsonl` 里 doc_create 只有 142 行（53 行 weight>1）；仪表盘另从 md `created` 补种并按 `(ref,day,type)` 去重（`store.py:1065-1082`） | 实测 | 报表不可核对 |
| **P19** | **`WORKSPACE_LAYOUT` 两处定义且已分叉**：`workspace.py:20-43` **22** 项 vs `mcp/constraints.py:21-39` **17** 项（后者缺 `Knowledge/Literature/{PDF,Annotations,Notes,Index,Previews}`） | 程序比对 | 同一骨架两份口径 |
| **P20** | **`System/Trash/` 与 kind 列表不匹配**：实测有 `knowledge`（**不是现役 kind**），缺 experiment/milestone/summary | 删除逻辑按 `doc["kind"]` 建目录、不校验（`store.py:717-719`） | 回收站结构漂移 |
| **P21** | **循环导入被写成「调用顺序契约」**：`config.py:666` 模块末尾直接 `reload_all()`；直接 `import app.workspace` 会经 `config→agent_tools→kb_naming/store→workspace` 回到半初始化模块并 **ImportError**（实测复现）；`billing.py:94-100` 用惰性导入绕过并注释说明 | 同上 | 插件运行期动态加载 core 模块会踩顺序炸弹（详见 §6.1） |
| **P22** | **5 个同步冲突文件常驻 Workspace**（含 7.1 MB 已损坏的 index 副本） | 同上 | 不进索引、无清理逻辑 |
| **P23** ✅ 已修复 | ~~**`kb_retrieve` 是悬空工具**~~（已从 `TOOLS`/`HANDLERS`/实现中移除，工具数 26 → 25，自检 problems 为空；留作「注册了却不可用」的案例）：`mcp/tools_workspace.py:217` 惰性 `from rag.client import retrieve`，而 `rag/` 源码已不存在 → 工具仍在 `TOOLS` 表（`:331`）并出现在会话工具清单里，**调用时才 `ModuleNotFoundError: No module named 'rag.client'`**（实测）。`python -m mcp.server --selftest` 仍报 `problems: []`（惰性导入不触发，自检抓不到） | 实测 | Agent 会看到并调用一个必然失败的工具（对外表现为「检索不了」） |
| **P24** | **RAG 实现与当前分支脱钩**（上一版误判为「已丢失」，此处更正）：完整实现提交在 `feature/rag-v261009@ee4dd86`（v3.1 已推送 origin）；当前分支工作树里 `rag/` 只剩 `__pycache__`，另有 `.rag/` 权重 92 MB 与 `Cache/rag.sqlite` 69.2 MB 常驻（被 gitignore，跨分支共用同一工作区） | `git ls-tree -r feature/rag-v261009` 列出 `rag/*.py` + 7 份 eval 报告；`git log --all -- rag/*` 非空（上一版只查了当前分支，故判断错误） | 真问题不是「丢了」，而是**同一功能散落在分支上、没有单一基线**（P27）；插件化正好让这类功能脱离「靠分支合并才能回来」 |
| **P26** | **规范引用的验证/采集脚本不在当前分支**：`AGENTS.md:36` 指定「改完必跑」的 `tools/kb_smoke.py` 与 `:28` 的 `tools/shot_page.py` 在本分支工作树里不存在（本分支 `tools/` 只剩 4 个 `.py`），但它们**都在 git 里**（`kb_smoke.py` 涉及 2 个提交、`shot_page.py` 1 个，另有 `shot_prep.py`、`rag_check.py`） | `Test-Path` 为假；`git log --all --oneline -- tools/kb_smoke.py` 非空 | 按自家规范在本分支执行会 `No such file or directory`；应从对应分支取回，或把规范改成「按分支可用性择一」 |
| **P27** | **分支发散、没有内核基线**：6 条本地分支 + 多条上游分支；当前 HEAD 比 `main` 领先 **204** 个提交；`feature/rag-v261009` 曾有 1 个提交未推送（v3.1 已推送）；`VERSION` 在分支间分叉（v261008.1 / v261008.2） | `git branch -a`、`git rev-list --left-right --count` 实测 | 「当前工作台是什么」取决于所在分支；精简/重构没有基线的成果会像 RAG 一样停在某条分支上 |
| **P28** | **纯读操作也要写库**：`perf_index_db._connect()` + 每次连接都执行 `_init_db()`，读路径因此需要写权限；服务占库时 `indexer.search_all()` 抛 `OperationalError: attempt to write a readonly database`（v3 实测） | `perf_index_db.py:36-37,101`；实测报错 | 只读消费者（冒烟脚本、只读 MCP、审计脚本）跑不了，只能改用裸 `?mode=ro` 连接绕过 |
| **P29** | **本分支缺「改动后必跑」的低成本回归闸门**（P26 的后果面）：`tools/` 只剩 4 个脚本，其中 `self_check.py` 会临时改写 `config/`，其余为性能 / 图标 / 临时空间脚本 | 实测 `tools/` 清单 | 任何精简动作只能靠手工验证，回归风险上升 |
| **P30** | **上游并行分支与本地方向重叠**：`upstream/feature/rag-recall-v2`、`upstream/test/rag-hybrid-retrieval`、`upstream/feature/custom-knowledge-types`（后者与 §8-D2「插件注册新 kind」直接相关） | `git branch -a` | 先对齐上游再做 RAG 插件化 / 自定义 kind，否则重复造且未来合并冲突 |

---

## 4. 精简方案

### 4.0 当前分支的实际进度（v3 实测）

| 已发生 | 说明 |
| --- | --- |
| UI 紧凑化（近 5 次提交） | 桌面标题栏 64px、设置页 sticky 偏移、compact layout 调整、PDF 阅读区恢复 —— **属外观压缩，未触动结构** |
| `kb_retrieve` 摘除 + `mcp/`、`plugins/` 入白名单 | 本轮完成（工具数 26 → 25，自检 problems 为空） |
| 方案文档入库 | `docs/REFACTOR_PLAN.md` 随 `cacdaad` 提交 |
| **基线对齐**（`5d753b4`） | 摘入 `23a83f7`「实验独立成类 + 类型化关系层」。**此前本分支代码停在 6 类**，与 `Workspace/` 里 25 条实验、索引 25 行 `documents` 及 `mcp/` 七类契约不一致——下一次索引同步会把这 25 条从索引与关系图删除（md 无损）。已消除 |
| **A13 取回验证工具**（`275107b`） | `tools/kb_smoke.py`、`kb_tree.py`、`kb_migrate_experiments.py`（随基线对齐取回）+ `shot_page.py`、`shot_prep.py`（自 `ba77ddc` 单独取回） |
| **P0 契约单源**（`e321a9d`） | 新增 `core/contracts/{kinds,naming}.py` 为唯一声明处与唯一校验器；`store`/`workspace`/`agent_tools` 改为消费，`mcp/constraints`、`mcp/naming` 退化为门面，删除过期副本 `app/kb_naming.py` |
| **P1 校验合并 / P5 建档缺口 / P19 骨架归一**（`e321a9d`） | 同标题在 HTTP 与 MCP 两路结论一致；Agent 可建 experiment 且补收 `status/record_date/due/added_date/summary_type`；`WORKSPACE_LAYOUT` 22/17 两项合并为一处 |
| **P11/P12/P13/P21**（`d02cb0f`） | `config` 导入期副作用清零（改显式 `init()`）、循环导入顺序炸弹拆除（每个 `app` 子模块均可作入口 import）、查询层不再导入期拖入 LLM 层、删零引用 `project_bridge.py` |
| **A1 vendor 按需加载**（`61b2f15`） | mathjax + mermaid 移出首屏，**首屏 5.23 MB → 0.77 MB（−85%）**，目标「< 1 MB」达成 |

| **A2 第一刀**（`a965a12`） | 装配清单化（`web/manifest.json` + `tools/web_manifest.py --write/--check`，index.html 三段引用块由清单生成）、前端静态体检闸门 `tools/web_check.py`（语法 / 清单一致 / 模块缺失 / `window.ERW*` 与自定义事件接缝 / 加载顺序）、5 个连续 IIFE 补丁合并为 `v260922-research-pages.js`（业务 JS 11 → 7，内容逐字复核一致） |
| **P3 首件**（本轮） | `python -m core.doctor` 只读体检：22 个检查项，覆盖 §5.5.5 清单的绝大部分；首次实测 199 条数据得 error 2 项 / warn 8 项（越界 status 1、越界标记 2、幽灵归属 2、断链 2、回收站漂移、4 个冲突文件、6.8 MB 冲突副本、WAL 21.4 MB） |
| **P1 补齐**（本轮） | 写入期字段校验 `core/contracts/validate.py`（F001–F007）：越界 status / 越界标记 / 强制标记 / 日期格式 / 未声明字段；`store` 与 MCP 两条写入路径消费同一份校验器，`create_doc` 按契约补齐标记，`update_doc` 白名单改由契约派生；`kb_smoke` 新增 14 条断言（第 7 组）全绿 —— **P16 的根因（写入期零校验）已堵住** |
| **P3 第二件**（`core/index/`） | 索引结构迁移框架：`core/index/migrations/m0001,m0002` + `core/index/migrate.py`（默认 dry-run、备份、验证、可回滚），**替换** `_init_db()` 里的四段内联 if；`SCHEMA_VERSION` 改为读 `migrate.TARGET_VERSION`（版本单源少一处）；新增「磁盘版本高于代码 → 拒绝写入」护栏，doctor 同步报出 |
| **A3 派生数据治理**（`core/index/maintain.py`） | 索引维护工具（checkpoint / vacuum，默认只读统计，VACUUM 前自动备份）；**实测回收 ≈49.9 MB**（35.70 MB + 21.39 MB WAL → 7.14 MB + 0），语义中性经 10 组查询 + 38 个 schema 对象比对证明；`server.py`/`client.py` 退出自动 checkpoint 防复发；doctor 新增空闲页告警 —— 并**更正了 §5.5.3 的收益假设**（删列/删边合计 < 1 MB） |
| **P29 前端闸门**（`tools/ui_smoke.py`） | 真浏览器逐路由走查（不截图）：首屏 console error / 失败请求 / 重型库请求必须为 0，`app.js` 声明的**每个路由**都点得开且渲染出内容，`window.erwVendor` 与补丁接缝齐备。**不下载浏览器**（复用系统 Chrome/Edge 或 ms-playwright 里的 chromium）。实测：当前代码新起实例上 **17/17 路由通过、0 error、0 失败请求** —— A2/A9/A10 与 §6.3 插件面板从此可验收 |
| **A10 首件：fetch 接缝化** | `v260922-performance.js` 不再在求值期执行 `window.fetch = ...`（P14 红线），改为提供 `window.erwFetch`，6 个模块的 `api()`（含 2 处直连）改为运行期解析 `(window.erwFetch \|\| fetch)`。行为等价经真浏览器验证（分页 1/2→2/2、图谱状态 199/199、搜索可用、0 console error）；「必须排在 app.js 之前」的旧约束作废。不变量改为静态可查：**不得给 `window.fetch` 赋值**、接缝提供方唯一、`api()` 不得绕过接缝（负向用例已验证） |
| **A9/§6.3 首件：前端面板注册表** | 新增 `window.ERWPanels`（导航 + 页头 + 渲染三合一的自登记点）；**用量计费整体搬出 `app.js`**（删导航项 / PAGE_META / 路由分支 / `renderBillingPage`），由 `v261008-billing.js` 自登记 —— 删掉计费模块只会少一个导航项、不再白屏（§6.7 红线 5 解除）。等价性：侧栏 17 项**顺序逐项一致**、`#billing` 正常渲染、0 console error；闸门新增「内核不得调用 `ERWPanels.register`」与「登记面板必须出现在侧栏」两侧断言 |
| **§6/P5 首件：插件运行时（内核侧）** | `core/plugins/{manifest,registry}.py` + `__main__.py` + `tools/plugin_check.py`：`plugin.json` 契约（P000–P018，含目录名=id、相对路由、裸工具名、派生库路径、未支持权限拒载）、两来源发现（ASSET 优先）、状态机（available/blocked/rejected/conflict）、**拓扑排序与环检测**、CLI `list/check/verify`；隔离体检含 I2（内核不得 import 插件）与「core 不得 import app」。夹具 21 项全通过 |
| **§6/P5 第二件：前端管线 + 首个真插件** | `GET /api/plugins`（只下发可用且生效启用的插件）+ `GET /plugins-file/<id>/<rel>`（路径安全经 10 例未归一化请求验证）+ `web/plugin-host.js`（面板自登记 `ERWPanels`，单插件失败不影响内核）；**`plugins/focus/`（专注计时）从 `app.js` 原样搬出**，内核不再认识它。端到端：侧栏 17 项顺序不变、`#focus` 由插件渲染、倒计时可交互、0 console error。顺带修 `/api/weather` 离线 500（并消除 `ui_smoke` 的天气 TTL 抖动） |
| **§6.3 附属：悬浮球 AI 助手整体搬成插件**（v261009.16，一次覆盖 6 项） | `web/v260930-floating-agent.{js,css}`（1222 行 + 323 行，105 KB）整体迁到 [`plugins/floating-assist`](plugins/floating-assist/plugin.json)：悬浮球助手、**工具轨迹时间线**（`ERWFabTimeline`，内核 Agent 消息按 `?.` 空值保护消费）、**阅读中知识关联**（`/api/kb/related` + 阅读区 `context()`）、**会话历史回看**、写模式开关（**执行侧仍在内核**：草稿闸门是安全不变式）、**AI 助手人设编辑器**（改为插件贡献的设置页 tab，内核不再插 `#erw-persona-host`、不再广播 `erw-llm-settings-rendered`）。新接缝：**浮层槽位 `overlay`**（`#erw-overlay-host`，插件不再往 `document.body` 塞 DOM）与 **`window.ERWToast`**（内核提示条）。验收 16/16（真 Chrome）：启用态悬浮球 `inSlot=true/inBody=false`、面板五件套齐全、设置页多出人设 tab 且渲染 3 行；停用态悬浮球与人设 tab 一起消失、`ERWFabTimeline` 缺失时内核走空值保护、0 console error |
| **图谱渲染彻底交插件**（v261009.18，用户要求） | 用户实测「关掉知识图谱插件，图谱页仍画出那张难看的螺旋图」→ 说明内核还留着旧渲染。于是**删净内核的图谱实现**（renderGraphPage 的页面模板 + 筛选/选中/预览/导出 + 简易 drawGraph + 邻域计算，共 68 行；app.js 1493→1438 行），改为**页面级接管**：ERWGraphRenderers 的 graph.mount(host, ctx) 由插件画整页（markup 也搬进插件，插件 555→611 行），总览迷你图同理；无接管者时只给「请启用插件」提示，**不再画兜底图**。插件 core_min 提到 v261009.18（旧内核会因缺 enhance 而**明确拒载**，不是静默失效）。验收 32/32：插件在场 = 718 节点/1854 关系/预览/导出 149 项且内核绘制 0 次；插件缺席或停用 = 无画布、无筛选、内核绘制 0 次、页面明示「知识图谱不可用」 |
| **合并：三插件 → 一个「文献阅读工作区」**（v261009.17，用户要求） | 原 `literature-reader`（阅读区）+ `litnote`（笔记 tab + 2 个 AI 工具）+ `reader-assist`（阅读区 AI）合并为 [`plugins/literature-reader`](plugins/literature-reader/plugin.json) **v2.0.0**（前端三段 IIFE 拼接 1049 行 + 后端并入；插件数 9→7），说明文字里写清三块能力。**等价性风险已处理**：插件 id 变化导致工具前缀 `p_litnote__*` → `p_literature-reader__*`，`LEGACY_TOOL_ALIASES` 增四条映射让老人设白名单继续生效，内置阅读助手的默认工具名同步改名。验收：合并后三块能力同在一个插件（`readerTab` = info/annotations/notes/ai）、停用即整块不可用而列表页照常、工具面与草稿闸门不变、旧工具名只出现在别名映射行 |
| **§6.3 附属：阅读区 AI 助手拆成插件**（v261009.15；v261009.17 已并入 literature-reader） | 阅读区不再硬编码 AI：`{id:"ai"}` tab、`sideTab` 的 ai 分支、`S.ai` 状态与 `aiPanel/runAssist/mdLite/noteApply`（75 行）整体迁出阅读区。新增 `window.ERWReaderAssist` 接缝（由阅读区提供）：三条入口（选中动作 / 框选截图联动 / 笔记 AI 整理）派发给助手，派发前切到其 `tabId`，并在打开文献时 `attach(ctx)` 预交实时上下文（`selection/capture/activate/aiPolish`）。结果区渲染改用内核 `ERWMarkdown` 接缝。验收 16/16（真 Chrome）：启用态三条入口都把面板切到前台并显示待处理内容；停用态 AI 选项整体消失而阅读区其余功能照常 |
| **§6.3 附属：阅读区整体搬成插件**（v261009.14，反转 SCOPE §2.1 C6 旧决定） | 新增**阅读区接管接缝** `window.ERWReader`（注册 / `available()` / `open(paperId)` / `openByAttachment` / `context()`）：内核在文献列表页点「PDF 阅读工作区」或点附件徽章时调它，**无接管者时入口不出现**并给明确提示，文献列表/元数据条目页照常可用。[`plugins/literature-reader`](plugins/literature-reader/plugin.json) 为**纯前端插件**（`panel.mount` + `panel.style`，无 `entry`）——`web/literature.js` 642 行 + `literature.css` 134 行整体搬出内核，**文献数据与文件服务全留内核**（`/api/literature/*` 含 PDF 的 Range 206、批注 JSON 与删批注的 Preview 级联清理、笔记真值在 literature 条目、`/workspace-file/`；故 `core_api` 无需扩容、无数据安全风险）。顺带修掉：内核 `literature.js` 两处 `toast(...)` 引用**不存在的全局**（app.js 里 `toast` 是闭包私有）→「批注加入笔记」的错误路径一直静默 ReferenceError，现在插件自带提示实现。验收 14 项接缝契约（含「无接管者 → 入口消失 + 明确提示」）+ 22 项阅读区/笔记端到端（真 Chrome，PDF 3 个 canvas、笔记 6914 字同源、停用 litnote 后 tab 优雅消失） |
| **§6.3 附属：知识图谱可视化搬成插件**（v261009.13） | 新增**渲染接管接缝** `window.ERWGraphRenderers`（`graph` / `overview` 两个作用域）：内核渲染图谱页与研究总览迷你图时先问注册表，有接管者就不画兜底图、把画布交给它；**`enhance()` 抛错或插件缺席时内核回退自带 `drawGraph`**（内核零依赖，I2）。同时新增两个文案面接缝：`window.ERWContract`（kind/类别词/标记/关系只读契约）与 `window.ERWMarkdown`（Markdown 渲染 + `/workspace-file/` 图片归一）。[`plugins/knowledge-graph`](plugins/knowledge-graph/plugin.json) 为**纯前端插件**（`panel.mount` + `panel.style`，无后端），`web/v260922-research-pages.js` 的图谱部分 **935→385 行**、图谱专属 CSS 迁出内核。**顺带修掉两处漂移**：引擎自带标签表缺 `experiment` 导致（a）实验节点标签回落英文、（b）「仅知识条目」把实验条目一起取消勾选。验收 32 项全绿（真 Chrome）：能力等价（718 节点/1854 边、筛选联动、搜索定位、节点预览、导出弹窗 24 项）、内核重复绘制 0 次、**插件被拦时兜底可用且可交互**、总览迷你图可跳转定位、启停 API 与「不动其他插件状态」 |
| **§5.2 附属：文献笔记（工具 + 编辑界面）** | 工具部分见下条；**编辑界面**用新扩展点 `ERWPanels.readerTab` 把阅读区「笔记」tab 交给 [`plugins/litnote`](plugins/litnote/plugin.json)（`panel.mount` 让无导航页的 UI 也能被加载）；数据走插件自己的 `/api/plugins/litnote/note|note-image`，后端经 `core_api.lit_*`。内核删掉 `note()/saveNote()/uploadNoteImage` 与硬编码 tab。**附带修掉：核心阅读器依赖 CDN 加载 PDF.js**（本地 vendor 树存在但从没入库也没被使用）→ 本地优先 + `cMapUrl`/`standardFontDataUrl`。验收 21 项 |
| **§5.2 附属：文献笔记（工具包）** | `plugins/litnote/`（只注册工具）：`lit_context`→`p_litnote__context`、`lit_note_write`→`p_litnote__note_write`，**内核工具集回到规格的恰好 4 个**（SCOPE §5.1）。新增 `core_api` 文献面（`lit_list/lit_item/lit_note/lit_note_save/lit_annotations`）——文献库仍由核心维护，插件经 API 访问。写工具走内核草稿闸门。**迁移等价性**：人设白名单旧名会静默丢能力 → 加 `LEGACY_TOOL_ALIASES` 别名映射 + 走配置 API 把工具加回阅读助手。悬浮球写工具集合改为按 `/api/agent/tools` 的 `write` 标记动态推导。验收 22 项 |
| **§6/P6 第三件：用量计费搬成插件 + 事件扩展点** | 先实现 `ctx.events`（`core/events.py`：`on/emit`，订阅者异常隔离、浅拷贝、可取消）把 `agent.py` 的 `billing.record()` 倒置为广播 `llm.usage`（**零订阅者时内核照常**，I1）；再把 `app/billing.py` 原样搬入 `plugins/billing/`（含前端面板），数据 `System/billing/*` → 插件命名空间**原样认领**（57 行账本一字不差）。内核删净 `app/billing.py` / `web/v261008-billing.*` / 5 条 `/api/billing/*` 路由。验收 24 项：账本与单价表认领一致、旧接口 404、**倒置前后广播行为**（0 送达不报错 → 1 订阅者记账且口径一致）、面板与作用域、AST 判定内核零计费、测试不留假账 |
| **§6/P6 第二件：天气搬成插件 + 顶栏槽位** | 新扩展点**槽位面板**（`ERWPanels.register({id, slot:'topbar', renderSlot})`，内核给挂载点与 `data-plugin` 作用域，`P019` 校验已知槽位）；`plugins/weather/`（`app/weather.py` 原样搬入、配置自动迁移、缓存进 `System/Plugins/weather/`、顶栏卡片 + 设置模态 + 自带样式）；内核删净 `app/weather.py`/两条路由/`config` 的 weather 段/`loadWeather`/设置页天气 tab/顶栏卡片/相关 CSS。验收 16 项：槽位挂载、样式作用域、设置模态、配置迁移、内核零痕迹、0 console error。顺带修掉「槽位面板被塞进侧栏导致 `#weather` 无页面可渲染」的真 bug |
| **A9 收尾：DOM 变更接缝** | `web/dom-seam.js`（`window.ERWDom.onChildList`）：**7 处文档级 `MutationObserver` 收敛为 1 个实例**，提供 root 作用域 / ignore 过滤 / 按帧合并 / 回调隔离。闸门新增「不得在接缝外自建含 childList 的 observer」（负向用例 5 例）与运行期「observer==1、订阅方≥5」。验收 8 项（真浏览器）：作用域、合并、隔离、装饰等价（分页器与图谱状态条）全通过 |
| **§8 ②：插件工具接入 Agent** | `core/plugins/runtime.py`（进程级持有已加载插件，唯一写入点 `loader.load()`）+ `app/agent_tools.py` 工具面动态化（`all_tool_names` / `openai_specs` / 文本协议 / `list_tool_meta` / `execute` 查插件工具）+ `agent.py`/`config.py` 白名单改用动态集。**写工具明确拒绝**（草稿确认流尚无插件分支，不半接）。验收 17 项：未加载则不存在、加载即可用、异常隔离、白名单生效、写工具被拒、HTTP 面可见、无插件时与改造前一致 |
| **§6/P6 首件：资讯搬成插件** | `plugins/rss/`（`plugin.json` + `backend.py` + `web/panel.js` + `web/panel.css`）：`app/rss.py` 原样搬入、配置改 `config/plugins/rss.json`（**自动迁移内核旧 9 个源**）、缓存改 `System/Plugins/rss/`、面板自登记并内联源设置、样式按 §2 加 `[data-plugin="rss"]` 作用域；内核删净 `app/rss.py`/`/api/rss`/`/api/config/rss`/`config` 的 rss 段/`app.js` 的资讯实现/`styles.css` 的 news-*+rss-* 规则。验收 17 项（真浏览器 + HTTP）：顺序不变、样式生效、9 源已迁移、旧路由 404、内核零痕迹、0 console error |
| **§6/P5 第三件：后端执行层** | `core_api.py`（插件唯一允许 import 的门面）+ `core/plugins/context.py`（`ctx`：routes/mcp/storage/config，声明期校验命名空间）+ `core/plugins/loader.py`（拓扑顺序执行 `register(ctx)`，**每插件独立 try/except**，路由冲突按条拒，handler 异常只影响该次请求）+ `server.py` 三入口分发与 `ERW_PLUGINS_ROOTS`。验收 19 项（真服务）：路由/query/body/命名空间/冲突/**失败隔离**全通过 |

| 尚未开始 | 对应动作 |
| --- | --- |
| 前端补丁并入主题模块、`window.fetch` 包装改显式分页 API、两处 canvas 先画后弃 | A2 剩余、A10（`fetch` 那项需浏览器验收，见下） |
| 钩子倒置：base 不再硬依赖 `window.ERW*` 补丁 | A9 |
| doctor 的修复动作（`--fix-*`）、迁移框架、索引瘦身 | §5.5、A6–A8 |
| 插件运行时（`plugins/`、`core/plugins` 都还不存在） | §6、P5 阶段 |
| `ba77ddc` 的业务改动（文献 PDF 定位、列表排序口径） | 需手工解冲突，按功能迁移时处理 |

> **A10 的 `window.fetch` 包装（`v260922-performance.js`）需要浏览器验收**：它把 `/api/docs` 改写成 `paged=1&page=N&page_size=M` 的分页请求、给 `/api/graph` 加 `limit`（`research-overview` 路由下改写为 `/api/graph/overview`）、并给 `/api/search` 挂可取消的 AbortController。改成显式分页 API 要动 `app.js` 的列表分页与图谱取数调用点，属「改完必须点着看」的改动；本机当前无 playwright（`tools/shot_page.py` 依赖它），故本轮只把契约与风险点记录在此，未动手。

**优先级调整（v3）**：**A2 从第 2 位提到第 1 位**——`17682ce fix: restore PDF workspace after performance patch syntax error` 就是补丁层脆性造成的真实功能故障（一个补丁的语法错误直接打掉整个 PDF 工作区），而近 5 次提交里有 4 次都在补丁层做像素级调整，说明"靠在 base 上叠补丁"的成本已经在持续支付。

### 4.1 判据

一个功能算内核，当且仅当满足**全部**三条：

1. 直接读写「科研数据结构」本身（条目 / 项目 / 待办 / 活动 / 索引 / 关系）；
2. 去掉它数据会失去一致性或不可恢复（校验、原子写、回收站、导出）；
3. 是「录入 → 组织 → 检索 → 汇总/导出」闭环的必经环节。

只满足「有用」而不满足三条的，一律下沉为插件。

### 4.2 三层分类（已按 [docs/SCOPE.md](SCOPE.md) 对齐）

> 功能分层的**权威定义**在 SCOPE 文档（核心 / 附属 / 插件 + 判定规则）；下表是它与本方案动作项的对应关系。

| 层 | 内容 | 理由 |
| --- | --- | --- |
| **核心 Core**（零插件完整可跑） | 条目 CRUD + 原子写 + 回收站；命名/存放/字段契约与校验；SQLite 索引 + **中文 FTS 关键词检索** + 关系数据；项目 + 待办 + 活动；界面壳；**文献梳理**（条目/元数据/阅读状态/BibTeX/互链）；**文献阅读**（打开/翻页/批注；**笔记见附属**）；**AI 基础**（对话 + SSE + 上下文注入 + **4 个知识库工具** + 草稿确认流，**不含直写路径**——边界见 [SCOPE §5](SCOPE.md)）；数据留档（登记与关联）；汇总导出（Markdown 知识包 / BibTeX） | 逐条对上 [SCOPE §2.1](SCOPE.md) 的 8 条核心功能与 §2.4 判据 |
| **附属 = 官方随包插件**（**默认开**、设置里可关；与插件同机制、同等隔离要求） | 天气；RSS 科研资讯；专注计时；知识图谱可视化；里程碑 3D 时间线；**AI 附属**（人设系统、`direct` 直写模式、悬浮球助手、阅读区 AI 助手、多模态截图、工具轨迹时间线、术语建档流水线）；**文献笔记**（编辑器 + `lit_context`/`lit_note_write`）；阅读中知识关联；用量计费；会话归档/历史回看；mermaid/mathjax 按需渲染 | 属科研主线或官方维护 → 默认开；关掉不影响核心闭环（[SCOPE §2.2](SCOPE.md)、§5.2） |
| **插件 = 可选插件**（**默认关**、不随包、可自由增删） | 语义检索 RAG（现处 `feature/rag-v261009`）；**数据视图（指标表/曲线）**；**报告导出（DOCX/PDF）**；文献库同步；备份/快照；统计绘图桥 | 与数据结构无关或纯展示/外部集成（SCOPE §2.3） |

> ※ 计费与悬浮球有**前置条件**：见 P14，须先把 `app.js` 的硬依赖倒置成钩子，否则摘除即坏页面。

**RAG 定级依据（按你的口径量化）**：它是唯一「自带独立进程 + 独立解释器环境 + 92 MB 模型权重 + 69 MB 向量库」的功能，内核要付 ≈161 MB 磁盘与一条常驻服务；而内核的关键词 FTS 已能覆盖「有没有相关内容」，语义检索属增强而非闭环必经环节。

### 4.3 精简动作清单（按收益排序）

| 动作 | 现状 → 目标 | 证据/收益 |
| --- | --- | --- |
| A1 vendor 按需加载 | 5 个库在 `index.html:35-39` 无条件 defer（8.2 MB）→ mermaid/mathjax 只在 Markdown 预览需要（`app.js:1114,1131`、补丁 `:270`）、pdfjs 只在文献视图需要（`literature.js:9-24`） | 首屏 < 1 MB |
| A2 前端补丁合并 | 13 个补丁 → 按主题合并为 6~8 个模块，装配改由 manifest 驱动 | 消除顺序依赖（P7/P14） |
| A3 派生数据治理 | 删冲突副本（7.1 MB）、关库 `wal_checkpoint(TRUNCATE)`、明确「Cache 全可删」+ 一键重建 | P6/P22 |
| A4 会话/草稿治理 | 69 草稿 + 24 回收无 TTL → 加过期策略（与 `.scratch` 同口径） | 防单调增长 |
| A5 `.scratch` 加限额 | 时间清理 → 时间 + 体积双阈值 + 目录白名单（禁 pycache / 浏览器 profile） | P10 |
| A6 删死代码 | 删 `project_bridge.py`；`search.py` 决定并入内核检索还是删除 | P11 |
| A7 层级解耦 | `perf_index_query` 不再 import `agent`；私有跨模块调用改公开 API | P12 |
| A8 导入期副作用清零 | `config` 的 `load_secrets/reload_all` 移入显式 `init()`，由 `build_server()` 调用；解开顺序炸弹 | P13/P21，插件隔离前提 |
| A9 前端接缝改契约 | 15 个 `window.ERW*` + 5 个自定义事件 + 6 个 MutationObserver → 统一注册表 + `ctx` 契约 | §6.3 |
| A10 消除双实现 | 删 canvas 先画后弃 ✅ **图谱页已删**（`graphEngineAvailable()`：引擎在场内核不再白画，补丁缺席自动回退；实测内核绘制次数 1→0，`.scratch/tmp/verify_graph_canvas_ownership.py` 19/19）；`#research-overview` 迷你图那层**刻意保留**（取数失败时是兜底）。**待办**：`window.fetch` 包装改为显式分页 API | P14 |
| **A11 摘掉悬空工具** ✅ 已执行 | `kb_retrieve` 已从 `mcp/tools_workspace.py` 的 `TOOLS` / `HANDLERS` / 实现中移除（工具数 26 → 25，`--selftest` problems 为空）；**待办**：给自检加「工具实现可导入」探测，否则同类悬空注册仍抓不到（I10） | P23 止血完成 |
| **A12 RAG 本地数据处置** | 161 MB（`.rag/` 92 MB + `rag.sqlite` 69.2 MB）现在**无用但可复用**（源码在 `feature/rag-v261009`）：① 保留 ② 清理省 161 MB ③ 做插件时原位复用 —— 见 §8-D6。**接入可行性结论（v261009.16 核实）**：RAG 作为插件**现在做不了**，缺三件内核能力——`ctx.search.addSection`（搜索框注入语义结果）、`ctx.jobs`（索引后台任务与进度）、`process` 类插件的隔离运行（`core/plugins/loader.py` 目前只跑 `inprocess` 的 `register(ctx)`）；这三件都是**内核侧新接缝**，得先实现并写进 PLUGIN_SPEC，才轮得到把 RAG 服务端搬过来。另外还差一个你的决定：那 161 MB 是「保留原位复用 / 清掉重建 / 只留 SQLite 不留向量目录」。在决定之前，我**没动**这些数据 | P24 |
| **A0 定基线** ✅ 已定（v3.1） | 内核基线 = `feature/slim-workbench-v261009`；RAG 分支的未推送提交已推上 origin；`main` 落后 204 个提交的合并策略仍待定 | P27，基线定了后续动作才有共同前提 |
| **A13 取回验证工具**（v3 新增） | 从 `feature/rag-v261009` / `feature/ai-assistant-v260930` 取回 `tools/kb_smoke.py`、`tools/shot_page.py`（并评估 `shot_prep.py`、`rag_check.py`），恢复「改动后必跑冒烟」；顺带修 `AGENTS.md` 的引用 | P26/P29，精简的安全网 |
| **A14 上游对齐**（v3 新增） | 先读 `upstream/feature/custom-knowledge-types`（对应 §8-D2）与两条上游 RAG 分支，再定插件契约的 kind 扩展设计 | P30，避免重复造 |
| **A15 AI 附属化**（v3 新增，依赖 A9/A10 钩子倒置） | 把 AI 的非基础部分按 [SCOPE §5](SCOPE.md) 迁为附属插件：人设系统、`direct` 直写模式、悬浮球、阅读区助手、多模态、轨迹时间线、术语流水线、两个文献工具；**核心只留 A1–A6（对话 + 上下文 + 4 工具 + 草稿确认 + 模型接入 + 会话存储）** | 落实「保留基础 AI，其余靠插件」；核心同时获得「无自动改库路径」的安全性质 |
| **A16 迁移等价性验收**（v3 新增，**每个功能迁移都做**） | 迁移前冻结行为基线（路由 / 工具 / UI / 存储 / 配置），迁移后产出《迁移等价性报告》；出现「回归」不得合并 | [PLUGIN_SPEC §11](PLUGIN_SPEC.md)：原功能与效果不变是准入门槛，不是加分项 |
| **A17 打包依赖审计**（v3 新增） | 打包功能为插件时跑 `pack --check`：有前提依赖必须显式声明 + 在安装/启用时提示；未声明依赖 → 打包中止 | [PLUGIN_SPEC §10](PLUGIN_SPEC.md)、不变量 I13 |

---

## 5. 数据结构重构方案

### 5.1 单一契约源（先做，其它都依赖它）

新增 `core/contracts/kinds.py`（或 `kinds.json` + 加载器），把 3 处声明合并为一份**机器可读**契约：

```python
KINDS = {
  "experiment": KindSpec(
      id_prefix="experiment", dir="Knowledge/Experiments", title_prefix="实验-",
      statuses=("计划","进行中","完成","受阻","已归档"),
      date_field="record_date", required_marks=("experiment",),
      body_skeleton=(("摘要",""),("目标与假设",""),("配置与参数",""),("数据与口径",""),
                     ("结果",""),("结论与失效模式",""),("留档路径",""),("关联","")),
      fields=("attachment",), plugin=None,
  ), ...
}
```

由它**生成**（不再手抄）：`kb_constraints` 的 kinds/schema/marks/storage 文本（`mcp/constraints.py` 改为渲染器）；标题校验器与规则码（`mcp/naming.py` 与 `kb_naming.py` **合并为一份**）；正文骨架（`store.create_doc`）；前端表单选项（或由 `/api/contract` 下发）；kind→目录与 `WORKSPACE_LAYOUT`（`store.py`、`workspace.py`、`perf_index_*`、`mcp/bridge.py`、`mcp/constraints.py` 全部消费同一份）。

**完成判据**：`grep -r "Knowledge/Experiments"` 只剩契约文件与生成物；`experiment` 在两条写入路径上得到同一校验结果；`WORKSPACE_LAYOUT` 只有一处定义。

> 插件注册的新 kind（`x-<plugin>-*`）也由这份契约校验；内核必须容忍未知 kind（不进内核导航、不阻断索引）。

### 5.2 条目模型：信封 + 类型扩展

| 段 | 字段 | 规则 |
| --- | --- | --- |
| 信封（共有） | `id, kind, title, created, updated, status, tags, kind_marks, pinned` | 强校验 |
| 组织关系 | `project_ids[]`（**唯一主键**）+ `projects[]`（显示派生）、按 kind 唯一的日期字段 | 见 §5.4 |
| 类型扩展 | `summary_type, authors, year, venue, doi, url, cite_key, attachment` | 由 `KindSpec.fields` 声明，未声明字段写入即报错 |
| 插件扩展 | `x-<plugin_id>-*` 或 `extensions: {<plugin_id>: {...}}` | 内核透传不解释 |

配套：① 契约补上 `project_id/project_ids`、`attachment`（数据有、契约无）；② **`status` 与 `kind_marks` 改枚举校验**（现已出现 `idea.status=进行中` 与 2 个越界 mark）；③ 每 kind 的**法定日期缺失即 error**（P5）；④ 未声明字段写入 → warn 并进体检清单。

### 5.3 id 与 kind 漂移的处置

不改 id 格式（199 条数据 + 全库引用都靠它），改为：契约明确 **id 是不可变标识、不承载类型语义**（修正文档说法）；`doctor` 增加 `id_prefix_mismatch`（已知 25 条）；可选 `--fix-ids`（生成新 id + 改文件名 + 重写引用 + 追加事件），**必须 dry-run 先行、可回滚**，默认不执行。

### 5.4 关系层与项目引用（含现存不一致的修复）

- **统一归属写入路径**：以 `project_ids` 为唯一主键，`projects[]` 为显示派生；**HTTP 与 MCP 必须走同一个写入函数**（现在 MCP 根本不写 id → P15）。修复后重建索引，验证 `document_projects` 中 `project_id=''` 的行数 = 0。
- 图节点 key 一律用 `project_id`（若缺失则**跳过并记警告**，而不是退化成 name 造出幽灵节点，`perf_index_core.py:174`）。
- 关系继续「正文 WikiLink + 小节语义」为事实来源（现状合理），增加：双向一致性校验；`document_links` 增 `relation_type / resolved_by(id|title) / broken` 三列，支持断链清单（现有 2 条不可解析）。
- 条目改名与项目改名走同一套 dry-run 影响面报告（`projects.py:345,348,381` 已有雏形）。

### 5.5 派生索引与迁移框架

1. **版本单一入口**：以 `System/schema.json` 为唯一记录；`perf_index_db.py:13-14`、`config.py:20`、`billing.py:31` 改为读它；磁盘版本 > 代码版本时**拒绝写入**并提示（防旧 exe 污染新数据）。
2. **迁移框架**：`core/index/migrations/NNNN_*.py`，声明 `from/to/apply/verify/rollback`；执行前自动备份到 `System/Backups/<ts>/`；幂等；`--dry-run` 打印影响面。**替换**现在 `document_links`/`documents_fts` 的 DROP 重建式迁移。
3. **索引瘦身**：`graph_edges` 不再重复物化 tag/project 边（可由 `document_tags`/`document_projects` 连接得到），去掉 typed 边的通用镜像边；`documents_fts` 只保留 `doc_id + seg`（其余四列无人读），正文真值只在 md。
   > **v261009 实测更正（重要）**：这一条的收益被高估了。实测 `index.sqlite` **35.70 MB 里只有 7.19 MB 是活数据**——`PRAGMA freelist_count` = **7299/9139 页（80%）是空闲页**，另有 **21.39 MB 的 `-wal`**。而本条能省的：`tag`+`project` 边 1356 行 ≈ **0.25 MB**、FTS 四列 ≈ **0.8 MB**，合计 < 1 MB。
   > 真正的瘦身是**维护**：`python -m core.index.maintain --checkpoint --vacuum` 已实测把 35.70 MB + 21.39 MB WAL 收到 **7.14 MB + 0**（回收 ≈49.9 MB），且经 10 组查询 + 38 个 schema 对象比对证明语义中性；`server.py`/`client.py` 退出时自动 checkpoint 防复发。删列/删边仍可做（省写放大），但**不该作为瘦身的主要手段**。
4. **插件数据的归属**：插件自有派生数据一律进 `System/Cache/<plugin_id>.sqlite`（RAG 就是 `rag.sqlite`），**不得**写 `index.sqlite`；插件启用/停用时由内核负责建库与清理。
5. **体检 `python -m core.doctor`**：磁盘 md 数 vs `documents` 行数；`id_prefix_mismatch`；缺法定日期；**status/kind_marks 越界**；未声明字段；title ≠ 首个 H1；断链/单向关系；`document_projects` 幽灵行；`System/Trash/` 目录 vs kind 列表；同步冲突文件；Cache 体积与 WAL；**孤儿派生库**（无对应插件的 `*.sqlite`）。
   - 注：旧 TODO 曾记「25 条实验不在索引」，实测**已修复**（`documents.experiment=25`），该项可关闭。
6. **缓存协议归一**：现在有 5 种自研有效性协议（`documents.(mtime_ns,size)`、`todos_signature`、`activity_offset` 字节偏移、weather 的 `key+timestamp`、rss 的 `timestamp`），统一为「源指纹 + 生成时间」两字段抽象。
7. **JSON 序列化归一**：`library.json` 的 `categories/tags/projects/favorite`、`AgentChats` 的 `refs/images` 都是**字符串化 JSON/repr**，迁移为真 JSON（一次性修复脚本 + dry-run）。

### 5.6 System 状态文件规范化

| 文件 | 改动 |
| --- | --- |
| `todos.json` | 统一 `project_id`（现在 1/3 有）；补 `schema_version` |
| `projects.json` | 补 `schema_version`；`name` 唯一性校验（重名行为当前未定义） |
| `activity.jsonl` | 事件统一 `{schema_version, ts, type, actor, ref, payload}`；**统一计数口径**（weight 求和 vs 行数二选一，P18）；旧 5 类兼容，只追加不改历史 |
| 各 JSON | 统一 envelope `{schema_version, data}`，或保留裸结构 + 中央版本表（§8-D3 二选一） |

---

## 6. 插件化方案

> **打包 / 安装 / 依赖 / 校验的完整规范见 [docs/PLUGIN_SPEC.md](PLUGIN_SPEC.md)**：统一插件库（`DATA_ROOT/plugins/` 用户库 + `ASSET_ROOT/plugins/` 随包库）、目录态与单文件包态、前提插件与级联停用、安装/启停/更新/卸载流程与 CLI、权限与安全校验、「丢进去就能用」的 5 个前提。本章只列与本方案动作相关的最小集。

### 6.1 设计约束（先钉死）

| 约束 | 来源 | 设计后果 |
| --- | --- | --- |
| 内核单进程 stdlib-only | `mcp/README.md:3`（零第三方依赖）、`server.py` 现状 | 插件默认**同进程**加载；重型/带依赖的走**独立进程 + HTTP** |
| `web/` 与 `app/` 都进 exe，只读 | `spec:8`、`build_client.bat:19` | 插件一切资源在 `DATA_ROOT/plugins/<id>/`，运行期加载 |
| Markdown 是唯一事实来源 | `paths.py`、AGENTS.md | 插件**不得**另建事实来源；自有数据必须可重建或明确标注 |
| 导入期会读写 config，且模块间存在顺序炸弹 | `config.py:665-666`；实测 `import app.workspace` 直接 ImportError（P21） | 插件加载 core 必须经**单一 `init()` 入口**，禁止在 import 期触碰 `app.*` 子模块 |
| Agent 侧还有一条 MCP 通道 | `mcp/` | 插件后端能力需**同一份实现**同时暴露给 HTTP 与 MCP，不能两写 |
| 分支/白名单会把功能「藏」起来 | P24/P27（RAG 只存在于分支上）、P25（`mcp/` 曾不在白名单，现已入库） | 新插件目录必须同时决定「是否入库」；跨分支功能必须有单一基线 |
| **随包（bundled）插件要能随 exe 发布** | `ResearchWorkbench.spec:8` 目前只打包 `web/` 与 `VERSION` | `bundled` 插件走 `ASSET_ROOT/plugins`（只读、随版本升级），用户插件走 `DATA_ROOT/plugins`（可改可删），同名时 ASSET 优先；打包脚本需加 `--add-data "plugins;plugins"`（见 §8-D-E） |

### 6.2 插件形态

```text
plugins/<plugin_id>/
├─ plugin.json          # manifest（唯一必需文件）
├─ backend.py           # 可选：register(ctx)
├─ web/{panel.js,panel.css}
├─ migrations/
└─ README.md
```

> 分发时也可为**单文件包** `plugins/<id>-<version>.zip`：**自动解包到 `plugins/<id>/`（每插件一个独立文件夹、互不混用）**，先临时后原子、禁止逐文件覆盖——见 [PLUGIN_SPEC §2](PLUGIN_SPEC.md)。

```json
{
  "id": "weather", "name": "天气", "version": "1.0.0",
  "api_version": 1, "core_min": "v261010", "kind": "inprocess",
  "distribution": "bundled",
  "default_enabled": true,
  "entry": "backend.py",
  "permissions": ["net:http", "storage:own", "config:own"],
  "nav": [{"id": "weather", "label": "天气", "mount": "web/panel.js"}],
  "routes": [{"method": "GET", "path": "forecast"}],
  "mcp_tools": ["weather_now"],
  "settings_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
  "jobs": [{"id": "refresh", "interval_min": 30}],
  "events": ["doc.updated"]
}
```

> `distribution` + `default_enabled` 就是「附属 vs 可选插件」的**唯一区别**：`bundled` + `true` = **附属**（随包、默认开，如天气 / RSS / 专注计时）；`optional` + `false` = **可选插件**（默认关，如 RAG、数据视图、报告导出）。两者在加载、注册、隔离、卸载上走**完全相同**的代码路径。

重型插件的 `"kind": "process"` 变体（RAG 若重建就走这支）：

```json
{
  "id": "rag", "kind": "process", "entry": "service.py",
  "process": {"port": 8770, "python_env": "ERW_RAG_PYTHON", "model_dir": ".rag",
              "auto_start": true, "health": "/health", "degrade_to": "keyword"},
  "routes": [{"method": "GET", "path": "search"}, {"method": "GET", "path": "status"}],
  "mcp_tools": ["kb_retrieve"],
  "storage": {"derived_db": "System/Cache/rag.sqlite"}
}
```

### 6.3 扩展点与命名空间

| 扩展点 | 注册方式 | 命名空间约束 |
| --- | --- | --- |
| HTTP 路由 | `ctx.routes.get("forecast", handler)` | 前缀固定 `/api/plugins/<id>/`；**禁止**注册裸 `/api/*` |
| MCP 工具 | `ctx.mcp.tool("weather_now", spec, handler)` | 对外名 `p_<id>__<tool>`；内置 Agent 工具同理；**未启用则工具不出现**（不能像现在 `kb_retrieve` 那样悬空注册） |
| 知识 kind | `ctx.kinds.register(KindSpec(...))` | 仅允许 `x-<id>-<kind>`；内核必须容忍未知 kind |
| 前端面板 | manifest `nav[]` + `mount(ctx)` | 内核按 manifest 渲染导航与挂载点；插件**不得**改内核 DOM |
| **浮层槽位 + 提示条接缝** | `nav[].slot:"overlay"` + `ERWPanels.register({slot:'overlay', renderSlot})`；`window.ERWToast(msg, error?)` | 内核在 `index.html` 提供 `#erw-overlay-host`（`KNOWN_SLOTS` 加 `overlay`），「始终挂在页面上」的 UI（悬浮球）挂在这里而**不是** `document.body`；`ERWToast` 把内核自家提示条暴露出去，结束 5 个模块各写一份 toast。首个使用者是 [`plugins/floating-assist`](plugins/floating-assist/plugin.json) |
| **槽位面板** | manifest `nav[].slot` + `ERWPanels.register({slot, renderSlot})` | 内核提供挂载点并在容器上带 `data-plugin="<id>"`；插件只在容器内画东西。已知槽位在 `core/plugins/manifest.KNOWN_SLOTS` 声明（`topbar` / `overlay`），新增槽位是**有意的动作** |
| **设置页 tab** | `ERWPanels.register({id, settingsTab: {id, label, render}})` | 任何模块都能往「设置」加一个 tab（内核只负责与内置 tab 排在一起，`app.js` 不加功能分支）。**只贡献 tab 的面板不进侧栏**；`ui_smoke` 断言它出现在设置页、点开非空、且不在侧栏 |
| **阅读区 tab** | `ERWPanels.register({id, readerTab: {id, label, render}})` + manifest `panel.mount` | 任何模块都能往**文献阅读区**右侧加一个 tab；阅读器传入上下文 `{paper, refreshList, aiPolish}`（「AI 整理」这类内核能力由阅读器回调，依赖方向仍是插件→内核）。首个使用者是 [`plugins/litnote`](plugins/litnote/plugin.json) 的「笔记」tab（SCOPE §2.2：阅读进核心、笔记进附属） |
| **无导航页 UI** | manifest `panel: {mount, style?}`（`P020` 校验） | 只贡献 tab / 槽位组件、**不占侧栏**的插件也要有前端脚本入口——此前宿主只加载 `nav[0]`，这类插件脚本永远不会被注册 |
| **契约只读视图** | `window.ERWContract`（app.js 导出） | 七类 kind、类别词、`kind_marks`、关系的**只读**中文契约（`kinds/kindLabels/kindLabel/entityLabel/marks/relations/relationLabel`）。插件**不得**再各抄一份标签表——此前图谱补丁自带一份且缺 `experiment`，实验节点标签回落英文 |
| **Markdown 渲染** | `window.ERWMarkdown.renderInto(el, raw)` / `.normalizePaths(html)` | 插件渲染笔记正文走内核同一套（marked + DOMPurify + hljs + mermaid/mathjax 按需），观感一致；`normalizePaths` 提供 `/workspace-file/` 图片路径归一（插件不必再抄正则） |
| **图谱渲染接管** | `window.ERWGraphRenderers.register({id, graph?, overview?})` | 内核渲染**图谱页** / **研究总览迷你图**时把画布交给接管者：`await enhance(canvas, ctx)` **resolve=已接管**（内核不画兜底图）、**throw=没接管**（内核打印原因并回退 `drawGraph`）；取消（页面已切走/画布被换）要 `return null` 而非抛错。内核零依赖——插件缺席时图谱页照旧可用（P14 红线 5）。首个使用者是 [`plugins/knowledge-graph`](plugins/knowledge-graph/plugin.json) |
| **阅读区接管** | `window.ERWReader.register({id, open, openByAttachment, context?})` | 内核在文献列表页点「PDF 阅读工作区」/点附件徽章时调它；**无接管者时入口不出现**、用户试图打开时给明确提示，文献列表/元数据条目页照常可用。**文献数据与文件服务留内核**（`/api/literature/*`、PDF 的 Range、批注级联清理、笔记真值）——插件只做 UI，故 `core_api` 无需扩容。首个使用者是 [`plugins/literature-reader`](plugins/literature-reader/plugin.json)（SCOPE §2.1 C6 于 2026-10-10 反转：阅读区改附属） |
| **插件管理（内核页）** | 预览 `GET /api/plugins?detail=1`；启停 `POST /api/plugin-manager/<id>/enabled` | 通用能力，与具体插件解耦：预览只读清单（状态/权限/路由/面板/工具/依赖/配置接口）；配置读写**转发**给插件自己的 `/api/plugins/<id>/config`（内核不解释其内容）；启停只改 `System/plugins.json` 并热重载，**不删文件、不动数据** |
| **搜索分区** | `ctx.search.addSection({id,label,render})` | 内核搜索框保留关键词结果，语义结果由插件注入（RAG 的位置就在这里） |
| 设置 | manifest `settings_schema` | 内核渲染表单，值落 `config/plugins/<id>.json` |
| **事件** | `ctx.events.on("doc.updated", cb)` | 只读载荷；回调内禁止同步长耗时。**已实现**（`core/events.py`：订阅者异常隔离、浅拷贝载荷、取消订阅）；首个使用者是计费插件订阅 `llm.usage` |
| 后台任务 | `ctx.jobs.add(...)` | 内核负责调度/超时/日志 |
| 存储 | `ctx.storage` | `Workspace/Plugins/<id>/`、`System/Plugins/<id>/`、`System/Cache/<id>.sqlite` |

### 6.4 隔离不变量（「插件不得影响精简版」的可验证定义）

| # | 不变量 | 如何自动验证 |
| --- | --- | --- |
| I1 | 内核**零插件**可完整启动与使用（含全部附属插件一起关闭） | `tools/plugin_check.py --assert-core-only`：`plugins/` 置空 + `--no-plugins` 启动后跑 `tools/kb_smoke.py` 全绿 |
| I2 | 依赖方向单向：内核不得 import 插件 | 静态检查 `core/**`、`server.py` 无 `plugins.` / `import_module("plugins…")` |
| I3 | 插件只依赖稳定门面 `core_api` | 插件只 `from core_api import …`；直接 import `core.model.store` 等私有模块 → 拒绝加载 |
| I4 | 单插件失败不影响内核 | 每个 hook 包 `try/except + 超时`；连续失败自动停用并在健康面板可见 |
| I5 | 存储互不越界 | 插件只拿到自己命名空间的路径对象；内核校验解析后绝对路径前缀 |
| I6 | 前端不得覆盖内核 | 插件 JS 以 module 挂载；lint 禁 `window.<name> =` 重定义与全局选择器样式 |
| I7 | 版本门控 | `api_version` 不匹配 → 拒绝加载并提示，内核继续运行 |
| I8 | 资源可控 | 每插件存储配额 + 调用耗时统计；超配额只禁该插件写 |
| I9 | 加载顺序无关 | 每个插件在独立 `try` 中注册；`core_api.init()` 之后才允许触碰 core 子模块 |
| **I10** | **注册即可用**：注册进工具表/路由表的入口必须可导入且能应答 | 自检新增「逐个工具做一次导入与最小调用探测」，堵住 P23 这类悬空注册（现在的 `--selftest` 只校验表结构，抓不到） |
| **I11** | **加载失败必须给出可执行的原因**：`rejected` / `blocked` / `conflict` + 修复建议，**不得静默失败** | `python -m core.plugins list` 展示每种状态与原因；安装自检用例（[PLUGIN_SPEC §9](PLUGIN_SPEC.md) 的 5 条前提逐条造错验证） |
| **I12** | **提取功能必须行为等价**（原功能与效果不变）：路由 / 工具 / UI / 存储 / 配置 五项逐项一致，差异必须显式声明为「有意变化」 | 每个功能迁移附《迁移等价性报告》（[PLUGIN_SPEC §11](PLUGIN_SPEC.md)）；契约 diff 脚本 + `shot_page.py` 前后对照 |
| **I13** | **前提依赖在打包期显式化、安装启用时必提示**：检测到未声明依赖 → **打包中止**；缺依赖 → 按 `error`/`warn` 分级提示，不得静默 | `python -m core.plugins pack <feature> --check` 与 `check <id>`；打包自检用例：故意造一个隐式依赖，验证会被拦下 |

### 6.5 生命周期

发现（扫 `plugins/*/plugin.json`）→ 校验（manifest/版本/权限）→ 注册（只登记不执行）→ 启用 → 运行 → 禁用（注销路由与面板，保留数据）→ 卸载（移入 `System/Trash/plugins/<id>/`，数据默认保留并提示）。

> 含 CLI、级联停用、更新与冲突处理的完整流程见 [PLUGIN_SPEC §5](PLUGIN_SPEC.md)；「丢进去就能用」的 5 个前提见 [PLUGIN_SPEC §9](PLUGIN_SPEC.md)。

后端变更需**重启**才生效（与 AGENTS.md「长驻进程改代码必须重启」一致）；前端面板刷新后热注册。

### 6.6 第一个插件选谁 + RAG 怎么回来

**第一个插件建议用「专注计时」或「天气」**，不要用 RAG：

| 候选 | 为什么适合打样 | 需要先做的事 |
| --- | --- | --- |
| **专注计时** | 0 路由、纯前端、无数据耦合——正好验证「manifest 渲染导航 + `mount(ctx)` + 禁用即消失」这条最小闭环 | 无 |
| **天气** | 2 路由、状态独立（`Cache/weather.json`）、今天仍在用 | 把 `weather.py` 的缓存路径改走 `ctx.storage` |
| 计费 / 悬浮球 | 价值高 | 先做 A10/P14 的钩子倒置 |
| **RAG** | 完整的「可选组件」参考实现，**源码在 `feature/rag-v261009`**（可直接取回，不必重写） | 见下 |

**RAG 若要恢复，按插件形态重建（不要进内核）**：

1. 建 `plugins/rag/`：`plugin.json` 用 §6.2 的 `kind:"process"`；`backend.py` 只做注册（把内核曾有过的 `_rag_client/_rag_http/_rag_retrieve/_rag_status` 这套「源码模式直连 + 打包模式走 HTTP + 缺包降级」逻辑搬进来）。
2. 从 `feature/rag-v261009` 检出 `rag/`（源码完整：`service/client/search/store/embedder/pdf/chunk/build_index/config` + eval 报告），**无需重写**；`.rag/` 权重 92 MB 与原 `rag.sqlite` 69.2 MB 可原位复用，必要时跑一次全量建库。
3. 检索入口两处都走注册表：HTTP 由 `/api/plugins/rag/search` 提供，UI 通过 `ctx.search.addSection()` 注入到现有搜索弹窗（不再是内核里的固定分区）。
4. MCP 的 `kb_retrieve` 改为「插件在册才注册」——插件未启用时该工具**不出现**（现在它悬空注册并报错，P23）。
5. 验收：插件关掉 → `/api/plugins/rag/*` 404、搜索弹窗只剩关键词分区、`kb_retrieve` 不在工具表、`kb_smoke` 全绿；插件开 → 语义结果与 PDF 页码命中恢复。

### 6.7 反模式（红线）

1. 插件在 import 期执行副作用（内核启动即被拖慢/拖崩）。
2. 插件直接改 `config/app.json` 或写 `Workspace/Knowledge/`（必须走 `ctx`）。
3. 插件注册裸 `/api/*` 路由或覆盖内核 CSS 选择器。
4. 插件把内核模块当内部 API 用。
5. 内核功能依赖某个插件才能工作（含「默认插件」也不行；可关闭的只能进 `core_plugins/`）。
6. **注册了却不可用的入口**（P23）：工具/路由必须来自「已启用的插件」，且自检要能探测到导入失败。

---

## 7. 实施顺序与验收

| 阶段 | 内容 | 交付 | 验收命令（必须全绿） |
| --- | --- | --- | --- |
| **P0** | 修悬空入口 + 定基线 + 契约源抽取（不改行为） | 摘掉/接管 `kb_retrieve`（✅ 已完成）；定内核基线（A0）；`core/contracts/` + 3 处改为消费 | `python -m mcp.server --selftest`、`python tools/kb_smoke.py`（先从对应分支取回，A13），并新增「工具可导入」探测（I10） |
| **P1** | 校验合并 + 补齐缺口（P2/P5/P16） | 一份校验器；status/mark 枚举校验；Agent 可写日期/状态 | 新增「Agent 建 experiment 违规标题被拒」「越界 status 被拒」用例 |
| **P2** | 死代码清理 + 层级解耦 + 导入期副作用清零（P11/P12/P13/P21） | `indexer` 不再 import `agent`；`config.init()`；顺序炸弹拆除 | `python -c "import server"` 不写盘（比对 config 目录 mtime） |
| **P3** | Doctor + 迁移框架 + 索引瘦身（P3/P4/P6/P15/P17/P19/P20/P22/P24） | `python -m core.doctor`；项目归属单一写入路径 | 清单含已知项（25 条 id 漂移、2 行幽灵归属、5 个冲突文件、RAG 分支遗留的 `rag.sqlite`），`--dry-run` 不落盘；修复后幽灵归属 = 0 |
| **P4** | 前端模块化 + vendor 按需 + 钩子倒置（A1/A2/A9/A10） | 首屏 < 1 MB；manifest 装配；base 不再直接调补丁 | `node --check web/*.js`、`tools/shot_page.py` 截图冒烟 |
| **P5** | 插件运行时 + 首个插件（专注计时或天气） | `plugins/` 空集可启动；一个真插件跑通 | `tools/plugin_check.py --assert-core-only` |
| **P6** | 迁移非内核功能：天气 → RSS → 计费 → 悬浮球 | 每个都能单独禁用 | 每迁一个跑 `kb_smoke` + 插件自检 |
| **P7** | （可选）RAG 按插件重建 | `plugins/rag/` + 复用权重/向量库 | §6.6 第 5 条双向验收 |

顺序原则：**先契约、再解耦、后搬运**。契约不归一就插件化，等于把分叉复制到更多地方。

> 两条硬门槛（[PLUGIN_SPEC](PLUGIN_SPEC.md)）：① 每个功能插件化都必须附**《迁移等价性报告》**——原功能与效果不变（§11）；② 打包前必须通过**依赖审计**——有前提依赖要显式声明并在安装/启用时提示，未声明则打包中止（§10）。

> 注：表中 `tools/kb_smoke.py` **不在当前分支**（它在 git 里，见 P26），作为验收命令前需先从对应分支取回（A13），或改用 `tools/self_check.py`。

---

## 8. 需要你拍板的决策点

| # | 问题 | 选项 | 我的建议 |
| --- | --- | --- | --- |
| **D1** | Agent / PDF 工作区 / 知识图谱，谁是内核？ | ✅ **已全部裁定**（[SCOPE §4](SCOPE.md)）：**阅读进核心**、**文献笔记进附属**、图谱进附属；数据先表化、报告插件化、AI 只留基础 4 工具 | 与 SCOPE §2 分层表一致；尚未实现的项见 [SCOPE §6 未来规划](SCOPE.md) |
| **D2** | 插件能否注册新 kind？ | ① 允许（`x-<id>-*`）② 不允许，只能展示/分析 | ① 但受契约约束；否则「数据集/协议」这类扩展永远要改内核 |
| **D3** | 数据重构激进程度 | ① 只加契约源 + doctor，不动 199 条数据 ② 补字段/统一 project_id/修幽灵归属 ③ 连 id 一起迁移 | ①→② 分两步（②含修 P15 这类**已发生**的不一致）；id 迁移单独作为可选操作 |
| **D4** | 插件运行形态 | ① 默认同进程 ② 默认独立进程 | ① 为常态；模型/GPU 类走 ②（RAG 属此类） |
| **D5** | 精简力度 | ① 只移出内核 + 按需加载 ② 直接删天气/RSS/专注计时 | ①：RSS 与天气**今天仍在写入**，先移出、观察一个版本再谈删 |
| **D6** | **RAG 怎么处置**（v3 重述） | ✅ 悬空工具已摘。实现本体在 `feature/rag-v261009`（已推送 origin），因此：① 保持分支分离，本地 161 MB 数据留着 ② 清理本地数据，需要时切分支重跑建库 ③ 按 §6.6 做成插件（从分支取回代码） | **① 先保持**：数据不贵、切回去即用；长期确认不要了再 ②；③ 等插件运行时可用之后 |
| **D8** | **内核基线选哪条线** | ✅ **已定：①** —— 以 `feature/slim-workbench-v261009` 为内核基线；RAG 分支的未推送提交已在 v3.1 推上 origin | 后续契约归一、插件化都在此分支推进；`main` 落后 204 个提交的合并策略另议 |
| **D7** | 版本库边界 | ✅ **已定：②** —— `.gitignore` 已放行 `mcp/**`（`*.py` / `README.md` / `*.bat`）与 `plugins/**`（代码与 manifest），并显式忽略 `plugins/**/data/`、`plugins/**/.cache/`、`__pycache__/`、`*.pyc` | 已落地（随 `cacdaad` 入库）；同类「整目录不受版本保护」不会再发生 |
| **D-E** | **随包（bundled）插件放哪**（「附属也是插件」的直接推论） | ① 打进 exe 的 `ASSET_ROOT/plugins`（只读、随版本升级）② 放 `DATA_ROOT/plugins`（用户可直接改坏）③ 两处都扫、ASSET 优先 | **③**：`bundled` 与 `optional` 的加载/注册/隔离/卸载代码路径完全相同，只有「默认开关 + 来源目录」不同（见 §6.2 的 `distribution` / `default_enabled`） |
