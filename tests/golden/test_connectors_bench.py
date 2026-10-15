"""The bench's connectors (M9): each plug pulled off its receptacle, both engines.

pull_open's plug comes off up, 10 (7 in, plus 3); pull_shelf's is stuck under its
shelf; pull_cable's lead, its mate, comes with it through its panel. pull_tight's and
pull_latch's come off too: what fingers make of them is hand room's
(test_hand_room_bench.py). byname's three are found by their names alone, "plug"
first in two (issue #157) and a screw terminal's the third (issue #166), and its
cover, named for a plug, is listed. pull_halved's shroud is two solids of one part,
and one receptacle (issue #200). pull_round's plug and shroud are round, and it comes
off as pull_open's does (issue #222).
"""

import pytest
from bench import connector_truth

TRAVEL_MM = 1e-9  # found to 0.1 mm


def _truth_params():
    return [pytest.param(name, entry, id=name) for name, entry in sorted(connector_truth().items())]


@pytest.fixture(scope="module")
def plugs(bench_report):
    return {entry["name"]: entry for entry in bench_report.to_json_dict()["connectors"]["results"]}


@pytest.mark.parametrize(("name", "expected"), _truth_params())
def test_connector_truth(name, expected, plugs):
    entry = plugs.get(name)
    assert entry is not None, f"{name} missing from the report"
    for key, want in expected.items():
        got = entry[key]
        if key == "travel":
            assert got == pytest.approx(want, abs=TRAVEL_MM), f"{name}.{key}"
        elif isinstance(want, list) and key != "axis":
            assert sorted(got) == sorted(want), f"{name}.{key}"
        else:
            assert got == want, f"{name}.{key}"


def test_every_connector_the_bench_checks_has_its_truth(plugs, bench_report):
    # Not one checked without a truth, nor one with a truth left unchecked; every one
    # the sidecar's but byname's three, found by their names (#157, #166); and one part
    # named like a connector besides, byname's cover.
    assert sorted(plugs) == sorted(connector_truth())
    by_name = sorted(name for name, entry in plugs.items() if entry["source"] == "name")
    assert by_name == ["byname_plug_fan_2", "byname_plug_motor", "byname_screw_terminal_plug"]
    assert {entry["source"] for entry in plugs.values()} == {"sidecar", "name"}
    connectors = bench_report.connectors
    assert (connectors.named, connectors.unmatched_rules, connectors.unmatched_mates) == (
        ("byname_plug_cover",),
        (),
        (),
    )
    assert connectors.summary == {
        "connectors": 10,
        "unplugs": 9,
        "stuck": 1,
        "no_grip": 0,
        "no_latch_access": 0,
        "not_covered": 0,
    }


def test_the_bench_says_its_stuck_plug(bench_report):
    assert "10 connectors: 9 unplug, 1 stuck, 0 not covered" in bench_report.terminal_lines()
    assert "FAIL pull_shelf_plug  stuck  pull_shelf_shelf" in bench_report.terminal_lines()
