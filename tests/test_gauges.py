"""The gauges the table skipped: #5, and a tapping screw's #7 and #14 (issue #165).

The gauge table held #0 to #4, #6, #8, #10 and #12. A screw named by any other
number was not covered, and the run exited 2: "#5 is outside the sizes the tables
hold (#0 to 3/4)", though a #5 sits between a #4 and a #6. A #5 is a machine screw
size, 5-40 and 5-44; a #7 and a #14 are tapping and wood screws' alone.

Now the three are sizes a name gives. No shank or hex is taken for one: a #7 and a
#14 are no machine thread's, and a #5, 3.175 across, sits where an M3 drawn a
little full does. Their rows, as the makers' sheets and fasten.it's ASME tables
give them (read 2026-10-11):

- #5, ASME B18.3: a socket head's key 3/32, a button head's and a flat countersunk
  head's 5/64, a set screw's 1/16. ASME B18.6.3: a machine screw nut 5/16 across
  flats, a pan or flat head's cross a No. 2. ASME B1.1: 40 threads to the inch
  coarse, so its thread's root is 3.175 - 1.2269 x 0.635 = 2.396 mm.
- #7 and #14, ASME B18.6.4: a #7's thread 0.158 in across at most and 0.108 at its
  core, a #14's 0.254 and 0.178; a #7's cross a No. 2, a #14's a No. 3.
"""

import math

import pytest
from build123d import Box, Cylinder, Pos, RegularPolygon, extrude

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.detect import read_name
from wrenchroom.detect.geometry import read_shape
from wrenchroom.fasteners import (
    BUTTON_KEY_AF,
    COARSE_PITCH_MM,
    FLAT_KEY_AF,
    HEX_AF,
    IMPERIAL_SIZES,
    NAMED_SIZES,
    PHILLIPS_NUMBER,
    SET_KEY_AF,
    SOCKET_KEY_AF,
    Kind,
    Size,
    thread_minor_mm,
)
from wrenchroom.report import Verdict

IN = 25.4


def test_the_three_are_sizes_a_name_gives():
    assert {
        "#5": pytest.approx(0.125 * IN),
        "#7": pytest.approx(0.158 * IN, abs=0.001),
        "#14": pytest.approx(0.254 * IN, abs=0.001),
    } == NAMED_SIZES
    assert not set(NAMED_SIZES) & set(IMPERIAL_SIZES)
    for written, designation in [("#5", "#5"), ("#5-40", "#5"), ("#5-44", "#5"), ("#14", "#14")]:
        assert Size.parse(written).designation == designation
    assert (Size.parse("#7").family, Size.parse("#7").is_tapping, Size.parse("#7").said) == (
        "inch",
        False,
        "a #7",
    )


@pytest.mark.parametrize("written", ["#9", "#11", "#13", "#16", "#20"])
def test_other_numbers_are_still_none(written):
    with pytest.raises(ValueError, match="unknown fastener size"):
        Size.parse(written)


def test_a_number_5_s_rows_are_asme_s():
    inch = {name: table["#5"] / IN for name, table in KEYS.items()}
    assert inch == pytest.approx(
        {"socket": 3 / 32, "button": 5 / 64, "flat": 5 / 64, "set": 1 / 16}
    )
    assert HEX_AF["#5"] == pytest.approx(5 / 16 * IN)
    assert PHILLIPS_NUMBER["#5"] == 2
    assert COARSE_PITCH_MM["#5"] == pytest.approx(IN / 40)
    assert thread_minor_mm(Size.parse("#5")) == pytest.approx(2.396, abs=0.001)


KEYS = {"socket": SOCKET_KEY_AF, "button": BUTTON_KEY_AF, "flat": FLAT_KEY_AF, "set": SET_KEY_AF}


def test_a_number_5_s_rows_sit_between_its_neighbours():
    # Each no less than a #4's and no more than a #6's, as a thread between them.
    for table in (*KEYS.values(), HEX_AF, PHILLIPS_NUMBER):
        assert table["#4"] <= table["#5"] <= table["#6"]
    assert thread_minor_mm(Size.parse("#4")) < thread_minor_mm(Size.parse("#5"))
    assert thread_minor_mm(Size.parse("#5")) < thread_minor_mm(Size.parse("#6"))


def test_a_7_and_a_14_are_a_tapping_screw_s_alone():
    assert (PHILLIPS_NUMBER["#7"], PHILLIPS_NUMBER["#14"]) == (2, 3)
    assert thread_minor_mm(Size.parse("#7")) == pytest.approx(0.108 * IN)
    assert thread_minor_mm(Size.parse("#14")) == pytest.approx(0.178 * IN)
    # No socket, button, flat or set screw is one, and no nut.
    for table in (*KEYS.values(), HEX_AF, COARSE_PITCH_MM):
        assert not {"#7", "#14"} & set(table)


