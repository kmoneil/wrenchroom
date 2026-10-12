"""The swing's step (``--step-deg``, ``check(step_deg=...)``): which are taken, where it is said.

Issue #184: any number was taken. A step of 0 was a traceback, nan an odd error, and
past 240 degrees, or below 0, the circle was one position, which stood for all of it:
a key free at one angle read as turning a full circle. A step is held to 0.1 to 30
degrees wherever it comes in, and every report records the one it was run at.

Issue #185: a step that doesn't divide 360 put its positions unevenly, the last some
other distance from 0, and an arc across 0 was counted in whole steps all the same: at
20.5, a key with 55 degrees of room, which needs 60, turned. The positions are spaced
evenly now, the nearest whole number of them to the step asked.

Issue #188: only ``check`` and ``explain`` could be told a step, so ``tools --used``
and the pytest plugin ran at 15 whatever a project checked at. The sidecar says it now
(``checks: {step_deg: 5}``) for every way of running the check, and ``--step-deg``
outranks it for one run.

Issue #192: a report said the step asked for, and its arcs were counted in another,
the spacing the step came to. It says both now (``swing_positions``), its Markdown
says the spacing, and an arc in the JSON carries no float's tail. And ``check()`` with
no sidecar finds fasteners, which its docstring had the other way round.

The search's own cases use a scene with no geometry, free at the angles it is told;
the issue's model is checked on both engines and through the command line.
"""

import inspect
import json
import math

import numpy as np
import pytest
from build123d import (
    Box,
    Compound,
    Cylinder,
    Polygon,
    Pos,
    RegularPolygon,
    export_step,
    extrude,
)
from click.testing import CliRunner

from fixture_models import hex_nut, nut_on_plate, screw_facing_wall
from wrenchroom import __version__, cli
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import EXIT_NOT_COVERED, main
from wrenchroom.config import Config, ConfigError
from wrenchroom.report import Report, Verdict
from wrenchroom.tools import sweep
from wrenchroom.tools.ball_end import BALL_END_KEYS, ball_end_attempts
from wrenchroom.tools.fingers import finger_attempts, rim_attempt
from wrenchroom.tools.hex_keys import HEX_RESEAT_DEG, ISO_2936, hex_key_attempts
from wrenchroom.tools.sockets import RATCHET_72_SWING_DEG, socket_attempts, socket_for
from wrenchroom.tools.spanners import (
    OPEN_RESEAT_DEG,
    RING_RESEAT_DEG,
    open_end_attempts,
    ring_attempts,
    spanner_for,
)
from wrenchroom.tools.sweep import (
    DEFAULT_STEP_DEG,
    MAX_STEP_DEG,
    MIN_STEP_DEG,
    Mount,
    checked_step,
    positions,
    swing_attempt,
)

#: Steps a swing is sampled at: the bounds themselves, and steps that don't divide 360.
TAKEN = [0.1, 0.25, 1.0, 5.0, 7.5, 15.0, 20.5, 29.999, 30.0]

#: The issue's table and its neighbours: nothing, less than nothing, no number, and
#: every step past the widest, 240 (two positions) and the one-position steps among
#: them; then the two too fine to count the positions of.
REFUSED = [
    0.0,
    -0.0,
    -0.1,
    -15.0,
    0.05,
    0.0999,
    30.001,
    31.0,
    45.0,
    60.0,
    200.0,
    240.0,
    250.0,
    300.0,
    400.0,
    math.inf,
    -math.inf,
    math.nan,
    1e-310,
    5e-324,
]

REFUSAL = "a swing step is from 0.1 to 30 degrees, not "

ORIGIN_MOUNT = Mount(seat=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0))


def seeded_steps(count=200):
    """Steps drawn evenly over the whole range taken, the same ones every run."""
    return np.random.default_rng(184).uniform(MIN_STEP_DEG, MAX_STEP_DEG, count).tolist()


# ---------------------------------------------------------------------------
# The range.
# ---------------------------------------------------------------------------


def test_a_step_is_from_a_tenth_of_a_degree_to_thirty():
    assert (MIN_STEP_DEG, DEFAULT_STEP_DEG, MAX_STEP_DEG) == (0.1, 15.0, 30.0)


def test_no_step_is_wider_than_the_arc_a_spanner_or_a_key_has_to_show():
    assert MAX_STEP_DEG == RING_RESEAT_DEG == OPEN_RESEAT_DEG == 30.0
    assert MAX_STEP_DEG <= HEX_RESEAT_DEG


@pytest.mark.parametrize("step", TAKEN)
def test_a_step_in_range_is_taken_as_given(step):
    assert checked_step(step) == step


def test_a_whole_number_of_degrees_is_taken_as_a_float():
    taken = checked_step(15)
    assert (taken, type(taken)) == (15.0, float)


@pytest.mark.parametrize("step", REFUSED)
def test_a_step_out_of_range_is_refused(step):
    with pytest.raises(ValueError, match=REFUSAL):
        checked_step(step)


@pytest.mark.parametrize(
    ("step", "said"),
    [(400.0, "400.0"), (-15, "-15"), (math.nan, "nan"), (math.inf, "inf"), (0.0, "0.0")],
)
def test_the_refusal_says_the_step_it_was_given(step, said):
    with pytest.raises(ValueError, match="^" + REFUSAL + said + "$"):
        checked_step(step)


def test_the_refusal_never_rounds_a_step_into_range():
    # At six figures, 30.0000001 is "30": in the range the message has just given.
    with pytest.raises(ValueError, match=r"not 30\.0000001$"):
        checked_step(30.0000001)
    with pytest.raises(ValueError, match=r"not 0\.09999999$"):
        checked_step(0.09999999)


@pytest.mark.parametrize(
    ("step", "count"), [(30.0, 12), (15.0, 24), (7.5, 48), (5.0, 72), (1.0, 360), (0.1, 3600)]
)
def test_a_step_gives_that_many_positions_round_the_circle(step, count):
    assert positions(step) == count


@pytest.mark.parametrize("step", REFUSED)
def test_no_positions_are_counted_at_a_step_out_of_range(step):
    with pytest.raises(ValueError, match=REFUSAL):
        positions(step)


def test_every_step_taken_tries_at_least_twelve_positions():
    steps = seeded_steps()
    assert min(steps) < 1  # the family reaches both ends of the range
    assert max(steps) > 29
    counts = [positions(step) for step in (*steps, *TAKEN)]
    assert min(counts) == 12
    assert max(counts) == 3600


# ---------------------------------------------------------------------------
# The search, on a scene with no geometry.
# ---------------------------------------------------------------------------


class Angles:
    """A scene of angles: an arm is clear where ``free`` says, and hits ``wall`` elsewhere.

    The arm "solid" is its angle, as :func:`swing` hands it over, so the search is
    tested apart from any tool's shape. ``asked`` is every angle it was asked about.
    """

    def __init__(self, free):
        self.free = free
        self.asked = []

    def contacts(self, phi):
        self.asked.append(phi)
        return ((), ()) if self.free(phi) else (("wall",), ())


