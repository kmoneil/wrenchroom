"""A tool's contact with a part is held to the meshes too (issue #169).

#163 held two parts' clash to their meshes: OCCT's boolean comes back empty for
solids drawn into each other, and says nothing of it. A tool's own contact with a
part is the same boolean, a piece at a time, and was still taken as given: under
``--exact`` a round shaft 13.2 mm^3 into a disc whose underside is split along a
circle of the shaft's radius read as clear, and a tool that reads clear passes.

Now a tool its booleans leave short of a hit is held to what its meshes and the
part's share, as a clash is: where the two differ by more than the floor and a
factor of two, the solids are asked, point by point, and what they bear out being
past the floor, the tool is into the part. A plug drawn into its receptacle is
measured the same way, as placed and as moved. The mesh engine's own referee is
not: it is asked where the meshes couldn't be sure, and they are no second opinion
there.

The tests give the engines booleans that come back empty, so they hold whatever
OCCT does on a platform. By hand:

- a shaft 4 across through a wall 10 thick: pi 2^2 10 = 125.66 mm^3;
- the issue's shaft, 4.1 across, 1.0 into its disc: pi 2.05^2 = 13.20 mm^3;
- two tool pieces end to end and a sliver of part across their seam, 0.1 x 0.6 x
  0.5 = 0.03 mm^3 in each: under the floor apiece, over it together.
"""

import itertools
import math

import pytest
from build123d import Box, Cylinder, Pos, Rot

import wrenchroom.engine.exact as exact_module
import wrenchroom.engine.mesh as mesh_module
from test_connectors import UP, board, plug, result, shroud
from test_connectors import run as run_connectors
from test_engine import x_cylinder, x_tool
from test_head_clash import BUTTON, button, plate
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.connectors import ConnectorVerdict
from wrenchroom.engine import HIT_MIN_VOLUME, ExactEngine, MeshEngine, make_engine
from wrenchroom.engine.exact import cut
from wrenchroom.engine.mesh import inner_points
from wrenchroom.engine.scene import Contact
from wrenchroom.report import Verdict
from wrenchroom.solids import RadialBox, ToolSolid
from wrenchroom.tools.sweep import axial_cylinder

THROUGH_THE_WALL = math.pi * 2**2 * 10
R = 2.05
SHAFT_IN_DISC = math.pi * R**2


def wall():
    return Part("wall", Box(10, 40, 40))


@pytest.fixture(params=["raw shape", "tool solid"])
def along_x(request):
    """Both kinds of tool the engines accept, built the same."""
    return x_cylinder if request.param == "raw shape" else x_tool


@pytest.fixture
def empty(monkeypatch):
    """Every boolean comes back empty: a tool's, and two parts'."""
    monkeypatch.setattr(exact_module, "exact_overlap", lambda a, b: 0.0)
    monkeypatch.setattr(mesh_module, "measured_common", lambda a, b: (None, True))


def test_the_hand_work():
    assert (f"{THROUGH_THE_WALL:.2f}", f"{SHAFT_IN_DISC:.2f}") == ("125.66", "13.20")
    assert 0.03 < HIT_MIN_VOLUME < 0.06


# ---------------------------------------------------------------------------
# A tool the booleans call clear.
# ---------------------------------------------------------------------------


def test_a_tool_through_a_part_is_a_hit_though_its_booleans_come_back_empty(empty, along_x):
    assert ExactEngine().query(along_x(0)).contact(wall()) is Contact.HIT


def test_as_it_is_where_they_don_t(along_x):
    assert ExactEngine().query(along_x(0)).contact(wall()) is Contact.HIT


def test_a_tool_clear_of_a_part_is_clear(empty, engine):
    probe = Pos(0, 0, 50) * Box(2, 2, 2)
    assert make_engine(engine).query(probe).contact(wall()) is Contact.CLEAR
    far = x_tool(40, length=20)  # x 30 to 50: 25 clear of the wall
    assert make_engine(engine).query(far).contact(wall()) is Contact.CLEAR


def test_a_tool_that_only_touches_a_part_is_clear(empty):
    # Its end on the wall's face, x = 5: the meshes share nothing.
    assert ExactEngine().query(x_tool(15, length=20)).contact(wall()) is Contact.CLEAR


def bored_block():
    return Part("block", Box(200, 100, 10) - Pos(-50, 0, 0) * Cylinder(25, 20))