# ---------------------------------------------------------------------------
# In a name.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("#5-40 x 1/2 pan head phillips machine screw", "#5"),
        ("SHCS #5-40 x 1/4", "#5"),
        ("#5-44 x 3/8 socket head cap screw", "#5"),
        ("Machine Screw ANSI B18.6.3 5-40 x 0.25", "#5"),  # bare, beside its standard
        ("#7 x 1/2 pan head phillips tapping screw", "#7"),
        ("Tapping Screw ANSI B18.6.4 7-19 x 0.5", "#7"),  # type AB's threads
        ("Tapping Screw ANSI B18.6.4 7-16 x 0.5", "#7"),  # type A's
        ("#14 x 1 pan head phillips tapping screw", "#14"),
        ("Tapping Screw ANSI B18.6.4 14-10 x 1", "#14"),
        ("#14 x 1-1/2 flat head wood screw", "#14"),
    ],
)
def test_a_name_gives_each(name, size):
    hint = read_name(name)
    assert (hint.size.designation, hint.not_covered) == (size, None)


@pytest.mark.parametrize(
    "name",
    [
        "Machine Screw ANSI B18.6.3 5-41 x 0.25",  # no #5 thread
        "Tapping Screw ANSI B18.6.4 7-40 x 0.5",  # nor a #7's
        "Tapping Screw ANSI B18.6.4 14-20 x 1",
    ],
)
def test_a_bare_pair_that_is_no_thread_of_theirs_is_no_size(name):
    assert read_name(name).size is None


def test_a_number_none_of_them_is_still_outside_the_tables():
    hint = read_name("#9 x 1 flat head wood screw")
    assert hint.not_covered == "#9 is outside the sizes the tables hold (#0 to 3/4)"


# ---------------------------------------------------------------------------
# In a check.
# ---------------------------------------------------------------------------


def pan(span, shank, dk, k):
    """A pan head ``dk`` by ``k`` on a shank 10 long, a cross ``span`` across its wings."""
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    head -= Pos(0, 0, k - 0.5) * (Box(span, 0.4, 1.01) + Box(0.4, span, 1.01))
    return head + Pos(0, 0, -5) * Cylinder(shank / 2, 10)


def hexagon(af, height):
    return extrude(RegularPolygon(af / math.sqrt(3), 6), height)


def socket_5(key):
    """ASME B18.3's #5 socket head, 0.205 by 0.125, on a 0.125 shank, its socket ``key`` in."""
    head = Pos(0, 0, 0.125 * IN / 2) * Cylinder(0.205 * IN / 2, 0.125 * IN)
    socket = Pos(0, 0, 0.125 * IN - 1.6) * hexagon(key * IN, 1.61)
    return head - socket + Pos(0, 0, -5) * Cylinder(0.125 * IN / 2, 10)


def run(cases, **kwargs):
    """Each (name, shape, hole) on a plate of its own, 100 apart, with no sidecar."""
    parts = []
    for index, (name, shape, hole) in enumerate(cases):
        at = Pos(index * 100, 0, 0)
        plate = at * (Pos(0, 0, -5) * Box(30, 30, 10) - Cylinder(hole / 2, 30))
        parts += [Part(f"plate {index}", plate), Part(name, at * shape)]
    report = check(Assembly(parts), kit="full", **kwargs)
    return {r.fastener.name: r for r in report.results}, report


# The issue's four, drawn to the sheets: a #7 pan head 0.296 by 0.106 with a cross
# 0.176 across, a #14 at a 1/4's 0.492 by 0.175 and 0.281, a #5 0.245 by 0.089 and
# 0.158, and a #6 0.270 by 0.097 and 0.166.
ISSUE = [
    ("#7 x 1/2 pan head phillips tapping screw", pan(4.3, 3.84, 7.5, 2.7), 4.2),
    ("#14 x 1 pan head phillips tapping screw", pan(7.0, 6.15, 12.5, 4.4), 6.6),
    ("#5-40 x 1/2 pan head phillips machine screw", pan(3.9, 3.175, 6.2, 2.3), 3.6),
    ("#6 x 1/2 pan head phillips tapping screw", pan(4.1, 3.51, 6.9, 2.5), 3.9),
]


