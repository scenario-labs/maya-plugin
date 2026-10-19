"""The 3D tab's Multi-view mode in mayapy against the fake Scenario server (0 CU):
views captured around the selection (no undo step, nothing left in the scene),
sent once, priced, generated with one image per named view, imported over the
object (any up axis or unit); a front view alone; Re-run; a model with eight views."""

import pytest

from tests.maya.conftest import fresh, qt_pump_until
from tests.maya.test_three_d_image_lane import concept, panel  # noqa: F401  (the same panel fixture)

TRIPO_P2_VIEWS = "model_tripo-p2-multiview-to-3d"
HUNYUAN_VIEWS = "model_hunyuan-3d-pro-3-1-multiview"


def views_page(panel):  # noqa: F811
    panel.select_lane("3d_views")
    page = panel.lane
    qt_pump_until(lambda: page.fields is not None and page.views.fields, timeout=10)
    return page


def ready(page):
    return any(card.row.get("state") == "ready" for card in page.cards.values())


def coloured_box(cmds, name="crate"):
    """A box with a red front (+Z) and a blue left side (+X), raised off a floor, beside another object."""
    node = cmds.polyCube(name=name, width=40, height=30, depth=30)[0]
    for face, rgb in ((0, (0.8, 0.05, 0.05)), (4, (0.05, 0.1, 0.8))):
        shader = cmds.shadingNode("lambert", asShader=True)
        cmds.setAttr(shader + ".color", *rgb, type="double3")
        group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True)
        cmds.connectAttr(shader + ".outColor", group + ".surfaceShader")
        cmds.sets(f"{node}.f[{face}]", edit=True, forceElement=group)
    cmds.move(30, 15, -20, node)
    cmds.polyPlane(name="floor", width=600, height=600)
    neighbour = cmds.polySphere(name="neighbour", radius=25)[0]
    cmds.move(130, 25, -20, neighbour)
    cmds.select(node)
    return node


def centre_colour(path):
    from PySide6 import QtGui

    image = QtGui.QImage(path)
    colour = image.pixelColor(image.width() // 2, image.height() // 2)
    return (colour.red(), colour.green(), colour.blue())


def test_capture_views_renders_each_side_and_leaves_nothing(panel, cmds, tmp_path):  # noqa: F811
    coloured_box(cmds)
    before = cmds.undoInfo(query=True, undoName=True)
    settings = (cmds.getAttr("defaultRenderGlobals.imageFormat"), cmds.getAttr("hardwareRenderingGlobals.ssaoEnable"))
    cameras = sorted(cmds.ls(type="camera"))
    made = fresh("scenario_maya.maya.capture").capture_views(["crate"], ["front", "left", "back", "right", "top"], folder=str(tmp_path / "views"))
    assert sorted(made["views"]) == ["back", "front", "left", "right", "top"] and made["name"] == "crate" and made["up_axis"] == "y"
    assert made["box"] == pytest.approx(cmds.exactWorldBoundingBox("crate"))
    red, blue = centre_colour(made["views"]["front"]), centre_colour(made["views"]["left"])
    assert red[0] > 150 and red[2] < 80, f"the front view sees the red +Z face: {red}"
    assert blue[2] > 150 and blue[0] < 80, f"the left view sees the blue +X face (the object's own left): {blue}"
    grey = centre_colour(made["views"]["back"])
    assert abs(grey[0] - grey[2]) < 20, "the back is neither"
    assert cmds.undoInfo(query=True, undoName=True) == before, "capturing is not an undo step"
    assert sorted(cmds.ls(type="camera")) == cameras, "the cameras are gone"
    assert (cmds.getAttr("defaultRenderGlobals.imageFormat"), cmds.getAttr("hardwareRenderingGlobals.ssaoEnable")) == settings
    from PySide6 import QtGui

    assert QtGui.QImage(made["views"]["top"]).size().toTuple() == (1024, 1024)


def facing(cmds, node, axis, sign):
    """The face of a box whose normal points along ``sign`` times the ``axis`` (0, 1, 2)."""
    for index in range(6):
        normal = [float(value) for value in cmds.polyInfo(f"{node}.f[{index}]", faceNormals=True)[0].split()[-3:]]
        if normal[axis] * sign > 0.9:
            return f"{node}.f[{index}]"
    raise AssertionError("no such face")


def test_capture_views_in_a_z_up_scene(panel, cmds, tmp_path):  # noqa: F811
    cmds.upAxis(axis="z")
    try:
        node = cmds.polyCube(name="crate", width=40, height=30, depth=30)[0]
        cmds.move(0, 0, 15, node)
        shader = cmds.shadingNode("lambert", asShader=True)
        cmds.setAttr(shader + ".color", 0.8, 0.05, 0.05, type="double3")
        group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True)
        cmds.connectAttr(shader + ".outColor", group + ".surfaceShader")
        cmds.sets(facing(cmds, node, axis=1, sign=-1), edit=True, forceElement=group)  # -Y: Maya's front in a Z-up scene
        made = fresh("scenario_maya.maya.capture").capture_views([node], ["front", "back"], folder=str(tmp_path / "views"))
        assert made["up_axis"] == "z" and centre_colour(made["views"]["front"])[0] > 150
    finally:
        cmds.upAxis(axis="y")


