"""Edit results back on the user's meshes (spec 6.4). Main thread.

Most edit models return the sent mesh resized and centred (on 2026-10-19:
Tripo models 1 m long, Meshy Remesh and Meshy 7 Retexture 2 m long), while
Meshy UV Unwrap returns it where and as large as it was sent. So a result is
never placed by its own coordinates: it is fitted onto the mesh that was sent
(one uniform scale and an offset from the bounds, no rotation), then put in
that mesh's object space. The sent file stays in the captures folder; the target is found again
by its UUID, never by name or selection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from maya import cmds
from maya.api import OpenMaya as om

from ..core import edits, gltf, naming, topology
from . import mesh_export
from .landing import LandingError

M_TO_CM = 100.0


class ApplyError(LandingError):
    """Nothing was changed; the message says why (shown like any landing refusal)."""


def edit_record(row: dict) -> dict:
    return ((row.get("origin") or {}).get("edit")) or {}


def find_target(record: dict) -> tuple:
    """(transform, shape) of the captured mesh by UUID, or ("", "") when it is gone."""
    mesh = (record.get("meshes") or [{}])[0]
    found = cmds.ls(mesh.get("uuid") or "", long=True) if mesh.get("uuid") else []
    if not found:
        return "", ""
    transform = found[0]
    shapes = cmds.ls(mesh.get("shape_uuid") or "", long=True) if mesh.get("shape_uuid") else []
    if not shapes:
        shapes = [mesh_export.mesh_shape(transform)] if mesh_export.mesh_shape(transform) else []
    return transform, shapes[0] if shapes else ""


def sent_points(record: dict) -> list:
    """The sent mesh's points in the file's space (metres, Y-up), read back from the kept GLB."""
    path = record.get("path") or ""
    if not os.path.isfile(path):
        raise ApplyError("The mesh file that was sent is no longer in the captures folder, so the result cannot be fitted onto it.")
    return topology.result_from_document(gltf.Document.load(path)).points


def fit_result(result_path: str, record: dict) -> tuple:
    """(scale, offset, result) that put the result onto the sent mesh."""
    result = topology.result_from_document(gltf.Document.load(result_path))
    if not result.points:
        raise ApplyError("The result has no mesh.")
    scale, offset = topology.fit(result.points, sent_points(record))
    return scale, offset, result


def placement_matrix(scale: float, offset: tuple, record: dict, world: list | None = None) -> list:
    """World matrix (centimetres, as ``cmds.xform`` takes it) for an imported result's top group.

    The importer builds points as file coordinates in centimetres and turns
    the top group 90 degrees on X in a Z-up scene; this matrix scales and
    moves them onto the sent mesh, turns them like the importer would, then
    puts them in the target's space.
    """
    fit = om.MMatrix([scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0, offset[0] * M_TO_CM, offset[1] * M_TO_CM, offset[2] * M_TO_CM, 1])
    axis = om.MEulerRotation(1.5707963267948966, 0.0, 0.0).asMatrix() if record.get("up_axis") == "z" else om.MMatrix()
    target = om.MMatrix(world or (record.get("meshes") or [{}])[0].get("world_matrix") or list(om.MMatrix()))
    return list(fit * axis * target)


def import_over_target(row: dict, result_path: str) -> dict:
    """Where an edit result lands on Import: its matrix over the source mesh, and what it was fitted to."""
    record = edit_record(row)
    scale, offset, _result = fit_result(result_path, record)
    transform, _shape = find_target(record)
    world = cmds.xform(transform, query=True, matrix=True, worldSpace=True) if transform else None
    name = transform.split("|")[-1] if transform else (record.get("meshes") or [{}])[0].get("node", "").split("|")[-1]
    return {"matrix": placement_matrix(scale, offset, record, world), "scale": scale, "target": transform, "target_name": name, "target_found": bool(transform)}


# -- Apply: the result written onto the mesh itself (spec 6.4) ---------------------------------------
#
# Three steps, as in the spec's apply contract. ``gather`` (main thread) reads
# the target as it is now and runs the preflight; ``compare`` (any thread, no
# Maya) proves the result is that surface and writes the review; ``run`` (main
# thread) rechecks the target and makes the edits in one undo chunk. This
# version applies UV unwrap and Retexture results; Replace geometry comes later.

TITLES = {"UV": "Replace UVs", "RETEXTURE": "Replace textures", "REMESH": "Replace geometry"}
BACKUP_SUFFIX = "_scnPrev"


@dataclass
class Review:
    mode: str
    name: str  # the target's short name, for messages
    title: str = ""
    refusal: str = ""  # non-empty: nothing can be applied, and why
    changes: list = field(default_factory=list)
    kept: list = field(default_factory=list)
    confirms: list = field(default_factory=list)  # each must be accepted before Apply
    target: str = ""
    shape: str = ""
    fingerprint: str = ""
    uv_set: str = ""
    backup: str = ""
    delete_history: bool = False
    write_uvs: tuple | None = None  # (us, vs, counts, ids) for scenarioSetUVs
    material: int | None = None  # the result's material index (Replace textures)
    result_path: str = ""
    facts: dict = field(default_factory=dict)


def gather(row: dict, mode: str = "") -> dict:
    """Main thread: the target as it is now, and what the preflight found."""
    record = edit_record(row)
    if not record:
        raise ApplyError("This result was not made from a mesh of the scene, so there is nothing to apply it to.")
    task = edits.BY_TASK.get(record.get("task") or "")
    mode = mode or (task.apply_mode if task else "UV")
    transform, shape = find_target(record)
    name = transform.split("|")[-1] if transform else (record.get("meshes") or [{}])[0].get("node", "").split("|")[-1]
    out = {"mode": mode, "name": name, "transform": transform, "shape": shape, "refusal": "", "notes": []}
    if not transform or not shape:
        return dict(out, refusal=f"{name} is no longer in the scene, so there is nothing to apply to. Import places the result where it was.")
    if mode == "REMESH":
        return dict(out, refusal=f"Replacing the geometry comes in a later version. Import places the remeshed result over {name}.")
    if mode not in ("UV", "RETEXTURE"):
        return dict(out, refusal=f"{TITLES.get(mode, mode)} is not available in this version.")
    if cmds.referenceQuery(shape, isNodeReferenced=True):
        return dict(out, refusal=f"{name} comes from a referenced file; apply the result in the file it comes from.")
    if any(cmds.lockNode(node, query=True, lock=True)[0] for node in (transform, shape)):
        return dict(out, refusal=f"{name} is locked.")
    history = cmds.listHistory(shape, pruneDagObjects=True) or []
    deformers = [node for node in history if "geometryFilter" in (cmds.nodeType(node, inherited=True) or [])]
    if deformers:
        return dict(out, refusal=f"{name} is deformed ({', '.join(deformers[:3])}). Applying onto a deformed mesh comes in a later version; Import places the result over it.")
    up_z = record.get("up_axis") == "z"
    uv_set = cmds.polyUVSet(shape, query=True, currentUVSet=True) or ["map1"]
    uv_set = uv_set[0]
    sets = cmds.polyUVSet(shape, query=True, allUVSets=True) or []
    backup, number = uv_set + BACKUP_SUFFIX, 1
    while backup in sets:
        backup, number = f"{uv_set}{BACKUP_SUFFIX}{number}", number + 1
    selection = om.MSelectionList()
    selection.add(shape)
    engines, _faces = om.MFnMesh(selection.getDagPath(0)).getConnectedShaders(0)
    sent = (record.get("meshes") or [{}])[0].get("fingerprint", "")
    fingerprint = mesh_export.shape_fingerprint(shape)
    if sent and sent != fingerprint:
        out["notes"].append(f"{name} changed after it was sent; the result is checked against it as it is now.")
    return dict(
        out,
        target=mesh_export.polygon_target(shape, up_z),
        uv_set=uv_set,
        backup=backup,
        current_uvs=mesh_export.corner_uvs(shape, uv_set),
        history=[node for node in history if node != shape][:4] if cmds.listConnections(shape + ".inMesh", source=True, destination=False) else [],
        instanced=selection.getDagPath(0).isInstanced(),
        engines=len(engines),
        fingerprint=fingerprint,
        model=str(row.get("model_name") or row.get("target_id") or "the model"),
    )


def compare(gathered: dict, result_path: str) -> Review:
    """Any thread, no Maya: proves the result is the target's surface and says what Apply will do."""
    mode, name = gathered["mode"], gathered["name"]
    review = Review(mode, name, title=f"{TITLES.get(mode, mode)} on {name}", target=gathered.get("transform", ""), shape=gathered.get("shape", ""), result_path=result_path)
    if gathered.get("refusal"):
        review.refusal = gathered["refusal"]
        return review
    review.fingerprint, review.uv_set, review.backup = gathered["fingerprint"], gathered["uv_set"], gathered["backup"]
    doc = gltf.Document.load(result_path)
    result = topology.result_from_document(doc)
    found = topology.match(gathered["target"], result)
    review.facts = dict(found.facts, uv_disagreements=found.uv_disagreements)
    if not found.same_surface:
        review.refusal = f"The result is not the same surface as {name}: {found.reason} Import places it over {name} instead."
        return review
    if result.uvs is None:
        review.refusal = "The result has no UVs, so there is nothing exact to write."
        return review
    if found.corner_uvs is None:
        review.refusal = f"{found.reason} Its UVs cannot be written exactly onto {name}'s faces. Import places it over {name} instead."
        return review
    current = gathered.get("current_uvs")
    differs = current is None or any(
        old is None or abs(old[0] - new[0]) > topology.UV_TOLERANCE or abs(old[1] - new[1]) > topology.UV_TOLERANCE for old, new in zip(current, found.corner_uvs, strict=True)
    )
    materials = doc.json.get("materials") or []
    if mode == "UV" and not differs:
        review.refusal = f"The result's UVs are already those of {gathered['uv_set']} on {name}: nothing to change."
        return review
    if mode == "RETEXTURE" and not materials:
        review.refusal = "The result has no material to apply."
        return review
    model = gathered.get("model") or "the model"
    if differs:
        review.write_uvs = _welded(found.corner_uvs, gathered["target"].connects, gathered["target"].counts)
        review.changes.append(f"Writes {model}'s UVs into {gathered['uv_set']} of {name} ({len(found.corner_uvs):,} face corners).")
        if current is not None:
            review.kept.append(f"The current {gathered['uv_set']} is copied to {gathered['backup']} first.")
        else:
            review.backup = ""
        if gathered.get("history"):
            review.delete_history = True
            review.confirms.append(f"Delete the construction history of {name} ({', '.join(gathered['history'])}): history would overwrite the new UVs.")
        if gathered.get("instanced"):
            review.confirms.append(f"{name} is instanced: every instance gets the new UVs.")
    if mode == "RETEXTURE":
        review.material = 0
        roles = sorted(set(gltf.texture_roles(doc).values()))
        maps = ", ".join(role.replace("_", " ") for role in roles) if roles else "no textures, only colours"
        review.changes.append(f"Assigns a new material from the result ({maps}) to {name}.")
        review.kept.append(f"The current material stays in the scene, no longer assigned to {name}.")
        if not differs:
            review.kept.append(f"{name}'s UVs already match the result's: they are not changed.")
        if gathered.get("engines", 0) > 1:
            review.confirms.append(f"{name} has {gathered['engines']} materials on its faces; they become one.")
        if len(materials) > 1:
            review.confirms.append(f"The result has {len(materials)} materials; the first one is applied to the whole mesh.")
        if gathered.get("instanced"):
            review.confirms.append(f"{name} is instanced: every instance gets the new material.")
    review.kept.append("Geometry and other UV sets are not changed." if mode == "UV" else "Geometry is not changed.")
    review.kept.extend(gathered.get("notes") or [])
    return review


