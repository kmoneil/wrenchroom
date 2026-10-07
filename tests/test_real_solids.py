"""Fastener solids as makers and bd_warehouse draw them (issue #81).

A maker's model chamfers every edge, countersinks a socket's mouth and leaves the
drill's point at its bottom, and chamfers the tip: cones everywhere, and none of
them a countersunk head. A button head is a dome, often with no cylinder at all
(bd_warehouse revolves one profile), and its only flat face may be a ring round
the socket, smaller than the tip's end. Detection used to call any cone a
countersunk head, overriding the name, and the check used to take the end with
the larger flat face for the head, so a domed button head was keyed from inside
the part it screws into. Expected values come from the standards' tables, never
from the reader's own output.
"""

import math
import sys
from pathlib import Path

import pytest
from bd_warehouse.fastener import ButtonHeadScrew, CounterSunkScrew, SocketHeadCapScrew
from build123d import Box, Cone, Cylinder, Pos, Rot

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.detect import describe, read_name
from wrenchroom.detect.geometry import read_shape, wide_end
from wrenchroom.fasteners import (
    BUTTON_KEY_AF,
    FLAT_KEY_AF,
    HEAD_OUTLINE,
    SOCKET_KEY_AF,
    Head,
    Kind,
)
from wrenchroom.report import Verdict

sys.path.insert(0, str(Path(__file__).parent / "golden"))
from parts import (  # the bench's builders, which its cells use too
    VENDOR_BUTTON,
    VENDOR_FLAT,
    VENDOR_SOCKET,
    vendor_button_screw,
    vendor_flat_screw,
    vendor_socket_screw,
)

S = Kind.SCREW


# ---------------------------------------------------------------------------
# Makers' cones are not countersunk heads.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("size", list(VENDOR_SOCKET))
def test_a_makers_socket_head_is_a_socket_head(size):
    reading = read_shape(vendor_socket_screw(size), S)
    assert (reading.head, reading.size.designation) == (Head.SOCKET, size)
    assert reading.drive_af == pytest.approx(SOCKET_KEY_AF[size])
    # Its chamfers are part of its outline: drawn to ISO 4762's (dk, k), it fits it.
    assert reading.head_standard == "ISO 4762"
    assert reading.head_drawn == pytest.approx(VENDOR_SOCKET[size][1:3])


@pytest.mark.parametrize("size", list(VENDOR_BUTTON))
def test_a_makers_domed_button_head_is_a_button_head(size):
    reading = read_shape(vendor_button_screw(size), S)
    assert (reading.head, reading.size.designation) == (Head.BUTTON, size)
    assert reading.drive_af == pytest.approx(BUTTON_KEY_AF[size])
    assert reading.head_drawn == pytest.approx(VENDOR_BUTTON[size][1:3])


@pytest.mark.parametrize("size", list(VENDOR_FLAT))
def test_a_makers_countersunk_head_is_still_countersunk(size):
    reading = read_shape(vendor_flat_screw(size), S)
    assert (reading.head, reading.size.designation) == (Head.FLAT, size)
    assert reading.drive_af == pytest.approx(FLAT_KEY_AF[size])


def _coned(inner, outer, half_deg, pocket=True):
    """An M6 under a 12 mm head: a cone under the head, from ``inner`` out to ``outer``.

    A rim band 12 across and 1 high tops it, with a hex socket a 4 mm key fits;
    the cone's half angle is ``half_deg``, so its height is set by its radii. A
    cone starting out from the shank leaves a flat under the head inside it, one
    stopping short of the rim a flat step up to it.
    """
    height = (outer - inner) / math.tan(math.radians(half_deg))
    head = Pos(0, 0, height / 2) * Cone(inner, outer, height)
    head += Pos(0, 0, height + 0.5) * Cylinder(6.0, 1.0)
    screw = head + Pos(0, 0, -10) * Cylinder(3.0, 20)
    return screw - hex_prism(4.0, 2.01, height - 1) if pocket else screw


