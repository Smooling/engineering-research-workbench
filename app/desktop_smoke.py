"""Opt-in native integration checks, invoked only with --smoke-test OUTPUT."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path


def run(controller, url: str, output: Path, data_root: Path) -> None:
    from ctypes import wintypes
    from app import paths
    window = controller.window
    checks = []
    result = {"ok": False, "frozen": paths.FROZEN, "url": url, "checks": checks}
    output = output.resolve()
    previous = {}
    ui_errors = []
    def ui_exception(_sender, event):
        ui_errors.append(str(event.Exception))
    def register_ui_errors():
        import System.Windows.Forms as Forms
        Forms.Application.ThreadException += ui_exception
    controller.focus_reminder._dispatch(register_ui_errors, wait=True)
    try:
        previous = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    restarted = previous.get("awaiting_restart") and previous.get("data_dir") == str(data_root)
    if restarted:
        checks.extend(previous["checks"])

    def wait_until(predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.1)
        raise AssertionError("Timed out waiting for native window state")

    def check(name, condition):
        assert condition, name
        checks.append(name)

    try:
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        user.IsZoomed.argtypes = [wintypes.HWND]
        user.IsIconic.argtypes = [wintypes.HWND]
        user.GetForegroundWindow.restype = wintypes.HWND
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        hwnd = int(window.native.Handle.ToInt64())
        wait_until(lambda: window.evaluate_js("document.documentElement.dataset.desktop === 'true' && !!window.ERWDesktop?.hasUnsavedChanges && !!document.querySelector('.overview-dashboard')"), 25)
        check("native bridge and dashboard ready", True)
        check("page tools live in the native titlebar", window.evaluate_js("!!document.querySelector('#desktop-titlebar #page-title') && !!document.querySelector('#desktop-titlebar #weather-pill') && getComputedStyle(document.querySelector('#app .topbar')).display === 'none'"))
        check("refresh opens choices beside window controls", window.evaluate_js("!!document.querySelector('#desktop-reload-slot #reload-btn') && !document.querySelector('#reload-btn').textContent.trim()"))
        check("tray icon registered", controller.tray_available and controller.tray.visible)
        check("frameless window", str(window.native.FormBorderStyle) == "None")
        if restarted:
            check("quick restart launches a new desktop process", previous["pid"] != os.getpid())
            check("localStorage survives process restart", window.evaluate_js("localStorage.getItem('desktop-smoke-persistence')") == "retained")
            with urllib.request.urlopen(url + "/api/health", timeout=3) as response:
                check("quick restart restores HTTP service", json.load(response)["ok"])
            check("close preference survives process restart", controller.snapshot()["close_action"] == "quit")
            controller.tray()
            wait_until(lambda: bool(user.IsZoomed(hwnd)))
            check("restored startup maximization remains native", bool(user.IsZoomed(hwnd)))
            bounds = wintypes.RECT()
            user.GetWindowRect(hwnd, ctypes.byref(bounds))
            work = controller._native_frame.monitor_info().rcWork
            check("maximized startup keeps Windows taskbar visible", bounds.bottom <= work.bottom and bounds.right <= work.right and bounds.top >= work.top and bounds.left >= work.left)
            check("restart has no unhandled .NET UI exceptions", not ui_errors)
            result["ok"] = True
            result["awaiting_restart"] = False
            return
        if controller.start_hidden:
            check("background startup hides native window", controller.hidden and not user.IsWindowVisible(hwnd))
        controller.tray()  # Invoke the registered default tray action.
        wait_until(lambda: bool(user.IsWindowVisible(hwnd)))
        check("tray restore shows native window", True)
        controller.toggle_maximize()
        wait_until(lambda: bool(user.IsZoomed(hwnd)))
        check("maximize control maximizes native window", True)
        bounds = wintypes.RECT()
        user.GetWindowRect(hwnd, ctypes.byref(bounds))
        work = controller._native_frame.monitor_info().rcWork
        check("maximized bounds preserve Windows taskbar", bounds.bottom <= work.bottom and bounds.right <= work.right and bounds.top >= work.top and bounds.left >= work.left)
        controller.toggle_maximize()
        wait_until(lambda: not user.IsZoomed(hwnd))
        check("maximize control restores native window", True)
        controller.minimize()
        wait_until(lambda: bool(user.IsIconic(hwnd)))
        check("minimize retains taskbar window", not controller.hidden)
        controller.show()
        # Exercise the real Win32 sizing loop, including a keyboard adjustment.
        width = window.width
        check("resize request accepted", controller.resize_from_edge("e"))
        time.sleep(0.3)
        user.PostMessageW(hwnd, 0x0100, 0x27, 0)  # WM_KEYDOWN, VK_RIGHT
        user.PostMessageW(hwnd, 0x0100, 0x27, 0)
        user.PostMessageW(hwnd, 0x0100, 0x0D, 0)  # VK_RETURN commits sizing
        wait_until(lambda: window.width != width)
        check("borderless native edge resizing changes width", True)
        # A keyboard size command can work while WebView still captures mouse
        # drags. Exercise the HTML hit targets with real held-button movement.
        user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        original_cursor = wintypes.POINT()
        user.GetCursorPos(ctypes.byref(original_cursor))
        window.evaluate_js("window.__resizeCalls=[];window.__resizePointer=null;document.addEventListener('pointerdown',e=>window.__resizePointer={x:e.clientX,y:e.clientY,edge:e.target.dataset.desktopResize},true);const originalResize=pywebview.api.desktop_resize;pywebview.api.desktop_resize=(edge)=>{window.__resizeCalls.push(edge);return originalResize(edge)}")
        def mouse_resize(edge, dx, dy, *, outer=False):
            target = window.evaluate_js("(()=>{const e=document.querySelector('[data-desktop-resize=" + edge + "]'),r=e.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;return {x,y,width:innerWidth,height:innerHeight,dpr:devicePixelRatio,hit:document.elementFromPoint(x,y)?.dataset.desktopResize,zoom:document.documentElement.style.zoom,maximized:document.documentElement.dataset.windowMaximized}})()")
            rect, origin, before = wintypes.RECT(), wintypes.POINT(), wintypes.RECT()
            user.GetClientRect(hwnd, ctypes.byref(rect))
            from System.Drawing import Point
            browser_origin = window.native.webview.PointToScreen(Point(0,0))
            origin.x, origin.y = browser_origin.X, browser_origin.Y
            user.GetWindowRect(hwnd, ctypes.byref(before))
            scale = target["dpr"]
            x, y = round(origin.x + target["x"] * scale), round(origin.y + target["y"] * scale)
            if outer:
                inset = max(6,round(6 * scale)) if len(edge) == 2 else 2
                x = before.left + inset if "w" in edge else before.right - 1 - inset if "e" in edge else (before.left + before.right) // 2
                y = before.top + inset if "n" in edge else before.bottom - 1 - inset if "s" in edge else (before.top + before.bottom) // 2
            user.SetCursorPos(x, y)
            user.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
            try:
                time.sleep(.2)
                for step in range(1, 9):
                    user.SetCursorPos(x + round(dx * step / 8), y + round(dy * step / 8))
                    time.sleep(.025)
            finally:
                user.mouse_event(0x0004, 0, 0, 0, 0)
            after = wintypes.RECT()
            time.sleep(.15)
            user.GetWindowRect(hwnd, ctypes.byref(after))
            result.setdefault("resize_attempts", []).append({"edge":edge,"target":target,"position":[x,y],"before":[before.left,before.top,before.right,before.bottom],"after":[after.left,after.top,after.right,after.bottom],"events":window.evaluate_js("({calls:window.__resizeCalls,pointer:window.__resizePointer})")})
            check("mouse drag resizes " + ("outer " if outer else "") + edge + " edge", (not dx or abs((after.right-after.left)-(before.right-before.left)) >= 15) and (not dy or abs((after.bottom-after.top)-(before.bottom-before.top)) >= 15))
        try:
            for edge, dx, dy in [("e",40,0),("w",40,0),("n",0,30),("s",0,30),
                                  ("ne",30,20),("nw",30,-20),("se",30,20),("sw",30,-20)]:
                mouse_resize(edge, dx, dy)
            for edge, dx, dy in [("e",30,0),("w",30,0),("n",0,20),("s",0,20),
                                  ("ne",20,20),("nw",20,-20),("se",20,20),("sw",20,-20)]:
                mouse_resize(edge, dx, dy, outer=True)
            window.evaluate_js("document.querySelector('#zoom-btn').click();document.querySelector('[data-zoom=\"125\"]').click()")
            mouse_resize("e",30,0)
            mouse_resize("s",0,20)
            window.evaluate_js("document.querySelector('#zoom-btn').click();document.querySelector('[data-zoom=\"100\"]').click()")
        finally:
            user.SetCursorPos(original_cursor.x, original_cursor.y)
        # Shorten only the test deadline; exercise a real persistent native reminder.
        reminder = controller.focus_reminder
        window.evaluate_js("document.querySelector('[data-route=focus]').click()")
        wait_until(lambda: window.evaluate_js("!!document.querySelector('#focus-start')"))
        window.evaluate_js("document.querySelector('#focus-minutes').value=1; document.querySelector('#focus-apply').click()")
        wait_until(lambda: controller.focus_timer.snapshot()["total"] == 60)
        wait_until(lambda: window.evaluate_js("!document.querySelector('#focus-start').disabled"))
        window.evaluate_js("document.querySelector('#focus-start').click()")
        wait_until(lambda: controller.focus_timer.snapshot()["running"])
        wait_until(lambda: window.evaluate_js("!document.querySelector('#focus-start').disabled"))
        check("focus start is owned by the native clock", controller.focus_timer.snapshot()["total"] == 60)
        window.evaluate_js("document.querySelector('#focus-start').click()")
        wait_until(lambda: not controller.focus_timer.snapshot()["running"])
        check("focus pause reaches native clock", controller.focus_timer.snapshot()["seconds"] > 0)
        for count, mode in enumerate(("专注", "休息"), 1):
            controller.set_theme("dark" if count == 1 else "light")
            controller.focus_timer.configure(2, mode, 60, running=True)
            controller.publish_focus()
            controller.hide()
            wait_until(lambda: reminder.pending_count == count and reminder.form is not None and reminder.form.Visible)
            reminder._dispatch(lambda: None, wait=True)  # Wait for Form.Show to finish on its UI thread.
            reminder_hwnd = int(reminder.form.Handle.ToInt64())
            check(mode + " completion shows persistent reminder while hidden", controller.hidden and not user.IsWindowVisible(hwnd) and user.IsWindowVisible(reminder_hwnd))
            # Another application may gain focus while the countdown runs.
            # Assert that our reminder itself never becomes the foreground window.
            check(mode + " reminder does not steal input focus", user.GetForegroundWindow() != reminder_hwnd and not reminder.form.ContainsFocus)
            check(mode + " reminder has readable theme colors", reminder.heading.ForeColor.R > 200 if count == 1 else reminder.heading.ForeColor.R < 60)
            bounds = wintypes.RECT()
            user.GetWindowRect(reminder_hwnd, ctypes.byref(bounds))
            work = controller._native_frame.monitor_info().rcWork
            check(mode + " reminder stays above taskbar", bounds.bottom <= work.bottom and bounds.right <= work.right)
            def save_preview():
                from System.Drawing import Bitmap, Rectangle
                from System.Drawing.Imaging import ImageFormat
                bitmap = Bitmap(reminder.form.Width, reminder.form.Height)
                try:
                    reminder.form.DrawToBitmap(bitmap, Rectangle(0, 0, bitmap.Width, bitmap.Height))
                    bitmap.Save(str(output.with_name("reminder-" + reminder.theme + ".png")), ImageFormat.Png)
                finally:
                    bitmap.Dispose()
            reminder._dispatch(save_preview, wait=True)
            if count == 1:
                time.sleep(8)
                check("reminder does not expire or restore the main window", reminder.form is not None and user.IsWindowVisible(reminder_hwnd) and controller.hidden)
        check("unread reminders accumulate until acknowledged", reminder.pending_count == 2)
        user.PostMessageW(int(reminder.dismiss_button.Handle.ToInt64()), 0x00F5, 0, 0)  # BM_CLICK
        wait_until(lambda: reminder.form is None and reminder.pending_count == 0)
        check("manual acknowledgement dismisses reminder", True)
        controller.focus_timer.configure(1, "专注", 60, running=True)
        controller.publish_focus()
        wait_until(lambda: reminder.form is not None and reminder.form.Visible)
        reminder._dispatch(lambda: None, wait=True)
        user.PostMessageW(int(reminder.open_button.Handle.ToInt64()), 0x00F5, 0, 0)
        wait_until(lambda: reminder.form is None and bool(user.IsWindowVisible(hwnd)))
        check("reminder action opens workbench and dismisses itself", not controller.hidden)
        for button_name in ("close_button", "dismiss_button", "open_button"):
            controller.focus_timer.configure(.3, "专注", 60, running=True)
            controller.publish_focus()
            wait_until(lambda: reminder.form is not None and reminder.form.Visible)
            reminder._dispatch(lambda: None, wait=True)
            popup = reminder.form
            user.PostMessageW(int(getattr(reminder, button_name).Handle.ToInt64()), 0x00F5, 0, 0)
            wait_until(lambda: reminder.form is None and popup.IsDisposed)
            check(button_name + " can close a recreated reminder safely", not ui_errors)
        check("reminder clicks have no unhandled .NET UI exceptions", not ui_errors)
        wait_until(lambda: window.evaluate_js("document.querySelector('#focus-time').textContent === '00:00'"))
        check("focus completion state survives hidden window", True)
        window.evaluate_js("localStorage.setItem('desktop-smoke-persistence', 'retained'); document.querySelector('[data-route=notes]').click()")
        wait_until(lambda: window.evaluate_js("!!document.querySelector('#new-doc')"))
        window.evaluate_js("document.querySelector('#new-doc').click()")
        wait_until(lambda: window.evaluate_js("!!window.ERWDesktop.documentDraft?.()"))
        check("unmodified new document is an in-memory draft", not window.evaluate_js("window.ERWDesktop.hasUnsavedChanges()") and not list((data_root / "Workspace/Knowledge/Notes").glob("*.md")))
        window.evaluate_js("document.querySelector('#md-input').value += '\\nNative smoke edit'; document.querySelector('#md-input').dispatchEvent(new Event('input',{bubbles:true}))")
        user.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE, same path as Alt+F4
        wait_until(lambda: not user.IsWindowVisible(hwnd))
        check("native close hides to tray without destroying editor", controller.hidden and not controller.quitting)
        with urllib.request.urlopen(url + "/api/health", timeout=3) as response:
            check("HTTP service stays alive while hidden", json.load(response)["ok"])
        check("hidden editor remains mounted", window.evaluate_js("window.ERWDesktop.hasUnsavedChanges()"))
        args = [sys.executable]
        if not paths.FROZEN:
            args.append(str(paths.ASSET_ROOT / "client.py"))
        duplicate = subprocess.run([*args, "--data-dir", str(data_root)], timeout=30,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        check("second process exits without second instance", duplicate.returncode == 0)
        wait_until(lambda: bool(user.IsWindowVisible(hwnd)))
        check("second launch restores hidden window", True)
        controller.set_close_action("quit")
        exit_results = []
        exit_thread = threading.Thread(target=lambda: exit_results.append(controller.request_close()), daemon=True)
        exit_thread.start()
        wait_until(lambda: window.evaluate_js("!!document.querySelector('#workbench-dialog')"))
        check("native exit uses themed save/discard/cancel dialog", window.evaluate_js("document.querySelector('#workbench-dialog').getAttribute('role') === 'alertdialog' && !!document.querySelector('[data-dialog-result=save]')"))
        window.evaluate_js("document.querySelector('[data-dialog-result=cancel]').click()")
        exit_thread.join(5)
        check("canceling exit keeps the edited draft mounted", exit_results == [False] and not controller.quitting and window.evaluate_js("window.ERWDesktop.hasUnsavedChanges()"))
        window.evaluate_js("document.querySelector('#doc-save').click()")
        wait_until(lambda: window.evaluate_js("!window.ERWDesktop.documentDraft?.() && !window.ERWDesktop.hasUnsavedChanges()"))
        check("first explicit save creates one Markdown file", len(list((data_root / "Workspace/Knowledge/Notes").glob("*.md"))) == 1)
        # Reload must retain browser storage in non-private mode.
        window.load_url(url)
        wait_until(lambda: window.evaluate_js("document.documentElement.dataset.desktop === 'true'"))
        check("localStorage survives reload", window.evaluate_js("localStorage.getItem('desktop-smoke-persistence')") == "retained")
        controller.toggle_maximize()
        wait_until(lambda: bool(user.IsZoomed(hwnd)))
        result.update(awaiting_restart=True, pid=os.getpid(), data_dir=str(data_root))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        request = urllib.request.Request(url + "/api/system/restart", data=b"{}", headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            check("quick restart request accepted", json.load(response)["ok"])
        wait_until(lambda: controller.restart_requested)
    except Exception:
        result["error"] = traceback.format_exc()
        result["awaiting_restart"] = False
        if controller.focus_reminder:
            reminder = controller.focus_reminder
            result["reminder"] = {"count": reminder.pending_count, "main_hidden": controller.hidden,
                                  "main_visible": bool(user.IsWindowVisible(hwnd)),
                                  "visible": bool(reminder.form and reminder.form.Visible),
                                  "handle": int(reminder.form.Handle.ToInt64()) if reminder.form else None,
                                  "foreground": user.GetForegroundWindow()}
        try:
            result["page"] = window.evaluate_js("({url:location.href,desktop:document.documentElement.dataset.desktop,route:document.documentElement.dataset.route,main:document.getElementById('main')?.innerText?.slice(0,1500),titlebar:!!document.querySelector('#desktop-titlebar #page-title')})")
        except Exception:
            pass
        print(result["error"])
    finally:
        if ui_errors:
            result["ui_errors"] = ui_errors
            result["ok"] = False
            result["awaiting_restart"] = False
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if not result.get("awaiting_restart"):
            controller.request_quit(force=True)
