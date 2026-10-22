"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
夹具：指标表插件（metrics-table）—— 提取/聚合/透视逻辑 + **真实数据上的作用** + 写入安全边界。

覆盖：
① 解析：```metrics 块（多块后者覆盖、注释/空行/`=` 写法、未闭合块、坏行）；
② 数值拆解：百分比 / 科学计数 / 单位 / 千分位 / 加粗数字 / 非数值；
③ 写入：追加、merge、replace、**正文其余部分逐字保留**、幂等、未闭合块拒绝写、空指标拒绝写；
④ 表格提取：数值列识别、对象列自动跳过「排名」、映射表（无数值列）被跳过、按行展开、加粗数字清理；
⑤ 聚合与透视：列并集与统计、缺项、pivot 把同名对象跨实验并到一行；
⑥ **真实数据**：在用户当前知识库上跑——必须真的能读出指标（这是「看出作用」的判据）；
⑦ 真服务器：路由、导出、**写工具在 confirm 模式只出草稿且条目一字未改**；
⑧ 真浏览器：页面**显示非空表格且能看到真实模型名**、模式切换、列收敛、0 console error；
⑨ 收尾：用户文件按原样恢复、不留夹具残留。

用法：`$env:PYTHONIOENCODING='utf-8'; python tests/plugins/test_metrics_table.py`
"""

from __future__ import annotations

import importlib.util
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
sys.path.insert(0, str(ROOT / "tests" / "support"))

import core_api  # noqa: E402
from fixture_cleanup import restore_many, snap_many  # noqa: E402

ID = "metrics-table"
PASS: list[str] = []
FAIL: list[str] = []
PLUGINS_JSON = ROOT / "Workspace" / "System" / "plugins.json"
CONFIG = ROOT / "config" / "plugins" / f"{ID}.json"
DRAFTS = ROOT / "Workspace" / "System" / "AgentChats" / "Drafts"


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"   ← {detail}" if detail and not cond else ""))


def load_backend():
    spec = importlib.util.spec_from_file_location("mt_backend", ROOT / "plugins" / ID / "backend.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
        return (r.status, dict(r.headers), data) if raw else json.loads(data.decode("utf-8"))


# ---------------------------------------------------------------- A. 逻辑

def logic_checks(mod) -> None:
    print("① 解析 ```metrics 块")
    body = "## 结果\n\n说明。\n\n```metrics\nmIoU: 0.732\nPd: 91%\n# 注释\n\nFa = 3.2e-6\n```\n\n尾注。\n"
    metrics, warns = mod.parse_metrics(body)
    check("①-1 基本解析（含 = 写法与注释/空行）",
          metrics == {"mIoU": "0.732", "Pd": "91%", "Fa": "3.2e-6"}, str(metrics))
    multi, _ = mod.parse_metrics("```metrics\nA: 1\n```\n\n中间\n\n```metrics\nA: 2\nB: 3\n```\n")
    check("①-2 多块后者覆盖", multi == {"A": "2", "B": "3"}, str(multi))
    unclosed, warns3 = mod.parse_metrics("```metrics\nA: 1\n没闭合\n")
    check("①-3 未闭合块被忽略并给警告", unclosed == {} and any("闭合" in w for w in warns3))
    junk, warns4 = mod.parse_metrics("```metrics\n没有冒号\nC: 4\n```\n")
    check("①-4 坏行只记警告", junk == {"C": "4"} and any("无法解析" in w for w in warns4))

    print("② 数值拆解")
    cases = [("0.732", (0.732, "")), ("91%", (91.0, "%")), ("3.2e-6", (3.2e-06, "")),
             ("25.4M", (25.4, "M")), ("1,234", (1234.0, "")), ("12ms", (12.0, "ms")),
             ("**0.7545**", (0.7545, "")), ("abc", (None, "abc")), ("—", (None, "—"))]
    bad = [(raw, mod.split_number(raw), want) for raw, want in cases if mod.split_number(raw) != want]
    check("②-1 百分比/科学计数/单位/千分位/加粗/非数值都对", not bad, str(bad))

    print("③ 写入块：正文其余部分逐字保留")
    original = "## 实验\n\n这是正文。\n\n## 结论\n\n有效。\n"
    appended = mod.upsert_metrics_block(original, {"mIoU": "0.7"})
    check("③-1 追加块且原正文完整保留",
          original.rstrip() in appended and "mIoU: 0.7" in appended, appended[-50:])
    merged = mod.upsert_metrics_block(appended, {"mIoU": "0.75", "Pd": "90%"})
    check("③-2 merge 更新同名键并新增",
          "mIoU: 0.75" in merged and "Pd: 90%" in merged and merged.count("```metrics") == 1)
    replaced = mod.upsert_metrics_block(merged, {"Fa": "1e-5"}, mode="replace")
    check("③-3 replace 只留传入的键", "Fa: 1e-5" in replaced and "mIoU" not in replaced)
    check("③-4 幂等", mod.upsert_metrics_block(merged, {"mIoU": "0.75", "Pd": "90%"}) == merged)
    check("③-5 只动块，正文头部逐字不变", merged.startswith(original.split("```")[0]))
    try:
        mod.upsert_metrics_block("```metrics\nA: 1\n（没闭合）\n", {"B": "2"})
        check("③-6 已有块未闭合时拒绝写", False, "居然写了")
    except ValueError as exc:
        check("③-6 已有块未闭合时拒绝写", "闭合" in str(exc))
    try:
        mod.upsert_metrics_block(original, {})
        check("③-7 空指标拒绝写", False, "居然写了")
    except ValueError:
        check("③-7 空指标拒绝写", True)

    print("④ 表格提取（关键：直接吃现有正文，不改数据）")
    sample = (
        "# 实验-对照（9.9）\n\n"
        "### 9.9 模型指标\n\n"
        "| 排名 | 模型 | #Params/M | mIoU_mean | Pd_mean | 出处 |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 1 | DNANet | 4.6966 | **0.7545** | 0.9588 | thop |\n"
        "| 2 | U-Net | 34.5259 | 0.7311 | 0.9465 | thop |\n\n"
        "### 9.9b 归档映射（没有数值列，应被跳过）\n\n"
        "| 环节 | 归档条目 | 本文保留 |\n| --- | --- | --- |\n"
        "| 指标语义 | [[知识-方法-X]] | 一、口径 |\n"
    )
    tables = mod.parse_tables(sample)
    check("④-1 解析出表格（含没有数值列的那张）", len(tables) == 2, str([len(t["rows"]) for t in tables]))
    numeric = [t for t in tables if len(t["numeric_cols"]) >= 1]
    check("④-2 只有数值表被认作指标表", len(numeric) == 1, str([t["header"] for t in tables]))
    table = numeric[0]
    check("④-3 数值列识别正确（#Params/M、mIoU_mean、Pd_mean；「排名」是序数不算指标）",
          [table["header"][c] for c in table["numeric_cols"]] == ["#Params/M", "mIoU_mean", "Pd_mean"],
          str([table["header"][c] for c in table["numeric_cols"]]))
    check("④-4 对象列自动跳过「排名」选到「模型」",
          table["object_col"] is not None and table["header"][table["object_col"]] == "模型",
          str(table["header"][table["object_col"]] if table["object_col"] is not None else None))
    check("④-5 小节名取自最近的标题", table["caption"] == "9.9 模型指标", str(table["caption"]))

    cfg = dict(mod.DEFAULT_CONFIG)
    records, _ = mod.extract_records(
        {"id": "experiment-9", "kind": "experiment", "title": "实验-对照（9.9）", "status": "完成",
         "projects": ["P"], "updated": "2026-10-10T10:00:00"}, sample, cfg)
    check("④-6 按行展开成 2 条记录（映射表不产出记录）",
          len(records) == 2 and [r["object"] for r in records] == ["DNANet", "U-Net"],
          str([r["object"] for r in records]))
    check("④-7 加粗数字被清理成纯数值",
          records[0]["metrics"]["mIoU_mean"] == "0.7545", str(records[0]["metrics"]))
    check("④-8 非数值列作为附带信息保留", records[0]["extra"].get("出处") == "thop", str(records[0]["extra"]))
    check("④-9 实验短名取自标题编号", records[0]["short"] == "9.9", str(records[0]["short"]))

    print("⑤ 聚合与透视")
    more = [{"id": "experiment-10", "kind": "experiment", "title": "实验-复核（9.10）", "status": "完成",
             "projects": ["P"], "updated": "2026-10-11T10:00:00"}]
    sample2 = ("| 模型 | mIoU_mean | Pd_mean |\n| --- | --- | --- |\n| DNANet | 0.7600 | 0.9600 |\n")
    records += mod.extract_records(more[0], sample2, cfg)[0]
    table_data = mod.build_table(records)
    keys = [c["key"] for c in table_data["columns"]]
    check("⑤-1 列并集", keys == ["#Params/M", "mIoU_mean", "Pd_mean"], str(keys))
    mIoU = next(c for c in table_data["columns"] if c["key"] == "mIoU_mean")
    check("⑤-2 统计正确（DNANet 两次）",
          mIoU["filled"] == 3 and abs(mIoU["mean"] - (0.7545 + 0.7311 + 0.76) / 3) < 1e-9, str(mIoU))
    check("⑤-3 缺项列出", records[0]["missing"] == [], str(records[0]["missing"]))
    pivot = mod.pivot_by_object(records)
    dnanet = next(r for r in pivot["rows"] if r["object"] == "DNANet")
    check("⑤-4 透视把同名对象跨实验并成一行",
          dnanet["metrics"].get("mIoU_mean@9.9") == "0.7545"
          and dnanet["metrics"].get("mIoU_mean@9.10") == "0.7600", str(dnanet["metrics"]))
    check("⑤-5 透视行记录来源实验", dnanet["entries"] == ["9.10", "9.9"], str(dnanet["entries"]))
    check("⑤-6 CSV 带 BOM 且表头含来源列",
          mod.to_csv(table_data).startswith("\ufeff") and "对象,条目,实验,小节,来源" in mod.to_csv(table_data))
    check("⑤-7 Markdown 空表不炸", "没有找到指标" in mod.to_markdown({"columns": [], "rows": []}))

    # 同名对象在同一实验里出现多次（模型 × 数据集逐行）→ 透视必须区分，不能静默覆盖
    multi = ("| 模型 | 数据集 | mIoU |\n| --- | --- | --- |\n"
             "| ACM | NUAA-SIRST | 0.6582 |\n| ACM | NUDT-SIRST | 0.6810 |\n| ACM | IRSTD-1K | 0.6209 |\n")
    mrows, _ = mod.extract_records(
        {"id": "experiment-11", "kind": "experiment", "title": "实验-逐数据集（9.11）", "status": "完成",
         "projects": ["P"], "updated": "2026-10-12T10:00:00"}, multi, cfg)
    mp = mod.pivot_by_object(mrows)
    acm = [r for r in mp["rows"] if str(r["object"]).startswith("ACM")]
    check("⑤-8 透视不静默覆盖：同名对象按附带信息（数据集）区分出 3 行",
          len(acm) == 3 and len({r["metrics"].get("mIoU@9.11") for r in acm}) == 3,
          str([(r["object"], r["metrics"]) for r in mp["rows"]]))
    check("⑤-9 分组视图的前提：附带列被保留（数据集）",
          all("数据集" in (r.get("extra") or {}) for r in mrows), str([r.get("extra") for r in mrows]))


