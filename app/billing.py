"""v261008 · 用量计费：Provider 单价表 + token 用量记账 + 聚合统计。

参照 dsh-cost-meter 的计价模型做了裁剪：不做峰谷计价、余额查询与 CLI 适配。

落盘目录 Workspace/System/billing/
- prices.json  单价表（USD / 1M tokens）+ 档案计费方式（plans），可在前端编辑
- ledger.jsonl 逐条追加的调用账本（只增不改，追加写）

计价口径（v261008b 起区分三种计费方式）：
    mode=token         按单价表计费：
                       cost = miss_in/1e6*input + out/1e6*output
                            + cache_read/1e6*cache_hit + cache_write/1e6*cache_write
                       miss_in = prompt_tokens - cache_read - cache_write（缺缓存明细时按全部 input 计）
    mode=subscription  订阅套餐（如 OpenCode Go / 方舟 Agent Plan）：只记 token 量，金额不适用，
                       记 billing_mode=subscription 且 priced=true，不计入"缺单价"告警——订阅制本来就没有按量费用
    mode=free          免费/本地模型：同上，但语义为免费
单价键支持按档案限定，优先级：`<profile_id>/<model>` → `<profile_id>`（该档案的兜底价）→ `<model>` → 通配。
未匹配到单价的 token 模式调用记 0 并标注 priced=false，不伪造金额。
"""
from __future__ import annotations

import fnmatch
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
SCHEMA_VERSION = 1
_PRICE_KEYS = ("input", "output", "cache_hit", "cache_write")
_STRING_KEYS = ("currency", "note")  # 单价条目可选：币种（默认取表头 currency）与备注
PLAN_MODES = ("token", "subscription", "free")
# 参考汇率：1 USD = N 该币种。仅用于把「官方人民币标价」折算成表头币种，可在 prices.fx 覆盖。
DEFAULT_FX = {"CNY": 7.1}
DEFAULT_FX_NOTE = "fx 为参考汇率（1 USD = N 该币种，预置 CNY≈7.1），请按当日汇率修改。"

# 预置参考价（USD / 1M tokens，取非高峰档）。来源：dsh-cost-meter docs/provider-pricing.json @2026-10-03。
# 仅作模板，可被用户覆盖；键为模型名，支持 * 通配。
DEFAULT_MODELS: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {"input": 0.15, "output": 0.6, "cache_hit": 0.003},
    "deepseek-v4-pro": {"input": 0.66, "output": 1.98, "cache_hit": 0.022},
    "gpt-4o": {"input": 2.5, "output": 10.0, "cache_hit": 1.25},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6, "cache_hit": 0.075},
    "claude-opus-4-5": {"input": 5.0, "output": 25.0, "cache_hit": 0.5, "cache_write": 6.25},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0, "cache_hit": 0.3, "cache_write": 3.75},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_hit": 0.1, "cache_write": 1.25},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0, "cache_hit": 0.125},
    "gemini-2.5-flash": {"input": 0.3, "output": 2.5, "cache_hit": 0.03},
    "qwen3.7-plus": {"input": 0.4, "output": 1.6, "cache_hit": 0.04, "cache_write": 0.5},
}

PRICE_NOTE = ("单价单位 = 表头 currency / 1M tokens；单条可写 \"currency\" 覆盖币种（例如直接粘贴官方人民币标价时写 CNY），"
              "按 fx 参考汇率折算：1 USD = N 该币种。" + DEFAULT_FX_NOTE +
              "plans 段可按档案声明计费方式：mode=token|subscription|free——订阅套餐（如 OpenCode Go、方舟 Agent Plan）"
              "只按订阅计费，但页面仍会用同一份单价表算出「等价标价」，便于判断套餐是否划算。")


def _clean_plan(raw: Any) -> dict[str, Any] | None:
    """档案计费方式：{mode, label?, monthly_usd?, note?}。"""
    if not isinstance(raw, dict):
        return None
    mode = str(raw.get("mode") or "token").strip().lower()
    if mode not in PLAN_MODES:
        raise ValueError(f"plans.mode 只能是 {'/'.join(PLAN_MODES)}，收到 {mode!r}")
    out: dict[str, Any] = {"mode": mode}
    if str(raw.get("label") or "").strip():
        out["label"] = str(raw["label"]).strip()[:80]
    monthly = raw.get("monthly_usd")
    if monthly not in (None, ""):
        try:
            value = float(monthly)
            if value >= 0:
                out["monthly_usd"] = value
        except (TypeError, ValueError):
            raise ValueError("plans.monthly_usd 必须是数字") from None
    if str(raw.get("note") or "").strip():
        out["note"] = str(raw["note"]).strip()[:200]
    return out


