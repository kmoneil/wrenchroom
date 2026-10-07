"""Sockets and Torx recesses drawn at their standards' size, a little over the key (issue #82).

A key goes into a recess, so the recess is always a little larger than its key, as
the standards allow: ISO 4762 (and ISO 7380-1 and ISO 10642 with it) draws a 2.5 mm
key's socket 2.52 to 2.58, ASME B18.3 a 5/32 in key's 5/32 to 0.1587 in. bd_warehouse
draws every socket at its standard's most, and 2.58 was "no tool's size: the
largest that fits, hex-key-2.5, is 0.08 smaller". A socket in its key's band takes
the key; one drawn up to 0.15 past it, loosely, takes it with a note. A Torx
recess's point to point, given as across_flats, picks its size by ISO 10664's
gauges in the same way.
"""

from itertools import pairwise

import pytest
from bd_warehouse.fastener import ButtonHeadScrew, CounterSunkScrew
from build123d import Box, Cone, Cylinder, Pos, Rot

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.detect import describe, read_name, read_shape, shows_drive
from wrenchroom.fasteners import (
    BUTTON_KEY_AF,
    RECESS_AF_MAX,
    RECESS_LOOSE_MM,
    TORX_RECESS_A,
    Head,
    Kind,
    in_recess_band,
    loosely_fits,
)
from wrenchroom.report import Verdict
from wrenchroom.tools.hex_keys import ASME_B18_3, HEX_KEYS, ISO_2936
from wrenchroom.tools.sizes import inch_mm, is_inch
from wrenchroom.tools.torx_keys import ISO_10664

# ---------------------------------------------------------------------------
# The tables.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "most"),
    [
        (1.5, 1.58),  # ISO 4762:2004 (1997 said 1.56)
        (2.5, 2.58),  # ISO 7380-1's M4, as bd_warehouse draws it
        (4.0, 4.095),
        (10.0, 10.175),
        (19.0, 19.275),
        (1.3, 1.36),  # ISO 10642's M2
        (inch_mm("5/32"), 0.1587 * 25.4),  # ASME B18.3's J max
        (inch_mm("3/4"), 0.7570 * 25.4),
    ],
)
def test_a_socket_may_be_drawn_up_to_its_standards_most(key, most):
    assert RECESS_AF_MAX[key] == pytest.approx(most)
    assert in_recess_band(key, key)  # never smaller than the key, and the key itself is in
    assert in_recess_band(most, key)
    assert not in_recess_band(key - 0.01, key)
    assert not in_recess_band(most + 0.01, key)
    assert loosely_fits(most + RECESS_LOOSE_MM, key)
    assert not loosely_fits(most + RECESS_LOOSE_MM + 0.01, key)


def test_every_key_has_its_socket_and_no_two_of_a_system_overlap():
    assert set(RECESS_AF_MAX) == set(HEX_KEYS)
    reaching = []
    for keys in (ISO_2936, ASME_B18_3):
        ordered = sorted(keys)
        assert len(ordered) > 12  # a vacuity guard: 14 metric keys, 19 inch
        for key, after in pairwise(ordered):
            assert key < RECESS_AF_MAX[key] < after, key  # a band, then the next key
            if RECESS_AF_MAX[key] + RECESS_LOOSE_MM >= after:
                reaching.append((key, after))
    # Loose, only the 1.3's socket reaches past the next key's size (to 1.51), where
    # a 1.5 exactly is that key's first.
    assert reaching == [(1.3, 1.5)]


def test_every_torx_recess_holds_its_own_nominal_and_no_other():
    bands = list(TORX_RECESS_A.items())
    assert len(bands) == 12  # a vacuity guard: T6 to T55
    for (size, (least, most)), (_, (next_least, _)) in pairwise(bands):
        assert least < most < next_least, size
    for size, key in ISO_10664.items():
        least, most = TORX_RECESS_A[size]
        assert least <= key.point_to_point <= most, size


# ---------------------------------------------------------------------------
# The issue's two screws, checked.
# ---------------------------------------------------------------------------


def _in_a_plate(screw, sunk=False):
    plate = Pos(0, 0, -5) * Box(60, 60, 10) - Cylinder(3.0, 30)
    if sunk:
        plate -= Pos(0, 0, -1.6) * Cone(1.6, 4.8, 3.21)
    return Assembly([Part("a_screw", screw), Part("a_plate", plate)])