# ---------------------------------------------------------------- B. 真实数据

def real_data_checks() -> None:
    print("⑥ 真实数据：在用户当前知识库上必须真能读出指标（「看出作用」的判据）")
    mod = load_backend()
    cfg = dict(mod.DEFAULT_CONFIG)
    rows = core_api.entries("experiment", limit=400)
    records: list[dict] = []
    for row in rows:
        try:
            body = str(core_api.entry(str(row["id"])).get("body") or "")
        except FileNotFoundError:
            continue
        found, _ = mod.extract_records(row, body, cfg)
        records.extend(found)
    check("⑥-1 实验条目能被扫到", len(rows) >= 10, f"{len(rows)} 条")
    check("⑥-2 从**现有正文**提取出大量记录（不需要改写任何条目）", len(records) >= 50, f"{len(records)} 条")
    src_table = sum(1 for r in records if r["source"] == "table")
    check("⑥-3 绝大多数来自正文表格", src_table >= len(records) * 0.8, f"表格={src_table} 总={len(records)}")

    table = mod.build_table(records)
    keys = [c["key"] for c in table["columns"]]
    check("⑥-4 出现可辨识的指标列（mIoU/Pd/Fa/Params 一类）",
          any(k in keys for k in ("mIoU_mean", "mIoU", "Pd_mean", "Pd", "Fa_mean", "#Params/M")),
          str(keys[:12]))
    dnanet = [r for r in table["rows"] if r["object"] == "DNANet"]
    check("⑥-5 能读出真实模型行（DNANet）", bool(dnanet), str([r["object"] for r in table["rows"][:6]]))
    mIoU = next((c for c in table["columns"] if c["key"] == "mIoU_mean"), None)
    check("⑥-6 mIoU_mean 列有真实统计（9 个模型、最优 0.7545）",
          bool(mIoU) and mIoU["filled"] >= 8 and abs((mIoU["max"] or 0) - 0.7545) < 1e-6, str(mIoU))
    row_22 = next((r for r in dnanet if r["short"] == "2.2" and "参数量" in str(r["scope"])), None)
    check("⑥-7 DNANet 在 2.2 的 mIoU_mean = 0.7545（与正文一致）",
          bool(row_22) and row_22["metrics"].get("mIoU_mean") == "0.7545",
          str(row_22["metrics"] if row_22 else [r["scope"] for r in dnanet]))
    check("⑥-8 记录了来源小节（可追溯）", bool(row_22 and row_22["scope"]), str(row_22["scope"] if row_22 else None))

    pivot = mod.pivot_by_object(records)
    dn = next((r for r in pivot["rows"] if r["object"] == "DNANet"), None)
    check("⑥-9 透视模式：DNANet 跨实验出现在同一行",
          bool(dn) and len(dn["entries"]) >= 2, str(dn["entries"] if dn else None))
    check("⑥-10 透视列带实验后缀（跨实验对照）",
          any("@2.2" in c["key"] for c in pivot["columns"]), str([c["key"] for c in pivot["columns"]][:8]))

    default_cols = [c for c in table["columns"] if c["filled"] >= 2]
    check("⑥-11 单张来源表的列数可读（分组呈现的前提）",
          max((len({k for r in records if (r["entry_id"], r["scope"]) == key for k in r["metrics"]})
               for key in {(r["entry_id"], r["scope"]) for r in records}), default=0) <= 15,
          "最大列数=" + str(max((len({k for r in records if (r["entry_id"], r["scope"]) == key for k in r["metrics"]})
                                for key in {(r["entry_id"], r["scope"]) for r in records}), default=0)))
    check("⑥-12 来源表张数足够多（分组视图才有意义）",
          len({(r["entry_id"], r["scope"]) for r in records}) >= 8,
          f"{len({(r['entry_id'], r['scope']) for r in records})} 张")
    check("⑥-13 序数列（排名）没有被当成指标",
          "排名" not in [c["key"] for c in table["columns"]], str([c["key"] for c in table["columns"]][:8]))


