# Agent 系统：技能、持久化任务与科研记忆

本分支在原有科研聊天工具循环上增加本地 Agent 运行层。直接打开原来的 **Agent** 页面，即可使用 **对话 / 任务 / 记忆 / 技能 / RAG / 设置**。主页面与悬浮助手使用同一个会话状态容器，选择会话、逐字回答、完成结果及草稿处理即时同步。聊天区只保留提问、助手与附件，模型选项默认折叠。任务自动来自普通对话，不另设任务输入框或“Agent 系统”弹窗入口。

## 数据设计与 CortexDB 的对应关系

参考仓库：[liliang-cn/cortexdb](https://github.com/liliang-cn/cortexdb)，研究基线提交 `5965a15cf2c0a3c5c6a26e010209e8322976c45f`。重点参考 `pkg/cortexdb/knowledge_memory_types.go` 中的作用域、来源、有效期、替代关系，以及 Recall 的 ContextPack 数据契约。

本实现使用 Python 标准库 SQLite，未复制 CortexDB 源码，也不要求安装 Go 或运行 CortexDB 服务。它借鉴数据组织和检索设计，不声称与 CortexDB 文件格式或 API 兼容。CortexDB 的 RDF/SPARQL、OWL、HNSW 索引和分布式共享脑不在本实现范围内。

| CortexDB 思路 | 工作台实现 |
| --- | --- |
| 单 SQLite 记忆与关系存储 | `Workspace/System/Agent/brain.sqlite`，WAL、外键、事务与在线备份 |
| Scoped memory | `global/user/project/session`，namespace 与 scope_id 联合隔离 |
| 记忆类型 | fact/preference/procedure/decision/episode |
| 来源与生命周期 | source、importance、TTL、active/superseded/forgotten |
| 稳定标识更新 | 同作用域相同 memory_key 的新内容替代旧记忆，保留历史 |
| 无 Embedding 可工作 | FTS5，中文双字索引，实体关联扩展 |
| 混合检索 | 可提交已有的 memory embedding/query_embedding，余弦相似度与词法结果做 RRF 融合 |
| ContextPack | 带 `[MEM id]`、来源、条数与字符预算的召回结果包 |

向量模式是有界精确扫描，目前最多读取 10,000 条有向量记忆；未配置外部 Embedding 自动生成服务。没有向量时明确使用 `lexical_graph`，不会把词法检索伪称为语义检索。

数据库保存会话、消息、任务、检查点、事件、工具调用、记忆、关系和草稿投影。研究 Markdown、PDF 仍保存在原有目录中。草稿 JSON 是现有界面的审批接口载体。

旧 `System/AgentChats/chat-*.json` 首次访问时幂等导入。消息按稳定 id 合并，删除标记防止旧文件重新导入。会话写入后仍生成 JSON 投影，继续兼容已有会话同步和备份机制。原始工具参数与返回值会随会话证据投影保存。

**不要通过文件同步直接复制运行中的 SQLite/WAL。** 现有同步继续同步会话 JSON；长期记忆、任务和运行状态目前保留在本机数据库。跨机器转移完整脑数据使用系统界面的“备份记忆库”，该操作调用 SQLite 在线备份；恢复时先停止服务，再用备份替换 `brain.sqlite`，清除旧的同名 WAL/SHM 后启动。不能同时运行两个服务实例写同一个 Agent 工作区。

## Skill

内置技能：`literature-review`、`knowledge-curation`、`research-analysis`、`evidence-audit`、`skill-authoring`。完整升级设计、执行契约与边界见 [Agent 升级设计](AGENT_UPGRADE_DESIGN.md)。

用户技能目录：

```text
Workspace/System/Agent/Skills/my-skill/
├── SKILL.md
├── references/         # 可选，文本参考
├── assets/             # 可选，模板与输入
└── scripts/            # 可选，Python 脚本
```

```markdown
---
name: my-skill
description: 描述技能用途和适用任务。
allowed-tools: kb_search kb_read
---

具体工作流程、验收标准和来源要求。
```

在“技能”页用总开关启停 Skill，并按项勾选允许使用的技能，不再在聊天区选择技能。启用的目录只加载名称、描述与兼容性；模型用 `skill_read` 按需读取指令和资源。输入 `$my-skill` 仍可显式激活已启用技能。停用技能不进入模型目录，也不能被 `skill_read/skill_run` 绕过开关执行；管理页仍可查看停用技能的说明。用户同名技能优先于内置技能。

## RAG 开关与检索设置

主对话和悬浮助手的输入框下方，与发送按钮同一行放置 **RAG / 记忆 / Skill** 三个独立总开关。开关同步保存到 `System/Agent/runtime.json`，局部更新不会清空其他设置。

- RAG 关闭：禁止助手调用 `kb_search/kb_read`；不影响记忆。
- 记忆关闭：停止对话前自动召回，禁止助手调用 `memory_recall/memory_remember`；不影响资料检索。已有记忆保留，记忆管理页仍可手动查看和修改。
- Skill 关闭：不加载技能目录，禁止 `skill_read/skill_run`；具体技能仍在“技能”页按项启用。

主动引用的资料、回复选段及当前页是用户提供的上下文，仍可使用。`rag_top_k`（1–20）限制每次资料/记忆召回条数；`rag_context_chars`（256–32000）限制记忆 ContextPack 字符预算；高级设置的 `auto_recall` 控制对话前自动召回。

未指定 limit 时，资料检索、检索试用和记忆召回均以 `rag_top_k` 为默认数量，模型工具参数同步显示当前上限，不再写死为 8。模型仅在确需更少结果时指定 limit；显式更大的值仍被用户上限限制。检索试用分别显示实际数量和上限。上限不保证一定命中该数量：匹配不足、去重、类型条件、来源失效或记忆字符预算都可能使结果更少。

**配置入口：设置 → RAG / 嵌入模型，或 Agent → RAG，或输入框旁齿轮。** 填写支持 `/embeddings` 的 Base URL、模型 ID、API Key；维数 0 表示模型默认（部分模型不支持自定义维数，应保留 0）。Base URL 可包含 `/v1`，也支持填写完整 `/embeddings` 地址；本地无鉴权服务可不填 Key。选择关键词、语义或混合模式后保存。

“保存并测试连接”仅嵌入一段短测试文本。“保存并更新索引”明确触发资料分块和嵌入调用；未修改分块复用已有向量。不会打开设置就发送整个资料库。保存密钥后输入框留空表示保留；清除必须勾选清除选项。Embedding 配置及凭据在本机 `config/agent-rag.json`，公开接口只返回 `has_api_key`，不进入对话、Agent 备份或工作区同步。

资料向量索引为 `Workspace/System/Agent/rag.sqlite`，与长期记忆库独立，可重新构建。默认索引所有知识条目 Markdown 正文，按字符分块、段落边界与重叠切分，嵌入标题及分块文本。可选索引文献 PDF 全文，保留 paper_id、页码和字符位置；扫描件需先 OCR，空正文在进度中计数。源文档保留原路径，向量索引不替代 Markdown/PDF。

构建在后台执行，显示来源、分块、新嵌入和复用计数，支持取消；完整新索引成功后原子切换，失败或取消保留旧索引。中途停止进程后再次更新会清理未发布的分块。修改模型、接口、维数或分块配置会使原索引失效，需重建。资料修改后手动点击更新；检索会过滤已经修改或删除的来源，防止引用旧正文。

`kb_search` 使用所选模式：关键词模式不调用 Embedding；语义模式嵌入问题并以归一化向量做精确余弦排序；混合模式将文档关键词命中和语义分块按文档 ID 做 RRF 融合。返回实际命中分块、路径、版本、字符区间及 PDF 页码。没有可用索引或接口失败时，语义模式报清晰错误，混合模式返回关键词结果并附 `warning`。相同问题的查询向量缓存最多 128 项、5 分钟。当前为 SQLite 中最多 100,000 分块的精确扫描，无 HNSW/ANN；大型资料库不宜视为专用向量服务的等价替代。

检索试用或对话示例：“有哪些减少微调参数的方法？请先检索知识库，给出命中的依据，再读取相关正文进行比较。”模型可调用 `kb_search`，依据命中来源继续 `kb_read` 或 `pdf_read`，再生成有出处的回答。长期记忆仍使用独立的词法/实体召回，不会因配置文档 Embedding 自动为记忆批量生成向量。

`allowed-tools` 是技能的说明性元数据，不是授权来源。实际执行始终受人设工具白名单、运行设置和写入审批限制。Frontmatter 使用 PyYAML 安全解析，支持多行描述、工具数组与版本元数据。技能页支持 ZIP、文件夹和文本导入、资源浏览、环境诊断；工作区 `.agents/skills`、`.codex/skills` 也可自动发现。`agents/openai.yaml` 可控制展示名称和是否允许自动选用。运行时记录使用原因、包版本、资源和脚本次数；安装不会执行脚本。

RAG 页新增“自动更新”设置，可分别开启资料变化后更新和定期更新。默认均关闭，仅在 RAG 开启、语义/混合模式、服务运行时生效。实时检查每 5 秒一次，合并连续编辑（默认 15 秒）；定期默认 60 分钟。只为变化分块重新嵌入，失败或取消保留旧索引，同一变化不会无限实时重试。“清除向量数据库”删除派生向量、压缩数据库并关闭自动更新，保留 Markdown、PDF、长期记忆与接口配置；有运行中的构建时须先取消并等待结束。

## 任务执行与上下文

普通 `/api/agent/send` 仍输出兼容的 SSE 事件，但实际执行已转为后台任务。新增 `run` 事件提供任务 id；浏览器断线不取消任务。停止按钮向任务发送取消信号；任务中心支持暂停、继续和失败重试。

SSE 响应头提供 `X-Agent-Run-ID`，持久化事件带 `id` 游标。终态快照会兜底发送 `done/error`，避免状态提交早于最终事件的竞态。共享客户端支持 CRLF、多行 data、末帧无空行与 UTF-8 分片；流中断后按同一个 run_id 读取状态与游标事件，不重新 POST 用户任务。真实模型错误仍显示为错误。

主聊天与悬浮助手均展示草稿查看、确认、拒绝和“继续任务”。审批操作共享状态并合并重复点击；网络错误保留待确认状态，不伪装成拒绝。继续操作从已有任务检查点执行，两处对话同时接收结果。历史会话返回最新 run_status，已完成任务不会因旧的待确认消息重新出现继续按钮。

每个会话最多一个 queued/running/pausing 任务。写入前记录工具执行预留，执行后记录完整结果。进程重启把遗留任务标为 interrupted；用户继续时从检查点恢复。已成功的调用按 call_id 复用结果；预留后进程中断而结果未知的调用返回 uncertain，要求读取核对，不会自动重放副作用。

审批流程：模型生成草稿 → 状态 waiting_approval → 用户检查正文并确认或拒绝 → 点击“继续” → 将真实审批结果交还模型继续执行。确认操作先持久化 executing 状态，并串行执行，防止重复点击造成重复写入；若进程在写入期间退出，executing 草稿需人工核对目标内容，不能直接重复确认。

默认每次执行 48 轮、900 秒软预算。达到预算会暂停并保留检查点；继续后获得新的执行预算。相同工具参数持续重复时会阻止重复执行，连续触发保护后暂停。取消可停止等待模型响应，并在工具边界检查；已经完成的写入不能撤销，外部工具调用可能需要等待返回。

历史保留工具调用及原始返回，不再只保留聊天文字。上下文预算使用本地字符启发式估算，未宣称与供应商 tokenizer 完全一致。超预算时以消息组为单位进行摘录式压缩，保持 assistant/tool 配对；完整证据通过 `evidence_read(run_id, call_id, offset)` 重读。超出预算的单次输入会明确报错。此版本没有额外调用模型生成语义摘要。

自动召回仅使用当前会话、当前项目及用户/全局记忆。Agent 保存长期记忆使用 `memory_remember`，遵循写入模式；不把每段对话自动当成事实。记忆正文会过滤 `<private>` 和常见凭证格式，原始聊天和工具事件仍是本地执行记录，不能当作脱敏日志对外发布。

## 科研工具与写入保护

- `kb_search/kb_read`：索引检索、分页读取，返回正文哈希版本。
- `kb_create_entry/kb_update_entry/kb_rollback`：命名与查重、更新草稿、版本冲突检测、修订回退。整体覆盖必须带 `expected_version`；追加可读取最新版本后执行。
- `lit_context/lit_note_write/pdf_read`：元数据、文献笔记、按页读取 PDF，最多五页，扫描件可能需要 OCR。
- `workspace_list/workspace_read`：只允许 Knowledge/Projects/Resources 中的研究文件，拒绝越界与链接逃逸。
- `web_search/web_fetch`：通过 Crossref 检索论文元数据，读取公开网页。网页工具拒绝本地/私有地址，重定向重新检查，大小与等待时间有上限；网页内容始终作为参考数据。
- `memory_recall/memory_remember/plan_update/evidence_read`：来源记忆、任务计划和完整工具证据。
- `python_run/skill_run`：Docker 隔离 Python 运行与产物保存。

Python 运行默认关闭。使用前安装并启动 Docker，事先拉取运行设置中指定的镜像（默认 `python:3.12-slim`），再启用隔离代码执行。容器无网络、只读根文件系统、非 root 用户、去除 Linux capabilities，限制 CPU、内存、进程数和时间。仅复制显式选择的研究输入；结果写入专用 `/output` 挂载。日志/产物大小由运行器轮询限制，输出目录不是容器磁盘配额。宿主机不直接执行模型代码。打包 exe 也通过 Docker 中的 Python 运行，不依赖 exe 自身充当解释器。

PDF 工具和技能解析需要 `pip install -r requirements.txt`。桌面构建会包含 pypdf、PyYAML 和内置技能目录。

## MCP 连接

实现 Streamable HTTP JSON-RPC（JSON/SSE 响应，协议版本 `2025-03-26`），不支持 stdio、OAuth 交互登录或旧版 HTTP+SSE 双端点传输。配置示例：

```json
[
  {
    "name": "papers",
    "url": "http://127.0.0.1:9000/mcp",
    "enabled": true,
    "tools": ["search", "save_note"],
    "read_only_tools": ["search"],
    "headers_env": {"Authorization": "PAPERS_MCP_AUTH"}
  }
]
```

环境变量保存完整请求头值，例如 `Bearer …`。配置中不填写凭证本身。保存后刷新连接，检查诊断，然后到人设编辑器勾选所需远端工具。只有显式 tools 白名单中的工具会被注册；未列入 read_only_tools 的工具默认按写操作审批。新任务可重新发现已配置工具。

## API

| 操作 | 接口 |
| --- | --- |
| Embedding 与向量索引 | `GET /api/agent/rag`，`POST /api/agent/rag/settings`、`/test`、`/index`、`/cancel`、`/clear`、`/search` |
| 系统与设置 | `GET /api/agent/system`，`POST /api/agent/settings` |
| 后台任务 | `POST /api/agent/runs`，`GET /api/agent/runs?session_id=...` |
| 任务详情/游标事件 | `GET /api/agent/runs/<id>`，`GET /api/agent/runs/<id>/events?after=<seq>` |
| 任务控制 | `POST /api/agent/runs/<id>/pause|cancel|resume|retry` |
| 记忆 | `GET /api/agent/memories?session_id=...&project_id=...`，`POST /api/agent/memory/remember|recall|forget` |
| 关系 | `GET /api/agent/memory/graph?session_id=...&project_id=...` |
| 技能 | `GET /api/agent/skills`，`POST /api/agent/skills/install|import|read|resources` |
| MCP | `POST /api/agent/mcp/refresh` |
| 一致性备份 | `POST /api/agent/backup` |

运行设置只存本机 `System/Agent/runtime.json`。模型 API Key 继续由现有配置层管理，不写入任务请求或运行检查点。

## 验证

主对话与悬浮助手的回复提供“RAG 检索依据”，展示实际查询、检索方式、单次命中数/上限、去重来源数、可打开的标题、片段及页码/字符范围。Embedding 失败后的关键词回退在折叠区域外提示。数据由工具证据生成，不依赖模型自述；旧会话可从原始 evidence 重建，无需重新请求模型。生成期间可查看来源，展开状态在流式刷新时保留。

新消息记录本轮开始时的 RAG、记忆和 Skill 有效状态。“术语建档员”等人设与 Skill 是独立机制，关闭 Skill 不删除所选人设；纯检索任务不应输出建档去向清单。用户明确要求“只参考 RAG”时，本轮不注入记忆、旧回答或页面资料，仅提供资料检索、已命中来源读取和当前任务证据读取；工具层阻止技能、外网、写入及未命中来源的扩展读取。该限制不更改全局开关。模型未取得任何 RAG 结果时会被要求先检索，持续不检索则明确返回无证据，未取证的直接回答不会逐字显示。

多轮执行中的公开回答随 `response` SSE 事件按轮展示，并作为 `assistant.response_parts` 随最终结果和历史会话返回。`content` 仍保留最终回复，完整工具证据仍用于下一轮上下文。旧会话会从已存证据恢复中间回答，不需要调用模型；这些正文不包含 `reasoning_content` 或文本工具协议控制块。中途失败保留浏览器已收到的正文。

主 Agent 回复选中文字后，“问 AI”保留当前对话；“引用”可以多次添加选段，支持预览、移除及发送后查看，合计最多 4000 字。发送时作为 `context.quote_text` 提供参考数据，随消息和历史上下文保存。选区工具不会覆盖已经输入的问题。

Agent 会话列表读取对临时网络/服务错误重试；连续失败在会话侧栏显示接口与连接说明并提供“重试加载”，不再用全屏 `Failed to fetch` 替换 Agent 页面，重试时保留输入草稿。持续连接失败仍需检查本地服务是否运行。

`python -m unittest discover -s tools -p test_agent_system.py -v` 在一次性工作区使用脚本化模型验证：迁移、作用域隔离、中文/关系/向量检索、替代与 TTL、Skill 加载、真实工具证据跨轮回放、审批后续跑、文本协议、轮数暂停、重启恢复、停止信号、写入防重复、冲突和修订回退、MCP 白名单、HTTP 后台任务及 SSE 断线继续。

`python -m unittest tools.test_agent_rag -v` 以本机 HTTP 模拟嵌入接口验证配置与密钥脱敏、向量响应校验、连接测试、增量分块与来源、删除/修改过滤、失败/取消回退、PDF 页码、工具调用和真实 HTTP 路由，不请求付费模型。

`node tools/agent_system_ui_check.js` 加载完整原始应用页面，以本地 API fixture 验证多轮正文实时展示/完成/重载、双向流式同步、切换会话后的结果归属、草稿预览/确认失败重试/后台续跑、断流状态恢复与游标回放、CRLF/多行 data/末帧无空行、输入保留、刷新异常不误报模型失败、Skill 按项启停与总开关、RAG 配置和全局设置入口、记忆增删、技能安装、MCP、备份及桌面/移动布局。恢复只读取原任务，测试检查没有重复 POST 或多次写入。需让 NODE_PATH 指向可用 Playwright 安装。测试不请求真实模型 API。

这些测试验证执行与数据契约，不代表任意模型的科研结论正确率；真实模型任务质量需要使用具体研究数据和验收标准评估。
