"""Detection wired up (M4): how a name and a solid make a fastener, and check uses it.

The merge rules, one test each: a drive the solid shows outranks the name; the
name outranks a guess from the head's outline; a size the drive settles outranks
the name's, which outranks a measured shank; a gland takes no size; a carriage
bolt needs its square neck. Then the check: detection fills in for parts no rule
names, a rule outranks it, ignored parts and `detect: false` keep it out, and the
tools take the measured across-flats when there is one.
"""

import sys
from pathlib import Path

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import (
    MINOR,
    hex_bolt,
    hex_nut,
    hex_prism,
    pan_phillips,
    socket_screw,
)
from fixture_models import gland_on_wall, screw_facing_wall
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config, ConfigError
from wrenchroom.detect import NO_SQUARE_NECK, describe, find_fasteners, read_name
from wrenchroom.fasteners import Head, Kind
from wrenchroom.report import Verdict

sys.path.insert(0, str(Path(__file__).parent / "golden"))
import parts as bench_parts


def detected(name, shape):
    return describe(Part(name, shape), read_name(name))


# ---------------------------------------------------------------------------
# The merge, field by field.
# ---------------------------------------------------------------------------


def test_a_drive_the_solid_shows_outranks_the_name():
    found = detected("hex bolt M6x20", socket_screw("M6"))
    assert found.head is Head.SOCKET
    assert found.drive_af == pytest.approx(5.0)
    assert found.source == "name+geometry"
    # It says what the name said, for a person to settle, and is less sure.
    assert found.basis == (
        "noun 'bolt', M6x20; solid: socket (the name says hex), 5 across flats, M6 measured"
    )
    assert found.confidence == "medium"


def test_where_name_and_drive_agree_the_basis_says_so_once():
    found = detected("socket head screw M6x20", socket_screw("M6"))
    assert found.basis == "noun 'screw', M6x20; solid: socket, 5 across flats, M6 measured"
    assert found.confidence == "high"


def torx_screw():
    """An M6 Torx socket head as code-CAD draws one: the recess a round pocket."""
    head = Pos(0, 0, 3) * Cylinder(5, 6) - Pos(0, 0, 4.5) * Cylinder(2.8, 3.01)
    return head + Pos(0, 0, -5) * Cylinder(3, 10)


@pytest.mark.parametrize("name", ["lid_torx_screw", "torx_lid_screw"])
def test_a_torx_screw_is_torx_by_its_name_wherever_the_word_sits(name):
    # Issue #19: torx_lid_screw was read as a socket head by its outline, and
    # turned with a 5 mm hex key that can't drive a Torx recess.
    found = detected(name, torx_screw())
    assert (found.head, found.size.designation) == (Head.TORX, "M6")
    assert "outline" not in found.basis


def test_a_torx_name_on_a_modelled_hex_socket_is_flagged():
    # The solid's hex pocket is a drive, and outranks the name: the bench's
    # torx_open cell. The comment detect writes says the two disagree.
    found = detected("torx_lid_screw", socket_screw("M6"))
    assert found.head is Head.SOCKET
    assert found.basis == (
        "noun 'screw', drive 'torx'; solid: socket (the name says torx), 5 across flats, "
        "M6 measured"
    )
    assert found.confidence == "medium"


def test_the_name_outranks_a_guess_from_the_outline():
    found = detected("button head screw M6", socket_screw("M6", pocket=False))
    assert found.head is Head.BUTTON


def test_the_outline_is_used_when_the_name_says_nothing():
    found = detected("lift_bolt", socket_screw("M6", pocket=False))
    assert found.head is Head.SOCKET
    assert "by its outline" in found.basis


def test_a_printer_carriage_bolt_with_a_hex_head_is_a_hex_bolt():
    found = detected("x_carriage_bolt", hex_bolt("M8"))
    assert found.head is Head.HEX
    assert found.not_covered is None


def test_a_carriage_bolt_by_name_alone_is_not_trusted():
    found = detected("carriage bolt M8", Cylinder(4, 30) + Pos(0, 0, 16) * Cylinder(8, 4))
    assert found.head is None
    assert found.not_covered == NO_SQUARE_NECK


def test_a_carriage_bolt_with_its_square_neck_holds_itself():
    found = detected("carriage bolt M6", bench_parts.carriage_bolt())
    assert found.head is Head.CARRIAGE
    assert found.not_covered is None


def test_a_size_the_drive_settles_outranks_the_name():
    found = detected("socket screw M5x20", socket_screw("M6"))  # a stale name
    assert found.size.designation == "M6"
    assert "M6 measured" in found.basis


def test_the_name_size_outranks_a_measured_shank():
    # An M5 drawn at its minor diameter with no socket reads as #8 by itself.
    found = detected("screw M5x16", socket_screw("M5", pocket=False, shank=MINOR["M5"]))
    assert found.size.designation == "M5"


