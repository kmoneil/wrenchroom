"""Custom tools in the sidecar, in the shape of the built-in tables (spec 5.3).

The escape hatch for a tool wrenchroom doesn't ship. A ``tools:`` list in the
sidecar describes each by the numbers the built-in tables hold for its kind; it
joins whatever kit the check uses, is tried after the kit's own tools of its
kind and size, and a rule's ``tool:`` may name it outright.

The worked cases: an M16 nut under metric-home, which holds no 24 mm spanner,
turned by a sidecar's shop spanner; and an M6 socket head under a slab 30 over
it, which ISO 2936's 5 mm key can't reach any way, turned by a short-arm key.
"""

import itertools
import math

import pytest
from build123d import Box, Cylinder, Pos
from click.testing import CliRunner

from fastener_models import hex_prism, socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config, ConfigError
from wrenchroom.report import Verdict
from wrenchroom.tools.custom import (
    NEAR_MM,
    TABLE_SIZES,
    CustomDriver,
    CustomKey,
    CustomNutDriver,
    CustomSocket,
    CustomSpanner,
    parse_tools,
    tool_af,
)
from wrenchroom.tools.hex_keys import HEX_KEYS
from wrenchroom.tools.nut_drivers import NUT_DRIVERS
from wrenchroom.tools.sizes import FLATS, SAME_MM, size_mm, size_name
from wrenchroom.tools.sockets import socket_for
from wrenchroom.tools.spanners import spanner_for
from wrenchroom.tools.torx_keys import ISO_10664

SHOP = {"name": "shop-spanner-24", "type": "spanner", "across_flats": 24, "length": 300}
STUBBY = {"name": "stubby-key-5", "type": "hex-key", "across_flats": 5, "long": 60, "short": 20}


def plate():
    return Part("plate", Pos(0, 0, -5) * Box(400, 400, 10))


def run(parts, rules, tools=(), kit="full", engine="mesh"):
    return reported(parts, rules, tools, kit, engine).results


def reported(parts, rules, tools=(), kit="full", engine="mesh"):
    config = Config.from_dict({"fasteners": list(rules), "tools": list(tools)})
    return check(Assembly(parts), config, kit=kit, engine=engine)


# ---------------------------------------------------------------------------
# Reading them: every kind, with its defaults.
# ---------------------------------------------------------------------------


def test_a_hex_key_reads_with_its_hexagon_s_corners():
    (key,) = parse_tools([STUBBY], "tools").tools
    assert key == CustomKey("stubby-key-5", "hex-key", "5", 5.0, 60.0, 20.0, 10 / math.sqrt(3))
    assert key.radius == pytest.approx(5 / math.sqrt(3))
    given = {**STUBBY, "across_corners": 5.6}
    assert parse_tools([given], "tools").tools[0].radius == 2.8


def test_a_torx_key_takes_iso_10664_s_section_for_its_size():
    entry = {"name": "long-t30", "type": "torx-key", "size": "T30", "long": 200, "short": 30}
    (key,) = parse_tools([entry], "tools").tools
    assert (key.size, key.section, key.long_mm) == ("T30", ISO_10664["T30"].point_to_point, 200)
    odd = {**entry, "size": "T45", "point_to_point": 7.9}
    assert parse_tools([odd], "tools").tools[0].section == 7.9


def test_a_spanner_takes_the_built_in_head_for_its_size():
    (tool,) = parse_tools([SHOP], "tools").tools
    assert isinstance(tool, CustomSpanner)
    base = spanner_for(24.0)
    assert tool.spanner.length == 300
    assert tool.spanner.stubby_length is None
    assert (tool.spanner.head_thickness, tool.spanner.ring_outer_radius) == (
        base.head_thickness,
        base.ring_outer_radius,
    )
    assert tool.spanner.label == "shop-spanner-24"
    assert tool.ends == ("ring", "open")
    ring = parse_tools([{**SHOP, "ends": ["ring"], "stubby": 150}], "tools").tools[0]
    assert (ring.ends, ring.spanner.stubby_length) == (("ring",), 150)


