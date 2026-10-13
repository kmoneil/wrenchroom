"""A model from shapes beside one from STEP: a part of several solids is one part (issue #199).

The two readers differ on such a part. ``from_shapes`` keeps it whole; ``from_step``
makes it its largest solid, which keeps the name, and ``name#2`` pieces. Inside one
model that is consistent. A run may hold a model of each, though: a build script's own
shapes as the main model and a STEP file as a state's or a build step's, or the other
way about. The piece was then taken for a part of its own, one the other model hasn't.

A state's model was noted as having a part the main model doesn't, for the same part.
And in a build step whose model was read from STEP, under a main model from shapes,
the piece of a part a later step adds had no step of its own, so it stayed in the
scene after its part was left out, and blocked a screw put in before it.

Parts are compared now, not their solids, and a piece is still to come when its part
is. The same four runs, each model read either way, give one report.
"""

import pytest
from build123d import Box, Compound, Cylinder, Pos

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check, find_clashes
from wrenchroom.config import Config
from wrenchroom.engine import ENGINES
from wrenchroom.report import Verdict

SCREW = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}


def in_pieces(named):
    """The assembly a STEP file of these parts gives, with no file written: a part of
    several solids is its largest, and its pieces."""
    shapes = []
    for name, shape in named:
        shape.label = name
        shapes.append(shape)
    return Assembly.from_compound(Compound(children=shapes))


#: Each model read as STEP reads it, or kept whole as from_shapes keeps it.
READERS = {"in-pieces": in_pieces, "whole": Assembly.from_shapes}
EITHER_WAY = pytest.mark.parametrize(
    ("main", "other"),
    [(main, other) for main in READERS for other in READERS],
    ids=[f"{main}-beside-{other}" for main in READERS for other in READERS],
)


def covered(lift=0.0, cover="cover", jig=None):
    """A plate, a screw standing head up to z = 26, and a cover of two solids: a slab
    off to the side and a pad 10 over the screw's head, both raised by ``lift``."""
    plate = Pos(0, 0, -5) * Box(200, 100, 10)
    bolt = Pos(0, 0, 10) * Cylinder(3, 20) + Pos(0, 0, 23) * Cylinder(5.5, 6)
    slab, pad = Pos(70, 0, 45 + lift) * Box(40, 80, 10), Pos(0, 0, 38 + lift) * Box(30, 30, 4)
    parts = [("plate", plate), ("bolt", bolt), (cover, Compound([slab.solid(), pad.solid()]))]
    return [*parts, *([("jig", jig)] if jig is not None else [])]


def verdict(report):
    (result,) = report.results
    return result.verdict, result.state, result.blocked_by


# ---------------------------------------------------------------------------
# A state's model.
# ---------------------------------------------------------------------------

OPEN = {
    "fasteners": [SCREW],
    "states": {"open": {"model": "open.step"}},
    "checks": {"try_states": ["open"]},
}


def opened(main, other, moved=None):
    """The covered screw, and a state whose model has the cover lifted clear."""
    return check(
        READERS[main](covered()),
        Config.from_dict(OPEN),
        models={"open.step": READERS[other](moved or covered(lift=300.0))},
    )


@EITHER_WAY
def test_the_same_part_in_a_state_s_model_is_noted_as_no_difference(main, other):
    report = opened(main, other)
    assert verdict(report) == (Verdict.TURNS, "open", ())
    assert (report.notes, report.warnings, report.exit_code) == ((), (), 0)


def test_each_way_of_reading_the_two_models_gives_one_report():
    reports = [opened(main, other).to_json_dict() for main in READERS for other in READERS]
    assert all(report == reports[0] for report in reports[1:])
    assert reports[0]["fasteners"][0]["state"] == "open"  # and it is a report of something


