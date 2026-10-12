"""Two parts drawn in one place, one a solid the boolean fails on, are not asked (issue #179).

A model of a kit draws the options of one part over each other: a public toolhead
has three cowlings in one place, each sharing nearly all of itself with the next.
Of such a pair OCCT's boolean is slow and comes back with what no solid could be.
Each of the three took about 7 seconds and answered -236 mm^3, which #163's guard
set aside for the meshes' 40,000: 21 of the run's 35 seconds, for answers thrown
away.

Now, where two parts' closed meshes share more than half of each one's volume, and
one of the two is a solid the boolean is known to fail on, the boolean isn't asked.
What the solids bear out of the meshes' overlap is the measure from the start, as
it was in the end before, and the clash says so. A solid it fails on is:

- one invalid as exported, which a boolean can only be approximate on (issue #85);
- one a clash's boolean has already failed on in the run, its clash told on the
  meshes: another of the options drawn over it.

Every other pair is asked as ever: sound solids drawn in one place (a fastener
drawn twice), and a failing solid's clash with any part not drawn in its place.

The solids here are 20 mm cubes, 8,000 mm^3, drawn a step along x apart: 1 apart
they share 19 x 20 x 20 = 7,600, 0.95 of each; 8 apart 4,800, 0.60; 12 apart 3,200,
0.40. A cube is made invalid by moving one corner's point a hundredth of a micron
off its edges: its faces, its volume and its mesh are as they were.
"""

import math

import pytest
from build123d import Box, Pos, Shape
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

from test_drawn_twice import M3, dup_parts
from test_mending import open_box
from test_shared import disc, failing, issue_pair
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check, find_clashes
from wrenchroom.clashes import BY_MESHES, NOT_ASKED
from wrenchroom.config import Config
from wrenchroom.engine import mesh as mesh_module
from wrenchroom.engine.exact import ExactEngine
from wrenchroom.engine.mesh import ONE_PLACE, MeshEngine
from wrenchroom.engine.scene import Engine
from wrenchroom.report import EngineNote

CUBE = 8000.0
UNSOUND = (None, False)  # what OCCT gave of the cowlings: nothing a solid could be
EMPTY = (None, True)  # and of other housings: nothing at all, and no sign of it


def cube(at=0.0, size=(20, 20, 20)):
    return Pos(at, 0, 0) * Box(*size)


def nudged(shape, by=1e-5):
    """A copy with one corner's point moved off its edges: an invalid B-rep, its faces as drawn."""
    copy = Shape.cast(BRepBuilderAPI_Copy(shape.wrapped).Shape())
    corner = TopoDS.Vertex(TopExp_Explorer(copy.wrapped, TopAbs_VERTEX).Current())
    at = BRep_Tool.Pnt_s(corner)
    BRep_Builder().UpdateVertex(corner, gp_Pnt(at.X() + by, at.Y(), at.Z()), 1e-7)
    return copy


def shares(apart):
    """What two of the cubes ``apart`` along x share, mm^3."""
    return (20 - apart) * 20 * 20.0


def test_the_hand_work():
    assert (shares(1), shares(8), shares(12)) == (7600.0, 4800.0, 3200.0)
    assert (shares(1) / CUBE, shares(8) / CUBE, shares(12) / CUBE) == (0.95, 0.6, 0.4)
    assert ONE_PLACE == 0.5


def test_a_nudged_cube_is_invalid_and_is_the_cube_it_was():
    whole, broken = cube(), nudged(cube())
    assert BRepCheck_Analyzer(whole.wrapped).IsValid()
    assert not BRepCheck_Analyzer(broken.wrapped).IsValid()
    assert broken.volume == pytest.approx(CUBE)
    engine = MeshEngine()
    mesh = engine.part_mesh(Part("broken", broken))
    assert mesh is not None  # it meshes closed
    assert mesh.volume() == pytest.approx(CUBE, abs=0.01)
    assert (engine.repaired, engine.fallbacks) == ([], [])


