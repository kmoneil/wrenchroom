"""The clash list measures a fastener as its verdict does (issue #156).

#116 made ``check`` measure a clash on all of a screw's head, and #123 on a nut to
its free end, each from the end a tool comes at it from. ``wrenchroom clashes``, and
the list ``check --clashes`` adds, try no tool, so they knew no end, and measured a
fastener on its hex and widest region, as ``check`` did before #116. In one report
the verdicts and the list disagreed: a part drawn into a dome was a clash in the
verdicts and missing from the list, a buried head was all of it in the verdicts and
its rim in the list, a countersunk screw's thread in its tapped hole was a clash in
the list alone, and a screw drawn twice was all of it in the verdicts and its head
in the list.

Now both measure to one end, found the same way: a screw's head's, which its solid
says, and a nut's free one, which the parts round it say. One fastener drawn twice
is told whole, as #94's verdict tells it. Each test here asks both, and the volumes
are worked by hand, most of them in the tests whose solids these are.
"""

import math
import re

import pytest
from build123d import Box, Compound, Cylinder, Pos, RegularPolygon, Rot, export_step, extrude
from click.testing import CliRunner

from test_drawn_twice import M3, dup_parts
from test_drawn_twice import plate as m3_plate
from test_drawn_twice import screw as m3_screw
from test_head_clash import (
    BUTTON,
    FLAT,
    HEAD,
    M4_MINOR,
    SOCKET_AREA,
    button,
    button_down,
    cap,
    counterbored_block,
    countersunk,
    pan,
    plate,
)
from test_nut_clash import BOLT, BORE, PLATE, POCKET, cap_nut, cover
from test_nut_clash import RULES as CAP_RULES
from test_nut_clash import cap as dome_cap
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check, find_clashes
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.report import Verdict

TWICE = "one fastener drawn twice"

DRAWN_INTO = re.compile(r"drawn into (?P<part>.+) \((?P<volume>[\d.]+) mm\^3\): fix the model")
DRAWN_TWICE = re.compile(
    r"drawn twice: (?P<part>.+) is drawn over it \((?P<volume>[\d.]+) mm\^3 in common\)"
)


def both(parts, rules, engine="mesh", kit="full"):
    """A check with its clash list: each verdict by name, and each clash as
    (first, second, volume to 0.1 mm^3, hint)."""
    config = Config.from_dict({"fasteners": list(rules), "checks": {"detect": False}})
    assembly = Assembly([Part(name, shape) for name, shape in parts])
    report = check(assembly, config, engine=engine, kit=kit, clashes=True)
    listed = [(c.first, c.second, round(c.volume, 1), c.hint) for c in report.clashes.found]
    return {r.fastener.name: r for r in report.results}, listed


def told(results):
    """Each clash the verdicts tell, as the list would: (first, second, volume)."""
    found = []
    for name, result in results.items():
        into = DRAWN_INTO.fullmatch(result.reason or "")
        twice = DRAWN_TWICE.match(result.reason or "")
        if into:
            found.append((name, into["part"], float(into["volume"])))
        if twice:  # said on the first by name, of the one drawn over it
            found.append((twice["part"], name, float(twice["volume"])))
    return sorted(found)


def screw_rule(**described):
    return [{"parts": "screw", **described}]


# ---------------------------------------------------------------------------
# A screw's head: the issue's three, and the other profiles.
# ---------------------------------------------------------------------------


def test_a_part_drawn_into_a_dome_is_in_the_list(engine):
    # #116's cover 0.5 down onto an M4 button head's dome: 4.54 mm^3, a clash in
    # the verdict, and missing from the list, which measured the rim under the dome.
    volume = cap(0.8) - cap(0.3) - SOCKET_AREA * 0.5
    parts = [("plate", plate()), ("screw", button()), ("cover", Pos(0, 0, 3.7) * Box(20, 20, 4))]
    results, listed = both(parts, screw_rule(**BUTTON), engine)
    assert results["screw"].reason == f"drawn into cover ({volume:.1f} mm^3): fix the model"
    assert listed == [("screw", "cover", 4.5, None)]


