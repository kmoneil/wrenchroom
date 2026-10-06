"""The two engines agree wherever the mesh tolerance can't matter: seeded cases.

Each case is built so its answer is known from the construction, not from either
engine, and the claims are only the ones the meshes can honour:

- **Flat parts** (a slab at any angle, anywhere): a flat face meshes exactly and
  a tool mesh holds the true tool, standing at most TOOL_FACET outside it. So
  the mesh must hit whenever the exact overlap passes the floor, and must be
  clear whenever the true gap is over TOOL_FACET. This family exercises every
  tool primitive, every way round.
- **Curved parts** (a round bar, a round bore), approached end-on by a probe at
  a known gap or depth: the mesh may be up to MESH_TOLERANCE off a curved face,
  so the claims start just past it, at 0.3 mm either side.

The exact engine is held to the construction too, so a case that is wrong
about its own geometry fails loudly rather than passing by accident. Seeds
are fixed: every run, on every platform, tries the same cases.
"""

import math

import numpy as np
import pytest
from build123d import Box, Cylinder, Location, Plane, Rot

from wrenchroom.assembly import Part
from wrenchroom.engine import HIT_MIN_VOLUME, make_engine
from wrenchroom.engine.exact import exact_overlap
from wrenchroom.engine.mesh import MESH_TOLERANCE, TOOL_FACET
from wrenchroom.solids import AxialCylinder, AxialRing, RadialBox, RadialCylinder, ToolSolid

FLAT_CASES = 160
CURVED_CASES = 48

#: Past this far from a curved face, mesh and exact must agree.
CURVED_MARGIN = 0.3


def _unit(rng):
    v = rng.normal(size=3)
    return v / np.linalg.norm(v)


def _random_primitive(rng):
    kind = rng.integers(4)
    if kind == 0:
        z0 = rng.uniform(-20, 20)
        return AxialCylinder(rng.uniform(0.5, 15), z0, z0 + rng.uniform(1, 80))
    if kind == 1:
        inner = rng.uniform(1, 12)
        z0 = rng.uniform(-20, 20)
        return AxialRing(inner, inner + rng.uniform(0.5, 8), z0, z0 + rng.uniform(0.5, 15))
    if kind == 2:
        r0 = rng.uniform(0, 20)
        return RadialCylinder(
            rng.uniform(0.5, 6),
            r0,
            r0 + rng.uniform(5, 120),
            rng.uniform(-40, 40),
            rng.uniform(0, 360),
        )
    r0 = rng.uniform(-20, 20)  # an open-end jaw's arm reaches past the axis
    return RadialBox(
        rng.uniform(2, 20),
        rng.uniform(1, 12),
        r0,
        r0 + rng.uniform(5, 150),
        rng.uniform(-40, 40),
        rng.uniform(0, 360),
        rng.uniform(-15, 15),  # and sits off to one side
    )


def _support(tool, normal):
    """How far the tool reaches along `normal` (max of n.x over the solid), exactly."""
    matrix = tool.matrix()
    rotation, shift = matrix[:3, :3], matrix[:3, 3]
    n_local = rotation.T @ normal  # the direction, in the tool's local frame
    (primitive,) = tool.primitives
    match primitive:
        case AxialCylinder(radius=r, z0=z0, z1=z1) | AxialRing(outer=r, z0=z0, z1=z1):
            ends = (z0 * n_local[2], z1 * n_local[2])
            reach = max(ends) + r * math.hypot(n_local[0], n_local[1])
        case RadialCylinder(radius=r, r0=r0, r1=r1, z=z, phi_deg=phi):
            u = np.array([math.cos(math.radians(phi)), math.sin(math.radians(phi)), 0.0])
            along = float(n_local @ u)
            across = math.sqrt(max(0.0, 1.0 - along * along))
            reach = max(r0 * along, r1 * along) + z * n_local[2] + r * across
        case RadialBox(width=w, thickness=t, r0=r0, r1=r1, z=z, phi_deg=phi, offset=offset):
            c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
            corners = [
                (x * c - y * s, x * s + y * c, zz)
                for x in (r0, r1)
                for y in (offset - w / 2, offset + w / 2)
                for zz in (z - t / 2, z + t / 2)
            ]
            reach = max(float(n_local @ np.array(corner)) for corner in corners)
        case _:
            raise AssertionError(primitive)
    return reach + float(normal @ shift)


def _slab_beyond(tool, normal, offset, thickness=30.0, size=2000.0):
    """A slab filling offset <= n.x <= offset + thickness, centred across from the tool."""
    seat = np.array(tool.seat)
    centre = seat + normal * (offset + thickness / 2 - float(normal @ seat))
    plane = Plane(origin=tuple(centre), z_dir=tuple(normal))
    return Location(plane) * Box(size, size, thickness)


def _flat_cases():
    rng = np.random.default_rng(4762)
    cases = []
    for index in range(FLAT_CASES):
        primitive = _random_primitive(rng)
        seat = rng.uniform(-3e4, 3e4, size=3)
        tool = ToolSolid((primitive,)).placed(tuple(seat), tuple(_unit(rng)))
        normal = _unit(rng)
        # The slab's near face sits `gap` past the tool's furthest point along
        # the normal: a positive gap is clear by that much, a negative one is
        # that deep into the tool. Half the cases straddle the facet allowance.
        gap = rng.choice([rng.uniform(-3, 3), rng.uniform(-0.1, 0.1)])
        cases.append(pytest.param(tool, normal, float(gap), id=f"flat{index:03d}"))
    return cases


