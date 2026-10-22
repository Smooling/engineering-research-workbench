"""常驻测试运行器：`tests/**/test_*.py`（原 .scratch/tmp 里的深度夹具，v261009.36 起入库）。

```powershell
python tools/run_tests.py                # 全部（自动起一个临时工作台服务并把 URL 传给用例）
python tools/run_tests.py --fast         # 只跑不需要浏览器的（秒级~分钟级，日常用）
python tools/run_tests.py --only manual  # 只跑名字含 manual 的
python tools/run_tests.py --list         # 列清单不执行
python tools/run_tests.py --no-server    # 不起服务（用例自己起服务时用）
python tools/run_tests.py -v             # 打印每个用例的完整输出
```

约定（与 `tools/` 里那批闸门的分工）：
- **闸门脚本**（`kb_smoke` / `web_check` / `ui_smoke` / `plugin_check` / `doc_check` / `web_manifest`）
  = 改完必须跑的"快速档"，秒级；
- **本运行器** = "完整档"，把每个特性的验收脚本全跑一遍，分钟级。

用例约定：把 `sys.argv[1]` 当工作台 URL（没有就用自己的默认值）；自己起服务的用例忽略它；
标准输出里出现 `结果：N/M 通过` 时以它为准，否则看退出码。
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
SUMMARY_RE = re.compile(r"结果：(\d+)/(\d+)\s*通过")
SERVER_SNIPPET = (
    "import sys; sys.path.insert(0, r'{root}'); import server;"
    "h, c, u = server.build_server(port_override={port}, auto_open_browser=False);"
    "print('LISTENING', u, flush=True); h.serve_forever(poll_interval=0.25)"
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def discover() -> list[Path]:
    """`tests/<域>/test_*.py`；`tests/support/` 只放共用助手，不当用例。"""
    return sorted(p for p in TESTS.glob("*/*.py")
                  if p.name.startswith("test_") and p.parent.name != "support")


def needs_browser(path: Path) -> bool:
    return "playwright" in path.read_text(encoding="utf-8", errors="replace")


def start_server(port: int) -> tuple[subprocess.Popen, list[str]]:
    """起临时工作台。**必须持续排空它的 stdout**：管道写满后子进程会阻塞在 write 上，
    表现为"连接建立了但一直不响应"——用例多次启停插件时就会踩到（实测 40s 后开始超时）。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        [sys.executable, "-c", SERVER_SNIPPET.format(root=ROOT, port=port)],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    log: list[str] = []

    def drain() -> None:
        for line in proc.stdout:                      # 读到 EOF 为止
            log.append(line.rstrip())
            del log[:-400]                            # 只留最后 400 行备查

    threading.Thread(target=drain, daemon=True).start()
    deadline = time.time() + 60
    while time.time() < deadline and not any(x.startswith("LISTENING") for x in log):
        if proc.poll() is not None:
            raise SystemExit("临时服务启动失败：" + "\n".join(log[-8:]))
        time.sleep(0.2)
    if not any(x.startswith("LISTENING") for x in log):
        raise SystemExit("临时服务启动超时")
    return proc, log


def run_one(path: Path, url: str, timeout: int, verbose: bool) -> dict:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "ERW_BASE": url}
    started = time.perf_counter()
    try:
        proc = subprocess.run([sys.executable, str(path), url], cwd=str(ROOT), env=env,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "") if isinstance(exc.stdout, str) else ""
        code, timed_out = 124, True
    took = time.perf_counter() - started
    hits = SUMMARY_RE.findall(out)
    passed, total = (int(hits[-1][0]), int(hits[-1][1])) if hits else (1 if code == 0 else 0, 1)
    if verbose:
        print(out)
    return {"name": path.relative_to(TESTS).as_posix(), "code": code, "took": took,
            "passed": passed, "total": total, "timeout": timed_out, "tail": out[-1500:]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="跑 tests/ 下的常驻验收用例")
    ap.add_argument("--fast", action="store_true", help="跳过需要浏览器的用例")
    ap.add_argument("--only", default="", help="只跑名字含该关键词的用例")
    ap.add_argument("--list", action="store_true", help="只列清单")
    ap.add_argument("--no-server", action="store_true", help="不起临时服务")
    ap.add_argument("--timeout", type=int, default=600, help="单个用例超时秒数（默认 600）")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印用例完整输出")
    args = ap.parse_args(argv)

    tests = discover()
    if args.only:
        tests = [p for p in tests if args.only.lower() in p.name.lower()]
    if args.fast:
        tests = [p for p in tests if not needs_browser(p)]
    if not tests:
        print("没有匹配的用例", file=sys.stderr)
        return 2
    if args.list:
        for path in tests:
            print(f"  {path.relative_to(TESTS).as_posix():38} {'浏览器' if needs_browser(path) else '纯逻辑'}")
        print(f"合计 {len(tests)} 个（其中需要浏览器 {sum(1 for p in tests if needs_browser(p))} 个）")
        return 0

    server = None
    url = os.environ.get("ERW_BASE", "http://127.0.0.1:8799")
    if not args.no_server:
        port = free_port()
        server, server_log = start_server(port)
        url = f"http://127.0.0.1:{port}"
        print(f"临时工作台：{url}\n")

    results = []
    try:
        for index, path in enumerate(tests, 1):
            print(f"[{index}/{len(tests)}] {path.relative_to(TESTS).as_posix()} … ", end="", flush=True)
            item = run_one(path, url, args.timeout, args.verbose)
            results.append(item)
            mark = "PASS" if item["passed"] == item["total"] and item["code"] == 0 else "FAIL"
            print(f"{mark}  {item['passed']}/{item['total']}  {item['took']:.1f}s")
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

    failed = [r for r in results if r["passed"] != r["total"] or r["code"] != 0]
    total_pass = sum(r["passed"] for r in results)
    total_cases = sum(r["total"] for r in results)
    print("\n" + "=" * 68)
    for item in failed:
        print(f"\n✗ {item['name']}（{item['passed']}/{item['total']}，exit {item['code']}"
              f"{'，超时' if item['timeout'] else ''}）")
        print("  " + "\n  ".join(item["tail"].strip().splitlines()[-12:]))
        # CI 里日志要登录才能看；注解是公开的，把失败尾部塞进 ::error:: 便于直接定位。
        if os.environ.get("GITHUB_ACTIONS"):
            tail = "\n".join(item["tail"].strip().splitlines()[-8:])
            escaped = tail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
            print(f"::error title={item['name']} 失败::{escaped}")
    print("\n" + "=" * 68)
    print(f"用例 {len(results)} 个：通过 {len(results) - len(failed)} · 失败 {len(failed)}"
          f" · 断言 {total_pass}/{total_cases} · 用时 {sum(r['took'] for r in results):.0f}s")
    if failed:
        print("失败清单：" + "、".join(r["name"] for r in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
