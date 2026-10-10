"""Connectors (M9): whether each plug comes off its receptacle.

A plug comes off by a straight pull out of its receptacle: the part, of those it
touches, that holds it in the most directions. It comes off the one way that leaves it
free, by its travel: how far it sits in, plus 3. Its pull path, its own solid moved
along that way by its travel, must meet nothing but its receptacle, its pieces and its
mates. A part named about a plug is one; a connector word or a family's code says
nothing of which half comes off, and such a part is listed, not checked.
"""

import json
import math

import pytest
from build123d import Box, Cylinder, Pos, Rot

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config, ConfigError, ConnectorRule, Grip
from wrenchroom.connectors import ConnectorVerdict, Named, read_connector_name

UP = (0.0, 0.0, 1.0)


def shroud(x=0.0):
    """A receptacle 20 by 12 by 10, its top at z = 10, a cavity 16 by 8 sunk 7 in it."""
    return Pos(x, 0, 5) * Box(20, 12, 10) - Pos(x, 0, 10 - 3.5) * Box(16, 8, 7.01)


def plug(x=0.0, grow=0.0):
    """A plug 16 by 8 in the cavity, 7 in, standing 13 above the shroud: z 3 to 23."""
    return Pos(x, 0, 13) * Box(16 + grow, 8 + grow, 20)


def board():
    return Pos(0, 0, -1) * Box(800, 100, 2)


def run(parts, connectors=(), engine="mesh", **sidecar):
    """Check parts given as (name, shape), with the sidecar's ``connectors:``."""
    config = Config.from_dict({"connectors": list(connectors), **sidecar})
    return check(Assembly([Part(n, s) for n, s in parts]), config, engine=engine)


def outcome(report):
    """Each connector as (verdict, receptacle, blockers)."""
    return {c.name: (c.verdict, c.receptacle, c.blockers) for c in report.connectors.results}


def result(report, name):
    return next(c for c in report.connectors.results if c.name == name)


# ---------------------------------------------------------------------------
# The sidecar.
# ---------------------------------------------------------------------------


def test_a_connector_rule_reads_every_key():
    config = Config.from_dict(
        {
            "connectors": [
                {
                    "parts": "motor_*",
                    "axis": "+y",
                    "travel": 9,
                    "grip": "hand",
                    "latch": [0, 0, 2],
                    "mates": ["motor_cable"],
                    "receptacle": "motor_jack",
                }
            ]
        }
    )
    assert config.connectors == (
        ConnectorRule(
            "motor_*",
            axis=(0.0, 1.0, 0.0),
            travel_mm=9.0,
            grip=Grip.HAND,
            latch=(0.0, 0.0, 1.0),
            mates=("motor_cable",),
            receptacle="motor_jack",
        ),
    )


def test_a_connector_rule_s_defaults_are_found_from_the_geometry():
    (rule,) = Config.from_dict(
        {"connectors": [{"parts": "p", "axis": "auto", "travel": "auto"}]}
    ).connectors
    assert rule == ConnectorRule("p")
    assert (rule.axis, rule.travel_mm, rule.grip, rule.latch, rule.receptacle) == (
        None,
        None,
        Grip.PINCH,
        None,
        None,
    )


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("plug", r"connectors\[0\]: must be a mapping"),
        ({"axis": "+z"}, r"connectors\[0\]: 'parts' is required"),
        ({"parts": "p", "pull": 3}, r"connectors\[0\]: unknown key\(s\) \['pull'\]"),
        ({"parts": "p", "travel": -2}, r"connectors\[0\]: travel must be a positive number"),
        ({"parts": "p", "travel": "far"}, r"connectors\[0\]: travel must be a positive number"),
        ({"parts": "p", "grip": "tongs"}, r"connectors\[0\]: grip: 'tongs' is not one of"),
        ({"parts": "p", "latch": "auto"}, r"connectors\[0\]: latch is the side its release"),
        ({"parts": "p", "latch": "up"}, r"connectors\[0\]: latch: axis must be"),
        ({"parts": "p", "axis": [0, 0, 0]}, r"connectors\[0\]: axis must not be the zero"),
        ({"parts": "p", "mates": "cable"}, r"connectors\[0\]: mates must be a list"),
        ({"parts": "p", "receptacle": 3}, r"connectors\[0\]: receptacle must be a string"),
        ({"parts": "p", "state": "gone"}, r"rule 'p' names unknown state 'gone'"),
    ],
)
def test_a_connector_rule_the_sidecar_can_t_mean_is_a_config_error(entry, message):
    with pytest.raises(ConfigError, match=message):
        Config.from_dict({"connectors": [entry]})


def test_connectors_must_be_a_list():
    with pytest.raises(ConfigError, match="connectors must be a list"):
        Config.from_dict({"connectors": {"parts": "p"}})


