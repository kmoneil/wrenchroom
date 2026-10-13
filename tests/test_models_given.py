"""A state's or a build step's model given as an assembly, no file written (issue #196).

``check`` takes the main model as an assembly, so a build script checks what it has
just built. A state's ``model:``, and a build step's, could only be a STEP file,
looked for beside the sidecar or the model: a script whose states are its own build
at other positions had to export each and have it read back. The round trip changed
the parts, too: ``from_shapes`` keeps a part drawn as several solids whole, where the
same part read from STEP is its largest solid and ``name#2`` pieces, so the run noted
every such part as one the main model hasn't.

``models=`` hands them over, each under the name the sidecar gives its model. One
given is used as it is and no file is looked for; one not given is read from its file,
as it was; a name no state or step has, or a thing that is no assembly, is refused
before anything is checked.
"""

import base64
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest
import yaml
from build123d import Box, Compound, Cylinder, Pos, RegularPolygon, export_step, extrude

from fixture_models import screw_facing_wall
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check, find_clashes
from wrenchroom.config import Config, ConfigError
from wrenchroom.engine import ENGINES
from wrenchroom.report import Verdict
from wrenchroom.view import view_data

M6_SOCKET = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}
SIDECAR = {
    "fasteners": [M6_SOCKET],
    "states": {"lever-up": {"model": "moved.step"}},
    "checks": {"try_states": ["lever-up"]},
}

#: How far over the screw's head the wall is, mm: no key gets in under it, and any does.
CLOSE, AWAY = 15.0, 300.0


def write_step(path, assembly):
    shapes = []
    for part in assembly:
        part.shape.label = part.name
        shapes.append(part.shape)
    path.parent.mkdir(parents=True, exist_ok=True)
    export_step(Compound(children=shapes), str(path))
    return path


def verdict(report):
    (result,) = report.results
    return result.verdict, result.state


# ---------------------------------------------------------------------------
# A state's model.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", ENGINES)
def test_a_state_s_model_is_taken_as_an_assembly_and_no_file_is_needed(engine):
    # A sidecar from a mapping has no folder, and no model_dir is given: there is
    # nowhere a file could be looked for.
    report = check(
        screw_facing_wall(CLOSE),
        Config.from_dict(SIDECAR),
        models={"moved.step": screw_facing_wall(AWAY)},
        engine=engine,
    )
    assert verdict(report) == (Verdict.TURNS, "lever-up")
    assert (report.warnings, report.notes, report.exit_code) == ((), (), 0)


@pytest.mark.parametrize(
    ("on_disk", "given", "expected"),
    [(CLOSE, AWAY, (Verdict.TURNS, "lever-up")), (AWAY, CLOSE, (Verdict.BLOCKED, None))],
    ids=["given-passes", "given-fails"],
)
def test_the_one_given_is_used_whatever_file_is_there(tmp_path, on_disk, given, expected):
    # moved.step beside the sidecar and beside the model, both saying the other thing.
    for folder in ("conf", "cad"):
        write_step(tmp_path / folder / "moved.step", screw_facing_wall(on_disk))
    sidecar = tmp_path / "conf" / "wrenchroom.yaml"
    sidecar.write_text(yaml.safe_dump(SIDECAR))
    report = check(
        screw_facing_wall(CLOSE),
        Config.load(sidecar),
        model_dir=tmp_path / "cad",
        models={"moved.step": screw_facing_wall(given)},
    )
    assert verdict(report) == expected


def test_a_file_of_its_name_is_not_read(tmp_path):
    # One that is no STEP file stops a run that reads it, and not one given the model.
    (tmp_path / "moved.step").write_text("not a STEP file\n")
    config = Config.from_dict(SIDECAR)
    with pytest.raises(ValueError, match=r"cannot read .*moved\.step as STEP"):
        check(screw_facing_wall(CLOSE), config, model_dir=tmp_path)
    given = {"moved.step": screw_facing_wall(AWAY)}
    report = check(screw_facing_wall(CLOSE), config, model_dir=tmp_path, models=given)
    assert verdict(report) == (Verdict.TURNS, "lever-up")


