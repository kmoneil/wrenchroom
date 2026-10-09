"""A set screw's thread is no clash; its core is (issue #122).

A set screw stopped by the part tapped for it was told as drawn into that part:
the clash was measured on all of it, and a set screw is all thread, drawn at its
nominal in a hole drawn at its minor. A screw with a head has its shank left out
(#63, #116); a set screw has neither. Now its clash is measured on its core: all
of it inside its thread's minor diameter, its whole length.

The screw, worked by hand: an M3x4 set screw, 3.0 across, z -4 to 0, a 1.5 hex
socket 1.5 deep (its corners 0.866 round). M3's minor, ISO 724's d3, is
3 - 1.226869 x 0.5 = 2.387, so its core is 1.1934 - 0.05 = 1.1434 round. The hub
is tapped through it, z -20 to 0, and a lid of the hub's own solid closes over
the screw 0.5 above it, so the key is stopped and the clash asked of the hub.
"""

import math

import pytest
from build123d import Box, Cylinder, Pos, RegularPolygon, Rot, extrude

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict

CORE = (3 - 1.226869 * 0.5) / 2 - 0.05  # 1.1434
SET_RULE = {"parts": "set", "kind": "screw", "head": "set", "size": "M3"}


def set_screw(d=3.0, length=4.0, key=1.5, depth=1.5):
    body = Pos(0, 0, -length / 2) * Cylinder(d / 2, length)
    socket = Pos(0, 0, -depth) * extrude(RegularPolygon(key / math.sqrt(3), 6), depth + 0.01)
    return body - socket


def hub(hole, lid=True):
    """The block tapped through, the hole ``hole`` across; and its lid 0.5 over the screw."""
    block = Pos(0, 0, -10) * Box(30, 30, 20) - Pos(0, 0, -10) * Cylinder(hole / 2, 21)
    return block + Pos(0, 0, 5.5) * Box(30, 30, 10) if lid else block


def run(parts, engine, rules=(SET_RULE,), kit="metric-home"):
    config = Config.from_dict({"fasteners": list(rules), "checks": {"detect": False}})
    report = check(Assembly([Part(n, s) for n, s in parts]), config, engine=engine, kit=kit)
    return next(r for r in report.results if r.name == "set")


def ring(outer, inner, length=4.0):
    return math.pi * (outer**2 - inner**2) * length


# ---------------------------------------------------------------------------
# Its thread is no clash.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hole", [2.387, 2.459, 2.5, 3.0])
def test_a_set_screw_in_its_tapped_hole_is_blocked_by_it(engine, hole):
    # At its minor (d3), the nut's minor (D1), a tap drill, the nominal: each was
    # "drawn into hub" but the last, and the M3 at d3 10.4 mm^3.
    result = run([("set", set_screw()), ("hub", hub(hole))], engine)
    assert (result.verdict, result.reason, result.blockers) == (Verdict.BLOCKED, None, ("hub",))


def test_the_issue_s_lid_apart_and_one_with_the_hub_read_alike(engine):
    apart = [("set", set_screw()), ("hub", hub(2.387, lid=False))]
    apart.append(("lid", Pos(0, 0, 5.5) * Box(30, 30, 10)))
    assert run(apart, engine).blockers == ("lid",)
    assert run([("set", set_screw()), ("hub", hub(2.387))], engine).blockers == ("hub",)


# ---------------------------------------------------------------------------
# Its core is a clash.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hole", "volume"), [(2.0, ring(CORE, 1.0)), (2.2, ring(CORE, 1.1)), (1.8, ring(CORE, 0.9))]
)
def test_a_hole_drawn_inside_its_minor_is_drawn_into_it(engine, hole, volume):
    # 3.87, 1.23 and 6.25 mm^3: the hub inside the core's 1.1434, the screw's
    # length. The socket's corners, 0.866 round, are inside every hole.
    result = run([("set", set_screw()), ("hub", hub(hole))], engine)
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == f"drawn into hub ({volume:.1f} mm^3): fix the model"


