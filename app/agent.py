from __future__ import annotations

import base64
import http.client
import json
import mimetypes
import os
import re
import shutil
import threading
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import config, store, activity, agent_tools, billing
from .workspace import ensure_workspace

_LOCK = threading.RLock()
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_MAX_CONTEXT_CHARS = 60_000
_MAX_DOC_CHARS = 18_000
_MAX_HISTORY_MESSAGES = 30


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _root() -> Path:
    root = ensure_workspace() / "System" / "AgentChats"
    (root / "Attachments").mkdir(parents=True, exist_ok=True)
    (root / "Trash").mkdir(parents=True, exist_ok=True)
    return root


def _atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _session_path(session_id: str) -> Path:
    if not re.fullmatch(r"chat-[a-zA-Z0-9_-]{6,80}", session_id or ""):
        raise ValueError("Invalid session id")
    return _root() / f"{session_id}.json"


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def list_sessions() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with _LOCK:
        for path in _root().glob("chat-*.json"):
            data = _load(path)
            if not data:
                continue
            messages = data.get("messages") if isinstance(data.get("messages"), list) else []
            last = messages[-1].get("content", "") if messages else ""
            out.append({
                "id": data.get("id") or path.stem,
                "title": data.get("title") or "新对话",
                "created": data.get("created") or "",
                "updated": data.get("updated") or "",
                "message_count": len(messages),
                "preview": str(last)[:160],
                "archived": bool(data.get("archived")),  # v260930n · 归档标记：前端按活跃/已归档分组展示
            })
    out.sort(key=lambda x: x.get("updated") or x.get("created") or "", reverse=True)
    return out


def get_session(session_id: str) -> dict[str, Any]:
    path = _session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(session_id)
    data = _load(path)
    if not data:
        raise FileNotFoundError(session_id)
    return data


def create_session(title: str = "") -> dict[str, Any]:
    now = _now()
    session_id = "chat-" + uuid.uuid4().hex[:12]
    data = {"id": session_id, "title": (title or "新对话").strip()[:120], "created": now, "updated": now, "messages": []}
    with _LOCK:
        _atomic_json(_session_path(session_id), data)
    return data


def rename_session(session_id: str, title: str) -> dict[str, Any]:
    with _LOCK:
        data = get_session(session_id)
        data["title"] = (title or "新对话").strip()[:120]
        data["updated"] = _now()
        _atomic_json(_session_path(session_id), data)
        return data


def archive_session(session_id: str, flag: bool) -> dict[str, Any]:  # v260930n · 归档/取消归档：只改 archived 标记，不动 updated（列表仍按最近更新排序）
    with _LOCK:
        data = get_session(session_id)
        data["archived"] = bool(flag)
        _atomic_json(_session_path(session_id), data)
        return data


def delete_session(session_id: str) -> dict[str, Any]:
    path = _session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(session_id)
    trash = _root() / "Trash" / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{path.name}"
    with _LOCK:
        shutil.move(str(path), str(trash))
    return {"ok": True}


def save_image(data_url: str, original_name: str = "image.png") -> dict[str, Any]:
    m = re.match(r"^data:(image/(?:png|jpeg|webp|gif));base64,(.+)$", data_url or "", flags=re.S | re.I)
    if not m:
        raise ValueError("仅支持 PNG / JPEG / WebP / GIF 图片")
    mime, raw = m.groups()
    blob = base64.b64decode(raw, validate=True)
    if len(blob) > _MAX_IMAGE_BYTES:
        raise ValueError("单张图片不能超过 12 MB")
    signatures = {
        "image/png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
        "image/webp": lambda b: len(b) > 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP",
        "image/gif": lambda b: b.startswith((b"GIF87a", b"GIF89a")),
    }
    mime = mime.lower()
    if not signatures[mime](blob):
        raise ValueError("图片内容与 MIME 不匹配")
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}[mime]
    date_dir = datetime.now().strftime("%Y/%m")
    root = _root() / "Attachments" / date_dir
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}{ext}"
    path.write_bytes(blob)
    rel = str(path.relative_to(ensure_workspace())).replace("\\", "/")
    return {"ok": True, "path": rel, "url": "/workspace-file/" + rel, "mime": mime, "name": Path(original_name).name, "size": len(blob)}


def _image_data_url(rel: str) -> str:
    root = ensure_workspace().resolve()
    path = (root / rel).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError("Invalid image path")
    if path.stat().st_size > _MAX_IMAGE_BYTES:
        raise ValueError("Image too large")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _reference_context(ref_ids: list[str]) -> tuple[str, list[dict[str, str]]]:
    chunks: list[str] = []
    refs: list[dict[str, str]] = []
    total = 0
    seen: set[str] = set()
    for doc_id in ref_ids or []:
        if doc_id in seen:
            continue
        seen.add(doc_id)
        try:
            doc = store.get_doc(str(doc_id))
        except FileNotFoundError:
            continue
        body = str(doc.get("body") or "")[:_MAX_DOC_CHARS]
        projects_list = doc.get("projects") or ([doc.get("project")] if doc.get("project") else [])
        project_text = ", ".join(projects_list) or "未归属"
        header = f"[REF {len(refs)+1}] {doc.get('title','')} | 类型={doc.get('kind','')} | 项目={project_text}\n"
        chunk = header + body.strip()
        if total + len(chunk) > _MAX_CONTEXT_CHARS:
            remain = max(0, _MAX_CONTEXT_CHARS - total)
            if remain < 500:
                break
            chunk = chunk[:remain]
        chunks.append(chunk)
        refs.append({"id": doc["id"], "title": str(doc.get("title") or doc["id"]), "kind": str(doc.get("kind") or ""), "project": str(doc.get("project") or "")})
        total += len(chunk)
        if total >= _MAX_CONTEXT_CHARS:
            break
    if not chunks:
        return "", refs
    return "\n\n---\n\n".join(chunks), refs


