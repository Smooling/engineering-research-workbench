"""夹具：外部接入授权（谁能改知识库）。

覆盖：
① 默认状态：MCP 写入**拒绝**、插件写入允许；
② `/api/external-access` 读写：授权/撤销/未知键忽略；
③ **MCP 写工具闸门**：未授权时被拦（返回未授权文案，且**不产生任何写入**）；
   授权后用**非法载荷**证明"闸门确实放行"（错误变成参数错误，而不是未授权）——全程不写数据；
④ **插件写入门面**：plugin_write=false 时 `core_api.entry_update` 抛 PermissionError（不写数据）；
⑤ 真浏览器：设置里出现「外部接入」tab，开关能改状态并回显；
⑥ 收尾：把授权状态按原样还原（不留下"已授权"）。

用法：`python tests/kernel/test_external_access.py [工作台URL]`
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "support"))

CFG = ROOT / "config" / "external-access.json"
PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def request(url: str, path: str, payload: dict | None = None, timeout: int = 30):
    if payload is None:
        req = urllib.request.Request(url + path)
    else:
        req = urllib.request.Request(url + path, method="POST",
                                     headers={"Content-Type": "application/json"},
                                     data=json.dumps(payload).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    saved = CFG.read_bytes() if CFG.is_file() else None
    httpd = None
    base = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("http") else ""
    try:
        if not base:
            os.environ.setdefault("ERW_PLUGINS_ROOTS", str(ROOT / "plugins"))
            import server

            httpd, _c, url = server.build_server(port_override=free_port(), auto_open_browser=False)
            threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
            base = url
            for _ in range(60):
                try:
                    request(base, "/api/external-access")
                    break
                except Exception:
                    time.sleep(0.25)

        print("① 默认状态（保守）")
        state = request(base, "/api/external-access")
        check("①-1 默认 MCP 写入为关闭", state["flags"]["mcp_write"] is False, str(state["flags"]))
        check("①-2 默认插件写入为开启（不改变既有行为）", state["flags"]["plugin_write"] is True)
        check("①-3 返回了文案与风险提示（设置页直接用）",
              all(i.get("label") and i.get("detail") and i.get("risk") for i in state["items"]))

        print("② 读写授权接口")
        out = request(base, "/api/external-access", {"mcp_write": True})
        check("②-1 授权生效并回报变更", out["flags"]["mcp_write"] is True and out["changed"],
              str(out.get("changed")))
        out = request(base, "/api/external-access", {"hack": True})
        check("②-2 未知键被忽略（不能借它塞东西）",
              out["changed"] == [] and "hack" not in json.loads(CFG.read_text(encoding="utf-8")))
        request(base, "/api/external-access", {"mcp_write": False})

        print("③ MCP 写工具闸门")
        from mcp import server as M
        from mcp.bridge import Workbench

        wb = Workbench()

        def call(name, args):
            return M.handle_tools_call(wb, {"name": name, "arguments": args})

        denied = call("kb_create_entry", {"kind": "note", "title": "知识-方法-授权闸门测试"})
        text = json.dumps(denied, ensure_ascii=False)
        check("③-1 未授权时写工具被拦（含未授权文案）",
              denied.get("isError") is True and "未授权" in text, text[:160])
        check("③-2 只读工具不受影响", not call("kb_constraints", {"topic": "storage"}).get("isError"))
        request(base, "/api/external-access", {"mcp_write": True})
        # 授权后用**非法载荷**：应变成参数错误（证明闸门放行），且不会写任何东西
        passed_gate = call("kb_create_entry", {"kind": "不存在的类型"})
        text2 = json.dumps(passed_gate, ensure_ascii=False)
        check("③-3 授权后闸门放行（错误变为参数错误，非未授权）",
              "未授权" not in text2 and "未知条目类型" in text2, text2[:160])
        request(base, "/api/external-access", {"mcp_write": False})

        print("④ 插件写入门面")
        import core_api

        request(base, "/api/external-access", {"plugin_write": False})
        try:
            core_api.entry_update("note-does-not-exist", body="x")
            blocked = None
        except PermissionError as exc:
            blocked = str(exc)
        except Exception as exc:  # 其他异常说明没被授权闸门拦住
            blocked = None
            print(f"    （其他异常：{type(exc).__name__}: {exc}）")
        check("④-1 plugin_write=false 时 entry_update 被拒（PermissionError）",
              blocked is not None and "未授权" in blocked, str(blocked))
        request(base, "/api/external-access", {"plugin_write": True})
        try:
            core_api.entry_update("note-does-not-exist", body="x")
            after = "未抛错"
        except PermissionError as exc:
            after = f"仍被拒：{exc}"
        except FileNotFoundError:
            after = "FileNotFoundError（说明已放行到「条目不存在」这一步）"
        except Exception as exc:
            after = f"{type(exc).__name__}"
        check("④-2 恢复授权后放行（走到「条目不存在」，未写数据）", "FileNotFoundError" in after, after)

        print("⑤ 真浏览器：设置里的「外部接入」")
        for name, ok, detail in browser_checks(base):
            check(name, ok, detail)
    finally:
        if saved is None:
            CFG.unlink(missing_ok=True)
        else:
            CFG.write_bytes(saved)
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        os.environ.pop("ERW_PLUGINS_ROOTS", None)
        from core.plugins import jobs as plugin_jobs

        plugin_jobs.shutdown()

    print("⑥ 收尾")
    check("⑥-1 授权状态按原样还原",
          (CFG.read_bytes() if CFG.is_file() else None) == saved,
          f"now={CFG.read_text(encoding='utf-8') if CFG.is_file() else None}")
    total = len(PASS) + len(FAIL)
    print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


def browser_checks(base: str) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [("⑤-0 playwright 可用", False, "pip install playwright")]
    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe if Path(exe).is_file() else None, headless=True)
        page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        errs: list[str] = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.goto(f"{base}/#settings", wait_until="networkidle", timeout=60000)
        page.wait_for_selector("#settings-panel", timeout=30000)
        page.wait_for_timeout(800)
        tab = page.query_selector('[data-set-tab="external-access"]')
        out.append(("⑤-1 设置里出现「外部接入」tab", tab is not None, ""))
        if tab:
            tab.click()
            page.wait_for_selector("[data-ea-flag]", timeout=20000)
            page.wait_for_timeout(800)
            labels = page.eval_on_selector_all("[data-ea-flag]", "els => els.map(e => e.dataset.eaFlag)")
            out.append(("⑤-2 两个开关都在（MCP / 插件）",
                        set(labels) == {"mcp_write", "plugin_write"}, str(labels)))
            chips = page.eval_on_selector_all(".ea-chip", "els => els.map(e => e.textContent.trim())")
            out.append(("⑤-3 状态 chip 如实显示",
                        any("只读" in c for c in chips) and any("已授权" in c for c in chips), str(chips)))
            box = page.query_selector('[data-ea-flag="mcp_write"]')
            box.click()
            page.wait_for_timeout(1200)
            state = json.loads((ROOT / "config" / "external-access.json").read_text(encoding="utf-8")) \
                if (ROOT / "config" / "external-access.json").is_file() else {}
            out.append(("⑤-4 勾选开关真的写进了配置", state.get("mcp_write") is True, str(state)))
            page.wait_for_timeout(400)
            chips2 = page.eval_on_selector_all(".ea-chip", "els => els.map(e => e.textContent.trim())")
            out.append(("⑤-5 界面回显已授权", any("已授权" in c for c in chips2), str(chips2)))
            page.query_selector('[data-ea-flag="mcp_write"]').click()   # 还原
            page.wait_for_timeout(900)
        out.append(("⑤-6 0 console error", not errs, str(errs[:3])))
        browser.close()
    return out


if __name__ == "__main__":
    raise SystemExit(main())