def test_bd_warehouse_s_button_head_takes_its_key_with_nothing_to_say():
    screw = ButtonHeadScrew(size="M4-0.7", length=12, fastener_type="iso7380_1", simple=True)
    (result,) = check(_in_a_plate(screw), Config(), kit="full").results
    assert (result.verdict, result.tool, result.notes) == (Verdict.TURNS, "hex-key-2.5", ())
    assert result.fastener.drive_af == pytest.approx(2.58)


def test_bd_warehouse_s_countersunk_head_takes_its_key_with_a_note():
    screw = CounterSunkScrew(size="M4-0.7", length=12, fastener_type="iso10642", simple=True)
    (result,) = check(_in_a_plate(screw, sunk=True), Config(), kit="full").results
    assert (result.verdict, result.tool) == (Verdict.TURNS, "hex-key-2.5")
    assert result.notes == (
        "socket drawn loose: 2.60 across flats, 0.02 past the most the standards allow a "
        "2.5 key's (2.58); taken as size 2.5",
    )


def _socket_head(af):
    return Pos(0, 0, -10) * Cylinder(3, 20) + Pos(0, 0, 3) * Cylinder(5, 6) - hex_prism(af, 3.01, 3)


@pytest.mark.parametrize(
    ("af", "tool", "loose"),
    [
        (4.0, "hex-key-4", False),  # the key's own size
        (4.095, "hex-key-4", False),  # ISO 4762's most
        (4.2, "hex-key-4", True),  # past it, loosely
        (5.14, "hex-key-5", False),
        (5.25, "hex-key-5", True),
    ],
)
def test_a_socket_takes_the_largest_key_it_fits(af, tool, loose):
    (result,) = check(Assembly([Part("screw", _socket_head(af))]), Config(), kit="full").results
    assert (result.verdict, result.tool) == (Verdict.TURNS, tool)
    assert bool(result.notes) is loose


def test_where_two_keys_fit_loosely_the_larger_goes_in():
    # A socket 4.12 across, its thread unknown (a 6.2 shank is no standard size):
    # loosely both the 4 mm key's (to 4.095) and the 5/32 in's (to 4.031). The
    # larger key, 4 mm, grips: the issue's largest key that fits.
    screw = Pos(0, 0, -10) * Cylinder(3.1, 20) + Pos(0, 0, 3) * Cylinder(5, 6)
    screw -= hex_prism(4.12, 3.01, 3)
    (result,) = check(Assembly([Part("screw", screw)]), Config(), kit="full").results
    assert result.fastener.size is None
    assert (result.verdict, result.tool) == (Verdict.TURNS, "hex-key-4")
    assert "past the most the standards allow a 4 key's (4.095)" in result.notes[0]


def test_a_socket_drawn_too_loose_names_the_key_that_fits_nearest():
    (result,) = check(Assembly([Part("screw", _socket_head(4.4))]), Config(), kit="full").results
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == (
        "4.40 mm across flats is no tool's size: the largest that fits, hex-key-4, is 0.40 "
        "smaller; set across_flats: or tool: in the sidecar"
    )


def test_a_socket_at_another_systems_key_keeps_to_its_own_thread_first():
    # 5/32 in's socket runs to 4.031, which a 4 mm key's covers: a 4.0 socket is the
    # 4 mm key's (its exact size), an M5's or not, whatever 5/32's band says.
    rule = {"parts": "screw", "kind": "screw", "head": "socket", "size": "M5"}
    config = Config.from_dict({"fasteners": [{**rule, "across_flats": 4.0}]})
    (result,) = check(Assembly([Part("screw", _socket_head(4.0))]), config, kit="full").results
    assert (result.tool, result.notes) == ("hex-key-4", ())


# ---------------------------------------------------------------------------
# Detection reads a socket's size through its standard's band.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("size", ["M3-0.5", "M4-0.7", "M5-0.8", "M6-1", "M8-1.25", "M10-1.5"])
def test_bd_warehouse_s_button_heads_are_sized_by_their_sockets(size):
    # Each socket is drawn at ISO 7380-1's most, and the shank at the minor diameter,
    # which for M5 lands on #8: the socket settles it.
    screw = ButtonHeadScrew(size=size, length=20, fastener_type="iso7380_1", simple=True)
    reading = read_shape(screw, Kind.SCREW)
    thread = size.split("-")[0]
    assert (reading.head, reading.size.designation, reading.size_from_drive) == (
        Head.BUTTON,
        thread,
        True,
    )
    assert in_recess_band(reading.drive_af, BUTTON_KEY_AF[thread])


