"""The engines: hits name their parts, touches and slivers don't count.

The first half runs once per engine (the `scene_of` fixture). The second half
is the mesh engine's own promises: each part meshed once and only when a tool
comes near it, a part that won't mesh tested exactly instead, and the one place
the two engines are allowed to differ, said out loud.
"""

import pytest
from build123d import Box, Cylinder, Pos, Rectangle, Rot, Shape

import wrenchroom.engine.mesh as mesh_module
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.engine import (
    DEFAULT_ENGINE,
    ENGINES,
    HIT_MIN_VOLUME,
    ExactEngine,
    MeshEngine,
    make_engine,
)
from wrenchroom.engine.exact import exact_overlap
from wrenchroom.engine.mesh import MESH_TOLERANCE, solid_mesh
from wrenchroom.engine.scene import boxes_overlap, shape_bounds
from wrenchroom.solids import RadialBox, ToolSolid
from wrenchroom.tools.sweep import axial_annulus, axial_cylinder, radial_box


def x_cylinder(x, radius=2, length=30):
    """A plain OCP cylinder along x, centred at (x, 0, 0): a tool as a raw shape."""
    return Pos(x, 0, 0) * Rot(0, 90, 0) * Cylinder(radius, length)


def x_tool(x, radius=2, length=30):
    """The same cylinder as a tool solid: on an axis along +x, centred at x."""
    local = axial_cylinder(radius, -length / 2, length / 2)
    return local.placed((x, 0.0, 0.0), (1.0, 0.0, 0.0))


@pytest.fixture(params=["raw shape", "tool solid"])
def along_x(request):
    """Both kinds of tool the engines accept, built the same."""
    return x_cylinder if request.param == "raw shape" else x_tool


# ---------------------------------------------------------------------------
# Both engines.
# ---------------------------------------------------------------------------


def test_a_tool_through_a_part_names_it(scene_of, along_x):
    scene = scene_of(wall=Box(10, 40, 40), bystander=Pos(100, 0, 0) * Box(10, 10, 10))
    assert scene.hits(along_x(0)) == ("wall",)
    assert not scene.clear(along_x(0))


def test_a_tool_through_two_parts_names_both_in_order(scene_of, along_x):
    scene = scene_of(first=Box(10, 40, 40), second=Pos(12, 0, 0) * Box(10, 40, 40))
    assert scene.hits(along_x(6, length=40)) == ("first", "second")


def test_a_clear_tool_hits_nothing(scene_of):
    scene = scene_of(wall=Box(10, 40, 40))
    probe = Pos(0, 0, 50) * Box(2, 2, 2)
    assert scene.hits(probe) == ()
    assert scene.clear(probe)


def test_a_tangent_touch_is_not_a_hit(scene_of, along_x):
    # The cylinder's end lands exactly on the wall's face: contact, zero volume.
    scene = scene_of(wall=Box(10, 40, 40))
    assert scene.hits(along_x(5 + 15)) == ()  # ends at x = 5, the wall's face


def test_a_sliver_below_the_volume_floor_is_not_a_hit(scene_of):
    # 1 x 1 mm cross-section buried 0.04 mm: 0.04 mm^3, under the 0.05 floor.
    scene = scene_of(wall=Box(10, 40, 40))
    sliver = Pos(5 - 0.02 + 0.5, 0, 0) * Box(1, 1, 1)
    assert scene.hits(sliver) == ()
    deeper = Pos(5 - 0.1 + 0.5, 0, 0) * Box(1, 1, 1)  # 0.1 mm^3: over it
    assert scene.hits(deeper) == ("wall",)


def test_a_tool_wholly_inside_a_part_is_a_hit(scene_of):
    # The case a surface-only BVH misses (no triangles cross): a nut's free-face
    # probe sitting inside the plate the nut stands on.
    scene = scene_of(plate=Pos(0, 0, -5) * Box(200, 200, 10))
    probe = axial_annulus(3.5, 5.5, 0.1, 1.0).placed((0.0, 0.0, 0.0), (0.0, 0.0, -1.0))
    assert scene.hits(probe) == ("plate",)


