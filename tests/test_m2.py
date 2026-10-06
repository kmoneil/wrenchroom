"""M2: pairs, extraction, states; each mechanism alone, hand-computed, on both engines."""

import pytest
from build123d import Box, Compound, Pos, export_step

from fixture_models import (
    bolt_with_slotted_nut,
    nut_with_bolt_through,
    screw_facing_wall,
    slotted_pocket,
    socket_screw,
)
from wrenchroom.assembly import Assembly, Part
from wrenchroom.check import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict

M6_SOCKET = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}
M8_PAIR = [
    {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"},
    {"parts": "nut", "kind": "nut", "size": "M8"},
]


def run(engine, assembly, config_dict, **kwargs):
    return check(assembly, Config.from_dict(config_dict), engine=engine, **kwargs)


# ---------------------------------------------------------------------- pairs


def test_a_nut_that_only_holds_passes_through_its_turning_bolt(engine):
    report = run(engine, bolt_with_slotted_nut(), {"fasteners": M8_PAIR})
    by_name = {r.fastener.name: r for r in report.results}
    bolt, nut = by_name["bolt"], by_name["nut"]
    assert bolt.verdict is Verdict.TURNS
    assert bolt.pair == "nut"
    assert nut.verdict is Verdict.HELD
    assert nut.tool == "spanner-13"
    assert nut.pair == "bolt"
    assert report.exit_code == 0


def test_two_holding_sides_fail_with_the_reason(engine):
    report = run(engine, bolt_with_slotted_nut(head_boxed=True), {"fasteners": M8_PAIR})
    by_name = {r.fastener.name: r for r in report.results}
    assert by_name["bolt"].verdict is Verdict.BLOCKED
    assert by_name["nut"].verdict is Verdict.BLOCKED
    assert "does not turn" in by_name["nut"].reason
    assert report.exit_code == 1


def test_a_forced_pair_overrides_and_an_unknown_name_warns(engine):
    config = {
        "fasteners": [
            {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M6"},
            {"parts": "nut", "kind": "nut", "size": "M6"},
        ],
        "pairs": [["bolt", "nut"]],
    }
    report = run(engine, nut_with_bolt_through(), config)
    assert all(r.pair for r in report.results)

    config["pairs"] = [["bolt", "ghost"]]
    report = run(engine, nut_with_bolt_through(), config)
    assert any("ghost" in w for w in report.warnings)
    assert report.exit_code == 2


def test_a_tapped_screw_that_only_holds_is_blocked(engine):
    # No nut anywhere: holding is worthless, and the reason says so.
    # Seat at 26; the short leg's arm swings at 26 + 0.3 + 33 = 59.3, inside the
    # slot band (50..68); the ceiling at 71 stops the driver and the long leg.
    assembly = Assembly(
        [
            Part("bolt", socket_screw()),
            Part("slot", slotted_pocket(18.0, 50, 68, pocket_r=12.0, arm_half_width=2.835)),
            Part("ceiling", Pos(0, 0, 76) * Box(300, 300, 10)),
        ]
    )
    report = run(engine, assembly, {"fasteners": [M6_SOCKET]})
    (result,) = report.results
    assert result.verdict is Verdict.BLOCKED
    assert "it has no nut" in result.reason


# ------------------------------------------------------------------ extraction


def test_a_screw_that_turns_but_cannot_come_out_is_stuck(engine):
    # Turns by the short leg (36.1 < 45) but 50 of shank must rise into a wall at 45.
    report = run(engine, screw_facing_wall(45.0, length=50.0), {"fasteners": [M6_SOCKET]})
    (result,) = report.results
    assert result.verdict is Verdict.STUCK
    assert result.stuck_on == ("wall",)
    assert result.how == "short leg in"
    assert report.exit_code == 1


def test_extraction_clear_by_ten_is_not_stuck(engine):
    report = run(engine, screw_facing_wall(60.0, length=50.0), {"fasteners": [M6_SOCKET]})
    (result,) = report.results
    assert result.verdict is Verdict.TURNS


def test_a_nut_is_never_extracted(engine):
    rules = {"fasteners": [{"parts": "nut", "kind": "nut", "size": "M6"}]}
    report = run(engine, nut_with_bolt_through(), rules)
    (result,) = report.results
    assert result.verdict is Verdict.TURNS
    assert result.stuck_on == ()


# --------------------------------------------------------------------- states


WALL_CASE = {"fasteners": [M6_SOCKET]}


def test_a_fastener_pinned_to_a_remove_state_passes_there(engine):
    config = {
        "fasteners": [{**M6_SOCKET, "state": "lid-off"}],
        "states": {"lid-off": {"remove": ["wall"]}},
    }
    report = run(engine, screw_facing_wall(15.0), config)
    (result,) = report.results
    assert result.verdict is Verdict.TURNS
    assert result.how == "driver straight in"
    assert result.state == "lid-off"


def test_try_states_retries_and_reports_where_it_passed(engine):
    config = {
        "fasteners": [M6_SOCKET],
        "states": {"open": {"remove": ["wall"]}},
        "checks": {"try_states": ["open"]},
    }
    report = run(engine, screw_facing_wall(15.0), config)
    (result,) = report.results
    assert result.verdict is Verdict.TURNS
    assert result.state == "open"


def test_a_state_remove_glob_matching_nothing_warns(engine):
    config = {
        "fasteners": [{**M6_SOCKET, "state": "open"}],
        "states": {"open": {"remove": ["ghost_*"]}},
    }
    report = run(engine, screw_facing_wall(60.0), config)
    assert any("ghost_*" in w for w in report.warnings)
    assert report.exit_code == 2


def test_base_chains_accumulate_removals(engine):
    config = {
        "fasteners": [{**M6_SOCKET, "state": "fully-open"}],
        "states": {
            "service": {"remove": ["wall"]},
            "fully-open": {"base": "service", "remove": ["bystander"]},
        },
    }
    assembly = Assembly(
        [
            Part("bolt", socket_screw()),
            Part("wall", Pos(0, 0, 46) * Box(400, 400, 10)),
            Part("bystander", Pos(0, 0, 150) * Box(400, 400, 10)),
        ]
    )
    report = run(engine, assembly, config)
    (result,) = report.results
    assert result.verdict is Verdict.TURNS
    assert result.how == "driver straight in"  # both obstacles off


def test_an_alternate_model_state_is_loaded_and_matched_by_name(engine, tmp_path):
    blocked = screw_facing_wall(15.0)
    moved = screw_facing_wall(300.0)
    for name, assembly in (("main.step", blocked), ("moved.step", moved)):
        shapes = []
        for part in assembly:
            part.shape.label = part.name
            shapes.append(part.shape)
        export_step(Compound(children=shapes), str(tmp_path / name))
    config = {
        "fasteners": [M6_SOCKET],
        "states": {"lever-up": {"model": "moved.step"}},
        "checks": {"try_states": ["lever-up"]},
    }
    report = check(
        Assembly.from_step(tmp_path / "main.step"),
        Config.from_dict(config),
        model_dir=tmp_path,
        engine=engine,
    )
    (result,) = report.results
    assert result.verdict is Verdict.TURNS
    assert result.state == "lever-up"


def test_the_state_override_parameter_wins(engine):
    config = {
        "fasteners": [M6_SOCKET],
        "states": {"open": {"remove": ["wall"]}},
    }
    report = run(engine, screw_facing_wall(15.0), config, state="open")
    (result,) = report.results
    assert result.verdict is Verdict.TURNS
    with pytest.raises(ValueError, match="unknown state"):
        run(engine, screw_facing_wall(15.0), config, state="ghost")
