"""A hex drawn inside its standard's tolerance takes its spanner (issue #27).

A nut standard lets a hex come a little under its nominal across flats (ISO 4032:
an M8 nut from 12.73 to 13.00), so a model drawn there, an M8 nut at 12.8, is a
real nut, and a 13 mm spanner fits it. The band lies below the size only: a
spanner fits a hex up to its own size and no further. The thread's own standard
comes first, exact or in its band; then any tool size the hex exactly is; then
a band that alone holds it. Hex keys have no band: a socket's tolerance runs the
other way, and isn't read here.
"""

from itertools import pairwise

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism, socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.detect.geometry import read_shape
from wrenchroom.fasteners import (
    DIN_HEX_AF,
    HEX_AF,
    HEX_AF_MIN,
    HEX_HEAD_AF,
    Kind,
    Size,
    in_hex_band,
    standard_hex_afs,
)
from wrenchroom.report import Verdict
from wrenchroom.tools.sizes import INCH_FLATS, METRIC_FLATS, inch_mm, size_name

IN = 25.4
FLATS = set(METRIC_FLATS) | {inch_mm(size) for size in INCH_FLATS}


# ---------------------------------------------------------------------------
# The table.
# ---------------------------------------------------------------------------


def test_every_band_lies_just_below_a_spanner_size():
    assert len(HEX_AF_MIN) == 42  # a vacuity guard: 25 metric sizes, 17 inch
    for af, minimum in HEX_AF_MIN.items():
        assert af in FLATS, af
        # A tolerance, not another size: within 5%, or 0.2 mm at the smallest, where
        # ISO 4032's 0.18 is 5.6% of a 3.2 (issue #83).
        assert 0 < af - minimum < max(0.05 * af, 0.2), af


@pytest.mark.parametrize(
    ("af", "minimum"),
    [
        # ISO 4032 (grade A to M16, B above) and DIN 934, as torqbolt.com prints them.
        (5.5, 5.32),
        (13.0, 12.73),
        (24.0, 23.67),
        (30.0, 29.16),
        (36.0, 35.0),
        (41.0, 40.0),  # M27, M30 and M33: the sizes large glands share (issue #33)
        (46.0, 45.0),
        (50.0, 49.0),
        (17.0, 16.73),  # DIN 934 M10
        (19.0, 18.67),  # DIN 934 M12
        (32.0, 31.0),  # DIN 934 M22
        # ASME B18.2.2 and B18.6.3, in inches; where both give a size, the smaller.
        (inch_mm("1/4"), 0.241 * IN),
        (inch_mm("7/16"), 0.423 * IN),  # B18.6.3's 1/4 machine screw nut (B18.2.2: 0.428)
        (inch_mm("9/16"), 0.545 * IN),  # B18.6.3's 5/16 (B18.2.2: 0.551)
        (inch_mm("3/4"), 0.736 * IN),
        (inch_mm("1-1/8"), 1.088 * IN),
    ],
)
def test_the_bands_are_the_standards(af, minimum):
    assert HEX_AF_MIN[af] == pytest.approx(minimum)


def test_every_nut_the_tables_name_has_a_band():
    for size, af in {**HEX_AF, **DIN_HEX_AF}.items():
        assert af in HEX_AF_MIN, size


def test_only_the_inch_head_that_parts_from_its_nut_and_every_table_lacks_a_band():
    # A 9/16 hex head is 13/16 in, which no nut is; B18.2.1's minimum wasn't to be had.
    assert {size for size, af in HEX_HEAD_AF.items() if af not in HEX_AF_MIN} == {"9/16"}


def test_the_bands_of_one_system_never_overlap():
    for system in (
        sorted(af for af in HEX_AF_MIN if af in METRIC_FLATS),
        sorted(af for af in HEX_AF_MIN if af not in METRIC_FLATS),
    ):
        for smaller, larger in pairwise(system):
            assert smaller < HEX_AF_MIN[larger], (smaller, larger)


