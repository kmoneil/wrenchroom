"""A round plug in a round receptacle (issue #222).

A plug's pull axis is found among the ways its faces face: each flat face's normal,
and each round face's axis. A round face's ways were its axis alone, so a round plug
in a round shroud was moved only along it, found held one way (its socket's floor),
and read as resting on its receptacle: ``it only rests against round_jack``. Circular
connectors, barrel jacks and any plug drawn as an envelope cylinder are round.

A round face faces every way round its axis. Its ways are now its axis and two ways
square to it, at right angles, each both ways: a round shroud holds a round plug in
five, as a square one holds a square plug, and it comes out the one way left. A cone
is a round face too (a tapered plug, a chamfer), and faced no way at all.

The issue's pair: a jack 30 across and 25 tall, its socket 26 across sunk 20 in it,
and a plug 26 across in the socket, 20 in, under a grip 30 across and 40 long; the
same drawn square beside it.
"""

import math

import pytest
from build123d import Axis, Box, Cone, Cylinder, Pos, Rot, fillet

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.connectors import ConnectorVerdict, face_directions, said_direction

UP = (0.0, 0.0, 1.0)


def jack(x, shape, slot=False):
    """The issue's jack, its top at z = 25; open at its +x side the plug's width if
    ``slot``, from its socket's floor up."""
    if shape == "round":
        found = Pos(x, 0, 12.5) * (Cylinder(15, 25) - Pos(0, 0, 2.5) * Cylinder(13, 20))
    else:
        found = Pos(x, 0, 12.5) * (Box(30, 30, 25) - Pos(0, 0, 2.5) * Box(26, 26, 20))
    if slot:
        found = found - Pos(x + 10, 0, 15) * Box(20, 26, 20)
    return found


def plug(x, shape, grow=0.0):
    """The issue's plug, 20 in its jack (z 5 to 25) under its grip (z 25 to 65)."""
    if shape == "round":
        return Pos(x, 0, 15) * Cylinder(13 + grow / 2, 20) + Pos(x, 0, 45) * Cylinder(15, 40)
    return Pos(x, 0, 15) * Box(26 + grow, 26 + grow, 20) + Pos(x, 0, 45) * Box(30, 30, 40)


def board():
    return Pos(0, 0, -1) * Box(200, 100, 2)


def pairs(slot=False, turn=None, grow=0.0):
    """The board, and the round pair at x = -40 beside the square one at x = 40."""
    parts = [("board", board())]
    for x, shape in ((-40, "round"), (40, "square")):
        parts += [(f"{shape}_jack", jack(x, shape, slot)), (f"{shape}_plug", plug(x, shape, grow))]
    if turn is not None:
        parts = [(name, turn * shape) for name, shape in parts]
    return parts


def run(parts, engine="mesh", connectors=None):
    """The report on parts given as (name, shape): plugs found by name, or by rules."""
    config = Config.from_dict({"connectors": connectors}) if connectors is not None else None
    return check(Assembly.from_shapes(parts), config, engine=engine)


def found(report):
    """Each connector as (verdict, receptacle, axis, travel, reason)."""
    return {
        c.name: (c.verdict, c.receptacle, c.axis, c.travel, c.reason)
        for c in report.connectors.results
    }


def said(shape):
    return [said_direction(direction) for direction in face_directions(shape)]


# ---------------------------------------------------------------------------
# The ways a round face faces.
# ---------------------------------------------------------------------------


def test_a_round_face_faces_along_its_axis_and_two_ways_square_to_it():
    # Its top and bottom say +z and -z again: each way is said once.
    assert said(Cylinder(5, 10)) == ["+z", "-z", "+y", "-y", "-x", "+x"]


def test_a_cone_faces_as_a_cylinder_does():
    assert said(Cone(11, 13, 20)) == ["+z", "-z", "+y", "-y", "-x", "+x"]


def test_a_round_face_lying_along_x_faces_the_other_two_axes_too():
    assert said(Rot(0, 90, 0) * Cylinder(5, 10)) == ["+x", "-x", "+z", "-z", "-y", "+y"]


def test_a_round_face_at_an_angle_faces_two_ways_square_to_its_axis_at_right_angles():
    directions = face_directions(Rot(30, 20, 0) * Cylinder(5, 10))
    assert len(directions) == 6
    axis, sideways = directions[0], directions[2:]
    assert directions[1] == pytest.approx(tuple(-c for c in axis))
    for direction in directions:
        assert math.fsum(c * c for c in direction) == pytest.approx(1.0)
    for direction in sideways:
        assert math.fsum(a * b for a, b in zip(axis, direction, strict=True)) == pytest.approx(
            0.0, abs=1e-12
        )
    across, other = sideways[0], sideways[2]
    assert sideways[1] == pytest.approx(tuple(-c for c in across))
    assert sideways[3] == pytest.approx(tuple(-c for c in other))
    assert math.fsum(a * b for a, b in zip(across, other, strict=True)) == pytest.approx(
        0.0, abs=1e-12
    )


def test_a_box_faces_its_six_ways_and_rounding_its_edges_adds_none():
    # A plug's rounded edges face the ways its flat faces do: nothing more to probe.
    box = Box(10, 6, 20)
    assert sorted(said(box)) == sorted(["+x", "-x", "+y", "-y", "+z", "-z"])
    rounded = fillet(box.edges().filter_by(Axis.Z), 2)
    assert sorted(said(rounded)) == sorted(said(box))


# ---------------------------------------------------------------------------
# A round plug in its receptacle, found as a square one is.
# ---------------------------------------------------------------------------


