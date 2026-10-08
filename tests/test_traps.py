"""Nuts in traps: a hex pocket, or a slot the nut's own width, holds it (issue #93).

A nut's corners, turning, sweep a ring round it. One part they meet on opposite sides
stops it turning whatever grips it, and it needn't turn: the part holds it, as a fixed
thread holds itself, and its screw must turn. A part on one side only, a rib a corner
touches, is no trap, and the nut is blocked by its corners as before (issue #63).
"""

import json
import math

import pytest
from build123d import Box, Cylinder, Pos, RegularPolygon, Rot, extrude

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict

SCREW = {"parts": "screw", "kind": "screw", "head": "socket", "size": "M3"}
NUT = {"parts": "nut", "kind": "nut", "size": "M3"}


def hexagon(af, h, z0=0.0):
    return Pos(0, 0, z0) * extrude(RegularPolygon(af / math.sqrt(3), 6), h)


def screw():
    """ISO 4762 M3x16: head 5.5 x 3 on z = 0..3, a 2.5 socket, shank to z = -16."""
    head = Pos(0, 0, 1.5) * Cylinder(2.75, 3) - hexagon(2.5, 1.31, 1.7)
    return head + Pos(0, 0, -8) * Cylinder(1.5, 16)


def nut(z0):
    """ISO 4032 M3: 5.5 across flats, 2.4 thick, bored at the nominal."""
    return hexagon(5.5, 2.4, z0) - Cylinder(1.5, 40)


def block():
    """30 by 30, 16 deep under z = 0, a 3.4 clearance hole down its axis."""
    return Pos(0, 0, -8) * Box(30, 30, 16) - Cylinder(1.7, 40)


def run(parts, rules=(SCREW, NUT), **kwargs):
    config = Config.from_dict({"fasteners": list(rules)})
    report = check(Assembly([Part(n, s) for n, s in parts]), config, kit="metric-home", **kwargs)
    return {r.fastener.name: r for r in report.results}, report


def slot_parts(width=5.7, height=2.6):
    cut = block() - Pos(6.7, 0, -8) * Box(20, width, height)
    return [("block", cut), ("screw", screw()), ("nut", Pos(0, 0, -9.2) * nut(0))]


def pocket_parts(af=5.6, depth=2.6):
    cut = block() - hexagon(af, depth, -16)
    return [("block", cut), ("screw", screw()), ("nut", nut(-16))]


@pytest.mark.parametrize("engine", ["mesh", "exact"])
@pytest.mark.parametrize("parts", [slot_parts, pocket_parts], ids=["slot", "pocket"])
def test_a_nut_in_its_trap_is_held_and_its_screw_turns(parts, engine):
    results, report = run(parts(), engine=engine)
    assert (results["nut"].verdict, results["nut"].tool, results["nut"].how) == (
        Verdict.HELD,
        None,
        "held by its trap in block",
    )
    assert (results["screw"].verdict, results["screw"].tool) == (Verdict.TURNS, "hex-key-2.5")
    assert results["nut"].pair == "screw"
    assert report.exit_code == 0


def test_a_slot_open_to_one_side_is_a_trap_as_its_walls_are_opposite():
    # Both faces covered, the nut used to be not covered: "both ends are covered".
    results, _ = run(slot_parts())
    assert results["nut"].reason is None


def test_a_loose_hex_pocket_is_still_a_trap():
    # 6 across flats round a 5.5 nut: its corners, 3.18 out, still meet the flats at 3.
    results, _ = run(pocket_parts(af=6.0))
    assert results["nut"].verdict is Verdict.HELD


def test_a_round_pocket_clear_of_the_corners_is_no_trap():
    # Past the corners' 3.18 and the ring's clearance: the nut could turn, if anything
    # got on it, and nothing does, the pocket too tight for a ring.
    cut = block() - Pos(0, 0, -16) * Cylinder(3.6, 5.2)
    results, _ = run([("block", cut), ("screw", screw()), ("nut", nut(-16))])
    result = results["nut"]
    assert (result.verdict, result.tool, result.blocked_by) == (
        Verdict.BLOCKED,
        "spanner-5.5",
        ("block",),
    )
    assert result.reason is None  # not its corners: the ring