# ---------------------------------------------------------------------------
# Drawn in one place, and one invalid as exported: not asked.
# ---------------------------------------------------------------------------


def test_two_sound_solids_drawn_in_one_place_are_asked_as_ever(monkeypatch):
    calls = failing(monkeypatch)
    engine = MeshEngine()
    overlap = engine.shared(Part("a", cube()), Part("b", cube(1)))
    assert len(calls) == 1
    assert overlap.volume == pytest.approx(shares(1))
    assert (overlap.by_meshes, overlap.unasked) == (False, False)
    assert engine.invalid == []


@pytest.mark.parametrize("which", ["first", "second", "both"])
def test_one_of_them_invalid_they_are_measured_on_their_meshes_unasked(monkeypatch, which):
    calls = failing(monkeypatch)
    a = nudged(cube()) if which in ("first", "both") else cube()
    b = nudged(cube(1)) if which in ("second", "both") else cube(1)
    engine = MeshEngine()
    overlap = engine.shared(Part("a", a), Part("b", b))
    assert calls == []  # the boolean is not asked
    assert (overlap.by_meshes, overlap.unasked) == (True, True)
    assert overlap.volume == pytest.approx(shares(1), abs=0.01)
    assert overlap.low == pytest.approx((-9, -10, -10), abs=0.01)
    assert overlap.high == pytest.approx((10, 10, 10), abs=0.01)
    # An invalid part leaned on is noted, as a boolean's or a mended mesh's is: both
    # of them, where both are.
    assert engine.invalid == {"first": ["a"], "second": ["b"], "both": ["a", "b"]}[which]


@pytest.mark.parametrize(
    ("apart", "asked"),
    [
        (1.0, 0),  # 0.95 of each
        (8.0, 0),  # 0.60
        (9.8, 0),  # 0.51
        (10.2, 1),  # 0.49: not one place, and asked
        (12.0, 1),  # 0.40
        (19.0, 1),  # 0.05
    ],
)
def test_one_place_is_more_than_half_of_each(monkeypatch, apart, asked):
    calls = failing(monkeypatch)
    engine = MeshEngine()
    overlap = engine.shared(Part("a", nudged(cube())), Part("b", cube(apart)))
    assert len(calls) == asked
    assert overlap.volume == pytest.approx(shares(apart), abs=0.01)
    assert overlap.unasked is (asked == 0)
    assert overlap.by_meshes is (asked == 0)


@pytest.mark.parametrize(
    ("size", "share", "asked"),
    [
        ((20, 20, 30), 0.667, 0),  # the cube is two thirds of it
        ((20, 20, 38), 0.526, 0),
        ((20, 20, 42), 0.476, 1),  # under half of the larger: not one place
        ((20, 20, 60), 0.333, 1),
    ],
)
def test_the_half_is_of_the_larger_too(monkeypatch, size, share, asked):
    # The invalid cube wholly inside a block: all of the cube, and this much of the block.
    calls = failing(monkeypatch)
    assert round(CUBE / math.prod(size), 3) == share
    engine = MeshEngine()
    overlap = engine.shared(Part("a", nudged(cube())), Part("b", cube(size=size)))
    assert len(calls) == asked
    assert overlap.volume == pytest.approx(CUBE, abs=0.01)
    assert overlap.unasked is (asked == 0)


def test_an_invalid_part_s_clash_with_a_part_not_in_its_place_is_exact_as_ever(monkeypatch):
    # A bar 10 x 4 x 4 from x 3 to 13: 7 x 4 x 4 = 112 mm^3 of it in the cube, all but
    # none of the cube. And a peg wholly inside it: all of the peg, 64 of 8,000.
    calls = failing(monkeypatch)
    engine = MeshEngine()
    block = Part("block", nudged(cube()))
    bar = engine.shared(block, Part("bar", Pos(8, 0, 0) * Box(10, 4, 4)))
    peg = engine.shared(block, Part("peg", Box(4, 4, 4)))
    assert len(calls) == 2
    assert (bar.volume, bar.by_meshes, bar.unasked) == (pytest.approx(112.0), False, False)
    assert (peg.volume, peg.by_meshes, peg.unasked) == (pytest.approx(64.0), False, False)


