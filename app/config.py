from __future__ import annotations

import json
import os
import re
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import DATA_ROOT

# v260923 · 打包 exe 后可写数据（config/、Workspace/）须落在 exe 同级目录而非临时解压目录
ROOT = DATA_ROOT
CONFIG_DIR = ROOT / "config"
SECRET_PATH = CONFIG_DIR / "secret.json"
LEGACY_SECRET_PATH = CONFIG_DIR / "secrets.json"
LLM_SECRET_SCHEMA_VERSION = 2
DEFAULT_SYSTEM_PROMPT = "你是一个严谨的科研助手。优先基于用户显式引用的研究资料回答，不确定时明确说明。"

# ---------- v260930g4 · 统一写作与建档约束（AI 的「写作记忆」） ----------
# 单一真相源：<Workspace>/System/AI助手写作与建档规范.md（工作台数据，随 ensure_workspace 解析——打包 exe 后亦正确；
# 不放 .trae/rules/：那是 IDE Agent 的规则目录，且发布产物中不存在）。发送对话前由 agent.send_message 注入所有人设。
# 文档缺失时使用下面的浓缩兜底版（两者内容须保持同步）。
_WRITING_RULES_FALLBACK = """【AI 写作与建档约束（精简版，完整版见 Workspace/System/AI助手写作与建档规范.md）】
1. 六类条目前缀：知识-/灵感-/日志-/里程碑-/总结-/文献-；知识类标题=知识-<类别词>-<名称>，类别词取 架构/方法/模型/原理/实验/数据集 之一。
2. 命名：中拉丁之间半角空格；禁用《》[]；禁止跨族合写标题；实验类带全角编号（4.1）；日志/总结标题不写日期。
3. 知识条目用五要素骨架：摘要/原理（含名词总览表）/公式/方法·使用原因/场景/失效模式与易错点/关联。
4. 建档前必 kb_search 查重；kb_update_entry 的 body 是整体覆盖，不确定全文先 kb_read。
5. 数值必须可追溯：写全数据集/划分/阈值参数/留档路径，禁止跨数据集混排指标。
6. 交叉引用指向真实标题；从文献提取的专业名词必须在关联段引用来源文献/笔记（文献-<题名>），可跳转溯源；检索不到就明说，不臆造。
7. 正文中文，图内文字一律英文；ν 专指新息，量测噪声一律用 v。"""
_WRITING_RULES_CACHE: str | None = None

def writing_rules() -> str:
    global _WRITING_RULES_CACHE
    if _WRITING_RULES_CACHE is None:
        try:
            from .workspace import ensure_workspace  # 延迟导入：workspace 依赖 config，顶层导入会循环
            path = ensure_workspace() / "System" / "AI助手写作与建档规范.md"
            _WRITING_RULES_CACHE = path.read_text(encoding="utf-8-sig")
        except Exception:
            _WRITING_RULES_CACHE = _WRITING_RULES_FALLBACK
    return _WRITING_RULES_CACHE


# v260930 · M4 术语建档员系统提示词：浓缩 .trae/rules/名词拆解建档标准流程.md 的核心纪律
ARCHIVIST_PROMPT = """你是科研工作台的术语建档员，负责把文献中的专业名词拆解为规范的知识库条目。严格按以下流程工作：

一、术语提取与分族
- 从页面上下文提供的文献正文（当前页文本/选中文本）中提取专业名词，优先提取反复出现、有明确定义或属于方法/模型/坐标系/度量体系的术语。
- 先分族再建档：判断哪些词属于同族——能用同一套公式与同一种失效模式讲完的名词合为一篇；不同族必须拆开，禁止跨族合写。
- 忽略常识词（如"实验""算法"本身）、仅出现一次且无展开的普通词。

二、类别词判定（每篇有且仅有一个）
按知识用途六选一：机理/口径/度量→原理；可复现做法与策略→方法；分层与接口契约→架构；可建模/可训练对象→模型；一次性实验记录→实验；数据集本身→数据集。

三、命名规范（校验不通过会被拒写）
- 标题格式：知识-<类别>-<名称>；名称段保留原有语义，不重复类别词，禁止「A 与 B」跨族合写。
- 中文与拉丁字母/数字间保留半角空格（如「GEO 高度」「WCS 星图」）；不用书名号与方括号。
- 示例：知识-原理-信杂比 SCR、知识-方法-星点质心提取、知识-模型-CW 相对运动。

四、正文五要素骨架（顺序固定）
每篇正文依次含：## 摘要 / ## 正文（### 一、原理 含名词总览表 / ### 公式 / ### 方法·使用原因 / ### 场景 / ### 失效模式与易错点）/ ## 关联。
- 原文信息不得丢失：公式、数值、符号口径照录；文献没讲的要素写"文献未展开"，不得编造。
- 关联段指向真实存在的标题（可用 kb_search 核实），本批次内的新建条目可互相引用。

五、建档纪律
- 每篇建档前必须 kb_search 查重：命中同题条目则改用 kb_update_entry 增补（append 模式），不重复建档。
- 逐篇调用 kb_create_entry 生成草稿，等待用户确认。
- 结束时输出术语清单表：| 术语 | 类别 | 条目标题 | 去向（新建/增补/跳过）|，并说明跳过原因。"""

