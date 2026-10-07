"""Screws and nuts below M3, and inch #0 to #3 (issue #83).

M2 and M2.5 are everywhere in printers, electronics and small mechanisms, and
were not covered: "M2 is outside the sizes the kit covers (M3 to M24)", even
with the full kit, which held the keys. The tables now carry M1.6 to M2.5 and
#0 to #3, each row read from its standard; the full kit holds the small
spanners, sockets, nut drivers, Torx keys and PH0 driver they take, and
metric-home stays the spec's. Where a standard has no such head, the reason
names the standard, not the kit.
"""

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.detect import describe, read_name
from wrenchroom.fasteners import (
    HEX_AF_MIN,
    PHILLIPS_NUMBER,
    TORX_SIZE,
    Head,
    Size,
    hex_key_af,
    no_such_head,
    spanner_af,
)
from wrenchroom.report import Verdict
from wrenchroom.tools.kits import FULL, IMPERIAL_HOME, METRIC_HOME
from wrenchroom.tools.sizes import inch_mm
from wrenchroom.tools.spanners import SMALL_OPEN_WIDTHS, spanner_for

# ---------------------------------------------------------------------------
# The rows, as the standards give them.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "size", "key"),
    [
        (Head.SOCKET, "M1.6", 1.5),  # ISO 4762:2004
        (Head.SOCKET, "M2", 1.5),
        (Head.SOCKET, "M2.5", 2.0),
        (Head.FLAT, "M2", 1.3),  # ISO 10642:2019
        (Head.FLAT, "M2.5", 1.5),
        (Head.SOCKET, "#0", inch_mm("0.050")),  # ASME B18.3
        (Head.SOCKET, "#1", inch_mm("1/16")),
        (Head.SOCKET, "#3", inch_mm("5/64")),
        (Head.BUTTON, "#0", inch_mm("0.035")),
        (Head.BUTTON, "#1", inch_mm("0.050")),
        (Head.BUTTON, "#3", inch_mm("1/16")),
        (Head.FLAT, "#0", inch_mm("0.035")),
        (Head.FLAT, "#3", inch_mm("1/16")),
    ],
)
def test_a_small_keyed_head_takes_its_standards_key(head, size, key):
    assert hex_key_af(head, Size.parse(size)) == pytest.approx(key)


@pytest.mark.parametrize(
    ("size", "af", "least"),
    [
        ("M1.6", 3.2, 3.02),  # ISO 4032:2012, grade A
        ("M2", 4.0, 3.82),
        ("M2.5", 5.0, 4.82),
        ("#0", inch_mm("5/32"), 0.150 * 25.4),  # ASME B18.6.3
        ("#1", inch_mm("5/32"), 0.150 * 25.4),
        ("#2", inch_mm("3/16"), 0.180 * 25.4),
        ("#3", inch_mm("3/16"), 0.180 * 25.4),
    ],
)
def test_a_small_nut_takes_its_standards_spanner(size, af, least):
    assert spanner_af(Size.parse(size)) == pytest.approx(af)
    assert HEX_AF_MIN[spanner_af(Size.parse(size))] == pytest.approx(least)


def test_small_torx_and_phillips():
    assert (TORX_SIZE["M2"], TORX_SIZE["M2.5"]) == ("T6", "T8")  # ISO 14579 and kin
    assert [PHILLIPS_NUMBER[s] for s in ("M1.6", "M2", "M2.5", "#0", "#1", "#3")] == [
        0,
        0,
        1,
        0,
        0,
        1,
    ]


@pytest.mark.parametrize(
    ("head", "size", "reason"),
    [
        (Head.BUTTON, "M2", "ISO 7380-1 has no M2 button head"),  # it starts at M3
        (Head.BUTTON, "M2.5", "ISO 7380-1 has no M2.5 button head"),
        (Head.FLAT, "M1.6", "ISO 10642 has no M1.6 flat head"),  # it starts at M2
        (Head.TORX, "M1.6", "ISO 14579 has no M1.6 torx head"),
        (Head.SOCKET, "#12", "ASME B18.3 has no #12 socket head"),
        (Head.SHOULDER, "M3", "ISO 7379 has no M3 shoulder head"),
        (Head.SHOULDER, "1/4", "no standard key for a 1/4 shoulder head"),  # no inch table
        (Head.TORX, "1/4", "no Torx size for a 1/4 head"),
    ],
)
def test_a_head_its_standard_lacks_names_the_standard(head, size, reason):
    assert no_such_head(head, Size.parse(size)) == reason


