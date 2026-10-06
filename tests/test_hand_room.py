"""Hand room (spec 6.4): the hand on each handle, off unless asked for.

The hand is a cylinder (r 35) along a handle's last 90 mm, resting on it from the
side the tool came from; a driver's is a fist round its handle; an L-key's arms get
none. Where the tool alone would turn and the hand can't follow, the fastener is
blocked "no room for a hand", naming what the hand hit. Off, nothing changes.
"""

import json

import pytest
from build123d import Box, Compound, Cylinder, Pos, export_step
from click.testing import CliRunner

from fixture_models import hex_nut, screw_facing_wall, socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config, ConfigError
from wrenchroom.report import Verdict, attempt_text
from wrenchroom.solids import RadialCylinder
from wrenchroom.tools.drivers import HANDLE_LENGTH, SHAFT_LENGTH, driver_hand
from wrenchroom.tools.sweep import (
    CONTACT_OFFSET,
    HAND_LENGTH,
    HAND_RADIUS,
    Mount,
    hand_on_handle,
    radial_cylinder,
    straight_attempt,
    swing_attempt,
)

NUT = {"parts": "nut", "kind": "nut", "size": "M6"}


def under_a_block(gap=7.0, bore=20.0):
    """An M6 nut (af 10, 5 tall) on a plate, a tall block `gap` over it, bored round it."""
    top = 5 + gap
    block = Pos(0, 0, top + 150) * Box(300, 300, 300) - Pos(0, 0, top + 150) * Cylinder(bore, 301)
    return Assembly(
        [
            Part("nut", hex_nut()),
            Part("plate", Pos(0, 0, -5) * Box(400, 400, 10)),
            Part("block", block),
        ]
    )


def run(assembly, *rules, engine="exact", **kwargs):
    return check(assembly, Config.from_dict({"fasteners": list(rules)}), engine=engine, **kwargs)


# ---------------------------------------------------------------------------
# Settings.
# ---------------------------------------------------------------------------


def test_hand_room_is_off_unless_asked_for():
    assert Config().hand_room is False
    assert Config.from_dict({"checks": {"hand_room": True}}).hand_room is True
    assert Config.from_dict({"checks": {"hand_room": False}}).hand_room is False
    with pytest.raises(ConfigError, match="hand_room"):
        Config.from_dict({"checks": {"hand_room": "maybe"}})


def test_the_argument_outranks_the_sidecar(engine):
    sidecar = {"fasteners": [NUT], "checks": {"hand_room": True}}
    on = check(under_a_block(), Config.from_dict(sidecar), engine=engine)
    off = check(under_a_block(), Config.from_dict(sidecar), engine=engine, hand_room=False)
    assert (on.hand_room, off.hand_room) == (True, False)
    assert on.results[0].verdict is Verdict.BLOCKED
    assert off.results[0].verdict is Verdict.TURNS


# ---------------------------------------------------------------------------
# The hand's geometry.
# ---------------------------------------------------------------------------


def test_the_hand_rests_on_the_handle_s_last_90_mm():
    (hand,) = hand_on_handle(2.5, 10.0, 114.75, 30.0).primitives
    assert hand == RadialCylinder(HAND_RADIUS, 114.75 - HAND_LENGTH, 114.75, 2.5 + HAND_RADIUS, 30)
    assert (HAND_RADIUS, HAND_LENGTH) == (35.0, 90.0)  # the spec's figures


def test_on_a_short_handle_the_hand_stays_on_it():
    (hand,) = hand_on_handle(2.5, 10.0, 63.1, 0.0).primitives
    assert (hand.r0, hand.r1) == (10.0, 63.1)  # never back over the fastener


def test_a_driver_s_hand_is_a_fist_round_its_handle():
    (fist,) = driver_hand().primitives
    handle_to = CONTACT_OFFSET + SHAFT_LENGTH + HANDLE_LENGTH
    assert (fist.radius, fist.z0, fist.z1) == (HAND_RADIUS, handle_to - HAND_LENGTH, handle_to)


# ---------------------------------------------------------------------------
# The sweep with a hand.
# ---------------------------------------------------------------------------

ORIGIN = Mount(seat=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0))


def _arm(phi):
    return ORIGIN.place(radial_cylinder(2, 0, 100, 10, phi))


