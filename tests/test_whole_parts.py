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

from fastener_models import hex_prism
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
    # The ground the rest stands on: the pad, cover#2, is in the key's way. The
    # report says the cover is, the part: no piece is named in one (issue #210).
    model = as_step_reads(covered())
    assert [(part.name, part.piece_of) for part in model][2:] == [
        ("cover", None),
        ("cover#2", "cover"),
    ]
    assert verdict(check(model, Config.from_dict({"fasteners": [SCREW]}))) == (
        Verdict.BLOCKED,
        None,
        ("cover",),
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
    assert "cover" in result.blocked_by
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
        ("cover",),
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
    # Told of the cover, the part: the list names no piece (issue #210).
    found = find_clashes(as_step_reads(sunk()), Config.from_dict({"fasteners": [SCREW]}))
    assert listed(found) == [("bolt", "cover", 95.0)]
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


@READERS
def test_the_two_pins_are_one_clash_of_the_part_however_it_is_read(reader):
    # Each pin 14.1 into the block: one clash of pin and block, 28.3, the two solids'
    # together (issue #210). Read in pieces it was two lines, the second of pin#2.
    assert listed(find_clashes(reader(pinned()), allowing())) == [("pin", "block", 28.3)]


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
    assert listed(find_clashes(model, allowing())) == [("pin", "block", 28.3)]
    assert listed(find_clashes(model, allowing("pin", "block"))) == []


def test_an_allow_glob_naming_a_piece_allows_that_solid_alone():
    # The short pin's share is allowed and the long pin's is told, of the part.
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
    assert unplugged(report) == (ConnectorVerdict.STUCK, None, ("lead",))


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


# ---------------------------------------------------------------------------
# A pair: a bolt and its nut, one drawn into the other (issue #208).
# ---------------------------------------------------------------------------

HEX_BOLT = {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"}
NUT = {"parts": "nut", "kind": "nut", "size": "M8"}


def joined():
    """An M8 bolt of two solids, its shank the larger, and its nut 0.5 up into its head.

    tests/test_clashes.py has the joint with its bolt one solid: a pair, and none. The
    nut's hex less its bore, 146.36 - 50.27 mm^2, 0.5 deep: 48.0 mm^3, in the bolt's piece.
    """
    head, shank = hex_prism(13, 5.3), Pos(0, 0, -30) * Cylinder(4, 60)
    nut = Pos(0, 0, -6.3) * (hex_prism(13, 6.8) - Cylinder(4, 30))  # z -6.3 to 0.5
    return [("bolt", Compound([shank.solid(), head.solid()])), ("nut", nut)]


def collared():
    """The other way about: the nut of two solids, a collar on its hex, 0.5 up into the
    head of a bolt drawn as one. The collar, 6 out and 4 in, pi 20 mm^2, 0.5 deep: 31.4."""
    bolt = hex_prism(13, 5.3) + Pos(0, 0, -15) * Cylinder(4, 30)
    body = Pos(0, 0, -8.3) * (hex_prism(13, 6.8) - Cylinder(4, 30))  # z -8.3 to -1.5
    collar = Pos(0, 0, -0.5) * (Cylinder(6, 2) - Cylinder(4, 30))  # z -1.5 to 0.5
    return [("bolt", bolt), ("nut", Compound([body.solid(), collar.solid()]))]


def paired():
    return Config.from_dict({"fasteners": [HEX_BOLT, NUT], "checks": {"detect": False}})


JOINTS = pytest.mark.parametrize("joint", [joined, collared], ids=["bolt-in-two", "nut-in-two"])


@READERS
@ORDERS
@JOINTS
@pytest.mark.parametrize("engine", ENGINES)
def test_a_fastener_drawn_into_its_partner_s_piece_is_its_pair_and_none(
    reader, turned, joint, engine
):
    parts = joint()[::-1] if turned else joint()
    assert listed(find_clashes(reader(parts), paired(), engine=engine)) == []


def test_without_the_pair_the_partner_s_piece_is_the_clash():
    # The guards: the same solids with one of the two no fastener, so no pair of it.
    only_nut = Config.from_dict({"fasteners": [NUT], "checks": {"detect": False}})
    assert listed(find_clashes(as_step_reads(joined()), only_nut)) == [("nut", "bolt", 48.0)]
    only_bolt = Config.from_dict({"fasteners": [HEX_BOLT], "checks": {"detect": False}})
    assert listed(find_clashes(as_step_reads(collared()), only_bolt)) == [("bolt", "nut", 31.4)]


def failing(report):
    return {r.fastener.name: (r.verdict, (r.reason or "").split(":")[0]) for r in report.results}


@READERS
@pytest.mark.parametrize("engine", ENGINES)
def test_the_check_passes_over_its_partner_s_piece_as_it_does_its_partner(reader, engine):
    # The nut can't turn, its corners in its bolt's head: blocked, as with the bolt one
    # solid. It was "drawn into bolt#2: fix the model", not covered, read in pieces.
    report = check(reader(joined()), paired(), kit="full", engine=engine, clashes=True)
    verdicts = {r.fastener.name: r.verdict for r in report.results}
    assert verdicts == {"bolt": Verdict.BLOCKED, "nut": Verdict.BLOCKED}
    assert not any("drawn into" in (r.reason or "") for r in report.results)
    assert listed(report.clashes) == []


@pytest.mark.parametrize("engine", ENGINES)
def test_the_check_reads_the_two_readers_alike_with_the_nut_in_two(engine):
    readers = (as_step_reads, Assembly.from_shapes)
    reports = [check(read(collared()), paired(), kit="full", engine=engine) for read in readers]
    assert failing(reports[0]) == failing(reports[1])
    assert not any("drawn into" in (r.reason or "") for report in reports for r in report.results)


def test_a_part_that_only_shares_a_partner_s_name_is_no_partner():
    # A chip named bolt as the bolt is, a part of its own (numbered bolt#2, and no
    # piece), 1 into the nut's corner and 3 tall, as tests/test_clashes.py draws it:
    # 5.2 mm^3. The nut's pair is its bolt, and the chip a clash still.
    corner = 13 / 3**0.5
    chip = Pos(corner - 1.0 + 5, 0, -6.3 + 3.4) * Box(10, 30, 3)
    bolt = hex_prism(13, 5.3, z0=2.0) + Pos(0, 0, -15) * Cylinder(4, 34)  # its head clear above
    nut = Pos(0, 0, -6.3) * (hex_prism(13, 6.8) - Cylinder(4, 30))
    assembly = as_step_reads([("bolt", bolt), ("nut", nut), ("bolt", chip)])
    assert [(part.name, part.piece_of) for part in assembly][-1] == ("bolt#2", None)
    assert listed(find_clashes(assembly, paired())) == [("nut", "bolt#2", 5.2)]
    # And to the check, which asks it of what stops the nut turning.
    by_name = {r.fastener.name: r for r in check(assembly, paired(), kit="full").results}
    assert by_name["nut"].verdict is Verdict.NOT_COVERED
    assert by_name["nut"].reason == "drawn into bolt#2 (5.2 mm^3): fix the model"


def test_a_fastener_drawn_into_another_part_s_piece_is_told_by_the_check():
    # The cover's pad, its piece, 1 down into the screw's head: no pair of the screw's,
    # and no mate. Passing over a partner's pieces passes over no other part's.
    (result,) = check(as_step_reads(sunk()), Config.from_dict({"fasteners": [SCREW]})).results
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == "drawn into cover (95.0 mm^3): fix the model"


def test_two_fasteners_each_with_a_pair_of_its_own_are_no_pair():
    # Two bolts 14 apart, each with its nut: the hexes' corners, 7.5 out, meet 1 deep,
    # head into head and nut into nut. Each one's pair is its own, and a fastener
    # drawn into another joint's is a clash.
    def joint(x, tag):
        bolt = hex_prism(13, 5.3, z0=12.0) + Pos(0, 0, 0) * Cylinder(4, 30)
        nut = Pos(0, 0, -6.3) * (hex_prism(13, 6.8) - Cylinder(4, 30))
        return [(f"bolt_{tag}", Pos(x, 0, 0) * bolt), (f"nut_{tag}", Pos(x, 0, 0) * nut)]

    rules = [{**HEX_BOLT, "parts": "bolt_*"}, {**NUT, "parts": "nut_*"}]
    config = Config.from_dict({"fasteners": rules, "checks": {"detect": False}})
    found = find_clashes(as_step_reads([*joint(0, "a"), *joint(14, "b")]), config)
    assert [(first, second) for first, second, _ in listed(found)] == [
        ("bolt_a", "bolt_b"),
        ("nut_a", "nut_b"),
    ]
