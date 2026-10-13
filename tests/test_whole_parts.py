"""A part drawn as several solids goes whole wherever the sidecar names it (issue #198).

Read from STEP, such a part is its largest solid, which keeps the name, and ``name#2``
pieces (issue #28). An ignore glob took the pieces with their part, and so did a build
step's ``add:``. A state's ``remove:``, a rule's ``mates:`` and an ``allow:`` pair did
not: each matched a solid by its own name, so ``remove: [cover]`` took off the cover's
largest solid and left the rest of it over the screw, which stayed blocked by
``cover#2``, a name the model doesn't have and no sidecar would give.

Now the part's other solids go with it in all three, in the tool's scene, a plug's and
the clash list. A glob that names a piece itself takes that solid alone, and a part
that only shares the name (a repeat, numbered the same way) is no piece of it. The
same parts given whole, as ``from_shapes`` keeps them, read the same.
"""

import pytest
from build123d import Box, Compound, Cylinder, Pos, export_step

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check, find_clashes
from wrenchroom.config import Config
from wrenchroom.connectors import ConnectorVerdict
from wrenchroom.engine import ENGINES
from wrenchroom.report import Verdict
from wrenchroom.view import view_data

SCREW = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}


def as_step_reads(named):
    """The assembly a STEP file of these parts gives, with no file written: a part of
    several solids is its largest, and its pieces."""
    shapes = []
    for name, shape in named:
        shape.label = name
        shapes.append(shape)
    return Assembly.from_compound(Compound(children=shapes))


READERS = pytest.mark.parametrize(
    "reader", [as_step_reads, Assembly.from_shapes], ids=["in-pieces", "whole"]
)


def socket_screw():
    """An M6 socket head screw standing head up, its head's top at z = 26."""
    return Pos(0, 0, 10) * Cylinder(3, 20) + Pos(0, 0, 23) * Cylinder(5.5, 6)


def two_solids(over="piece", solids=2):
    """A slab off to the side and a pad 10 over the screw's head, solids of one part.

    The slab is the larger, so it keeps the part's name and the pad is its piece; with
    ``over="largest"`` they change places, and the solid over the screw is the named one.
    """
    aside, above = Pos(70, 0, 45), Pos(0, 0, 38)
    if over == "largest":
        aside, above = above, aside
    slab, pad = aside * Box(40, 80, 10), above * Box(30, 30, 4)
    more = [Pos(-70, 0, 40 + 10 * k) * Box(20, 20, 2) for k in range(solids - 2)]
    return Compound([slab.solid(), pad.solid(), *(extra.solid() for extra in more)])


def covered(cover=None):
    """A plate, the screw, and a cover of two solids, one of them over the screw's head."""
    plate = Pos(0, 0, -5) * Box(200, 100, 10)
    return [("plate", plate), ("bolt", socket_screw()), ("cover", cover or two_solids())]


def namesakes():
    """The same solids as two parts, each named cover: the second is numbered, and no piece."""
    plate = Pos(0, 0, -5) * Box(200, 100, 10)
    slab, pad = two_solids().solids()
    return as_step_reads(
        [("plate", plate), ("bolt", socket_screw()), ("cover", slab), ("cover", pad)]
    )


def cover_off(*globs):
    return {
        "fasteners": [SCREW],
        "states": {"cover-off": {"remove": list(globs)}},
        "checks": {"try_states": ["cover-off"]},
    }


def verdict(report):
    (result,) = report.results
    return result.verdict, result.state, result.blocked_by


# ---------------------------------------------------------------------------
# A state's remove:.
# ---------------------------------------------------------------------------


def test_read_in_pieces_the_cover_s_piece_is_what_blocks_the_screw():
    # The ground the rest stands on: the pad, cover#2, is in the key's way.
    model = as_step_reads(covered())
    assert [(part.name, part.piece_of) for part in model][2:] == [
        ("cover", None),
        ("cover#2", "cover"),
    ]
    assert verdict(check(model, Config.from_dict({"fasteners": [SCREW]}))) == (
        Verdict.BLOCKED,
        None,
        ("cover#2",),
    )


@READERS
@pytest.mark.parametrize("engine", ENGINES)
def test_a_state_takes_a_part_off_whole(reader, engine):
    report = check(reader(covered()), Config.from_dict(cover_off("cover")), engine=engine)
    assert verdict(report) == (Verdict.TURNS, "cover-off", ())
    assert (report.warnings, report.exit_code) == ((), 0)