def test_a_measured_size_fills_in_when_the_name_has_none():
    found = detected("frame_bolt", hex_bolt("M10"))
    assert found.size.designation == "M10"
    assert found.drive_af == pytest.approx(16.0)


def test_a_gland_takes_its_hex_and_no_size():
    found = detected("cable_gland", bench_parts.gland())
    assert found.kind is Kind.NUT
    assert found.size is None
    assert found.drive_af == pytest.approx(24.0)
    assert not found.socket_allowed


def test_a_set_screw_named_takes_its_own_head_and_size():
    # Issue #96: ISO 4026's keys, not ISO 4762's; with no socket drawn, the name's.
    found = detected("set screw M6x10", Cylinder(3, 10))
    assert (found.head, found.size.designation, found.not_covered) == (Head.SET, "M6", None)


def test_a_name_with_nothing_measurable_is_source_name():
    found = detected("bolt M6x20", Box(5, 5, 5))
    assert found.source == "name"
    assert found.size.designation == "M6"
    assert found.basis == "noun 'bolt', M6x20"


def test_phillips_is_read_from_the_cross():
    found = detected("frame_screw", pan_phillips())
    assert (found.head, found.size.designation) == (Head.PHILLIPS, "M4")


def test_only_named_fasteners_are_found():
    parts = [
        Part("bolt", hex_bolt("M8")),
        Part("plate", Box(50, 50, 5)),
        Part("nut", hex_nut("M8")),
    ]
    assert sorted(f.name for f in find_fasteners(parts)) == ["bolt", "nut"]


# ---------------------------------------------------------------------------
# In the check.
# ---------------------------------------------------------------------------


def test_with_no_sidecar_a_torx_lid_screw_takes_the_torx_key():
    plate = Pos(0, 0, -5) * Box(100, 100, 10)
    assembly = Assembly([Part("torx_lid_screw", torx_screw()), Part("plate", plate)])
    (result,) = check(assembly, Config(), kit="full").results
    assert (result.verdict, result.tool) == (Verdict.TURNS, "torx-key-T30")


def run(assembly, config=None, **kwargs):
    return check(assembly, Config.from_dict(config or {}), engine="exact", **kwargs)


def test_with_no_sidecar_the_bolt_is_found_and_checked():
    report = run(screw_facing_wall(15.0))
    (result,) = report.results
    assert result.fastener.name == "bolt"
    assert result.verdict is Verdict.BLOCKED
    assert result.blockers == ("wall",)
    assert report.to_json_dict()["fasteners"][0]["source"] in {"name", "name+geometry"}


def test_a_rule_outranks_detection():
    rule = {"parts": "bolt", "kind": "screw", "head": "torx", "size": "M6"}
    (result,) = run(screw_facing_wall(50.0), {"fasteners": [rule]}, kit="full").results
    assert result.fastener.source == "sidecar"
    assert result.tool == "torx-key-T30"  # the rule's Torx head, not the solid's 5 mm hex


def test_detect_false_finds_nothing():
    report = run(screw_facing_wall(50.0), {"checks": {"detect": False}})
    assert report.results == ()


def test_an_ignored_part_is_never_detected():
    report = run(screw_facing_wall(50.0), {"ignore": ["bolt"]})
    assert report.results == ()


def test_a_gland_found_by_name_gets_the_spanner_its_hex_takes():
    found = run(gland_on_wall(), kit="full")  # a 24 mm hex: metric-home stops at 19
    described = run(
        gland_on_wall(),
        {"fasteners": [{"parts": "gland", "kind": "nut", "size": "M16", "socket": False}]},
        kit="full",
    )
    (alone,) = found.results
    (ruled,) = described.results
    assert (
        (alone.verdict, alone.tool) == (ruled.verdict, ruled.tool) == (Verdict.TURNS, "spanner-24")
    )


def test_across_flats_in_the_sidecar_picks_the_spanner():
    rule = {"parts": "nut", "kind": "nut", "size": "M8", "across_flats": 13}
    nut = Assembly([Part("nut", hex_nut("M8")), Part("plate", Pos(0, 0, -5) * Box(200, 200, 10))])
    (result,) = run(nut, {"fasteners": [rule]}).results
    assert result.tool == "spanner-13"


def test_an_inch_hex_takes_an_inch_spanner_not_a_metric_guess():
    inch_nut = hex_prism(11.1125, 6) - Cylinder(3.175, 30)  # 7/16" hex
    nut = Assembly([Part("nut", inch_nut), Part("plate", Pos(0, 0, -5) * Box(200, 200, 10))])
    (home,) = run(nut).results
    assert home.verdict is Verdict.NOT_COVERED
    assert home.reason == (
        "needs spanner-7/16in or socket-7/16in, which kit metric-home does not hold "
        "(imperial-home and full have it)"
    )
    (inch,) = run(nut, kit="imperial-home").results
    assert inch.verdict is Verdict.TURNS
    assert inch.tool == "spanner-7/16in"