def test_a_buried_head_is_all_of_it_in_the_list(engine):
    # The head in a 20 mm cube from z 0: 62.35 mm^3, where the list said its rim's
    # 18.15.
    parts = [("plate", plate()), ("screw", button()), ("block", Pos(0, 0, 10) * Box(20, 20, 20))]
    results, listed = both(parts, screw_rule(**BUTTON), engine)
    assert results["screw"].reason == f"drawn into block ({HEAD:.1f} mm^3): fix the model"
    assert listed == [("screw", "block", 62.4, None)]
    assert f"{math.pi * 3.8**2 * 0.4:.1f}" == "18.1"  # the rim, as it was told


def test_a_cover_clear_of_the_head_is_no_clash(engine):
    parts = [("plate", plate()), ("screw", button()), ("cover", Pos(0, 0, 6.2) * Box(20, 20, 4))]
    results, listed = both(parts, screw_rule(**BUTTON), engine)
    assert (results["screw"].verdict, results["screw"].reason) == (Verdict.BLOCKED, None)
    assert listed == []


@pytest.mark.parametrize("depth", [0.01, 0.1, 0.3, 0.6, 0.9, 1.2, 1.5, 1.8])
def test_a_cover_any_way_down_a_dome_is_told_the_same_by_both(depth):
    # A cover's underside ``depth`` under the dome's top, as far down as the rim:
    # the cap of 0.3 + depth less the cap of 0.3, cut off flat at the top, less the
    # socket, 1.3 deep. From 0.03 mm^3 (under the floor: no clash) to all the dome.
    volume = cap(0.3 + depth) - cap(0.3) - SOCKET_AREA * min(depth, 1.3)
    slab = Pos(0, 0, 2.2 - depth + 2) * Box(20, 20, 4)
    parts = [("plate", plate()), ("screw", button()), ("cover", slab)]
    results, listed = both(parts, screw_rule(**BUTTON))
    clash = volume > 0.05  # the hit floor
    assert clash is (depth > 0.01)  # the guard: one under the floor, the rest over
    in_the_list = [(first, second, volume) for first, second, volume, _ in listed]
    assert in_the_list == ([("screw", "cover", round(volume, 1))] if clash else [])
    assert told(results) == in_the_list


def test_a_buried_head_s_thread_stays_out_of_the_list(engine):
    # The block down to z -10, tapped at the minor for a shank drawn at the nominal:
    # 43.2 mm^3 of thread in common, which is no clash. The head alone, 62.35.
    block = Pos(0, 0, 5) * Box(20, 20, 30) - Pos(0, 0, -5) * Cylinder(M4_MINOR / 2, 10)
    _, listed = both([("screw", button()), ("block", block)], screw_rule(**BUTTON), engine)
    assert listed == [("screw", "block", 62.4, None)]


def test_a_part_drawn_into_a_pan_head_s_crown_is_in_the_list(engine):
    # #116's cover 0.5 down onto a pan head's crown: 16.68 mm^3, missing from the list.
    parts = [("plate", plate()), ("screw", pan()), ("cover", Pos(0, 0, 4.6) * Box(20, 20, 4))]
    rule = screw_rule(kind="screw", head="phillips", size="M4")
    results, listed = both(parts, rule, engine)
    assert results["screw"].reason == "drawn into cover (16.7 mm^3): fix the model"
    assert listed == [("screw", "cover", 16.7, None)]


@pytest.mark.parametrize(("bore", "volume"), [(5.0, 16.8), (3.5, 85.1)])
def test_a_countersunk_head_s_cone_is_measured_in_the_list(engine, bore, volume):
    # #116's cone in a counterbore drawn too small. Its rim is too thin to be a
    # region, and the list measured the whole screw: the cone and all its thread,
    # 12 long in a hole tapped at the minor.
    parts = [("screw", countersunk()), ("block", counterbored_block(bore))]
    results, listed = both(parts, [FLAT], engine)
    assert results["screw"].reason == f"drawn into block ({volume} mm^3): fix the model"
    assert listed == [("screw", "block", volume, None)]


