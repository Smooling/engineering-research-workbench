"""版本族自动合并（v261020）：让模型逐节选来源，模型不可用时回退到「最新版本」规则。

为什么放在内核：

- 合并的唯一写入收口是 `app/versions.merge_family`，模型调用在 `app/agent`；
- 插件只允许 `from core_api import …`（I3），因此由 `core_api.auto_merge_variants`
  暴露这一个动作，插件不接触 `app`。

调用方（插件页面）只拿到建议，是否落盘由 `apply` 决定。
"""

from __future__ import annotations

import json
from typing import Any

from . import store
from . import versions as V

#: 一次最多分析多少个「有改动」的小节（超出的小节沿用基准，避免上下文爆炸）。
MAX_SECTIONS = 24
#: 每段正文的最大字符数（模型上下文与费用控制）。
MAX_TEXT = 1400
#: 每个小节最多带几个候选版本（按 updated 取最新）。
MAX_CANDIDATES = 4
#: 单次调用最多带几个小节；推理模型一次分析太多会只思考不出结论。
BATCH_SECTIONS = 3
#: 发给模型时每段正文的截断长度（比落盘口径更短，给推理留 token）。
AGENT_TEXT = 350
#: 发给模型时每个小节最多带几个候选。
AGENT_CANDIDATES = 3

SYSTEM_PROMPT = (
    "你是科研笔记的版本合并助手。输入是基条与若干候选版本按 H2 小节切分后的内容。"
    "请为每个「有改动」的小节选择来源：优先信息更完整、结论更可靠、与上下文一致的内容；"
    "仅仅措辞或格式不同时选基准（空字符串）；若某版本整节删除且删除合理，可选该版本（合并后会删掉这一节）。"
    "只输出 JSON 对象，键为 picks（小节标题 → 候选 id 或空字符串）与 reasons（小节标题 → 不超过 40 字的理由）。"
)


def _clip(text: Any, limit: int = MAX_TEXT) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit] + "\n…（已截断）"


def _section_map(body: str) -> dict[str, str]:
    return {s["heading"]: s["text"] for s in V.split_sections(body) if s["heading"]}


def _sort_key(row: dict) -> str:
    return str(row.get("updated") or row.get("variant_at") or row.get("created") or "")


def _collect(base_id: str, variant_ids: list[str] | None) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
    """读取基条与各版本的正文，返回 (基条, 基条小节, 候选版本)。"""
    fam = V.family(base_id)
    if not fam.get("base"):
        raise FileNotFoundError(f"基条不存在：{base_id}")
    base_doc = store.get_doc(base_id)
    base_map = _section_map(base_doc.get("body") or "")
    wanted = {str(x) for x in (variant_ids or []) if str(x).strip()}
    variants: list[dict[str, Any]] = []
    for row in fam.get("variants") or []:
        vid = str(row.get("id") or "")
        if wanted and vid not in wanted:
            continue
        doc = store.get_doc(vid)
        variants.append({
            "id": vid,
            "label": str(row.get("variant_label") or ""),
            "updated": _sort_key(row),
            "sections": _section_map(doc.get("body") or ""),
        })
    return base_doc, base_map, variants