def test_the_assembly_given_is_the_one_the_report_keeps():
    # Not a copy, nor one read back: the view draws the state from what was handed over.
    # Any mapping does, one that can't be written to as well.
    given = screw_facing_wall(AWAY)
    models = MappingProxyType({"moved.step": given})
    report = check(screw_facing_wall(CLOSE), Config.from_dict(SIDECAR), models=models)
    assert report.models["lever-up"].assembly is given


TWO_STATES = {
    "fasteners": [M6_SOCKET],
    "states": {"lever-up": {"model": "up.step"}, "lever-out": {"model": "out.step"}},
    "checks": {"try_states": ["lever-up", "lever-out"]},
}


@pytest.mark.parametrize(
    ("on_disk", "name", "given"),
    [(AWAY, "up.step", CLOSE), (CLOSE, "out.step", AWAY)],
    ids=["first-given", "second-given"],
)
def test_a_model_not_given_is_still_read_from_its_file(tmp_path, on_disk, name, given):
    # Both models are on disk, saying one thing; one is given, saying the other. The
    # screw turns in lever-out alone when lever-up's wall is close and lever-out's
    # away: the given model was used for its state, and the other's file for its own.
    for filename in ("up.step", "out.step"):
        write_step(tmp_path / filename, screw_facing_wall(on_disk))
    handed = screw_facing_wall(given)
    models = {name: handed}
    report = check(
        screw_facing_wall(CLOSE), Config.from_dict(TWO_STATES), model_dir=tmp_path, models=models
    )
    assert verdict(report) == (Verdict.TURNS, "lever-out")
    kept = {state: model.assembly is handed for state, model in report.models.items()}
    assert kept == {None: False, "lever-up": name == "up.step", "lever-out": name == "out.step"}
    assert models == {name: handed}  # the caller's mapping is not where a file read is kept


@pytest.mark.parametrize(
    "models",
    [lambda: None, dict, lambda: {"out.step": screw_facing_wall(AWAY)}],
    ids=["none", "empty", "another-s"],
)
def test_a_model_neither_given_nor_found_is_the_error_it_was(tmp_path, models):
    config = Config.from_dict(TWO_STATES, source="w.yaml")
    with pytest.raises(ConfigError) as caught:
        check(screw_facing_wall(CLOSE), config, model_dir=tmp_path, models=models())
    assert str(caught.value) == (
        "state 'lever-up': its model up.step not found "
        f"(w.yaml, states.lever-up.model; looked in {tmp_path})"
    )


def test_with_nowhere_to_look_the_error_says_it_can_be_given():
    with pytest.raises(ConfigError) as caught:
        check(screw_facing_wall(CLOSE), Config.from_dict(SIDECAR))
    assert str(caught.value) == (
        "state 'lever-up': its model 'moved.step' needs a model directory to load from, "
        "or an assembly given for it in models"
    )


def lidded(wall, lid=True):
    """The screw, the wall ``wall`` over its head, and a lid 5 over it, under the wall."""
    over = Pos(0, 0, 26 + 5 + 2) * Box(60, 60, 4)
    return Assembly([*screw_facing_wall(wall), *([Part("lid", over)] if lid else [])])


