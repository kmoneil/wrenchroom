"""The bench's fasteners, read from their solids, against the bench's own sidecar.

Every part the sidecar describes is read from the written bench.step: the head
must be the rule's, the drive's across-flats the standard tables' for the rule's
size (or, for hex_band's nut alone, inside its standard's band below that size),
and the size the rule's; low_head's screw, drawn with no drive, is held to the
standard head its outline fits instead. And the reading from STEP must equal the reading
from the shape as built: the round trip changes nothing a tool depends on.

A Torx head is the one exception: the solid reading knows hex, cross, slot and
square drives, not a hexalobular recess, so a Torx screw is Torx by its rule or
its name, never its solid (torx_wall), and only its size is held to the solid.
"""

import fnmatch

import pytest
from bench import sidecar_and_truth
from cells import CELLS

from wrenchroom.assembly import Assembly
from wrenchroom.detect.geometry import read_shape
from wrenchroom.fasteners import Head, Kind, Size, hex_key_af, in_hex_band, spanner_af


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
    wrong, banded, outlined = [], [], []
    for name, rule in _described(bench_parts):
        kind = Kind(rule.get("kind", "screw"))
        size = Size.parse(rule["size"]) if "size" in rule else None  # a gland may give none
        head = Head(rule["head"]) if "head" in rule else None
        # A shoulder screw's head is the one only its name can tell (issue #40).
        named = head if head is Head.SHOULDER else None
        reading = read_shape(bench_parts[name].shape, kind, named)
        expected_af = rule.get("across_flats")
        if expected_af is None and size is not None and (kind is Kind.NUT or head is Head.HEX):
            expected_af = spanner_af(size)
        elif expected_af is None and size is not None and head is not None:
            expected_af = hex_key_af(head, size)
        got = (reading.head, reading.drive_af and round(reading.drive_af, 6), reading.size)
        want = (head, expected_af and round(expected_af, 6), size)  # inch sizes in mm
        if head is Head.TORX:
            got, want = got[2], want[2]  # the size only: no Torx recess is read
        elif reading.head is None and reading.drive_af is None and reading.head_guess:
            outlined.append(name)  # no drive drawn: the outline's head, held to a standard
            got = (reading.head_guess, reading.head_standard, reading.size)
            want = (head, "ISO 7380-1" if head is Head.BUTTON else "ISO 4762", size)
        elif got != want and expected_af and in_hex_band(reading.drive_af, expected_af):
            banded.append(name)  # drawn inside its standard's band below the size
            got = (got[0], want[1], got[2])
        if got != want:
            wrong.append((name, got, want))
    assert not wrong
    assert banded == ["hex_band_nut"]  # issue #27: 12.8, inside ISO 4032's band for 13
    # Button heads drawn flat (issue #31), and #25's graze cells' M4 screws.
    graze_screws = [f"{c}_screw" for c in ("torus_graze", "torus_deep", "flat_graze", "flat_deep")]
    assert outlined == ["low_head_screw", "rubber_screw", *graze_screws]


def test_the_step_round_trip_changes_no_reading(bench_parts):
    built = {f"{cell.name}_{role}": shape for cell in CELLS for role, shape in cell.build()}
    for name, rule in _described(built):
        kind = Kind(rule.get("kind", "screw"))
        from_step = read_shape(bench_parts[name].shape, kind)
        as_built = read_shape(built[name], kind)
        assert (from_step.head, from_step.size) == (as_built.head, as_built.size), name
        assert from_step.drive_af == pytest.approx(as_built.drive_af, abs=1e-6), name
