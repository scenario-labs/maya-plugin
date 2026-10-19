"""Selected meshes written as a GLB for an edit model (spec 6.3, 7.5), read back by the plug-in's importer (0 CU)."""

import os

import pytest

from tests.glb_samples import png_bytes
from tests.maya.conftest import fresh


@pytest.fixture
def export(cmds, plugin, tmp_path):
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    cmds.workspace(str(tmp_path), openWorkspace=True)
    module = fresh("scenario_maya.maya.mesh_export")
    module.landing = fresh("scenario_maya.maya.landing")
    module.gltf = fresh("scenario_maya.core.gltf")
    yield module
    cmds.upAxis(axis="y", rotateView=False)
    cmds.currentUnit(linear="cm")


def crate(cmds, tmp_path, textured=True):
    """A bevelled 80 x 60 x 60 cm box, moved, turned and scaled, with a PNG on a lambert."""
    box = cmds.polyCube(name="crate_GEO", width=80, height=60, depth=60)[0]
    cmds.polyBevel3(box, offset=4, segments=1)
    cmds.xform(box, translation=(120, 30, -40), rotation=(0, 35, 0), scale=(1.5, 1.5, 1.5))
    if textured:
        path = tmp_path / "crate_wood.png"
        path.write_bytes(png_bytes(8, 8, (150, 100, 50)))
        shader = cmds.shadingNode("lambert", asShader=True, name="crateWood_MAT")
        engine = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="crateWood_SG")
        cmds.connectAttr(shader + ".outColor", engine + ".surfaceShader")
        texture = cmds.shadingNode("file", asTexture=True, name="crateWood_tex")
        cmds.setAttr(texture + ".fileTextureName", str(path), type="string")
        cmds.connectAttr(texture + ".outColor", shader + ".color")
        cmds.sets(box, edit=True, forceElement=engine)
    return cmds.ls(box, long=True)[0]


def local_points(cmds, shape):
    count = cmds.polyEvaluate(shape, vertex=True)
    return sorted(tuple(round(v, 3) for v in cmds.xform(f"{shape}.vtx[{i}]", query=True, objectSpace=True, translation=True)) for i in range(count))


def uv_pairs(cmds, shape):
    flat = cmds.polyEditUV(f"{shape}.map[*]", query=True)
    return {(round(flat[i], 4), round(flat[i + 1], 4)) for i in range(0, len(flat), 2)}


def signed_volume(cmds, shape):
    """Positive when faces wind outward (the right-hand rule), as Maya and glTF both expect."""
    from maya.api import OpenMaya as om

    selection = om.MSelectionList()
    selection.add(shape)
    fn = om.MFnMesh(selection.getDagPath(0))
    points = fn.getPoints()
    _counts, triangles = fn.getTriangles()
    total = 0.0
    for start in range(0, len(triangles), 3):
        a, b, c = (points[triangles[start + k]] for k in range(3))
        total += (a.x * (b.y * c.z - b.z * c.y) - a.y * (b.x * c.z - b.z * c.x) + a.z * (b.x * c.y - b.y * c.x)) / 6.0
    return total


def test_selection_is_written_in_object_space_with_neutral_names(cmds, export, tmp_path):
    box = crate(cmds, tmp_path)
    cmds.select(f"{box}.f[0:3]")
    assert export.selected_meshes() == [box], "a face selection counts as its object"
    made = export.export(export.selected_meshes())
    assert made["path"].endswith(".glb") and os.sep.join(("images", "scenario", "captures")) in made["path"]
    doc = export.gltf.Document.load(made["path"])
    shape = cmds.listRelatives(box, shapes=True, fullPath=True)[0]
    assert made["triangles"] == cmds.polyEvaluate(shape, triangle=True) == doc.summary()["triangles"]
    assert made["faces"] == cmds.polyEvaluate(shape, face=True)
    names = [node["name"] for node in doc.json["nodes"]] + [material["name"] for material in doc.json["materials"]]
    assert names == ["scn_input_0", "scn_material_0"] and made["names"] == {"scn_input_0": box, "scn_material_0": "crateWood_SG"}
    assert b"crate" not in open(made["path"], "rb").read().lower(), "no scene name leaves the machine"
    position = doc.accessor(doc.json["meshes"][0]["primitives"][0]["attributes"]["POSITION"])
    assert [round(v, 4) for v in position.max] == [0.4, 0.3, 0.3], "object space, metres: transforms stay in Maya"
    assert doc.image_bytes(0)[0] == (tmp_path / "crate_wood.png").read_bytes()
    record = made["meshes"][0]
    assert record["uuid"] == cmds.ls(box, uuid=True)[0] and record["uv_set"] == "map1"
    assert [round(v, 3) for v in record["world_matrix"][12:15]] == [120.0, 30.0, -40.0]
    assert made["notes"] == []


