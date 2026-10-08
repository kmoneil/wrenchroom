"""Washers named after their screws, set screws' own keys, and fasteners turned by hand (#96).

- A name is about its own phrase: ``Nylon Washer (Thumbscrew)`` and ``Washer for M3
  screw`` are washers, which aren't checked.
- A set screw (ISO 4026 to 4029, DIN 913 to 916; ``set screw``, ``grub screw``) is
  ``head: set``: no head, a hex socket in one end of its thread, and the key its own
  table gives (M3 1.5, M6 3), not ISO 4762's. A hex socket in a headless solid is a
  set screw whatever the name says, and its socket's end is the end it is turned
  from. It backs out through its own tapped hole.
- A thumb screw, a wing nut, a knurled nut is turned by hand: its tool is ``hand``,
  checked as room for fingers, round its grip or a fingertip on its rim from any one
  side. It needs no head, so no head is guessed for it.
"""

import json
import math

import pytest
import yaml
from build123d import Box, Compound, Cylinder, Pos, RegularPolygon, export_step, extrude
from click.testing import CliRunner

from fastener_models import socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.detect import find, read_name, read_shape
from wrenchroom.detect.names import STANDARDS
from wrenchroom.fasteners import SET_KEY_AF, Fastener, Head, Kind, Size, hex_key_af, no_such_head
from wrenchroom.report import FastenerResult, Report, Verdict
from wrenchroom.tools.fingers import FINGER_MM, FINGER_REACH, HAND
from wrenchroom.tools.kits import KITS

S, N = Kind.SCREW, Kind.NUT


def hexagon(af, h, z0=0.0):
    return Pos(0, 0, z0) * extrude(RegularPolygon(af / math.sqrt(3), 6), h)


def set_screw(d=3.0, length=4.0, key=1.5, depth=1.5, top=0.0):
    """An ISO 4026 set screw, its socket ``depth`` deep in its top end at ``top``."""
    body = Pos(0, 0, top - length / 2) * Cylinder(d / 2, length)
    return body - hexagon(key, depth + 0.01, top - depth)


# ---------------------------------------------------------------------------
# Names.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Nylon Washer (Thumbscrew)",
        "Nylon Washer (Thumbscrew):1",
        "Washer for M3 screw",
        "washer_for_m3_screw",
        "Spacer (M3 bolt)",
        "Plate (for M3 screw)",
        "M3 Washer",
        "Washer (DIN 912 M3 screw)",  # a standard in the aside is the screw's
        "Washer for ISO 4762 M3x8",
    ],
)
def test_a_name_whose_own_noun_is_no_fastener_s_is_none(name):
    assert read_name(name) is None


@pytest.mark.parametrize(
    ("name", "head", "by_hand", "needs_drive"),
    [
        ("Thumb Screw (Nylon Washer)", None, True, False),  # outright, not a candidate
        ("Screw (ISO 7380 M3x8)", Head.BUTTON, False, False),  # the standard still read
        ("M3x16 (Socket Head)", Head.SOCKET, False, True),  # the words in the brackets
        ("Bolt for M8 nut plate", None, False, False),
    ],
)
def test_a_fastener_s_own_phrase_is_read_and_its_aside_kept_where_it_says_more(
    name, head, by_hand, needs_drive
):
    found = read_name(name)
    assert (found.kind, found.head, found.by_hand, found.needs_drive) == (
        S,
        head,
        by_hand,
        needs_drive,
    )


def test_an_instance_marker_in_brackets_is_no_aside():
    assert read_name("M3 nut (1)").kind is N
    assert read_name("M3x6 BHCS v1 (1) (1) (2)").head is Head.BUTTON


@pytest.mark.parametrize(
    "label", sorted(label for label, (_, head, _) in STANDARDS.items() if head is Head.SET)
)
def test_every_set_screw_standard_reads_as_one(label):
    found = read_name(f"{label} M5x8")
    assert (found.kind, found.head, found.not_covered) == (S, Head.SET, None)
    assert found.size.designation == "M5"


def test_the_set_screw_standards_are_iso_4026_to_4029_and_din_913_to_916():
    sets = {label for label, (_, head, _) in STANDARDS.items() if head is Head.SET}
    assert sets == {f"ISO {n}" for n in range(4026, 4030)} | {f"DIN {n}" for n in range(913, 917)}


