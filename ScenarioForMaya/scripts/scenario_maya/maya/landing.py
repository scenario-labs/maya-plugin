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
import itertools
import math
import os

from maya import cmds, mel

from ..core import errors, gltf, naming
from . import scene

SRGB = "sRGB Encoded Rec.709 (sRGB)"
LINEAR = "scene-linear Rec.709-sRGB"
# Curves keyed in time; driven keys (animCurveU*) are left alone.
TIME_CURVES = ("animCurveTA", "animCurveTL", "animCurveTT", "animCurveTU")
COMMON_RATES = (12, 15, 24, 25, 30, 48, 50, 60, 120)
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


def file_texture(path: str, name: str, colour_space: str) -> tuple:
    """A colour-managed ``file`` node and its ``place2dTexture``, wired as Maya's own UI wires them.

    ``ignoreColorSpaceFileRules`` keeps Maya's file rules from overriding the space chosen by role.
    """
    texture = cmds.shadingNode("file", asTexture=True, isColorManaged=True, name=f"{name}_file")
    place = cmds.shadingNode("place2dTexture", asUtility=True, name=f"{name}_place2d")
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
    cmds.setAttr(texture + ".colorSpace", colour_space, type="string")
    return texture, place


def image_material(path: str, base: str, attributes: dict) -> dict:
    """Shader, shading group, file and place2d nodes with the image as base colour."""
    kind = surface_type()
    shader = cmds.shadingNode(kind, asShader=True, name=f"{base}_mtl")
    group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=f"{base}_SG")
    cmds.connectAttr(shader + ".outColor", group + ".surfaceShader")
    texture, place = file_texture(path, f"{base}_albedo", LINEAR if _hdr(path) else SRGB)
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
    textures = mode != "image_plane" and not cmds.about(batch=True) and scene.show_textures()
    made.update(mode=mode, namespace=ns, undo=chunk, textures_turned_on=bool(textures))
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


def land_model(
    path: str,
    attributes: dict,
    *,
    texture_folder: str,
    label: str = "",
    select: bool = True,
    place: tuple | None = None,
    matrix: list | None = None,
    box: list | None = None,
    over: str = "",
) -> dict:
    """Imports a 3D result (GLB, or FBX through Maya's importer) as a new group: one undo step, provenance on the group.

    Textures are written to ``texture_folder`` first (files stay after an
    undo, spec 7.3). With ``place`` (a world point) the group is moved so the
    model's bottom centre sits on the ground plane below that point (spec
    10.4); with ``matrix`` (centimetres, as ``cmds.xform`` takes it) the group
    gets that world matrix, which is how an edit result lands over the mesh
    it came from; with ``box`` (a world bounding box in scene units) it is
    scaled and moved onto that box, which is how a multi-view result lands
    over the object its views show and a motion over the character it was
    made for (``over`` names the mesh or object);
    without any, the file's own origin is kept. Returns what was made plus
    the import checks.
    """
    from . import fbx_import, glb_builder, import_command

    kind = gltf.sniff_format(path)
    if kind == "missing":
        raise LandingError("Nothing was imported: the result file is missing. Download it again from Jobs.")
    if kind not in ("glb", "fbx"):
        raise LandingError(f"Nothing was imported: this result is a {kind.upper()} file, which this version cannot import yet.")
    base = naming.slug(label or attributes.get("scenario_prompt") or os.path.splitext(os.path.basename(path))[0])
    if kind == "fbx":
        images: list = []

        def build():
            return fbx_import.build(path, base, texture_folder)

    else:
        try:
            doc = gltf.Document.load(path)
        except (errors.ProtocolError, ValueError, KeyError) as error:
            raise LandingError(f"Nothing was imported: the GLB file could not be read ({error}).") from error
        if doc.unsupported:
            raise LandingError("Nothing was imported: the file uses " + " and ".join(doc.unsupported) + ", which the importer cannot read yet.")
        images = gltf.extract_images(doc, texture_folder, base)

        def build():
            return glb_builder.build(doc, images, base)

    namespace = free_namespace(f"scn_{base}")
    chunk = f"Scenario: Import {base}"
    with undo_chunk(chunk):
        scene.scene_uuid()
        with in_namespace(namespace) as ns:
            made = import_command.run(build)
        if matrix is not None:
            cmds.xform(made["top"], matrix=matrix, worldSpace=True)
        elif box is not None and made["meshes"]:
            _onto_box(made["top"], made["meshes"], box, (made.get("clip") or {}).get("start"))
        elif place is not None and made["meshes"]:
            _on_ground(made["top"], made["meshes"], place)
        if attributes:
            add_provenance(made["top"], attributes)
        if select:
            cmds.select(made["top"], replace=True)
    made["checks"] = glb_builder.inspect(made)
    note = off_frame_note(ns)
    if note:
        made["checks"].setdefault("notes", []).append(note)
    textures = not cmds.about(batch=True) and scene.show_textures()
    checks = made["checks"]
    made.update(
        mode="model",
        namespace=ns,
        undo=chunk,
        textures=images,
        textures_turned_on=bool(textures),
        summary=f"Imported {base}: {checks['faces']:,} faces"
        + (f", {checks['joints']} joints" if checks["joints"] else "")
        + (f", over {over}" if (matrix is not None or box is not None) and over else "")
        + (", on the ground at the camera's centre of interest" if matrix is None and box is None and place is not None and made["meshes"] else ""),
    )
    return made


