"""Kits: a check tries only the kit's tools, and says which kit has what it lacks.

The spec's kits (5.3), held to the letter: metric-home's hex keys stop at 10 mm and
its spanners and sockets at 19 mm, and `full` holds everything metric-home does and
more. A fastener needing a tool outside the kit is not covered, naming the tool and
the kit that has it; the sidecar's `tool:` can pick a tool but not add one.
"""

import re

import pytest
from build123d import Compound, export_step
from click.testing import CliRunner

from fixture_models import (
    gland_on_wall,
    nut_on_plate,
    nut_with_bolt_through,
    screw_facing_wall,
    socket_screw,
)
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import EXIT_NOT_COVERED, main
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.tools import kits
from wrenchroom.tools.hex_keys import HEX_KEYS
from wrenchroom.tools.kits import (
    FULL,
    IMPERIAL_HOME,
    KITS,
    METRIC_HOME,
    Kit,
    kit_named,
    missing,
)
from wrenchroom.tools.sizes import METRIC_FLATS, size_mm, size_name

M6_SOCKET = {"kind": "screw", "head": "socket", "size": "M6"}


def run(assembly, *rules, kit="metric-home"):
    return check(assembly, Config.from_dict({"fasteners": list(rules)}), kit=kit, engine="exact")


# ---------------------------------------------------------------------------
# The kits as data.
# ---------------------------------------------------------------------------


def test_metric_home_is_the_spec_s_kit():
    assert METRIC_HOME.hex_keys == ("1.5", "2", "2.5", "3", "4", "5", "6", "8", "10")
    flats = ("5.5", *(str(af) for af in range(6, 20)))
    assert METRIC_HOME.spanners == flats
    assert METRIC_HOME.sockets == flats
    assert METRIC_HOME.drivers == ("ph1", "ph2", "ph3", "slotted")


def test_imperial_home_is_what_us_home_sets_agree_on():
    keys = [
        "0.050",
        "1/16",
        "5/64",
        "3/32",
        "7/64",
        "1/8",
        "9/64",
        "5/32",
        "3/16",
        "7/32",
        "1/4",
        "5/16",
        "3/8",
    ]
    assert IMPERIAL_HOME.hex_keys == tuple(f"{k}in" for k in keys)  # the 13-piece set
    spanners = ["1/4", "5/16", "3/8", "7/16", "1/2", "9/16", "5/8", "11/16", "3/4"]
    assert IMPERIAL_HOME.spanners == tuple(f"{s}in" for s in spanners)
    quarter = ["3/16", "7/32", "1/4", "9/32", "5/16", "11/32", "3/8", "7/16", "1/2", "9/16"]
    three_eighths = ["5/8", "11/16", "3/4"]  # 5/16 to 9/16 the 1/4 drive set has already
    assert IMPERIAL_HOME.sockets == tuple(f"{s}in" for s in quarter + three_eighths)
    assert IMPERIAL_HOME.drivers == METRIC_HOME.drivers


def test_full_holds_everything_each_home_kit_does_and_more():
    for home in (METRIC_HOME, IMPERIAL_HOME):
        for family in ("hex_keys", "spanners", "sockets", "drivers"):
            assert set(getattr(home, family)) <= set(getattr(FULL, family)), (home.name, family)
    assert len(FULL.hex_keys) == len(HEX_KEYS)
    assert {"36", "1-1/2in"} <= set(FULL.spanners) & set(FULL.sockets)


def test_every_kit_size_is_a_real_tool():
    for kit in KITS.values():
        assert {size_mm(size) for size in kit.hex_keys} <= set(HEX_KEYS), kit.name
        for size in kit.spanners + kit.sockets:
            assert size_name(size_mm(size)) == size, (kit.name, size)  # names round-trip


@pytest.mark.parametrize(
    ("tool", "home", "full"),
    [
        ("hex-key-5", True, True),
        ("hex-key-10", True, True),
        ("hex-key-12", False, True),
        ("spanner-19", True, True),
        ("spanner-24", False, True),
        ("spanner-5.5", True, True),
        ("socket-19", True, True),
        ("socket-36", False, True),
        ("socket-37", False, False),
        ("spanner-22.5", False, False),  # no tool is made in that size
        ("driver-ph2", True, True),
        ("driver-slotted", True, True),
        ("driver-ph4", False, False),
        ("spanner-ten", False, False),
        ("wrench-10", False, False),
        ("hex-key-7", False, False),  # no ISO 2936 row
        ("", False, False),
    ],
)
def test_holds_reads_tool_names_as_the_report_writes_them(tool, home, full):
    assert METRIC_HOME.holds(tool) is home
    assert FULL.holds(tool) is full


def test_the_reason_names_the_tool_and_the_kit_that_has_it():
    assert missing(("spanner-24", "socket-24"), METRIC_HOME) == (
        "needs spanner-24 or socket-24, which kit metric-home does not hold (full has it)"
    )
    assert missing(("socket-40",), FULL) == (
        "needs socket-40, which kit full does not hold; no kit has it"
    )


def test_an_unknown_kit_is_a_typo():
    match = "unknown kit 'mars'; available: metric-home, imperial-home, full"
    with pytest.raises(ValueError, match=match):
        kit_named("mars")
    with pytest.raises(ValueError, match="unknown kit"):
        run(screw_facing_wall(40.0), {"parts": "bolt", **M6_SOCKET}, kit="mars")


# ---------------------------------------------------------------------------
# A check uses the kit's tools only.
# ---------------------------------------------------------------------------


