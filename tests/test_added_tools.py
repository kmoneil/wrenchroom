"""Built-in tools a sidecar adds to the kit by name (issue #234).

A kit is taken whole. A metric machine with a few inch nuts had full, which holds
tools the owner hasn't got, or a custom tool redrawing a built-in under another
name. A ``tools:`` entry that is a built-in tool's name adds that tool, as the
tables have it, to whichever kit is used; one the kit holds already is noted.
"""

import json

import pytest
from build123d import Box, Cylinder, Pos
from click.testing import CliRunner

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config, ConfigError
from wrenchroom.report import Verdict
from wrenchroom.tools import custom
from wrenchroom.tools.kits import FULL, IMPERIAL_HOME, KITS, METRIC_HOME, added_listing

INCH_TOOLS = ["spanner-9/16in", "socket-9/16in"]


def plate():
    return Part("plate", Pos(0, 0, -5) * Box(400, 400, 10))


def inch_nut():
    """A 3/8 nut: 9/16 in across flats, which metric-home holds no tool for."""
    return [plate(), Part("nut", hex_prism(14.2875, 8.3) - Cylinder(4.8, 40))]


def m8_nut():
    return [plate(), Part("nut", hex_prism(13, 6.8) - Cylinder(4, 30))]


INCH = {"parts": "nut", "kind": "nut", "size": "3/8"}
M8 = {"parts": "nut", "kind": "nut", "size": "M8"}


def run(parts, rules, tools=(), kit="metric-home", engine="mesh"):
    config = Config.from_dict({"fasteners": list(rules), "tools": list(tools)})
    return check(Assembly(parts), config, kit=kit, engine=engine)


# ---------------------------------------------------------------------------
# Reading them.
# ---------------------------------------------------------------------------


def test_a_built_in_tool_s_name_is_read_beside_custom_tools():
    shop = {"name": "shop-spanner-24", "type": "spanner", "across_flats": 24, "length": 300}
    tools = Config.from_dict({"tools": ["spanner-9/16in", shop, "socket-9/16in"]}).tools
    assert tools.built_in == ("spanner-9/16in", "socket-9/16in")
    assert [tool.name for tool in tools.tools] == ["shop-spanner-24"]
    assert len(tools) == 3


@pytest.mark.parametrize(
    "name",
    [
        "hex-key-5",
        "hex-key-0.050in",
        "ball-end-key-5",
        "torx-key-T30",
        "driver-ph2",
        "nut-driver-7",
    ],
)
def test_every_family_s_tools_may_be_named(name):
    assert Config.from_dict({"tools": [name]}).tools.built_in == (name,)


@pytest.mark.parametrize(
    ("name", "says"),
    [
        ("spaner-9/16in", "; the nearest: spanner-9/16in, spanner-7/16in, spanner-5/16in"),
        ("spanner-9/16", "; the nearest: spanner-9/16in, spanner-16, spanner-9"),
        ("spanner-60", "; the nearest: spanner-6, spanner-50, spanner-46"),
        ("zzz", ""),
    ],
)
def test_a_name_that_is_no_built_in_tool_is_refused_naming_the_nearest(name, says):
    with pytest.raises(ConfigError) as caught:
        Config.from_dict({"tools": ["spanner-13", name]}, source="w.yaml")
    assert str(caught.value) == (
        f"w.yaml: tools[1]: {name!r} is no built-in tool{says} (`wrenchroom tools --kit "
        "full` lists them; a tool of your own is a mapping with a name and a type)"
    )


def test_a_tool_named_twice_is_refused():
    with pytest.raises(ConfigError, match=r"tools\[1\]: a second tool named 'spanner-13'"):
        Config.from_dict({"tools": ["spanner-13", "spanner-13"]})


def test_a_custom_tool_named_as_a_built_in_one_is_pointed_here():
    entry = {"name": "spanner-1/2in", "type": "spanner", "across_flats": 12.7, "length": 150}
    with pytest.raises(ConfigError) as caught:
        Config.from_dict({"tools": [entry]}, source="w.yaml")
    assert str(caught.value) == (
        "w.yaml: tools[0]: 'spanner-1/2in' is a built-in tool "
        "(imperial-home, full): list it by name to add it to the kit, or give a custom "
        "tool a name of its own"
    )


