"""Local-first synchronization of saved records and content-addressed attachments.

Markdown remains authoritative. SQLite stores observed versions, peer baselines
and conflicts, not a second editable copy of the knowledge base.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from . import activity

PROTOCOL = 2  # Both peers must understand append-only research activity events.
MAX_BLOB = 512 * 1024 * 1024
CHUNK = 2 * 1024 * 1024
SCOPES = ("documents", "attachments", "records", "settings", "history")
DEFAULTS = {"url": "", "mode": "off", "interval": 30,
            "scopes": ["documents", "attachments", "records", "settings"]}
APP_FIELDS = ("ui", "academic_profile", "knowledge_types", "classification_marks", "weather",
              "app_name", "subtitle")
PREFERENCES = {"theme", "pageDensity", "uiScale", "focusMinutes", "breakMinutes",
               "sidebarPinned", "sidebarOpen", "heatmapMonths", "heatmapThresholds", "heatmapColors"}
# Shared by the HTTP write routes and local sync application. Network waits never hold it.
mutation_lock = threading.RLock()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return deepcopy(fallback)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(canonical(value), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def normalized_url(raw):
    raw = str(raw or "").strip().rstrip("/")
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("请输入 HTTP / HTTPS 服务地址，不包含账号、查询参数或片段")
    try:
        parts.port
    except ValueError:
        raise ValueError("服务器端口无效") from None
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


class SyncEngine:
    def __init__(self, root: Path, data_root: Path, after_apply=None):
        self.root, self.data_root = root.resolve(), data_root.resolve()
        self.directory = self.root / "System" / "Sync"
        self.blobs = self.directory / "blobs"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / "state.sqlite"
        self.config_path = self.data_root / "config" / "sync.json"
        self.preferences_path = self.data_root / "config" / "ui-preferences.json"
        self.after_apply = after_apply or (lambda: None)
        self._lock = threading.RLock()
        self._cycle_lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._cache = {}
        self._guards = {}
        self._blob_locks = {}
        self._status = {"phase": "idle", "error": "", "last_success": None, "last_check": None,
                        "peer": None, "remote_known": False, "applied": 0, "transferred": 0}
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS resources(key TEXT PRIMARY KEY,scope TEXT NOT NULL,
                  hash TEXT,version INTEGER NOT NULL,descriptor TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bases(peer TEXT,key TEXT,hash TEXT,descriptor TEXT,
                  remote_version INTEGER NOT NULL,PRIMARY KEY(peer,key));
                CREATE TABLE IF NOT EXISTS conflicts(peer TEXT,key TEXT,local_hash TEXT,
                  remote TEXT NOT NULL,PRIMARY KEY(peer,key));
            """)
            db.execute("INSERT OR IGNORE INTO meta VALUES('instance',?)", (uuid.uuid4().hex,))
            self.instance = db.execute("SELECT value FROM meta WHERE key='instance'").fetchone()[0]
            row = db.execute("SELECT value FROM meta WHERE key='status'").fetchone()
            if row:
                self._status.update(json.loads(row[0]))
            self._status.update(phase="idle", error="", remote_known=False)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def config(self):
        value = read_json(self.config_path, DEFAULTS)
        return {**DEFAULTS, **value}

    def configure(self, value):
        mode = value.get("mode", "off")
        if mode not in ("off", "manual", "auto"):
            raise ValueError("同步模式无效")
        url = normalized_url(value.get("url"))
        if mode != "off" and not url:
            raise ValueError("请先填写服务器地址")
        scopes = value.get("scopes", DEFAULTS["scopes"])
        if not isinstance(scopes, list) or any(s not in SCOPES for s in scopes):
            raise ValueError("同步范围无效")
        if mode != "off" and not scopes:
            raise ValueError("请至少选择一种同步内容")
        interval = max(10, min(3600, int(value.get("interval", 30))))
        with self._lock:
            if self._status["phase"] == "syncing":
                raise ValueError("正在同步，请完成后再修改连接设置")
            previous = self.config()
            atomic_json(self.config_path, {"url": url, "mode": mode, "interval": interval, "scopes": scopes})
            if previous["url"] != url or previous["scopes"] != scopes:
                self._status.update(peer=None, remote_known=False, last_check=None, error="")
            self._status["phase"] = "idle"
            self._persist_status()
        self._wake.set()
        return self.status()

    def _persist_status(self):
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES('status',?)", (canonical(self._status),))

    def _path(self, raw):
        if not isinstance(raw, str) or "\\" in raw or "\x00" in raw:
            raise ValueError("同步文件路径无效")
        parts = PurePosixPath(raw).parts
        if not parts or PurePosixPath(raw).as_posix() != raw or parts[0] not in ("Knowledge", "Projects", "Resources", "System") or any(p in ("..", ".") or p.endswith((".", " ")) or re.search(r'[<>:"|?*\x00-\x1f]', p) or PureWindowsPath(p).is_reserved() for p in parts):
            raise ValueError("同步路径超出资料范围")
        if parts[0] == "System" and (len(parts) < 2 or parts[1] not in ("AgentChats",)):
            raise ValueError("此系统目录不能同步")
        if any(p.startswith(".") for p in parts) or any(p in ("Trash", "Cache", "Previews", "Index") for p in parts):
            raise ValueError("缓存、回收站与索引不能同步为文件")
        path = (self.root / raw).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("同步路径超出 Workspace")
        return path

    def _blob_path(self, sha):
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("文件校验值无效")
        return self.blobs / sha

    def _blob_lock(self, sha):
        self._blob_path(sha)
        with self._lock:
            return self._blob_locks.setdefault(sha, threading.Lock())

    def _commit_blob(self, source, sha, size):
        """Publish verified content once; never replace a blob held by a reader.

        Windows rename fails if the destination exists. POSIX hard-link creation
        gives the same no-replacement guarantee when different publishers race.
        """
        target = self._blob_path(sha)
        for attempt in range(5):
            if target.is_file():
                if target.stat().st_size != size:
                    raise ValueError(f"同步缓存大小校验失败，已停止同步：{sha}")
                return
            try:
                if os.name == "nt":
                    os.rename(source, target)
                else:
                    os.link(source, target)
                return
            except OSError as exc:
                if target.is_file():
                    continue  # Another publisher finished after our existence check.
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 4:
                    raise
                time.sleep(.05 * (2 ** attempt))
        if target.is_file() and target.stat().st_size == size:
            return
        raise ValueError("同步缓存写入未完成，请稍后重试")

    def _store_blob(self, path):
        stat = path.stat()
        if stat.st_size > MAX_BLOB:
            raise ValueError(f"附件超过 512 MB：{path.name}")
        signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        cached = self._cache.get(str(path))
        if cached and cached[0] == signature and self._blob_path(cached[1]).is_file():
            return cached[1], stat.st_size
        temp = self.blobs / (uuid.uuid4().hex + ".tmp")
        sha = hashlib.sha256()
        try:
            with path.open("rb") as source, temp.open("wb") as target:
                while chunk := source.read(CHUNK):
                    sha.update(chunk)
                    target.write(chunk)
            after = path.stat()
            if signature != (after.st_mtime_ns, after.st_size, after.st_ino):
                raise ValueError(f"文件仍在写入，稍后重试：{path.name}")
            key = sha.hexdigest()
            self._commit_blob(temp, key, stat.st_size)
            self._cache[str(path)] = (signature, key)
            return key, stat.st_size
        finally:
            temp.unlink(missing_ok=True)

    def blob_info(self, sha):
        path = self._blob_path(sha)
        part = path.with_suffix(".part")
        return {"ready": path.is_file(), "offset": path.stat().st_size if path.is_file() else part.stat().st_size if part.is_file() else 0}

    def receive_blob(self, sha, chunk, offset, total):
        path = self._blob_path(sha)
        if not 0 <= offset <= total <= MAX_BLOB or len(chunk) > CHUNK or offset + len(chunk) > total:
            raise ValueError("附件分块大小无效")
        with self._blob_lock(sha):
            if path.exists():
                return self.blob_info(sha)
            part = path.with_suffix(".part")
            current = part.stat().st_size if part.exists() else 0
            if offset != current:
                return {"ready": False, "offset": current}
            with part.open("ab") as stream:
                stream.write(chunk)
            if part.stat().st_size == total:
                with part.open("rb") as stream:
                    hasher = hashlib.sha256()
                    while block := stream.read(CHUNK):
                        hasher.update(block)
                    actual = hasher.hexdigest()
                if actual != sha:
                    part.unlink()
                    raise ValueError("附件校验失败，请重新上传")
                self._commit_blob(part, sha, total)
                part.unlink(missing_ok=True)
            return self.blob_info(sha)

    def _row(self, row):
        return {"key": row["key"], "scope": row["scope"], "hash": row["hash"],
                "version": row["version"], "descriptor": json.loads(row["descriptor"])}

    def _record(self, db, key, descriptor, sha):
        old = db.execute("SELECT * FROM resources WHERE key=?", (key,)).fetchone()
        if old and old["hash"] == sha:
            return self._row(old)
        version = int(db.execute("SELECT COALESCE(MAX(version),0)+1 FROM resources").fetchone()[0])
        db.execute("INSERT OR REPLACE INTO resources VALUES(?,?,?,?,?)", (key, descriptor["scope"], sha, version, canonical(descriptor)))
        return {"key": key, "scope": descriptor["scope"], "hash": sha, "version": version, "descriptor": descriptor}

    def _collection_specs(self):
        specs = [("todos", "System/todos.json", None), ("projects", "System/projects.json", None),
                 ("papers", "Knowledge/Literature/Index/library.json", "items")]
        directory = self.root / "Knowledge/Literature/Annotations"
        if directory.exists():
            specs.extend(("annotations:" + p.stem, p.relative_to(self.root).as_posix(), None) for p in directory.glob("*.json"))
        return specs

    def _inventory(self):
        result = {}
        def add(key, desc):
            if key in result:
                raise ValueError(f"发现重复条目 ID，先修正再同步：{key}")
            result[key] = desc
        collection_paths = {path for _, path, _ in self._collection_specs()}
        for top in ("Knowledge", "Projects", "Resources", "System/AgentChats"):
            directory = self.root / top
            if not directory.exists():
                continue
            for path in directory.rglob("*"):
                if not path.is_file() or path.is_symlink() or path.suffix in (".tmp", ".part", ".lock"):
                    continue
                rel = path.relative_to(self.root).as_posix()
                if rel in collection_paths:
                    continue
                try:
                    self._path(rel)
                except ValueError:
                    continue
                blob, size = self._store_blob(path)
                scope = "history" if top.startswith("System/") else "documents" if path.suffix.lower() == ".md" else "attachments"
                key = "file:" + rel
                doc_id = ""
                if scope == "documents":
                    from .store import _frontmatter_parse
                    meta, _body = _frontmatter_parse(self._blob_path(blob).read_text(encoding="utf-8-sig"))
                    doc_id = str(meta.get("id") or "")
                    if doc_id:
                        key = "doc:" + doc_id
                add(key, {"type": "file", "scope": scope, "path": rel, "blob": blob, "size": size, "doc_id": doc_id})
        for collection, rel, member in self._collection_specs():
            data = read_json(self.root / rel, {"items": []} if member else [])
            rows = data.get(member, []) if member else data
            if not isinstance(rows, list):
                raise ValueError(f"记录文件格式无效：{rel}")
            for value in rows:
                if not isinstance(value, dict) or not value.get("id"):
                    continue
                rid = str(value["id"])
                add("record:" + collection + ":" + rid, {"type": "record", "scope": "records", "collection": collection, "id": rid, "value": value})
        for event in activity.list_events(root=self.root):
            add("activity:" + event["id"], {"type": "activity", "scope": "records", "value": event})
        app = read_json(self.data_root / "config/app.json", {})
        def leaves(prefix, value):
            if isinstance(value, dict) and value:
                for k, v in value.items():
                    yield from leaves(prefix + [k], v)
            else:
                yield prefix, value
        for field in APP_FIELDS:
            if field in app:
                for keys, value in leaves([field], app[field]):
                    add("setting:app:" + canonical(keys), {"type": "setting", "scope": "settings", "source": "app", "keys": keys, "value": value})
        rss = self.data_root / "config/rss.json"
        if rss.exists():
            add("setting:rss", {"type": "setting", "scope": "settings", "source": "rss", "keys": [], "value": read_json(rss, {})})
        for key, value in read_json(self.preferences_path, {}).items():
            if key in PREFERENCES:
                add("preference:" + key, {"type": "preference", "scope": "settings", "name": key, "value": value})
        return result

    def refresh(self):
        with mutation_lock, self._lock, self._db() as db:
            current = self._inventory()
            for key, desc in current.items():
                self._record(db, key, desc, digest(desc))
            for row in db.execute("SELECT * FROM resources WHERE hash IS NOT NULL").fetchall():
                if row["key"] not in current:
                    if json.loads(row["descriptor"]).get("type") == "activity":
                        # Activity history is a union, never a propagated deletion.
                        continue
                    self._record(db, row["key"], json.loads(row["descriptor"]), None)
            return {r["key"]: self._row(r) for r in db.execute("SELECT * FROM resources")}

    def manifest(self, scopes=None):
        scopes = self._scopes(scopes)
        rows = self.refresh()
        return {"protocol": PROTOCOL, "instance": self.instance,
                "resources": [v for v in rows.values() if v["scope"] in scopes]}

    @staticmethod
    def _scopes(scopes):
        if scopes is None:
            return list(SCOPES)
        if not isinstance(scopes, list) or any(s not in SCOPES for s in scopes):
            raise ValueError("同步范围无效")
        return scopes

    def save_preferences(self, values):
        if not isinstance(values, dict):
            raise ValueError("界面偏好格式无效")
        with mutation_lock:
            data = read_json(self.preferences_path, {})
            for key, value in values.items():
                if key not in PREFERENCES or len(canonical(value)) > 16000:
                    raise ValueError("不支持的界面偏好")
                data[key] = value
            atomic_json(self.preferences_path, data)
        self._wake.set()
        return data

    def guard_editor(self, client, doc_id, dirty):
        with self._lock:
            self._guards[str(client)[:100]] = ("doc:" + str(doc_id), bool(dirty), time.monotonic())
        return {"ok": True}

    def _guarded(self, key):
        return any(k == key and dirty and time.monotonic() - stamp < 180 for k, dirty, stamp in self._guards.values())

    def _collection_target(self, collection):
        if collection == "todos":
            return self.root / "System/todos.json", None
        if collection == "projects":
            return self.root / "System/projects.json", None
        if collection == "papers":
            return self.root / "Knowledge/Literature/Index/library.json", "items"
        if collection.startswith("annotations:") and re.fullmatch(r"[\w.-]{1,180}", collection[12:]) and ".." not in collection[12:]:
            return self.root / "Knowledge/Literature/Annotations" / (collection[12:] + ".json"), None
        raise ValueError("记录类型无效")

    def _validate(self, key, desc):
        if not isinstance(desc, dict) or len(canonical(desc)) > 2 * 1024 * 1024:
            raise ValueError("同步记录过大或格式无效")
        kind = desc.get("type")
        if kind == "file":
            self._path(desc.get("path"))
            blob = self._blob_path(desc.get("blob"))
            if not blob.is_file() or blob.stat().st_size != desc.get("size"):
                raise ValueError("附件尚未传输完整")
            scope = "history" if desc["path"].startswith("System/AgentChats/") else "documents" if desc["path"].lower().endswith(".md") else "attachments"
            if desc.get("scope") != scope:
                raise ValueError("文件同步范围不匹配")
            doc_id = desc.get("doc_id", "")
            if doc_id:
                from .store import _frontmatter_parse
                actual, _ = _frontmatter_parse(blob.read_text(encoding="utf-8-sig"))
                if scope != "documents" or actual.get("id") != doc_id or key != "doc:" + doc_id:
                    raise ValueError("文档 ID 不匹配")
            elif key != "file:" + desc["path"]:
                raise ValueError("文件 ID 不匹配")
        elif kind == "activity":
            activity.validate_event(desc.get("value"))
            if key != "activity:" + desc["value"]["id"] or desc.get("scope") != "records":
                raise ValueError("科研活动 ID 或同步范围不匹配")
        elif kind == "record":
            self._collection_target(desc.get("collection", ""))
            if not isinstance(desc.get("value"), dict) or desc["value"].get("id") != desc.get("id") or key != "record:" + desc["collection"] + ":" + str(desc["id"]) or desc.get("scope") != "records":
                raise ValueError("记录 ID 不匹配")
        elif kind == "setting":
            keys = desc.get("keys")
            if not isinstance(keys, list) or any(not isinstance(k, str) or not k or len(k) > 100 for k in keys) or desc.get("scope") != "settings":
                raise ValueError("设置路径无效")
            if desc.get("source") == "app":
                if not keys or keys[0] not in APP_FIELDS or key != "setting:app:" + canonical(keys):
                    raise ValueError("此配置项只能保存在本机")
            elif desc.get("source") != "rss" or keys or key != "setting:rss":
                raise ValueError("设置来源无效")
        elif kind == "preference":
            if desc.get("name") not in PREFERENCES or key != "preference:" + desc["name"] or desc.get("scope") != "settings":
                raise ValueError("界面偏好无效")
        else:
            raise ValueError("同步条目类型无效")

    def _archive(self, path):
        if not path.exists():
            return
        target = self.root / "System/Trash/Sync" / uuid.uuid4().hex / path.relative_to(self.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))

    def _apply_content(self, key, desc, deleted, previous):
        if desc["type"] == "activity":
            if deleted:
                raise ValueError("科研活动历史不支持同步删除")
            activity.merge_events([desc["value"]], root=self.root)
        elif desc["type"] == "file":
            path = self._path(desc["path"])
            if deleted:
                self._archive(path)
                return
            if previous and previous["descriptor"].get("path") != desc["path"]:
                self._archive(self._path(previous["descriptor"]["path"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                shutil.copyfile(self._blob_path(desc["blob"]), temp)
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
        elif desc["type"] == "record":
            path, member = self._collection_target(desc["collection"])
            data = read_json(path, {"version": 1, "items": []} if member else [])
            rows = data.get(member, []) if member else data
            rows = [r for r in rows if r.get("id") != desc["id"]]
            if not deleted:
                rows.append(desc["value"])
            if member:
                data[member] = rows
            else:
                data = rows
            atomic_json(path, data)
        elif desc["type"] in ("setting", "preference"):
            if desc["type"] == "preference":
                path, keys = self.preferences_path, [desc["name"]]
            else:
                path, keys = self.data_root / "config" / (desc["source"] + ".json"), desc["keys"]
            data = read_json(path, {})
            if not keys:
                data = {} if deleted else desc["value"]
            else:
                target = data
                for part in keys[:-1]:
                    if not isinstance(target.get(part), dict):
                        target[part] = {}
                    target = target[part]
                if deleted:
                    target.pop(keys[-1], None)
                else:
                    target[keys[-1]] = desc["value"]
            atomic_json(path, data)

    def apply_many(self, changes):
        if not isinstance(changes, list) or len(changes) > 100:
            raise ValueError("单次最多同步 100 项变化")
        accepted, conflicts, failures = [], [], []
        with mutation_lock, self._lock:
            current = self.refresh()
            for change in changes:
                try:
                    key, desc, expected = change["key"], change["descriptor"], change["expected_version"]
                    previous = current.get(key)
                    if (previous["version"] if previous else 0) != expected or self._guarded(key):
                        conflicts.append({**(previous or {"key": key, "version": 0, "hash": None, "descriptor": desc, "scope": desc["scope"]}), "guarded": self._guarded(key)})
                        continue
                    deleted = change.get("deleted") is True
                    if deleted:
                        if not previous:
                            raise ValueError("不能删除不存在的条目")
                        desc = previous["descriptor"]
                    else:
                        self._validate(key, desc)
                    sha = None if deleted else digest(desc)
                    # Reject an unrelated resource already occupying the destination path.
                    if not deleted and desc["type"] == "file":
                        if any(k != key and r["hash"] and r["descriptor"].get("type") == "file" and r["descriptor"].get("path") == desc["path"] for k, r in current.items()):
                            raise ValueError("目标文件已被其他条目占用")
                    self._apply_content(key, desc, deleted, previous)
                    with self._db() as db:
                        row = self._record(db, key, desc, sha)
                    current[key] = row
                    accepted.append(row)
                except (ValueError, KeyError, OSError, TypeError) as exc:
                    failures.append({"key": change.get("key", ""), "message": str(exc)})
            if accepted:
                self._status["applied"] += 1
                self.after_apply()
        self._wake.set()
        return {"accepted": accepted, "conflicts": conflicts, "failed": failures}

    def _bases(self, peer):
        with self._db() as db:
            return {r["key"]: {"hash": r["hash"], "descriptor": json.loads(r["descriptor"]),
                    "version": r["remote_version"]} for r in db.execute("SELECT * FROM bases WHERE peer=?", (peer,))}

    def _base(self, peer, row):
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO bases VALUES(?,?,?,?,?)", (peer, row["key"], row["hash"], canonical(row["descriptor"]), row["version"]))
            db.execute("DELETE FROM conflicts WHERE peer=? AND key=?", (peer, row["key"]))

    def _conflict(self, peer, local, remote):
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO conflicts VALUES(?,?,?,?)", (peer, remote["key"], local.get("hash"), canonical(remote)))

    def _remote_rows(self):
        with self._db() as db:
            row = db.execute("SELECT value FROM meta WHERE key='remote'").fetchone()
        return json.loads(row[0]) if row else {}

    @staticmethod
    def _label(row):
        d = row.get("descriptor", {})
        if d.get("type") == "activity":
            value = d.get("value", {})
            return "科研活动 · " + str(value.get("timestamp", ""))[:10] + " · " + str(value.get("title") or value.get("type", ""))
        if d.get("type") == "file":
            return d.get("path", row["key"])
        if d.get("type") == "record":
            v = d.get("value", {})
            return str(v.get("title") or v.get("name") or d.get("id"))
        return "设置 · " + (" / ".join(d.get("keys", [])) or d.get("name") or d.get("source", ""))

    def status(self, scan=False):
        if scan:
            self.refresh()
        cfg = self.config()
        with self._lock, self._db() as db:
            local = {r["key"]: self._row(r) for r in db.execute("SELECT * FROM resources")}
            peer = self._status.get("peer") or ""
            conflicts = {r["key"]: json.loads(r["remote"]) for r in db.execute("SELECT * FROM conflicts WHERE peer=?", (peer,))}
            bases = self._bases(peer)
            remote = self._remote_rows() if self._status["remote_known"] else {}
            changes, upload, download = [], 0, 0
            for key in sorted(set(local) | set(remote) | set(conflicts)):
                l, r, b = local.get(key), remote.get(key), bases.get(key)
                row = l or r or conflicts.get(key)
                if row["scope"] not in cfg["scopes"]:
                    continue
                lh, rh, bh = (l or {}).get("hash"), (r or {}).get("hash"), (b or {}).get("hash")
                lc = lh != bh
                rc = key in remote and rh != bh
                if (key in conflicts and conflicts[key]["hash"] != lh) or (lc and rc and lh != rh):
                    code = "!"
                elif lc and not (key in remote and lh == rh):
                    code = "D" if lh is None else "M" if bh else "A"
                    upload += 1
                elif rc and lh != rh:
                    code = "↓"
                    download += 1
                else:
                    continue
                changes.append({"key": key, "code": code, "label": self._label(row), "scope": row["scope"],
                                "doc_id": row["descriptor"].get("doc_id", ""), "guarded": self._guarded(key)})
            result = {**self._status, "config": cfg, "upload": upload, "download": download,
                      "conflicts": sum(c["code"] == "!" for c in changes), "changes": changes,
                      "preferences": read_json(self.preferences_path, {}), "instance": self.instance}
            return result

    @staticmethod
    def _request(url, route, payload=None, method=None):
        body = None if payload is None else canonical(payload).encode("utf-8")
        request = Request(url + route, data=body, method=method or ("POST" if body is not None else "GET"),
                          headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=25) as response:
                raw = response.read(32 * 1024 * 1024 + 1)
                if len(raw) > 32 * 1024 * 1024:
                    raise ValueError("服务器清单超过 32 MB")
                return json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            try:
                message = json.loads(exc.read(4096)).get("message", "")
            except Exception:
                message = ""
            raise ValueError(message or f"服务器返回 HTTP {exc.code}，请确认两端版本与地址") from None

    def _fetch_manifest(self, url, scopes):
        data = self._request(url, "/api/sync/manifest?" + urlencode({"scopes": ",".join(scopes)}))
        if data.get("protocol") != PROTOCOL or not isinstance(data.get("resources"), list) or not isinstance(data.get("instance"), str):
            raise ValueError("同步版本不兼容，请将客户端和服务器端都更新到支持科研活动同步的版本")
        if data["instance"] == self.instance:
            raise ValueError("此地址指向当前工作台，请填写另一台服务器的地址")
        rows = {}
        for row in data["resources"]:
            if not isinstance(row, dict) or not isinstance(row.get("key"), str) or row.get("scope") not in scopes or not isinstance(row.get("version"), int):
                raise ValueError("服务器同步清单无效")
            if row["key"] in rows or (row.get("hash") is not None and row["hash"] != digest(row.get("descriptor"))):
                raise ValueError("服务器清单存在重复条目或校验失败")
            rows[row["key"]] = row
        return data["instance"], rows

    def test_connection(self, url):
        url = normalized_url(url)
        if not url:
            raise ValueError("请填写服务器地址")
        peer, rows = self._fetch_manifest(url, self.config()["scopes"])
        return {"ok": True, "instance": peer, "count": len(rows), "url": url}

    def _upload_blob(self, url, desc):
        sha, size = desc["blob"], desc["size"]
        info = self._request(url, "/api/sync/blob-info?" + urlencode({"hash": sha}))
        if info.get("ready"):
            return
        offset = int(info.get("offset", 0))
        if offset < 0 or offset > size:
            raise ValueError("服务器附件断点无效")
        with self._blob_path(sha).open("rb") as source:
            while not info.get("ready"):
                if self._stop.is_set():
                    raise ValueError("同步已停止")
                source.seek(offset)
                chunk = source.read(CHUNK)
                request = Request(url + "/api/sync/blob?" + urlencode({"hash": sha, "offset": offset, "total": size}),
                                  data=chunk, method="PUT", headers={"Content-Type": "application/octet-stream"})
                with urlopen(request, timeout=40) as response:
                    info = json.loads(response.read(4096))
                new_offset = int(info["offset"])
                if not info.get("ready") and new_offset <= offset:
                    raise ValueError("服务器附件传输没有进展")
                offset = new_offset
                self._status["transferred"] += len(chunk)
                if info.get("ready"):
                    break

    def _download_blob(self, url, desc):
        # The shared .part file must have only one writer, including HTTP uploads
        # arriving at this instance. Do not hold the main lock during networking.
        with self._blob_lock(desc["blob"]):
            self._download_blob_locked(url, desc)

    def _download_blob_locked(self, url, desc):
        sha, size = desc["blob"], desc["size"]
        if not isinstance(size, int) or not 0 <= size <= MAX_BLOB:
            raise ValueError("服务器附件大小无效")
        target = self._blob_path(sha)
        if target.is_file():
            return
        part = target.with_suffix(".part")
        offset = part.stat().st_size if part.exists() else 0
        if offset > size:
            part.unlink()
            offset = 0
        request = Request(url + "/api/sync/blob?" + urlencode({"hash": sha, "offset": offset}))
        with urlopen(request, timeout=40) as response, part.open("ab") as output:
            while chunk := response.read(CHUNK):
                if self._stop.is_set():
                    raise ValueError("同步已停止")
                if output.tell() + len(chunk) > size:
                    raise ValueError("服务器附件超出声明大小")
                output.write(chunk)
                self._status["transferred"] += len(chunk)
        actual = hashlib.sha256()
        with part.open("rb") as source:
            while chunk := source.read(CHUNK):
                actual.update(chunk)
        if part.stat().st_size != size:
            raise ValueError("附件传输中断，下次同步将从断点继续")
        if actual.hexdigest() != sha:
            part.unlink(missing_ok=True)
            raise ValueError("附件校验失败，未应用到资料库")
        self._commit_blob(part, sha, size)
        part.unlink(missing_ok=True)

    def _transfer(self, url, row, upload=False):
        if row["hash"] is not None and row["descriptor"]["type"] == "file":
            (self._upload_blob if upload else self._download_blob)(url, row["descriptor"])

    @staticmethod
    def _change(row, version):
        return {"key": row["key"], "descriptor": row["descriptor"], "deleted": row["hash"] is None, "expected_version": version}

    def _remember_remote(self, peer, remote):
        with self._lock, self._db() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES('remote',?)", (canonical(remote),))
            self._status.update(peer=peer, remote_known=True, last_check=time.time())

    def synchronize(self, check_only=False, _acquired=False):
        if not _acquired and not self._cycle_lock.acquire(blocking=False):
            return self.status()
        try:
            cfg = self.config()
            if cfg["mode"] == "off":
                return self.status()
            with self._lock:
                self._status.update(phase="syncing", error="", transferred=0, deferred=0)
            local = self.refresh()
            peer, remote = self._fetch_manifest(cfg["url"], cfg["scopes"])
            self._remember_remote(peer, remote)
            bases = self._bases(peer)
            pushes, pulls = [], []
            for key in sorted(set(local) | set(remote)):
                l, r, b = local.get(key), remote.get(key), bases.get(key)
                row = l or r
                if row["scope"] not in cfg["scopes"]:
                    continue
                lh, rh, bh = (l or {}).get("hash"), (r or {}).get("hash"), (b or {}).get("hash")
                if lh == rh:
                    if r:
                        self._base(peer, r)
                elif lh != bh and rh != bh:
                    self._conflict(peer, l or {}, r or {**row, "hash": None, "version": 0})
                elif lh != bh and l:
                    pushes.append((l, r))
                elif rh != bh and r:
                    pulls.append((r, l))
            if not check_only:
                # Blob transfer occurs outside the write lock. CAS is checked again at application time.
                for offset in range(0, len(pushes), 100):
                    batch = pushes[offset:offset + 100]
                    for l, _ in batch:
                        self._transfer(cfg["url"], l, upload=True)
                    result = self._request(cfg["url"], "/api/sync/apply", {"changes": [self._change(l, (r or {}).get("version", 0)) for l, r in batch]})
                    for row in result["accepted"]:
                        remote[row["key"]] = row
                        self._base(peer, row)
                    for row in result["conflicts"]:
                        remote[row["key"]] = row
                        if row.get("guarded"):
                            self._status["deferred"] += 1
                        else:
                            self._conflict(peer, local.get(row["key"], {}), row)
                    if result["failed"]:
                        raise ValueError(result["failed"][0]["message"])
                for offset in range(0, len(pulls), 100):
                    batch = pulls[offset:offset + 100]
                    for r, _ in batch:
                        self._transfer(cfg["url"], r)
                    result = self.apply_many([self._change(r, (l or {}).get("version", 0)) for r, l in batch])
                    for row in result["accepted"]:
                        self._base(peer, remote[row["key"]])
                    for row in result["conflicts"]:
                        if not self._guarded(row["key"]):
                            self._conflict(peer, row, remote[row["key"]])
                    if result["failed"]:
                        raise ValueError(result["failed"][0]["message"])
            self._remember_remote(peer, remote)
            self.refresh()
            status = self.status()
            with self._lock:
                self._status["phase"] = "conflict" if status["conflicts"] else "pending" if status["upload"] or status["download"] else "synced"
                if self._status["phase"] == "synced" and not check_only:
                    self._status["last_success"] = time.time()
        except Exception as exc:
            with self._lock:
                self._status.update(phase="error", error=str(exc)[:500])
        finally:
            self._persist_status()
            self._cycle_lock.release()
        return self.status()

    def launch(self, check_only=False):
        if self.config()["mode"] == "off":
            return self.status()
        if self._cycle_lock.acquire(blocking=False):
            with self._lock:
                self._status.update(phase="syncing", error="")
            threading.Thread(target=self.synchronize, kwargs={"check_only": check_only, "_acquired": True}, daemon=True, name="workbench-sync-once").start()
        return self.status()

    def conflict_detail(self, key):
        peer = self._status.get("peer")
        with self._db() as db:
            row = db.execute("SELECT * FROM conflicts WHERE peer=? AND key=?", (peer, key)).fetchone()
        if not row:
            raise ValueError("此冲突已处理，请刷新状态")
        local, remote = self.refresh().get(key), json.loads(row["remote"])
        base = self._bases(peer).get(key)
        self._transfer(self.config()["url"], remote)
        def version(r):
            if not r or r.get("hash") is None:
                return {"deleted": True, "text": "（已删除）"}
            d = r["descriptor"]
            if d["type"] == "file":
                path = self._blob_path(d["blob"])
                if d["size"] <= 2 * 1024 * 1024 and path.exists():
                    try:
                        return {"deleted": False, "text": path.read_text(encoding="utf-8-sig"), "editable": d["scope"] == "documents"}
                    except UnicodeError:
                        pass
                return {"deleted": False, "text": f"附件 · {d['path']} · {d['size']} 字节"}
            return {"deleted": False, "text": json.dumps(d.get("value"), ensure_ascii=False, indent=2)}
        return {"key": key, "label": self._label(local or remote), "local_hash": (local or {}).get("hash"),
                "remote_version": remote["version"], "local": version(local), "remote": version(remote), "base": version(base),
                "can_keep_both": bool(local and local["hash"] and local["descriptor"]["type"] == "file")}

    def resolve(self, payload):
        if not self._cycle_lock.acquire(blocking=False):
            raise ValueError("正在同步，请稍后处理冲突")
        try:
            cfg, key = self.config(), payload.get("key")
            if cfg["mode"] == "off":
                raise ValueError("请先启用同步")
            with self._lock:
                self._status.update(phase="syncing", error="")
            peer, remote_rows = self._fetch_manifest(cfg["url"], cfg["scopes"])
            if peer != self._status.get("peer"):
                raise ValueError("服务器已变化，请重新同步")
            local = self.refresh().get(key)
            remote = remote_rows.get(key)
            if not remote or remote["version"] != payload.get("remote_version") or (local or {}).get("hash") != payload.get("local_hash"):
                if remote:
                    self._conflict(peer, local or {}, remote)
                    self._remember_remote(peer, remote_rows)
                raise ValueError("此条目又有新修改，请重新打开冲突后确认")
            if self._guarded(key):
                raise ValueError("编辑器还有未保存修改，请先保存或放弃修改")
            choice = payload.get("choice")
            if choice in ("remote", "both"):
                self._transfer(cfg["url"], remote)
                with mutation_lock, self._lock:
                    current = self.refresh().get(key)
                    if (current or {}).get("hash") != payload.get("local_hash") or self._guarded(key):
                        raise ValueError("本地内容已变化，请重新确认")
                    if choice == "both":
                        if not local or not local["hash"] or local["descriptor"]["type"] != "file":
                            raise ValueError("该条目不支持保留两份")
                        desc = local["descriptor"]
                        source = self._path(desc["path"])
                        suffix = "-本地副本-" + uuid.uuid4().hex[:8]
                        copy = source.with_name(source.stem + suffix + source.suffix)
                        if desc.get("doc_id"):
                            from .store import _frontmatter_parse, _frontmatter_dump
                            meta, body = _frontmatter_parse(source.read_text(encoding="utf-8-sig"))
                            meta["id"] = uuid.uuid4().hex
                            meta["title"] = str(meta.get("title", source.stem)) + "（本地副本）"
                            copy.write_text(_frontmatter_dump(meta) + "\n" + body, encoding="utf-8")
                        else:
                            shutil.copyfile(source, copy)
                    result = self.apply_many([self._change(remote, (local or {}).get("version", 0))])
                if not result["accepted"]:
                    raise ValueError((result["failed"] or [{"message": "内容又有变化，请重新确认"}])[0]["message"])
                self._base(peer, remote)
            elif choice in ("local", "merge"):
                if not local:
                    raise ValueError("本地版本不存在")
                if choice == "merge":
                    if local["descriptor"]["scope"] != "documents":
                        raise ValueError("只能手动合并 Markdown 文档")
                    text = payload.get("text")
                    if not isinstance(text, str) or len(text.encode("utf-8")) > 2 * 1024 * 1024:
                        raise ValueError("合并内容过大")
                    temp = self.directory / (uuid.uuid4().hex + ".md")
                    try:
                        temp.write_text(text, encoding="utf-8")
                        sha, size = self._store_blob(temp)
                    finally:
                        temp.unlink(missing_ok=True)
                    desc = {**local["descriptor"], "blob": sha, "size": size}
                    result = self.apply_many([{"key": key, "descriptor": desc, "expected_version": local["version"]}])
                    if not result["accepted"]:
                        raise ValueError((result["failed"] or [{"message": "本地内容已变化"}])[0]["message"])
                    local = result["accepted"][0]
                self._transfer(cfg["url"], local, upload=True)
                result = self._request(cfg["url"], "/api/sync/apply", {"changes": [self._change(local, remote["version"])]})
                if not result["accepted"]:
                    raise ValueError((result["failed"] or [{"message": "服务器内容已变化，请重新同步"}])[0]["message"])
                remote_rows[key] = result["accepted"][0]
                self._base(peer, remote_rows[key])
            else:
                raise ValueError("冲突处理选项无效")
            self._remember_remote(peer, remote_rows)
            self.refresh()
            status = self.status()
            phase = "conflict" if status["conflicts"] else "pending" if status["upload"] or status["download"] else "synced"
            self._status.update(phase=phase, error="")
            if phase == "synced":
                self._status["last_success"] = time.time()
            self._persist_status()
            return self.status()
        except Exception as exc:
            self._status.update(phase="conflict", error=str(exc)[:500])
            raise
        finally:
            self._persist_status()
            self._cycle_lock.release()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, daemon=True, name="workbench-sync")
        self._thread.start()

    def _worker(self):
        last_run, last_signature, changed_at = 0, None, 0
        while not self._stop.is_set():
            try:
                cfg = self.config()
                if cfg["mode"] != "off":
                    rows = self.refresh()
                    signature = digest({k: v["hash"] for k, v in rows.items() if v["scope"] in cfg["scopes"]})
                    now = time.monotonic()
                    if signature != last_signature:
                        last_signature, changed_at = signature, now
                    if cfg["mode"] == "auto" and (now - last_run >= cfg["interval"] or changed_at and now - changed_at >= 3):
                        self.synchronize()
                        last_run, changed_at = time.monotonic(), 0
            except Exception as exc:
                self._status.update(phase="error", error=str(exc)[:500])
            self._wake.wait(5)
            self._wake.clear()

    def stop(self):
        self._stop.set()
        self._wake.set()
