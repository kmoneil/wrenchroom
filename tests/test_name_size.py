"""A name's thread size the solid disagrees with, and leadscrew nuts (issue #117).

- A screw named M5x16 and drawn as an M3, its drive and its shank both an M3's:
  checked as drawn, as it was, but no longer silently: noted, as a length is
  (issue #94), at low confidence, the basis saying what the name said. Likewise a
  nut by its hex and bore, and a screw with no drive by its shank alone, which used
  to take the name's size.
- A thread is drawn anywhere from its minor diameter to its nominal, a nut's bore
  with clearance over it: drawn so, it is the name's, and quiet.
- A leadscrew, a ball screw or the nut that runs on one moves a part, and no tool
  turns it: passed over, whatever its solid shows.
"""

import json
import math

import pytest
from build123d import Box, Cone, Cylinder, Pos, RegularPolygon, extrude

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.detect import MOTION, NUT_BORE_OVER, find, read_name, read_shape
from wrenchroom.detect.geometry import SIZE_SNAP_MM
from wrenchroom.detect.sidecar import sidecar_text
from wrenchroom.fasteners import (
    COARSE_PITCH_MM,
    IMPERIAL_SIZES,
    METRIC_SIZES,
    Kind,
    Size,
    thread_minor_mm,
)


def hexagon(af, h, z0=0.0):
    return Pos(0, 0, z0) * extrude(RegularPolygon(af / math.sqrt(3), 6), h)


def socket_screw(shank=3.0, key=2.5, dk=5.5, k=3.0, length=16.0):
    """ISO 4762 M3x16 as drawn by default: a 5.5 by 3 head, a 2.5 socket, a 3 shank."""
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k) - hexagon(key, 1.31, k - 1.3)
    return head + Pos(0, 0, -length / 2) * Cylinder(shank / 2, length)


def phillips_screw(shank=3.0, dk=5.6, k=2.4, length=12.0):
    """A pan head with a cross 3.2 by 0.6 sunk 1.4 into it: no hex, no size of its own."""
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    cross = Pos(0, 0, k - 0.7) * (Box(3.2, 0.6, 1.41) + Box(0.6, 3.2, 1.41))
    return head - cross + Pos(0, 0, -length / 2) * Cylinder(shank / 2, length)


def hex_nut(af=5.5, bore=3.0, m=2.4):
    return hexagon(af, m) - Cylinder(bore / 2, 3 * m)


def found(name, shape):
    (fastener,) = find([Part(name, shape)]).fasteners
    return fastener


def drawn_as(solid, shown, named):
    return f"drawn as {solid} ({shown}), where its name says {named}: taken as drawn"


# ---------------------------------------------------------------------------
# The issue's four names on one M3.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "named"),
    [
        ("M5x16 SHCS", "M5"),
        ("M2x16 SHCS", "M2"),
        ("ISO 4762 M4x16", "M4"),
        ("1/4-20 x 5/8 SHCS", "1/4"),
    ],
)
def test_a_screw_drawn_as_another_size_than_its_name_s_is_noted(name, named):
    fastener = found(name, socket_screw())
    assert fastener.size == Size.parse("M3")
    assert fastener.notes == (drawn_as("an M3", "3.00 shank, 2.50 socket", named),)
    assert fastener.confidence == "low"
    assert fastener.basis.endswith(f"M3 measured (the name says {named})")


def test_the_same_screw_named_for_its_size_is_quiet():
    fastener = found("M3x16 SHCS", socket_screw())
    assert (fastener.size, fastener.notes, fastener.confidence) == (
        Size.parse("M3"),
        (),
        "high",
    )
    assert fastener.basis.endswith("M3 measured")


def test_the_check_says_it_and_the_json_carries_it():
    plate = Pos(0, 0, -5) * Box(30, 30, 10) - Cylinder(1.5, 30)
    report = check(Assembly([Part("plate", plate), Part("M5x16 SHCS", socket_screw())]))
    (result,) = report.results
    assert (result.tool, result.passed) == ("hex-key-2.5", True)
    note = drawn_as("an M3", "3.00 shank, 2.50 socket", "M5")
    assert f"NOTE M5x16 SHCS: {note}" in report.terminal_lines()
    (entry,) = json.loads(report.json_text())["fasteners"]
    assert (entry["size"], entry["notes"]) == ("M3", [note])