@pytest.mark.parametrize(
    "name",
    ["set screw M4x6", "grub screw M5", "setscrew_m3", "Socket Set Screw M5x8", "grubscrew"],
)
def test_a_set_or_grub_word_makes_a_set_screw(name):
    found = read_name(name)
    assert (found.kind, found.head, found.by_hand, found.not_covered) == (S, Head.SET, False, None)


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("thumb screw M4", S),
        ("M3x10 Thumb Screw 0", S),
        ("thumbscrew", S),
        ("knurled screw M3", S),
        ("wing nut M6", N),
        ("wingnut", N),
        ("thumbnut", N),
        ("knurled nut M3", N),
    ],
)
def test_a_thumb_wing_or_knurled_word_is_turned_by_hand(name, kind):
    found = read_name(name)
    assert (found.kind, found.by_hand, found.not_covered) == (kind, True, None)


def test_a_knurled_insert_is_set_not_turned():
    found = read_name("knurled insert M3")
    assert (found.kind, found.by_hand) == (Kind.INSERT, False)


# ---------------------------------------------------------------------------
# The key table.
# ---------------------------------------------------------------------------


def test_iso_4026_s_keys_against_the_table_read_on_2026_10_08():
    assert {d: SET_KEY_AF[d] for d in ("M3", "M4", "M5", "M6", "M8", "M10")} == {
        "M3": 1.5,
        "M4": 2.0,
        "M5": 2.5,
        "M6": 3.0,
        "M8": 4.0,
        "M10": 5.0,
    }  # the issue's, and ISO 4026's
    assert (SET_KEY_AF["M1.6"], SET_KEY_AF["M12"], SET_KEY_AF["M24"]) == (0.7, 6.0, 12.0)
    assert "M14" not in SET_KEY_AF


def test_every_set_screw_takes_a_smaller_key_than_its_socket_head():
    for designation, key in SET_KEY_AF.items():
        size = Size.parse(designation)
        socket = hex_key_af(Head.SOCKET, size)
        if socket is not None:
            assert key < socket, designation


def test_a_set_screw_the_standard_lacks_says_so():
    assert no_such_head(Head.SET, Size.parse("M14")) == "ISO 4026 has no M14 set screw"


# ---------------------------------------------------------------------------
# The solid.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("named", [None, Head.SET, Head.SOCKET, Head.BUTTON])
def test_a_hex_socket_in_a_headless_solid_is_a_set_screw(named):
    # The issue's: drawn 2.9 across, its 1.5 key says M3, not M2.5 (ISO 10642's 1.5).
    reading = read_shape(set_screw(d=2.9), S, named)
    assert (reading.head, reading.drive_af, reading.size.designation) == (
        Head.SET,
        pytest.approx(1.5),
        "M3",
    )
    assert reading.size_from_drive
    assert (reading.head_guess, reading.outline_head) == (None, None)


def test_a_cup_point_narrowing_one_end_is_still_headless():
    cup = set_screw(d=6.0, length=8.0, key=3.0) - Pos(0, 0, -8) * Cylinder(1.5, 2)
    tip = Pos(0, 0, -7.75) * Cylinder(2.0, 0.5)
    body = cup - Pos(0, 0, -7.75) * (Cylinder(3.1, 0.5) - Cylinder(2.0, 0.5))
    assert read_shape(body + tip, S).head is Head.SET


def test_a_headed_solid_named_a_set_screw_keeps_its_head():
    reading = read_shape(socket_screw("M5"), S, Head.SET)
    assert reading.head is Head.SOCKET
    (fastener,) = find([Part("set screw M5x8", socket_screw("M5"))]).fasteners
    assert fastener.head is Head.SOCKET
    assert "(the name says set)" in fastener.basis
    assert fastener.confidence == "medium"


def test_a_set_screw_is_detected_with_its_own_key():
    (fastener,) = find([Part("DIN 913 - M3 x 4", set_screw(d=2.9))]).fasteners
    assert (fastener.head, fastener.size.designation) == (Head.SET, "M3")
    assert fastener.basis == "DIN 913, M3 x 4; solid: set, 1.5 across flats, M3 measured"
    assert fastener.confidence == "high"
    assert fastener.notes == ()


# ---------------------------------------------------------------------------
# Set screws in the check.
# ---------------------------------------------------------------------------


