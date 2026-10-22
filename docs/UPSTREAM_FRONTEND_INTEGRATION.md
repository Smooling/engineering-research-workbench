# 上游前端接入说明（`feature/upstream-frontend-v261022`）

> 背景：上游 `Smooling/...codex/agent-harness-cortex-memory` 已并入 `feature/slim-workbench-v261009`（v261022.0 合并提交 `96eec87`）。
> 合并时为控制风险，上游 7 个前端模块先移出工作树；本分支按「一项一提交」逐项接回，每一项都经过浏览器实测 + 闸门 + CI。
>
> 本文记录**接了什么、没接什么、为什么**，后续接手时以本文为准。

## 一、已接入

| 版本 | 模块 | 接入点 | 接缝改造 |
| --- | --- | --- | --- |
| v261022.1 | `milestone-gantt.js/css` | 里程碑页「甘特」tab：项目分组、阶段条/菱形节点、全览/日/周/月、定位今天、状态筛选、点击编辑起止日期与进度 | `erwFetch`；`ERWProjectScope` 缺失时降级原生下拉（v261022.5 已换回）；无 `ERWResearchUI` 依赖 |
| v261022.2 | `sync.js/css` | 设置「同步」tab、顶栏同步按钮与计数、文档变更徽章、冲突处理弹窗 | `erwFetch`；`ERWDom.onChildList` 替代自建 MutationObserver；新增 `window.ERWSyncUI` 适配层（复用 `#modal`/toast/导航）；`app.js` 派发 `workbench:ready` |
| v261022.3 | `agent-client.js`、`agent-system.js/css`（设置侧） | 设置「AI 能力」（RAG/记忆/Skill 总开关）与「RAG」（模式/嵌入模型/分块/索引/检索试用/清除） | `erwFetch`；`ERWDom.onChildList`；新增 `ERWAgentPage`/`ERWResearchUI`/`ERWFabTimeline` 适配；补装 PyYAML |
| v261022.4 | `document-references.js/css` | 编辑器 `[[` 补全、`Ctrl/⌘+Shift+K` 选择器、引用浮动预览、断链状态、输入法组合暂停 | `erwFetch`；复用 `ERWMarkdown`/`ERWNav`/`ERWCurrentDoc`/`ERWToast`；`ERWPaneZoom` 空实现 |
| v261022.5 | `research-ui.js/css`、`project-scope.js/css` | 项目显示名、证据徽章、阅读字号（缩放菜单）、滚轮缩放辅助；甘特项目范围改为可搜索/键盘选择器 | `erwFetch`；首屏后预取项目记录 |
| v261022.6 | `agent-system.js`（Agent 页侧） | Agent 页右侧六 tab：对话 / 任务 / 记忆 / 技能 / RAG / 设置 | 对话区包 `#agent-chat-panel`、系统面板 `#agent-system-panel`；`ERWAgentPage.refresh` 改为只刷新消息，避免循环 |

## 二、未接入（附理由）

| 模块 | 处理 | 理由 |
| --- | --- | --- |
| `literature.js` / `literature.css` | 不接 | 本地 `plugins/literature-reader/web/panel.js`（1055 行）已完整替代：PDF.js 本地/离线、按页渲染、批注、笔记、AI tab、`ERWPanels.readerTab` 接缝 |
| `literature-workspace.css` | 不接 | 配套上游 literature 面板的布局样式；本地插件面板自带 `.lit-shell` 样式 |
| PDF「离屏绘制保帧」 | 不移植 | 本地面板已有等价策略：占位符 → 可视区渲染（`IntersectionObserver`，700px 预取）→ 渲染半径 4 页 → 切文献/离页 `cleanup`。上游是把整块面板换成离屏 canvas 方案，替换风险大于收益；若要做，应作为独立任务单独验证 |
| `v260922-*.js/css` | 不接 | 本地已按功能改名替代（`projects-manager.css`、`layout-compact.css`、`perf-and-fetch-seam.js`、`overview-editor-tools.css` 等），内容等价 |
| `v261008-billing.js/css` | 不接 | 计费已插件化（`plugins/billing`），内核只广播 `llm.usage` |
| `v260930-floating-agent.js/css` | 不接 | 本地无「悬浮助手」页面；`plugins/floating-assist` 提供悬浮球与快捷入口，两者不兼容 |
| `ERWFabTimeline` | 空实现降级 | 任务结果里的悬浮助手时间线；本地没有该模块，任务结果按纯文本渲染 |

## 三、新增/扩充的全局接缝

| 接缝 | 作用 | 缺失时行为 |
| --- | --- | --- |
| `window.ERWSyncUI` | 同步页宿主能力：`modal`/`closeModal`/`toast`/`openSettings`/`applyPreferences`/`refresh` | `sync.js` 不加载即无同步页 |
| `window.ERWAgentPage` | Agent 页会话与刷新：`sessionId`/`refresh`/`quote`/`searchSelection` | 任务「返回对话」不跳转；刷新退化为无操作 |
| `window.ERWResearchUI` | 项目显示名、证据徽章、阅读字号、`wheelScale` | 项目名原样显示，证据徽章为空 |
| `window.ERWProjectScope` | 可搜索/键盘项目范围选择器 | 甘特降级为原生下拉 |
| `window.ERWPaneZoom` | 面板级文本缩放 | 引用预览仍渲染，仅不能单独缩放正文 |
| `window.ERWFabTimeline` | 悬浮助手时间线渲染 | 任务结果按纯文本展示 |

`tools/web_check.py` 的原生事件白名单同步补充：`pagehide`/`pageshow`/`beforeunload`/`message`/`compositionstart`/`compositionend`/`compositionupdate`。

## 四、验证方式

每项接入都做过：

1. **静态**：`node --check`、`web_check`（语法/清单/接缝/加载顺序）、`web_manifest --check`
2. **浏览器**：Playwright 打开对应页面，量测 DOM 与接口，确认 0 console error，并按需截图
3. **回归**：`ui_smoke`（20 路由）、`kb_smoke`、`plugin_check --assert-core-only`、`mcp.server --selftest`、`run_tests --fast --no-server`（15/15）
4. **CI**：本分支每次推送都跑 GitHub Actions（ubuntu/windows 静态闸门 + 纯逻辑用例），截至 v261022.6 全部 success

## 五、后续可选任务（按价值排序）

1. **Agent 对话走 `agent_runtime`**：目前本地对话用自有发送链路，「任务」面板看不到 run；把发送接到 `agent_runtime.execute_loop` 后，任务/草稿/RAG 证据会自然出现（改动集中在 `app/agent.py` 的 `run_chat` 调用与 SSE 映射）。
2. **PDF 面板离屏保帧**：单独评估，需要替换 `renderPage` 的绘制顺序并做真实 PDF 缩放回归。
3. **悬浮助手时间线**：先决定是否引入上游的悬浮助手页面，再谈 `ERWFabTimeline`。
