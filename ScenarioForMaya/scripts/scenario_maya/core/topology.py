"""Is an edit result the same surface as the mesh that was sent? (spec 6.4)

Edit models return GLBs that are triangulated, split at UV seams and
rescaled: on 2026-10-19 Tripo models returned the sent mesh 1 m long and
Meshy models 2 m long, centred, with no rotation. Before UVs or textures can
go back onto the user's mesh exactly, the result has to be proven to be that
mesh:

1. Fit: one uniform scale and an offset, from the bounds (never a rotation).
2. Every result vertex lands on a target vertex within 1e-5 of the target's
   size (candidates are kept when the target has coincident vertices).
3. Every result triangle lies inside exactly one target face, with the same
   winding, and the triangles tile each face: n - 2 distinct triangles that
   use every corner.
4. The result's UV at each target face corner is the same, within 1e-5, in
   every triangle that uses that corner; otherwise the corners are counted.

The target is given as Maya stores it (counts, vertex ids per face corner,
points), converted to the sent file's space (metres, Y-up) by the caller.
Pure Python, no Maya.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

WELD = 1e-5  # of the target's bounding diagonal
UV_TOLERANCE = 1e-5
MAX_COMPONENTS = 2_000_000


@dataclass
class Target:
    points: list  # (x, y, z) per vertex
    counts: list  # corners per face
    connects: list  # vertex id per face corner, faces in order


@dataclass
class Result:
    points: list  # (x, y, z) per vertex
    triangles: list  # (a, b, c) vertex ids
    uvs: list | None = None  # (u, v) per vertex, glTF convention (V down)


@dataclass
class Match:
    verdict: str  # "same_surface" or "different"
    scale: float = 1.0
    offset: tuple = (0.0, 0.0, 0.0)
    reason: str = ""
    corner_uvs: list | None = None  # (u, v) per target face corner, Maya convention (V up)
    uv_disagreements: int = 0
    facts: dict = field(default_factory=dict)

    @property
    def same_surface(self) -> bool:
        return self.verdict == "same_surface"


def bounds(points: list) -> tuple:
    lows = [min(point[axis] for point in points) for axis in range(3)]
    highs = [max(point[axis] for point in points) for axis in range(3)]
    return lows, highs


def fit(result_points: list, target_points: list) -> tuple:
    """(scale, offset) that put the result's bounding box on the target's: one uniform scale, no rotation."""
    rlo, rhi = bounds(result_points)
    tlo, thi = bounds(target_points)
    rdiag = math.dist(rlo, rhi)
    tdiag = math.dist(tlo, thi)
    scale = tdiag / rdiag if rdiag > 0 else 1.0
    offset = tuple((tlo[k] + thi[k]) / 2 - scale * (rlo[k] + rhi[k]) / 2 for k in range(3))
    return scale, offset


def apply_fit(points: list, scale: float, offset: tuple) -> list:
    return [(scale * x + offset[0], scale * y + offset[1], scale * z + offset[2]) for x, y, z in points]


def match(target: Target, result: Result) -> Match:
    """Proves (or not) that ``result`` is ``target``'s surface; see the module text."""
    if not result.points or not result.triangles or not target.points:
        return Match("different", reason="One of the meshes is empty.")
    if len(target.connects) + 3 * len(result.triangles) > MAX_COMPONENTS:
        return Match("different", reason=f"Too large to compare exactly (over {MAX_COMPONENTS:,} components).")
    scale, offset = fit(result.points, target.points)
    lo, hi = bounds(target.points)
    tolerance = max(math.dist(lo, hi), 1e-12) * WELD
    placed = apply_fit(result.points, scale, offset)
    facts = {"result_triangles": len(result.triangles), "target_faces": len(target.counts), "scale": scale}

    if len(result.triangles) != sum(count - 2 for count in target.counts):
        facts["expected_triangles"] = sum(count - 2 for count in target.counts)
        return Match("different", scale, offset, f"The result has {len(result.triangles):,} triangles; the mesh splits into {facts['expected_triangles']:,}.", facts=facts)

    # 2. Result vertices onto target vertices.
    grid: dict = {}
    for index, point in enumerate(target.points):
        grid.setdefault(_cell(point, tolerance), []).append(index)
    candidates = []
    off_mesh = 0
    for point in placed:
        found = [
            index
            for cell in _neighbours(_cell(point, tolerance))
            for index in grid.get(cell, ())
            if abs(target.points[index][0] - point[0]) <= tolerance and abs(target.points[index][1] - point[1]) <= tolerance and abs(target.points[index][2] - point[2]) <= tolerance
        ]
        off_mesh += not found
        candidates.append(found)
    if off_mesh:
        return Match("different", scale, offset, f"{off_mesh:,} result vertices are not on the mesh's vertices.", facts=facts)

    # 3. Each triangle inside one face, same winding; faces tiled.
    starts = []
    cursor = 0
    for count in target.counts:
        starts.append(cursor)
        cursor += count
    faces_of: dict = {}
    for face, start in enumerate(starts):
        for corner in range(target.counts[face]):
            faces_of.setdefault(target.connects[start + corner], set()).add(face)
    tiles: dict = {}
    corner_of_triangle = []
    for number, triangle in enumerate(result.triangles):
        sets = [set().union(*(faces_of.get(vertex, set()) for vertex in candidates[corner])) for corner in triangle]
        faces = sets[0] & sets[1] & sets[2]
        placed_corners = []
        for face in faces:
            start, count = starts[face], target.counts[face]
            ring = target.connects[start : start + count]
            positions = []
            for corner in triangle:
                hits = [k for k, vertex in enumerate(ring) if vertex in candidates[corner]]
                if len(hits) != 1:
                    break
                positions.append(hits[0])
            else:
                if len(set(positions)) == 3 and _same_winding(positions, count):
                    placed_corners.append((face, positions))
        if len(placed_corners) != 1:
            why = "lies in no single face of the mesh" if not placed_corners else "fits several faces"
            return Match("different", scale, offset, f"Triangle {number + 1} of the result {why}.", facts=facts)
        face, positions = placed_corners[0]
        tiles.setdefault(face, set()).add(tuple(sorted(positions)))
        corner_of_triangle.append((face, positions))
    for face, count in enumerate(target.counts):
        if not _tiles(tiles.get(face, set()), count):
            return Match("different", scale, offset, f"Face {face + 1} of the mesh is not covered exactly by the result's triangles.", facts=facts)

    out = Match("same_surface", scale, offset, facts=facts)
    if result.uvs is None:
        return out
    # 4. One UV per target face corner.
    per_corner: dict = {}
    disagreements = set()
    for (face, positions), triangle in zip(corner_of_triangle, result.triangles, strict=True):
        for corner, vertex in zip(positions, triangle, strict=True):
            key = starts[face] + corner
            u, v = result.uvs[vertex]
            known = per_corner.get(key)
            if known is None:
                per_corner[key] = (u, v)
            elif abs(known[0] - u) > UV_TOLERANCE or abs(known[1] - v) > UV_TOLERANCE:
                disagreements.add(key)
    out.uv_disagreements = len(disagreements)
    if disagreements:
        out.reason = f"The result splits UV coordinates at {len(disagreements):,} face corners of the mesh."
        return out
    out.corner_uvs = [(per_corner[key][0], 1.0 - per_corner[key][1]) for key in range(len(target.connects))]
    return out


