"""FBX results through Maya's own FBX importer (spec 6.7). Main thread only.

Scenario returns FBX for quad meshes (Tripo's ``quad`` option) and converts
any 3D asset to FBX on download. The GLB builder stays the first carrier;
an FBX goes through ``FBXImport``, called by the landing inside the plug-in's
recording import command, so one undo removes everything it made.

Each import sets the importer's options from scratch [verified in mayapy
2027.2 on Scenario's FBX]: mode ``add`` (the default merge imports nothing
when a node of the same name exists), the scene's unit, no cameras, lights,
log, timeline or frame rate changes. The importer turns the content to the
scene's up axis whatever its own up-axis option says, so a Z-up scene is
set to Y-up for the import and back after; like the GLB builder, the new
group is then turned 90 degrees on X, so every placement treats both
carriers alike. The file is copied into the result's texture folder
first, so its embedded textures extract there (``<name>.fbm``).

The importer runs at the root namespace (its own clean-up steps fail inside
one). After the import: the scene's up axis and the playback range, current
frame and frame rate are put back as they were; the new nodes move into the
result's namespace, with the names the FBX SDK escaped (``FBXASC045`` for
``-``) cleaned, and its top nodes are grouped under ``<base>_grp``. The
importer's materials stay (Phong for Scenario's FBX), with every texture but
colour set to Raw and normal maps read as tangent-space normals.
"""

from __future__ import annotations

import os
import re
import shutil

from maya import cmds, mel

from .landing import SRGB, LandingError

PLUGIN = "fbxmaya"
RAW = "Raw"
COLOUR_INPUTS = ("color", "baseColor", "diffuse", "incandescence")
# The importer's unit names differ from Maya's for inches only.
UNITS = {"in": "In"}


def available() -> bool:
    try:
        if not cmds.pluginInfo(PLUGIN, query=True, loaded=True):
            cmds.loadPlugin(PLUGIN, quiet=True)
        return True
    except RuntimeError:
        return False


def build(path: str, base: str, texture_folder: str) -> dict:
    """Imports ``path`` under ``<base>_grp`` in the current namespace; returns what was made, like ``glb_builder.build``."""
    if not available():
        raise LandingError("Nothing was imported: Maya's FBX plug-in (fbxmaya) is not available. Turn it on in the Plug-in Manager.")
    os.makedirs(texture_folder, exist_ok=True)
    local = os.path.join(texture_folder, os.path.splitext(os.path.basename(path))[0] + ".fbx")  # the importer goes by the extension
    if os.path.abspath(local) != os.path.abspath(path):
        shutil.copy2(path, local)
    up = cmds.upAxis(query=True, axis=True)
    timeline = _timeline()
    namespace = cmds.namespaceInfo(currentNamespace=True, absoluteName=True)
    before = set(cmds.ls(long=True))
    tops_before = set(cmds.ls(assemblies=True, long=True))
    # The importer's own clean-up steps name nodes without their namespace and fail inside
    # one (lost settings, errors in the Script Editor), so it imports at the root and the
    # new nodes move into the namespace after.
    cmds.namespace(setNamespace=":")
    if up != "y":
        cmds.upAxis(axis="y", rotateView=False)  # the importer converts to the scene's axis, whatever its own option says
    try:
        mel.eval("FBXResetImport")
        unit = cmds.currentUnit(query=True, linear=True)
        for option in (
            "FBXImportMode -v add",
            "FBXImportUpAxis y",
            f"FBXImportConvertUnitString {UNITS.get(unit, unit)}",
            "FBXImportCameras -v false",
            "FBXImportLights -v false",
            "FBXImportGenerateLog -v false",
            "FBXImportFillTimeline -v false",
            "FBXImportSetMayaFrameRate -v false",
            "FBXImportSkins -v true",
            "FBXImportShapes -v true",
        ):
            mel.eval(option)
        try:
            mel.eval('FBXImport -f "{}"'.format(local.replace("\\", "/").replace('"', '\\"')))
        except RuntimeError as error:
            raise LandingError("Nothing was imported: Maya's FBX importer could not read this FBX file.") from error
    finally:
        cmds.namespace(setNamespace=namespace)
        if cmds.upAxis(query=True, axis=True) != up:
            cmds.upAxis(axis=up, rotateView=False)
        _restore_timeline(timeline)
    # UUIDs from names: ``cmds.ls(uuid=True)`` with no objects lists names, not UUIDs.
    new = cmds.ls([node for node in cmds.ls(long=True) if node not in before], uuid=True)
    tops = [node for node in cmds.ls(assemblies=True, long=True) if node not in tops_before]
    if not tops:
        raise LandingError("Nothing was imported: the FBX file holds no objects.")
    tops = cmds.ls(tops, uuid=True)
    _into_namespace(new, namespace)
    root = cmds.group(empty=True, name=f"{base}_grp", world=True)
    cmds.parent(cmds.ls(tops, long=True), root)
    if up == "z":
        cmds.setAttr(root + ".rotateX", 90)
    root = cmds.ls(root, long=True)[0]
    alive = [uuid for uuid in new if cmds.ls(uuid)]
    meshes = cmds.listRelatives(root, allDescendents=True, type="mesh", fullPath=True) or []
    meshes = [shape for shape in meshes if not cmds.getAttr(shape + ".intermediateObject")]
    made_here = set(cmds.ls(alive, type="shadingEngine", long=True))
    groups = list(dict.fromkeys(cmds.listConnections(meshes, type="shadingEngine") or [])) if meshes else []
    groups = [group for group in groups if group in made_here]  # never initialShadingGroup
    shaders = _shaders(groups)
    _texture_roles(groups)
    return {
        "top": root,
        "meshes": meshes,
        "shaders": shaders,
        "shading_groups": groups,
        "joints": cmds.ls(alive, type="joint", long=True),
        "skin_clusters": cmds.ls(alive, type="skinCluster", long=True),
        "blend_shapes": cmds.ls(alive, type="blendShape", long=True),
        "clip": _clip(alive),
        "other_clips": [],
        "collapsed_triangles": 0,
        "notes": [],
    }


