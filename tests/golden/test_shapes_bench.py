"""The bench's fasteners, read from their solids, against the bench's own sidecar.

Every part the sidecar describes is read from the written bench.step: the head
must be the rule's, the drive's across-flats the standard tables' for the rule's
size (or, for hex_band's nut alone, inside its standard's band below that size),
and the size the rule's; low_head's screw, drawn with no drive, is held to the
standard head its outline fits instead. guessed's nut, drawn a little under its
band on a bore of no standard size, can't say its size alone: its band guesses
another, and only its bolt gives the rule's (issue #50). plain_pin's and
stepped_pin's shoulder screws are ISO 7379's by their outlines (issue #48);
odd_head's fits no standard head, and is the one guess. And the reading from
STEP must equal the reading from the shape as built: the round trip changes
nothing a tool depends on.

A Torx head is the one exception: the solid reading knows hex, cross, slot and
square drives, not a hexalobular recess, so a Torx screw is Torx by its rule or
its name, never its solid (torx_wall), and only its size is held to the solid.
"""

import fnmatch

import pytest
from bench import sidecar_and_truth
from cells import CELLS

from wrenchroom.assembly import Assembly
from wrenchroom.checker import UNDERSIZE_MM
from wrenchroom.detect.geometry import read_shape
from wrenchroom.fasteners import (
    HEX_AF_MIN,
    Head,
    Kind,
    Size,
    hex_key_af,
    in_hex_band,
    spanner_af,
)


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
    wrong, banded, outlined, guessed, unmatched = [], [], [], [], []
    for name, rule in _described(bench_parts):
        kind = Kind(rule.get("kind", "screw"))
        size = Size.parse(rule["size"]) if "size" in rule else None  # a gland may give none
        head = Head(rule["head"]) if "head" in rule else None
        # A shoulder screw's head is the one only its name can tell (issue #40), and
        # named_head's outline is a socket head's, the name's button standing (#81).
        named = head if head is Head.SHOULDER or name in _BY_NAME else None
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
            standard = _STANDARD.get(head, "ISO 4762")
            if reading.head_unmatched:
                unmatched.append(name)  # no standard's: a guess by its proportions
                standard = None
            want = (head, standard, size)
        elif got != want and expected_af and in_hex_band(reading.drive_af, expected_af):
            banded.append(name)  # drawn inside its standard's band below the size
            got = (got[0], want[1], got[2])
        elif reading.size_from_band and size is not None and reading.size != size:
            guessed.append(name)  # its band alone says another size; its bolt says the rule's
            least = HEX_AF_MIN[expected_af]
            assert least - UNDERSIZE_MM <= reading.drive_af < least, name
            got = (got[0], want[1], size)
        if got != want:
            wrong.append((name, got, want))
    assert not wrong
    # Issue #27: 12.8, inside ISO 4032's band for 13 (band_agrees's on a bore of no size).
    assert banded == ["hex_band_nut", "band_agrees_nut"]
    # Issue #50: 12.6, a 5/16's by the band; its bolt, or its name, says M8.
    assert guessed == ["guessed_nut", "named_size_m8_nut"]
    # Button heads drawn flat (issue #31), and #25's graze cells' M4 screws.
    graze_screws = [f"{c}_screw" for c in ("torus_graze", "torus_deep", "flat_graze", "flat_deep")]
    # And issue #48's shoulder screws drawn plainly, and its odd head.
    pins = ["plain_pin_bolt", "stepped_pin_bolt", "minor_pin_bolt"]
    odd = ["odd_head_screw", "odd_head_button_screw"]
    assert outlined == ["low_head_screw", "rubber_screw", *graze_screws, *pins, *odd]
    assert unmatched == odd


_STANDARD = {Head.BUTTON: "ISO 7380-1", Head.SHOULDER: "ISO 7379"}

#: Screws whose head only their name gives, with the head their outline shows instead.
_BY_NAME = {"named_head_bhcs": Head.SOCKET}


def test_a_head_only_its_name_gives_is_disputed_by_its_outline(bench_parts):
    for name, outline in _BY_NAME.items():
        reading = read_shape(bench_parts[name].shape, Kind.SCREW)
        assert (reading.head, reading.head_standard) == (outline, "ISO 4762"), name


def test_the_step_round_trip_changes_no_reading(bench_parts):
    built = {f"{cell.name}_{role}": shape for cell in CELLS for role, shape in cell.build()}
    for name, rule in _described(built):
        kind = Kind(rule.get("kind", "screw"))
        from_step = read_shape(bench_parts[name].shape, kind)
        as_built = read_shape(built[name], kind)
        assert (from_step.head, from_step.size) == (as_built.head, as_built.size), name
        assert from_step.drive_af == pytest.approx(as_built.drive_af, abs=1e-6), name
