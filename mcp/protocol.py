"""MCP 协议层 —— stdio 上的 JSON-RPC 2.0 传输与 schema 构建助手。

零第三方依赖：官方 ``mcp`` SDK 未安装，这里按 Model Context Protocol 规范
自行实现 stdio 传输（换行分隔的 JSON-RPC 消息，同时兼容 LSP 风格的
``Content-Length`` 分帧），因此本服务器可直接用系统 Python 启动。
"""

from __future__ import annotations

import json
import os
from typing import Any, BinaryIO

JSONRPC_VERSION = "2.0"

SUPPORTED_PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

MAX_MESSAGE_BYTES = 32 * 1024 * 1024


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            out["data"] = self.data
        return out


# ------------------------------------------------------------------ 传输层

class StdioTransport:
    """按 MCP stdio 规范收发消息（每条消息一行 JSON）。"""

    def __init__(self, stdin: BinaryIO, stdout: BinaryIO) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self._buf = b""

    # -- 读 --
    def _fill(self, n: int) -> None:
        """尽量多读：``BufferedReader.read(n)`` 会阻塞到读满 n 字节，
        因此优先使用 ``read1``（有数据即返回），否则退回 ``os.read``。"""
        read1 = getattr(self.stdin, "read1", None)
        if callable(read1):
            chunk = read1(max(1, n))
        else:
            chunk = os.read(self.stdin.fileno(), max(1, n))
        if not chunk:
            raise EOFError
        self._buf += chunk

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            self._fill(n - len(self._buf))
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def _read_line(self) -> bytes | None:
        while b"\n" not in self._buf:
            try:
                self._fill(65536)
            except EOFError:
                if self._buf:
                    line, self._buf = self._buf, b""
                    return line
                return None
        line, self._buf = self._buf.split(b"\n", 1)
        return line.rstrip(b"\r")

    def read(self) -> dict[str, Any] | None:
        """读取一条消息；EOF 返回 None。"""
        while True:
            line = self._read_line()
            if line is None:
                return None
            if not line.strip():
                continue
            if line.lower().startswith(b"content-length:"):
                payload = self._read_framed(line)
            else:
                payload = line
            try:
                msg = json.loads(payload.decode("utf-8"))
            except Exception as exc:
                raise RpcError(PARSE_ERROR, f"消息不是合法 JSON: {exc}") from exc
            if not isinstance(msg, dict):
                raise RpcError(INVALID_REQUEST, "消息必须是 JSON 对象")
            return msg

    def _read_framed(self, first_header: bytes) -> bytes:
        length = 0
        header = first_header
        while True:
            try:
                key, _, value = header.decode("ascii", "replace").partition(":")
                if key.strip().lower() == "content-length":
                    length = int(value.strip())
            except Exception as exc:
                raise RpcError(PARSE_ERROR, f"非法 Content-Length 头: {exc}") from exc
            if length <= 0 or length > MAX_MESSAGE_BYTES:
                raise RpcError(PARSE_ERROR, f"非法消息长度: {length}")
            nxt = self._read_line()
            if nxt is None:
                raise RpcError(PARSE_ERROR, "分帧头未结束")
            if not nxt.strip():
                break
            header = nxt
        return self._read_exact(length)

    # -- 写 --
    def write(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.stdout.write(data + b"\n")
        self.stdout.flush()


# ------------------------------------------------------------------ schema 助手

def s(desc: str, *, default: Any = None, enum: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "string", "description": desc}
    if enum:
        out["enum"] = enum
    if default is not None:
        out["default"] = default
    return out


def i(desc: str, *, default: int | None = None, minimum: int | None = None, maximum: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "integer", "description": desc}
    if default is not None:
        out["default"] = default
    if minimum is not None:
        out["minimum"] = minimum
    if maximum is not None:
        out["maximum"] = maximum
    return out


def b(desc: str, *, default: bool = False) -> dict[str, Any]:
    return {"type": "boolean", "description": desc, "default": default}


def arr(desc: str, *, items: str = "string") -> dict[str, Any]:
    return {"type": "array", "description": desc, "items": {"type": items}}


def tool(
    name: str,
    title: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    *,
    read_only: bool = False,
    destructive: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
        "annotations": {
            "title": title,
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
            "idempotentHint": read_only,
            "openWorldHint": False,
        },
    }


# ------------------------------------------------------------------ 结果封装

def as_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def ok(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": as_text(payload)}]}


def fail(message: str, hint: str = "") -> dict[str, Any]:
    text = f"[错误] {message}"
    if hint:
        text += f"\n[建议] {hint}"
    return {"content": [{"type": "text", "text": text}], "isError": True}


def resource(uri: str, name: str, title: str, description: str, mime: str = "text/markdown") -> dict[str, Any]:
    return {"uri": uri, "name": name, "title": title, "description": description, "mimeType": mime}