def hub(hole_radius=1.23, top=0.0):
    """A block with a vertical tapped hole, drawn at the M3's minor diameter."""
    return Pos(0, 0, top - 10) * Box(30, 30, 20) - Pos(0, 0, top - 10) * Cylinder(hole_radius, 21)


SET_RULE = {"parts": "set", "kind": "screw", "head": "set", "size": "M3", "length": 4}


def checked(parts, rules=(), kit="metric-home", **kwargs):
    config = Config.from_dict({"fasteners": list(rules)}) if rules else None
    assembly = Assembly([Part(name, shape) for name, shape in parts])
    report = check(assembly, config, kit=kit, **kwargs)
    return {r.fastener.name: r for r in report.results}, report


def test_a_set_screw_recessed_in_its_hole_turns_with_its_key_and_backs_out():
    results, _ = checked([("hub", hub()), ("set", set_screw(top=-1.0))], [SET_RULE])
    result = results["set"]
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "hex-key-1.5",
        "driver straight in",
    )
    assert result.seat == pytest.approx((0.0, 0.0, -1.0))  # its socket's end
    assert result.axis == pytest.approx((0.0, 0.0, 1.0))
    # Backing out through a hole drawn at its minor diameter, it meets the thread only.
    assert not result.stuck_on


def test_a_set_screw_drawn_socket_down_is_turned_from_below():
    upside = Pos(0, 0, -6) * set_screw().mirror()
    results, _ = checked([("hub", hub()), ("set", upside)], [SET_RULE])
    result = results["set"]
    assert result.axis == pytest.approx((0.0, 0.0, -1.0))
    assert result.verdict is Verdict.TURNS


def test_a_set_screw_under_a_collar_is_blocked():
    collar = Pos(0, 0, 5) * Box(30, 30, 10)
    results, _ = checked(
        [("hub", hub()), ("set", set_screw(top=-1.0)), ("collar", collar)], [SET_RULE]
    )
    assert (results["set"].verdict, results["set"].blocked_by[0]) == (Verdict.BLOCKED, "collar")


def test_its_way_out_is_still_checked():
    # A lip over the hole, bored 2 across: the 1.5 key (0.84 round) goes in, the
    # screw, backing out at its minor's 1.2, can't come past.
    lip = Pos(0, 0, 0.5) * (Box(30, 30, 1) - Cylinder(1.0, 2))
    results, _ = checked([("hub", hub()), ("set", set_screw(top=-1.0)), ("lip", lip)], [SET_RULE])
    result = results["set"]
    assert (result.verdict, result.tool, result.stuck_on) == (
        Verdict.STUCK,
        "hex-key-1.5",
        ("lip",),
    )


def test_a_set_screw_with_no_socket_drawn_says_so():
    rule = {**SET_RULE}
    results, _ = checked([("hub", hub()), ("set", Pos(0, 0, -3) * Cylinder(1.5, 4))], [rule])
    assert results["set"].reason == (
        "cannot tell which end its socket is in: no socket in the solid"
    )


def test_a_set_screw_socketed_at_both_ends_says_so():
    both = set_screw() - hexagon(1.5, 1.51, -4.0)
    results, _ = checked([("hub", hub()), ("set", both)], [SET_RULE])
    assert results["set"].reason == ("cannot tell which end its socket is in: both ends look alike")


def test_a_set_screw_whose_key_no_table_holds_names_it():
    rule = {"parts": "set", "kind": "screw", "head": "set", "size": "M1.6"}
    small = set_screw(d=1.6, length=3.0, key=0.7, depth=0.7)
    results, _ = checked([("set", small)], [rule], kit="full")
    assert results["set"].reason == (
        "needs hex-key-0.7, which kit full does not hold; no kit has it"
    )


def test_an_m14_set_screw_has_no_standard_key():
    rule = {"parts": "set", "kind": "screw", "head": "set", "size": "M14"}
    results, _ = checked([("set", set_screw(d=14.0, length=10.0, key=6.0))], [rule], kit="full")
    assert results["set"].reason == "ISO 4026 has no M14 set screw"
    # Its socket's size, given, decides: a 6 mm key, which the full kit holds.
    results, _ = checked(
        [("set", set_screw(d=14.0, length=10.0, key=6.0))],
        [{**rule, "across_flats": 6}],
        kit="full",
    )
    assert (results["set"].verdict, results["set"].tool) == (Verdict.TURNS, "hex-key-6")


# ---------------------------------------------------------------------------
# By hand.
# ---------------------------------------------------------------------------


