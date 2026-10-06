"""The dimension tables hold together: spec examples, cross-references, monotony."""

import pytest

from wrenchroom.fasteners import (
    BUTTON_KEY_AF,
    FLAT_KEY_AF,
    HEX_AF,
    METRIC_SIZES,
    SOCKET_KEY_AF,
    Head,
    Size,
    hex_key_af,
    spanner_af,
)
from wrenchroom.tools.hex_keys import ISO_2936
from wrenchroom.tools.sockets import socket_for
from wrenchroom.tools.spanners import spanner_for


@pytest.mark.parametrize(
    ("size", "head", "af"),
    [
        ("M3", Head.SOCKET, 2.5),
        ("M3", Head.BUTTON, 2.0),
        ("M4", Head.SOCKET, 3.0),
        ("M4", Head.BUTTON, 2.5),
        ("M5", Head.SOCKET, 4.0),
        ("M5", Head.BUTTON, 3.0),
        ("M6", Head.SOCKET, 5.0),
        ("M6", Head.BUTTON, 4.0),
        ("M8", Head.SOCKET, 6.0),
        ("M8", Head.BUTTON, 5.0),
        ("M8", Head.FLAT, 5.0),
    ],
)
def test_the_spec_examples_hold(size, head, af):
    assert hex_key_af(head, Size.parse(size)) == af


def test_heads_without_a_hex_key_say_so():
    m6 = Size.parse("M6")
    for head in (Head.HEX, Head.PHILLIPS, Head.SLOTTED, Head.CARRIAGE, Head.TORX):
        assert hex_key_af(head, m6) is None


def test_a_size_outside_a_heads_range_is_none_not_a_guess():
    assert hex_key_af(Head.BUTTON, Size.parse("M24")) is None


def test_every_key_size_a_head_needs_exists_as_a_key():
    needed = set(SOCKET_KEY_AF.values()) | set(BUTTON_KEY_AF.values()) | set(FLAT_KEY_AF.values())
    missing = needed - set(ISO_2936)
    assert not missing


def test_key_tables_only_name_known_threads():
    for table in (SOCKET_KEY_AF, BUTTON_KEY_AF, FLAT_KEY_AF, HEX_AF):
        assert set(table) <= set(METRIC_SIZES)


def test_spanner_af_covers_every_hex_thread():
    for designation in HEX_AF:
        assert spanner_af(Size.parse(designation)) == HEX_AF[designation]


def _by_diameter(table):
    return [table[d] for d in sorted(table, key=lambda d: METRIC_SIZES[d])]


def test_tables_grow_with_the_thread():
    for table in (SOCKET_KEY_AF, BUTTON_KEY_AF, FLAT_KEY_AF, HEX_AF):
        values = _by_diameter(table)
        assert values == sorted(values)
    assert len(set(_by_diameter(HEX_AF))) == len(HEX_AF)  # strictly increasing


def test_iso_2936_keys_are_self_consistent():
    for key in ISO_2936.values():
        assert key.long_mm > key.short_mm
        assert key.across_corners > key.af
        # e/af for a hexagon is 2/sqrt(3) = 1.1547 nominal, less manufacturing
        # undercut; the standard's rows sit between 1.12 (the 1.5 mm key) and 1.14.
        assert 1.11 <= key.across_corners / key.af < 1.16
        assert key.radius == key.across_corners / 2


def test_iso_2936_against_the_standard_rows_read_on_2026_10_06():
    assert ISO_2936[5.0].long_mm == 85.0
    assert ISO_2936[5.0].short_mm == 33.0
    assert ISO_2936[1.5].short_mm == 15.5
    assert ISO_2936[10.0].long_mm == 122.0


def test_spanner_and_socket_approximations_behave():
    small, large = spanner_for(8.0), spanner_for(19.0)
    assert small.length < large.length
    assert small.stubby_length < small.length
    assert spanner_for(10.0).length == 135.0  # the prototype's formula, pinned
    assert socket_for(10.0).outer_radius == pytest.approx(7.2)
    assert socket_for(5.5).length == 25.0  # the floor