@EITHER_WAY
def test_a_part_renamed_in_a_state_s_model_is_noted_once_and_not_per_solid(main, other):
    report = opened(main, other, moved=covered(lift=300.0, cover="hatch"))
    assert report.notes == (
        "state 'open': its model open.step lacks 1 part of the main model's: cover; "
        "has 1 part the main model doesn't: hatch",
    )


def test_a_part_that_only_shares_a_name_is_still_a_part_the_other_lacks():
    # Two parts named cover in the main model, numbered cover and cover#2; one cover of
    # two solids in the state's: the second part is missing there, whatever its piece is called.
    plate, bolt, cover = covered()
    slab, pad = cover[1].solids()
    two_parts = in_pieces([plate, bolt, ("cover", slab), ("cover", pad)])
    assert [(part.name, part.piece_of) for part in two_parts][2:] == [
        ("cover", None),
        ("cover#2", None),
    ]
    report = check(
        two_parts, Config.from_dict(OPEN), models={"open.step": in_pieces(covered(lift=300.0))}
    )
    assert report.notes == (
        "state 'open': its model open.step lacks 1 part of the main model's: cover#2",
    )


# ---------------------------------------------------------------------------
# A build step's model.
# ---------------------------------------------------------------------------

BUILD = {
    "fasteners": [SCREW],
    "build": [
        {"step": "screw", "add": ["plate", "bolt"], "model": "half.step"},
        {"step": "cover", "add": ["cover"]},
    ],
}


def built(report):
    return {
        placed.result.name: (placed.result.verdict, placed.step, placed.result.blocked_by)
        for placed in report.build.placed
    }


def half_built(main, other, half=None, engine="mesh"):
    """The covered screw, put in before its cover in a step with a model of its own."""
    return check(
        READERS[main](covered()),
        Config.from_dict(BUILD),
        models={"half.step": READERS[other](half or covered())},
        engine=engine,
    )


@EITHER_WAY
@pytest.mark.parametrize("engine", ENGINES)
def test_a_piece_is_still_to_come_when_its_part_is(main, other, engine):
    # The cover goes on after the screw: neither of its solids is there when the
    # screw goes in, though both are in the step's model.
    report = half_built(main, other, engine=engine)
    assert built(report) == {"bolt": (Verdict.TURNS, "screw", ())}
    assert verdict(report) == (
        Verdict.BLOCKED,
        None,
        ("cover#2" if main == "in-pieces" else "cover",),
    )
    assert report.notes == ()


@EITHER_WAY
def test_a_jig_of_two_solids_stays_whole_and_is_noted_once(main, other):
    # A jig only the step's model has, a block aside and a bar 10 over the screw's
    # head where the cover's pad will be: no step adds it, so it is there, all of it.
    block, bar = Pos(-70, 0, 20) * Box(40, 40, 40), Pos(0, 0, 38) * Box(30, 30, 4)
    jig = Compound([block.solid(), bar.solid()])
    report = half_built(main, other, half=covered(jig=jig))
    in_the_way = "jig#2" if other == "in-pieces" else "jig"
    assert built(report) == {"bolt": (Verdict.BLOCKED, "screw", (in_the_way,))}
    assert report.notes == (
        "build step 'screw': its model half.step has 1 part the main model doesn't: jig",
    )


@EITHER_WAY
def test_a_part_a_step_s_model_lacks_is_noted_once_and_not_per_solid(main, other):
    # One step adds everything, and its model hasn't the cover at all.
    steps = [{"step": "all", "add": ["*"], "model": "half.step"}]
    report = check(
        READERS[main](covered()),
        Config.from_dict({"fasteners": [SCREW], "build": steps}),
        models={"half.step": READERS[other](covered()[:2])},
    )
    assert report.notes == (
        "build step 'all': its model half.step lacks 1 part added by then: cover",
    )


# ---------------------------------------------------------------------------
# A part that only shares a name: numbered as a piece would be, and a part still.
# ---------------------------------------------------------------------------


