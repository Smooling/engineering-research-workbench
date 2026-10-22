"""插件后台任务调度（PLUGIN_SPEC §6.2 ③ 的第一件能力，v261009.24）。

插件用 `ctx.jobs.add(name, callback, every_minutes=…)` 注册周期性任务，内核负责调度、
状态与日志——插件自己**不要**起线程（那样热重载后旧线程会变成幽灵，还可能并把内存越用越多）。

不变量与取舍：

- **I4 单任务失败不影响别的**：回调抛异常只记进该任务的状态（`last_error` / `failures`），调度继续。
- **同一任务不重入**：上一轮还没跑完就跳过这一轮——慢任务不会把自己堆成并发洪峰。
- **不阻塞调度线程**：每个任务在**自己的线程**里跑，卡住的任务既不拖住调度器，也不拖住其它任务。
- **不强制超时**：Python 无法安全中断线程，"超时"只能做到「状态可见 + 不重入」——
  需要强隔离的任务应该做成 `kind: "process"` 插件（那是另一件事，见 §6）。
- **热重载安全**：`loader.load` 每次重新装配，先停掉旧调度器再起新的；停用插件 → 它的任务立刻不再跑。
  停止是协作式的（最多等一个 tick），不做强杀。
- **进程退出兜底**：`shutdown()` 幂等，且注册 `atexit`。
"""

from __future__ import annotations

import atexit
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

#: 调度轮询间隔（秒）。任务的最小间隔也是它——秒级以下没有意义（桌面应用）。
TICK_SECONDS = 5.0
#: 每个插件允许注册的任务数上限（防手滑起几百个线程）
MAX_JOBS_PER_PLUGIN = 8


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Job:
    plugin_id: str
    name: str
    every_seconds: float
    callback: Callable[[], Any]
    run_on_start: bool = False
    running: bool = False
    runs: int = 0
    failures: int = 0
    next_due: float = 0.0
    last_started: str = ""
    last_finished: str = ""
    last_error: str = ""

    @property
    def key(self) -> str:
        return f"{self.plugin_id}:{self.name}"

    def as_dict(self) -> dict:
        return {
            "plugin": self.plugin_id, "name": self.name,
            "every_minutes": round(self.every_seconds / 60.0, 3),
            "run_on_start": self.run_on_start, "running": self.running,
            "runs": self.runs, "failures": self.failures,
            "last_started": self.last_started, "last_finished": self.last_finished,
            "last_error": self.last_error,
        }


class JobTable:
    """插件在 `register(ctx)` 期间看到的那一层（只接受自己命名空间内的注册）。"""

    def __init__(self, plugin_id: str, scheduler: "JobScheduler") -> None:
        self.plugin_id = plugin_id
        self._scheduler = scheduler
        self.names: list[str] = []

    def add(self, name: str, callback: Callable[[], Any], *, every_minutes: float = 30.0,
            run_on_start: bool = False) -> Job:
        raw = str(name or "").strip()
        if not raw:
            raise ValueError("任务名不能为空")
        if not callable(callback):
            raise ValueError(f"任务 {raw} 的 callback 不可调用")
        try:
            minutes = float(every_minutes)
        except (TypeError, ValueError):
            raise ValueError(f"任务 {raw} 的 every_minutes 必须是数字") from None
        if minutes <= 0:
            raise ValueError(f"任务 {raw} 的 every_minutes 必须 > 0（收到 {every_minutes!r}）")
        if len(self.names) >= MAX_JOBS_PER_PLUGIN:
            raise ValueError(f"插件 {self.plugin_id} 的任务数已达上限 {MAX_JOBS_PER_PLUGIN}")
        if raw in self.names:
            raise ValueError(f"任务 {raw} 重复注册")
        job = self._scheduler.register(self.plugin_id, raw, minutes * 60.0, callback, run_on_start)
        self.names.append(raw)
        return job

    def list(self) -> list[dict]:
        return [j.as_dict() for j in self._scheduler.jobs if j.plugin_id == self.plugin_id]


