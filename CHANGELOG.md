# Changelog

## v261022.8 · 本地 Embedding 服务与语义索引打通

- 新增 `tools/embedding_server.py`：OpenAI 兼容的本地 Embedding 服务（`POST /v1/embeddings`、`GET /v1/models`、`GET /health`），基于 fastembed + **BAAI/bge-small-zh-v1.5**（24M 参数、512 维、中文优化、ONNX、无需 torch）。模型缓存固定在 `D:/Project/.models/fastembed`（约 91 MB，不随临时目录清理），首次启动自动下载。
- 工作台 RAG 配置为 `hybrid`（关键词 + 语义）、`http://127.0.0.1:8800/v1`、512 维；连接检查通过，语义索引构建完成：**230 份来源 / 706 个分块**（约 30 秒），页面显示「语义索引可用」。
- 检索实测：`红外暗弱目标检测方法` 返回 8 条（文献题录 + 知识条目，score 0.73–0.76）；`知识库条目怎么归类` 命中《知识-原理-知识库全局说明》（0.757）。
- 新增 `docs/LOCAL_EMBEDDING.md`：选型理由、安装启动、工作台配置字段、验证命令、常驻与换模型注意事项。

## v261022.7 · 上游前端接入说明文档

- 新增 `docs/UPSTREAM_FRONTEND_INTEGRATION.md`：逐项记录已接入的 6 个模块（甘特 / 同步 / AI 能力与 RAG / 引用补全 / 项目范围与科研界面 / Agent 系统面板）、每项的接缝改造、未接入模块及理由（文献面板已有等价实现、`v260922-*` 已改名替代、计费已插件化、无悬浮助手等）、新增的 6 个全局接缝、验证方式与后续可选任务。
- README 顶部加了指引入口。目的是让"合并后还差什么"有可追溯的答案，而不是散在提交记录里。

## v261022.6 · Agent 页接入系统面板（上游前端第 6 项）

- Agent 页右侧新增**系统面板**：顶部六个 tab「对话 / 任务 / 记忆 / 技能 / RAG / 设置」，由 `agent-system.js` 渲染进 `#agent-system-panel`；对话区包进 `#agent-chat-panel`，切 tab 时两者互斥显示（对话 tab 回到原聊天界面）。
- 「任务」显示当前会话的任务进度、待确认草稿（确认/拒绝）、运行日志与结果；「记忆」「技能」「RAG」「设置」分别复用第 3 项接入的同一套面板。
- `ERWAgentPage.refresh` 改为只刷新当前会话消息（不再整页重渲染），避免 `mount → refresh → renderAgent` 循环。
- 说明：本地对话走自己的发送链路，不创建上游的 task run，所以「任务」列表在纯聊天下为空——这是预期降级，一旦主循环走 `agent_runtime` 就会记录。
- 验证：六个 tab 渲染、点击「任务」出现面板、0 console error；`web_check`、`ui_smoke`、`kb_smoke` 通过。

## v261022.5 · 接入项目范围选择器与科研界面适配层（上游前端第 5 项）

- 新增 **`research-ui.js`**（`window.ERWResearchUI`）：项目显示名（`display_name`）、资料证据徽章（题录 / 公开摘要 / 有 PDF 全文 / 已核对原文，按正文声明与附件推断）、阅读字号（12–20px，写进缩放菜单）、`wheelScale` 滚轮缩放辅助。项目记录在首屏后预取，失败不阻塞页面。
- 新增 **`project-scope.js`**（`window.ERWProjectScope`）：可搜索、键盘可用的项目范围选择器（↑↓/Home/End 选择、Enter 确认、Esc 关闭、输入法组合保护、点外部关闭）。
- 甘特图的项目范围从「原生下拉」换回该选择器；项目名统一走显示名。未加载该模块时仍自动降级为原生下拉。
- 网络统一走 `window.erwFetch`；本地 `app.js` 的 `ERWResearchUI` 桩只在实际模块缺失时生效（先加载真实模块）。
- 验证：甘特项目选择器展开 3 个选项、搜索框可用、阅读字号控件出现在缩放菜单、0 console error；`web_check`、`web_manifest --check`、`ui_smoke`、`kb_smoke` 通过。

## v261022.4 · 编辑器接入引用补全与预览（上游前端第 4 项）

- 新增 **`document-references.js`**：编辑器里输入 `[[` 弹出引用候选（带类型/状态/项目，↑↓ 选择、Enter 插入、Esc 关闭）；`Ctrl/⌘ + Shift + K` 打开引用选择器；预览区点击引用弹出浮动预览（可返回上一跳、直接打开文档，PDF 条目提供「阅读 PDF」）；断链显示状态；中文输入法组合期间暂停补全。
- **宿主适配**：`fetch` 走 `window.erwFetch`；复用本地已有的 `ERWMarkdown.renderInto`、`ERWNav.open`、`ERWCurrentDoc`、`ERWToast`；新增 `ERWResearchUI.esc` 与 `ERWPaneZoom` 空实现（本地无面板级文本缩放，预览照常渲染）。
- 编辑器 `wireEditor()` 与预览区在渲染时自动绑定（幂等），无需改各页面的编辑流程。
- `web_check` 的原生事件白名单再补 `compositionstart/end/update`（输入法组合事件）。
- 关于 PDF：**文献阅读工作区本地面板已具备 PDF.js 阅读**（`plugins/literature-reader/web/panel.js`：本地/离线 PDF.js、按页渲染、批注与笔记）；上游的「离屏绘制保帧、左右分隔线拖动」等增强属于面板整体替换，与本地插件接缝冲突较大，本轮未移植，留作单独评估。
- 验证：真实编辑器输入 `[[知识` 弹出 20 条候选、0 console error；`web_check`、`web_manifest --check`、`ui_smoke`（20 路由）、`kb_smoke`、`plugin_check` 全过。

## v261022.3 · 设置页接入「AI 能力」与「RAG」（上游前端第 3 项）

- 设置新增 **「AI 能力」** tab：RAG 知识检索 / 记忆 / Skill 三个总开关（改动即时保存、后续工具调用生效），以及「管理技能」「配置 RAG」入口。
- 设置新增 **「RAG」** tab：可用状态（关键词检索 / 语义索引是否就绪）、接口与检索设置（模式：关键词 / 混合 / 语义，Embedding Base URL、模型、密钥、分块与索引选项、PDF 正文索引、自动更新）、连接检查与更新索引、清除向量索引、检索试用。
- **宿主适配**：`agent-system.js` / `agent-client.js` 的 `fetch` 改走 `window.erwFetch`，文档级观察改走 `ERWDom.onChildList`；本地 Agent 页结构不同，新增 `window.ERWAgentPage` / `ERWResearchUI` / `ERWFabTimeline` 三个最小适配（聊天跳转、项目名、证据徽章、悬浮时间线按空值降级），`ERWToast` 直接复用内核。
- 运行环境补装 `PyYAML`（`requirements.txt` 早已声明；此前未安装导致 `/api/agent/skills` 报「读取 YAML 需要 PyYAML」）。安装后技能接口返回 5 个技能、0 错误。
- 验证：AI 能力 tab 3 个开关 + 2 个入口正常、RAG tab 表单与「关键词检索可用」状态正常、0 console error；`web_check`、`web_manifest --check`、`ui_smoke`、`kb_smoke`、`plugin_check`、`mcp --selftest` 全过。

## v261022.2 · 设置页接入「同步」（上游前端第 2 项）

- 设置新增 **「同步」tab**（排在「服务与存储」之后）：服务器地址 + 测试连接、同步方式（不同步 / 主动 / 自动）、自动检查间隔、五类同步内容（Markdown 文档 / PDF 与附件 / 项目待办文献与热力图 / 通用设置与界面偏好 / Agent 对话）多选、保存与立即同步。
- 同时接入 sync.js 的完整状态能力：顶栏同步按钮与变化计数（不同步时隐藏）、文档列表上的 A/M/D/↓/! 变更徽章、冲突处理弹窗（使用本地 / 服务器版本、保留两份、手动合并），以及「同步状态与变化」列表。
- **接缝改造**：网络走 `window.erwFetch`；文档级 DOM 变更改走 `ERWDom.onChildList`（不再自建 MutationObserver）；宿主能力（弹窗/吐司/打开设置/应用偏好/刷新）由新增的 **`window.ERWSyncUI`** 适配层提供，复用本地 `#modal` 与 toast；`app.js` 初始化完成后派发一次 `workbench:ready`，sync.js 在此之后才贴附与轮询。
- `web_check` 的原生事件白名单补上 `pagehide` / `pageshow` / `beforeunload` / `message`——此前会把浏览器原生事件误报成「没人派发的自定义事件」。
- 验证：同步设置页渲染正常（5 个范围、状态栏、0 console error）、`/api/sync/status` 200；`web_check`、`web_manifest --check`、`ui_smoke`（20 路由）、`kb_smoke`、`mcp --selftest` 全过。

## v261022.1 · 里程碑页接入甘特图（上游前端第 1 项）

- 里程碑视图新增「甘特」tab（时间轴 / 甘特 / 列表 / 文档），接入上游 `ERWMilestoneGantt`：按项目分组，阶段条看周期、菱形看截止节点；支持全览 / 日 / 周 / 月缩放、定位今天、状态筛选（含逾期与待排期）、搜索与项目范围下拉。
- 点击阶段条/节点在右侧修改起止日期、进度与状态，写回同一份 Markdown（`start_date` / `due` / `progress`）；有未保存修改时切换视图会先确认。数据来自 `/api/milestones/plan`（不受文档列表分页限制）。
- **接缝改造**（相对上游原版）：网络请求改走 `window.erwFetch`；项目筛选去掉对未接入的 `ERWProjectScope` 的依赖，降级为原生下拉；移除对 `ERWResearchUI.projectLabel` 的引用；观察器仍是局部 `ResizeObserver`（非文档级 MutationObserver）。
- 设置 → 界面 → 里程碑默认视图新增「甘特图」。
- 验证：真实页面渲染 3 节点 / 1 已完成 / 0 逾期、0 console error；`web_check`、`web_manifest --check` 通过。

## v261022.0 · 合并上游 codex/agent-harness-cortex-memory（22 提交）

- 合并上游分支的功能线：Agent harness（`agent_context` / `agent_mcp` / `agent_memory` / `agent_rag` / `agent_research` / `agent_runtime` / `agent_skills` / `evidence`）、CortexDB 风格记忆、统一文献工作区与稳定 PDF 绘制（离屏绘制、PDF.js 随客户端）、图谱范围全览与里程碑甘特图（`app/milestones.py`）、同步引擎（`sync_engine` / `sync_service`）、技能包（`app/skills/`）、用量文件竞争修复、SSE 终态与断线恢复。
- **冲突处理原则**：以本地 v261021.x 主线（插件化 / 契约 / CI / UI 规范）为基底，上游核心文件只取新增接线、不覆盖本地重构；上游新增模块与新增文件原样并入。3 个本地已删除的 `web/v260922-*.js` 保持删除（本地已迁移到新模块）。
- 涉及 27 个冲突文件、约 60 个冲突块，逐块处理；文档（`.gitignore` / `VERSION` / `README` / `docs/WINDOWS.md`）按并集合并。
- **索引迁移 0004**：`activity_seen`（按活动 id 去重）与 `activity_legacy`（旧日志指纹计数）。这两张表原先只在上游的建表语句里，本地迁移清单缺失，合并后同步/留版路径会报 `no such table`——现已补进 DDL 与迁移链，本地库迁到 v5。
- **上游前端 7 个模块本轮未接入**：`sync.js` / `agent-system.js` / `agent-client.js` / `milestone-gantt.js` / `document-references.js` / `project-scope.js` / `research-ui.js`（及对应 7 个 CSS）——它们自建 `api()`、文档级 `MutationObserver`，且监听的事件在本地没有派发方，直接加载会违反 P14 接缝（`web_check` 报 7 项）。已从工作树移除；`app/` 侧的新模块（agent_* / sync_engine / milestones / skills）与 `server.py` 路由保留，接线时按 `ERW*` 接缝改造后再引入。
- 验证：6 个静态闸门（`kb_smoke` / `web_check` / `web_manifest --check` / `plugin_check --assert-core-only` / `core.plugins verify` / `mcp.server --selftest`）全过；`run_tests.py --fast --no-server` **15/15**（121 断言）；重启后 `/api/health` 200、`ui_smoke` **20 个路由全部可渲染**、0 console error。

## v261022.9 · 合并上游 codex 最新提交（de31add pdf updata）

- 合入上游 `codex/agent-harness-cortex-memory` 的 `de31add`：里程碑排期修订保护（`expected_revision` / `store.RevisionConflict`）、待办写入前统一校验（`todos.validate_payload`）、`status_class` 归一（完成/已完成同义）、Agent 排期工具（`kb_read` 返回 revision 与排期字段、`kb_create_entry` / `kb_update_entry` 支持 start_date/progress/status/projects 并生成字段级草稿变更）、引用导出元数据优先与缺失清单。
- **冲突处理原则同 v261022.0**：以本地插件化 / 契约 / 接缝主线为基底，上游核心文件只取新增能力、不覆盖本地重构。
  - `app/perf_index_runtime.update_doc` 保留本地「唯一写入路径」委派（`store.update_doc`），上游的 `expected_revision` 校验移到委派之前（写入锁内比较），因此仍走契约校验、来源记录与分叉留版。
  - `app/todos.py` 取上游 `validate_payload`，同时保留本地「逾期需确认」（`OverdueError`）与 `completed_at` 维护；上游会把 `due` 收窄为纯日期，本地保留「日期 + 可选时分」口径，校验函数接受 `YYYY-MM-DD` 与 `YYYY-MM-DD HH:MM`。
  - `server.py` 同时保留逾期 409 与修订冲突 409（两者错误码不同）。
  - `web/app.js` 保存里程碑时带上 `expected_revision`，并保留本地的 `ERWDocReferences.invalidate()`。
  - `web/milestone-gantt.js` 取上游的冲突合并 UI 与 `status_class`，网络仍走 `window.erwFetch`。
  - `plugins/floating-assist/web/panel.js` 不做改动：本地悬浮助手的草稿区已是 v261008b 的紧凑行（标题 + 行内确认/拒绝），没有上游的 `data-draft-preview` 按钮，上游对 `web/v260930-floating-agent.js` 的 `draftPreview` 改动无落点。`ERWAgentClient.draftPreview` 已随 `web/agent-client.js` 引入，消费方是执行记录面板 `web/agent-system.js`。
  - `web/literature.js` 保持删除（本地已迁移到 `plugins/literature-reader`），上游对该文件的改动（导出状态行）不迁移。
  - `web/v260922-performance.js` 本地已拆分为 `web/perf-and-fetch-seam.js` 等文件，上游对该文件的改动不迁移。
- **契约补齐**：`start_date` / `progress` 此前不在 `core/contracts/kinds.py` 的字段序与 `UPDATE_FIELDS` 里，`store.update_doc` 会静默丢弃这两个字段——上游的排期编辑在本地会「保存成功但没生效」。现已补进 `FRONTMATTER_ORDER` 与 `UPDATE_FIELDS`。
- **与上游语义对齐的两处放宽**（均为上游 de31add 明确设计，本地契约原先会拒写）：
  - `core/contracts/validate.py` 的 F002 对 `milestone` 降为 warn：`store.milestone_status_class` 把「已完成 / 阻塞」当作「完成 / 受阻」的别名，未知标签也照常显示为「计划中」，排期因此允许自定义状态；其它类型的越界 status 仍是 error。
  - `app/agent_tools.execute` 的中央 schema 校验把数组参数的 `enum` 逐项比较（此前整表比较，`kind_marks=[]` 会被判成越界）；标量参数的语义不变。
- `store.update_doc` 新增可选 `now` 参数：索引层在写入锁内取一次时间再传入，使同一次写入的文件时间戳与返回值一致（上游「同秒写入仍按 revision 区分」的回归用例依赖这一点）。
- 新增上游验收用例 `tools/test_functional_regressions.py` / `tools/test_planning_regressions.py`（含真实 HTTP、双窗口并发、合成模型 SSE、草稿审批回归），浏览器段由 `ERW_FUNCTIONAL_UI` / `ERW_PLANNING_UI` 开关控制。

<details>
<summary>上游 CHANGELOG 原文（合并前）</summary>

## v261021.3 · 引用导出、计划并发保护与 Agent 排期

- BibTeX 导出采用元数据优先规则，兼容旧正文引用、尊重显式清空，显示导出数量和缺失清单；全部缺失时不下载空文件。
- 概览正确显示项目待完成节点；统一“完成 / 已完成”等里程碑状态分类。待办创建与更新统一校验标题、日期、优先级和完成状态，拒绝无效输入且保留原记录。
- 甘特图和里程碑文档保存增加包含元数据与正文的修订检查；冲突保留输入，支持比较当前值、合并后重试。甘特图仅发送改动字段，移除不适用的文档分页。
- Agent 建档、读取和更新工具支持结构化起止日期、进度、状态与项目；继续使用草稿审批，预览字段旧值与新值。旧草稿不能覆盖新计划；未提供日期时保留待排期。
- 修正验收脚本并新增真实 HTTP、双窗口并发、合成模型 HTTP/SSE 与草稿审批回归；196 项 Python 测试、自检、完整 Agent / 工作台 UI 及计划专项通过。

## v261021.2 · 统一文献工作区与稳定 PDF 绘制

- PDF 改为离屏绘制完成后替换，缩放和 DPI 更新保留上一帧；取消过时任务，回收缩放后遗留的离屏页，修复初次进入与缩放时的黑屏闪烁。随客户端提供 PDF.js 及 worker，支持离线阅读。
- 文献统一进入 PDF 工作区，元数据集中在“信息”、原 Markdown 正文集中在“笔记”，保留原文档 ID、引用和正文。旧的无 PDF 条目保留为待补充，可原位上传绑定，不重复创建文献。
- 文献卡片压缩为题名与简要信息，增加 PDF 状态筛选和分页。左右分隔线支持鼠标拖动、键盘调整、双击复原及宽度记忆，小屏资料栏改为浮层。
- 笔记操作固定在侧栏底部，保存提供进度与失败反馈；草稿跨标签保留，离开时可保存 / 放弃 / 取消，加入修订检查防止覆盖其他位置的更新。
- BibTeX 作为独立元数据保存；旧正文中的 BibTeX 在首次写入时兼容保留，替换阅读笔记不会再丢失引用信息，修改引用信息也不会向笔记插入代码块。
- AI 整理明确使用当前笔记草稿，迟到结果不会覆盖另一篇文献；结果和批注先放入可编辑草稿，再由用户保存。文献笔记支持 Markdown 预览、本地引用及插图。

## v261021.1 · 图谱范围全览与里程碑甘特图

- 项目范围切换不再自动选择最近的笔记；清除旧焦点、预览与相机动画，自动适配当前范围的所有已加载节点，并保留相关标签。范围全览保留所选项目，概况数量随范围更新。
- 项目范围改为可搜索、支持键盘的选择器，固定宽度省略长名称，候选列表保留全名，兼容明暗主题。
- 里程碑新增甘特图：按项目分组、阶段条与截止节点、明确进度、状态与逾期提示，支持筛选、折叠、日周月缩放、全览与定位今天；名称列和日期表头固定。
- 计划侧栏可修改起止日期、进度和状态，与原里程碑 Markdown 编辑器共享数据；未排期和无效旧日期仍保留可见，保存失败保留输入，未保存离开时确认。
- 新增完整计划快照接口，甘特图不受文档列表的 200 条分页限制；使用生成的 27 条界面样例和 205 条真实临时文档进行回归，无模型或 Embedding 调用。

## v261019.1 · 用量文件竞争与科研热力图同步

- 修复用量页并行加载时首次初始化单价表的 Windows 文件占用错误；串行处理单价表读写，使用独立临时文件、原子替换和短暂占用重试，保留已有单价与账本。
- 将科研活动纳入默认“记录”同步范围，按活动 ID 合并两端历史、保留原始日期与权重；为旧日志生成稳定标识，避免共同历史和反复同步导致重复累计。
- 热力图索引接收后更新，支持导入去重、索引重建与历史计数恢复；同步协议升级到 2，客户端和服务器均需更新。
- 新增并发读写、真实 Windows 句柄、三设备合并、旧日志重叠、后台导入及真实服务热力图一致性回归。

## 未发布 · Agent 系统与 CortexDB 风格记忆

- 修复 SSE 终态先于 done 事件写入导致的提前断流；增加终态结果兜底、事件游标及同一任务断线恢复，兼容 CRLF、多行 data 和末帧无空行，不重复提交任务。
- 主聊天补齐草稿查看、确认、拒绝和继续任务；主页面与悬浮助手共享会话、流式正文及审批状态，修复历史已完成任务继续按钮过期问题。
- 输入框下方与发送按钮同行提供 RAG / 记忆 / Skill 三个独立总开关，两处对话及设置实时同步；技能仍在“技能”页按项启用，模型选项默认折叠。
- 新增可填写的 Embedding 接口、模型、密钥和维数配置，支持连接测试、Markdown / 可选分页 PDF 向量索引、增量复用、取消和检索试用；支持关键词、语义与 RRF 混合检索，索引异常明确提示，失败或取消保留旧索引。
- 主 Agent 回复选区“问 AI”留在当前对话，并新增多段“引用”、预览和移除；引用随消息持久化。不再因相同会话/草稿状态的重复刷新打断悬浮窗选区。
- 修复多轮工具调用清空中间回答、最终只剩“任务已完成”：悬浮助手、Agent 聊天与任务结果按轮展示正文，已有会话从工具证据恢复中间回答，无需重新调用模型；中途失败保留已生成内容，阻止延迟流式绘制覆盖错误提示。
- Agent 会话列表遇到临时断线自动重试，持续失败时保留功能界面并提供连接说明与重试入口，恢复连接时保留输入草稿。
- Agent 功能直接整合到原聊天页，共用会话和输入框；修复成功回复后 `qa is not defined` 被误报为请求失败，以及 API 配置控件异步重复插入。

- 增加标准 Skill 发现与渐进加载、三个内置科研技能、任务中心和运行设置。
- 增加 SQLite 会话/记忆/关系/事件/工具执行记录，来源召回、TTL、替代关系、可选向量融合、旧会话幂等迁移及一致性备份。
- 对话改为后台执行，支持暂停、恢复、失败重试、断线继续、审批检查点、完整工具证据与上下文预算。
- 增加分页 PDF/研究文件读取、公开文献检索、Docker 隔离 Python、HTTP MCP；补充写入版本冲突检测、修订回退和重复确认保护。
- 使用与边界见 `docs/AGENT_SYSTEM.md`；新增 Agent 专项回归与桌面/移动浏览器验收。

</details>

## v261021.9 · CI 纯逻辑用例：两个夹具不再依赖真实 Workspace

- 用 v261021.7 加的注解定位到最后两处红点：
  - `test_doctor_bloat.py` 直接 `shutil.copy2(Workspace/System/Cache/index.sqlite, …)`，干净检出没有这个文件 → `FileNotFoundError`。现在无真实库时改用 `app.perf_index_db._init_db()` 建一个「当前结构」的空库再制造膨胀，测的仍是「doctor 能识别膨胀」，不依赖用户数据。
  - `test_migrations.py` 第 8 组「真实库只读 dry-run」在库不存在时断言失败；改为打印 SKIP（与第 8 组原有的「库被占用」分支同一口径）。
- 验证：干净副本（无 `Workspace/`、无 `config/`、无 `.scratch/`）`run_tests.py --fast --no-server` **15/15 通过**（121 断言）；本地有真实库时两个用例仍 PASS（膨胀 49% / 只读 dry-run current=4）。

## v261021.8 · 设置页两栏：按内容收缩，不强行填满

- 设置页左右两栏从 `align-items: stretch` 改为 `start`：内容少时卡片高度就随内容收缩（不再被拉到与另一栏同高、在卡片内留大片空白），内容多时仍由 `max-height` 封顶在卡片内部滚动。典型对比：设置导航栏 414px 时不再被撑到 798px；「基础」tab 的右栏卡片 192px 就是 192px。
- `docs/UI_DESIGN.md` 同步：§4.2 与 §5.5 改为"各自按内容收缩"，P4「并列元素等高」注明设置页两栏是例外。
- 验证：知识条目 tab 左栏 414 / 右栏 798（内容 1048 封顶滚动）、基础 tab 右栏 192（内容 190）、`body.scrollHeight == innerHeight`、滚动仍只发生在内容卡片内；`web_check`、`web_manifest --check`、`kb_smoke`、`ui_smoke` 全部通过。

## v261021.7 · CI：失败用例输出 GitHub 注解

- `tools/run_tests.py` 在 `GITHUB_ACTIONS` 环境下，把每个失败用例的尾部 8 行以 `::error title=…::` 输出。此前 job 日志需要登录才能看，Annotations 区块是公开的——失败原因直接进注解，排查不用再翻日志。
- 本地运行不受影响（该分支只在 CI 生效）。

## v261021.6 · CI：Windows 静态闸门设置 UTF-8 输出

- `static-gates` 的 Windows 任务在 job 级加 `PYTHONIOENCODING: utf-8`：Windows runner 默认 stdout 编码是 cp1252，`kb_smoke` 第 7 组会打印 `⚗` 等符号，编码失败直接 `UnicodeEncodeError` 让整步 red（ubuntu 同一工作流已绿，差异只在编码）。
- 全工作流统一该变量（`logic-tests` 原本就有），避免以后新增脚本打印中文符号时再踩。

## v261021.5 · 修复 CI：干净检出可跑

- **`kb_smoke` 在无 Workspace 时降级而不是直接失败**：CI 的 checkout 没有 `Workspace/`，原脚本在“索引存在”处直接 `return 1`，连带 `plugin_check --assert-core-only` 也红。现在 4~6 组（索引/通用基础/工具视图，依赖真实数据）打印 SKIP，1/2/3/7 组（关系解析、命名、归属归一化、写入期校验）照常执行；“store 更新路径”一条在没有条目时也改判 SKIP，不再用写死的条目 id。
- **两个依赖工作台服务的用例在无服务时 SKIP**：`test_plugin_assets`（路径穿越）与 `test_reader_plugin_tools`（文献插件）是常驻夹具，需要 `tools/run_tests.py` 起临时服务；CI 用 `--fast --no-server` 时它们连 8799 直接抛 `ConnectionRefused`。现在探测不到服务就打印 SKIP 并以 0 退出，完整档行为不变。
- **工具面断言改为读插件清单**：`test_mcp_plugin_split` 写死“内核 + 3”，而 v261020.6 给 `version-manager` 加了 `auto_merge_versions`（`mcp_tools` 3→4），实际工具面 34 = 内核 30 + 4，断言过期。现在从 `plugin.json` 的 `mcp_tools` 读数量，插件增删工具不再让夹具误红。
- 验证：把 HEAD 用 `git archive` 导出到仓库外的独立目录（无 `.git`、无 `Workspace`、无 `config/`）复现 CI：`kb_smoke` / `web_check` / `web_manifest --check` / `plugin_check --assert-core-only` / `core.plugins verify` / `mcp.server --selftest` 全部 0 退出；`run_tests.py --fast --no-server` 连续两轮 15/15 通过（121/121 断言）。

## v261021.4 · UI 设计说明文档 + compact 侧栏内边距收口

- 新增 `docs/UI_DESIGN.md`：把当前实际生效的界面规则整理成可检索的一篇——设计原则、色彩三层变量（`--sc-*` 画布 / `--lux-*` 主题 / 旧变量兼容映射）、模块身份色与暗色值、字体字号层级、圆角阴影动效、布局骨架（可拖拽侧栏 52–200px 三档模式、顶栏、主内容、桌面外壳）、滚动规范（侧栏未铺满不滚、设置页两栏各自滚动）、组件规格（按钮/表单/卡片/列表/徽章/弹窗/Toast）、主题与密度与缩放、响应式断点、插件 UI 接缝、文件加载顺序、改界面验收清单与常见问题。README 顶部加了指引入口。
- 一并修掉 `data-sidebar-mode="compact"` 下 `.sidebar-nav` 残留的 54px 底部内边距（与 v261021.3 同类问题：内容未铺满时会产生可滚区域），改为 12px，与 full 模式一致。
- 验证：`web_check`、`web_manifest --check`、`kb_smoke`、`ui_smoke`（20 路由）全部通过；文档内数值均取自代码实测（侧栏 52–200 / 默认 168、顶栏 64 与桌面 58、设置页上限 102 与 `--vh-px - 96`、断点 1101/1100/820）。

## v261021.3 · 侧栏：内容未铺满时不再可滚

- 左栏导航（`#sidebar-nav`）底部内边距从 56/64/60px 收到 **12px**。真实生效的是 `v261014-linear-luxe.css` 里 `padding:9px 8px 60px!important` 那条（`styles.css` 与 `layout-compact.css` 的 56/64px 一直被它覆盖）；60px 的底部内边距被计入 `scrollHeight`，于是内容只到 828px、容器 886px 时仍能滚 27px——滚轮在侧栏上会被这 27px 截走，而不是滚页面。
- 现在：内容未铺满时 `scrollHeight == clientHeight`、`maxScroll = 0`，滚轮直接作用于页面；窗口变矮、导航真正溢出时照常滚动，末尾保留 12px 留白 + 组间距，不贴 footer。
- 验证：视口 1113 / 1000 高时侧栏 `maxScroll = 0`，640 高时 `maxScroll = 339`（正常滚动）；`web_check`、`web_manifest --check`、`kb_smoke`、`ui_smoke`（20 路由）全部通过。

## v261021.2 · 设置页滚动：外壳固定，只滚内容区

- 设置页（含插件自登记的设置 tab）从**整页滚动**改为**内容区内部滚动**：滚动时顶栏、侧栏、左栏标签零位移，滚动条只出现在右栏卡片内。此前是 body 滚动——滚动条贴窗口右缘、拖动时整页位移；桌面模式又被 `desktop.css` 顶成 `height:calc(--vh-px - 20px)`，左栏比视口还高、滚动时错位。
- 两栏各自封顶 `calc(100vh - 102px)`（桌面模式 `calc(--vh-px - 96px)`）：内容少时卡片自然高，内容多时封顶并在内部滚动，同时保持两栏等高；`≤820px` 窄屏恢复整页滚动。
- 滚动体验：10px 细滚动条 + 半透明圆角滑块（WebKit 与 Firefox 双口径）；`overscroll-behavior:contain` 阻断滚到边界后的链式整页滚动；`scrollbar-gutter:stable` 避免滚动条出现/消失时内容横向跳动；切换设置 tab 时内容区回到顶部。
- 验证：`body.scrollHeight == innerHeight`（页面不再整体滚动）、`#settings-panel` scrollH 1048 / clientH 796，滚动前后 topbar / sidebar / settings-nav 的 `top` 完全不变，切 tab 后 `scrollTop=0`，0 console error；`web_check`、`web_manifest --check`、`kb_smoke`、`ui_smoke`（20 路由）全部通过。

## v261021.1 · Agent 接入 OpenCode 免费档（本地 CLI 桥）

- 新增 `tools/opencode_cli_bridge.py`：把 OpenAI Chat Completions 请求（含 SSE 流式）摊平成一段文本交给本机 `opencode run --format json`，再把 `text` 事件聚合为回答、把 `step_finish.tokens` 回填 `usage`；`GET /v1/models`、`/v1/health` 供设置页「测试连接」使用。默认监听 `127.0.0.1:9357`，CLI 路径优先取 npm 包内 `opencode.exe`（`.cmd` 经 `cmd /c` 中转会把中文提示词打成乱码，已实测踩过）。
- 新增 Agent 档案 `profile-opencode-free-cli`（`http://127.0.0.1:9357/v1` · `deepseek-v4.1-flash-free`），并在 `prices.json` 的 `plans` 里登记为 `mode=free`。该模型只在 Zen 通用网关 `/zen/v1`，Go 网关 `/zen/go/v1` 没有它。
- 为什么必须走 CLI：上游对免费档做客户端识别，非 OpenCode 客户端直连一律 `403 FreeTierError`。实测系统提示词、UA、`Authorization: Bearer public` 都不构成判别依据，**请求里的 opencode 工具集**才是（`bash` 单独不够，`bash+read` 的原版 schema 即可放行）。因此不伪造签名直连，而是交给官方 CLI 出网。
- 安全边界：桥为每次调用生成 `config/opencode-cli-bridge.json`（`bash/edit/write/webfetch/websearch` 全部 `deny`），并在独立临时目录运行，模型无法在工作区执行命令。
- 能力边界：只做纯文本问答——工作台的原生 function calling 不下发，工具循环退化为普通回答；免费档限速紧，429 原样透出为 HTTP 502/429 并显示原文。
- 验证：桥非流式与 SSE 双路径实测；`GET /api/agent/test` 返回 `连接成功`；`POST /api/agent/send` 端到端得到 `round → delta → done`，正文与 `usage` 正常。
- **设置页补上「实验」类型**：内置类型从 6 类恢复为契约里的 7 类，默认顺序 `idea → journal → note → experiment → milestone → summary → literature`（与侧栏一致，实验在里程碑之前）。此前 `knowledge_type_registry()` 的 `default_order` 漏了 `experiment`，导致设置页看不到实验、无法调顺序/隐藏/改模板；`app/config.py`、`app/store.py`、`web/app.js` 三处同时补齐，并对旧配置里缺 `experiment` 的 `order` 按**相对位置插入**而不是一律追加到末尾，避免它被排到文献之后。
- **版本页入口移到「系统」**：`version-manager` 的面板注册从 `group:'research'` / `before:'graph'` 改为 `group:'system'` / `before:'settings'`，侧栏显示为「系统 → 版本 → 设置」；插件 README、`plugin.json` 的 `where` 与手册 02 同步。版本是全局维护动作，与具体研究条目并列在「研究 · 知识」组里不合语义。
- 验证：重启主实例后 `/api/knowledge-types` 返回 7 类且 `experiment` 在 `note` 与 `milestone` 之间；真浏览器走查侧栏 `system` 组为「使用手册 / 用量 / 版本 / 设置」、设置页知识条目 7 行顺序正确、分类标记 3/24 与 7 个内置模板恢复（`/api/knowledge-marks` 500 已修）、0 console error。

## v261020.7 · 版本页：批量清理快照

- 版本页左侧新增「批量清理」卡片：一次扫描所有版本族，把变体分成**内容一致**（与基条正文相同，通常是外部写入只改来源/元数据）与**有改动**（写入前的旧内容）两类，支持「归档内容一致的 N 个」和「归档全部 N 个…」；归档走原有 `archive_variants`，移到 `System/Versions/<基条>/archived/`，可随时取回，基条内容不变。
- 版本族列表每行标出「有改动 / 内容一致」，一眼看出哪些族需要先对照再清；合并/自动确认里的「合并后归档」改为**默认勾选**，减少处理后又堆一批快照。
- 新增路由 `GET /cleanup`、`POST /cleanup-archive`（插件 1.2.0）；`cleanup-archive` 支持 `mode=same|changed|all`，单族失败不影响其余并返回 `errors`。
- 验证：真浏览器走查（23 个快照 / 内容一致 1 · 有改动 22、列表 23 个标记、确认框可取消、0 console error）；`plugin_check`、`web_check`、`ui_smoke`、`kb_smoke` 全部通过。后端与插件改动需重启工作台生效。

## v261020.6 · 版本页：Agent 自动确认合并

- 版本族详情 ② 区新增「✦ Agent 自动确认」：内核把**有改动的小节**分批（3 节/批、每段截 350 字）交给设置里已配置的模型逐节选来源，返回「采用哪版 / 保留基准」与一句理由；批次并发执行、每批最多重试 3 次。建议会填进每节的来源选择器并打 `Agent` 标记，横幅汇总「采用 N 处 / 保留基准 M 处」，逐节理由折叠展示；确认后仍点原来的「应用」，勾「直接应用」则一步写回。
- 模型不可用（未启用 / 没填 Key / 网关异常）或某批始终没有返回结果时，自动回退「最近更新优先」规则，横幅注明 `rule-fallback` 或回退段数；外部 Agent / CLI 可显式传 `strategy="rule"` 走规则，不产生模型调用。
- 新增内核模块 `app/merge_ai.py` 与门面 `core_api.auto_merge_variants()`（`apply=False` 只给建议、`apply=True` 写回；合并仍走 `app/versions.merge_family` 与 `doc_merge` 活动记录）；插件新增 `POST /auto-merge` 路由、写工具 `auto_merge_versions`（走内核草稿闸门）与 `llm:use` 权限（manifest 校验同步支持）。
- 验证：真浏览器走查（打开版本族 → 点自动确认 → 单次运行得到 6 处采用 / 6 处保留基准，横幅、理由折叠与 `Agent` 标记正常，0 console error）；`plugin_check`、`web_check`、`kb_smoke`、`ui_smoke`、`mcp.server --selftest` 全部通过；`doctor` 未新增问题。后端与插件改动需重启工作台生效。