def test_a_later_rule_replaces_an_earlier_one_and_globs_naming_nothing_are_said():
    config = Config.from_dict(
        {
            "connectors": [
                {"parts": "*_plug", "travel": 4},
                {"parts": "b_plug", "travel": 6, "mates": ["b_cable", "gone_cable"]},
                {"parts": "gone_plug"},
            ],
            "ignore": ["c_*"],
        }
    )
    parts = [
        Part(n, Pos(20 * i, 0, 0) * Box(5, 5, 5))
        for i, n in enumerate(["a_plug", "b_plug", "b_cable", "c_plug"])
    ]
    matches = config.apply_connectors(Assembly(parts))
    assert {name: rule.travel_mm for name, rule in matches.rules.items()} == {
        "a_plug": 4.0,
        "b_plug": 6.0,
    }
    assert matches.unmatched_rules == ("gone_plug",)
    assert matches.unmatched_mates == (("b_plug", "gone_cable"),)


# ---------------------------------------------------------------------------
# Names.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "named"),
    [
        ("xt60_plug", Named.PLUG),
        ("Motor Plug (2):1", Named.PLUG),
        ("fanPlug", Named.PLUG),
        ("plugs", Named.PLUG),
        ("drain plug", None),  # screwed in, not pulled
        ("spark_plug", None),
        ("plugin_bracket", None),
        ("XT60 female", Named.CONNECTOR),
        ("xt90_male_panel", Named.CONNECTOR),
        ("JST XH 2 v3:1", Named.CONNECTOR),
        ("2 PIN HEADER v2:1", Named.CONNECTOR),
        ("DT04-2P", Named.CONNECTOR),
        ("dtp06_4s housing", Named.CONNECTOR),
        ("Deutsch receptacle", Named.CONNECTOR),
        ("barrel_jack", Named.CONNECTOR),
        ("usb connector", Named.CONNECTOR),
        ("socket head cap screw", None),  # a screw head, never a connector
        ("xt600_frame", None),
        ("dt_bracket", None),
    ],
)
def test_a_name_about_a_plug_is_one_and_a_connector_word_names_no_half(name, named):
    assert read_connector_name(name) is named


@pytest.mark.parametrize(
    "name",
    [
        # The issue's six: the kind first, as code names a part, and a number after it.
        "motor_plug",
        "plug_motor",
        "plug_battery_main",
        "Plug - Motor",
        "PLUG_FAN",
        "fan plug 2",
        # A side, a letter, a version or a number after it, or run onto it.
        "motor_plug_left",
        "Plug A",
        "X1_plug_v2",
        "fan_plug.001",
        "plug_01",
        "plug2",
        "motor_plug2",
        "PlugMotor",
        "motorplug",  # run onto the word before it
        "XT60 plug male",  # its family and its gender round it
        "JST XH plug housing 4p",  # a plug's housing is the plug
        "plug_oil_pump",  # the oil pump's plug: what follows is more than "oil"
        # What stands before "plug" describes it, whatever it is: only what follows
        # can be the thing the name is about.
        "cable_plug",
        "header plug",
        "pcb_plug",
        "plug_holder_plug",  # the last "plug" is the noun
    ],
)
def test_plug_is_a_part_s_noun_wherever_it_stands(name):
    assert read_connector_name(name) is Named.PLUG


@pytest.mark.parametrize(
    "name",
    [
        "drain_plug",
        "oil drain plug M12",
        "filler_plug",
        "oil_filler_plug",
        "blanking plug",
        "sparkplug",
        "plug_drain",  # the kind first, and what it is after it
        "plug_filler_oil",
        "threaded plug",
        "unplug",  # no plug: a verb
        "unplugged_state",
        "plugin_bracket",
    ],
)
def test_a_plug_turned_or_pressed_in_and_a_word_that_only_holds_plug_are_none(name):
    assert read_connector_name(name) is None


@pytest.mark.parametrize(
    "name",
    [
        "plug_cover",  # a cover, most likely: said, not pulled at
        "plug_header",
        "plug_socket_4p",
        "plug_motor_cable",
        "motor_plug_holder",
        "plug_board",
        "plug_latch",
        "Plug - Pin 3",
    ],
)
def test_a_plug_word_before_a_noun_it_describes_is_listed_not_checked(name):
    assert read_connector_name(name) is Named.CONNECTOR


# ---------------------------------------------------------------------------
# A plug in its receptacle: found, and pulled.
# ---------------------------------------------------------------------------


def test_a_plug_in_the_open_comes_off_the_way_its_receptacle_leaves_free(engine):
    report = run(
        [("board", board()), ("jack", shroud()), ("plug", plug())], [{"parts": "plug"}], engine
    )
    found = result(report, "plug")
    assert (found.verdict, found.receptacle, found.axis, found.blockers) == (
        ConnectorVerdict.UNPLUGS,
        ("jack",),
        UP,
        (),
    )
    assert found.travel == pytest.approx(7 + 3, abs=1e-9)  # 7 in, plus the margin
    assert (found.source, found.state, found.reason) == ("sidecar", None, None)
    assert report.exit_code == 0


@pytest.mark.parametrize(
    ("gap", "verdict"),
    [(9.0, ConnectorVerdict.STUCK), (11.0, ConnectorVerdict.UNPLUGS)],
)
def test_a_shelf_closer_than_its_travel_leaves_it_stuck(engine, gap, verdict):
    # The plug must rise 10 (7 in, plus 3): a shelf 9 over its top is in the way.
    shelf = Pos(0, 0, 23 + gap + 5) * Box(80, 80, 10)
    parts = [("board", board()), ("jack", shroud()), ("plug", plug()), ("shelf", shelf)]
    report = run(parts, [{"parts": "plug"}], engine)
    assert outcome(report)["plug"][0] is verdict
    if verdict is ConnectorVerdict.STUCK:
        assert outcome(report)["plug"][2] == ("shelf",)
        assert "FAIL plug  stuck  shelf" in report.terminal_lines()
        assert report.exit_code == 1