def thumb_screw(head_radius=4.0, head_height=3.0, length=10.0):
    """A knurled-head thumb screw drawn plain: a disc over an M3 shank."""
    head = Pos(0, 0, head_height / 2) * Cylinder(head_radius, head_height)
    return head + Pos(0, 0, -length / 2) * Cylinder(1.5, length)


def plate():
    return Pos(0, 0, -5) * Box(80, 80, 10) - Cylinder(1.6, 30)


THUMB_RULE = {"parts": "thumb", "kind": "screw", "size": "M3", "tool": "hand"}


def test_a_thumb_screw_in_the_open_turns_with_fingers_round_its_head():
    results, report = checked([("plate", plate()), ("thumb", thumb_screw())], [THUMB_RULE])
    result = results["thumb"]
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        HAND,
        "fingers round its head",
    )
    assert report.exit_code == 0


def test_a_thumb_screw_needs_room_for_fingers_round_its_head():
    # A wall a fingertip's thickness away, less a millimetre: the ring meets it.
    gap = 4.0 + 0.3 + FINGER_MM - 1.0
    wall = Pos(gap + 5, 0, 10) * Box(10, 80, 20)
    results, _ = checked(
        [("plate", plate()), ("thumb", thumb_screw()), ("wall", wall)], [THUMB_RULE]
    )
    assert results["thumb"].attempts[0].blockers == ("wall",)
    # ...and a fingertip on its rim from the other side turns it.
    assert (results["thumb"].verdict, results["thumb"].how) == (
        Verdict.TURNS,
        "a fingertip on its rim",
    )


def test_and_room_over_its_end():
    ceiling = Pos(0, 0, 3 + FINGER_REACH - 5 + 5) * Box(80, 80, 10)
    results, _ = checked(
        [("plate", plate()), ("thumb", thumb_screw()), ("ceiling", ceiling)], [THUMB_RULE]
    )
    assert results["thumb"].attempts[0].blockers == ("ceiling",)


def wheel_in_a_window(window=True):
    """A thumb wheel inside a block, its rim showing through a window on +x.

    The wheel (r4, 3 thick) sits in a cavity r5 from z -2 to 2, its shank down
    through the block; a slot 12 wide and 9 high runs out from the cavity on +x.
    """
    block = Box(40, 40, 20) - Pos(0, 0, 0) * Cylinder(5, 4) - Pos(0, 0, -6) * Cylinder(1.6, 9)
    block -= Pos(0, 0, 6) * Cylinder(4.6, 9)  # its way out, up through the block
    if window:
        block -= Pos(12.5, 0, 0) * Box(25, 12, 9)
    wheel = Pos(0, 0, -1.5) * thumb_screw(length=8.0)
    return [("block", block), ("thumb", wheel)]


def test_a_thumb_wheel_in_a_window_turns_with_a_fingertip_on_its_rim():
    results, _ = checked(wheel_in_a_window(), [THUMB_RULE])
    result = results["thumb"]
    assert [a.way for a in result.attempts] == ["fingers round its head", "a fingertip on its rim"]
    assert not result.attempts[0].turns
    assert (result.verdict, result.how) == (Verdict.TURNS, "a fingertip on its rim")


def test_a_thumb_wheel_shut_in_is_blocked_naming_what_shuts_it():
    results, report = checked(wheel_in_a_window(window=False), [THUMB_RULE])
    result = results["thumb"]
    assert (result.verdict, result.tool, result.blocked_by) == (
        Verdict.BLOCKED,
        HAND,
        ("block",),
    )
    assert report.exit_code == 1


def wing_nut():
    """An M6 wing nut: a hub bored 6, two wings 20 across."""
    hub_ = Cylinder(5, 6) + Pos(0, 0, 0.5) * Box(22, 2.5, 5)
    return Pos(0, 0, 3) * (hub_ - Cylinder(3, 7))


def test_a_wing_nut_turns_with_fingers_round_it_its_bolt_left_alone():
    bolt = Pos(0, 0, -5) * (Cylinder(3, 30) + Pos(0, 0, -16) * hexagon(10, 4, -2))
    parts = [("plate", Pos(0, 0, -5) * Box(80, 80, 10) - Cylinder(3.2, 30)), ("bolt", bolt)]
    parts.append(("wing", wing_nut()))
    rules = [
        {"parts": "wing", "kind": "nut", "size": "M6", "tool": "hand"},
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M6"},
    ]
    results, _ = checked(parts, rules)
    result = results["wing"]
    assert (result.verdict, result.tool, result.how) == (Verdict.TURNS, HAND, "fingers round it")