## v261020.5 · 分类标记：内置模板一键添加 + 自定义图案

- 设置 → 知识条目 → 分类标记：保留默认 3 个（知识 / 方法 / 实验），新增「内置模板」区——归类 / 问题 / 思路 / 架构 / 数据 / 模型 / 原理 共 7 个模板卡片（含图案、颜色与用途说明），点卡片即添加、支持「全部添加」；上限 24 个，达到上限后按钮禁用并提示。
- 自定义标记改为弹窗：名称、颜色与**分组图案面板**（几何 / 科研 / 符号 / 标记 4 组、共 64 个图案）+ 实时预览；仍支持任意符号 / emoji 输入。条目编辑器里的「＋ 自定义」复用同一套表单。
- 弹窗排版：分类名称 / 颜色 / 预览改为等宽三列（控件统一 34px），颜色改为自绘色块 + 十六进制值选择器，预览收进虚线框；修掉相邻字段的说明文字把网格行拉高、导致输入框与色块错位 15px 的问题。1440 / 1100 / 820px 量测均无横向溢出，同一行控件对齐。
- 条目信息栏的「收起 / 展开」按钮原先贴卡片右上圆角（与圆角边线仅约 8px，悬停还会上浮 1px），窄内边距或覆盖式滚动条下会压到边线；现在 `.meta-head` 右侧留 12px，并取消该按钮的 hover 上浮，与圆角/滚动条保持 20px 以上间距。
- **修复既有缺陷**：此前在设置页新建的自定义标记（`mark_*`）能存进配置，但写入条目时会被 `F003` 拒绝，等于不可用。现在 `core/contracts/validate.py` 接受调用方传入的 `allowed_marks`，`app/store.py` 把 `config/app.json` 里 `classification_marks` 的 id 一并放行；`core/doctor.py` 同步读取自定义标记，不再误报越界；Agent 工具与 MCP `kb_list_entries(mark=…)` 的 enum 也随配置动态刷新。
- 新增 `GET /api/knowledge-marks`（内置模板 / 默认集合 / 上限）；`core/contracts/kinds.py` 为 10 个内置标记补上颜色与用途提示，新增 `MARK_LIMIT = 24` 与 `MARK_DEFAULT_IDS`。
- 验证：`kb_smoke` 新增「自定义标记未放行被拒 / 放行后合法」用例；真浏览器走查（7 个模板卡片、4 组 64 个图案、添加后 `4/24` 且 `ERWContract.marks()` 同步、0 console error），配置已还原为默认 3 个；`web_check`、`web_manifest --check`、`doctor` 未新增问题。后端改动需重启工作台生效。

## v261020.4 · 结构总览与 README 对齐实测数据

- `docs/OVERVIEW.md` 按 2026-10-20 实测刷新：文档版本 v261020.4、**251 条目**（228 主条目 + 23 版本快照）、**1983 关系边**、5 项目、1 待办、12 插件；目录树的文件行数与模块数（app 27 模块、tools 27 个脚本）、`/api` 分支（61）、MCP 工具（30 = `kb_*` 15 + `ws_*`/`todo_*`/导出 15）全部同步现状。
- 修正两处能力归属：科研 Agent 的**内核内置工具是 4 个**（版本族 3 个工具由 `version-manager` 插件登记，停用则不可用）；**浏览器可导航页面 19 个**（内核 14 + 启用插件 5：专注、日历、资讯、用量统计、版本）。补齐 `version-manager` 条目、literature-reader v2.0.1、索引 schema v4、`rag/` 现状与 `config/external-access.json`。
- `README.md`：当前版本对齐 `VERSION`（v261020.4），插件清单 11 → 12 并补 `version-manager` 行。
- 健康度按实测记录：`core.doctor` **error 1 / warn 4**——error 为 2 条 journal 标题超长，待用 `kb_rename_entry` 改名。
- 本版一并提交此前未入库的 v261019–v261020.3 改动（待办行内编辑与完成时间、日历入口、手册扩写与截图、条目卡片元信息两行化）。

## v261020.3 · 条目卡片元信息改为「项目名一行 + 标签/日期一行」

- 条目卡片（笔记 / 日志 / 文献 / 里程碑等列表）的元信息分两行：**项目名独占一行**（长名按整行宽度省略，悬停看全名），**标签 / 状态 / 日期另起一行**紧跟其后。
- 起因：先尝试把标签与日期压到项目名同一行，窄列表下项目名被挤成「红外-…」，按反馈改回两行、保证项目名完整可读。
- 实现：`.doc-compact-meta` 保持 `flex-wrap`；项目名 `flex:1 1 100%` 独占行，标签/状态/日期 `flex:0 0 auto` 自动落到第二行。`v261015-usability.css` 版本参数更新为 `261020-meta2`。
- 同步重拍 `notes-list.png`、`literature.png`。
- 验证：DOM 量测 notes/journals/literature × 1440/1280/1100px，项目名宽度 = 元信息行宽、标签/日期均在其下一行且不溢出卡片；`web_check`、`web_manifest --check`、手册用例通过。

## v261020.2 · 使用手册扩写与截图更新

- 第六章改名「项目、待办、日历与里程碑」并大幅扩写：待办**新增**（截止日期 + 时间、时间留空=当天 23:59）、**行内编辑**（五项字段、Enter/Esc、只改一项不清空其余）、**完成时间限制**（逾期二次确认、服务端 409、`completed_at` 与「完成于」展示、恢复即清空、逾期标红）、排序与清理；新增「日历」（核心工作入口、月历/四段清单/顶栏角标/近期窗口/数据来源/停用影响）。
- 新增第八章「插件：使用与开发」：插件模型与零插件约束、设置页卡片的每一块、启停/安装/更新/卸载与生效时机、权限与写知识库授权、12 个内置插件一览、插件页面出现的位置与排障；开发侧给出目录结构、三步上手、`plugin.json` 字段、`register(ctx)` 能力表、前端 `ERW*` 接缝表、最小示例、七条红线、验证/打包/安装与常见错误。
- 截图**全部重拍**（1x 采集，统一 900px 宽；笔记列表/编辑器与文献页按 860/300px 口径）：`overview`、`todos`、新增 `todos-edit`、`calendar`、`plugins`、`notes-list`、`doc-editor`、`global-search`、`literature`、`lit-detail`、`agent`、`agent-ref`、`milestones`、`settings-general`、`settings-llm`、`settings-service`。其中 `overview`/`settings-general` 反映新的侧栏（项目/日历）与设置 tab（插件/外部接入/AI 助手人设），`agent-ref` 带检索结果。
- 同步：手册 README 目录与范围说明、第一章侧栏分组（含日历与插件入口）、第七章「插件」行链接到第八章。
- 验证：`tests/docs/test_manual.py` **31/31**；真实实例只读走查目录 9 章、06/08 的图片真实解码、代码块 8 块、0 console error。

## v261020.1 · 日历插件入口移到「核心工作」并改名

- `plugins/milestone-calendar`：侧栏入口从「研究 · 知识 → 日历提醒」移到「**核心工作** → 日历」（排在待办之后、Agent 之前）；名称统一为「日历」（导航、页面标题、页内标题、插件清单与预览文案同步）。
- 顶栏常驻角标不变（逾期/今日），点角标仍跳到该页；插件版本 1.0.0 → 1.0.1。
- 验证：真实实例只读走查——核心工作顺序 `概览/项目/待办/专注/日历/Agent/资讯`，研究组不再有「日历提醒」，页面标题为「日历」，角标仍在，0 console error；插件隔离体检通过。

## v261019.1 · 待办可编辑与完成时间限制

- 待办页新增**行内编辑**：每行「编辑」就地展开表单，可改标题、截止**日期 + 时间**、所属项目、优先级（Enter 保存 / Esc 取消，不弹窗）；新增表单同步多一个时间输入。
- **完成时间限制**：截止时间精确到分（`YYYY-MM-DD HH:MM`；只填日期按当天 23:59）；过了截止点仍可完成，但要**二次确认**——前端对话框确认后带 `force=true` 重试，服务端对未确认的逾期待办返回 **409 `requires_confirm`** 拦截。完成时写入实际完成时间 `completed_at`（恢复待办即清空），列表显示「完成于 …」，逾期条目的时间与标题标红。
- 索引：`todos_index` 补 `completed_at` 列（迁移 `0003`，索引版本 3 → 4，可回滚）；`/api/todos`、`core_api.todos()`、MCP `todo_list` 一并返回 `completed_at` 与派生的 `overdue`。
- MCP：`todo_create` / `todo_update` 的 `due` 支持到分；`todo_update` 新增 `force`（逾期完成的显式确认），逾期未确认时返回可读失败提示。
- 验证：迁移框架 `tests/kernel/test_migrations.py` 全部通过（含 dry-run / apply / rollback / 幂等 / 版本护栏）；隔离工作台真浏览器验收 **9/9**（行渲染、时间到分、逾期标记、行内编辑保存、逾期二次确认、完成时间展示、无待办相关 console error）；DOM 几何量测 1440/1024/390px 行与编辑表单均无横向溢出；`web_check`、`web_manifest --check`、`tools/test_bulk_delete.py` 通过。改动尚未在运行中的桌面版重启，需重启工作台（或重建 EXE）后生效。

## 2026-10-19 · 相对 UI V3 的新增功能与合并内容复核

- 按代码事实复核 `97932f3..2245726`：V3 已是当前 HEAD 的祖先，合并完成且 V3 之后未再前进；104 个提交、255 个非 vendor 文件。
- 整理两张总表：我们相对 V3 新增的能力（契约单源、插件平台与 12 插件、前端装配接缝、来源与版本追踪、外部接入授权、MCP 服务、验证设施、内置手册、桌面运行时），以及 V3 35 个文件的存活状态（15 个逐字节一致、16 个已适配、4 个迁移删除）。
- 确认草稿接口、`guardEditor` 未保存保护与原生后台计时桥接均已落地；列出计费/资讯/天气旧 API 迁移与窄屏选择器回归等差异点。详见 `docs/BRANCH_COMPARISON_UI_V3_20261016.md` 第 9 节。本次仅复核与文档，未修改应用代码。

## v261016.9 · 修复刷新菜单按钮

- 恢复远端 UI V3 的单图标刷新按钮，移除旧版文字和未绑定操作的下拉箭头，修复 32px 按钮中的文字换行溢出；保留配置与索引重新加载、快速重启两项操作和键盘交互。
- 验证：390 / 768 / 1100 / 1440px 窗口在明暗主题下均无图标溢出，点击、Enter、方向键展开、Escape 和外部点击关闭正常；前端静态体检、19 个路由真浏览器走查及知识库只读冒烟通过。

## v261016.8 · run.bat 端口冲突处理

- 按用户要求停止生成 EXE，清理已生成的 EXE、发布 ZIP、随包运行库、构建环境和打包专用临时文件；保留源码、配置和 `Workspace/` 用户数据，浏览器版继续通过 `run.bat` 启动。
- `run.bat` 启动前检查配置端口：若已有同一工作区服务，则直接复用并打开现有地址；若端口被其他程序占用，则自动选择空闲端口，不再显示未处理的 `WinError 10048`。
- 只读比较健康接口返回的索引路径，不结束或接管已有进程；正常退出的 `run.bat` 不再无条件停在 `pause`。
- 验证：已运行的工作台返回 `/api/health` 版本 `v261016.7`、索引指向当前 `Workspace`，端口复用单测 4/4 通过；已有服务进程保持运行。

## v261016.7 · 按参考程序切换为单文件 EXE

- 默认打包格式改为单文件 EXE，依赖版本与参考 `D:\ResearchWorkbench.exe` 对齐（PyInstaller 6.22.3、Python.NET 3.2.1、CLR 加载器 0.3.1）；保留 `--layout directory` 供需要免解压的场景。
- 单文件运行库临时解压到当前工作目录，避开这台机器系统 TEMP 路径创建 `_MEI` 失败；运行目录需可写，正常退出时由 PyInstaller 清理临时目录。
- EXE 启动原生 WebView 前自动在 EXE 同级补建本程序专用 `.exe.config`，只在该程序范围启用 CLR 的随包程序集加载；若已有配置则不覆盖。发布 ZIP 也包含配置文件。
- 验证：将发布 ZIP 解压到隔离目录，单独复制 EXE 到空目录运行；服务、WebView2、托盘、单实例唤回、最大化/还原、后台计时与正常退出均通过。12 个随包插件被发现，手册可读；浏览器走查 19 个路由通过，无控制台错误或失败请求。桌面回归 19/19、资源回归 4/4，知识库只读冒烟通过。记录：`.scratch/verify/exe-20261016-135831/result.json`；产物校验和：`dist/windows-build.json`。

## v261016.6 · Windows EXE 启动修复与实际打包验收

- 默认发布免解压目录版，保留可选 `--layout onefile`；EXE、版本化运行库目录及同名 `.exe.config` 必须一起保留。避开单文件启动器临时目录创建失败，应用级 CLR 配置修复随包程序集被 Windows 判为网络来源后的加载失败，不改系统配置。
- 固定 Python.NET / CLR 加载器及 PyInstaller 版本；ZIP 按本次干净构建清单收录运行库，排除旧运行库残留及用户数据。保留正在运行的旧实例，新输出为 `ResearchWorkbench-Updated.exe`，ZIP 内仍用标准名称。
- 兼容托盘创建窗口后可选消息过滤设置的权限拒绝（WinError 5），保留图标、菜单及后台运行；其他原生错误仍交由现有任务栏降级处理。
- 已构建 Windows x64 EXE / ZIP。真实 ZIP 解压至隔离目录后验证：WebView2、原生标题栏、托盘后台启动、单实例唤回、最大化/还原、隐藏时计时/暂停和正常退出；12 个随包插件被发现、默认启用 8 个，使用手册可读。
- 浏览器走查 19 个路由通过，无 console error / 失败请求，首屏未加载重型库；桌面回归 19/19、资源回归 3/3、知识库只读冒烟通过。验收记录：`.scratch/verify/exe-20261016-134447/result.json`，构建校验和：`dist/windows-build.json`。

## 2026-10-16 · 合并后远端功能保留复核

- 复核远端 `97932f3` 与合并结果 `eb0c733`：主要 V3 UI 与功能实现保留；记录插件化后的旧 API 不兼容、插件启用条件和一处 Agent 窄屏 CSS 选择器回归。详见分支比较文档第 8 节；本次仅补充审计记录，未修改应用代码。

## 2026-10-16 · 合并 UI V3 与桌面性能改进

- 合并 Smooling `feature/ui-redesign-v3` 至 `97932f3`，保留远端界面、深色主题、原生标题栏、异步确认框、托盘/单实例及后台专注计时；当前契约、插件、来源与版本管理继续保留。
- 接入不落盘草稿、统一未保存保护和保存期间继续输入保护；项目页通过 `ERWPanels` 导航，保留标签与未归属筛选，桌面 DOM 监听复用 `ERWDom`。
- 保留 SQLite 快照读取、后台同步、增量图谱和重型库按需加载，接入 HTTP 队列、断连容错及启动超时重试。修复 Agent/插件/MCP 写入索引一致性、项目稳定 ID 更新、MCP 旧搜索引用与回收站导入缺失。
- 修复计费页首次并发读取价格表的竞争；补齐随包插件、手册、PDF 资源及打包隐藏导入，正确区分资源根与自定义数据根，打包资源排除个人配置/工作区。
- 验证：架构 20/20、桌面 17/17、计时 9/9、资源 3/3、批量删除 4/4、隔离版本回归 40/40；知识库、前端静态、清单、插件及 MCP 自检通过。浏览器隔离回归及本地服务走查结果见 `docs/BRANCH_COMPARISON_UI_V3_20261016.md` 合并落地记录。
- 未构建或发布 Windows EXE；原生托盘/通知及干净目录 EXE 验收仍需实际打包验证。本次没有重新运行万篇性能基准。

## 2026-10-16 · UI V3 分支合并评估

- 对比当前 `301398a` 与 Smooling 的 `feature/ui-redesign-v3`（`97932f3`），区分共有性能基线、当前契约/插件/版本改动与远端新增桌面/草稿保护。
- 记录两项已复现的索引回归、打包资源缺口、7 处三方合并冲突及分组保留建议；详见 `docs/BRANCH_COMPARISON_UI_V3_20261016.md`。本次仅评估与文档记录，未合并或修改应用代码。

## 2026-10-15 · Architecture performance optimization

- 将外部文件检查移到后台，缓存工作区初始化；读取使用 SQLite 快照，避免周期性全库扫描阻塞请求。
- 统一 HTTP、Agent 和文献的文档读写入口，修复中文短词搜索、附件更新及保存后索引可见性。
- 图谱改为局部依赖更新，批量删除共用事务；加入稳定 FTS rowid、排序索引、连接关闭和可恢复的 schema 3 升级。
- 图谱页面只加载一次数据；MathJax/Mermaid 按需加载。删除旧研究总览、旧图谱/里程碑渲染、项目桥接和旧搜索装配路径。
- 自检改为隔离配置，增加架构回归、浏览器按需渲染验证及可复现万篇合成基准。对比数据见 `docs/PERFORMANCE_ARCHITECTURE.md`。

## v261009.57

**版本/快照条目不再出现在列表与检索里**（用户反馈：工作总结里还能看到很多残留历史笔记）。

### 根因
版本与快照是**真实存在于 `Knowledge/` 的条目**（当初的取舍是"版本都在 Knowledge/"），
于是它们和普通条目一起进了索引 → **工作总结、笔记等所有列表、检索、计数**里都能看到
`总结-学位论文开题报告完善稿（v2·500字版）（v-1012-171121）` 这类残留 ✗

### 修法：版本条目不进索引
- `app/perf_index_core.py` 新增 `is_variant_file(path)`（只读文件头判 `variant_of:`），
  索引遍历 `_doc_paths()` **跳过版本/快照条目** → 所有列表、检索、计数都不再显示它们；
- 「版本」页不受影响：它走**文件层** `store.list_docs`（实测索引 5 条 vs 文件层 6 条 ✓ 版本仍在）；
- `core/doctor.py` 相应调整：新增「文档·版本条目」一项（如 `note 1、summary 1`），
  磁盘计数**按 kind 扣掉**版本条目后再与索引比对（实测 203 = 203，7 类逐一相等 ✓），
  并让版本条目**跳过普通条目的命名/H1/字段校验**（它的标题故意带「（v-…）」后缀、H1 是原名，
  否则会误报「title 与首个 H1 不一致」）。

### 验收
索引里 `summary` 5 条（无快照）/ 文件层 6 条（版本页可见）；
`python -m core.doctor` **error 0**、`kb_smoke` 通过（203 条）、`plugin_check`、`web_check`、
快速档 **15/15 · 121/121**。

### 你还需要做的
**重启 8765**（内核改动）。重启后：工作总结等列表里不再出现带「（v-…）」的版本；
想把现有版本彻底收掉，在「版本」页点 **「采用最新版本并归档其余」**（进归档区，不占条目数）。

## v261009.56

**默认合并最新版本 + 不再堆一堆版本条目**（用户要求：默认合并最新版本，不要在库里存这么多笔记）。

### ① 每族只保留**一个**自动快照（内核）
此前"每次来源变化/分叉期间写入"都会**新建**一版 → 同一条笔记被外部工具改几次就堆出好几版
（用户那条开题报告就出现了 17:10 / 17:22 / 17:26 三版）。
现在 `snapshot_before_write`：族里**已有自动快照就覆盖它**（保留原 id，更新内容/标签/时间），
不再新建。**用户显式开的分支不受影响**，仍各自独立保留。
- 实测：连续两次外部写入 → 版本数 **1 → 1**（快照内容为第二次写入前的内容）；
- 新增 `is_snapshot()`（区分"内核自动快照"与"用户显式分支"）与 `latest_variant()`（最新版口径）。

### ② 默认就对着"最新版本"（界面）
- ② 的对照对象默认改成 **最新版本**（按 `variant_at` → `created` → `updated` 取最大），不再默认第一版；
- 多版本时顶部多一个醒目按钮 **「采用最新版本（v-…）并归档其余」**：一键把最新版正文写回基条、
  其余版本移入 `System/Versions/<基条>/archived/`（**离开知识库**、仍可追溯/取回）；
- 采用动作记 `doc_merge`（`wholesale=true`），出现在修改记录里；**改动前基条快照会保留**（可回退）。

### 清理你现有的多余版本
打开那条开题报告 → 点 **「采用最新版本（…）并归档其余」**，3 版会收敛成 1 条基条 +
归档区里的副本（不再占知识库条目数）。

### 验收
隔离验证：快照节流 1→1 ✓、快照内容正确 ✓、`latest_variant` 取到最新 ✓、采用后归档其余 ✓；
`tests/kernel/test_versions.py` **40/40**（④-1 改为断言"仍留版本但不再堆新条目"）、
`tests/kernel/test_versions_page.py` **14/14**。

## v261009.55

**「我要保留哪一版」可以直接选**（用户反馈：不能直观选择要保留的版本）。

### 新增：整版采用（以这版为准）
- 每个版本行右侧两个按钮：**「对照」**（用这版做对比基准）与 **「以这版为准」**（整篇采用）；
- 点「以这版为准」→ 确认后把该版正文**整篇写回基条**（保留基条 id/标题/项目），
  并把**采用前已存在的其他版本**归档（可追溯）；**内核自动留下的"改动前基条"快照会保留**，
  万一采用错了还能回退；
- 记录 `doc_merge`（`detail.wholesale = true`、`adopted = <版本 id>`），因此它会出现在**修改记录**里。

### 新增：对照版本可选
- ② 顶部多一个 **「对照版本」选择器**（多版本时出现），切换后所有小节的徽章与差异**即时重算**；
- 默认取第一版；点某行「对照」也能切换。

### 内核
`app/versions.adopt_variant()`（单一实现）+ `core_api.adopt_variant()` 窗口 + 插件路由 `adopt`。
语义细节：`others` 在写入**之前**取——否则会把"写入触发的改动前快照"也一并归档掉。

### 验证
隔离工作区真调用：采用 v2 后基条正文变为 v2 内容 ✓、基条 id/标题未变 ✓、v3 已归档 ✓、
族里只剩"改动前基条"快照（可回退）✓；`test_versions` **40/40**、`test_versions_page` **14/14**。

## v261009.54

**版本页：只显示被改动的内容，差异直接内联展开**（用户反馈：界面不直观、太繁杂）。

### 先说清一件事：截图里 13 个小节全标「基准独有」是**数据层**问题
版本正文的取数修复在 `core_api.py`（**内核**，v261009.52）—— 用户当时的 **8765 实例还在跑旧代码**，
插件拿不到版本正文，于是每个小节都被判成「基准独有」，13 个全冒出来。**重启 8765 后即恢复**。

### 界面改动（插件 v1.0.7）
| | 之前 | 现在 |
| --- | --- | --- |
| 有改动的小节 | 标题在左、下拉与「看变更」推到最右，中间一大片空白；差异要点按钮才展开 | **紧凑卡片**：标题 + 徽章 + 右侧小控件，**差异直接内联展开**（不用再点） |
| 来源选择 | 一律用宽下拉 | 只有一个版本时是 **「采用新版 / 保留基准」** 两个小按钮（多版本才用下拉） |
| 一致的小节 | 也列出来（还带下拉） | **只留一行**灰色「N 个小节与基准一致 · 已自动沿用（点开可核对）」，**没有任何控件** |

### 顺带确认的语义（不是 bug）
有改动的小节**默认就选中「采用新版」**——这正是"只有被修改的部分需要同意"的落地：
你不需要逐节挑，只在**不想要**某处改动时点「保留基准」。夹具原先在合并后仍期待"有待确认项"，
按新语义已把断言挪到合并前。

### 验证
`tests/kernel/test_versions_page.py` **14/14**（②-3 兼容按钮/下拉两种布局、②-9 改动行徽章、
②-10 差异内联展开、②-11 一致行无任何控件）；快速档 **15/15 · 121/121**。

## v261009.53

**只有「被改动的小节」需要你确认**（用户反馈：每段都要挑版本太麻烦）。

### 改动前 vs 改动后
| | 之前 | 现在 |
| --- | --- | --- |
| 一致的小节 | 也摆一个下拉，逼你逐个确认 | **收进折叠块**「N 个小节一致 · 已自动沿用基准（点开查看）」，**没有下拉**，只在行尾标「沿用基准」 |
| 有改动的小节 | 与一致的小节混在一起 | **只列这些**，各带来源下拉（默认已是该版本；选「基准」= 不采用这处改动） |
| 一键 | 无 | **「全部采用 <版本> 的改动」**，把有改动的小节一次设为该版本 |
| 主按钮 | 「合并」 | **「应用 N 处改动」**（语义：只写回需确认的那几处） |
| 总览 | 有差异小节数 | 「…**N 个小节有改动，需要你确认**；其余小节自动沿用基准」 |

### 顺带补上一个真缺口：删除型改动原本应用不了
`app/versions.py::merge_bodies` 原先只在"来源含该标题"时替换，**来源缺该节时保持基准** ——
于是「某版本删掉一整节」这种改动**根本无法应用**（实测：Trae 写出的版本删了「附：条目关联」，
挑它合并却毫无变化）。现在：**挑中的来源缺该小节 = 该节被删除**，从结果里去掉，
并在返回值里标成 `小节名（删除）`（`doc_merge` 活动也会记下）。

### 验证
- `tests/kernel/test_versions_page.py` **14/14**（新增 ②-11：只有改动的小节要确认、一致行里没有下拉）；
- `tests/kernel/test_versions.py` **40/40**（新增 ⑭：删除型改动能应用、返回值标明删除）；
- 快速档 **15/15 · 121/121**；
- 真实数据：该笔记 13 个小节中 **1 个需确认**（附：条目关联，基准独有）、其余自动沿用基准，
  顶部一句「与 v-1012-171041 相比：1 个小节有改动，需要你确认」+ 一键采用按钮。

## v261009.52

**版本页加「逐节变更对照」**（用户反馈：看不到变更内容，无法直观决定怎么改）。

### 为什么需要
之前版本页只列出「基条 / 各版本 + 来源 + 小节数」，**看不到正文差异** —— 用户面对
`总结-学位论文开题报告完善稿（v2·500字版）` 与 Trae 写出的 `v-1012-171041` 时，
不知道两者差在哪、该保留哪版，也就无法决定怎么合并。

### 做了什么（只动 version-manager 插件 + 一处内核取数）
1. **逐节状态徽章**：每个 H2 小节标出 **`+N / −M 行`（有改动）/ 一致 / 基准独有 / 仅该版本有**；
2. **「看变更」展开逐行 diff**：行级 LCS 对比（无第三方库），`+` 绿底新增、`−` 红底删除、其余为上下文；
   **单边小节也能看内容**（基准独有 → 该节行以 `−` 列出；仅该版本有 → 以 `+` 列出）；
3. **对照对象跟随选择**：切「② 按小节挑内容」里的来源版本，该小节的徽章与 diff **即时**跟着变；
4. **顶部总览**：如「与 v-1012-171041 相比：**1 个小节**有差异」；
5. 大节保护：行数乘积过大时退化为「仅统计 N 行 → M 行」，避免卡界面。

### 顺带修掉一个内核取数 bug
`core_api.variant_family(with_body=True)` 此前**没带出版本正文**：`V.family()` 内部用的是
`store.list_docs()`（**不含正文**），只有基条是完整条目 → 界面做逐节 diff 时会把每个小节都判成
「基准独有」（实测踩到，13 个小节全错）。修法：`with_body=True` 时逐个 `store.get_doc` 取完整条目。

### 验证
- 夹具 `tests/kernel/test_versions_page.py` **13/13**（新增 ②-9 小节变更徽章、②-10 看变更展开逐行差异）；
- 你的真实数据：搜「开题报告完善稿」→ 该笔记 13 个小节中 **12 个一致、1 个（附：条目关联）基准独有**，
  点「看变更」看到它独有的 4 行（方法笔记 / 灵感 / 里程碑 三条关联）；**0 console error**。

## v261009.51

**让「任意笔记的更新历史」找得到、看得懂**（用户问：开题报告总结稿用 Trae 更新了，为什么看不到更新历史）。

### 先查清事实（那条笔记 `summary-20261012103239-b5999e`）
它**有 11 条更新记录**，包括今天的 `16:10 / 16:19 / 16:34 / 16:48` 四次 —— 记录一直在，是**两个显示问题**让你看不到：

| 原因 | 说明 |
| --- | --- |
| **① 它不在左栏列表里** | 该笔记 `forked=False`（没有分叉），而列表默认「只看分叉中」→ **根本选不中**，自然看不到它的修改记录 |
| **② 来源是空的** | 那几次写入来自 **Trae 那个 09:56 启动的旧 MCP 进程**（早于 v261009.47 的修复）→ 旧代码只记事件、不记来源，页面上显示为空白，看起来像「没有历史」 |

### 改动（version-manager 插件 v1.0.4）
1. **搜索时忽略「只看分叉中」筛选**：输入标题关键词就能选中没分叉的笔记，看到它的更新历史；
2. 左栏每行显示**最近修改时间**（如「工作总结 · 改于 10-12 16:48」），便于发现刚改过的笔记；
3. 修改记录里来源为空时，明确写成 **「未记录来源（该次写入来自旧版 MCP 进程或外部工具）」**（弱化斜体），
   而不是留空让人以为没历史；
4. 空列表提示补一句：「想看某条笔记的**更新历史**？切到「全部」，或直接搜标题。」

### 验证（真浏览器，1413×741，真实库）
搜索前可见族 **1** → 搜「开题报告完善稿」→ 命中 `总结-学位论文开题报告完善稿（v2·500字版）`
（副标题「工作总结 · 改于 10-12 16:48」）→ 点开显示 **11 条修改记录**，最近四条即今天
16:10/16:19/16:34/16:48，均标注「未记录来源（…旧版 MCP 进程或外部工具）」；**0 console error**。

### 你该做的
**在 Trae 里重启 MCP 服务**（旧进程仍在跑 09:56 的代码）—— 之后 Trae 的每次写入都会带来源
（`外部 MCP 客户端 · kb_update_entry · 客户端名 · 时间`），分叉/冲突时还会自动留版本。

## v261009.50

**kb_* MCP 工具审计：清单 + 参数一致性 + 隔离工作区逐个真调用**（用户要求"梳理 kb 的 MCP 功能、查 bug 与重复工具"）。

### 修掉 3 个真 bug（都是"真调用"抓出来的，不是看代码猜的）
| # | 问题 | 根因 | 修法 |
| --- | --- | --- | --- |
| A | **`kb_list_entries` 完全不可用**（`TypeError: list_docs() got an unexpected keyword argument`） | bridge 把 `sort` 传给了索引层 `list_docs`，它不接受该参数 | 只传索引层支持的参数，**`sort` 在本地做** |
| B | **`kb_check_entries` 同样崩** | 同源（它也列举条目） | 同上 |
| C | **版本族 4 个工具返回双重包装**（客户端拿到 `{"content":[{"text":"{\"content\":…}"}]}`） | handler 自己调了 `ok()`/`fail()`，包装层又包一层 | 包装层改**幂等** `_wrap()`：已是信封就原样返回 |

修复后：**13 个 kb 工具逐个真调用 13/13 全绿**（唯一 RAISE 是故意放的"不存在的工具"对照）。

### 重复工具评估：**没有该删的重复**，3 组需说清边界
- `kb_rename_entry` ≠ `kb_update_entry{title}`：前者同步 H1 与**全库交叉引用**、带规范校验与 dry-run；
- `kb_change_kind` ≠ 建+删：迁移保留 id/created、目录随动、可同步引用；
- `kb_delete_entry` vs `kb_archive_variants`：条目进 `System/Trash/` vs 版本进 `System/Versions/<基条>/archived/`；
- **部分重叠**：`kb_branch_entry` ↔ `kb_create_entry{variant_of}`（前者多做：复制源内容、生成标签、写 `variant_at`）
  建议开分支一律用 `kb_branch_entry`；`kb_search` ↔ `kb_list_entries{query}`（相关性检索 vs 枚举过滤）。

### 交付
`docs/MCP_KB_AUDIT.md`（清单表 + bug 表 + 重叠评估 + 复跑命令）；
`tests/kernel/test_mcp_plugin_split.py` 的工具面计数改为**动态**（内核工具增删不再让夹具变红）。

## v261009.49

**排查「用 Trae 改笔记却没有记录」**（用户报告），并补上「外部直接改文件」的发现能力。

### 排查结论（三项事实）
1. **Trae CN 的 MCP 配置是最新的** ✓ —— `%APPDATA%\Trae CN\User\mcp.json` 里
   `engineering-research-workbench` → `python -m mcp.server`，`PYTHONPATH` 指向本仓库，无需修改；
2. **但 Trae 持有的 MCP 进程是旧代码**：实测在跑 4 个 `python -m mcp.server`（起于 10-11 12:39 / 13:43 / 14:06、
   10-12 09:56），**都早于** v261009.47 的写入路径修复 → 旧进程写出来的就是「有事件、**无来源**、无分支」
   （活动日志里 16:05/16:10/16:19/16:34 那几条「（无来源）」正是这个签名）；
3. **用户那两份「开题报告-详细稿/完善稿.md」根本没走 MCP**：16:44 被改，却**一条事件都没有**、
   也没有来源字段 —— 它们是**工作区根目录的普通文件，不在知识库里**（没有 id/frontmatter），
   工作台本就不跟踪这类文件。

### 新增：外部直接改动巡检（`app/external_edits.py`）
- **判据不需要新状态**：条目文件改动时间**晚于**该条目最后一次活动事件（内核每次写入都会同时更新文件并记事件）；
- `scan(record=True)` 把发现记成 **`doc_external_edit`** 事件（来源「工作区外部改动（未经界面/MCP，
  可能是外部工具或同步）」），于是会出现在「版本」页的**修改记录**里；
- 同时列出 **`untracked`**：工作区里被改过但**不在知识库内**的 `.md`（实测就抓到了用户那两份开题报告，
  以及 `Projects/…/README.md`、`Exports/…` 等），并在结果里标注「是知识库条目: False」；
- 入口：`core_api.external_edits()`、MCP 工具 **`ws_external_edits`**（`record=true` 是写，受外部接入授权约束）。

### 验收
真实库巡检：条目 **6 条**被外部直接改动（10-08/10-11 的同步或外部工具写入）+ 库外文件 **5 个**
（含用户的两份开题报告，`in_kb=False`）。
`tests/kernel/test_versions.py` 新增 ⑬ 节：巡检发现「文件被改过但没有记录」· 记录成 `doc_external_edit`
（来源含「工作区外部改动」）· 结果含库外文件清单。

### 用户该做什么
1. **在 Trae 里重启 MCP 服务**（或退出重开 Trae）—— 之后 `kb_*` 的写入才会带来源、才会在分叉/冲突时留版本；
2. 想让某份稿子有记录，就把它**放进 `Knowledge/`**（用 `kb_create_entry` 建条目），
   工作区根目录的散稿不在知识库范围内、不会被跟踪。

## v261009.48

**把「修改记录」变成看得见的东西**（用户报告：用 `kb_update_entry` 改了笔记，在历史里看不到修改记录）。

### 先验证：后端其实一直在记
在真实库上跑了一次 `kb_update_entry`（写回该条自己的正文，内容不变），活动日志确实新增三条：

```
doc_create · 知识-架构-意图世界模型实现架构（v-1012-162303） · 命令行 · snapshot:来源变化 ->mcp
doc_update · 知识-架构-意图世界模型实现架构 · 命令行 · mark_forked
doc_update · 知识-架构-意图世界模型实现架构 · 外部 MCP 客户端 · kb_update_entry · 2026-10-12 16:23   ← 这条就是「修改记录」
```

**问题在界面**：概览的「最近研究活动」渲染的是 `dash.recent.*`（最近**产生的条目**），**不是活动事件日志** ——
所以修改记录只躺在 `System/activity.jsonl` 里，界面上没有任何地方显示它。

### 改动
1. **`core_api.activity_events(days, ref=…, refs=…, types=…, limit=…)`**：内核窗口，插件可读活动日志（I3），
   每条带 `source` 与合并 `detail`；
2. **MCP `ws_activity` 支持 `ref` / `types` / `limit`**：外部 Agent 可以直接问
   `ws_activity { ref: "<条目 id>", days: 30 }` 拿到这条笔记的修改记录；