@pytest.mark.parametrize(
    "second",
    [{"base": "lever-up", "remove": ["lid"]}, {"model": "moved.step", "remove": ["lid"]}],
    ids=["built-on-it", "naming-it-again"],
)
def test_one_model_given_serves_every_state_that_uses_it(second):
    # The wall is away in the model given, and the lid still over the screw: it turns
    # with the lid off, in the state that takes the model from the first or names it too.
    sidecar = {
        "fasteners": [M6_SOCKET],
        "states": {"lever-up": {"model": "moved.step"}, "lever-up-lid-off": second},
        "checks": {"try_states": ["lever-up", "lever-up-lid-off"]},
    }
    given = lidded(AWAY)
    report = check(lidded(CLOSE), Config.from_dict(sidecar), models={"moved.step": given})
    assert verdict(report) == (Verdict.TURNS, "lever-up-lid-off")
    assert report.models["lever-up"].assembly is given
    assert report.models["lever-up-lid-off"].assembly is given
    assert report.models["lever-up-lid-off"].removed == {"lid"}
    assert (report.warnings, report.notes) == ((), ())


def test_a_model_given_that_lacks_the_fastener_is_said_as_a_file_s_is():
    # Issue #74's guards are the given model's too, under the sidecar's name for it.
    renamed = Assembly(
        Part("bolt_renamed" if part.name == "bolt" else part.name, part.shape)
        for part in screw_facing_wall(AWAY)
    )
    report = check(
        screw_facing_wall(CLOSE), Config.from_dict(SIDECAR), models={"moved.step": renamed}
    )
    assert verdict(report) == (Verdict.BLOCKED, None)
    assert report.warnings == (
        "state 'lever-up': its model moved.step has no part bolt (renamed?), "
        "so it wasn't tried there",
    )
    assert report.notes == (
        "state 'lever-up': its model moved.step lacks 1 part of the main model's: bolt; "
        "has 1 part the main model doesn't: bolt_renamed",
    )
    assert report.exit_code == 2


# ---------------------------------------------------------------------------
# What is refused, before anything is checked.
# ---------------------------------------------------------------------------

#: Two states of one model, one built on it, a third's, and a build step's: four names
#: given, three models.
NAMING = {
    "fasteners": [M6_SOCKET],
    "states": {
        "lever-up": {"model": "up.step"},
        "lever-up-lid-off": {"base": "lever-up", "remove": ["wall"]},
        "lever-out": {"model": "out.step"},
        "lever-up-again": {"model": "up.step"},
    },
    "build": [{"step": "all", "add": ["*"], "model": "half.step"}],
}


@pytest.mark.parametrize("run", [check, find_clashes])
@pytest.mark.parametrize(
    ("sidecar", "name", "named"),
    [
        (SIDECAR, "moved.stp", "moved.step"),
        (SIDECAR, "lever-up", "moved.step"),  # the state's name is not its model's
        (SIDECAR, "./moved.step", "moved.step"),  # as the sidecar gives it, to the letter
        (NAMING, "lever-up-lid-off", "up.step, out.step, half.step"),
        ({"fasteners": [M6_SOCKET]}, "moved.step", "none"),
        (None, "moved.step", "none"),
    ],
    ids=["typo", "state-name", "another-spelling", "each-once", "no-models", "no-sidecar"],
)
def test_a_name_the_sidecar_gives_no_model_is_refused(run, sidecar, name, named):
    # The wall is away: the screw turns as given, so no state would ever be tried and
    # the assembly under the wrong name never missed.
    config = None if sidecar is None else Config.from_dict(sidecar)
    with pytest.raises(ValueError, match="unknown model") as caught:
        run(screw_facing_wall(AWAY), config, models={name: screw_facing_wall(AWAY)})
    assert str(caught.value) == (
        f"unknown model {name!r} in models; the sidecar's states and build steps name: {named}"
    )
    assert type(caught.value) is ValueError  # the caller's slip, not the sidecar's


def test_every_name_a_state_or_a_step_gives_may_be_given():
    # A state's, another's, and a build step's, which find_clashes has no use for and
    # takes all the same: one mapping serves both.
    given = {name: screw_facing_wall(AWAY) for name in ("up.step", "out.step", "half.step")}
    report = check(screw_facing_wall(AWAY), Config.from_dict(NAMING), models=given)
    assert verdict(report) == (Verdict.TURNS, None)
    assert built(report) == {"bolt": (Verdict.TURNS, "all", "all")}
    found = find_clashes(screw_facing_wall(AWAY), Config.from_dict(NAMING), models=given)
    assert found.found == ()


