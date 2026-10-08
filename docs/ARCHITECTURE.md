# Architecture · workbench-v260920.2

```text
Browser SPA
  web/index.html
  web/styles.css
  web/app.js
       │
       │ JSON HTTP
       ▼
ThreadingHTTPServer (server.py)
       │
       ├─ app/config.py       配置、环境变量密钥状态、Agent 请求预设
       ├─ app/workspace.py    Workspace / 项目目录 / 迁移
       ├─ app/store.py        Markdown、标签/项目/WikiLink 图谱、BibTeX、导出
       ├─ app/activity.py     科研活动 / 热力图
       ├─ app/todos.py        Todo
       ├─ app/search.py       全局检索
       ├─ app/agent.py        会话、图像、知识引用、工具调用循环、OpenAI-compatible 调用
        ├─ app/agent_tools.py  M1 工具层：kb_search/kb_read/kb_create_entry/kb_update_entry/lit_context/lit_note_write + 写工具草稿确认流
        ├─ app/kb_naming.py    M1 命名规范校验：知识库条目标题 error/warn 双级（error 拒写）
       ├─ app/rss.py          RSS/Atom、arXiv fallback、缓存与诊断
       └─ app/weather.py      Open-Meteo
```

## Markdown metadata

```yaml
---
id: note-...
kind: note
title: 示例笔记
project: 论文A
projects: [论文A, 项目B]
tags: [LLM, Agent]
status: 整理中
---
```

`project` 是向后兼容的第一主项目，`projects` 是完整多项目集合。

## Knowledge graph

节点：

- Markdown 文档节点；
- `tag:<name>` 虚拟标签节点；
- `project:<name>` 虚拟项目节点。

边：

- `wikilink`：正文 `[[WikiLink]]`；
- `tag`：文档 → 标签；
- `project`：文档 → 项目。

浏览器端先按“节点类别 + 关系来源”生成 filtered graph，2D/3D 渲染、邻域计算和 Markdown 导出都基于同一份 filtered graph，因此“当前显示什么，导出就采用什么”。

## Agent request presets

`config/app.json` 中 `llm.request_presets`：

```json
[
  {"id":"default","label":"默认","params":{}},
  {"id":"high","label":"高思考","params":{"reasoning_effort":"high"}}
]
```

前端每轮发送 `request_preset`。后端只从已配置预设中取 `params`，并合并到 API 请求体；核心字段受到保护。

## Agent 工具调用层（v260930 · M1/M2）

- `app/agent.py` `_run_with_tools`：原生 function calling 优先，端点 4xx 不支持时降级文本协议（\`\`\`json {"tool":…} \`\`\`），限 8 步。
- `app/agent_tools.py`：kb_search / kb_read / kb_create_entry / kb_update_entry / lit_context / lit_note_write；写工具 confirm 模式只出草稿（`System/AgentChats/Drafts/`），`/api/agent/drafts/<id>/confirm|reject` 确认后落盘。
- `app/kb_naming.py`：条目标题 error/warn 双级校验（规则见 `.trae/rules/知识库条目命名规范.md`），error 拒写。
- `/api/agent/send` 新增 `context` 参数：`{view, paper_id, page, doc_id, selection, write_mode}`，由前端悬浮球采集（`web/v260930-floating-agent.js`），`app/agent.py` `_page_context` 注入系统提示词。
- 悬浮球（M2）：全局常驻 `#erw-fab-ball`，面板带上下文条 / 工具轨迹 / 草稿确认卡片 / 划词气泡；文献上下文经 `window.ERWLiterature.context()` 桥，LLM 就绪探针 `window.ERWLLMReady`。
- v261008b · **工具轨迹可视化**：`_run_with_tools` 返回第 5 项 `timing`（`total_ms` / `llm_ms` / `tool_ms` / `rounds` / `tool_calls` / `protocol` / `timeline`，段级 `t0/t1` 相对本轮起点），挂到 assistant 消息随 SSE `done` 回传；前端渲染为「汇总一行 + 与耗时成比例的堆叠时间条 + 可折叠过程明细」（`window.ERWFabTimeline` 暴露给 Agent 页复用，样式在 `web/v260930-floating-agent.css` 的 `.fab-tl*`），流式期间另有一条实时条随 `round`/`tool` 事件推进。旧会话无 `timing` 时按 `tool_trace` 的 `ms` 顺序兜底。

## Agent 人设系统（v260930 · M3）