def test_a_travel_given_is_the_travel(engine):
    shelf = Pos(0, 0, 23 + 9 + 5) * Box(80, 80, 10)
    parts = [("board", board()), ("jack", shroud()), ("plug", plug()), ("shelf", shelf)]
    report = run(parts, [{"parts": "plug", "travel": 8}], engine)
    assert result(report, "plug").travel == 8.0
    assert outcome(report)["plug"][0] is ConnectorVerdict.UNPLUGS


def cabled():
    """A plug whose cable runs up 80 from its top, through a hole in a panel 25 over it."""
    cable = Pos(0, 0, 23 + 40) * Cylinder(3, 80)
    panel = Pos(0, 0, 50) * Box(80, 80, 4) - Pos(0, 0, 50) * Cylinder(3.5, 5)
    return [
        ("board", board()),
        ("jack", shroud()),
        ("plug", plug()),
        ("cable", cable),
        ("panel", panel),
    ]


def test_its_cable_comes_with_it_as_a_mate(engine):
    report = run(cabled(), [{"parts": "plug", "mates": ["cable"]}], engine)
    assert outcome(report)["plug"] == (ConnectorVerdict.UNPLUGS, ("jack",), ())


def test_a_cable_not_said_to_be_its_mate_is_in_its_way(engine):
    report = run(cabled(), [{"parts": "plug"}], engine)
    assert outcome(report)["plug"] == (ConnectorVerdict.STUCK, ("jack",), ("cable",))


OWN_CABLE = "its own cable? name it in mates:"


@pytest.mark.parametrize("name", ["cable", "motor_wire", "Lead 2", "harness_a", "power cord"])
def test_a_cable_in_its_way_that_touches_it_is_asked_about(engine, name):
    # Its cable runs up from its top, along the way it comes off, and no mate names
    # it: stuck, as before, and the reason says what it most likely is (issue #157).
    parts = [(name if n == "cable" else n, shape) for n, shape in cabled()]
    report = run(parts, [{"parts": "plug"}], engine)
    found = result(report, "plug")
    assert (found.verdict, found.blockers) == (ConnectorVerdict.STUCK, (name,))
    assert found.reason == f"{name} ({OWN_CABLE})"
    assert f"FAIL plug  stuck  {name} ({OWN_CABLE})" in report.terminal_lines()


def test_a_cable_in_its_way_among_other_parts_is_the_one_asked_about():
    # A shelf over it too, 6 above its top and bored for its cable: both are in its
    # way, and the question is of the cable.
    shelf = Pos(0, 0, 23 + 6 + 2) * Box(40, 40, 4) - Pos(0, 0, 31) * Cylinder(3.5, 5)
    report = run([*cabled(), ("shelf", shelf)], [{"parts": "plug"}])
    found = result(report, "plug")
    assert set(found.blockers) == {"cable", "shelf"}
    assert found.reason == f"cable, shelf (cable: {OWN_CABLE})"


def test_a_cable_in_its_way_that_doesn_t_touch_it_is_any_part():
    # Another plug's cable crossing 6 over this one: in its way, and not its own.
    parts = [(n, s) for n, s in cabled() if n not in {"cable", "panel"}]
    crossing = Pos(0, 0, 23 + 6 + 3) * Rot(0, 90, 0) * Cylinder(3, 80)
    report = run([*parts, ("cable", crossing)], [{"parts": "plug"}])
    found = result(report, "plug")
    assert (found.verdict, found.blockers, found.reason) == (
        ConnectorVerdict.STUCK,
        ("cable",),
        None,
    )


def test_a_part_in_its_way_that_touches_it_and_is_no_cable_is_any_part():
    # The same rod up from its top, named a post: nothing says it comes off with it.
    parts = [("post" if n == "cable" else n, shape) for n, shape in cabled()]
    found = result(run(parts, [{"parts": "plug"}]), "plug")
    assert (found.blockers, found.reason) == (("post",), None)


def test_its_own_cable_is_asked_about_in_the_json_and_the_markdown():
    report = run(cabled(), [{"parts": "plug"}])
    (entry,) = report.to_json_dict()["connectors"]["results"]
    assert (entry["blocked_by"], entry["reason"]) == (["cable"], f"cable ({OWN_CABLE})")
    assert f"| `plug` | stuck | `cable ({OWN_CABLE})` |" in report.markdown()


def test_a_plug_drawn_into_its_receptacle_comes_off_the_way_moving_leaves_no_more_in(engine):
    # Drawn 0.2 wider than its cavity, a press fit: it is in its shroud as drawn, and
    # only rising adds no overlap.
    parts = [("board", board()), ("jack", shroud()), ("plug", plug(grow=0.2))]
    found = result(run(parts, [{"parts": "plug"}], engine), "plug")
    assert (found.verdict, found.receptacle, found.axis) == (
        ConnectorVerdict.UNPLUGS,
        ("jack",),
        UP,
    )


