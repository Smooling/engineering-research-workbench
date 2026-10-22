#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""截图预处理：裁剪 + 像素预算，把"图片 token"压到最低（v261008）

背景（实测，2026-10-08 · deepseek-v4.1-flash @ OpenCode Zen Go）：
    同一屏 UI，带图 prompt_tokens − 无图基线 得到「图像占用」：
      2x 整窗 2000x1400 (2.80 MP) → 991 tokens
      1x 整窗 1000x700  (0.70 MP) → 428 tokens
      1x 只截列表区 305x700 (0.21 MP) → 203 tokens
    即：图像 token ≈ 140（每张固定开销）+ 约 300/MP，且随面积次线性增长。
    因此「1x + 裁剪」比「2x 整窗」省 ~80%，而单纯压缩文件体积毫无用处。

用法：
    python tools/shot_prep.py <输入图> [-o 输出图] [--crop x1,y1,x2,y2]
                            [--max-mp 0.7] [--max-edge 1600] [--scale 0.5]
    # 例：只留列表面板并压到 0.3 MP
    python tools/shot_prep.py .scratch/tmp/raw.png -o .scratch/tmp/prep.png --crop 195,0,500,700 --max-mp 0.3

输出：处理后图片 + 一行像素/体积/估算 token 对比。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print("需要 Pillow：pip install Pillow", file=sys.stderr)
    raise SystemExit(2)

# 实测标定（2026-10-08 · deepseek-v4.1-flash @ OpenCode Zen Go）：
#   100x70  (0.007 MP) → 190 tokens   ← 地板：再小的图也要 ~190（每张固定开销）
#   305x700 (0.213 MP) → 203 tokens
#   1000x700(0.700 MP) → 428 tokens
#   2000x1400(2.80 MP) → 991 tokens   ← 天花板：>2.8 MP 不再增加（4000x2800/6000x4200 同为 991）
# 结论：token 与**像素面积**强相关、与文件体积无关；低于 ~0.3 MP 后收益极小（地板 190），
#      高于 ~2.8 MP 也不必再压（provider 自带上限）。多张图请合并为一张，省掉每张的地板开销。
MEASURED: list[tuple[float, int]] = [
    (0.000, 190),   # 地板
    (0.213, 203),
    (0.700, 428),
    (2.800, 991),   # 天花板（>2.8 MP 沿用此值）
]
FLOOR_TOKENS = MEASURED[0][1]
CEIL_TOKENS = MEASURED[-1][1]


def estimate_tokens(width: int, height: int) -> int:
    """按实测分段曲线估算单张图的图像 token（含每张固定开销与 provider 上限）。"""
    mp = width * height / 1_000_000
    if mp <= MEASURED[0][0]:
        return FLOOR_TOKENS
    if mp >= MEASURED[-1][0]:
        return CEIL_TOKENS
    for (x0, y0), (x1, y1) in zip(MEASURED, MEASURED[1:]):
        if x0 <= mp <= x1:
            t = (mp - x0) / (x1 - x0)
            return int(round(y0 + (y1 - y0) * t))
    return CEIL_TOKENS


def parse_box(text: str) -> tuple[int, int, int, int]:
    parts = [int(float(p)) for p in text.replace(" ", "").split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("--crop 需要 x1,y1,x2,y2")
    return parts[0], parts[1], parts[2], parts[3]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="截图预处理：裁剪 + 像素预算（降图片 token）")
    ap.add_argument("src", help="输入图片路径")
    ap.add_argument("-o", "--out", help="输出路径（默认 <输入名>.prep.png）")
    ap.add_argument("--crop", type=parse_box, help="裁剪框 x1,y1,x2,y2（像素）")
    ap.add_argument("--scale", type=float, default=1.0, help="先按比例缩放（0.5 = 2x 截图还原为 1x）")
    ap.add_argument("--max-mp", type=float, default=0.7, help="像素预算上限（百万像素，默认 0.7）")
    ap.add_argument("--max-edge", type=int, default=1600, help="长边上限（默认 1600）")
    ap.add_argument("--keep", action="store_true", help="保留原图（默认只写输出）")
    args = ap.parse_args(argv)

    src = Path(args.src)
    if not src.exists():
        print(f"找不到输入：{src}", file=sys.stderr)
        return 1
    img = Image.open(src)
    img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
    before = (img.width, img.height, src.stat().st_size)

    # 顺序很重要：先按 --scale 把 2x 截图还原成 1x，再按 1x 坐标裁剪
    if args.scale and args.scale != 1.0:
        img = img.resize((max(1, int(img.width * args.scale)), max(1, int(img.height * args.scale))), Image.LANCZOS)
    if args.crop:
        img = img.crop(args.crop)
    # 像素预算 + 长边上限，取更严格者
    budget = max(1, int(args.max_mp * 1_000_000))
    factor = min(1.0, (budget / (img.width * img.height)) ** 0.5)
    if max(img.width, img.height) * factor > args.max_edge:
        factor = args.max_edge / max(img.width, img.height)
    if factor < 1.0:
        img = img.resize((max(1, int(img.width * factor + 0.5)), max(1, int(img.height * factor + 0.5))), Image.LANCZOS)

    out = Path(args.out) if args.out else src.with_suffix(".prep.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, format="PNG", optimize=True)

    b_tok = estimate_tokens(before[0], before[1])
    a_tok = estimate_tokens(img.width, img.height)
    saved = b_tok - a_tok
    pct = (saved / b_tok * 100) if b_tok else 0
    print(f"  输入：{before[0]}x{before[1]}  {before[2] / 1024:.0f} KB  ≈ {b_tok} tokens")
    print(f"  输出：{img.width}x{img.height}  {out.stat().st_size / 1024:.0f} KB  ≈ {a_tok} tokens   → {out}")
    print(f"  省：{saved} tokens/张（{pct:.0f}%）；按 8 轮对话累计 ≈ {saved * 8} tokens")
    print("  提示：文件体积与 token 无关——把 441 KB 压到 139 KB 一分钱不省，缩小像素才省。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
