"""Reading GLB files without Maya (spec 6.7): the container, accessors and the
real format of any downloaded file.

Parsing runs on a worker; the Maya side (``maya/glb_builder.py``) only turns
the arrays into nodes on the main thread. Accessors come back as flat
``array.array`` values (fast ``frombytes`` when the data is tightly packed),
with ``count`` and ``components`` to index them.

Not handled (reported, never guessed): Draco and meshopt compression, KTX2
textures, external buffers.
"""

from __future__ import annotations

import array
import json
import struct
import sys
from dataclasses import dataclass

from . import errors

COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
NORMALIZED_DIVISOR = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}
UNSUPPORTED_EXTENSIONS = {
    "KHR_draco_mesh_compression": "Draco-compressed meshes",
    "EXT_meshopt_compression": "meshopt-compressed meshes",
    "KHR_texture_basisu": "KTX2 textures",
}
_LITTLE = sys.byteorder == "little"


def sniff_format(path: str) -> str:
    """The file's real format from its first bytes; a stored file's declared type can be wrong."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(64)
    except OSError:
        return "missing"
    if head.startswith(b"glTF"):
        return "glb"
    if head.startswith(b"Kaydara FBX Binary"):
        return "fbx"
    if head.startswith(b"; FBX") or b"FBXHeaderExtension" in head:
        return "fbx"
    if head.startswith(b"ply"):
        return "ply"
    if head.startswith(b"BLENDER"):
        return "blend"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"v/1\x01"):
        return "exr"
    if head.startswith(b"#?RADIANCE") or head.startswith(b"#?RGBE"):
        return "hdr"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head[:2] == b"\x1f\x8b":
        return "gzip"  # SPZ files are gzip-compressed
    if head.startswith(b"{") and b'"asset"' in head:
        return "gltf"
    text = head.lstrip()
    if text[:2] in (b"v ", b"o ", b"g ", b"# ", b"mt", b"vt", b"vn", b"f "):
        return "obj"
    return "unknown"


@dataclass
class Accessor:
    values: array.array
    count: int
    components: int
    min: list | None = None
    max: list | None = None

    def row(self, index: int) -> tuple:
        start = index * self.components
        return tuple(self.values[start : start + self.components])


class Document:
    """A parsed GLB: ``json`` is the glTF object, ``binary`` the BIN chunk."""

    def __init__(self, data: dict, binary: bytes) -> None:
        self.json = data
        self.binary = binary
        self._cache: dict = {}
        used = set(data.get("extensionsUsed") or []) | set(data.get("extensionsRequired") or [])
        self.unsupported = [UNSUPPORTED_EXTENSIONS[name] for name in sorted(used) if name in UNSUPPORTED_EXTENSIONS]

    @classmethod
    def load(cls, path: str) -> Document:
        with open(path, "rb") as handle:
            data = handle.read()
        return cls.parse(data)

    @classmethod
    def parse(cls, data: bytes) -> Document:
        if len(data) < 20 or data[:4] != b"glTF":
            raise errors.ProtocolError("Not a GLB file.")
        _magic, version, length = struct.unpack_from("<4sII", data, 0)
        if version != 2:
            raise errors.ProtocolError(f"GLB version {version} is not supported (2 is).")
        offset, document, binary = 12, None, b""
        while offset + 8 <= min(length, len(data)):
            chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
            chunk = data[offset + 8 : offset + 8 + chunk_length]
            if chunk_type == 0x4E4F534A:
                document = json.loads(chunk.decode("utf-8"))
            elif chunk_type == 0x004E4942 and not binary:
                binary = bytes(chunk)
            offset += 8 + chunk_length  # chunk lengths include their padding to 4 bytes
        if not isinstance(document, dict):
            raise errors.ProtocolError("The GLB file has no JSON chunk.")
        return cls(document, binary)

    # -- raw data ----------------------------------------------------------

    def view(self, index: int) -> tuple:
        """(bytes, stride) of a buffer view."""
        view = self.json["bufferViews"][index]
        buffer = self.json["buffers"][view.get("buffer", 0)]
        if buffer.get("uri"):
            raise errors.ProtocolError("External buffers are not supported in GLB results.")
        start = view.get("byteOffset", 0)
        return self.binary[start : start + view["byteLength"]], view.get("byteStride")

    def image_bytes(self, index: int) -> tuple:
        """(bytes, mime type) of an embedded image."""
        image = self.json["images"][index]
        if "bufferView" not in image:
            raise errors.ProtocolError("The GLB result references an external image.")
        raw, _stride = self.view(image["bufferView"])
        return bytes(raw), image.get("mimeType") or ""

    def accessor(self, index: int) -> Accessor:
        if index in self._cache:
            return self._cache[index]
        spec = self.json["accessors"][index]
        code, size = COMPONENT[spec["componentType"]]
        components = WIDTH[spec["type"]]
        count = spec["count"]
        values = array.array(code if code != "I" else _uint32_code())
        if "bufferView" in spec:
            raw, stride = self.view(spec["bufferView"])
            start = spec.get("byteOffset", 0)
            element = size * components
            stride = stride or element
            if stride == element:
                values.frombytes(raw[start : start + element * count])
            else:
                for row in range(count):
                    base = start + row * stride
                    values.frombytes(raw[base : base + element])
            if not _LITTLE:
                values.byteswap()
        else:
            values.extend([0] * (count * components))
        if "sparse" in spec:
            self._apply_sparse(values, spec["sparse"], components)
        if spec.get("normalized") and spec["componentType"] in NORMALIZED_DIVISOR:
            divisor = NORMALIZED_DIVISOR[spec["componentType"]]
            values = array.array("f", (max(item / divisor, -1.0) for item in values))
        result = Accessor(values, count, components, spec.get("min"), spec.get("max"))
        self._cache[index] = result
        return result

    def _apply_sparse(self, values: array.array, sparse: dict, components: int) -> None:
        indices_spec, values_spec = sparse["indices"], sparse["values"]
        count = sparse["count"]
        code, size = COMPONENT[indices_spec["componentType"]]
        raw, _stride = self.view(indices_spec["bufferView"])
        start = indices_spec.get("byteOffset", 0)
        indices = array.array(code if code != "I" else _uint32_code())
        indices.frombytes(raw[start : start + size * count])
        vcode, vsize = values.typecode, values.itemsize
        raw, _stride = self.view(values_spec["bufferView"])
        start = values_spec.get("byteOffset", 0)
        replacement = array.array(vcode)
        replacement.frombytes(raw[start : start + vsize * components * count])
        for row, target in enumerate(indices):
            values[target * components : (target + 1) * components] = replacement[row * components : (row + 1) * components]

    # -- summaries -----------------------------------------------------------

    def summary(self) -> dict:
        """Counts for the import checks (spec 6.7), from the JSON only."""
        data = self.json
        triangles = vertices = 0
        for mesh in data.get("meshes") or []:
            for primitive in mesh.get("primitives") or []:
                position = (primitive.get("attributes") or {}).get("POSITION")
                if position is not None:
                    vertices += data["accessors"][position]["count"]
                if primitive.get("mode", 4) == 4:
                    if "indices" in primitive:
                        triangles += data["accessors"][primitive["indices"]]["count"] // 3
                    elif position is not None:
                        triangles += data["accessors"][position]["count"] // 3
        joints = sorted({joint for skin in data.get("skins") or [] for joint in skin.get("joints") or []})
        return {
            "meshes": len(data.get("meshes") or []),
            "triangles": triangles,
            "vertices": vertices,
            "materials": len(data.get("materials") or []),
            "textures": len(data.get("images") or []),
            "joints": len(joints),
            "skins": len(data.get("skins") or []),
            "animations": [anim.get("name") or f"clip_{index + 1}" for index, anim in enumerate(data.get("animations") or [])],
            "morph_targets": sum(len(p.get("targets") or []) for m in data.get("meshes") or [] for p in m.get("primitives") or []),
            "unsupported": list(self.unsupported),
            "generator": (data.get("asset") or {}).get("generator") or "",
        }


def _uint32_code() -> str:
    """The array typecode whose items are 4 bytes and unsigned ("I" on every platform Maya runs on)."""
    return "I" if array.array("I").itemsize == 4 else "L"
