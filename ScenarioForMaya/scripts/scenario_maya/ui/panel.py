"""The Scenario panel: a dockable ``workspaceControl`` that restores with the layout (spec 4.2).

The control's ``uiScript`` is a one-line import that calls ``restore()`` and
its ``requiredPlugin`` is this plug-in, so Maya loads the plug-in before
rebuilding the panel at startup.
"""

from __future__ import annotations

from maya import OpenMayaUI as omui1
from maya import cmds
from shiboken6 import getCppPointer

from .. import __version__
from ..core import diagnostics, links
from .common import copy_text, error_text, message_label, open_url, show_message
from .jobs import JobsView
from .qt import QtCore, QtWidgets, dpi, isValid, maya_main_window
from .signin import SignInPage

CONTROL = "ScenarioPanelWorkspaceControl"
PLUGIN = "scenario_for_maya"
UI_SCRIPT = "import scenario_maya.ui.panel as _scn; _scn.restore()"
DOCK_BESIDE = "ChannelBoxLayerEditor"

_PANEL: ScenarioPanel | None = None


def _runtime():
    from ..maya import runtime

    return runtime.current()


class ScenarioPanel(QtWidgets.QWidget):
    def __init__(self, runtime, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ScenarioPanel")
        self.runtime = runtime

        self.workspace_button = QtWidgets.QToolButton()
        self.workspace_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.workspace_button.setAutoRaise(True)
        self.workspace_button.setToolTip("Choose the Scenario team and project to work in.")
        self.workspace_button.clicked.connect(lambda: choose_workspace(ask=True))
        self.menu_button = QtWidgets.QToolButton()
        self.menu_button.setText("☰")
        self.menu_button.setAutoRaise(True)
        self.menu_button.setToolTip("Account, diagnostics and help.")
        self.menu_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_button.setMenu(self._build_menu())
        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(dpi(6), dpi(4), dpi(4), dpi(4))
        header.addWidget(self.workspace_button)
        header.addStretch(1)
        header.addWidget(self.menu_button)
        self.header = QtWidgets.QWidget()
        self.header.setLayout(header)

        self.message = message_label()
        self.signin = SignInPage(runtime)
        self.signin.signed_in.connect(self._after_sign_in)
        self.jobs = JobsView(runtime)
        jobs_title = QtWidgets.QLabel("Jobs")
        font = jobs_title.font()
        font.setBold(True)
        jobs_title.setFont(font)
        home = QtWidgets.QWidget()
        home_layout = QtWidgets.QVBoxLayout(home)
        home_layout.setContentsMargins(dpi(6), 0, dpi(6), dpi(6))
        home_layout.addWidget(jobs_title)
        home_layout.addWidget(self.jobs, 1)
        self.home = home

        self.pages = QtWidgets.QStackedWidget()
        self.pages.addWidget(self.signin)
        self.pages.addWidget(self.home)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.message)
        layout.addWidget(self.pages, 1)
        self._unsubscribe = runtime.subscribe(self._on_event)
        self.destroyed.connect(lambda *_: self._detach())
        self.refresh()

    # -- state -----------------------------------------------------------

    def _build_menu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)
        self.action_workspace = menu.addAction("Workspace...", lambda: choose_workspace(ask=True))
        menu.addAction("Refresh jobs", lambda: self.jobs.refresh())
        menu.addAction("Copy diagnostics", copy_diagnostics)
        menu.addSeparator()
        menu.addAction("Handbook", lambda: open_url(links.HANDBOOK))
        menu.addAction("Privacy", lambda: open_url(links.PRIVACY))
        menu.addAction("Report a problem", lambda: open_url(links.ISSUES))
        menu.addSeparator()
        self.action_sign_out = menu.addAction("Sign out", sign_out)
        return menu

    def refresh(self) -> None:
        session = self.runtime.session
        signed_in = session.signed_in
        self.pages.setCurrentWidget(self.home if signed_in else self.signin)
        self.workspace_button.setVisible(signed_in)
        self.action_workspace.setEnabled(signed_in)
        self.action_sign_out.setEnabled(signed_in)
        if signed_in:
            team = session.settings.get("team_name") or ""
            project = session.settings.get("project_name") or ""
            label = f"{team} / {project}" if team or project else "Choose a project"
            self.workspace_button.setText(label + "  ▾")
        self.jobs.refresh()

    def show_page(self, page: str | None) -> None:
        if page == "jobs" and self.runtime.session.signed_in:
            self.pages.setCurrentWidget(self.home)

    def _after_sign_in(self) -> None:
        self.refresh()
        choose_workspace(ask=False)

    def _on_event(self, event: str, data: dict) -> None:
        if event in ("signed_in", "signed_out", "workspace"):
            show_message(self.message, "")
            self.refresh()
        elif event in ("submitted", "not_confirmed", "jobs"):
            self.jobs.refresh()

    def show_error(self, error: BaseException) -> None:
        show_message(self.message, error_text(error), "error")

    def _detach(self) -> None:
        unsubscribe, self._unsubscribe = getattr(self, "_unsubscribe", None), None
        if unsubscribe:
            unsubscribe()


