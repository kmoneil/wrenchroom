"""Time the golden bench scaled to N fasteners: the "500 in under 10 s" target.

Usage::

    uv run python scripts/perf.py                        # 500 fasteners, 10 s budget
    uv run python scripts/perf.py --fasteners 1000 --budget 0     # report only
    uv run python scripts/perf.py --exact --fasteners 100 --budget 0

The bench is repeated along the grid until it has at least N fasteners and
written as STEP (that part is not timed). Then it times what a user waits for
with ``wrenchroom check``: reading the model, and checking it, which includes
reading the alternate lever-up model when the first fastener is retried there.
The verdict counts must come out as exactly that many copies of the bench's, so
a fast engine that is wrong cannot pass. Exits 1 when read plus check is over
the budget or a count is off.

Under GitHub Actions the table also goes to the job summary, so the CI job
reports a number on every run before it is trusted to gate.
"""

from __future__ import annotations

import argparse
import math
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN = REPO_ROOT / "tests" / "golden"


def main(argv: list[str]) -> int:
    """Build, time, compare, report."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fasteners", type=int, default=500, help="at least this many")
    parser.add_argument("--budget", type=float, default=10.0, help="seconds; 0 reports only")
    parser.add_argument("--exact", action="store_true", help="time the exact engine instead")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(GOLDEN))
    from bench import FINAL_COUNTS, KIT, write  # noqa: PLC0415  (path set just above)

    from wrenchroom.assembly import Assembly  # noqa: PLC0415  (heavy; after argparse)
    from wrenchroom.check import check  # noqa: PLC0415
    from wrenchroom.config import Config  # noqa: PLC0415

    copies = math.ceil(args.fasteners / FINAL_COUNTS["fasteners"])
    engine = "exact" if args.exact else "mesh"
    with tempfile.TemporaryDirectory() as scratch:
        directory = Path(scratch)
        started = time.perf_counter()
        write(directory, copies=copies)
        built = time.perf_counter() - started

        started = time.perf_counter()
        assembly = Assembly.from_step(directory / "bench.step")
        read = time.perf_counter() - started

        config = Config.load(directory / "wrenchroom.yaml")
        started = time.perf_counter()
        report = check(
            assembly, config, kit=KIT, model="bench.step", model_dir=directory, engine=engine
        )
        checked = time.perf_counter() - started

    want = {key: count * copies for key, count in FINAL_COUNTS.items()}
    counts_ok = report.summary == want
    total = read + checked
    in_budget = args.budget <= 0 or total <= args.budget
    fasteners = report.summary["fasteners"]
    verdict = "report only" if args.budget <= 0 else ("PASS" if in_budget else "OVER")
    rows = [
        (
            "machine",
            f"{platform.machine()} {platform.system()}, Python {platform.python_version()}",
        ),
        ("model", f"{fasteners} fasteners, {len(assembly)} parts ({copies} copies of the bench)"),
        ("engine", engine),
        ("build and write", f"{built:.2f} s (not timed)"),
        ("read model", f"{read:.2f} s"),
        ("check", f"{checked:.2f} s ({1000 * checked / max(1, fasteners):.1f} ms a fastener)"),
        ("read + check", f"{total:.2f} s, budget {args.budget:g} s: {verdict}"),
        ("counts", "as expected" if counts_ok else f"WRONG: {report.summary} != {want}"),
    ]
    width = max(len(name) for name, _ in rows)
    for name, value in rows:
        print(f"{name:<{width}}  {value}")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a") as summary:
            summary.write("### wrenchroom perf\n\n| | |\n|---|---|\n")
            summary.writelines(f"| {name} | {value} |\n" for name, value in rows)
    return 0 if counts_ok and in_budget else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
