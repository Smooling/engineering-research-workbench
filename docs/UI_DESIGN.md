# 工程科研工作台 · UI 设计说明

> 本文描述工作台界面**当前实际生效**的视觉语言、布局、组件与交互规则，供两类人使用：
> ① 改界面之前先对照规范，避免"每个补丁各写一套"；② 排查界面问题时知道该看哪个文件、哪个变量。
>
> - 文档版本：v261021.4 · 实测于 2026-10-21
> - 唯一事实来源是 `web/` 下的 CSS 与 `web/app.js`；本文是**索引与规则说明**，数值以变量为准，冲突时以代码为准。
> - 新增页面请走 `window.ERWPanels.register()` 自登记（§9），不要改 `app.js` 的导航分支。

---

## 一、设计原则

| # | 原则 | 含义 | 反例（曾经踩过） |
| --- | --- | --- | --- |
| P1 | **零插件可跑** | 界面骨架、导航、设置页在清空 `plugins/` 后必须完整可用 | 把"用量统计"写进 `app.js` 的导航与路由分支 |
| P2 | **信息优先** | 紧凑只压缩留白，不压缩信息；不为了"好看"挤掉功能控件 | 把标签与日期压到项目名同一行，长项目名被截成"红外-…" |
| P3 | **滚动只作用于内容** | 侧栏、顶栏、设置左栏在滚动时零位移；内容不足时不出现可滚区域 | 整页 body 滚动带动所有面板（v261021.2 已改） |
| P4 | **并列元素等高** | 同一行的卡片、同一组控件严格等高、风格统一（设置页「导航 + 内容」两栏除外：按内容收缩，见 §4.2） | 设置页左栏比右栏矮一截 / 控件高矮不一 |
| P5 | **一处定义、全局继承** | 颜色/圆角/间距用变量；旧变量通过映射层桥接，不各写一套 | 同一绿色出现 3 个不同十六进制值 |

---

## 二、视觉语言

### 2.1 色彩体系

三层变量，**从下往上覆盖**，改主题只改最上层的映射：

| 层 | 文件 | 变量前缀 | 作用 |
| --- | --- | --- | --- |
| 画布层 | `v261014-soft-chromatic.css` | `--sc-*` | 画布/卡片/线条/模块身份色/语义色 |
| 主题层 | `v261014-linear-luxe.css` | `--lux-*` | 主色、墨色、阴影、渐变、焦点环 |
| 兼容层 | 两个文件末尾的映射块 | `--bg` `--surface` `--accent` … | 让旧模块无需改动即继承新语言 |

**画布层级**（软彩主题，明亮模式）：

| 变量 | 值 | 用途 |
| --- | --- | --- |
| `--sc-app` | `#F1F4F9` | 应用最底层背景 |
| `--sc-main` | `#F7F9FC` | 侧栏、顶栏底色 |
| `--sc-card` | `#FCFDFE` | 卡片表面 |
| `--sc-subtle` | `#F2F5FA` | 次级填充（列表行、输入框底） |
| `--sc-float` | `#FFFFFF` | 浮层（下拉、弹窗） |
| `--sc-line` / `--sc-line-strong` | `#DFE5EF` / `#C5D0E3` | 常规描边 / 强调描边 |

**模块身份色**（导航项、模块页眉按 `html[data-route]` 自动切换 `--module-accent` / `--module-soft`）：

| 模块 | 变量 | 明亮值 | 暗色值 |
| --- | --- | --- | --- |
| 任务 / 待办 / 笔记 / Agent | `--sc-task` | `#5069DE` | `#a7b9ff` |
| 研究 / 实验 / 日志 | `--sc-research` | `#168C78` | `#7bd2bd` |
| 里程碑 / 灵感 | `--sc-milestone` | `#C58A31` | `#f1c47e` |
| 图谱 / 总结 | `--sc-graph` | `#8462CB` | `#c6a8f8` |
| 文献 | `--sc-literature` | `#3488BE` | `#8bcff5` |
| 风险 / 逾期 | `--sc-risk` | `#D85F6A` | `#ffadb8` |

**主色与强调**：`--lux-primary #5e6ad2`（靛蓝），`--accent` 由它映射；`--accent-soft` 用于选中态底色，`--accent-ink` 用于选中态文字。

**语义色**：`--danger` `--warning` `--ok`，均有 `-soft` 变体作浅底。

**暗色**：`theme-dark.css` 只覆盖 `--sc-*` 与少量 `--lux-*`，再回写 `--bg/--surface/--text/--line` 等旧变量。新增组件必须走这些变量，才能自动适配暗色。

