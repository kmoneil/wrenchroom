"""A cross recess's drawn span picks its Phillips number (issue #125).

A cross's span across its wings has been read from the solid since #115, but the
driver came from the thread's size alone: an M4 drawn with a cross for PH1 got a
PH2 driver, which doesn't fit what is drawn. Now the span decides where it sits
in one number's range, as a socket's across flats decides its key, and where it
disagrees with the thread's number the result notes it. A span between two
numbers' ranges says nothing: the thread's number stands.

The ranges are the product standards' m, the recess's diameter at the head's
face, types H and Z, transcribed below from fasten.it's copies (2026-10-08).
"""

import pytest
from build123d import Box, Cylinder, Pos

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.detect.sidecar import sidecar_text
from wrenchroom.fasteners import PHILLIPS_NUMBER, PHILLIPS_SPAN, phillips_by_span
from wrenchroom.report import Verdict

#: (standard, size, recess number, m type H, m type Z), as the standards print them.
STANDARDS_M = [
    ("ISO 7045", "M1.6", 0, 1.7, 1.6),
    ("ISO 7045", "M2", 0, 1.9, 2.1),
    ("ISO 7045", "M2.5", 1, 2.7, 2.6),
    ("ISO 7045", "M3", 1, 3.0, 2.8),
    ("ISO 7045", "M3.5", 2, 3.9, 3.9),
    ("ISO 7045", "M4", 2, 4.4, 4.3),
    ("ISO 7045", "M5", 2, 4.9, 4.7),
    ("ISO 7045", "M6", 3, 6.9, 6.7),
    ("ISO 7045", "M8", 4, 9.0, 8.8),
    ("ISO 7045", "M10", 4, 10.1, 9.9),
    ("ISO 7046 form 1", "M2", 0, 1.9, 1.9),
    ("ISO 7046 form 1", "M2.5", 1, 2.9, 2.8),
    ("ISO 7046 form 1", "M3", 1, 3.2, 3.0),
    ("ISO 7046 form 1", "M3.5", 2, 4.4, 4.1),
    ("ISO 7046 form 1", "M4", 2, 4.6, 4.4),
    ("ISO 7046 form 1", "M5", 2, 5.2, 4.9),
    ("ISO 7046 form 1", "M6", 3, 6.8, 6.6),
    ("ISO 7046 form 1", "M8", 4, 8.9, 8.8),
    ("ISO 7046 form 1", "M10", 4, 10.0, 9.8),
    ("ISO 7046 form 2", "M2", 0, 1.9, 1.9),
    ("ISO 7046 form 2", "M2.5", 1, 2.7, 2.5),
    ("ISO 7046 form 2", "M3", 1, 2.9, 2.8),
    ("ISO 7046 form 2", "M3.5", 2, 4.1, 4.0),
    ("ISO 7046 form 2", "M4", 2, 4.6, 4.4),
    ("ISO 7046 form 2", "M5", 2, 4.8, 4.6),
    ("ISO 7046 form 2", "M6", 3, 6.6, 6.3),
    ("ISO 7046 form 2", "M8", 4, 8.7, 8.5),
    ("ISO 7046 form 2", "M10", 4, 9.6, 9.4),
    ("ISO 7049", "ST2.2", 0, 1.9, 2.0),
    ("ISO 7049", "ST2.9", 1, 3.0, 3.0),
    ("ISO 7049", "ST3.5", 2, 3.9, 4.0),
    ("ISO 7049", "ST4.2", 2, 4.4, 4.4),
    ("ISO 7049", "ST4.8", 2, 4.9, 4.8),
    ("ISO 7049", "ST5.5", 3, 6.4, 6.2),
    ("ISO 7049", "ST6.3", 3, 6.9, 6.8),
    ("ISO 7049", "ST8", 4, 9.0, 8.9),
    ("ISO 7049", "ST9.5", 4, 10.1, 10.1),
    ("ISO 7050", "ST2.2", 0, 1.9, 2.0),
    ("ISO 7050", "ST2.9", 1, 3.2, 3.0),
    ("ISO 7050", "ST3.5", 2, 4.4, 4.1),
    ("ISO 7050", "ST4.2", 2, 4.6, 4.4),
    ("ISO 7050", "ST4.8", 2, 5.2, 4.9),
    ("ISO 7050", "ST5.5", 3, 6.6, 6.3),
    ("ISO 7050", "ST6.3", 3, 6.8, 6.6),
    ("ISO 7050", "ST8", 4, 8.9, 8.8),
    ("ISO 7050", "ST9.5", 4, 10.0, 9.8),
]


