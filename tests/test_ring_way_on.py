"""A ring gets on along the axis, over the end of the bolt through it (issue #121).

A ring was tried as an annulus round the hex at the hex's mid-plane, its thickness
held to the hex's. That is where it grips, not how it gets there: a ring is
closed, so it comes down the axis over the fastener's end, and over the end of
the bolt sticking out of a nut. A part over a nut's end stopped a socket and a
nut driver, whose bodies run up the axis, but not the ring, at any gap.

Now the ring's way on is part of its engagement: its annulus from where it grips
up to its own full thickness past the bolt's end, where it can come in from the
side.

And past the end of whatever the nut is on, named or not, and with its handle
(issue #143): a stud no rule names was measured only to the nut's own end, and the
way on was the ring's annulus alone, though its handle comes down the axis with it.

The joint, worked by hand: an M8 nut, 13 across flats and 6.5 high (z 0 to 6.5),
on a bolt through a plate (z -10 to 0), the bolt's end at z 8 unless said. A
13 mm spanner's ring is 5.4 thick (0.3 af + 1.5), from 7.81 (the corners' 7.51
and 0.3) to 12.4 (0.8 af + 2) round the axis. It needs the annulus clear up to
the bolt's end and 5.4 more: z 13.4. The cover over the nut has a hole 9 across
for the bolt's end, inside the ring's bore, so only the ring can meet it.
"""

import math

import pytest
from build123d import Box, Cylinder, Polygon, Pos, RegularPolygon, Rot, Sphere, extrude

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import _runs_up, _through, check
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.solids import AxialRing, RadialBox
from wrenchroom.tools.sweep import Mount

T = 5.4  # the 13 mm ring's thickness
NUT_TOP = 6.5
RING, STUBBY, OPEN = "ring, full length", "ring, stubby", "open end, full length"


def nut():
    return extrude(RegularPolygon(13.0 / math.sqrt(3), 6), NUT_TOP) - Cylinder(6.647 / 2, 40)


def bolt(end=8.0):
    """A hex bolt up through the plate, its head under it, its end at z ``end``."""
    head = Pos(0, 0, -15.3) * extrude(RegularPolygon(13.0 / math.sqrt(3), 6), 5.3)
    return head + Pos(0, 0, (end - 10) / 2) * Cylinder(4, end + 10)


def cover(underside, hole=4.5):
    """A slab over the nut, its underside at ``underside``, a hole for the bolt's end."""
    slab = Pos(0, 0, underside + 5) * Box(60, 60, 10)
    return slab - Cylinder(hole, 200) if hole else slab


PLATE = Pos(0, 0, -5) * Box(60, 60, 10) - Cylinder(4.5, 30)
RULES = [
    {"parts": "nut", "kind": "nut", "size": "M8"},
    {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"},
]


def run(parts, engine, rules=RULES, name="nut", **extra):
    config = Config.from_dict({"fasteners": rules, "checks": {"detect": False}, **extra})
    report = check(Assembly([Part(n, s) for n, s in parts]), config, engine=engine)
    return next(r for r in report.results if r.name == name)


def attempt(result, way):
    (found,) = [a for a in result.attempts if a.way == way]
    return found


def joint(underside, end=8.0):
    return [("plate", PLATE), ("bolt", bolt(end)), ("nut", nut()), ("cover", cover(underside))]


# ---------------------------------------------------------------------------
# The issue's gaps, and where the way on ends.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gap", "how"), [(1.5, OPEN), (3.0, OPEN), (6.0, OPEN), (10.0, RING), (20.0, RING)]
)
def test_the_issue_s_gaps(engine, gap, how):
    # Each turned with a ring before, at every gap. The way on ends at 13.4: the
    # 6 mm gap (12.5) is short of it, the 10 mm (16.5) past it.
    result = run(joint(NUT_TOP + gap), engine)
    assert (result.verdict, result.tool, result.how) == (Verdict.TURNS, "spanner-13", how)


@pytest.mark.parametrize("engine", ["exact", "mesh"])
def test_a_ring_short_of_its_way_on_says_what_is_in_it(engine):
    result = run(joint(NUT_TOP + 3.0), engine)
    for way in (RING, STUBBY):
        ring = attempt(result, way)
        assert not ring.turns
        assert not ring.holds
        assert ring.blockers == ("cover",)