def _llm_cfg() -> dict[str, Any]:
    cfg = config.get_active_llm_profile_runtime()
    if not cfg.get("enabled", False):
        raise ValueError("尚未在 设置 → Agent / LLM 中启用模型接口")
    if not str(cfg.get("api_key") or "").strip():
        raise ValueError("当前 Agent 配置尚未填写 API Key")
    if not str(cfg.get("base_url") or "").strip():
        raise ValueError("当前 Agent 配置尚未填写 Base URL")
    return cfg


def _endpoint(base_url: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith(suffix):
        return base
    return base + suffix


_HTTP_POOL: dict[tuple[str, str, int], list[http.client.HTTPConnection]] = {}  # v260929c · Keep-Alive 连接池：复用已建立的 TLS 连接，省去每次请求的 DNS/TCP/TLS 握手
_HTTP_POOL_LOCK = threading.Lock()
_MAX_POOL_PER_HOST = 4


_DEFAULT_UA = "Workbench/260922.3"  # 注意：opencode.ai 侧按 UA 做边缘拦截（Python-urllib 默认 UA 会触发 Cloudflare 1010），改动后需实测


def _api_headers(api_key: str, extra: dict[str, Any] | None = None) -> dict[str, str]:
    """v261008 · extra：档案级自定义请求头（config/secret.json 的 profiles[].headers）。

    先铺自定义头再落核心头，故 Content-Type 与 Authorization 不可被覆盖（密钥始终取档案的 api_key）；
    User-Agent / Accept 允许自定义头改写，便于适配有 UA 或边缘校验要求的网关。
    """
    headers = {str(k): str(v) for k, v in (extra or {}).items() if str(k).strip()}
    headers["Content-Type"] = "application/json"
    headers["Authorization"] = f"Bearer {api_key}"
    headers.setdefault("User-Agent", _DEFAULT_UA)
    headers.setdefault("Accept", "application/json")
    return headers


def _http_error_message(status: int, raw: str) -> str:
    detail = raw[:2000]
    try:
        msg = json.loads(raw).get("error", {}).get("message") or detail
    except Exception:
        msg = detail
    return f"LLM API HTTP {status}: {msg}"


def _pool_get(key: tuple[str, str, int], timeout: int) -> tuple[http.client.HTTPConnection, bool]:
    with _HTTP_POOL_LOCK:
        conns = _HTTP_POOL.get(key)
        if conns:
            return conns.pop(), True  # 复用池中连接
    scheme, host, port = key
    conn = http.client.HTTPSConnection(host, port, timeout=timeout) if scheme == "https" else http.client.HTTPConnection(host, port, timeout=timeout)
    return conn, False


def _pool_put(key: tuple[str, str, int], conn: http.client.HTTPConnection) -> None:
    with _HTTP_POOL_LOCK:
        conns = _HTTP_POOL.setdefault(key, [])
        if len(conns) < _MAX_POOL_PER_HOST:
            conns.append(conn)
            return
    try:
        conn.close()
    except Exception:
        pass


def _http_json(url: str, payload: dict[str, Any] | None, api_key: str, timeout: int = 120, method: str = "POST", extra_headers: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = _api_headers(api_key, extra_headers)
    tmo = max(5, min(int(timeout or 120), 600))
    # v260929c · 响应提速：未配置系统 https 代理时走 Keep-Alive 连接池（直连复用）；配置了代理则维持 urlopen 旧路径，行为不变
    if not urllib.request.getproxies().get("https"):
        u = urlparse(url)
        host = u.hostname or ""
        port = u.port or (443 if u.scheme == "https" else 80)
        key = (u.scheme, host, port)
        path = u.path + (("?" + u.query) if u.query else "")
        for attempt in (1, 0):  # 复用连接可能已被服务端关闭 → 新连接重试一次
            conn, reused = _pool_get(key, tmo)
            try:
                conn.request(method, path, body=body, headers=headers)
                resp = conn.getresponse()
                raw = resp.read().decode("utf-8", errors="replace")
                if resp.will_close:
                    conn.close()
                else:
                    _pool_put(key, conn)
                if resp.status >= 400:
                    raise ValueError(_http_error_message(resp.status, raw))
                return json.loads(raw) if raw else {}
            except ValueError:
                raise
            except TimeoutError:
                raise ValueError(f"无法连接 LLM API：请求超时（>{tmo}s），可在 设置 → Agent / LLM 调大超时") from None
            except Exception as e:
                try:
                    conn.close()
                except Exception:
                    pass
                if not reused or attempt == 0:
                    raise ValueError(f"无法连接 LLM API：{e}") from None
    req = Request(url, data=body, method=method, headers=headers)
    try:
        with urlopen(req, timeout=tmo) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:2000]
        try:
            msg = json.loads(detail).get("error", {}).get("message") or detail
        except Exception:
            msg = detail
        raise ValueError(f"LLM API HTTP {e.code}: {msg}") from None
    except URLError as e:
        raise ValueError(f"无法连接 LLM API：{e.reason}") from None


def _deep_merge_request(base: dict[str, Any], extra: dict[str, Any], protected: set[str]) -> dict[str, Any]:
    out = dict(base)
    for key, value in (extra or {}).items():
        if key in protected:
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge_request(out[key], value, set())
        else:
            out[key] = value
    return out


def _request_preset(cfg: dict[str, Any], preset_id: str) -> tuple[str, str, str, float | None, dict[str, Any]]:
    presets = cfg.get("request_presets") if isinstance(cfg.get("request_presets"), list) else []
    wanted = (preset_id or str(cfg.get("default_request_preset") or (presets[0].get("id") if presets else "default"))).strip()
    for item in presets:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") == wanted:
            params = item.get("params") if isinstance(item.get("params"), dict) else {}
            model = str(item.get("model") or "").strip()
            temperature = item.get("temperature")
            if temperature is not None:
                try:
                    temperature = float(temperature)
                except Exception:
                    temperature = None
            return wanted, str(item.get("label") or wanted), model, temperature, params
    if presets:
        first = presets[0]
        return (
            str(first.get("id") or "default"),
            str(first.get("label") or "默认"),
            str(first.get("model") or "").strip(),
            float(first.get("temperature")) if first.get("temperature") is not None else None,
            first.get("params") if isinstance(first.get("params"), dict) else {},
        )
    return "default", "默认", "", None, {}


def _reasoning_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ("text", "content", "summary", "reasoning_content"):
                    if item.get(key):
                        parts.append(str(item[key])); break
        return "\n".join(x for x in parts if x).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "summary", "reasoning_content"):
            if value.get(key):
                return _reasoning_text(value[key])
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return str(value).strip()


