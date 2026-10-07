"""Shoulder screws (issue #40): the key their thread sets, not their shoulder's.

A socket head shoulder screw (ISO 7379) has a shoulder wider than its thread and
takes a smaller key than a socket head cap screw of the same thread: an M6 on an
8 mm shoulder takes a 4 mm key, where ISO 4762's M6 takes 5 and an 8 mm shank
would say M8 and a 6 mm key. Its socket head looks like any other, so only its
name can tell it: ``shoulder`` before the noun says the head, and detection reads
the solid knowing it.
"""

import pytest
import yaml
from build123d import Box, Compound, Cylinder, Pos, export_step
from click.testing import CliRunner

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.detect import describe, read_name, read_shape
from wrenchroom.fasteners import (
    SHOULDER_KEY_AF,
    SHOULDER_THREAD,
    SOCKET_KEY_AF,
    Head,
    Kind,
    Size,
    hex_key_af,
)
from wrenchroom.report import Verdict


def shoulder_screw(*, pocket=True, thread=True, shoulder_d=8.0):
    """An M6 ISO 7379 shoulder screw: head 13 by 5.5 on z 0..5.5, the 8 mm shoulder
    20 long below it, the M6 thread 10 below that; a 4 mm hex socket 3.3 deep."""
    head = Pos(0, 0, 2.75) * Cylinder(6.5, 5.5)
    shape = head + Pos(0, 0, -10) * Cylinder(shoulder_d / 2, 20)
    if thread:
        shape = shape + Pos(0, 0, -25) * Cylinder(3, 10)
    if pocket:
        shape = shape - hex_prism(4.0, 3.31, 5.5 - 3.3)
    return shape


def pivot(shape):
    """The screw through a lever into a plate, its head in open air."""
    return Assembly(
        [
            Part("pivot_shoulder_screw", Pos(0, 0, 20) * shape),
            Part("lever", Pos(0, 0, 10) * (Box(60, 30, 20) - Cylinder(4.1, 21))),
            Part("plate", Pos(0, 0, -5) * (Box(200, 200, 10) - Cylinder(3, 11))),
        ]
    )


# ---------------------------------------------------------------------------
# The tables.
# ---------------------------------------------------------------------------


def test_the_keys_are_iso_7379_s_and_smaller_than_a_cap_screw_s():
    assert SHOULDER_KEY_AF == {
        "M5": 3.0,
        "M6": 4.0,
        "M8": 5.0,
        "M10": 6.0,
        "M12": 8.0,
        "M16": 10.0,
        "M20": 12.0,
    }
    for size, key in SHOULDER_KEY_AF.items():
        assert key < SOCKET_KEY_AF[size], size
        assert hex_key_af(Head.SHOULDER, Size.parse(size)) == key


def test_every_shoulder_names_a_thread_with_a_key():
    assert SHOULDER_THREAD == {
        6.5: "M5",
        8.0: "M6",
        10.0: "M8",
        13.0: "M10",
        16.0: "M12",
        20.0: "M16",
        25.0: "M20",
    }
    for shoulder, thread in SHOULDER_THREAD.items():
        assert thread in SHOULDER_KEY_AF
        assert shoulder > Size.parse(thread).diameter_mm


# ---------------------------------------------------------------------------
# Names.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("shoulder_bolt", None),
        ("pivot_shoulder_screw", None),
        ("shoulder screw M6x20", "M6"),
        ("M6x20 shoulder", "M6"),  # alone, still the screw
        ("socket head shoulder screw M8", "M8"),  # a shoulder outranks a socket
    ],
)
def test_shoulder_says_the_head(name, size):
    hint = read_name(name)
    assert (hint.kind, hint.head) == (Kind.SCREW, Head.SHOULDER)
    assert (hint.size.designation if hint.size else None) == size


# ---------------------------------------------------------------------------
# The solid, read knowing the name.
# ---------------------------------------------------------------------------


def test_without_the_name_its_head_reads_as_another():
    # Its head (13 by 5.5) fits neither ISO 4762's M6 nor ISO 7380-1's, and by its
    # proportions reads as a button head, a guess. ISO 7380's button keys happen to
    # be ISO 7379's for M5 to M16, so the size comes out M6 all the same: only the
    # head is wrong, which the name puts right.
    reading = read_shape(shoulder_screw(), Kind.SCREW)
    assert (reading.head, reading.head_unmatched) == (Head.BUTTON, True)
    assert reading.size.designation == "M6"


@pytest.mark.parametrize(
    ("pocket", "thread", "head", "settled"),
    [
        (True, True, Head.SHOULDER, True),  # the 4 mm key settles M6
        (True, False, Head.SHOULDER, True),
        (False, True, None, False),  # the thread drawn: the thinnest round
        (False, False, None, False),  # the shoulder alone: ISO 7379's thread for it
    ],
)
def test_knowing_the_name_every_drawing_reads_m6(pocket, thread, head, settled):
    reading = read_shape(shoulder_screw(pocket=pocket, thread=thread), Kind.SCREW, Head.SHOULDER)
    assert reading.head is head
    assert (reading.size.designation, reading.size_from_drive) == ("M6", settled)


def test_a_shoulder_no_standard_has_gives_no_size_by_itself():
    shape = shoulder_screw(pocket=False, thread=False, shoulder_d=9.0)
    assert read_shape(shape, Kind.SCREW, Head.SHOULDER).size is None


def test_detection_agrees_with_the_name_and_says_so():
    found = describe(
        Part("pivot_shoulder_screw", shoulder_screw()), read_name("pivot_shoulder_screw")
    )
    assert (found.head, found.size.designation, found.drive_af) == (
        Head.SHOULDER,
        "M6",
        pytest.approx(4.0),
    )
    assert found.basis == "noun 'screw'; solid: shoulder, 4 across flats, M6 measured"
    assert found.confidence == "high"


# ---------------------------------------------------------------------------
# The check, the sidecar, detect.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("pocket", "thread"), [(True, True), (False, True), (False, False)])
def test_an_m6_shoulder_screw_turns_with_the_4_mm_key(pocket, thread):
    (result,) = check(pivot(shoulder_screw(pocket=pocket, thread=thread))).results
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "hex-key-4",
        "driver straight in",
    )
    assert result.fastener.head is Head.SHOULDER


def test_a_sidecar_rule_says_shoulder_outright():
    rule = {"parts": "pivot_*", "kind": "screw", "head": "shoulder", "size": "M8"}
    (result,) = check(pivot(shoulder_screw()), Config.from_dict({"fasteners": [rule]})).results
    assert (result.fastener.source, result.tool) == ("sidecar", "hex-key-5")  # M8's: 5


def test_detect_writes_the_head(tmp_path):
    shapes = []
    for part in pivot(shoulder_screw()):
        part.shape.label = part.name
        shapes.append(part.shape)
    export_step(Compound(children=shapes), str(tmp_path / "model.step"))
    out = CliRunner().invoke(main, ["detect", str(tmp_path / "model.step")]).stdout
    (rule,) = yaml.safe_load(out)["fasteners"]
    assert (rule["head"], rule["size"]) == ("shoulder", "M6")


def test_with_the_thread_drawn_the_thread_is_the_size_whatever_the_shoulder():
    # A 10 mm shoulder, ISO 7379's for M8, on an M6 thread drawn as such: the
    # thinnest round is the thread, and it stands.
    shape = shoulder_screw(pocket=False, thread=True, shoulder_d=10.0)
    assert read_shape(shape, Kind.SCREW, Head.SHOULDER).size.designation == "M6"