def test_a_socket_a_nut_driver_and_a_driver_default_to_the_built_in_ones():
    tools = parse_tools(
        [
            {"name": "deep-13", "type": "socket", "across_flats": 13, "length": 63},
            {"name": "nd-10", "type": "nut-driver", "across_flats": 10},
            {"name": "long-ph2", "type": "driver", "tip": "ph2", "shaft_length": 250},
        ],
        "tools",
    ).tools
    socket, driver, screwdriver = tools
    assert isinstance(socket, CustomSocket)
    assert (socket.socket.outer_radius, socket.socket.length) == (
        socket_for(13.0).outer_radius,
        63,
    )
    assert socket.socket.label == "deep-13"
    assert isinstance(driver, CustomNutDriver)
    assert driver.driver.outer_radius == NUT_DRIVERS[10.0].outer_radius
    assert driver.driver.name == "nd-10"
    assert screwdriver == CustomDriver("long-ph2", "ph2", 3.0, 250.0)


@pytest.mark.parametrize(
    ("entry", "says"),
    [
        # A string is a built-in tool's name (issue #234), and this one is none.
        ("long-key", "'long-key' is no built-in tool"),
        ({"type": "hex-key"}, "name must be"),
        ({**STUBBY, "name": ""}, "name must be"),
        ({**STUBBY, "name": "key 5"}, "name must be"),
        ({**STUBBY, "name": "\x1b[31mkey"}, "name must be"),
        ({**STUBBY, "name": "k" * 65}, "name must be"),
        ({**STUBBY, "name": "spanner-24"}, "'spanner-24' is a built-in tool (full): list it"),
        ({**STUBBY, "name": "hex-key-5-long"}, "named like a built-in tool"),
        ({**STUBBY, "type": "crowsfoot"}, "type must be one of"),
        ({"name": "k", "type": "hex-key", "across_flats": 5, "long": 60}, "needs short"),
        ({**STUBBY, "colour": "red"}, "unknown key(s) for a hex-key: colour"),
        ({**STUBBY, "long": 0}, "long must be a positive number"),
        ({**STUBBY, "long": -60}, "long must be a positive number"),
        ({**STUBBY, "long": "60"}, "long must be a positive number"),
        ({**STUBBY, "long": True}, "long must be a positive number"),
        ({**STUBBY, "long": float("inf")}, "long must be finite"),
        ({**STUBBY, "across_corners": 4.9}, "is less than across_flats"),
        # Arms swapped, the short eight times the long (issue #75).
        ({**STUBBY, "long": 10, "short": 80}, "short (80) is longer than long (10): swapped?"),
        (
            {"name": "t", "type": "torx-key", "size": "T30", "long": 10, "short": 80},
            "short (80) is longer than long (10): swapped?",
        ),
        (
            {"name": "t", "type": "torx-key", "size": "30", "long": 9, "short": 9},
            "a Torx size",
        ),
        (
            {"name": "t", "type": "torx-key", "size": "T45", "long": 9, "short": 9},
            "give point_to_point",
        ),
        ({**SHOP, "ends": ["box"]}, "ends must be a list of ring and open"),
        ({**SHOP, "ends": []}, "ends must be a list of ring and open"),
        ({**SHOP, "ends": ["ring", "ring"]}, "ends must be a list of ring and open"),
        ({**SHOP, "stubby": 300}, "stubby (300) is no shorter than length"),
        (
            {"name": "s", "type": "socket", "across_flats": 13, "outer_radius": 7},
            "inside the hex's corners",
        ),
        ({"name": "n", "type": "nut-driver", "across_flats": 9}, "give outer_radius"),
        ({"name": "d", "type": "driver", "tip": "pz2"}, "tip must be one of"),
    ],
)
def test_a_tool_the_check_can_t_read_is_refused_saying_why(entry, says):
    with pytest.raises(ConfigError) as caught:
        Config.from_dict({"tools": [entry]}, source="w.yaml")
    message = str(caught.value)
    assert message.startswith("w.yaml: tools[0]")
    assert says in message