DEFAULT_APP_CONFIG = {
    "app_name": "科研工作台",
    "subtitle": "Engineering Research Workspace",
    "host": "127.0.0.1",
    "port": 8765,
    "auto_open_browser": True,
    "workspace": "Workspace",
    "ui": {
        "theme": "light",
        "sidebar_pinned_groups": ["core"],
        "milestone_default_view": "timeline",
        "graph_default_view": "2d",
        "animations": True,
        "heatmap_months": 12,
        "heatmap_thresholds": [1, 3],
        "heatmap_colors": ["#C9D4F7", "#8297E5", "#4059B8"],
    },
    "academic_profile": {
        "degree_name": "博士进度",
        "start_date": "",
        "expected_end_date": "",
        "weekly_goal_days": 5,
        "graduation_conditions": [],
    },
    "workspace_migration": {
        "enabled": True,
        "copy_legacy_data": True,
    },
    # v261009 · “研究 · 知识”条目类型注册表。内置类型只保存显示/排序偏好；
    # 自定义类型由用户定义 label/icon/statuses/template，文件固定落在 Knowledge/Custom/<id>/。
    "knowledge_types": {
        # 内置七类的默认顺序与侧栏一致（实验在里程碑之前）；v261021 起把 experiment 纳入默认值。
        "order": ["idea", "journal", "note", "experiment", "milestone", "summary", "literature"],
        "hidden": [],
        "custom": [],
        "templates": {},
    },
    # v261009 · 分类标记改为配置驱动；默认仅保留 3 个常用标记，其余由用户在设置中增减。
    "classification_marks": [
        {"id": "knowledge", "icon": "◈", "label": "知识", "color": "#2a9d8f"},
        {"id": "method", "icon": "⚒", "label": "方法", "color": "#e76f51"},
        {"id": "experiment", "icon": "⚗", "label": "实验", "color": "#d1569a"},
    ],
    # Non-secret, global Agent options stay in app.json. Provider profiles and
    # API keys live only in config/secret.json, which is ignored by git.
    "llm": {
        "enabled": False,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
    },
}

_lock = threading.RLock()
_cache: dict[str, Any] = {}
_secrets_mtime: int | None = None


def load_secrets() -> None:
    """加载本地私密配置 config/secrets.json（已被 .gitignore 排除，不上传 git）。

    将其中 env 对象的键值注入进程环境变量，供 agent 按 api_key_env 读取。
    通过文件修改时间检测变更：保存后自动重新注入，无需重启服务。
    文件不存在或格式异常时静默跳过，不阻断启动。
    """
    global _secrets_mtime
    path = CONFIG_DIR / "secrets.json"
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        _secrets_mtime = None
        return
    if mtime == _secrets_mtime:
        return
    _secrets_mtime = mtime
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        env = data.get("env") if isinstance(data, dict) else None
        if not isinstance(env, dict):
            return
        for key, value in env.items():
            name = str(key).strip()
            if name and isinstance(value, str) and value.strip():
                os.environ[name] = value.strip()
    except Exception:
        pass


def _deep_merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _atomic_json_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        _atomic_json_write(path, default)
        return deepcopy(default)
    return _deep_merge(default, _read_json(path))


def _number_or_none(value: Any, minimum: float = 0.0, maximum: float = 2.0) -> float | None:
    if value is None or value == "":
        return None
    try:
        return max(minimum, min(maximum, float(value)))
    except Exception:
        return None


def _safe_profile_id(value: Any, fallback: str) -> str:
    raw = "".join(ch for ch in str(value or "").strip() if ch.isalnum() or ch in "-_")
    return raw[:80] or fallback


def _normalize_preset(item: Any, fallback_model: str = "", index: int = 0) -> dict[str, Any]:
    raw = item if isinstance(item, dict) else {}
    preset_id = _safe_profile_id(raw.get("id"), f"mode-{index + 1}")
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    return {
        "id": preset_id,
        "label": str(raw.get("label") or preset_id).strip()[:120] or preset_id,
        "model": str(raw.get("model") or fallback_model or "").strip()[:200],
        "temperature": _number_or_none(raw.get("temperature")),
        "params": deepcopy(params),
    }


