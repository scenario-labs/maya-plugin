"""The money contract end to end against the fake Scenario server (0 CU)."""

import pytest

from scenario_maya.core import errors
from tests.fake_backend import API_KEY, API_SECRET


@pytest.fixture
def signed_in(session):
    session.sign_in_api_key(API_KEY, API_SECRET)
    return session


def test_sign_in_with_api_key_stores_secret_outside_settings(signed_in, private_home):
    status = signed_in.status()
    assert status["signed_in"] and status["method"] == "api_key"
    assert status["project"]["name"] == "Test project"
    settings_text = (private_home / "settings.json").read_text()
    assert API_SECRET not in settings_text
    assert API_KEY in settings_text  # the key id is not a secret
    assert signed_in.credentials.store.get(f"api_secret:{API_KEY}") == API_SECRET


def test_bad_key_is_refused_and_nothing_is_stored(session):
    with pytest.raises(errors.AuthFailed):
        session.sign_in_api_key(API_KEY, "wrong")
    assert not session.signed_in
    assert session.settings.get("api_key_id") == ""


def test_price_then_generate_once(signed_in, fake):
    params = {"prompt": "a brass lantern"}
    quote = signed_in.price("model_openai-gpt-image-2-5-flare", params)
    assert quote.cu_cost_exact == "11"
    assert not fake.state.paid_runs()
    row = signed_in.submit(quote.quote_id, approved_cost="11", params=params)
    assert row["state"] == "remote" and row["remote_job_id"].startswith("job_fake")
    assert row["cost_exact"] == "11"
    assert len(fake.state.paid_runs()) == 1
    with pytest.raises(errors.QuoteError, match="already used"):
        signed_in.submit(quote.quote_id, approved_cost="11", params=params)
    assert len(fake.state.paid_runs()) == 1


def test_fractional_price_must_be_echoed_exactly(signed_in):
    quote = signed_in.price("model_spark-test", {"prompt": "x"})
    assert quote.cu_cost_exact == "2.75"
    with pytest.raises(errors.QuoteError, match="exactly '2.75'"):
        signed_in.submit(quote.quote_id, approved_cost="2.8", params={"prompt": "x"})


def test_changed_parameters_invalidate_the_quote(signed_in, fake):
    quote = signed_in.price("model_openai-gpt-image-2-5-flare", {"prompt": "a"})
    with pytest.raises(errors.QuoteError, match="parameters changed"):
        signed_in.submit(quote.quote_id, approved_cost="11", params={"prompt": "b"})
    assert not fake.state.paid_runs()


def test_no_spend_refuses_before_sending(signed_in, fake, monkeypatch):
    quote = signed_in.price("model_openai-gpt-image-2-5-flare", {"prompt": "a"})
    monkeypatch.setenv("SCENARIO_NO_SPEND", "1")
    with pytest.raises(errors.Refused, match="SCENARIO_NO_SPEND"):
        signed_in.submit(quote.quote_id, approved_cost="11")
    assert not fake.state.paid_runs()


@pytest.mark.parametrize("fault", ["drop", "http500", "http429", "tool_error_500", "tool_error_generic"])
def test_unknown_outcome_is_not_confirmed_and_never_resent(signed_in, fake, fault):
    params = {"prompt": "a crate"}
    quote = signed_in.price("model_meshy-7-1-txt23d", params)
    fake.state.fail("model_run", fault)
    with pytest.raises(errors.NotConfirmed):
        signed_in.submit(quote.quote_id, approved_cost="120", params=params)
    assert len(fake.state.paid_runs()) == 1, "a paid call is sent exactly once"
    rows = signed_in.ledger.list(states=("uncertain",))
    assert len(rows) == 1 and rows[0]["cost_exact"] == "120"
    again = signed_in.price("model_meshy-7-1-txt23d", params)
    with pytest.raises(errors.Refused, match="Not confirmed"):
        signed_in.submit(again.quote_id, approved_cost="120", params=params)
    assert len(fake.state.paid_runs()) == 1


def test_a_different_payload_is_not_blocked(signed_in, fake):
    quote = signed_in.price("model_meshy-7-1-txt23d", {"prompt": "a crate"})
    fake.state.fail("model_run", "drop")
    with pytest.raises(errors.NotConfirmed):
        signed_in.submit(quote.quote_id, approved_cost="120")
    other = signed_in.price("model_meshy-7-1-txt23d", {"prompt": "a barrel"})
    assert signed_in.submit(other.quote_id, approved_cost="120")["state"] == "remote"


