"""REST client over the SDK: requests, retry rules, error kinds."""

import pytest

from scenario_maya.core import errors
from scenario_maya.core.auth import ApiKeyAuth
from scenario_maya.core.backend import RestBackend
from scenario_maya.core.http import Response
from scenario_maya.core.rest import RestClient
from tests.fake_backend import API_KEY, API_SECRET


def backend(fake, auth=None):
    return RestBackend(RestClient(auth or ApiKeyAuth(API_KEY, API_SECRET), fake.endpoint), sleep=lambda s: None)


class Workspace(ApiKeyAuth):
    """A key that names a workspace, as an OAuth session does."""

    def workspace_args(self):
        return {"teamId": "team_a", "projectId": "proj_b"}


class Rotating(ApiKeyAuth):
    refreshed = 0

    def refresh(self):
        self.refreshed += 1
        return True


def test_reads_retry_transient_errors(fake):
    fake.state.fail("models", "http500")
    fake.state.fail("models", "http429")
    assert backend(fake).models()[0]
    assert len(fake.state.calls_to("models")) == 3


def test_reads_give_up_after_three_attempts(fake):
    fake.state.fail("models", "http500", times=3)
    with pytest.raises(errors.ServerError):
        backend(fake).models()


def test_a_plan_limit_says_so(fake):
    fake.state.fail("models", "plan_limit", times=3)
    with pytest.raises(errors.RateLimited, match="limit"):
        backend(fake).models()


def test_empty_arguments_are_left_out(fake):
    backend(fake).models(privacy="public", page_token="")
    assert "paginationToken" not in fake.state.calls_to("models")[0]["query"]


def test_a_user_session_names_its_workspace(fake):
    api = backend(fake, Workspace(API_KEY, API_SECRET))
    api.models()
    api.projects("team_c")
    project, team = fake.state.calls
    assert (project["query"]["teamId"], project["query"]["projectId"]) == ("team_a", "proj_b")
    assert team["query"]["teamId"] == "team_c" and "projectId" not in team["query"]


def test_paid_call_refused_by_the_gateway_is_renewed_and_sent_again(fake):
    auth = Rotating(API_KEY, API_SECRET)
    fake.state.fail("generate", "expired")
    assert backend(fake, auth).run("model_x", {"prompt": "a"}).startswith("job_")
    assert auth.refreshed == 1
    assert len(fake.state.paid_runs()) == 1  # the refused attempt never reached the handler


def test_a_paid_call_is_never_retried_by_the_sdk(fake):
    fake.state.fail("generate", "http429")
    with pytest.raises(errors.RateLimited, match="Not sent"):
        backend(fake).run("model_x", {"prompt": "a"})
    assert len(fake.state.calls_to("generate")) == 1


def test_a_refused_key_is_auth_failed(fake):
    with pytest.raises(errors.AuthFailed):
        backend(fake, ApiKeyAuth(API_KEY, "wrong")).models()


def test_a_dry_run_answer_is_read(fake):
    assert backend(fake).estimate("model_spark-test", {"prompt": "x"}) == "2.75"
    assert fake.state.calls_to("generate")[0]["query"]["dryRun"] == "true"
    assert not fake.state.paid_runs()


def test_redirects_are_refused_not_followed(fake):
    fake.state.fail("models", "redirect")
    with pytest.raises(errors.ProtocolError, match="302"):
        backend(fake).models()
    assert not fake.state.file_requests, "the redirect target was never asked"


def test_offline_mode_sends_nothing(fake, monkeypatch):
    monkeypatch.setenv("SCENARIO_MAYA_OFFLINE", "1")
    with pytest.raises(errors.Offline):
        backend(fake).models()
    assert not fake.state.calls


def test_unreachable_server_is_a_network_error():
    api = RestBackend(RestClient(ApiKeyAuth(API_KEY, API_SECRET), "http://127.0.0.1:9/v1"))
    with pytest.raises(errors.NetworkError):
        api.models()


def test_error_lines_are_one_line_with_kind():
    error = errors.NotConfirmed("generate with model_x: no answer")
    assert str(error) == "NotConfirmed: generate with model_x: no answer"
    assert "\n" not in str(error)


def test_http_status_mapping():
    assert isinstance(errors.from_http_status(401, ""), errors.AuthFailed)
    assert isinstance(errors.from_http_status(429, ""), errors.RateLimited)
    assert isinstance(errors.from_http_status(503, ""), errors.ServerError)
    assert Response(200, {"retry-after": "5"}).header("Retry-After") == "5"
