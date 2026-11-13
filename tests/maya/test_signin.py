"""The sign-in dialogs, built offscreen in mayapy (0 CU)."""

import os
import threading
import time

import pytest

from tests.maya.conftest import MODULE, PLUGIN, fresh, qt_pump_until


@pytest.fixture
def runtime(fake, monkeypatch, cmds):
    monkeypatch.setenv("SCENARIO_API_URL", fake.endpoint)
    cmds.loadPlugin(os.path.join(MODULE, "plug-ins", "scenario_for_maya.py"))
    yield fresh("scenario_maya.maya.runtime").get()
    if cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        cmds.unloadPlugin(PLUGIN)


def clipped(dialog):
    """The visible widgets shorter than they need: a wrapped label its lines, any other widget its minimum size.

    A dialog too short for a wrapped text cuts the text or, when it can, squeezes the fields around it.
    """
    from PySide6 import QtWidgets

    QtWidgets.QApplication.processEvents()
    out = []
    for widget in dialog.findChildren(QtWidgets.QWidget):
        if widget.parentWidget() is not dialog or not widget.isVisible():
            continue
        need = widget.heightForWidth(widget.width()) if widget.hasHeightForWidth() else widget.minimumSizeHint().height()
        if widget.height() < need:
            out.append(widget.text() if isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton)) else type(widget).__name__)
    return out


def tls_error():
    """A real error long enough to wrap in either dialog on any font: the one a TLS-inspecting proxy causes."""
    errors = fresh("scenario_maya.core.errors")
    return errors.NetworkError(
        "The TLS certificate of Scenario could not be verified.",
        hint="A proxy may be inspecting TLS; its root certificate must be in the system trust store.",
    )


def test_device_dialog_grows_to_the_instructions_and_errors(runtime):
    signin = fresh("scenario_maya.ui.signin")
    oauth = fresh("scenario_maya.core.oauth")
    dialog = signin.DeviceDialog(runtime)
    dialog.show()
    qt_pump_until(dialog.isVisible)
    dialog._show_code(oauth.DeviceCode("dc_test", "WXYZ-1234", "https://example.invalid/device", "", 1.0, time.time() + 60))
    assert dialog.where.heightForWidth(dialog.where.width()) > dialog.fontMetrics().lineSpacing() * 1.5, "the instructions wrap"
    assert clipped(dialog) == []
    dialog._failed(tls_error())
    assert dialog.status.heightForWidth(dialog.status.width()) > dialog.fontMetrics().lineSpacing() * 1.5, "the error wraps"
    assert clipped(dialog) == []
    dialog.reject()


def test_api_key_dialog_grows_to_a_long_error(runtime, monkeypatch):
    from PySide6 import QtWidgets

    signin = fresh("scenario_maya.ui.signin")
    common = fresh("scenario_maya.ui.common")
    error = tls_error()
    answer = threading.Event()

    def refuse(key_id, secret):
        answer.wait(10)  # like the network: the dialog settles on its one-line "Checking..." first
        raise error

    monkeypatch.setattr(runtime.session, "sign_in_api_key", refuse)
    dialog = signin.ApiKeyDialog(runtime)
    dialog.show()
    qt_pump_until(dialog.isVisible)
    dialog.key.setText("api_test")
    dialog.secret.setText("secret_test")
    try:
        dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).click()
        qt_pump_until(dialog.status.isVisible)
        QtWidgets.QApplication.processEvents()
    finally:
        answer.set()
    qt_pump_until(lambda: dialog.buttons.isEnabled() and dialog.status.text() == common.error_text(error))
    assert dialog.status.heightForWidth(dialog.status.width()) > dialog.fontMetrics().lineSpacing() * 1.5, "the error wraps"
    assert clipped(dialog) == []
    dialog.reject()