- 人设档案 `{id, name, builtin, system_prompt, tools, write_mode, request_preset, temperature}` 存于 `config/app.json` 的 `llm.personas`（非密钥），`app/config.py` `_clean_personas` 清洗 + `resolve_persona` 解析；内置 reader（只读三件套）/ executor（全量工具）缺失自动补默认，用户对内置人设的编辑优先于默认值。
- `send_message(..., persona_id=...)`：人设替换系统提示词、过滤工具白名单（specs 与文本协议提示同步收窄，`app/agent_tools.py` `execute()` 二次拦截）；温度取值链 preset > persona > 默认。
- 写模式取人设与页面开关**交集（更严格者胜）**：仅当人设 `write_mode=direct` 且页面开关也为 direct 才直写，否则一律出草稿；直写成功的 `doc_id` 记入 `tool_trace` 供前端展示。
- 前端：悬浮球面板人设选择器（`#fab-persona`，记忆于 localStorage）+ 设置页人设编辑器（`web/v260930-floating-agent.js` 监听 `erw-llm-settings-rendered` 事件挂载到 `#erw-persona-host`）。

## 术语提取与建档流水线（v260930c · M4）

- 内置人设 `archivist`（术语建档员，`app/config.py` `ARCHIVIST_PROMPT`）：系统提示词浓缩 `.trae/rules/名词拆解建档标准流程.md` 的核心纪律——先分族（同公式同失效模式合为一篇，禁跨族合写）→ 类别词六选一 → 标题按 `知识-<类别>-<名称>` → 正文五要素骨架（摘要/原理含名词总览/公式/方法·使用原因/场景/失效模式/关联）→ 每篇建档前 kb_search 查重 → 结束输出术语清单表。全量工具、默认 confirm（草稿确认）。
- 当前页正文注入：`web/literature.js` `pageText()` 从渲染页缓存的 pdf.js 文本几何（`textItems`）拼接正文（≤6000 字符），经 `ERWLiterature.context().page_text` → `buildContext()` → `/api/agent/send` `context.page_text` → `app/agent.py` `_page_context` 写入系统提示词。后端无 PDF 解析依赖。
- 悬浮球「提取本页术语」快捷按钮（文献页显示）：自动切换到 archivist 人设并预填 SOP 指令；上下文条显示「▤ 本页正文 N 字」chip。
- 草稿批量确认：单条消息 ≥2 篇待确认草稿时显示整批操作条（`.fab-draft-batch`），`resolveDrafts` 逐个调用 confirm/reject（草稿间无事务，单个失败不影响其余），完成后统一汇报成功/失败数。

## 阅读中知识关联（v260930d · M5）

- 后端匹配：`app/store.py` `match_related(page_text)`——页面正文 × 全库条目标题/标签纯文本匹配（零 LLM 依赖）。候选词由 `_title_terms` 提取：知识类取名称段（去 `知识-<类别>-` 前缀）再拆词，文献类只整题参与不拆词（论文名单词撞页面文本噪声大）；英文虚词走 `_EN_STOPWORDS` 停用表，短英文介词排除、全大写缩写保留。权重：整名称段命中（50+）> 标题 token（按词长）> tags 半权；同分时 note 优先。
- 路由：`POST /api/kb/related {page_text}`（server.py），返回 `{items:[{id,title,kind,kind_marks,excerpt,hits}]}`，默认 top 8。
- 悬浮球面板：`#fab-related` 关联区——打开面板/翻页时 `ensureRelated()` 匹配当前页正文（同页不重复请求），命中显示 chips + 展开卡片（摘要/命中词/「打开条目」/「问 AI 关联」）；单条命中自动展开。
- 跳转桥：`web/app.js` 暴露 `window.ERWNav.open(kind, id)`（navigate 到对应路由 + selectDoc），悬浮球卡片借此打开知识条目。
- 划词气泡：新增「查知识库」动作——选中文本直接调 `/api/docs?q=` 即时检索（不经 AI），结果复用关联卡片渲染。
- 翻页事件：`web/literature.js` `track()/go()` 派发 `erw-lit-page`，悬浮球监听后刷新上下文条与关联知识。
- 导入顺序防雷：`agent_tools.py` 顶部不再 import workspace、specs 的 kind enum 用字面量 `_KIND_ENUM`——否则 `store→workspace→config(模块级 reload_all)→agent_tools` 链会循环导入炸模块（本次实测踩雷两处，均已修复）。

