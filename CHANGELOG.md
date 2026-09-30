# Changelog

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
