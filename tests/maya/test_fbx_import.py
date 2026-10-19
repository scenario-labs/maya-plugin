"""FBX results through Maya's FBX importer (spec 6.7), in mayapy, 0 CU: one undo
step, the right size and up axis in any scene, the timeline and frame rate
kept, escaped names cleaned, the importer's materials with Raw data
textures and tangent-space normal maps, skins and keys kept, and Maya still
stable after an undone import leaves the undo queue. Fixtures are written by Maya's own FBX
exporter, with dashes in the names as in Scenario's FBX files."""

import os

import pytest

from tests import glb_samples
from tests.maya.conftest import fresh


def png(folder, name, rgb):
    path = os.path.join(folder, name)
    with open(path, "wb") as handle:
        handle.write(glb_samples.png_bytes(rgb=rgb))
    return path


def write_fbx(cmds, folder, *, rig=False):
    """A 1 m crate standing on the ground with a colour and a normal map (optionally skinned to two joints keyed over 1 s at 30 fps, at rest on the first two frames), as ASCII FBX."""
    from maya import mel

    cmds.loadPlugin("fbxmaya", quiet=True)
    cmds.file(new=True, force=True)
    cmds.currentUnit(linear="cm", time="ntsc")
    box = cmds.polyCube(name="crate_part_a", width=100, height=100, depth=100, subdivisionsY=2)[0]
    cmds.move(0, 50, 0, box)
    phong = cmds.shadingNode("phong", asShader=True, name="crate_mat")
    colour = cmds.shadingNode("file", asTexture=True, name="crate_colour")
    cmds.setAttr(colour + ".fileTextureName", png(folder, "colour.png", (200, 120, 40)), type="string")
    cmds.connectAttr(colour + ".outColor", phong + ".color")
    normal = cmds.shadingNode("file", asTexture=True, name="crate_normal")
    cmds.setAttr(normal + ".fileTextureName", png(folder, "normal.png", (128, 128, 255)), type="string")
    bump = cmds.shadingNode("bump2d", asUtility=True)
    cmds.setAttr(bump + ".bumpInterp", 1)
    cmds.connectAttr(normal + ".outAlpha", bump + ".bumpValue")
    cmds.connectAttr(bump + ".outNormal", phong + ".normalCamera")
    group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="crate_SG")
    cmds.connectAttr(phong + ".outColor", group + ".surfaceShader")
    cmds.sets(box, edit=True, forceElement=group)
    if rig:
        cmds.select(clear=True)
        root = cmds.joint(name="hips", position=(0, 0, 0))
        tip = cmds.joint(name="spine", position=(0, 100, 0))
        cmds.skinCluster(root, tip, box, toSelectedBones=True)
        for frame, value in ((1, 0), (2, 0), (31, 45)):  # a key on the second frame, as in a clip keyed on every frame
            cmds.setKeyframe(tip, attribute="rotateZ", time=frame, value=value)
    path = os.path.join(folder, "crate.fbx")
    cmds.select([node for node in cmds.ls(assemblies=True) if not cmds.listRelatives(node, shapes=True, type="camera")])
    mel.eval("FBXResetExport")
    mel.eval("FBXExportInAscii -v true")
    mel.eval("FBXExportSkins -v true")
    mel.eval('FBXExport -f "{}" -s'.format(path.replace("\\", "/")))
    with open(path, encoding="utf-8", errors="surrogateescape") as handle:
        text = handle.read()
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as handle:
        handle.write(text.replace("crate_part_a", "crate-part-a"))
    cmds.file(new=True, force=True)
    return path


def land(cmds, path, tmp_path, **kwargs):
    landing = fresh("scenario_maya.maya.landing")
    return landing.land_model(str(path), {}, texture_folder=str(tmp_path / "sourceimages" / "crate"), label="crate", **kwargs)


def ours(cmds):
    return cmds.ls("scn_crate*:*")


