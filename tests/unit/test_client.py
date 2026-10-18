"""MCP client: reply parsing, retry rules, error kinds."""

import json
import os

import pytest

from scenario_maya.core import errors
from scenario_maya.core.auth import ApiKeyAuth
from scenario_maya.core.http import Response
from scenario_maya.core.mcp import McpClient, parse_event_stream, tool_error_detail, tool_payload
from tests.fake_backend import API_KEY, API_SECRET

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "mcp")


def fixture(name):
    with open(os.path.join(FIXTURES, name)) as handle:
        return json.load(handle)


def client(fake, **kw):
    return McpClient(ApiKeyAuth(API_KEY, API_SECRET), fake.endpoint, sleep=lambda s: None, **kw)


def test_event_stream_with_progress_before_result():
    body = 'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\nevent: message\ndata: {"jsonrpc":"2.0","id":3,"result":{"ok":true}}\n\n'
    messages = parse_event_stream(body)
    assert messages[-1]["id"] == 3 and messages[0]["method"] == "notifications/progress"


def test_structured_content_wins_and_text_fallback():
    recorded = fixture("model_run_dry_run_result.json")
    assert tool_payload(recorded).data["creativeUnitsCost"] == 120
    text_only = {"content": [{"type": "text", "text": '{"a": 1}'}]}
    assert tool_payload(text_only).data == {"a": 1}


def test_tool_error_detail_reads_api_status_and_reason():
    message, status = tool_error_detail(tool_payload(fixture("tool_error_400_result.json")))
    assert status == 400
    assert message.startswith("Input prompt is required")
    assert "mcpt_fixture" in message


@pytest.mark.parametrize("mode", ["sse", "json"])
def test_reads_work_in_both_reply_modes(fake, mode):
    fake.state.reply_mode = mode
    data = client(fake).call_tool("teams_list", {}).data
    assert data["teams"][0]["projects"][0]["id"].startswith("proj_")


def test_reads_retry_transient_errors(fake):
    fake.state.fail("teams_list", "http500")
    fake.state.fail("teams_list", "http429")
    assert client(fake).call_tool("teams_list", {}).data["teams"]
    assert len(fake.state.tool_calls("teams_list")) == 3


def test_reads_give_up_after_three_attempts(fake):
    fake.state.fail("teams_list", "http500", times=3)
    with pytest.raises(errors.ServerError):
        client(fake).call_tool("teams_list", {})


def test_null_arguments_are_dropped(fake):
    client(fake).call_tool("models_list", {"limit": 2, "page_token": None})
    assert "page_token" not in fake.state.tool_calls("models_list")[0]["arguments"]


def test_expired_session_is_renewed_once(fake):
    fake.state.issue_sessions = True
    mcp = client(fake)
    mcp.initialize()
    fake.state.fail("teams_list", "session_404")
    assert mcp.call_tool("teams_list", {}).data["teams"]


def test_paid_401_is_refreshed_and_sent_again(fake):
    class Rotating(ApiKeyAuth):
        refreshed = 0

        def refresh(self):
            self.refreshed += 1
            return True

    auth = Rotating(API_KEY, API_SECRET)
    mcp = McpClient(auth, fake.endpoint, sleep=lambda s: None)
    fake.state.fail("model_run", "http401")
    result = mcp.call_tool("model_run", {"model_id": "model_x", "parameters": {"prompt": "a"}}, paid=True)
    assert result.data["job_id"]
    assert auth.refreshed == 1
    assert len(fake.state.paid_runs()) == 1  # the 401 attempt never reached the tool


def test_offline_mode_sends_nothing(fake, monkeypatch):
    monkeypatch.setenv("SCENARIO_MAYA_OFFLINE", "1")
    with pytest.raises(errors.Offline):
        client(fake).call_tool("teams_list", {})
    assert not fake.state.calls


def test_unreachable_server_is_a_network_error():
    mcp = McpClient(ApiKeyAuth(API_KEY, API_SECRET), "http://127.0.0.1:9/mcp", sleep=lambda s: None)
    with pytest.raises(errors.NetworkError):
        mcp.call_tool("teams_list", {})


def test_error_lines_are_one_line_with_kind():
    error = errors.NotConfirmed("model_run: no answer")
    assert str(error) == "NotConfirmed: model_run: no answer"
    assert "\n" not in str(error)


def test_http_status_mapping():
    assert isinstance(errors.from_http_status(401, ""), errors.AuthFailed)
    assert isinstance(errors.from_http_status(429, ""), errors.RateLimited)
    assert isinstance(errors.from_http_status(503, ""), errors.ServerError)
    assert Response(200, {"retry-after": "5"}).header("Retry-After") == "5"
