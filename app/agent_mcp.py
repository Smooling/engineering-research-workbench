"""Explicitly configured Streamable HTTP MCP clients (JSON or SSE responses)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

_LOCK = threading.RLock()
_SESSIONS: dict[str, str] = {}
_CATALOG: dict[str, tuple[dict, dict]] = {}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("MCP 不跟随重定向，请配置最终服务地址")


def validate_servers(items) -> list[dict]:
    if not isinstance(items, list) or len(items) > 12:
        raise ValueError("MCP 服务配置须为至多 12 项的数组")
    out, names = [], set()
    for item in items:
        name = str(item.get("name") or "")
        url = str(item.get("url") or "")
        parsed = urlparse(url)
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,30}", name) or name in names:
            raise ValueError("MCP 名称须唯一，使用小写字母、数字、下划线或连字符")
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("MCP 地址须为 HTTP(S)，凭证请使用 headers_env")
        env = item.get("headers_env") or {}
        if not isinstance(env, dict) or any(not re.fullmatch(r"[A-Za-z0-9_-]+", str(k)) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(v)) for k, v in env.items()):
            raise ValueError("headers_env 须映射请求头名称到环境变量名称")
        tools = item.get("tools") or []
        if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
            raise ValueError("MCP tools 必须为工具名称数组")
        out.append({"name": name, "url": url, "enabled": item.get("enabled") is True, "headers_env": env, "tools": tools, "read_only_tools": [str(t) for t in item.get("read_only_tools") or []]})
        names.add(name)
    with _LOCK:
        _CATALOG.clear()
        _SESSIONS.clear()
    return out


def _rpc(server: dict, method: str, params=None, *, notification=False, _retried=False):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26"}
    for key, env in server.get("headers_env", {}).items():
        value = os.environ.get(env, "")
        if value and "\r" not in value and "\n" not in value:
            headers[key] = value
    session_key = server["url"] + json.dumps(server.get("headers_env", {}), sort_keys=True)
    if method == "initialize":
        _SESSIONS.pop(session_key, None)
    if session_key in _SESSIONS:
        headers["Mcp-Session-Id"] = _SESSIONS[session_key]
    payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if not notification:
        payload["id"] = hashlib.sha256((method + json.dumps(params)).encode()).hexdigest()[:16]
    request = Request(server["url"], data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        response = build_opener(_NoRedirect()).open(request, timeout=30)
    except HTTPError as exc:
        if exc.code == 404 and session_key in _SESSIONS and not _retried and method != "initialize":
            _SESSIONS.pop(session_key, None)
            _rpc(server, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "research-workbench", "version": "1"}})
            _rpc(server, "notifications/initialized", notification=True)
            return _rpc(server, method, params, notification=notification, _retried=True)
        raise
    with response:
        if response.headers.get("Mcp-Session-Id"):
            _SESSIONS[session_key] = response.headers["Mcp-Session-Id"]
        if notification:
            return {}
        if "text/event-stream" in response.headers.get("Content-Type", ""):
            size, started, parts = 0, time.monotonic(), []
            for line in response:
                size += len(line)
                if size > 2 * 1024 * 1024:
                    raise ValueError("MCP 响应过大")
                if time.monotonic() - started > 30:
                    raise ValueError("MCP 流式响应超时")
                if line.startswith(b"data:"):
                    parts.append(line[5:].lstrip().rstrip(b"\r\n"))
                elif not line.strip() and parts:
                    data = json.loads(b"\n".join(parts))
                    parts = []
                    if isinstance(data, dict) and data.get("id") == payload["id"]:
                        break
            else:
                raise ValueError("MCP 未返回匹配结果")
        else:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("MCP 响应过大")
            data = json.loads(raw)
    if not isinstance(data, dict) or data.get("id") != payload["id"]:
        raise ValueError("MCP 返回了不匹配的响应 id")
    if data.get("error"):
        raise ValueError("MCP: " + str(data["error"].get("message")))
    return data.get("result") or {}


def discover() -> dict:
    from .agent_runtime import settings
    specs, errors, catalog = [], [], {}
    for server in settings()["mcp_servers"]:
        if not server.get("enabled"):
            continue
        try:
            _rpc(server, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "research-workbench", "version": "1"}})
            _rpc(server, "notifications/initialized", notification=True)
            result = _rpc(server, "tools/list")
            for item in result.get("tools", [])[:80]:
                if item["name"] not in server.get("tools", []):
                    continue  # An explicit allowlist prevents silently adding capabilities.
                name = "mcp_" + server["name"] + "_" + hashlib.sha256(item["name"].encode()).hexdigest()[:16]
                catalog[name] = (server, item)
                specs.append({"type": "function", "function": {"name": name, "description": f"[{server['name']}/{item['name']}] " + str(item.get("description") or "")[:2000], "parameters": item.get("inputSchema") or {"type": "object", "properties": {}}}})
        except Exception as exc:
            errors.append({"server": server["name"], "error": str(exc)})
    with _LOCK:
        _CATALOG.clear()
        _CATALOG.update(catalog)
    return {"tools": specs, "errors": errors}


def specs() -> list[dict]:
    from .agent_runtime import settings
    configured = settings()["mcp_servers"]
    with _LOCK:
        return [{"type": "function", "function": {"name": name, "description": f"[{server['name']}] {item.get('description', '')}", "parameters": item.get("inputSchema") or {"type": "object", "properties": {}}}} for name, (server, item) in _CATALOG.items() if server in configured and server.get("enabled") and item["name"] in server.get("tools", [])]


def is_write(name: str) -> bool:
    with _LOCK:
        server, item = _CATALOG[name]
    return item["name"] not in server.get("read_only_tools", [])


def execute(name: str, args: dict) -> dict:
    from .agent_runtime import settings
    with _LOCK:
        if name not in _CATALOG:
            raise ValueError("MCP 工具未加载，请在设置中刷新连接")
        server, item = _CATALOG[name]
    if server not in settings()["mcp_servers"] or not server.get("enabled") or item["name"] not in server.get("tools", []):
        raise ValueError("MCP 服务或工具已被禁用，请刷新连接")
    result = _rpc(server, "tools/call", {"name": item["name"], "arguments": args})
    return {"ok": not result.get("isError", False), "content": result.get("content") or [], "structured": result.get("structuredContent")}
