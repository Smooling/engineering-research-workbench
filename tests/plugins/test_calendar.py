"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
夹具：日历插件（milestone-calendar）—— 到期分桶口径 + 顶栏槽位。

覆盖：
① agenda 的分桶与 `core_api` 数据**逐项对齐**（用夹具独立复算同一套规则交叉验证）；
② 每个分桶的谓词成立（overdue < 今天、today == 今天、soon ≤ 今天+N、undated 无日期）；
③ 已完成项不参与提醒；改「近期窗口」会按新窗口重算；
④ Agent 工具与 HTTP 路由口径一致；
⑤ 真浏览器：月历渲染、点某天看明细、改窗口保存、**顶栏槽位角标出现**、0 console error；
⑥ 收尾：插件配置按原样恢复。

用法：`$env:PYTHONIOENCODING='utf-8'; python tests/plugins/test_calendar.py`
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import core_api  # noqa: E402

ID = "milestone-calendar"
PASS: list[str] = []
FAIL: list[str] = []
CONFIG = ROOT / "config" / "plugins" / f"{ID}.json"
#: 启用插件会往这里写记录：夹具必须**按原样恢复**（这是用户的文件）
PLUGINS_JSON = ROOT / "Workspace" / "System" / "plugins.json"


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def request(url: str, body: dict | None = None):
    if body is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(url, method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_due(raw: str) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def expected_buckets(lookahead: int) -> dict:
    """夹具独立复算（与插件文档里的口径一致），用来交叉验证插件实现。"""
    today = date.today()
    soon_end = today + timedelta(days=lookahead)
    out = {"overdue": [], "today": [], "soon": [], "later": [], "undated": []}
    for row in core_api.entries("milestone", limit=500):
        if str(row.get("status") or "") in ("完成", "已归档"):
            continue
        due = parse_due(row.get("due") or "")
        if due is None:
            out["undated"].append(row["id"])
        elif due < today:
            out["overdue"].append(row["id"])
        elif due == today:
            out["today"].append(row["id"])
        elif due <= soon_end:
            out["soon"].append(row["id"])
        else:
            out["later"].append(row["id"])
    for row in core_api.todos(include_done=False):
        due = parse_due(row.get("due") or "")
        if due is None:
            out["undated"].append(row["id"])
        elif due < today:
            out["overdue"].append(row["id"])
        elif due == today:
            out["today"].append(row["id"])
        elif due <= soon_end:
            out["soon"].append(row["id"])
        else:
            out["later"].append(row["id"])
    return out


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="erwcal-"))
    root = base / "plugins"
    root.mkdir(parents=True)
    shutil.copytree(ROOT / "plugins" / ID, root / ID)
    httpd = None
    saved_cfg = CONFIG.read_bytes() if CONFIG.is_file() else None
    saved_json = PLUGINS_JSON.read_bytes() if PLUGINS_JSON.is_file() else None
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
                time.sleep(0.25)

        print("① 启用插件（默认不启用）并核对分桶口径")
        request(f"{url}/api/plugin-manager/{ID}/enabled", {"enabled": True})
        data = request(f"{url}/api/plugins/{ID}/agenda")
        expect = expected_buckets(data["lookahead_days"])
        got = {k: [it["id"] for it in data["buckets"][k]] for k in expect}
        for key in ("overdue", "today", "soon", "later", "undated"):
            check(f"① 分桶 {key} 与独立复算一致（{len(expect[key])} 项）",
                  sorted(got[key]) == sorted(expect[key]),
                  f"插件={len(got[key])} 复算={len(expect[key])}")
        check("①-6 counts 与 buckets 自洽",
              all(data["counts"][k] == len(data["buckets"][k]) for k in data["counts"]),
              str(data["counts"]))

        print("② 每个分桶的谓词成立（不是只对上数量）")
        today = date.today()
        soon_end = today + timedelta(days=data["lookahead_days"])
        ok = all(parse_due(it["due"]) < today for it in data["buckets"]["overdue"])
        check("②-1 overdue 全部早于今天", ok)
        check("②-2 today 全部等于今天", all(parse_due(it["due"]) == today for it in data["buckets"]["today"]))
        check("②-3 soon 全在今天..今天+N 之内",
              all(today < parse_due(it["due"]) <= soon_end for it in data["buckets"]["soon"]))
        check("②-4 later 全部晚于今天+N",
              all(parse_due(it["due"]) > soon_end for it in data["buckets"]["later"]))
        check("②-5 undated 都没有日期", all(not it["due"] for it in data["buckets"]["undated"]))
        check("②-6 逾期项带 overdue_days 且 > 0",
              all(it.get("overdue_days", 0) > 0 for it in data["buckets"]["overdue"]))
        check("②-7 每条都有来源标签与标题",
              all(it.get("kind_label") in ("里程碑", "待办") and it.get("title")
                  for k in ("overdue", "today", "soon") for it in data["buckets"][k]))
        check("②-8 已完成项不出现",
              not any(it.get("done") for k in data["buckets"] for it in data["buckets"][k]))

        print("③ 改「近期窗口」按新窗口重算")
        before_soon = data["counts"]["soon"]
        cfg = request(f"{url}/api/plugins/{ID}/config", {"lookahead_days": 60})
        check("③-1 配置写入成功", cfg.get("lookahead_days") == 60, str(cfg))
        data60 = request(f"{url}/api/plugins/{ID}/agenda")
        expect60 = expected_buckets(60)
        check("③-2 新窗口下的 soon/later 与复算一致",
              sorted(it["id"] for it in data60["buckets"]["soon"]) == sorted(expect60["soon"])
              and sorted(it["id"] for it in data60["buckets"]["later"]) == sorted(expect60["later"]),
              f"soon={data60['counts']['soon']} later={data60['counts']['later']}")
        check("③-3 窗口变大后近期项不减", data60["counts"]["soon"] >= before_soon,
              f"{before_soon} → {data60['counts']['soon']}")
        check("③-4 逾期与今日不受窗口影响",
              data60["counts"]["overdue"] == data["counts"]["overdue"]
              and data60["counts"]["today"] == data["counts"]["today"])
        request(f"{url}/api/plugins/{ID}/config", {"lookahead_days": 7})

        print("④ Agent 工具与路由口径一致")
        tools = request(f"{url}/api/agent/tools")
        names = [t.get("name") for t in (tools if isinstance(tools, list) else [])]
        check("④-1 工具已接入", f"p_{ID}__agenda" in names, str([n for n in names if "calend" in str(n)]))
        # 直接用内核的工具执行入口跑一次，确认返回同一套计数
        sys.path.insert(0, str(ROOT))
        from core.plugins import runtime as plugin_runtime

        result = plugin_runtime.current()
        tool = next(t for t in result.mcp_tools if t.exposed_name == f"p_{ID}__agenda")
        out = tool.handler({"limit": 3})
        check("④-2 工具返回同类计数", out["counts"] == data["counts"], f"{out['counts']} vs {data['counts']}")
        check("④-3 工具受 limit 约束", all(len(v) <= 3 for v in out["items"].values()), str(out["items"])[:120])

        print("⑤ 真浏览器：页面 + 顶栏槽位角标")
        for name, ok, detail in browser_checks(url):
            check(name, ok, detail)
    finally:
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        os.environ.pop("ERW_PLUGINS_ROOTS", None)
        if saved_cfg is None:
            CONFIG.unlink(missing_ok=True)
        else:
            CONFIG.write_bytes(saved_cfg)
        if saved_json is None:
            PLUGINS_JSON.unlink(missing_ok=True)
        else:
            PLUGINS_JSON.write_bytes(saved_json)
        from core.plugins import jobs as plugin_jobs

        plugin_jobs.shutdown()
        shutil.rmtree(base, ignore_errors=True)

    print("⑥ 收尾")
    check("⑥-1 插件配置按原样恢复", (CONFIG.read_bytes() if CONFIG.is_file() else None) == saved_cfg)
    check("⑥-2 System/plugins.json 按原样恢复",
          (PLUGINS_JSON.read_bytes() if PLUGINS_JSON.is_file() else None) == saved_json)

    total = len(PASS) + len(FAIL)
    print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


