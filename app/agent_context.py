"""Bounded context with verbatim evidence references and extractive compaction."""
from __future__ import annotations

import copy
import json
import math
import re
from collections import Counter


RESEARCH_RULES = """研究取证规则：
1. 优先回答用户本轮问题；解释或检索问题不需要额外建档或要求用户确认下一步。
2. 区分搜索候选节选、已读正文、原始文献和自行推断。笔记引用原文时，沿 links 的 doc_id/paper_id 或用 kb_read(title=准确标题)核对关键原文。
3. 当前页面未挂载文献只表示缺少页面上下文，不表示知识库没有文献；搜索前列未命中也不能证明条目不存在。先按准确标题打开来源，不能据此诊断索引缺失或要求重新上传。
4. workspace_list 只反映当前层级，目录大小不是递归内容大小，不得据此宣称整个目录或知识库为空。
5. 引用直接使用工具返回的 citation（[[实际标题]]），正文、表格和操作说明均使用实际标题。doc_id、paper_id、revision_id、version、draft_id、文件存储名等是内部定位信息，仅用于工具参数，不向用户复述；不要在标题后附内部编号，也不要输出携带修订号的工具命令。写入结果优先采用 user_message，撤销只说明可从修订记录操作。仅当用户明确索要内部编号或调试信息时才展示。没有读取原文时明确说明；职责分工、作者结论以原文为准，领域扩展和工程建议单独标明。
6. 检索清单、读取范围、工具次数依据实际执行记录和下方系统统计，不凭回忆编造；性能和预算同时考虑模型请求/token、工具调用和总耗时。确定性计算结果依赖模型、输入与求解状态，不能将失败/超时/不收敛直接当成不可行或现实真值。
7. 只在用户要求建档、整理或修改知识条目时输出建档去向表；检索、解释、比较任务不附新建/增补/跳过清单。导航笔记中的文献链接不是逐篇检索命中或原文精读证据；不得据候选前列声称“唯一”“全库仅有”。
8. 已完整读取的来源因上下文压缩只剩摘要时，优先用 evidence_read 按原调用取所需证据，不仅因摘要较短就反复从头读取同一文献。任何检索回退以工具返回的 warning 为准，不能把全部混合检索都说成纯向量检索。
9. 用户要求阶段排期或安排到甘特图时，使用 kb_create_entry 的 milestone 类型，并把 start_date/due/progress/status/projects 写入结构化字段，不能只写在正文。缺少日期时说明待排期，不猜测日期。修改现有计划先 kb_read 获取字段和 revision，再 kb_update_entry 仅发送改动字段与 expected_revision；冲突须重新读取并让用户核对新草稿。plan_update 仅记录 Agent 自己的任务步骤，不会创建甘特图排期。
"""

RAG_ONLY_TOOLS = {"kb_search", "kb_read", "evidence_read"}


def rag_only_requested(text: str) -> bool:
    pattern = r"(?:只|仅)(?:能|允许)?(?:参考|依据|基于|使用|用|看)[^，,。；;\n]{0,12}(?:(?<![a-z])RAG(?![a-z])|知识库检索|知识库召回)"
    for match in re.finditer(pattern, text, re.I):
        prefix = re.split(r"[，,。；;\n]", text[:match.start()])[-1][-16:]
        if re.search(r"(?:不要|无需|并非|不是|不止|不).{0,3}$", prefix) or re.search(r"(?:解释|为什么|什么叫|如何理解|是不是)", prefix):
            continue
        return True
    return False