@pytest.mark.parametrize(
    ("inner", "outer", "half_deg", "countersunk"),
    [
        (3.0, 6.0, 45.0, True),  # ISO 10642's: shank to rim at 90 degrees
        (3.0, 6.0, 41.0, True),  # ASME B18.3's 82 degrees
        (3.0, 6.0, 60.0, True),  # a 120 degree head
        (4.1, 6.0, 45.0, True),  # from just past the shank: 63% of the way down
        (4.3, 6.0, 45.0, False),  # a big chamfer under a head: 57% of the way
        (3.0, 5.3, 45.0, False),  # under a wider head: it stops short of the rim
        (3.0, 6.0, 30.0, False),  # too steep for a head: a taper
        (3.0, 6.0, 70.0, False),  # too flat for a head: a chamfer
    ],
)
def test_only_the_heads_own_cone_is_a_countersink(inner, outer, half_deg, countersunk):
    reading = read_shape(_coned(inner, outer, half_deg), S)
    assert reading.drive_af == pytest.approx(4.0)
    assert (reading.head is Head.FLAT) is countersunk


def test_a_cone_facing_in_is_never_a_countersink():
    # A socket's drill point and countersunk mouth face the axis: the solid is
    # outside them. One as wide as the head and as steep as a countersink is
    # still a pocket's: a plain head with a 90 degree conical pocket in it.
    head = Pos(0, 0, 3) * Cylinder(6.0, 6) + Pos(0, 0, -10) * Cylinder(3.0, 20)
    pocket = Pos(0, 0, 4.5) * Cone(2.9, 5.9, 3.01)
    reading = read_shape(head - pocket, S)
    assert reading.head is not Head.FLAT
    assert reading.head_guess is not Head.FLAT


# ---------------------------------------------------------------------------
# bd_warehouse's ISO heads.
# ---------------------------------------------------------------------------

BD_SIZES = ["M3-0.5", "M4-0.7", "M5-0.8", "M6-1", "M8-1.25", "M10-1.5", "M12-1.75"]


@pytest.mark.parametrize("size", BD_SIZES)
def test_bd_warehouse_iso_4762_reads_as_a_socket_head(size):
    screw = SocketHeadCapScrew(size=size, length=20, fastener_type="iso4762", simple=True)
    reading = read_shape(screw, S)
    thread = size.split("-")[0]
    assert (reading.head, reading.size.designation) == (Head.SOCKET, thread)
    assert reading.drive_af == pytest.approx(SOCKET_KEY_AF[thread])


@pytest.mark.parametrize("size", BD_SIZES)
def test_bd_warehouse_iso_7380_reads_as_a_button_head(size):
    # Its head is one revolved profile: no cylinder, so the widest cylinder (its
    # shank) used to be taken for the head, 20 long, and the head called a socket.
    screw = ButtonHeadScrew(size=size, length=20, fastener_type="iso7380_1", simple=True)
    reading = read_shape(screw, S)
    thread = size.split("-")[0]
    assert reading.head is Head.BUTTON
    assert reading.head_drawn == pytest.approx(HEAD_OUTLINE[Head.BUTTON][thread], rel=0.01)


@pytest.mark.parametrize("size", BD_SIZES)
def test_bd_warehouse_iso_10642_reads_as_countersunk(size):
    screw = CounterSunkScrew(size=size, length=20, fastener_type="iso10642", simple=True)
    assert read_shape(screw, S).head is Head.FLAT


# ---------------------------------------------------------------------------
# The name's keyed head outranks the outline's.
# ---------------------------------------------------------------------------


def detected(name, shape):
    return describe(Part(name, shape), read_name(name))


@pytest.mark.parametrize(
    ("name", "shape", "head"),
    [
        ("M3x16 BHCS", lambda: vendor_button_screw("M3"), Head.BUTTON),
        ("M3x8 FHCS", lambda: vendor_flat_screw("M3"), Head.FLAT),
        ("M3x12 SHCS", lambda: vendor_socket_screw("M3"), Head.SOCKET),
    ],
)
def test_where_name_and_solid_agree_it_is_sure(name, shape, head):
    found = detected(name, shape())
    assert (found.head, found.size.designation, found.confidence) == (head, "M3", "high")
    assert "outline" not in found.basis


def test_the_names_button_stands_over_a_socket_heads_outline():
    # The solid's pocket says a key goes in; which head it is in is the outline's
    # guess, and the name outranks a guess. They disagree, so a person settles it.
    found = detected("M3x16 BHCS", vendor_socket_screw("M3"))
    assert found.head is Head.BUTTON
    assert found.drive_af == pytest.approx(2.5)  # the key the solid takes, whatever its head
    assert found.basis == (
        "noun 'bhcs', M3x16; solid: a socket head's outline (the name's button stands), "
        "2.5 across flats"
    )
    assert found.confidence == "low"
    # The key's size says the thread only through its head's table, here in
    # doubt (ISO 7380-1's 2.5 is M4's): the name's M3 stands.
    assert found.size.designation == "M3"