### 2.2 字体与字号

```css
font-family: Inter, "SF Pro Text", "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
font-size: 14px;      /* body 基准 */
line-height: 1.5;
```

| 层级 | 字号 | 典型用途 |
| --- | --- | --- |
| 页面标题 | 21px / 700 | 顶栏 `#page-title` |
| 区块标题 | 16–18px / 600–700 | 卡片头 `h3`、面板标题 |
| 正文 | 14px | 默认 |
| 辅助文字 | 12px | `row-meta`、说明文字 |
| 标签/元信息 | 10–11px | 徽章、日期、分组标题（`letter-spacing: .11em` + 大写） |
| 等宽 | `Consolas, "SFMono-Regular", monospace` | 路径、ID、版本号 |

### 2.3 圆角、阴影、间距、动效

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `--radius` / `--sc-radius-card` | 12px | 卡片、面板 |
| `--radius-sm` / `--sc-radius-soft` | 8–10px | 按钮、列表行、输入框 |
| `--sc-radius-small` | 6px | 小徽章、紧凑控件 |
| `--lux-shadow-xs/sm/md/lg` | 1px→16px 四档 | 卡片→浮层逐级加深 |
| `--sc-shadow-card` / `--sc-shadow-hover` | 极浅 | 卡片默认 / 悬停 |
| `--sc-ease` | `180ms cubic-bezier(.2,0,0,1)` | 主题统一过渡曲线 |
| 按钮过渡 | `120ms` 同曲线 | 背景/边框/颜色/阴影/位移 |

间距习惯：卡片内边距 14–18px；卡片间距 12–14px；表单网格 `gap: 8px`；控件间距 6–8px。

---

## 三、布局骨架

```
┌──────────────────────────── desktop titlebar 48px（仅桌面版）────────────────────────────┐
│ ┌──────────────┬─────────────────────────────────────────────────────────────────────┐ │
│ │ sidebar      │ topbar 64px（桌面 58px）：页面标题 / 日期 ··· 搜索 天气 主题 密度 缩放 刷新 │ │
│ │ 52–200px     ├─────────────────────────────────────────────────────────────────────┤ │
│ │ 可拖拽       │ main#main：max-width 1800px（主题层 1900px），padding 14/22/24        │ │
│ │ brand 64px   │                                                                     │ │
│ │ nav（滚动）  │  页面内容（卡片 / 列表 / 设置两栏 / 文档三栏 …）                        │ │
│ │ footer       │                                                                     │ │
│ └──────────────┴─────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.1 侧栏（`aside.sidebar`）

- **宽度可拖拽**：右缘 `.sidebar-resizer` 手柄，范围 **52–200px，默认 168px**，宽度写入 `localStorage.sidebarWidth`。
- **三档模式**（`html[data-sidebar-mode]`）：
  | 模式 | 宽度 | 表现 |
  | --- | --- | --- |
  | `icon` | < 90px | 只留图标，文字隐藏 |
  | `compact` | 90–139px | 图标 + 短标签，品牌副标题隐藏 |
  | `full` | ≥ 140px | 完整品牌区与分组标题 |
- 结构：`brand`（64px，与顶栏等高）→ `#sidebar-nav`（`flex:1`，唯一滚动区）→ `sidebar-footer`（Workspace 路径与版本号）。
- 导航按分组：**核心工作 / 研究 · 知识 / 资源 / 系统**；「研究 · 知识」默认折叠。分组头可折叠、可置顶（`.pin`）。
- 插件的导航项由 `ERWPanels.register` 并入对应分组（§9）。

### 3.2 顶栏（`.topbar`）

- 高 64px（桌面外壳下 58px），`position:sticky; top:0`，半透明 + `backdrop-filter: blur(15px)`。
- 左：`#page-title` + `#page-date`；右：全局搜索（⌘K）、插件槽位 `#topbar-slot`、主题、密度、缩放、刷新/重启。
- 顶栏右侧是**插件槽位**：天气、资讯角标等由插件 `renderSlot` 画入，内核不认识具体功能。

### 3.3 主内容（`main#main`）

- `padding: 14px 22px 24px`；`max-width: 1800px`（主题层 1900px），居中。
- 绝大多数页面由 `#main` 承载，**body 整页滚动**（设置页例外，见 §4.2）。
- 内容形态：卡片网格（`grid-2/3/4`）、列表（`list-stack` + `list-row`）、文档三栏（`docs-layout`）、设置两栏（`settings-layout`）。

