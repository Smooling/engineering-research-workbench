"""知识条目类工具 —— 覆盖 Workspace/Knowledge 下六类条目的读写与合规校验。"""

from __future__ import annotations

from typing import Any

from . import constraints as C
from . import naming
from core.contracts import validate
from .bridge import Workbench, WorkbenchError
from .protocol import RpcError, arr, b, fail, i, ok, s, tool

KIND_ENUM = C.KIND_ORDER
CATEGORY_ENUM = [c["word"] for c in C.CATEGORY_WORDS]
MARK_ENUM = [m["id"] for m in C.MARK_IDS]

COMMON_WRITE_NOTE = (
    "写入前必须先满足命名规范；返回结果含 `validation` 字段，"
    "其中 `level=error` 的项是硬约束，未通过时工具会拒绝写入（除非显式 allow_violation=true）。"
)


def _resolve_title(args: dict[str, Any], kind: str) -> str:
    title = str(args.get("title") or "").strip()
    if title:
        return title
    name = str(args.get("name") or "").strip()
    if not name:
        return ""
    return naming.suggest_title(kind, name, str(args.get("category") or ""), str(args.get("note_suffix") or ""))


def _derive_marks(kind: str, title: str, marks: list[str]) -> list[str]:
    """标记推导的唯一实现在 core/contracts/naming.py（HTTP 侧 Agent 工具共用同一份）。"""
    return naming.derive_marks(kind, title, marks)


def _payload_from_args(args: dict[str, Any], kind: str, title: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"title": title}
    marks = args.get("kind_marks") if isinstance(args.get("kind_marks"), list) else []
    payload["kind_marks"] = _derive_marks(kind, title, marks)
    for key in ("status", "body", "summary_type", "authors", "year", "venue", "doi", "url", "cite_key",
                "record_date", "due", "added_date", "bibtex"):
        if args.get(key) not in (None, ""):
            payload[key] = args[key]
    projects = [str(x).strip() for x in (args.get("projects") or []) if str(x).strip()]
    if args.get("project"):
        projects = [str(args["project"]).strip()] + [p for p in projects if p != str(args["project"]).strip()]
    if projects:
        payload["projects"] = projects
    tags = [str(x).strip() for x in (args.get("tags") or []) if str(x).strip()]
    if tags:
        payload["tags"] = tags
    return payload


def _projects_of(doc: dict[str, Any]) -> list[str]:
    """取条目的项目归属（`projects` 全集，回退到 `project` 首个）。"""
    projects = [str(p).strip() for p in (doc.get("projects") or []) if str(p).strip()]
    if not projects and doc.get("project"):
        projects = [str(doc["project"]).strip()]
    return projects


def _validation_block(kind: str, title: str, marks: list[str], body: str | None,
                      projects: list[str] | None = None) -> dict[str, Any]:
    issues = naming.validate_title(kind, title, kind_marks=marks, body=body, projects=projects)
    return {
        "ok": not any(x["level"] == "error" for x in issues),
        "issues": issues,
        "errors": [x for x in issues if x["level"] == "error"],
        "warnings": [x for x in issues if x["level"] == "warn"],
    }


# ------------------------------------------------------------------ 工具实现

def t_constraints(wb: Workbench, args: dict[str, Any]) -> Any:
    topic = str(args.get("topic") or "").strip()
    if topic and topic not in C.TOPICS:
        return fail(f"未知约束主题 `{topic}`", "可选：" + " / ".join(C.TOPICS))
    if topic:
        return {topic: _constraint_text(topic)}
    return {key: _constraint_text(key) for key in C.TOPICS}


