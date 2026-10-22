"""Keep a borderless WinForms window inside the active monitor's work area."""
from __future__ import annotations

import ctypes
from ctypes import wintypes


class MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class MinMaxInfo(ctypes.Structure):
    _fields_ = [(name, wintypes.POINT) for name in
               ("ptReserved", "ptMaxSize", "ptMaxPosition", "ptMinTrackSize", "ptMaxTrackSize")]


def work_area_bounds(monitor, work) -> tuple[int, int, int, int]:
    """WM_GETMINMAXINFO positions are relative to the current monitor origin."""
    return (work.left - monitor.left, work.top - monitor.top,
            work.right - work.left, work.bottom - work.top)


def resize_hit_test(x: int, y: int, bounds, edge: int, corner: int) -> int | None:
    """Native non-client edges, using physical pixels and signed screen positions."""
    if not bounds.left <= x < bounds.right or not bounds.top <= y < bounds.bottom:
        return None
    left, right = x - bounds.left, bounds.right - 1 - x
    top, bottom = y - bounds.top, bounds.bottom - 1 - y
    if top < corner and left < corner:
        return 13  # HTTOPLEFT
    if top < corner and right < corner:
        return 14  # HTTOPRIGHT
    if bottom < corner and left < corner:
        return 16  # HTBOTTOMLEFT
    if bottom < corner and right < corner:
        return 17  # HTBOTTOMRIGHT
    if left < edge:
        return 10  # HTLEFT
    if right < edge:
        return 11  # HTRIGHT
    if top < edge:
        return 12  # HTTOP
    if bottom < edge:
        return 15  # HTBOTTOM
    return None


class WindowsFrame:
    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.user.MonitorFromWindow.restype = wintypes.HANDLE
        self.user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.IsZoomed.argtypes = [wintypes.HWND]
        self.user.GetDpiForWindow.argtypes = [wintypes.HWND]
        self.user.GetDpiForWindow.restype = wintypes.UINT
        self.comctl = ctypes.WinDLL("comctl32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
        self.comctl.SetWindowSubclass.argtypes = [wintypes.HWND, callback_type, ctypes.c_size_t, ctypes.c_size_t]
        self.comctl.RemoveWindowSubclass.argtypes = [wintypes.HWND, callback_type, ctypes.c_size_t]
        self.comctl.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.comctl.DefSubclassProc.restype = ctypes.c_ssize_t
        # Retain the callback until WM_NCDESTROY; installation happens on the
        # owning UI thread in before_show, never on a pywebview bridge thread.
        self.callback = callback_type(self._procedure)
        if not self.comctl.SetWindowSubclass(hwnd, self.callback, 1, 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def monitor_info(self) -> MonitorInfo:
        monitor = self.user.MonitorFromWindow(self.hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
        if not self.user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return info

    def _procedure(self, hwnd, message, wparam, lparam, subclass_id, reference):
        if message == 0x0084 and not self.user.IsZoomed(hwnd):  # WM_NCHITTEST
            bounds = wintypes.RECT()
            if self.user.GetWindowRect(hwnd, ctypes.byref(bounds)):
                dpi = self.user.GetDpiForWindow(hwnd) or 96
                hit = resize_hit_test(ctypes.c_short(lparam & 0xffff).value,
                                      ctypes.c_short((lparam >> 16) & 0xffff).value,
                                      bounds, max(7, round(7 * dpi / 96)), max(12, round(12 * dpi / 96)))
                if hit is not None:
                    return hit
        if message == 0x0082:  # WM_NCDESTROY
            self.comctl.RemoveWindowSubclass(hwnd, self.callback, subclass_id)
        result = self.comctl.DefSubclassProc(hwnd, message, wparam, lparam)
        if message == 0x0024 and lparam:  # WM_GETMINMAXINFO
            try:
                info = self.monitor_info()
                left, top, width, height = work_area_bounds(info.rcMonitor, info.rcWork)
                limits = MinMaxInfo.from_address(lparam)
                limits.ptMaxPosition.x, limits.ptMaxPosition.y = left, top
                limits.ptMaxSize.x, limits.ptMaxSize.y = width, height
            except Exception as exc:
                print(f"[desktop] could not constrain maximized bounds: {exc}")
        return result


class NativeResizeBorders:
    """Narrow native hit targets above WebView and its non-DOM scrollbars."""

    def __init__(self, form, resize, user):
        from System.Drawing import Point, Size
        import System.Windows.Forms as Forms
        self.form, self.user = form, user
        self.Point, self.Size, self.Forms = Point, Size, Forms
        self.panels = {}
        self.theme = "light"
        cursors = {"n":Forms.Cursors.SizeNS,"s":Forms.Cursors.SizeNS,
                   "w":Forms.Cursors.SizeWE,"e":Forms.Cursors.SizeWE,
                   "nw":Forms.Cursors.SizeNWSE,"se":Forms.Cursors.SizeNWSE,
                   "ne":Forms.Cursors.SizeNESW,"sw":Forms.Cursors.SizeNESW}
        for edge, cursor in cursors.items():
            panel = Forms.Panel()
            panel.Name = "WorkbenchResize_" + edge
            panel.Cursor, panel.TabStop = cursor, False
            panel.Margin = Forms.Padding(0)
            panel.Padding = Forms.Padding(0)
            def down(_sender, event, edge=edge):
                if event.Button == Forms.MouseButtons.Left:
                    resize(edge, mouse=True)
            panel.MouseDown += down
            form.Controls.Add(panel)
            self.panels[edge] = panel
        self._layout_handler = lambda *_: self.layout()
        form.Resize += self._layout_handler
        self.set_theme("light")
        self.layout()

    def set_theme(self, theme):
        if self.form.IsDisposed:
            return
        self.theme = theme
        def update():
            if self.form.IsDisposed:
                return
            from System.Drawing import ColorTranslator
            palette = ("#222a39", "#162030", "#101827") if theme == "dark" else ("#f5f8fe", "#f2f5fa", "#f7f9fc")
            for edge, panel in self.panels.items():
                panel.BackColor = ColorTranslator.FromHtml(palette[0] if "n" in edge else palette[1] if edge == "w" else palette[2])
        if self.form.InvokeRequired:
            from System import Action
            self.form.BeginInvoke(Action(update))
        else:
            update()

    def layout(self):
        if self.form.IsDisposed:
            return
        normal = self.form.WindowState == self.Forms.FormWindowState.Normal
        hwnd = int(self.form.Handle.ToInt64())
        scale = (self.user.GetDpiForWindow(hwnd) or 96) / 96
        edge, corner = max(7, round(7 * scale)), max(12, round(12 * scale))
        inset = edge if normal else 0
        if self.form.Padding.All != inset:
            self.form.Padding = self.Forms.Padding(inset)
        w, h = self.form.ClientSize.Width, self.form.ClientSize.Height
        bounds = {"n":(corner,0,w-2*corner,edge),"s":(corner,h-edge,w-2*corner,edge),
                  "w":(0,corner,edge,h-2*corner),"e":(w-edge,corner,edge,h-2*corner),
                  "nw":(0,0,corner,corner),"ne":(w-corner,0,corner,corner),
                  "sw":(0,h-corner,corner,corner),"se":(w-corner,h-corner,corner,corner)}
        for key, (x,y,width,height) in bounds.items():
            panel = self.panels[key]
            panel.Location, panel.Size = self.Point(x,y), self.Size(max(0,width),max(0,height))
            panel.Visible = normal
            if normal:
                panel.BringToFront()
