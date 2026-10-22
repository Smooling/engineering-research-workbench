"""指标表 · 插件后端 v1.1.0

**数据表化作为插件**：内核不加新 kind、不动契约，指标就留在**条目正文**里（KB 仍是唯一事实来源），
本插件负责**提取、聚合、透视、缺项提示与导出**。

## 两个数据来源（默认都开）

1. **正文里的 ```metrics 块**（规范形式，最省事也最稳）：

   ````markdown
   ```metrics
   mIoU: 0.732
   Pd: 91%
   ```
   ````

2. **正文里的 Markdown 表格**（**不需要你改写任何东西**）：只要一张表里有「数值列」，
   它就按行变成记录——`| 模型 | #Params/M | mIoU_mean | Pd_mean |` 这样一张表直接产出 9 行指标。
   - 表头行 = 指标名；每个数据行 = 一条记录；
   - **对象列** = 第一个「非数值列」（如 `模型`、`方法`、`数据集`；`排名` 这种数字列会自动跳过）；
   - 其余非数值列（如 `参数量出处`）作为附带信息保留，不进指标列；
   - 小节名 = 该表格上方最近的标题（没有标题就用上一行文字截断）。

> 为什么这么做：一开始只认 `metrics` 块，结果在**已有数据**上打开是一张空表——要求用户先改写正文
> 才能看到价值，这本身就是设计错误。现在**先读现有表格**，想规范化的条目再用写工具升级成块。

## 写路径

- 读：`core_api.entries/entry`（与 `/api/docs` 同源），只读。
- 写：只通过**写工具** `p_metrics-table__record_metrics`（`spec.write = True`）——内核在 confirm 模式下
  先生成草稿，用户确认后才以 direct 模式调用本插件的 handler；handler 里走 `core_api.entry_update`
  （内核的校验写入路径）。插件**不直接改文件**，面板也不提供"直接改条目"的按钮。
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

import core_api

DEFAULT_CONFIG = {
    "block_name": "metrics",          # 正文里的块名（```metrics）
    "sources": ["block", "table"],    # 提取来源：block（块）/ table（正文表格）
    "kinds": ["experiment"],          # 默认只看这些 kind
    "min_numeric_cols": 1,            # 一张表至少要有几个数值列才算指标表
    "numeric_ratio": 0.5,             # 一列里多少比例是数字才算数值列
    "scan_all_kinds": False,          # 关掉就只扫 kinds 里列出的类别
}
MAX_ROWS = 600
MAX_ENTRIES = 400

_NUM = re.compile(r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([^\d\s]*)\s*$")
_STRONG = re.compile(r"\*{1,3}([^*]+)\*{1,3}")
_TITLE_SUFFIX = re.compile(r"[（(]\s*([0-9][0-9.]*[a-z]?)\s*[）)]\s*$")
#: 序数/编号类列名：它们是数字，但不是「指标」，当指标列只会制造噪音（注意别误伤 `#Params/M`）
_ORDINAL = re.compile(r"^(排名|序|序号|编号|档|rank|no\.?|idx|index|#)$", re.IGNORECASE)


# ---------------------------------------------------------------- 基础工具

def clean_cell(text: str) -> str:
    """去掉单元格里的强调标记与多余空白（`**0.7545**` → `0.7545`）。"""
    value = _STRONG.sub(r"\1", str(text or ""))
    return value.replace("`", "").strip()


def split_number(raw: str) -> tuple[float | None, str]:
    """把 `91%` / `3.2e-6` / `25.4M` / `**0.7545**` 拆成 (数值, 单位)。非数值 → (None, 原文)。"""
    text = clean_cell(raw).replace(",", "")
    match = _NUM.match(text)
    if not match:
        return None, text
    try:
        return float(match.group(1)), match.group(2)
    except ValueError:
        return None, text


def is_numberish(raw: str) -> bool:
    value = clean_cell(raw)
    if not value or value in ("-", "—", "–", "/", "N/A", "n/a", "无"):
        return False
    return split_number(value)[0] is not None


# ---------------------------------------------------------------- 来源 1：```metrics 块

def parse_metrics(body: str, block_name: str = "metrics") -> tuple[dict[str, str], list[str]]:
    """从正文里抽 ```<block_name> 块 → ({键: 原始值}, 警告列表)。容错优先：坏行只记警告。"""
    warnings: list[str] = []
    text = str(body or "")
    open_re = re.compile(r"^[ \t]*```[ \t]*" + re.escape(block_name) + r"[ \t]*$", re.MULTILINE)
    metrics: dict[str, str] = {}
    for match in open_re.finditer(text):
        rest = text[match.end():]
        end = re.search(r"^[ \t]*```[ \t]*$", rest, re.MULTILINE)
        if end is None:
            warnings.append(f"```{block_name} 块没有闭合（已忽略这一段）")
            continue
        for raw_line in rest[: end.start()].splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"[:：=]", line, maxsplit=1)
            if len(parts) != 2:
                warnings.append(f"跳过无法解析的行：{line[:40]}")
                continue
            key, value = parts[0].strip(), parts[1].strip()
            if not key:
                warnings.append(f"跳过没有键的行：{line[:40]}")
                continue
            metrics[key] = value
    return metrics, warnings


