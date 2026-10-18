"""Model picker (spec 4.3): search, team models, legacy, details, Use this model.

Opens at once from the cached catalog and refreshes it in the background
when it is older than a day (or on Refresh).
"""

from __future__ import annotations

from ..core.catalog import is_legacy
from ..core.lanes import Lane
from .common import error_text, message_label, show_message
from .qt import QtCore, QtWidgets, dpi


class ModelPicker(QtWidgets.QDialog):
    def __init__(self, runtime, lane: Lane, current: str = "", parent=None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.lane = lane
        self.chosen = ""
        self.setWindowTitle(f"Choose a model: {lane.label}")
        self.resize(dpi(640), dpi(440))
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search models...")
        self.search.setClearButtonEnabled(True)
        self.team = QtWidgets.QCheckBox("Team models")
        self.legacy = QtWidgets.QCheckBox("Show legacy")
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.setToolTip("Read the model list from Scenario again.")
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.team)
        top.addWidget(self.legacy)
        top.addWidget(self.refresh_button)
        self.list = QtWidgets.QListWidget()
        self.list.setUniformItemSizes(True)
        self.name = QtWidgets.QLabel()
        font = self.name.font()
        font.setBold(True)
        self.name.setFont(font)
        self.name.setWordWrap(True)
        self.details = QtWidgets.QLabel()
        self.details.setWordWrap(True)
        self.details.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.details.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        side = QtWidgets.QVBoxLayout()
        side.addWidget(self.name)
        side.addWidget(self.details, 1)
        side_box = QtWidgets.QWidget()
        side_box.setLayout(side)
        split = QtWidgets.QSplitter()
        split.addWidget(self.list)
        split.addWidget(side_box)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self.status = message_label()
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.use = self.buttons.addButton("Use this model", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.use.setEnabled(False)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(split, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        self.search.textChanged.connect(self.fill)
        self.team.toggled.connect(self.fill)
        self.legacy.toggled.connect(self.fill)
        self.list.currentItemChanged.connect(self._selected)
        self.list.itemDoubleClicked.connect(lambda *_: self._accept())
        self.refresh_button.clicked.connect(self.refresh)
        self._current = current
        self.fill()
        if not runtime.catalog.fresh(runtime.session.workspace()):
            self.refresh()

    def _workspace(self) -> str:
        return self.runtime.session.workspace()

    def refresh(self) -> None:
        show_message(self.status, "Loading models...")
        self.refresh_button.setEnabled(False)
        workspace = self._workspace()
        backend = self.runtime.session.backend()

        def done(_rows):
            self.refresh_button.setEnabled(True)
            show_message(self.status, "")
            self.fill()

        def failed(error):
            self.refresh_button.setEnabled(True)
            show_message(self.status, "Could not read the model list: " + error_text(error), "error")

        self.runtime.background(lambda: self.runtime.catalog.refresh(backend, workspace, modalities=(self.lane.modality,)), on_done=done, on_error=failed)

    def fill(self) -> None:
        rows = self.runtime.catalog.for_lane(self._workspace(), self.lane, text=self.search.text(), show_legacy=self.legacy.isChecked(), team_only=self.team.isChecked())
        self.list.clear()
        picks = set(self.lane.quick_picks)
        for row in rows:
            badges = [word for word, on in (("Quick pick", row["id"] in picks), ("Team", row.get("team")), ("Legacy", is_legacy(row))) if on]
            item = QtWidgets.QListWidgetItem(row.get("name") or row["id"])
            if badges:
                item.setText(f"{item.text()}    {' . '.join(badges)}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, row)
            item.setToolTip(row.get("shortDescription") or "")
            self.list.addItem(item)
            if row["id"] == self._current:
                self.list.setCurrentItem(item)
        if not rows and not self.status.isVisible():
            show_message(self.status, "No model matches." if self.search.text() else "No models yet; press Refresh.")
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)

    def _selected(self, item, _previous=None) -> None:
        row = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
        self.use.setEnabled(row is not None)
        if row is None:
            self.name.clear()
            self.details.clear()
            return
        self.name.setText(row.get("name") or row["id"])
        caps = ", ".join(row.get("capabilities") or ())
        self.details.setText(f"{row.get('shortDescription') or ''}\n\n{caps}\n{row['id']}")

    def _accept(self) -> None:
        item = self.list.currentItem()
        row = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
        if row is None:
            return
        self.chosen = row["id"]
        self.accept()