@pytest.mark.parametrize(("underside", "on"), [(13.4 - 0.3, False), (13.4 + 0.3, True)])
def test_the_way_on_ends_a_ring_s_thickness_past_the_bolt_s_end(engine, underside, on):
    assert attempt(run(joint(underside), engine), RING).turns is on


@pytest.mark.parametrize(("underside", "on"), [(25.4 - 0.3, False), (25.4 + 0.3, True)])
def test_a_longer_bolt_needs_more_room(engine, underside, on):
    # The bolt's end at 20: the ring clears it at 25.4. A cover at 13.7, past the
    # 8 mm bolt's 13.4, would stop this one.
    assert attempt(run(joint(underside, end=20.0), engine), RING).turns is on


#: A wedge 60 degrees either side of +x, through anything over the joint: room for the
#: handle at 0, 15 and 30 degrees round, coming down (issue #143).
SLOT = Pos(0, 0, -50) * extrude(Polygon((0, 0), (200, -346), (200, 346), align=None), 200)


@pytest.mark.parametrize(
    ("hole", "slot", "on"),
    [(10.0, True, False), (12.0, True, False), (12.7, True, True), (12.7, False, False)],
)
def test_the_way_on_is_the_ring_s_own_annulus(engine, hole, slot, on):
    # A cover 3 over the nut with a hole: the ring's bore (7.81) passes one 10 or
    # 12 in radius, the ring (12.4) doesn't; one 12.7 lets the whole ring through,
    # and its handle too where a slot lets it down.
    over = cover(NUT_TOP + 3.0, hole=hole)
    parts = [*joint(0.0)[:3], ("cover", over - SLOT if slot else over)]
    assert attempt(run(parts, engine), RING).turns is on


@pytest.mark.parametrize(("sleeve", "on"), [((7.0, 7.6), True), ((8.0, 9.5), False)])
def test_the_way_on_runs_from_the_ring_s_bore_out(engine, sleeve, on):
    # A sleeve over the bolt's end, z 8 to 40: one inside the ring's bore (7.81)
    # lets it by, one in its annulus stops it, however high.
    inside, outside = sleeve
    tube = Pos(0, 0, 24) * (Cylinder(outside, 32) - Cylinder(inside, 33))
    parts = [*joint(0.0)[:3], ("sleeve", tube)]
    assert attempt(run(parts, engine), RING).turns is on


@pytest.mark.parametrize("covered", [True, False])
def test_a_ring_must_get_down_past_a_cap_nut_s_dome(engine, covered):
    # An M8 cap nut, its hex z 0 to 6.5, a collar 6.25 round to 9 and a dome to 15,
    # narrower than the ring's bore. A cover 3 thick, z 9 to 12, its hole 8.5 round
    # the dome: the ring, coming down over the dome, meets it below the dome's top.
    dome = Pos(0, 0, 7.75) * Cylinder(6.25, 2.5) + Pos(0, 0, 9.0) * Sphere(6.0)
    dome = dome - Pos(0, 0, -30) * Box(40, 40, 60)
    cap_nut = nut() + dome - Pos(0, 0, 6) * Cylinder(6.647 / 2, 12)
    parts = [("plate", PLATE), ("bolt", bolt(5.0)), ("nut", cap_nut)]
    if covered:
        parts.append(("cover", Pos(0, 0, 10.5) * (Box(60, 60, 3) - Cylinder(8.5, 4))))
    result = run(parts, engine)
    assert attempt(result, RING).turns is not covered
    assert (result.verdict, result.how) == (Verdict.TURNS, OPEN if covered else RING)


def test_a_bolt_into_the_cover_leaves_no_ring_on(engine):
    # The bolt runs on up into the cover's hole: no ring comes down over its end,
    # however high the cover's underside, short of the bolt's end and a ring more.
    result = run(joint(16.0, end=40.0), engine)
    assert attempt(result, RING).blockers == ("cover",)
    assert (result.verdict, result.how) == (Verdict.TURNS, OPEN)


@pytest.mark.parametrize(
    ("underside", "on"), [(NUT_TOP + T - 0.3, False), (NUT_TOP + T + 0.3, True)]
)
def test_a_nut_with_no_bolt_through_it_needs_a_ring_past_its_own_end(engine, underside, on):
    parts = [("plate", PLATE), ("nut", nut()), ("cover", cover(underside, hole=None))]
    result = run(parts, engine, rules=RULES[:1])
    assert attempt(result, RING).turns is on