def upsert_metrics_block(body: str, metrics: dict, mode: str = "merge",
                         block_name: str = "metrics") -> str:
    """把指标写进正文的 ```<block_name> 块：**merge** 合并 / **replace** 整体替换。

    正文其余部分**逐字保留**（只动那个块），块不存在就追加到末尾。
    """
    text = str(body or "")
    incoming = {str(k).strip(): str(v).strip() for k, v in (metrics or {}).items() if str(k).strip()}
    if not incoming:
        raise ValueError("metrics 为空，没什么可写")

    open_re = re.compile(r"^[ \t]*```[ \t]*" + re.escape(block_name) + r"[ \t]*$", re.MULTILINE)
    match = open_re.search(text)
    if match is not None:
        rest = text[match.end():]
        end = re.search(r"^[ \t]*```[ \t]*$", rest, re.MULTILINE)
        if end is None:
            raise ValueError(f"正文里已有的 ```{block_name} 块没有闭合，请先手工修好再写")
        existing: dict[str, str] = {}
        for raw_line in rest[: end.start()].splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"[:：=]", line, maxsplit=1)
            if len(parts) == 2 and parts[0].strip():
                existing[parts[0].strip()] = parts[1].strip()
        merged = dict(existing)
        merged.update(incoming)
        if mode == "replace":
            merged = dict(incoming)
        block = "```" + block_name + "\n" + "\n".join(f"{k}: {v}" for k, v in merged.items()) + "\n```"
        # 注意偏移基准：`end` 是在 `rest`（开围栏之后）里匹配到的，要加回 `match.end()` 才是正文里的绝对位置
        head, tail = text[: match.start()], text[match.end() + end.end():]
        return head + block + tail

    block = "```" + block_name + "\n" + "\n".join(f"{k}: {v}" for k, v in incoming.items()) + "\n```"
    base = text.rstrip()
    return (base + "\n\n" + block + "\n") if base else (block + "\n")


# ---------------------------------------------------------------- 来源 2：Markdown 表格

def parse_tables(body: str) -> list[dict]:
    """把正文里的 Markdown 表格解析出来（不做筛选，筛选交给 extract_records）。

    返回 [{header: [...], rows: [[...]], caption, numeric_cols: [idx], object_col: idx|None, lines: [...]}]
    """
    lines = str(body or "").splitlines()
    tables: list[dict] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip().startswith("|"):
            index += 1
            continue
        start = index
        while index < len(lines) and lines[index].strip().startswith("|"):
            index += 1
        block = [ln for ln in lines[start:index]]
        if len(block) < 3:                      # 至少要有表头 + 分隔 + 一行数据
            continue
        header = [clean_cell(c) for c in block[0].strip().strip("|").split("|")]
        body_rows = []
        for raw in block[1:]:
            cells = [clean_cell(c) for c in raw.strip().strip("|").split("|")]
            if cells and all(set(c) <= set("-: ") for c in cells):
                continue                        # 分隔行
            if any(cells):
                body_rows.append(cells)
        if not body_rows:
            continue

        def ratio(col: int) -> float:
            values = [r[col] for r in body_rows if col < len(r) and r[col]]
            if not values:
                return 0.0
            return sum(1 for v in values if is_numberish(v)) / len(values)

        numeric_ratio_cols = [c for c in range(len(header)) if c < len(header) and ratio(c) >= 0.5]
        # 指标列 = 数值列 - 序数列（排名/编号）；**对象列**要按"是否数值"判断（不能用排除序数后的集合，
        # 否则「排名」会被当成对象列，把对象读成 1/2/3）
        numeric_cols = [c for c in numeric_ratio_cols if not _ORDINAL.match(header[c])]
        object_col = next((c for c in range(len(header)) if c not in numeric_ratio_cols and c < len(header)
                           and header[c]), None)
        caption = ""
        for back in range(start - 1, max(0, start - 14), -1):
            line = lines[back].strip()
            if not line or line.startswith("|"):
                continue
            if line.startswith("#"):
                caption = line.lstrip("# ").strip()
                break
            if not caption:
                caption = line[:60]
        tables.append({
            "header": header, "rows": body_rows, "caption": caption,
            "numeric_cols": numeric_cols, "object_col": object_col,
            "lines": block,
        })
    return tables


