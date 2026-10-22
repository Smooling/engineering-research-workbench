"""桥接层 —— 让 MCP 直接复用工作台自身的 ``app`` 包。

MCP 不重新实现文件读写，而是调用与 Web 服务同一套代码，因此
原子写入、回收站删除、活动日志、项目注册表与 SQLite 索引的行为完全一致。
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


class WorkbenchError(RuntimeError):
    """统一的工具层错误，携带可读中文提示。"""


class Workbench:
    """工作台数据访问门面（惰性加载 ``app`` 包）。"""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = (repo_root or REPO_ROOT).resolve()
        #: MCP `initialize` 里 clientInfo.name（来源追踪用）
        self.client_name: str = ""
        self._mod: SimpleNamespace | None = None

    # ------------------------------------------------------------ 模块加载
    @property
    def mod(self) -> SimpleNamespace:
        if self._mod is None:
            root = str(self.repo_root)
            if root not in sys.path:
                sys.path.insert(0, root)
            try:
                from app import (activity, config, indexer, projects, store, todos,
                                 versions, workspace)
            except Exception as exc:  # pragma: no cover - 环境缺失时给出可读提示
                raise WorkbenchError(f"无法加载工作台 app 包（{self.repo_root}）：{exc}") from exc
            config.init()  # v261009 · 配置初始化改由入口显式触发（不再在 config 模块 import 期执行）
            self._mod = SimpleNamespace(
                activity=activity, config=config, indexer=indexer, projects=projects,
                store=store, todos=todos, workspace=workspace,
                versions=versions,      # v261009.45 · 版本族（MCP 的开分支/合并/族视图用它）
            )
        return self._mod

    @property
    def root(self) -> Path:
        """工作区绝对路径（``Workspace/``）。"""
        return self.mod.config.workspace_root()

    def rel(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.root.resolve())).replace("\\", "/")
        except Exception:
            return str(path)

    # ------------------------------------------------------------ 工作区
    def info(self) -> dict[str, Any]:
        m = self.mod
        data = m.workspace.workspace_info()
        idx = m.indexer.status()
        return {
            "workspace_root": str(data.get("root")),
            "workspace_relative": data.get("relative"),
            "layout": data.get("layout"),
            "project_layout": data.get("project_layout"),
            "index": {
                "schema_version": idx.get("schema_version"),
                "workspace_schema_version": idx.get("workspace_schema_version"),
                "last_sync": idx.get("last_sync"),
                "counts": idx.get("counts"),
            },
        }

    def tree(self, max_depth: int = 3, max_entries: int = 400) -> dict[str, Any]:
        return self.mod.workspace.tree(max_depth=max(1, min(8, int(max_depth))), max_entries=max(50, min(1800, int(max_entries))))

    # ------------------------------------------------------------ 条目读写
    def list_entries(
        self, kind: str = "", query: str = "", status: str = "", project: str = "", mark: str = "",
        tag: str = "", unowned: bool = False, sort: str = "", page: int = 1, page_size: int = 20,
    ) -> dict[str, Any]:
        """列举条目（过滤 + 分页）。

        修 v261009.50：此前把 `sort` 也传给了索引层的 `list_docs`，而它**不接受** `sort`
        → `TypeError`，导致 `kb_list_entries` / `kb_check_entries` 两个工具**完全不可用**。
        现在只传索引层支持的参数（kind/query/status/project/mark/tag/unowned/page/page_size），
        `sort` 在本地做。
        """
        kwargs: dict[str, Any] = {"kind": kind or None, "query": query or "", "status": status or "",
                                  "project": project or "", "mark": mark or ""}
        if tag:
            kwargs["tag"] = tag
        if unowned:
            kwargs["unowned"] = True
        rows = self.mod.indexer.list_docs(**kwargs)
        if not isinstance(rows, list):        # 防御：万一返回分页字典
            rows = list((rows or {}).get("items") or [])
        if sort == "title":
            rows = sorted(rows, key=lambda d: str(d.get("title") or ""))
        elif sort == "updated":
            rows = sorted(rows, key=lambda d: str(d.get("updated") or ""), reverse=True)
        total = len(rows)
        page = max(1, int(page or 1))
        page_size = max(1, int(page_size or 20))
        start = (page - 1) * page_size
        return {"items": rows[start:start + page_size], "total": total, "page": page,
                "page_size": page_size, "has_more": start + page_size < total}

    def change_kind_entry(self, doc_id: str, new_kind: str, new_title: str = "",
                          status: str = "", kind_marks: list[str] | None = None) -> dict[str, Any]:
        """v261008.2 · 结构性迁移：条目改挂到另一类 kind（id/created 不变，目录随动）。"""
        return self.mod.store.change_kind(doc_id, new_kind, new_title,
                                          status=status, kind_marks=kind_marks)

    def get_entry(self, doc_id: str) -> dict[str, Any]:
        try:
            doc = self.mod.indexer.get_doc(doc_id)
        except FileNotFoundError as exc:
            raise WorkbenchError(f"条目 `{doc_id}` 不存在（已删除或 id 有误）") from exc
        return doc

    def origin(self, tool: str, surface: str = "mcp") -> dict[str, str]:
        """构造来源字段：外部 MCP 客户端 + 工具名 + 客户端名（v261009.41）。"""
        from app import versions

        return versions.origin(surface, tool, self.client_name)

    def create_entry(self, kind: str, payload: dict[str, Any],
                     origin: dict[str, Any] | None = None) -> dict[str, Any]:
        m = self.mod
        if kind not in m.store.kind_dir_map():
            raise WorkbenchError(f"未知条目类型 `{kind}`，取值限定为 " + " / ".join(m.store.kind_dir_map()))
        return m.indexer.create_doc(kind, payload, origin=origin)

    def update_entry(self, doc_id: str, payload: dict[str, Any],
                     origin: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            # 走索引层入口（它内部委派给 store.update_doc，因此来源记录与"分叉/冲突留版"都生效）
            return self.mod.indexer.update_doc(doc_id, payload, origin=origin)
        except FileNotFoundError as exc:
            raise WorkbenchError(f"条目 `{doc_id}` 不存在，无法更新") from exc

    def delete_entry(self, doc_id: str) -> dict[str, Any]:
        doc = self.get_entry(doc_id)
        kind = str(doc.get("kind") or "")
        try:
            self.mod.indexer.delete_doc(doc_id)
        except FileNotFoundError as exc:
            raise WorkbenchError(f"条目 `{doc_id}` 不存在，无法删除") from exc
        return {"ok": True, "doc_id": doc_id, "kind": kind, "title": doc.get("title"),
                "trashed_to": f"System/Trash/{kind}/（可人工恢复）"}

    def entry_path(self, doc_id: str) -> Path:
        doc = self.get_entry(doc_id)
        return self.root / str(doc.get("path") or "")

    def _index_doc(self, doc: dict[str, Any]) -> None:
        try:
            path = self.root / str(doc.get("path") or "")
            self.mod.indexer.index_doc_path(path)
        except Exception:
            pass

    # ------------------------------------------------------------ 项目
    def list_projects(self) -> list[dict[str, Any]]:
        out = []
        for r in self.mod.indexer.project_records():
            out.append({
                "project_id": r.get("id") or "",
                "name": r.get("name") or "",
                "status": r.get("status") or "进行中",
                "description": r.get("description") or "",
                "docs": int(r.get("docs") or 0),
                "milestones": int(r.get("milestones") or 0),
                "open_todos": int(r.get("open_todos") or 0),
                "last_updated": r.get("last_updated") or "",
            })
        return out

    def resolve_project(self, ref: str) -> dict[str, Any]:
        ref = str(ref or "").strip()
        for r in self.list_projects():
            if ref in {str(r.get("project_id") or ""), str(r.get("name") or "")}:
                return r
        raise WorkbenchError(f"未找到项目 `{ref}`；可用项目：" + "、".join(str(r["name"]) for r in self.list_projects()))

    def create_project(self, name: str, description: str = "", status: str = "进行中") -> dict[str, Any]:
        try:
            return self.mod.projects.create_project(name, description, status)
        except ValueError as exc:
            raise WorkbenchError(str(exc)) from exc

    def update_project(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.mod.projects.update_project(project_id, payload)
        except FileNotFoundError as exc:
            raise WorkbenchError(f"项目 `{project_id}` 不存在") from exc

    def project_files(self, ref: str, max_depth: int = 3) -> dict[str, Any]:
        rec = self.resolve_project(ref)
        base = self.root / "Projects" / str(rec["name"])
        if not base.is_dir():
            raise WorkbenchError(f"项目目录不存在：{self.rel(base)}")
        max_depth = max(1, min(6, int(max_depth)))
        files: list[dict[str, Any]] = []

        def walk(path: Path, depth: int) -> None:
            try:
                items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.casefold()))
            except OSError:
                return
            for item in items:
                if item.name.startswith("."):
                    continue
                if item.is_dir():
                    if depth < max_depth:
                        walk(item, depth + 1)
                else:
                    try:
                        st = item.stat()
                    except OSError:
                        continue
                    files.append({
                        "path": self.rel(item), "size": st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                    })

        walk(base, 1)
        return {"project": rec["name"], "project_id": rec["project_id"], "count": len(files), "files": files[:400]}

    # ------------------------------------------------------------ 待办
    def list_todos(self, include_done: bool = True) -> list[dict[str, Any]]:
        items = self.mod.indexer.list_todos()
        if not include_done:
            items = [x for x in items if not x.get("done")]
        return items

    def create_todo(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = self.mod.todos.create(payload)
        try:
            self.mod.indexer.refresh_todos()
        except Exception:
            pass
        return item

    def update_todo(self, todo_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            item = self.mod.todos.update(todo_id, payload)
        except FileNotFoundError as exc:
            raise WorkbenchError(f"待办 `{todo_id}` 不存在") from exc
        try:
            self.mod.indexer.refresh_todos()
        except Exception:
            pass
        return item

    # ------------------------------------------------------------ 检索与洞察
    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.mod.indexer.search_all(query, limit=max(1, min(60, int(limit))))

    def graph_overview(self, limit: int = 80) -> dict[str, Any]:
        return self.mod.indexer.graph_overview(limit=limit)

    def graph_neighborhood(self, doc_id: str, depth: int = 1) -> dict[str, Any]:
        return self.mod.indexer.graph_neighborhood(doc_id, depth=depth)

    def dashboard(self) -> dict[str, Any]:
        return self.mod.indexer.dashboard()

    def export_bibtex(self, ids: list[str] | None = None) -> dict[str, Any]:
        return self.mod.indexer.export_bibtex(ids)

    def activity(self, days: int = 7) -> dict[str, Any]:
        since = date.today() - timedelta(days=max(1, min(400, int(days)))) if days else None
        events = self.mod.activity.list_events(since)
        by_type: dict[str, int] = {}
        for e in events:
            key = str(e.get("type") or "activity")
            by_type[key] = by_type.get(key, 0) + 1
        return {"since": since.isoformat() if since else None, "count": len(events), "by_type": by_type, "events": events[-200:]}

    # ------------------------------------------------------------ 索引维护
    def index_status(self) -> dict[str, Any]:
        return self.mod.indexer.status()

    def reindex(self) -> dict[str, Any]:
        self.mod.indexer.rebuild()
        return self.mod.indexer.status()


_singleton: Workbench | None = None


def get_workbench() -> Workbench:
    global _singleton
    if _singleton is None:
        _singleton = Workbench()
    return _singleton