def _constraint_text(topic: str) -> str:
    k = C.KINDS
    if topic == "storage":
        lines = ["## 存放规则", "", C.KNOWLEDGE_ROOT_RULE, "", C.SOURCE_OF_TRUTH_RULE, "", "### Workspace 目录", ""]
        lines += [f"- `{p}/`" for p in C.WORKSPACE_LAYOUT]
        lines += ["", "### 项目目录（`Projects/<项目名>/`）", ""] + [f"- `{p}/`" for p in C.PROJECT_LAYOUT]
        lines += ["", "### System 文件语义", ""] + [f"- `{p}`：{d}" for p, d in C.SYSTEM_FILES.items()]
        return "\n".join(lines)
    if topic == "naming":
        lines = ["## 命名规范", "", C.PREFIX_RULE, "", "### 前缀表", "",
                 "| 条目类型 | 前缀 | 类别词 |", "| --- | --- | --- |"]
        lines += [f"| {kind} | `{'` / `'.join(naming.allowed_prefixes(kind))}` | {'有且仅有一个' if v['category_word'] else '不使用'} |" for kind, v in C.KINDS.items()]
        lines += ["", "### 类别词判据（仅 `知识-`）", "", "| 类别词 | 判据 |", "| --- | --- |"]
        lines += [f"| `{c['word']}` | {c['criteria']} |" for c in C.CATEGORY_WORDS]
        lines += ["", "### 名称段规则", ""] + [f"{n}. {r}" for n, r in enumerate(C.NAME_SEGMENT_RULES, 1)]
        lines += ["", "### 禁用字符", "", "、".join(f"`{c}`" for c in C.FORBIDDEN_TITLE_CHARS)]
        return "\n".join(lines)
    if topic == "sync":
        return "## 改名同步要求\n\n" + "\n".join(f"{n}. {r}" for n, r in enumerate(C.SYNC_RULES, 1))
    if topic == "kinds":
        lines = ["## 七类条目矩阵", "",
                 "| kind | 目录 | 前缀 | 状态机 | 日期字段 | 默认正文骨架 |", "| --- | --- | --- | --- | --- | --- |"]
        for kind in C.KIND_ORDER:
            v = k[ kind]
            lines.append("| `{}` | `{}` | `{}` | {} | {} | {} |".format(
                kind, v["dir"], v["prefix"], " / ".join(v["statuses"]), v["date_field"] or "—",
                " / ".join(v["default_sections"])))
        return "\n".join(lines) + "\n\n" + C.KIND_CHOICE_HINT
    if topic == "schema":
        return "\n".join([
            "## frontmatter 字段契约", "",
            "字段序（写入时按此顺序落盘）：", "",
            "`" + "`, `".join(C.FRONTMATTER_ORDER) + "`", "",
            f"- 不可变字段：`{'`, `'.join(C.IMMUTABLE_FIELDS)}`（改名/更新均不得改动）",
            f"- 创建可写：`{'`, `'.join(C.CREATE_FIELDS)}`",
            f"- 更新可写：`{'`, `'.join(C.UPDATE_FIELDS)}`",
            "", C.DATE_FIELD_RULE, "", C.RELATION_RULE, "", C.DOC_ID_RULE,
        ])
    if topic == "marks":
        lines = ["## kind_marks 标记表", "", "| id | 显示 |", "| --- | --- |"]
        lines += [f"| `{m['id']}` | {m['icon']} {m['label']} |" for m in C.MARK_IDS]
        lines += ["", "类别词 → 标记映射：", "", "| 类别词 | id |", "| --- | --- |"]
        lines += [f"| `{c['word']}` | `{c['mark']}` |" for c in C.CATEGORY_WORDS]
        lines += ["", "`kind_marks` 可多选叠加；跨族底账类条目可用 `knowledge` / `synthesis`。",
                  "`kind: experiment` 的条目**固定**含 `experiment` 标记（由写入工具自动补齐），"
                  "不再使用 `实验` 类别词。",
                  "",
                  "自定义标记：设置页「知识条目 → 分类标记」可从内置模板添加，或自定义名称/图案/颜色"
                  "（id 形如 `mark_xxx`，上限 24 个）；写入时与内置标记同等合法。"]
        return "\n".join(lines)
    if topic == "relations":
        lines = ["## 关系层（v261008.2）", "", C.RELATION_RULE, "",
                 "### 关系类型矩阵", "",
                 "| 关系 id | 显示 | 由哪一小节/标签产生 | 含义 |", "| --- | --- | --- | --- |"]
        lines += [f"| `{r['id']}` | {r['label']} | {r['section']} | {r['meaning']} |" for r in C.RELATION_MATRIX]
        lines += [
            "", "### 用法要点", "",
            "- 实验条目在「关联」段用 `### 依据的知识` / `### 用到的数据` / `### 同系列实验` 三节登记依赖，"
            "这样「哪些实验用了这条知识」「这条知识被哪些实验交叉使用」都能直接查出来。",
            "- 系列实验用 `### 同系列实验` 互指，并建一张系列枢纽条目（`实验-<系列名>（系列枢纽）`）作为总入口。",
            "- 写论文时在稿件「引用清单」段按 `### 依据的知识` / `### 实验` / `### 用到的数据` / `### 引用文献` "
            "登记引用即可复用同一套关系。",
            "- 关系边是**派生数据**：改完正文跑 `ws_reindex`（或让工作台启动时自动同步）即生效。",
        ]
        return "\n".join(lines)
    if topic == "playbook":
        return "\n".join([
            "## Agent 操作手册", "",
            "### 标准作业流程", "",
            "1. `kb_constraints` 读取相关约束（首次会话至少读 `storage` + `naming`）。",
            "2. `ws_list_projects` 确认 `projects` 归属，不要凭空拼项目名。",
            "3. `kb_list_entries` / `kb_search` 查重，避免重复建档。",
            "4. `kb_create_entry` 建档：先给 `name` + `category`，由工具生成规范标题；或直接给 `title`。",
            "5. `kb_update_entry` 补正文；改动 `title` 时用 `kb_rename_entry` 走改名流程。",
            "6. 收尾 `kb_check_entries` 复核，必要时 `ws_reindex` 重建索引。",
            "", "### 红线", "",
            "- 不得手写 frontmatter 落盘、不得直接操纵 `System/Cache` 索引文件。",
            "- 不得编造 `id`；不得改动既有条目的 `id` / `created`。",
            "- 删除只能通过 `kb_delete_entry`（进回收站），不得直接删文件。",
            "- 一次实验一条 `实验-…`（kind=experiment）；不要把多个知识点塞进同一标题。",
            "- 跨项目通用知识照常按 note 建，但 `projects` 留空并打 `通用基础` 标签，不要挂到某一个项目上。",
            "- 需要换 kind（如老 `知识-实验-…` 迁到 `实验-…`）用 `kb_change_kind`，不要手工建新条目再删旧的。",
            "- 逾期/收口请改用 `summary` / `journal`，不要往 `note` 里塞流水账。",
        ])
    return fail(f"未定义的约束主题 `{topic}`")