def swing(free, step, required=HEX_RESEAT_DEG, engagement=None):
    scene = Angles(free)
    attempt = swing_attempt(
        tool="probe",
        way="probe",
        scene=scene,
        engagement=engagement,
        arm_at=lambda phi: phi,
        required_deg=required,
        step_deg=step,
    )
    return attempt, scene


def at_zero_only(phi):
    return phi == 0


def everywhere(_phi):
    return True


@pytest.mark.parametrize("required", [RATCHET_72_SWING_DEG, RING_RESEAT_DEG, HEX_RESEAT_DEG])
def test_one_free_angle_holds_and_turns_nothing_at_any_step_taken(required):
    for step in (*TAKEN, *seeded_steps(40)):
        attempt, scene = swing(at_zero_only, step, required)
        assert (attempt.turns, attempt.holds, attempt.swing_deg) == (False, True, 0.0), step
        assert attempt.bounds == ("wall",)
        # Every position round the circle was tried, twelve at the fewest, and only
        # the one at 0 was free: no one position stood for the rest.
        assert len(scene.asked) == positions(step) >= 12, step
        assert [phi for phi in scene.asked if at_zero_only(phi)] == [0.0]


@pytest.mark.parametrize("step", REFUSED)
def test_the_search_refuses_a_step_out_of_range(step):
    with pytest.raises(ValueError, match=REFUSAL):
        swing(at_zero_only, step)


@pytest.mark.parametrize("step", [400.0, 0.0, math.nan])
def test_the_search_refuses_it_before_it_asks_the_scene_anything(step):
    # A blocked engagement ends an attempt early: not early enough to pass a step
    # no swing could be sampled at.
    scene = Angles(lambda _solid: False)
    with pytest.raises(ValueError, match=REFUSAL):
        swing_attempt(
            tool="probe",
            way="probe",
            scene=scene,
            engagement="the engagement",
            arm_at=lambda phi: phi,
            required_deg=HEX_RESEAT_DEG,
            step_deg=step,
        )
    assert scene.asked == []


def test_a_free_circle_turns_at_either_end_of_the_range():
    for step in (MIN_STEP_DEG, MAX_STEP_DEG):
        attempt, _ = swing(everywhere, step)
        assert attempt.turns
        assert attempt.swing_deg == pytest.approx(HEX_RESEAT_DEG)


def test_every_position_free_is_the_whole_circle_and_one_short_of_it_is_not():
    # A tool that had to go all the way round, as none here does. Every position
    # free is the circle; all but one is the circle less the space either side of it.
    for step in (30.0, 15.0, 5.0):
        attempt, _ = swing(everywhere, step, required=360.0)
        assert (attempt.turns, attempt.swing_deg) == (True, 360.0)
        attempt, _ = swing(lambda phi: phi != 0, step, required=360.0)
        assert (attempt.turns, attempt.holds) == (False, True)
        assert attempt.swing_deg == pytest.approx(360.0 - 2 * step)


@pytest.mark.parametrize("step", REFUSED)
def test_a_fingertip_on_a_rim_refuses_a_step_out_of_range(step):
    scene = Angles(everywhere)
    with pytest.raises(ValueError, match=REFUSAL):
        rim_attempt(ORIGIN_MOUNT, scene, 4.0, 3.0, step)
    assert scene.asked == []


# ---------------------------------------------------------------------------
# Every tool samples at the step it was handed: what a report says of its step is
# true of each swing in it.
# ---------------------------------------------------------------------------


class Clear:
    """A scene nothing is in: every tool, each way, gets as far as its swing."""

    @staticmethod
    def contacts(_solid):
        return (), ()

    @staticmethod
    def hits(_solid):
        return ()


@pytest.fixture
def steps_sampled(monkeypatch):
    """Every step a swing or a fingertip was sampled at, as the searches were handed it."""
    seen = []

    def spy(step_deg):
        seen.append(step_deg)
        return checked_step(step_deg)

    monkeypatch.setattr(sweep, "checked_step", spy)
    return seen


HEX_BAND = (0.0, -5.0)

FAMILIES = {
    "hex key": lambda step: hex_key_attempts(ORIGIN_MOUNT, ISO_2936[5.0], Clear, step),
    "ball end": lambda step: ball_end_attempts(ORIGIN_MOUNT, BALL_END_KEYS[5.0], Clear, step),
    "ring": lambda step: ring_attempts(
        ORIGIN_MOUNT, spanner_for(10.0), 10.0, HEX_BAND, Clear, step
    ),
    "open end": lambda step: open_end_attempts(
        ORIGIN_MOUNT, spanner_for(10.0), 10.0, HEX_BAND, Clear, step
    ),
    "socket": lambda step: socket_attempts(
        ORIGIN_MOUNT, socket_for(10.0), 10.0, HEX_BAND, Clear, step
    ),
    "fingers": lambda step: finger_attempts(
        ORIGIN_MOUNT, Clear, 4.0, 3.0, 0.0, nut=False, step_deg=step
    ),
}


@pytest.mark.parametrize("family", FAMILIES)
def test_each_tool_samples_at_the_step_it_is_handed(family, steps_sampled):
    attempts = list(FAMILIES[family](7.5))
    assert attempts
    assert steps_sampled, "no way of this tool reached a swing"
    assert set(steps_sampled) == {7.5}


@pytest.mark.parametrize("family", FAMILIES)
def test_each_tool_refuses_a_step_out_of_range(family):
    with pytest.raises(ValueError, match=REFUSAL):
        list(FAMILIES[family](400.0))


M6_SOCKET = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}
M6_TORX = {**M6_SOCKET, "head": "torx"}
M6_NUT = {"parts": "nut", "kind": "nut", "size": "M6"}
THUMB = {"parts": "thumb", "kind": "screw", "size": "M3", "tool": "hand"}

#: A sidecar's own key, short enough for an M6 socket head under a wall 30 over it.
STUBBY = {"name": "stubby-key-5", "type": "hex-key", "across_flats": 5, "long": 60, "short": 20}

RIM = "a fingertip on its rim"


def nut_in_a_well():
    """An M6 nut at the foot of a tube: no spanner's handle fits, a socket on an extension does."""
    plate = Pos(0, 0, -5) * Box(200, 200, 10)
    well = Pos(0, 0, 30) * (Cylinder(12, 60) - Cylinder(9, 60))
    return Assembly([Part("nut", hex_nut()), Part("plate", plate), Part("well", well)])


def thumb_in_a_cup():
    """A thumb screw's head in a cup too close round it for fingers, or a fingertip."""
    thumb = Pos(0, 0, 1.5) * Cylinder(4.0, 3.0) + Pos(0, 0, -5) * Cylinder(1.5, 10)
    plate = Pos(0, 0, -5) * Box(80, 80, 10) - Cylinder(1.6, 30)
    cup = Pos(0, 0, 10) * (Cylinder(9, 20) - Cylinder(6, 20))
    return Assembly([Part("thumb", thumb), Part("plate", plate), Part("cup", cup)])


