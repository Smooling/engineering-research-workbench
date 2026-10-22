"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
证明 VACUUM/checkpoint 语义中性：原库 vs 处理后副本，逐项查询结果必须完全一致。"""
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "Workspace" / "System" / "Cache" / "index.sqlite"
WORK = ROOT / ".scratch" / "verify" / "migrate"
DST = WORK / "vac_check.sqlite"

for suffix in ("", "-wal", "-shm"):
    p = Path(str(DST) + suffix)
    if p.exists():
        p.unlink()
import shutil  # noqa: E402

shutil.copy2(SRC, DST)
# 一并带走 WAL，保证副本与源库状态一致
if Path(str(SRC) + "-wal").is_file():
    shutil.copy2(str(SRC) + "-wal", str(DST) + "-wal")

QUERIES = [
    ("documents 总数", "SELECT COUNT(*) FROM documents"),
    ("按 kind 计数", "SELECT kind, COUNT(*) FROM documents GROUP BY kind ORDER BY kind"),
    ("document_links role 分布",
     "SELECT role, COUNT(*) FROM document_links GROUP BY role ORDER BY role"),
    ("graph_edges 关系分布",
     "SELECT relation, COUNT(*) FROM graph_edges GROUP BY relation ORDER BY relation"),
    ("document_projects", "SELECT COUNT(*) FROM document_projects"),
    ("document_tags", "SELECT COUNT(*) FROM document_tags"),
    ("document_marks", "SELECT COUNT(*) FROM document_marks"),
    ("FTS 命中（质心）",
     "SELECT doc_id FROM documents_fts WHERE documents_fts MATCH '质心' ORDER BY doc_id"),
    ("FTS 命中（数据集）",
     "SELECT doc_id FROM documents_fts WHERE documents_fts MATCH '数据集' ORDER BY doc_id"),
    ("标题样本", "SELECT id, title FROM documents ORDER BY id LIMIT 5"),
]


def snapshot(path: Path) -> dict:
    c = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    out = {}
    try:
        for name, sql in QUERIES:
            try:
                out[name] = list(c.execute(sql))
            except sqlite3.Error as exc:
                out[name] = f"ERR {exc}"
        out["schema"] = sorted(
            r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','index') ORDER BY name"
            )
        )
    finally:
        c.close()
    return out


before = snapshot(DST)
print(f"处理前：{DST.stat().st_size / 1048576:.2f} MB")

r = subprocess.run(
    [sys.executable, "-m", "core.index.maintain", "--db", str(DST), "--checkpoint", "--vacuum", "--json"],
    capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
)
if r.returncode != 0:
    print("维护命令失败：", r.stderr[-400:])
    raise SystemExit(1)
after = snapshot(DST)
print(f"处理后：{DST.stat().st_size / 1048576:.2f} MB")

FAILS = []
for name, _sql in QUERIES:
    if before[name] != after[name]:
        FAILS.append(name)
        print(f"FAIL {name}\n  前: {before[name]}\n  后: {after[name]}")
    else:
        print(f"PASS {name}  · {str(before[name])[:70]}")
if before["schema"] != after["schema"]:
    FAILS.append("schema")
    print("FAIL schema 变化：", set(before["schema"]) ^ set(after["schema"]))
else:
    print(f"PASS schema 对象集合不变（{len(before['schema'])} 个）")

print()
print("结果：全部一致（VACUUM/checkpoint 语义中性）" if not FAILS else f"结果：{FAILS} 不一致")
raise SystemExit(1 if FAILS else 0)
