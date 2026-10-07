"""The parts that decided a verdict, out of all the parts any probe touched (#52).

A fastener's blocked_by was every part any position of any attempt ran into: a
nut whose spanner swings 20 deg of the 30 it needs listed every obstacle round
the sweep, and nothing said which bounded the best arc, or how much it got. Now
each attempt says the best arc it found and what stood at each end of it; the
fastener's blocked_by leads with those of its best attempt (``deciding``), and
the terminal and Markdown name them alone, with how many more the JSON lists.
With hand room, a hand stopped names what it hit along the tool's best arc.

The swing cases are the arm probe of test_sweeps.py: a thin radial arm at z 50,
reaching 100 mm, posts 12 mm square standing 60 out at the arm's height, in 15
deg steps.
"""

import json
import math

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import _deciding, check
from wrenchroom.config import Config
from wrenchroom.fasteners import Fastener, Kind
from wrenchroom.report import FastenerResult, Report, Verdict, attempt_text
from wrenchroom.tools.sweep import (
    Attempt,
    Mount,
    axial_cylinder,
    radial_cylinder,
    swing_attempt,
)

ORIGIN = Mount(seat=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0))


def arm(phi_deg):
    return ORIGIN.place(radial_cylinder(2, 10, 100, 50, phi_deg))


def hand(phi_deg):
    """A block on the arm's far end, as a hand on a handle."""
    return ORIGIN.place(radial_cylinder(6, 80, 100, 60, phi_deg))


def post(phi_deg, z=50.0, size=12.0):
    rad = math.radians(phi_deg)
    return Pos(60 * math.cos(rad), 60 * math.sin(rad), z) * Box(size, size, 20)


def swing(scene, required=60.0, with_hand=False):
    return swing_attempt(
        tool="probe",
        way="probe",
        scene=scene,
        engagement=ORIGIN.place(axial_cylinder(1, 20, 30)),
        arm_at=arm,
        required_deg=required,
        hand_at=hand if with_hand else None,
    )


# ---------------------------------------------------------------------------
# The swing search: what stands at each end of the best arc.
# ---------------------------------------------------------------------------


def test_the_best_arc_s_ends_bound_it(scene_of):
    # Posts every 30 deg but a 45 deg gap between a (100) and b (145): the arm is
    # free at 120 and 135 there, 15 deg; at one angle in every other gap.
    angles = {"a": 100, "b": 145, **{f"p{k}": 145 + 30 * k for k in range(1, 11)}}
    attempt = swing(scene_of(**{name: post(phi) for name, phi in angles.items()}))
    assert (attempt.turns, attempt.holds, attempt.swing_deg) == (False, True, 15.0)
    assert set(attempt.bounds) == {"a", "b"}
    assert len(attempt.blockers) == 12  # every post, hit somewhere round the sweep
    assert attempt.required_deg == 60.0


def test_an_arc_across_zero_is_bounded_on_both_sides(scene_of):
    # The wide gap spans 0: from a at 340 to b at 25.
    angles = {"a": 340, "b": 25, **{f"p{k}": 25 + 30 * k for k in range(1, 11)}}
    attempt = swing(scene_of(**{name: post(phi) for name, phi in angles.items()}))
    assert attempt.swing_deg == 15.0
    assert set(attempt.bounds) == {"a", "b"}


def test_one_part_at_both_ends_is_named_once(scene_of):
    # A wall all round but a 45 deg slot: the arm is free in the slot, the wall
    # both sides of it.
    wall = Pos(0, 0, 50) * (Cylinder(70, 20) - Cylinder(50, 21))
    slot = Pos(60, 0, 50) * Box(30, 2 * 60 * math.tan(math.radians(22.5)), 22)
    attempt = swing(scene_of(wall=wall - slot))
    assert attempt.holds
    assert not attempt.turns
    assert attempt.bounds == ("wall",)


def test_a_turn_or_a_blocked_engagement_or_no_free_angle_has_no_bounds(scene_of):
    assert swing(scene_of(far=post(0, z=500))).bounds == ()  # turns
    capped = swing(scene_of(cap=Pos(0, 0, 27) * Box(50, 50, 10)))  # the engagement
    assert (capped.turns, capped.holds, capped.bounds) == (False, False, ())
    ring = Pos(0, 0, 50) * (Cylinder(70, 20) - Cylinder(50, 21))
    walled = swing(scene_of(ring=ring))  # free nowhere
    assert (walled.holds, walled.bounds) == (False, ())


