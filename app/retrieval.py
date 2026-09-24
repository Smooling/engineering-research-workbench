from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from .perf_index_core import _connect, _init_db, ensure_rag_units, sync

DEFAULT_LIMIT = 8
MAX_LIMIT = 20
ROUTE_LIMIT = 36
RRF_K = 60
PASSAGE_CHARS = 3200

_GENERIC_TERMS = {
    "什么", "为什么", "怎么", "如何", "之前", "以前", "关于", "这个", "那个", "这些", "那些",
    "进行", "一个", "一些", "是否", "可以", "需要", "已经", "现在", "当时", "考虑", "里面",
    "以及", "还有", "然后", "最后", "相关", "内容", "资料", "研究", "问题",
    "the", "and", "for", "with", "from", "what", "why", "how", "this", "that", "about",
}

_KIND_LABEL = {
    "idea": "灵感",
    "journal": "研究日志",
    "note": "笔记",
    "milestone": "里程碑",
    "summary": "工作总结",
    "literature": "文献",
}


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[,，]", value)
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def normalize_options(options: dict[str, Any] | None) -> dict[str, Any]:
    raw = options if isinstance(options, dict) else {}
    project_mode = str(raw.get("project_mode") or ("strict" if raw.get("project") else "all")).strip().lower()
    if project_mode not in {"all", "prefer", "strict"}:
        project_mode = "all"
    return {
        "enabled": bool(raw.get("enabled", False)),
        "project": str(raw.get("project") or "").strip(),
        "project_mode": project_mode,
        "tags": _clean_list(raw.get("tags")),
        "kinds": _clean_list(raw.get("kinds")),
        "limit": max(1, min(MAX_LIMIT, int(raw.get("limit") or DEFAULT_LIMIT))),
        "expand_wikilinks": raw.get("expand_wikilinks", True) is not False,
        "multi_query": raw.get("multi_query", True) is not False,
        "adaptive_second_pass": raw.get("adaptive_second_pass", True) is not False,
        "candidate_limit": max(20, min(200, int(raw.get("candidate_limit") or 80))),
    }


def _query_terms(query: str, max_terms: int = 28) -> list[str]:
    query = str(query or "").strip()
    terms: list[str] = []

    def add(term: str) -> None:
        term = term.strip().casefold()
        if len(term) < 2 or term in _GENERIC_TERMS or term in terms:
            return
        terms.append(term)

    for quoted in re.findall(r'["“](.+?)["”]', query):
        add(quoted)

    for token in re.findall(r"[A-Za-z][A-Za-z0-9_.+\-/]{1,}", query):
        add(token)

    for seq in re.findall(r"[\u4e00-\u9fff]{2,}", query):
        if len(seq) <= 10:
            add(seq)
        for n in (5, 4, 3, 2):
            if len(seq) < n:
                continue
            for i in range(0, len(seq) - n + 1):
                add(seq[i:i+n])
                if len(terms) >= max_terms:
                    return terms
    return terms[:max_terms]


def _query_variants(query: str, terms: list[str], enabled: bool = True) -> list[str]:
    query = str(query or "").strip()
    variants: list[str] = []

    def add(value: str) -> None:
        value = re.sub(r"\s+", " ", str(value or "")).strip()
        if value and value.casefold() not in {x.casefold() for x in variants}:
            variants.append(value)

    add(query)
    if not enabled:
        return variants

    clauses = [x.strip() for x in re.split(r"[，。；;、]|\b(?:and|or|with)\b|以及|并且|同时|还有|然后", query, flags=re.I) if x.strip()]
    for clause in clauses[:4]:
        if len(clause) >= 3:
            add(clause)

    long_terms = [t for t in terms if len(t) >= 3]
    ascii_terms = [t for t in long_terms if re.search(r"[a-z]", t, re.I)]
    chinese_terms = [t for t in long_terms if re.search(r"[\u4e00-\u9fff]", t)]

    if long_terms:
        add(" ".join(long_terms[:10]))
    if ascii_terms:
        add(" ".join(ascii_terms[:8]))
    if chinese_terms:
        add(" ".join(chinese_terms[:8]))

    if len(long_terms) >= 5:
        add(" ".join(long_terms[::2][:8]))
        add(" ".join(long_terms[1::2][:8]))
    return variants[:8]


