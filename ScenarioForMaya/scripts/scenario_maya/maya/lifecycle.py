"""Plug-in load and unload: version check, runtime, and the GUI entry points.

In batch and ``mayapy`` sessions no UI is built (Maya's UI commands quietly
return ``False`` there), only the runtime.
"""

from __future__ import annotations

import sys

from maya import cmds
from maya.api import OpenMaya as om

from . import compat, runtime

PLUGIN_NAME = "scenario_for_maya"
MIN_MAYA = 2025

_STATE = {"exiting": False, "callbacks": []}


def _on_exit(*_args) -> None:
    _STATE["exiting"] = True


def load() -> runtime.Runtime:
    major = int(str(cmds.about(majorVersion=True)) or 0)
    if major < MIN_MAYA:
        raise RuntimeError(f"Scenario for Maya needs Maya {MIN_MAYA} or later; this is Maya {major}.")
    gui = compat.is_gui()
    instance = runtime.start(gui=gui)
    _STATE["exiting"] = False
    _STATE["callbacks"].append(om.MSceneMessage.addCallback(om.MSceneMessage.kMayaExiting, _on_exit))
    if gui:
        from ..ui import commands, menu

        commands.install()
        menu.install()
    lost = instance.recovered.get("not_confirmed") or []
    if lost:
        om.MGlobal.displayWarning(f"Scenario: {len(lost)} request(s) were being sent when Maya last stopped. They show as Not confirmed in Jobs until you check them.")
    return instance


def unload() -> None:
    for callback in _STATE["callbacks"]:
        try:
            om.MMessage.removeCallback(callback)
        except RuntimeError:
            pass
    _STATE["callbacks"].clear()
    instance = runtime.current()
    try:
        if instance is not None and instance.gui:
            from ..ui import menu, panel

            menu.remove()
            panel.dispose(close_control=not _STATE["exiting"])
    finally:
        runtime.stop()


def purge_modules() -> None:
    """Forgets the package so the next load imports fresh code (reload during development)."""
    for name in [n for n in sys.modules if n == "scenario_maya" or n.startswith("scenario_maya.")]:
        del sys.modules[name]