def test_a_tilted_plug_comes_off_along_its_own_axis(engine):
    tilt = Rot(30, 0, 0)
    parts = [("board", tilt * board()), ("jack", tilt * shroud()), ("plug", tilt * plug())]
    found = result(run(parts, [{"parts": "plug"}], engine), "plug")
    expected = (0.0, -math.sin(math.radians(30)), math.cos(math.radians(30)))
    assert found.verdict is ConnectorVerdict.UNPLUGS
    assert found.axis == pytest.approx(expected, abs=1e-6)
    assert found.travel == pytest.approx(10, abs=1e-9)


def test_the_receptacle_holding_it_most_wins_over_a_neighbour_beside_it(engine):
    # A block against its side holds it one way; the shroud, five.
    neighbour = Pos(0, 4 + 5, 13) * Box(16, 10, 20)  # flush with its +y face
    parts = [("board", board()), ("jack", shroud()), ("plug", plug()), ("beside", neighbour)]
    found = result(run(parts, [{"parts": "plug"}], engine), "plug")
    assert (found.verdict, found.receptacle) == (ConnectorVerdict.UNPLUGS, ("jack",))


# ---------------------------------------------------------------------------
# Where the geometry can't say: not covered, saying what to give.
# ---------------------------------------------------------------------------


def not_covered(report, name="plug"):
    found = result(report, name)
    assert found.verdict is ConnectorVerdict.NOT_COVERED
    return found.reason


def test_a_plug_resting_on_a_part_plugs_into_nothing(engine):
    resting = Pos(0, 0, 10) * Box(16, 8, 20)  # on the board, no shroud
    reason = not_covered(run([("board", board()), ("plug", resting)], [{"parts": "plug"}], engine))
    assert (
        reason
        == "it only rests against board, plugged into none: say what it plugs into (receptacle:)"
    )


def test_a_plug_touching_nothing_needs_its_axis_and_travel(engine):
    floating = Pos(0, 0, 50) * Box(16, 8, 20)
    parts = [("board", board()), ("plug", floating)]
    reason = not_covered(run(parts, [{"parts": "plug"}], engine))
    assert reason == (
        "it touches no part, so nothing it plugs into: "
        "say which way it comes off (axis:) and how far (travel:)"
    )
    given = run(parts, [{"parts": "plug", "axis": "+z", "travel": 10}], engine)
    assert outcome(given)["plug"] == (ConnectorVerdict.UNPLUGS, (), ())


def test_a_receptacle_letting_it_go_two_ways_asks_for_its_axis(engine):
    # The cavity runs out of the shroud's +x end: it slides out sideways as well as up.
    slot = Pos(0, 0, 5) * Box(20, 12, 10) - Pos(3, 0, 10 - 3.5) * Box(16 + 6.01, 8, 7.01)
    parts = [("board", board()), ("jack", slot), ("plug", plug())]
    reason = not_covered(run(parts, [{"parts": "plug"}], engine))
    assert reason == "jack lets it go 2 ways (+x, +z): say which way it comes off (axis:)"
    given = run(parts, [{"parts": "plug", "axis": "+z"}], engine)
    assert outcome(given)["plug"][0] is ConnectorVerdict.UNPLUGS


def test_an_axis_given_into_its_receptacle_is_said(engine):
    parts = [("board", board()), ("jack", shroud()), ("plug", plug())]
    reason = not_covered(run(parts, [{"parts": "plug", "axis": "-z"}], engine))
    assert reason == "its axis -z runs into jack: which way does it come off?"


def test_two_parts_holding_it_alike_ask_which_it_plugs_into(engine):
    # Two angle brackets, each round one side and under it: each holds it two ways.
    left = Pos(-8 - 2, 0, 5) * Box(4, 20, 30) + Pos(-4, 0, 2) * Box(8, 20, 4)
    right = Pos(8 + 2, 0, 5) * Box(4, 20, 30) + Pos(4, 0, 2) * Box(8, 20, 4)
    resting = Pos(0, 0, 4 + 10) * Box(16, 8, 20)
    parts = [("left", left), ("right", right), ("plug", resting)]
    reason = not_covered(run(parts, [{"parts": "plug"}], engine))
    assert reason in {
        "left and right hold it alike: say which it plugs into (receptacle:)",
        "right and left hold it alike: say which it plugs into (receptacle:)",
    }
    named = run(parts, [{"parts": "plug", "receptacle": "left", "axis": "+z", "travel": 5}], engine)
    assert outcome(named)["plug"][:2] == (ConnectorVerdict.UNPLUGS, ("left",))


def test_a_receptacle_glob_naming_nothing_is_said(engine):
    parts = [("board", board()), ("jack", shroud()), ("plug", plug())]
    reason = not_covered(run(parts, [{"parts": "plug", "receptacle": "socket_*"}], engine))
    assert reason == "its receptacle glob 'socket_*' names no part (renamed part?)"