def test_without_a_closed_mesh_of_both_the_boolean_is_asked(monkeypatch):
    # An open shell made a solid: invalid, and no mesh of it closes. There is no
    # second opinion to measure on, so the boolean is the measure, as before.
    calls = failing(monkeypatch)
    engine = MeshEngine()
    slab = Part("slab", open_box(100, 100, 20, 0))
    twin = Part("twin", Pos(0, 0, 10) * Box(100, 100, 20))
    assert engine.part_mesh(slab) is None
    engine.shared(slab, twin)
    assert len(calls) == 1


def test_what_the_solids_bear_out_is_the_measure_and_nothing_where_they_bear_none(monkeypatch):
    # The meshes' overlap is kept where points deep in it lie inside both solids. A
    # solid that says none of them is inside it bears nothing out: no clash.
    monkeypatch.setattr(Engine, "inside", lambda self, part, point: part.name != "a")
    assert MeshEngine().shared(Part("a", nudged(cube())), Part("b", cube(1))) is None


def test_unasked_it_is_measured_as_a_failed_boolean_was(monkeypatch):
    # The same two parts, the boolean asked and failing as OCCT's did: the measure
    # the rule now goes to from the start. Volume, surface and box are the same.
    a, b = Part("a", nudged(cube())), Part("b", cube(1))
    unasked = MeshEngine().shared(a, b)
    monkeypatch.setattr(mesh_module, "ONE_PLACE", 1.0)  # no two parts are one place
    calls = failing(monkeypatch, UNSOUND)
    asked = MeshEngine().shared(a, b)
    assert len(calls) == 1
    assert (asked.by_meshes, asked.unasked, unasked.unasked) == (True, False, True)
    assert unasked == asked  # volume, surface and box
    assert unasked.volume == asked.volume


# ---------------------------------------------------------------------------
# Drawn in one place, and a boolean has failed on one already: not asked.
# ---------------------------------------------------------------------------


def options():
    """Three sound cubes drawn 1 apart: 7,600 shared by neighbours, 7,200 by the outer two."""
    return Part("a", cube()), Part("b", cube(1)), Part("c", cube(2))


def test_three_sound_options_are_each_asked(monkeypatch):
    calls = failing(monkeypatch)
    engine = MeshEngine()
    a, b, c = options()
    found = [engine.shared(a, b), engine.shared(a, c), engine.shared(b, c)]
    assert len(calls) == 3
    assert [round(o.volume, 1) for o in found] == [7600.0, 7200.0, 7600.0]
    assert not any(o.by_meshes or o.unasked for o in found)


def test_the_first_failed_boolean_is_the_last_asked_of_the_three(monkeypatch):
    calls = failing(monkeypatch, UNSOUND)
    engine = MeshEngine()
    a, b, c = options()
    first = engine.shared(a, b)
    assert (len(calls), first.by_meshes, first.unasked) == (1, True, False)  # asked, and failed
    second, third = engine.shared(a, c), engine.shared(b, c)
    assert len(calls) == 1  # a failed on, then b: neither is asked again of one in its place
    assert [(o.by_meshes, o.unasked) for o in (second, third)] == [(True, True), (True, True)]
    assert [round(o.volume, 1) for o in (first, second, third)] == [7600.0, 7200.0, 7600.0]
    assert engine.invalid == []  # sound solids all: none is noted