def extract_records(row: dict, body: str, cfg: dict) -> tuple[list[dict], list[str]]:
    """一条条目 → 若干记录（块算一条，表格按行算若干条）。"""
    warnings: list[str] = []
    records: list[dict] = []
    base = {
        "entry_id": row.get("id"), "entry_title": row.get("title"), "kind": row.get("kind"),
        "status": row.get("status"), "projects": row.get("projects") or [],
        "date": row.get("record_date") or str(row.get("updated") or row.get("created") or "")[:10],
        "short": _short_label(row),
    }
    if "block" in cfg["sources"]:
        metrics, warn = parse_metrics(body, cfg["block_name"])
        warnings.extend(warn)
        if metrics:
            records.append({**base, "source": "block", "scope": f"```{cfg['block_name']} 块",
                            "object": "", "metrics": metrics, "extra": {}})
    if "table" in cfg["sources"]:
        for table in parse_tables(body):
            if len(table["numeric_cols"]) < int(cfg["min_numeric_cols"]):
                continue
            names = [table["header"][c] for c in table["numeric_cols"]]
            extras = [table["header"][c] for c in range(len(table["header"]))
                      if c not in table["numeric_cols"] and c != table["object_col"] and table["header"][c]]
            for cells in table["rows"]:
                metrics = {}
                for pos, col in enumerate(table["numeric_cols"]):
                    value = cells[col] if col < len(cells) else ""
                    if value and is_numberish(value):
                        metrics[names[pos]] = value
                if not metrics:
                    continue
                obj = cells[table["object_col"]] if (table["object_col"] is not None
                                                     and table["object_col"] < len(cells)) else ""
                extra = {name: (cells[table["header"].index(name)]
                                if table["header"].index(name) < len(cells) else "")
                         for name in extras}
                records.append({**base, "source": "table", "scope": table["caption"] or "（无小节名）",
                                "object": obj or "（未命名行）", "metrics": metrics, "extra": extra})
    return records, warnings


def _short_label(row: dict) -> str:
    """条目的短标签：标题里的（2.2）这种编号，没有就截断标题。"""
    title = str(row.get("title") or "")
    match = _TITLE_SUFFIX.search(title)
    if match:
        return match.group(1)
    short = re.sub(r"^(实验|知识|笔记|文献)-", "", title)
    return short[:12] or str(row.get("id") or "")


# ---------------------------------------------------------------- 聚合

def _columns(records: list[dict]) -> list[dict]:
    order: list[str] = []
    for record in records:
        for key in record["metrics"]:
            if key not in order:
                order.append(key)
    columns = []
    for key in order:
        values: list[float] = []
        units: dict[str, int] = {}
        filled = 0
        for record in records:
            if key not in record["metrics"]:
                continue
            filled += 1
            number, unit = split_number(record["metrics"][key])
            if unit:
                units[unit] = units.get(unit, 0) + 1
            if number is not None:
                values.append(number)
        columns.append({
            "key": key, "filled": filled, "missing": len(records) - filled,
            "numeric": len(values), "unit": max(units, key=units.get) if units else "",
            "min": min(values) if values else None, "max": max(values) if values else None,
            "mean": (sum(values) / len(values)) if values else None,
        })
    return columns


def build_table(records: list[dict]) -> dict:
    columns = _columns(records)
    for record in records:
        record["missing"] = [c["key"] for c in columns if c["key"] not in record["metrics"]]
    return {"rows": records, "columns": columns}


