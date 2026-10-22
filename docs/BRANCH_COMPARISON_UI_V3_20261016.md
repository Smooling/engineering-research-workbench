# 当前分支与 UI Redesign V3 对比及合并建议

评估日期：2026-10-16。本文记录代码对比、只读检查及隔离回归测试结果，不代表已完成合并或修复。

## 1. 对比范围与结论

| 对象 | 分支 / 提交 |
| --- | --- |
| 当前分支 | `feature/slim-workbench-v261009`，`301398a3b422bf2b6167aced22f1d878d0f25c29` |
| 目标仓库 | `git@github.com:Smooling/engineering-research-workbench.git`，本地 remote 为 `upstream` |
| 目标分支 | `feature/ui-redesign-v3`，已 fetch 至 `97932f3`（`bulid exe!`） |
| 共同祖先 | `320c8f0e7d449d6dd86344a7eddb91fb33d0b73c` |
| 双方独有提交数 | 当前 100，目标 1 |
| 两端最终树差异 | 450 个文件，新增 33,710 行、删除 4,627 行；其中 187 个文件属于本地 PDF.js 资源 |

当前 HEAD 已合入旧 V3 基线 `320c8f0`，但尚未包含远端最新的桌面增强提交 `97932f3`。因此应按三方差异判断归属：远端新加的桌面文件在当前树中不存在，并不表示当前分支主动删除了它们。

建议保留当前的契约单源、插件平台、验证设施与科研数据模型；版本管理保留，但先修写入一致性回归。接入最新 V3 的桌面、草稿和未保存保护，并适配插件与装配清单。当前状态适合作为集成起点，尚不适合直接作为可发布版本。

已有性能优化多数位于共同基线：后台扫描、SQLite 快照读取、图谱增量更新及 MathJax/Mermaid 按需加载，不能整体算作当前分支新增。当前另有 vendor 加载、DOM 接缝及插件迁移等后续工作。V3 的主要视觉基底仍在，`v261014-linear-luxe.css` 两端仅有一行替换，当前变化主要是架构和功能演进。

## 2. 当前分支独有内容与保留价值

| 改动组 | 具体变化 | 建议 |
| --- | --- | --- |
| 内核契约集中 | `core/contracts/` 统一 kind、字段、命名、标记、状态和关系声明，写入期校验；不再在 store/MCP 各抄一套 | **优先保留**。减少新增类型、修改规则时的多处漂移 |
| 科研数据模型 | 实验成为独立第七类，与日志分开；增加依据知识、使用数据、引用、实验系列、上下环节、产出等类型化关系；标签及无归属项目筛选 | **保留**。适合本项目科研工作流；旧实验数据迁移须另做 dry-run，不能随代码合并批量改数据 |
| 前端扩展边界 | `web/manifest.json` 生成引用块；`ERWPanels` 自登记；显式 `erwFetch`；共享 `ERWDom`；vendor 按需加载；日期补丁按功能重命名 | **优先保留**。新页面与插件有明确接入口，降低核心脚本耦合 |
| 诊断与工程验证 | doctor、索引迁移与维护、静态检查、真实浏览器路由冒烟、常驻测试、CI、发布说明和内置手册 | **优先保留**。但通过现有 CI 不能替代索引架构回归测试，后者本次检出了问题 |
| 插件平台 | 发现、依赖、执行上下文、后台任务、ZIP 解包、管理/配置/预览、脚手架；后端只通过 `core_api` | **保留平台和既有功能迁移**。它是本分支最有价值的结构变化之一 |
| 既有功能插件化 | 图谱、文献阅读工作区、悬浮助手、资讯、天气、计费、专注计时迁入插件；PDF.js/CMap/字体本地化 | **保留**。旧模块删除多为迁移，不能只恢复旧文件；特别要保留文献离线资源 |
| 新增生态插件 | 报告导出、指标表、备份快照、日历提醒等 | **按需求启用**。可随平台保留，但不需要全部成为默认功能或主界面入口 |
| MCP/Agent 接入 | `mcp/` 正式入库，工具按已启用插件暴露；插件写工具进入 Agent 草稿确认流；设置增加外部写入开关 | **保留并准确说明权限**。MCP 写入默认关闭，插件写知识库默认开启；这不是进程级插件沙箱 |
| 版本与来源追踪 | `app/versions.py` 留内核，界面为 version-manager 插件；来源、分支时间、逐节对照/合并、整版采用、归档恢复、自动快照节流；版本不进入普通列表和索引 | **保留，完成回归后合并**。标题归族、采用与归档涉及数据语义，需要重点验证 |
| 外部文件修改识别 | 根据文件 mtime 与事件记录识别外部改写 | **保留但限定承诺**。能发现记录缺口，不能还原首次发现前的旧正文，也不能据此确定具体编辑器 |
| 卡片与多项目布局 | 固定条目卡片高度，标题/摘要两行截断及提示，修正窄列与多项目展示 | **保留**。改动小，直接改善已有界面 |

