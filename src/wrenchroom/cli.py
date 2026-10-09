"""The command line interface.

Five commands: check, explain, detect (writes the sidecar), tools and clashes.

Exit codes, fixed: 0 every fastener passes, 1 a fastener fails (or two parts clash), 2
something not covered or a config error.

A report's FILE may be ``-``, for stdout: the report can then be piped, and what
would have been printed for a person goes to stderr instead, out of its way. Only one
report can go to stdout; a file really named ``-`` is ``./-``.

The heavy imports (build123d pulls OCP, seconds) happen inside the commands that need
them, so `--help` and `--version` stay instant.
"""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import click

from wrenchroom import __version__
from wrenchroom.terminal import printable

if TYPE_CHECKING:
    from collections.abc import Callable

    from wrenchroom.report import Report

#: Exit code for "not covered or a config error".
EXIT_NOT_COVERED = 2

#: The FILE that means stdout, as in most command-line tools.
STDOUT = "-"

_HAND_ROOM_HELP = (
    "Also check room for a hand on each handle, and for fingers on each plug (as "
    "`checks: {hand_room: true}`); untuned, so off by default."
)

_CLASHES_HELP = (
    "Also look for parts drawn into each other over the whole model (as "
    "`checks: {clashes: true}`); off by default, since models drawn with shortcuts "
    "have many."
)


def _say(text: str = "", *, err: bool = False) -> None:
    """Print one line for a person: the only way such text reaches the terminal here.

    Part names come from the model, and a model can come from anybody, so every
    line goes through :func:`wrenchroom.terminal.printable` and nothing in it can
    steer the terminal. A blank line is its own call, never a newline inside one.
    A whole report sent to stdout goes by :func:`_emit` instead.
    """
    click.echo(printable(text), err=err)


def _emit(document: str) -> None:
    """Write one whole report to stdout as UTF-8, as its file would hold it.

    Not through :func:`_say`, which would write the report's own newlines out as
    escapes. Each report is safe on a terminal as made: the JSON encoder and the
    page's data escape every control character, and the Markdown writes names
    through :func:`wrenchroom.terminal.printable` (tests/test_terminal.py holds
    all three to that).
    """
    click.echo(document.encode("utf-8"), nl=False)  # bytes: written as they are


def _wants_stdout(**outputs: str | None) -> bool:
    """Whether a report goes to stdout; two can't share it (exit 2, before any work)."""
    dashed = [f"--{option}" for option, path in outputs.items() if path == STDOUT]
    if len(dashed) > 1:
        msg = f"only one report can go to stdout (-), not {len(dashed)}: {', '.join(dashed)}"
        raise click.UsageError(msg)
    return bool(dashed)