def t_list_entries(wb: Workbench, args: dict[str, Any]) -> Any:
    result = wb.list_entries(
        kind=str(args.get("kind") or ""), query=str(args.get("query") or ""),
        status=str(args.get("status") or ""), project=str(args.get("project") or ""),
        mark=str(args.get("mark") or ""), tag=str(args.get("tag") or ""),
        unowned=bool(args.get("unowned")), sort=str(args.get("sort") or ""),
        page=int(args.get("page") or 1),
        page_size=int(args.get("page_size") or 20),
    )
    return {**result, "_tip": "标题不合规时用 kb_check_entries 定位，用 kb_rename_entry 修正。"}


def t_get_entry(wb: Workbench, args: dict[str, Any]) -> Any:
    doc = wb.get_entry(str(args["doc_id"]))
    validation = _validation_block(str(doc.get("kind") or ""), str(doc.get("title") or ""),
                                  doc.get("kind_marks") or [], doc.get("body"), _projects_of(doc))
    return {"entry": doc, "validation": validation}


def t_branch_entry(wb: Workbench, args: dict[str, Any]) -> Any:
    """**开一条分支**：以某条条目为源，复制内容成一个新版本（记 variant_of / variant_label / variant_at）。"""
    V = wb.mod.versions
    source_id = str(args.get("doc_id") or args.get("source_id") or "").strip()
    if not source_id:
        return fail("缺少 doc_id（要分支的源条目）")
    try:
        out = V.create_branch(source_id,
                              label=str(args.get("label") or ""),
                              title=str(args.get("title") or ""),
                              body=args.get("body") if isinstance(args.get("body"), str) else None,
                              origin_info=wb.origin("kb_branch_entry"))
    except Exception as exc:                      # noqa: BLE001
        return fail(f"开分支失败：{exc}")
    return ok({"created": True, "base_id": out["base_id"], "variant_label": out["variant_label"],
               "variant_at": out["variant_at"], "entry": out["entry"],
               "_hint": "改完这条分支后用 kb_merge_variants 合并（picks 指定哪个小节用哪个版本）。"})


def t_variants(wb: Workbench, args: dict[str, Any]) -> Any:
    """列某条条目的版本族（基条 + 各版本 + 已归档 + 每版来源）。"""
    sys_path_versions = wb.mod.versions  # noqa: F841  （确保 app.versions 已加载）
    V = wb.mod.versions
    doc_id = str(args.get("doc_id") or "").strip()
    if not doc_id:
        return fail("缺少 doc_id")
    try:
        base = V.base_id_of(wb.get_entry(doc_id))
    except Exception:
        return fail(f"条目不存在：{doc_id}")
    fam = V.family(base)
    return ok({"base_id": base, "forked": fam["forked"], "count": fam["count"],
               "base": _variant_row(wb, fam["base"]),
               "variants": [_variant_row(wb, v) for v in fam["variants"]],
               "archived": fam["archived"],
               "times": fam.get("times") or {},
               "_hint": "合并用 kb_merge_variants（选基准 + 逐节挑来源）；结束后用 kb_archive_variants 归档。"})


