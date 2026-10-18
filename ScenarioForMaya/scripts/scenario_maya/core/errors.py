"""Error kinds shared by the client, the UI and the agent server.

Every error renders as one line, ``Kind: message``, with no secrets and no
local paths, so it can be shown in the panel, logged and returned to an agent
as is. ``retryable`` says whether a read may be sent again; paid calls are never
retried whatever this says (see ``core.session``).
"""

from __future__ import annotations


class ScenarioError(Exception):
    """Base class. ``kind`` is the stable name agents and tests match on."""

    kind = "ScenarioError"
    retryable = False

    def __init__(self, message: str, *, hint: str = "", status: int = 0, retry_after: float = 0.0):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.status = status
        self.retry_after = retry_after

    def __str__(self) -> str:
        return f"{self.kind}: {self.message}"

    def to_dict(self) -> dict:
        out = {"error": self.kind, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        if self.status:
            out["status"] = self.status
        return out


class SignInRequired(ScenarioError):
    kind = "SignInRequired"


class AuthFailed(ScenarioError):
    """The credentials were refused (401 after one refresh, or a revoked key)."""

    kind = "AuthFailed"


class Forbidden(ScenarioError):
    """403: the account, key or plan may not use this model or tool."""

    kind = "Forbidden"


class NotFound(ScenarioError):
    kind = "NotFound"


class RateLimited(ScenarioError):
    kind = "RateLimited"
    retryable = True


class ServerError(ScenarioError):
    kind = "ServerError"
    retryable = True


class NetworkError(ScenarioError):
    """The request may not have reached Scenario, or the reply was lost."""

    kind = "NetworkError"
    retryable = True


class Offline(ScenarioError):
    kind = "Offline"


class ProtocolError(ScenarioError):
    """Scenario answered, but not in a shape the plug-in understands."""

    kind = "ProtocolError"


class ToolError(ScenarioError):
    """A Scenario tool ran and reported an error (``isError`` in the reply)."""

    kind = "ToolError"


class Refused(ScenarioError):
    """The plug-in itself refused the action before anything was sent."""

    kind = "Refused"


class QuoteError(Refused):
    """Missing, expired, used or mismatched quote."""

    kind = "QuoteError"


class NotConfirmed(ScenarioError):
    """A paid request was sent and its outcome is unknown. Never resend it."""

    kind = "NotConfirmed"


class Blocked(ScenarioError):
    """Moderation refused the request. Never retried."""

    kind = "Blocked"


class CredentialStoreError(ScenarioError):
    kind = "CredentialStoreError"


def from_http_status(status: int, message: str, *, retry_after: float = 0.0) -> ScenarioError:
    """Maps an HTTP status from Scenario to an error kind."""
    if status == 401:
        return AuthFailed(message or "Scenario refused the credentials.", status=status)
    if status == 403:
        return Forbidden(message or "Not allowed for this account or key.", status=status)
    if status == 404:
        return NotFound(message or "Not found.", status=status)
    if status == 408:
        return NetworkError(message or "Request timed out.", status=status)
    if status == 429:
        return RateLimited(message or "Too many requests.", status=status, retry_after=retry_after)
    if status >= 500:
        return ServerError(message or f"Scenario returned HTTP {status}.", status=status, retry_after=retry_after)
    return ProtocolError(message or f"Unexpected HTTP {status}.", status=status)
