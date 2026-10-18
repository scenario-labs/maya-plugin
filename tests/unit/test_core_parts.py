"""Quotes, ledger states and recovery, schema forms, canonical JSON."""

import json
import os

import pytest

from scenario_maya.core import errors
from scenario_maya.core.jsonutil import canonical_json, cu_display, cu_exact, payload_hash
from scenario_maya.core.ledger import Ledger
from scenario_maya.core.quotes import QuoteBook, input_assets
from scenario_maya.core.schema import ModelForm

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "mcp")


def schema(model_id):
    with open(os.path.join(FIXTURES, f"schema_{model_id}.json")) as handle:
        return json.load(handle)


# -- canonical JSON and costs ------------------------------------------------


def test_canonical_json_is_stable_and_drops_nulls():
    assert canonical_json({"b": 1, "a": None, "c": [1, None]}) == '{"b":1,"c":[1,null]}'
    assert payload_hash({"x": 1, "y": 2}) == payload_hash({"y": 2, "x": 1})


@pytest.mark.parametrize("value,exact", [(120, "120"), (120.0, "120"), (2.75, "2.75"), (0.1, "0.1"), ("15.50", "15.5"), (0, "0")])
def test_cu_exact(value, exact):
    assert cu_exact(value) == exact


def test_cu_exact_rejects_nonsense():
    for bad in (True, None, -1, "abc", float("nan")):
        with pytest.raises(ValueError):
            cu_exact(bad)


def test_cu_display():
    assert cu_display("1200") == "1,200 CU"
    assert cu_display("2.75") == "2.75 CU"
    assert cu_display("0.0004") == "< 0.001 CU"
    assert cu_display("0") == "0 CU"
    assert cu_display("11.25") == "11.25 CU"
    assert cu_display("1.23456") == "1.235 CU"
    assert cu_display("9999") == "9,999 CU"
    assert cu_display("12345") == "12.3K CU"
    assert cu_display("120000") == "120K CU"
    assert cu_display("2500000") == "2.5M CU"


# -- quotes ------------------------------------------------------------------


def test_quote_expires():
    now = [1000.0]
    book = QuoteBook(clock=lambda: now[0])
    quote = book.issue(kind="model", target_id="m", params={"p": 1}, workspace="w", cu_cost_exact="5")
    now[0] += 121
    with pytest.raises(errors.QuoteError, match="expired"):
        book.take(quote.quote_id, approved_cost="5")


def test_quote_bound_to_origin():
    book = QuoteBook()
    origin = {"scene_uuid": "s1", "target": "|crate_GEO", "fingerprint": "f1"}
    quote = book.issue(kind="model", target_id="m", params={}, workspace="w", cu_cost_exact="5", origin=origin)
    with pytest.raises(errors.QuoteError, match="scene or target"):
        book.take(quote.quote_id, origin=dict(origin, fingerprint="f2"))
    assert book.take(quote.quote_id, origin=origin).used


def test_quote_public_view_has_no_params():
    book = QuoteBook()
    quote = book.issue(kind="model", target_id="m", params={"prompt": "secret plan"}, workspace="w", cu_cost_exact="5")
    assert "secret plan" not in json.dumps(quote.public())


def test_input_assets_found_anywhere():
    assert input_assets({"image": "asset_a", "refs": ["asset_b", "x"], "n": {"m": "asset_a"}}) == ("asset_a", "asset_b")


# -- ledger ------------------------------------------------------------------


def make_row(ledger, **kw):
    values = dict(kind="model", target_id="m", workspace="w", payload_hash="h", params={"p": 1}, cost_exact="5")
    values.update(kw)
    return ledger.prepare(**values)


def test_state_machine_refuses_illegal_moves(tmp_path):
    ledger = Ledger(str(tmp_path / "l.sqlite3"))
    row = make_row(ledger)
    with pytest.raises(errors.Refused):
        ledger.set_state(row["local_id"], "applied")
    ledger.claim(row["local_id"])
    with pytest.raises(errors.Refused, match="not sent again"):
        ledger.claim(row["local_id"])
    ledger.close()


