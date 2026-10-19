"""Selected Maya meshes as a GLB for a 3D edit model (spec 6.3, 7.5). Main thread.

Maya has no GLB exporter, so the plug-in writes its own: each mesh in its
object space (pivots and transforms stay in Maya, recorded in the capture),
centimetres to metres, Y-up (a Z-up scene is turned like the importer turns
it back), triangulated with Maya's own triangulation, normals and the current
UV set per face-vertex, one material per shading group with its colour,
metalness, roughness and a base colour texture when one file node feeds it.
History and deformers are evaluated: what is sent is the mesh people see.

Node and material names leave the machine as ``scn_input_0`` and
``scn_material_0``; the record keeps the mapping locally. The record also
keeps what an apply needs to find the target again without its name or the
selection: UUIDs, the path, a fingerprint of geometry and UVs, the world
matrix.
"""

from __future__ import annotations

import os
import time

from maya import cmds
from maya.api import OpenMaya as om

from ..core import edits, gltf, gltf_write, naming
from . import capture

CM_TO_M = 0.01
COLOR_ATTRIBUTES = ("baseColor", "color", "diffuseColor")
METAL_ATTRIBUTES = ("baseMetalness", "metalness", "metallic")
ROUGH_ATTRIBUTES = ("specularRoughness", "roughness")
IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg"}


def selected_meshes() -> list:
    """Transforms of the selected meshes, long paths, in selection order; a face selection counts as its object."""
    out = []
    for item in cmds.ls(selection=True, long=True, flatten=False) or []:
        node = item.split(".")[0]
        if cmds.nodeType(node) == "mesh":
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        if mesh_shape(node) and node not in out:
            out.append(node)
    return out


def mesh_shape(transform: str) -> str:
    shapes = cmds.listRelatives(transform, shapes=True, type="mesh", noIntermediate=True, fullPath=True) or []
    return shapes[0] if shapes else ""


def face_count(transform: str) -> int:
    shape = mesh_shape(transform)
    return cmds.polyEvaluate(shape, face=True) if shape else 0


def triangle_count(transform: str) -> int:
    shape = mesh_shape(transform)
    return cmds.polyEvaluate(shape, triangle=True) if shape else 0


def export(transforms: list, folder: str = "", neutral: bool = True) -> dict:
    """Writes the meshes into one GLB and returns the capture record."""
    if not transforms:
        raise ValueError("Select a mesh to edit.")
    folder = folder or capture.captures_folder()
    os.makedirs(folder, exist_ok=True)
    up_z = cmds.upAxis(query=True, axis=True) == "z"
    parts, materials, records, notes = [], [], [], []
    material_index: dict = {}
    names: dict = {}
    for number, transform in enumerate(transforms):
        shape = mesh_shape(transform)
        if not shape:
            raise ValueError(f"{transform.split('|')[-1]} is not a mesh.")
        label = f"scn_input_{number}" if neutral else transform.split("|")[-1]
        names[label] = transform
        read = read_mesh(shape, up_z)
        notes.extend(read["notes"])
        primitives = []
        for engine, indices in read["groups"]:
            if engine not in material_index:
                part, found = material_for(engine, f"scn_material_{len(materials)}" if neutral else engine)
                notes.extend(found)
                material_index[engine] = len(materials)
                materials.append(part)
                names[part.name] = engine
            primitives.append(gltf_write.Primitive(indices, material_index[engine]))
        matrix = None
        if len(transforms) > 1:  # several meshes keep their arrangement; one mesh goes in its own space
            matrix = _gltf_matrix(cmds.xform(transform, query=True, matrix=True, worldSpace=True), up_z)
        parts.append(gltf_write.MeshPart(label, read["positions"], primitives, read["normals"], read["uvs"], matrix))
        records.append(
            {
                "node": transform,
                "uuid": cmds.ls(transform, uuid=True)[0],
                "shape": shape,
                "shape_uuid": cmds.ls(shape, uuid=True)[0],
                "name": label,
                "fingerprint": read["fingerprint"],
                "faces": read["faces"],
                "triangles": read["triangles"],
                "vertices": read["vertices"],
                "uv_set": read["uv_set"],
                "uv_sets": read["uv_sets"],
                "world_matrix": cmds.xform(transform, query=True, matrix=True, worldSpace=True),
                "shading_groups": [engine for engine, _indices in read["groups"]],
            }
        )
    base = "scn_input" if neutral else transforms[0].split("|")[-1]
    path = naming.unique_path(folder, f"{base}_{time.strftime('%Y%m%d_%H%M%S')}", ".glb")
    written = gltf_write.write(path, parts, materials)
    return {
        "path": path,
        "sha256": written["sha256"],
        "size": written["size"],
        "format": "glb",
        "meshes": records,
        "faces": sum(record["faces"] for record in records),
        "triangles": sum(record["triangles"] for record in records),
        "names": names,
        "up_axis": "z" if up_z else "y",
        "notes": list(dict.fromkeys(notes)),
    }


