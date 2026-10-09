"""A bolt's hex head in a hex pocket: the part holds it, and its nut turns (issue #134).

#93 held a nut in a trap, its screw the part that turns. A hex head in a hex pocket is
the same joint the other way round, as printed and moulded parts draw it so a bolt
can be tightened from one side: the head's corners, turning, meet the pocket on
opposite sides, so it is held, and its nut must turn. A part on one side only is no
trap, as for a nut. A joint whose two halves are both held, a trapped head on a
trapped nut or a carriage bolt's, has nothing in it to turn, and fails.
"""

import json
import math
import sys
from pathlib import Path

import pytest
from build123d import Box, Cylinder, Pos, RegularPolygon, extrude

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.used import tools_used

sys.path.insert(0, str(Path(__file__).parent / "golden"))
from parts import carriage_bolt, slot_block

BOLT = {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"}
NUT = {"parts": "nut", "kind": "nut", "size": "M8"}
CORNER = 13 / math.sqrt(3)  # an M8 hex's corners, 7.51 from its axis


def hexagon(af, h, z0=0.0):
    return Pos(0, 0, z0) * extrude(RegularPolygon(af / math.sqrt(3), 6), h)


def bolt(top=-5.3):
    """ISO 4017 M8x30: a 13 hex 5.3 high from z ``top`` up, its shank 30 long under it."""
    return hexagon(13, 5.3, top) + Pos(0, 0, top - 15) * Cylinder(4, 30)


def nut(z0=-16.8):
    """ISO 4032 M8: 13 across flats, 6.8 thick, under the plate."""
    return hexagon(13, 6.8, z0) - Cylinder(4, 100)


def plate(pocket=None):
    """80 by 80, 10 thick under z = 0, an 8.4 hole; a hex pocket 5.3 deep in its top."""
    cut = Pos(0, 0, -5) * Box(80, 80, 10) - Cylinder(4.2, 30)
    return cut - hexagon(pocket, 5.3, -5.3) if pocket is not None else cut


def trapped(pocket=13.1):
    return [("plate", plate(pocket)), ("bolt", bolt()), ("nut", nut())]


def run(parts, rules=(BOLT, NUT), kit="metric-home", **kwargs):
    config = Config.from_dict({"fasteners": list(rules)})
    report = check(Assembly([Part(n, s) for n, s in parts]), config, kit=kit, **kwargs)
    return {r.fastener.name: r for r in report.results}, report


# ---------------------------------------------------------------------------
# Held by its pocket.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", ["mesh", "exact"])
def test_a_hex_head_in_its_pocket_is_held_and_its_nut_turns(engine):
    results, report = run(trapped(), engine=engine)
    held = results["bolt"]
    assert (held.verdict, held.tool, held.how, held.blocked_by) == (
        Verdict.HELD,
        None,
        "held by its trap in plate",
        (),
    )
    assert (results["nut"].verdict, results["nut"].tool) == (Verdict.TURNS, "spanner-13")
    assert (held.pair, results["nut"].pair) == ("nut", "bolt")
    assert report.exit_code == 0


def issue_model():
    """The issue's two joints, by their names: one head in a 13.1 pocket, one on top."""
    parts = []
    for x, tag in ((0, "trapped"), (200, "open")):
        top = -5.3 if tag == "trapped" else 0.0
        for name, shape in (
            ("plate", plate(13.1 if tag == "trapped" else None)),
            ("M8x30 hex bolt", bolt(top)),
            ("M8 nut", nut()),
        ):
            parts.append(Part(f"{tag} {name}", Pos(x, 0, 0) * shape))
    return Assembly(parts)


def test_the_issue_s_model_passes_its_trapped_head_held():
    report = check(issue_model(), kit="metric-home")
    results = {r.fastener.name: r for r in report.results}
    assert (results["trapped M8x30 hex bolt"].verdict, results["trapped M8x30 hex bolt"].how) == (
        Verdict.HELD,
        "held by its trap in trapped plate",
    )
    for name in ("trapped M8 nut", "open M8x30 hex bolt", "open M8 nut"):
        assert (results[name].verdict, results[name].tool) == (Verdict.TURNS, "spanner-13")
    assert report.exit_code == 0  # it failed: "the head's corners hit trapped plate"
    used = tools_used(report)
    (use,) = used.uses
    assert (use.tool, use.fasteners, use.at_once) == (
        "spanner-13",
        ("open M8 nut", "open M8x30 hex bolt", "trapped M8 nut"),
        2,  # the open joint's: the trapped one needs one 13, on its nut
    )
    assert used.no_tool == ("trapped M8x30 hex bolt",)


def test_the_report_says_it_in_every_format():
    _, report = run(trapped())
    line = "  M8 hex screw             -              x1    all pass (held by its trap in plate)"
    assert line in report.terminal_lines()
    (entry,) = [f for f in json.loads(report.json_text())["fasteners"] if f["name"] == "bolt"]
    assert (entry["verdict"], entry["tool"], entry["how"]) == (
        "held",
        None,
        "held by its trap in plate",
    )
    assert "held by its trap in plate" in report.markdown()


def test_a_loose_hex_pocket_is_still_a_trap():
    # 14 across flats round a 13 head: its corners, 7.51 out, still meet the flats at 7.
    results, _ = run(trapped(pocket=14.0))
    assert results["bolt"].verdict is Verdict.HELD


def test_a_head_drawn_into_its_pocket_is_held_and_said():
    # A 12.8 pocket round a 13 head: (13^2 - 12.8^2) sqrt(3) / 2 = 4.469 mm^2 between
    # the hexes, 5.3 deep, 23.7 mm^3: a press fit as often as a clash, so said.
    results, report = run(trapped(pocket=12.8))
    assert results["bolt"].verdict is Verdict.HELD
    assert results["bolt"].notes == (
        "drawn 23.7 mm^3 into its trap: a press fit, or a clash to fix",
    )
    assert report.exit_code == 0


def test_a_held_head_needs_no_nut():
    # Its nut out of the model, as a trapped nut's screw may be: held all the same.
    results, report = run(trapped()[:2], rules=(BOLT,))
    assert (results["bolt"].verdict, results["bolt"].pair) == (Verdict.HELD, None)
    assert report.exit_code == 0


def test_a_trap_is_the_model_s_whatever_the_kit():
    # imperial-home holds no 13: the nut's not covered, the head held all the same.
    results, _ = run(trapped(), kit="imperial-home")
    assert (results["bolt"].verdict, results["bolt"].how) == (
        Verdict.HELD,
        "held by its trap in plate",
    )
    assert results["nut"].verdict is Verdict.NOT_COVERED


def test_a_trapped_head_is_not_tried_again_in_a_state_without_its_trap():
    config = Config.from_dict(
        {
            "fasteners": [BOLT, NUT],
            "states": {"plate-off": {"remove": ["plate"]}},
            "checks": {"try_states": ["plate-off"]},
        }
    )
    report = check(Assembly([Part(n, s) for n, s in trapped()]), config, kit="full")
    (held,) = [r for r in report.results if r.fastener.name == "bolt"]
    assert (held.verdict, held.how, held.state) == (Verdict.HELD, "held by its trap in plate", None)


# ---------------------------------------------------------------------------
# No trap.
# ---------------------------------------------------------------------------


def test_a_round_pocket_clear_of_the_corners_is_no_trap():
    # 8.5 round, past the corners' 7.51: the head could turn if anything got on it,
    # and nothing does, the pocket too tight for a ring or a socket.
    cut = plate() - Pos(0, 0, -2.65) * Cylinder(8.5, 5.3)
    results, report = run([("plate", cut), ("bolt", bolt()), ("nut", nut())])
    blocked = results["bolt"]
    assert (blocked.verdict, blocked.tool, blocked.blocked_by, blocked.reason) == (
        Verdict.BLOCKED,
        "spanner-13",
        ("plate",),
        None,  # not its corners: the tools
    )
    assert report.exit_code == 1


def test_a_part_on_one_side_only_is_no_trap():
    # The head on the plate, a bar over one corner: blocked by its corners, as before.
    bar = Pos(CORNER + 5, 0, 2.65) * Box(10, 30, 2)
    results, _ = run([("plate", plate()), ("bolt", bolt(top=0)), ("nut", nut()), ("bar", bar)])
    assert (results["bolt"].verdict, results["bolt"].reason) == (
        Verdict.BLOCKED,
        "the head's corners hit bar as it turns",
    )


# ---------------------------------------------------------------------------
# Its nut must turn.
# ---------------------------------------------------------------------------


def test_its_nut_that_cannot_turn_fails_with_its_own_reason():
    bar = Pos(CORNER + 5, 0, -13.4) * Box(10, 30, 2)
    results, report = run([*trapped(), ("bar", bar)])
    assert results["bolt"].verdict is Verdict.HELD
    assert (results["nut"].verdict, results["nut"].reason) == (
        Verdict.BLOCKED,
        "the nut's corners hit bar as it turns",
    )
    assert report.exit_code == 1


def test_its_nut_that_only_holds_says_its_bolt_cannot_turn_for_it():
    # A guide round the nut, a slot for the 13's handle (13.7 wide) 10 degrees each
    # way at 60 out: the ring gets on and swings 20 of the 30 it needs.
    half = 13.7 / 2 + 60 * math.tan(math.radians(10))
    guide = slot_block(-18, -10.2, 20, half)
    rules = (BOLT, {**NUT, "tool": "spanner-13"})
    results, report = run([*trapped(), ("guide", guide)], rules=rules)
    assert results["nut"].verdict is Verdict.BLOCKED
    assert results["nut"].reason == (
        "only holds, and its bolt (bolt) is held by its trap in plate, so it must turn; "
        "best arc bounded by guide"
    )
    assert report.exit_code == 1


# ---------------------------------------------------------------------------
# Nothing in the joint turns.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", ["mesh", "exact"])
def test_a_trapped_head_on_a_trapped_nut_fails_both(engine):
    # It passed the bolt's half by failing it: "the head's corners hit plate".
    base = Pos(0, 0, -20) * Box(80, 80, 20) - Cylinder(4.2, 80) - hexagon(13.1, 6.8, -16.8)
    results, report = run([*trapped(), ("base", base)], engine=engine)
    assert [(r.verdict, r.tool, r.how, r.reason) for r in results.values()] == [
        (
            Verdict.BLOCKED,
            None,
            None,
            "held by its trap in plate, and its nut (nut) is held by its trap in base: "
            "nothing in the joint turns",
        ),
        (
            Verdict.BLOCKED,
            None,
            None,
            "held by its trap in base, and its bolt (bolt) is held by its trap in plate: "
            "nothing in the joint turns",
        ),
    ]
    assert report.exit_code == 1


def test_a_trapped_head_into_a_fixed_thread_fails_both():
    insert = Pos(0, 0, -20) * (Cylinder(6, 10) - Cylinder(4, 10))
    low = Pos(0, 0, -20) * Box(80, 80, 10) - Pos(0, 0, -20) * Cylinder(6, 10)
    rules = (BOLT, {"parts": "insert", "kind": "insert", "size": "M8"})
    parts = [*trapped()[:2], ("insert", insert), ("low", low)]
    results, _ = run(parts, rules=rules)
    assert results["bolt"].reason == (
        "held by its trap in plate, and its fixed thread (insert) holds itself: "
        "nothing in the joint turns"
    )
    assert results["insert"].reason == (
        "holds itself, and its bolt (bolt) is held by its trap in plate: nothing in the joint turns"
    )


def carriage_joint(nut_trapped):
    """A DIN 603 M6 carriage bolt, its 6 square neck in the plate, an M6 nut under it."""
    cut = Pos(0, 0, -5) * Box(80, 80, 10) - Pos(0, 0, -2) * Box(6, 6, 4.01) - Cylinder(3.2, 30)
    parts = [("plate", cut), ("bolt", carriage_bolt(length=20))]
    parts.append(("nut", hexagon(10, 5.2, -15.2) - Cylinder(3, 100)))
    if nut_trapped:
        base = Pos(0, 0, -20) * Box(80, 80, 20) - Cylinder(3.2, 80) - hexagon(10.1, 5.2, -15.2)
        parts.append(("base", base))
    return parts


def test_a_carriage_bolt_on_a_trapped_nut_fails_both():
    # Both held, both passed: nothing in the joint turns, so it can't come apart.
    rules = (
        {"parts": "bolt", "head": "carriage", "size": "M6"},
        {"parts": "nut", "kind": "nut", "size": "M6"},
    )
    results, report = run(carriage_joint(nut_trapped=True), rules=rules)
    assert (results["bolt"].verdict, results["bolt"].reason) == (
        Verdict.BLOCKED,
        "holds itself, and its nut (nut) is held by its trap in base: nothing in the joint turns",
    )
    assert results["nut"].reason == (
        "held by its trap in base, and its bolt (bolt) holds itself: nothing in the joint turns"
    )
    assert report.exit_code == 1
    results, report = run(carriage_joint(nut_trapped=False), rules=rules)
    assert (results["bolt"].verdict, results["nut"].verdict) == (Verdict.HELD, Verdict.TURNS)
    assert report.exit_code == 0