def test_two_tools_of_one_name_are_refused():
    with pytest.raises(ConfigError, match=r"tools\[1\]: a second tool named 'stubby-key-5'"):
        Config.from_dict({"tools": [STUBBY, STUBBY]})


def test_tools_must_be_a_list():
    with pytest.raises(ConfigError, match="must be a list of tools"):
        Config.from_dict({"tools": {"stubby": STUBBY}})


def test_no_tools_is_none():
    assert len(Config.from_dict({}).tools) == 0
    assert len(Config.from_dict({"tools": []}).tools) == 0


# ---------------------------------------------------------------------------
# In the check: joined to the kit, after its own.
# ---------------------------------------------------------------------------


def m16_nut():
    return [plate(), Part("nut", hex_prism(24, 13) - Cylinder(8, 40))]


M16 = {"parts": "nut", "kind": "nut", "size": "M16"}


def test_a_shop_spanner_covers_a_size_the_kit_lacks(engine):
    (without,) = run(m16_nut(), [M16], kit="metric-home", engine=engine)
    assert without.verdict is Verdict.NOT_COVERED
    assert without.reason.startswith("needs spanner-24 or socket-24")
    (result,) = run(m16_nut(), [M16], [SHOP], kit="metric-home", engine=engine)
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "shop-spanner-24",
        "ring, full length",
    )


def screw_under_a_slab():
    return [
        plate(),
        Part("screw", socket_screw("M6")),
        Part("slab", Pos(0, 0, 41) * Box(300, 300, 10)),
    ]


M6 = {"parts": "screw", "kind": "screw", "head": "socket", "size": "M6"}


def test_a_short_key_turns_where_iso_s_can_t(engine):
    (without,) = run(screw_under_a_slab(), [M6], engine=engine)
    assert without.verdict is Verdict.BLOCKED
    (result,) = run(screw_under_a_slab(), [M6], [STUBBY], engine=engine)
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "stubby-key-5",
        "short leg in",
    )
    tools = [attempt.tool for attempt in result.attempts]
    assert tools.index("hex-key-5") < tools.index("ball-end-key-5") < tools.index("stubby-key-5")


def test_the_kit_s_own_tool_comes_first():
    # Open air: the kit's spanner turns it, and the shop one is never tried.
    (result,) = run(m16_nut(), [M16], [SHOP])
    assert result.tool == "spanner-24"
    assert all(attempt.tool != "shop-spanner-24" for attempt in result.attempts)


def test_a_custom_tool_of_another_size_is_not_tried():
    (result,) = run(screw_under_a_slab(), [M6], [{**STUBBY, "name": "k6", "across_flats": 6}])
    assert result.verdict is Verdict.BLOCKED
    assert all(attempt.tool != "k6" for attempt in result.attempts)


def test_a_rule_may_name_a_custom_tool():
    rule = {**M16, "tool": "shop-spanner-24"}
    (result,) = run(m16_nut(), [rule], [SHOP])
    assert result.tool == "shop-spanner-24"
    assert {attempt.tool for attempt in result.attempts} == {"shop-spanner-24"}
    key = {**M6, "tool": "stubby-key-5"}
    (keyed,) = run(screw_under_a_slab(), [key], [STUBBY])
    assert (keyed.verdict, keyed.tool) == (Verdict.TURNS, "stubby-key-5")


@pytest.mark.parametrize(
    ("ends", "ways"),
    [
        (["ring"], ["ring, full length"]),
        (["open"], ["open end, full length"]),
        (["ring", "open"], ["ring, full length"]),  # the ring turns it first
    ],
)
def test_a_spanner_is_tried_by_its_ends(ends, ways):
    (result,) = run(m16_nut(), [M16], [{**SHOP, "ends": ends}], kit="metric-home")
    assert [attempt.way for attempt in result.attempts] == ways


