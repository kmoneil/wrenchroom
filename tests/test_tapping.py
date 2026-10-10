"""A tapping screw is sized as a tapping screw (issue #142).

A self-tapping screw is sold by its ISO 1478 size, ST2.2, ST2.9, ST3.5 and so on,
and often named loosely for the machine screw it stands in for: an "M2 self
tapping" screw is an ST2.2, whose thread is 2.24 across at most. The size tables
and the shank reading were machine screws' only, so one drawn as the ST2.2 it is,
a 2.2 shank and a PH0 cross, was reported as an inch machine screw, "drawn as a #2
(2.20 shank), where its name says M2", then noted again for a cross its #2 doesn't
take; and a name that gave the ST size wasn't read as a size at all.

Now the tables hold ISO 1478's fourteen threads, with the product standards' tools:
ISO 7049's cross recesses, ISO 1479's hexagons, ISO 14585's hexalobular sockets. A
name gives the size as ``ST2.2``, or as a machine size beside a word that says
tapping, which is the tapping size that machine size stands for. A tapping screw's
shank is then its own thread's, and quiet.

The figures here are the standards', in millimetres, not read back from the tables.
"""

import itertools
import math

import pytest
from build123d import Box, Cylinder, Pos, RegularPolygon, extrude

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config, ConfigError
from wrenchroom.detect import read_name
from wrenchroom.detect.names import name_words
from wrenchroom.fasteners import (
    HEX_HEAD_AF,
    PHILLIPS_NUMBER,
    TAPPING_FOR,
    TAPPING_THREADS,
    TORX_SIZE,
    Head,
    Size,
    no_such_head,
    tapping_by_thread,
    thread_minor_mm,
)
from wrenchroom.report import Verdict

# ---------------------------------------------------------------------------
# The tables.
# ---------------------------------------------------------------------------

#: ISO 1478:1999, Table 1: thread size -> (d1 min, d1 max, d2 min), and the number it had.
ISO_1478 = {
    "ST1.5": (1.38, 1.52, 0.84, 0),
    "ST1.9": (1.76, 1.90, 1.17, 1),
    "ST2.2": (2.10, 2.24, 1.52, 2),
    "ST2.6": (2.43, 2.57, 1.80, 3),
    "ST2.9": (2.76, 2.90, 2.08, 4),
    "ST3.3": (3.12, 3.30, 2.29, 5),
    "ST3.5": (3.35, 3.53, 2.51, 6),
    "ST3.9": (3.73, 3.91, 2.77, 7),
    "ST4.2": (4.04, 4.22, 2.95, 8),
    "ST4.8": (4.62, 4.80, 3.43, 10),
    "ST5.5": (5.28, 5.46, 3.99, 12),
    "ST6.3": (6.03, 6.25, 4.70, 14),
    "ST8": (7.78, 8.00, 5.99, 16),
    "ST9.5": (9.43, 9.65, 7.59, 20),
}


def test_the_threads_are_iso_1478_s():
    assert {size: thread for size, (*thread, _) in ISO_1478.items()} == {
        size: list(thread) for size, thread in TAPPING_THREADS.items()
    }


@pytest.mark.parametrize("designation", ISO_1478)
def test_a_tapping_size_is_its_thread_s_major_diameter(designation):
    least, most, core, _ = ISO_1478[designation]
    size = Size.parse(designation)
    assert (size.designation, size.diameter_mm) == (designation, most)
    assert (size.is_tapping, size.is_metric, size.family) == (True, True, "ST")
    assert thread_minor_mm(size) == core
    assert size.said == f"an {designation}"
    assert least < most


@pytest.mark.parametrize(
    ("written", "designation"),
    [("st2.2", "ST2.2"), ("ST 2.9", "ST2.9"), ("ST4,2", "ST4.2"), ("ST8", "ST8"), ("ST8.0", "ST8")],
)
def test_a_tapping_size_is_read_however_it_is_written(written, designation):
    assert Size.parse(written).designation == designation


@pytest.mark.parametrize("written", ["ST2", "ST3", "ST12", "ST", "ST2.25", "STUD"])
def test_a_size_iso_1478_doesn_t_have_is_none(written):
    with pytest.raises(ValueError, match="unknown fastener size"):
        Size.parse(written)