def test_a_plug_drawn_into_another_part_is_said_as_it_stands(engine):
    lump = Pos(0, 4, 15) * Box(4, 4, 4)  # 2 into the plug's +y face
    parts = [("board", board()), ("jack", shroud()), ("plug", plug()), ("lump", lump)]
    reason = not_covered(run(parts, [{"parts": "plug"}], engine))
    assert reason == (
        "drawn into lump as it stands: its cable belongs in its mates, "
        "anything else is a fault in the model to fix"
    )


# ---------------------------------------------------------------------------
# States: a plug reached with a part off.
# ---------------------------------------------------------------------------


def lidded():
    lid = Pos(0, 0, 23 + 4 + 5) * Box(80, 80, 10)
    return [("board", board()), ("jack", shroud()), ("plug", plug()), ("lid", lid)]


def test_a_plug_s_own_state_is_where_it_is_pulled(engine):
    states = {"lid-off": {"remove": ["lid"]}}
    report = run(lidded(), [{"parts": "plug", "state": "lid-off"}], engine, states=states)
    found = result(report, "plug")
    assert (found.verdict, found.state) == (ConnectorVerdict.UNPLUGS, "lid-off")


def test_a_stuck_plug_is_retried_in_each_try_state(engine):
    sidecar = {"states": {"lid-off": {"remove": ["lid"]}}, "checks": {"try_states": ["lid-off"]}}
    report = run(lidded(), [{"parts": "plug"}], engine, **sidecar)
    found = result(report, "plug")
    assert (found.verdict, found.state) == (ConnectorVerdict.UNPLUGS, "lid-off")
    plain = run(lidded(), [{"parts": "plug"}], engine)
    assert (result(plain, "plug").verdict, result(plain, "plug").state) == (
        ConnectorVerdict.STUCK,
        None,
    )


# ---------------------------------------------------------------------------
# Found by name, listed by name.
# ---------------------------------------------------------------------------


def named_model():
    return [
        ("board", board()),
        ("motor_jack", shroud(0)),
        ("motor_plug", plug(0)),
        ("xt60_female", Pos(100, 0, 5) * Box(10, 10, 10)),
        ("JST XH 2 v3:1", Pos(200, 0, 5) * Box(10, 6, 10)),
    ]


def test_a_part_named_about_a_plug_is_checked_and_its_receptacle_isn_t_listed():
    report = run(named_model())
    found = result(report, "motor_plug")
    assert (found.verdict, found.source, found.receptacle) == (
        ConnectorVerdict.UNPLUGS,
        "name",
        ("motor_jack",),
    )
    assert report.connectors.named == ("xt60_female", "JST XH 2 v3:1")
    assert (
        "NOTE 2 parts named like connectors, not checked: xt60_female, JST XH 2 v3:1 "
        "(a name doesn't say which half comes off: list the plugs under connectors:)"
    ) in report.terminal_lines()
    assert "2 parts named like connectors (passed over)" in report.not_checked
    assert report.exit_code == 0


def issue_model():
    """The issue's six cells, 100 apart: a plug in a shroud on a board, each plug named
    another way, and no shroud named like a connector."""
    names = ["motor_plug", "plug_motor", "plug_battery_main", "Plug - Motor", "PLUG_FAN"]
    names.append("fan plug 2")
    parts = [("board", board())]
    for index, name in enumerate(names):
        parts += [(f"shroud {index}", shroud(100 * index)), (name, plug(100 * index))]
    return parts, names


def test_a_plug_named_any_of_the_issue_s_ways_is_checked():
    parts, names = issue_model()
    report = run(parts)
    connectors = report.connectors
    assert sorted(c.name for c in connectors.results) == sorted(names)
    assert {(c.verdict, c.source) for c in connectors.results} == {
        (ConnectorVerdict.UNPLUGS, "name")
    }
    assert [
        c.receptacle for c in sorted(connectors.results, key=lambda c: names.index(c.name))
    ] == [(f"shroud {index}",) for index in range(6)]
    assert connectors.named == ()
    assert "6 connectors: 6 unplug, 0 stuck, 0 not covered" in report.terminal_lines()
    # Only motor_plug was checked, and nothing was said of the other five.


def test_a_part_named_with_a_plug_and_another_noun_is_listed():
    # A cover over the plug, clear of its way off, named for the plug it covers.
    cover = Pos(40, 0, 15) * Box(10, 30, 30)
    parts = [("board", board()), ("shroud", shroud()), ("plug_motor", plug())]
    report = run([*parts, ("plug_motor_cover", cover)])
    assert [c.name for c in report.connectors.results] == ["plug_motor"]
    assert report.connectors.named == ("plug_motor_cover",)
    assert (
        "NOTE 1 part named like a connector, not checked: plug_motor_cover "
        "(a name doesn't say which half comes off: list the plugs under connectors:)"
    ) in report.terminal_lines()


def test_a_drain_plug_is_no_connector_at_all():
    parts = [("sump", shroud()), ("oil drain plug", plug()), ("plug_drain", plug(100))]
    report = run(parts)
    assert report.connectors is None
    assert "connector" not in report.not_checked


def test_detection_off_finds_no_plug_and_lists_none():
    report = run(named_model(), checks={"detect": False})
    assert report.connectors is None
    assert "named like a" not in report.not_checked


