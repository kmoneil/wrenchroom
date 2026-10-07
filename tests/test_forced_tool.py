"""A rule's tool: must fit its fastener: the kind its drive takes, at a size it takes (#72).

A rule's ``tool:`` was used as written. ``spanner-10`` on an M8 nut (13 across flats)
passed with a ring that can't go on, and ``hex-key-5`` on a nut was swept into its
bore and came out blocked by the bolt. Now a forced tool must be of the kind the
drive takes (a spanner, socket or nut driver on a hex; a hex key in a hex socket; a
Torx key in a Torx recess; the right driver), at a size the fastener takes: the one
the unforced check would choose, or the hex the solid shows. One that doesn't is not
covered, saying so; ``across_flats:`` is how a rule says the model's hex is meant.
"""

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism, pan_phillips
from fixture_models import nut_with_bolt_through, screw_facing_wall
from wrenchroom import checker
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict

NUT = {"parts": "nut", "kind": "nut", "size": "M8", "axis": [0, 0, 1]}
M6_SOCKET = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}


def m8_pair():
    """The issue's case: an M8 nut (13 across flats) on an M8 bolt, through a plate."""
    return nut_with_bolt_through(af=13.0, nut_h=6.8, bolt_d=8.0)


def run(assembly, rule, kit="full", **extra):
    config = Config.from_dict({"fasteners": [rule], "checks": {"detect": False}, **extra})
    return check(assembly, config, kit=kit)


def result_of(report, name):
    (result,) = [r for r in report.results if r.fastener.name == name]
    return result


def nut_reason(tool, kit="full", **rule):
    report = run(m8_pair(), {**NUT, "tool": tool, **rule}, kit=kit)
    return result_of(report, "nut")


# ---------------------------------------------------------------------------
# The wrong size.
# ---------------------------------------------------------------------------


def test_a_spanner_of_the_wrong_size_is_not_covered_saying_so():
    report = run(m8_pair(), {**NUT, "tool": "spanner-10"})
    result = result_of(report, "nut")
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == (
        "its tool: spanner-10 is 10 across flats, but the nut (M8) takes 13; "
        "give its rule across_flats: 10 if its hex really is 10"
    )
    assert result.attempts == ()  # nothing was swept
    assert report.exit_code == 2
    (fail,) = [line for line in report.terminal_lines() if line.startswith("FAIL nut ")]
    assert fail.endswith(result.reason)


@pytest.mark.parametrize("tool", ["spanner-13", "socket-13", "nut-driver-13"])
def test_each_tool_on_the_flats_at_the_right_size_is_used(tool):
    result = nut_reason(tool)
    assert (result.verdict, result.tool, result.reason) == (Verdict.TURNS, tool, None)


def test_an_inch_spanner_near_the_size_is_still_the_wrong_one():
    # 1/2 in is 12.7: near 13, and still not the nut's spanner.
    assert nut_reason("spanner-1/2in").reason == (
        "its tool: spanner-1/2in is 1/2in across flats, but the nut (M8) takes 13; "
        "give its rule across_flats: 1/2in if its hex really is 1/2in"
    )


def test_a_wrong_size_is_said_before_the_kit_is_asked():
    # metric-home has no 24 mm spanner, but the misfit is the first thing wrong.
    assert nut_reason("spanner-24", kit="metric-home").reason.startswith(
        "its tool: spanner-24 is 24 across flats, but the nut (M8) takes 13"
    )


def test_across_flats_says_the_model_s_hex_is_meant():
    # The rule says the hex is 10: a 10 mm spanner fits what the rule says, and is
    # swept (the model's 13 mm hex then decides what happens to it).
    result = nut_reason("spanner-10", across_flats=10)
    assert not (result.reason or "").startswith("its tool:")
    assert result.attempts


def drawn_nut(af):
    """A nut drawn as a hex of ``af`` across flats, bored for M10, on a plate."""
    plate = Part("plate", Pos(0, 0, -5) * Box(200, 200, 10))
    return Assembly([Part("nut", hex_prism(af, 8.0) - Cylinder(4.5, 40)), plate])


def test_a_tool_that_fits_the_hex_the_solid_shows_is_used():
    # Named M10 (16 across flats by ISO 4032), drawn 15: a 15 mm tool fits the
    # solid, as the gland and custom-tool tests have it; a 14 fits neither.
    rule = {"parts": "nut", "kind": "nut", "size": "M10", "axis": [0, 0, 1]}
    fits = result_of(run(drawn_nut(15.0), {**rule, "tool": "spanner-15"}), "nut")
    assert not (fits.reason or "").startswith("its tool:")
    wrong = result_of(run(drawn_nut(15.0), {**rule, "tool": "spanner-14"}), "nut")
    assert wrong.reason == (
        "its tool: spanner-14 is 14 across flats, but the nut (M10) takes 16, its hex "
        "drawn 15; give its rule across_flats: 14 if its hex really is 14"
    )


def test_a_key_of_the_wrong_size_is_not_covered():
    (result,) = run(screw_facing_wall(50), {**M6_SOCKET, "tool": "hex-key-6"}).results
    assert result.reason == (
        "its tool: hex-key-6 is 6 across flats, but the socket head (M6) takes 5; "
        "give its rule across_flats: 6 if its hex really is 6"
    )


def test_a_torx_key_of_the_wrong_size_is_not_covered():
    rule = {**M6_SOCKET, "head": "torx", "tool": "torx-key-T25"}
    (result,) = run(screw_facing_wall(50), rule).results
    assert result.reason == "its tool: torx-key-T25 is T25, but the Torx head (M6) takes T30"