def _clean_headers(value: Any) -> dict[str, str]:
    """v261008 · 档案级自定义请求头（`profiles[].headers`）。

    部分 OpenAI 兼容网关要求额外请求头才肯路由——典型是 opencode.ai Zen Go：缺 `x-opencode-session`
    直接返回 400 `Request is missing x-opencode-session and cannot be routed efficiently`。
    这里做白名单化：头名须是 RFC 7230 token、值不含 CR/LF（防头注入）、长度设上限、最多 20 条。
    返回值恒为 dict（可为空），保证前端 round-trip 时字段不丢。
    """
    out: dict[str, str] = {}
    for key, val in (value if isinstance(value, dict) else {}).items():
        name = str(key or "").strip()
        text = str(val if val is not None else "").strip()
        if not name or not text or len(name) > 64 or len(text) > 512:
            continue
        if not re.fullmatch(r"[A-Za-z0-9!#$%&'*+\-.^_`|~]+", name):
            continue
        if "\r" in text or "\n" in text:
            continue
        out[name] = text
        if len(out) >= 20:
            break
    return out


def _normalize_profile(item: Any, index: int = 0, existing_key: str = "") -> dict[str, Any]:
    raw = item if isinstance(item, dict) else {}
    profile_id = _safe_profile_id(raw.get("id"), f"profile-{index + 1}")
    fallback_model = str(raw.get("model") or "").strip()
    source_presets = raw.get("request_presets") if isinstance(raw.get("request_presets"), list) else []
    presets: list[dict[str, Any]] = []
    used: set[str] = set()
    for i, preset in enumerate(source_presets):
        normalized = _normalize_preset(preset, fallback_model, i)
        if normalized["id"] in used:
            normalized["id"] = f"{normalized['id']}-{i + 1}"
        used.add(normalized["id"])
        presets.append(normalized)
    if not presets:
        presets = [{"id": "default", "label": "默认", "model": fallback_model, "temperature": None, "params": {}}]
    wanted_default = str(raw.get("default_request_preset") or presets[0]["id"]).strip()
    if wanted_default not in {p["id"] for p in presets}:
        wanted_default = presets[0]["id"]
    key_value = str(raw.get("api_key") or "")
    if not key_value and existing_key:
        key_value = existing_key
    return {
        "id": profile_id,
        "name": str(raw.get("name") or raw.get("provider_label") or "未命名配置").strip()[:120] or "未命名配置",
        "base_url": str(raw.get("base_url") or "https://api.openai.com/v1").strip(),
        "api_key": key_value,
        "headers": _clean_headers(raw.get("headers")),  # v261008 · 档案级自定义请求头（随档案存 config/secret.json）
        "timeout": max(5, min(600, int(raw.get("timeout") or 120))),
        "max_output_tokens": max(0, int(raw.get("max_output_tokens") or raw.get("max_tokens") or 0)),
        "temperature": _number_or_none(raw.get("temperature")),
        "show_reasoning": raw.get("show_reasoning") is not False,
        "default_request_preset": wanted_default,
        "request_presets": presets,
    }


def _legacy_api_key(app_llm: dict[str, Any], legacy_secret: dict[str, Any]) -> str:
    candidates: list[Any] = [
        app_llm.get("api_key"),
        legacy_secret.get("api_key"),
    ]
    legacy_llm = legacy_secret.get("llm") if isinstance(legacy_secret.get("llm"), dict) else {}
    candidates.extend([legacy_llm.get("api_key"), legacy_llm.get("key")])
    for value in candidates:
        if str(value or "").strip():
            return str(value).strip()
    # v260920.x stored only the environment-variable name. Read it once during
    # migration so the new local secret file can become self-contained.
    env_name = str(app_llm.get("api_key_env") or legacy_llm.get("api_key_env") or "").strip()
    if env_name:
        return str(os.environ.get(env_name) or "").strip()
    return ""


