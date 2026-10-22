# 工程科研工作台 MCP 使用说明

面向 Agent 的 MCP（Model Context Protocol）服务，把「工程科研工作台」的存放规则、命名规范与知识库读写能力暴露给任意 MCP 客户端。服务零第三方依赖，只用 Python 标准库；写入路径复用工作台自身的 `app` 包，因此原子写入、回收站删除、活动日志与索引更新的行为与 Web 端一致。

- 传输：stdio，JSON-RPC 2.0。首选协议版本 `2025-06-18`，同时接受 `2024-11-05`；换行分隔帧，兼容 LSP 风格 `Content-Length` 帧。
- 事实来源：`Workspace/**` 的 Markdown + YAML frontmatter。`System/Cache/index.sqlite` 是可重建的派生索引。
- 规模：25 个工具、9 个约束资源、2 个提示模板。

## 快速开始

### 前置条件

- Python 3.9 以上。本机解释器为 `D:\Software\Miniforge\python.exe`。
- 工作台仓库位于 `d:\Project\engineering-research-workbench`。
- 工作区位置由 `config/app.json` 的 `workspace` 决定，默认为仓库内的 `Workspace/`，与启动时的工作目录无关。

### 自检

```powershell
# 在工作台根目录执行
python -m mcp.server --selftest
```

自检不启动 stdio，只校验工具表与约束资源：工具名是否重复、每个工具是否都有实现、必填参数是否在 `properties` 中声明、七个约束主题能否正常渲染。全部通过时输出 `"problems": []`、`"ok": true`，退出码 0。当前基线为 25 工具 / 9 资源 / 2 提示模板。

### 注册到 MCP 客户端

Trae 的用户级注册表位于 `%APPDATA%\TRAE SOLO CN\User\mcp.json`，在 `mcpServers` 下加一项：