def off_frame_note(namespace: str) -> str:
    """A note when the namespace's keys fall between the scene's frames (a 30 fps clip in a 24 fps scene), else ""."""
    curves = cmds.ls(namespace + ":*", type=TIME_CURVES)
    times = sorted(set(cmds.keyframe(curves, query=True, timeChange=True) or [])) if curves else []
    if not any(abs(time - round(time)) > 1e-3 for time in times):
        return ""
    fps = mel.eval("currentTimeUnitToFPS()")
    steps = [b - a for a, b in itertools.pairwise(times)]
    step = min(steps) if steps else 0.0  # one frame of the file's rate when keyed on every frame
    source = fps / step if step > 0 and fps else 0.0
    rate = next((rate for rate in COMMON_RATES if abs(source - rate) < 0.05), None)
    if rate and rate != round(fps):
        return f"The clip was made at {rate} fps and this scene runs at {fps:g} fps, so its keys fall between frames."
    return "The clip's keys fall between this scene's frames."


def _onto_box(top: str, meshes: list, box: list, frame: float | None = None) -> None:
    """Scales ``top`` uniformly and moves it so the meshes' bounding box has ``box``'s centre and diagonal (no rotation).

    ``top`` is a new group at the origin, so its scale applies about the origin.
    An animated result is measured on ``frame`` (its clip's first), the
    current frame kept.
    """
    now = cmds.currentTime(query=True)
    if frame is not None and frame != now:
        cmds.currentTime(frame, update=True)
    try:
        have = cmds.exactWorldBoundingBox(meshes)
    finally:
        if frame is not None and frame != now:
            cmds.currentTime(now, update=True)
    size, want = math.dist(have[:3], have[3:]), math.dist(box[:3], box[3:])
    scale = want / size if size > 0 else 1.0
    cmds.setAttr(top + ".scale", scale, scale, scale, type="double3")
    move = [(box[i] + box[i + 3]) / 2.0 - scale * (have[i] + have[i + 3]) / 2.0 for i in range(3)]
    cmds.move(*move, top, relative=True, worldSpace=True)


def _on_ground(top: str, meshes: list, point: tuple) -> None:
    """Moves ``top`` so the meshes' bottom centre sits at ``point`` projected on the ground (y or z = 0)."""
    box = cmds.exactWorldBoundingBox(meshes)
    centre = [(box[i] + box[i + 3]) / 2.0 for i in range(3)]
    up = 2 if cmds.upAxis(query=True, axis=True) == "z" else 1
    target = list(point)
    target[up] = 0.0
    bottom = list(centre)
    bottom[up] = box[up]
    cmds.move(*(target[i] - bottom[i] for i in range(3)), top, relative=True, worldSpace=True)


def landed_nodes() -> list:
    """Every node carrying ``scenario_asset_id`` (In this scene, spec 10.3)."""
    return sorted(set(cmds.ls("*.scenario_asset_id", recursive=True, objectsOnly=True, long=True) or []))