#: Each road check has to a swing: a model, its rule, the sidecar's own tools, and
#: what must be among the attempts for the road to have been taken.
ROADS = {
    "the kit's hex key": (lambda: screw_facing_wall(50.0), M6_SOCKET, (), {"hex-key-5"}),
    "a hex key the rule names": (
        lambda: screw_facing_wall(50.0),
        {**M6_SOCKET, "tool": "hex-key-5"},
        (),
        {"hex-key-5"},
    ),
    "the kit's Torx key": (lambda: screw_facing_wall(50.0), M6_TORX, (), {"torx-key-T30"}),
    "a Torx key the rule names": (
        lambda: screw_facing_wall(50.0),
        {**M6_TORX, "tool": "torx-key-T30"},
        (),
        {"torx-key-T30"},
    ),
    "a ball end, then the sidecar's own key": (
        lambda: screw_facing_wall(30.0),
        M6_SOCKET,
        (STUBBY,),
        {"hex-key-5", "ball-end-key-5", "stubby-key-5"},
    ),
    "the sidecar's own key the rule names": (
        lambda: screw_facing_wall(30.0),
        {**M6_SOCKET, "tool": "stubby-key-5"},
        (STUBBY,),
        {"stubby-key-5"},
    ),
    "a ring": (nut_on_plate, M6_NUT, (), {"spanner-10"}),
    "an open end, then a socket": (nut_in_a_well, M6_NUT, (), {"open end, stubby", "socket-10"}),
    "a fingertip on a rim": (thumb_in_a_cup, THUMB, (), {RIM}),
}


@pytest.mark.parametrize("road", ROADS)
def test_check_hands_every_tool_the_run_s_step(road, steps_sampled):
    # A report says the step it ran at, which has to be true of each swing in it:
    # check reaches the tools by ten calls, and one handing over the default would
    # go unseen in every run at 15.
    model, rule, own, taken = ROADS[road]
    config = Config.from_dict({"fasteners": [rule], "tools": list(own)})
    report = check(model(), config, kit="full", step_deg=7.5)
    (result,) = report.results
    tried = {attempt.tool for attempt in result.attempts}
    tried |= {attempt.way for attempt in result.attempts}
    assert tried >= taken
    assert steps_sampled
    assert set(steps_sampled) == {7.5}
    assert report.step_deg == 7.5


# ---------------------------------------------------------------------------
# The issue's model: a socket head screw a key holds at one angle only.
# ---------------------------------------------------------------------------


def slotted_tube(low=-5.0, high=5.0):
    """The issue's model, by part: an M3x10 socket head screw free at one angle.

    An ISO 4762 M3x10 (head 5.5 across and 3 tall, a 2.5 hex socket 1.3 deep) in a
    30 x 30 x 5 plate. A slab 40 mm over its head keeps a hex key from going in as a
    driver, and a tube round it (radius 25 to 28, from the plate up to the slab)
    stops the key's long arm everywhere but in a slot 10 degrees wide on +X: from
    ``low`` to ``high`` degrees round +Z, measured from +X.
    """
    socket = Pos(0, 0, 1.7) * extrude(RegularPolygon(2.5 / math.sqrt(3), 6), 1.3)
    screw = Pos(0, 0, 1.5) * Cylinder(2.75, 3) + Pos(0, 0, -5) * Cylinder(1.5, 10) - socket
    plate = Pos(0, 0, -2.5) * Box(30, 30, 5) - Cylinder(1.5, 20)
    across = (low, (low + high) / 2, high)
    edge = [(40 * math.cos(math.radians(a)), 40 * math.sin(math.radians(a))) for a in across]
    slot = extrude(Polygon((0, 0), *edge, align=None), 50)
    wall = Pos(0, 0, 21.5) * (Cylinder(28, 43) - Cylinder(25, 43)) - slot
    slab = Pos(0, 0, 44) * Box(10, 10, 2)
    return {"plate": plate, "M3x10 SHCS": screw, "slab": slab, "wall": wall}


M3_SOCKET = {"parts": "M3x10 SHCS", "kind": "screw", "head": "socket", "size": "M3"}

ONLY_HOLDS = "only holds, and it has no nut; best arc bounded by wall"


def check_slot(engine="mesh", slot=(-5.0, 5.0), checks=None, **kwargs):
    assembly = Assembly([Part(name, shape) for name, shape in slotted_tube(*slot).items()])
    sidecar = {"fasteners": [M3_SOCKET], **({} if checks is None else {"checks": checks})}
    return check(assembly, Config.from_dict(sidecar), engine=engine, **kwargs)


def export_slot(model, low=-5.0, high=5.0):
    """A slotted tube's model as a STEP file: the screw is found by its name."""
    shapes = []
    for name, shape in slotted_tube(low, high).items():
        shape.label = name
        shapes.append(shape)
    export_step(Compound(children=shapes), str(model))
    return model


@pytest.mark.parametrize("step", [30.0, 20.5, 15.0, 7.5, 5.0])
def test_a_key_free_at_one_angle_only_holds_at_every_step(engine, step):
    report = check_slot(engine, step_deg=step)
    (result,) = report.results
    assert (result.verdict, result.tool, result.reason) == (
        Verdict.BLOCKED,
        "hex-key-2.5",
        ONLY_HOLDS,
    )
    assert result.deciding == ("wall",)
    driver, short_leg, long_leg = result.attempts
    assert (driver.blockers, long_leg.blockers) == (("slab",), ("slab",))
    assert (short_leg.turns, short_leg.holds, short_leg.swing_deg) == (False, True, 0.0)
    # The leg in the socket, then the arm at every position the step gives.
    assert len(short_leg.probes) == 1 + positions(step)
    assert report.exit_code == 1


def test_a_finer_step_finds_a_slot_s_few_degrees_and_still_only_holds(engine):
    # A slot 12 degrees wide. The key's arm is 2.82 across its corners, 6.5 degrees
    # at the tube's 25 mm, so its centre line has 2.77 degrees either side of +X.
    # At a step of 2 the positions 2 either side are 0.3 mm clear of the wall and
    # the ones at 4 half a millimetre into it: three free, two steps of swing.
    (result,) = check_slot(engine, (-6.0, 6.0), step_deg=2.0).results
    short_leg = result.attempts[1]
    assert (result.verdict, result.reason) == (Verdict.BLOCKED, ONLY_HOLDS)
    assert (short_leg.turns, short_leg.holds) == (False, True)
    assert short_leg.swing_deg == pytest.approx(4.0)


def test_the_finest_step_is_a_run_that_ends():
    (result,) = check_slot(step_deg=MIN_STEP_DEG).results
    short_leg = result.attempts[1]
    assert (result.verdict, short_leg.holds) == (Verdict.BLOCKED, True)
    assert len(short_leg.probes) == 3601
    assert 3.0 < short_leg.swing_deg < 5.0


