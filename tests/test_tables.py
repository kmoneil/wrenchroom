"""The dimension tables hold together: spec examples, cross-references, monotony."""

import pytest

from wrenchroom.fasteners import (
    BUTTON_KEY_AF,
    FLAT_KEY_AF,
    HEX_AF,
    HEX_HEAD_AF,
    IMPERIAL_SIZES,
    METRIC_SIZES,
    SOCKET_KEY_AF,
    Head,
    Size,
    hex_key_af,
    spanner_af,
)
from wrenchroom.tools.hex_keys import ASME_B18_3, HEX_KEYS, ISO_2936
from wrenchroom.tools.sizes import INCH_FLATS, MM_PER_INCH, inch_mm, size_name
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
    assert needed <= set(HEX_KEYS)


def test_every_hex_a_nut_or_head_presents_is_a_spanner_size():
    flats = {size_name(af) for af in (*HEX_AF.values(), *HEX_HEAD_AF.values())}
    sold = {f"{af:g}" for af in range(5, 37)} | {"5.5"} | {f"{s}in" for s in INCH_FLATS}
    assert flats <= sold


def test_key_tables_only_name_known_threads():
    for table in (SOCKET_KEY_AF, BUTTON_KEY_AF, FLAT_KEY_AF, HEX_AF, HEX_HEAD_AF):
        assert set(table) <= set(METRIC_SIZES) | set(IMPERIAL_SIZES)


def test_spanner_af_covers_every_hex_thread():
    for designation in HEX_AF:
        assert spanner_af(Size.parse(designation)) == HEX_AF[designation]


def _by_diameter(table, sizes):
    return [table[d] for d in sorted(set(table) & set(sizes), key=lambda d: sizes[d])]


@pytest.mark.parametrize("sizes", [METRIC_SIZES, IMPERIAL_SIZES], ids=["metric", "inch"])
def test_tables_grow_with_the_thread(sizes):
    for table in (SOCKET_KEY_AF, BUTTON_KEY_AF, FLAT_KEY_AF, HEX_AF, HEX_HEAD_AF):
        values = _by_diameter(table, sizes)
        assert values == sorted(values)
    nuts = _by_diameter(HEX_AF, sizes)
    assert len(set(nuts)) == len(nuts)  # strictly increasing


@pytest.mark.parametrize(
    ("table", "thread", "tool"),
    [
        # ASME B18.3 (Unbrako; fasten.it tables 1A, 2A, 3), read 2026-10-06.
        (SOCKET_KEY_AF, "#10", "5/32"),
        (SOCKET_KEY_AF, "1/4", "3/16"),
        (SOCKET_KEY_AF, "1/2", "3/8"),
        (BUTTON_KEY_AF, "#10", "1/8"),
        (BUTTON_KEY_AF, "1/4", "5/32"),
        (FLAT_KEY_AF, "#10", "1/8"),  # a flat head takes the button head's key
        (FLAT_KEY_AF, "3/4", "1/2"),
        # ASME B18.2.2 and B18.6.3 nuts, B18.2.1 heads.
        (HEX_AF, "#10", "3/8"),
        (HEX_AF, "1/4", "7/16"),
        (HEX_AF, "7/16", "11/16"),
        (HEX_AF, "9/16", "7/8"),
        (HEX_HEAD_AF, "7/16", "5/8"),  # a head and its nut part ways here...
        (HEX_HEAD_AF, "9/16", "13/16"),  # ...and here
        (HEX_HEAD_AF, "3/4", "1-1/8"),
    ],
)
def test_inch_rows_as_read(table, thread, tool):
    assert table[thread] == pytest.approx(inch_mm(tool))


def test_a_head_and_its_nut_take_the_same_spanner_except_where_asme_says():
    shared = set(HEX_AF) & set(HEX_HEAD_AF)
    differ = {size for size in shared if HEX_AF[size] != HEX_HEAD_AF[size]}
    assert differ == {"7/16", "9/16"}
    assert spanner_af(Size.parse("7/16"), head=True) == pytest.approx(inch_mm("5/8"))
    assert spanner_af(Size.parse("7/16")) == pytest.approx(inch_mm("11/16"))


def test_asme_keys_are_self_consistent():
    for key in ASME_B18_3.values():
        assert key.long_mm > key.short_mm
        # Across corners over across flats: 2/sqrt(3) = 1.1547 for a sharp hexagon;
        # the inch rows sit between 1.12 (0.050) and 1.15.
        assert 1.11 <= key.across_corners / key.af < 1.16
        assert key.name.endswith("in")
    five_32 = ASME_B18_3[inch_mm("5/32")]
    assert five_32.across_corners == pytest.approx(0.1774 * MM_PER_INCH)
    assert (five_32.short_mm, five_32.long_mm) == pytest.approx(
        (0.938 * MM_PER_INCH, 2.594 * MM_PER_INCH)
    )
    assert not set(ASME_B18_3) & set(ISO_2936)  # no inch key is a metric key


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