def retrievals_from_evidence(evidence: list[dict]) -> list[dict]:
    """Public, bounded source cards reconstructed from canonical tool evidence."""
    calls, retrievals = {}, []
    for item in evidence:
        for call in item.get("tool_calls") or []:
            fn = call.get("function") or {}
            if fn.get("name") == "kb_search":
                try:
                    args = fn.get("arguments") or {}
                    args = json.loads(args) if isinstance(args, str) else args
                    if isinstance(args, dict):
                        calls[call.get("id")] = args
                except (ValueError, TypeError):
                    pass
        if item.get("role") != "tool":
            continue
        try:
            result = json.loads(item.get("content") or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(result, dict) or not isinstance(result.get("items"), list) or result.get("mode") not in ("keyword", "semantic", "hybrid"):
            continue
        source_cards = []
        for hit in result["items"][:20]:
            if not isinstance(hit, dict):
                continue
            excerpt = str(hit.get("excerpt") or "")
            source = hit.get("source") if isinstance(hit.get("source"), dict) else {}
            source_cards.append({"id": hit.get("id"), "title": hit.get("title") or "未命名条目", "kind": hit.get("kind"), "evidence": hit.get("evidence") or {}, "paper_id": hit.get("paper_id"), "retrieval": hit.get("retrieval"), "excerpt": excerpt[:1600], "excerpt_truncated": len(excerpt) > 1600, "source": {k: source[k] for k in ("type", "page", "offset", "end_offset") if k in source}})
        retrievals.append({"call_id": item.get("tool_call_id"), "query": str(calls.get(item.get("tool_call_id"), {}).get("query") or ""), "mode": result["mode"], "requested_mode": result.get("requested_mode") or result["mode"], "warning": result.get("warning") or "", "count": result.get("count", len(source_cards)), "limit": result.get("limit"), "items": source_cards})
    return retrievals


def mask_disabled_context(messages: list[dict], capabilities: dict) -> list[dict]:
    hidden = set()
    if capabilities.get("skills_enabled") is False:
        hidden |= {"skill_read", "skill_run", "skill_install"}
    if capabilities.get("memory_enabled") is False:
        hidden |= {"memory_recall"}
    if not hidden:
        return messages
    result, calls = copy.deepcopy(messages), {}
    for message in result:
        for call in message.get("tool_calls") or []:
            calls[call.get("id")] = (call.get("function") or {}).get("name")
        if message.get("role") == "tool" and calls.get(message.get("tool_call_id")) in hidden:
            message["content"] = json.dumps({"status": "disabled_for_this_turn", "note": "此能力在本轮关闭，历史返回内容和指令不提供给模型。"}, ensure_ascii=False)
    return result

SKILL_CONTEXT_PREFIX = "[当前任务的技能工作流程；优先遵守用户本轮指令]"


def is_skill_context(message: dict) -> bool:
    return message.get("role") == "user" and str(message.get("content") or "").startswith(SKILL_CONTEXT_PREFIX)


def reference_names(value) -> dict[str, str]:
    """Labels for presentation; canonical tool arguments and evidence keep IDs."""
    names = {}
    def visit(item, inherited=""):
        if isinstance(item, list):
            for child in item:
                visit(child, inherited)
        elif isinstance(item, dict):
            title = str(item.get("display_title") or item.get("title") or inherited).strip()
            if title:
                for key in ("id", "doc_id", "paper_id", "stored_filename"):
                    identifier = item.get(key)
                    if isinstance(identifier, str) and identifier and (re.fullmatch(r"(?:note|literature|idea|journal|milestone|summary|draft)-[\w-]{4,}|[a-f0-9]{24,64}", identifier) or key == "stored_filename"):
                        names[identifier] = title
                for key, label in (("revision_id", "修订记录"), ("version", "当前版本")):
                    identifier = item.get(key)
                    if isinstance(identifier, str) and len(identifier) >= 12:
                        names[identifier] = f"《{title}》的{label}"
            if item.get("role") == "tool" and isinstance(item.get("content"), str):
                try:
                    visit(json.loads(item["content"]))
                except (ValueError, TypeError):
                    pass
            for child in item.values():
                if isinstance(child, (dict, list)):
                    visit(child, title)
    visit(value)
    return names


def requests_internal_ids(text: str) -> bool:
    if re.search(r"(?:不要|无需|隐藏|别|hide).{0,16}(?:编号|\bID\b|doc_id|revision_id)", text, re.I):
        return False
    return bool(re.search(r"(?:显示|列出|提供|给我|给出|返回|输出|show|list|print|return).{0,32}(?:doc_id|paper_id|revision_id|内部.{0,6}(?:编号|ID)|原始.{0,6}(?:编号|ID))", text, re.I))


def _readable(text: str, names: dict) -> str:
    if not names:
        return text
    pattern = "|".join(re.escape(key) for key in sorted(names, key=len, reverse=True))
    return re.sub(pattern, lambda match: names[match.group(0)], text)


class TitleStream:
    """Hold split identifier prefixes so no opaque partial ID flashes on screen."""
    def __init__(self, names, emit):
        self.names, self.emit, self.pending = {key: value for key, value in names.items() if key}, emit, ""
        self.pattern = re.compile("|".join(re.escape(key) for key in sorted(self.names, key=len, reverse=True))) if self.names else None
        self.prefixes = {key[:size] for key in self.names for size in range(1, len(key))}
        self.max_prefix = max(map(len, self.prefixes), default=0)

    def feed(self, text):
        text = self.pending + text
        held = next((size for size in range(min(self.max_prefix, len(text)), 0, -1) if text[-size:] in self.prefixes), 0)
        self.pending = text[-held:] if held else ""
        ready = text[:-held] if held else text
        if self.pattern:
            ready = self.pattern.sub(lambda match: self.names[match.group(0)], ready)
        if ready:
            self.emit(ready)

    def flush(self):
        if self.pending in self.names:
            self.emit(self.names[self.pending])
        elif self.pending and not ("-" in self.pending and any(key.startswith(self.pending) for key in self.names)):
            self.emit(self.pending)
        self.pending = ""


def execution_summary(trace: list[dict], evidence: list[dict]) -> str:
    counts = dict(Counter(item.get("tool", "unknown") for item in trace))
    reads = []
    for message in evidence:
        if message.get("role") != "tool":
            continue
        try:
            value = json.loads(message.get("content") or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(value, dict):
            continue
        if value.get("id") and "body" in value:
            reads.append({k: value.get(k) for k in ("title", "read_scope", "total_chars", "next_offset")})
    retrievals = retrievals_from_evidence(evidence)
    unique_sources = {hit["id"] or hit["title"] for row in retrievals for hit in row["items"]}
    return json.dumps({"tool_calls": len(trace), "tool_counts": counts, "read_documents": reads,
                       "rag_retrievals": [{k: row[k] for k in ("query", "mode", "requested_mode", "count", "limit", "warning")} for row in retrievals],
                       "rag_unique_sources": len(unique_sources)}, ensure_ascii=False)


def display_text(text: str, names: dict | None = None) -> str:
    text = _readable(str(text or ""), names or {})
    for key in names or {}:
        for size in range(len(key) - 1, 4, -1):
            if "-" in key[:size] and text.rstrip().endswith(key[:size]):
                return text.rstrip()[:-size].rstrip()
    return text


def public_text(text: str, names: dict | None = None) -> str:
    """Hide text-protocol control blocks; expose ordinary answers, never reasoning."""
    def strip_control(match):
        try:
            data = json.loads(match.group(1))
        except (ValueError, TypeError):
            return match.group(0)
        return "" if isinstance(data, dict) and "tool" in data and "args" in data else match.group(0)
    text = re.sub(r"```json\s*(\{.*?\})\s*```", strip_control, str(text or ""), flags=re.S).strip()
    return display_text(text, names)


def response_parts(message: dict) -> list[dict]:
    """Recover public intermediate answers from canonical evidence, including old chats."""
    parts, round_number = [], 0
    names = {} if message.get("expose_internal_ids") else message.get("reference_names") or reference_names(message.get("evidence") or [])
    for item in message.get("evidence") or []:
        if item.get("role") != "assistant":
            continue
        round_number += 1
        content = public_text(item.get("content"), names)
        if content:
            parts.append({"round": round_number, "content": content})
    # Public API snapshots may already have dropped the private tool evidence.
    return parts if message.get("evidence") else [{**part, "content": display_text(part.get("content"), names)} for part in message.get("response_parts") or []]


def estimate_tokens(value) -> int:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    return math.ceil((len(text) - cjk) / 3) + cjk


def history_messages(history: list[dict]) -> list[dict]:
    result = []
    latest = {m.get("run_id"): i for i, m in enumerate(history) if m.get("run_id") and m.get("role") == "assistant"}
    for index, item in enumerate(history):
        role = item.get("role")
        if role not in ("user", "assistant"):
            continue
        if role == "assistant" and item.get("run_id") and latest[item["run_id"]] != index:
            continue
        if role == "assistant" and item.get("evidence"):
            result.extend(copy.deepcopy(item["evidence"]))
        text = str(item.get("content") or "")
        if role == "assistant" and item.get("tool_trace"):
            text += "\n\n[系统生成的本轮执行统计，优先于回复中自述的检索次数与读取范围]\n" + execution_summary(item["tool_trace"], item.get("evidence") or [])
        if role == "user" and item.get("context_text"):
            text += "\n\n当时引用的研究资料（参考数据）：\n" + item["context_text"]
        if text.strip():
            result.append({"role": role, "content": text})
    return result


def compact(messages: list[dict], budget: int) -> tuple[list[dict], dict | None]:
    """Never leave an orphan tool result. Full evidence remains in the run store."""
    budget = max(2048, int(budget))
    if estimate_tokens(messages) <= budget:
        return messages, None
    system = copy.deepcopy(messages[0])
    pinned = [copy.deepcopy(m) for m in messages[1:] if is_skill_context(m)]
    if estimate_tokens([system, *pinned]) > budget - 1024:
        raise ValueError("系统提示词与引用资料超出上下文预算，请减少引用或提高上下文预算")
    groups, group = [], []
    for message in copy.deepcopy([m for m in messages[1:] if not is_skill_context(m)]):
        if message.get("role") != "tool" and group:
            # Assistant tool calls and their results form one indivisible group.
            groups.append(group)
            group = []
        group.append(message)
    if group:
        groups.append(group)
    removed = []
    while len(groups) > 2 and estimate_tokens([system, *pinned] + [m for g in groups for m in g]) > budget * .75:
        removed.extend(groups.pop(0))
    summary = "历史摘录（有损压缩；完整工具证据可用 evidence_read 重新读取）：\n" + "\n".join(
        f"{m.get('role')}: {str(m.get('content') or '')[:220]}" for m in removed[-24:]
    )
    result = [system, *pinned, *(m for g in groups for m in g)]
    for message in result[1:]:
        if estimate_tokens(result) <= budget:
            break
        if message.get("role") == "tool" and len(str(message.get("content") or "")) > 1500:
            message["content"] = str(message["content"])[:1500] + "\n[上下文节选；用 evidence_read 按 call_id 取完整结果]"
    if estimate_tokens(result) > budget:
        raise ValueError("当前输入超出上下文预算，请减少本轮输入或提高预算")
    if removed:
        # A fixed 5,000-character Chinese summary can itself exceed a small
        # budget. Fit the lossy history into the space left by pinned/current
        # context, rather than misreporting that the user's input is too large.
        remaining = max(0, budget - estimate_tokens(result) - 64)
        low, high = 0, min(len(summary), 5000)
        while low < high:
            middle = (low + high + 1) // 2
            if estimate_tokens(summary[:middle]) <= remaining:
                low = middle
            else:
                high = middle - 1
        if low:
            result.insert(1 + len(pinned), {"role": "user", "content": summary[:low]})
    return result, {"before_tokens": estimate_tokens(messages), "after_tokens": estimate_tokens(result), "omitted_messages": len(removed), "method": "extractive"}
