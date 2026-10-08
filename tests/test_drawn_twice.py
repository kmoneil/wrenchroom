"""Drawing faults that used to get a verdict as if the model were right (issue #94).

- A screw drawn into a part beside its head, which its way out meets: #63's
  "drawn into <part> (N mm^3): fix the model", not stuck.
- A fastener drawn twice, over itself (most of each one's volume in common): said
  once, on the first by name, naming the other, which isn't checked again.
- A name's length the solid disagrees with: noted, and the solid's taken, as it is
  what the way out meets.
"""

import json
import math

import pytest
from build123d import Box, Cone, Cylinder, Pos, RegularPolygon, extrude

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.detect import LENGTH_SLACK, LENGTH_SLACK_MM, find, read_shape
from wrenchroom.fasteners import Head, Kind
from wrenchroom.report import Verdict

M3 = {"kind": "screw", "head": "socket", "size": "M3"}


def hexagon(af, h, z0=0.0):
    return Pos(0, 0, z0) * extrude(RegularPolygon(af / math.sqrt(3), 6), h)


def screw(length=8.0):
    """ISO 4762 M3: a 5.5 by 3 head on z = 0..3, a 2.5 socket 1.3 deep, the shank below."""
    head = Pos(0, 0, 1.5) * Cylinder(2.75, 3) - hexagon(2.5, 1.31, 1.7)
    return head + Pos(0, 0, -length / 2) * Cylinder(1.5, length)


def plate(x=0.0):
    return Pos(x, 0, -5) * Box(30, 30, 10) - Pos(x, 0, 0) * Cylinder(1.5, 30)


def run(parts, rules, **kwargs):
    config = Config.from_dict({"fasteners": rules})
    report = check(Assembly([Part(n, s) for n, s in parts]), config, kit="metric-home", **kwargs)
    return {r.fastener.name: r for r in report.results}, report


# ---------------------------------------------------------------------------
# Drawn into what its way out meets.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", ["mesh", "exact"])
def test_a_screw_drawn_into_what_its_way_out_meets_is_a_clash(engine):
    # The issue's side box, 1 into the head's side: 2.957 mm^2 by 3, 8.9 mm^3.
    box = Pos(2.75 - 1 + 5, 0, 5) * Box(10, 10, 10)
    results, report = run(
        [("plate", plate()), ("screw", screw()), ("box", box)],
        [{"parts": "screw", **M3}],
        engine=engine,
    )
    result = results["screw"]
    assert (result.verdict, result.tool, result.reason) == (
        Verdict.NOT_COVERED,
        None,
        "drawn into box (8.9 mm^3): fix the model",
    )
    assert report.exit_code == 2


#: A box over the head, 0.5 above it, from 1.6 out: clear of the 2.5 key's shaft
#: (1.41 round) and in the head's way out (2.75 round), drawn into nothing.
OVER = Pos(1.6 + 5, 0, 3.5 + 5) * Box(10, 10, 10)


def test_a_part_in_its_way_out_it_isn_t_drawn_into_still_makes_it_stuck():
    results, _ = run(
        [("plate", plate()), ("screw", screw()), ("box", OVER)], [{"parts": "screw", **M3}]
    )
    assert (results["screw"].verdict, results["screw"].stuck_on) == (Verdict.STUCK, ("box",))


def test_only_what_the_way_out_meets_is_asked():
    # A box drawn 1 into the head's side under its top, which nothing meets, and the
    # box over it: only the second is in the way, and it isn't drawn in.
    near = Pos(2.75 - 1 + 5, 0, 1.5) * Box(10, 10, 2)
    parts = [("plate", plate()), ("screw", screw()), ("near", near), ("over", OVER)]
    results, _ = run(parts, [{"parts": "screw", **M3}])
    assert (results["screw"].verdict, results["screw"].stuck_on) == (Verdict.STUCK, ("over",))


# ---------------------------------------------------------------------------
# Drawn twice.
# ---------------------------------------------------------------------------


def dup_parts():
    return [("plate", plate()), ("M3x8 SHCS", screw()), ("M3x12 SHCS", screw())]


@pytest.mark.parametrize("engine", ["mesh", "exact"])
def test_a_screw_drawn_twice_is_said_once_on_the_first_naming_the_other(engine):
    results, report = run(dup_parts(), [{"parts": "M3x* SHCS", **M3}], engine=engine)
    assert list(results) == ["M3x12 SHCS"]
    result = results["M3x12 SHCS"]
    assert (result.verdict, result.tool) == (Verdict.NOT_COVERED, None)
    assert result.reason == (
        "drawn twice: M3x8 SHCS is drawn over it (120.8 mm^3 in common): fix the model"
    )
    assert report.summary["fasteners"] == 1
    assert report.exit_code == 2


def test_drawn_twice_detected_too():
    report = check(Assembly([Part(n, s) for n, s in dup_parts()]), kit="metric-home")
    (result,) = report.results
    assert result.reason.startswith("drawn twice: M3x8 SHCS is drawn over it")


def test_three_drawn_over_one_another_are_said_on_the_first():
    parts = [*dup_parts(), ("M3x16 SHCS", screw())]
    results, _ = run(parts, [{"parts": "M3x* SHCS", **M3}])
    # The first by name keeps one of the others; the third, drawn over the first too,
    # is dropped all the same.
    assert list(results) == ["M3x12 SHCS"]