def test_a_countersunk_screw_s_thread_is_no_clash_in_the_list(engine):
    # A counterbore clear of the cone: only the thread is in common, which the list
    # told as a clash, the whole screw standing in for its head.
    parts = [("screw", countersunk()), ("block", counterbored_block(6.1))]
    results, listed = both(parts, [FLAT], engine)
    assert (results["screw"].verdict, results["screw"].reason) == (Verdict.BLOCKED, None)
    assert listed == []


@pytest.mark.parametrize("down", ["turned", "drawn"])
def test_a_head_pointing_down_is_measured_the_same_in_the_list(engine, down):
    # The buried head upside down: turned over whole, its own axis with it, or drawn
    # head down, its head at the near end along its axis.
    if down == "turned":
        flip = Rot(180, 0, 0)
        parts = [("plate", flip * plate()), ("screw", flip * button())]
    else:
        parts = [("plate", Pos(0, 0, 5) * Box(30, 30, 10) - Cylinder(2, 30))]
        parts.append(("screw", button_down()))
    parts.append(("block", Pos(0, 0, -10) * Box(20, 20, 20)))
    results, listed = both(parts, screw_rule(**BUTTON), engine)
    assert results["screw"].reason == "drawn into block (62.4 mm^3): fix the model"
    assert listed == [("screw", "block", 62.4, None)]


def test_a_rule_s_own_axis_says_which_end_the_head_is(engine):
    # A head drawn without its shank, its rule giving its axis: all of it is head.
    # Left to its solid, its rim is its wide end, and its dome would be its shank.
    head = button() & (Pos(0, 0, 5) * Box(20, 20, 10))
    parts = [("plate", plate()), ("screw", head), ("block", Pos(0, 0, 10) * Box(20, 20, 20))]
    results, listed = both(parts, screw_rule(**BUTTON, axis="+z"), engine)
    assert results["screw"].reason == "drawn into block (62.4 mm^3): fix the model"
    assert listed == [("screw", "block", 62.4, None)]


def test_a_screw_whose_head_end_can_t_be_told_is_still_measured():
    # A plain rod 6 across, named a screw: both its ends alike, so no verdict, and
    # no head to measure. The list measures it as before, all of it: a lid 1 down
    # onto its end, pi 9 = 28.3 mm^3.
    rod = Pos(0, 0, 10) * Cylinder(3, 20)
    lid = Pos(0, 0, 19 + 5) * Box(20, 20, 10)
    rule = screw_rule(kind="screw", head="socket", size="M6")
    results, listed = both([("screw", rod), ("lid", lid)], rule)
    assert results["screw"].reason == "cannot tell the head end: both ends look alike"
    assert listed == [("screw", "lid", 28.3, None)]


# ---------------------------------------------------------------------------
# A nut: its free end, as the check finds it.
# ---------------------------------------------------------------------------

STUD = Pos(0, 0, -2.5) * Cylinder(4, 15)  # no fastener: nothing pairs with the nut
NUT_ALONE = CAP_RULES[:1]


def hexagon_prism(af, height):
    """A hex prism ``af`` across flats, centred on the origin."""
    return Pos(0, 0, -height / 2) * extrude(RegularPolygon(af / math.sqrt(3), 6), height)


def on_a_stud(*extra, nut=None):
    return [("plate", PLATE), ("nut", nut or cap_nut()), ("stud", STUD), *extra]


