"""A fastener drawn as several solids is one fastener (issue #28).

A leaf of a STEP file holding several solids (a nut and its washer drawn as one
part, a nyloc as nut and dome) is split one part per solid, as collision wants.
Its largest solid keeps the leaf's name and each other is a piece of it: a rule
and detection see the leaf, never a piece; a fastener's pieces leave its scene
with it; an ignored leaf takes its pieces along; the view paints them as it.
"""

import math

import pytest
from build123d import Box, Compound, Cylinder, Pos, RegularPolygon, Rot, export_step, extrude

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.view import view_data


def hexagon(af, h, z0=0.0):
    return Pos(0, 0, z0) * extrude(RegularPolygon(af / math.sqrt(3), 6), h)


def washer_and_nut():
    """The issue's part: a washer (the smaller) drawn first, then an M8 nut on it."""
    washer = Pos(0, 0, 0.8) * (Cylinder(8, 1.6) - Cylinder(4.2, 1.6))
    nut = hexagon(13, 6.8, 1.6) - Cylinder(4, 30)
    return Compound([washer.solid(), nut.solid()])


def nut_and_dome():
    """An M8 nyloc as one part: the nut, and its nylon dome on the free face."""
    nut = hexagon(13, 6.8) - Cylinder(4, 20)
    dome = Pos(0, 0, 6.8 + 1.25) * (Cylinder(6, 2.5) - Cylinder(4, 3))
    return Compound([dome.solid(), nut.solid()])


def joint(nut, prefix="two_solids"):
    """A plate, an M8-ish bolt up through it with its head below, and the nut part."""
    plate = Pos(0, 0, -3) * (Box(80, 80, 6) - Cylinder(4.5, 6))
    bolt = Pos(0, 0, 4) * Cylinder(4, 20) + Pos(0, 0, -6 - 5.3) * hexagon(13, 5.3)
    return [(f"{prefix}_plate", plate), (f"{prefix}_bolt", bolt), (f"{prefix}_nut", nut)]


def from_step(tmp_path, named, file="model.step"):
    shapes = []
    for name, shape in named:
        shape.label = name
        shapes.append(shape)
    path = tmp_path / file
    export_step(Compound(children=shapes), str(path))
    return Assembly.from_step(path)


# ---------------------------------------------------------------------------
# The assembly: one part per solid, the pieces marked.
# ---------------------------------------------------------------------------


def test_the_largest_solid_keeps_the_name_and_the_rest_are_its_pieces(tmp_path):
    assembly = from_step(tmp_path, joint(washer_and_nut()))
    assert assembly.names == (
        "two_solids_plate",
        "two_solids_bolt",
        "two_solids_nut",
        "two_solids_nut#2",
    )
    nut, washer = assembly["two_solids_nut"], assembly["two_solids_nut#2"]
    assert nut.shape.volume > washer.shape.volume  # the nut, though the washer came first
    assert (nut.piece_of, washer.piece_of) == (None, "two_solids_nut")
    assert assembly.pieces("two_solids_nut") == ("two_solids_nut#2",)
    assert assembly.pieces("two_solids_bolt") == ()


def test_two_placements_of_a_two_solid_part_are_two_parts_each_with_its_piece(tmp_path):
    first = washer_and_nut()
    second = Pos(200, 0, 0) * washer_and_nut()
    assembly = from_step(tmp_path, [("nut", first), ("nut", second)])
    pieces = {part.name: part.piece_of for part in assembly}
    assert pieces == {"nut": None, "nut#2": "nut", "nut#3": None, "nut#4": "nut#3"}


def test_a_name_repeated_on_one_solid_parts_marks_no_pieces(tmp_path):
    # Two screws named alike are two instances, not one part's pieces.
    screw = Cylinder(3, 20)
    assembly = from_step(tmp_path, [("screw", screw), ("screw", Pos(50, 0, 0) * screw)])
    assert [(p.name, p.piece_of) for p in assembly] == [("screw", None), ("screw#2", None)]


def test_from_compound_marks_pieces_too():
    nut = washer_and_nut()
    nut.label = "nut"
    assembly = Assembly.from_compound(Compound(children=[nut]))
    assert [(p.name, p.piece_of) for p in assembly] == [("nut", None), ("nut#2", "nut")]


def test_from_shapes_keeps_a_caller_s_several_solids_whole():
    assembly = Assembly.from_shapes([("nut", washer_and_nut())])
    (part,) = assembly
    assert (part.name, part.piece_of, len(part.shape.solids())) == ("nut", None, 2)


