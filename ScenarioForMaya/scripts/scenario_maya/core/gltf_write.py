"""Writing GLB files without Maya (spec 6.3): the inverse of ``gltf.py``.

The Maya side (``maya/mesh_export.py``) reads meshes into flat arrays; this
module packs them into one GLB: a node and a mesh per input, a primitive per
material, positions in metres with their bounds, normals, one UV set (glTF's
V points down), and base colour textures embedded as PNG or JPEG. Names are
whatever the caller passes; the plug-in passes neutral ones (spec 7.5).
"""

from __future__ import annotations

import array
import hashlib
import json
import struct
import sys
from dataclasses import dataclass, field

_LITTLE = sys.byteorder == "little"
FLOAT, USHORT, UINT = 5126, 5123, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963


@dataclass
class Primitive:
    indices: list  # triangle corners, three per triangle, into the mesh's vertex arrays
    material: int | None = None


@dataclass
class MeshPart:
    name: str
    positions: list  # x, y, z per vertex, metres
    primitives: list
    normals: list | None = None  # x, y, z per vertex
    uvs: list | None = None  # u, v per vertex, glTF convention
    matrix: list | None = None  # the node's column-major 4x4, metres; identity when None


@dataclass
class MaterialPart:
    name: str
    base_color: tuple = (0.8, 0.8, 0.8, 1.0)
    metallic: float = 0.0
    roughness: float = 0.5
    image: bytes = b""  # base colour texture, PNG or JPEG bytes
    image_mime: str = ""
    double_sided: bool = False


@dataclass
class _Builder:
    generator: str
    binary: bytearray = field(default_factory=bytearray)
    doc: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.doc = {
            "asset": {"version": "2.0", "generator": self.generator},
            "scenes": [{"nodes": []}],
            "scene": 0,
            "nodes": [],
            "meshes": [],
            "buffers": [{"byteLength": 0}],
            "bufferViews": [],
            "accessors": [],
        }

    def view(self, data: bytes, target: int | None = None) -> int:
        self.binary += b"\x00" * (-len(self.binary) % 4)
        spec = {"buffer": 0, "byteOffset": len(self.binary), "byteLength": len(data)}
        if target:
            spec["target"] = target
        self.doc["bufferViews"].append(spec)
        self.binary += data
        return len(self.doc["bufferViews"]) - 1

    def accessor(self, values: array.array, component: int, kind: str, width: int, target: int | None = None, bounds: bool = False) -> int:
        data = values if _LITTLE else _swapped(values)
        spec = {"bufferView": self.view(data.tobytes(), target), "componentType": component, "count": len(values) // width, "type": kind}
        if bounds and len(values):
            spec["min"] = [min(values[i::width]) for i in range(width)]
            spec["max"] = [max(values[i::width]) for i in range(width)]
        self.doc["accessors"].append(spec)
        return len(self.doc["accessors"]) - 1


def to_bytes(meshes: list, materials: list | None = None, generator: str = "Scenario for Maya") -> bytes:
    """One GLB holding every mesh as a root node of the scene."""
    builder = _Builder(generator)
    doc = builder.doc
    for material in materials or []:
        doc.setdefault("materials", []).append(_material(builder, material))
    for mesh in meshes:
        count = len(mesh.positions) // 3
        if count * 3 != len(mesh.positions) or not count:
            raise ValueError(f"{mesh.name}: positions must be x, y, z triples")
        attributes = {"POSITION": builder.accessor(array.array("f", mesh.positions), FLOAT, "VEC3", 3, ARRAY_BUFFER, bounds=True)}
        if mesh.normals is not None:
            if len(mesh.normals) != count * 3:
                raise ValueError(f"{mesh.name}: one normal per vertex")
            attributes["NORMAL"] = builder.accessor(array.array("f", mesh.normals), FLOAT, "VEC3", 3, ARRAY_BUFFER)
        if mesh.uvs is not None:
            if len(mesh.uvs) != count * 2:
                raise ValueError(f"{mesh.name}: one UV per vertex")
            attributes["TEXCOORD_0"] = builder.accessor(array.array("f", mesh.uvs), FLOAT, "VEC2", 2, ARRAY_BUFFER)
        primitives = []
        for primitive in mesh.primitives:
            if not primitive.indices:
                continue
            if len(primitive.indices) % 3 or max(primitive.indices) >= count:
                raise ValueError(f"{mesh.name}: triangle indices out of range")
            wide = count > 65535
            indices = array.array(_uint32_code() if wide else "H", primitive.indices)
            spec = {"attributes": attributes, "indices": builder.accessor(indices, UINT if wide else USHORT, "SCALAR", 1, ELEMENT_ARRAY_BUFFER), "mode": 4}
            if primitive.material is not None:
                spec["material"] = primitive.material
            primitives.append(spec)
        if not primitives:
            raise ValueError(f"{mesh.name}: no triangles")
        doc["meshes"].append({"name": mesh.name, "primitives": primitives})
        node = {"name": mesh.name, "mesh": len(doc["meshes"]) - 1}
        if mesh.matrix is not None and list(mesh.matrix) != _IDENTITY:
            node["matrix"] = [float(value) for value in mesh.matrix]
        doc["nodes"].append(node)
        doc["scenes"][0]["nodes"].append(len(doc["nodes"]) - 1)
    binary = bytes(builder.binary) + b"\x00" * (-len(builder.binary) % 4)
    doc["buffers"][0]["byteLength"] = len(binary)
    text = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(binary), 0x004E4942) + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def write(path: str, meshes: list, materials: list | None = None, generator: str = "Scenario for Maya") -> dict:
    """Writes the GLB and returns ``{path, size, sha256}``."""
    data = to_bytes(meshes, materials, generator)
    with open(path, "wb") as handle:
        handle.write(data)
    return {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _material(builder: _Builder, material: MaterialPart) -> dict:
    pbr = {"baseColorFactor": [float(value) for value in material.base_color], "metallicFactor": float(material.metallic), "roughnessFactor": float(material.roughness)}
    if material.image:
        doc = builder.doc
        doc.setdefault("images", []).append({"bufferView": builder.view(material.image), "mimeType": material.image_mime or "image/png"})
        doc.setdefault("samplers", [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}])
        doc.setdefault("textures", []).append({"source": len(doc["images"]) - 1, "sampler": 0})
        pbr["baseColorTexture"] = {"index": len(doc["textures"]) - 1}
    spec = {"name": material.name, "pbrMetallicRoughness": pbr}
    if material.double_sided:
        spec["doubleSided"] = True
    return spec


_IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _swapped(values: array.array) -> array.array:
    copy = array.array(values.typecode, values)
    copy.byteswap()
    return copy


def _uint32_code() -> str:
    return "I" if array.array("I").itemsize == 4 else "L"
