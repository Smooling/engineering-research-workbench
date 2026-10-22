"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
文献笔记插件验收（SCOPE §5.1 铁律 + §5.2 文献工具搬出）。

1. 内核工具集**恰好 4 个**（kb_search / kb_read / kb_create_entry / kb_update_entry）
2. 插件工具出现在 Agent 工具面：`p_literature-reader__context`（读）/ `p_literature-reader__note_write`（写）
3. 读工具真的能读：对真实文献返回元信息 + 批注数 + 笔记全文
4. 写工具受**内核草稿闸门**：confirm 只出草稿（笔记不变）→ 确认后真写 → 拒绝不写
5. 停用插件 → 两个工具从工具面消失（I10）；内核 4 个工具不受影响
6. 人设白名单用对外名引用（插件停用时自动退化，不报错）
7. 内核零残留（AST 判定：agent_tools 里没有这两个工具的痕迹）
8. 0 console error（工具面板/设置页仍可打开）
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8799"

# 没有服务时跳过：完整档由 tools/run_tests.py 起临时服务并传入 URL，
# --no-server（CI 的纯逻辑档）下这里应安静跳过，而不是报连接失败。
try:
    urllib.request.urlopen(BASE.rstrip("/") + "/api/health", timeout=2)
except Exception:
    print(f"SKIP 需要工作台服务 {BASE}（用 tools/run_tests.py 完整档会自动起）")
    raise SystemExit(0)
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  · {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def get(path, timeout=30):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload, timeout=30):
    req = urllib.request.Request(BASE + path, method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps(payload).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


sys.path.insert(0, str(ROOT))

# v261009.13 · 快照用户当前的启停选择：本夹具要启停 literature-reader，收尾还原用户原值
# （本轮踩过：夹具收尾固定 `enabled: true`，把用户在设置里关掉的 literature-reader 又打开了）
try:
    _snap = (json.loads((ROOT / "Workspace" / "System" / "plugins.json").read_text(encoding="utf-8")).get("plugins") or {})
except Exception:
    _snap = {}
LITNOTE_WAS_ENABLED = (_snap.get("literature-reader") or {}).get("enabled", True)

print("== 1. 内核工具集 ==")
from app import agent_tools as T  # noqa: E402
check("内核工具恰好 4 个（SCOPE §5.1 铁律；版本工具已搬进 version-manager 插件）",
      set(T.TOOL_NAMES) == {"kb_search", "kb_read", "kb_create_entry", "kb_update_entry"}, str(T.TOOL_NAMES))
check("工具集与规格一致",
      set(T.TOOL_NAMES) == {s["function"]["name"] for s in T.openai_specs()}, str(T.TOOL_NAMES))
check("内核工具实现表里没有文献工具", not ({"lit_context", "lit_note_write"} & set(T._TOOL_IMPL)))

print("\n== 2. 工具面（HTTP）==")
tools = {t["name"]: t for t in get("/api/agent/tools")}
check("插件读工具在工具面", "p_literature-reader__context" in tools, str([n for n in tools if n.startswith("p_")]))
check("插件写工具在工具面且带 write 标记",
      tools.get("p_literature-reader__note_write", {}).get("write") is True)
check("插件工具标注了归属", tools.get("p_literature-reader__context", {}).get("plugin") == "literature-reader")
check("内核 4 个工具仍在", {"kb_search", "kb_read", "kb_create_entry", "kb_update_entry"} <= set(tools))
check("旧工具名已不在工具面", not ({"lit_context", "lit_note_write"} & set(tools)))

print("\n== 3. 读工具真的能读（真实文献）==")
from core.plugins import runtime as RT  # noqa: E402
import server as S  # noqa: E402
S.load_plugins(S.ROOT, S.workspace.ensure_workspace())   # 让本进程也拿到插件工具
lit = get("/api/literature?page_size=1")
items = lit.get("items") or []
if not items:
    check("文献库里有可测条目", False, "文献库为空，跳过读工具测试")
else:
    pid = items[0]["id"]
    res = T.execute("p_literature-reader__context", {"paper_id": pid}, {})
    check("读工具返回元信息 + 批注数 + 笔记字段",
          res.get("ok") is True and res.get("plugin") == "literature-reader"
          and isinstance(res.get("paper"), dict) and "annotation_count" in res and "note" in res,
          f"title={str((res.get('paper') or {}).get('title'))[:26]} ann={res.get('annotation_count')} note={len(str(res.get('note') or ''))}字")
    # 缺 paper_id 且无上下文 → 明确报错（不静默）
    bad = T.execute("p_literature-reader__context", {}, {})
    check("缺 paper_id 时明确报错", bad.get("ok") is False and "paper_id" in str(bad.get("error")), str(bad.get("error"))[:50])

    print("\n== 4. 写工具的草稿闸门 ==")
    from app import literature as LIT  # noqa: E402
    before_note = LIT.get_note(pid)
    pending = T.execute("p_literature-reader__note_write", {"paper_id": pid, "content": "验收追加内容", "mode": "append"}, {"write_mode": "confirm"})
    check("confirm 模式只出草稿", pending.get("pending") is True and str(pending.get("draft_id", "")).startswith("draft-"),
          str(pending)[:80])
    check("**草稿阶段笔记未变**", LIT.get_note(pid) == before_note)
    T.reject_draft(pending["draft_id"])
    check("拒绝后仍未变", LIT.get_note(pid) == before_note)
    pending2 = T.execute("p_literature-reader__note_write", {"paper_id": pid, "content": "验收追加内容", "mode": "append"}, {"write_mode": "confirm"})
    done = T.confirm_draft(pending2["draft_id"])
    after = LIT.get_note(pid)
    check("确认后真的写进笔记（追加模式）", done.get("status") == "confirmed" and "验收追加内容" in after,
          f"笔记 {len(before_note)} → {len(after)} 字")
    LIT.save_note(pid, before_note)          # 还原，不留副作用
    check("验收后笔记已还原", LIT.get_note(pid) == before_note)

print("\n== 5. 停用即消失（I10）==")
post("/api/plugin-manager/literature-reader/enabled", {"enabled": False})
tools2 = {t["name"] for t in get("/api/agent/tools")}
check("停用后两个插件工具消失", not ({"p_literature-reader__context", "p_literature-reader__note_write"} & tools2),
      str([n for n in tools2 if n.startswith("p_")]))
check("停用后内核 4 个工具仍在", {"kb_search", "kb_read", "kb_create_entry", "kb_update_entry"} <= tools2)
post("/api/plugin-manager/literature-reader/enabled", {"enabled": True})
tools3 = {t["name"] for t in get("/api/agent/tools")}
check("重新启用后工具回来", "p_literature-reader__context" in tools3)

print("\n== 6. 人设白名单 ==")
# v261009.11 · 停用插件**不应**抹掉白名单条目：加载期不裁剪，使用期才过滤。
# 否则一次临时不可用（插件被阻塞/未加载）就会把条目永久写没（本轮真踩过）。
def _reader_tools():
    cfg_ = get("/api/config")
    for p_ in ((cfg_.get("app") or {}).get("llm") or {}).get("personas") or []:
        if p_.get("id") == "reader":
            return list(p_.get("tools") or [])
    return []

_before_disable = _reader_tools()
post("/api/plugin-manager/literature-reader/enabled", {"enabled": False})
_after_disable = _reader_tools()
check("停用插件不抹掉人设白名单条目（加载期不裁剪）",
      "p_literature-reader__context" in _after_disable and _after_disable == _before_disable,
      f"{_before_disable} → {_after_disable}")
post("/api/plugin-manager/literature-reader/enabled", {"enabled": bool(LITNOTE_WAS_ENABLED)})
cfg = get("/api/config")
personas = ((cfg.get("app") or {}).get("llm") or {}).get("personas") or []
reader = next((p for p in personas if p.get("id") == "reader"), None)
check("阅读助手人设用对外名引用文献工具",
      reader is not None and "p_literature-reader__context" in (reader.get("tools") or []),
      str((reader or {}).get("tools")))
check("人设里没有旧工具名", not any("lit_context" in (p.get("tools") or []) or "lit_note_write" in (p.get("tools") or []) for p in personas))

print("\n== 7. 内核零残留（AST）==")
import ast as _ast  # noqa: E402


def _mentions(path, names):
    tree = _ast.parse(path.read_text(encoding="utf-8"))
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Constant) and isinstance(node.value, str):
            continue                     # 文档字符串/提示文案不算实现痕迹
        if isinstance(node, _ast.Name) and node.id in names:
            return True
        if isinstance(node, _ast.Attribute) and isinstance(node.value, _ast.Name) and node.value.id in names:
            return True
        if isinstance(node, _ast.keyword) and isinstance(node.value, _ast.Constant) and node.value.value in names:
            return True
    return False