def _variant_row(wb: Workbench, doc: dict[str, Any] | None) -> dict[str, Any]:
    if not doc:
        return {}
    return {"id": doc.get("id"), "title": doc.get("title"), "label": doc.get("variant_label") or "",
            "status": doc.get("status"), "updated": doc.get("updated"),
            "origin": wb.mod.versions.describe_origin(doc)}


def t_merge_variants(wb: Workbench, args: dict[str, Any]) -> Any:
    """按小节合并版本族（走内核统一实现，会记 doc_merge 活动与时间）。"""
    V = wb.mod.versions
    base_id = str(args.get("base_id") or args.get("doc_id") or "").strip()
    if not base_id:
        return fail("缺少 base_id")
    picks = args.get("picks") if isinstance(args.get("picks"), dict) else {}
    try:
        out = V.merge_family(base_id, picks, archive_merged=bool(args.get("archive_merged")),
                             origin_info=wb.origin("kb_merge_variants"))
    except FileNotFoundError as exc:
        return fail(str(exc))
    return ok(out)



def t_archive_variants(wb: Workbench, args: dict[str, Any]) -> Any:
    """归档指定版本到 System/Versions/<base>/archived/（保留可追溯）。"""
    V = wb.mod.versions
    base_id = str(args.get("base_id") or "").strip()
    ids = [str(x) for x in (args.get("variant_ids") or []) if str(x).strip()]
    if not base_id or not ids:
        return fail("需要 base_id 与 variant_ids")
    return ok(V.archive_variants(base_id, ids, {"tool": "kb_archive_variants"}))


def t_create_entry(wb: Workbench, args: dict[str, Any]) -> Any:
    kind = str(args.get("kind") or "").strip()
    if kind not in C.KINDS:
        return fail(f"未知条目类型 `{kind}`", "可选：" + " / ".join(C.KIND_ORDER))
    title = _resolve_title(args, kind)
    if not title:
        return fail("缺少标题", "给出 `title`，或给出 `name`（配合 `category`）由工具按规范拼接。")
    payload = _payload_from_args(args, kind, title)
    validation = _validation_block(kind, title, payload.get("kind_marks") or [], payload.get("body"),
                                   _projects_of(payload))
    if not validation["ok"] and not args.get("allow_violation"):
        return {
            "created": False, "validation": validation,
            "_hint": "标题不符合命名规范，未写入。请修正后重试，或显式传 allow_violation=true 强制建档。",
        }
    # v261009 · 字段级硬校验（status / kind_marks / 日期 / 未声明字段），与 store.write 同一实现
    field_issues = validate.validate_write(kind, payload, title=title)
    if validate.errors(field_issues) and not args.get("allow_violation"):
        return {
            "created": False, "field_issues": field_issues,
            "_hint": "字段不符合契约，未写入（" + validate.summarize(field_issues) + "）。"
                     "取值见 kb_constraints topic=kinds|marks；或显式传 allow_violation=true 强制建档。",
        }
    doc = wb.create_entry(kind, payload, origin=wb.origin("kb_create_entry"))
    return {"created": True, "entry": doc, "validation": validation,
            "field_issues": field_issues, "dir": C.KINDS[kind]["dir"]}


def t_update_entry(wb: Workbench, args: dict[str, Any]) -> Any:
    doc_id = str(args["doc_id"])
    current = wb.get_entry(doc_id)
    kind = str(current.get("kind") or "")
    payload: dict[str, Any] = {}
    for key in ("status", "summary_type", "authors", "year", "venue", "doi", "url", "cite_key",
                "record_date", "due", "added_date", "bibtex"):
        if key in args and args[key] is not None:
            payload[key] = args[key]
    if args.get("projects") is not None:
        payload["projects"] = [str(x).strip() for x in (args.get("projects") or []) if str(x).strip()]
    if args.get("tags") is not None:
        payload["tags"] = [str(x).strip() for x in (args.get("tags") or []) if str(x).strip()]
    if args.get("kind_marks") is not None:
        payload["kind_marks"] = [str(x) for x in (args.get("kind_marks") or []) if str(x)]
    if args.get("pinned") is not None:
        payload["pinned"] = bool(args.get("pinned"))

    title = current.get("title") or ""
    body = args.get("body")
    if args.get("title"):
        title = str(args["title"]).strip()
        payload["title"] = title
        body = naming.replace_h1(str(body if body is not None else current.get("body") or ""), title)[0]
    if body is not None:
        payload["body"] = body

    marks = payload.get("kind_marks") or current.get("kind_marks") or []
    validation = _validation_block(kind, title, marks, body,
                                   _projects_of(payload) or _projects_of(current))
    if not validation["ok"] and not args.get("allow_violation"):
        return {"updated": False, "validation": validation,
                "_hint": "改动不符合命名规范，未写入。改名请用 kb_rename_entry 以同步交叉引用。"}
    # v261009 · 字段级硬校验（更新语义：只校验本次实际写入的字段）
    field_issues = validate.validate_write(kind, payload, partial=True, title=title)
    if validate.errors(field_issues) and not args.get("allow_violation"):
        return {"updated": False, "field_issues": field_issues,
                "_hint": "字段不符合契约，未写入（" + validate.summarize(field_issues) + "）。"}
    doc = wb.update_entry(doc_id, payload, origin=wb.origin("kb_update_entry"))
    return {"updated": True, "entry": doc, "validation": validation, "field_issues": field_issues}