def test_with_hand_room_the_hand_over_the_fingers_must_be_clear_too():
    ceiling = Pos(0, 0, 60) * Box(400, 400, 10)
    parts = [("plate", plate()), ("thumb", thumb_screw()), ("ceiling", ceiling)]
    results, _ = checked(parts, [THUMB_RULE])
    assert results["thumb"].verdict is Verdict.TURNS  # fingers alone fit under it
    results, _ = checked(parts, [THUMB_RULE], hand_room=True)
    result = results["thumb"]
    assert result.verdict is Verdict.BLOCKED
    assert result.reason.startswith("no room for a hand: the hand hits ")
    assert "ceiling" in result.reason


def test_a_thumb_screw_drawn_as_two_solids_finds_its_head_end():
    # The issue's Stealthburner wheel: a 12 mm disc, the larger solid, and its shank
    # apart. The disc alone has no head end; its shank, a piece of it, says which.
    disc = Pos(0, 0, 1.5) * Cylinder(6, 3)
    shank = Pos(0, 0, -10) * Cylinder(1.5, 20)
    parts = [
        Part("plate", Pos(0, 0, -5) * Box(80, 80, 10) - Cylinder(1.6, 30)),
        Part("M3 Thumb Screw", disc),
        Part("M3 Thumb Screw#2", shank, piece_of="M3 Thumb Screw"),
    ]
    report = check(Assembly(parts), kit="metric-home")
    (result,) = report.results
    assert (result.verdict, result.tool, result.axis) == (
        Verdict.TURNS,
        HAND,
        pytest.approx((0.0, 0.0, 1.0)),
    )


def test_a_by_hand_fastener_is_detected_with_no_head_and_no_guess():
    (fastener,) = find([Part("M3x10 Thumb Screw", thumb_screw(head_radius=4.0))]).fasteners
    assert (fastener.tool, fastener.head, fastener.notes) == (HAND, None, ())
    assert fastener.confidence == "high"
    assert fastener.not_covered is None


def test_a_wing_nut_needs_no_hex():
    (fastener,) = find([Part("wing nut M6", wing_nut())]).fasteners
    assert (fastener.kind, fastener.tool, fastener.not_covered) == (N, HAND, None)


# ---------------------------------------------------------------------------
# The issue's repro, in every format, and detect.
# ---------------------------------------------------------------------------


def repro():
    parts = []
    for i, name in enumerate(("Nylon Washer (Thumbscrew)", "Washer for M3 screw", "M3 Washer")):
        at = Pos(100 * i, 0, 0)
        board = Pos(0, 0, -5) * Box(30, 30, 10) - Cylinder(1.5, 30)
        washer = Pos(0, 0, 0.5) * (Cylinder(4, 1) - Cylinder(1.6, 1))
        thumb = Pos(0, 0, 2.5) * Cylinder(4, 3) + Pos(0, 0, -4) * Cylinder(1.5, 10)
        parts += [
            Part(f"plate {i}", at * board),
            Part(name, at * washer),
            Part(f"M3x10 Thumb Screw {i}", at * thumb),
        ]
    block = Pos(0, 0, -5) * Box(20, 20, 10) - Pos(0, 0, -2) * Cylinder(1.45, 4)
    screw = Pos(0, 0, -2) * Cylinder(1.45, 4) - hexagon(1.5, 1.5, -1.5)
    at = Pos(300, 0, 0)
    parts += [Part("set block", at * block), Part("DIN 913 - M3 x 4", at * screw)]
    return Assembly(parts)


@pytest.fixture(scope="module")
def report():
    return check(repro(), kit="metric-home")


def test_the_issue_s_repro_passes_and_no_washer_is_a_fastener(report):
    names = {r.fastener.name: (r.verdict, r.tool) for r in report.results}
    assert names == {
        "M3x10 Thumb Screw 0": (Verdict.TURNS, HAND),
        "M3x10 Thumb Screw 1": (Verdict.TURNS, HAND),
        "M3x10 Thumb Screw 2": (Verdict.TURNS, HAND),
        "DIN 913 - M3 x 4": (Verdict.TURNS, "hex-key-1.5"),
    }
    assert report.exit_code == 0
    assert report.passed_over == ()


