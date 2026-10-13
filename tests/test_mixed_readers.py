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
from wrenchroom.checker import check
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