def test_a_cap_nut_on_a_stud_is_measured_to_its_dome_in_the_list(engine):
    # #123's cap nut, a cover 2 into its dome, a cap of 2 of a sphere of 6: 67.02
    # mm^3. On a bolt, the bolt said which end its dome is; on a stud no rule
    # names, nothing did, and the list measured its hex alone, under the cover.
    parts = on_a_stud(("pocket", POCKET), ("cover", cover(13.0)))
    results, listed = both(parts, NUT_ALONE, engine, kit="metric-home")
    assert results["nut"].reason == "drawn into cover (67.0 mm^3): fix the model"
    assert listed == [("nut", "cover", 67.0, None)]
    assert f"{dome_cap(2):.1f}" == "67.0"


def test_a_clash_that_stops_no_tool_is_in_the_list_all_the_same(engine):
    # No pocket: the open end turns the nut from the side, under the cover, and a
    # verdict asks of no clash. The list is where the cover in its dome is said.
    results, listed = both(on_a_stud(("cover", cover(13.0))), NUT_ALONE, engine, kit="metric-home")
    assert (results["nut"].verdict, results["nut"].reason) == (Verdict.TURNS, None)
    assert listed == [("nut", "cover", 67.0, None)]


def test_a_nut_whose_own_axis_points_into_its_stud_is_measured_the_same(engine):
    # The same nut, its bore drawn pointing down: its free end is its frame's low end.
    parts = on_a_stud(("pocket", POCKET), ("cover", cover(13.0)), nut=cap_nut(bore_down=True))
    results, listed = both(parts, NUT_ALONE, engine, kit="metric-home")
    assert results["nut"].reason == "drawn into cover (67.0 mm^3): fix the model"
    assert listed == [("nut", "cover", 67.0, None)]


BURIED = math.pi * 6.25**2 * 2 + 2 / 3 * math.pi * 6**3 - math.pi * BORE**2 * 5  # 524.33


def test_a_nut_both_of_whose_ends_are_covered_is_measured_from_its_bolt(engine):
    # #123's dome buried from z 7: no free end to find, and its bolt says which.
    parts = [("plate", PLATE), ("nut", cap_nut()), ("cover", cover(7.0)), ("bolt", BOLT)]
    results, listed = both(parts, CAP_RULES, engine, kit="metric-home")
    assert results["nut"].reason == f"drawn into cover ({BURIED:.1f} mm^3): fix the model"
    assert listed == [("nut", "cover", 524.3, None)]


def test_with_neither_a_free_end_nor_a_bolt_its_hex_and_widest_region_are_measured(engine):
    # Buried on a stud: nothing says which end is free, and both tell #123's 176.0.
    results, listed = both(on_a_stud(("cover", cover(7.0))), NUT_ALONE, engine, kit="metric-home")
    assert results["nut"].reason == "drawn into cover (176.0 mm^3): fix the model"
    assert listed == [("nut", "cover", 176.0, None)]


# ---------------------------------------------------------------------------
# One fastener drawn twice.
# ---------------------------------------------------------------------------

M3_RULES = [{"parts": "M3x* SHCS", **M3}]
#: #94's M3x8: a head 5.5 by 3 less its socket, 2.5 across flats and 1.3 deep, and a
#: shank 3 by 8. The list told the head alone, 64.2.
M3_HEAD = math.pi * 2.75**2 * 3 - math.sqrt(3) / 2 * 2.5**2 * 1.3
M3_WHOLE = M3_HEAD + math.pi * 1.5**2 * 8


def test_a_screw_drawn_twice_is_told_whole_as_its_verdict_tells_it(engine):
    results, listed = both(dup_parts(), M3_RULES, engine, kit="metric-home")
    assert results["M3x12 SHCS"].reason == (
        "drawn twice: M3x8 SHCS is drawn over it (120.8 mm^3 in common): fix the model"
    )
    # The later by name into the first, as the verdict says them, whichever the
    # model has first: here the M3x8.
    assert listed == [("M3x8 SHCS", "M3x12 SHCS", 120.8, TWICE)]
    assert told(results) == [("M3x8 SHCS", "M3x12 SHCS", 120.8)]
    assert (f"{M3_HEAD:.1f}", f"{M3_WHOLE:.1f}") == ("64.2", "120.8")


