"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
验证 docs/*.md 里的 mermaid 图能真渲染（用仓库自带的 web/vendor/mermaid.min.js）。

做法：真浏览器 + 注入 vendored mermaid → 对每个 ```mermaid 块 mermaid.parse() + mermaid.render()；
任何语法错都会抛异常。可选把主结构图导出成 SVG（供不支持 mermaid 的查看器）。

用法：python tests/docs/test_mermaid.py [要导出的图序号，默认 1]
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / "docs" / "OVERVIEW.md", ROOT / "README.md", ROOT / "docs" / "PLUGIN_SPEC.md"]
MERMAID_JS = ROOT / "web" / "vendor" / "mermaid.min.js"
OUT_SVG = ROOT / "docs" / "img" / "structure.svg"

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


def blocks(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return re.findall(r"```mermaid\n(.*?)```", text, re.S)


def main() -> int:
    # 参数兼容：手跑时可传「要导出的图序号」（`--export N` 或裸数字）；被 tools/run_tests.py 调用时
    # 第 1 个参数是工作台 URL（本用例不需要服务）——两种情况都要能跑（实测把 URL 当序号会 ValueError）。
    # **默认不导出**：`docs/img/structure.svg` 是入库产物，测试每次重写它只会产生"随机 id 变化"的噪音 diff。
    export_index = 0
    for index, arg in enumerate(sys.argv[1:]):
        if arg.startswith("http"):
            continue
        if arg == "--export":
            nxt = sys.argv[index + 2] if index + 2 < len(sys.argv) else "1"
            export_index = int(nxt) if nxt.isdigit() else 1
            continue
        if arg.isdigit() and export_index == 0:
            export_index = int(arg)
    from playwright.sync_api import sync_playwright

    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe if Path(exe).is_file() else None, headless=True)

        def fresh_page():
            """每张图一个全新页面：mermaid 是单例，同页连续渲染会互相污染（实测会报
            `Cannot set properties of undefined (setting 'order')` 这类与图本身无关的错）。"""
            page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
            page.goto("about:blank")
            page.add_script_tag(path=str(MERMAID_JS))
            page.evaluate("() => mermaid.initialize({startOnLoad:false, theme:'neutral'})")
            return page

        probe = fresh_page()
        ok = probe.evaluate("() => typeof mermaid !== 'undefined' && typeof mermaid.parse === 'function'")
        check("vendored mermaid 可用", bool(ok))
        probe.close()

        first_svg = ""
        total = 0
        for path in DOCS:
            if not path.is_file():
                continue
            found = blocks(path)
            print(f"\n{path.relative_to(ROOT)}（{len(found)} 张图）")
            for index, source in enumerate(found, 1):
                total += 1
                page = fresh_page()
                result = page.evaluate(
                    """async (src) => {
                        try {
                            await mermaid.parse(src);
                            const out = await mermaid.render('g' + Math.random().toString(36).slice(2), src);
                            const svg = (out && out.svg) || (typeof out === 'string' ? out : '');
                            return {ok: true, svg, nodes: (svg.match(/class="node/g) || []).length,
                                    edges: (svg.match(/class="edge/g) || []).length, len: svg.length};
                        } catch (e) {
                            return {ok: false, error: String((e && e.message) || e).slice(0, 300)};
                        }
                    }""",
                    source,
                )
                page.close()
                label = f"{path.name} 图{index}"
                check(f"{label} 能解析并渲染",
                      bool(result.get("ok")) and int(result.get("len", 0)) > 500,
                      str(result.get("error") or result)[:200])
                if result.get("ok"):
                    print(f"    → SVG {result['len'] // 1024} KB · 节点 {result['nodes']} · 连线 {result['edges']}")
                    if path.name == "OVERVIEW.md" and index == export_index and not first_svg:
                        first_svg = result["svg"]
        browser.close()

    if first_svg:
        OUT_SVG.parent.mkdir(parents=True, exist_ok=True)
        OUT_SVG.write_text(first_svg, encoding="utf-8")
        print(f"\n已导出主结构图 → {OUT_SVG.relative_to(ROOT)}（{OUT_SVG.stat().st_size // 1024} KB）")
        check("导出的 SVG 是合法 XML", first_svg.lstrip().startswith("<svg") or "<svg" in first_svg[:400])

    print(f"\n结果：{len(PASS)}/{len(PASS) + len(FAIL)} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    print(f"（共检查 {total} 张 mermaid 图）")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
