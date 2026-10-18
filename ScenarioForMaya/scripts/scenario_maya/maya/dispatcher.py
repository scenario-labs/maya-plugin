"""Main-thread dispatcher: workers do the network, Maya's main thread does the scene.

Maya commands and OpenMaya must run on the main thread. ``maya.utils.
executeDeferred`` never runs in ``mayapy``, and ``executeInMainThreadWithResult``
from a worker deadlocks unless the main thread pumps idle events, so neither is
used. Instead:

- ``run_in_worker(fn)`` runs ``fn`` on a small thread pool and returns a Future.
- ``call_on_main(fn)`` queues ``fn`` for the main thread and returns a Future
  (or runs it at once when already on the main thread).
- ``drain()`` runs queued calls on the main thread within a time slice. The GUI
  drives it with a ``QTimer``; ``mayapy`` drives it with ``pump()``.

The dispatcher measures every main-thread slice it runs so Diagnostics can
report the longest one (budget: 16 ms during polling and downloads).
"""

from __future__ import annotations

import concurrent.futures
import queue
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

MAIN_THREAD = threading.main_thread()


class Dispatcher:
    def __init__(self, workers: int = 4, slice_ms: float = 12.0) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scenario-worker")
        self._slice = slice_ms / 1000.0
        self._timer = None
        self._closed = False
        self.longest_slice_ms = 0.0
        self.longest_call = ("", 0.0)  # qualified name and ms of the slowest single call
        self.slices = 0
        self.errors: list = []

    # -- threads ---------------------------------------------------------

    @staticmethod
    def on_main_thread() -> bool:
        return threading.current_thread() is MAIN_THREAD

    def run_in_worker(self, fn: Callable, *args, **kwargs) -> concurrent.futures.Future:
        if self._closed:
            raise RuntimeError("Scenario dispatcher is stopped.")
        return self._pool.submit(fn, *args, **kwargs)

    def call_on_main(self, fn: Callable, *args, **kwargs) -> concurrent.futures.Future:
        future: concurrent.futures.Future = concurrent.futures.Future()
        if self.on_main_thread():
            self._run(future, fn, args, kwargs)
        else:
            self._queue.put((future, fn, args, kwargs))
        return future

    def then_on_main(self, future: concurrent.futures.Future, callback: Callable[[concurrent.futures.Future], Any]) -> None:
        """Runs ``callback(future)`` on the main thread once ``future`` is done."""
        future.add_done_callback(lambda done: self.call_on_main(callback, done))

    def background(self, fn: Callable, on_done: Callable[[Any], Any] | None = None, on_error: Callable[[BaseException], Any] | None = None) -> concurrent.futures.Future:
        """Worker call whose result or error is delivered on the main thread."""
        future = self.run_in_worker(fn)

        future._scenario_callback = on_done or on_error or fn  # type: ignore[attr-defined]

        def deliver(done: concurrent.futures.Future) -> None:
            error = done.exception()
            if error is not None:
                if on_error is not None:
                    on_error(error)
            elif on_done is not None:
                on_done(done.result())

        self.then_on_main(future, deliver)
        return future

    # -- main thread -----------------------------------------------------

    def _run(self, future, fn, args, kwargs) -> None:
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:  # noqa: BLE001 - delivered to the waiting side
            self.errors.append("".join(traceback.format_exception_only(type(error), error)).strip()[:300])
            del self.errors[:-20]
            future.set_exception(error)

    def drain(self, budget_s: float | None = None) -> int:
        """Runs queued main-thread calls until the queue is empty or the slice is used."""
        budget = self._slice if budget_s is None else budget_s
        start = time.perf_counter()
        count = 0
        while True:
            try:
                future, fn, args, kwargs = self._queue.get_nowait()
            except queue.Empty:
                break
            began = time.perf_counter()
            self._run(future, fn, args, kwargs)
            took = (time.perf_counter() - began) * 1000.0
            if took > self.longest_call[1]:
                self.longest_call = (_name(fn, args), took)
            count += 1
            if time.perf_counter() - start >= budget:
                break
        if count:
            elapsed = (time.perf_counter() - start) * 1000.0
            self.slices += 1
            self.longest_slice_ms = max(self.longest_slice_ms, elapsed)
        return count

    def reset_timing(self) -> None:
        self.longest_slice_ms, self.longest_call, self.slices = 0.0, ("", 0.0), 0

    def pending(self) -> int:
        return self._queue.qsize()

    def pump(self, until: Callable[[], bool] | None = None, timeout: float | None = None, interval: float = 0.01) -> bool:
        """Headless loop for ``mayapy``: drains until ``until()`` is true or ``timeout`` passes."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            self.drain(budget_s=0.05)
            if until is not None and until():
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            if self._closed:
                return False
            time.sleep(interval)

    def wait(self, future: concurrent.futures.Future, timeout: float | None = None) -> Any:
        """Waits for a future on the main thread while keeping the queue moving."""
        if not self.on_main_thread():
            return future.result(timeout)
        if not self.pump(until=future.done, timeout=timeout):
            raise TimeoutError("Timed out waiting for Scenario.")
        return future.result()

    # -- GUI timer -------------------------------------------------------

    def start_gui_timer(self, interval_ms: int = 30) -> None:
        from ..ui.qt import QtCore

        if self._timer is not None:
            return
        timer = QtCore.QTimer()
        timer.setInterval(interval_ms)
        timer.timeout.connect(self.drain)
        timer.start()
        self._timer = timer

    def stop(self) -> None:
        self._closed = True
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        self._pool.shutdown(wait=False, cancel_futures=True)
        while True:
            try:
                future, *_ = self._queue.get_nowait()
            except queue.Empty:
                break
            future.cancel()


def _name(fn: Callable, args: tuple) -> str:
    """``deliver`` wrappers name the callback they deliver to, which is what a slow slice is about."""
    target = fn
    if getattr(fn, "__name__", "") == "deliver" and args:
        target = getattr(args[0], "_scenario_callback", fn)
    return getattr(target, "__qualname__", None) or repr(target)[:80]
