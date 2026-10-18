"""Landing image results in the scene (spec 6.9, 6.8, 7.3, 10.2 to 10.4).

Three ways, each one named undo step, so one Ctrl+Z removes everything it
made (nodes, material, namespace) and one redo brings it back:

- ``card``: a ``polyPlane`` at the image's aspect, facing the camera, at the
  camera's centre of interest, with the image as base colour.
- ``material``: a new material with the image as base colour on the selected
  meshes or faces. The meshes' old assignment comes back with undo; shared
  materials are never edited.
- ``image_plane``: an image plane on the camera, for concept reference.

Every node the plug-in makes lives in one ``scn_<slug>`` namespace and the
top node, material and file node carry the provenance attributes. Images are
images only here: no ``cmds.file(i=True)``, which would erase the undo queue.
Main thread only.
"""

from __future__ import annotations

import contextlib
import math
import os

from maya import cmds

from ..core import naming
from . import scene

SRGB = "sRGB Encoded Rec.709 (sRGB)"
LINEAR = "scene-linear Rec.709-sRGB"
_BASE_COLOR = {"openPBRSurface": "baseColor", "standardSurface": "baseColor", "lambert": "color"}
MODES = ("card", "material", "image_plane")
LABELS = {"card": "Import as card", "material": "Material on selection", "image_plane": "Image plane"}


class LandingError(Exception):
    """Nothing was landed; the message says why and what to do."""


@contextlib.contextmanager
def undo_chunk(name: str):
    cmds.undoInfo(openChunk=True, chunkName=name)
    try:
        yield
    finally:
        cmds.undoInfo(closeChunk=True)


@contextlib.contextmanager
def in_namespace(namespace: str):
    previous = cmds.namespaceInfo(currentNamespace=True, absoluteName=True)
    if not cmds.namespace(exists=":" + namespace):
        cmds.namespace(add=namespace, parent=":")
    cmds.namespace(setNamespace=":" + namespace)
    try:
        yield ":" + namespace
    finally:
        cmds.namespace(setNamespace=previous)


def free_namespace(base: str) -> str:
    name, number = base, 2
    while cmds.namespace(exists=":" + name):
        name = f"{base}{number}"
        number += 1
    return name


def surface_type() -> str:
    """openPBRSurface where Maya has it (2027's default surface), else standardSurface, else lambert."""
    for kind in ("openPBRSurface", "standardSurface"):
        if kind in (cmds.listNodeTypes("shader") or []):
            return kind
    return "lambert"


def add_provenance(node: str, attributes: dict, extra: dict | None = None) -> None:
    for name, value in list(attributes.items()) + list((extra or {}).items()):
        if not cmds.attributeQuery(name, node=node, exists=True):
            cmds.addAttr(node, longName=name, dataType="string", category="Scenario")
        cmds.setAttr(f"{node}.{name}", str(value), type="string")


def _hdr(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in (".exr", ".hdr")


def image_material(path: str, base: str, attributes: dict) -> dict:
    """Shader, shading group, file and place2d nodes with the image as base colour."""
    kind = surface_type()
    shader = cmds.shadingNode(kind, asShader=True, name=f"{base}_mtl")
    group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=f"{base}_SG")
    cmds.connectAttr(shader + ".outColor", group + ".surfaceShader")
    texture = cmds.shadingNode("file", asTexture=True, isColorManaged=True, name=f"{base}_albedo_file")
    place = cmds.shadingNode("place2dTexture", asUtility=True, name=f"{base}_place2d")
    for out_attr, in_attr in (
        ("coverage", "coverage"),
        ("translateFrame", "translateFrame"),
        ("rotateFrame", "rotateFrame"),
        ("repeatUV", "repeatUV"),
        ("offset", "offset"),
        ("rotateUV", "rotateUV"),
        ("wrapU", "wrapU"),
        ("wrapV", "wrapV"),
        ("outUV", "uvCoord"),
        ("outUvFilterSize", "uvFilterSize"),
    ):
        cmds.connectAttr(f"{place}.{out_attr}", f"{texture}.{in_attr}")
    cmds.setAttr(texture + ".fileTextureName", path, type="string")
    cmds.setAttr(texture + ".ignoreColorSpaceFileRules", 1)
    cmds.setAttr(texture + ".colorSpace", LINEAR if _hdr(path) else SRGB, type="string")
    cmds.connectAttr(texture + ".outColor", f"{shader}.{_BASE_COLOR[kind]}")
    has_alpha = bool(cmds.getAttr(texture + ".fileHasAlpha"))
    if has_alpha:
        if kind == "openPBRSurface":
            cmds.connectAttr(texture + ".outAlpha", shader + ".geometryOpacity")
        elif kind == "standardSurface":
            for channel in "RGB":
                cmds.connectAttr(texture + ".outAlpha", f"{shader}.opacity{channel}")
        else:
            cmds.connectAttr(texture + ".outTransparency", shader + ".transparency")
    add_provenance(shader, attributes)
    add_provenance(texture, attributes, {"scenario_role": "albedo"})
    width, height = cmds.getAttr(texture + ".outSizeX"), cmds.getAttr(texture + ".outSizeY")
    return {"shader": shader, "shading_group": group, "file": texture, "place2d": place, "width": width, "height": height, "alpha": has_alpha}


