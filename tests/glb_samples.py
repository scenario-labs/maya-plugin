"""Small GLB files written by hand for the importer tests (no third-party samples in the repository)."""

from __future__ import annotations

import json
import math
import struct
import zlib

COMPONENT_CODES = {5121: "B", 5123: "H", 5125: "I", 5126: "f"}
WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def png_bytes(width: int = 4, height: int = 4, rgb=(200, 120, 40)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class Writer:
    def __init__(self, generator: str = "scenario-maya tests") -> None:
        self.binary = bytearray()
        self.doc: dict = {"asset": {"version": "2.0", "generator": generator}, "buffers": [{}], "bufferViews": [], "accessors": []}

    def _view(self, data: bytes) -> int:
        self.binary += b"\x00" * (-len(self.binary) % 4)
        self.doc["bufferViews"].append({"buffer": 0, "byteOffset": len(self.binary), "byteLength": len(data)})
        self.binary += data
        return len(self.doc["bufferViews"]) - 1

    def accessor(self, kind: str, values: list, component: int = 5126, bounds: bool = False) -> int:
        flat = [value for row in values for value in (row if isinstance(row, (list, tuple)) else (row,))]
        data = struct.pack("<" + COMPONENT_CODES[component] * len(flat), *flat)
        spec = {"bufferView": self._view(data), "componentType": component, "count": len(values), "type": kind}
        if bounds:
            width = WIDTHS[kind]
            spec["min"] = [min(flat[i::width]) for i in range(width)]
            spec["max"] = [max(flat[i::width]) for i in range(width)]
        self.doc["accessors"].append(spec)
        return len(self.doc["accessors"]) - 1

    def image(self, data: bytes, mime: str = "image/png") -> int:
        self.doc.setdefault("images", []).append({"bufferView": self._view(data), "mimeType": mime})
        self.doc.setdefault("textures", []).append({"source": len(self.doc["images"]) - 1})
        return len(self.doc["textures"]) - 1

    def add(self, key: str, item: dict) -> int:
        self.doc.setdefault(key, []).append(item)
        return len(self.doc[key]) - 1

    def to_bytes(self) -> bytes:
        self.doc["buffers"][0]["byteLength"] = len(self.binary)
        text = json.dumps(self.doc).encode()
        text += b" " * (-len(text) % 4)
        binary = bytes(self.binary) + b"\x00" * (-len(self.binary) % 4)
        body = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(binary), 0x004E4942) + binary
        return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body

    def save(self, path: str) -> str:
        with open(path, "wb") as handle:
            handle.write(self.to_bytes())
        return path


def textured_quad(path: str) -> str:
    """A 1 m quad stored as two triangles with split corners (6 vertices), PBR textures, one material."""
    w = Writer()
    corners = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 0, 0), (1, 1, 0), (0, 1, 0)]
    uvs = [(0, 1), (1, 1), (1, 0), (0, 1), (1, 0), (0, 0)]
    position = w.accessor("VEC3", corners, bounds=True)
    normal = w.accessor("VEC3", [(0, 0, 1)] * 6)
    uv = w.accessor("VEC2", uvs)
    indices = w.accessor("SCALAR", list(range(6)), component=5123)
    base = w.image(png_bytes(rgb=(200, 120, 40)))
    packed = w.image(png_bytes(rgb=(255, 128, 0)))
    normal_map = w.image(png_bytes(rgb=(128, 128, 255)))
    w.add(
        "materials",
        {
            "name": "Crate Wood",
            "pbrMetallicRoughness": {"baseColorTexture": {"index": base}, "metallicRoughnessTexture": {"index": packed}, "metallicFactor": 1.0, "roughnessFactor": 0.5},
            "normalTexture": {"index": normal_map, "scale": 1.0},
        },
    )
    w.add("meshes", {"name": "quad", "primitives": [{"attributes": {"POSITION": position, "NORMAL": normal, "TEXCOORD_0": uv}, "indices": indices, "material": 0}]})
    w.add("nodes", {"name": "Quad", "mesh": 0, "translation": [0, 0.5, 0]})
    w.add("scenes", {"nodes": [0]})
    return w.save(path)


def quaternion(axis, degrees) -> list:
    half = math.radians(degrees) / 2.0
    x, y, z = axis
    return [x * math.sin(half), y * math.sin(half), z * math.sin(half), math.cos(half)]


REST = quaternion((1, 0, 0), 30)
KEY = [0.2, 0.3, 0.5, math.sqrt(1 - 0.2**2 - 0.3**2 - 0.5**2)]


