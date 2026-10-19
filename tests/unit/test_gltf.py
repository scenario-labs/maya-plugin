"""GLB parsing and format sniffing on plain Python (0 CU)."""

import json
import struct

import pytest

from scenario_maya.core import errors, gltf


def glb(document: dict, binary: bytes) -> bytes:
    text = json.dumps(document).encode()
    text += b" " * (-len(text) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(binary), 0x004E4942) + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def triangle_document():
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    indices = struct.pack("<3H", 0, 1, 2) + b"\x00\x00"
    # interleaved: uv (2 floats) + pad (1 float) per vertex -> stride 12
    interleaved = b"".join(struct.pack("<3f", u, v, 9.0) for u, v in ((0, 0), (1, 0), (0, 1)))
    colors = struct.pack("<12B", 255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255)
    sparse_indices = struct.pack("<H", 2) + b"\x00\x00"
    sparse_values = struct.pack("<3f", 5, 5, 5)
    binary = positions + indices + interleaved + colors + sparse_indices + sparse_values
    offsets = {}
    cursor = 0
    for name, chunk in (("pos", positions), ("idx", indices), ("uv", interleaved), ("col", colors), ("si", sparse_indices), ("sv", sparse_values)):
        offsets[name] = (cursor, len(chunk))
        cursor += len(chunk)
    views = [
        {"buffer": 0, "byteOffset": offsets["pos"][0], "byteLength": 36},
        {"buffer": 0, "byteOffset": offsets["idx"][0], "byteLength": 6},
        {"buffer": 0, "byteOffset": offsets["uv"][0], "byteLength": 36, "byteStride": 12},
        {"buffer": 0, "byteOffset": offsets["col"][0], "byteLength": 12},
        {"buffer": 0, "byteOffset": offsets["si"][0], "byteLength": 2},
        {"buffer": 0, "byteOffset": offsets["sv"][0], "byteLength": 12},
    ]
    document = {
        "asset": {"version": "2.0", "generator": "test"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
            {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": 3, "componentType": 5121, "count": 3, "type": "VEC4", "normalized": True},
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "sparse": {"count": 1, "indices": {"bufferView": 4, "componentType": 5123}, "values": {"bufferView": 5}}},
        ],
        "meshes": [{"name": "tri", "primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 2, "COLOR_0": 3}, "indices": 1}]}],
        "nodes": [{"mesh": 0, "name": "Triangle"}],
        "scenes": [{"nodes": [0]}],
    }
    return document, binary


def test_parse_accessors_tight_strided_normalized_and_sparse(tmp_path):
    document, binary = triangle_document()
    path = tmp_path / "tri.glb"
    path.write_bytes(glb(document, binary))
    doc = gltf.Document.load(str(path))
    positions = doc.accessor(0)
    assert positions.count == 3 and positions.components == 3 and positions.row(1) == (1.0, 0.0, 0.0)
    assert list(doc.accessor(1).values) == [0, 1, 2]
    assert [doc.accessor(2).row(i) for i in range(3)] == [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    assert doc.accessor(3).row(0) == pytest.approx((1.0, 0.0, 0.0, 1.0))
    assert doc.accessor(4).row(2) == (5.0, 5.0, 5.0) and doc.accessor(4).row(0) == (0.0, 0.0, 0.0)
    summary = doc.summary()
    assert summary["triangles"] == 1 and summary["vertices"] == 3 and summary["generator"] == "test"
    assert gltf.sniff_format(str(path)) == "glb"


def test_unsupported_compression_is_reported():
    document, binary = triangle_document()
    document["extensionsUsed"] = ["KHR_draco_mesh_compression", "KHR_materials_emissive_strength"]
    doc = gltf.Document.parse(glb(document, binary))
    assert doc.unsupported == ["Draco-compressed meshes"]


def test_not_a_glb_is_refused():
    with pytest.raises(errors.ProtocolError, match="Not a GLB"):
        gltf.Document.parse(b"Kaydara FBX Binary  \x00")


@pytest.mark.parametrize(
    "head,kind",
    [
        (b"Kaydara FBX Binary  \x00\x1a\x00", "fbx"),
        (b"ply\nformat binary_little_endian 1.0\n", "ply"),
        (b"BLENDER-v300", "blend"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"\xff\xd8\xff\xe0", "jpg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp"),
        (b"\x1f\x8b\x08\x00", "gzip"),
        (b"# Blender OBJ\nv 0 0 0\n", "obj"),
        (b"PK\x03\x04", "zip"),
        (b"\x00\x01\x02", "unknown"),
    ],
)
def test_sniff_format_by_header(tmp_path, head, kind):
    path = tmp_path / "file.bin"
    path.write_bytes(head)
    assert gltf.sniff_format(str(path)) == kind
    assert gltf.sniff_format(str(tmp_path / "missing.bin")) == "missing"
