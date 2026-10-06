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


def test_every_command_is_built():
    for command in ("check", "detect", "explain", "tools"):
        result = CliRunner().invoke(main, [command, "--help"])
        assert result.exit_code == 0
        assert "not built" not in result.output


def test_tools_lists_the_kit_with_its_caveats():
    result = CliRunner().invoke(main, ["tools"])
    assert result.exit_code == 0
    assert "hex-key-5" in result.output
    assert "long arm 85" in result.output  # the ISO 2936 row, not the old provisional one
    assert "spanner-10" in result.output
    assert "socket-19" in result.output  # metric-home's largest (tests/test_kits.py)
    assert "driver-ph2" in result.output
    assert "approximate" in result.output  # the caveat travels with the numbers


def test_tools_unknown_kit_exits_2():
    result = CliRunner().invoke(main, ["tools", "--kit", "mars"])
    assert result.exit_code == EXIT_NOT_COVERED


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
    (tmp_path / "wrenchroom.yaml").write_text("states:\n  open:\n    base: missing\n")
    result = CliRunner().invoke(main, ["check", str(exported)])
    assert result.exit_code == EXIT_NOT_COVERED
    assert "is not a state" in result.output


def test_check_unknown_kit_exits_2(exported):
    result = CliRunner().invoke(main, ["check", str(exported), "--kit", "mars"])
    assert result.exit_code == EXIT_NOT_COVERED
    assert "unknown kit" in result.output


def test_explain_prints_every_attempt(exported):
    result = CliRunner().invoke(main, ["explain", str(exported), "bolt"])
    assert result.exit_code == 1  # the bolt is blocked, and explain says so
    assert "bolt: blocked" in result.output
    assert "tried hex-key-5, driver straight in: blocked" in result.output
    assert "tried hex-key-5, short leg in: blocked" in result.output
    assert "hit wall" in result.output


def test_explain_unknown_fastener_exits_2(exported):
    result = CliRunner().invoke(main, ["explain", str(exported), "ghost"])
    assert result.exit_code == EXIT_NOT_COVERED
    assert "no fastener named" in result.output


# ---------------------------------------------------------------------------
# --exact: the referee engine, same contract.
# ---------------------------------------------------------------------------


def test_check_and_explain_offer_exact():
    for command in ("check", "explain"):
        result = CliRunner().invoke(main, [command, "--help"])
        assert "--exact" in result.output


def test_check_exact_gives_the_same_report_by_the_other_engine(exported, tmp_path):
    runs = {}
    for engine, flags in (("mesh", []), ("exact", ["--exact"])):
        json_path = tmp_path / f"{engine}.json"
        result = CliRunner().invoke(
            main, ["check", str(exported), *flags, "--json", str(json_path)]
        )
        runs[engine] = (result, json.loads(json_path.read_text()))
    (mesh, mesh_doc), (exact, exact_doc) = runs["mesh"], runs["exact"]
    assert mesh.exit_code == exact.exit_code == 1
    assert mesh.output == exact.output
    assert mesh_doc.pop("engine") == "mesh"
    assert exact_doc.pop("engine") == "exact"
    assert mesh_doc == exact_doc


def test_explain_exact_tells_the_same_story(exported):
    default = CliRunner().invoke(main, ["explain", str(exported), "bolt"])
    exact = CliRunner().invoke(main, ["explain", str(exported), "bolt", "--exact"])
    assert exact.exit_code == default.exit_code == 1
    assert exact.output == default.output


def test_check_and_explain_find_fasteners_with_no_sidecar(tmp_path):
    assembly = screw_facing_wall(15.0)
    shapes = []
    for part in assembly:
        part.shape.label = part.name
        shapes.append(part.shape)
    model = tmp_path / "model.step"
    export_step(Compound(children=shapes), str(model))
    checked = CliRunner().invoke(main, ["check", str(model)])
    assert checked.exit_code == 1
    assert "FAIL bolt" in checked.output
    explained = CliRunner().invoke(main, ["explain", str(model), "bolt"])
    assert "found by name" in explained.output
    assert "noun 'bolt'" in explained.output
