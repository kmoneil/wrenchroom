"""Clashes: parts drawn into each other, anywhere in the model (M8).

Every pair of parts whose boxes overlap is measured; a clash is an overlap past the
hit floor, 0.05 mm^3. A fastener is measured past its thread, as #63's "drawn into"
is, so a thread in its hole is none; nor is a fastener with its pair, its mates or
its own pieces, an ignored part, or two parts an ``allow:`` names. A state's own
model is looked in too. Each volume here is worked by hand.
"""

import json
import math
import re

import pytest
from build123d import Box, Compound, Cylinder, Pos, Rot, export_step
from click.testing import CliRunner

from fastener_models import MINOR, hex_prism, socket_screw
from test_nut_clash import BOLT, PLATE, cap, cap_nut
from test_nut_clash import RULES as CAP_RULES
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check, find_clashes
from wrenchroom.cli import main
from wrenchroom.config import Config, ConfigError
from wrenchroom.engine.exact import exact_overlap
from wrenchroom.engine.mesh import MeshEngine

CORNER = 13 / math.sqrt(3)  # an M8 nut's corners, 7.505 out


def clashes(parts, rules=(), engine="mesh", **sidecar):
    """The clashes in parts given as (name, shape), the sidecar's fasteners ``rules``."""
    config = Config.from_dict({"fasteners": list(rules), "checks": {"detect": False}, **sidecar})
    assembly = Assembly([Part(name, shape) for name, shape in parts])
    return find_clashes(assembly, config, engine=engine)


def found(result):
    """Each clash as (first, second, volume to 0.1 mm^3, state, hint)."""
    return [(c.first, c.second, round(c.volume, 1), c.state, c.hint) for c in result.found]


def bracket():
    """A block 10 on a side round the origin."""
    return Box(10, 10, 10)


def frame(x):
    """A block 20 on a side, its middle ``x`` along: its near face at x - 10."""
    return Pos(x, 0, 0) * Box(20, 20, 20)


# ---------------------------------------------------------------------------
# Two parts, and the floor.
# ---------------------------------------------------------------------------


def test_two_parts_drawn_into_each_other_are_a_clash(engine):
    # The frame's face 1 into the bracket's: 1 by 10 by 10, 100 mm^3, the bracket
    # (1000 mm^3) into the frame (8000 mm^3), the smaller first.
    result = clashes([("frame", frame(14)), ("bracket", bracket())], engine=engine)
    assert found(result) == [("bracket", "frame", 100.0, None, None)]
    (clash,) = result.found
    assert clash.point == pytest.approx((4.5, 0, 0), abs=1e-3)  # the overlap's middle
    assert result.exit_code == 1


@pytest.mark.parametrize(("x", "clash"), [(15.0, False), (14.9996, False), (14.9994, True)])
def test_a_touch_or_an_overlap_under_the_floor_is_none(engine, x, clash):
    # A touch is no overlap; 0.0004 deep over 10 by 10 is 0.04 mm^3, under the
    # floor; 0.0006 deep, 0.06 mm^3, over it.
    result = clashes([("frame", frame(x)), ("bracket", bracket())], engine=engine)
    assert bool(result.found) is clash
    assert result.exit_code == int(clash)


def shafts():
    """Two shafts 40 across and 40 long, 0.05 into each other along their length; the
    first turned 4 deg, so no vertex of its mesh lies where they meet."""
    return [
        ("shaft_a", Rot(0, 0, 4) * Cylinder(20, 40)),
        ("shaft_b", Pos(39.95, 0, 0) * Cylinder(20, 40)),
    ]


def test_curved_parts_whose_meshes_miss_their_overlap_are_measured(engine):
    # A lens 4/3 sqrt(20 0.05) 0.05 = 0.0667 mm^2 across, 40 long: 2.67 mm^3, and as
    # thin as a press fit. On the mesh engine, how far each mesh could stray, not
    # their overlap, which is none, says to measure it.
    ((first, second, volume, state, hint),) = found(clashes(shafts(), engine=engine))
    assert (first, second, volume, state) == ("shaft_a", "shaft_b", 2.7, None)
    assert hint.startswith("a press fit, 0.03 deep?")