def test_a_machine_size_is_no_tapping_size():
    for written, family, said in (
        ("M3", "M", "an M3"),
        ("#4", "inch", "a #4"),
        ("1/4", "inch", "a 1/4"),
    ):
        size = Size.parse(written)
        assert (size.is_tapping, size.family, size.said) == (False, family, said)


def test_the_cross_recesses_are_iso_7049_s():
    # ISO 7049:2011, Table 1, pan head tapping screws ST2.2 to ST9.5.
    assert {size: n for size, n in PHILLIPS_NUMBER.items() if size.startswith("ST")} == {
        "ST2.2": 0,
        "ST2.9": 1,
        "ST3.5": 2,
        "ST4.2": 2,
        "ST4.8": 2,
        "ST5.5": 3,
        "ST6.3": 3,
        "ST8": 4,
        "ST9.5": 4,
    }


def test_the_hexagons_are_iso_1479_s():
    assert {size: af for size, af in HEX_HEAD_AF.items() if size.startswith("ST")} == {
        "ST2.2": 3.2,
        "ST2.9": 5.0,
        "ST3.5": 5.5,
        "ST4.2": 7.0,
        "ST4.8": 8.0,
        "ST5.5": 8.0,
        "ST6.3": 10.0,
        "ST8": 13.0,
    }


def test_the_hexalobular_sockets_are_iso_14585_s():
    # ISO 14585:2011, Table 1: ST2.9 to ST6.3 only.
    assert {size: t for size, t in TORX_SIZE.items() if size.startswith("ST")} == {
        "ST2.9": "T10",
        "ST3.5": "T15",
        "ST4.2": "T20",
        "ST4.8": "T25",
        "ST5.5": "T25",
        "ST6.3": "T30",
    }


def test_a_machine_size_stands_for_the_tapping_size_of_its_old_number():
    # ISO 1478's numbers are 0.060 in and 0.013 a number across: No. 2 is 2.18, an
    # M2 to a seller, and ST2.2; No. 4, 2.84, an M3, ST2.9; and so on.
    assert TAPPING_FOR == {
        "M1.6": "ST1.5",
        "M2": "ST2.2",
        "M2.5": "ST2.6",
        "M3": "ST2.9",
        "M3.5": "ST3.5",
        "M4": "ST4.2",
        "M5": "ST4.8",
        "M6": "ST6.3",
        "M8": "ST8",
        "M10": "ST9.5",
    }
    by_number = {number: size for size, (*_, number) in ISO_1478.items()}
    for machine, tapping in list(TAPPING_FOR.items())[:8]:
        number = next(n for n, size in by_number.items() if size == tapping)
        gauge = (0.060 + 0.013 * number) * 25.4
        assert abs(gauge - Size.parse(machine).diameter_mm) < 0.2, (machine, gauge)


@pytest.mark.parametrize("designation", ISO_1478)
def test_a_shank_anywhere_in_a_thread_s_range_is_that_size(designation):
    least, most, *_ = ISO_1478[designation]
    for drawn in (least, (least + most) / 2, most, round(most, 1)):
        found = tapping_by_thread(drawn)
        assert found is not None, drawn
        assert found.designation == designation, drawn


@pytest.mark.parametrize("drawn", [1.0, 1.65, 2.35, 3.0, 5.0, 5.8, 7.0, 9.0, 12.0])
def test_a_shank_between_two_threads_ranges_is_no_tapping_size(drawn):
    assert tapping_by_thread(drawn) is None


def test_the_threads_ranges_don_t_meet():
    ranges = sorted((least, most) for least, most, *_ in ISO_1478.values())
    gaps = [later[0] - earlier[1] for earlier, later in itertools.pairwise(ranges)]
    assert min(gaps) == pytest.approx(0.05, abs=1e-9)  # ST3.3's 3.30 and ST3.5's 3.35


