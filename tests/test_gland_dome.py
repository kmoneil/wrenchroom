"""A gland whose dome is wider than its hex's flats (issue #47).

A gland drawn as its hex and a plain dome, with no bore, was not covered once
the dome was wider than the hex across flats: "the bore leaves no face to probe
for the free end". Three things were wrong:

- the dome's outside was taken for a bore (the smallest coaxial cylinder of any
  kind): only a face looking at the axis is a bore now;
- the band a ring grips was the part's widest region, so a dome about as wide as
  the hex's corners stretched it over the dome, and a wider one was the band:
  where the part has flats parallel to its axis, the band is theirs now;
- a ring, socket or nut driver goes on along the axis, over the dome: one wider
  than their bore round the hex keeps them off, and only an open end, from the
  side, grips the hex. The result says so.

The worked gland: a 15 mm hex 3 high (corners 8.66 from the axis; a ring's or
socket's bore round them, 8.96) on a wall, a dome 7 high on top.
"""

import math

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import hex_bolt, hex_prism, slotted_screw, socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import _band, _frame, check
from wrenchroom.config import Config
from wrenchroom.fasteners import Fastener, Kind
from wrenchroom.report import Verdict
from wrenchroom.solids import AxialRing
from wrenchroom.tools.spanners import RING_CLEARANCE

AF, HEX_T, DOME_L = 15.0, 3.0, 7.0
BORE = AF / math.sqrt(3) + RING_CLEARANCE  # 8.96: a ring's or socket's, round the corners
RING_WAYS = ("ring, full length", "ring, stubby")


def gland(dome, *, cable=None):
    """The hex on z 0..3 and a dome of diameter ``dome`` on 3..10; bored if ``cable``."""
    shape = hex_prism(AF, HEX_T) + Pos(0, 0, HEX_T + DOME_L / 2) * Cylinder(dome / 2, DOME_L)
    if cable is not None:
        shape = shape - Cylinder(cable / 2, 40)
    return shape


def on_wall(shape, name="gland"):
    wall = Pos(0, 0, -2) * (Box(80, 80, 4) - Cylinder(6, 4))
    return Assembly([Part(f"{name}_wall", wall), Part(name, shape)])


def run(assembly, engine="mesh", rules=None, kit="full"):
    (result,) = check(assembly, Config.from_dict(rules or {}), kit=kit, engine=engine).results
    return result


def ring_z(result, bore=BORE):
    """The world heights of the ring on the hex in the turning attempt's engagement."""
    (turning,) = [a for a in result.attempts if a.turns]
    solid = turning.probes[0].solid
    rings = [p for p in solid.primitives if isinstance(p, AxialRing) and p.inner == bore]
    assert rings, "no ring round the corners in the engagement"
    seat_z = solid.seat[2]
    return min(seat_z + r.z0 for r in rings), max(seat_z + r.z1 for r in rings)


# ---------------------------------------------------------------------------
# The issue's glands.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dome", [12.0, 15.0, 16.0, 17.0, 17.9])
def test_a_dome_inside_the_ring_s_bore_lets_the_ring_on(engine, dome):
    # 16 and 17 used to be "the bore leaves no face to probe for the free end".
    result = run(on_wall(gland(dome)), engine)
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "spanner-15",
        "ring, full length",
    )
    assert result.notes == ()


@pytest.mark.parametrize("dome", [18.0, 20.0, 24.0])
def test_a_dome_wider_than_the_ring_s_bore_leaves_the_open_end(engine, dome):
    result = run(on_wall(gland(dome)), engine)
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "spanner-15",
        "open end, full length",
    )
    rings = [a for a in result.attempts if a.way in RING_WAYS]
    assert [a.way for a in rings] == list(RING_WAYS)
    assert all(a.blockers == ("gland",) and not a.turns and not a.holds for a in rings)
    assert result.notes == (
        f"no ring, socket or nut driver gets on: past its hex the part is {dome:.2f} "
        "across, wider than their bore round the hex; only an open end grips it, from the side",
    )


def test_the_ring_sits_on_the_hex_under_a_dome_about_as_wide():
    # A 17 dome, 8.5 from the axis, is wider than 0.75 of the corners: it used to
    # join the band, which ran 0..10, and the ring sat on the dome.
    low, high = ring_z(run(on_wall(gland(17.0))))
    assert 0.0 <= low < high <= HEX_T