def test_a_screw_and_the_nut_on_it_are_no_twins():
    nut = Pos(0, 0, -12) * (hexagon(5.5, 2.4) - Cylinder(1.25, 10))  # bored at the minor
    parts = [("plate", plate()), ("screw", screw(length=16)), ("nut", nut)]
    rules = [{"parts": "screw", **M3}, {"parts": "nut", "kind": "nut", "size": "M3"}]
    results, _ = run(parts, rules)
    assert set(results) == {"screw", "nut"}
    assert not any((r.reason or "").startswith("drawn twice") for r in results.values())


def test_two_screws_overlapping_by_less_than_half_are_no_twins():
    # The second 3 along: their heads share most of a lens, their shanks a sliver.
    parts = [("plate", plate()), ("one", screw()), ("two", Pos(3, 0, 0) * screw())]
    results, _ = run(parts, [{"parts": "one", **M3}, {"parts": "two", **M3}])
    assert set(results) == {"one", "two"}


def test_only_naming_the_one_drawn_over_reports_the_first():
    results, report = run(dup_parts(), [{"parts": "M3x* SHCS", **M3}], only="M3x8*")
    assert list(results) == ["M3x12 SHCS"]
    assert report.warnings == ()


# ---------------------------------------------------------------------------
# A name's length against the solid's.
# ---------------------------------------------------------------------------


def test_a_name_s_length_the_solid_disagrees_with_is_noted_and_the_solid_s_taken():
    (fastener,) = find([Part("M3x12 SHCS", screw(length=8.0))]).fasteners
    assert fastener.length_mm == 8.0
    assert fastener.notes == (
        "drawn 8.00 long under its head, where its name says 12: taken as drawn",
    )


@pytest.mark.parametrize(
    ("named", "drawn", "noted"),
    [
        (8, 8.0, False),
        (8, 8.5, False),  # within half a millimetre
        (8, 8.6, True),
        (20, 21.0, False),  # within 5%
        (20, 21.1, True),
    ],
)
def test_the_slack_is_half_a_millimetre_or_five_percent(named, drawn, noted):
    assert (LENGTH_SLACK_MM, LENGTH_SLACK) == (0.5, 0.05)
    (fastener,) = find([Part(f"M3x{named} SHCS", screw(length=drawn))]).fasteners
    assert bool(fastener.notes) is noted
    assert fastener.length_mm == (round(drawn, 2) if noted else named)


def flat_screw(length):
    """ISO 10642 M3: a 90 degree cone head 6 across, a 2 socket; ``length`` overall."""
    k = 1.5
    head = Pos(0, 0, -k / 2) * Cone(1.5, 3.0, k) - hexagon(2.0, 1.11, -1.1)
    return head + Pos(0, 0, -k - (length - k) / 2) * Cylinder(1.5, length - k)


def test_a_countersunk_head_s_length_is_overall():
    reading = read_shape(flat_screw(10.0), Kind.SCREW)
    assert reading.head is Head.FLAT
    assert reading.length_mm == pytest.approx(10.0)
    (fastener,) = find([Part("M3x10 FHCS", flat_screw(10.0))]).fasteners
    assert fastener.notes == ()


def test_a_set_screw_s_length_is_overall():
    body = Pos(0, 0, -2) * Cylinder(1.5, 4) - hexagon(1.5, 1.51, -1.5)
    assert read_shape(body, Kind.SCREW).length_mm == pytest.approx(4.0)


def test_a_head_whose_standard_may_measure_either_way_is_not_compared():
    # A cross in a round head: pan heads measure under, countersunk ones overall.
    head = Pos(0, 0, 1.5) * Cylinder(3.5, 3) - Pos(0, 0, 2.5) * (
        Box(4, 0.8, 2.1) + Box(0.8, 4, 2.1)
    )
    pan = head + Pos(0, 0, -4) * Cylinder(1.5, 8)
    assert read_shape(pan, Kind.SCREW).length_mm is None
    (fastener,) = find([Part("M3x12 phillips screw", pan)]).fasteners
    assert (fastener.length_mm, fastener.notes) == (12.0, ())


def test_a_name_with_no_length_gets_none_from_the_solid():
    (fastener,) = find([Part("ISO 4762 M3", screw(length=8.0))]).fasteners
    assert (fastener.length_mm, fastener.notes) == (None, ())


def test_the_length_taken_is_the_one_reported():
    report = check(Assembly([Part("plate", plate()), Part("M3x12 SHCS", screw())]))
    (entry,) = json.loads(report.json_text())["fasteners"]
    assert entry["length"] == 8.0
    assert entry["notes"] == [
        "drawn 8.00 long under its head, where its name says 12: taken as drawn"
    ]


def test_a_small_fastener_drawn_inside_a_big_one_is_no_twin():
    # An M3x4 set screw drawn wholly inside an M10 bolt's head: all of the small one
    # in common, little of the big. Twins share most of each; this is a clash.
    big = Pos(0, 0, 3.2) * hexagon(16, 6.4) + Pos(0, 0, -15) * Cylinder(5, 30)
    small = Pos(0, 0, 4) * (Cylinder(1.5, 4) - hexagon(1.5, 1.51, 0.5))
    parts = [("plate", Pos(0, 0, -5) * Box(60, 60, 10) - Cylinder(5, 30)), ("bolt", big)]
    parts.append(("set", small))
    rules = [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M10"},
        {"parts": "set", "kind": "screw", "head": "set", "size": "M3"},
    ]
    results, _ = run(parts, rules)
    assert set(results) == {"bolt", "set"}
    assert not any((r.reason or "").startswith("drawn twice") for r in results.values())