def _shapes():
    return [(part.name, part.shape) for part in screw_facing_wall(AWAY)]


@pytest.mark.parametrize("run", [check, find_clashes])
@pytest.mark.parametrize(
    "thing",
    [
        _shapes,
        lambda: Compound(children=[shape for _, shape in _shapes()]),
        lambda: "moved.step",
        lambda: Path("moved.step"),
        lambda: None,
    ],
    ids=["shapes", "compound", "path", "Path", "none"],
)
def test_a_model_that_is_no_assembly_is_refused(run, thing):
    # Whether or not it would ever be read: here the screw turns as given.
    value = thing()
    with pytest.raises(TypeError) as caught:
        run(screw_facing_wall(AWAY), Config.from_dict(SIDECAR), models={"moved.step": value})
    assert str(caught.value) == (
        f"models['moved.step'] must be an Assembly, got {type(value).__name__} "
        "(Assembly.from_shapes makes one of shapes, Assembly.from_step of a file)"
    )
    assert "got list (" in str(caught.value) or thing is not _shapes


# ---------------------------------------------------------------------------
# A build step's model.
# ---------------------------------------------------------------------------

BUILD = {
    "fasteners": [M6_SOCKET],
    "build": [
        {"step": "base", "add": ["wall"]},
        {"step": "screw", "add": ["bolt"], "model": "moved.step"},
    ],
}


def built(report):
    return {p.result.name: (p.result.verdict, p.step, p.checked_in) for p in report.build.placed}


@pytest.mark.parametrize("engine", ENGINES)
def test_a_build_step_s_model_is_taken_as_an_assembly(engine):
    # The wall close over the screw in the model as given; swung away while it goes in.
    report = check(
        screw_facing_wall(CLOSE),
        Config.from_dict(BUILD),
        models={"moved.step": screw_facing_wall(AWAY)},
        engine=engine,
    )
    assert verdict(report) == (Verdict.BLOCKED, None)
    assert built(report) == {"bolt": (Verdict.TURNS, "screw", "screw")}
    assert "  screw  1 fastener: 1 turn, in moved.step" in report.terminal_lines()
    assert report.to_json_dict()["build"]["steps"][1]["model"] == "moved.step"
    assert (report.warnings, report.notes) == ((), ())


def test_a_step_s_model_given_wins_over_its_file_too(tmp_path):
    write_step(tmp_path / "moved.step", screw_facing_wall(AWAY))
    config = Config.from_dict(BUILD)
    by_file = check(screw_facing_wall(CLOSE), config, model_dir=tmp_path)
    assert built(by_file) == {"bolt": (Verdict.TURNS, "screw", "screw")}
    given = {"moved.step": screw_facing_wall(CLOSE)}
    report = check(screw_facing_wall(CLOSE), config, model_dir=tmp_path, models=given)
    assert built(report) == {"bolt": (Verdict.BLOCKED, "screw", "screw")}


def test_one_model_given_serves_a_state_and_a_step():
    sidecar = {**SIDECAR, "build": BUILD["build"]}
    given = screw_facing_wall(AWAY)
    report = check(
        screw_facing_wall(CLOSE), Config.from_dict(sidecar), models={"moved.step": given}
    )
    assert verdict(report) == (Verdict.TURNS, "lever-up")
    assert built(report) == {"bolt": (Verdict.TURNS, "screw", "screw")}


def test_a_step_s_model_given_that_lacks_parts_is_said_as_a_file_s_is():
    half = Assembly([Part("jig", Pos(200, 0, 0) * Box(10, 10, 10))])
    report = check(screw_facing_wall(CLOSE), Config.from_dict(BUILD), models={"moved.step": half})
    (placed,) = report.build.placed
    assert placed.result.verdict is Verdict.NOT_COVERED
    assert placed.result.reason == (
        "not in step 'screw', whose model moved.step has no part of its name (renamed?)"
    )
    assert report.notes == (
        "build step 'screw': its model moved.step lacks 2 parts added by then: bolt, wall; "
        "has 1 part the main model doesn't: jig",
    )


