"""What the home kit makes of the bench, which is checked under `full`.

The cells whose tool is past metric-home (24 mm, for the glands) are not covered
under it, each naming the tool and the kit that has it; every other cell comes out
exactly as under `full`, so a kit takes tools away and changes nothing else.
"""

import pytest
from bench import KIT, check_bench

from wrenchroom.tools.kits import METRIC_HOME

#: The bench's cells that need a tool metric-home doesn't hold: the five 24 mm glands.
PAST_HOME = {
    "gland_rib_gland",
    "glands_apart_a_gland",
    "glands_apart_b_gland",
    "glands_close_a_gland",
    "glands_close_b_gland",
}


@pytest.fixture(scope="session")
def home_json(bench_dir):
    report = check_bench(bench_dir, kit=METRIC_HOME.name)
    assert report.kit == METRIC_HOME.name
    assert report.exit_code == 2  # not covered
    return {entry["name"]: entry for entry in report.to_json_dict()["fasteners"]}


def test_the_bench_is_checked_with_the_full_kit(bench_report):
    assert KIT == "full"
    assert bench_report.kit == "full"


def test_only_the_cells_past_the_home_kit_change(home_json, bench_json):
    past = {
        name for name, e in bench_json.items() if e["tool"] and not METRIC_HOME.holds(e["tool"])
    }
    assert past == PAST_HOME
    changed = {
        name
        for name, full in bench_json.items()
        if (home_json[name]["verdict"], home_json[name]["tool"], home_json[name]["how"])
        != (full["verdict"], full["tool"], full["how"])
    }
    assert changed == PAST_HOME
    for name in sorted(PAST_HOME):
        entry = home_json[name]
        assert entry["verdict"] == "not-covered", name
        assert entry["reason"] == (
            "needs spanner-24, which kit metric-home does not hold (full has it)"
        ), name


def test_everything_else_is_the_same_report(home_json, bench_json):
    for name, full in bench_json.items():
        if name in PAST_HOME:
            continue
        assert home_json[name] == full, name