```json
{
  "mcpServers": {
    "engineering-research-workbench": {
      "command": "D:/Software/Miniforge/python.exe",
      "args": ["-m", "mcp.server"],
      "env": {
        "PYTHONPATH": "d:/Project/engineering-research-workbench",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

Trae 的 stdio 配置只支持 `command` / `args` / `env` 三个字段，不支持 `cwd`，且 `command` 不得含空格，因此这里用 `env.PYTHONPATH` 把仓库根注入 `sys.path` 来定位本包。若客户端支持 `cwd`（如 Claude Desktop），可等价地改用 `"cwd": "d:/Project/engineering-research-workbench"`。

注册后重启客户端，工具应以 `mcp_engineering-research-workbench` 前缀出现。本机实测挂载点为 `%USERPROFILE%\.trae-cn\mcps\<工作区 id>\mcp_engineering-research-workbench\tools\*.json`，共 24 个描述文件。

> 命名冲突提示：本包名为 `mcp`，与官方 `mcp` SDK 同名。`PYTHONPATH` 指向仓库根时本包优先解析；若环境同时需要官方 SDK，请改用 `mcp/run_mcp.bat` 启动，或为服务单独指定解释器。

### 直接启动

```powershell
# 在工作台根目录执行，进程进入等待 stdin 的状态即为正常
python -m mcp.server
```

`mcp/run_mcp.bat` 是同等的命令行入口，适合作为客户端的 `command`。手工验证协议时，向标准输入写入一行 `initialize` 请求即可看到握手结果；服务把 `sys.stdout` 重定向到 `stderr`，业务代码里的任何 `print` 都不会污染协议通道。

## 工作约定

服务在 `initialize` 的 `instructions` 字段里向 Agent 下发六条约定，客户端支持时会自动注入会话上下文：

1. 会话开始先调 `kb_constraints`，至少读 `storage` 与 `naming` 两个主题。
2. 建档前用 `kb_search` / `kb_list_entries` 查重，用 `ws_list_projects` 确认项目归属，不要凭空拼项目名。
3. 一切写入都走 `kb_create_entry` / `kb_update_entry` / `kb_rename_entry` / `kb_delete_entry`，不要手写 frontmatter 落盘。
4. 命名规范是硬约束。校验结果中 `level=error` 的项会导致工具拒绝写入，除非显式传 `allow_violation=true`。
5. 改名必须用 `kb_rename_entry`。它会同步 title、首个 H1 与全库交叉引用，并只追加一次 `doc_update` 事件。
6. 收尾用 `kb_check_entries` 复核，必要时 `ws_reindex` 重建索引。

## 工具面按插件拆分（v261009.46 起）

**内核工具始终可用**（`kb_*` / `ws_*` / `todo_*` / 文献导出，共 29 个）；
**插件工具只在对应插件启用时出现**，名字形如 `p_<插件id>__<工具名>`（与内核 Agent 面一致）：

```powershell
python -m mcp.server --selftest      # 看当前工具面统计：kernel_tools / plugin_tools
```

- 在工作台「设置 → 插件」里**启用/停用一个插件**，MCP 侧**下一次 `tools/list` 就会跟着变**，
  不需要重启 MCP 服务（服务每次取目录时会比对"已启用插件指纹"并重载）；
- 判定口径与内核同源（`registry.effective_enabled`：有记录按记录，没记录按 `default_enabled`）——
  所以"附属插件默认开"的工具默认就在，可选插件要启用后才有；
- 插件**写工具**（注册时 `write: true`）同样受「设置 → 外部接入 → 允许外部 MCP 客户端写入知识库」约束；
- MCP 进程**只借插件的工具，不跑它们的后台任务**（加载后立刻停调度器），
  否则备份插件这类定时任务会在 MCP 进程里再跑一份。

### 发现「外部直接改文件」（v261009.49 起）

Markdown 是唯一事实来源，但 IDE/脚本可以**直接写 `.md`** —— 那条路绕过写入收口点，
既没有活动事件也没有来源与版本。用 `ws_external_edits` 巡检：

```json
{ "record": true }
```

- 判据：条目文件改动时间**晚于**该条目最后一次活动事件（内核每次写入都会同时更新文件并记事件）；
- 结果里另附 **`untracked`**：工作区里被改过但**不在知识库内**的 `.md`（临时稿、外部产物），
  它们没有任何 id/来源，工作台**不跟踪**——想让它们有记录，就得放进 `Knowledge/` 成为条目；
- `record=true` 会把发现写成 `doc_external_edit` 事件（来源「工作区外部改动」），
  于是出现在「版本」页的修改记录里。

### 看「修改记录」（v261009.48 起）

`ws_activity` 支持按**条目**或**事件类型**过滤，用来回答「这条笔记谁改的、什么时候改的」：

```json
{ "days": 30, "ref": "note-2026...", "types": ["doc_update", "doc_merge"] }
```

每条事件的 `source` 形如「外部 MCP 客户端 · kb_update_entry · Claude Desktop · 10-12 16:23」；
合并事件另带 `detail`（`merged_at` / `replaced_sections` / `merged_from`）。
工作台里的对应视图：**版本** 页 →「④ 修改记录（最近 90 天）」。

### 版本族（v261009.45 起）

| 工具 | 作用 | 写？ |
| --- | --- | --- |
| `kb_variants` | 列某条条目的版本族（基条 + 各版本 + 已归档 + **每条分支的时间**） | 否 |
| `kb_branch_entry` | **开一条分支**：以某条为源复制内容成新版本，记 `variant_label` 与 **`variant_at`（分支创建时间）** | **是** |
| `kb_merge_variants` | 按 H2 小节挑内容合并（`picks`），结果写回基条；记 `doc_merge` 活动（时间/小节/参与版本） | **是** |
| `kb_archive_variants` | 归档指定版本到 `System/Versions/<基条>/archived/`（保留可追溯） | **是** |

时间口径：`variant_at` 分支创建时间 · `created/updated` 条目创建/最近写入 · `origin_at` 该次写入时间 ·
归档清单里的 `archived_at` 归档时间 · 活动日志 `doc_merge.detail.merged_at` 合并时间。

> 🔐 **外部写入默认关闭**（v261009.38 起）：MCP 的 5 个写工具（`kb_create_entry` /
> `kb_update_entry` / `kb_rename_entry` / `kb_change_kind` / `kb_delete_entry`）受
> 「**设置 → 外部接入 → 允许外部 MCP 客户端写入知识库**」约束，**默认拒绝**。
> 未授权时写工具会返回 `[未授权] …`，只读工具（`kb_get_entry` / `kb_list_entries` / `kb_search` /
> `kb_check_entries` / `kb_constraints` 等）不受影响。这是为了补上"MCP 直写不走界面草稿闸门"这个缺口：
> 授权与否由你在设置里显式决定，配置文件是 `config/external-access.json`。

## 约束资源

九个资源以 Markdown 文本返回，供 Agent 直接读取。会话开始读约束是写入前的必要动作。

| URI | 内容 |
| --- | --- |
| `workbench://constraints/storage` | 知识库存放规则：目录结构、条目位置、事实来源、系统文件语义 |
| `workbench://constraints/naming` | 标题命名规范全文：前缀、类别词、名称段规则 |
| `workbench://constraints/sync` | 改名同步要求：title/H1 一致、id/created 不变、交叉引用与 activity 事件 |
| `workbench://constraints/kinds` | 七类条目矩阵：目录、前缀、状态机、日期字段、默认正文骨架 |
| `workbench://constraints/schema` | frontmatter 字段契约：字段序、可变性、日期字段、关系与标签 |
| `workbench://constraints/marks` | `kind_marks` 标记表与类别词映射 |
| `workbench://constraints/playbook` | Agent 操作手册：标准作业流程与红线 |
| `workbench://rules/naming-source` | `.trae/rules/知识库条目命名规范.md` 原文，命名约束的权威出处 |
| `workbench://workspace/layout` | `storage` 与 `kinds` 两节拼接的目录骨架 |

