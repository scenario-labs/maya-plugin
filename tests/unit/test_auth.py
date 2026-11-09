"""Sign-in: OAuth browser and device flows against the fake server, credential stores."""

import os
import stat
import sys
import threading
import urllib.parse
import urllib.request

import pytest

from scenario_maya.core import errors
from scenario_maya.core.auth import ACCOUNT_REFRESH, ApiKeyAuth, Credentials, mask, parse_key_pair
from scenario_maya.core.credstore import FileStore, MacKeychainStore, MemoryStore
from scenario_maya.core.oauth import PRODUCTION_ISSUER, LoopbackReceiver, OAuthApp, OAuthClient, pkce_pair, selected_app
from scenario_maya.core.settings import Settings
from tests.fake_backend.fake_scenario import CLIENT_ID


def browser(url):
    """Plays the user's browser: follows the authorize redirect to the loopback listener."""
    threading.Thread(target=lambda: urllib.request.urlopen(url, timeout=10).read(), daemon=True).start()


def test_pkce_pair_shape():
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128 and "=" not in challenge


def test_browser_sign_in_end_to_end(session, fake):
    session.sign_in_browser(browser)
    assert session.status()["method"] == "oauth"
    client_id = session.settings.get("oauth_client_id")
    assert client_id in fake.state.clients
    refresh = session.credentials.store.get(ACCOUNT_REFRESH)
    assert refresh and refresh.startswith("rt_")
    settings_text = open(session.settings.path).read()
    assert refresh not in settings_text
    assert session.backend().teams()


def test_sign_in_uses_the_registered_application(session, fake):
    session.sign_in_browser(browser)
    assert fake.state.registrations == []
    assert session.settings.get("oauth_client_id") == CLIENT_ID
    query = fake.state.authorize_queries[-1]
    assert query["client_id"] == CLIENT_ID and query["scope"] == "openid offline_access"
    assert "resource" not in query
    redirect = urllib.parse.urlparse(query["redirect_uri"])
    assert (redirect.hostname, redirect.path) == ("127.0.0.1", "/callback") and redirect.port


def test_a_session_from_another_application_is_not_resumed(session, fake):
    session.sign_in_browser(browser)
    other = OAuthClient(app=OAuthApp(fake.base, "a_client_registered_by_an_older_install"))
    assert Credentials(session.settings, session.credentials.store, other).resolve() is None


def test_sign_in_waits_for_a_registered_application(fake):
    credentials = Credentials(Settings(), MemoryStore(), OAuthClient(app=OAuthApp(fake.base, "")))
    with pytest.raises(errors.Refused, match="not available in this release yet"):
        credentials.client_id()


def test_developer_override_names_issuer_and_client_together(monkeypatch):
    monkeypatch.delenv("SCENARIO_OAUTH_ISSUER", raising=False)
    monkeypatch.delenv("SCENARIO_OAUTH_CLIENT_ID", raising=False)
    assert selected_app() == OAuthApp(PRODUCTION_ISSUER, "l6aUFP02nCjsHHDp")
    monkeypatch.setenv("SCENARIO_OAUTH_ISSUER", "https://idp.example.invalid/")
    with pytest.raises(errors.ProtocolError):
        selected_app()
    monkeypatch.setenv("SCENARIO_OAUTH_CLIENT_ID", "dev_client")
    assert selected_app() == OAuthApp("https://idp.example.invalid", "dev_client")
    monkeypatch.setenv("SCENARIO_OAUTH_ISSUER", "http://idp.example.invalid")
    with pytest.raises(errors.ProtocolError):
        selected_app()


def test_oauth_calls_carry_workspace_ids(session, fake):
    session.sign_in_browser(browser)
    session.set_workspace("team_a", "proj_b")
    session.backend().models()
    args = fake.state.tool_calls("models_list")[-1]["arguments"]
    assert args["team_id"] == "team_a" and args["project_id"] == "proj_b"


def test_refresh_rotates_and_is_stored(session, fake):
    session.sign_in_browser(browser)
    first = session.credentials.store.get(ACCOUNT_REFRESH)
    assert session.auth.refresh()
    second = session.credentials.store.get(ACCOUNT_REFRESH)
    assert second != first and second in fake.state.refresh_tokens


def test_expired_access_token_refreshes_before_use(session, fake):
    fake.state.token_lifetime = 30  # under the 60 s margin
    session.sign_in_browser(browser)
    before = session.credentials.store.get(ACCOUNT_REFRESH)
    session.backend().teams()
    assert session.credentials.store.get(ACCOUNT_REFRESH) != before