def test_a_ring_only_spanner_has_no_open_end_to_fall_back_on():
    # A gland whose dome is wider than any ring's bore (issue #47): a ring spanner,
    # with no open end, can't turn it; a combination one turns it by its open end.
    domed = hex_prism(15, 3) + Pos(0, 0, 6.5) * Cylinder(10, 7)
    rule = {"parts": "nut", "kind": "nut", "size": "M10", "socket": False, "tool": "ring-15"}
    ring = {"name": "ring-15", "type": "spanner", "across_flats": 15, "length": 200}
    (only,) = run([plate(), Part("nut", domed)], [rule], [{**ring, "ends": ["ring"]}])
    assert only.verdict is Verdict.BLOCKED
    assert {attempt.way for attempt in only.attempts} == {"ring, full length"}
    (both,) = run([plate(), Part("nut", domed)], [rule], [ring])
    assert (both.verdict, both.how) == (Verdict.TURNS, "open end, full length")


def test_a_custom_socket_turns_what_the_kit_s_thicker_one_can_t():
    # Ribs 8.5 off the flats of an M8 nut, lower than it: every spanner meets them,
    # and so does the kit's socket (its wall to r 9.0); a thin-wall one (r 8.3) doesn't.
    nut = hex_prism(13, 6.8) - Cylinder(4, 30)
    ribs = [Part(n, Pos(0, y, 2) * Box(80, 10, 4)) for n, y in (("left", -13.5), ("right", 13.5))]
    rule = {"parts": "nut", "kind": "nut", "size": "M8"}
    thin = {"name": "thin-13", "type": "socket", "across_flats": 13, "outer_radius": 8.3}
    (without,) = run([plate(), Part("nut", nut), *ribs], [rule])
    assert without.verdict is Verdict.BLOCKED
    (result,) = run([plate(), Part("nut", nut), *ribs], [rule], [thin])
    assert (result.verdict, result.tool) == (Verdict.TURNS, "thin-13")


def test_a_gland_takes_a_custom_spanner_but_no_custom_socket():
    gland = {**M16, "socket": False}
    tools = [{"name": "deep-24", "type": "socket", "across_flats": 24}, SHOP]
    (result,) = run(m16_nut(), [gland], tools, kit="metric-home")
    assert {attempt.tool for attempt in result.attempts} == {"shop-spanner-24"}


def test_a_short_torx_key_turns_where_the_kit_s_can_t():
    # An M6 Torx head under a slab 25 over it: the kit's T30 needs 29.1 to swing
    # short leg in (its short arm 26); one with a 15 mm short arm needs 18.1.
    screw = Part("screw", socket_screw("M6", pocket=False))
    slab = Part("slab", Pos(0, 0, 36) * Box(300, 300, 10))
    rule = {"parts": "screw", "kind": "screw", "head": "torx", "size": "M6"}
    short = {"name": "short-t30", "type": "torx-key", "size": "T30", "long": 60, "short": 15}
    (without,) = run([plate(), screw, slab], [rule])
    assert (without.verdict, without.tool) == (Verdict.BLOCKED, "torx-key-T30")
    (result,) = run([plate(), screw, slab], [rule], [short])
    assert (result.verdict, result.tool, result.how) == (Verdict.TURNS, "short-t30", "short leg in")


def test_a_slim_nut_driver_reaches_down_a_well():
    # An M6 nut at the bottom of a well 30 across and 300 deep: the ratchet's head
    # (r 17) and the kit's nut driver's handle (r 18) don't fit down it; a slim
    # driver's (r 12) does.
    nut = Part("nut", hex_prism(10, 5.2) - Cylinder(3, 30))
    stud = Part("stud", Pos(0, 0, 2.5) * Cylinder(3, 25))
    well = Part("well", Pos(0, 0, 150) * (Box(150, 150, 300) - Cylinder(15, 301)))
    rule = {"parts": "nut", "kind": "nut", "size": "M6"}
    slim = {"name": "slim-nd-10", "type": "nut-driver", "across_flats": 10, "handle_radius": 12}
    (without,) = run([plate(), nut, stud, well], [rule])
    assert without.verdict is Verdict.BLOCKED
    (result,) = run([plate(), nut, stud, well], [rule], [slim])
    assert (result.verdict, result.tool) == (Verdict.TURNS, "slim-nd-10")
    tools = [attempt.tool for attempt in result.attempts]
    assert tools.index("nut-driver-10") < tools.index("slim-nd-10")  # the kit's first


