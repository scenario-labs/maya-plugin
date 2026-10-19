"""GLB results built as Maya nodes in one undo step (spec 6.7, 7.3), on hand-written files (0 CU)."""

import os

import pytest

from tests import glb_samples
from tests.maya.conftest import fresh

ATTRS = {"scenario_asset_id": "asset_test3d0001", "scenario_model_id": "model_test-3d", "scenario_prompt": "a wooden crate"}


@pytest.fixture
def land(cmds, plugin, tmp_path):
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    cmds.workspace(str(tmp_path), openWorkspace=True)
    landing = fresh("scenario_maya.maya.landing")

    def run(path, **kwargs):
        return landing.land_model(path, kwargs.pop("attributes", ATTRS), texture_folder=str(tmp_path / "textures"), **kwargs)

    run.landing = landing
    return run


def close(a, b, tolerance=1e-3):
    return all(abs(x - y) < tolerance for x, y in zip(a, b, strict=True))


def test_textured_mesh_welds_and_wires_pbr_textures(cmds, land, tmp_path):
    made = land(glb_samples.textured_quad(str(tmp_path / "crate.glb")))
    checks = made["checks"]
    assert (checks["faces"], checks["vertices"]) == (2, 4), "split corners are welded back"
    assert close(checks["size_metres"], [1.0, 1.0, 0.0]) and close(checks["size_scene_units"], [100.0, 100.0, 0.0])
    assert checks["uv_sets"] == {"QuadShape": ["map1"]} and checks["missing_textures"] == [] and checks["textures"] == 3
    assert cmds.getAttr(made["top"] + ".scenario_asset_id") == "asset_test3d0001"
    assert made["namespace"].startswith(":scn_wooden_crate")
    quad = made["meshes"][0].rsplit("|", 1)[0]
    assert close(cmds.xform(quad, query=True, worldSpace=True, translation=True), [0.0, 50.0, 0.0])
    shader = made["shaders"][0]
    assert cmds.nodeType(shader) == "openPBRSurface"
    base = cmds.listConnections(shader + ".baseColor", source=True)[0]
    assert cmds.getAttr(base + ".colorSpace") == "sRGB Encoded Rec.709 (sRGB)"
    packed = cmds.listConnections(shader + ".specularRoughness", source=True, plugs=True)[0]
    assert packed.endswith(".outColorG") and cmds.getAttr(packed.split(".")[0] + ".colorSpace") == "Raw"
    assert cmds.listConnections(shader + ".baseMetalness", source=True, plugs=True)[0].endswith(".outColorB")
    assert cmds.nodeType(cmds.listConnections(shader + ".normalCamera", source=True)[0]) == "bump2d"
    assert sorted(os.path.basename(p) for p in made["textures"]) == ["wooden_crate_base_color.png", "wooden_crate_metal_rough.png", "wooden_crate_normal.png"]
    assert cmds.ls(selection=True, long=True) == [made["top"]]
    assert made["summary"] == "Imported wooden_crate: 2 faces"


def test_one_undo_removes_the_import_and_redo_restores_the_same_nodes(cmds, land, tmp_path):
    cube = cmds.polyCube(name="userCube")[0]
    cmds.move(1, 2, 3, cube)
    before = set(cmds.ls())
    made = land(glb_samples.textured_quad(str(tmp_path / "crate.glb")))
    created = set(cmds.ls()) - before
    uuids = sorted(cmds.ls(list(created), uuid=True))
    assert cmds.undoInfo(query=True, undoName=True) == made["undo"]
    cmds.undo()
    assert not (created & set(cmds.ls())), "materials, textures and meshes all go"
    assert not cmds.namespace(exists=made["namespace"])
    assert cmds.getAttr(cube + ".translate")[0] == (1.0, 2.0, 3.0)
    cmds.redo()
    assert sorted(cmds.ls(list(created), uuid=True)) == uuids, "redo brings back the same nodes"
    assert cmds.getAttr(made["top"] + ".scenario_prompt") == "a wooden crate"
    cmds.undo()
    cmds.undo()
    assert cmds.getAttr(cube + ".translate")[0] == (0.0, 0.0, 0.0), "earlier undo history is intact"
    assert all(os.path.isfile(p) for p in made["textures"]), "files on disk stay after undo"


def test_skin_and_clip_follow_gltf(cmds, land, tmp_path):
    made = land(glb_samples.skinned_strip(str(tmp_path / "strip.glb")), attributes={})
    checks = made["checks"]
    assert checks["joints"] == 2 and checks["influences"] == 2
    assert checks["clip"]["name"] == "Bend" and checks["other_clips"] == ["Idle"]
    spine = [joint for joint in made["joints"] if joint.endswith("Spine")][0]
    assert close(cmds.getAttr(spine + ".jointOrient")[0], (30.0, 0.0, 0.0)), "rest rotation lives in jointOrient"
    assert cmds.getAttr(spine + ".segmentScaleCompensate") is False
    shape = made["meshes"][0]
    start = cmds.playbackOptions(query=True, minTime=True)
    cmds.currentTime(start)
    assert close(cmds.getAttr(spine + ".rotate")[0], (0.0, 0.0, 0.0))
    assert close(cmds.pointPosition(shape + ".vtx[5]", world=True), [10.0, 200.0, 0.0]), "bind pose, the mesh node's own transform ignored"
    cmds.currentTime(start + checks["clip"]["end"] - checks["clip"]["start"])
    local = glb_samples.apply(glb_samples._invert_rigid(glb_samples._matrix(glb_samples.REST, (0, 1, 0))), (0.1, 2.0, 0.0))
    expected = [value * 100.0 for value in glb_samples.apply(glb_samples._matrix(glb_samples.KEY, (0, 1, 0)), local)]
    assert close(cmds.pointPosition(shape + ".vtx[5]", world=True), expected), "keys converted for jointOrient match glTF"


