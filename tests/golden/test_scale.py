"""The bench repeated along the grid: every copy gives its cell's answer.

Three copies in one STEP, checked together on the default engine. This shows
two things a single bench can't:

- a verdict doesn't depend on where its cell sits: the last copy is metres
  further from the origin than the first, and every field of its report, seats
  included (shifted by exactly the grid offset), must come out the same;
- the engine's per-part caches never hand one copy another's geometry: every
  copy repeats every role under its own prefix, and the lever-up model repeats
  them all again with each copy's lever moved.

The 500-fastener timing run is `scripts/perf.py` (the `perf` lane); this is
its correctness half, small enough for every push.
"""

import re

import pytest
from bench import FINAL_COUNTS, PITCH, SLOTS, check_bench, copy_prefix, write
from cells import CELLS

COPIES = 3
_PREFIX = re.compile(r"^r\d+_")


@pytest.fixture(scope="module")
def scaled(tmp_path_factory):
    directory = tmp_path_factory.mktemp("scaled")
    truth = write(directory, copies=COPIES)
    report = check_bench(directory)
    return truth, {entry["name"]: entry for entry in report.to_json_dict()["fasteners"]}, report


def test_the_counts_scale(scaled):
    _, _, report = scaled
    assert report.summary == {key: count * COPIES for key, count in FINAL_COUNTS.items()}
    assert report.exit_code == 1


def test_every_copy_meets_the_truth(scaled):
    truth, entries, _ = scaled
    wrong = []
    for name, expected in sorted(truth.items()):
        if expected.get("needs"):
            continue  # a strict xfail in test_bench; nothing to compare yet
        entry = entries[name]
        for key, want in expected.items():
            got = entry[key]
            if sorted(got) != sorted(want) if isinstance(want, list) else got != want:
                wrong.append((name, key, got, want))
    assert not wrong


def _slot_of(name):
    """The grid slot of a copy-0 fastener's cell."""
    if name.startswith("twins_"):
        return len(CELLS)
    cell = max((c for c in CELLS if name.startswith(f"{c.name}_")), key=lambda c: len(c.name))
    return CELLS.index(cell)


def _offset(copy, slot):
    def place(index):
        return ((index % 6) * PITCH, (index // 6) * PITCH, 0.0)

    a, b = place(copy * SLOTS + slot), place(slot)
    return tuple(a[i] - b[i] for i in range(3))


def _unprefixed(value, prefix):
    """The copy's names back to the first copy's, in lists and inside reasons."""
    if isinstance(value, list):
        return [_unprefixed(item, prefix) for item in value]
    if isinstance(value, str):
        return re.sub(rf"\b{re.escape(prefix)}", "", value)
    return value


def test_every_copy_reports_like_the_first(scaled):
    _, entries, _ = scaled
    firsts = {name: entry for name, entry in entries.items() if not _PREFIX.match(name)}
    assert len(firsts) == FINAL_COUNTS["fasteners"]
    for copy in range(1, COPIES):
        prefix = copy_prefix(copy)
        for name, first in firsts.items():
            other = {
                key: _unprefixed(value, prefix) for key, value in entries[prefix + name].items()
            }
            for key in first:
                if key == "seat" and first["seat"] is not None:
                    shift = _offset(copy, _slot_of(name))
                    moved = [other["seat"][i] - shift[i] for i in range(3)]
                    assert moved == pytest.approx(first["seat"], abs=1e-6), (prefix + name, key)
                elif key == "axis" and first["axis"] is not None:
                    assert other["axis"] == pytest.approx(first["axis"], abs=1e-9), (
                        prefix + name,
                        key,
                    )
                else:
                    assert other[key] == first[key], (prefix + name, key)


def test_the_perf_bench_s_timed_and_untimed_cells_make_the_whole_bench():
    # scripts/perf.py times the "timed" copies against the budget and the
    # deliberate worst cases apart (issue #25): between them, nothing is left out.
    from bench import sidecar_and_truth, summary_of  # noqa: PLC0415

    whole = sidecar_and_truth(1)[1]
    timed = sidecar_and_truth(1, "timed")[1]
    untimed = sidecar_and_truth(1, "untimed")[1]
    assert summary_of(whole) == FINAL_COUNTS
    assert set(timed) | set(untimed) == set(whole)
    assert not set(timed) & set(untimed)
    assert sorted(untimed) == [
        "flat_deep_screw",
        "flat_graze_screw",
        "torus_deep_screw",
        "torus_graze_screw",
    ]
    assert summary_of(sidecar_and_truth(3, "timed")[1])["fasteners"] == 3 * len(timed)