def test_those_shafts_meshes_miss_their_overlap():
    # The guard: their meshes, inside their true surfaces, don't overlap at all.
    engine = MeshEngine()
    a, b = (Part(name, shape) for name, shape in shafts())
    assert (engine.part_mesh(a) ^ engine.part_mesh(b)).volume() == 0
    assert exact_overlap(a.shape, b.shape) == pytest.approx(2.666, abs=0.01)


def test_parts_whose_boxes_meet_but_whose_solids_don_t_are_none(engine):
    # An L of two bars round the bracket's corner: its box holds the corner, its
    # solid stops 1 short of it all round.
    ell = Pos(7, 0, 0) * Box(2, 30, 30) + Pos(0, 7, 0) * Box(30, 2, 30)
    result = clashes([("ell", Pos(0.5, 0.5, 0) * ell), ("bracket", bracket())], engine=engine)
    assert found(result) == []


# ---------------------------------------------------------------------------
# Fasteners, measured past their threads.
# ---------------------------------------------------------------------------

SCREW = {"parts": "screw", "kind": "screw", "head": "socket", "size": "M6"}
NUT = {"parts": "nut", "kind": "nut", "size": "M8"}


def tapped(radius, lid=None):
    """A block under z = 0, tapped down its axis at ``radius``; a lid ``lid`` into the head."""
    parts = [("block", Pos(0, 0, -10) * Box(30, 30, 20) - Pos(0, 0, -10) * Cylinder(radius, 21))]
    if lid is not None:
        parts.append(("lid", Pos(0, 0, 6 - lid + 5) * Box(30, 30, 10)))
    return [("screw", socket_screw("M6")), *parts]


@pytest.mark.parametrize("radius", [MINOR["M6"] / 2, 2.0, 2.5])
def test_a_screw_s_thread_in_its_hole_is_none(engine, radius):
    # Its shank, 6 across, drawn into a hole at M6's minor, inside it, or at a tap
    # drill: a thread, as a model draws one, measured past.
    assert found(clashes(tapped(radius), [SCREW], engine=engine)) == []


def test_a_screw_s_head_drawn_into_a_part_is_a_clash(engine):
    # A lid 0.5 down into its head (10 across, a 5 mm key's hex 3 deep): the head
    # less its hex, 0.5 deep, (78.54 - 21.65) * 0.5 = 28.4 mm^3, as #63 measured it.
    result = clashes(tapped(MINOR["M6"] / 2, lid=0.5), [SCREW], engine=engine)
    assert found(result) == [("screw", "lid", 28.4, None, None)]


def nut(bore=4.0):
    return hex_prism(13, 6.8) - Cylinder(bore, 30)


def test_a_nut_drawn_into_its_bracket_is_a_clash_the_fastener_first(engine):
    # A chip 1 past the nut's corner, 3 tall: the corner's tip, 1 deep and 2 tan 60
    # = 3.46 wide, 1.73 mm^2, 3 tall, 5.2 mm^3. The chip (900 mm^3) is smaller than
    # the nut, and the nut, a fastener, is the one drawn in, first.
    chip = Pos(CORNER - 1.0 + 5, 0, 3.4) * Box(10, 30, 3)
    result = clashes([("nut", nut()), ("chip", chip)], [NUT], engine=engine)
    assert found(result) == [("nut", "chip", 5.2, None, None)]


