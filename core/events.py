"""内核事件总线（REFACTOR_PLAN §6.3 声明的扩展点 · `ctx.events`）。

**为什么在 core 而不是 app**：它是「解耦硬依赖」的通用机制——内核在某个节点**广播事实**
（一次 LLM 调用的用量、某个条目被改写），功能模块按需订阅；**没有订阅者时内核照常工作**。
这正是计划里 P14 要求的「钩子倒置」：`app/agent.py` 不该 import 计费，只该广播。

用法（内核侧）：

    from core import events
    events.emit("llm.usage", {"billing": ctx, "usage": usage, "model": model})

用法（插件侧，经 `ctx.events`）：

    def on_usage(payload): ...
    off = ctx.events.on("llm.usage", on_usage)     # 返回取消订阅函数

约定（与 PLUGIN_SPEC §6「hook 全部 try/except」一致）：
1. **订阅者异常被隔离**：一个订阅者抛异常不影响其它订阅者，也不影响广播方；
2. **载荷只读**：订阅者不得修改载荷（拿到的是一份浅拷贝，避免互相串味）；
3. **不得同步长耗时**：回调里不要做慢 IO（内核在请求路径上广播）；
4. **未启用则收不到**：插件的订阅随 `register(ctx)` 建立，停用即不再广播给它。
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Callable

_LOCK = threading.RLock()
_SUBS: dict[str, list[Callable[[dict], Any]]] = {}

#: 已知事件名及其载荷（未列出的也允许，只是不做校验）
KNOWN_EVENTS: dict[str, str] = {
    "llm.usage": "一次 LLM 调用结束：{billing, usage, model, profile_id, profile_name}",
}


def on(name: str, callback: Callable[[dict], Any]) -> Callable[[], None]:
    """订阅事件，返回**取消订阅**函数。"""
    if not callable(callback):
        raise TypeError("events.on 需要可调用对象")
    key = str(name or "").strip()
    if not key:
        raise ValueError("events.on 需要事件名")
    with _LOCK:
        _SUBS.setdefault(key, []).append(callback)
    def off() -> None:
        with _LOCK:
            cbs = _SUBS.get(key) or []
            if callback in cbs:
                cbs.remove(callback)
            if not cbs:
                _SUBS.pop(key, None)
    return off


def emit(name: str, payload: dict | None = None) -> int:
    """广播事件，返回成功送达的订阅者数量（订阅者异常只记日志、不计入）。"""
    key = str(name or "").strip()
    with _LOCK:
        callbacks = list(_SUBS.get(key) or [])
    if not callbacks:
        return 0
    data = dict(payload or {})   # 浅拷贝：订阅者拿到的载荷互不串味
    delivered = 0
    for cb in callbacks:
        try:
            cb(data)
            delivered += 1
        except Exception as exc:  # 订阅者故障不得影响广播方（内核请求路径）
            print(f"[events] 订阅者处理 {key} 失败（已隔离）：{type(exc).__name__}: {exc}", file=sys.stderr)
    return delivered


def subscriber_count(name: str = "") -> int:
    """体检用：某事件（留空=全部）的订阅者数量。"""
    with _LOCK:
        if name:
            return len(_SUBS.get(str(name)) or [])
        return sum(len(v) for v in _SUBS.values())


def clear() -> None:
    """测试用：清空所有订阅。"""
    with _LOCK:
        _SUBS.clear()