def plan_for(profile_id: str, plans: dict[str, Any] | None = None) -> dict[str, Any]:
    """取档案的计费方式；未声明按 token（按量计费）处理。"""
    pid = str(profile_id or "").strip()
    if not pid:
        return {"mode": "token"}
    table = plans if isinstance(plans, dict) else (load_prices().get("plans") or {})
    entry = table.get(pid)
    cleaned = _clean_plan(entry) if isinstance(entry, dict) else None
    return cleaned or {"mode": "token"}


def _ensure_workspace():
    """延迟导入 workspace：顶层导入会在「billing 作为首个 app 模块」时形成循环
    （billing → workspace → config(reload_all) → agent_tools → store → workspace 半初始化）。
    先导入 config 让工作台按正常依赖顺序完成初始化，再取 ensure_workspace。"""
    from . import config  # noqa: F401  先按正常顺序初始化（config → agent_tools → store → workspace）
    from .workspace import ensure_workspace
    return ensure_workspace()


def _dir() -> Path:
    root = _ensure_workspace() / "System" / "billing"
    root.mkdir(parents=True, exist_ok=True)
    return root


def prices_path() -> Path:
    return _dir() / "prices.json"


def ledger_path() -> Path:
    return _dir() / "ledger.jsonl"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def default_prices() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "currency": "USD",
        "unit": "per_1m_tokens",
        "fx": dict(DEFAULT_FX),
        "note": PRICE_NOTE,
        "models": {k: dict(v) for k, v in DEFAULT_MODELS.items()},
        "plans": {},
    }


