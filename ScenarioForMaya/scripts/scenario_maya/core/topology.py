"""Is an edit result the same surface as the mesh that was sent? (spec 6.4)

Edit models return GLBs that are triangulated, split at UV seams and
usually rescaled: on 2026-10-19 Tripo models returned the sent mesh 1 m long
and centred (also when it was sent 1.5 m off the origin), Meshy Remesh and
Meshy 7 Retexture 2 m long and centred, Meshy UV Unwrap in place; never
rotated. Before UVs or textures can
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

import bisect
import math
from dataclasses import dataclass, field

WELD = 1e-5  # of the target's bounding diagonal
UV_TOLERANCE = 1e-5
MAX_COMPONENTS = 2_000_000
# Fit and verify (spec 6.4): at most FIT_SHARE of the sampled points farther
# than FIT_NEAR of the target's diagonal from the other surface, none beyond FIT_FAR.
FIT_NEAR = 0.02
FIT_FAR = 0.10
FIT_SHARE = 0.05


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


def surface_gap(points: list, triangles: list, triangle_points: list, diagonal: float, samples: int = 1500) -> dict:
    """How far ``points`` lie from the surface ``triangles`` (over ``triangle_points``), as fractions of ``diagonal``.

    Up to ``samples`` points, evenly spread; distances beyond FIT_FAR of the
    diagonal are not searched and count as far. Returns ``{over_2, over_10,
    worst}``: the share of points beyond FIT_NEAR, the count beyond FIT_FAR,
    the worst distance found (capped at FIT_FAR).
    """
    if not points or not triangles or diagonal <= 0:
        return {"over_2": 1.0, "over_10": len(points), "worst": FIT_FAR}
    cell = diagonal / 32.0
    limit = diagonal * FIT_FAR
    grid: dict = {}
    for index, (a, b, c) in enumerate(triangles):
        pa, pb, pc = triangle_points[a], triangle_points[b], triangle_points[c]
        lo = [math.floor(min(pa[k], pb[k], pc[k]) / cell) for k in range(3)]
        hi = [math.floor(max(pa[k], pb[k], pc[k]) / cell) for k in range(3)]
        for x in range(lo[0], hi[0] + 1):
            for y in range(lo[1], hi[1] + 1):
                for z in range(lo[2], hi[2] + 1):
                    grid.setdefault((x, y, z), []).append(index)
    step = max(1, len(points) // samples)
    picked = points[::step]
    over_2 = over_10 = 0
    worst = 0.0
    reach = math.ceil(limit / cell)
    for point in picked:
        x0, y0, z0 = _cell(point, cell)
        best = math.inf
        seen: set = set()
        for radius in range(reach + 1):  # shells of cells around the point's own
            for key in _shell(x0, y0, z0, radius):
                for index in grid.get(key, ()):
                    if index in seen:
                        continue
                    seen.add(index)
                    a, b, c = triangles[index]
                    best = min(best, _point_triangle(point, triangle_points[a], triangle_points[b], triangle_points[c]))
            if best <= radius * cell:  # anything in a further shell is at least that far
                break
        distance = min(best, limit)
        worst = max(worst, distance / diagonal)
        over_2 += distance > FIT_NEAR * diagonal
        over_10 += best > limit
    return {"over_2": over_2 / len(picked), "over_10": over_10, "worst": worst}


def verify_fit(result: Result, sent: Result, scale: float, offset: tuple) -> dict:
    """Fit and verify (spec 6.4): is the fitted result on the sent surface, and the sent surface on it?

    Both ways, because a result that covers only part of the mesh passes one
    way. The second way is skipped when the first already fails. Returns the
    worse of the two ``surface_gap`` readings plus ``verified``.
    """
    placed = apply_fit(result.points, scale, offset)
    lo, hi = bounds(sent.points)
    diagonal = math.dist(lo, hi)
    gap = surface_gap(surface_samples(placed, result.triangles), sent.triangles, sent.points, diagonal)
    if _close(gap):
        back = surface_gap(surface_samples(sent.points, sent.triangles), result.triangles, placed, diagonal)
        gap = {key: max(gap[key], back[key]) for key in gap}
    return dict(gap, verified=_close(gap))


def surface_samples(points: list, triangles: list, count: int = 1500) -> list:
    """``count`` points spread over the triangles by area, the same every time (no random numbers)."""
    areas = []
    total = 0.0
    for a, b, c in triangles:
        total += _area(points[a], points[b], points[c])
        areas.append(total)
    if total <= 0:
        return [points[index] for triangle in triangles for index in triangle][:count]
    out = []
    for k in range(count):
        a, b, c = triangles[min(bisect.bisect_left(areas, (k + 0.5) / count * total), len(triangles) - 1)]
        r, t = (k * 0.7548776662) % 1.0, (k * 0.5698402910) % 1.0  # a plastic-number sequence: even cover
        if r + t > 1.0:
            r, t = 1.0 - r, 1.0 - t
        pa, pb, pc = points[a], points[b], points[c]
        out.append(tuple(pa[i] + r * (pb[i] - pa[i]) + t * (pc[i] - pa[i]) for i in range(3)))
    return out


def _area(a: tuple, b: tuple, c: tuple) -> float:
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    return 0.5 * math.sqrt((u[1] * v[2] - u[2] * v[1]) ** 2 + (u[2] * v[0] - u[0] * v[2]) ** 2 + (u[0] * v[1] - u[1] * v[0]) ** 2)


def _close(gap: dict) -> bool:
    return gap["over_2"] <= FIT_SHARE and gap["over_10"] == 0


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


def _point_triangle(p: tuple, a: tuple, b: tuple, c: tuple) -> float:
    """Distance from ``p`` to triangle ``abc`` (closest point by regions, as in Ericson's Real-Time Collision Detection)."""
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    ap = (p[0] - a[0], p[1] - a[1], p[2] - a[2])
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return math.dist(p, a)
    bp = (p[0] - b[0], p[1] - b[1], p[2] - b[2])
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return math.dist(p, b)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        t = d1 / (d1 - d3)
        return math.dist(p, (a[0] + t * ab[0], a[1] + t * ab[1], a[2] + t * ab[2]))
    cp = (p[0] - c[0], p[1] - c[1], p[2] - c[2])
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return math.dist(p, c)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        t = d2 / (d2 - d6)
        return math.dist(p, (a[0] + t * ac[0], a[1] + t * ac[1], a[2] + t * ac[2]))
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return math.dist(p, (b[0] + t * (c[0] - b[0]), b[1] + t * (c[1] - b[1]), b[2] + t * (c[2] - b[2])))
    total = va + vb + vc
    if total == 0:  # a degenerate triangle: its corners
        return min(math.dist(p, a), math.dist(p, b), math.dist(p, c))
    v, w = vb / total, vc / total
    return math.dist(p, (a[0] + ab[0] * v + ac[0] * w, a[1] + ab[1] * v + ac[1] * w, a[2] + ab[2] * v + ac[2] * w))


def _shell(x0: int, y0: int, z0: int, radius: int):
    """The grid cells exactly ``radius`` cells away from (x0, y0, z0), in the max norm."""
    if radius == 0:
        yield (x0, y0, z0)
        return
    for x in range(x0 - radius, x0 + radius + 1):
        for y in range(y0 - radius, y0 + radius + 1):
            if abs(x - x0) == radius or abs(y - y0) == radius:
                for z in range(z0 - radius, z0 + radius + 1):
                    yield (x, y, z)
            else:
                yield (x, y, z0 - radius)
                yield (x, y, z0 + radius)


def _dot(u: tuple, v: tuple) -> float:
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def _cell(point: tuple, size: float) -> tuple:
    return (math.floor(point[0] / size), math.floor(point[1] / size), math.floor(point[2] / size))


def _neighbours(cell: tuple):
    x, y, z = cell
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                yield (x + dx, y + dy, z + dz)
