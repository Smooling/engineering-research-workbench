"""备份与快照 · 插件后端 v1.0.0

把**知识库与配置**打成一个带时间戳的 zip 快照，按间隔自动执行、按份数清理，可下载。

| 设计点 | 选择 | 为什么 |
| --- | --- | --- |
| 归档格式 | 一个 `.zip`（内含 `manifest.json` + 原相对路径文件） | 单文件好搬走、好校验、好删；`manifest.json` 记录范围/条数/字节数/内核版本，恢复前能先看清内容 |
| 触发方式 | 内核调度（`ctx.jobs.add("auto", …)`，v261009.24 起）+ 面板「立即备份」+ Agent 工具 | 「定时」由内核负责调度与状态，插件**不起自己的线程**（否则热重载会留下幽灵线程） |
| 幂等 | 回调先看 `state.json` 里的上次时间：距上次不足间隔就跳过 | 任务在插件重载时会重新注册，没有这道闸门就会「一重启就备一次」 |
| 范围 | 默认只收**知识 + 配置 + 状态**；附件（PDF/图片）、项目大文件、派生索引**默认不收** | 知识库本体只有几 MB，天天全量也无所谓；PDF 有几百 MB，默认收会让快照失去意义 |
| 清理 | 只删**本插件生成的** `snapshot-*.zip`，按份数保留 | 目标目录可能是用户自己的文件夹，绝不能碰别的文件 |
| 恢复 | **不做自动恢复**，只给「查看内容 + 下载」 | 覆盖用户数据是破坏性动作，必须由人看过内容再决定；自动恢复写错一次就是事故 |

目标目录默认是自己的命名空间 `Workspace/System/Plugins/backup-snapshot/snapshots/`；
可配置成**外部目录**（如 `D:\\Backups`）——备份与数据放在同一处只防手滑，防不了磁盘故障，
所以面板会明确提示这一点。
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import core_api

SNAPSHOT_GLOB = "snapshot-*.zip"
DEFAULT_CONFIG = {
    "interval_hours": 24,        # 自动备份间隔（小时）
    "keep": 7,                   # 保留份数（只删本插件生成的快照）
    "dest_dir": "",              # 空 = 插件自己的命名空间；可填绝对路径做外置备份
    "include_projects_text": False,   # 收录 Projects/ 下的文本类文件
    "include_attachments": False,     # 收录 PDF / 图片等附件
    "include_index": False,           # 收录派生索引（可重建，默认不收）
    "auto_enabled": True,             # 关掉自动，保留手动
}
MAX_KEEP = 60

#: 默认收录：知识条目 + 系统状态 + 三类配置（都是小体积、丢了最疼的东西）
CORE_DIRS = ("Workspace/Knowledge",)
CORE_FILES = ("Workspace/System/todos.json", "Workspace/System/projects.json",
              "Workspace/System/plugins.json", "Workspace/System/activity.jsonl",
              "config/app.json", "config/secrets.json")
CONFIG_GLOB = "config/plugins/*.json"
#: 可选：项目目录里的「文本类」文件
TEXT_SUFFIXES = {".md", ".txt", ".csv", ".json", ".bib", ".tex", ".yaml", ".yml", ".tif.txt"}
#: 可选：附件类
ATTACH_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".docx", ".xlsx", ".pptx", ".zip"}
#: **重文件**后缀：即使落在默认目录里也不收（除非打开「收录附件与大文件」）。
#: 实测 `Workspace/Knowledge/` 下就躺着 295 MB 的 PDF（Attachments/ + Literature/PDF/），
#: 不挡住它们，所谓"小体积快照"就是假的。
HEAVY_SUFFIXES = ATTACH_SUFFIXES | {".tif", ".tiff", ".bmp", ".mp4", ".avi", ".mov",
                                    ".h5", ".npy", ".npz", ".pth", ".pt", ".onnx", ".7z", ".rar"}
#: 可重建 / 生成物：默认不收（分别在打开「索引」「附件」时才考虑）
SKIP_REL_PREFIXES = ("Workspace/System/Cache", "Workspace/Knowledge/Exports")
#: 单个文件上限（防手滑把 2 GB 的东西塞进快照）
MAX_FILE_BYTES = 256 * 1024 * 1024

#: **串行化**：自动任务与手动请求跑在不同线程里，同一秒发起就会算出同一个文件名、
#: 争同一个 `.part` 临时文件（实测出现在并发时 500）。一次只允许一份快照在跑。
_CREATE_LOCK = threading.Lock()


def _now() -> datetime:
    return datetime.now()


def _stamp(dt: datetime | None = None) -> str:
    return (dt or _now()).strftime("%Y%m%d-%H%M%S")


def _project_root() -> Path:
    """数据根（= 工作台安装目录）：`config/` 与 `Workspace/` 都在它下面。"""
    return core_api.data_root()


def register(ctx):
    ctx.storage.ensure()
    state_file = ctx.storage.system / "state.json"
    default_dest = ctx.storage.system / "snapshots"

    # ---------------------------------------------------------------- 配置 / 状态

    def config() -> dict:
        cfg = dict(DEFAULT_CONFIG)
        saved = ctx.config_read({})
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in DEFAULT_CONFIG})
        cfg["interval_hours"] = max(0.5, float(cfg["interval_hours"] or 24))
        cfg["keep"] = max(1, min(MAX_KEEP, int(cfg["keep"] or 7)))
        cfg["dest_dir"] = str(cfg.get("dest_dir") or "").strip()
        return cfg

    def read_state() -> dict:
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def write_state(data: dict) -> None:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(state_file)

    def dest() -> Path:
        raw = config()["dest_dir"]
        path = Path(raw).expanduser() if raw else default_dest
        if not path.is_absolute():
            path = _project_root() / path
        return path

    # ---------------------------------------------------------------- 收集与打包

    def _collect(cfg: dict) -> tuple[list[tuple[Path, Path]], list[str], dict[str, int]]:
        """返回 ([(绝对路径, 归档内相对路径)], 跳过的说明, 按类别计数的跳过统计)。"""
        root = _project_root()
        picked: list[tuple[Path, Path]] = []
        skipped: list[str] = []
        hints: dict[str, int] = {}

        def hint(key: str) -> None:
            hints[key] = hints.get(key, 0) + 1

        def add(path: Path, rel: Path, *, allow_heavy: bool = False) -> None:
            if not path.is_file():
                return
            posix = rel.as_posix()
            if any(posix.startswith(prefix) for prefix in SKIP_REL_PREFIXES):
                hint("可重建/生成物（Cache、Exports）")
                return
            if not allow_heavy and path.suffix.lower() in HEAVY_SUFFIXES:
                hint("附件与大文件")
                return
            try:
                size = path.stat().st_size
            except OSError:
                return
            if size > MAX_FILE_BYTES:
                skipped.append(f"{posix}（{size / 1048576:.0f} MB，超过单文件上限）")
                hint("超过单文件上限")
                return
            picked.append((path, rel))

        for folder in CORE_DIRS:
            base = root / folder
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    add(path, path.relative_to(root))
        for rel in CORE_FILES:
            add(root / rel, Path(rel))
        for path in sorted(root.glob(CONFIG_GLOB)):
            add(path, path.relative_to(root))

        if cfg["include_projects_text"]:
            base = root / "Workspace" / "Projects"
            if base.is_dir():
                for path in sorted(base.rglob("*")):
                    if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                        add(path, path.relative_to(root))
        if cfg["include_attachments"]:
            for folder in ("Workspace/Knowledge/Attachments", "Workspace/Knowledge/Literature"):
                base = root / folder
                if not base.is_dir():
                    continue
                for path in sorted(base.rglob("*")):
                    if path.is_file() and path.suffix.lower() in ATTACH_SUFFIXES:
                        add(path, path.relative_to(root), allow_heavy=True)
        if cfg["include_index"]:
            add(root / "Workspace" / "System" / "Cache" / "index.sqlite",
                Path("Workspace/System/Cache/index.sqlite"), allow_heavy=True)
        return picked, skipped, hints

    def create_snapshot(reason: str = "manual") -> dict:
        if not _CREATE_LOCK.acquire(blocking=False):
            return {"ok": False, "error": "已有一次备份正在进行，请稍后再试（同一时刻只允许一份快照）"}
        try:
            return _create_snapshot_locked(reason)
        finally:
            _CREATE_LOCK.release()

    def _create_snapshot_locked(reason: str) -> dict:
        cfg = config()
        target_dir = dest()
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"目标目录不可写：{target_dir}（{exc}）"}
        files, skipped, hints = _collect(cfg)
        if not files:
            return {"ok": False, "error": "没有可收录的文件（检查 Workspace 是否存在）"}
        stamp = _stamp()
        name = f"snapshot-{stamp}.zip"
        suffix = 2
        while (target_dir / name).exists() and suffix < 50:   # 同一秒内的第二份：加序号，不覆盖
            name = f"snapshot-{stamp}-{suffix}.zip"
            suffix += 1
        # 临时名带随机串：即使并发（理论上已被锁挡住）也不会互相踩同一个 .part
        tmp = target_dir / f".{name}.{uuid.uuid4().hex[:8]}.part"
        total = 0
        manifest = {
            "format": 1, "created": _now().isoformat(timespec="seconds"), "reason": reason,
            "kernel_version": core_api.kernel_version(),
            "plugin": "backup-snapshot", "options": cfg, "skipped": skipped[:40],
            "skipped_summary": hints,
        }
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                for path, rel in files:
                    z.write(path, rel.as_posix())
                    total += path.stat().st_size
                manifest.update({"files": len(files), "raw_bytes": total})
                z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            tmp.replace(target_dir / name)          # 原子收尾：不会留下半个快照
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            return {"ok": False, "error": f"写入快照失败：{exc}"}
        size = (target_dir / name).stat().st_size
        removed = _prune(cfg, target_dir)
        write_state({"last_at": manifest["created"], "last_name": name, "last_bytes": size,
                     "last_files": len(files), "last_reason": reason})
        ctx.log(f"快照完成 {name}（{len(files)} 文件 / {total / 1048576:.1f} MB → {size / 1048576:.1f} MB）"
                + (f"；清理旧快照 {removed}" if removed else ""))
        return {"ok": True, "file": name, "dir": str(target_dir), "files": len(files),
                "raw_bytes": total, "bytes": size, "skipped": skipped, "removed": removed,
                "skipped_summary": hints, "manifest": manifest}

    def _prune(cfg: dict, target_dir: Path) -> list[str]:
        """只清理**本插件生成的** `snapshot-*.zip`，按份数保留最新的 N 个。

        按 mtime 排序（不是文件名）：同一秒内可能有多份（带 `-2` 序号），文件名排序会把它们排反。
        """
        def mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        snaps = sorted(target_dir.glob(SNAPSHOT_GLOB), key=lambda p: (mtime(p), p.name))
        removed: list[str] = []
        for path in snaps[:max(0, len(snaps) - cfg["keep"])]:
            try:
                path.unlink()
                removed.append(path.name)
            except OSError:
                continue
        return removed

    def list_snapshots() -> dict:
        target_dir = dest()
        rows = []
        for path in sorted(target_dir.glob(SNAPSHOT_GLOB), reverse=True):
            try:
                stat = path.stat()
            except OSError:
                continue
            rows.append({"name": path.name, "bytes": stat.st_size,
                         "at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")})
        total = sum(r["bytes"] for r in rows)
        return {"dir": str(target_dir), "is_default_dir": not config()["dest_dir"],
                "items": rows, "count": len(rows), "total_bytes": total,
                "state": read_state(), "config": config()}

    def _safe_snapshot_path(name: str) -> Path | None:
        raw = str(name or "").replace("\\", "/").strip().lstrip("/")
        if "/" in raw or ".." in raw or not re.match(r"^snapshot-[\w.\-]+\.zip$", raw):
            return None
        target = (dest() / raw).resolve()
        return target if target.parent == dest().resolve() else None

    # ---------------------------------------------------------------- 自动任务

    def auto_job() -> None:
        cfg = config()
        if not cfg["auto_enabled"]:
            return
        last = str(read_state().get("last_at") or "")
        if last:
            try:
                elapsed = _now() - datetime.fromisoformat(last)
            except ValueError:
                elapsed = timedelta(days=999)
            if elapsed < timedelta(hours=cfg["interval_hours"]) * 0.9:
                return                      # 距上次不足间隔：跳过（重载后重新注册也不会连点）
        result = create_snapshot("auto")
        if not result.get("ok"):
            ctx.log(f"自动快照失败：{result.get('error')}")

    ctx.jobs.add("auto", auto_job, every_minutes=30, run_on_start=True)

    # ---------------------------------------------------------------- 路由

    def route_status(request):
        return {"ok": True, "snapshots": list_snapshots(), "job": (ctx.jobs.list() or [{}])[0],
                "capabilities": {"max_keep": MAX_KEEP,
                                 "max_file_mb": MAX_FILE_BYTES // 1048576,
                                 "dest_default": str(default_dest),
                                 "notes": ["快照只收录知识库本体与配置（几 MB）；附件与派生索引默认不收",
                                           "自动备份由内核调度（每 30 分钟检查一次，到间隔才真正执行）",
                                           "恢复请先「查看内容」确认，再手动解压覆盖——本插件不做自动恢复"]}}

    def route_config_get(request):
        return config()

    def route_config_post(request):
        body = request.get("body") or {}
        cfg = config()
        for key in ("interval_hours", "keep", "dest_dir", "include_projects_text",
                    "include_attachments", "include_index", "auto_enabled"):
            if key in body:
                cfg[key] = body[key]
        # 规范化写回（数值夹取在 config() 里做）
        cfg = {**DEFAULT_CONFIG, **cfg}
        ctx.config_write(cfg)
        return config()

    def route_snapshot(request):
        return create_snapshot("manual")

    def route_delete(request):
        name = str(((request.get("body") or {}).get("name")) or "")
        path = _safe_snapshot_path(name)
        if path is None or not path.is_file():
            return {"ok": False, "error": "只能删除本插件生成的 snapshot-*.zip"}
        try:
            path.unlink()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        ctx.log(f"已删除快照 {name}")
        return {"ok": True, "removed": name, "snapshots": list_snapshots()}

    def route_inspect(request):
        """看快照里到底装了什么（恢复前的确认步骤；不做自动恢复）。"""
        name = str(((request.get("body") or {}).get("name")) or "")
        path = _safe_snapshot_path(name)
        if path is None or not path.is_file():
            return {"ok": False, "error": "找不到该快照"}
        try:
            with zipfile.ZipFile(path) as z:
                manifest = {}
                if "manifest.json" in z.namelist():
                    manifest = json.loads(z.read("manifest.json").decode("utf-8"))
                names = [n for n in z.namelist() if n != "manifest.json"]
                by_dir: dict[str, int] = {}
                for n in names:
                    key = "/".join(n.split("/")[:2])
                    by_dir[key] = by_dir.get(key, 0) + 1
            return {"ok": True, "manifest": manifest, "entries": len(names),
                    "by_dir": dict(sorted(by_dir.items(), key=lambda kv: -kv[1])[:12]),
                    "sample": names[:40]}
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            return {"ok": False, "error": f"快照损坏或无法读取：{exc}"}

    def route_download(request):
        name = str((request["query"].get("name") or [""])[0])
        path = _safe_snapshot_path(name)
        if path is None or not path.is_file():
            return ctx.raw("<h1>找不到该快照</h1>", content_type="text/html; charset=utf-8", status=404)
        return ctx.raw(path.read_bytes(), content_type="application/zip", filename=path.name)

    ctx.routes.get("status", route_status)
    ctx.routes.get("config", route_config_get)
    ctx.routes.post("config", route_config_post)
    ctx.routes.post("snapshot", route_snapshot)
    ctx.routes.post("delete", route_delete)
    ctx.routes.post("inspect", route_inspect)
    ctx.routes.get("download", route_download)

    # ---------------------------------------------------------------- Agent 工具

    def tool_snapshot(args, call_ctx=None):
        result = create_snapshot("agent")
        result.pop("manifest", None)
        return result

    def tool_list(args, call_ctx=None):
        data = list_snapshots()
        return {"dir": data["dir"], "count": data["count"], "total_bytes": data["total_bytes"],
                "state": data["state"], "items": data["items"][:20], "config": data["config"]}

    ctx.mcp.tool("snapshot_now", {
        "description": "立刻给知识库与配置打一个 zip 快照（只写插件自己的快照目录，不改任何知识条目）",
        "parameters": {"type": "object", "properties": {}},
    }, tool_snapshot)

    ctx.mcp.tool("list_snapshots", {
        "description": "列出已有快照（名称/大小/时间）、目标目录与上次备份时间",
        "parameters": {"type": "object", "properties": {}},
    }, tool_list)

    ctx.log(f"备份插件已注册（快照目录 {dest()}；自动任务每 30 分钟检查一次，间隔 "
            f"{config()['interval_hours']} 小时）")
