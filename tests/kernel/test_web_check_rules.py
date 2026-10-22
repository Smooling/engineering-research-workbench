"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
负向验证：web_check 的新不变量真的能抓到违规（用合成文本，不改真实文件）。"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import web_check as W  # noqa: E402

CASES = [
    ("代码里给 window.fetch 赋值", "window.fetch = async function(){};", True),
    ("注释里提到 window.fetch =", "/* 原先这里是 window.fetch = ... */", False),
    ("行注释里提到 window.fetch =", "// window.fetch = x", False),
    ("字符串里出现（保守起见仍算违规）", "const s = 'window.fetch = x';", True),
    ("正常接缝消费", "const r = await (window.erwFetch||fetch)(u,i);", False),
]
FAILS = []
for name, text, want in CASES:
    got = bool(re.search(r"window\.fetch\s*=", W.strip_comments(text)))
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}：检测={got} 期望={want}")
    if not ok:
        FAILS.append(name)

# 提供方计数：只有赋值才算提供方
provider_src = "window.erwFetch = perfFetch;"
consumer_src = "const r = await (window.erwFetch||fetch)(u,i);"
got = bool(re.search(r"window\.erwFetch\s*=", provider_src)), bool(re.search(r"window\.erwFetch\s*=", consumer_src))
ok = got == (True, False)
print(("PASS " if ok else "FAIL ") + f"提供方计数：赋值={got[0]} 消费={got[1]}（消费不应计为提供方）")
if not ok:
    FAILS.append("提供方计数")

# 绕过接缝的 api() 必须被抓到
bypass_src = "async function api(url,opts={}){\n  const r=await fetch(url,opts);\n  return r;\n}\n"
seam_src = "async function api(url,opts={}){\n  const r=await (window.erwFetch||fetch)(url,opts);\n  return r;\n}\n"


def api_bypass(text):
    for m in re.finditer(r"async function api\([^)]*\)\s*\{(.*?)\n\s*\}", text, re.S):
        if "erwFetch" not in m.group(1):
            return True
    return False


ok = api_bypass(bypass_src) and not api_bypass(seam_src)
print(("PASS " if ok else "FAIL ") + f"api() 绕过检测：绕过={api_bypass(bypass_src)} 接缝={api_bypass(seam_src)}")
if not ok:
    FAILS.append("api() 绕过检测")

print()
print("结果：全部符合预期" if not FAILS else f"结果：{FAILS}")
raise SystemExit(1 if FAILS else 0)
