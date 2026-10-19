"""The 3D lane end to end in mayapy against the fake Scenario server (0 CU):
price, generate, follow, download the GLB only, import on the ground, one undo."""

import os
import threading
from datetime import date

import pytest

from tests.fake_backend import API_KEY, API_SECRET
from tests.maya.conftest import MODULE, PLUGIN, fresh, pump_until, qt_pump_until

MESHY = "model_meshy-7-1-txt23d"


@pytest.fixture
def lane(fake, monkeypatch, cmds, tmp_path):
    monkeypatch.setenv("SCENARIO_MCP_URL", fake.endpoint)
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    os.makedirs(tmp_path / "project", exist_ok=True)
    cmds.workspace(str(tmp_path / "project"), openWorkspace=True)
    cmds.loadPlugin(os.path.join(MODULE, "plug-ins", "scenario_for_maya.py"))
    runtime = fresh("scenario_maya.maya.runtime").get()
    done = runtime.background(lambda: runtime.session.sign_in_api_key(API_KEY, API_SECRET))
    pump_until(done.done)
    done.result()
    yield runtime
    if cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        cmds.flushUndo()  # an import in the undo queue keeps the plug-in in use
        cmds.file(new=True, force=True)
        cmds.unloadPlugin(PLUGIN)


def generate(runtime, prompt="a mossy stone well, stylized"):
    params = {"prompt": prompt, "shouldRemesh": True, "targetPolycount": 30000}
    origin = {"lane": "3d"}
    priced = runtime.background(lambda: runtime.session.price(MESHY, params, origin=origin))
    pump_until(priced.done)
    quote = priced.result()
    sent = []
    runtime.jobs.generate(quote.quote_id, approved_cost=quote.cu_cost_exact, params=params, origin=origin, model_name="Meshy 7.1", on_sent=sent.append, on_error=sent.append)
    pump_until(lambda: sent)
    assert isinstance(sent[0], dict), sent[0]
    return sent[0]["local_id"]


def test_generate_download_and_import_on_the_ground(lane, fake, cmds, tmp_path):
    runtime = lane
    events = []
    runtime.subscribe(lambda event, data: events.append((data.get("row", {}).get("state"), threading.current_thread() is threading.main_thread())) if event == "job" else None)
    local_id = generate(runtime)
    pump_until(lambda: events and events[-1][0] == "ready", timeout=20)
    row = runtime.ledger.get(local_id)
    files = row["result"]["files"]
    originals = tmp_path / "project" / "scenario" / date.today().isoformat()
    assert len(files) == 1 and files[0]["path"].endswith(".glb") and files[0]["path"].startswith(str(originals))
    assert os.path.exists(row["result"]["thumbnail"])
    assert all(main for _state, main in events)
    # The camera looks at a point off the origin; the model lands below it, on the ground.
    cmds.setAttr("persp.translate", 10, 8, 20, type="double3")
    cmds.camera("perspShape", edit=True, worldCenterOfInterest=(3, 4, -2))
    made = runtime.jobs.land(local_id, "model", camera=("persp", "perspShape"))
    top = made["top"]
    assert cmds.getAttr(top + ".scenario_job_id") == row["remote_job_id"]
    assert cmds.getAttr(top + ".scenario_apply").startswith("import ")
    box = cmds.exactWorldBoundingBox(made["meshes"])
    assert box[1] == pytest.approx(0.0, abs=1e-4), "bottom on the ground"
    assert (box[0] + box[3]) / 2 == pytest.approx(3.0, abs=1e-4) and (box[2] + box[5]) / 2 == pytest.approx(-2.0, abs=1e-4)
    assert made["checks"]["faces"] == 2 and made["checks"]["textures"] == 3
    textures = os.path.dirname(made["textures"][0])
    assert textures.startswith(str(tmp_path / "project" / "sourceimages" / "scenario"))
    assert runtime.ledger.get(local_id)["state"] == "applied"
    assert made["undo"] == cmds.undoInfo(query=True, undoName=True)
    cmds.undo()
    assert not cmds.objExists(top), "one undo removes the import and its placement"
    cmds.redo()
    assert cmds.objExists(top)
    assert cmds.exactWorldBoundingBox(made["meshes"])[1] == pytest.approx(0.0, abs=1e-4), "redo restores the placement"
    assert len(fake.state.paid_runs()) == 1, "importing never spends"


def test_panel_shows_the_3d_lane_with_its_preset_and_import(lane, fake, cmds):
    runtime = lane
    runtime.session.set_workspace("team_fake0000000000000001", "proj_fake0000000000000001", "Test team", "Test project")
    runtime.session.settings.update(lane_image_prompt="a brass lantern")  # someone who already generated an image
    panel = fresh("scenario_maya.ui.panel").ScenarioPanel(runtime)
    try:
        assert [button.text() for button in panel.lane_buttons.buttons()] == ["Image", "3D"]
        panel.select_lane("3d")
        page = panel.lane
        assert page.lane.id == "3d" and runtime.session.settings.get("lane") == "3d"
        assert page.prompt.toPlainText() == "a carved wooden treasure chest, game prop", "a lane never used yet starts with its example"
        qt_pump_until(lambda: page.fields is not None, timeout=10)
        values = page.values()
        assert values["shouldRemesh"] is True and values["targetPolycount"] == 30000, "the lane proposes a game polycount"
        qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=10)
        assert page.generate_button.text() == "Generate . 120 CU"
        page.generate()
        qt_pump_until(lambda: any(card.row.get("state") == "ready" for card in page.cards.values()), timeout=20)
        card = next(iter(page.cards.values()))
        buttons = [card.actions.itemAt(i).widget().text() for i in range(card.actions.count()) if card.actions.itemAt(i).widget()]
        assert buttons[0] == "Import" and "Card" not in buttons
        assert card.note.text().startswith("GLB  .  2 faces")
        assert not panel.lane_pages["image"].cards, "a 3D job never shows in the Image lane"
        card.update_row(dict(card.row, result=dict(card.row["result"], thumbnail="")))
        assert card.thumb.text() == "3D", "a model whose preview is not rendered yet shows a placeholder"
        page.land(card.row, "model")
        assert page.message.text().startswith("Imported carved_wooden_treasure_chest: 2 faces, on the ground"), page.message.text()
        assert len(fake.state.paid_runs()) == 1
    finally:
        panel.deleteLater()
