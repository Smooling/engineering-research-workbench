from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
SECRET_PATH = CONFIG_DIR / "secret.json"
LEGACY_SECRET_PATH = CONFIG_DIR / "secrets.json"
LLM_SECRET_SCHEMA_VERSION = 2
DEFAULT_SYSTEM_PROMPT = "你是一个严谨的科研助手。优先基于用户显式引用的研究资料回答，不确定时明确说明。"

DEFAULT_APP_CONFIG = {
    "app_name": "科研工作台",
    "subtitle": "Engineering Research Workspace",
    "host": "127.0.0.1",
    "port": 8765,
    "auto_open_browser": True,
    "workspace": "Workspace",
    "weather": {
        "enabled": True,
        "location": "天津市南开区",
        "latitude": 39.105,
        "longitude": 117.15,
        "timezone": "Asia/Shanghai",
    },
    "ui": {
        "theme": "light",
        "sidebar_pinned_groups": ["core"],
        "milestone_default_view": "timeline",
        "graph_default_view": "2d",
        "animations": True,
        "heatmap_months": 12,
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
    # Non-secret, global Agent options stay in app.json. Provider profiles and
    # API keys live only in config/secret.json, which is ignored by git.
    "llm": {
        "enabled": False,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
    },
    # Embedding is intentionally independent from the Agent / chat provider.
    # Only the environment-variable name is persisted; the real key stays in os.environ.
    "embedding": {
        "enabled": False,
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "model": "",
        "timeout": 120,
        "batch_size": 32,
    },
}

DEFAULT_RSS_CONFIG = {
    "sources": [
        {"name": "arXiv · Artificial Intelligence", "url": "https://rss.arxiv.org/rss/cs.AI", "enabled": True},
        {"name": "arXiv · Machine Learning", "url": "https://rss.arxiv.org/rss/cs.LG", "enabled": True},
        {"name": "arXiv · Computation and Language", "url": "https://rss.arxiv.org/rss/cs.CL", "enabled": True},
    ],
    "max_items_per_source": 12,
}

_lock = threading.RLock()
_cache: dict[str, Any] = {}


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


def _strip_legacy_llm_for_storage(app: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(app)
    old = out.get("llm") if isinstance(out.get("llm"), dict) else {}
    out["llm"] = {
        "enabled": old.get("enabled", False) is True,
        "system_prompt": str(old.get("system_prompt") or DEFAULT_SYSTEM_PROMPT),
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
    global _cache
    with _lock:
        raw_app = _load_json(CONFIG_DIR / "app.json", DEFAULT_APP_CONFIG)
        rss = _load_json(CONFIG_DIR / "rss.json", DEFAULT_RSS_CONFIG)
        secret, migrated = _load_or_migrate_secret(raw_app)
        app = _strip_legacy_llm_for_storage(raw_app)
        # On the first v2 migration, remove obsolete key/environment/provider fields
        # from app.json after they have been copied to secret.json.
        if migrated or app != raw_app:
            _atomic_json_write(CONFIG_DIR / "app.json", app)
        _cache = {"app": app, "rss": rss, "secret": secret}
        return {"app": deepcopy(app), "rss": deepcopy(rss)}


def get_all() -> dict:
    with _lock:
        if not _cache:
            reload_all()
        return {"app": deepcopy(_cache["app"]), "rss": deepcopy(_cache["rss"])}


def get_app() -> dict:
    return get_all()["app"]


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
        rss = deepcopy(_cache["rss"])
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
    embedding = _normalize_embedding(app.get("embedding"))
    env_name = str(embedding.get("api_key_env") or "").strip()
    embedding["has_api_key"] = bool(env_name and os.environ.get(env_name))
    app["embedding"] = embedding
    return {"app": app, "rss": rss}


def get_active_llm_profile_runtime() -> dict[str, Any]:
    with _lock:
        if not _cache:
            reload_all()
        app_llm = deepcopy(_cache["app"].get("llm") or {})
        profile = _active_profile(_cache["secret"])
    profile["enabled"] = app_llm.get("enabled", False) is True
    profile["system_prompt"] = str(app_llm.get("system_prompt") or DEFAULT_SYSTEM_PROMPT)
    profile["protocol"] = "chat_completions"
    return profile


def _normalize_embedding(item: Any) -> dict[str, Any]:
    raw = item if isinstance(item, dict) else {}
    return {
        "enabled": raw.get("enabled", False) is True,
        "base_url": str(raw.get("base_url") or "https://api.openai.com/v1").strip().rstrip("/"),
        "api_key_env": str(raw.get("api_key_env") or "OPENAI_API_KEY").strip() or "OPENAI_API_KEY",
        "model": str(raw.get("model") or "").strip()[:240],
        "timeout": max(5, min(600, int(raw.get("timeout") or 120))),
        "batch_size": max(1, min(128, int(raw.get("batch_size") or 32))),
    }


def get_embedding_runtime() -> dict[str, Any]:
    cfg = get_app()
    emb = _normalize_embedding(cfg.get("embedding"))
    env_name = str(emb.get("api_key_env") or "").strip()
    emb["api_key"] = str(os.environ.get(env_name) or "").strip() if env_name else ""
    emb["has_api_key"] = bool(emb["api_key"])
    return emb


def get_rss() -> dict:
    return get_all()["rss"]


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


def save_app(data: dict) -> dict:
    incoming = deepcopy(data or {})
    incoming_llm = incoming.get("llm") if isinstance(incoming.get("llm"), dict) else {}
    with _lock:
        if not _cache:
            reload_all()
        current_secret = deepcopy(_cache["secret"])
        secret = _merge_profiles_from_public(incoming_llm, current_secret)
        clean_llm = {
            "enabled": incoming_llm.get("enabled", False) is True,
            "system_prompt": str(incoming_llm.get("system_prompt") or DEFAULT_SYSTEM_PROMPT),
        }
        incoming["llm"] = clean_llm
        merged = _deep_merge(DEFAULT_APP_CONFIG, incoming)
        _atomic_json_write(CONFIG_DIR / "app.json", merged)
        _atomic_json_write(SECRET_PATH, secret)
        reload_all()
    return get_public()["app"]


def save_rss(data: dict) -> dict:
    merged = _deep_merge(DEFAULT_RSS_CONFIG, data or {})
    with _lock:
        _atomic_json_write(CONFIG_DIR / "rss.json", merged)
        reload_all()
    return get_rss()


def workspace_root() -> Path:
    cfg = get_app()
    raw = str(cfg.get("workspace") or "Workspace")
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


reload_all()
