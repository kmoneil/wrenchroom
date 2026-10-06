"""The check loop end to end: resolution, tool choice, verdicts, exit codes."""

import pytest

from fixture_models import SEAT_Z, nut_on_plate, screw_facing_wall
from wrenchroom.check import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.tools.hex_keys import ISO_2936
from wrenchroom.tools.sweep import CONTACT_OFFSET

M6_SOCKET = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}
KEY_5 = ISO_2936[5.0]
BOUNDARY = CONTACT_OFFSET + KEY_5.short_mm + KEY_5.radius


def run(assembly, *rules, **kwargs):
    return check(assembly, Config.from_dict({"fasteners": list(rules)}), **kwargs)


def test_the_trident_bolt_is_blocked_and_says_by_what():
    report = run(screw_facing_wall(16.4), M6_SOCKET)
    (result,) = report.results
    assert result.verdict is Verdict.BLOCKED
    assert result.tool == "hex-key-5"
    assert result.blockers == ("wall",)
    assert len(result.attempts) == 3
    assert report.exit_code == 1


def test_the_same_bolt_with_room_turns_by_the_short_leg():
    report = run(screw_facing_wall(BOUNDARY + 0.5), M6_SOCKET)
    (result,) = report.results
    assert result.verdict is Verdict.TURNS
    assert result.how == "short leg in"
    assert report.exit_code == 0


def test_axis_and_seat_resolve_from_the_geometry():
    report = run(screw_facing_wall(50), M6_SOCKET)
    (result,) = report.results
    assert result.axis == pytest.approx((0, 0, 1))
    assert result.seat == pytest.approx((0, 0, SEAT_Z))


def test_a_nut_resolves_its_free_face_and_takes_the_ring():
    report = run(nut_on_plate(), {"parts": "nut", "kind": "nut", "size": "M6"})
    (result,) = report.results
    assert result.verdict is Verdict.TURNS
    assert result.tool == "spanner-10"
    assert result.axis == pytest.approx((0, 0, 1))  # up: the plate covers the bottom
    assert result.seat[2] == pytest.approx(5.0)


def test_a_forced_tool_is_used():
    report = run(screw_facing_wall(50), {**M6_SOCKET, "tool": "hex-key-4"})
    (result,) = report.results
    assert result.tool == "hex-key-4"
    assert result.verdict is Verdict.TURNS


def test_a_carriage_bolt_holds_itself():
    report = run(screw_facing_wall(1.0), {"parts": "bolt", "head": "carriage"})
    (result,) = report.results
    assert result.verdict is Verdict.HELD
    assert result.how == "holds itself"
    assert report.exit_code == 0


def test_torx_is_not_covered_until_m6():
    report = run(screw_facing_wall(50), {**M6_SOCKET, "head": "torx"})
    (result,) = report.results
    assert result.verdict is Verdict.NOT_COVERED
    assert "Torx" in result.reason
    assert report.exit_code == 2


def test_a_sizeless_screw_is_not_covered_with_the_reason():
    report = run(screw_facing_wall(50), {"parts": "bolt", "kind": "screw", "head": "socket"})
    (result,) = report.results
    assert result.verdict is Verdict.NOT_COVERED
    assert "size unknown" in result.reason


def test_an_unmatched_rule_fails_the_run():
    report = run(screw_facing_wall(50), M6_SOCKET, {"parts": "ghost_*"})
    assert report.unmatched_rules == ("ghost_*",)
    assert report.exit_code == 2
    assert any("matched nothing" in line for line in report.terminal_lines())


def test_only_narrows_the_run():
    report = run(screw_facing_wall(50), M6_SOCKET, only="nothing_*")
    assert report.results == ()


def test_an_unknown_kit_is_a_loud_error():
    with pytest.raises(ValueError, match="unknown kit"):
        run(screw_facing_wall(50), M6_SOCKET, kit="mars-rover")


def test_the_json_document_has_the_spec_shape():
    report = run(screw_facing_wall(16.4), M6_SOCKET, model="trident.step")
    document = report.to_json_dict()
    assert document["model"] == "trident.step"
    assert document["summary"]["blocked"] == 1
    (entry,) = document["fasteners"]
    assert entry["name"] == "bolt"
    assert entry["verdict"] == "blocked"
    assert entry["blocked_by"] == ["wall"]
    assert entry["size"] == "M6"
    assert entry["stuck_on"] == []


def test_terminal_lines_lead_with_the_summary():
    report = run(screw_facing_wall(16.4), M6_SOCKET)
    lines = report.terminal_lines()
    assert lines[0].startswith("1 fasteners: 0 turn")
    assert any(line.startswith("FAIL bolt") for line in lines)