def _stream_chat(cfg: dict[str, Any], payload: dict[str, Any], tmo: int, on_delta) -> dict[str, Any]:
    """v260930k · 方案 A 流式：stream=True 发送，逐行读 SSE 聚合为完整 message（与 _post_chat 返回同构）。
    每收到一片 content delta 即回调 on_delta(text)；tool_calls 分片按 index 拼接。
    超时语义变为「相邻两片之间 ≤tmo 秒」——模型持续吐 token 则永不整体超时，根治长回答超时。"""
    payload = dict(payload)
    payload["stream"] = True
    payload.setdefault("stream_options", {"include_usage": True})  # v261008 · 请求末帧携带 usage（端点不支持时由 _STREAM_4XX_RE 降级非流式）
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = _api_headers(str(cfg["api_key"]), cfg.get("headers"))  # v261008 · 流式同样带档案自定义头
    headers["Accept"] = "text/event-stream"

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    usage_holder: dict[str, Any] = {}  # v261008 · 计费：捕获末帧 usage

    def _feed(line: str) -> None:
        if not line.startswith("data:"):
            return
        data = line[5:].strip()
        if not data or data == "[DONE]":
            return
        try:
            chunk = json.loads(data)
        except Exception:
            return
        if isinstance(chunk.get("usage"), dict):
            usage_holder["usage"] = chunk["usage"]
        for ch in chunk.get("choices") or []:
            delta = ch.get("delta") or {}
            piece = delta.get("content")
            if piece:
                content_parts.append(piece)
                on_delta(piece)
            r = delta.get("reasoning_content")
            if r:
                reasoning_parts.append(r if isinstance(r, str) else _reasoning_text(r))
            for tc in delta.get("tool_calls") or []:
                idx = int(tc.get("index") or 0)
                slot = tool_calls.setdefault(idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = str(tc["id"])
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] += str(fn["name"])
                if fn.get("arguments"):
                    slot["function"]["arguments"] += str(fn["arguments"])

    endpoint = _endpoint(str(cfg["base_url"]), "/chat/completions")
    # v260930k · 直连池路径：与 _http_json 相同的 Keep-Alive 复用，但逐行读响应
    if not urllib.request.getproxies().get("https"):
        u = urlparse(endpoint)
        host = u.hostname or ""
        port = u.port or (443 if u.scheme == "https" else 80)
        key = (u.scheme, host, port)
        path = u.path + (("?" + u.query) if u.query else "")
        for attempt in (1, 0):
            conn, reused = _pool_get(key, tmo)
            try:
                conn.request("POST", path, body=body, headers=headers)
                resp = conn.getresponse()
                if resp.status >= 400:
                    raw = resp.read().decode("utf-8", errors="replace")
                    if resp.will_close:
                        conn.close()
                    else:
                        _pool_put(key, conn)
                    raise ValueError(_http_error_message(resp.status, raw))
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    _feed(line.decode("utf-8", errors="replace").rstrip("\r\n"))
                if resp.will_close:
                    conn.close()
                else:
                    _pool_put(key, conn)
                break
            except ValueError:
                raise
            except TimeoutError:
                raise ValueError(f"LLM 流式响应中断（>{tmo}s 无新内容）") from None
            except Exception as e:
                try:
                    conn.close()
                except Exception:
                    pass
                if not reused or attempt == 0:
                    raise ValueError(f"无法连接 LLM API：{e}") from None
    else:  # v260930k · 代理路径：urlopen 逐行读
        req = Request(endpoint, data=body, method="POST", headers=headers)
        try:
            with urlopen(req, timeout=tmo) as resp:
                for raw_line in resp:
                    _feed(raw_line.decode("utf-8", errors="replace").rstrip("\r\n"))
        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:2000]
            try:
                msg = json.loads(detail).get("error", {}).get("message") or detail
            except Exception:
                msg = detail
            raise ValueError(f"LLM API HTTP {e.code}: {msg}") from None
        except TimeoutError:
            raise ValueError(f"LLM 流式响应中断（>{tmo}s 无新内容）") from None

    message: dict[str, Any] = {"content": "".join(content_parts)}
    if reasoning_parts:
        message["reasoning_content"] = "".join(reasoning_parts)
    calls = [tool_calls[i] for i in sorted(tool_calls)]
    if calls:
        message["tool_calls"] = calls
    billing.record(cfg, usage_holder.get("usage"))  # v261008 · 计费：流式末帧 usage（无 _billing 上下文时自动跳过）
    return message


