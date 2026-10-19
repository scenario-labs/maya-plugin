"""The 3D tab's Motion mode in mayapy against the fake Scenario server (0 CU): a
prompt alone on a model that makes its own character; a character (a group of
meshes) sent once to a model that rigs it, priced, generated and imported over
it with its joints and clip; the frame rate taken from the scene; Re-run.

The fake server answers like the motion models did live on 2026-10-19: Cartwheel
refuses to price without a character, Uthana prices one in, and a result is a
skinned, keyed character (here the two-joint strip of the GLB samples).
"""

import math

import pytest

from tests.maya.conftest import qt_pump_until
from tests.maya.test_three_d_image_lane import panel  # noqa: F401  (the same panel fixture)

MESHY = "model_meshy-text-to-motion"
CARTWHEEL = "model_cartwheel-text-to-motion"
UTHANA = "model_uthana-text-to-motion-3.0"


def motion_page(panel, model=MESHY):  # noqa: F811
    panel.select_lane("3d_motion")
    page = panel.lane
    qt_pump_until(lambda: page.fields is not None, timeout=10)
    if page.model_id != model:
        page.set_model(model)
        qt_pump_until(lambda: page.form is not None and page.form.model_id == model, timeout=10)
    return page


def robot(cmds):
    """A character made of two meshes under one group, standing off the origin."""
    body = cmds.polyCube(name="robot_body", width=40, height=50, depth=30)[0]
    cmds.move(0, 45, 0, body)
    head = cmds.polyCube(name="robot_head", width=25, height=25, depth=25)[0]
    cmds.move(0, 82.5, 0, head)
    group = cmds.group(body, head, name="robot")
    cmds.move(150, 0, -80, group)
    cmds.select(group)
    return group


def ready(page):
    return any(card.row.get("state") == "ready" for card in page.cards.values())


def test_the_3d_tab_has_a_motion_mode_that_works_from_a_prompt(panel):  # noqa: F811
    panel.select_tab("3d")
    assert panel.mode_button["3d_motion"].text() == "Motion"
    page = motion_page(panel)
    assert page.form.model_id == MESHY, "the default makes its own character"
    assert page.mesh.isVisible() and page.mesh.title.text() == "Character (made by the model)"
    assert not page.mesh.use_button.isEnabled() and "Pick Uthana or Cartwheel" in page.mesh.note.text()
    assert page.prompt.toPlainText() == "waves hello with the right hand"
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    assert page.generate_button.text() == "Generate . 40 CU"


def test_uthana_takes_the_scene_frame_rate_and_an_optional_character(panel, fake, cmds):  # noqa: F811
    cmds.currentUnit(time="film")
    page = motion_page(panel, UTHANA)
    assert page.values()["fps"] == 24, "the model offers 24 fps, the scene's rate"
    assert page.mesh.title.text() == "Character (optional)" and page.mesh.use_button.isEnabled()
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    assert page.generate_button.text() == "Generate . 104 CU", "no character needed"
    robot(cmds)
    page.mesh.use_selection()
    qt_pump_until(lambda: page.generate_button.text() == "Generate . 124 CU", timeout=15)
    assert page.values()["characterFile"] == page.mesh.asset_id()


def test_cartwheel_needs_a_character_then_lands_over_it(panel, fake, cmds):  # noqa: F811
    page = motion_page(panel, CARTWHEEL)
    assert page.mesh.title.text() == "Character"
    qt_pump_until(lambda: page.generate_button.text() == "Select your character", timeout=10)
    assert not page.generate_button.isEnabled()
    assert page.fields.values()["outputFormat"] == "fbx-maya", "Maya's FBX, never a scene file"
    group = robot(cmds)
    before = cmds.undoInfo(query=True, undoName=True)
    page.mesh.use_selection()
    assert cmds.undoInfo(query=True, undoName=True) == before, "writing the character is not an undo step"
    record = page.mesh.item["record"]
    assert len(record["meshes"]) == 2 and page.mesh.name() == "robot", "a selected group sends its meshes and names the row"
    assert record["box"] == pytest.approx(cmds.exactWorldBoundingBox(group))
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    assert page.generate_button.text() == "Generate . 72 CU"
    assert "over robot" in page.destination.text()
    asset_id = page.mesh.asset_id()

    page.generate()
    qt_pump_until(lambda: ready(page), timeout=20)
    run = fake.state.paid_runs()[0]["arguments"]
    assert run["model_id"] == CARTWHEEL and run["parameters"]["characterModel"] == asset_id and run["parameters"]["outputFormat"] == "fbx-maya"
    card = next(iter(page.cards.values()))
    assert card.row["origin"]["character"]["name"] == "robot" and card.row["origin"]["target"] == "|robot"

    cmds.undoInfo(stateWithoutFlush=False)
    cmds.currentTime(20)
    cmds.undoInfo(stateWithoutFlush=True)
    page.land(card.row, "model")
    assert page.message.text().startswith("Imported waves_hello_right_hand: 4 faces, 2 joints, over robot"), page.message.text()
    assert cmds.currentTime(query=True) == 20, "the fit is measured on the clip's first frame, the current frame kept"
    top = [t for t in cmds.ls(assemblies=True) if cmds.attributeQuery("scenario_job_id", node=t, exists=True)][0]
    meshes = cmds.listRelatives(top, allDescendents=True, type="mesh", fullPath=True, noIntermediate=True)
    cmds.undoInfo(stateWithoutFlush=False)  # in mayapy a frame change is an undo step of its own
    cmds.currentTime(cmds.playbackOptions(query=True, minTime=True))
    cmds.undoInfo(stateWithoutFlush=True)
    placed, target = cmds.exactWorldBoundingBox(meshes), cmds.exactWorldBoundingBox(group)
    for i in range(3):
        assert (placed[i] + placed[i + 3]) / 2 == pytest.approx((target[i] + target[i + 3]) / 2, abs=1e-3), "centred on the character"
    assert math.dist(placed[:3], placed[3:]) == pytest.approx(math.dist(target[:3], target[3:]), abs=1e-3), "at its size"
    cmds.undo()
    assert not cmds.objExists(top) and cmds.objExists(group), "one undo removes the result, the character stays"
    assert len(fake.state.uploads) == 1 and len(fake.state.paid_runs()) == 1


def test_rerun_restores_the_character_without_sending_it_again(panel, fake, cmds):  # noqa: F811
    page = motion_page(panel, CARTWHEEL)
    robot(cmds)
    page.mesh.use_selection()
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    page.generate()
    qt_pump_until(lambda: ready(page), timeout=20)
    row = next(iter(page.cards.values())).row
    page.mesh.clear()
    qt_pump_until(lambda: page.generate_button.text() == "Select your character", timeout=5)
    page.reuse(row)
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    assert page.mesh.asset_id() == row["params"]["characterModel"] and page.mesh.name() == "robot"
    assert len(fake.state.uploads) == 1, "a re-run sends nothing"


def test_a_model_without_a_character_input_leaves_the_character_out(panel, fake, cmds):  # noqa: F811
    page = motion_page(panel, UTHANA)
    robot(cmds)
    page.mesh.use_selection()
    qt_pump_until(lambda: page.mesh.asset_id(), timeout=15)
    page.set_model(MESHY)
    qt_pump_until(lambda: page.form is not None and page.form.model_id == MESHY, timeout=10)
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    assert "characterFile" not in page.values() and "character" not in page.origin()
    assert "robot is kept for a model that takes a character" in page.mesh.note.text()
