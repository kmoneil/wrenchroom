"""The command line interface.

Four commands: check, explain, detect (writes the sidecar) and tools.

Exit codes, fixed: 0 every fastener passes, 1 a fastener fails, 2 something not covered
or a config error.

The heavy imports (build123d pulls OCP, seconds) happen inside the commands that need
them, so `--help` and `--version` stay instant.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from wrenchroom import __version__
from wrenchroom.terminal import printable

if TYPE_CHECKING:
    from wrenchroom.report import Report

#: Exit code for "not covered or a config error".
EXIT_NOT_COVERED = 2

_HAND_ROOM_HELP = (
    "Also check room for a hand on each handle (as `checks: {hand_room: true}`); "
    "untuned, so off by default."
)


def _say(text: str = "", *, err: bool = False) -> None:
    """Print one line for a person: the only way text reaches the terminal here.

    Part names come from the model, and a model can come from anybody, so every
    line goes through :func:`wrenchroom.terminal.printable` and nothing in it can
    steer the terminal. A blank line is its own call, never a newline inside one.
    """
    click.echo(printable(text), err=err)


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
@click.option(
    "--md",
    "md_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Also write the report as Markdown here, for a CI summary or a PR comment.",
)
@click.option(
    "--html",
    "html_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Also write the 3D view here: one self-contained file to open in a browser.",
)
@click.option("--step-deg", default=15.0, show_default=True, help="Swing sampling step.")
@click.option("--only", help="Check only fasteners whose name matches this glob.")
@click.option("--state", help="Check in this state instead of the config's default.")
@click.option(
    "--exact",
    is_flag=True,
    help="Use the exact OCP boolean engine: slow, the referee for borderline results.",
)
@click.option("--hand-room", is_flag=True, default=None, help=_HAND_ROOM_HELP)
def check(  # noqa: PLR0913, PLR0917  (Click passes one parameter per option)
    model: Path,
    config_path: Path | None,
    kit: str,
    json_path: Path | None,
    md_path: Path | None,
    html_path: Path | None,
    step_deg: float,
    only: str | None,
    state: str | None,
    exact: bool,
    hand_room: bool | None,
) -> None:
    """Check every fastener in MODEL and report the verdicts."""
    report = _run(
        model,
        config_path,
        kit=kit,
        step_deg=step_deg,
        only=only,
        state=state,
        exact=exact,
        hand_room=hand_room,
    )
    for line in report.terminal_lines():
        _say(line)
    if json_path is not None:
        report.to_json(json_path)
    if md_path is not None:
        report.to_markdown(md_path)
    if html_path is not None:
        report.to_html(html_path)
    sys.exit(report.exit_code)


def _run(
    model: Path,
    config_path: Path | None,
    *,
    kit: str = "metric-home",
    step_deg: float = 15.0,
    only: str | None = None,
    state: str | None = None,
    exact: bool = False,
    hand_room: bool | None = None,
) -> Report:
    """Load, check, and turn config mistakes into exit 2; shared by check and explain."""
    from wrenchroom.assembly import Assembly
    from wrenchroom.checker import check as run_check
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
            engine="exact" if exact else "mesh",
            hand_room=hand_room,
        )
    except (ConfigError, ValueError) as exc:
        _say(f"error: {exc}", err=True)
        sys.exit(EXIT_NOT_COVERED)


@main.command()
@click.argument("model", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--kit", default="metric-home", show_default=True, help="Which tool kit.")
def detect(model: Path, kit: str) -> None:
    """Write the fasteners found in MODEL as a sidecar YAML, for correcting and keeping.

    Fasteners are found by their part names and solids, as check finds them; a
    wrenchroom.yaml beside the model is not read. Each rule's comment says how sure
    detection was, what found the part, its axis and how it fares now. Redirect
    the output to wrenchroom.yaml, correct it, and keep it.
    """
    from wrenchroom.assembly import Assembly
    from wrenchroom.checker import check as run_check
    from wrenchroom.config import Config
    from wrenchroom.detect.sidecar import sidecar_text

    try:
        assembly = Assembly.from_step(model)
        report = run_check(assembly, Config(), kit=kit, model=model.name, model_dir=model.parent)
    except ValueError as exc:
        _say(f"error: {exc}", err=True)
        sys.exit(EXIT_NOT_COVERED)
    for line in sidecar_text(report, model.name).splitlines():
        _say(line)
    counts = report.summary
    _say(f"found {counts['fasteners']} fasteners, {counts['not_covered']} not covered", err=True)


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
@click.option(
    "--exact",
    is_flag=True,
    help="Use the exact OCP boolean engine: slow, the referee for borderline results.",
)
@click.option(
    "--html",
    "html_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Also write the 3D view here, opening on this fastener's attempts.",
)
@click.option("--hand-room", is_flag=True, default=None, help=_HAND_ROOM_HELP)
def explain(
    model: Path,
    fastener: str,
    config_path: Path | None,
    kit: str,
    step_deg: float,
    exact: bool,
    html_path: Path | None,
    hand_room: bool | None,
) -> None:
    """Show every attempt for one FASTENER in MODEL, with the blockers."""
    from wrenchroom.report import attempt_text

    report = _run(
        model,
        config_path,
        kit=kit,
        step_deg=step_deg,
        only=fastener,
        exact=exact,
        hand_room=hand_room,
    )
    if not report.results:
        _say(f"error: no fastener named {fastener!r} (is it in the sidecar?)", err=True)
        sys.exit(EXIT_NOT_COVERED)
    (result,) = report.results
    if html_path is not None:
        report.to_html(html_path, select=result.fastener.name)
    _say(result.headline)
    if result.fastener.source != "sidecar":
        _say(f"  found by {result.fastener.source}: {result.fastener.basis}")
    if result.reason:
        _say(f"  reason: {result.reason}")
    for attempt in result.attempts:
        _say(f"  tried {attempt_text(attempt)}")
    if result.stuck_on:
        _say(f"  cannot come out: {', '.join(result.stuck_on)} in the way")
    sys.exit(report.exit_code)


@main.command()
@click.option("--kit", default="metric-home", show_default=True, help="Which tool kit.")
def tools(kit: str) -> None:
    """List the kit's tools and their dimensions, citations and approximations.

    Exactly the tools a check with this kit tries, from the same tables the
    sweeps read: a fastener needing anything not listed is not covered.
    """
    from wrenchroom.tools.drivers import SHAFT_RADIUS
    from wrenchroom.tools.hex_keys import ISO_2936
    from wrenchroom.tools.kits import kit_named
    from wrenchroom.tools.sockets import EXTENSION_LENGTHS, socket_for
    from wrenchroom.tools.spanners import spanner_for

    try:
        chosen = kit_named(kit)
    except ValueError as exc:
        _say(f"error: {exc}", err=True)
        sys.exit(EXIT_NOT_COVERED)
    _say(f"kit {chosen.name}: {chosen.summary}")
    _say()
    _say("hex keys (DIN ISO 2936:2016-10; all mm):")
    for key in (ISO_2936[af] for af in chosen.hex_keys):
        _say(
            f"  hex-key-{key.af:<6g} across flats {key.af:<5g} "
            f"long arm {key.long_mm:<6g} short arm {key.short_mm:g}"
        )
    _say()
    _say("ring spanners, full and stubby (approximate until DIN 3113 is read out):")
    for af in chosen.spanners:
        spanner = spanner_for(af)
        _say(
            f"  spanner-{spanner.af:<7g} length {spanner.length:<6g} "
            f"ring outer r {spanner.ring_outer_radius:<5g} stubby {spanner.stubby_length:g}"
        )
    extensions = "/".join(f"{e:g}" for e in EXTENSION_LENGTHS)
    _say()
    _say(f"sockets on a 72-tooth ratchet, extensions {extensions} mm (approximate until DIN 3124):")
    for af in chosen.sockets:
        socket = socket_for(af)
        _say(f"  socket-{socket.af:<8g} outer r {socket.outer_radius:<5g} length {socket.length:g}")
    _say()
    _say("drivers (shaft radii approximate, catalogue-typical):")
    for drive in chosen.drivers:
        _say(f"  driver-{drive:<9} shaft r {SHAFT_RADIUS[drive]:g}")