def _post_chat(cfg: dict[str, Any], messages: list[dict[str, Any]], request_params: dict[str, Any] | None = None, tools: list[dict[str, Any]] | None = None, on_delta=None) -> dict[str, Any]:
    """v260930 · M1 底层补全请求：发送完整 messages，返回原始 assistant message（含 tool_calls）。
    tools 传入时走原生 function calling；端点不支持时由调用方降级文本协议。"""
    payload: dict[str, Any] = {"model": cfg["model"], "messages": messages, "stream": False}
    if cfg.get("temperature") is not None:
        payload["temperature"] = float(cfg.get("temperature"))
    if int(cfg.get("max_output_tokens") or 0) > 0:
        payload["max_tokens"] = int(cfg["max_output_tokens"])
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    payload = _deep_merge_request(payload, request_params or {}, {"model", "messages", "stream", "tools", "tool_choice"})
    tmo = int(cfg.get("timeout") or 120)
    if on_delta:  # v260930k · 方案 A：流式优先；端点拒绝流式（4xx）时降级非流式，行为与旧路径一致
        try:
            return _stream_chat(cfg, payload, tmo, on_delta)
        except ValueError as e:
            if not _STREAM_4XX_RE.search(str(e)):
                raise
    data = _http_json(_endpoint(str(cfg["base_url"]), "/chat/completions"), payload, str(cfg["api_key"]), tmo, extra_headers=cfg.get("headers"))
    billing.record(cfg, data.get("usage"))  # v261008 · 计费：非流式 usage（流式分支已在 _stream_chat 内记录，4xx 降级不重复计）
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("模型返回中没有 choices")
    message = choices[0].get("message", {}) or {}
    if not isinstance(message, dict):
        raise ValueError("模型返回的 message 结构异常")
    return message


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, list):
        content = "\n".join(str(x.get("text") or "") for x in content if isinstance(x, dict))
    return str(content or "").strip()


def _message_reasoning(cfg: dict[str, Any], message: dict[str, Any]) -> str:
    if not cfg.get("show_reasoning", True):
        return ""
    for key in ("reasoning_content", "reasoning", "thinking", "analysis"):
        if message.get(key) is not None:
            reasoning = _reasoning_text(message.get(key))
            if reasoning:
                return reasoning
    return ""


def _chat_completions(cfg: dict[str, Any], system_prompt: str, history: list[dict[str, Any]], user_text: str, image_paths: list[str], request_params: dict[str, Any] | None = None, image_data_urls: list[str] | None = None) -> tuple[str, str]:
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for m in history[-_MAX_HISTORY_MESSAGES:]:
        role = m.get("role")
        if role in ("user", "assistant") and str(m.get("content") or "").strip():
            messages.append({"role": role, "content": str(m.get("content") or "")})
    img_urls: list[str] = []  # v260929c · 多模态消息：workspace 图片路径 + 直接传入的截图 data URL 合并
    if image_paths:
        img_urls.extend(_image_data_url(p) for p in image_paths[:6])
    if image_data_urls:
        img_urls.extend(str(u) for u in image_data_urls[:6] if str(u).startswith("data:image/"))
    if img_urls:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text or "请分析这些图片。"}]
        for u in img_urls:
            content.append({"type": "image_url", "image_url": {"url": u}})
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user_text})
    message = _post_chat(cfg, messages, request_params)
    return _message_text(message), _message_reasoning(cfg, message)


_MAX_TOOL_STEPS = 12  # v260930l · 8→12：批量建档（如一次建 6 条）单轮检索+创建+更新步数不够
_TOOL_BUDGET_SECONDS = 480  # v260930l · 工具循环整体时间预算：超时强制收尾作答，不再无限等待
_TOOL_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)
_FALLBACK_STATUS_RE = re.compile(r"LLM API HTTP 4(?:00|04|22)")
_STREAM_4XX_RE = re.compile(r"LLM API HTTP 4\d\d")  # v260930k · 流式被端点拒绝（4xx）→ 降级非流式重试


def _page_context(context: Any) -> str:
    """v260930 · M1 页面上下文注入：把前端传来的「你在哪/选中了什么」写进系统提示词，
    工具层同享该上下文（lit_context/lit_note_write 缺省 paper_id 时取它）。"""
    if not isinstance(context, dict):
        return ""
    parts: list[str] = []
    paper_id = str(context.get("paper_id") or "").strip()
    page = context.get("page")
    doc_id = str(context.get("doc_id") or "").strip()
    view = str(context.get("view") or "").strip()
    selection = str(context.get("selection") or "").strip()
    if paper_id:
        try:
            from . import literature
            item = literature.get_item(paper_id)
            parts.append(f"正在阅读文献《{item.get('title')}》（paper_id={paper_id}" + (f"，第 {page} 页" if page else "") + "）")
        except Exception:
            parts.append(f"正在阅读文献（paper_id={paper_id}）")
    elif view:
        parts.append(f"当前页面：{view}" + (f"，第 {page} 页" if page else ""))
    if doc_id:
        parts.append(f"当前打开的知识条目：doc_id={doc_id}")
    if selection:
        parts.append("用户当前选中的内容：\n" + selection[:4000] + ("…" if len(selection) > 4000 else ""))
    page_text = str(context.get("page_text") or "").strip()
    if page_text:  # v260930 · M4 术语提取：文献当前页正文（前端 pdf.js 文本层采集），供提取专业名词
        parts.append("文献当前页正文（供术语提取与问答，勿向用户复述全文）：\n" + page_text[:6000] + ("…" if len(page_text) > 6000 else ""))
    quote = str(context.get("quote_text") or "").strip()
    if quote:  # v260930j · 引用历史对话：前端从被引用会话提取的消息文本，跨会话延续上下文
        parts.append("用户引用的历史对话内容（供参考，回答时可引用；勿复述全文）：\n" + quote[:4000] + ("…" if len(quote) > 4000 else ""))
    if not parts:
        return ""
    return "\n\n当前页面上下文（lit_context / lit_note_write 不传 paper_id 时默认使用此文献）：\n" + "\n".join(f"- {p}" for p in parts)