# ---------------------------------------------------------------- C. 真服务器与浏览器

def live_checks() -> None:
    base = Path(tempfile.mkdtemp(prefix="erwmt-"))
    root = base / "plugins"
    root.mkdir(parents=True)
    shutil.copytree(ROOT / "plugins" / ID, root / ID)
    httpd = None
    saved_json = PLUGINS_JSON.read_bytes() if PLUGINS_JSON.is_file() else None
    saved_cfg = CONFIG.read_bytes() if CONFIG.is_file() else None
    drafts_before = {p.name for p in DRAFTS.glob("draft-*.json")} if DRAFTS.is_dir() else set()
    ns_before = snap_many([ROOT / "Workspace" / "Plugins" / ID,
                           ROOT / "Workspace" / "System" / "Plugins" / ID])
    try:
        os.environ["ERW_PLUGINS_ROOTS"] = str(root)
        import server
        from app import agent_tools

        httpd, _c, url = server.build_server(port_override=free_port(), auto_open_browser=False)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
        for _ in range(60):
            try:
                request(f"{url}/api/plugins")
                break
            except Exception:
                time.sleep(0.25)
        request(f"{url}/api/plugin-manager/{ID}/enabled", {"enabled": True})

        print("⑦ 真服务器：路由 / 导出 / 写入安全边界")
        table = request(f"{url}/api/plugins/{ID}/table")
        check("⑦-1 表格路由在真实知识库上就有内容（不再是空表）",
              table.get("with_metrics", 0) > 50, f"命中 {table.get('with_metrics')} 条记录")
        check("⑦-2 来源分布里表格占多数",
              (table.get("sources") or {}).get("table", 0) > 50, str(table.get("sources")))
        pivot = request(f"{url}/api/plugins/{ID}/table?mode=pivot")
        check("⑦-3 透视模式可用且有对象", pivot.get("pivot") is True and len(pivot.get("rows") or []) > 5,
              f"{len(pivot.get('rows') or [])} 个对象")

        code, headers, body = request(f"{url}/api/plugins/{ID}/export?format=csv", raw=True)
        text = body.decode("utf-8-sig")
        check("⑦-4 CSV 导出含真实模型与指标", code == 200 and "DNANet" in text and "mIoU_mean" in text,
              text[:120])
        code, headers, body = request(f"{url}/api/plugins/{ID}/export?format=md&mode=pivot", raw=True)
        check("⑦-5 Markdown 透视导出可下载", code == 200 and "attachment" in headers.get("Content-Disposition", ""))

        any_entry = request(f"{url}/api/docs?paged=1&page_size=1").get("items") or []
        target = str(any_entry[0]["id"]) if any_entry else ""
        if target:
            before = request(f"{url}/api/plugins/{ID}/entry?id={target}")
            pending = agent_tools.execute(f"p_{ID}__record_metrics",
                                          {"entry_id": target, "metrics": {"夹具指标": "0.123"}},
                                          {"write_mode": "confirm"})
            check("⑦-6 confirm 模式只出草稿不执行",
                  pending.get("pending") is True and str(pending.get("draft_id", "")).startswith("draft-"))
            after = request(f"{url}/api/plugins/{ID}/entry?id={target}")
            check("⑦-7 **条目正文一字未改**（草稿未确认）", before.get("preview") == after.get("preview"))
            agent_tools.reject_draft(pending["draft_id"])
            final = request(f"{url}/api/plugins/{ID}/entry?id={target}")
            check("⑦-8 拒绝草稿后仍然未改", final.get("preview") == before.get("preview"))

        print("⑧ 真浏览器：页面必须显示真实数据")
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
        if saved_json is None:
            PLUGINS_JSON.unlink(missing_ok=True)
        else:
            PLUGINS_JSON.write_bytes(saved_json)
        if saved_cfg is None:
            CONFIG.unlink(missing_ok=True)
        else:
            CONFIG.write_bytes(saved_cfg)
        for path in (DRAFTS.glob("draft-*.json") if DRAFTS.is_dir() else []):
            if path.name not in drafts_before:
                path.unlink()
        from core.plugins import jobs as plugin_jobs

        plugin_jobs.shutdown()
        restore_many(ns_before)
        shutil.rmtree(base, ignore_errors=True)

    print("⑨ 收尾")
    check("⑨-1 plugins.json 按原样恢复",
          (PLUGINS_JSON.read_bytes() if PLUGINS_JSON.is_file() else None) == saved_json)
    check("⑨-2 插件配置无残留", (CONFIG.read_bytes() if CONFIG.is_file() else None) == saved_cfg)
    left = {p.name for p in DRAFTS.glob("draft-*.json")} if DRAFTS.is_dir() else set()
    check("⑨-3 夹具产生的草稿已清理", left == drafts_before, f"left={sorted(left - drafts_before)}")
    leftover = {k: [str(p.relative_to(Path(k))) for p in Path(k).rglob("*")
                    if p.is_file() and str(p.relative_to(Path(k))).replace("\\", "/") not in v[1]]
                for k, v in ns_before.items() if Path(k).exists()}
    check("⑨-4 插件命名空间没有本次新增文件", not any(leftover.values()), str(leftover))


