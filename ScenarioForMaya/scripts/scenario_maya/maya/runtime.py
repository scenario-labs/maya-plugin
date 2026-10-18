"""One Scenario runtime per Maya process: settings, ledger, session and dispatcher.

Created when the plug-in loads and closed when it unloads. UI and agent code
read it through ``get()``. Session events (sign-in, workspace, submissions)
arrive on any thread; ``subscribe`` delivers them on Maya's main thread.
"""

from __future__ import annotations

from collections.abc import Callable

from ..core import http, log
from ..core.ledger import Ledger
from ..core.session import Session
from ..core.settings import Settings
from . import compat
from .dispatcher import Dispatcher

_RUNTIME: Runtime | None = None


class Runtime:
    def __init__(self, gui: bool, host: str = "", session: Session | None = None) -> None:
        self.gui = gui
        self.log_path = log.configure()
        http.set_host(host or compat.host_label())
        self.dispatcher = Dispatcher()
        if session is None:
            settings = Settings()
            ledger = Ledger()
            session = Session(settings=settings, ledger=ledger)
        self.session = session
        self.settings = session.settings
        self.ledger = session.ledger
        self.recovered = self.ledger.recover()
        self.session.load()
        self._subscribers: list = []
        self.session.listeners.append(self._forward)
        if gui:
            self.dispatcher.start_gui_timer()
        log.LOGGER.info("runtime started (%s, gui=%s, recovered=%s)", http.user_agent(), gui, {k: len(v) for k, v in self.recovered.items()})

    # -- events ----------------------------------------------------------

    def subscribe(self, callback: Callable[[str, dict], None]) -> Callable[[], None]:
        """``callback(event, data)`` runs on the main thread. Returns the unsubscribe function."""
        self._subscribers.append(callback)
        return lambda: self._subscribers.remove(callback) if callback in self._subscribers else None

    def _forward(self, event: str, data: dict) -> None:
        self.dispatcher.call_on_main(self.emit, event, **data)

    def emit(self, event: str, **data) -> None:
        for callback in list(self._subscribers):
            try:
                callback(event, data)
            except Exception:  # noqa: BLE001 - one broken view never stops the others
                log.LOGGER.exception("subscriber failed on %s", event)

    # -- work ------------------------------------------------------------

    def background(self, fn, on_done=None, on_error=None):
        return self.dispatcher.background(fn, on_done, on_error)

    def close(self) -> None:
        if self._forward in self.session.listeners:
            self.session.listeners.remove(self._forward)
        self._subscribers.clear()
        self.dispatcher.stop()
        self.ledger.close()
        log.LOGGER.info("runtime stopped")
        log.close()


def start(gui: bool, **kwargs) -> Runtime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = Runtime(gui, **kwargs)
    return _RUNTIME


def current() -> Runtime | None:
    return _RUNTIME


def get() -> Runtime:
    if _RUNTIME is None:
        raise RuntimeError("Scenario for Maya is not loaded. Load scenario_for_maya in the Plug-in Manager.")
    return _RUNTIME


def stop() -> None:
    global _RUNTIME
    runtime, _RUNTIME = _RUNTIME, None
    if runtime is not None:
        runtime.close()