def read_mesh(shape: str, up_z: bool = False) -> dict:
    """The shape's evaluated mesh as glTF arrays: one vertex per distinct (point, normal, UV) corner."""
    selection = om.MSelectionList()
    selection.add(shape)
    dag = selection.getDagPath(0)
    fn = om.MFnMesh(dag)
    points = fn.getPoints(om.MSpace.kObject)  # centimetres whatever the scene unit
    counts, connects = fn.getVertices()
    _tri_counts, tri_offsets = fn.getTriangleOffsets()  # face-vertex offsets, three per triangle
    normals = fn.getNormals(om.MSpace.kObject)
    _normal_counts, normal_ids = fn.getNormalIds()
    uv_set = fn.currentUVSetName()
    uv_sets = list(fn.getUVSetNames())
    has_uvs = bool(uv_set) and fn.numUVs(uv_set) > 0
    us, vs = fn.getUVs(uv_set) if has_uvs else ([], [])
    uv_counts, uv_ids = fn.getAssignedUVs(uv_set) if has_uvs else ([], [])
    engines, face_engine = _shading(fn, dag)

    # Per face-vertex: the face it belongs to and its UV id (-1 on a face without UVs).
    corner_face, corner_uv = [], []
    uv_cursor = 0
    missing_uv_faces = 0
    for face, count in enumerate(counts):
        corner_face.extend([face] * count)
        if has_uvs and uv_counts[face]:
            corner_uv.extend(uv_ids[uv_cursor : uv_cursor + count])
            uv_cursor += count
        else:
            corner_uv.extend([-1] * count)
            missing_uv_faces += 1 if has_uvs else 0

    def axis(x, y, z):
        return (x, z, -y) if up_z else (x, y, z)

    positions, out_normals, out_uvs = [], [], []
    vertex_of: dict = {}
    groups: dict = {}
    for start in range(0, len(tri_offsets), 3):
        face = corner_face[tri_offsets[start]]
        target = groups.setdefault(face_engine[face], [])
        for corner in tri_offsets[start : start + 3]:
            key = (connects[corner], normal_ids[corner], corner_uv[corner])
            index = vertex_of.get(key)
            if index is None:
                index = len(vertex_of)
                vertex_of[key] = index
                point = points[key[0]]
                positions.extend(axis(point.x * CM_TO_M, point.y * CM_TO_M, point.z * CM_TO_M))
                normal = normals[key[1]]
                out_normals.extend(axis(normal.x, normal.y, normal.z))
                if has_uvs:
                    out_uvs.extend((us[key[2]], 1.0 - vs[key[2]]) if key[2] >= 0 else (0.0, 0.0))
            target.append(index)
    notes = []
    if missing_uv_faces:
        notes.append(f"{missing_uv_faces} face(s) of {shape.split('|')[-1]} have no UVs in {uv_set}")
    if not has_uvs:
        notes.append(f"{shape.split('|')[-1]} has no UVs: sent without them")
    flat_points = [value for point in points for value in (point.x, point.y, point.z)]
    flat_uvs = list(us) + list(vs)
    return {
        "positions": positions,
        "normals": out_normals,
        "uvs": out_uvs if has_uvs else None,
        "groups": [(engines[key] if key >= 0 else "", groups[key]) for key in sorted(groups)],
        "faces": len(counts),
        "triangles": len(tri_offsets) // 3,
        "vertices": len(points),
        "uv_set": uv_set if has_uvs else "",
        "uv_sets": uv_sets,
        "fingerprint": edits.fingerprint(flat_points, counts, connects, flat_uvs, uv_counts, uv_ids),
        "notes": notes,
    }


def shape_fingerprint(shape: str) -> str:
    """The same fingerprint ``read_mesh`` records, from the shape as it is now: any edit of points, faces or UVs changes it."""
    fn = _fn(shape)
    counts, connects = fn.getVertices()
    uv_set = fn.currentUVSetName()
    has_uvs = bool(uv_set) and fn.numUVs(uv_set) > 0
    us, vs = fn.getUVs(uv_set) if has_uvs else ([], [])
    uv_counts, uv_ids = fn.getAssignedUVs(uv_set) if has_uvs else ([], [])
    flat_points = [value for point in fn.getPoints(om.MSpace.kObject) for value in (point.x, point.y, point.z)]
    return edits.fingerprint(flat_points, counts, connects, list(us) + list(vs), uv_counts, uv_ids)


def corner_uvs(shape: str, uv_set: str) -> list | None:
    """(u, v) per face corner of ``uv_set`` in Maya's convention, None on a face without UVs; None when the set is empty."""
    fn = _fn(shape)
    if not fn.numUVs(uv_set):
        return None
    us, vs = fn.getUVs(uv_set)
    uv_counts, uv_ids = fn.getAssignedUVs(uv_set)
    counts, _connects = fn.getVertices()
    out: list = []
    cursor = 0
    for face, count in enumerate(counts):
        if uv_counts[face]:
            out.extend((us[i], vs[i]) for i in uv_ids[cursor : cursor + count])
            cursor += count
        else:
            out.extend([None] * count)
    return out