def _where(options: dict[str, Any], alias: str = "d", strict_project: bool | None = None) -> tuple[list[str], list[Any]]:
    where = ["1=1"]
    params: list[Any] = []
    project = options["project"]
    if strict_project is None:
        strict_project = options.get("project_mode") == "strict"
    if project and strict_project:
        where.append(
            f"EXISTS (SELECT 1 FROM document_projects rp WHERE rp.doc_id={alias}.id "
            "AND (rp.project_name=? OR rp.project_id=?))"
        )
        params.extend([project, project])

    kinds = options["kinds"]
    if kinds:
        marks = ",".join("?" for _ in kinds)
        where.append(f"{alias}.kind IN ({marks})")
        params.extend(kinds)

    for tag in options["tags"]:
        where.append(
            f"EXISTS (SELECT 1 FROM document_tags rt WHERE rt.doc_id={alias}.id AND rt.tag=?)"
        )
        params.append(tag)
    return where, params


def _loads_list(raw: Any) -> list[str]:
    try:
        value = json.loads(str(raw or "[]"))
        return [str(x) for x in value] if isinstance(value, list) else []
    except Exception:
        return []


def _row_payload(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "title": str(row["title"] or row["id"]),
        "kind": str(row["kind"] or ""),
        "status": str(row["status"] or ""),
        "project": str(row["project"] or ""),
        "projects": _loads_list(row["projects_json"]),
        "project_id": str(row["project_id"] or ""),
        "project_ids": _loads_list(row["project_ids_json"]),
        "tags": _loads_list(row["tags_json"]),
        "updated": str(row["updated"] or row["created"] or ""),
    }


def _unit_payload(row: Any) -> dict[str, Any]:
    doc = _row_payload(row)
    return {
        "unit_id": str(row["unit_id"]),
        "doc_id": doc["id"],
        "level": str(row["level"] or ""),
        "ordinal": int(row["ordinal"] or 0),
        "heading": str(row["heading_path"] or ""),
        "text": str(row["unit_text"] or ""),
        "embedding_text": str(row["embedding_text"] or ""),
        "content_hash": str(row["content_hash"] or ""),
        "doc": doc,
    }


def _project_matches(doc: dict[str, Any], options: dict[str, Any]) -> bool:
    project = str(options.get("project") or "")
    if not project:
        return False
    return project in doc["projects"] or project in doc["project_ids"] or project in (doc["project"], doc["project_id"])


def _safe_fts_query(terms: list[str]) -> str:
    usable = [t for t in terms if len(t) >= 3][:12]
    if not usable:
        return ""
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in usable)


def _fts_unit_route(conn, variant: str, options: dict[str, Any], level: str | None = None, route_limit: int = ROUTE_LIMIT) -> list[dict[str, Any]]:
    terms = _query_terms(variant, 18)
    match = _safe_fts_query(terms)
    if not match:
        return []
    where, params = _where(options)
    if level:
        where.append("ru.level=?")
        params.append(level)
    sql_where = " AND ".join(where)
    try:
        rows = conn.execute(
            f"""
            SELECT
                ru.unit_id,ru.doc_id,ru.level,ru.ordinal,ru.heading_path,ru.text AS unit_text,
                ru.embedding_text,ru.content_hash,
                d.*,
                bm25(rag_units_fts) AS bm25_score
            FROM rag_units_fts
            JOIN rag_units ru ON ru.unit_id=rag_units_fts.unit_id
            JOIN documents d ON d.id=ru.doc_id
            WHERE rag_units_fts MATCH ? AND {sql_where}
            ORDER BY bm25_score
            LIMIT ?
            """,
            [match, *params, route_limit],
        ).fetchall()
    except Exception:
        return []
    return [_unit_payload(row) for row in rows]


