"""A nut's clash runs on to its end on the tool's side: a cap nut's dome (issue #123).

A nut's clash was measured on its hex and its widest region (#63), which on a cap
nut leaves out most of its dome: a cover drawn into the dome blocked the spanner,
and a dome buried in a cover was told as a third of the overlap. Now a nut's
region runs from its bearing face to its end on the tool's side, as a head's does
since #116, and where no tool has found that end, both its ends covered, its bolt
says which: a bolt's middle is on its head's side, where the nut bears. A gland's
stub, on the bearing side, stays out, and so does a thread in the nut's bore, but
only where the bore runs: a cap nut's is blind.

The cap nut, worked by hand: an M8, DIN 1587-ish, a 13 hex z 0 to 6.5, a collar
6.25 round to z 9, and a dome, a sphere of 6 about z 9, to z 15; bored 6.647
(M8's minor) blind, z 0 to 12. A cap of height h is pi h^2 (18 - h) / 3. It sits
on an M8 bolt up through a plate, its end at z 5, a pocket 8 round its hex (no
spanner fits; the corners, 7.51, turn) so that the clash is asked.
"""

import math

import pytest
from build123d import Box, Cylinder, Pos, RegularPolygon, Rot, Sphere, extrude

from fixture_models import gland
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import _frame, check
from wrenchroom.config import Config
from wrenchroom.fasteners import Fastener, Kind, Size
from wrenchroom.report import Verdict

BORE = 6.647 / 2


def cap(h, radius=6.0):
    return math.pi * h**2 * (3 * radius - h) / 3


def cap_nut(bore_down=False):
    """``bore_down``: the same solid, its bore's own axis drawn pointing down, into
    its bolt; the bore, its largest round face, sets the frame's axis."""
    dome = Pos(0, 0, 7.75) * Cylinder(6.25, 2.5) + Pos(0, 0, 9.0) * Sphere(6.0)
    dome = dome - Pos(0, 0, -30) * Box(40, 40, 60)
    hexagon = extrude(RegularPolygon(13.0 / math.sqrt(3), 6), 6.5)
    bore = Cylinder(BORE, 12)
    return hexagon + dome - Pos(0, 0, 6) * (Rot(180, 0, 0) * bore if bore_down else bore)