def test_a_boolean_that_loses_what_the_solids_bear_out_marks_them_too(monkeypatch):
    # Empty, where the meshes share 7,600 and the solids bear it out: told on the
    # meshes, so failed. (A cube has no face to merge, and is asked once.)
    calls = failing(monkeypatch, EMPTY)
    engine = MeshEngine()
    a, b, c = options()
    first = engine.shared(a, b)
    assert (len(calls), first.by_meshes, first.unasked) == (1, True, False)
    assert engine.shared(a, c).unasked
    assert len(calls) == 1


def test_a_boolean_that_comes_right_when_asked_again_marks_nothing(monkeypatch):
    # #163's disc on its bored plate: empty, then right with the disc's faces
    # merged. Exact, so nothing failed, and the disc's twin, drawn 0.5 from it, is
    # asked of it.
    calls = failing(monkeypatch, EMPTY)
    engine = MeshEngine()
    boss, bracket = issue_pair()
    first = engine.shared(boss, bracket)
    assert (len(calls), first.by_meshes) == (2, False)
    twin = engine.shared(boss, Part("twin", Pos(0.5, 0, 0) * disc()))
    assert (len(calls), twin.by_meshes, twin.unasked) == (3, False, False)


def test_failing_both_times_it_marks_them(monkeypatch):
    # The same, empty with the faces merged too: on the meshes, and the twin unasked.
    calls = failing(monkeypatch, EMPTY, EMPTY)
    engine = MeshEngine()
    boss, bracket = issue_pair()
    assert engine.shared(boss, bracket).by_meshes
    twin = engine.shared(boss, Part("twin", Pos(0.5, 0, 0) * disc()))
    assert (len(calls), twin.by_meshes, twin.unasked) == (2, True, True)


def test_a_part_a_boolean_failed_on_is_asked_of_a_part_not_in_its_place(monkeypatch):
    calls = failing(monkeypatch, UNSOUND)
    engine = MeshEngine()
    a, b, _ = options()
    engine.shared(a, b)
    bar = engine.shared(a, Part("bar", Pos(-8, 0, 0) * Box(10, 4, 4)))
    assert len(calls) == 2
    assert (bar.volume, bar.by_meshes, bar.unasked) == (pytest.approx(112.0), False, False)


def test_what_failed_is_this_run_s_alone(monkeypatch):
    calls = failing(monkeypatch, UNSOUND)
    a, b, c = options()
    MeshEngine().shared(a, b)
    assert not MeshEngine().shared(a, c).unasked  # another run's engine knows nothing of it
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# --exact measures the same way.
# ---------------------------------------------------------------------------


def test_the_exact_engine_does_not_ask_either_and_notes_the_invalid_part(monkeypatch):
    calls = failing(monkeypatch)
    engine = ExactEngine()
    overlap = engine.shared(Part("a", nudged(cube())), Part("b", cube(1)))
    assert calls == []
    assert (overlap.by_meshes, overlap.unasked) == (True, True)
    assert overlap.volume == pytest.approx(shares(1), abs=0.01)
    assert engine.invalid == ["a"]  # in its own list, the run's


# ---------------------------------------------------------------------------
# The clash list, in every format.
# ---------------------------------------------------------------------------


def kit():
    """Three options of one housing drawn over each other, each invalid, and a bar in all
    three: 10 x 4 x 4 from x -13 to -3, so 7, 6 and 5 of its length, 112, 96 and 80 mm^3."""
    return Assembly(
        [
            Part("cowl_a", nudged(cube())),
            Part("cowl_b", nudged(cube(1))),
            Part("cowl_c", nudged(cube(2))),
            Part("bar", Pos(-8, 0, 0) * Box(10, 4, 4)),
        ]
    )


