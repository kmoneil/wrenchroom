"""A flat-topped head is held to the standards' outlines (issue #31).

A screw head drawn as a plain cylinder, with no recess, was taken for a socket
head whatever its proportions, and checked with a socket head's key. Its
diameter and height are now compared with each standard head for the shank's
size: an M5 head 9.5 across and 2.75 high is ISO 7380-1's button head (a 3 mm
key), not ISO 4762's socket head (8.5 by 5, a 4 mm key). Where no standard fits,
the proportions decide and the basis says the head is a guess.
"""

import pytest
from build123d import Axis, Box, Cylinder, Pos, fillet

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.detect import describe, read_name, read_shape
from wrenchroom.fasteners import (
    HEAD_OUTLINE,
    HEAD_STANDARD,
    IMPERIAL_SIZES,
    METRIC_SIZES,
    Head,
    Kind,
)
from wrenchroom.report import Verdict

SIZES = {**METRIC_SIZES, **IMPERIAL_SIZES}


def screw(d, head_d, head_h, pocket=None):
    """A shank of diameter `d` below z 0, a flat-topped cylinder head above."""
    shape = Pos(0, 0, -8) * Cylinder(d / 2, 16) + Pos(0, 0, head_h / 2) * Cylinder(
        head_d / 2, head_h
    )
    if pocket is not None:
        depth = head_h * 0.6
        shape = shape - hex_prism(pocket, depth + 0.01, head_h - depth)
    return shape


# ---------------------------------------------------------------------------
# The tables.
# ---------------------------------------------------------------------------


def test_the_outlines_are_the_standards_pattern():
    for size, (dk, k) in HEAD_OUTLINE[Head.SOCKET].items():
        if size.startswith("M"):
            assert k == SIZES[size], size  # ISO 4762: the head as tall as the thread
        assert 1.4 * k <= dk <= 1.9 * k, size
    for size, (dk, k) in HEAD_OUTLINE[Head.BUTTON].items():
        assert k == pytest.approx(0.55 * SIZES[size]), size  # ISO 7380-1: k = 0.55 d
        assert dk > HEAD_OUTLINE[Head.SOCKET][size][0], size  # wider than the socket head


def test_every_outline_is_a_size_the_tool_knows():
    for table in HEAD_OUTLINE.values():
        assert set(table) <= set(SIZES)


def test_every_outline_names_its_standard():
    for head, table in HEAD_OUTLINE.items():
        for size in table:
            assert (head, size.startswith("M")) in HEAD_STANDARD, (head, size)
    assert HEAD_STANDARD[Head.BUTTON, True] == "ISO 7380-1"
    assert HEAD_STANDARD[Head.SOCKET, True] == "ISO 4762"


def test_no_size_fits_both_standards_at_once():
    # The two outlines must stay apart, or a head drawn to one would fit neither.
    for size, button in HEAD_OUTLINE[Head.BUTTON].items():
        socket = HEAD_OUTLINE[Head.SOCKET][size]
        assert abs(button[1] - socket[1]) > 0.24 * socket[1], size


@pytest.mark.parametrize(
    ("head", "size"),
    [(head, size) for head, table in HEAD_OUTLINE.items() for size in table],
)
def test_every_standard_head_drawn_flat_reads_as_itself(head, size):
    dk, k = HEAD_OUTLINE[head][size]
    reading = read_shape(screw(SIZES[size], dk, k), Kind.SCREW)
    assert reading.size.designation == size
    assert (reading.head, reading.head_guess) == (None, head)
    assert reading.head_standard == HEAD_STANDARD[head, size.startswith("M")]
    assert not reading.head_unmatched


