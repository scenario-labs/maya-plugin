"""Apply (spec 6.4): an edit result written onto the mesh it came from, in mayapy (0 CU).

Results are made like the fake server makes them, which is how the edit
models answered live on 2026-10-19: the sent mesh resized and centred, with a
new UV layout (UV unwrap) or the same UVs and a texture (Retexture). Every
apply is checked over two undo and redo cycles.
"""

import os

import pytest

from tests.fake_backend.fake_scenario import _edited_glb
from tests.maya.conftest import fresh


@pytest.fixture
def scene(plugin, cmds, tmp_path):
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    os.makedirs(tmp_path / "project", exist_ok=True)
    cmds.workspace(str(tmp_path / "project"), openWorkspace=True)
    yield tmp_path
    cmds.upAxis(axis="y")


def crate(cmds, name="crate"):
    node = cmds.polyCube(name=name, width=40, height=30, depth=30, subdivisionsX=2)[0]
    cmds.xform(node, translation=(120, 15, -60), rotation=(0, 35, 0))
    return node


def sent(cmds, node, task):
    """The job row an Edit selection run keeps: what was sent, for which task."""
    record = fresh("scenario_maya.maya.mesh_export").export([cmds.ls(node, long=True)[0]])
    edit = dict(record, task=task, asset_id="asset_test")
    return {"origin": {"edit": edit, "lane": "3d_edit"}, "model_name": "Test model"}


def result(row, tmp_path, task, side=1.0):
    with open(row["origin"]["edit"]["path"], "rb") as handle:
        data, _triangles, _dims = _edited_glb(task, side, handle.read())
    path = tmp_path / f"{task}_result.glb"
    path.write_bytes(data)
    return str(path)


def review(row, path, mode=""):
    apply = fresh("scenario_maya.maya.apply")
    return apply.compare(apply.gather(row, mode), path)


def uvs(cmds, shape, uv_set="map1"):
    return [tuple(round(c, 5) for c in uv) if uv else None for uv in fresh("scenario_maya.maya.mesh_export").corner_uvs(shape, uv_set) or []]


def planar(cmds, shape):
    """The fake UV model's layout, worked out from the mesh itself: u from x, v from z over the longest side."""
    from maya.api import OpenMaya as om

    selection = om.MSelectionList()
    selection.add(shape)
    fn = om.MFnMesh(selection.getDagPath(0))
    points = fn.getPoints(om.MSpace.kObject)
    _counts, connects = fn.getVertices()
    xs, ys, zs = [p.x for p in points], [p.y for p in points], [p.z for p in points]
    size = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    return [(round((points[v].x - min(xs)) / size, 5), round(1 - (points[v].z - min(zs)) / size, 5)) for v in connects]


def test_replace_uvs_writes_the_new_layout_and_one_undo_restores_everything(scene, cmds):
    node = crate(cmds)
    shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
    row = sent(cmds, node, "uv")
    seen = review(row, result(row, scene, "uv"))
    assert not seen.refusal, seen.refusal
    assert seen.title == "Replace UVs on crate"
    assert seen.changes == ["Writes Test model's UVs into map1 of crate (40 face corners)."]
    assert "The current map1 is copied to map1_scnPrev first." in seen.kept
    assert seen.confirms and seen.confirms[0].startswith("Delete the construction history of crate (polyCube1)")
    before, history = uvs(cmds, shape), cmds.listHistory(shape, pruneDagObjects=True)
    made = fresh("scenario_maya.maya.apply").run(seen)
    assert made["summary"] == "Replace UVs on crate"
    after = uvs(cmds, shape)
    assert after == planar(cmds, shape) and after != before
    assert cmds.polyUVSet(shape, query=True, allUVSets=True) == ["map1", "map1_scnPrev"]
    assert uvs(cmds, shape, "map1_scnPrev") == before, "the old layout is kept as a backup set"
    assert not cmds.listHistory(shape, pruneDagObjects=True)
    for _cycle in range(2):
        cmds.undo()
        assert uvs(cmds, shape) == before and cmds.polyUVSet(shape, query=True, allUVSets=True) == ["map1"]
        assert cmds.listHistory(shape, pruneDagObjects=True) == history, "undo brings the history back"
        cmds.redo()
        assert uvs(cmds, shape) == after and "map1_scnPrev" in cmds.polyUVSet(shape, query=True, allUVSets=True)


