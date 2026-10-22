"""A desktop-owned countdown that continues when WebView timers are throttled."""
from __future__ import annotations

import math
import threading
import time
from typing import Callable


class FocusTimer:
    def __init__(self, on_complete: Callable, *, clock=time.monotonic, timer_factory=threading.Timer):
        self._complete = on_complete
        self._clock = clock
        self._factory = timer_factory
        self._lock = threading.RLock()
        self._timer = None
        self._generation = 0
        self._deadline = None
        self._remaining = self._total = 1500
        self._mode = "专注"
        self._initialized = False
        self._closed = False

    @staticmethod
    def _duration(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 14400:
            raise ValueError("计时时长需大于 0 且不超过 240 分钟")
        return float(value)

    def _left(self):
        return max(0, self._deadline - self._clock()) if self._deadline is not None else self._remaining

    def snapshot(self):
        with self._lock:
            remaining = self._left()
            return {"initialized": self._initialized, "running": self._deadline is not None,
                    "remaining": remaining, "seconds": math.ceil(remaining), "total": self._total,
                    "mode": self._mode, "generation": self._generation}

    def _cancel(self):
        self._generation += 1
        if self._timer:
            self._timer.cancel()
        self._timer = None

    def configure(self, seconds, mode, total=None, *, running=False):
        seconds = self._duration(seconds)
        total = self._duration(total if total is not None else seconds)
        if mode not in ("专注", "休息") or seconds > total:
            raise ValueError("无效的计时模式或剩余时长")
        with self._lock:
            if self._closed:
                raise RuntimeError("计时服务已停止")
            self._cancel()
            self._initialized = True
            self._remaining, self._total, self._mode = seconds, total, mode
            self._deadline = self._clock() + seconds if running else None
            if running:
                self._timer = self._factory(seconds, self._finish, args=(self._generation,))
                self._timer.daemon = True
                self._timer.start()
            return self.snapshot()

    def pause(self):
        with self._lock:
            self._remaining = self._left()
            if self._deadline is not None and self._remaining <= 0:
                generation = self._generation
            else:
                self._cancel()
                self._deadline = None
                return self.snapshot()
        self._finish(generation)
        return self.snapshot()

    def _finish(self, generation):
        with self._lock:
            if self._closed or generation != self._generation or self._deadline is None:
                return
            self._remaining, self._deadline, self._timer = 0, None, None
            mode, total = self._mode, self._total
        self._complete(mode, total, generation)

    def close(self):
        with self._lock:
            self._closed = True
            self._remaining = self._left()
            self._cancel()
            self._deadline = None
