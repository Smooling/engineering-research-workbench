"""文献笔记 · 插件后端 v1.0.0

把两个「文献侧」AI 工具从内核搬出来（docs/SCOPE.md §5.1 铁律：**内核只保留 4 个工具**；
§5.2 原文：`lit_context` / `lit_note_write` 属附属，随插件一起装）：

| 搬出前（内核工具） | 搬出后（插件工具） | 说明 |
| --- | --- | --- |
| `lit_context` | `p_literature-reader__context` | 读：文献元信息 + 批注数 + 笔记全文 |
| `lit_note_write` | `p_literature-reader__note_write` | 写：追加或替换文献笔记 |

**写工具的安全闸门在内核**（本插件不实现确认逻辑）：声明 `write: true` 后，
confirm 模式下内核只生成草稿、用户确认后才以 direct 模式调用本 handler 真正落盘
（见 `app/agent_tools.execute`）。所以这里直接写即可，与搬出前的行为一致。

数据访问一律走 `core_api.lit_*`（文献库由**核心**维护：SCOPE §2.1「文献梳理/阅读进核心」），
插件不自己去读 Workspace 下的 PDF / Notes 文件——那是核心的数据结构（§6 隔离）。
"""

from __future__ import annotations

_MAX_BODY_CHARS = 20000


def _clip(text: str, limit: int = _MAX_BODY_CHARS) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + f"\n…（已截断，原文 {len(text)} 字）"


def register(ctx):
    """注册工具 + 阅读区「笔记」tab 需要的三个接口。"""
    import core_api

    # ---- 阅读区「笔记」tab 的数据面（面板只跟自己的路由打交道）----
    def route_note_get(request):
        q = request.get("query") or {}
        paper_id = str((q.get("paper_id") or [""])[0])
        if not paper_id:
            raise ValueError("paper_id 不能为空")
        return {"paper_id": paper_id, "content": core_api.lit_note(paper_id)}

    def route_note_post(request):
        body = request.get("body") or {}
        paper_id = str(body.get("paper_id") or "")
        if not paper_id:
            raise ValueError("paper_id 不能为空")
        return core_api.lit_note_save(paper_id, str(body.get("content") or ""))

    def route_note_image(request):
        body = request.get("body") or {}
        paper_id = str(body.get("paper_id") or "")
        data_url = str(body.get("data_url") or "")
        if not data_url:
            raise ValueError("data_url 不能为空")
        return core_api.lit_note_image(paper_id, data_url)

    ctx.routes.get("note", route_note_get)
    ctx.routes.post("note", route_note_post)
    ctx.routes.post("note-image", route_note_image)

    def tool_context(args, call_ctx):
        paper_id = str((args or {}).get("paper_id") or (call_ctx or {}).get("paper_id") or "").strip()
        if not paper_id:
            raise ValueError("paper_id 不能为空（未提供且当前上下文无文献）")
        item = core_api.lit_item(paper_id)
        try:
            note = _clip(core_api.lit_note(paper_id))
        except Exception:
            note = ""
        anns = core_api.lit_annotations(paper_id)
        return {
            "paper": {k: item.get(k) for k in
                      ("id", "title", "authors", "year", "venue", "doi", "reading_status", "tags")},
            "annotation_count": len(anns),
            "note": note,
        }

    def tool_note_write(args, call_ctx):
        args = args or {}
        paper_id = str(args.get("paper_id") or (call_ctx or {}).get("paper_id") or "").strip()
        if not paper_id:
            raise ValueError("paper_id 不能为空（未提供且当前上下文无文献）")
        content = str(args.get("content") or "").strip()
        if not content:
            raise ValueError("content 不能为空")
        mode = str(args.get("mode") or "append")
        if mode not in ("append", "replace"):
            raise ValueError("mode 须为 append 或 replace")
        item = core_api.lit_item(paper_id)          # 校验条目存在（含 doc_id 关联）
        cur = str(core_api.lit_note(paper_id) or "")
        next_body = (content if mode == "replace"
                     else (cur.rstrip() + "\n\n" + content + "\n" if cur.strip() else content + "\n"))
        core_api.lit_note_save(paper_id, next_body)
        return {"ok": True, "paper_id": paper_id, "title": item.get("title"), "mode": mode}

    ctx.mcp.tool("context", {
        "description": "读当前文献的元信息、批注数量与笔记全文（不传 paper_id 时用页面上下文里的文献）",
        "parameters": {
            "type": "object",
            "properties": {"paper_id": {"type": "string", "description": "文献 id；缺省用当前页面上下文"}},
        },
    }, tool_context)

    ctx.mcp.tool("note_write", {
        "description": "写当前文献的笔记（mode=append 追加 / replace 覆盖）。写入前会生成草稿等用户确认。",
        "parameters": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "文献 id；缺省用当前页面上下文"},
                "content": {"type": "string", "description": "要写入的 Markdown 正文"},
                "mode": {"type": "string", "enum": ["append", "replace"], "description": "默认 append"},
            },
            "required": ["content"],
        },
        "write": True,
    }, tool_note_write)

    ctx.log("文献阅读工作区插件已注册（工具 p_literature-reader__context / p_literature-reader__note_write；阅读区「笔记」tab）")
