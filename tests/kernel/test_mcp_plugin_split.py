"""夹具：MCP 工具按插件拆分——只暴露**已启用插件**的工具，且启停后即时生效。

完全隔离：workspace 指到临时目录（`System/plugins.json` 也在临时目录里），
因此**不动用户的插件开关**；只快照/还原仓库里的 `config/external-access.json`（授权文件）。

覆盖：
① 只启用 version-manager 时：它的工具在列表里，未启用插件（literature-reader）的工具**不在**；
② 改 plugins.json 启用 literature-reader → **不重启进程**，下次取目录就能看到它的工具（指纹感知）；
③ 停用后它的工具消失；
④ 调用插件工具能拿到结果（p_version-manager__versions → 版本族）；
⑤ 插件写工具受「外部接入」授权约束（未授权被拦，授权后放行到参数错误）；
⑥ 内核工具始终在（与插件无关）。

用法：`python tests/kernel/test_mcp_plugin_split.py`
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []
TEMP = Path(tempfile.mkdtemp(prefix="erwmcp-"))
AUTH = ROOT / "config" / "external-access.json"
_auth_before = AUTH.read_bytes() if AUTH.is_file() else None


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


#: 附属插件默认就是开的（manifest 的 default_enabled）——要"关"必须**显式**写 enabled:false，
#: 这是内核 `registry.effective_enabled` 的判定口径（只读 plugins.json 的 true 会误判）。
DEFAULT_ON = ["billing", "floating-assist", "focus", "knowledge-graph", "literature-reader",
              "rss", "version-manager", "weather"]


def set_enabled(ids: list[str]) -> None:
    """只让 `ids` 里的插件开：其余按内核口径显式写 False。"""
    path = TEMP / "System" / "plugins.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = {pid: {"enabled": pid in ids} for pid in DEFAULT_ON}
    for pid in ids:
        records.setdefault(pid, {"enabled": True})
    path.write_text(json.dumps({"schema_version": 1, "plugins": records}, ensure_ascii=False),
                    encoding="utf-8")


def names() -> list[str]:
    from mcp import server as S

    return [t["name"] for t in S.all_tools()]


def main() -> int:
    from app import config as C

    orig_app, orig_all = C.get_app, C.get_all
    _orig_root = C.workspace_root
    C.workspace_root = lambda: TEMP
    C.get_app = lambda: {**(orig_app() or {}), "workspace": str(TEMP)}
    C.get_all = lambda: {**(orig_all() or {}), "workspace": str(TEMP)}
    try:
        from app import external_access, store, versions, workspace
        from mcp import server as S
        from mcp.bridge import Workbench

        workspace.reset_runtime_state()
        wb = Workbench()

        print("① 只启用 version-manager")
        set_enabled(["version-manager"])
        first = names()
        check("①-1 已启用插件的工具在列表里",
              all(f"p_version-manager__{t}" in first for t in ("versions", "merge_versions", "archive_versions")),
              str([n for n in first if n.startswith("p_")]))
        check("①-2 未启用插件的工具**不在**列表里",
              not any(n.startswith("p_literature-reader__") for n in first),
              str([n for n in first if "literature" in n]))
        check("①-3 内核工具始终在（与插件无关）",
              all(n in first for n in ("kb_create_entry", "kb_variants", "ws_list_projects")),
              str(first[:6]))
        kernel_n = len(S.KB_TOOLS) + len(S.WS_TOOLS)   # 动态：内核工具增删不该让夹具变红
        # 插件工具数也从清单读：v261020.6 给 version-manager 加了 auto_merge_versions（3→4），
        # 写死 +3 会让夹具在功能正常演进时误报。
        vm_tools = json.loads((ROOT / "plugins" / "version-manager" / "plugin.json").read_text(encoding="utf-8")).get("mcp_tools") or []
        check("①-4 工具面 = 内核 + 已启用插件", len(first) == kernel_n + len(vm_tools),
              f"实际 {len(first)}（内核 {kernel_n} + 插件 {len(vm_tools)}）")

        print("② 启用另一个插件 → 不重启也能看到（指纹感知）")
        set_enabled(["version-manager", "literature-reader"])
        second = names()
        check("②-1 新启用插件的工具出现了",
              "p_literature-reader__context" in second and "p_literature-reader__note_write" in second,
              str([n for n in second if n.startswith("p_lit")]))

        print("③ 停用后工具消失")
        set_enabled(["version-manager"])
        third = names()
        check("③-1 停用的插件工具已消失",
              not any(n.startswith("p_literature-reader__") for n in third),
              str([n for n in third if n.startswith("p_lit")]))

        print("④ 调用插件工具")
        doc = store.create_doc("note", {"title": "知识-方法-MCP拆分测试", "body": "## 摘要\nA\n"},
                               origin=versions.origin("ui"))
        called = S.handle_tools_call(wb, {"name": "p_version-manager__versions",
                                          "arguments": {"doc_id": doc["id"]}})
        text = json.dumps(called, ensure_ascii=False)
        check("④-1 插件工具可调用并返回结果",
              called.get("isError") is not True and doc["id"] in text, text[:150])

        print("⑤ 插件写工具受外部接入授权约束")
        external_access.save({"mcp_write": False})
        denied = S.handle_tools_call(wb, {"name": "p_version-manager__merge_versions",
                                          "arguments": {"base_id": doc["id"], "picks": {}}})
        check("⑤-1 未授权时插件写工具被拦",
              denied.get("isError") is True and "未授权" in json.dumps(denied, ensure_ascii=False),
              json.dumps(denied, ensure_ascii=False)[:140])
        external_access.save({"mcp_write": True})
        allowed = S.handle_tools_call(wb, {"name": "p_version-manager__merge_versions",
                                           "arguments": {"base_id": doc["id"], "picks": {}}})
        allowed_text = json.dumps(allowed, ensure_ascii=False)
        check("⑤-2 授权后放行（走到正常返回，不再是未授权）",
              "未授权" not in allowed_text and allowed.get("isError") is not True, allowed_text[:150])

        print("⑥ 未知插件工具名")
        from mcp.protocol import RpcError

        try:
            S.handle_tools_call(wb, {"name": "p_not-enabled__whatever", "arguments": {}})
            unknown_msg = "（未抛错）"
        except RpcError as exc:                       # JSON-RPC 层正确行为：报"未知工具"
            unknown_msg = str(exc)
        check("⑥-1 未启用/不存在插件工具 → 明确报未知工具",
              "未知工具" in unknown_msg, unknown_msg[:120])
    finally:
        C.get_app, C.get_all = orig_app, orig_all
        C.workspace_root = _orig_root
        if _auth_before is None:
            AUTH.unlink(missing_ok=True)
        else:
            AUTH.write_bytes(_auth_before)
        try:
            from app import workspace as W

            W.reset_runtime_state()
        except Exception:
            pass
        try:
            from core.plugins import jobs as plugin_jobs

            plugin_jobs.shutdown()
        except Exception:
            pass
        shutil.rmtree(TEMP, ignore_errors=True)

    check("⑦ 授权文件已还原", (AUTH.read_bytes() if AUTH.is_file() else None) == _auth_before)
    total = len(PASS) + len(FAIL)
    print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
