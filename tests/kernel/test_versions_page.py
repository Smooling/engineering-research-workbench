"""验证「版本管理」插件页：真浏览器里族列表 / 详情 / 小节挑内容 / 合并 / 归档 / 取回。

在**隔离工作区**里造数据（monkeypatch config），再用真服务器 + 真浏览器走一遍，
不碰真实知识库。用法：`python tests/kernel/test_versions_page.py [工作台URL]`
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []
TEMP = Path(tempfile.mkdtemp(prefix="erwverpage-"))


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get(url: str):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def post(url: str, payload: dict):
    req = urllib.request.Request(url, method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps(payload).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    from app import config as C

    orig_app, orig_all = C.get_app, C.get_all

    def fake_app():
        cfg = dict(orig_app() or {})
        cfg["workspace"] = str(TEMP)
        return cfg

    def fake_all():
        data = dict(orig_all() or {})
        data["workspace"] = str(TEMP)
        return data

    C.get_app, C.get_all = fake_app, fake_all
    httpd = None
    try:
        from app import store, versions, workspace

        workspace.reset_runtime_state()
        base = store.create_doc("note", {"title": "知识-方法-页面测试",
                                         "body": "## 摘要\n基线摘要\n\n## 方法\n基线方法\n"},
                                origin=versions.origin("ui", "doc_save"))
        v2 = store.create_doc("note", {"title": "知识-方法-页面测试（v2）",
                                       "body": "## 摘要\nMCP 摘要\n\n## 方法\nMCP 方法\n"},
                              origin=versions.origin("mcp", "kb_create_entry", "Claude Desktop"))

        import server

        httpd, _c, url = server.build_server(port_override=free_port(), auto_open_browser=False)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
        for _ in range(60):
            try:
                get(f"{url}/api/plugins/version-manager/overview")
                break
            except Exception:
                time.sleep(0.25)

        print("① HTTP 接口")
        overview = get(f"{url}/api/plugins/version-manager/overview")
        check("①-1 总览里有 1 个族、1 个分叉", overview["counts"]["families"] == 1
              and overview["counts"]["forked"] == 1, str(overview["counts"]))
        detail = get(f"{url}/api/plugins/version-manager/family?id={base['id']}")
        check("①-2 详情含基条 + 1 个版本 + 小节清单",
              detail["base"]["id"] == base["id"] and len(detail["variants"]) == 1
              and "摘要" in detail["sections"], str(detail["sections"]))
        check("①-3 详情里能看到 MCP 来源",
              "MCP" in (detail["variants"][0]["origin"] or ""), detail["variants"][0]["origin"])

        print("② 真浏览器：插件页面与操作")
        for name, ok, text in browser_checks(url, base, v2):
            check(name, ok, text)
    finally:
        C.get_app, C.get_all = orig_app, orig_all
        try:
            from app import workspace as W

            W.reset_runtime_state()
        except Exception:
            pass
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        from core.plugins import jobs as plugin_jobs

        plugin_jobs.shutdown()
        shutil.rmtree(TEMP, ignore_errors=True)

    total = len(PASS) + len(FAIL)
    print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


def browser_checks(url: str, base: dict, v2: dict):
    out = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [("②-0 playwright 可用", False, "pip install playwright")]
    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe if Path(exe).is_file() else None, headless=True)
        page = browser.new_context(viewport={"width": 1500, "height": 950}).new_page()
        errs = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.goto(f"{url}/#version-manager", wait_until="networkidle", timeout=60000)
        page.wait_for_selector(".vm-item", timeout=30000)
        page.wait_for_timeout(800)
        out.append(("②-1 侧栏出现「版本」导航项",
                    page.eval_on_selector_all("[data-route]", "els => els.some(e => e.dataset.route === 'version-manager')"), ""))
        page.click(".vm-item")
        page.wait_for_selector("#vm-merge", timeout=20000)
        page.wait_for_timeout(600)
        out.append(("②-2 族详情渲染出各版本与来源",
                    page.eval_on_selector_all(".vm-vrow", "els => els.length") >= 1
                    and page.eval_on_selector_all(".vm-origin", "els => els.length") >= 2, ""))
        sections = page.eval_on_selector_all(
            "[data-vm-pick], [data-vm-accept]",
            "els => els.map(e => e.dataset.vmPick || e.dataset.vmAccept)")
        out.append(("②-3 小节可挑来源", set(sections) >= {"摘要", "方法"}, str(sections)))
        # 变更对照：改动行徽章 + 差异内联展开（v261009.54 起不用再点「看变更」）
        need_badges = page.eval_on_selector_all(
            ".vm-need .vm-sbadge", "els => els.map(e => e.textContent.trim())")
        diff_lines = page.eval_on_selector_all(
            ".vm-need .vm-dline", "els => els.map(e => e.className)")
        out.append(("②-9 只有改动的小节列出并带徽章",
                    bool(need_badges) and all("一致" not in b for b in need_badges), str(need_badges)))
        out.append(("②-10 差异直接内联展开（无需点击）",
                    any("add" in c or "del" in c for c in diff_lines), str(diff_lines[:3])))
        same_controls = page.eval_on_selector_all(
            ".vm-same-row [data-vm-pick], .vm-same-row [data-vm-accept]", "els => els.length")
        out.append(("②-11 一致的小节没有任何选择控件",
                    same_controls == 0, f"一致行里的控件={same_controls}"))
        # 选「摘要」用 v2，然后合并
        page.click('[data-vm-accept="摘要"]')   # 单版本时是「采用新版」按钮
        page.click("#vm-merge")
        page.wait_for_timeout(2500)
        body = page.evaluate("() => document.querySelector('#vm-pane') ? document.querySelector('#vm-pane').textContent : ''")
        out.append(("②-4 合并后页面刷新（含替换提示或新内容）", "已合并" in body or "MCP" in body, body[:80]))
        # 归档勾选
        # 修改记录：外部写入必须能在页面上看到来源
        page.wait_for_selector("#vm-history .vm-hrow", timeout=20000)
        hist = page.eval_on_selector_all("#vm-history .vm-hrow", "els => els.map(e => e.textContent)")
        out.append(("②-8 页面显示「修改记录」且带来源",
                    any("外部 MCP 客户端" in h or "工作台界面" in h for h in hist), str(hist[:2])))
        page.check("[data-vm-archive]")
        page.click("#vm-archive")
        page.wait_for_timeout(2500)
        has_archived = page.eval_on_selector_all(".vm-arow", "els => els.length")
        out.append(("②-5 归档后出现归档区（可追溯）", has_archived >= 1, str(has_archived)))
        if has_archived:
            page.click("[data-vm-restore]")
            page.wait_for_timeout(2500)
            out.append(("②-6 取回后重新出现活版本",
                        page.eval_on_selector_all(".vm-vrow", "els => els.length") >= 1, ""))
        out.append(("②-7 0 console error", not errs, str(errs[:3])))
        browser.close()
    return out


if __name__ == "__main__":
    raise SystemExit(main())
