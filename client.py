"""Portable Windows desktop: local server, borderless WebView2 and system tray."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

from app import paths
from app.desktop import DesktopBridge, DesktopController, SingleInstance


def _setup_logging():
    if paths.FROZEN or sys.stdout is None:
        stream = open(paths.DATA_ROOT / "workbench.log", "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _health(url: str) -> dict:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=1.5) as resp:
            return json.load(resp) if resp.status == 200 else {}
    except (OSError, ValueError):
        return {}


def _wait_ready(url: str, timeout: float = 15) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = _health(url)
        if health.get("ok") and health.get("version"):
            return True
        time.sleep(0.15)
    return False


def _clamped_window_size(width: int = 1440, height: int = 900) -> tuple[int, int]:
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        user = ctypes.windll.user32
        if user.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            dpi = user.GetDpiForSystem() if hasattr(user, "GetDpiForSystem") else 96
            scale = max(1, dpi / 96)
            width = min(width, int((rect.right - rect.left) / scale))
            height = min(height, int((rect.bottom - rect.top) / scale))
    except Exception:
        pass
    return width, height


def _load_window_state() -> dict:
    fallback = {"maximized": False, "width": 0, "height": 0, "close_action": "tray"}
    try:
        data = json.loads((paths.DATA_ROOT / "window-state.json").read_text(encoding="utf-8-sig"))
        width, height = int(data.get("width") or 0), int(data.get("height") or 0)
        if 400 <= width <= 8000 and 300 <= height <= 4000:
            return {"maximized": bool(data.get("maximized")), "width": width, "height": height,
                    "close_action": "quit" if data.get("close_action") == "quit" else "tray"}
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        print(f"[desktop] invalid saved window state: {exc}")
    return fallback


_state_lock = threading.Lock()


def _save_window_state(state: dict) -> None:
    with _state_lock:
        try:
            target = paths.DATA_ROOT / "window-state.json"
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            temporary.replace(target)
        except OSError as exc:
            print(f"[desktop] could not save window state: {exc}")


def _preferred_service_port(host: str, configured_port: int) -> int:
    try:
        saved = json.loads((paths.DATA_ROOT / "desktop-service.json").read_text(encoding="utf-8"))
        port = int(saved["port"])
        if saved.get("host") == host and saved.get("configured_port") == configured_port and 1 <= port <= 65535:
            return port
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return configured_port


def _remember_service_port(host: str, configured_port: int, port: int) -> None:
    try:
        target = paths.DATA_ROOT / "desktop-service.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"host":host,"configured_port":configured_port,"port":port}), encoding="utf-8")
        temporary.replace(target)
    except OSError as exc:
        print(f"[desktop] could not save local service port: {exc}")


def _open_service():
    import server
    from app import config, workspace
    cfg = config.get_app()
    host = str(cfg.get("host") or "127.0.0.1")
    local_host = "127.0.0.1" if host == "0.0.0.0" else host
    configured_port = int(cfg.get("port") or 8765)
    preferred_port = _preferred_service_port(host, configured_port)
    url = f"http://{local_host}:{preferred_port}"
    health = _health(url)
    expected = (workspace.ensure_workspace() / "System" / "Cache" / "index.sqlite").resolve()
    # Reuse only a workbench serving this workspace, never an unrelated app.
    index_path = health.get("index", {}).get("path")
    if health.get("ok") and index_path and Path(index_path).resolve() == expected:
        return None, cfg, url
    try:
        httpd, cfg, _ = server.build_server(port_override=preferred_port, auto_open_browser=False)
    except OSError as exc:
        if getattr(exc, "winerror", None) != 10048 and exc.errno != 98:
            raise
        httpd, cfg, _ = server.build_server(port_override=_free_port(), auto_open_browser=False)
    port = httpd.server_address[1]
    _remember_service_port(host, configured_port, port)
    return httpd, cfg, f"http://{local_host}:{port}"


def _run_window(url: str, cfg: dict, gate: SingleInstance, server_stopped: threading.Event | None,
                httpd, *, background: bool = False, smoke_output: Path | None = None) -> bool:
    if paths.FROZEN and sys.platform == "win32":
        from app.windows_runtime import ensure_clr_config
        ensure_clr_config(Path(sys.executable))
    import webview
    saved = _load_window_state()
    width, height = _clamped_window_size(saved["width"] or 1440, saved["height"] or 900)
    saved.update(width=width, height=height)
    controller = DesktopController(str(cfg.get("app_name") or "科研工作台"), paths.ASSET_ROOT,
                                   saved, _save_window_state, start_hidden=background)
    webview.settings["DRAG_REGION_SELECTOR"] = ".desktop-drag-region"
    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
    window = webview.create_window(
        controller.title, url, js_api=DesktopBridge(controller), width=width, height=height,
        min_size=(min(1000, width), min(680, height)),
        frameless=True, easy_drag=False, shadow=True, resizable=True,
        hidden=True, background_color="#F7F8FB", text_select=True,
    )
    controller.attach(window)
    gate.listen(controller.show)

    def started():
        controller.start()
        if server_stopped:
            def supervise():
                server_stopped.wait()
                if not controller.quitting:
                    restarting = bool(getattr(httpd, "restart_requested", False))
                    controller.request_quit(restart=restarting, force=restarting)
            threading.Thread(target=supervise, name="desktop-server-monitor", daemon=True).start()
        if smoke_output:
            from app.desktop_smoke import run
            run(controller, url, smoke_output, paths.DATA_ROOT)

    icon = paths.ASSET_ROOT / "research-workstation.ico"
    try:
        webview.start(started, gui="edgechromium", private_mode=False,
                      storage_path=str(paths.DATA_ROOT / ".webview-profile"),
                      icon=str(icon) if icon.exists() else None)
    finally:
        controller.stop()
    return controller.restart_requested


def _launch_arguments(argv: list[str]) -> list[str]:
    return [sys.executable, *([] if paths.FROZEN else [str(Path(__file__).resolve())]), *argv]


def _restart_environment() -> dict[str, str]:
    environment = dict(os.environ)
    if paths.FROZEN:
        # A onefile restart must unpack its own resources before the old
        # bootloader removes its temporary directory (PyInstaller >= 6.9).
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="科研工作台 Windows 桌面客户端")
    parser.add_argument("--background", action="store_true", help="启动后隐藏到系统托盘")
    parser.add_argument("--data-dir", type=Path, help="指定便携数据目录（默认 exe 所在目录）")
    parser.add_argument("--smoke-test", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.data_dir:
        paths.DATA_ROOT = args.data_dir.expanduser().resolve()
    paths.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    gate = SingleInstance(paths.DATA_ROOT)
    if not gate.primary:
        gate.close()
        return 0
    httpd = None
    restart = False
    try:
        _setup_logging()
        httpd, cfg, url = _open_service()
        stopped = None
        if httpd:
            stopped = threading.Event()
            def serve():
                try:
                    httpd.serve_forever(poll_interval=0.25)
                except Exception:
                    traceback.print_exc()
                finally:
                    stopped.set()
            threading.Thread(target=serve, name="workbench-http", daemon=True).start()
        if not _wait_ready(url):
            raise RuntimeError(f"本地服务未能就绪：{url}")
        restart = _run_window(url, cfg, gate, stopped, httpd, background=args.background,
                              smoke_output=args.smoke_test)
    finally:
        if httpd:
            httpd.shutdown()
            httpd.server_close()
            try:
                from app import indexer
                indexer.checkpoint()
            except Exception as exc:
                print(f"[client] index checkpoint skipped: {exc}")
        gate.close()
    if restart:
        subprocess.Popen(_launch_arguments(argv), env=_restart_environment(),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        traceback.print_exc()
        if "--smoke-test" in sys.argv:
            output = Path(sys.argv[sys.argv.index("--smoke-test") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({"ok":False,"error":traceback.format_exc()}), encoding="utf-8")
        elif sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"启动失败：{exc}\n\n请查看数据目录中的 workbench.log。\n需要 Microsoft Edge WebView2 Runtime。", "科研工作台", 0x10)
        raise SystemExit(1)