def _hand(phi):
    return ORIGIN.place(hand_on_handle(10, 0, 100, phi))


def test_a_hand_blocked_everywhere_stops_a_tool_that_would_turn(scene_of):
    scene = scene_of(lid=Pos(0, 0, 40) * Box(400, 400, 10))  # over the arm, in the hand
    attempt = swing_attempt(
        tool="probe",
        way="probe",
        scene=scene,
        engagement=ORIGIN.place(radial_cylinder(1, 0, 1, 1, 0)),
        arm_at=_arm,
        required_deg=60.0,
        hand_at=_hand,
    )
    assert not attempt.turns
    assert not attempt.holds
    assert attempt.no_hand_room
    assert attempt.blockers == ()  # the tool itself never touched it
    assert attempt.hand_blockers == ("lid",)
    alone = swing_attempt(
        tool="probe",
        way="probe",
        scene=scene,
        engagement=ORIGIN.place(radial_cylinder(1, 0, 1, 1, 0)),
        arm_at=_arm,
        required_deg=60.0,
    )
    assert alone.turns


def test_a_hand_free_in_part_of_the_circle_turns_there(scene_of):
    # The lid covers x > 50 only: the hand is free on the far side.
    scene = scene_of(lid=Pos(250, 0, 40) * Box(400, 400, 10))
    attempt = swing_attempt(
        tool="probe",
        way="probe",
        scene=scene,
        engagement=ORIGIN.place(radial_cylinder(1, 0, 1, 1, 0)),
        arm_at=_arm,
        required_deg=60.0,
        hand_at=_hand,
    )
    assert attempt.turns
    assert not attempt.no_hand_room


def test_the_hand_is_only_tried_where_the_tool_is_clear(scene_of):
    # A wall the arm meets everywhere: no hand is ever placed.
    scene = scene_of(ring=Pos(0, 0, 10) * (Cylinder(200, 4) - Cylinder(50, 5)))
    attempt = swing_attempt(
        tool="probe",
        way="probe",
        scene=scene,
        engagement=ORIGIN.place(radial_cylinder(1, 0, 1, 1, 0)),
        arm_at=_arm,
        required_deg=60.0,
        hand_at=_hand,
    )
    assert not attempt.no_hand_room
    assert all(probe.solid.primitives[0].radius != HAND_RADIUS for probe in attempt.probes)


def test_a_straight_tool_with_no_room_for_its_fist(scene_of):
    # A tube round the driver's handle: wide enough for the handle (r 14), not the fist.
    handle_from = CONTACT_OFFSET + SHAFT_LENGTH
    tube = Pos(0, 0, handle_from + 50) * (Cylinder(60, 60) - Cylinder(20, 61))
    scene = scene_of(tube=tube)
    from wrenchroom.tools.drivers import driver_solid  # noqa: PLC0415

    attempt = straight_attempt(
        tool="driver",
        way="driver straight in",
        scene=scene,
        solid=ORIGIN.place(driver_solid(3.0)),
        hand=ORIGIN.place(driver_hand()),
    )
    assert attempt.no_hand_room
    assert not attempt.turns
    assert attempt.hand_blockers == ("tube",)
    assert attempt.blockers == ()


# ---------------------------------------------------------------------------
# A check with hand room.
# ---------------------------------------------------------------------------


def test_a_nut_a_spanner_reaches_and_a_hand_cannot(engine):
    (off,) = run(under_a_block(), NUT, engine=engine).results
    assert off.verdict is Verdict.TURNS
    assert (off.tool, off.how) == ("spanner-10", "ring, full length")
    (on,) = run(under_a_block(), NUT, engine=engine, hand_room=True).results
    assert on.verdict is Verdict.BLOCKED
    assert on.reason == "no room for a hand (block in the way)"
    assert "block" in on.blockers
    ring = on.attempts[0]
    assert attempt_text(ring) == (
        "spanner-10, ring, full length: blocked (no room for a hand); the hand hit block"
    )


