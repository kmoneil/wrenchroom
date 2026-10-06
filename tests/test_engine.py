"""The exact engine: hits name their parts, touches and slivers don't count."""

from build123d import Box, Cylinder, Pos, Rot

from wrenchroom.assembly import Part
from wrenchroom.engine import Scene, _boxes_overlap


def scene_of(**shapes):
    return Scene(Part(name, shape) for name, shape in shapes.items())


def x_cylinder(x, radius=2, length=30):
    """A cylinder along x, centred at (x, 0, 0)."""
    return Pos(x, 0, 0) * Rot(0, 90, 0) * Cylinder(radius, length)


def test_a_tool_through_a_part_names_it():
    scene = scene_of(wall=Box(10, 40, 40), bystander=Pos(100, 0, 0) * Box(10, 10, 10))
    assert scene.hits(x_cylinder(0)) == ("wall",)
    assert not scene.clear(x_cylinder(0))


def test_a_tool_through_two_parts_names_both_in_order():
    scene = scene_of(first=Box(10, 40, 40), second=Pos(12, 0, 0) * Box(10, 40, 40))
    assert scene.hits(x_cylinder(6, length=40)) == ("first", "second")


def test_a_clear_tool_hits_nothing():
    scene = scene_of(wall=Box(10, 40, 40))
    probe = Pos(0, 0, 50) * Box(2, 2, 2)
    assert scene.hits(probe) == ()
    assert scene.clear(probe)


def test_a_tangent_touch_is_not_a_hit():
    # The cylinder's end lands exactly on the wall's face: contact, zero volume.
    scene = scene_of(wall=Box(10, 40, 40))
    touching = x_cylinder(5 + 15)  # ends at x = 5, the wall's face
    assert scene.hits(touching) == ()


def test_a_sliver_below_the_volume_floor_is_not_a_hit():
    # 1 x 1 mm cross-section buried 0.04 mm: 0.04 mm^3, under the 0.05 floor.
    scene = scene_of(wall=Box(10, 40, 40))
    sliver = Pos(5 - 0.02 + 0.5, 0, 0) * Box(1, 1, 1)
    assert scene.hits(sliver) == ()
    deeper = Pos(5 - 0.1 + 0.5, 0, 0) * Box(1, 1, 1)  # 0.1 mm^3: over it
    assert scene.hits(deeper) == ("wall",)


def test_box_overlap_prefilter():
    a = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    near = ((1.05, 0.0, 0.0), (2.0, 1.0, 1.0))  # inside the 0.1 margin
    far = ((5.0, 0.0, 0.0), (6.0, 1.0, 1.0))
    assert _boxes_overlap(a, near)
    assert not _boxes_overlap(a, far)
    assert _boxes_overlap(a, a)