def _fn(shape: str) -> om.MFnMesh:
    selection = om.MSelectionList()
    selection.add(shape)
    return om.MFnMesh(selection.getDagPath(0))


def polygon_target(shape: str, up_z: bool | None = None):
    """The shape as the sent file saw it (object space, metres, Y-up), for ``core.topology.match``."""
    from ..core import topology

    if up_z is None:
        up_z = cmds.upAxis(query=True, axis=True) == "z"
    selection = om.MSelectionList()
    selection.add(shape)
    fn = om.MFnMesh(selection.getDagPath(0))
    counts, connects = fn.getVertices()
    points = []
    for point in fn.getPoints(om.MSpace.kObject):
        x, y, z = point.x * CM_TO_M, point.y * CM_TO_M, point.z * CM_TO_M
        points.append((x, z, -y) if up_z else (x, y, z))
    return topology.Target(points, list(counts), list(connects))


def material_for(engine: str, name: str) -> tuple:
    """(``MaterialPart``, notes) for a shading group: colour or one file texture, metalness, roughness."""
    notes: list = []
    part = gltf_write.MaterialPart(name)
    shaders = cmds.listConnections(engine + ".surfaceShader", source=True, destination=False) if engine else None
    if not shaders:
        return part, notes
    shader = shaders[0]
    for attribute in COLOR_ATTRIBUTES:
        if not cmds.attributeQuery(attribute, node=shader, exists=True):
            continue
        files = cmds.listConnections(f"{shader}.{attribute}", source=True, destination=False, type="file") or []
        incoming = cmds.listConnections(f"{shader}.{attribute}", source=True, destination=False) or []
        if files:
            image, mime, note = _texture_bytes(files[0])
            if image:
                part.image, part.image_mime, part.base_color = image, mime, (1.0, 1.0, 1.0, 1.0)
            else:
                notes.append(note)
        elif incoming:
            notes.append(f"the base colour of {shader} comes from a network the export cannot read: sent as its colour only")
        if not part.image:
            color = cmds.getAttr(f"{shader}.{attribute}")[0]
            part.base_color = (float(color[0]), float(color[1]), float(color[2]), 1.0)
        break
    for attributes, target in ((METAL_ATTRIBUTES, "metallic"), (ROUGH_ATTRIBUTES, "roughness")):
        for attribute in attributes:
            if cmds.attributeQuery(attribute, node=shader, exists=True):
                value = cmds.getAttr(f"{shader}.{attribute}")
                if isinstance(value, (int, float)):
                    setattr(part, target, min(max(float(value), 0.0), 1.0))
                break
    return part, notes


def _texture_bytes(file_node: str) -> tuple:
    """(bytes, mime, note) of a file node's image; PNG and JPEG only, never a tiled (UDIM) one."""
    path = cmds.getAttr(file_node + ".fileTextureName") or ""
    if cmds.attributeQuery("uvTilingMode", node=file_node, exists=True) and cmds.getAttr(file_node + ".uvTilingMode"):
        return b"", "", f"{os.path.basename(path)} is a tiled texture (UDIM): sent as the material's colour only"
    resolved = path if os.path.isabs(path) else cmds.workspace(expandName=path)
    kind = gltf.sniff_format(resolved)
    if kind == "missing":
        return b"", "", f"{os.path.basename(path) or file_node} was not found: sent as the material's colour only"
    if kind not in IMAGE_MIME:
        return b"", "", f"{os.path.basename(path)} is not PNG or JPEG: sent as the material's colour only"
    with open(resolved, "rb") as handle:
        return handle.read(), IMAGE_MIME[kind], ""


def _shading(fn: om.MFnMesh, dag: om.MDagPath) -> tuple:
    """(shading group names, the group index of each face, -1 for none)."""
    try:
        objects, face_engine = fn.getConnectedShaders(dag.instanceNumber())
    except RuntimeError:
        return [], [-1] * fn.numPolygons
    engines = [om.MFnDependencyNode(item).name() for item in objects]
    return engines, list(face_engine)


def _gltf_matrix(maya_matrix: list, up_z: bool) -> list:
    """A Maya world matrix (row vectors, centimetres) as a glTF node matrix (column-major, metres, Y-up)."""
    matrix = om.MMatrix(maya_matrix)
    if up_z:
        turn = om.MEulerRotation(-1.5707963267948966, 0.0, 0.0).asMatrix()
        matrix = matrix * turn
    values = list(matrix)
    values[12], values[13], values[14] = values[12] * CM_TO_M, values[13] * CM_TO_M, values[14] * CM_TO_M
    return values  # Maya's row-vector layout is glTF's column-major order
