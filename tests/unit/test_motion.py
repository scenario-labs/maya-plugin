"""The Motion mode's core (spec 6.5), against the fake Scenario server (0 CU): which
models it lists, which take a character, the frame rate taken from the scene, and a
character sent and priced the way the live models answered on 2026-10-19."""

import pytest

from scenario_maya.core import catalog, delivery, lanes, motion, uploads
from scenario_maya.core.schema import ModelForm
from tests.unit.test_uploads import schema, signed_in  # noqa: F401  (the same signed-in session)

MESHY = "model_meshy-text-to-motion"
CARTWHEEL = "model_cartwheel-text-to-motion"
UTHANA = "model_uthana-text-to-motion-3.0"


def test_the_motion_mode_lists_motion_models_only():
    assert lanes.THREE_D_MOTION.tab == "3d" and lanes.THREE_D_MOTION.inputs == "character"
    assert lanes.THREE_D_MOTION.quick_picks[0] == MESHY, "works from a prompt alone"
    assert lanes.lane_for_model(["txt23d"], ["3D", "Motion"]) is lanes.THREE_D_MOTION
    assert lanes.lane_for_model(["txt23d"], ["3d"]) is lanes.THREE_D
    assert lanes.lane_for_model(["txt23d", "3d23d"], ["Motion"]) is lanes.THREE_D_MOTION, "Cartwheel is not an edit"
    assert lanes.lane_for_model(["3d23d"]) is lanes.THREE_D_EDIT


def test_the_catalog_keeps_motion_models_out_of_text_and_edit(tmp_path):
    cache = catalog.Catalog(str(tmp_path / "catalog.json"))
    rows = [
        {"id": "model_mesh", "name": "Mesh", "capabilities": ["txt23d"], "tags": ["3D"], "createdAt": "2026-10-10"},
        {"id": MESHY, "name": "Meshy Text to Motion", "capabilities": ["txt23d"], "tags": ["3D", "Motion"], "createdAt": "2026-08-25"},
        {"id": CARTWHEEL, "name": "Cartwheel Text to Motion", "capabilities": ["txt23d", "3d23d"], "tags": ["Motion"], "createdAt": "2026-06-25"},
        {"id": "model_remesh", "name": "Remesh", "capabilities": ["3d23d"], "tags": [], "createdAt": "2026-09-01"},
    ]
    cache._data = {"workspaces": {"w": {"fetched": 0, "models": rows}}}
    assert [row["id"] for row in cache.for_lane("w", lanes.THREE_D_MOTION)] == [MESHY, CARTWHEEL]
    assert [row["id"] for row in cache.for_lane("w", lanes.THREE_D)] == ["model_mesh"]
    assert [row["id"] for row in cache.for_lane("w", lanes.THREE_D_EDIT)] == ["model_remesh"]


def test_each_motion_model_needs_takes_or_ignores_a_character():
    forms = {model: ModelForm.from_schema(schema(model)) for model in (MESHY, CARTWHEEL, UTHANA)}
    assert [field.name for field in forms[CARTWHEEL].mesh_fields] == ["characterModel"], "its image field is not the character row's"
    assert [field.name for field in forms[UTHANA].mesh_fields] == ["characterFile"] and not forms[MESHY].mesh_fields
    rules = {model: motion.character_rule(model, bool(form.mesh_fields)) for model, form in forms.items()}
    assert rules == {MESHY: motion.NONE, CARTWHEEL: motion.REQUIRED, UTHANA: motion.OPTIONAL}
    assert motion.character_rule("model_new-motion", True) == motion.OPTIONAL and motion.character_rule("model_new-motion", False) == motion.NONE
    assert lanes.THREE_D_MOTION.presets[CARTWHEEL] == {"outputFormat": "fbx-maya"}, "never .ma or .mb (spec 6.5)"


@pytest.mark.parametrize(
    "model, fps, expected",
    [(UTHANA, 24.0, {"fps": 24}), (UTHANA, 25.0, {}), (CARTWHEEL, 25.0, {"frameRate": 25}), (CARTWHEEL, 23.976, {"frameRate": 23.976}), (MESHY, 24.0, {})],
)
def test_the_frame_rate_starts_at_the_scenes_when_the_model_offers_it(model, fps, expected):
    form = ModelForm.from_schema(schema(model))
    assert motion.scene_rate_values(form, fps, {}) == expected
    assert motion.scene_rate_values(form, fps, {"fps": 60, "frameRate": 60}) == {}, "a value the user set stays"


def test_a_character_is_sent_as_3d_and_cartwheel_refuses_without_one(signed_in, fake, tmp_path):  # noqa: F811
    from scenario_maya.core import errors
    from tests.glb_samples import textured_quad

    session = signed_in
    with pytest.raises(errors.ScenarioError, match="Provide a reference image or a 3D model"):
        session.price(CARTWHEEL, {"prompt": "waves hello"}, origin={"lane": lanes.THREE_D_MOTION.id})
    sent = uploads.upload_file(session, textured_quad(str(tmp_path / "scn_input_robot.glb")), kind="3d")
    quote = session.price(CARTWHEEL, {"prompt": "waves hello", "characterModel": sent["asset_id"], "outputFormat": "fbx-maya"}, origin={"lane": lanes.THREE_D_MOTION.id})
    assert quote.cu_cost_exact == "72"
    alone = session.price(MESHY, {"prompt": "waves hello", "duration": 3}, origin={"lane": lanes.THREE_D_MOTION.id})
    row = session.submit(
        alone.quote_id, approved_cost="40", params={"prompt": "waves hello", "duration": 3}, origin={"lane": lanes.THREE_D_MOTION.id}, model_name="Meshy Text to Motion", label="waves hello"
    )
    row = delivery.follow(session, row["local_id"], sleep=lambda s: None)
    done = delivery.download_results(session, row["local_id"], str(tmp_path / "out"), formats=lanes.THREE_D_MOTION.formats)
    files = done["result"]["files"]
    assert [item["path"].rsplit(".", 1)[1] for item in files] == ["glb"], "the character file only, not its OBJ, MTL or texture"