def test_a_custom_tool_named_like_a_family_but_no_tool_is_refused_as_before():
    entry = {"name": "hex-key-5-long", "type": "hex-key", "across_flats": 5, "long": 9, "short": 2}
    with pytest.raises(ConfigError, match="'hex-key-5-long' is named like a built-in tool; give"):
        Config.from_dict({"tools": [entry]})


# ---------------------------------------------------------------------------
# The kit with them.
# ---------------------------------------------------------------------------


def test_a_kit_holds_what_is_added_and_the_rest_as_before():
    kit = METRIC_HOME.adding(INCH_TOOLS)
    assert (kit.name, kit.added) == ("metric-home", tuple(INCH_TOOLS))
    assert all(kit.holds(tool) for tool in INCH_TOOLS)
    assert not any(METRIC_HOME.holds(tool) for tool in INCH_TOOLS)  # the kit itself unchanged
    others = [tool for tool in FULL.tool_names() if tool not in INCH_TOOLS]
    assert [kit.holds(tool) for tool in others] == [METRIC_HOME.holds(tool) for tool in others]


def test_one_held_already_or_named_twice_is_added_once():
    kit = METRIC_HOME.adding(["spanner-13", "socket-9/16in", "socket-9/16in"])
    assert kit.added == ("socket-9/16in",)
    assert kit.adding(["socket-9/16in"]) == kit
    assert METRIC_HOME.adding([]) is METRIC_HOME


@pytest.mark.parametrize("kit", list(KITS.values()), ids=list(KITS))
def test_any_kit_with_every_tool_added_holds_what_full_does(kit):
    every = FULL.tool_names()
    assert len(every) > 150  # a vacuity guard: every family, both systems
    grown = kit.adding(every)
    assert set(grown.tool_names()) == set(every)
    assert all(grown.holds(tool) for tool in every)
    assert grown.added == tuple(tool for tool in every if not kit.holds(tool))


def test_full_names_every_tool_once():
    every = FULL.tool_names()
    assert len(set(every)) == len(every)
    assert all(FULL.holds(tool) for tool in every)


# ---------------------------------------------------------------------------
# In the check.
# ---------------------------------------------------------------------------


def test_a_metric_kit_with_the_inch_tools_added_turns_an_inch_nut(engine):
    (without,) = run(inch_nut(), [INCH], engine=engine).results
    assert without.reason == (
        "needs spanner-9/16in or socket-9/16in, which kit metric-home does not hold "
        "(imperial-home and full have it)"
    )
    report = run(inch_nut(), [INCH], INCH_TOOLS, engine=engine)
    (result,) = report.results
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "spanner-9/16in",
        "ring, full length",
    )
    assert (report.kit, report.kit_added, report.notes) == ("metric-home", tuple(INCH_TOOLS), ())
    assert report.exit_code == 0


def test_the_socket_alone_added_is_the_one_tried():
    (result,) = run(inch_nut(), [INCH], ["socket-9/16in"]).results
    assert result.tool == "socket-9/16in"
    assert {attempt.tool for attempt in result.attempts} == {"socket-9/16in"}


def test_an_added_tool_joins_whichever_kit_is_used():
    (without,) = run(m8_nut(), [M8], kit="imperial-home").results
    assert without.verdict is Verdict.NOT_COVERED
    (result,) = run(m8_nut(), [M8], ["spanner-13"], kit="imperial-home").results
    assert (result.verdict, result.tool) == (Verdict.TURNS, "spanner-13")


def test_a_rule_may_name_an_added_tool():
    rule = {**INCH, "tool": "socket-9/16in"}
    (without,) = run(inch_nut(), [rule]).results
    assert without.verdict is Verdict.NOT_COVERED
    (result,) = run(inch_nut(), [rule], ["socket-9/16in"]).results
    assert (result.verdict, result.tool) == (Verdict.TURNS, "socket-9/16in")


def test_one_the_kit_holds_already_is_noted_not_failed():
    report = run(m8_nut(), [M8], ["spanner-13", "spanner-9/16in"], kit="full")
    assert report.kit_added == ()
    assert report.notes == (
        "tool spanner-13: kit full holds it already",
        "tool spanner-9/16in: kit full holds it already",
    )
    assert report.exit_code == 0
    assert "NOTE tool spanner-13: kit full holds it already" in report.terminal_lines()