def _metadata_route(conn, terms: list[str], options: dict[str, Any], route_limit: int = ROUTE_LIMIT) -> list[dict[str, Any]]:
    where, params = _where(options)
    rows = conn.execute(
        f"""
        SELECT
            ru.unit_id,ru.doc_id,ru.level,ru.ordinal,ru.heading_path,ru.text AS unit_text,
            ru.embedding_text,ru.content_hash,
            d.*
        FROM rag_units ru
        JOIN documents d ON d.id=ru.doc_id
        WHERE ru.level IN ('document','section') AND {" AND ".join(where)}
        ORDER BY COALESCE(NULLIF(d.updated,''), d.created) DESC
        LIMIT 800
        """,
        params,
    ).fetchall()

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        unit = _unit_payload(row)
        doc = unit["doc"]
        title = doc["title"].casefold()
        heading = unit["heading"].casefold()
        tags = " ".join(doc["tags"]).casefold()
        score = 0.0
        for term in terms:
            if term in title:
                score += 4.0
            if term in heading:
                score += 3.2
            if term in tags:
                score += 2.8
        if options.get("project_mode") == "prefer" and _project_matches(doc, options):
            score += 1.8
        if score > 0:
            scored.append((score, unit))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored[:route_limit]]


def _rrf_add(scores: dict[str, float], traces: dict[str, list[dict[str, Any]]], route_name: str, items: list[dict[str, Any]], weight: float = 1.0) -> None:
    for rank, unit in enumerate(items, 1):
        unit_id = unit["unit_id"]
        scores[unit_id] += weight / (RRF_K + rank)
        traces[unit_id].append({"route": route_name, "rank": rank, "weight": weight})


