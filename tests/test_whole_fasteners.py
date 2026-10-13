"""A fastener drawn as several solids is one part, read from STEP as from shapes (issue #210).

Read from STEP, a part of several solids is its largest solid, which keeps the name,
and ``name#2`` pieces: right for what stands in a tool's way (issue #28). A fastener
was read from its largest solid too, so a hex bolt whose head and shank are two
solids was a rod with no hex, or a hex with no axis: ``held`` in the plate's hole, or
not covered, where the same shapes handed over whole are a bolt that turns.

A fastener is one thing. Once the fasteners are known, each is made whole again in
every model of the run: read from all of itself, tried as one part, measured as one
for a clash, and drawn as one. The readers then give one report.
"""

import math

import pytest
from build123d import Box, Compound, Cylinder, Pos, export_step

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check, find_clashes
from wrenchroom.config import Config
from wrenchroom.detect import describe, read_name
from wrenchroom.engine import ENGINES
from wrenchroom.fasteners import Head
from wrenchroom.report import Verdict

BOLT = {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"}
RULED = {"fasteners": [BOLT], "checks": {"detect": False}}


def in_pieces(named):
    """The assembly a STEP file of these parts gives, with no file written."""
    shapes = []
    for name, shape in named:
        shape.label = name
        shapes.append(shape)
    return Assembly.from_compound(Compound(children=shapes))


READERS = {"in-pieces": in_pieces, "whole": Assembly.from_shapes}
EITHER = pytest.mark.parametrize("reader", list(READERS))
#: Which of the bolt's two solids is the larger, and so keeps its name read in pieces.
LARGER = pytest.mark.parametrize("larger", ["head", "shank"])


def bolt(larger="shank", name="bolt"):
    """An M8 hex bolt as two solids, its head 5.3 or 8 tall on z = 0 and its shank below.

    The head, 146.4 mm^2 of hex, is 776 or 1171 mm^3; the shank, 50.3 mm^2, 20 long, 1005.
    """
    head = hex_prism(13, 8.0 if larger == "head" else 5.3)
    shank = Pos(0, 0, -10) * Cylinder(4, 20)
    return (name, Compound([head.solid(), shank.solid()]))


def plate():
    return ("plate", Pos(0, 0, -5) * (Box(40, 40, 10) - Cylinder(4.5, 30)))


def said(report):
    """Each fastener as the report has it, its seat to a hundredth."""
    return [
        (
            e["name"],
            e["verdict"],
            e["tool"],
            e["how"],
            [round(x, 2) for x in e["seat"]],
            e["blocked_by"],
            e["reason"],
        )
        for e in report.to_json_dict()["fasteners"]
    ]


# ---------------------------------------------------------------------------
# The reading: a bolt whose head and shank are two solids.
# ---------------------------------------------------------------------------


@LARGER
def test_read_in_pieces_the_named_solid_is_the_larger_and_the_other_its_piece(larger):
    assembly = in_pieces([bolt(larger), plate()])
    assert [(part.name, part.piece_of) for part in assembly] == [
        ("bolt", None),
        ("bolt#2", "bolt"),
        ("plate", None),
    ]
    named = assembly["bolt"].shape
    assert bool(named.faces().filter_by(lambda face: face.geom_type.name == "CYLINDER")) == (
        larger == "shank"
    )


@LARGER
@EITHER
@pytest.mark.parametrize("engine", ENGINES)
def test_a_bolt_of_two_solids_turns_however_it_is_read(larger, reader, engine):
    report = check(READERS[reader]([bolt(larger), plate()]), Config.from_dict(RULED), engine=engine)
    tall = 8.0 if larger == "head" else 5.3
    assert said(report) == [
        ("bolt", "turns", "spanner-13", "ring, full length", [0.0, 0.0, tall], [], None)
    ]


@LARGER
@pytest.mark.parametrize("engine", ENGINES)
def test_the_two_readers_give_one_report(larger, engine):
    reports = [
        check(read([bolt(larger), plate()]), Config.from_dict(RULED), kit="full", engine=engine)
        for read in READERS.values()
    ]
    first, second = (report.to_json_dict() for report in reports)
    assert first == second


@LARGER
@EITHER
def test_detection_reads_all_of_it_too(larger, reader):
    # No rule: found by its name, and its hex and its thread read off the two solids.
    name, shape = bolt(larger, name="M8x20 hex bolt")
    report = check(READERS[reader]([(name, shape), plate()]), kit="full")
    (entry,) = report.to_json_dict()["fasteners"]
    assert (entry["name"], entry["verdict"], entry["tool"]) == (name, "turns", "spanner-13")
    assert (entry["size"], entry["head"], entry["source"]) == ("M8", "hex", "name+geometry")


@EITHER
def test_a_part_not_named_a_fastener_is_looked_at_whole(reader):
    # An M3 socket screw named for nothing, its head and its shank two solids, the
    # shank the larger: a plain rod by itself, and plainly a screw once both are
    # looked at. Passed over, saying so (issue #95), from either reader.
    head = Pos(0, 0, 1.5) * Cylinder(2.75, 3) - hex_prism(2.5, 1.51, 1.5)
    shank = Pos(0, 0, -8) * Cylinder(1.5, 16)
    screw = ("Part7", Compound([head.solid(), shank.solid()]))
    report = check(READERS[reader]([screw, plate()]), kit="full")
    assert [(p.name, p.named, p.reason) for p in report.passed_over] == [
        (
            "Part7",
            False,
            "not named as a fastener, but its solid looks like one: M3 screw, a 2.5 hex socket",
        )
    ]


# ---------------------------------------------------------------------------
# One part, in the scene and in the list.
# ---------------------------------------------------------------------------


def lidded(larger="shank"):
    """The bolt under a lid 3 over its head: nothing gets on from above."""
    tall = 8.0 if larger == "head" else 5.3
    return [bolt(larger), plate(), ("lid", Pos(0, 0, tall + 3 + 5) * Box(40, 40, 10))]


@LARGER
@EITHER
@pytest.mark.parametrize("engine", ENGINES)
def test_another_fastener_s_tool_meets_the_bolt_by_its_name(larger, reader, engine):
    # A socket screw under the bolt, head up, its top 6 below the bolt's shank end: no
    # key comes down to it. Blocked by the bolt, though the shank is its piece where
    # the head is the larger solid, and by no piece of it.
    screw = Pos(0, 0, -52) * (Pos(0, 0, 10) * Cylinder(3, 20) + Pos(0, 0, 23) * Cylinder(5.5, 6))
    rules = [BOLT, {"parts": "screw", "kind": "screw", "head": "socket", "size": "M6"}]
    base = Pos(0, 0, -47) * (Box(60, 60, 10) - Cylinder(3.2, 30))
    parts = [bolt(larger), ("screw", screw), ("base", base)]
    report = check(
        READERS[reader](parts),
        Config.from_dict({"fasteners": rules, "checks": {"detect": False}}),
        engine=engine,
    )
    by_name = {result.fastener.name: result for result in report.results}
    assert by_name["screw"].verdict is Verdict.BLOCKED
    assert by_name["screw"].blocked_by == ("bolt",)


@LARGER
@EITHER
@pytest.mark.parametrize("engine", ENGINES)
def test_its_thread_in_its_hole_is_no_clash_whichever_solid_it_is(larger, reader, engine):
    # The shank, 4 out, in a block tapped at M8's minor, 3.32: a thread, measured
    # past, as the whole bolt's is. Read as a solid of its own it was a clash.
    block = Pos(0, 0, -10) * (Box(40, 40, 20) - Cylinder(3.32, 40))
    found = find_clashes(
        READERS[reader]([bolt(larger), ("block", block)]), Config.from_dict(RULED), engine=engine
    )
    assert (found.found, found.unmeasured) == ((), ())


@LARGER
@EITHER
def test_its_head_drawn_into_a_part_is_one_clash_under_its_name(larger, reader):
    # A lid 0.5 down into the head, on a bolt in a hole it clears: the hex, 146.4 mm^2,
    # 0.5 deep, 73.2 mm^3, told of the bolt and of no piece.
    tall = 8.0 if larger == "head" else 5.3
    lid = ("lid", Pos(0, 0, tall - 0.5 + 5) * Box(40, 40, 10))
    found = find_clashes(READERS[reader]([bolt(larger), plate(), lid]), Config.from_dict(RULED))
    assert [(c.first, c.second, round(c.volume, 1)) for c in found.found] == [("bolt", "lid", 73.2)]


def test_the_report_keeps_the_model_as_it_was_checked():
    # The fastener whole, the part that is none still in its solids, and a model with
    # nothing to make whole the very one handed over.
    slab, pad = Pos(60, 0, 20) * Box(20, 20, 10), Pos(60, 30, 20) * Box(10, 10, 4)
    cover = ("cover", Compound([slab.solid(), pad.solid()]))
    read = in_pieces([bolt(), plate(), cover])
    assert "bolt#2" in read.names
    checked = check(read, Config.from_dict(RULED)).models[None].assembly
    assert checked.names == ("bolt", "plate", "cover", "cover#2")
    assert len(checked["bolt"].shape.solids()) == 2
    assert read.names == ("bolt", "bolt#2", "plate", "cover", "cover#2")  # and left alone
    given = Assembly.from_shapes([bolt(), plate(), cover])
    assert check(given, Config.from_dict(RULED)).models[None].assembly is given
    plain = in_pieces([("bolt", hex_prism(13, 5.3) + Pos(0, 0, -10) * Cylinder(4, 20)), plate()])
    assert check(plain, Config.from_dict(RULED)).models[None].assembly is plain


# ---------------------------------------------------------------------------
# A state's model, and a build step's.
# ---------------------------------------------------------------------------

OPEN = {
    **RULED,
    "states": {"open": {"model": "open.step"}},
    "checks": {"detect": False, "try_states": ["open"]},
}
EITHER_WAY = pytest.mark.parametrize(
    ("main", "other"), [(main, other) for main in READERS for other in READERS]
)


def opened(lift):
    """lidded(), its lid lifted: 3 over the head as drawn, clear at 40."""
    parts = lidded()
    name, lid = parts[-1]
    return [*parts[:-1], (name, Pos(0, 0, lift) * lid)]


@EITHER_WAY
@pytest.mark.parametrize("engine", ENGINES)
def test_a_state_s_model_has_the_bolt_whole_however_each_is_read(main, other, engine):
    report = check(
        READERS[main](opened(0.0)),
        Config.from_dict(OPEN),
        models={"open.step": READERS[other](opened(40.0))},
        engine=engine,
    )
    (result,) = report.results
    assert (result.verdict, result.state, report.notes) == (Verdict.TURNS, "open", ())
    assert report.models["open"].assembly.pieces("bolt") == ()


def test_a_state_s_model_read_from_its_file_has_the_bolt_whole(tmp_path):
    shapes = []
    for name, shape in opened(40.0):
        shape.label = name
        shapes.append(shape)
    export_step(Compound(children=shapes), str(tmp_path / "open.step"))
    assert "bolt#2" in Assembly.from_step(tmp_path / "open.step").names
    report = check(in_pieces(opened(0.0)), Config.from_dict(OPEN), model_dir=tmp_path)
    (result,) = report.results
    assert (result.verdict, result.state) == (Verdict.TURNS, "open")
    assert report.models["open"].assembly.names == ("bolt", "plate", "lid")


@EITHER_WAY
def test_a_build_step_s_model_has_the_bolt_whole_however_each_is_read(main, other):
    # The bolt goes in before the lid, in the step's own model: turned there.
    steps = [
        {"step": "bolt", "add": ["plate", "bolt"], "model": "early.step"},
        {"step": "lid", "add": ["lid"]},
    ]
    report = check(
        READERS[main](lidded()),
        Config.from_dict({**RULED, "build": steps}),
        models={"early.step": READERS[other](lidded())},
    )
    (placed,) = report.build.placed
    assert (placed.result.verdict, placed.step) == (Verdict.TURNS, "bolt")
    assert report.notes == ()


# ---------------------------------------------------------------------------
# Assembly.joined, and what a part read in pieces carries.
# ---------------------------------------------------------------------------


def test_the_largest_solid_carries_the_leaf_it_was_read_from():
    assembly = in_pieces([bolt(), plate()])
    named, piece, flat = assembly["bolt"], assembly["bolt#2"], assembly["plate"]
    assert named.leaf is not None
    assert len(named.leaf.solids()) == 2
    assert (piece.leaf, flat.leaf) == (None, None)
    assert named.whole is named.leaf
    assert (piece.whole, flat.whole) == (piece.shape, flat.shape)
    assert named.whole.volume == pytest.approx(named.shape.volume + piece.shape.volume)
    # And a part handed over whole is its own shape, all of it.
    given = Assembly.from_shapes([bolt(), plate()])["bolt"]
    assert (given.leaf, given.whole) == (None, given.shape)


def test_a_leaf_read_from_a_step_file_carries_it_too(tmp_path):
    shapes = []
    for name, shape in [bolt(), plate()]:
        shape.label = name
        shapes.append(shape)
    export_step(Compound(children=shapes), str(tmp_path / "bolt.step"))
    read = Assembly.from_step(tmp_path / "bolt.step")
    assert read.names == ("bolt", "bolt#2", "plate")
    assert read["bolt"].leaf is not None
    assert read["bolt"].whole.volume == pytest.approx(776.0 + 1005.3, abs=0.5)


def test_joined_makes_the_parts_named_whole_and_leaves_the_rest():
    slab, pad = Pos(60, 0, 20) * Box(20, 20, 10), Pos(60, 30, 20) * Box(10, 10, 4)
    assembly = in_pieces([bolt(), plate(), ("cover", Compound([slab.solid(), pad.solid()]))])
    joined = assembly.joined({"bolt"})
    assert joined.names == ("bolt", "plate", "cover", "cover#2")
    assert (joined.pieces("bolt"), joined.pieces("cover")) == ((), ("cover#2",))
    assert joined["bolt"].shape is assembly["bolt"].leaf
    assert (joined["bolt"].piece_of, joined["bolt"].leaf) == (None, None)
    for name in ("plate", "cover", "cover#2"):
        assert joined[name] is assembly[name]
    both = assembly.joined(["cover", "bolt"])
    assert both.names == ("bolt", "plate", "cover")
    assert len(both["cover"].shape.solids()) == 2


@pytest.mark.parametrize("names", [(), ("plate",), ("bolt#2",), ("nothing",)])
def test_joined_with_nothing_to_make_whole_is_the_assembly_itself(names):
    assembly = in_pieces([bolt(), plate()])
    assert assembly.joined(names) is assembly
    whole = Assembly.from_shapes([bolt(), plate()])
    assert whole.joined({"bolt"}) is whole


def test_joined_takes_no_part_that_only_shares_the_name():
    # Two parts named bolt: the second is numbered as a piece is, and is none.
    chip = Pos(30, 0, 0) * Box(4, 4, 4)
    assembly = in_pieces([bolt(), plate(), ("bolt", chip)])
    assert [(part.name, part.piece_of) for part in assembly] == [
        ("bolt", None),
        ("bolt#2", "bolt"),
        ("plate", None),
        ("bolt#3", None),
    ]
    joined = assembly.joined({"bolt"})
    assert joined.names == ("bolt", "plate", "bolt#3")
    assert joined["bolt#3"] is assembly["bolt#3"]
    assert len(joined["bolt"].shape.solids()) == 2


def test_joined_keeps_the_surfaces_named():
    decal = Pos(0, 0, 40) * Box(10, 10, 1)
    shapes = []
    for name, shape in [bolt(), plate(), ("decal", decal.faces()[0])]:
        shape.label = name
        shapes.append(shape)
    assembly = Assembly.from_compound(Compound(children=shapes))
    assert assembly.surfaces == ("decal",)
    assert assembly.joined({"bolt"}).surfaces == ("decal",)


def test_joined_puts_pieces_made_by_hand_together():
    # Parts built one by one, with no leaf to go back to: the solids, all of them.
    head, shank = hex_prism(13, 5.3), Pos(0, 0, -10) * Cylinder(4, 20)
    assembly = Assembly([Part("bolt", shank), Part("bolt#2", head, piece_of="bolt")])
    joined = assembly.joined({"bolt"})
    assert joined.names == ("bolt",)
    assert len(joined["bolt"].shape.solids()) == 2
    assert joined["bolt"].shape.volume == pytest.approx(
        math.pi * 16 * 20 + 13**2 * math.sqrt(3) / 2 * 5.3, abs=0.5
    )


@LARGER
def test_a_part_in_pieces_is_described_from_all_of_it(larger):
    # describe() asked by itself, with no reading handed to it: the hex and the shank,
    # whichever solid has the name.
    name, shape = bolt(larger, name="hex bolt")
    part = in_pieces([(name, shape)])[name]
    found = describe(part, read_name(name))
    assert (found.head, found.size.designation, found.not_covered) == (Head.HEX, "M8", None)
    whole = describe(Part(name, shape), read_name(name))
    assert (found.head, found.size, found.basis) == (whole.head, whole.size, whole.basis)
