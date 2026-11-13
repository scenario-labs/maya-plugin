"""A local stand-in for Scenario's REST API, its OAuth server and its file CDN.

Used by the unit tests, the ``mayapy`` tests and the agent tests, so no test
spends Creative Units or needs the network. Model records are derived from
recordings of the hosted MCP's schema reads (``tests/fixtures/mcp``), turned
back into the API's own shape; jobs, assets and uploads follow the API's
documented answers, with placeholder ids.

Faults are queued per operation: ``server.state.fail("generate", kind)`` where
kind is one of ``drop`` (job created, connection closed before the reply),
``http500``, ``http504``, ``expired`` (the gateway refuses the token before any
handler runs: 403 with ``x-amzn-errortype``), ``http429``, ``plan_limit``,
``http400``, ``moderation``, ``no_job`` (a success without a job), ``redirect``.
Operations: ``teams``, ``projects``, ``models``, ``model``, ``generate``,
``job``, ``jobs``, ``asset``, ``download``, ``upload_create``,
``upload_action``, ``upload_read``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(os.path.dirname(HERE), "fixtures", "mcp")

API_KEY = "api_testkey000000000001"
API_SECRET = "test-secret-not-real"  # not a secret
# Maya's registered OAuth application, as the identity provider knows it.
CLIENT_ID = "maya_test_client"
TEAM = {"id": "team_fake0000000000000001", "name": "Test team"}
IMAGE_MODEL = {
    "id": "model_openai-gpt-image-2-5-flare",
    "name": "GPT Image 2.5 Flare",
    "shortDescription": "Fast image generation and editing.",
    "type": "custom",
    "privacy": "public",
    "capabilities": ["txt2img", "img2img"],
    "status": "trained",
    "tags": ["Image"],
    "createdAt": "2026-09-01T00:00:00.000Z",
}
THREE_D_MODEL = {
    "id": "model_meshy-7-1-txt23d",
    "name": "Meshy 7.1 - Text-to-3D",
    "shortDescription": "Textured 3D models from a prompt.",
    "type": "custom",
    "privacy": "public",
    "capabilities": ["txt23d"],
    "status": "trained",
    "tags": ["3d"],
    "createdAt": "2026-09-22T00:00:00.000Z",
}
IMAGE_TO_3D_MODEL = {
    "id": "model_meshy-7-1-img23d",
    "name": "Meshy 7.1 - Image to 3D",
    "shortDescription": "Textured 3D models from one image or up to four views.",
    "type": "custom",
    "privacy": "public",
    "capabilities": ["img23d"],
    "status": "trained",
    "tags": ["3d"],
    "createdAt": "2026-09-22T00:00:00.000Z",
}
PROJECT = {"id": "proj_fake0000000000000001", "name": "Test project"}

PRICES = {
    "model_openai-gpt-image-2-5-flare": 11,
    "model_meshy-7-1-txt23d": 120,
    "model_meshy-remesh": 20,
    "model_meshy-uv-unwrap": 20,
    "model_tripo-v3-1-image-to-3d": 45,
    "model_meshy-7-1-img23d": 120,
    "model_tripo-p2-image-to-3d": 220,
    "model_spark-test": 2.75,
    "model_tripo-retopology-v3": 70,
    "model_tripo-smart-uv": 40,
    "model_tencent-uv-unwrapping": 23,
    "model_meshy-7-retexture": 40,
    "model_tripo-v3-0-texturing": 15,
    "model_tripo-p2-multiview-to-3d": 220,
    "model_tripo-v3-1-multiview-to-3d": 45,
    "model_hunyuan-3d-pro-3-1-multiview": 120,
    "model_meshy-text-to-motion": 40,
    "model_cartwheel-text-to-motion": 72,
    "model_uthana-text-to-motion-3.0": 104,
}


THREE_D_MODELS = ("model_meshy-7-1-txt23d", "model_meshy-t2-5-smart-topology", "model_tripo-v3-1-image-to-3d", "model_meshy-7-1-img23d", "model_tripo-p2-image-to-3d")
IMAGE_INPUT_MODELS = ("model_tripo-v3-1-image-to-3d", "model_meshy-7-1-img23d", "model_tripo-p2-image-to-3d")
# Multi-view models: named view fields; the Tripo ones refuse a front view alone, like the live ones say they do.
MULTIVIEW_MODELS = {
    "model_tripo-p2-multiview-to-3d": "Tripo P2 Multi View",
    "model_tripo-v3-1-multiview-to-3d": "Tripo 3.1 Multi View",
    "model_hunyuan-3d-pro-3-1-multiview": "Hunyuan 3D 3.1 Pro (Multiview)",
}
THREE_D_MODELS = THREE_D_MODELS + tuple(MULTIVIEW_MODELS)
MULTIVIEW_ROWS = [
    {
        "id": model_id,
        "name": name,
        "shortDescription": "A textured 3D model from views of one object.",
        "type": "custom",
        "privacy": "public",
        "capabilities": ["img23d"],
        "status": "trained",
        "tags": ["3d", "Multiview"],
        "createdAt": "2026-09-01T00:00:00.000Z",
    }
    for model_id, name in MULTIVIEW_MODELS.items()
]

# Edit models (3d23d): task, mesh field, longest side of the result in metres (0: returned in
# place). On 2026-10-19 Tripo models returned the sent mesh 1 m long and centred, Meshy Remesh
# and Meshy 7 Retexture 2 m long and centred, Meshy UV Unwrap in place, none rotated; the
# Tencent model was not run live, so its size here is a guess.
EDIT_MODELS = {
    "model_tripo-retopology-v3": ("remesh", "model", 1.0, "Tripo Retopology v3"),
    "model_meshy-remesh": ("remesh", "model", 2.0, "Meshy Remesh"),
    "model_tripo-smart-uv": ("uv", "model", 1.0, "Tripo Smart UV"),
    "model_tencent-uv-unwrapping": ("uv", "file3d", 1.0, "Tencent UV Unwrapping"),
    "model_meshy-uv-unwrap": ("uv", "model", 0.0, "Meshy UV Unwrap"),
    "model_meshy-7-retexture": ("retexture", "model", 2.0, "Meshy 7 Retexture"),
    "model_tripo-v3-0-texturing": ("retexture", "model", 1.0, "Tripo 3.0 Texturing"),
}
EDIT_ROWS = [
    {
        "id": model_id,
        "name": name,
        "shortDescription": f"{task.title()} of an uploaded 3D model.",
        "type": "custom",
        "privacy": "public",
        "capabilities": ["3d23d"],
        "status": "trained",
        "tags": ["3d"],
        "createdAt": "2026-09-15T00:00:00.000Z",
    }
    for model_id, (task, _field, _side, name) in EDIT_MODELS.items()
]


# Motion models (txt23d, tagged Motion): their character field, if any, and whether they need one.
# Cartwheel refuses to price without a character, as the live one did on 2026-10-19.
MOTION_MODELS = {
    "model_meshy-text-to-motion": ("", False, "Meshy Text to Motion", ["txt23d"]),
    "model_cartwheel-text-to-motion": ("characterModel", True, "Cartwheel Text to Motion", ["txt23d", "3d23d"]),
    "model_uthana-text-to-motion-3.0": ("characterFile", False, "Uthana Text to Motion 3.0", ["txt23d"]),
}
MOTION_ROWS = [
    {
        "id": model_id,
        "name": name,
        "shortDescription": "A rigged character that moves, from a prompt.",
        "type": "custom",
        "privacy": "public",
        "capabilities": capabilities,
        "status": "trained",
        "tags": ["3D", "Animation", "Motion"],
        "createdAt": "2026-08-25T00:00:00.000Z",
    }
    for model_id, (_field, _needed, name, capabilities) in MOTION_MODELS.items()
]


def _motion_glb() -> bytes:
    """A skinned, keyed character stand-in: the two-joint strip of the GLB samples."""
    from tests import glb_samples

    with tempfile.TemporaryDirectory() as folder:
        with open(glb_samples.skinned_strip(os.path.join(folder, "motion.glb")), "rb") as handle:
            return handle.read()


def _glb() -> bytes:
    """A textured quad GLB, the shape of a real 3D result at test size."""
    import tempfile

    from tests import glb_samples

    with tempfile.TemporaryDirectory() as folder:
        path = glb_samples.textured_quad(os.path.join(folder, "result.glb"))
        with open(path, "rb") as handle:
            return handle.read()


def _edited_glb(task: str, side: float, source: bytes) -> tuple:
    """(GLB bytes, triangles, dimensions): the sent mesh as the edit models returned it on
    2026-10-19, rescaled to ``side`` metres and centred (in place when 0), no rotation. A UV task gets a new
    layout (a planar projection, one UV per vertex position), a retexture keeps the sent
    UVs and adds a base colour texture, a remesh returns the same surface with its own
    triangles (each split in four at its edge midpoints, as a stand-in for a new topology)."""
    from scenario_maya.core import gltf, gltf_write, topology

    mesh = topology.result_from_document(gltf.Document.parse(source))
    lo, hi = topology.bounds(mesh.points)
    size = max(max(hi[k] - lo[k] for k in range(3)), 1e-9)
    scale = side / size if side else 1.0
    centre = [(lo[k] + hi[k]) / 2 for k in range(3)] if side else [0.0, 0.0, 0.0]
    points = [(scale * (x - centre[0]), scale * (y - centre[1]), scale * (z - centre[2])) for x, y, z in mesh.points]
    triangles = mesh.triangles
    uvs = mesh.uvs
    materials = None
    if task == "uv" or (task == "retexture" and uvs is None):
        uvs = [((x - lo[0]) / size, (z - lo[2]) / size) for x, _y, z in mesh.points]
    if task == "remesh":
        points, triangles, uvs = _split_in_four(points, triangles, uvs)
    if task == "retexture":
        materials = [gltf_write.MaterialPart("retextured", image=_png(8, 8, (60, 110, 200)), image_mime="image/png")]
    part = gltf_write.MeshPart(
        "result",
        [value for point in points for value in point],
        [gltf_write.Primitive([index for triangle in triangles for index in triangle], 0 if materials else None)],
        uvs=[value for uv in uvs for value in uv] if uvs is not None else None,
    )
    dims = [round(scale * (hi[k] - lo[k]), 6) for k in range(3)]
    return gltf_write.to_bytes([part], materials, generator="fake edit model"), len(triangles), dims


def _split_in_four(points: list, triangles: list, uvs: list | None) -> tuple:
    """Each triangle split in four at its edge midpoints: the same surface, another topology."""
    points, uvs = list(points), list(uvs) if uvs is not None else None
    middle: dict = {}

    def mid(a: int, b: int) -> int:
        key = (min(a, b), max(a, b))
        if key not in middle:
            middle[key] = len(points)
            points.append(tuple((points[a][k] + points[b][k]) / 2 for k in range(3)))
            if uvs is not None:
                uvs.append(((uvs[a][0] + uvs[b][0]) / 2, (uvs[a][1] + uvs[b][1]) / 2))
        return middle[key]

    out = []
    for a, b, c in triangles:
        ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
        out += [(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)]
    return points, out, uvs


def _load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def _png(width: int = 8, height: int = 8, rgb=(200, 120, 40)) -> bytes:
    import struct
    import zlib

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class ToolFailure(Exception):
    """A handler's refusal: the status and the API's ``{reason}`` body."""

    def __init__(self, status: int, body: dict) -> None:
        super().__init__(status)
        self.status = status
        self.body = body


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: list = []
        self.faults: dict = {}
        self.jobs: dict = {}
        self.assets: dict = {}
        self.files: dict = {}
        self.uploads: dict = {}
        self.upload_puts: list = []  # (upload id, part number, headers) per PUT
        self.file_requests: list = []  # (name, Range header) per file GET
        self.file_faults: dict = {}  # name -> list of "503", "cut" (half the bytes, then close), "redirect:<url>"
        self.polls_to_finish = 2
        self.clients: dict = {CLIENT_ID: {"redirect_uris": ["http://127.0.0.1/callback"], "name": "Scenario for Maya"}}
        self.registrations: list = []
        self.authorize_queries: list = []
        self.codes: dict = {}
        self.access_tokens: dict = {}
        self.refresh_tokens: dict = {}
        self.device_codes: dict = {}
        self.revoked: list = []
        self.auto_approve = True
        self.token_lifetime = 3600

    def fail(self, op: str, kind: str, times: int = 1) -> None:
        with self.lock:
            self.faults.setdefault(op, []).extend([kind] * times)

    def take_fault(self, op: str) -> str:
        with self.lock:
            queue = self.faults.get(op) or []
            return queue.pop(0) if queue else ""

    def paid_runs(self) -> list:
        """Paid requests that got past the gateway (a refused token never reaches the handler)."""
        return [c for c in self.calls if c["op"] == "generate" and c["query"].get("dryRun") != "true" and c.get("fault") != "expired"]

    def calls_to(self, op: str) -> list:
        return [c for c in self.calls if c["op"] == op]


class Handler(BaseHTTPRequestHandler):
    server_version = "FakeScenario/1.0"

    def log_message(self, *args):
        return

    @property
    def state(self) -> State:
        return self.server.state  # type: ignore[attr-defined]

    @property
    def base(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    # -- helpers ---------------------------------------------------------

    def _send(self, status: int, body: bytes = b"", content_type: str = "application/json", headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, status: int, data, headers: dict | None = None) -> None:
        self._send(status, json.dumps(data).encode(), "application/json", headers)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _credentials(self) -> str:
        """``key`` or ``user`` for accepted credentials, ``""`` for anything else."""
        header = self.headers.get("Authorization") or ""
        if header.startswith("Basic "):
            try:
                key, _, secret = base64.b64decode(header[6:]).decode().partition(":")
            except ValueError:
                return ""
            return "key" if key == API_KEY and secret == API_SECRET else ""
        if header.startswith("Bearer "):
            expires = self.state.access_tokens.get(header[7:])
            return "user" if expires and expires > time.time() else ""
        return ""

    def _denied(self, reason: str = "Forbidden") -> None:
        """The gateway's refusal: before any handler, with the header the API's gateway adds."""
        self._json(403, {"reason": reason}, {"x-amzn-errortype": "AccessDeniedException"})

    # -- routes ----------------------------------------------------------

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/.well-known/oauth-authorization-server":
            self._json(
                200,
                {
                    "issuer": self.base,
                    "authorization_endpoint": self.base + "/oauth/authorize",
                    "token_endpoint": self.base + "/oauth/token",
                    "registration_endpoint": self.base + "/oauth/register",
                    "revocation_endpoint": self.base + "/oauth/revoke",
                    "device_authorization_endpoint": self.base + "/oauth/device_authorization",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
            return
        if parsed.path == "/oauth/authorize":
            self._authorize(urllib.parse.parse_qs(parsed.query))
            return
        if parsed.path.startswith("/files/"):
            self._file(parsed.path[len("/files/") :])
            return
        if parsed.path.startswith("/v1/"):
            self._api("GET", parsed, b"")
            return
        self._send(404)

    def do_PUT(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/upload/"):
            upload_id = parsed.path.split("/")[2]
            number = int((urllib.parse.parse_qs(parsed.query).get("partNumber") or ["1"])[0])
            data = self._body()
            with self.state.lock:
                upload = self.state.uploads.get(upload_id)
                if upload is None:
                    self._send(404)
                    return
                upload["parts"][number] = data
                self.state.upload_puts.append((upload_id, number, {k.lower(): v for k, v in self.headers.items()}))
            self._send(200, b"", "text/plain", {"ETag": '"' + hashlib.md5(data).hexdigest() + '"'})
            return
        self._send(404)

    def do_POST(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        body = self._body()
        if parsed.path == "/oauth/register":
            self._register(json.loads(body or b"{}"))
        elif parsed.path == "/oauth/token":
            self._token(urllib.parse.parse_qs(body.decode()))
        elif parsed.path == "/oauth/device_authorization":
            self._device(urllib.parse.parse_qs(body.decode()))
        elif parsed.path == "/oauth/revoke":
            form = urllib.parse.parse_qs(body.decode())
            self.state.revoked.append((form.get("token") or [""])[0])
            self.state.refresh_tokens.pop((form.get("token") or [""])[0], None)
            self._send(200)
        elif parsed.path.startswith("/v1/"):
            self._api("POST", parsed, body)
        else:
            self._send(404)

    # -- OAuth -----------------------------------------------------------

    def _register(self, data: dict) -> None:
        self.state.registrations.append(data)
        client_id = "client_" + secrets.token_hex(6)
        self.state.clients[client_id] = {"redirect_uris": data.get("redirect_uris") or [], "name": data.get("client_name")}
        self._json(201, {"client_id": client_id, "redirect_uris": data.get("redirect_uris") or []})

    def _authorize(self, query: dict) -> None:
        get = lambda key: (query.get(key) or [""])[0]  # noqa: E731
        self.state.authorize_queries.append({key: values[0] for key, values in query.items()})
        client = self.state.clients.get(get("client_id"))
        redirect = get("redirect_uri")
        if client is None or not _redirect_allowed(redirect, client["redirect_uris"]) or get("code_challenge_method") != "S256":
            self._send(400, b"bad request", "text/plain")
            return
        code = "code_" + secrets.token_hex(8)
        self.state.codes[code] = {"client_id": get("client_id"), "redirect": redirect, "challenge": get("code_challenge")}
        target = redirect + "?" + urllib.parse.urlencode({"code": code, "state": get("state")} if self.state.auto_approve else {"error": "access_denied", "state": get("state")})
        self._send(302, b"", "text/plain", {"Location": target})

    def _issue(self, client_id: str) -> dict:
        access = "at_" + secrets.token_hex(12)
        refresh = "rt_" + secrets.token_hex(12)
        self.state.access_tokens[access] = time.time() + self.state.token_lifetime
        self.state.refresh_tokens[refresh] = client_id
        return {"access_token": access, "refresh_token": refresh, "expires_in": self.state.token_lifetime, "token_type": "Bearer", "scope": "openid offline_access"}

    def _token(self, form: dict) -> None:
        get = lambda key: (form.get(key) or [""])[0]  # noqa: E731
        grant = get("grant_type")
        if grant == "authorization_code":
            entry = self.state.codes.pop(get("code"), None)
            verifier = get("code_verifier")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if entry is None or entry["client_id"] != get("client_id") or entry["redirect"] != get("redirect_uri") or entry["challenge"] != challenge:
                self._json(400, {"error": "invalid_grant"})
                return
            self._json(200, self._issue(get("client_id")))
        elif grant == "refresh_token":
            client = self.state.refresh_tokens.pop(get("refresh_token"), None)
            if client is None or client != get("client_id"):
                self._json(400, {"error": "invalid_grant", "error_description": "refresh token revoked"})
                return
            self._json(200, self._issue(client))
        elif grant == "urn:ietf:params:oauth:grant-type:device_code":
            entry = self.state.device_codes.get(get("device_code"))
            if entry is None:
                self._json(400, {"error": "expired_token"})
            elif entry["polls"] > 0:
                entry["polls"] -= 1
                self._json(400, {"error": "authorization_pending"})
            else:
                self.state.device_codes.pop(get("device_code"))
                self._json(200, self._issue(entry["client_id"]))
        else:
            self._json(400, {"error": "unsupported_grant_type"})

    def _device(self, form: dict) -> None:
        client_id = (form.get("client_id") or [""])[0]
        if client_id not in self.state.clients:
            self._json(401, {"error": "invalid_client"})
            return
        code = "dc_" + secrets.token_hex(8)
        self.state.device_codes[code] = {"client_id": client_id, "polls": 1}
        self._json(200, {"device_code": code, "user_code": "WXYZ-1234", "verification_uri": "https://example.invalid/device", "interval": 1, "expires_in": 60})

    # -- files -----------------------------------------------------------

    def _file(self, name: str) -> None:
        data = self.state.files.get(name)
        header = self.headers.get("Range") or ""
        with self.state.lock:
            self.state.file_requests.append((name, header))
            queue = self.state.file_faults.get(name) or []
            fault = queue.pop(0) if queue else ""
        if data is None:
            self._send(404)
            return
        if fault == "503":
            self._send(503, b"busy", "text/plain")
            return
        if fault.startswith("redirect:"):
            self._send(302, b"", "text/plain", {"Location": fault[len("redirect:") :]})
            return
        if fault == "cut":
            half = data[: len(data) // 2]
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(half)
            self.wfile.flush()
            self.close_connection = True
            return
        if header.startswith("bytes="):
            start = int(header[6:].split("-")[0] or 0)
            part = data[start:]
            self._send(206, part, "application/octet-stream", {"Content-Range": f"bytes {start}-{len(data) - 1}/{len(data)}", "Accept-Ranges": "bytes"})
        else:
            self._send(200, data, "application/octet-stream", {"Accept-Ranges": "bytes"})

    # -- REST API ----------------------------------------------------------

    _ROUTES = (
        ("GET", r"/v1/teams", "teams"),
        ("GET", r"/v1/projects", "projects"),
        ("GET", r"/v1/models", "models"),
        ("GET", r"/v1/models/(?P<id>[^/]+)", "model"),
        ("POST", r"/v1/generate/custom/(?P<id>[^/]+)", "generate"),
        ("GET", r"/v1/jobs", "jobs"),
        ("GET", r"/v1/jobs/(?P<id>[^/]+)", "job"),
        ("GET", r"/v1/assets/(?P<id>[^/]+)", "asset"),
        ("POST", r"/v1/assets/(?P<id>[^/]+)/download", "download"),
        ("POST", r"/v1/uploads", "upload_create"),
        ("POST", r"/v1/uploads/(?P<id>[^/]+)/action", "upload_action"),
        ("GET", r"/v1/uploads/(?P<id>[^/]+)", "upload_read"),
    )

    def _api(self, method: str, parsed, body: bytes) -> None:
        found = next(((op, match) for verb, pattern, op in self._ROUTES if verb == method and (match := re.fullmatch(pattern, parsed.path))), None)
        if found is None:
            self._json(404, {"reason": "Not found"})
            return
        op, match = found
        query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()}
        try:
            data = json.loads(body) if body else {}
        except ValueError:
            self._json(400, {"reason": "Invalid JSON body"})
            return
        who = self._credentials()
        fault = self.state.take_fault(op)
        with self.state.lock:
            self.state.calls.append({"op": op, "id": match.groupdict().get("id") or "", "query": query, "body": data, "auth": who, "time": time.time(), "fault": fault})
        if not who or fault == "expired":
            self._denied()
            return
        if op in ("teams",) and who == "key":
            self._denied("You cannot access this team or project")
            return
        if fault == "http500":
            self._json(500, {"reason": "Internal server error"})
            return
        if fault == "redirect":
            self._send(302, b"", "text/plain", {"Location": self.base + "/files/elsewhere"})
            return
        if fault == "http504":
            self._json(504, {"message": "Endpoint request timed out"})
            return
        if fault == "http429":
            self._json(429, {"reason": "Too many requests, please slow down.", "name": "RateLimitError"})
            return
        if fault == "plan_limit":
            self._json(429, {"reason": "Your plan's limit is reached.", "name": "PlanLimitReachedError", "details": {"limitScope": "team"}})
            return
        if fault == "http400":
            self._json(400, {"reason": "Input prompt is required"})
            return
        if fault == "moderation":
            self._json(400, {"reason": "Prompt flagged by moderation"})
            return
        try:
            status, result = getattr(self, "_op_" + op)(match.group("id") if "id" in match.groupdict() else "", query, data, who)
        except ToolFailure as failure:
            self._json(failure.status, failure.body)
            return
        if fault == "drop":
            self.close_connection = True
            self.connection.close()
            return
        if fault == "no_job":
            result = {}
        self._json(status, result)

    def _op_teams(self, _id, query, data, who):
        return 200, {"teams": [dict(TEAM, projects=[dict(PROJECT)])]}

    def _op_projects(self, _id, query, data, who):
        return 200, {"projects": [dict(PROJECT, teamId=TEAM["id"], members=[{"email": "member@example.invalid"}])], "nextPaginationToken": ""}

    def _op_models(self, _id, query, data, who):
        if query.get("privacy") != "public":
            return 200, {"models": [], "nextPaginationToken": ""}
        rows = _load_fixture("models_list.json")["models"] + [IMAGE_MODEL, THREE_D_MODEL, IMAGE_TO_3D_MODEL] + [dict(row) for row in EDIT_ROWS + MULTIVIEW_ROWS + MOTION_ROWS]
        return 200, {"models": rows, "nextPaginationToken": ""}

    def _op_model(self, model_id, query, data, who):
        name = f"schema_{model_id}.json"
        path = os.path.join(FIXTURES, name)
        schema = (
            _load_fixture(name)
            if os.path.exists(path)
            else {"model_id": model_id, "name": "Test model", "capabilities": ["txt2img"], "parameters": [{"name": "prompt", "type": "string", "required": True, "prompt": True}]}
        )
        model = {
            "id": model_id,
            "name": schema.get("name"),
            "type": "custom",
            "capabilities": schema.get("capabilities") or [],
            "status": "trained",
            "inputs": [_api_input(p) for p in schema.get("parameters") or []],
        }
        return 200, {"model": model}

    def _op_generate(self, model_id, query, params, who):
        cost = PRICES.get(model_id, 10)
        if model_id in IMAGE_INPUT_MODELS:
            # Like the service, a run checks its required image: it must be an uploaded asset.
            given = params.get("image")
            ids = given if isinstance(given, list) else [given] if given else []
            if not ids or any(asset_id not in self.state.assets for asset_id in ids):
                raise ToolFailure(400, {"reason": "image: Asset not found or not an uploaded image."})
        if model_id in MULTIVIEW_MODELS:
            given = {key: value for key, value in params.items() if key.endswith("Image")}
            if given.get("frontImage") not in self.state.assets or any(value not in self.state.assets for value in given.values()):
                raise ToolFailure(400, {"reason": "frontImage: Asset not found or not an uploaded image."})
            if model_id.startswith("model_tripo") and len(given) < 2:
                raise ToolFailure(400, {"reason": "Provide the front view with at least one of left, back, right."})
        if model_id in EDIT_MODELS:
            field = EDIT_MODELS[model_id][1]
            given = params.get(field)
            asset = self.state.assets.get(given) if isinstance(given, str) else None
            if asset is None or asset.get("kind") != "3d":
                raise ToolFailure(400, {"reason": f"{field}: Asset not found or not an uploaded 3D model."})
        if model_id in MOTION_MODELS:
            field, needed, _name, _caps = MOTION_MODELS[model_id]
            given = params.get(field) if field else None
            if needed and not given:
                raise ToolFailure(400, {"reason": "Provide a reference image or a 3D model."})
            if given is not None:
                asset = self.state.assets.get(given) if isinstance(given, str) else None
                if asset is None or asset.get("kind") != "3d":
                    raise ToolFailure(400, {"reason": f"{field}: Asset not found or not an uploaded 3D model."})
                cost += 20 if model_id == "model_uthana-text-to-motion-3.0" else 0  # Uthana prices a character in
        if query.get("dryRun") == "true":
            return 269, {"creativeUnitsCost": cost, "creativeUnitsDiscount": 0}
        job_id = "job_fake" + secrets.token_hex(8)
        if model_id in THREE_D_MODELS:
            self._run_3d(model_id, job_id, cost)
        elif model_id in MOTION_MODELS:
            self._run_3d(model_id, job_id, cost, glb=_motion_glb(), meta={"kind": "3d", "faceCount": 4, "boneCount": 2})
        elif model_id in EDIT_MODELS:
            task, field, side, _name = EDIT_MODELS[model_id]
            source = self.state.files[self.state.assets[params[field]]["file"]]
            glb, triangles, dims = _edited_glb(task, side, source)
            self._run_3d(model_id, job_id, cost, glb=glb, meta={"kind": "3d", "faceCount": triangles, "dimensions": dims})
        else:
            asset_id = "asset_fake" + secrets.token_hex(8)
            with self.state.lock:
                self.state.jobs[job_id] = _new_job(job_id, model_id, cost, [asset_id])
                self.state.files[asset_id + ".png"] = _png()
                self.state.assets[asset_id] = {"id": asset_id, "mimeType": "image/png", "kind": "image", "file": asset_id + ".png"}
        return 200, {"job": self._job_row(job_id, advance=False)}

    def _run_3d(self, model_id: str, job_id: str, cost, glb: bytes = b"", meta: dict | None = None) -> None:
        """Like the service: a GLB, its OBJ and MTL siblings and a texture. The OBJ comes
        first here (the service lists the GLB first) so tests prove the pick is by format."""
        data = glb or _glb()
        glb, obj, mtl, png = ("asset_fake" + secrets.token_hex(8) for _ in range(4))
        meta = meta or {"kind": "3d", "faceCount": 2, "dimensions": [1.0, 1.0, 0.0]}
        with self.state.lock:
            self.state.jobs[job_id] = _new_job(job_id, model_id, cost, [obj, glb, mtl, png])
            self.state.files[glb + ".glb"] = data
            self.state.files[glb + "_thumb.png"] = _png(16, 16, (90, 160, 90))
            self.state.files[obj + ".obj"] = b"v 0 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 3\n"
            self.state.files[mtl + ".mtl"] = b"newmtl m\n"
            self.state.files[png + ".png"] = _png()
            self.state.assets[glb] = {"id": glb, "mimeType": "model/gltf-binary", "kind": "3d", "file": glb + ".glb", "metadata": dict(meta, format="glb"), "thumbnail": glb + "_thumb.png"}
            self.state.assets[obj] = {"id": obj, "mimeType": "model/obj", "kind": "3d", "file": obj + ".obj", "metadata": dict(meta, format="obj", parentId=glb)}
            self.state.assets[mtl] = {"id": mtl, "mimeType": "model/mtl", "kind": "3d", "file": mtl + ".mtl", "metadata": {"type": "3d-texture-mtl", "parentId": glb}}
            self.state.assets[png] = {"id": png, "mimeType": "image/png", "kind": "image", "file": png + ".png", "metadata": {"type": "3d-texture-albedo", "parentId": glb}}

    def _job_row(self, job_id: str, advance: bool = True) -> dict:
        """The job as ``GET /jobs/{id}`` answers it; each read moves it on until it succeeds."""
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job is None:
                return {}
            if advance and job["status"] not in ("success", "failure"):
                job["polls"] += 1
                if job["polls"] >= self.state.polls_to_finish:
                    job["status"] = "success"
                    job["progress"] = 1
                    job["metadata"]["assetIds"] = list(job["result_assets"])
                else:
                    job["status"] = "in-progress"
                    job["progress"] = 0.5
            return json.loads(json.dumps({k: v for k, v in job.items() if k not in ("polls", "result_assets")}))

    def _op_job(self, job_id, query, data, who):
        row = self._job_row(job_id)
        if not row:
            raise ToolFailure(404, {"reason": f"Job {job_id} not found"})
        return 200, {"job": row}

    def _op_jobs(self, _id, query, data, who):
        with self.state.lock:
            ids = list(self.state.jobs)
        rows = [self._job_row(job_id, advance=False) for job_id in ids]
        if query.get("status"):
            rows = [row for row in rows if row["status"] == query["status"]]
        rows.sort(key=lambda r: r["createdAt"], reverse=True)
        return 200, {"jobs": rows[: int(query.get("pageSize") or 50)], "nextPaginationToken": ""}

    def _op_asset(self, asset_id, query, data, who):
        asset = self.state.assets.get(asset_id)
        if not asset:
            raise ToolFailure(404, {"reason": f"Asset {asset_id} not found"})
        out = {"id": asset["id"], "url": f"{self.base}/files/{asset['file']}", "mimeType": asset["mimeType"], "kind": asset["kind"], "status": "success"}
        if asset.get("metadata"):
            out["metadata"] = dict(asset["metadata"])
        if asset.get("thumbnail"):
            out["thumbnail"] = {"assetId": asset["id"] + "_thumb", "url": f"{self.base}/files/{asset['thumbnail']}"}
        return 200, {"asset": out}

    def _op_download(self, asset_id, query, data, who):
        asset = self.state.assets.get(asset_id)
        if not asset:
            raise ToolFailure(404, {"reason": f"Asset {asset_id} not found"})
        return 200, {"url": f"{self.base}/files/{asset['file']}", "mimeType": asset["mimeType"]}

    def _op_upload_create(self, _id, query, data, who):
        upload_id = "upl_fake" + secrets.token_hex(6)
        count = int(data.get("parts") or 1)
        with self.state.lock:
            self.state.uploads[upload_id] = {
                "parts": {},
                "name": data.get("fileName"),
                "kind": data.get("kind"),
                "size": int(data.get("fileSize") or 0),
                "content_type": data.get("contentType"),
                "status": "pending",
                "count": count,
            }
        # Signed links carry their signature in the query; a client must PUT them unchanged.
        parts = [{"number": n, "url": f"{self.base}/upload/{upload_id}?partNumber={n}&X-Amz-Signature=fake", "expires": "2099-01-01T00:00:00.000Z"} for n in range(1, count + 1)]
        return 200, {"upload": {"id": upload_id, "status": "pending", "fileName": data.get("fileName"), "partsCount": count, "parts": parts}, "creativeUnitsCost": 0}

    def _upload_json(self, upload_id: str) -> dict:
        upload = self.state.uploads[upload_id]
        out = {"id": upload_id, "status": upload["status"], "fileName": upload["name"]}
        if upload.get("entityId"):
            out["entityId"] = upload["entityId"]
        if upload.get("errorMessage"):
            out["errorMessage"] = upload["errorMessage"]
        return out

    def _op_upload_action(self, upload_id, query, data, who):
        upload = self.state.uploads.get(upload_id)
        if upload is None:
            raise ToolFailure(400, {"reason": f"Unable to load request upload id {upload_id}"})
        if data.get("action") != "complete":
            raise ToolFailure(400, {"reason": "Unknown action"})
        if upload["status"] != "pending":
            raise ToolFailure(400, {"reason": f"Unable to complete upload with status: {upload['status']}"})
        received = b"".join(upload["parts"][n] for n in sorted(upload["parts"]))
        with self.state.lock:
            if len(received) != upload["size"]:
                upload["status"] = "failed"
                upload["errorMessage"] = f"received {len(received)} of {upload['size']} bytes"
            else:
                asset_id = "asset_up" + secrets.token_hex(8)
                upload["data"] = received
                upload["status"] = "imported"
                upload["entityId"] = asset_id
                self.state.files[asset_id] = received
                self.state.assets[asset_id] = {"id": asset_id, "mimeType": upload["content_type"] or "application/octet-stream", "kind": upload["kind"], "file": asset_id}
        return 200, {"upload": self._upload_json(upload_id)}

    def _op_upload_read(self, upload_id, query, data, who):
        if upload_id not in self.state.uploads:
            raise ToolFailure(404, {"reason": "Upload not found"})
        return 200, {"upload": self._upload_json(upload_id)}


def _new_job(job_id: str, model_id: str, cost, result_assets: list) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    return {
        "jobId": job_id,
        "jobType": "custom",
        "status": "queued",
        "progress": 0,
        "metadata": {"input": {"modelId": model_id}, "assetIds": []},
        "billing": {"cuCost": cost, "cuDiscount": 0},
        "createdAt": now,
        "updatedAt": now,
        "polls": 0,
        "result_assets": result_assets,
    }


def _api_input(parameter: dict) -> dict:
    """A recorded MCP parameter back in the API's own shape (camelCase, ``required.always``)."""
    renames = {
        "allowed_values": "allowedValues",
        "min_length": "minLength",
        "max_length": "maxLength",
        "cost_impact": "costImpact",
        "prompt_spark": "promptSpark",
        "model_types": "modelTypes",
        "max_size": "maxSize",
        "max_duration": "maxDuration",
    }
    out = {}
    for key, value in parameter.items():
        if key in ("array", "array_note", "background_note"):
            continue
        if key == "required":
            if value:
                out["required"] = {"always": True}
        elif key == "fields":
            out["inputs"] = [_api_input(item) for item in value]
        else:
            out[renames.get(key, key)] = value
    return out


def _redirect_allowed(redirect: str, registered: list) -> bool:
    """Exact match, except that a loopback redirect matches on scheme, host and path (RFC 8252, 7.3)."""
    if redirect in registered:
        return True
    asked = urllib.parse.urlparse(redirect)
    if asked.scheme != "http" or asked.hostname != "127.0.0.1":
        return False
    for uri in registered:
        known = urllib.parse.urlparse(uri)
        if known.scheme == "http" and known.hostname == "127.0.0.1" and known.path == asked.path:
            return True
    return False


class FakeScenario:
    """Context manager: ``with FakeScenario() as fake: fake.endpoint ...``."""

    def __init__(self) -> None:
        self.state = State()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.state = self.state  # type: ignore[attr-defined]
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="fake-scenario", daemon=True)

    @property
    def base(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def endpoint(self) -> str:
        """The API base, as ``SCENARIO_API_URL`` names it."""
        return self.base + "/v1"

    @property
    def metadata_url(self) -> str:
        return self.base + "/.well-known/oauth-authorization-server"

    def start(self) -> FakeScenario:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self) -> FakeScenario:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