# ---------------------------------------------------------------------------
# The check: one fastener, its pieces with it.
# ---------------------------------------------------------------------------


def test_the_issue_s_nut_is_one_fastener_that_turns(tmp_path):
    report = check(from_step(tmp_path, joint(washer_and_nut())), kit="full")
    by_name = {r.fastener.name: r for r in report.results}
    assert sorted(by_name) == ["two_solids_bolt", "two_solids_nut"]  # no "#2" fastener
    nut = by_name["two_solids_nut"]
    assert (nut.verdict, nut.tool, nut.how) == (Verdict.TURNS, "spanner-13", "ring, full length")
    assert nut.fastener.confidence == "high"
    assert report.passed_over == ()
    assert report.exit_code == 0


def test_a_piece_on_the_free_face_leaves_the_scene_with_its_fastener(tmp_path, engine):
    # The dome covers the nut's top: as another part, both ends would read covered.
    report = check(from_step(tmp_path, joint(nut_and_dome())), kit="full", engine=engine)
    (nut,) = [r for r in report.results if r.fastener.name == "two_solids_nut"]
    assert (nut.verdict, nut.tool) == (Verdict.TURNS, "spanner-13")


def test_the_same_dome_as_a_part_of_its_own_still_needs_its_mate(tmp_path):
    # Two leaves, not one: the dome is a part like any other, as before.
    nut, dome = nut_and_dome().solids()[1], nut_and_dome().solids()[0]
    named = [*joint(nut)[:2], ("two_solids_nut", nut), ("two_solids_dome", dome)]
    assembly = from_step(tmp_path, named)
    assert all(part.piece_of is None for part in assembly)
    (result,) = [
        r for r in check(assembly, kit="full").results if r.fastener.name == "two_solids_nut"
    ]
    assert result.reason == "cannot tell the nut's free face: both ends are covered"


def test_a_rule_names_the_leaf_and_never_a_piece(tmp_path):
    assembly = from_step(tmp_path, joint(nut_and_dome()))
    rules = [
        {"parts": "two_solids_*", "kind": "nut", "size": "M8"},  # a glob that would take "#2"
        {"parts": "two_solids_bolt", "kind": "screw", "head": "hex", "size": "M8"},
        {"parts": "two_solids_plate", "kind": "screw"},  # not a fastener, but named
    ]
    config = Config.from_dict({"fasteners": rules[:2], "checks": {"detect": False}})
    report = check(assembly, config, kit="full")
    names = sorted(r.fastener.name for r in report.results)
    assert names == ["two_solids_bolt", "two_solids_nut", "two_solids_plate"]
    (nut,) = [r for r in report.results if r.fastener.name == "two_solids_nut"]
    assert nut.verdict is Verdict.TURNS


def test_an_ignored_leaf_takes_its_pieces_along(tmp_path):
    named = joint(nut_and_dome())
    assembly = from_step(tmp_path, named)
    config = Config.from_dict({"ignore": ["two_solids_nut"]})
    report = check(assembly, config, kit="full")
    assert {"two_solids_nut", "two_solids_nut#2"} <= report.ignored
    assert [r.fastener.name for r in report.results] == ["two_solids_bolt"]


def test_the_view_draws_a_piece_as_its_fastener(tmp_path):
    report = check(from_step(tmp_path, joint(nut_and_dome())), kit="full")
    parts = {part["name"]: part for part in view_data(report)["parts"]}
    assert (parts["two_solids_nut#2"]["owner"], parts["two_solids_nut#2"]["role"]) == (
        "two_solids_nut",
        "fastener",
    )
    assert (parts["two_solids_nut"]["owner"], parts["two_solids_nut"]["role"]) == (None, "fastener")
    assert parts["two_solids_plate"]["owner"] is None


@pytest.mark.parametrize("flip", [False, True])
def test_detect_writes_one_rule_for_the_part(tmp_path, flip):
    from click.testing import CliRunner  # noqa: PLC0415

    from wrenchroom.cli import main  # noqa: PLC0415

    nut = washer_and_nut()
    named = joint(Rot(180, 0, 0) * nut if flip else nut)
    path = tmp_path / "model.step"
    from_step(tmp_path, named)
    text = CliRunner().invoke(main, ["detect", str(path)]).stdout
    assert "parts: two_solids_nut\n" in text
    assert "two_solids_nut#2" not in text
