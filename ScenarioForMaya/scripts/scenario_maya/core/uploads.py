"""Local files sent to Scenario as model inputs (spec 7.1 point 8, 7.5).

A file is sent only on an explicit action: a person adding it to a form, or
an agent passing a file the plug-in produced. Scenario returns storage links;
each part is PUT to its link exactly as given, with no checksum headers
(Scenario's instructions: extra ``x-amz-checksum-*`` headers make the store
refuse the part). The same bytes added again in the same workspace during
this Maya session reuse the asset id instead of uploading twice.
"""

from __future__ import annotations

import hashlib
import os
import threading

from . import errors, gltf
from .http import Transport, UrllibTransport, is_secure_url
from .session import no_spend

IMAGE_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
MODEL_TYPES = {"glb": "model/gltf-binary", "fbx": "model/x-fbx", "obj": "model/obj"}
_PENDING = ("timeout", "in_progress", "processing", "pending")
_CACHE: dict = {}
_LOCK = threading.Lock()


def image_type(path: str) -> str:
    """``png``, ``jpeg`` or ``webp`` from the file's first bytes, else ""."""
    with open(path, "rb") as handle:
        head = handle.read(12)
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return ""


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def put_parts(path: str, parts: list, part_size: int, transport: Transport, content_type: str = "application/octet-stream", cancel: threading.Event | None = None) -> None:
    """PUTs the file to the links of ``upload_start``, part by part, bodies only."""
    size = os.path.getsize(path)
    part_size = part_size or size
    with open(path, "rb") as handle:
        for part in sorted(parts, key=lambda item: item["number"]):
            if cancel is not None and cancel.is_set():
                raise errors.Refused("The upload was stopped; nothing was sent to a model.")
            if not is_secure_url(part.get("url") or ""):
                raise errors.ProtocolError("Scenario returned an upload link that is not HTTPS.")
            offset = (part["number"] - 1) * part_size
            handle.seek(offset)
            data = handle.read(int(part.get("size") or min(part_size, size - offset)))
            # The type given to upload_start; without one urllib would label the body as a form.
            response = transport.send("PUT", part["url"], headers={"Content-Type": content_type}, body=data, timeout=300.0)
            if not 200 <= response.status < 300:
                raise errors.from_http_status(response.status, f"Scenario's storage refused part {part['number']} of the upload (HTTP {response.status}).")


def upload_file(session, path: str, *, kind: str = "image", transport: Transport | None = None, cancel: threading.Event | None = None) -> dict:
    """Sends one file and returns ``{asset_id, name, path, sha256, size, reused}``. Blocks: call from a worker."""
    if no_spend():
        raise errors.Refused("Spending is off (SCENARIO_NO_SPEND=1): files are not sent to Scenario.")
    name = os.path.basename(path)
    if not os.path.isfile(path):
        raise errors.Refused(f"{name} was not found.")
    content_type = "application/octet-stream"
    if kind == "image":
        found = image_type(path)
        if not found:
            raise errors.Refused(f"{name} is not a PNG, JPEG or WebP image.", hint="Save it as PNG or JPEG and add it again.")
        content_type = IMAGE_TYPES[found]
    elif kind == "3d":
        found = gltf.sniff_format(path)
        if found not in MODEL_TYPES:
            raise errors.Refused(f"{name} is not a GLB, FBX or OBJ file.")
        content_type = MODEL_TYPES[found]
    size = os.path.getsize(path)
    if not size:
        raise errors.Refused(f"{name} is empty.")
    digest = file_sha256(path)
    key = (session.workspace(), kind, digest)
    with _LOCK:
        known = _CACHE.get(key)
    if known:
        return dict(known, name=name, path=path, reused=True)
    backend = session.backend()
    started = backend.upload_start(name, content_type, kind, size)
    put_parts(path, started["parts"], started["part_size"], transport or UrllibTransport(), content_type, cancel)
    done = {}
    for _ in range(3):  # Scenario answers "timeout" while it is still processing a large file
        done = backend.upload_complete(started["upload_id"])
        if done.get("asset_id") or str(done.get("status") or "").lower() not in _PENDING:
            break
    asset_id = str(done.get("asset_id") or "")
    if not asset_id.startswith("asset_"):
        raise errors.ProtocolError(f"Scenario did not confirm the upload of {name} ({done.get('status') or 'no status'}).")
    out = {"asset_id": asset_id, "name": name, "path": path, "sha256": digest, "size": size, "reused": False}
    with _LOCK:
        _CACHE[key] = out
    return out


def forget() -> None:
    """Sign-out and tests: the next add uploads again."""
    with _LOCK:
        _CACHE.clear()