def phillips():
    plate = Part("plate", Pos(0, 0, -5) * Box(200, 200, 10))
    return Assembly([Part("screw", pan_phillips()), plate])


PHILLIPS = {"parts": "screw", "kind": "screw", "head": "phillips", "size": "M4"}


def test_a_phillips_driver_of_the_wrong_number_is_not_covered():
    result = result_of(run(phillips(), {**PHILLIPS, "tool": "driver-ph1"}), "screw")
    assert result.reason == "its tool: driver-ph1 is PH1, but the Phillips head (M4) takes PH2"
    right = result_of(run(phillips(), {**PHILLIPS, "tool": "driver-ph2"}), "screw")
    assert (right.verdict, right.tool) == (Verdict.TURNS, "driver-ph2")


# ---------------------------------------------------------------------------
# The wrong kind.
# ---------------------------------------------------------------------------


def test_a_key_on_a_nut_is_not_swept_into_its_bore():
    result = nut_reason("hex-key-5")
    assert (result.verdict, result.attempts) == (Verdict.NOT_COVERED, ())
    assert result.reason == "its tool: hex-key-5 is a hex key, which doesn't fit the nut (M8)"


@pytest.mark.parametrize(
    ("tool", "called"),
    [
        ("spanner-10", "a spanner"),
        ("socket-10", "a socket"),
        ("nut-driver-10", "a nut driver"),
        ("torx-key-T30", "a Torx key"),
        ("driver-ph2", "a Phillips driver"),
        ("driver-slotted", "a slotted driver"),
    ],
)
def test_nothing_but_a_hex_key_goes_in_a_socket_head(tool, called):
    (result,) = run(screw_facing_wall(50), {**M6_SOCKET, "tool": tool}).results
    assert result.reason == f"its tool: {tool} is {called}, which doesn't fit the socket head (M6)"


@pytest.mark.parametrize(
    ("head", "called"),
    [
        ("button", "button head"),
        ("flat", "countersunk head"),
        ("shoulder", "shoulder screw's head"),
    ],
)
def test_the_other_keyed_heads_take_a_key_too(head, called):
    rule = {**M6_SOCKET, "head": head, "tool": "spanner-10"}
    (result,) = run(screw_facing_wall(50), rule).results
    assert (
        result.reason == f"its tool: spanner-10 is a spanner, which doesn't fit the {called} (M6)"
    )


def test_a_slotted_driver_doesn_t_fit_a_phillips_head():
    result = result_of(run(phillips(), {**PHILLIPS, "tool": "driver-slotted"}), "screw")
    assert result.reason == (
        "its tool: driver-slotted is a slotted driver, which doesn't fit the Phillips head (M4)"
    )


def test_a_hex_key_doesn_t_fit_a_torx_head():
    rule = {**M6_SOCKET, "head": "torx", "tool": "hex-key-5"}
    (result,) = run(screw_facing_wall(50), rule).results
    assert result.reason == "its tool: hex-key-5 is a hex key, which doesn't fit the Torx head (M6)"


# ---------------------------------------------------------------------------
# The sidecar's own tools, and what isn't checked.
# ---------------------------------------------------------------------------


TOOLS = [
    {"name": "shop-spanner-10", "type": "spanner", "across_flats": 10, "length": 150},
    {"name": "shop-spanner-13", "type": "spanner", "across_flats": 13, "length": 150},
    {"name": "long-key-5", "type": "hex-key", "across_flats": 5, "long": 150, "short": 30},
]


def test_a_sidecar_s_own_tool_is_held_to_the_same():
    def nut_with(tool):
        report = run(m8_pair(), {**NUT, "tool": tool}, tools=TOOLS)
        return result_of(report, "nut")

    assert nut_with("shop-spanner-10").reason.startswith(
        "its tool: shop-spanner-10 is 10 across flats, but the nut (M8) takes 13"
    )
    assert nut_with("long-key-5").reason == (
        "its tool: long-key-5 is a hex key, which doesn't fit the nut (M8)"
    )
    fits = nut_with("shop-spanner-13")
    assert (fits.verdict, fits.tool) == (Verdict.TURNS, "shop-spanner-13")


def test_a_tool_the_tables_don_t_hold_still_says_so_itself():
    assert nut_reason("spanner-99").reason == (
        "needs spanner-99, which kit full does not hold; no kit has it"
    )


def test_with_no_head_known_the_forced_tool_says_what_drives_it():
    # A rule with no head: nothing to hold the key to, so it is swept as before.
    rule = {"parts": "bolt", "kind": "screw", "size": "M6", "tool": "hex-key-5"}
    (result,) = run(screw_facing_wall(50), rule).results
    assert (result.verdict, result.tool) == (Verdict.TURNS, "hex-key-5")


def test_the_solid_is_read_again_only_where_a_rule_forces_a_tool(monkeypatch):
    # The extra read (issue #72) is for forced tools alone: a check of a model of
    # described fasteners must not pay it for every one.
    reads = []
    real = checker.read_shape

    def counted(*args, **kwargs):
        reads.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(checker, "read_shape", counted)
    run(m8_pair(), NUT)
    assert reads == []
    run(m8_pair(), {**NUT, "tool": "spanner-13"})
    assert len(reads) == 1
    run(m8_pair(), {**NUT, "tool": "spanner-13", "across_flats": 13})
    assert len(reads) == 1  # across_flats: says the size; nothing to read