def result_from_document(doc) -> Result:
    """Every triangle mesh of a parsed GLB as one ``Result``, node transforms applied, first UV set."""
    data = doc.json
    nodes = data.get("nodes") or []
    children = {child for node in nodes for child in node.get("children") or []}
    points: list = []
    triangles: list = []
    uvs: list = []
    has_uvs = True

    def visit(index: int, parent: list) -> None:
        nonlocal has_uvs
        node = nodes[index]
        world = _multiply(_node_matrix(node), parent)
        if "mesh" in node:
            for primitive in (data.get("meshes") or [])[node["mesh"]].get("primitives") or []:
                attributes = primitive.get("attributes") or {}
                if primitive.get("mode", 4) != 4 or "POSITION" not in attributes:
                    continue
                position = doc.accessor(attributes["POSITION"])
                base = len(points)
                for row in range(position.count):
                    points.append(_transform(world, position.row(row)))
                if "TEXCOORD_0" in attributes:
                    uv = doc.accessor(attributes["TEXCOORD_0"])
                    uvs.extend(uv.row(row) for row in range(uv.count))
                else:
                    has_uvs = False
                    uvs.extend([(0.0, 0.0)] * position.count)
                indices = doc.accessor(primitive["indices"]).values if "indices" in primitive else range(position.count)
                for start in range(0, len(indices) - 2, 3):
                    triangles.append((base + indices[start], base + indices[start + 1], base + indices[start + 2]))
        for child in node.get("children") or []:
            visit(child, world)

    scenes = data.get("scenes") or []
    if scenes:
        roots = scenes[data.get("scene", 0)].get("nodes") or []
    else:
        roots = [index for index in range(len(nodes)) if index not in children]
    for index in roots:
        visit(index, _IDENTITY)
    return Result(points, triangles, uvs if has_uvs else None)


_IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _node_matrix(node: dict) -> list:
    """Column-major 4x4 of a glTF node (``matrix`` or translation, rotation, scale)."""
    if "matrix" in node:
        return [float(value) for value in node["matrix"]]
    tx, ty, tz = node.get("translation") or (0.0, 0.0, 0.0)
    x, y, z, w = node.get("rotation") or (0.0, 0.0, 0.0, 1.0)
    sx, sy, sz = node.get("scale") or (1.0, 1.0, 1.0)
    return [
        (1 - 2 * (y * y + z * z)) * sx, (2 * (x * y + z * w)) * sx, (2 * (x * z - y * w)) * sx, 0.0,
        (2 * (x * y - z * w)) * sy, (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z + x * w)) * sy, 0.0,
        (2 * (x * z + y * w)) * sz, (2 * (y * z - x * w)) * sz, (1 - 2 * (x * x + y * y)) * sz, 0.0,
        tx, ty, tz, 1.0,
    ]  # fmt: skip


def _multiply(local: list, parent: list) -> list:
    """parent x local, both column-major."""
    return [sum(parent[k * 4 + row] * local[col * 4 + k] for k in range(4)) for col in range(4) for row in range(4)]


def _transform(matrix: list, point: tuple) -> tuple:
    x, y, z = point
    return (
        matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
        matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
        matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    )


def _tiles(triangles: set, count: int) -> bool:
    """n - 2 triangles that triangulate an n-gon: each side in one triangle, each diagonal in two."""
    if len(triangles) != count - 2:
        return False
    edges: dict = {}
    for a, b, c in triangles:
        for edge in ((a, b), (b, c), (a, c)):
            edges[edge] = edges.get(edge, 0) + 1
    for (a, b), uses in edges.items():
        side = (b - a) % count in (1, count - 1)
        if uses != (1 if side else 2):
            return False
    return sum(1 for (a, b) in edges if (b - a) % count in (1, count - 1)) == count


def _same_winding(positions: list, count: int) -> bool:
    """True when the triangle's corners go round the face in the face's own order."""
    a, b, c = positions
    return (b - a) % count < (c - a) % count


def _cell(point: tuple, size: float) -> tuple:
    return (math.floor(point[0] / size), math.floor(point[1] / size), math.floor(point[2] / size))


def _neighbours(cell: tuple):
    x, y, z = cell
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                yield (x + dx, y + dy, z + dz)