## 悬浮球增强（v260930e · 截图 / 阅读区选中 / 历史回看）

- **截图附图（多模态）**：`web/literature.js` 暴露 `window.ERWCapture`——`page()` 同步截当前 PDF 页（复用 `pageDataUrl()`），`area()` 返回 Promise 走框选流程（`S.areaResolver` 在框选完成回调中 resolve，外部接管优先于阅读区 AI 面板联动）。悬浮球面板新增「📷 截当前页 / ⬚ 框选截图」：截当前页立即附加；框选先收起面板、框完回填再开面板。附图 dataURL 暂存 `S.images`（≤4 张，缩略图可删），**发送时**才经 `POST /api/agent/assets` 上传落盘换相对路径（后端链路沿用 M2：`save_image` + `send_message` 收 `image_paths`，user 消息存 images）。单张上传失败 toast 提示但不阻塞其余。
- **消息附图渲染**：`msgImagesHtml()`——`data:` 前缀直接用（本地乐观渲染），否则 `/workspace-file/<path>`（历史会话加载）。
- **阅读区划词气泡**：`onDocMouseUp` 移除 `if(q(".lit-shell"))return` 守卫，PDF 阅读区划词同样弹出解释/总结/存知识库/查知识库气泡（此前为避免双 UI 跳过，用户要求补齐内容选中功能）。
- **历史会话回看**：面板头部新增 🕘 按钮切换 `S.view`（chat ⇄ history）。历史视图 `GET /api/agent/sessions` 渲染列表（标题/时间/条数/预览，当前会话高亮），点击即切换 `S.session` + `loadSession()` 回对话视图；新建对话同样重置视图。
- 版本参数升至 `v=260930e`（literature.js / floating-agent.js / floating-agent.css）。
- **悬浮球拖拽移动（v260930f）**：`initBallDrag()` Pointer Events 拖拽（`setPointerCapture`），位移 <5px 视为点击（不误开面板）、拖后吞 click；位置夹取在视口内，持久化 `localStorage.fabBallPos`，启动时 `restoreBallPos()` 恢复；CSS 加 `touch-action:none` 与 `.dragging` 态（抑制 hover 位移）。
- **知识库写入能力保障（v260930g）**：工具注册表本就含 3 个写工具（kb_create_entry / kb_update_entry / lit_note_write），但悬浮球默认人设 reader 白名单只读，写类请求被工具过滤挡住。修复：①默认人设改 executor（老用户尊重 localStorage 已存选择）；②`ensureWritePersona()`——写类动作（气泡「存知识库」、快捷动作「整理为知识库笔记/写文献笔记」）在当前人设无写工具时自动切到 executor（或首个有写工具的人设）并 toast 提示；③上下文条加「✎ 可写 / ◔ 只读」徽章（`personaHasWrite()` 实时判定，人设加载/切换即刷新），只读悬停提示会自动切换。人设架构（reader 只读定位）不变，仅改默认值与自适应兜底。
- **统一写作约束注入（v260930g4）**：`<Workspace>/System/AI助手写作与建档规范.md` 是 AI 的「写作记忆」单一真相源——六类条目命名硬规则、知识条目五要素骨架、日志/总结/灵感/里程碑/文献笔记模板、写作纪律（查重先行/只增不改/数值可追溯/交叉引用闭合/不臆造）。`config.writing_rules()` 首次调用读全文（utf-8-sig，缓存；经 `ensure_workspace()` 动态解析路径，打包 exe 后亦正确；文档缺失时回退内置浓缩版）；`agent.send_message` 把它拼在所有人设系统提示词最前部。改文档即改 AI 行为，无需动代码。注意该文档属工作台数据，**不放 `.trae/rules/`**（IDE Agent 规则目录，且发布产物中不存在）。

## RSS resilience

arXiv 来源支持 RSS → 官方 Atom API 自动回退。若全源失败：

- 有旧缓存：返回旧内容并标记 `stale=true`；
- 无旧缓存：返回诊断但不写空缓存；
- 强制刷新始终重新发起网络请求。


## Agent 密钥边界（v260920.2）

工作台只保存 `llm.api_key_env`（环境变量名称）。真实 API Key 由 `app/agent.py` 在请求发生时从 `os.environ` 读取，不进入 Workspace、`config/app.json` 或 Agent 会话文件。


## v260921.1 UI interaction notes