def _exec_tool_call(name: str, args_raw: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    """执行单个工具调用：参数解析失败也转 ok=False 结果，交回模型自修正。"""
    if isinstance(args_raw, str):
        try:
            args = json.loads(args_raw) if args_raw.strip() else {}
        except Exception:
            return {"ok": False, "error": f"工具参数不是合法 JSON：{args_raw[:200]}"}
    elif isinstance(args_raw, dict):
        args = args_raw
    else:
        args = {}
    return agent_tools.execute(name, args, ctx)


def _run_with_tools(cfg: dict[str, Any], system_prompt: str, history: list[dict[str, Any]], user_text: str, image_paths: list[str], request_params: dict[str, Any], ctx: dict[str, Any], on_delta=None, on_round=None, on_tool=None) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """v260930 · M1 工具调用循环：原生 function calling 优先，端点不支持时降级文本协议。
    返回 (最终回答, 推理过程, 工具轨迹, 本轮产生的待确认草稿, 计时)。
    v260930k · on_delta/on_round 用于 SSE 流式转发：每轮请求前 on_round(i)，文本片段 on_delta(t)。
    v260930l · on_tool(name,result) 工具执行完实时上报；_TOOL_BUDGET_SECONDS 超时强制收尾，防长任务体感卡死。
    v261008b · 第 5 项计时：每轮 LLM 调用与每次工具调用都记 t0/t1（相对本轮起点毫秒），
    汇总成 timing（总耗时 / 思考耗时 / 工具耗时 / 轮数 / 时间轴），供前端画时间条而非罗列流水账。"""
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for m in history[-_MAX_HISTORY_MESSAGES:]:
        if m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip():
            messages.append({"role": m["role"], "content": str(m.get("content") or "")})
    img_urls = [_image_data_url(p) for p in (image_paths or [])[:6]]
    if img_urls:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text or "请分析这些图片。"}] + [{"type": "image_url", "image_url": {"url": u}} for u in img_urls]
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user_text})

    tool_trace: list[dict[str, Any]] = []
    drafts: list[dict[str, Any]] = []
    allowed = [t for t in (ctx.get("tools") or agent_tools.TOOL_NAMES) if t in agent_tools.TOOL_NAMES] or list(agent_tools.TOOL_NAMES)
    specs = agent_tools.openai_specs(allowed)

    # ---------- v261008b · 计时：时间轴 + 汇总 ----------
    t_start = time.monotonic()
    timeline: list[dict[str, Any]] = []

    def _ms() -> int:
        return int((time.monotonic() - t_start) * 1000)

    def _llm_seg(step: int) -> dict[str, Any]:
        seg = {"kind": "llm", "t0": _ms(), "t1": None, "round": step + 1}
        timeline.append(seg)
        return seg

    def _close(seg: dict[str, Any] | None) -> None:
        if seg is not None and seg.get("t1") is None:
            seg["t1"] = _ms()

    def _tool_seg(name: str, ok: bool, t0: int, t1: int) -> None:
        timeline.append({"kind": "tool", "name": name, "ok": bool(ok), "t0": t0, "t1": t1})

    def _timing(protocol: str) -> dict[str, Any]:
        total = _ms()
        llm_ms = sum(max(0, int(s.get("t1") or 0) - int(s.get("t0") or 0)) for s in timeline if s.get("kind") == "llm")
        tool_ms = sum(max(0, int(s.get("t1") or 0) - int(s.get("t0") or 0)) for s in timeline if s.get("kind") == "tool")
        return {
            "total_ms": total,
            "llm_ms": llm_ms,
            "tool_ms": tool_ms,
            "rounds": sum(1 for s in timeline if s.get("kind") == "llm"),
            "tool_calls": len(tool_trace),
            "protocol": protocol,  # tools=原生 function calling，text=文本协议兜底
            "timeline": timeline,
        }

    def _record(result: dict[str, Any], name: str, args: dict[str, Any], t0: int | None = None, t1: int | None = None) -> None:
        entry = {"tool": name, "ok": bool(result.get("ok")), "ms": result.get("tool_ms", 0)}
        if t0 is not None:
            entry["t0"] = t0
        if t1 is not None:
            entry["t1"] = t1
        if result.get("pending") and result.get("draft_id"):
            entry["draft_id"] = result["draft_id"]
            drafts.append({"draft_id": result["draft_id"], "tool": name, "summary": (result.get("draft") or {}).get("title") or (result.get("draft") or {}).get("doc_id") or name})
        if result.get("doc_id"):  # v260930 · M3 直写成功时记录落盘条目 id，便于前端展示与追溯
            entry["doc_id"] = result["doc_id"]
        tool_trace.append(entry)

    # 阶段一：原生 function calling（端点报 4xx 工具不支持时整体转文本协议）
    deadline = time.monotonic() + _TOOL_BUDGET_SECONDS  # v260930l · 循环整体预算
    try:
        for step in range(_MAX_TOOL_STEPS):
            if time.monotonic() > deadline:
                break  # v260930l · 超出预算：跳出循环走收尾作答
            if on_round:
                on_round(step)  # v260930k · 新一轮 LLM 请求：前端清空临时缓冲，区分中途文本与最终回答
            seg = _llm_seg(step)  # v261008b · 本轮 LLM 调用计时
            message = _post_chat(cfg, messages, request_params, tools=specs, on_delta=on_delta)
            _close(seg)
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list) or not calls:
                return _message_text(message), _message_reasoning(cfg, message), tool_trace, drafts, _timing("tools")
            messages.append({"role": "assistant", "content": _message_text(message) or None, "tool_calls": calls})
            for tc in calls:
                fn = (tc or {}).get("function") or {}
                name = str(fn.get("name") or "")
                t0 = _ms()  # v261008b · 单次工具调用计时
                result = _exec_tool_call(name, fn.get("arguments"), ctx)
                t1 = _ms()
                if on_tool:
                    on_tool(name, result)  # v260930l · 工具执行完实时上报
                _record(result, name, {} if not isinstance(fn.get("arguments"), dict) else fn.get("arguments"), t0, t1)
                _tool_seg(name, bool(result.get("ok")), t0, t1)
                messages.append({"role": "tool", "tool_call_id": str(tc.get("id") or ""), "content": json.dumps(result, ensure_ascii=False)[:16000]})
        messages.append({"role": "user", "content": "工具调用步数或时间已达上限，请直接基于已获得的信息作答，不要再调用工具。"})
        if on_round:
            on_round(_MAX_TOOL_STEPS)
        seg = _llm_seg(_MAX_TOOL_STEPS)
        message = _post_chat(cfg, messages, request_params, on_delta=on_delta)
        _close(seg)
        return _message_text(message), _message_reasoning(cfg, message), tool_trace, drafts, _timing("tools")
    except ValueError as e:
        if not _FALLBACK_STATUS_RE.search(str(e)):
            raise

    # 阶段二：文本协议兜底（同一循环内逐轮解析 ```json {"tool":...}``` 块）
    messages = [dict(messages[0])]  # 重建：system 换成带文本协议说明的版本
    messages[0]["content"] = system_prompt + "\n\n" + agent_tools.text_protocol_prompt(allowed)
    for m in history[-_MAX_HISTORY_MESSAGES:]:
        if m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip():
            messages.append({"role": m["role"], "content": str(m.get("content") or "")})
    messages.append({"role": "user", "content": user_text})
    deadline = time.monotonic() + _TOOL_BUDGET_SECONDS  # v260930l
    for step in range(_MAX_TOOL_STEPS):
        if time.monotonic() > deadline:
            break  # v260930l · 超出预算：停止循环，按上限作答
        if on_round:
            on_round(step)
        seg = _llm_seg(step)  # v261008b
        message = _post_chat(cfg, messages, request_params, on_delta=on_delta)
        _close(seg)
        text = _message_text(message)
        m = _TOOL_JSON_RE.search(text)
        if not m:
            return text, _message_reasoning(cfg, message), tool_trace, drafts, _timing("text")
        try:
            call = json.loads(m.group(1))
        except Exception:
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": "上一个工具调用块不是合法 JSON，请重新按格式调用，或直接给出最终回答。"})
            continue
        name = str(call.get("tool") or "")
        t0 = _ms()  # v261008b
        result = _exec_tool_call(name, call.get("args"), ctx)
        t1 = _ms()
        if on_tool:
            on_tool(name, result)  # v260930l
        _record(result, name, call.get("args") if isinstance(call.get("args"), dict) else {}, t0, t1)
        _tool_seg(name, bool(result.get("ok")), t0, t1)
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": "工具结果：\n```json\n" + json.dumps(result, ensure_ascii=False)[:16000] + "\n```\n请继续（可再次调用工具或给出最终回答）。"})
    raise ValueError("工具调用步数或时间已达上限（文本协议），请精简任务后重试")