代表性提交：契约 `e321a9d`、实验及关系 `5d753b4`、装配检查 `a965a12`、面板接缝 `498d994`、插件运行时 `5247953` / `e203163`、版本模型 `b92e334`、版本插件 `2ceffd6`、MCP 插件拆分 `771b9c0`、卡片布局 `9bb9eff`。这些是定位锚点，不能把各组后续修复拆散，仅摘取首个提交。

当前发现 12 个有效插件：backup-snapshot、billing、floating-assist、focus、knowledge-graph、literature-reader、metrics-table、milestone-calendar、report-export、rss、version-manager、weather。

## 3. 最新 V3 应接入的内容

远端独有的 `97932f3` 覆盖 35 个文件，新增 3,012 行、删除 300 行，包含：

- 桌面窗口桥接、无边框 WebView2、托盘、单实例、Windows 窗口处理、通知和桌面自检。
- `FocusTimer` 原生线程计时，避免窗口隐藏时浏览器计时器节流影响专注倒计时。
- 独立桌面依赖及 Windows EXE/ZIP 构建脚本、发布哈希与使用说明。
- 深色主题、异步对话框，以及新建草稿、切换文档/路由/退出时的未保存保护。
- 服务端草稿准备接口、HTTP 排队容量和断连容错、相关测试扩展。

其中新建草稿及未保存保护应优先接入：当前 `web/app.js:1099` 新建按钮仍直接 POST 落盘，再重绘列表；该路径没有先处理当前未保存内容。远端使用 `/api/docs/draft` 获取尚未落盘的草稿，并以 `guardEditor` 统一处理保存、放弃和取消。不能用当前的局部 confirm/beforeunload 代替这一整套行为。

适配要求：

1. 桌面、深色主题、异步对话框资源经 `web/manifest.json` 装配，重新生成 `index.html`；不要手工保留两套引用块。
2. 远端编辑器保护接入当前的七类条目、标签/项目筛选、插件面板及阅读工作区；不要整份覆盖 `app.js`。
3. 原生专注计时通过明确的桌面 API 提供给 focus 插件；当前插件仍是浏览器 `setInterval` 倒计时，避免把具体插件功能重新硬编码回内核。
4. 移入插件的阅读、计费、悬浮助手和项目页面也要接入远端相应交互修复，不能恢复已淘汰的旧补丁入口。

## 4. 合并前需要处理的问题

### A. Agent 写入后索引不能立即读取（已复现）

`app/agent_tools.py:176` / `:197` 为记录来源，改为直接调用 `store.create_doc` / `store.update_doc`。写入成功，但该路径不执行索引刷新，而检索走索引。

`tools/test_index_architecture.py:143` 的测试在创建后立即检索 `agentunique`，结果为空并触发 `IndexError`；同一测试后续的更新断言因此尚未执行。更新路径存在相同结构缺口，但本次该测试直接证实的是创建后不可见。

建议让统一写入服务同时保留来源/版本逻辑和索引同步；不能为恢复索引而绕开来源记录或快照。

### B. 修改项目归属残留旧项目 ID（已复现）

`app/perf_index_runtime.py:104` 仍有 `normalize_project_update`，但新版 `update_doc` 在 `:206` 委派 store 时未使用它。修改项目名后，旧项目 ID 仍可能留在元数据中。

`tools/test_index_architecture.py:224` 的测试中，First 改为 Second 后，返回的 `project_ids` 仍是 First 的 ID，断言失败；该测试后续的清空归属及按 ID 改挂步骤尚未执行。