def test_morph_target_and_weight_keys(cmds, land, tmp_path):
    made = land(glb_samples.morph_quad(str(tmp_path / "flag.glb")), attributes={})
    assert made["checks"]["blend_shape_targets"] == 1
    shape = made["meshes"][0]
    start = cmds.playbackOptions(query=True, minTime=True)
    cmds.currentTime(start)
    assert close(cmds.pointPosition(shape + ".vtx[2]", world=True), [100.0, 100.0, 0.0])
    cmds.currentTime(start + 24)
    assert close(cmds.pointPosition(shape + ".vtx[2]", world=True), [100.0, 100.0, 50.0])
    blend = made["blend_shapes"][0]
    assert cmds.aliasAttr(blend, query=True)[0] == "Lift"


@pytest.mark.parametrize("unit, per_metre", [("m", 1.0), ("mm", 1000.0)])
def test_sizes_hold_in_metre_and_millimetre_scenes(cmds, land, tmp_path, unit, per_metre):
    """Mesh points, bind matrices and distance keys go through the API in centimetres, whatever the scene unit."""

    def world_points(sample):
        made = land(sample(str(tmp_path / f"{sample.__name__}.glb")), attributes={})
        start = cmds.playbackOptions(query=True, minTime=True)
        points = []
        for frame in (start, start + 24):
            cmds.currentTime(frame)
            for shape in made["meshes"]:
                points += [cmds.pointPosition(f"{shape}.vtx[{i}]", world=True) for i in range(cmds.polyEvaluate(shape, vertex=True))]
        return points

    samples = (glb_samples.skinned_strip, glb_samples.morph_quad, glb_samples.moving_quad)
    in_cm = {sample: world_points(sample) for sample in samples}
    cmds.file(new=True, force=True)
    cmds.currentUnit(linear=unit)
    try:
        for sample in samples:
            scaled = [[value * per_metre / 100.0 for value in point] for point in in_cm[sample]]
            found = world_points(sample)
            assert len(found) == len(scaled) and all(close(a, b, 1e-3 * per_metre / 100.0) for a, b in zip(found, scaled, strict=True)), sample.__name__
    finally:
        cmds.currentUnit(linear="cm")


def test_z_up_scene_turns_the_root(cmds, land, tmp_path):
    cmds.upAxis(axis="z", rotateView=False)
    try:
        made = land(glb_samples.textured_quad(str(tmp_path / "crate.glb")))
        assert close(cmds.getAttr(made["top"] + ".rotate")[0], (90.0, 0.0, 0.0))
        assert close(made["checks"]["size_metres"], [1.0, 0.0, 1.0]), "upright in Z-up"
    finally:
        cmds.upAxis(axis="y", rotateView=False)


def test_refusals_say_why(cmds, land, tmp_path):
    fbx = tmp_path / "result.glb"
    fbx.write_bytes(b"Kaydara FBX Binary  \x00\x1a\x00")
    with pytest.raises(land.landing.LandingError, match="FBX file"):
        land(str(fbx))
    writer = glb_samples.Writer()
    writer.doc["extensionsUsed"] = ["KHR_draco_mesh_compression"]
    with pytest.raises(land.landing.LandingError, match="Draco"):
        land(writer.save(str(tmp_path / "draco.glb")))
    with pytest.raises(land.landing.LandingError, match="missing"):
        land(str(tmp_path / "gone.glb"))


def test_import_glb_menu_action_writes_textures_in_the_project(cmds, land, tmp_path):
    made = fresh("scenario_maya.ui.panel").import_glb(glb_samples.textured_quad(str(tmp_path / "Old Crate.glb")))
    folder = os.path.join(str(tmp_path), "sourceimages", "scenario", "old_crate")
    assert sorted(os.listdir(folder)) == ["old_crate_base_color.png", "old_crate_metal_rough.png", "old_crate_normal.png"]
    assert made["checks"]["faces"] == 2 and not cmds.attributeQuery("scenario_asset_id", node=made["top"], exists=True)


def test_an_undone_import_freed_from_the_undo_queue_leaves_maya_stable(plugin, cmds, tmp_path):
    """Maya 2027.2 crashed on the next polyCube after an API modifier that deleted shading nodes, and no DAG node,
    was freed (spec 6.7). An import's undo deletes its top group too; this keeps that path covered."""
    from tests import glb_samples

    landing = plugin("scenario_maya.maya.landing")
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    path = glb_samples.textured_quad(str(tmp_path / "quad.glb"))
    landing.land_model(path, {}, texture_folder=str(tmp_path / "tex"), label="quad")
    cmds.undo()
    cmds.flushUndo()
    cmds.polyCube(name="after")
    cmds.file(new=True, force=True)
    assert cmds.polyCube(name="still_fine")
