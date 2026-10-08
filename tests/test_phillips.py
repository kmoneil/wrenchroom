"""Phillips recess numbers by thread, and the PH4 driver M8 and M10 take (issue #101).

ISO 7045 (pan), 7046-1 and 7046-2 (countersunk) and 7047 (raised countersunk) agree
size for size, in each one's Table 1: PH0 to M2, PH1 to M3, PH2 to M5, PH3 at M6, PH4
at M8 and M10.
"""

import pytest
from build123d import Box, Cylinder, Pos

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.detect import find
from wrenchroom.fasteners import PHILLIPS_NUMBER, Head
from wrenchroom.report import Verdict
from wrenchroom.tools.drivers import SHAFT_RADIUS
from wrenchroom.tools.kits import FULL, IMPERIAL_HOME, METRIC_HOME


def test_the_metric_numbers_are_iso_7045_s():
    metric = {size: number for size, number in PHILLIPS_NUMBER.items() if size.startswith("M")}
    assert metric == {
        "M1.6": 0,
        "M2": 0,
        "M2.5": 1,
        "M3": 1,
        "M3.5": 2,
        "M4": 2,
        "M5": 2,
        "M6": 3,
        "M8": 4,
        "M10": 4,
    }


def test_every_number_the_table_gives_has_a_driver():
    assert {f"ph{n}" for n in PHILLIPS_NUMBER.values()} <= set(SHAFT_RADIUS)


def test_the_ph4_driver_is_10_round_and_only_the_full_kit_has_it():
    assert SHAFT_RADIUS["ph4"] == 5.0
    assert SHAFT_RADIUS["ph4"] > SHAFT_RADIUS["ph3"]
    assert FULL.holds("driver-ph4")
    assert not METRIC_HOME.holds("driver-ph4")
    assert not IMPERIAL_HOME.holds("driver-ph4")


def pan(d=8.0, dk=16.0, k=6.0, arm=9.0, width=1.8, depth=4.0):
    """An ISO 7045 pan head, a cross in its top, its shank under z = 0."""
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    cross = Pos(0, 0, k - depth / 2) * (
        Box(arm, width, depth + 0.01) + Box(width, arm, depth + 0.01)
    )
    return head - cross + Pos(0, 0, -8) * Cylinder(d / 2, 16)


def plate(radius=4.5):
    return Pos(0, 0, -5) * Box(60, 60, 10) - Cylinder(radius, 30)


@pytest.mark.parametrize("size", ["M8", "M10"])
def test_an_m8_or_m10_phillips_turns_with_ph4(size):
    d = float(size[1:])
    rule = {"parts": "screw", "kind": "screw", "head": "phillips", "size": size}
    parts = [Part("plate", plate(d / 2 + 0.5)), Part("screw", pan(d=d, dk=2 * d))]
    report = check(Assembly(parts), Config.from_dict({"fasteners": [rule]}), kit="full")
    (result,) = report.results
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "driver-ph4",
        "driver straight in",
    )


def test_a_home_kit_says_it_needs_ph4():
    rule = {"parts": "screw", "kind": "screw", "head": "phillips", "size": "M8"}
    parts = [Part("plate", plate()), Part("screw", pan())]
    report = check(Assembly(parts), Config.from_dict({"fasteners": [rule]}))
    (result,) = report.results
    assert (result.verdict, result.reason) == (
        Verdict.NOT_COVERED,
        "needs driver-ph4, which kit metric-home does not hold (full has it)",
    )


@pytest.mark.parametrize(("bore", "turns"), [(4.9, False), (5.6, True)])
def test_the_ph4_shaft_is_10_round(bore, turns):
    # A collar over the head, bored 9.8 or 11.2 across: the 10 mm shaft goes down the
    # wider only. (The head, 16 across, can't come out past it: the screw is stuck.)
    collar = Pos(0, 0, 6 + 10) * (Cylinder(20, 20) - Cylinder(bore, 21))
    rule = {"parts": "screw", "kind": "screw", "head": "phillips", "size": "M8"}
    parts = [Part("plate", plate()), Part("screw", pan()), Part("collar", collar)]
    report = check(Assembly(parts), Config.from_dict({"fasteners": [rule]}), kit="full")
    (result,) = report.results
    (driver,) = result.attempts
    assert (driver.tool, driver.turns) == ("driver-ph4", turns)


def test_a_detected_m8_phillips_takes_ph4():
    (fastener,) = find([Part("M8x16 pan head phillips screw", pan())]).fasteners
    assert (fastener.head, fastener.size.designation) == (Head.PHILLIPS, "M8")
    report = check(
        Assembly([Part("plate", plate()), Part("M8x16 pan head phillips screw", pan())]), kit="full"
    )
    (result,) = report.results
    assert result.tool == "driver-ph4"
