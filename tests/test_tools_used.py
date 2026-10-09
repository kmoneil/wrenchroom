"""The tools a model needs (M8): `wrenchroom tools --used`, the JSON, Markdown and view.

Every check records the tool each fastener ended up needing; the list is them, one
line per tool, with how many fasteners need it and why an unusual one is: outside
the default kit, needed by one or two fasteners, or the only tool reaching one (a
ball end, a stubby). Built here from results written by hand, so each rule is seen
alone; the bench's own list is held to its snapshot in test_bench.py.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from wrenchroom.cli import main
from wrenchroom.fasteners import Fastener, Kind
from wrenchroom.report import FastenerResult, Report, Verdict
from wrenchroom.used import tools_used

BRACKET = Path(__file__).parents[1] / "examples" / "bracket.step"
T, H, B, S, N = Verdict.TURNS, Verdict.HELD, Verdict.BLOCKED, Verdict.STUCK, Verdict.NOT_COVERED


def result(name, verdict=T, tool="hex-key-4", how="driver straight in", **more):
    fastener = Fastener(name=name, kind=Kind.NUT if "nut" in name else Kind.SCREW)
    if verdict in (B, N):
        tool = tool if verdict is B else None
        how = None
    return FastenerResult(fastener, verdict, tool=tool, how=how, **more)


def used(*results, kit="full"):
    return tools_used(Report("model.step", kit, tuple(results)))


def by_tool(listing):
    return {use.tool: use for use in listing.uses}


# ---------------------------------------------------------------------------
# A line per tool.
# ---------------------------------------------------------------------------


def test_one_line_per_tool_counting_its_fasteners_family_by_family_smallest_first():
    listing = used(
        result("a", tool="spanner-13", how="ring, full length"),
        result("b", tool="hex-key-4"),
        result("c", tool="hex-key-2.5"),
        result("d", tool="hex-key-5/32in"),  # 3.97: between 2.5 and 4
        result("e", tool="hex-key-4"),
        result("f", tool="driver-ph2"),
        result("g", tool="hex-key-4"),
    )
    assert [(use.tool, use.fasteners) for use in listing.uses] == [
        ("hex-key-2.5", ("c",)),
        ("hex-key-5/32in", ("d",)),
        ("hex-key-4", ("b", "e", "g")),
        ("spanner-13", ("a",)),
        ("driver-ph2", ("f",)),
    ]
    assert listing.families == "3 hex keys, 1 spanner, 1 driver"


def test_a_held_fastener_counts_its_holding_tool_and_a_joint_needs_two_at_once():
    listing = used(
        result("bolt", tool="spanner-13", how="ring, full length", pair="nut"),
        result("nut", H, tool="spanner-13", how="open end, full length", pair="bolt"),
        result("bolt_2", tool="spanner-13", how="ring, full length", pair="nut_2"),
        result("nut_2", H, tool="spanner-10", how="ring, full length", pair="bolt_2"),
    )
    tools = by_tool(listing)
    assert tools["spanner-13"].fasteners == ("bolt", "nut", "bolt_2")
    assert tools["spanner-13"].at_once == 2
    assert tools["spanner-10"].at_once == 1  # its bolt takes a 13
    assert "2 at once on a joint" in tools["spanner-13"].said()


def test_a_stuck_fastener_needs_its_tool_and_a_failure_has_none_yet():
    listing = used(
        result("stuck", S, tool="hex-key-5", how="short leg in"),
        result("blocked", B, tool="hex-key-5"),
        result("covered", N),
    )
    assert by_tool(listing)["hex-key-5"].fasteners == ("stuck",)
    assert listing.without == (("blocked", B), ("covered", N))
    assert listing.apart() == ["no tool yet: 1 blocked, 1 not-covered (wrenchroom check says why)"]


def test_by_hand_and_held_by_itself_need_no_tool():
    listing = used(
        result("thumb_screw", tool="hand", how="fingers round its head"),
        result("carriage_bolt", H, tool=None, how="holds itself"),
        result("trapped_nut", H, tool=None, how="held by its trap in block"),
    )
    assert listing.uses == ()
    assert listing.apart() == [
        "by hand: 1 (thumb_screw)",
        "no tool needed: 2, held by themselves or a trap",
    ]
    assert listing.lines()[0] == "0 tools this model needs (kit full): none"


def test_every_fastener_is_in_the_list_somewhere():
    results = [
        result("a"),
        result("b", H, tool="spanner-13", how="open end, full length"),
        result("c", S, tool="hex-key-5", how="short leg in"),
        result("d", tool="hand", how="fingers round it"),
        result("e", H, tool=None, how="holds itself"),
        result("f", B, tool="hex-key-5"),
        result("g", N),
    ]
    listing = used(*results)
    seen = [n for use in listing.uses for n in use.fasteners]
    seen += [*listing.by_hand, *listing.no_tool, *(name for name, _ in listing.without)]
    assert sorted(seen) == [r.fastener.name for r in results]


# ---------------------------------------------------------------------------
# Unusual, by definition.
# ---------------------------------------------------------------------------


def test_a_tool_the_default_kit_lacks_is_unusual():
    listing = used(*(result(f"s{i}", tool="torx-key-T25") for i in range(3)))
    (use,) = listing.uses
    assert (use.in_default_kit, use.unusual) == (False, ("outside_default_kit",))
    assert use.said() == ("not in metric-home",)


@pytest.mark.parametrize(("count", "few"), [(1, True), (2, True), (3, False)])
def test_a_tool_one_or_two_fasteners_need_is_unusual_and_names_them(count, few):
    listing = used(*(result(f"s{i}") for i in range(count)))
    (use,) = listing.uses
    assert use.in_default_kit  # metric-home holds a 4 mm key
    assert ("few" in use.unusual) is few
    names = ", ".join(f"s{i}" for i in range(count))
    assert use.said() == ((f"only {names}",) if few else ())


def test_a_ball_end_is_the_only_tool_reaching_its_fastener():
    listing = used(result("arm_pin", tool="ball-end-key-4", how="ball end, 20 deg off the axis"))
    (use,) = listing.uses
    assert use.only_way == ("arm_pin",)
    assert use.unusual == ("outside_default_kit", "only_way")
    assert use.said() == ("not in metric-home", "no straight key gets in at arm_pin")


def test_a_stubby_is_a_tool_of_its_own_and_the_only_one_reaching_its_fastener():
    listing = used(
        result("tight_nut", tool="spanner-13", how="ring, stubby"),
        *(result(f"n{i}", tool="spanner-13", how="ring, full length") for i in range(3)),
    )
    tools = by_tool(listing)
    assert tools["spanner-13"].fasteners == ("n0", "n1", "n2")
    stubby = tools["spanner-13, stubby"]
    assert (stubby.fasteners, stubby.only_way, stubby.in_default_kit) == (
        ("tight_nut",),
        ("tight_nut",),
        True,  # metric-home's 13s come stubby too
    )
    assert stubby.said() == ("no full-length spanner swings at tight_nut",)
    assert [use.tool for use in listing.uses] == ["spanner-13", "spanner-13, stubby"]


def test_many_fasteners_are_named_a_few_then_how_many_more():
    listing = used(*(result(f"pin_{i}", tool="ball-end-key-4", how="ball end") for i in range(5)))
    (use,) = listing.uses
    assert use.said()[1] == "no straight key gets in at pin_0, pin_1, pin_2 and 2 more"


def test_a_sidecar_s_own_tool_is_outside_the_default_kit():
    listing = used(*(result(f"s{i}", tool="shop-spanner-23", how="ring") for i in range(3)))
    assert listing.uses[0].said() == ("not in metric-home",)
    assert listing.families == "1 other"


def test_the_states_a_tool_is_needed_in():
    listing = used(result("a"), result("b", state="lid-off"), result("c"))
    assert listing.uses[0].states == (None, "lid-off")


# ---------------------------------------------------------------------------
# In each report.
# ---------------------------------------------------------------------------


def report_of(*results):
    return Report("model.step", "full", tuple(results))


def test_the_json_carries_the_list():
    report = report_of(
        result("a", tool="ball-end-key-4", how="ball end"),
        result("b", B, tool="hex-key-4"),
        result("c", tool="hand", how="fingers round it"),
    )
    document = json.loads(report.json_text())
    assert document["tools_used"] == {
        "default_kit": "metric-home",
        "tools": [
            {
                "tool": "ball-end-key-4",
                "count": 1,
                "fasteners": ["a"],
                "at_once": 1,
                "in_default_kit": False,
                "unusual": ["outside_default_kit", "only_way"],
                "states": [None],
            }
        ],
        "by_hand": ["c"],
        "no_tool": [],
        "without": [{"name": "b", "verdict": "blocked"}],
    }


def test_the_markdown_lists_the_tools_after_the_summary_table_names_in_code_spans():
    report = report_of(
        result("odd|name", tool="ball-end-key-4", how="ball end"),
        *(result(f"s{i}") for i in range(3)),
        result("thumb", tool="hand", how="fingers round it"),
    )
    markdown = report.markdown()
    assert markdown.index("| Fasteners | Tool |") < markdown.index("#### Tools")
    section = markdown.split("#### Tools")[1]
    assert "| `hex-key-4` | 3 |  |" in section
    assert (
        "| `ball-end-key-4` | 1 | not in metric-home; no straight key gets in at `odd\\|name` |"
        in (section)
    )
    assert "- By hand: 1 (`thumb`)" in section


def test_no_result_no_tools_section():
    assert "#### Tools" not in report_of().markdown()


# ---------------------------------------------------------------------------
# The command.
# ---------------------------------------------------------------------------


def test_tools_used_lists_the_example_s_tools_and_exits_0():
    run = CliRunner().invoke(main, ["tools", "--used", str(BRACKET)])
    assert run.exit_code == 0, run.output
    assert run.output.splitlines() == [
        "3 tools this model needs (kit metric-home): 1 hex key, 2 spanners",
        "  hex-key-5              x1      only front_screw",
        "  spanner-10             x1      only side_bolt",
        "  spanner-13             x2      only clamp_bolt, clamp_nut; 2 at once on a joint",
        "no tool yet: 1 blocked (wrenchroom check says why)",
    ]


def test_tools_used_with_a_broken_sidecar_exits_2(tmp_path):
    config = tmp_path / "bad.yaml"
    config.write_text("fasteners: [{parts: x, kind: bolt}]\n", encoding="utf-8")
    run = CliRunner().invoke(main, ["tools", "--used", str(BRACKET), "--config", str(config)])
    assert run.exit_code == 2
    assert run.output.startswith("error: ")


@pytest.mark.parametrize("flag", [["--state", "lid-off"], ["--exact"]])
def test_a_check_s_options_without_a_model_are_a_usage_error(flag):
    run = CliRunner().invoke(main, ["tools", *flag])
    assert run.exit_code == 2
    assert "--state and --exact go with --used MODEL" in run.output


def test_tools_used_checks_with_the_kit_it_is_given():
    # The bracket's metric fasteners under the inch kit: none has its tool.
    run = CliRunner().invoke(main, ["tools", "--used", str(BRACKET), "--kit", "imperial-home"])
    assert run.exit_code == 0, run.output
    assert run.output.splitlines() == [
        "0 tools this model needs (kit imperial-home): none",
        "no tool yet: 5 not-covered (wrenchroom check says why)",
    ]