def test_the_issue_s_four_are_each_checked(engine):
    results, report = run(ISSUE, engine=engine)
    assert {
        name: (r.fastener.size.designation, r.verdict, r.tool, r.notes)
        for name, r in results.items()
    } == {
        "#7 x 1/2 pan head phillips tapping screw": ("#7", Verdict.TURNS, "driver-ph2", ()),
        "#14 x 1 pan head phillips tapping screw": ("#14", Verdict.TURNS, "driver-ph3", ()),
        "#5-40 x 1/2 pan head phillips machine screw": ("#5", Verdict.TURNS, "driver-ph2", ()),
        "#6 x 1/2 pan head phillips tapping screw": ("#6", Verdict.TURNS, "driver-ph2", ()),
    }
    # It said "3 not covered", and "#5 is outside the sizes the tables hold".
    assert report.terminal_lines()[0] == (
        "4 fasteners: 4 turn, 0 held, 0 blocked, 0 stuck, 0 not covered"
    )
    assert report.exit_code == 0


@pytest.mark.parametrize("shank", [0.110 * IN, 0.151 * IN, 0.154 * IN, 0.158 * IN])
def test_a_7_s_shank_drawn_anywhere_in_its_thread_is_quiet(shank):
    # From its core to the most a Type A's thread is made, 0.158 in: over its basic
    # diameter, 0.151, and a #7's all the same.
    name = "#7 x 1/2 pan head phillips tapping screw"
    results, _ = run([(name, pan(4.3, shank, 7.5, 2.7), 4.4)])
    assert (results[name].fastener.size.designation, results[name].notes) == ("#7", ())


def test_a_7_drawn_as_another_thread_is_the_tapping_size_of_that_diameter():
    # 2.9 across, under a #7's core (2.74)? No: inside its thread. 2.2 is under it,
    # and an ST2.2's: taken as drawn, as a #6 so drawn is.
    name = "#7 x 1/2 pan head phillips tapping screw"
    results, _ = run([(name, pan(1.9, 2.2, 4.0, 1.6), 2.6)])
    assert results[name].fastener.size.designation == "ST2.2"
    assert results[name].notes == (
        "drawn as an ST2.2 (2.20 shank), where its name says #7: taken as drawn",
    )


@pytest.mark.parametrize(
    ("name", "key", "tool"),
    [
        ("#5-40 x 3/8 socket head cap screw", 3 / 32, "hex-key-3/32in"),
        ("#5-40 x 3/8 button head cap screw", 5 / 64, "hex-key-5/64in"),
    ],
)
def test_a_number_5_socket_screw_takes_its_own_key(name, key, tool):
    results, _ = run([(name, socket_5(key), 3.6)])
    assert (results[name].fastener.size.designation, results[name].tool) == ("#5", tool)
    assert results[name].verdict is Verdict.TURNS


def test_a_number_5_nut_takes_a_5_16_spanner():
    nut = hexagon(5 / 16 * IN, 0.114 * IN) - Cylinder(0.1 * IN / 2, 10)
    results, _ = run([("#5-40 hex nut", nut, 3.6)])
    (found,) = results.values()
    assert (found.fastener.size.designation, found.tool) == ("#5", "spanner-5/16in")


# ---------------------------------------------------------------------------
# No shank is taken for one.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("shank", "size"),
    [
        (0.125 * IN, None),  # a #5's: no size a shank gives
        (3.2, None),
        (0.151 * IN, None),  # a #7's basic diameter
        (0.158 * IN, "M4"),  # and the most its thread is made: an M4's, 4.0, by the snap
        (0.242 * IN, None),  # a #14's basic
        (0.254 * IN, None),  # and its most, 6.45: between an M6 and a 1/4
    ],
)
def test_a_shank_alone_reads_as_before(shank, size):
    reading = read_shape(pan(3.9, shank, 2 * shank, 0.7 * shank), Kind.SCREW)
    assert (reading.size.designation if reading.size else None) == size


@pytest.mark.parametrize("shank", [3.13, 3.15, 3.175, 3.2, 3.22])
def test_an_m3_drawn_a_little_full_is_no_number_5(shank):
    # 3.175 across is a #5's, and 3.13 to 3.22 within the snap of it. An M3 so drawn
    # is the M3 its name says: quiet up to 3.15, the looseness a shank is given, and
    # past that kept and said, as before. Were a shank taken for a #5 it would be
    # told as one, "drawn as a #5", with a #5's key and driver.
    name = "M3x10 pan head phillips screw"
    results, _ = run([(name, pan(2.9, shank, 5.6, 2.4), shank + 0.4)])
    found = results[name]
    assert (found.fastener.size.designation, found.tool) == ("M3", "driver-ph1")
    if shank <= 3.15:
        assert found.notes == ()
    else:
        (note,) = found.notes
        assert note.startswith(f"drawn with a {shank:.2f} shank, no M3's thread")
        assert note.endswith("the name's M3 kept")
        assert "#5" not in note