def test_detect_s_comment_says_what_the_name_said():
    plate = Pos(0, 0, -5) * Box(30, 30, 10) - Cylinder(1.5, 30)
    report = check(Assembly([Part("plate", plate), Part("M5x16 SHCS", socket_screw())]))
    text = sidecar_text(report, "model.step")
    assert (
        "# M5x16 SHCS: low confidence; found by noun 'shcs', M5x16; solid: socket, "
        "2.5 across flats, M3 measured (the name says M5)"
    ) in text
    assert "    size: M3\n" in text


def test_an_inch_screw_drawn_as_a_metric_one_is_noted():
    # An M6: 6.0 shank and ISO 4762's 5 mm key, under a 1/4-20 name. The shank lies in
    # 1/4's thread too (its minor is 4.79), but it is drawn as the drive's M6 exactly.
    fastener = found("1/4-20 SHCS", socket_screw(shank=6.0, key=5.0, dk=10.0, k=6.0))
    assert fastener.size == Size.parse("M6")
    assert fastener.notes == (drawn_as("an M6", "6.00 shank, 5.00 socket", "1/4"),)


def test_an_inch_size_is_said_with_its_own_article():
    # A #4's key (3/32) and shank under an M3 name.
    fastener = found("M3x16 SHCS", socket_screw(shank=2.845, key=2.381, dk=4.83, k=2.845))
    assert fastener.size == Size.parse("#4")
    assert fastener.notes == (drawn_as("a #4", "2.85 shank, 2.38 socket", "M3"),)


# ---------------------------------------------------------------------------
# Drawn as the name's thread: quiet.
# ---------------------------------------------------------------------------


def test_a_shank_drawn_within_its_thread_s_tolerance_is_quiet():
    # The issue's 2.9 on an M3: a 6g M3's major runs 2.874 to 2.980.
    fastener = found("M3x16 SHCS", socket_screw(shank=2.9))
    assert (fastener.size, fastener.notes) == (Size.parse("M3"), ())
    fastener = found("M3x12 phillips screw", phillips_screw(shank=2.9))
    assert (fastener.size, fastener.notes) == (Size.parse("M3"), ())


def test_a_thread_drawn_at_its_minor_that_sits_on_another_size_is_the_name_s():
    # An M5's drawn at its minor, 4.13, is #8's 4.166 within the snap: with no drive
    # to say otherwise, the name's M5 stands, as it did, and nothing is said.
    reading = read_shape(phillips_screw(shank=4.13, dk=9.5, k=3.5), Kind.SCREW)
    assert reading.size == Size.parse("#8")
    fastener = found("M5x12 phillips screw", phillips_screw(shank=4.13, dk=9.5, k=3.5))
    assert (fastener.size, fastener.notes) == (Size.parse("M5"), ())


def test_a_drive_that_agrees_with_the_name_keeps_it_whatever_the_shank():
    # ISO 4762 M5's 4 mm key over a shank drawn as an M3's.
    fastener = found("M5x16 SHCS", socket_screw(shank=3.0, key=4.0, dk=8.5, k=5.0))
    assert (fastener.size, fastener.notes) == (Size.parse("M5"), ())


def test_a_drive_alone_against_the_name_stays_as_it_was():
    # M3's 2.5 key over a 3.5 shank, which an M4 could be drawn as (its minor 3.14)
    # and no size's own: the drive's M3, as before, and nothing said.
    fastener = found("M4x16 SHCS", socket_screw(shank=3.5))
    assert (fastener.size, fastener.notes) == (Size.parse("M3"), ())


# ---------------------------------------------------------------------------
# The bounds: from the minor, less the snap, to the nominal, plus it.
# ---------------------------------------------------------------------------


def test_the_minors_are_iso_724_s_and_the_pitches_coarse():
    assert set(COARSE_PITCH_MM) == {*METRIC_SIZES, *IMPERIAL_SIZES}
    assert COARSE_PITCH_MM["M3"] == 0.5
    assert COARSE_PITCH_MM["M24"] == 3.0
    assert COARSE_PITCH_MM["1/4"] == pytest.approx(25.4 / 20)
    assert COARSE_PITCH_MM["#0"] == pytest.approx(25.4 / 80)
    # d3 = d - 1.22687 P: an M3's 2.387, an M6's 4.773, a 1/4-20's 4.792.
    assert thread_minor_mm(Size.parse("M3")) == pytest.approx(2.387, abs=0.001)
    assert thread_minor_mm(Size.parse("M6")) == pytest.approx(4.773, abs=0.001)
    assert thread_minor_mm(Size.parse("1/4")) == pytest.approx(4.792, abs=0.001)
    assert (SIZE_SNAP_MM, NUT_BORE_OVER) == (0.05, 1.15)


