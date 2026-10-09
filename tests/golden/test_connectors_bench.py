"""The bench's connectors (M9): each plug pulled off its receptacle, both engines.

plug_open's plug comes off up, 10 (7 in, plus 3); plug_shelf's is stuck under its
shelf; plug_cable's lead, its mate, comes with it through its panel. plug_tight's and
plug_latch's come off too: what fingers make of them is hand room's
(test_hand_room_bench.py).
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
    # Not one checked without a truth, nor one with a truth left unchecked; and every
    # one the sidecar's: no part of the bench is named like a connector besides.
    assert sorted(plugs) == sorted(connector_truth())
    assert {entry["source"] for entry in plugs.values()} == {"sidecar"}
    connectors = bench_report.connectors
    assert (connectors.named, connectors.unmatched_rules, connectors.unmatched_mates) == (
        (),
        (),
        (),
    )
    assert connectors.summary == {
        "connectors": 5,
        "unplugs": 4,
        "stuck": 1,
        "no_grip": 0,
        "no_latch_access": 0,
        "not_covered": 0,
    }


def test_the_bench_says_its_stuck_plug(bench_report):
    assert "5 connectors: 4 unplug, 1 stuck, 0 not covered" in bench_report.terminal_lines()
    assert "FAIL plug_shelf_plug  stuck  plug_shelf_shelf" in bench_report.terminal_lines()
