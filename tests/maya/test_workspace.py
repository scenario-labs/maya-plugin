"""The team and project picker, built offscreen in mayapy against the fake backend (0 CU)."""

import os
import threading
import time

import pytest

from tests.fake_backend import API_KEY, API_SECRET, PROJECT, TEAM
from tests.maya.conftest import MODULE, PLUGIN, fresh, pump_until, qt_pump_until


@pytest.fixture
def runtime(fake, monkeypatch, cmds):
    monkeypatch.setenv("SCENARIO_API_URL", fake.endpoint)
    cmds.loadPlugin(os.path.join(MODULE, "plug-ins", "scenario_for_maya.py"))
    runtime = fresh("scenario_maya.maya.runtime").get()
    signed = runtime.background(lambda: runtime.session.sign_in_api_key(API_KEY, API_SECRET))
    pump_until(signed.done)
    signed.result()
    yield runtime
    for dialog in pickers():
        dialog.close()
    if cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        cmds.unloadPlugin(PLUGIN)


class Gate:
    """Holds every teams load until opened, like a slow network, and counts the loads."""

    def __init__(self, load) -> None:
        self.opened = threading.Event()
        self.loads = 0
        self.fail = False
        self._load = load

    def __call__(self, backend):
        self.loads += 1
        self.opened.wait(10)
        if self.fail:
            self.fail = False
            raise RuntimeError("Scenario could not be reached.")
        return self._load(backend)


@pytest.fixture
def gate(runtime, monkeypatch):
    workspace = fresh("scenario_maya.ui.workspace")
    held = Gate(workspace.load)
    monkeypatch.setattr(workspace, "load", held)
    yield held
    held.opened.set()


@pytest.fixture
def chosen(runtime):
    """Each workspace set, as ``team/project``."""
    out = []
    unsubscribe = runtime.subscribe(lambda event, data: out.append(f"{data['team_id']}/{data['project_id']}") if event == "workspace" else None)
    yield out
    unsubscribe()


def pickers():
    from PySide6 import QtWidgets

    return [widget for widget in QtWidgets.QApplication.topLevelWidgets() if type(widget).__name__ == "WorkspaceDialog" and widget.isVisible()]


def settle(seconds=0.5):
    """Runs Qt events and the dispatcher a while: time for a second load or picker to show up."""
    deadline = time.monotonic() + seconds
    qt_pump_until(lambda: time.monotonic() >= deadline)


def test_clicks_during_the_load_open_one_picker(runtime, gate, chosen):
    workspace = fresh("scenario_maya.ui.workspace")
    workspace.choose(runtime, ask=True)
    workspace.choose(runtime, ask=True)
    gate.opened.set()
    qt_pump_until(pickers)
    settle()
    assert len(pickers()) == 1 and gate.loads == 1, "the second click joins the first load"
    pickers()[0].accept()
    settle()
    assert pickers() == [], "Use this project closes the only picker"
    assert chosen == [f"{TEAM['id']}/{PROJECT['id']}"]


def test_a_click_while_the_picker_is_open_keeps_one_picker(runtime, gate, chosen):
    workspace = fresh("scenario_maya.ui.workspace")
    gate.opened.set()
    workspace.choose(runtime, ask=True)
    qt_pump_until(pickers)
    picker = pickers()[0]
    workspace.choose(runtime, ask=True)
    settle()
    assert pickers() == [picker] and gate.loads == 1
    picker.reject()
    settle()
    assert pickers() == [] and chosen == []
    workspace.choose(runtime, ask=True)
    qt_pump_until(pickers)
    assert gate.loads == 2, "a closed picker opens again on the next click"


def test_a_click_during_the_automatic_pick_asks(runtime, gate, chosen):
    workspace = fresh("scenario_maya.ui.workspace")
    workspace.choose(runtime, ask=False)
    workspace.choose(runtime, ask=True)
    gate.opened.set()
    qt_pump_until(pickers)
    settle()
    assert len(pickers()) == 1 and gate.loads == 1
    assert chosen == [], "the one team and project is not picked without asking"


def test_a_failed_load_lets_the_next_click_try_again(runtime, gate):
    workspace = fresh("scenario_maya.ui.workspace")
    errors = []
    gate.fail = True
    gate.opened.set()
    workspace.choose(runtime, ask=True, on_error=errors.append)
    qt_pump_until(lambda: errors)
    workspace.choose(runtime, ask=True, on_error=errors.append)
    qt_pump_until(pickers)
    assert len(errors) == 1 and gate.loads == 2
