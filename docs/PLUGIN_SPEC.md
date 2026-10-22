# 工程科研工作台 · 插件规范（打包 / 安装 / 依赖）

> 配套：[docs/SCOPE.md](SCOPE.md)（定位与功能分层）、[docs/REFACTOR_PLAN.md](REFACTOR_PLAN.md)（§6 插件化方案）。
> 一句话目标：**把插件放进统一插件库就能用；不能用的必须明确告诉你为什么，且绝不影响核心。**

---

## 0. 三条设计原则

| # | 原则 | 含义 |
| --- | --- | --- |
| P1 | **丢进去就能用** | 用户只需把「目录」或「单文件包」放进 `plugins/`；发现、校验、注册全自动，**不改代码、不重编译** |
| P2 | **打包隔离** | 每个插件自包含（manifest + 后端 + 前端 + 迁移 + 依赖声明），不共享可变文件；共享物只能走 `core_api` 或**前提插件** |
| P3 | **失败只伤自己** | manifest 不合法 / API 版本不兼容 / 依赖缺失 / 运行时抛错 → **只拒载或停用该插件**，核心与其它插件照常运行 |

---

## 1. 统一插件库：两个来源，一个入口

| 来源 | 目录 | 谁能写 | 用途 |
| --- | --- | --- | --- |
| **用户库**（统一入口） | `DATA_ROOT/plugins/` | 用户 | 自己装/删的插件；**你说的"统一插件库"就是这里** |
| **随包库**（bundled） | `ASSET_ROOT/plugins/` | 只能由发行版更新 | 官方附属插件（天气 / RSS / 专注计时 / 图谱 …），只读 |

- 同名 `id` 同时存在时 **ASSET 优先**（防止用户误改随包插件导致升级不一致），并在诊断里报提示。
- 开发态 `DATA_ROOT` = 仓库根 → 开发时就是仓库里的 `plugins/`（已被 `.gitignore` 放行、可入库）。
- 打包态 `DATA_ROOT` = exe 同级 → 与便携数据同处一地，符合现有便携约定（`app/paths.py:16-23`）。

**安装状态**记在 `System/plugins.json`（不放在插件目录里，避免插件写坏自己的清单）：

```json
{"schema_version": 1, "plugins": {
  "weather":  {"version": "1.0.0", "source": "bundled", "enabled": true,  "installed_at": "2026-10-09T18:00:00", "hash": "sha256:…"},
  "rag":      {"version": "0.9.3", "source": "user",    "enabled": false, "installed_at": "2026-10-10T09:00:00", "hash": "sha256:…"}
}}
```

> 目录决定「在不在」，`System/plugins.json` 决定「开不开」。

---

## 2. 插件包格式：目录态 与 单文件包态

| 形态 | 样子 | 生效方式 |
| --- | --- | --- |
| **目录态**（开发/源码） | `plugins/<id>/`（含 `plugin.json`） | 直接扫描加载 |
| **单文件包态**（分发） | `plugins/<id>-<version>.zip`（内含 `plugin.json` 在根） | **自动解包到 `plugins/<id>/`**：每个功能模块**一个独立文件夹、互不混用**（✅ 已实现，见 §12 与 §2「解包规则」；实现 `core/plugins/unpack.py`） |

`plugins/<id>/` 的标准结构：

```text
plugins/weather/
├─ plugin.json          # 唯一必需文件
├─ backend.py           # 可选：register(ctx) 入口
├─ web/
│  ├─ panel.js          # 可选：export mount(ctx) / unmount()
│  └─ panel.css         # 可选：必须以 [data-plugin="weather"] 作用域（内核给挂载容器打这个属性）
├─ migrations/          # 可选：自有数据迁移（NNNN_*.py）
└─ README.md
```

**解包规则（核心要求：每插件一个独立文件夹，绝不混用）**：

> ✅ **状态：已实现**（v261009.21，实现 `core/plugins/unpack.py`；夹具 `.scratch/tmp/verify_zip_unpack.py` 53 项、`.scratch/tmp/verify_zip_install_http.py` 27 项）。
> **三个安装时机**：服务启动（`loader.load`）→ 打开设置页插件页（`build_plugin_payload(detail=True)`，结果以结构化 `install` 字段显示在页面上）→ CLI `python -m core.plugins list --install`。
> **发现永远只读**：`registry.discover` / `report` 不写盘，所以 `tools/plugin_check.py` 与每个插件请求路径都不会顺带装东西；安装必须显式调 `registry.install_packages()`。
> **额外安全上限**（规范之外的兜底）：包内条目 ≤ 20000、解压后 ≤ 512 MB、解压比 ≤ 200:1（小包不查比值）。

1. **先临时后原子**：解到 `plugins/.unpack-<id>-<version>/`，全部校验通过后**原子改名**为 `plugins/<id>/` → 任何时候都不存在"半解包"状态。
2. **一包一插件**：包内只能是一个插件的完整内容（清单在根）；一个包里塞两个插件、或把文件直接铺到 `plugins/` 根 → **拒载**。
3. **目录名 = manifest id**：解包目录必须是 `plugins/<id>/`，与 `plugin.json` 的 `id` 一致；不一致 → 拒载（避免"文件夹叫 A、插件自称 B"的混乱）。
4. **版本替换不合并**：`plugins/<id>/` 已存在且版本不同 → 旧目录**整体**移入 `System/Trash/plugins/<id>-<旧版本>/`，再放入新版；**禁止逐文件覆盖合并**。
5. **不覆盖用户手改目录**：若 `plugins/<id>/` 是你自己放的目录态插件（非由 zip 解出），同名 zip 只提示冲突，不自动覆盖。
   判定依据是目录里的标记文件 **`.erw-unpacked`**（记录 id / version / 来源包 / 解包时间）：**删掉它即视为手放目录**，从此不会被任何同名包升级；反过来，若删包后想彻底回到"未安装"，把 `plugins/<id>/` 整个删掉即可（包文件不会被本模块删除）。
6. **路径安全**：解包落点必须严格在 `plugins/<id>/` 内——拒绝绝对路径、`..` 穿越、符号链接逃逸。

---

## 3. manifest（`plugin.json`）完整字段