def test_a_fastener_is_no_connector():
    # A rule says the plug-named part is a screw: it is checked as one, not pulled.
    parts = [("board", board()), ("motor_jack", shroud()), ("motor_plug", plug())]
    rules = [{"parts": "motor_plug", "kind": "screw", "head": "socket", "size": "M6"}]
    report = run(parts, fasteners=rules)
    assert [r.name for r in report.results] == ["motor_plug"]
    assert report.connectors is not None
    assert report.connectors.results == ()


def test_a_model_with_no_connectors_says_nothing_of_them():
    report = run([("board", board()), ("shroud", shroud())])
    assert report.connectors is None
    assert report.to_json_dict()["connectors"] is None
    assert not any("connector" in line for line in report.terminal_lines())


# ---------------------------------------------------------------------------
# What the report says.
# ---------------------------------------------------------------------------


def shelved():
    shelf = Pos(100, 0, 23 + 4 + 5) * Box(80, 80, 10)
    floating = Pos(200, 0, 50) * Box(16, 8, 20)
    return [
        ("board", board()),
        ("a_jack", shroud(0)),
        ("a_plug", plug(0)),
        ("b_jack", shroud(100)),
        ("b_plug", plug(100)),
        ("shelf", shelf),
        ("c_plug", floating),
    ]


SHELVED = [{"parts": "*_plug"}, {"parts": "gone_plug"}, {"parts": "a_plug", "mates": ["a_lead"]}]


def test_the_terminal_says_the_counts_and_each_failure():
    lines = run(shelved(), SHELVED).terminal_lines()
    start = lines.index("3 connectors: 1 unplug, 1 stuck, 1 not covered")
    assert lines[start : start + 5] == [
        "3 connectors: 1 unplug, 1 stuck, 1 not covered",
        "FAIL b_plug  stuck  shelf",
        "FAIL c_plug  not-covered  it touches no part, so nothing it plugs into: say which way "
        "it comes off (axis:) and how far (travel:)",
        "WARN connector rule matched nothing: 'gone_plug' (renamed part?)",
        "WARN connector rule 'a_plug': mate glob 'a_lead' matched nothing (renamed part?)",
    ]


def test_exit_codes_stuck_fails_and_not_covered_or_a_glob_naming_nothing_is_2():
    stuck = [("board", board()), ("b_jack", shroud(100)), ("b_plug", plug(100)), shelved()[5]]
    assert run(stuck, [{"parts": "b_plug"}]).exit_code == 1
    assert run(stuck, [{"parts": "b_plug"}, {"parts": "gone"}]).exit_code == 2
    assert run(shelved(), SHELVED[:1]).exit_code == 2
    report = run(stuck, [{"parts": "b_plug"}])
    with pytest.raises(AssertionError, match="FAIL b_plug  stuck  shelf"):
        report.assert_all_pass()


def test_the_json_has_every_connector():
    document = run(shelved(), SHELVED).to_json_dict()
    connectors = document["connectors"]
    assert connectors["summary"] == {
        "connectors": 3,
        "unplugs": 1,
        "stuck": 1,
        "no_grip": 0,
        "no_latch_access": 0,
        "not_covered": 1,
    }
    assert connectors["grip_checked"] is False
    a_plug = connectors["results"][0]
    assert a_plug == {
        "name": "a_plug",
        "source": "sidecar",
        "verdict": "unplugs",
        "receptacle": ["a_jack"],
        "axis": [0.0, 0.0, 1.0],
        "travel": pytest.approx(10.0, abs=1e-9),
        "blocked_by": [],
        "reason": None,
        "state": None,
        "grip": None,
        "latch": None,
    }
    assert connectors["results"][1]["blocked_by"] == ["shelf"]
    assert connectors["results"][2]["axis"] is None
    assert connectors["unmatched_rules"] == ["gone_plug"]
    assert connectors["unmatched_mates"] == [{"rule": "a_plug", "glob": "a_lead"}]
    assert connectors["named"] == []
    json.dumps(document)


def test_the_markdown_has_the_counts_and_the_failures():
    markdown = run(shelved(), SHELVED).markdown()
    section = markdown[markdown.index("#### Connectors") :].splitlines()
    assert section[:10] == [
        "#### Connectors",
        "",
        "**3 connectors: 1 unplug, 1 stuck, 1 not covered**",
        "",
        "| Connector | Verdict | In the way, or why |",
        "| --- | --- | --- |",
        "| `b_plug` | stuck | `shelf` |",
        "| `c_plug` | not-covered | `it touches no part, so nothing it plugs into: say which way "
        "it comes off (axis:) and how far (travel:)` |",
        "",
        "- Connector rule matched nothing: `gone_plug` (renamed part?)",
    ]


def test_names_from_outside_can_t_steer_the_terminal_or_the_markdown():
    esc, rlo = "\x1b[2J", chr(0x202E)
    shelf = Pos(0, 0, 23 + 4 + 5) * Box(80, 80, 10)
    parts = [
        ("board", board()),
        ("jack", shroud()),
        (f"pl|ug{rlo}", plug()),
        (f"she{esc}lf", shelf),
    ]
    report = run(parts, [{"parts": "pl*"}])
    assert "FAIL pl|ug\\u202e  stuck  she\\x1b[2Jlf" in report.terminal_lines()
    assert "| `pl\\|ug\\u202e` | stuck | `she\\x1b[2Jlf` |" in report.markdown()