def t_rename_entry(wb: Workbench, args: dict[str, Any]) -> Any:
    doc_id = str(args["doc_id"])
    current = wb.get_entry(doc_id)
    kind = str(current.get("kind") or "")
    old_title = str(current.get("title") or "")
    new_title = str(args.get("new_title") or "").strip()
    if not new_title:
        new_name = str(args.get("new_name") or "").strip()
        if not new_name:
            return fail("缺少新标题", "给出 `new_title`，或给出 `new_name`（配合 `new_category`）。")
        new_title = naming.suggest_title(kind, new_name, str(args.get("new_category") or ""),
                                         str(args.get("note_suffix") or ""))
    if new_title == old_title:
        return {"renamed": False, "_hint": "新标题与当前标题一致，无需改名。"}

    marks = current.get("kind_marks") or []
    new_body, h1_changed = naming.replace_h1(str(current.get("body") or ""), new_title)
    validation = _validation_block(kind, new_title, marks, new_body, _projects_of(current))
    root = wb.root
    path = wb.entry_path(doc_id)
    refs = naming.scan_references(root, old_title, exclude=path)

    plan = {
        "doc_id": doc_id, "kind": kind, "old_title": old_title, "new_title": new_title,
        "h1_synced": h1_changed, "immutable_fields_kept": C.IMMUTABLE_FIELDS,
        "references": refs, "validation": validation,
        "activity_event": "doc_update",
    }
    if args.get("dry_run"):
        return {"dry_run": True, "plan": plan}
    if not validation["ok"] and not args.get("allow_violation"):
        return {"renamed": False, "plan": plan,
                "_hint": "新标题不符合命名规范，未执行。修正后重试，或传 allow_violation=true。"}

    doc = wb.update_entry(doc_id, {"title": new_title, "body": new_body})
    changed = []
    if refs and args.get("update_references", True):
        changed = naming.rewrite_references(root, old_title, new_title, exclude=path)
    return {
        "renamed": True, "entry": doc,
        "updated_references": changed,
        "activity_event": "doc_update（已由工作台写入 System/activity.jsonl，仅一次）",
        "validation": validation,
    }


def t_delete_entry(wb: Workbench, args: dict[str, Any]) -> Any:
    doc_id = str(args["doc_id"])
    if not args.get("confirm"):
        doc = wb.get_entry(doc_id)
        return {"deleted": False, "preview": {"id": doc_id, "title": doc.get("title"), "kind": doc.get("kind")},
                "_hint": "删除会移入回收站；确认请传 confirm=true。"}
    return {"deleted": True, "result": wb.delete_entry(doc_id)}


def t_check_entries(wb: Workbench, args: dict[str, Any]) -> Any:
    if args.get("doc_id"):
        doc = wb.get_entry(str(args["doc_id"]))
        return {"scope": "single", "doc_id": doc["id"], "title": doc.get("title"),
                "validation": _validation_block(str(doc.get("kind") or ""), str(doc.get("title") or ""),
                                                doc.get("kind_marks") or [], doc.get("body"), _projects_of(doc))}

    limit = max(1, min(200, int(args.get("limit") or 60)))
    check_h1 = bool(args.get("check_h1", False))
    listed = wb.list_entries(kind=str(args.get("kind") or ""), page=1, page_size=limit)
    results: list[dict[str, Any]] = []
    for item in listed["items"]:
        body = None
        if check_h1:
            try:
                body = wb.get_entry(str(item["id"])).get("body")
            except WorkbenchError:
                body = None
        v = _validation_block(str(item.get("kind") or ""), str(item.get("title") or ""),
                              item.get("kind_marks") or [], body, _projects_of(item))
        if v["ok"] and not v["warnings"] and not args.get("include_ok"):
            continue
        results.append({"id": item["id"], "kind": item.get("kind"), "title": item.get("title"),
                        "dir": C.KINDS.get(str(item.get("kind")), {}).get("dir"),
                        "validation": v})
    return {
        "scope": "scan", "checked": len(listed["items"]), "total_in_scope": listed["total"],
        "h1_checked": check_h1, "compliant": len(results) == 0,
        "findings": results,
        "_tip": "用 kb_rename_entry 逐条修正；改名会自动同步 title/H1/交叉引用并写入 doc_update 事件。",
    }