@pytest.mark.parametrize("step", REFUSED)
def test_check_refuses_a_step_out_of_range(engine, step):
    with pytest.raises(ValueError, match=REFUSAL):
        check_slot(engine, step_deg=step)


@pytest.mark.parametrize("step", [0.0, 400.0, math.nan])
def test_check_refuses_it_with_nothing_to_swing_a_tool_on(step):
    # No fastener, so no swing: the step is still what the report would say it ran at.
    nothing = Config.from_dict({"checks": {"detect": False}})
    assert check(screw_facing_wall(40.0), nothing).summary["fasteners"] == 0
    with pytest.raises(ValueError, match=REFUSAL):
        check(screw_facing_wall(40.0), nothing, step_deg=step)


# ---------------------------------------------------------------------------
# The report records the step it was run at.
# ---------------------------------------------------------------------------


def test_a_report_made_by_hand_is_at_the_default_step():
    assert Report(model="m", kit="full", results=()).step_deg == DEFAULT_STEP_DEG


def test_a_run_s_report_carries_its_step():
    assert check_slot().step_deg == DEFAULT_STEP_DEG
    for step in (5, 7.5, 30.0):
        carried = check_slot(step_deg=step).step_deg
        assert (carried, type(carried)) == (float(step), float)


def test_the_json_records_the_step_beside_the_engine():
    document = check_slot(step_deg=5.0).to_json_dict()
    assert document["step_deg"] == 5.0
    assert list(document)[:5] == ["schema", "model", "kit", "engine", "step_deg"]
    assert check_slot().to_json_dict()["step_deg"] == 15.0
    assert json.loads(check_slot(step_deg=7.5).json_text())["step_deg"] == 7.5


@pytest.mark.parametrize(("step", "said"), [(None, "15"), (5.0, "5"), (7.5, "7.5"), (0.25, "0.25")])
def test_the_markdown_says_the_step_on_its_kit_line(step, said):
    report = check_slot() if step is None else check_slot(step_deg=step)
    assert report.markdown().splitlines()[4] == (
        f"Kit `metric-home`, swings tried every {said} deg, mesh engine, wrenchroom {__version__}."
    )


# ---------------------------------------------------------------------------
# The command line: the issue's table.
# ---------------------------------------------------------------------------

BLOCKED_LINE = (
    "FAIL M3x10 SHCS  hex-key-2.5  blocked  only holds, and it has no nut; best arc bounded by wall"
)

USAGE = "Error: Invalid value for '--step-deg': " + REFUSAL

#: As typed: the issue's own (0, nan, 250, 300, 400, inf, -15), and 200, which gave
#: the right answer from two positions and is past the widest step all the same.
TYPED_REFUSED = [
    "0",
    "nan",
    "250",
    "300",
    "400",
    "inf",
    "-inf",
    "-15",
    "200",
    "30.5",
    "0.05",
    "1e-320",
]


@pytest.fixture(scope="module")
def slot_step(tmp_path_factory):
    """The issue's model as a STEP file with no sidecar: the screw is found by its name."""
    return export_slot(tmp_path_factory.mktemp("slot") / "slot.step")


@pytest.mark.parametrize(
    "flags", [[], ["--step-deg", "5"], ["--step-deg", "30"], ["--step-deg=7.5"]]
)
def test_check_blocks_the_key_at_every_step_taken(slot_step, flags):
    result = CliRunner().invoke(main, ["check", str(slot_step), *flags])
    assert result.exit_code == 1
    assert "1 fasteners: 0 turn, 0 held, 1 blocked, 0 stuck, 0 not covered" in result.output
    assert BLOCKED_LINE in result.output


@pytest.mark.parametrize("typed", TYPED_REFUSED)
def test_check_refuses_a_step_out_of_range_as_a_usage_error(slot_step, typed):
    result = CliRunner().invoke(main, ["check", str(slot_step), f"--step-deg={typed}"])
    assert result.exit_code == EXIT_NOT_COVERED
    assert isinstance(result.exception, SystemExit)  # said, not a traceback
    assert USAGE in result.output
    assert "fasteners" not in result.output  # nothing was checked


@pytest.mark.parametrize("typed", TYPED_REFUSED)
def test_explain_refuses_a_step_out_of_range_as_a_usage_error(slot_step, typed):
    arguments = ["explain", str(slot_step), "M3x10 SHCS", f"--step-deg={typed}"]
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == EXIT_NOT_COVERED
    assert isinstance(result.exception, SystemExit)
    assert USAGE in result.output
    assert "tried" not in result.output


def test_a_negative_step_typed_after_a_space_is_refused_too(slot_step):
    result = CliRunner().invoke(
        main, ["explain", str(slot_step), "M3x10 SHCS", "--step-deg", "-15"]
    )
    assert result.exit_code == EXIT_NOT_COVERED
    assert USAGE + "-15.0" in result.output


def test_explain_tells_the_one_angle_at_a_step_taken(slot_step):
    arguments = ["explain", str(slot_step), "M3x10 SHCS", "--step-deg", "5"]
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 1
    assert "M3x10 SHCS: blocked" in result.output
    assert "tried hex-key-2.5, driver straight in: blocked; hit slab" in result.output
    assert (
        "tried hex-key-2.5, short leg in: holds, at one angle only (60 deg needed), "
        "bounded by wall; hit wall"
    ) in result.output


@pytest.mark.parametrize("command", [["check"], ["explain", "M3x10 SHCS"]])
def test_a_step_out_of_range_is_refused_before_the_model_is_read(tmp_path, command):
    scrawl = tmp_path / "scrawl.step"
    scrawl.write_text("no STEP file\n")
    verb, *rest = command
    refused = CliRunner().invoke(main, [verb, str(scrawl), *rest, "--step-deg=400"])
    assert refused.exit_code == EXIT_NOT_COVERED
    assert USAGE in refused.output
    assert "error:" not in refused.output
    # At a step taken the model is read, and it is the model the run fails on.
    read = CliRunner().invoke(main, [verb, str(scrawl), *rest, "--step-deg=30"])
    assert read.exit_code == EXIT_NOT_COVERED
    assert "error:" in read.output
    assert "--step-deg" not in read.output


@pytest.mark.parametrize("command", ["check", "explain"])
def test_the_help_gives_the_range_the_sidecar_s_key_and_the_default(command):
    result = CliRunner().invoke(main, [command, "--help"])
    assert result.exit_code == 0
    said = " ".join(result.output.split())
    assert (
        f"degrees, from {MIN_STEP_DEG:g} to {MAX_STEP_DEG:g} (as `checks: {{step_deg: 5}}`); "
        f"{DEFAULT_STEP_DEG:g} unless the sidecar says."
    ) in said


def test_no_way_of_running_the_check_has_a_step_of_its_own_to_hide_the_sidecar_s():
    # A default of 15 anywhere on the way would be a step given, and outrank the sidecar.
    run = cli._run  # noqa: SLF001  (what check, explain and tools --used all go through)
    assert inspect.signature(run).parameters["step_deg"].default is None
    assert inspect.signature(check).parameters["step_deg"].default is None


