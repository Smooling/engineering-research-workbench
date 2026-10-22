"""A persistent, non-activating reminder on the existing WinForms UI thread."""
from __future__ import annotations

import ctypes


class FocusReminder:
    def __init__(self, window, title, open_workbench):
        self.window = window
        self.title = title
        self.open_workbench = open_workbench
        self.theme = "light"
        self.form = None
        self.pending_count = 0
        self._closed = False

    def _dispatch(self, callback, *, wait=False):
        native = self.window.native
        if native is None or native.IsDisposed:
            return
        from System import Action
        def safely():
            try:
                callback()
            except Exception as exc:
                print(f"[desktop] persistent reminder failed: {exc}")
        if not native.InvokeRequired:
            safely()
        elif wait:
            native.Invoke(Action(safely))
        else:
            native.BeginInvoke(Action(safely))

    def notify(self, mode, message):
        def show():
            if self._closed:
                return
            self.pending_count += 1
            if self.form is None:
                self._create()
            self.heading.Text = f"{mode}计时完成"
            self.message.Text = message
            prefix = f"{self.pending_count} 条计时提醒 · " if self.pending_count > 1 else ""
            self.hint.Text = prefix + "提醒保留至手动关闭"
            self._paint_theme()
            self._position()
            self.form.Show(self.form.Location)
        self._dispatch(show)

    def set_theme(self, theme):
        self.theme = "dark" if theme == "dark" else "light"
        if self.form is not None:
            self._dispatch(lambda: self._paint_theme() if self.form is not None else None)

    def _create(self):
        from ctypes import wintypes
        import System.Windows.Forms as Forms
        from System.Drawing import Color, Font, FontStyle, GraphicsUnit, Point, Size
        self._color = Color.FromArgb
        native = self.window.native
        self._user = ctypes.WinDLL("user32", use_last_error=True)
        self._user.GetDpiForWindow.argtypes = [wintypes.HWND]
        self._user.GetDpiForWindow.restype = wintypes.UINT
        self._user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user.GetWindowLongW.restype = wintypes.LONG
        self._user.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        self.scale = max(1, self._user.GetDpiForWindow(int(native.Handle.ToInt64())) / 96)
        s = lambda value: round(value * self.scale)
        # ToolStripDropDown uses SW_SHOWNOACTIVATE. A regular Form.Show can
        # explicitly activate even when WS_EX_NOACTIVATE is already set.
        form = Forms.ToolStripDropDown()
        self.form = form
        form.Text = "科研工作台 · 计时提醒"
        form.AccessibleName = form.Text
        form.AutoClose = False
        form.AutoSize = False
        form.Padding = Forms.Padding(1)
        form.GripStyle = Forms.ToolStripGripStyle.Hidden
        form.CanOverflow = False
        form.ClientSize = Size(s(380), s(214))
        self.surface = Forms.Panel()
        self.surface.Size = Size(form.ClientSize.Width - 2, form.ClientSize.Height - 2)
        host = Forms.ToolStripControlHost(self.surface)
        host.AutoSize = False
        host.Size = self.surface.Size
        host.Margin = Forms.Padding(0)
        host.Padding = Forms.Padding(0)
        form.Items.Add(host)
        self._fonts = []
        self._dismiss_requested = False

        def font(size, bold=False):
            value = Font("Microsoft YaHei UI", float(s(size)), FontStyle.Bold if bold else FontStyle.Regular, GraphicsUnit.Pixel)
            self._fonts.append(value)
            return value

        def label(text, x, y, width, height, size=13, bold=False):
            control = Forms.Label()
            control.Text = text
            control.Location = Point(s(x), s(y))
            control.Size = Size(s(width), s(height))
            control.Font = font(size, bold)
            control.AutoEllipsis = True
            self.surface.Controls.Add(control)
            return control

        def button(text, x, y, width, height, action):
            control = Forms.Button()
            control.Text = text
            control.AccessibleName = text
            control.Location = Point(s(x), s(y))
            control.Size = Size(s(width), s(height))
            control.Font = font(13)
            control.FlatStyle = Forms.FlatStyle.Flat
            control.FlatAppearance.BorderSize = 1
            control.UseVisualStyleBackColor = False
            control.Click += lambda *_: action()
            self.surface.Controls.Add(control)
            return control

        self.brand = label(self.title, 18, 14, 300, 22, 12)
        self.heading = label("", 18, 44, 342, 30, 19, True)
        self.message = label("", 18, 84, 342, 42, 14)
        self.hint = label("", 18, 135, 342, 20, 11)
        self.close_button = button("×", 336, 8, 32, 30, self._dismiss)
        self.open_button = button("打开工作台", 18, 166, 166, 32, self._open)
        self.dismiss_button = button("知道了", 196, 166, 166, 32, self._dismiss)
        def closing(_sender, event):
            # Windows menu-mode cleanup can request CloseCalled even with
            # AutoClose=false. Only our explicit buttons or app exit may close it.
            event.Cancel = not self._dismiss_requested
        form.Closing += closing
        form.Closed += lambda *_: self._disposed(form)
        hwnd = int(form.Handle.ToInt64())
        style = self._user.GetWindowLongW(hwnd, -20)
        self._user.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x00000080)
        try:
            rounded = ctypes.c_int(2)
            dwm = ctypes.WinDLL("dwmapi")
            dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
            dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rounded), ctypes.sizeof(rounded))
        except OSError:
            pass

    def _paint_theme(self):
        color = self._color
        dark = self.theme == "dark"
        background = color(29, 42, 60) if dark else color(250, 251, 254)
        text = color(228, 236, 248) if dark else color(35, 49, 72)
        muted = color(174, 190, 212) if dark else color(83, 103, 132)
        border = color(75, 96, 125) if dark else color(196, 208, 227)
        button_background = color(37, 53, 76) if dark else color(235, 240, 249)
        self.form.BackColor = border
        self.surface.BackColor = background
        for control in (self.heading, self.message):
            control.BackColor, control.ForeColor = background, text
        for control in (self.brand, self.hint):
            control.BackColor, control.ForeColor = background, muted
        for control in (self.open_button, self.dismiss_button, self.close_button):
            control.BackColor, control.ForeColor = button_background, text
            control.FlatAppearance.BorderColor = border
        self.dismiss_button.BackColor = color(80, 100, 207)
        self.dismiss_button.ForeColor = color(255, 255, 255)
        self.dismiss_button.FlatAppearance.BorderColor = color(80, 100, 207)

    def _position(self):
        from System.Drawing import Point
        from System.Windows.Forms import Screen
        work = Screen.FromControl(self.window.native).WorkingArea
        margin = round(14 * self.scale)
        self.form.Location = Point(max(work.Left, work.Right - self.form.Width - margin),
                                   max(work.Top, work.Bottom - self.form.Height - margin))

    def _disposed(self, form):
        if self.form == form:
            self.form = None
            self.pending_count = 0
            fonts, self._fonts = self._fonts, []
            # Closed is raised before ToolStrip finishes its menu-mode cleanup.
            # Disposing within that event makes .NET access an already freed popup.
            self._queue_release(form, fonts)

    def _queue_release(self, form, fonts):
        from System import Action
        def release():
            try:
                if not form.IsDisposed:
                    form.Dispose()
                for font in fonts:
                    font.Dispose()
            except Exception as exc:
                print(f"[desktop] reminder cleanup failed: {exc}")
        self.window.native.BeginInvoke(Action(release))

    def _dismiss(self):
        if self.form is not None:
            self._dismiss_requested = True
            self.form.Close()

    def _open(self):
        self._dismiss()
        # pywebview operations may synchronously wait for its own UI thread.
        import threading
        threading.Thread(target=self.open_workbench, name="focus-reminder-open", daemon=True).start()

    def close(self):
        self._closed = True
        self._dispatch(self._dismiss, wait=True)