def test_a_part_wholly_inside_a_tool_is_a_hit(scene_of):
    scene = scene_of(pebble=Pos(0, 0, 50) * Box(1, 1, 1))
    driver = axial_cylinder(14, 0.3, 100).placed((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert scene.hits(driver) == ("pebble",)


def test_an_oblique_tool_solid_lands_where_it_should(scene_of):
    # A handle at 45 deg in a frame tilted off every axis, past one post and
    # well clear of another on the far side.
    axis = (0.0, 0.6, 0.8)
    handle = radial_box(10, 4, 0, 100, 20, 45).placed((10.0, 20.0, 30.0), axis)
    centre = handle.shape().center()
    near = Pos(centre) * Box(2, 2, 2)
    far = Pos(2 * 10 - centre.X, 2 * 20 - centre.Y, 2 * 30 - centre.Z) * Box(2, 2, 2)
    scene = scene_of(near=near, far=far)
    assert scene.hits(handle) == ("near",)


def test_an_empty_scene_is_clear(scene_of, along_x):
    scene = scene_of()
    assert scene.hits(along_x(0)) == ()
    assert scene.clear(along_x(0))


def test_box_overlap_prefilter():
    a = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    near = ((1.05, 0.0, 0.0), (2.0, 1.0, 1.0))  # inside the 0.1 margin
    far = ((5.0, 0.0, 0.0), (6.0, 1.0, 1.0))
    assert boxes_overlap(a, near)
    assert not boxes_overlap(a, far)
    assert boxes_overlap(a, a)


@pytest.mark.parametrize("tilt", [0, 17, 45, 90])
def test_the_quick_box_always_holds_the_tight_one(tilt):
    # The prefilter's box may be loose, never tight: a part outside it would
    # never be tested, whatever the engine.
    shape = Rot(tilt, tilt / 2, 0) * (Cylinder(7, 30) - Cylinder(3, 31))
    (lo, hi), tight = shape_bounds(shape), shape.bounding_box()
    tight_lo, tight_hi = tuple(tight.min), tuple(tight.max)
    assert all(lo[i] <= tight_lo[i] + 1e-9 for i in range(3))
    assert all(hi[i] >= tight_hi[i] - 1e-9 for i in range(3))


def test_engines_by_name():
    assert ENGINES == ("mesh", "exact")
    assert DEFAULT_ENGINE == "mesh"
    assert isinstance(make_engine(), MeshEngine)
    assert isinstance(make_engine("exact"), ExactEngine)
    with pytest.raises(ValueError, match="unknown engine 'fcl'"):
        make_engine("fcl")


def test_check_rejects_an_unknown_engine():
    assembly = Assembly([Part("bolt", Cylinder(3, 20))])
    with pytest.raises(ValueError, match="unknown engine"):
        check(assembly, Config(), engine="fcl")


def test_the_report_names_its_engine(engine):
    report = check(Assembly([Part("bolt", Cylinder(3, 20))]), Config(), engine=engine)
    assert report.engine == engine
    assert report.to_json_dict()["engine"] == engine


# ---------------------------------------------------------------------------
# The mesh engine's own promises.
# ---------------------------------------------------------------------------


def test_parts_are_meshed_once_and_only_when_a_tool_comes_near():
    engine = MeshEngine()
    wall, far = Part("wall", Box(10, 40, 40)), Part("far", Pos(500, 0, 0) * Box(10, 10, 10))
    for _ in range(3):  # three fasteners' scenes over the same parts
        engine.scene([wall, far]).hits(x_tool(0))
    assert engine.meshed == ("wall",)


def test_clear_stops_at_the_first_offender():
    engine = MeshEngine()
    scene = engine.scene(
        [Part("first", Box(10, 40, 40)), Part("second", Pos(12, 0, 0) * Box(10, 40, 40))]
    )
    assert not scene.clear(x_tool(6, length=40))
    assert engine.meshed == ("first",)  # never needed the second


def test_the_same_name_in_another_model_is_another_part():
    # The lever in a state's alternate model has the default model's name and
    # other geometry. A cache keyed by name would answer with the wrong lever.
    # The raised one sits in the corner of the tool's box, outside its round
    # (2.26 from the axis against r 2): near enough to be meshed, never hit.
    engine = MeshEngine()
    down = Part("lever", Box(10, 40, 40))
    up = Part("lever", Pos(0, 1.8, 1.8) * Box(10, 0.4, 0.4))
    assert engine.scene([down]).hits(x_tool(0)) == ("lever",)
    assert engine.scene([up]).hits(x_tool(0)) == ()
    assert engine.meshed == ("lever", "lever")


def test_a_part_that_will_not_mesh_is_tested_exactly(monkeypatch):
    # Its triangles never come, and mending can't make them (issue #85).
    refuse = {"wall"}
    real = mesh_module.shape_triangles

    def flaky(shape, tolerance=MESH_TOLERANCE):
        return None if shape.label in refuse else real(shape, tolerance)

    monkeypatch.setattr(mesh_module, "shape_triangles", flaky)
    monkeypatch.setattr(mesh_module, "_split_closed", lambda shape: shape)
    wall = Box(10, 40, 40)
    wall.label = "wall"
    engine = MeshEngine()
    scene = engine.scene([Part("wall", wall)])
    assert scene.hits(x_tool(0)) == ("wall",)  # answered by the exact engine
    assert scene.hits(x_tool(100)) == ()
    assert engine.fallbacks == ["wall"]


def test_an_open_face_does_not_mesh_and_never_hits():
    face = Pos(0, 0, 0) * Rectangle(40, 40)  # a sheet: no volume to hit
    assert solid_mesh(face) is None
    engine = MeshEngine()
    assert engine.scene([Part("sheet", face)]).hits(x_tool(0, length=60)) == ()
    assert engine.fallbacks == ["sheet"]


@pytest.mark.parametrize(
    ("shape", "volume"),
    [
        (Box(10, 20, 30), 6000.0),
        (Pos(1e4, -3e4, 5e3) * Box(10, 20, 30), 6000.0),  # far from the origin
        (Cylinder(5, 20), 3.141592653589793 * 25 * 20),
        (Box(40, 40, 10) - Cylinder(6, 11), 16000.0 - 3.141592653589793 * 36 * 10),
    ],
    ids=["box", "far box", "cylinder", "plate with hole"],
)
def test_a_part_mesh_is_closed_and_close(shape, volume):
    mesh = solid_mesh(shape)
    assert mesh is not None
    assert mesh.volume() == pytest.approx(volume, rel=0.02)


def test_meshing_ignores_whatever_meshed_the_shape_before():
    shape = Cylinder(20, 10)
    fresh = solid_mesh(shape).volume()
    solid_mesh(shape, tolerance=2.0)  # leaves a coarse triangulation behind
    assert solid_mesh(shape).volume() == fresh


@pytest.mark.parametrize(("clearance", "referred"), [(0.05, 1), (0.5, 0)])
def test_where_a_mesh_could_be_wrong_the_referee_decides(clearance, referred):
    # A shaft in a bore. The bore's mesh is drawn inside its true circle by up
    # to the 0.2 mm tolerance, so with 0.05 mm of clearance the mesh alone read
    # blocked where the exact engine reads clear (issue #25). The mesh engine
    # now refers such a part to its exact referee, and agrees; with 0.5 mm the
    # gap is wider than the mesh can stray, and it decides alone.
    tube = Cylinder(30, 40) - Cylinder(5 + clearance, 41)
    shaft = axial_cylinder(5, -10, 10).placed((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert make_engine("exact").scene([Part("tube", tube)]).hits(shaft) == ()
    mesh = make_engine("mesh")
    assert mesh.scene([Part("tube", tube)]).hits(shaft) == ()
    assert mesh.referred == referred


def test_hits_are_volumes_not_contacts():
    # Same threshold, same units in both engines.
    assert HIT_MIN_VOLUME == 0.05


def test_a_tool_solid_is_placed_once():
    local = axial_cylinder(1, 0, 10)
    placed = local.placed((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    with pytest.raises(ValueError, match="placed once"):
        placed.placed((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    with pytest.raises(ValueError, match="before placing"):
        placed + local
    with pytest.raises(ValueError, match="at least one primitive"):
        ToolSolid(()).shape()


def test_a_part_across_two_pieces_counts_their_overlaps_together(engine):
    # Two boxes end to end along x, meeting at x = 10; a sliver of part straddles
    # the seam, 0.03 mm^3 in each: under the hit floor apiece, over it together.
    # A tool's pieces never overlap (solids.py), so their overlaps add up to the
    # whole tool's, and both engines must add them.
    tool = ToolSolid(
        (RadialBox(4.0, 2.0, 0.0, 10.0, 0.0, 0.0), RadialBox(4.0, 2.0, 10.0, 20.0, 0.0, 0.0))
    ).placed((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    sliver = Pos(10, 0, 0) * Box(0.2, 0.6, 0.5)  # 0.1 x 0.6 x 0.5 = 0.03 each side
    assert 0.03 < HIT_MIN_VOLUME < 0.06
    scene = make_engine(engine).scene([Part("sliver", sliver)])
    assert scene.hits(tool) == ("sliver",)
    alone = ToolSolid((RadialBox(4.0, 2.0, 0.0, 10.0, 0.0, 0.0),)).placed(
        (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    )
    assert scene.hits(alone) == ()  # one piece's share alone is under the floor


def test_an_overlap_is_measured_next_to_the_origin(monkeypatch):
    # 35 m out, a double's last digit of a coordinate squared is as large as the
    # 1e-7 mm OCP decides a coincidence by, and on Linux a graze measured 365
    # mm^3 there (issue #107). Both shapes are moved by one step, the second's
    # box centre to the origin, as locations sharing their geometry.
    ring = Cylinder(70, 4) - Cylinder(12, 4)
    arm = Pos(40, 0, 2 - 0.004 + 1.25) * Box(40, 2.5, 2.5)  # 0.004 into the ring's top
    near = exact_overlap(ring, arm)
    assert near == pytest.approx(40 * 2.5 * 0.004)
    far = Pos(3000, 35000, 0)
    ring, arm = far * ring, far * arm
    seen = []
    intersect = Shape.intersect

    def spy(self, *others, **kwargs):
        seen.extend((self, *others))
        return intersect(self, *others, **kwargs)

    monkeypatch.setattr(Shape, "intersect", spy)
    assert exact_overlap(ring, arm) == pytest.approx(near, rel=1e-9)
    assert len(seen) == 2
    for shape, was in zip(seen, (ring, arm), strict=True):
        assert shape.wrapped.IsPartner(was.wrapped)  # the same geometry, not a copy
        low, high = shape_bounds(shape)
        assert max(abs(c) for c in (*low, *high)) < 200
