"""Credentials in use: API key or OAuth session, and where they come from.

Read order: environment variables (``SCENARIO_API_KEY`` and
``SCENARIO_API_SECRET``), then the OS credential store as named by the
settings, then nothing (signed out). The access token of an OAuth session is
kept in memory only; its refresh token sits in the credential store and is
rotated there.
"""

from __future__ import annotations

import base64
import os
import threading
import time

from . import errors
from .credstore import CredentialStore, default_store
from .oauth import OAuthClient, Tokens
from .settings import Settings

ACCOUNT_REFRESH = "oauth_refresh_token"


def api_secret_account(key_id: str) -> str:
    return f"api_secret:{key_id}"


def mask(key_id: str) -> str:
    if len(key_id) <= 12:
        return key_id[:4] + "..."
    return f"{key_id[:8]}...{key_id[-4:]}"


def parse_key_pair(text: str) -> tuple:
    """Accepts ``key:secret`` pasted in one field; returns ``(key, secret)`` or ``("", "")``."""
    value = (text or "").strip()
    if ":" in value and value.startswith("api_"):
        key, _, secret = value.partition(":")
        return key.strip(), secret.strip()
    return "", ""


class ApiKeyAuth:
    kind = "api_key"

    def __init__(self, key_id: str, secret: str, source: str = "credential store") -> None:
        if not key_id or not secret:
            raise errors.SignInRequired("API key and secret are both needed.")
        self.key_id = key_id.strip()
        self._header = "Basic " + base64.b64encode(f"{self.key_id}:{secret.strip()}".encode()).decode()
        self.source = source

    def authorization(self) -> str:
        return self._header

    def refresh(self) -> bool:
        return False

    def ensure_fresh(self, min_seconds: float = 300.0) -> None:
        return None

    def workspace_args(self) -> dict:
        return {}

    def label(self) -> str:
        return f"API key {mask(self.key_id)} ({self.source})"


class OAuthAuth:
    """Bearer session with one lock around refresh, so parallel workers never
    refresh twice. Before a paid call, ``ensure_fresh`` refreshes when less
    than five minutes remain, so the paid request itself never meets an
    expired token."""

    kind = "oauth"

    def __init__(
        self,
        client: OAuthClient,
        client_id: str,
        tokens: Tokens,
        store: CredentialStore | None = None,
        team_id: str = "",
        project_id: str = "",
    ) -> None:
        self.client = client
        self.client_id = client_id
        self._tokens = tokens
        self._store = store
        self._lock = threading.Lock()
        self.team_id = team_id
        self.project_id = project_id
        self.source = "browser sign-in"

    def _refresh_locked(self) -> None:
        if not self._tokens.refresh_token:
            raise errors.SignInRequired("The Scenario session ended; sign in again.")
        fresh = self.client.refresh(self.client_id, self._tokens.refresh_token)
        if fresh.refresh_token and fresh.refresh_token != self._tokens.refresh_token and self._store is not None:
            self._store.set(ACCOUNT_REFRESH, fresh.refresh_token)
        self._tokens = fresh

    def authorization(self) -> str:
        with self._lock:
            if not self._tokens.access_token or self._tokens.expires_in() < 60:
                self._refresh_locked()
            return "Bearer " + self._tokens.access_token

    def refresh(self) -> bool:
        with self._lock:
            try:
                self._refresh_locked()
                return True
            except errors.AuthFailed:
                return False

    def ensure_fresh(self, min_seconds: float = 300.0) -> None:
        with self._lock:
            if not self._tokens.access_token or self._tokens.expires_in() < min_seconds:
                self._refresh_locked()

    def workspace_args(self) -> dict:
        out = {}
        if self.team_id:
            out["team_id"] = self.team_id
        if self.project_id:
            out["project_id"] = self.project_id
        return out

    def refresh_token(self) -> str:
        with self._lock:
            return self._tokens.refresh_token

    def label(self) -> str:
        return "Signed in with Scenario"


class Credentials:
    """Resolves, saves and clears the active credentials."""

    def __init__(self, settings: Settings, store: CredentialStore | None = None, oauth: OAuthClient | None = None) -> None:
        self.settings = settings
        self.store = store or default_store()
        self.oauth = oauth or OAuthClient()

    def resolve(self):
        env_key = os.environ.get("SCENARIO_API_KEY", "").strip()
        env_secret = os.environ.get("SCENARIO_API_SECRET", "").strip()
        if env_key and env_secret:
            return ApiKeyAuth(env_key, env_secret, source="environment")
        method = self.settings.get("auth_method")
        if method == "api_key":
            key_id = self.settings.get("api_key_id")
            secret = self.store.get(api_secret_account(key_id)) if key_id else None
            if key_id and secret:
                return ApiKeyAuth(key_id, secret, source=self.store.name)
            return None
        if method == "oauth":
            client_id = self.settings.get("oauth_client_id")
            refresh = self.store.get(ACCOUNT_REFRESH) if client_id else None
            if client_id and refresh:
                team = os.environ.get("SCENARIO_TEAM_ID", "").strip() or self.settings.get("team_id")
                project = os.environ.get("SCENARIO_PROJECT_ID", "").strip() or self.settings.get("project_id")
                return OAuthAuth(self.oauth, client_id, Tokens(access_token="", refresh_token=refresh), self.store, team, project)
        return None

    def from_environment(self) -> bool:
        return bool(os.environ.get("SCENARIO_API_KEY", "").strip() and os.environ.get("SCENARIO_API_SECRET", "").strip())

    def save_api_key(self, key_id: str, secret: str) -> ApiKeyAuth:
        auth = ApiKeyAuth(key_id, secret, source=self.store.name)
        self._forget_oauth()
        previous = self.settings.get("api_key_id")
        if previous and previous != auth.key_id:
            self.store.delete(api_secret_account(previous))
        self.store.set(api_secret_account(auth.key_id), secret.strip())
        self.settings.update(auth_method="api_key", api_key_id=auth.key_id, account_label=mask(auth.key_id))
        return auth

    def client_id(self) -> str:
        """The registered OAuth client of this install, registering it once."""
        client_id = self.settings.get("oauth_client_id")
        if client_id:
            return client_id
        registered = self.oauth.register()
        self.settings.update(oauth_client_id=registered["client_id"], oauth_registered_at=int(time.time()))
        return registered["client_id"]

    def save_oauth(self, client_id: str, tokens: Tokens) -> OAuthAuth:
        if not tokens.refresh_token:
            raise errors.ProtocolError("Sign-in returned no refresh token; the session would end within a day.")
        key_id = self.settings.get("api_key_id")
        if key_id:
            self.store.delete(api_secret_account(key_id))
        self.store.set(ACCOUNT_REFRESH, tokens.refresh_token)
        self.settings.update(auth_method="oauth", oauth_client_id=client_id, api_key_id="", account_label="Scenario account")
        return OAuthAuth(self.oauth, client_id, tokens, self.store, self.settings.get("team_id"), self.settings.get("project_id"))

    def _forget_oauth(self) -> None:
        refresh = self.store.get(ACCOUNT_REFRESH)
        client_id = self.settings.get("oauth_client_id")
        if refresh and client_id:
            self.oauth.revoke(client_id, refresh)
        self.store.delete(ACCOUNT_REFRESH)

    def sign_out(self) -> None:
        """Revokes the refresh token, deletes stored secrets, keeps the client registration."""
        self._forget_oauth()
        key_id = self.settings.get("api_key_id")
        if key_id:
            self.store.delete(api_secret_account(key_id))
        self.settings.update(auth_method="", api_key_id="", account_label="", team_id="", team_name="", project_id="", project_name="")