def test_three_drawn_over_one_another_are_each_pair_told_whole():
    parts = [*dup_parts(), ("M3x16 SHCS", m3_screw())]
    _, listed = both(parts, M3_RULES, kit="metric-home")
    assert listed == [
        ("M3x16 SHCS", "M3x12 SHCS", 120.8, TWICE),
        ("M3x8 SHCS", "M3x12 SHCS", 120.8, TWICE),
        ("M3x8 SHCS", "M3x16 SHCS", 120.8, TWICE),
    ]


def stepped(shift):
    """Two screws on one axis, the second ``shift`` up it: a head 6 by 3 on a shank
    3 by 9, no socket drawn. They share pi (9 (3 - shift) + 20.25) of each one's
    47.25 pi: half at a shift of 2.625."""
    solid = Pos(0, 0, 1.5) * Cylinder(3, 3) + Pos(0, 0, -4.5) * Cylinder(1.5, 9)
    return [("a_screw", solid), ("b_screw", Pos(0, 0, shift) * solid)]


STEPPED = [{"parts": "*_screw", "kind": "screw", "head": "socket", "size": "M3"}]


def test_over_half_of_each_in_common_is_one_drawn_twice(engine):
    # 2.5 up: 24.75 pi of 47.25 pi, 0.524 of each, all of it told: 77.8 mm^3. The
    # verdict and the list draw the line at the same half.
    results, listed = both(stepped(2.5), STEPPED, engine)
    assert listed == [("b_screw", "a_screw", 77.8, TWICE)]
    assert told(results) == [("b_screw", "a_screw", 77.8)]
    assert list(results) == ["a_screw"]  # the one drawn over it isn't checked again
    assert f"{math.pi * 24.75:.1f}" == "77.8"


def test_under_half_in_common_is_two_fasteners_measured_past_their_threads(engine):
    # 2.75 up: 0.476 of each. Two screws, each measured on its head. The lower
    # one's has the upper's head 0.25 into it, 9 pi 0.25, and its shank through it
    # from under that, 2.25 pi 2.75: 8.4375 pi = 26.51, the larger measure of the
    # two. The shanks in common, 6.25 long, are threads, and not added.
    results, listed = both(stepped(2.75), STEPPED, engine)
    assert listed == [("a_screw", "b_screw", 26.5, None)]
    assert sorted(results) == ["a_screw", "b_screw"]  # two fasteners to the verdicts too
    assert not any((r.reason or "").startswith("drawn twice") for r in results.values())
    assert f"{math.pi * 8.4375:.1f}" == "26.5"


def test_a_small_fastener_inside_a_big_one_is_no_twin():
    # #94's M3x4 set screw drawn wholly inside an M10 bolt's head: all of the small
    # one in common, little of the big. A clash, of two fasteners.
    big = Pos(0, 0, 3.2) * Cylinder(8, 6.4) + Pos(0, 0, -15) * Cylinder(5, 30)
    small = Pos(0, 0, 4) * Cylinder(1.5, 4)
    rules = [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M10"},
        {"parts": "set", "kind": "screw", "head": "socket", "size": "M3", "axis": "+z"},
    ]
    _, listed = both([("bolt", big), ("set", small)], rules)
    assert len(listed) == 1
    assert listed[0][3] is None


def test_a_screw_and_a_part_that_is_no_fastener_are_no_twins():
    # The same solid twice, one of them no fastener: a part drawn into a screw, as
    # any is, measured past the screw's thread: its head, 64.2.
    parts = [("plate", m3_plate()), ("M3x8 SHCS", m3_screw()), ("copy", m3_screw())]
    _, listed = both(parts, M3_RULES, kit="metric-home")
    assert listed == [("M3x8 SHCS", "copy", 64.2, None)]


