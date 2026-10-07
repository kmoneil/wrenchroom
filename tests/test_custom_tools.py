"""Custom tools in the sidecar, in the shape of the built-in tables (spec 5.3).

The escape hatch for a tool wrenchroom doesn't ship. A ``tools:`` list in the
sidecar describes each by the numbers the built-in tables hold for its kind; it
joins whatever kit the check uses, is tried after the kit's own tools of its
kind and size, and a rule's ``tool:`` may name it outright.

The worked cases: an M16 nut under metric-home, which holds no 24 mm spanner,
turned by a sidecar's shop spanner; and an M6 socket head under a slab 30 over
it, which ISO 2936's 5 mm key can't reach any way, turned by a short-arm key.
"""

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
    CustomDriver,
    CustomKey,
    CustomNutDriver,
    CustomSocket,
    CustomSpanner,
    parse_tools,
)
from wrenchroom.tools.nut_drivers import NUT_DRIVERS
from wrenchroom.tools.sockets import socket_for
from wrenchroom.tools.spanners import spanner_for
from wrenchroom.tools.torx_keys import ISO_10664

SHOP = {"name": "shop-spanner-24", "type": "spanner", "across_flats": 24, "length": 300}
STUBBY = {"name": "stubby-key-5", "type": "hex-key", "across_flats": 5, "long": 60, "short": 20}


def plate():
    return Part("plate", Pos(0, 0, -5) * Box(400, 400, 10))


def run(parts, rules, tools=(), kit="full", engine="mesh"):
    config = Config.from_dict({"fasteners": list(rules), "tools": list(tools)})
    return check(Assembly(parts), config, kit=kit, engine=engine).results


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
        ("long-key", "must be a mapping"),
        ({"type": "hex-key"}, "name must be"),
        ({**STUBBY, "name": ""}, "name must be"),
        ({**STUBBY, "name": "key 5"}, "name must be"),
        ({**STUBBY, "name": "\x1b[31mkey"}, "name must be"),
        ({**STUBBY, "name": "k" * 65}, "name must be"),
        ({**STUBBY, "name": "spanner-24"}, "named like a built-in tool"),
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
    assert result.blockers == ("nut",)


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


def test_the_tools_command_refuses_a_bad_sidecar(tmp_path):
    sidecar = tmp_path / "w.yaml"
    sidecar.write_text("tools:\n  - {name: spanner-24, type: spanner, across_flats: 24}\n")
    result = CliRunner().invoke(main, ["tools", "--config", str(sidecar)])
    assert result.exit_code == 2
    assert "named like a built-in tool" in result.output