# ---------------------------------------------------------------------------
# Clashes.
# ---------------------------------------------------------------------------

LEVER_UP = {"states": {"lever-up": {"model": "up.step"}}}


def levered(lever_z):
    """A wall whose underside is at z = 20, and a lever 10 tall whose middle is at ``lever_z``."""
    wall = Pos(0, 0, 25) * Box(40, 40, 10)
    return Assembly([Part("wall", wall), Part("lever", Pos(0, 0, lever_z) * Box(4, 4, 10))])


def clashes(result):
    return [(c.first, c.second, round(c.volume, 1), c.state) for c in result.found]


@pytest.mark.parametrize("engine", ENGINES)
def test_find_clashes_takes_a_state_s_model_as_an_assembly(engine):
    # The lever up 1 into the wall, 4 by 4 by 1: 16 mm^3, in the model given alone.
    result = find_clashes(
        levered(5.0), Config.from_dict(LEVER_UP), models={"up.step": levered(16.0)}, engine=engine
    )
    assert clashes(result) == [("lever", "wall", 16.0, "lever-up")]
    assert result.lines()[1] == "CLASH lever into wall  16.0 mm^3  in state lever-up"


def test_find_clashes_uses_the_one_given_whatever_file_is_there(tmp_path):
    write_step(tmp_path / "up.step", levered(16.0))
    config = Config.from_dict(LEVER_UP)
    assert clashes(find_clashes(levered(5.0), config, model_dir=tmp_path)) == [
        ("lever", "wall", 16.0, "lever-up")
    ]
    given = {"up.step": levered(17.0)}  # 2 into the wall
    assert clashes(find_clashes(levered(5.0), config, model_dir=tmp_path, models=given)) == [
        ("lever", "wall", 32.0, "lever-up")
    ]


def test_find_clashes_reads_a_model_not_given_from_its_file(tmp_path):
    with pytest.raises(ConfigError, match=r"state 'lever-up': its model up\.step not found"):
        find_clashes(levered(5.0), Config.from_dict(LEVER_UP), model_dir=tmp_path, models={})


def test_check_looks_for_clashes_in_the_model_given():
    report = check(
        levered(5.0), Config.from_dict(LEVER_UP), models={"up.step": levered(16.0)}, clashes=True
    )
    assert clashes(report.clashes) == [("lever", "wall", 16.0, "lever-up")]
    assert "CLASH lever into wall  16.0 mm^3  in state lever-up" in report.terminal_lines()


# ---------------------------------------------------------------------------
# Given as its file reads, nothing in a report tells the two apart.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("sidecar", [SIDECAR, BUILD], ids=["state", "step"])
def test_given_as_its_file_reads_the_report_is_the_file_s(tmp_path, engine, sidecar):
    main = Assembly.from_step(write_step(tmp_path / "main.step", screw_facing_wall(CLOSE)))
    moved = write_step(tmp_path / "moved.step", screw_facing_wall(AWAY))
    sidecar = sidecar | {"checks": sidecar.get("checks", {}) | {"clashes": True}}
    by_file = check(main, Config.from_dict(sidecar), model_dir=tmp_path, engine=engine)
    given = check(
        main,
        Config.from_dict(sidecar),
        models={"moved.step": Assembly.from_step(moved)},
        engine=engine,
    )
    assert given.to_json_dict() == by_file.to_json_dict()
    assert given.terminal_lines() == by_file.terminal_lines()
    assert given.markdown() == by_file.markdown()
    assert view_data(given) == view_data(by_file)


