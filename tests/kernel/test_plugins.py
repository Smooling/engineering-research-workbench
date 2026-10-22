"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
插件契约验收：用夹具覆盖 manifest 校验 + 发现 + 依赖 + 冲突 + 环。

全部在 .scratch/verify/plugins-fixtures/ 下自造，不碰真实 plugins/。
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.plugins import manifest as M  # noqa: E402
from core.plugins import registry as R  # noqa: E402

BASE = ROOT / ".scratch" / "verify" / "plugins-fixtures"
BUNDLED = BASE / "bundled"
USER = BASE / "user"
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  · {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def write_plugin(root: Path, pid: str, manifest: dict, *, files: dict | None = None) -> None:
    d = root / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for rel, content in (files or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def base_manifest(pid: str, **over) -> dict:
    m = {
        "id": pid, "name": pid, "version": "1.0.0", "api_version": 1,
        "kind": "inprocess", "distribution": "optional", "default_enabled": False,
    }
    m.update(over)
    return m


if BASE.exists():
    shutil.rmtree(BASE)
BUNDLED.mkdir(parents=True)
USER.mkdir(parents=True)

# ---- 合法：随包插件（带面板 + 路由 + 工具 + 权限 + 后端入口）----
write_plugin(BUNDLED, "weather", base_manifest(
    "weather", name="天气", distribution="bundled", default_enabled=True,
    entry="backend.py", permissions=["net:http", "storage:own", "config:own", "ui:panel"],
    nav=[{"id": "weather", "label": "天气", "mount": "web/panel.js"}],
    routes=[{"method": "GET", "path": "forecast"}],
    mcp_tools=["weather_now"],
    settings_schema={"type": "object", "properties": {"city": {"type": "string"}}},
    storage={"derived_db": "System/Cache/weather.sqlite"},
), files={"backend.py": "def register(ctx):\n    pass\n", "web/panel.js": "export function mount(ctx){}\n"})

# ---- 合法：前提插件 ----
write_plugin(BUNDLED, "literature-base", base_manifest(
    "literature-base", name="文献基础", distribution="bundled", default_enabled=True,
    provides=["literature-base"],
))

# ---- 合法：依赖前提插件（应 available，且加载顺序在前）----
write_plugin(USER, "reader-ai", base_manifest(
    "reader-ai", name="阅读区 AI", requires={"plugins": [{"id": "literature-base", "version": ">=1.0,<2"}]},
))

# ---- 拒绝：id 不合法 + 目录名与 id 不一致 ----
write_plugin(USER, "BadId", base_manifest("BadId"))

# ---- 拒绝：api_version 不匹配 ----
write_plugin(USER, "bad-api", base_manifest("bad-api", api_version=99))

# ---- 拒绝：路由写成裸 /api ----
write_plugin(USER, "bad-route", base_manifest("bad-route", routes=[{"method": "GET", "path": "/api/weather/x"}]))

# ---- 拒绝：工具名自带前缀 ----
write_plugin(USER, "bad-tool", base_manifest("bad-tool", mcp_tools=["p_bad-tool__x"]))

# ---- 拒绝：未支持的权限 ----
write_plugin(USER, "bad-perm", base_manifest("bad-perm", permissions=["net:ftp"]))

# ---- 拒绝：派生库路径不合规 ----
write_plugin(USER, "bad-db", base_manifest("bad-db", storage={"derived_db": "System/Cache/other.sqlite"}))

# ---- 拒绝：core_min 高于当前内核 ----
write_plugin(USER, "future-core", base_manifest("future-core", core_min="v999999"))

# ---- 拒绝：entry 指向不存在的文件 ----
write_plugin(USER, "missing-entry", base_manifest("missing-entry", entry="backend.py"))

# ---- blocked：依赖不存在的插件 ----
write_plugin(USER, "needs-ghost", base_manifest("needs-ghost", requires={"plugins": [{"id": "ghost"}]}))

# ---- blocked：依赖成环 ----
write_plugin(USER, "cycle-a", base_manifest("cycle-a", requires={"plugins": [{"id": "cycle-b"}]}))
write_plugin(USER, "cycle-b", base_manifest("cycle-b", requires={"plugins": [{"id": "cycle-a"}]}))

# ---- 冲突：同 id 出现在两个来源（ASSET 优先）----
write_plugin(USER, "dup", base_manifest("dup", version="0.9.0"))
write_plugin(BUNDLED, "dup", base_manifest("dup", version="1.2.0", distribution="bundled"))

report = R.report(roots=[("bundled", BUNDLED), ("user", USER)], workspace=None, core_version="v261009.0")
states = {r["id"]: r["state"] for r in report["plugins"]}
print("发现状态：", json.dumps(states, ensure_ascii=False))
print()

check("合法插件 available", states.get("weather") == "available" and states.get("literature-base") == "available")
check("满足依赖的插件 available", states.get("reader-ai") == "available", str(states.get("reader-ai")))
check("id 不合法被拒", states.get("BadId") == "rejected")
check("api_version 不匹配被拒", states.get("bad-api") == "rejected")
check("裸 /api 路由被拒", states.get("bad-route") == "rejected")
check("自带前缀的工具名被拒", states.get("bad-tool") == "rejected")
check("未支持权限被拒", states.get("bad-perm") == "rejected")
check("派生库路径不合规被拒", states.get("bad-db") == "rejected")
check("core_min 高于内核被拒", states.get("future-core") == "rejected")
check("entry 文件缺失被拒", states.get("missing-entry") == "rejected")
check("依赖缺失 → blocked", states.get("needs-ghost") == "blocked")
check("依赖成环 → 整环 blocked", states.get("cycle-a") == "blocked" and states.get("cycle-b") == "blocked")
_dup_version = next(r for r in report["plugins"] if r["id"] == "dup")["version"]
check("同 id 双来源按 ASSET 优先（保留 1.2.0）", _dup_version == "1.2.0", _dup_version)
check("优先提示可见", any("dup" in n for n in report["notes"]), str(report["notes"])[:70])
order = report["load_order"]
check("加载顺序把前提插件排在前面",
      order.index("literature-base") < order.index("reader-ai") if {"literature-base", "reader-ai"} <= set(order) else False,
      str(order))
check("被拒/被阻的插件不进加载顺序",
      not any(p in order for p in ("bad-api", "needs-ghost", "cycle-a", "bad-route")), str(order))

# 具体错误码抽查
by_id = {r["id"]: r for r in report["plugins"]}
codes = {i["code"] for i in by_id["bad-route"]["issues"]}
check("PV011 路由规则给出 P011", "P011" in codes, str(sorted(codes)))
check("blocked 项带可执行修复建议", bool(by_id["needs-ghost"]["fix"]), by_id["needs-ghost"]["fix"])
check("rejected 项带原因", bool(by_id["bad-api"]["reason"]), by_id["bad-api"]["reason"][:60])

# 汇总计数
check("汇总计数自洽",
      report["available"] == 4 and report["rejected"] == 8 and report["blocked"] == 3,
      f"available={report['available']} rejected={report['rejected']} blocked={report['blocked']} conflict={report['conflict']}")

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过（manifest 契约 + 发现 + 依赖 + 冲突 + 环）")
