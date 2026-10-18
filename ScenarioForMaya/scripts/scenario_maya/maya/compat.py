"""The few places where Maya versions or session kinds differ."""

from __future__ import annotations

from maya import cmds
from maya.api import OpenMaya as om


def maya_version() -> str:
    """``"2027.2"``: major version from ``about``, update from the API version number."""
    major = str(cmds.about(majorVersion=True)) if hasattr(cmds, "about") else ""
    try:
        api = int(cmds.about(apiVersion=True))
        minor = (api // 100) % 100
        return f"{major}.{minor}" if minor else major
    except (TypeError, ValueError):
        return major


def is_gui() -> bool:
    return om.MGlobal.mayaState() == om.MGlobal.kInteractive


def is_creative() -> bool:
    try:
        return bool(cmds.about(creativeVersion=True))
    except (TypeError, RuntimeError):
        return False


def host_label() -> str:
    return f"Maya {maya_version()}"
