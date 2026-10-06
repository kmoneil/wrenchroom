"""Fixed threads (issue #29): well nuts, inserts, cage and T-nuts hold themselves.

A rubber well nut, a rivnut, a threaded insert, a cage, T-, press or weld nut is
set in its panel and never turned: no spanner grips it, and the screw into it is
the one that must turn. Such a part is an insert: like a carriage bolt it holds
itself, is never given a tool, and is reported as held; the screw pairs with it
and is checked as a screw into a tapped hole. And a nut whose solid shows no hex
is no longer given its thread's spanner, which could not grip it.
"""

import json

import pytest
import yaml
from build123d import Box, Compound, Cylinder, Pos, export_step
from click.testing import CliRunner

from fastener_models import hex_nut
from fixture_models import bolt_with_slotted_nut
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.detect import NO_HEX, describe, read_name
from wrenchroom.fasteners import Fastener, Kind
from wrenchroom.report import Verdict

# ---------------------------------------------------------------------------
# Names.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "base_well_nut",
        "panel_insert_nut",
        "rack_cage_nut",
        "panel_rivnut",
        "rail_tnut",
        "t_nut",
        "T-Nut M6",
        "tee_nut",
        "rivet_nut",
        "press_nut",
        "self_clinching_nut",
        "pem_nut",
        "weld_nut",
        "captive_nut",
        "wellnut",
        "nutsert",
        "plusnut",
        "threaded_insert",
        "heat_set_insert M4",
        "M6 insert",
    ],
)
def test_a_fixed_thread_reads_as_an_insert(name):
    found = read_name(name)
    assert found is not None
    assert (found.kind, found.head, found.not_covered) == (Kind.INSERT, None, None)


@pytest.mark.parametrize(
    ("name", "basis"),
    [
        ("base_well_nut", "noun 'well nut'"),
        ("T-Nut M6", "noun 't nut', M6"),
        ("panel_rivnut", "noun 'rivnut'"),
    ],
)
def test_the_basis_says_what_made_it_an_insert(name, basis):
    assert read_name(name).basis == basis


@pytest.mark.parametrize(
    "name",
    [
        "nylon_insert_lock_nut",  # McMaster's own words for a nyloc
        "Nylon-Insert Locknut M6",
        "nylon_insert_nut",
        "insert_lock_nut",
        "lock_nut",
        "well_cover_nut",  # "well" isn't the word before "nut"
        "hex_nut",
    ],
)
def test_a_nut_with_an_insert_word_elsewhere_is_still_a_nut(name):
    assert read_name(name).kind is Kind.NUT


def test_an_insert_word_never_makes_a_screw_an_insert():
    assert read_name("weld_screw").kind is Kind.SCREW
    assert read_name("cage_bolt").kind is Kind.SCREW


def test_an_insert_reads_its_size():
    assert read_name("heat_set_insert M4").size.designation == "M4"
    assert read_name("base_well_nut_M4").size.designation == "M4"


def test_an_insert_holds_itself():
    insert = Fastener(name="x", kind=Kind.INSERT)
    assert insert.self_holding
    assert not Fastener(name="x", kind=Kind.NUT).self_holding


# ---------------------------------------------------------------------------
# The issue's model: an M4 screw through a panel into a well nut in a wall.
# ---------------------------------------------------------------------------


def well_nut_model(nut_name="cell_well_nut"):
    wall = Pos(0, 0, -1) * (Box(80, 80, 2) - Cylinder(4.5, 2))
    flange = Pos(0, 0, 0.75) * (Cylinder(5.5, 1.5) - Cylinder(2, 1.5))
    body = Pos(0, 0, -5) * (Cylinder(4.4, 10) - Cylinder(2, 10))
    panel = Pos(0, 0, 3) * (Box(80, 80, 3) - Cylinder(2.2, 3))
    screw = Pos(0, 0, -1.5) * Cylinder(2, 12) + Pos(0, 0, 5.6) * Cylinder(3.8, 2.2)
    return Assembly(
        [
            Part("cell_wall", wall),
            Part(nut_name, (flange + body).solid()),
            Part("cell_panel", panel),
            Part("cell_screw", screw),
        ]
    )


@pytest.fixture(scope="module")
def report():
    return check(well_nut_model(), kit="full")


def test_the_well_nut_holds_itself_and_gets_no_tool(report):
    (nut,) = [r for r in report.results if r.fastener.name == "cell_well_nut"]
    assert (nut.fastener.kind, nut.verdict, nut.tool, nut.how) == (
        Kind.INSERT,
        Verdict.HELD,
        None,
        "holds itself",
    )
    assert nut.pair == "cell_screw"
    assert nut.seat is None  # no tool comes at it from either end
    assert abs(nut.axis[2]) == pytest.approx(1.0)


def test_the_screw_into_it_is_the_one_that_turns(report):
    (screw,) = [r for r in report.results if r.fastener.name == "cell_screw"]
    assert screw.verdict is Verdict.TURNS
    assert screw.pair == "cell_well_nut"
    assert screw.tool.startswith("hex-key-")
    assert report.summary["held"] == 1
    assert report.exit_code == 0


def test_every_format_names_it_an_insert(report):
    (entry,) = [
        e for e in json.loads(report.json_text())["fasteners"] if e["name"] == "cell_well_nut"
    ]
    assert (entry["kind"], entry["verdict"], entry["how"], entry["tool"]) == (
        "insert",
        "held",
        "holds itself",
        None,
    )
    assert any("insert" in line and "holds itself" in line for line in report.terminal_lines())


