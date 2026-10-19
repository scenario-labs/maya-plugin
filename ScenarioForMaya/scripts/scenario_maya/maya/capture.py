"""Stills of the scene to send as model inputs (spec 6.13, 10.1). Main thread only.

A capture is a one-frame playblast of the viewport people look through, as a
JPEG under ``images/scenario/captures``; ``capture_views`` renders the
selection from named sides with temporary cameras, for multi-view models. In the GUI the grid, the heads-up
display and the selection highlight are hidden for the capture and restored
after; headless, Maya plays back the default perspective camera. A playblast
is an undo step of its own in Maya, so undo recording is paused around it
(and only when it was on): the capture never takes the place of the user's
last step in the undo queue.
"""

from __future__ import annotations

import math
import os
import shutil
import time

from maya import cmds

from . import scene

LONG_SIDE = 1024
VIEW_SIZE = 1024
VIEW_BACKGROUND = (0.6, 0.6, 0.6)  # scene-linear: a light grey once the view transform is applied
_DIAGONAL = math.sqrt(0.5)
# Where each view's camera stands, seen from the object, in a Y-up scene (Maya's front is +Z;
# "left" is the object's own left, a character's left arm, so the camera stands at +X).
VIEW_DIRECTIONS = {
    "front": (0.0, 0.0, 1.0),
    "left": (1.0, 0.0, 0.0),
    "back": (0.0, 0.0, -1.0),
    "right": (-1.0, 0.0, 0.0),
    "top": (0.0, 1.0, 0.0),
    "bottom": (0.0, -1.0, 0.0),
    "leftFront": (_DIAGONAL, 0.0, _DIAGONAL),
    "rightFront": (-_DIAGONAL, 0.0, _DIAGONAL),
}


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


def capture_views(nodes: list, views: list, folder: str = "", size: int = VIEW_SIZE) -> dict:
    """Orthographic JPEGs of ``nodes`` from each of ``views``; returns ``{views: {view: path}, box, up_axis, name}``.

    Every view uses the same scale, framing the nodes' world bounding box with
    a margin, and the cameras clip just around the box, so objects outside it
    stay out of frame (a floor the object stands on is cut by the far plane,
    except seen from below). Rendered with ``ogsRender`` (Viewport 2.0, also
    without a window). Cameras are made and removed with undo recording
    paused, and the render settings touched are put back: nothing stays in
    the scene or the undo queue.
    """
    found = cmds.ls(nodes, long=True, objectsOnly=True) or []
    if not found:
        raise RuntimeError("Select the object to capture first.")
    box = cmds.exactWorldBoundingBox(found, ignoreInvisible=True)
    centre = [(box[i] + box[i + 3]) / 2 for i in range(3)]
    half = [(box[i + 3] - box[i]) / 2 for i in range(3)]
    if max(half) <= 0:
        raise RuntimeError("The selection has no size to capture.")
    if not views:
        raise RuntimeError("This model takes no named views.")
    z_up = cmds.upAxis(query=True, axis=True) == "z"
    turned = [_scene_direction(VIEW_DIRECTIONS[view], z_up) for view in views]
    # One scale for every view: the widest extent any of them sees (across or up its image), plus a margin.
    width = 2.3 * max(max(_support(half, _across(direction, _up(view, z_up))), _support(half, _up(view, z_up))) for view, direction in zip(views, turned, strict=True))
    distance = 4.0 * math.sqrt(sum(value * value for value in half)) + width
    folder = folder or captures_folder()
    os.makedirs(folder, exist_ok=True)
    stem = "views_" + time.strftime("%Y%m%d_%H%M%S")
    recording = cmds.undoInfo(query=True, state=True)
    if recording:
        cmds.undoInfo(stateWithoutFlush=False)
    saved = _render_settings()
    cameras: list = []
    out: dict = {}
    try:
        _set_render_settings()
        for view, direction in zip(views, turned, strict=True):
            eye = [centre[i] + direction[i] * distance for i in range(3)]
            transform, shape = cmds.camera(orthographic=True, name=f"scn_view_{view}")
            cameras.append(transform)
            cmds.viewPlace(shape, eye=eye, lookAt=centre, up=_up(view, z_up))
            depth = _support(half, direction)
            cmds.setAttr(shape + ".orthographicWidth", width)
            cmds.setAttr(shape + ".nearClipPlane", max(distance - depth - 0.02 * width, 0.001))
            cmds.setAttr(shape + ".farClipPlane", distance + depth - 0.002 * width)
            cmds.setAttr(shape + ".backgroundColor", *VIEW_BACKGROUND, type="double3")
            written = cmds.ogsRender(camera=shape, width=size, height=size)
            path = os.path.join(folder, f"{stem}_{view}.jpg")
            shutil.move(written, path)
            out[view] = path
    finally:
        for transform in cameras:
            if cmds.objExists(transform):
                cmds.delete(transform)
        _restore_render_settings(saved)
        if recording:
            cmds.undoInfo(stateWithoutFlush=True)
    return {"views": out, "box": box, "up_axis": "z" if z_up else "y", "name": found[0].split("|")[-1]}