def test_claim_blocks_identical_not_confirmed(tmp_path):
    ledger = Ledger(str(tmp_path / "l.sqlite3"))
    first = make_row(ledger, target="|crate")
    ledger.claim(first["local_id"])
    ledger.not_confirmed(first["local_id"], "no answer")
    twin = make_row(ledger, target="|crate")
    with pytest.raises(errors.Refused, match="Not confirmed"):
        ledger.claim(twin["local_id"])
    other_target = make_row(ledger, target="|barrel")
    assert ledger.claim(other_target["local_id"])["state"] == "submitting"
    ledger.close()


def test_recovery_after_a_crash_marks_submitting_not_confirmed(tmp_path):
    path = str(tmp_path / "l.sqlite3")
    crashed = Ledger(path, session_id="crashed")
    row = make_row(crashed)
    crashed.claim(row["local_id"])
    dl = make_row(crashed, payload_hash="h2")
    crashed.claim(dl["local_id"])
    crashed.submitted(dl["local_id"], "job_1")
    crashed.set_state(dl["local_id"], "succeeded")
    crashed.set_state(dl["local_id"], "downloading", owner="crashed")
    crashed.close()  # the crashed session's lock is gone
    survivor = Ledger(path, session_id="next")
    changed = survivor.recover()
    assert changed["not_confirmed"] == [row["local_id"]]
    assert changed["interrupted_downloads"] == [dl["local_id"]]
    assert survivor.get(row["local_id"])["state"] == "uncertain"
    survivor.close()


def test_recovery_leaves_a_live_session_alone(tmp_path):
    path = str(tmp_path / "l.sqlite3")
    live = Ledger(path, session_id="live")
    row = make_row(live)
    live.claim(row["local_id"])
    other = Ledger(path, session_id="other")
    assert other.recover()["not_confirmed"] == []
    assert other.get(row["local_id"])["state"] == "submitting"
    other.close()
    live.close()


def test_events_are_recorded(tmp_path):
    ledger = Ledger(str(tmp_path / "l.sqlite3"))
    row = make_row(ledger)
    ledger.claim(row["local_id"])
    ledger.submitted(row["local_id"], "job_1")
    assert [e["state"] for e in ledger.events(row["local_id"])] == ["prepared", "submitting", "remote"]
    ledger.close()


# -- schema forms ------------------------------------------------------------


def test_form_from_recorded_3d_schema():
    form = ModelForm.from_schema(schema("model_meshy-7-1-txt23d"))
    assert form.prompt_field.name == "prompt" and form.prompt_field.prompt_spark
    assert form.field("textureImage").is_file and form.field("textureImage").kind == "image"
    assert form.field("geometryResolution").cost_impact
    assert form.problems({}) == ["Needs a prompt"]
    assert "at most 300000" in form.problems({"prompt": "x", "targetPolycount": 400000})[0]


def test_build_params_leaves_defaults_out():
    form = ModelForm.from_schema(schema("model_meshy-7-1-txt23d"))
    params = form.build_params({"prompt": "a crate", "topology": "triangle", "textureResolution": "4k", "targetPolycount": None})
    assert params == {"prompt": "a crate", "textureResolution": "4k"}


def test_file_fields_need_asset_ids():
    form = ModelForm.from_schema(schema("model_meshy-remesh"))
    assert form.problems({}) == ["Needs a model (3d)"]
    assert "asset id" in form.problems({"model": "/Users/me/crate.glb"})[0]
    assert form.problems({"model": "asset_abc"}) == []


def test_file_array_cardinality():
    form = ModelForm.from_schema(schema("model_openai-gpt-image-2-5-flare"))
    assert form.field("referenceImages").is_array
    assert form.build_params({"prompt": "x", "referenceImages": "asset_a"}) == {"prompt": "x", "referenceImages": ["asset_a"]}
