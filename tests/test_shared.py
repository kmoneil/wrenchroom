"""A boolean's answer is held to what the two meshes share (issue #163).

OCCT's boolean fails without a word. For two parts drawn far into each other it
comes back empty (a face of one split along an edge the other's bore runs on; two
housings, variants of one part, drawn in one place), or with a piece of what they
share, or with a solid turned inside out; and for two that only touch, with the
whole of the smaller. wrenchroom took each answer as given: three housings sharing
40,000 mm^3 on a public model were no clash at all.

Now the answer is compared with what the two parts' meshes share. Where the two
differ by more than the floor and a factor of two, the solids themselves are asked,
point by point, which no boolean has a hand in: the lumps of the meshes' overlap
with points deep inside them inside both solids are the overlap. The boolean is
asked once more, the solids' faces merged; failing that too, the overlap is
measured on the meshes, and says so.

Most tests here give the engine a boolean that fails as OCCT's does, so they hold
on every platform, whatever OCCT does there. The volumes, by hand:

- a bar 10 x 4 x 4 from x 3 to 13, in a block 20 x 20 x 10 about the origin: x 3 to
  10 of it, 7 x 4 x 4 = 112 mm^3, inside 2 (28 + 28 + 16) = 144 mm^2;
- a tab 2 x 2 from z 3 to 7, in a block up to z 5: 2 x 2 x 2 = 8 mm^3;
- the issue's disc 7 across on a plate 1.0 up it, bored 4.1: pi (3.5^2 - 2.05^2) =
  25.28 mm^3;
- #116's M4 button head in a block: 62.35 mm^3 (test_head_clash.py);
- an insert 5 across and 4 long in a hole 4.6 across: pi (2.5^2 - 2.3^2) 4 = 12.06.
"""

import base64
import itertools
import json
import math

import numpy as np
import pytest
from build123d import Box, Compound, Cylinder, Pos, Rot, Shape
from manifold3d import Manifold

from test_drawn_twice import M3, dup_parts
from test_head_clash import BUTTON, HEAD, button, plate
from test_set_in import INSERT, block, insert, shell
from wrenchroom import clashes as clashes_module
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check, find_clashes
from wrenchroom.config import Config
from wrenchroom.engine import exact as exact_module
from wrenchroom.engine import mesh as mesh_module
from wrenchroom.engine.exact import ExactEngine, cut, measured_common, possible
from wrenchroom.engine.mesh import WITNESS_DEPTH, MeshEngine, _agree, inner_points
from wrenchroom.engine.scene import HIT_MIN_VOLUME, PartOverlap
from wrenchroom.view import view_data

BY_MESHES = "measured on their meshes: the solids' boolean failed"
BAR_IN_BLOCK = 7 * 4 * 4.0
DISC_IN_PLATE = math.pi * (3.5**2 - 2.05**2)


def the_block():
    return Part("block", Box(20, 20, 10))


def bar(at=8.0):
    """A bar 10 x 4 x 4 about x = ``at``: 3 to 13, 7 of it in the block; at 15, touching it."""
    return Part("bar", Pos(at, 0, 0) * Box(10, 4, 4))


def box_of(overlap):
    """An overlap's box, its low corner then its high."""
    return (*overlap.low, *overlap.high)


def failing(monkeypatch, *answers):
    """Give the mesh engine a boolean that answers as told, then as OCCT does; the calls made."""
    real, left, calls = measured_common, list(answers), []

    def boolean(a, b):
        calls.append((a, b))
        return left.pop(0) if left else real(a, b)

    monkeypatch.setattr(mesh_module, "measured_common", boolean)
    return calls


def always(monkeypatch, answer):
    """A boolean that gives one answer to everything, whoever asks it."""
    monkeypatch.setattr(mesh_module, "measured_common", lambda a, b: answer)
    monkeypatch.setattr(exact_module, "measured_common", lambda a, b: answer)


EMPTY = (None, True)


def test_the_hand_work():
    assert (BAR_IN_BLOCK, f"{DISC_IN_PLATE:.2f}", f"{shell(5.0, 4.6):.2f}") == (
        112.0,
        "25.28",
        "12.06",
    )


# ---------------------------------------------------------------------------
# An answer no solid could be.
# ---------------------------------------------------------------------------


def test_a_solid_has_a_volume_and_no_less_surface_than_a_ball_of_it():
    ball = 4 / 3 * math.pi, 4 * math.pi  # of radius 1: the least surface for its volume
    assert possible(*ball)
    assert possible(1.0, 6.0)  # a cube
    assert not possible(ball[0], 0.99 * ball[1])
    assert not possible(0.0, 1.0)
    # The public models' own: an insert in its part, 7.57 mm^3 inside 5.73 mm^2, where
    # a ball of that volume has 18.6; and two housings in one place, a solid inside out.
    assert f"{(36 * math.pi) ** (1 / 3) * 7.57 ** (2 / 3):.1f}" == "18.6"
    assert not possible(7.57, 5.73)
    assert not possible(-236.14, 140.86)