# ---------------------------------------------------------------------------
# Names.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "size", "length"),
    [
        # Its own size, as ISO 1478 writes it.
        ("ST2.2x10 pan head phillips tapping screw", "ST2.2", 10.0),
        ("ST 4,2 x 16 hex head tapping screw", "ST4.2", 16.0),
        ("st3.9x16 csk screw", "ST3.9", 16.0),
        ("ST3.5x19", "ST3.5", 19.0),
        ("Screw ST4.8 x 13 mm", "ST4.8", 13.0),
        # A machine size, and a word that says tapping: the size it stands for.
        ("M2x10 self tapping pan head phillips screw", "ST2.2", 10.0),
        ("M3x10 self-tapping screw", "ST2.9", 10.0),
        ("M2x10 Selftapping screw", "ST2.2", 10.0),
        ("M4x12 tapping screw", "ST4.2", 12.0),
        ("M4x12 thread forming screw", "ST4.2", 12.0),
        ("M5x20 Type AB pan head screw", "ST4.8", 20.0),
        ("M6x25 sheet metal screw", "ST6.3", 25.0),
        ("M4x13 sheetmetal screw", "ST4.2", 13.0),
        ("Sheet Metal Screws M4x13", "ST4.2", 13.0),
        ("M3.5x13 self tapper screw", "ST3.5", 13.0),
        ("M2.5x8 self tapping screw", "ST2.6", 8.0),
        # Named by its thread's own diameter, which no machine screw has.
        ("M2.9x9.5 self-tapping screw", "ST2.9", 9.5),
        ("M4.2x13 sheet metal screw", "ST4.2", 13.0),
        ("M4.8x16 tapping screw", "ST4.8", 16.0),
    ],
)
def test_a_tapping_screw_s_name_gives_its_tapping_size(name, size, length):
    hint = read_name(name)
    assert hint is not None
    assert (hint.size.designation, hint.length_mm, hint.tapping, hint.not_covered) == (
        size,
        length,
        True,
        None,
    )


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("M3x10 pan head phillips screw", "M3"),  # no word says tapping
        ("M3x10 socket head cap screw", "M3"),
        ("#6 x 1/2 pan head tapping screw", "#6"),  # an inch one is named by its gauge
        ("M12x30 self tapping screw", "M12"),  # no tapping size stands for an M12
        ("M5x20 pan head screw Type B", "M5"),  # a variant of its own, as often as a thread
        ("M5x20 pan head screw type A", "M5"),
        ("M4x10 screw metal sheet", "M4"),  # not the words "sheet metal screw"
        ("M4x10 screw sheet metal side", "M4"),  # the sheet metal it holds, not its kind
        ("ST12 bracket screw", None),  # no size of ISO 1478's: a part number, say
    ],
)
def test_a_name_that_gives_no_tapping_size_keeps_its_own(name, size):
    hint = read_name(name)
    assert (hint.size.designation if hint.size else None) == size
    assert hint.size is None or not hint.size.is_tapping


def test_a_tapping_word_alone_gives_no_size():
    hint = read_name("pan head tapping screw")
    assert (hint.size, hint.tapping) == (None, True)


def test_a_tapping_nut_is_no_tapping_screw():
    # A word of a screw's: a nut named with it is a nut of its own size.
    hint = read_name("M4 self tapping nut")
    assert (hint.size.designation, hint.tapping) == ("M4", False)


def test_the_basis_says_what_the_name_s_size_stands_for():
    assert read_name("M3x10 self tapping screw").basis == (
        "noun 'screw', M3x10, a tapping screw's: ST2.9"
    )
    assert read_name("M2.9x9.5 tapping screw").basis == "noun 'screw', M2.9x9.5: ST2.9"
    assert read_name("ST2.9x9.5 tapping screw").basis == "noun 'screw', ST2.9x9.5"


# ---------------------------------------------------------------------------
# The issue's three, and their relations.
# ---------------------------------------------------------------------------


def hexagon(af, height, z0=0.0):
    return Pos(0, 0, z0) * extrude(RegularPolygon(af / math.sqrt(3), 6), height)