def _card_height(camera_shape: str, distance: float) -> float:
    """Half the camera's view height at the centre of interest, so the card fills about half the view."""
    if cmds.getAttr(camera_shape + ".orthographic"):
        return cmds.getAttr(camera_shape + ".orthographicWidth") * 0.5
    fov = cmds.camera(camera_shape, query=True, verticalFieldOfView=True)
    return max(2.0 * distance * math.tan(math.radians(fov) / 2.0) * 0.5, 1e-3)


def land(path: str, attributes: dict, mode: str, *, label: str = "", camera: tuple | None = None, targets: list | None = None, select: bool = True) -> dict:
    """Lands one image file. Returns what was made, for the result card and agents."""
    if mode not in MODES:
        raise LandingError(f"Unknown landing {mode!r}; use one of {', '.join(MODES)}.")
    if not os.path.isfile(path):
        raise LandingError("Nothing was imported: the result file is missing. Download it again from Jobs.")
    if mode == "material":
        targets = targets if targets is not None else scene.selected_surfaces()
        if not targets:
            raise LandingError("Nothing was applied: select a mesh or faces first.")
    camera = camera or scene.active_camera()
    base = naming.slug(label or attributes.get("scenario_prompt") or os.path.splitext(os.path.basename(path))[0])
    namespace = free_namespace(f"scn_{base}")
    selection = cmds.ls(selection=True, long=True) or []
    chunk = {"card": f"Scenario: Import {base}", "material": f"Scenario: Material {base}", "image_plane": f"Scenario: Image plane {base}"}[mode]
    with undo_chunk(chunk):
        scene.scene_uuid()
        with in_namespace(namespace) as ns:
            if mode == "card":
                made = _card(path, base, attributes, camera)
            elif mode == "material":
                made = _material(path, base, attributes, targets)
            else:
                made = _image_plane(path, base, attributes, camera)
        if select and made.get("top"):
            cmds.select(made["top"], replace=True)
        elif selection:  # node creation changes the selection; a material leaves the user's own
            cmds.select(selection, replace=True)
        else:
            cmds.select(clear=True)
    made.update(mode=mode, namespace=ns, undo=chunk)
    return made


def _card(path: str, base: str, attributes: dict, camera: tuple) -> dict:
    material = image_material(path, base, attributes)
    width, height = material["width"] or 1, material["height"] or 1
    camera_transform, camera_shape = camera
    eye = cmds.xform(camera_transform, query=True, worldSpace=True, translation=True)
    target = cmds.camera(camera_shape, query=True, worldCenterOfInterest=True)
    distance = math.dist(eye, target) or 10.0
    card_height = _card_height(camera_shape, distance)
    plane = cmds.polyPlane(width=card_height * width / height, height=card_height, subdivisionsX=1, subdivisionsY=1, axis=(0, 0, 1), constructionHistory=False, name=f"{base}_card")[0]
    cmds.sets(plane, edit=True, forceElement=material["shading_group"])
    group = cmds.group(plane, name=f"{base}_grp")
    cmds.xform(group, worldSpace=True, translation=target)
    cmds.xform(group, worldSpace=True, rotation=cmds.xform(camera_transform, query=True, worldSpace=True, rotation=True))
    add_provenance(group, attributes)
    return {
        "top": group,
        "nodes": [group, plane, material["shader"], material["shading_group"], material["file"], material["place2d"]],
        "material": material["shader"],
        "file": material["file"],
        "size": [round(card_height * width / height, 4), round(card_height, 4)],
        "image_size": [width, height],
        "summary": f"Card {width}x{height} px at the centre of interest of {scene.short(camera_transform)}",
    }


def _material(path: str, base: str, attributes: dict, targets: list) -> dict:
    material = image_material(path, base, attributes)
    cmds.sets(targets, edit=True, forceElement=material["shading_group"])
    return {
        "top": None,
        "nodes": [material["shader"], material["shading_group"], material["file"], material["place2d"]],
        "material": material["shader"],
        "file": material["file"],
        "targets": [scene.short(item) for item in targets],
        "image_size": [material["width"], material["height"]],
        "summary": f"New material {scene.short(material['shader'])} on {scene.surfaces_label(targets)}",
    }


def _image_plane(path: str, base: str, attributes: dict, camera: tuple) -> dict:
    camera_transform, camera_shape = camera
    transform, shape = cmds.imagePlane(camera=camera_shape, fileName=path, name=f"{base}_imagePlane")
    cmds.setAttr(shape + ".ignoreColorSpaceFileRules", 1)
    cmds.setAttr(shape + ".colorSpace", LINEAR if _hdr(path) else SRGB, type="string")
    add_provenance(shape, attributes)
    return {
        "top": transform,
        "nodes": [transform, shape],
        "image_plane": shape,
        "summary": f"Image plane on {scene.short(camera_transform)}",
    }


def landed_nodes() -> list:
    """Every node carrying ``scenario_asset_id`` (In this scene, spec 10.3)."""
    return sorted(set(cmds.ls("*.scenario_asset_id", recursive=True, objectsOnly=True, long=True) or []))
