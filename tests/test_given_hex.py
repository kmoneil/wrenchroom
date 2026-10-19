"""A rule's across_flats: for a nut is wider than its thread and its bore (issue #244).

A given hex was taken as written, whatever it was. 1.3 written for 13 on an M8 nut
put the hex's corners inside the bolt through it, and the bolt then read as the
trap holding the nut (issue #93): held, a pass. A nut's bore is its thread, so a hex
no wider than the rule's size, or than its bore as drawn where the rule gives no
size, is a slip, and the nut is not covered, saying so. A hex head is left as given.
"""

import pytest
from build123d import Box, Cylinder, Pos

from fixture_models import hex_bolt, hex_nut_shape, nut_with_bolt_through
from wrenchroom import checker
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.fasteners import Fastener, Kind, Size
from wrenchroom.report import Verdict

IN = 25.4
NUT = {"parts": "nut", "kind": "nut", "axis": [0, 0, 1]}


def m8_pair():
    """An M8 nut (13 across flats, bored 8) on an M8 bolt, through a plate."""
    return nut_with_bolt_through(af=13.0, nut_h=6.8, bolt_d=8.0)


def on_a_stud(d=8.0, af=13.0, bore=None):
    """A nut on a plain stud no rule names: no partner, as a stud in a boss is."""
    plate = Pos(0, 0, -5) * Box(200, 200, 10) - Cylinder(d / 2 + 0.4, 40)
    nut = hex_nut_shape(bore or d, af, 0.8 * d)
    stud = Pos(0, 0, 2.5) * Cylinder(d / 2, 25)
    return Assembly([Part("plate", plate), Part("stud", stud), Part("nut", nut)])


def report_of(assembly, rule, engine="mesh"):
    config = Config.from_dict({"fasteners": [rule], "checks": {"detect": False}})
    return check(assembly, config, kit="full", engine=engine)


def nut_of(report):
    (result,) = [r for r in report.results if r.fastener.name == "nut"]
    return result


def thread(given, size="M8", across="8.00"):
    return (
        f"its rule's across_flats: {given} is no hex on its {size} thread, {across} across: "
        "a nut's hex is wider than its thread"
    )


def bore(given, across="8.00"):
    return (
        f"its rule's across_flats: {given} is no hex on its bore as drawn, {across} across: "
        "a nut's hex is wider than its bore"
    )


@pytest.mark.parametrize("given", [1.3, 5, 8])
def test_a_hex_no_wider_than_the_nut_s_thread_is_not_covered(given, engine):
    # 1.3 and 5 came out held by a trap in the bolt; 8 turned with spanner-8.
    report = report_of(m8_pair(), {**NUT, "size": "M8", "across_flats": given}, engine)
    result = nut_of(report)
    assert (result.verdict, result.reason, result.attempts) == (
        Verdict.NOT_COVERED,
        thread(given),
        (),
    )
    assert (result.how, result.tool) == (None, None)  # held by nothing
    assert report.exit_code == 2
    (fail,) = [line for line in report.terminal_lines() if line.startswith("FAIL nut ")]
    assert fail.endswith(result.reason)


@pytest.mark.parametrize("given", [1.3, 5, 8])
def test_with_no_size_the_hex_is_held_to_the_bore_as_drawn(given):
    result = nut_of(report_of(m8_pair(), {**NUT, "across_flats": given}))
    assert (result.verdict, result.reason) == (Verdict.NOT_COVERED, bore(given))


@pytest.mark.parametrize(("size", "rule"), [("M8", {"size": "M8"}), ("none", {})])
def test_a_nut_on_a_stud_no_rule_names_is_not_held_by_the_stud(size, rule):
    # With no partner, the stud was the trap.
    result = nut_of(report_of(on_a_stud(), {**NUT, **rule, "across_flats": 1.3}))
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == (thread(1.3) if size == "M8" else bore(1.3))


def test_the_thread_holds_a_nut_bored_at_its_minor():
    # Bored at M8's minor, 6.65: 7 is past the bore but on the thread.
    result = nut_of(report_of(on_a_stud(bore=6.65), {**NUT, "size": "M8", "across_flats": 7}))
    assert result.reason == thread(7)


def test_the_bore_holds_a_nut_drawn_bored_past_its_thread():
    # Drawn bored 10 on an M8, as a clearance: 9 is past the thread but in the bore.
    result = nut_of(report_of(on_a_stud(bore=10.0), {**NUT, "size": "M8", "across_flats": 9}))
    assert result.reason == bore(9, "10.00")


def test_an_inch_nut_s_hex_its_thread_s_size_is_not_covered():
    # A 5/16 nut is 1/2 in across flats; given 5/16in, it is its thread's own width.
    pair = nut_with_bolt_through(af=0.5 * IN, nut_h=0.27 * IN, bolt_d=5 / 16 * IN)
    result = nut_of(report_of(pair, {**NUT, "size": "5/16", "across_flats": "5/16in"}))
    assert result.reason == thread(7.9375, "5/16", "7.94")


def test_a_hex_wider_than_the_thread_turns_as_before():
    result = nut_of(report_of(m8_pair(), {**NUT, "size": "M8", "across_flats": 13}))
    assert (result.verdict, result.tool) == (Verdict.TURNS, "spanner-13")


def test_a_forced_tool_of_the_size_given_is_refused_too():
    # A tool and its size given together are taken as written (issue #237): not
    # when the size is no hex on the nut.
    rule = {**NUT, "size": "M8", "tool": "spanner-5", "across_flats": 5}
    result = nut_of(report_of(m8_pair(), rule))
    assert (result.verdict, result.reason) == (Verdict.NOT_COVERED, thread(5))


def hex_bolt_on_plate():
    plate = Pos(0, 0, -5) * Box(200, 200, 10) - Cylinder(4.4, 40)
    return Assembly([Part("bolt", hex_bolt(8.0, 20.0, 13.0, 5.3)), Part("plate", plate)])


def test_a_hex_head_is_left_as_given():
    # A hex on a screw's end can be under its thread (an adjuster's): its rule's
    # across_flats: is taken as written, as before.
    head = {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"}
    (small,) = report_of(hex_bolt_on_plate(), {**head, "across_flats": 5}).results
    assert (small.verdict, small.tool) == (Verdict.TURNS, "spanner-5")
    (slip,) = report_of(hex_bolt_on_plate(), {**head, "across_flats": 1.3}).results
    assert slip.reason.startswith("1.30 mm across flats is no tool's size")


@pytest.mark.parametrize("source", ["name", "name+geometry"])
def test_a_hex_detection_measured_is_not_held_to_it(source):
    # Detection reads the hex round the bore it measures: only a rule's is a slip.
    m8 = Size.parse("M8")
    found = Fastener(name="nut", kind=Kind.NUT, size=m8, drive_af=5.0, source=source)
    checker._round_its_thread(found, 4.0)  # noqa: SLF001
    described = Fastener(name="nut", kind=Kind.NUT, size=m8, drive_af=5.0)
    with pytest.raises(checker.NotCovered):
        checker._round_its_thread(described, 4.0)  # noqa: SLF001


def test_a_screw_s_drive_is_not_held_to_it():
    # A socket head's key is under its thread by design.
    m6 = Size.parse("M6")
    screw = Fastener(name="bolt", kind=Kind.SCREW, size=m6, drive_af=5.0)
    checker._round_its_thread(screw, 0.0)  # noqa: SLF001