def test_a_peg_drawn_into_its_core_is_drawn_into_it(engine):
    # The lid apart, a peg 1.4 across down from it to z -3: through the socket
    # (inside its 0.75 flats), then 1.5 into the screw's core: pi 0.7^2 1.5 = 2.31.
    lid = Pos(0, 0, 5.5) * Box(30, 30, 10) + Pos(0, 0, -1.25) * Cylinder(0.7, 3.5)
    parts = [("set", set_screw()), ("hub", hub(2.387, lid=False)), ("lid", lid)]
    result = run(parts, engine)
    volume = math.pi * 0.7**2 * 1.5
    assert result.reason == f"drawn into lid ({volume:.1f} mm^3): fix the model"


def test_a_set_screw_of_no_size_takes_its_minor_as_its_drawn_over_1_4(engine):
    # Keyed by its socket alone: its core is 1.5 / 1.4 - 0.05 = 1.0214. A hole 2.2
    # across is outside it, where an M3's core (1.1434) would meet it; one 2.0
    # across is inside it, ring(1.0214, 1.0) = 0.54 mm^3.
    rule = {"parts": "set", "kind": "screw", "head": "set", "across_flats": 1.5}
    result = run([("set", set_screw()), ("hub", hub(2.2))], engine, rules=[rule])
    assert (result.verdict, result.blockers) == (Verdict.BLOCKED, ("hub",))
    result = run([("set", set_screw()), ("hub", hub(2.0))], engine, rules=[rule])
    volume = ring(1.5 / 1.4 - 0.05, 1.0)
    assert result.reason == f"drawn into hub ({volume:.1f} mm^3): fix the model"


def test_an_inch_set_screw_takes_its_own_minor(engine):
    # A #8-32 (0.164 in, 4.166): d3 4.166 - 1.226869 x 25.4 / 32 = 3.192. Drawn in
    # a hole at its minor: blocked; in one 2.8 across, inside its core (1.546),
    # drawn in: ring(1.546, 1.4) over its 6 mm.
    rule = {"parts": "set", "kind": "screw", "head": "set", "size": "#8"}
    screw = set_screw(d=4.166, length=6.0, key=5 / 64 * 25.4, depth=2.0)
    result = run([("set", screw), ("hub", hub(3.192))], engine, rules=[rule], kit="full")
    assert (result.verdict, result.blockers) == (Verdict.BLOCKED, ("hub",))
    result = run([("set", screw), ("hub", hub(2.8))], engine, rules=[rule], kit="full")
    core = (4.166 - 1.226869 * 25.4 / 32) / 2 - 0.05
    assert result.reason == f"drawn into hub ({ring(core, 1.4, 6.0):.1f} mm^3): fix the model"


@pytest.mark.parametrize("hole", [2.387, 2.0])
def test_drawn_socket_down_and_turned_over_it_reads_the_same(engine, hole):
    turned = Rot(35, 20, 0) * Rot(180, 0, 0)
    parts = [("set", turned * set_screw()), ("hub", turned * hub(hole))]
    result = run(parts, engine)
    if hole == 2.0:
        assert result.reason == f"drawn into hub ({ring(CORE, 1.0):.1f} mm^3): fix the model"
    else:
        assert (result.verdict, result.blockers) == (Verdict.BLOCKED, ("hub",))


def test_detected_by_its_name_it_reads_the_same(engine):
    parts = [("set screw M3x4", set_screw()), ("hub", hub(2.387))]
    report = check(Assembly([Part(n, s) for n, s in parts]), Config.from_dict({}), engine=engine)
    (result,) = report.results
    assert (result.fastener.head.value, result.fastener.size.designation) == ("set", "M3")
    assert (result.verdict, result.blockers) == (Verdict.BLOCKED, ("hub",))