def test_the_names_socket_stands_over_a_countersink():
    found = detected("M3x16 SHCS", vendor_flat_screw("M3"))
    assert (found.head, found.confidence) == (Head.SOCKET, "low")
    assert "a flat head's outline (the name's socket stands)" in found.basis


def test_with_no_drive_the_names_head_stands_over_the_outline_too():
    # No pocket: the outline is only head_guess, which the name outranks, and
    # a countersink that says otherwise is still said.
    found = detected("button head screw M6", _coned(3.0, 6.0, 45.0, pocket=False))
    assert found.head is Head.BUTTON
    assert "a flat head's outline (the name's button stands)" in found.basis


def test_a_shoulder_screw_is_one_by_its_name_whatever_its_outline():
    # ISO 7379's head looks like a socket head; only the name tells (issue #40).
    found = detected("M6 shoulder bolt", vendor_socket_screw("M6"))
    assert found.head is Head.SHOULDER
    assert "outline" not in found.basis


def test_a_drive_still_outranks_a_name_that_says_another_drive():
    # A hex bolt by name with a hex socket in its solid: the drive is evidence,
    # not an outline, and wins as before; the name is said.
    found = detected("hex bolt M4x12", vendor_socket_screw("M4"))
    assert found.head is Head.SOCKET
    assert "(the name says hex)" in found.basis


# ---------------------------------------------------------------------------
# The head end is the wide end.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("along", "out", "end"),
    [
        ((0, 3, -12, -12), (5, 5, 1.5, 1), 1),  # head up
        ((0, -3, 12, 12), (5, 5, 1.5, 1), -1),  # head down
        ((0, 10, 0, 10), (3, 3, 3, 3), 0),  # a plain pin
        ((0, 1, 9, 10), (5, 5, 5, 5), 0),  # wide both ends: a spool
        ((), (), 0),
    ],
)
def test_the_wide_end(along, out, end):
    assert wide_end(along, out) == end


def _domed_in_plate(turn=None):
    """An M3 domed button through a plate, its head on the plate's top face, open above."""
    plate = Pos(0, 0, -5) * Box(60, 60, 10) - Cylinder(1.7, 30)
    screw = vendor_button_screw("M3", length=8.0)
    parts = [Part("screw", screw), Part("plate", plate)]
    if turn is not None:
        parts = [Part(p.name, turn * p.shape) for p in parts]
    return Assembly(parts)


RULE = {"parts": "screw", "kind": "screw", "head": "button", "size": "M3"}


@pytest.mark.parametrize("turn", [None, Rot(180, 0, 0), Rot(0, 90, 0), Rot(37, -61, 12)], ids=str)
@pytest.mark.parametrize("engine", ["mesh", "exact"])
def test_a_domed_head_is_keyed_from_its_own_end(turn, engine):
    # The tip's end face (5.2 mm^2) is larger than the dome's ring (2.2): the
    # larger-flat rule put the head at the tip, and the key came up through the
    # plate. Keyed from the dome, it goes straight in.
    config = Config.from_dict({"fasteners": [RULE]})
    (result,) = check(_domed_in_plate(turn), config, engine=engine).results
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "hex-key-2",
        "driver straight in",
    )
    up = (0.0, 0.0, 1.0) if turn is None else tuple((turn * Pos(0, 0, 1)).position)
    assert result.axis == pytest.approx(up, abs=1e-6)


def test_a_screw_alike_at_both_ends_is_not_covered():
    pin = Assembly([Part("screw", Cylinder(3.0, 20))])
    config = Config.from_dict({"fasteners": [{**RULE, "size": "M6"}]})
    (result,) = check(pin, config).results
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == "cannot tell the head end: both ends look alike"


def test_the_seat_is_the_top_of_the_dome():
    config = Config.from_dict({"fasteners": [RULE]})
    (result,) = check(_domed_in_plate(), config).results
    assert result.seat == pytest.approx((0.0, 0.0, VENDOR_BUTTON["M3"][2]), abs=1e-6)
