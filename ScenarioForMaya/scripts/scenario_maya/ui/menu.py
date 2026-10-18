"""The Scenario menu in Maya's main menu bar (GUI sessions only).

Built again each time it opens, so Sign in and Sign out always match the
current state.
"""

from __future__ import annotations

from maya import cmds, mel

from ..core import links

MENU = "ScenarioMainMenu"


def install() -> None:
    remove()
    main_window = mel.eval("$scnTmp = $gMainWindow")
    cmds.menu(MENU, parent=main_window, label="Scenario", tearOff=True, postMenuCommand=_build)
    _build()


def remove() -> None:
    if cmds.menu(MENU, exists=True):
        cmds.deleteUI(MENU, menu=True)


def _call(path: str, name: str, *args, **kwargs):
    def run(*_ignored):
        import importlib

        getattr(importlib.import_module(path), name)(*args, **kwargs)

    return run


def _build(*_args) -> None:
    from ..maya import runtime

    cmds.menu(MENU, edit=True, deleteAllItems=True)
    instance = runtime.current()
    signed_in = bool(instance and instance.session.signed_in)
    cmds.setParent(MENU, menu=True)
    cmds.menuItem(label="Scenario Panel", annotation="Open or focus the Scenario panel.", command=_call("scenario_maya.ui.panel", "show"))
    cmds.menuItem(label="Jobs", annotation="Show your Scenario jobs.", command=_call("scenario_maya.ui.panel", "show", page="jobs"))
    cmds.menuItem(divider=True)
    if signed_in:
        cmds.menuItem(label="Workspace...", annotation="Choose the Scenario team and project to work in.", command=_call("scenario_maya.ui.panel", "choose_workspace"))
        cmds.menuItem(label="Sign Out", annotation="Sign out of Scenario on this computer.", command=_call("scenario_maya.ui.panel", "sign_out"))
    else:
        cmds.menuItem(label="Sign In...", annotation="Sign in to Scenario.", command=_call("scenario_maya.ui.panel", "show"))
    cmds.menuItem(divider=True)
    cmds.menuItem(label="Help", subMenu=True, tearOff=False)
    cmds.menuItem(label="Handbook", annotation="Open the Scenario for Maya handbook.", command=_call("scenario_maya.ui.common", "open_url", links.HANDBOOK))
    cmds.menuItem(label="Privacy", annotation="What Scenario for Maya sends and stores.", command=_call("scenario_maya.ui.common", "open_url", links.PRIVACY))
    cmds.menuItem(label="Report a Problem", annotation="Open an issue on GitHub.", command=_call("scenario_maya.ui.common", "open_url", links.ISSUES))
    cmds.menuItem(label="Copy Diagnostics", annotation="Copy versions, paths and state (no secrets) for a bug report.", command=_call("scenario_maya.ui.panel", "copy_diagnostics"))
    cmds.menuItem(label="About Scenario for Maya", command=_call("scenario_maya.ui.panel", "about"))
    cmds.setParent("..", menu=True)