@pytest.mark.parametrize("engine", ENGINES)
def test_given_as_its_file_reads_the_clashes_are_the_file_s(tmp_path, engine):
    main = Assembly.from_step(write_step(tmp_path / "down.step", levered(5.0)))
    up = write_step(tmp_path / "up.step", levered(16.0))
    config = Config.from_dict(LEVER_UP)
    by_file = find_clashes(main, config, model_dir=tmp_path, engine=engine)
    given = find_clashes(main, config, models={"up.step": Assembly.from_step(up)}, engine=engine)
    assert given.lines() == by_file.lines()
    assert given.to_json() == by_file.to_json()


# ---------------------------------------------------------------------------
# The issue's model: a build script's own shapes, at two positions.
# ---------------------------------------------------------------------------

RAISED = {"states": {"raised": {"model": "raised.step"}}, "checks": {"try_states": ["raised"]}}


def nut_under_a_cup(lift):
    """A plate, an M8 nut and its washer, two solids of one part, and a cup over them.

    No spanner or socket gets on the nut under the cup; ``lift`` raises the cup clear.
    """
    plate = Pos(0, 0, -2.5) * Box(60, 60, 5)
    washer = Pos(0, 0, 0.8) * (Cylinder(8, 1.6) - Cylinder(4.2, 1.6))
    hexagon = extrude(RegularPolygon(13 / 3**0.5, 6), 6.8) - Cylinder(4, 6.8)
    nut = Compound([washer.solids()[0], (Pos(0, 0, 1.65) * hexagon).solids()[0]])
    cup = Pos(0, 0, 7 + lift) * (Cylinder(15, 14) - Pos(0, 0, -1) * Cylinder(12, 12))
    return [("plate", plate), ("M8 nut", nut), ("arm", cup)]


def test_a_script_s_own_shapes_are_checked_in_each_state_with_no_step_file(tmp_path):
    main = Assembly.from_shapes(nut_under_a_cup(0))
    raised = Assembly.from_shapes(nut_under_a_cup(20))
    # The part of two solids is one part in both: nothing differs by name.
    assert main.names == raised.names == ("plate", "M8 nut", "arm")
    (alone,) = check(main).results
    assert (alone.verdict, alone.blocked_by) == (Verdict.BLOCKED, ("arm",))

    report = check(main, Config.from_dict(RAISED), models={"raised.step": raised})
    (nut,) = report.results
    assert (nut.name, nut.verdict, nut.state, nut.tool) == (
        "M8 nut",
        Verdict.TURNS,
        "raised",
        "spanner-13",
    )
    assert (report.warnings, report.notes, report.exit_code) == ((), (), 0)
    # The round trip the script was put to before: the same part comes back as two.
    read_back = Assembly.from_step(write_step(tmp_path / "raised.step", raised))
    assert read_back.names == ("plate", "M8 nut", "M8 nut#2", "arm")


def test_the_tools_list_and_the_view_have_the_state_given():
    # What tools --used prints, and the page: both read the report, and the report
    # the model handed over.
    raised = Assembly.from_shapes(nut_under_a_cup(20))
    report = check(
        Assembly.from_shapes(nut_under_a_cup(0)),
        Config.from_dict(RAISED),
        models={"raised.step": raised},
    )
    (tool,) = report.tools_used().to_json()["tools"]
    assert (tool["tool"], tool["fasteners"], tool["states"]) == (
        "spanner-13",
        ["M8 nut"],
        ["raised"],
    )
    data = view_data(report)
    (entry,) = data["fasteners"]
    view = data["views"][entry["view"]]
    assert (entry["name"], view["state"]) == ("M8 nut", "raised")
    (cup,) = [data["parts"][i] for i in view["parts"] if data["parts"][i]["name"] == "arm"]
    drawn = base64.b64decode(data["shapes"][cup["shape"]]["p"])
    points = np.frombuffer(drawn, "<f4").reshape(-1, 3)
    assert points[:, 2].min() == pytest.approx(20.0, abs=1e-4)  # the cup's rim, raised 20
