"""Small helpers shared by the panel and dialogs."""

from __future__ import annotations

from ..core import errors
from .qt import QtCore, QtGui, QtWidgets, dpi

TONE_COLORS = {"ok": "#6dbb73", "warning": "#e3a33b", "error": "#e2705f"}


def error_text(error: BaseException) -> str:
    """The user-facing sentence for an error: message, then the hint when there is one."""
    if isinstance(error, errors.ScenarioError):
        return f"{error.message} {error.hint}".strip()
    if isinstance(error, TimeoutError):
        return "Timed out waiting for Scenario."
    return f"Something went wrong: {type(error).__name__}. Details are in the Scenario log."


def open_url(url: str) -> None:
    QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))


def copy_text(text: str) -> None:
    QtWidgets.QApplication.clipboard().setText(text)


def link_label(html: str, on_link, parent=None) -> QtWidgets.QLabel:
    """A label with ``<a href="...">`` links; ``on_link(href)`` handles them."""
    label = QtWidgets.QLabel(html, parent)
    label.setTextFormat(QtCore.Qt.TextFormat.RichText)
    label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.LinksAccessibleByMouse | QtCore.Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
    label.setOpenExternalLinks(False)
    label.linkActivated.connect(on_link)
    label.setWordWrap(True)
    return label


def message_label(parent=None) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel("", parent)
    label.setWordWrap(True)
    label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
    label.hide()
    return label


def show_message(label: QtWidgets.QLabel, text: str, tone: str = "") -> None:
    color = TONE_COLORS.get(tone)
    label.setStyleSheet(f"color: {color};" if color else "")
    label.setText(text)
    label.setVisible(bool(text))


def heading(text: str, scale: float = 1.25, parent=None) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text, parent)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * scale)
    font.setBold(True)
    label.setFont(font)
    return label


def spacing(value: float) -> int:
    return dpi(value)
