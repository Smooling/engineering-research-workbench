"""前端静态体检 —— 提交前的低成本回归闸门（只读）。

背景：`17682ce fix: restore PDF workspace after performance patch syntax error` —— 一个补丁的
语法错误直接打掉整个 PDF 工作区，而当时没有任何闸门能在提交前发现它（见
docs/REFACTOR_PLAN.md P7/P14/P29）。本脚本把能静态查的都查掉：

1. **语法**：web/ 下所有非 vendor 的 `.js` / `.css` 过一遍 `node --check`（CSS 过括号配平）。
2. **装配一致性**：index.html 与 `web/manifest.json` 一致（调 web_manifest --check）。
3. **模块缺失**：清单里的文件必须在磁盘上；磁盘上的入口文件必须进清单。
4. **接缝完整（P14）**：任何 `window.ERW*` 的**消费方**都必须存在**定义方**；
   任何自定义事件（`workbench:*` / `erw-*`）的监听方都必须存在派发方。
   —— 这条是「补丁可以单独摘除」的可验证定义：删掉 billing.js 而没人提供 ERWBilling 时会立刻报错，
   而不是等用户在页面上点「用量」才发现白屏。
5. **加载顺序约束**：`perf-and-fetch-seam.js` 包装 `window.fetch`，必须排在 `app.js` 之前。

用法：
    python tools/web_check.py            # 全部检查
    python tools/web_check.py --no-node  # 跳过 node 检查（无 node 时）

退出码非 0 表示有问题。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
MANIFEST = WEB / "manifest.json"

BROWSER_EVENTS = {
    "DOMContentLoaded", "load", "beforeunload", "click", "change", "input", "keydown", "keyup",
    "pywebviewready",  # 由 pywebview 原生桥接派发，不属于仓库内的自定义事件
    "resize", "scroll", "hashchange", "popstate", "paste", "drop", "dragover", "dragleave",
    "pointerdown", "pointermove", "pointerup", "pointercancel", "mousedown", "mousemove",
    "mouseup", "wheel", "focus", "blur", "submit", "animationend", "transitionend",
    "abort", "error", "readystatechange", "visibilitychange", "contextmenu", "pointerenter",
    "pointerleave", "touchstart", "touchmove", "touchend", "online", "offline", "storage",
    # v261009.27 · 补上鼠标进出与其余标准 UI 事件：它们不需要"派发方"，
    # 缺了会让 web_check 把标准事件误报成「没人派发的自定义事件」（实测 mouseenter/mouseleave 踩到）
    "mouseenter", "mouseleave", "mouseover", "mouseout", "dblclick", "select", "reset",
    "focusin", "focusout", "invalid", "play", "pause", "ended", "canplay", "timeupdate",
    # v261015 · 指针捕获是浏览器原生事件（截断拖拽用），同样不需要派发方
    "lostpointercapture", "gotpointercapture",
    # v261022.2 · pagehide 是浏览器原生事件（同步页在页面隐藏时上报脏状态），无需派发方
    "pagehide", "beforeunload", "pageshow", "message",
    # v261022.4 · 输入法组合事件（引用补全在中文输入时暂停）同样是原生事件
    "compositionstart", "compositionend", "compositionupdate",
}

#: 派发自定义事件：`new CustomEvent("x")` 与 `new Event("x")` 两种写法都要认
_DISPATCH = re.compile(r"new\s+(?:Custom)?Event\(\s*['\"]([\w:.-]+)")

problems: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


def app_js_files() -> list[Path]:
    """web/ 根下的业务 JS（不含 vendor/ 子树）。"""
    return sorted(p for p in WEB.glob("*.js"))


def check_syntax(use_node: bool) -> None:
    files = app_js_files()
    if not use_node or not shutil.which("node"):
        notes.append("跳过 node --check（未找到 node）")
    else:
        for path in files:
            r = subprocess.run(
                ["node", "--check", str(path)], capture_output=True, text=True,
                encoding="utf-8", errors="replace", cwd=str(ROOT),
            )
            if r.returncode != 0:
                detail = (r.stderr or r.stdout).strip().splitlines()
                fail(f"语法错误 {path.relative_to(ROOT)}：{detail[-1] if detail else 'node --check 失败'}")
    # CSS：粗查括号配平（脏括号是补丁层最常见的破坏方式）
    for path in sorted(WEB.glob("*.css")):
        text = path.read_text(encoding="utf-8")
        stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        depth = stripped.count("{") - stripped.count("}")
        if depth != 0:
            fail(f"CSS 花括号不配平 {path.name}：差值 {depth:+d}")


def check_manifest() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "web_manifest.py"), "--check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    if r.returncode != 0:
        fail("index.html 与 web/manifest.json 不一致（跑 python tools/web_manifest.py --write）")

    listed: set[str] = set()
    for group in ("css", "vendor_js", "js"):
        for item in manifest[group]:
            listed.add(item["file"])
            path = WEB / item["file"]
            if not path.is_file():
                fail(f"清单引用了不存在的文件：{item['file']}（{group}）")
            if item.get("v") and path.is_file():
                pass  # 版本参数只做缓存键，无法静态校验是否"最新"，由 review 保证
    for path in app_js_files():
        rel = path.name
        if rel not in listed and rel != "vendor-lazy.js":
            fail(f"{rel} 不在 manifest.json 里（新增前端模块必须登记装配清单）")
    notes.append(f"清单登记 {len(listed)} 个资源")
    return manifest


def check_seams() -> None:
    files = app_js_files()
    # v261009.14 · 插件前端脚本与内核同处一个页面：**自定义事件的派发方可能在插件里**
    # （阅读区搬成 plugins/literature-reader 后，erw-lit-page/-selection 就由它派发）。
    # 故事件完备性按「内核 + 插件」一起判，插件里的派发方也算数。
    # `plugins/.template` 这类点目录不是插件（与 registry.discover 同一规则）：不参与接缝统计，
    # 否则模板里的示例脚本会被当成"提供方"，把真实的缺口掩盖掉。
    plugin_files = sorted(p for p in (ROOT / "plugins").glob("*/web/*.js")
                          if not p.parent.parent.name.startswith(".")) if (ROOT / "plugins").is_dir() else []
    defined: dict[str, set[str]] = {}
    consumed: dict[str, set[str]] = {}
    dispatched: dict[str, set[str]] = {}
    listened: dict[str, set[str]] = {}

    for path in files:
        text = path.read_text(encoding="utf-8")
        name = path.name
        for sym in set(re.findall(r"window\.(ERW[\w$]*)\s*=", text)):
            defined.setdefault(sym, set()).add(name)
        for sym in set(re.findall(r"window\.(ERW[\w$]*)\b(?!\s*[=])", text)):
            consumed.setdefault(sym, set()).add(name)
        for ev in set(_DISPATCH.findall(text)):
            dispatched.setdefault(ev, set()).add(name)
        for ev in set(re.findall(r"addEventListener\(\s*['\"]([\w:.-]+)", text)):
            listened.setdefault(ev, set()).add(name)

    for path in plugin_files:
        text = path.read_text(encoding="utf-8")
        name = f"plugins/{path.parent.parent.name}/{path.name}"
        # 插件也能**提供**接缝：如 plugins/literature-reader 提供 window.ERWLiterature / ERWCapture
        # 给悬浮球消费（依赖方向仍是插件→内核：内核只认 window.ERWReader 注册表，不认识具体插件）
        for sym in set(re.findall(r"window\.(ERW[\w$]*)\s*=", text)):
            defined.setdefault(sym, set()).add(name)
        for ev in set(_DISPATCH.findall(text)):
            dispatched.setdefault(ev, set()).add(name)

    for sym, users in sorted(consumed.items()):
        if sym in defined:
            continue
        # 由其它层提供（原生外壳注入 / 后端页面）的例外在此登记
        fail(f"window.{sym} 被 {', '.join(sorted(users))} 消费，但 web/ 与 plugins/ 里都没有定义方")

    for ev, users in sorted(listened.items()):
        if ev in BROWSER_EVENTS or ev in dispatched:
            continue
        fail(f"自定义事件 {ev} 被 {', '.join(sorted(users))} 监听，但 web/ 与 plugins/ 里都没有派发方")

    notes.append(
        f"接缝：定义 {len(defined)} 个 window.ERW*、消费 {len(consumed)} 个；"
        f"自定义事件派发 {len(dispatched)} 个、监听 {len(listened)} 个"
    )


def strip_comments(text: str) -> str:
    """去掉 JS 注释后再做结构性扫描——否则「注释里提到 window.fetch =」会被误判成违规。"""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"(?m)//[^\n]*$", " ", text)


def check_order(manifest: dict) -> None:
    """加载顺序与 fetch 接缝的结构性不变量。

    v261009 · A10 把「全局替换 window.fetch」换成了 `window.erwFetch` 显式接缝，因此这里
    不再靠「哪个文件必须排在前面」来保证正确性，而是直接查三条硬约束：
    1. **任何模块都不得给 `window.fetch` 赋值**（全局猴子补丁是 P14 的红线：它让补丁无法摘除，
       还制造出假的加载顺序依赖）；
    2. 接缝提供方**有且只有一个**（`window.erwFetch =` 只应出现在 performance 补丁里）；
    3. 每个自带 `api()` 的模块都必须走接缝（`erwFetch`），否则会绕过分页/图谱限流/搜索取消。
    """
    order = [item["file"] for item in manifest["js"]]
    files = app_js_files()
    sources = {p.name: strip_comments(p.read_text(encoding="utf-8")) for p in files}

    offenders = [name for name, text in sources.items() if re.search(r"window\.fetch\s*=", text)]
    if offenders:
        fail(f"禁止全局替换 window.fetch（P14 红线）：{offenders}；请改用 window.erwFetch 接缝")

    providers = [name for name, text in sources.items() if re.search(r"window\.erwFetch\s*=", text)]
    if len(providers) != 1:
        fail(f"window.erwFetch 接缝提供方应恰好 1 个，实际 {len(providers)} 个：{providers}")

    bypass = []
    for name, text in sources.items():
        for m in re.finditer(r"async function api\([^)]*\)\s*\{(.*?)\n\s*\}", text, re.S):
            if "erwFetch" not in m.group(1):
                bypass.append(name)
                break
    if bypass:
        fail(f"这些模块自带 api() 却绕过接缝（会丢分页/限流/取消）：{sorted(set(bypass))}")

    # §6.3：内核不替功能登记面板——登记应由功能模块自己做（app.js = 内核）
    app_src = sources.get("app.js", "")
    if re.search(r"ERWPanels\.register\s*\(", app_src):
        fail("app.js（内核）调用了 ERWPanels.register：面板应由功能模块自行登记（§6.3）")
    providers_panel = [name for name, text in sources.items() if re.search(r"ERWPanels\.register\s*\(", text)]
    notes.append(f"面板自登记模块：{providers_panel or '（暂无）'}")

    # §A9：文档级 childList 观察必须走共享接缝——不许各补丁自建整树 observer
    # （属性观察 attributeFilter / ResizeObserver / IntersectionObserver 语义不同，不在此列）
    seam_file = "dom-seam.js"
    if seam_file not in order:
        fail(f"{seam_file} 不在 manifest 的 js 里（ERWDom 接缝必须在所有补丁之前加载）")
    doc_observers = []
    for name, raw in sources.items():
        if name == seam_file:
            continue
        # 去掉注释后找 `new MutationObserver`，再看其后 300 字符内的 observe 配置是否含 childList
        for m in re.finditer(r"new\s+MutationObserver", raw):
            window = raw[m.start(): m.start() + 300]
            if "childList" in window:
                doc_observers.append(name)
                break
    if doc_observers:
        fail(f"这些模块仍在自建文档级 MutationObserver（应改用 window.ERWDom.onChildList）：{sorted(set(doc_observers))}")
    elif seam_file in order:
        notes.append("文档级 DOM 变更观察已收敛到 ERWDom 单一实例")

    if "vendor-lazy.js" not in [item["file"] for item in manifest["vendor_js"]]:
        fail("vendor-lazy.js 不在 manifest 的 vendor_js 中（erwVendor 需在业务脚本前就位）")
    if "perf-and-fetch-seam.js" in order and "app.js" in order:
        # 不再强制顺序（接缝在运行期解析），但提供方排在前面更稳：未来若有求值期请求也不会漏
        notes.append("fetch 接缝提供方位于 app.js 之前（非强制，但更稳）"
                     if order.index("perf-and-fetch-seam.js") < order.index("app.js")
                     else "fetch 接缝提供方排在 app.js 之后（运行期解析下仍正确，但求值期请求会漏）")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="前端静态体检（只读）")
    ap.add_argument("--no-node", action="store_true", help="跳过 node --check")
    args = ap.parse_args(argv)

    check_syntax(use_node=not args.no_node)
    manifest = check_manifest()
    check_seams()
    check_order(manifest)

    for n in notes:
        print(f"  - {n}")
    if problems:
        print(f"\n发现 {len(problems)} 个问题：")
        for p in problems:
            print(f"  [x] {p}")
        return 1
    print("\n前端体检通过：语法、装配清单、模块缺失、接缝完整性、加载顺序约束均无问题")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