def send_message(session_id: str, text: str, ref_ids: list[str] | None = None, image_paths: list[str] | None = None, request_preset: str = "", context: dict[str, Any] | None = None, persona_id: str = "", on_delta=None, on_round=None, on_tool=None) -> dict[str, Any]:
    text = str(text or "").strip()
    ref_ids = [str(x) for x in (ref_ids or []) if str(x).strip()]
    ctx_doc_id = str((context or {}).get("doc_id") or "").strip()
    if ctx_doc_id and ctx_doc_id not in ref_ids:  # v260930i · 直接引用当前打开条目：doc_id 自动并入 ref_ids，注入标题+正文节选，AI 无需工具即可引用
        ref_ids.append(ctx_doc_id)
    image_paths = [str(x) for x in (image_paths or []) if str(x).strip()][:6]
    if not text and not image_paths:
        raise ValueError("请输入消息或添加图片")
    root = ensure_workspace().resolve()
    total_image_bytes = 0
    for rel in image_paths:
        p = (root / rel).resolve()
        if root not in p.parents or not p.is_file():
            raise ValueError("对话图片路径无效")
        total_image_bytes += p.stat().st_size
    if total_image_bytes > 30 * 1024 * 1024:
        raise ValueError("本次发送的图片总大小不能超过 30 MB")
    cfg = _llm_cfg()
    with _LOCK:
        try:
            session = get_session(session_id)
        except FileNotFoundError:
            session = create_session()
            session_id = session["id"]
        messages = session.get("messages") if isinstance(session.get("messages"), list) else []
        history = list(messages)
    ref_context, refs = _reference_context(ref_ids)
    # v260930 · M3 人设：系统提示词/工具白名单/写模式由人设决定；未传 persona_id 时沿用 llm.system_prompt + 全量工具（向下兼容）
    persona: dict[str, Any] | None = None
    if str(persona_id or "").strip():
        persona = config.resolve_persona(str(persona_id))
        system_prompt = str(persona.get("system_prompt") or config.DEFAULT_SYSTEM_PROMPT).strip()
    else:
        system_prompt = str(cfg.get("system_prompt") or config.DEFAULT_SYSTEM_PROMPT).strip()
    system_prompt = config.writing_rules() + "\n\n" + system_prompt  # v260930g4 · 统一写作与建档约束注入所有人设（单一真相源 Workspace/System/AI助手写作与建档规范.md）
    if ref_context:
        system_prompt += "\n\n以下是用户手动引用的本地研究资料。仅将其作为上下文，不要声称看到了未提供的资料：\n\n" + ref_context
    system_prompt += _page_context(context)  # v260930 · M1 页面上下文注入
    preset_id, preset_label, preset_model, preset_temperature, request_params = _request_preset(cfg, request_preset or (str(persona.get("request_preset") or "") if persona else ""))
    if not preset_model:
        raise ValueError(f"请求模式 {preset_label} 尚未配置模型名称")
    request_cfg = dict(cfg)
    request_cfg["model"] = preset_model
    persona_temp = persona.get("temperature") if persona else None  # v260930 · M3 人设可覆盖温度（请求模式未给温度时生效）
    if preset_temperature is not None:
        request_cfg["temperature"] = preset_temperature
    elif persona_temp is not None:
        request_cfg["temperature"] = persona_temp
    now = _now()
    user_msg = {"id": "msg-" + uuid.uuid4().hex[:10], "role": "user", "content": text, "created": now, "refs": refs, "images": image_paths, "request_preset": preset_id, "request_preset_label": preset_label, "profile_id": cfg.get("id"), "profile_name": cfg.get("name"), "persona_id": (persona or {}).get("id", ""), "persona_name": (persona or {}).get("name", "")}
    with _LOCK:
        session = get_session(session_id)
        session.setdefault("messages", []).append(user_msg)
        if session.get("archived"):
            session["archived"] = False  # v260930n · 归档会话收到新消息：自动回到活跃列表
        if session.get("title") in ("", "新对话"):
            session["title"] = (text or "图片分析")[:36]
        session["updated"] = _now()
        _atomic_json(_session_path(session_id), session)
    # v260930 · M1/M3 工具上下文：confirm（默认）写工具只出草稿；人设 write_mode 与页面 write_mode 取交集（更严格者胜）
    page_ctx = context if isinstance(context, dict) else {}
    persona_mode = str(persona.get("write_mode") or "confirm") if persona else "confirm"
    page_mode = str(page_ctx.get("write_mode") or "").strip()
    write_mode = "direct" if persona_mode == "direct" and page_mode == "direct" else "confirm"
    ctx = {
        "paper_id": str(page_ctx.get("paper_id") or "").strip(),
        "write_mode": write_mode,
        "tools": list(persona.get("tools") or []) if persona else list(agent_tools.TOOL_NAMES),  # v260930 · M3 人设工具白名单
    }
    request_cfg["_billing"] = {  # v261008 · 计费归属：会话 + 请求模式（探针类调用无此上下文，自动不计费）
        "session_id": session_id,
        "session_title": str(session.get("title") or ""),
        "preset_label": preset_label,
        "source": "chat",
    }
    answer, reasoning, tool_trace, drafts, timing = _run_with_tools(request_cfg, system_prompt, history, text, image_paths, request_params, ctx, on_delta=on_delta, on_round=on_round, on_tool=on_tool)
    assistant_msg = {
        "id": "msg-" + uuid.uuid4().hex[:10], "role": "assistant", "content": answer, "reasoning": reasoning,
        "created": _now(), "model": preset_model, "request_preset": preset_id, "request_preset_label": preset_label,
        "profile_id": cfg.get("id"), "profile_name": cfg.get("name"),
        "persona_id": (persona or {}).get("id", ""), "persona_name": (persona or {}).get("name", ""),  # v260930 · M3 回复标记人设
        "tool_trace": tool_trace, "drafts": drafts,  # v260930 · M1 工具轨迹与本轮待确认草稿（前端可展示）
        "timing": timing,  # v261008b · 计时与时间轴：前端据此画时间条 + 显示总耗时（SSE done 事件随 assistant 一并回传）
    }
    with _LOCK:
        session = get_session(session_id)
        session.setdefault("messages", []).append(assistant_msg)
        session["updated"] = _now()
        _atomic_json(_session_path(session_id), session)
    activity.record("agent_chat", ref=session_id, kind="agent", title=session.get("title", "Agent 对话"), project="")
    return {"ok": True, "session": session, "assistant": assistant_msg}