PLATE = Pos(0, 0, -5) * Box(60, 60, 10) - Cylinder(4.5, 30)
BOLT = Pos(0, 0, -11.5) * Box(13, 13, 2) + Pos(0, 0, -2.5) * Cylinder(4, 15)  # end at 5
POCKET = Pos(0, 0, 4) * (Box(60, 60, 8) - Cylinder(8.0, 8))
RULES = [
    {"parts": "nut", "kind": "nut", "size": "M8"},
    {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"},
]


def cover(underside):
    return Pos(0, 0, underside + 5) * Box(60, 60, 10)


def run(parts, engine, rules=RULES, kit="metric-home"):
    config = Config.from_dict({"fasteners": rules, "checks": {"detect": False}})
    report = check(Assembly([Part(n, s) for n, s in parts]), config, engine=engine, kit=kit)
    return next(r for r in report.results if r.name == "nut")


def joint(*extra, bolt=True):
    parts = [("plate", PLATE), ("nut", cap_nut()), *extra]
    return [*parts, ("bolt", BOLT)] if bolt else parts


def clash(name, volume):
    return f"drawn into {name} ({volume:.1f} mm^3): fix the model"


# ---------------------------------------------------------------------------
# The issue's cap nut.
# ---------------------------------------------------------------------------


def test_a_cover_into_its_dome_is_a_clash(engine):
    # The cover 2 into the dome, z 13 up: cap(2) = 67.02. It blocked the spanner.
    result = run(joint(("pocket", POCKET), ("cover", cover(13.0))), engine)
    assert (result.verdict, result.reason) == (Verdict.NOT_COVERED, clash("cover", cap(2)))


def test_its_dome_s_top_inside_the_thread_s_reach_is_measured(engine):
    # The cover 1 into the dome, z 14 up, all of it inside 1.25 of the bore (4.15):
    # the bore stops at 12, so it is no thread. cap(1) = 17.80.
    result = run(joint(("pocket", POCKET), ("cover", cover(14.0))), engine)
    assert result.reason == clash("cover", cap(1))


def test_a_cover_clear_of_its_dome_blocks_it(engine):
    result = run(joint(("pocket", POCKET), ("cover", cover(16.0))), engine)
    assert (result.verdict, result.reason) == (Verdict.BLOCKED, None)
    assert set(result.blockers) == {"pocket", "cover"}


def test_a_dome_buried_both_ends_covered_is_told_whole(engine):
    # The cover from z 7: the collar from 7 to 9, pi 6.25^2 2 = 245.44, and the
    # dome's half sphere, 452.39, less the bore from 7 to 12, pi 3.3235^2 5 = 173.50:
    # 524.33, told as 176.0 before. No tool finds its end: its bolt's head is below.
    result = run(joint(("cover", cover(7.0))), engine)
    volume = math.pi * 6.25**2 * 2 + 2 / 3 * math.pi * 6**3 - math.pi * BORE**2 * 5
    assert result.reason == clash("cover", volume)


def test_with_no_bolt_to_say_its_free_end_its_hex_and_widest_region_are_measured(engine):
    # Both ends covered and no bolt: its region as before, the hex and what of the
    # dome is wider than 0.75 of the hex's corner radius (5.63): 176.0.
    result = run(joint(("cover", cover(7.0)), bolt=False), engine, rules=RULES[:1])
    assert result.reason == clash("cover", 176.0)


@pytest.mark.parametrize(("underside", "volume"), [(13.0, cap(2)), (7.0, None)])
def test_turned_over_it_reads_the_same(engine, underside, volume):
    if volume is None:
        volume = math.pi * 6.25**2 * 2 + 2 / 3 * math.pi * 6**3 - math.pi * BORE**2 * 5
    turned = Rot(25, -15, 0) * Rot(180, 0, 0)
    extra = [("cover", cover(underside))] + ([("pocket", POCKET)] if underside > 10 else [])
    parts = [(n, turned * s) for n, s in joint(*extra)]
    assert run(parts, engine).reason == clash("cover", volume)


@pytest.mark.parametrize(("underside", "pocket"), [(13.0, True), (7.0, False)])
def test_its_own_axis_drawn_into_its_bolt_it_reads_the_same(engine, underside, pocket):
    # Turning a nut over turns its own axis too; drawn this way, its frame's axis
    # points from its dome into its bolt, and its free end is the frame's low end.
    flipped = cap_nut(bore_down=True)
    nut = Fastener(name="nut", kind=Kind.NUT, size=Size.parse("M8"))
    assert _frame(Part("nut", flipped), nut).direction == pytest.approx((0, 0, -1))
    extra = [("cover", cover(underside))] + ([("pocket", POCKET)] if pocket else [])
    parts = [("plate", PLATE), ("nut", flipped), *extra, ("bolt", BOLT)]
    volume = (
        cap(2)
        if pocket
        else (math.pi * 6.25**2 * 2 + 2 / 3 * math.pi * 6**3 - math.pi * BORE**2 * 5)
    )
    assert run(parts, engine).reason == clash("cover", volume)


# ---------------------------------------------------------------------------
# What stays out, and other nuts.
# ---------------------------------------------------------------------------


def test_a_gland_s_dome_is_measured_and_its_stub_not(engine):
    # A gland (hex 24, z 0 to 8, dome 10 round to 22, stub 10 round under it, bored
    # 9 through) on a wall drawn whole, its stub in it: 3006.5 mm^3 of thread, no
    # clash. A pocket 14.5 round its hex, of the wall's solid to z 4 and the cover's
    # above, leaves no spanner on and stops both; the cover's slab from z 20, 2 into
    # its dome: pi (10^2 - 4.5^2) 2 = 501.1. A gland takes no socket, so the parts
    # its spanner meets, where it grips, are all the clash is asked of.
    pocket = Box(80, 80, 4) - Cylinder(14.5, 4)
    wall = Pos(0, 0, -10) * Box(80, 80, 20) + Pos(0, 0, 2) * pocket
    lid = cover(20.0) + Pos(0, 0, 12) * (Box(80, 80, 16) - Cylinder(14.5, 16))
    parts = [("wall", wall), ("nut", gland()), ("cover", lid)]
    rules = [{"parts": "nut", "kind": "nut", "size": "M16", "socket": False}]
    result = run(parts, engine, rules=rules, kit="full")
    assert result.reason == clash("cover", math.pi * (10**2 - 4.5**2) * 2)


def test_a_nut_s_collar_past_its_widest_region_is_measured(engine):
    # A plain 13 nut, z 0 to 6.5, and a collar 5.5 round (under 0.75 of its corners'
    # 7.51) to z 9, bored 6.647 through: a cover from z 7.5 meets the collar only,
    # pi (5.5^2 - 3.3235^2) 1.5 = 90.50. It was blocked by the cover.
    collar = Pos(0, 0, 7.75) * Cylinder(5.5, 2.5)
    nyloc = extrude(RegularPolygon(13.0 / math.sqrt(3), 6), 6.5) + collar
    nyloc = nyloc - Cylinder(BORE, 40)
    parts = [("plate", PLATE), ("nut", nyloc), ("pocket", POCKET), ("cover", cover(7.5))]
    parts.append(("bolt", BOLT))
    result = run(parts, engine)
    assert result.reason == clash("cover", math.pi * (5.5**2 - BORE**2) * 1.5)