def pan(span, shank, dk=4.0, k=1.6):
    """A pan head ``dk`` by ``k`` with a cross ``span`` across its wings, on a shank
    ``shank`` across and 10 long: ISO 7049's ST2.2 by default (4.0 by 1.6, PH0)."""
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    head -= Pos(0, 0, k - 0.5) * (Box(span, 0.4, 1.01) + Box(0.4, span, 1.01))
    return head + Pos(0, 0, -5) * Cylinder(shank / 2, 10)


def run(cases, **kwargs):
    """Each (name, shape) on a plate of its own, 100 apart, checked with no sidecar."""
    parts = []
    for index, (name, shape) in enumerate(cases):
        plate = Pos(index * 100, 0, -5) * Box(30, 30, 10) - Pos(index * 100, 0, 0) * Cylinder(1, 30)
        parts += [Part(f"plate {index}", plate), Part(name, Pos(index * 100, 0, 0) * shape)]
    report = check(Assembly(parts), kit="full", **kwargs)
    return {r.fastener.name: r for r in report.results}, report


ISSUE = [
    ("M2x10 self tapping pan head phillips screw", pan(1.9, 2.2)),
    ("ST2.2x10 pan head phillips tapping screw", pan(1.9, 2.2)),
    ("M3x10 self tapping pan head phillips screw", pan(2.9, 2.9, dk=5.6, k=2.2)),
]


def test_the_issue_s_three_are_tapping_sizes_and_nothing_is_noted(engine):
    results, report = run(ISSUE, engine=engine)
    assert {
        name: (r.fastener.size.designation, r.tool, r.notes) for name, r in results.items()
    } == {
        "M2x10 self tapping pan head phillips screw": ("ST2.2", "driver-ph0", ()),
        "ST2.2x10 pan head phillips tapping screw": ("ST2.2", "driver-ph0", ()),
        "M3x10 self tapping pan head phillips screw": ("ST2.9", "driver-ph1", ()),
    }
    lines = report.terminal_lines()
    assert lines[:3] == [
        "3 fasteners: 3 turn, 0 held, 0 blocked, 0 stuck, 0 not covered",
        "  ST2.2 phillips screw     driver-ph0     x2    all pass (driver straight in)",
        "  ST2.9 phillips screw     driver-ph1     x1    all pass (driver straight in)",
    ]
    # It said "#2 phillips screw x2", and two notes: "drawn as a #2 (2.20 shank), where
    # its name says M2" and "cross drawn for PH0 ..., where a #2's standard gives PH1".
    assert not any(line.startswith("NOTE M") or line.startswith("NOTE ST") for line in lines)


def test_the_same_screws_with_no_tapping_word_are_machine_screws_as_before():
    cases = [
        ("M2x10 pan head phillips screw", pan(1.9, 2.2)),
        ("M3x10 pan head phillips screw", pan(2.9, 2.9, dk=5.6, k=2.2)),
    ]
    results, _ = run(cases)
    sizes = {name: r.fastener.size.designation for name, r in results.items()}
    assert sizes == {"M2x10 pan head phillips screw": "#2", "M3x10 pan head phillips screw": "M3"}
    (note,) = results["M2x10 pan head phillips screw"].notes[:1]
    assert note == "drawn as a #2 (2.20 shank), where its name says M2: taken as drawn"


@pytest.mark.parametrize("shank", [2.0, 2.1, 2.2, 2.24])
def test_an_st2_2_s_shank_drawn_anywhere_a_seller_s_m2_is_is_quiet(shank):
    # At the M2 its name says, at ISO 1478's least, at the number it is sold by, at
    # its most: each its own thread, core to major.
    results, _ = run([("M2x10 self tapping pan head phillips screw", pan(1.9, shank))])
    (result,) = results.values()
    assert (result.fastener.size.designation, result.notes) == ("ST2.2", ())


def test_a_tapping_screw_with_no_size_in_its_name_is_its_shank_s_own():
    # A 4.2 shank and a PH2 cross: an ST4.2 (ISO 7049: 8.0 by 3.1, m 4.4), where the
    # machine tables hold nothing 4.2 across.
    results, _ = run([("pan head phillips tapping screw", pan(4.4, 4.2, dk=8.0, k=3.1))])
    (result,) = results.values()
    assert (result.fastener.size.designation, result.tool, result.notes) == (
        "ST4.2",
        "driver-ph2",
        (),
    )
    assert result.fastener.confidence == "medium"  # its size rests on its shank