def _write(path: str, document: Callable[[], str], to_file: Callable[[str], None]) -> None:
    """Write one report to its file, or to stdout when the path is ``-``."""
    if path == STDOUT:
        _emit(document())
    else:
        to_file(path)


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
    type=click.Path(dir_okay=False, allow_dash=True),
    help="Also write the machine-readable report here; - for stdout.",
)
@click.option(
    "--md",
    "md_path",
    type=click.Path(dir_okay=False, allow_dash=True),
    help="Also write the report as Markdown here, for a CI summary or a PR comment; - for stdout.",
)
@click.option(
    "--html",
    "html_path",
    type=click.Path(dir_okay=False, allow_dash=True),
    help="Also write the 3D view here: one self-contained file to open in a browser; - for stdout.",
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
@click.option("--clashes", is_flag=True, default=None, help=_CLASHES_HELP)
def check(  # noqa: PLR0913, PLR0917  (Click passes one parameter per option)
    model: Path,
    config_path: Path | None,
    kit: str,
    json_path: str | None,
    md_path: str | None,
    html_path: str | None,
    step_deg: float,
    only: str | None,
    state: str | None,
    exact: bool,
    hand_room: bool | None,
    clashes: bool | None,
) -> None:
    """Check every fastener in MODEL and report the verdicts.

    A report sent to stdout (-) moves the table to stderr, so the report can be
    piped: --json - | jq, or --md - >> "$GITHUB_STEP_SUMMARY".
    """
    to_stdout = _wants_stdout(json=json_path, md=md_path, html=html_path)
    report = _run(
        model,
        config_path,
        kit=kit,
        step_deg=step_deg,
        only=only,
        state=state,
        exact=exact,
        hand_room=hand_room,
        clashes=clashes,
    )
    for line in report.terminal_lines():
        _say(line, err=to_stdout)
    if json_path is not None:
        _write(json_path, report.json_text, report.to_json)
    if md_path is not None:
        _write(md_path, report.markdown, report.to_markdown)
    if html_path is not None:
        from wrenchroom.view import html_text

        _write(html_path, partial(html_text, report), report.to_html)
    sys.exit(report.exit_code)


def _run(  # noqa: PLR0913  (one keyword per check option, as check takes them)
    model: Path,
    config_path: Path | None,
    *,
    kit: str = "metric-home",
    step_deg: float = 15.0,
    only: str | None = None,
    state: str | None = None,
    exact: bool = False,
    hand_room: bool | None = None,
    clashes: bool | None = None,
) -> Report:
    """Load, check, and turn config mistakes into exit 2; shared by check and explain."""
    from wrenchroom.assembly import Assembly
    from wrenchroom.checker import check as run_check
    from wrenchroom.config import Config, ConfigError

    config_path = _beside(model, config_path)
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
            clashes=clashes,
        )
    except (ConfigError, ValueError) as exc:
        _say(f"error: {exc}", err=True)
        sys.exit(EXIT_NOT_COVERED)


def _beside(model: Path, config_path: Path | None) -> Path | None:
    """The sidecar: the one named, else wrenchroom.yaml beside the model, if present."""
    if config_path is not None:
        return config_path
    beside = model.parent / "wrenchroom.yaml"
    return beside if beside.exists() else None


@main.command(name="clashes")
@click.argument("model", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Sidecar YAML; default: wrenchroom.yaml beside the model, if present.",
)
@click.option(
    "--json",
    "json_path",
    type=click.Path(dir_okay=False, allow_dash=True),
    help="Also write the clashes as JSON here; - for stdout.",
)
@click.option(
    "--md",
    "md_path",
    type=click.Path(dir_okay=False, allow_dash=True),
    help="Also write the clashes as Markdown here; - for stdout.",
)
@click.option(
    "--exact",
    is_flag=True,
    help="Use the exact OCP boolean engine: slow, the referee for borderline results.",
)
@click.option(
    "--with-ignored",
    is_flag=True,
    help="Also measure the parts the sidecar ignores (cables, hoses), which a clash leaves out.",
)
def clashes_command(
    model: Path,
    config_path: Path | None,
    json_path: str | None,
    md_path: str | None,
    exact: bool,
    with_ignored: bool,
) -> None:
    """List every pair of parts in MODEL drawn into each other, in every state's model.

    A fastener is measured past its thread, so a screw in a hole drawn at its tap
    drill is no clash; nor is a fastener with its pair or its mates, an ignored
    part, or two parts the sidecar's allow: names. Exits 1 for a clash, 2 for a
    config error or an allow glob that names no part.
    """
    from wrenchroom.assembly import Assembly
    from wrenchroom.checker import find_clashes
    from wrenchroom.config import Config, ConfigError

    to_stdout = _wants_stdout(json=json_path, md=md_path)
    config_path = _beside(model, config_path)
    try:
        config = Config.load(config_path) if config_path else None
        found = find_clashes(
            Assembly.from_step(model),
            config,
            model_dir=model.parent,
            engine="exact" if exact else "mesh",
            with_ignored=with_ignored,
        )
    except (ConfigError, ValueError) as exc:
        _say(f"error: {exc}", err=True)
        sys.exit(EXIT_NOT_COVERED)
    for line in found.lines():
        _say(line, err=to_stdout)
    engine = "exact" if exact else "mesh"
    if json_path is not None:
        document = partial(found.json_text, model.name, engine)
        _write(json_path, document, partial(_save, document))
    if md_path is not None:
        page = partial(found.markdown_text, model.name)
        _write(md_path, page, partial(_save, page))
    sys.exit(found.exit_code)


