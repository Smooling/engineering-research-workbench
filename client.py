"""v260923 · 桌面客户端入口：后台线程跑 HTTP 服务，pywebview（Edge WebView2）承载前端窗口。

用法：
- 开发调试：python client.py
- 打包产物：PyInstaller onefile exe（build_client.bat）
  v260923w · exe 生成在项目根目录（--distpath .），frozen 时 DATA_ROOT=exe 所在目录，
  即直接使用根目录的 config/ 与 Workspace/，与开发环境共用同一份数据，不再产生独立副本。
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from app.paths import DATA_ROOT, FROZEN

# v260923x · 窗口状态记忆文件：记住上次关闭时的尺寸与最大化状态，下次启动原样恢复
_WINDOW_STATE_FILE = DATA_ROOT / "window-state.json"


def _setup_logging():
    """windowed exe 无控制台，把输出落到 exe 同级 workbench.log 便于排查。"""
    if not FROZEN:
        return
    try:
        log_path = DATA_ROOT / "workbench.log"
        # 覆盖式写入，避免便携目录下日志无限增长
        stream = open(log_path, "w", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
    except OSError:
        pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_ready(url: str, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1.5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def _clamped_window_size(preferred_w: int = 1440, preferred_h: int = 900) -> tuple[int, int]:
    """v260923v · 按屏幕工作区预收缩窗口尺寸。小屏上若按原始尺寸建窗，
    Windows 会先显示大窗再压回屏幕，产生用户可见的「拉伸」闪动。
    v260923x · 接受任意期望尺寸（含窗口状态记忆的恢复值），统一向工作区收缩。"""
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        # SPI_GETWORKAREA：任务栏以外的可用区域，返回值与窗口逻辑坐标一致
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            preferred_w = min(preferred_w, rect.right - rect.left)
            preferred_h = min(preferred_h, rect.bottom - rect.top)
    except Exception:
        pass
    return preferred_w, preferred_h


def _load_window_state() -> dict:
    """v260923x · 读取上次关闭时的窗口状态。尺寸需通过合理性校验才采信。
    v260923y · 用 utf-8-sig 读以免疫 BOM（外部工具写的带 BOM 文件不再静默失效），
    解析失败时打印原始字节前 16 位，便于从 workbench.log 直接定位坏文件。"""
    fallback = {"maximized": False, "width": 0, "height": 0}
    raw = b""
    try:
        raw = _WINDOW_STATE_FILE.read_bytes()
        data = json.loads(raw.decode("utf-8-sig"))
        w, h = int(data.get("width") or 0), int(data.get("height") or 0)
        if 400 <= w <= 8000 and 300 <= h <= 4000:
            return {"maximized": bool(data.get("maximized")), "width": w, "height": h}
        print(f"[client] window state ignored (size out of range): {raw[:64]!r}")
    except Exception as e:
        print(f"[client] window state unreadable ({e}): bytes={raw[:16]!r}")
    return fallback


def _save_window_state(state: dict) -> None:
    try:
        _WINDOW_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[client] {time.strftime('%H:%M:%S')} window state saved: {state}")
    except OSError as e:
        print(f"[client] window state save failed: {e}")


def _run_window(url: str, cfg, httpd=None):
    """打开桌面窗口。httpd 为 None 表示连接到已有实例（次生窗口），退出时不触碰对方服务。"""
    try:
        import webview
    except ImportError:
        print("pywebview 未安装：pip install pywebview", file=sys.stderr)
        if httpd is not None:
            httpd.shutdown()
        sys.exit(1)

    title = str(cfg.get("app_name") or "科研工作台")
    # v260923x · 恢复上次窗口状态：有有效记忆则用记忆尺寸，否则默认 1440x900；均向工作区收缩
    saved = _load_window_state()
    print(f"[client] {time.strftime('%H:%M:%S')} window state restored: {saved}")
    pref_w = saved["width"] or 1440
    pref_h = saved["height"] or 900
    win_w, win_h = _clamped_window_size(pref_w, pref_h)
    # v260923v · 尺寸与 min_size 都按工作区收缩，min_size 超过实际窗口会触发二次调整（同样可见）
    window = webview.create_window(
        title, url, width=win_w, height=win_h,
        min_size=(min(1080, win_w), min(720, win_h)),
        maximized=saved["maximized"],
    )

    # v260923x · 运行期采集窗口状态：maximized/restored 维护标志，resized 仅在非最大化时记录
    # 尺寸（事件按 maximized/restored → resized 顺序触发，标志总是先就位）。pywebview 的
    # events.resized 回传逻辑像素，与 create_window 同单位，可直接存档复用。
    # v260923y · live 尺寸用 saved 值兜底：最大化恢复打开的窗口从未处于非最大化，
    # resized 不会记录尺寸，若无兜底则退出时 live["width"]=0 导致状态漏存。
    live = {"maximized": saved["maximized"], "width": saved["width"], "height": saved["height"]}

    def _on_maximized():
        live["maximized"] = True

    def _on_restored():
        live["maximized"] = False

    def _on_resized(w, h):
        if not live["maximized"] and w and h:
            live["width"], live["height"] = int(w), int(h)

    window.events.maximized += _on_maximized
    window.events.restored += _on_restored
    window.events.resized += _on_resized

    # storage_path 指向 exe 同级，保证 localStorage（自定义标记、侧栏状态等）便携持久化
    webview.start(storage_path=str(DATA_ROOT / ".webview-profile"))

    # v260923x · 窗口关闭后落盘窗口状态，供下次启动恢复
    if live["width"] > 0:
        _save_window_state(live)

    if httpd is None:
        return
    httpd.shutdown()
    httpd.server_close()

    # 设置页触发「快速重启」时：拉起新进程接管，当前进程退出（此时端口已释放，新进程可直接绑定）
    if getattr(httpd, "restart_requested", False):
        print("Restarting client...")
        subprocess.Popen([sys.executable])
        sys.exit(0)


def main():
    _setup_logging()
    t0 = time.time()
    now = lambda: time.strftime("%H:%M:%S")

    import server

    # v260923v · 端口被占时先探测是否为另一个健康的工作台实例：是则开一个次生窗口（单服务多窗口），
    # 避免回退随机端口造成双服务并存；探测失败（陌生进程占用）才回退空闲端口。
    try:
        httpd, cfg, url = server.build_server(auto_open_browser=False)
    except OSError as first_err:
        print(f"[client] {now()} bind failed ({first_err}), probing existing instance...")
        from app import config as _config
        _cfg = _config.get_app()
        _host = str(_cfg.get("host") or "127.0.0.1")
        _port = int(_cfg.get("port") or 8765)
        _url = f"http://{_host}:{_port}"
        if _wait_ready(_url, timeout=2.0):
            print(f"[client] {now()} existing workbench at {_url} is healthy, opening a secondary window.")
            _run_window(_url, _cfg)
            return
        print(f"[client] {now()} no healthy instance detected, falling back to a free port.")
        httpd, cfg, url = server.build_server(port_override=_free_port(), auto_open_browser=False)

    # v260923v · 服务线程兜底：异常打印完整堆栈到 workbench.log，避免线程静默死亡无从排查
    def _serve():
        try:
            httpd.serve_forever(poll_interval=0.25)
        except Exception:
            import traceback
            traceback.print_exc()

    serve_thread = threading.Thread(target=_serve, daemon=True)
    serve_thread.start()
    print(f"[client] {now()} serve thread started (+{time.time() - t0:.1f}s)")

    if not _wait_ready(url):
        print(f"Server failed to become ready at {url}", file=sys.stderr)
        httpd.shutdown()
        sys.exit(1)

    print(f"[client] {now()} server ready (+{time.time() - t0:.1f}s) at {url}")
    _run_window(url, cfg, httpd=httpd)


if __name__ == "__main__":
    main()