def test_a_hand_stopped_names_what_it_hit_along_the_tool_s_best_arc(scene_of):
    # Posts at 180 and 225 deg leave the arm two free arcs: 195 to 210, short of
    # the 30 it needs, and the long one round through 0, where the search proves
    # it at 0 to 30. A ring over the arm's far end, at the hand's height, stops
    # the hand everywhere: the quarter from 180 to 270 is one part, the rest
    # another. The hand hit both; along the arc the arm alone turns in, one.
    ring = Pos(0, 0, 66) * (Cylinder(110, 8) - Cylinder(70, 9))
    quarter = Pos(-60, -60, 66) * Box(120, 120, 10)
    attempt = swing(
        scene_of(
            post_180=post(180),
            post_225=post(225),
            ledge_short=ring & quarter,
            ledge_long=ring - quarter,
        ),
        required=30.0,
        with_hand=True,
    )
    assert attempt.no_hand_room  # the arm alone turns, the hand can't follow
    assert not attempt.holds
    assert set(attempt.hand_blockers) == {"ledge_short", "ledge_long"}
    assert attempt.bounds == ("ledge_long",)  # what it hit along the long arc only
    assert ", the hand stopped by ledge_long on its best arc;" in attempt_text(attempt)


# ---------------------------------------------------------------------------
# The attempt's line.
# ---------------------------------------------------------------------------


def attempt_of(**fields):
    base = {"tool": "spanner-13", "way": "ring, full length", "turns": False, "holds": True}
    return Attempt(**{**base, "swing_deg": 15.0, "blockers": ("a", "b", "c"), **fields})


@pytest.mark.parametrize(
    ("fields", "text"),
    [
        (
            {"bounds": ("a", "b"), "required_deg": 30.0},
            "spanner-13, ring, full length: holds, best 15 of 30 deg, between a and b; hit a, b, c",
        ),
        (
            {"bounds": ("a",), "required_deg": 30.0, "swing_deg": 0.0},
            "spanner-13, ring, full length: holds, at one angle only (30 deg needed), "
            "bounded by a; hit a, b, c",
        ),
        (
            {"bounds": ("a", "b", "c"), "required_deg": 30.0},
            "spanner-13, ring, full length: holds, best 15 of 30 deg, bounded by a, b, c; "
            "hit a, b, c",
        ),
        (
            {"required_deg": 0.0},  # no swing search (a straight-in tool): as before
            "spanner-13, ring, full length: holds, swing 15 deg; hit a, b, c",
        ),
    ],
)
def test_an_attempt_says_its_best_arc_and_what_bounds_it(fields, text):
    assert attempt_text(attempt_of(**fields)) == text


# ---------------------------------------------------------------------------
# The fastener: blocked_by leads with the best attempt's bounds.
# ---------------------------------------------------------------------------


def test_the_best_attempt_decides():
    tried = [
        attempt_of(swing_deg=0.0, bounds=("x",)),
        attempt_of(swing_deg=15.0, bounds=("a", "b")),
        attempt_of(swing_deg=15.0, bounds=("c",)),  # a tie: the first stands
        attempt_of(holds=False, swing_deg=0.0),
    ]
    assert _deciding(tried) == ("a", "b")
    assert _deciding([attempt_of(holds=False, swing_deg=0.0)]) == ()


def ring_of_posts():
    """An M8 nut on a stud, twelve posts 60 out round it, 30 deg apart but for a
    and b, 45 apart, and a roof 33 over the nut."""
    angles = {"post_a": 345.0, "post_b": 30.0, **{f"post_{k}": 30.0 + 30 * k for k in range(1, 11)}}
    parts = [
        Part("plate", Pos(0, 0, -5) * (Box(200, 200, 10) - Cylinder(4.5, 11))),
        Part("stud", Pos(0, 0, 2.5) * Cylinder(4, 25)),
        Part("nut", hex_prism(13, 6.8) - Cylinder(4, 30)),
        Part("roof", Pos(0, 0, 42) * Box(200, 200, 4)),
    ]
    for name, a in angles.items():
        rad = math.radians(a)
        parts.append(Part(name, Pos(60 * math.cos(rad), 60 * math.sin(rad), 10) * Cylinder(4, 20)))
    return Assembly(parts)


