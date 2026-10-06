"""Inch sizes: named with their unit, told from metric neighbours, checked with inch tools.

A tool's name carries "in" for an inch size (spanner-7/16in), because some inch sizes
sit within hundredths of a millimetre of metric ones: 3/4 in is 19.05 mm, 3/8 in
9.525. A measured hex is the nearest real tool size, so an exact model is never read
as its neighbour from the other system.
"""

import pytest
from build123d import Box, Cylinder, Pos, Rot
from click.testing import CliRunner

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.tools.hex_keys import HEX_KEYS
from wrenchroom.tools.sizes import (
    INCH_FLATS,
    INCH_KEYS,
    METRIC_FLATS,
    inch_mm,
    inches,
    size_mm,
    size_name,
    snap,
)

IN = 25.4

# ---------------------------------------------------------------------------
# Sizes and their names.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [("7/16", 0.4375), ("1-1/8", 1.125), ("0.050", 0.05), ("1", 1.0), ("1-1/2", 1.5)],
)
def test_inch_sizes_read_as_the_trade_writes_them(text, value):
    assert inches(text) == pytest.approx(value)
    assert inch_mm(text) == pytest.approx(value * IN)


@pytest.mark.parametrize("bad", ["", "seven", "1/0", "1-", "-1/2x"])
def test_a_non_size_is_refused(bad):
    with pytest.raises(ValueError, match="not an inch size"):
        inches(bad)


def test_every_tool_size_names_itself_and_back():
    for text in INCH_KEYS + INCH_FLATS:
        name = size_name(inch_mm(text))
        assert name == f"{text}in"
        assert size_mm(name) == pytest.approx(inch_mm(text))
    for af in METRIC_FLATS:
        assert size_name(af) == f"{af:g}"
        assert size_mm(size_name(af)) == af


@pytest.mark.parametrize(
    ("measured", "named"),
    [
        (19.0, "19"),
        (19.05, "3/4in"),  # 0.05 from 19 mm, exactly 3/4 in
        (9.525, "3/8in"),  # nearest is 3/8 in, not a metric size
        (4.0, "4"),
        (3.96875, "5/32in"),  # 0.03 from 4 mm, exactly 5/32 in
        (11.11, "7/16in"),
        (13.02, "13"),
    ],
)
def test_a_measurement_is_the_nearest_real_size(measured, named):
    sizes = tuple(HEX_KEYS) + METRIC_FLATS + tuple(inch_mm(s) for s in INCH_FLATS)
    snapped = snap(measured, sizes)
    assert snapped is not None
    assert size_name(snapped) == named


def test_a_measurement_far_from_every_size_is_none():
    assert snap(22.5, METRIC_FLATS) is None
    assert snap(4.4, tuple(HEX_KEYS)) is None
    assert snap(13.0, ()) is None


def test_inch_and_metric_tool_sizes_never_coincide():
    inch = {round(inch_mm(s), 6) for s in INCH_KEYS + INCH_FLATS}
    metric = {round(af, 6) for af in METRIC_FLATS} | {
        round(af, 6) for af in HEX_KEYS if not size_name(af).endswith("in")
    }
    assert not inch & metric


# ---------------------------------------------------------------------------
# Inch fasteners checked with inch tools.
# ---------------------------------------------------------------------------


def run(assembly, *rules, kit="imperial-home"):
    return check(assembly, Config.from_dict({"fasteners": list(rules)}), kit=kit, engine="exact")


def _inch_bolt(head_af):
    """A 7/16 hex head bolt standing head-up on a plate (head 0.3 in tall)."""
    head = hex_prism(head_af * IN, 0.3 * IN)
    shank = Pos(0, 0, -0.75 * IN) * Cylinder(7 / 32 * IN, 1.5 * IN)
    return Assembly([Part("bolt", head + shank), Part("plate", Pos(0, 0, -5) * Box(200, 200, 10))])