_ASSIST_PROMPTS = {  # v260929 · PDF 阅读区 AI 助手：按动作切换系统提示词，全部要求 Markdown 输出；具体行为可经 设置→文献/PDF→AI 阅读助手 调整
    "translate": "你是科研文献翻译助手。将用户提供的学术内容准确翻译为目标语言：专业术语首次出现时在括号内保留原文；公式、变量、单位、人名保持原样。只输出译文本身，不要任何解释或原文重复。",
    "summarize": "你是科研文献阅读助手。用中文对用户提供的内容做要点总结：提炼核心观点、方法与结论，输出为简洁的 Markdown 列表；只依据给定内容，不得编造其中不存在的信息。",
    "organize": "你是科研知识整理助手。把用户提供的内容整理为结构化中文知识笔记（Markdown 分节）：核心要点、关键术语、方法/数据、可引用结论；条目化并保留关键数字与公式；只依据给定内容，不得编造。",
    "polish": "你是科研笔记编辑助手。整理润色用户提供的文献笔记（Markdown）：统一为清晰的结构（如 摘要/要点/方法/结论/摘录），修正错别字与冗余表达；必须保留用户笔记中的全部原有信息，不得删改实质内容，不得添加虚构内容。",
}
_MAX_ASSIST_CHARS = 24_000  # 默认输入上限，可经 设置→文献/PDF→AI 阅读助手 调整（1000–60000）