# ---------------------------------------------------------------------------
# One report: the issue's model, as the command says it.
# ---------------------------------------------------------------------------


def issue_model(path):
    """The issue's three cells, 100 apart: #116's M4 button head buried in a block,
    under a cover 0.5 down onto its dome, and under one clear of it; and #94's
    screw drawn twice."""
    cells = {
        "buried": {"block": Pos(0, 0, 10) * Box(20, 20, 20)},
        "dome": {"cover": Pos(0, 0, 3.7) * Box(20, 20, 4)},
        "clear": {"cover": Pos(0, 0, 6.2) * Box(20, 20, 4)},
    }
    shapes = []
    for index, (tag, extra) in enumerate(cells.items()):
        for name, shape in {"plate": plate(), "M4x10 BHCS": button(), **extra}.items():
            placed = Pos(index * 100, 0, 0) * shape
            placed.label = f"{tag} {name}"
            shapes.append(placed)
    for name, shape in dup_parts():
        placed = Pos(300, 0, 0) * shape
        placed.label = f"dup {name}"
        shapes.append(placed)
    export_step(Compound(children=shapes), path)
    return path


@pytest.mark.parametrize("exact", [False, True])
def test_check_s_verdicts_and_its_clash_list_agree(tmp_path, exact):
    model = issue_model(tmp_path / "dome.step")
    args = ["check", str(model), "--clashes", *(["--exact"] if exact else [])]
    said = CliRunner().invoke(main, args).output.splitlines()
    verdicts = [line for line in said if line.startswith("FAIL")]
    assert verdicts == [
        "FAIL clear M4x10 BHCS  hex-key-2.5  blocked  clear cover",
        "FAIL buried M4x10 BHCS  -  not-covered  drawn into buried block (62.4 mm^3): "
        "fix the model",
        "FAIL dome M4x10 BHCS  -  not-covered  drawn into dome cover (4.5 mm^3): fix the model",
        "FAIL dup M3x12 SHCS  -  not-covered  drawn twice: dup M3x8 SHCS is drawn over it "
        "(120.8 mm^3 in common): fix the model",
    ]
    at = said.index("3 clashes (overlap over 0.05 mm^3)")
    assert said[at + 1 : at + 4] == [
        "CLASH buried M4x10 BHCS into buried block  62.4 mm^3",
        "CLASH dome M4x10 BHCS into dome cover  4.5 mm^3",
        "CLASH dup M3x8 SHCS into dup M3x12 SHCS  120.8 mm^3  (one fastener drawn twice)",
    ]


def test_the_clashes_command_tells_the_same_list(tmp_path):
    model = issue_model(tmp_path / "dome.step")
    result = CliRunner().invoke(main, ["clashes", str(model), "--md", "-"])
    assert result.exit_code == 1
    assert result.output.splitlines()[:4] == [
        "3 clashes (overlap over 0.05 mm^3)",
        "CLASH buried M4x10 BHCS into buried block  62.4 mm^3",
        "CLASH dome M4x10 BHCS into dome cover  4.5 mm^3",
        "CLASH dup M3x8 SHCS into dup M3x12 SHCS  120.8 mm^3  (one fastener drawn twice)",
    ]
    assert (
        "| `dup M3x8 SHCS` | `dup M3x12 SHCS` | 120.8 | one fastener drawn twice |" in result.output
    )


def test_a_twin_s_hint_is_in_the_json():
    assembly = Assembly([Part(name, shape) for name, shape in dup_parts()])
    report = check(assembly, Config.from_dict({"fasteners": M3_RULES}), clashes=True)
    (entry,) = report.to_json_dict()["clashes"]["found"]
    assert (entry["parts"], entry["volume"], entry["hint"]) == (
        ["M3x8 SHCS", "M3x12 SHCS"],
        120.79,
        TWICE,
    )


# ---------------------------------------------------------------------------
# A state's own model: measured where the state's parts are off.
# ---------------------------------------------------------------------------


