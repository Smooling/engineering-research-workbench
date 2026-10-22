"""前端装配清单 —— index.html 的资源引用块由本清单生成。

用法：
    python tools/web_manifest.py --write    # 按清单重写 index.html 的三段引用块
    python tools/web_manifest.py --check    # 校验 index.html 与清单一致（不一致非零退出）

为什么要清单：`index.html` 原先手写 11 个 `<link>` 与 15 个 `<script>`，**顺序有语义**
（补丁按加载顺序互相覆盖：perf-and-fetch-seam.js 覆盖 window.fetch 且必须排在 app.js 之前）。
顺序散落在 HTML 里既看不出约束、也无从校验——`17682ce` 那次「一个补丁的语法错误直接打掉
整个 PDF 工作区」就是这套隐式顺序的代价（见 docs/REFACTOR_PLAN.md P7/P14）。

清单化之后：顺序只有一处声明，`--check` 可在提交前拦住漂移，
`tools/web_check.py` 再叠加语法、接缝与模块缺失检查。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "web" / "index.html"
MANIFEST = ROOT / "web" / "manifest.json"

MARKERS = {
    "css": ("web:css:start", "web:css:end"),
    "vendor_js": ("web:vendor-js:start", "web:vendor-js:end"),
    "js": ("web:app-js:start", "web:app-js:end"),
}

MARKER_NOTE = "由 tools/web_manifest.py 生成，勿手改；顺序见 web/manifest.json"


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def render_css(entries: list[dict]) -> list[str]:
    out = []
    for item in entries:
        href = f"/{item['file']}" + (f"?v={item['v']}" if item.get("v") else "")
        attrs = f'href="{href}"'
        if item.get("cdn"):
            attrs += f" onerror=\"this.onerror=null;this.href='{item['cdn']}'\""
        line = f'  <link rel="stylesheet" {attrs}>'
        if item.get("note"):
            line += f"<!-- {item['note']} -->"
        out.append(line)
    return out


def render_js(entries: list[dict]) -> list[str]:
    out = []
    for item in entries:
        src = f"/{item['file']}" + (f"?v={item['v']}" if item.get("v") else "")
        attrs = f'src="{src}"'
        if item.get("cdn"):
            attrs += f" onerror=\"this.onerror=null;this.src='{item['cdn']}'\""
        line = f'  <script defer {attrs}></script>'
        if item.get("note"):
            line += f"<!-- {item['note']} -->"
        out.append(line)
    return out


def render_region(kind: str, manifest: dict) -> list[str]:
    start, end = MARKERS[kind]
    body = render_css(manifest["css"]) if kind == "css" else render_js(manifest[kind])
    return [f"  <!-- {start}（{MARKER_NOTE}） -->", *body, f"  <!-- {end} -->"]


def splice(html: str, kind: str, lines: list[str]) -> str:
    start, end = MARKERS[kind]
    pattern = re.compile(
        rf"[ \t]*<!-- {re.escape(start)}.*?-->.*?[ \t]*<!-- {re.escape(end)} -->",
        re.S,
    )
    replacement = "\n".join(lines)
    new, n = pattern.subn(lambda _m: replacement, html, count=1)
    if n != 1:
        raise SystemExit(f"index.html 缺少 {start}/{end} 标记块（找到 {n} 个）")
    return new


def build(html: str, manifest: dict) -> str:
    for kind in ("css", "vendor_js", "js"):
        html = splice(html, kind, render_region(kind, manifest))
    return html


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="前端装配清单：生成/校验 index.html 的引用块")
    ap.add_argument("--write", action="store_true", help="按清单重写 index.html")
    ap.add_argument("--check", action="store_true", help="校验 index.html 与清单一致")
    args = ap.parse_args(argv)

    manifest = load_manifest()
    html = INDEX.read_text(encoding="utf-8")
    want = build(html, manifest)

    if args.write:
        if want != html:
            INDEX.write_text(want, encoding="utf-8")
            print("已按清单重写 index.html")
        else:
            print("index.html 已与清单一致，无需改动")
        return 0

    if want != html:
        print("index.html 与 web/manifest.json 不一致：", file=sys.stderr)
        import difflib

        for line in difflib.unified_diff(
            html.splitlines(), want.splitlines(), "index.html", "manifest", lineterm="", n=1
        ):
            print("  " + line, file=sys.stderr)
        print("  修复：python tools/web_manifest.py --write", file=sys.stderr)
        return 1
    print("index.html 与清单一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