def test_what_a_state_takes_off_names_each_solid():
    report = check(as_step_reads(covered()), Config.from_dict(cover_off("cover")))
    assert report.models["cover-off"].removed == {"cover", "cover#2"}


def test_a_part_of_three_solids_comes_off_whole():
    model = as_step_reads(covered(two_solids(solids=3)))
    report = check(model, Config.from_dict(cover_off("cover")))
    assert verdict(report) == (Verdict.TURNS, "cover-off", ())
    assert report.models["cover-off"].removed == {"cover", "cover#2", "cover#3"}


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ("piece", (Verdict.TURNS, "cover-off", ())),  # the pad was the solid in the way
        ("largest", (Verdict.BLOCKED, None, ("cover",))),  # the slab is, and it stays
    ],
)
def test_a_remove_glob_naming_a_piece_takes_that_solid_alone(over, expected):
    model = as_step_reads(covered(two_solids(over)))
    report = check(model, Config.from_dict(cover_off("cover#2")))
    assert verdict(report) == expected
    assert report.models["cover-off"].removed == {"cover#2"}


def test_a_part_that_only_shares_the_name_stays():
    # Two parts named cover: the second is cover#2 as a piece would be, and is none.
    model = namesakes()
    assert [(part.name, part.piece_of) for part in model][2:] == [
        ("cover", None),
        ("cover#2", None),
    ]
    report = check(model, Config.from_dict(cover_off("cover")))
    assert verdict(report) == (Verdict.BLOCKED, None, ("cover#2",))
    assert report.models["cover-off"].removed == {"cover"}


def test_a_state_built_on_another_takes_both_their_parts_off_whole():
    sidecar = {
        "fasteners": [SCREW],
        "states": {
            "cover-off": {"remove": ["cover"]},
            "all-off": {"base": "cover-off", "remove": ["lid"]},
        },
        "checks": {"try_states": ["cover-off", "all-off"]},
    }
    report = check(lidded(), Config.from_dict(sidecar))
    assert verdict(report) == (Verdict.TURNS, "all-off", ())
    assert report.models["all-off"].removed == {"cover", "cover#2", "lid"}


def lidded():
    """The covered screw with a lid over it too, above the cover's pad: a part of one solid."""
    return as_step_reads([*covered(), ("lid", Pos(0, 0, 60) * Box(30, 30, 4))])


def test_a_state_that_takes_off_another_part_leaves_this_one_s_piece():
    # The lid alone comes off: the cover's pad is no piece of it, and is still in the way.
    sidecar = {
        "fasteners": [SCREW],
        "states": {"lid-off": {"remove": ["lid"]}},
        "checks": {"try_states": ["lid-off"]},
    }
    report = check(lidded(), Config.from_dict(sidecar))
    (result,) = report.results
    assert (result.verdict, result.state) == (Verdict.BLOCKED, None)
    assert "cover#2" in result.blocked_by
    assert report.models["lid-off"].removed == {"lid"}


def test_a_state_s_own_model_gives_the_pieces_it_takes_off(tmp_path):
    # The cover is two solids in the main model and three in the state's: what comes
    # off there is the state's model's to say.
    shapes = []
    for name, shape in covered(two_solids(solids=3)):
        shape.label = name
        shapes.append(shape)
    export_step(Compound(children=shapes), str(tmp_path / "moved.step"))
    sidecar = {
        "fasteners": [SCREW],
        "states": {"moved": {"model": "moved.step", "remove": ["cover"]}},
        "checks": {"try_states": ["moved"]},
    }
    report = check(as_step_reads(covered()), Config.from_dict(sidecar), model_dir=tmp_path)
    assert verdict(report) == (Verdict.TURNS, "moved", ())
    assert report.models["moved"].removed == {"cover", "cover#2", "cover#3"}


def test_a_remove_glob_that_names_nothing_still_says_so():
    report = check(as_step_reads(covered()), Config.from_dict(cover_off("cover", "hatch")))
    assert report.warnings == (
        "state 'cover-off': remove glob 'hatch' matched nothing (renamed part?)",
    )


def test_the_view_draws_none_of_a_part_taken_off():
    data = view_data(check(as_step_reads(covered()), Config.from_dict(cover_off("cover"))))
    drawn = {
        view["state"]: [data["parts"][index]["name"] for index in view["parts"]]
        for view in data["views"]
    }
    assert drawn == {None: ["plate", "bolt", "cover", "cover#2"], "cover-off": ["plate", "bolt"]}


