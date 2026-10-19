"""A local stand-in for the hosted Scenario MCP, its OAuth server and its file CDN.

Used by the unit tests, the ``mayapy`` tests and the agent tests, so no test
spends Creative Units or needs the network. Reply shapes follow recordings of
the hosted server (version 0.34.0, 2026-10-18), scrubbed of real ids.

Faults are queued per tool: ``server.state.fail("model_run", kind)`` where kind
is one of ``drop`` (job created, connection closed before the reply),
``http500``, ``http401``, ``http429``, ``tool_error_400``, ``tool_error_500``,
``tool_error_generic``, ``moderation``, ``session_404``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(os.path.dirname(HERE), "fixtures", "mcp")

API_KEY = "api_testkey000000000001"
API_SECRET = "test-secret-not-real"  # not a secret
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
}


THREE_D_MODELS = ("model_meshy-7-1-txt23d", "model_meshy-t2-5-smart-topology", "model_tripo-v3-1-image-to-3d", "model_meshy-7-1-img23d", "model_tripo-p2-image-to-3d")
IMAGE_INPUT_MODELS = ("model_tripo-v3-1-image-to-3d", "model_meshy-7-1-img23d", "model_tripo-p2-image-to-3d")

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
    """A tool's own refusal, answered as the hosted server does (isError with the status)."""

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
        self.upload_part_size = 6000000  # Scenario's part size; tests lower it to get several parts
        self.upload_puts: list = []  # (upload id, part number, headers) per PUT
        self.file_requests: list = []  # (name, Range header) per file GET
        self.file_faults: dict = {}  # name -> list of "503", "cut" (half the bytes, then close), "redirect:<url>"
        self.polls_to_finish = 2
        self.reply_mode = "sse"  # or "json"
        self.issue_sessions = False
        self.sessions: set = set()
        self.clients: dict = {}
        self.codes: dict = {}
        self.access_tokens: dict = {}
        self.refresh_tokens: dict = {}
        self.device_codes: dict = {}
        self.revoked: list = []
        self.auto_approve = True
        self.token_lifetime = 3600

    def fail(self, tool: str, kind: str, times: int = 1) -> None:
        with self.lock:
            self.faults.setdefault(tool, []).extend([kind] * times)

    def take_fault(self, tool: str) -> str:
        with self.lock:
            queue = self.faults.get(tool) or []
            return queue.pop(0) if queue else ""

    def paid_runs(self) -> list:
        """Paid requests that got past authentication (a 401 or an expired session refuses before the tool)."""
        return [c for c in self.calls if c["tool"] == "model_run" and not c["arguments"].get("dry_run") and c.get("fault") not in ("http401", "session_404")]

    def tool_calls(self, name: str) -> list:
        return [c for c in self.calls if c["tool"] == name]


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

    def _rpc_reply(self, request_id, result=None, error=None, headers: dict | None = None) -> None:
        message = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            message["error"] = error
        else:
            message["result"] = result
        if self.state.reply_mode == "sse":
            progress = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 0.5}}
            body = f"event: message\ndata: {json.dumps(progress)}\n\nevent: message\ndata: {json.dumps(message)}\n\n".encode()
            self._send(200, body, "text/event-stream", headers)
        else:
            self._json(200, message, headers)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization") or ""
        if header.startswith("Basic "):
            try:
                key, _, secret = base64.b64decode(header[6:]).decode().partition(":")
            except ValueError:
                return False
            return key == API_KEY and secret == API_SECRET
        if header.startswith("Bearer "):
            token = header[7:]
            expires = self.state.access_tokens.get(token)
            return bool(expires and expires > time.time())
        return False

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
        elif parsed.path == "/mcp":
            self._mcp(body)
        else:
            self._send(404)

    # -- OAuth -----------------------------------------------------------

    def _register(self, data: dict) -> None:
        client_id = "client_" + secrets.token_hex(6)
        self.state.clients[client_id] = {"redirect_uris": data.get("redirect_uris") or [], "name": data.get("client_name")}
        self._json(201, {"client_id": client_id, "redirect_uris": data.get("redirect_uris") or []})

    def _authorize(self, query: dict) -> None:
        get = lambda key: (query.get(key) or [""])[0]  # noqa: E731
        client = self.state.clients.get(get("client_id"))
        redirect = get("redirect_uri")
        if client is None or redirect not in client["redirect_uris"] or get("code_challenge_method") != "S256":
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
        return {"access_token": access, "refresh_token": refresh, "expires_in": self.state.token_lifetime, "token_type": "Bearer", "scope": "profile email offline_access"}

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

    # -- MCP -------------------------------------------------------------

    def _mcp(self, body: bytes) -> None:
        if not self._authorized():
            self._send(401, b'{"error":"unauthorized"}', "application/json", {"WWW-Authenticate": 'Bearer resource_metadata="x"'})
            return
        try:
            message = json.loads(body)
        except ValueError:
            self._json(400, {"error": "bad json"})
            return
        session = self.headers.get("Mcp-Session-Id") or ""
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            headers = {}
            if self.state.issue_sessions:
                session = "sess_" + secrets.token_hex(6)
                self.state.sessions.add(session)
                headers["Mcp-Session-Id"] = session
            self._rpc_reply(
                request_id,
                {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake-scenario-mcp", "version": "0.34.0"}, "instructions": "Fake Scenario MCP for tests."},
                headers=headers,
            )
            return
        if request_id is None:
            self._send(202)
            return
        if self.state.issue_sessions and session not in self.state.sessions:
            self._send(404, b'{"error":"session not found"}')
            return
        if method == "tools/list":
            self._rpc_reply(
                request_id,
                {
                    "tools": [
                        {"name": n, "inputSchema": {"type": "object"}}
                        for n in (
                            "teams_list",
                            "models_list",
                            "model_schema_get",
                            "model_run",
                            "job_get",
                            "jobs_wait",
                            "jobs_list",
                            "asset_get",
                            "asset_download",
                            "upload_asset",
                            "upload_asset_complete",
                            "recommend",
                        )
                    ]
                },
            )
            return
        if method != "tools/call":
            self._rpc_reply(request_id, error={"code": -32601, "message": "Method not found"})
            return
        params = message.get("params") or {}
        tool = params.get("name")
        args = params.get("arguments") or {}
        fault = self.state.take_fault(tool)
        with self.state.lock:
            self.state.calls.append({"tool": tool, "arguments": args, "time": time.time(), "fault": fault})
        if fault == "session_404":
            self.state.sessions.discard(session)
            self._send(404, b'{"error":"session not found"}')
            return
        if fault == "http401":
            self._send(401, b'{"error":"expired"}')
            return
        if fault == "http500":
            self._send(500, b'{"error":"boom"}')
            return
        if fault == "http429":
            self._send(429, b'{"error":"slow down"}', "application/json", {"Retry-After": "0"})
            return
        handler = getattr(self, "_tool_" + str(tool), None)
        if handler is None:
            self._tool_error(request_id, 404, {"reason": f"Unknown tool {tool}"})
            return
        if fault == "tool_error_400":
            self._tool_error(request_id, 400, {"reason": "Input prompt is required"})
            return
        if fault == "tool_error_500":
            self._tool_error(request_id, 500, {"reason": "Internal error"})
            return
        if fault == "tool_error_generic":
            self._rpc_reply(request_id, {"content": [{"type": "text", "text": "⚠ Scenario error (trace_id: mcpt_fake). For a diagnostic report, run diagnostics_run."}], "isError": True})
            return
        if fault == "moderation":
            self._tool_error(request_id, 400, {"reason": "Prompt flagged by moderation"})
            return
        try:
            result = handler(args)
        except ToolFailure as failure:
            self._tool_error(request_id, failure.status, failure.body)
            return
        if fault == "drop":
            self.close_connection = True
            self.connection.close()
            return
        self._rpc_reply(request_id, {"content": [{"type": "text", "text": json.dumps(result)}], "structuredContent": result, "_meta": {"scenario.com/trace_id": "mcpt_fake"}})

    def _tool_error(self, request_id, status: int, body: dict) -> None:
        self._rpc_reply(
            request_id,
            {
                "content": [
                    {"type": "text", "text": "⚠ Scenario error (trace_id: mcpt_fake). For a diagnostic report, run diagnostics_run."},
                    {"type": "text", "text": f"Error: {status} {json.dumps(body)}"},
                ],
                "isError": True,
                "_meta": {"scenario.com/trace_id": "mcpt_fake"},
            },
        )

    # -- tools -----------------------------------------------------------

    def _tool_teams_list(self, args):
        return {"teams": [dict(TEAM, projects=[dict(PROJECT)])]}

    def _tool_projects_list(self, args):
        return {"projects": [dict(PROJECT)]}

    def _tool_models_list(self, args):
        data = _load_fixture("models_list.json")
        filters = args.get("filters") or {}
        if filters.get("modality") == "image" and filters.get("privacy") == "public":
            data["models"] = data["models"] + [IMAGE_MODEL]
        if filters.get("modality") == "3d" and filters.get("privacy") == "public":
            data["models"] = data["models"] + [THREE_D_MODEL, IMAGE_TO_3D_MODEL] + [dict(row) for row in EDIT_ROWS]
        return data

    def _tool_model_schema_get(self, args):
        name = f"schema_{args.get('model_id')}.json"
        path = os.path.join(FIXTURES, name)
        if not os.path.exists(path):
            return {"model_id": args.get("model_id"), "name": "Test model", "capabilities": ["txt2img"], "parameters": [{"name": "prompt", "type": "string", "required": True, "prompt": True}]}
        return _load_fixture(name)

    def _tool_recommend(self, args):
        return {"next_step": {"type": "proceed"}, "ranked": [{"model_id": "model_meshy-7-1-txt23d", "name": "Meshy 7.1 - Text-to-3D", "rank": 1}]}

    def _tool_model_run(self, args):
        model_id = args.get("model_id")
        cost = PRICES.get(model_id, 10)
        if model_id in IMAGE_INPUT_MODELS:
            # Like the hosted service, a run checks its required image: it must be an uploaded asset.
            given = (args.get("parameters") or {}).get("image")
            ids = given if isinstance(given, list) else [given] if given else []
            if not ids or any(asset_id not in self.state.assets for asset_id in ids):
                raise ToolFailure(400, {"error": "image: Asset not found or not an uploaded image."})
        if model_id in EDIT_MODELS:
            field = EDIT_MODELS[model_id][1]
            given = (args.get("parameters") or {}).get(field)
            asset = self.state.assets.get(given) if isinstance(given, str) else None
            if asset is None or asset.get("kind") != "3d":
                raise ToolFailure(400, {"error": f"{field}: Asset not found or not an uploaded 3D model."})
        if args.get("dry_run"):
            return {"dry_run": True, "model_id": model_id, "job": {}, "creativeUnitsCost": cost, "creativeUnitsDiscount": 0}
        job_id = "job_fake" + secrets.token_hex(8)
        asset_id = "asset_fake" + secrets.token_hex(8)
        if model_id in THREE_D_MODELS:
            return self._run_3d(model_id, job_id, cost)
        if model_id in EDIT_MODELS:
            task, field, side, _name = EDIT_MODELS[model_id]
            source = self.state.files[self.state.assets[args["parameters"][field]]["file"]]
            glb, triangles, dims = _edited_glb(task, side, source)
            return self._run_3d(model_id, job_id, cost, glb=glb, meta={"kind": "3d", "faceCount": triangles, "dimensions": dims})
        with self.state.lock:
            self.state.jobs[job_id] = {
                "jobId": job_id,
                "jobType": "custom",
                "status": "queued",
                "progress": 0,
                "modelId": model_id,
                "assetIds": [],
                "cuCost": cost,
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "polls": 0,
                "result_assets": [asset_id],
            }
            self.state.files[asset_id + ".png"] = _png()
            self.state.assets[asset_id] = {"id": asset_id, "mimeType": "image/png", "kind": "image", "file": asset_id + ".png"}
        return {"model_id": model_id, "job_id": job_id, "status": "queued"}

    def _run_3d(self, model_id: str, job_id: str, cost, glb: bytes = b"", meta: dict | None = None) -> dict:
        """Like the hosted service: a GLB, its OBJ and MTL siblings and a texture. The OBJ comes
        first here (the service lists the GLB first) so tests prove the pick is by format."""
        data = glb or _glb()
        glb, obj, mtl, png = ("asset_fake" + secrets.token_hex(8) for _ in range(4))
        meta = meta or {"kind": "3d", "faceCount": 2, "dimensions": [1.0, 1.0, 0.0]}
        with self.state.lock:
            self.state.jobs[job_id] = {
                "jobId": job_id,
                "jobType": "custom",
                "status": "queued",
                "progress": 0,
                "modelId": model_id,
                "assetIds": [],
                "cuCost": cost,
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "polls": 0,
                "result_assets": [obj, glb, mtl, png],
            }
            self.state.files[glb + ".glb"] = data
            self.state.files[glb + "_thumb.png"] = _png(16, 16, (90, 160, 90))
            self.state.files[obj + ".obj"] = b"v 0 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 3\n"
            self.state.files[mtl + ".mtl"] = b"newmtl m\n"
            self.state.files[png + ".png"] = _png()
            self.state.assets[glb] = {"id": glb, "mimeType": "model/gltf-binary", "kind": "3d", "file": glb + ".glb", "metadata": dict(meta, format="glb"), "thumbnail": glb + "_thumb.png"}
            self.state.assets[obj] = {"id": obj, "mimeType": "model/obj", "kind": "3d", "file": obj + ".obj", "metadata": dict(meta, format="obj", parentId=glb)}
            self.state.assets[mtl] = {"id": mtl, "mimeType": "model/mtl", "kind": "3d", "file": mtl + ".mtl", "metadata": {"type": "3d-texture-mtl", "parentId": glb}}
            self.state.assets[png] = {"id": png, "mimeType": "image/png", "kind": "image", "file": png + ".png", "metadata": {"type": "3d-texture-albedo", "parentId": glb}}
        return {"model_id": model_id, "job_id": job_id, "status": "queued"}

    def _job_row(self, job_id: str, advance: bool = True) -> dict:
        with self.state.lock:
            job = self.state.jobs.get(job_id)
            if job is None:
                return {}
            if advance and job["status"] not in ("success", "failure"):
                job["polls"] += 1
                if job["polls"] >= self.state.polls_to_finish:
                    job["status"] = "success"
                    job["progress"] = 1
                    job["assetIds"] = list(job["result_assets"])
                else:
                    job["status"] = "in-progress"
                    job["progress"] = 0.5
            return {k: v for k, v in job.items() if k not in ("polls", "result_assets")}

    def _tool_job_get(self, args):
        row = self._job_row(args.get("job_id", ""))
        return {"job": row} if row else {}

    def _tool_jobs_wait(self, args):
        rows = [self._job_row(j) for j in args.get("job_ids") or []]
        pending = [r["jobId"] for r in rows if r and r["status"] not in ("success", "failure")]
        return {"status": "in_progress" if pending else "completed", "jobs": rows, "pending_job_ids": pending}

    def _tool_jobs_list(self, args):
        with self.state.lock:
            rows = [{k: v for k, v in job.items() if k not in ("polls", "result_assets")} for job in self.state.jobs.values()]
        rows.sort(key=lambda r: r["createdAt"], reverse=True)
        return {"jobs": rows[: int(args.get("limit") or 20)]}

    def _tool_asset_get(self, args):
        asset = self.state.assets.get(args.get("asset_id"))
        if not asset:
            return {}
        out = {"id": asset["id"], "mimeType": asset["mimeType"], "kind": asset["kind"], "status": "success"}
        if asset.get("metadata"):
            out["metadata"] = dict(asset["metadata"])
        if asset.get("thumbnail"):
            out["thumbnail"] = {"assetId": asset["id"] + "_thumb", "url": f"{self.base}/files/{asset['thumbnail']}"}
        return {"asset": out}

    def _tool_asset_download(self, args):
        asset = self.state.assets.get(args.get("asset_id"))
        if not asset:
            return {}
        return {"url": f"{self.base}/files/{asset['file']}", "mimeType": asset["mimeType"]}

    def _tool_upload_asset(self, args):
        upload_id = "upl_fake" + secrets.token_hex(6)
        size = int(args.get("file_size") or 0)
        part_size = self.state.upload_part_size
        count = max(1, -(-size // part_size))
        with self.state.lock:
            self.state.uploads[upload_id] = {"parts": {}, "name": args.get("file_name"), "kind": args.get("kind"), "size": size, "content_type": args.get("content_type")}
        parts = [
            {"part_number": n, "upload_url": f"{self.base}/upload/{upload_id}?partNumber={n}&x-amz-checksum-crc32=AAAAAA%3D%3D", "content_length": min(part_size, size - (n - 1) * part_size)}
            for n in range(1, count + 1)
        ]
        return {"upload_id": upload_id, "parts": parts, "part_size": part_size, "total_parts": count}

    def _tool_upload_asset_complete(self, args):
        upload = self.state.uploads.get(args.get("upload_id"))
        if upload is None:
            return {"status": "failed"}
        data = b"".join(upload["parts"][n] for n in sorted(upload["parts"]))
        if len(data) != upload["size"]:
            return {"status": "failed", "message": f"received {len(data)} of {upload['size']} bytes"}
        asset_id = "asset_up" + secrets.token_hex(8)
        with self.state.lock:
            upload["data"] = data
            self.state.files[asset_id] = data
            self.state.assets[asset_id] = {"id": asset_id, "mimeType": upload["content_type"] or "application/octet-stream", "kind": upload["kind"], "file": asset_id}
        return {"asset_id": asset_id, "status": "imported"}


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
        return self.base + "/mcp"

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