@pytest.mark.parametrize(
    ("shank", "noted"),
    [
        (4.0, False),  # M4's nominal, but inside an M5's thread: its minor is 4.019
        (3.96, True),  # M4 within the snap, and under the M5's minor by more than it
    ],
)
def test_a_shank_alone_under_the_name_s_minor_is_drawn_as_its_own(shank, noted):
    fastener = found("M5x12 phillips screw", phillips_screw(shank=shank, dk=9.5, k=3.5))
    assert fastener.size == Size.parse("M4" if noted else "M5")
    want = (drawn_as("an M4", f"{shank:.2f} shank", "M5"),) if noted else ()
    assert fastener.notes == want


@pytest.mark.parametrize(
    ("shank", "named", "noted"),
    [
        (3.5, "M3", True),  # an M3.5's, over an M3's nominal
        (3.04, "M3.5", False),  # an M3, inside an M3.5's thread (its minor 2.76)
        (2.5, "M2", True),  # an M2.5's, 0.45 over an M2's
        (2.0, "M2.5", False),  # inside an M2.5's thread (minor 1.95): the name's
        (1.95, "M2.5", False),  # snaps to M2, still inside (1.948 - 0.05)
        (2.52, "M2.5", False),  # snaps to #3's 2.515, within the snap over 2.5
        (2.56, "M2.5", True),  # #3's too, and past it
    ],
)
def test_a_shank_alone_over_the_name_s_nominal_is_drawn_as_its_own(shank, named, noted):
    fastener = found(f"{named}x12 phillips screw", phillips_screw(shank=shank))
    if noted:
        solid = read_shape(phillips_screw(shank=shank), Kind.SCREW).size
        assert fastener.size == solid
        article = "an" if solid.is_metric else "a"
        assert fastener.notes == (
            drawn_as(f"{article} {solid.designation}", f"{shank:.2f} shank", named),
        )
        assert fastener.confidence == "low"
    else:
        assert (fastener.size, fastener.notes) == (Size.parse(named), ())


def test_a_phillips_screw_takes_the_driver_of_the_size_it_is_drawn_as():
    plate = Pos(0, 0, -5) * Box(30, 30, 10) - Cylinder(1.5, 30)
    model = Assembly([Part("plate", plate), Part("M5x12 phillips screw", phillips_screw())])
    (result,) = check(model).results
    assert (result.fastener.size.designation, result.tool) == ("M3", "driver-ph1")
    assert result.notes == (drawn_as("an M3", "3.00 shank", "M5"),)


# ---------------------------------------------------------------------------
# Nuts: the hex and the bore.
# ---------------------------------------------------------------------------


def test_a_nut_drawn_as_another_size_is_noted():
    # An M3 nut, 5.5 across, bored at 3, under an M4 name.
    fastener = found("M4 hex nut", hex_nut())
    assert fastener.size == Size.parse("M3")
    assert fastener.notes == (drawn_as("an M3", "3.00 bore, 5.50 hex", "M4"),)
    assert fastener.confidence == "low"


def test_a_nut_bored_at_its_minor_is_noted_by_its_bore_s_distance():
    # An M3 nut bored at its minor, 2.46: no M5 thread is drawn so.
    fastener = found("M5 hex nut", hex_nut(bore=2.46))
    assert fastener.notes == (drawn_as("an M3", "2.46 bore, 5.50 hex", "M5"),)


@pytest.mark.parametrize(
    ("bore", "noted"),
    [
        (3.4, False),  # an M3's clearance, inside an M4's thread: drive alone
        (4.6, False),  # 1.15 of an M4, an M4's with clearance: drive alone
        (4.64, False),  # 4.6 plus the snap, at the edge
        (4.75, True),  # past it: no M4's bore
    ],
)
def test_a_nut_s_bore_may_be_drawn_with_clearance(bore, noted):
    fastener = found("M4 hex nut", hex_nut(bore=bore))
    assert fastener.size == Size.parse("M3")  # the 5.5 hex, as before
    assert bool(fastener.notes) is noted


def test_an_insert_s_bore_is_no_size_against_its_name():
    # A heat-set insert's bore is drawn at the tap drill or anything else: its name
    # stands, and its screw outranks it at the check (issue #84).
    insert = Cylinder(2.5, 5) - Cylinder(1.5, 6)
    fastener = found("M5 heat set insert", insert)
    assert (fastener.size, fastener.notes) == (Size.parse("M5"), ())