@pytest.mark.parametrize("up, unit", [("y", "cm"), ("y", "m"), ("z", "cm")])
def test_an_fbx_lands_as_one_undo_step_at_its_size(plugin, cmds, tmp_path, up, unit):
    path = write_fbx(cmds, str(tmp_path))
    cmds.upAxis(axis=up)
    cmds.currentUnit(linear=unit, time="film")
    try:
        cmds.playbackOptions(minTime=5, maxTime=50)
        cmds.currentTime(7)
        made = land(cmds, path, tmp_path)
        assert made["summary"] == "Imported crate: 10 faces", made["summary"]
        k = 0.01 if unit == "m" else 1.0
        expected = [-50, -50, 0, 50, 50, 100] if up == "z" else [-50, 0, -50, 50, 100, 50]
        assert cmds.exactWorldBoundingBox(made["meshes"]) == pytest.approx([value * k for value in expected], abs=1e-3 * k)
        assert cmds.upAxis(query=True, axis=True) == up and cmds.currentUnit(query=True, linear=True) == unit
        assert cmds.currentUnit(query=True, time=True) == "film" and cmds.playbackOptions(query=True, minTime=True) == 5
        assert cmds.playbackOptions(query=True, maxTime=True) == 50 and cmds.currentTime(query=True) == 7
        assert made["top"].split("|")[-1].endswith(":crate_grp") and made["namespace"].startswith(":scn_crate")
        assert not [node for node in ours(cmds) if "FBXASC" in node], "escaped names are cleaned"
        assert cmds.ls(made["namespace"] + ":crate_part_a"), "the dash comes back as an underscore"
        nodes = ours(cmds)
        for _ in range(2):
            cmds.undo()
            assert not ours(cmds), "one undo removes the whole import"
            cmds.redo()
            assert sorted(ours(cmds)) == sorted(nodes)
    finally:
        cmds.currentUnit(linear="cm", time="film")
        cmds.upAxis(axis="y")


def test_fbx_materials_keep_colour_srgb_and_read_normal_maps(plugin, cmds, tmp_path):
    path = write_fbx(cmds, str(tmp_path))
    made = land(cmds, path, tmp_path)
    landing = fresh("scenario_maya.maya.landing")
    assert [cmds.nodeType(shader) for shader in made["shaders"]] == ["phong"], "the importer's material, kept (see the next test)"
    shader = made["shaders"][0]
    colour = cmds.listConnections(shader + ".color", source=True, destination=False)[0]
    assert cmds.getAttr(colour + ".colorSpace") == landing.SRGB
    bump = cmds.listConnections(shader + ".normalCamera", source=True, destination=False, type="bump2d")[0]
    normal = cmds.listConnections(bump + ".bumpValue", source=True, destination=False)[0]
    assert cmds.getAttr(normal + ".colorSpace") == "Raw" and cmds.getAttr(bump + ".bumpInterp") == 1, "a tangent-space normal map"
    checks = made["checks"]
    assert checks["materials"] == 1 and checks["textures"] == 2 and not checks["missing_textures"]


def test_an_fbx_rig_keeps_its_skin_and_keys(plugin, cmds, tmp_path):
    path = write_fbx(cmds, str(tmp_path), rig=True)
    cmds.currentUnit(time="film")
    cmds.playbackOptions(minTime=10, maxTime=60)
    made = land(cmds, path, tmp_path)
    assert len(made["joints"]) == 2 and len(made["skin_clusters"]) == 1
    assert made["checks"]["joints"] == 2 and made["checks"]["influences"] == 2
    clip = made["clip"]
    assert clip is not None and clip["seconds"] == pytest.approx(1.0, abs=0.05), clip
    assert clip["start"] == 10 and clip["end"] == pytest.approx(34), "the clip starts on the scene's start frame, as a GLB clip does"
    curve = cmds.ls(made["namespace"] + ":*", type="animCurveTA")[0]
    assert cmds.keyframe(curve, query=True, timeChange=True) == pytest.approx([10, 10.8, 34])
    assert made["checks"]["notes"] == ["The clip was made at 30 fps and this scene runs at 24 fps, so its keys fall between frames."]
    assert cmds.currentUnit(query=True, time=True) == "film", "the scene keeps its frame rate"
    cmds.undo()
    assert not ours(cmds)
    cmds.redo()
    assert cmds.keyframe(curve, query=True, timeChange=True) == pytest.approx([10, 10.8, 34]), "redo brings the moved keys back"


