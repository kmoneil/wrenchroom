"""Tool primitives: one set of numbers, two renderings that must coincide.

A primitive is numbers. The exact engine renders it as an OCP solid, the mesh
engine as a manifold3d mesh, by separate code. If the two drifted apart (an arm
turned the wrong way, a frame read transposed) the engines would disagree
everywhere, so every primitive is built both ways, in frames along every axis
and in seeded random ones far from the origin, and compared: the mesh must hold
the whole OCP solid, and stand outside it by no more than the facet allowance.
"""

import math

import numpy as np
import pytest
from build123d import Pos, Vector

from wrenchroom.engine import MeshEngine
from wrenchroom.engine.mesh import TOOL_FACET, solid_mesh
from wrenchroom.solids import (
    AxialCylinder,
    AxialRing,
    RadialBox,
    RadialCylinder,
    ToolSolid,
    frame_location,
    frame_matrix,
    transform_bounds,
)

PRIMITIVES = [
    AxialCylinder(2.835, 0.3, 33.3),  # a 5 mm key's short leg
    AxialCylinder(14.0, 100.3, 200.3),  # a driver's handle
    AxialRing(9.54, 14.8, -5.0, 2.5),  # a 16 mm ring
    AxialRing(3.5, 5.5, 0.1, 1.1),  # a free-face probe
    *(RadialCylinder(2.835, 0.0, 85.0, 33.3, phi) for phi in (0.0, 15.0, 90.0, 187.5, 345.0)),
    *(RadialBox(16.0, 10.0, 18.0, 180.0, 50.0, phi) for phi in (0.0, 30.0, 135.0, 270.0)),
]


def _random_frames(count, seed):
    rng = np.random.default_rng(seed)  # PCG64: the same frames on every platform
    frames = []
    for _ in range(count):
        axis = rng.normal(size=3)
        axis /= np.linalg.norm(axis)
        seat = rng.uniform(-5e4, 5e4, size=3)
        frames.append((tuple(float(c) for c in seat), tuple(float(c) for c in axis)))
    return frames


FRAMES = [
    None,  # the local frame itself
    ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    ((0.0, 0.0, 0.0), (0.0, 0.0, -1.0)),  # Plane picks its x direction differently
    ((10.0, -20.0, 30.0), (1.0, 0.0, 0.0)),
    ((10.0, -20.0, 30.0), (-1.0, 0.0, 0.0)),
    ((0.0, 5.0, 0.0), (0.0, 1.0, 0.0)),
    ((0.0, 5.0, 0.0), (0.0, -1.0, 0.0)),
    *_random_frames(6, seed=2936),
]


def _frame_id(frame):
    if frame is None:
        return "local"
    _, axis = frame
    return f"axis({axis[0]:.2f},{axis[1]:.2f},{axis[2]:.2f})"


def _tool(primitive, frame):
    local = ToolSolid((primitive,))
    return local if frame is None else local.placed(*frame)


def _analytic(primitive):
    """Volume and curved area (where the facet allowance applies) from the numbers."""
    match primitive:
        case AxialCylinder(radius=r, z0=z0, z1=z1):
            return math.pi * r * r * (z1 - z0), 2 * math.pi * r * (z1 - z0)
        case AxialRing(inner=a, outer=b, z0=z0, z1=z1):
            h = z1 - z0
            return math.pi * (b * b - a * a) * h, 2 * math.pi * (a + b) * h
        case RadialCylinder(radius=r, r0=r0, r1=r1):
            return math.pi * r * r * (r1 - r0), 2 * math.pi * r * (r1 - r0)
        case RadialBox(width=w, thickness=t, r0=r0, r1=r1):
            return w * t * (r1 - r0), 0.0
    raise AssertionError(primitive)


def _piece(tool):
    query = MeshEngine().query(tool)
    return query._piece(0)  # noqa: SLF001  (the mesh under test, nothing else exposes it)


@pytest.mark.parametrize("primitive", PRIMITIVES, ids=repr)
def test_the_ocp_solid_has_the_analytic_volume(primitive):
    volume, _ = _analytic(primitive)
    assert _tool(primitive, None).shape().volume == pytest.approx(volume, rel=1e-6)