def two_covers(lift=0.0):
    """The covered screw with its cover's two solids as two parts, both named cover."""
    plate, bolt, cover = covered(lift)
    slab, pad = cover[1].solids()
    return in_pieces([plate, bolt, ("cover", slab), ("cover", pad)])


ONE_STEP = {"fasteners": [SCREW], "build": [{"step": "all", "add": ["*"], "model": "half.step"}]}


def test_a_step_s_model_lacks_a_part_whose_name_one_of_its_pieces_has():
    # Two parts named cover in the main model; one cover of two solids in the step's.
    report = check(
        two_covers(), Config.from_dict(ONE_STEP), models={"half.step": in_pieces(covered())}
    )
    assert report.notes == (
        "build step 'all': its model half.step lacks 1 part added by then: cover#2",
    )


def test_a_step_s_model_has_a_part_whose_name_a_piece_of_the_main_model_has():
    report = check(
        in_pieces(covered()), Config.from_dict(ONE_STEP), models={"half.step": two_covers()}
    )
    assert report.notes == (
        "build step 'all': its model half.step has 1 part the main model doesn't: cover#2",
    )


def test_a_piece_goes_by_its_part_though_the_main_model_has_a_part_of_its_name():
    # In the main model cover#2 is a part of its own, a pad over the screw, and it goes
    # on with the screw; the cover, a slab aside, comes later. In the step's model the
    # cover is one part of two solids, so its cover#2 is the cover's piece: still to
    # come with the cover, and not in the screw's way. The note says the pad is missing.
    steps = [
        {"step": "screw", "add": ["plate", "bolt", "cover#2"], "model": "half.step"},
        {"step": "cover", "add": ["cover"]},
    ]
    report = check(
        two_covers(),
        Config.from_dict({"fasteners": [SCREW], "build": steps}),
        models={"half.step": in_pieces(covered())},
    )
    assert built(report) == {"bolt": (Verdict.TURNS, "screw", ())}
    assert report.notes == (
        "build step 'screw': its model half.step lacks 1 part added by then: cover#2",
    )


# ---------------------------------------------------------------------------
# The clash list, a state's model beside the main one (issue #209).
# ---------------------------------------------------------------------------

UP = {"checks": {"detect": False}, "states": {"up": {"model": "up.step"}}}


def pinned(lift=0.0, second=0.0, lever=0.0):
    """A block under z = 0, a rod of two pins, one part, and a lever beside them.

    Each pin is drawn 1 into the block: pi 9 = 28.3 mm^3 of the first, pi 4 = 12.6 of the
    second, 40.8 of the rod whole. ``lift`` raises the rod and ``second`` its second pin
    alone, clear of the block; the lever, 2 clear, comes down by ``lever``.
    """
    block = Pos(0, 0, -5) * Box(80, 20, 10)
    first = Pos(-8, 0, 14 + lift) * Cylinder(3, 30)
    other = Pos(8, 0, 14 + lift + second) * Cylinder(2, 30)
    arm = Pos(30, 0, 7 + lever) * Box(4, 4, 10)
    return [("block", block), ("rod", Compound([first.solid(), other.solid()])), ("lever", arm)]


def told(found):
    return [(c.first, c.second, round(c.volume, 1), c.state) for c in found.found]


def in_state(found):
    return [row for row in told(found) if row[3] is not None]


def clashes(main, other, state_parts, main_parts=None):
    return find_clashes(
        READERS[main](main_parts if main_parts is not None else pinned()),
        Config.from_dict(UP),
        models={"up.step": READERS[other](state_parts)},
    )


@EITHER_WAY
def test_a_state_s_model_of_the_same_parts_adds_no_clash(main, other):
    # The same parts in the same place: what the main model has by itself is all of it.
    alone = find_clashes(READERS[main](pinned()), Config.from_dict({"checks": {"detect": False}}))
    found = clashes(main, other, pinned())
    want = {
        "in-pieces": [("rod", "block", 28.3, None), ("rod#2", "block", 12.6, None)],
        "whole": [("rod", "block", 40.8, None)],
    }
    assert told(found) == told(alone) == want[main]