# ---------------------------------------------------------------------------
# The issue's two screws, and the edges.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("head_d", "head_h", "head", "basis", "key"),
    [
        (9.5, 2.75, Head.BUTTON, "button by its outline, ISO 7380-1's", "hex-key-3"),
        (8.5, 5.0, Head.SOCKET, "socket by its outline, ISO 4762's", "hex-key-4"),
    ],
)
def test_the_issue_s_two_screws(head_d, head_h, head, basis, key):
    shape = screw(5.0, head_d, head_h)
    found = describe(Part("a_screw", shape), read_name("a_screw"))
    assert found.head is head
    assert found.basis == f"noun 'screw'; solid: {basis}, M5 measured"
    plate = Pos(0, 0, -3) * (Box(80, 80, 6) - Cylinder(2.75, 6))
    (result,) = check(Assembly([Part("a_screw", shape), Part("plate", plate)])).results
    assert (result.verdict, result.tool) == (Verdict.TURNS, key)


@pytest.mark.parametrize(
    ("scale", "fits"),
    [(1.0, True), (1.11, True), (0.89, True), (1.13, False), (0.87, False)],
)
def test_a_head_fits_within_twelve_percent(scale, fits):
    reading = read_shape(screw(5.0, 9.5 * scale, 2.75 * scale), Kind.SCREW)
    assert (reading.head_standard == "ISO 7380-1") is fits
    assert reading.head_unmatched is not fits


@pytest.mark.parametrize(
    ("head_d", "head_h", "head"),
    [(12.0, 2.0, Head.BUTTON), (7.0, 7.0, Head.SOCKET)],
)
def test_a_head_that_fits_no_standard_is_a_guess_by_its_proportions(head_d, head_h, head):
    shape = screw(5.0, head_d, head_h)
    reading = read_shape(shape, Kind.SCREW)
    assert (reading.head_guess, reading.head_standard, reading.head_unmatched) == (head, None, True)
    found = describe(Part("a_screw", shape), read_name("a_screw"))
    assert f"{head.value} by its outline, fitting no standard head" in found.basis


def test_with_no_size_to_compare_by_the_proportions_decide_and_say_nothing_more():
    # A 5.3 shank is no standard size: the outline is not compared, nor called unmatched.
    shape = screw(5.3, 9.5, 2.75)
    reading = read_shape(shape, Kind.SCREW)
    assert reading.size is None
    assert (reading.head_guess, reading.head_standard, reading.head_unmatched) == (
        Head.BUTTON,
        None,
        False,
    )


def test_a_size_with_no_button_row_is_held_to_the_socket_head_alone():
    # M20 has no ISO 7380-1 button head: drawn to ISO 4762, it is a socket head.
    reading = read_shape(screw(20.0, 30.0, 20.0), Kind.SCREW)
    assert (reading.head_guess, reading.head_standard) == (Head.SOCKET, "ISO 4762")


def test_a_rounded_head_is_read_by_its_proportions_as_before():
    shank = Pos(0, 0, -8) * Cylinder(2.5, 16)
    head = Pos(0, 0, 1.375) * Cylinder(4.75, 2.75)
    head = fillet(head.edges().sort_by(Axis.Z)[-1:], 1.5)
    reading = read_shape(shank + head, Kind.SCREW)
    assert reading.head_guess is Head.BUTTON
    assert (reading.head_standard, reading.head_unmatched) == (None, False)


# ---------------------------------------------------------------------------
# A keyed head with its pocket: the outline picks the key table, and the size.
# ---------------------------------------------------------------------------


def test_a_flat_button_head_with_its_pocket_takes_the_button_key_and_size():
    # Read as a socket head, its 3 mm key would name M4 (ISO 4762's 3 mm key),
    # and the drive would outrank the shank's M5: the wrong size.
    reading = read_shape(screw(5.0, 9.5, 2.75, pocket=3.0), Kind.SCREW)
    assert reading.head is Head.BUTTON
    assert reading.drive_af == pytest.approx(3.0)
    assert (reading.size.designation, reading.size_from_drive) == ("M5", True)
    assert reading.head_standard == "ISO 7380-1"


def test_a_socket_head_with_its_pocket_is_still_a_socket_head():
    reading = read_shape(screw(5.0, 8.5, 5.0, pocket=4.0), Kind.SCREW)
    assert (reading.head, reading.size.designation) == (Head.SOCKET, "M5")
