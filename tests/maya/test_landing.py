"""Image landings in mayapy: card, material on selection, image plane; one undo step each (0 CU)."""

import json
import os
import struct
import zlib

import pytest

from tests.maya.conftest import fresh

ATTRS = {
    "scenario_asset_id": "asset_test000001",
    "scenario_job_id": "job_test000001",
    "scenario_model_id": "model_openai-gpt-image-2-5-flare",
    "scenario_model_name": "GPT Image 2.5 Flare",
    "scenario_prompt": "a carved wooden treasure chest",
    "scenario_parameters": "{}",
    "scenario_input_asset_ids": "[]",
    "scenario_quoted_cu": "11",
    "scenario_charged_cu": "11",
}


def png(path, width, height, alpha=False):
    channels = 4 if alpha else 3
    pixel = bytes([180, 120, 60, 128][:channels])
    raw = b"".join(b"\x00" + pixel * width for _ in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


@pytest.fixture
def landing(cmds, scripts_on_path, tmp_path):
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    cmds.workspace(str(tmp_path), openWorkspace=True)
    return fresh("scenario_maya.maya.landing")


def user_steps(cmds):
    cube = cmds.polyCube(name="userCube")[0]
    cmds.move(1, 2, 3, cube)
    return cube


def test_card_lands_in_one_undo_step(cmds, landing, tmp_path):
    image = png(str(tmp_path / "chest.png"), 64, 32)
    cube = user_steps(cmds)
    before = set(cmds.ls())
    made = landing.land(image, ATTRS, "card")
    group = made["top"]
    assert made["namespace"].startswith(":scn_carved_wooden_treasure_chest") and group.startswith("scn_carved_wooden_treasure_chest")
    assert cmds.getAttr(group + ".scenario_asset_id") == "asset_test000001"
    assert cmds.getAttr(made["file"] + ".scenario_role") == "albedo"
    assert cmds.getAttr(made["file"] + ".colorSpace") == landing.SRGB
    assert cmds.getAttr(made["file"] + ".fileTextureName") == image
    assert cmds.nodeType(made["material"]) == "openPBRSurface"
    width, height = made["size"]
    assert abs(width / height - 2.0) < 1e-6
    assert cmds.ls(selection=True) == [group]
    uuid = cmds.fileInfo("scenario_scene_uuid", query=True)
    assert uuid and len(uuid[0]) == 32
    assert cmds.undoInfo(query=True, undoName=True) == made["undo"]
    created = set(cmds.ls()) - before
    cmds.undo()
    assert not (created & set(cmds.ls())), "one undo removes every node the card made"
    assert not cmds.namespace(exists=made["namespace"])
    assert cmds.getAttr(cube + ".translate")[0] == (1.0, 2.0, 3.0), "the user's own step is still there"
    cmds.redo()
    assert cmds.objExists(group) and cmds.getAttr(group + ".scenario_prompt") == "a carved wooden treasure chest"
    cmds.undo()
    cmds.undo()
    assert cmds.getAttr(cube + ".translate")[0] == (0.0, 0.0, 0.0), "earlier undo history is intact"


def test_card_faces_the_camera_at_its_centre_of_interest(cmds, landing, tmp_path):
    image = png(str(tmp_path / "wide.png"), 32, 32)
    cam, shape = cmds.camera(name="shotCam")
    cmds.xform(cam, worldSpace=True, translation=(0, 0, 20), rotation=(0, 30, 0))
    cmds.setAttr(shape + ".centerOfInterest", 10)
    made = landing.land(image, ATTRS, "card", camera=(cam, shape))
    target = cmds.camera(shape, query=True, worldCenterOfInterest=True)
    position = cmds.xform(made["top"], query=True, worldSpace=True, translation=True)
    assert all(abs(a - b) < 1e-4 for a, b in zip(position, target, strict=True))
    assert abs(cmds.xform(made["top"], query=True, worldSpace=True, rotation=True)[1] - 30) < 1e-4


def test_material_on_selection_and_undo_restores_the_old_one(cmds, landing, tmp_path):
    image = png(str(tmp_path / "rgba.png"), 16, 16, alpha=True)
    cube = cmds.polyCube(name="crate")[0]
    sphere = cmds.polySphere(name="ball")[0]
    shape = cmds.listRelatives(cube, shapes=True)[0]
    old = cmds.listConnections(shape, type="shadingEngine")
    cmds.select([cube, sphere + ".f[0:10]"])
    made = landing.land(image, ATTRS, "material")
    assert made["top"] is None and made["targets"] == ["crate", "ball.f[0:10]"]
    group = cmds.listConnections(shape, type="shadingEngine")
    assert group != old and cmds.listConnections(group[0] + ".surfaceShader") == [made["material"].split("|")[-1]]
    assert cmds.listConnections(made["material"] + ".geometryOpacity"), "alpha drives opacity"
    assert sorted(cmds.ls(selection=True)) == sorted([cube, sphere + ".f[0:10]"]), "selection kept"
    cmds.undo()
    assert cmds.listConnections(shape, type="shadingEngine") == old
    assert not cmds.objExists(made["material"])


def test_image_plane_on_the_camera(cmds, landing, tmp_path):
    image = png(str(tmp_path / "ref.png"), 40, 20)
    made = landing.land(image, ATTRS, "image_plane", camera=("persp", "perspShape"))
    shape = made["image_plane"]
    assert cmds.getAttr(shape + ".imageName") == image
    assert cmds.getAttr(shape + ".colorSpace") == landing.SRGB
    assert cmds.getAttr(shape + ".scenario_model_id") == ATTRS["scenario_model_id"]
    assert landing.landed_nodes() == sorted(cmds.ls(shape, long=True))
    cmds.undo()
    assert not cmds.objExists(shape)


def test_refusals_change_nothing(cmds, landing, tmp_path):
    image = png(str(tmp_path / "x.png"), 8, 8)
    cmds.select(clear=True)
    before = sorted(cmds.ls())
    with pytest.raises(landing.LandingError, match="select a mesh"):
        landing.land(image, ATTRS, "material")
    with pytest.raises(landing.LandingError, match="missing"):
        landing.land(str(tmp_path / "gone.png"), ATTRS, "card")
    assert sorted(cmds.ls()) == before


def test_two_imports_get_separate_namespaces(cmds, landing, tmp_path):
    image = png(str(tmp_path / "a.png"), 8, 8)
    first = landing.land(image, ATTRS, "card")
    second = landing.land(image, ATTRS, "card")
    assert first["namespace"] != second["namespace"]
    assert json.loads(cmds.getAttr(second["top"] + ".scenario_input_asset_ids")) == []
    assert os.path.exists(image)