3. **version-manager 插件 v1.0.3**：新增路由 `history?id=&days=`，页面详情新增
   **「④ 修改记录（最近 90 天）」** —— 逐条显示 时间 · 类型（新建/更新/合并/归档/取回）· **来源** ·
   合并的替换小节；顶部一句说明「外部 MCP 客户端 · kb_update_entry · 客户端名」这类来源会直接写在这里。

### 验收
`tests/kernel/test_versions_page.py` **11/11**（新增 ②-8：**页面显示「修改记录」且带来源**）；
`core_api.activity_events` 实测能取到真实库最近事件（含 `外部 MCP 客户端 · kb_update_entry`）；
快速档 **15/15 · 116/116**。

## v261009.47

**修两个用户报告的问题**：① 插件卡片「可用」徽章点不动；② 外部 Agent 改了既有笔记却没有修改记录与分支。

### ① 插件卡片的「可用」徽章改成可点的快捷启停
**现象**：卡片上那个「可用」看起来像按钮，点它没反应（真正的开关是旁边的「启用」勾选框）。
**修法**：徽章改成 `<button class="badge pm-state-btn">`，点击即切换启用状态（复用启用开关那条路径，
失败时给提示）；悬停有提示文案「点击启用/停用这个插件」。文案与配色仍走内核同一份 `STATE_LABEL`。

### ② 外部 Agent 改既有笔记 → 现在会出现修改记录与分支（**根因在写入路径**）
**根因（两层）**：
1. **界面保存与 MCP 更新此前都绕过了写入收口点**：它们走 `indexer.update_doc` →
   `app/perf_index_runtime.update_doc`，而那个函数**自己解析 frontmatter、自己 `_atomic_write`**，
   于是 `store.update_doc` 里的来源记录与"分叉/冲突时先留一版"**完全不会发生** ✗；
2. 即便走到 store，**历史条目从没记过 `origin_*`**（200+ 条），旧规则要求"前后来源不同"才算冲突 →
   "上一个来源未知"被当成不冲突 → 外部写入不留版本 ✗。

**修法**：
- `perf_index_runtime.update_doc` **改为委派 `store.update_doc`**（单一写入路径：契约校验、来源、留版、
  活动日志都在 store），本函数只负责同步索引 —— 界面保存与 MCP 更新因此都走同一条路；
- 冲突判定扩展：**来源未知 + 外部写入（agent/mcp/plugin/cli）也算冲突**，先把写入前内容留成一版；
  **界面自己保存（ui）不算**，否则每改一条历史笔记都会凭空多一版（实测确认两种情形）；
- MCP 的 `update_entry` 补上来源（`kb_update_entry` → `origin_surface=mcp`），
  `mcp/bridge.py` 的 `update_entry` 支持 `origin` 透传。

### 顺带：夹具隔离补强
`mcp/bridge.py` 的工作区取的是 `config.workspace_root()`（不是 `get_app()`），夹具只 patch 后者会让
MCP 路径指向真实库、报 `relative_to` ValueError（假失败）→ 夹具同时 patch `workspace_root`。

### 验收
`tests/kernel/test_versions.py` **35/35**（新增第 ⑫ 节：历史条目确实无来源字段 · **外部写入历史条目会先留一版** ·
留下的那版是写入前内容 · **基条记下外部写入来源 = mcp** · **界面自己保存历史条目不凭空多一版**）；
快速档 **15/15 · 116/116**；`kb_smoke` / `web_check` / `plugin_check` / `core.plugins list` / `mcp --selftest` 全绿。
另：按你的意图把 `metrics-table` 关掉了（`enabled: false`）。

## v261009.46

**MCP 工具面按插件拆分：只暴露「已启用插件」的工具**（用户要求）。

### 改动
- `mcp/server.py` 的 `tools/list` / 分发**动态**组成：**内核工具 29 个始终可用**
  （`kb_*` / `ws_*` / `todo_*` / 文献导出）+ **已启用插件的工具**（名如 `p_<插件id>__<工具>`，与内核 Agent 面一致）；
- **插件停用 → 它的 MCP 工具消失**（判定与内核同源：`registry.effective_enabled`——有记录按记录，
  没记录按 `default_enabled`）；启用 → 出现，**不需要重启 MCP 服务**（每次取目录比对"已启用插件指纹"，
  变了就重载运行时）；
- 插件**写工具**（注册时 `write: true`）同样受「设置 → 外部接入 → 允许外部 MCP 客户端写入知识库」约束；
- MCP 进程**只借插件的工具，不跑它们的后台任务**：加载后立刻 `jobs.shutdown()`，
  否则备份插件这类定时任务会在 MCP 进程里再跑一份；
- `--selftest` 改为报「工具面统计」：`kernel_tools` / `plugin_tools` / `tools`。

实测（当前启用集合）：工具面 **34** = 内核 **29** + 插件 **5**
（`p_literature-reader__context|note_write`、`p_version-manager__versions|merge_versions|archive_versions`）；
未启用的插件（report-export / backup-snapshot / milestone-calendar / metrics-table）**一个工具都不贡献**。

### 实现里踩到并修掉的三个真问题
1. **停用插件后工具仍在**：运行时可能还留着上次加载的注册表 → 目录改为按**当前启用集合过滤**，
   不信任运行时的清理；
2. **插件写工具没被授权拦住**：我构建目录条目时把 `write` 标记丢了 → 内部字段 `_write` 保留并让
   `_is_write_tool` 同时认它（该字段不随 `tools/list` 外发）；
3. **默认开启的插件被误过滤**：只读 `plugins.json` 的 `enabled: true` 会漏掉
   "随包附属、默认开、尚未产生记录"的插件（version-manager 就是这样，实测插件工具只剩 2 个）
   → 改用内核同一判定 `registry.effective_enabled`。

### 验收
新增 `tests/kernel/test_mcp_plugin_split.py` **11/11**（**完全隔离**：workspace 与 `System/plugins.json`
都在临时目录，不动用户的插件开关；只快照/还原仓库里的 `config/external-access.json`）：
只启用 version-manager 时它的 3 个工具在列表、未启用插件的工具不在、内核工具始终在、
工具面计数正确、**启用另一插件后不重启也能看到**、**停用后消失**、插件工具可调用、
**插件写工具未授权被拦 / 授权后放行**、未知工具名报明确错误、授权文件已还原。
快速档 **15/15 · 111/111**；`mcp.server --selftest` 绿。

## v261009.45

**分支/合并的 MCP 工具 + 每个分支记录时间**（用户要求）。

### 新增 MCP 工具（`mcp/` 是内核侧，直接调内核实现）
| 工具 | 作用 | 写？ |
| --- | --- | --- |
| `kb_branch_entry`（**新**） | **开一条分支**：以某条条目为源复制内容成新版本，记 `variant_of`/`variant_label` 与 **`variant_at`** | **是**（受「外部接入」授权约束） |
| `kb_variants`（增强） | 族视图里带出**每条分支的时间**（`times`：variant_at/created/updated/origin_at） | 否 |
| `kb_merge_variants`（改走统一实现） | 按小节合并；记 `doc_merge` 活动 | **是** |
| `kb_archive_variants` | 归档（清单里已有 `archived_at`） | **是** |

MCP 工具数 **12 → 13**，`WRITE_TOOLS` 加 `kb_branch_entry`。

### 时间口径（一次说清）
`variant_at` 分支创建时间 · `created`/`updated` 条目创建/最近写入 · `origin_at` 该次写入时间 ·
归档清单 `archived_at` · 合并时活动日志 `doc_merge.detail.merged_at`（含替换小节与参与版本）。

### 内核侧（让四条路径行为一致）
- 契约新增 **`variant_at`**，由内核在**写文件之前**写入（放到写完之后是无效的——实测踩到）；
- `app/versions.py` 新增 **`create_branch()`**（开分支的唯一实现）与 **`merge_family()`**（合并的唯一实现：
  合并正文 → 写回基条 → 记 `doc_merge` 活动）；`family()` 带出 `times`；
- `core_api.merge_variants` 与 MCP 的 `t_merge_variants` 都改为调用 `merge_family` ——
  界面 / 内核 Agent / 插件 / MCP **共用一套实现**，不会各写一份；
- `app/activity.py` 支持结构化 `detail`（合并记了哪些小节、来自哪些版本）；
- `mcp/bridge.py` 暴露 `versions`（MCP 工具用它；此前没有 → 工具报 `SimpleNamespace has no attribute`）。

### 界面
`version-manager` 插件（v1.0.2）的版本行现在显示「**分支于 2026-10-12 14:32** · 更新 … · 小节 N 个」。

### 验收
`tests/kernel/test_versions.py` **30/30**（新增第 ⑩/⑪ 节）：活着的分支都带创建时间 ·
开分支复制内容且记 variant_at/variant_of/label · 族视图带每条分支时间 · 合并返回 merged_at 与参与版本 ·
活动日志有 `doc_merge`（含时间/小节/来源） · **MCP 未授权时开分支被拦** · 授权后开分支成功并返回创建时间 ·
MCP 族视图带时间。夹具还快照/还原了 `config/external-access.json`（授权文件在仓库里，不能改用户的开关）。

## v261009.44

**「版本」功能改为插件：`plugins/version-manager/`**（用户要求"将该功能作为插件"）。

### 边界怎么划的
| 归**内核**（插件无法替代） | 归**插件**（`version-manager`） |
| --- | --- |
| 契约字段 `variant_of`/`variant_label`/`has_variants`/`origin_*` | 导航页（族列表、逐版对照、挑小节、归档/取回） |
| **写入收口点**记来源、分叉/冲突时先留一版（`store.create_doc/update_doc`） | 本插件 5 条 HTTP 路由 + 3 个 Agent 工具（两个写工具走草稿确认） |
| 版本逻辑引擎 `app/versions.py`（归族、分节合并、归档区） | —— |
| MCP 侧同名工具（`mcp/` 属内核侧） | —— |

理由：版本与来源必须在内核的**写入收口点**处理，否则界面 / 内核 Agent / MCP / 插件四条路径里总有漏网的；
而"页面与操作"是功能面，按项目架构归插件。

### 具体改动
- **新增插件** `plugins/version-manager/`（`plugin.json` / `backend.py` / `web/panel.js` / `web/panel.css` /
  `README.md`）：`default_enabled: true`（附属），权限 `ui:panel` + `config:own`，导航 id `version-manager`，
  路由 `overview|family|merge|archive|restore`，工具 `versions|merge_versions|archive_versions`，并带 `preview`。
- **`core_api` 新增版本窗口**（插件唯一入口，I3）：`version_overview` / `variant_family` / `variant_sections` /
  `merge_variants` / `archive_variants` / `restore_variant`。
- **内核移除**：页面 `web/versions.{js,css}` 与装配清单条目、`/api/versions*` 路由与 4 个辅助函数、
  3 个内核 Agent 工具（内核工具回到 **4 个**，与 SCOPE §5.1 一致）；MCP 工具保留。
- 升 `VERSION` → `v261009.44`（插件 `core_min` 指向引入版本窗口的这一版）。

### 实现里踩到并修掉的两个真问题
1. **`core_api.entries()` 走 SQLite 索引，而索引 schema 不含 `variant_of`** → 总览把每个版本都当成独立族
   （实测报 2 个族 / 0 个分叉）。`version_overview` 改用**文件层** `store.list_docs()`。
2. 换实现时漏了 `from app import versions as V`（函数后半段还在用它）→ 插件路由 500；
   已修，并在注释里写明"这里必须走文件层"的原因。

### 验收
- 插件校验通过（`core.plugins check version-manager`）；`plugin_check --assert-core-only`、`web_check`、
  `kb_smoke`、`core.plugins list`、`mcp.server --selftest` 全绿；
- `tests/kernel/test_versions_page.py` **10/10**（已改为走插件路由与 `.vm-*` 选择器）：
  族详情、来源 chip、挑小节、合并、归档、取回、0 console error；
- `tests/kernel/test_versions.py` **22/22**（内核逻辑不变）；快速档 **14/14 · 92/92**；
- `tests/plugins/test_reader_plugin_tools.py` 的"内核工具恰好 4 个"断言恢复成立（版本工具已搬走）。

## v261009.43

**「版本」页 UI 重做**（用户反馈"UI 不可看"）——修掉截图里能看到的三个真问题。

### 问题与修法
| 现象 | 根因 | 修法 |
| --- | --- | --- |
| 左栏行被压扁成一条条细线、底部还有横向滚动条 | 列表是 grid，子项缺 `min-width:0`，列宽被内容撑开；行高又被 `height:auto` + 撑宽后的省略号挤压 | `grid-auto-rows:min-content` + `overflow-x:hidden` + 标题 `min-width:0` 省略号；行高实测 **45px**、横向溢出 **0px** |
| 右栏头部与「① 各版本」之间一大片空白 | 上一版给 `.ver-pane` 设了 `grid-template-rows:minmax(0,1fr)`，多个子元素时**第一个子元素独占整屏** | 改回普通块流 + 自身 `overflow:auto`；实测头部到 ① 间距 **14px** |
| 202 个族全列出来等于噪音，且没有分叉时默认视图**空着像坏了** | 缺少过滤与兜底 | 加「只看分叉中 / 全部」分段控件 + 标题搜索框；**没有分叉时自动回落到「全部」**并给出一句说明（教怎么造出第一个版本） |

另外：没有分叉的族不再摆一堆空控件，改成一句虚线提示（"再建一条同名不同版，这里就会出现可对照的版本"）。

### 验收
- 文本量测（1428×760，你的真实库）：左栏 **202 行 · 行高 45px · 横向溢出 0**；右栏头部间距 14px、自身可滚 0；
  默认过滤 `all`（自动兜底）、窗口可滚 0、横向溢出 0、**console error 0**；
- 真浏览器夹具 `tests/kernel/test_versions_page.py` **10/10**（族详情、来源 chip、挑小节、**合并**、**归档**、**取回**、0 报错）——重做 UI 后交互未回退；
- `web_check`、`ui_smoke` **20 路由**、快速档 **14/14 · 92/92** 全绿。

> 另记：`metrics-table` 又被某次夹具运行翻回未启用（同类问题此前出现过），已重新启用。
> 根因是部分夹具会快照/还原 `System/plugins.json`，失败中断时会留下旧状态——后续可让这些夹具把
> `plugins.json` 也指向临时目录以彻底隔离。

## v261009.42

**「版本」页：在工作台里查看与处理同一笔记的不同版本**（v261009.41 内核功能的界面部分）。

### 页面（内核模块 `web/versions.js`，自登记导航页，**不动 app.js**）
- **左栏**：版本族列表（标题 / 类别 / `N 个版本`），当前项用内核惯用的 `--accent-soft + --accent-ink`；
  顶部三个状态 chip：族数 / **分叉中** / 版本数；
- **右栏**：① 各版本（版本名、更新时间、H2 小节数、**来源 chip**：工作台界面 / 内核 Agent /
  **外部 MCP 客户端** / 插件，带客户端名与时间）② **按小节挑内容**（每个 H2 一个下拉，可选基准或某个版本）
  + 「合并」（可选"合并后归档被替换的版本"）+「归档勾选版本」③ 已归档清单（时间、来源、**取回**按钮）；
- 布局口径与内核一致：两栏、行高 31px、圆角 7px、**只有内容列滚动**（窗口不滚）。

### 验收（`tests/kernel/test_versions_page.py`，**完全隔离**：workspace 指到临时目录）
**10/10**：HTTP 接口 3 项（总览计数、详情含基条+版本+小节、来源含 MCP）+ 真浏览器 7 项
（侧栏项、族详情与来源 chip、小节可挑来源、**点合并真的合并**、**归档后出现归档区**、
**取回后重新出现活版本**、0 console error）。

真实库上的旁证：`/api/versions` 返回 **201 个族 / 0 个分叉**——自动归族没有误合并任何既有条目。
`ui_smoke` 现在走查 **20 个路由**；`web_check`、`doc_check`、快速档 14/14 · 92/92 全绿。

## v261009.41

**笔记多版本 / 分支 / 来源追踪 / 合并归档（内核功能，第一部分：数据模型 + 四条来源 + 工具与接口）**。

### 为什么放内核
界面、内核 Agent、**MCP 工具**、插件四条写入路径最终都汇到 `app/store.py` 的 `create_doc` /
`update_doc`。版本与来源只有在这两个收口点处理，才能"跟踪工作台内直接添加与外部工具（如 MCP）添加的文件"。

### 数据模型（字段声明在 `core/contracts/kinds.py` 唯一声明处）
- 同一笔记的不同版本 = **同一 kind 下的多条正常条目**，靠 `variant_of`（基条 id）+ `variant_label` 关联；
- 来源追踪（扁平字符串，避免嵌套映射在 frontmatter 往返里变形）：`origin_surface`（ui/agent/mcp/plugin/cli）
  + `origin_tool` + `origin_client`（MCP `initialize` 的 clientInfo.name）+ `origin_at`；
- `has_variants`：基条上的 **O(1) 标记**（族里还有活版本时为 true）——没有它，每次保存都要扫全库
  （200 条约 76ms）才能判断"是否处于分叉中"。

### 归族与留版本时机（按用户选定的口径）
- **归族**：显式给 `variant_of` 就用它；否则按**标题归一化签名**在同 kind 内找基条
  （外部工具塞进来的 `知识-方法-X（v2）.md` 自动归到 `知识-方法-X`）；
  **实验条目的 `（2.2）` 是编号不是版本号**，按 kind 区分，避免 `实验-X（2.3）` 被误判成 `（2.2）` 的变体；
- **留版本**：日常编辑仍是覆盖式（不变），只在①族处于分叉中 ②写入来源与该条上次写入者不同（冲突信号）
  时，**先把写入前的内容存成一版**；合并/归档时收口。

### 合并与归档
- **按 H2 小节合并**：选基准（基条）+ 逐节挑来源 → 合并结果写回基条，返回实际替换的小节清单；
- **归档**：变体移入 `Workspace/System/Versions/<基条>/archived/<时间>-<标签>.md`（**保留可追溯**，
  不计入条目数与检索），同目录 `index.json` 记来源与时间；`restore_variant` 可取回；
- 合并/归档后自动维护基条的 `has_variants` 标记。

### 接口与工具
- 内核 Agent：`kb_variants`（读）· `kb_merge_variants` · `kb_archive_variants`（写，自动走草稿闸门）→ 内核工具 4 → **7 个**；
- MCP：同名 3 个（9 → **12 个工具**），两个写工具已加入 `WRITE_TOOLS` → 受「设置 → 外部接入」授权约束；
- HTTP：`GET /api/versions`（族总览）、`GET /api/versions/<base>`（详情含各版正文与小节）、
  `POST /api/versions/{merge,archive,restore}`；
- 活动日志：`doc_create` / `doc_update` 增加 `source`（如「外部 MCP 客户端 · kb_update_entry · Claude Desktop · 10-12 13:30」）。

### 验收
新增 `tests/kernel/test_versions.py` **22/22**（**完全隔离**：monkeypatch workspace 到临时目录，不碰真实知识库）：
基条与来源 · MCP 自动归族 · 分叉留版 · 来源变化留版 · 分节合并 · 归档+清单+标记清理 · 取回 ·
实验编号防误合并 · 活动日志带来源。快速档 **14/14 用例 · 92/92 断言**；`kb_smoke` / `web_check` /
`plugin_check` / `core.plugins verify` / `mcp.server --selftest` 全绿。
顺带把 `test_reader_plugin_tools` 里"内核工具恰好 4 个"的**过时断言**更新为 7 个（版本功能所致）。

### 下一步（本版未含）
工作台内的**「版本」页面**（族列表 + 逐版对照 + 逐节挑内容合并 + 归档/取回按钮）——数据、工具与接口已就位，
页面单独提交。

## v261009.40

**第⑥步：清理工作区残留 + GitHub 上传前准备**。

### 清理（都是"搬出"或"删调试残留"，用户数据只读）
| 项 | 体积 | 处理 |
| --- | --- | --- |
| `Workspace (备份261009).zip` | **340 MB** | 搬到仓库外 `engineering-research-workbench-archive/2026-10-12-cleanup/`（可搬回） |
| `Workspace.zip` | 2.7 MB | 同上 |
| `_preview_*.png` ×4、`_verify_*.{py,mjs}` ×3 | ~0.6 MB | 删（早期调试残留） |
| `dsh-acl-recovery/` | 0.24 MB | 搬到归档（非本项目产物） |
| `__pycache__/`、`.scratch/{logs,preview}` | — | 删/清空（可重建） |
| `ResearchWorkbench.exe` + `build/` | 41 MB | **保留**（那是能直接运行的成品，且不入库） |

### 上传前审计（结论）
- **密钥**：`config/` 完全未跟踪，`secrets.json` 从未入库；跟踪文件里无 `sk-…` 形态密钥 ✓
- **历史最大对象 2.45 MB**（mermaid），无 >50 MB 对象 ✓；`.git` 约 **10 MB** / 430 个跟踪文件 ✓
- **用户数据**：当前 0 个 `Workspace/` 文件被跟踪 ✓；但**历史里仍有 11 个**（0.24 MB，
  1 张会话截图 244 KB + todos/activity/migration/README）与 4 个历史 `config/*.json`（无密钥值）。
  → 写进 `docs/PUBLISH.md`，给出**可回滚的 `filter-branch` 清理步骤**，公开仓库建议执行。

### 新增
- **`.github/workflows/ci.yml`**：Ubuntu+Windows × py3.12 跑静态闸门（`kb_smoke` / `web_check` /
  `web_manifest --check` / `plugin_check --assert-core-only` / `core.plugins verify` / `mcp.server --selftest`）
  + 一个纯逻辑用例作业（`run_tests.py --fast --no-server`）；需要浏览器与真实数据的 25 个用例**只在本地跑**，
  `doctor` 以 `continue-on-error` 输出供参考。**已在本地逐条验证过这些闸门全绿**，CI 不会一上来就红。
- **`.gitattributes`**：`* text=auto` + Windows 脚本保持 CRLF + 二进制不做行尾转换
  （消除"LF will be replaced by CRLF"噪音；实测无大规模行尾改动，只有新增文件）。
- **`docs/PUBLISH.md`**：上线前检查清单、最简上传命令、**清历史的两套命令**（`git bundle` 先备份 →
  `filter-branch` / `filter-repo` → 复核）、上传后本地怎么跑完整档（含性能预算）。
- `.gitignore` 放行 `.github/workflows/*.yml` 与 `.gitattributes`（白名单模式，不放行就进不了库）。

## v261009.39

**前端「日期命名」补丁按功能改名**（第⑤步，可维护性）。

### 改了什么
`web/` 里 10 个 `v260922-*` 文件只记录"哪天的补丁"，看不出职责；现在文件名即职责，且用 `git mv` 保留历史：

| 旧名 | 新名 |
| --- | --- |
| `v260922-performance.js` | **`perf-and-fetch-seam.js`**（性能补丁 + `window.fetch` 接缝提供方） |
| `v260922-performance.css` | `perf-affordances.css` |
| `v260922-compact-layout.css` | `layout-compact.css` |
| `v260922-agent-profiles.css` | `sidebar-agent-profiles.css` |
| `v260922-graph-performance.css` | `graph-page-layers.css` |
| `v260922-layout-bugfixes.{css,js}` | `layout-fixes.{css,js}` |
| `v260922-overview-editor-tools.css` | `overview-editor-tools.css` |
| `v260922-projects.css` | `projects-manager.css` |
| `v260922-research-pages.js` | `research-pages.js` |

同步了**所有功能性引用**：`web/manifest.json`（含缓存键统一升到 `261009ac`，文件名变了键必须变）、
`tools/web_check.py`（加载顺序约束里那个硬编码名）、`tools/web_manifest.py`（文档串）、
以及代码里提到自己文件名的注释。**CHANGELOG 等历史文档不重写**（记录的是当时的事实），
改在 `docs/OVERVIEW.md` 里留一张新旧对照表。

### 验收
- `tools/web_manifest.py --write/--check` 一致；`web_check` 全绿；
- **加载顺序约束仍在**：实测 `index.html` 顺序
  `vendor-lazy → dom-seam → perf-and-fetch-seam → app.js → plugin-host → research-pages → layout-fixes → plugin-manager → manual → external-access`，
  接缝提供方确实排在 `app.js` 之前 ✓；
- `ui_smoke` **19 路由** 全绿（真浏览器加载这些改名后的文件）；
- 全量回归 `tools/run_tests.py`（38 个用例，含浏览器）见下条。

## v261009.38

**新增「设置 → 外部接入」：谁可以改知识库（默认拒绝外部写入）**（第④步，用户要求）。

### 补的是什么缺口
内核自带 Agent 的写工具走**草稿确认闸门**，但**外部通道此前没有闸门**：`mcp/` 的 5 个写工具
（`kb_create_entry` / `kb_update_entry` / `kb_rename_entry` / `kb_change_kind` / `kb_delete_entry`）
**直写知识库**（文档里已如实写明）。现在给外部接入一个"默认拒绝、显式授权"的开关。

### 两个开关（设置 → 外部接入）
| 开关 | 默认 | 管什么 |
| --- | --- | --- |
| `mcp_write` · 允许外部 MCP 客户端写入知识库 | **关闭**（只读） | MCP 客户端的新建/修改/改名/改挂/删除，**不经过界面草稿确认** |
| `plugin_write` · 允许插件写入知识库 | **开启** | 插件经 `core_api.entry_update` 改条目正文/字段；关掉 = **只读工作台** |

- 存储：`config/external-access.json`（独立小文件，不动 `app.json` 既有结构；**原子写**、
  未知键忽略；文件损坏/缺失按**保守值**并如实说明）；
- 只读操作（检索、读条目、看统计、`kb_constraints`）**永远允许**——授权只影响写入；
- 设置在**内核模块** `web/external-access.js`（自登记 `settingsTab`，**不动 `app.js`**），
  状态用 chip 表达（只读/已授权），每项都带说明与 ⚠ 风险提示；
- 闸门落点：`mcp/server.py` 的**分发表**（一处覆盖 5 个写工具）与 `core_api.entry_update`
  （插件写入门面）。插件无需改动，但**写工具仍须声明 `spec.write = true`**。

### 测试（新增 `tests/kernel/test_external_access.py`，17/17）
① 默认保守（MCP 关、插件开、文案齐备）② 读写接口（授权生效、**未知键不能借它塞东西**）
③ MCP 闸门：未授权被拦 + **只读工具不受影响** + 授权后**用非法载荷**证明"闸门放行但没写数据"
④ 插件门面：`plugin_write=false` 时抛 `PermissionError`，恢复后走到「条目不存在」而非写入
⑤ 真浏览器：设置里出现 tab、两个开关、chip 回显、勾选真的写进配置、0 console error
⑥ 收尾恢复原授权状态。

### 夹具当场抓到的真 bug
我在 `handle_tools_call` 里写 `ok, reason = external_access.allowed(...)` —— **遮蔽了协议层的 `ok()` 函数**，
导致所有**只读工具**的成功路径 `UnboundLocalError`（写工具因为提前 return 反而看不出来）。
改名 `allowed` 后 `mcp.server --selftest` 与 ③-2 均通过。

文档同步：`mcp/README.md`（默认关闭 + 如何授权）、`docs/PLUGIN_SPEC.md`（写窗口的显式授权与闸门位置）、
`docs/manual/07-设置运维与边界.md`（设置各栏新增一行）。

## v261009.37

**收口 doctor 可自动处理的 warn + 测试稳定性收尾**（第③步；`doctor` info 6 → 3 条）。

### 做了什么（表格里都是实测前后）
| 项 | 处理前 | 处理后 |
| --- | --- | --- |
| 索引 WAL | **6.91 MB** | **0 MB**（`python -m core.index.maintain --checkpoint`） |
| 索引空闲页 | 17% | **4%**（无需 VACUUM，工具自己给出结论） |
| `Trash/knowledge/` 漂移目录 | 1 个 2026-09-21 的遗留文件 | 已搬出（doctor 该项转 ok） |
| Syncthing 冲突副本 | 1 个 chat 冲突 json | 已搬出（doctor 该项转 ok） |
| `Cache/rag.sqlite` | **69 MB**，全仓 grep **无任何代码读它** | 已搬出 |
| 仓库根 `.rag/` | **92 MB** 早期 RAG 派生索引 | 已搬出（`rag/` 源码保留） |

**全部是"搬出"不是"删除"**：落到仓库外的
`D:\Project\engineering-research-workbench-archive\<日期>-cleanup\`，随时可搬回；
每个待搬路径都先 `Resolve-Path` 打印绝对路径再动（`Workspace/` 是你的数据，不批量重写不顺手统一）。

剩下的 3 条 warn 都是**设计使然或需你拍板**：`契约·字段自洽`（`attachment` 仅 UPDATE 可写）、
`id 前缀与 kind 不符`（契约已明确 id 不承载类型语义）、`不可解析的关联链接`（要你决定补条目还是改链接）。

### 测试稳定性（这一步里被自动化暴露出来的两个真问题）
1. **`test_backup_snapshot` 依赖环境状态**：插件的 `state.json` 守卫"距上次不足间隔就跳过"，
   而该用例假定冷启动 —— 环境里刚备过份就必红（实测 52/52 → 0/1）。
   改为**先清守卫再验启动任务**，收尾把 `state.json` **按字节还原**（`snap_many` 只删新增文件，
   不还原被改写内容——这点也补了注释）；
2. **`test_mermaid` 默认导出会重写入库产物**：每次跑都产生"mermaid 随机 id"噪音 diff。
   改为 **`--export N` 按需导出**，默认只校验不改文件。

另：核对条目数 199 → 201 的来源时确认 `note 90→91`、`summary 4→5`，且**测试无一处直写条目**
（grep `/api/docs` POST、`kb_create_entry` 零命中）——那两条是用户自己的新内容，不做任何清理。

## v261009.36

**把临时夹具落成常驻测试 + 热路径提速 ~100×**（用户要求：按建议顺序执行优化，先做这两件）。

### ① 38 个深度夹具从 `.scratch/tmp` 迁进 `tests/`，并写统一运行器
**问题**：`tools/scratch_clean.py` 默认 7 天清理 `.scratch/`，而 38 个 `verify_*.py`
（指标表 63 项、手册 31 项、备份 52 项、报告导出 43 项、zip 解包 58 项…）是目前**唯一的回归保护网**，
再过几天就会被删掉；仓库里也没有 `tests/`、没有 CI。

**改法**：
- 新建 `tests/{kernel,plugins,docs}/test_*.py`（15/21/2）+ `tests/support/fixture_cleanup.py`（共用还原助手）；
  放"域/文件"两层，原有 `ROOT = parents[2]` 无需改动，迁移面最小；
- 新增 **`tools/run_tests.py`**：自动发现、按 `结果：N/M 通过` 汇总断言数、`--fast`（跳过需要浏览器的 25 个）、
  `--only`、`--list`、`--no-server`、`--timeout`，失败时打印每个用例的尾部输出；
  它还会**自动起一个临时工作台**并把 URL 当 `argv[1]` 传给用例。

**迁移中修掉的 4 个真问题**（都是"自动化之后才暴露"的）：
1. **临时服务 stdout 管道写满导致子进程阻塞**——表现是"连接建立了但一直不响应"，用例多次启停插件时必踩；
   运行器改为后台线程持续排空；
2. `test_plugin_assets.py` 把 `argv[1]` 当**端口**，运行器传的是 URL → 改成两者都收；
3. `test_mermaid.py` 把 `argv[1]` 当**图序号** → 改成识别 URL 并忽略；
4. **三处"侧栏 17 项全量清单"写死断言**：内核新增「使用手册」页后立刻变红（实际 19 项）——
   改为稳健断言（内核页面按 NAV_GROUPS 相对顺序 + 插件项在位 + **不断言总数**），
   "新增页面"不再被误报为回归。另外 `test_plugin_tools.py` 清理用户配置时在 Windows 上会撞
   `PermissionError`（另一进程持有句柄）→ 改为重试 6 次并如实报告。

**结果**：`python tools/run_tests.py --fast` **13/13 用例 · 70/70 断言 · 13 秒**；
全量 38 个用例（含 25 个浏览器用例）**404/408 断言 · 272 秒**（修完上述 4 处后重跑见下）。

### ② `/api/docs` 837ms → 8ms（根因是"每条文档各建一次目录"）
**定位**（cProfile）：`list_docs()` 731ms 里 **0.77s 花在 `ensure_workspace()`**——
`_doc_from_path` **每读一条文档就调一次**，而 `ensure_workspace` 每次要把 ~24 个骨架目录
各 mkdir/stat 一遍（200 条 = 4768 次 mkdir + 5189 次 stat）。

**改法**：
- `app/workspace.py`：`ensure_workspace()` 加**进程级快路径**（同一根路径只确认一次；换根时键不同会重新确认，
  `reset_runtime_state()` 清缓存）。安全性：写路径各自 `mkdir(parents=True, exist_ok=True)`，缓存只影响"读前顺手补齐骨架"；
- `app/store.py`：`_doc_from_path(..., root=None)` 支持传入 root，`list_docs` 在**循环外只取一次**。

**实测**：`store.list_docs()` 731ms → **76ms**；HTTP `/api/docs?paged=1` 837ms → **8ms**，
`/api/docs` 30ms、`/api/dashboard` 30ms、`/api/graph/overview` 13ms。

**防回退**：`tools/performance_benchmark.py` 新增 `--assert-budget`（`store_list_docs ≤ 250ms` 等三条预算），
并修掉它自身一个真 bug（`measure(indexer.graph_overview(80), …)` 传的是结果不是可调用对象 → 该工具此前直接崩）。

## v261009.35

**手册栏目条改用内核既有口径重做**（用户给了「文件夹」树面板作例子：用它改进 UI）。

### 先量参照物，再照做（不凭感觉）
| | 文件夹树行 `.tree-line` | 设置左导航 `.settings-nav button` | 手册目录（改前） |
| --- | --- | --- | --- |
| 高度 | **31px** | padding 10px | 28px |
| 字号 | **12px** | 继承 | 12.5px |
| 圆角 | 6px | **7px** | `0 6px 6px 0`（左侧色条造型） |
| 图标 | 目录 `▱` / 文件 **`·`** | 无 | 无 |
| 选中态 | — | **`--accent-soft` 底 + `--accent-ink` 字** | 自创的左侧 2px 色条 + 淡底 + 加粗 |
| 行内信息 | 悬停才出 `↗` | 无 | 常驻 `3 KB` 噪音 |

### 改法（全部对齐内核既有做法）
- 行：**高 31px、字号 12px、圆角 7px、内边距 0/8、间距 7px**（树行 + 设置导航的口径）；
- 前置 **`·` 图标**——与「文件夹」页树里**文件行**同一符号（目录是 `▱`）；
- 选中态改内核惯用的 **`background:var(--accent-soft); color:var(--accent-ink)`**（同 `.settings-nav button.active`），
  删掉我自创的左侧色条；
- 未选中用 `--muted`、悬停淡底回到正文色（与左侧栏 `.nav-item` 手感一致）；
- **去掉行内 `3 KB` 噪音**，体积只留在 `title` 悬停提示里；
- 左卡片内边距改 **12px**（同 `.tree-panel`）。

实测：目录行 222×**31**、字号 12、圆角 7；左卡片高 387（内容 324，仍贴顶不拉伸）。

### 验收
`verify_manual` **31/31**、`ui_smoke` **19 路由**、`web_check` 绿；
三种窗口阅读列仍居中（500/760/760）、图片与正文同宽对齐、窗口可滚 0、横向溢出 0。

## v261009.34

**手册页比例与栏目条排版**（用户反馈"调整图片大小与文字的比例；调整栏目条 UI 大小与排版"）。

### 图片 : 文字 比例
问题：上一版"正文 700px / 图片 900px"两层宽度，**图片从文字左边冒出去**，图内文字也比正文看着大
（截图 1x 采集，900px 原尺寸显示 → 图内文字 ≈ 页面字号，但图片块比正文宽 200px，比例失调）。

改法：**统一栏宽 760px** —— 正文、标题、图片、表格同一宽度、左边缘对齐；
900px 截图按 **0.84×** 显示，图内文字与正文接近。实测：段落/图片/标题同为 757px、左边缘一致（差 ≤2px）。

### 栏目条（章节目录）
问题：每项一圈边框 + 12px 内边距，8 项下来视觉很重、栏目条被撑高。

改法：改**轻量列表**——去掉整圈边框，当前章用**左侧 2px 色条 + 淡底 + 加粗**表示；
内边距 6/9 → 5/8，项间距 4 → 2px，字号 12 → 12.5px；KB 体积降到 10px/opacity .75（仍可悬停看全称）。
实测条目高 **28px**、目录总高 **239px**（原 ~276px）。

### 验收（三种窗口）
| 窗口 | 面板宽 | 阅读列（居中） | 段落 | 截图 | 窗口滚 / 横溢 |
| --- | --- | --- | --- | --- | --- |
| 1086×965 | 552 | 500（26/26） | 500 | 500/900 | 0 / 0 |
| 1440×800 | 884 | 760（62/62） | 760 | 760/900 | 0 / 0 |
| 1920×1080 | 1340 | 760（290/290） | 760 | 760/900 | 0 / 0 |

仍只滚内容列（窗口可滚 0），页脚钉在视口内；回归 `verify_manual` **31/31**、`ui_smoke` **19 路由**、
`web_check`、`doc_check`（8 图）全绿。

## v261009.33

**手册页版式修复：左卡片不再被拉成空块、阅读列居中限宽**（用户反馈"很难看，且有空白区域"）。

### 量测到的两个真问题（都是我上一版 CSS 写的）
1. **左卡片"标题在上、说明与目录沉到底部"**：我把 `grid-template-rows:auto minmax(0,1fr)` 用在有
   **4 个子元素**的列上，第 2 行 `1fr` 恰好分给了 `h3` → 标题被拉高（实测 h3 高几百像素），
   说明与目录被推到底部，中间一大片空白。
2. **右侧大片留白**：内容限宽后**左对齐**，宽屏下右侧空出几百像素，看起来像"没填满"。

### 改法
- 左列改 **flex + `align-self:start`**（按内容高度贴顶，不再是撑满高度的空卡片）；说明精简为一行并允许换行；
- 阅读列改为**居中**，且分两层宽度：容器 `min(900px,100%)`（让 900px 截图按原尺寸显示）、
  正文与标题 `min(100%,700px)`（行宽可读、标题下划线不会比正文宽出一截）；
- 两处 CSS 坑已写进注释：**用 px 而不是 `ch`**（`ch` 随字号变，h1 的 84ch≈924px 会跟容器一样宽）；
  居中规则必须用 `.manual-body .manual-doc>*` 提权重（`.manual-body p` 的 0,1,1 压过 `.manual-doc>*` 的 0,1,0）。

### 验收（三种窗口 × 两种密度，全部量测）
| 窗口 | 面板宽 | 阅读列（居中） | 段落（居中） | 截图 | 窗口滚 / 横溢 |
| --- | --- | --- | --- | --- | --- |
| 1086×965 紧凑 | 552 | 500（26/26） | 500（26/26） | 500/900 | 0 / 0 |
| 1440×800 紧凑 | 884 | 832（26/26） | 700（92/92） | 832/900 | 0 / 0 |
| 1920×1080 宽松 | 1340 | 900（220/220） | 700（320/320） | 900/900 | 0 / 0 |

左卡片高度 358（内容合计 319）、h3 高 21px（不再被拉高）、标题与说明间距 10px；页脚钉在视口内。
回归：`verify_manual` **31/31**、`ui_smoke` **19 路由**、`web_check` 绿。

## v261009.32

**手册页改为「只滚动内容列」**（用户反馈：滑动条会拖动整个页面，要只拖内容页）。

### 对齐项目既有做法（不是自创）
量测内核各页面发现 house style：两栏页（`.docs-layout` 笔记/文献、`.agent-layout` Agent）
都是**给布局显式高度 + 内部列各自滚**，窗口完全不滚——
`height: calc(100vh - 121px)`（紧凑模式 133），`grid-template-rows: minmax(0,1fr)`。
而我上一版把手册改成整页滚动，量测到窗口可滚 **473px**，外壳被一起拖走。

### 改法
- `.manual-layout` 采用同款：`height:calc(100vh - 121px)`、`html[data-density="compact"]` 下 133、
  行高模板 `minmax(0,1fr)`（≤900px 窄屏回退为整页滚动）；
- **正文列是唯一滚动容器**：`.manual-pane` 网格行分配高度，`.manual-body{overflow:auto;min-height:0}`；
- 页脚（上一章/下一章）钉在列底，翻章始终可见；
- 左列目录仅在必要时自己滚（8 章时不会出现滚动条），不再 sticky。

### 验收（两种密度都量，不靠"看起来没问题"）
| 检查 | 宽松型 | 紧凑型 |
| --- | --- | --- |
| 窗口可滚 | **0px** ✓ | **0px** ✓ |
| 滚动容器 | `#manual-body`（+内核侧栏） | 同左 |
| 页脚位置 | 底 764 / 视口 800 ✓ | 底 740 / 视口 800 ✓ |

