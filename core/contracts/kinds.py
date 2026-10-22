"""权威契约 —— 知识库条目类型、标记、字段、关系与工作区骨架的**单一事实来源**。

历史上同一套规则有 3 处实现（``app/store.py``、``mcp/constraints.py``、``app/kb_naming.py``），
任一处更新另两处就漂移。v261009 起本模块是唯一声明处，其余位置一律从这里消费：

- ``app/store.py`` —— kind→目录/标签/状态机/日期字段/frontmatter 字段序/正文骨架/关系映射
- ``app/workspace.py`` —— 工作区与项目目录骨架
- ``core/contracts/naming.py`` —— 标题校验（规则码 T000–T022）与建议标题
- ``mcp/constraints.py`` —— 只是再导出本模块的门面，供 MCP 工具层使用

约束：本模块**纯数据 + 纯文本 + 纯函数**，不触碰磁盘，也不 import ``app`` / ``mcp``
（内核与工具层都要能安全 import 它）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

SERVER_NAME = "engineering-research-workbench"
SERVER_VERSION = "1.0.0"


def _read_expected_version() -> str:
    """从 VERSION 读取工作台版本，避免再抄一份会过期的常量。

    源码态是仓库根的 ``VERSION``；打包态（PyInstaller onefile）本模块在 PYZ 内，
    ``__file__`` 指向解压目录，而 ``VERSION`` 以 datas 形式落在同一解压目录根。
    """
    try:
        text = (Path(__file__).resolve().parents[2] / "VERSION").read_text(encoding="utf-8")
        return text.strip().lstrip("\ufeff")
    except OSError:
        return ""


WORKBENCH_VERSION_EXPECTED = _read_expected_version() or "v261010.1"

# ---------------------------------------------------------------- 工作区结构

WORKSPACE_LAYOUT: list[str] = [
    "Knowledge/Ideas",
    "Knowledge/Journals",
    "Knowledge/Notes",
    "Knowledge/Experiments",
    "Knowledge/Milestones",
    "Knowledge/Summaries",
    "Knowledge/Literature",
    "Knowledge/Literature/PDF",
    "Knowledge/Literature/Annotations",
    "Knowledge/Literature/Notes",
    "Knowledge/Literature/Index",
    "Knowledge/Literature/Previews",
    "Knowledge/Attachments",
    "Knowledge/Exports/KnowledgeBundles",
    "Knowledge/Exports/BibTeX",
    "Knowledge/Exports/KnowledgeTree",
    "Projects",
    "Resources",
    "System/Trash",
    "System/Cache",
    "System/AgentChats/Attachments",
    "System/AgentChats/Trash",
]

PROJECT_LAYOUT: list[str] = ["Notes", "Experiments", "Data", "Results", "Figures", "Manuscript", "References"]

SYSTEM_FILES: dict[str, str] = {
    "System/activity.jsonl": "追加型研究活动日志；UTF-8 无 BOM，每行一个 JSON 对象，禁止改写历史行",
    "System/todos.json": "待办清单，JSON 数组",
    "System/projects.json": "项目注册表，含稳定 project_id",
    "System/Trash/<kind>/": "删除条目的回收站，删除即改名为 <YYYYMMDDHHMMSS>-<原文件名> 后移入",
    "System/Trash/plugins/": "插件回收站（非 kind 命名空间）：插件卸载与单文件包升级时整体移入，见 PLUGIN_SPEC §2/§5",
    "System/Cache/": "派生索引（SQLite）缓存目录",
}

#: `System/Trash/` 下**非 kind** 的合法命名空间（按 PLUGIN_SPEC §2/§5 规定）。
#: doctor 的「回收站目录漂移」检查用 `KINDS + TRASH_EXTRA` 判定，避免把插件的回收站误报成漂移。
TRASH_EXTRA: tuple[str, ...] = ("plugins", "Literature", "Projects")

KNOWLEDGE_ROOT_RULE = (
    "知识条目的**唯一权威存放位置**是 `Workspace/Knowledge/<KindDir>/<id>.md`（扁平存放，不建子目录）；"
    "项目目录 `Workspace/Projects/<项目名>/` 只放该项目的实验数据、图表与稿件，不作为知识条目仓库。"
)

SOURCE_OF_TRUTH_RULE = (
    "Markdown + YAML frontmatter 是唯一事实来源；SQLite 索引与知识图谱均为**可重建的派生数据**。"
    "Agent 不得直接改写 System/Cache 下的索引文件，需要一致性时调用 `ws_reindex`。"
)

# ---------------------------------------------------------------- 条目类型

KIND_ORDER: list[str] = ["idea", "journal", "note", "experiment", "milestone", "summary", "literature"]

KINDS: dict[str, dict[str, Any]] = {
    "idea": {
        "dir": "Knowledge/Ideas",
        "label": "灵感",
        "prefix": "灵感-",
        "category_word": False,
        "statuses": ["待整理", "探索中", "已采纳", "已归档"],
        "date_field": None,
        "default_sections": ["想法", "为什么值得记录", "下一步"],
    },
    "journal": {
        "dir": "Knowledge/Journals",
        "label": "研究日志",
        "prefix": "日志-",
        "category_word": False,
        "statuses": ["记录", "复盘", "已归档"],
        "date_field": "record_date",
        "default_sections": ["今日进展", "关键发现", "问题与阻塞", "下一步"],
    },
    "note": {
        "dir": "Knowledge/Notes",
        "label": "笔记",
        "prefix": "知识-",
        "category_word": True,
        "statuses": ["草稿", "整理中", "稳定", "已归档"],
        "date_field": None,
        "default_sections": ["摘要", "正文", "关联"],
    },
    "milestone": {
        "dir": "Knowledge/Milestones",
        "label": "里程碑",
        "prefix": "里程碑-",
        "category_word": False,
        "statuses": ["计划", "进行中", "受阻", "完成"],
        "date_field": "due",
        "default_sections": ["目标", "验收条件", "进展记录"],
    },
    "experiment": {
        "dir": "Knowledge/Experiments",
        "label": "实验",
        "prefix": "实验-",
        "category_word": False,
        "required_marks": ["experiment"],  # 契约强制：实验条目固定带 ⚗ 标记
        "statuses": ["计划", "进行中", "完成", "受阻", "已归档"],
        "date_field": "record_date",
        "default_sections": [
            "摘要", "目标与假设", "配置与参数", "数据与口径", "结果", "结论与失效模式", "留档路径",
            "关联（依据的知识 / 用到的数据 / 同系列实验）",
        ],
    },
    "summary": {
        "dir": "Knowledge/Summaries",
        "label": "工作总结",
        "prefix": "总结-",
        "category_word": False,
        "statuses": ["草稿", "已定稿", "已归档"],
        "date_field": "record_date",
        "default_sections": ["本阶段完成", "结果与产出", "问题与经验", "下一阶段"],
    },
    "literature": {
        "dir": "Knowledge/Literature",
        "label": "文献",
        "prefix": "文献-",
        # 文献与专利同属文献内容：`prefixes` 声明全部合法前缀（T002 校验口径），主前缀仍为 `文献-`
        "prefixes": ["文献-", "专利-"],
        "category_word": False,
        "title_verbatim": True,  # 文献题名照抄原文（外文题名保留原样），不套用名称段「不夹小写英文词 / 不合写」两项规则
        "statuses": ["待阅读", "阅读中", "已精读", "已归档"],
        "date_field": "added_date",
        "default_sections": ["BibTeX", "核心结论", "方法与数据", "与当前研究的关系", "摘录与批注"],
    },
}

#: 新建条目的正文骨架（唯一声明处；``app/store._make_default_body`` 只做转发）。
#: 占位符 ``{title}`` 与 ``{bibtex}`` 用字面替换填充，因此模板里可以自由出现花括号。
BODY_TEMPLATES: dict[str, str] = {
    "idea": "# {title}\n\n## 想法\n\n\n## 为什么值得记录\n\n\n## 下一步\n\n- [ ] \n",
    "journal": (
        "# {title}\n\n## 今日进展\n\n\n## 关键发现\n\n\n## 问题与阻塞\n\n\n## 下一步\n\n- [ ] \n"
    ),
    "note": "# {title}\n\n## 摘要\n\n\n## 正文\n\n\n## 关联\n\n",
    "milestone": "# {title}\n\n## 目标\n\n\n## 验收条件\n\n- [ ] \n\n## 进展记录\n\n",
    "summary": (
        "# {title}\n\n## 本阶段完成\n\n\n## 结果与产出\n\n\n## 问题与经验\n\n\n## 下一阶段\n\n- [ ] \n"
    ),
    "literature": (
        "# {title}\n\n"
        "## BibTeX\n\n"
        "```bibtex\n{bibtex}\n```\n\n"
        "## 核心结论\n\n\n"
        "## 方法与数据\n\n\n"
        "## 与当前研究的关系\n\n\n"
        "## 摘录与批注\n\n"
    ),
    "experiment": (
        "# {title}\n\n"
        "## 摘要\n\n\n"
        "## 目标与假设\n\n\n"
        "## 配置与参数\n\n\n"
        "## 数据与口径\n\n\n"
        "## 结果\n\n\n"
        "## 结论与失效模式\n\n\n"
        "## 留档路径\n\n\n"
        "## 关联\n\n"
        "### 依据的知识\n\n\n"
        "### 用到的数据\n\n\n"
        "### 同系列实验\n\n\n"
    ),
    "_default": "# {title}\n\n## 要点\n\n\n## 正文\n\n\n## 关联\n\n",
}

DEFAULT_BIBTEX = "@article{cite_key,\n  title = {},\n  author = {},\n  year = {}\n}"


def default_body(kind: str, title: str, payload: dict[str, Any] | None = None) -> str:
    """按契约生成新条目的正文骨架（与旧 ``store._make_default_body`` 输出逐字一致）。"""
    template = BODY_TEMPLATES.get(str(kind)) or BODY_TEMPLATES["_default"]
    body = template.replace("{title}", str(title))
    if "{bibtex}" in body:
        raw = (payload or {}).get("bibtex") or DEFAULT_BIBTEX
        body = body.replace("{bibtex}", str(raw).strip())
    return body


KIND_CHOICE_HINT = (
    "选型口径：一次可复现的做法/策略 → note+方法；可被建模或训练的对象 → note+模型；"
    "机理与指标口径 → note+原理；分层与接口契约 → note+架构；数据集本身及选型 → note+数据集；"
    "**一次具体实验记录 → experiment（`实验-` 前缀，名称须带编号）**；未成形的念头 → idea；"
    "当日流水 → journal；阶段收口 → summary；有验收条件的节点 → milestone；外部文献 → literature。"
    "跨项目通用的基础知识照常按 note 建，但**不挂项目归属**（projects 留空）并打 `通用基础` 标签。"
)

# ---------------------------------------------------------------- 命名规范

PREFIX_RULE = "标题结构固定为 `<前缀>-<类别>-<名称>`；`类别` 仅 `知识-`（note）条目使用，且**有且仅有一个**。"

CATEGORY_WORDS: list[dict[str, str]] = [
    {"word": "架构", "mark": "architecture", "icon": "▤", "criteria": "代码/系统的分层、边界、接口契约与扩展点"},
    {"word": "方法", "mark": "method", "icon": "⚒", "criteria": "可复现的算法、求解方法、技术手段、策略"},
    {"word": "模型", "mark": "model", "icon": "⬡", "criteria": "可建模对象：物理动力学模型、参数化抽象、可训练网络"},
    {"word": "原理", "mark": "principle", "icon": "∑", "criteria": "机理、口径、度量与基础认识"},
    {"word": "数据集", "mark": "data", "icon": "⊞", "criteria": "数据集本身及其选型"},
]

# v261008.2 · `实验` 类别词已升格为独立类型 `experiment`（`实验-` 前缀）。
# 它不再出现在类别词表里：类别词只服务 `知识-`（note）条目，实验用 kind 区分。
# 实验条目的 `kind_marks` 固定含 `experiment`，由写入工具自动补齐。

CATEGORY_WORD_ALIASES: dict[str, str] = {
    "归类": "知识",  # 历史上的 `归类-` 前缀已废弃，归并到 `知识-<类别>-`
}

MARK_IDS: list[dict[str, str]] = [
    {"id": "knowledge", "icon": "◈", "label": "知识", "color": "#2a9d8f"},
    {"id": "synthesis", "icon": "◎", "label": "归类", "color": "#6b7fd7"},
    {"id": "method", "icon": "⚒", "label": "方法", "color": "#e76f51"},
    {"id": "question", "icon": "？", "label": "问题", "color": "#d1495b"},
    {"id": "thinking", "icon": "✦", "label": "思路", "color": "#f4a261"},
    {"id": "architecture", "icon": "▤", "label": "架构", "color": "#4a6fa5"},
    {"id": "experiment", "icon": "⚗", "label": "实验", "color": "#d1569a"},
    {"id": "data", "icon": "⊞", "label": "数据", "color": "#2d7dd2"},
    {"id": "model", "icon": "⬡", "label": "模型", "color": "#8e6fbf"},
    {"id": "principle", "icon": "∑", "label": "原理", "color": "#7a8b3a"},
]

#: 每个内置标记的一句话用途（设置页「内置模板」卡片显示，帮助判断该不该加）。
MARK_TEMPLATE_HINTS: dict[str, str] = {
    "knowledge": "术语、概念与机制",
    "synthesis": "跨族归并与索引",
    "method": "算法、流程与操作口径",
    "question": "待解疑问与风险",
    "thinking": "猜想、方案与思路",
    "architecture": "结构设计与模块边界",
    "experiment": "实验记录与结论",
    "data": "数据集与选型",
    "model": "模型、训练与推理设置",
    "principle": "原理、度量与数学基础",
}

#: 默认启用的三个标记；其余内置模板在「设置 → 知识条目 → 分类标记」按需添加。
MARK_DEFAULT_IDS: list[str] = ["knowledge", "method", "experiment"]

#: 分类标记总数上限（配置清洗、前端与校验共用同一口径）。
MARK_LIMIT = 24

# 实验编号体系（`<阶段序号>.<序号>`）仅适用于有编号规范的课题（红外暗弱探测）；
# 以下项目无编号规范，豁免 T017「实验类条目未写明实验编号」告警。
EXPERIMENT_NUMBER_EXEMPT_PROJECTS: list[str] = [
    "proj_cd25f2144562",  # GEO高轨道多对一博弈
    "GEO高轨道多对一博弈",
]

# ---------------------------------------------------------------- 标题长度上限（v261008.2h）

#: 非文献条目标题显示宽度的硬上限（半角当量：1 汉字 = 2，1 拉丁字符/数字 = 1）
TITLE_WIDTH_LIMIT = 60

#: 各类型的建议宽度上限（warn 级）。阈值按全库长尾分布定：单主题类取 P90 附近，
#: `日志`/`总结`/`里程碑` 承载当日多事件与验收条件，放宽到 56（仍受 60 硬顶约束）。
TITLE_WIDTH_WARN: dict[str, int] = {
    "idea": 44, "note": 44, "experiment": 44, "milestone": 56, "journal": 56, "summary": 56,
}

TITLE_WIDTH_RULE = (
    "标题长度以**显示宽度**计（1 个汉字 = 2，1 个拉丁字符/数字/半角符号 = 1，按 Unicode East Asian Width）："
    "非文献条目标题**硬上限 60**（≈30 汉字，`T021` error）；建议**单主题类**（`知识-`/`实验-`/`灵感-`）≤ **44**（≈22 汉字）、"
    "**流水与收口类**（`日志-`/`总结-`/`里程碑-`）≤ **56**（≈28 汉字，因承载当日多事件而放宽，`T022` warn）。"
    "超长时把限定语、适用范围与并列项移入正文摘要或 `tags`，标题只保留「是什么（+ 编号）」；"
    "末尾全角括号里的编号、版本、维度缩写不计入补救范围。`文献-` 题名照抄原文，**豁免长度上限**（列表侧以两行截断控制观感）。"
)

NAME_SEGMENT_RULES: list[str] = [
    "名称段**不得重复类别词**（原「…对比实验」归为实验类后写作 `知识-实验-…对比`）。",
    "名称段内部保留原有缩写、代号与括号补充（如 `U-Net`、`4.2b`、`多对一 vs 一对一`）。",
    "中文与拉丁字母/数字之间保留半角空格；不使用书名号《》、方括号 []。",
    "禁止「A 与 B」式的跨族合写标题（一篇只讲一个知识点或一个族）。"
    "`知识-` 条目已用类别词声明唯一族、文献（`title_verbatim`）题名照抄原文，二者均不再提示。",
    "非 `知识-` 类条目的名称段同样**只用中文术语**：不夹小写英文词（`report` → `报告`）；"
    "凡涉及实验须补全实验名（「实验 4.1」→「星点质心算法对比 4.1」）；多事件用 `、` 分隔并按当日顺序排列。"
    "**外文文献题名保留原文，属该规则唯一豁免。**",
    "日志类条目标题**不写日期**：日期由 `record_date` 与 `id` 承载，标题只写「当天做了什么」。",
    "实验类条目（`experiment`）须在名称段写明实验内容与编号，编号可用**全角括号**补充"
    "（如 `实验-质心算法对比（4.1）`）；无编号规范的课题（见 `EXPERIMENT_NUMBER_EXEMPT_PROJECTS`）豁免此项。",
    TITLE_WIDTH_RULE,
]

SYNC_RULES: list[str] = [
    "`title` 与正文首个 H1 必须**完全一致**。",
    "改名**不得**改动 `id` 与 `created`；须刷新 `updated`。",
    "须同步更新全库中按旧标题互相引用的位置（「关联」小节、正文行内引用、项目 README）。",
    "须向 `Workspace/System/activity.jsonl` 追加 `doc_update` 事件（UTF-8 **无 BOM**，沿用现有换行风格，"
    "勿另插空行、勿重复追加同一事件）。",
    "类别词与 `kind_marks` 一一对应：`模型` 类条目**不再**沿用 `method` 标记，改用 `model`。",
]

FORBIDDEN_TITLE_CHARS: list[str] = ["《", "》", "[", "]"]

# ---------------------------------------------------------------- 字段契约

FRONTMATTER_ORDER: list[str] = [
    "id", "kind", "title", "created", "updated", "status", "project", "projects", "tags", "kind_marks",
    "project_id", "project_ids",
    "variant_of", "variant_label", "origin_surface", "origin_tool", "origin_client", "origin_at",
    "record_date", "due", "added_date", "summary_type", "pinned", "authors", "year", "venue", "doi", "url", "cite_key",
    "start_date", "progress",
    "has_variants",
    "variant_at",
]

#: 版本/分支与来源追踪字段（v261009.41）：由内核写入，也允许界面/工具显式设置
VARIANT_FIELDS: list[str] = ["variant_of", "variant_label", "has_variants", "variant_at"]
#: variant_at：这条分支**创建的时间**（ISO），由内核在开分支时写入
#: has_variants：基条上的 O(1) 标记（族里还有活版本时为 true），由内核在分叉/归档时维护
ORIGIN_FIELDS: list[str] = ["origin_surface", "origin_tool", "origin_client", "origin_at"]
#: origin_surface 的取值（谁写入了这条内容）
ORIGIN_SURFACES: list[str] = ["ui", "agent", "mcp", "plugin", "cli"]

IMMUTABLE_FIELDS: list[str] = ["id", "kind", "created"]

CREATE_FIELDS: list[str] = [
    "title", "status", "project", "projects", "tags", "kind_marks", "pinned", "body",
    "project_id", "project_ids",
    "record_date", "due", "added_date", "summary_type", "authors", "year", "venue", "doi", "url", "cite_key",
    "start_date", "progress",
    "variant_of", "variant_label", "origin_surface", "origin_tool", "origin_client", "origin_at",
    "has_variants",
    "variant_at",
]

UPDATE_FIELDS: list[str] = [
    "title", "status", "project", "projects", "tags", "kind_marks", "pinned", "body",
    "project_id", "project_ids",
    "record_date", "due", "added_date", "summary_type", "authors", "year", "venue", "doi", "url", "cite_key",
    "start_date", "progress",
    "attachment",
    "variant_of", "variant_label", "origin_surface", "origin_tool", "origin_client", "origin_at",
    "has_variants",
    "variant_at",
]

DATE_FIELD_RULE = (
    "日期字段按类型固定：journal/summary/experiment → `record_date`（experiment 为执行日期）；"
    "milestone → `due`；literature → `added_date`；idea/note 无日期字段。"
    "日期一律 `YYYY-MM-DD`，不得写进标题。"
)

RELATION_RULE = (
    "显式关系用 WikiLink 写在正文的**「关联」小节**，由小节标题或行内标签决定关系类型"
    "（`### 依据的知识` → uses-knowledge、`### 用到的数据` → uses-data、`### 引用文献` → cites、"
    "`### 同系列实验` → series、`### 上一环节`/`### 下一环节` → chain-prev/chain-next、"
    "`### 产出与汇总` → produces）；未命中的链接一律记为 `wikilink`。"
    "链接可写 `[[<id>]]` 或 `[[<标题>]]`（推荐 id，改名不断链）。"
    "**不要手写 `relations` 字段**；标签用 `tags`，项目归属用 `project`（首个）与 `projects`（全集），"
    "跨项目通用知识留空 `projects` 并打 `通用基础` 标签。"
    "关系层的实现单一事实来源是 `app/store.py` 的 `RELATION_SECTIONS` / `RELATION_LABELS`。"
)

# ---------------------------------------------------------------- 关系层清单（v261008.2）

RELATION_MATRIX: list[dict[str, str]] = [
    {"id": "uses-knowledge", "label": "依据知识", "section": "依据的知识（或行内「方法条目/原理条目/知识条目/依据」）",
     "meaning": "本条目的结论/做法建立在哪条知识上"},
    {"id": "uses-data", "label": "使用数据", "section": "用到的数据（或行内「数据/数据集」）",
     "meaning": "本条目的数据来自哪个数据集或哪批产物"},
    {"id": "cites", "label": "引用文献", "section": "引用文献（或行内「文献/引用」）",
     "meaning": "依据或对照的外部文献"},
    {"id": "series", "label": "同系列", "section": "同系列实验",
     "meaning": "同一系列（同一课题线/同一阶段线）的其他实验"},
    {"id": "chain-prev", "label": "上一环节", "section": "上一环节（或行内「上一步/前置」）",
     "meaning": "上游环节，构成实验链条"},
    {"id": "chain-next", "label": "下一环节", "section": "下一环节（或行内「下一步/后续」）",
     "meaning": "下游环节，构成实验链条"},
    {"id": "produces", "label": "产出汇总", "section": "产出与汇总（或行内「汇总/全链汇总/报告」）",
     "meaning": "本条目归集到的总结、里程碑或汇总条目"},
    {"id": "wikilink", "label": "显式引用", "section": "其余任何位置",
     "meaning": "未分类的显式引用（保底类型，向后兼容）"},
]

DOC_ID_RULE = (
    "条目 id 形如 `{kind}-{%Y%m%d%H%M%S}-{hex6}`，由系统生成，全库唯一；"
    "文件名即 `<id>.md`。Agent **不得**自行编造或修改 id。"
)

# ---------------------------------------------------------------- 目录索引

TOPICS: dict[str, str] = {
    "storage": "知识库存放规则：目录结构、条目位置、事实来源、系统文件语义",
    "naming": "标题命名规范全文：前缀、类别词、名称段规则",
    "sync": "改名同步要求：title/H1 一致、id/created 不变、交叉引用与 activity 事件",
    "kinds": "七类条目矩阵：目录、前缀、状态机、日期字段、默认正文骨架",
    "schema": "frontmatter 字段契约：字段序、可变/不可变、日期字段、关系与标签",
    "marks": "kind_marks 标记表与类别词映射",
    "relations": "关系层：关联段小标题 → 关系类型（依据知识/使用数据/引用文献/同系列/环节链/产出汇总）",
    "playbook": "Agent 操作手册：标准作业流程与红线",
}

# ---------------------------------------------------------------- 关系层映射
# 正文「关联」小节的标题或行内标签决定关系类型；都不命中退化为 RELATION_GENERIC。
# 与 RELATION_MATRIX 是同一份口径的两种视图（矩阵给人看，映射给解析器用）。

RELATION_GENERIC = "wikilink"

RELATION_SECTIONS: dict[str, str] = {
    "依据的知识": "uses-knowledge",
    "用到的知识": "uses-knowledge",
    "用到的数据": "uses-data",
    "引用文献": "cites",
    "同系列实验": "series",
    "上一环节": "chain-prev",
    "下一环节": "chain-next",
    "产出与汇总": "produces",
}

RELATION_LABELS: dict[str, str] = {
    "方法条目": "uses-knowledge",
    "原理条目": "uses-knowledge",
    "模型条目": "uses-knowledge",
    "架构条目": "uses-knowledge",
    "知识条目": "uses-knowledge",
    "依据的知识": "uses-knowledge",
    "用到的知识": "uses-knowledge",
    "依据": "uses-knowledge",
    "参照": "uses-knowledge",
    "数据": "uses-data",
    "数据集": "uses-data",
    "用到的数据": "uses-data",
    "文献": "cites",
    "引用文献": "cites",
    "引用": "cites",
    "同系列": "series",
    "同系列实验": "series",
    "系列": "series",
    "上一环节": "chain-prev",
    "上一步": "chain-prev",
    "前置": "chain-prev",
    "下一环节": "chain-next",
    "下一步": "chain-next",
    "后续": "chain-next",
    "产出": "produces",
    "产出与汇总": "produces",
    "汇总": "produces",
    "全链汇总": "produces",
    "报告": "produces",
}

#: 关系类型 → 显示名（前端图谱筛选、导出与文档共用同一份口径）
RELATION_LABELS_DISPLAY: list[tuple[str, str]] = [
    ("uses-knowledge", "依据知识"),
    ("uses-data", "使用数据"),
    ("cites", "引用文献"),
    ("series", "同系列"),
    ("chain-prev", "上一环节"),
    ("chain-next", "下一环节"),
    ("produces", "产出汇总"),
    ("wikilink", "显式引用"),
]

# ---------------------------------------------------------------- 派生视图（消费方一律取这里）

KIND_DIRS: dict[str, str] = {k: str(v["dir"]) for k, v in KINDS.items()}
KIND_LABELS: dict[str, str] = {k: str(v["label"]) for k, v in KINDS.items()}
DATE_FIELDS: dict[str, str] = {k: str(v["date_field"]) for k, v in KINDS.items() if v.get("date_field")}


def kind_dir_map() -> dict[str, str]:
    return dict(KIND_DIRS)


def kind_label_map() -> dict[str, str]:
    return dict(KIND_LABELS)


def kind_statuses(kind: str) -> list[str]:
    return [str(x) for x in (KINDS.get(kind, {}).get("statuses") or [])]


def all_statuses() -> dict[str, list[str]]:
    return {k: [str(x) for x in (v.get("statuses") or [])] for k, v in KINDS.items()}


def required_marks(kind: str) -> list[str]:
    """契约强制该类型必须携带的 kind_marks（如 experiment 固定带 ⚗）。"""
    return [str(x) for x in (KINDS.get(kind, {}).get("required_marks") or [])]