def test_a_long_driver_reaches_down_a_well():
    # A Phillips screw at the bottom of a well 150 deep and 20 across: the kit's
    # driver's handle (r 14, from 100 up) meets the well; a 200 mm shaft clears it.
    screw = Pos(0, 0, -6) * Cylinder(2.5, 12) + Pos(0, 0, 1.5) * Cylinder(4, 3)
    well = Pos(0, 0, 75) * (Box(100, 100, 150) - Cylinder(10, 151))
    parts = [plate(), Part("screw", screw), Part("well", well)]
    rule = {"parts": "screw", "kind": "screw", "head": "phillips", "size": "M5"}
    long_driver = {"name": "long-ph2", "type": "driver", "tip": "ph2", "shaft_length": 200}
    (without,) = run(parts, [rule])
    assert without.verdict is Verdict.BLOCKED
    (result,) = run(parts, [rule], [long_driver])
    assert (result.verdict, result.tool) == (Verdict.TURNS, "long-ph2")


def test_a_custom_size_is_one_a_measured_hex_can_take():
    # A nut drawn 25.5 across flats: no tool's size, and no standard's band below
    # one, until a sidecar has a spanner that size.
    parts = [plate(), Part("nut", hex_prism(25.5, 13) - Cylinder(8, 40))]
    rule = {"parts": "nut", "kind": "nut", "across_flats": 25.5}
    (without,) = run(parts, [rule])
    assert without.verdict is Verdict.NOT_COVERED
    odd = {**SHOP, "name": "odd-25.5", "across_flats": 25.5}
    (result,) = run(parts, [rule], [odd])
    assert (result.verdict, result.tool) == (Verdict.TURNS, "odd-25.5")


def test_a_measured_socket_of_a_custom_key_s_size_takes_it():
    # A socket head drawn with a 5.5 pocket: no ISO key is 5.5, so no tool's size,
    # until a sidecar has a key that size.
    rule = {**M6, "across_flats": 5.5}
    (without,) = run(screw_under_a_slab()[:2], [rule])
    assert without.verdict is Verdict.NOT_COVERED
    odd = {**STUBBY, "name": "key-5.5", "across_flats": 5.5}
    (result,) = run(screw_under_a_slab()[:2], [rule], [odd])
    assert (result.verdict, result.tool) == (Verdict.TURNS, "key-5.5")


def test_a_custom_socket_cannot_get_on_over_a_dome_wider_than_its_bore():
    # Issue #47's rule holds for a sidecar's own tools too.
    domed = hex_prism(15, 3) + Pos(0, 0, 6.5) * Cylinder(10, 7)
    rule = {"parts": "nut", "kind": "nut", "size": "M10", "tool": "deep-15"}
    socket = {"name": "deep-15", "type": "socket", "across_flats": 15}
    (result,) = run([plate(), Part("nut", domed)], [rule], [socket])
    assert result.verdict is Verdict.BLOCKED
    assert result.blockers == ()  # not in its own way (issue #221): the reason says it
    assert result.reason.startswith("no ring, socket or nut driver gets on: past its hex")
    assert [attempt.kept_off for attempt in result.attempts] == [
        "past its hex the part is 20.00 across"
    ]


# ---------------------------------------------------------------------------
# A size written a little off, or by its name (issue #233).
# ---------------------------------------------------------------------------


def inch_nut():
    """A 3/8-16 nut: ASME B18.2.2's 9/16 in across flats (14.2875), which metric-home lacks."""
    return [plate(), Part("nut", hex_prism(14.2875, 8.3) - Cylinder(4.8, 40))]


INCH_NUT = {"parts": "nut", "kind": "nut", "size": "3/8-16"}
UB_SPANNER = {"name": "ub-spanner", "type": "spanner", "across_flats": 14.29, "length": 185}
UB_SOCKET = {
    "name": "ub-socket",
    "type": "socket",
    "across_flats": 14.29,
    "outer_radius": 10.5,
    "length": 25,
}