def test_a_nut_is_measured_in_its_state_s_scene(tmp_path):
    # The cap nut on its stud, a cover 2 into its dome, and a guard, a ring on its
    # hex's top round its collar: both its ends covered, and no bolt, so its hex
    # and widest region are measured, which the cover is clear of. A state with
    # the guard off, its own model the same: there its free end is found, and its
    # dome measured, 67.02 mm^3.
    guard = Pos(0, 0, 7) * (Cylinder(7.1, 1) - Cylinder(6.3, 2))
    parts = on_a_stud(("cover", cover(13.0)), ("guard", guard))
    shapes = []
    for name, shape in parts:
        shape.label = name
        shapes.append(shape)
    for name in ("closed.step", "open.step"):
        export_step(Compound(children=shapes), tmp_path / name)
    states = {"guard-off": {"model": "open.step", "remove": ["guard"]}}
    config = Config.from_dict(
        {"fasteners": NUT_ALONE, "checks": {"detect": False}, "states": states}
    )
    assembly = Assembly.from_step(tmp_path / "closed.step")
    found = find_clashes(assembly, config, model_dir=tmp_path).found
    assert [(c.first, c.second, round(c.volume, 1), c.state) for c in found] == [
        ("nut", "cover", 67.0, "guard-off")
    ]


# ---------------------------------------------------------------------------
# A nut held by its trap: its note and its line in the list.
# ---------------------------------------------------------------------------


def test_a_trapped_nut_s_note_and_its_line_in_the_list_agree(engine):
    # The cap nut on its stud in a housing: a hex pocket 13.2 across round its hex,
    # which holds it; over that a round cavity, its free face clear; and a lid from
    # z 13, 2 into its dome, all one part. The check notes what it is drawn into its
    # trap by, measured to its free end as the list measures it: 67.02 mm^3. With no
    # bolt to say which end is free, the note measured its hex, and said nothing.
    pocket = Pos(0, 0, 3.25) * (Box(60, 60, 6.5) - hexagon_prism(13.2, 6.5))
    cavity = Pos(0, 0, 9.75) * (Box(60, 60, 6.5) - Cylinder(8.0, 6.5))
    housing = pocket + cavity + cover(13.0)
    results, listed = both(on_a_stud(("housing", housing)), NUT_ALONE, engine, kit="metric-home")
    nut = results["nut"]
    assert (nut.verdict, nut.how) == (Verdict.HELD, "held by its trap in housing")
    assert nut.notes == ("drawn 67.0 mm^3 into its trap: a press fit, or a clash to fix",)
    # And the line says what the note says (issue #158).
    assert listed == [("nut", "housing", 67.0, "its trap: a press fit, or a clash to fix")]


def test_one_drawn_twice_in_a_state_s_model_alone_says_its_state(tmp_path):
    # Two M3 screws in two holes 20 apart; in the state's own model the second is
    # drawn over the first: one drawn twice, there and nowhere else.
    def model(apart):
        screws = [("M3x8 SHCS", m3_screw()), ("M3x12 SHCS", Pos(apart, 0, 0) * m3_screw())]
        return [("plate", m3_plate() - Pos(20, 0, 0) * Cylinder(1.5, 30)), *screws]

    for name, apart in (("apart.step", 20), ("over.step", 0)):
        shapes = []
        for label, shape in model(apart):
            shape.label = label
            shapes.append(shape)
        export_step(Compound(children=shapes), tmp_path / name)
    config = Config.from_dict({"fasteners": M3_RULES, "states": {"moved": {"model": "over.step"}}})
    assembly = Assembly.from_step(tmp_path / "apart.step")
    found = find_clashes(assembly, config, model_dir=tmp_path).found
    assert [(c.first, c.second, round(c.volume, 1), c.state, c.hint) for c in found] == [
        ("M3x8 SHCS", "M3x12 SHCS", 120.8, "moved", TWICE)
    ]