### 3.4 桌面外壳（`desktop.css`）

- 仅在桌面版（`html[data-desktop="true"]`）生效：自定义 48px 标题栏 + 窗口控制按钮；`--vh-px` 由 `desktop.js` 注入，表示"扣除标题栏后的可用视口高度"。
- 所有依赖视口高度的布局（设置页、侧栏、全屏页）必须用 `var(--vh-px, 100vh)`，不要直接写 `100vh`。

---

## 四、滚动规范（v261021.2 / v261021.3 定稿）

**总原则：滚动只作用于内容，不带动其他要素；内容不足时不产生可滚区域。**

### 4.1 侧栏

```css
.sidebar-nav { padding: 10px 8px 12px; overflow-y: auto; flex: 1; }
```

- 底部内边距固定 12px。**不要写回 56/60/64px**：内边距会计入 `scrollHeight`，内容只到 828px、容器 886px 时会产生 27px 的"空滚"，滚轮被侧栏截走。
- 验收：内容未铺满时 `scrollHeight === clientHeight`、`maxScroll === 0`；窗口变矮、真正溢出时才可滚。
- 已知覆盖链：`v261014-linear-luxe.css`（`.sidebar-nav{padding:9px 8px 12px!important}`）> `layout-compact.css` > `styles.css`。改内边距要三处一起改，否则被 `!important` 覆盖。

### 4.2 设置页（`settings-layout`）

- 介于"顶栏 + 主内容内边距"之间的高度内，**两栏各自滚动**，`body` 不再滚动：
  - 普通模式：`max-height: calc(100vh - 102px)`
  - 桌面模式：`max-height: calc(var(--vh-px, 100vh) - 96px)`
- 两栏**各自按内容收缩**（`align-items: start`）：内容少时卡片就矮，不强行等高、不在卡片里留大片空白；内容多时由上面的 `max-height` 封顶，在卡片内部滚动。左栏短于右栏是正常状态（不是缺陷）。
- 右栏 `overscroll-behavior: contain`：滚到边界不再链式带动整页。
- `scrollbar-gutter: stable`：滚动条出现/消失时内容不横向跳动。
- 切换设置 tab 时 `#settings-panel` 回到顶部（`app.js` 的 tab onclick）。
- 窄屏 `≤820px` 取消高度上限、恢复整页滚动。

### 4.3 其他页面

- 保持 body 整页滚动；长列表（文档列表、项目树）在自己的面板内滚动（`.doc-list-panel`、`.tree-panel` 有 `max-height`）。
- 纵向滚动条统一 10px、半透明圆角滑块；`scrollbar-width: thin` 兼容 Firefox。

---

## 五、组件规格

### 5.1 按钮

| 类型 | 类名 | 规格 | 用途 |
| --- | --- | --- | --- |
| 主按钮 | `.primary-btn` | 高 34px、左右 16px、主色底白字 | 保存、新建、确认 |
| 次按钮 | `.secondary-btn` | 高 34px、左右 14px、白底强调色字 | 取消、模板、排序、编辑 |
| 幽灵按钮 | `.ghost-btn` | 无边框、悬停浅底 | 行内次要操作 |
| 图标按钮 | `.icon-btn` | 方形、图标居中 | 顶栏、卡片角标 |
| 顶栏胶囊 | `.density-pill` `.zoom-pill` `.top-search-btn` | 与顶栏等高的小胶囊 | 密度/缩放/搜索 |

所有按钮：圆角 8px（紧凑 6px）、`:active` 下移 0.5px、`:focus-visible` 3px 焦点环（`--lux-focus`）。**禁用态禁止只靠颜色**，要同时降透明度并保留可读文字。

### 5.2 表单

- 输入框/下拉/多行框统一高 **34px**（多行除外），圆角 8px，边框 `--line`，聚焦变主色 + 焦点环。
- 字段结构：`label`（11px 灰）→ 控件 → `field-help`（说明，11px）。
- 网格：`.form-grid` 默认 4 列，`span-2/3/4` 跨列；`≤1100px` 降为 2 列，`≤820px` 单列。
- 复选框 14×14，`accent-color: var(--accent)`。

### 5.3 卡片与列表

