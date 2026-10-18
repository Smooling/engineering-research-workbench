"""Embed the existing backend without desktop dependencies or subprocesses."""
from __future__ import annotations

import os
import threading
import zipfile
from pathlib import Path

_lock = threading.RLock()
_server = None
_thread = None
_url = None


def start(data_directory: str, asset_directory: str) -> str:
    global _server, _thread, _url
    with _lock:
        if _server is not None:
            return _url
        root = Path(data_directory).resolve()
        root.mkdir(parents=True, exist_ok=True)
        os.environ["WORKBENCH_DATA_ROOT"] = str(root)
        os.environ["WORKBENCH_ASSET_ROOT"] = str(Path(asset_directory).resolve())
        os.environ["WORKBENCH_PLATFORM"] = "android"
        from app import config
        if not (root / "config" / "app.json").exists():
            defaults = config.get_public()["app"]
            defaults.update(host="127.0.0.1", auto_open_browser=False, workspace="Workspace")
            defaults["workspace_migration"] = {"enabled": False, "copy_legacy_data": False}
            config.save_app(defaults)
        from server import build_server
        # A fixed loopback origin preserves WebView localStorage across restarts.
        # Never use the configurable desktop host: this server is phone-local.
        _server, _cfg, _url = build_server(port_override=8765, auto_open_browser=False,
                                         host_override="127.0.0.1")
        _thread = threading.Thread(target=_serve, name="android-workbench", daemon=True)
        _thread.start()
        return _url


def _serve() -> None:
    # /api/system/restart must retain the same embedded interpreter and origin.
    while True:
        _server.serve_forever(poll_interval=0.25)
        if not getattr(_server, "restart_requested", False):
            break
        _server.restart_requested = False
        from app import config, indexer
        config.reload_all()
        indexer.sync(immediate=True)


def export_backup(destination: str) -> str:
    from app import config
    from app.paths import DATA_ROOT
    from app.sync_engine import mutation_lock
    root = config.workspace_root()
    with _lock, mutation_lock, zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            if path.is_symlink() or not path.is_file():
                continue
            if any(part.startswith(".") for part in rel.parts) or rel.parts[:2] == ("System", "Sync"):
                continue
            if "Cache" in rel.parts or "Previews" in rel.parts:
                continue
            archive.write(path, "Workspace/" + rel.as_posix())
        # Provider keys and device-specific synchronization state are excluded.
        for name in ("app.json", "rss.json", "ui-preferences.json"):
            path = DATA_ROOT / "config" / name
            if path.is_file():
                archive.write(path, "config/" + name)
    return destination
