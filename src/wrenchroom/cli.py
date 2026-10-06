"""The command line interface.

The four commands exist from day one so the entry point, the exit-code contract and the
help text are testable before any of them work. Each stub exits 2, the code for
"something not covered": a command that does not exist yet is the clearest possible case
of not covered.

Exit codes, fixed: 0 every fastener passes, 1 a fastener fails, 2 something not covered
or a config error.
"""

from __future__ import annotations

import sys
from typing import NoReturn

import click

from wrenchroom import __version__

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
@click.argument("model")
def check(model: str) -> None:
    """Check every fastener in MODEL and report the verdicts."""
    _not_built("check")


@main.command()
@click.argument("model")
def detect(model: str) -> None:
    """Write what was found in MODEL as a sidecar YAML, for correcting and keeping."""
    _not_built("detect")


@main.command()
@click.argument("model")
@click.argument("fastener")
def explain(model: str, fastener: str) -> None:
    """Show every attempt for one FASTENER in MODEL, with the blockers."""
    _not_built("explain")


@main.command()
@click.option("--kit", default="metric-home", show_default=True, help="Which tool kit.")
def tools(kit: str) -> None:
    """List the kit's tools and their dimensions."""
    _not_built("tools")
