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


def test_check_only_mismatch_fails_saying_so(exported):
    # Issue #20: it used to check nothing and exit 0.
    result = CliRunner().invoke(main, ["check", str(exported), "--only", "nothing_*"])
    assert result.exit_code == EXIT_NOT_COVERED
    assert "0 fasteners" in result.output
    assert "WARN only glob 'nothing_*' matched no fastener (renamed part?)" in result.output


def test_check_only_that_matches_checks_just_those(exported):
    result = CliRunner().invoke(main, ["check", str(exported), "--only", "bo*"])
    assert result.exit_code == 1  # the bolt, blocked
    assert "1 fasteners" in result.output
    assert "WARN" not in result.output


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


# ---------------------------------------------------------------------------
# A report's FILE may be -, for stdout, so it can be piped (issue #21).
# ---------------------------------------------------------------------------

REPORTS = [("--json", "r.json"), ("--md", "r.md"), ("--html", "r.html")]


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    """Run from tmp_path, where a stray file named - would land."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _check(*args):
    return CliRunner().invoke(main, ["check", *map(str, args)])


@pytest.mark.parametrize(("option", "file"), REPORTS)
def test_a_dash_sends_the_report_to_stdout_byte_for_byte_as_its_file(
    exported, in_tmp, option, file
):
    to_file = _check(exported, option, file)
    to_stdout = _check(exported, option, "-")
    assert to_stdout.exit_code == to_file.exit_code == 1
    assert to_stdout.stdout_bytes == (in_tmp / file).read_bytes()
    assert not (in_tmp / "-").exists()  # issue #21: it used to be written here
    # The table moved to stderr, out of the pipe's way, word for word.
    assert to_file.stderr == ""
    assert to_stdout.stderr == to_file.stdout
    assert "FAIL bolt  hex-key-5  blocked  wall" in to_stdout.stderr


def test_json_on_stdout_pipes_into_a_reader(exported, in_tmp):
    result = _check(exported, "--json", "-")
    report = json.loads(result.stdout)  # as `--json - | jq` would read it
    assert report["summary"]["blocked"] == 1
    assert report["fasteners"][0]["blocked_by"] == ["wall"]


def test_with_one_report_on_stdout_the_others_still_go_to_their_files(exported, in_tmp):
    result = _check(exported, "--json", "-", "--md", "r.md", "--html", "r.html")
    assert result.exit_code == 1
    assert json.loads(result.stdout)["summary"]["blocked"] == 1
    assert (in_tmp / "r.md").read_text().startswith("### wrenchroom: `model.step`\n")
    assert (in_tmp / "r.html").read_text().startswith("<!doctype html>\n")
    assert "1 fasteners" in result.stderr


@pytest.mark.parametrize(
    "dashed",
    [("--json", "--md"), ("--json", "--html"), ("--md", "--html"), ("--json", "--md", "--html")],
)
def test_only_one_report_can_go_to_stdout(exported, in_tmp, dashed):
    result = _check(exported, *(arg for option in dashed for arg in (option, "-")))
    assert result.exit_code == EXIT_NOT_COVERED
    message = f"only one report can go to stdout (-), not {len(dashed)}: {', '.join(dashed)}"
    assert message in result.stderr
    assert result.stdout == ""
    assert "fasteners" not in result.output  # refused before any check ran
    assert not (in_tmp / "-").exists()


def test_a_dash_is_stdout_even_beside_a_directory_named_dash(exported, in_tmp):
    (in_tmp / "-").mkdir()  # as a path, - would be refused: it's a directory
    result = _check(exported, "--json", "-")
    assert result.exit_code == 1
    assert json.loads(result.stdout)["summary"]["blocked"] == 1


def test_a_file_really_named_dash_is_dot_slash_dash(exported, in_tmp):
    result = _check(exported, "--md", "./-")
    assert result.exit_code == 1
    assert (in_tmp / "-").read_text().startswith("### wrenchroom: `model.step`\n")
    assert "1 fasteners" in result.stdout  # nothing went to stdout, so the table stays
    assert result.stderr == ""


def test_a_report_goes_out_as_utf_8_as_its_file_does(exported, in_tmp, monkeypatch):
    # A name in the Markdown keeps its accents and CJK; build123d 0.13 can't put
    # one in a STEP file, so the report is given one here.
    from wrenchroom.report import Report  # noqa: PLC0415

    markdown = Report.markdown
    monkeypatch.setattr(Report, "markdown", lambda self: markdown(self) + "- `螺丝 é`\n")
    to_file = _check(exported, "--md", "r.md")
    to_stdout = _check(exported, "--md", "-")
    assert to_file.exit_code == to_stdout.exit_code == 1
    assert "- `螺丝 é`\n".encode() in to_stdout.stdout_bytes
    assert to_stdout.stdout_bytes == (in_tmp / "r.md").read_bytes()


def test_explain_html_dash_sends_the_view_to_stdout_and_the_story_to_stderr(exported, in_tmp):
    to_file = CliRunner().invoke(main, ["explain", str(exported), "bolt", "--html", "bolt.html"])
    to_stdout = CliRunner().invoke(main, ["explain", str(exported), "bolt", "--html", "-"])
    assert to_stdout.exit_code == to_file.exit_code == 1
    assert to_stdout.stdout_bytes == (in_tmp / "bolt.html").read_bytes()
    assert not (in_tmp / "-").exists()
    assert to_file.stderr == ""
    assert to_stdout.stderr == to_file.stdout
    assert "tried hex-key-5, driver straight in: blocked" in to_stdout.stderr


def test_explain_without_a_dash_keeps_its_story_on_stdout(exported, in_tmp):
    result = CliRunner().invoke(main, ["explain", str(exported), "bolt"])
    assert result.stderr == ""
    assert result.stdout.splitlines()[0].startswith("bolt: blocked")


def test_help_names_file_and_dash_for_every_report():
    for command, options in (("check", ("--json", "--md", "--html")), ("explain", ("--html",))):
        text = " ".join(CliRunner().invoke(main, [command, "--help"]).output.split())
        for option in options:
            assert f"{option} FILE" in text
        assert text.count("- for stdout") == len(options)