def test_a_shaft_in_a_bore_of_its_own_radius_is_clear(empty):
    # A tool 50 across down a bore 50 across. A tool's mesh stands outside it and
    # the bore's inside the bore, so the two meshes overlap all the way round, by
    # more than the floor; no point of that is inside both the tool and the block.
    tool = axial_cylinder(25.0, -15.0, 15.0).placed((-50.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    engine, block = ExactEngine(), bored_block()
    meshes = MeshEngine()
    shared = meshes.query(tool).shares(block)
    assert shared > 20 * HIT_MIN_VOLUME
    assert shared == pytest.approx(
        sum(overlap.volume() for _, overlap in meshes.query(tool).overlaps(block))
    )
    assert engine.query(tool).contact(block) is Contact.CLEAR


def test_a_tube_on_a_post_of_its_own_bore_is_clear_of_it(empty):
    # The other way round, the tool a plain shape meshed as a part is: a tube bored
    # 50 on a post 50 across, turned 3 degrees on it. The slivers their meshes share
    # are deep enough to ask about, and each deepest point is inside the post and in
    # the tube's bore: it is the tool's own solid that says no.
    tube = Rot(0, 0, 3) * (Cylinder(30, 10) - Cylinder(25, 10))
    post = Part("post", Cylinder(25, 40))
    meshes = MeshEngine()
    slivers = [
        lump for _, overlap in meshes.query(tube).overlaps(post) for lump in overlap.decompose()
    ]
    asked = [inner_points(lump)[0] for lump in slivers if len(inner_points(lump))]
    assert len(asked) > 20
    assert all(meshes.inside(post, point) for point in asked)
    assert ExactEngine().query(tube).contact(post) is Contact.CLEAR


def test_a_graze_the_booleans_measure_is_theirs():
    # The tool's end 0.003 into the wall: pi 2^2 0.003 = 0.038 mm^3, a graze, and
    # the meshes agree with that within the floor.
    graze = x_tool(15 - 0.003, length=20)
    assert ExactEngine().query(graze).contact(wall()) is Contact.GRAZE


def test_a_graze_lost_by_its_booleans_is_too_thin_to_ask_about(empty):
    # The same, and the booleans say nothing: 0.038 is within the floor of that,
    # and it stands. A graze changes no verdict.
    graze = x_tool(15 - 0.003, length=20)
    assert ExactEngine().query(graze).contact(wall()) is Contact.CLEAR


def seam_tool(*pieces):
    return ToolSolid(pieces).placed((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))


FIRST, SECOND = RadialBox(4.0, 2.0, 0.0, 10.0, 0.0, 0.0), RadialBox(4.0, 2.0, 10.0, 20.0, 0.0, 0.0)


def test_what_the_solids_bear_out_is_summed_over_a_tool_s_pieces(empty):
    # test_engine.py's sliver across the seam of two pieces: 0.03 mm^3 in each,
    # 0.05 from each face of it. Together a hit; one piece's share alone is not.
    sliver = Part("sliver", Pos(10, 0, 0) * Box(0.2, 0.6, 0.5))
    assert ExactEngine().query(seam_tool(FIRST, SECOND)).contact(sliver) is Contact.HIT
    assert ExactEngine().query(seam_tool(FIRST)).contact(sliver) is Contact.CLEAR


def test_booleans_a_little_short_of_the_meshes_stand(monkeypatch):
    # A sliver 0.04 mm^3 in each of two pieces, 0.08 on the meshes, and each boolean
    # says 0.02 of it: 0.04 together, a graze, and within the floor of the 0.08.
    # Theirs to say: it is what they say that is held to the meshes, not nothing.
    monkeypatch.setattr(exact_module, "exact_overlap", lambda a, b: 0.02)
    sliver = Part("sliver", Pos(10, 0, 0) * Box(0.2, 0.8, 0.5))
    assert ExactEngine().query(seam_tool(FIRST, SECOND)).contact(sliver) is Contact.GRAZE


def test_it_is_what_the_solids_bear_out_that_the_booleans_are_held_to(monkeypatch):
    # The same again, and the meshes made to say they share 5 mm^3, as they would
    # with slivers beside the true overlap. The solids bear out the 0.08, which the
    # booleans' 0.04 is within the floor of: theirs to say still.
    monkeypatch.setattr(exact_module, "exact_overlap", lambda a, b: 0.02)
    monkeypatch.setattr(mesh_module.MeshQuery, "shares", lambda self, part: 5.0)
    sliver = Part("sliver", Pos(10, 0, 0) * Box(0.2, 0.8, 0.5))
    assert ExactEngine().query(seam_tool(FIRST, SECOND)).contact(sliver) is Contact.GRAZE


def test_booleans_short_of_a_hit_and_far_short_of_the_meshes_are_not_taken(monkeypatch, along_x):
    # Each says 0.04 mm^3, a graze, of a tool 125.66 through the wall.
    monkeypatch.setattr(exact_module, "exact_overlap", lambda a, b: 0.04)
    assert ExactEngine().query(along_x(0)).contact(wall()) is Contact.HIT


def test_a_part_with_no_closed_mesh_leaves_the_booleans_to_it(empty, monkeypatch):
    monkeypatch.setattr(MeshEngine, "part_mesh", lambda self, part: None)
    assert ExactEngine().query(x_tool(0)).contact(wall()) is Contact.CLEAR


def test_the_mesh_engine_s_referee_is_not_held_to_the_meshes(empty):
    # It is asked where they couldn't be sure. Asked of a tool through a wall, with
    # its booleans empty, it says what they say; the mesh engine itself never asks
    # it: its meshes are sure of that hit.
    engine = MeshEngine()
    assert engine.referee.second_opinion is False
    assert engine.referee.query(x_tool(0)).contact(wall()) is Contact.CLEAR
    assert engine.query(x_tool(0)).contact(wall()) is Contact.HIT
    assert engine.referred == 0
    assert ExactEngine().second_opinion is True


# ---------------------------------------------------------------------------
# The issue's shaft and disc, as OCCT has them.
# ---------------------------------------------------------------------------


def disc():
    """A disc 7 across and 4 thick, its underside split by a circle 2.05 round."""
    whole = Pos(0, 0, 2) * Cylinder(3.5, 4) + Pos(0, 0, -5) * Cylinder(2.0, 10)
    return cut(whole, Pos(0, 0, -5) * Cylinder(R, 10))


def shaft(offset=0.0, over=0.0, lean=0.0):
    """A shaft of that circle's radius and ``over``, z -1 to 1: 1.0 of it in the disc."""
    turned = Rot(0, math.degrees(lean), 0) * Cylinder(R + over, 2)
    return Pos(offset, offset / 3, 0) * turned


def test_the_issue_s_shaft_is_into_its_disc_on_either_engine(engine):
    # 3e-7 off the axis and 1e-7 over: on macOS arm64 the boolean came back empty,
    # and under --exact the shaft was clear of the disc.
    contact = make_engine(engine).query(shaft(3e-7, 1e-7)).contact(Part("disc", disc()))
    assert contact is Contact.HIT


def test_however_a_hair_off_the_shaft_is_it_is_into_the_disc():
    # The 48 placements #156's tests use.
    part = Part("disc", disc())
    offsets, over, leans = (0.0, 1e-7, 3e-7, 1e-6, 3e-6, 1e-5), (0.0, 1e-7, -1e-7, 1e-6), (0, 2e-6)
    read = {
        placed: ExactEngine().query(shaft(*placed)).contact(part)
        for placed in itertools.product(offsets, over, leans)
    }
    assert len(read) == 48
    assert {placed: got for placed, got in read.items() if got is not Contact.HIT} == {}


# ---------------------------------------------------------------------------
# In a check, and a plug in its receptacle.
# ---------------------------------------------------------------------------


def covered(engine):
    """#116's button head under a cover 2 clear of it: no tool reaches it."""
    parts = [("plate", plate()), ("screw", button()), ("cover", Pos(0, 0, 6.2) * Box(20, 20, 4))]
    config = Config.from_dict({"fasteners": [{"parts": "screw", **BUTTON}]})
    assembly = Assembly([Part(name, shape) for name, shape in parts])
    (found,) = check(assembly, config, engine=engine, kit="full").results
    return found


def test_a_screw_under_a_cover_is_blocked_though_every_boolean_comes_back_empty(empty, engine):
    # Under --exact each tool's contact with the cover was a boolean, and empty,
    # every tool passed straight through it.
    found = covered(engine)
    assert found.verdict is Verdict.BLOCKED
    assert "cover" in found.blocked_by


def test_as_it_is_where_they_don_t_in_a_check(engine):
    assert covered(engine).verdict is Verdict.BLOCKED


def test_a_plug_drawn_into_its_receptacle_is_measured_on_the_meshes_too(empty, engine):
    # test_connectors.py's plug drawn 0.2 wider than its cavity: in its shroud as
    # drawn, and only rising adds no overlap. What it shares with the shroud, as
    # placed and as moved, is its boolean's to say, and with that empty, the meshes'.
    parts = [("board", board()), ("jack", shroud()), ("plug", plug(grow=0.2))]
    found = result(run_connectors(parts, [{"parts": "plug"}], engine), "plug")
    assert (found.verdict, found.receptacle, found.axis) == (
        ConnectorVerdict.UNPLUGS,
        ("jack",),
        UP,
    )