def test_check_writes_its_step_in_the_json_and_the_markdown(slot_step, tmp_path):
    for flags, step, said in (([], 15.0, "15"), (["--step-deg", "5"], 5.0, "5")):
        json_path, md_path = tmp_path / "report.json", tmp_path / "report.md"
        outputs = ["--json", str(json_path), "--md", str(md_path)]
        result = CliRunner().invoke(main, ["check", str(slot_step), *flags, *outputs])
        assert result.exit_code == 1
        assert json.loads(json_path.read_text())["step_deg"] == step
        assert (
            f"Kit `metric-home`, swings tried every {said} deg, mesh engine" in md_path.read_text()
        )


# ---------------------------------------------------------------------------
# A step that doesn't divide the circle (issue #185): the positions are even.
# ---------------------------------------------------------------------------

#: Steps 360 is no whole number of, each with the count of positions it is taken as.
UNEVEN = {20.5: 18, 25.0: 14, 28.7: 13, 7.7: 47, 11.0: 33, 0.7: 514}


def nowhere(_phi):
    return False


def arc(start, width):
    """Free on the arc from ``start`` on for ``width`` degrees, its ends too, across 0 or not."""
    return lambda phi: (phi - start) % 360.0 <= width


def gaps(angles):
    """The space from each position to the next, and from the last back round to the first."""
    return [b - a for a, b in zip(angles, [*angles[1:], angles[0] + 360.0], strict=True)]


@pytest.mark.parametrize("step", [*UNEVEN, *TAKEN])
def test_the_positions_are_spaced_evenly_round_the_circle(step):
    _, scene = swing(nowhere, step)
    assert len(scene.asked) == positions(step)
    assert scene.asked[0] == 0.0
    spaces = gaps(scene.asked)
    assert max(spaces) - min(spaces) < 1e-9
    assert spaces[-1] == pytest.approx(360.0 / positions(step))  # across 0 as anywhere


@pytest.mark.parametrize(("step", "count"), UNEVEN.items())
def test_a_step_that_doesn_t_divide_the_circle_is_the_nearest_count_of_positions(step, count):
    assert positions(step) == count
    _, scene = swing(nowhere, step)
    assert scene.asked == pytest.approx([index * 360.0 / count for index in range(count)])


@pytest.mark.parametrize("step", [30.0, 15.0, 7.5, 5.0, 1.0, 0.5, 0.25])
def test_a_step_that_divides_the_circle_is_tried_at_its_own_multiples(step):
    _, scene = swing(nowhere, step)
    assert scene.asked == [index * step for index in range(round(360 / step))]


class ArmAndHand:
    """A scene nothing is in, which keeps where the arm, and the hand on it, were tried."""

    def __init__(self):
        self.arms = []
        self.hands = []

    def contacts(self, phi):
        self.arms.append(phi)
        return (), ()

    def hits(self, phi):
        self.hands.append(phi)
        return ()


@pytest.mark.parametrize("step", UNEVEN)
def test_the_hand_is_tried_where_the_arm_is_at_a_step_that_doesn_t_divide_the_circle(step):
    scene = ArmAndHand()
    attempt = swing_attempt(
        tool="probe",
        way="probe",
        scene=scene,
        engagement=None,
        arm_at=lambda phi: phi,
        hand_at=lambda phi: phi,
        required_deg=HEX_RESEAT_DEG,
        step_deg=step,
    )
    assert attempt.turns
    assert len(scene.arms) >= 3
    assert scene.hands == scene.arms
    assert scene.arms[1] == pytest.approx(360.0 / UNEVEN[step])


def test_an_arc_across_zero_is_worth_what_it_spans():
    # The issue's figures. At 20.5 there were 18 positions, 0 to 348.5, and the 11.5
    # degrees from the last back to 0 counted as a step: the four from 307.5 to 0,
    # 52.5 degrees apart, read as 61.5, and a key that needs 60 turned.
    key_room = arc(305.4, 56.7)  # a little under 57 degrees, ending just past 0
    for step, proved in ((15.0, 45.0), (5.0, 50.0), (1.0, 56.0), (20.0, 40.0), (20.5, 40.0)):
        attempt, _ = swing(key_room, step)
        assert (attempt.turns, attempt.holds) == (False, True), step
        assert attempt.swing_deg == pytest.approx(proved), step