def _clean_entry(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for key in _PRICE_KEYS:
        val = raw.get(key)
        if val is None or val == "":
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            raise ValueError(f"单价 {key} 必须是数字") from None
        if num < 0:
            raise ValueError(f"单价 {key} 不能为负数")
        out[key] = num
    for key in _STRING_KEYS:  # v261008b · 币种与备注：直接粘贴官方人民币标价时用 currency=CNY
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()[:120]
    if "currency" in out:
        out["currency"] = str(out["currency"]).upper()
    if not any(k in out for k in _PRICE_KEYS):
        return None  # 只有备注/币种、没有任何数字：不算有效单价（否则会被当成 0 元"已计价"）
    if "input" not in out:
        out["input"] = out.get("cache_hit", out.get("output", 0.0))
    if "cache_hit" not in out:
        out["cache_hit"] = out["input"]
    if "output" not in out:
        out["output"] = 0.0
    return out


def _clean_fx(raw: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for code, val in (raw if isinstance(raw, dict) else {}).items():
        name = str(code or "").strip().upper()
        try:
            rate = float(val)
        except (TypeError, ValueError):
            continue
        if name and rate > 0:
            out[name] = rate
    return out


def convert_cost(cost: float, entry_currency: str, fx: dict[str, float], base: str = "USD") -> tuple[float, bool]:
    """把单价条目币种下的金额折成表头币种。fx 语义：1 <base> = N <code>。
    返回 (折算后金额, 是否有可用汇率)；缺汇率时返回 0 并由调用方标注 fx_missing。"""
    cur = str(entry_currency or base).upper()
    base = str(base or "USD").upper()
    if cur == base:
        return float(cost), True
    rate = float((fx or {}).get(cur) or 0.0)
    if rate <= 0:
        return 0.0, False
    return float(cost) / rate, True


def normalize_prices(raw: Any) -> dict[str, Any]:
    models_src = raw.get("models") if isinstance(raw, dict) else None
    if not isinstance(models_src, dict):
        raise ValueError("价格表缺少 models 字段")
    models: dict[str, dict[str, float]] = {}
    for name, entry in models_src.items():
        key = str(name or "").strip()
        if not key:
            continue
        cleaned = _clean_entry(entry)
        if cleaned is not None:
            models[key] = cleaned
    plans_src = raw.get("plans") if isinstance(raw.get("plans"), dict) else {}
    plans: dict[str, dict[str, Any]] = {}
    for pid, entry in plans_src.items():
        key = str(pid or "").strip()
        if not key:
            continue
        cleaned_plan = _clean_plan(entry)
        if cleaned_plan is not None and cleaned_plan.get("mode") != "token":  # token 是默认，无需落盘
            plans[key] = cleaned_plan
    return {
        "schema_version": SCHEMA_VERSION,
        "currency": str((raw.get("currency") if isinstance(raw, dict) else "") or "USD").upper(),
        "unit": "per_1m_tokens",
        "fx": {**DEFAULT_FX, **_clean_fx(raw.get("fx") if isinstance(raw, dict) else None)},
        "note": str(raw.get("note") or PRICE_NOTE) if isinstance(raw, dict) else PRICE_NOTE,
        "models": models,
        "plans": plans,
    }


_PRICE_CACHE: dict[str, Any] = {"mtime": None, "data": None}


def load_prices() -> dict[str, Any]:
    """读价格表；文件不存在时落一份预置模板。按 mtime 缓存，避免每次调用都读盘。"""
    path = prices_path()
    if not path.exists():
        data = default_prices()
        _write_json(path, data)
        _PRICE_CACHE.update({"mtime": path.stat().st_mtime, "data": data})
        return data
    mtime = path.stat().st_mtime
    with _LOCK:
        if _PRICE_CACHE["mtime"] == mtime and _PRICE_CACHE["data"] is not None:
            return _PRICE_CACHE["data"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raw = default_prices()
    data = normalize_prices(raw)
    with _LOCK:
        _PRICE_CACHE.update({"mtime": mtime, "data": data})
    return data


def save_prices(raw: Any) -> dict[str, Any]:
    data = normalize_prices(raw)
    path = prices_path()
    _write_json(path, data)
    with _LOCK:
        _PRICE_CACHE.update({"mtime": path.stat().st_mtime, "data": data})
    return data


def _candidates(model: str, profile_id: str = "") -> list[str]:
    """候选键顺序（先档案限定、后裸模型名）：
    `<profile_id>/<model>` → `<profile_id>`（该档案兜底价）→ `<model>` → 去 provider 前缀/标签 → 小写。"""
    name = str(model or "").strip()
    pid = str(profile_id or "").strip()
    out: list[str] = []

    def add(value: str) -> None:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)

    if pid and name:
        add(f"{pid}/{name}")
    if pid:
        add(pid)
    add(name)
    if "/" in name:
        add(name.rsplit("/", 1)[1])
    if ":" in name:
        add(name.split(":", 1)[0])
    if name and name.lower() != name:
        add(name.lower())
    return out


def match_price(model: str, models: dict[str, Any], profile_id: str = "") -> tuple[str, dict[str, Any] | None]:
    """精确名（含 `<profile_id>/<model>` 与档案兜底键）→ 去前缀/标签 → 大小写无关 → 通配（* 模式）。"""
    if not isinstance(models, dict):
        return "", None
    cands = _candidates(model, profile_id)
    for cand in cands:
        entry = models.get(cand)
        if isinstance(entry, dict):
            return cand, entry
    low_map = {str(k).lower(): k for k in models}
    for cand in cands:
        key = low_map.get(cand.lower())
        if key:
            return key, models[key]
    for key in models:
        k = str(key)
        if any(ch in k for ch in "*?[") and any(fnmatch.fnmatch(cand, k) for cand in cands):
            return k, models[key]
    return "", None


def extract_usage(raw: Any) -> dict[str, int]:
    """兼容 OpenAI（prompt/completion + prompt_tokens_details）与 Anthropic（input/output + cache_*）字段。"""
    if not isinstance(raw, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "cache_write_tokens": 0}
    details = raw.get("prompt_tokens_details") if isinstance(raw.get("prompt_tokens_details"), dict) else {}

    def _int(*values: Any) -> int:
        for val in values:
            if val is None or val == "":
                continue
            try:
                return max(int(val), 0)
            except (TypeError, ValueError):
                continue
        return 0

    prompt = _int(raw.get("prompt_tokens"), raw.get("input_tokens"))
    completion = _int(raw.get("completion_tokens"), raw.get("output_tokens"))
    total = _int(raw.get("total_tokens"))
    if not prompt and total:
        prompt = max(total - completion, 0)
    cached = _int(details.get("cached_tokens"), raw.get("cache_read_input_tokens"), raw.get("prompt_cache_hit_tokens"))
    cache_write = _int(details.get("cache_creation_tokens"), details.get("cache_creation_input_tokens"), raw.get("cache_creation_input_tokens"))
    return {"prompt_tokens": prompt, "completion_tokens": completion, "cached_tokens": cached, "cache_write_tokens": cache_write}


def compute_cost(usage: dict[str, int], entry: dict[str, Any]) -> float:
    price = _clean_entry(entry) or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    cached = int(usage.get("cached_tokens") or 0)
    cache_write = int(usage.get("cache_write_tokens") or 0)
    if cached + cache_write > prompt:  # 明细异常时按比例收敛，避免 miss 为负
        scale = prompt / (cached + cache_write) if (cached + cache_write) else 0
        cached = int(cached * scale)
        cache_write = max(prompt - cached, 0)
    miss = max(prompt - cached - cache_write, 0)
    return (
        miss / 1e6 * float(price.get("input", 0.0))
        + completion / 1e6 * float(price.get("output", 0.0))
        + cached / 1e6 * float(price.get("cache_hit", 0.0))
        + cache_write / 1e6 * float(price.get("cache_write", price.get("cache_hit", 0.0)))
    )


def record(cfg: dict[str, Any], usage_raw: Any) -> dict[str, Any] | None:
    """采集一次 LLM 调用的用量并追加账本。cfg["_billing"] 缺省时直接跳过（如连通性探针）。

    v261008b：①按档案计费方式（prices.plans）区分 token / subscription / free——订阅制只记用量、
    金额不适用且不再报「缺单价」；②单价键支持 `<profile_id>/<model>` 与 `<profile_id>` 兜底；
    ③网关未返回 usage 时也落一条 `usage_missing` 记录（tokens=0），保证调用次数口径与实际一致。
    """
    ctx = cfg.get("_billing") if isinstance(cfg, dict) else None
    if not isinstance(ctx, dict) or not ctx.get("session_id"):
        return None
    usage = extract_usage(usage_raw)
    usage_missing = not usage["prompt_tokens"] and not usage["completion_tokens"]
    model = str(cfg.get("model") or "").strip()
    profile_id = str(cfg.get("id") or "")
    prices = load_prices()
    models = prices.get("models") or {}
    base = str(prices.get("currency") or "USD")
    fx = prices.get("fx") or {}
    plan = plan_for(profile_id, prices.get("plans") or {})
    mode = str(plan.get("mode") or "token")
    key, entry = match_price(model, models, profile_id)
    fx_ok = True
    cost = 0.0
    equiv = 0.0  # 等价标价：token 模式 = 实付；订阅/免费模式 = 按官方标价折算的参考金额
    if entry:
        converted, fx_ok = convert_cost(compute_cost(usage, entry), str(entry.get("currency") or base), fx, base)
        equiv = converted
        if mode == "token":
            cost = converted
    rec = {
        "ts": _now(),
        "session_id": str(ctx.get("session_id") or ""),
        "session_title": str(ctx.get("session_title") or ""),
        "profile_id": profile_id,
        "profile_name": str(cfg.get("name") or ""),
        "preset_label": str(ctx.get("preset_label") or ""),
        "model": model,
        "price_key": key,
        "priced": True if mode in ("subscription", "free") else bool(entry),  # 订阅/免费：金额项不适用，不算「缺单价」
        "billing_mode": mode,
        "plan_label": str(plan.get("label") or ""),
        "cost_usd": round(cost, 8),
        "equiv_usd": round(equiv, 8),
        "equiv_priced": bool(entry) and fx_ok,
        "source": str(ctx.get("source") or "chat"),
        **usage,
    }
    if entry and not fx_ok:
        rec["fx_missing"] = str(entry.get("currency") or base).upper()  # 有标价但缺该币种汇率：等价标价记 0
    if usage_missing:
        rec["usage_missing"] = True
    line = json.dumps(rec, ensure_ascii=False)
    with _LOCK:
        path = ledger_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return rec


def _read_records() -> list[dict[str, Any]]:
    path = ledger_path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                out.append(item)
    return out


def _bucket() -> dict[str, Any]:
    return {"cost_usd": 0.0, "equiv_usd": 0.0, "subscription_equiv_usd": 0.0, "calls": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
            "cache_write_tokens": 0, "missing_usage_calls": 0, "subscription_calls": 0, "free_calls": 0,
            "unpriced_calls": 0, "equiv_unpriced_calls": 0, "mode_counts": {}}


def _add(bucket: dict[str, Any], rec: dict[str, Any]) -> None:
    bucket["cost_usd"] += float(rec.get("cost_usd") or 0.0)
    equiv = float(rec.get("equiv_usd") or 0.0)
    bucket["equiv_usd"] += equiv
    bucket["calls"] += 1
    for key in ("prompt_tokens", "completion_tokens", "cached_tokens", "cache_write_tokens"):
        bucket[key] += int(rec.get(key) or 0)
    mode = str(rec.get("billing_mode") or "token")
    counts = bucket["mode_counts"]
    counts[mode] = counts.get(mode, 0) + 1
    if mode == "subscription":
        bucket["subscription_calls"] += 1
        bucket["subscription_equiv_usd"] += equiv
    elif mode == "free":
        bucket["free_calls"] += 1
    elif not rec.get("priced", False):
        bucket["unpriced_calls"] += 1
    if not rec.get("equiv_priced", bool(rec.get("priced", False))):
        bucket["equiv_unpriced_calls"] += 1
    if rec.get("usage_missing"):
        bucket["missing_usage_calls"] += 1


def _finish(bucket: dict[str, Any]) -> dict[str, Any]:
    counts = bucket.pop("mode_counts", {}) or {}
    bucket["billing_mode"] = next(iter(counts)) if len(counts) == 1 else ("mixed" if counts else "token")
    for key in ("cost_usd", "equiv_usd", "subscription_equiv_usd"):
        bucket[key] = round(bucket[key], 8)
    bucket["total_tokens"] = bucket["prompt_tokens"] + bucket["completion_tokens"]
    prompt = bucket["prompt_tokens"]
    # 缓存命中率：长上下文 Agent 的主要成本变量（命中部分按 cache_hit 单价计）
    bucket["cache_hit_rate"] = round(bucket["cached_tokens"] / prompt, 4) if prompt else 0.0
    bucket["miss_input_tokens"] = max(prompt - bucket["cached_tokens"] - bucket["cache_write_tokens"], 0)
    return bucket


def _effective_mode(rec: dict[str, Any], plans: dict[str, Any]) -> str:
    mode = str(rec.get("billing_mode") or "").strip()
    if mode in PLAN_MODES:
        return mode
    return str(plan_for(str(rec.get("profile_id") or ""), plans).get("mode") or "token")


def _view(rec: dict[str, Any], plans: dict[str, Any], models: dict[str, Any] | None = None,
          base: str = "USD", fx: dict[str, float] | None = None) -> dict[str, Any]:
    """视图层补齐计费方式与「等价标价」（不改账本文件——账本只增不改）。

    - 老账本（v261008 早期）没有 `billing_mode`：按「当前 plans 声明」推导，订阅/免费档案的历史调用即归位；
    - 没有 `equiv_usd` 的老记录：用**当前单价表**折算一次等价标价（只读视图，token 模式的
      `cost_usd` 仍然冻结在写入时的值，不改历史实付口径）。
    """
    mode_known = str(rec.get("billing_mode") or "") in PLAN_MODES
    if mode_known and rec.get("equiv_usd") is not None:
        return rec
    out = dict(rec)
    plan = plan_for(str(rec.get("profile_id") or ""), plans)
    mode = str(rec.get("billing_mode") or plan.get("mode") or "token")
    out["billing_mode"] = mode
    if mode != "token":
        out["priced"] = True  # 订阅/免费：金额项不适用
        out.setdefault("plan_label", str(plan.get("label") or ""))
    if rec.get("equiv_usd") is None:
        entry = match_price(str(rec.get("model") or ""), models or {}, str(rec.get("profile_id") or ""))[1]
        if entry:
            usage = {key: int(rec.get(key) or 0) for key in ("prompt_tokens", "completion_tokens", "cached_tokens", "cache_write_tokens")}
            converted, ok = convert_cost(compute_cost(usage, entry), str(entry.get("currency") or base), fx or {}, base)
            out["equiv_usd"] = round(converted, 8)
            out["equiv_priced"] = ok
        else:
            out["equiv_usd"] = 0.0
            out["equiv_priced"] = False
    return out


def summary() -> dict[str, Any]:
    """按会话 / 模型 / 日期聚合 + 订阅档案用量与等价标价 + 缺单价清单（v261008b）。"""
    prices = load_prices()
    plans_cfg = prices.get("plans") or {}
    models_cfg = prices.get("models") or {}
    base = str(prices.get("currency") or "USD")
    fx = prices.get("fx") or {}
    records = [_view(rec, plans_cfg, models_cfg, base, fx) for rec in _read_records()]
    total = _bucket()
    for rec in records:
        _add(total, rec)
    by_session: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_date: dict[str, dict[str, Any]] = {}
    for rec in records:
        sid = str(rec.get("session_id") or "")
        s = by_session.setdefault(sid, {**_bucket(), "session_id": sid, "title": str(rec.get("session_title") or "")})
        if not s["title"] and rec.get("session_title"):
            s["title"] = str(rec["session_title"])
        _add(s, rec)
        model = str(rec.get("model") or "(未知)")
        m = by_model.setdefault(model, {**_bucket(), "model": model, "priced": bool(rec.get("priced"))})
        _add(m, rec)
        day = str(rec.get("ts") or "")[:10]
        d = by_date.setdefault(day, {**_bucket(), "date": day})
        _add(d, rec)

    # 订阅/免费档案用量（金额项不适用）与缺单价清单（仅 token 模式且未命中单价）
    plans: dict[str, dict[str, Any]] = {}
    unpriced: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in records:
        mode = str(rec.get("billing_mode") or "token")
        if mode != "token":
            pid = str(rec.get("profile_id") or "(未知档案)")
            row = plans.setdefault(pid, {
                "profile_id": pid,
                "label": str(rec.get("plan_label") or rec.get("profile_name") or pid),
                "mode": mode, "calls": 0, "total_tokens": 0, "equiv_usd": 0.0,
            })
            row["calls"] += 1
            row["total_tokens"] += int(rec.get("prompt_tokens") or 0) + int(rec.get("completion_tokens") or 0)
            row["equiv_usd"] += float(rec.get("equiv_usd") or 0.0)
            continue
        if not rec.get("priced", False):
            pid, model = str(rec.get("profile_id") or ""), str(rec.get("model") or "(未知)")
            row = unpriced.setdefault((pid, model), {
                "profile_id": pid,
                "profile_name": str(rec.get("profile_name") or ""),
                "model": model,
                "suggested_key": f"{pid}/{model}" if pid else model,
                "calls": 0, "total_tokens": 0,
            })
            row["calls"] += 1
            row["total_tokens"] += int(rec.get("prompt_tokens") or 0) + int(rec.get("completion_tokens") or 0)

    return {
        "unit": "USD",
        "total": {**_finish(total), "record_count": len(records)},
        "by_session": sorted((_finish(v) for v in by_session.values()), key=lambda x: x["cost_usd"], reverse=True),
        "by_model": sorted((_finish(v) for v in by_model.values()), key=lambda x: x["total_tokens"], reverse=True),
        "by_date": sorted((_finish(v) for v in by_date.values()), key=lambda x: x["date"]),
        "plans": sorted(({**row, "equiv_usd": round(row["equiv_usd"], 8)} for row in plans.values()),
                        key=lambda x: x["calls"], reverse=True),
        "unpriced": sorted(unpriced.values(), key=lambda x: x["calls"], reverse=True),
    }


def records(limit: int = 200, offset: int = 0, session_id: str = "") -> dict[str, Any]:
    prices = load_prices()
    plans_cfg = prices.get("plans") or {}
    models_cfg = prices.get("models") or {}
    base = str(prices.get("currency") or "USD")
    fx = prices.get("fx") or {}
    items = [_view(rec, plans_cfg, models_cfg, base, fx) for rec in _read_records()]
    if session_id:
        items = [x for x in items if str(x.get("session_id") or "") == session_id]
    items.reverse()  # 最新在前
    limit = max(1, min(int(limit or 200), 2000))
    offset = max(0, int(offset or 0))
    return {"total": len(items), "items": items[offset:offset + limit]}


def clear() -> dict[str, Any]:
    path = ledger_path()
    with _LOCK:
        count = len(_read_records())
        path.write_text("", encoding="utf-8")
    return {"ok": True, "removed": count}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
