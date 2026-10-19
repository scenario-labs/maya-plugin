"""The 3D tab's Image mode in mayapy against the fake Scenario server (0 CU):
add an image (sent once), price, generate, import; a viewport capture; an
Image result sent to 3D without a new upload; a model that takes one image."""

import os

import pytest

from tests.fake_backend import API_KEY, API_SECRET
from tests.fake_backend.fake_scenario import _png
from tests.maya.conftest import MODULE, PLUGIN, fresh, pump_until, qt_pump_until

TRIPO_P2 = "model_tripo-p2-image-to-3d"


@pytest.fixture
def panel(fake, monkeypatch, cmds, tmp_path):
    monkeypatch.setenv("SCENARIO_MCP_URL", fake.endpoint)
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    os.makedirs(tmp_path / "project", exist_ok=True)
    cmds.workspace(str(tmp_path / "project"), openWorkspace=True)
    cmds.loadPlugin(os.path.join(MODULE, "plug-ins", "scenario_for_maya.py"))
    fresh("scenario_maya.core.uploads").forget()
    runtime = fresh("scenario_maya.maya.runtime").get()
    signed = runtime.background(lambda: runtime.session.sign_in_api_key(API_KEY, API_SECRET))
    pump_until(signed.done)
    signed.result()
    runtime.session.set_workspace("team_fake0000000000000001", "proj_fake0000000000000001", "Test team", "Test project")
    widget = fresh("scenario_maya.ui.panel").ScenarioPanel(runtime)
    widget.resize(420, 900)
    widget.show()
    yield widget
    widget.close()
    widget.deleteLater()
    if cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        cmds.flushUndo()
        cmds.file(new=True, force=True)
        cmds.unloadPlugin(PLUGIN)


def concept(tmp_path, name="lantern_concept.png", rgb=(180, 140, 60)):
    path = tmp_path / name
    path.write_bytes(_png(32, 32, rgb))
    return str(path)


def image_page(panel):
    panel.select_lane("3d_image")
    page = panel.lane
    qt_pump_until(lambda: page.fields is not None, timeout=10)
    return page


def test_3d_tab_has_its_modes_and_remembers_the_last(panel):
    assert [button.text() for button in panel.lane_buttons.buttons()] == ["Image", "3D"]
    panel.select_tab("3d")
    assert panel.lane.lane.id == "3d", "a tab opens on its first mode"
    assert panel.mode_bars["3d"].isVisible() and [panel.mode_button[i].text() for i in ("3d", "3d_image", "3d_edit")] == ["Text", "Image", "Edit selection"]
    panel.select_lane("3d_image")
    panel.select_tab("image")
    assert not panel.mode_bars["3d"].isVisible()
    panel.select_tab("3d")
    assert panel.lane.lane.id == "3d_image", "the 3D tab reopens on the mode used last"


def test_add_an_image_then_generate_and_import(panel, fake, cmds, tmp_path):
    page = image_page(panel)
    assert page.inputs.isVisible() and page.inputs.title.text() == "Image"
    assert page.prompt_label.text() == "Texture prompt (optional)", "Meshy's prompt only guides the texture"
    assert page.generate_button.text() == "Add an image" and not page.generate_button.isEnabled()
    assert page.values()["shouldRemesh"] is True and page.values()["targetPolycount"] == 30000
    path = concept(tmp_path)
    page.inputs.add_file(path)
    assert page.generate_button.text() == "Sending the image..."
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    assert page.generate_button.text() == "Generate . 120 CU"
    upload = next(iter(fake.state.uploads.values()))
    with open(path, "rb") as handle:
        assert upload["data"] == handle.read() and upload["name"] == "lantern_concept.png"
    asset_id = page.inputs.asset_ids()[0]
    page.generate()
    qt_pump_until(lambda: any(card.row.get("state") == "ready" for card in page.cards.values()), timeout=20)
    run = fake.state.paid_runs()[0]["arguments"]
    assert run["model_id"] == "model_meshy-7-1-img23d" and run["parameters"]["image"] == [asset_id]
    card = next(iter(page.cards.values()))
    assert card.title.text() == "lantern_concept", "a job without a prompt is named after its image"
    assert panel.lane_pages["3d"].cards, "the Text mode shows the tab's results too"
    page.land(card.row, "model")
    assert page.message.text().startswith("Imported lantern_concept: 2 faces"), page.message.text()
    top = next(iter(cmds.ls("*.scenario_input_asset_ids", recursive=True, objectsOnly=True)))
    assert asset_id in cmds.getAttr(top + ".scenario_input_asset_ids"), "provenance names the image it came from"
    assert len(fake.state.uploads) == 1 and len(fake.state.paid_runs()) == 1


