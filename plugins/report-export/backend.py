"""报告导出 · 插件后端 v1.0.0

把知识库条目整理成**可交付文档**：

| 格式 | 怎么产出 | 为什么要这样 |
| --- | --- | --- |
| **DOCX** | 纯标准库写 OOXML（`zipfile` + 手写 `document.xml`） | 工作台跑在**用户的** Python 上，那里不一定有 `python-docx`（本机实测没有）。`.docx` 本质是装 XML 的 ZIP，标准库足够写出一份 Word 能正常打开的文档——插件「丢进去就能用」，零第三方依赖 |
| **HTML** | 同一份内容渲染成自包含 HTML，带打印样式 | 浏览器 `打印 → 另存为 PDF` 就是 PDF：中文与字体交由系统处理，效果比任何纯 Python 方案都好，同样零依赖 |
| **Markdown** | 原文拼装 | 便于再加工（贴进别的工具、进版本库） |

数据一律走 `core_api` 的只读窗口（`entries/entry/projects/kind_labels`，与前端 `/api/docs` 同源同量），
**不直接读 `Workspace/Knowledge/*.md`** —— 绕过索引会看到过期或半写状态（PLUGIN_SPEC §6 隔离）。

导出文件只写自己的命名空间 `Workspace/Plugins/report-export/exports/`，下载接口做路径安全校验。
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime
from html import escape as html_escape
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import core_api

EXPORT_DIRNAME = "exports"
MAX_ENTRIES = 500                      # 单份报告最多收录条目数（防手滑导出整库到卡死）
FORMATS = ("docx", "html", "md")
DEFAULT_OPTIONS = {
    "include_body": True,              # 收录正文
    "include_meta": True,              # 收录状态/项目/标签/时间
    "split_by_kind": True,             # 按 kind 分章
    "max_entries": 200,
}


# ---------------------------------------------------------------- 取数

def _scope_entries(scope: dict, opts: dict) -> tuple[str, list[dict]]:
    """按范围取条目（含正文），返回 (报告标题, 条目列表)。"""
    stype = str((scope or {}).get("type") or "all")
    svalue = str((scope or {}).get("value") or "")
    limit = max(1, min(MAX_ENTRIES, int(opts.get("max_entries") or DEFAULT_OPTIONS["max_entries"])))

    if stype == "project":
        rows = core_api.entries(project=svalue, limit=limit)
        title = f"{svalue} · 项目报告"
    elif stype == "kind":
        rows = core_api.entries(svalue or None, limit=limit)
        title = f"{core_api.kind_labels().get(svalue, svalue)} · 汇总报告"
    else:
        rows = core_api.entries(limit=limit)
        title = "知识库全量报告"

    if not rows:
        return title, []

    if opts.get("include_body", True):
        out = []
        for row in rows:
            try:
                out.append(core_api.entry(row["id"]))   # 单条取全文（列表接口不含正文）
            except FileNotFoundError:
                continue
        return title, out
    return title, rows


def _groups(entries: list[dict], opts: dict) -> list[tuple[str, list[dict]]]:
    """按契约顺序分组（`split_by_kind` 关掉时只分一组）。"""
    labels = core_api.kind_labels()
    if not opts.get("split_by_kind", True):
        return [("", entries)]
    order = [k for k in core_api.kind_order()]
    buckets: dict[str, list[dict]] = {}
    for e in entries:
        buckets.setdefault(str(e.get("kind") or ""), []).append(e)
    return [(labels.get(k, k), buckets[k]) for k in order if buckets.get(k)] + \
           [(labels.get(k, k), v) for k, v in buckets.items() if k not in order]


# ---------------------------------------------------------------- Markdown → 轻量块

_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_FENCE = re.compile(r"^\s*```")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_STRONG = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_EM = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)")
_CODE = re.compile(r"`([^`]+)`")


def _inline(text: str) -> str:
    """去掉行内标记，保留纯文本（DOCX/HTML 里再按自己的方式强调）。"""
    text = _IMAGE.sub("", text)
    text = _LINK.sub(lambda m: f"{m.group(1)}（{m.group(2)}）" if m.group(2).startswith("http") else m.group(1), text)
    text = _CODE.sub(r"\1", text)
    text = _STRONG.sub(lambda m: m.group(1) or m.group(2), text)
    text = _EM.sub(lambda m: m.group(1) or m.group(2), text)
    return text.strip()


def markdown_blocks(md: str) -> list[tuple[str, str]]:
    """把 Markdown 压成 [(类型, 文本)]，类型取 `h3|li|p|quote|code`。

    刻意只做"能读懂"的降级（标题/列表/引用/代码块/段落），不追求还原富文本：
    报告是给人读的，保真度交给 Markdown/HTML 格式。
    """
    blocks: list[tuple[str, str]] = []
    in_fence = False
    for raw in str(md or "").splitlines():
        line = raw.rstrip()
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            blocks.append(("code", line))
            continue
        if not line.strip():
            blocks.append(("gap", ""))
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            blocks.append(("h3" if len(heading.group(1)) >= 3 else "h3", _inline(heading.group(2))))
            continue
        if _BULLET.match(line):
            blocks.append(("li", _inline(_BULLET.sub("", line))))
            continue
        if line.lstrip().startswith(">"):
            blocks.append(("quote", _inline(line.lstrip().lstrip(">").strip())))
            continue
        if line.lstrip().startswith("|"):          # 表格：先按整行文本收录
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue                            # 对齐行丢掉
            blocks.append(("li", " ｜ ".join(_inline(c) for c in cells)))
            continue
        blocks.append(("p", _inline(line)))
    # 折叠连续空行，去掉首尾空白块
    out: list[tuple[str, str]] = []
    for kind, text in blocks:
        if kind == "gap" and (not out or out[-1][0] == "gap"):
            continue
        out.append((kind, text))
    while out and out[0][0] == "gap":
        out.pop(0)
    while out and out[-1][0] == "gap":
        out.pop()
    return out


def _meta_line(entry: dict) -> str:
    bits = []
    if entry.get("status"):
        bits.append(f"状态：{entry['status']}")
    projects = entry.get("projects") or []
    if projects:
        bits.append("项目：" + "、".join(str(p) for p in projects))
    tags = entry.get("tags") or []
    if tags:
        bits.append("标签：" + "、".join(str(t) for t in tags))
    date = entry.get("record_date") or str(entry.get("updated") or entry.get("created") or "")[:10]
    if date:
        bits.append(f"日期：{date}")
    if entry.get("pinned"):
        bits.append("置顶")
    return "　·　".join(bits)


# ---------------------------------------------------------------- DOCX（纯标准库）

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

#: 中文字体按 eastAsia 指定，西文用 Calibri —— Word/WPS 都认这套
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="宋体" w:cs="Calibri"/>
<w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="300" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:before="0" w:after="240"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="44"/><w:szCs w:val="44"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:before="360" w:after="160"/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:before="280" w:after="120"/><w:outlineLvl w:val="1"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="25"/><w:szCs w:val="25"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:before="220" w:after="100"/><w:outlineLvl w:val="2"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Meta"><w:name w:val="Meta"/><w:basedOn w:val="Normal"/>
<w:rPr><w:color w:val="666666"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/>
<w:pPr><w:ind w:left="420"/></w:pPr><w:rPr><w:i/><w:color w:val="555555"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/>
<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="宋体"/><w:sz w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListItem"><w:name w:val="List Item"/><w:basedOn w:val="Normal"/>
<w:pPr><w:ind w:left="420" w:hanging="210"/></w:pPr></w:style>
</w:styles>"""