```json
{
  "id": "weather",
  "name": "天气",
  "version": "1.0.0",
  "description": "当前位置的实况天气卡片",

  "api_version": 1,
  "core_min": "v261010",

  "kind": "inprocess",
  "distribution": "bundled",
  "default_enabled": true,

  "entry": "backend.py",

  "permissions": ["net:http", "storage:own", "config:own"],

  "requires": {
    "plugins": [{"id": "literature-base", "version": ">=1.0,<2"}],
    "python": ">=3.10"
  },
  "provides": ["weather"],

  "nav": [{"id": "weather", "label": "天气", "mount": "web/panel.js"}],
  "routes": [{"method": "GET", "path": "forecast"}],
  "mcp_tools": ["weather_now"],
  "settings_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
  "jobs": [{"id": "refresh", "interval_min": 30}],
  "events": ["doc.updated"],
  "storage": {"derived_db": "System/Cache/weather.sqlite"}
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | ✅ | 小写字母/数字/短横线；决定命名空间（路由、工具、存储、CSS 作用域） |
| `version` | ✅ | 语义化版本，用于依赖解析与升级判定 |
| `api_version` | ✅ | 插件所依赖的**内核 API 版本**；不匹配直接拒载（I7） |
| `core_min` | — | 最低内核版本提示（不满足时给出明确信息） |
| `kind` | ✅ | `inprocess`（默认）或 `process`（独立进程，见 §6） |
| `distribution` / `default_enabled` | — | 合起来就是「附属（bundled+true）」与「可选插件（optional+false）」的唯一区别 |
| `entry` | `process`/有后端时 ✅ | 后端入口文件 |
| `permissions` | — | 权限清单（§7），安装/启用时展示给用户 |
| `requires` / `provides` | — | 依赖与供给（§4） |
| `nav` / `routes` / `mcp_tools` / `settings_schema` / `jobs` / `events` | — | 扩展点声明（注册方式与命名空间见 REFACTOR_PLAN §6.3）。`jobs` 是**声明式清单**（`[{"id":"auto","interval_min":1440}]`，给人看/给设置页显示），真正生效的是 `register(ctx)` 里的 `ctx.jobs.add(...)`；两者不一致只在加载时提示，不拒载 |
| `nav[].slot` | — | **槽位面板**：声明 `slot` 后该面板**不进导航**，而是画进内核提供的槽位容器（容器带 `data-plugin="<id>"`，样式按 §2 作用域）；入口脚本用 `ERWPanels.register({id, slot, renderSlot(container)})` 自登记。**当前两个槽位**：`topbar`（顶栏一行）与 `overlay`（页面浮层，悬浮球这类"始终挂在页面上"的 UI 用它；**不要**直接往 `document.body` 塞 DOM）。已知槽位在 `core/plugins/manifest.KNOWN_SLOTS` 声明，未知槽位会被拒载（`P019`） |
| `storage` | — | 自有派生数据路径，**只允许** `System/Cache/<id>.sqlite` 这一类 |
| `preview` | — | **演示预览**（v261009.27）：`{summary, features[], where, screens[]}`。设置页悬停/点击插件卡片时显示，让用户不看文档就知道这个插件干什么。**由插件自己声明**——内核只负责呈现，不认识任何具体插件；没声明这一行就不出现（形状不对只给 `P022` 警告，不拒载）。`screens` 是插件目录内的相对路径（约定放 `plugins/<id>/web/preview.png`），内核会带缓存键下发，图片改了浏览器必然重新取 |

**演示预览怎么写**（可选，但强烈建议随插件一起给）：

```json
"preview": {
  "summary": "一句话：这个插件解决什么问题（不超过 ~40 字最好读）",
  "features": ["功能点 1（能做什么，而不是内部怎么实现）", "功能点 2"],
  "where": "在哪里能找到它，如「侧栏 → 指标表」或「顶栏角标」",
  "screens": ["web/preview.png"]
}
```

- 截图**建议用元素级截图**（只截插件自己的界面区域）：1x、宽 ≤760px、高 ≤700px，PNG；
  放在 `plugins/<id>/web/preview.png`（`.gitignore` 已为 `plugins/**/web/preview*.png` 放行）；
- 截图是**给它自己看的证明**：设置页里点开就能确认这个插件长什么样，而不是只读一行描述；
- 没截图也能写 `preview`（只显示摘要与功能点），此时面板会注明"插件没提供截图"。


---

## 4. 依赖与「前提插件」

### 4.1 两类依赖

| 类型 | 声明 | 说明 |
| --- | --- | --- |
| **前提插件**（prerequisite） | `requires.plugins[]` | 被依赖方必须已安装且启用；它就是普通插件，只是**默认开**。例：`literature-base`（文献条目/PDF 能力）被"阅读区 AI 助手""术语流水线"共同依赖 |
| 内核 API | `api_version` / `core_min` | 与内核的契约版本；不匹配 → 拒载 |

### 4.2 加载规则（确定性）

1. **拓扑排序**：按 `requires.plugins` 做 DAG 排序后再注册；检测到环 → **整环拒载**并报错（不做"部分加载"）。
2. **版本消解**：同一 `id` 在库中**只允许存在一个版本**；出现多版本（目录 + 单文件包、或两个包）→ 不猜、直接报冲突并列出候选，由用户删掉多余的那个。
3. **缺失依赖**：某插件依赖的 `id` 未安装/未启用 → 该插件状态记为 `blocked`，在设置页显示「缺少前提插件：literature-base ≥1.0」，**核心与其它插件不受影响**。
4. **级联停用**：前提插件被禁用/卸载 → 依赖它的插件**自动一起停用**（不崩溃、不清数据），恢复前提插件后可一键恢复启用。
5. **顺序无关**（I9）：每个插件在独立 `try` 中注册；任何插件的注册失败都不阻断其它插件与核心。

### 4.3 前提插件的边界（重要）

前提插件**不得成为事实上的核心**：
- 它自己必须能在「核心 + 它」的最小组合下独立工作；
- 核心绝不允许依赖任何前提插件（I1：核心 + 零插件必须完整可跑）；
- 前提插件被禁用时，核心功能不得退化（依赖它的插件一起停用即可）。

---

## 5. 安装 / 启用 / 禁用 / 更新 / 卸载

| 动作 | 用户做什么 | 内核做什么 | 生效时机 |
| --- | --- | --- | --- |
| **安装** | 把目录或 `<id>-<version>.zip` 丢进 `plugins/` | 扫描 → 校验 manifest → 检查 `api_version`/依赖/冲突 → 记入 `System/plugins.json`（默认**不启用**，除非 `default_enabled: true`）。**单文件包**按 §2 解包规则自动解到 `plugins/<id>/`（服务启动、打开设置页插件页、CLI `--install` 三处触发；`tools/plugin_check.py` 之类的只读审计**不会**触发） | 后端需**重启**注册路由/工具；前端刷新即可见面板 |
| **启用** | 设置页点「启用」（或 CLI） | 校验 → 拓扑排序注册 → 写 `enabled: true` | 同上 |
| **禁用** | 点「禁用」 | 注销路由/面板/工具 → 级联停用其依赖者 → **保留数据** → 写 `enabled: false` | 同上 |
| **更新** | 用新版本替换目录/包 | 版本比对 → 跑 `migrations/` → 更新记录与哈希；`api_version` 不兼容则**拒绝并保留旧版** | 同上 |
| **卸载** | 点「卸载」 | 插件移入 `System/Trash/plugins/<id>/`；**数据默认保留**并提示（`Workspace/Plugins/<id>/`、`System/Plugins/<id>/` 是否一并删除由用户勾选） | 同上 |

**CLI（与设置页同一套逻辑，便于排障）**：

```powershell
python -m core.plugins list            # 已发现 / 已启用 / blocked / 冲突
python -m core.plugins list --install  # 同上，但先把 plugins/ 下的单文件包解包（§2）
python -m core.plugins check <id>      # manifest 校验 + 依赖与权限报告（不落盘）
python -m core.plugins enable <id>     # 启用（含级联检查）
python -m core.plugins disable <id>    # 禁用（含级联停用预览）
python -m core.plugins verify          # 全库体检：孤儿派生库、缺失依赖、版本冲突
```

> 与现有约定一致：**后端改动必须重启**（AGENTS.md §二.4）；前端面板刷新即生效。

---

## 6. 隔离：三层，按插件类型选

| 层 | 做法 | 适用 |
| --- | --- | --- |
| **命名空间隔离**（所有插件） | 路由 `/api/plugins/<id>/…`、工具 `p_<id>__<tool>`、存储 `Workspace/Plugins/<id>/`、`System/Plugins/<id>/`、`System/Cache/<id>.sqlite`、配置 `config/plugins/<id>.json`、CSS `[data-plugin="<id>"]` | 全部 |
| **代码隔离**（`inprocess`） | 只允许 `from core_api import …`；禁止碰 `core.*` 私有模块；hook 全部 `try/except + 超时`，连续失败自动停用 | 轻量插件（天气、RSS、计时、面板类） |
| **进程隔离**（`process`） | 插件自带解释器环境与依赖，通过本机 HTTP 与内核通信（`process: {port, python_env, health, model_dir}`）；内核缺包/服务未起时**降级**而非报错 | 重型插件（RAG、模型类） |

**「打包隔离」的落地含义**（对应你的要求）：每个插件的**代码、前端、迁移、依赖声明、数据命名空间**都自包含，安装/启停/卸载互不写对方文件；插件之间**只能**通过 ① `core_api` ② 前提插件的公开接口 交互，**不允许** import 彼此的私有模块。

**`core_api` 的公开面**（每加一项都是有意动作，语义写在这里）：

| 成员 | 语义 |
| --- | --- |
| `API_VERSION` | 内核 API 版本，与 `core.plugins.manifest.SUPPORTED_API_VERSION` 同源 |
| `plugin_dir(id)` | 插件自己的目录（只读代码 + 资源） |
| `system_dir(id)` / `workspace_dir(id)` / `cache_db(id)` | 插件的三个数据落点：`System/Plugins/<id>/`、`Workspace/Plugins/<id>/`、`System/Cache/<id>.sqlite` |
| `config_path(id)` / `read_config(id, default)` / `write_config(id, data)` | 插件自有配置 `config/plugins/<id>.json`（内核不解释其内容；写入是原子的） |
| `http_get(url, timeout, headers, limit)` | **出网的推荐方式**：取字节。带代理兜底——系统代理若是**回环地址且端口没人监听**（Clash/V2Ray 没启动），本次请求自动改直连，避免所有出网请求都撞 `WinError 10061`；远程代理不受影响，超时 / DNS 失败 / 非 2xx 照原样抛 |
| `data_root()` | 可写数据根。**只正当用于一次性迁移**（把内核时代写在别处、如 `System/Cache/*` 的数据认领进自己的命名空间）；日常请用上面的命名空间内助手 |
| `log(id, message)` | 带插件前缀的日志 |

### 6.1 前端接缝与公开数据 API（插件 UI 的接触面）

插件的前端脚本（`nav[].mount` / `panel.mount`）跑在内核页面里，但**不得改内核 DOM**（P14 红线）。需要的能力一律走下面这些接缝：

| 接缝 | 用途 |
| --- | --- |
| `window.ERWPanels.register({...})` | 侧栏导航页 / 顶栏槽位 / 设置页 tab / 阅读区 tab（见 §3 的 `nav[]`、`panel` 字段） |
| `window.ERWContract` | 七类 kind、类别词、`kind_marks`、关系的**只读**中文契约（`kinds/kindLabels/kindLabel/entityLabel/marks/relations/relationLabel`）。插件不要再各抄一份标签表 |
| `window.ERWMarkdown.renderInto(el, raw)` / `.normalizePaths(html)` | Markdown 渲染（marked + DOMPurify + hljs + mermaid/mathjax 按需）与 `/workspace-file/` 图片路径归一 |
| `window.ERWGraphRenderers.register({id, graph?: {mount(host, ctx)}, overview?: {enhance(canvas, ctx)}})` | **图谱渲染接管**（v261009.18 起是**页面级**）：内核渲染图谱页时把 `#main` 交给 `graph.mount(host, ctx)`（**页面 markup 也由插件产出**），总览迷你图走 `overview.enhance(canvas, ctx)`；内核**不再自带任何图谱渲染器**——接管者缺席或抛错时只显示「知识图谱不可用：请启用插件」提示（旧的简易兜底图已按用户要求删除） |
| `window.ERWReader.register({id, open(paperId?), openByAttachment(att), context?()})` | **阅读区接管**：内核在文献列表页点「PDF 阅读工作区」或点附件徽章时调它。无接管者时内核**不显示该入口**，并在用户试图打开时给明确提示（"阅读区不可用：请启用…"），文献列表/元数据条目页照常可用。首个使用者是 [`plugins/literature-reader`](REFACTOR_PLAN.md) |
| `window.ERWReaderAssist.register({id, tabId, run(action,payload), attach?, fromNote?, useImage?})` | **阅读区助手**（**插件提供、插件消费**的接缝，v261009.15）：阅读区把「选中动作 / 框选截图 / 笔记 AI 整理」派发给助手插件，派发前切到它声明的 `tabId`；助手在 `attach(ctx)` 里拿到实时上下文 `{paper, refreshList, selection(), capture{page(),area()}, activate(), aiPolish()}`。阅读区因此**不认识任何具体助手**，助手停用 → AI tab 与工具条按钮一起消失。首个使用者是 [`plugins/reader-assist`](REFACTOR_PLAN.md) |
| **`ctx.raw(body, content_type=…, filename=…)`**（后端接缝，v261009.23） | **插件产出文件的原样响应**：handler 返回它就**不做 JSON 包装**，内核直接把字节与响应头写回浏览器（`Content-Disposition` 对中文名用 RFC 5987 编码）。下载导出件、生成图表、回 CSV 都用它。首个使用者是 [`plugins/report-export`](../plugins/report-export/README.md) |
| **槽位面板**（manifest `nav[].slot` + `ERWPanels.register({slot, renderSlot})`） | 内核给挂载点并给容器加 `data-plugin="<id>"`，插件**只在容器内**画东西。已知槽位由 `core/plugins/manifest.KNOWN_SLOTS` 声明（新增槽位是有意的动作），当前两个：`topbar`（顶栏一行，`#topbar-slot`）与 **`overlay`**（页面浮层 `#erw-overlay-host`——悬浮球这类「始终挂在页面上」的 UI 用它；**不要**直接往 `document.body` 塞 DOM） |
| **挂载点标记 `data-plugin="<id>"`**（v261009.22） | 内核在插件自登记的容器上写这个属性，**值是「面板 id」**：主面板（`id` = 插件 id）→ 导航页 `#main`；设置页 tab 用 `settingsTab.id`（模板里就是插件 id）；**槽位容器用槽位面板自己的 id**（所以一个插件登记了两个面板时，CSS 要么按各自的 id 分别写，要么用前缀匹配如 `[data-plugin^="my-plugin"]`）。每次导航/切 tab 先清掉上一轮的值，插件样式不会泄漏到内核页面 |
| `window.erwFetch(url, init)` | 出网与访问内核 HTTP API（**不得**替换 `window.fetch`） |
| `window.erwVendor.load('mathjax'\|'mermaid')` | 重型库按需加载（本地优先、CDN 兜底） |
| `window.ERWDom.onChildList(cb, {root})` | 文档级 DOM 变更观察的唯一入口（内核合并成一个 observer） |
| `workbench:*` / `erw-*` 自定义事件 | 内核广播（如 `llm.usage`）与模块间解耦通信 |
| `window.ERWToast(msg, error?)` / `window.ERWMarkBadges/ERWMarkList/ERWMarkChips/ERWTagPicker` / `ERWVisionEnabled` / `ERWAssistCustomActions` | 提示条与「标记 / 标签 / 多模态开关 / 自定义 AI 动作」这类内核 UI 小件（由内核模块提供；插件**不要**自己再造一套，也别依赖它们一定存在——调用处做空值保护） |

**内核消费的插件提供接缝**（v261009.16 起，全部经 `?.`／`typeof` 守卫）：

| 接缝 | 提供方 | 内核消费点 | 插件缺席时 |
| --- | --- | --- | --- |
| `window.ERWFabTimeline` | `plugins/floating-assist` | `app.js` 的 Agent 消息气泡（工具轨迹块） | 该块**静默不渲染**，消息照常显示 |
| `window.ERWLiterature` / `window.ERWCapture` | `plugins/literature-reader` | 悬浮球上下文/截图桥、阅读区助手 | 阅读相关动作不可用，其余照常 |
| `window.ERWReaderAssist` | `plugins/literature-reader` | 同插件内的 AI 面板（v261009.17 合并后为例：**同一插件内部**提供与消费，仍对外暴露，将来可再拆） | AI 面板不注册并在控制台说明 |

> **不要把这类可选 UI 块搬回内核**。「零插件可跑」（I1）的含义是*工作台与核心流程可用*，
> 不是*每个可选 UI 块都必须在场*；守卫 + 明确退化即可。把某一附属的渲染代码塞回内核，
> 等于把附属重新变成核心（与 §5/A15 的方向相反），并且会让内核重新依赖具体功能。
> 判定标准：**内核是否在无该插件时报错/白屏**——不是「某块 UI 是否消失」。

### 6.2 插件能力矩阵：什么不用改内核，什么必须改内核

> 这份表是**根因导向**的：回答「加一个新插件，要不要动内核」。结论分三类：
> **① 完全不用改内核**（绝大多数功能）；**② 要一次性加一种"形态"**（加完这一类的插件都不用再改）；
> **③ 要内核先把某个能力实现出来**（当前明确的缺口只有三件）。

**① 不改内核就能做到（现有接缝已覆盖）**

| 需求 | 用什么 |
| --- | --- |
| 加一个侧栏页面 / 顶栏组件 / 设置页 tab / 阅读区 tab | `ERWPanels.register` + manifest `nav[]`/`panel`（4 类自登记点） |
| 让「始终挂在页面上」的 UI 进页面 | 浮层槽位 `overlay`（内核给 `#erw-overlay-host`），或 `topbar` |
| 自己提供 HTTP 接口 | `ctx.routes.get/post/...` → 自动挂到 `/api/plugins/<id>/…` |
| 产出文件并让用户下载（导出件、图表、CSV） | `ctx.raw(bytes, content_type=…, filename=…)`（v261009.23 起；不做 JSON 包装，中文文件名按 RFC 5987 编码） |
| 读知识条目 / 项目 / 总览统计 | `core_api.entries/entry/projects/project_names/todos/dashboard/kind_labels/kernel_version`（只读窗口，与 `/api/docs` 等**同一套查询实现**；v261009.23 起） |
| 写条目正文或字段（结构化内容） | `core_api.entry_update(doc_id, body=…)` + 把它注册成**写工具**（`spec.write = true`）→ 内核草稿闸门；v261009.25 起 |
| 给内置 Agent 加工具 | `ctx.mcp.tool(name, spec, handler)` → 对外 `p_<id>__<name>`；**写工具自动走内核草稿闸门** |
| 存自己的数据 / 配置 | `ctx.storage`（`Workspace/Plugins/<id>`、`System/Plugins/<id>`、`System/Cache/<id>.sqlite`）、`ctx.config` |
| 订阅内核事件 | `ctx.events.on("llm.usage"\|…)` |
| 后台任务（定时备份、周期检查） | `ctx.jobs.add(name, cb, every_minutes=…)`（v261009.24 起，内核调度/状态/日志；插件**不要**自己起线程） |
| 读内核数据 | 公开数据 API（`/api/docs`、`/api/literature`、`/api/graph`、`/api/search`、`/api/dashboard`…） |
| 用内核的 UI 小件 | `ERWContract`（kind/标记/关系）、`ERWMarkdown`（渲染+图片路径）、`ERWToast`、`ERWMarkBadges/ERWMarkList/ERWMarkChips/ERWTagPicker` |
| 网络 / 重型库 | `core_api.http_get`（带代理兜底）、`window.erwFetch`、`window.erwVendor.load('mathjax'\|'mermaid')` |
| 依赖别的插件 | `requires.plugins`（拓扑排序 + 缺依赖则 blocked 并给原因） |
| 自登记前端接缝（**插件提供、别的模块消费**） | 挂 `window.ERW*`；`web_check`/`ui_smoke` 把 `plugins/*/web/*.js` 计入提供方 |

**② 需要一次性加"形态"**（加完同类插件不再需要改内核；本轮实际加过 5 个）

| 形态 | 内核侧一次性成本 | 之后谁受益 |
| --- | --- | --- |
| 让插件**接管某个内核页面**（图谱页、阅读区） | 一个注册表 + 一处委托调用（`ERWGraphRenderers.mount`、`ERWReader`） | 同页面的替代实现（换渲染器/换阅读器） |
| 让插件**接管页面的一部分**（总览迷你图、阅读区 tab） | 一个 `enhance(canvas, ctx)` / `readerTab` 钩子 | 所有在既有容器里加 UI 的插件 |
| 让插件**提供页面级 UI 容器** | 一个新的 slot（如 `overlay`）+ 挂载点 | 所有"常驻页面"型 UI 插件 |
| 让插件**之间**通信（助手↔宿主） | 一个契约（如 `ERWReaderAssist`：`tabId` + `attach(ctx)`） | 同类"宿主—扩展"组合 |

**③ 内核必须先实现的能力（当前缺口，只有两件）**

| 缺口 | 影响什么插件 | 状态 |
| --- | --- | --- |
| `ctx.search.addSection` | 往全局搜索框注入「语义结果」分区（RAG 的落点） | **未实现**（`core/plugins/context.py` 明确标注） |
| `process` 类插件的执行层 | 独立进程/独立解释器的重型插件（模型、向量服务） | manifest 能声明 `kind:"process"`，但 loader 只跑 `inprocess` 的 `register(ctx)` |
| ~~`ctx.jobs`~~ | 后台任务：定时备份、周期性检查、长时索引 | ✅ **已实现**（v261009.24，`core/plugins/jobs.py`）：`ctx.jobs.add(name, cb, every_minutes=…)`，内核负责调度/状态/日志；插件**不要**自己起线程。首个使用者 `plugins/backup-snapshot` |

> **判断口径**：如果新插件只需要上面①里的能力 → 直接写插件、零内核改动；
> 如果它要一种**全新的形态**（新容器/新接管点）→ 内核加一个接缝（一次性，几十行）；
> 如果它要的能力落在③里 → 必须先把内核能力补齐，插件才能落地。

**RAG 的可行性结论（2026-10-10 梳理）**：RAG 属于③而不是①——

- **必须**：`ctx.search.addSection`（否则语义结果没有展示位）+ `process` 隔离（向量索引与 embedding 属重依赖，放 inprocess 会把内核进程拖住）；
- **可选**：~~`ctx.jobs`~~（v261009.24 已实现，做索引进度条现在可以直接用）；
- **数据**：本地 `.rag/` 92 MB + `rag.sqlite` 69 MB **按用户决定保留原位复用**；重建向量需要重新调用 embedding（耗时且消耗配额）；
- **轻量替代**（若不想先补内核）：纯前端插件在**自己的页面**里做语义检索（不经搜索框），只需内核已有的公开数据 API + 插件自己的 sqlite——代价是没有搜索框分区、也没有后台任务。

**公开数据 API**（只读，插件可直接消费）：`/api/docs`、`/api/docs/<id>`、`/api/statuses`、`/api/projects`、`/api/dashboard`、`/api/graph`、`/api/graph/overview`、`/api/graph/neighborhood`、`/api/search`、`/api/todos`、`/api/literature`（含 `/pdf` 的 **Range 分片**、`/annotations`、`/note`、`/storage`、`/lookup`、`/import`、`/rebuild`、`export-bibtex`）。写路径一律走内核草稿闸门，插件**不得**直写 `Workspace/`。

**后端侧等价的只读窗口**（v261009.23 起，`core_api`）：前端用 HTTP API，插件**后端**用这些同名助手——
`entry(doc_id)`（含正文）、`entries(kind, project=…, limit=…)`、`projects()`、`project_names()`、`todos()`、
`dashboard()`、`kind_labels()`、`kind_order()`、`kernel_version()`。它们与 HTTP 端点**同一套查询实现**
（实测同源同量），插件因此不必自己读 `Workspace/Knowledge/*.md`（绕过索引会看到过期或半写状态）。

**外部 MCP 面（v261009.46 起）**：你注册的工具（`ctx.mcp.tool`）不仅给内核 Agent 用，也会出现在 **MCP 工具面**上（名如 `p_<你的 id>__<工具>`）——**只有插件启用时才暴露**，停用即消失；写工具受「设置 → 外部接入」的 MCP 写入授权约束。

**版本窗口（v261009.44 起）**：`version_overview()` / `variant_family(doc_id, with_body=…)` /
`variant_sections(body)` / `merge_variants(base_id, picks, archive_merged=…)` /
`archive_variants(base_id, ids)` / `restore_variant(base_id, file)` —— 做「同一笔记的不同版本」的
界面与工具时用它；**版本与来源的记录在内核写入路径**，插件只操作，不自己解析文件。

**自动确认（v261020 起）**：`auto_merge_variants(base_id, strategy="agent", apply=False, archive_merged=…)`
—— 内核用**已配置的模型**逐节比较基条与各版本，返回 `picks` / `reasons`（`apply=False` 只给建议；
`apply=True` 写回基条）。模型不可用或某批没有返回结果时**自动回退**到「最近更新优先」规则，并在
`mode`（`agent` / `rule` / `rule-fallback`）与 `note` 里说明。调用方需在 `plugin.json` 声明
`llm:use`（会消耗模型用量）；纯规则用法传 `strategy="rule"`，不产生模型调用。

**写窗口（v261009.25 起）**：`entry_update(doc_id, body=…, **字段)` —— 改条目正文或白名单字段，
走内核的**校验写入路径**（字段白名单取自 `core/contracts`、原子写、记 `doc_update` 活动）。
它与 `lit_note_save` 同一模式：**安全闸门在内核**——插件把它注册成写工具（`spec.write = true`）后，
confirm 模式下内核只会生成草稿，用户确认后才以 direct 模式调用插件 handler。插件**不要**自己实现确认流，
也**不得**直接改 `Workspace/` 下的文件。

> **显式授权（v261009.38 起）**：用户可在「设置 → 外部接入」关掉**允许插件写入知识库**
> （`config/external-access.json` 的 `plugin_write`，默认开启）。关掉后本函数抛 `PermissionError`——
> 即"只读工作台"：插件仍可写自己的命名空间与配置，只是不碰知识库。
> 同理，外部 MCP 客户端的 5 个写工具由同一处的 `mcp_write`（默认**关闭**）控制。
> 插件**不需要**为此做任何事：闸门在 `core_api.entry_update` 与 `mcp/server.py` 分发层，
> 但**写工具仍要按规范声明 `spec.write = true`**（否则草稿闸门形同虚设）。

> **纯前端插件不必扩 `core_api`**：`core_api` 是给插件**后端**（`inprocess` 的 `entry`）用的；
> 只有前端脚本的插件直接消费上面的公开 HTTP API 即可（`plugins/knowledge-graph`、
> `plugins/literature-reader` 都是这个形态，无 `entry`、无后端）。
>
> **重型 vendor 库仍在内核 `web/vendor/`**：PDF.js（`/vendor/pdfjs/**`，含 worker / cmaps / standard_fonts，
> 本地优先 + CDN 兜底）与 mermaid / mathjax / marked / DOMPurify / highlight.js 一样，属**公开 vendor 路径**——
> 插件页面可直接引用，不要把 MB 级副本塞进插件目录。

**渲染接管契约**（`ERWGraphRenderers`）：

- 形如 `{id, graph: {async enhance(canvas, ctx)}, overview: {async enhance(canvas, ctx)}}`；同一 `id` 不得重复注册，至少声明一个作用域。
- 内核在**页面 markup 就绪后**调用 `enhance(canvas, ctx)`（`ctx = {route, host, contract}`）并 `await`：**resolve = 已接管**（内核不再画兜底图）；**throw = 没接管**（内核打印原因并回退 `drawGraph`）。
- 取消与失败要分清：页面已切走 / 画布已被更新的一次渲染替换 → **静默 `return null`**（那不是错误，别往控制台丢 error）；取数失败 → **throw**。
- 实例生命周期归插件自己：内核只在进入页面时喊一次，插件自行在 `hashchange` 上释放。

---

## 7. 安全与校验

安装/启用时的校验清单（任一不过 → **拒载并说明原因**）：

1. `plugin.json` 存在且能通过 schema 校验（`id` 合法、`version` 语义化、`api_version` 为整数）；
2. `api_version` 与内核兼容；`core_min` 满足；
3. 依赖可满足、无环、无同 id 多版本冲突；
4. 单文件包解包安全：拒绝绝对路径、`..` 穿越、符号链接逃逸（只允许包内相对路径，且落点必须严格在 `plugins/<id>/` 内，见 §2 解包规则）；**已实现**，另加条目数/解压体积/解压比上限；
5. 可选完整性校验：包内或其旁提供 `.sha256`，与 `System/plugins.json` 记录比对；
6. **权限清单展示**：`permissions` 会在安装/启用时用人话列出（如「可访问网络」「可写入自己的数据目录」）；声明了未支持权限 → 拒载；
7. 冲突检查：`id`、路由前缀、工具名前缀、CSS 作用域与已启用插件重复 → 拒载。

**失败行为统一为**：该插件状态 `rejected`/`blocked` + 原因 + 修复建议；**核心零影响**（I4），并在 `System/plugins.json` 与设置页健康面板同时可见。

---

## 8. AI 工具的扩展路径（默认最小集 → 按需添加）

AI 的工具**只有三种来源**，且核心默认只开第一种：

| 来源 | 默认 | 命名 | 说明 |
| --- | --- | --- | --- |
| ① 核心内置 | **开（不可关）** | `kb_search`、`kb_read`、`kb_create_entry`、`kb_update_entry` | 读库 + 出草稿等确认（SCOPE §5.1） |
| ② 插件注册的工具包 | 关（可勾选） | `p_<plugin>__<tool>` | 把**已经存在**的工作台 MCP 25 个工具按主题打包成官方工具包，见下 |
| ③ 外部 MCP 服务器 | 关（需显式确认） | `mcp_<server>__<tool>` | 在 `config/mcp.json` 里声明 `mcpServers`（stdio/http）即可接入任意第三方工具 |

**②的三个官方工具包**（直接复用 `mcp/` 里已有的实现，不重写）：

| 工具包 | 含工具 | 用途 |
| --- | --- | --- |
| `tools-kb-admin` | `kb_constraints`、`kb_list_entries`、`kb_get_entry`、`kb_check_entries`、`kb_rename_entry`、`kb_change_kind`、`kb_delete_entry` | 命名体检、改名、改 kind、删除（写类仍走草稿确认） |
| `tools-ws-ops` | `ws_info`、`ws_tree`、`ws_list_projects`、`ws_project_detail`、`ws_create_project`、`ws_update_project`、`ws_dashboard`、`ws_activity`、`ws_index_status`、`ws_reindex`、`todo_list`、`todo_create`、`todo_update`、`kb_graph`、`lit_export_bibtex` | 项目/待办/索引/图谱/导出 |
| （未来）`tools-rag` | `kb_retrieve` | 语义检索（随 RAG 插件） |

**③的安全提示**：外部 MCP 服务器能读你的知识库，因此**默认关闭**，启用时展示它声明的能力并需一次人工确认；工具名一律加 `mcp_<server>__` 前缀避免撞名。

---

## 9. 「丢进去就能用」的 5 个前提（速查）

| # | 条件 | 不满足时 |
| --- | --- | --- |
| 1 | `plugin.json` 合法（含 `id`/`version`/`api_version`/`kind`） | `rejected` + 指明哪个字段 |
| 2 | `api_version` 与内核兼容 | `rejected` + 提示升级内核或换插件版本 |
| 3 | 依赖（前提插件）已安装并启用 | `blocked` + 列出缺哪个、要什么版本 |
| 4 | 无同 id 多版本 / 无命名空间冲突 | `conflict` + 列出候选，让你选留哪个 |
| 5 | 声明的权限都被内核支持 | `rejected` + 列出不支持的权限项 |

> 默认**不启用**（除非 `default_enabled: true`）；发现后出现在设置页「可用插件」里，一键启用。

---

## 10. 打包期的依赖审计与前置提示（约束）

**规则**：任何功能被打包成插件时，**必须先做依赖审计**；只要存在对「前提插件」的依赖，就**必须显式声明并提示**，不允许隐式共享。

打包自检 `python -m core.plugins pack <feature> --check` 扫描四类引用：

| 扫描项 | 发现什么 | 处理 |
| --- | --- | --- |
| Python import（`inprocess` 插件） | 引用了别的插件模块 / `core.*` 私有模块 | 前者 → 必须声明为前提插件依赖；后者 → 必须改走 `core_api` |
| 路由 / 工具 / 事件注册 | 注册进别的插件命名空间，或依赖对方提供的钩子 | 声明依赖 |
| 存储访问 | 读写别的插件的数据目录 / 共享 DB 表 | **禁止**：改为对方公开接口或 `core_api` |
| 前端资源 | 引用别的插件的 JS/CSS/DOM 钩子 | 声明依赖（前提插件须提供稳定的 `ctx` 接口） |

三种结论：

1. **无依赖** → 通过，产物标注「无前置依赖」；
2. **有依赖且已声明**（`requires.plugins` + 对方 `provides`）→ 通过，产物生成人可读的 `DEPENDENCIES.md`（id / 版本区间 / 缺失时的表现）；
3. **有依赖但未声明** → **打包中止**（不是警告），提示「检测到对 `X` 的依赖：请声明 `requires.plugins`，或先把 `X` 抽成前提插件」——避免把隐式依赖带给用户。

**安装 / 启用时必须提示**（同一信息两处出现）：

- 设置页：「需要前提插件 `literature-base` ≥1.0 —— 未安装〔一键安装〕/ 已装未启用〔一键启用〕」；
- CLI：`python -m core.plugins check <id>` 输出同样的依赖树与状态。

**提示分级**：

| 级别 | 含义 | 行为 |
| --- | --- | --- |
| `error` | 缺了它功能根本不可用 | 该插件 `blocked`，不允许启用 |
| `warn` | 缺了会**降级**（例：没装 RAG → 语义检索退回关键词） | 允许启用，但启用前明确告知降级后的表现 |

---

## 11. 功能提取的等价性要求（约束：原功能与效果不变）

**规则**：把已有功能「提取」成插件**不是重写**——对外可见的功能与效果必须逐项保持不变；任何有意变化都要显式声明理由，否则视为回归。

### 11.1 迁移前：冻结「行为基线」

| 契约面 | 要抓的东西 |
| --- | --- |
| HTTP | 路由全表（方法 + 路径 + 参数 + 响应形状）与状态码 |
| 工具 | MCP 工具表（`--selftest`）与内置 AI 工具表（`agent_tools.TOOL_NAMES`）的名称、参数、返回结构 |
| UI | 导航项/面板位置、DOM id 与 `window.ERW*` 钩子、快捷键、文案、空态与错误提示 |
| 存储 | 文件路径与格式（`System/Cache/*.sqlite`、`config/*.json`、`Workspace/**` 有无变化） |
| 配置 | `config/app.json` 中该功能用到的键与默认值 |

### 11.2 迁移后：逐项比对，产出《迁移等价性报告》

每项标 `一致` / `有意变化（附理由）` / `回归`；**出现「回归」必须修掉才能合并**。报告随该插件的迁移提交一起入库（放插件 `README.md` 末尾或 `docs/migrations/`）。

### 11.3 兼容与降级

- **数据兼容**：默认不改存储格式与路径；确需改动 → 插件自带 migration（幂等 + `--dry-run` + 可回滚），且**插件被禁用时核心仍能正确忽略旧数据**（不误删、不报错）。
- **禁用等价性**：插件禁用后，表现必须等于「这个功能从未存在」——不残留路由 / 工具 / 面板 / 报错，也不损坏数据。
- **体验不变**：用户不应因为「它变成插件了」而重新学习操作（按钮位置、快捷键、交互手感保持一致）。

### 11.4 验收手段（可执行）

| 手段 | 做法 |
| --- | --- |
| 契约 diff | 迁移前后各抓一次路由表 / 工具表 / 导航表，做集合 diff |
| 固定用例回放 | 同一批只读请求与操作序列比对响应（注意 P28：读也要写权限，基准测试应在服务停时跑，或用 `?mode=ro` 连接） |
| 界面对照 | `tools/shot_page.py` 迁移前后各一张 1x 裁剪图对照 |
| 人工清单 | 快捷键、拖拽、空态、错误提示逐条勾选 |

> 这四项是**每个功能插件化的准入门槛**。也正因如此，A13（取回 `tools/kb_smoke.py` 与 `tools/shot_page.py`）是整条插件化路线的前置条件。

---

## 12. 已定（原「待定两点」）

| # | 问题 | 决定 |
| --- | --- | --- |
| **P-A** | 单文件包扩展名 | ✅ **先用 `.zip`**，后续再改（将来可加 `.erwp` 别名，两种都要能识别） |
| **P-B** | 是否自动解包 | ✅ **自动解包**（v261009.21 已实现 `core/plugins/unpack.py`），但**每个功能模块一个独立文件夹、不能混用**——规则见 §2「解包规则」 |

---

## 13. 上手：从模板到可用插件（不改内核）

### 13.1 一句话回答四个问题

| 问题 | 结论 | 靠什么成立 | 可执行证据 |
| --- | --- | --- | --- |
| **① 内核预留了接入基础，按标准放进目录就能用** | ✅ 成立 | 目录即发现（§1 两个来源）；清单校验/依赖拓扑/命名空间隔离/单文件包解包都在内核侧 | `python -m core.plugins list`；`.scratch/tmp/verify_zip_unpack.py` |
| **② 有模板，照它开发不用改内核** | ✅ 成立 | `plugins/.template/` + `tools/new_plugin.py` | `.scratch/tmp/verify_plugin_template.py` ①（脚手架）/②（占位符与校验） |
| **③ 加插件不用动内核 UI** | ✅ 成立 | 4 类自登记点（导航页 / 设置页 tab / 阅读区 tab / 槽位）+ 挂载点带 `data-plugin=<id>` 做样式作用域 | 同一夹具 ⑦：真浏览器里新页面与新 tab 可用、切回内核页面属性被清掉、0 console error |
| **④ 内核可改，且改一次不会废掉所有插件** | ⚠️ **有边界**，见 §13.3 | `api_version`（不匹配**明确拒载**，不是静默失效）、`core_min`、接缝只增不删、模板即回归夹具 | 夹具 ④（内核源码零引用）+ ⑨（装不上的插件在设置页如实可见） |

**③ 的边界要说清**：这里的"不动内核 UI"指**新增功能不需要改内核**。如果新插件要往**既有内核页面内部**塞东西（例如在文献列表页加一个按钮），那必须有内核先声明一个接缝——这属于 §6.2 的第 ② 类（一次性加一种"形态"），是**有意设计**的：内核不认识具体功能，插件也不能改内核 DOM。

### 13.2 三步做出一个插件

```powershell
# ① 生成（会校验一遍，通过才落盘；默认拒绝覆盖已存在目录）
python tools/new_plugin.py my-tool --name "我的工具" --desc "一句话说明它干什么"

# ② 改三个文件：backend.py（路由/工具/配置）、web/panel.js（界面）、web/panel.css（样式）
#    不需要动内核任何文件——内核源码里不该出现你插件的 id

# ③ 验证 → 重启 → 启用
python -m core.plugins list
python -m core.plugins check my-tool
python tools/plugin_check.py      # 改了插件后端就跑
python tools/web_check.py         # 改了插件前端就跑
```

**模板里有什么**（都带占位符，`new_plugin.py` 会替换成你的 id / 名字 / 最低内核版本）：

| 文件 | 演示了什么 |
| --- | --- |
| `plugin.json` | 清单：权限、导航项、`panel.style`、`routes`、`mcp_tools`；`core_min` 默认取**当前内核版本** |
| `backend.py` | `register(ctx)`：`ctx.routes.get/post`、`ctx.mcp.tool`、`ctx.config_read/write`、`ctx.log` |
| `web/panel.js` | 自登记导航页 + 设置页 tab；`window.erwFetch` 调自己的后端；`ERWContract`/`ERWToast` 空值保护 |
| `web/panel.css` | 全部选择器落在 `[data-plugin="<id>"]` 里（否则样式会泄漏到内核页面） |
| `README.md` | 改哪四步、怎么验证、隔离边界、7 个真实插件的"想看什么就看哪个"索引 |

**挂载点与样式作用域**：内核会给插件自登记的容器写 `data-plugin="<id>"` —— 导航页（`#main`）、
设置页（`#settings-panel`）、槽位容器；每次导航/切 tab 先清掉上一轮的值，所以插件 CSS **不会**
泄漏到内核页面。阅读区 tab 的容器由阅读区插件自己提供，同样按此约定加属性。

**生成新插件用到的目录约定**（`new_plugin.py` 会自动遵守）：

1. 目录名必须等于 `plugin.json` 的 `id`（否则 P018 拒载）；
2. 渲染与校验在 `<plugins>/.staging/<id>/` 里做，通过后原子改名为 `<plugins>/<id>/`——不会留下半成品被扫描器读到；
3. `--force` 重做时，旧目录整体挪到 `<plugins>/.backup-<id>-<时间戳>/`（不删除、不与新文件合并）；
4. 一律写 **UTF-8 无 BOM**（带 BOM 会让 `plugin.json` 解析失败、`core_min` 比较全线失败）。

### 13.3 兼容性承诺：内核怎么改才不"一改废掉所有插件"

| 规则 | 说明 |
| --- | --- |
| **`api_version` 只在破坏性变更时 +1** | 它代表"插件所依赖的内核 API 版本"，不是内核版本。**新增**接缝、新增字段、新增槽位都**不动** `api_version`；只有"旧插件按老写法必然走不通"（删改已有接缝语义、改签名）才 +1，并在 CHANGELOG 里明写迁移方法。 |
| **不匹配就明确拒载** | `api_version` 不符 → `rejected` 并给出「升级内核或换插件版本」（I7）。刻意不做"尽力而为"的兼容：静默半坏比拒绝更贵。 |
| **接缝只增不删** | §6.1 里的接缝即使没人用也不删；确要下线，先在 §6.1 标注「已弃用」并保留至少一个大版本。 |
| **`core_min` 是插件侧的下限** | 插件声明"至少需要哪个内核"；内核版本高于它就一直可用（`v261009.22` 满足 `v261009`）。反向（内核低于插件要求）→ `rejected` 且理由写在设置页上。 |
| **内核改动必须过插件回归** | `tools/plugin_check.py`（依赖方向/零插件可跑）+ `tools/web_check.py`（接缝提供方/消费方是否齐备）+ `ui_smoke.py`（真浏览器 17 路由）+ **`.scratch/tmp/verify_plugin_template.py`**（模板生成的插件端到端 49 项）。改了 `core/plugins/` 或 `web/` 的接缝层就把这几个跑一遍。 |
| **模板即夹具** | `plugins/.template/` 不只是示例：夹具每次都从它生成一个真插件跑端到端。所以模板一旦随内核演进而失效，回归会红——这比"文档说没问题"可靠。 |

**已知仍需改内核的情况**（不是缺陷，是边界）：想新增一种"形态"（让插件接管整页 / 接管局部 / 提供常驻容器 / 插件间通信契约）见 §6.2 ②；想让内核先实现某个能力（`ctx.search.addSection`、`ctx.jobs`、`process` 执行层）见 §6.2 ③。