@pytest.mark.parametrize(("tool", "normal", "gap"), _flat_cases())
def test_flat_parts_agree_exactly(tool, normal, gap):
    slab = _slab_beyond(tool, normal, _support(tool, normal) + gap)
    part = Part("slab", slab)
    exact_volume = exact_overlap(slab, tool.shape())
    exact_hit = make_engine("exact").scene([part]).hits(tool) == ("slab",)
    mesh_hit = make_engine("mesh").scene([part]).hits(tool) == ("slab",)
    assert exact_hit == (exact_volume > HIT_MIN_VOLUME)
    if gap > 0:
        assert not exact_hit, "the construction says clear"
    if exact_volume > HIT_MIN_VOLUME:
        assert mesh_hit, f"mesh missed {exact_volume:.3f} mm^3 the exact engine found"
    if gap > TOOL_FACET:
        assert not mesh_hit, f"mesh hit across a {gap:.3f} mm gap"


def test_the_flat_family_is_not_vacuous():
    # Enough of each outcome that the claims above were actually exercised. The
    # family runs about 23% hits and 46% clear whatever its size (160, 240 and 320
    # cases measured, 2026-10-06): half the gaps are within 0.1 mm, mostly too
    # shallow to count, and half the wide ones are clear. A fifth sits under both
    # with margin; the quarter this guard once held was met by chance and stopped
    # being met when boxes gained a sideways offset and the draws moved.
    hits = clear = 0
    for param in _flat_cases():
        tool, normal, gap = param.values
        slab = _slab_beyond(tool, normal, _support(tool, normal) + gap)
        volume = exact_overlap(slab, tool.shape())
        hits += volume > HIT_MIN_VOLUME
        clear += gap > TOOL_FACET
    assert hits >= FLAT_CASES // 5
    assert clear >= FLAT_CASES // 5


def _curved_cases():
    rng = np.random.default_rng(10642)
    cases = []
    for index in range(CURVED_CASES):
        bore = bool(index % 2)
        radius = float(rng.uniform(3, 40))
        probe = float(rng.uniform(1.5, min(5.0, radius * 0.5)))
        depth = float(rng.choice([-1, 1]) * rng.uniform(CURVED_MARGIN, 3.0))
        origin = tuple(float(c) for c in rng.uniform(-3e4, 3e4, size=3))
        axis = tuple(float(c) for c in _unit(rng))
        name = f"{'bore' if bore else 'bar'}{index:02d}"
        cases.append(pytest.param(bore, radius, probe, depth, origin, axis, id=name))
    return cases


@pytest.mark.parametrize(("bore", "radius", "probe", "depth", "origin", "axis"), _curved_cases())
def test_curved_parts_agree_past_the_tolerance(bore, radius, probe, depth, origin, axis):
    """A probe's flat end against a round face, `depth` into it (negative: a gap).

    Built in a local frame, then the whole case is moved to (origin, axis): the
    round face runs along local x. A bar is solid inside `radius` and the probe
    comes down onto its crest, which its flat end meets first at the middle. A
    bore is a block with a round hole and the probe stands in the hole from the
    axis up: there the end's rim meets the curved wall first, so a gap is set
    at the rim, and a depth at the middle (the rim is deeper still).
    """
    if bore:
        shape = Box(4 * radius, 2 * radius + 60, 2 * radius + 60) - _x_bar(radius, 6 * radius)
        # A gap puts the rim, at (probe, end_z), `-depth` inside the circle.
        rim_gap_z = math.sqrt((radius + depth) ** 2 - probe**2) if depth < 0 else 0.0
        end_z = radius + depth if depth > 0 else rim_gap_z
        local = ToolSolid((AxialCylinder(probe, 0.0, end_z),))
    else:
        shape = _x_bar(radius, 4 * radius)
        end_z = radius - depth  # the probe's bottom, pushed down onto the crest
        local = ToolSolid((AxialCylinder(probe, end_z, end_z + 20.0),))
    tool = local.placed(origin, axis)  # the same Plane the part is moved by
    part = Part("round", Location(Plane(origin=origin, z_dir=axis)) * shape)
    expect = depth > 0
    assert (make_engine("exact").scene([part]).hits(tool) == ("round",)) == expect
    assert (make_engine("mesh").scene([part]).hits(tool) == ("round",)) == expect
    assert MESH_TOLERANCE < CURVED_MARGIN  # the margin is what makes this claim sound


def _x_bar(radius, length):
    return Rot(0, 90, 0) * Cylinder(radius, length)


def test_the_curved_family_is_not_vacuous():
    cases = [param.values for param in _curved_cases()]
    for bore in (False, True):
        depths = [depth for is_bore, _, _, depth, _, _ in cases if is_bore == bore]
        assert sum(d > 0 for d in depths) >= CURVED_CASES // 8
        assert sum(d < 0 for d in depths) >= CURVED_CASES // 8
