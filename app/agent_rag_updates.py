"""Low-cost RAG maintenance: stat polling, debounce and persisted scheduling.

Only the local server owns a scheduler. Status/search never start updates.
Unchanged chunks are reused by the existing atomic-generation index builder.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time

from . import agent_memory as brain

_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD = None


def _path():
    return brain.root() / "rag-updates.json"


def status():
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def reset():
    with _LOCK:
        brain.atomic_json(_path(), {})


def source_stamp(opts):
    from . import store, literature
    entries = []
    for kind, path in store._iter_docs():
        try:
            stat = path.stat()
            entries.append((kind, str(path), stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            continue
    if opts["include_pdf"]:
        paths = [literature._registry_path(), *literature._pdf_dir().glob("*.pdf")]
        for path in paths:
            try:
                stat = path.stat()
                entries.append(("pdf", str(path), stat.st_size, stat.st_mtime_ns))
            except FileNotFoundError:
                continue
    return hashlib.sha256(brain.encode(sorted(entries)).encode()).hexdigest()


def tick(now=None, background=True):
    from . import agent_rag as rag, agent_runtime
    now = time.time() if now is None else now
    with _LOCK:
        opts = rag.settings(private=True)
        if not (opts["realtime_updates"] or opts["scheduled_updates"]):
            return "disabled"
        if not agent_runtime.settings()["rag_enabled"] or opts["mode"] == "keyword" or not opts["base_url"] or not opts["model"]:
            return "inactive"
        # Never queue another build behind one that is running or being cleared.
        with rag._LOCK:
            job = rag._JOBS.get(str(brain.root()), {})
            if job.get("state") in ("running", "cancelling", "clearing"):
                return "busy"
        state = status()
        previous = dict(state)
        policy = brain.encode({k: opts[k] for k in ("realtime_updates", "scheduled_updates", "update_interval_minutes", "update_debounce_seconds")})
        if state.get("policy") != policy:
            state.update(policy=policy, next_scheduled_at=now + opts["update_interval_minutes"] * 60)
        observed = source_stamp(opts)
        fingerprint = rag._fingerprint(opts)
        stamp = observed + ":" + fingerprint
        if state.get("observed_stamp") != stamp:
            state.update(observed_stamp=stamp, pending_since=now)
        with rag._connection() as conn:
            manifest = rag._manifest(conn)
        if manifest.get("source_stamp") == observed and manifest.get("fingerprint") == fingerprint:
            state["attempted_stamp"] = stamp
        scheduled = opts["scheduled_updates"] and now >= state["next_scheduled_at"]
        live = opts["realtime_updates"] and stamp != state.get("attempted_stamp") and now - state.get("pending_since", now) >= opts["update_debounce_seconds"]
        reason = "scheduled" if scheduled else "realtime" if live else ""
        if reason:
            # Persist before dispatch. A failure/cancel doesn't cause a live
            # retry loop; next edit, manual update or scheduled run can retry.
            state.update(attempted_stamp=stamp, last_trigger=reason, last_attempt_at=now, next_scheduled_at=now + opts["update_interval_minutes"] * 60)
        if state != previous:
            brain.atomic_json(_path(), state)
        if reason:
            try:
                rag.build_index(background=background, reason=reason)
            except ValueError:
                return "deferred"
        return reason or "waiting"


def start():
    global _THREAD, _STOP
    with _LOCK:
        if _THREAD and _THREAD.is_alive() and not _STOP.is_set():
            return
        _STOP = threading.Event()
        stop_event = _STOP
        def loop():
            while not stop_event.wait(5):
                try:
                    tick()
                except Exception:
                    # Service availability is independent of optional embedding
                    # maintenance; provider failures are visible in job status.
                    pass
        _THREAD = threading.Thread(target=loop, name="rag-maintenance", daemon=True)
        _THREAD.start()


def stop():
    _STOP.set()
    from . import agent_rag as rag
    with rag._LOCK:
        job = rag._JOBS.get(str(brain.root()), {})
        if job.get("reason") in ("realtime", "scheduled") and job.get("state") == "running":
            job["state"] = "cancelling"
            job["cancel"].set()