def test_the_viewport_capture_is_sent_without_an_undo_step(panel, fake, cmds):
    page = image_page(panel)
    cube = cmds.polyCube(name="blockout")[0]
    before = cmds.undoInfo(query=True, undoName=True)
    page.inputs.capture_viewport()
    assert cmds.undoInfo(query=True, undoName=True) == before, "the capture is not an undo step"
    item = page.inputs.items[0]
    assert item["source"] == "viewport" and item["path"].endswith(".jpg")
    assert os.sep.join(("images", "scenario", "captures")) in item["path"] and os.path.getsize(item["path"]) > 1000
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    upload = next(iter(fake.state.uploads.values()))
    assert upload["content_type"] == "image/jpeg"
    cmds.undo()
    assert not cmds.objExists(cube), "the user's last step is still the first undo"


def test_an_image_result_goes_to_3d_without_a_new_upload(panel, fake, cmds):
    panel.select_lane("image")
    image = panel.lane
    qt_pump_until(lambda: image.generate_button.isEnabled(), timeout=10)
    image.generate()
    qt_pump_until(lambda: any(card.row.get("state") == "ready" for card in image.cards.values()), timeout=20)
    card = next(iter(image.cards.values()))
    actions = [action.text() for action in card.actions.itemAt(card.actions.count() - 1).widget().menu().actions()]
    assert "Make a 3D model from this image" in actions
    image.image_to_3d.emit(card.row)
    page = panel.lane
    assert page.lane.id == "3d_image"
    qt_pump_until(lambda: page.form is not None, timeout=10)
    asset_id = card.row["result"]["files"][0]["asset_id"]
    assert page.inputs.asset_ids() == [asset_id]
    qt_pump_until(lambda: page.form is not None and page.generate_button.isEnabled(), timeout=10)
    assert page.generate_button.text() == "Generate . 120 CU"
    assert not fake.state.uploads, "an Image result is already on Scenario"
    assert [row["local_id"] for row in page.inputs.image_results()] == [card.row["local_id"]]


def test_a_model_that_takes_one_image_uses_the_first(panel, fake, tmp_path):
    page = image_page(panel)
    page.inputs.add_file(concept(tmp_path, "front.png"))
    qt_pump_until(lambda: not page.inputs.busy(), timeout=15)
    page.inputs.add_file(concept(tmp_path, "side.png", (60, 140, 180)))
    qt_pump_until(lambda: not page.inputs.busy() and len(page.inputs.asset_ids()) == 2, timeout=15)
    first = page.inputs.asset_ids()[0]
    page.set_model(TRIPO_P2)
    qt_pump_until(lambda: page.form is not None and page.form.model_id == TRIPO_P2, timeout=10)
    assert page.values()["image"] == first, "Tripo P2 takes one image, sent as a single id"
    assert "only the first is used" in page.inputs.note.text()
    assert not page.prompt.isVisible(), "Tripo P2 takes no prompt"
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=10)
    assert page.generate_button.text() == "Generate . 220 CU"


def test_rerun_restores_the_images(panel, fake, tmp_path):
    page = image_page(panel)
    page.inputs.add_file(concept(tmp_path))
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    page.generate()
    qt_pump_until(lambda: any(card.row.get("state") == "ready" for card in page.cards.values()), timeout=20)
    row = next(iter(page.cards.values())).row
    page.inputs.remove(0)
    assert not page.inputs.asset_ids()
    panel.lane_pages["3d"].reuse(row)
    assert panel.lane is page, "a re-run from the Text mode switches to the job's mode"
    assert page.inputs.asset_ids() == list(row["params"]["image"])
    assert len(fake.state.uploads) == 1, "a re-run sends nothing"
