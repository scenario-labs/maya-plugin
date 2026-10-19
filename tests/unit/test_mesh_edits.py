"""The GLB writer and the edit checks made before a mesh is sent (spec 6.3), on plain Python (0 CU)."""

import pytest

from scenario_maya.core import edits, gltf, gltf_write
from tests.glb_samples import png_bytes


def quad(name="scn_input_0", material=0):
    return gltf_write.MeshPart(
        name,
        positions=[0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0],
        primitives=[gltf_write.Primitive([0, 1, 2, 0, 2, 3], material)],
        normals=[0, 0, 1] * 4,
        uvs=[0, 1, 1, 1, 1, 0, 0, 0],
    )


def test_written_glb_reads_back_with_the_plugins_reader():
    texture = png_bytes(rgb=(10, 200, 30))
    materials = [gltf_write.MaterialPart("scn_material_0", metallic=0.25, roughness=0.75, image=texture, image_mime="image/png")]
    moved = quad("scn_input_1", None)
    moved.matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 0, 0, 1]
    data = gltf_write.to_bytes([quad(), moved], materials)
    doc = gltf.Document.parse(data)
    assert doc.summary()["meshes"] == 2 and doc.summary()["triangles"] == 4 and doc.summary()["textures"] == 1
    primitive = doc.json["meshes"][0]["primitives"][0]
    position = doc.accessor(primitive["attributes"]["POSITION"])
    assert list(position.values) == [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0] and position.min == [0, 0, 0] and position.max == [1, 1, 0]
    assert list(doc.accessor(primitive["attributes"]["TEXCOORD_0"]).values) == [0, 1, 1, 1, 1, 0, 0, 0]
    assert list(doc.accessor(primitive["indices"]).values) == [0, 1, 2, 0, 2, 3]
    assert doc.json["accessors"][primitive["indices"]]["componentType"] == gltf_write.USHORT
    assert doc.image_bytes(0) == (texture, "image/png") and gltf.texture_roles(doc) == {0: "base_color"}
    pbr = doc.json["materials"][0]["pbrMetallicRoughness"]
    assert (pbr["metallicFactor"], pbr["roughnessFactor"]) == (0.25, 0.75)
    assert "matrix" not in doc.json["nodes"][0] and doc.json["nodes"][1]["matrix"][12] == 2
    assert "material" not in doc.json["meshes"][1]["primitives"][0]
    assert [node["name"] for node in doc.json["nodes"]] == ["scn_input_0", "scn_input_1"]


def test_large_meshes_use_32_bit_indices():
    count = 70000
    positions = [float(i % 7) for i in range(count * 3)]
    mesh = gltf_write.MeshPart("big", positions, [gltf_write.Primitive([0, 1, count - 1])])
    doc = gltf.Document.parse(gltf_write.to_bytes([mesh]))
    indices = doc.json["meshes"][0]["primitives"][0]["indices"]
    assert doc.json["accessors"][indices]["componentType"] == gltf_write.UINT
    assert list(doc.accessor(indices).values) == [0, 1, count - 1]


def test_bad_arrays_are_refused():
    with pytest.raises(ValueError, match="triples"):
        gltf_write.to_bytes([gltf_write.MeshPart("a", [0, 0], [gltf_write.Primitive([0, 0, 0])])])
    with pytest.raises(ValueError, match="out of range"):
        gltf_write.to_bytes([gltf_write.MeshPart("a", [0, 0, 0], [gltf_write.Primitive([0, 0, 1])])])
    with pytest.raises(ValueError, match="one UV per vertex"):
        gltf_write.to_bytes([gltf_write.MeshPart("a", [0, 0, 0], [gltf_write.Primitive([0, 0, 0])], uvs=[0])])


def test_checks_refuse_before_upload():
    capture = {"format": "glb", "triangles": 52310}
    assert edits.check("model_meshy-uv-unwrap", "Meshy UV Unwrap", capture) == ["Meshy UV Unwrap takes up to 44,000 triangles; the selection has 52,310. Remesh it first."]
    assert edits.check("model_tripo-smart-uv", "Tripo Smart UV", capture) == []
    assert edits.check("model_tencent-texture-edit", "Hunyuan Texture Edit", {"format": "glb", "triangles": 10}) == ["Hunyuan Texture Edit takes FBX only; the plug-in sends GLB."]
    assert edits.check("model_unknown", "Other", capture) == [], "models outside the table are left to Scenario"


def test_tasks_and_defaults():
    assert [task.label for task in edits.TASKS] == ["Remesh", "UV unwrap", "Retexture"]
    for task in edits.TASKS:
        assert all(edits.MODELS[model].task == task.id for model in task.quick_picks)
    assert edits.task_for_model("model_meshy-7-retexture").apply_mode == "RETEXTURE"
    assert edits.BY_TASK["retexture"].needs_prompt and not edits.BY_TASK["uv"].needs_prompt


def test_fingerprint_follows_every_value():
    points, counts, connects = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0], [3], [0, 1, 2]
    first = edits.fingerprint(points, counts, connects)
    assert first == edits.fingerprint(list(points), list(counts), list(connects))
    assert first != edits.fingerprint([*points[:-1], 1e-7], counts, connects)
    assert first != edits.fingerprint(points, counts, [0, 2, 1]), "a rotated face changes it"


def test_the_fake_servers_edit_replies_match_like_the_live_ones():
    """The fake answers like the live models did: a UV or retexture result is the sent surface, a remesh is the same shape with other triangles."""
    from scenario_maya.core import topology
    from tests.fake_backend.fake_scenario import _edited_glb

    box = gltf_write.MeshPart(
        "scn_input_0",
        positions=[0, 0, 0, 0.4, 0, 0, 0.4, 0.3, 0, 0, 0.3, 0, 0, 0, 0.2, 0.4, 0, 0.2, 0.4, 0.3, 0.2, 0, 0.3, 0.2],
        primitives=[gltf_write.Primitive([0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 3, 7, 6, 3, 6, 2, 0, 4, 7, 0, 7, 3, 1, 2, 6, 1, 6, 5])],
        uvs=[0.1 * k for k in range(16)],
    )
    sent = gltf_write.to_bytes([box])
    sent_mesh = topology.result_from_document(gltf.Document.parse(sent))
    target = topology.Target(sent_mesh.points, [3] * len(sent_mesh.triangles), [v for t in sent_mesh.triangles for v in t])
    for task, side in (("uv", 1.0), ("retexture", 2.0), ("remesh", 1.0)):
        data, triangles, dims = _edited_glb(task, side, sent)
        result = topology.result_from_document(gltf.Document.parse(data))
        found = topology.match(target, result)
        assert max(dims) == pytest.approx(side)
        if task == "remesh":
            assert not found.same_surface and triangles == 48
            assert topology.verify_fit(result, sent_mesh, found.scale, found.offset)["verified"]
            continue
        assert found.same_surface and found.scale == pytest.approx(0.4 / side), found.reason
        kept = [(round(u, 6), round(1 - v, 6)) for u, v in sent_mesh.uvs]
        assert ([tuple(round(c, 6) for c in uv) for uv in found.corner_uvs] == [kept[v] for t in sent_mesh.triangles for v in t]) == (task == "retexture")
    assert gltf.Document.parse(_edited_glb("retexture", 2.0, sent)[0]).summary()["textures"] == 1