def test_an_insert_s_solid_is_never_said_against_its_name():
    # A press-in insert with a hex body, 8 across (an M5 nut's), bored 3: its hex
    # settles its size as it did, and nothing is said. An insert's solid is no
    # thread's to hold against a name: its bore is a guess its screw outranks
    # (issue #84), and its body grips the part, not a tool.
    insert = hex_nut(af=8.0, bore=3.0, m=6.0)
    reading = read_shape(insert, Kind.INSERT)
    assert (reading.size, reading.size_from_drive) == (Size.parse("M5"), True)
    fastener = found("M4 press-in insert", insert)
    assert fastener.kind is Kind.INSERT
    assert (fastener.size, fastener.notes) == (Size.parse("M5"), ())


def test_a_hex_in_a_band_alone_is_no_size_against_its_name():
    # 12.8 across: in an M8's ISO 4032 band, and no exact size; bored at no size.
    reading = read_shape(hex_nut(af=12.8, bore=7.0, m=6.5), Kind.NUT)
    assert reading.size_from_band
    fastener = found("M10 nut", hex_nut(af=12.8, bore=7.0, m=6.5))
    assert (fastener.size, fastener.notes) == (Size.parse("M10"), ())


def test_a_drive_drawn_loose_against_another_shank_settles_nothing():
    # M3's 2.5 key drawn 2.6, loose, over an M4's 4.0 shank: the solid says no one
    # size, so the name's M6 stands, though the shank is no M6's.
    body = socket_screw(shank=4.0, key=2.6, dk=7.0, k=4.0)
    reading = read_shape(body, Kind.SCREW)
    assert (reading.size, reading.size_from_drive) == (Size.parse("M4"), False)
    fastener = found("M6 SHCS", body)
    assert (fastener.size, fastener.notes) == (Size.parse("M6"), ())


def test_a_head_s_round_never_sizes_against_the_name():
    # A Phillips over a tapered shank, its head 6 across: the head's round snaps to
    # M6, but no shank is drawn, and with no drive the name's M3 stands, quiet.
    head = Pos(0, 0, 1.2) * Cylinder(3.0, 2.4)
    cross = Pos(0, 0, 1.7) * (Box(3.2, 0.6, 1.41) + Box(0.6, 3.2, 1.41))
    body = head - cross + Pos(0, 0, -6) * Cone(0.5, 1.5, 12)
    reading = read_shape(body, Kind.SCREW)
    assert (reading.size, reading.shank_mm, reading.drive_af) == (Size.parse("M6"), None, None)
    fastener = found("M3 phillips screw", body)
    assert (fastener.size, fastener.notes) == (Size.parse("M3"), ())


def test_a_hex_head_is_said_as_a_hex():
    # An M6 bolt, 10 across and 6 through, under an M8 name.
    bolt = hexagon(10.0, 4.0) + Pos(0, 0, -10) * Cylinder(3.0, 20)
    fastener = found("M8 hex bolt", bolt)
    assert fastener.notes == (drawn_as("an M6", "6.00 shank, 10.00 hex", "M8"),)


def test_a_size_and_a_length_are_both_said_the_size_first():
    fastener = found("M5x12 SHCS", socket_screw(length=16.0))
    assert fastener.notes == (
        drawn_as("an M3", "3.00 shank, 2.50 socket", "M5"),
        "drawn 16.00 long under its head, where its name says 12: taken as drawn",
    )


def test_a_drive_that_settles_nothing_says_nothing():
    # ISO 4762 14 mm key fits M16 and M18; a shank at no size can't pick.
    reading = read_shape(socket_screw(shank=15.0, key=14.0, dk=24.0, k=16.0), Kind.SCREW)
    assert (reading.size, reading.drive_af) == (None, pytest.approx(14.0))
    fastener = found("M20 SHCS", socket_screw(shank=15.0, key=14.0, dk=24.0, k=16.0))
    assert (fastener.size, fastener.notes) == (Size.parse("M20"), ())