class JobScheduler:
    """一个进程内唯一的调度器；由 `loader.load` 装配，插件不直接持有它。"""

    def __init__(self, tick_seconds: float = TICK_SECONDS) -> None:
        self.tick_seconds = max(1.0, float(tick_seconds))
        self.jobs: list[Job] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self.started_at = ""

    # ---- 注册与查询 ----
    def register(self, plugin_id: str, name: str, every_seconds: float,
                 callback: Callable[[], Any], run_on_start: bool = False) -> Job:
        import time

        with self._lock:
            job = Job(plugin_id=plugin_id, name=name, every_seconds=every_seconds,
                      callback=callback, run_on_start=run_on_start)
            job.next_due = time.monotonic() + (0.0 if run_on_start else every_seconds)
            self.jobs.append(job)
            return job

    def as_list(self) -> list[dict]:
        with self._lock:
            return [j.as_dict() for j in self.jobs]

    def for_plugin(self, plugin_id: str) -> list[dict]:
        with self._lock:
            return [j.as_dict() for j in self.jobs if j.plugin_id == plugin_id]

    def summary(self) -> dict:
        with self._lock:
            return {
                "jobs": len(self.jobs),
                "running": sum(1 for j in self.jobs if j.running),
                "failures": sum(j.failures for j in self.jobs),
                "started_at": self.started_at,
                "tick_seconds": self.tick_seconds,
            }

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._thread is not None:
            return
        self.started_at = _now()
        self._thread = threading.Thread(target=self._loop, name="erw-plugin-jobs", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """协作式停止：置位并等一个短超时，**不强杀**正在跑的插件回调。"""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def run_now(self, plugin_id: str, name: str) -> dict:
        """手动触发一个任务（排障/面板「立即执行」用）。"""
        with self._lock:
            job = next((j for j in self.jobs if j.plugin_id == plugin_id and j.name == name), None)
        if job is None:
            return {"ok": False, "error": f"没有任务 {plugin_id}:{name}"}
        if job.running:
            return {"ok": False, "error": f"任务 {name} 正在运行中"}
        self._spawn(job)
        return {"ok": True, "job": job.as_dict()}

    # ---- 内部 ----
    def _loop(self) -> None:
        import time

        while not self._stop.is_set():
            try:
                now = time.monotonic()
                with self._lock:
                    due = [j for j in self.jobs if not j.running and now >= j.next_due]
                for job in due:
                    job.next_due = now + job.every_seconds   # 先推进时间：回调再慢也不会连点
                    self._spawn(job)
            except Exception:      # 调度器自身绝不能死掉
                pass
            self._stop.wait(self.tick_seconds)

    def _spawn(self, job: Job) -> None:
        job.running = True
        thread = threading.Thread(target=self._run, args=(job,),
                                  name=f"erw-job-{job.plugin_id}-{job.name}", daemon=True)
        thread.start()

    def _run(self, job: Job) -> None:
        import traceback

        job.last_started = _now()
        try:
            job.callback()
            job.runs += 1
            job.last_error = ""
        except Exception as exc:                      # I4：只记状态，不冒泡、不影响别的任务
            job.failures += 1
            job.last_error = f"{type(exc).__name__}: {exc}"
            print(f"[plugin-jobs] 任务 {job.key} 失败（调度继续）：{job.last_error}", flush=True)
            traceback.print_exc()
        finally:
            job.last_finished = _now()
            job.running = False


#: 进程内当前调度器（与 `runtime.py` 的 current LoadResult 同一思路）
_current: JobScheduler | None = None
_lock = threading.RLock()


def current() -> JobScheduler | None:
    return _current


def replace(tick_seconds: float = TICK_SECONDS) -> JobScheduler:
    """装配新一轮：**先停旧再建新**（热重载时旧插件的任务必须立刻停）。"""
    global _current
    with _lock:
        if _current is not None:
            _current.stop()
        _current = JobScheduler(tick_seconds=tick_seconds)
        return _current


def shutdown() -> None:
    """进程退出/测试收尾：停掉当前调度器（幂等）。"""
    global _current
    with _lock:
        if _current is not None:
            _current.stop()
            _current = None


atexit.register(shutdown)