def _p(text: str, style: str = "", *, bold: bool = False, bullet: bool = False) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    prefix = "• " if bullet else ""
    return (f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">'
            f'{xml_escape(prefix + str(text or ""))}</w:t></w:r></w:p>')


def _core_props(title: str, generator: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{xml_escape(title)}</dc:title>'
            f'<dc:creator>{xml_escape(generator)}</dc:creator>'
            f'<cp:lastModifiedBy>{xml_escape(generator)}</cp:lastModifiedBy>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{stamp}</dcterms:modified>'
            '</cp:coreProperties>')


def build_docx(paragraphs: list[str], *, title: str, generator: str) -> bytes:
    """把已排好序的段落 XML 打成最小可用的 .docx（Word / WPS / LibreOffice 都能打开）。"""
    body = "".join(paragraphs)
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f'<w:body>{body}'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
                '</w:body></w:document>')
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/document.xml", document)
        z.writestr("docProps/core.xml", _core_props(title, generator))
    return buf.getvalue()


def docx_paragraphs(title: str, subtitle: str, groups: list[tuple[str, list[dict]]], opts: dict) -> list[str]:
    out = [_p(title, "Title"), _p(subtitle, "Meta")]
    for label, rows in groups:
        if label:
            out.append(_p(label, "Heading1"))
        for entry in rows:
            out.append(_p(str(entry.get("title") or entry.get("id")), "Heading2"))
            if opts.get("include_meta", True):
                meta = _meta_line(entry)
                if meta:
                    out.append(_p(meta, "Meta"))
            for kind, text in markdown_blocks(entry.get("body") or ""):
                if not text:
                    out.append(_p(""))
                elif kind == "h3":
                    out.append(_p(text, "Heading3"))
                elif kind == "li":
                    out.append(_p(text, "ListItem", bullet=True))
                elif kind == "quote":
                    out.append(_p(text, "Quote"))
                elif kind == "code":
                    out.append(_p(text, "Code"))
                else:
                    out.append(_p(text, "Normal"))
    return out


