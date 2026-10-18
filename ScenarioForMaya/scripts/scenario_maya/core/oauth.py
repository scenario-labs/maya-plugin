"""Sign in with Scenario: OAuth 2.0 authorization code with PKCE, loopback redirect,
and the device code grant for machines whose browser cannot reach 127.0.0.1.

Flow (browser):
1. Discover the authorization server from the hosted Scenario MCP.
2. Register this install once (dynamic client registration, public client,
   three fixed loopback redirect URIs), cached in settings by client id.
3. Open the browser on the authorize URL with ``state``, PKCE S256 and
   ``resource``; a one-shot listener on 127.0.0.1 receives the code.
4. Exchange the code; keep the access token in memory and the refresh token
   in the OS credential store.

Every function here blocks: the Maya layer runs them on worker threads.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from . import errors
from .http import Response, Transport, UrllibTransport, is_secure_url

METADATA_URL = "https://mcp.scenario.com/.well-known/oauth-authorization-server"
RESOURCE = "https://mcp.scenario.com/mcp"
SCOPE = "profile email offline_access"
CLIENT_NAME = "Scenario for Maya"
REDIRECT_PORTS = (38927, 38928, 38929)
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


@dataclass
class Metadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str = ""
    revocation_endpoint: str = ""
    device_authorization_endpoint: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Metadata":
        fields = ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint", "device_authorization_endpoint")
        for name in fields:
            url = data.get(name) or ""
            if url and not is_secure_url(url):
                raise errors.ProtocolError(f"Sign-in endpoint is not HTTPS: {name}.")
        if not data.get("authorization_endpoint") or not data.get("token_endpoint"):
            raise errors.ProtocolError("Scenario's sign-in metadata is incomplete.")
        return cls(issuer=data.get("issuer", ""), **{name: data.get(name) or "" for name in fields})


@dataclass
class Tokens:
    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    scope: str = ""
    extra: dict = field(default_factory=dict)

    def expires_in(self, now: float | None = None) -> float:
        if not self.expires_at:
            return float("inf")
        return self.expires_at - (now if now is not None else time.time())


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    interval: float
    expires_at: float


def pkce_pair() -> tuple:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def redirect_uri(port: int) -> str:
    return f"http://127.0.0.1:{port}/callback"


class OAuthClient:
    def __init__(self, transport: Transport | None = None, metadata_url: str = METADATA_URL, resource: str = RESOURCE, scope: str = SCOPE):
        self.transport = transport or UrllibTransport()
        self.metadata_url = metadata_url
        self.resource = resource
        self.scope = scope
        self._metadata: Metadata | None = None

    # -- plumbing --------------------------------------------------------

    def _json(self, response: Response) -> dict:
        try:
            data = json.loads(response.text() or "{}")
        except ValueError as error:
            raise errors.ProtocolError("Sign-in service sent a reply that is not JSON.") from error
        return data if isinstance(data, dict) else {}

    def _post_form(self, url: str, fields: dict, timeout: float = 30.0) -> tuple:
        body = urllib.parse.urlencode({k: v for k, v in fields.items() if v}).encode("ascii")
        response = self.transport.send("POST", url, {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, body, timeout)
        return response.status, self._json(response) if response.body else {}

    def metadata(self) -> Metadata:
        if self._metadata is None:
            response = self.transport.send("GET", self.metadata_url, {"Accept": "application/json"}, None, 20.0)
            if response.status != 200:
                raise errors.from_http_status(response.status, "Could not read Scenario's sign-in settings.")
            self._metadata = Metadata.from_dict(self._json(response))
        return self._metadata

    # -- registration ----------------------------------------------------

    def register(self) -> dict:
        meta = self.metadata()
        if not meta.registration_endpoint:
            raise errors.ProtocolError("Scenario does not offer client registration; use an API key.")
        body = {
            "client_name": CLIENT_NAME,
            "redirect_uris": [redirect_uri(port) for port in REDIRECT_PORTS],
            "grant_types": ["authorization_code", "refresh_token", DEVICE_GRANT],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "application_type": "native",
            "scope": self.scope,
        }
        response = self.transport.send(
            "POST", meta.registration_endpoint, {"Content-Type": "application/json", "Accept": "application/json"}, json.dumps(body).encode(), 30.0
        )
        data = self._json(response)
        if response.status not in (200, 201) or not data.get("client_id"):
            raise errors.ProtocolError(f"Client registration failed (HTTP {response.status}): {_oauth_error(data)}")
        return {"client_id": data["client_id"], "redirect_uris": data.get("redirect_uris") or body["redirect_uris"]}

    # -- browser flow ----------------------------------------------------

    def authorize_url(self, client_id: str, redirect: str, state: str, challenge: str) -> str:
        query = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": self.scope,
            "resource": self.resource,
        }
        return self.metadata().authorization_endpoint + "?" + urllib.parse.urlencode(query)

    def exchange_code(self, client_id: str, code: str, redirect: str, verifier: str) -> Tokens:
        status, data = self._post_form(
            self.metadata().token_endpoint,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": self.resource,
            },
        )
        return _tokens(status, data, "Sign-in")

    def sign_in_browser(
        self,
        client_id: str,
        open_browser: Callable[[str], object],
        timeout: float = 300.0,
        cancel: threading.Event | None = None,
    ) -> Tokens:
        """Runs the loopback flow. Blocks until the code arrives, times out or is cancelled."""
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(24)
        receiver = LoopbackReceiver(state)
        port = receiver.start()
        try:
            redirect = redirect_uri(port)
            open_browser(self.authorize_url(client_id, redirect, state, challenge))
            code = receiver.wait(timeout, cancel)
        finally:
            receiver.stop()
        return self.exchange_code(client_id, code, redirect, verifier)

    # -- device flow -----------------------------------------------------

    def start_device(self, client_id: str) -> DeviceCode:
        meta = self.metadata()
        if not meta.device_authorization_endpoint:
            raise errors.ProtocolError("Scenario does not offer sign-in on another device; use an API key.")
        status, data = self._post_form(meta.device_authorization_endpoint, {"client_id": client_id, "scope": self.scope, "resource": self.resource})
        if status != 200 or not data.get("device_code") or not data.get("user_code"):
            raise errors.ProtocolError(f"Device sign-in could not start (HTTP {status}): {_oauth_error(data)}")
        uri = data.get("verification_uri") or ""
        if not uri.startswith("https://"):
            raise errors.ProtocolError("Device sign-in sent a verification link that is not HTTPS.")
        return DeviceCode(
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=uri,
            verification_uri_complete=data.get("verification_uri_complete") or "",
            interval=float(data.get("interval") or 5),
            expires_at=time.time() + float(data.get("expires_in") or 600),
        )

    def poll_device(self, client_id: str, device: DeviceCode, cancel: threading.Event | None = None, sleep: Callable[[float], None] = time.sleep) -> Tokens:
        interval = max(device.interval, 1.0)
        while time.time() < device.expires_at:
            if cancel is not None and cancel.is_set():
                raise errors.Refused("Sign-in cancelled.")
            sleep(interval)
            status, data = self._post_form(self.metadata().token_endpoint, {"grant_type": DEVICE_GRANT, "device_code": device.device_code, "client_id": client_id})
            code = data.get("error", "")
            if status == 200 and data.get("access_token"):
                return _tokens(status, data, "Device sign-in")
            if code == "authorization_pending":
                continue
            if code == "slow_down":
                interval += 5
                continue
            if code == "access_denied":
                raise errors.Refused("Sign-in was declined in the browser.")
            if code == "expired_token":
                break
            raise errors.AuthFailed(f"Device sign-in failed: {_oauth_error(data)}", status=status)
        raise errors.AuthFailed("The sign-in code expired. Start again.")

    # -- refresh and revoke ----------------------------------------------

    def refresh(self, client_id: str, refresh_token: str) -> Tokens:
        status, data = self._post_form(
            self.metadata().token_endpoint,
            {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id, "resource": self.resource},
        )
        tokens = _tokens(status, data, "Session refresh")
        if not tokens.refresh_token:
            tokens.refresh_token = refresh_token
        return tokens

    def revoke(self, client_id: str, token: str, hint: str = "refresh_token") -> bool:
        endpoint = self.metadata().revocation_endpoint
        if not endpoint or not token:
            return False
        try:
            status, _ = self._post_form(endpoint, {"token": token, "token_type_hint": hint, "client_id": client_id})
        except errors.ScenarioError:
            return False
        return status in (200, 204)


def _oauth_error(data: dict) -> str:
    if not isinstance(data, dict):
        return "unknown error"
    return str(data.get("error_description") or data.get("error") or data.get("message") or "unknown error")[:200]


def _tokens(status: int, data: dict, what: str) -> Tokens:
    if status != 200 or not data.get("access_token"):
        if status in (400, 401) and data.get("error") in ("invalid_grant", "invalid_client", "unauthorized_client"):
            raise errors.AuthFailed(f"{what} was refused: {_oauth_error(data)}", hint="Sign in again.", status=status)
        raise errors.ProtocolError(f"{what} failed (HTTP {status}): {_oauth_error(data)}", status=status)
    expires_in = data.get("expires_in")
    try:
        expires_at = time.time() + float(expires_in) if expires_in else 0.0
    except (TypeError, ValueError):
        expires_at = 0.0
    return Tokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token") or "",
        expires_at=expires_at,
        scope=data.get("scope") or "",
        extra={k: v for k, v in data.items() if k in ("token_type", "id_token_present")},
    )


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scenario for Maya</title><style>body{{font:16px -apple-system,Segoe UI,sans-serif;background:#0b0b0c;color:#f2f2f2;display:grid;place-items:center;height:100vh;margin:0}}
main{{max-width:28rem;padding:2rem;text-align:center}}h1{{font-size:1.25rem;margin:0 0 .5rem}}p{{color:#b8b8bc;margin:0}}</style></head>
<body><main><h1>{title}</h1><p>{body}</p></main></body></html>"""