def test_the_importer_reads_the_export_back_as_the_same_mesh(cmds, export, tmp_path):
    box = crate(cmds, tmp_path)
    shape = cmds.listRelatives(box, shapes=True, fullPath=True)[0]
    made = export.export([box])
    back = export.landing.land_model(made["path"], {}, texture_folder=str(tmp_path / "back"), label="back")
    other = back["meshes"][0]
    assert local_points(cmds, other) == local_points(cmds, shape), "same points, welded back"
    assert cmds.polyEvaluate(other, triangle=True) == cmds.polyEvaluate(shape, triangle=True)
    assert signed_volume(cmds, other) == pytest.approx(signed_volume(cmds, shape), rel=1e-4) and signed_volume(cmds, shape) > 0, "faces keep their winding"
    assert uv_pairs(cmds, other) == uv_pairs(cmds, shape), "UVs come back unchanged (glTF flips V; the importer flips it back)"


def test_z_up_and_metre_scenes(cmds, export, tmp_path):
    cmds.upAxis(axis="z", rotateView=False)
    cmds.currentUnit(linear="m")
    box = cmds.polyCube(name="tall", width=0.2, height=0.4, depth=1.0)[0]  # 1 m along the scene's up axis (Z)
    made = export.export([cmds.ls(box, long=True)[0]])
    doc = export.gltf.Document.load(made["path"])
    position = doc.accessor(doc.json["meshes"][0]["primitives"][0]["attributes"]["POSITION"])
    assert [round(v, 4) for v in position.max] == [0.1, 0.5, 0.2], "Z-up becomes glTF's Y-up; metres stay metres"
    assert made["up_axis"] == "z"
    back = export.landing.land_model(made["path"], {}, texture_folder=str(tmp_path / "back"), label="back")
    box_bounds = cmds.exactWorldBoundingBox(back["top"])
    assert [round(v, 4) for v in box_bounds] == [-0.1, -0.2, -0.5, 0.1, 0.2, 0.5], "the importer turns it back"


def test_untextured_mesh_without_uvs_is_sent_with_a_note(cmds, export):
    ball = cmds.polySphere(name="ball", subdivisionsAxis=8, subdivisionsHeight=6)[0]
    cmds.polyMapDel(f"{ball}.f[*]")
    made = export.export([cmds.ls(ball, long=True)[0]])
    doc = export.gltf.Document.load(made["path"])
    assert "TEXCOORD_0" not in doc.json["meshes"][0]["primitives"][0]["attributes"]
    assert made["notes"] == ["ballShape has no UVs: sent without them"]
    pbr = doc.json["materials"][0]["pbrMetallicRoughness"]
    assert "baseColorTexture" not in pbr and pbr["baseColorFactor"][3] == 1.0


def test_fingerprint_follows_the_mesh_not_its_transform(cmds, export, tmp_path):
    box = crate(cmds, tmp_path, textured=False)
    first = export.export([box])["meshes"][0]["fingerprint"]
    cmds.move(0, 500, 0, box, relative=True)
    assert export.export([box])["meshes"][0]["fingerprint"] == first
    cmds.move(0, 1, 0, f"{box}.vtx[0]", relative=True)
    moved = export.export([box])["meshes"][0]["fingerprint"]
    assert moved != first
    cmds.polyEditUV(f"{box}.map[0]", uValue=0.1, relative=True)
    assert export.export([box])["meshes"][0]["fingerprint"] != moved, "UV edits count"


def test_same_mesh_gives_the_same_bytes(cmds, export, tmp_path):
    box = crate(cmds, tmp_path)
    assert export.export([box])["sha256"] == export.export([box])["sha256"], "an unchanged mesh is not uploaded twice"