@pytest.mark.parametrize(
    ("boxed", "bolt_verdict"),
    [(False, Verdict.TURNS), (True, Verdict.BLOCKED)],
)
def test_a_screw_that_only_holds_cannot_lean_on_the_insert(engine, boxed, bolt_verdict):
    # The M2 bolt-and-nut fixture with its nut said to be an insert. With the head
    # boxed in, the bolt's spanner gets on but can't swing: a nut could turn
    # against it, an insert never does, so the bolt is blocked, as into a tapped
    # hole. Either way the insert holds itself.
    rules = [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"},
        {"parts": "nut", "kind": "insert", "size": "M8"},
    ]
    report = check(
        bolt_with_slotted_nut(head_boxed=boxed),
        Config.from_dict({"fasteners": rules}),
        engine=engine,
    )
    by_name = {r.fastener.name: r for r in report.results}
    assert by_name["bolt"].verdict is bolt_verdict
    assert (by_name["nut"].verdict, by_name["nut"].tool) == (Verdict.HELD, None)
    if boxed:
        assert by_name["bolt"].reason == "only holds, and its partner nut does not turn"


def test_named_only_as_a_nut_its_round_solid_gets_no_spanner():
    # The same part named "cell_nut": the name says nut, and the solid shows no
    # hex. It used to turn with spanner-7, a tool that can't grip it.
    report = check(well_nut_model("cell_nut"), kit="full")
    (nut,) = [r for r in report.results if r.fastener.name == "cell_nut"]
    assert (nut.verdict, nut.reason) == (Verdict.NOT_COVERED, NO_HEX)
    assert "kind: insert" in NO_HEX


def test_a_nut_with_its_hex_is_unchanged():
    model = Assembly(
        [Part("frame_nut", hex_nut("M8")), Part("plate", Pos(0, 0, -5) * Box(100, 100, 10))]
    )
    (nut,) = check(model, kit="full").results
    assert (nut.fastener.kind, nut.verdict, nut.tool) == (Kind.NUT, Verdict.TURNS, "spanner-13")


def test_a_sidecar_rule_says_insert_outright():
    rule = {"parts": "cell_nut", "kind": "insert", "size": "M4"}
    report = check(well_nut_model("cell_nut"), Config.from_dict({"fasteners": [rule]}), kit="full")
    (nut,) = [r for r in report.results if r.fastener.name == "cell_nut"]
    assert (nut.fastener.source, nut.verdict) == ("sidecar", Verdict.HELD)


def test_a_sidecar_nut_rule_is_believed_as_ever():
    # A rule describes its part outright: the round solid isn't second-guessed.
    rule = {"parts": "cell_nut", "kind": "nut", "size": "M4"}
    report = check(well_nut_model("cell_nut"), Config.from_dict({"fasteners": [rule]}), kit="full")
    (nut,) = [r for r in report.results if r.fastener.name == "cell_nut"]
    assert nut.reason != NO_HEX


def test_detect_writes_the_insert_and_its_sidecar_keeps_the_verdicts(tmp_path):
    shapes = []
    for part in well_nut_model():
        part.shape.label = part.name
        shapes.append(part.shape)
    model = tmp_path / "well.step"
    export_step(Compound(children=shapes), str(model))
    result = CliRunner().invoke(main, ["detect", str(model), "--kit", "full"])
    assert result.exit_code == 0, result.output
    rules = {rule["parts"]: rule for rule in yaml.safe_load(result.stdout)["fasteners"]}
    assert rules["cell_well_nut"]["kind"] == "insert"
    assembly = Assembly.from_step(model)
    detected = check(assembly, kit="full")
    kept = check(assembly, Config.from_dict({"fasteners": list(rules.values())}), kit="full")
    verdicts = [(r.fastener.name, r.verdict, r.tool) for r in detected.results]
    assert [(r.fastener.name, r.verdict, r.tool) for r in kept.results] == verdicts


# ---------------------------------------------------------------------------
# By the word before "nut" alone, an insert is a nut if its solid has a hex.
# ---------------------------------------------------------------------------


def round_sleeve():
    return Cylinder(4.4, 10) - Cylinder(2, 12)


@pytest.mark.parametrize(
    ("name", "unless_hex"),
    [
        ("base_well_nut", True),  # by the word before "nut"
        ("rack_cage_nut", True),
        ("panel_rivnut", False),  # by its noun: nothing else it could be
        ("threaded_insert", False),
        ("hex_nut", False),
    ],
)
def test_only_an_insert_by_the_word_before_nut_waits_on_its_solid(name, unless_hex):
    assert read_name(name).unless_hex is unless_hex


def test_a_nut_deep_in_a_well_is_a_nut_by_its_hex():
    # The bench's nut_deep_well cell: an M6 hex nut at the foot of a deep well.
    found = describe(Part("nut_deep_well_nut", hex_nut("M6")), read_name("nut_deep_well_nut"))
    assert found.kind is Kind.NUT
    assert found.basis == "noun 'well nut'; solid: a hex, so a nut, 10 across flats, M6 measured"
    assert found.confidence == "medium"
    assert found.not_covered is None


def test_a_well_nut_with_no_hex_stays_an_insert():
    found = describe(Part("base_well_nut", round_sleeve()), read_name("base_well_nut"))
    assert (found.kind, found.not_covered) == (Kind.INSERT, None)
    assert "a hex, so a nut" not in found.basis


def test_an_insert_by_its_noun_is_not_second_guessed_by_a_hex():
    # A hex-bodied rivnut is still a rivnut: set in its panel, never turned.
    found = describe(Part("panel_rivnut", hex_nut("M6")), read_name("panel_rivnut"))
    assert found.kind is Kind.INSERT
