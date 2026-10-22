"""文档闸门：检查 Markdown 里的 mermaid 图**真的能渲染**（用仓库自带的 `web/vendor/mermaid.min.js`）。

```powershell
python tools/doc_check.py                      # 检查 docs/*.md 与 README.md 里的全部 mermaid 图
python tools/doc_check.py --export docs/OVERVIEW.md 1
                                              # 顺带把某张图导出成 docs/img/*.svg
python tools/doc_check.py --files docs/OVERVIEW.md README.md
```

为什么要它：mermaid 的语法错在编辑器里往往只表现为一张「红字报错图」，很容易带着坏图提交。
实测踩过两次——`flowchart` 里**给子图参与画边**（`FE --> SV`）会让当前 vendored 版本抛
`Cannot set properties of undefined (setting 'order')`；子图只作视觉分组、边一律节点→节点即可。

每张图**用全新页面渲染**：mermaid 是单例，同页连续渲染会互相污染，产生与图无关的假失败。
需要 `playwright`；浏览器复用机器上已有的 Chrome/Edge 或 ms-playwright 的 chromium。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MERMAID_JS = ROOT / "web" / "vendor" / "mermaid.min.js"
DEFAULT_FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def blocks(path: Path) -> list[str]:
    return re.findall(r"```mermaid\n(.*?)```", path.read_text(encoding="utf-8"), re.S)


def find_browser() -> str | None:
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ]
    for path in candidates:
        if Path(path).is_file():
            return path
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="检查 Markdown 里的 mermaid 图能否渲染")
    ap.add_argument("--files", nargs="*", help="要检查的文件（默认 README.md + docs/*.md）")
    ap.add_argument("--export", nargs=2, metavar=("FILE", "INDEX"),
                    help="把某文件的第 N 张图导出为 docs/img/structure.svg")
    ap.add_argument("--out", default="", help="导出路径（默认 docs/img/structure.svg）")
    args = ap.parse_args(argv)

    if not MERMAID_JS.is_file():
        print(f"找不到 vendored mermaid：{MERMAID_JS}", file=sys.stderr)
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("需要 playwright：pip install playwright", file=sys.stderr)
        return 2

    files = [Path(p) if Path(p).is_absolute() else ROOT / p for p in args.files] if args.files else DEFAULT_FILES
    files = [p for p in files if p.is_file()]
    if not files:
        print("没有可检查的文件", file=sys.stderr)
        return 2

    problems: list[str] = []
    checked = 0
    export_target = Path(args.out) if args.out else ROOT / "docs" / "img" / "structure.svg"
    export_svg = ""

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=find_browser(), headless=True)

        def fresh_page():
            page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
            page.goto("about:blank")
            page.add_script_tag(path=str(MERMAID_JS))
            page.evaluate("() => mermaid.initialize({startOnLoad:false, theme:'neutral'})")
            return page

        probe = fresh_page()
        if not probe.evaluate("() => typeof mermaid !== 'undefined' && typeof mermaid.parse === 'function'"):
            print("vendored mermaid 无法初始化", file=sys.stderr)
            return 2
        probe.close()

        for path in files:
            found = blocks(path)
            if not found:
                continue
            rel = path.relative_to(ROOT)
            for index, source in enumerate(found, 1):
                checked += 1
                page = fresh_page()
                result = page.evaluate(
                    """async (src) => {
                        try {
                            await mermaid.parse(src);
                            const out = await mermaid.render('g' + Math.random().toString(36).slice(2), src);
                            const svg = (out && out.svg) || '';
                            return {ok: true, svg, len: svg.length,
                                    nodes: (svg.match(/class="node/g) || []).length};
                        } catch (e) {
                            return {ok: false, error: String((e && e.message) || e).slice(0, 200)};
                        }
                    }""",
                    source,
                )
                page.close()
                if result.get("ok"):
                    print(f"  ok   {rel} 图{index}  SVG {result['len'] // 1024} KB · 节点 {result['nodes']}")
                    if args.export and str(rel) == str(Path(args.export[0])) and index == int(args.export[1]):
                        export_svg = result["svg"]
                else:
                    problems.append(f"{rel} 图{index}：{result.get('error')}")
                    print(f"  FAIL {rel} 图{index}  {result.get('error')}")
        browser.close()

    if export_svg:
        export_target.parent.mkdir(parents=True, exist_ok=True)
        export_target.write_text(export_svg, encoding="utf-8")
        print(f"\n已导出 {export_target.relative_to(ROOT)}（{export_target.stat().st_size // 1024} KB）")

    print(f"\nmermaid 图检查：{checked} 张，失败 {len(problems)} 张")
    for item in problems:
        print("  - " + item)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