# ---------------------------------------------------------------------------
# The ranges.
# ---------------------------------------------------------------------------


def test_the_ranges_are_the_standards_least_and_most():
    assert PHILLIPS_SPAN == {
        0: (1.6, 2.1),
        1: (2.5, 3.2),
        2: (3.9, 5.2),
        3: (6.2, 6.9),
        4: (8.5, 10.1),
    }
    for number, (least, most) in PHILLIPS_SPAN.items():
        ms = [m for _, _, n, h, z in STANDARDS_M if n == number for m in (h, z)]
        assert (min(ms), max(ms)) == (least, most), number


@pytest.mark.parametrize(("standard", "size", "number", "h", "z"), STANDARDS_M)
def test_every_recess_the_standards_give_takes_its_own_number(standard, size, number, h, z):
    assert phillips_by_span(h) == number, (standard, size)
    assert phillips_by_span(z) == number, (standard, size)
    if size in PHILLIPS_NUMBER:  # the thread table agrees with the standards' recesses
        assert PHILLIPS_NUMBER[size] == number, (standard, size)


@pytest.mark.parametrize(
    ("span", "number"),
    [
        (1.5, None),
        (1.6, 0),
        (2.1, 0),
        (2.3, None),
        (2.5, 1),
        (3.2, 1),
        (3.5, None),
        (3.9, 2),
        (5.2, 2),
        (5.7, None),
        (6.2, 3),
        (6.9, 3),
        (7.5, None),
        (8.5, 4),
        (10.1, 4),
        (11.0, None),
    ],
)
def test_a_span_takes_the_number_whose_range_holds_it(span, number):
    assert phillips_by_span(span) == number


# ---------------------------------------------------------------------------
# In the check.
# ---------------------------------------------------------------------------


def pan(d, dk, k, span):
    """A pan head ``dk`` by ``k`` on a shank ``d``, a cross ``span`` across, 0.8 wide."""
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    cross = Pos(0, 0, k - 0.9) * (Box(span, 0.8, 1.8) + Box(0.8, span, 1.8))
    return head - cross + Pos(0, 0, -5) * Cylinder(d / 2, 10)


def checked(name, shape, engine="mesh", rules=None, kit="full"):
    plate = Pos(0, 0, -5) * Box(30, 30, 10) - Cylinder(3, 30)
    config = Config.from_dict({"fasteners": rules} if rules else {})
    assembly = Assembly([Part("plate", plate), Part(name, shape)])
    report = check(assembly, config, engine=engine, kit=kit)
    (result,) = report.results
    return result, report


M4_PH1 = (
    "cross drawn for PH1 (3.00 across its wings), where an M4's standard gives PH2: taken as drawn"
)


@pytest.mark.parametrize(
    ("span", "tool", "notes"), [(4.4, "driver-ph2", ()), (3.0, "driver-ph1", (M4_PH1,))]
)
def test_the_issue_s_m4_takes_the_driver_its_cross_is_drawn_for(engine, span, tool, notes):
    # Both used to take PH2, the M4's by ISO 7045, silently.
    result, _ = checked("M4x10 pan head screw", pan(4, 8, 3.1, span), engine)
    assert (result.verdict, result.tool, result.notes) == (Verdict.TURNS, tool, notes)