建议在唯一写入路径恢复项目名/ID 的替换与清空语义，并覆盖单值、多值、名称、ID 四种输入。

### C. 独立 EXE 尚未适配插件化资源（静态确认，未实际打包）

当前 `build_client.bat:73` 仅显式加入 `web` 和 `VERSION`，没有加入 `plugins` 与 `docs/manual`。插件发现打包态查找 `_MEIPASS/plugins` 或 EXE 同级插件；手册从 `ASSET_ROOT/docs/manual` 读取。因此仅把 EXE 放到干净目录运行时，无法获得源码目录中的随包插件与手册。

远端新 `tools/build_windows.py` 也未包含上述资源，不能原样照搬。应补插件清单、后端、前端及依赖资源和手册，并在无源码、无预置 Workspace 的目录验证。另需审查配置持久化位置：`app/external_access.py` 当前按模块路径定位 config，打包态应核对是否落在临时解压目录。

## 5. 合并预演与推荐步骤

运行 `git merge-tree --write-tree --name-only HEAD upstream/feature/ui-redesign-v3`，仅计算合并树，不修改工作区、索引或分支。预演返回 7 个冲突路径：

| 路径 | 处理原则 |
| --- | --- |
| `app/store.py` | 保留契约/来源/版本写入能力，接入远端草稿准备接口；同时修复写入一致性 |
| `web/app.js` | 保留当前注册表和新类型，移植远端草稿/未保存/退出保护 |
| `web/index.html` | 以最终 manifest 重新生成 |
| `plugins/billing/web/panel.js` | 将远端旧计费模块的交互修复移入插件 |
| `plugins/literature-reader/web/panel.js` | 将远端旧阅读模块的交互修复移入插件 |
| `web/v260922-projects.js` | 当前删除、远端修改；把有效改动移植到当前项目页面实现，避免复活旧模块 |
| `docs/ARCHITECTURE.md` | 同时描述插件架构和最新桌面运行方式 |

自动文本合并成功也不代表功能已兼容：`client.py`、`server.py`、打包脚本和被重命名的其他模块仍需语义检查。

推荐从当前 HEAD 创建集成分支，合并远端 `97932f3`，按上述原则解决冲突。无需把 100 个历史提交逐个 cherry-pick 到 V3，后续修复和功能迁移相互依赖较多。若必须向 V3 提供精选变更，应按“契约与验证 → 插件平台及既有能力迁移 → 可选生态插件 → 来源与版本管理”组织完整变更组。

发布前至少满足：修复两项索引回归并使架构测试 16/16 通过；验证未保存文档的新建/切换/退出取消；原生计时与插件联动；干净目录 EXE 插件/手册/配置持久化验证；再运行前端和插件闸门。合并代码不应顺带重写用户 Workspace 或清理版本数据。

## 6. 本次验证证据与边界

| 检查 | 结果 |
| --- | --- |
| `python tools/kb_smoke.py` | UTF-8 输出模式下通过，204 条目 / 1,843 关系；首次默认 GBK 输出被实验符号触发编码错误 |
| `python tools/web_check.py` | 通过，32 个装配资源，语法和接缝有效 |
| `python tools/web_manifest.py --check` | 通过 |
| `python tools/plugin_check.py` | 通过，含依赖方向及插件 API 隔离 |
| `python -m core.plugins verify` | 12 个插件可用，阻塞/拒绝/冲突均为 0 |
| `python -m mcp.server --selftest` | 通过，35 工具（内核 30 + 插件 5）、10 资源、2 prompts，problems 为空 |
| `python tools/test_bulk_delete.py` | 4/4 通过 |
| `python tools/test_index_architecture.py` | 14/16 通过，1 error + 1 failure，见上文 A/B |
| `python tools/ui_smoke.py --strict --json` | 现有 `127.0.0.1:8765` 服务 18 路由通过，无 console error、失败请求或首屏重型库加载 |
| Git 三方合并预演 | 7 个冲突路径；未执行实际合并 |

浏览器结果针对当时正在运行的本地服务，不能据此保证服务进程已经载入磁盘上全部最新后端代码。本次未做完整测试集、Windows 构建或桌面运行验收；打包结论来自资源路径和构建参数的静态检查。未修改应用代码及用户知识库。

## 7. 合并落地记录（2026-10-16，后续获用户授权）