拖动验证：正文 scrollTop 0 → 1800 → 400 期间，**窗口 scrollY 恒为 0、侧栏与顶栏 top 恒为 0** ✓。
回归：`verify_manual` **31/31**、`ui_smoke` **19 路由**、`web_check` 绿、截图仍按比例 820px 显示。

## v261009.31

**使用手册页 UI 优化：去掉层叠的滑动条，截图放大到 820px**（用户反馈「不要这么多滑动条」）。

### 量测到的问题（不是猜的）
改前实测该页同时存在**三个滚动容器**：窗口/页面、`#manual-body`（client 707 / scroll 4136 的内层滚动）、
`#sidebar-nav`（内核侧栏，非本页引入）——同一屏右侧能同时看到内外两条滚动条。

### 改法
- **正文不再自带滚动**：去掉 `.manual-body` 的 `overflow:auto`，以及 `.manual-pane` 的
  `max-height` + 网格行约束 → 整页滚动（与其他内核页一致）；
- **目录不再自带滚动**：去掉 `.manual-toc` 的 `overflow:auto` 与 `.manual-side` 的 `max-height`，
  保留 `position:sticky` → 目录吸顶跟随，章节切换始终够得到；
- **截图放开限宽**：`.manual-body>*{max-width:78ch}` 会让含图段落把 900px 截图压到 617px（图里的字变小）；
  改为 `p:has(>img)` 与 `img` 上限 `min(100%,820px)` → 实测截图按 820px 显示且比例不变形。

### 验收（文本量测，不靠"看起来没问题"）
- 滚动容器：除内核侧栏外**无**；横向溢出 **0px**；
- 目录吸顶：滚到 1800/900 px 时 `top` 恒为 10，始终可见；
- 截图：820×579 / 820×712 / 820×693，与原始比例一致（1.416/1.417、1.151/1.152、1.184/1.184）；
- 回归：`verify_manual` **31/31**、`ui_smoke` **19 路由**、`web_check` 全绿。

## v261009.30

**新增「使用手册」：带截图的教程，内置在工作台里可自由翻阅**（侧栏「系统 → 使用手册」）。

### 内容（`docs/manual/`，8 篇 · 13 张截图）
只讲**内核自带功能**（插件功能各自看插件 README，不重复）：
[目录](manual/README.md) → 快速开始 / 知识库条目 / 检索导航与文件夹 / 文献 / 科研 Agent /
项目待办与里程碑 / 设置运维与边界。每篇都是「怎么一步步做」+ 常见问题表，例如：
新建条目的真实流程（点 ＋ 会**立即创建**再改标题，不是弹窗）、命名规范的合法/非法示例、
筛选组合用法、草稿确认流的完整流程（草稿卡 → 确认/拒绝 → direct 重放）、
写模式"取更严格者"的规则、BibTeX 导出与 PDF 目录迁移、数据位置表与备份/恢复步骤。

### 内核侧：手册阅读页（不是插件）
- `web/manual.js` + `web/manual.css`：用 `ERWPanels.register` 自登记侧栏页（**零插件可读**），
  左目录 + 右正文，正文走内核 `ERWMarkdown.renderInto`（与条目编辑器同一套 marked/DOMPurify/hljs/mermaid）；
- `server.py`：`/api/manual`（章节列表）、`/api/manual/<id>`（章节正文，id 收口防穿越）、
  `/manual-file/<rel>`（手册图片，只允许 `docs/manual/**`，越权 403）；
- 站内章节链接在本页直接切章；指向仓库其它文件的链接明确提示而不是静默 404。

### 抓到的真 bug（夹具发现）
站内章节链接点了**没反应**：渲染管线把中文文件名做了百分号编码
（`01-快速开始.md` → `01-%E5%BF%AB….md`），我的比较用的是原始 id → 被判成"仓库文件"分支。
修法：比较前 `decodeURIComponent`。夹具另有两处断言范围错误也一并修正
（首章目录本身没有图与 `.md` 链接，`every()` 在空列表上恒真——**假通过**比失败更危险）。

### 验收
新增 `.scratch/tmp/verify_manual.py` **31/31**：API 7 项（列表/取章/非法 id 404/图片 200/越权 403）、
真浏览器 11 项（侧栏项、目录全章、正文渲染、**图片真实解码且走 /manual-file/**、点目录切章、
高亮、`.md` 链接切章、下一章、0 console error）、**零插件模式下再跑一遍 11 项**（证明手册不依赖插件）。
`ui_smoke` 现在走查 **19 个路由**（内核 14 + 插件页 5，含新的 `#manual`）；`web_check`、`doc_check`(8 图)、
`kb_smoke`、`doctor`(error 0) 全绿。

### 顺手
README 顶部加「使用教程」指路；`docs/OVERVIEW.md` 文档地图补手册入口。

## v261009.29

**新增 `docs/OVERVIEW.md`：项目结构与功能总览（含三张结构图 + 一张导出 SVG）**，并把这个「图必须能渲染」的检查做成正式闸门。

### 文档
- **`docs/OVERVIEW.md`**（当前状态入口）：这是什么 → 三层结构图 → 目录树（标出关键文件行数）→
  数据流图（一次页面请求 / 一次 Agent 工具调用，含草稿闸门）→ 插件生命史图（发现→校验→依赖→启用→
  注册→运行→停用，含 rejected/blocked/failed 三分支）→ 11 个插件一览（提供什么/入口/权限）→
  内核功能清单 → 数据与文件位置表 → 闸门与验证表 → 「想加功能」决策表（哪些不用改内核、哪些要）。
- **`docs/img/structure.svg`**（29 KB）：由 OVERVIEW 的 mermaid 源码导出，供不渲染 mermaid 的查看器；
  另放行 `!docs/**/*.svg`（此前 `docs/` 只放行 `*.md`，图会被 gitignore 吞掉）。
- **README 顶部加指路** + 闸门表补 `tools/doc_check.py`；**`docs/ARCHITECTURE.md` 加历史横幅**：
  它是 v260920–v261008 的实现笔记堆积，多处模块位置已变（`app/rss.py`、`app/weather.py`、
  `app/kb_naming.py`、`web/literature.js`、`web/v260930-floating-agent.*` 都已搬进 `plugins/`），
  指向 OVERVIEW 作为当前状态。

### 新闸门：`tools/doc_check.py`
用**仓库自带的 `web/vendor/mermaid.min.js`** 在真浏览器里逐张 `parse()` + `render()` 文档中的 mermaid 图，
可选 `--export <file> <index>` 导出 SVG。**每张图用全新页面渲染**——mermaid 是单例，同页连续渲染会互相污染，
产生与图本身无关的假失败（实测踩到）。

### 它当场抓到的真 bug
README 的架构图（本次新画）**渲染报错**：`Cannot set properties of undefined (setting 'order')`。
用变体法定位到根因不是「子图↔子图」边，而是**给「子图」参与画边**（`FE --> SV`、`HOST --> PLG` 这类）——
当前 vendored mermaid 版本在这个构造上会崩。改法：**子图只作视觉分组，边一律节点→节点**；
改完 README 架构图正常渲染（75 节点 / 98 连线）。全仓 8 张 mermaid 图现在 8/8 通过。

## v261009.28

**重新梳理 README（项目结构与功能总览）**——只改文档，不动代码。

- **架构图重画**：原图把 `app/rss.py`、`app/weather.py` 画成内核模块（它们早已搬成插件），
  也没有 `core/`、`core_api.py`、插件层。新图分四块：**前端内核 / 插件 / 内核 core / 后端 app + 数据**，
  并标出插件经 `ctx.routes`、`ctx.mcp.tool`、`ctx.jobs`、`core_api` 四条通路接触内核。
- **新增「🧩 插件体系」章节**：内核/插件/数据三层职责与硬约束表、插件能做什么（10 类自登记接缝）、
  **11 个插件一览**（提供什么 + 默认开关）、安装/启停/预览方式。
- **三处功能章节标注归属**：科研资讯（`plugins/rss`）、天气（`plugins/weather`）、专注计时（`plugins/focus`）
  现在都是插件——原描述的行为不变，但内核里已经没有它们的代码，停用后对应入口消失。
- **开发目录树重写**：按 `app/`（19 模块，标出关键文件行数）、`core/`（契约/索引/插件运行时/体检/事件/出网）、
  `core_api.py`、`plugins/`（11 个 + 模板）、`web/`（壳 + 插件宿主 + 装配清单 + vendor）、
  `mcp/`、`tools/`、`config/`、`Workspace/` 重排，并补上**闸门脚本表**（8 个脚本各管什么）。
- 后端模块小节里 `app/rss.py` / `app/weather.py` 两节改标为 `plugins/rss/backend.py` /
  `plugins/weather/backend.py`（原 `app/…`），说明职责不变、位置已变。

## v261009.27

**插件设置页的「演示预览」**：鼠标移到插件卡片（或点击「预览」行）即可看到这个插件的**摘要 + 功能点 + 界面截图**，不用读文档。

### 内核侧（只负责呈现，仍然不认识任何具体插件）
- `plugin.json` 新增可选字段 **`preview`**：`{summary, features[], where, screens[]}`（PLUGIN_SPEC §3）。
  校验为 `P022`**警告**级（形状不对只提示、不拒载）；截图路径必须是插件目录内的相对路径且文件存在，否则给警告。
- `/api/plugins?detail=1` 下发 `preview`（截图 URL 走既有 `asset_url`，**带文件 mtime 缓存键**——换了截图浏览器必然重新取）；
  仅在真有内容时下发：空对象在 JS 里是真值，会把"没声明预览"的插件也画出一行（实测踩到并修）。
- 设置页 UI：卡片多一行「预览」；**悬停浮出**、**点击固定**、再点/Esc/点浮层外收起；
  浮层贴卡片右侧（放不下转左侧，并夹在视口内），**滚动时跟随卡片**（移出视野才收起）——
  一开始写成"一滚就收"，结果 `hover` 先把卡片滚进视野、浮层刚建出来就被自己收掉（夹具抓到的真 bug）。
- CLI `python -m core.plugins check <id>` 也打印预览摘要与功能点，作者能自查。
- **未启用的插件同样能预览**（这正是最需要预览的时候），浮层里明确标注"未启用"。
- 顺手修 `tools/web_check.py`：把 `mouseenter`/`mouseleave` 等标准 UI 事件加入白名单——
  此前它把标准事件误报成「没人派发的自定义事件」。

### 插件侧：11 个插件都补了预览
每个 `plugin.json` 写清 `summary`（一句话讲清解决什么问题）、`features`（能做什么，3–6 条）、
`where`（在哪找），并用 **Playwright 元素级截图**生成 `web/preview.png`：只截该插件自己的界面区域，
1x、宽 ≤760px、高 ≤700px（超高取顶部），元素级截图后按像素统计确认不是空白页。11 张共约 1.3 MB。
- `.gitignore` 放行 `plugins/**/web/preview*.png`（否则截图进不了版本库，别人装了就看不到预览）。
- 两个特例的处理：**槽位类插件**（顶栏天气）只截元素会得到一条 32px 细条，改为截它所在的顶部区域；
  **浮层类插件**（悬浮球）先点开球再截它的面板；**接管型插件**（图谱、阅读区）分别截图谱页与阅读区。

### 验收
- 新增 `.scratch/tmp/verify_plugin_preview.py` **19/19**：11 个插件都下发 `preview`、11 张截图 HTTP 200；
  真浏览器里悬停出浮层（含插件名/摘要/功能点/**图片真实解码** naturalWidth>0/"在哪找"）、
  移开消失、点击固定、Esc 收起、**未启用插件也能预览并提示未启用**、
  **删掉 preview 的对照组不出现预览行**、全程 0 console error、`plugins.json` 未被改动。
- 回归：`verify_plugin_tools`、`verify_metrics_table` 63/63、`verify_plugin_template` 49/49、
  `verify_report_export`、`verify_backup_snapshot` 52/52、`verify_calendar` 32/32、
  `verify_zip_unpack` 58/58、`verify_zip_install_http` 27/27、`verify_plugin_manager`；
  `web_check`、`plugin_check --assert-core-only`、`ui_smoke`、`kb_smoke`、`doctor`、`mcp.server --selftest` 全绿。

## v261009.26

**指标表重做：直接读你现有的正文表格**（上一版要求先改写正文，所以打开是空表——你说「没看出作用」是对的）。

### 问题与根因
v1.0 只认自己那套 ````metrics` 块约定。实测你的 25 条实验里 **0 条**有该块，于是页面只能显示空表 + 格式提示。
而同一批条目里其实**躺着大量指标**：`实验-多模型基线对照（2.2）` 有 61 行表格（`| 排名 | 模型 | #Params/M | FLOPs/G | mIoU_mean | Pd_mean | Fa_mean |`，9 个模型 × 6 项），
还有逐数据集 mIoU 矩阵。**要求用户先改数据才能看到价值，是设计错误。**

### 改法：把「现有正文」变成一等数据源
- **Markdown 表格直接吃**：一张表只要有「数值列」就按行展开成记录——表头 = 指标名；
  **对象列自动识别**（第一个非数值列，`排名` 这种序数列会跳过；非数值列如 `参数量出处` 作为附带信息保留）；
  小节名取自表格上方最近的标题。映射表（无数值列）自动跳过。
- **`metrics` 块保留**（规范形式，适合手写几项指标），两者默认都开、可在设置里关。
- **呈现方式重做**：一张来源表 = 一个分组（表头 + 行 + 列统计），不再把所有表的列摊成一张 75 列的宽表；
  **按对象透视**把同名对象（同一模型/方法）在不同实验的数字并到一行（`mIoU_mean@2.2`、`FA@2.1`…）——这才是跨实验对照。
- 关键词同时过滤行与列；「指标列最少出现」阈值可收敛走廊；点行显示**来源**（条目 + 小节 + 表格/块）与该行全部指标。
- 修两个解析缺陷：序数列（`排名`/`编号`）不再当指标列；**对象列必须按「是否数值」判断**（否则会把 `排名` 当对象列，对象读成 1/2/3）。

### 在**你的真实数据**上的实测（这就是「作用」）
| 指标 | 实测 |
| --- | --- |
| 扫描 | 25 条实验条目 → **174 条记录**（全部来自正文表格，零改写） |
| 明细分组 | 来源表 ≥8 张，单表最多 15 列（可读） |
| 关键列 | `mIoU_mean` 9 个模型有值，最优 **0.7545**（DNANet）；`#Params/M` 0.2166–50.5403；`Pd_mean` 0.532–0.9588 |
| 透视 | **DNANet 同时出现在 2.1 与 2.2**（`FA@2.1` 与 `Fa_mean@2.2` 并排），113 个对象 |
| 可追溯 | 每行标明来源条目与小节（如「2.1 参数量与三数据集均值排行」） |

### 验收（`.scratch/tmp/verify_metrics_table.py`，**61/61**）
- 逻辑（内存注入）：块解析、数值拆解（百分比/科学计数/单位/加粗/非数值）、写入（追加/merge/replace/正文逐字保留/幂等/拒绝写）、
  **表格提取**（数值列、对象列跳过排名、映射表跳过、按行展开、附带信息、实验短名）、聚合与透视、CSV/MD。
- **真实数据**（只读）：记录数、来源分布、DNANet 的 `mIoU_mean=0.7545`、透视跨实验、单表列数、序数列不算指标。
- 真服务器：路由、透视模式、CSV/MD 导出含真实模型与指标、**写工具 confirm 只出草稿且条目一字未改**、拒绝草稿同改。
- 真浏览器：摘要非零、表格里能看到 **DNANet / mIoU_mean**、透视带 `@2.2`、关键词过滤生效、点行显示来源、0 console error。
- 回归：其余 9 个夹具与 `web_check`/`plugin_check`/`ui_smoke`/`kb_smoke`/`doctor`/`selftest` 全绿；插件 **11 个可用**。

## v261009.25

**数据表化按「插件」实现**（你的要求）+ 顺手修掉上一轮三个插件的真缺陷。

### `plugins/metrics-table`（指标表，v1.0.0）：不动内核契约的数据表化
- **不新增 kind**：kind 矩阵是内核契约（`core/contracts/kinds.py` 是唯一声明处），为数据表化新增 kind
  等于把功能搬进内核（存放目录/标题前缀/状态机/正文骨架/字段契约/索引/命名校验全要改）。
  改为**指标写在条目正文的 `metrics` 围栏块里**（`键: 值` 一行一项）——于是它自动被全文检索、
  图谱、报告导出与备份覆盖，任何 kind 的条目都能带，零内核契约改动。
- **汇总视图**：列 = 指标键并集（按首次出现排序）、**缺项显式标出**（单元格 `—` + 行尾缺项清单）、
  列统计（min/max/mean、单位识别 `%`/`M`/`ms`、非数值项计数）、可按项目与类别收窄；
  单条详情显示指标、解析警告与正文预览。
- **导出**：CSV（带 BOM，Excel 打开中文不乱码）与 Markdown，走 `ctx.raw` 原样下载（复用 v261009.23 的接缝）。
- **写入只有一条路**：写工具 `p_metrics-table__record_metrics`（`spec.write = true`）→ 内核 confirm 模式
  只生成草稿，用户确认后才以 direct 模式调用 handler → handler 走**新增的** `core_api.entry_update`
  （内核的校验写入路径：字段白名单取自 `core/contracts`、原子写、记 `doc_update` 活动）。
  面板**不提供**"直接改条目"的按钮，只读 + 导出 + 提示。
- **容错**：块未闭合、行无法解析、键为空都只记 `warnings` 并在页面提示；已有块未闭合时**拒绝写入**
  （不让正文被改坏）；`merge` 保留未提到的键，`replace` 整体覆盖，正文其余部分**逐字保留**。

### 顺带修掉的真缺陷（都在上一轮新插件里）
- **插件工具签名不匹配（真 bug）**：内核用 `handler(args, call_ctx)` 调用插件工具，而我上一轮交付的
  `report-export` / `backup-snapshot` / `milestone-calendar` 都把 handler 写成了 `def tool_x(args)`
  ——经 Agent 调用会 `TypeError`。已全部改为 `(args, call_ctx=None)`，模板里也加了醒目注释。
  **为什么之前没发现**：那些夹具直接调 `handler(args)`，绕过了内核的真实调用路径。
- **夹具盲点补上**：`verify_plugin_tools.py` 扩了一节「真实插件：每个工具的 handler 都要符合内核调用约定」——
  用 `loader.load(enabled_only=False)` 装载**全部**插件（含默认不启用的），对每个工具做
  `inspect.signature(...).bind({}, {})` 静态判定（精确、零副作用），并检查工具元信息与 `write` 标记一致、
  后台任务可见、**装载期间不产生快照**（先临时关掉备份插件的自动开关，事后按原样恢复配置）。
- **`metrics-table` 自己的 bug（夹具抓到）**：替换已有块时把闭合围栏的**相对偏移**当成绝对偏移，
  截断了正文尾部；已修并有「正文逐字保留」断言守着。

### 验收（`.scratch/tmp/verify_metrics_table.py`，**47/47**）
- 逻辑（内存注入，不碰知识库）：多块后者覆盖、注释/空行/`=` 写法、未闭合块、坏行只记警告；
  数值拆解（百分比/科学计数/单位/千分位/非数值）；写入（追加/merge/replace/**正文逐字保留**/幂等/拒绝写）；
  聚合（列并集与顺序、filled/missing、单位、min/max/mean、非数值计数、无指标条目排除）；CSV/MD 导出。
- 真服务器：表格路由、单条查询、CSV/MD 下载（`ctx.raw` + RFC 5987 文件名）、写工具标记正确，
  以及**关键安全断言**——`confirm` 模式下条目正文**一字未改**、`reject_draft` 后仍未改、夹具产生的草稿清理干净。
- 真浏览器：页面渲染、空态给出块格式提示、导出链接、类别下拉、写入方式说明、0 console error。
- 回归：`verify_plugin_tools`（含新节）、`verify_backup_snapshot` 52/52、`verify_calendar` 32/32、
  `verify_report_export` 42/42、`verify_plugin_template` 49/49、`verify_zip_unpack` 58/58、
  `verify_zip_install_http` 27/27、`verify_plugin_manager`；`web_check`、`plugin_check --assert-core-only`、
  `ui_smoke`、`kb_smoke`、`mcp.server --selftest` 全绿；`doctor` error 0、warn 6；插件 **11 个可用**。

## v261009.24

**插件生态收官：内核补上后台任务能力（`ctx.jobs`）+ 两个生态插件**（你选的「定时备份/快照」与「日历/提醒」，三个都完成了）。

> 本节属**插件生态任务**那条线（v261009.x 序列）；同日本仓库另一端还有一条 UI 打磨线用 v261010.x 序列，
> 两节各自独立、互不覆盖——编号不跨序列比较。

### 内核：`ctx.jobs` 后台任务（PLUGIN_SPEC §6.2 ③ 的第一个缺口 → 关闭）
- 新增 `core/plugins/jobs.py`（约 240 行）：内核起**唯一一个调度线程**，按间隔调用插件注册的任务回调。
  - **I4 单任务失败不影响别的**：回调异常只记进该任务状态（`last_error`/`failures`）并打日志，调度继续。
  - **同一任务不重入**：上一轮没跑完就跳过（慢任务不会再堆成并发）；**每个任务独立线程**，卡住的任务不拖调度器。
  - **不做强制超时**：Python 无法安全中断线程——"超时"只做到「状态可见 + 不重入」；需要强隔离的任务该做成 `kind:"process"` 插件（那是另一个缺口）。
  - **热重载安全**：`loader.load` 每次装配先 `jobs.replace()` 停掉旧调度器再建新的 → **停用插件后它的任务立刻不再被调度**（夹具专门验这条）。
  - **进程退出兜底**：`shutdown()` 幂等 + `atexit`。
- `ctx.jobs.add(name, cb, every_minutes=…, run_on_start=False)` / `ctx.jobs.list()`；每插件最多 8 个任务，重名/非正间隔在注册期即报错（早失败）。
- manifest 的 `jobs` 字段**首次真正被校验**（新增 `P021`：必须是数组、每项要有合法 `id`、`interval_min` 必须是正数）——此前它只活在文档里。声明与注册不一致时加载期提示，不拒载。
- `context.py` 的模块说明同步：`ctx.jobs` 从「尚未实现」移入已实现表；缺口只剩 `ctx.search.addSection` 与 `process` 执行层。

### 插件 `plugins/backup-snapshot`（备份与快照，v1.0.0）
- 把**知识库本体 + 系统状态 + 配置**打成带 `manifest.json` 的 zip；默认只收小体积关键数据，
  **附件（PDF/图片/办公文档）、项目数据、派生索引默认不收**，三项可在面板打开。
- **自动备份由内核调度**（`ctx.jobs`）：回调先比对 `state.json` 里的上次时间 → 不足间隔就跳过，
  所以「重启工作台」「在设置页开关插件」都不会连点出多余备份。
- **原子收尾**（`.part` → rename）、**只清理本插件生成的 `snapshot-*.zip`**（目标目录里别人的文件一个不碰）、
  目标目录可外置（默认在插件命名空间，面板明确提示"同盘只防手滑"）。
- 面板：状态（目录/份数/上次时间）、立即备份、快照列表（下载 / 查看内容 / 删除）、范围与保留设置；
  两个 Agent 工具 `snapshot_now` / `list_snapshots`。**不做自动恢复**（覆盖用户数据必须由人确认，只给"查看内容 + 下载"）。
- **夹具抓到并修掉两个真 bug**：
  1. 默认范围沿 `Workspace/Knowledge/**` 递归时把 **295 MB 的 PDF**（`Attachments/` + `Literature/PDF/`）也收了进去，
     "小体积快照"当场失效。现在按**重文件后缀 + 可重建目录**（`Cache`/`Exports`）挡住，并如实记录跳过类别。
  2. 秒级时间戳 + 无串行化 → 自动任务与手动请求同秒发起会争同一个 `.part`（实测 500）。
     现在**一次只允许一份快照在跑**（拿不到锁返回可读拒绝）、文件名冲突加序号、临时名带随机串、保留排序改用 mtime。

### 插件 `plugins/milestone-calendar`（日历与提醒，v1.0.0）
- 汇总**里程碑 `due`** 与**待办 `due`**，分桶 `逾期 / 今天 / 近期（窗口可配）/ 稍后 / 无日期`。
- **两个自登记点**：侧栏「日历提醒」（月历，每周一起始，点某天看当天明细 + 四段清单）与
  **顶栏槽位角标**（`nav[].slot = "topbar"`：`⚠ 逾期数` / `◔ 今日数`，无到期项显示 `✓ 到期`，切页仍常驻）。
- 刻意**不做系统通知**：内核没有通知通道；与其做会漏的假提醒，不如把到期情况做成常驻角标
  （每 5 分钟自刷、切回标签页立即刷新）。真要做推送，应先在 §6.2 ③ 加一条通知能力。
- Agent 工具 `p_milestone-calendar__agenda`；只读知识库与待办，只写自己的配置。
- `core_api` 新增 `todos(include_done=…)` 与 `kernel_version()`（后者让插件不必为了读 VERSION 去 `import core.*`——那是 I3 边界）。

### 顺带说清/修正
- **`data-plugin` 的语义写明了**：容器上写的是**面板 id**。此前文档写 `<id>`，一个插件登记两个面板
  （页面 + 顶栏角标）时按插件 id 写的 CSS 只覆盖页面那个，角标会掉样式——`milestone-calendar` 实测命中，
  已改为前缀作用域并在 §6.1 写明三种容器各写哪个 id。

### 验收（两个新夹具，全绿）
- `.scratch/tmp/verify_backup_snapshot.py` **52/52，连跑三次确定性通过**：自动任务真跑且状态可见、内容正确
  （含清单/知识条目/不收附件、快照 <30 MB 而附件 295 MB）、幂等（重启不连点）、保留策略只删自己的文件、
  外置目录、下载/查看/删除、6 种越权路径被拒、**热重载后任务立刻消失**、并发只成一份且另一份是可读拒绝、真浏览器 5 项。
- `.scratch/tmp/verify_calendar.py` **31/31**：分桶与夹具**独立复算逐项对齐**、每个桶的谓词成立、已完成项不出现、
  改窗口按新窗口重算、Agent 工具口径一致、真浏览器（月历 42 格 / 点某日 / 改窗口 / **顶栏角标出现且样式命中** / 切页常驻 / 0 console error）。
- 回归：`verify_report_export` 42/42、`verify_plugin_template` 49/49、`verify_zip_unpack` 58/58、
  `verify_zip_install_http` 27/27、`verify_plugin_manager`；`web_check`、`plugin_check --assert-core-only`、
  `ui_smoke` 17 路由、`kb_smoke`、`mcp.server --selftest` 全绿；`doctor` error 0、warn 仍 6；插件 **10 个可用**。

## v261009.23

**第一个生态插件：`plugins/report-export`（报告导出）+ 它需要的内核接缝**（你选的「报告导出 DOCX/PDF」）。

### 交付文档：三种格式，零第三方依赖
- **DOCX**：用**标准库**写 OOXML（`zipfile` + 手写 `word/document.xml` / `styles.xml` / core props）。理由是本机实测**运行时 Python（Miniforge）没有 `python-docx`**，也没有 LibreOffice——若依赖它们，插件就必须让用户先装东西，违背「丢进去就能用」。`.docx` 本质是装 XML 的 ZIP，标准库足以写出 Word/WPS/LibreOffice 都能正常打开的文档。
- **HTML → PDF**：同一份内容渲染成自包含 HTML（带打印样式），页面提供「打印 / 另存为 PDF」，`view?print=1` 自动唤起打印。中文与字体交给系统处理，效果比任何纯 Python 方案都好，同样零依赖。
- **Markdown**：便于再加工（贴进别的工具、进版本库、被 diff）。
- 报告内容：范围（项目 / 某类条目 / 全部）→ 按**契约顺序**分章 → 每条目（标题 + 状态/项目/标签/日期 + 正文的轻量降级渲染）。正文 Markdown 只做"能读懂"的降级（标题/列表/引用/代码块/段落/表格行），保真度交给 HTML 与 Markdown 格式。

### 内核侧新增两个接缝（都是纯增量，`api_version` 不变）
1. **`ctx.raw(body, content_type=…, filename=…)`**（`core/plugins/context.py` + `loader.dispatch` + `server.send_raw`）：插件路由的**原样响应**——此前插件路由只能返回 JSON，`json_safe` 会把 `bytes` 变成字符串，**插件根本无法产出文件**（导出、备份下载、图表都是这一类）。现在 handler 返回 `ctx.raw(...)` 时不包装，内核直接写字节与响应头，中文文件名按 RFC 5987（`filename*=UTF-8''…`）编码。
2. **`core_api` 只读数据窗口**（`entry` / `entries` / `projects` / `project_names` / `dashboard` / `kind_labels` / `kind_order`）：与 `lit_*` 同一模式，把知识条目、项目、总览统计与**契约里的中文标签**递给插件。此前插件要用知识库数据只能自己读 `Workspace/Knowledge/*.md`（绕过索引会看到过期/半写状态）。实测与 HTTP 公开 API **同源同量**：`entries()` 199 = `/api/docs` 199，按类别 25/67 一致，跨页 130 条无重复。
   - `kind_labels()` 的意义与前端 `ERWContract` 相同：插件**不要**再抄一份中文标签表，权威声明仍在 `core/contracts/kinds.py`。

### 插件本身
- **页面**：侧栏「报告导出」（自登记在「研究 · 知识」组，图谱之前）——范围选择、选项（收录正文/元信息/分章节/上限）、预览清单、三个导出按钮、下载与打印链接。样式全部落在 `[data-plugin="report-export"]` 内。
- **Agent 工具**：`p_report-export__list_scopes`（列范围与格式）、`p_report-export__export_report`（按范围导出并返回文件名与目录）。
- **只写自己**：导出件落在 `Workspace/Plugins/report-export/exports/`，不改任何知识条目，因此**不是写工具**、不走草稿闸门；下载/预览做路径安全校验（只允许导出目录内的文件，拒绝 `..`、盘符、子目录）。
- 顺手修：报告文件名原先含空格与 `·`，返回的 URL 也没做百分号编码（会造成 `URL can't contain control characters`）——现在文件名归一为 `标题-时间戳.ext`，URL 一律百分号编码。

### 验收（`.scratch/tmp/verify_report_export.py`，**42/42**）
- 范围取数与 `core_api` 逐项对齐；三格式导出；**DOCX 用带 python-docx 的捆绑解释器做独立裁判**（能打开、段落数与条目量相称、用到 Heading 样式）+ OOXML 部件齐备 + `document.xml` 是合法 XML；`ctx.raw` 的 Content-Type / RFC 5987 / 字节一致 / 不带 JSON 包装；4 种越权下载路径全部被拒且不泄漏文件；真浏览器走查（导航项、范围、预览、页内导出、0 console error）；收尾把 `plugins.json`、`config/plugins/*`、`Workspace/Plugins/*` **按原样恢复**并断言。
- 回归：全套闸门（`plugin_check --assert-core-only`、`web_check`、`ui_smoke`、`kb_smoke`、`doctor`）与既有夹具（`verify_plugin_template` 49/49、`verify_zip_unpack` 58/58、`verify_zip_install_http` 27/27）全绿；插件 **8 个可用**。

## v261009.22

**插件生态地基：模板 + 脚手架 + 挂载点作用域 + 兼容性承诺**（回答你的四个问题，逐条给了实测证据）。

### ① 内核预留接入基础 —— 已成立（实测）
- 从零生成一个全新插件，**内核源码零改动**即可被发现、启用、提供导航页/设置页 tab/HTTP 路由/Agent 工具/自有配置。夹具用「内核源码里搜不到该插件 id 与显示名」来证明这一点（`.scratch/tmp/verify_plugin_template.py` ④）。