@pytest.mark.parametrize(
    ("name", "d", "span", "tool"),
    [
        ("M3x6 pan head screw", 3, 2.74, "driver-ph1"),  # SO-101's ISO 7045 M3s
        ("#1 phillips screw", 1.854, 1.60, "driver-ph0"),  # its #1 tapping screws
        ("#0 phillips screw", 1.524, 1.39, "driver-ph0"),  # its #0s, short of PH0's
        ("M2 phillips screw", 2, 2.40, "driver-ph0"),  # the Legacy's M2s, between two
    ],
)
def test_the_real_models_crosses_take_what_they_took(name, d, span, tool):
    result, _ = checked(name, pan(d, 2 * d, 0.6 * d + 0.6, span))
    assert (result.tool, result.notes) == (tool, ())


@pytest.mark.parametrize(("span", "tool"), [(4.4, "driver-ph2"), (3.0, "driver-ph1")])
def test_a_rule_s_across_flats_is_its_cross_s_span(span, tool):
    rule = {"parts": "screw", "kind": "screw", "head": "phillips", "size": "M4"}
    result, _ = checked("screw", pan(4, 8, 3.1, 4.4), rules=[{**rule, "across_flats": span}])
    assert result.tool == tool
    result, _ = checked("screw", pan(4, 8, 3.1, 3.0), rules=[rule])  # described: no span
    assert result.tool == "driver-ph2"


def test_a_cross_of_no_size_is_driven_by_its_span():
    rule = {"parts": "screw", "kind": "screw", "head": "phillips", "across_flats": 4.4}
    result, _ = checked("screw", pan(4, 8, 3.1, 4.4), rules=[rule])
    assert (result.verdict, result.tool) == (Verdict.TURNS, "driver-ph2")
    result, _ = checked("screw", pan(4, 8, 3.1, 4.4), rules=[{**rule, "across_flats": 2.4}])
    assert result.reason == (
        "a cross 2.40 across its wings is no Phillips number's, and size unknown: "
        "name it in the sidecar"
    )


def test_a_size_no_table_numbers_takes_its_cross_s():
    rule = {"parts": "screw", "kind": "screw", "head": "phillips", "size": "M12"}
    result, _ = checked("screw", pan(12, 20, 6, 9.5), rules=[{**rule, "across_flats": 9.5}])
    assert result.tool == "driver-ph4"
    result, _ = checked("screw", pan(12, 20, 6, 9.5), rules=[{**rule, "across_flats": 7.5}])
    assert result.reason == (
        "a cross 7.50 across its wings is no Phillips number's, and ISO 7045 and ASME "
        "B18.6.3 give no Phillips number for M12"
    )
    result, _ = checked("screw", pan(12, 20, 6, 9.5), rules=[rule])
    assert result.reason == "ISO 7045 and ASME B18.6.3 give no Phillips number for M12"


@pytest.mark.parametrize(("span", "written"), [(3.0, True), (4.4, False)])
def test_detect_writes_a_cross_its_thread_s_table_wouldn_t_give(span, written):
    _, report = checked("M4x10 pan head screw", pan(4, 8, 3.1, span))
    text = sidecar_text(report, "model.step")
    assert (f"across_flats: {span}" in text) is written
    assert "head: phillips" in text


def test_a_cross_between_numbers_is_not_written():
    _, report = checked("M2 phillips screw", pan(2, 4, 1.8, 2.4))
    assert "across_flats" not in sidecar_text(report, "model.step")


def test_the_table_names_an_unsized_cross_or_torx_by_no_across_flats():
    rule = {"parts": "screw", "kind": "screw", "head": "phillips", "across_flats": 4.4}
    _, report = checked("screw", pan(4, 8, 3.1, 4.4), rules=[rule])
    assert any(line.lstrip().startswith("? phillips screw") for line in report.terminal_lines())