def test_a_shank_that_is_another_tapping_size_s_is_taken_as_drawn_and_noted():
    # Named for an M3, an ST2.9, and drawn 3.5 across with ST3.5's head and PH2 cross.
    results, _ = run([("M3x10 self tapping pan head phillips screw", pan(3.9, 3.5, dk=7.0, k=2.6))])
    (result,) = results.values()
    assert (result.fastener.size.designation, result.tool) == ("ST3.5", "driver-ph2")
    assert result.notes == (
        "drawn as an ST3.5 (3.50 shank), where its name says ST2.9: taken as drawn",
    )
    assert result.fastener.confidence == "low"


def test_a_shank_that_is_no_tapping_size_s_is_said_and_the_name_s_kept():
    results, _ = run([("ST2.9x10 pan head phillips tapping screw", pan(2.9, 1.0, dk=5.6, k=2.2))])
    (result,) = results.values()
    assert (result.fastener.size.designation, result.tool) == ("ST2.9", "driver-ph1")
    assert result.notes == ("drawn with a 1.00 shank, no ST2.9's thread: the name's ST2.9 kept",)


def test_an_inch_tapping_screw_keeps_its_gauge():
    # ASME B18.6.4's numbered sizes are the machine screws' gauges: a #6, 3.51 across.
    results, _ = run([("#6 x 1/2 pan head phillips tapping screw", pan(4.0, 3.5, dk=7.0, k=2.6))])
    (result,) = results.values()
    assert (result.fastener.size.designation, result.tool, result.notes) == ("#6", "driver-ph2", ())


def test_an_inch_tapping_screw_drawn_as_another_thread_is_that_tapping_size():
    # Named a #6 and drawn 2.2 across with a PH0 cross, under a #6's own thread
    # (2.53 at its root): a tapping screw, so the thread ISO 1478 makes at 2.2, not
    # the #2 a machine screw would be.
    name = "#6 x 1/2 pan head phillips tapping screw"
    results, _ = run([(name, pan(1.9, 2.2))])
    assert (results[name].fastener.size.designation, results[name].tool) == ("ST2.2", "driver-ph0")
    assert results[name].notes == (
        "drawn as an ST2.2 (2.20 shank), where its name says #6: taken as drawn",
    )


# ---------------------------------------------------------------------------
# Other drives.
# ---------------------------------------------------------------------------


def test_a_hexagon_head_tapping_screw_takes_iso_1479_s_spanner(engine):
    # ST4.2: 7 across flats. By the machine tables a 7 mm hex is an M4 nut's, and a
    # 4.2 shank no M4's: its name's size stands, and nothing is said.
    screw = hexagon(7.0, 2.8) + Pos(0, 0, -5) * Cylinder(2.1, 10)
    results, _ = run([("ST4.2x10 hex head tapping screw", screw)], engine=engine)
    (result,) = results.values()
    assert (result.verdict, result.fastener.size.designation, result.tool, result.notes) == (
        Verdict.TURNS,
        "ST4.2",
        "spanner-7",
        (),
    )


def test_a_hex_socket_tapping_screw_takes_the_key_its_socket_shows():
    # The public CW2 model's shape: a button head on a 2 mm key, named an M2
    # self-tapping screw. The tool was right, and the size bought wasn't said.
    head = Pos(0, 0, 0.65) * Cylinder(1.9, 1.3) - hexagon(2.0, 0.9, 0.41)
    screw = head + Pos(0, 0, -5) * Cylinder(1.0, 10)
    results, report = run([("M2x10 Selftapping screw", screw)])
    (result,) = results.values()
    assert (result.fastener.size.designation, result.tool, result.notes) == (
        "ST2.2",
        "hex-key-2",
        (),
    )
    assert "  ST2.2 button screw       hex-key-2      x1    all pass" in report.terminal_lines()[1]


RULED = Pos(0, 0, 1.3) * Cylinder(3.5, 2.6) + Pos(0, 0, -5) * Cylinder(1.75, 10)


