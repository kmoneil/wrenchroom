"""The open end of a combination spanner (spec 6.2): the jaw from the side.

The jaw grips two flats and turns with its handle, so each position tests jaw and
handle together, turning on 30 degrees of free swing. First, at no angle, the space
the hex's own corners sweep must be clear: a neighbour inside it stops the hex
turning whatever holds it. The fixtures here are worked by hand.
"""

import math

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.solids import RadialBox
from wrenchroom.tools.spanners import (
    JAW_CLEARANCE,
    JAW_REACH,
    OPEN_RESEAT_DEG,
    RING_CLEARANCE,
    open_jaw,
    spanner_for,
)

R3 = math.sqrt(3)


def _nut():
    """An M8 nut, af 13, 6.5 tall, on z = 0..6.5, corners along x."""
    return hex_prism(13, 6.5) - Cylinder(4, 20)


def nut_pair(apart):
    """Two M8 nuts `apart` mm between centres along x, corner towards corner."""
    return Assembly(
        [
            Part("a_nut", _nut()),
            Part("b_nut", Pos(apart, 0, 0) * _nut()),
            Part("plate", Pos(0, 0, -5) * Box(400, 400, 10)),
        ]
    )


RULE = {"parts": "a_nut", "kind": "nut", "size": "M8", "socket": False}


def run(assembly, rule=RULE, engine="exact", **kwargs):
    config = Config.from_dict({"fasteners": [rule], "checks": {"detect": False}})
    (result,) = check(assembly, config, engine=engine, **kwargs).results
    return result


# ---------------------------------------------------------------------------
# The numbers.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("af", "width_range", "thick_range", "iso_max"),
    [
        # Stahlwille OPEN-BOX and Hazet 600N heads as published (read 2026-10-06),
        # and ISO 3318:2016's maximum head width b1.
        (8, (18.0, 18.5), (4.2, 4.5), 24.0),
        (13, (29.0, 30.0), (5.3, 6.3), 34.0),
        (24, (51.0, 53.0), (7.8, 9.5), 57.0),
    ],
)
def test_the_open_end_is_near_two_makers_heads_and_inside_iso_3318(
    af, width_range, thick_range, iso_max
):
    spanner = spanner_for(af)
    assert width_range[0] - 1.2 <= spanner.open_width <= width_range[1] + 1.2
    assert thick_range[0] - 1.0 <= spanner.open_thickness <= thick_range[1] + 1.0
    assert spanner.open_width <= iso_max


def test_the_jaw_is_two_arms_beside_the_flats_and_a_back():
    spanner = spanner_for(13)
    arm_left, arm_right, back = open_jaw(spanner, 13, 5.0, 3.25, 0.0).primitives
    arm = (spanner.open_width - 13) / 2 - JAW_CLEARANCE
    throat = 13 / R3 + RING_CLEARANCE
    assert arm_left == RadialBox(arm, 5.0, -JAW_REACH * 13, throat, 3.25, 0.0, 6.5 + 0.15 + arm / 2)
    assert arm_right == RadialBox(
        arm, 5.0, -JAW_REACH * 13, throat, 3.25, 0.0, -(6.5 + 0.15 + arm / 2)
    )
    assert back == RadialBox(spanner.open_width, 5.0, throat, spanner.open_width / 2, 3.25, 0.0)
    # The arms' inner faces stand off the flats; the arms and back don't overlap.
    assert arm_left.offset - arm / 2 == pytest.approx(13 / 2 + JAW_CLEARANCE)
    assert arm_left.r1 == back.r0
    assert OPEN_RESEAT_DEG == 30.0


# ---------------------------------------------------------------------------
# Worked cases: two M8 nuts, 13 across flats, corner r 7.5.
# ---------------------------------------------------------------------------


def test_beside_a_neighbour_the_open_end_turns_where_the_ring_cannot(engine):
    # 18 apart: the neighbour's corner is 10.5 from the axis, inside the ring's
    # outer r 12.4, outside the hex's own corners' 7.8. Handle away from it, the
    # tips stop at 6.5; swung 15 deg the arms' outer tips (r 15.9) reach x 10.0 at
    # y 12.3, where the neighbour's edge is at x 17.6.
    result = run(nut_pair(18.0), engine=engine)
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "spanner-13",
        "open end, full length",
    )
    ways = [(a.way, a.turns) for a in result.attempts]
    assert ways == [
        ("ring, full length", False),
        ("ring, stubby", False),
        ("open end, full length", True),
    ]


def test_a_neighbour_inside_the_corners_sweep_stops_the_hex_turning_at_all(engine):
    # 15 apart: the neighbour's corner is 7.5 from the axis, inside the space the
    # hex's corners sweep (to 7.8): nothing can turn it, which the corner sweep,
    # tried alone before any tool, says once (issue #63).
    result = run(nut_pair(15.0), engine=engine)
    assert result.verdict is Verdict.BLOCKED
    assert result.reason == "the nut's corners hit b_nut as it turns"
    (attempt,) = result.attempts
    assert (attempt.way, len(attempt.probes), attempt.blockers) == (
        "its corners, turning",
        1,
        ("b_nut",),
    )


def test_with_room_all_round_the_ring_turns_and_the_open_end_is_never_tried():
    result = run(nut_pair(60.0))
    assert result.how == "ring, full length"
    assert [a.way for a in result.attempts] == ["ring, full length"]


def test_a_forced_spanner_tries_both_ends():
    result = run(nut_pair(18.0), {**RULE, "tool": "spanner-13"})
    assert (result.tool, result.how) == ("spanner-13", "open end, full length")


def test_hand_room_rests_the_hand_on_the_open_end_s_handle():
    # A low ceiling over the handle's far end (beyond r 40): the open end alone
    # turns, the hand on its handle can't follow.
    assembly = nut_pair(18.0)
    ceiling = Pos(-140, 0, 20) * Box(200, 400, 10)  # x from -240 to -40, over the handle
    assembly = Assembly([*assembly.parts, Part("ceiling", ceiling)])
    assert run(assembly).verdict is Verdict.TURNS
    result = run(assembly, hand_room=True)
    assert result.verdict is Verdict.BLOCKED
    assert result.reason == "no room for a hand: the hand hits ceiling on its best arc"
