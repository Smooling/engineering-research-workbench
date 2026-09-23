from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from .perf_index_core import _connect, _init_db, sync

DEFAULT_LIMIT = 6
MAX_LIMIT = 12
CANDIDATE_LIMIT = 240
PASSAGE_CHARS = 2400

_GENERIC_TERMS = {
    "什么", "为什么", "怎么", "如何", "之前", "以前", "关于", "这个", "那个", "这些", "那些",
    "进行", "一个", "一些", "是否", "可以", "需要", "已经", "现在", "当时", "考虑", "里面",
    "the", "and", "for", "with", "from", "what", "why", "how", "this", "that", "about",
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
    limit = max(1, min(MAX_LIMIT, int(raw.get("limit") or DEFAULT_LIMIT)))
    return {
        "enabled": bool(raw.get("enabled", False)),
        "project": str(raw.get("project") or "").strip(),
        "tags": _clean_list(raw.get("tags")),
        "kinds": _clean_list(raw.get("kinds")),
        "limit": limit,
        "expand_wikilinks": raw.get("expand_wikilinks", True) is not False,
    }


def _query_terms(query: str) -> list[str]:
    query = str(query or "").strip()
    terms: list[str] = []

    def add(term: str) -> None:
        term = term.strip().casefold()
        if len(term) < 2 or term in _GENERIC_TERMS or term in terms:
            return
        terms.append(term)

    for token in re.findall(r"[A-Za-z][A-Za-z0-9_.+\-/]{1,}", query):
        add(token)

    for seq in re.findall(r"[\u4e00-\u9fff]{2,}", query):
        if len(seq) <= 8:
            add(seq)
        for n in (4, 3, 2):
            if len(seq) < n:
                continue
            for i in range(0, len(seq) - n + 1):
                add(seq[i:i+n])
                if len(terms) >= 24:
                    return terms
    return terms[:24]


def _where(options: dict[str, Any], alias: str = "d") -> tuple[list[str], list[Any]]:
    where = ["1=1"]
    params: list[Any] = []
    project = options["project"]
    if project:
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


def _row_payload(row: Any) -> dict[str, Any]:
    import json

    def loads_list(value: Any) -> list[str]:
        try:
            parsed = json.loads(str(value or "[]"))
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except Exception:
            return []

    return {
        "id": str(row["id"]),
        "title": str(row["title"] or row["id"]),
        "kind": str(row["kind"] or ""),
        "status": str(row["status"] or ""),
        "project": str(row["project"] or ""),
        "projects": loads_list(row["projects_json"]),
        "project_id": str(row["project_id"] or ""),
        "project_ids": loads_list(row["project_ids_json"]),
        "tags": loads_list(row["tags_json"]),
        "updated": str(row["updated"] or row["created"] or ""),
        "excerpt": str(row["excerpt"] or ""),
        "body": str(row["body_text"] or ""),
    }


def _candidate_rows(conn, terms: list[str], options: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    where, params = _where(options)
    sql_where = " AND ".join(where)
    candidates: dict[str, dict[str, Any]] = {}
    fts_bonus: dict[str, float] = {}

    fts_terms = [t for t in terms if len(t) >= 3][:14]
    for term_index, term in enumerate(fts_terms):
        phrase = '"' + term.replace('"', '""') + '"'
        try:
            rows = conn.execute(
                f"""
                SELECT d.*, documents_fts.body AS body_text
                FROM documents_fts
                JOIN documents d ON d.id=documents_fts.doc_id
                WHERE documents_fts MATCH ? AND {sql_where}
                ORDER BY bm25(documents_fts)
                LIMIT 36
                """,
                [phrase, *params],
            ).fetchall()
        except Exception:
            rows = []
        for rank, row in enumerate(rows):
            doc_id = str(row["id"])
            candidates.setdefault(doc_id, _row_payload(row))
            fts_bonus[doc_id] = fts_bonus.get(doc_id, 0.0) + max(0.15, 1.8 - rank * 0.07) / (1 + term_index * 0.08)

    rows = conn.execute(
        f"""
        SELECT d.*, f.body AS body_text
        FROM documents d
        JOIN documents_fts f ON f.doc_id=d.id
        WHERE {sql_where}
        ORDER BY COALESCE(NULLIF(d.updated,''), d.created) DESC
        LIMIT ?
        """,
        [*params, CANDIDATE_LIMIT],
    ).fetchall()
    for row in rows:
        candidates.setdefault(str(row["id"]), _row_payload(row))
    return candidates, fts_bonus


def _count_hit(text: str, term: str, cap: int = 4) -> int:
    if not text or not term:
        return 0
    return min(cap, text.count(term))


def _freshness_bonus(updated: str) -> float:
    if not updated:
        return 0.0
    try:
        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400)
        return 0.45 * math.exp(-age_days / 240.0)
    except Exception:
        return 0.0


def _lexical_score(doc: dict[str, Any], query: str, terms: list[str], fts_score: float = 0.0) -> tuple[float, dict[str, Any]]:
    title = doc["title"].casefold()
    body = doc["body"].casefold()
    tags = " ".join(doc["tags"]).casefold()
    projects = " ".join(doc["projects"]).casefold()
    q = query.casefold().strip()

    score = min(4.2, fts_score)
    title_terms: list[str] = []
    body_terms: list[str] = []
    tag_terms: list[str] = []
    project_terms: list[str] = []
    matched: set[str] = set()

    if len(q) >= 3 and q in title:
        score += 8.0
    elif len(q) >= 5 and q in body:
        score += 5.0

    for term in terms:
        if term in title:
            title_terms.append(term)
            matched.add(term)
            score += 3.0
        bh = _count_hit(body, term)
        if bh:
            body_terms.append(term)
            matched.add(term)
            score += 0.8 + 0.38 * bh
        if term in tags:
            tag_terms.append(term)
            matched.add(term)
            score += 2.2
        if term in projects:
            project_terms.append(term)
            matched.add(term)
            score += 1.0

    if terms:
        score += 3.4 * (len(matched) / len(terms))
    score += _freshness_bonus(doc["updated"])

    evidence = {
        "title_terms": title_terms[:6],
        "body_terms": body_terms[:8],
        "tag_terms": tag_terms[:5],
        "project_terms": project_terms[:5],
        "fts": fts_score > 0,
        "coverage": round(len(matched) / max(1, len(terms)), 3),
    }
    return score, evidence


def _section_candidates(body: str) -> list[tuple[list[str], str]]:
    lines = str(body or "").splitlines()
    stack: list[tuple[int, str]] = []
    out: list[tuple[list[str], str]] = []
    buf: list[str] = []
    current_path: list[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal buf
        text = "\n".join(buf).strip()
        if text:
            out.append((list(current_path), text))
        buf = []

    fence = chr(96) * 3
    for line in lines:
        if line.lstrip().startswith(fence):
            in_fence = not in_fence
            buf.append(line)
            continue
        m = None if in_fence else re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            flush()
            level = len(m.group(1))
            heading = m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
            current_path = [x[1] for x in stack]
            continue
        buf.append(line)
    flush()
    return out or [([], body.strip())]


def _trim_passage(text: str, terms: list[str], limit: int = PASSAGE_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    low = text.casefold()
    positions = [low.find(t) for t in terms if low.find(t) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - limit // 3)
    end = min(len(text), start + limit)
    start = max(0, text.rfind("\n", 0, start) + 1)
    tail = text.find("\n", end)
    if tail >= 0 and tail - start <= limit + 240:
        end = tail
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def _best_passage(doc: dict[str, Any], query: str, terms: list[str]) -> tuple[str, str]:
    sections = _section_candidates(doc["body"])
    best_path: list[str] = []
    best_text = doc["excerpt"] or doc["body"][:PASSAGE_CHARS]
    best_score = -1.0
    q = query.casefold().strip()
    for path, text in sections:
        hay = (" ".join(path) + "\n" + text).casefold()
        score = 0.0
        if len(q) >= 5 and q in hay:
            score += 8.0
        for term in terms:
            if any(term in h.casefold() for h in path):
                score += 3.0
            score += min(3, hay.count(term)) * 0.8
        if score > best_score:
            best_score = score
            best_path = path
            best_text = text
    heading = " > ".join(best_path[-3:])
    return heading, _trim_passage(best_text, terms)


def _passes_filter_doc(doc: dict[str, Any], options: dict[str, Any]) -> bool:
    project = options["project"]
    if project and project not in doc["projects"] and project not in doc["project_ids"] and project not in (doc["project"], doc["project_id"]):
        return False
    if options["kinds"] and doc["kind"] not in options["kinds"]:
        return False
    tags = set(doc["tags"])
    return all(tag in tags for tag in options["tags"])


def _fetch_docs(conn, ids: set[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT d.*, f.body AS body_text
        FROM documents d JOIN documents_fts f ON f.doc_id=d.id
        WHERE d.id IN ({marks})
        """,
        list(ids),
    ).fetchall()
    return {str(r["id"]): _row_payload(r) for r in rows}


def retrieve(query: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    query = str(query or "").strip()
    opts = normalize_options(options)
    if not query:
        return {"query": query, "items": [], "meta": {"reason": "empty_query", "options": opts}}

    terms = _query_terms(query)
    sync()
    with _connect() as conn:
        _init_db(conn)
        candidates, fts_bonus = _candidate_rows(conn, terms, opts)

        scored: dict[str, dict[str, Any]] = {}
        for doc_id, doc in candidates.items():
            score, evidence = _lexical_score(doc, query, terms, fts_bonus.get(doc_id, 0.0))
            if score < 2.15 and not evidence["fts"]:
                continue
            scored[doc_id] = {
                "doc": doc,
                "score": score,
                "evidence": evidence,
                "source": "keyword",
                "expanded_from": [],
            }

        seeds = sorted(scored.values(), key=lambda x: x["score"], reverse=True)[:4]
        if opts["expand_wikilinks"] and seeds:
            seed_ids = {x["doc"]["id"] for x in seeds}
            marks = ",".join("?" for _ in seed_ids)
            rows = conn.execute(
                f"""
                SELECT source,target FROM graph_edges
                WHERE relation='wikilink' AND (source IN ({marks}) OR target IN ({marks}))
                """,
                [*seed_ids, *seed_ids],
            ).fetchall()
            neighbors: dict[str, list[str]] = {}
            linked_ids: set[str] = set()
            for row in rows:
                a, b = str(row["source"]), str(row["target"])
                if a in seed_ids:
                    linked_ids.add(b)
                    neighbors.setdefault(b, []).append(a)
                if b in seed_ids:
                    linked_ids.add(a)
                    neighbors.setdefault(a, []).append(b)
            linked_docs = _fetch_docs(conn, linked_ids)
            seed_map = {x["doc"]["id"]: x for x in seeds}
            for doc_id, doc in linked_docs.items():
                if doc_id in scored or not _passes_filter_doc(doc, opts):
                    continue
                parent_ids = [x for x in neighbors.get(doc_id, []) if x in seed_map]
                if not parent_ids:
                    continue
                parent = max((seed_map[x] for x in parent_ids), key=lambda x: x["score"])
                lexical, evidence = _lexical_score(doc, query, terms, fts_bonus.get(doc_id, 0.0))
                graph_score = min(4.0, parent["score"] * 0.28) + 1.35
                scored[doc_id] = {
                    "doc": doc,
                    "score": lexical + graph_score,
                    "evidence": evidence,
                    "source": "wikilink",
                    "expanded_from": [seed_map[x]["doc"]["title"] for x in parent_ids[:3]],
                }

    ranked = sorted(
        scored.values(),
        key=lambda x: (x["score"], x["doc"]["updated"]),
        reverse=True,
    )[:opts["limit"]]

    items: list[dict[str, Any]] = []
    for rank, item in enumerate(ranked, 1):
        doc = item["doc"]
        heading, passage = _best_passage(doc, query, terms)
        ev = item["evidence"]
        reasons: list[str] = []
        if ev["title_terms"]:
            reasons.append("标题命中：" + " / ".join(ev["title_terms"][:3]))
        if ev["tag_terms"]:
            reasons.append("标签命中：" + " / ".join(ev["tag_terms"][:3]))
        if ev["body_terms"]:
            reasons.append("正文命中：" + " / ".join(ev["body_terms"][:4]))
        if ev["fts"]:
            reasons.append("FTS5 候选")
        if item["source"] == "wikilink":
            reasons.append("WikiLink：" + " / ".join(item["expanded_from"]))
        items.append({
            "rank": rank,
            "id": doc["id"],
            "title": doc["title"],
            "kind": doc["kind"],
            "project": doc["project"],
            "projects": doc["projects"],
            "tags": doc["tags"],
            "updated": doc["updated"],
            "score": round(float(item["score"]), 3),
            "source": item["source"],
            "expanded_from": item["expanded_from"],
            "reason": "；".join(reasons) or "关键词相关",
            "heading": heading,
            "passage": passage,
        })

    return {
        "query": query,
        "terms": terms,
        "items": items,
        "meta": {
            "options": opts,
            "candidate_count": len(candidates),
            "qualified_count": len(scored),
            "returned": len(items),
            "retrieval": "FTS5 + metadata filters + WikiLink expansion + deterministic rerank",
        },
    }