### ② 插件模板 —— 新增
- **`plugins/.template/`**：一个**能直接跑**的最小插件（5 个文件），演示清单字段、`register(ctx)`、自登记导航页 + 设置页 tab、`window.erwFetch` 调自己的后端、`ERWContract`/`ERWToast` 空值保护、`[data-plugin]` 样式作用域；`README.md` 同时是模板说明书与新插件的起点（改哪四步、怎么验证、隔离边界、7 个真实插件的阅读索引）。
- **`tools/new_plugin.py`**：`python tools/new_plugin.py my-tool --name "我的工具"`。渲染占位符（`__ID__`/`__NAME__`/`__DESC__`/`__ICON__`/`__CORE_MIN__`）、**先临时后原子**（渲染到 `.staging/<id>/`、用安装期同一套校验器验过才改名）、默认拒绝覆盖、`--force` 把旧目录整体挪进 `.backup-*`（不删不合并）、`--dry-run` 不落盘、一律写 UTF-8 无 BOM。`--core-min` 默认取**当前内核版本**。
- 点目录约定：`.template` 不会被当成插件（`discover` 本来就跳过点目录；这次让 `tools/web_check.py` 与 `tools/ui_smoke.py` 也跳过，否则模板里的示例脚本会被算成"接缝提供方"，掩盖真实缺口）。

### ③ 加入插件不动内核 UI —— 已成立，并补齐一处规则落地
- **挂载点带 `data-plugin=<id>`**（`web/app.js`）：此前只有**槽位容器**有这个属性，而 §2 要求 `panel.css` 按它作用域——导航页（拿到的是内核共用 `#main`）与设置页 tab 根本拿不到，那条规则对它们**落不了地**。现在导航页 `#main`、设置页 `#settings-panel` 也带该属性，且**每次导航/切 tab 先清掉上一轮的值**（插件 CSS 不许泄漏到内核页面）。
- 夹具用 computed style 反向验证：插件 CSS 的 `borderTopWidth` 真的生效（拿不到属性的旧行为会是 `0px`），切回内核 tab/页面后属性被清掉、0 console error。

### ④ 内核可扩展、改动不"一改废掉全部插件" —— 写明边界 + 补两个真缺陷
- **PLUGIN_SPEC §13.3「兼容性承诺」**：`api_version` 只在破坏性变更时 +1（新增接缝/字段/槽位都不动它）；不匹配**明确拒载**而非尽力而为；接缝只增不删；`core_min` 是插件侧下限； **`plugins/.template/` 即回归夹具**——模板随内核演进而失效时夹具会红，比"文档说没问题"可靠。
- **修缺陷 A（预览会说谎）**：设置页预览接口用**空版本号**解析候选（`resolve(candidates, "")` 跳过了 `core_min` 检查），于是"内核版本过低"的插件在设置页显示**可用**，启用后却被加载器拒载（静默失效）。改为用真实内核版本解析。
- **修缺陷 B（装不上的插件从页面消失）**：`/api/plugins?detail=1` 一律跳过非 `available` 的候选，导致内部版本过高/缺依赖的插件在插件页**完全看不见**（用户只看到"还没发现任何插件"），而 CLI 明明给得出原因；前端 `cardHtml` 本来就写好了显示 `state/reason`。现在 detail 模式的载荷如实列出 `rejected/blocked/conflict` 及原因，普通清单（脚本宿主用）仍只给"可用且启用"。
- **顺手修文档漂移**：`core/plugins/context.py` 的模块说明还写着 `ctx.events`「尚未实现」，而它早已实现且 billing 正在用——插件作者最先读的就是这段，已改为列出真实缺口（`ctx.jobs`/`ctx.search.addSection`/`process` 执行层）。
- **`verify` 顺带诚实**：`core.plugins.report` 现在会提示 `System/plugins.json` 里"插件已不存在"的孤儿记录（否则同名插件重装后会**默默继承**启用状态）。

### 验收
- 新增 `.scratch/tmp/verify_plugin_template.py` **49/49**：脚手架（生成/占位符/无 BOM/校验/拒绝覆盖/`--force` 备份/dry-run）+ 零内核引用 + 真服务器（发现→默认未启用→未启用时路由 404→启用→路由/工具/配置齐备）+ 真浏览器 12 项 + 收尾清理（含按原样恢复 `System/plugins.json`）。
- 回归：`verify_zip_unpack` 58/58、`verify_zip_install_http` 27/27、`verify_plugin_manager`、`web_check`、`plugin_check --assert-core-only`、`ui_smoke` 17 路由、`kb_smoke`、`mcp.server --selftest` 全绿；`doctor` error 0、warn 仍 6；插件 **7 个可用**；`web/index.html` 缓存键已同步（app.js → `261009t`）。

## v261009.21

**补上阶段 1 的最后一项：单文件包（`.zip`）自动解包**（你选的「完整实现」）。至此 SCOPE §6 阶段 1「地基」五项全部完成。

- **新增 `core/plugins/unpack.py`**（≈390 行），按 PLUGIN_SPEC §2 六条规则逐条实现：
  - **① 先临时后原子**：解到 `plugins/.unpack-<id>-<version>/` → 校验 → `rename` 成 `plugins/<id>/`（同盘原子），任何时刻不存在半解包状态；崩溃残留的临时目录超过 24h 自动清理。
  - **② 一包一插件**：`plugin.json` 必须在包根；只在子目录里有清单 → 拒收并指出「在 `xxx/` 里」（这条最容易被做包的人踩）。
  - **③ 目录名 = manifest id**：落点由 manifest 的 `id` 决定、**与包文件名无关**（随手重命名包不会造成"文件夹叫 A、插件自称 B"）。
  - **④ 版本替换不合并**：旧目录**整体**移入 `System/Trash/plugins/<id>-<旧版本>/`，绝不逐文件覆盖；同名回收站已存在时再加时间戳，不砸旧东西。
  - **⑤ 不覆盖用户手改目录**：靠目录里的 `.erw-unpacked` 标记区分「解出来的」与「手放的」——手放目录遇到同名包只报冲突，**一个字节都不动**。
  - **⑥ 路径安全**：拒绝绝对路径/盘符/UNC、`..` 穿越、符号链接条目，落点必须严格在目标目录内；另加**条目数 ≤ 20000 / 解压后 ≤ 512 MB / 解压比 ≤ 200:1**（zip 炸弹）。
- **「发现」与「安装」彻底分成两个函数**（这是本轮最关键的架构决定）：
  - `registry.discover()` / `report()` 现在**结构上只读**——`tools/plugin_check.py` 与每个插件请求路径（`/api/plugins/*` 转发、插件静态资源）都在调 `discover`，审计工具和热路径绝不能顺带安装东西。
  - 写盘只发生在显式调用 `registry.install_packages()` 的**三个用户可见时机**：服务启动（`loader.load`）、打开设置页插件页、CLI `list --install`。
  - 验收里专门断言这条：`discover`/`report` 跑完目录快照逐字节不变；启动后新丢进来的包，`GET /api/plugins`（每次页面加载都调）不会解包。
- **设置页把结果如实显示出来**（`web/plugin-manager.js` + `.css`，新增 `.pm-notes` 区块）：内核以结构化 `install` 字段下发每条结果（包名/id/版本/动作/原因），页面按成败标色显示「已解包安装 / 已升级 / 已是该版本 / 拒收 / 冲突」+ 原因；**一个插件都没有时也显示**（原来那种"丢个 zip 进来毫无反应"正是要消灭的形态）。
- **验收**（两个新夹具，共 80 项，全绿）：
  - `.scratch/tmp/verify_zip_unpack.py` **53/53**：正常解包/嵌套清单/落点由 id 决定/manifest 不过/缺件/版本替换进回收站/幂等/手放目录不被覆盖/无工作区拒改/穿越与盘符与符号链接/炸弹上限/僵尸临时目录/只读根/只读保证/CLI/坏包隔离。
  - `.scratch/tmp/verify_zip_install_http.py` **27/27**：启动即安装、启动后新包对普通请求不可见、设置页安装并结构化上报、二次请求幂等、手放冲突，以及**真浏览器**确认页面渲染（成功项标绿、拒收项标红带原因、高度合理、0 console error、空列表分支）。
- **顺手修掉一个自己引入的交叉缺陷**：插件升级把旧版移进 `System/Trash/plugins/<id>-<版本>/`，而 `core.doctor` 的「回收站目录漂移」检查只认 `KINDS`——插件一升级就会多出一条新告警。修法是**在契约里声明**：`core/contracts/kinds.py` 新增 `TRASH_EXTRA = ("plugins", "Literature", "Projects")`（都是代码里真实存在的非 kind 回收站命名空间：插件、文献、项目），`doctor` 改用 `KINDS + TRASH_EXTRA`（大小写不敏感）。夹具里**双向**断言：`plugins` 不算漂移、`bogus_ns` 仍被抓到——既有那条合法的 `knowledge` 告警保持不变（那是历史遗留，不该顺手抹掉）。
- **文档同步**：PLUGIN_SPEC §2 的「规格已定、未实现」横幅改为「已实现」并写明三个触发时机与安全上限、§5 安装行与 CLI、§12 P-B、§306 校验清单；SCOPE §6 阶段 1 收尾；`plugins/README.md` 补齐包态说明（标记文件、回收站、三个时机）；AGENTS.md 仓库表的 `core/plugins/` 模块清单加上 `unpack`（本机指令文件，不入版本库）。
- 回归：`verify_plugin_manager`（设置页插件管理，前端被改）全部通过、`web_check`、`plugin_check --assert-core-only`、`ui_smoke` 17 路由 0 error、`kb_smoke`、`mcp.server --selftest` 全绿；`doctor` error 0、warn 仍为 6（未新增）；插件仍 **7 个可用**、工作树干净。

## v261009.20

**完成情况审计（回答「检查任务完成情况」）+ 文档漂移修正。**

- **审计方法**：把 SCOPE §6 路线图的 5 个阶段逐行拿去实测（契约单一源 / doctor / 验证工具 / 插件运行时 / `.zip` 解包 / 四插件归属 / AI 边界），而不是只看文档自述。
- **发现并修正 8 行文档漂移**（活儿早干完了，文档还写「未实现」）：
  - **阶段 1 五项里 4 项**（契约单一源、Doctor + 迁移框架、取回验证工具、插件运行时）实测均已落地 —— 例：`app/store.py:18-20` 直接 `from core.contracts import …`，`mcp/constraints.py:10` 退化为门面，`python -m core.doctor` / `core.plugins list|check|verify` 均可用，`tools/` 六个闸门脚本齐备 → 状态改为「已实现」。
  - **阶段 2 四行**（专注计时 / 天气 / RSS / 用量计费）仍写旧位置 `web/app.js`、`app/weather.py`、`app/rss.py`、`app/billing.py` —— 实测这四个文件**都已不存在**，功能在 `plugins/{focus,weather,rss,billing}`，内核只剩一行历史注释（`app.js:623/721/1276/1399`）→ 改为 `✅ 已迁 plugins/<id>`。
- **发现唯一真缺口：`.zip` 自动解包「规格完整、代码零实现」。**
  - 全仓搜 `zipfile|\.zip|extractall` 在 `core/`（含 `core/plugins/*.py` 七个文件）**命中 0 次**：`loader.py` 只识别目录态。
  - **实测行为**（临时扫描根，未动真插件目录）：造一个 `hello-1.0.0.zip`（`plugin.json` 在根）放进 `--plugins-root` → 输出「未发现任何插件」、**退出码 0、无任何提示** —— 用户丢个 zip 进来是**完全静默**的，比报错更糟。
  - 已在 `docs/PLUGIN_SPEC.md` §2「解包规则」加状态横幅、§2 形态表与 §12 P-B 标注「**已定、未实现**」，`docs/SCOPE.md` §6 阶段 1 标为「**唯一剩余项**」。
- **AI 边界核对（回答你对「内核只做 AI 设置」那条）**：实测**你的描述已经是现状，无需改代码** —— ① AI 设置全部在 `config/app.json` 的 `llm` 段（`enabled / personas×3 / system_prompt / vision_enabled / assist`×10 键）；② `config/plugins/` 下只有 `weather.json`、`rss.json`（各自业务数据），**没有任何插件自存 AI 设置**；③ 插件是*消费*内核设置：`floating-assist/web/panel.js:340` 读 `/api/config` 取人设、`:1229` 把人设写回 `/api/config/app`，`literature-reader` 走内核 `ERWVisionEnabled` / `ERWAssistCustomActions` 接缝且 LLM 调用走内核 `POST /api/agent/assist`；④ 内核侧 AI 工具**恰为 4 个** `kb_*`，其余（`context` / `note_write`）在文献插件里。
- 状态：插件 **7 个可用 · 0 blocked / rejected / 冲突**；`doctor` error 0；工作树干净。

## v261009.19

- **三处「小账」全修**（按你的选择）：
  - **悬浮球不再嗅探阅读区 markup**：`litContext()` 与「框选截图」入口从 `q('.lit-shell')` 改为问接缝 `window.ERWReader.available()`——内核/插件都不再靠别人的 DOM 判断状态。
  - **悬浮球最终消息正文改走内核 `ERWMarkdown`**（代码高亮 / mermaid / MathJax / 宽表格包裹与全站一致）：只在**流式结束后**升级（流式期间每次状态刷新会重绘整列表，走重渲染会把整个对话反复 typeset）；旧的内联 MathJax 兜底保留为「内核接缝缺席」时的退路。
  - **内核 observer 忽略清单去掉 `#erw-fab-panel`**（插件已搬走，内核不该再点名插件 DOM）。
  - **清掉 `System/plugins.json` 里已删插件 `litnote` 的残留记录**（现为 7 条，与 7 个插件一致）。
  - 验收（`.scratch/tmp/_check_fab_markdown_and_seam.py`，真 Chrome，**7/7**）：内核 `ERWMarkdown` 可用（表格包裹 / 代码高亮 / 数学三连）；悬浮球最终消息的待升级标记被消费（说明确实走了接缝）；**阅读区插件缺席时悬浮球照常可用且 0 console error**。
- **新增 `docs/PLUGIN_SPEC.md` §6.2「插件能力矩阵：什么不用改内核，什么必须改内核」**（回答你的问题：现体系够不够、加插件要不要动内核）：
  - **① 完全不用改内核**：导航页/槽位/设置页 tab/阅读区 tab、自有 HTTP 路由、给 Agent 加工具（写工具自动走草稿闸门）、自有存储与配置、订阅内核事件、读公开数据 API、内核 UI 小件、出网/重型库按需、前提插件依赖、自登记前端接缝——共 11 类，当前 7 个插件基本都落在这一类。
  - **② 要一次性加一种「形态」**：插件接管整页 / 接管局部 / 提供常驻容器 / 插件间通信——本轮实际新增了 5 处（`ERWReader`、`ERWGraphRenderers.mount`、`overlay` 槽位、`ERWToast`、`ERWReaderAssist`），**加完同类插件不再需要动内核**。
  - **③ 内核必须先实现的缺口（只有三件）**：`ctx.search.addSection`、`ctx.jobs`、`process` 执行层。
  - **RAG 结论**：属③——必须补 `ctx.search.addSection` + `process` 隔离（`ctx.jobs` 可选，取决于是否要索引进度）；数据按你的决定**保留原位复用**；也给出了「纯前端轻量版（不经搜索框、用插件自己的 sqlite）」的替代路径。

## v261009.18

- **图谱渲染彻底交给插件**（你的实测发现：关掉知识图谱插件后，图谱页仍画出那张难看的螺旋图——说明内核还留着旧渲染）。
  - **删净内核的图谱实现**：`renderGraphPage` 的页面模板、筛选/选中/预览/导出、简易 `drawGraph`（2D/3D、拖拽、缩放）、邻域计算，共 **68 行**（`app.js` 1493 → **1438 行**）。`copyText` 因被 BibTeX 对话框共用而保留。
  - **改为页面级接管**：`ERWGraphRenderers` 的 `graph.mount(host, ctx)` 由插件画**整页**（页面 markup 也搬进插件，插件 555 → **611 行**），总览迷你图仍走 `overview.enhance`。
  - **无接管者时只给提示**：图谱页显示「知识图谱不可用：请在「设置 → 插件」里启用「知识图谱可视化」插件」，总览的迷你图卡片同样换成一行提示——**不再画任何兜底图**。
  - 插件 `core_min` 提到 **v261009.18**：旧内核会因缺少 `mount` 而**明确拒载**（不是静默失效）；插件说明同步改写（"停用后图谱页给提示，内核不再自带兜底图"）。
- **验收**（`.scratch/tmp/verify_graph_plugin_migration.py`，真 Chrome，**32/32**）：
  - 插件在场：718 节点 / 1854 关系、力导向布局、筛选联动、搜索定位、节点预览、导出弹窗 **149 项**、总览迷你图可跳转定位，**内核绘制次数 0**；
  - **插件缺席（脚本被拦）与「停用插件」两条路径都断言**：无画布、无筛选、**内核绘制 0 次**、页面明示「知识图谱不可用」、0 console error；
  - 启停契约：停用后不再下发、重新启用回到列表、**其他插件启停状态未被改动**。
- 回归：`verify_reader_note_tab`、`verify_reader_plugin_tools`、`verify_reader_seam` 14/14、`verify_floating_assist` 16/16、插件管理夹具、`ui_smoke` 17 路由 0 error、`web_check`、`plugin_check --assert-core-only`、`kb_smoke` 全绿；`doctor` error 0；插件 **7 个可用**。
- 夹具：A10 时代的 `verify_graph_canvas_ownership.py` 退役（它验证的「内核兜底绘制」路径已按你的要求删除）。
- **提示**：`Workspace/System/plugins.json` 里还留着已删除插件 `litnote` 的历史记录（`enabled:false`），无害（加载器忽略未知 id）；如需清爽可在插件页再点一次开关或我帮你清。

## v261009.17

- **三个插件合并成一个「文献阅读工作区」**（按你的要求；说明里体现合并后的能力）。原 `literature-reader`（阅读区）+ `litnote`（文献笔记 + 2 个 AI 工具）+ `reader-assist`（阅读区 AI 助手）→ **一个插件** `plugins/literature-reader` **v2.0.0**，插件数 9 → **7**。
  - 前端 `panel.js` = 三段 IIFE 拼接（阅读区 645 行 + 笔记 tab 136 行 + AI 面板 249 行 → **1049 行**）；`panel.css` 合并（154 行）；后端 `backend.py` 并入（2 个 AI 工具 + 3 条 note 路由）。
  - **插件说明按你的要求写清三块能力**：PDF 打开·翻页·缩放·跳页、批注增改删、阅读区「笔记」tab + 两个 AI 工具、阅读区「AI」tab（含多模态截图与写回笔记）。
  - `panel.mount` 仍是单一入口；`ERWReaderAssist` 接缝保留（现在由同一个插件内部提供与消费，仍对外暴露，将来可再拆）。
- **⚠️ 合并的等价性风险已处理**：插件 id 变了 → 插件工具前缀从 `p_litnote__*` 变成 `p_literature-reader__*`，**已保存的人设白名单会静默丢能力**（v261009.9 真踩过一次）。处理：
  - `app/config.py` 的 `LEGACY_TOOL_ALIASES` 增加四条映射（`lit_context` / `lit_note_write` / `p_litnote__context` / `p_litnote__note_write` → 新名），旧配置照旧生效；
  - 内置「阅读助手」人设的默认工具名直接写成 `p_literature-reader__context`；
  - 夹具断言「人设里没有旧工具名」「内核源码里旧工具名只出现在别名映射行」。
- **验收**：`.scratch/tmp/verify_reader_note_tab.py`（已对齐合并）**全部通过**——合并后**三块能力在同一插件里**（`readerTab` = `info/annotations/notes/ai` 且 AI 助手已注册）、**停用后阅读区不可用**（无接管者、入口不出现、无残留 tab）而**文献列表页照常**（50 行）；`.scratch/tmp/verify_reader_plugin_tools.py`（原 litnote 夹具改名对齐）**全部通过**——2 个插件工具在工具面、写工具仍走内核草稿闸门、停用后工具消失、内核工具恰好 4 个、旧工具名只存在于别名映射。
- 回归：`verify_reader_seam` 14/14、`verify_floating_assist` 16/16、`verify_graph_plugin_migration` 32/32、插件管理夹具、`ui_smoke` 17 路由 0 error、`web_check`、`plugin_check --assert-core-only`、`kb_smoke` 全绿；`doctor` error 0。
- 夹具退役：`verify_reader_assist.py` 删除（AI 不再是可独立停用的插件；它的两条核心断言——AI tab 存在 + 派发切前台——已并入阅读区夹具）。

## v261009.16

- **悬浮球 AI 助手整体搬成插件**（`plugins/floating-assist/`，1222 行 JS + 323 行 CSS 迁出内核）——**一次覆盖 6 个附属项**（SCOPE §2.2）：
  - 悬浮球助手（拖动定位 / 选区气泡 / 上下文注入 / 流式对话 / 草稿状态角标）
  - **工具轨迹时间线**（`window.ERWFabTimeline`，内核 Agent 消息气泡按 `?.` 空值保护消费）
  - **阅读中知识关联**（`#fab-related`，调内核 `POST /api/kb/related`，输入取阅读区 `ERWLiterature.context()`）
  - **会话历史回看**（🕘）
  - 写模式开关（"写工具直接落盘"）——**执行侧仍在内核**：草稿确认闸门是安全不变式，插件只给开关 UI
  - **AI 助手人设编辑器**（改为本插件的**设置页 tab**）
- **两个新内核接缝**：
  - **浮层槽位 `overlay`**：`nav[].slot:"overlay"` + `ERWPanels.register({slot:'overlay', renderSlot})`，内核在 `index.html` 提供 `#erw-overlay-host` 挂载点（`KNOWN_SLOTS` 增加 `overlay`）。插件不再往 `document.body` 塞 DOM——实测悬浮球 `inSlot=true / inBody=false`。
  - **`window.ERWToast`**（通用提示条）：内核把自家 `toast()` 暴露出来，结束「5 个模块各写一份 toast」；插件优先用它，缺失时自行兜底。
- **内核删减**：`web/v260930-floating-agent.{js,css}` 删除（105 KB）；`v260922-research-pages.js` 不再插 `#erw-persona-host`、不再广播 `erw-llm-settings-rendered`（人设编辑器随插件走，并改口为「设置页『AI 助手人设』tab，由插件提供」）。
- **验收**（`.scratch/tmp/verify_floating_assist.py`，真 Chrome，**16/16**）：启用 → 悬浮球存在且**挂在内核浮层槽位里**、`ERWFabTimeline` 已提供、`ERWToast` 来自内核、点球开面板且含「关联知识宿主 / 人设下拉 / 写模式开关 / 历史 / 截图入口」、设置页多出「AI 助手人设」tab 且渲染出 3 行人设、0 console error；**停用（脚本被拦）→ 悬浮球消失、`ERWFabTimeline` 不存在（内核空值保护）、人设 tab 消失、无残留宿主、无 console error**。
- 回归：`verify_reader_assist` 16/16、`verify_reader_seam` 14/14、`verify_graph_plugin_migration` 32/32、`ui_smoke` 17 路由 0 error、`web_check`、`plugin_check --assert-core-only`、`kb_smoke` 全绿；插件合计 **9 个可用**；`doctor` error 0。
- **顺带核实（无需再改）**：mermaid/mathjax 的按需渲染在 v261009 A1 已完成——`index.html` 首屏只有 MathJax 配置桩与 `vendor-lazy.js`，2.11 MB / 2.57 MB 的真库由 `erwVendor.load('mathjax'|'mermaid')` 在用到处加载（app.js 两处 + 本插件 mathjax 一处）。

## v261009.15

- **阅读区 AI 助手拆成独立插件**（`plugins/reader-assist/`，你要的「只有开启 AI 助手，阅读区才出现 AI 功能选项」）。
  - **阅读区不再硬编码 AI**：`{id:"ai"}` 从 tab 行删掉、`sideTab` 的 `ai` 分支删掉、`S.ai` 状态与 `aiPanel/runAssist/mdLite/noteApply` 整段（75 行）搬走——阅读区现在**不认识 AI 这个概念**，只知道「有个助手接缝」。
  - **新接缝 `window.ERWReaderAssist`**（**插件提供、插件消费**，v261009.15 首例）：阅读区把三条入口派发给助手插件 —— ① 选中文本 → 工具条「AI 翻译/总结/整理」`run(action,{text})`；② 框选完成（多模态开启）→ 自动切到助手 tab；③ 「笔记」tab 的「AI 整理」`fromNote(text)`。派发前阅读区先切到助手声明的 `tabId`，并在打开文献时经 `attach(ctx)` 把**实时上下文**交过去（`{paper, refreshList, selection(), capture{page(),area()}, activate(), aiPolish()}`）——这是验收里抓到的设计缺口：不预交上下文时，助手从工具条被触发会把面板画进别人的 tab。
  - **门控**：工具条的三个 AI 按钮与「AI」tab 都只在助手可用时出现；助手停用时点任何 AI 入口给一条明确提示（"AI 助手不可用：请在「设置 → 插件」里启用「阅读区 AI 助手」"），阅读区其余功能与「笔记」tab 不受影响。
  - 插件声明 `requires: {plugins:[{id:"literature-reader"}]}`（它的 tab 挂在阅读区上），加载仍有两次兜底重试，避免顺序意外导致静默失效。
  - **结果区渲染改用内核接缝 `window.ERWMarkdown`**（与全站一致，含代码高亮/mermaid/mathjax），内核接缝缺席时回退插件自带的轻量 Markdown 渲染。
  - **验收**（`.scratch/tmp/verify_reader_assist.py`，真 Chrome，**16/16**）：启用 → 助手已注册、tab 行含「AI」、工具条 3 个 AI 按钮、`run()`/`fromNote()` 都切到 AI tab 且面板显示出待处理内容、PDF 画布仍在、无非配额类 console error；**停用（脚本被拦）→ 无 AI tab、无 AI 按钮、阅读区其余功能照常**。回归：阅读区接缝 14/14、阅读区+笔记端到端 22/22、`web_check` / `ui_smoke`（17 路由 0 error）/ `plugin_check` 全绿。
  - 环境说明：本机 LLM 配额仍用尽（上游 429 → 内核 400），验收对 assist 的断言只要求「面板有反应（结果或错误）」，不依赖模型输出。

## v261009.14

- **阅读区整体搬成插件**（`plugins/literature-reader/`；**反转** SCOPE §2.1 C6 原先的「阅读进核心」决定——只有启用该插件才能使用阅读区）。
  - **新接缝 `window.ERWReader`**（§6.3）：`register({id, open, openByAttachment, context?})` + `available()`。内核在文献列表页点「PDF 阅读工作区」或点附件徽章时经它调用；**没有接管者时入口不出现**，用户试图打开时给一条明确提示（"阅读区不可用：请在「设置 → 插件」里启用「文献阅读工作区」"），而**文献列表/元数据条目页照常可用**（核心不依赖阅读区）。
  - **插件是纯前端**（`panel: {mount, style}`、`ui:panel`、无 `entry`、无后端）：`web/literature.js`（642 行）+ `literature.css`（134 行）整体迁出内核。**文献数据与文件服务全留内核**——`/api/literature/*`（含 PDF 的 **Range 206 分片**）、批注 JSON 与**删批注时的 Preview 级联清理**、笔记真值在 `literature` 条目、`/workspace-file/`、`/api/agent/assist`。因此**无需扩 `core_api`、无数据安全风险**：风险最大的那几处（文件服务、级联删除、双载体真值、Workspace 外绝对路径）都没动。
  - **顺带修掉一个一直静默的 bug**：内核 `literature.js` 的两处 `toast(...)` 引用的 `toast` **从来不是全局**（`app.js` 里那个是 IIFE 闭包私有，运行时实测 `typeof toast === "undefined"`）——「批注加入笔记」的两条错误路径一进就 `ReferenceError`，用户看到的是"点了没反应"。插件自带提示实现（优先 `window.ERWToast`，否则往 `#toast-stack` 放一条）。
  - **内核 CSS 不再引用插件 markup**：紧凑密度下那条 `html[data-density="compact"] .lit-shell{…}` 随阅读区一起搬进插件样式。
  - **验收**：`.scratch/tmp/verify_reader_seam.py` **14/14**（有接管者 → 入口在、进得去、tab 就绪、PDF 3 个 canvas、`context()` 可用；**无接管者 → 入口消失 + 明确提示 + 列表页照常**）；`.scratch/tmp/verify_reader_note_tab.py` **22/22**（阅读区 tab 行 `info/annotations/notes/ai`、笔记同源 6914 字、插件路由写入并可还原、停用 litnote 后 tab 优雅消失）；`ui_smoke` 17 路由 0 error；`web_check` / `plugin_check --assert-core-only` / `kb_smoke` / `doctor`（error 0）全绿。
  - **环境说明（不是回归）**：验收时本机 LLM 配额用尽（上游 429 → 内核 400），「AI 整理」那一步的 LLM 调用断言按环境**跳过并点名**，tab 切换仍照常断言。
- **工具口径随之放宽到「插件也算装配的一部分」**（否则内核精简越多、闸门越假）：
  - `tools/web_check.py`：自定义事件的**派发方**与 `window.ERW*` 的**提供方**都改为「内核 + `plugins/*/web/*.js`」一起判（阅读区搬走后 `erw-lit-page/-selection` 由插件派发、`ERWLiterature`/`ERWCapture` 由插件提供）。**负向用例**（`.scratch/tmp/verify_web_check_negative.py`：注入一个无人定义的接缝 + 一个无人派发的事件）仍被如实抓出。
  - `tools/ui_smoke.py`：装配自洽性同样把插件前端脚本计入提供方。
  - `tools/plugin_check.py`：面板契约的自登记接缝清单加入 `ERWReader`。
  - 夹具卫生：验收脚本的「前置启用 bundled 插件」改为**尊重用户在设置里明确停用的插件**，theme 类夹具（litnote）改为**进入时快照、收尾还原**（本轮真踩过：夹具把用户关掉的 litnote 又打开）。

## v261009.13

- **知识图谱可视化搬成插件**（`plugins/knowledge-graph/`，SCOPE §2.2 附属；`docs/REFACTOR_PLAN.md` §7）。
  - **新接缝 `window.ERWGraphRenderers`**（渲染接管，§6.3）：`graph` / `overview` 两个作用域。内核渲染图谱页与研究总览迷你图时**先问注册表**——有接管者就把画布交给它、不再画兜底图；接管者 `enhance()` 抛错或插件缺席时，内核回退自带 `drawGraph`。**内核零依赖**（删掉插件图谱页照旧可用），并且彻底消掉了此前「内核先画一遍 → 补丁 `replaceCanvas` 丢掉」的白画（`v261009.12` 那次的临时判据 `window.__knowledgeGraphEngineVersion` 也随之退役）。
  - **新接缝 `window.ERWContract`**（契约只读视图）：七类 kind、类别词、`kind_marks`、关系的中文标签由内核统一导出，插件不再各抄一份。
  - **新接缝 `window.ERWMarkdown`**：`renderInto(el, raw)`（与内核同一套 marked + DOMPurify + hljs + mermaid/mathjax 按需）+ `normalizePaths(html)`（`/workspace-file/` 图片路径归一）。
  - **`plugins/knowledge-graph`** 是**纯前端插件**：`panel: {mount, style}`、`permissions: ["ui:panel"]`、无 `entry`（宿主对「没有后端的插件」是一等公民）。数据走内核公开 API（`/api/graph`、`/api/graph/overview`、`/api/docs/<id>`、`POST /api/graph/bundle`）。
  - **内核删减**：`web/v260922-research-pages.js` 的图谱两个 IIFE（`935 → 385` 行，删 550 行）；图谱专属 CSS 从 `web/v260922-graph-performance.css` 迁到插件自带样式（内核只留图谱页 markup 的层级/尺寸，兜底渲染也要用）。
  - **顺带修掉两处漂移**（引擎自带标签表缺 `experiment`，内核有）：① 实验节点的侧栏/搜索标签回落成英文；②「仅知识条目」按钮会把实验条目一起取消勾选。现统一取自 `ERWContract`。
  - **验收**（`.scratch/tmp/verify_graph_plugin_migration.py`，真 Chrome，**32/32 通过**）：能力等价（718 节点 / 1854 边、18.0 万 px 已绘制、筛选联动 718→714、选中节点→侧栏+Markdown 预览、导出弹窗 24 项、2D/3D 切换）、**内核重复绘制 0 次**、**插件被拦时兜底可用且可交互**（`_graphRenderToken` 1→2）、总览迷你图接管并可跳转定位图谱节点、`/api/plugin-manager` 启停契约且**不动其他插件的启停状态**。
  - **`ui_smoke` 抓到并修掉一个真 bug**：总览页接管时那条仍在飞的取数在导航切走后把「画布已被替换」抛成 console error → 现在「取消」与「失败」分开：页面切走/画布被换**静默返回 null**，只有取数失败才 `throw` 让内核兜底（内核侧也随之不再往已脱离文档的画布上画）。
  - **工具**：`tools/plugin_check.py` 的面板契约从「必须调用 `ERWPanels.register`」扩展为「必须自登记**某个**内核接缝」（认可 `ERWPanels` 与 `ERWGraphRenderers`），否则仍判失败。
  - **文档**：[`docs/PLUGIN_SPEC.md`](docs/PLUGIN_SPEC.md) 新增 §6.1「前端接缝与公开数据 API」+ 渲染接管契约；[`docs/REFACTOR_PLAN.md`](docs/REFACTOR_PLAN.md) §6.3 扩展点表补三行、§7 记一行。

## v261009.12

- **A10 收口：删掉图谱页的「先画后弃」**（`docs/REFACTOR_PLAN.md` §7 A10 后半项之一，P14 双实现）。
  - 现象（实测确认）：`#graph` 路由下，`app.js` 的 `renderGraphCanvas()` 先在自己的画布上画一遍整图，随后 v260922 的 `OptimizedKnowledgeGraph` 用 `replaceCanvas()` 换掉这块画布、在**新画布**上重画，并顺手覆盖 `[data-gview]` / `[data-graph-kind]` / `[data-graph-relation]` / `#graph-filter-all` / `#graph-filter-docs` / `#graph-bundle` 的处理器与 `selectNode → 侧栏/预览` 路径 —— 内核这一次绘制**没有任何消费者**，纯浪费。
  - 改法：`app.js` 新增 `graphEngineAvailable()`，判据是补丁在加载期同步声明的接缝 `window.__knowledgeGraphEngineVersion`（或实例 `window.__knowledgeGraphEngine`）。引擎在场 → 内核不再绘制（视图按钮的 active 态与选中态记账仍保留）；**补丁被裁掉或未加载时自动回退**到原 `drawGraph` 路径，行为不变。
  - 实测（`.scratch/tmp/verify_graph_canvas_ownership.py`，**19/19 通过**，真 Chrome）：
    - 内核在本路径上取 `2d` 上下文的次数：`1 → 0`（同一探针里把补丁脚本请求 abort 掉，兜底路径计数 `2`、`_graphRenderToken=1`、画布 96 519 px 有内容 —— 证明计数器灵敏且回退可用）；
    - 引擎侧不受影响：接管画布（`optimizedGraph=1`）、718 节点、画布 165 792 px 有内容、`#graph` 无 console error；
    - 一轮交互（切 2D/3D、全选、只看文档、逐个勾选）后内核绘制次数**仍为 0**，引擎继续渲染（544 节点 / 93 926 px）。
  - `#research-overview` 的迷你图**刻意保留**内核这层绘制：v260922 的 `OverviewGraph` 只在 `/api/graph/overview` 取数成功后才克隆替换画布，取数失败时内核的绘制就是它的兜底（代码注释已写明）。
  - `web/manifest.json` 的 `app.js` 缓存键 `261009i → 261009j`，`index.html` 随 `web_manifest.py --write` 重建。

## v261009.11

- **§5.2 附属：文献笔记的「编辑界面」也搬成插件**（SCOPE §2.2 的另一半；工具部分 `v261009.9` 已搬）。
  - **新扩展点 `ERWPanels.readerTab`**：任何模块都能往**文献阅读区**右侧加一个 tab（与已有的「设置页 tab」同一模式——内核只把 tab 排进行里，并把上下文 `{paper, refreshList, aiPolish}` 传给插件）。阅读器现在只留「信息 / 批注 / AI」。
  - 插件 [`litnote`](plugins/litnote/plugin.json) v1.1.0：`web/panel.js` 的阅读区 tab 从内核 `literature.js` **原样搬出**（textarea + 保存 + 插入图片 + AI 整理）；数据面走**插件自己的路由** `/api/plugins/litnote/note|note-image`，后端经 `core_api.lit_*` 访问核心文献库（插件不直接读 `Workspace/` 下的文件）；「AI 整理」由阅读器经上下文回调（**依赖方向仍是插件→内核**）。
  - **新 manifest 字段 `panel.mount`**（`P020` 校验）：**没有导航页的 UI** 也能被宿主加载——此前只有 `nav[0]` 会被加载，像 litnote 这种只贡献 tab 的插件，前端脚本**永远不会被注册**（实测确认过：`readerTabs` 为空）。
  - `core_api.lit_note_image()`：插入图片的等价能力（与核心同一实现）。
  - **内核删除**：`literature.js` 的 `note()` / `saveNote()` / `uploadNoteImage` 与硬编码的 `data-tab="notes"`（`insertAtCursor` 保留——「批注加入笔记」等核心流程仍用它）。
  - **验收**（`.scratch/tmp/verify_reader_note_tab.py`，21 项全通过）：tab 行 = 内核三项 + 插件「笔记」· 插件渲染的编辑器载入现有正文（与核心路由**同一份数据**，594 字一致）· 保存经插件路由写入并可还原 · 「AI 整理」切到阅读器 AI tab · **停用插件 → tab 优雅消失、内核 tab 不受影响** · 内核已无笔记实现。