def t_change_kind(wb: Workbench, args: dict[str, Any]) -> Any:
    """v261008.2 · 结构性迁移：条目换 kind（目录随动、id/created 不变、交叉引用同步）。"""
    doc_id = str(args.get("doc_id") or "").strip()
    if not doc_id:
        return fail("缺少 doc_id", "给出要迁移的条目 id。")
    new_kind = str(args.get("new_kind") or "").strip()
    if new_kind not in C.KINDS:
        return fail(f"未知目标类型 `{new_kind}`", "可选：" + " / ".join(C.KIND_ORDER))

    current = wb.get_entry(doc_id)
    old_kind = str(current.get("kind") or "")
    old_title = str(current.get("title") or "")
    if new_kind == old_kind:
        return {"changed": False, "_hint": f"条目已是 `{new_kind}` 类型。"}

    old_marks = [str(m) for m in (current.get("kind_marks") or [])]
    new_title = str(args.get("new_title") or "").strip()
    if not new_title:
        seg = naming.split_segments(old_title, old_kind)
        name = seg["name"] or ""
        if not name:
            return fail("无法自动改写标题", "给出 `new_title`。")
        if C.KINDS[new_kind].get("category_word"):
            new_title = naming.suggest_title(new_kind, name, seg["category"], seg["note"])
        else:
            new_title = f"{C.KINDS[new_kind]['prefix']}{name}{seg['note']}"

    new_marks = _derive_marks(new_kind, new_title or old_title, old_marks)
    new_body, _h1_changed = naming.replace_h1(str(current.get("body") or ""), new_title or old_title)
    validation = _validation_block(new_kind, new_title or old_title, new_marks, new_body, _projects_of(current))

    root = wb.root
    path = wb.entry_path(doc_id)
    refs = naming.scan_references(root, old_title, exclude=path) if new_title != old_title else []
    plan = {
        "doc_id": doc_id, "old_kind": old_kind, "new_kind": new_kind,
        "old_title": old_title, "new_title": new_title or old_title,
        "kind_marks": new_marks, "target_dir": C.KINDS[new_kind]["dir"],
        "immutable_fields_kept": C.IMMUTABLE_FIELDS,
        "references": refs, "validation": validation,
    }
    if args.get("dry_run"):
        return {"dry_run": True, "plan": plan}
    if not validation["ok"] and not args.get("allow_violation"):
        return {"changed": False, "plan": plan,
                "_hint": "迁移后的标题不符合命名规范，未执行。传 new_title 修正，或传 allow_violation=true。"}

    doc = wb.change_kind_entry(doc_id, new_kind, new_title, kind_marks=new_marks)
    changed = []
    if refs and args.get("update_references", True):
        changed = naming.rewrite_references(root, old_title, new_title, exclude=path)
    return {
        "changed": True, "entry": doc, "plan": plan,
        "updated_references": changed,
        "activity_event": "doc_update（已由工作台写入 System/activity.jsonl，仅一次）",
        "validation": validation,
    }


HANDLERS = {
    "kb_constraints": t_constraints,
    "kb_list_entries": t_list_entries,
    "kb_get_entry": t_get_entry,
    "kb_create_entry": t_create_entry,
    "kb_update_entry": t_update_entry,
    "kb_rename_entry": t_rename_entry,
    "kb_change_kind": t_change_kind,
    "kb_delete_entry": t_delete_entry,
    "kb_check_entries": t_check_entries,
    "kb_variants": t_variants,
    "kb_merge_variants": t_merge_variants,
    "kb_archive_variants": t_archive_variants,
    "kb_branch_entry": t_branch_entry,
}