def test_the_issue_s_round_and_square_plugs_both_unplug_with_no_rule(engine):
    report = run(pairs(), engine)
    assert report.connectors.headline == "2 connectors: 2 unplug, 0 stuck, 0 not covered"
    assert found(report) == {
        "round_plug": (ConnectorVerdict.UNPLUGS, ("round_jack",), UP, 23.0, None),
        "square_plug": (ConnectorVerdict.UNPLUGS, ("square_jack",), UP, 23.0, None),
    }
    assert not [line for line in report.terminal_lines() if "named like a connector" in line]


def test_a_rule_naming_its_receptacle_says_the_same(engine):
    # The issue's way round it: now it changes nothing.
    rules = [{"parts": "round_plug", "receptacle": "round_jack"}, {"parts": "square_plug"}]
    assert found(run(pairs(), engine, rules)) == found(run(pairs(), engine))


def test_a_round_plug_open_at_its_side_goes_two_ways_as_a_square_one_does(engine):
    # Its socket runs out of the jack's +x side, the plug's width: it slides out
    # that way as well as up, and the check asks which.
    reasons = {name: entry[4] for name, entry in found(run(pairs(slot=True), engine)).items()}
    assert reasons == {
        f"{shape}_plug": (
            f"{shape}_jack lets it go 2 ways (+z, +x): say which way it comes off (axis:)"
        )
        for shape in ("round", "square")
    }
    given = [{"parts": "*_plug", "axis": "+z"}]
    assert {entry[0] for entry in found(run(pairs(slot=True), engine, given)).values()} == {
        ConnectorVerdict.UNPLUGS
    }


def test_a_round_plug_turned_comes_off_along_its_own_axis(engine):
    # Turned off every axis of the model, its two ways across are none of the model's.
    turn = Rot(30, 20, 0)
    report = run(pairs(turn=turn), engine)
    expected = tuple((turn * Pos(0, 0, 1)).position - turn.position)
    for name in ("round_plug", "square_plug"):
        verdict, receptacle, axis, travel, _ = found(report)[name]
        assert (verdict, receptacle) == (ConnectorVerdict.UNPLUGS, (name.replace("plug", "jack"),))
        assert axis == pytest.approx(expected, abs=1e-6)
        assert travel == pytest.approx(23.0, abs=1e-9)


def test_a_round_plug_drawn_into_its_jack_comes_off_up(engine):
    # Drawn 0.2 wider than its socket, a press fit: in its jack as drawn, and only
    # rising adds no overlap, round as square.
    for name, entry in found(run(pairs(grow=0.2), engine)).items():
        assert entry[:3] == (ConnectorVerdict.UNPLUGS, (name.replace("plug", "jack"),), UP)


def test_a_barrel_plug_over_its_jack_s_pin_comes_off_up(engine):
    # A barrel jack: the plug's sleeve in the jack's bore, round the jack's centre pin.
    jack_body = Pos(0, 0, 6) * (Cylinder(6, 12) - Pos(0, 0, 2) * Cylinder(4, 8)) + Pos(
        0, 0, 6
    ) * Cylinder(1, 12)
    sleeve = Pos(0, 0, 8) * (Cylinder(4, 8) - Cylinder(1, 8)) + Pos(0, 0, 22) * Cylinder(5, 20)
    parts = [("board", board()), ("barrel_jack", jack_body), ("barrel_plug", sleeve)]
    assert found(run(parts, engine))["barrel_plug"] == (
        ConnectorVerdict.UNPLUGS,
        ("barrel_jack",),
        UP,
        11.0,
        None,
    )


def test_a_tapered_plug_in_a_tapered_socket_comes_off_up(engine):
    # Cones and flat ends only: it read as resting on its jack. Its travel is 3.1, not
    # the 20 it sits in, as any plug's that its socket's walls don't touch (issue #225).
    taper = Pos(0, 0, 15) * Cone(11, 13, 20)
    tapered_jack = Pos(0, 0, 12.5) * Cylinder(15, 25) - taper
    parts = [
        ("board", board()),
        ("tapered_jack", tapered_jack),
        ("tapered_plug", taper + Pos(0, 0, 35) * Cone(13, 12, 20)),
    ]
    assert found(run(parts, engine))["tapered_plug"][:3] == (
        ConnectorVerdict.UNPLUGS,
        ("tapered_jack",),
        UP,
    )


def test_a_round_plug_on_a_board_still_only_rests_on_it(engine):
    # Moved across, it slides along the board: held one way, it plugs into nothing.
    resting = Pos(0, 0, 10) * Cylinder(13, 20)
    (entry,) = found(run([("board", board()), ("round_plug", resting)], engine)).values()
    assert entry[0] is ConnectorVerdict.NOT_COVERED
    assert entry[4] == (
        "it only rests against board, plugged into none: say what it plugs into (receptacle:)"
    )


def test_a_rounded_plug_turned_about_its_axis_still_comes_off_up(engine):
    # Its rounded edges, turned 30 degrees, face the model's axes and not its own
    # faces: four more ways to probe, each of which its shroud holds.
    turn = Rot(0, 0, 30)
    body = fillet(Box(26, 16, 20).edges().filter_by(Axis.Z), 3)
    shroud = Pos(0, 0, 12.5) * Box(30, 20, 25) - Pos(0, 0, 15) * Box(26, 16, 20.01)
    parts = [
        ("board", board()),
        ("jack", turn * shroud),
        ("plug", turn * (Pos(0, 0, 15) * body + Pos(0, 0, 45) * Box(30, 20, 40))),
    ]
    assert len(face_directions(parts[2][1])) > 6  # the ways it adds, the premise
    entry = found(run(parts, engine, [{"parts": "plug"}]))["plug"]
    assert entry[:4] == (ConnectorVerdict.UNPLUGS, ("jack",), UP, 23.0)