- **修复：核心阅读器依赖 CDN 加载 PDF.js → 网络受限时打不开任何 PDF**（本轮实测暴露）。
  - 排查发现 `web/vendor/pdfjs/` 里**已有一份完整本地 PDF.js**（build + 169 个 cmap + 16 个标准字体，3.2 MB），但它 ① **从没进过版本库**（被 `.gitignore` 的 `build/`（本是构建产物规则）与白名单误伤）② 阅读器**根本没用它**（`ensurePdfJs()` 只从 jsdelivr 取）。
  - 修：`.gitignore` 末尾**逐级放行** `web/vendor/pdfjs/**`（gitignore「后面的规则优先」，放前面会被 `build/` 覆盖）；`literature.js` 改为**本地优先、CDN 兜底**，并把 `cMapUrl` / `cMapPacked` / `standardFontDataUrl` 指向本地（中文 PDF 缺字形的根因就是没配这两项）。
  - 实测：PDF.js **3.11.174 从本地加载**（`window.__pdfjsLocal=true`）、**渲染出 3 个 canvas**、全程 **0 console error / 0 失败请求**。
- **本轮 22 套闸门全绿**；索引 WAL 折回 0，`doctor` 2 errors / 7 warnings（均为既有已知项）。

## v261009.10

- **插件页：卡片摘要直接写明「提供什么」**（用户反馈「在插件设置中没看到文献工具插件」）。
  - 排查结论：**插件一直在列表里**（实测该页渲染 5 张卡片，第 3 张就是「文献笔记 litnote」，0 console error）——但上一轮把卡片压成一行「版本 + 来源」后，**只有工具、没有页面**的插件看不出用途。
  - 现在摘要行给出能力：`版本 1.0.0 · 2 个 AI 工具`（litnote）/ `面板 资讯 · 3 条接口 · 可配置`（rss）/ `顶栏组件 · 4 条接口 · 可配置`（weather）/ `面板 用量 · 5 条接口`（billing）。
  - 另把 `VERSION` 从 `v261009.0` 补正为 **`v261009.9`**（页头「内核 v…」此前一直显示旧值）。
- **修一个会「让所有插件消失」的隐患：`VERSION` 带 UTF-8 BOM**。
  - 我用 PowerShell `Set-Content -Encoding utf8` 写 `VERSION`，带上了 BOM（`\ufeffv261009.9`）→ `core_min` 比较全线失败 → **所有插件被判为「内核版本过低」而阻塞** → 服务启动后**插件路由全部 404**（`ui_smoke` 报 6 条 console error，计费/资讯/天气面板全空）。
  - 修法：① `core.plugins.manifest.read_core_version()` 统一读取并**去 BOM**，`server` / CLI / `plugin_check` 全部改走它（此前 CLI 里有一处零散的 `lstrip("\ufeff")`，所以「命令行看正常、服务端全阻塞」）；② `plugin_check` 新增硬闸门：**VERSION 带 BOM 直接判失败**（正反用例都验过）。
- **修一个「一次临时不可用就永久丢配置」的脆弱点**（BOM 事故的连带损伤暴露）。
  - 现象：插件被阻塞期间，人设白名单清洗按「当前可用工具」裁剪并**被 `reload_all()` 写回磁盘** → 阅读助手的文献工具条目被**永久删掉**（本轮修了两次：一次是搬家改名，一次是 BOM 事故）。
  - 修法：`_clean_personas` **加载期不再裁剪**，只做「旧名→新名」映射与去重；可用性在**使用时**过滤（`agent.py` 的 allowed 过滤）。实测：停用 litnote 后人设白名单条目**保留**，重新启用能力自动恢复。
  - 数据修复：走配置 API 把 `p_litnote__context` 加回阅读助手（已落盘回读确认）。
- **本轮 21 套闸门全绿**（`ui_smoke` 17 路由、`plugin_check --assert-core-only`、6 个插件夹具、`kb_smoke`、`web_check`、`doctor`、`mcp --selftest`）。

## v261009.9

- **§5.2 附属：文献笔记搬成插件（文献工具包）**——把两个「文献侧」AI 工具从内核搬出，内核工具集回到规格要求的**恰好 4 个**（SCOPE §5.1 铁律）。

  | 搬出前（内核工具） | 搬出后（插件工具） | 说明 |
  | --- | --- | --- |
  | `lit_context` | `p_litnote__context` | 读：文献元信息 + 批注数 + 笔记全文 |
  | `lit_note_write` | `p_litnote__note_write` | 写：追加/替换文献笔记（走内核草稿闸门） |

  - 新增 [`plugins/litnote/`](plugins/litnote/plugin.json)（计划的「插件工具包」形态，只注册工具、不注册路由/面板）。**写工具的安全闸门仍在内核**（confirm 只出草稿 → 用户确认后以 direct 模式调用插件 handler），插件不实现确认逻辑。
  - **新增 `core_api` 文献面**（有意的 API 动作，已写进 PLUGIN_SPEC §6）：`lit_list` / `lit_item` / `lit_note` / `lit_note_save` / `lit_annotations`——文献库由**核心**维护（SCOPE §2.1「梳理与阅读进核心」），插件经此访问，不自己去读 `Workspace/` 下的 PDF/Notes。
  - **内核删除**：`app/agent_tools.py` 的两个实现 + 映射 + 元信息（19.2 KB → 16.4 KB），`agent.py` 两处文案不再点名工具。
  - **迁移等价性（本轮实测抓到的真实能力丢失）**：工具改名后，**用户已保存的人设白名单里还是旧名**，被清洗逻辑静默过滤掉 → 阅读助手**丢了文献工具**，且旧名在更早的一次清洗里已被写回 `config/app.json`。两处修：① `config.py` 增加 `LEGACY_TOOL_ALIASES`（旧名→新名，插件停用时新名自然被过滤，优雅退化）；② 走**配置 API**（与前端人设编辑器同一路径）把 `p_litnote__context` 显式加回阅读助手白名单。
  - **悬浮球去硬编码**：写工具集合改为从 `/api/agent/tools` 的 `write` 标记**动态推导**（内核模块不再硬编码插件工具名）；工具标签表只覆盖内核工具；清掉两处旧工具名文案。
  - **验收**（`.scratch/tmp/verify_litnote_plugin.py`，22 项全通过）：**内核工具恰好 4 个且正是规格那四个** · 插件读/写工具在工具面（写工具带 `write: true` 与 `plugin` 归属）· 旧工具名已不在工具面 · **读工具对真实文献返回元信息+批注数+笔记全文** · 缺 `paper_id` 明确报错 · **写工具草稿闸门四段验证**（confirm 只出草稿/笔记未变 → 拒绝仍未变 → 确认后真写入 → 验收后还原）· **停用插件工具即消失、内核 4 个不受影响** · 人设白名单用对外名 · 内核零残留（AST 判定，旧名只允许出现在别名映射行）。
- **闸门夹具加固**：全部插件夹具的前置改为「**随包插件全部启用**」——用户手动停用某个插件时（本轮实测 `billing` 在 10:20 被手动停用），夹具会先恢复到默认态，而不是报出「插件不存在」这类误导性失败。
- **维护**：索引 WAL 4.04 MB → 0（`core.index.maintain --checkpoint`），doctor 回到 2 errors / 7 warnings（均为既有已知项）。
- **本轮 20 套闸门全绿**。

## v261009.8

- **§6/P6 第三件：用量计费搬成插件**（计划里 P6 顺序的第三项；它有**硬依赖前置条件**，所以先倒置再搬运）。
  - **新增内核扩展点 `ctx.events`**（REFACTOR_PLAN §6.3 早就声明、此前未实现）：[`core/events.py`](core/events.py) 提供 `on/emit/subscriber_count`——内核在节点上**广播事实**，功能模块按需订阅；**订阅者异常被隔离**（不影响广播方与其它订阅者）、载荷浅拷贝（互不串味）、取消订阅即停。
  - **依赖倒置（P14）**：`app/agent.py` 原先两处直接调 `billing.record(cfg, usage)`，删掉计费就会报错。现在改为广播 `llm.usage`（新增 `_emit_usage()`）；**没有订阅者时什么也不发生**，内核照常跑（I1）。`app/agent.py` 已不再 import 计费。
  - **搬运**：新增 [`plugins/billing/`](plugins/billing/plugin.json)——`backend.py`（`app/billing.py` **原样搬入**：计价模型、三种计费方式、单价匹配、聚合统计逻辑未改写）+ `web/panel.js` + `web/panel.css`（从内核模块搬出，接口前缀改 `/api/plugins/billing/*`、外层加 `data-plugin="billing"`、CSS 统一作用域）。
  - **数据原样认领**：`Workspace/System/billing/{ledger.jsonl, prices.json}` → `Workspace/System/Plugins/billing/`，**首次运行原样复制**（账本是只增不改的真实历史，实测 57 行一字不差；单价表逐字段一致）。
  - **内核删除**：`app/billing.py`、`web/v261008-billing.js`、`web/v261008-billing.css`、`/api/billing/*`（5 条路由）与 `server.py` 的计费导入、装配清单里的两个条目。
  - **验收**（`.scratch/tmp/verify_billing_plugin.py`，24 项全通过）：账本 57 行原样认领且前几行相同 · 单价表逐字段一致 · 插件 4 个接口可用（含 `?defaults=1` 与 `DELETE records`）· **内核旧接口全部 404** · **未加载插件时广播 0 送达且不报错（I1）** · **加载插件后送达 1 个订阅者并记进账本**，记账口径与搬出前一致（session_id / model / tokens / `billing_mode=subscription`）· 面板渲染 1477 字、侧栏有「用量」、容器带作用域 · 内核已无计费实现（AST 判定）· 0 console error。**验收把测试写入的那条假账原样还原**，不留副作用。
- **本轮共 21 套闸门全绿**（新增计费验收，其余 20 套见 `v261009.0` 的验收基线）。

## v261009.7

- **插件卡片也收成一行（只留版本），其余信息进「详情」按需展开**（用户要求：这些内容一并压缩）。
  - 之前每张卡片固定 7 行（版本/权限/路由/工具/依赖/目录/面板）。现在默认只有**一行**：`版本 1.0.0　来源 bundled　▸ 详情`；点这行展开权限/路由/工具/依赖/面板/目录，再点收起。
  - 实测：卡片高度 **400px → 150px**（默认态），详情展开 290px、收起回 150px。
- **配置区的展开/收起改为「点同一行」**（用户反馈：折叠效果不好、收起按键很大）。
  - 去掉底部那个大「收起」按钮；展开态该行自身变成 `配置 [已展开] JSON，可直接编辑后保存　▾ 收起`，点一下即收起。动作区只留 [重新读取] [保存配置]。
  - 卡片摘要行与配置行统一到同一套 `.pm-row` 版式（同高 31px、同边框、同样的右侧动作位），两处交互一致。
  - 实测：配置区默认 **31px 纯一行**（比上一版还少了区块内边距）、未展开 **0 请求**；展开 189px 且此时才请求；点同一行收起回 31px；保存后自动收起。
- **验收**：新增 `.scratch/tmp/verify_plugin_card_compact.py`（15 项全通过）覆盖「默认一行 / 详情展开收起 / 配置行双向切换 / 无大收起按钮 / 0 console error」；既有夹具同步到新选择器与「默认收起」的前提。**19 套闸门全绿**。

## v261009.6

- **插件配置区默认收成「一条目」**（用户要求：需要修改再展开）。
  - 之前每个插件都把整段 JSON 摊开（6 行起），页面被撑得很长。现在配置区**只有一行**：`配置 [未展开] 摘要/提示 … 展开编辑`——标签、状态、摘要、动作同排，「内核只做转发」这类说明移到悬停提示，不再占版面。
  - **展开后才拉取配置**（未展开不请求，减少无谓请求），展开态给编辑器 + 重新读取 / 保存配置 / 收起；**保存成功后自动收回一行**，摘要随即反映新值。
  - 没有配置接口的插件（专注）本来就是一行说明；旧后端也是同一行的「请重启工作台」。
  - 实测（文本量测，非截图）：默认态**整块 42px = 一行 31px + 区块内边距 11px**、无编辑器、**0 次配置请求**；点开 → 218px、出现编辑器与按钮、此时才请求；收起 → 回到 42px；改值保存 → 落盘 `timezone=Asia/Tokyo` 且**自动收回一行**、摘要显示新值。14 项全通过。
- **停用插件加一道确认**：这个开关很小、又在卡片右上角，**实测被误点过一次**（`focus` 在 09:39 被停用，导致侧栏少了「专注」）。现在**停用**会先确认（说明「文件、配置与数据都会保留，可随时恢复」），**启用**不打扰。已把 `focus` 恢复为启用。
- **夹具自愈**：三个插件 E2E 与面板夹具在开跑前先确保被测插件处于启用态（默认即启用）——避免用户手动停用插件时，夹具报出「插件不存在」这类误导性失败。`verify_plugin_manager` 的「配置编辑器在位」断言同步改为「先展开再断言」。

## v261009.5

- **插件页在旧后端上不再「装作信息是空的」**（用户反馈：权限显示「未声明」、路由「无后端接口」、启用未勾选且点不动）。
  - 真实原因：那些字段（状态 / 权限 / 路由 / 面板槽位 / 工具 / 目录 / 启用状态）是 `v261009.4` 新加到预览接口里的，**用户当时跑的后端还是旧版**，只下发 `id / version / source / distribution / nav`。旧页把「字段不存在」直接渲染成「未声明 / 无后端接口 / 未注册工具」，看起来像功能坏了。
  - 现在：检测到精简清单就在页顶明确报「**后端版本较旧，本页信息不完整**」并列出实际收到的字段、要求**重启工作台**；权限/路由/工具/目录整段改为说明而不是假数据；**启用勾选框禁用并在 tooltip 说明原因**（旧后端没有启停接口）；配置区同样如实说明。
  - 验收：用 Playwright `page.route` 把 `?detail=1` 改写成精简清单（**真实模拟旧后端**）→ 断言出现「后端版本较旧」提示、勾选框禁用且有原因、**不再出现「未声明/无后端接口/未注册工具」**；切回新后端 → 默认启用被正确勾选且可点、权限/路由/槽位齐备、JSON 编辑器在位。两个分支各 0 console error。
- **笔记（及全部条目列表）的时间标签默认右对齐**（用户要求）。
  - 此前时间标签跟在项目名后面：**有项目名时被挤到右边、没项目名时落在左边**，同一页两种样子。
  - 改为 `.doc-item .doc-projects .badge.mono{margin-left:auto}`——无论有没有项目名都贴右。
  - 实测（文本量测）：`#notes` / `#experiments` / `#literature` 各取 20 张卡片，时间标签距行右缘 **0px**（有项目名 20/20、无项目名 18/18 均贴右）。

## v261009.4

- **设置 → 「插件」页：插件预览 + 插件设置 + 启停**（用户要求「在设置提供插件预览接口以及插件使用的相关设置」）。
  - **预览接口**：`GET /api/plugins?detail=1` —— 每个插件给出状态（含中文状态名与不可用原因/建议）、版本、来源（bundled/user）、分发类型、kind、权限（**带中文说明**）、路由清单、面板（区分导航页/槽位）、MCP 工具、依赖、目录、内核版本要求、是否有配置接口。
  - **插件设置**：读/写**插件自己的配置接口**（`/api/plugins/<id>/config`）—— 内核只做转发与展示，**不解释插件配置的内容**（所以内核仍然不认识任何具体插件）；界面上是可编辑的 JSON，保存即落盘到 `config/plugins/<id>.json`。没有配置接口的插件如实说明「它的设置在自己的界面里」（如专注/天气）。
  - **启停**：`POST /api/plugin-manager/<id>/enabled` → 写 `System/plugins.json` 后**热重载**插件集合（每次加载都在新的路由表/工具表上重跑 `register(ctx)`，插件不持有跨加载状态）。**停用不删文件、不动数据**——只改「开不开」（§1）。
  - **扩展点（通用，不是特例）**：`ERWPanels.register({id, settingsTab:{label, render}})` —— 任何模块都能往「设置」里加一个 tab；`app.js` 只负责把内置 tab 与登记的 tab 排在一起，**不加任何功能分支**。「插件」页本身由新内核模块 [`web/plugin-manager.js`](web/plugin-manager.js) 自登记。
  - **实测**（`.scratch/tmp/verify_plugin_manager.py`，30 项全通过）：设置页出现「插件」tab · 三张插件卡片（权限/路由/面板/版本/目录齐全）· 停用 rss → 清单与侧栏同步消失、**插件目录与资讯缓存都还在**、`System/plugins.json` 记下意图 · 重新启用恢复 · 改天气配置 → 落盘到 `config/plugins/weather.json` 并可读回 · 无配置接口的插件不产生 4xx 噪音 · 0 console error。
- **顺带修掉两个由本页暴露出来的问题**：
  1. 「只贡献设置页 tab」的面板曾被 `navGroups()` 当成导航面板，于是侧栏**多出一项没有页面的「插件」**；现在按能力分类挂载（有 `render` 才进导航），`ui_smoke` 也新增断言：贡献的设置页 tab **必须出现在设置页、且不得出现在侧栏**，并会点开它确认渲染非空。
  2. 插件资源 URL 现在带 `?v=<mtime>` 缓存键（内核 JS/CSS 早有 `v` 参数，插件资源此前没有，浏览器可能一直用旧面板脚本）。

## v261009.3

- **修复：「资讯源设置」点了像没反应**（用户二次报「资讯设置不可用」——上一版只解掉了「等抓取」，真正的原因是**看不见**）。
  - 根因：设置面板被渲染在**资讯列表下方**，而列表有 72 张卡片——点按钮后设置在屏幕外，视觉上完全没变化。
  - 修法：① 设置面板移到**列表上方**（点开即见）；② 展开时 `scrollIntoView({block:'nearest'})` 兜底；③ **失败卡片里也保留「资讯源设置」按钮**（接口异常时设置也不该消失）。
  - 实测（文本量测，非截图）：设置面板 `top=310px / height=523px`，在 900px 视口内且位于 `.news-grid` 之前；点开 **31 ms**、列出 9 个源、**0 次多余请求**；源筛选 345 ms 生效；强制刷新拿到「最近抓取 2026/10/10 09:14:58」。
- **修复：插件前端资源没有缓存键**，浏览器可能一直用旧面板脚本（改了插件前端、刷新却还是旧行为）。
  - 内核自己的 JS/CSS 由装配清单的 `v` 参数充当缓存键；插件资源此前**没有**。现在 `/api/plugins` 下发的面板与样式 URL 一律带 `?v=<文件 mtime>`，文件一变键就变。
  - 实测：`/plugins-file/rss/web/panel.js?v=1791594851` 返回 200 且内容为最新。

## v261009.2

- **修复：「资讯源设置 / 源筛选」点了像没反应**（用户报「资讯设置不可用」）。面板里这两个动作（以及切页面）都先 `await` 一整轮抓取才重绘——离线时 6 个源逐个超时，等于点了没反应。现在面板把**上次抓取结果与配置**留在内存里，设置展开、源筛选、切页回访都**只重绘不抓取**；只有「强制刷新」才真抓，并在按钮上显示「抓取中…」与 `disabled`，行内显示进行态。
  - 实测：点「资讯源设置」**29 ms** 出面板（9 个源），**0 个多余 feed 请求**；点源筛选 350 ms 生效、**0 个多余请求**；强制刷新期间按钮变「抓取中…」，完成后「最近抓取 2026/10/10 09:10:56」。
- **新增：网络代理兜底（`core/net.py`）——「回环代理没启动就直连」**，解决「资讯抓不到 / 天气不可用 / LLM 连不上」。
  - 判定**保守**：仅当 ①配置的代理是**回环地址**（127.0.0.1 / localhost / ::1）②该端口**没人监听**（TCP 拒绝，1/4 秒探测）③调用方明确要求直连时，本次请求才改直连；远程代理（公司网关等）永不动，超时 / DNS 失败 / 非 2xx 一律照原样抛出。
  - 落点：`core/net.py`（判定 + `read_url`）、`core_api.http_get()`（插件出网唯一推荐入口，写进 PLUGIN_SPEC §6）、两个插件（`rss` 的 `_download`、`weather` 的 `_json_get`）、`app/agent.py` 的两处代理分支（原判据 `if not getproxies().get("https")` → `net.direct_preferred("https")`）。
  - **实测（本机系统代理 127.0.0.1:7890 未启动）**：资讯 `?force=1` → **72 条、`stale:false`、6/6 源健康**；天气 → **实时**（上海市浦东新区 晴 19.6°，无降级）；LLM → **HTTP 200 + usage**（用真实 key 打通，此前是 `WinError 10061`）。
- **诊断留档**：注册表 `ProxyEnable=1 / ProxyServer=127.0.0.1:7890` 而 7890 无进程监听；`urllib` 与 `requests` 都会读注册表代理，故所有出网请求被转发到死端口得到 `WinError 10061`。旁证：显式禁用代理直连时 arXiv 200、方舟端点可达、open-meteo 可达。**这不是重构引起的**，但应用层现在能自动降级。

## v261009.1

- **修复：插件迁移漏搬旧缓存，导致断网时行为退化**（用户报「资讯获取失败、0 条」时定位到）。
  - 现象：搬出内核后插件用的是自己的缓存路径（`System/Plugins/<id>/cache.json`），而内核时代的缓存留在 `System/Cache/rss_cache.json`（72 条）与 `System/Cache/weather.json`。于是网络不通时，插件是「空缓存 + 抓取失败 = 0 条 + 全部获取失败」，而不是原来的「显示上一次成功抓到的内容」——**这是搬出时漏做的一步，属真实回归（I12）**。
  - 修法：两个插件增加**一次性认领**旧缓存（`adopt_legacy_cache`）——插件缓存不存在且旧缓存存在时复制过来，之后一律只用插件自己的路径。顺带把 `core_api` 的数据根做成**公开** `data_root()`（原先天气插件在读配置迁移时用了私有 `_data_root()`），并在文档里写明它**只正当用于一次性迁移**，插件日常应使用命名空间内的助手。
  - 实测（断网环境）：`/api/plugins/rss/feed` → **72 条 + `stale: true`**（来自 10-09 16:22 缓存）；资讯页 **72 张卡片** + 「缓存更新 2026/10/9 16:22:54」提示；顶栏天气回到「上海市浦东新区 · 晴 25.5° · 16~26.1°」并在 tooltip 标注「当前为缓存内容：网络不可达（连接被拒绝）」；0 console error。
- **诊断（非代码问题，供存档）**：本机注册表 `ProxyEnable=1 / ProxyServer=127.0.0.1:7890`，但 **7890 无进程监听**（代理未启动）。Python 的 `urllib` 与 `requests` 都会读注册表代理，因此**所有**出网请求（arXiv、Open-Meteo、方舟 LLM API，连 pypi 也一样）都被转发到死代理并得到 `WinError 10061 连接被拒绝`。**证据**：显式禁用代理直连时 `rss.arxiv.org` 200、`ark.cn-beijing.volces.com` 401（可达，仅缺 key）、`api.open-meteo.com` 503（可达，服务端繁忙）；走系统代理则 10061。**与本次重构无关**——网络路径代码未改（搬出前后同样是 `urlopen` + 同一套代理发现逻辑）。

## v261009.0

### 契约单源 + 基线对齐（底层变更，需重启生效）

- **基线对齐（关键修复）**：把 `23a83f7`「知识库结构升级：实验独立成类 + 类型化关系层」摘到本分支（零冲突）。此前本分支的 `app/store.py`、`app/workspace.py`、`app/perf_index_*`、`web/app.js` 都停在升级前（6 类，没有 experiment），而 `Workspace/Knowledge/Experiments/` 里的 25 条实验、索引中 25 行 `documents(kind=experiment)` 以及 `mcp/` 层都已按七类写就——**下一次索引同步会把 25 条实验从索引与关系图中删除**（md 本体无损，但界面看不到实验）。复现证据：`.scratch/tmp/audit_kind_gap.py`（基线看得到 174 个 md，索引里 199 条，25 条会被删）。
- **补齐「改动后必跑」的验证工具（A13）**：随上一条取回 `tools/kb_smoke.py`、`tools/kb_tree.py`、`tools/kb_migrate_experiments.py`；另从 `ba77ddc` 单独取回只读的 `tools/shot_page.py`、`tools/shot_prep.py`（截图 + 像素预算），使 `AGENTS.md` 指定的验收流程在本分支可用。
- **契约单源（P0）**：新增 `core/contracts/kinds.py` —— 七类矩阵、标记表、字段契约、`WORKSPACE_LAYOUT`、关段关系映射、正文骨架的**唯一声明处**；新增 `core/contracts/naming.py` —— 标题校验的**唯一实现**（规则码 T000–T022、标记推导、建议标题）。`app/store.py`、`app/workspace.py`、`app/agent_tools.py` 改为消费契约；`mcp/constraints.py` 与 `mcp/naming.py` 退化为再导出门面（调用点零改动）；**删除**过期的第二套校验 `app/kb_naming.py`。
- **校验合并（P1/P2）**：同一标题在 HTTP（应用内 Agent）与 MCP 两条写入路径上现在得到同一结论；`experiment` 不再被 Agent 侧放行（原先「未知条目类型 experiment，跳过命名校验」）。
- **Agent 建档缺口（P5）**：`kb_create_entry` 开始接受 `status` / `record_date` / `due` / `added_date` / `summary_type`；`_KIND_ENUM` 改由契约派生（Agent 首次能看到 `experiment`，此前靠字面量硬编码六类）。
- **幽灵常量修正**：`WORKBENCH_VERSION_EXPECTED` 改为直接读 `VERSION`，不再抄一份写死的 `v260924.1`。
- **工作区骨架归一（P19）**：`WORKSPACE_LAYOUT` 由两处（`app/workspace.py` 22 项、`mcp/constraints.py` 17 项）合并为一处 22 项，`knowledge/constraints` 的 storage 主题不再漏掉 `Knowledge/Literature/{PDF,Annotations,Notes,Index,Previews}`。
- **验证**：`python tools/kb_smoke.py` 全绿（199 条 / 关系边 1854）；`python -m mcp.server --selftest` 的 `problems` 为空；新增等价性核对 `.scratch/tmp/verify_contract_equiv.py` —— 七类正文骨架与旧实现**逐字一致**，kind→目录/标签/状态机/日期字段/关系映射四张表**逐项一致**。
- **导入期副作用清零 + 顺序炸弹拆除（P13/P21）**：`app/config.py` 尾部的 `load_secrets()` / `reload_all()` 移除，改为显式 `config.init()`，由 `server.build_server()` 与 `mcp.bridge.Workbench` 调用；其余访问器保留 `if not _cache: reload_all()` 惰性兜底。收益：`import app.config` 不再读写用户配置（迁移路径原先会落盘 `app.json`/`secret.json`），且 `config → agent_tools → store → workspace → config` 的循环导入死结解开——实测 `app.config` / `app.store` / `app.workspace` / `app.agent_tools` / `app.agent` / `app.literature` / `app.perf_index_query` / `app.projects` **每一个都可作为入口直接 import**（此前 `import app.agent_tools` 直接 `AttributeError: partially initialized module`），`python -c "import server"` 前后 `config/` 目录 mtime 不变。
- **层级解耦（P12）**：`app/perf_index_query.py` 不再在导入期 `import agent`（会话搜索改为函数内惰性导入），实测导入查询层/索引层后 `app.agent` 不在 `sys.modules`；跨模块私有调用改走新公开入口 `store.doc_from_path()` / `store.academic_progress()`。
- **死代码清理（P11）**：删除全仓零引用的 `app/project_bridge.py`（52 行）。`app/search.py` 仍被 `mcp/bridge.py` 与 `tools/self_check.py` 使用，暂留待并入内核检索时再处置。
- **端到端复核**：在备用端口 8799 以新代码起了一个实例，`/api/dashboard` 返回 `experiment:25 / 199 条`，`/api/docs?kind=experiment` 列出 25 条，索引 `document_links.role` 八类分布与 1854 条 `graph_edges` 全部保留——**「重启即丢 25 条实验」的风险已消除**（验证后退掉该实例）。
- **vendor 按需加载（A1，前端首屏）**：`mathjax-tex-svg.js`(2.11 MB) 与 `mermaid.min.js`(2.57 MB) 原先在 `index.html` 里**无条件 defer**，首屏就要下载。新增 `web/vendor-lazy.js` 提供 `window.erwVendor.load('mathjax'|'mermaid')`（共享 Promise、只加载一次、失败回退 CDN、可重试）与 `hasMath()` 判断；四处调用点改为真正用到时才 `await`：`app.js` 的 Markdown 预览与 Mermaid 渲染、`v260922-graph-performance.js` 的图谱节点预览、`v260930-floating-agent.js` 的对话气泡。**首屏 5.23 MB → 0.77 MB（−4.46 MB / −85%）**，`/vendor/mathjax-tex-svg.js` 与 `/vendor/mermaid.min.js` 已不在首屏引用列表内（核对脚本 `.scratch/tmp/a1_payload_compare.py`）。纯文本预览不会拉 MathJax；离线时 MathJax 静默降级、Mermaid 保留原有「渲染库暂未加载」提示。
- **A2 第一刀：装配清单化 + 前端静态体检闸门 + 连续补丁合并**：
  - **装配清单**：新增 `web/manifest.json` 与 `tools/web_manifest.py`（`--write` / `--check`）。`index.html` 原先手写 11 个 `<link>` + 15 个 `<script>`，顺序有语义（`v260922-performance.js` 包装 `window.fetch`，必须排在 `app.js` 之前）却无处校验；现在三段引用块由清单生成，顺序只有一处声明，`--check` 可在提交前拦住漂移。
  - **静态体检闸门**：新增 `tools/web_check.py`（只读）——① 语法（全部业务 JS 过 `node --check`、CSS 花括号配平）；② 清单↔`index.html` 一致；③ 清单↔磁盘双向缺失（新增前端模块不登记即报错）；④ **接缝完整性**：任何 `window.ERW*` 的消费方必须有定义方、任何自定义事件的监听方必须有派发方；⑤ 加载顺序约束。这条闸门正对 `17682ce`（一个补丁的语法错误直接打掉整个 PDF 工作区）那类事故——现在提交前就能拦住。
  - **连续补丁合并**：`v260922-projects.js`、`overview-editor-tools`、`graph-performance`、`overview-graph`、`agent-profiles` 五个**在加载顺序上连续**的 IIFE 补丁合并为 `web/v260922-research-pages.js`，业务 JS **11 → 7 个**。合并前提经程序复核：5 个文件都是 `(() => {…})();` 且**顶层声明为 0**、彼此只经 `window`/事件/DOM 通信，且合并后放回第一个补丁的位置 → 全局顺序与文件内顺序都不变。复核脚本比对 git 中源文件：**payload 与按序拼接逐字一致（80,995 B），5 个 IIFE 原样**。
  - **未做 CSS 主题合并（有意）**：11 个 CSS 在加载顺序上不构成连续的主题分组（`styles.css` 之后各补丁互相覆盖），合并会改变层叠顺序，收益（少几次请求）不抵风险；留待与 A9 钩子倒置一并处理。
  - 顺带：`.gitignore` 放行 `web/**/*.json`（清单需入库）；本机 `AGENTS.md`（**当前不在版本库内**，见文末待决项）补「动 `web/` 必跑 `web_check.py`」「引用块不要手改」两条，并更正两处过期描述（`mcp/` 早已入白名单、新增 `core/` 契约层）。
- **P3 首件：`python -m core.doctor` 只读体检**：新增 `core/doctor.py`，把「契约 / 磁盘 / 派生索引」三者一致性从人眼检查变成一条可重复的命令。22 个检查项：契约自洽（字段序 vs 创建/更新字段）、磁盘条目数与索引逐类对照、`id` 前缀与 kind 漂移、**status 越界**、**kind_marks 越界与缺契约强制标记**、**缺法定日期**、title≠首个 H1、标题不合命名规范、未声明字段、**项目归属幽灵行**、**不可解析的关联链接**、回收站目录漂移、同步冲突残留、索引体积与 WAL、派生库归属与冲突副本、`schema.json` 与代码版本一致。支持 `--json`（机器可读）与 `--strict`（有 error 级发现时非零退出）。
  - **首次实测（2026-10-09，199 条）**：`error` 级 2 项 —— `idea-20260924104458-90ee1b` 的 `status=进行中` 越界（该类型状态机只有 待整理/探索中/已采纳/已归档）、`note-20260930121751-769a43` 的 `kind_marks` 含 `知识-方法` 与 `术语清单`（不在 10 个合法标记内）；`warn` 级 8 项 —— 25 条 `note-*` 前缀的 experiment（§5.3 已明确 id 不承载类型语义）、2 行幽灵归属（`document_projects` 有 name 无 id）、2 条不可解析链接（`DUST-实验方案`/`DUST-数据集说明`）、`System/Trash/knowledge` 非现役 kind、4 个同步冲突文件、`index-冲突-Moxise_Win11.sqlite` 6.8 MB、WAL 21.4 MB（超过库体量 60%）。**均为只读发现，本轮未改动任何用户数据。**
- **P1 补齐：写入期字段校验（P16 根因修复）**：新增 `core/contracts/validate.py` —— status 必须落在该类型状态机内（`F002`）、`kind_marks` 必须是合法标记 id（`F003`）、更新时**显式**漏掉契约强制标记则拒写（`F004`，建档路径仍自动补齐）、日期必须 `YYYY-MM-DD` 且只用于该类型的日期字段（`F005`/`F006`）、未声明字段告警（`F007`）。
  - `app/store.py` 的 `create_doc`/`update_doc` 与 `mcp/tools_knowledge.py` 的 `kb_create_entry`/`kb_update_entry` 现在消费**同一份**校验器：越界 status/标记在两条路径上都被拒（此前写入期零校验，正是 doctor 那 2 个 error 的来源）。`create_doc` 同时按契约补齐标记——此前只有 MCP 侧补、HTTP 侧不补，属两条路径行为不一致。
  - `update_doc` 的可写字段白名单改由契约 `UPDATE_FIELDS` 派生（原先在 store 里手抄 18 项，又是一处会漂移的副本）。
  - `tools/kb_smoke.py` 新增第 7 组共 14 条断言（越界 status/标记被拒、合法值放行、强制标记语义、日期格式、未声明字段、两条写入路径结论一致），**全绿**；并复核冒烟仍严格只读（`activity.jsonl` 945 行、`Knowledge` 200 个 md 前后不变）。
  - 注：本轮**未修**库里已有的 1 条越界 status 与 2 条越界标记——按 AGENTS.md「`Workspace/` 是用户数据」，修数据需确认后走 `kb_*` 工具，不手改文件。
- **P3 第二件：索引结构迁移框架（§5.5.2）**：
  - 新增 `core/index/migrations/` —— `m0001_documents_attachment`（v1→v2）、`m0002_document_links_role`（v2→v3），每个迁移声明 `ID / TITLE / FROM_VERSION / TO_VERSION` 与 `apply(conn)->bool`（是否真改动）、`verify(conn)->(ok, detail)`、`rollback(conn)->bool`；`core/index/migrate.py` 负责编排：读当前版本 → 列待执行 → **默认 dry-run** → 备份 → 执行 → 验证，CLI 为 `python -m core.index.migrate [--apply | --rollback --to N] [--db] [--json]`。
  - **替换**原先内联在 `app/perf_index_db._init_db()` 里的四段 if（没有声明、没有验证、没有回滚、没有备份，出问题只能删库重建）。
  - **版本单一入口**：`app/perf_index_db.SCHEMA_VERSION` 改为读 `core.index.migrate.TARGET_VERSION`（= 迁移清单里的最大目标版本），不再写死数字——§5.5.1 点名的「5 处版本号各自演进」少了一处。
  - **新增硬护栏**：磁盘库版本**高于**代码版本时拒绝写入并给出可执行提示（防旧 exe 打开新 Workspace 把结构改坏）；`core.doctor` 新增「索引·结构迁移状态」一并报出该状态与待执行迁移。
  - 备份走 SQLite 自己的 backup API（WAL 下也得到一致快照），落在 `Workspace/System/Backups/<时间戳>-pre-v<N>.sqlite`。
  - **验收**（`.scratch/tmp/verify_migrations.py`，24 项全通过）：在合成的 v1 旧库上 —— dry-run 后结构与版本**逐字节不变**；apply 补出 `attachment`/`role` 两列并升版到 3、`documents` 数据保留、`document_links` 按设计重建（纯派生数据，由索引器回填）；二次执行为 no-op 且 verify 仍通过；`rollback` 可逆回 v1（两列移除、版本回落）；**全新库**走 DDL 后迁移为 no-op、标记需全量建索引；`_init_db` 对版本 99 的库抛 `MigrationError`。CLI 端到端（dry-run → apply → 再 apply → rollback）实跑通过。真实库只读 dry-run 确认 `v3 → v3 已是最新`；服务侧 `indexer.initialize()` 实跑后索引仍为 **199 条 / 1854 边**、八类 `document_links.role` 分布不变。
