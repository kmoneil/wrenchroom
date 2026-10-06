"""Every lane this repository has, named in one place.

A lane is a name, the commands it runs, and one line saying what it proves. CI invokes
lanes by name and never spells out a tool's arguments itself; two spellings of "how this
project runs its checks" is how a flag exists locally and not in CI, or the other way
round. `ci.yml` and a developer's shell run exactly the same thing.

Usage::

    python scripts/lanes.py             # the table
    python scripts/lanes.py gates fast  # run those lanes, in that order

Tools are resolved inside `.venv` rather than taken from PATH: the versions that gate
have to be the ones `uv.lock` pins, not whatever a shell finds first.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = REPO_ROOT / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")


@dataclass(frozen=True)
class Lane:
    """One named way of running this project's checks.

    Attributes:
        name: What you type after ``lanes.py``.
        summary: What the lane proves, in one line.
        steps: The commands, in order; each argv[0] is resolved inside ``.venv``.
    """

    name: str
    summary: str
    steps: tuple[tuple[str, ...], ...]


LANES: tuple[Lane, ...] = (
    Lane(
        name="gates",
        summary="the static gates: ruff lint, ruff format, ty",
        steps=(
            ("ruff", "check", "."),
            ("ruff", "format", "--check", "."),
            ("ty", "check"),
        ),
    ),
    Lane(
        name="fast",
        summary="the unit suite, golden bench included",
        steps=(("pytest",),),
    ),
    Lane(
        name="golden",
        summary="only the golden bench: truth, counts, isolation, snapshot",
        steps=(("pytest", "tests/golden"),),
    ),
)


def _resolve(tool: str) -> Path:
    """Find the tool inside .venv, or say exactly what to run to get it."""
    path = VENV_BIN / (f"{tool}.exe" if sys.platform == "win32" else tool)
    if not path.exists():
        sys.exit(f"{path} does not exist. Run `uv sync` first.")
    return path


def _run(lane: Lane) -> int:
    """Run a lane's steps in order, stopping at the first failure."""
    for step in lane.steps:
        argv = [str(_resolve(step[0])), *step[1:]]
        print(f"[{lane.name}] {' '.join(step)}", flush=True)
        code = subprocess.run(argv, cwd=REPO_ROOT, check=False).returncode
        if code != 0:
            return code
    return 0


def main(argv: list[str]) -> int:
    """Print the table, or run the named lanes in order."""
    if not argv:
        width = max(len(lane.name) for lane in LANES)
        for lane in LANES:
            print(f"{lane.name:<{width}}  {lane.summary}")
        return 0
    by_name = {lane.name: lane for lane in LANES}
    unknown = [name for name in argv if name not in by_name]
    if unknown:
        sys.exit(f"unknown lane(s): {', '.join(unknown)}. Run with no arguments for the table.")
    for name in argv:
        code = _run(by_name[name])
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
