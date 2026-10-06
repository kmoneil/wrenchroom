"""Kits: a check tries only the kit's tools, and says which kit has what it lacks.

The spec's kits (5.3), held to the letter: metric-home's hex keys stop at 10 mm and
its spanners and sockets at 19 mm, and `full` holds everything metric-home does and
more. A fastener needing a tool outside the kit is not covered, naming the tool and
the kit that has it; the sidecar's `tool:` can pick a tool but not add one.
"""

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
from wrenchroom.check import check
from wrenchroom.cli import EXIT_NOT_COVERED, main
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.tools import kits
from wrenchroom.tools.hex_keys import ISO_2936
from wrenchroom.tools.kits import FULL, KITS, METRIC_HOME, Kit, kit_named, missing

M6_SOCKET = {"kind": "screw", "head": "socket", "size": "M6"}


def run(assembly, *rules, kit="metric-home"):
    return check(assembly, Config.from_dict({"fasteners": list(rules)}), kit=kit, engine="exact")


# ---------------------------------------------------------------------------
# The kits as data.
# ---------------------------------------------------------------------------


def test_metric_home_is_the_spec_s_kit():
    assert METRIC_HOME.hex_keys == (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)
    flats = (5.5, *(float(af) for af in range(6, 20)))
    assert METRIC_HOME.spanners == flats
    assert METRIC_HOME.sockets == flats
    assert METRIC_HOME.drivers == ("ph1", "ph2", "ph3", "slotted")


def test_full_holds_everything_metric_home_does_and_more():
    for family in ("hex_keys", "spanners", "sockets", "drivers"):
        home, full = set(getattr(METRIC_HOME, family)), set(getattr(FULL, family))
        assert home <= full, family
    assert set(FULL.hex_keys) == set(ISO_2936)
    assert max(FULL.spanners) == max(FULL.sockets) == 36


def test_every_kit_key_is_a_standard_row():
    for kit in KITS.values():
        assert set(kit.hex_keys) <= set(ISO_2936), kit.name


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
    with pytest.raises(ValueError, match="unknown kit 'mars'; available: metric-home, full"):
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
    rule = {"parts": "bolt", **M6_SOCKET, "tool": "hex-key-12"}
    (result,) = run(screw_facing_wall(40.0), rule).results
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
    rule = {"parts": "nut", "kind": "nut", "size": "M6", "tool": tool}
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
    kit = Kit("sockets-only", "16 mm socket", (), (), (16.0,), ())
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
        "needs driver-ph2, which kit sockets-only does not hold (metric-home and full have it)"
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