def test_where_metric_and_inch_bands_overlap_the_thread_decides():
    overlaps = {
        (size_name(metric), size_name(inch))
        for metric in HEX_AF_MIN
        if metric in METRIC_FLATS
        for inch in HEX_AF_MIN
        if inch not in METRIC_FLATS
        and max(HEX_AF_MIN[metric], HEX_AF_MIN[inch]) <= min(metric, inch)
    }
    assert overlaps == {
        ("4", "5/32in"),  # an M2 nut's and a #0's, 3.82 to 3.97 (issue #83)
        ("8", "5/16in"),
        ("11", "7/16in"),
        ("16", "5/8in"),
        ("19", "3/4in"),
        ("22", "7/8in"),
        ("24", "15/16in"),
        ("34", "1-5/16in"),
    }


@pytest.mark.parametrize(
    ("measured", "af", "inside"),
    [
        (12.8, 13.0, True),
        (12.73, 13.0, True),
        (13.0, 13.0, True),
        (12.72, 13.0, False),
        (13.01, 13.0, False),  # above the size: no spanner of it fits
        (29.2, 30.0, True),
        (2.5, 2.5, False),  # a key size: no band
        (inch_mm("13/16") - 0.1, inch_mm("13/16"), False),
    ],
)
def test_in_hex_band(measured, af, inside):
    assert in_hex_band(measured, af) is inside


@pytest.mark.parametrize(
    ("size", "afs"),
    [
        ("M8", {13.0}),
        ("M10", {16.0, 17.0}),  # ISO 4032 and DIN 934
        ("M22", {34.0, 32.0}),
        ("7/16", {inch_mm("11/16"), inch_mm("5/8")}),  # its nut, and its head
        ("M3.5", set()),  # in no hex table
    ],
)
def test_standard_hex_afs(size, afs):
    assert standard_hex_afs(Size.parse(size)) == afs


# ---------------------------------------------------------------------------
# In the check.
# ---------------------------------------------------------------------------


def nut_on_plate(af, bore=4.0):
    """A nut of `af` across flats, 6.8 tall, on a plate: room all round."""
    return Assembly(
        [
            Part("nut", hex_prism(af, 6.8) - Cylinder(bore, 30)),
            Part("plate", Pos(0, 0, -5) * Box(200, 200, 10)),
        ]
    )


def run(assembly, rule=None, kit="full"):
    config = Config.from_dict({"fasteners": [rule]} if rule else {})
    (result,) = check(assembly, config, kit=kit).results
    return result


@pytest.mark.parametrize("af", [13.0, 12.8, 12.73])
def test_a_detected_m8_nut_in_its_band_takes_the_13(af):
    # Issue #27's reproduction: 12.8 used to be "no tool's size".
    result = run(nut_on_plate(af), kit="metric-home")
    assert (result.verdict, result.tool) == (Verdict.TURNS, "spanner-13")
    assert result.fastener.size.designation == "M8"


def test_across_flats_in_the_sidecar_takes_its_band_too():
    rule = {"parts": "nut", "kind": "nut", "size": "M8", "across_flats": 12.8}
    assert run(nut_on_plate(12.8), rule).tool == "spanner-13"


@pytest.mark.parametrize(
    ("size", "tool"),
    [("M5", "spanner-8"), ("#6", "spanner-5/16in")],
)
def test_where_two_bands_hold_a_hex_its_thread_decides(size, tool):
    # 7.85 lies in 8 mm's band (7.78 to 8) and 5/16 in's (7.67 to 7.94).
    rule = {"parts": "nut", "kind": "nut", "size": size, "across_flats": 7.85}
    assert run(nut_on_plate(7.85, bore=1.5), rule).tool == tool


def test_where_two_bands_hold_it_and_nothing_decides_it_is_not_covered_saying_so():
    rule = {"parts": "nut", "kind": "nut", "across_flats": 7.85}
    result = run(nut_on_plate(7.85, bore=1.5), rule)
    assert result.verdict is Verdict.NOT_COVERED
    assert (
        result.reason
        == "7.85 mm across flats fits spanner-8 or spanner-5/16in: set tool: in the sidecar"
    )


