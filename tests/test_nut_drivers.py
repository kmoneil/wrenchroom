"""Nut drivers (spec 6.3), full kit: a socket on a screwdriver's shaft, turned in place.

One straight clearance test after every spanner and socket way has failed; ruled
out, as a socket is, by a cable through the fastener. Worked cases: an M6 nut at the
foot of a tube, bore r 11 for 100 then r `upper` above.
"""

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.solids import AxialCylinder, AxialRing
from wrenchroom.tools.kits import FULL, IMPERIAL_HOME, METRIC_HOME
from wrenchroom.tools.nut_drivers import BLADE_LENGTH, NUT_DRIVERS, nut_driver_solid
from wrenchroom.tools.sockets import BORE_DEPTH, socket_wall
from wrenchroom.tools.spanners import corner_sweep
from wrenchroom.tools.sweep import CONTACT_OFFSET

RULE = {"parts": "nut", "kind": "nut", "size": "M6"}


def in_a_tube(upper=40.0):
    """An M6 nut (af 10, 5 tall) on a plate at the foot of a 400 tall tube."""
    tube = (
        Pos(0, 0, 200) * Box(200, 200, 400)
        - Pos(0, 0, 50) * Cylinder(11, 100.02)
        - Pos(0, 0, 250.5) * Cylinder(upper, 301)
    )
    nut = hex_prism(10, 5) - Cylinder(3, 20)
    return Assembly(
        [Part("nut", nut), Part("plate", Pos(0, 0, -5) * Box(300, 300, 10)), Part("tube", tube)]
    )


def run(assembly, rule=RULE, kit="full", engine="exact", **kwargs):
    config = Config.from_dict({"fasteners": [rule], "checks": {"detect": False}})
    (result,) = check(assembly, config, kit=kit, engine=engine, **kwargs).results
    return result


def test_the_drivers_are_the_larger_of_two_makers():
    # (Wera 395 socket OD, Wiha 341 socket OD, Wiha handle diameter, handle length)
    makers = {
        4.0: (6.9, 6.9, 30, 111),  # issue #83
        5.0: (8.1, 7.9, 30, 111),
        5.5: (8.1, 7.9, 30, 111),
        7.0: (11.0, 10.9, 36, 118),
        8.0: (12.1, 11.9, 36, 118),
        10.0: (14.1, 14.4, 36, 118),
        13.0: (18.1, 18.4, 41, 124),
    }
    assert sorted(NUT_DRIVERS) == sorted(makers)
    for af, (wera, wiha, handle_d, handle_l) in makers.items():
        driver = NUT_DRIVERS[af]
        assert driver.outer_radius == max(wera, wiha) / 2
        assert (driver.handle_radius, driver.handle_length) == (handle_d / 2, handle_l)
        assert driver.name == f"nut-driver-{af:g}"


def test_the_solid_is_mouth_blade_and_handle_end_to_end():
    driver = NUT_DRIVERS[10.0]
    band = (0.0, -5.0)
    corners, wall, mouth, blade, handle = nut_driver_solid(driver, 10.0, band).primitives
    (expected_corners,) = corner_sweep(10.0, band).primitives
    (expected_wall,) = socket_wall(10.0, driver.outer_radius, band).primitives
    assert (corners, wall) == (expected_corners, expected_wall)
    assert (wall.z0, wall.z1) == pytest.approx((-5.0, CONTACT_OFFSET))  # round the hex
    assert isinstance(mouth, AxialRing)
    assert (mouth.outer, mouth.z0, mouth.z1) == (7.2, CONTACT_OFFSET, CONTACT_OFFSET + BORE_DEPTH)
    assert mouth.inner == pytest.approx(10 / 3**0.5 + 0.3)
    assert blade == AxialCylinder(7.2, CONTACT_OFFSET + BORE_DEPTH, CONTACT_OFFSET + BLADE_LENGTH)
    handle_from = CONTACT_OFFSET + BLADE_LENGTH
    assert handle == AxialCylinder(18.0, handle_from, handle_from + 118)


def test_only_the_full_kit_holds_nut_drivers():
    assert FULL.nut_drivers == ("4", "5", "5.5", "7", "8", "10", "13")
    assert METRIC_HOME.nut_drivers == IMPERIAL_HOME.nut_drivers == ()


def test_at_the_foot_of_a_tube_only_the_nut_driver_turns_it(engine):
    result = run(in_a_tube(), engine=engine)
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "nut-driver-10",
        "nut driver straight in",
    )
    ways = [a.way for a in result.attempts]
    assert ways[-1] == "nut driver straight in"  # tried last, after every socket way
    assert "socket, 250 mm extension" in ways
    assert all(not a.turns for a in result.attempts[:-1])


def test_the_home_kit_cannot_get_down_the_tube():
    result = run(in_a_tube(), kit="metric-home")
    assert result.verdict is Verdict.BLOCKED
    assert result.blockers == ("tube",)
    assert {a.tool for a in result.attempts} == {"spanner-10", "socket-10"}


def test_a_cable_through_it_rules_the_nut_driver_out():
    result = run(in_a_tube(), {**RULE, "socket": False})
    assert result.verdict is Verdict.BLOCKED
    assert {a.tool for a in result.attempts} == {"spanner-10"}


def test_its_fist_needs_room_with_hand_room_on():
    # Upper bore r 30: the handle (r 18) fits, the fist round it (r 35) doesn't.
    assert run(in_a_tube(upper=30.0)).verdict is Verdict.TURNS
    result = run(in_a_tube(upper=30.0), hand_room=True)
    assert result.verdict is Verdict.BLOCKED
    assert result.reason == "no room for a hand: the hand hits tube"


@pytest.mark.parametrize(
    ("tool", "reason"),
    [
        ("nut-driver-10", None),
        ("nut-driver-9", "no nut driver sized 9: the tables hold 5.5 to 13"),
    ],
)
def test_a_forced_nut_driver(tool, reason):
    result = run(in_a_tube(), {**RULE, "tool": tool})
    assert result.reason == reason
    if reason is None:
        assert (result.verdict, result.tool) == (Verdict.TURNS, tool)


def test_a_forced_nut_driver_must_be_in_the_kit():
    result = run(in_a_tube(), {**RULE, "tool": "nut-driver-10"}, kit="metric-home")
    assert result.reason == "needs nut-driver-10, which kit metric-home does not hold (full has it)"
