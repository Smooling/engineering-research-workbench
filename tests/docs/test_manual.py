"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
夹具：内置「使用手册」页 —— 内核自带文档能在工作台里自由翻阅。

覆盖：
① API：章节列表、取章、非法 id 拒绝、图片路由可取、越权路径 403；
② 真浏览器：侧栏出现「使用手册」、目录列出全部章节、正文渲染、**图片真实解码**；
③ 章内导航：点目录切章、上一章/下一章、章内 `.md` 链接直接切章；
④ **零插件模式下同样可读**（手册是内核文档，不该依赖插件）；
⑤ 0 console error。

用法：`$env:PYTHONIOENCODING='utf-8'; python tests/docs/test_manual.py`
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

ID = "manual"
PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def status_of(url: str) -> tuple[int, int]:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return int(r.status), len(r.read())
    except urllib.error.HTTPError as exc:
        return int(exc.code), 0


def start_server(plugins_root: Path):
    os.environ["ERW_PLUGINS_ROOTS"] = str(plugins_root)
    import server

    httpd, _c, url = server.build_server(port_override=free_port(), auto_open_browser=False)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
    for _ in range(60):
        try:
            get_json(f"{url}/api/manual")
            return httpd, url
        except Exception:
            time.sleep(0.25)
    return httpd, url


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="erwmanual-"))
    plugins_root = base / "plugins"
    plugins_root.mkdir(parents=True)
    open_root = base / "empty-plugins"          # 零插件模式
    open_root.mkdir(parents=True)
    httpd = None
    httpd2 = None
    try:
        print("① 手册 API（内核文档，不需要插件）")
        httpd, url = start_server(plugins_root)
        data = get_json(f"{url}/api/manual")
        chapters = data.get("chapters") or []
        check("①-1 章节列表非空（>=6 章）", len(chapters) >= 6, str([c["id"] for c in chapters]))
        check("①-2 目录首项是总览/目录", chapters and chapters[0]["id"] == "README",
              str(chapters[0] if chapters else None))
        check("①-3 每章都有标题与字节数",
              all(c.get("title") and c.get("bytes", 0) > 200 for c in chapters),
              str(chapters[:2]))
        first = get_json(f"{url}/api/manual/{quote(chapters[0]['id'])}")
        check("①-4 取章返回 markdown 正文",
              first.get("markdown", "").startswith("#") and len(first["markdown"]) > 500,
              str(first)[:120])
        check("①-5 非法 id 拒绝（404）",
              status_of(f"{url}/api/manual/..%2Fserver")[0] == 404, "")
        code, size = status_of(f"{url}/manual-file/img/overview.png")
        check("①-6 手册图片可取（200 且有字节）", code == 200 and size > 10000, f"{code} {size}")
        check("①-7 越权取仓库文件被拒（403）",
              status_of(f"{url}/manual-file/../server.py")[0] in (403, 404), "")

        print("② 真浏览器：目录 + 正文 + 图片")
        for name, ok, detail in browser_checks(url):
            check(name, ok, detail)

        print("③ 零插件模式下同样可读（手册是内核文档）")
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
            httpd = None
        httpd2, url2 = start_server(open_root)
        payload = get_json(f"{url2}/api/plugins")
        check("③-1 该实例确实没有插件", payload.get("plugins") == [], str(payload.get("plugins")))
        manual2 = get_json(f"{url2}/api/manual")
        check("③-2 无插件时手册目录照常有", len(manual2.get("chapters") or []) >= 6,
              str(len(manual2.get("chapters") or [])))
        for name, ok, detail in browser_checks(url2, tag="③", expect_plugins=False):
            check(name, ok, detail)
    finally:
        for server_obj in (httpd, httpd2):
            if server_obj is not None:
                try:
                    server_obj.shutdown()
                    server_obj.server_close()
                except Exception:
                    pass
        os.environ.pop("ERW_PLUGINS_ROOTS", None)
        from core.plugins import jobs as plugin_jobs

        plugin_jobs.shutdown()
        import shutil

        shutil.rmtree(base, ignore_errors=True)

    total = len(PASS) + len(FAIL)
    print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


