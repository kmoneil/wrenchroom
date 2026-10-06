"""Assembly input: names survive a STEP round-trip and repeats become unique."""

import pytest
from build123d import Box, Compound, Cylinder, Pos, export_step

from wrenchroom import Assembly
from wrenchroom.assembly import UNNAMED, Part


def four_labelled_solids():
    """Two frame blocks and two bolts sharing one name, like a real export does."""
    left = Pos(0, 0, 0) * Box(10, 10, 10)
    left.label = "frame_left"
    right = Pos(30, 0, 0) * Box(10, 10, 10)
    right.label = "frame_right"
    bolt_a = Pos(15, 0, 20) * Cylinder(3, 12)
    bolt_a.label = "block_frontL_bolt_0"
    bolt_b = Pos(15, 20, 20) * Cylinder(3, 12)
    bolt_b.label = "block_frontL_bolt_0"
    return [left, right, bolt_a, bolt_b]


def test_step_round_trip_keeps_names_and_makes_repeats_unique(tmp_path):
    compound = Compound(children=four_labelled_solids())
    compound.label = "probe"
    path = tmp_path / "probe.step"
    export_step(compound, str(path))

    assembly = Assembly.from_step(path)

    assert assembly.names == (
        "frame_left",
        "frame_right",
        "block_frontL_bolt_0",
        "block_frontL_bolt_0#2",
    )
    assert len(assembly) == 4


def test_from_shapes_matches_the_step_path():
    shapes = [(solid.label, solid) for solid in four_labelled_solids()]
    assembly = Assembly.from_shapes(shapes)
    assert assembly.names == (
        "frame_left",
        "frame_right",
        "block_frontL_bolt_0",
        "block_frontL_bolt_0#2",
    )


def test_from_compound_inherits_the_nearest_label():
    inner = Pos(0, 0, 0) * Box(5, 5, 5)  # deliberately unlabelled
    sub = Compound(children=[inner])
    sub.label = "gearbox"
    outer = Compound(children=[sub])
    assembly = Assembly.from_compound(outer)
    assert assembly.names == ("gearbox",)


def test_unlabelled_solid_is_named_unnamed():
    box = Box(5, 5, 5)
    assembly = Assembly.from_compound(Compound(children=[box]))
    assert assembly.names == (UNNAMED,)


def test_lookup_by_name_and_miss():
    assembly = Assembly.from_shapes([("lid", Box(5, 5, 5))])
    assert assembly["lid"].name == "lid"
    with pytest.raises(KeyError):
        assembly["base"]


def test_empty_input_is_an_error():
    with pytest.raises(ValueError, match="no solids found"):
        Assembly.from_shapes([])


def test_constructor_rejects_repeated_names():
    box = Box(5, 5, 5)
    with pytest.raises(ValueError, match="repeated: lid"):
        Assembly([Part("lid", box), Part("lid", box)])