- **A3 派生数据治理：索引维护工具 + 关库 checkpoint + 实测瘦身 ≈49.9 MB**：
  - 新增 `core/index/maintain.py`：`python -m core.index.maintain [--checkpoint] [--vacuum] [--json]`（默认只读统计）。checkpoint 走 `PRAGMA wal_checkpoint(TRUNCATE)`；VACUUM 前自动备份到 `System/Backups/`；VACUUM 需要独占访问，工作台运行时会被锁挡住并给出提示。
  - **实测发现（更正方案 §5.5.3 的假设）**：索引库文件 35.70 MB，而 `dbstat` 逐对象求和只有 **7.19 MB 活数据** —— `PRAGMA freelist_count` 显示 **7299/9139 页是空闲页（80%，28.51 MB）**，另有 **21.39 MB** 的 `-wal` 未 checkpoint。因此「索引瘦身」的真正收益在**维护**，不在原先假设的「删可推导边 / 砍 FTS 列」：`tag`+`project` 边 1356 行 ≈ 0.25 MB、FTS 的 `title/body/tags/projects` 四列 ≈ 0.8 MB，两项合计不到 1 MB。
  - **已执行**（执行前备份 `Workspace/System/Backups/20261009-155909-pre-vacuum.sqlite`，37.4 MB）：WAL 21.39 MB → 0，库文件 35.70 MB → **7.14 MB**，合计回收 **≈49.9 MB**。**语义中性已程序证明**：原库 vs 处理后副本逐项比对 10 组查询（条目总数、按 kind 计数、八类 `document_links.role`、`graph_edges` 关系分布、tags/marks/projects 行数、两组 FTS 关键词命中、标题样本）与 38 个 schema 对象**完全一致**；处理后 `kb_smoke` 全绿（199 条 / 1854 边）、`doctor` 结果不变、运行中的实例仍返回正确计数。
  - **防止复发**：新增 `app/perf_index_db.checkpoint()` 与 `indexer.checkpoint` 门面；`server.py` 退出与 `client.py` 窗口关闭时自动 `wal_checkpoint(TRUNCATE)`；`core.doctor` 新增「索引·体积与空闲页」检查（空闲页 >30% 或 WAL >30% 库体量时告警并给出维护命令，已用合成膨胀库正向验证）。
- **A13 收尾：恢复「页面能不能点开」的自动闸门**（P29，前几轮唯一缺失的验证能力）：
  - 新增 `tools/ui_smoke.py` —— 真浏览器逐路由走查，**只读 DOM/控制台/网络，不截图**（文本优先）。断言：首屏无 console error / 无失败请求；`web/app.js` 里 `NAV_GROUPS` 声明的**每个路由**都点得开且渲染出内容（期望路由从 `app.js` 解析，不另抄清单）；首屏**不请求** mathjax/mermaid（A1 的按需加载是硬约束）；`window.erwVendor` 与补丁接缝（`ERWLiterature`/`ERWBilling`/`ERWFabTimeline`/`ERWNav`）齐备。支持 `--base-url` / `--json` / `--strict`。
  - **不要求下载浏览器**：脚本复用机器上已有的 Chrome / Edge / `ms-playwright` 里的 chromium（也可用 `ERW_BROWSER` 指定），只依赖 `playwright` 这个 Python 包。
  - **实测结果**：对**用当前代码新起的实例**（备用端口 8799）走查 —— 页面标题「概览 · 科研工作台」，**17 个路由全部可渲染**、console error **0**、失败请求 **0**、首屏重型库请求 **0**；实验页标题「实验」并渲染出真实实验内容（基线对齐在真实 UI 中生效）。同一脚本对 8765 上的旧实例同样全绿。
  - 顺带核实 `tools/shot_page.py` 在本机可直接用（它自己探测 Windows/macOS/Linux 的 Chrome/Edge 路径，不依赖 playwright）：实拍一张裁剪图，`1000x700 ≈428 tokens → 521x576 ≈243 tokens`。
- **A10：拆掉全局 `window.fetch` 猴子补丁，改为运行期接缝**：
  - 原先 `v260922-performance.js` 在**求值期**执行 `window.fetch = ...`：给 `/api/docs` 加分页参数并把分页信封**拆回数组**、给 `/api/graph` 加限流并改写 `/api/graph/overview`、给 `/api/search` 挂可取消的 AbortController，同时派发 `workbench:docs-page` / `workbench:graph-meta`。这正是 P14 点名的「补丁无法摘除 + 假加载顺序依赖」。
  - 现在改为提供 `window.erwFetch` 显式接缝，各模块的 `api()` 用 `(window.erwFetch || fetch)` **运行期解析**：`app.js`、`literature.js`、`v260930-floating-agent.js`、`v261008-billing.js`、`v260922-research-pages.js`（3 处 `api()` + 2 处直连 `/api/docs`、`/api/graph/overview`）。
  - **行为等价经真浏览器验证**（`.scratch/tmp/verify_a10.py`）：`window.fetch` 已恢复原生（`function fetch() { [native code] }`）；分页器「1/2 页 · 共 90 条」、请求带 `paged=1&page=1&page_size=50`、点「下一页」→「2/2 页」且列表内容变化；图谱状态条「当前加载 199 / 199 个知识节点」（`graphMeta` 事件仍通）；全局搜索返回结果；全程无 console error。
  - **不变量改为静态可查**（`tools/web_check.py`）：① 任何模块**不得**给 `window.fetch` 赋值（P14 红线）；② `window.erwFetch` 提供方有且只有一个；③ 每个自带 `api()` 的模块必须走接缝（否则会静默丢分页/限流/取消）。扫描前先剥注释，负向用例已验证（代码违规能抓到、注释里提及不误报、消费方不被误计为提供方）。`tools/ui_smoke.py` 同步在运行期断言接缝存在且 `window.fetch` 未被替换。
  - 「必须排在 `app.js` 之前」的旧约束随之作废（`app.js` 的引导挂在 `load` 事件上，任何请求都晚于全部 defer 脚本求值）；清单说明改为「非强制，但保持最先加载更稳」。
- **A9/§6.3：前端面板注册表 —— 内核不再硬编码具体功能**：
  - 新增 `window.ERWPanels`（`register` / `list` / `get`）：功能模块自行登记**导航项 + 页头元数据 + 渲染函数**；`app.js` 的 `navGroups()` 合并登记项（支持 `before` 保持既有顺序），`setHeader()` 与 `navigate()` 增加面板分支（内核路由优先级仍高于面板）。
  - **用量计费整体搬出内核**：删掉 `app.js` 里的导航项 `['billing','用量','▩']`、`PAGE_META.billing`、`navigate()` 的 billing 分支与 `renderBillingPage()`；改由 `v261008-billing.js` 自己 `ERWPanels.register`。这正是 P14 与 §6.7 红线 5「内核功能依赖某个补丁才能工作」——现在删掉计费模块**只会少一个导航项，不会白屏**。
  - **等价性经真浏览器验证**（`.scratch/tmp/verify_panels.py`，9 项全通过）：侧栏导航项与顺序**与改造前逐项一致**（用量仍在设置之前）、billing 是面板登记项且出现在侧栏、`#billing` 渲染出内容、页头「SYSTEM / 用量统计」由面板元数据提供、全程 0 console error；静态复核 `app.js` 实现里已无任何 billing 痕迹。
  - **不变量进闸门**：`web_check` 新增「**app.js（内核）不得调用 `ERWPanels.register`**」（面板应由功能模块自行登记）并列出面板自登记模块；`ui_smoke` 断言注册表存在、**每个登记面板都真的出现在侧栏导航里**，并把这些面板路由一并走查 —— 期望路由 = `app.js` 声明 ∪ 运行期面板，不另抄清单。
  - **「内核零插件可跑」已实测**（`.scratch/tmp/drop_billing.py`）：把 `v261008-billing.js` 从 `web/manifest.json` 摘掉并重新生成 `index.html` 后起实例，`ui_smoke` 报 **16 个路由全部可渲染、0 console error、0 失败请求、装配接缝缺失 0 个、面板登记 0 个** —— 即「删掉计费 = 少一个导航项」，不再是白屏。实验后已还原清单与 `index.html`（`--check` 一致）。
  - 顺带修掉 `ui_smoke` 自身的一处**过期硬编码**：原先把 `ERWBilling` 等写死在「必备接缝」里，导致上述实验被误判失败。现改为**从装配清单推导**——只检查「已装配模块消费的接缝是否都由已装配模块提供」（装配自洽性），并区分状态型接缝（如 `ERWCurrentDoc` 仅在打开条目后赋值，首屏为空是正常的）。
- **§6/P5 首件：插件运行时（内核侧：发现 / 校验 / 依赖解析）**：
  - 新增 `core/plugins/manifest.py` —— `plugin.json` 契约的唯一实现（PLUGIN_SPEC §3/§4/§7）：规则码 `P000–P018`，覆盖 id 合法性与**目录名必须等于 id**、语义化版本、`api_version` 匹配（I7）、`core_min`、`kind`/`distribution`、`entry` 文件存在、**未支持权限拒载**、**路由必须是相对路径**（不得写裸 `/api/...`）、**MCP 工具名不得自带前缀**（前缀由内核加）、`settings_schema` 形状、依赖项自依赖/重复、**`storage.derived_db` 只允许 `System/Cache/<id>.sqlite`**、`nav.mount` 文件存在。所有 `error` 级问题都带可执行的修复建议。
  - 新增 `core/plugins/registry.py` —— 两个来源（`ASSET_ROOT/plugins` 随包优先，`DATA_ROOT/plugins` 用户库）的发现、**状态机**（`available` / `blocked` / `rejected` / `conflict`）、**拓扑排序与环检测**（§4.2.1 检测到环整环拒载）、缺失前提插件 → `blocked` + 「缺什么、怎么补」（§4.2.3）、同 id 多来源按 §1 规则 ASSET 优先并给出提示、`System/plugins.json` 的安装意图读取。
  - 新增 `core/plugins/__main__.py` —— CLI `list` / `check <id>` / `verify`（PLUGIN_SPEC §5），把权限用人话列出、把路由挂载点与工具前缀提前说明；有 `rejected`/`blocked`/`conflict` 时非零退出，可直接当闸门。
  - 新增 `tools/plugin_check.py` —— 隔离体检：**I2**（`core/**`、`app/**`、`server.py` 都不得 import 插件实现）、**core 不得 import app**、**空插件集是合法状态**；`--assert-core-only` 额外跑 `kb_smoke` 作为「零插件下核心完整可跑」的代理（I1）。
  - 新增 `plugins/README.md` —— 丢进去就能用的约定速查（目录名=id、相对路由、裸工具名、派生库路径、权限集合、不得 import 私有模块、核心不依赖插件）。
  - **诚实边界**：本阶段**不含执行层**（`register(ctx)`、路由/工具/面板的挂载与卸载、I3/I4/I8/I10 的运行期校验），状态因此只报「已校验、可加载」而**不谎报 `enabled`**；这些随第一个真插件一并落地（前端面板接缝 `window.ERWPanels` 已在 `498d994` 就位）。
  - **验收**：21 项夹具断言全通过（`.scratch/tmp/verify_plugins.py`）—— 合法插件 available、依赖满足 available、**8 类违规各自被拒**（id 非法 / api_version=99 / 裸 `/api` 路由 / 自带前缀工具名 / 未支持权限 / 派生库路径 / `core_min` 过高 / entry 缺文件）、依赖缺失 → `blocked`、**依赖成环 → 整环 blocked**、同 id 双来源 ASSET 优先（保留 1.2.0）、加载顺序把前提插件排在依赖者之前、被拒/被阻的插件不进加载顺序。CLI 对夹具库实跑通过。
  - **顺带修掉一个真问题**：`tools/plugin_check.py` 的新不变量当场抓出 `core/doctor.py` 在 import `app`（第二轮为比对 schema 版本引入）。已改为从 `core.index.migrate.TARGET_VERSION` 取代码侧版本 —— `core/` 重新做到零 `app` 依赖。
- **§6/P5：插件前端管线 + 首个真插件「专注计时」**：
  - 内核侧新增 `GET /api/plugins`（只下发「已校验可用 且 生效启用」的插件与其面板入口）与 `GET /plugins-file/<id>/<rel>`（提供插件自带静态资源，**只允许插件目录内的文件**）。「开不开」的判定落在 `core.plugins.registry.effective_enabled`：`System/plugins.json` 有记录用记录，没有记录用 manifest 的 `default_enabled`（随包附属默认开、可选默认关）。实测：无记录 → 出现；显式 `enabled:false` → 消失；`enabled:true` → 出现。
  - 新增 `web/plugin-host.js`：按清单加载面板脚本，面板在 eval 期自登记 `window.ERWPanels`；`app.js` 在建侧栏前 `await ERWPluginHost.ready`（否则插件导航项要等下一次渲染才出现）。**单插件失败不影响内核与其它插件**（I4），失败原因明示并附排查命令（I11）。
  - **首个真插件 [`plugins/focus/`](plugins/focus/plugin.json)**：把专注计时从 `app.js` **原样搬出**（逻辑与标记未改写，只把内核内部的 `$`/`$$`/`toast` 换成等价的本地实现），localStorage 键沿用 `focusMinutes`/`breakMinutes`（老用户设置不丢）。`app.js` 删掉导航项、`PAGE_META.focus`、路由分支、`renderFocus` 簇、`state.focus` 与两处 localStorage 读取 —— 内核不再认识「专注」。
  - **端到端验收**（`.scratch/tmp/verify_focus_plugin.py`，真浏览器）：`/api/plugins` 下发 focus、面板脚本确实被请求、`ERWPluginHost.loaded=['focus']` 且 failures 为空、**侧栏 17 项与顺序逐项不变**（专注仍在「待办」与「Agent」之间）、`#focus` 由插件面板渲染出计时器、点「开始」倒计时真的在走（25:00 → 24:58，按钮变「暂停」）、暂停/重置可用、改时长写回 `focusMinutes=45`/`breakMinutes=10`、**全程 0 console error**、内核源码已无任何专注痕迹。
  - **路径安全**（`.scratch/tmp/verify_plugin_assets.py`，用**未归一化**的原始请求行，避免客户端先把 `..` 归一化掉）：10 例全通过 —— 正常面板 200、插件自身文件 200、编码 `../` 与多次穿越 403、未知插件 404、缺 id/子路径 400，且无源码泄漏。
  - `plugin_check` 新增**面板契约**不变量：声明了 `nav` 的插件，其 mount 脚本必须自登记 `ERWPanels` —— 否则脚本会「正常加载但什么都不做」，属静默失败。
  - **顺带修掉一个真 bug，并让闸门变确定**：`/api/weather` 在离线时 `URLError` 冒泡成 **500 + 浏览器 console error**，既让「天气」卡片报错，也让 `ui_smoke` 的「无 console error」断言随天气缓存 TTL 时好时坏（**不确定的闸门比没有闸门更糟**）。现改为：先退回**陈旧缓存**（带 `stale:true` 与可读原因），无缓存则返回显式的 `unavailable` 载荷；`geocode` 同样不再抛异常。实测离线返回陈旧数据 +「网络不可达（连接被拒绝）」，`/api/weather` 恢复 200，失败请求归零。
- **§6/P5：插件后端执行层（`register(ctx)` / 路由分发 / 命名空间隔离）**：
  - 新增 [`core_api.py`](core_api.py)（仓库根）：插件**唯一允许** import 的内核门面 —— `log` / `plugin_dir` / `cache_db` / `workspace_dir` / `system_dir` / `config_path` / `read_config` / `write_config`。保持最小面，要加是有意的动作（须同步 PLUGIN_SPEC §6）。
  - 新增 [`core/plugins/context.py`](core/plugins/context.py)：`ctx`（`PluginContext`）—— `routes.get/post/put/patch/delete`（**声明期**就强制相对路径、拒裸 `/api/*`、拒重复，错误信息直接给出正确挂载点）、`mcp.tool(name, spec, handler)`（只收裸名，对外名内核加 `p_<id>__`）、`storage`（只给插件自己命名空间内的路径，I5）、`config_read/config_write`、`log`。**未实现的不假装有**：`jobs` / `events` / `search.addSection` 明确列为待做。
  - 新增 [`core/plugins/loader.py`](core/plugins/loader.py)：按拓扑顺序执行 `register(ctx)`；**每插件独立 `try/except`**（I4）——注册失败记为 `failed` + 可读原因并继续跑其它插件；路由冲突按条拒绝并记原因；`dispatch()` 按 `(METHOD, 完整路径)` 查表，handler 抛异常**只影响该次请求**（500 且带插件 id）。
  - `server.py`：`build_server()` 启动时加载插件（按拓扑顺序打印、失败打到 stderr）；`/api/plugins/<id>/<rel>` 在 **GET/POST/DELETE** 三个入口统一分发；`ERW_PLUGINS_ROOTS`（`|` 分隔）可覆盖扫描根，便于测试与便携安装。
  - `plugin_check` 新增 **I3 静态检查**：插件后端只允许 import 标准库与 `core_api`；`core.*` / `app.*` / `mcp.*` / `server` 一律拦下（负向用例 6 例验证：注释里的 import 不误报）。
  - **验收**（`.scratch/tmp/verify_plugin_api.py`，19 项全通过，起真服务）：GET 路由拿到 query、POST 路由拿到 body、挂载点确为 `/api/plugins/<id>/<rel>`、`ctx.storage` 落在 `Workspace/Plugins/<id>` 与 `System/Plugins/<id>`、配置写 `config/plugins/<id>.json`、MCP 工具暴露为 `p_hello__hello_now`；**`register` 抛异常的插件记为 failed 且内核与其它插件不受影响**；**裸 `/api/docs` 路由在声明期被拒**并给出挂载点提示；未注册路径 404、handler 抛异常 500（带插件 id）、内核路由与 `/api/plugins` 清单均不受影响。（夹具运行期产物已清理，未留在 `config/` 与 `Workspace/`。）
  - **顺带修正我自己的一个 bug**：加载器最初把 `/api/plugins` 当「内核保留前缀」，导致**所有**插件路由被拒 —— 正是上面这套验收当场抓出来的；插件路由天然带命名空间前缀，与内核路由不可能撞，现在只保留插件之间的冲突检查。
  - **诚实边界**：后端执行层已可用但**尚无真功能消费者** —— 首个插件 `focus` 是纯前端，`register(ctx)` 要等把某个带后端的功能（天气/RSS）搬成插件时才有实战检验。
- **§6/P6 首件：把「资讯（RSS）」整体搬成插件**（后端执行层的第一个真消费者）：
  - 新增 [`plugins/rss/`](plugins/rss/plugin.json)：`plugin.json`（路由 `feed` / `config`、面板 + 自带样式、权限 `net:http`/`storage:own`/`config:own`/`ui:panel`）、`backend.py`、`web/panel.js`、`web/panel.css`。
  - **后端**：`app/rss.py`（166 行）原样搬入 `backend.py`（解析/抓取/去重/陈旧回退逻辑未改写），三处适配 —— 配置来源改为插件自己的 `config/plugins/rss.json`、缓存改为 `Workspace/System/Plugins/rss/cache.json`（只碰自己命名空间，I5）、入口由 `fetch()` 改为 `register(ctx)` 注册三条路由。**首次运行自动把内核 `config/rss.json` 的 9 个源迁移过来**（实测已迁移，老用户配置不丢，PLUGIN_SPEC §11.3）。
  - **前端**：`app.js` 的 `renderNews`（资讯列表 + 源筛选 + 刷新 + 诊断）搬入面板并自登记 `ERWPanels`；资讯源编辑（原设置页的一个 tab）改为**面板内联**；样式按 §2 从 `styles.css` 搬入 `web/panel.css` 并统一加 `[data-plugin="rss"]` 作用域（宿主新增 `nav.style` 支持）。
  - **内核删除**：`app/rss.py`、`/api/rss`、`/api/config/rss`、`config.py` 的 `DEFAULT_RSS_CONFIG`/`get_rss`/`save_rss` 与 `get_all()` 里的 `rss`、`app.js` 的导航项/`PAGE_META.news`/路由分支/`renderNews`/设置页资讯源 tab/`sourceRow`+`wireSourceRows`、`styles.css` 的 news-*/rss-*/source-row 规则、`server.py` 的 rss 导入与 `clear_cache` 调用。`tools/self_check.py` 的 RSS 解析测试改为按路径加载插件后端（覆盖不丢）。
  - **端到端验收**（`.scratch/tmp/verify_rss_plugin.py`，17 项全通过）：`/api/plugins` 同时下发 focus 与 rss（含面板与样式 URL）· 面板脚本与插件样式均被请求 · 宿主 `loaded=['focus','rss']` 且 failures 为空 · **侧栏 17 项与顺序逐项不变**（资讯仍在 Agent 之后）· `#news` 由插件渲染且**插件样式生效**（`.news-grid` computed `display:grid`）· 资讯源设置内联可用且**9 个源已迁移** · 插件路由 `feed`/`config` 可用（离线也 200 + 源状态）· **内核 `/api/rss` 已 404** · 内核 Python 已无任何 rss 痕迹 · 全程 0 console error / 0 失败请求。
  - **有意变化（PLUGIN_SPEC §11.2 显式声明）**：资讯源设置从「设置页的一个 tab」移到「资讯页内联」——插件拥有自己的 UI，内核不再知道「资讯源」这个概念；接口从 `/api/rss`、`/api/config/rss` 变为 `/api/plugins/rss/*`。
- **§8 ②：插件 MCP 工具接入内置 Agent**（此前 `ctx.mcp` 注册的工具只在加载结果里收集，从未进入 Agent 工具面）：
  - 新增 [`core/plugins/runtime.py`](core/plugins/runtime.py)：进程级持有当前 `LoadResult`，外部只读 `current()` / `tools()` / `tool_specs()` / `route_map()` / `summary()`；唯一写入点是 `loader.load()`（避免各处持副本或反向依赖 `server.py`）。
  - `loader.load()` 结束时登记到 runtime；**声明 `write: true` 的插件工具被明确拒绝注册**并给出原因 —— 插件写工具要走内核的草稿确认流，那条链路还没有插件分支，**不半接**以免留下「绕过确认直接落盘」的口子。
  - `app/agent_tools.py` 的工具面全面动态化：新增 `plugin_tool_meta` / `all_tool_meta` / `all_tool_names`，`openai_specs` / `text_protocol_prompt` / `is_write_tool` / `list_tool_meta` 改为读统一视图；`execute()` 未命中内核工具时查插件工具（`handler(args, ctx)`），异常只影响该次调用，返回值带 `plugin` 字段，人设白名单同样生效。`app/agent.py` 与 `app/config.py` 的白名单过滤改用 `all_tool_names()`（人设可勾选插件工具）。`server.py` 的插件路由分发改读 `runtime.current()`（与工具面同一份状态）。
  - `plugin_check` 新增不变量：**manifest 声明的 `mcp_tools` 必须真的在入口里注册**（声明了却不可用 = I10 反例）。
  - **验收**（`.scratch/tmp/verify_plugin_tools.py`，17 项全通过）：未加载时插件工具不存在且调用返回「未知工具」· 加载后读工具进入 `all_tool_names`/`openai_specs`/文本协议/`list_tool_meta`（带 description 与 plugin）· `execute` 调用成功且带 `plugin` · handler 抛异常只影响该次调用 · 人设白名单可限制 · **`write:true` 工具被拒且原因可读** · HTTP 面 `/api/agent/tools` 含插件工具、不含被拒的写工具 · **无插件时工具面与改造前完全一致**（6 个内核工具）。
- **A9 收尾：7 处文档级 `MutationObserver` 收敛为 1 个共享接缝**：
  - 新增 [`web/dom-seam.js`](web/dom-seam.js)：`window.ERWDom.onChildList(cb, {root, ignore})` —— **一个** MutationObserver 观察 `documentElement` 后按订阅方分发，提供 ① `root` 作用域（保持各补丁原有的观察范围）② `ignore` 过滤（浮球面板 / PDF 阅读区的高频增删）③ **按帧合并**（一帧内多次变更只回调一次）④ **回调隔离**（某订阅方抛异常不影响其它订阅方与内核）。
  - 7 处改写：`v260922-performance.js`（带 ignore 过滤）、`v260922-research-pages.js` 的 5 处（projects / overview-editor-tools / overview-graph / graph-performance / agent-profiles，各自保留 `root` 作用域）、`v260922-layout-bugfixes.js`。**保留** `layout-bugfixes.js` 中那个只观察单卡片行内样式的**属性观察**（语义不同，不属于本轮范围）。
  - **不变量进闸门**：`web_check` 禁止在 `dom-seam.js` 之外自建「配置含 `childList`」的 MutationObserver（负向用例 5 例已验证：自建能抓到、属性观察与注释里的提及不误报）；`ui_smoke` 在运行期断言 observer 实例 == 1、订阅方 ≥ 5。装配清单新增 `dom-seam.js` 并置于所有补丁之前（补丁在求值期就要注册）。
  - **验收**（`.scratch/tmp/verify_dom_seam.py`，8 项全通过，真浏览器）：observer 恰好 **1** 个、订阅方 **7** 个（7 处全部接上）· **作用域生效**（改侧栏不唤醒 `#main` 作用域的订阅方）· **按帧合并**（一帧 3 次变更 → 1 次回调）· **隔离生效**（故意抛异常的订阅方不影响其它，且不泄漏 console error）· **装饰等价** —— 文档分页器「1/2 页 · 共 90 条」与图谱状态条「当前加载 199 / 199」仍由接缝驱动出现。`ui_smoke` 17/17、A10 行为验证、RSS/focus 插件 E2E 全部回归通过。
- **§6/P6 第二件：把「天气」整体搬成插件，并新增顶栏槽位扩展点**：
  - **新扩展点（槽位面板）**：`ERWPanels.register({id, slot:'topbar', renderSlot(container)})` —— 内核在顶栏提供挂载点 `#topbar-slot[data-erw-slot="topbar"]`，并给容器加 `data-plugin="<id>"`，插件只在这个容器里画东西（**不去改内核 DOM**），样式按 §2 作用域。已知槽位在 `core/plugins/manifest.KNOWN_SLOTS`（新增 `P019` 校验）与 `app.js` 的 `ERWPanels.SLOTS` 两处对齐。
  - 新增 [`plugins/weather/`](plugins/weather/plugin.json)：`backend.py`（`app/weather.py` **原样搬入**：天气码表 / 缓存 TTL / 地名解析 / 离线降级）、`web/panel.js`（顶栏卡片 + 设置模态）、`web/panel.css`（天气专有样式）。**配置迁移**：首次运行把内核 `config/app.json` 的 `weather` 段搬进 `config/plugins/weather.json`（实测迁移到用户真实地点「上海市浦东新区」）；缓存改到 `System/Plugins/weather/`。
  - **内核删除**：`app/weather.py`、`GET /api/weather`、`GET /api/weather/geocode`、`config.py` 的 `weather` 默认段、`app.js` 的 `loadWeather` + 设置页天气 tab + 顶栏卡片、`styles.css` 的 `.status-dot` 与窄屏隐藏规则。
  - **顺带修掉一个真 bug（被闸门当场抓出）**：槽位面板曾被 `navGroups()` 一并塞进侧栏导航，于是冒出一个没有页面的 `#weather` 路由，并在 `navigate()` 抛 `render is not a function`。现在 `navGroups()` 跳过槽位面板、`navigate()` 用 `?.render` 守卫。
  - **闸门同步**：`ui_smoke` 区分**导航面板**（须出现在侧栏、须可走查）与**槽位面板**（须真的挂到对应槽位）；`plugin_check` 的面板契约检查覆盖全部插件；`manifest.py` 新增 `P019`（`nav.slot` 必须是已知槽位）。
  - **验收**（`.scratch/tmp/verify_weather_plugin.py`，16 项全通过）：插件清单含 weather（面板 + 样式 URL）· 配置路由可用且已迁移真实地点 · 内核 `/api/weather` 已 404 · **顶栏槽位容器存在且插件把自己的卡片画了进去** · 卡片文本已填充（离线降级显示「天气不可用」）· **插件样式生效**（status-dot 7px 圆点）· 点卡片弹出**插件自己的设置模态**（地点/经纬度/时区/启用 + 搜索坐标 + 保存并刷新）· 保存落盘到插件配置 · 内核 Python 零 weather 痕迹 · `index.html` 只剩槽位 · 全程 0 console error / 0 失败请求。
- **§8 ② 收尾：插件写工具接入草稿确认流**（此前是**明确拒绝注册**，因为写路径会绕过确认）：
  - `core/plugins/loader.py`：写工具不再被拒，改为正常注册并记录「调用时由内核走草稿确认流」。
  - `app/agent_tools.execute()`：插件写工具在 `write_mode != 'direct'` 时**先生成草稿**（返回 `pending` + `draft_id` + 插件归属），**完全不调用插件 handler**；用户确认后 `confirm_draft` 以 direct 模式再进来执行；`reject_draft` 则不动。
  - **为什么闸门必须在内核侧**：插件拿不到 `save_draft`（那是 `app.agent_tools` 的内部能力，也不在 `core_api` 门面里），所以「写工具必须经用户确认」这条**不能指望插件自觉**——由内核统一拦截，插件 handler 只在 direct 模式下真正落盘。
  - **验收**（`.scratch/tmp/verify_plugin_tools.py`，19 项全通过）：读/写工具都进入工具面且写工具带 `write: true` · 读工具直接执行、handler 异常隔离、人设白名单生效 · **confirm 模式只出草稿、插件 handler 未被调用** · `confirm_draft` 真正执行 · `reject_draft` 不执行 · `direct` 模式直接执行 · HTTP 面 `/api/agent/tools` 含读写工具与 `write` 标记 · 未加载插件时工具不存在。
- **本轮收尾：21 套闸门全部通过**。可复跑的验收基线（都在仓库里，只读）：
  - `python tools/kb_smoke.py` —— 数据/关系层冒烟（199 条 / 1854 边）
  - `python tools/web_check.py` —— 前端静态：语法 / 装配清单 / 接缝 / 不变量（含「不得全局替换 `window.fetch`」「文档级 observer 必须走 `ERWDom`」「内核不得调用 `ERWPanels.register`」）
  - `python tools/ui_smoke.py` —— 真浏览器逐路由走查（17 路由 + 导航面板在侧栏 + 槽位面板已挂载 + 首屏不拉重型库 + 0 console error）
  - `python tools/web_manifest.py --check` —— 装配清单与 `index.html` 一致
  - `python tools/plugin_check.py --assert-core-only` —— 插件隔离（I2 依赖方向、core 不依赖 app、零插件合法）+ 面板契约 + `mcp_tools` 声明即注册
  - `python -m core.plugins list|check <id>|verify` —— 插件清单/依赖/冲突
  - `python -m core.doctor` —— 知识库与索引只读体检（当前 2 errors / 7 warnings，均为已知数据问题）
  - `python -m core.index.migrate` / `python -m core.index.maintain` —— 索引结构迁移（默认 dry-run）与维护（默认只读统计）
  - `python -m mcp.server --selftest` —— MCP 工具面自检（problems 为空）
  - `.scratch/tmp/` 下的 12 个夹具套件：插件执行层(19) / 插件工具与写工具草稿闸门(19) / manifest 契约(21) / 路径安全(10) / 三个插件 E2E(16+17+11) / DOM 接缝(8) / A10(6) / 面板注册表(9) / 迁移框架(24) / doctor 护栏与膨胀(各 1) / 规则负向(5+6)
- **未做（留给后续）**：MCP stdio 服务侧的插件工具、`settings_schema` 通用表单（插件目前自带设置 UI）、`ctx.jobs` / `ctx.events`、`A2 剩余`（把补丁并入主题模块、两处 canvas 先画后弃）、`doctor --fix-*`。`index-冲突-Moxise_Win11.sqlite`（6.8 MB 冲突副本）**未删**——删文件需你确认。
- **待决（发布边界）**：`AGENTS.md` 与 `.trae/rules/知识库条目命名规范.md` **均未被 git 跟踪**（白名单 `*` 未放行），而后者正是命名规范的权威文档、上文多处引用它——与 P25「整目录不受版本保护」同类。是否放行入库需要拍板（涉及把本机作业约定与规范文档推到 origin）。
- 注意：`ResearchWorkbench.exe` **未重新打包**；工作台与 MCP 是长驻进程，需**重启**后才加载新契约。

## v261008.2

### 知识库数据结构升级：实验独立成类 + 类型化关系层（底层变更，需重启生效）