Knowledge Graph keeps Markdown as the source of truth. The canvas now maintains per-view camera state (pan/zoom/rotation), and selecting a node opens a read-only Markdown preview without creating duplicate storage. Milestone 3D preview follows the same pattern. Runtime/server parameters remain in `config/app.json` but are now editable through the Settings UI.


## Agent Provider 接入（v261008 · OpenCode Go / 火山方舟 Agent Plan）

Agent 只依赖一种协议——OpenAI-compatible **Chat Completions**，所以「接入一个服务」= 往 `config/secret.json` 的 `profiles` 里加一套档案。设置页「Agent API 配置」与本次接入同源：读写都走 `POST /api/config/app` → `config.save_app` → `_merge_profiles_from_public`（按 profile id 保留原 Key，新增档案才带 Key 落盘）。

| 档案 id | 名称 | base_url | 默认模型 |
| --- | --- | --- | --- |
| `profile-legacy` | Qianwen3.8-Flash（原有） | `https://maas.qianwenaiapi.com/compatible-mode/v1` | `qwen3.8-flash` |
| `profile-opencode-go` | OpenCode Go · 本地代理 | `http://127.0.0.1:9355/zen/go/v1` | `deepseek-v4.1-flash` |
| `profile-opencode-go-direct` | OpenCode Go · 直连 Zen | `https://opencode.ai/zen/go/v1` | `deepseek-v4.1-flash` |
| `profile-ark-agent-plan` | 火山方舟 · Agent Plan | `https://ark.cn-beijing.volces.com/api/plan/v3` | `deepseek-v4.1-flash` |

- **代理一套**（`profile-opencode-go`）依赖本机 `D:\Project\opencode-go-proxy-for-trae.py` 反代理（监听 `127.0.0.1:9355`）在跑，由代理注入 `x-opencode-session / x-opencode-request / x-opencode-client / x-opencode-project` 四个头；工作台侧填真实模型名即可（`proxy-` 前缀也会被代理剥掉，两种写法都通）。
- **直连一套**（`profile-opencode-go-direct`）不经任何本地进程，直接打 `opencode.ai`。上游要求 `x-opencode-session`（缺它返回 400 `Request is missing x-opencode-session and cannot be routed efficiently`），故新增**档案级自定义请求头**能力承载：`profiles[].headers` 经 `config._clean_headers()` 白名单化（头名须 RFC 7230 token、值禁 CR/LF、单值 ≤512 字符、最多 20 条），由 `agent._api_headers(api_key, extra)` 合并进所有请求路径——普通补全、SSE 流式、`/models` 探针、对话探针都带。实测**只有 session 是硬要求**，`x-opencode-request/client/project` 可省（保留是为了与官方 CLI 同形）；`Content-Type` 与 `Authorization` 由工作台接管、自定义头覆盖不了，`User-Agent` 允许改写。设置页「Agent API 配置」已加「自定义请求头（JSON）」输入框。
- 火山方舟必须用 **Agent Plan 专属网关** `/api/plan/v3`：通用网关 `/api/v3` 与 Coding Plan 网关 `/api/coding/v3` 都会 401（`The API key or AK/SK in the request is missing or invalid`）。
- 切换方式：Agent 页顶部「API 配置」下拉，或设置页「Agent API 配置」→「设为当前配置」。
- ⚠️ 旧版 exe（v260924.1 及更早）的 `_normalize_profile` 不认识 `headers`：在旧版里点「保存全部配置」会把直连档案的请求头**静默抹掉**。直连配置需配 v261008.1 及以后的 exe（或开发模式）使用。

### 接入实测结论（2026-10-08）