用户确认以远端 UI 设计和性能优化为重点，在当前 `feature/slim-workbench-v261009` 合并 `upstream/feature/ui-redesign-v3`（`97932f3`）。以下记录取代前文“仅评估、未合并”的阶段状态。

### 最终取舍

- 远端 UI、深色主题和原生标题栏完整接入；CSS/JS 经 manifest 装配，保持远端主题覆盖顺序。异步对话框、未保存保护、不落盘草稿、保存期间继续输入保护覆盖当前编辑器和插件导航。
- 保留当前契约唯一声明处、十二插件及来源/版本归族。focus 原生后台计时接入插件，阅读和计费交互修复进入插件，不恢复旧内核页面。项目页改为 `ERWPanels` 自登记，使项目导航同样经过未保存保护。
- 保留已有 SQLite 快照读取、后台同步、局部图谱更新及重型库按需加载；接入远端请求队列、断连容错和启动超时重试，没有用旧实现覆盖当前性能架构。
- 修复评估中 A/B 两项索引问题；统一 Agent、插件和 MCP 写入入口，保留 origin；项目 ID 字段加入唯一契约。回归测试另外发现并修复 MCP 残留 `app.search` 导入、回收站缺少 `shutil` 导入和计费页初次并发建价格表的竞争。
- 打包暂存仅包含代码/资源，补齐插件、手册、PDF cmap/字体/构建资源和动态后端隐藏导入；排除个人数据、配置、缓存和测试预览。资源根与 `--data-dir` 数据根分离，源码态和打包态均有路径测试。

### 验证与运行边界

| 检查 | 合并后结果 |
| --- | --- |
| 架构回归 | `tools/test_index_architecture.py` 20/20，含草稿无副作用、即时索引、MCP 桥接、项目 ID 与回收站 |
| 桌面 / 计时 / 资源 / 批量删除 | 17/17、9/9、3/3、4/4 |
| 来源与版本 | `tests/kernel/test_versions.py` 以额外隔离 DATA_ROOT 与授权配置的包装运行，40/40；原测试自身授权配置路径未改 |
| 知识库、前端、清单、插件、MCP | `kb_smoke`、`web_check`、`web_manifest --check`、`plugin_check`、`core.plugins verify`、`mcp.server --selftest` 通过，12 插件可用 |
| 浏览器 | `tools/test_ui_v3_integration.py` 4/4 通过，使用 `.scratch/verify/` 临时数据运行真实服务，无截图；覆盖草稿、保存/放弃/取消导航、失败保存、请求期间输入、模拟原生标题栏/主题/退出、并发计费及 19 路由；重启后的 8765 服务另走查 19 路由通过，两者均无 console error、失败请求或首屏重型库加载 |

8765 后端已通过 `/api/system/restart` 重启并确认新草稿接口可用。已有 MCP 宿主连接需要重启/重连后加载新模块；自检使用的是新进程。测试写操作使用隔离工作区，没有批量重写或清理用户 Workspace。未推送远端、未生成 EXE，未重新测量万篇性能基准；浏览器原生桥接使用模拟 API，不代表真实 WebView/系统托盘/通知已验收。

## 8. 合并后相对远端的功能保留复核（2026-10-16）

再次通过 `git ls-remote` 确认远端分支仍为 `97932f3`，比较对象为本地合并提交 `eb0c733`。本轮为代码与接口差异复核，引用上节已有回归证据，没有重新做全部交互、原生桌面或性能验收。