def ruled(**rule):
    plate = Pos(0, 0, -5) * Box(30, 30, 10) - Cylinder(1.8, 30)
    config = Config.from_dict(
        {"fasteners": [{"parts": "screw", "kind": "screw", **rule}], "checks": {"detect": False}}
    )
    report = check(Assembly([Part("plate", plate), Part("screw", RULED)]), config, kit="full")
    (result,) = report.results
    return result


@pytest.mark.parametrize(
    ("head", "size", "tool"),
    [
        ("phillips", "ST2.2", "driver-ph0"),
        ("phillips", "ST3.5", "driver-ph2"),
        ("phillips", "ST6.3", "driver-ph3"),
        ("torx", "ST2.9", "torx-key-T10"),
        ("torx", "ST3.5", "torx-key-T15"),
        ("torx", "ST4.8", "torx-key-T25"),
        ("torx", "ST5.5", "torx-key-T25"),
        ("hex", "ST3.5", "spanner-5.5"),
        ("hex", "ST8", "spanner-13"),
    ],
)
def test_a_sidecar_s_tapping_size_takes_its_standard_s_tool(head, size, tool):
    result = ruled(head=head, size=size)
    assert (result.verdict, result.tool, result.fastener.size.designation) == (
        Verdict.TURNS,
        tool,
        size,
    )


def test_a_tapping_size_with_no_standard_tool_says_so():
    assert ruled(head="socket", size="ST4.2").reason == (
        "no standard key for an ST4.2 socket head: give across_flats:"
    )
    assert ruled(head="torx", size="ST8").reason == "ISO 14585 has no ST8 torx head"
    assert no_such_head(Head.TORX, Size.parse("ST2.2")) == "ISO 14585 has no ST2.2 torx head"
    # And a machine screw's as it did.
    assert no_such_head(Head.BUTTON, Size.parse("M2")) == "ISO 7380-1 has no M2 button head"


def test_a_size_no_table_holds_is_a_config_error():
    with pytest.raises(ConfigError, match="unknown fastener size 'ST3'"):
        Config.from_dict({"fasteners": [{"parts": "s", "kind": "screw", "size": "ST3"}]})


def test_the_json_and_the_tools_list_say_the_tapping_size():
    _, report = run(ISSUE)
    document = report.to_json_dict()
    assert sorted(f["size"] for f in document["fasteners"]) == ["ST2.2", "ST2.2", "ST2.9"]
    assert "| ST2.2 phillips screw | `driver-ph0` | 2 |" in report.markdown()


def test_a_shank_a_drawing_rounds_past_a_thread_s_range_is_still_its_size():
    # 0.04 past ST2.2's most, 2.24, is its; 0.06 past is no size's (ST2.6 starts at 2.43).
    assert tapping_by_thread(2.28).designation == "ST2.2"
    assert tapping_by_thread(2.06).designation == "ST2.2"
    assert tapping_by_thread(2.30) is None
    assert tapping_by_thread(2.04) is None


def test_a_seller_s_m3_drawn_as_the_m3_its_name_says_is_quiet():
    # A 3.0 shank on an ST2.9, 0.10 past its most: drawn to the name, loosely, as an
    # M3's drawn 3.1 is an M3 (#135). 0.15 is the slack; 3.10 is past it, and is
    # ST3.3's (3.12 at least, less a drawing's 0.05).
    name = "M3x10 self tapping pan head phillips screw"
    results, _ = run([(name, pan(2.9, 3.0, dk=5.6, k=2.2))])
    assert (results[name].fastener.size.designation, results[name].notes) == ("ST2.9", ())
    results, _ = run([(name, pan(2.9, 3.1, dk=5.6, k=2.2))])
    assert results[name].notes == (
        "drawn as an ST3.3 (3.10 shank), where its name says ST2.9: taken as drawn",
    )


def test_a_tapping_size_is_left_out_of_a_name_s_words_and_no_other_st_is():
    assert name_words("ST2.9x13 pan head screw") == ["pan", "head", "screw"]
    assert name_words("ST12 bracket") == ["st12", "bracket"]
