"""HTTPS transport on the standard library.

TLS is verified against the operating system's trust store through the
vendored ``truststore`` (Maya's Python finds no CA bundle on macOS, and studio
proxies that inspect TLS install their root certificate in the OS store);
``certifi`` is the fallback, then Python's default context. Proxies come from
the environment and, on macOS and Windows, from the system settings, as
``urllib`` does by default.

Nothing here retries: callers decide, because a paid call must never be sent
twice.
"""

from __future__ import annotations

import platform
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .. import __version__
from . import errors
from .paths import env_flag

_SSL_CONTEXT: ssl.SSLContext | None = None
_SSL_SOURCE = ""
_HOST_INFO = {"app": "", "os": ""}


def set_host(app: str) -> None:
    """Called by the Maya layer with e.g. ``"Maya 2027.2"``; kept out of core imports."""
    _HOST_INFO["app"] = app


def user_agent() -> str:
    system = {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, "Linux" if sys.platform.startswith("linux") else sys.platform)
    host = _HOST_INFO["app"] or f"Python {platform.python_version()}"
    return f"ScenarioMaya/{__version__} ({host}; {system})"


def ssl_context() -> ssl.SSLContext:
    global _SSL_CONTEXT, _SSL_SOURCE
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT
    try:
        from .._vendor import truststore

        _SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        _SSL_SOURCE = "os-trust-store"
    except Exception:  # noqa: BLE001 - any failure falls back to a bundle
        try:
            import certifi

            _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
            _SSL_SOURCE = "certifi"
        except Exception:  # noqa: BLE001
            _SSL_CONTEXT = ssl.create_default_context()
            _SSL_SOURCE = "python-default"
    return _SSL_CONTEXT


def ssl_source() -> str:
    ssl_context()
    return _SSL_SOURCE


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


class Transport:
    """Sends one request and returns the response, whatever its status.

    Raises ``NetworkError`` only when no HTTP status came back (DNS, TLS,
    connection reset, timeout), and ``Offline`` when offline mode is on.
    """

    def send(self, method: str, url: str, headers: dict | None = None, body: bytes | None = None, timeout: float = 60.0) -> Response:
        raise NotImplementedError


class UrllibTransport(Transport):
    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context()))

    def send(self, method: str, url: str, headers: dict | None = None, body: bytes | None = None, timeout: float = 60.0) -> Response:
        if env_flag("SCENARIO_MAYA_OFFLINE"):
            raise errors.Offline("Offline mode is on (SCENARIO_MAYA_OFFLINE).")
        all_headers = {"User-Agent": user_agent()}
        all_headers.update(headers or {})
        request = urllib.request.Request(url, data=body, headers=all_headers, method=method)
        try:
            with self._opener.open(request, timeout=timeout) as reply:
                return Response(reply.status, {k.lower(): v for k, v in reply.headers.items()}, reply.read())
        except urllib.error.HTTPError as error:
            try:
                data = error.read()
            except Exception:  # noqa: BLE001
                data = b""
            return Response(error.code, {k.lower(): v for k, v in (error.headers or {}).items()}, data)
        except urllib.error.URLError as error:
            reason = error.reason
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise errors.NetworkError(
                    "The TLS certificate of Scenario could not be verified.",
                    hint="A proxy may be inspecting TLS; its root certificate must be in the system trust store.",
                ) from error
            raise errors.NetworkError(f"Could not reach Scenario ({_reason_text(reason)}).") from error
        except (TimeoutError, socket.timeout) as error:
            raise errors.NetworkError("No answer from Scenario before the time limit.") from error
        except (ConnectionError, ssl.SSLError, OSError) as error:
            raise errors.NetworkError(f"Connection to Scenario failed ({type(error).__name__}).") from error


def _reason_text(reason: object) -> str:
    if isinstance(reason, socket.gaierror):
        return "name lookup failed"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timed out"
    if isinstance(reason, ConnectionRefusedError):
        return "connection refused"
    return type(reason).__name__ if not isinstance(reason, str) else reason[:80]


def is_secure_url(url: str) -> bool:
    """HTTPS, or plain HTTP to this machine (local test servers and the OAuth loopback)."""
    if url.startswith("https://"):
        return True
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")


def retry_after_seconds(response: Response, default: float = 0.0, cap: float = 300.0) -> float:
    value = response.header("retry-after")
    try:
        return min(float(value), cap) if value else default
    except ValueError:
        return default
