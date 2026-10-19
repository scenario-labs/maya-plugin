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
from ..core.lanes import IMAGE, LANES
from .common import copy_text, error_text, message_label, open_url, show_message
from .jobs import JobsView
from .lane import LanePage
from .qt import QtCore, QtWidgets, dpi, isValid, maya_main_window
from .signin import SignInPage

CONTROL = "ScenarioPanelWorkspaceControl"
PLUGIN = "scenario_for_maya"
UI_SCRIPT = "import scenario_maya.ui.panel as _scn; _scn.restore()"
DOCK_BESIDE = "ChannelBoxLayerEditor"

LANE_TIPS = {
    "image": "Image lane: generate images, then land them as a card, a material or an image plane.",
    "3d": "3D lane: generate a 3D model from a prompt and import it as a textured group.",
}

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
        self.lanes = QtWidgets.QHBoxLayout()
        self.lanes.setSpacing(dpi(2))
        self.lane_buttons = QtWidgets.QButtonGroup(self)
        self.lane_button: dict = {}
        self.lane_pages: dict = {}
        self.lane_stack = QtWidgets.QStackedWidget()
        for lane in LANES:
            button = QtWidgets.QToolButton()
            button.setText(lane.label)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolTip(LANE_TIPS.get(lane.id, f"{lane.label} lane"))
            button.clicked.connect(lambda _=False, lane_id=lane.id: self.select_lane(lane_id))
            self.lane_buttons.addButton(button)
            self.lanes.addWidget(button)
            self.lane_button[lane.id] = button
            page = LanePage(runtime, lane)
            self.lane_pages[lane.id] = page
            self.lane_stack.addWidget(page)
        self.lanes.addStretch(1)
        self.lane = self.lane_pages[IMAGE.id]
        self.banner = QtWidgets.QFrame()
        self.banner.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.banner_text = QtWidgets.QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_button = QtWidgets.QPushButton("Download")
        self.banner_button.setToolTip("Download the results of jobs that finished while Maya was closed.")
        self.banner_button.clicked.connect(self._resume_downloads)
        banner_layout = QtWidgets.QHBoxLayout(self.banner)
        banner_layout.addWidget(self.banner_text, 1)
        banner_layout.addWidget(self.banner_button)
        self.banner.hide()
        self.jobs = JobsView(runtime)
        self.jobs.setMinimumHeight(dpi(150))
        jobs_title = QtWidgets.QLabel("Jobs")
        font = jobs_title.font()
        font.setBold(True)
        jobs_title.setFont(font)
        form = QtWidgets.QWidget()
        home_layout = QtWidgets.QVBoxLayout(form)
        home_layout.setContentsMargins(dpi(8), dpi(2), dpi(8), dpi(8))
        home_layout.setSpacing(dpi(6))
        home_layout.addLayout(self.lanes)
        home_layout.addWidget(self.banner)
        home_layout.addWidget(self.lane_stack)
        home_layout.addSpacing(dpi(6))
        home_layout.addWidget(jobs_title)
        home_layout.addWidget(self.jobs)
        home_layout.addStretch(1)
        home = QtWidgets.QScrollArea()
        home.setWidgetResizable(True)
        home.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        home.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        home.setWidget(form)
        self.home = home
        self._states: dict = {}

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
        self.select_lane(runtime.session.settings.get("lane") or IMAGE.id, save=False)
        self.refresh()
        QtCore.QTimer.singleShot(0, self.resume)

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

    def select_lane(self, lane_id: str, save: bool = True) -> None:
        page = self.lane_pages.get(lane_id) or self.lane_pages[IMAGE.id]
        for other in self.lane_pages.values():
            # A hidden page must not size the stack, or the shorter lane shows a gap.
            policy = QtWidgets.QSizePolicy.Policy.Preferred if other is page else QtWidgets.QSizePolicy.Policy.Ignored
            other.setSizePolicy(policy, policy)
        self.lane = page
        self.lane_stack.setCurrentWidget(page)
        self.lane_button[page.lane.id].setChecked(True)
        if save:
            self.runtime.session.settings.update(lane=page.lane.id)

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
            for page in self.lane_pages.values():
                page.refresh()
            self.resume()
        elif event == "job":
            row = data.get("row") or {}
            for page in self.lane_pages.values():
                page.on_job(data)
            if self._states.get(row.get("local_id")) != row.get("state"):
                self._states[row.get("local_id")] = row.get("state")
                self.jobs.refresh()
                self._update_banner()
        elif event in ("submitted", "not_confirmed", "jobs"):
            self.jobs.refresh()

    def resume(self) -> None:
        """Spec 7.4: jobs running on Scenario resume when the panel opens; downloads wait for a click."""
        if not self.runtime.session.signed_in or not self.runtime.session.workspace():
            return
        self.runtime.jobs.resume_polling()
        self._update_banner()

    def _update_banner(self) -> None:
        waiting = self.runtime.jobs.waiting_downloads() if self.runtime.session.signed_in else []
        if waiting:
            self.banner_text.setText(f"{len(waiting)} result(s) finished while Maya was closed or their download stopped.")
        self.banner.setVisible(bool(waiting))

    def _resume_downloads(self) -> None:
        self.runtime.jobs.resume_downloads()
        self.banner.hide()

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


def import_glb(path: str = "") -> dict | None:
    """Scenario > Import GLB...: any local GLB through the plug-in's builder (spec 6.7). No sign-in needed."""
    import os

    from maya.api import OpenMaya as om

    from ..core import naming
    from ..maya import landing, scene

    if not path:
        chosen = cmds.fileDialog2(fileFilter="glTF binary (*.glb)", dialogStyle=2, fileMode=1, caption="Import GLB")
        if not chosen:
            return None
        path = chosen[0]
    base = naming.slug(os.path.splitext(os.path.basename(path))[0])
    folder = naming.unique_folder(scene.folders()["images"], base)
    try:
        made = landing.land_model(path, {}, texture_folder=folder, label=base)
    except landing.LandingError as error:
        om.MGlobal.displayWarning(str(error))
        cmds.confirmDialog(title="Import GLB", message=str(error), button=["OK"])
        return None
    notes = made["checks"]["notes"]
    om.MGlobal.displayInfo(f"{made['summary']}. One Ctrl+Z removes it." + (f" Notes: {'; '.join(notes)}." if notes else ""))
    return made


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
