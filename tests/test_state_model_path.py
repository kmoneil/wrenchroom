"""A state's model: is found beside the sidecar, then beside the model (issue #73).

A state's ``model:`` was looked for only in the main model's folder, so a sidecar
kept elsewhere (``--config conf/wrenchroom.yaml``) with its state model beside it
failed with "cannot read cad/moved.step as STEP": not unreadable, not there. A path
in a config file reads as one beside the file, so it is looked for there first, then
beside the model, as before. One found nowhere says so, naming the sidecar entry and
where it looked; one found and not readable says that instead.
"""

import os
from pathlib import Path

import pytest
import yaml
from build123d import Compound, export_step
from click.testing import CliRunner

from fixture_models import screw_facing_wall
from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config, ConfigError
from wrenchroom.report import Verdict

M6_SOCKET = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}
SIDECAR = {
    "fasteners": [M6_SOCKET],
    "states": {"lever-up": {"model": "moved.step"}},
    "checks": {"try_states": ["lever-up"]},
}


def write_step(path, assembly):
    shapes = []
    for part in assembly:
        part.shape.label = part.name
        shapes.append(part.shape)
    path.parent.mkdir(parents=True, exist_ok=True)
    export_step(Compound(children=shapes), str(path))


def layout(root, moved_in=("conf",), sidecar=SIDECAR):
    """cad/main.step (the screw under a wall 15 over it), conf/wrenchroom.yaml, and
    a lever-up model (the wall 300 over) in each folder of ``moved_in``."""
    write_step(root / "cad" / "main.step", screw_facing_wall(15.0))
    (root / "conf").mkdir(exist_ok=True)
    (root / "conf" / "wrenchroom.yaml").write_text(yaml.safe_dump(sidecar))
    for folder in moved_in:
        write_step(root / folder / "moved.step", screw_facing_wall(300.0))
    return root / "cad" / "main.step", root / "conf" / "wrenchroom.yaml"


def run(model, sidecar, **kwargs):
    config = Config.load(sidecar)
    return check(Assembly.from_step(model), config, **kwargs)


def test_beside_the_sidecar_is_found_first(tmp_path):
    # The issue's case: the model in cad/, the sidecar and its state model in conf/.
    model, sidecar = layout(tmp_path, moved_in=("conf",))
    (result,) = run(model, sidecar, model_dir=model.parent).results
    assert (result.verdict, result.state) == (Verdict.TURNS, "lever-up")


def test_beside_the_model_is_still_found(tmp_path):
    model, sidecar = layout(tmp_path, moved_in=("cad",))
    (result,) = run(model, sidecar, model_dir=model.parent).results
    assert (result.verdict, result.state) == (Verdict.TURNS, "lever-up")


def test_where_both_have_one_the_sidecar_s_is_used(tmp_path):
    # conf/moved.step has the wall away; cad/moved.step keeps it close. The screw
    # turning in lever-up shows conf's was read.
    model, sidecar = layout(tmp_path, moved_in=("conf",))
    write_step(tmp_path / "cad" / "moved.step", screw_facing_wall(15.0))
    (result,) = run(model, sidecar, model_dir=model.parent).results
    assert (result.verdict, result.state) == (Verdict.TURNS, "lever-up")


def test_from_python_the_loaded_sidecar_says_where_to_look(tmp_path):
    # No model_dir: Config.load knows where the sidecar was, and that is enough.
    model, sidecar = layout(tmp_path, moved_in=("conf",))
    (result,) = run(model, sidecar).results
    assert result.verdict is Verdict.TURNS
    assert Config.load(sidecar).directory == sidecar.parent
    assert Config.from_dict(SIDECAR).directory is None


def test_a_sidecar_from_a_mapping_still_needs_a_model_directory(tmp_path):
    model, _ = layout(tmp_path, moved_in=("cad",))
    with pytest.raises(ConfigError, match="needs a model directory to load from"):
        check(Assembly.from_step(model), Config.from_dict(SIDECAR))


def test_a_missing_model_says_so_and_where_it_looked(tmp_path):
    model, sidecar = layout(tmp_path, moved_in=())
    with pytest.raises(ConfigError) as caught:
        run(model, sidecar, model_dir=model.parent)
    assert str(caught.value) == (
        f"state 'lever-up': its model moved.step not found ({sidecar}, "
        f"states.lever-up.model; looked in {sidecar.parent}, {model.parent})"
    )


def test_a_state_built_on_another_names_the_one_whose_model_it_is(tmp_path):
    states = {
        "lever-up": {"model": "moved.step"},
        "lever-up-lid-off": {"base": "lever-up", "remove": ["wall"]},
    }
    sidecar = {**SIDECAR, "states": states, "checks": {"try_states": ["lever-up-lid-off"]}}
    model, path = layout(tmp_path, moved_in=(), sidecar=sidecar)
    with pytest.raises(ConfigError, match=r"states\.lever-up\.model;"):
        run(model, path, model_dir=model.parent)


def test_a_file_there_but_not_step_says_that(tmp_path):
    model, sidecar = layout(tmp_path, moved_in=())
    (tmp_path / "conf" / "moved.step").write_text("not a STEP file\n")
    with pytest.raises(ValueError, match=r"cannot read .*moved\.step as STEP"):
        run(model, sidecar, model_dir=model.parent)


def test_an_absolute_path_is_taken_as_it_is(tmp_path):
    elsewhere = tmp_path / "exports" / "moved.step"
    write_step(elsewhere, screw_facing_wall(300.0))
    sidecar = {**SIDECAR, "states": {"lever-up": {"model": str(elsewhere)}}}
    model, path = layout(tmp_path, moved_in=(), sidecar=sidecar)
    (result,) = run(model, path, model_dir=model.parent).results
    assert result.verdict is Verdict.TURNS


def test_an_absolute_path_needs_no_folder_at_all(tmp_path):
    # A sidecar from a mapping has no folder, and no model_dir is given: an absolute
    # model path is still found.
    elsewhere = tmp_path / "exports" / "moved.step"
    write_step(elsewhere, screw_facing_wall(300.0))
    config = Config.from_dict({**SIDECAR, "states": {"lever-up": {"model": str(elsewhere)}}})
    (result,) = check(screw_facing_wall(15.0), config).results
    assert (result.verdict, result.state) == (Verdict.TURNS, "lever-up")


def test_one_folder_is_said_once(tmp_path):
    # The sidecar beside the model: one folder to look in, said once.
    write_step(tmp_path / "main.step", screw_facing_wall(15.0))
    (tmp_path / "wrenchroom.yaml").write_text(yaml.safe_dump(SIDECAR))
    with pytest.raises(ConfigError) as caught:
        run(tmp_path / "main.step", tmp_path / "wrenchroom.yaml", model_dir=tmp_path)
    assert str(caught.value).endswith(f"looked in {tmp_path})")


def test_the_command_line_reads_the_issue_s_layout_and_names_a_missing_model(tmp_path):
    layout(tmp_path, moved_in=("conf",))
    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        ok = CliRunner().invoke(
            main, ["check", "cad/main.step", "--config", "conf/wrenchroom.yaml"]
        )
        assert ok.exit_code == 0, ok.output
        (tmp_path / "conf" / "moved.step").unlink()
        missing = CliRunner().invoke(
            main, ["check", "cad/main.step", "--config", "conf/wrenchroom.yaml"]
        )
    finally:
        os.chdir(cwd)
    assert missing.exit_code == 2
    assert missing.output.strip() == (
        "error: state 'lever-up': its model moved.step not found (conf/wrenchroom.yaml, "
        "states.lever-up.model; looked in conf, cad)"
    )
