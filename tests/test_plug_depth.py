"""How far a plug sits in its receptacle, however it is drawn to fit (issue #225).

A plug's travel is how far it sits in its receptacle, plus 3. How far it sits in was
how far it moved along its axis before it was 0.01 from the receptacle: right for a
plug drawn touching its socket's walls, which it stays within 0.01 of until it is out.
A plug drawn with room round it, as most connector models are, or tapered, is clear of
the walls as soon as it lifts: it sat in by nothing, its travel was 3, and a part over
it that it would meet coming out went unmet. With hand room on, its fingers started at
its foot, down in the socket.

It sits in now as far as it must move before its receptacle holds it in none of the
ways across its axis it held it in as drawn: out of its socket, it could be taken off
sideways.

The worked pair: a jack 30 square and 25 tall, its socket 26 square sunk 20 in it, and
a plug in the socket, 20 in, under a grip 30 square and 40 long; a shelf 10 over the
grip's top.
"""

import pytest
from build123d import Axis, Box, Compound, Cone, Cylinder, Pos, chamfer

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.connectors import ConnectorVerdict

UP = (0.0, 0.0, 1.0)
DEEP = 20.0  # how far the plug sits in its socket
TRAVEL = DEEP + 3.0


def jack():
    """The jack, its top at z = 25, its socket 26 square from z = 5 up."""
    return Pos(0, 0, 12.5) * (Box(30, 30, 25) - Pos(0, 0, 2.5) * Box(26, 26, 20))


def plug(room=0.0, lift=0.0):
    """The plug, ``room`` narrower than its socket and ``lift`` off its floor."""
    body = Pos(0, 0, 15 + lift) * Box(26 - room, 26 - room, 20 - lift)
    return body + Pos(0, 0, 45) * Box(30, 30, 40)


def shelf():
    return Pos(0, 0, 65 + 10 + 2.5) * Box(60, 60, 5)


def board():
    return Pos(0, 0, -1) * Box(200, 100, 2)


def run(parts, engine="mesh", **rule):
    """The plug's result, checked under a rule (``parts: plug`` and ``rule``)."""
    config = Config.from_dict({"connectors": [{"parts": "plug", **rule}]})
    report = check(Assembly.from_shapes(parts), config, engine=engine)
    (result,) = report.connectors.results
    return result


def said(result):
    return (result.verdict, result.receptacle, result.axis, result.travel, result.blockers)


# ---------------------------------------------------------------------------
# A plug with room round it sits as deep as one drawn tight.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("room", [0.0, 0.2, 1.0])
def test_a_plug_drawn_with_room_round_it_sits_as_deep_as_one_drawn_tight(engine, room):
    found = run([("board", board()), ("jack", jack()), ("plug", plug(room))], engine)
    assert said(found) == (ConnectorVerdict.UNPLUGS, ("jack",), UP, TRAVEL, ())


@pytest.mark.parametrize("room", [0.0, 0.2])
def test_a_part_over_it_stops_a_plug_drawn_with_room_as_one_drawn_tight(engine, room):
    # The issue's false pass: drawn loose, the shelf 10 over it went unmet.
    parts = [("board", board()), ("jack", jack()), ("plug", plug(room)), ("shelf", shelf())]
    assert said(run(parts, engine)) == (ConnectorVerdict.STUCK, ("jack",), UP, TRAVEL, ("shelf",))


def test_a_round_plug_with_room_round_it_sits_as_deep(engine):
    socket = Pos(0, 0, 12.5) * (Cylinder(15, 25) - Pos(0, 0, 2.5) * Cylinder(13, 20))
    loose = Pos(0, 0, 15) * Cylinder(12.9, 20) + Pos(0, 0, 45) * Cylinder(15, 40)
    found = run([("board", board()), ("jack", socket), ("plug", loose)], engine)
    assert said(found) == (ConnectorVerdict.UNPLUGS, ("jack",), UP, TRAVEL, ())


def test_a_tapered_plug_sits_as_deep_as_its_taper(engine):
    # A taper leaves its socket's walls at once: it sat in by nothing, travel 3.1.
    taper = Pos(0, 0, 15) * Cone(11, 13, 20)
    parts = [
        ("board", board()),
        ("jack", Pos(0, 0, 12.5) * Cylinder(15, 25) - taper),
        ("plug", taper + Pos(0, 0, 45) * Box(30, 30, 40)),
    ]
    assert said(run(parts, engine)) == (ConnectorVerdict.UNPLUGS, ("jack",), UP, TRAVEL, ())


def test_a_plug_touching_its_socket_nowhere_sits_in_it_still(engine):
    # Room round it and 0.1 off the floor: the socket is named, as it touches nothing.
    # It sits 19.9 in; it read as in by nothing, as it touched its receptacle nowhere.
    parts = [("board", board()), ("jack", jack()), ("plug", plug(room=0.2, lift=0.1))]
    found = run(parts, engine, receptacle="jack")
    assert said(found) == (ConnectorVerdict.UNPLUGS, ("jack",), UP, round(DEEP - 0.1 + 3, 1), ())


def test_a_plug_drawn_into_its_socket_sits_as_deep(engine):
    # Drawn 0.2 wider than its socket, a press fit: it overlaps the jack as drawn, and
    # is held across by what moving adds until it is out.
    found = run([("board", board()), ("jack", jack()), ("plug", plug(room=-0.2))], engine)
    assert said(found) == (ConnectorVerdict.UNPLUGS, ("jack",), UP, TRAVEL, ())


# ---------------------------------------------------------------------------
# Whatever holds it across, as long as it does.
# ---------------------------------------------------------------------------


