"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
负向验证：web_check 的「文档级 observer 必须走 ERWDom」不变量真的能抓到违规。"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import web_check as W  # noqa: E402

CASES = [
    ("自建文档级 childList observer",
     'const o=new MutationObserver(()=>{});o.observe(document.body,{childList:true,subtree:true});', True),
    ("自建 observer 观察 #main",
     'new MutationObserver(schedule).observe(main,{childList:true,subtree:true})', True),
    ("仅属性观察（语义不同，不报）",
     'const o=new MutationObserver(cb);o.observe(card,{attributes:true,attributeFilter:["style"]});', False),
    ("走共享接缝",
     'window.ERWDom.onChildList(schedule,{root:"#main"});', False),
    ("注释里提到 new MutationObserver",
     '/* 原先 new MutationObserver(cb).observe(body,{childList:true}) */', False),
]

fails = []
for name, src, want in CASES:
    text = W.strip_comments(src)
    hit = False
    for m in re.finditer(r"new\s+MutationObserver", text):
        if "childList" in text[m.start(): m.start() + 300]:
            hit = True
            break
    ok = hit == want
    print(("PASS " if ok else "FAIL ") + f"{name}：检出={hit} 期望={want}")
    if not ok:
        fails.append(name)

print()
print("结果：全部符合预期" if not fails else f"结果：{fails}")
raise SystemExit(1 if fails else 0)