def test_a_part_on_one_side_only_is_no_trap():
    # issue #63's corner_touch: a bar on the corner circle, one side. Blocked, as before.
    corner = 5.5 / math.sqrt(3)
    plate = Pos(0, 0, -5) * Box(60, 60, 10) - Cylinder(1.7, 20)
    bar = Pos(corner + 5, 0, 1.2) * Box(10, 30, 1.0)
    stud = Pos(0, 0, 5) * Cylinder(1.5, 20)
    parts = [("plate", plate), ("stud", stud), ("nut", nut(0)), ("bar", bar)]
    results, _ = run(parts, rules=(NUT,))
    assert results["nut"].verdict is Verdict.BLOCKED
    assert results["nut"].reason == "the nut's corners hit bar as it turns"


def test_two_parts_one_each_side_are_no_trap():
    # A trap is one part's: two others, a corner touching each, block it.
    corner = 5.5 / math.sqrt(3)
    plate = Pos(0, 0, -5) * Box(60, 60, 10) - Cylinder(1.7, 20)
    stud = Pos(0, 0, 5) * Cylinder(1.5, 20)
    east = Pos(corner + 5, 0, 1.2) * Box(10, 30, 1.0)
    west = Pos(-corner - 5, 0, 1.2) * Box(10, 30, 1.0)
    parts = [("plate", plate), ("stud", stud), ("nut", nut(0)), ("east", east), ("west", west)]
    results, _ = run(parts, rules=(NUT,))
    assert results["nut"].verdict is Verdict.BLOCKED


def test_the_same_part_on_both_sides_is_one():
    corner = 5.5 / math.sqrt(3)
    plate = Pos(0, 0, -5) * Box(60, 60, 10) - Cylinder(1.7, 20)
    stud = Pos(0, 0, 5) * Cylinder(1.5, 20)
    ribs = Pos(corner + 5, 0, 1.2) * Box(10, 30, 1.0) + Pos(-corner - 5, 0, 1.2) * Box(10, 30, 1.0)
    parts = [("plate", plate), ("stud", stud), ("nut", nut(0)), ("ribs", ribs)]
    results, _ = run(parts, rules=(NUT,))
    assert (results["nut"].verdict, results["nut"].how) == (
        Verdict.HELD,
        "held by its trap in ribs",
    )


def test_a_nut_drawn_into_its_trap_is_held_and_said():
    # A pocket 5.4 across a 5.5 nut: a press fit, as often as a clash, so said, not failed.
    results, report = run(pocket_parts(af=5.4))
    result = results["nut"]
    assert result.verdict is Verdict.HELD
    (note,) = result.notes
    assert note.startswith("drawn ")
    assert note.endswith(" mm^3 into its trap: a press fit, or a clash to fix")
    volume = float(note.split()[1])
    assert 0.5 < volume < 5.0  # the six slivers between 5.4 and 5.5 across flats, 2.4 deep
    assert report.exit_code == 0


def test_a_screw_that_only_holds_says_its_trapped_nut_cannot_turn_for_it():
    # A slotted guide over the head: the 2.5 key's short leg gets in, its arm swings 36
    # of the 60 degrees it needs; a ceiling stops the rest.
    half = 2.82 / 2 + 60 * math.tan(math.radians(18))
    guide = Pos(0, 0, 22.5) * Box(120, 120, 15) - Pos(0, 0, 22.5) * Cylinder(8, 16)
    guide -= Pos(30, 0, 22.5) * Box(60, 2 * half, 16)  # a slot narrowing to 18 deg each way
    ceiling = Pos(0, 0, 38) * Box(200, 200, 10)
    parts = [*pocket_parts(), ("guide", guide), ("ceiling", ceiling)]
    results, report = run(parts)
    screw_result = results["screw"]
    assert screw_result.verdict is Verdict.BLOCKED
    assert screw_result.reason.startswith(
        "only holds, and its nut (nut) is held by its trap in block, so it must turn"
    )
    assert results["nut"].verdict is Verdict.HELD
    assert report.exit_code == 1