def assist(action: str, text: str, instruction: str = "", image: str = "") -> dict[str, Any]:
    """v260929 · PDF 阅读区 AI 助手（无会话状态的一次性补全）：
    复用 设置→Agent/LLM 的模型档案；行为参数（启用/请求模式/翻译目标语言/附加风格指令/输入上限/
    自定义动作）来自 设置→文献/PDF→AI 阅读助手（config/app.json llm.assist）。
    v260929c · image：页面/框选截图 data URL，代替选中文本交多模态模型处理（需在 Agent/LLM 开启多模态）。"""
    action = str(action or "").strip() or "custom"
    instruction = str(instruction or "").strip()
    text = str(text or "").strip()
    image = str(image or "").strip()
    if not text and not image:
        raise ValueError("没有可处理的文本或截图")
    cfg = _llm_cfg()
    if image:  # v260929c · 截图模式：多模态门控 + 数据校验
        if not cfg.get("vision_enabled"):
            raise ValueError("多模态未开启：可在 设置 → Agent / LLM 开启「多模态 / 截图识别」，并确认当前模型支持图片输入")
        if not image.startswith("data:image/") or ";base64," not in image[:64]:
            raise ValueError("截图数据无效")
        if len(image) > 10 * 1024 * 1024:
            raise ValueError("截图过大（超过 10 MB），请缩小截图范围或降低页面缩放后重试")
    st = cfg.get("assist") if isinstance(cfg.get("assist"), dict) else {}
    if st.get("enabled") is False:
        raise ValueError("AI 阅读助手已在 设置 → 文献 / PDF 中关闭")
    try:
        max_chars = max(1000, min(60000, int(st.get("max_chars") or _MAX_ASSIST_CHARS)))
    except Exception:
        max_chars = _MAX_ASSIST_CHARS
    if len(text) > max_chars:
        text = text[:max_chars]
    action_label = ""  # v260929b · 自定义动作的显示名（用于报错信息）
    custom = next((x for x in (st.get("custom_actions") if isinstance(st.get("custom_actions"), list) else [])
                   if isinstance(x, dict) and str(x.get("id") or "") == action), None)  # v260929b · 自定义阅读动作：id 匹配则用其提示词
    if custom:
        action_label = str(custom.get("name") or "自定义动作")
        system_prompt = str(custom.get("prompt") or "").strip()
        if not system_prompt:
            raise ValueError(f"自定义动作「{action_label}」尚未配置提示词，可在 设置 → 文献 / PDF → AI 阅读助手 中补充")
    elif action in _ASSIST_PROMPTS:
        # v260929x · 预设动作提示词可覆盖（设置→文献/PDF→AI 阅读助手），留空用内置默认
        overrides = st.get("prompts") if isinstance(st.get("prompts"), dict) else {}
        system_prompt = str(overrides.get(action) or "").strip() or _ASSIST_PROMPTS[action]
        if action == "translate":
            lang = str(st.get("target_language") or "中文").strip() or "中文"
            system_prompt += f"\n目标语言：{lang}。"
    else:
        if not instruction:
            raise ValueError("自定义指令不能为空")
        system_prompt = "你是科研工作台里的 AI 助手，严格按用户给出的指令处理提供的文本，输出中文 Markdown。"
    style = str(st.get("style_instruction") or "").strip()
    if style:
        system_prompt += "\n\n附加要求：\n" + style
    if image:  # v260929c · 截图模式：提示模型先做精确的图内识别，提高公式/表格提取正确率
        system_prompt += "\n用户以截图提供内容：请先从图片中精确识别文字、公式与图表信息（保持 LaTeX 形式），再按上述要求处理。"
    presets = cfg.get("request_presets") if isinstance(cfg.get("request_presets"), list) else []  # v260929b · 阅读助手未指定请求模式时直接用第一个，不走 Agent 默认解析
    first = presets[0] if presets and isinstance(presets[0], dict) else {}
    preset_id, preset_label, preset_model, preset_temperature, request_params = _request_preset(cfg, str(st.get("request_preset") or str(first.get("id") or "default")))
    model_override = str(st.get("model_override") or "").strip()  # v260929 · 阅读助手可无视所选请求模式，直接覆盖模型/温度/附加参数
    if model_override:
        preset_model = model_override
    if not preset_model:
        raise ValueError(f"请求模式 {preset_label} 尚未配置模型名称，可在 设置 → 文献/PDF → AI 阅读助手 的「模型覆盖」中填写")
    request_cfg = dict(cfg)
    request_cfg["model"] = preset_model
    resolved_temp = preset_temperature
    if st.get("temperature_override") is not None:
        try:
            resolved_temp = float(st.get("temperature_override"))
        except Exception:
            pass
    if resolved_temp is not None:
        request_cfg["temperature"] = resolved_temp
    extra = st.get("extra_params") if isinstance(st.get("extra_params"), dict) else {}
    if extra:
        request_params = _deep_merge_request(request_params, extra, {"model", "messages", "stream"})
    user_text = (text + (f"\n\n---\n指令：{instruction}" if instruction and action == "custom" else "")) or ("请处理这张截图中的内容。" if image else "")
    request_cfg["_billing"] = {  # v261008 · 计费归属：阅读助手无会话，归入虚拟会话统一统计
        "session_id": "__assist__",
        "session_title": "AI 阅读助手",
        "preset_label": preset_label,
        "source": "assist",
    }
    content, reasoning = _chat_completions(request_cfg, system_prompt, [], user_text, None, request_params, [image] if image else None)
    return {"ok": True, "action": action, "label": action_label, "content": content, "model": preset_model,
            "reasoning": reasoning if cfg.get("show_reasoning", True) else ""}


_MODELS_UNSUPPORTED_RE = re.compile(r"LLM API HTTP (?:404|405|501)\b")  # v261008 · 网关不提供 GET /models 的信号


def test_connection() -> dict[str, Any]:
    """连通性探针：优先 GET /models 列出模型。

    v261008 · 部分 OpenAI 兼容网关（如火山方舟 Agent Plan 的 /api/plan/v3）不提供 /models，
    返回 404 会让「能用但测不通」；此时退化为一次最小 Chat Completions 探针（默认请求模式的模型，
    16 tokens），返回 choices 即视为连通。其余错误（401/429/5xx 等）仍原样抛出，保留诊断信息。
    """
    cfg = _llm_cfg()
    timeout = min(int(cfg.get("timeout") or 30), 45)
    url = _endpoint(str(cfg["base_url"]), "/models")
    try:
        data = _http_json(url, None, str(cfg["api_key"]), timeout, method="GET", extra_headers=cfg.get("headers"))
    except ValueError as e:
        if not _MODELS_UNSUPPORTED_RE.search(str(e)):
            raise
        _preset_id, preset_label, model, _preset_temp, params = _request_preset(cfg, "")
        if not model:
            raise ValueError(f"{e}；且默认请求模式 {preset_label} 未配置模型名，无法用对话探针替代") from None
        payload = _deep_merge_request(
            {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 16, "stream": False},
            params,
            {"model", "messages", "stream"},
        )
        data = _http_json(_endpoint(str(cfg["base_url"]), "/chat/completions"), payload, str(cfg["api_key"]), max(timeout, 60), extra_headers=cfg.get("headers"))
        if not (isinstance(data, dict) and data.get("choices")):
            raise ValueError("对话探针没有返回 choices，网关可能不是 OpenAI 兼容的 Chat Completions") from None
        return {
            "ok": True,
            "models": [model],
            "message": f"连接成功（网关不提供 GET /models，已用对话探针验证 {model}）",
            "profile": cfg.get("name") or "",
            "probe": "chat_completions",
        }
    models = data.get("data") if isinstance(data, dict) else []
    names = [str(x.get("id")) for x in (models or []) if isinstance(x, dict) and x.get("id")][:12]
    return {"ok": True, "models": names, "message": "连接成功", "profile": cfg.get("name") or "", "probe": "models"}