def test_capture_views_then_generate_with_one_image_per_view(panel, fake, cmds):  # noqa: F811
    page = views_page(panel)
    assert page.form.model_id == TRIPO_P2_VIEWS and not page.prompt.isVisible()
    assert [button.text() for button in page.views.buttons.values()] == ["Front", "Left", "Back", "Right"]
    assert page.generate_button.text() == "Add a front view" and not page.generate_button.isEnabled()
    coloured_box(cmds)
    before = cmds.undoInfo(query=True, undoName=True)
    page.views.capture()
    assert cmds.undoInfo(query=True, undoName=True) == before
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=20)
    assert page.generate_button.text() == "Generate . 220 CU" and len(fake.state.uploads) == 4
    sent = {view: item["asset_id"] for view, item in page.views.slots.items()}
    page.generate()
    qt_pump_until(lambda: ready(page), timeout=20)
    run = fake.state.paid_runs()[0]["arguments"]
    assert run["model_id"] == TRIPO_P2_VIEWS
    assert {key: value for key, value in run["parameters"].items() if key.endswith("Image")} == {f"{view}Image": asset for view, asset in sent.items()}
    card = next(iter(page.cards.values()))
    assert card.title.text() == "Views of crate"
    assert card.row["origin"]["views_capture"]["box"] == pytest.approx(cmds.exactWorldBoundingBox("crate"))
    page.land(card.row, "model")
    assert page.message.text().startswith("Imported views_crate:") and "over crate" in page.message.text(), page.message.text()
    box = cmds.exactWorldBoundingBox("crate")
    landed = cmds.exactWorldBoundingBox(cmds.ls("scn_views_crate*:*", type="mesh"))
    assert [(landed[i] + landed[i + 3]) / 2 for i in range(3)] == pytest.approx([(box[i] + box[i + 3]) / 2 for i in range(3)], abs=1e-3), "the result sits on the object"

    page.views.slots.clear()
    page.views.set_fields(page.views.fields)
    page.reuse(card.row)
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    assert {view: item["asset_id"] for view, item in page.views.slots.items()} == sent and len(fake.state.uploads) == 4, "a re-run sends nothing"


def test_a_front_view_alone_is_not_enough(panel, fake, tmp_path):  # noqa: F811
    page = views_page(panel)
    page.views.add_file("front", concept(tmp_path, "robot_front.png"))
    qt_pump_until(lambda: page.generate_button.text() == "Add one more view", timeout=15)
    page.views.add_file("back", concept(tmp_path, "robot_back.png", (40, 40, 40)))
    qt_pump_until(lambda: page.generate_button.isEnabled(), timeout=15)
    page.views.clear("front")
    assert page.generate_button.text() == "Add a front view"


def test_a_model_with_eight_views_shows_eight_slots(panel, cmds):  # noqa: F811
    page = views_page(panel)
    page.set_model(HUNYUAN_VIEWS)
    qt_pump_until(lambda: page.form is not None and page.form.model_id == HUNYUAN_VIEWS, timeout=10)
    labels = [button.text() for button in page.views.buttons.values()]
    assert labels == ["Front", "Left", "Back", "Right", "Top", "Bottom", "Left front", "Right front"]
    assert page.values()["faceCount"] == 40000, "Hunyuan starts at its lightest mesh"


def box_glb(path, size, centre):
    """A closed box GLB in the file's space (metres, Y-up): eight corners, twelve triangles."""
    from tests import glb_samples

    w = glb_samples.Writer()
    half = [value / 2 for value in size]
    corners = [tuple(centre[k] + (half[k] if (index >> k) & 1 else -half[k]) for k in range(3)) for index in range(8)]
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    indices = [index for a, b, c, d in faces for index in (a, b, c, a, c, d)]
    w.add("meshes", {"name": "box", "primitives": [{"attributes": {"POSITION": w.accessor("VEC3", corners, bounds=True)}, "indices": w.accessor("SCALAR", indices, component=5123)}]})
    w.add("nodes", {"name": "Box", "mesh": 0})
    w.add("scenes", {"nodes": [0]})
    return w.save(str(path))


@pytest.mark.parametrize("up, unit", [("y", "cm"), ("z", "cm"), ("y", "m")])
def test_a_multi_view_result_lands_over_the_captured_object(plugin, cmds, tmp_path, up, unit):
    """Like the live results: 1 m tall, centred, the front towards +Z. It lands on the object, at its size, facing its way."""
    cmds.upAxis(axis=up)
    cmds.currentUnit(linear=unit)
    try:
        k = 0.01 if unit == "m" else 1.0
        node = cmds.polyCube(name="crate", width=40 * k, height=20 * k, depth=30 * k)[0]  # Y-up: 40 wide, 20 tall, 30 deep
        if up == "z":
            cmds.setAttr(node + ".rotateX", 90)  # Z-up: 40 wide, 30 deep (along -Y, the front), 20 tall
        cmds.move(30 * k, -12 * k, 7 * k, node)
        capture = {"box": cmds.exactWorldBoundingBox(node), "up_axis": up, "name": node}
        path = box_glb(tmp_path / "views.glb", (0.4 * 2.5, 0.2 * 2.5, 0.3 * 2.5), (0.1, 0.5, -0.05))
        apply, landing = fresh("scenario_maya.maya.apply"), fresh("scenario_maya.maya.landing")
        over = apply.import_over_views(capture, path)
        made = landing.land_model(path, {}, texture_folder=str(tmp_path / "tex"), label="views", matrix=over["matrix"], over=over["target_name"])
        assert cmds.exactWorldBoundingBox(made["meshes"]) == pytest.approx(capture["box"], abs=1e-3 * k)
        assert made["summary"].endswith(", over crate")
    finally:
        cmds.currentUnit(linear="cm")
        cmds.upAxis(axis="y")