class LoopbackReceiver:
    """One-shot HTTP listener on 127.0.0.1 for the OAuth redirect."""

    def __init__(self, state: str, ports: tuple = REDIRECT_PORTS):
        self.state = state
        self.ports = ports
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._done = threading.Event()
        self._code = ""
        self._error = ""

    def start(self) -> int:
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # never log query strings (they carry the code)
                return

            def do_GET(self):  # noqa: N802 - http.server API
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_error(404)
                    return
                query = urllib.parse.parse_qs(parsed.query)
                state = (query.get("state") or [""])[0]
                if not secrets.compare_digest(state, receiver.state):
                    self._reply(400, "Sign-in not completed", "This page did not come from the sign-in Maya started. Start again from Maya.")
                    return
                if query.get("error"):
                    receiver._error = (query.get("error_description") or query.get("error"))[0][:200]
                    self._reply(200, "Sign-in not completed", "Scenario reported: " + receiver._error)
                else:
                    receiver._code = (query.get("code") or [""])[0]
                    self._reply(200, "Signed in to Scenario", "You can close this tab and go back to Maya.")
                receiver._done.set()

            def _reply(self, status, title, body):
                data = _PAGE.format(title=html.escape(title), body=html.escape(body)).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

        last_error: OSError | None = None
        for port in self.ports:
            try:
                self._server = HTTPServer(("127.0.0.1", port), Handler)
                break
            except OSError as error:
                last_error = error
        if self._server is None:
            raise errors.Refused(
                "The local sign-in ports are busy.", hint='Use "Sign in on another device" or an API key.'
            ) from last_error
        self._server.timeout = 0.5
        self._thread = threading.Thread(target=self._serve, name="scenario-oauth-callback", daemon=True)
        self._thread.start()
        return self._server.server_address[1]

    def _serve(self) -> None:
        server = self._server
        while server is not None and not self._done.is_set():
            try:
                server.handle_request()
            except (OSError, ValueError):
                break

    def wait(self, timeout: float, cancel: threading.Event | None = None) -> str:
        deadline = time.time() + timeout
        while not self._done.wait(0.2):
            if cancel is not None and cancel.is_set():
                raise errors.Refused("Sign-in cancelled.")
            if time.time() > deadline:
                raise errors.AuthFailed("Sign-in timed out.", hint='Start again, or use "Sign in on another device".')
        if self._error:
            raise errors.AuthFailed(f"Sign-in was not completed: {self._error}")
        if not self._code:
            raise errors.ProtocolError("The sign-in page returned no code.")
        return self._code

    def stop(self) -> None:
        self._done.set()
        server, self._server = self._server, None
        if server is not None:
            server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