def _save(document: Callable[[], str], path: str) -> None:
    """Write a document to its file, as UTF-8."""
    Path(path).write_text(document(), encoding="utf-8")


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
    type=click.Path(dir_okay=False, allow_dash=True),
    help="Also write the 3D view here, opening on this fastener's attempts; - for stdout.",
)
@click.option("--hand-room", is_flag=True, default=None, help=_HAND_ROOM_HELP)
def explain(
    model: Path,
    fastener: str,
    config_path: Path | None,
    kit: str,
    step_deg: float,
    exact: bool,
    html_path: str | None,
    hand_room: bool | None,
) -> None:
    """Show every attempt for one FASTENER in MODEL, with the blockers.

    With --html - the view goes to stdout and the attempts to stderr.
    """
    from wrenchroom.detect.sidecar import glob_escape
    from wrenchroom.report import attempt_text

    report = _run(
        model,
        config_path,
        kit=kit,
        step_deg=step_deg,
        only=glob_escape(fastener),  # the name exactly: "bolt[1]" is that part
        exact=exact,
        hand_room=hand_room,
    )
    if not report.results:
        _say(f"error: no fastener named {fastener!r} (is it in the sidecar?)", err=True)
        sys.exit(EXIT_NOT_COVERED)
    (result,) = report.results
    if html_path is not None:
        from wrenchroom.view import html_text

        name = result.fastener.name
        _write(
            html_path,
            partial(html_text, report, select=name),
            partial(report.to_html, select=name),
        )
    lines = [result.headline]
    if result.fastener.source != "sidecar":
        lines.append(f"  found by {result.fastener.source}: {result.fastener.basis}")
    if result.reason:
        lines.append(f"  reason: {result.reason}")
    lines.extend(f"  tried {attempt_text(attempt)}" for attempt in result.attempts)
    if result.stuck_on:
        lines.append(f"  cannot come out: {', '.join(result.stuck_on)} in the way")
    told = report.build.told(result.name) if report.build is not None else None
    if told is not None:
        lines.append(f"  in the build: {told}")
    for line in lines:
        _say(line, err=html_path == STDOUT)
    sys.exit(report.exit_code)


@main.command()
@click.option("--kit", default="metric-home", show_default=True, help="Which tool kit.")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="A sidecar whose own tools (its tools: list) join the kit, listed after it.",
)
@click.option(
    "--used",
    "model",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Check this model, and list the tools its fasteners need instead.",
)
@click.option("--state", help="With --used: check in this state instead of the config's default.")
@click.option("--exact", is_flag=True, help="With --used: use the exact OCP boolean engine.")
def tools(
    kit: str, config_path: Path | None, model: Path | None, state: str | None, exact: bool
) -> None:
    """List the kit's tools and their dimensions, citations and approximations.

    Exactly the tools a check with this kit tries, from the same tables the
    sweeps read: a fastener needing anything not listed is not covered. With
    --config, a sidecar's own tools too, which a check tries after the kit's.

    With --used MODEL, the tools MODEL's fasteners need, as a check with this
    kit finds them: one line per tool, how many fasteners need it, and why an
    unusual one is (outside the default kit, needed by one or two fasteners, or
    the only tool reaching one). It exits 0 once the check has run: `wrenchroom
    check` is the one that fails a build.
    """
    if model is not None:
        report = _run(model, config_path, kit=kit, state=state, exact=exact)
        for line in report.tools_used().lines():
            _say(line)
        return
    if state is not None or exact:
        raise click.UsageError("--state and --exact go with --used MODEL: they say how to check it")
    from wrenchroom.config import Config, ConfigError
    from wrenchroom.tools import custom
    from wrenchroom.tools.kits import kit_named, listing

    try:
        chosen = kit_named(kit)
        config = Config.load(config_path) if config_path else None
    except (ConfigError, ValueError) as exc:
        _say(f"error: {exc}", err=True)
        sys.exit(EXIT_NOT_COVERED)
    for line in listing(chosen):
        _say(line)
    if config is not None and config.tools:
        _say("")
        for line in custom.listing(config.tools, config_path.name if config_path else ""):
            _say(line)