- `.card`：12px 圆角、1px 描边、极浅阴影、内边距 14–18px。
- `.card-head`：标题 + 说明 + 右侧操作，底部 8–10px 间距。
- `.list-stack > .list-row`：行高由内容决定（最小约 54px）、内边距 11–12px、`--surface-2` 底、8px 圆角；悬停加深描边。
- `.row-main` 允许收缩（`min-width:0`），元信息用 `.row-meta`（10–11px 灰）。
- 条目卡片元信息分两行：**项目名独占一行**，标签/状态/日期另起一行。

### 5.4 徽章与标记

- `.badge`：高 22px、左右 8px、999px 圆角、10px 字号；`accent` / `warn` / `danger` 变体用于状态。
- 分类标记 `.mark-chip`：带 `--mark-color` 自定义色，图标 + 文案。
- 条目卡片上的徽章行**固定单行**，放不下时右端淡出（不换行撑高卡片）。

### 5.5 设置页两栏

- 左栏 `.settings-nav`：卡片内的一组按钮，当前项用 `--accent-soft` 底 + `--accent-ink` 字；可扩展（插件设置 tab 由 `ERWPanels.settingsTab` 追加）。
- 右栏 `.settings-panel`：`data-plugin` 标记插件页来源；内核 tab 与插件 tab 共用同一渲染容器。
- 两栏各自按内容收缩、各自滚动（§4.2）；切换 tab 重置滚动位置。

### 5.6 弹窗、下拉、Toast

| 组件 | 规格 |
| --- | --- |
| 弹窗 `.modal` | 宽 `min(820px, 100%)`、`max-height: 88vh`、14px 圆角；头部/底部 13px 内边距，正文区独立滚动 |
| 遮罩 `.modal-backdrop` | `rgba(5,15,18,.48)`，居中，`padding: 22px` |
| 下拉 `.dropdown` | 白底、`--line` 描边、8–10px 圆角、`--lux-shadow-md`，按需 `hidden` 切换 |
| Toast `.toast-stack` | 固定右下 20px，纵向堆叠 7px；成功=深底白字，错误=`--danger` 底；最长 360px |

### 5.7 图标

- 内置使用**字符图标**（`▦ ✦ ⚗ ⑂ ⚙` 等）与少量内联 SVG，不引入图标字体。
- 分类标记支持任意符号/emoji（上限 24 个），图案面板按"几何 / 科研 / 符号 / 标记"分组。

---

## 六、主题、密度与缩放

| 维度 | 开关 | 实现 | 注意 |
| --- | --- | --- | --- |
| 主题 | 顶栏 ◐ / 设置 | `html[data-theme="light|dark"]` | 新增颜色必须走 `--sc-*`/`--lux-*`，否则暗色下失配 |
| 密度 | 顶栏「紧凑型/宽松型」 | `html[data-density="compact|cozy"]` | 紧凑只压留白（padding 10–18px），不改字号层级 |
| 缩放 | 顶栏 80%–125% | `documentElement.style.zoom` + `syncViewportVars()` | zoom 变化后需重算计 `--vh-px`；热力图等 one-screen 布局要重跑适配 |
| 侧栏宽度 | 拖拽手柄 | `--sidebar`（52–200）+ `data-sidebar-mode` | 宽度存 `localStorage.sidebarWidth` |

**响应式断点**：

| 断点 | 变化 |
| --- | --- |
| `≥1101px` | 宽屏紧凑布局生效（侧栏 260px 基准、内边距收缩） |
| `≤1100px` | 侧栏 238px；4 列表单→2 列；图谱/文档侧栏隐藏 |
| `≤820px` | 单列：侧栏变顶部块、设置两栏单列并恢复整页滚动、`.form-grid` 单列 |

---

## 七、交互与可访问性

- **状态反馈**：悬停（背景加一档）、按下（0.5px 位移）、聚焦（3px 焦点环）、禁用（降透明度）、加载（按钮文字或骨架，不阻塞滚动）。
- **焦点环**：`button/input/textarea/select/a:focus-visible` 统一 `box-shadow: 0 0 0 3px var(--lux-focus)`；不要用 `outline: none` 后不补替代。
- **键盘**：全局搜索 `Ctrl/⌘ K`；弹窗 `Esc` 关闭；列表行内的可编辑字段 `Enter` 提交、`Esc` 还原（待办行内编辑即此口径）。
- **对比度**：正文与背景 ≥ 4.5:1；辅助文字（10–11px 灰）只用于非关键信息。
- **动效**：统一 120–180ms、`cubic-bezier(.2,0,0,1)`；不做大幅位移与自动播放动画。
- **触控/窄屏**：可点区域不小于 34px；表格类在窄屏改卡片或横向滚动，不压缩到不可读。

---

