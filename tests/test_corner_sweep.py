"""Every tool on a hex's flats tests what the hex itself sweeps, and what it stands in.

Two things a tool on the flats needs that only the open end used to test:

- the hex's own corner sweep: from its flats out to its corners (plus the ring's
  clearance), over its height. A part in it stops the hex turning whatever grips
  it, and a ring's bore or a socket's mouth stands outside it and hid it;
- a socket's wall round the hex, over the hex's height: a socket slides down over
  the hex, but was drawn from the nut's top face up, so a rib beside a nut, no
  taller than it, let a socket "turn" a nut no socket could get onto.

The cases: an M8 nut (af 13, corners 7.505 from the axis, 6.8 tall) on a plate,
its corners along x and so its flats facing +y and -y (6.5 off), beside a rib or
a lip facing a flat.
"""

import math

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.solids import AxialRing
from wrenchroom.tools.nut_drivers import NUT_DRIVERS, nut_driver_solid
from wrenchroom.tools.sockets import socket_for, socket_wall
from wrenchroom.tools.spanners import RING_CLEARANCE, corner_sweep
from wrenchroom.tools.sweep import CONTACT_OFFSET

NUT = {"parts": "nut", "kind": "nut", "size": "M8"}
CORNER = 13 / math.sqrt(3)  # 7.505


def beside(part, *, nut_h=6.8):
    """The nut on a plate, with ``part`` beside it."""
    nut = hex_prism(13, nut_h) - Cylinder(4, 30)
    return Assembly(
        [Part("nut", nut), Part("plate", Pos(0, 0, -5) * Box(200, 200, 10)), Part("side", part)]
    )


def rib(face_y, height):
    """A rib along x facing a flat, its face ``face_y`` from the axis, ``height`` tall."""
    return Pos(0, face_y + 5, height / 2) * Box(60, 10, height)


def run(assembly, rule=NUT, kit="full", engine="exact"):
    config = Config.from_dict({"fasteners": [rule], "checks": {"detect": False}})
    (result,) = check(assembly, config, kit=kit, engine=engine).results
    return result


# ---------------------------------------------------------------------------
# The pieces.
# ---------------------------------------------------------------------------


def test_the_corner_sweep_runs_from_the_flats_to_the_corners_over_the_hex():
    (piece,) = corner_sweep(13.0, (0.0, -6.8)).primitives
    assert piece == AxialRing(6.5, CORNER + RING_CLEARANCE, -6.8, 0.0)


def test_a_socket_s_wall_stands_round_the_hex_up_to_its_bore():
    socket = socket_for(13.0)
    (wall,) = socket_wall(13.0, socket.outer_radius, (0.0, -6.8)).primitives
    assert (wall.inner, wall.outer) == (CORNER + RING_CLEARANCE, socket.outer_radius)
    assert (wall.z0, wall.z1) == pytest.approx((-6.8, CONTACT_OFFSET))


def test_a_nut_driver_has_both():
    driver = NUT_DRIVERS[13.0]
    pieces = nut_driver_solid(driver, 13.0, (0.0, -6.8)).primitives
    (corners,) = corner_sweep(13.0, (0.0, -6.8)).primitives
    (wall,) = socket_wall(13.0, driver.outer_radius, (0.0, -6.8)).primitives
    assert pieces[:2] == (corners, wall)


# ---------------------------------------------------------------------------
# A low lip against a flat: inside the corner sweep, below the ring.
# ---------------------------------------------------------------------------


def test_a_low_lip_against_a_flat_stops_the_hex_whatever_grips_it(engine):
    # A short lip 0.5 off a flat (y 7.0 to 7.6, x -1.5 to 1.5), 0.6 tall: at most
    # 7.75 from the axis, inside every tool's bore (7.8) and under the ring, which
    # sits on the hex's middle, but inside the corners' 7.5 too. The hex can't turn
    # past it, so no tool turns it: every attempt meets it, by the corner sweep alone.
    lip = Pos(0, 7.3, 0.3) * Box(3.0, 0.6, 0.6)
    result = run(beside(lip), engine=engine)
    assert result.verdict is Verdict.BLOCKED
    tools = {a.tool for a in result.attempts}
    assert tools == {"spanner-13", "socket-13", "nut-driver-13"}
    assert all(a.blockers == ("side",) for a in result.attempts)


def test_a_lip_past_the_corners_lets_the_hex_turn():
    # A long lip 1.0 past the corners' sweep (y 8.81 on): the ring, which sits over
    # the lip's top, turns it.
    lip = Pos(0, CORNER + RING_CLEARANCE + 1.0 + 2, 0.3) * Box(60, 4, 0.6)
    result = run(beside(lip))
    assert (result.verdict, result.how) == (Verdict.TURNS, "ring, full length")


# ---------------------------------------------------------------------------
# A rib beside the nut, no taller than it: the socket's wall.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("face_x", "socket_turns"),
    [
        (7.0, False),  # 0.5 off the flats, inside the corners: nothing turns it
        (8.5, False),  # clear of the corners' 7.8, inside the socket's wall (r 9.0)
        (9.5, True),  # clear of the socket
    ],
)
def test_a_rib_no_taller_than_the_nut_and_the_socket_s_wall(engine, face_x, socket_turns):
    result = run(beside(rib(face_x, 4.0)), engine=engine)
    socket = [a for a in result.attempts if a.tool == "socket-13"]
    assert socket
    assert any(a.turns for a in socket) is socket_turns
    if not socket_turns:
        assert all(a.blockers == ("side",) for a in socket)
    driver = [a for a in result.attempts if a.tool == "nut-driver-13"]
    if face_x < 9.5:  # the nut driver's socket, r 9.2, stands in the same place
        assert driver
        assert all(a.blockers == ("side",) for a in driver)


@pytest.mark.parametrize("tool", ["socket-13", "nut-driver-13"])
def test_a_forced_socket_or_nut_driver_meets_the_rib_too(tool):
    result = run(beside(rib(8.5, 4.0)), {**NUT, "tool": tool})
    assert result.verdict is Verdict.BLOCKED
    assert result.blockers == ("side",)


@pytest.mark.parametrize("tool", ["socket-13", "nut-driver-13", "spanner-13"])
def test_a_forced_tool_on_a_hex_too_thin_to_grip_is_not_covered(tool):
    # A hex 0.4 tall: nothing to grip, whichever tool is named (the socket and the
    # nut driver used to skip the band and go on).
    result = run(beside(rib(30.0, 4.0), nut_h=0.4), {**NUT, "tool": tool})
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == "could not measure the hex's height"


def test_a_hex_head_s_socket_stands_round_the_head():
    # An M8 hex bolt (head af 13, 5.3 tall) up through the plate, a rib 2.0 off
    # its head's flats and lower than the head: the socket's wall meets it.
    bolt = Pos(0, 0, -10) * Cylinder(4, 20) + hex_prism(13, 5.3)
    assembly = Assembly(
        [
            Part("bolt", bolt),
            Part("plate", Pos(0, 0, -5) * Box(200, 200, 10) - Cylinder(4.5, 11)),
            Part("side", rib(8.5, 3.0)),
        ]
    )
    rule = {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8", "tool": "socket-13"}
    result = run(assembly, rule)
    assert (result.verdict, result.blockers) == (Verdict.BLOCKED, ("side",))