def test_a_trapped_nut_is_detected_and_held_too():
    parts = [("block", slot_parts()[0][1]), ("ISO 4762 M3x16", screw())]
    parts.append(("M3 nut", Pos(0, 0, -9.2) * nut(0)))
    report = check(Assembly([Part(n, s) for n, s in parts]), kit="metric-home")
    results = {r.fastener.name: r for r in report.results}
    assert (results["M3 nut"].verdict, results["M3 nut"].how) == (
        Verdict.HELD,
        "held by its trap in block",
    )
    assert results["ISO 4762 M3x16"].verdict is Verdict.TURNS


def test_the_report_says_it_in_every_format():
    _, report = run(slot_parts())
    assert (
        "  M3 nut                   -              x1    all pass (held by its trap in block)"
        in (report.terminal_lines())
    )
    (entry,) = [f for f in json.loads(report.json_text())["fasteners"] if f["name"] == "nut"]
    assert (entry["verdict"], entry["tool"], entry["how"]) == (
        "held",
        None,
        "held by its trap in block",
    )
    assert "held by its trap in block" in report.markdown()


def test_a_trap_is_the_model_s_whatever_the_kit():
    # imperial-home holds no 5.5 spanner: the nut's not covered by any tool, but
    # held by its trap all the same, as the same nut in the full kit, word for word.
    config = Config.from_dict({"fasteners": [SCREW, NUT]})
    for parts in (slot_parts(), pocket_parts()):
        assembly = Assembly([Part(n, s) for n, s in parts])
        said = []
        for kit in ("imperial-home", "full"):
            report = check(assembly, config, kit=kit)
            (entry,) = [f for f in report.to_json_dict()["fasteners"] if f["name"] == "nut"]
            said.append(entry)
        assert said[0] == said[1]
        assert (said[0]["verdict"], said[0]["how"], said[0]["blocked_by"]) == (
            "held",
            "held by its trap in block",
            [],
        )


def test_a_rule_s_tool_on_a_trapped_nut_finds_the_trap_too():
    rules = (SCREW, {**NUT, "tool": "spanner-5.5"})
    results, _ = run(pocket_parts(), rules=rules)
    assert results["nut"].verdict is Verdict.HELD


def test_a_slot_at_any_angle_is_a_trap():
    # A slot along 45 degrees: its walls face 135 and 315. A probe every 90 degrees
    # from 0 would pass between them (at 90, 3.48 out is only 2.46 along a wall's
    # normal, short of its 2.85); every 30, the ones at 150 and 330 meet them.
    cut = block() - Rot(0, 0, 45) * Pos(6.7, 0, -8) * Box(20, 5.7, 2.6)
    parts = [("block", cut), ("screw", screw()), ("nut", Pos(0, 0, -9.2) * nut(0))]
    results, _ = run(parts)
    assert (results["nut"].verdict, results["nut"].how) == (
        Verdict.HELD,
        "held by its trap in block",
    )


def test_a_trapped_nut_is_not_tried_again_in_a_state_without_its_trap():
    # Held by its trap as the model stands, it needn't turn, in that state or any:
    # a state taking its block away doesn't make it the one to turn, as a fixed
    # thread is never retried either.
    config = Config.from_dict(
        {
            "fasteners": [SCREW, NUT],
            "states": {"block-off": {"remove": ["block"]}},
            "checks": {"try_states": ["block-off"]},
        }
    )
    report = check(Assembly([Part(n, s) for n, s in pocket_parts()]), config, kit="full")
    (nut,) = [r for r in report.results if r.fastener.name == "nut"]
    assert (nut.verdict, nut.how, nut.state) == (Verdict.HELD, "held by its trap in block", None)
