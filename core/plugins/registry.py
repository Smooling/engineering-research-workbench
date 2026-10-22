"""插件发现与状态判定（PLUGIN_SPEC §1 两个来源、§4 依赖、§7 校验、§5 安装状态）。

**本模块只做发现 / 校验 / 依赖解析，不加载插件代码。** 执行与注册（`register(ctx)`、
路由与工具的挂载、隔离不变量 I3/I4/I8）要等第一个真插件落地时一并实现——
在那之前，把状态诚实地报成 `available`（已校验、可加载）而不是 `enabled`。

状态模型（对应 §7「失败行为统一为 rejected/blocked + 原因 + 修复建议」）：

| 状态 | 含义 |
| --- | --- |
| `rejected` | manifest 校验不过（错误清单给出原因与修法） |
| `blocked` | manifest 合法，但前提插件缺失/被拒/成环 |
| `conflict` | 同一 id 在库里出现多个版本（§4.2.2：不猜，直接报冲突） |
| `available` | 校验通过、依赖满足，等待加载器（首个插件落地后进入 `enabled`） |

两个来源：`ASSET_ROOT/plugins`（随包，只读）与 `DATA_ROOT/plugins`（用户库），**同名 ASSET 优先**。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import manifest as M
from . import unpack as U

#: 状态含义（供 CLI / 文档复用）
STATE_LABELS = {
    "rejected": "校验不通过",
    "blocked": "前提依赖不满足",
    "conflict": "同 id 多版本冲突",
    "available": "已校验、可加载",
}


@dataclass
class PluginCandidate:
    id: str
    dir: Path
    source: str  # bundled | user
    manifest: dict | None = None
    issues: list[dict] = field(default_factory=list)
    state: str = "available"
    reason: str = ""
    fix: str = ""
    version: str = ""
    shadowed: str = ""  # 被另一个来源的同名插件遮蔽时记录来源

    def as_dict(self) -> dict:
        return {
            "id": self.id, "version": self.version, "source": self.source,
            "dir": str(self.dir), "state": self.state,
            "state_label": STATE_LABELS.get(self.state, self.state),
            "reason": self.reason, "fix": self.fix,
            "shadowed": self.shadowed,
            "issues": self.issues,
            "nav": [n.get("id") for n in (self.manifest or {}).get("nav", []) if isinstance(n, dict)],
            "routes": [f"{r.get('method','GET')} {r.get('path','')}" for r in (self.manifest or {}).get("routes", []) if isinstance(r, dict)],
            "mcp_tools": list((self.manifest or {}).get("mcp_tools") or []),
            "permissions": list((self.manifest or {}).get("permissions") or []),
            "requires": [d.get("id") if isinstance(d, dict) else d
                         for d in ((self.manifest or {}).get("requires") or {}).get("plugins", [])],
            # 演示预览（可选，插件自己声明；内核只呈现）：CLI 里一并显示，便于作者核对
            "preview": ({"summary": str(pv.get("summary") or ""),
                         "features": [str(f) for f in (pv.get("features") or []) if isinstance(f, str)],
                         "screens": [str(s) for s in (pv.get("screens") or []) if isinstance(s, str)]}
                        if isinstance(pv := (self.manifest or {}).get("preview"), dict) else {}),
        }


def default_roots(repo_root: Path | None = None, *, asset_root: Path | None = None) -> list[tuple[str, Path]]:
    """(source, dir) 列表，ASSET 在前（同名 ASSET 优先）。

    这里镜像 `app/paths.py` 的 frozen 判定（3 行），而不是 import app：
    `core/` 必须保持不依赖 `app`（`tools/plugin_check.py` 会静态检查）。
    """
    root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    if asset_root is not None:
        data_root = root
        asset_root = Path(asset_root).resolve()
    elif getattr(sys, "frozen", False):  # 打包态：随包资源在解压目录，数据在 exe 同级
        data_root = Path(repo_root).resolve() if repo_root else Path(sys.executable).resolve().parent
        asset_root = Path(getattr(sys, "_MEIPASS", data_root))
    else:
        data_root = asset_root = root
    return [("bundled", asset_root / "plugins"), ("user", data_root / "plugins")]


def discover(roots: list[tuple[str, Path]] | None = None) -> tuple[dict[str, PluginCandidate], list[str]]:
    """扫描各根目录下的 `plugins/<id>/`，返回 (候选表, 提示列表)。同名 ASSET 优先。

    **本函数只读，永不写盘**：`tools/plugin_check.py` 与每个插件请求路径（`/api/plugins/*`
    转发、插件静态资源）都在调用它——审计工具与热路径不该顺带安装东西。安装是另一个
    显式动作，见 `install_packages`。
    """
    notes: list[str] = []
    found: dict[str, PluginCandidate] = {}
    seen_roots: set[Path] = set()
    for source, root in (roots or default_roots()):
        # 开发态 packaged 与 user 指向同一个目录（仓库根），同一个根不要扫两遍，
        # 否则会给自己报一个假的「同名插件冲突」。
        real = Path(root).resolve() if Path(root).exists() else Path(root)
        if real in seen_roots:
            continue
        seen_roots.add(real)
        if not Path(root).is_dir():
            continue
        for entry in sorted(Path(root).iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            data, issues = M.load_manifest(entry)
            pid = str((data or {}).get("id") or entry.name).strip()
            candidate = PluginCandidate(
                id=pid, dir=entry, source=source, manifest=data,
                issues=list(issues), version=str((data or {}).get("version") or ""),
            )
            if pid in found:
                keep, drop = (candidate, found[pid]) if source == "bundled" else (found[pid], candidate)
                notes.append(
                    f"同名插件 `{pid}` 同时存在于 {drop.source}({drop.dir.name}) 与 "
                    f"{keep.source}({keep.dir.name})：按 §1 规则 {keep.source} 优先"
                )
                drop.state = "conflict"
                drop.reason = f"同一 id 出现于两个来源，{keep.source} 已生效"
                found[pid] = keep
                continue
            found[pid] = candidate
    return found, notes


def _validate_all(candidates: dict[str, PluginCandidate], core_version: str) -> None:
    for cand in candidates.values():
        if cand.state == "conflict":
            continue
        issues = list(cand.issues) + M.validate(cand.manifest, plugin_dir=cand.dir, core_version=core_version)
        cand.issues = issues
        errors = M.errors(issues)
        if errors:
            cand.state = "rejected"
            cand.reason = M.summarize(issues)
            cand.fix = errors[0].get("fix", "")


def _blocked_within_cycles(candidates: dict[str, PluginCandidate]) -> tuple[list[str], list[str]]:
    """在合法候选之间做依赖 DAG：返回 (加载顺序, 成环的 id 列表)。§4.2.1 检测到环 → 整环拒载。"""
    nodes = {pid: c for pid, c in candidates.items() if c.state in ("available", "blocked")}
    deps: dict[str, list[str]] = {}
    for pid, cand in nodes.items():
        requires = ((cand.manifest or {}).get("requires") or {}).get("plugins") or []
        deps[pid] = [str(d.get("id") if isinstance(d, dict) else d) for d in requires]

    order: list[str] = []
    state: dict[str, int] = {}  # 0=未访问 1=在栈上 2=完成
    cycle: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            cycle.update(stack[stack.index(node):] if node in stack else [node])
            return
        state[node] = 1
        stack.append(node)
        for dep in deps.get(node, []):
            if dep in nodes:
                visit(dep, stack)
        stack.pop()
        state[node] = 2
        order.append(node)

    for pid in sorted(nodes):
        visit(pid, [])
    return order, sorted(cycle)


def resolve(candidates: dict[str, PluginCandidate], core_version: str = "") -> dict:
    """校验 + 依赖解析，就地更新每个候选的状态。返回汇总（含加载顺序与提示）。"""
    _validate_all(candidates, core_version)
    order, cycle = _blocked_within_cycles(candidates)

    for cand in candidates.values():
        if cand.state != "available":
            continue
        requires = ((cand.manifest or {}).get("requires") or {}).get("plugins") or []
        missing: list[str] = []
        for dep in requires:
            dep_id = str(dep.get("id") if isinstance(dep, dict) else dep)
            target = candidates.get(dep_id)
            if target is None:
                missing.append(f"{dep_id}（未安装）")
            elif target.state == "rejected":
                missing.append(f"{dep_id}（被拒载：{target.reason[:40]}）")
            elif target.state in ("blocked", "conflict"):
                missing.append(f"{dep_id}（{STATE_LABELS.get(target.state, target.state)}）")
        if cand.id in cycle:
            cand.state = "blocked"
            cand.reason = f"依赖成环：{' → '.join(cycle)}"
            cand.fix = "去掉环上的一条依赖（§4.2.1：检测到环整环拒载，不做部分加载）"
        elif missing:
            cand.state = "blocked"
            cand.reason = "缺少前提插件：" + "、".join(missing)
            cand.fix = "先安装并启用上述前提插件（§4.3：前提插件被禁用时，依赖它的插件一起停用）"

    # 只有可用节点参与加载顺序
    load_order = [pid for pid in order if candidates[pid].state == "available"]
    return {"load_order": load_order, "cycle": cycle}


def effective_enabled(candidate: PluginCandidate, install: dict) -> bool:
    """「开不开」的判定（§1：目录决定在不在，`System/plugins.json` 决定开不开）。

    - 有安装记录且写了 `enabled` → 用它；
    - 没有记录 → 用 manifest 的 `default_enabled`（随包附属插件默认开，可选插件默认关）。
    """
    record = (install.get("plugins") or {}).get(candidate.id)
    if isinstance(record, dict) and "enabled" in record:
        return bool(record.get("enabled"))
    return bool((candidate.manifest or {}).get("default_enabled", False))


def read_install_state(workspace: Path) -> dict:
    """读 `System/plugins.json`（§1：目录决定「在不在」，它决定「开不开」）。"""
    path = Path(workspace) / "System" / "plugins.json"
    if not path.is_file():
        return {"schema_version": 1, "plugins": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"schema_version": 1, "plugins": {}}
        data.setdefault("schema_version", 1)
        data.setdefault("plugins", {})
        return data
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "plugins": {}}


def write_install_state(workspace: Path, plugin_id: str, enabled: bool) -> dict:
    """把某个插件的启停意图写进 `System/plugins.json`（原子写，保留其他插件与字段）。

    **只改「开不开」，不删任何文件**（§1）——停用不等于卸载：插件目录原样保留，
    数据与配置也不动，重新启用即回到原状。
    """
    path = Path(workspace) / "System" / "plugins.json"
    state = read_install_state(workspace)
    records = state.setdefault("plugins", {})
    record = records.get(plugin_id)
    if not isinstance(record, dict):
        record = {}
    record["enabled"] = bool(enabled)
    record["updated"] = datetime.now().isoformat(timespec="seconds")
    records[plugin_id] = record
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return state


def install_packages(
    roots: list[tuple[str, Path]] | None = None,
    *,
    workspace: Path | None = None,
) -> list[U.UnpackOutcome]:
    """**安装动作**：把各扫描根下的 `<id>-<version>.zip` 解包成 `plugins/<id>/`（PLUGIN_SPEC §2）。

    与 `discover` 严格分开：发现的调用方（审计闸门、每个插件请求路径）不可能因为调了
    `discover` 而写盘；安装必须显式调这个函数。当前三个调用点都是用户可见的安装时机：
    服务启动（`loader.load`）、打开设置页插件页（`server.build_plugin_payload`）、
    CLI `python -m core.plugins list --install`。同一根只会扫一次（与 discover 同样的去重）。
    """
    seen: set[Path] = set()
    out: list[U.UnpackOutcome] = []
    for _source, root in (roots or default_roots()):
        real = Path(root).resolve() if Path(root).exists() else Path(root)
        if real in seen:
            continue
        seen.add(real)
        out.extend(U.unpack_all(root, workspace=workspace))
    return out


def report(
    *,
    roots: list[tuple[str, Path]] | None = None,
    workspace: Path | None = None,
    core_version: str = "",
) -> dict:
    """一次完整盘点：候选状态 + 加载顺序 + 安装意图 + 提示。**只读**（安装见 `install_packages`）。"""
    candidates, notes = discover(roots)
    summary = resolve(candidates, core_version)
    install = read_install_state(workspace) if workspace else {"plugins": {}}
    # §1 的诚实补一句：plugins.json 里可能留着「插件目录早已删掉」的记录（装卸试过、手删目录…）。
    # 不报出来就会出现「同名插件一装上就自动是启用状态」这种看不见的继承。
    records = set((install.get("plugins") or {}).keys())
    orphans = sorted(records - set(candidates))
    if orphans:
        notes.append(f"System/plugins.json 里有 {len(orphans)} 条记录对应的插件已不存在（可删可留，"
                     f"不影响运行）：{orphans}")
    rows = []
    for pid in sorted(candidates):
        row = candidates[pid].as_dict()
        record = (install.get("plugins") or {}).get(pid) or {}
        # 目录存在 + plugins.json 记 enabled=true 才是「意图启用」；真正加载要等执行层（见模块头）
        row["enabled_intent"] = bool(record.get("enabled"))
        row["recorded_version"] = str(record.get("version") or "")
        rows.append(row)
    return {
        "roots": [{"source": s, "dir": str(d), "exists": d.is_dir()} for s, d in (roots or default_roots())],
        "plugins": rows,
        "load_order": summary["load_order"],
        "cycle": summary["cycle"],
        "notes": notes,
        "available": sum(1 for r in rows if r["state"] == "available"),
        "rejected": sum(1 for r in rows if r["state"] == "rejected"),
        "blocked": sum(1 for r in rows if r["state"] == "blocked"),
        "conflict": sum(1 for r in rows if r["state"] == "conflict"),
    }