def test_a_boolean_s_answer_comes_with_whether_a_solid_could_be_it():
    overlap, sound = measured_common(the_block().shape, bar().shape)
    assert sound
    assert (overlap.volume, overlap.area) == pytest.approx((BAR_IN_BLOCK, 144.0))
    assert not overlap.by_meshes
    assert measured_common(the_block().shape, bar(15.0).shape) == (None, True)  # touching
    assert measured_common(the_block().shape, bar(40.0).shape) == (None, True)  # apart


def test_a_solid_inside_out_is_no_answer(monkeypatch):
    # What OCCT gave for two housings drawn in one place: one piece, its volume under
    # nothing. A box reversed is one: the same faces, each turned to face in.
    inside_out = Shape.cast(Box(7, 4, 4).wrapped.Reversed())
    assert inside_out.volume == pytest.approx(-112.0)
    monkeypatch.setattr("wrenchroom.engine.exact.common", lambda a, b: inside_out)
    assert measured_common(the_block().shape, bar().shape) == (None, False)


def test_a_boolean_occt_calls_failed_is_no_answer(monkeypatch):
    monkeypatch.setattr("wrenchroom.engine.exact.common", lambda a, b: None)
    assert measured_common(the_block().shape, bar().shape) == (None, False)


@pytest.mark.parametrize(("thick", "sound"), [(0.1, True), (0.15, False)])
def test_a_speck_under_nothing_is_no_sign_of_a_fault(monkeypatch, thick, sound):
    # A piece inside out beside the overlap itself, 0.2 square: 0.1 thick it is
    # -0.004 mm^3, under a tenth of the floor, and the answer is still one a solid
    # could be (a public model's 18.2 mm^3 came with a sliver of -0.0014); 0.15
    # thick, -0.006, it is not. Counted either way, as it always was.
    speck = Shape.cast((Pos(40, 0, 0) * Box(0.2, 0.2, thick)).wrapped.Reversed())
    both = Compound(children=[Pos(6.5, 0, 0) * Box(7, 4, 4), speck])
    assert speck.volume == pytest.approx(-0.04 * thick)
    monkeypatch.setattr("wrenchroom.engine.exact.common", lambda a, b: both)
    overlap, said = measured_common(the_block().shape, bar().shape)
    assert said is sound
    assert overlap.volume == pytest.approx(BAR_IN_BLOCK - 0.04 * thick)


# ---------------------------------------------------------------------------
# Points deep inside a mesh.
# ---------------------------------------------------------------------------


def room_in_a_box(points, size):
    """How far each point is from the nearest wall of a box at the origin's corner."""
    return np.minimum(points, np.array(size) - points).min(axis=1)


def test_points_inside_a_cube_are_well_inside_it():
    # From the middle of each of its twelve triangles straight in to the far wall,
    # 1 off: half way, 0.5 in, and a third of the way along the face from its edges.
    points = inner_points(Manifold.cube([1, 1, 1]))
    assert len(points) == 12
    assert room_in_a_box(points, (1, 1, 1)) == pytest.approx(np.full(12, 1 / 3))


@pytest.mark.parametrize(("thick", "some"), [(0.03, False), (0.039, False), (0.05, True)])
def test_a_plate_thinner_than_twice_the_depth_has_no_point_deep_enough(thick, some):
    # Its middle is half its thickness from each face: 0.02 is the least asked.
    points = inner_points(Manifold.cube([10, 10, thick]))
    assert bool(len(points)) is some
    assert WITNESS_DEPTH == 0.02
    if some:
        assert room_in_a_box(points, (10, 10, thick)).min() >= WITNESS_DEPTH


def test_a_chord_down_a_sliver_s_length_is_not_its_depth():
    # A sliver 10 long and 0.03 square: from its end the far wall is 10 off, and the
    # middle of that chord is still 0.015 from its sides.
    assert len(inner_points(Manifold.cube([10, 0.03, 0.03]))) == 0
    # 0.1 square, its points are the middles of chords across it, each from a third
    # of the way over a side: 0.05 from two walls and 0.033 from a third.
    deep = inner_points(Manifold.cube([10, 0.1, 0.1]))
    assert len(deep)
    assert room_in_a_box(deep, (10, 0.1, 0.1)) == pytest.approx(np.full(len(deep), 0.1 / 3))