class _Unavailable(QtWidgets.QLabel):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setWordWrap(True)
        self.setMargin(dpi(12))


# -- control management --------------------------------------------------


def restore() -> None:
    """Called by Maya through ``uiScript`` (creation and layout restore): builds the panel inside the control."""
    global _PANEL
    parent = omui1.MQtUtil.getCurrentParent()
    runtime = _runtime()
    widget = ScenarioPanel(runtime) if runtime is not None else _Unavailable("Scenario for Maya is not loaded. Load scenario_for_maya in Windows > Settings/Preferences > Plug-in Manager.")
    omui1.MQtUtil.addWidgetToMayaLayout(int(getCppPointer(widget)[0]), int(parent))
    if isinstance(widget, ScenarioPanel):
        _PANEL = widget


def current() -> ScenarioPanel | None:
    return _PANEL if _PANEL is not None and isValid(_PANEL) else None


def show(page: str | None = None) -> ScenarioPanel | None:
    if cmds.workspaceControl(CONTROL, exists=True):
        cmds.workspaceControl(CONTROL, edit=True, restore=True)
        cmds.workspaceControl(CONTROL, edit=True, visible=True)
    else:
        options = dict(label="Scenario", uiScript=UI_SCRIPT, requiredPlugin=PLUGIN, retain=False, loadImmediately=True, initialWidth=dpi(380), minimumWidth=dpi(300))
        if cmds.workspaceControl(DOCK_BESIDE, exists=True):
            options["tabToControl"] = (DOCK_BESIDE, -1)
        else:
            options["floating"] = True
        cmds.workspaceControl(CONTROL, **options)
    # A new tab beside the Channel Box is added behind it: bring it to the front.
    cmds.workspaceControl(CONTROL, edit=True, r=True)
    panel = current()
    if panel is None:
        # Some Maya versions defer the uiScript until the control is shown.
        cmds.setParent(CONTROL)
        restore()
        panel = current()
    if panel is not None:
        panel.show_page(page)
        panel.raise_()
    return panel


def dispose(close_control: bool = True) -> None:
    """Plug-in unload: drop the widget and, unless Maya is quitting, close the control."""
    global _PANEL
    panel, _PANEL = current(), None
    if panel is not None:
        panel._detach()
        panel.setParent(None)
        panel.deleteLater()
    if close_control and cmds.workspaceControl(CONTROL, exists=True):
        cmds.workspaceControl(CONTROL, edit=True, close=True)


# -- menu actions --------------------------------------------------------


def choose_workspace(ask: bool = True) -> None:
    from . import workspace

    runtime = _runtime()
    if runtime is None:
        return
    panel = current()
    parent = panel or maya_main_window()
    workspace.choose(runtime, parent, ask=ask, on_error=(panel.show_error if panel else None))


def sign_out() -> None:
    runtime = _runtime()
    if runtime is None or not runtime.session.signed_in:
        return
    answer = QtWidgets.QMessageBox.question(
        current() or maya_main_window(),
        "Sign out of Scenario",
        "Sign out of Scenario on this computer? Jobs already sent keep running on Scenario.",
    )
    if answer != QtWidgets.QMessageBox.StandardButton.Yes:
        return
    panel = current()
    runtime.background(runtime.session.sign_out, on_error=(panel.show_error if panel else None))


def copy_diagnostics() -> None:
    runtime = _runtime()
    text = diagnostics.report(runtime.session, runtime.dispatcher, {"Maya": cmds.about(version=True)}) if runtime else diagnostics.report()
    copy_text(text)
    cmds.inViewMessage(assistMessage="Scenario diagnostics copied (no secrets).", position="topCenter", fade=True)


def about() -> None:
    QtWidgets.QMessageBox.about(
        current() or maya_main_window(),
        "About Scenario for Maya",
        f"Scenario for Maya {__version__}\n\nEvery Scenario model, inside Maya.\nMIT License.",
    )