def test_a_bolt_taken_off_in_its_state_is_no_bolt_to_clear(engine):
    # A cover at 12.5: past the nut's own end and a ring (11.9), short of the
    # bolt's (13.4). With the bolt off, in the nut's state, the ring gets on.
    rules = [{**RULES[0], "state": "bolt_out"}, RULES[1]]
    states = {"states": {"bolt_out": {"remove": ["bolt"]}}}
    assert attempt(run(joint(12.5), engine), RING).turns is False
    result = run(joint(12.5), engine, rules=rules, **states)
    assert (result.verdict, result.how, result.state) == (Verdict.TURNS, RING, "bolt_out")


@pytest.mark.parametrize(("underside", "on"), [(5.3 + T - 0.3, False), (5.3 + T + 0.3, True)])
def test_a_hex_head_s_ring_clears_the_head(engine, underside, on):
    # A hex bolt head up (z 0 to 5.3), its nut under the plate: the nut is on the
    # far side, so the ring clears the head alone, by its thickness.
    head = extrude(RegularPolygon(13.0 / math.sqrt(3), 6), 5.3)
    up = head + Pos(0, 0, -10) * Cylinder(4, 20)
    under = Pos(0, 0, -10) * Rot(180, 0, 0) * nut()
    parts = [("plate", PLATE), ("bolt", up), ("nut", under), ("cover", cover(underside, None))]
    result = run(parts, engine, name="bolt")
    assert attempt(result, RING).turns is on


@pytest.mark.parametrize(("gap", "how"), [(3.0, OPEN), (10.0, RING)])
def test_a_joint_turned_over_reads_the_same(engine, gap, how):
    turned = Rot(30, 20, 0)
    parts = [(n, turned * s) for n, s in joint(NUT_TOP + gap)]
    result = run(parts, engine)
    assert (result.verdict, result.how) == (Verdict.TURNS, how)


# ---------------------------------------------------------------------------
# The bolt's end, as measured.
# ---------------------------------------------------------------------------


def test_the_bolt_s_end_is_measured_past_the_seat_along_the_axis():
    mount = Mount(seat=(0.0, 0.0, NUT_TOP), axis=(0.0, 0.0, 1.0))
    assert _through(mount, Part("bolt", bolt(8.0))) == pytest.approx(1.5)
    assert _through(mount, Part("bolt", bolt(20.0))) == pytest.approx(13.5)
    down = Mount(seat=(0.0, 0.0, -15.3), axis=(0.0, 0.0, -1.0))  # from its head's side
    assert _through(down, Part("bolt", bolt(8.0))) == 0.0


# ---------------------------------------------------------------------------
# What the view draws.
# ---------------------------------------------------------------------------


def test_its_way_on_is_drawn_only_where_it_stops_the_ring(engine):
    # Stopped on its way: its grip, clear, and its way on, which met the cover.
    grip, way_on = attempt(run(joint(NUT_TOP + 3.0), engine), RING).probes
    assert (grip.hits, way_on.hits) == ((), ("cover",))
    top = max(p.z1 for p in way_on.solid.primitives if isinstance(p, AxialRing))
    assert top == pytest.approx(1.5 + T)  # the bolt's end past the seat, and a ring
    # Got on: its grip and its handle, and no way on drawn over the nut.
    turned = attempt(run(joint(NUT_TOP + 10.0), engine), RING)
    tops = [p.z1 for p in turned.probes[0].solid.primitives if isinstance(p, AxialRing)]
    assert max(tops) <= 0.0
    assert all(not isinstance(p, AxialRing) for q in turned.probes[1:] for p in q.solid.primitives)


def test_a_ring_stopped_where_it_grips_says_so_as_before(engine):
    # A rib beside the nut, 10 to 20 off its axis, in the ring's 7.81 to 12.4 but
    # clear of its corners (7.81): the ring is stopped where it grips, and says
    # so, though the cover 3 over the nut is in its way on too.
    rib = Pos(15, 0, 3) * Box(10, 40, 6)
    result = run([*joint(NUT_TOP + 3.0), ("rib", rib)], engine)
    ring = attempt(result, RING)
    assert ring.blockers == ("rib",)
    assert len(ring.probes) == 1


