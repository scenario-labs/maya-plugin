"""The sign-in dialogs, built offscreen in mayapy (0 CU)."""

import os
import time

import pytest

from tests.maya.conftest import MODULE, PLUGIN, fresh, qt_pump_until


@pytest.fixture
def runtime(fake, monkeypatch, cmds):
    monkeypatch.setenv("SCENARIO_MCP_URL", fake.endpoint)
    cmds.loadPlugin(os.path.join(MODULE, "plug-ins", "scenario_for_maya.py"))
    yield fresh("scenario_maya.maya.runtime").get()
    if cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        cmds.unloadPlugin(PLUGIN)


def clipped(dialog):
    """Texts of the visible wrapped labels that are shorter than their lines need."""
    from PySide6 import QtWidgets

    QtWidgets.QApplication.processEvents()
    labels = [label for label in dialog.findChildren(QtWidgets.QLabel) if label.isVisible() and label.wordWrap()]
    return [label.text() for label in labels if label.height() < label.heightForWidth(label.width())]


def test_device_dialog_grows_to_the_instructions_and_errors(runtime):
    signin = fresh("scenario_maya.ui.signin")
    oauth = fresh("scenario_maya.core.oauth")
    dialog = signin.DeviceDialog(runtime)
    dialog.show()
    qt_pump_until(dialog.isVisible)
    dialog._show_code(oauth.DeviceCode("dc_test", "WXYZ-1234", "https://example.invalid/device", "", 1.0, time.time() + 60))
    assert dialog.where.heightForWidth(dialog.where.width()) > dialog.fontMetrics().lineSpacing() * 1.5, "the instructions wrap"
    assert clipped(dialog) == []
    dialog._failed(RuntimeError("test"))
    assert dialog.status.heightForWidth(dialog.status.width()) > dialog.fontMetrics().lineSpacing() * 1.5, "the error wraps"
    assert clipped(dialog) == []
    dialog.reject()