# ---------------------------------------------------------------------------
# A rule's mates:.
# ---------------------------------------------------------------------------


def mated(*globs):
    return {"fasteners": [{**SCREW, "mates": list(globs)}]}


@READERS
@pytest.mark.parametrize("engine", ENGINES)
def test_a_mate_is_the_whole_part(reader, engine):
    report = check(reader(covered()), Config.from_dict(mated("cover")), engine=engine)
    assert verdict(report) == (Verdict.TURNS, None, ())
    assert (report.warnings, report.exit_code) == ((), 0)


@pytest.mark.parametrize(
    ("over", "expected"),
    [("piece", (Verdict.TURNS, None, ())), ("largest", (Verdict.BLOCKED, None, ("cover",)))],
)
def test_a_mate_glob_naming_a_piece_is_that_solid_alone(over, expected):
    model = as_step_reads(covered(two_solids(over)))
    assert verdict(check(model, Config.from_dict(mated("cover#2")))) == expected


def test_a_part_that_only_shares_a_mate_s_name_is_no_mate():
    assert verdict(check(namesakes(), Config.from_dict(mated("cover")))) == (
        Verdict.BLOCKED,
        None,
        ("cover#2",),
    )


def test_a_mate_takes_no_other_part_s_piece_with_it():
    # The lid is the mate: the cover's pad is no piece of it, and is still in the way.
    assert verdict(check(lidded(), Config.from_dict(mated("lid")))) == (
        Verdict.BLOCKED,
        None,
        ("cover#2",),
    )


def sunk():
    """The cover's pad drawn 1 into the screw's head: 4 to 5 mm of it, pi 5.5^2 = 95.0 mm^3."""
    slab = Pos(70, 0, 45) * Box(40, 80, 10)
    pad = Pos(0, 0, 27) * Box(30, 30, 4)
    return covered(Compound([slab.solid(), pad.solid()]))


def listed(found):
    return [(clash.first, clash.second, round(clash.volume, 1)) for clash in found.found]


#: The order the model has its parts in, which is the order a pair of them is asked in.
ORDERS = pytest.mark.parametrize("turned", [False, True], ids=["as-drawn", "other-way-round"])


@READERS
@ORDERS
@pytest.mark.parametrize("engine", ENGINES)
def test_a_fastener_drawn_into_its_mate_s_piece_is_no_clash(reader, turned, engine):
    parts = sunk()[::-1] if turned else sunk()
    found = find_clashes(reader(parts), Config.from_dict(mated("cover")), engine=engine)
    assert listed(found) == []


def test_without_the_mate_the_piece_is_the_clash():
    found = find_clashes(as_step_reads(sunk()), Config.from_dict({"fasteners": [SCREW]}))
    assert listed(found) == [("bolt", "cover#2", 95.0)]
    inside = check(as_step_reads(sunk()), Config.from_dict(mated("cover")), clashes=True)
    assert listed(inside.clashes) == []


# ---------------------------------------------------------------------------
# An allow: pair.
# ---------------------------------------------------------------------------


def pinned(block_in_two=False):
    """A block and two pins 6 across, each drawn 0.5 into its top: 14.1 mm^3 apiece.

    The two pins are one part, the longer its largest solid. ``block_in_two`` cuts the
    block in two under the gap between them, the half under the short pin the smaller.
    """
    block = Pos(0, 0, -10) * Box(60, 30, 20)
    if block_in_two:
        left, right = Pos(-10, 0, -10) * Box(40, 30, 20), Pos(20, 0, -10) * Box(20, 30, 20)
        block = Compound([left.solid(), right.solid()])
    long_pin, short_pin = Pos(-15, 0, 9.5) * Cylinder(3, 20), Pos(15, 0, 4.5) * Cylinder(3, 10)
    return [("block", block), ("pin", Compound([long_pin.solid(), short_pin.solid()]))]


def allowing(*pair):
    return Config.from_dict({"allow": [list(pair)]} if pair else {})


def test_read_in_pieces_each_pin_is_a_clash_of_its_own():
    assert listed(find_clashes(as_step_reads(pinned()), allowing())) == [
        ("pin", "block", 14.1),
        ("pin#2", "block", 14.1),
    ]


