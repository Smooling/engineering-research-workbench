# -*- coding: utf-8 -*-
"""v261008 · 操作临时空间 `.scratch/` 清理入口（一键脚本 / 手动调用 / 排障）。

用法：
  python tools/scratch_clean.py                # 按默认保留期（7 天）清理
  python tools/scratch_clean.py --days 3       # 临时改保留期
  python tools/scratch_clean.py --days 0       # 清空（保留骨架目录与 README.md）
  python tools/scratch_clean.py --dry-run      # 只列出将删除的内容，不落盘
  python tools/scratch_clean.py --status       # 只看占用概况，不清理
  python tools/scratch_clean.py --json         # 机器可读输出（便于日志采集）

保留期也可用环境变量覆盖：`ERW_SCRATCH_RETENTION_DAYS`。

退出码：0 成功 / 1 执行失败 / 2 参数错误。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import scratch  # noqa: E402


def _format_time(stamp: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp)) if stamp else "—"


def _print_status(info: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"status": info}, ensure_ascii=False, indent=2))
        return
    print(f"临时空间：{info['dir']}")
    if not info["exists"]:
        print("  状态：尚未创建（首次清理或工作台启动时会自动创建）")
        return
    print(f"  文件数：{info['files']}    占用：{scratch.human_size(info['bytes'])}")
    print(f"  最旧：{_format_time(info['oldest'])}    最新：{_format_time(info['newest'])}")
    if info["by_dir"]:
        print("  分目录：")
        for name, slot in sorted(info["by_dir"].items(), key=lambda kv: -kv[1]["bytes"]):
            print(f"    {name:<10} {slot['files']:>4} 个    {scratch.human_size(slot['bytes'])}")


def _print_retention_note(days: int) -> None:
    cutoff = time.time() - days * scratch.SECONDS_PER_DAY
    print(f"  （保留期 {days} 天，早于 {_format_time(cutoff)} 的文件视为过期）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scratch_clean.py",
        description="清理操作临时空间 .scratch/（按 mtime 删除过期文件，保留骨架目录与 README.md）",
    )
    parser.add_argument("--days", type=int, default=None, help=f"保留天数，默认 {scratch.DEFAULT_RETENTION_DAYS}（0 = 清空）")
    parser.add_argument("--dry-run", action="store_true", help="只列出将删除的内容，不落盘")
    parser.add_argument("--status", action="store_true", help="只看占用概况，不清理")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--quiet", action="store_true", help="无删除时保持安静（供启动钩子调用）")
    args = parser.parse_args(argv)

    if args.days is not None and args.days < 0:
        print("参数错误：--days 不能为负数", file=sys.stderr)
        return 2

    try:
        if args.status:
            _print_status(scratch.stats(), args.json)
            return 0

        days = scratch.resolve_retention_days() if args.days is None else args.days
        scratch.ensure()
        result = scratch.clean(days, dry_run=args.dry_run)

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif result["deleted"] or not args.quiet:
            title = "将清理（干跑）" if args.dry_run else "清理完成"
            print(f"{title}：{scratch.summarize(result)}")
            _print_retention_note(result["retention_days"])
            for name in result["deleted"]:
                print(f"  {'- ' if not args.dry_run else '? '}{name}")
            if not result["deleted"]:
                print(f"  没有过期文件；空间位置：{result['dir']}")
            for message in result["errors"]:
                print(f"  ! 失败：{message}", file=sys.stderr)

        return 1 if result["errors"] else 0
    except Exception as exc:  # 清理失败不应让调用方崩掉
        print(f"清理失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