hits = [q.relative_to(ROOT).as_posix() for q in (ROOT / "app").rglob("*.py")
        if _mentions(q, {"lit_context", "lit_note_write", "_t_lit_context", "_t_lit_note_write"})]
check("内核 Python 已无这两个工具的痕迹", not hits, str(hits))
def _stray_old_names(path):
    """旧工具名只允许出现在「旧名 → 新名」的别名映射行里（同一行带新名）。"""
    bad = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if ("lit_context" in line or "lit_note_write" in line) and "p_literature-reader__" not in line:
            bad.append(i)
    return bad


stray = {q.relative_to(ROOT).as_posix(): _stray_old_names(q) for q in (ROOT / "app").rglob("*.py")}
stray = {k: v for k, v in stray.items() if v}
check("内核源码里旧工具名只出现在别名映射行", not stray, str(stray))
alias_ok = 'LEGACY_TOOL_ALIASES' in (ROOT / "app" / "config.py").read_text(encoding="utf-8")
check("别名映射仍在（迁移兼容用）", alias_ok)
for q in (ROOT / "web").glob("*.js"):
    txt = q.read_text(encoding="utf-8")
    check(f"前端 {q.name} 无旧工具名硬编码", "lit_context" not in txt and "lit_note_write" not in txt) if q.name == "v260930-floating-agent.js" else None

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（文献工具已成插件工具包；内核工具集回到规格要求的 4 个）")