def browser_checks(url: str, tag: str = "②", expect_plugins: bool = True) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [(f"{tag}-0 playwright 可用", False, "pip install playwright")]
    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe if Path(exe).is_file() else None, headless=True)
        page = browser.new_context(viewport={"width": 1500, "height": 950}).new_page()
        errs: list[str] = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.goto(f"{url}/#{ID}", wait_until="networkidle", timeout=60000)
        page.wait_for_selector(f'#main[data-plugin="{ID}"]', timeout=30000)
        page.wait_for_selector(".manual-toc-item", timeout=30000)
        page.wait_for_selector("#manual-body h1", timeout=30000)
        page.wait_for_timeout(1200)

        out.append((f"{tag}-1 侧栏出现「使用手册」导航项",
                    page.eval_on_selector_all("[data-route]", f"els => els.some(e => e.dataset.route === '{ID}')"), ""))
        toc = page.eval_on_selector_all(".manual-toc-item", "els => els.length")
        out.append((f"{tag}-2 目录列出全部章节（>=6）", int(toc) >= 6, f"{toc} 项"))
        title = page.eval_on_selector("#manual-body h1", "e => e.textContent || ''")
        out.append((f"{tag}-3 正文渲染出标题", len(title) > 2, title[:40]))

        # 第二章（README 本身没有图）→ 断言图片真实解码与内核路由
        page.click(".manual-toc-item:nth-child(2)")
        page.wait_for_selector("#manual-body img", timeout=20000)
        page.wait_for_timeout(1200)
        imgs = page.eval_on_selector_all("#manual-body img",
                                         "els => els.map(i => ({w: i.naturalWidth, src: i.getAttribute('src')}))")
        out.append((f"{tag}-4 手册图片真实解码（naturalWidth>0）",
                    bool(imgs) and all(i["w"] > 50 for i in imgs), str(imgs[:2])))
        out.append((f"{tag}-5 图片走内核 /manual-file/ 路由",
                    bool(imgs) and all(str(i["src"]).startswith("/manual-file/") for i in imgs),
                    str([i["src"] for i in imgs][:2])))

        # 回目录章，点章节互链（README 里有 7 条 .md 链接）
        page.click(".manual-toc-item:nth-child(1)")
        page.wait_for_timeout(900)
        before_link = page.eval_on_selector("#manual-body h1", "e => e.textContent || ''")
        link = page.query_selector('#manual-body a[href$=".md"]')
        if link:
            target_label = link.text_content().strip()
            link.click()
            page.wait_for_timeout(1200)
            after_link = page.eval_on_selector("#manual-body h1", "e => e.textContent || ''")
            out.append((f"{tag}-10 章内 .md 链接切换章节", after_link != before_link,
                        f"点「{target_label}」→ {after_link[:30]}"))
        else:
            out.append((f"{tag}-10 章内 .md 链接切换章节", False, "目录章里没找到 .md 链接"))

        # 点目录切章（选第 3 章）
        second = page.eval_on_selector_all(".manual-toc-item", "els => els[2].textContent.trim()")
        page.click(".manual-toc-item:nth-child(3)")
        page.wait_for_timeout(1200)
        title2 = page.eval_on_selector("#manual-body h1", "e => e.textContent || ''")
        out.append((f"{tag}-6 点目录切章生效", title2 and title2 != after_link, f"{title2[:30]} ← {second[:20]}"))
        active = page.eval_on_selector_all(".manual-toc-item.active", "els => els.length")
        out.append((f"{tag}-7 当前章在目录里高亮", int(active) == 1, f"{active} 个"))
        page.wait_for_timeout(600)
        htmlish = page.eval_on_selector("#manual-body", "e => e.innerHTML.length")
        out.append((f"{tag}-8 切章后正文有内容", int(htmlish) > 800, f"innerHTML {htmlish} 字符"))

        # 上一章 / 下一章
        page.click("#manual-next")
        page.wait_for_timeout(1000)
        title3 = page.eval_on_selector("#manual-body h1", "e => e.textContent || ''")
        out.append((f"{tag}-9 下一章按钮生效", title3 != title2, f"{title3[:30]}"))

        out.append((f"{tag}-11 0 console error", not errs, str(errs[:3])))
        browser.close()
    return out


if __name__ == "__main__":
    raise SystemExit(main())
