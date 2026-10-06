"""The CLI's contract from day one: the commands exist, the exit codes mean something."""

import json

import pytest
from build123d import Compound, export_step
from click.testing import CliRunner

import wrenchroom
from fixture_models import screw_facing_wall
from wrenchroom.cli import EXIT_NOT_COVERED, main


def test_help_lists_every_spec_command():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for command in ("check", "detect", "explain", "tools"):
        assert command in result.output


def test_version_reports_the_package_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert wrenchroom.__version__ in result.output


@pytest.mark.parametrize(
    "argv",
    [
        ["detect", "model.step"],
        ["explain", "model.step", "lift_link_0_bolt_top"],
        ["tools"],
    ],
    ids=["detect", "explain", "tools"],
)
def test_unbuilt_commands_exit_not_covered(argv):
    result = CliRunner().invoke(main, argv)
    assert result.exit_code == EXIT_NOT_COVERED
    assert "not built yet" in result.output


# ---------------------------------------------------------------------------
# `check` end to end, against a real STEP file and sidecar on disk.
# ---------------------------------------------------------------------------

SIDECAR = """
fasteners:
  - parts: bolt
    kind: screw
    head: socket
    size: M6
"""


@pytest.fixture
def exported(tmp_path):
    """The close-wall case (blocked) as model.step + wrenchroom.yaml."""
    assembly = screw_facing_wall(15.0)
    shapes = []
    for part in assembly:
        part.shape.label = part.name
        shapes.append(part.shape)
    compound = Compound(children=shapes)
    model = tmp_path / "model.step"
    export_step(compound, str(model))
    (tmp_path / "wrenchroom.yaml").write_text(SIDECAR)
    return model


def test_check_reports_the_blocked_bolt_and_exits_1(exported, tmp_path):
    json_path = tmp_path / "report.json"
    result = CliRunner().invoke(main, ["check", str(exported), "--json", str(json_path)])
    assert result.exit_code == 1
    assert "1 fasteners: 0 turn" in result.output
    assert "FAIL bolt  hex-key-5  blocked  wall" in result.output
    report = json.loads(json_path.read_text())
    assert report["summary"]["blocked"] == 1
    assert report["fasteners"][0]["blocked_by"] == ["wall"]


def test_check_only_mismatch_passes_empty(exported):
    result = CliRunner().invoke(main, ["check", str(exported), "--only", "nothing_*"])
    assert result.exit_code == 0
    assert "0 fasteners" in result.output


def test_check_bad_config_exits_2(exported, tmp_path):
    (tmp_path / "wrenchroom.yaml").write_text("states: {}\n")
    result = CliRunner().invoke(main, ["check", str(exported)])
    assert result.exit_code == EXIT_NOT_COVERED
    assert "arrives with M2" in result.output


def test_check_unknown_kit_exits_2(exported):
    result = CliRunner().invoke(main, ["check", str(exported), "--kit", "mars"])
    assert result.exit_code == EXIT_NOT_COVERED
    assert "unknown kit" in result.output