def test_the_points_come_deepest_first():
    # A slab 0.1 thick with a cube 2 on a side on it: the cube's middle first.
    lump = Manifold.cube([10, 10, 0.1]) + Manifold.cube([2, 2, 2]).translate([4, 4, 0])
    points = inner_points(lump, rays=48)
    assert tuple(points[0]) == pytest.approx((5, 5, 1), abs=0.5)
    assert len(inner_points(Manifold())) == 0  # nothing has no inside


# ---------------------------------------------------------------------------
# The boolean and the meshes, compared.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("said", "theirs", "agreed"),
    [
        (0.0, 0.05, True),  # within the floor
        (0.0, 0.06, False),
        (1.0, 1.9, True),  # within a factor of two
        (1.0, 2.1, False),
        (2.1, 1.0, False),  # either way
        (2.765, 2.883, True),  # an insert's knurl in its hole, on a public model
        (0.016, 6.476, False),  # and one the boolean lost
        (39.29, 0.0, False),  # and one it made up
    ],
)
def test_they_agree_within_the_floor_or_a_factor_of_two(said, theirs, agreed):
    assert _agree(said, theirs) is agreed
    assert HIT_MIN_VOLUME == 0.05


def test_two_parts_overlap_is_the_boolean_s_where_the_meshes_agree(monkeypatch):
    calls = failing(monkeypatch)
    overlap = MeshEngine().shared(the_block(), bar())
    assert (overlap.volume, overlap.area) == pytest.approx((BAR_IN_BLOCK, 144.0))
    assert (overlap.by_meshes, overlap.shape is not None, len(calls)) == (False, True, 1)
    assert box_of(overlap) == pytest.approx((3, -2, -2, 10, 2, 2))


def test_an_empty_boolean_for_parts_drawn_into_each_other_is_not_taken(monkeypatch):
    # The issue: the boolean comes back empty, and again with the faces merged. The
    # meshes share 112 mm^3, and points deep in that are inside both solids.
    always(monkeypatch, EMPTY)
    engine = MeshEngine()
    overlap = engine.shared(the_block(), bar())
    assert overlap.by_meshes
    assert overlap.shape is None
    assert (overlap.volume, overlap.area) == pytest.approx((BAR_IN_BLOCK, 144.0))
    assert box_of(overlap) == pytest.approx((3, -2, -2, 10, 2, 2))
    vertices, triangles = overlap.mesh
    assert (vertices.shape, triangles.shape) == ((8, 3), (12, 3))
    assert overlap.corners() is vertices
    assert engine.unsure == []


def issue_pair(offset=0.0, over=0.0):
    """The issue's disc, its underside in three pieces, and its bored plate."""
    return Part("boss", disc()), Part("bracket", bored_plate(offset, over))


def test_the_boolean_is_asked_once_more_with_the_faces_merged(monkeypatch):
    # Empty the first time, right the second: the exact figure, and its solid.
    calls = failing(monkeypatch, EMPTY)
    overlap = MeshEngine().shared(*issue_pair())
    assert len(calls) == 2
    assert (overlap.by_meshes, overlap.shape is not None) == (False, True)
    assert overlap.volume == pytest.approx(DISC_IN_PLATE, abs=0.01)


def test_with_no_face_to_merge_it_is_not_asked_what_it_was_asked_before(monkeypatch):
    # A block and a bar, six faces each, merged or not: the meshes' own figure.
    calls = failing(monkeypatch, EMPTY)
    overlap = MeshEngine().shared(the_block(), bar())
    assert (len(calls), overlap.by_meshes) == (1, True)
    assert overlap.volume == pytest.approx(BAR_IN_BLOCK)


def test_it_is_asked_of_the_solids_with_their_faces_merged(monkeypatch):
    # The issue's disc has its underside in three pieces, round the rod that cut
    # it: five faces, and merged, three. That is the solid the second asking is of.
    boss, bracket = Part("boss", disc()), Part("bracket", bored_plate(3e-7, 1e-7))
    calls = failing(monkeypatch, EMPTY)
    overlap = MeshEngine().shared(boss, bracket)
    assert overlap.volume == pytest.approx(DISC_IN_PLATE, abs=0.01)
    assert [len(a.faces()) for a, _ in calls] == [5, 3]
    assert [len(b.faces()) for _, b in calls] == [7, 7]  # the plate has none to merge


def test_a_second_answer_no_solid_could_be_is_not_taken(monkeypatch):
    # The right volume the second time, inside 3 mm^2: the meshes' own figure, a
    # little under the 25.28 (the disc's mesh lies inside it).
    calls = failing(monkeypatch, EMPTY, (PartOverlap(25.28, 3.0, (0, 0, 0), (1, 1, 1)), False))
    overlap = MeshEngine().shared(*issue_pair())
    assert (len(calls), overlap.by_meshes) == (2, True)
    assert overlap.volume == pytest.approx(DISC_IN_PLATE, rel=0.015)