def test_stored_session_survives_restart(session, fake):
    session.sign_in_browser(browser)
    session.set_workspace("team_a", "proj_b")
    restarted = Credentials(session.settings, session.credentials.store, session.credentials.oauth).resolve()
    assert restarted.kind == "oauth" and restarted.workspace_args() == {"team_id": "team_a", "project_id": "proj_b"}
    assert restarted.authorization().startswith("Bearer ")


def test_declined_sign_in(session, fake):
    fake.state.auto_approve = False
    with pytest.raises(errors.AuthFailed, match="access_denied"):
        session.sign_in_browser(browser)
    assert not session.signed_in


def test_device_sign_in(session, fake):
    shown = []
    client = session.credentials.oauth
    original = client.poll_device
    client.poll_device = lambda cid, dev, cancel=None, sleep=None: original(cid, dev, cancel, sleep=lambda s: None)
    session.sign_in_device(shown.append)
    assert shown[0].user_code == "WXYZ-1234"
    assert session.status()["method"] == "oauth"


def test_sign_out_revokes_and_deletes(session, fake):
    session.sign_in_browser(browser)
    refresh = session.credentials.store.get(ACCOUNT_REFRESH)
    session.sign_out()
    assert refresh in fake.state.revoked
    assert session.credentials.store.get(ACCOUNT_REFRESH) is None
    assert not session.signed_in and session.credentials.resolve() is None


def test_a_session_from_another_application_is_forgotten_without_revoking(session, fake):
    session.sign_in_browser(browser)
    refresh = session.credentials.store.get(ACCOUNT_REFRESH)
    other = Credentials(session.settings, session.credentials.store, OAuthClient(app=OAuthApp(fake.base, "another_application")))
    other.sign_out()
    assert refresh not in fake.state.revoked  # its provider is unknown: the token never goes to this one
    assert other.store.get(ACCOUNT_REFRESH) is None


def test_sign_out_forgets_when_the_provider_is_unreachable(session, fake):
    session.sign_in_browser(browser)
    offline = Credentials(session.settings, session.credentials.store, OAuthClient(app=OAuthApp(fake.base + "/unreachable", CLIENT_ID)))
    offline.sign_out()
    assert offline.store.get(ACCOUNT_REFRESH) is None and offline.resolve() is None


def test_loopback_rejects_wrong_state():
    receiver = LoopbackReceiver("expected", ports=(0,))
    port = receiver.start()
    try:
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=x&state=forged", timeout=5)
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(errors.Refused):
            receiver.wait(5, cancel)
    finally:
        receiver.stop()


def test_metadata_must_be_https_or_loopback():
    from scenario_maya.core.oauth import Metadata

    with pytest.raises(errors.ProtocolError):
        Metadata.from_dict({"authorization_endpoint": "http://evil.example/authorize", "token_endpoint": "https://x/token"})


def test_environment_credentials_win(monkeypatch):
    monkeypatch.setenv("SCENARIO_API_KEY", "api_env")
    monkeypatch.setenv("SCENARIO_API_SECRET", "s")
    auth = Credentials(Settings(), MemoryStore(), OAuthClient()).resolve()
    assert isinstance(auth, ApiKeyAuth) and auth.source == "environment"


def test_key_pair_parsing_and_mask():
    assert parse_key_pair("api_abc:def") == ("api_abc", "def")
    assert parse_key_pair("hello") == ("", "")
    assert mask("api_gDAU12345678917Kk") == "api_gDAU...17Kk"


def test_settings_refuse_secrets():
    with pytest.raises(ValueError):
        Settings().update(api_secret="x")
    with pytest.raises(ValueError):
        Settings().update(refresh_token="x")


def test_file_store_is_owner_only(tmp_path):
    store = FileStore(str(tmp_path / "c.json"))
    store.set("a", "secret-1")
    assert store.get("a") == "secret-1"
    if not sys.platform.startswith("win"):
        assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600
    assert store.delete("a") and store.get("a") is None


@pytest.mark.skipif(not MacKeychainStore.available(), reason="macOS only")
def test_macos_keychain_round_trip():
    store = MacKeychainStore(service="Scenario for Maya TEST")
    account = "unit-test@example.invalid"
    store.delete(account)
    store.set(account, 'value with "quotes" and spaces')
    assert store.get(account) == 'value with "quotes" and spaces'
    store.set(account, "second")
    assert store.get(account) == "second"
    assert store.delete(account)
    assert store.get(account) is None
