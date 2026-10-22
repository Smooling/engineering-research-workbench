"""日历 · 插件后端 v1.0.1

把**里程碑的 `due`** 与**待办的 `due`** 汇成一份 agenda（逾期 / 今日 / 近期 / 无日期），
供页面日历与顶栏角标使用。

为什么不做"到点弹通知"：内核**没有通知通道**，操作系统级通知还要处理权限与打包差异。
与其做一个会漏的假提醒，不如把「逾期/今日」做成**顶栏常驻角标**——打开工作台就一定看得见。
真要推送，应先在 §6.2 ③ 里加一条通知能力，再由插件消费（而不是各插件自己起线程轮询弹窗）。

数据读取走 `core_api`：里程碑用条目窗口（`entries("milestone")`，含 `due`），
待办用 `core_api.todos()`——两者都与前端 `/api/todos`、`/api/docs` 同源。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import core_api

DEFAULT_CONFIG = {
    "lookahead_days": 7,        # 「近期」窗口
    "include_todos": True,
    "include_milestones": True,
    "badge_days": 7,            # 角标统计的天数窗口
}
MAX_LOOKAHEAD = 90
KIND_ORDER = ("milestone", "todo")


def _today() -> date:
    return date.today()


def _parse_due(raw: str) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    return None


def register(ctx):
    def config() -> dict:
        cfg = dict(DEFAULT_CONFIG)
        saved = ctx.config_read({})
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in DEFAULT_CONFIG})
        cfg["lookahead_days"] = max(1, min(MAX_LOOKAHEAD, int(cfg["lookahead_days"] or 7)))
        cfg["badge_days"] = max(1, min(MAX_LOOKAHEAD, int(cfg["badge_days"] or 7)))
        return cfg

    def _items() -> list[dict]:
        """归一成 {id, kind, title, due, done, project, link, overdue_days}。"""
        cfg = config()
        out: list[dict] = []
        if cfg["include_milestones"]:
            for row in core_api.entries("milestone", limit=500):
                due = _parse_due(row.get("due") or "")
                out.append({
                    "id": row.get("id"), "kind": "milestone", "kind_label": "里程碑",
                    "title": row.get("title"), "due": due.isoformat() if due else "",
                    "done": str(row.get("status") or "") in ("完成", "已归档"),
                    "project": "、".join(row.get("projects") or []),
                    "status": row.get("status") or "", "_due": due,
                })
        if cfg["include_todos"]:
            for row in core_api.todos(include_done=False):
                due = _parse_due(row.get("due") or "")
                out.append({
                    "id": row.get("id"), "kind": "todo", "kind_label": "待办",
                    "title": row.get("title"), "due": due.isoformat() if due else "",
                    "done": bool(row.get("done")), "project": str(row.get("project") or ""),
                    "status": str(row.get("priority") or ""), "_due": due,
                })
        return out

    def agenda_from(items: list[dict]) -> dict:
        cfg = config()
        today = _today()
        soon_end = today + timedelta(days=cfg["lookahead_days"])
        buckets: dict[str, list[dict]] = {"overdue": [], "today": [], "soon": [], "later": [], "undated": []}
        for item in items:
            due, done = item["_due"], item["done"]
            row = {k: v for k, v in item.items() if not k.startswith("_")}
            if due is None:
                buckets["undated"].append(row)
                continue
            row["days_left"] = (due - today).days
            if done:
                continue                        # 已完成的不参与提醒
            if due < today:
                row["overdue_days"] = (today - due).days
                buckets["overdue"].append(row)
            elif due == today:
                buckets["today"].append(row)
            elif due <= soon_end:
                buckets["soon"].append(row)
            else:
                buckets["later"].append(row)
        for key in buckets:
            buckets[key].sort(key=lambda r: (r.get("due") or "9999", str(r.get("title") or "")))
        return {
            "today": today.isoformat(),
            "lookahead_days": cfg["lookahead_days"],
            "counts": {k: len(v) for k, v in buckets.items()},
            "buckets": buckets,
        }

    def route_agenda(request):
        data = agenda_from(_items())
        data["config"] = config()
        return data

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

    ctx.routes.get("agenda", route_agenda)
    ctx.routes.get("config", route_config_get)
    ctx.routes.post("config", route_config_post)

    def tool_agenda(args, call_ctx=None):
        args = args or {}
        data = agenda_from(_items())
        names = ("overdue", "today", "soon")
        return {
            "today": data["today"],
            "counts": data["counts"],
            "items": {k: [{f: r.get(f) for f in ("title", "kind_label", "due", "days_left", "overdue_days", "project")}
                          for r in data["buckets"][k][: int(args.get("limit") or 10)]]
                      for k in names},
            "hint": "overdue=逾期未完成，today=今天到期，soon=近期窗口内",
        }

    ctx.mcp.tool("agenda", {
        "description": "看里程碑与待办的到期情况：逾期、今天到期、近期（默认 7 天）各有哪些",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "每个分组最多返回几条（默认 10）"}},
        },
    }, tool_agenda)

    ctx.log("日历与提醒插件已注册（/api/plugins/milestone-calendar/agenda；顶栏槽位角标）")