- **实验升格为第七类 `experiment`**（`app/store.py`、`app/workspace.py`、`mcp/constraints.py`、`mcp/naming.py`、`mcp/tools_knowledge.py`、`web/app.js`）：目录 `Knowledge/Experiments`、前缀 `实验-`、状态机 计划/进行中/完成/受阻/已归档、日期字段 `record_date`、实验专用正文骨架（摘要/目标与假设/配置与参数/数据与口径/结果/结论与失效模式/留档路径/关联）。原先作为 `note` 类别词的「实验」**废弃**：`mcp/naming.py` 新增 **T020 error** 并在提示里给出迁移出路，T017 编号校验改按 `kind == "experiment"` 判定。前端新增「实验」导航/路由/状态机，图谱节点类别、`KIND_ROUTE`/`routeByKind`/`PAGE_META` 同步。
- **新增 `kb_change_kind` 工具与 `store.change_kind()`**（结构性迁移的唯一合法途径）：`id`/`created` 不变，目录随动、标题前缀改写、首个 H1 同步、状态映射、`kind_marks` 补齐，可选重写全库交叉引用；默认返回迁移计划，`dry_run=false` 才落盘。通用 `kb_update_entry` 仍然拒绝改 `kind`（`IMMUTABLE_FIELDS` 未变）。
- **关系层：关联段小标题 → 类型化边**（`app/store.py` 的 `RELATION_SECTIONS` / `RELATION_LABELS` / `iter_body_links()`，`app/perf_index_core.py`）。关系类型：`uses-knowledge`（依据的知识）、`uses-data`（用到的数据）、`cites`（引用文献）、`series`（同系列实验）、`chain-prev`/`chain-next`（上一/下一环节）、`produces`（产出与汇总），未命中一律退化为通用 `wikilink`。**不新增 frontmatter 字段**；历史条目沿用行内标签写法（`- 方法条目：[[…]]`）即被识别，存量内容无需改写。`graph_edges` 对类型化边**双写**通用 `wikilink` 边，保证只认旧类型的消费方（含前端默认筛选）不受影响。
- **索引结构变更**（`app/perf_index_db.py`）：`SCHEMA_VERSION` 2 → **3**；`document_links` 主键由 `(doc_id, token)` 扩为 `(doc_id, token, role)`，旧库检测缺列后整表重建（纯派生数据）并强制全量重索引；`_rebuild_graph_edges()` 按 role 建边。同步修掉一处**静默失败**：`sync()` 原先把 `OSError`/`UnicodeError` 直接 `continue`，条目会"凭空消失"而无任何提示，现在返回结果带 `skipped` 列表。
- **通用基础知识归属**（`app/perf_index_query.py`、`mcp/bridge.py`、`mcp/tools_knowledge.py`、`server.py`、`web/app.js`）：`kb_list_entries` 与 `GET /api/docs` 新增 `tag`（标签精确筛选，此前只能靠全文搜索命中）与 `unowned`（只看未归属项目）两个过滤维；列表页新增标签筛选项、「未归属项目（通用基础）」与「仅未归属」。约定：跨项目通用知识 `projects` 留空 + 标签 `通用基础`，不建伪项目（避免污染项目仪表盘/里程碑/待办）。
- **新增 `tools/kb_tree.py`**：只读派生索引生成四张视图 —— 知识树（按类别词分层、按"被几个实验交叉使用"分档）、交叉使用清单（同一知识被 ≥N 个实验共用）、实验依赖视图（依据知识/用到的数据/同系列/环节链/产出）、通用基础清单、实验链条与系列；支持 `--section` / `--min-shared` / `--out`，默认输出到 `Workspace/Knowledge/Exports/KnowledgeTree/`。
- **新增 `tools/kb_migrate_experiments.py` 并已执行迁移**：25 条 `知识-实验-…`（note）→ `实验-…`（kind=experiment），`id` 不变、状态按 稳定→完成 / 草稿→计划 / 整理中→进行中 映射、补 ⚗ 标记，全库**改写 139 处**按旧标题写的 WikiLink；并给 DUST 在轨链路（4.5–4.8b，5 条）与 GEO 多对一制导（4 条）两条实验线补 `### 同系列实验` 互指关系。复核：194 条（note 85 / experiment 25 / literature 67 / journal 6 / idea 4 / summary 4 / milestone 3），命名体检零 error。
- **关系实测**（迁移+重建后）：`uses-knowledge` 47、`produces` 6、`chain-prev` 4、`chain-next` 3、`series` 两条系列、`wikilink` 236（保底）、`tag` 1140、`project` 195；`知识-方法-WCS 星图定姿与坏帧判据` 被 7 个实验交叉使用，`知识-方法-受控归因诊断`/`帧间稳像与链式配准` 各 4 个 —— 即"哪些实验交叉使用同一知识"已可直接查出。
- **关系层内容补录（同批次，证据驱动，不发明引用）**：① 建 5 条数据集条目（`知识-数据集-DUST 在轨实测（SET 1 / SET 2）`/`NUAA-SIRST`/`IRSTD-1K`/`NUDT-SIRST`/`SIRST-v2（已退出评测口径）`），把实验反复点名却从未建档的数据集变成可引用对象（未确证的数字不写，标"待补"）；② 按"该实验正文自己点名了某数据集"补 `### 用到的数据` → `uses-data` 25 条边（DUST 10 / NUAA-SIRST 7 / IRSTD-1K 3 / NUDT-SIRST 3 / SIRST-v2 2）；③ 把正文里**以纯文本形式完整出现**的文献题名补成 `### 引用文献` 链接 → `cites` 50 条边、26 个条目获得引用小节；④ 17 条教科书级通用方法（亚像素质心五法、Top-Hat/LCM/SR/IPI、CKF/SCKF/EIF/IF、LQDG/Stackelberg/Minimax）清空项目归属并打 `通用基础` 标签。补录后：199 条（note 90 / experiment 25 / literature 67 / journal 6 / idea 4 / summary 4 / milestone 3），关系边 `uses-knowledge` 52 / `uses-data` 25 / `cites` 50 / `series` 32 / `produces` 7 / `chain-prev` 4 / `chain-next` 3 / `wikilink` 325（保底），未归属条目 23 条。补录脚本一处教训：同批次多次改同一个「关联」段时必须**改前重读磁盘正文**，否则后一步会用旧快照覆盖前一步（本批次踩到并已修正重放）。
- **修复 `_normalize_projects()` 的幽灵归属**（`app/store.py`）：该函数原先只同步 `projects`/`project`，清空归属时残留的 `project_id`/`project_ids` 会让索引（`document_projects` 同时看名字与 id）仍按项目计入——即"清不掉的归属"。现改为名字清空时同步清 id。
- **新增 `tools/kb_smoke.py` 冒烟测试**（只读、可重复）：覆盖关系解析（小标题/行内标签/小节继承/兜底类型）、命名规则（experiment 前缀与编号、旧类别词 T020、缺编号 T017）、归属归一化、关系边与 `document_links.role`、无幽灵归属、七类条目齐备、通用基础标签与未归属可查、`kb_tree` 五张视图可生成、约束主题渲染、实验迁移幂等。当前 **全部通过**。
- **文档**：新增 `docs/KNOWLEDGE_RELATIONS.md`（对象层 / 关系层 / 索引与接口变更 / 迁移记录 / 内容补录 / 通用知识口径 / 论文引用层预留 / 已知陷阱）；`README.md` 增加「知识库结构（七类条目 + 关系层）」小节并更新开发目录；`kb_constraints` 新增 `topic=relations`，`kinds` 主题变七类矩阵，`schema`/`marks`/`playbook` 文案同步（`实验-` 建档、通用基础归属、`kb_change_kind` 红线）。
- 注意：本次只改源码，`ResearchWorkbench.exe` **未重新打包**；`VERSION` 升至 `v261008.2`。工作台 exe 与 MCP 服务是长驻进程，需**重启**后才加载新结构与新工具；重启前旧进程若刷新索引会按旧口径重建（派生数据，重启后自动恢复）。

## v261008.1

### Agent 接入 OpenCode Go（代理 / 直连）与火山方舟 Agent Plan

- 新增三套 Agent API 配置（`config/secret.json` 的 `profiles`）：`profile-opencode-go`（本机 `127.0.0.1:9355` 上的 opencode-go 反代理，`base_url=http://127.0.0.1:9355/zen/go/v1`）、`profile-opencode-go-direct`（**不经任何本地进程**，`base_url=https://opencode.ai/zen/go/v1`）与 `profile-ark-agent-plan`（`base_url=https://ark.cn-beijing.volces.com/api/plan/v3`，方舟 **Agent Plan 专属网关**）。接入本身不改变激活项；切换用 Agent 页顶部「API 配置」下拉或设置页「设为当前配置」。
- **新增档案级自定义请求头**（`profiles[].headers`）：opencode.ai 直连强制要求 `x-opencode-session`（缺它 400 `Request is missing x-opencode-session and cannot be routed efficiently`），工作台原先只发 4 个固定头，故 `app/config.py` 加 `_clean_headers()` 白名单化（头名须 RFC 7230 token、值禁 CR/LF、单值 ≤512 字符、最多 20 条），`app/agent.py` `_api_headers(api_key, extra)` 把它合并进**全部**请求路径（普通补全、SSE 流式、`/models` 探针、对话探针）；`Content-Type` / `Authorization` 由工作台接管不可覆盖，`User-Agent` 允许改写。实测只有 session 是硬要求，`x-opencode-request/client/project` 可省（保留以与官方 CLI 同形）。设置页「Agent API 配置」同步加「自定义请求头（JSON）」输入框（`web/v260922-agent-profiles.js`）。
- 请求模式：每套先给 6 个，默认 `deepseek-v4.1-flash`，另含「· 无思考」（`{"thinking":{"type":"disabled"}}`）、`deepseek-v4-pro`、`glm-5.3`、`doubao-seed-2.1-pro`、`kimi-k3`、`qwen3.8-flash`、`deepseek-v4-flash-vision-exp` 等，均按服务商实际可得模型逐个实测返回 200；超时给到 300s（推理模型长回答 + 阅读区 AI 助手非流式路径）。
- `app/agent.py` `test_connection()` 修复「能用但测不通」：方舟 Agent Plan 不提供 `GET /models`（404），新增回退分支——仅当 /models 报 404/405/501 时，用默认请求模式的模型发一次 16-token 对话探针，返回 `choices` 即判定连通（响应 `probe=chat_completions`、`message` 说明已改用探针）；401/429/5xx 仍原样抛错保留诊断信息。
- 接入验证走工作台自身代码路径（非另写探针）：`test_connection()` + `assist()` 真实补全 + `_post_chat(on_delta=…)` SSE 流式 + `_run_with_tools()` 原生 function calling 工具循环，四套配置全绿（含直连一套：`/models` 直连返回列表、流式 9 个 delta、工具循环命中知识库）；三家的 `reasoning_content` 均能回传并进入「模型思考过程」。
- 踩坑记录三则：①方舟 Agent Plan 网关是 `/api/plan/v3`，误用通用网关 `/api/v3` 或 Coding Plan 网关 `/api/coding/v3` 一律 401；②opencode.ai 侧按 UA 拦访问，`Python-urllib/*` 默认 UA 触发 Cloudflare 1010，工作台自带的 `Workbench/260922.3` 直连与经代理均放行——日后改 `_api_headers` 的 UA 需重新实测；③**旧版 exe 不认识 `headers`**，在旧版设置页点「保存全部配置」会把直连档案的请求头静默抹掉，直连配置需搭配 v261008.1 及以后的 exe（或开发模式）。
- 架构与实测结论记入 `docs/ARCHITECTURE.md`「Agent Provider 接入（v261008）」；`VERSION` 升至 `v261008.1`，`ResearchWorkbench.exe` 已重新打包（2026-10-08 12:11），并用归档解析核对产物内含 `pf-headers` / `_MODELS_UNSUPPORTED_RE` / `extra_headers` / `_clean_headers` 与内嵌 `VERSION=v261008.1`。
- 工具轨迹改为**时间条视图**（v261008b）：`app/agent.py` 的 `_run_with_tools` 为每轮 LLM 调用与每次工具调用记录 `t0/t1`（相对本轮起点毫秒），返回第 5 项 `timing`（总耗时 / 思考累计 / 工具累计 / 轮数 / `timeline` 段列表）并挂到 assistant 消息（SSE `done` 随 `assistant` 回传），`tool_trace` 条目同步补 `t0/t1`。前端把原来的逐条 chip 流水账换成「一行汇总（⏱ 总耗时 · 轮数 · 思考合计 · 工具合计与次数）+ 一条与耗时成比例的堆叠时间条 + 图例（色块 ↔ 工具名，带 ×次数与累计耗时，失败另标 ✗N）+ 可折叠过程明细（逐段名称与耗时，工具名前带同色圆点，草稿的已确认/已拒绝仍保留）」；**思考段用浅灰，每个工具按本消息内首次出现顺序取 8 色调色板中的一色（保证同一条消息里各工具颜色互不相同），失败段固定红色（语义优先于配色）**，悬停任一段显示「名称 · 耗时」。生成中另有一条实时时间条随 `round`/`tool` 事件推进，取色顺序与最终结果一致。渲染器经 `window.ERWFabTimeline` 暴露，Agent 页（`web/app.js`）复用同一套类名与样式（`web/v260930-floating-agent.css`）。旧会话没有 `timing` 时按 `tool_trace` 的 `ms` 顺序兜底成条，并标「旧记录」，不谎报 0 轮 / 0ms 思考。
- 草稿确认卡片紧凑化（v261008b）：待确认从「一张四行卡片」改为**紧凑行**（工具徽标 + 标题同行、确认/拒绝按钮右对齐；≥2 篇仍给「✓ 全部确认 / ✗ 全部拒绝」整批操作条），已处理（已确认/已拒绝）折成**一行汇总**「✓ 已确认 N ✗ 已拒绝 M · 共 X 篇 · 点击展开明细」，明细收进 `<details>` 默认收起（每篇一行：状态徽标 + 工具 + 标题 + 落盘 `doc_id`）。11 篇批量建档的场景由约 11 张卡片（≈900px）压到一行（≈40px）。`data-draft-confirm` / `-reject` / `-confirm-all` / `-reject-all` 四个钩子原样保留，单条与整批确认/拒绝的既有接线（含 `querySelectorAll("[data-draft-confirm]")` 收集 id）不变；旧 `.fab-draft*` 样式保留备回退。渲染器经 `window.ERWFabTimeline.drafts(msg, states)` 暴露，便于离线预览与复用。
- 悬浮球面板**自适应窗口**（v261008b）：内容不再撑破面板。①`.fab-messages` 补 `overflow-x:hidden`，flex 子项统一 `min-width:0`（默认 `min-width:auto` 不肯收缩，是溢出的根因）；②长串断行（`overflow-wrap:anywhere`），宽表格在 `mdRender` 渲染后套 `.fab-tbl` 滚动容器——表格保持自身布局、超宽时在气泡内横滚，Agent 页 `renderMarkdownInto` 同步处理（先试过 `table{display:block}`，实测会把表格压成逐字换行「lite rat ure」，已弃用）；③已处理草稿行改为「徽标 + 标题一行、`doc_id` 另起一行」（实测 298px 可用宽度下徽标 138px + id 171px 已超，标题曾被挤成 0 宽）；④面板尺寸/位置此前只在「恢复」与「拖拽」时钳制，窗口变小后不重算，新增 `reflowPanel()` 在 `resize` 时按当前视口重新钳制面板与悬浮球，尺寸上下限改为随视口推导（`fabMaxW/H`、`fabMinW/H`），避免窄窗口下「下限大于上限」把面板顶出视口。无头浏览器实测：360px 窄面板内塞入 5 列宽表 + 长英文题名 + 长 `doc_id`，8 项断言全 PASS（消息区 358/358 无横向溢出，表格在 276px 容器内滚动 947px）；预置 900×900 尺寸与 (800,700) 位置后缩小窗口，面板被钳制为 456×357@(32,102)，7 项断言全 PASS。
- 修复 Agent 页（`web/app.js`）与 SSE 后端的协议错位：`/api/agent/send` 自 v260930k 改为 SSE，v260930m 又把 `done` 负载瘦身成只回 `assistant`，而 Agent 页仍按旧 JSON 契约读 `r.session.id`（`api()` 对流式响应 `res.json()` 抛错后返回 `{}`），表现为发消息即报 `Cannot read properties of undefined (reading 'id')`。新增 `streamAgentSend()` 消费 `round|delta|tool|done|error` 事件（delta 增量就地渲染进思考气泡、round 显示工具循环轮次），`done` 后回读 `GET /api/agent/sessions/<id>` 补齐会话对象，故其后的既有渲染逻辑一行未改；悬浮球（`web/v260930-floating-agent.js`）本就是 SSE 版，不受影响。已用 Node 同构脚本对着运行中的服务实测 round→delta→done→会话回读全通。
- 消息元信息去重（v261008b）：悬浮球与 Agent 页的元信息行原本并排显示 `model` 与「请求模式标签」，而标签通常自带模型名（`deepseek-v4.1-flash` + `DeepSeek V4.1 Flash（默认）`），同一件事报两遍。新增 `metaParts()`——归一化（去空格/点/连字符/括号）后标签已含模型名则只留标签，标签确实不同才两者都留，人设名始终保留；悬浮球经 `window.ERWFabTimeline.metaParts` 暴露给 Agent 页复用。自检五例：`术语建档员 · DeepSeek V4.1 Flash（默认）`、`DeepSeek V4.1 Flash · 无思考`、`qwen3.8-flash · 默认（不附加参数）`、`glm-5.3`、空（旧消息只剩时间）。
- 用量计费口径升级（v261008b，`app/billing.py` + `web/v261008-billing.js` + `web/v261008-billing.css`；该模块本身为 v261008 新增，此处一并补记）：①**按档案区分计费方式**——`prices.json` 新增 `plans` 段（`mode=token|subscription|free`），订阅套餐（OpenCode Go · 直连/代理、火山方舟 Agent Plan）只统计用量、金额项不适用，不再被算成「缺单价」；②**单价键支持档案限定**，优先级 `档案id/模型名` → `档案id`（该档案兜底价）→ `模型名`（含 `*` 通配），解决同一模型在不同 Provider 价格不同的问题；③**缓存命中率**进入总览卡片与按会话/按模型表（命中部分按 `cache_hit`、未命中输入按 `input` 计），长上下文 Agent 的最大成本变量终于可见；④**缺单价闭环**：总览新增「缺单价」清单（按 档案+模型 聚合并给出建议键）与「加入单价表」按钮，一键生成待填条目并跳到编辑框；⑤**usage 缺失也落账**（`usage_missing`），调用次数与实际一致；⑥老账本（无 `billing_mode` 字段）在**读取时按当前 plans 推导**归位，账本文件仍只增不改。实测：47 条历史调用由「未计价 47 / 请补全单价表」变为「订阅内 47 · 缺单价 0」，命中率 72.5%（输入 1,078,568 中命中 781,952，计费输入 296,616）；真跑一次对话后新记录带 `billing_mode=subscription`、`priced=true`、`plan_label`。另修 `billing.py` 顶层 `from .workspace import ...` 在「billing 作为首个 app 模块」时的循环导入（改为延迟导入、先初始化 config）。
- 订阅制**按官方定价换算等价标价**（v261008b，续上条）：①单价条目新增可选 `currency`（直接粘贴官方人民币标价即写 `"currency":"CNY"`），价格表顶层新增 `fx` 参考汇率（语义 1 USD = N 该币种，预置 `{"CNY":7.1}`，可在单价表里改），新增 `convert_cost()` 统一折算，缺汇率的条目标 `fx_missing`（等价记 0，不猜数）；②订阅/免费档案除 `cost_usd`（实付口径，订阅记 0）外另记 `equiv_usd`（等价标价），token 模式两者相同；③`summary()` 给出 `equiv_usd` / `subscription_equiv_usd`，页面新增「等价标价合计」卡片、订阅档案表与按模型表的「等价标价」列（明示为参考、非实付）；④老账本读取时用**当前单价表**补算等价标价（仍是视图层：不改账本文件，也不改 token 模式写入时冻结的实付金额）；⑤价格表预置 DeepSeek 官方标价（`deepseek-v4.1-flash` 与官方名 `deepseek-flash`：空闲时段 输入 1 元、缓存命中 0.02 元、输出 4 元 / 百万 tokens，高峰时段为该值 2 倍），来源 [api-docs.deepseek.com「模型 & 价格」](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)（2026-10-08 核对，与七牛云同模型页标价一致）。实测你那 48 次调用按此折算 ≈ **$0.0831**（≈0.59 元），其中 OpenCode Go·直连 Zen 47 次 ≈$0.0829、方舟 Agent Plan 1 次 ≈$0.00015——订阅制"省下多少"终于可见。计费纯函数自检 17/17 通过（含档案限定键优先、通配、计费口径、人民币折算、缺汇率处理、老账本归位与实付冻结、`fx`/`currency` 归一化）。
- Agent 对话页排版优化（v261008c，`web/styles.css` + `web/v260922-agent-profiles.js`）：①原 `.agent-message` 锁死 `max-width:920px` 且助手气泡左对齐，1828px 宽屏下右侧空出 600+px——改为整条会话（消息列 + 引用条 + 输入框）共用一条**居中阅读列**（`--agent-col:1180px`，以 `padding-inline:max(6px,calc((100% - var(--agent-col))/2))` 实现），助手气泡放宽到 1080px、用户气泡 900px，≤1100px 自动回退通栏；②`.agent-message-body` 的 `overflow-wrap:anywhere` 会把表格单元格里的英文逐字断开（实测 `literature` → `literat/ure`、表头「中 1」竖排），改为 `break-word`，并补齐消息内表格样式（`width:max-content` 保持自身列宽 + 表头 `nowrap` + 渲染时已套的 `.fab-tbl` 容器内横滚，与悬浮球同一套做法），正文 12→13px；③输入区「API 配置」旁的徽标原本把下拉框已选中的配置名重复显示一遍，改为显示**接口地址主机**（`opencode.ai` / `127.0.0.1:9355` / `ark.cn-beijing.volces.com`，悬停看完整 base_url）——直连还是走本地反代理一眼可辨；④输入区与引用条套用同一条阅读列，与消息对齐。无头浏览器按用户截图同尺寸（1828×1109）与窄屏（980×860）各验一次：宽屏会话列居中、表格列宽正常且超宽在气泡内横滚，窄屏回退通栏、输入区自动换行。**v261008d · 对齐与秩序**：原 `.agent-message.user{align-self:flex-end}` 会把「YOU 头像 + 气泡」整体推到右边，YOU 与 AI 的开头相差数百像素（用户反馈「两个对话开头不对齐」）；改为**统一栅格 + 全部左对齐**——两角色的 `article` 同宽同起点、头像固定占第一列（`--agent-gutter:36px`），**AI 与 YOU 的气泡一律从「头像右侧」同一条线起笔**（YOU 气泡 `width:fit-content` 贴合文字，短消息不被拉成一条空框；角色靠头像与底色区分），并让聊天头 / 消息列 / 引用条 / 输入框共用同一条列宽 `--agent-col-inner:1080px`——整页只剩一条对齐轴。已用真实短会话（两轮问答，截图后删除）在 1828×1000 核对：四个头像落在同一竖线、四个气泡左缘同为 x≈697；用户真实长会话（含 5 列表格与耗时时间条）复核无回归。

## v260929.1

### 文献 PDF 工作区合并（四阶段方案落地）

- 并入上游 `feature/literature-pdf-workspace` 40 个提交：PDF 上传与流式阅读、三栏文献工作区、矩形/手绘/文字批注、区域截图预览、批注笔记，合并后按方案分四阶段与既有文献条目体系融合。
- **阶段 1 · 共存接入**：移除对 `kind='literature'` 页面的整体接管，文献列表/编辑器（BibTeX 双向同步、自动 cite_key、元数据表单）原样保留；工作区改由列表页头部「PDF 阅读工作区」按钮进入，工作区内提供「← 返回文献列表」按钮。
- **阶段 2 · 数据互认**：上传 PDF 即同步创建 literature md 条目（`attachment` 指向 `Knowledge/Literature/PDF/`，cite_key 自动生成），`doc_id` 双向关联写入 `library.json`；删除文献时联动清理 md 条目（均入 Trash）；列表「⧉ 附件」徽章优先跳转工作区阅读，未登记附件退回新窗口直开。
- **阶段 3 · 真值归一**：元数据以 md 条目为唯一真值——工作区列表/详情 join 回读 md（编辑器改题名/作者/DOI 即时生效于检索与展示），工作区侧改元数据经 `indexer.update_doc` 回写 md 并刷新索引；新增「重建关联」按钮与 `POST /api/literature/rebuild`（幂等：补 doc_id 关联、旧附件 PDF 复制入库登记、孤儿条目补建 md）；修复上游遗留的 `/api/literature/export-bibtex` 路由错位（误置于 GET 分发致 POST 落入泛匹配 404）。
- **阶段 4 · 自动填写**：文献编辑器新增「自动填写」行——粘贴 DOI（CrossRef）或 arXiv 编号（arXiv API）联网抓取回填，粘贴 BibTeX 文本则前端本地解析回填；cite_key 按第一作者姓氏 + 年份生成；回填仅覆盖空字段并提示核对。
- **附件入口统一与存放空间合并**：列表「⧉ 附件」徽章点击一律跳转 PDF 阅读区（原浏览器新窗口直开并入工作区）；未登记的附件自动单条登记（`rebuild` 支持 `doc_id`）后重试打开；附件 PDF 统一存放于 `Knowledge/Literature/PDF/`——Workspace 内的旧附件（如 `Knowledge/Attachments/`）原地移动迁入不留双份，Workspace 外绝对路径仅复制不破坏外部文件。
- 打包提醒：`web/` 与 `VERSION` 均为构建期注入，改动后须重跑 `build_client.bat` 才对 exe 生效；开发模式重启服务即生效。

## v260924.1

### 分类标记

- 内置分类标记新增 `model`（⬡ 模型）与 `principle`（∑ 原理），候选由 8 个扩展到 10 个。
- `模型` 用于可建模对象：物理动力学模型、参数化抽象、可训练网络；`原理` 用于记录某个方法的具体原理与公式：机理推导、口径与度量定义、判据式。
- 标记与条目命名规范的类别词对齐：`架构`→`architecture`、`方法`→`method`、`模型`→`model`、`原理`→`principle`、`实验`→`experiment`、`数据集`→`data`。`.trae/rules/知识库条目命名规范.md` 中原「类别词不新增 `kind_marks` 取值、`模型` 类条目沿用 `method` 标记」条款同步修订为「类别词与 `kind_marks` 一一对应」。
- 标记仍为前端固定常量，保存写入 frontmatter `kind_marks`；后端存储、索引与 `/api/docs?mark=` 过滤均按字符串处理，无 schema 变更、无需数据库迁移。
- 按新映射对存量 `知识-` 笔记批量重标记（2026-09-24 10:16，经 `store.update_doc` 写入并自动记录 `doc_update`）：65 篇中 25 篇标记与新规范不一致，已全部对齐 —— `模型` 16 篇由 `method` 改为 `model`，`原理` 4 篇由 `data` / `architecture` / `thinking` 等代用标记改为 `principle`，`方法` 4 篇去除 `synthesis` / `thinking` / `experiment` 代用标记，`架构` 1 篇去除其中 `method`；其余 40 篇（`方法` 20、`实验` 16、`架构` 3、`数据集` 1）原本合规未动。重标记后 `知识-` 笔记标记分布（篇）：`knowledge` + `method` 24、`knowledge` + `model` 16、`knowledge` + `experiment`（含叠加 `method` / `data`）16、`knowledge` + `architecture` 4、`knowledge` + `principle` 4、`knowledge` + `data` 1。

### 条目拆分

- 按《知识库条目命名规范》§四.4「禁止「A 与 B」式跨族合写标题（一篇只讲一个知识点或一个族）」拆分 2 篇「一篇多实验」条目为 9 篇单实验条目（2026-09-24 10:55，经 `store.create_doc` / `delete_doc` 写入并自动记录 `doc_create` / `doc_update` / `doc_delete`）：`知识-实验-传统单帧检测方法对比与失效机理（1.1/1.2）`（含 1.1/1.1b/1.2/1.2b/1.2c/1.2d/1.2e 七项实验）拆为 7 篇，`知识-实验-数据集难度分级与深度学习批量基线（2.0/2.1）` 拆为 2 篇。
- 新条目：`知识-实验-小区域滤波单帧检测基线（1.1）`、`知识-实验-小区域滤波虚警改进（1.1b）`、`知识-实验-传统单帧经典方法对比（1.2）`、`知识-实验-LCM 失效根因诊断（1.2b）`、`知识-实验-四方法增强域受控归因（1.2c）`、`知识-实验-IPI 强云层帧虚警根因（1.2d）`、`知识-实验-四方法环境适用性分层（1.2e）`、`知识-实验-数据集结构实测与难度分级（2.0）`、`知识-实验-深度学习批量基线（2.1）`；`kind_marks` 沿用原主题标记（阶段 1 七篇叠 `method`，阶段 2 两篇叠 `data`），`project_id` 经 `apply_doc_project_ids` 补写。
- 原 2 篇经 `delete_doc` 移入 `Workspace/System/Trash/note/`（可回滚）；全库互引同步：`知识-实验-GEO单帧经典检测（1.3g）` 中指向原条目的管线来源行改指新的 1.1b / 1.2 两篇，扫描确认无其余残留引用。
- 全库同类问题排查：其余 63 篇标题均为「单类别词 + 单一对象」，`知识-方法-传统红外小目标检测` 为声明的「同目标多方法归类」篇、三篇制导实验条目以括号补充侧面而非跨族合写，均不属此问题。

### 打包

- `ResearchWorkbench.exe` 由 PyInstaller onefile 打包，`web/` 与 `VERSION` 在构建时写入包内（`--add-data "web;web" --add-data "VERSION;."`）；冻结运行时 `ASSET_ROOT = sys._MEIPASS`，**修改 `web/` 或 `VERSION` 后必须重新执行 `build_client.bat`**，改动才对 exe 生效，直接跑开发模式（`python server.py` / `run.bat`）读的是仓库目录。
- 本版本已重新打包（2026-09-24 10:11），确认 exe 内 `/app.js` 含 `model` / `principle`，`/api/health` 返回 `v260924.1`。

## v260922.3

### 性能优化

- 新增 SQLite 可重建索引，Markdown 仍作为唯一真实数据源。
- 文档、项目、标签、待办、活动和知识关系改为索引查询，减少大规模 Workspace 下的重复扫描。
- 文档列表支持服务端分页，全文搜索接入 FTS5。
- Workspace 文件树改为按需加载。
- Dashboard、项目统计和科研活动改为聚合查询。
- 新增索引状态、手动重建接口及性能测试脚本。

### 知识图谱优化

- 知识图谱改用 Force-Directed Layout，并加入社区辅助布局。
- 新增 Semantic Zoom、标签 LOD、标签碰撞检测和 Edge LOD。
- 新增节点搜索、实时联想、最近编辑、自动定位和 Camera 聚焦。
- 新增一阶 / 二阶 `Focus + Context` 关系浏览。
- 建立邻接表、布局缓存、投影缓存、Viewport Culling 和 `requestAnimationFrame` 合帧。
- 2D / 3D 共用统一的搜索、选择和 Focus 逻辑。
- 修复搜索框、Canvas、预览区等 UI 层级覆盖问题。
- 「研究 · 知识总览」中的知识关系预览同步升级为新版绘图方式。

### 界面

- 新增类似 ChatGPT Web 的左侧栏收起 / 展开功能。
- 侧栏状态自动保存，收起后主区域自适应扩展。

### Agent / LLM

- Agent 配置升级为多套 API Profile，可独立保存并快速切换。
- API Key 改为直接保存在本地 `config/secret.json`，不再依赖环境变量。
- 每套 Profile 独立支持：
  - Base URL；
  - API Key；
  - 超时时间；
    -最大输出 Token；
  - Temperature；
  - 是否显示思考；
  - 多套 Request Mode。
- Request Mode 支持独立配置模型、Temperature 和扩展 `params`。
- Agent 设置页改为结构化配置管理界面，不再手动编辑整段 Preset JSON。
- Agent 对话页支持选择当前 API Profile 和 Request Mode。
- 模型调用统一使用 OpenAI-compatible Chat Completions。

### 配置迁移

- 首次升级时自动读取旧版 Agent 配置并生成「未命名配置」。
- 兼容旧 `app.json`、`secrets.json` 和 `api_key_env`。
- 原有 Base URL、模型、请求模式、超时和思考设置等会尽量自动迁移。
- 新版密钥配置保存在 Git 忽略的 `config/secret.json` 中。

## v260922.2

* 优化「核心工作 → 概览」页面布局，整体调整为更紧凑的科研仪表盘结构，提高桌面端信息密度并减少纵向空白。
* 重构概览页模块排列：科研热力图与学业进度 / 毕业条件组成顶部区域，「今日科研桌面」与「快速记录」作为左侧组合，并与右侧科研节奏、当前任务和近期节点统一对齐。
* 调整「今日科研桌面」与「快速记录」的高度分配，减少今日概览卡片无效留白，同时为快速记录提供更充足的操作空间。
* 「当前任务」与「近期节点」统一限制为最多显示 3 条记录；无记录或记录较少时仍保持合理的卡片最小高度，避免概览布局塌缩。
* 调整「项目推进」与「最近研究活动」布局，使两组内容顶部对齐；最近灵感、最近笔记和最近工作总结分别支持最多展示 10 条近期记录。
* 优化项目推进、统计卡片、列表项、导航栏、顶部栏及卡片间距，使整体界面在保持可读性的同时更加紧凑。
* Markdown 编辑界面新增独立缩放控制，支持分别调整编辑区和预览区显示比例，范围为 10%–200%，100% 对应原始显示大小。
* 编辑区与预览区缩放比例分别保存到本地浏览器，页面刷新或重新进入编辑界面后自动恢复上次设置。

## v260922.1

* 新增「核心工作 → 项目」管理模块，支持项目新建、编辑、重命名、状态修改和删除，并展示描述、最近编辑及关联内容统计。
* 项目改用稳定 `project_id` 作为唯一索引；旧 Workspace 启动时自动为历史项目补充 ID，并迁移笔记、灵感、里程碑和待办等项目关联。
* 项目重命名后保持原 ID 和知识关联不变；删除项目时解除关联，并将项目工程目录移入 Workspace 回收目录。
* 修复知识图谱 Markdown 预览中的本地图片路径解析，支持正常显示 Workspace 附件图片。
* 修复「研究 · 知识总览」近期里程碑，仅显示计划中节点的问题；现在默认展示当前日前后约半年的全部状态里程碑。
* 里程碑普通时间轴与 3D 时间轴新增状态筛选，支持计划、进行中、受阻、完成等状态，并在视图切换时保留筛选条件。

## v260921.1

- 修复知识图谱右侧长文本不换行。
- 新增知识图谱节点 Markdown 预览抽屉；支持真实文档和项目/标签虚拟节点。
- 里程碑 3D 时间线新增 Markdown 预览抽屉与“打开编辑”。
- 知识图谱新增空白画布拖动、Ctrl/Cmd+滚轮缩放、3D Alt/右键旋转与一键全览。
- 设置中心新增“服务与存储”页，暴露 Host、Port、自动打开浏览器、Workspace、迁移策略；天气启用开关和 LLM provider_label 也可视化。

## workbench-v260921 · 2026-09-21

### 本轮新增

- 文档新增「分类标记」：每条 Markdown 可挂载多个标记（知识 ◈ / 归类 ◎ / 方法 ⚒ / 问题 ？），编辑器元信息区以 chip 多选，保存写入 frontmatter `kind_marks` 字段。
- 列表条目显示彩色标记胶囊；文档筛选栏新增标记下拉，后端 `/api/docs` 支持 `mark` 参数按标记过滤。
- 标记候选为前端固定常量（图标与颜色内置），与配置解耦，不再依赖 `custom_kinds`。
- 新增本地私密配置 `config/secrets.json`：在 `env` 对象中填入 `"环境变量名": "密钥值"`，服务运行中保存后自动注入进程环境变量（修改时间检测热重载，无需重启），`run.bat` 启动无需每次手动设置 API Key。该文件已被 `.gitignore` 排除，不会上传 git；Key 依旧不进入 `config/app.json` 与接口返回。

### 本轮修复与调整

- 修复笔记分屏/预览模式下 Markdown 界面无法使用滚轮阅读的问题。
- 笔记编辑器顶部表单区紧凑化；项目选择弹窗修复项目名竖排折行，选择框高度与其它控件统一，备注输入移至选择框下方。

### 本轮移除

- 移除自定义笔记类型机制（`custom_kinds`）：侧栏入口、`kind-` 路由、设置页「笔记类型」管理、后端 `custom_kinds()` 配置读取与 `Knowledge/Custom` 目录；原四类图标与颜色由分类标记固定候选继承。

## workbench-v260920.2 · 2026-09-20

### 本轮新增

- 概览「项目推进」新增“＋ 新建项目”，无需先进入资源页面。
- 研究条目的项目字段改为已有项目选择器：默认空白、支持多项目、支持移除，不再手动输入项目名称；待办项目也限制为已有项目。
- Agent API Key 机制改为环境变量：新增 `api_key_env`，默认 `OPENAI_API_KEY`；服务运行时从 `os.environ` 读取，不再创建或更新 `config/secrets.json`。
- Agent 默认请求模式增加三套：默认、Qwen 低思考（`enable_thinking=true` + `thinking_budget=1024`）、Qwen 无思考（`enable_thinking=false`）。
- Agent 输入改为乐观渲染：发送后用户消息立即出现在对话区，模型调用期间显示思考状态与耗时。
- Agent 支持从兼容接口提取 `reasoning_content` / `reasoning` / `thinking` / `analysis`，并通过设置项控制是否展示。
- Agent 用户消息在外部模型调用前写入会话历史；即使模型请求失败，也尽可能保留本轮用户输入。
- 知识图谱点击空白处可清除当前选中节点与邻接高亮。
- 更新自检：覆盖环境变量密钥、无本地 secrets 文件、模型 reasoning 提取、项目选择器与图谱取消高亮。

### 上一轮整合内容

本版本延续 workbench 独立工程，并整合此前图谱、资讯、Agent 与 Markdown 能力：

- 修复资讯模块：arXiv RSS 增加官方 Atom API 回退与短重试；全部抓取失败时不再覆盖有效缓存，也不缓存空失败结果；资讯页显示每个源的实际状态与详细诊断。
- Markdown 标签 placeholder 改为 `标签1, 标签2, 标签3`。
- Agent 增加 JSON 请求模式配置，可把供应商自定义请求参数动态合并到 Chat Completions / Responses API 请求；对话页可逐轮选择请求模式。
- Markdown 编辑时 `Ctrl/Cmd + S` 改为保存当前文档并阻止浏览器“保存网页”。
- 修复知识图谱从 3D 切换 2D 后旧动画循环继续绘制的问题。
- 选中图谱节点时，高亮当前节点、一阶相邻节点和相关边，并弱化其它图元。
- 图谱新增标签节点和标签关系；项目关系升级为多项目；Markdown 支持 `projects: []`，同时保留 `project` 兼容字段。
- 图谱筛选增加“关系来源”：显式引用 / 标签关联 / 项目归属。
- 关联 Markdown 导出改为继承当前图谱可见节点与关系，不再使用未过滤图谱；支持直接以标签或项目虚拟节点作为导出核心。
- 自检覆盖多项目、标签图谱、筛选导出、动态 Agent 请求参数和 RSS arXiv 回退。