# ---------------------------------------------------------------- HTML / Markdown

_HTML_CSS = """body{font:15px/1.75 "Segoe UI","Microsoft YaHei",system-ui,sans-serif;color:#1c1c1e;
max-width:820px;margin:36px auto;padding:0 22px}h1{font-size:26px;margin:0 0 6px}
h2{font-size:20px;margin:34px 0 10px;padding-bottom:6px;border-bottom:1px solid #e3e3e6}
h3{font-size:16px;margin:22px 0 8px}.meta{color:#6b6b70;font-size:12px;margin:0 0 10px}
.sub{color:#6b6b70;font-size:12px;margin:0 0 22px}ul{margin:6px 0 6px 20px}
blockquote{margin:8px 0;padding:4px 12px;border-left:3px solid #d8d8dc;color:#55555a}
pre{background:#f4f4f6;padding:9px 11px;border-radius:6px;font:12px/1.6 Consolas,monospace;overflow-x:auto}
.entry{margin:0 0 26px}@media print{body{margin:0;max-width:none}h2{page-break-after:avoid}
.entry{page-break-inside:avoid}}"""


def build_html(title: str, subtitle: str, groups: list[tuple[str, list[dict]]], opts: dict,
               *, autoprint: bool) -> str:
    parts = [f"<h1>{html_escape(title)}</h1>", f'<p class="sub">{html_escape(subtitle)}</p>']
    for label, rows in groups:
        if label:
            parts.append(f"<h2>{html_escape(label)}</h2>")
        for entry in rows:
            parts.append('<section class="entry">')
            parts.append(f"<h3>{html_escape(str(entry.get('title') or entry.get('id')))}</h3>")
            if opts.get("include_meta", True):
                meta = _meta_line(entry)
                if meta:
                    parts.append(f'<p class="meta">{html_escape(meta)}</p>')
            for kind, text in markdown_blocks(entry.get("body") or ""):
                if not text:
                    continue
                esc = html_escape(text)
                if kind == "h3":
                    parts.append(f"<h4>{esc}</h4>")
                elif kind == "li":
                    parts.append(f"<ul><li>{esc}</li></ul>")
                elif kind == "quote":
                    parts.append(f"<blockquote>{esc}</blockquote>")
                elif kind == "code":
                    parts.append(f"<pre>{esc}</pre>")
                else:
                    parts.append(f"<p>{esc}</p>")
            parts.append("</section>")
    script = "<script>window.addEventListener('load',function(){window.print()})</script>" if autoprint else ""
    return ("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            f"<title>{html_escape(title)}</title><style>{_HTML_CSS}</style></head><body>"
            + "".join(parts) + script + "</body></html>")


def build_markdown(title: str, subtitle: str, groups: list[tuple[str, list[dict]]], opts: dict) -> str:
    out = [f"# {title}", "", f"*{subtitle}*", ""]
    for label, rows in groups:
        if label:
            out += [f"## {label}", ""]
        for entry in rows:
            out += [f"### {entry.get('title') or entry.get('id')}", ""]
            if opts.get("include_meta", True):
                meta = _meta_line(entry).replace("　·　", " · ")
                if meta:
                    out += [f"*{meta}*", ""]
            body = str(entry.get("body") or "").strip()
            if body:
                out += [body, ""]
            else:
                out += ["*（未收录正文）*", ""]
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- 文件名与路径安全