def test_replace_uvs_in_a_z_up_scene(scene, cmds):
    cmds.upAxis(axis="z")
    node = crate(cmds)
    cmds.delete(node, constructionHistory=True)
    shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
    row = sent(cmds, node, "uv")
    seen = review(row, result(row, scene, "uv", side=2.0))
    assert not seen.refusal and not seen.confirms, (seen.refusal, seen.confirms)
    fresh("scenario_maya.maya.apply").run(seen)
    # The sent file is Y-up: Maya's z went out as the file's y, so the layout follows x and -y here.
    assert len(uvs(cmds, shape)) == 40 and uvs(cmds, shape) != uvs(cmds, shape, "map1_scnPrev")


def test_replace_textures_keeps_the_uvs_and_assigns_a_new_material(scene, cmds):
    node = crate(cmds)
    shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
    row = sent(cmds, node, "retexture")
    seen = review(row, result(row, scene, "retexture", side=2.0))
    assert not seen.refusal, seen.refusal
    assert seen.write_uvs is None and not seen.confirms, "the result kept the UVs: nothing else changes"
    assert seen.changes == ["Assigns a new material from the result (base color) to crate."]
    assert "crate's UVs already match the result's: they are not changed." in seen.kept
    before = uvs(cmds, shape)
    folder = str(scene / "project" / "sourceimages" / "scenario" / "crate_retexture")
    made = fresh("scenario_maya.maya.apply").run(seen, {"scenario_job_id": "job_test"}, texture_folder=folder)
    engines = cmds.listConnections(shape, type="shadingEngine") or []
    assert engines == ["crate_retexture_SG"] and made["material"] == "crate_retexture_mtl", engines
    assert cmds.getAttr(made["material"] + ".scenario_job_id") == "job_test"
    assert os.listdir(folder), "the result's texture is written to the project"
    assert uvs(cmds, shape) == before and cmds.listHistory(shape, pruneDagObjects=True), "UVs and history untouched"
    for _cycle in range(2):
        cmds.undo()
        assert cmds.listConnections(shape, type="shadingEngine") == ["initialShadingGroup"]
        assert not cmds.objExists(made["material"])
        cmds.redo()
        assert cmds.objExists(made["material"]) and cmds.listConnections(shape, type="shadingEngine") == engines
    assert "lambert1" in cmds.ls(materials=True), "Maya's default material is never edited"


def test_per_face_materials_become_one_after_a_confirm(scene, cmds):
    node = crate(cmds)
    shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
    red = cmds.shadingNode("lambert", asShader=True, name="red")
    group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="red_SG")
    cmds.connectAttr(red + ".outColor", group + ".surfaceShader")
    cmds.sets(f"{node}.f[0:3]", edit=True, forceElement=group)
    row = sent(cmds, node, "retexture")
    seen = review(row, result(row, scene, "retexture"))
    assert "crate has 2 materials on its faces; they become one." in seen.confirms
    made = fresh("scenario_maya.maya.apply").run(seen)
    assert len(set(cmds.listConnections(shape, type="shadingEngine"))) == 1
    assert not cmds.sets(group, query=True), "no face keeps the old material"
    cmds.undo()
    assert cmds.sets(group, query=True), "undo gives the faces their material back"
    assert not cmds.objExists(made["material"])


def test_a_remeshed_result_is_refused_for_uvs_with_the_reason(scene, cmds):
    node = crate(cmds)
    row = sent(cmds, node, "uv")
    seen = review(row, result(row, scene, "remesh"))
    assert seen.refusal == "The result is not the same surface as crate: The result has 80 triangles; the mesh splits into 20. Import places it over crate instead."
    with pytest.raises(fresh("scenario_maya.maya.apply").ApplyError):
        fresh("scenario_maya.maya.apply").run(seen)


def names(cmds, node):
    return sorted(shape.split("|")[-1] for shape in cmds.listRelatives(node, shapes=True, fullPath=True) or [])


