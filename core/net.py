"""网络：代理可用性判定 + 「回环代理没起来就直连」的兜底。

**为什么需要它**：本机常见配置是系统代理指向 `127.0.0.1:7890`（Clash / V2Ray 之类）。
代理一旦没启动，注册表里的 `ProxyEnable=1` 仍然生效，于是 `urllib` / `requests`
（两者都会读注册表）把**所有**出网请求转发到这个死端口，统一得到
`WinError 10061 由于目标计算机积极拒绝，无法连接`——表现就是「资讯抓不到、天气不可用、
LLM 连不上」，而实际网络本身是通的。

判定是**保守**的，只在这三条同时成立时才认为代理不可用：
1. 配置的代理是**回环地址**（127.0.0.1 / localhost / ::1 / 0.0.0.0）；
2. 该端口**没人监听**（TCP 连接被拒，1/4 秒超时内）；
3. 调用方明确要求「代理不可用就直连」。
真正的远程代理（公司网关等）**永远不动**；超时、DNS 失败、非 2xx 一律照原样抛出，
绝不因为一次失败就悄悄换路径。
"""

from __future__ import annotations

import socket
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0", "[::1]"})
_PROBE_TIMEOUT = 0.25


def proxy_url_for(scheme: str = "https") -> str:
    """当前生效的代理（注册表 / 环境变量，urllib 的取法）。"""
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        return ""
    return str(proxies.get(scheme) or proxies.get("all") or "").strip()


def proxy_host_port(proxy: str) -> tuple[str, int]:
    """从 `http://user:pass@host:port` 里取出 (host, port)。"""
    if not proxy:
        return "", 0
    candidate = proxy if "://" in proxy else "http://" + proxy
    parts = urlsplit(candidate)
    host = (parts.hostname or "").strip().lower()
    try:
        port = int(parts.port or 0)
    except (TypeError, ValueError):
        port = 0
    return host, port


def proxy_is_dead_loopback(scheme: str = "https") -> bool:
    """系统代理是回环地址且端口没人监听 → True（代理没启动）。"""
    host, port = proxy_host_port(proxy_url_for(scheme))
    if host not in LOOPBACK_HOSTS or not port:
        return False
    target = "127.0.0.1" if host in {"0.0.0.0", "::1", "[::1]"} else host
    try:
        with socket.create_connection((target, port), timeout=_PROBE_TIMEOUT):
            return False   # 有人监听 → 代理可用，照常走代理
    except OSError:
        return True


def direct_preferred(scheme: str = "https") -> bool:
    """是否应走直连：没配代理，或配的是「没起来的回环代理」。"""
    if not proxy_url_for(scheme):
        return True
    return proxy_is_dead_loopback(scheme)


def _direct_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def open_url(url: str | Request, timeout: float = 8.0, headers: dict[str, Any] | None = None):
    """`urlopen` 的替代：代理是死回环时本次回退直连，其它异常照原样抛。

    返回响应对象（调用方自行 read/close）。
    """
    if isinstance(url, Request):
        req = url
        scheme = urlsplit(req.full_url).scheme
    else:
        req = Request(str(url), headers=dict(headers or {}))
        scheme = urlsplit(str(url)).scheme
    scheme = (scheme or "https").lower()
    if direct_preferred(scheme):
        opener = _direct_opener() if proxy_url_for(scheme) else urllib.request.build_opener()
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def read_url(url: str, timeout: float = 8.0, headers: dict[str, Any] | None = None, limit: int = 8 * 1024 * 1024) -> bytes:
    """取字节（限长），代理不可用则直连。"""
    with open_url(url, timeout=timeout, headers=headers) as resp:
        return resp.read(limit)


def data_root() -> Path:
    """可写数据根（开发态=仓库根；打包态=exe 同级）。`core_api.data_root()` 同源。"""
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]