@pytest.mark.parametrize("frame", FRAMES, ids=_frame_id)
@pytest.mark.parametrize("primitive", PRIMITIVES, ids=repr)
def test_the_mesh_holds_the_solid_and_hugs_it(primitive, frame):
    tool = _tool(primitive, frame)
    volume, curved_area = _analytic(primitive)
    piece = _piece(tool)
    truth = solid_mesh(tool.shape(), tolerance=0.002)  # a fine mesh of the OCP solid
    assert truth is not None
    # Placement: the mesh sits where the OCP solid sits (a turned or flipped arm
    # would share almost nothing with it).
    shared = (truth ^ piece).volume()
    assert shared == pytest.approx(truth.volume(), rel=2e-4)
    # Never smaller than the true tool; never bigger by more than the facets allow.
    assert piece.volume() >= volume * (1 - 1e-9)
    assert piece.volume() <= volume + TOOL_FACET * curved_area + 1e-6


@pytest.mark.parametrize("frame", FRAMES[1:], ids=_frame_id)
@pytest.mark.parametrize("primitive", PRIMITIVES, ids=repr)
def test_the_box_holds_the_placed_solid(primitive, frame):
    tool = _tool(primitive, frame)
    (lo, hi) = tool.bounds()
    tight = tool.shape().bounding_box()
    assert all(lo[i] <= c + 1e-6 for i, c in enumerate(tight.min))
    assert all(hi[i] >= c - 1e-6 for i, c in enumerate(tight.max))


@pytest.mark.parametrize("frame", FRAMES[1:], ids=_frame_id)
def test_the_matrix_is_the_ocp_placement(frame):
    seat, axis = frame
    matrix = frame_matrix(seat, axis)
    location = frame_location(seat, axis)
    for point in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (3.5, -7.25, 11.0)):
        expected = (location * Pos(*point)).position
        got = matrix @ np.array([*point, 1.0])
        assert tuple(got[:3]) == pytest.approx(tuple(expected), abs=1e-9)
    assert np.allclose(matrix[:3, 2], axis)  # local +Z is the axis
    assert np.allclose(matrix[:3, 3], seat)  # local origin is the seat


def test_the_matrix_is_read_only():
    matrix = frame_matrix((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    with pytest.raises(ValueError, match="read-only"):
        matrix[0, 0] = 2.0


def test_transformed_bounds_hold_every_corner():
    turn = frame_matrix((5.0, 6.0, 7.0), (0.0, math.sqrt(0.5), math.sqrt(0.5)))
    (lo, hi) = transform_bounds(((-1.0, -2.0, -3.0), (1.0, 2.0, 3.0)), turn)
    for x in (-1, 1):
        for y in (-2, 2):
            for z in (-3, 3):
                corner = turn @ np.array([x, y, z, 1.0])
                assert all(lo[i] - 1e-9 <= corner[i] <= hi[i] + 1e-9 for i in range(3))


def test_joined_tools_keep_every_primitive_in_order():
    mouth = ToolSolid((AxialRing(9.0, 11.0, 0.3, 15.3),))
    body = ToolSolid((AxialCylinder(11.0, 15.3, 40.0),))
    stack = mouth + body
    assert stack.primitives == mouth.primitives + body.primitives
    assert not stack.is_placed
    placed = stack.placed((1.0, 2.0, 3.0), (0.0, 0.0, 1.0))
    assert placed.is_placed
    assert placed.primitives == stack.primitives
    assert placed.shape().volume == pytest.approx(
        _analytic(mouth.primitives[0])[0] + _analytic(body.primitives[0])[0], rel=1e-6
    )


def test_a_radial_arm_points_along_u_phi():
    # u(phi) = (cos phi, sin phi, 0) in the local frame: the arm's far end is there.
    arm = ToolSolid((RadialCylinder(1.0, 0.0, 50.0, 0.0, 90.0),))
    centre = arm.shape().center()
    assert tuple(centre) == pytest.approx((0.0, 25.0, 0.0), abs=1e-6)
    assert pytest.approx(50.0) == Vector(*arm.bounds()[1]).Y
