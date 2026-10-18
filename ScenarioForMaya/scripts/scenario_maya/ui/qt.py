"""Qt imports and Maya window helpers. PySide6 only (Maya 2025 and later)."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
from shiboken6 import isValid, wrapInstance  # noqa: F401


def maya_main_window() -> QtWidgets.QWidget | None:
    from maya import OpenMayaUI as omui1

    pointer = omui1.MQtUtil.mainWindow()
    return wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None


def dpi(value: float) -> int:
    """Scales a size in pixels by Maya's UI scale."""
    try:
        from maya import OpenMayaUI as omui1

        return int(round(value * omui1.MQtUtil.dpiScale(1.0)))
    except Exception:  # noqa: BLE001
        return int(value)


def widget_for(name: str) -> QtWidgets.QWidget | None:
    """The Qt widget behind a Maya UI element name (control or layout)."""
    from maya import OpenMayaUI as omui1

    pointer = omui1.MQtUtil.findControl(name) or omui1.MQtUtil.findLayout(name)
    return wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None


def active_modal() -> bool:
    app = QtWidgets.QApplication.instance()
    return bool(app is not None and isinstance(app, QtWidgets.QApplication) and app.activeModalWidget() is not None)
