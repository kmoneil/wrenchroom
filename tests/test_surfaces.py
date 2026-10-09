"""Parts drawn as surfaces, not solids, which the reader used to drop without a word (#104).

A closed shell bounds a volume as a solid does, and is taken as that solid. An open
shell or loose faces bound nothing a tool could meet: the part is left out, and every
report says so and names it. A sidecar rule naming only such a part says that, not
"renamed part?", and an ignore naming one is satisfied: the part is out anyway.
"""

import json

import pytest
from build123d import Box, Compound, Cylinder, Pos, Shell, Solid, export_step

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Report, Verdict

BOX = Box(10, 10, 10)


def closed_shell(at=0.0):
    return Pos(at, 0, 0) * Shell(BOX.faces())


def open_shell(at=0.0):
    return Pos(at, 0, 0) * Shell(BOX.faces()[:-1])


def one_face(at=0.0):
    return Pos(at, 0, 0) * BOX.faces()[0]


def write(tmp_path, named):
    shapes = []
    for name, shape in named:
        shape.label = name
        shapes.append(shape)
    path = tmp_path / "model.step"
    export_step(Compound(children=shapes), str(path))
    return path


@pytest.fixture
def model(tmp_path):
    """The issue's four: a solid, a closed shell, an open shell, one face."""
    return write(
        tmp_path,
        [
            ("solid block", Pos(0, 0, 0) * Box(10, 10, 10)),
            ("closed shell", closed_shell(30)),
            ("open shell", open_shell(60)),
            ("one face", one_face(90)),
        ],
    )


def test_a_closed_shell_is_the_solid_it_bounds_and_the_rest_are_surfaces(model):
    assembly = Assembly.from_step(model)
    parts = {part.name: part.shape for part in assembly}
    assert list(parts) == ["solid block", "closed shell"]
    assert isinstance(parts["closed shell"], Solid)
    assert parts["closed shell"].volume == pytest.approx(1000.0)
    assert assembly.surfaces == ("open shell", "one face")


def test_a_leaf_of_two_closed_shells_is_a_part_and_its_piece(tmp_path):
    two = Compound([closed_shell(), Pos(0, 0, 20) * Shell(Box(4, 4, 4).faces())])
    assembly = Assembly.from_step(write(tmp_path, [("pair", two)]))
    assert [(p.name, p.piece_of) for p in assembly] == [("pair", None), ("pair#2", "pair")]
    assert assembly.parts[0].shape.volume == pytest.approx(1000.0)  # the larger first


def test_a_model_of_nothing_but_surfaces_says_so(tmp_path):
    path = write(tmp_path, [("a", open_shell()), ("b", one_face(30))])
    with pytest.raises(
        ValueError, match=r"no solids found in .*: 2 parts are surfaces only \(a, b\)"
    ):
        Assembly.from_step(path)


def test_from_shapes_and_from_compound_read_surfaces_the_same_way():
    shapes = [("solid", Box(5, 5, 5)), ("closed", closed_shell(30)), ("open", open_shell(60))]
    assembly = Assembly.from_shapes(shapes)
    assert assembly.names == ("solid", "closed")
    assert isinstance(assembly["closed"].shape, Solid)
    assert assembly.surfaces == ("open",)
    labelled = []
    for name, shape in shapes:
        shape.label = name
        labelled.append(shape)
    from_compound = Assembly.from_compound(Compound(children=labelled))
    assert (from_compound.names, from_compound.surfaces) == (("solid", "closed"), ("open",))


def test_every_report_says_the_surfaces(model):
    report = check(Assembly.from_step(model))
    lines = report.terminal_lines()
    note = "2 parts drawn as surfaces, not solids, are left out, as nothing can meet them"
    assert f"NOTE {note}: open shell, one face" in lines
    assert lines[-1] == (
        "NOTE not checked: room for a hand (checks: {hand_room: true} turns it on); "
        "parts drawn into each other (checks: {clashes: true} turns it on); "
        "2 parts drawn as surfaces, not solids (left out); parts the model doesn't have"
    )
    assert json.loads(report.json_text())["surfaces"] == ["open shell", "one face"]
    markdown = report.markdown()
    assert f"The model: {note}: `open shell`, `one face`." in markdown
    assert "2 parts drawn as surfaces, not solids (left out); parts the model" in markdown
    assert report.exit_code == 0  # said, not failed


def test_one_surface_is_said_in_the_singular():
    report = Report(model="m", kit="full", results=(), surfaces=("decal",))
    assert report.surfaces_note == (
        "1 part drawn as a surface, not a solid, is left out, as nothing can meet it"
    )
    assert "1 part drawn as a surface, not a solid (left out)" in report.not_checked


def test_no_surfaces_says_nothing_new():
    report = Report(model="m", kit="full", results=())
    assert "surface" not in report.not_checked
    assert not any("surface" in line for line in report.terminal_lines())
    assert json.loads(report.json_text())["surfaces"] == []


def test_a_rule_naming_only_a_surface_says_so(model):
    rule = {"parts": "one face", "kind": "screw", "head": "socket", "size": "M3"}
    report = check(Assembly.from_step(model), Config.from_dict({"fasteners": [rule]}))
    assert report.unmatched_rules == ()
    assert report.warnings == (
        "rule 'one face' names only one face, drawn as a surface, not a solid: "
        "make it a solid to check it",
    )
    assert report.exit_code == 2  # a described fastener nothing can check


def test_a_rule_naming_several_surfaces_says_them_all(model):
    rule = {"parts": "o*", "kind": "screw", "head": "socket", "size": "M3"}
    report = check(Assembly.from_step(model), Config.from_dict({"fasteners": [rule]}))
    assert report.warnings == (
        "rule 'o*' names only open shell, one face, drawn as surfaces, not solids: "
        "make them solids to check them",
    )


def test_a_rule_naming_nothing_at_all_is_still_a_rename(model):
    rule = {"parts": "gone", "kind": "screw", "head": "socket", "size": "M3"}
    report = check(Assembly.from_step(model), Config.from_dict({"fasteners": [rule]}))
    assert report.unmatched_rules == ("gone",)
    assert report.warnings == ()


def test_an_ignore_naming_a_surface_is_satisfied(model):
    report = check(Assembly.from_step(model), Config.from_dict({"ignore": ["open shell"]}))
    assert report.unmatched_ignores == ()
    assert report.exit_code == 0


@pytest.mark.parametrize("engine", ["mesh", "exact"])
def test_a_closed_shell_ceiling_stops_a_key_as_a_solid_one_does(tmp_path, engine):
    # An M6 socket head under a ceiling 15 over it, exported as a closed shell: once
    # dropped, the key turned the screw through it.
    plate = Pos(0, 0, -5) * Box(200, 200, 10) - Cylinder(3, 30)
    head = Pos(0, 0, 3) * Cylinder(5, 6) - Pos(0, 0, 4.5) * Box(5, 5, 3.01)
    screw = head + Pos(0, 0, -10) * Cylinder(3, 20)
    ceiling = Pos(0, 0, 6 + 15 + 5) * Shell(Box(300, 300, 10).faces())
    path = write(tmp_path, [("plate", plate), ("screw", screw), ("ceiling", ceiling)])
    rule = {"parts": "screw", "kind": "screw", "head": "socket", "size": "M6"}
    report = check(Assembly.from_step(path), Config.from_dict({"fasteners": [rule]}), engine=engine)
    (result,) = report.results
    assert (result.verdict, result.blocked_by) == (Verdict.BLOCKED, ("ceiling",))
    assert report.surfaces == ()