`kb_constraints` 返回同样内容，可用 `topic` 参数只取一个主题。`topic` 留空时返回全部七个主题。

## 工具总览

工具名大体按用途分组：`kb_` 前缀作用于 `Knowledge/` 下的知识条目，`ws_` 前缀作用于工作区、项目、待办与索引，`todo_` 前缀作用于待办清单。

### 知识条目

| 工具 | 说明 | 只读 |
| --- | --- | --- |
| `kb_constraints` | 读取约束 Markdown | 是 |
| `kb_list_entries` | 分页列出条目，可按类型、状态、项目、标记过滤并做全文字段检索 | 是 |
| `kb_get_entry` | 按 `doc_id` 读取全文并附命名校验 | 是 |
| `kb_create_entry` | 按规范建档，落盘到该 kind 的 `Knowledge` 子目录 | 否 |
| `kb_update_entry` | 按白名单字段与正文更新 | 否 |
| `kb_rename_entry` | 改名专用流程：校验新标题 → 同步首个 H1 → 重写全库交叉引用 → 追加一次 `doc_update` | 否 |
| `kb_change_kind` | 把条目改挂到另一类 kind：目录随动、标题前缀按目标类型改写、`id`/`created` 不变，可选同步全库交叉引用 | 否 |
| `kb_delete_entry` | 删除并移入 `System/Trash/<kind>/` | 破坏性 |
| `kb_check_entries` | 批量或单条命名体检，输出规则码问题清单 | 是 |

### 工作区、项目、待办与洞察

| 工具 | 说明 | 只读 |
| --- | --- | --- |
| `ws_info` | 工作区根路径、目录骨架、七类落盘目录、索引状态 | 是 |
| `ws_tree` | 目录树，受深度与条数上限保护 | 是 |
| `ws_list_projects` | 项目注册表：id、名称、状态、条目/里程碑/待办计数 | 是 |
| `ws_project_detail` | 项目记录、标准子目录文件树、关联条目、未完成待办 | 是 |
| `ws_create_project` | 创建项目并生成标准子目录 | 否 |
| `ws_update_project` | 更新项目名称、简介或状态 | 否 |
| `todo_list` | 读取 `System/todos.json`，可按项目过滤或只看逾期 | 是 |
| `todo_create` | 新增待办 | 否 |
| `todo_update` | 更新标题、项目、截止日、优先级或完成状态 | 否 |
| `kb_search` | 跨条目、待办、会话的统一检索 | 是 |
| `kb_graph` | 给 `doc_id` 返回邻域关系图，留空返回全库总览 | 是 |
| `ws_dashboard` | 条目、项目、待办、活动的聚合统计 | 是 |
| `ws_activity` | 读取 `System/activity.jsonl` 活动事件 | 是 |
| `lit_export_bibtex` | 导出文献条目的 BibTeX，可限定 `ids` | 是 |
| `ws_index_status` | 索引版本、最后同步时间与计数 | 是 |
| `ws_reindex` | 全量重建派生索引 | 否 |

## 写入类工具的用法

### 建档

`kb_create_entry` 的标题有两种给法。给 `title` 时按原值使用；给 `name`（配合 `category`、`note_suffix`）时由工具按命名规范拼出完整标题，`note` 类必须在 `category` 中给出类别词。