@READERS
@ORDERS
@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("pair", [("pin", "block"), ("block", "pin")], ids=["as-said", "turned"])
def test_an_allow_pair_lets_the_whole_part_in(reader, turned, engine, pair):
    parts = pinned()[::-1] if turned else pinned()
    found = find_clashes(reader(parts), allowing(*pair), engine=engine)
    assert listed(found) == []
    assert found.unmatched_allows == ()


def test_an_allow_pair_holds_between_two_parts_pieces():
    model = as_step_reads(pinned(block_in_two=True))
    assert listed(find_clashes(model, allowing())) == [
        ("pin", "block", 14.1),
        ("pin#2", "block#2", 14.1),
    ]
    assert listed(find_clashes(model, allowing("pin", "block"))) == []


def test_an_allow_glob_naming_a_piece_allows_that_solid_alone():
    found = find_clashes(as_step_reads(pinned()), allowing("pin#2", "block"))
    assert listed(found) == [("pin", "block", 14.1)]


def test_a_part_that_only_shares_an_allowed_name_is_not_allowed():
    block, pin = pinned()
    long_pin, short_pin = pin[1].solids()
    model = as_step_reads([block, ("pin", long_pin), ("pin", short_pin)])
    assert [(part.name, part.piece_of) for part in model][1:] == [("pin", None), ("pin#2", None)]
    assert listed(find_clashes(model, allowing("pin", "block"))) == [("pin#2", "block", 14.1)]


# ---------------------------------------------------------------------------
# A plug: its mates, and a state's remove:.
# ---------------------------------------------------------------------------


def plugged(name, over):
    """A plug in its jack on a board, and a part of two solids: one aside, one in its way.

    The plug stands to z = 23 and comes off upwards by 10; ``over`` crosses its path at 28.
    """
    jack = Pos(0, 0, 5) * Box(20, 12, 10) - Pos(0, 0, 6.5) * Box(16, 8, 7.01)
    plug = Pos(0, 0, 13) * Box(16, 8, 20)
    aside = Pos(60, 0, 20) * Box(30, 30, 10)
    return [
        ("board", Pos(0, 0, -1) * Box(200, 100, 2)),
        ("jack", jack),
        ("plug", plug),
        (name, Compound([aside.solid(), (Pos(0, 0, 29) * over).solid()])),
    ]


def unplugged(report):
    (result,) = report.connectors.results
    return result.verdict, result.state, result.blockers


def test_read_in_pieces_the_lead_s_piece_is_in_the_plug_s_way():
    model = as_step_reads(plugged("lead", Box(4, 30, 2)))
    report = check(model, Config.from_dict({"connectors": [{"parts": "plug"}]}))
    assert unplugged(report) == (ConnectorVerdict.STUCK, None, ("lead#2",))


@READERS
def test_a_plug_s_mate_is_the_whole_part(reader):
    model = reader(plugged("lead", Box(4, 30, 2)))
    config = Config.from_dict({"connectors": [{"parts": "plug", "mates": ["lead"]}]})
    assert unplugged(check(model, config)) == (ConnectorVerdict.UNPLUGS, None, ())


@READERS
def test_a_plug_comes_off_in_a_state_that_takes_a_part_off_whole(reader):
    model = reader(plugged("lid", Box(30, 30, 2)))
    sidecar = {
        "connectors": [{"parts": "plug"}],
        "states": {"lid-off": {"remove": ["lid"]}},
        "checks": {"try_states": ["lid-off"]},
    }
    assert unplugged(check(model, Config.from_dict(sidecar))) == (
        ConnectorVerdict.UNPLUGS,
        "lid-off",
        (),
    )


# ---------------------------------------------------------------------------
# The issue's model, through a STEP file.
# ---------------------------------------------------------------------------


def test_the_issue_s_cover_read_from_step_is_as_the_shapes_have_it(tmp_path):
    shapes = []
    for name, shape in covered():
        shape.label = name
        shapes.append(shape)
    export_step(Compound(children=shapes), str(tmp_path / "covered.step"))
    from_step = Assembly.from_step(tmp_path / "covered.step")
    assert from_step.names == ("plate", "bolt", "cover", "cover#2")
    from_shapes = Assembly.from_shapes(covered())
    for sidecar in (cover_off("cover"), mated("cover")):
        config = Config.from_dict(sidecar)
        read, given = check(from_step, config), check(from_shapes, config)
        assert verdict(read) == verdict(given)
        assert verdict(read)[0] is Verdict.TURNS