def test_a_hex_in_one_band_takes_it_when_nothing_gives_its_thread():
    # 12.6 is under M8's band, and inside 1/2 in's (12.42 to 12.70): that spanner
    # fits. With a thread, its own system's spanner comes first (test_undersize.py).
    rule = {"parts": "nut", "kind": "nut", "across_flats": 12.6}
    assert run(nut_on_plate(12.6), rule).tool == "spanner-1/2in"


@pytest.mark.parametrize(
    ("af", "reason"),
    [
        (
            12.4,  # 0.33 under M8's band: further under than a model drawn small
            "12.40 mm across flats is no tool's size: the smallest that fits, spanner-13, "
            "is 0.60 larger; set across_flats: or tool: in the sidecar",
        ),
        (
            13.3,  # over 13: no band reaches above its size
            "13.30 mm across flats is no tool's size: the smallest that fits, spanner-14, "
            "is 0.70 larger; set across_flats: or tool: in the sidecar",
        ),
    ],
)
def test_outside_every_band_the_reason_names_the_smallest_that_fits(af, reason):
    rule = {"parts": "nut", "kind": "nut", "size": "M8", "across_flats": af}
    result = run(nut_on_plate(af), rule)
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == reason


@pytest.mark.parametrize(
    ("af", "size", "tool"),
    [
        (13.0, None, "spanner-13"),
        (12.99, None, "spanner-13"),
        (19.05, None, "spanner-3/4in"),
        (11.1125, None, "spanner-7/16in"),
        # A few hundredths from an inch size and inside a metric band: with no
        # thread the exact size decides, with one its own standard does.
        (7.94, None, "spanner-5/16in"),
        (7.94, "M5", "spanner-8"),
        (12.73, None, "spanner-1/2in"),
        (12.73, "M8", "spanner-13"),
        (19.05, "M12", "spanner-3/4in"),  # over DIN's 19, no metric size: exactly 3/4 in
    ],
)
def test_the_thread_s_own_size_first_then_an_exact_size(af, size, tool):
    rule = {"parts": "nut", "kind": "nut", "across_flats": af, **({"size": size} if size else {})}
    assert run(nut_on_plate(af, bore=3.0), rule).tool == tool


def test_a_hex_key_has_no_band():
    # A socket at 7.85 is inside 8 mm's spanner band (and 5/16 in's); a key is
    # another matter.
    rule = {
        "parts": "screw",
        "kind": "screw",
        "head": "socket",
        "size": "M10",
        "across_flats": 7.85,
    }
    assembly = Assembly(
        [Part("screw", socket_screw("M10")), Part("plate", Pos(0, 0, -5) * Box(200, 200, 10))]
    )
    result = run(assembly, rule)
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == (
        "7.85 mm across flats is no tool's size: the largest that fits, hex-key-6, is 1.85 "
        "smaller; set across_flats: or tool: in the sidecar"
    )


# ---------------------------------------------------------------------------
# In detection: the band settles the size.
# ---------------------------------------------------------------------------


def test_a_hex_in_its_band_guesses_the_size_when_the_bore_cannot():
    # The bore drawn at 6.8, near M8's minor diameter, is no standard size. The
    # band alone says M8: a guess, which a name or the nut's bolt outranks (#50).
    nut = hex_prism(12.8, 6.8) - Cylinder(3.4, 30)
    reading = read_shape(nut, Kind.NUT)
    assert reading.drive_af == pytest.approx(12.8)
    assert reading.size.designation == "M8"
    assert (reading.size_from_drive, reading.size_from_band) == (False, True)


def test_a_key_pocket_has_no_band_in_detection_either():
    # A 5.9 pocket in an M8 socket head (6 mm key). 5.9 is inside 6 mm's spanner
    # band, but a pocket isn't a hex a spanner grips: the shank gives the size.
    screw = (
        Pos(0, 0, -10) * Cylinder(4, 20) + Pos(0, 0, 4) * Cylinder(6.5, 8) - hex_prism(5.9, 4.01, 4)
    )
    reading = read_shape(screw, Kind.SCREW)
    assert reading.drive_af == pytest.approx(5.9)
    assert (reading.size.designation, reading.size_from_drive) == ("M8", False)
