"""The panel's Image lane, built offscreen in mayapy and clicked like a person would (0 CU)."""

import os

import pytest

from tests.fake_backend import API_KEY, API_SECRET
from tests.maya.conftest import MODULE, PLUGIN, fresh, pump_until, qt_pump_until


@pytest.fixture
def page(fake, monkeypatch, cmds, tmp_path):
    monkeypatch.setenv("SCENARIO_MCP_URL", fake.endpoint)
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    os.makedirs(tmp_path / "project", exist_ok=True)
    cmds.workspace(str(tmp_path / "project"), openWorkspace=True)
    cmds.loadPlugin(os.path.join(MODULE, "plug-ins", "scenario_for_maya.py"))
    runtime = fresh("scenario_maya.maya.runtime").get()
    signed = runtime.background(lambda: runtime.session.sign_in_api_key(API_KEY, API_SECRET))
    pump_until(signed.done)
    signed.result()
    lane = fresh("scenario_maya.ui.lane").LanePage(runtime)
    lane.resize(400, 700)
    lane.show()
    runtime.subscribe(lambda event, data: lane.on_job(data) if event == "job" else None)
    yield lane
    lane.close()
    lane.deleteLater()
    if cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        cmds.unloadPlugin(PLUGIN)


def test_first_run_prices_the_starter_prompt(page, fake):
    assert page.prompt.toPlainText() == "a carved wooden treasure chest, game prop, studio light"
    qt_pump_until(lambda: page.generate_button.isEnabled())
    assert page.generate_button.text() == "Generate . 11 CU"
    assert not fake.state.paid_runs(), "pricing is free"
    assert page.fields is not None and "numOutputs" in page.fields.widgets


def test_empty_prompt_says_what_is_missing(page):
    qt_pump_until(lambda: page.form is not None)
    page.prompt.setPlainText("")
    qt_pump_until(lambda: not page.generate_button.isEnabled())
    assert page.generate_button.text() == "Needs a prompt"


def test_an_edit_reprices_before_generate_is_enabled(page, fake):
    qt_pump_until(lambda: page.generate_button.isEnabled())
    page.prompt.setPlainText("a stone well")
    assert not page.generate_button.isEnabled() and page.generate_button.text() == "Checking price..."
    qt_pump_until(lambda: page.generate_button.isEnabled())
    assert page.quote[1] == {"prompt": "a stone well"}


def test_generate_then_land_a_card_from_the_result(page, fake, cmds):
    qt_pump_until(lambda: page.generate_button.isEnabled())
    page.generate_button.click()
    assert page.generate_button.text() == "Waiting for Scenario..."
    qt_pump_until(lambda: page.cards and next(iter(page.cards.values())).row.get("state") == "ready", timeout=20)
    assert len(fake.state.paid_runs()) == 1
    card = next(iter(page.cards.values()))
    buttons = {card.actions.itemAt(i).widget().text() for i in range(card.actions.count()) if card.actions.itemAt(i).widget()}
    assert {"Card", "Material", "Image plane"} <= buttons
    qt_pump_until(lambda: card.thumb.pixmap() is not None and not card.thumb.pixmap().isNull())
    card_button = next(card.actions.itemAt(i).widget() for i in range(card.actions.count()) if card.actions.itemAt(i).widget() and card.actions.itemAt(i).widget().text() == "Card")
    card_button.click()
    landed = cmds.ls("*.scenario_asset_id", recursive=True, objectsOnly=True)
    assert landed and "One Ctrl+Z removes it" in page.message.text()
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=10)
    assert len(fake.state.paid_runs()) == 1, "one click, one request"


def test_material_without_selection_shows_why(page, cmds):
    qt_pump_until(lambda: page.generate_button.isEnabled())
    page.generate_button.click()
    qt_pump_until(lambda: page.cards and next(iter(page.cards.values())).row.get("state") == "ready", timeout=20)
    cmds.select(clear=True)
    page.land(next(iter(page.cards.values())).row, "material")
    assert "select a mesh" in page.message.text()


def test_picker_lists_image_models(page):
    picker = fresh("scenario_maya.ui.picker").ModelPicker(page.runtime, page.lane, current=page.model_id)
    qt_pump_until(lambda: picker.list.count() > 0)
    assert picker.list.item(0).text().startswith("GPT Image 2.5 Flare")
    assert picker.use.isEnabled()
    picker.close()


def test_workspace_question_never_blocks_the_dispatcher(page):
    from PySide6 import QtWidgets

    runtime = page.runtime
    runtime.dispatcher.reset_timing()
    picked = []
    fresh("scenario_maya.ui.workspace").choose(runtime, page, ask=True, on_done=lambda: picked.append(runtime.session.workspace()))
    qt_pump_until(lambda: QtWidgets.QApplication.activeModalWidget() is not None)
    dialog = QtWidgets.QApplication.activeModalWidget()
    assert type(dialog).__name__ == "WorkspaceDialog"
    assert runtime.dispatcher.longest_slice_ms < 1000, "the question is open while the dispatcher keeps running"
    dialog.accept()
    qt_pump_until(lambda: picked)
    assert "/" in picked[0]
