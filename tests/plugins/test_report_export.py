"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
夹具：报告导出插件（report-export）—— 导出真能打开、新接缝 ctx.raw 真能用。

覆盖：
① 只读窗口（core_api.entries/entry/projects/kind_labels）与公开 API 同源；
② capabilities / scopes / preview / export(docx|html|md) / download / view 全链路；
③ **DOCX 用带 python-docx 的捆绑解释器复核**（Word 侧能不能解析），并校验 OOXML 结构；
④ `ctx.raw` 原样响应接缝（Content-Type / Content-Disposition / 字节一致）；
⑤ 下载路径安全（拒绝 `..`、绝对路径、子目录）；
⑥ 真浏览器走查新插件的页面（预览 + 导出 + 0 console error）；
⑦ 收尾：把夹具写过的真实路径（plugins.json、config、Workspace/Plugins）**按原样恢复**。

用法：`$env:PYTHONIOENCODING='utf-8'; python tests/plugins/test_report_export.py`
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "support"))

import core_api  # noqa: E402
from fixture_cleanup import restore_many, snap_many  # noqa: E402

ID = "report-export"
PASS: list[str] = []
FAIL: list[str] = []
PLUGINS_JSON = ROOT / "Workspace" / "System" / "plugins.json"
CONFIG = ROOT / "config" / "plugins" / f"{ID}.json"
WS_PLUGIN = ROOT / "Workspace" / "Plugins" / ID
BUNDLE_PY = Path(os.path.expandvars(
    r"%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"))
