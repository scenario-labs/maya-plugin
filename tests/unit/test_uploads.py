"""Sending an image as a model input, against the fake Scenario server (0 CU)."""

import json
import os

import pytest

from scenario_maya.core import errors, lanes, uploads
from scenario_maya.core.schema import ModelForm
from tests.fake_backend import API_KEY, API_SECRET
from tests.fake_backend.fake_scenario import _png

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "mcp")
MESHY_IMAGE = "model_meshy-7-1-img23d"


@pytest.fixture
def signed_in(session):
    uploads.forget()
    session.sign_in_api_key(API_KEY, API_SECRET)
    yield session
    uploads.forget()


def image(tmp_path, name="concept.png", size=64):
    path = tmp_path / name
    path.write_bytes(_png(size, size))
    return str(path)


def schema(model_id):
    with open(os.path.join(FIXTURES, f"schema_{model_id}.json")) as handle:
        return json.load(handle)


def test_an_image_is_sent_part_by_part_and_reused(signed_in, fake, tmp_path):
    fake.state.upload_part_size = 100  # several parts, like a large file on the real store
    path = image(tmp_path)
    sent = uploads.upload_file(signed_in, path)
    assert sent["asset_id"].startswith("asset_") and not sent["reused"]
    upload = next(iter(fake.state.uploads.values()))
    with open(path, "rb") as handle:
        assert upload["data"] == handle.read(), "the parts join back into the same bytes"
    assert upload["content_type"] == "image/png" and upload["kind"] == "image"
    puts = fake.state.upload_puts
    assert [number for _upload, number, _headers in puts] == list(range(1, len(puts) + 1)) and len(puts) > 1
    for _upload, _number, headers in puts:
        assert headers["content-type"] == "image/png"
        assert not [name for name in headers if name.startswith("x-amz-")], "no checksum headers: the store refuses them"
    again = uploads.upload_file(signed_in, path)
    assert again["asset_id"] == sent["asset_id"] and again["reused"]
    assert len(fake.state.uploads) == 1, "the same bytes are not sent twice in one session"


def test_a_new_workspace_sends_the_file_again(signed_in, fake, tmp_path):
    path = image(tmp_path)
    uploads.upload_file(signed_in, path)
    signed_in.set_workspace("team_fake0000000000000001", "proj_other", "Test team", "Other project")
    uploads.upload_file(signed_in, path)
    assert len(fake.state.uploads) == 2


def test_refusals_send_nothing(signed_in, fake, tmp_path, monkeypatch):
    text = tmp_path / "notes.png"
    text.write_text("not an image")
    with pytest.raises(errors.Refused, match="not a PNG, JPEG or WebP"):
        uploads.upload_file(signed_in, str(text))
    with pytest.raises(errors.Refused, match="was not found"):
        uploads.upload_file(signed_in, str(tmp_path / "missing.png"))
    monkeypatch.setenv("SCENARIO_NO_SPEND", "1")
    with pytest.raises(errors.Refused, match="SCENARIO_NO_SPEND"):
        uploads.upload_file(signed_in, image(tmp_path))
    assert not fake.state.uploads


def test_image_types_are_read_from_the_bytes(tmp_path):
    jpeg = tmp_path / "a.png"  # the name says PNG, the bytes say JPEG
    jpeg.write_bytes(b"\xff\xd8\xff\xe0" + b"\0" * 20)
    webp = tmp_path / "b.webp"
    webp.write_bytes(b"RIFF\0\0\0\0WEBPVP8 ")
    assert uploads.image_type(str(jpeg)) == "jpeg"
    assert uploads.image_type(str(webp)) == "webp"


