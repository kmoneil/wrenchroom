"""Maintain the golden bench's snapshot, or write the bench out for a person.

Usage::

    uv run python scripts/golden.py --update      # rewrite tests/golden/bench.snapshot.json
    uv run python scripts/golden.py --out DIR     # write bench.step + sidecars to look at
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN = REPO_ROOT / "tests" / "golden"
SNAPSHOT = GOLDEN / "bench.snapshot.json"


def main(argv: list[str]) -> int:
    """Parse the one flag that was given and do it."""
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--update", action="store_true", help="rewrite the committed snapshot")
    group.add_argument("--out", type=Path, help="write bench.step and sidecars here")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(GOLDEN))
    from bench import canonical, check_bench, write  # noqa: PLC0415  (path set just above)

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        write(args.out)
        print(f"wrote bench.step, bench_lever-up.step and both sidecars to {args.out}")
        return 0

    with tempfile.TemporaryDirectory() as scratch:
        write(scratch)
        report = check_bench(scratch)
    SNAPSHOT.write_text(json.dumps(canonical(report.to_json_dict()), indent=1) + "\n")
    print(f"snapshot rewritten: {SNAPSHOT}")
    print(f"summary: {report.summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
