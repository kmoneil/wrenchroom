"""The CLI's contract from day one: the commands exist, the exit codes mean something."""

import pytest
from click.testing import CliRunner

import wrenchroom
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
        ["check", "model.step"],
        ["detect", "model.step"],
        ["explain", "model.step", "lift_link_0_bolt_top"],
        ["tools"],
    ],
    ids=["check", "detect", "explain", "tools"],
)
def test_unbuilt_commands_exit_not_covered(argv):
    result = CliRunner().invoke(main, argv)
    assert result.exit_code == EXIT_NOT_COVERED
    assert "not built yet" in result.output
