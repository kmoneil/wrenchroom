"""The canonical report must match the committed snapshot byte for byte.

The truth layer asserts what each cell is about; this catches everything else:
swing angles, blocker order, seats, reasons. When a change is meant, regenerate
with `uv run python scripts/golden.py --update` and let the PR show the diff.
"""

import json
from pathlib import Path

from bench import canonical

SNAPSHOT = Path(__file__).parent / "bench.snapshot.json"


def test_report_matches_snapshot(bench_report):
    got = canonical(bench_report.to_json_dict())
    want = json.loads(SNAPSHOT.read_text())
    assert got == want, (
        "the canonical report moved; if the change is meant, run "
        "`uv run python scripts/golden.py --update` and review the diff"
    )
