"""A plug's receptacle drawn as several solids is one receptacle (issue #200).

A housing in two halves, or a header and its pins, is one part of several solids. Read
from STEP it is its largest solid, which keeps the name, and ``name#2`` pieces, and
each solid was tried as a receptacle of its own. Found by geometry, two solids of the
one part held the plug alike, so it was not covered: ``jack and jack#2 hold it alike:
say which it plugs into (receptacle:)``. Named as that asks, ``receptacle: jack``
matched the largest solid alone, which doesn't hold the plug as the housing does:
``jack lets it go 2 ways``. The same parts given whole unplugged.

Now a part's solids hold the plug together, a glob that names the part takes them all,
and the report names the part once. A glob that names a piece itself is that solid
alone, and two parts that only share a name are two receptacles still.
"""

import pytest
from build123d import Box, Compound, Pos

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.connectors import ConnectorVerdict
from wrenchroom.engine import ENGINES
from wrenchroom.view import view_data

UP = (0.0, 0.0, 1.0)


def in_pieces(named):
    """The assembly a STEP file of these parts gives, with no file written: a part of
    several solids is its largest, and its pieces."""
    shapes = []
    for name, shape in named:
        shape.label = name
        shapes.append(shape)
    return Assembly.from_compound(Compound(children=shapes))


READERS = pytest.mark.parametrize(
    "reader", [in_pieces, Assembly.from_shapes], ids=["in-pieces", "whole"]
)


def shroud():
    """A receptacle 20 by 12 by 10, its top at z = 10, a cavity 16 by 8 sunk 7 in it."""
    return Pos(0, 0, 5) * Box(20, 12, 10) - Pos(0, 0, 6.5) * Box(16, 8, 7.01)


def halves():
    """The shroud cut in two across its length: the left half the larger."""
    left = shroud() & (Pos(-5.5, 0, 5) * Box(11, 14, 12))
    right = shroud() & (Pos(5.5, 0, 5) * Box(9, 14, 12))
    return left.solid(), right.solid()


def plugged(jack=None):
    """A board, a jack on it, and a plug 7 into the jack, standing to z = 23."""
    board = Pos(0, 0, -1) * Box(100, 100, 2)
    plug = Pos(0, 0, 13) * Box(16, 8, 20)
    return [("board", board), ("jack", jack or Compound(list(halves()))), ("plug", plug)]


def connector(**rule):
    return Config.from_dict({"connectors": [{"parts": "plug", **rule}]})


def seated(report):
    """The plug as (verdict, receptacle, axis, travel, blockers, reason)."""
    (plug,) = report.connectors.results
    return plug.verdict, plug.receptacle, plug.axis, plug.travel, plug.blockers, plug.reason


OFF = (ConnectorVerdict.UNPLUGS, ("jack",), UP, 10.0, (), None)


@READERS
@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("rule", [{}, {"receptacle": "jack"}], ids=["found", "named"])
def test_a_housing_in_two_halves_is_one_receptacle(reader, engine, rule):
    report = check(reader(plugged()), connector(**rule), engine=engine)
    assert seated(report) == OFF
    # A part named like a connector is listed, but for a receptacle: this is one.
    assert report.connectors.named == ()


def test_the_report_names_the_part_once_and_the_view_draws_all_of_it():
    report = check(in_pieces(plugged()), connector())
    assert report.connectors.to_json()["results"][0]["receptacle"] == ["jack"]
    data = view_data(report)
    (plug,) = data["connectors"]["found"]
    assert [data["parts"][index]["name"] for index in plug["receptacle"]] == ["jack", "jack#2"]


def test_a_receptacle_glob_naming_a_piece_is_that_solid_alone():
    # The smaller half alone lets the plug go sideways as well, and says so by its name.
    report = check(in_pieces(plugged()), connector(receptacle="jack#2"))
    assert seated(report)[::5] == (
        ConnectorVerdict.NOT_COVERED,
        "jack#2 lets it go 2 ways (-x, +z): say which way it comes off (axis:)",
    )


def namesakes():
    """The two halves as two parts, each named jack: the second is numbered, and no piece."""
    board, _, plug = plugged()
    left, right = halves()
    return in_pieces([board, ("jack", left), ("jack", right), plug])


def test_two_parts_that_only_share_a_name_are_two_receptacles_still():
    model = namesakes()
    assert [(part.name, part.piece_of) for part in model][1:3] == [
        ("jack", None),
        ("jack#2", None),
    ]
    assert seated(check(model, connector()))[5] == (
        "jack and jack#2 hold it alike: say which it plugs into (receptacle:)"
    )
    assert seated(check(model, connector(receptacle="jack")))[5] == (
        "jack lets it go 2 ways (+x, +z): say which way it comes off (axis:)"
    )


@READERS
def test_a_receptacle_s_other_solid_leaves_the_plug_s_way_with_it(reader):
    # The whole shroud, and a bar of the same part across the plug's path, 5 over its
    # top and touching it nowhere: the part is the receptacle, bar and all, as it is
    # when given whole, and no part of its receptacle is in a plug's way (a latch's
    # hook, a key over it). A bar that is another part's stops the plug. Its travel is
    # out of its socket, 7 and 3 more: the bar holds it across in no way (issue #225).
    # It was to clear the bar too, from its foot at 3 past the bar's top at 30.
    bar = Pos(0, 0, 29) * Box(30, 4, 2)
    of_the_jack = plugged(Compound([shroud().solid(), bar.solid()]))
    assert seated(check(reader(of_the_jack), connector())) == (
        ConnectorVerdict.UNPLUGS,
        ("jack",),
        UP,
        10.0,
        (),
        None,
    )
    another_s = [*plugged(shroud()), ("clip", bar)]
    assert seated(check(reader(another_s), connector()))[::4] == (
        ConnectorVerdict.STUCK,
        ("clip",),
    )


@READERS
def test_a_part_of_two_solids_a_plug_only_rests_on_is_named_once(reader):
    # Standing on a board of two tiles, in no jack at all.
    tiles = Compound(
        [(Pos(-30, 0, 2) * Box(60, 100, 2)).solid(), (Pos(25, 0, 2) * Box(50, 100, 2)).solid()]
    )
    model = reader([("board", tiles), ("plug", Pos(0, 0, 13) * Box(16, 8, 20))])
    assert seated(check(model, connector()))[::5] == (
        ConnectorVerdict.NOT_COVERED,
        "it only rests against board, plugged into none: say what it plugs into (receptacle:)",
    )


@READERS
def test_a_neighbour_of_two_solids_does_not_outdo_the_jack(reader):
    # A block of two solids beside the plug, each touching one side of it: together they
    # hold it one way, and the jack, whole, holds it in four.
    beside = Compound(
        [(Pos(0, 9, 18) * Box(16, 10, 8)).solid(), (Pos(0, 9, 12.5) * Box(16, 10, 3)).solid()]
    )
    model = reader([*plugged(shroud()), ("block", beside)])
    plug = seated(check(model, connector()))
    assert plug[:2] == (ConnectorVerdict.UNPLUGS, ("jack",))