- 三家均支持：Chat Completions 非流式、SSE 流式（`agent._stream_chat`）、原生 function calling（`agent._run_with_tools`，工具循环实测命中知识库）、`reasoning_content` 回传（前端「模型思考过程」可折叠展示）。
- **关思考参数**：三家都认 `{"thinking": {"type": "disabled"}}`（实测 `reasoning_content` 归零），故各带一个「· 无思考」请求模式；`reasoning_effort=low` 与 `enable_thinking=false` 在实测中均被忽略。
- **`GET /models` 兼容性**：opencode 代理转发与 `opencode.ai` 直连都正常返回模型列表；方舟 Agent Plan 返回 **404**。`app/agent.py` `test_connection()` 因此增加回退分支（v261008）：仅当 /models 报 404/405/501 时，用默认请求模式的模型发一次 16-token 对话探针，返回 `choices` 即判定连通（响应带 `probe=chat_completions`）；401/429/5xx 仍原样抛错保留诊断信息。
- **Cloudflare UA 边界**：opencode.ai 按 UA 拦访问，`Python-urllib/*` 默认 UA 触发 Cloudflare 1010；工作台 `_api_headers` 自带的 `Workbench/260922.3`（直连与经代理都实测放行）与代理注入的 `opencode/1.18.29 cli` 都可用。**改 `_api_headers` 的 UA 时需重新实测这条链路**，必要时用档案 `headers` 覆盖 `User-Agent` 绕过。
- 打包提醒：`app/agent.py`、`app/config.py`、`web/` 属源码改动，**必须重跑 `build_client.bat` 才对 exe 生效**；只改 `config/secret.json` 档案则热生效（设置页保存或 `POST /api/system/reload`）。v261008.1 已重打包（2026-10-08 12:11）。
- ⚠️ **换版时的「次生窗口劫持」**：`client.py` 绑定 8765 失败时会探测既有实例，若其 `/api/health` 健康就只开一个次生窗口挂上去（单服务多窗口设计）。因此若上一个版本（或开发模式的 `python server.py`）仍占着 8765，双击新 exe **不会**让新代码生效，`workbench.log` 会留下 `bind failed (WinError 10048) … opening a secondary window`。换版务必先结束旧进程再启动新 exe，并用 `GET /api/config` 是否返回 `headers` 字段确认运行中的是新版 `config.py`。


## 用量计费（v261008 · v261008b 升级口径）

数据流：`app/agent.py` 三处挂钩采量 → `app/billing.py` 算价落账 → `/api/billing/*` → `web/v261008-billing.js` 三页签仪表盘。

- **采量点**：`_stream_chat` 末帧 usage（SSE 主路径）、`_post_chat` 非流式 usage、`cfg["_billing"]` 上下文（会话 + 请求模式 + source=chat/assist）决定归属；连通性探针无上下文，自动不计费。
- **落盘**：`Workspace/System/billing/prices.json`（单价表 + `plans` 计费方式）、`ledger.jsonl`（逐条追加，**只增不改**）。
- **计费方式**（`prices.plans.<profile_id>.mode`）：`token`（默认，按单价表）/ `subscription`（订阅套餐：只记用量，金额列不适用，不再报「缺单价」）/ `free`。
- **单价键优先级**：`<profile_id>/<model>` → `<profile_id>`（该档案兜底价）→ `<model>`（支持 `*` 通配）→ 大小写无关。同一模型在不同 Provider 价格不同时，用档案限定键区分。
- **计价口径**：`cost = miss_in/1e6*input + out/1e6*output + cache_read/1e6*cache_hit + cache_write/1e6*cache_write`，其中 `miss_in = prompt_tokens - cache_read - cache_write`；未命中单价的 token 模式调用记 0 且标 `priced=false`（绝不伪造金额）。
- **缓存命中率**：总览/按会话/按模型都给出 `cache_hit_rate`——长上下文 Agent 的主要成本变量（本地实测 72.5%：输入 1,078,568 中 781,952 命中，计费输入仅 296,616）。
- **兼容老账本**：早期记录没有 `billing_mode`，读取时按当前 `plans` 推导（`_view()`），文件本身不改写；`usage_missing` 记录用于「网关未返回 usage」的调用，保证次数口径一致。
- **币种与汇率**：单价条目可带 `currency`（默认取表头 `currency`，直接粘贴官方人民币标价就写 `CNY`），价格表顶层 `fx` 语义为「1 USD = N 该币种」（预置 CNY≈7.1，参考值、可改）；`convert_cost()` 统一折算，缺汇率的条目标 `fx_missing` 且等价记 0（不猜数）。
- **等价标价**（v261008b）：订阅/免费档案实付口径不适用，但仍按同一份单价表（官方标价）折算 `equiv_usd`，`summary()` 另给 `subscription_equiv_usd`；页面以「等价标价合计」卡片与各表「等价标价」列呈现，并明示为参考而非实付。老账本读取时用当前单价表补算等价标价，但 token 模式写入时冻结的 `cost_usd` 不改（历史实付口径不追溯）。
- **已预置标价来源**：DeepSeek 官方 [模型 & 价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)（2026-10-08）——`deepseek-v4.1-flash` / `deepseek-flash` 空闲时段 输入 1 元、缓存命中 0.02 元、输出 4 元 / 百万 tokens，高峰时段 ×2；其余条目沿用 dsh-cost-meter 参考价，需按实际账单核对。