def test_a_second_answer_far_from_the_meshes_is_not_taken_either(monkeypatch):
    # The second time a tenth of it: the meshes' own figure is the measure.
    part = measured_common(the_block().shape, Pos(8, 0, 0) * Box(10, 1, 0.4))
    assert part[0].volume == pytest.approx(2.8)
    calls = failing(monkeypatch, EMPTY, part)
    overlap = MeshEngine().shared(*issue_pair())
    assert (len(calls), overlap.by_meshes) == (2, True)
    assert overlap.volume == pytest.approx(DISC_IN_PLATE, rel=0.015)


def test_an_empty_boolean_for_parts_that_only_touch_stands(monkeypatch):
    calls = failing(monkeypatch)
    engine = MeshEngine()
    assert engine.shared(the_block(), bar(15.0)) is None
    assert engine.shared(the_block(), bar(40.0)) is None
    assert len(calls) == 2  # asked once of each, and never again


def shaft_in_its_bore():
    """A shaft 50 across in a bore of its own radius, turned 3 degrees in it.

    The two are drawn on one cylinder, and share nothing. Their meshes do: each is
    a polygon inside the circle, and turned, one's corners stand past the other's
    sides: 31 mm^3 in 36 slivers, each deep enough to ask about.
    """
    host = Part("host", Box(200, 100, 10) - Pos(-50, 0, 0) * Cylinder(25, 20))
    shaft = Part("shaft", Pos(-50, 0, 0) * Rot(0, 0, 3) * Cylinder(25, 30))
    return host, shaft


def test_two_faces_drawn_in_one_place_overlap_on_their_meshes_and_are_no_clash():
    # The meshes share more than the floor, in slivers deep enough to ask about, and
    # no point of them is inside both solids: inside the shaft is outside the bore's
    # wall. The boolean's nothing stands.
    host, shaft = shaft_in_its_bore()
    engine = MeshEngine()
    assert engine.meshes_share(host, shaft) > 20.0
    slivers = (engine.part_mesh(host) ^ engine.part_mesh(shaft)).decompose()
    asked = [lump for lump in slivers if len(inner_points(lump))]
    assert len(asked) > 20  # the solids were asked of each, and said no
    assert all(engine.inside_both(lump, host, shaft) is False for lump in asked)
    assert engine.shared(host, shaft) is None
    assert engine.shared(shaft, host) is None  # whichever is asked about first
    assert ExactEngine().shared(host, shaft) is None


@pytest.mark.parametrize(
    ("answers", "asked", "inside"),
    [
        ("YYY...", 3, True),  # three agree: no further
        ("NNNYYY", 3, False),  # either way
        ("YNYNNN", 6, False),  # two of six
        ("YNYYNN", 6, True),  # half of them
        ("NYNNYY", 6, True),
        ("YN", 2, True),  # all there are
        ("N", 1, False),
        ("", 0, None),  # none deep enough: nothing to say
    ],
)
def test_a_lump_is_inside_both_solids_where_half_its_points_are(
    monkeypatch, answers, asked, inside
):
    # Each point asked of both solids, deepest first. Three alike are enough;
    # otherwise six are asked, and at least half inside both, the lump is.
    points = np.array([(float(i), 0.0, 0.0) for i, _ in enumerate(answers)]).reshape(-1, 3)
    monkeypatch.setattr(mesh_module, "inner_points", lambda lump: points)
    engine, seen = MeshEngine(), []

    def inside_of(part, point):
        seen.append((part.name, point[0]))
        return part.name == "block" or answers[int(point[0])] == "Y"

    monkeypatch.setattr(engine, "inside", inside_of)
    assert engine.inside_both(Manifold(), the_block(), bar()) is inside
    assert len({at for _, at in seen}) == asked
    assert [name for name, _ in seen[:2]] == ["block", "bar"][: len(seen)]  # both are asked


def with_a_tab(*tabs):
    """The shaft in its bore, and with it, one part, tabs 2 x 2 standing 2 into the host."""
    host, shaft = shaft_in_its_bore()
    solids = [shaft.shape, *(Pos(x, 0, 5) * Box(2, 2, 4) for x in tabs)]
    return host, Part("shaft", Compound(children=solids))


