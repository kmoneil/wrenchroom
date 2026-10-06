"""Ball-end hex keys (spec 6.1): the long leg in at up to 25 degrees off the axis.

Tried after the plain key's three ways, from the full kit only: each tilt in 5 degree
steps, every way round, turning about the key's own leant axis on 60 degrees. The
cases are worked by hand in the docstrings.
"""

import math

import numpy as np
import pytest
from build123d import Box, Pos

from fixture_models import SEAT_Z, socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.tools.ball_end import BALL_END_KEYS, MAX_TILT_DEG, ROUND_STEP_DEG, TILTS, tilted
from wrenchroom.tools.hex_keys import ISO_2936
from wrenchroom.tools.kits import FULL, IMPERIAL_HOME, METRIC_HOME
from wrenchroom.tools.sweep import Mount

M6 = {"parts": "screw", "kind": "screw", "head": "socket", "size": "M6"}


def under_a_slotted_ceiling(slot_from):
    """An M6 socket head; a ceiling 20 over its head, slotted along +x from `slot_from`."""
    middle = SEAT_Z + 20 + 5  # the ceiling's underside 20 over the head's top
    ceiling = Pos(0, 0, middle) * Box(300, 300, 10) - Pos(slot_from + 30, 0, middle) * Box(
        60, 20, 12
    )
    return Assembly(
        [
            Part("screw", socket_screw()),
            Part("plate", Pos(0, 0, -5) * Box(200, 200, 10)),
            Part("ceiling", ceiling),
        ]
    )


def run(assembly, kit="full", engine="exact", rule=M6):
    config = Config.from_dict({"fasteners": [rule], "checks": {"detect": False}})
    (result,) = check(assembly, config, kit=kit, engine=engine).results
    return result


def test_the_keys_are_wera_s_arms_on_iso_2936_sections():
    arms = {3: (123, 21), 4: (137, 24), 5: (154, 27), 6: (172, 31), 8: (195, 37), 10: (224, 42)}
    assert sorted(BALL_END_KEYS) == sorted(arms)
    for af, (long, short) in arms.items():
        key = BALL_END_KEYS[af]
        assert (key.long_mm, key.short_mm) == (long, short)
        assert key.across_corners == ISO_2936[af].across_corners
        assert key.name == f"ball-end-key-{af:g}"


def test_the_tilts_reach_the_most_bondhus_and_wiha_give_and_no_further():
    assert MAX_TILT_DEG == 25.0
    assert TILTS == (10.0, 15.0, 20.0, 25.0)
    assert ROUND_STEP_DEG == 30.0


@pytest.mark.parametrize("axis", [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.6, -0.48, 0.64)])
def test_a_lean_is_the_tilt_off_the_axis_every_way_round(axis):
    axis = tuple(np.array(axis) / np.linalg.norm(axis))
    mount = Mount((1.0, 2.0, 3.0), axis)
    leans = [np.array(tilted(mount, 20.0, round_deg).axis) for round_deg in range(0, 360, 15)]
    for lean in leans:
        assert np.linalg.norm(lean) == pytest.approx(1.0)
        assert math.degrees(math.acos(float(lean @ np.array(axis)))) == pytest.approx(20.0)
    # Every way round: the leans' sideways parts spread over the whole circle.
    sideways = [lean - (lean @ np.array(axis)) * np.array(axis) for lean in leans]
    assert np.linalg.norm(np.sum(sideways, axis=0)) == pytest.approx(0.0, abs=1e-9)


def test_only_the_full_kit_holds_ball_end_keys():
    assert FULL.ball_end_keys == ("3", "4", "5", "6", "8", "10")
    assert METRIC_HOME.ball_end_keys == IMPERIAL_HOME.ball_end_keys == ()


def test_leant_25_deg_the_ball_end_turns_where_no_straight_key_can(engine):
    # The ball_tilt cell's geometry: slot from 4.5. Straight up, every way of the
    # 5 mm key meets the ceiling; leant 20 deg the leg's lower edge (3.02 out from
    # its axis, 7.28 off) is at 4.26, in the solid; leant 25 it is at 6.2, clear.
    result = run(under_a_slotted_ceiling(4.5), engine=engine)
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "ball-end-key-5",
        "ball end, 25 deg off the axis",
    )
    ways = [a.way for a in result.attempts]
    assert ways[:3] == ["driver straight in", "short leg in", "long leg in"]
    assert ways[3:] == [f"ball end, {t:g} deg off the axis" for t in TILTS]


def test_the_home_kit_has_only_the_straight_key():
    result = run(under_a_slotted_ceiling(4.5), kit="metric-home")
    assert result.verdict is Verdict.BLOCKED
    assert result.blockers == ("ceiling",)
    assert {a.tool for a in result.attempts} == {"hex-key-5"}


def test_a_slot_that_wants_more_than_25_deg_is_not_credited():
    # Slotted from 9.0: leant 25 deg the edge is at 6.2, still in the solid; a
    # 30 deg ball end (PB Swiss) might reach, but 25 is the most counted.
    result = run(under_a_slotted_ceiling(9.0))
    assert result.verdict is Verdict.BLOCKED
    assert all(not a.turns for a in result.attempts)


def test_a_size_with_no_ball_end_tries_the_plain_key_only():
    # An M3 socket head takes a 2.5 mm key: no ball-end 2.5 was read, so none is tried.
    rule = {**M6, "size": "M3"}
    result = run(under_a_slotted_ceiling(4.5), rule=rule)
    assert {a.tool for a in result.attempts} == {"hex-key-2.5"}