def run(review: Review, attributes: dict | None = None, texture_folder: str = "") -> dict:
    """Main thread: the edits of a review, in one undo chunk. Raises ApplyError before changing anything."""
    from . import glb_builder, uv_command
    from .landing import add_provenance, undo_chunk

    if review.refusal:
        raise ApplyError(review.refusal)
    shapes = cmds.ls(review.shape, long=True) if review.shape else []
    if not shapes:
        raise ApplyError(f"{review.name} is no longer in the scene.")
    shape = shapes[0]
    if mesh_export.shape_fingerprint(shape) != review.fingerprint:
        raise ApplyError(f"{review.name} changed after the review. Open Apply again.")
    made: dict = {}
    doc = gltf.Document.load(review.result_path) if review.mode == "RETEXTURE" else None
    images = gltf.extract_images(doc, texture_folder, naming.slug(review.name + "_retexture")) if doc is not None and texture_folder else []
    chunk = f"Scenario: {review.title}"
    with undo_chunk(chunk):
        if review.write_uvs is not None:
            if review.delete_history:
                cmds.delete(shape, constructionHistory=True)
            if review.backup:
                cmds.polyUVSet(shape, copy=True, uvSet=review.uv_set, newUVSet=review.backup)
            uv_command.run(shape, review.uv_set, *review.write_uvs)
        if doc is not None:
            base = naming.slug(review.name + "_retexture")
            # Plain undoable commands, not the import command: undoing API deletions of shading
            # nodes alone (no DAG node) crashed Maya 2027.2 later (spec 6.7).
            made = glb_builder.build_materials(doc, images, base, name=base)
            index = review.material or 0
            if index >= len(made["shading_groups"]):
                raise ApplyError("The result's material could not be built.")
            cmds.sets(shape, edit=True, forceElement=made["shading_groups"][index])
            if attributes:
                add_provenance(made["shaders"][index], attributes)
    summary = f"{review.title}" + (f": {made['shaders'][review.material or 0]} assigned" if made else "")
    return {"summary": summary, "undo": chunk, "shape": shape, "material": (made.get("shaders") or [""])[review.material or 0] if made else "", "notes": made.get("notes", []) if made else []}


def _welded(corner_uvs: list, connects: list, counts: list) -> tuple:
    """(us, vs, counts, ids): one UV id per distinct (vertex, UV), so shells stay connected in the UV Editor."""
    us, vs, ids = [], [], []
    seen: dict = {}
    for corner, (u, v) in enumerate(corner_uvs):
        key = (connects[corner], round(u / topology.UV_TOLERANCE), round(v / topology.UV_TOLERANCE))
        index = seen.get(key)
        if index is None:
            index = seen[key] = len(us)
            us.append(u)
            vs.append(v)
        ids.append(index)
    return us, vs, list(counts), ids