def written(af):
    """The two tools for the inch nut, their size written ``af``."""
    return [{**UB_SPANNER, "across_flats": af}, {**UB_SOCKET, "across_flats": af}]


@pytest.mark.parametrize("af", [14.2875, 14.29, 14.285, "9/16in", " 9/16in "])
def test_a_tool_written_a_little_off_or_by_name_is_tried(af, engine):
    # 14.29 is how 9/16 in is written most often: never tried, and not noted unused
    # either, when matching asked 1e-6 mm and the note 0.01 (issue #233).
    report = reported(inch_nut(), [INCH_NUT], written(af), kit="metric-home", engine=engine)
    (result,) = report.results
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "ub-spanner",
        "ring, full length",
    )
    assert report.notes == ()


def test_one_further_off_is_named_where_its_fastener_is_not_covered():
    report = reported(inch_nut(), [INCH_NUT], written(14.4), kit="metric-home")
    (result,) = report.results
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == (
        "needs spanner-9/16in or socket-9/16in, which kit metric-home does not hold "
        "(imperial-home and full have it); the sidecar's ub-spanner and ub-socket are "
        "14.4 across flats, not 14.2875 (9/16in)"
    )
    assert report.notes == (
        "tool ub-spanner: no fastener here takes a 14.4 mm spanner",
        "tool ub-socket: no fastener here takes a 14.4 mm socket",
    )


@pytest.mark.parametrize("off", [0.0, 0.002, 0.0049, -0.0049, 0.0051, -0.0051, 0.008, 0.012, 0.3])
def test_a_custom_tool_is_either_tried_or_noted_unused_never_neither(off):
    # One comparison for both: a tool off by 0.0025 fell between the two.
    spanner = {**UB_SPANNER, "across_flats": 14.2875 + off}
    report = reported(inch_nut(), [INCH_NUT], [spanner], kit="metric-home")
    (result,) = report.results
    tried = any(attempt.tool == "ub-spanner" for attempt in result.attempts)
    assert tried is (abs(off) < 0.005)
    assert bool(report.notes) is not tried


def test_tools_off_by_different_amounts_are_each_given_their_size():
    tools = [
        {**UB_SPANNER, "across_flats": 14.4},
        {**UB_SOCKET, "across_flats": 14.1},
        {"name": "nd-14", "type": "nut-driver", "across_flats": 14, "outer_radius": 10},
        {**UB_SPANNER, "name": "ub-ring", "across_flats": 14.4},
    ]
    (result,) = run(inch_nut(), [INCH_NUT], tools, kit="metric-home")
    assert result.reason.endswith(
        "; the sidecar's ub-spanner and ub-ring are 14.4 across flats, ub-socket 14.1 "
        "and nd-14 14, not 14.2875 (9/16in)"
    )


def test_only_a_tool_the_fastener_would_try_within_half_a_millimetre_is_named():
    tools = [
        {**UB_SPANNER, "name": "under", "across_flats": 14.2875 - 0.49},
        {**UB_SPANNER, "name": "over", "across_flats": 14.2875 + 0.51},
        {**UB_SPANNER, "name": "far-under", "across_flats": 13},
        {"name": "key", "type": "hex-key", "across_flats": 14.3, "long": 200, "short": 50},
        {"name": "t", "type": "torx-key", "size": "T30", "long": 80, "short": 20},
        {"name": "ph", "type": "driver", "tip": "ph2"},
    ]
    (result,) = run(inch_nut(), [INCH_NUT], tools, kit="metric-home")
    assert result.reason.endswith(
        "(imperial-home and full have it); the sidecar's under is 13.7975 across flats, "
        "not 14.2875 (9/16in)"
    )


def test_a_gland_names_a_spanner_off_its_size_and_no_socket():
    # A cable through it: no socket is tried, so none is named.
    gland = {**INCH_NUT, "socket": False}
    (result,) = run(inch_nut(), [gland], written(14.4), kit="metric-home")
    assert result.reason == (
        "needs spanner-9/16in, which kit metric-home does not hold (imperial-home and "
        "full have it); the sidecar's ub-spanner is 14.4 across flats, not 14.2875 (9/16in)"
    )