def test_its_terminal_lines_say_hand_and_set_and_no_head_guess(report):
    lines = report.terminal_lines()
    assert lines[1:3] == [
        "  M3 screw                 hand           x3    all pass (fingers round its head)",
        "  M3 set screw             hex-key-1.5    x1    all pass (driver straight in)",
    ]
    assert not any("its head is a guess" in line for line in lines)


def test_its_json_names_the_tool_hand_and_the_head_set(report):
    by_name = {f["name"]: f for f in json.loads(report.json_text())["fasteners"]}
    assert (by_name["M3x10 Thumb Screw 0"]["tool"], by_name["M3x10 Thumb Screw 0"]["head"]) == (
        "hand",
        None,
    )
    assert by_name["DIN 913 - M3 x 4"]["head"] == "set"


def _export(tmp_path, assembly):
    shapes = []
    for part in assembly:
        part.shape.label = part.name
        shapes.append(part.shape)
    path = tmp_path / "model.step"
    export_step(Compound(children=shapes), str(path))
    return path


def test_detect_writes_tool_hand_and_head_set_and_they_load_back(tmp_path):
    path = _export(tmp_path, repro())
    result = CliRunner().invoke(main, ["detect", str(path)])
    assert result.exit_code == 0, result.output
    rules = {rule["parts"]: rule for rule in yaml.safe_load(result.stdout)["fasteners"]}
    assert rules["M3x10 Thumb Screw 0"]["tool"] == "hand"
    assert "head" not in rules["M3x10 Thumb Screw 0"]
    assert rules["DIN 913 - M3 x 4"]["head"] == "set"
    config = Config.from_dict(yaml.safe_load(result.stdout))
    kept = check(Assembly.from_step(path), config, model_dir=tmp_path)
    assert kept.exit_code == 0
    assert {r.fastener.source for r in kept.results} == {"sidecar"}


def test_a_group_of_ways_as_long_reads_the_same_from_every_run():
    # "fingers round its head" and "a fingertip on its rim" are as long: a group's
    # way is the longest, and of two as long the first by name, whatever the set's
    # order, which differs from one process to the next.
    def turned(name, how):
        fastener = Fastener(name, Kind.SCREW, size=Size.parse("M3"), tool=HAND)
        return FastenerResult(fastener, Verdict.TURNS, tool=HAND, how=how)

    ways = ("fingers round its head", "a fingertip on its rim")
    assert len(ways[0]) == len(ways[1])
    for order in (ways, ways[::-1]):
        results = tuple(turned(f"thumb {i}", how) for i, how in enumerate(order))
        report = Report(model="m", kit="full", results=results)
        assert report.terminal_lines()[1].endswith("all pass (fingers round its head)")


@pytest.mark.parametrize(
    ("wall_at", "pinched"),
    [(15.3, False), (16.8, True)],  # inside the ring's 16.3, and past it
)
def test_the_fingers_round_a_head_are_a_fingertip_12_thick(wall_at, pinched):
    # In millimetres, not the module's own figures: an 8 across head, the ring from
    # 4.3 (4 and the contact offset) out by 12, to 16.3.
    wall = Pos(wall_at + 5, 0, 10) * Box(10, 80, 20)
    results, _ = checked(
        [("plate", plate()), ("thumb", thumb_screw()), ("wall", wall)], [THUMB_RULE]
    )
    assert results["thumb"].attempts[0].turns is pinched


@pytest.mark.parametrize(
    ("ceiling_at", "pinched"),
    [(24.8, False), (25.8, True)],  # over the head's top, 3 up: inside 25.3, and past it
)
def test_the_fingers_reach_25_over_the_head(ceiling_at, pinched):
    ceiling = Pos(0, 0, 3 + ceiling_at + 5) * Box(80, 80, 10)
    results, _ = checked(
        [("plate", plate()), ("thumb", thumb_screw()), ("ceiling", ceiling)], [THUMB_RULE]
    )
    assert results["thumb"].attempts[0].turns is pinched


def test_every_kit_has_hands():
    assert all(kit.holds(HAND) for kit in KITS.values())
    for kit in KITS:
        results, _ = checked([("plate", plate()), ("thumb", thumb_screw())], [THUMB_RULE], kit=kit)
        assert (results["thumb"].verdict, results["thumb"].tool) == (Verdict.TURNS, HAND), kit