# ---------------------------------------------------------------------------
# Whatever the nut is on, named or not (issue #143).
# ---------------------------------------------------------------------------


def stud(end=8.0):
    """A stud no rule names, up through the plate from z -10 to ``end``."""
    return Pos(0, 0, (end - 10) / 2) * Cylinder(4, end + 10)


def stud_joint(underside, end=8.0):
    return [("plate", PLATE), ("stud", stud(end)), ("nut", nut()), ("cover", cover(underside))]


def test_a_stud_on_up_through_a_cover_leaves_no_ring_on(engine):
    # The issue's first joint: the stud runs on to z 60, through a cover 40 over the
    # nut. The ring used to turn the nut, the stud measured to the nut's own end.
    result = run(stud_joint(NUT_TOP + 40.0, end=60.0), engine, rules=RULES[:1])
    ring = attempt(result, RING)
    assert (ring.turns, ring.holds, ring.blockers) == (False, False, ("cover",))
    assert (result.verdict, result.how) == (Verdict.TURNS, OPEN)


@pytest.mark.parametrize(("underside", "on"), [(13.4 - 0.3, False), (13.4 + 0.3, True)])
def test_a_stud_no_rule_names_is_cleared_as_a_bolt_is(engine, underside, on):
    # Its end at 8, as the bolt's: the ring clears it at 13.4. Measured to the nut's
    # own end, the ring would clear 11.9.
    result = run(stud_joint(underside), engine, rules=RULES[:1])
    assert attempt(result, RING).turns is on


@pytest.mark.parametrize(("underside", "on"), [(25.4 - 0.3, False), (25.4 + 0.3, True)])
def test_a_tube_through_the_nut_is_cleared_as_a_rod_is(engine, underside, on):
    # A tube 2 inside and 4 outside, up through the nut to z 20: its end, 13.5 past
    # the nut, is cleared at 25.4, as a rod's is.
    tube = Pos(0, 0, 5) * (Cylinder(4, 30) - Cylinder(2, 31))
    parts = [("plate", PLATE), ("tube", tube), ("nut", nut()), ("cover", cover(underside))]
    assert attempt(run(parts, engine, rules=RULES[:1]), RING).turns is on


@pytest.mark.parametrize(("underside", "on"), [(13.4 - 0.3, False), (13.4 + 0.3, True)])
def test_a_stud_welded_to_the_plate_is_measured_from_the_nut_up(engine, underside, on):
    # One part, the plate and its stud: the plate spreads far past the ring's bore,
    # under the nut. The stud's end, at 8, is what the ring clears.
    welded = Pos(0, 0, -5) * Box(60, 60, 10) + Pos(0, 0, -1) * Cylinder(4, 18)
    parts = [("plate", welded), ("nut", nut()), ("cover", cover(underside))]
    assert attempt(run(parts, engine, rules=RULES[:1]), RING).turns is on


@pytest.mark.parametrize(("underside", "on"), [(17.4 - 0.3, False), (17.4 + 0.3, True)])
def test_a_stud_is_cleared_all_of_it_within_the_ring_s_bore(engine, underside, on):
    # The stud's end is a cup, one part with it: its rim, at z 12, 5 to 6 round the
    # axis, is past the nut's bore (3.32) and inside the ring's (7.81). The ring
    # clears the rim at 17.4.
    cup = Pos(0, 0, 10) * (Cylinder(6, 4) - Pos(0, 0, 1) * Cylinder(5, 4))
    parts = [("plate", PLATE), ("stud", stud() + cup), ("nut", nut()), ("cover", cover(underside))]
    assert attempt(run(parts, engine, rules=RULES[:1]), RING).turns is on


def test_a_part_across_the_axis_further_up_is_no_end_to_clear(engine):
    # One part: a plate, its stud up through the nut to z 8, a post 25 off the axis
    # and a bridge from it over the nut, z 30 to 35, a hole 10 across on the axis.
    # The ring clears the stud's end at 13.4 and comes in from the side under the
    # bridge: the bridge, up the axis apart from the stud, is not what the nut is on.
    frame = (
        Pos(0, 0, -5) * Box(60, 60, 10)
        + Pos(0, 0, -1) * Cylinder(4, 18)
        + Pos(25, 0, 15) * Box(6, 6, 30)
        + Pos(0, 0, 32.5) * (Box(60, 20, 5) - Cylinder(5, 10))
    )
    result = run([("frame", frame), ("nut", nut())], engine, rules=RULES[:1])
    assert (result.verdict, result.how) == (Verdict.TURNS, RING)