def test_a_24_mm_hex_is_not_covered_by_the_home_kit_and_turns_with_full():
    rule = {"parts": "gland", "kind": "nut", "size": "M16", "socket": False}
    (home,) = run(gland_on_wall(), rule).results
    assert home.verdict is Verdict.NOT_COVERED
    assert home.reason == "needs spanner-24, which kit metric-home does not hold (full has it)"
    assert home.attempts == ()
    (full,) = run(gland_on_wall(), rule, kit="full").results
    assert full.verdict is Verdict.TURNS
    assert full.tool == "spanner-24"


def _m14_socket_screw():
    """An M14-ish socket head: its 12 mm key is past metric-home's 10."""
    return Assembly([Part("bolt", socket_screw())])


def test_a_key_past_the_home_kit_is_not_covered():
    rule = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M14"}
    (result,) = run(_m14_socket_screw(), rule).results
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == "needs hex-key-12, which kit metric-home does not hold (full has it)"


def test_a_forced_tool_must_be_in_the_kit():
    # The M14's own key, past metric-home's 10 (a key that doesn't fit is #72's).
    rule = {"parts": "bolt", "kind": "screw", "head": "socket", "size": "M14"}
    (result,) = run(_m14_socket_screw(), {**rule, "tool": "hex-key-12"}).results
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == "needs hex-key-12, which kit metric-home does not hold (full has it)"
    forced_in_kit = {"parts": "bolt", **M6_SOCKET, "tool": "hex-key-5"}
    (result,) = run(screw_facing_wall(40.0), forced_in_kit).results
    assert result.verdict is Verdict.TURNS


@pytest.mark.parametrize(
    ("tool", "allowed"),
    [("spanner-10", True), ("socket-10", True), ("spanner-24", False), ("socket-24", False)],
)
def test_every_forced_family_asks_the_kit(tool, allowed):
    # across_flats: says the hex is the tool's size, so the tool fits (issue #72)
    # and only the kit is in question.
    af = float(tool.rpartition("-")[2])
    rule = {"parts": "nut", "kind": "nut", "size": "M6", "across_flats": af, "tool": tool}
    (result,) = run(nut_on_plate(), rule).results
    if allowed:
        assert result.verdict is Verdict.TURNS
        assert result.tool == tool
    else:
        assert result.verdict is Verdict.NOT_COVERED
        assert result.reason == f"needs {tool}, which kit metric-home does not hold (full has it)"


@pytest.fixture
def sockets_only(monkeypatch):
    """A kit with M10's socket but no spanners at all."""
    kit = Kit("sockets-only", "16 mm socket", (), (), ("16",), ())
    monkeypatch.setitem(kits.KITS, kit.name, kit)
    return kit.name


def test_a_kit_with_only_the_socket_tries_only_the_socket(sockets_only):
    rule = {"parts": "nut", "kind": "nut", "size": "M10"}
    assembly = nut_with_bolt_through(af=16.0, nut_h=8.4, bolt_d=10.0)
    (result,) = [
        r for r in run(assembly, rule, kit=sockets_only).results if r.fastener.name == "nut"
    ]
    assert result.attempts
    assert {attempt.tool for attempt in result.attempts} == {"socket-16"}


def test_a_kit_with_no_drivers_does_not_cover_a_phillips_screw(sockets_only):
    rule = {"parts": "bolt", "kind": "screw", "head": "phillips", "size": "M4"}
    (result,) = run(screw_facing_wall(40.0), rule, kit=sockets_only).results
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == (
        "needs driver-ph2, which kit sockets-only does not hold "
        "(metric-home, imperial-home and full have it)"
    )


# ---------------------------------------------------------------------------
# The CLI lists exactly a kit's tools.
# ---------------------------------------------------------------------------


def _tools(*args):
    return CliRunner().invoke(main, ["tools", *args])


def test_tools_lists_the_home_kit_and_nothing_more():
    result = _tools()
    assert result.exit_code == 0
    assert result.output.startswith("kit metric-home: ")
    listed = {word for line in result.output.splitlines() for word in line.split()[:1]}
    assert {"hex-key-10", "spanner-19", "socket-19", "driver-ph3"} <= listed
    assert not {"hex-key-12", "spanner-24", "socket-24"} & listed
    assert sum(name.startswith("hex-key-") for name in listed) == len(METRIC_HOME.hex_keys)
    assert sum(name.startswith("spanner-") for name in listed) == len(METRIC_HOME.spanners)
    assert sum(name.startswith("socket-") for name in listed) == len(METRIC_HOME.sockets)


def test_tools_lists_the_full_kit():
    result = _tools("--kit", "full")
    assert result.exit_code == 0
    listed = {line.split()[0] for line in result.output.splitlines() if line.startswith("  ")}
    assert {"hex-key-19", "spanner-36", "socket-24"} <= listed


def test_tools_and_detect_refuse_an_unknown_kit(tmp_path):
    assert _tools("--kit", "mars").exit_code == EXIT_NOT_COVERED
    shapes = []
    for part in screw_facing_wall(40.0):
        part.shape.label = part.name
        shapes.append(part.shape)
    export_step(Compound(children=shapes), str(tmp_path / "m.step"))
    result = CliRunner().invoke(main, ["detect", str(tmp_path / "m.step"), "--kit", "mars"])
    assert result.exit_code == EXIT_NOT_COVERED
    assert "unknown kit 'mars'" in result.output
    ok = CliRunner().invoke(main, ["detect", str(tmp_path / "m.step"), "--kit", "full"])
    assert ok.exit_code == 0
    assert "parts: bolt" in ok.output


def test_the_full_kit_s_summary_reaches_its_largest_tools():
    # The summary once stopped at 36 mm while the kit held 41, 46 and 50: what
    # `tools` and the README say of a kit must be what it holds.
    for af in (36.0, *METRIC_FLATS[METRIC_FLATS.index(36.0) + 1 :]):
        assert re.search(rf"\b{af:g}\b", kits.FULL.summary), af
    assert max(METRIC_FLATS) == 50.0
