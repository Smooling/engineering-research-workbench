"""core.doctor —— 知识库与派生索引的只读体检。

用法：
    python -m core.doctor                 # 人读报告
    python -m core.doctor --json          # 机器可读
    python -m core.doctor --strict        # 有 error 级发现时非零退出
    python -m core.doctor --workspace DIR # 指定 Workspace（默认按 config/app.json）

为什么要它（docs/REFACTOR_PLAN.md P3/§5.5.5）：契约、索引与磁盘三者的一致性此前只靠人眼——
已经实际发生过「同一套规则两套校验结论相反」「越界 status/标记进了库」「幽灵项目节点」
「25 条实验不在索引」。这些都能静态查出来，`doctor` 把它们变成一条可重复的命令。

**只读**：本模块只读 Markdown 与 SQLite（`mode=ro` 打开），不写任何东西；
`--fix-*` 之类的修复动作（如有）必须在别处显式实现并先跑 dry-run。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

from .contracts import kinds as C
from .contracts import naming

def _looks_like_variant(path) -> bool:
    """只读文件头判断是不是版本/快照条目（与索引器 `is_variant_file` 同一判据）。

    v261009.57 · 版本条目**不进索引**（只在「版本」页可见），体检的"磁盘 vs 索引数量"
    必须把它们单独计数，否则会误报索引漂移。
    """
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:1200]
    except OSError:
        return False
    if not head.startswith("---"):
        return False
    end = head.find("\n---", 3)
    return "variant_of:" in (head[:end] if end > 0 else head)

#: frontmatter 里合法但不在字段序中的键（历史遗留，契约已确认其存在）
EXTRA_KNOWN_FIELDS = {"project_id", "project_ids", "attachment"}
KNOWN_FIELDS = set(C.FRONTMATTER_ORDER) | EXTRA_KNOWN_FIELDS


# ---------------------------------------------------------------- 读取

def resolve_workspace(arg: str | None, root: Path) -> Path:
    if arg:
        return Path(arg).resolve()
    cfg = root / "config" / "app.json"
    raw = "Workspace"
    if cfg.is_file():
        try:
            raw = str(json.loads(cfg.read_text(encoding="utf-8")).get("workspace") or "Workspace")
        except Exception:
            pass
    p = Path(raw)
    return p if p.is_absolute() else (root / p).resolve()


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """最小 frontmatter 解析器（与 app/store.py 同口径，独立实现以免 doctor 依赖 app）。"""
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.S)
    if not m:
        return {}, text
    meta: dict = {}
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key, value = key.strip(), value.strip()
        if not key:
            continue
        if value.lower() in ("true", "false"):
            meta[key] = value.lower() == "true"
        elif value.startswith("[") and value.endswith("]"):
            try:
                meta[key] = json.loads(value)
            except Exception:
                meta[key] = []
        elif value[:1] in ('"', "'"):
            try:
                meta[key] = json.loads(value) if value.startswith('"') else value.strip("'")
            except Exception:
                meta[key] = value.strip("\"'")
        else:
            try:
                meta[key] = int(value)
            except Exception:
                meta[key] = value
    return meta, text[m.end():]


def as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [x.strip() for x in re.split(r"[,，]", value) if x.strip()]
    return []


def iter_docs(ws: Path):
    for kind, rel in C.KIND_DIRS.items():
        folder = ws / rel
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            try:
                meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            except OSError:
                continue
            yield kind, path, meta, body


def load_index(ws: Path) -> sqlite3.Connection | None:
    db = ws / "System" / "Cache" / "index.sqlite"
    if not db.is_file():
        return None
    try:
        return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


# ---------------------------------------------------------------- 检查项

class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, check: str, level: str, count: int, detail: str, samples: list[str] | None = None) -> None:
        self.items.append({
            "check": check, "level": level, "count": count, "detail": detail,
            "samples": (samples or [])[:8],
        })

    def errors(self) -> int:
        return sum(1 for i in self.items if i["level"] == "error" and i["count"])

    def warns(self) -> int:
        return sum(1 for i in self.items if i["level"] == "warn" and i["count"])


def check_contract_selfconsistency(rep: Report) -> None:
    """契约自洽：字段序与创建/更新字段的关系。（历史问题：attachment 只在 UPDATE 列表）"""
    missing = [
        f for f in C.CREATE_FIELDS
        if f not in set(C.FRONTMATTER_ORDER) | EXTRA_KNOWN_FIELDS and f != "body"  # body 是正文，不是 frontmatter 键
    ]
    only_update = [f for f in C.UPDATE_FIELDS if f not in C.CREATE_FIELDS]
    rep.add(
        "契约·字段自洽", "warn" if (missing or only_update) else "info",
        len(missing) + len(only_update),
        "CREATE 字段不在字段序中" + (f"：{missing}" if missing else "")
        + "；仅 UPDATE 可写" + (f"：{only_update}" if only_update else ""),
    )
    bad = [
        k for k, spec in C.KINDS.items()
        if not spec.get("statuses") or (not spec.get("date_field") and k not in ("idea", "note"))
    ]
    rep.add("契约·类型完整", "error" if bad else "info", len(bad),
            f"缺状态机或日期字段的类型：{bad}" if bad else "七类均有状态机与日期字段")


def configured_marks(root: Path) -> set[str]:
    """config/app.json 里用户自定义的分类标记 id（doctor 不 import app，直接读配置）。"""
    cfg = root / "config" / "app.json"
    try:
        rows = json.loads(cfg.read_text(encoding="utf-8")).get("classification_marks") or []
    except Exception:
        return set()
    out: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            mark_id = str(row.get("id") or "").strip()
            if mark_id:
                out.add(mark_id)
    return out


def scan_docs(ws: Path, rep: Report, index: sqlite3.Connection | None,
              extra_marks: set[str] | None = None) -> dict:
    docs = list(iter_docs(ws))
    by_kind: dict[str, int] = {}
    id_mismatch: list[str] = []
    status_bad: list[str] = []
    mark_bad: list[str] = []
    mark_missing: list[str] = []
    date_missing: list[str] = []
    h1_bad: list[str] = []
    name_bad: list[str] = []
    field_unknown: list[str] = []
    for kind, path, meta, body in docs:
        by_kind[kind] = by_kind.get(kind, 0) + 1
        doc_id = str(meta.get("id") or path.stem)
        if not doc_id.startswith(f"{kind}-"):
            id_mismatch.append(f"{doc_id}（声明 {kind}）")
        status = str(meta.get("status") or "")
        allowed = C.kind_statuses(kind)
        if allowed and status not in allowed:
            status_bad.append(f"{doc_id}: status={status} 不在 {allowed}")
        marks = as_list(meta.get("kind_marks"))
        valid_marks = {str(m["id"]) for m in C.MARK_IDS} | set(extra_marks or ())
        for m in marks:
            if m not in valid_marks:
                mark_bad.append(f"{doc_id}: kind_marks 含 {m}")
        for req in C.required_marks(kind):
            if req not in marks:
                mark_missing.append(f"{doc_id}: 缺必需标记 {req}")
        if str(meta.get("variant_of") or "").strip():
            # 版本/快照条目：标题带「（v-…）」后缀、H1 是原名，
            # 不该走普通条目的命名/H1/字段校验（v261009.57）
            continue
        date_field = C.DATE_FIELDS.get(kind)
        if date_field and not str(meta.get(date_field) or "").strip():
            date_missing.append(f"{doc_id}: 缺 {date_field}")
        h1 = naming.first_h1(body)
        if h1 and h1 != str(meta.get("title") or "").strip():
            h1_bad.append(f"{doc_id}: title≠H1")
        issues = naming.validate_title(
            kind, str(meta.get("title") or ""), kind_marks=marks, projects=as_list(meta.get("projects")),
        )
        errs = [i for i in issues if i["level"] == "error"]
        if errs:
            name_bad.append(f"{doc_id}: {errs[0]['code']} {errs[0]['message'][:40]}")
        for key in meta:
            if key not in KNOWN_FIELDS:
                field_unknown.append(f"{doc_id}: {key}")

    # v261009.57 · 版本/快照条目**不进索引**（只在「版本」页可见）：
    # 磁盘计数要按 kind 扣掉它们，否则"磁盘 vs 索引"会误报漂移（实测 note/summary 各差 1）。
    _variant_files = [p for p in (ws / "Knowledge").rglob("*.md")
                      if p.is_file() and _looks_like_variant(p)]
    _variant_by_kind: dict[str, int] = {}
    for _p in _variant_files:
        for _k, _rel in C.KIND_DIRS.items():
            if _p.parent.name == Path(_rel).name:
                _variant_by_kind[_k] = _variant_by_kind.get(_k, 0) + 1
                break
    for _k, _n in _variant_by_kind.items():
        by_kind[_k] = max(0, int(by_kind.get(_k, 0)) - _n)

    rep.add("文档·版本条目", "info", len(_variant_files),
            f"版本/快照 {len(_variant_files)} 条（不计入索引，只在「版本」页可见）"
            + (f"：{'、'.join(f'{k} {v}' for k, v in sorted(_variant_by_kind.items()))}"
               if _variant_by_kind else ""))

    _disk_total = sum(int(v) for v in by_kind.values())
    rep.add("文档·磁盘数量", "info", _disk_total, f"按契约目录扫到 {_disk_total} 条（不含版本）：" + "、".join(f"{k} {v}" for k, v in sorted(by_kind.items())))
    rep.add("文档·id 前缀与 kind 不符", "warn", len(id_mismatch),
            "契约已明确「id 不承载类型语义」，故仅提示；修法见 REFACTOR_PLAN §5.3", id_mismatch)
    rep.add("文档·status 越界", "error", len(status_bad), "状态机在 core/contracts/kinds.py 声明", status_bad)
    rep.add("文档·kind_marks 越界", "error", len(mark_bad), "合法标记见契约 MARK_IDS + 设置页自定义标记", mark_bad)
    rep.add("文档·缺契约强制标记", "error", len(mark_missing), "如 experiment 固定带 ⚗", mark_missing)
    rep.add("文档·缺法定日期", "error", len(date_missing), "各类型日期字段见契约 DATE_FIELDS", date_missing)
    rep.add("文档·title 与首个 H1 不一致", "error", len(h1_bad), "改名须同步 H1（用 kb_rename_entry）", h1_bad)
    rep.add("文档·标题不合命名规范", "error", len(name_bad), "校验器 core/contracts/naming.py", name_bad)
    rep.add("文档·未声明字段", "warn", len(field_unknown), f"不在字段序也不在 {sorted(EXTRA_KNOWN_FIELDS)} 中的键", field_unknown)

    # 索引对照
    if index is None:
        rep.add("索引·可用性", "warn", 1, "找不到或打不开 System/Cache/index.sqlite（未建索引？）")
    else:
        try:
            rows = {k: c for k, c in index.execute("SELECT kind, COUNT(*) FROM documents GROUP BY kind")}
        except sqlite3.Error as exc:
            rep.add("索引·可用性", "warn", 1, f"查询失败：{exc}")
            rows = {}
        if rows:
            diff = {k: (by_kind.get(k, 0), rows.get(k, 0)) for k in set(by_kind) | set(rows)}
            bad = {k: v for k, v in diff.items() if v[0] != v[1]}
            rep.add("索引·与磁盘数量一致", "error" if bad else "info", len(bad),
                    f"不一致（磁盘, 索引）：{bad}" if bad else f"7 类逐一相等，共 {sum(rows.values())} 条")
        # 幽灵归属：document_projects 有 name 无 id
        try:
            ghost = index.execute(
                "SELECT doc_id, project_name FROM document_projects WHERE TRIM(COALESCE(project_id,''))=''"
            ).fetchall()
            rep.add("索引·项目归属幽灵行", "warn", len(ghost),
                    "同一项目在图谱上会裂成 name / id 两个节点（REFACTOR_PLAN P15）",
                    [f"{r[0]} → {r[1]}" for r in ghost])
        except sqlite3.Error:
            pass
        # 断链
        try:
            known = {r[0] for r in index.execute("SELECT id FROM documents")}
            titles = {str(r[0]).strip() for r in index.execute("SELECT title FROM documents")}
            broken = [t for (t,) in index.execute("SELECT DISTINCT token FROM document_links")
                      if str(t).strip() not in known and str(t).strip() not in titles]
            rep.add("索引·不可解析的关联链接", "warn", len(broken),
                    "既不是 doc_id 也不是现有标题（改名后未同步？）", broken)
        except sqlite3.Error:
            pass
        try:
            meta = dict(index.execute("SELECT key, value FROM meta"))
            rep.add("索引·meta", "info", 1,
                    f"schema_version={meta.get('schema_version')} last_sync={meta.get('last_sync')}")
        except sqlite3.Error:
            pass
        # 结构迁移状态（core/index/migrate）：磁盘版本高于代码是硬错误——旧代码写入会破坏新结构
        try:
            from .index import migrate as index_migrate

            try:
                index_migrate.guard_disk_version(index)
                guard_ok, guard_msg = True, ""
            except index_migrate.MigrationError as exc:
                guard_ok, guard_msg = False, str(exc)
            info = index_migrate.plan(index)
            rep.add("索引·结构迁移状态", "error" if not guard_ok else ("warn" if info["pending"] else "info"),
                    0 if guard_ok and not info["pending"] else 1,
                    guard_msg if not guard_ok else (
                        f"当前 v{info['current_version']}（{info['current_label']}）→ 目标 v{info['target_version']}；"
                        + ("待执行 " + ", ".join(s["id"] for s in info["pending"]) if info["pending"] else "已是最新")
                    ),
                    [f"{s['id']} {s['title']}" for s in info["pending"]])
        except Exception as exc:  # pragma: no cover - 迁移模块不可用时不应拖垮体检
            rep.add("索引·结构迁移状态", "info", 1, f"未检查（{exc}）")
    return by_kind


def check_workspace_hygiene(ws: Path, rep: Report) -> None:
    # 回收站目录 vs kind 列表 + 契约声明的非 kind 命名空间（如插件回收站 System/Trash/plugins/）
    trash = ws / "System" / "Trash"
    if trash.is_dir():
        dirs = sorted(p.name for p in trash.iterdir() if p.is_dir())
        allowed = {str(k).lower() for k in C.KINDS} | {str(x).lower() for x in C.TRASH_EXTRA}
        stale = [d for d in dirs if d.lower() not in allowed]
        rep.add("工作区·回收站目录漂移", "warn", len(stale),
                f"不在现役 kind 中的回收站子目录：{stale}（现有：{dirs}）" if stale else f"与 kind 列表一致：{dirs}")

    # 同步冲突残留
    conflicts = [p for p in ws.rglob("*sync-conflict*") if p.is_file()]
    size = sum(p.stat().st_size for p in conflicts)
    rep.add("工作区·同步冲突残留", "warn", len(conflicts),
            f"合计 {size / 1048576:.1f} MB（不进索引，需人工确认后清理）",
            [f"{p.relative_to(ws)} ({p.stat().st_size / 1048576:.1f} MB)" for p in conflicts])

    # Cache 体积 / WAL / 孤儿库
    cache = ws / "System" / "Cache"
    if cache.is_dir():
        files = {p.name: p.stat().st_size for p in cache.glob("*") if p.is_file()}
        main = files.get("index.sqlite", 0)
        wal = files.get("index.sqlite-wal", 0)
        # 空闲页与 WAL：实测曾有「文件 35.7 MB / 活数据 7.19 MB（80% 空闲页）+ WAL 21.4 MB」，
        # 真正的瘦身在维护（VACUUM + checkpoint），不在删列/删边——见 core/index/maintain.py
        free_ratio = 0.0
        live = 0
        try:
            from .index import maintain as index_maintain

            st = index_maintain.stats(cache / "index.sqlite")
            free_ratio = float(st.get("free_ratio") or 0.0)
            live = int(st.get("live_bytes") or 0)
        except Exception:
            pass
        bloated = free_ratio > 0.3 or (main and wal > main * 0.3)
        rep.add("索引·体积与空闲页", "warn" if bloated else "info", 1,
                f"文件 {main / 1048576:.1f} MB（活数据 {live / 1048576:.1f} MB、空闲页 "
                f"{100 * free_ratio:.0f}%）+ WAL {wal / 1048576:.1f} MB"
                + ("；建议 `python -m core.index.maintain --checkpoint --vacuum`" if bloated else ""))
        sqlites = [n for n in files if n.endswith(".sqlite")]
        orphans = [n for n in sqlites if n != "index.sqlite"]
        rep.add("索引·派生库归属", "info", len(orphans),
                "index.sqlite 之外的派生库（应归属某个插件，内核不依赖）", orphans)
        # 冲突副本有两种命名：Syncthing 的 `*sync-conflict*` 与人工/工具留下的 `*冲突*`
        conflict_db = [n for n in files if "sync-conflict" in n or "冲突" in n]
        if conflict_db:
            rep.add("索引·冲突副本", "warn", len(conflict_db),
                    "冲突产生的库副本（实测曾有 6.8 MB 副本损坏到无法打开，属可删的派生数据）",
                    [f"{n} ({files[n] / 1048576:.1f} MB)" for n in conflict_db])


def check_schema_versions(root: Path, ws: Path, rep: Report) -> None:
    """版本单一入口：System/schema.json 的 index_schema_version 应与代码一致（REFACTOR_PLAN §5.5.1）。

    代码侧版本取自 `core.index.migrate.TARGET_VERSION`——**不 import app**：
    `core/` 必须能脱离 app 独立加载（`tools/plugin_check.py` 会静态拦这条）。
    `workspace_schema_version` 的归属仍在 `app/perf_index_db`（工作区骨架版本），
    这里只把它如实展示出来，不参与判定。
    """
    schema = ws / "System" / "schema.json"
    disk = {}
    if schema.is_file():
        try:
            disk = json.loads(schema.read_text(encoding="utf-8"))
        except Exception:
            pass
    code_version: int | None = None
    try:
        from .index import migrate as index_migrate

        code_version = index_migrate.TARGET_VERSION
    except Exception:
        pass
    if disk and code_version is not None:
        disk_version = disk.get("index_schema_version")
        mismatched = disk_version != code_version
        rep.add("版本·schema.json 与代码", "error" if mismatched else "info", 1 if mismatched else 0,
                f"index_schema_version 不一致（磁盘 {disk_version} / 代码 {code_version}）"
                if mismatched else
                f"index_schema_version 一致（{code_version}）；workspace_schema_version={disk.get('workspace_schema_version')}")
    else:
        rep.add("版本·schema.json", "info", 1,
                f"磁盘={disk or '缺失'}；代码={code_version if code_version is not None else '未取到'}")


# ---------------------------------------------------------------- 入口

def run(workspace: Path, root: Path) -> Report:
    rep = Report()
    rep.add("环境·工作区", "info" if workspace.is_dir() else "error",
            0 if workspace.is_dir() else 1, str(workspace))
    check_contract_selfconsistency(rep)
    index = load_index(workspace)
    scan_docs(workspace, rep, index, configured_marks(root))
    if index is not None:
        index.close()
    check_workspace_hygiene(workspace, rep)
    check_schema_versions(root, workspace, rep)
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="知识库只读体检（core.doctor）")
    ap.add_argument("--workspace", help="Workspace 路径（默认按 config/app.json）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict", action="store_true", help="有 error 级发现时非零退出")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    ws = resolve_workspace(args.workspace, root)
    rep = run(ws, root)

    if args.json:
        print(json.dumps({"workspace": str(ws), "items": rep.items,
                          "errors": rep.errors(), "warnings": rep.warns()},
                         ensure_ascii=False, indent=2))
    else:
        icon = {"error": "[E]", "warn": "[W]", "info": "[i]"}
        print(f"core.doctor · 工作区 {ws}\n")
        for item in rep.items:
            # 有发现才显示级别图标；零发现一律显示 ok，避免「[E] 0 条」这种自相矛盾的行
            mark = icon.get(item["level"], "[?]") if item["count"] else " ok"
            print(f"  {mark} {item['check']:<26} {item['detail']}")
            for s in item["samples"]:
                print(f"       - {s}")
        print(f"\n合计：error 级检查项 {rep.errors()} 个、warn 级 {rep.warns()} 个")

    return 1 if (args.strict and rep.errors()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
