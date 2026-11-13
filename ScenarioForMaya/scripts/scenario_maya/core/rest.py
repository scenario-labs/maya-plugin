"""Calls to Scenario's REST API (``https://api.cloud.scenario.com/v1``) through its Python SDK.

Each call is one SDK method with ``with_raw_response``, so replies are read as
the API's JSON. The SDK's HTTP client is built here: TLS against the OS trust
store (``core.http``), the system proxy settings, and no redirects, so
credentials go to the API base only. An OAuth session names its team and
project on each request (``teamId`` and ``projectId`` in the query); an API
key is already scoped to its project.

Retry rules, which carry the money contract:

- Reads: the SDK retries up to twice on connection errors, 408, 409, 429 and 5xx.
- Paid calls (``paid=True``) are sent once (``max_retries=0``). A credential
  refusal is renewed and resent once: the API's gateway refuses an expired or
  unknown token with 403 and ``x-amzn-errortype: AccessDeniedException`` (401
  for a missing one) before any handler runs, so nothing was started. A 429 or
  any other 4xx is a refusal, reported as not sent and never retried. Any
  failure where Scenario may have started the work (no reply, timeout, 408,
  5xx, a success without a job) raises ``NotConfirmed``; the session layer then
  blocks an identical request until a person reviews it.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from . import errors, sdk
from .http import Response, retry_after_seconds, ssl_context, user_agent
from .paths import env_flag

DEFAULT_API_URL = "https://api.cloud.scenario.com/v1"

_MODERATION = re.compile(r"moderation|flagged|nsfw|content policy|safety", re.IGNORECASE)


class Auth(Protocol):
    kind: str

    def authorization(self) -> str:
        """The ``Authorization`` header value."""

    def refresh(self) -> bool:
        """Renews the credentials; False when they cannot be renewed."""

    def workspace_args(self) -> dict:
        """``teamId`` and ``projectId`` for a user session, ``{}`` for a key."""


@dataclass
class Reply:
    status: int
    data: dict


def error_body(response: Response) -> dict:
    """``{reason, name, details}`` as the API sends them; ``{}`` for anything else."""
    try:
        data = json.loads(response.text() or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def error_message(body: dict, response: Response) -> str:
    text = body.get("reason") or body.get("message") or body.get("error")
    if isinstance(text, str) and text.strip():
        return text.strip()[:400]
    return "" if body else response.text().strip()[:200]


def gateway_refusal(response: Response) -> bool:
    """The gateway refused the credentials before any handler ran."""
    if response.status == 401:
        return True
    return response.status == 403 and response.header("x-amzn-errortype").startswith("AccessDeniedException")


def system_proxy(url: str) -> str:
    """The proxy the system settings (or the environment) name for ``url``, or ``""``."""
    host = urllib.parse.urlparse(url).hostname or ""
    proxy = urllib.request.getproxies().get(urllib.parse.urlparse(url).scheme, "")
    if not proxy or host in ("127.0.0.1", "localhost", "::1") or urllib.request.proxy_bypass(host):
        return ""
    return proxy


class RestClient:
    def __init__(self, auth: Auth, base_url: str = DEFAULT_API_URL, http_client: Any = None) -> None:
        self.auth = auth
        self.base_url = base_url.rstrip("/")
        self._http = http_client
        self._sdk: Any = None
        self._lock = threading.Lock()

    def _base(self):
        with self._lock:
            if self._sdk is None:
                module = sdk.load()
                import httpx  # loaded with the SDK

                http = self._http or httpx.Client(verify=ssl_context(), proxy=system_proxy(self.base_url) or None, follow_redirects=False, trust_env=False, timeout=60.0)
                self._sdk = module.Scenario(base_url=self.base_url, http_client=http, max_retries=2, default_headers={"User-Agent": user_agent()})
            return self._sdk

    def call(self, op: Callable, *, workspace: str = "project", paid: bool = False, timeout: float = 60.0, name: str = "") -> Reply:
        """Runs ``op(client, query)``, an SDK method with ``with_raw_response``, and returns its JSON.

        ``workspace`` names what the OAuth session adds to the query:
        ``project`` (team and project), ``team`` (the team only) or ``none``.
        """
        if env_flag("SCENARIO_MAYA_OFFLINE"):
            raise errors.Offline("Offline mode is on (SCENARIO_MAYA_OFFLINE).")
        query: dict = {}
        if workspace != "none":
            names = self.auth.workspace_args()
            if names.get("teamId"):
                query["teamId"] = names["teamId"]
            if workspace == "project" and names.get("projectId"):
                query["projectId"] = names["projectId"]
        module = sdk.load()
        base = self._base()
        name = name or "Scenario request"
        renewed = False
        while True:
            client = base.with_options(default_headers={"Authorization": self.auth.authorization()}, max_retries=0 if paid else 2, timeout=timeout)
            try:
                raw = op(client, query)
            except module.APIStatusError as failure:
                response = _response(failure.response)
                if gateway_refusal(response) and not renewed and self.auth.refresh():
                    renewed = True
                    continue
                raise _classify(response, paid, name) from None
            except module.APIConnectionError as failure:
                if paid:
                    raise errors.NotConfirmed(f"{name}: the request was sent but no answer came back ({type(failure).__name__}).") from None
                kind = "timed out" if isinstance(failure, module.APITimeoutError) else "connection failed"
                raise errors.NetworkError(f"Could not reach Scenario ({kind}).") from None
            return Reply(raw.status_code, _json_object(raw.text()))


def _response(http_response) -> Response:
    return Response(http_response.status_code, {k.lower(): v for k, v in http_response.headers.items()}, http_response.content)


def _json_object(text: str) -> dict:
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as error:
        raise errors.ProtocolError("Scenario's reply was not JSON.") from error
    if not isinstance(data, dict):
        raise errors.ProtocolError("Scenario's reply was not a JSON object.")
    return data


def _classify(response: Response, paid: bool, name: str) -> errors.ScenarioError:
    status = response.status
    body = error_body(response)
    message = error_message(body, response)
    if gateway_refusal(response):
        if status == 401 or message in ("", "Forbidden", "Unauthorized"):
            return errors.AuthFailed("Scenario refused the credentials.", hint="Sign in again or check the API key.", status=status)
        return errors.Forbidden(message, status=status)
    if paid and (status == 408 or status >= 500):
        return errors.NotConfirmed(f"{name}: Scenario answered HTTP {status}; the outcome is unknown.")
    if _MODERATION.search(message):
        return errors.Blocked(message, status=status)
    if status == 429:
        if body.get("name") == "PlanLimitReachedError":
            return errors.RateLimited(message or "The plan's limit is reached.", hint="Upgrade the plan or wait for the limit to reset.", status=429)
        return errors.RateLimited("Not sent: Scenario asked to slow down. Try again.", status=429, retry_after=retry_after_seconds(response))
    if status in (403, 404, 408) or status >= 500:
        return errors.from_http_status(status, message, retry_after=retry_after_seconds(response))
    if status >= 400:  # 408, 429 and 5xx are handled above
        details = body.get("details") if isinstance(body.get("details"), dict) else {}
        if details.get("reason") == "task-id-required":
            return errors.ToolError(message or "This project requires a task id.", hint="Paid requests from Maya cannot name a task yet; use a project that does not require one.", status=status)
        return errors.ToolError(message or f"Scenario refused the request (HTTP {status}).", status=status)
    return errors.ProtocolError(f"Unexpected HTTP {status} from Scenario.", status=status)
