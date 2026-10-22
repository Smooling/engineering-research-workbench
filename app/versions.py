"""笔记多版本 / 分支 / 来源追踪 / 合并归档（v261009.41）。

**为什么放在内核**：工作台界面、内核 Agent 工具、MCP 工具、插件 `core_api.entry_update`
四条写入路径最终都汇到 `app/store.py` 的 `create_doc` / `update_doc`。版本与来源只有在这两个收口点
处理，才能"跟踪工作台内直接添加与外部工具（如 MCP）添加的文件"。

**数据模型**（字段声明在 `core/contracts/kinds.py`，这里只用不另抄）：
- 同一笔记的不同版本 = **同一 kind 下的多条正常条目**，靠 frontmatter 关联：
  `variant_of`（基条 id）+ `variant_label`（人看的版本名）；
- 来源追踪：`origin_surface`（ui/agent/mcp/plugin/cli）+ `origin_tool` + `origin_client` + `origin_at`；
- **归族规则**：界面/工具显式给 `variant_of` 就用它；否则按"标题归一化签名"在同 kind 内找基条
  （外部工具塞进来的 `知识-方法-X（v2）.md` 会被自动归到 `知识-方法-X` 那一族），界面上可手改。

**留版本时机**（用户选定：只在分叉/冲突/归档时，日常编辑仍是覆盖式，磁盘可控）：
- 基条**已处于分叉状态**（族里还有活着的版本）时，任何对基条的写入都先把**写入前的内容**存成一版；
- 写入来源与该条**上一次写入者不同**（例如上次是界面、这次是 MCP）时，同样先存一版——这是"冲突"信号；
- 合并/归档时把参与的各版按用户选择处理（合并结果成为基条，其余归档）。

**归档**：变体移入 `Workspace/System/Versions/<base_id>/archived/<ts>-<label>.md`（**保留可追溯**、
不计入条目数与检索），并在同目录 `index.json` 留一份清单；需要时可 `restore` 取回。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

#: 版本族归档目录（相对 Workspace）
VERSION_SUBDIR = ("System", "Versions")

#: 标题里的"版本后缀"形态：归一化后用于自动归族
#: 注意分成三类：**裸数字**（`（2.2）`）在 experiment 里是**实验编号**而不是版本号，
#: 所以按 kind 决定要不要剥（否则新建 `实验-X（2.3）` 会被误判成 `（2.2）` 的变体）。
_V_SUFFIXES = [
    r"[（(]\s*v\d+(?:[.\-]\d+)*\s*[)）]",                        # （v2）/（v2.1）
    r"[-—–_]\s*v\d+(?:[.\-]\d+)*\s*$",                          # -v2 / - v2 / _v2.1
]
_NUM_SUFFIXES = [
    r"[（(]\s*\d+(?:[.\-]\d+)*\s*[)）]",                         # （2）/（2.2）
    r"[-—–_]\s*\d+(?:[.\-]\d+)*\s*$",                           # -2 / - 2.2
]
_WORD_SUFFIXES = [
    r"[（(]\s*(?:草稿|副本|修订|完善稿|终稿|定稿|存档|旧版|新版)\s*[)）]",
    r"[-—–_]\s*(?:草稿|副本|修订|完善稿|终稿|定稿|存档|旧版|新版)\s*$",
]


def _suffixes_for(kind: str) -> list[str]:
    """实验条目的 `（数字）` 是编号，不能当版本后缀剥掉。"""
    if str(kind or "") == "experiment":
        return _V_SUFFIXES + _WORD_SUFFIXES
    return _V_SUFFIXES + _NUM_SUFFIXES + _WORD_SUFFIXES


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def title_signature(title: str, kind: str = "") -> str:
    """标题的「族签名」：去掉版本后缀与空白。`知识-方法-X（v2）` 与 `知识-方法-X` 同签名。

    `kind` 影响剥后缀的口径：**实验条目的 `（2.2）` 是编号**（命名规范强制带编号），
    不能当版本后缀，否则 `实验-X（2.3）` 会被误判成 `（2.2）` 的变体。
    """
    text = str(title or "").strip()
    patterns = _suffixes_for(kind)
    for _ in range(3):                       # 允许叠后缀（如 `X（v2）-副本`）
        before = text
        for pattern in patterns:
            text = re.sub(pattern, "", text).strip()
        if text == before:
            break
    return re.sub(r"\s+", "", text)


def label_from_title(title: str, signature: str = "", kind: str = "") -> str:
    """从标题里抽出人看的版本标签（`（v2）`→`v2`），抽不到就返回空。"""
    sig = signature or title_signature(title, kind)
    raw = str(title or "").strip()
    if raw == sig:
        return ""
    tail = raw[len(sig):].strip() if raw.startswith(sig) else raw.replace(sig, " ", 1).strip()
    return tail.strip(" -—–_（）()") or ""


# --------------------------------------------------------------------------- 来源

def origin(surface: str, tool: str = "", client: str = "") -> dict[str, str]:
    """构造来源字段（写进 frontmatter 的扁平字符串）。"""
    return {
        "origin_surface": str(surface or "").strip() or "cli",
        "origin_tool": str(tool or "").strip(),
        "origin_client": str(client or "").strip(),
        "origin_at": _now(),
    }


def describe_origin(doc: dict[str, Any]) -> str:
    """把来源字段说成人话，供界面/工具展示。"""
    surface = str(doc.get("origin_surface") or "").strip()
    if not surface:
        return "（未记录来源）"
    names = {"ui": "工作台界面", "agent": "内核 Agent", "mcp": "外部 MCP 客户端",
             "plugin": "插件", "cli": "命令行"}
    parts = [names.get(surface, surface)]
    if doc.get("origin_tool"):
        parts.append(str(doc["origin_tool"]))
    if doc.get("origin_client"):
        parts.append(str(doc["origin_client"]))
    if doc.get("origin_at"):
        parts.append(str(doc["origin_at"]).replace("T", " ")[:16])
    return " · ".join(parts)


# --------------------------------------------------------------------------- 族

def base_id_of(doc: dict[str, Any]) -> str:
    """这条条目所属的基条 id（基条自己返回自身 id）。"""
    return str(doc.get("variant_of") or doc.get("id") or "")


def is_variant(doc: dict[str, Any]) -> bool:
    return bool(str(doc.get("variant_of") or "").strip())


def family(base_id: str) -> dict[str, Any]:
    """返回一个版本族：基条 + 活着的各版本 + 已归档清单。"""
    from app import store

    base = None
    try:
        base = store.get_doc(base_id)
    except FileNotFoundError:
        base = None
    variants = []
    for doc in store.list_docs():
        if str(doc.get("variant_of") or "") == base_id:
            variants.append(doc)
    variants.sort(key=lambda d: (str(d.get("variant_at") or d.get("created") or ""),
                                 str(d.get("title") or "")))
    return {
        "base_id": base_id,
        "base": base,
        "variants": variants,
        "archived": archived_index(base_id),
        "forked": bool(variants),
        "count": len(variants) + (1 if base else 0),
        # 每条分支的时间（v261009.45）：创建 variant_at（缺省回退 created）/ 最近写入 updated / 该次写入时间 origin_at
        "times": {str(d.get("id")): {"variant_at": d.get("variant_at") or d.get("created") or "",
                                    "created": d.get("created") or "",
                                    "updated": d.get("updated") or "",
                                    "origin_at": d.get("origin_at") or ""}
                  for d in variants},
    }


def is_snapshot(doc: dict[str, Any]) -> bool:
    """是不是"内核自动留的改动前快照"（区别于用户显式开的分支）。"""
    return str(doc.get("origin_tool") or "").startswith("snapshot")


def latest_variant(base_id: str) -> dict[str, Any] | None:
    """族里**最新**的活版本（按 variant_at/created，缺省回退 updated）——"默认合并最新版"的口径。"""
    items = family(base_id)["variants"]
    if not items:
        return None
    return sorted(items, key=lambda d: str(d.get("variant_at") or d.get("created") or d.get("updated") or ""))[-1]


def find_same_signature(kind: str, title: str, exclude_id: str = "") -> str | None:
    """在同 kind 里找"标题同签名"的基条（外部工具塞进来的版本靠它自动归族）。"""
    from app import store

    sig = title_signature(title, kind)
    if not sig:
        return None
    best: str | None = None
    for doc in store.list_docs(kind):
        doc_id = str(doc.get("id") or "")
        if not doc_id or doc_id == exclude_id or is_variant(doc):
            continue
        if title_signature(str(doc.get("title") or ""), kind) == sig:
            # 同签名多条时取最早创建的那条当基条，保证族稳定
            if best is None or str(doc.get("created") or "") < str(
                    next((d.get("created") for d in store.list_docs(kind) if d.get("id") == best), "") or ""):
                best = doc_id
    return best


def mark_base_forked(base_id: str, forked: bool) -> None:
    """在基条上维护 `has_variants` 标记。

    为什么需要它：`update_doc` 每次写入都要判断"族是否处于分叉中"，若每次都扫全库（200 条约 76ms）
    会让每次保存都变慢；有了这个 O(1) 标记，热路径零成本，全量扫描只留给界面与工具。
    """
    from app import store

    try:
        doc = store.get_doc(base_id)
    except FileNotFoundError:
        return
    if bool(doc.get("has_variants")) == bool(forked):
        return
    try:
        store.update_doc(base_id, {"has_variants": bool(forked)},
                         origin=origin("cli", "mark_forked"),
                         _skip_versioning=True)
    except Exception:                     # 标记失败不影响主流程（下次写入会重试）
        pass


def snapshot_before_write(doc: dict[str, Any], reason: str = "") -> dict[str, Any] | None:
    """把 `doc` 的**当前内容**另存为一个版本条目（在覆盖写入之前调用）。

    触发时机（用户选定）：① 族已处于分叉中；② 写入来源与该条上次写入者不同（冲突信号）。

    **每族只保留一个自动快照**（v261009.56）：族里已有"快照型"版本时**覆盖它**而不是再新建一版——
    否则同一条笔记被外部工具改几次就会堆出好几个版本条目（用户反馈"不要存这么多笔记"）。
    显式开的分支（`create_branch` / `kb_branch_entry`）不受影响，仍然各自独立保留。
    """
    from app import store

    try:
        current = store.get_doc(str(doc.get("id") or ""))
    except FileNotFoundError:
        return None
    base = base_id_of(current)
    body = str(current.get("body") or "")
    label = f"v-{datetime.now().strftime('%m%d-%H%M%S')}"
    # 已有自动快照 → 覆盖它（保留原 id，改内容与时间；标题同步成新的时间戳标签）
    for variant in family(base)["variants"]:
        if is_snapshot(variant):
            store.update_doc(str(variant["id"]),
                             {"title": f"{current.get('title') or base}（{label}）",
                              "body": body, "variant_label": label, "variant_at": _now()},
                             origin=origin("cli", f"snapshot:{reason[:40]}"), _skip_versioning=True)
            mark_base_forked(base, True)
            try:
                return store.get_doc(str(variant["id"]))
            except FileNotFoundError:
                return variant
    payload = {
        "title": f"{current.get('title') or base}（{label}）",
        "status": current.get("status"),
        "tags": current.get("tags") or [],
        "kind_marks": current.get("kind_marks") or [],
        "variant_of": base,
        "variant_label": label,
        "body": body,
    }
    snap = store.create_doc(str(current.get("kind") or "note"), payload,
                            origin=origin("cli", f"snapshot:{reason[:40]}"), _skip_versioning=True)
    mark_base_forked(base, True)
    return snap


# --------------------------------------------------------------------------- 归档区

def version_dir(base_id: str) -> Path:
    from app import workspace

    return workspace.ensure_workspace().joinpath(*VERSION_SUBDIR) / base_id


def archived_dir(base_id: str) -> Path:
    return version_dir(base_id) / "archived"


def archived_index(base_id: str) -> list[dict[str, Any]]:
    path = version_dir(base_id) / "index.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _write_index(base_id: str, rows: list[dict[str, Any]]) -> None:
    directory = version_dir(base_id)
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / "index.tmp"
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(directory / "index.json")


# --------------------------------------------------------------------------- 分节与合并

def split_sections(body: str) -> list[dict[str, str]]:
    """按 H2（`## `）切正文。返回 [{heading, text}]，第一段的 heading 为空（前言）。"""
    text = str(body or "")
    lines = text.splitlines()
    sections: list[dict[str, str]] = []
    current_heading = ""
    current: list[str] = []
    for line in lines:
        if re.match(r"^##\s+\S", line):
            sections.append({"heading": current_heading, "text": "\n".join(current).strip("\n")})
            current_heading = line.strip()[3:].strip()
            current = [line]
            continue
        current.append(line)
    sections.append({"heading": current_heading, "text": "\n".join(current).strip("\n")})
    return [s for s in sections if s["text"].strip() or s["heading"]]


def merge_bodies(base_body: str, picks: dict[str, str], others: dict[str, str]) -> tuple[str, list[str]]:
    """按小节合并：`picks` 是 {小节标题: 来源版本 id}，`others` 是 {版本 id: 正文}。

    返回 (合并后的正文, **被改动的小节标题列表**)。没被挑中的小节沿用基准。

    改动有两种，都会被记进第二个返回值（v261009.53）：
    - 挑中的来源**有**该小节 → 用来源的内容替换；
    - 挑中的来源**没有**该小节 → 视为**该节被删除**，从结果里去掉（此前是"保持基准"，
      于是"某版本删掉一整节"这种改动根本应用不了——实测踩到）。
    """
    sections = split_sections(base_body)
    replaced: list[str] = []
    out: list[str] = []
    for section in sections:
        heading = section["heading"]
        source_id = picks.get(heading) if heading else None
        if source_id and source_id in others:
            source_sections = {s["heading"]: s["text"] for s in split_sections(others[source_id])}
            if heading in source_sections:
                out.append(source_sections[heading])
                replaced.append(heading)
                continue
            replaced.append(f"{heading}（删除）")     # 来源里没有 → 这节被删掉
            continue
        out.append(section["text"])
    return "\n\n".join(part for part in out if part.strip()) + "\n", replaced


# --------------------------------------------------------------------------- 归档 / 取回

def archive_variants(base_id: str, variant_ids: list[str], origin_info: dict[str, str] | None = None) -> dict[str, Any]:
    """把指定版本移出 Knowledge → `System/Versions/<base>/archived/`（保留可追溯）。"""
    from app import store

    rows = archived_index(base_id)
    moved: list[dict[str, Any]] = []
    for doc_id in variant_ids:
        try:
            doc = store.get_doc(doc_id)
        except FileNotFoundError:
            continue
        if str(doc.get("variant_of") or "") != base_id and doc_id != base_id:
            continue
        if doc_id == base_id:                     # 基条不允许归档（它是族的主条）
            continue
        target_dir = archived_dir(base_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        label = re.sub(r"[^\w\u4e00-\u9fa5.-]+", "-", str(doc.get("variant_label") or doc_id))[:40]
        target = target_dir / f"{stamp}-{label}.md"
        source_path = store.ensure_workspace() / str(doc["path"])
        target.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
        store.delete_doc(doc_id)                  # 移出主库（进回收站，但归档副本已留）
        rows.append({"id": doc_id, "title": doc.get("title"), "label": doc.get("variant_label") or "",
                     "archived_at": _now(), "file": target.name,
                     "origin": describe_origin(doc), "reason": (origin_info or {}).get("tool") or "archive"})
        moved.append({"id": doc_id, "title": doc.get("title"), "file": target.name})
    _write_index(base_id, rows)
    # 归档后更新基条标记：还有活版本就保持 true，否则清掉（否则后续写入会持续留无谓的快照）
    try:
        mark_base_forked(base_id, bool(family(base_id)["variants"]))
    except Exception:
        pass
    return {"base_id": base_id, "archived": moved, "archived_total": len(rows)}


def restore_variant(base_id: str, file_name: str) -> dict[str, Any]:
    """把归档区里的某一份取回成一个活版本（新条目）。"""
    from app import store

    source = archived_dir(base_id) / file_name
    if not source.is_file():
        raise FileNotFoundError(str(source))
    text = source.read_text(encoding="utf-8")
    meta, body = store._frontmatter_parse(text)          # 复用同一套解析
    payload = {
        "title": str(meta.get("title") or f"{base_id}-restored"),
        "status": meta.get("status"),
        "tags": meta.get("tags") or [],
        "kind_marks": meta.get("kind_marks") or [],
        "variant_of": base_id,
        "variant_label": f"{meta.get('variant_label') or 'restored'}",
        "body": body,
    }
    doc = store.create_doc(str(meta.get("kind") or "note"), payload,
                           origin=origin("ui", "restore_variant"), _skip_versioning=True)
    return {"restored": True, "entry": doc, "from": file_name}

def create_branch(source_id: str, *, label: str = "", title: str = "", body: str | None = None,
                  origin_info: dict[str, str] | None = None) -> dict[str, Any]:
    """**开一条分支**：以某条条目（基条或任一版本）为源，复制内容成一个新版本。

    - `label` 缺省用 `v-<时间戳>`；`title` 缺省为「源标题（label）」；
    - 记录 `variant_of`（归族）、`variant_label`（人看的版本名）、**`variant_at`（这条分支的创建时间）**；
    - `body` 给了就用它（例如外部工具已经改好的内容），否则复制源正文。
    """
    from app import store

    source = store.get_doc(str(source_id))
    base = base_id_of(source)
    stamp = datetime.now().strftime("%m%d-%H%M%S")
    label = str(label or "").strip() or f"v-{stamp}"
    payload = {
        "title": str(title or "").strip() or f"{source.get('title')}（{label}）",
        "status": source.get("status"),
        "tags": source.get("tags") or [],
        "kind_marks": source.get("kind_marks") or [],
        "variant_of": base,
        "variant_label": label,
        "variant_at": _now(),
        "body": source.get("body") if body is None else str(body),
    }
    doc = store.create_doc(str(source.get("kind") or "note"), payload,
                           origin=dict(origin_info or origin("cli", "create_branch")),
                           _skip_versioning=True)
    mark_base_forked(base, True)
    return {"base_id": base, "entry": doc, "variant_label": label,
            "variant_at": doc.get("variant_at") or _now(),
            "source_id": str(source_id)}


def merge_family(base_id: str, picks: dict[str, str] | None = None, *, archive_merged: bool = False,
                 origin_info: dict[str, str] | None = None) -> dict[str, Any]:
    """**合并**一个版本族的唯一实现（界面 / 内核 Agent / 插件 / MCP 都调这里）。

    合并正文 → 写回基条 → 记 `doc_merge` 活动（含替换小节、参与版本、是否归档、时间）。
    """
    from app import activity, store

    fam = family(base_id)
    if not fam["base"]:
        raise FileNotFoundError(f"基条不存在：{base_id}")
    picks = dict(picks or {})
    bodies = {v["id"]: (store.get_doc(v["id"]).get("body") or "") for v in fam["variants"]}
    merged, replaced = merge_bodies(fam["base"].get("body") or "", picks, bodies)
    info = dict(origin_info or origin("cli", "merge_family"))
    store.update_doc(base_id, {"body": merged}, origin=info)
    used = sorted({vid for vid in picks.values() if vid in bodies})
    out: dict[str, Any] = {"base_id": base_id, "replaced_sections": replaced, "body_length": len(merged),
                           "merged_from": used, "merged_at": _now()}
    if archive_merged and used:
        out["archived"] = archive_variants(base_id, used, {"tool": "merge_family"})
    try:
        activity.record("doc_merge", ref=base_id, kind=str((fam["base"] or {}).get("kind") or ""),
                        title=str((fam["base"] or {}).get("title") or ""),
                        source=describe_origin(info),
                        detail={"merged_at": out["merged_at"], "replaced_sections": replaced,
                                "merged_from": used, "archive_merged": bool(archive_merged)})
    except Exception:
        pass                      # 活动日志是次要信息，不能拖垮合并
    return out

def adopt_variant(base_id: str, variant_id: str, *, archive_others: bool = False,
                  origin_info: dict[str, str] | None = None) -> dict[str, Any]:
    """**整版采用**：把某个版本的正文整篇写回基条（保留基条的 id/标题/项目）。

    场景：用户看到三四个版本，直接决定"就留这一版"——不必逐节挑。
    `archive_others=True` 时把其余版本一并归档（进 `System/Versions/<基条>/archived/`，可追溯）。
    """
    from app import activity, store

    base = store.get_doc(str(base_id))
    variant = store.get_doc(str(variant_id))
    if base_id_of(variant) != str(base_id):
        raise ValueError(f"`{variant_id}` 不属于 `{base_id}` 这个版本族")
    body = variant.get("body") or ""
    info = dict(origin_info or origin("cli", "adopt_variant"))
    # **先**记下采用前已存在的其他版本：写入本身可能触发"改动前基条"快照，
    # 那一版要留着（用户可回退），不该被一起归档。
    others = [v["id"] for v in family(base_id)["variants"] if v["id"] != str(variant_id)]
    store.update_doc(str(base_id), {"body": body}, origin=info)
    out: dict[str, Any] = {"base_id": str(base_id), "adopted": str(variant_id),
                           "adopted_at": _now(), "body_length": len(body),
                           "other_variants": others}
    if archive_others and others:
        out["archived"] = archive_variants(str(base_id), others, {"tool": "adopt_variant"})
    try:
        activity.record("doc_merge", ref=str(base_id), kind=str(base.get("kind") or ""),
                        title=str(base.get("title") or ""), source=describe_origin(info),
                        detail={"merged_at": out["adopted_at"], "wholesale": True,
                                "adopted": str(variant_id), "archived_others": bool(archive_others)})
    except Exception:      # noqa: BLE001
        pass
    return out
