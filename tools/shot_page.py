#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一条龙 UI 截图：无头浏览器按 **1x** 采集 → 裁剪/压像素 → 打印图片 token 估算（v261008.2m）

为什么需要它：
    图片 token 只与**像素面积**相关（实测 ≈140 固定 + ~300/MP，地板 ~190、上限 ~991），
    而"2x 整窗 + 每改一处截一张"是这类工作里最大的浪费来源。常用组合的实测成本：
        2x 整窗 2000x1400 (2.80 MP) → 991 tokens
        1x 整窗 1000x700  (0.70 MP) → 428 tokens   ← 本脚本默认
        1x 裁到面板 305x700 (0.21 MP) → 203 tokens ← 推荐（--crop 或 --max-mp 0.3）
    另外：每次都用**全新临时 profile**，避免反复出现「改了 CSS 但截图没变」的缓存假象
    （旧 profile 会命中 HTTP 缓存，这是排查一次就能浪费半小时的坑）。

用法：
    python tools/shot_page.py <url 或本地 html 路径> -o out.png [选项]

    # 采集整窗（1x）
    python tools/shot_page.py http://127.0.0.1:8765/#literature -o .scratch/tmp/list.png

    # 只保留列表面板：先按 2x 采、再还原 1x 裁剪（本地预览页更推荐直接做成"只含目标区域"）
    python tools/shot_page.py page.html -o .scratch/tmp/panel.png --scale 2 --crop 195,0,500,700

    # 像素预算 0.3 MP（约 200 tokens/张）
    python tools/shot_page.py page.html -o out.png --max-mp 0.3

选项：
    --size 1000x700     视口（CSS 像素，默认 1000x700）
    --scale 1           设备像素比；2 = 视网膜（token ×4，默认不用）
    --crop x1,y1,x2,y2  裁剪框（按 --scale 还原后的 1x 坐标）
    --max-mp 0.3        像素预算（百万像素）；0 表示不压
    --wait 3000         虚拟时间预算（毫秒），SPA 建议 ≥ 6000
    --keep-raw          保留未处理的原始截图
    --quiet             只打印一行结果

输出：处理后的图片路径 + 像素/体积/token 对比（图片 token 是**每次请求都重算**的，
     所以省下来的量要按"这张图还会在上下文里出现多少轮"去算）。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shot_prep import estimate_tokens, main as prep_main  # noqa: E402  （同目录工具，复用标定与裁剪逻辑）

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)


def find_browser() -> str:
    import os

    env = os.environ.get("ERW_BROWSER") or os.environ.get("CHROME_PATH")
    if env and Path(env).exists():
        return env
    for cand in CHROME_CANDIDATES:
        if Path(cand).exists():
            return cand
    found = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("msedge")
    if found:
        return found
    raise SystemExit("找不到 Chrome/Edge：设置环境变量 ERW_BROWSER 指向可执行文件")


def to_url(target: str) -> str:
    if target.startswith(("http://", "https://", "file://", "about:")):
        return target
    path = Path(target).resolve()
    if not path.exists():
        raise SystemExit(f"找不到本地文件：{path}")
    return "file:///" + path.as_posix().lstrip("/")


def parse_size(text: str) -> tuple[int, int]:
    try:
        w, h = (int(float(p)) for p in text.lower().replace(" ", "").split("x"))
    except Exception:
        raise SystemExit("--size 需要 宽x高，例如 1000x700") from None
    return w, h


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="无头浏览器 1x 截图 + 裁剪 + 图片 token 估算")
    ap.add_argument("target", help="URL 或本地 html 路径")
    ap.add_argument("-o", "--out", required=True, help="输出图片路径")
    ap.add_argument("--size", type=parse_size, default=(1000, 700), help="视口宽x高（CSS 像素，默认 1000x700）")
    ap.add_argument("--scale", type=float, default=1.0, help="设备像素比（2 = 视网膜，token ×4；默认 1）")
    ap.add_argument("--crop", default="", help="裁剪框 x1,y1,x2,y2（1x 坐标）")
    ap.add_argument("--max-mp", type=float, default=0.3, help="像素预算（百万像素，默认 0.3≈200 token；0 = 不压）")
    ap.add_argument("--max-edge", type=int, default=1600, help="长边上限")
    ap.add_argument("--wait", type=int, default=3000, help="虚拟时间预算（ms），SPA 建议 ≥6000")
    ap.add_argument("--keep-raw", action="store_true", help="保留原始截图")
    ap.add_argument("--quiet", action="store_true", help="只打印一行结果")
    args = ap.parse_args(argv)

    url = to_url(args.target)
    out = Path(args.out).resolve()   # 必须是绝对路径：Chrome 的工作目录与本进程不同，相对路径会写失败
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_name(out.stem + ".raw.png")
    width, height = args.size
    profile = Path(tempfile.mkdtemp(prefix="erw-shot-"))  # 每次全新 profile：避免 HTTP 缓存假象

    cmd = [
        find_browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
        "--no-default-browser-check", f"--force-device-scale-factor={args.scale:g}",
        f"--window-size={width},{height}", f"--virtual-time-budget={max(500, args.wait)}",
        f"--user-data-dir={profile}", f"--screenshot={raw}", url,
    ]
    try:
        # 编码必须显式指定：Windows 默认 GBK 解 Chrome 的 UTF-8 输出会抛 UnicodeDecodeError
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except subprocess.TimeoutExpired:
        shutil.rmtree(profile, ignore_errors=True)
        print("截图超时（120s）：把 --wait 调小或检查页面是否卡住", file=sys.stderr)
        return 1
    shutil.rmtree(profile, ignore_errors=True)

    if not raw.exists():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        print("截图失败：没有产出图片文件。浏览器输出尾部：\n  " + "\n  ".join(tail), file=sys.stderr)
        return 1

    if not args.quiet:
        from PIL import Image

        with Image.open(raw) as im:
            print(f"  原始：{im.width}x{im.height}  ≈ {estimate_tokens(im.width, im.height)} tokens"
                  f"   （px 比例 {args.scale:g}x，视口 {width}x{height}）")

    prep_argv = [str(raw), "-o", str(out), "--scale", f"{args.scale:g}", "--max-edge", str(args.max_edge)]
    if args.crop:
        prep_argv += ["--crop", args.crop]
    if args.max_mp and args.max_mp > 0:
        prep_argv += ["--max-mp", f"{args.max_mp:g}"]
    rc = prep_main(prep_argv)
    if rc != 0:
        return rc
    if not args.keep_raw:
        raw.unlink(missing_ok=True)
    if not args.quiet:
        print("  提示：图片 token 每次请求都要重算——按「这张图还会在上下文里出现几轮」估算实际代价；"
              "能靠文本度量（getBoundingClientRect / computed style）判断的改动不要截图。")
    else:
        from PIL import Image

        with Image.open(out) as im:
            print(f"{out}  {im.width}x{im.height}  ≈ {estimate_tokens(im.width, im.height)} tokens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
