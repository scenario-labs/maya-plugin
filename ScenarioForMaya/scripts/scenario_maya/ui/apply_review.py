"""Apply review (spec 4.7): what an edit result will change on the mesh, before anything changes.

Three lists from ``maya.apply.compare``: what changes, what is kept, and what
the person has to accept (each a checkbox; Apply stays off until all are
ticked). A refused apply shows its reason and only Close. The dialog never
touches the scene; the page applies on Accept.
"""

from __future__ import annotations

from .common import heading
from .qt import QtWidgets, dpi


class ApplyReview(QtWidgets.QDialog):
    def __init__(self, review, parent=None) -> None:
        super().__init__(parent)
        self.review = review
        self.setWindowTitle(review.title)
        self.setMinimumWidth(dpi(440))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpi(6))
        layout.addWidget(heading(review.title))
        self.checks: list = []
        self.buttons = QtWidgets.QDialogButtonBox()
        if review.refusal:
            layout.addWidget(_wrapped(review.refusal))
            self.apply_button = None
            self.buttons.addButton(QtWidgets.QDialogButtonBox.StandardButton.Close)
            self.buttons.rejected.connect(self.reject)
        else:
            self._section(layout, "What changes", review.changes)
            self._section(layout, "What is kept", review.kept)
            if review.confirms:
                layout.addWidget(_bold("Please confirm"))
                for text in review.confirms:
                    box = QtWidgets.QCheckBox(text)
                    box.setStyleSheet("QCheckBox { padding-left: 2px; }")
                    box.toggled.connect(self._update)
                    self.checks.append(box)
                    layout.addWidget(box)
            note = _wrapped("One Ctrl+Z undoes the whole apply.")
            note.setEnabled(False)  # Maya greys disabled labels: secondary text
            layout.addWidget(note)
            self.apply_button = self.buttons.addButton("Apply", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
            self.buttons.addButton(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
            self.buttons.accepted.connect(self.accept)
            self.buttons.rejected.connect(self.reject)
            self._update()
        layout.addWidget(self.buttons)

    def _section(self, layout, title: str, lines: list) -> None:
        if not lines:
            return
        layout.addWidget(_bold(title))
        for line in lines:
            layout.addWidget(_wrapped("• " + line))

    def _update(self) -> None:
        if self.apply_button is not None:
            self.apply_button.setEnabled(all(box.isChecked() for box in self.checks))

    def confirm_all(self) -> None:
        """Ticks every confirmation (tests and agents with an explicit approval)."""
        for box in self.checks:
            box.setChecked(True)


def _wrapped(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    return label


def _bold(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label
