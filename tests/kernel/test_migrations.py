"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
迁移框架验收：在**合成旧库**上验证 dry-run / apply / verify / rollback / 幂等 / 版本护栏。

不碰用户的 Workspace（全程在 .scratch/verify/ 下自建库）。
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.index import migrate as mig  # noqa: E402

WORK = ROOT / ".scratch" / "verify" / "migrate"
WORK.mkdir(parents=True, exist_ok=True)
DB = WORK / "old.sqlite"
BACKUPS = WORK / "Backups"
for p in (DB,):
    if p.exists():
        p.unlink()

FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  · {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def make_old_db() -> None:
    """构造 v1 结构：documents 无 attachment、document_links 无 role，带少量数据。"""
    c = sqlite3.connect(str(DB))
    c.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE documents (
            id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
            title TEXT NOT NULL, updated TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE document_links (
            doc_id TEXT NOT NULL, token TEXT NOT NULL,
            PRIMARY KEY(doc_id, token),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        """
    )
    c.execute("INSERT INTO documents(id,path,kind,title) VALUES('note-1','Knowledge/Notes/note-1.md','note','知识-方法-A')")
    c.execute("INSERT INTO documents(id,path,kind,title) VALUES('note-2','Knowledge/Notes/note-2.md','note','知识-方法-B')")
    c.executemany("INSERT INTO document_links(doc_id,token) VALUES(?,?)",
                  [("note-1", "note-2"), ("note-2", "note-1"), ("note-1", "知识-方法-B")])
    c.execute("INSERT INTO meta(key,value) VALUES('schema_version','1')")
    c.commit()
    c.close()


def schema_snapshot() -> dict:
    c = sqlite3.connect(str(DB))
    try:
        docs = [r[1] for r in c.execute("PRAGMA table_info(documents)")]
        links = [r[1] for r in c.execute("PRAGMA table_info(document_links)")]
        ver = mig.current_version(c)
        n_docs = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        n_links = c.execute("SELECT COUNT(*) FROM document_links").fetchone()[0]
        return {"docs": docs, "links": links, "version": ver, "n_docs": n_docs, "n_links": n_links}
    finally:
        c.close()


print("== 构造 v1 旧库 ==")
make_old_db()
before = schema_snapshot()
check("旧库起点正确", before["version"] == 1 and "attachment" not in before["docs"] and "role" not in before["links"],
      f"version={before['version']} docs={before['docs']} links={before['links']}")

print("\n== 1. 计划（只读）==")
c = sqlite3.connect(str(DB))
p = mig.plan(c)
expected_ids = [m["id"] for m in p["pending"]]
check("识别出全部待执行迁移", len(p["pending"]) == len(mig.REGISTRY), str(expected_ids))
check("标记需要重建索引", p["needs_reindex"] is True)
check("目标版本 = 迁移清单最大值", p["target_version"] == mig.TARGET_VERSION == max(m.to_version for m in mig.REGISTRY), f"target={p['target_version']}")

print("\n== 2. dry-run 不改动任何东西 ==")
res = mig.apply(c, dry_run=True)
after_dry = schema_snapshot()
check("dry-run 报告将执行的迁移", res["applied"] == [m.id for m in mig.REGISTRY], str(res["applied"]))
check("dry-run 后结构与版本不变", after_dry == before, f"{after_dry}")

print("\n== 3. apply（含备份）+ verify ==")
backup = mig.backup_db(DB, backups_dir=BACKUPS, label="pre-v4")
check("备份文件已生成", bool(backup and backup.is_file()), str(backup))
res = mig.apply(c)
c.commit()
after = schema_snapshot()
check("attachment 列已补", "attachment" in after["docs"], str(after["docs"]))
check("role 列已补", "role" in after["links"], str(after["links"]))
check("版本已升到目标", after["version"] == mig.TARGET_VERSION, str(after["version"]))
check("documents 数据保留", after["n_docs"] == before["n_docs"], f"{after['n_docs']}")
check("document_links 被重建（纯派生数据）", after["n_links"] == 0, f"重建后 {after['n_links']} 行（由索引器回填）")
check("verify 全部通过", all(v["ok"] for v in res["verify"]), str(res["verify"]))

print("\n== 4. 幂等：再跑一次无变化 ==")
res2 = mig.apply(c)
c.commit()
check("第二次无待执行迁移", res2["applied"] == [] and res2["changed"] == [], f"applied={res2['applied']} changed={res2['changed']}")
check("第二次 verify 仍通过", all(v["ok"] for v in res2["verify"]), str(res2["verify"]))
check("结构不变", schema_snapshot() == after)

print("\n== 5. 版本护栏：磁盘版本高于代码 ==")
c.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
c.commit()
try:
    mig.guard_disk_version(c, 3)
    check("磁盘版本高于代码时拒写", False, "未抛错")
except mig.MigrationError as exc:
    check("磁盘版本高于代码时拒写", True, str(exc)[:60] + "…")
c.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(mig.TARGET_VERSION),))
c.commit()

print("\n== 6. rollback 回退到 v1 ==")
rb = mig.rollback(c, to_version=1)
c.commit()
rolled = schema_snapshot()
check("已回退到起点", rb["rolled_back"] == [m.id for m in reversed(mig.REGISTRY)], str(rb["rolled_back"]))
check("role 列已移除", "role" not in rolled["links"], str(rolled["links"]))
check("attachment 列已移除", "attachment" not in rolled["docs"], str(rolled["docs"]))
check("版本回到 1", rolled["version"] == 1, str(rolled["version"]))

print("\n== 7. rollback dry-run ==")
res_apply_again = mig.apply(c)
c.commit()
rb2 = mig.rollback(c, to_version=1, dry_run=True)
check("dry-run 只报计划", rb2.get("would_rollback") == [m.id for m in reversed(mig.REGISTRY)], str(rb2))
check("dry-run 未改动", mig.current_version(c) == mig.TARGET_VERSION)
c.close()

print("\n== 8. 真实库只读 dry-run（不落盘）==")
real = ROOT / "Workspace" / "System" / "Cache" / "index.sqlite"
if real.is_file():
    try:
        rc = sqlite3.connect(f"file:{real.as_posix()}?mode=ro", uri=True)
        rp = mig.plan(rc)
        # 工作台正在运行时，库可能被占用而读不到 meta；此时如实报 SKIP，不误判成回归。
        if rp["current_version"] == 0 and mig.current_version(rc) == 0:
            print("SKIP 真实库当前不可读（工作台可能正在运行并占用该库）")
        else:
            check("真实库已是最新，无待执行迁移", rp["up_to_date"] is True,
                  f"current={rp['current_version']} target={rp['target_version']} pending={rp['pending']}")
        rc.close()
    except sqlite3.Error as exc:
        print(f"SKIP 真实库当前不可读：{exc}")
else:
    print("SKIP 真实库不存在（干净检出）：第 8 组需要用户 Workspace 才能只读 dry-run")

print("\n== 9. 服务侧 _init_db 集成（全新库 / 版本护栏）==")
import app.perf_index_db as pdb  # noqa: E402

FRESH = WORK / "fresh.sqlite"
if FRESH.exists():
    FRESH.unlink()
_orig_db_path = pdb._db_path
pdb._db_path = lambda root=None: FRESH
try:
    conn = pdb._connect()
    upgraded = pdb._init_db(conn)
    conn.commit()
    fresh_docs = [r[1] for r in conn.execute("PRAGMA table_info(documents)")]
    fresh_links = [r[1] for r in conn.execute("PRAGMA table_info(document_links)")]
    check("全新库建表即当前结构", "attachment" in fresh_docs and "role" in fresh_links,
          f"docs={len(fresh_docs)} links={fresh_links}")
    check("全新库标记为需要全量建索引", upgraded is True)
    check("全新库版本 = 目标", mig.current_version(conn) == mig.TARGET_VERSION)
    check("迁移在全新库上是 no-op（幂等）",
          mig.apply(conn, dry_run=True)["applied"] == [], "pending 应为空")

    # 版本护栏：把版本改成高于代码，_init_db 必须拒绝而不是照改
    pdb._SCHEMA_READY.pop(str(FRESH), None)   # 清掉已初始化缓存，才会重新走版本检查
    conn.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    conn.commit()
    try:
        pdb._init_db(conn)
        check("_init_db 拒绝高于代码的库版本", False, "未抛错")
    except mig.MigrationError:
        check("_init_db 拒绝高于代码的库版本", True, "抛出 MigrationError")
    conn.close()
finally:
    pdb._db_path = _orig_db_path

print()
if FAILS:
    print(f"结果：{len(FAILS)} 项失败 → {FAILS}")
    raise SystemExit(1)
print("结果：全部通过")
