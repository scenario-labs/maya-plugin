"""JSON-RPC client for the hosted Scenario MCP (``https://mcp.scenario.com/mcp``).

The hosted server speaks MCP over streamable HTTP: one POST per JSON-RPC
message, replies in JSON or as a short event stream that may carry progress
notifications before the result. It is stateless today (no session id), but
the client keeps and renews a session id if one is issued.

Retry rules, which carry the money contract:

- Reads are retried up to twice on network errors, 408, 429 and 5xx.
- Paid calls (``paid=True``) are sent once. A 401 is refreshed and resent once,
  and an expired session (404 with a session id) is renewed and resent once:
  both mean the request was refused before it reached the tool. Any other
  failure where Scenario may have started the work (no reply, timeout, 408,
  429, 5xx, an unknown JSON-RPC error, a tool error whose text is not a known
  refusal) raises ``NotConfirmed``. The session layer then blocks an identical
  request until a person reviews it.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .. import __version__
from . import errors
from .http import Response, Transport, UrllibTransport, retry_after_seconds
from .jsonutil import drop_nulls

DEFAULT_ENDPOINT = "https://mcp.scenario.com/mcp?toolsets=full"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

# Tool error texts that mean "refused before any work started". A paid call
# whose error matches none of these is treated as Not confirmed.
_DEFINITE_REFUSAL = re.compile(
    r"insufficient|not enough (creative units|credits)|quota|limit reached|exceed|forbidden|not allowed|"
    r"permission|unauthori[sz]ed|invalid|required|missing|must be|validation|unsupported|not supported|"
    r"not found|unknown model|does not exist|too (long|large|small|many)|blocked|moderation|flagged|nsfw",
    re.IGNORECASE,
)
_MODERATION = re.compile(r"moderation|flagged|nsfw|content policy|safety", re.IGNORECASE)
_JOB_ID = re.compile(r"\bjob_[A-Za-z0-9]{8,}\b")


class Auth(Protocol):
    kind: str

    def authorization(self) -> str: ...

    def refresh(self) -> bool: ...

    def workspace_args(self) -> dict: ...


@dataclass
class ToolResult:
    data: dict = field(default_factory=dict)
    text: str = ""
    trace_id: str = ""
    raw: dict = field(default_factory=dict)


def parse_event_stream(body: str) -> list:
    """Parses a ``text/event-stream`` body into JSON messages (``data:`` lines)."""
    messages, lines = [], []
    for line in body.replace("\r\n", "\n").split("\n") + [""]:
        if not line:
            if lines:
                try:
                    messages.append(json.loads("\n".join(lines)))
                except ValueError:
                    pass
                lines = []
        elif line.startswith("data:"):
            lines.append(line[6:] if line[5:6] == " " else line[5:])
    return messages


def parse_messages(response: Response) -> list:
    text = response.text()
    content_type = response.header("content-type")
    if "text/event-stream" in content_type or text.lstrip().startswith(("data:", "event:", "id:")):
        return parse_event_stream(text)
    if not text.strip():
        return []
    try:
        parsed = json.loads(text)
    except ValueError as error:
        raise errors.ProtocolError("Scenario's reply was not JSON.") from error
    return parsed if isinstance(parsed, list) else [parsed]


def tool_payload(result: dict) -> ToolResult:
    """Structured content first, then the first JSON text block, then plain text."""
    texts = [item.get("text") or "" for item in result.get("content") or [] if isinstance(item, dict) and item.get("type") == "text"]
    text = texts[0] if texts else ""
    meta = result.get("_meta") or {}
    trace = meta.get("scenario.com/trace_id", "") if isinstance(meta, dict) else ""
    data = result.get("structuredContent")
    if not isinstance(data, dict):
        data = {}
        if text:
            try:
                parsed = json.loads(text)
                data = parsed if isinstance(parsed, dict) else {"items": parsed}
            except ValueError:
                data = {}
    return ToolResult(data=data, text="\n".join(t for t in texts if t), trace_id=trace, raw=result)


_API_ERROR = re.compile(r"Error:\s*(\d{3})\b\s*(.*)", re.DOTALL)


def tool_error_detail(payload: ToolResult) -> tuple:
    """Reads Scenario's tool error: ``(message, api_status)``.

    The hosted server sends a generic first line with a trace id, then
    ``Error: <HTTP status of the Scenario API> <JSON body>``.
    """
    status = 0
    message = ""
    for line in payload.text.split("\n"):
        match = _API_ERROR.search(line)
        if match:
            status = int(match.group(1))
            body = match.group(2).strip()
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                message = str(parsed.get("reason") or parsed.get("message") or parsed.get("error") or body)
            else:
                message = body
            break
    if not message:
        lines = [line for line in payload.text.split("\n") if line.strip() and "Scenario error (trace_id" not in line]
        message = lines[0] if lines else payload.text.strip()
    if payload.trace_id:
        message = f"{message} (trace {payload.trace_id})" if message else f"Scenario error (trace {payload.trace_id})"
    return (message or "The tool reported an error.")[:400], status


class McpClient:
    def __init__(
        self,
        auth: Auth,
        endpoint: str = DEFAULT_ENDPOINT,
        transport: Transport | None = None,
        client_name: str = "scenario-maya",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.auth = auth
        self.endpoint = endpoint
        self.transport = transport or UrllibTransport()
        self.client_name = client_name
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_id = 1
        self._session = ""
        self._protocol = ""
        self.server_info: dict = {}
        self.instructions = ""

    # -- low level -------------------------------------------------------

    def _new_id(self) -> int:
        with self._lock:
            value = self._next_id
            self._next_id += 1
            return value

    def _headers(self) -> dict:
        headers = {
            "Authorization": self.auth.authorization(),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        with self._lock:
            if self._protocol:
                headers["MCP-Protocol-Version"] = self._protocol
            if self._session:
                headers["Mcp-Session-Id"] = self._session
        return headers

    def _post(self, payload: dict, timeout: float) -> Response:
        response = self.transport.send("POST", self.endpoint, self._headers(), json.dumps(payload).encode("utf-8"), timeout)
        session = response.header("mcp-session-id")
        if session:
            with self._lock:
                self._session = session
        return response

    def _had_session(self) -> bool:
        with self._lock:
            return bool(self._session)

    def initialize(self, timeout: float = 30.0) -> dict:
        with self._lock:
            self._session = ""
            self._protocol = ""
        payload = {
            "jsonrpc": "2.0",
            "id": self._new_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSIONS[0],
                "capabilities": {},
                "clientInfo": {"name": self.client_name, "version": __version__},
            },
        }
        response = self._post(payload, timeout)
        if response.status == 401 and self.auth.refresh():
            response = self._post(payload, timeout)
        if response.status >= 300:
            raise errors.from_http_status(response.status, _error_text(response), retry_after=retry_after_seconds(response))
        result = _find_reply(parse_messages(response), payload["id"])
        if "error" in result:
            raise errors.ProtocolError(f"initialize refused: {_rpc_error_text(result['error'])}")
        info = result.get("result") or {}
        version = info.get("protocolVersion") or PROTOCOL_VERSIONS[0]
        with self._lock:
            self._protocol = version if version in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        self.server_info = info.get("serverInfo") or {}
        self.instructions = info.get("instructions") or ""
        try:
            self.transport.send("POST", self.endpoint, self._headers(), json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(), timeout)
        except errors.ScenarioError:
            pass
        return info

    def _ensure_initialized(self) -> None:
        with self._lock:
            ready = bool(self._protocol)
        if not ready:
            self.initialize()

    # -- tools -----------------------------------------------------------

    def call_tool(self, name: str, arguments: dict | None = None, *, paid: bool = False, timeout: float = 120.0, workspace: bool = True) -> ToolResult:
        """Calls one hosted tool and returns its payload.

        ``workspace`` adds ``team_id`` and ``project_id`` for OAuth sessions
        (an API key is already scoped to its project).
        """
        args = drop_nulls(dict(arguments or {}))
        if workspace:
            for key, value in self.auth.workspace_args().items():
                args.setdefault(key, value)
        self._ensure_initialized()
        attempts = 1 if paid else 3
        refreshed = renewed = False
        attempt = 0
        while True:
            attempt += 1
            payload = {"jsonrpc": "2.0", "id": self._new_id(), "method": "tools/call", "params": {"name": name, "arguments": args}}
            try:
                response = self._post(payload, timeout)
            except errors.Offline:
                raise
            except errors.NetworkError as error:
                if paid:
                    raise errors.NotConfirmed(f"{name}: the request was sent but no answer came back ({error.message}).") from error
                if attempt < attempts:
                    self._sleep(attempt)
                    continue
                raise
            status = response.status
            if status == 401 and not refreshed:
                refreshed = True
                if self.auth.refresh():
                    continue
                raise errors.AuthFailed("Scenario refused the credentials.", hint="Sign in again or check the API key.", status=401)
            if status == 404 and self._had_session() and not renewed:
                renewed = True
                self.initialize()
                continue
            if status >= 300:
                error = errors.from_http_status(status, _error_text(response), retry_after=retry_after_seconds(response))
                if paid:
                    if status in (408, 429) or status >= 500:
                        raise errors.NotConfirmed(f"{name}: Scenario answered HTTP {status}; the outcome is unknown.") from error
                    raise error
                if error.retryable and attempt < attempts:
                    self._sleep(min(error.retry_after or attempt, 10.0))
                    continue
                raise error
            reply = _find_reply(parse_messages(response), payload["id"])
            if "error" in reply:
                rpc = reply["error"] if isinstance(reply["error"], dict) else {}
                message = _rpc_error_text(rpc)
                if paid and rpc.get("code") not in (-32600, -32601, -32602, -32700):
                    raise errors.NotConfirmed(f"{name}: {message}")
                raise errors.ProtocolError(f"{name}: {message}")
            result = reply.get("result") or {}
            payload_out = tool_payload(result)
            if result.get("isError"):
                message, api_status = tool_error_detail(payload_out)
                if _MODERATION.search(message):
                    raise errors.Blocked(message, status=api_status)
                refused = 400 <= api_status < 500 and api_status not in (408, 429)
                if paid and not refused and (api_status or _JOB_ID.search(message) or not _DEFINITE_REFUSAL.search(message)):
                    raise errors.NotConfirmed(f"{name}: {message}", status=api_status)
                if api_status == 403:
                    raise errors.Forbidden(message, status=api_status)
                if api_status == 404:
                    raise errors.NotFound(message, status=api_status)
                if api_status == 429 or api_status >= 500:
                    error = errors.from_http_status(api_status, message)
                    if not paid and attempt < attempts:
                        self._sleep(attempt)
                        continue
                    raise error
                raise errors.ToolError(message, status=api_status)
            return payload_out

    def list_tools(self) -> list:
        self._ensure_initialized()
        tools, cursor = [], None
        for _ in range(20):
            payload = {"jsonrpc": "2.0", "id": self._new_id(), "method": "tools/list", "params": {"cursor": cursor} if cursor else {}}
            response = self._post(payload, 60.0)
            if response.status >= 300:
                raise errors.from_http_status(response.status, _error_text(response))
            reply = _find_reply(parse_messages(response), payload["id"])
            result = reply.get("result") or {}
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools


def _find_reply(messages: list, request_id: int) -> dict:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("id") == request_id and ("result" in message or "error" in message):
            return message
    raise errors.ProtocolError("Scenario sent no reply to the request.")


def _rpc_error_text(error: Any) -> str:
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "error")[:300]
    return str(error)[:300]


def _error_text(response: Response) -> str:
    text = response.text().strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except ValueError:
        return text[:200]
    if isinstance(data, dict):
        inner = data.get("error")
        if isinstance(inner, dict):
            return str(inner.get("message") or inner)[:200]
        if inner:
            return str(data.get("error_description") or inner)[:200]
        return str(data.get("message") or "")[:200]
    return ""