def skinned_strip(path: str) -> str:
    """Two joints (the child with a 30 degree rest rotation), a 2 m strip bound to them, one rotation clip."""
    w = Writer()
    points = [(-0.1, 0, 0), (0.1, 0, 0), (-0.1, 1, 0), (0.1, 1, 0), (-0.1, 2, 0), (0.1, 2, 0)]
    position = w.accessor("VEC3", points, bounds=True)
    indices = w.accessor("SCALAR", [0, 1, 3, 0, 3, 2, 2, 3, 5, 2, 5, 4], component=5123)
    joints = w.accessor("VEC4", [(0, 0, 0, 0)] * 2 + [(1, 0, 0, 0)] * 4, component=5121)
    weights = w.accessor("VEC4", [(1, 0, 0, 0)] * 6)
    # Inverse bind matrices: joint 0 at the origin; joint 1 at 1 m, turned by REST (column-major, as glTF stores them).
    inverse = _invert_rigid(_matrix(REST, (0, 1, 0)))
    binds = w.accessor("MAT4", [_identity(), inverse])
    times = w.accessor("SCALAR", [0.0, 1.0])
    rotations = w.accessor("VEC4", [REST, KEY])
    w.add("meshes", {"name": "strip", "primitives": [{"attributes": {"POSITION": position, "JOINTS_0": joints, "WEIGHTS_0": weights}, "indices": indices}]})
    w.add("nodes", {"name": "Strip", "mesh": 0, "skin": 0, "translation": [5, 5, 5]})
    w.add("nodes", {"name": "Hips", "children": [2]})
    w.add("nodes", {"name": "Spine", "translation": [0, 1, 0], "rotation": REST})
    w.add("skins", {"joints": [1, 2], "inverseBindMatrices": binds})
    w.add("animations", {"name": "Bend", "samplers": [{"input": times, "output": rotations}], "channels": [{"sampler": 0, "target": {"node": 2, "path": "rotation"}}]})
    w.add("animations", {"name": "Idle", "samplers": [{"input": times, "output": rotations}], "channels": [{"sampler": 0, "target": {"node": 2, "path": "rotation"}}]})
    w.add("scenes", {"nodes": [0, 1]})
    return w.save(path)


def morph_quad(path: str) -> str:
    """A quad with one morph target lifting a corner by 0.5 m, its weight keyed from 0 to 1."""
    w = Writer()
    position = w.accessor("VEC3", [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], bounds=True)
    indices = w.accessor("SCALAR", [0, 1, 2, 0, 2, 3], component=5123)
    lift = w.accessor("VEC3", [(0, 0, 0), (0, 0, 0), (0, 0, 0.5), (0, 0, 0)], bounds=True)
    times = w.accessor("SCALAR", [0.0, 1.0])
    values = w.accessor("SCALAR", [0.0, 1.0])
    w.add(
        "meshes", {"name": "flag", "primitives": [{"attributes": {"POSITION": position}, "indices": indices, "targets": [{"POSITION": lift}]}], "weights": [0.0], "extras": {"targetNames": ["Lift"]}}
    )
    w.add("nodes", {"name": "Flag", "mesh": 0})
    w.add("animations", {"samplers": [{"input": times, "output": values}], "channels": [{"sampler": 0, "target": {"node": 0, "path": "weights"}}]})
    w.add("scenes", {"nodes": [0]})
    return w.save(path)


def moving_quad(path: str) -> str:
    """A 0.5 m quad whose node moves from the origin to (2, 1, 0) m in one second."""
    w = Writer()
    position = w.accessor("VEC3", [(0, 0, 0), (0.5, 0, 0), (0.5, 0.5, 0), (0, 0.5, 0)], bounds=True)
    indices = w.accessor("SCALAR", [0, 1, 2, 0, 2, 3], component=5123)
    times = w.accessor("SCALAR", [0.0, 1.0])
    moves = w.accessor("VEC3", [(0, 0, 0), (2, 1, 0)])
    w.add("meshes", {"name": "tile", "primitives": [{"attributes": {"POSITION": position}, "indices": indices}]})
    w.add("nodes", {"name": "Mover", "mesh": 0})
    w.add("animations", {"samplers": [{"input": times, "output": moves}], "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}]})
    w.add("scenes", {"nodes": [0]})
    return w.save(path)


def apply(m, point) -> tuple:
    """A column-major matrix applied to a point."""
    x, y, z = point
    return (m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14])


def _identity() -> list:
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _matrix(q, t) -> list:
    """Column-major 4x4 of rotation ``q`` (x, y, z, w) then translation ``t``."""
    x, y, z, w = q
    r = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    return [r[0][0], r[1][0], r[2][0], 0, r[0][1], r[1][1], r[2][1], 0, r[0][2], r[1][2], r[2][2], 0, t[0], t[1], t[2], 1]


def _invert_rigid(m) -> list:
    """Inverse of a column-major rotation plus translation."""
    r = [[m[0], m[4], m[8]], [m[1], m[5], m[9]], [m[2], m[6], m[10]]]
    t = [m[12], m[13], m[14]]
    rt = [[r[j][i] for j in range(3)] for i in range(3)]
    tt = [-sum(rt[i][k] * t[k] for k in range(3)) for i in range(3)]
    return [rt[0][0], rt[1][0], rt[2][0], 0, rt[0][1], rt[1][1], rt[2][1], 0, rt[0][2], rt[1][2], rt[2][2], 0, tt[0], tt[1], tt[2], 1]
