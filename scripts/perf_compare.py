"""Time this tree's check against a base commit's, on the same machine.

Usage::

    WRENCHROOM_PERF_BASE=../base uv run python scripts/perf_compare.py
    uv run python scripts/perf_compare.py --base ../base --rounds 3 --slower 0

The perf lane's budget is for a laptop. A hosted runner takes two to four times as
long, and which runner a job gets moves that by as much again: the bench read and
checked took 25 to 49 s on Linux and 19 to 48 s on macOS over the same week of runs,
the code hardly changing. No one figure there both passes every run and fails a
check half as fast. Two runs on the same Linux runner come within 3% of each other,
so this times both trees on the runner the job got, and fails when this tree takes
more than ``--slower`` times as long a fastener as the base. A macOS runner varies as
much within a job as between jobs (25 to 43 s for one commit), so CI compares on
Linux only.

The base is a checkout of the commit to compare with (a git worktree), with its own
environment synced (``uv sync`` in it). Each tree runs its own ``scripts/perf.py``
with its own code, its own bench and its own Python, budget off, so a bench that grew
is allowed for by the time a fastener. The trees take turns, base first, ``--rounds``
times each, and each side's fastest run counts. Exits 1 when this tree is too slow,
or when either tree's verdict counts are wrong, as the perf lane does.

Under GitHub Actions the comparison also goes to the job summary.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The perf script's rows read here, as every version of it since the engines were
#: refereed (c476d9d) prints them: ``model  549 fasteners, ...`` and
#: ``read + check  47.75 s, budget 0 s: report only``.
FASTENERS = re.compile(r"^model\s+(\d+) fasteners", re.MULTILINE)
TOTAL = re.compile(r"^read \+ check\s+([\d.]+) s", re.MULTILINE)


@dataclass
class Tree:
    """One side of the comparison: a checkout, and what its runs measured."""

    name: str
    root: Path
    commit: str = "?"
    fasteners: int = 0
    totals: list[float] = field(default_factory=list)
    failed: str = ""

    @property
    def fastest(self) -> float:
        """The fastest run's read and check, in ms a fastener."""
        return 1000 * min(self.totals) / max(1, self.fasteners)


def main(argv: list[str]) -> int:
    """Take turns timing the two trees, compare, report."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--base",
        type=Path,
        default=os.environ.get("WRENCHROOM_PERF_BASE"),
        help="the base commit's checkout (default: $WRENCHROOM_PERF_BASE)",
    )
    parser.add_argument("--rounds", type=int, default=2, help="runs of each tree")
    parser.add_argument(
        "--slower", type=float, default=1.5, help="times as long a fastener; 0 reports only"
    )
    args = parser.parse_args(argv)
    if args.base is None:
        parser.error("say which checkout to compare with: --base or $WRENCHROOM_PERF_BASE")

    base = Tree("base", args.base.resolve(), _commit(args.base))
    this = Tree("this tree", REPO_ROOT, _commit(REPO_ROOT))
    for tree in (base, this):
        if not _python(tree).exists():
            sys.exit(f"{_python(tree)} does not exist. Run `uv sync` in {tree.root} first.")
    for _ in range(args.rounds):
        for tree in (base, this):
            _run(tree)
            if tree.failed:
                print(f"{tree.name} ({tree.commit}): {tree.failed}")
                return 1

    ratio = (min(this.totals) * base.fasteners) / (min(base.totals) * this.fasteners)
    in_bounds = args.slower <= 0 or ratio <= args.slower
    verdict = (
        "report only"
        if args.slower <= 0
        else (f"within {args.slower:g}" if in_bounds else f"OVER {args.slower:g}")
    )
    rows = [
        ("", f"base ({base.commit})", f"this tree ({this.commit})"),
        ("fasteners", str(base.fasteners), str(this.fasteners)),
        *(
            (f"round {n + 1}", f"{b:.2f} s", f"{t:.2f} s")
            for n, (b, t) in enumerate(zip(base.totals, this.totals, strict=True))
        ),
        ("fastest", f"{base.fastest:.1f} ms a fastener", f"{this.fastest:.1f} ms a fastener"),
    ]
    widths = [max(len(row[column]) for row in rows) for column in range(3)]
    print()
    for row in rows:
        print(
            "  ".join(f"{cell:<{width}}" for cell, width in zip(row, widths, strict=True)).rstrip()
        )
    said = f"this tree takes {ratio:.2f} times as long a fastener as its base: {verdict}"
    print(said)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a") as summary:
            summary.write("### wrenchroom perf, against the base\n\n")
            summary.write(f"| {' | '.join(rows[0])} |\n|---|---|---|\n")
            summary.writelines(f"| {' | '.join(row)} |\n" for row in rows[1:])
            summary.write(f"\n{said}\n")
    return 0 if in_bounds else 1


def _commit(root: Path) -> str:
    """The checkout's commit, short, or ``?`` where git can't say."""
    git = shutil.which("git")
    if git is None:
        return "?"
    found = subprocess.run(
        [git, "-C", str(root), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return found.stdout.strip() or "?"


def _python(tree: Tree) -> Path:
    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    return tree.root / ".venv" / bin_dir / ("python.exe" if sys.platform == "win32" else "python")


def _run(tree: Tree) -> None:
    """One run of the tree's own perf script, budget off; its table goes to the log."""
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_STEP_SUMMARY", "VIRTUAL_ENV")}
    print(f"[{tree.name} {tree.commit}]", flush=True)
    ran = subprocess.run(
        [str(_python(tree)), "scripts/perf.py", "--budget", "0"],
        cwd=tree.root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    print(ran.stdout, end="", flush=True)
    print(ran.stderr, end="", file=sys.stderr, flush=True)
    fasteners, total = FASTENERS.search(ran.stdout), TOTAL.search(ran.stdout)
    if ran.returncode != 0:
        tree.failed = (
            f"its perf run exited {ran.returncode}: wrong verdict counts, or its output above says"
        )
    elif fasteners is None or total is None:
        tree.failed = "its perf run printed no model or read + check row"
    else:
        tree.fasteners = int(fasteners.group(1))
        tree.totals.append(float(total.group(1)))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