def test_read_one_each_way_the_piece_s_clash_was_the_state_s():
    # The fault, by its figures: the main model from shapes and the state's read from
    # STEP has no clash in the state. It said CLASH rod#2 into block 12.6 in state up.
    assert in_state(clashes("whole", "in-pieces", pinned())) == []


@EITHER_WAY
def test_a_clash_only_the_state_s_model_has_is_said_with_it(main, other):
    # The lever, one solid however it is read, 1 into the block in the state alone.
    assert in_state(clashes(main, other, pinned(lever=-3.0))) == [("lever", "block", 16.0, "up")]


@EITHER_WAY
def test_a_part_of_two_solids_that_clashes_in_the_state_alone_is_said_there(main, other):
    # The rod clear in the main model and down in the state's: told as that model has it.
    found = clashes(main, other, pinned(), main_parts=pinned(lift=5.0))
    want = {
        "in-pieces": [("rod", "block", 28.3, "up"), ("rod#2", "block", 12.6, "up")],
        "whole": [("rod", "block", 40.8, "up")],
    }
    assert told(found) == want[other]


@EITHER_WAY
def test_a_second_solid_s_clash_is_the_state_s_where_both_models_have_the_solids(main, other):
    # The first pin in the block in both models, the second in the state's alone. Two
    # models that both have the rod in pieces tell solid from solid, and the second
    # pin's clash is the state's, as it was. A model with the rod whole has the rod
    # clashing already, and the pair is said once: so it is for any part, whole.
    found = clashes(main, other, pinned(), main_parts=pinned(second=5.0))
    both_in_pieces = (main, other) == ("in-pieces", "in-pieces")
    assert in_state(found) == ([("rod#2", "block", 12.6, "up")] if both_in_pieces else [])


@pytest.mark.parametrize(
    ("first", "second"), [(first, second) for first in READERS for second in READERS]
)
def test_two_states_models_tell_one_clash_once_however_each_is_read(first, second):
    # Clear in the main model and down in both states' models, read alike or one each
    # way: the first state has it, and the second has nothing more.
    config = {**UP, "states": {"up": {"model": "up.step"}, "out": {"model": "out.step"}}}
    found = find_clashes(
        Assembly.from_shapes(pinned(lift=5.0)),
        Config.from_dict(config),
        models={"up.step": READERS[first](pinned()), "out.step": READERS[second](pinned())},
    )
    assert {row[3] for row in told(found)} == {"up"}
    assert len(told(found)) == {"in-pieces": 2, "whole": 1}[first]


def test_a_part_that_only_shares_a_name_is_told_for_itself():
    # Two rods, two parts with one name, so the second is numbered rod#2 and is no
    # piece; and a block of two solids, whole in the main model and in pieces in the
    # state's. The first rod is in the block in both; the second comes down into it in
    # the state alone. That is a clash of its own, the state's, though "rod" and "block"
    # clash already and the two models draw the block differently.
    def parts(drop):
        slab, foot = Pos(0, 0, -5) * Box(80, 20, 10), Pos(0, 0, -20) * Box(10, 10, 4)
        first, second = Pos(-8, 0, 14) * Cylinder(3, 30), Pos(8, 0, 19 - drop) * Cylinder(2, 30)
        block = Compound([slab.solid(), foot.solid()])
        return [("block", block), ("rod", first), ("rod", second)]

    state = in_pieces(parts(5.0))
    assert [(p.name, p.piece_of) for p in state] == [
        ("block", None),
        ("block#2", "block"),
        ("rod", None),
        ("rod#2", None),
    ]
    found = find_clashes(
        Assembly.from_shapes(parts(0.0)), Config.from_dict(UP), models={"up.step": state}
    )
    assert told(found) == [("rod", "block", 28.3, None), ("rod#2", "block", 12.6, "up")]