def _changed_sections(base_map: dict[str, str], variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只挑「与基条不同」的小节（含被某版本整节删除的情况）。"""
    out: list[dict[str, Any]] = []
    for heading, base_text in base_map.items():
        if not heading:
            continue
        candidates: list[dict[str, Any]] = []
        for variant in variants:
            text = variant["sections"].get(heading)
            if text is None:
                candidates.append({"id": variant["id"], "label": variant["label"],
                                   "updated": variant["updated"], "deleted": True, "text": ""})
            elif text != base_text:
                candidates.append({"id": variant["id"], "label": variant["label"],
                                   "updated": variant["updated"], "deleted": False, "text": text})
        if candidates:
            candidates.sort(key=lambda c: c["updated"], reverse=True)
            out.append({"heading": heading, "base": base_text, "candidates": candidates})
    return out


def _rule_picks(changed: list[dict[str, Any]]) -> dict[str, str]:
    """回退规则：每个改动小节采用「最近更新」的那个版本。"""
    picks: dict[str, str] = {}
    for row in changed:
        if row["candidates"]:
            picks[row["heading"]] = row["candidates"][0]["id"]
    return picks


def _validate(result: Any, changed: list[dict[str, Any]], variants: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    """只接受已知小节与已知版本 id；其余丢弃。"""
    if not isinstance(result, dict):
        return {}, {}
    headings = {row["heading"] for row in changed}
    valid_ids = {v["id"] for v in variants}
    raw_picks = result.get("picks") if isinstance(result.get("picks"), dict) else {}
    raw_reasons = result.get("reasons") if isinstance(result.get("reasons"), dict) else {}
    picks: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for heading, value in raw_picks.items():
        key = str(heading or "")
        if key not in headings:
            continue
        vid = str(value or "").strip()
        if vid in valid_ids:
            picks[key] = vid
        elif not vid:
            picks[key] = ""
    for heading, value in raw_reasons.items():
        key = str(heading or "")
        if key in headings:
            reasons[key] = _clip(str(value or ""), 80)
    return picks, reasons


def _analyze_chunk(chunk: list[dict[str, Any]], base_doc: dict[str, Any],
                   variants: list[dict[str, Any]], agent_mod: Any, attempts: int = 3):
    """单批分析；推理模型偶尔只思考不出正文，重试到有结果或次数用尽。"""
    payload = {
        "task": "为每个有改动的小节选择来源；不确定时选空字符串保留基准。",
        "base_title": str(base_doc.get("title") or ""),
        "sections": [
            {
                "heading": row["heading"],
                "base": _clip(row["base"], AGENT_TEXT),
                "candidates": [
                    {"id": c["id"], "label": c["label"], "updated": c["updated"],
                     "deleted": c["deleted"], "text": _clip(c["text"], AGENT_TEXT)}
                    for c in row["candidates"][:AGENT_CANDIDATES]
                ],
            }
            for row in chunk
        ],
        "answer": {"picks": {"<小节标题>": "<候选 id 或空字符串>"},
                   "reasons": {"<小节标题>": "不超过 40 字的理由"}},
    }
    text = json.dumps(payload, ensure_ascii=False)
    last: Exception | None = None
    for attempt in range(max(1, attempts)):
        extra = {"reasoning_effort": "low"} if attempt == 0 else {}
        try:
            out = agent_mod.complete_json(SYSTEM_PROMPT, text, temperature=0.0,
                                          max_tokens=1200, request_params=extra)
            picks, reasons = _validate(out.get("json"), chunk, variants)
            if not picks:
                raise ValueError("模型没有给出有效的小节选择")
            return picks, reasons, str(out.get("model") or ""), None
        except Exception as exc:  # noqa: BLE001
            last = exc
    return _rule_picks(chunk), {}, "", str(last)


def _agent_picks(base_doc: dict[str, Any], changed: list[dict[str, Any]],
                 variants: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str], list[str], list[str]]:
    """分批并发请模型逐节选来源；某批最终失败时该批用规则兜底。

    推理型模型一次给太多小节会「只思考不出结论」（content 为空、reasoning 被截断），
    所以按 BATCH_SECTIONS 分批 + 每批最多 3 次重试，并对推理模型传 `reasoning_effort=low`。
    """
    from concurrent.futures import ThreadPoolExecutor

    from . import agent as agent_mod

    chunks = [changed[i:i + BATCH_SECTIONS] for i in range(0, len(changed), BATCH_SECTIONS)]
    picks: dict[str, str] = {}
    reasons: dict[str, str] = {}
    models: list[str] = []
    errors: list[str] = []
    if not chunks:
        return picks, reasons, models, errors
    with ThreadPoolExecutor(max_workers=min(3, len(chunks))) as pool:
        futures = [pool.submit(_analyze_chunk, chunk, base_doc, variants, agent_mod) for chunk in chunks]
        results = [future.result() for future in futures]
    for batch_picks, batch_reasons, model, error in results:
        picks.update(batch_picks)
        reasons.update(batch_reasons)
        if model:
            models.append(model)
        if error:
            errors.append(error)
    return picks, reasons, models, errors


def propose_picks(base_id: str, *, strategy: str = "agent", variant_ids: list[str] | None = None,
                  apply: bool = False, archive_merged: bool = False,
                  origin: dict[str, str] | None = None) -> dict[str, Any]:
    """给出逐节来源建议；`apply=True` 时直接写回基条。

    strategy:
      - ``agent``（默认）：调用已配置模型；失败自动回退到规则，并在 note 里说明原因；
      - ``rule``：只用「最新版本优先」规则，不调用模型。
    """
    base_doc, base_map, variants = _collect(base_id, variant_ids)
    changed = _changed_sections(base_map, variants)
    strategy = str(strategy or "agent").strip().lower()
    mode = "noop"
    picks: dict[str, str] = {}
    reasons: dict[str, str] = {}
    note = ""
    model = ""

    if not variants:
        note = "这一族没有活版本，无需合并"
    elif not changed:
        note = "正文与基条一致，没有需要确认的小节"
    elif strategy == "rule":
        mode = "rule"
        picks = _rule_picks(changed)
        note = "按「最近更新优先」规则选择（未调用模型）"
    else:
        try:
            picks, reasons, models, errors = _agent_picks(base_doc, changed[:MAX_SECTIONS], variants)
            model = next((m for m in models if m), "")
            if not models:
                raise ValueError(errors[0] if errors else "模型没有返回结果")
            if not picks:
                raise ValueError("模型没有给出有效的小节选择")
            mode = "agent"
            note = f"模型 {model or '（未命名）'} 已逐节分析 {min(len(changed), MAX_SECTIONS)} 处改动；可逐节调整后再应用"
            if errors:
                note += f"；{len(errors)} 段模型未返回结果，已按规则回退"
        except Exception as exc:  # noqa: BLE001 —— 无模型/解析失败都回退，不让页面卡死
            mode = "rule-fallback"
            picks = _rule_picks(changed)
            note = f"模型不可用，已回退到「最近更新优先」规则：{exc}"

    ignored = max(0, len(changed) - MAX_SECTIONS)
    if ignored:
        note += f"；另有 {ignored} 处改动超出单次分析上限，沿用基准"

    merge: dict[str, Any] | None = None
    if apply and picks:
        merge = V.merge_family(base_id, picks, archive_merged=archive_merged,
                               origin_info=dict(origin or V.origin("plugin", "auto_merge")))

    adopt_count = sum(1 for value in picks.values() if value)
    keep_count = sum(1 for value in picks.values() if not value)
    return {
        "base_id": base_id,
        "mode": mode,
        "model": model,
        "changed_sections": len(changed),
        "analyzed_sections": min(len(changed), MAX_SECTIONS),
        "picks": picks,
        "reasons": reasons,
        "adopt_count": adopt_count,
        "keep_count": keep_count,
        "note": note,
        "applied": bool(merge),
        "merge": merge,
    }