def test_a_bolt_drawn_into_its_own_nut_is_its_pair_and_none(engine):
    # The nut 0.5 up into its bolt's head: a pair, passed over as #63 passes it.
    bolt = hex_prism(13, 5.3) + Pos(0, 0, -12.5) * Cylinder(4, 25)
    into = Pos(0, 0, -6.3) * nut()  # z -6.3 to 0.5
    bolt_rule = {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"}
    assert found(clashes([("bolt", bolt), ("nut", into)], [NUT, bolt_rule], engine=engine)) == []
    # The guard: the same solid, no fastener and no pair, is drawn into the nut.
    rod = clashes([("rod", bolt), ("nut", into)], [NUT], engine=engine)
    assert [(a, b) for a, b, *_ in found(rod)] == [("nut", "rod")]


def test_a_cap_nut_s_dome_is_measured_from_its_bolt_s_side(engine):
    # #123's M8 cap nut on its bolt, its dome a sphere of 6 about z 9, topping out at
    # 15, and a cover 2 down into it: a cap 2 high, pi 2^2 (18 - 2) / 3 = 67.0 mm^3.
    # Its bolt says which end its dome is; from neither, its hex alone is measured.
    cover = Pos(0, 0, 13 + 5) * Box(60, 60, 10)
    parts = [("plate", PLATE), ("bolt", BOLT), ("nut", cap_nut()), ("cover", cover)]
    result = clashes(parts, CAP_RULES, engine=engine)
    assert found(result) == [("nut", "cover", 67.0, None, None)]
    assert f"{cap(2):.1f}" == "67.0"


def test_two_fasteners_drawn_into_each_other_are_told_by_the_larger_measure(engine):
    # An M8 nut beside an M6 screw, over its head and its shank. Measured on the
    # screw (its head alone) 63.5 mm^3 of the nut; on the nut (its body, its bore's
    # thread less), 87.2 of the screw: the larger is told, the nut first.
    nut_beside = Pos(8, 0, -3.4) * (hex_prism(13, 6.8) - Cylinder(4, 30))
    parts = [("screw", socket_screw("M6")), ("nut", nut_beside)]
    assert found(clashes(parts, [SCREW, NUT], engine=engine)) == [
        ("nut", "screw", 87.2, None, None)
    ]


def test_a_rod_in_a_nut_bored_at_its_minor_is_none(engine):
    # A stud 8 across, no fastener, in a nut bored at M8's minor, 6.65: its thread.
    stud = Pos(0, 0, 3) * Cylinder(4, 20)
    result = clashes([("nut", nut(MINOR["M8"] / 2)), ("stud", stud)], [NUT], engine=engine)
    assert found(result) == []


def test_a_bolt_and_its_nut_are_a_pair_and_none(engine):
    # The bolt 8 across in the nut bored at its minor: a pair, as check pairs them.
    bolt = Pos(0, 0, 8) * (hex_prism(13, 5.3) + Pos(0, 0, -12.5) * Cylinder(4, 25))
    bolt_rule = {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"}
    parts = [("nut", nut(MINOR["M8"] / 2)), ("bolt", bolt)]
    assert found(clashes(parts, [NUT, bolt_rule], engine=engine)) == []


def test_a_fastener_not_understood_is_said_and_not_measured():
    # Named a screw, a plain block: no axis, no thread to measure past. Measured
    # whole it would clash with its block; it is left out, and said.
    parts = [("screw", Pos(0, 0, 2) * Box(4, 4, 8)), ("block", bracket())]
    result = clashes(parts, [SCREW])
    assert (result.found, result.unmeasured) == ((), ("screw",))
    assert result.lines()[-1] == (
        "NOTE not measured for clashes, not understood as fasteners: screw"
    )


# ---------------------------------------------------------------------------
# Meant to overlap.
# ---------------------------------------------------------------------------


def washer_parts():
    """The M6 screw, and a washer under its head drawn 0.5 up into it."""
    washer = Pos(0, 0, -1 + 0.5) * (Cylinder(6, 2) - Cylinder(3.2, 3))
    return [("screw", socket_screw("M6")), ("washer", washer)]


def test_a_fastener_s_mate_is_none(engine):
    assert found(clashes(washer_parts(), [SCREW], engine=engine)) != []  # the guard
    mated = {**SCREW, "mates": ["washer"]}
    assert found(clashes(washer_parts(), [mated], engine=engine)) == []


def test_a_part_s_own_pieces_are_none():
    # A leaf read as two solids, overlapping: one part split for collision.
    assembly = Assembly(
        [Part("bracket", bracket()), Part("bracket#2", Pos(4, 0, 0) * bracket(), "bracket")]
    )
    assert find_clashes(assembly, Config()).found == ()


def test_an_ignored_part_is_none_unless_asked(engine):
    parts = [("frame", frame(14)), ("bracket", bracket())]
    config = Config.from_dict({"ignore": ["frame"]})
    assembly = Assembly([Part(name, shape) for name, shape in parts])
    assert find_clashes(assembly, config, engine=engine).found == ()
    asked = find_clashes(assembly, config, engine=engine, with_ignored=True)
    assert [(c.first, c.second) for c in asked.found] == [("bracket", "frame")]


@pytest.mark.parametrize("pair", [["bracket", "frame"], ["fr*", "brack*"]])
def test_an_allowed_pair_is_none_either_way_round(pair):
    result = clashes([("frame", frame(14)), ("bracket", bracket())], allow=[pair])
    assert (result.found, result.exit_code) == ((), 0)


def test_an_allow_glob_naming_no_part_fails_the_run():
    result = clashes([("frame", frame(14)), ("bracket", bracket())], allow=[["frame", "brakcet"]])
    assert result.unmatched_allows == ("brakcet",)
    assert result.exit_code == 2  # a renamed part, as an unmatched rule is
    assert "WARN allow matched nothing: 'brakcet' (renamed part?)" in result.lines()


@pytest.mark.parametrize("entry", [["only one"], "a, b", [1, 2], ["a", "b", "c"]])
def test_an_allow_entry_that_is_no_pair_of_globs_is_a_config_error(entry):
    with pytest.raises(ConfigError, match=r"allow\[0\]: an allowed overlap is a two-item list"):
        Config.from_dict({"allow": [entry]})


# ---------------------------------------------------------------------------
# Hints: shortcuts, not verdicts.
# ---------------------------------------------------------------------------


def test_a_pin_a_few_hundredths_into_its_hole_is_a_press_fit_said(engine):
    # A pin 4.06 across in a hole 4 across, 10 deep: a shell 0.03 thick, 2 pi 2.015
    # 0.03 10 = 3.80 mm^3, its surface 2 pi (2 + 2.03) 10 and its two rims, 253.98:
    # twice the volume over the surface, 0.03, is how thick it is.
    block = Pos(0, 0, -5) * Box(20, 20, 10) - Pos(0, 0, -5) * Cylinder(2, 11)
    pin = Pos(0, 0, -5) * Cylinder(2.03, 10)
    result = clashes([("block", block), ("pin", pin)], engine=engine)
    assert found(result) == [
        ("pin", "block", 3.8, None, "a press fit, 0.03 deep? allow it in the sidecar")
    ]


def solid_gland():
    """A gland drawn without its bore: a 24 hex, its dome and stub, solid."""
    body = hex_prism(24, 8) + Pos(0, 0, 15) * Cylinder(10, 14)
    return body + Pos(0, 0, -6) * Cylinder(10, 12)


@pytest.mark.parametrize("name", ["cable_a", "Cable 2", "motor wire"])
def test_a_gland_drawn_into_its_cable_is_said(engine, name):
    cable = Pos(0, 0, 10) * Cylinder(3, 60)
    rule = {"parts": "gland", "kind": "nut", "socket": False, "across_flats": 24}
    result = clashes([("gland", solid_gland()), (name, cable)], [rule], engine=engine)
    ((first, second, _, _, hint),) = found(result)
    assert (first, second, hint) == ("gland", name, "a gland and its cable: drawn without a bore?")


def test_a_grommet_drawn_into_its_cable_is_said():
    grommet = Cylinder(6, 4)
    cable = Cylinder(2, 40)
    ((first, second, _, _, hint),) = found(clashes([("grommet_1", grommet), ("cable", cable)]))
    assert (first, second, hint) == (
        "grommet_1",
        "cable",
        "a gland and its cable: drawn without a bore?",
    )


def test_a_gland_beside_a_part_named_like_no_cable_says_nothing():
    rod = Pos(0, 0, 10) * Cylinder(3, 60)
    rule = {"parts": "gland", "kind": "nut", "socket": False, "across_flats": 24}
    ((*_, hint),) = found(clashes([("gland", solid_gland()), ("leadscrew", rod)], [rule]))
    assert hint is None  # a word in a name, not part of one


# ---------------------------------------------------------------------------
# States: a model of its own.
# ---------------------------------------------------------------------------


def write_step(path, parts):
    """Parts given as (name, shape) written to a STEP file, each named."""
    shapes = []
    for name, shape in parts:
        shape.label = name
        shapes.append(shape)
    export_step(Compound(children=shapes), path)
    return path


def state_files(tmp_path, up_into):
    """The lever down, and its state's model with it up ``up_into`` into the wall."""
    wall = Pos(0, 0, 25) * Box(40, 40, 10)
    write_step(
        tmp_path / "up.step", [("wall", wall), ("lever", Pos(0, 0, 15 + up_into) * Box(4, 4, 10))]
    )
    down = write_step(
        tmp_path / "down.step", [("wall", wall), ("lever", Pos(0, 0, 5) * Box(4, 4, 10))]
    )
    return Assembly.from_step(down)


def test_a_state_s_model_with_a_clash_of_its_own_says_its_state(tmp_path):
    # The lever up 1 into the wall, 4 by 4 by 1: 16 mm^3, in that state alone.
    assembly = state_files(tmp_path, 1.0)
    config = Config.from_dict({"states": {"lever-up": {"model": "up.step"}}})
    result = find_clashes(assembly, config, model_dir=tmp_path)
    assert found(result) == [("lever", "wall", 16.0, "lever-up", None)]
    assert result.lines()[1] == "CLASH lever into wall  16.0 mm^3  in state lever-up"


def test_a_clash_in_the_model_and_its_state_s_is_said_once(tmp_path):
    assembly = state_files(tmp_path, 1.0)
    config = Config.from_dict({"states": {"lever-up": {"model": "up.step"}}})
    up = Assembly.from_step(tmp_path / "up.step")
    result = find_clashes(up, config, model_dir=tmp_path)  # the up model as given, too
    assert found(result) == [("lever", "wall", 16.0, None, None)]
    assert len(find_clashes(assembly, config, model_dir=tmp_path).found) == 1


def test_a_state_that_only_takes_parts_away_adds_none(tmp_path):
    assembly = state_files(tmp_path, 1.0)
    config = Config.from_dict({"states": {"no-lever": {"remove": ["lever"]}}})
    assert find_clashes(assembly, config, model_dir=tmp_path).found == ()


# ---------------------------------------------------------------------------
# Inside check, and in each report.
# ---------------------------------------------------------------------------


def two_blocks():
    return Assembly([Part("frame", frame(14)), Part("bracket", bracket())])


def test_check_looks_only_when_asked():
    off = check(two_blocks(), Config())
    assert (off.clashes, off.exit_code, off.to_json_dict()["clashes"]) == (None, 0, None)
    assert (
        "parts drawn into each other (checks: {clashes: true} turns it on)"
        in (off.terminal_lines()[-1])
    )
    for on in (
        check(two_blocks(), Config(), clashes=True),
        check(two_blocks(), Config.from_dict({"checks": {"clashes": True}})),
    ):
        assert [(c.first, c.second) for c in on.clashes.found] == [("bracket", "frame")]
        assert on.exit_code == 1
        assert "parts drawn into each other" not in on.terminal_lines()[-1]
    sidecar_on = Config.from_dict({"checks": {"clashes": True}})
    assert check(two_blocks(), sidecar_on, clashes=False).clashes is None  # --clashes wins


def test_the_report_says_the_clashes_in_every_format():
    report = check(two_blocks(), Config(), clashes=True)
    lines = report.terminal_lines()
    at = lines.index("1 clash (overlap over 0.05 mm^3)")
    assert lines[at + 1] == "CLASH bracket into frame  100.0 mm^3"
    assert report.to_json_dict()["clashes"] == {
        "floor_mm3": 0.05,
        "found": [
            {
                "parts": ["bracket", "frame"],
                "volume": 100.0,
                "point": [4.5, 0.0, 0.0],
                "state": None,
                "hint": None,
            }
        ],
        "unmatched_allows": [],
        "unmeasured": [],
        "set_in": [],
    }
    section = report.markdown().split("#### Clashes")[1]
    assert "1 clash (overlap over 0.05 mm^3)." in section
    assert "| `bracket` | `frame` | 100.0 |  |" in section
    with pytest.raises(AssertionError, match=re.escape("CLASH bracket into frame  100.0 mm^3")):
        report.assert_all_pass()


def test_no_clash_said_when_looked_for_and_none_found():
    report = check(Assembly([Part("bracket", bracket())]), Config(), clashes=True)
    assert "no clashes (overlap over 0.05 mm^3)" in report.terminal_lines()
    assert report.exit_code == 0


def test_an_allow_glob_naming_nothing_fails_check_too():
    config = Config.from_dict({"allow": [["frame", "nothing_*"]]})
    report = check(two_blocks(), config, clashes=True)
    assert report.exit_code == 2
    assert "WARN allow matched nothing: 'nothing_*' (renamed part?)" in report.terminal_lines()


def test_a_name_from_the_model_can_t_steer_the_terminal():
    hostile = "frame\x1b[2J"
    report = check(
        Assembly([Part(hostile, frame(14)), Part("bracket", bracket())]), Config(), clashes=True
    )
    assert "CLASH bracket into frame\\x1b[2J  100.0 mm^3" in report.terminal_lines()
    assert "`frame\x1b[2J`" not in report.markdown()


# ---------------------------------------------------------------------------
# The engines agree.
# ---------------------------------------------------------------------------


def test_both_engines_find_the_same_clashes():
    chip = Pos(CORNER - 1.0 + 5, 0, 3.4) * Box(10, 30, 3)
    parts = [
        ("nut", nut()),
        ("chip", chip),
        ("frame", Pos(100, 0, 0) * frame(14)),
        ("bracket", Pos(100, 0, 0) * bracket()),
        ("near", Pos(100, 0, 0) * frame(-14.9996)),  # 0.04 mm^3: none
    ]
    mesh, exact = (found(clashes(parts, [NUT], engine=e)) for e in ("mesh", "exact"))
    assert mesh == exact
    assert [(a, b) for a, b, *_ in mesh] == [("bracket", "frame"), ("nut", "chip")]


# ---------------------------------------------------------------------------
# The command.
# ---------------------------------------------------------------------------


def write_model(tmp_path, parts):
    return write_step(tmp_path / "model.step", parts)


def test_the_command_lists_the_clashes_and_exits_1(tmp_path):
    model = write_model(tmp_path, [("frame", frame(14)), ("bracket", bracket())])
    run = CliRunner().invoke(main, ["clashes", str(model)])
    assert run.exit_code == 1, run.output
    assert run.output.splitlines() == [
        "1 clash (overlap over 0.05 mm^3)",
        "CLASH bracket into frame  100.0 mm^3",
    ]


def test_the_command_exits_0_with_none_and_2_on_a_glob_naming_nothing(tmp_path):
    model = write_model(tmp_path, [("bracket", bracket()), ("frame", frame(30))])
    assert CliRunner().invoke(main, ["clashes", str(model)]).exit_code == 0
    sidecar = tmp_path / "wrenchroom.yaml"
    sidecar.write_text("allow: [[bracket, gone]]\n", encoding="utf-8")
    run = CliRunner().invoke(main, ["clashes", str(model)])  # found beside the model
    assert run.exit_code == 2
    assert "WARN allow matched nothing: 'gone' (renamed part?)" in run.output


def test_the_command_writes_json_and_markdown(tmp_path):
    model = write_model(tmp_path, [("frame", frame(14)), ("bracket", bracket())])
    run = CliRunner().invoke(main, ["clashes", str(model), "--json", "-"])
    document = json.loads(run.stdout)
    assert (document["model"], document["engine"]) == ("model.step", "mesh")
    assert document["clashes"]["found"][0]["parts"] == ["bracket", "frame"]
    assert "CLASH bracket into frame" in run.stderr  # the person's lines, out of the way
    md = tmp_path / "clashes.md"
    CliRunner().invoke(main, ["clashes", str(model), "--md", str(md), "--exact"])
    text = md.read_text(encoding="utf-8")
    assert text.startswith("### wrenchroom clashes: `model.step`\n\n1 clash")
    assert "| `bracket` | `frame` | 100.0 |  |" in text


def test_the_command_measures_ignored_parts_when_asked(tmp_path):
    model = write_model(tmp_path, [("frame", frame(14)), ("bracket", bracket())])
    (tmp_path / "wrenchroom.yaml").write_text("ignore: [frame]\n", encoding="utf-8")
    assert CliRunner().invoke(main, ["clashes", str(model)]).exit_code == 0
    assert CliRunner().invoke(main, ["clashes", str(model), "--with-ignored"]).exit_code == 1


def test_check_clashes_turns_it_on(tmp_path):
    model = write_model(tmp_path, [("frame", frame(14)), ("bracket", bracket())])
    assert CliRunner().invoke(main, ["check", str(model)]).exit_code == 0
    run = CliRunner().invoke(main, ["check", str(model), "--clashes"])
    assert run.exit_code == 1
    assert "CLASH bracket into frame  100.0 mm^3" in run.output