def test_an_added_tool_no_fastener_takes_is_noted():
    # Written for the wrong nut, most often, as a custom tool of no size here is (#75).
    report = run(m8_nut(), [M8], ["spanner-9/16in", "hex-key-12"])
    assert report.notes == (
        "tool spanner-9/16in, added to the kit: no fastener here takes a 9/16in spanner",
        "tool hex-key-12, added to the kit: no fastener here takes a 12 mm hex key",
    )
    assert report.results[0].tool == "spanner-13"


def test_an_added_tool_a_fastener_takes_or_a_rule_names_is_not_noted():
    assert run(inch_nut(), [INCH], INCH_TOOLS).notes == ()
    named = run(m8_nut(), [{**M8, "tool": "nut-driver-13"}], ["nut-driver-13"])
    assert named.notes == ()


def test_the_json_and_markdown_say_what_was_added():
    report = run(inch_nut(), [INCH], INCH_TOOLS)
    document = json.loads(report.json_text())
    assert (document["kit"], document["kit_added"]) == ("metric-home", INCH_TOOLS)
    assert "Kit `metric-home` with `spanner-9/16in` and `socket-9/16in` added, swings" in (
        report.markdown()
    )
    one = run(inch_nut(), [INCH], ["socket-9/16in"]).markdown()
    assert "Kit `metric-home` with `socket-9/16in` added, swings" in one
    plain = run(m8_nut(), [M8])
    assert json.loads(plain.json_text())["kit_added"] == []
    assert "Kit `metric-home`, swings" in plain.markdown()


def test_three_added_are_listed_with_commas():
    report = run(inch_nut(), [INCH], [*INCH_TOOLS, "spanner-24"])
    assert "with `spanner-9/16in`, `socket-9/16in` and `spanner-24` added" in report.markdown()


# ---------------------------------------------------------------------------
# The tools command lists them after the kit's own.
# ---------------------------------------------------------------------------


def test_the_listing_shows_them_as_the_kit_s_own_are_shown():
    lines = added_listing(METRIC_HOME, ("spanner-9/16in", "spanner-13", "hex-key-3/16in"), "w.yaml")
    assert lines[0] == "added to kit metric-home, from w.yaml (tried as its own):"
    (spanner,) = [line for line in lines if line.startswith("  spanner-")]
    assert spanner.split()[0] == "spanner-9/16in"
    (key,) = [line for line in lines if line.startswith("  hex-key-")]
    assert key.split()[0] == "hex-key-3/16in"
    assert lines[-1] == "already in kit metric-home: spanner-13"
    assert added_listing(METRIC_HOME, (), "w.yaml") == []


def test_the_tools_command_lists_the_added_after_the_kit_s_own(tmp_path):
    sidecar = tmp_path / "wrenchroom.yaml"
    sidecar.write_text(
        "tools:\n"
        "  - spanner-9/16in\n"
        "  - socket-9/16in\n"
        "  - {name: shop-spanner-24, type: spanner, across_flats: 24, length: 300}\n"
    )
    result = CliRunner().invoke(main, ["tools", "--config", str(sidecar)])
    assert result.exit_code == 0
    lines = result.output.splitlines()
    added = lines.index("added to kit metric-home, from wrenchroom.yaml (tried as its own):")
    custom = lines.index("custom tools, from wrenchroom.yaml (tried after the kit's own; mm):")
    assert lines.index("kit metric-home: " + METRIC_HOME.summary) < added < custom
    between = lines[added:custom]
    assert [line.split()[0] for line in between if line.startswith("  ")] == INCH_TOOLS


def test_the_tools_command_with_only_added_tools_lists_no_custom_ones(tmp_path):
    sidecar = tmp_path / "w.yaml"
    sidecar.write_text("tools: [spanner-13]\n")
    output = CliRunner().invoke(main, ["tools", "--config", str(sidecar)]).output
    assert "already in kit metric-home: spanner-13" in output
    assert "custom tools" not in output


def test_the_custom_listing_lists_no_built_in_tool():
    tools = Config.from_dict({"tools": ["spanner-13"]}).tools
    assert list(custom.listing(tools, "w.yaml")) == []


def test_imperial_home_has_no_metric_spanner_till_one_is_added():
    assert not IMPERIAL_HOME.holds("spanner-13")
    assert IMPERIAL_HOME.adding(["spanner-13"]).holds("spanner-13")