def _slug(text: str, fallback: str = "report") -> str:
    """把报告标题变成安全文件名：保留中文，空格与标点归一成短横线，避免 URL/命令行里要转义。"""
    clean = re.sub(r"[\s　]+", "-", str(text or ""))
    clean = re.sub(r"[\\/:*?\"<>|·—–,，。;；!！?？()（）\[\]{}]+", "-", clean)
    clean = re.sub(r"-{2,}", "-", clean).strip(" .-")
    return (clean[:60] or fallback)


def _export_dir() -> Path:
    path = core_api.workspace_dir("report-export") / EXPORT_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_export_path(name: str) -> Path | None:
    """下载/预览只允许导出目录内的文件（拒绝穿越与绝对路径）。"""
    raw = str(name or "").replace("\\", "/").strip().lstrip("/")
    if not raw or raw.startswith("..") or "/" in raw or _ABS_RE.match(raw):
        return None
    target = (_export_dir() / raw).resolve()
    root = _export_dir().resolve()
    return target if root == target.parent else None


_ABS_RE = re.compile(r"^[A-Za-z]:")


# ---------------------------------------------------------------- 对外接口

def register(ctx):
    ctx.storage.ensure()

    def config() -> dict:
        cfg = dict(DEFAULT_OPTIONS)
        saved = ctx.config_read({})
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in DEFAULT_OPTIONS})
        return cfg

    def capabilities() -> dict:
        return {
            "formats": list(FORMATS),
            "docx_engine": "stdlib（zipfile + OOXML，无第三方依赖）",
            "pdf_hint": "PDF 走「HTML → 浏览器打印 → 另存为 PDF」（中文与字体由系统处理）",
            "max_entries": MAX_ENTRIES,
            "defaults": config(),
            "kind_labels": core_api.kind_labels(),
        }

    def scopes() -> dict:
        projects = []
        for row in core_api.projects():
            projects.append({"value": str(row.get("name") or ""),
                             "docs": int(row.get("docs") or 0),
                             "status": str(row.get("status") or "")})
        counts = core_api.dashboard().get("counts") or {}
        kinds = [{"value": k, "label": core_api.kind_labels().get(k, k),
                  "count": int(counts.get(k) or 0)} for k in core_api.kind_order()]
        all_count = sum(int(counts.get(k) or 0) for k in core_api.kind_order()) or len(core_api.entries(limit=MAX_ENTRIES))
        return {"projects": projects, "kinds": kinds, "total": all_count}

    def _prepare(body: dict) -> tuple[str, list[dict], dict]:
        opts = config()
        for key in DEFAULT_OPTIONS:
            if key in (body or {}):
                opts[key] = body[key]
        opts["max_entries"] = max(1, min(MAX_ENTRIES, int(opts.get("max_entries") or 200)))
        opts["include_body"] = bool(opts.get("include_body", True))
        opts["include_meta"] = bool(opts.get("include_meta", True))
        opts["split_by_kind"] = bool(opts.get("split_by_kind", True))
        title, entries = _scope_entries((body or {}).get("scope") or {}, opts)
        return title, entries, opts

    def preview(request):
        body = request.get("body") or {}
        title, entries, opts = _prepare(body)
        return {
            "title": title, "count": len(entries), "options": opts,
            "items": [{"id": e.get("id"), "kind": e.get("kind"),
                       "kind_label": core_api.kind_labels().get(str(e.get("kind")), str(e.get("kind"))),
                       "title": e.get("title"), "status": e.get("status"),
                       "projects": e.get("projects") or [], "tags": (e.get("tags") or [])[:6],
                       "meta": _meta_line(e),
                       "chars": len(str(e.get("body") or ""))} for e in entries],
        }

    def export(request):
        body = request.get("body") or {}
        fmt = str(body.get("format") or "docx").lower()
        if fmt not in FORMATS:
            return {"ok": False, "error": f"不支持的格式：{fmt}（可选 {'/'.join(FORMATS)}）"}
        title, entries, opts = _prepare(body)
        if not entries:
            return {"ok": False, "error": "该范围没有条目，报告会是空的"}
        groups = _groups(entries, opts)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        generator = "工程科研工作台 · 报告导出插件"
        subtitle = (f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:11]}:{stamp[11:13]} · "
                    f"{len(entries)} 条条目 · 由{generator}生成")
        base = f"{_slug(title)}-{stamp}"
        if fmt == "docx":
            data = build_docx(docx_paragraphs(title, subtitle, groups, opts), title=title, generator=generator)
            ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif fmt == "html":
            data = build_html(title, subtitle, groups, opts, autoprint=False).encode("utf-8")
            ctype = "text/html"
        else:
            data = build_markdown(title, subtitle, groups, opts).encode("utf-8")
            ctype = "text/markdown"
        name = f"{base}.{fmt}"
        path = _export_dir() / name
        path.write_bytes(data)
        ctx.log(f"已导出报告 {name}（{len(entries)} 条 / {len(data)} 字节）")
        # URL 里对文件名做百分号编码：文件名含中文，交给浏览器/命令行时不该要求调用方自己转义
        from urllib.parse import quote

        quoted = quote(name)
        return {"ok": True, "file": name, "bytes": len(data), "entries": len(entries),
                "content_type": ctype, "format": fmt,
                "url": f"/api/plugins/{ctx.id}/download?name={quoted}",
                "print_url": f"/api/plugins/{ctx.id}/view?name={quoted}&print=1" if fmt == "html" else ""}

    def download(request):
        name = str((request["query"].get("name") or [""])[0])
        path = _safe_export_path(name)
        if not path or not path.is_file():
            return {"ok": False, "error": "文件不存在（只允许下载导出目录内的文件）"}
        types = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 ".html": "text/html; charset=utf-8", ".md": "text/markdown; charset=utf-8"}
        return ctx.raw(path.read_bytes(),
                       content_type=types.get(path.suffix.lower(), "application/octet-stream"),
                       filename=path.name)

    def view(request):
        """把 HTML 报告直接给浏览器（PDF = 打印它）。"""
        name = str((request["query"].get("name") or [""])[0])
        path = _safe_export_path(name)
        if not path or path.suffix.lower() != ".html" or not path.is_file():
            return ctx.raw("<h1>只有 HTML 报告可以在浏览器里打开</h1>", content_type="text/html; charset=utf-8",
                           status=404)
        text = path.read_text(encoding="utf-8")
        if str((request["query"].get("print") or [""])[0]) == "1":
            text = text.replace("</body>",
                                "<script>window.addEventListener('load',function(){window.print()})</script></body>")
        return ctx.raw(text, content_type="text/html; charset=utf-8")

    ctx.routes.get("capabilities", lambda request: capabilities())
    ctx.routes.get("scopes", lambda request: scopes())
    ctx.routes.post("preview", preview)
    ctx.routes.post("export", export)
    ctx.routes.get("download", download)
    ctx.routes.get("view", view)

    def tool_scopes(args, call_ctx=None):
        data = scopes()
        return {"projects": data["projects"], "kinds": data["kinds"], "total": data["total"],
                "formats": list(FORMATS)}

    def tool_export(args, call_ctx=None):
        args = args or {}
        request = {"body": {"scope": {"type": str(args.get("scope_type") or "project"),
                                      "value": str(args.get("scope_value") or "")},
                            "format": str(args.get("format") or "docx"),
                            "include_body": bool(args.get("include_body", True)),
                            "max_entries": int(args.get("max_entries") or 100)}}
        result = export(request)
        result["file_dir"] = str(_export_dir())
        return result

    ctx.mcp.tool("list_scopes", {
        "description": "列出可导出报告的范围（项目、条目类别）与可用格式",
        "parameters": {"type": "object", "properties": {}},
    }, tool_scopes)

    ctx.mcp.tool("export_report", {
        "description": ("把某个项目或某类条目导出成交付文档（docx/html/md），返回文件名与所在目录。"
                        "只写插件自己的 exports 目录，不改知识库。"),
        "parameters": {
            "type": "object",
            "properties": {
                "scope_type": {"type": "string", "enum": ["project", "kind", "all"],
                               "description": "范围类型；project 用项目名，kind 用 idea/journal/note/experiment/milestone/summary/literature"},
                "scope_value": {"type": "string", "description": "范围取值（project 填项目名，kind 填类别，all 留空）"},
                "format": {"type": "string", "enum": ["docx", "html", "md"], "description": "导出格式，默认 docx"},
                "include_body": {"type": "boolean", "description": "是否收录正文（默认 true）"},
                "max_entries": {"type": "integer", "description": "最多收录多少条（默认 100，上限 500）"},
            },
            "required": ["scope_type"],
        },
    }, tool_export)

    ctx.log("报告导出插件已注册（/api/plugins/report-export/{capabilities,scopes,preview,export,download,view}）")