def test_only_narrows_the_connectors_and_a_connector_is_a_match():
    report = check(
        Assembly([Part(n, s) for n, s in shelved()]),
        Config.from_dict({"connectors": SHELVED[:1]}),
        only="b_plug",
    )
    assert [c.name for c in report.connectors.results] == ["b_plug"]
    assert not any("only glob" in warning for warning in report.warnings)
    nothing = check(
        Assembly([Part(n, s) for n, s in shelved()]),
        Config.from_dict({"connectors": SHELVED[:1]}),
        only="z_*",
    )
    assert "only glob 'z_*' matched no fastener or connector (renamed part?)" in nothing.warnings


# ---------------------------------------------------------------------------
# Fingers (hand room on): room to grip it, and to press its latch.
# ---------------------------------------------------------------------------

HAND = {"checks": {"hand_room": True}}


def block(x, y, width, depth):
    """A block 30 tall on the board, centred at (x, y)."""
    return Pos(x, y, 15) * Box(width, depth, 30)


def seated():
    return [("board", board()), ("jack", shroud()), ("plug", plug())]


#: Either end of the plug, 2 off: neighbours in a row.
ROW = [("left", block(-15, 0, 10, 12)), ("right", block(15, 0, 10, 12))]

#: Walls along either side, 3 off: the row in a channel.
CHANNEL = [("near", block(0, -12, 60, 10)), ("far", block(0, 12, 60, 10))]


def test_fingers_pinch_a_plug_in_the_open(engine):
    report = run(seated(), [{"parts": "plug"}], engine, **HAND)
    found = result(report, "plug")
    assert (found.verdict, found.grip) == (ConnectorVerdict.UNPLUGS, "pinch")
    assert report.connectors.grip_checked
    assert report.connectors.headline == (
        "1 connector: 1 unplug, 0 stuck, 0 no grip, 0 no latch access, 0 not covered"
    )


def test_a_plug_in_a_row_is_pinched_from_its_sides(engine):
    # Its neighbours 2 off either end leave no finger room there; across it there is.
    report = run(seated() + ROW, [{"parts": "plug"}], engine, **HAND)
    assert outcome(report)["plug"][0] is ConnectorVerdict.UNPLUGS


def test_a_plug_hemmed_in_all_round_has_no_grip(engine):
    report = run(seated() + ROW + CHANNEL, [{"parts": "plug"}], engine, **HAND)
    verdict, _, met = outcome(report)["plug"]
    assert verdict is ConnectorVerdict.NO_GRIP
    assert set(met) == {"left", "right", "near", "far"}
    assert report.exit_code == 1
    assert any(line.startswith("FAIL plug  no-grip  ") for line in report.terminal_lines())


def test_with_hand_room_off_no_finger_is_tried(engine):
    report = run(seated() + ROW + CHANNEL, [{"parts": "plug"}], engine)
    found = result(report, "plug")
    assert (found.verdict, found.grip) == (ConnectorVerdict.UNPLUGS, None)
    assert report.connectors.headline == "1 connector: 1 unplug, 0 stuck, 0 not covered"
    assert "room for a hand (checks: {hand_room: true} turns it on)" in report.not_checked


def test_stuck_comes_before_no_grip(engine):
    shelf = ("shelf", Pos(0, 0, 23 + 4 + 5) * Box(80, 80, 10))
    report = run(seated() + ROW + CHANNEL + [shelf], [{"parts": "plug"}], engine, **HAND)
    assert outcome(report)["plug"][0] is ConnectorVerdict.STUCK


def test_a_fist_needs_more_room_than_a_pinch(engine):
    # A wall 20 off one side: the fist round the plug (30 out from it) meets it; two
    # fingers from the ends don't.
    wall = [("wall", block(0, 4 + 20 + 5, 60, 10))]
    pinched = run(seated() + wall, [{"parts": "plug"}], engine, **HAND)
    fisted = run(seated() + wall, [{"parts": "plug", "grip": "hand"}], engine, **HAND)
    assert outcome(pinched)["plug"][0] is ConnectorVerdict.UNPLUGS
    assert outcome(fisted)["plug"][::2] == (ConnectorVerdict.NO_GRIP, ("wall",))
    assert result(fisted, "plug").grip == "hand"


@pytest.mark.parametrize(
    ("latch", "verdict"),
    [
        ("+y", ConnectorVerdict.NO_LATCH),
        ([0, 1, 1], ConnectorVerdict.NO_LATCH),  # pressed from the side, whatever up says
        ("-y", ConnectorVerdict.UNPLUGS),
    ],
)
def test_a_latch_against_a_wall_has_no_access(engine, latch, verdict):
    wall = [("wall", block(0, 4 + 5 + 5, 60, 10))]  # 5 off the plug's +y side
    report = run(seated() + wall, [{"parts": "plug", "latch": latch}], engine, **HAND)
    assert outcome(report)["plug"][0] is verdict
    if verdict is ConnectorVerdict.NO_LATCH:
        assert outcome(report)["plug"][2] == ("wall",)
        assert "FAIL plug  no-latch-access  wall" in report.terminal_lines()


