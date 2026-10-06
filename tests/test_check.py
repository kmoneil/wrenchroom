"""The check loop end to end: resolution, tool choice, verdicts, exit codes; both engines."""

import pytest

from fixture_models import (
    SEAT_Z,
    gland_on_wall,
    nut_on_plate,
    nut_with_bolt_through,
    screw_facing_wall,
)
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.tools.hex_keys import ISO_2936
from wrenchroom.tools.sweep import CONTACT_OFFSET

M6_SOCKET = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}
KEY_5 = ISO_2936[5.0]
BOUNDARY = CONTACT_OFFSET + KEY_5.short_mm + KEY_5.radius


def run(engine, assembly, *rules, **kwargs):
    config = Config.from_dict({"fasteners": list(rules)})
    return check(assembly, config, engine=engine, **kwargs)


def test_a_screw_under_a_close_wall_is_blocked_and_says_by_what(engine):
    report = run(engine, screw_facing_wall(15.0), M6_SOCKET)
    (result,) = report.results
    assert result.verdict is Verdict.BLOCKED
    assert result.tool == "hex-key-5"
    assert result.blockers == ("wall",)
    assert len(result.attempts) == 3
    assert report.exit_code == 1


def test_the_same_bolt_with_room_turns_by_the_short_leg(engine):
    report = run(engine, screw_facing_wall(BOUNDARY + 0.5), M6_SOCKET)
    (result,) = report.results
    assert result.verdict is Verdict.TURNS
    assert result.how == "short leg in"
    assert report.exit_code == 0


def test_axis_and_seat_resolve_from_the_geometry(engine):
    report = run(engine, screw_facing_wall(50), M6_SOCKET)
    (result,) = report.results
    assert result.axis == pytest.approx((0, 0, 1))
    assert result.seat == pytest.approx((0, 0, SEAT_Z))


def test_a_nut_resolves_its_free_face_and_takes_the_ring(engine):
    report = run(engine, nut_on_plate(), {"parts": "nut", "kind": "nut", "size": "M6"})
    (result,) = report.results
    assert result.verdict is Verdict.TURNS
    assert result.tool == "spanner-10"
    assert result.axis == pytest.approx((0, 0, 1))  # up: the plate covers the bottom
    assert result.seat[2] == pytest.approx(5.0)


def test_a_forced_tool_is_used(engine):
    report = run(engine, screw_facing_wall(50), {**M6_SOCKET, "tool": "hex-key-4"})
    (result,) = report.results
    assert result.tool == "hex-key-4"
    assert result.verdict is Verdict.TURNS


def test_a_carriage_bolt_holds_itself(engine):
    report = run(engine, screw_facing_wall(1.0), {"parts": "bolt", "head": "carriage"})
    (result,) = report.results
    assert result.verdict is Verdict.HELD
    assert result.how == "holds itself"
    assert report.exit_code == 0


def test_torx_is_not_covered_until_m6(engine):
    report = run(engine, screw_facing_wall(50), {**M6_SOCKET, "head": "torx"})
    (result,) = report.results
    assert result.verdict is Verdict.NOT_COVERED
    assert "Torx" in result.reason
    assert report.exit_code == 2


def test_a_sizeless_screw_is_not_covered_with_the_reason(engine):
    report = run(
        engine, screw_facing_wall(50), {"parts": "bolt", "kind": "screw", "head": "socket"}
    )
    (result,) = report.results
    assert result.verdict is Verdict.NOT_COVERED
    assert "size unknown" in result.reason


def test_an_unmatched_rule_fails_the_run(engine):
    report = run(engine, screw_facing_wall(50), M6_SOCKET, {"parts": "ghost_*"})
    assert report.unmatched_rules == ("ghost_*",)
    assert report.exit_code == 2
    assert any("matched nothing" in line for line in report.terminal_lines())


def test_only_narrows_the_run(engine):
    report = run(engine, screw_facing_wall(50), M6_SOCKET, only="nothing_*")
    assert report.results == ()


def test_an_unknown_kit_is_a_loud_error(engine):
    with pytest.raises(ValueError, match="unknown kit"):
        run(engine, screw_facing_wall(50), M6_SOCKET, kit="mars-rover")


def test_the_json_document_has_the_spec_shape(engine):
    report = run(engine, screw_facing_wall(15.0), M6_SOCKET, model="bench.step")
    document = report.to_json_dict()
    assert document["model"] == "bench.step"
    assert document["summary"]["blocked"] == 1
    (entry,) = document["fasteners"]
    assert entry["name"] == "bolt"
    assert entry["verdict"] == "blocked"
    assert entry["blocked_by"] == ["wall"]
    assert entry["size"] == "M6"
    assert entry["stuck_on"] == []


def test_terminal_lines_lead_with_the_summary(engine):
    report = run(engine, screw_facing_wall(15.0), M6_SOCKET)
    lines = report.terminal_lines()
    assert lines[0].startswith("1 fasteners: 0 turn")
    assert any(line.startswith("FAIL bolt") for line in lines)


# ---------------------------------------------------------------------------
# The three resolution bugs the bench prototyping found (handoff section 8).
# ---------------------------------------------------------------------------


def test_a_nut_with_its_bolt_through_it_still_orients(engine):
    # Bug A: the free-face probe is an annulus, so the bolt's protruding end
    # doesn't read as "covered" and the nut resolves without an axis hint.
    # The bolt through it is found by its name too; this test is about the nut.
    nut_rule = {"parts": "nut", "kind": "nut", "size": "M6"}
    report = run(engine, nut_with_bolt_through(), nut_rule, only="nut")
    (result,) = report.results
    assert result.verdict is Verdict.TURNS
    assert result.tool == "spanner-10"
    assert result.axis == pytest.approx((0, 0, 1))


def test_a_gland_orients_by_its_hex_not_its_extremes(engine):
    # Bug B: the probes sit at the hex band's ends; the stub below is inside the
    # wall (covered side), the dome above is the gland's own body (free side).
    report = run(  # a 24 mm hex: the full kit's (metric-home stops at 19)
        engine,
        gland_on_wall(),
        {"parts": "gland", "kind": "nut", "size": "M16", "socket": False},
        kit="full",
    )
    (result,) = report.results
    assert result.verdict is Verdict.TURNS
    assert result.tool == "spanner-24"
    assert result.axis == pytest.approx((0, 0, 1))


def test_the_ring_sits_on_the_hex_not_the_dome(engine):
    # Bug C: with a rib beside the hex, a ring placed on the dome would clear it
    # and pass falsely; placed on the hex band it must report the rib.
    report = run(
        engine,
        gland_on_wall(rib=True),
        {"parts": "gland", "kind": "nut", "size": "M16", "socket": False, "axis": "+z"},
        kit="full",
    )
    (result,) = report.results
    assert result.verdict is Verdict.BLOCKED
    assert "rib" in result.blockers


def test_the_json_document_carries_its_schema_number(engine):
    report = run(engine, screw_facing_wall(15.0), M6_SOCKET)
    assert report.to_json_dict()["schema"] == 1