- 未发现主要用户功能被整项删除。三份 V3 主样式（`v261014-linear-luxe.css`、`v261014-soft-chromatic.css`、`v261015-usability.css`）与远端一致；阅读笔记保存、图片插入、AI 自定义动作、截图、结果追加/替换在迁移后的插件中仍有实现。函数改名或旧文件删除不能直接算功能损失。
- **旧 API 兼容性确有损失**：远端 `/api/rss`、`/api/config/rss`、`/api/weather`、`/api/weather/geocode`、`/api/billing/{summary,records,prices}` 的显式处理已移除，替代入口分别在 `/api/plugins/rss/{feed,config}`、`/api/plugins/weather/{current,geocode,config}`、`/api/plugins/billing/{summary,records,prices}`。内置前端已适配，直接调用旧接口的外部脚本需要迁移。
- **功能可用性增加插件条件**：专注、天气、资讯、计费、图谱增强和阅读工作区现在依赖对应插件。随包清单均声明默认启用，合并验收中十二插件可用；停用或加载失败会使相应入口/增强不可用。RSS/天气旧配置与缓存、计费旧账本/单价表有兼容认领实现，但不能由此宣称所有升级环境都已实测。
- **发现一处窄屏样式回归**：`web/styles.css:264` 的媒体查询将远端 `.agent-compose-actions` 写成 `agent-compose-actions`，使宽度不超过 820px 时该规则无法匹配 class。影响的是 Agent 操作栏 `align-items:flex-end` 规则，不能据此推断发送或其他业务功能失效。本轮只记录，未修改应用代码。
- 远端当前版本同样已将旧研究总览书签重定向到概览，里程碑也只暴露时间轴/列表/文档；不能把旧 3D/鱼骨入口计为本次相对远端的损失。
- 原生 WebView/托盘/通知、独立 EXE 及合并后万篇性能仍属未验收项目，不能把保留代码等同于运行保证，也没有证据将它们判为已经丢失。

## 9. 相对 V3 的新增功能与合并内容总表（2026-10-19 复核）

本轮按代码事实重新核对 `97932f3..2245726`（104 个提交、442 个文件，其中 187 个为 `web/vendor/pdfjs` 资源），把前文分散在各节的结论整理成"我们新增了什么"与"从 V3 合进来了什么"两张表。复核方式为 `git diff` / `git cat-file` 逐项确认，未重新跑回归。

### 9.1 基线关系

| 项 | 值 |
| --- | --- |
| 当前 HEAD | `2245726`（`feature/slim-workbench-v261009`，v261016.9） |
| V3 分支 | `feature/ui-redesign-v3` = `97932f3`，**是 HEAD 的祖先**（HEAD 已完整包含它） |
| 共同祖先 | `320c8f0`；V3 独有 1 个提交（35 文件 +3012/−300） |
| 我方独有 | 104 个提交、255 个文件（不含 vendor）+34107/−1734 |
| 结论 | 不是"待合并"状态，而是**已合并完成**；V3 之后没有再前进 |

### 9.2 我们相对 V3 新增的功能（V3 没有）

| 能力 | 落点 | 说明 |
| --- | --- | --- |
| 内核契约单源化 | `core/contracts/{kinds,naming,validate}.py` | 七类条目（实验独立成类）、标记表、字段契约、关系矩阵、命名校验集中一处；写入期硬校验 |
| 插件平台 | `core/plugins/*`、`core_api.py`、`plugins/.template/`、`tools/new_plugin.py` | 清单契约、只读发现、依赖解析、`ctx` 执行层、后台任务、ZIP 单文件包解包、脚手架 |
| 12 个插件 | `plugins/`（58 个新文件） | 随包 8 个默认启用（billing/floating-assist/focus/knowledge-graph/literature-reader/rss/weather/version-manager），可选 4 个（backup-snapshot/metrics-table/milestone-calendar/report-export） |
| 既有功能插件化 | 删 `web/literature.js`、`web/v260930-floating-agent.js`、`web/v261008-billing.js`、`web/v260922-projects.js`、`app/rss.py`、`app/weather.py`、`app/kb_naming.py` | 四者均为**迁移**而非删除，替代实现分别在 literature-reader / floating-assist / billing 插件、`ERWPanels` 项目页与 `core/contracts/naming.py` |
| 前端装配与接缝 | `web/manifest.json`、`web/plugin-host.js`、`web/plugin-manager.js`、`web/dom-seam.js`、`web/vendor-lazy.js`、`web/research-pages.js`、`web/manual.js` | `index.html` 由清单生成；`ERWPanels` 自登记；`erwFetch`/`ERWDom`/`ERWToast` 显式接缝；重型库按需加载 |
| 来源与版本追踪 | `app/versions.py` + `plugins/version-manager` | 四条来源（ui/agent/mcp/plugin）、版本族、逐节对照与合并、整版采用、归档取回、自动快照节流；版本条目不进列表与索引 |
| 外部接入授权 | `app/external_access.py`、`web/external-access.js` | MCP 写知识库默认拒绝，插件写默认开启，设置页可改 |
| 外部改动巡检 | `app/external_edits.py` | 用 mtime 与事件时间差识别绕过收口点的直写，可记为活动事件 |
| MCP 服务 | `mcp/`（10 个新文件） | 30 个内核工具 + 插件工具按启用状态暴露，10 资源、2 prompts |
| 诊断与验证设施 | `core/doctor.py`、`core/index/{migrate,maintain}.py`、`tools/{web_check,web_manifest,ui_smoke,plugin_check,kb_smoke,run_tests,doc_check}.py`、`tests/`（43 个新文件）、`.github/workflows` CI | 只读体检、索引迁移框架、静态闸门、真浏览器路由走查、42 个常驻测试（27 个需浏览器） |
| 内置使用手册 | `docs/manual/`、`web/manual.js`、`/api/manual` | 带截图分章教程，工作台内可读 |
| 桌面运行时增强 | `app/windows_runtime.py`、`app/windows_tray.py` | 在 V3 的 `windows_frame.py` 之上补运行时与托盘层 |