def test_three_invalid_options_are_three_clashes_and_no_boolean_between_them(monkeypatch, engine):
    calls = failing(monkeypatch)
    found = find_clashes(kit(), Config(), engine=engine)
    assert [(c.first, c.second, round(c.volume), c.by_meshes, c.unasked) for c in found.found] == [
        ("bar", "cowl_a", 112, False, False),
        ("bar", "cowl_b", 96, False, False),
        ("bar", "cowl_c", 80, False, False),
        ("cowl_a", "cowl_b", 7600, True, True),
        ("cowl_a", "cowl_c", 7200, True, True),
        ("cowl_b", "cowl_c", 7600, True, True),
    ]
    assert len(calls) == 3  # the bar's alone, exact as ever: none between the options
    assert found.lines() == [
        "6 clashes (overlap over 0.05 mm^3)",
        "CLASH bar into cowl_a  112.0 mm^3",
        "CLASH bar into cowl_b  96.0 mm^3",
        "CLASH bar into cowl_c  80.0 mm^3",
        f"CLASH cowl_a into cowl_b  7600.0 mm^3  ({NOT_ASKED})",
        f"CLASH cowl_a into cowl_c  7200.0 mm^3  ({NOT_ASKED})",
        f"CLASH cowl_b into cowl_c  7600.0 mm^3  ({NOT_ASKED})",
    ]
    assert (found.unsure, found.exit_code) == ((), 1)


def test_the_words_say_which_of_the_two_it_was():
    assert BY_MESHES == "measured on their meshes: the solids' boolean failed"
    assert NOT_ASKED == (
        "measured on their meshes: drawn in one place, and one is a solid the boolean fails on"
    )


def test_a_failed_boolean_says_failed_and_the_next_says_not_asked(monkeypatch):
    calls = failing(monkeypatch, UNSOUND)
    a, b, c = options()
    found = find_clashes(Assembly([a, b, c]), Config())
    assert len(calls) == 1
    assert found.lines()[1:] == [
        f"CLASH a into b  7600.0 mm^3  ({BY_MESHES})",
        f"CLASH a into c  7200.0 mm^3  ({NOT_ASKED})",
        f"CLASH b into c  7600.0 mm^3  ({NOT_ASKED})",
    ]


def test_the_json_and_the_markdown_say_it_too():
    found = find_clashes(kit(), Config())
    document = found.to_json()["found"]
    assert [(e["parts"], e["by_meshes"], e["unasked"]) for e in document] == [
        (["bar", "cowl_a"], False, False),
        (["bar", "cowl_b"], False, False),
        (["bar", "cowl_c"], False, False),
        (["cowl_a", "cowl_b"], True, True),
        (["cowl_a", "cowl_c"], True, True),
        (["cowl_b", "cowl_c"], True, True),
    ]
    assert document[3]["volume"] == pytest.approx(7600.0, abs=0.01)
    page = found.markdown_text("kit.step")
    assert f"| `cowl_a` | `cowl_b` | 7600.0 | {NOT_ASKED} |" in page
    assert "| `bar` | `cowl_a` | 112.0 |  |" in page


def test_check_with_clashes_notes_the_invalid_parts_it_leaned_on(engine):
    report = check(kit(), Config(), clashes=True, engine=engine)
    assert EngineNote("invalid", ("cowl_a", "cowl_b", "cowl_c")) in report.engine_notes
    assert f"CLASH cowl_a into cowl_b  7600.0 mm^3  ({NOT_ASKED})" in report.terminal_lines()
    assert (
        "NOTE 3 parts are invalid as exported, so a collision with one is approximate: "
        "cowl_a, cowl_b, cowl_c"
    ) in report.terminal_lines()


def test_a_fastener_drawn_twice_is_asked_and_exact_as_ever(monkeypatch):
    # Two sound screws in one place share all of themselves: one place, and asked.
    calls = failing(monkeypatch)
    parts = Assembly([Part(name, shape) for name, shape in dup_parts()])
    config = Config.from_dict({"fasteners": [{"parts": "M3x* SHCS", **M3}]})
    found = find_clashes(parts, config)
    (twice,) = [c for c in found.found if c.hint == "one fastener drawn twice"]
    assert (round(twice.volume, 1), twice.by_meshes, twice.unasked) == (120.8, False, False)
    assert len(calls) >= 1
