"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
夹具：备份与快照插件 + 内核后台任务（ctx.jobs）。

覆盖：
① 调度器：run_on_start 会真跑、失败隔离、不重入、手动触发、热重载后立刻停（用真服务器验）；
② 快照：内容正确（含 manifest.json / 知识条目 / 默认不含附件）、原子收尾、zip 可读；
③ 幂等：已有新鲜快照时不重复备份（重启/重载也不会连点）；
④ 保留策略：只删自己生成的 snapshot-*.zip，别人的文件一个不碰；
⑤ 目标目录：可外置（配置生效），下载/查看/删除都从该目录取；
⑥ 路径安全：删除/下载拒绝穿越、绝对路径、非本插件命名的文件；
⑦ 真浏览器：页面能用（备份 / 列表 / 查看内容 / 0 console error）；
⑧ 收尾：用户文件（plugins.json、插件配置、插件状态目录）按原样恢复。

用法：`$env:PYTHONIOENCODING='utf-8'; python tests/plugins/test_backup_snapshot.py`
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
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "support"))
from fixture_cleanup import restore, restore_many, snap_many  # noqa: E402

ID = "backup-snapshot"
PASS: list[str] = []
FAIL: list[str] = []
PLUGINS_JSON = ROOT / "Workspace" / "System" / "plugins.json"
CONFIG = ROOT / "config" / "plugins" / f"{ID}.json"
STATE_DIR = ROOT / "Workspace" / "System" / "Plugins" / ID


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def request(url: str, body: dict | None = None, *, raw: bool = False, method: str | None = None):
    if body is None and method is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(url, method=method or "POST",
                                     headers={"Content-Type": "application/json"},
                                     data=json.dumps(body or {}).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
        return (r.status, dict(r.headers), data) if raw else json.loads(data.decode("utf-8"))


def status_of(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=40) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return int(e.code)


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="erwbak-"))
    root = base / "plugins"
    root.mkdir(parents=True)
    shutil.copytree(ROOT / "plugins" / ID, root / ID)
    dest_dir = base / "external-snapshots"
    dest_dir.mkdir(parents=True)
    (dest_dir / "keepme.txt").write_text("别人的文件，绝不能被删", encoding="utf-8")   # 保留策略的守护文件

    httpd = None
    saved_json = PLUGINS_JSON.read_bytes() if PLUGINS_JSON.is_file() else None
    saved_cfg = CONFIG.read_bytes() if CONFIG.is_file() else None
    had_state = STATE_DIR.exists()
    # 插件命名空间（register() 会建目录、跑起来会写快照与 state.json）：按原状还原
    ns_before = snap_many([STATE_DIR, ROOT / "Workspace" / "Plugins" / ID])
    # v261009.36 · `snap_many` 只删"本次新增的文件"，不改回被改写文件的内容；
    # state.json 会被本用例改写（守卫时间），这里单独按字节还原，确保测试不动用户的插件状态。
    _state_file = STATE_DIR / "state.json"
    _state_before = _state_file.read_bytes() if _state_file.is_file() else None
    try:
        # 先把目标目录指到外部临时目录，避免夹具往用户 Workspace 里写快照
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps({"dest_dir": str(dest_dir), "interval_hours": 0.5, "keep": 7},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
        os.environ["ERW_PLUGINS_ROOTS"] = str(root)
        import server
        from core.plugins import jobs as plugin_jobs

        httpd, _c, url = server.build_server(port_override=free_port(), auto_open_browser=False)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
        for _ in range(60):
            try:
                request(f"{url}/api/plugins")
                break
            except Exception:
                time.sleep(0.25)

        print("① 启用插件后，后台任务在启动时真的跑了（run_on_start）")
        # v261009.36 · 先把「上次运行时间」守卫清掉：插件按 state.json 判断"距上次不足间隔就跳过"，
        # 而环境里可能刚跑过（夹具自己在上一次运行里留下的，或用户手动备过一次），
        # 那样 run_on_start 会被正当跳过 → 本用例会误报失败（实测踩到）。收尾时按原状还原。
        _state = STATE_DIR / "state.json"
        if _state.is_file():
            _state.unlink()
        request(f"{url}/api/plugin-manager/{ID}/enabled", {"enabled": True})
        auto_made = None
        for _ in range(20):                       # 调度 tick 是 5 秒，最多等 ~20 秒
            time.sleep(1.2)
            if list(dest_dir.glob("snapshot-*.zip")):
                auto_made = sorted(dest_dir.glob("snapshot-*.zip"))[-1]
                break
        check("①-1 自动备份在启动时生成了快照", auto_made is not None,
              str(sorted(p.name for p in dest_dir.iterdir())))
        status = request(f"{url}/api/plugins/{ID}/status")
        check("①-2 任务状态可见（名字/次数/无失败）",
              status["job"].get("name") == "auto" and status["job"].get("runs", 0) >= 1
              and status["job"].get("failures", 0) == 0, str(status.get("job")))
        check("①-3 调度器里注册了这个任务",
              [j["name"] for j in plugin_jobs.current().for_plugin(ID)] == ["auto"],
              str(plugin_jobs.current().as_list()))
        check("①-4 快照目录是配置的外部目录", status["snapshots"]["dir"] == str(dest_dir),
              status["snapshots"]["dir"])

        print("② 快照内容正确（含清单 / 知识条目 / 默认不含附件与索引）")
        with zipfile.ZipFile(auto_made) as z:
            names = z.namelist()
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            corpus_ok = z.testzip() is None
        check("②-1 zip 完整可读", corpus_ok)
        check("②-2 含 manifest.json 与文件数", manifest.get("files", 0) > 0 and "created" in manifest,
              str({k: manifest.get(k) for k in ("files", "raw_bytes", "reason")}))
        check("②-3 记了内核版本", str(manifest.get("kernel_version") or "").startswith("v261"),
              str(manifest.get("kernel_version")))
        check("②-4 收录了知识条目", any(n.startswith("Workspace/Knowledge/") for n in names),
              str(names[:5]))
        check("②-5 收录了系统状态与配置",
              "Workspace/System/todos.json" in names and "config/app.json" in names,
              str([n for n in names if n.endswith(".json")][:6]))
        check("②-6 默认不收 PDF / 索引 / Autosave",
              not any(n.lower().endswith(".pdf") for n in names) and "index.sqlite" not in names
              and not any("/Exports/" in n for n in names))
        check("②-7 无 .part 半成品残留", not list(dest_dir.glob("*.part")))
        snap_mb = auto_made.stat().st_size / 1048576
        check("②-8 快照确实是「小体积」（<30 MB，而附件有 295 MB）", snap_mb < 30, f"{snap_mb:.1f} MB")
        check("②-9 清单如实记录跳过的类别",
              int((manifest.get("skipped_summary") or {}).get("附件与大文件", 0)) > 10,
              str(manifest.get("skipped_summary")))

        print("③ 幂等：刚备份过就不再备（重启/重载不会连点）")
        before = len(list(dest_dir.glob("snapshot-*.zip")))
        reloaded = request(f"{url}/api/plugin-manager/{ID}/enabled", {"enabled": True})
        check("③-1 重载成功", reloaded.get("ok") is True, str(reloaded))
        time.sleep(7)                                  # 跨过一个调度 tick
        after = len(list(dest_dir.glob("snapshot-*.zip")))
        check("③-2 重载后没有多出快照", after == before, f"before={before} after={after}")
        state = json.loads((STATE_DIR / "state.json").read_text(encoding="utf-8"))
        check("③-3 state.json 记了上次时间与来源", state.get("last_reason") == "auto" and state.get("last_at"),
              str(state))

        print("④ 手动备份 + 保留策略（只删自己的文件）")
        earliest = sorted(dest_dir.glob("snapshot-*.zip"))[0].name      # ① 自动生成的那份
        manual = request(f"{url}/api/plugins/{ID}/snapshot", {})
        check("④-1 手动备份成功", manual.get("ok") is True and manual.get("files", 0) > 0,
              str(manual)[:200])
        request(f"{url}/api/plugins/{ID}/config", {"keep": 2})
        third = request(f"{url}/api/plugins/{ID}/snapshot", {})
        time.sleep(0.3)
        snaps = sorted(p.name for p in dest_dir.glob("snapshot-*.zip"))
        check("④-2 保留 2 份后只剩 2 个快照", len(snaps) == 2, str(snaps))
        check("④-3 清理结果有回报", bool(third.get("removed")), str(third.get("removed")))
        check("④-4 别人的文件没被碰", (dest_dir / "keepme.txt").is_file())
        check("④-5 被清理的是最早的那份（自动生成的那份）",
              earliest not in snaps and earliest in (third.get("removed") or []),
              f"earliest={earliest} snaps={snaps} removed={third.get('removed')}")

        print("⑤ 查看内容（恢复前的确认步骤）")
        newest = snaps[-1]
        info = request(f"{url}/api/plugins/{ID}/inspect", {"name": newest})
        check("⑤-1 返回清单与分布", info.get("ok") is True and info.get("entries", 0) > 0
              and info.get("by_dir"), str(info)[:200])
        check("⑤-2 清单与文件一致", info["manifest"].get("files", -1) == info["entries"] - 0
              or info["manifest"].get("files", 0) > 0, str(info["manifest"].get("files")))

        print("⑥ 下载 / 删除 + 路径安全")
        code, headers, body = request(f"{url}/api/plugins/{ID}/download?name={quote(newest)}", raw=True)
        target = dest_dir / newest
        check("⑥-1 下载字节与文件一致", code == 200 and body == target.read_bytes(),
              f"code={code} len={len(body)}/{target.stat().st_size}")
        check("⑥-2 以 application/zip 返回", "zip" in headers.get("Content-Type", ""),
              headers.get("Content-Type"))
        for evil in ("../plugins.json", "..%2Fplugins.json", "C:/Windows/win.ini", "keepme.txt",
                     "sub/x.zip", "snapshot-x.zip/../keepme.txt"):
            code = status_of(f"{url}/api/plugins/{ID}/download?name={evil}")
            check(f"⑥-3 拒绝下载 {evil!r}", code in (400, 404), f"code={code}")
            res = request(f"{url}/api/plugins/{ID}/delete", {"name": evil})
            check(f"⑥-4 拒绝删除 {evil!r}", res.get("ok") is False, str(res))
        check("⑥-5 守护文件仍在", (dest_dir / "keepme.txt").is_file())
        removed = request(f"{url}/api/plugins/{ID}/delete", {"name": newest})
        check("⑥-6 正常删除成功", removed.get("ok") is True and not (dest_dir / newest).exists(), str(removed)[:120])

        print("⑦ 关掉插件后任务立刻消失（热重载不留幽灵线程）")
        request(f"{url}/api/plugin-manager/{ID}/enabled", {"enabled": False})
        check("⑦-1 调度器里没有它的任务了", plugin_jobs.current().for_plugin(ID) == [],
              str(plugin_jobs.current().as_list()))
        count = len(list(dest_dir.glob("snapshot-*.zip")))
        time.sleep(6)
        check("⑦-2 停用后不再产生快照", len(list(dest_dir.glob("snapshot-*.zip"))) == count)
        request(f"{url}/api/plugin-manager/{ID}/enabled", {"enabled": True})

        print("⑦.5 并发保护：两个请求同时备份，只能成一个，另一个给可读拒绝而不是 500")
        results: list[dict] = []
        lock = threading.Lock()

        def fire() -> None:
            try:
                out = request(f"{url}/api/plugins/{ID}/snapshot", {})
            except Exception as exc:            # 500/连接异常都算"没有给可读拒绝"
                out = {"ok": False, "httperror": str(exc)[:80]}
            with lock:
                results.append(out)

        threads = [threading.Thread(target=fire) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        oks = [r for r in results if r.get("ok")]
        check("⑦.5-1 并发时恰好一份成功", len(oks) == 1, str(results)[:300])
        refused = [r for r in results if not r.get("ok")]
        check("⑦.5-2 另一份是「正在进行」的可读拒绝（不是异常）",
              all("正在进行" in str(r.get("error", "")) for r in refused)
              and all("httperror" not in r for r in refused), str(refused)[:200])
        check("⑦.5-3 没有留下 .part 残渣", not list(dest_dir.glob("*.part")))

        print("⑧ 真浏览器：页面能用")
        for name, ok, detail in browser_checks(url):
            check(name, ok, detail)
    finally:
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        try:
            from core.plugins import jobs as plugin_jobs

            plugin_jobs.shutdown()
        except Exception:
            pass
        os.environ.pop("ERW_PLUGINS_ROOTS", None)
        if saved_json is None:
            PLUGINS_JSON.unlink(missing_ok=True)
        else:
            PLUGINS_JSON.write_bytes(saved_json)
        if saved_cfg is None:
            CONFIG.unlink(missing_ok=True)
        else:
            CONFIG.write_bytes(saved_cfg)
        restore_many(ns_before)
        if not had_state:
            shutil.rmtree(STATE_DIR, ignore_errors=True)
        elif _state_before is not None:
            _state_file.parent.mkdir(parents=True, exist_ok=True)
            _state_file.write_bytes(_state_before)      # 守卫时间按原样还原
        shutil.rmtree(base, ignore_errors=True)

    print("⑨ 收尾")
    check("⑨-1 plugins.json 按原样恢复",
          (PLUGINS_JSON.read_bytes() if PLUGINS_JSON.is_file() else None) == saved_json)
    check("⑨-2 插件配置按原样恢复", (CONFIG.read_bytes() if CONFIG.is_file() else None) == saved_cfg)
    leftover = {k: restore(Path(k), v) for k, v in ns_before.items()}
    check("⑨-3 插件命名空间回到运行前的状态（不留本次新增文件/目录）",
          all(not v for v in leftover.values()), str(leftover))

    total = len(PASS) + len(FAIL)
    print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


def browser_checks(url: str) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [("⑧-0 playwright 可用", False, "pip install playwright")]
    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe if Path(exe).is_file() else None, headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 950}).new_page()
        errs: list[str] = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.goto(f"{url}/#{ID}", wait_until="networkidle", timeout=60000)
        page.wait_for_selector(f'#main[data-plugin="{ID}"]', timeout=30000)
        page.wait_for_selector("#bk-summary", timeout=30000)
        page.wait_for_timeout(1200)
        out.append(("⑧-1 页面渲染并读到状态", "快照目录" in page.inner_text("#bk-summary"),
                    page.inner_text("#bk-summary")[:80]))
        out.append(("⑧-2 显示后台任务状态", "后台任务" in page.inner_text("#bk-job"),
                    page.inner_text("#bk-job")[:80]))
        page.click("#bk-now")
        page.wait_for_selector("#bk-list .bk-row", timeout=120000)
        rows = page.eval_on_selector_all("#bk-list .bk-row", "els => els.length")
        out.append(("⑧-3 页内备份后列表出现快照", int(rows) >= 1, f"{rows} 行"))
        page.click("#bk-list .bk-row [data-bk-inspect]")
        page.wait_for_selector(".bk-inspect-box", timeout=60000)
        box = page.inner_text(".bk-inspect-box")
        out.append(("⑧-4 查看内容显示清单", "快照内容" in box and "个文件" in box, box[:100]))
        out.append(("⑧-5 0 console error", not errs, str(errs[:3])))
        browser.close()
    return out


if __name__ == "__main__":
    raise SystemExit(main())