## 八、页面注册与插件接缝

内核只负责挂载，功能自己登记。新增页面**禁止**在 `app.js` 里加路由分支。

| 接缝 | 用途 |
| --- | --- |
| `window.ERWPanels.register({id, group, label, icon, eyebrow, title, before?, render})` | 侧栏导航项 + 页面渲染 |
| `register({slot: 'topbar'|'overlay', renderSlot})` | 顶栏槽位 / 悬浮层 |
| `register({settingsTab: {label, render}})` | 设置页新增 tab |
| `register({readerTab: …})` | 文献阅读区新增 tab |
| `window.erwFetch` | 统一网络入口（不要给 `window.fetch` 赋值） |
| `window.erwVendor` | 重型库按需加载（mathjax / mermaid 不进首屏） |
| `workbench:*` / `erw-*` 自定义事件 | 跨模块通信 |

分组 id：`core` / `research` / `resources` / `system`；默认追加到分组末尾，`before: '<路由>'` 可插到指定项之前（版本页即 `group:'system', before:'settings'`）。

---

## 九、文件组织与加载顺序

`web/manifest.json` 是唯一装配清单，`index.html` 的 `<link>/<script>` 由 `python tools/web_manifest.py --write` 生成，**不要手改**。

| 顺序 | 文件 | 职责 |
| --- | --- | --- |
| 1 | `styles.css` | 基础组件与旧语言（变量兜底） |
| 2–8 | `projects-manager` `layout-compact` `overview-editor-tools` `perf-affordances` `graph-page-layers` `sidebar-agent-profiles` `layout-fixes` | 各功能域补丁 |
| 9 | `v261014-linear-luxe.css` | 主视觉（靛蓝、阴影、圆角） |
| 10 | `v261014-soft-chromatic.css` | 画布层级与模块色（`--sc-*`） |
| 11 | `v261015-usability.css` | 可用性收口（行高、间距、折叠） |
| 12 | `v261019-todo-edit.css` | 待办行内编辑 |
| 13 | `vendor/github.min.css` | 代码高亮 |
| 14–17 | `manual` `external-access` `desktop` `theme-dark` | 手册、外部接入、桌面外壳、暗色 |
| 18 | `workbench-ui.css` | **最后的全局覆盖层**（滚动规范、项目卡、计费暗色等） |

规则：

1. 新增样式优先放进对应功能文件；**跨页面全局规则**才放 `workbench-ui.css`（它最后加载，不必堆 `!important`）。
2. 改了 `web/*.js|css` 必须同步 `manifest.json` 里该文件的 `v` 版本参数（缓存键），再跑 `--write` 重建 `index.html`。
3. 不要在 `web/` 里覆盖内核设施（给 `window.fetch` 赋值、覆盖内核 DOM/CSS 选择器），`tools/web_check.py` 会拦。

---

## 十、改界面的验收清单

| 步骤 | 命令 / 做法 | 通过标准 |
| --- | --- | --- |
| 静态体检 | `python tools/web_check.py` | 语法、装配清单、接缝、加载顺序无问题 |
| 清单一致 | `python tools/web_manifest.py --check` | `index.html` 与清单无漂移 |
| 路由走查 | `python tools/ui_smoke.py` | 20 个路由可打开、0 console error、首屏不拉重型库 |
| 布局量测 | `getBoundingClientRect()` / `scrollHeight` / `computedStyle` | 并列元素等高；未铺满时 `maxScroll=0`；滚动前后其他元素 `top` 不变 |
| 像素确认 | `python tools/shot_page.py <url> -o .scratch/preview/x.png --crop …` | 1x、裁剪到改动区域、一轮至多 1 张 |
| 知识库回归 | `python tools/kb_smoke.py` | 全部通过 |

---

## 附：常见问题

| 现象 | 先查 |
| --- | --- |
| 侧栏没铺满却能滚 | `.sidebar-nav` 的 `padding-bottom` 是否被改回 56/60/64px（三处：linear-luxe / layout-compact / styles） |
| 滚动时整页跟着动 | 是否又给 `overflow-y:auto` 的容器叠加了 body 滚动；设置页上限是否失效 |
| 暗色下某块发白 | 新写的颜色没走 `--sc-*`，被 `background:#fff` 之类写死 |
| 紧凑密度下列表高低不一 | 行高用了内容撑开而不是固定/最小高；检查 `.list-row` 的 `align-items` |
| 插件页面不出现在侧栏 | `register` 是否声明了 `render`；`group` 是否为已知分组 |