def _socket_head(af):
    return Pos(0, 0, -10) * Cylinder(3, 20) + Pos(0, 0, 3) * Cylinder(5, 6) - hex_prism(af, 3.01, 3)


def test_a_socket_no_key_fits_is_not_covered():
    report = run(Assembly([Part("screw", _socket_head(4.4))]), kit="full")
    (result,) = report.results
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == (
        "4.40 mm across flats is no tool's size: the largest that fits, hex-key-4, is 0.40 "
        "smaller; set across_flats: or tool: in the sidecar"
    )


def test_an_inch_socket_takes_its_inch_key():
    (result,) = run(Assembly([Part("screw", _socket_head(4.7625))]), kit="full").results
    assert result.tool == "hex-key-3/16in"
    assert result.verdict is Verdict.TURNS


# ---------------------------------------------------------------------------
# The sidecar keys.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [24, 24.0, 5.5])
def test_across_flats_takes_a_positive_number(value):
    config = Config.from_dict({"fasteners": [{"parts": "g", "kind": "nut", "across_flats": value}]})
    assert config.rules[0].drive_af == float(value)


@pytest.mark.parametrize("value", [0, -3, "24", True])
def test_across_flats_refuses_anything_else(value):
    with pytest.raises(ConfigError, match="across_flats"):
        Config.from_dict({"fasteners": [{"parts": "g", "kind": "nut", "across_flats": value}]})


def test_detect_is_on_unless_said_otherwise():
    assert Config.from_dict({}).detect
    assert not Config.from_dict({"checks": {"detect": False}}).detect
    with pytest.raises(ConfigError, match="detect"):
        Config.from_dict({"checks": {"detect": "no"}})


def test_a_nut_whose_size_has_no_spanner_is_not_covered_not_a_crash():
    # Found by this file: the hex-flats attempts are a generator, and a reason
    # raised inside one surfaced only while the attempts ran, outside the code
    # that turns it into a verdict, so the whole check crashed. ISO 4032 has no
    # M3.5 row; that has always been reachable from a sidecar.
    rule = {"parts": "nut", "kind": "nut", "size": "M3.5", "axis": "+z"}
    nut = Assembly([Part("nut", hex_prism(6.0, 2.8) - Cylinder(1.75, 10))])
    (result,) = run(nut, {"fasteners": [rule], "checks": {"detect": False}}).results
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == "no across-flats for M3.5"


# ---------------------------------------------------------------------------
# Confidence: what the evidence supports, for the sidecar detect writes.
# ---------------------------------------------------------------------------


def _plain_head(dk, k):
    """An M6 with a plain head of no standard's outline: proportions alone call it."""
    return Pos(0, 0, -10) * Cylinder(3, 20) + Pos(0, 0, k / 2) * Cylinder(dk / 2, k)


@pytest.mark.parametrize(
    ("name", "shape", "level"),
    [
        ("ISO 4762 M6x20", lambda: socket_screw("M6"), "high"),  # standard, socket shown
        ("frame_bolt", lambda: hex_bolt("M8"), "high"),  # hex shown, size settled by it
        ("frame_nut", lambda: hex_nut("M10"), "high"),
        ("socket head screw M6", lambda: socket_screw("M6", pocket=False), "high"),  # name says all
        # The name says all, and the outline, ISO 4762's exactly, says another (issue #81).
        ("button head screw M6", lambda: socket_screw("M6", pocket=False), "low"),
        # Nothing but proportions says otherwise: the name stands, sure.
        ("button head screw M6", lambda: _plain_head(13.0, 6.0), "high"),
        ("hex bolt M6x20", lambda: socket_screw("M6"), "medium"),  # name and drive disagree
        ("torx_lid_screw M6", torx_screw, "high"),  # a drive word away from the noun
        ("lift_bolt", lambda: socket_screw("M6", pocket=False), "medium"),  # head by outline
        ("frame_screw", pan_phillips, "medium"),  # size from the shank alone
        ("set screw M6x10", lambda: Cylinder(3, 10), "high"),  # the name says all (#96)
        ("DIN 7984 M6x10", lambda: socket_screw("M6"), "low"),  # not covered
        ("bolt", lambda: Box(5, 5, 5), "low"),  # nothing measurable, no size
    ],
)
def test_confidence_follows_the_evidence(name, shape, level):
    assert detected(name, shape()).confidence == level


def test_a_sidecar_fastener_has_no_confidence():
    config = Config.from_dict({"fasteners": [{"parts": "bolt", "size": "M6", "head": "socket"}]})
    (fastener,) = config.apply(screw_facing_wall(50.0)).fasteners
    assert fastener.confidence == ""