def pivot_by_object(records: list[dict]) -> dict:
    """按对象透视：行 = 对象（模型/方法），列 = `指标@实验`，用于跨实验对照同一对象。

    **同名对象在同一实验里出现多次时不合并**（如 2.1 的 27 组基线是「模型 × 数据集」逐行）：
    用该行第一个附带信息（通常是数据集名）做区分，避免后一行把前一行的数字静默覆盖。
    """
    seen: dict[tuple[str, str], int] = {}
    for record in records:
        obj = record["object"] or record["entry_title"] or "（未命名）"
        seen[(obj, record["short"])] = seen.get((obj, record["short"]), 0) + 1

    labels: list[str] = []
    pairs: list[tuple[str, str]] = []
    cells: dict[tuple[str, str, str], str] = {}
    for record in records:
        base = record["object"] or record["entry_title"] or "（未命名）"
        label = base
        if seen[(base, record["short"])] > 1:      # 同一实验内重复：用附带信息（数据集等）区分
            extras = [v for v in (record.get("extra") or {}).values() if str(v).strip()]
            label = f"{base} · {extras[0]}" if extras else base
        if label not in labels:
            labels.append(label)
        for key, value in record["metrics"].items():
            pair = (key, record["short"])
            if pair not in pairs:
                pairs.append(pair)
            cells[(label, key, record["short"])] = value
    pairs.sort(key=lambda p: (p[0], p[1]))
    columns = []
    for key, short in pairs:
        values: list[float] = []
        units: dict[str, int] = {}
        filled = 0
        for label in labels:
            value = cells.get((label, key, short))
            if value is None:
                continue
            filled += 1
            number, unit = split_number(value)
            if unit:
                units[unit] = units.get(unit, 0) + 1
            if number is not None:
                values.append(number)
        columns.append({"key": f"{key}@{short}", "metric": key, "source": short,
                        "filled": filled, "missing": len(labels) - filled, "numeric": len(values),
                        "unit": max(units, key=units.get) if units else "",
                        "min": min(values) if values else None, "max": max(values) if values else None,
                        "mean": (sum(values) / len(values)) if values else None})
    rows = []
    for label in labels:
        metrics = {}
        for col in columns:
            value = cells.get((label, col["metric"], col["source"]))
            if value is not None:
                metrics[col["key"]] = value
        rows.append({"object": label, "metrics": metrics,
                     "missing": [c["key"] for c in columns if c["key"] not in metrics],
                     "entries": sorted({r["short"] for r in records
                                        if (r["object"] or r["entry_title"] or "（未命名）") in label})})
    return {"rows": rows, "columns": columns, "pivot": True}


# ---------------------------------------------------------------- 导出

def to_csv(table: dict) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    keys = [c["key"] for c in table["columns"]]
    if table.get("pivot"):
        writer.writerow(["对象", "来源实验"] + keys)
        for row in table["rows"]:
            writer.writerow([row["object"], "、".join(row.get("entries") or [])]
                            + [row["metrics"].get(k, "") for k in keys])
    else:
        writer.writerow(["对象", "条目", "实验", "小节", "来源", "状态", "日期"] + keys)
        for row in table["rows"]:
            writer.writerow([row.get("object") or "", row.get("entry_title") or "", row.get("short") or "",
                             row.get("scope") or "", row.get("source") or "", row.get("status") or "",
                             row.get("date") or ""] + [row["metrics"].get(k, "") for k in keys])
    return "\ufeff" + buf.getvalue()          # 带 BOM：Excel 打开中文才不乱码


def to_markdown(table: dict) -> str:
    keys = [c["key"] for c in table["columns"]]
    if not keys:
        return "# 指标表\n\n（没有找到指标：条目里既没有 ```metrics 块，也没有可识别的数值表格）\n"
    if table.get("pivot"):
        head = ["对象", "来源实验"] + keys
        lines = ["| " + " | ".join(head) + " |", "| " + " | ".join(["---"] * len(head)) + " |"]
        for row in table["rows"]:
            lines.append("| " + " | ".join([row["object"], "、".join(row.get("entries") or [])]
                                           + [row["metrics"].get(k, "—") for k in keys]) + " |")
    else:
        head = ["对象", "条目", "实验", "小节", "来源"] + keys
        lines = ["| " + " | ".join(head) + " |", "| " + " | ".join(["---"] * len(head)) + " |"]
        for row in table["rows"]:
            lines.append("| " + " | ".join([str(row.get("object") or ""), str(row.get("entry_title") or ""),
                                            str(row.get("short") or ""), str(row.get("scope") or ""),
                                            str(row.get("source") or "")]
                                           + [row["metrics"].get(k, "—") for k in keys]) + " |")
    return "# 指标表\n\n" + "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 对外接口

