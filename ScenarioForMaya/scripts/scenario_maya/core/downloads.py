"""Result downloads with receipts (spec 7.4).

- Every attempt asks Scenario for a fresh signed link; links are never stored
  (they carry a signature, and Scenario's expire at the end of the month).
- Bytes go to ``<file>.part``. A later attempt resumes with an HTTP range
  request; a server that ignores the range restarts the file from zero.
- The finished file gets a SHA-256 receipt and is renamed atomically. Nothing
  is ever overwritten (``naming.unique_path``).
- Links and redirects are followed only over HTTPS to Scenario's delivery
  hosts (plain HTTP only to this machine, for tests).

Runs on a worker thread; ``progress(received, total)`` is called from it.
"""

from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime

from . import errors
from .http import is_secure_url, ssl_context, user_agent
from .jsonutil import file_sha256
from .paths import env_flag

# Scenario serves results from its CDN; signed links can redirect to cloud storage.
DELIVERY_HOSTS = ("scenario.com", "amazonaws.com", "cloudfront.net")
CHUNK = 256 * 1024
ATTEMPTS = 3


class Cancelled(errors.ScenarioError):
    """The person or agent stopped the download; the ``.part`` file stays for a resume."""


def allowed_url(url: str) -> bool:
    if not is_secure_url(url):
        return False
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http":
        return True  # is_secure_url allows plain HTTP to this machine only
    return any(host == suffix or host.endswith("." + suffix) for suffix in DELIVERY_HOSTS)


def host_of(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "?").lower()


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise errors.ProtocolError(f"The download link redirected to an unexpected host ({host_of(newurl)}).")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context()), _CheckedRedirects())


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_once(url: str, part: str, progress, cancel, timeout: float) -> str:
    """Appends to ``part`` from its current size. Returns the response's content type."""
    if env_flag("SCENARIO_MAYA_OFFLINE"):
        raise errors.Offline("Offline mode is on (SCENARIO_MAYA_OFFLINE).")
    have = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"User-Agent": user_agent()}
    if have:
        headers["Range"] = f"bytes={have}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        reply = _opener().open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        if error.code == 416 and have:
            return ""  # the part file already holds every byte
        if error.code in (401, 403):
            raise errors.AuthFailed(f"The download link was refused ({error.code}); a fresh one is needed.", status=error.code) from error
        if error.code == 404:
            raise errors.NotFound("The result file is not on Scenario's servers (404).", status=404) from error
        raise errors.from_http_status(error.code, f"The download failed ({error.code}).") from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, errors.ScenarioError):
            raise error.reason from error
        raise errors.NetworkError(f"The download could not reach the file host ({type(error.reason).__name__}).") from error
    except errors.ScenarioError:
        raise
    except (TimeoutError, ConnectionError, OSError) as error:
        raise errors.NetworkError(f"The download connection failed ({type(error).__name__}).") from error
    with reply:
        status = reply.status
        content_type = reply.headers.get("Content-Type", "")
        mode = "ab"
        if have and status == 200:
            have, mode = 0, "wb"  # the range was ignored: start over
        length = reply.headers.get("Content-Length")
        total = have + int(length) if length and length.isdigit() else 0
        received = have
        with open(part, mode) as handle:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled("Download stopped.")
                try:
                    block = reply.read(CHUNK)
                except (TimeoutError, ConnectionError, OSError) as error:
                    raise errors.NetworkError(f"The download stopped at {received:,} bytes ({type(error).__name__}).") from error
                if not block:
                    break
                handle.write(block)
                received += len(block)
                if progress is not None:
                    progress(received, total)
        if total and received < total:
            raise errors.NetworkError(f"The download stopped at {received:,} of {total:,} bytes.")
    return content_type


def download(
    get_link: Callable[[], dict],
    path: str,
    *,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
    attempts: int = ATTEMPTS,
    timeout: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Downloads to ``path`` (which must not exist) and returns its receipt.

    ``get_link()`` returns ``{"url", "mime_type"}`` and is called once per
    attempt, so each attempt has a fresh signed link.
    """
    if os.path.exists(path):
        raise errors.Refused(f"{os.path.basename(path)} already exists; downloads never overwrite.")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = path + ".part"
    last: errors.ScenarioError | None = None
    mime = ""
    for attempt in range(1, attempts + 1):
        link = get_link()
        url = link.get("url") or ""
        mime = link.get("mime_type") or mime
        if not allowed_url(url):
            raise errors.ProtocolError(f"Scenario returned a download link to an unexpected host ({host_of(url)}).")
        try:
            content_type = _fetch_once(url, part, progress, cancel, timeout)
            mime = mime or content_type.split(";", 1)[0].strip()
            break
        except Cancelled:
            raise
        except errors.ScenarioError as error:
            last = error
            if not (error.retryable or isinstance(error, errors.AuthFailed)) or attempt == attempts:
                raise
            sleep(min(2 ** (attempt - 1), 8))
    else:  # pragma: no cover - the loop either breaks or raises
        raise last or errors.NetworkError("The download failed.")
    if not os.path.exists(part) or os.path.getsize(part) == 0:
        raise errors.ProtocolError("The downloaded file is empty.")
    os.replace(part, path)
    return receipt_for(path, mime)


def receipt_for(path: str, mime_type: str = "") -> dict:
    return {
        "file": os.path.basename(path),
        "path": path,
        "size": os.path.getsize(path),
        "sha256": file_sha256(path),
        "mime_type": mime_type,
        "received_utc": _now(),
    }


def verify(receipt: dict) -> bool:
    """True when the file is still there with the same bytes (rehash, never download again)."""
    path = receipt.get("path") or ""
    try:
        return os.path.getsize(path) == receipt.get("size") and file_sha256(path) == receipt.get("sha256")
    except OSError:
        return False
