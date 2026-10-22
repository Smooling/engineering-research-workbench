from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config, indexer, store


def measure(fn: Callable[[], Any], repeat: int) -> dict[str, Any]:
    samples = []
    value = None
    for _ in range(max(1, repeat)):
        start = time.perf_counter()
        value = fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return {
        "min_ms": round(min(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "max_ms": round(max(samples), 3),
        "last_result_type": type(value).__name__,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Non-destructive Engineering Research Workbench performance benchmark")
    parser.add_argument("--query", default="research", help="FTS query used by the search benchmark")
    parser.add_argument("--repeat", type=int, default=3, help="number of warm measurements per operation")
    parser.add_argument("--rebuild", action="store_true", help="rebuild the disposable SQLite index before measuring")
    parser.add_argument("--assert-budget", action="store_true",
                        help="按下面的预算判定（超出则非零退出），用于守住已修好的热路径")
    parser.add_argument("--synthetic", type=int, default=0, metavar="COUNT", help="use a newly generated isolated workspace instead of personal data")
    args = parser.parse_args()

    #: 热路径预算（ms）。v261009.36 之前 `list_docs` 实测 731ms：`_doc_from_path` **每条文档**
    #: 都调一次 `ensure_workspace()`（每次 ~24 次 mkdir + stat），把 /api/docs 拖到 837ms。
    #: 现在 ensure_workspace 有进程级快路径、循环外只取一次 root，实测 ~76ms（200 条）。
    BUDGET_MS = {"store_list_docs": 250.0, "documents_page_50": 120.0, "dashboard": 200.0}
    from app import store

    if args.synthetic:
        scratch = ROOT / ".scratch"
        scratch.mkdir(exist_ok=True)
        data_root = Path(tempfile.mkdtemp(prefix="performance-", dir=scratch))
        config.ROOT = data_root
        config.CONFIG_DIR = data_root / "config"
        config.SECRET_PATH = config.CONFIG_DIR / "secret.json"
        config.LEGACY_SECRET_PATH = config.CONFIG_DIR / "secrets.json"
        config._cache = {}
        config.CONFIG_DIR.mkdir()
        (config.CONFIG_DIR / "app.json").write_text(json.dumps({
            "workspace": "Workspace", "workspace_migration": {"enabled": False}, "llm": {"enabled": False},
        }), encoding="utf-8")
        notes = data_root / "Workspace" / "Knowledge" / "Notes"
        notes.mkdir(parents=True)
        for i in range(args.synthetic):
            meta = {"id": f"note-{i:06}", "kind": "note", "title": f"Synthetic document {i}",
                    "created": "2026-10-01T00:00:00", "updated": "2026-10-01T00:00:00",
                    "tags": [f"topic-{i % 40}", f"group-{i % 15}"], "projects": [f"Project {i % 100}"]}
            (notes / f"note-{i:06}.md").write_text(store._frontmatter_dump(meta) + "Synthetic research body. " * 25, encoding="utf-8")

    cold_start = time.perf_counter()
    state = indexer.rebuild() if args.rebuild else indexer.initialize(force=False)
    indexer.stop_background_sync()
    cold_ms = (time.perf_counter() - cold_start) * 1000.0

    store.list_docs()          # 预热：ensure_workspace 快路径与本进程缓存
    first_page = indexer.list_docs(page=1, page_size=50, paged=True)
    sample_id = first_page["items"][0]["id"] if first_page.get("items") else ""

    results = {
        "index": state,
        "index_initialize_ms": round(cold_ms, 3),
        "store_list_docs": measure(store.list_docs, args.repeat),   # ← 全量条目（磁盘 + frontmatter）
        "documents_page_50": measure(lambda: indexer.list_docs(page=1, page_size=50, paged=True), args.repeat),
        "dashboard": measure(indexer.dashboard, args.repeat),
        "fts_search": measure(lambda: indexer.search_all(args.query, 50), args.repeat),
        "graph_overview_80": measure(lambda: indexer.graph_overview(80), args.repeat),
        "graph_initial_300": measure(lambda: indexer.graph(300), args.repeat),
        "project_records": measure(lambda: indexer.project_records(), args.repeat),
        "unchanged_filesystem_sync": measure(lambda: indexer.sync(immediate=True), args.repeat),
    }
    if sample_id:
        results["open_document_by_id"] = measure(lambda: indexer.get_doc(sample_id), args.repeat)
        if args.synthetic:
            doc = indexer.get_doc(sample_id)
            results["index_single_document"] = measure(lambda: indexer.index_doc_path(doc["path"]), args.repeat)
            results["save_single_document"] = measure(lambda: indexer.update_doc(sample_id, {"body": doc["body"]}), args.repeat)
    if args.synthetic:
        results["synthetic_data_root"] = str(data_root)
        (data_root / "benchmark-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(results, ensure_ascii=False, indent=2))

    if args.assert_budget:
        breaches = []
        print("\n热路径预算：")
        for name, budget in BUDGET_MS.items():
            got = results.get(name, {}).get("min_ms")
            if got is None:
                continue
            ok = got <= budget
            print(f"  {'ok  ' if ok else 'FAIL'} {name:20} {got:8.1f} ms  预算 {budget:.0f} ms")
            if not ok:
                breaches.append(name)
        if breaches:
            print(f"\n超预算：{breaches}")
            raise SystemExit(1)
        print("\n全部在预算内")


if __name__ == "__main__":
    main()
