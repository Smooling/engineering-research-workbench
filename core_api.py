"""`core_api` —— 插件**唯一允许** import 的内核门面（PLUGIN_SPEC §6 代码隔离）。

插件只写 `from core_api import log` 这类导入；**不得** import `core.*` 私有模块、
`app.*`，也不得 import 别的插件。`tools/plugin_check.py` 会对内核侧做反向检查
（内核不得 import 插件），而插件的合规由加载器在运行期把关（§7 冲突与权限）。

这里保持**最小面**：只放插件真正需要、且内核承诺长期稳定的东西。要加东西是**有意的动作**——
每加一项都要在 docs/PLUGIN_SPEC.md §6 里写清语义。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: 内核 API 版本，与 `core.plugins.manifest.SUPPORTED_API_VERSION` 同源
API_VERSION = 1


def _data_root() -> Path:
    """可写数据根，沿用桌面端的 --data-dir 设置。"""
    from app.paths import DATA_ROOT

    return DATA_ROOT


def plugin_dir(plugin_id: str) -> Path:
    """插件自己的目录（只读代码 + 资源）。"""
    from core.plugins.registry import default_roots
    from app.paths import ASSET_ROOT

    for _, source_root in default_roots(_data_root(), asset_root=ASSET_ROOT):
        candidate = source_root / plugin_id
        if candidate.is_dir():
            return candidate
    return _data_root() / "plugins" / plugin_id


def cache_db(plugin_id: str) -> Path:
    """插件自有派生库路径：`System/Cache/<id>.sqlite`（§3 只允许这一类）。"""
    return _data_root() / "Workspace" / "System" / "Cache" / f"{plugin_id}.sqlite"


def workspace_dir(plugin_id: str) -> Path:
    """插件自有用户数据目录：`Workspace/Plugins/<id>/`。"""
    return _data_root() / "Workspace" / "Plugins" / plugin_id


def data_root() -> Path:
    """可写数据根（打包态是 exe 同级，开发态是仓库根）。

    插件通常**不需要**它 —— 优先用 `plugin_dir` / `system_dir` / `workspace_dir` /
    `config_path` 这些**命名空间内**的助手。正当用途只有两个：

    1. **一次性迁移**：把内核时代写在别处（如 `System/Cache/*`）的数据认领进插件自己的命名空间；
    2. **归档/备份类插件枚举文件**（如 `plugins/backup-snapshot`）：备份天然要读到 `Workspace/**` 与
       `config/**`，这是它的职责；但**写入仍然只该落在自己的命名空间**，除非用户显式指定了外部目标目录。
    """
    return _data_root()


def http_get(url: str, timeout: float = 8.0, headers: dict | None = None, limit: int = 8 * 1024 * 1024) -> bytes:
    """取 URL 的内容（字节，限长）。插件出网的推荐方式。

    带**代理兜底**：系统代理若指向回环地址而端口没人监听（Clash/V2Ray 没启动的常见情形），
    本次请求自动改走直连，避免所有出网请求都撞上 `WinError 10061`；真正的远程代理不受影响，
    超时 / DNS 失败 / 非 2xx 也照原样抛出（详见 `core/net.py`）。
    """
    from core import net

    return net.read_url(url, timeout=timeout, headers=headers, limit=limit)


# ---- 文献（文献库由**核心**维护：梳理与阅读进核心，见 docs/SCOPE.md §2.1/§2.2）----
# 插件若要做「文献侧」的功能（如文献笔记工具包），通过这些函数访问核心的文献库，
# **不要**自己去读 Workspace 下的 PDF/Notes 文件（那是核心的数据结构，见 §6 隔离）。

def lit_list(query: str = "", status: str = "", page: int = 1, page_size: int = 50) -> dict:
    """列出文献条目（分页）。字段与 `/api/literature` 一致。"""
    from app import literature

    return literature.list_items(query=query, status=status, page=page, page_size=page_size)


def lit_item(paper_id: str) -> dict:
    """取单篇文献的元信息（含 `doc_id` 关联、阅读状态、标签）。"""
    from app import literature

    return literature.get_item(paper_id)


def lit_note(paper_id: str) -> str:
    """读该文献的笔记正文（与知识库条目正文同源）。"""
    from app import literature

    return literature.get_note(paper_id)


def lit_note_save(paper_id: str, content: str) -> dict:
    """写该文献的笔记正文。

    **写操作的安全闸门在内核**：插件注册的**写工具**在 confirm 模式下只会生成草稿，
    用户确认后内核才以 direct 模式调用插件 handler（见 `app/agent_tools.execute`）。
    所以插件 handler 里直接写即可，不要自己再实现一套确认逻辑。
    """
    from app import literature

    return literature.save_note(paper_id, content)


def lit_annotations(paper_id: str, page: int | None = None) -> list:
    """读该文献的批注（可选按页过滤）。"""
    from app import literature

    return literature.get_annotations(paper_id, page)


def lit_note_image(paper_id: str, data_url: str) -> dict:
    """把 data_url 图片落盘到**笔记图片目录**，返回路径口径与附件一致的引用（供笔记 Markdown 使用）。

    与核心阅读器「插入图片」走的是同一个核心实现（`literature.save_note_image`）。
    """
    from app import literature

    return literature.save_note_image(paper_id, data_url)


def system_dir(plugin_id: str) -> Path:
    """插件自有系统数据目录：`System/Plugins/<id>/`。"""
    return _data_root() / "Workspace" / "System" / "Plugins" / plugin_id


# ---- 知识条目 / 项目 / 总览（只读；v261009.23 起插件可用的数据窗口）----
# 插件要用知识库数据时**走这里**（与前端 `/api/docs`、`/api/projects` 同一套查询实现），
# **不要**自己去读 `Workspace/Knowledge/*.md`：那是核心的数据结构，绕过索引会看到过期或半写的状态（§6 隔离）。

def entry(doc_id: str) -> dict:
    """取一条知识条目的完整内容（**含 `body` 正文**）。找不到时抛 `FileNotFoundError`。"""
    from app import indexer

    return indexer.get_doc(doc_id)


def entry_update(doc_id: str, *, body: str | None = None, origin: dict | None = None,
                 **fields) -> dict:
    """更新一条知识条目（正文 `body` 与/或白名单字段），返回更新后的完整条目。

    **写操作的安全闸门在内核**：插件注册的**写工具**（`spec` 里 `"write": True`）在 confirm 模式下
    只会生成草稿，用户确认后内核才以 direct 模式调用插件 handler（见 `app/agent_tools.execute`）。
    所以插件 handler 里直接调本函数即可，**不要**自己再实现一套确认逻辑（插件也拿不到 `save_draft`）。

    写入走内核的**校验路径**（`app/store.py` 的 `update_doc`：字段白名单取自 `core/contracts`、
    原子写、记 `doc_update` 活动），不是"帮插件绕开规则直接改文件"。
    条目不存在时抛 `FileNotFoundError`；没有可写内容时抛 `ValueError`。
    """
    from app import indexer

    payload: dict = {k: v for k, v in fields.items() if v is not None}
    if body is not None:
        payload["body"] = body
    if not payload:
        raise ValueError("entry_update 需要 body 或至少一个可写字段")
    # v261009.38 · 插件写知识库受「外部接入授权」约束（设置 → 外部接入 → 允许插件写入知识库）：
    # 关掉它即"只读工作台"——插件仍可写自己的命名空间与配置，只是不碰知识库。
    from app import external_access

    ok, reason = external_access.allowed("plugin_write")
    if not ok:
        raise PermissionError(reason)
    from app import versions

    # v261009.41 · 来源：插件可用 `origin={"tool": "<插件 id>"}` 说明是谁写的
    _origin = dict(origin or versions.origin("plugin"))
    _origin.setdefault("origin_surface", "plugin")
    return indexer.update_doc(doc_id, payload, origin=_origin)


def entries(kind: str | None = None, *, query: str = "", status: str = "", project: str = "",
            mark: str = "", tag: str = "", unowned: bool = False,
            limit: int = 200, page: int = 1) -> list[dict]:
    """列出知识条目（只含元数据与摘要，**不含正文**）。

    字段与 `/api/docs` 一致（`id/kind/title/status/projects/tags/marks/updated/created/pinned/…`）。
    需要正文就按 id 逐条 `entry(doc_id)` —— 列表刻意不返回正文：一次拉几百条正文很慢，
    而且多数调用方（列表、统计、筛选）根本用不上。
    """
    from app import indexer

    want = max(1, int(limit or 1))
    out: list[dict] = []
    cursor = max(1, int(page or 1))
    while len(out) < want:
        chunk = indexer.list_docs(kind, query, status, project, mark, tag=tag, unowned=unowned,
                                  page=cursor, page_size=min(want - len(out), 200), paged=True)
        rows = list((chunk or {}).get("items") or [])
        out.extend(rows)
        if not rows or not (chunk or {}).get("next_page"):
            break
        cursor = int(chunk["next_page"])
    return out[:want]


def projects() -> list[dict]:
    """项目注册表（含 `project_id`/名称/状态/计数），与 `/api/project-records` 同源。"""
    from app import indexer

    return indexer.project_records()


def project_names() -> list[str]:
    """项目名列表（与 `/api/projects` 同源）。"""
    from app import indexer

    return indexer.project_names()


def todos(include_done: bool = True) -> list[dict]:
    """待办清单（`System/todos.json`），字段与 `/api/todos` 一致：

    `id/title/done/project/due/priority/completed_at/overdue`。
    `due` 为 `YYYY-MM-DD`（当天 23:59 截止）或 `YYYY-MM-DD HH:MM`（精确到分）；
    `overdue` 是读取时派生的布尔值；`completed_at` 记录实际完成时间。

    默认含已完成项；只关心待办的传 `include_done=False`。
    """
    from app import indexer

    rows = indexer.list_todos()
    return list(rows) if include_done else [r for r in rows if not r.get("done")]


def dashboard() -> dict:
    """工作台总览统计（条目/项目/待办/活动计数），与 `/api/dashboard` 同源。"""
    from app import indexer

    return indexer.dashboard()


def kind_labels() -> dict[str, str]:
    """七类 kind 的中文标签（`{"note": "笔记", …}`）。

    插件**不要**自己再抄一份标签表（前端有等价的 `window.ERWContract.kindLabels()`）：
    权威声明在 `core/contracts/kinds.py`，这里只是把它原样递给插件。
    """
    from core.contracts import kinds as contracts

    return dict(contracts.KIND_LABELS)


def kind_order() -> list[str]:
    """kind 的契约顺序（报告、目录、统计按它排列，保证各插件输出一致）。"""
    from core.contracts import kinds as contracts

    return list(contracts.KIND_ORDER)


def kernel_version() -> str:
    """内核版本（`VERSION` 文件的内容，如 `v261009.24`）。

    给需要写"由谁生成"这类来源信息的插件用（快照清单、导出文档、备份元数据）。
    去掉 UTF-8 BOM 再返回；读不到时返回空串。
    """
    from core.plugins import manifest as _manifest

    try:
        return _manifest.read_core_version(_data_root())
    except Exception:
        return ""


def config_path(plugin_id: str) -> Path:
    """插件自有配置：`config/plugins/<id>.json`（内核不解释其内容）。"""
    return _data_root() / "config" / "plugins" / f"{plugin_id}.json"


def read_config(plugin_id: str, default: dict | None = None) -> dict:
    path = config_path(plugin_id)
    if not path.is_file():
        return dict(default or {})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(default or {})
    except (OSError, json.JSONDecodeError):
        return dict(default or {})


def write_config(plugin_id: str, data: dict) -> None:
    path = config_path(plugin_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def log(plugin_id: str, message: str) -> None:
    """插件日志（带插件前缀，便于在内核日志里区分）。"""
    print(f"[plugin:{plugin_id}] {message}", flush=True)


__all__ = [
    "API_VERSION", "plugin_dir", "cache_db", "workspace_dir", "data_root", "system_dir",
    "config_path", "read_config", "write_config", "http_get", "log",
    "lit_list", "lit_item", "lit_note", "lit_note_save", "lit_annotations", "lit_note_image",
]

# ---------------------------------------------------------------- 版本族（v261009.44）
#: 插件要做「同一笔记的不同版本」的界面/工具时，走这几个函数即可——**不要**去 import app.versions
#: （I3：插件只许 from core_api import …）。内核负责数据模型与写入时的留版，这里只暴露操作窗口。

def version_overview() -> dict:
    """所有版本族的总览（族数 / 分叉中 / 版本数 + 每族摘要）。

    必须用**文件层**的 `store.list_docs()`，不能用 `entries()`：后者走 SQLite 索引，
    而索引 schema 不含 `variant_of` 这类新字段，会把每个版本都当成独立族（实测踩到：
    总览报 2 个族 / 0 个分叉）。
    """
    from app import store
    from app import versions as V

    families: dict[str, dict] = {}
    for doc in store.list_docs():
        vid = str(doc.get("variant_of") or "").strip()
        base = vid or str(doc.get("id") or "")
        row = families.setdefault(base, {"base_id": base, "base": None, "variants": [], "updated": ""})
        if vid:
            row["variants"].append(doc)
        else:
            row["base"] = doc
        stamp = str(doc.get("updated") or "")
        if stamp > str(row.get("updated") or ""):
            row["updated"] = stamp
    out = []
    for row in families.values():
        if not row["base"] and row["variants"]:
            row["base"] = row["variants"][0]
        out.append({"base_id": row["base_id"], "title": (row["base"] or {}).get("title") or "",
                    "kind": (row["base"] or {}).get("kind") or "", "updated": row["updated"],
                    "variant_count": len(row["variants"]),
                    "variants": [{"id": v.get("id"), "label": v.get("variant_label") or "",
                                  "updated": v.get("updated"), "origin": V.describe_origin(v)}
                                 for v in row["variants"]]})
    out.sort(key=lambda r: (r["variant_count"] == 0, str(r["updated"])[::-1]))
    return {"families": out, "counts": {"families": len(out),
                                        "forked": sum(1 for r in out if r["variant_count"]),
                                        "variants": sum(r["variant_count"] for r in out)}}


def variant_family(doc_id: str, *, with_body: bool = False) -> dict:
    """一个版本族的详情：基条 + 各版本（含来源、小节清单；with_body=True 时带正文）+ 已归档清单。"""
    from app import store
    from app import versions as V

    doc = entry(doc_id)
    base = V.base_id_of(doc)
    fam = V.family(base)

    def row(item, body: bool):
        if not item:
            return {}
        out = {"id": item.get("id"), "title": item.get("title"),
               "label": item.get("variant_label") or "", "status": item.get("status"),
               "updated": item.get("updated"), "created": item.get("created"),
               "origin": V.describe_origin(item), "origin_surface": item.get("origin_surface") or "",
               "sections": [s["heading"] for s in V.split_sections(item.get("body") or "") if s["heading"]]}
        if body:
            out["body"] = item.get("body") or ""
        return out

    # 版本行的正文要**单独取**：`V.family()` 用的是不含正文的列表接口（`store.list_docs`），
    # 只有基条是完整条目。少了这一步，界面做逐节 diff 时会把每个小节都判成"基准独有"（实测踩到）。
    def variant_row(item: dict) -> dict:
        if with_body and item.get("id"):
            try:
                item = store.get_doc(str(item["id"]))
            except FileNotFoundError:
                pass
        return row(item, with_body)

    return {"base_id": base, "forked": fam["forked"], "base": row(fam["base"], with_body),
            "variants": [variant_row(v) for v in fam["variants"]], "archived": fam["archived"],
            "sections": [s["heading"] for s in V.split_sections((fam["base"] or {}).get("body") or "")
                         if s["heading"]]}


def variant_sections(body: str) -> list[str]:
    """正文里的 H2 小节标题（合并时按它挑来源）。"""
    from app import versions as V

    return [s["heading"] for s in V.split_sections(body) if s["heading"]]


def merge_variants(base_id: str, picks: dict, *, archive_merged: bool = False,
                   origin: dict | None = None) -> dict:
    """按小节合并版本族：picks = {小节标题: 来源版本 id}，结果写回基条。

    统一走 `app/versions.merge_family`——界面 / 内核 Agent / 插件 / MCP 四条路径共用同一实现，
    合并会记 `doc_merge` 活动（替换小节、参与版本、时间），不会各写一套。
    """
    from app import versions as V

    return V.merge_family(base_id, picks or {}, archive_merged=archive_merged,
                          origin_info=dict(origin or V.origin("plugin", "merge_variants")))


def auto_merge_variants(base_id: str, *, strategy: str = "agent", variant_ids: list | None = None,
                        apply: bool = False, archive_merged: bool = False,
                        origin: dict | None = None) -> dict:
    """Agent 自动确认版本合并：模型逐节选来源，返回建议（或直接应用）。

    - `strategy="agent"`：调用设置里已启用的模型；不可用/解析失败时**自动回退**到
      「最近更新优先」规则，并在 `note` 里说明原因；
    - `strategy="rule"`：不调用模型，只按规则选；
    - `apply=False`（默认）：只返回 `picks` / `reasons`，由界面展示后再调 `merge_variants`；
    - `apply=True`：直接写回基条（只改正文，不动标题/项目/状态）。

    需要插件在 `plugin.json` 声明 `llm:use`（会消耗已配置模型的用量）。
    """
    from app.merge_ai import propose_picks

    return propose_picks(base_id, strategy=strategy, variant_ids=list(variant_ids or []),
                         apply=apply, archive_merged=archive_merged, origin=origin)

def archive_variants(base_id: str, variant_ids: list) -> dict:
    """归档指定版本到 System/Versions/<基条>/archived/（保留可追溯）。"""
    from app import versions as V

    return V.archive_variants(base_id, [str(x) for x in (variant_ids or []) if str(x).strip()],
                              {"tool": "archive_variants"})


def restore_variant(base_id: str, file_name: str) -> dict:
    """把归档区里的某一份取回成一个活版本。"""
    from app import versions as V

    return V.restore_variant(base_id, file_name)

def activity_events(days: int = 7, *, ref: str = "", refs: list | None = None,
                    types: list | None = None, limit: int = 100) -> dict:
    """活动日志（谁在什么时候改了什么）——**修改记录**的权威来源（v261009.48）。

    - `ref` / `refs`：只看某条（或某几条）条目的事件，用来做"这条笔记的修改记录"；
    - `types`：只看某类事件（doc_create / doc_update / doc_merge / doc_delete …）；
    - 每条事件的 `source` 形如「外部 MCP 客户端 · kb_update_entry · Claude Desktop · 10-12 16:23」。
    """
    from datetime import date, timedelta

    from app import activity

    since = date.today() - timedelta(days=max(1, int(days)))
    events = activity.list_events(since)
    wanted = {str(x) for x in (refs or []) if str(x).strip()}
    if str(ref or "").strip():
        wanted.add(str(ref).strip())
    if wanted:
        events = [e for e in events if str(e.get("ref") or "") in wanted]
    if types:
        keep = {str(t) for t in types}
        events = [e for e in events if str(e.get("type") or "") in keep]
    events = events[-max(1, int(limit)):]
    rows = [{"timestamp": e.get("timestamp"), "type": e.get("type"), "ref": e.get("ref"),
             "kind": e.get("kind"), "title": e.get("title"), "project": e.get("project"),
             "source": e.get("source") or "", "detail": e.get("detail") or {}}
            for e in events]
    return {"since": since.isoformat(), "days": int(days), "count": len(rows), "events": rows}


def external_edits(*, record: bool = False, limit: int = 200) -> dict:
    """外部直接改动巡检（v261009.49）：找出"文件被改过但没有对应记录"的条目。

    `record=True` 会把它们记成 `doc_external_edit` 事件（来源「工作区外部改动」），
    于是会出现在「版本」页的修改记录里——用于发现 IDE/脚本绕过写入收口点的改动。
    """
    from app import external_edits as scanner

    return scanner.scan(record=record, limit=limit)


def adopt_variant(base_id: str, variant_id: str, *, archive_others: bool = False,
                  origin: dict | None = None) -> dict:
    """整版采用：把某版本正文整篇写回基条（"就留这一版"），可选把其余版本归档。"""
    from app import versions as V

    return V.adopt_variant(base_id, variant_id, archive_others=archive_others,
                           origin_info=dict(origin or V.origin("plugin", "adopt_variant")))