def _scene_direction(direction: tuple, z_up: bool) -> tuple:
    x, y, z = direction
    return (x, -z, y) if z_up else (x, y, z)


def _across(direction: tuple, up: tuple) -> tuple:
    """A view's image x axis (direction cross up, unit length)."""
    across = (direction[1] * up[2] - direction[2] * up[1], direction[2] * up[0] - direction[0] * up[2], direction[0] * up[1] - direction[1] * up[0])
    length = math.sqrt(sum(value * value for value in across))
    return tuple(value / length for value in across)


def _support(half: list, direction: tuple) -> float:
    """Half the box's extent along ``direction``."""
    return sum(abs(direction[i]) * half[i] for i in range(3))


def _up(view: str, z_up: bool) -> tuple:
    """Image up: the scene's up, except from above (the back at the top) and below (the front at the top)."""
    if view in ("top", "bottom"):
        return _scene_direction(VIEW_DIRECTIONS["back" if view == "top" else "front"], z_up)
    return (0.0, 0.0, 1.0) if z_up else (0.0, 1.0, 0.0)


def _render_settings() -> dict:
    return {
        "format": cmds.getAttr("defaultRenderGlobals.imageFormat"),
        "transform": cmds.colorManagementPrefs(query=True, outputTarget="renderer", outputTransformEnabled=True),
        "view_transform": cmds.colorManagementPrefs(query=True, outputTarget="renderer", outputUseViewTransform=True),
        "ssao": cmds.getAttr("hardwareRenderingGlobals.ssaoEnable"),
        "multisample": cmds.getAttr("hardwareRenderingGlobals.multiSampleEnable"),
    }


def _set_render_settings() -> None:
    cmds.setAttr("defaultRenderGlobals.imageFormat", 8)  # JPEG
    # ogsRender writes scene-linear values unless the output transform is on (spec 6.13).
    cmds.colorManagementPrefs(edit=True, outputTarget="renderer", outputTransformEnabled=True)
    cmds.colorManagementPrefs(edit=True, outputTarget="renderer", outputUseViewTransform=True)
    cmds.setAttr("hardwareRenderingGlobals.ssaoEnable", True)  # shading between parts reads as shape
    cmds.setAttr("hardwareRenderingGlobals.multiSampleEnable", True)


def _restore_render_settings(saved: dict) -> None:
    cmds.setAttr("defaultRenderGlobals.imageFormat", saved["format"])
    cmds.colorManagementPrefs(edit=True, outputTarget="renderer", outputTransformEnabled=bool(saved["transform"]))
    cmds.colorManagementPrefs(edit=True, outputTarget="renderer", outputUseViewTransform=bool(saved["view_transform"]))
    cmds.setAttr("hardwareRenderingGlobals.ssaoEnable", saved["ssao"])
    cmds.setAttr("hardwareRenderingGlobals.multiSampleEnable", saved["multisample"])