def default_material(cmds):
    return cmds.listConnections("initialShadingGroup.surfaceShader")[0]  # openPBR_shader1 in Maya 2027


def test_replace_geometry_swaps_the_shape_and_one_undo_restores_it(scene, cmds):
    node = crate(cmds)
    uuid = cmds.ls(node, uuid=True)[0]
    shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
    probe = cmds.createNode("closestPointOnMesh", name="probe")
    cmds.connectAttr(shape + ".worldMesh[0]", probe + ".inMesh")
    box, history = cmds.exactWorldBoundingBox(node), cmds.listHistory(shape, pruneDagObjects=True)
    row = sent(cmds, node, "remesh")
    seen = review(row, result(row, scene, "remesh"))
    assert not seen.refusal and not seen.confirms, (seen.refusal, seen.confirms)
    assert seen.title == "Replace geometry on crate"
    assert seen.changes == ["Replaces the geometry of crate (10 faces) with Test model's result (80 triangles)."]
    assert seen.kept[:3] == [
        f"The new mesh keeps crate's material ({default_material(cmds)}).",
        "The transform crate: its place, attributes, parent, sets and connections.",
        "The old shape, hidden, as crateShape_scnPrev with its construction history.",
    ]
    assert seen.kept[3].startswith("Checked by surface distance: the farthest point is 0.0% of crate's size away.")
    made = fresh("scenario_maya.maya.apply").run(seen, {"scenario_job_id": "job_test"})
    assert made["summary"] == "Replace geometry on crate: 80 triangles"

    def replaced():
        assert names(cmds, node) == ["crateShape", "crateShape_scnPrev"] and cmds.ls(node, uuid=True)[0] == uuid
        new, old = (f"|{node}|{name}" for name in names(cmds, node))
        assert cmds.polyEvaluate(new, face=True) == 80 and cmds.getAttr(old + ".intermediateObject")
        assert cmds.exactWorldBoundingBox(new) == pytest.approx(box, abs=1e-3), "the new mesh sits where the old one was"
        assert cmds.listConnections(probe + ".inMesh", plugs=True) == ["crateShape.worldMesh"], "the probe follows the new shape"
        assert cmds.listConnections(new, type="shadingEngine") == ["initialShadingGroup"]
        assert cmds.getAttr(new + ".scenario_job_id") == "job_test" and not cmds.listHistory(new, pruneDagObjects=True)
        assert cmds.listHistory(old, pruneDagObjects=True) == history, "the old shape keeps its history"
        assert not cmds.namespace(exists=":scn_stage"), "the staging namespace is gone"

    replaced()
    for _cycle in range(2):
        cmds.undo()
        assert names(cmds, node) == ["crateShape"] and not cmds.getAttr(shape + ".intermediateObject")
        assert cmds.polyEvaluate(node, face=True) == 10 and cmds.listHistory(shape, pruneDagObjects=True) == history
        assert cmds.listConnections(probe + ".inMesh", plugs=True) == ["crateShape.worldMesh"] and cmds.exactWorldBoundingBox(node) == pytest.approx(box, abs=1e-3)
        assert not cmds.namespace(exists=":scn_stage") and cmds.ls(type="mesh") == ["crateShape"]
        cmds.redo()
        replaced()


@pytest.mark.parametrize("up, unit", [("z", "cm"), ("y", "m"), ("z", "mm")])
def test_replace_geometry_in_other_up_axes_and_units(scene, cmds, up, unit):
    cmds.upAxis(axis=up)
    cmds.currentUnit(linear=unit)
    try:
        node = crate(cmds)
        cmds.move(25, 0, -10, f"{node}.vtx[*]", relative=True, objectSpace=True)  # off-centre in object space: the fit's offset counts
        cmds.delete(node, constructionHistory=True)
        box = cmds.exactWorldBoundingBox(node)
        row = sent(cmds, node, "remesh")
        seen = review(row, result(row, scene, "remesh", side=2.0))
        assert not seen.refusal, seen.refusal
        fresh("scenario_maya.maya.apply").run(seen)
        assert cmds.polyEvaluate(node, face=True) == 80
        assert cmds.exactWorldBoundingBox(f"|{node}|crateShape") == pytest.approx(box, abs=1e-3 * max(abs(v) for v in box))
    finally:
        cmds.currentUnit(linear="cm")