NUT = {"parts": "nut", "kind": "nut", "size": "M8", "socket": False}


@pytest.fixture(scope="module")
def ring_report():
    return check(ring_of_posts(), Config.from_dict({"fasteners": [NUT]}), kit="full")


def test_the_issue_s_nut_names_the_two_posts_that_decided_it(engine):
    (result,) = check(
        ring_of_posts(), Config.from_dict({"fasteners": [NUT]}), engine=engine
    ).results
    assert result.verdict is Verdict.BLOCKED
    assert set(result.deciding) == {"post_a", "post_b"}
    assert result.blockers[:2] == result.deciding  # blocked_by leads with them
    assert len(result.blockers) == 12  # and keeps every post
    ring = result.attempts[0]
    assert attempt_text(ring).startswith(
        f"spanner-13, ring, full length: holds, best 15 of 30 deg, "
        f"between {ring.bounds[0]} and {ring.bounds[1]}"
    )


def test_every_report_names_the_deciding_parts(ring_report):
    (result,) = ring_report.results
    first, second = result.deciding
    (fail,) = [line for line in ring_report.terminal_lines() if line.startswith("FAIL")]
    assert fail == (
        f"FAIL nut  spanner-13  blocked  only holds, and it has no nut; "
        f"best arc between {first} and {second}"
    )
    assert (
        f"| `nut` | `spanner-13` | blocked | `only holds, and it has no nut`; "
        f"best arc between `{first}` and `{second}` |"
    ) in ring_report.markdown()
    (entry,) = json.loads(ring_report.json_text())["fasteners"]
    assert entry["deciding"] == [first, second]
    assert entry["blocked_by"][:2] == [first, second]
    assert len(entry["blocked_by"]) == 12


def test_every_result_with_deciding_parts_has_a_reason(ring_report):
    # So the line is the reason, and the parts that decided it, never a bare list.
    for config in ({"fasteners": [NUT]}, {"fasteners": [NUT], "checks": {"hand_room": True}}):
        (result,) = check(ring_of_posts(), Config.from_dict(config), kit="full").results
        assert result.deciding
        assert result.reason


def test_with_nothing_decided_the_line_names_every_blocker():
    result = FastenerResult(
        Fastener("nut", Kind.NUT), Verdict.BLOCKED, tool="spanner-13", blockers=("a", "b")
    )
    report = Report(model="m", kit="full", results=(result,))
    (fail,) = [line for line in report.terminal_lines() if line.startswith("FAIL")]
    assert fail == "FAIL nut  spanner-13  blocked  a, b"
    assert json.loads(report.json_text())["fasteners"][0]["deciding"] == []


def test_a_held_nut_names_no_deciding_parts():
    # The issue's own case: the nut on a bolt that turns from below is held, a pass,
    # and nothing decided a failure.
    parts = [p for p in ring_of_posts() if p.name != "stud"]
    bolt = Pos(0, 0, 2) * Cylinder(4, 24) + Pos(0, 0, -15.3) * hex_prism(13, 5.3)  # under
    plate = Part("plate", Pos(0, 0, -5) * (Box(200, 200, 10) - Cylinder(4.5, 11)))
    parts = [plate if p.name == "plate" else p for p in parts] + [Part("bolt", bolt)]
    rules = [NUT, {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"}]
    report = check(Assembly(parts), Config.from_dict({"fasteners": rules}), kit="full")
    nut = {r.fastener.name: r for r in report.results}["nut"]
    assert nut.verdict is Verdict.HELD
    assert nut.deciding == ()
    assert any(a.bounds for a in nut.attempts)  # its attempts were bounded all the same


def test_with_hand_room_the_hand_names_what_stopped_it(ring_report):
    config = Config.from_dict({"fasteners": [NUT], "checks": {"hand_room": True}})
    (result,) = check(ring_of_posts(), config, kit="full").results
    assert result.reason == "no room for a hand (roof in the way)"
    (plain,) = ring_report.results
    assert plain.reason == "only holds, and it has no nut"
