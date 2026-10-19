"""Proving that an edit result is the sent mesh (spec 6.4), on hand-made meshes (0 CU).

The result side imitates what edit models returned on 2026-10-19: rescaled
and moved, triangulated, every triangle with its own vertices (split at
seams), triangles in another order and starting at another corner.
"""

import random

from scenario_maya.core import topology

# Two quads and a pentagon side by side (a Maya-style polygon mesh); faces share at most an edge.
POINTS = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0), (3, 0, 0), (3.5, 0.8, 0), (3, 1.6, 0)]
COUNTS = [4, 4, 5]
CONNECTS = [0, 1, 4, 3, 1, 2, 5, 4, 2, 6, 7, 8, 5]


def corner_uv(face, corner):
    """A distinct UV per face corner, so any mix-up shows."""
    return (0.1 * face + 0.01 * corner, 0.5 + 0.02 * corner)


def target():
    return topology.Target(POINTS, COUNTS, CONNECTS)


def fan_triangles(counts, connects, diagonal_from=None):
    """Triangles as (face, corner positions), fanned from corner 0 (or another corner)."""
    out = []
    for face, count in enumerate(counts):
        start = (diagonal_from or {}).get(face, 0)
        for k in range(1, count - 1):
            out.append((face, (start % count, (start + k) % count, (start + k + 1) % count)))
    return out


def result_from(triangles, scale=2.5, shift=(10.0, -3.0, 4.0), shuffle=True, rotate=True, uv=corner_uv):
    starts = [sum(COUNTS[:face]) for face in range(len(COUNTS))]
    rng = random.Random(7)
    order = list(triangles)
    if shuffle:
        rng.shuffle(order)
    points, tris, uvs = [], [], []
    for face, corners in order:
        corners = list(corners)
        if rotate:
            turn = rng.randrange(3)
            corners = corners[turn:] + corners[:turn]
        ids = []
        for corner in corners:
            x, y, z = POINTS[CONNECTS[starts[face] + corner]]
            points.append((x * scale + shift[0], y * scale + shift[1], z * scale + shift[2]))
            u, v = uv(face, corner)
            uvs.append((u, 1.0 - v))  # glTF V points down
            ids.append(len(points) - 1)
        tris.append(tuple(ids))
    return topology.Result(points, tris, uvs)


def expected_uvs():
    return [corner_uv(face, corner) for face, count in enumerate(COUNTS) for corner in range(count)]


def test_rescaled_split_shuffled_result_is_the_same_surface():
    found = topology.match(target(), result_from(fan_triangles(COUNTS, CONNECTS)))
    assert found.same_surface, found.reason
    assert abs(found.scale - 0.4) < 1e-9 and found.uv_disagreements == 0
    assert [tuple(round(v, 9) for v in uv) for uv in found.corner_uvs] == [tuple(round(v, 9) for v in uv) for uv in expected_uvs()]


def test_another_triangulation_of_the_same_faces_still_matches():
    other = fan_triangles(COUNTS, CONNECTS, diagonal_from={0: 1, 2: 3})
    assert topology.match(target(), result_from(other)).same_surface


def test_a_corner_shared_by_two_triangles_must_agree():
    triangles = fan_triangles(COUNTS, CONNECTS)  # the pentagon's corner 0 is in its three triangles
    result = result_from(triangles, shuffle=False, rotate=False)
    pentagon_first = [index for index, (face, corners) in enumerate(triangles) if face == 2][0]
    corner_zero = result.triangles[pentagon_first][0]
    result.uvs[corner_zero] = (0.99, 0.01)
    found = topology.match(target(), result)
    assert found.same_surface and found.corner_uvs is None and found.uv_disagreements == 1
    assert found.reason == "The result splits UV coordinates at 1 face corners of the mesh."


def test_overlapping_triangles_do_not_tile_a_face():
    triangles = fan_triangles(COUNTS, CONNECTS)
    triangles[1] = (0, (0, 1, 3))  # quad 0: (0,1,2) and (0,1,3) overlap and leave a hole
    found = topology.match(target(), result_from(triangles))
    assert not found.same_surface and "Face 1" in found.reason


def test_flipped_winding_is_not_the_same_surface():
    triangles = [(face, (a, c, b)) for face, (a, b, c) in fan_triangles(COUNTS, CONNECTS)]
    found = topology.match(target(), result_from(triangles))
    assert not found.same_surface and "lies in no single face" in found.reason


def test_a_remeshed_result_is_different_and_says_why():
    triangles = fan_triangles(COUNTS, CONNECTS)[:-1]
    found = topology.match(target(), result_from(triangles))
    assert not found.same_surface and found.reason == "The result has 6 triangles; the mesh splits into 7."


def test_a_moved_vertex_breaks_the_match():
    result = result_from(fan_triangles(COUNTS, CONNECTS), shuffle=False, rotate=False)
    x, y, z = result.points[4]
    result.points[4] = (x, y, z + 0.01)
    found = topology.match(target(), result)
    assert not found.same_surface and "not on the mesh's vertices" in found.reason


def test_coincident_target_vertices_still_resolve():
    # A hard edge exported unwelded: vertex 9 sits where vertex 1 is, and quad 1 uses it instead.
    points = POINTS + [POINTS[1]]
    connects = list(CONNECTS)
    connects[4] = 9
    mesh = topology.Target(points, COUNTS, connects)
    found = topology.match(mesh, result_from(fan_triangles(COUNTS, connects)))
    assert found.same_surface, found.reason


def test_fit_is_uniform_and_never_rotates():
    scale, offset = topology.fit([(0, 0, 0), (2, 1, 1)], [(10, 10, 10), (11, 10.5, 10.5)])
    assert abs(scale - 0.5) < 1e-12 and [round(v, 9) for v in offset] == [10.0, 10.0, 10.0]
