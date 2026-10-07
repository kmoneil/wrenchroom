"""What each home kit makes of the bench, which is checked under `full`.

A kit takes tools away and changes nothing else. Under metric-home, the cells whose
tool is past it (24 mm for the glands, inch sizes for inch_pair) are not covered,
each naming the tool and the kits that have it, and every other cell comes out
exactly as under `full`. Under imperial-home it is the other way round: inch_pair
comes out exactly as under `full`, and every metric fastener is not covered, naming
its metric tool, unless it needs no sized tool at all: a Phillips or slotted driver
fits a screw whatever its thread is measured in, and a carriage bolt holds itself.
A sidecar's own tool (spec 5.3: short_key's) joins whichever kit is used, so its
cell comes out as under `full` in each.
"""

import pytest
from bench import KIT, check_bench, sidecar_and_truth

from wrenchroom.tools.kits import IMPERIAL_HOME, METRIC_HOME

_GLAND = "needs spanner-24, which kit metric-home does not hold (full has it)"

#: The bench sidecar's own tools: in every kit.
CUSTOM = {tool["name"] for tool in sidecar_and_truth()[0]["tools"]}

#: The bench's cells that need a tool metric-home doesn't hold, and why.
PAST_HOME = {
    "gland_rib_gland": _GLAND,
    "glands_apart_a_gland": _GLAND,
    "glands_apart_b_gland": _GLAND,
    "glands_close_a_gland": _GLAND,
    "glands_close_b_gland": _GLAND,
    "big_gland_gland": "needs spanner-41, which kit metric-home does not hold (full has it)",
    "big_tube_gland": "needs spanner-36, which kit metric-home does not hold (full has it)",
    "vented_gland_vent": _GLAND,
    "inch_pair_screw": (
        "needs hex-key-3/16in, which kit metric-home does not hold (imperial-home and full have it)"
    ),
    "inch_pair_nut": (
        "needs spanner-7/16in or socket-7/16in, which kit metric-home does not hold "
        "(imperial-home and full have it)"
    ),
    "torx_wall_screw": "needs torx-key-T30, which kit metric-home does not hold (full has it)",
}

#: Cells metric-home holds a tool for but can't turn without full's: the ball end.
#: The plain key is tried and blocked, which is the verdict, not "not covered".
HOME_BLOCKED = {
    "ball_tilt_screw": ["ball_tilt_ceiling"],
    "ball_shoulder_screw": ["ball_shoulder_ceiling"],
    "nut_tube_nut": ["nut_tube_tube"],
}

#: The bench's inch fasteners: all imperial-home can turn.
INCH = {"inch_pair_screw", "inch_pair_nut"}


def _by_name(report):
    return {entry["name"]: entry for entry in report.to_json_dict()["fasteners"]}


@pytest.fixture(scope="session")
def home_json(bench_dir):
    report = check_bench(bench_dir, kit=METRIC_HOME.name)
    assert report.kit == METRIC_HOME.name
    assert report.exit_code == 2  # not covered
    return _by_name(report)


@pytest.fixture(scope="session")
def inch_json(bench_dir):
    report = check_bench(bench_dir, kit=IMPERIAL_HOME.name)
    assert report.kit == IMPERIAL_HOME.name
    assert report.exit_code == 2
    return _by_name(report)


def test_the_bench_is_checked_with_the_full_kit(bench_report):
    assert KIT == "full"
    assert bench_report.kit == "full"


def test_only_the_cells_past_metric_home_change(home_json, bench_json):
    past = {
        name
        for name, e in bench_json.items()
        if e["tool"] and not METRIC_HOME.holds(e["tool"]) and e["tool"] not in CUSTOM
    }
    assert past == set(PAST_HOME) | set(HOME_BLOCKED)
    changed = {
        name
        for name, full in bench_json.items()
        if (home_json[name]["verdict"], home_json[name]["tool"], home_json[name]["how"])
        != (full["verdict"], full["tool"], full["how"])
    }
    assert changed == set(PAST_HOME) | set(HOME_BLOCKED)
    for name, reason in sorted(PAST_HOME.items()):
        assert home_json[name]["verdict"] == "not-covered", name
        assert home_json[name]["reason"] == reason, name
    for name, blockers in HOME_BLOCKED.items():
        assert home_json[name]["verdict"] == "blocked", name
        assert home_json[name]["blocked_by"] == blockers, name


def test_everything_else_is_the_same_report_under_metric_home(home_json, bench_json):
    for name, full in bench_json.items():
        if name not in PAST_HOME and name not in HOME_BLOCKED:
            assert home_json[name] == full, name


def test_imperial_home_turns_the_inch_pair_exactly_as_full_does(inch_json, bench_json):
    for name in INCH:
        assert inch_json[name] == bench_json[name], name
        assert IMPERIAL_HOME.holds(bench_json[name]["tool"]), name


def test_imperial_home_covers_nothing_metric_but_drivers(inch_json, bench_json):
    unsized = 0
    for name, full in bench_json.items():
        if name in INCH:
            continue
        entry = inch_json[name]
        if full["tool"] in CUSTOM:  # the sidecar's own: in this kit too
            assert entry == full, name
            continue
        if full["tool"] is None or full["tool"].startswith("driver-"):
            # Held by itself, or a driver's tip: no size for the kit to lack.
            assert entry == full, name
            unsized += 1
            continue
        assert entry["verdict"] == "not-covered", name
        assert entry["reason"].startswith("needs "), name
        assert "which kit imperial-home does not hold" in entry["reason"], name
        assert "in," not in entry["reason"].split(", which")[0], name  # metric tools named
    assert unsized == 4  # the carriage bolt, the well nut and the two Phillips screws