def register(ctx):
    ctx.storage.ensure()

    def config() -> dict:
        cfg = dict(DEFAULT_CONFIG)
        saved = ctx.config_read({})
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in DEFAULT_CONFIG})
        cfg["block_name"] = str(cfg.get("block_name") or "metrics").strip() or "metrics"
        sources = cfg.get("sources")
        cfg["sources"] = [s for s in (sources if isinstance(sources, list) else DEFAULT_CONFIG["sources"])
                          if s in ("block", "table")] or ["table"]
        kinds = cfg.get("kinds")
        cfg["kinds"] = [str(k) for k in kinds] if isinstance(kinds, list) else list(DEFAULT_CONFIG["kinds"])
        cfg["min_numeric_cols"] = max(1, int(cfg.get("min_numeric_cols") or 1))
        return cfg

    def _candidate_rows(project: str, kind: str, cfg: dict) -> list[dict]:
        if kind:
            return core_api.entries(kind, project=project, limit=MAX_ENTRIES)
        kinds = list(cfg["kinds"] or ["experiment"])
        if cfg.get("scan_all_kinds") or project:
            kinds = list(core_api.kind_order())
        rows: list[dict] = []
        seen: set[str] = set()
        for k in kinds:
            for row in core_api.entries(k, project=project, limit=MAX_ENTRIES):
                if row["id"] not in seen:
                    rows.append(row)
                    seen.add(row["id"])
        return rows[:MAX_ENTRIES]

    def collect(project: str, kind: str, cfg: dict) -> tuple[list[dict], list[str], int]:
        rows = _candidate_rows(project, kind, cfg)
        records: list[dict] = []
        warnings: list[str] = []
        for row in rows:
            try:
                body = str(core_api.entry(str(row.get("id"))).get("body") or "")
            except FileNotFoundError:
                continue
            found, warn = extract_records(row, body, cfg)
            warnings.extend(f"{row.get('title')}：{w}" for w in warn)
            records.extend(found)
        return records[:MAX_ROWS], warnings[:30], len(rows)

    def _query(request) -> tuple[str, str, str]:
        query = request["query"]
        return (str((query.get("project") or [""])[0]),
                str((query.get("kind") or [""])[0]),
                str((query.get("mode") or ["records"])[0]))

    def build_payload(project: str, kind: str, mode: str) -> dict:
        cfg = config()
        records, warnings, scanned = collect(project, kind, cfg)
        table = pivot_by_object(records) if mode == "pivot" else build_table(records)
        table.update({
            "scope": {"project": project, "kind": kind, "mode": mode},
            "config": cfg, "scanned": scanned, "with_metrics": len(records),
            "sources": {s: sum(1 for r in records if r["source"] == s) for s in ("block", "table")},
            "warnings": warnings,
        })
        table["hint"] = "" if records else (
            f"没找到指标。两种来源都没命中：① 正文里没有 ```{cfg['block_name']} 块；"
            f"② 正文里没有「有数值列的 Markdown 表格」。"
            f"任选其一即可，例如加一张表：| 模型 | mIoU | Pd |")
        return table

    def route_table(request):
        project, kind, mode = _query(request)
        return build_payload(project, kind, mode)

    def route_entry(request):
        doc_id = str((request["query"].get("id") or [""])[0])
        if not doc_id:
            return {"ok": False, "error": "缺少 id"}
        try:
            entry = core_api.entry(doc_id)
        except FileNotFoundError:
            return {"ok": False, "error": f"条目不存在：{doc_id}"}
        cfg = config()
        records, warnings = extract_records(entry, str(entry.get("body") or ""), cfg)
        return {"ok": True, "id": doc_id, "title": entry.get("title"), "kind": entry.get("kind"),
                "status": entry.get("status"), "date": entry.get("record_date") or "",
                "records": records, "warnings": warnings, "block_name": cfg["block_name"],
                "tables": [{"caption": t["caption"], "header": t["header"], "numeric": len(t["numeric_cols"]),
                            "rows": len(t["rows"]), "object_col": t["object_col"]} for t in parse_tables(str(entry.get("body") or ""))],
                "preview": str(entry.get("body") or "")[:800]}

    def route_export(request):
        project, kind, mode = _query(request)
        fmt = str((request["query"].get("format") or ["csv"])[0]).lower()
        table = build_payload(project, kind, mode)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = f"metrics-{project or kind or 'all'}-{mode}-{stamp}".replace(" ", "-")
        if fmt == "md":
            return ctx.raw(to_markdown(table), content_type="text/markdown; charset=utf-8",
                           filename=f"{base}.md")
        return ctx.raw(to_csv(table), content_type="text/csv; charset=utf-8", filename=f"{base}.csv")

    def route_config_get(request):
        return config()

    def route_config_post(request):
        body = request.get("body") or {}
        cfg = config()
        for key in DEFAULT_CONFIG:
            if key in body:
                cfg[key] = body[key]
        ctx.config_write({**DEFAULT_CONFIG, **cfg})
        return config()

    ctx.routes.get("table", route_table)
    ctx.routes.get("entry", route_entry)
    ctx.routes.get("export", route_export)
    ctx.routes.get("config", route_config_get)
    ctx.routes.post("config", route_config_post)

    # ---------------------------------------------------------------- Agent 工具

    def tool_table(args, call_ctx=None):
        args = args or {}
        mode = str(args.get("mode") or "records")
        payload = build_payload(str(args.get("project") or ""), str(args.get("kind") or ""), mode)
        return {
            "mode": mode,
            "columns": [{k: c[k] for k in ("key", "filled", "missing", "unit", "min", "max", "mean")}
                        for c in payload["columns"]],
            "rows": [{**{k: r.get(k) for k in ("object", "entry_title", "short", "scope", "source")},
                      "metrics": r["metrics"], "missing": r["missing"]} for r in payload["rows"][:80]],
            "scanned": payload["scanned"], "with_metrics": payload["with_metrics"],
            "sources": payload["sources"], "warnings": payload["warnings"], "hint": payload["hint"],
        }

    def tool_record(args, call_ctx=None):
        args = args or {}
        doc_id = str(args.get("entry_id") or "").strip()
        metrics = args.get("metrics")
        mode = str(args.get("mode") or "merge")
        if not doc_id:
            raise ValueError("entry_id 不能为空")
        if not isinstance(metrics, dict) or not metrics:
            raise ValueError('metrics 必须是非空对象，如 {"mIoU": "0.732", "Pd": "91%"}')
        if mode not in ("merge", "replace"):
            raise ValueError("mode 只能是 merge 或 replace")
        entry = core_api.entry(doc_id)                      # 条目不存在会抛 FileNotFoundError
        new_body = upsert_metrics_block(str(entry.get("body") or ""), metrics, mode,
                                        config()["block_name"])
        updated = core_api.entry_update(doc_id, body=new_body)
        ctx.log(f"已把 {len(metrics)} 项指标写入 {doc_id}（{mode}）")
        return {"ok": True, "entry_id": doc_id, "title": updated.get("title"), "mode": mode,
                "written": {str(k): str(v) for k, v in metrics.items()}}

    ctx.mcp.tool("metrics_table", {
        "description": ("读跨条目的指标对照表。数据来自条目正文：```metrics 块**或**有数值列的 Markdown 表格"
                        "（后者按行展开，自动识别对象列）。mode=pivot 时按对象透视，便于跨实验对照同一模型。"),
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "只看某个项目（留空 = 全部）"},
                "kind": {"type": "string", "description": "只看某一类条目（留空 = 配置里的类别）"},
                "mode": {"type": "string", "enum": ["records", "pivot"], "description": "默认 records（明细）；pivot 按对象透视"},
            },
        },
    }, tool_table)

    ctx.mcp.tool("record_metrics", {
        "description": ("把指标写进某条条目正文的 ```metrics 块（mode=merge 合并 / replace 覆盖）。"
                        "这是**写操作**：内核会先生成草稿，用户确认后才落盘。"
                        "注意：只读的正文表格不需要它——表格已经能被自动识别。"),
        "write": True,
        "parameters": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string", "description": "条目 id（如 experiment-…）"},
                "metrics": {"type": "object", "description": "指标键值对，如 {\"mIoU\": \"0.732\", \"Pd\": \"91%\"}"},
                "mode": {"type": "string", "enum": ["merge", "replace"], "description": "默认 merge"},
            },
            "required": ["entry_id", "metrics"],
        },
    }, tool_record)

    ctx.log("指标表插件已注册（/api/plugins/metrics-table/{table,entry,export,config}；"
            "数据来源：```metrics 块 + 正文数值表格）")
