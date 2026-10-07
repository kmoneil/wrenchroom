"""A plain shoulder-screw head is ISO 7379's, and a head that fits nothing says so (#48).

A shoulder screw drawn plainly, a head 13 across and 5.5 high over an 8 mm
shoulder, was read as "button by its outline, fitting no standard head", and
checked with a 5 mm key (an M8 button head's) where ISO 7379 gives its M6 thread
a 4 mm key. Its head goes with its shoulder, the widest round under it, not with
its thread, so the outline table holds ISO 7379's heads by shoulder; the
shoulder gives the thread when none is drawn at a size. And where no standard
head fits, the head is a guess from proportions: detection's confidence is low,
and the check's result says so, not only detect's comment.
"""

import json

import pytest
import yaml
from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.detect import read_shape
from wrenchroom.detect.sidecar import sidecar_text
from wrenchroom.fasteners import (
    HEAD_OUTLINE,
    SHOULDER_KEY_AF,
    SHOULDER_OUTLINE,
    SHOULDER_THREAD,
    Head,
    Kind,
    Size,
)
from wrenchroom.report import Verdict


def shoulder_screw(shoulder=8.0, *, thread=None, pocket=False, head=None):
    """A head over a shoulder 25 long, over a thread 11 long when given (its diameter).

    ``head`` is (diameter, height), ISO 7379's for the shoulder unless given;
    ``pocket`` cuts the shoulder's ISO 7379 key into it.
    """
    head_d, head_h = head or SHOULDER_OUTLINE[shoulder]
    shape = Pos(0, 0, head_h / 2) * Cylinder(head_d / 2, head_h)
    shape = shape + Pos(0, 0, -12.5) * Cylinder(shoulder / 2, 25)
    if thread is not None:
        shape = shape + Pos(0, 0, -30.5) * Cylinder(thread / 2, 11)
    if pocket:
        key = SHOULDER_KEY_AF[SHOULDER_THREAD[shoulder]]
        shape = shape - hex_prism(key, head_h * 0.6 + 0.01, head_h * 0.4)
    return shape


def in_plate(shape, name="bolt", *, at=0.0):
    """The screw down through a plate, its head in open air."""
    plate = Pos(at, 0, -5) * (Box(80, 80, 10) - Cylinder(13, 10))
    return [Part(f"{name}_plate", plate), Part(name, Pos(at, 0, 0) * shape)]


def run(parts, engine="mesh", config=None):
    return check(Assembly(parts), config or Config(), kit="full", engine=engine)


# ---------------------------------------------------------------------------
# The issue's reproduction: one stepped to its thread, one drawn as its shoulder.
# ---------------------------------------------------------------------------


def test_the_issue_s_screws_are_m6_shoulder_screws_with_a_4_mm_key(engine):
    parts = [
        *in_plate(shoulder_screw(thread=6.0), "stepped_bolt"),
        *in_plate(shoulder_screw(), "plain_bolt", at=200.0),
    ]
    results = {r.fastener.name: r for r in run(parts, engine).results}
    for name in ("stepped_bolt", "plain_bolt"):
        result = results[name]
        fastener = result.fastener
        assert (fastener.head, fastener.size.designation) == (Head.SHOULDER, "M6"), name
        assert (result.verdict, result.tool) == (Verdict.TURNS, "hex-key-4"), name
        assert "shoulder by its outline, ISO 7379's" in fastener.basis
        assert fastener.confidence == "medium"  # a head by its outline, as any
        assert result.notes == ()


# ---------------------------------------------------------------------------
# Every ISO 7379 head, drawn every way.
# ---------------------------------------------------------------------------


def test_the_table_is_iso_7379_s():
    assert SHOULDER_OUTLINE == {
        6.5: (10.0, 4.5),
        8.0: (13.0, 5.5),
        10.0: (16.0, 7.0),
        13.0: (18.0, 9.0),
        16.0: (24.0, 11.0),
        20.0: (30.0, 14.0),
        25.0: (36.0, 16.0),
    }
    assert set(SHOULDER_OUTLINE) == set(SHOULDER_THREAD)  # a head for every shoulder


@pytest.mark.parametrize("shoulder", sorted(SHOULDER_OUTLINE))
@pytest.mark.parametrize("drawn", ["shoulder alone", "thread", "pocket"])
def test_every_iso_7379_head_reads_as_its_shoulder_s(shoulder, drawn):
    thread = Size.parse(SHOULDER_THREAD[shoulder])
    shape = shoulder_screw(
        shoulder,
        thread=thread.diameter_mm if drawn == "thread" else None,
        pocket=drawn == "pocket",
    )
    reading = read_shape(shape, Kind.SCREW)
    head = reading.head if drawn == "pocket" else reading.head_guess
    assert (head, reading.head_standard) == (Head.SHOULDER, "ISO 7379")
    assert reading.size == thread
    assert reading.size_from_drive is (drawn == "pocket")  # the key settles it
    if drawn == "pocket":
        assert reading.drive_af == pytest.approx(SHOULDER_KEY_AF[thread.designation])


def test_a_thread_drawn_at_no_size_takes_the_shoulder_s():
    # Stepped to M6's minor diameter, 4.92, which is no size: the shoulder says M6.
    reading = read_shape(shoulder_screw(thread=4.917), Kind.SCREW)
    assert (reading.head_guess, reading.size.designation) == (Head.SHOULDER, "M6")