def test_a_real_overlap_beside_such_slivers_is_measured_without_them(monkeypatch):
    # The same shaft with a tab on it 8 mm^3 into the host. The boolean, right, says
    # 8.0, the meshes, slivers and all, near 40: but the solids bear out the tab's
    # lump alone, 8.0 of it, and the boolean stands.
    host, shaft = with_a_tab(10)
    engine = MeshEngine()
    assert engine.meshes_share(host, shaft) > 8.0 + 20.0
    exact = engine.shared(host, shaft)
    assert (exact.by_meshes, exact.volume) == (False, pytest.approx(8.0))
    # The boolean failing, the meshes' figure is the tab's lump alone, which the
    # solids bear out: not the slivers with it.
    always(monkeypatch, EMPTY)
    overlap = MeshEngine().shared(host, shaft)
    assert overlap.by_meshes
    assert overlap.volume == pytest.approx(8.0)
    assert box_of(overlap) == pytest.approx((9, -1, 3, 11, 1, 5))


def test_a_boolean_a_little_under_what_the_solids_bear_out_stands(monkeypatch):
    # The same again, and the boolean says 7.5 of the tab's 8: far from the meshes'
    # 40, slivers and all, and within a factor of two of the 8 the solids bear out.
    # Taken as it is, and not asked again.
    host, shaft = with_a_tab(10)
    under = PartOverlap(7.5, 24.0, (9, -1, 3), (11, 1, 5), Pos(10, 0, 4) * Box(2, 2, 1.875))
    calls = failing(monkeypatch, (under, True), EMPTY)
    assert MeshEngine().shared(host, shaft) is under
    assert len(calls) == 1


def test_every_lump_the_solids_bear_out_is_counted(monkeypatch):
    always(monkeypatch, EMPTY)
    overlap = MeshEngine().shared(*with_a_tab(6, 12))
    assert overlap.volume == pytest.approx(16.0)
    assert box_of(overlap) == pytest.approx((5, -1, 3, 13, 1, 5))
    assert overlap.mesh[1].shape == (24, 3)


def whole_bar(at):
    """What OCCT gave for an insert touching its part: all of the smaller one."""
    shape = bar(at).shape
    return PartOverlap(160.0, 192.0, (at - 5, -2, -2), (at + 5, 2, 2), shape), True


def test_a_boolean_that_gives_the_whole_of_a_part_that_only_touches_is_not_taken(monkeypatch):
    # The bar against the block's side, and the boolean says all 160 mm^3 of it. No
    # point of the bar is inside the block: nothing is shared.
    always(monkeypatch, whole_bar(15.0))
    engine = MeshEngine()
    assert engine.refuted(whole_bar(15.0)[0], the_block(), bar(15.0))
    assert engine.shared(the_block(), bar(15.0)) is None


def test_it_is_cut_back_to_what_the_meshes_share_where_they_share_some(monkeypatch):
    # The bar 1 into the block, 16 mm^3, and the boolean says all 160 of it. Points
    # deep in the bar are mostly outside the block, so its answer is not taken; the
    # meshes' 16 mm^3 is borne out, and is the measure.
    always(monkeypatch, whole_bar(14.0))
    overlap = MeshEngine().shared(the_block(), bar(14.0))
    assert overlap.by_meshes
    assert overlap.volume == pytest.approx(1 * 4 * 4.0)


def test_a_boolean_that_says_more_than_the_solids_bear_out_is_asked_too(monkeypatch):
    # The shaft in its bore with its tab, 8 mm^3 truly, near 40 on the meshes with
    # their slivers. A boolean saying 18, most of it a piece out in the open, agrees
    # with neither, and its bulk is outside both solids: the 8 the solids bear out.
    host, shaft = with_a_tab(10)
    stray = Compound(children=[Pos(10, 0, 4) * Box(2, 2, 2), Pos(10, 0, 30) * Box(2, 2, 2.5)])
    lie = PartOverlap(18.0, 52.0, (9, -1, 3), (11, 1, 31.25), stray), True
    always(monkeypatch, lie)
    engine = MeshEngine()
    assert engine.refuted(lie[0], host, shaft)
    overlap = engine.shared(host, shaft)
    assert (overlap.by_meshes, overlap.volume) == (True, pytest.approx(8.0))


def test_a_stray_piece_does_not_undo_the_whole_answer(monkeypatch):
    # The bar's 112 mm^3 in the block, and with it a piece of 8 out in the open: 8
    # of 120 lies outside the solids, under half, and the answer stands as given.
    pieces = Compound(children=[Pos(6.5, 0, 0) * Box(7, 4, 4), Pos(0, 0, 30) * Box(2, 2, 2)])
    answer = PartOverlap(120.0, 168.0, (-1, -2, -2), (10, 2, 31), pieces), True
    engine = MeshEngine()
    monkeypatch.setattr(engine, "_pair", lambda first, second: (False, 0.0))
    always(monkeypatch, answer)
    assert not engine.refuted(answer[0], the_block(), bar())
    assert engine.shared(the_block(), bar()) is answer[0]


