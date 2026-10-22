"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
夹具：单文件包解包的**HTTP 接线**验证 —— 设置页会安装、普通页面加载不会。

验的是接线而不是解包本身（解包规则见 `verify_zip_unpack.py`）：
`server.build_plugin_payload` 只在 `detail=True`（设置页插件页）时打开 `unpack`，
`GET /api/plugins`（每次页面加载都调）必须保持只读。

用法：`$env:PYTHONIOENCODING='utf-8'; python tests/plugins/test_zip_install_http.py`
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def make_zip(path: Path, pid: str = "httppkg", ver: str = "1.0.0") -> None:
    manifest = {
        "id": pid, "name": "HTTP 包", "version": ver, "api_version": 1,
        "core_min": "v261009", "kind": "inprocess", "distribution": "optional",
        "default_enabled": True, "permissions": ["ui:panel"],
        "nav": [{"id": pid, "label": "HTTP", "icon": "H", "mount": "web/panel.js"}],
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("plugin.json", json.dumps(manifest, ensure_ascii=False))
        z.writestr("web/panel.js",
                   "window.ERWPanels && window.ERWPanels.register("
                   "{id:'" + pid + "',label:'HTTP',render:function(){}});\n")


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="erwziphttp-"))
    port = free_port()
    try:
        root = base / "plugins"
        root.mkdir(parents=True)
        make_zip(root / "bootpkg-1.0.0.zip", pid="bootpkg")   # 启动前就在 → 服务启动时安装

        os.environ["ERW_PLUGINS_ROOTS"] = str(root)
        import server

        httpd, _cfg, url = server.build_server(port_override=port, auto_open_browser=False)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        thread.start()
        try:
            print("① 服务启动即安装（§5：把包丢进 plugins/ → 重启生效）")
            check("①-1 启动后已解出", (root / "bootpkg").is_dir(),
                  str(sorted(p.name for p in root.iterdir())))
            check("①-2 标记文件已写入", (root / "bootpkg" / ".erw-unpacked").is_file())

            print("② 启动之后新丢进来的包：普通请求必须保持只读")
            make_zip(root / "httppkg-1.0.0.zip")
            plain = get(f"{url}/api/plugins")
            check("②-1 GET /api/plugins 没有解包", not (root / "httppkg").exists(),
                  f"盘上出现了 {sorted(p.name for p in root.iterdir())}")
            check("②-2 未安装的包不出现在清单里",
                  all(p.get("id") != "httppkg" for p in plain.get("plugins", [])),
                  str([p.get("id") for p in plain.get("plugins", [])]))

            print("③ 设置页（GET /api/plugins?detail=1）执行安装")
            detail = get(f"{url}/api/plugins?detail=1")
            rows = {p["id"]: p for p in detail.get("plugins", [])}
            inst = {i["file"]: i for i in detail.get("install", [])}
            check("③-1 目录已解出", (root / "httppkg").is_dir())
            check("③-2 出现在预览清单里且可用", "httppkg" in rows, str(sorted(rows)))
            check("③-3 面板文件到位", (root / "httppkg" / "web" / "panel.js").is_file())
            check("③-4 结构化 install 说明已解包",
                  inst.get("httppkg-1.0.0.zip", {}).get("action") == "unpacked"
                  and inst["httppkg-1.0.0.zip"].get("action_label") == "已解包安装",
                  str(detail.get("install", [])))
            check("③-5 install 带 id/version（前端要显示）",
                  inst.get("httppkg-1.0.0.zip", {}).get("id") == "httppkg"
                  and inst.get("httppkg-1.0.0.zip", {}).get("version") == "1.0.0")

            print("④ 再次请求幂等（不重复解包、不报错）")
            again = get(f"{url}/api/plugins?detail=1")
            inst2 = {i["file"]: i for i in again.get("install", [])}
            check("④-1 仍是同一个插件", any(p["id"] == "httppkg" for p in again.get("plugins", [])))
            check("④-2 第二次是「已是该版本」而不是重复写盘",
                  inst2.get("httppkg-1.0.0.zip", {}).get("action") == "current",
                  str(again.get("install", [])))
            check("④-3 没有临时目录残留", not list(root.glob(".unpack-*")))
            check("④-4 普通清单（无 detail）不下发 install 字段",
                  "install" not in plain or plain.get("install") == [])

            print("⑤ 手放目录不被覆盖（HTTP 层同样遵守规则 5）")
            hand = root / "handpkg"
            hand.mkdir()
            (hand / "plugin.json").write_text(json.dumps({
                "id": "handpkg", "name": "手放", "version": "0.1.0", "api_version": 1,
                "kind": "inprocess", "distribution": "optional",
            }, ensure_ascii=False), encoding="utf-8")
            (hand / "mine.txt").write_text("keep me", encoding="utf-8")
            make_zip(root / "handpkg-9.9.9.zip", pid="handpkg", ver="9.9.9")
            out = get(f"{url}/api/plugins?detail=1")
            inst3 = {i["file"]: i for i in out.get("install", [])}
            check("⑤-1 手放目录仍在且内容保留", (hand / "mine.txt").read_text(encoding="utf-8") == "keep me")
            check("⑤-2 版本没被换掉", json.loads((hand / "plugin.json").read_text(encoding="utf-8"))["version"] == "0.1.0")
            check("⑤-3 结构化上报 conflict 并给出原因",
                  inst3.get("handpkg-9.9.9.zip", {}).get("action") == "conflict"
                  and "不是由 zip 解出" in inst3.get("handpkg-9.9.9.zip", {}).get("reason", ""),
                  str(out.get("install", [])))

            print("⑥ 设置页真的把安装结果显示出来（真浏览器，只查 DOM 不截图）")
            # 一个当场新丢进来的包（这次会真的解包 → 出现「已解包安装」绿行）+ 一个坏包
            make_zip(root / "uipkg-1.0.0.zip", pid="uipkg")
            bad = root / "badpkg-1.0.0.zip"
            with zipfile.ZipFile(bad, "w") as z:
                z.writestr("badpkg/plugin.json", json.dumps({
                    "id": "badpkg", "name": "坏包", "version": "1.0.0", "api_version": 1,
                    "kind": "inprocess", "distribution": "optional",
                }, ensure_ascii=False))
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                check("⑥-0 playwright 可用", False, "pip install playwright")
            else:
                exe = os.path.expandvars(
                    r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(
                        executable_path=exe if Path(exe).is_file() else None, headless=True)
                    page = browser.new_context(viewport={"width": 1440, "height": 950}).new_page()
                    errs: list[str] = []
                    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
                    page.goto(f"{url}/#settings", wait_until="networkidle", timeout=60000)
                    page.wait_for_selector("#settings-panel", timeout=30000)
                    page.click('[data-set-tab="plugins"]')
                    page.wait_for_selector(".pm-notes", timeout=30000)
                    page.wait_for_timeout(600)
                    info = page.eval_on_selector(".pm-notes", """e => ({
                        text: e.innerText,
                        h: e.getBoundingClientRect().height,
                        good: e.querySelectorAll('li.good').length,
                        bad: e.querySelectorAll('li.bad').length,
                        items: e.querySelectorAll('li').length,
                    })""")
                    check("⑥-1 有安装结果区块", info["items"] >= 1, str(info))
                    check("⑥-2 成功项标绿（解包/升级）", info["good"] >= 1, str(info))
                    check("⑥-3 拒收/冲突项标红并有原因",
                          info["bad"] >= 1 and "包根" in info["text"], info["text"][:200])
                    check("⑥-4 文案含「已解包安装」", "已解包安装" in info["text"], info["text"][:200])
                    check("⑥-5 高度合理（未把卡片挤爆）", 24 < info["h"] < 500, f"h={info['h']}")
                    check("⑥-6 插件卡片仍在同页", page.eval_on_selector_all(
                        "[data-plugin-card]", "els => els.length") >= 1)
                    check("⑥-7 0 console error", not errs, str(errs[:3]))
                    browser.close()

            print("⑦ 一个插件都没有时，拒收原因也必须看得见（空列表分支）")
            root2 = base / "plugins2"
            root2.mkdir()
            with zipfile.ZipFile(root2 / "solo-1.0.0.zip", "w") as z:
                z.writestr("solo/plugin.json", json.dumps({
                    "id": "solo", "name": "只在子目录", "version": "1.0.0", "api_version": 1,
                    "kind": "inprocess", "distribution": "optional",
                }, ensure_ascii=False))
            os.environ["ERW_PLUGINS_ROOTS"] = str(root2)
            httpd2, _c2, url2 = server.build_server(port_override=free_port(), auto_open_browser=False)
            th2 = threading.Thread(target=httpd2.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
            th2.start()
            try:
                payload = get(f"{url2}/api/plugins?detail=1")
                check("⑦-1 后端上报拒收",
                      any(i["action"] == "rejected" for i in payload.get("install", [])),
                      str(payload.get("install", [])))
                check("⑦-2 此时插件清单为空", payload.get("plugins") == [], str(payload.get("plugins")))
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(
                        executable_path=exe if Path(exe).is_file() else None, headless=True)
                    page = browser.new_context(viewport={"width": 1440, "height": 950}).new_page()
                    page.goto(f"{url2}/#settings", wait_until="networkidle", timeout=60000)
                    page.wait_for_selector("#settings-panel", timeout=30000)
                    page.click('[data-set-tab="plugins"]')
                    page.wait_for_timeout(1500)
                    text = page.inner_text("#pm-list")
                    check("⑦-3 空列表时仍显示拒收原因", "包根" in text, text[:200])
                    check("⑦-4 空态说明提到支持 .zip", ".zip" in text, text[:200])
                    browser.close()
            finally:
                httpd2.shutdown()
                httpd2.server_close()
                th2.join(timeout=5)
                os.environ["ERW_PLUGINS_ROOTS"] = str(root)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
    finally:
        os.environ.pop("ERW_PLUGINS_ROOTS", None)
        shutil.rmtree(base, ignore_errors=True)

    total = len(PASS) + len(FAIL)
    print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
