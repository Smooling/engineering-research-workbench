"""Windows tray compatibility for processes with restricted message permissions."""
import pystray
from pystray._util import win32


class WindowsTrayIcon(pystray.Icon):
    def _create_window(self, atom):
        hwnd = win32.CreateWindowEx(
            0, atom, None, win32.WS_POPUP, 0, 0, 0, 0,
            0, None, win32.GetModuleHandle(None), None)
        try:
            # Explorer restart notifications are optional; low-integrity Windows
            # processes cannot change this filter even for their own windows.
            win32.ChangeWindowMessageFilterEx(
                hwnd, win32.WM_TASKBARCREATED, win32.MSGFLT_ALLOW, None)
        except OSError as exc:
            if exc.winerror != 5:
                win32.DestroyWindow(hwnd)
                raise
            print("[desktop] tray message filter restricted; using default permissions")
        return hwnd
