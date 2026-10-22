"""Presentation scope inferred from explicit source metadata, never reading status."""
import re


def describe(doc: dict) -> dict:
    text = str(doc.get("body") or doc.get("excerpt") or "")[:2400]
    match = re.search(r"(?:证据级别|证据范围)\s*[:：]\s*([^\n]+)", text)
    declared = match.group(1) if match else ""
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    has_pdf = bool(doc.get("attachment_exists") or doc.get("has_pdf") or source.get("type") == "pdf")
    level = "catalog" if doc.get("kind") == "literature" else "note"
    label = "题录" if level == "catalog" else "知识笔记"
    abstract_unavailable = re.search(r"(?:未|无|没有|不含|尚未|尚无).{0,5}摘要|摘要(?:尚未|未|不可|缺失)", declared)
    if ("摘要" in declared and not abstract_unavailable) or "摘要可检索" in (doc.get("tags") or []):
        level, label = "abstract", "公开摘要"
    if has_pdf or re.search(r"PDF\s*全文已提取", declared):
        level, label = "pdf", "有 PDF 全文"
    if re.match(r"已核对原文|已逐条核对原文|已精读原文", declared.strip()):
        level, label = "verified", "已核对原文"
    return {"level": level, "label": label, "has_pdf": has_pdf, "declared": bool(declared)}