### 9.3 从 V3 合进来的内容（合并后存活状态）

V3 的 35 个文件，HEAD 中**全部存在**，其中 15 个与 V3 逐字节一致、16 个有改动、4 个被迁移删除：

| 类别 | 文件 | 状态 |
| --- | --- | --- |
| 桌面层 | `app/windows_frame.py`、`app/desktop_notification.py`、`app/desktop_smoke.py`、`app/focus_timer.py`、`web/desktop.css`、`web/theme-dark.css`、`web/ui-dialogs.js`、`build_client.bat`、`run_client.bat`、`requirements.txt`、`tools/test_focus_timer.py`、`tools/ui_usability_check.js` | **原样保留** |
| 三份主样式 | `web/v261014-linear-luxe.css`、`web/v261015-usability.css`、`web/workbench-ui.css` | **原样保留** |
| 需适配 | `app/desktop.py`、`app/store.py`、`client.py`、`server.py`、`web/app.js`、`web/desktop.js`、`web/index.html`、`docs/WINDOWS.md`、`tools/build_windows.py`、`tools/test_desktop.py`、`requirements-desktop.txt` | 已改（接入插件/契约/装配清单） |
| 迁移删除 | `web/literature.js`→literature-reader、`web/v260930-floating-agent.js`→floating-assist、`web/v261008-billing.js`→billing、`web/v260922-projects.js`→`ERWPanels` 项目页 | 功能等价迁移 |

关键交互已确认落地：`/api/docs/draft`（`server.py:301` + `web/app.js:1147`）、统一未保存保护 `guardEditor`（`web/app.js:277` 定义，11 处导航/刷新/退出路径调用）、原生后台计时桥接（`desktop_focus_{state,start,pause,reset}` ↔ `plugins/focus/web/panel.js`，含 `pywebviewready` 与 `workbench:window-state` 事件）。

### 9.4 差异点清单（相对 V3 的真实行为变化）

| 项 | V3 | 当前 HEAD | 影响 |
| --- | --- | --- | --- |
| 计费接口 | `/api/billing/{summary,records,prices}` | `/api/plugins/billing/{...}` | 外部脚本需迁移 |
| 资讯/天气接口 | `/api/rss`、`/api/config/rss`、`/api/weather`、`/api/weather/geocode` | `/api/plugins/rss/*`、`/api/plugins/weather/*` | 外部脚本需迁移 |
| 新增接口 | — | `/api/plugins`、`/api/plugin-manager/*`、`/api/manual`、`/api/external-access` | 新增能力 |
| 功能可用性 | 内置 | 依赖对应插件启用 | 停用插件则入口消失 |
| 条目类型 | 六类 | 七类（实验独立） | 旧实验数据迁移需 dry-run |
| 前端装配 | 手写 `index.html` 引用 | `web/manifest.json` 生成 | 加模块必须改清单 |
| 已知回归 | — | `web/styles.css:264` 窄屏 `.agent-compose-actions` 选择器缺前导点（未修） | 仅影响 ≤820px 时 Agent 操作栏对齐 |

### 9.5 未验收边界

原生 WebView/托盘/通知的真实运行、干净目录 EXE、合并后万篇性能基准仍未验收；上述"原样保留"只代表代码一致，不等于运行保证。