def test_a_latch_is_only_tried_with_hand_room(engine):
    wall = [("wall", block(0, 4 + 5 + 5, 60, 10))]
    report = run(seated() + wall, [{"parts": "plug", "latch": "+y"}], engine)
    found = result(report, "plug")
    assert (found.verdict, found.latch) == (ConnectorVerdict.UNPLUGS, (0.0, 1.0, 0.0))


def test_no_grip_is_retried_in_each_try_state(engine):
    sidecar = {
        "states": {"walls-off": {"remove": ["near", "far"]}},
        "checks": {"try_states": ["walls-off"], "hand_room": True},
    }
    report = run(seated() + ROW + CHANNEL, [{"parts": "plug"}], engine, **sidecar)
    found = result(report, "plug")
    assert (found.verdict, found.state) == (ConnectorVerdict.UNPLUGS, "walls-off")


# ---------------------------------------------------------------------------
# Edges of the geometry.
# ---------------------------------------------------------------------------


def test_a_plug_drawn_loose_in_its_cavity_is_still_held_there(engine):
    # The cavity 1 wider each way: moved 0.5 sideways it is free; 2, it isn't.
    loose = Pos(0, 0, 5) * Box(20, 12, 10) - Pos(0, 0, 10 - 3.5) * Box(17, 9, 7.01)
    parts = [("board", board()), ("jack", loose), ("plug", plug())]
    found = result(run(parts, [{"parts": "plug"}], engine), "plug")
    assert (found.verdict, found.axis) == (ConnectorVerdict.UNPLUGS, UP)


def test_a_long_travel_meets_a_thin_sheet_between_its_ends(engine):
    # Told to come 40: a sheet 1 thick 15 over its top is past its end at the start and
    # short of its foot at the end, and met on the way.
    sheet = Pos(0, 0, 23 + 15.5) * Box(80, 80, 1)
    parts = [("board", board()), ("jack", shroud()), ("plug", plug()), ("sheet", sheet)]
    report = run(parts, [{"parts": "plug", "travel": 40}], engine)
    assert outcome(report)["plug"] == (ConnectorVerdict.STUCK, ("jack",), ("sheet",))


def test_a_plug_drawn_as_two_solids_comes_off_whole(engine):
    # Its latch drawn as a solid of its own, against its +y side: one part, two solids.
    body, latch = plug(), Pos(0, 4 + 1, 18) * Box(6, 2, 6)
    assembly = Assembly(
        [
            Part("board", board()),
            Part("jack", shroud()),
            Part("plug", body),
            Part("plug#2", latch, piece_of="plug"),
        ]
    )
    report = check(assembly, Config.from_dict({"connectors": [{"parts": "plug"}]}), engine=engine)
    found = result(report, "plug")
    assert (found.verdict, found.receptacle, found.axis) == (
        ConnectorVerdict.UNPLUGS,
        ("jack",),
        UP,
    )
    assert [c.name for c in report.connectors.results] == ["plug"]


def test_a_fist_stands_out_from_the_plug_itself(engine):
    # A wall 32 off the axis on its +y side: past a bare 30, inside the fist's reach
    # from a plug 8.9 round (38.9).
    wall = [("wall", block(0, 32 + 5, 60, 10))]
    fisted = run(seated() + wall, [{"parts": "plug", "grip": "hand"}], engine, **HAND)
    assert outcome(fisted)["plug"][::2] == (ConnectorVerdict.NO_GRIP, ("wall",))


def test_fingers_stand_beside_the_plug_not_in_it(engine):
    # A ring 19 from its axis: fingers 16 across beside a plug 16 by 8 reach 24 out
    # from its ends and 20 from its sides, so meet it at every angle.
    ring = Pos(0, 0, 15) * (Cylinder(30, 30) - Cylinder(19, 31))
    report = run([*seated(), ("ring", ring)], [{"parts": "plug"}], engine, **HAND)
    assert outcome(report)["plug"][::2] == (ConnectorVerdict.NO_GRIP, ("ring",))
    wider = Pos(0, 0, 15) * (Cylinder(40, 30) - Cylinder(25, 31))
    report = run([*seated(), ("ring", wider)], [{"parts": "plug"}], engine, **HAND)
    assert outcome(report)["plug"][0] is ConnectorVerdict.UNPLUGS


def test_a_thumb_presses_across_the_plug_whatever_its_latch_side_says_of_up(engine):
    # A wall 22 tall, 5 off the +y side: a thumb across the plug meets it; one along
    # [0, 1, 1] from up its corner would pass over it.
    wall = [("wall", Pos(0, 4 + 5 + 5, 11) * Box(60, 10, 22))]
    report = run(seated() + wall, [{"parts": "plug", "latch": [0, 1, 1]}], engine, **HAND)
    assert outcome(report)["plug"][::2] == (ConnectorVerdict.NO_LATCH, ("wall",))


def test_an_ignored_part_is_never_listed_as_a_connector():
    report = run(named_model(), ignore=["xt60_*"])
    assert report.connectors.named == ("JST XH 2 v3:1",)