def test_what_only_the_hand_hit_is_named_in_the_way(engine):
    # No socket (as on a gland): the ring is clear everywhere, so the block is in
    # the way only because of the hand, and must still be named and highlighted.
    rule = {**NUT, "socket": False}
    (on,) = run(under_a_block(), rule, engine=engine, hand_room=True).results
    assert all(not a.blockers for a in on.attempts)  # the tool never touched it
    assert on.blockers == ("block",)
    report = run(under_a_block(), rule, engine=engine, hand_room=True)
    (entry,) = report.to_json_dict()["fasteners"]
    assert entry["blocked_by"] == ["block"]


def test_more_room_over_the_handle_gives_the_hand_room(engine):
    (result,) = run(under_a_block(gap=80.0), NUT, engine=engine, hand_room=True).results
    assert result.verdict is Verdict.TURNS


def test_key_arms_get_no_hand():
    # A key under a ceiling 40 over the head turns short leg in, hand room or not:
    # an arm is turned with the fingertips (sweep.py).
    rule = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}
    for hand_room in (False, True):
        (result,) = run(screw_facing_wall(40.0), rule, hand_room=hand_room).results
        assert result.verdict is Verdict.TURNS
        assert result.how == "short leg in"


def test_a_driver_in_a_tube_is_blocked_for_its_fist():
    screw = Assembly(
        [
            Part("screw", socket_screw()),
            Part("tube", Pos(0, 0, 26 + 150) * (Cylinder(60, 60) - Cylinder(20, 61))),
        ]
    )
    rule = {"parts": "screw", "kind": "screw", "head": "phillips", "size": "M4"}
    (off,) = run(screw, rule).results
    assert off.verdict is Verdict.TURNS
    (on,) = run(screw, rule, hand_room=True).results
    assert on.verdict is Verdict.BLOCKED
    assert on.reason == "no room for a hand (tube in the way)"


def test_the_report_says_whether_the_hand_was_checked():
    off = run(under_a_block(), NUT)
    on = run(under_a_block(), NUT, hand_room=True)
    assert off.to_json_dict()["hand_room"] is False
    assert on.to_json_dict()["hand_room"] is True
    assert off.terminal_lines()[-1] == (
        "NOTE not checked: room for a hand (checks: {hand_room: true} turns it on); "
        "parts the model doesn't have"
    )
    assert on.terminal_lines()[-1] == "NOTE not checked: parts the model doesn't have"
    assert "Not checked: parts the model doesn't have." in on.markdown().splitlines()
    assert "Not checked: room for a hand" not in on.markdown()
    assert "Not checked: room for a hand" in off.markdown()
    with pytest.raises(AssertionError, match="no room for a hand"):
        on.assert_all_pass()


# ---------------------------------------------------------------------------
# The CLI and the pytest setting.
# ---------------------------------------------------------------------------


@pytest.fixture
def step(tmp_path):
    shapes = []
    for part in under_a_block():
        part.shape.label = part.name
        shapes.append(part.shape)
    export_step(Compound(children=shapes), str(tmp_path / "model.step"))
    (tmp_path / "wrenchroom.yaml").write_text(json.dumps({"fasteners": [NUT]}))
    return tmp_path / "model.step"


def test_check_and_explain_take_hand_room(step):
    assert CliRunner().invoke(main, ["check", str(step)]).exit_code == 0
    checked = CliRunner().invoke(main, ["check", str(step), "--hand-room"])
    assert checked.exit_code == 1
    assert "FAIL nut  spanner-10  blocked  no room for a hand (block in the way)" in checked.output
    explained = CliRunner().invoke(main, ["explain", str(step), "nut", "--hand-room"])
    assert "blocked (no room for a hand); the hand hit block" in explained.output


def test_the_sidecar_turns_it_on_for_the_cli(step):
    (step.parent / "wrenchroom.yaml").write_text(
        json.dumps({"fasteners": [NUT], "checks": {"hand_room": True}})
    )
    assert CliRunner().invoke(main, ["check", str(step)]).exit_code == 1


def test_the_pytest_setting(pytester, step):
    pytester.makeini(f"[pytest]\nwrenchroom_model = {step}\nwrenchroom_hand_room = true\n")
    pytester.makepyfile(
        "def test_reach(wrenchroom_report):\n    wrenchroom_report.assert_all_pass()\n"
    )
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*no room for a hand (block in the way)*"])
    pytester.makeini(f"[pytest]\nwrenchroom_model = {step}\n")
    pytester.runpytest().assert_outcomes(passed=1)  # unset: the sidecar's, which is off
