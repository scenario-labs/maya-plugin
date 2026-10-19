"""What the plug-in reads from the open scene: project folders, the scene's
id, the camera people look through, the selection. Main thread only.
"""

from __future__ import annotations

import os
import uuid
from datetime import date

from maya import cmds

SCENE_UUID_KEY = "scenario_scene_uuid"


def scene_uuid(create: bool = True) -> str:
    """A random id kept in the scene's ``fileInfo``, so jobs find the scene they came from."""
    found = cmds.fileInfo(SCENE_UUID_KEY, query=True) or []
    if found and found[0]:
        return found[0]
    if not create:
        return ""
    value = uuid.uuid4().hex
    cmds.fileInfo(SCENE_UUID_KEY, value)
    return value


def scene_path() -> str:
    return cmds.file(query=True, sceneName=True) or ""


def project_root() -> str:
    return cmds.workspace(query=True, rootDirectory=True) or os.path.expanduser("~")


def is_default_project() -> bool:
    root = os.path.normpath(project_root())
    return os.path.basename(root) == "default" and os.path.basename(os.path.dirname(root)) == "projects"


def _rule(name: str, fallback: str) -> str:
    try:
        value = cmds.workspace(fileRuleEntry=name) or ""
    except RuntimeError:
        value = ""
    return value or fallback


def folders() -> dict:
    """Where results go, inside the current Maya project (spec 10.1)."""
    root = project_root()
    return {
        "images": os.path.join(root, _rule("sourceImages", "sourceimages"), "scenario"),
        "originals": os.path.join(root, "scenario", date.today().isoformat()),
        "project": root,
        "default_project": is_default_project(),
    }


def model_panel() -> str:
    """The viewport with focus, else the first visible one, else ""."""
    panels = []
    try:
        focus = cmds.getPanel(withFocus=True)
        if focus and cmds.getPanel(typeOf=focus) == "modelPanel":
            panels.append(focus)
        panels.extend(cmds.getPanel(visiblePanels=True) or [])
    except RuntimeError:
        pass
    for panel in panels:
        if cmds.getPanel(typeOf=panel) != "modelPanel":
            continue
        camera = cmds.modelPanel(panel, query=True, camera=True)
        if camera and cmds.objExists(camera):
            return panel
    return ""


def active_camera() -> tuple:
    """(transform, shape) of the camera in the viewport with focus, else the first visible one, else persp."""
    panel = model_panel()
    return _camera_pair(cmds.modelPanel(panel, query=True, camera=True) if panel else "persp")


def interest_point(camera: tuple | None = None) -> tuple:
    """The camera's centre of interest in world space (where new results are placed)."""
    _transform, shape = camera or active_camera()
    try:
        return tuple(cmds.camera(shape, query=True, worldCenterOfInterest=True))
    except RuntimeError:
        return (0.0, 0.0, 0.0)


def show_textures() -> bool:
    """Turns on textured display (key 6) in the active viewport; True when it was off.

    A view setting, not scene data: it stays out of the undo queue.
    """
    panel = model_panel()
    if not panel or cmds.modelEditor(panel, query=True, displayTextures=True):
        return False
    cmds.modelEditor(panel, edit=True, displayTextures=True)
    return True


def _camera_pair(camera: str) -> tuple:
    if cmds.nodeType(camera) == "camera":
        return cmds.listRelatives(camera, parent=True, fullPath=True)[0], camera
    shapes = cmds.listRelatives(camera, shapes=True, type="camera", fullPath=True) or []
    return camera, shapes[0] if shapes else camera


def selected_surfaces() -> list:
    """Selected meshes (transforms) and face components a material can go on."""
    out = []
    for item in cmds.ls(selection=True, long=True) or []:
        if ".f[" in item:
            out.append(item)
            continue
        if cmds.nodeType(item) == "mesh":
            out.append(item)
            continue
        if cmds.listRelatives(item, shapes=True, type="mesh", noIntermediate=True):
            out.append(item)
    return out


def short(node: str) -> str:
    return node.split("|")[-1]


def surfaces_label(items: list) -> str:
    if not items:
        return ""
    names = sorted({short(item.split(".")[0]) for item in items})
    faces = any(".f[" in item for item in items)
    text = ", ".join(names[:2]) + (f" and {len(names) - 2} more" if len(names) > 2 else "")
    return f"faces of {text}" if faces else text