def test_a_socket_cannot_get_on_either():
    rules = {"fasteners": [{"parts": "gland", "kind": "nut", "size": "M10", "tool": "socket-15"}]}
    result = run(on_wall(gland(20.0)), rules=rules)
    assert result.verdict is Verdict.BLOCKED
    assert result.blockers == ("gland",)
    (attempt,) = result.attempts
    assert (attempt.tool, attempt.way) == ("socket-15", "socket on ratchet")
    assert result.notes[0].startswith("no ring, socket or nut driver gets on")


def test_a_forced_spanner_still_tries_its_open_end():
    rules = {"fasteners": [{"parts": "gland", "kind": "nut", "size": "M10", "tool": "spanner-15"}]}
    result = run(on_wall(gland(20.0)), rules=rules)
    assert (result.verdict, result.how) == (Verdict.TURNS, "open end, full length")


def test_a_nut_driver_cannot_get_on():
    # A 10 mm hex (a nut driver's size) under a 14 dome: wider than its bore, 6.07.
    shape = hex_prism(10.0, 3.0) + Pos(0, 0, 6.5) * Cylinder(7.0, 7.0)
    rules = {
        "fasteners": [{"parts": "gland", "kind": "nut", "size": "M6", "tool": "nut-driver-10"}]
    }
    result = run(on_wall(shape), rules=rules)
    assert result.verdict is Verdict.BLOCKED
    (attempt,) = result.attempts
    assert (attempt.way, attempt.blockers) == ("nut driver straight in", ("gland",))


def test_a_bored_gland_too(engine):
    # Its cable way is a bore: the free face is probed outside it, as before.
    result = run(on_wall(gland(20.0, cable=6.0)), engine)
    assert (result.verdict, result.how) == (Verdict.TURNS, "open end, full length")


# ---------------------------------------------------------------------------
# The band is the flats', wherever the widest region is.
# ---------------------------------------------------------------------------


def test_a_flange_nut_s_ring_sits_on_its_hex():
    # A flange 20 across under a 13 mm hex: the flange is the widest region, and
    # used to be the band.
    nut = Pos(0, 0, 0.75) * Cylinder(10, 1.5) + hex_prism(13, 6.5, 1.5) - Cylinder(4, 30)
    plate = Pos(0, 0, -5) * (Box(200, 200, 10) - Cylinder(4.5, 11))
    assembly = Assembly([Part("plate", plate), Part("nut", nut)])
    rules = {"fasteners": [{"parts": "nut", "kind": "nut", "size": "M8"}]}
    result = run(assembly, rules=rules)
    assert (result.verdict, result.how) == (Verdict.TURNS, "ring, full length")
    low, high = ring_z(result, 13 / math.sqrt(3) + RING_CLEARANCE)
    assert 1.5 <= low < high <= 8.0  # the hex, over the flange


def test_the_band_is_the_flats_when_there_are_any():
    projections = (0.0, 3.0, 3.0, 10.0)
    radials = (8.66, 8.66, 8.5, 8.5)
    assert _band(projections, radials, (True, True, False, False)) == (0.0, 3.0)
    assert _band(projections, radials) == (0.0, 10.0)  # no flats: the widest region
    assert _band(projections, radials, (False,) * 4) == (0.0, 10.0)


def flats_heights(shape):
    """The heights of the vertices the frame counts on flats, from z 0 up."""
    frame = _frame(Part("x", shape), Fastener("x", Kind.SCREW))
    flats = frame.flats or (False,) * len(frame.projections)
    return sorted({round(p, 6) for p, flat in zip(frame.projections, flats, strict=True) if flat})


def test_a_hex_head_s_flats_are_its_band():
    heights = flats_heights(hex_bolt("M8"))  # its head, 13 across and 5.2 high
    assert max(heights) - min(heights) == pytest.approx(5.2)


@pytest.mark.parametrize("shape", [socket_screw("M6"), slotted_screw()], ids=["pocket", "slot"])
def test_a_key_s_pocket_or_a_slot_is_no_flats(shape):
    # Their flats face the axis: nothing a spanner grips, and no band.
    assert flats_heights(shape) == []


def test_a_spanner_with_no_stubby_lists_no_stubby_ring():
    # A 36 mm gland under a dome 50 across: no ring gets on, and a 36 mm spanner has
    # no stubby (issue #49), so the ring is tried, and fails, at full length only.
    gland = hex_prism(36, 10) + Pos(0, 0, 15) * Cylinder(25, 10)
    result = run(on_wall(gland))
    rings = [a.way for a in result.attempts if a.way.startswith("ring")]
    assert rings == ["ring, full length"]
    assert result.how == "open end, full length"
