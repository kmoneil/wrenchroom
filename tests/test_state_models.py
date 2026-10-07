"""A state's model that lacks a fastener says so, and fails the run (issue #74).

A state's model is meant to be the same parts, moved. When an export renamed or
dropped a fastener, the fastener was quietly not tried in that state, and its
default-state verdict stood with the default state's cause: the user went looking at
the lever, not at the export. Now a retry in a state whose model lacks the fastener
is a warning that fails the run, as an unmatched glob is; a fastener whose own state
it is is not covered, naming the model; and a state's model whose part names differ
from the main model's is noted, without failing, since a state may add or take away
parts on purpose.
"""

import json

import pytest
from build123d import Box, Compound, Pos, export_step

from fixture_models import screw_facing_wall
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict, md_text

M6_SOCKET = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}
RETRY = {"states": {"lever-up": {"model": "moved.step"}}, "checks": {"try_states": ["lever-up"]}}


def write(path, assembly, rename=None, drop=()):
    """Write an assembly as STEP, its parts renamed or dropped as asked."""
    rename = rename or {}
    shapes = []
    for part in assembly:
        if part.name in drop:
            continue
        part.shape.label = rename.get(part.name, part.name)
        shapes.append(part.shape)
    export_step(Compound(children=shapes), str(path))


def run(tmp_path, moved, config, rule=M6_SOCKET):
    """The screw under a wall 15 over it, a lever-up state ``moved``, checked."""
    write(tmp_path / "main.step", screw_facing_wall(15.0))
    moved(tmp_path / "moved.step")
    config = Config.from_dict({"fasteners": [rule], **config})
    return check(Assembly.from_step(tmp_path / "main.step"), config, model_dir=tmp_path)


def wall_away(rename=None, drop=()):
    """The lever-up model: the wall 300 over the screw, its parts renamed or dropped."""
    return lambda path: write(path, screw_facing_wall(300.0), rename, drop)


def test_with_the_same_names_the_state_is_tried_and_nothing_said(tmp_path):
    report = run(tmp_path, wall_away(), RETRY)
    (result,) = report.results
    assert (result.verdict, result.state) == (Verdict.TURNS, "lever-up")
    assert (report.warnings, report.notes, report.exit_code) == ((), (), 0)


@pytest.mark.parametrize(
    ("moved", "note"),
    [
        (
            wall_away(rename={"bolt": "bolt_renamed"}),
            "state 'lever-up': its model moved.step lacks 1 part of the main model's: bolt; "
            "has 1 part the main model doesn't: bolt_renamed",
        ),
        (
            wall_away(drop={"bolt"}),
            "state 'lever-up': its model moved.step lacks 1 part of the main model's: bolt",
        ),
    ],
    ids=["renamed", "dropped"],
)
def test_a_retry_state_whose_model_lacks_the_fastener_fails_the_run(tmp_path, moved, note):
    report = run(tmp_path, moved, RETRY)
    (result,) = report.results
    # Its verdict is still the default state's, but the run says why it stands.
    assert (result.verdict, result.blocked_by) == (Verdict.BLOCKED, ("wall",))
    warning = (
        "state 'lever-up': its model moved.step has no part bolt (renamed?), "
        "so it wasn't tried there"
    )
    assert report.warnings == (warning,)
    assert report.exit_code == 2
    assert report.notes == (note,)
    lines = report.terminal_lines()
    assert f"WARN {warning}" in lines
    assert f"NOTE {note}" in lines
    document = json.loads(report.json_text())
    assert (document["warnings"], document["notes"]) == ([warning], [note])
    assert f"- {md_text(note)}" in report.markdown()  # escaped: names come from the model


def test_its_own_state_lacking_it_is_not_covered_naming_the_model(tmp_path):
    rule = {**M6_SOCKET, "state": "lever-up"}
    states = {"states": {"lever-up": {"model": "moved.step"}}}
    report = run(tmp_path, wall_away(rename={"bolt": "bolt_2"}), states, rule)
    (result,) = report.results
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == (
        "not in state 'lever-up', whose model moved.step has no part of its name (renamed?)"
    )
    assert report.warnings == ()  # the reason says it; not twice


def test_only_the_names_that_differ_are_noted_and_ignored_parts_aren_t(tmp_path):
    # The main model has a cable the sidecar ignores, and the lever-up model hasn't:
    # no note. A part only the lever-up model has is noted.
    def main(path):
        screw = screw_facing_wall(15.0)
        cable = Part("loom_cable", Pos(80, 0, 0) * Box(5, 5, 5))
        write(path, Assembly([*screw, cable]))

    def moved(path):
        screw = screw_facing_wall(300.0)
        write(path, Assembly([*screw, Part("lever", Pos(-80, 0, 0) * Box(5, 5, 5))]))

    main(tmp_path / "main.step")
    moved(tmp_path / "moved.step")
    config = Config.from_dict({"fasteners": [M6_SOCKET], "ignore": ["*_cable"], **RETRY})
    report = check(Assembly.from_step(tmp_path / "main.step"), config, model_dir=tmp_path)
    assert report.notes == (
        "state 'lever-up': its model moved.step has 1 part the main model doesn't: lever",
    )
    assert report.warnings == ()
    assert report.results[0].verdict is Verdict.TURNS


def test_a_removal_only_state_has_no_model_to_lack_anything(tmp_path):
    del tmp_path
    config = Config.from_dict(
        {
            "fasteners": [M6_SOCKET],
            "states": {"open": {"remove": ["wall"]}},
            "checks": {"try_states": ["open"]},
        }
    )
    report = check(screw_facing_wall(15.0), config)
    assert (report.results[0].verdict, report.warnings, report.notes) == (Verdict.TURNS, (), ())