TOOLS = [
    tool("kb_constraints", "读取知识库约束",
         "返回权威的存放规则与命名规范（Markdown）。topic：storage 存放规则 / naming 命名规范 / "
         "sync 改名同步 / kinds 七类矩阵 / schema 字段契约 / marks 标记表 / relations 关系层 / playbook 操作手册。",
         {"topic": s("约束主题；留空返回全部", enum=list(C.TOPICS))}, read_only=True),
    tool("kb_list_entries", "列出知识条目",
         "分页列出 Knowledge 下的条目，可按类型/状态/项目/标记/标签过滤、只看未归属项目（通用基础）条目，"
         "并做全文字段检索。",
         {"kind": s("条目类型", enum=KIND_ENUM), "query": s("全文检索词"),
          "status": s("状态过滤"), "project": s("项目名或 project_id"),
          "mark": s("kind_marks 标记 id", enum=MARK_ENUM),
          "tag": s("标签精确匹配（此前只能靠全文搜索命中）"),
          "unowned": b("只看未归属任何项目的条目（跨项目通用基础知识）"),
          "sort": s("排序：added=加入时间（默认，不受写入影响）/ updated=最近更新 / title=标题",
                    enum=["added", "updated", "title"]),
          "page": i("页码，从 1 开始", default=1, minimum=1),
          "page_size": i("每页条数", default=20, minimum=1, maximum=100)}, read_only=True),
    tool("kb_get_entry", "读取单条条目",
         "按 id 读取条目全文（含 frontmatter 与正文），并附带命名合规校验结果。",
         {"doc_id": s("条目 id，形如 note-20260924094556-d4f901")}, ["doc_id"], read_only=True),
    tool("kb_create_entry", "创建知识条目",
         "按规范创建条目，落盘到该 kind 对应的 Knowledge 子目录。" + COMMON_WRITE_NOTE,
         {"kind": s("条目类型", enum=KIND_ENUM),
          "title": s("完整标题；与 name 二选一，给出时优先使用"),
          "name": s("名称段（不含前缀与类别词），由工具按规范拼标题"),
          "category": s("类别词（仅 note 使用；name 模式未给时会从名称推断校验）", enum=CATEGORY_ENUM),
          "note_suffix": s("补充说明，写成全角括号 `（…）` 追加在标题末尾"),
          "status": s("状态；缺省取该 kind 的首个状态"),
          "body": s("正文 Markdown；缺省使用该 kind 的默认骨架"),
          "projects": arr("归属项目名列表（会校验项目是否存在）"),
          "tags": arr("标签列表"),
          "kind_marks": arr("kind_marks 标记 id 列表", items="string"),
          "summary_type": s("仅 summary：阶段总结/里程碑总结等"),
          "record_date": s("journal/summary 的记录日期 YYYY-MM-DD"),
          "due": s("仅 milestone：截止日期 YYYY-MM-DD"),
          "authors": s("仅 literature：作者"),
          "year": s("仅 literature：年份"),
          "venue": s("仅 literature：期刊/会议"),
          "doi": s("仅 literature：DOI"),
          "url": s("仅 literature：链接"),
          "cite_key": s("仅 literature：BibTeX 引用键"),
          "allow_violation": b("跳过命名规范硬校验强制建档（不推荐）")},
         ["kind"], destructive=False),
    tool("kb_update_entry", "更新知识条目",
         "按白名单字段更新条目与正文；id/kind/created 不可变。" + COMMON_WRITE_NOTE,
         {"doc_id": s("条目 id"),
          "title": s("新标题（会同步首个 H1；批量改名请改用 kb_rename_entry）"),
          "status": s("新状态"),
          "body": s("新的完整正文 Markdown（整体覆盖）"),
          "projects": arr("归属项目名列表（整体覆盖）"),
          "tags": arr("标签列表（整体覆盖）"),
          "kind_marks": arr("kind_marks 标记 id 列表（整体覆盖）"),
          "pinned": b("是否置顶"),
          "summary_type": s("仅 summary：阶段总结/里程碑总结等"),
          "record_date": s("journal/summary 的记录日期 YYYY-MM-DD"),
          "due": s("仅 milestone：截止日期 YYYY-MM-DD"),
          "added_date": s("仅 literature：收录日期 YYYY-MM-DD"),
          "authors": s("仅 literature：作者"),
          "year": s("仅 literature：年份"),
          "venue": s("仅 literature：期刊/会议"),
          "doi": s("仅 literature：DOI"),
          "url": s("仅 literature：链接"),
          "cite_key": s("仅 literature：BibTeX 引用键"),
          "allow_violation": b("跳过命名规范硬校验强制写入（不推荐）")},
         ["doc_id"], destructive=False),
    tool("kb_rename_entry", "按规范改名条目",
         "标题改名专用流程：校验新标题、同步首个 H1、重写全库交叉引用，"
         "并只追加一次 doc_update 事件；id/created 保持不变。",
         {"doc_id": s("条目 id"),
          "new_title": s("新完整标题；与 new_name 二选一"),
          "new_name": s("新名称段（配合 new_category）"),
          "new_category": s("新类别词（仅 note）", enum=CATEGORY_ENUM),
          "note_suffix": s("补充说明（全角括号内容）"),
          "update_references": b("是否同步重写其他条目中的交叉引用", default=True),
          "dry_run": b("只返回改名计划与影响面，不落盘"),
          "allow_violation": b("跳过命名规范硬校验强制改名（不推荐）")},
         ["doc_id"], destructive=False),
    tool("kb_change_kind", "迁移条目类型（换 kind）",
         "v261008.2 · 把条目改挂到另一类 kind：目录随动、标题前缀按目标类型改写、`id`/`created` 不变、"
         "可选同步全库交叉引用；用于把老的 `知识-实验-…` 迁到 `实验-…` 等结构性调整。"
         "默认返回迁移计划，需 `dry_run=false` 才落盘。",
         {"doc_id": s("条目 id"),
          "new_kind": s("目标类型", enum=KIND_ENUM),
          "new_title": s("迁移后的完整标题；留空则按目标类型前缀自动改写"),
          "update_references": b("是否同步重写其他条目中的交叉引用", default=True),
          "dry_run": b("只返回迁移计划与影响面，不落盘"),
          "allow_violation": b("跳过命名规范硬校验强制迁移（不推荐）")},
         ["doc_id", "new_kind"], destructive=False),
    tool("kb_delete_entry", "删除知识条目",
         "删除条目并移入 System/Trash/<kind>/，写入 doc_delete 事件；默认先返回预览，需 confirm=true 才执行。",
         {"doc_id": s("条目 id"), "confirm": b("确认执行删除")},
         ["doc_id"], destructive=True),
    tool("kb_check_entries", "批量体检命名合规",
         "对全库或指定条目做命名规范体检，输出可定位的问题清单（错误/警告 + 规则码）。"
         "可选联动校验 title 与首个 H1 是否一致。",
         {"doc_id": s("只校验该条目；留空则批量扫描"),
          "kind": s("批量扫描时限定条目类型", enum=KIND_ENUM),
          "limit": i("批量扫描条数上限", default=60, minimum=1, maximum=200),
          "check_h1": b("额外读取正文，校验 title 与首个 H1 一致"),
          "include_ok": b("连合规条目一并返回")},
         read_only=True),
    tool("kb_variants", "列某条条目的版本族",
         "同一笔记的不同版本（含外部工具添加的）都归在一条「版本族」里：返回基条、各版本与其来源"
         "（工作台界面 / 内核 Agent / 外部 MCP 客户端 / 插件），以及已归档清单。",
         {"doc_id": s("任一条目的 id（基条或某个版本都行）")}, ["doc_id"], read_only=True),
    tool("kb_merge_variants", "按小节合并版本族",
         "先选基准（基条），再逐节指定用哪个版本的内容；合并结果写回基条。可顺带归档被合并掉的版本。"
         "写操作受「设置 → 外部接入」的 MCP 写入授权约束。",
         {"base_id": s("族里的基条 id"),
          "picks": {"type": "object", "description": "小节标题 -> 来源版本 id；未列出的小节沿用基准",
                    "additionalProperties": {"type": "string"}},
          "archive_merged": b("合并后把被替换的版本一并归档")},
         ["base_id"], destructive=False),
    tool("kb_archive_variants", "归档指定版本",
         "把版本移入 Workspace/System/Versions/<基条>/archived/ 永久保留（可追溯、可再取回），"
         "主库与检索里不再出现。写操作受外部接入授权约束。",
         {"base_id": s("族里的基条 id"),
          "variant_ids": {"type": "array", "items": {"type": "string"}, "description": "要归档的版本 id"}},
         ["base_id", "variant_ids"], destructive=False),
    tool("kb_branch_entry", "开一条分支（同一笔记的另一个版本）",
         "以某条条目为源复制内容成一个新版本：记录 variant_of / variant_label，"
         "并记下这条分支的**创建时间** variant_at。改完用 kb_merge_variants 合并。"
         "写操作受「设置 → 外部接入」的 MCP 写入授权约束。",
         {"doc_id": s("源条目 id（基条或任一版本都行）"),
          "label": s("版本名，如 v2 / 2026-10-12-开题稿；留空按时间戳生成"),
          "title": s("新标题；留空为「源标题（版本名）」"),
          "body": s("正文；留空则复制源正文")},
         ["doc_id"], destructive=False),
]