| 参数 | 说明 |
| --- | --- |
| `kind` | 必填。取值限定 `idea` / `journal` / `note` / `milestone` / `summary` / `literature` |
| `title` / `name` + `category` | 二选一，给 `title` 时优先 |
| `body` | 正文 Markdown；缺省使用该 kind 的默认骨架 |
| `status` | 缺省取该 kind 状态机的首个状态 |
| `projects` | 归属项目名列表，会校验项目是否存在 |
| `tags` / `kind_marks` / `pinned` | 标签、标记与置顶 |
| `record_date` / `due` / `added_date` | 日期字段，按 kind 固定 |
| `allow_violation` | 跳过硬校验强制建档，不推荐 |

返回体含 `created`、`entry`（落盘后的完整 frontmatter 与正文）、`validation`（`ok` / `issues` / `errors` / `warnings`）与 `dir`。`validation.ok` 为假且未传 `allow_violation` 时不落盘，返回体里带 `_hint` 说明拒绝原因。

```json
{
  "name": "kb_create_entry",
  "arguments": {
    "kind": "note",
    "name": "点目标候选提取判据",
    "category": "方法",
    "projects": ["红外-可见光天基动目标识别与跟踪"],
    "tags": ["红外", "点目标检测"],
    "body": "# 知识-方法-点目标候选提取判据\n\n## 摘要\n\n…"
  }
}
```

### 改名

`kb_rename_entry` 是唯一的改名通道。它校验新标题、替换正文首个 H1、重写其他 Markdown 中出现的旧标题、只追加一次 `doc_update` 事件，`id` 与 `created` 保持不变。

批量改名之前先传 `dry_run=true` 取影响面：返回的 `plan` 里含 `old_title`、`new_title`、`h1_synced`、`references`（被引用的文件与次数）、`validation`。确认后才不带 `dry_run` 再调一次。传 `update_references=false` 可跳过交叉引用重写。

### 更新与删除

`kb_update_entry` 只接受白名单字段，`projects` / `tags` / `kind_marks` 是整体覆盖语义，`body` 也是整体覆盖。只想换标题时仍应走 `kb_rename_entry`，否则引用面不会同步。

`kb_delete_entry` 缺省只返回 `preview`，需要显式传 `confirm=true` 才移入回收站。删除前先用 `kb_graph` 或 `kb_rename_entry` 的 `references` 看清被引用情况。

### 体检

`kb_check_entries` 不传 `doc_id` 时批量扫描，用 `kind` 限定类型、`limit` 限定条数（默认 60，上限 200）。传 `check_h1=true` 会额外读取正文校验 title 与首个 H1 是否一致，代价是逐条读盘。返回的 `findings` 里每条含 `id`、`kind`、`title`、`dir` 与 `validation`；合规且无警告的条目默认被过滤掉。

## 校验规则码

命名体检与写入校验共用同一套规则码，`level=error` 阻断写入，`level=warn` 只提示。

| 码 | 级别 | 含义 |
| --- | --- | --- |
| `T000` | error | 未知条目类型 |
| `T001` | error | 标题为空 |
| `T002` | error | 前缀与 kind 不匹配 |
| `T004` | error | 使用了已废弃的 `归类-` 前缀 |
| `T005` | error | `知识-` 条目缺少类别词 |
| `T006` | error | 类别词不在 `架构` / `方法` / `模型` / `原理` / `实验` / `数据集` 之内 |
| `T007` | error | 非 `知识-` 条目出现类别词 |
| `T008` | error | 名称段为空 |
| `T009` | warn | 名称段重复了类别词 |
| `T010` | error | 标题含书名号或方括号 |
| `T011` | warn | 中文与拉丁字母、数字之间缺少半角空格 |
| `T012` | warn | 名称段存在连续多余空格 |
| `T013` | error | 全角括号未成对闭合 |
| `T014` | warn | 标题含日期 |
| `T015` | warn | 疑似「A 与 B」式跨族合写标题 |
| `T016` | warn | 名称段夹带小写英文词 |
| `T017` | warn | 实验类条目未写明实验编号 |
| `T018` | error | 类别词要求的 `kind_marks` 标记缺失 |
| `T019` | error | title 与正文首个 H1 不一致 |

`T015` 采用较宽的启发式，对「知识-架构-注册表与扩展点」这类单一知识点的标题也会命中，实践中的误报率偏高，适宜人工复核后再决定是否改名。

## 提示模板

两个提示模板把常见流程固化成可直接注入会话的指令文本，用 `prompts/get` 获取。

