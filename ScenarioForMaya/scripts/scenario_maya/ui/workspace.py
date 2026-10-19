"""Team and project picker (spec 4.10, step 3). The rules live in ``core.workspaces``."""

from __future__ import annotations

from ..core.workspaces import automatic_choice, load
from .qt import QtCore, QtWidgets


class WorkspaceDialog(QtWidgets.QDialog):
    def __init__(self, teams: list, team_id: str = "", project_id: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scenario workspace")
        self.teams = teams
        self.team_box = QtWidgets.QComboBox()
        self.project_box = QtWidgets.QComboBox()
        for team in teams:
            self.team_box.addItem(team.get("name") or team["id"], team["id"])
        index = max(0, self.team_box.findData(team_id))
        self.team_box.setCurrentIndex(index)
        self.team_box.currentIndexChanged.connect(self._fill_projects)
        self._fill_projects()
        found = self.project_box.findData(project_id)
        if found >= 0:
            self.project_box.setCurrentIndex(found)
        form = QtWidgets.QFormLayout()
        form.addRow("Team", self.team_box)
        form.addRow("Project", self.project_box)
        note = QtWidgets.QLabel("New jobs, results and library assets go to this project.")
        note.setWordWrap(True)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Use this project")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _fill_projects(self) -> None:
        self.project_box.clear()
        team = self.teams[self.team_box.currentIndex()] if self.teams else {}
        for project in team.get("projects") or []:
            self.project_box.addItem(project.get("name") or project["id"], project["id"])

    def choice(self):
        team = self.teams[self.team_box.currentIndex()]
        projects = team.get("projects") or []
        if not projects:
            return None
        project = projects[self.project_box.currentIndex()]
        return team, project


def choose(runtime, parent=None, *, ask: bool = False, on_done=None, on_error=None) -> None:
    """Loads teams on a worker, then picks automatically or asks.

    The question opens with ``open()``, not ``exec()``: this runs as a
    dispatcher callback, and a nested event loop there would hold the
    dispatcher until the user answers.
    """
    session = runtime.session

    def use(picked) -> None:
        team, project = picked
        session.set_workspace(team["id"], project["id"], team.get("name", ""), project.get("name", ""))
        if on_done:
            on_done()

    def apply(teams: list) -> None:
        settings = session.settings
        picked = None if ask else automatic_choice(teams, settings.get("team_id"), settings.get("project_id"))
        if picked is not None:
            use(picked)
            return
        if not teams:
            if on_error:
                on_error(RuntimeError("This account has no Scenario team."))
            return
        dialog = WorkspaceDialog(teams, settings.get("team_id"), settings.get("project_id"), parent)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)

        def finished(code: int) -> None:
            choice = dialog.choice() if code == QtWidgets.QDialog.DialogCode.Accepted.value else None
            if choice is not None:
                use(choice)

        dialog.finished.connect(finished)
        dialog.open()

    runtime.background(lambda: load(session.backend()), on_done=apply, on_error=on_error)
