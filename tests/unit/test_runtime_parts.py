"""Status words, log redaction, diagnostics and workspace choice (no Maya, 0 CU)."""

import logging

from scenario_maya.core import diagnostics, log
from scenario_maya.core.status import status_tone, status_word
from scenario_maya.core.workspaces import automatic_choice, load
from tests.fake_backend import API_KEY, API_SECRET


def test_status_words_follow_the_spec():
    assert status_word({"state": "remote", "result": {"status": "in-progress", "progress": 0.42}}) == "Generating 42%"
    assert status_word({"state": "remote", "result": {"status": "warming-up"}}) == "Starting"
    assert status_word({"state": "remote"}) == "Queued"
    assert status_word({"state": "uncertain"}) == "Not confirmed"
    assert status_word({"state": "downloading", "result": {"download_progress": 0.63}}) == "Downloading 63%"
    assert status_word({"state": "failed", "error": "Blocked: flagged"}) == "Blocked"
    assert status_word({"state": "failed", "error": "bad input"}) == "Failed"
    assert status_word({"state": "applying", "owner": "", "hint": "Maya stopped during the apply."}) == "Needs review"
    assert status_word({"state": "ready"}) == "Ready to apply"


def test_status_tones():
    assert status_tone({"state": "uncertain"}) == "warning"
    assert status_tone({"state": "failed"}) == "error"
    assert status_tone({"state": "applied"}) == "ok"
    assert status_tone({"state": "remote"}) == "busy"


def test_log_masks_credentials_and_signed_links(private_home):
    path = log.configure()
    try:
        log.LOGGER.info("auth %s", "Bearer at_abcdefghijklmnop")
        log.LOGGER.info("url https://cdn.example/a.png?X-Amz-Signature=deadbeef&Expires=1 and Basic YWJjOmRlZg==")
        for handler in log.LOGGER.handlers:
            handler.flush()
        text = open(path).read()
    finally:
        log.close()
    assert "abcdefghijklmnop" not in text and "deadbeef" not in text and "YWJjOmRlZg" not in text
    assert "Bearer ***" in text and "X-Amz-Signature=***" in text
    assert logging.getLogger("scenario_maya").handlers == []


def test_diagnostics_never_contain_the_secret(session):
    session.sign_in_api_key(API_KEY, API_SECRET)
    text = diagnostics.report(session)
    assert API_SECRET not in text
    assert "Signed in: yes, api_key" in text and "Test project" in text


def test_workspace_choice():
    one = [{"id": "t1", "name": "T", "projects": [{"id": "p1", "name": "P"}]}]
    assert automatic_choice(one) == (one[0], one[0]["projects"][0])
    many = [{"id": "t1", "projects": [{"id": "p1"}, {"id": "p2"}]}, {"id": "t2", "projects": [{"id": "p3"}]}]
    assert automatic_choice(many) is None
    assert automatic_choice(many, "t2", "p3")[1]["id"] == "p3"
    assert automatic_choice(many, "t2", "gone") is None


def test_workspaces_load_fills_missing_projects():
    class Backend:
        def teams(self):
            return [{"id": "t1"}, {"name": "no id"}]

        def projects(self, team_id):
            return [{"id": "p_" + team_id}]

    assert load(Backend()) == [{"id": "t1", "projects": [{"id": "p_t1"}]}]