def test_an_uploaded_image_prices_and_runs_image_to_3d(signed_in, fake, tmp_path):
    form = ModelForm.from_schema(schema(MESHY_IMAGE))
    field = form.image_fields[0]
    assert field.name == "image" and field.is_array and field.max_items == 4, "Scenario gives the list limit as max_length"
    assert form.prompt_field.name == "texturePrompt" and not form.prompt_field.required
    assert form.problems({}) == ["Add an image"]
    params = form.build_params({"image": "asset_x"})
    assert params == {"image": ["asset_x"]}, "a file list is always sent as a list"
    with pytest.raises(errors.ScenarioError):
        signed_in.price(MESHY_IMAGE, {"image": ["asset_notuploaded"]})
    sent = uploads.upload_file(signed_in, image(tmp_path))
    params = form.build_params({"image": [sent["asset_id"]], "shouldRemesh": True, "targetPolycount": 30000})
    quote = signed_in.price(MESHY_IMAGE, params, origin={"lane": lanes.THREE_D_IMAGE.id})
    assert quote.cu_cost_exact == "120"
    row = signed_in.submit(quote.quote_id, approved_cost="120", params=params, origin={"lane": lanes.THREE_D_IMAGE.id}, model_name="Meshy 7.1 - Image to 3D", label="concept")
    assert row["state"] == "remote" and fake.state.paid_runs()[0]["arguments"]["parameters"]["image"] == [sent["asset_id"]]


def test_the_3d_tab_has_text_image_multi_view_and_edit_modes():
    assert lanes.tabs() == ("image", "3d")
    assert [lane.mode for lane in lanes.tab_lanes("3d")] == ["Text", "Image", "Multi-view", "Edit selection"]
    assert lanes.THREE_D_VIEWS.inputs == "views" and lanes.THREE_D_VIEWS.quick_picks[0] == "model_tripo-p2-multiview-to-3d"
    assert lanes.lane_for_model(["img23d"]) is lanes.THREE_D_IMAGE
    assert lanes.lane_for_model(["3d23d"]) is lanes.THREE_D_EDIT and lanes.THREE_D_EDIT.inputs == "mesh"
    assert lanes.THREE_D_IMAGE.quick_picks[0] == MESHY_IMAGE and lanes.THREE_D_IMAGE.formats == ("glb", "fbx")
    assert lanes.THREE_D_EDIT.formats == ("glb",), "edit results are fitted from the GLB"


def test_a_mesh_is_sent_as_3d_and_runs_an_edit_model(signed_in, fake, tmp_path):
    from tests.glb_samples import textured_quad

    form = ModelForm.from_schema(schema("model_tripo-smart-uv"))
    assert [field.name for field in form.mesh_fields] == ["model"] and form.prompt_field is None
    mesh = textured_quad(str(tmp_path / "scn_input_test.glb"))
    with pytest.raises(errors.Refused, match="is not a GLB, FBX or OBJ file"):
        uploads.upload_file(signed_in, image(tmp_path), kind="3d")
    sent = uploads.upload_file(signed_in, mesh, kind="3d")
    upload = next(iter(fake.state.uploads.values()))
    assert (upload["kind"], upload["content_type"]) == ("3d", "model/gltf-binary")
    picture = uploads.upload_file(signed_in, image(tmp_path))
    with pytest.raises(errors.ScenarioError):
        signed_in.price("model_tripo-smart-uv", {"model": picture["asset_id"]})  # an image is not a mesh
    params = form.build_params({"model": sent["asset_id"]})
    quote = signed_in.price("model_tripo-smart-uv", params, origin={"lane": lanes.THREE_D_EDIT.id})
    assert quote.cu_cost_exact == "40"


def test_multi_view_models_have_named_views_in_panel_order():
    from scenario_maya.core.schema import VIEWS, view_of

    tripo = ModelForm.from_schema(schema("model_tripo-p2-multiview-to-3d"))
    assert [field.name for field in tripo.view_fields] == ["frontImage", "leftImage", "backImage", "rightImage"]
    assert tripo.view_fields[0].required and not any(field.required for field in tripo.view_fields[1:])
    hunyuan = ModelForm.from_schema(schema("model_hunyuan-3d-pro-3-1-multiview"))
    assert [view_of(field.name) for field in hunyuan.view_fields] == list(VIEWS), "the schema lists right before back; the panel keeps its own order"
    assert ModelForm.from_schema(schema("model_tripo-p2-image-to-3d")).view_fields == [], "a one-image model has no views"
    assert view_of("image") == "" and view_of("frontImage") == "front"
