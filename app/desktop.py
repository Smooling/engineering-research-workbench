"""Windows window controls, tray lifecycle and per-data-directory single instance."""
from __future__ import annotations

import ctypes
import hashlib
import json
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Callable
from .focus_timer import FocusTimer


class SingleInstance:
    """A named event restores the first process without exposing an HTTP endpoint."""

    def __init__(self, data_root: Path):
        self.primary = True
        self._handles: list[int] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._event = None
        if sys.platform != "win32":
            return
        from ctypes import wintypes
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self._kernel.CreateEventW.restype = wintypes.HANDLE
        self._kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self._kernel.CreateMutexW.restype = wintypes.HANDLE
        self._kernel.SetEvent.argtypes = [wintypes.HANDLE]
        self._kernel.SetEvent.restype = wintypes.BOOL
        self._kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._kernel.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        key = hashlib.sha256(str(data_root.resolve()).casefold().encode("utf-8")).hexdigest()[:24]
        prefix = "Local\\ResearchWorkbench." + key
        self._event = self._kernel.CreateEventW(None, False, False, prefix + ".Show")
        if not self._event:
            raise ctypes.WinError(ctypes.get_last_error())
        self._handles.append(self._event)
        mutex = self._kernel.CreateMutexW(None, False, prefix + ".Instance")
        error = ctypes.get_last_error()
        if not mutex:
            self.close()
            raise ctypes.WinError(error)
        self._handles.append(mutex)
        self.primary = error != 183  # ERROR_ALREADY_EXISTS
        if not self.primary:
            self._kernel.SetEvent(self._event)

    def listen(self, show: Callable[[], Any]) -> None:
        if not self.primary or self._event is None:
            return
        def wait():
            while not self._stop.is_set():
                result = self._kernel.WaitForSingleObject(self._event, 500)
                if result == 0 and not self._stop.is_set():
                    show()
                elif result == 0xFFFFFFFF:
                    break
        self._thread = threading.Thread(target=wait, name="desktop-activation", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._event:
            self._kernel.SetEvent(self._event)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        for handle in reversed(self._handles):
            self._kernel.CloseHandle(handle)
        self._handles.clear()
        self._event = None


class DesktopController:
    def __init__(self, title: str, asset_root: Path, state: dict[str, Any], save_state: Callable,
                 *, start_hidden: bool = False):
        self.title = title
        self.asset_root = asset_root
        self.state = dict(state)
        self.save_state = save_state
        self.window = None
        self.tray = None
        self.tray_available = False
        self.hidden = False
        self.quitting = False
        self.restart_requested = False
        self.start_hidden = start_hidden
        self._show_pending = False
        self._notified = False
        self._quit_lock = threading.Lock()
        self._tray_ready = threading.Event()
        self._window_ready = threading.Event()
        self._native_frame = None
        self._resize_borders = None
        self._exit_event = threading.Event()
        self._exit_token: str | None = None
        self._exit_approved = False
        self.focus_timer = FocusTimer(self._focus_completed)
        self.focus_reminder = None
        self.theme = "light"

    def attach(self, window) -> None:
        self.window = window
        window.events.closing += self.on_closing
        window.events.minimized += self.on_minimized
        window.events.maximized += self.on_maximized
        window.events.restored += self.on_restored
        window.events.resized += self.on_resized
        window.events.before_show += self.apply_native_appearance

    def snapshot(self) -> dict[str, Any]:
        return {"title": self.title, "maximized": bool(self.state.get("maximized")),
                "tray_available": self.tray_available, "hidden": self.hidden,
                "close_action": self.state.get("close_action", "tray")}

    def publish(self) -> None:
        if not self._window_ready.is_set():
            return
        try:
            payload = json.dumps(self.snapshot(), ensure_ascii=False)
            self.window.evaluate_js(f"window.dispatchEvent(new CustomEvent('workbench:window-state',{{detail:{payload}}}))")
        except Exception:
            pass  # Reload/navigation may temporarily remove the bridge.

    def start(self) -> None:
        self._window_ready.set()
        if sys.platform == "win32":
            from .desktop_notification import FocusReminder
            self.focus_reminder = FocusReminder(self.window, self.title, self.show)
            self.focus_reminder.set_theme(self.theme)
        self.start_tray()
        if self._show_pending or not self.start_hidden or not self.tray_available:
            self.show()
        else:
            self.hide()
        self.publish()

    def start_tray(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import pystray
            from .windows_tray import WindowsTrayIcon
            from PIL import Image
            with Image.open(self.asset_root / "web" / "favicon.png") as source:
                image = source.convert("RGBA").resize((64, 64))
            menu = pystray.Menu(
                pystray.MenuItem("打开科研工作台", lambda *_: self.show(), default=True),
                pystray.MenuItem("隐藏到托盘", lambda *_: self.hide()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", lambda *_: self.request_quit()),
            )
            self.tray = WindowsTrayIcon("ResearchWorkbench", image, self.title, menu)
            def ready(icon):
                icon.visible = True
                self._tray_ready.set()
            self.tray.run_detached(setup=ready)
            self.tray_available = self._tray_ready.wait(5)
            if not self.tray_available:
                self.tray.stop()
                self.tray = None
        except Exception as exc:
            print(f"[desktop] tray unavailable; retaining taskbar access: {exc}")
            if self.tray:
                try:
                    self.tray.stop()
                except Exception:
                    pass
            self.tray = None
            self.tray_available = False

    def show(self) -> dict[str, Any]:
        if self.quitting:
            return self.snapshot()
        if not self.window or not self._window_ready.is_set():
            self._show_pending = True
            return self.snapshot()
        self._show_pending = False
        self.hidden = False
        if self.state.get("maximized"):
            self.window.maximize()
        else:
            self.window.restore()
        self.window.show()
        self.publish()
        return self.snapshot()

    def hide(self) -> dict[str, Any]:
        if self.quitting or not self.window:
            return self.snapshot()
        self.save_state(self.state)
        if self.tray_available:
            self.hidden = True
            self.window.hide()
            if not self._notified and self.tray:
                try:
                    self.tray.notify("已在后台运行。点击托盘图标打开窗口，从右键菜单退出。", self.title)
                except Exception:
                    pass
                self._notified = True
        else:
            self.window.minimize()
        self.publish()
        return self.snapshot()

    def toggle_maximize(self) -> dict[str, Any]:
        if self.state.get("maximized"):
            self.window.restore()
            self.state["maximized"] = False
        else:
            self.window.maximize()
            self.state["maximized"] = True
        self.publish()
        return self.snapshot()

    def minimize(self) -> dict[str, Any]:
        self.hidden = False
        self.window.minimize()
        self.publish()
        return self.snapshot()

    def set_close_action(self, action: str) -> dict[str, Any]:
        if action not in ("tray", "quit"):
            raise ValueError("Unknown close action")
        self.state["close_action"] = action
        self.save_state(self.state)
        self.publish()
        return self.snapshot()

    def request_close(self):
        if self.state.get("close_action", "tray") == "quit":
            return self.request_quit()
        return self.hide()

    def on_closing(self):
        if self.quitting:
            return True
        # Return before dispatching UI calls: FormClosing blocks the UI thread.
        threading.Thread(target=self.request_close, name="desktop-close-action", daemon=True).start()
        return False

    def resize_from_edge(self, edge: str, *, mouse: bool = False) -> bool:
        # The bridge runs on a worker. Release WebView's mouse capture and enter
        # the native sizing loop on the window's owning thread.
        edges = {"w": 1, "e": 2, "n": 3, "nw": 4, "ne": 5, "s": 6, "sw": 7, "se": 8}
        if sys.platform != "win32" or edge not in edges or self.state.get("maximized"):
            return False
        from ctypes import wintypes
        from System import Action
        native = self.window.native
        if native is None or native.IsDisposed:
            return False
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.SendMessageW.argtypes = user.PostMessageW.argtypes
        user.SendMessageW.restype = ctypes.c_ssize_t
        user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user.GetAsyncKeyState.restype = ctypes.c_short
        user.IsZoomed.argtypes = [wintypes.HWND]
        def resize():
            if native.IsDisposed:
                return
            hwnd = int(native.Handle.ToInt64())
            if user.IsZoomed(hwnd) or (mouse and not user.GetAsyncKeyState(0x01) & 0x8000):
                return  # A released click must not leave keyboard sizing active.
            user.ReleaseCapture()
            if mouse:
                point = wintypes.POINT()
                user.GetCursorPos(ctypes.byref(point))
                position = (point.x & 0xffff) | ((point.y & 0xffff) << 16)
                user.SendMessageW(hwnd, 0x00A1, edges[edge] + 9, position)  # WM_NCLBUTTONDOWN
            else:
                user.PostMessageW(hwnd, 0x0112, 0xF000 | edges[edge], 0)  # SC_SIZE
        native.BeginInvoke(Action(resize))
        return True

    def on_minimized(self):
        self.publish()

    def on_maximized(self):
        self.state["maximized"] = True
        self.publish()

    def on_restored(self):
        if not self.hidden:
            self.state["maximized"] = False
        self.publish()

    def on_resized(self, width, height):
        if not self.hidden and not self.state.get("maximized") and width >= 400 and height >= 300:
            self.state["width"], self.state["height"] = int(width), int(height)

    def request_quit(self, *, restart: bool = False, force: bool = False) -> bool:
        if not self._quit_lock.acquire(blocking=False):
            return False
        try:
            if self.quitting:
                return True
            if not force and self.window and self._window_ready.is_set():
                try:
                    dirty = self.window.evaluate_js("Boolean(window.ERWDesktop?.hasUnsavedChanges?.())")
                    if dirty:
                        self.show()
                        if not self._request_editor_exit():
                            return False
                except Exception as exc:
                    # Keep a live window reachable if the page cannot report its state.
                    print(f"[desktop] could not confirm unsaved state: {exc}")
                    self.show()
                    if not self.window.create_confirmation_dialog(self.title, "无法确认页面的保存状态。仍要退出吗？"):
                        return False
            self.restart_requested = restart
            self.quitting = True
            self.focus_timer.close()
            if self.focus_reminder:
                self.focus_reminder.close()
            self.save_state(self.state)
            if self.window:
                self.window.destroy()
            return True
        finally:
            self._quit_lock.release()

    def _request_editor_exit(self) -> bool:
        """The page can save/discard/cancel before acknowledging a native exit."""
        token = self._exit_token = uuid.uuid4().hex
        self._exit_approved = False
        self._exit_event.clear()
        try:
            started = self.window.evaluate_js(
                "Boolean(window.ERWDesktop?.requestExit && (window.ERWDesktop.requestExit("
                + json.dumps(token) + "), true))")
            if not started:
                raise RuntimeError("Editor exit dialog is not available")
            if not self._exit_event.wait(300):
                return False
            return self._exit_approved
        finally:
            self._exit_token = None

    def resolve_exit(self, token: str, approved: bool) -> bool:
        if not self._exit_token or token != self._exit_token:
            return False
        self._exit_approved = approved is True
        self._exit_event.set()
        return True

    def stop(self) -> None:
        self.focus_timer.close()
        self.save_state(self.state)
        if self.tray:
            try:
                self.tray.stop()
            except Exception as exc:
                print(f"[desktop] tray stop failed: {exc}")
        self.tray_available = False

    def publish_focus(self, *, completed=False, completion_mode=None, completion_id=None) -> None:
        if not self.window or not self._window_ready.is_set() or self.quitting:
            return
        try:
            payload = json.dumps({**self.focus_timer.snapshot(), "completed": completed,
                                  "completion_mode": completion_mode, "completion_id": completion_id}, ensure_ascii=False)
            self.window.evaluate_js("window.dispatchEvent(new CustomEvent('workbench:focus-state',{detail:" + payload + "}))")
        except Exception:
            pass  # A hidden/reloading page must not prevent the native notification.

    def _focus_completed(self, mode: str, total: float, generation: int) -> None:
        if self.quitting:
            return
        message = "专注时间已结束，休息一下吧。" if mode == "专注" else "休息时间已结束，可以开始下一段专注。"
        if self.focus_reminder:
            try:
                self.focus_reminder.notify(mode, message)
            except Exception as exc:
                print(f"[desktop] focus notification failed: {exc}")
        self.publish_focus(completed=True, completion_mode=mode, completion_id=generation)

    def set_theme(self, theme: str) -> None:
        self.theme = "dark" if theme == "dark" else "light"
        if self._resize_borders:
            self._resize_borders.set_theme(self.theme)
        if self.focus_reminder:
            self.focus_reminder.set_theme(self.theme)

    def apply_native_appearance(self):
        if sys.platform != "win32":
            return
        from .windows_frame import WindowsFrame, NativeResizeBorders
        hwnd = int(self.window.native.Handle.ToInt64())
        self._native_frame = WindowsFrame(hwnd)
        self._resize_borders = NativeResizeBorders(self.window.native, self.resize_from_edge, self._native_frame.user)
        self._resize_borders.set_theme(self.theme)
        try:
            from ctypes import wintypes
            dwm = ctypes.WinDLL("dwmapi")
            dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
            rounded = ctypes.c_int(2)  # DWMWCP_ROUND; ignored on older Windows.
            dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rounded), ctypes.sizeof(rounded))
        except Exception as exc:
            print(f"[desktop] native corner preference unavailable: {exc}")


class DesktopBridge:
    """Window operations and the background focus clock for the local page."""

    def __init__(self, controller: DesktopController):
        self._controller = controller

    def desktop_get_state(self):
        return self._controller.snapshot()

    def desktop_hide(self):
        return self._controller.hide()

    def desktop_minimize(self):
        return self._controller.minimize()

    def desktop_close(self):
        return self._controller.request_close()

    def desktop_set_close_action(self, action: str):
        return self._controller.set_close_action(action)

    def desktop_toggle_maximize(self):
        return self._controller.toggle_maximize()

    def desktop_quit(self):
        return self._controller.request_quit()

    def desktop_resolve_exit(self, token: str, approved: bool):
        return self._controller.resolve_exit(token, approved)

    def desktop_resize(self, edge: str):
        return self._controller.resize_from_edge(edge, mouse=True)

    def desktop_focus_state(self):
        return self._controller.focus_timer.snapshot()

    def desktop_set_theme(self, theme: str):
        self._controller.set_theme(theme)

    def desktop_focus_start(self, seconds: float, mode: str, total: float):
        return self._controller.focus_timer.configure(seconds, mode, total, running=True)

    def desktop_focus_pause(self):
        return self._controller.focus_timer.pause()

    def desktop_focus_reset(self, seconds: float, mode: str):
        return self._controller.focus_timer.configure(seconds, mode)