def test_a_thin_answer_the_meshes_don_t_show_stands(monkeypatch):
    # The bar 0.03 into the block, 0.48 mm^3, and the meshes made to say nothing.
    # Its one piece has no point deep enough to ask about: it says nothing against
    # the answer, which stands.
    engine = MeshEngine()
    monkeypatch.setattr(engine, "_pair", lambda first, second: (False, 0.0))
    overlap = engine.shared(the_block(), bar(14.97))
    assert (overlap.by_meshes, overlap.volume) == (False, pytest.approx(0.48))
    assert not engine.refuted(overlap, the_block(), bar(14.97))


def test_a_boolean_that_says_more_than_the_meshes_and_is_right_stands(monkeypatch):
    # The meshes made to say nothing: the boolean's 112 is asked of the solids, and
    # points deep in it are inside both.
    engine = MeshEngine()
    monkeypatch.setattr(engine, "_pair", lambda first, second: (False, 0.0))
    overlap = engine.shared(the_block(), bar())
    assert (overlap.by_meshes, overlap.volume) == (False, pytest.approx(BAR_IN_BLOCK))
    assert not engine.refuted(overlap, the_block(), bar())


GARBAGE = PartOverlap(500.0, 3.0, (0, 0, 0), (1, 1, 1)), False


def test_an_answer_no_solid_could_be_is_never_taken(monkeypatch):
    calls = failing(monkeypatch, GARBAGE, GARBAGE)
    engine = MeshEngine()
    overlap = engine.shared(the_block(), bar())
    assert (overlap.by_meshes, overlap.volume) == (True, pytest.approx(BAR_IN_BLOCK))
    assert engine.shared(the_block(), bar(15.0)) is None  # touching: nothing borne out
    assert engine.unsure == []
    assert len(calls) == 2  # each asked once: such a boolean is not asked again


def test_nor_is_one_that_happens_to_agree_with_the_meshes(monkeypatch):
    # 112 mm^3 inside 3 mm^2: the right volume, and no solid. The meshes' own.
    always(monkeypatch, (PartOverlap(112.0, 3.0, (0, 0, 0), (1, 1, 1)), False))
    overlap = MeshEngine().shared(the_block(), bar())
    assert (overlap.by_meshes, overlap.area) == (True, pytest.approx(144.0))


def test_without_a_closed_mesh_the_boolean_s_answer_stands(monkeypatch):
    engine = MeshEngine()
    monkeypatch.setattr(engine, "part_mesh", lambda part: None)
    assert engine.shared(the_block(), bar()).volume == pytest.approx(BAR_IN_BLOCK)
    assert engine.shared(the_block(), bar(15.0)) is None
    assert engine.unsure == []


def test_without_one_an_answer_no_solid_could_be_is_noted_as_not_measured(monkeypatch):
    always(monkeypatch, GARBAGE)
    engine = MeshEngine()
    monkeypatch.setattr(engine, "part_mesh", lambda part: None)
    assert engine.shared(the_block(), bar()) is None
    assert engine.unsure == [("block", "bar")]


def test_the_exact_engine_measures_as_the_mesh_engine_does(monkeypatch):
    always(monkeypatch, EMPTY)
    engine = ExactEngine()
    overlap = engine.shared(the_block(), bar())
    assert (overlap.by_meshes, overlap.volume) == (True, pytest.approx(BAR_IN_BLOCK))
    assert not engine.parts_apart(the_block(), bar(40.0))  # and clears no pair by its meshes
    always(monkeypatch, GARBAGE)
    monkeypatch.setattr(MeshEngine, "part_mesh", lambda self, part: None)
    assert engine.shared(the_block(), bar()) is None
    assert engine.unsure == [("block", "bar")]  # its own list


# ---------------------------------------------------------------------------
# The issue's two parts, as OCCT has them.
# ---------------------------------------------------------------------------

R = 2.05
OFFSETS = (0.0, 1e-7, 3e-7, 1e-6, 3e-6, 1e-5)
OVER = (0.0, 1e-7, -1e-7, 1e-6)
LEANS = (0.0, 2e-6)


def disc():
    """A disc 7 across and 4 thick, its underside split by a circle 2.05 round: a
    post 2.0 round cut off it by a rod 2.05, by wrenchroom's bare cut, which leaves
    the face in its pieces."""
    whole = Pos(0, 0, 2) * Cylinder(3.5, 4) + Pos(0, 0, -5) * Cylinder(2.0, 10)
    return cut(whole, Pos(0, 0, -5) * Cylinder(R, 10))


