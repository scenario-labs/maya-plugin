"""Jobs list (spec 4.6): the durable ledger rows of this workspace, newest first."""

from __future__ import annotations

from ..core.jsonutil import cu_display
from ..core.status import status_tone, status_word
from .common import TONE_COLORS, copy_text
from .qt import QtCore, QtGui, QtWidgets

COLUMNS = ("State", "Model", "Prompt / input", "Quoted", "Charged")
NOT_CONFIRMED_TEXT = "Scenario may or may not have received this request. An identical one stays blocked until you check."


def _cu(value: str | None) -> str:
    if value in (None, ""):
        return "·"
    try:
        return cu_display(str(value)).replace(" CU", "")
    except Exception:  # noqa: BLE001 - a malformed value is shown as is
        return str(value)


def row_texts(row: dict) -> list:
    params = row.get("params") or {}
    prompt = row.get("label") or params.get("prompt") or row.get("target") or ""
    return [status_word(row), row.get("target_name") or row.get("target_id") or "", str(prompt), _cu(row.get("cost_exact")), _cu(row.get("charged_exact"))]


class JobsView(QtWidgets.QWidget):
    def __init__(self, runtime, parent=None, limit: int = 50) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.limit = limit
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(list(COLUMNS))
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column in (0, 1, 3, 4):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.empty = QtWidgets.QLabel("No jobs yet.")
        self.empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)
        layout.addWidget(self.empty)
        self.rows: list = []
        self.refresh()

    def refresh(self) -> None:
        session = self.runtime.session
        workspace = session.workspace() if session.signed_in else None
        self.rows = self.runtime.ledger.list(limit=self.limit, workspace=workspace) if workspace else []
        self.tree.clear()
        for row in self.rows:
            item = QtWidgets.QTreeWidgetItem(row_texts(row))
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, row["local_id"])
            color = TONE_COLORS.get(status_tone(row))
            if color:
                item.setForeground(0, QtGui.QBrush(QtGui.QColor(color)))
            tip = " ".join(part for part in (row.get("error"), row.get("hint")) if part)
            if row["state"] == "uncertain" and not row.get("reviewed"):
                tip = NOT_CONFIRMED_TEXT + (" " + tip if tip else "")
            if tip:
                for column in range(len(COLUMNS)):
                    item.setToolTip(column, tip)
            self.tree.addTopLevelItem(item)
            if row["state"] == "uncertain" and not row.get("reviewed"):
                note = QtWidgets.QTreeWidgetItem([NOT_CONFIRMED_TEXT])
                note.setFirstColumnSpanned(True)
                note.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
                item.addChild(note)
                item.setExpanded(True)
        self.tree.setVisible(bool(self.rows))
        self.empty.setVisible(not self.rows)

    def _menu(self, point) -> None:
        item = self.tree.itemAt(point)
        local_id = item.data(0, QtCore.Qt.ItemDataRole.UserRole) if item else None
        row = next((r for r in self.rows if r["local_id"] == local_id), None)
        if row is None:
            return
        menu = QtWidgets.QMenu(self)
        menu.addAction("Copy details", lambda: copy_text(self.details(row)))
        menu.exec(self.tree.viewport().mapToGlobal(point))

    def details(self, row: dict) -> str:
        lines = [
            f"Local job: {row['local_id']}",
            f"State: {status_word(row)} ({row['state']})",
            f"Model: {row.get('target_name') or row.get('target_id')}",
            f"Scenario job: {row.get('remote_job_id') or '-'}",
            f"Quoted: {row.get('cost_exact') or '-'} CU, charged: {row.get('charged_exact') or '-'} CU",
            f"Created: {row.get('created_utc')} UTC",
        ]
        if row.get("error"):
            lines.append(f"Error: {row['error']}")
        if row.get("hint"):
            lines.append(f"Hint: {row['hint']}")
        return "\n".join(lines)
