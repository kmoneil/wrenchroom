"""Each placed piece is measured against each part once, and only ever answers for that.

The same piece comes back attempt after attempt: a socket's mouth on every
extension, a ring's engagement for the stubby, the hex's corner sweep in every
tool on its flats. Both engines keep a piece's overlap with a part, keyed by the
piece, where it is placed and which part; a different placement or part is
measured afresh. The mesh engine's sure-hit bound counts every overlapping
piece's surface, the first pieces' included.
"""

import pytest
from build123d import Box, Pos

from wrenchroom.assembly import Part
from wrenchroom.engine import make_engine
from wrenchroom.engine.mesh import MeshEngine, MeshQuery, _Measure
from wrenchroom.engine.scene import Contact
from wrenchroom.tools.sweep import axial_annulus, axial_cylinder

BLOCK = Part("block", Box(10, 10, 10))
FAR_BLOCK = Part("far", Pos(100, 0, 0) * Box(10, 10, 10))


def into_block(depth, seat=(0.0, 0.0, 0.0)):
    """A key end and a collar, the end ``depth`` into the block's top face."""
    local = axial_cylinder(2.0, 5 - depth, 8) + axial_annulus(3, 6, 8, 2)
    return local.placed(seat, (0.0, 0.0, 1.0))


@pytest.mark.parametrize("engine_name", ["mesh", "exact"])
def test_a_piece_is_measured_once_however_often_it_comes_back(engine_name):
    engine = make_engine(engine_name)
    scene = engine.scene([BLOCK])
    first = scene.contacts(into_block(1.0))
    entries = len(engine.measured)
    assert entries >= 1
    assert scene.contacts(into_block(1.0)) == first == (("block",), ())
    assert len(engine.measured) == entries  # the same piece, place and part: kept


@pytest.mark.parametrize("engine_name", ["mesh", "exact"])
def test_another_placement_or_part_is_measured_afresh(engine_name):
    engine = make_engine(engine_name)
    scene = engine.scene([BLOCK, FAR_BLOCK])
    assert scene.contacts(into_block(1.0)) == (("block",), ())
    # The same tool over the far block: a new placement, and a new part.
    over_far = into_block(1.0, seat=(100.0, 0.0, 0.0))
    assert scene.contacts(over_far) == (("far",), ())
    # The very same pieces placed 10 higher, over the same block: clear. Only the
    # placement tells this from the first test.
    assert scene.contacts(into_block(1.0, seat=(0.0, 0.0, 10.0))) == ((), ())


def test_a_piece_s_answer_is_never_another_part_s(monkeypatch):
    # Two parts at the same place, one solid, one a thin shell round it: the same
    # placed piece must be measured against each.
    engine = make_engine("mesh")
    solid = Part("solid", Box(10, 10, 10))
    hollow = Part("hollow", Box(30, 30, 30) - Box(20, 20, 20))
    tool = into_block(1.0)
    assert engine.scene([solid]).contacts(tool) == (("solid",), ())
    assert engine.scene([hollow]).contacts(tool) == ((), ())


def test_the_sure_hit_bound_counts_every_piece_s_surface(monkeypatch):
    # Two pieces overlapping thinly: 0.04 mm^3 over 4 mm^2, then 0.1 over 2. Taking
    # 0.02 (the key's facet) off all 6 mm^2 leaves 0.02, under the floor: the
    # referee decides. Counting only the second piece's surface would have said
    # 0.1, a sure hit, without it.
    measures = iter([_Measure(None, 0.04, 4.0), _Measure(None, 0.1, 2.0)])
    monkeypatch.setattr(MeshEngine, "part_strays", lambda self, part: (0.0, 0.0))
    monkeypatch.setattr(MeshQuery, "_measure", lambda self, index, mesh, part: next(measures))
    engine = make_engine("mesh")
    two_pieces = axial_cylinder(2.0, 4, 8) + axial_annulus(2.5, 4, 4, 1)
    query = engine.query(two_pieces.placed((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
    monkeypatch.setattr(MeshQuery, "_refer", lambda self, part: Contact.GRAZE)  # a marker
    assert query.contact(BLOCK) is Contact.GRAZE  # referred, not decided on the mesh


@pytest.mark.parametrize("engine_name", ["mesh", "exact"])
def test_the_same_pieces_elsewhere_in_one_part_are_measured_there(engine_name):
    # A hollow box: the same pieces clear in its cavity, and run into its wall
    # 12 to the side, both inside its box, so both are tested, and only the
    # placement tells the two apart.
    hollow = Part("hollow", Box(30, 30, 30) - Box(20, 20, 20))
    scene = make_engine(engine_name).scene([hollow])
    assert scene.contacts(into_block(1.0)) == ((), ())
    assert scene.contacts(into_block(1.0, seat=(12.0, 0.0, 0.0))) == (("hollow",), ())