def bored_plate(offset=0.0, over=0.0, lean=0.0):
    """A plate from z -1.5 to 1.0, bored at that circle's radius and ``over``, its
    bore ``offset`` off the axis and leaning ``lean``."""
    bored = Pos(0, 0, -0.25) * Box(30, 30, 2.5) - Cylinder(R + over, 40)
    return Pos(offset, offset / 3, 0) * Rot(0, math.degrees(lean), 0) * bored


def test_the_issue_s_two_parts_are_a_clash(engine):
    # A bore 3e-7 off the axis and 1e-7 over: on macOS arm64 the boolean came back
    # empty, and the two were no clash on either engine.
    parts = [Part("boss", disc()), Part("bracket", bored_plate(3e-7, 1e-7))]
    found = find_clashes(Assembly(parts), None, engine=engine)
    assert [(c.first, c.second, round(c.volume, 1)) for c in found.found] == [
        ("boss", "bracket", 25.3)
    ]


def test_however_a_hair_off_its_bore_is_the_disc_s_part_in_the_plate_is_measured():
    # Every plate of the family #156 found a head's failure in: 25.28 mm^3 each, to
    # 0.01 where a boolean gives it and to the meshes' 1.5 % where none does.
    engine, boss = MeshEngine(), Part("boss", disc())
    read = {}
    for placed in itertools.product(OFFSETS, OVER, LEANS):
        overlap = engine.shared(boss, Part("bracket", bored_plate(*placed)))
        read[placed] = (overlap.volume, overlap.by_meshes) if overlap is not None else (0.0, False)
    assert len(read) == 48
    wrong = {
        placed: got
        for placed, (got, by_meshes) in read.items()
        if abs(got - DISC_IN_PLATE) > (0.015 * DISC_IN_PLATE if by_meshes else 0.01)
    }
    assert wrong == {}


# ---------------------------------------------------------------------------
# In the list, and in a verdict.
# ---------------------------------------------------------------------------


def listed(found):
    return [(c.first, c.second, round(c.volume, 1), c.hint, c.by_meshes) for c in found.found]


def test_a_clash_measured_on_the_meshes_says_so(monkeypatch, engine):
    always(monkeypatch, EMPTY)
    found = find_clashes(Assembly([the_block(), bar()]), None, engine=engine)
    assert listed(found) == [("bar", "block", 112.0, None, True)]
    assert found.lines() == [
        "1 clash (overlap over 0.05 mm^3)",
        f"CLASH bar into block  112.0 mm^3  ({BY_MESHES})",
    ]
    assert found.exit_code == 1
    assert found.to_json()["found"] == [
        {
            "parts": ["bar", "block"],
            "volume": 112.0,
            "point": [6.5, 0.0, 0.0],
            "state": None,
            "hint": None,
            "by_meshes": True,
        }
    ]
    assert f"| `bar` | `block` | 112.0 | {BY_MESHES} |" in found.markdown()


def test_one_the_boolean_measures_does_not(engine):
    found = find_clashes(Assembly([the_block(), bar()]), None, engine=engine)
    assert listed(found) == [("bar", "block", 112.0, None, False)]
    assert found.lines()[1] == "CLASH bar into block  112.0 mm^3"
    assert found.to_json()["found"][0]["by_meshes"] is False
    assert found.to_json()["unsure"] == []


def test_a_hint_and_the_meshes_are_both_said(monkeypatch):
    # A bar 0.06 into the block, 0.96 mm^3: a press fit by its depth, 2 V / A = 0.06,
    # and thick enough, 0.03 from each face, to ask the solids about.
    always(monkeypatch, EMPTY)
    found = find_clashes(Assembly([the_block(), bar(14.94)]), None)
    (line,) = found.lines()[1:]
    assert line == (
        "CLASH bar into block  1.0 mm^3  (a press fit, 0.06 deep? allow it in the sidecar)"
        f"  ({BY_MESHES})"
    )


def test_an_overlap_too_thin_to_ask_about_is_left_to_the_boolean(monkeypatch):
    # 0.03 into the block: its middle is 0.015 from each face, nearer than a mesh
    # may stand off its surface. With no boolean to measure it, it is not told.
    always(monkeypatch, EMPTY)
    assert find_clashes(Assembly([the_block(), bar(14.97)]), None).found == ()
    monkeypatch.undo()
    (clash,) = find_clashes(Assembly([the_block(), bar(14.97)]), None).found
    assert (round(clash.volume, 2), clash.by_meshes) == (0.48, False)


def both(parts, rules, engine):
    config = Config.from_dict({"fasteners": list(rules), "checks": {"detect": False}})
    assembly = Assembly([Part(name, shape) for name, shape in parts])
    return check(assembly, config, engine=engine, kit="full", clashes=True)


