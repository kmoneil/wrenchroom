"""Torx keys: ISO 10664 sizes, the longest arms makers sell, the full kit's alone.

A Torx key is swept as a hex key is; these tests hold its numbers to their sources,
the thread-to-size table to the screw standards, and the kits to the spec (Torx keys
T10 to T40, in `full` only).
"""

import pytest

from fixture_models import screw_facing_wall
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.fasteners import TORX_SIZE
from wrenchroom.report import Verdict
from wrenchroom.tools.kits import FULL, IMPERIAL_HOME, METRIC_HOME
from wrenchroom.tools.torx_keys import ISO_10664

IN = 25.4

#: ISO 10664:2014 Table 1, A (point to point), mm.
A = {
    "T6": 1.75,  # M2's (issue #83)
    "T8": 2.40,  # M2.5's
    "T10": 2.80,
    "T15": 3.35,
    "T20": 3.95,
    "T25": 4.50,
    "T27": 5.10,
    "T30": 5.60,
    "T40": 6.75,
}

#: Each maker's (long, short) arms, mm: Wera 967 SPKL, Bondhus long, Eklind long (inches).
ARMS = {
    "T6": ((55, 16), (2.95 * IN, 0.61 * IN)),  # Wera makes no long T6
    "T8": ((76, 16), (67, 16), (3.15 * IN, 0.61 * IN)),
    "T10": ((85, 17), (80, 19), (3.38 * IN, 0.66 * IN)),
    "T30": ((122, 24), (116, 26), (4.50 * IN, 0.94 * IN)),
    "T40": ((132, 27), (125, 28), (4.88 * IN, 1.03 * IN)),
}


def test_the_keys_are_iso_10664_t6_to_t40():
    assert list(ISO_10664) == list(A)
    for size, key in ISO_10664.items():
        assert key.point_to_point == A[size]
        assert key.radius == A[size] / 2
        assert key.name == f"torx-key-{size}"
        assert key.long_mm > key.short_mm


@pytest.mark.parametrize("size", sorted(ARMS))
def test_each_arm_is_the_longest_any_maker_sells(size):
    key = ISO_10664[size]
    assert key.long_mm == pytest.approx(max(long for long, _ in ARMS[size]))
    assert key.short_mm == pytest.approx(max(short for _, short in ARMS[size]))


def test_the_thread_takes_the_size_the_screw_standards_say():
    # The machine screws'; the tapping screws', ISO 14585's, are test_tapping.py's.
    assert {size: torx for size, torx in TORX_SIZE.items() if not size.startswith("ST")} == {
        "M2": "T6",
        "M2.5": "T8",
        "M3": "T10",
        "M4": "T20",
        "M5": "T25",
        "M6": "T30",
        "M8": "T45",
        "M10": "T50",
        "M12": "T55",
    }


def test_only_the_full_kit_holds_torx_keys():
    assert FULL.torx_keys == tuple(A)
    assert METRIC_HOME.torx_keys == IMPERIAL_HOME.torx_keys == ()
    assert FULL.holds("torx-key-T30")
    assert not METRIC_HOME.holds("torx-key-T30")
    assert not FULL.holds("torx-key-T45")


def run(rule, kit="full", engine="exact", gap=50.0):
    config = Config.from_dict({"fasteners": [{"parts": "bolt", "kind": "screw", **rule}]})
    (result,) = check(screw_facing_wall(gap), config, kit=kit, engine=engine).results
    return result


def test_an_m6_torx_turns_with_its_t30_on_either_engine(engine):
    result = run({"head": "torx", "size": "M6"}, engine=engine)
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "torx-key-T30",
        "short leg in",
    )


def test_a_lower_wall_stops_the_t30_where_its_arm_meets_it():
    # Bend at 26.3, arm r 2.8: the arm reaches 29.1. A wall at 28 is in its way.
    result = run({"head": "torx", "size": "M6"}, gap=28.0)
    assert result.verdict is Verdict.BLOCKED
    assert result.blockers == ("wall",)


def test_an_m8_torx_needs_a_key_no_kit_holds():
    result = run({"head": "torx", "size": "M8"})
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == "needs torx-key-T45, which kit full does not hold; no kit has it"


def test_an_inch_torx_head_has_no_size():
    result = run({"head": "torx", "size": "1/4"})
    assert result.reason == "no Torx size for a 1/4 head"


@pytest.mark.parametrize(
    ("tool", "verdict", "reason"),
    [
        ("torx-key-T30", Verdict.TURNS, None),
        ("torx-key-T99", Verdict.NOT_COVERED, "no Torx key T99: the tables hold T10 to T40"),
    ],
)
def test_a_forced_torx_key(tool, verdict, reason):
    result = run({"head": "torx", "size": "M6", "tool": tool})
    assert result.verdict is verdict
    assert result.reason == reason
    if verdict is Verdict.TURNS:
        assert result.tool == tool


def test_a_forced_torx_key_must_be_in_the_kit():
    result = run({"head": "torx", "size": "M6", "tool": "torx-key-T30"}, kit="metric-home")
    assert result.reason == "needs torx-key-T30, which kit metric-home does not hold (full has it)"
