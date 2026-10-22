# -*- coding: utf-8 -*-
"""负向用例：把 `plugins/` 也纳入接缝来源之后，web_check 仍能抓出真正的「没人提供/没人派发」。

做法：注入两个假依赖（一个被消费但无人定义的 window.ERW*、一个被监听但无人派发的事件），
在临时目录里跑一遍 check_seams，必须报出这两条。
"""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools"))
import web_check as W  # noqa: E402

notes, problems = W.notes, W.problems
srcs = {p.name: p.read_text(encoding="utf-8") for p in W.app_js_files()}
srcs["__probe__.js"] = (
    "window.addEventListener('erw-nobody-dispatch', () => {});\n"
    "window.ERWGhostSeam;\n"
)

tmp = pathlib.Path(tempfile.mkdtemp())
for name, text in srcs.items():
    (tmp / name).write_text(text, encoding="utf-8")

orig_app, orig_root = W.app_js_files, W.ROOT
W.app_js_files = lambda: sorted(tmp.glob("*.js"))
W.notes, W.problems = [], []
W.check_seams()
collected = list(W.problems)          # 先抓住本轮收集到的问题，再还原模块状态
W.app_js_files, W.ROOT = orig_app, orig_root
W.notes, W.problems = notes, problems

hits = [p for p in collected if "ERWGhostSeam" in p or "erw-nobody-dispatch" in p]
print("注入假接缝后 problems 数 =", len(collected))
for p in collected:
    print("   -", p[:130])
print("\n负向用例结论：", "通过（两条假依赖都被抓出）" if len(hits) == 2 else f"失败（只抓到 {len(hits)} 条）")
sys.exit(0 if len(hits) == 2 else 1)
