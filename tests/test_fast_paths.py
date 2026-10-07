"""The check's cheaper paths give what the slower ones gave.

Two things a check does once per fastener used to cost a second of the scaled
bench: reading a part's faces over and over for its frame (each test took a
face's centroid, an integral over it), and gathering every part's box again for
each fastener's scene. A part's planar and cylindrical faces are now read once,
by their own parameters; and the assembly's boxes once, each scene masking out
its fastener's own parts. Neither may change a verdict: the bench's snapshots
are byte for byte as before, and these pin the pieces.
"""

import math

import numpy as np
import pytest
from build123d import Box, Cylinder, GeomType, Pos, RegularPolygon, Rot, extrude

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import _faces_of, _StateSpace
from wrenchroom.config import Config
from wrenchroom.engine import make_engine
from wrenchroom.engine.scene import Scene


def nut():
    return extrude(RegularPolygon(13 / math.sqrt(3), 6), 6.8) - Cylinder(4, 30)


SHAPES = {
    "nut": nut(),
    "tilted nut": Rot(20, 35, 0) * nut(),
    "bolt": Pos(0, 0, -10) * Cylinder(4, 20) + extrude(RegularPolygon(13 / math.sqrt(3), 6), 5.3),
    "socket head": Cylinder(5, 6) - extrude(RegularPolygon(5 / math.sqrt(3), 6), 3),
}


@pytest.mark.parametrize("name", list(SHAPES))
def test_a_face_s_own_point_and_normal_answer_as_its_centroid_did(name):
    # On a plane or a cylinder about its own axis, the tests ask the side a
    # point is on and the normal's direction: the same at any point of the face.
    faces = _faces_of(Part("x", SHAPES[name]))
    kinds = [f.face.geom_type for f in faces]
    assert set(kinds) <= {GeomType.PLANE, GeomType.CYLINDER}
    assert sum(1 for k in kinds if k is GeomType.PLANE) >= 2  # a vacuity guard
    for f in faces:
        centroid = tuple(f.face.center())
        normal = tuple(f.face.normal_at(f.face.center()))
        assert f.normal == pytest.approx(normal, abs=1e-9)
        if f.plane:  # the same plane: the same distance along the normal
            offset = np.dot(np.subtract(f.point, centroid), f.normal)
            assert offset == pytest.approx(0.0, abs=1e-9)
        else:  # the same cylinder: the same distance from its axis
            axis = f.face.axis_of_rotation
            on = np.subtract(f.point, tuple(axis.position))
            off = np.subtract(centroid, tuple(axis.position))
            d = np.array(tuple(axis.direction))
            radial = np.linalg.norm(on - np.dot(on, d) * d)
            assert radial == pytest.approx(np.linalg.norm(off - np.dot(off, d) * d), abs=1e-9)


def assembly():
    return Assembly(
        [
            Part("plate", Pos(0, 0, -5) * Box(200, 200, 10)),
            Part("bolt", SHAPES["bolt"]),
            Part("nut", nut()),
            Part("wall", Pos(50, 0, 10) * Box(10, 100, 20)),
            Part("rib", Pos(-50, 0, 5) * Box(10, 100, 10)),
        ]
    )


@pytest.mark.parametrize("engine", ["mesh", "exact"])
def test_a_scene_from_the_assembly_s_boxes_is_the_scene_from_its_parts(engine):
    model = assembly()
    config = Config.from_dict({"ignore": ["rib"]})
    space = _StateSpace(model, config, None, make_engine(engine))
    masked = space.scene(model, {"nut", "bolt"})
    gathered = Scene([model["plate"], model["wall"]], space.engine)
    assert [p.name for p in masked.parts] == ["plate", "wall"]  # assembly order, less
    assert np.array_equal(masked._low, gathered._low)  # noqa: SLF001
    assert np.array_equal(masked._high, gathered._high)  # noqa: SLF001
    # The same boxes each time: the assembly's are gathered once and masked.
    again = space.scene(model, {"plate"})
    assert [p.name for p in again.parts] == ["bolt", "nut", "wall"]
    assert space.scene(model, set()).parts == tuple(p for p in model if p.name != "rib")


def test_a_name_on_several_pieces_masks_them_all():
    # A part drawn as two solids is two pieces with one name (issue #28).
    model = Assembly(
        [
            Part("plate", Pos(0, 0, -5) * Box(200, 200, 10)),
            Part("nut", nut()),
            Part("nut#2", Pos(0, 0, 8) * Cylinder(5, 2), piece_of="nut"),
        ]
    )
    space = _StateSpace(model, Config(), None, make_engine("mesh"))
    names = {p.name for p in space.scene(model, {"nut", "nut#2"}).parts}
    assert names == {"plate"}