def browser_checks(url: str) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [("⑤-0 playwright 可用", False, "pip install playwright")]
    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe if Path(exe).is_file() else None, headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 950}).new_page()
        errs: list[str] = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.goto(f"{url}/#{ID}", wait_until="networkidle", timeout=60000)
        page.wait_for_selector(f'#main[data-plugin="{ID}"]', timeout=30000)
        page.wait_for_selector(".mc-cell", timeout=30000)
        page.wait_for_timeout(800)
        cells = page.eval_on_selector_all(".mc-cell", "els => els.length")
        out.append(("⑤-1 月历渲染 42 格", int(cells) == 42, f"{cells} 格"))
        chips = page.inner_text("#mc-summary")
        out.append(("⑤-2 摘要显示逾期/今日计数", "逾期" in chips and "今日" in chips, chips[:90]))
        page.click('.mc-cell.has')
        page.wait_for_timeout(400)
        day = page.inner_text("#mc-day")
        out.append(("⑤-3 点某天显示当天明细", "项" in day, day[:80]))
        page.fill("#mc-days", "21")
        page.click("#mc-save")
        page.wait_for_timeout(1200)
        out.append(("⑤-4 改窗口并保存生效", "21" in page.inner_text("#mc-summary"), page.inner_text("#mc-summary")[:90]))
        # 顶栏槽位：内核写在容器上的是**面板 id**（本插件的角标面板 id = ID + '-badge'）
        badge_sel = f'[data-erw-slot="topbar"] [data-plugin="{ID}-badge"]'
        badge = page.eval_on_selector_all(badge_sel + " .mc-badge",
                                          "els => els.map(e => e.textContent.trim())")
        out.append(("⑤-5 顶栏槽位出现角标", bool(badge), str(badge)))
        box_title = page.eval_on_selector_all(badge_sel,
                                              "els => els.map(e => e.getAttribute('title') || '')")
        out.append(("⑤-6 角标带可读提示", bool(box_title and box_title[0]), str(box_title)))
        # 切到别的页面，角标必须还在（常驻）
        page.click('[data-route="overview"]')
        page.wait_for_timeout(700)
        still = page.eval_on_selector_all(badge_sel + " .mc-badge", "els => els.length")
        out.append(("⑤-7 切页后角标仍常驻", int(still) >= 1, f"{still} 个"))
        styled = page.eval_on_selector_all(badge_sel + " .mc-badge",
                                           "els => els.map(e => getComputedStyle(e).borderTopWidth)")
        out.append(("⑤-8 角标样式生效（前缀作用域命中）",
                    bool(styled) and styled[0] not in ("0px", ""), str(styled)))
        out.append(("⑤-9 0 console error", not errs, str(errs[:3])))
        browser.close()
    return out


if __name__ == "__main__":
    raise SystemExit(main())
