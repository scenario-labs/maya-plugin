"""The 3D tab's Edit selection mode in mayapy against the fake Scenario server (0 CU):
a selected mesh written and sent once, priced, edited, and imported fitted over
the mesh it came from; the checks that refuse a mesh before it is sent; Re-run.

The fake server answers like the edit models did live on 2026-10-19: the sent
mesh back rescaled and centred, with new UVs, a texture or fewer triangles.
"""

import pytest

from tests.maya.conftest import qt_pump_until
from tests.maya.test_three_d_image_lane import panel  # noqa: F401  (the same panel fixture)

SMART_UV = "model_tripo-smart-uv"
TENCENT_UV = "model_tencent-uv-unwrapping"


def edit_page(panel, task="uv"):  # noqa: F811
    panel.select_lane("3d_edit")
    page = panel.lane
    qt_pump_until(lambda: page.fields is not None, timeout=10)
    if page.mesh.task.id != task:
        page.mesh.task_button[task].click()
        qt_pump_until(lambda: page.fields is not None and page.mesh.task.id == task, timeout=10)
    return page


def crate(cmds, name="crate"):
    """A box moved, turned and scaled, so a result placed by its own coordinates would miss it."""
    node = cmds.polyCube(name=name, width=40, height=30, depth=30)[0]
    cmds.xform(node, translation=(120, 15, -60), rotation=(0, 35, 0), scale=(1.5, 1, 1))
    cmds.select(node)
    return node


def ready(page):
    return any(card.row.get("state") == "ready" for card in page.cards.values())


def test_the_3d_tab_has_an_edit_selection_mode(panel):  # noqa: F811
    panel.select_tab("3d")
    assert [panel.mode_button[i].text() for i in ("3d", "3d_image", "3d_edit")] == ["Text", "Image", "Edit selection"]
    page = edit_page(panel)
    assert page.mesh.isVisible() and [b.text() for b in page.mesh.task_buttons.buttons()] == ["Remesh", "UV unwrap", "Retexture"]
    assert page.form.model_id == SMART_UV, "UV unwrap starts on its first quick pick"
    assert page.generate_button.text() == "Select a mesh to edit" and not page.generate_button.isEnabled()


def test_uv_unwrap_a_selected_mesh_then_import_it_over_the_mesh(panel, fake, cmds):  # noqa: F811
    page = edit_page(panel)
    node = crate(cmds)
    before = cmds.undoInfo(query=True, undoName=True)
    page.mesh.use_selection()
    assert cmds.undoInfo(query=True, undoName=True) == before, "writing the mesh is not an undo step"
    record = page.mesh.item["record"]
    assert record["triangles"] == 12 and record["names"]["scn_input_0"] == "|" + node
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    assert page.generate_button.text() == "Generate . 40 CU"
    upload = next(iter(fake.state.uploads.values()))
    with open(record["path"], "rb") as handle:
        assert upload["data"] == handle.read() and upload["kind"] == "3d" and upload["content_type"] == "model/gltf-binary"
    assert node.encode() not in upload["data"], "the scene's names stay in the scene"
    asset_id = page.mesh.asset_id()

    page.generate()
    qt_pump_until(lambda: ready(page), timeout=20)
    run = fake.state.paid_runs()[0]["arguments"]
    assert run["model_id"] == SMART_UV and run["parameters"]["model"] == asset_id
    card = next(iter(page.cards.values()))
    assert card.title.text() == "UV unwrap crate"
    assert card.row["origin"]["target"].endswith("crate")

    page.land(card.row, "model")
    assert page.message.text().startswith("Imported uv_unwrap_crate: 12 faces, over crate."), page.message.text()
    assert "not the same shape" not in page.message.text(), "the fit is verified: no note"
    top = [t for t in cmds.ls(assemblies=True) if cmds.attributeQuery("scenario_job_id", node=t, exists=True)][0]
    meshes = cmds.listRelatives(top, allDescendents=True, type="mesh", fullPath=True)
    placed = cmds.exactWorldBoundingBox(meshes, ignoreInvisible=False)
    source = cmds.exactWorldBoundingBox(node)
    assert placed == pytest.approx(source, abs=1e-3), "the result sits exactly over the mesh it came from"
    cmds.undo()
    assert not cmds.objExists(top) and cmds.objExists(node), "one undo removes the result, the mesh stays"
    assert len(fake.state.uploads) == 1 and len(fake.state.paid_runs()) == 1