@pytest.mark.parametrize(
    ("kind", "of_size"),
    [
        ({"type": "spanner", "length": 200}, "spanners"),
        ({"type": "socket"}, "sockets"),
        ({"type": "nut-driver", "outer_radius": 20}, "nut_drivers"),
        ({"type": "hex-key", "long": 200, "short": 50}, "hex_keys"),
    ],
)
def test_two_tools_written_within_same_mm_of_each_other_are_one_size(kind, of_size):
    # 25.501 and 25.504: no table holds 25.5, so neither is taken as a table's size,
    # and a hex measured as either is the other's size too.
    tools = parse_tools(
        [
            {"name": "a", "across_flats": 25.501, **kind},
            {"name": "b", "across_flats": 25.504, **kind},
        ],
        "tools",
    )
    assert [tool.name for tool in getattr(tools, of_size)(25.501)] == ["a", "b"]
    assert [tool.name for tool in getattr(tools, of_size)(25.507)] == ["b"]


def test_near_is_off_the_size_and_not_on_it():
    tools = parse_tools([*written(14.29), {**UB_SPANNER, "name": "x", "across_flats": 14.4}], "")
    assert tools.near(14.2875, ("spanner", "socket")) == (("x", 14.4),)
    assert tools.near(14.2875, ("socket",)) == ()


def test_a_metric_size_is_said_once():
    shop = {**SHOP, "across_flats": 24.3}
    (result,) = run(m16_nut(), [M16], [shop], kit="metric-home")
    assert result.reason.endswith("; the sidecar's shop-spanner-24 is 24.3 across flats, not 24")


def test_a_key_off_its_size_is_named_where_its_screw_is_not_covered():
    # imperial-home holds no metric key: the M6 socket head's 5 mm is not covered.
    key = {**STUBBY, "name": "key-5.1", "across_flats": 5.1}
    (result,) = run(
        screw_under_a_slab()[:2], [M6], [key, {**SHOP, "across_flats": 5.2}], "imperial-home"
    )
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason.startswith("needs hex-key-5")
    assert result.reason.endswith("; the sidecar's key-5.1 is 5.1 across flats, not 5")


def test_nothing_is_added_with_no_tool_near():
    (result,) = run(inch_nut(), [INCH_NUT], [SHOP], kit="metric-home")
    assert result.reason == (
        "needs spanner-9/16in or socket-9/16in, which kit metric-home does not hold "
        "(imperial-home and full have it)"
    )


def test_a_size_within_same_mm_of_a_table_size_is_that_size():
    def af(written):
        entry = {**SHOP, "across_flats": written}
        return parse_tools([entry], "tools").tools[0].spanner.af

    assert af(14.29) == af(14.2875 + 0.0049) == af(14.2875 - 0.0049) == 14.2875
    assert af(14.2875 + 0.0051) == pytest.approx(14.2926)
    assert af(26.99) == size_mm("1-1/16in")  # the tables' own, 0.0125 under 27
    assert af(26.993) == 26.993  # 0.0055 over 1-1/16 in and 0.007 under 27: neither
    assert af(26.996) == af(27.004) == 27.0
    assert af(25.5) == 25.5  # no table's size: as written


def test_no_size_written_is_two_of_the_tables():
    sizes = sorted({*FLATS, *HEX_KEYS})
    assert tuple(sizes) == TABLE_SIZES
    gaps = [b - a for a, b in itertools.pairwise(sizes)]
    assert min(gaps) == pytest.approx(0.0125)  # 1-1/16 in and 27
    assert min(gaps) > 2 * SAME_MM
    assert SAME_MM == 0.005
    assert NEAR_MM == 0.5