def test_a_7_16_head_takes_a_5_8_spanner_and_its_nut_11_16():
    bolt = {"parts": "bolt", "kind": "screw", "head": "hex", "size": "7/16"}
    (result,) = run(_inch_bolt(5 / 8), bolt).results
    assert result.verdict is Verdict.TURNS
    assert result.tool == "spanner-5/8in"
    nut = Assembly(
        [
            Part("nut", hex_prism(11 / 16 * IN, 3 / 8 * IN) - Cylinder(7 / 32 * IN, 2 * IN)),
            Part("plate", Pos(0, 0, -5) * Box(200, 200, 10)),
        ]
    )
    (result,) = run(nut, {"parts": "nut", "kind": "nut", "size": "7/16"}).results
    assert result.verdict is Verdict.TURNS
    assert result.tool == "spanner-11/16in"


def test_an_inch_socket_head_takes_its_asme_key():
    head = Pos(0, 0, 0.125 * IN) * Cylinder(0.1875 * IN, 0.25 * IN) - hex_prism(
        3 / 16 * IN, 0.13 * IN, 0.12 * IN
    )
    screw = head + Pos(0, 0, -0.5 * IN) * Cylinder(0.125 * IN, IN)
    rule = {"parts": "screw", "kind": "screw", "head": "socket", "size": "1/4"}
    (result,) = run(Assembly([Part("screw", screw)]), rule).results
    assert result.verdict is Verdict.TURNS
    assert (result.tool, result.how) == ("hex-key-3/16in", "driver straight in")
    (home,) = run(Assembly([Part("screw", screw)]), rule, kit="metric-home").results
    assert home.verdict is Verdict.NOT_COVERED
    assert home.reason == (
        "needs hex-key-3/16in, which kit metric-home does not hold (imperial-home and full have it)"
    )


@pytest.mark.parametrize(
    ("tool", "verdict"),
    [
        ("spanner-5/8in", Verdict.TURNS),
        ("socket-5/8in", Verdict.TURNS),
        ("spanner-5/8", Verdict.NOT_COVERED),  # no unit: a metric name, and no such size
        ("spanner-16", Verdict.NOT_COVERED),  # metric: not in imperial-home
    ],
)
def test_a_forced_tool_is_named_with_its_unit(tool, verdict):
    rule = {"parts": "bolt", "kind": "screw", "head": "hex", "size": "7/16", "tool": tool}
    (result,) = run(_inch_bolt(5 / 8), rule).results
    assert result.verdict is verdict, result.reason


def test_an_inch_size_without_its_unit_is_an_unknown_tool():
    # Said plainly, so the typo is found: not "no kit has it".
    rule = {"parts": "bolt", "kind": "screw", "head": "hex", "size": "7/16", "tool": "spanner-5/8"}
    (result,) = run(_inch_bolt(5 / 8), rule, kit="full").results
    assert result.reason == "unknown tool 'spanner-5/8'"


def test_an_inch_phillips_screw_takes_its_driver():
    pan = Pos(0, 0, 1) * Cylinder(4, 2) + Pos(0, 0, -6) * Cylinder(2.4, 12)
    pan = pan - Pos(0, 0, 1.5) * Box(4, 0.8, 2) - Pos(0, 0, 1.5) * Rot(0, 0, 90) * Box(4, 0.8, 2)
    rule = {"parts": "screw", "kind": "screw", "head": "phillips", "size": "#10"}
    (result,) = run(Assembly([Part("screw", pan)]), rule).results
    assert result.tool == "driver-ph2"
    assert result.verdict is Verdict.TURNS


def test_tools_lists_the_inch_kit():
    result = CliRunner().invoke(main, ["tools", "--kit", "imperial-home"])
    assert result.exit_code == 0
    assert "hex-key-0.050in" in result.output
    assert "spanner-3/4in" in result.output
    assert "socket-3/16in" in result.output
    assert "spanner-7/8in" not in result.output  # past the home sets
    assert "hex-key-5 " not in result.output  # metric keys are metric-home's