- `kb-capture`：参数 `content`（必填）与 `kind`（可选）。引导「读约束 → 查重 → 确认项目 → 建档 → 复核」的沉淀流程。
- `kb-audit`：参数 `kind`（可选，留空为全部）。引导「体检 → 给出规范标题 → 用 `dry_run` 评估影响面 → 逐条改名 → 汇总合规率」的整改流程。

## 用脚本驱动服务

脱离 MCP 客户端做批量操作时，可以直接按 stdio 协议驱动本服务：从客户端注册表读出 `command` / `args` / `env` 原样拉起进程，然后依次发 `initialize`、`notifications/initialized`，再循环发 `tools/call`。这样批量脚本与客户端使用同一套配置，不会出现两处解释器或 `PYTHONPATH` 不一致。

```python
import json, os, subprocess

CFG = os.path.join(os.environ["APPDATA"], "TRAE SOLO CN", "User", "mcp.json")
with open(CFG, encoding="utf-8-sig") as f:
    ent = json.load(f)["mcpServers"]["engineering-research-workbench"]
argv = [ent["command"], *ent.get("args", [])]
env = {**os.environ, **(ent.get("env") or {})}

p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0, env=env)

def call(i, name, args):
    msg = {"jsonrpc": "2.0", "id": i, "method": "tools/call",
           "params": {"name": name, "arguments": args}}
    p.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
    p.stdin.flush()
    buf = b""
    while b"\n" not in buf:
        buf += os.read(p.stdout.fileno(), 65536)  # bufsize=0 时没有 read1
    return json.loads(buf.decode("utf-8"))
```

两个编码要点：`os.read` 直接读文件描述符，`bufsize=0` 下 `Popen.stdout` 是原始 `FileIO`，没有 `read1`；把输出落盘或打印时请保证 `PYTHONIOENCODING=utf-8`，否则中文会按控制台代码页编码而失败。

## 模块结构

| 文件 | 职责 |
| --- | --- |
| `server.py` | stdio 入口：协议握手、`tools` / `resources` / `prompts` 分发、`--selftest` |
| `protocol.py` | 传输层与 JSON Schema 助手（`s` / `i` / `b` / `arr` / `tool` / `ok` / `fail` / `resource`） |
| `constraints.py` | 全部约束的机器可读数据：目录骨架、六类矩阵、前缀与类别词、标记表、字段契约、红线 |
| `naming.py` | 命名规范实现：标题解析、校验、建议，H1 替换，交叉引用扫描与改写 |
| `bridge.py` | 桥接层：惰性加载 `app` 包并对 MCP 暴露单一门面 `Workbench` |
| `tools_knowledge.py` | 知识条目工具，8 个 |
| `tools_workspace.py` | 工作区、项目、待办、检索、图谱、索引工具，16 个 |
| `run_mcp.bat` | 命令行启动入口 |

## 常见问题

客户端里看不到工具。确认注册项写在 `%APPDATA%\TRAE SOLO CN\User\mcp.json` 的 `mcpServers` 下，然后重启客户端；工作区级的 `mcp.json` 不是用户级注册表，写在那里不会生效。

进程启动后立即退出。先在有 `PYTHONPATH` 的环境下跑 `python -m mcp.server --selftest`，退出码非 0 时按输出的 `problems` 定位；退出码为 0 说明服务本身正常，问题在客户端配置。

中文显示为乱码。确保 `PYTHONUTF8=1` 与 `PYTHONIOENCODING=utf-8` 都已注入；手工调试时同样需要设置，否则错误信息里的中文会触发编码异常。

写入被拒绝。返回体的 `validation.errors` 给出规则码与修正建议，按码查上面的规则表即可。确实需要越过校验时传 `allow_violation=true`，但这会在库里留下不合规标题。

工具返回 `[错误]` 文本。执行期异常被包装成 `isError=true` 的结果，正文第一行是错误摘要，其后是截断的 traceback。目标文件不存在会返回 `[错误] 目标不存在：…`。

索引与实际文件不一致。`ws_index_status` 看 `last_sync` 与计数，然后 `ws_reindex` 传 `confirm=true` 重建。索引只是派生数据，重建不会影响 Markdown。

## 维护基线

`python -m mcp.server --selftest` 输出 `25` 个工具、`9` 个资源、`2` 个提示模板、`problems` 为空，即为当前验收基线。工具表与实现分离在 `tools_knowledge.py` / `tools_workspace.py` 的 `TOOLS` 与 `HANDLERS` 两个结构中，自检会核对两者的配对关系与必填参数声明。