def test_a_thread_drawn_at_another_size_stands():
    # A maker's M5 on an 8 mm shoulder: the thread drawn is the thread.
    reading = read_shape(shoulder_screw(thread=5.0), Kind.SCREW)
    assert (reading.head_guess, reading.size.designation) == (Head.SHOULDER, "M5")


@pytest.mark.parametrize("scale", [0.9, 1.1])
def test_a_head_drawn_near_the_standard_s_maxima_fits(scale):
    head = (13.0 * scale, 5.5 * scale)
    reading = read_shape(shoulder_screw(head=head), Kind.SCREW)
    assert (reading.head_guess, reading.head_standard) == (Head.SHOULDER, "ISO 7379")


@pytest.mark.parametrize("head", [(13.0, 6.3), (13.0, 4.7), (11.3, 5.5), (14.7, 5.5)])
def test_a_head_further_off_is_no_shoulder_s(head):
    # More than 12% off ISO 7379's 13 by 5.5 in one dimension.
    reading = read_shape(shoulder_screw(head=head), Kind.SCREW)
    assert reading.head_standard != "ISO 7379"


def test_a_maker_s_12_mm_shoulder_is_no_iso_7379_s():
    # Makers sell M10 shoulder screws on a 12 mm shoulder, an 18 by 9 head, where
    # ISO 7379's is 13 mm: only the standard's are read, and this one is a guess.
    reading = read_shape(shoulder_screw(12.0, head=(18.0, 9.0)), Kind.SCREW)
    assert (reading.head_standard, reading.head_unmatched) == (None, True)


@pytest.mark.parametrize(
    ("head", "size"),
    [
        (head, size)
        for head, table in HEAD_OUTLINE.items()
        for size in table
        if size.startswith("M")
    ],
)
def test_no_metric_socket_or_button_head_reads_as_a_shoulder_screw(head, size):
    # Each standard head drawn plainly over its own shank: still its own standard's,
    # wherever its shank is also a shoulder's size (M8 and M10, M16 and M20).
    d = Size.parse(size).diameter_mm
    head_d, head_h = HEAD_OUTLINE[head][size]
    shape = Pos(0, 0, head_h / 2) * Cylinder(head_d / 2, head_h) + Pos(0, 0, -8) * Cylinder(
        d / 2, 16
    )
    reading = read_shape(shape, Kind.SCREW)
    assert reading.head_guess is head
    assert reading.size.designation == size


def test_some_standard_heads_sit_on_shoulder_sizes():
    # A vacuity guard for the test above: shanks a shoulder could be.
    shanks = {
        Size.parse(size).diameter_mm
        for table in HEAD_OUTLINE.values()
        for size in table
        if size.startswith("M")
    }
    assert len(shanks & set(SHOULDER_OUTLINE)) >= 3


# ---------------------------------------------------------------------------
# A head that fits no standard: a guess, which the check says.
# ---------------------------------------------------------------------------

ODD = {"head": (12.0, 3.0)}  # over an M6 shank: no socket, button or shoulder head
GUESS = (
    "its head is a guess: drawn 12.00 across and 3.00 high, it fits no standard head, "
    "so button by its proportions; set head: in the sidecar"
)


def odd_screw():
    head_d, head_h = ODD["head"]
    return Pos(0, 0, head_h / 2) * Cylinder(head_d / 2, head_h) + Pos(0, 0, -10) * Cylinder(3, 20)


def test_a_head_that_fits_nothing_is_a_low_confidence_guess_the_check_says(engine):
    report = run(in_plate(odd_screw(), "odd_screw"), engine)
    (result,) = report.results
    assert (result.fastener.head, result.tool, result.verdict) == (
        Head.BUTTON,
        "hex-key-4",
        Verdict.TURNS,
    )
    assert result.fastener.confidence == "low"
    assert result.notes == (GUESS,)
    assert f"NOTE odd_screw: {GUESS}" in report.terminal_lines()
    assert f"- `odd_screw`: {GUESS}" in report.markdown()
    assert json.loads(report.json_text())["fasteners"][0]["notes"] == [GUESS]


def test_detect_writes_the_guess_down_for_a_person_to_confirm():
    assembly = Assembly(in_plate(odd_screw(), "odd_screw"))
    text = sidecar_text(check(assembly, Config()), "model.step")
    assert "# odd_screw: low confidence;" in text
    assert "button by its outline, fitting no standard head" in text
    (rule,) = [line for line in text.splitlines() if "head: button" in line]
    assert rule.strip() == "head: button"
    # Kept as written, the sidecar says the head: no guess, nothing to note.
    kept = check(assembly, Config.from_dict(yaml.safe_load(text)))
    (result,) = kept.results
    assert (result.tool, result.notes) == ("hex-key-4", ())


@pytest.mark.parametrize(
    "how",
    ["named", "sidecar", "pocket"],
)
def test_a_head_said_otherwise_is_no_guess(how):
    name = "odd_button_screw" if how == "named" else "odd_screw"
    shape = odd_screw()
    if how == "pocket":
        shape = shape - hex_prism(4.0, 1.81, 1.2)
    rules = (
        {"fasteners": [{"parts": name, "kind": "screw", "head": "button", "size": "M6"}]}
        if how == "sidecar"
        else {}
    )
    (result,) = run(in_plate(shape, name), config=Config.from_dict(rules)).results
    assert result.notes == ()
    assert result.fastener.confidence != "low"