REFEREE = ROOT / ".scratch" / "tmp" / "_docx_referee.py"


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def request(url: str, body: dict | None = None, *, raw: bool = False):
    if body is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(url, method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        return (r.status, dict(r.headers), data) if raw else json.loads(data.decode("utf-8"))


def status_of(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return int(e.code)


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="erwreport-"))
    root = base / "plugins"
    root.mkdir(parents=True)
    shutil.copytree(ROOT / "plugins" / ID, root / ID)      # 插件放进临时扫描根，仓库不动
    httpd = None
    saved_json = PLUGINS_JSON.read_bytes() if PLUGINS_JSON.is_file() else None
    saved_cfg = CONFIG.read_bytes() if CONFIG.is_file() else None
    had_ws = WS_PLUGIN.exists()
    # 命名空间（register() 建目录、导出会写 exports/）：按原状还原，只删本次新增的文件
    ns_before = snap_many([WS_PLUGIN, ROOT / "Workspace" / "System" / "Plugins" / ID])
    try:
        os.environ["ERW_PLUGINS_ROOTS"] = str(root)
        import server

        httpd, _c, url = server.build_server(port_override=free_port(), auto_open_browser=False)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
        for _ in range(60):
            try:
                request(f"{url}/api/plugins")
                break
            except Exception:
                import time
                time.sleep(0.25)

        print("① 启用插件（走设置页同一条接口）")
        enabled = request(f"{url}/api/plugin-manager/{ID}/enabled", {"enabled": True})
        check("①-1 启用成功", enabled.get("ok") is True, str(enabled))
        tools = request(f"{url}/api/agent/tools")
        names = [t.get("name") or "" for t in (tools if isinstance(tools, list) else [])]
        check("①-2 两个 Agent 工具已接入",
              f"p_{ID}__list_scopes" in names and f"p_{ID}__export_report" in names,
              str([n for n in names if "report" in n]))

        print("② capabilities / scopes 与内核只读窗口一致")
        cap = request(f"{url}/api/plugins/{ID}/capabilities")
        check("②-1 三种格式齐备", set(cap.get("formats") or []) == {"docx", "html", "md"}, str(cap.get("formats")))
        check("②-2 说明 DOCX 引擎是标准库", "stdlib" in str(cap.get("docx_engine")), str(cap.get("docx_engine")))
        check("②-3 kind 标签来自内核契约", cap.get("kind_labels", {}).get("note") == "笔记",
              str(cap.get("kind_labels")))
        scopes = request(f"{url}/api/plugins/{ID}/scopes")
        api_total = len(core_api.entries(limit=500))
        check("②-4 总数与 core_api 一致", scopes.get("total") == api_total,
              f"插件={scopes.get('total')} core_api={api_total}")
        check("②-5 项目列表与 core_api 同源",
              sorted(p["value"] for p in scopes.get("projects", [])) == sorted(core_api.project_names()),
              str([p["value"] for p in scopes.get("projects", [])]))
        first_project = (scopes.get("projects") or [{}])[0].get("value", "")

        print("③ 预览：范围取数与只读窗口一致")
        preview = request(f"{url}/api/plugins/{ID}/preview",
                          {"scope": {"type": "project", "value": first_project}, "options": {}})
        expect = len(core_api.entries(project=first_project, limit=500))
        check("③-1 项目范围条数一致", preview.get("count") == expect,
              f"预览={preview.get('count')} core_api={expect}")
        check("③-2 预览项带类别中文名与字数",
              bool(preview.get("items")) and preview["items"][0].get("kind_label")
              and preview["items"][0].get("chars", 0) > 0, str(preview.get("items", [])[:1])[:160])
        kinds_prev = request(f"{url}/api/plugins/{ID}/preview",
                             {"scope": {"type": "kind", "value": "experiment"}, "options": {}})
        check("③-3 类别范围条数一致",
              kinds_prev.get("count") == len(core_api.entries("experiment", limit=500)),
              f"{kinds_prev.get('count')}")
        no_body = request(f"{url}/api/plugins/{ID}/preview",
                          {"scope": {"type": "kind", "value": "note"}, "options": {"include_body": False}})
        check("③-4 关掉正文时仍然列出条目", no_body.get("count", 0) > 0, str(no_body.get("count")))

        print("④ 导出三格式（DOCX 用捆绑解释器复核 + OOXML 结构校验）")
        docx = request(f"{url}/api/plugins/{ID}/export",
                       {"scope": {"type": "kind", "value": "experiment"}, "format": "docx",
                        "max_entries": 12})
        check("④-1 DOCX 导出成功", docx.get("ok") is True and docx.get("bytes", 0) > 8000, str(docx)[:200])
        path = ROOT / "Workspace" / "Plugins" / ID / "exports" / str(docx.get("file"))
        check("④-2 文件落在插件自己的命名空间", path.is_file(), str(path))
        with zipfile.ZipFile(path) as z:
            parts = set(z.namelist())
            check("④-3 OOXML 必需部件齐备",
                  {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml"}
                  <= parts, str(sorted(parts)))
            document = z.read("word/document.xml")
        try:
            ET.fromstring(document)
            xml_ok = True
        except ET.ParseError as exc:
            xml_ok = False
            detail = str(exc)
        check("④-4 document.xml 是合法 XML", xml_ok, "" if xml_ok else detail)
        check("④-5 正文含中文与标题", "实验" in document.decode("utf-8"), "")
        if BUNDLE_PY.is_file():
            r = subprocess.run([str(BUNDLE_PY), str(REFEREE), str(path)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            try:
                verdict = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception:
                verdict = {"ok": False, "err": (r.stdout + r.stderr)[-200:]}
            check("④-6 python-docx（独立裁判）能打开", verdict.get("ok") is True, str(verdict)[:200])
            check("④-7 段落数与条目量相称",
                  verdict.get("paragraphs", 0) >= docx.get("entries", 1),
                  f"段落={verdict.get('paragraphs')} 条目={docx.get('entries')}")
            check("④-8 用到了 Heading 样式（Word 里有层级）",
                  any(str(k).startswith("Heading") for k in (verdict.get("styles") or {})),
                  str(verdict.get("styles")))
        else:
            check("④-6 捆绑解释器存在（跳过 python-docx 复核）", False, str(BUNDLE_PY))

        html = request(f"{url}/api/plugins/{ID}/export",
                       {"scope": {"type": "project", "value": first_project}, "format": "html",
                        "max_entries": 5})
        html_path = ROOT / "Workspace" / "Plugins" / ID / "exports" / str(html.get("file"))
        html_text = html_path.read_text(encoding="utf-8")
        check("④-9 HTML 含标题与打印样式",
              "<h1>" in html_text and "@media print" in html_text and "<h1>" in html_text, html_text[:80])
        check("④-10 HTML 给出打印链接（PDF 路径）", "print=1" in str(html.get("print_url")), str(html.get("print_url")))

        md = request(f"{url}/api/plugins/{ID}/export",
                     {"scope": {"type": "kind", "value": "milestone"}, "format": "md", "max_entries": 5})
        md_text = (ROOT / "Workspace" / "Plugins" / ID / "exports" / str(md.get("file"))).read_text(encoding="utf-8")
        check("④-11 Markdown 以一级标题开头", md_text.startswith("# "), md_text[:60])

        bad = request(f"{url}/api/plugins/{ID}/export",
                      {"scope": {"type": "kind", "value": "nonexistent-kind"}, "format": "docx"})
        check("④-12 空范围给出可读错误而不是坏文件", bad.get("ok") is False and "没有条目" in str(bad.get("error")),
              str(bad)[:160])
        check("④-13 文件名与 URL 可直接用（无空格、已百分号编码）",
              " " not in str(docx.get("file")) and " " not in str(docx.get("url"))
              and "%" in str(docx.get("url")),
              f"file={docx.get('file')} url={docx.get('url')}")

        print("⑤ ctx.raw 接缝：原样响应、字节一致、中文文件名不乱码")
        code, headers, body = request(f"{url}{docx['url']}", raw=True)
        check("⑤-1 下载返回 200 且字节与文件一致", code == 200 and body == path.read_bytes(),
              f"code={code} len={len(body)}/{path.stat().st_size}")
        check("⑤-2 Content-Type 是 Word 的 MIME",
              "wordprocessingml" in headers.get("Content-Type", ""), headers.get("Content-Type"))
        check("⑤-3 中文文件名用 RFC 5987 编码",
              "filename*=UTF-8''" in headers.get("Content-Disposition", ""),
              headers.get("Content-Disposition"))
        check("⑤-4 下载不带 JSON 包装（不是 {\"ok\": ...}）", not body.lstrip().startswith(b"{"), body[:24])
        code, headers, body = request(f"{url}/api/plugins/{ID}/view?name={quote(str(html['file']))}&print=1", raw=True)
        check("⑤-5 view 按 text/html 原样返回且注入打印脚本",
              code == 200 and "text/html" in headers.get("Content-Type", "")
              and b"window.print()" in body, f"code={code} {headers.get('Content-Type')}")

        print("⑥ 下载路径安全")
        for evil in ("../plugins.json", "..%2Fplugins.json", "C:/Windows/win.ini", "sub/dir.docx"):
            code = status_of(f"{url}/api/plugins/{ID}/download?name={evil}")
            payload = None
            try:
                with urllib.request.urlopen(f"{url}/api/plugins/{ID}/download?name={evil}", timeout=20) as r:
                    payload = r.read()
            except urllib.error.HTTPError:
                pass
            leaked = bool(payload) and (b"plugins" in payload or b"[fonts]" in payload or b"schema_version" in payload)
            check(f"⑥ 拒绝越权下载 {evil!r}", (not leaked), f"code={code} leaked={leaked}")

        print("⑦ 真浏览器：新插件的页面能用（导航项 / 预览 / 导出 / 0 console error）")
        for name, ok, detail in browser_checks(f"{url}", first_project):
            check(name, ok, detail)
    finally:
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        os.environ.pop("ERW_PLUGINS_ROOTS", None)
        # 按原样恢复用户的文件（不是只删自己那条记录）
        if saved_json is None:
            PLUGINS_JSON.unlink(missing_ok=True)
        else:
            PLUGINS_JSON.write_bytes(saved_json)
        if saved_cfg is None:
            CONFIG.unlink(missing_ok=True)
        else:
            CONFIG.write_bytes(saved_cfg)
        if not had_ws:
            shutil.rmtree(WS_PLUGIN, ignore_errors=True)
        restore_many(ns_before)
        shutil.rmtree(base, ignore_errors=True)

    print("⑧ 收尾")
    check("⑧-1 plugins.json 已按原样恢复",
          (PLUGINS_JSON.read_bytes() if PLUGINS_JSON.is_file() else None) == saved_json)
    check("⑧-2 config/plugins 无残留", (CONFIG.read_bytes() if CONFIG.is_file() else None) == saved_cfg)
    check("⑧-3 仓库未受污染", not (ROOT / "plugins" / ".staging").exists())
    leftover_files = {k: [str(p.relative_to(Path(k))) for p in Path(k).rglob("*")
                          if p.is_file() and str(p.relative_to(Path(k))).replace("\\", "/") not in v[1]]
                      for k, v in ns_before.items() if Path(k).exists()}
    check("⑧-4 插件命名空间没有本次新增文件", not any(leftover_files.values()), str(leftover_files))

    total = len(PASS) + len(FAIL)
    print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


def browser_checks(url: str, project: str) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [("⑦-0 playwright 可用", False, "pip install playwright")]
    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe if Path(exe).is_file() else None, headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 950}).new_page()
        errs: list[str] = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.goto(f"{url}/#{ID}", wait_until="networkidle", timeout=60000)
        page.wait_for_selector(f'#main[data-plugin="{ID}"]', timeout=30000)
        page.wait_for_timeout(800)
        out.append(("⑦-1 侧栏有导航项且页面渲染", page.eval_on_selector_all(
            "[data-route]", f"els => els.some(e => e.dataset.route === '{ID}')"), ""))
        scopes = page.eval_on_selector("#re-total", "e => e.textContent || ''")
        out.append(("⑦-2 读到范围与总数", "共" in scopes and "条" in scopes, scopes[:80]))
        opts = page.eval_on_selector_all("#re-scope-kind option", "els => els.length")
        out.append(("⑦-3 类别下拉有选项", int(opts) >= 7, f"{opts} 个"))
        page.click("#re-preview-btn")
        page.wait_for_selector(".re-pv-list li", timeout=30000)
        rows = page.eval_on_selector_all(".re-pv-list li", "els => els.length")
        out.append(("⑦-4 预览列出条目", int(rows) > 0, f"{rows} 行"))
        page.click("#re-md")
        page.wait_for_selector(".re-ok", timeout=60000)
        result = page.inner_text("#re-result")
        out.append(("⑦-5 页面内导出并给出下载链接", "已生成" in result and "下载" in result, result[:100]))
        out.append(("⑦-6 0 console error", not errs, str(errs[:3])))
        browser.close()
    return out


if __name__ == "__main__":
    raise SystemExit(main())