def test_an_fbx_clip_at_the_scene_rate_has_no_note(plugin, cmds, tmp_path):
    path = write_fbx(cmds, str(tmp_path), rig=True)
    cmds.currentUnit(time="ntsc")
    cmds.playbackOptions(minTime=1, maxTime=60)  # the unit change made the start 1.25
    try:
        made = land(cmds, path, tmp_path)
        assert made["clip"]["start"] == cmds.playbackOptions(query=True, minTime=True)
        assert not made["checks"]["notes"]
    finally:
        cmds.currentUnit(time="film")


@pytest.mark.parametrize("up", ["y", "z"])
def test_a_rigged_fbx_moves_once_with_its_group(plugin, cmds, tmp_path, up):
    """Skinned meshes stop inheriting, so the group moves the joints and the skin follows once (a Z-up turn or a move applied twice put the character upside down or off its spot)."""
    path = write_fbx(cmds, str(tmp_path), rig=True)
    cmds.upAxis(axis=up)
    try:
        cmds.currentTime(1)
        made = land(cmds, path, tmp_path, place=(30, 40, 20) if up == "y" else (30, 20, 40))
        cmds.currentTime(made["clip"]["start"])
        expected = [-20, 0, -30, 80, 100, 70] if up == "y" else [-20, -30, 0, 80, 70, 100]
        assert cmds.exactWorldBoundingBox(made["meshes"]) == pytest.approx(expected, abs=1e-3)
        for shape in made["meshes"]:
            assert not cmds.getAttr(cmds.listRelatives(shape, parent=True, fullPath=True)[0] + ".inheritsTransform")
        box = [10.0, 5.0, -20.0, 50.0, 45.0, 20.0]
        over = land(cmds, path, tmp_path, box=box, over="blockout")
        cmds.currentTime(over["clip"]["start"])
        assert cmds.exactWorldBoundingBox(over["meshes"]) == pytest.approx(box, abs=1e-3)
    finally:
        cmds.upAxis(axis="y")


def test_an_undone_fbx_import_freed_from_the_undo_queue_leaves_maya_stable(plugin, cmds, tmp_path):
    """Swapping the importer's Phong for openPBR inside the import made the next polyCube crash Maya 2027.2 once the
    import was undone and the queue freed (spec 6.7); the materials are kept as imported, and this path stays covered."""
    path = write_fbx(cmds, str(tmp_path))
    cmds.undoInfo(state=True, infinity=True)
    land(cmds, path, tmp_path)
    cmds.undo()
    cmds.flushUndo()
    cmds.polyCube(name="after")
    cmds.file(new=True, force=True)
    assert cmds.polyCube(name="still_fine")


def test_the_same_fbx_twice_lands_twice(plugin, cmds, tmp_path):
    path = write_fbx(cmds, str(tmp_path))
    first = land(cmds, path, tmp_path)
    second = land(cmds, path, tmp_path)
    assert first["namespace"] != second["namespace"] and second["meshes"], "the importer's merge mode would import nothing"


def test_an_fbx_lands_over_a_box(plugin, cmds, tmp_path):
    path = write_fbx(cmds, str(tmp_path))
    target = [10.0, 5.0, -20.0, 50.0, 45.0, 20.0]
    made = land(cmds, path, tmp_path, box=target, over="blockout")
    assert cmds.exactWorldBoundingBox(made["meshes"]) == pytest.approx(target, abs=1e-3)
    assert made["summary"].endswith(", over blockout")
