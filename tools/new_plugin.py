"""从模板生成一个新插件（PLUGIN_SPEC §13）。

```powershell
python tools/new_plugin.py my-tool --name "我的工具" --desc "一句话说明它干什么"
python tools/new_plugin.py my-tool --root <其他插件根> --dry-run
```

做的事只有一件：把 `plugins/.template/` 的占位符替换掉，放进 `plugins/<id>/`，
再跑一遍**和安装时同一套** manifest 校验。

**先临时后原子**（与单文件包解包同一套规矩）：内容先渲染到 `<root>/.new-<id>/`，
校验通过才 `rename` 成 `<root>/<id>/`——所以任何时刻都不会留下一个"半成品插件"让扫描器难受。
默认拒绝覆盖已存在的目录；确要重做用 `--force`（旧目录整体挪到 `<root>/.backup-<id>-<时间戳>/`，
不删除、不合并）。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.plugins import manifest as M  # noqa: E402

DEFAULT_TEMPLATE = ROOT / "plugins" / ".template"

#: 会被替换的占位符（模板里出现即替换；文件里没有就跳过）
TOKENS = ("__ID__", "__NAME__", "__DESC__", "__ICON__", "__CORE_MIN__")
#: 只有这些后缀当文本处理（模板里目前也只有这些）
TEXT_SUFFIXES = {".json", ".py", ".js", ".css", ".md", ".txt", ".html"}
#: 复制时跳过的东西
SKIP_DIRS = {"__pycache__", ".git"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def render_tree(template: Path, dest: Path, values: dict[str, str]) -> list[str]:
    """把模板渲染到 dest，返回写出的相对路径列表（不碰模板本身）。"""
    written: list[str] = []
    for src in sorted(template.rglob("*")):
        rel = src.relative_to(template)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if src.is_dir():
            continue
        if src.suffix in SKIP_SUFFIXES:
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in TEXT_SUFFIXES:
            text = src.read_text(encoding="utf-8")
            for token, value in values.items():
                text = text.replace(token, value)
            # 写 UTF-8 **无 BOM**：带 BOM 会让 plugin.json 解析失败、core_min 比较全线失败
            out.write_text(text, encoding="utf-8", newline="\n")
        else:
            shutil.copy2(src, out)
        written.append(str(rel).replace("\\", "/"))
    return written


def build_plan(plugin_id: str, *, name: str, desc: str, icon: str) -> dict[str, str]:
    return {
        "__ID__": plugin_id,
        "__NAME__": name or plugin_id,
        "__DESC__": desc or f"{name or plugin_id}（插件）",
        "__ICON__": icon or "◇",
        # 默认要求「开发这个插件时所处的内核版本」：低了会在别的机器上被静默拒载
        "__CORE_MIN__": M.read_core_version(ROOT) or "v261009",
    }


def check_new_dir(plugin_dir: Path) -> tuple[dict | None, list[dict]]:
    """用安装时同一套校验器检查渲染结果（含文件是否存在、目录名是否等于 id）。"""
    data, issues = M.load_manifest(plugin_dir)
    issues = list(issues) + list(M.validate(data, plugin_dir=plugin_dir))
    return data, issues


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="从模板生成新插件（不改内核，只落文件）")
    ap.add_argument("id", help="插件 id：小写字母开头，小写字母/数字/短横线，长度 2–40")
    ap.add_argument("--name", default="", help="界面显示名（默认用 id）")
    ap.add_argument("--desc", default="", help="一句话描述（默认自动生成）")
    ap.add_argument("--icon", default="", help="导航图标字符（默认 ◇）")
    ap.add_argument("--core-min", default="", help="最低内核版本（默认沿用模板里的值）")
    ap.add_argument("--root", default="", help="插件根目录（默认仓库 plugins/）")
    ap.add_argument("--template", default="", help="模板目录（默认 plugins/.template）")
    ap.add_argument("--force", action="store_true", help="允许重做：旧目录整体挪到 .backup-<id>-<时间戳>/")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不落盘")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    plugin_id = str(args.id or "").strip()
    if not M.ID_RE.match(plugin_id):
        print(f"插件 id `{plugin_id}` 不合法：小写字母开头、只含小写字母/数字/短横线，长度 2–40",
              file=sys.stderr)
        return 2

    root = Path(args.root).resolve() if args.root else ROOT / "plugins"
    template = Path(args.template).resolve() if args.template else DEFAULT_TEMPLATE
    if not (template / "plugin.json").is_file():
        print(f"模板目录不完整（缺 plugin.json）：{template}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"插件根目录不存在：{root}", file=sys.stderr)
        return 2

    values = build_plan(plugin_id, name=args.name, desc=args.desc, icon=args.icon)
    if args.core_min:
        values["__CORE_MIN__"] = str(args.core_min).strip()
    target = root / plugin_id
    backup: Path | None = None

    plan = {
        "id": plugin_id, "root": str(root), "template": str(template),
        "target": str(target), "name": values["__NAME__"], "description": values["__DESC__"],
        "icon": values["__ICON__"], "force": bool(args.force), "dry_run": bool(args.dry_run),
    }
    if target.exists() and not args.force:
        print(f"目录已存在：{target}\n要用模板重做请加 --force（旧目录会整体挪到 "
              f"{root / f'.backup-{plugin_id}-<时间戳>'}/，不会被删）", file=sys.stderr)
        return 2

    if args.dry_run:
        with __import__("tempfile").TemporaryDirectory() as td:
            written = render_tree(template, Path(td), values)
        plan["files"] = written
        print(json.dumps(plan, ensure_ascii=False, indent=2) if args.json
              else f"[dry-run] 会把 {len(written)} 个文件渲染到 {target}：\n  " + "\n  ".join(written))
        return 0

    tmp = root / ".staging" / plugin_id
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    try:
        written = render_tree(template, tmp, values)
        data, issues = check_new_dir(tmp)
        errors = M.errors(issues)
        if errors:
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(root / ".staging", ignore_errors=True)
            print("模板渲染后校验不过（这是模板/脚手架的问题，请报一下）：", file=sys.stderr)
            for i in issues:
                print(f"  [{i['level']}] {i['code']} {i['message']}", file=sys.stderr)
            return 1
        if target.exists():   # --force：旧目录整体挪走，不删除、不合并
            backup = root / f".backup-{plugin_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            try:
                shutil.move(str(target), str(backup))
            except OSError as exc:
                shutil.rmtree(tmp, ignore_errors=True)
                shutil.rmtree(root / ".staging", ignore_errors=True)
                print(f"旧目录挪不动，已放弃（原目录未改）：{exc}", file=sys.stderr)
                return 1
        tmp.rename(target)
        try:
            (root / ".staging").rmdir()   # 只在空的时候删掉，别动别人的暂存内容
        except OSError:
            pass
    except OSError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"生成失败：{exc}", file=sys.stderr)
        return 1

    plan["files"] = written
    plan["version"] = str((data or {}).get("version") or "")
    plan["backup"] = str(backup) if backup else ""
    plan["warnings"] = [f"{i['code']} {i['message']}" for i in issues if i["level"] != "error"]

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(f"已生成 {target}")
        print(f"  文件 {len(written)} 个：{'、'.join(written)}")
        if backup:
            print(f"  旧目录已挪到：{backup}")
        for w in plan["warnings"]:
            print(f"  提示：{w}")
        print("下一步：")
        print(f"  1) 改 backend.py 的 register(ctx) 与 web/panel.js —— 不需要动内核任何文件")
        print(f"  2) python -m core.plugins list 与 python -m core.plugins check {plugin_id}")
        print(f"  3) 改了后端/清单要**重启工作台**；只改 web/* 刷新即可")
        print(f"  4) 默认不启用：到「设置 → 插件」里点启用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