def hooded(room):
    """A plug 16 by 8 in a shroud 20 by 12 (its top at 10, a socket 7 deep), with a
    hood 8 deep round the shroud's outside, ``room`` off it; a cap over both, to 23."""
    shroud = Pos(0, 0, 5) * Box(20, 12, 10) - Pos(0, 0, 10 - 3.5) * Box(16, 8, 7.01)
    body = Pos(0, 0, 13) * Box(16, 8, 20)
    hood = Pos(0, 0, 6) * (Box(24, 16, 8) - Box(20 + 2 * room, 12 + 2 * room, 8))
    cap = Pos(0, 0, 16.5) * Box(24, 16, 13)
    return [("board", board()), ("shroud", shroud), ("plug", body + hood + cap)]


@pytest.mark.parametrize("room", [0.0, 0.2])
def test_a_hood_round_its_shroud_keeps_it_in_until_the_hood_is_clear(engine, room):
    # Its body is 7 in the socket; its hood, 8 down the shroud's outside: it is out
    # once the hood is, 8 up. Drawn with room, the hood was clear at once, and its body
    # alone, 7, said how far it sat in.
    found = run(hooded(room), engine)
    assert said(found) == (ConnectorVerdict.UNPLUGS, ("shroud",), UP, 11.0, ())


@pytest.mark.parametrize("room", [0.0, 0.2])
def test_a_plug_sunk_deeper_than_it_is_long_comes_out_of_the_whole_tube(engine, room):
    # 5 long on the floor of a tube 30 deep: held across all the way up, out at 30.
    tube = Pos(0, 0, 15.5) * (Box(30, 30, 31) - Pos(0, 0, 0.5) * Box(26, 26, 30))
    short = Pos(0, 0, 3.5) * Box(26 - room, 26 - room, 5)
    found = run([("board", board()), ("tube", tube), ("plug", short)], engine)
    assert said(found) == (ConnectorVerdict.UNPLUGS, ("tube",), UP, 33.0, ())


def in_pieces(named):
    """The assembly a STEP file of these parts gives, with no file written: a part of
    several solids is its largest, and its pieces."""
    shapes = []
    for name, shape in named:
        shape.label = name
        shapes.append(shape)
    return Assembly.from_compound(Compound(children=shapes))


@pytest.mark.parametrize("reader", [in_pieces, Assembly.from_shapes], ids=["in-pieces", "whole"])
def test_a_receptacle_of_two_solids_holds_it_across_with_both(reader):
    # A base with a socket 5 deep, and a collar of the same part on it round the socket,
    # 10 higher: the plug is 15 in, and out once the collar is clear. Read in pieces,
    # the collar is a piece of the base's part, which holds it too.
    base = Pos(0, 0, 5) * (Box(40, 40, 10) - Pos(0, 0, 2.5) * Box(26, 26, 5))
    collar = Pos(0, 0, 15) * (Box(30, 30, 10) - Box(26, 26, 10))
    body = Pos(0, 0, 12.5) * Box(25.8, 25.8, 15) + Pos(0, 0, 40) * Box(30, 30, 40)
    parts = [("board", board()), ("jack", Compound([base.solid(), collar.solid()]))]
    config = Config.from_dict({"connectors": [{"parts": "plug"}]})
    report = check(reader([*parts, ("plug", body)]), config)
    (found,) = report.connectors.results
    assert said(found) == (ConnectorVerdict.UNPLUGS, ("jack",), UP, 18.0, ())


def test_a_plug_with_a_bevelled_foot_sits_as_deep(engine):
    # Its foot's bevels face out and down, slant to the axis: not ways across it. As
    # ways across, moved down and out by them it met the jack's rim once out, and sat
    # in deeper than it is.
    body = chamfer(Box(25.8, 25.8, 20).edges().group_by(Axis.Z)[0], 1.5)
    bevelled = Pos(0, 0, 15) * body + Pos(0, 0, 45) * Box(30, 30, 40)
    found = run([("board", board()), ("jack", jack()), ("plug", bevelled)], engine)
    assert said(found) == (ConnectorVerdict.UNPLUGS, ("jack",), UP, TRAVEL, ())


def test_a_plug_named_into_a_part_it_only_rests_on_is_out_as_it_moves(engine):
    # The board holds it one way, down, and none across: nothing it sits in.
    resting = Pos(0, 0, 10) * Box(16, 8, 20)
    found = run([("board", board()), ("plug", resting)], engine, receptacle="board", axis="+z")
    assert said(found) == (ConnectorVerdict.UNPLUGS, ("board",), UP, 3.0, ())


# ---------------------------------------------------------------------------
# Fingers start where the receptacle ends.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("grip", ["pinch", "hand"])
@pytest.mark.parametrize("room", [0.0, 0.2])
def test_fingers_on_a_plug_with_room_round_it_start_above_its_socket(grip, room):
    # A plain plug, no wider than its socket, standing 20 out of it: fingers either
    # side, or a fist round it, start where the jack ends. Drawn with room, they
    # started at its foot, down in the socket, and met the jack: no grip.
    plain = Pos(0, 0, 25) * Box(26 - room, 26 - room, 40)
    config = Config.from_dict(
        {"connectors": [{"parts": "plug", "grip": grip}], "checks": {"hand_room": True}}
    )
    parts = [("board", board()), ("jack", jack()), ("plug", plain)]
    (found,) = check(Assembly.from_shapes(parts), config).connectors.results
    assert (found.verdict, found.travel, found.blockers) == (ConnectorVerdict.UNPLUGS, TRAVEL, ())