def test_definite_refusal_fails_without_blocking(signed_in, fake):
    params = {"prompt": "a crate"}
    quote = signed_in.price("model_meshy-7-1-txt23d", params)
    fake.state.fail("model_run", "tool_error_400")
    with pytest.raises(errors.ToolError, match="prompt is required"):
        signed_in.submit(quote.quote_id, approved_cost="120", params=params)
    assert signed_in.ledger.list(states=("failed",))
    again = signed_in.price("model_meshy-7-1-txt23d", params)
    assert signed_in.submit(again.quote_id, approved_cost="120", params=params)["state"] == "remote"


def test_moderation_is_blocked_and_failed(signed_in, fake):
    quote = signed_in.price("model_openai-gpt-image-2-5-flare", {"prompt": "x"})
    fake.state.fail("model_run", "moderation")
    with pytest.raises(errors.Blocked):
        signed_in.submit(quote.quote_id, approved_cost="11")
    row = signed_in.ledger.list(states=("failed",))[0]
    assert row["error"].startswith("Blocked")


def test_review_not_confirmed_person_only(signed_in, fake):
    params = {"prompt": "a crate"}
    quote = signed_in.price("model_meshy-7-1-txt23d", params)
    fake.state.fail("model_run", "drop")
    with pytest.raises(errors.NotConfirmed):
        signed_in.submit(quote.quote_id, approved_cost="120", params=params)
    row = signed_in.ledger.list(states=("uncertain",))[0]
    candidates = signed_in.candidates(row["local_id"])
    assert len(candidates) == 1 and candidates[0]["model_id"] == "model_meshy-7-1-txt23d"
    with pytest.raises(errors.Refused, match="Only a person"):
        signed_in.link(row["local_id"], candidates[0]["job_id"], by_person=False)
    with pytest.raises(errors.Refused, match="Only a person"):
        signed_in.mark_reviewed(row["local_id"], by_person=False)
    linked = signed_in.link(row["local_id"], candidates[0]["job_id"], by_person=True)
    assert linked["remote_job_id"] == candidates[0]["job_id"]
    assert len(fake.state.paid_runs()) == 1


def test_mark_reviewed_unblocks(signed_in, fake):
    params = {"prompt": "a crate"}
    quote = signed_in.price("model_meshy-7-1-txt23d", params)
    fake.state.fail("model_run", "http500")
    with pytest.raises(errors.NotConfirmed):
        signed_in.submit(quote.quote_id, approved_cost="120", params=params)
    row = signed_in.ledger.list(states=("uncertain",))[0]
    signed_in.mark_reviewed(row["local_id"], by_person=True)
    again = signed_in.price("model_meshy-7-1-txt23d", params)
    assert signed_in.submit(again.quote_id, approved_cost="120", params=params)["state"] == "remote"


def test_job_reaches_success_with_assets_and_charge(signed_in, fake):
    quote = signed_in.price("model_openai-gpt-image-2-5-flare", {"prompt": "x"})
    row = signed_in.submit(quote.quote_id, approved_cost="11")
    for _ in range(3):
        row = signed_in.refresh_job(row["local_id"])
    assert row["state"] == "succeeded"
    assert row["charged_exact"] == "11"
    assert row["result"]["asset_ids"]


def test_workspace_change_clears_quotes(signed_in):
    quote = signed_in.price("model_openai-gpt-image-2-5-flare", {"prompt": "x"})
    signed_in.set_workspace("team_x", "proj_y")
    with pytest.raises(errors.QuoteError):
        signed_in.submit(quote.quote_id, approved_cost="11")


def test_price_check_returning_a_job_stops_price_checks(signed_in, fake, monkeypatch):
    original = fake.httpd.RequestHandlerClass._tool_model_run

    def leaky(handler, args):
        args = dict(args)
        args.pop("dry_run", None)
        return original(handler, args)

    monkeypatch.setattr(fake.httpd.RequestHandlerClass, "_tool_model_run", leaky)
    with pytest.raises(errors.ProtocolError, match="ALARM"):
        signed_in.price("model_openai-gpt-image-2-5-flare", {"prompt": "x"})
    with pytest.raises(errors.Refused, match="stopped"):
        signed_in.price("model_openai-gpt-image-2-5-flare", {"prompt": "x"})
    tracked = signed_in.ledger.list(states=("remote",))
    assert tracked and tracked[0]["driver"] == "price-check"