def _timeline() -> dict:
    return {
        "time": cmds.currentUnit(query=True, time=True),
        "range": [cmds.playbackOptions(query=True, **{key: True}) for key in ("minTime", "maxTime", "animationStartTime", "animationEndTime")],
        "frame": cmds.currentTime(query=True),
    }


def _restore_timeline(saved: dict) -> None:
    if cmds.currentUnit(query=True, time=True) != saved["time"]:
        cmds.currentUnit(time=saved["time"], updateAnimation=True)
    low, high, start, end = saved["range"]
    cmds.playbackOptions(minTime=low, maxTime=high, animationStartTime=start, animationEndTime=end)
    cmds.currentTime(saved["frame"], update=False)


def _into_namespace(uuids: list, namespace: str) -> None:
    """Each new node renamed into ``namespace``, with ``FBXASC045`` and the like (the FBX SDK's escapes for characters Maya cannot hold) as ``_``."""
    prefix = namespace.rstrip(":") + ":"  # absolute (":scn_x:"), whatever the current namespace
    for uuid in uuids:
        found = cmds.ls(uuid, long=True)
        if not found or cmds.lockNode(found[0], query=True, lock=True)[0]:
            continue
        clean = re.sub(r"FBXASC\d{3}", "_", found[0].split("|")[-1].split(":")[-1])
        if ":" + found[0].split("|")[-1] != prefix + clean:
            cmds.rename(found[0], prefix + clean)


def _source(plug: str) -> str:
    found = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
    return found[0] if found else ""


def _shaders(groups: list) -> list:
    """The surface shader of each shading group, as the importer made it.

    Kept as is: replacing it with an openPBR surface inside the import made
    Maya 2027.2 crash on the next ``polyCube`` once that import was undone
    and the undo queue freed (spec 6.7).
    """
    out = []
    for group in groups:
        out.extend(cmds.listConnections(group + ".surfaceShader", source=True, destination=False) or [])
    return list(dict.fromkeys(out))


def _texture_roles(groups: list) -> None:
    """Colour textures stay sRGB, every other one is Raw; a normal map through ``bump2d`` is read as tangent-space normals."""
    for node in cmds.ls(cmds.listHistory(groups, pruneDagObjects=True) if groups else [], type="file"):
        targets = [plug.split(".")[-1] for plug in cmds.listConnections(node, source=False, destination=True, plugs=True) or []]
        colour = any(target in COLOUR_INPUTS for target in targets)
        cmds.setAttr(node + ".ignoreColorSpaceFileRules", True)
        cmds.setAttr(node + ".colorSpace", SRGB if colour else RAW, type="string")
        if "normal" in node.split(":")[-1].lower():
            for bump in cmds.listConnections(node, source=False, destination=True, type="bump2d") or []:
                cmds.setAttr(bump + ".bumpInterp", 1)


def _clip(uuids: list) -> dict | None:
    curves = cmds.ls(uuids, type="animCurve", long=True)
    times = cmds.keyframe(curves, query=True, timeChange=True) if curves else None
    if not times:
        return None
    fps = mel.eval("currentTimeUnitToFPS()")
    return {"name": "clip_1", "start": min(times), "end": max(times), "seconds": (max(times) - min(times)) / fps if fps else 0.0}