def browser_checks(url: str) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [("⑧-0 playwright 可用", False, "pip install playwright")]
    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe if Path(exe).is_file() else None, headless=True)
        page = browser.new_context(viewport={"width": 1600, "height": 950}).new_page()
        errs: list[str] = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.goto(f"{url}/#{ID}", wait_until="networkidle", timeout=60000)
        page.wait_for_selector(f'#main[data-plugin="{ID}"]', timeout=30000)
        page.wait_for_selector(".mt-table tbody tr", timeout=60000)
        page.wait_for_timeout(1000)
        summary = page.inner_text("#mt-summary")
        out.append(("⑧-1 摘要显示命中记录数（不是 0）", "命中" in summary and " 0 " not in summary, summary[:100]))
        text = page.inner_text(".mt-table")
        out.append(("⑧-2 表格里能看到真实模型名（DNANet / U-Net）",
                    "DNANet" in text or "U-Net" in text, text[:120]))
        out.append(("⑧-3 表格里能看到真实指标列（mIoU_mean / Pd_mean）",
                    "mIoU_mean" in text or "Pd_mean" in text, text[:160]))
        rows = page.eval_on_selector_all(".mt-table tbody tr", "els => els.length")
        out.append(("⑧-4 渲染出多行（>5）", int(rows) > 5, f"{rows} 行"))
        page.select_option("#mt-mode", "pivot")
        page.wait_for_timeout(1500)
        pivot_text = page.inner_text(".mt-table")
        out.append(("⑧-5 透视模式渲染并带实验后缀", "@2.2" in pivot_text or "@2.1" in pivot_text,
                    pivot_text[:140]))
        page.select_option("#mt-mode", "records")
        page.wait_for_timeout(1200)
        page.fill("#mt-kw", "DNANet")
        page.wait_for_timeout(600)
        filtered = page.eval_on_selector_all(".mt-table tbody tr", "els => els.length")
        out.append(("⑧-6 关键词过滤生效（行数变少）", 0 < int(filtered) < int(rows), f"{filtered} 行"))
        page.click("[data-mt-g]")            # 统计行也在 tbody 里，必须点真正的数据行
        page.wait_for_timeout(400)
        detail = page.inner_text("#mt-detail")
        out.append(("⑧-7 点行显示来源与小节（可追溯）", "对象" in detail and "小节" in detail, detail[:140]))
        out.append(("⑧-8 0 console error", not errs, str(errs[:3])))
        browser.close()
    return out


def main() -> int:
    print("=== A. 逻辑（内存注入，不碰知识库）===")
    logic_checks(load_backend())
    print("\n=== B. 真实数据（只读）===")
    real_data_checks()
    print("\n=== C. 真服务器与真浏览器 ===")
    live_checks()
    total = len(PASS) + len(FAIL)
    print(f"\n结果：{len(PASS)}/{total} 通过" + (f"，失败 {len(FAIL)}：{FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