def _fetch_units(conn, unit_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not unit_ids:
        return {}
    marks = ",".join("?" for _ in unit_ids)
    rows = conn.execute(
        f"""
        SELECT
            ru.unit_id,ru.doc_id,ru.level,ru.ordinal,ru.heading_path,ru.text AS unit_text,
            ru.embedding_text,ru.content_hash,
            d.*
        FROM rag_units ru JOIN documents d ON d.id=ru.doc_id
        WHERE ru.unit_id IN ({marks})
        """,
        list(unit_ids),
    ).fetchall()
    return {str(row["unit_id"]): _unit_payload(row) for row in rows}


def _fetch_best_unit_for_doc(conn, doc_id: str, query_terms: list[str]) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        SELECT
            ru.unit_id,ru.doc_id,ru.level,ru.ordinal,ru.heading_path,ru.text AS unit_text,
            ru.embedding_text,ru.content_hash,
            d.*
        FROM rag_units ru JOIN documents d ON d.id=ru.doc_id
        WHERE ru.doc_id=? AND ru.level IN ('section','document')
        ORDER BY CASE ru.level WHEN 'section' THEN 0 ELSE 1 END, ru.ordinal
        """,
        (doc_id,),
    ).fetchall()
    best: tuple[float, dict[str, Any]] | None = None
    for row in rows:
        unit = _unit_payload(row)
        hay = (unit["heading"] + "\n" + unit["text"]).casefold()
        score = sum(2.0 if term in unit["heading"].casefold() else 0.0 for term in query_terms)
        score += sum(min(3, hay.count(term)) * 0.7 for term in query_terms)
        if best is None or score > best[0]:
            best = (score, unit)
    return best[1] if best else None


def _graph_expand(conn, seed_units: list[dict[str, Any]], query_terms: list[str], options: dict[str, Any], max_docs: int = 18) -> list[dict[str, Any]]:
    if not options.get("expand_wikilinks") or not seed_units:
        return []
    seed_docs = []
    for unit in seed_units:
        doc_id = unit["doc_id"]
        if doc_id not in seed_docs:
            seed_docs.append(doc_id)
    seed_docs = seed_docs[:8]
    marks = ",".join("?" for _ in seed_docs)
    rows = conn.execute(
        f"""
        SELECT source,target FROM graph_edges
        WHERE relation='wikilink' AND (source IN ({marks}) OR target IN ({marks}))
        """,
        [*seed_docs, *seed_docs],
    ).fetchall()
    linked: list[str] = []
    for row in rows:
        a, b = str(row["source"]), str(row["target"])
        if a in seed_docs and b not in seed_docs and b not in linked:
            linked.append(b)
        if b in seed_docs and a not in seed_docs and a not in linked:
            linked.append(a)

    out: list[dict[str, Any]] = []
    for doc_id in linked[:max_docs]:
        unit = _fetch_best_unit_for_doc(conn, doc_id, query_terms)
        if not unit:
            continue
        doc = unit["doc"]
        if options["project_mode"] == "strict" and not _project_matches(doc, options):
            continue
        if options["kinds"] and doc["kind"] not in options["kinds"]:
            continue
        if options["tags"] and not all(tag in set(doc["tags"]) for tag in options["tags"]):
            continue
        out.append(unit)
    return out


def _freshness_bonus(updated: str) -> float:
    if not updated:
        return 0.0
    try:
        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400)
        return 0.25 * math.exp(-age_days / 300.0)
    except Exception:
        return 0.0


def _rerank_score(unit: dict[str, Any], query: str, terms: list[str], rrf: float, traces: list[dict[str, Any]], options: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    doc = unit["doc"]
    title = doc["title"].casefold()
    heading = unit["heading"].casefold()
    text = unit["text"].casefold()
    tags = " ".join(doc["tags"]).casefold()
    q = query.casefold().strip()

    matched: set[str] = set()
    title_hits: list[str] = []
    heading_hits: list[str] = []
    body_hits: list[str] = []
    tag_hits: list[str] = []
    score = rrf * 120.0

    if len(q) >= 5 and q in (heading + "\n" + text):
        score += 5.0

    for term in terms:
        if term in title:
            title_hits.append(term)
            matched.add(term)
            score += 2.4
        if term in heading:
            heading_hits.append(term)
            matched.add(term)
            score += 2.2
        count = min(4, text.count(term))
        if count:
            body_hits.append(term)
            matched.add(term)
            score += 0.5 + 0.28 * count
        if term in tags:
            tag_hits.append(term)
            matched.add(term)
            score += 1.5

    coverage = len(matched) / max(1, len(terms))
    score += 2.4 * coverage
    if options.get("project_mode") == "prefer" and _project_matches(doc, options):
        score += 2.0
    if unit["level"] == "section":
        score += 0.45
    elif unit["level"] == "chunk":
        score += 0.3
    score += min(0.6, 0.15 * max(0, len(traces) - 1))
    score += _freshness_bonus(doc["updated"])

    evidence = {
        "coverage": round(coverage, 3),
        "title_hits": title_hits[:5],
        "heading_hits": heading_hits[:5],
        "body_hits": body_hits[:6],
        "tag_hits": tag_hits[:5],
        "routes": traces,
    }
    return score, evidence


def _coverage(items: list[dict[str, Any]], terms: list[str]) -> dict[str, Any]:
    useful_terms = [t for t in terms if len(t) >= 3]
    if not useful_terms:
        useful_terms = terms
    combined = "\n".join(
        (item["unit"]["heading"] + "\n" + item["unit"]["text"]).casefold()
        for item in items[:12]
    )
    covered = [term for term in useful_terms if term in combined]
    missing = [term for term in useful_terms if term not in combined]
    ratio = len(covered) / max(1, len(useful_terms))
    docs = {item["unit"]["doc_id"] for item in items[:12]}
    routes = {trace["route"] for item in items[:12] for trace in item["evidence"]["routes"]}
    sufficient = ratio >= 0.58 or (ratio >= 0.42 and len(docs) >= 3 and len(routes) >= 2)
    return {
        "ratio": round(ratio, 3),
        "covered_terms": covered[:12],
        "missing_terms": missing[:12],
        "document_diversity": len(docs),
        "route_diversity": len(routes),
        "sufficient": sufficient,
    }


def _feedback_terms(items: list[dict[str, Any]], original_terms: list[str]) -> list[str]:
    original = set(original_terms)
    counts: Counter[str] = Counter()
    for item in items[:8]:
        unit = item["unit"]
        doc = unit["doc"]
        source = " ".join([doc["title"], unit["heading"], " ".join(doc["tags"])])
        for term in _query_terms(source, 24):
            if term not in original and term not in _GENERIC_TERMS and len(term) >= 3:
                counts[term] += 1
    return [term for term, _ in counts.most_common(10)]


def _collect_routes(conn, query: str, options: dict[str, Any], extra_terms: list[str] | None = None) -> tuple[dict[str, float], dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], list[str], list[str]]:
    terms = _query_terms(query)
    if extra_terms:
        for term in extra_terms:
            if term not in terms:
                terms.append(term)
    variants = _query_variants(query, terms, options.get("multi_query", True))
    if extra_terms:
        variants.append(" ".join(extra_terms[:10]))
        variants.append(" ".join((terms[:6] + extra_terms[:6])))

    scores: dict[str, float] = defaultdict(float)
    traces: dict[str, list[dict[str, Any]]] = defaultdict(list)
    units: dict[str, dict[str, Any]] = {}

    for idx, variant in enumerate(variants[:10]):
        for level, weight in (("document", 0.9), ("section", 1.15), ("chunk", 1.0)):
            rows = _fts_unit_route(conn, variant, options, level=level)
            if not rows:
                continue
            for unit in rows:
                units[unit["unit_id"]] = unit
            _rrf_add(scores, traces, f"fts:{level}:q{idx+1}", rows, weight)

    metadata = _metadata_route(conn, terms, options)
    for unit in metadata:
        units[unit["unit_id"]] = unit
    _rrf_add(scores, traces, "metadata", metadata, 0.85)

    prelim_ids = sorted(scores, key=scores.get, reverse=True)[:16]
    prelim = [units[x] for x in prelim_ids if x in units]
    graph_rows = _graph_expand(conn, prelim, terms, options)
    for unit in graph_rows:
        units[unit["unit_id"]] = unit
    _rrf_add(scores, traces, "wikilink", graph_rows, 0.75)

    return scores, traces, units, terms, variants


def _rank_candidates(scores: dict[str, float], traces: dict[str, list[dict[str, Any]]], units: dict[str, dict[str, Any]], query: str, terms: list[str], options: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for unit_id, rrf in scores.items():
        unit = units.get(unit_id)
        if not unit:
            continue
        score, evidence = _rerank_score(unit, query, terms, rrf, traces.get(unit_id, []), options)
        ranked.append({"unit": unit, "score": score, "rrf": rrf, "evidence": evidence})
    ranked.sort(key=lambda x: (x["score"], x["unit"]["doc"]["updated"]), reverse=True)

    # Diversify the high-recall pool so one long note cannot occupy every slot.
    out: list[dict[str, Any]] = []
    per_doc: Counter[str] = Counter()
    for item in ranked:
        doc_id = item["unit"]["doc_id"]
        cap = 3 if item["unit"]["level"] == "chunk" else 2
        if per_doc[doc_id] >= cap:
            continue
        out.append(item)
        per_doc[doc_id] += 1
        if len(out) >= limit:
            break
    return out


def _display_reason(item: dict[str, Any]) -> str:
    ev = item["evidence"]
    parts: list[str] = []
    if ev["title_hits"]:
        parts.append("标题：" + " / ".join(ev["title_hits"][:3]))
    if ev["heading_hits"]:
        parts.append("章节：" + " / ".join(ev["heading_hits"][:3]))
    if ev["tag_hits"]:
        parts.append("标签：" + " / ".join(ev["tag_hits"][:3]))
    if ev["body_hits"]:
        parts.append("正文：" + " / ".join(ev["body_hits"][:4]))
    route_names = [x["route"] for x in ev["routes"][:6]]
    if route_names:
        parts.append("召回：" + " / ".join(route_names))
    return "；".join(parts) or "多路检索候选"


def _to_items(ranked: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_docs: Counter[str] = Counter()
    for ranked_item in ranked:
        unit = ranked_item["unit"]
        doc = unit["doc"]
        # Final context is smaller than the candidate pool. Keep at most two units per document.
        if seen_docs[doc["id"]] >= 2:
            continue
        seen_docs[doc["id"]] += 1
        passage = unit["text"].strip()
        if len(passage) > PASSAGE_CHARS:
            passage = passage[:PASSAGE_CHARS].rstrip() + "…"
        items.append({
            "rank": len(items) + 1,
            "id": doc["id"],
            "unit_id": unit["unit_id"],
            "level": unit["level"],
            "title": doc["title"],
            "kind": doc["kind"],
            "kind_label": _KIND_LABEL.get(doc["kind"], doc["kind"]),
            "project": doc["project"],
            "projects": doc["projects"],
            "tags": doc["tags"],
            "updated": doc["updated"],
            "score": round(float(ranked_item["score"]), 3),
            "rrf_score": round(float(ranked_item["rrf"]), 6),
            "source": "multi_retrieval",
            "reason": _display_reason(ranked_item),
            "heading": unit["heading"],
            "passage": passage,
            "routes": ranked_item["evidence"]["routes"],
            "coverage": ranked_item["evidence"]["coverage"],
        })
        if len(items) >= limit:
            break
    return items


def retrieve(query: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    query = str(query or "").strip()
    opts = normalize_options(options)
    if not query:
        return {"query": query, "items": [], "meta": {"reason": "empty_query", "options": opts}}

    sync()
    ensure_rag_units(force=False)

    with _connect() as conn:
        _init_db(conn)

        scores, traces, units, terms, variants = _collect_routes(conn, query, opts)
        ranked = _rank_candidates(
            scores, traces, units, query, terms, opts,
            max(opts["candidate_limit"], opts["limit"] * 5),
        )
        first_coverage = _coverage(ranked, terms)

        second_pass = False
        feedback_terms: list[str] = []
        if opts.get("adaptive_second_pass") and not first_coverage["sufficient"]:
            feedback_terms = _feedback_terms(ranked, terms)
            if feedback_terms:
                second_pass = True
                scores2, traces2, units2, terms2, variants2 = _collect_routes(conn, query, opts, feedback_terms)
                for unit_id, value in scores2.items():
                    scores[unit_id] += value
                    traces[unit_id].extend(traces2.get(unit_id, []))
                units.update(units2)
                for term in terms2:
                    if term not in terms:
                        terms.append(term)
                for variant in variants2:
                    if variant not in variants:
                        variants.append(variant)
                ranked = _rank_candidates(
                    scores, traces, units, query, terms, opts,
                    max(opts["candidate_limit"], opts["limit"] * 5),
                )

        final_coverage = _coverage(ranked, terms)
        items = _to_items(ranked, opts["limit"])

    return {
        "query": query,
        "terms": terms,
        "query_variants": variants[:16],
        "items": items,
        "meta": {
            "options": opts,
            "candidate_count": len(ranked),
            "returned": len(items),
            "first_pass_coverage": first_coverage,
            "coverage": final_coverage,
            "second_pass": second_pass,
            "feedback_terms": feedback_terms,
            "retrieval": "Multi-Query + Document/Section/Chunk FTS5 + Metadata + WikiLink + RRF + adaptive second pass",
            "embedding_enabled": False,
        },
    }
