"""（常驻测试 · 原 .scratch/tmp 夹具，v261009.36 迁入 tests/）
验证 doctor 能报出「磁盘版本高于代码」这一硬错误（用合成工作区，不碰真实数据）。"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core import doctor  # noqa: E402

WS = ROOT / ".scratch" / "verify" / "ws_guard"
CACHE = WS / "System" / "Cache"
CACHE.mkdir(parents=True, exist_ok=True)
DB = CACHE / "index.sqlite"
if DB.exists():
    DB.unlink()

c = sqlite3.connect(str(DB))
c.executescript(
    """
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE documents (id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL);
    """
)
c.execute("INSERT INTO meta(key,value) VALUES('schema_version','99')")
c.commit()
c.close()

rep = doctor.run(WS, ROOT)
item = next((i for i in rep.items if i["check"] == "索引·结构迁移状态"), None)
ok = item is not None and item["level"] == "error" and item["count"] == 1
print("PASS" if ok else "FAIL", "doctor 报出高于代码的库版本：", item)
print("error 级检查项数：", rep.errors())
raise SystemExit(0 if ok and rep.errors() >= 1 else 1)