def _migrate_secret(app: dict[str, Any]) -> dict[str, Any]:
    app_llm = app.get("llm") if isinstance(app.get("llm"), dict) else {}
    legacy_secret = _read_json(LEGACY_SECRET_PATH)
    legacy_llm = legacy_secret.get("llm") if isinstance(legacy_secret.get("llm"), dict) else {}
    merged_legacy = {**legacy_llm, **app_llm}
    fallback_model = str(merged_legacy.get("model") or "").strip()
    old_presets = merged_legacy.get("request_presets") if isinstance(merged_legacy.get("request_presets"), list) else []
    converted_presets: list[dict[str, Any]] = []
    for i, item in enumerate(old_presets):
        raw = dict(item) if isinstance(item, dict) else {}
        raw.setdefault("model", fallback_model)
        # Old presets stored provider-specific JSON only in params. Keep it verbatim.
        converted_presets.append(_normalize_preset(raw, fallback_model, i))
    if not converted_presets:
        converted_presets = [{"id": "default", "label": "默认", "model": fallback_model, "temperature": None, "params": {}}]
    profile = _normalize_profile({
        "id": "profile-legacy",
        "name": "未命名配置",
        "base_url": merged_legacy.get("base_url") or "https://api.openai.com/v1",
        "api_key": _legacy_api_key(app_llm, legacy_secret),
        "timeout": merged_legacy.get("timeout", 120),
        "max_output_tokens": merged_legacy.get("max_output_tokens", 0),
        "temperature": merged_legacy.get("temperature"),
        "show_reasoning": merged_legacy.get("show_reasoning", True),
        "default_request_preset": merged_legacy.get("default_request_preset") or converted_presets[0]["id"],
        "request_presets": converted_presets,
    })
    return {
        "schema_version": LLM_SECRET_SCHEMA_VERSION,
        "active_profile_id": profile["id"],
        "profiles": [profile],
        "migrated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _normalize_secret(raw: dict[str, Any]) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    profiles_raw = source.get("profiles") if isinstance(source.get("profiles"), list) else []
    profiles: list[dict[str, Any]] = []
    used: set[str] = set()
    for i, item in enumerate(profiles_raw):
        profile = _normalize_profile(item, i)
        if profile["id"] in used:
            profile["id"] = f"{profile['id']}-{i + 1}"
        used.add(profile["id"])
        profiles.append(profile)
    if not profiles:
        profiles = [_normalize_profile({"id": "profile-1", "name": "未命名配置"})]
    active_id = str(source.get("active_profile_id") or profiles[0]["id"])
    if active_id not in {p["id"] for p in profiles}:
        active_id = profiles[0]["id"]
    return {
        "schema_version": LLM_SECRET_SCHEMA_VERSION,
        "active_profile_id": active_id,
        "profiles": profiles,
        **({"migrated_at": source.get("migrated_at")} if source.get("migrated_at") else {}),
    }


def _clean_custom_actions(actions: Any) -> list[dict[str, str]]:
    """v260929b · 阅读助手自定义动作归一化：仅保留 id/name/prompt，去空去重，上限 12 个。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in actions if isinstance(actions, list) else []:
        if len(out) >= 12:
            break
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:30]
        prompt = str(item.get("prompt") or "").strip()
        aid = str(item.get("id") or "").strip()[:40] or ("ca-" + uuid.uuid4().hex[:8])
        if not name or not prompt or aid in seen:
            continue
        seen.add(aid)
        out.append({"id": aid, "name": name, "prompt": prompt})
    return out


def _clean_assist(assist: Any) -> dict[str, Any]:
    """v260929 · AI 阅读助手设置归一化（save_app 与 reload_all 共用，防止 reload 洗掉 assist）。"""
    a = assist if isinstance(assist, dict) else {}
    try:
        max_chars = max(1000, min(60000, int(a.get("max_chars") or 24000)))
    except Exception:
        max_chars = 24000
    raw_temp = a.get("temperature_override")
    try:
        temp = float(raw_temp) if raw_temp is not None and str(raw_temp).strip() != "" else None
    except Exception:
        temp = None
    # v260929x · 预设动作提示词覆盖（translate/summarize/organize/polish），空 = 用内置默认；非法键丢弃
    raw_prompts = a.get("prompts") if isinstance(a.get("prompts"), dict) else {}
    prompts = {k: str(raw_prompts.get(k) or "").strip() for k in ("translate", "summarize", "organize", "polish")}
    prompts = {k: v for k, v in prompts.items() if v}
    return {
        "enabled": a.get("enabled") is not False,
        "request_preset": str(a.get("request_preset") or ""),
        "model_override": str(a.get("model_override") or ""),
        "temperature_override": temp,
        "extra_params": a.get("extra_params") if isinstance(a.get("extra_params"), dict) else {},
        "target_language": str(a.get("target_language") or "中文"),
        "style_instruction": str(a.get("style_instruction") or ""),
        "max_chars": max_chars,
        "custom_actions": _clean_custom_actions(a.get("custom_actions")),  # v260929b · 自定义阅读动作
        "prompts": prompts,  # v260929x · 预设动作提示词覆盖
    }


def _clean_personas(personas: Any) -> list[dict[str, Any]]:
    """v260930 · M3 Agent 人设归一化：id/name/system_prompt/tools/write_mode/request_preset/temperature。
    内置 reader/executor 不可删除、始终存在；用户对内置人设的编辑（提示词/白名单/写模式）优先于内置默认；
    自定义人设跟在后面。

    tools 白名单**按原样保留**（只做旧名→新名映射与去重）——不按「当前可用」裁剪。
    当前可用的工具集合在使用时过滤（`agent.py` 的 allowed 过滤），这样插件停用/未加载时
    白名单里的条目不会被写回磁盘时抹掉，重新启用即自动恢复。"""
    from . import agent_tools  # noqa: F401  保持导入：调用方与历史行为都经过它
    #: 工具搬家时的**旧名 → 新名**别名（用户已保存的人设白名单据此迁移，避免悄悄丢能力）
    #: v261009.17 · 文献笔记/阅读区 AI 助手并入「文献阅读工作区」后，插件工具前缀从
    #: `p_litnote__*` 变为 `p_literature-reader__*`；四种旧写法都指向新名。
    LEGACY_TOOL_ALIASES = {
        "lit_context": "p_literature-reader__context",
        "lit_note_write": "p_literature-reader__note_write",
        "p_litnote__context": "p_literature-reader__context",
        "p_litnote__note_write": "p_literature-reader__note_write",
    }
    builtin_defaults = {
        # v261009.9 · 文献工具已搬成插件（v261009.17 起并入「文献阅读工作区」）：这里用**对外名**引用它，
        # 插件未启用时该名字会被 all_tool_names() 过滤掉，人设自动退化为纯知识库工具。
        "reader": {"name": "阅读助手", "system_prompt": "你是严谨的科研阅读助手。回答优先基于知识库检索结果与用户提供的文献上下文；擅长解释概念、总结要点、对比方法。你不修改任何知识库内容，检索不到时明确说明。", "tools": ["kb_search", "kb_read", "p_literature-reader__context"], "write_mode": "confirm"},
        "executor": {"name": "执行助手", "system_prompt": "你是科研工作台的执行助手。用户交代任务后主动检索知识库、查重、生成条目/笔记草稿并等待确认；写知识条目前必须遵守命名规范（知识-<类别>-<名称>），命中同名条目改为增补。完成后简洁汇报做了什么、产出了哪些草稿。", "tools": list(agent_tools.all_tool_names()), "write_mode": "confirm"},
        "archivist": {"name": "术语建档员", "system_prompt": ARCHIVIST_PROMPT, "tools": list(agent_tools.all_tool_names()), "write_mode": "confirm"},
    }

    def _clean(pid: str, item: dict[str, Any], is_builtin: bool) -> dict[str, Any]:
        # v261009.9 · 工具搬家后，用户已保存的白名单里可能还是旧名——按别名映射到新名，
        # 避免「功能搬成插件」悄悄让人设丢掉一项能力（迁移等价性）。
        # v261009.11 · **不再按「当前可用」裁剪**：清洗结果会被 reload_all() 写回磁盘，
        # 于是任何一次「临时不可用」（插件被阻塞/未加载）都会**永久**删掉白名单条目。
        # 未知名字在使用时过滤即可（`agent.py` 的 allowed 过滤），保留它才能优雅恢复。
        raw_tools = item.get("tools") if isinstance(item.get("tools"), list) else []
        tools: list[str] = []
        for t in raw_tools:
            name = LEGACY_TOOL_ALIASES.get(str(t), str(t))
            if name and name not in tools:
                tools.append(name)
        if not tools:
            tools = list(builtin_defaults[pid]["tools"]) if pid in builtin_defaults else ["kb_search", "kb_read"]  # 空白名单回退安全默认（v261009.9：只回退**核心**工具）
        temp = item.get("temperature")
        try:
            temp = float(temp) if temp is not None and str(temp).strip() != "" else None
        except Exception:
            temp = None
        return {
            "id": pid,
            "name": str(item.get("name") or builtin_defaults.get(pid, {}).get("name") or pid).strip()[:30],
            "builtin": is_builtin,
            "system_prompt": str(item.get("system_prompt") or builtin_defaults.get(pid, {}).get("system_prompt") or "").strip(),
            "tools": tools,
            "write_mode": "direct" if str(item.get("write_mode") or "").strip() == "direct" else "confirm",
            "request_preset": str(item.get("request_preset") or "").strip(),
            "temperature": temp,
        }

    by_id: dict[str, dict[str, Any]] = {}
    for item in (personas if isinstance(personas, list) else []):
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()[:40]
        if not pid:
            continue
        by_id[pid] = _clean(pid, item, pid in builtin_defaults)
    out: list[dict[str, Any]] = []
    for pid, default in builtin_defaults.items():  # 内置在前（缺失则补默认），保证 personas[0] 回退稳定
        out.append(by_id.pop(pid) if pid in by_id else _clean(pid, {**default, "id": pid}, True))
    out.extend(by_id.values())  # 自定义人设按用户顺序追加
    return out


def resolve_persona(persona_id: str) -> dict[str, Any]:
    """按 id 取人设；不存在时回退第一个人设（阅读助手）。返回带 tools/write_mode 的完整档案。"""
    personas = _clean_personas(get_app().get("llm", {}).get("personas"))
    wanted = str(persona_id or "").strip()
    for p in personas:
        if p["id"] == wanted:
            return p
    return personas[0]


def _strip_legacy_llm_for_storage(app: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(app)
    old = out.get("llm") if isinstance(out.get("llm"), dict) else {}
    out["llm"] = {
        "enabled": old.get("enabled", False) is True,
        "system_prompt": str(old.get("system_prompt") or DEFAULT_SYSTEM_PROMPT),
        "assist": _clean_assist(old.get("assist")),  # v260929 · 保留 AI 阅读助手设置
        "vision_enabled": old.get("vision_enabled", False) is True,  # v260929c · 多模态开关
        "personas": _clean_personas(old.get("personas")),  # v260930 · M3 人设档案
    }
    return _deep_merge(DEFAULT_APP_CONFIG, out)


def _load_or_migrate_secret(app: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    raw = _read_json(SECRET_PATH)
    if int(raw.get("schema_version") or 0) >= LLM_SECRET_SCHEMA_VERSION and isinstance(raw.get("profiles"), list):
        normalized = _normalize_secret(raw)
        if normalized != raw:
            _atomic_json_write(SECRET_PATH, normalized)
        return normalized, False
    migrated = _migrate_secret(app)
    _atomic_json_write(SECRET_PATH, migrated)
    return migrated, True


def reload_all() -> dict:
    global _cache, _workspace_cache
    load_secrets()
    with _lock:
        raw_app = _load_json(CONFIG_DIR / "app.json", DEFAULT_APP_CONFIG)
        secret, migrated = _load_or_migrate_secret(raw_app)
        app = _strip_legacy_llm_for_storage(raw_app)
        # On the first v2 migration, remove obsolete key/environment/provider fields
        # from app.json after they have been copied to secret.json.
        if migrated or app != raw_app:
            _atomic_json_write(CONFIG_DIR / "app.json", app)
        _cache = {"app": app, "secret": secret}
        _workspace_cache = None
        return {"app": deepcopy(app)}


def init() -> dict:
    """显式初始化：注入 secrets 环境变量 + 载入配置缓存。

    v261009 · 原先这两步写在模块尾部（import 即执行），带来两个后果：
    ① ``import app.config`` 就会读写用户配置（迁移路径会落盘 app.json/secret.json）；
    ② 由此形成 ``config → agent_tools → store → workspace → config`` 的**导入顺序炸弹**
       ——先 import ``app.agent_tools`` 或 ``app.workspace`` 会在半初始化模块上 ImportError。

    现在改由运行入口显式调用（``server.build_server``、``mcp.bridge``）；
    其余访问器（``get_all`` / ``get_public`` / ``save_*``）依旧带 ``if not _cache: reload_all()``
    惰性兜底，所以漏调 init() 也只是晚一点初始化，不会拿到半初始化状态。
    """
    load_secrets()
    return reload_all()


def get_all() -> dict:
    load_secrets()
    with _lock:
        if not _cache:
            reload_all()
        return {"app": deepcopy(_cache["app"])}


def get_app() -> dict:
    load_secrets()
    with _lock:
        if not _cache:
            reload_all()
        return deepcopy(_cache["app"])


def _active_profile(secret: dict[str, Any] | None = None) -> dict[str, Any]:
    if secret is None:
        with _lock:
            if not _cache:
                reload_all()
            secret = _cache["secret"]
    active_id = str(secret.get("active_profile_id") or "")
    profiles = secret.get("profiles") if isinstance(secret.get("profiles"), list) else []
    profile = next((p for p in profiles if str(p.get("id") or "") == active_id), None)
    return deepcopy(profile or (profiles[0] if profiles else {}))


def _public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(profile)
    key = str(out.pop("api_key", "") or "")
    out["has_api_key"] = bool(key)
    return out


def get_public() -> dict:
    with _lock:
        if not _cache:
            reload_all()
        app = deepcopy(_cache["app"])
        secret = deepcopy(_cache["secret"])
    llm = dict(app.get("llm") or {})
    profiles = [_public_profile(p) for p in secret.get("profiles", [])]
    active = _active_profile(secret)
    active_public = _public_profile(active) if active else {}
    presets = active_public.get("request_presets") if isinstance(active_public.get("request_presets"), list) else []
    default_preset = str(active_public.get("default_request_preset") or (presets[0]["id"] if presets else "default"))
    selected = next((p for p in presets if str(p.get("id")) == default_preset), presets[0] if presets else {})
    # Compatibility fields keep the existing Agent page functional while the
    # new settings UI consumes the profiles array.
    llm.update({
        "protocol": "chat_completions",
        "provider_label": str(active_public.get("name") or "OpenAI-compatible"),
        "active_profile_id": str(secret.get("active_profile_id") or ""),
        "active_profile_name": str(active_public.get("name") or ""),
        "profile_count": len(profiles),
        "profiles": profiles,
        "base_url": str(active_public.get("base_url") or ""),
        "timeout": int(active_public.get("timeout") or 120),
        "max_output_tokens": int(active_public.get("max_output_tokens") or 0),
        "temperature": active_public.get("temperature"),
        "show_reasoning": active_public.get("show_reasoning") is not False,
        "request_presets": presets,
        "default_request_preset": default_preset,
        "model": str(selected.get("model") or ""),
        "has_api_key": active_public.get("has_api_key", False),
        "api_key_source": "config/secret.json",
    })
    app["llm"] = llm
    return {"app": app}


def get_active_llm_profile_runtime() -> dict[str, Any]:
    with _lock:
        if not _cache:
            reload_all()
        app_llm = deepcopy(_cache["app"].get("llm") or {})
        profile = _active_profile(_cache["secret"])
    profile["enabled"] = app_llm.get("enabled", False) is True
    profile["system_prompt"] = str(app_llm.get("system_prompt") or DEFAULT_SYSTEM_PROMPT)
    profile["protocol"] = "chat_completions"
    profile["assist"] = app_llm.get("assist") if isinstance(app_llm.get("assist"), dict) else {}  # v260929 · 阅读区 AI 助手设置（app.json 持久化，运行时透出给 agent.assist）
    profile["vision_enabled"] = app_llm.get("vision_enabled", False) is True  # v260929c · 多模态开关：阅读区 AI 助手可发送截图（需模型支持图片输入）
    return profile


def _merge_profiles_from_public(incoming_llm: dict[str, Any], current_secret: dict[str, Any]) -> dict[str, Any]:
    incoming_profiles = incoming_llm.get("profiles")
    if not isinstance(incoming_profiles, list):
        return deepcopy(current_secret)
    existing = {str(p.get("id") or ""): p for p in current_secret.get("profiles", []) if isinstance(p, dict)}
    merged_profiles: list[dict[str, Any]] = []
    for i, item in enumerate(incoming_profiles):
        if not isinstance(item, dict):
            continue
        pid = _safe_profile_id(item.get("id"), f"profile-{i + 1}")
        old_key = str(existing.get(pid, {}).get("api_key") or "")
        merged_profiles.append(_normalize_profile({**item, "id": pid}, i, existing_key=old_key))
    if not merged_profiles:
        raise ValueError("至少需要保留一套 Agent API 配置")
    active_id = str(incoming_llm.get("active_profile_id") or current_secret.get("active_profile_id") or merged_profiles[0]["id"])
    if active_id not in {p["id"] for p in merged_profiles}:
        active_id = merged_profiles[0]["id"]
    return {
        "schema_version": LLM_SECRET_SCHEMA_VERSION,
        "active_profile_id": active_id,
        "profiles": merged_profiles,
        **({"migrated_at": current_secret.get("migrated_at")} if current_secret.get("migrated_at") else {}),
    }


def _clean_knowledge_types(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    builtin = {"idea", "journal", "note", "experiment", "milestone", "summary", "literature"}
    custom: list[dict[str, Any]] = []
    seen = set(builtin)
    for item in (raw.get("custom") or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("id") or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", kind) or kind in seen:
            continue
        label = str(item.get("label") or kind).strip()[:32] or kind
        icon = str(item.get("icon") or "◆").strip()[:4] or "◆"
        statuses = [str(x).strip()[:24] for x in (item.get("statuses") or []) if str(x).strip()]
        if not statuses:
            statuses = ["草稿", "进行中", "完成", "已归档"]
        custom.append({
            "id": kind,
            "label": label,
            "icon": icon,
            "statuses": list(dict.fromkeys(statuses))[:12],
            "template": str(item.get("template") or "")[:20000].replace("\r\n", "\n"),
            "hidden": bool(item.get("hidden", False)),
        })
        seen.add(kind)
    valid = builtin | {x["id"] for x in custom}
    order = [str(x) for x in (raw.get("order") or []) if str(x) in valid]
    # 旧配置的 order 可能缺后来新增的内置类型（如 experiment）：按默认顺序的相对位置补齐，
    # 而不是一律追加到末尾——否则「设置 → 知识条目」里实验会排到「文献」之后。
    default_order = ["idea", "journal", "note", "experiment", "milestone", "summary", "literature"]
    if not order:
        order = list(default_order)
    else:
        for i, kind in enumerate(default_order):
            if kind in order:
                continue
            prev = next((k for k in reversed(default_order[:i]) if k in order), None)
            order.insert(order.index(prev) + 1 if prev else 0, kind)
        order = list(dict.fromkeys(order + [x["id"] for x in custom]))
    hidden = [str(x) for x in (raw.get("hidden") or []) if str(x) in valid]
    templates_raw = raw.get("templates") if isinstance(raw.get("templates"), dict) else {}
    templates: dict[str, str] = {}
    for kind, value in templates_raw.items():
        key = str(kind).strip()
        if key in valid:
            templates[key] = str(value or "")[:30000].replace("\r\n", "\n")
    return {"order": order, "hidden": list(dict.fromkeys(hidden)), "custom": custom, "templates": templates}


def _clean_classification_marks(value: Any) -> list[dict[str, str]]:
    rows = value if isinstance(value, list) else []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        mark_id = str(item.get("id") or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", mark_id) or mark_id in seen:
            continue
        label = str(item.get("label") or mark_id).strip()[:16] or mark_id
        icon = str(item.get("icon") or "◆").strip()[:4] or "◆"
        color = str(item.get("color") or "#4a6fa5").strip().lower()
        if not re.fullmatch(r"#[0-9a-f]{6}", color):
            color = "#4a6fa5"
        out.append({"id": mark_id, "icon": icon, "label": label, "color": color})
        seen.add(mark_id)
        if len(out) >= 24:
            break
    return out


def save_app(data: dict) -> dict:
    incoming = deepcopy(data or {})
    incoming_llm = incoming.get("llm") if isinstance(incoming.get("llm"), dict) else {}
    with _lock:
        if not _cache:
            reload_all()
        if "knowledge_types" not in incoming:
            incoming["knowledge_types"] = deepcopy(_cache["app"].get("knowledge_types") or DEFAULT_APP_CONFIG["knowledge_types"])
        if "classification_marks" not in incoming:
            incoming["classification_marks"] = deepcopy(_cache["app"].get("classification_marks") or DEFAULT_APP_CONFIG["classification_marks"])
        current_secret = deepcopy(_cache["secret"])
        secret = _merge_profiles_from_public(incoming_llm, current_secret)
        assist = incoming_llm.get("assist") if isinstance(incoming_llm.get("assist"), dict) else {}
        clean_llm = {
            "enabled": incoming_llm.get("enabled", False) is True,
            "system_prompt": str(incoming_llm.get("system_prompt") or DEFAULT_SYSTEM_PROMPT),
            "assist": _clean_assist(assist),  # v260929 · AI 阅读助手设置：app.json 的 llm 下持久化（其余 llm 字段归 secret profiles，save 时会被清掉，故显式保留）
            "vision_enabled": incoming_llm.get("vision_enabled", False) is True,  # v260929c · 多模态开关：阅读区 AI 助手可发送截图
            "personas": _clean_personas(incoming_llm.get("personas")),  # v260930 · M3 人设档案：随 app.json 持久化，否则 save 时被清掉导致回退默认 confirm
        }
        incoming["llm"] = clean_llm
        incoming["knowledge_types"] = _clean_knowledge_types(incoming.get("knowledge_types"))
        incoming["classification_marks"] = _clean_classification_marks(incoming.get("classification_marks"))
        merged = _deep_merge(DEFAULT_APP_CONFIG, incoming)
        _atomic_json_write(CONFIG_DIR / "app.json", merged)
        _atomic_json_write(SECRET_PATH, secret)
        reload_all()
    return get_public()["app"]


_workspace_cache: tuple[tuple[str, str], Path] | None = None


def workspace_root() -> Path:
    global _workspace_cache
    with _lock:
        if not _cache:
            reload_all()
        raw = str(_cache["app"].get("workspace") or "Workspace")
        key = (str(ROOT), raw)
        if _workspace_cache is None or _workspace_cache[0] != key:
            p = Path(raw)
            _workspace_cache = (key, (p if p.is_absolute() else ROOT / p).resolve())
        return _workspace_cache[1]