def test_a_screw_with_no_round_shank_is_held_to_its_drive_alone():
    # A head and socket over a tapered shank, as a tapping screw's is drawn: no round
    # under the head (the head's own isn't one), so the socket is the only word.
    head = Pos(0, 0, 1.5) * Cylinder(2.75, 3) - hexagon(2.5, 1.31, 1.7)
    body = head + Pos(0, 0, -8) * Cone(0.6, 1.5, 16)
    reading = read_shape(body, Kind.SCREW)
    assert (reading.shank_mm, reading.size, reading.size_from_drive) == (
        None,
        Size.parse("M3"),
        True,
    )
    fastener = found("M5x16 SHCS", body)
    assert fastener.size == Size.parse("M3")
    assert fastener.notes == (drawn_as("an M3", "2.50 socket", "M5"),)


def test_a_set_screw_s_thread_is_its_shank():
    # ISO 4026 M3: a 1.5 key in a 3 mm thread, all of it, under an M4 name.
    body = Pos(0, 0, -3) * Cylinder(1.5, 6) - hexagon(1.5, 1.51, -1.5)
    assert read_shape(body, Kind.SCREW).shank_mm == pytest.approx(3.0)
    fastener = found("M4x6 set screw", body)
    assert fastener.size == Size.parse("M3")
    assert fastener.notes == (drawn_as("an M3", "3.00 shank, 1.50 socket", "M4"),)


def test_a_head_s_round_is_no_shank():
    # The issue's M3x16 drawn as head and socket alone: its one round is its head's.
    head = Pos(0, 0, 1.5) * Cylinder(2.75, 3) - hexagon(2.5, 1.31, 1.7)
    body = head + Pos(0, 0, -8) * Cone(0.6, 1.5, 16)
    assert read_shape(body, Kind.SCREW).shank_mm is None
    assert read_shape(socket_screw(), Kind.SCREW).shank_mm == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Leadscrews, ball screws and their nuts.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Leadscrew Nut",
        "Lead Screw Nut",
        "lead_screw_nut_upper",
        "leadscrew_nut",
        "Ball Screw",
        "SFU1204 Ballscrew Nut",
        "T8 nut",
        "Tr8x8 brass nut",
        "TR10x2 nut",
        "Trapezoidal nut",
        "Anti-backlash nut",
        "ACME nut 1/2-10",
        "lead_screw",
    ],
)
def test_a_leadscrew_s_or_ball_screw_s_name_is_motion(name):
    hint = read_name(name)
    assert hint is not None
    assert hint.motion


@pytest.mark.parametrize(
    "name",
    [
        "M8 nut",
        "Flanged nut M8",
        "M5 T-nut",
        "M3 T8 torx screw",  # a T8 screw is a Torx screw as readily
        "T20 screw",
        "ball_end_screw",
        "M3x16 SHCS",
        "lead_bracket_bolt",
        "screw_lead",
    ],
)
def test_other_names_are_not(name):
    hint = read_name(name)
    assert hint is not None
    assert not hint.motion


def test_a_leadscrew_nut_is_passed_over_whatever_its_solid_shows():
    # The Voron Legacy's: a T8 flanged brass nut, round, bored 8. And one with a hex.
    flanged = Cylinder(11, 3.5) + Pos(0, 0, 7) * Cylinder(5, 11) - Cylinder(4, 40)
    hexed = hex_nut(af=13.0, bore=8.0, m=6.5)
    result = find(
        [
            Part("Leadscrew Nut", flanged),
            Part("T8 hex nut", hexed),
            Part("lead_screw_cover", Box(10, 10, 2)),
        ]
    )
    assert result.fasteners == ()
    passed = [(p.name, p.kind, p.reason) for p in result.passed_over]
    assert passed == [
        ("Leadscrew Nut", Kind.NUT, f"noun 'nut'; {MOTION}"),
        ("T8 hex nut", Kind.NUT, f"noun 'nut'; {MOTION}"),
    ]  # a cover is a cover, and not listed (issue #75)
    assert MOTION == (
        "named for a leadscrew or a ball screw, or the nut that runs on one: a motion "
        "part, which no tool turns"
    )


def test_a_leadscrew_nut_fails_no_run():
    flanged = Cylinder(11, 3.5) + Pos(0, 0, 7) * Cylinder(5, 11) - Cylinder(4, 40)
    report = check(Assembly([Part("Leadscrew Nut:1", flanged)]))
    assert report.results == ()
    assert report.exit_code == 0
    lines = report.terminal_lines()
    assert f"NOTE passed over Leadscrew Nut:1: noun 'nut'; {MOTION}" in lines
    assert any(
        "1 part named for a leadscrew or a ball screw, which no tool turns (passed over)" in line
        for line in lines
    )
    assert not any("named like a fastener" in line for line in lines)
