# __NAME__（`__ID__`）· 插件

> 这份 README 既是**模板说明书**，也是**新插件的起点**：用
> `python tools/new_plugin.py <id> --name "<中文名>"` 生成后，占位符已经替换好，直接改代码即可。

## 这是什么

一个**能直接跑**的最小插件：侧栏一个页面 + 设置页一个 tab + 两个 HTTP 路由 + 一个 Agent 工具，
数据存在自己的命名空间里。它演示了插件与内核的全部接触面，**照它改不需要修改内核任何一行**。

## 目录结构

```text
plugins/__ID__/
├─ plugin.json      ← 唯一必需文件（清单：id/版本/权限/扩展点声明）
├─ backend.py       ← 可选：register(ctx)，注册路由与 Agent 工具
├─ web/panel.js     ← 可选：前端面板，必须自登记 window.ERWPanels
├─ web/panel.css    ← 可选：样式，必须落在 [data-plugin="__ID__"] 作用域内
└─ README.md        ← 本文件
```

## 改四步就能变成你的插件

0. **（建议）给插件加一张演示预览**：`plugin.json` 里的 `preview` 已经写好骨架——
   改 `summary`（一句话讲清解决什么问题）、`features`（能做什么），再把一张截图放进
   `web/preview.png`（元素级截图：只截这个插件自己的界面区域，1x、宽 ≤760、高 ≤700），
   然后在 `preview.screens` 里写上 `["web/preview.png"]`。
   之后用户只要在「设置 → 插件」里**把鼠标移到你这个插件上**，就能看到摘要 + 功能点 + 截图，
   不用读文档。规范见 [PLUGIN_SPEC §3](../docs/PLUGIN_SPEC.md)。

1. **改 `plugin.json`**：`id`（= 目录名，小写字母/数字/短横线）与 `name`（界面显示名）、`description`；
   不需要的扩展点（`nav` / `panel` / `routes` / `mcp_tools`）删掉即可，删干净不会报错。
2. **改 `backend.py` 的 `register(ctx)`**：留下你要的路由与工具。写工具在 `spec` 里加 `"write": True`，
   内核会**自动**帮你走"生成草稿 → 用户确认 → 才落盘"的闸门。
3. **改 `web/panel.js`**：换成你的界面；所有网络请求走 `window.erwFetch`，
   能用的内核小件（`ERWContract` / `ERWMarkdown` / `ERWToast` …）见 PLUGIN_SPEC §6.1，**都做空值保护**。
4. **改 `web/panel.css`**：选择器一律包在 `[data-plugin="__ID__"]` 里。

## 怎么验证

```powershell
python -m core.plugins list                # 发现 / 状态 / 启用了没（--install 顺带解包）
python -m core.plugins check __ID__        # 清单校验 + 依赖 + 权限报告（不落盘）
python tools/plugin_check.py               # 隔离体检：依赖方向单向、内核可脱离 app
python tools/web_check.py                  # 前端静态体检（改了 web/ 就跑）
```

- 改了 `backend.py` / `plugin.json` → **重启工作台**才生效；
- 只改 `web/*` → 浏览器刷新即可；
- 默认**不启用**（`default_enabled: false`）：装好后到「设置 → 插件」里点启用。

## 隔离与边界（违反会被拦下）

1. 插件**只许** `from core_api import …`；import 内核私有模块（`core.*` / `app.*`）会被 `plugin_check` 拦；
2. 路由写**相对路径**（内核加 `/api/plugins/__ID__/` 前缀），不要写裸 `/api/...`；
3. 工具名写**裸名**（内核加 `p___ID__` 前缀），不要自带前缀；
4. 只用自己的存储路径：`Workspace/Plugins/__ID__`、`System/Plugins/__ID__`、`System/Cache/__ID__.sqlite`；
5. **不要改内核 DOM/CSS**，不要替换 `window.fetch`；要新挂载点就走 §6.1 的接缝清单。

## 参考实现

仓库里 7 个真实插件是最完整的例子，按需要读：

| 想做的事 | 看哪个 |
| --- | --- |
| 只要一个前端页面（无后端） | `plugins/focus` |
| 顶栏槽位组件 + 配置页 | `plugins/weather` |
| 定时抓外部数据 / 缓存 / 离线降级 | `plugins/rss`、`plugins/weather` |
| 订阅内核事件（用量记账） | `plugins/billing` |
| 常驻浮层 UI（悬浮球） | `plugins/floating-assist` |
| 接管整个内核页面（图谱） | `plugins/knowledge-graph` |
| 多 tab、给别的插件提供接缝 | `plugins/literature-reader` |
| **产出文件并下载**（DOCX/HTML/Markdown 导出、`ctx.raw` 用法） | `plugins/report-export` |
| **后台定时任务**（`ctx.jobs`、快照与保留策略、外部目标目录） | `plugins/backup-snapshot` |
| **顶栏槽位角标**（`nav[].slot`、多面板 CSS 作用域） | `plugins/milestone-calendar` |
| **写工具 + 草稿闸门**（把结构化内容写回条目正文，`core_api.entry_update`） | `plugins/metrics-table` |

规范全文：[`docs/PLUGIN_SPEC.md`](../../docs/PLUGIN_SPEC.md)（§6.1 接缝、§6.2 能力矩阵、§7 安全与校验）。
