"""Workspace-scoped service shared by the browser server and desktop host."""
import threading
from . import config, indexer
from .paths import DATA_ROOT
from .sync_engine import SyncEngine

_lock = threading.RLock()
_engine = None


def _reload():
    config.reload_all()
    indexer.sync(immediate=True)
    indexer.refresh_todos()


def get():
    global _engine
    root = config.workspace_root().resolve()
    with _lock:
        if _engine is None or _engine.root != root:
            if _engine:
                _engine.stop()
            _engine = SyncEngine(root, DATA_ROOT, _reload)
            _engine.start()
        return _engine


def stop():
    global _engine
    with _lock:
        if _engine:
            _engine.stop()
            _engine = None
