"""Edit results back on the user's meshes (spec 6.4). Main thread.

Every edit model seen so far returns the sent mesh rescaled and centred
(Tripo: 1 m long, Meshy: 2 m long), so a result is never placed by its own
coordinates: it is fitted onto the mesh that was sent (one uniform scale and
an offset from the bounds, no rotation), then put in that mesh's object
space. The sent file stays in the captures folder; the target is found again
by its UUID, never by name or selection.
"""

from __future__ import annotations

import os

from maya import cmds
from maya.api import OpenMaya as om

from ..core import gltf, topology
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
        from .mesh_export import mesh_shape

        shapes = [mesh_shape(transform)] if mesh_shape(transform) else []
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
