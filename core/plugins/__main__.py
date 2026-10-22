"""插件 CLI —— 与设置页同一套逻辑，便于排障（PLUGIN_SPEC §5）。

    python -m core.plugins list                 # 已发现 / 可用 / blocked / 冲突
    python -m core.plugins check <id>           # 单个插件的校验 + 依赖 + 权限报告（不落盘）
    python -m core.plugins verify               # 全库盘点（孤儿派生库 / 缺失依赖 / 版本冲突）

    --plugins-root <dir>[:source]  追加/替换扫描根（默认：随包库 → 用户库；测试用）
    --json                         机器可读

退出码：0 正常；1 = 存在 `rejected`/`blocked`/`conflict`（便于当闸门用）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import manifest as M
from . import registry as R

ROOT = Path(__file__).resolve().parents[2]


def _core_version() -> str:
    try:
        return M.read_core_version(ROOT)
    except OSError:
        return ""


def _workspace(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    cfg = ROOT / "config" / "app.json"
    raw = "Workspace"
    if cfg.is_file():
        try:
            raw = str(json.loads(cfg.read_text(encoding="utf-8")).get("workspace") or "Workspace")
        except Exception:
            pass
    p = Path(raw)
    return p if p.is_absolute() else (ROOT / p).resolve()


def _roots(arg: list[str] | None) -> list[tuple[str, Path]]:
    if not arg:
        return R.default_roots(ROOT)
    out: list[tuple[str, Path]] = []
    for i, item in enumerate(arg):
        if ":" in item and not item[1:3] == ":\\":  # 允许 "dir:source"，但别把盘符当分隔符
            path, source = item.rsplit(":", 1)
        else:
            path, source = item, ("bundled" if i == 0 else "user")
        out.append((source, Path(path).resolve()))
    return out


def _icon(state: str) -> str:
    return {"available": "ok ", "blocked": "BLK", "rejected": "REJ", "conflict": "CFL"}.get(state, "?  ")


def cmd_list(report: dict) -> int:
    rows = report["plugins"]
    for r in report["roots"]:
        print(f"  扫描根 {r['source']:8} {r['dir']}{'' if r['exists'] else '（不存在）'}")
    if not rows:
        print("  未发现任何插件（内核零插件可跑是设计目标，不是故障）")
    for row in rows:
        line = f"  [{_icon(row['state'])}] {row['id']:<20} v{row['version'] or '?':<10} {row['source']:<8}"
        if row["reason"]:
            line += f" {row['reason']}"
        print(line)
        if row["fix"]:
            print(f"        修复：{row['fix']}")
    if report["load_order"]:
        print(f"  加载顺序（拓扑）：{' → '.join(report['load_order'])}")
    for note in report["notes"]:
        print(f"  提示：{note}")
    print(f"  合计：可用 {report['available']} · blocked {report['blocked']} · "
          f"rejected {report['rejected']} · 冲突 {report['conflict']}")
    return 1 if (report["rejected"] or report["blocked"] or report["conflict"]) else 0


def cmd_check(report: dict, pid: str) -> int:
    from . import manifest as MM

    row = next((r for r in report["plugins"] if r["id"] == pid), None)
    if row is None:
        print(f"  未找到插件 `{pid}`；已知：{[r['id'] for r in report['plugins']]}", file=sys.stderr)
        return 1
    print(f"插件 {row['id']} v{row['version']}（{row['source']}，{row['dir']}）")
    print(f"  状态：{row['state_label']}" + (f" —— {row['reason']}" if row["reason"] else ""))
    if row["fix"]:
        print(f"  修复：{row['fix']}")
    perms = row["permissions"]
    if perms:
        print("  权限（安装/启用时会展示给用户）：")
        for p in perms:
            print(f"    - {p}：{MM.KNOWN_PERMISSIONS.get(p, '（未支持的权限）')}")
    if row["requires"]:
        print(f"  前提插件：{row['requires']}")
    if row["nav"]:
        print(f"  前端面板：{row['nav']}")
    if row["routes"]:
        print(f"  路由（内核会挂到 /api/plugins/{row['id']}/ 下）：{row['routes']}")
    if row["mcp_tools"]:
        print("  MCP 工具（对外名加前缀）：" + ", ".join(f"p_{row['id']}__{t}" for t in row["mcp_tools"]))
    pv = row.get("preview") or {}
    if pv:
        print("  演示预览（设置页悬停/点击卡片时显示）：")
        if pv.get("summary"):
            print(f"    摘要：{pv['summary']}")
        for f in pv.get("features") or []:
            print(f"    · {f}")
        shots = pv.get("screens") or []
        print("    截图：" + ("、".join(shots) if shots else "（未提供）"))
    if row["issues"]:
        print("  校验项：")
        for i in row["issues"]:
            print(f"    [{'E' if i['level'] == 'error' else 'W'}] {i['code']} {i['message']}"
                  + (f"  → {i['fix']}" if i.get("fix") else ""))
    else:
        print("  校验项：无（manifest 合法、依赖满足）")
    return 0 if row["state"] == "available" else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="插件发现 / 校验 / 状态报告（不加载插件代码）")
    ap.add_argument("action", nargs="?", default="list", choices=["list", "check", "verify"])
    ap.add_argument("plugin_id", nargs="?")
    ap.add_argument("--plugins-root", action="append", help="扫描根，可多次；形如 <dir>[:bundled|user]")
    ap.add_argument("--workspace", help="Workspace 路径（默认按 config/app.json）")
    ap.add_argument("--install", action="store_true",
                    help="先把 plugins/ 下的单文件包（<id>-<version>.zip）解包再盘点"
                         "（PLUGIN_SPEC §2；默认只读，不动磁盘）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    roots = _roots(args.plugins_root)
    workspace = _workspace(args.workspace)

    install_notes: list[str] = []
    if args.install:  # §5 安装：显式动作，与只读盘点分开（见 registry.install_packages）
        for outcome in R.install_packages(roots, workspace=workspace):
            install_notes.append(outcome.note())
            print(outcome.note())

    report = R.report(
        roots=roots,
        workspace=workspace,
        core_version=_core_version(),
    )
    report["notes"] = install_notes + report["notes"]

    if args.json:
        if args.action == "check" and args.plugin_id:
            row = next((r for r in report["plugins"] if r["id"] == args.plugin_id), None)
            print(json.dumps(row or {"error": f"未找到 {args.plugin_id}"}, ensure_ascii=False, indent=2))
            return 0 if row and row["state"] == "available" else 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return cmd_list(report) if args.action != "verify" else cmd_list(report)

    if args.action == "check":
        if not args.plugin_id:
            print("用法：python -m core.plugins check <id>", file=sys.stderr)
            return 2
        return cmd_check(report, args.plugin_id)
    return cmd_list(report)


if __name__ == "__main__":
    raise SystemExit(main())