def test_the_same_arc_is_worth_the_same_wherever_it_lies():
    # Even positions make no part of the circle special: turned round to start on a
    # position anywhere, an arc holds as many, and proves as much.
    for step in UNEVEN:
        count = positions(step)
        proved = {
            swing(arc(index * 360.0 / count, 56.7), step)[0].swing_deg
            for index in range(0, count, max(count // 12, 1))
        }
        assert len(proved) == 1, step


def test_no_step_proves_more_arc_than_there_is():
    rng = np.random.default_rng(185)
    crossing = turned = held = blocked = 0
    for _ in range(3000):
        step = float(rng.uniform(1.0, MAX_STEP_DEG))
        start, width = float(rng.uniform(0.0, 360.0)), float(rng.uniform(0.0, 150.0))
        required = float(rng.choice([RATCHET_72_SWING_DEG, RING_RESEAT_DEG, HEX_RESEAT_DEG]))
        free = arc(start, width)
        attempt, _ = swing(free, step, required)
        count = positions(step)
        space = 360.0 / count
        inside = sum(free(index * 360.0 / count) for index in range(count))
        case = (step, start, width, required)
        # What is proved lies in the free arc, first position to last.
        assert attempt.swing_deg <= width + 1e-9, case
        assert attempt.holds == (inside >= 1), case
        assert attempt.turns == ((inside - 1) * space >= required - 1e-9), case
        if attempt.turns:
            # The search stops at the first run long enough: under a space past it.
            assert required - 1e-9 <= attempt.swing_deg < required + space, case
        else:
            assert attempt.swing_deg == pytest.approx(max(inside - 1, 0) * space), case
        # An arc two spaces longer than a tool needs is never missed.
        assert attempt.turns or width < required + 2 * space, case
        crossing += start + width > 360.0
        turned += attempt.turns
        held += attempt.holds and not attempt.turns
        blocked += not attempt.holds
    # Not vacuous: arcs across 0 and clear of it, tools that turn, hold and neither.
    assert min(crossing, 3000 - crossing, turned, held) > 400
    assert blocked > 20


#: A slot from 56 degrees one side of +X to 6 the other: the key's arm, about 6
#: degrees across at the tube, has under 56 degrees of room, and needs 60. Each
#: step's first and last free positions stand a degree or more inside the room.
WIDE_SLOT = (-56.0, 6.0)
MIRRORED = (-6.0, 56.0)

#: The arc each step proves in that slot: one space fewer than its positions there.
PROVED = {
    15.0: 45.0,
    5.0: 50.0,
    2.0: 54.0,
    20.0: 40.0,
    20.5: 40.0,  # 18 positions, 20 apart: it read 61.5, and turned
    25.0: 2 * 360.0 / 14,
    28.7: 360.0 / 13,
}


@pytest.mark.parametrize("slot", [WIDE_SLOT, MIRRORED])
@pytest.mark.parametrize("step", PROVED)
def test_a_key_with_under_sixty_degrees_of_room_turns_at_no_step(engine, slot, step):
    report = check_slot(engine, slot, step_deg=step)
    (result,) = report.results
    short_leg = result.attempts[1]
    assert (result.verdict, result.reason) == (Verdict.BLOCKED, ONLY_HOLDS)
    assert (short_leg.turns, short_leg.holds) == (False, True)
    assert short_leg.swing_deg == pytest.approx(PROVED[step])
    assert short_leg.swing_deg < 56.0
    assert report.step_deg == step  # the step asked, whatever it was taken as


@pytest.fixture(scope="module")
def wide_slot_step(tmp_path_factory):
    """The wide slot as a STEP file, across 0 the way the positions are walked."""
    return export_slot(tmp_path_factory.mktemp("wide") / "wide.step", *WIDE_SLOT)


@pytest.mark.parametrize(
    ("typed", "best"), [("20.5", "40"), ("20", "40"), ("15", "45"), ("5", "50")]
)
def test_explain_tells_the_arc_the_key_has_at_a_step_that_doesn_t_divide_360(
    wide_slot_step, typed, best
):
    arguments = ["explain", str(wide_slot_step), "M3x10 SHCS", "--step-deg", typed]
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 1
    assert "M3x10 SHCS: blocked" in result.output
    assert (
        f"tried hex-key-2.5, short leg in: holds, best {best} of 60 deg, bounded by wall"
    ) in result.output


def test_check_blocks_it_at_a_step_that_doesn_t_divide_360(wide_slot_step):
    result = CliRunner().invoke(main, ["check", str(wide_slot_step), "--step-deg", "20.5"])
    assert result.exit_code == 1
    assert BLOCKED_LINE in result.output


# ---------------------------------------------------------------------------
# The sidecar's step (issue #188): every way of running the check takes it.
# ---------------------------------------------------------------------------

#: A slot from 11 degrees one side of +X to 62 the other: the key's arm has about 66
#: degrees of room and needs 60. At 15 the positions in it are 0 to 45, which prove
#: 45; at 5 they run from -5 to 55, which prove 60. Each end position stands over a
#: degree inside the room or past it.
GAP = (-11.0, 62.0)


def from_checks(**checks):
    return Config.from_dict({"checks": checks})


def test_a_sidecar_with_no_step_has_none():
    assert Config().step_deg is None
    assert Config.from_dict({}).step_deg is None
    assert from_checks(hand_room=True).step_deg is None
    assert from_checks(step_deg=None).step_deg is None


@pytest.mark.parametrize("step", TAKEN)
def test_a_sidecar_s_step_in_range_is_taken(step):
    assert from_checks(step_deg=step).step_deg == step


def test_a_sidecar_s_whole_number_of_degrees_is_a_float():
    taken = from_checks(step_deg=5).step_deg
    assert (taken, type(taken)) == (5.0, float)


@pytest.mark.parametrize("step", REFUSED)
def test_a_sidecar_s_step_out_of_range_is_a_config_error(step):
    with pytest.raises(ConfigError, match="^<dict>: checks: step_deg: " + REFUSAL):
        from_checks(step_deg=step)


@pytest.mark.parametrize("step", ["5", "fine", True, False, [5], {"deg": 5}])
def test_a_sidecar_s_step_that_is_no_number_is_a_config_error(step):
    with pytest.raises(ConfigError, match=r"^<dict>: checks: step_deg must be a number of degrees"):
        from_checks(step_deg=step)


@pytest.mark.parametrize("key", ["step", "step-deg", "step_degrees"])
def test_another_spelling_of_the_key_is_unknown_not_ignored(key):
    with pytest.raises(ConfigError, match="unknown key"):
        Config.from_dict({"checks": {key: 5}})


@pytest.mark.parametrize(
    ("written", "said"),
    [
        ("400", "a swing step is from 0.1 to 30 degrees, not 400"),
        ("0", "a swing step is from 0.1 to 30 degrees, not 0"),
        (".nan", "a swing step is from 0.1 to 30 degrees, not nan"),
        (".inf", "a swing step is from 0.1 to 30 degrees, not inf"),
        ("yes", "must be a number of degrees, not True"),
        ("fine", "must be a number of degrees, not 'fine'"),
    ],
)
def test_a_sidecar_file_s_bad_step_names_the_file_and_the_key(tmp_path, written, said):
    sidecar = tmp_path / "wrenchroom.yaml"
    sidecar.write_text(f"checks:\n  step_deg: {written}\n")
    with pytest.raises(ConfigError) as error:
        Config.load(sidecar)
    assert str(error.value).startswith(f"{sidecar}: checks: step_deg")
    assert str(error.value).endswith(said)


def test_a_sidecar_file_s_step_is_read(tmp_path):
    sidecar = tmp_path / "wrenchroom.yaml"
    sidecar.write_text("checks:\n  step_deg: 7.5\n")
    assert Config.load(sidecar).step_deg == 7.5


@pytest.mark.parametrize(
    ("asked", "sidecar", "used"),
    [
        (None, None, 15.0),
        (None, 5, 5.0),
        (None, 30.0, 30.0),
        (7.5, None, 7.5),
        (7.5, 5, 7.5),
        (15.0, 5, 15.0),  # the default, asked for: it is a step given like any other
    ],
)
def test_a_run_swings_at_the_step_asked_then_the_sidecar_s_then_the_default(
    asked, sidecar, used, steps_sampled
):
    checks = None if sidecar is None else {"step_deg": sidecar}
    kwargs = {} if asked is None else {"step_deg": asked}
    report = check_slot(checks=checks, **kwargs)
    assert steps_sampled
    assert set(steps_sampled) == {used}
    assert (report.step_deg, type(report.step_deg)) == (used, float)
    assert report.to_json_dict()["step_deg"] == used


@pytest.mark.parametrize("step", [0.0, 400.0, math.nan])
def test_a_step_asked_out_of_range_is_refused_whatever_the_sidecar_says(step):
    with pytest.raises(ValueError, match=REFUSAL):
        check_slot(checks={"step_deg": 5}, step_deg=step)


def test_a_key_the_default_step_misses_turns_at_the_sidecar_s(engine):
    (coarse,) = check_slot(engine, GAP).results
    assert (coarse.verdict, coarse.reason) == (Verdict.BLOCKED, ONLY_HOLDS)
    assert coarse.attempts[1].swing_deg == pytest.approx(45.0)
    (fine,) = check_slot(engine, GAP, checks={"step_deg": 5}).results
    assert (fine.verdict, fine.tool, fine.how) == (Verdict.TURNS, "hex-key-2.5", "short leg in")
    assert fine.attempts[1].swing_deg == pytest.approx(60.0)
    (back,) = check_slot(engine, GAP, checks={"step_deg": 5}, step_deg=15.0).results
    assert (back.verdict, back.reason) == (Verdict.BLOCKED, ONLY_HOLDS)


@pytest.fixture(scope="module")
def gap_models(tmp_path_factory):
    """The gap's model twice: beside a sidecar that says a step of 5, and with none."""
    stepped, plain = tmp_path_factory.mktemp("stepped"), tmp_path_factory.mktemp("plain")
    (stepped / "wrenchroom.yaml").write_text("checks:\n  step_deg: 5\n")
    return export_slot(stepped / "gap.step", *GAP), export_slot(plain / "gap.step", *GAP)


def test_check_takes_the_sidecar_s_step_and_the_flag_outranks_it(gap_models, tmp_path):
    stepped, plain = gap_models
    json_path, md_path = tmp_path / "report.json", tmp_path / "report.md"
    outputs = ["--json", str(json_path), "--md", str(md_path)]

    fine = CliRunner().invoke(main, ["check", str(stepped), *outputs])
    assert fine.exit_code == 0
    assert "1 fasteners: 1 turn, 0 held, 0 blocked, 0 stuck, 0 not covered" in fine.output
    assert json.loads(json_path.read_text())["step_deg"] == 5.0
    assert "swings tried every 5 deg" in md_path.read_text()

    coarse = CliRunner().invoke(main, ["check", str(stepped), "--step-deg", "15", *outputs])
    assert coarse.exit_code == 1
    assert BLOCKED_LINE in coarse.output
    assert json.loads(json_path.read_text())["step_deg"] == 15.0

    default = CliRunner().invoke(main, ["check", str(plain), *outputs])
    assert default.exit_code == 1
    assert BLOCKED_LINE in default.output
    assert json.loads(json_path.read_text())["step_deg"] == 15.0

    asked = CliRunner().invoke(main, ["check", str(plain), "--step-deg", "5"])
    assert asked.exit_code == 0


def test_explain_takes_the_sidecar_s_step_and_the_flag_outranks_it(gap_models):
    stepped, plain = gap_models
    fine = CliRunner().invoke(main, ["explain", str(stepped), "M3x10 SHCS"])
    assert fine.exit_code == 0
    assert "M3x10 SHCS: turns with hex-key-2.5, short leg in" in fine.output
    for arguments in ([str(stepped), "M3x10 SHCS", "--step-deg", "15"], [str(plain), "M3x10 SHCS"]):
        coarse = CliRunner().invoke(main, ["explain", *arguments])
        assert coarse.exit_code == 1
        assert "short leg in: holds, best 45 of 60 deg, bounded by wall" in coarse.output


def test_the_tools_a_model_needs_are_found_at_the_sidecar_s_step(gap_models):
    # The issue: the model passed check --step-deg 5, and was told it needed no tools.
    stepped, plain = gap_models
    fine = CliRunner().invoke(main, ["tools", "--used", str(stepped)])
    assert fine.exit_code == 0
    assert "1 tool this model needs (kit metric-home): 1 hex key" in fine.output
    assert "hex-key-2.5" in fine.output
    assert "blocked" not in fine.output
    coarse = CliRunner().invoke(main, ["tools", "--used", str(plain)])
    assert coarse.exit_code == 0
    assert "0 tools this model needs (kit metric-home): none" in coarse.output
    assert "blocked, once reached: hex-key-2.5 x1" in coarse.output


def test_a_sidecar_named_on_the_command_line_gives_its_step_too(gap_models, tmp_path):
    _, plain = gap_models
    sidecar = tmp_path / "fine.yaml"
    sidecar.write_text("checks:\n  step_deg: 5\n")
    named = [str(plain), "--config", str(sidecar)]
    checked = CliRunner().invoke(main, ["check", *named])
    assert checked.exit_code == 0
    assert "1 fasteners: 1 turn, 0 held, 0 blocked" in checked.output
    listed = CliRunner().invoke(main, ["tools", "--used", *named])
    assert listed.exit_code == 0
    assert "1 tool this model needs (kit metric-home): 1 hex key" in listed.output


@pytest.mark.parametrize(
    "command", [["check"], ["explain", "M3x10 SHCS"], ["tools", "--used"], ["clashes"]]
)
@pytest.mark.parametrize(
    ("written", "said"),
    [
        ("400", "checks: step_deg: a swing step is from 0.1 to 30 degrees, not 400"),
        (".nan", "checks: step_deg: a swing step is from 0.1 to 30 degrees, not nan"),
        ("yes", "checks: step_deg must be a number of degrees, not True"),
    ],
)
def test_a_sidecar_s_bad_step_is_a_config_error_from_every_command(
    gap_models, tmp_path, command, written, said
):
    _, plain = gap_models
    sidecar = tmp_path / "bad.yaml"
    sidecar.write_text(f"checks:\n  step_deg: {written}\n")
    verb, *rest = command
    arguments = [verb, *([] if verb == "explain" else rest), str(plain)]
    arguments += rest if verb == "explain" else []
    result = CliRunner().invoke(main, [*arguments, "--config", str(sidecar)])
    assert result.exit_code == EXIT_NOT_COVERED
    assert isinstance(result.exception, SystemExit)  # said, not a traceback
    assert f"error: {sidecar}: {said}" in result.output


PLUGIN_TEST = """
def test_every_fastener_reachable(wrenchroom_report):
    assert wrenchroom_report.step_deg == {step}
    wrenchroom_report.assert_all_pass()
"""


def test_the_pytest_plugin_checks_at_the_sidecar_s_step(pytester):
    cad = pytester.path / "cad"
    cad.mkdir()
    export_slot(cad / "gap.step", *GAP)
    pytester.makeini("[pytest]\nwrenchroom_model = cad/gap.step\n")
    # With no step in a sidecar, the plugin's run is at 15, and the key only holds.
    pytester.makepyfile(test_design=PLUGIN_TEST.format(step=15.0))
    coarse = pytester.runpytest()
    coarse.assert_outcomes(failed=1)
    coarse.stdout.fnmatch_lines(["*FAIL M3x10 SHCS  hex-key-2.5  blocked*"])


def test_the_pytest_plugin_passes_the_model_its_sidecar_s_step_passes(pytester):
    cad = pytester.path / "cad"
    cad.mkdir()
    export_slot(cad / "gap.step", *GAP)
    (cad / "wrenchroom.yaml").write_text("checks:\n  step_deg: 5\n")
    pytester.makeini("[pytest]\nwrenchroom_model = cad/gap.step\n")
    pytester.makepyfile(test_design=PLUGIN_TEST.format(step=5.0))
    pytester.runpytest().assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# What a run says of itself (issue #192): the step asked for, and what it came to.
# ---------------------------------------------------------------------------

#: A step, the positions round the circle it comes to, and how far apart they are.
CAME_TO = [
    (15.0, 24, 15.0),
    (30.0, 12, 30.0),
    (0.1, 3600, 0.1),
    (7.5, 48, 7.5),
    (20.5, 18, 20.0),
    (29.0, 12, 30.0),
    (7.0, 51, 360.0 / 51),
    (0.7, 514, 360.0 / 514),
]


def open_screw():
    """The issue's model with no tube round it: the key's arm swings free all round."""
    return Assembly([Part(n, s) for n, s in slotted_tube().items() if n != "wall"])


def check_open(**kwargs):
    return check(open_screw(), Config.from_dict({"fasteners": [M3_SOCKET]}), **kwargs)


@pytest.mark.parametrize(("step", "count", "apart"), CAME_TO)
def test_a_report_says_the_positions_its_step_came_to_and_how_far_apart(step, count, apart):
    report = Report(model="m", kit="full", results=(), step_deg=step)
    assert (report.step_deg, report.swing_positions) == (step, count)
    assert type(report.swing_positions) is int
    assert report.spacing_deg == pytest.approx(apart)
    assert report.swing_positions == positions(step)


def test_a_report_made_by_hand_is_at_twenty_four_positions():
    report = Report(model="m", kit="full", results=())
    assert (report.swing_positions, report.spacing_deg) == (24, 15.0)


@pytest.mark.parametrize(("step", "count", "apart"), CAME_TO)
def test_the_json_records_the_positions_beside_the_step(step, count, apart):
    document = check_open(step_deg=step).to_json_dict()
    assert (document["step_deg"], document["swing_positions"]) == (step, count)
    assert list(document)[:7] == [
        "schema",
        "model",
        "kit",
        "engine",
        "step_deg",
        "swing_positions",
        "tool_version",
    ]
    # What the count is for: the arc is a whole number of the spaces it gives.
    arc = document["fasteners"][0]["swing_deg"]
    assert arc / apart == pytest.approx(round(arc / apart), abs=1e-4)
    assert json.loads(check_open(step_deg=step).json_text())["swing_positions"] == count


@pytest.mark.parametrize(
    ("step", "arc_in_json", "spaces"),
    [(20.5, 60.0, 3), (29.0, 60.0, 2), (7.0, 63.5294, 9), (15.0, 60.0, 4), (0.7, 60.2335, 86)],
)
def test_an_arc_in_the_json_has_six_figures_and_the_result_keeps_the_float(
    step, arc_in_json, spaces
):
    # The issue's table: at 7 the arc was 63.529411764705884 in the JSON.
    report = check_open(step_deg=step)
    (result,) = report.results
    assert (result.verdict, result.how) == (Verdict.TURNS, "short leg in")
    assert result.swing_deg == pytest.approx(spaces * 360.0 / positions(step), abs=1e-12)
    (entry,) = report.to_json_dict()["fasteners"]
    assert entry["swing_deg"] == arc_in_json
    assert entry["swing_deg"] == float(f"{result.swing_deg:g}")  # as the terminal prints it


def test_an_arc_that_comes_out_even_is_as_it_was_in_the_json():
    for slot, step, arc in (
        (WIDE_SLOT, 15.0, 45.0),
        (WIDE_SLOT, 25.0, 51.4286),
        ((-5.0, 5.0), 5.0, 0.0),
    ):
        (entry,) = check_slot(slot=slot, step_deg=step).to_json_dict()["fasteners"]
        assert entry["swing_deg"] == arc


@pytest.mark.parametrize(
    ("step", "said"),
    [
        (15.0, "every 15 deg"),
        (5.0, "every 5 deg"),
        (0.1, "every 0.1 deg"),
        (7.5, "every 7.5 deg"),
        (20.5, "every 20 deg (20.5 asked)"),
        (29.0, "every 30 deg (29 asked)"),
        (7.0, "every 7.05882 deg (7 asked)"),
        (0.7, "every 0.700389 deg (0.7 asked)"),
    ],
)
def test_the_markdown_says_the_spacing_and_the_step_asked_where_they_differ(step, said):
    report = check_open(step_deg=step)
    assert report.swings_tried == said
    assert report.markdown().splitlines()[4] == (
        f"Kit `metric-home`, swings tried {said}, mesh engine, wrenchroom {__version__}."
    )


def test_check_writes_the_positions_and_the_spacing_at_a_step_that_doesn_t_divide_360(
    wide_slot_step, tmp_path
):
    json_path, md_path = tmp_path / "report.json", tmp_path / "report.md"
    outputs = ["--json", str(json_path), "--md", str(md_path)]
    result = CliRunner().invoke(
        main, ["check", str(wide_slot_step), "--step-deg", "20.5", *outputs]
    )
    assert result.exit_code == 1
    document = json.loads(json_path.read_text())
    assert (document["step_deg"], document["swing_positions"]) == (20.5, 18)
    assert document["fasteners"][0]["swing_deg"] == 40.0
    assert "swings tried every 20 deg (20.5 asked), mesh engine" in md_path.read_text()


# ---------------------------------------------------------------------------
# check() with no sidecar (issue #192): an empty one, with detection on.
# ---------------------------------------------------------------------------


def test_check_with_no_sidecar_finds_the_fasteners_the_names_and_solids_give(engine):
    # Its docstring said None meant no fasteners.
    found = check(open_screw(), engine=engine)
    assert found.summary == check(open_screw(), Config(), engine=engine).summary
    assert found.summary["fasteners"] == 1
    (result,) = found.results
    assert (result.fastener.name, result.fastener.source) == ("M3x10 SHCS", "name+geometry")
    assert (result.verdict, result.tool) == (Verdict.TURNS, "hex-key-2.5")


def test_a_run_that_checks_nothing_is_detection_turned_off():
    nothing = check(open_screw(), Config.from_dict({"checks": {"detect": False}}))
    assert nothing.summary["fasteners"] == 0
    assert nothing.exit_code == 0


def test_check_reads_no_sidecar_from_the_model_s_folder(tmp_path):
    # A wrenchroom.yaml beside the model is the command line's to find: this one
    # would turn detection off and set the step, and check() is told only the folder.
    (tmp_path / "wrenchroom.yaml").write_text("checks:\n  detect: false\n  step_deg: 5\n")
    report = check(open_screw(), model_dir=tmp_path)
    assert report.summary["fasteners"] == 1
    assert report.step_deg == DEFAULT_STEP_DEG
    read = check(open_screw(), Config.load(tmp_path / "wrenchroom.yaml"), model_dir=tmp_path)
    assert (read.summary["fasteners"], read.step_deg) == (0, 5.0)


def test_the_command_line_does_read_the_sidecar_beside_the_model(tmp_path):
    model = export_slot(tmp_path / "slot.step")
    (tmp_path / "wrenchroom.yaml").write_text("checks:\n  detect: false\n")
    result = CliRunner().invoke(main, ["check", str(model)])
    assert result.exit_code == 0
    assert "0 fasteners" in result.output
