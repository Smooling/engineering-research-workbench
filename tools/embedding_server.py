# -*- coding: utf-8 -*-
"""本地 OpenAI 兼容 Embedding 服务（RAG 用）。

用途：给工作台的「设置 → RAG」提供一个本地 `/v1/embeddings` 接口，无需外部 API。

模型：`BAAI/bge-small-zh-v1.5`（fastembed 的 ONNX 版，512 维，中文优化）。
- 体积小（约 100 MB）、CPU 推理即可（本地知识库规模下建索引几十秒）；
- 不依赖 torch；显卡可用但不是必须（RTX 4060 上同样可以直接跑本服务，只是走 CPU）。

启动：
    python tools/embedding_server.py --port 8800

接口（与 OpenAI Embeddings 对齐，工作台只用到这些）：
    GET  /health            → {"ok": true, "model": ..., "dimensions": ...}
    GET  /v1/models         → {"data": [{"id": model, ...}]}
    POST /v1/embeddings     → {"data": [{"index": i, "embedding": [...]}], "model": ..., "usage": {...}}
        body: {"model": "...", "input": "文本" | ["a", "b"], "encoding_format": "float"}

缓存：模型落在 `D:/Project/.models/fastembed`（可用 --cache-dir 覆盖），不随临时目录清理。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_CACHE = Path("D:/Project/.models/fastembed")
MODEL = None
MODEL_LOCK = threading.Lock()
DIM = 512


def load_model(model_name: str, cache_dir: Path):
    """懒加载：首次请求时初始化，避免启动阶段卡住。"""
    global MODEL, DIM
    with MODEL_LOCK:
        if MODEL is None:
            from fastembed import TextEmbedding

            cache_dir.mkdir(parents=True, exist_ok=True)
            MODEL = TextEmbedding(model_name, cache_dir=str(cache_dir))
            probe = next(iter(MODEL.embed(["维度探测"])))
            DIM = int(len(probe))
    return MODEL


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = load_model(os.environ.get("ERW_EMBED_MODEL", DEFAULT_MODEL), CACHE_DIR)
    vectors = list(model.embed(texts))
    return [[float(x) for x in vec] for vec in vectors]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # 安静：只记录错误
        if str(fmt).startswith(("POST", "GET")) and " 200 " not in str(fmt):
            sys.stderr.write("[embedding] " + (fmt % args) + "\n")

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/health", "/v1/health"):
            return self._send(200, {"ok": True, "model": MODEL_NAME, "dimensions": DIM, "cache": str(CACHE_DIR)})
        if path == "/v1/models":
            return self._send(200, {"object": "list", "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "local"}]})
        return self._send(404, {"error": {"message": "not found", "type": "invalid_request_error"}})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/v1/embeddings":
            return self._send(404, {"error": {"message": "not found", "type": "invalid_request_error"}})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 16 * 1024 * 1024:
                raise ValueError("请求体为空或过大")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            raw = payload.get("input")
            texts = [raw] if isinstance(raw, str) else raw
            if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
                raise ValueError("input 须为字符串或字符串数组")
            texts = [t[:8000] for t in texts]
            started = time.time()
            vectors = embed_texts(texts)
            self._send(200, {
                "object": "list",
                "model": payload.get("model") or MODEL_NAME,
                "data": [{"object": "embedding", "index": i, "embedding": vec} for i, vec in enumerate(vectors)],
                "usage": {"prompt_tokens": sum(len(t) for t in texts), "total_tokens": sum(len(t) for t in texts)},
                "elapsed_ms": int((time.time() - started) * 1000),
            })
        except Exception as exc:  # noqa: BLE001 - 对客户端统一报 400/500
            self._send(400, {"error": {"message": str(exc), "type": "invalid_request_error"}})


MODEL_NAME = os.environ.get("ERW_EMBED_MODEL", DEFAULT_MODEL)
CACHE_DIR = Path(os.environ.get("ERW_EMBED_CACHE", str(DEFAULT_CACHE)))


def main(argv: list[str] | None = None) -> int:
    global MODEL_NAME, CACHE_DIR
    parser = argparse.ArgumentParser(description="本地 OpenAI 兼容 Embedding 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--cache-dir", default=str(CACHE_DIR))
    args = parser.parse_args(argv)
    MODEL_NAME = args.model
    CACHE_DIR = Path(args.cache_dir)
    load_model(MODEL_NAME, CACHE_DIR)  # 启动即加载，首请求不等待
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Embedding 服务已就绪：http://{args.host}:{args.port}/v1  ·  模型 {MODEL_NAME} · {DIM} 维", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