def test_a_verdict_and_the_list_tell_a_head_s_clash_alike_on_the_meshes(monkeypatch, engine):
    # #116's button head in a block, every boolean coming back empty: 62.35 mm^3 by
    # hand, and both tell the meshes' figure of it, the same one to the digit.
    always(monkeypatch, EMPTY)
    parts = [("plate", plate()), ("screw", button()), ("block", Pos(0, 0, 10) * Box(20, 20, 20))]
    report = both(parts, [{"parts": "screw", **BUTTON}], engine)
    (clash,) = report.clashes.found
    assert (clash.first, clash.second, clash.by_meshes) == ("screw", "block", True)
    # A dome's mesh lies inside it: 59.7 of the 62.35.
    assert 0.95 * HEAD < clash.volume < HEAD
    (result,) = report.results
    assert result.reason == f"drawn into block ({clash.volume:.1f} mm^3): fix the model"


def test_an_insert_measured_on_the_meshes_is_still_set_into_its_part(monkeypatch, engine):
    # 5 across in a hole 4.6: 12.06 mm^3, 0.15 of its cylinder, set in. Its share is
    # read from the meshes' overlap as it is from a solid's.
    always(monkeypatch, EMPTY)
    parts = [Part("insert", insert()), Part("block", block(4.6))]
    config = Config.from_dict({"fasteners": [INSERT], "checks": {"detect": False}})
    found = find_clashes(Assembly(parts), config, engine=engine)
    assert found.found == ()
    (set_in,) = found.set_in
    assert (set_in.first, set_in.second, set_in.by_meshes) == ("insert", "block", True)
    assert set_in.volume == pytest.approx(shell(5.0, 4.6), rel=0.05)
    assert found.to_json()["set_in"][0]["by_meshes"] is True
    assert found.lines(with_inserts=True)[-1].endswith(f"mm^3  ({BY_MESHES})")


def test_one_fastener_drawn_twice_is_still_told_so_on_the_meshes(monkeypatch, engine):
    # #94's M3 screw drawn twice in one hole, every boolean coming back empty: one
    # is drawn over the other in its verdict, and in the list, to the same volume,
    # all the two share. 120.8 mm^3 by hand; the meshes' figure of it is the mesh
    # of the screw itself, a little inside it.
    always(monkeypatch, EMPTY)
    report = both(dup_parts(), [{"parts": "M3x* SHCS", **M3}], engine)
    (clash,) = report.clashes.found
    assert (clash.first, clash.second) == ("M3x8 SHCS", "M3x12 SHCS")
    assert (clash.hint, clash.by_meshes) == ("one fastener drawn twice", True)
    assert 0.9 * 120.8 < clash.volume <= 120.8
    (result,) = report.results
    assert result.reason == (
        f"drawn twice: M3x8 SHCS is drawn over it ({clash.volume:.1f} mm^3 in common):"
        " fix the model"
    )


def test_a_pair_not_measured_at_all_is_said(monkeypatch):
    always(monkeypatch, GARBAGE)
    monkeypatch.setattr(MeshEngine, "part_mesh", lambda self, part: None)
    found = find_clashes(Assembly([the_block(), bar()]), None)
    note = "not measured, the solids' boolean failed and one has no closed mesh"
    assert found.lines() == [
        "no clashes (overlap over 0.05 mm^3)",
        f"NOTE {note}: block with bar",
    ]
    assert found.to_json()["unsure"] == [["block", "bar"]]
    assert found.markdown()[-1] == f"- N{note[1:]}: `block` with `bar`"
    assert found.exit_code == 0
    assert note == clashes_module.UNSURE


def test_the_json_document_is_still_valid(monkeypatch):
    always(monkeypatch, EMPTY)
    found = find_clashes(Assembly([the_block(), bar()]), None)
    document = json.loads(found.json_text("model.step"))
    assert document["clashes"]["found"][0]["by_meshes"] is True


def test_the_view_draws_an_overlap_measured_on_the_meshes(monkeypatch):
    # Its triangles are the meshes' own: eight corners, x 3 to 10.
    always(monkeypatch, EMPTY)
    assembly = Assembly([the_block(), bar()])
    report = check(assembly, Config.from_dict({"checks": {"detect": False}}), clashes=True)
    data = view_data(report)
    (entry,) = data["clashes"]["found"]
    assert (entry["label"], entry["volume"]) == ("bar into block", "112.0")
    points = base64.b64decode(data["shapes"][entry["overlap"]]["p"])
    vertices = np.frombuffer(points, "<f4").reshape(-1, 3)
    assert len(vertices) == 8
    assert (*vertices.min(axis=0), *vertices.max(axis=0)) == pytest.approx((3, -2, -2, 10, 2, 2))