def test_a_stud_taken_off_in_its_state_is_no_stud_to_clear(engine):
    # A cover at 12.5: past the nut's own end and a ring (11.9), short of the stud's
    # (13.4). With the stud off, in the nut's state, the ring gets on.
    rules = [{**RULES[0], "state": "stud_out"}]
    states = {"states": {"stud_out": {"remove": ["stud"]}}}
    assert attempt(run(stud_joint(12.5), engine, rules=RULES[:1]), RING).turns is False
    result = run(stud_joint(12.5), engine, rules=rules, **states)
    assert (result.verdict, result.how, result.state) == (Verdict.TURNS, RING, "stud_out")


@pytest.mark.parametrize(("end", "how"), [(60.0, OPEN), (8.0, RING)])
def test_a_stud_turned_over_reads_the_same(engine, end, how):
    turned = Rot(30, 20, 0)
    parts = [(n, turned * s) for n, s in stud_joint(NUT_TOP + 40.0, end=end)]
    result = run(parts, engine, rules=RULES[:1])
    assert (result.verdict, result.how) == (Verdict.TURNS, how)


def test_what_runs_up_through_the_bore_is_measured_past_the_seat_along_the_axis():
    # From the hex's middle, 3.25 under the seat, within the 13 ring's bore, 7.81.
    mount = Mount(seat=(0.0, 0.0, NUT_TOP), axis=(0.0, 0.0, 1.0))
    assert _runs_up(mount, Part("stud", stud(8.0)), 7.81, -3.25) == pytest.approx(1.5)
    assert _runs_up(mount, Part("stud", stud(20.0)), 7.81, -3.25) == pytest.approx(13.5)
    assert _runs_up(mount, Part("stud", stud(4.0)), 7.81, -3.25) == 0.0  # ends in the nut
    down = Mount(seat=(0.0, 0.0, 0.0), axis=(0.0, 0.0, -1.0))  # out of its other face
    assert _runs_up(down, Part("stud", stud(8.0)), 7.81, -3.25) == pytest.approx(10.0)


def test_only_the_piece_running_up_from_inside_the_nut_is_measured():
    # One part, in pieces within the ring's bore: what is in the nut, a disc resting
    # on its face (drawn 0.005 into it, as a model's parts often are), and a disc
    # further up. Only the first runs through it.
    mount = Mount(seat=(0.0, 0.0, NUT_TOP), axis=(0.0, 0.0, 1.0))
    resting = Pos(0, 0, NUT_TOP - 0.005 + 1.5) * Cylinder(6, 3)
    further = Pos(0, 0, 30) * Cylinder(6, 4)
    assert _runs_up(mount, Part("stud", stud(8.0) + further), 7.81, -3.25) == pytest.approx(1.5)
    assert _runs_up(mount, Part("stud", stud(4.0) + resting), 7.81, -3.25) == 0.0


# ---------------------------------------------------------------------------
# The handle comes down with the ring (issue #143).
# ---------------------------------------------------------------------------


def tube(bottom, inside=15.0, outside=25.0, height=60.0):
    """A tube round the joint's axis, from z ``bottom`` up."""
    ring = Cylinder(outside, height) - Cylinder(inside, height + 1)
    return Pos(0, 0, bottom + height / 2) * ring


@pytest.mark.parametrize(("inside", "outside"), [(15.0, 25.0), (12.7, 14.0)])
def test_a_tube_the_ring_fits_down_stops_its_handle(engine, inside, outside):
    # The issue's second joint: a tube 3.5 over the nut, 15 inside, room for the
    # ring (12.4 round) but not its handle, which comes down the axis with it, from
    # the ring's edge out: a tube just round the ring stops it too.
    hollow = tube(NUT_TOP + 3.5, inside=inside, outside=outside)
    result = run([*joint(0.0)[:3], ("tube", hollow)], engine)
    ring = attempt(result, RING)
    assert (ring.turns, ring.holds, ring.blockers) == (False, False, ("tube",))
    assert (result.verdict, result.how) == (Verdict.TURNS, OPEN)