def test_the_result_lands_over_the_mesh_where_it_is_now(panel, fake, cmds):  # noqa: F811
    page = edit_page(panel)
    node = crate(cmds)
    page.mesh.use_selection()
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    page.generate()
    qt_pump_until(lambda: ready(page), timeout=20)
    cmds.xform(node, translation=(-30, 5, 200), rotation=(10, -20, 0))
    page.land(next(iter(page.cards.values())).row, "model")
    top = [t for t in cmds.ls(assemblies=True) if cmds.attributeQuery("scenario_job_id", node=t, exists=True)][0]
    meshes = cmds.listRelatives(top, allDescendents=True, type="mesh", fullPath=True)
    assert cmds.exactWorldBoundingBox(meshes) == pytest.approx(cmds.exactWorldBoundingBox(node), abs=1e-3)


def test_a_result_that_is_not_the_same_shape_lands_with_a_note(panel, fake, cmds, monkeypatch):  # noqa: F811
    from tests.fake_backend import fake_scenario

    monkeypatch.setattr(fake_scenario, "_split_in_four", lambda points, triangles, uvs: (points, triangles[: len(triangles) // 2], uvs))
    page = edit_page(panel, "remesh")
    node = crate(cmds)
    page.mesh.use_selection()
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    page.generate()
    qt_pump_until(lambda: ready(page), timeout=20)
    page.land(next(iter(page.cards.values())).row, "model")  # a remesh that lost half the faces
    text = page.message.text()
    assert ", over crate." in text and "not the same shape as crate (" in text and "placed by the bounds only, check the placement" in text, text
    top = [t for t in cmds.ls(assemblies=True) if cmds.attributeQuery("scenario_job_id", node=t, exists=True)][0]
    meshes = cmds.listRelatives(top, allDescendents=True, type="mesh", fullPath=True)
    assert cmds.exactWorldBoundingBox(meshes) == pytest.approx(cmds.exactWorldBoundingBox(node), abs=1e-3), "still placed by the bounds"


def test_a_mesh_over_the_model_cap_is_refused_before_it_is_sent(panel, fake, cmds):  # noqa: F811
    page = edit_page(panel)
    page.set_model(TENCENT_UV)
    qt_pump_until(lambda: page.form is not None and page.form.model_id == TENCENT_UV, timeout=10)
    cmds.polySphere(name="dense", subdivisionsAxis=150, subdivisionsHeight=110)
    page.mesh.use_selection()
    qt_pump_until(lambda: page.generate_button.text() == "Mesh not accepted by this model", timeout=10)
    assert "takes up to 30,000 triangles; the selection has 32,700. Remesh it first." in page.mesh.note.text()
    assert not page.generate_button.isEnabled() and not fake.state.uploads, "nothing is sent"
    page.set_model(SMART_UV)
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    assert len(fake.state.uploads) == 1, "a model that takes it sends it"


def test_one_mesh_at_a_time(panel, fake, cmds):  # noqa: F811
    page = edit_page(panel)
    page.mesh.use_selection()
    assert page.mesh.note.text() == "Select a mesh in the scene first."
    cmds.polyCube(name="a")
    cmds.polyCube(name="b")
    cmds.select("a", "b")
    page.mesh.use_selection()
    assert page.mesh.note.text() == "2 meshes are selected. This version edits one mesh at a time: select one."
    assert page.mesh.item is None and not fake.state.uploads


def test_retexture_needs_a_prompt(panel, fake, cmds):  # noqa: F811
    page = edit_page(panel, "retexture")
    assert page.form.model_id == "model_meshy-7-retexture"
    assert page.prompt.isVisible() and page.prompt_label.text() == "Prompt"
    crate(cmds)
    page.mesh.use_selection()
    qt_pump_until(lambda: page.generate_button.text() == "Needs a prompt", timeout=15)
    page.prompt.setPlainText("weathered oak crate, iron bands")
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=10)
    page.generate()
    qt_pump_until(lambda: ready(page), timeout=20)
    run = fake.state.paid_runs()[0]["arguments"]
    assert run["parameters"]["textStylePrompt"] == "weathered oak crate, iron bands"
    card = next(iter(page.cards.values()))
    page.land(card.row, "model")
    assert ", over crate" in page.message.text(), page.message.text()


def test_the_task_remembers_its_own_model(panel, cmds):  # noqa: F811
    page = edit_page(panel)
    page.set_model(TENCENT_UV)
    qt_pump_until(lambda: page.form is not None and page.form.model_id == TENCENT_UV, timeout=10)
    page.mesh.task_button["remesh"].click()
    qt_pump_until(lambda: page.form is not None and page.form.model_id == "model_tripo-retopology-v3", timeout=10)
    page.mesh.task_button["uv"].click()
    qt_pump_until(lambda: page.form is not None and page.form.model_id == TENCENT_UV, timeout=10)


def test_rerun_restores_the_mesh_without_sending_it_again(panel, fake, cmds):  # noqa: F811
    page = edit_page(panel)
    crate(cmds)
    page.mesh.use_selection()
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    page.generate()
    qt_pump_until(lambda: ready(page), timeout=20)
    row = next(iter(page.cards.values())).row
    page.mesh.clear()
    # The button keeps "Waiting for Scenario..." for 2 s after Generate, however fast the job is.
    qt_pump_until(lambda: page.generate_button.text() == "Select a mesh to edit", timeout=5)
    page.reuse(row)
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    assert page.mesh.asset_id() == row["params"]["model"] and page.mesh.name() == "crate"
    assert len(fake.state.uploads) == 1, "a re-run sends nothing"


def card_button(card, text):
    from PySide6 import QtWidgets

    return next(w for w in card.findChildren(QtWidgets.QPushButton) if w.text() == text)


def test_apply_writes_the_uvs_after_a_review(panel, fake, cmds):  # noqa: F811
    page = edit_page(panel)
    node = crate(cmds)
    shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
    page.mesh.use_selection()
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    page.generate()
    qt_pump_until(lambda: ready(page), timeout=20)
    card = next(iter(page.cards.values()))
    assert "backup" in card_button(card, "Apply...").toolTip()
    card_button(card, "Apply...").click()
    qt_pump_until(lambda: page.review_dialog is not None and page.review_dialog.isVisible(), timeout=15)
    dialog = page.review_dialog
    assert dialog.windowTitle() == "Replace UVs on crate"
    assert not dialog.apply_button.isEnabled(), "the history deletion needs a tick first"
    assert dialog.checks[0].text().startswith("Delete the construction history of crate")
    dialog.confirm_all()
    assert dialog.apply_button.isEnabled()
    dialog.apply_button.click()
    qt_pump_until(lambda: page.message.text().startswith("Replace UVs on crate"), timeout=10)
    assert page.message.text() == "Replace UVs on crate. One Ctrl+Z undoes it."
    assert cmds.polyUVSet(shape, query=True, allUVSets=True) == ["map1", "map1_scnPrev"]
    assert card.row["state"] == "applied" or page.cards[card.row["local_id"]].row["state"] == "applied"
    cmds.undo()
    assert cmds.polyUVSet(shape, query=True, allUVSets=True) == ["map1"]


def test_apply_replaces_the_geometry_after_a_review(panel, fake, cmds):  # noqa: F811
    page = edit_page(panel, "remesh")
    node = crate(cmds)
    page.mesh.use_selection()
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    page.generate()
    qt_pump_until(lambda: ready(page), timeout=20)
    card = next(iter(page.cards.values()))
    assert "old shape stays" in card_button(card, "Apply...").toolTip()
    card_button(card, "Apply...").click()
    qt_pump_until(lambda: page.review_dialog is not None and page.review_dialog.isVisible(), timeout=15)
    dialog = page.review_dialog
    assert dialog.windowTitle() == "Replace geometry on crate" and dialog.apply_button.isEnabled() and not dialog.checks
    dialog.apply_button.click()
    qt_pump_until(lambda: page.message.text().startswith("Replace geometry on crate"), timeout=10)
    assert page.message.text() == "Replace geometry on crate: 48 triangles. One Ctrl+Z undoes it."
    shapes = cmds.listRelatives(node, shapes=True, fullPath=True)
    assert sorted(s.split("|")[-1] for s in shapes) == ["crateShape", "crateShape_scnPrev"] and cmds.polyEvaluate(node, face=True) == 48
    cmds.undo()
    assert [s.split("|")[-1] for s in cmds.listRelatives(node, shapes=True)] == ["crateShape"] and cmds.polyEvaluate(node, face=True) == 6