@pytest.mark.parametrize(
    ("entry", "af", "named"),
    [
        ({**SHOP, "across_flats": "9/16in"}, 14.2875, "9/16in"),
        ({**SHOP, "across_flats": "1-1/16in"}, size_mm("1-1/16in"), "1-1/16in"),
        ({**SHOP, "across_flats": "13"}, 13.0, "13"),
        ({"name": "d", "type": "socket", "across_flats": "5.5"}, 5.5, "5.5"),
        (
            {"name": "n", "type": "nut-driver", "across_flats": "7/16in", "outer_radius": 9},
            size_mm("7/16in"),
            "7/16in",
        ),
        ({**STUBBY, "across_flats": "5/32in"}, 3.96875, "5/32in"),
    ],
)
def test_across_flats_may_be_a_size_s_name(entry, af, named):
    (tool,) = parse_tools([entry], "tools").tools
    assert tool_af(tool) == af
    assert size_name(af) == named


def test_a_key_written_by_name_has_its_name_for_its_size():
    (key,) = parse_tools([{**STUBBY, "across_flats": 3.97}], "tools").tools
    assert (key.size, key.af) == ("5/32in", 3.96875)


@pytest.mark.parametrize(
    "value", ["9/16", "13mm", "", "in", "0", "-1", "0in", "nan", "inf", True, None, [13]]
)
def test_across_flats_that_is_no_size_is_refused(value):
    with pytest.raises(ConfigError) as caught:
        Config.from_dict({"tools": [{**SHOP, "across_flats": value}]}, source="w.yaml")
    assert str(caught.value) == (
        "w.yaml: tools[0] (shop-spanner-24): across_flats must be a positive number of mm "
        f"or a size's name (9/16in), got {value!r}"
    )


# ---------------------------------------------------------------------------
# The tools command lists them after the kit's own.
# ---------------------------------------------------------------------------


def test_the_tools_command_lists_a_sidecar_s_own(tmp_path):
    sidecar = tmp_path / "wrenchroom.yaml"
    sidecar.write_text(
        "tools:\n"
        "  - {name: shop-spanner-24, type: spanner, across_flats: 24, length: 300}\n"
        "  - {name: stubby-key-5, type: hex-key, across_flats: 5, long: 60, short: 20}\n"
    )
    output = CliRunner().invoke(main, ["tools", "--config", str(sidecar)]).output
    lines = output.splitlines()
    head = lines.index("custom tools, from wrenchroom.yaml (tried after the kit's own; mm):")
    assert lines[head + 1].split() == [
        "shop-spanner-24",
        "spanner",
        "24,",
        "ring",
        "and",
        "open",
        "end,",
        "length",
        "300",
    ]
    assert lines[head + 2].split()[:3] == ["stubby-key-5", "hex", "key"]
    assert "spanner-13" in output  # the kit's own come first


def test_the_tools_command_names_an_inch_size_as_the_tables_do(tmp_path):
    # Written 14.29, listed as the size it is taken as (issue #233).
    sidecar = tmp_path / "wrenchroom.yaml"
    sidecar.write_text(
        "tools:\n"
        "  - {name: ub-spanner, type: spanner, across_flats: 14.29, length: 185}\n"
        "  - {name: ub-socket, type: socket, across_flats: 9/16in}\n"
        "  - {name: nd, type: nut-driver, across_flats: 14.29, outer_radius: 10}\n"
        "  - {name: key, type: hex-key, across_flats: 14.29, long: 200, short: 50}\n"
    )
    output = CliRunner().invoke(main, ["tools", "--config", str(sidecar)]).output
    lines = output.splitlines()
    head = lines.index("custom tools, from wrenchroom.yaml (tried after the kit's own; mm):")
    assert [line.split()[1:3] for line in lines[head + 1 : head + 5]] == [
        ["spanner", "9/16in,"],
        ["socket", "9/16in,"],
        ["nut", "driver"],
        ["hex", "key"],
    ]
    assert lines[head + 3].split()[3] == "9/16in,"
    assert lines[head + 4].split()[3] == "9/16in,"


def test_the_tools_command_refuses_a_bad_sidecar(tmp_path):
    sidecar = tmp_path / "w.yaml"
    sidecar.write_text("tools:\n  - {name: spanner-24, type: spanner, across_flats: 24}\n")
    result = CliRunner().invoke(main, ["tools", "--config", str(sidecar)])
    assert result.exit_code == 2
    assert "'spanner-24' is a built-in tool (full): list it by name" in result.output
