"""Stills of the scene to send as model inputs (spec 6.13, 10.1). Main thread only.

A capture is a one-frame playblast of the viewport people look through, as a
JPEG under ``images/scenario/captures``. In the GUI the grid, the heads-up
display and the selection highlight are hidden for the capture and restored
after; headless, Maya plays back the default perspective camera. A playblast
is an undo step of its own in Maya, so undo recording is paused around it
(and only when it was on): the capture never takes the place of the user's
last step in the undo queue.
"""

from __future__ import annotations

import os
import time

from maya import cmds

from . import scene

LONG_SIDE = 1024


def captures_folder() -> str:
    root = scene.project_root()
    try:
        images = cmds.workspace(fileRuleEntry="images") or "images"
    except RuntimeError:
        images = "images"
    return os.path.join(root, images, "scenario", "captures")


def _panel_size(panel: str) -> tuple:
    """The viewport's aspect, scaled so its long side is ``LONG_SIDE`` pixels."""
    width = height = 0
    try:
        width = cmds.control(panel, query=True, width=True)
        height = cmds.control(panel, query=True, height=True)
    except RuntimeError:
        pass
    if not width or not height:
        return (LONG_SIDE, LONG_SIDE)
    scale = LONG_SIDE / max(width, height)
    return (max(64, int(width * scale)) // 2 * 2, max(64, int(height * scale)) // 2 * 2)


def capture_viewport(folder: str = "", name: str = "") -> dict:
    """Writes a JPEG of the active viewport and returns ``{path, camera, width, height}``."""
    folder = folder or captures_folder()
    os.makedirs(folder, exist_ok=True)
    panel = scene.model_panel()
    camera, _shape = scene.active_camera()
    stem = name or f"viewport_{scene.short(camera)}_{time.strftime('%Y%m%d_%H%M%S')}"
    path = os.path.join(folder, stem + ".jpg")
    index = 1
    while os.path.exists(path):
        index += 1
        path = os.path.join(folder, f"{stem}_{index}.jpg")
    width, height = _panel_size(panel) if panel else (LONG_SIDE, LONG_SIDE)
    view = {}
    if panel:
        view = {key: cmds.modelEditor(panel, query=True, **{key: True}) for key in ("grid", "selectionHiliteDisplay", "headsUpDisplay")}
        cmds.modelEditor(panel, edit=True, grid=False, selectionHiliteDisplay=False, headsUpDisplay=False)
    recording = cmds.undoInfo(query=True, state=True)
    if recording:
        cmds.undoInfo(stateWithoutFlush=False)
    try:
        options = dict(frame=[cmds.currentTime(query=True)], format="image", compression="jpg", quality=95, offScreen=True, viewer=False, showOrnaments=False, percent=100)
        if panel:
            options["editorPanelName"] = panel
        cmds.playblast(completeFilename=path, forceOverwrite=True, widthHeight=(width, height), **options)
    finally:
        if recording:
            cmds.undoInfo(stateWithoutFlush=True)
        if panel and view:
            cmds.modelEditor(panel, edit=True, **view)
    if not os.path.exists(path):
        raise RuntimeError("Maya wrote no capture of the viewport.")
    return {"path": path, "camera": scene.short(camera), "width": width, "height": height}
