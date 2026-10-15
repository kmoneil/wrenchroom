"""A round plug whose receptacle is open at a side off the model's axes (issue #227).

A round face stands for every way round its axis by two square to it, at right angles
(issue #222): for a plug along a model axis, the model's other two. A round plug in a
round jack open at its side, the plug's width, along one of those, is asked about: the
jack lets it go two ways. Open 20 or 45 degrees round, no way probed went into the
opening, and it read as coming off one way. A square plug's own faces face its
opening; a round plug has no face that says where it is.

The receptacle's do: its flat faces near the plug, square to its round faces' axes,
are an opening's sides, and their normals and the ways along them, both ways, are
probed too. The jack is the issue's: 30 across and 25 tall, its socket 26 across sunk
20 in it, the plug 26 across in the socket under a grip 30 across.
"""

import math

import pytest
from build123d import Box, Cylinder, Pos, Rot

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.connectors import (
    ConnectorVerdict,
    face_directions,
    receptacle_ways,
    said_direction,
)

UP = (0.0, 0.0, 1.0)


def jack(angle=None):
    """The issue's jack, open at its side the plug's width, ``angle`` round from +x."""
    found = Pos(0, 0, 12.5) * (Cylinder(15, 25) - Pos(0, 0, 2.5) * Cylinder(13, 20))
    if angle is not None:
        found = found - Rot(0, 0, angle) * (Pos(10, 0, 15) * Box(20, 26, 20))
    return found


def plug():
    return Pos(0, 0, 15) * Cylinder(13, 20) + Pos(0, 0, 45) * Cylinder(15, 40)


def board():
    return Pos(0, 0, -1) * Box(200, 100, 2)


def run(parts, engine="mesh", **rule):
    config = Config.from_dict({"connectors": [{"parts": "plug", **rule}]})
    (found,) = check(Assembly.from_shapes(parts), config, engine=engine).connectors.results
    return found


def toward(angle):
    """The way ``angle`` degrees round from +x, as a report says it."""
    return said_direction((math.cos(math.radians(angle)), math.sin(math.radians(angle)), 0.0))


# ---------------------------------------------------------------------------
# An opening at any side is seen.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("angle", [0, 20, 45, 150])
def test_a_round_plug_s_opening_at_any_side_is_asked_about(engine, angle):
    found = run([("board", board()), ("jack", jack(angle)), ("plug", plug())], engine)
    assert found.verdict is ConnectorVerdict.NOT_COVERED
    assert found.reason == (
        f"jack lets it go 2 ways (+z, {toward(angle)}): say which way it comes off (axis:)"
    )


def test_the_way_out_of_the_opening_is_said_with_no_minus_nought():
    # Its third figure was -0, as round it came out a hair under nought.
    assert toward(20) == "[0.94, 0.34, 0]"
    assert said_direction((-1e-9, 0.6, 0.8)) == "[0, 0.6, 0.8]"


def test_turned_off_every_axis_of_the_model_its_opening_is_seen_still(engine):
    turn = Rot(30, 20, 0)
    parts = [("board", board()), ("jack", jack(20)), ("plug", plug())]
    found = run([(name, turn * shape) for name, shape in parts], engine)
    assert found.verdict is ConnectorVerdict.NOT_COVERED
    assert found.reason.startswith("jack lets it go 2 ways (")


def test_an_axis_given_takes_it_off_that_way(engine):
    found = run([("board", board()), ("jack", jack(20)), ("plug", plug())], engine, axis="+z")
    assert (found.verdict, found.axis, found.travel) == (ConnectorVerdict.UNPLUGS, UP, 23.0)


def turned_block():
    """A block 40 square with the jack's socket bored in it, turned 20 about its axis:
    its flat sides face no way the plug's faces do."""
    block = Pos(0, 0, 12.5) * (Box(40, 40, 25) - Pos(0, 0, 2.5) * Cylinder(13, 20))
    return Rot(0, 0, 20) * block


def test_a_round_plug_in_a_turned_block_s_bore_comes_off_up(engine):
    # Its sides add four ways, and the bore holds it in each.
    parts = [("board", board()), ("jack", turned_block()), ("plug", plug())]
    assert len(receptacle_ways(plug(), [Part("jack", turned_block())], face_directions(plug())))
    found = run(parts, engine)
    assert (found.verdict, found.receptacle, found.axis, found.travel) == (
        ConnectorVerdict.UNPLUGS,
        ("jack",),
        UP,
        23.0,
    )


# ---------------------------------------------------------------------------
# The ways a receptacle's sides add.
# ---------------------------------------------------------------------------


def ways(shape, receptacle):
    return sorted(
        said_direction(way)
        for way in receptacle_ways(shape, [Part("jack", receptacle)], face_directions(shape))
    )


def test_an_opening_s_sides_add_their_normals_and_the_ways_along_them():
    # The sides of the opening at 20 face 110 and 290 round; along them, 20 and 200.
    assert ways(plug(), jack(20)) == sorted(toward(a) for a in (20, 110, 200, 290))


def test_sides_along_the_model_s_axes_add_none():
    # The plug's own faces face those ways already.
    assert ways(plug(), jack(0)) == []
    assert ways(plug(), Rot(0, 0, 90) * jack(0)) == []


def test_a_plug_with_no_round_face_takes_none():
    square = Pos(0, 0, 15) * Box(26, 26, 20) + Pos(0, 0, 45) * Box(30, 30, 40)
    assert ways(square, jack(20)) == []


def test_only_sides_near_the_plug_add_ways():
    # A side 20 round, out of reach of every probe, faces no way the plug can go.
    far = Rot(0, 0, 20) * (Pos(80, 0, 10) * Box(10, 10, 20))
    near = Rot(0, 0, 20) * (Pos(20, 0, 10) * Box(10, 10, 20))  # 2 off the grip's side
    assert ways(plug(), far) == []
    assert ways(plug(), near) == sorted(toward(a) for a in (20, 110, 200, 290))


def test_a_side_within_a_probe_step_of_the_plug_s_box_is_near():
    # A post's box 3.4 off the plug's, its sides 20 round: a 5 mm step reaches it.
    post = Pos(21, 0, 10) * (Rot(0, 0, 20) * Box(4, 4, 20))
    assert ways(plug(), post) == sorted(toward(a) for a in (20, 110, 200, 290))


def test_one_side_alone_adds_both_ways_along_it():
    # A disc cut flat 20 out from the plug's axis, 20 round: its one flat side faces the
    # plug, the rest of it round. Its normal both ways, and the way along it both ways,
    # with no other side to say the other.
    disc = Pos(50, 0, 10) * Cylinder(60, 20) - Pos(-20, 0, 10) * Box(80, 200, 30)
    assert ways(plug(), Rot(0, 0, 20) * disc) == sorted(toward(a) for a in (20, 110, 200, 290))