# ---------------------------------------------------------------------------
# The kits.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool",
    [
        "hex-key-1.3",
        "hex-key-0.035in",
        "spanner-3.2",
        "spanner-4",
        "spanner-4.5",
        "spanner-5",
        "socket-3.2",
        "socket-5",
        "nut-driver-4",
        "nut-driver-5",
        "torx-key-T6",
        "torx-key-T8",
        "driver-ph0",
    ],
)
def test_the_full_kit_holds_the_small_tools_and_the_home_kits_do_not(tool):
    assert FULL.holds(tool)
    assert not METRIC_HOME.holds(tool)
    assert not IMPERIAL_HOME.holds(tool)


def test_the_home_kits_keep_their_small_keys():
    assert METRIC_HOME.holds("hex-key-1.5")  # an M2 socket head's, as before
    assert IMPERIAL_HOME.holds("hex-key-0.050in")  # a #0's
    assert METRIC_HOME.spanners[0] == "5.5"  # the spec's 5.5 to 19


@pytest.mark.parametrize(
    ("af", "width"), [(3.2, 10.0), (4.0, 12.5), (4.5, 12.5), (5.0, 16.5), (13.0, 2.09 * 13 + 1.9)]
)
def test_a_small_open_end_is_as_wide_as_the_makers(af, width):
    # The fit to 8 to 24 mm heads runs narrow below 5.5: the makers' own stand.
    assert spanner_for(af).open_width == pytest.approx(width)
    assert set(SMALL_OPEN_WIDTHS) == {3.2, 4.0, 4.5, 5.0}


# ---------------------------------------------------------------------------
# Checked.
# ---------------------------------------------------------------------------


def _plate(hole):
    return Part("plate", Pos(0, 0, -5) * Box(80, 80, 10) - Cylinder(hole, 12))


def _m2_socket():
    """ISO 4762 M2x6: head 3.8 by 2, a 1.5 socket 1 deep."""
    head = Pos(0, 0, 1) * Cylinder(1.9, 2) - hex_prism(1.5, 1.01, 1)
    return head + Pos(0, 0, -3) * Cylinder(1.0, 6)


def _nut(d, af, m):
    return hex_prism(af, m) - Cylinder(d / 2, 4 * m)


def _on_a_stud(d, af, m):
    stud = Pos(0, 0, 2.5) * Cylinder(d / 2, 15)
    return Assembly([_plate(d / 2 + 0.2), Part("stud", stud), Part("nut", _nut(d, af, m))])


def test_an_m2_socket_head_turns_with_the_home_kits_key():
    model = Assembly([_plate(1.1), Part("M2x6 SHCS", _m2_socket())])
    (result,) = check(model, Config()).results
    assert (result.fastener.size.designation, result.fastener.head) == ("M2", Head.SOCKET)
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "hex-key-1.5",
        "driver straight in",
    )


@pytest.mark.parametrize(
    ("size", "d", "af", "m"), [("M1.6", 1.6, 3.2, 1.3), ("M2", 2.0, 4.0, 1.6), ("M2.5", 2.5, 5, 2)]
)
def test_a_small_nut_turns_with_the_full_kit_and_the_home_kit_says_what_to_get(size, d, af, m):
    rule = {"parts": "nut", "kind": "nut", "size": size}
    config = Config.from_dict({"fasteners": [rule]})
    (full,) = check(_on_a_stud(d, af, m), config, kit="full").results
    assert (full.verdict, full.tool, full.how) == (
        Verdict.TURNS,
        f"spanner-{af:g}",
        "ring, full length",
    )
    (home,) = check(_on_a_stud(d, af, m), config).results
    assert home.verdict is Verdict.NOT_COVERED
    assert home.reason.startswith(f"needs spanner-{af:g} or socket-{af:g}")
    assert home.reason.endswith("which kit metric-home does not hold (full has it)")


def test_an_m2_button_head_names_the_standard_that_lacks_it():
    rule = {"parts": "screw", "kind": "screw", "head": "button", "size": "M2"}
    model = Assembly([_plate(1.1), Part("screw", _m2_socket())])
    config = Config.from_dict({"fasteners": [rule], "checks": {"detect": False}})
    (result,) = check(model, config, kit="full").results
    assert (result.verdict, result.reason) == (
        Verdict.NOT_COVERED,
        "ISO 7380-1 has no M2 button head",
    )


def test_an_m2_name_reads_as_a_size_now():
    found = read_name("M2x6 SHCS")
    assert (found.size.designation, found.length_mm, found.not_covered) == ("M2", 6.0, None)


def test_an_m2_socket_is_told_from_an_m1_6_by_its_shank():
    # ISO 4762 gives M1.6 and M2 the same 1.5 key: the shank decides.
    found = describe(Part("cap_screw", _m2_socket()), read_name("cap_screw"))
    assert (found.size.designation, found.drive_af) == ("M2", pytest.approx(1.5))