def test_a_loose_socket_is_a_guess_its_name_outranks():
    screw = CounterSunkScrew(size="M4-0.7", length=12, fastener_type="iso10642", simple=True)
    reading = read_shape(screw, Kind.SCREW)
    assert (reading.size.designation, reading.size_from_drive, reading.size_from_band) == (
        "M4",
        False,
        True,
    )


def test_the_basis_says_a_size_from_a_loose_socket_is_a_guess():
    screw = CounterSunkScrew(size="M4-0.7", length=12, fastener_type="iso10642", simple=True)
    found = describe(Part("a_screw", screw), read_name("a_screw"))
    assert "M4 by its socket alone, drawn past its standard's most" in found.basis
    assert found.size_guessed


def test_a_loose_socket_outranks_a_shank_thinner_than_any_size_it_allows():
    # bd_warehouse's "ISO 10642" M5 (DIN 7991's): its socket, 3.10, is loosely a 3
    # mm key's, which only an M5 countersunk head takes; its shank, drawn at the
    # minor diameter (4.13), lands on #8 (4.17). A shank is never thicker than its
    # thread: #8, thinner than M5, is a thread drawn small, and the socket stands.
    screw = CounterSunkScrew(size="M5-0.8", length=12, fastener_type="iso10642", simple=True)
    reading = read_shape(screw, Kind.SCREW)
    assert reading.drive_af == pytest.approx(3.1)
    assert (reading.size.designation, reading.size_from_band) == ("M5", True)


def test_a_candidate_name_is_taken_on_a_socket_drawn_at_its_standards_most():
    rotated = Rot(0, 90, 0) * _socket_head(4.095)
    assert shows_drive(read_shape(rotated, Kind.SCREW))
    assert not shows_drive(read_shape(_socket_head(4.4), Kind.SCREW))


# ---------------------------------------------------------------------------
# Torx: a recess's point to point, given, picks the size.
# ---------------------------------------------------------------------------


def _torx_head():
    return (
        Pos(0, 0, 3) * Cylinder(8, 6)
        - Pos(0, 0, 4.5) * Cylinder(3.3, 3.01)
        + Pos(0, 0, -8) * Cylinder(4, 16)
    )


def _torx(size, recess, **rule):
    rule = {"parts": "screw", "kind": "screw", "head": "torx", "size": size, **rule}
    if recess is not None:
        rule["across_flats"] = recess
    model = Assembly([Part("screw", _torx_head()), Part("plate", Pos(0, 0, -5) * Box(90, 90, 10))])
    config = Config.from_dict({"fasteners": [rule], "checks": {"detect": False}})
    (result,) = check(model, config, kit="full").results
    return result


@pytest.mark.parametrize(
    ("size", "recess", "tool"),
    [
        ("M6", None, "torx-key-T30"),  # by its thread, as before
        ("M6", 5.6, "torx-key-T30"),  # its recess agrees
        ("M8", 6.75, "torx-key-T40"),  # an M8 pan head for T40, where ISO 14583 says T45
        ("M8", 6.673, "torx-key-T40"),  # the GO gauge's least
        ("M8", 6.814, "torx-key-T40"),  # the NO GO gauge's most
    ],
)
def test_a_torx_recess_picks_its_size(size, recess, tool):
    result = _torx(size, recess)
    assert (result.verdict, result.tool, result.notes) == (Verdict.TURNS, tool, ())


def test_a_torx_recess_drawn_loose_takes_its_size_with_a_note():
    result = _torx("M8", 6.9)
    assert (result.verdict, result.tool) == (Verdict.TURNS, "torx-key-T40")
    assert result.notes == (
        "Torx recess drawn loose: 6.90 point to point, 0.09 past the most ISO 10664 allows "
        "a T40 (6.814); taken as T40",
    )


def test_a_torx_recess_no_size_holds_is_not_covered():
    result = _torx("M8", 7.2)
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == (
        "7.20 mm point to point is no Torx recess's size; the largest that fits, T40; "
        "set tool: in the sidecar"
    )


def test_a_rule_s_torx_key_is_held_to_its_recess():
    # tool: torx-key-T40 on an M8 fits a T40 recess; the thread alone would say T45.
    assert _torx("M8", 6.75, tool="torx-key-T40").verdict is Verdict.TURNS
    misfit = _torx("M8", 6.75, tool="torx-key-T30")
    assert misfit.verdict is Verdict.NOT_COVERED
    assert misfit.reason.startswith("its tool: torx-key-T30 is T30, but")


def test_inch_keys_are_inch():
    assert all(is_inch(key) for key in ASME_B18_3)
