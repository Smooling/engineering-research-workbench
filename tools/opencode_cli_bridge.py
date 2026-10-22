"""OpenCode CLI 桥：把 opencode 的免费档模型（如 deepseek-v4.1-flash-free）接进工作台 LLM。

为什么需要它
------------
`deepseek-v4.1-flash-free` 只出现在 Zen 通用网关（`https://opencode.ai/zen/v1`），且上游对免费档
做客户端识别：非 OpenCode 客户端直连一律 `403 FreeTierError`（实测系统提示词、UA、`Authorization: Bearer public`
都不是判别依据，请求里的 opencode 工具集才是）。因此工作台不直连，而是把请求交给本机官方 CLI
（`opencode run`），由 CLI 以自己的身份出网，再把结果包成 OpenAI Chat Completions 回给工作台。

运行
----
    python tools/opencode_cli_bridge.py            # 默认 127.0.0.1:9357
    python tools/opencode_cli_bridge.py --port 9357 --timeout 300

工作台侧档案：base_url = `http://127.0.0.1:9357/v1`，模型 `deepseek-v4.1-flash-free`。

能力边界（重要）
----------------
- 只有纯文本问答：`opencode run` 拿不到工作台的原生 function calling，工具循环会退化为普通回答。
- 每条消息只取文本（`text` 事件）；CLI 自己的思考/工具事件被丢弃。
- 请求携带的工具定义不会下发给 CLI，CLI 的工具一律**拒权**（见 `_ensure_deny_config`），
  并在独立临时目录里运行，避免模型在仓库里执行命令。
- 免费档限速很紧（实测多次 429）；429/403 原样转成 HTTP 错误，由工作台显示。

实现约束
--------
- 仅标准库；每次请求起一个 `opencode run` 子进程，`--format json` 逐行取结构化事件。
- 非流式与 SSE 两种响应都支持（工作台优先走 SSE）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_MODEL = "deepseek-v4.1-flash-free"
DEFAULT_PORT = 9357
MAX_PROMPT_CHARS = 24000  # 免费档上下文有限，超长历史按「保留最近若干条」截断

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DENY_CONFIG = CONFIG_DIR / "opencode-cli-bridge.json"

#: CLI 的工具全部拒权：免费档要求请求里带 opencode 工具集才放行，但执行必须关掉。
DENY_PERMISSIONS = {
    "$schema": "https://opencode.ai/config.json",
    "permission": {
        "bash": "deny",
        "edit": "deny",
        "write": "deny",
        "webfetch": "deny",
        "websearch": "deny",
    },
}


def _ensure_deny_config() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not DENY_CONFIG.exists():
        DENY_CONFIG.write_text(json.dumps(DENY_PERMISSIONS, ensure_ascii=False, indent=2), encoding="utf-8")
    return DENY_CONFIG


def _find_cli() -> list[str]:
    """定位 opencode 可执行文件，返回可直接交给 subprocess 的命令前缀。

    优先用 npm 包内的 `opencode.exe`：`.cmd` 需经 `cmd /c` 中转，中文提示词会被代码页破坏。
    """
    override = str(os.environ.get("OPENCODE_CLI") or "").strip()
    if override:
        return [override]
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe",
        Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "opencode-ai" / "node_modules"
        / "opencode-windows-x64" / "bin" / "opencode.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return [str(candidate)]
    for name in ("opencode.exe", "opencode"):
        found = shutil.which(name)
        if found:
            if found.lower().endswith((".cmd", ".bat")):
                return ["cmd", "/c", found]
            return [found]
    raise RuntimeError("找不到 opencode CLI：请先 `npm i -g opencode-ai`，或用 OPENCODE_CLI 指定 exe 路径")


def _flatten(messages: list[dict]) -> str:
    """OpenAI messages → 单段文本提示。system 置顶，其余按角色标注。"""
    system_parts: list[str] = []
    turns: list[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user")
        content = msg.get("content")
        if isinstance(content, list):
            content = "\n".join(
                str(x.get("text") or "") for x in content if isinstance(x, dict) and x.get("type") in ("text", "")
            )
        text = str(content or "").strip()
        if role == "system":
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            turns.append(f"[工具结果]\n{text}")
        elif text:
            turns.append(f"{'用户' if role == 'user' else '助手'}：{text}")
    prompt = "\n\n".join(filter(None, system_parts + turns))
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[-MAX_PROMPT_CHARS:]
    return prompt


def _run_cli(model: str, prompt: str, timeout: int) -> dict:
    """调用 `opencode run --format json`，聚合 assistant 文本与 token 用量。"""
    cmd = _find_cli()[:]
    cmd += ["run", "--format", "json", "-m", f"opencode/{model}", prompt]
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    env["OPENCODE_CONFIG"] = str(_ensure_deny_config())
    workdir = tempfile.mkdtemp(prefix="erw-opencode-")
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=workdir, env=env, capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"opencode CLI 超时（>{timeout}s）") from None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    stderr = proc.stderr.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"opencode CLI 退出码 {proc.returncode}：{stderr[-800:] or '无错误输出'}")

    texts: list[str] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "text":
            part = event.get("part") or {}
            if part.get("type") == "text" and str(part.get("text") or "").strip():
                texts.append(str(part["text"]))
        elif event.get("type") == "step_finish":
            tokens = (event.get("part") or {}).get("tokens") or {}
            usage["prompt_tokens"] += int(tokens.get("input") or 0)
            usage["completion_tokens"] += int(tokens.get("output") or 0)
    content = "\n".join(texts).strip()
    if not content:
        raise RuntimeError(f"opencode CLI 未返回文本：{stderr[-400:] or '（无输出）'}")
    usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return {"content": content, "usage": usage, "elapsed": round(time.time() - started, 2)}


def _chunks(text: str, size: int = 40) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


class BridgeServer(ThreadingHTTPServer):
    """工作台每次请求都新建短连接，客户端断开属常态——不要把这些异常打成 traceback。"""
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ERW-OpenCodeBridge/1.0"

    def log_message(self, fmt: str, *args) -> None:  # 静默：工作台侧已有会话日志
        pass

    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": {"type": "bridge_error", "message": message}})

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path.endswith("/models"):
            self._json(200, {"object": "list", "data": [{"id": DEFAULT_MODEL, "object": "model", "owned_by": "opencode-cli"}]})
        elif path.endswith("/health"):
            self._json(200, {"ok": True, "model": DEFAULT_MODEL})
        else:
            self._error(404, f"未实现的路径：{self.path}")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            self._error(400, "请求体不是合法 JSON")
            return
        model = str(payload.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        model = model.split("/")[-1]  # 容忍 opencode/xxx 写法
        prompt = _flatten(payload.get("messages") or [])
        if not prompt:
            self._error(400, "messages 为空")
            return
        try:
            result = _run_cli(model, prompt, self.server.cli_timeout)  # type: ignore[attr-defined]
        except TimeoutError as exc:
            self._error(504, str(exc))
            return
        except RuntimeError as exc:
            message = str(exc)
            # 免费档限速/客户端限制：保留原文供工作台显示
            status = 429 if "429" in message else 502
            self._error(status, message)
            return

        completion_id = "chatcmpl-" + uuid.uuid4().hex[:24]
        created = int(time.time())
        if not payload.get("stream"):
            self._json(200, {
                "id": completion_id, "object": "chat.completion", "created": created, "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": result["content"]},
                             "finish_reason": "stop"}],
                "usage": result["usage"],
            })
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def emit(data: dict) -> None:
            frame = f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
            self.wfile.write(f"{len(frame):X}\r\n".encode() + frame + b"\r\n")
            self.wfile.flush()

        for piece in _chunks(result["content"]):
            emit({"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model,
                  "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]})
        emit({"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model,
              "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": result["usage"]})
        done = b"data: [DONE]\n\n"
        self.wfile.write(f"{len(done):X}\r\n".encode() + done + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        self.close_connection = True


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenCode CLI → OpenAI Chat Completions 桥")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=int, default=300, help="单次 CLI 调用超时（秒）")
    args = parser.parse_args()

    try:
        cli = _find_cli()
    except RuntimeError as exc:
        print(f"[bridge] {exc}", file=sys.stderr)
        return 2
    _ensure_deny_config()
    server = BridgeServer((args.host, args.port), Handler)
    server.cli_timeout = max(30, int(args.timeout))  # type: ignore[attr-defined]
    print(f"[bridge] {args.host}:{args.port}  model={DEFAULT_MODEL}  cli={' '.join(cli)}", flush=True)
    print(f"[bridge] 工作台档案 base_url = http://{args.host}:{args.port}/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
