"""The command line interface.

The four commands exist from day one so the entry point, the exit-code contract and the
help text are testable before all of them work. A command not yet delivered exits 2,
the code for "something not covered".

Exit codes, fixed: 0 every fastener passes, 1 a fastener fails, 2 something not covered
or a config error.

The heavy imports (build123d pulls OCP, seconds) happen inside the commands that need
them, so `--help` and `--version` stay instant.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import click

from wrenchroom import __version__

if TYPE_CHECKING:
    from wrenchroom.report import Report

#: Exit code for "not covered or a config error".
EXIT_NOT_COVERED = 2


def _not_built(command: str) -> NoReturn:
    """Exit with the not-covered code: the command is promised but not delivered yet."""
    click.echo(f"wrenchroom {command} is not built yet.", err=True)
    sys.exit(EXIT_NOT_COVERED)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="wrenchroom")
def main() -> None:
    """Check that a real hand tool can reach, turn and remove every fastener."""


@main.command()
@click.argument("model", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Sidecar YAML; default: wrenchroom.yaml beside the model, if present.",
)
@click.option("--kit", default="metric-home", show_default=True, help="Which tool kit.")
@click.option(
    "--json",
    "json_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Also write the machine-readable report here.",
)
@click.option("--step-deg", default=15.0, show_default=True, help="Swing sampling step.")
@click.option("--only", help="Check only fasteners whose name matches this glob.")
@click.option("--state", help="Check in this state instead of the config's default.")
def check(
    model: Path,
    config_path: Path | None,
    kit: str,
    json_path: Path | None,
    step_deg: float,
    only: str | None,
    state: str | None,
) -> None:
    """Check every fastener in MODEL and report the verdicts."""
    report = _run(model, config_path, kit=kit, step_deg=step_deg, only=only, state=state)
    for line in report.terminal_lines():
        click.echo(line)
    if json_path is not None:
        report.to_json(json_path)
    sys.exit(report.exit_code)


def _run(
    model: Path,
    config_path: Path | None,
    *,
    kit: str = "metric-home",
    step_deg: float = 15.0,
    only: str | None = None,
    state: str | None = None,
) -> Report:
    """Load, check, and turn config mistakes into exit 2; shared by check and explain."""
    from wrenchroom.assembly import Assembly
    from wrenchroom.check import check as run_check
    from wrenchroom.config import Config, ConfigError

    if config_path is None:
        beside = model.parent / "wrenchroom.yaml"
        config_path = beside if beside.exists() else None
    try:
        config = Config.load(config_path) if config_path else None
        return run_check(
            Assembly.from_step(model),
            config,
            kit=kit,
            step_deg=step_deg,
            model=model.name,
            only=only,
            state=state,
            model_dir=model.parent,
        )
    except (ConfigError, ValueError) as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(EXIT_NOT_COVERED)


@main.command()
@click.argument("model")
def detect(model: str) -> None:
    """Write what was found in MODEL as a sidecar YAML, for correcting and keeping."""
    _not_built("detect")


@main.command()
@click.argument("model", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("fastener")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Sidecar YAML; default: wrenchroom.yaml beside the model, if present.",
)
@click.option("--kit", default="metric-home", show_default=True, help="Which tool kit.")
@click.option("--step-deg", default=15.0, show_default=True, help="Swing sampling step.")
def explain(
    model: Path, fastener: str, config_path: Path | None, kit: str, step_deg: float
) -> None:
    """Show every attempt for one FASTENER in MODEL, with the blockers."""
    report = _run(model, config_path, kit=kit, step_deg=step_deg, only=fastener)
    if not report.results:
        click.echo(f"error: no fastener named {fastener!r} (is it in the sidecar?)", err=True)
        sys.exit(EXIT_NOT_COVERED)
    (result,) = report.results
    header = f"{result.fastener.name}: {result.verdict}"
    if result.tool:
        header += f" with {result.tool}" + (f", {result.how}" if result.how else "")
    if result.state:
        header += f" (in state {result.state})"
    if result.pair:
        header += f"; paired with {result.pair}"
    click.echo(header)
    if result.reason:
        click.echo(f"  reason: {result.reason}")
    for attempt in result.attempts:
        outcome = "turns" if attempt.turns else ("holds" if attempt.holds else "blocked")
        line = f"  tried {attempt.tool}, {attempt.way}: {outcome}"
        if attempt.swing_deg and not attempt.turns:
            line += f", swing {attempt.swing_deg:g} deg"
        if attempt.blockers:
            line += f"; hit {', '.join(attempt.blockers)}"
        click.echo(line)
    if result.stuck_on:
        click.echo(f"  cannot come out: {', '.join(result.stuck_on)} in the way")
    sys.exit(report.exit_code)


@main.command()
@click.option("--kit", default="metric-home", show_default=True, help="Which tool kit.")
def tools(kit: str) -> None:
    """List the kit's tools and their dimensions."""
    _not_built("tools")