@pytest.mark.parametrize(("bottom", "on"), [(13.4 - 0.3, False), (13.4 + 0.3, True)])
def test_the_handle_comes_down_as_far_as_the_ring(engine, bottom, on):
    # The ring comes in from the side at 13.4, the bolt's end and a ring past it, and
    # its handle with it.
    assert attempt(run([*joint(0.0)[:3], ("tube", tube(bottom))], engine), RING).turns is on


def test_a_handle_s_way_down_that_only_grazes_says_so(engine):
    # The tube's underside 0.0002 under the handle's way down, at 13.4: some 0.03
    # mm^3 of it at each angle, under the hit floor. The ring gets on, and says what
    # its handle grazed.
    result = run([*joint(0.0)[:3], ("tube", tube(13.4 - 0.0002))], engine)
    assert (result.verdict, result.how, result.grazes) == (Verdict.TURNS, RING, ("tube",))


def test_a_stubby_s_shorter_handle_comes_down_where_a_full_length_s_does_not(engine):
    # A tube 100 inside: past the stubby's handle, 95.0 (0.85 of its 111.8), short
    # of the full length's, 175.2.
    wide = tube(NUT_TOP + 3.5, inside=100.0, outside=120.0)
    result = run([*joint(0.0)[:3], ("tube", wide)], engine)
    assert attempt(result, RING).turns is False
    assert attempt(result, STUBBY).turns is True
    assert (result.verdict, result.how) == (Verdict.TURNS, STUBBY)


@pytest.mark.parametrize(("width", "holds"), [(16.0, True), (10.0, False)])
def test_a_handle_let_down_at_one_angle_only_holds(engine, width, holds):
    # The cover's hole passes the ring, and a slot 16 wide along +x its handle, 13.7
    # wide, at that one angle: 15 degrees round, the handle meets the slot's side.
    # The ring gets on and holds, but can't swing; the open end turns the nut. A slot
    # 10 wide lets the handle down at no angle.
    slot = Pos(100, 0, 0) * Box(200, width, 100)
    parts = [*joint(0.0)[:3], ("cover", cover(NUT_TOP + 3.0, hole=12.7) - slot)]
    result = run(parts, engine)
    ring = attempt(result, RING)
    assert (ring.turns, ring.holds, ring.blockers) == (False, holds, ("cover",))
    assert (result.verdict, result.how) == (Verdict.TURNS, OPEN)


def test_a_handle_that_can_t_come_down_is_no_hand_s_fault(engine):
    # With hand room on: the ring stopped by its handle's way down is stopped itself,
    # not "no room for a hand".
    checks = {"checks": {"detect": False, "hand_room": True}}
    result = run([*joint(0.0)[:3], ("tube", tube(NUT_TOP + 3.5))], engine, **checks)
    ring = attempt(result, RING)
    assert (ring.turns, ring.no_hand_room, ring.hand_blockers) == (False, False, ())
    assert (result.verdict, result.how) == (Verdict.TURNS, OPEN)


def _top(probe):
    """How high up the axis a probe's handle reaches, past the seat."""
    return max(p.z + p.thickness / 2 for p in probe.solid.primitives if isinstance(p, RadialBox))


def test_the_handle_s_way_down_is_drawn_only_where_it_stops_the_ring(engine):
    # Stopped: at each angle its handle, clear, and its way down, to the bolt's end and
    # a ring past the seat, which met the tube.
    stopped = attempt(run([*joint(0.0)[:3], ("tube", tube(NUT_TOP + 3.5))], engine), RING)
    ways = [probe for probe in stopped.probes[1:] if probe.hits]
    handles = [probe for probe in stopped.probes[1:] if not probe.hits]
    assert len(ways) == len(handles) == 24
    assert {probe.hits for probe in ways} == {("tube",)}
    assert {round(_top(probe), 6) for probe in ways} == {round(1.5 + T, 6)}
    # Got on: its handle at each angle tried, and no way down drawn.
    turned = attempt(run(joint(NUT_TOP + 10.0), engine), RING)
    assert turned.turns
    assert all(_top(probe) <= 0.0 for probe in turned.probes[1:])