def test_replace_geometry_with_a_textured_result_assigns_its_material(scene, cmds):
    node = crate(cmds)
    row = sent(cmds, node, "remesh")
    folder = str(scene / "project" / "sourceimages" / "scenario" / "crate_remesh")
    seen = review(row, result(row, scene, "retexture", side=2.0), mode="REMESH")  # same shape, with a texture
    assert seen.changes[1] == f"Assigns the result's material (base color) to the new mesh; {default_material(cmds)} stays on the old shape."
    made = fresh("scenario_maya.maya.apply").run(seen, texture_folder=folder)
    assert made["material"] == "crate_remesh_mtl" and os.listdir(folder)
    assert cmds.listConnections(f"|{node}|crateShape", type="shadingEngine") == ["crate_remesh_SG"]
    cmds.undo()
    assert not cmds.objExists("crate_remesh_mtl") and names(cmds, node) == ["crateShape"]
    cmds.flushUndo()  # regression: freeing the undone build must leave Maya stable (spec 6.7)
    cmds.polyCube(name="after")
    cmds.file(new=True, force=True)
    assert cmds.polyCube(name="still_fine")


def test_replace_geometry_refuses_another_shape_and_instances(scene, cmds):
    node = crate(cmds)
    ball = cmds.polySphere(name="ball", subdivisionsAxis=24, subdivisionsHeight=12)[0]
    other = sent(cmds, ball, "remesh")
    seen = review(sent(cmds, node, "remesh"), result(other, scene, "remesh"))
    assert seen.refusal.startswith("The result is not the same shape as crate (") and seen.refusal.endswith(". Import places it over crate instead."), seen.refusal
    cmds.instance(node, name="crate_twin")
    seen = review(sent(cmds, node, "remesh"), result(other, scene, "remesh"))
    assert seen.refusal.startswith("crate is instanced.")


def test_the_same_uvs_are_not_written_again(scene, cmds):
    node = crate(cmds)
    row = sent(cmds, node, "uv")
    seen = review(row, result(row, scene, "retexture"), mode="UV")
    assert seen.refusal == "The result's UVs are already those of map1 on crate: nothing to change."


def test_a_deformed_or_missing_mesh_is_refused(scene, cmds):
    node = crate(cmds)
    row = sent(cmds, node, "uv")
    path = result(row, scene, "uv")
    joint = cmds.joint(position=(120, 0, -60))
    cmds.skinCluster(joint, node)
    seen = review(row, path)
    assert seen.refusal.startswith("crate is deformed (skinCluster1).")
    cmds.delete(node)
    assert review(row, path).refusal.startswith("crate is no longer in the scene")


def test_a_mesh_changed_after_the_review_is_not_touched(scene, cmds):
    node = crate(cmds)
    shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
    cmds.delete(node, constructionHistory=True)
    row = sent(cmds, node, "uv")
    seen = review(row, result(row, scene, "uv"))
    before = uvs(cmds, shape)
    cmds.move(0, 1, 0, f"{node}.vtx[0]", relative=True)
    apply = fresh("scenario_maya.maya.apply")
    with pytest.raises(apply.ApplyError, match="crate changed after the review. Open Apply again."):
        apply.run(seen)
    assert uvs(cmds, shape) == before
    again = review(row, result(row, scene, "uv"))
    assert again.refusal.endswith("Import places it over crate instead.") and "not on the mesh's vertices" in again.refusal


def test_undoing_a_texture_apply_leaves_maya_stable(scene, cmds):
    """Regression: undoing API deletions of shading nodes alone, then freeing them, crashed the next polyCube."""
    node = crate(cmds)
    row = sent(cmds, node, "retexture")
    fresh("scenario_maya.maya.apply").run(review(row, result(row, scene, "retexture")))
    cmds.undo()
    cmds.flushUndo()
    cmds.polyCube(name="after")
    cmds.file(new=True, force=True)
    assert cmds.polyCube(name="still_fine")
