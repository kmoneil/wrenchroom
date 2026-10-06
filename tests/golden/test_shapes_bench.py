"""The bench's fasteners, read from their solids, against the bench's own sidecar.

Every part the sidecar describes is read from the written bench.step: the head
must be the rule's, the drive's across-flats the standard tables' for the rule's
size, and the size the rule's. And the reading from STEP must equal the reading
from the shape as built: the round trip changes nothing a tool depends on.
"""

import fnmatch

import pytest
from bench import sidecar_and_truth
from cells import CELLS

from wrenchroom.assembly import Assembly
from wrenchroom.detect.geometry import read_shape
from wrenchroom.fasteners import Head, Kind, Size, hex_key_af, spanner_af


def _rules():
    sidecar, _ = sidecar_and_truth()
    return sidecar["fasteners"]


def _described(names):
    rules = _rules()
    for name in names:
        matches = [r for r in rules if fnmatch.fnmatchcase(name, r["parts"])]
        if matches:
            yield name, matches[-1]


@pytest.fixture(scope="module")
def bench_parts(bench_dir):
    return {part.name: part for part in Assembly.from_step(bench_dir / "bench.step")}


def test_every_bench_fastener_reads_as_its_rule_says(bench_parts):
    wrong = []
    for name, rule in _described(bench_parts):
        kind = Kind(rule.get("kind", "screw"))
        reading = read_shape(bench_parts[name].shape, kind)
        size = Size.parse(rule["size"])
        head = Head(rule["head"]) if "head" in rule else None
        expected_af = None
        if kind is Kind.NUT or head is Head.HEX:
            expected_af = spanner_af(size)
        elif head is not None:
            expected_af = hex_key_af(head, size)
        got = (reading.head, reading.drive_af and round(reading.drive_af, 6), reading.size)
        want = (head, expected_af and round(expected_af, 6), size)  # inch sizes in mm
        if got != want:
            wrong.append((name, got, want))
    assert not wrong


def test_the_step_round_trip_changes_no_reading(bench_parts):
    built = {f"{cell.name}_{role}": shape for cell in CELLS for role, shape in cell.build()}
    for name, rule in _described(built):
        kind = Kind(rule.get("kind", "screw"))
        from_step = read_shape(bench_parts[name].shape, kind)
        as_built = read_shape(built[name], kind)
        assert (from_step.head, from_step.size) == (as_built.head, as_built.size), name
        assert from_step.drive_af == pytest.approx(as_built.drive_af, abs=1e-6), name
