"""An insert set into its part is no clash, and a nut in its trap is said so (issue #158).

A heat-set insert goes into a hole drawn smaller than its knurl, so overlapping the
part it is melted into is what it is drawn to do. On printed-part models such
overlaps were half of every clash list, each failing ``check --clashes`` and each
needing an ``allow:`` of its own, with the real clashes hard to find among them.

Now an insert set into a part is counted apart, and fails nothing. It is set into a
part that is round its middle and takes up no more than 0.3 of its own cylinder
along the length the two share: a hole 0.84 of the insert across, or more. A part
over one end of it only, or one with no hole for it (a hole drawn for the screw
alone takes half of it), is a clash as before.

The makers' holes, each 0.87 to 0.93 of its insert, and ISO 273's medium clearance
hole for the same thread, 0.68 to 0.81 of it, are the two families below. The
volumes are a shell's, pi (R^2 - r^2) L.

A nut or a hex head drawn into the trap that holds it stays a clash, with the words
``check`` notes it in: a press fit, or a clash to fix.
"""

import math

import pytest
from build123d import Box, Compound, Cylinder, Pos, export_step
from click.testing import CliRunner

from test_head_trap import BOLT as HEX_BOLT
from test_head_trap import NUT as HEX_NUT
from test_head_trap import trapped
from test_traps import NUT, SCREW, hexagon, pocket_parts
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check, find_clashes
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.report import Verdict

DEEP = "deeper than a knurl: no hole drawn for the insert?"
TRAP = "its trap: a press fit, or a clash to fix"
LISTS = " (wrenchroom clashes --with-inserts lists them)"

INSERT = {"parts": "insert*", "kind": "insert", "size": "M3"}


def insert(across=5.0, bore=3.0, length=4.0):
    """An insert ``across`` wide and ``length`` long under z = 0, bored for its thread."""
    return Pos(0, 0, -length / 2) * (Cylinder(across / 2, length) - Cylinder(bore / 2, length + 1))


def block(hole, depth=4.0, screw=3.4):
    """A block under z = 0 with a hole ``hole`` across and ``depth`` deep for the
    insert, and the screw's own hole, ``screw`` across, on through it."""
    solid = Pos(0, 0, -8) * Box(30, 30, 16) - Cylinder(screw / 2, 40)
    return solid - Pos(0, 0, -depth / 2) * Cylinder(hole / 2, depth)


def shell(across, hole, length=4.0):
    return math.pi * ((across / 2) ** 2 - (hole / 2) ** 2) * length


def clashes(parts, rules=(INSERT,), engine="mesh", **sidecar):
    config = Config.from_dict({"fasteners": list(rules), "checks": {"detect": False}, **sidecar})
    assembly = Assembly([Part(name, shape) for name, shape in parts])
    return find_clashes(assembly, config, engine=engine)


def said(found):
    return [(c.first, c.second, round(c.volume, 1), c.hint) for c in found]


# ---------------------------------------------------------------------------
# Set into its part.
# ---------------------------------------------------------------------------


def test_an_insert_in_a_hole_drawn_smaller_than_it_is_set_in(engine):
    # 5.0 across in a hole 4.6 across, 4 deep: a skin 0.2 thick, 12.06 mm^3, 0.15 of
    # the insert's own cylinder. It was a clash, and failed the run.
    result = clashes([("insert", insert()), ("block", block(4.6))], engine=engine)
    assert said(result.found) == []
    assert said(result.set_in) == [("insert", "block", 12.1, None)]
    assert result.exit_code == 0
    assert result.lines() == [
        "no clashes (overlap over 0.05 mm^3)",
        "NOTE 1 insert set into its part, no clash" + LISTS,
    ]
    assert f"{shell(5.0, 4.6):.2f}" == "12.06"


def test_asked_for_each_insert_set_in_is_a_line():
    result = clashes([("insert", insert()), ("block", block(4.6))])
    assert result.lines(with_inserts=True) == [
        "no clashes (overlap over 0.05 mm^3)",
        "NOTE 1 insert set into its part, no clash",
        "SET insert into block  12.1 mm^3",
    ]


@pytest.mark.parametrize(
    ("hole", "share", "volume"),
    [
        (4.25, 0.2775, 21.8),  # 0.85 of the insert: set in
        (4.10, 0.3276, 25.7),  # 0.82 of it: more than a knurl
    ],
)
def test_a_hole_under_0_84_of_the_insert_is_no_hole_for_it(engine, hole, share, volume):
    # The share is 1 - (hole / insert)^2, and 0.3 is the line.
    assert 1 - (hole / 5.0) ** 2 == pytest.approx(share, abs=1e-4)
    result = clashes([("insert", insert()), ("block", block(hole))], engine=engine)
    hint = None if share <= 0.3 else DEEP
    told = [("insert", "block", volume, hint)]
    assert (said(result.found), said(result.set_in)) == (([], told) if hint is None else (told, []))
    assert result.exit_code == (0 if hint is None else 1)


def test_an_insert_in_a_hole_drawn_for_its_screw_alone_is_a_clash(engine):
    # No hole for the insert: the screw's, 3.4 across, right through. The block takes
    # up 1 - 0.68^2 = 0.54 of the insert, 42.2 mm^3.
    result = clashes([("insert", insert()), ("block", block(3.4, depth=0.0))], engine=engine)
    assert said(result.found) == [("insert", "block", 42.2, DEEP)]
    assert result.set_in == ()
    assert result.lines() == [
        "1 clash (overlap over 0.05 mm^3)",
        f"CLASH insert into block  42.2 mm^3  ({DEEP})",
    ]


def test_the_share_is_of_the_length_the_two_share():
    # The insert standing 1.4 proud of the block, 2.6 of its 4 in a hole 4.1 across:
    # the block takes up 0.33 of it where it is in the block, not 0.21 of all of it.
    proud = Pos(0, 0, 1.4) * insert()
    result = clashes([("insert", proud), ("block", block(4.1, depth=2.6))])
    assert said(result.found) == [("insert", "block", round(shell(5.0, 4.1, 2.6), 1), DEEP)]
    assert (1 - 0.82**2) * 2.6 / 4 < 0.3 < 1 - 0.82**2  # the guard: either side of the line


def test_an_insert_set_in_is_no_press_fit_to_allow(engine):
    # A hole 4.9 across: a skin 0.05 thick, 3.11 mm^3, which on any other part reads
    # "a press fit, 0.05 deep? allow it in the sidecar". Set in, it says nothing.
    result = clashes([("insert", insert()), ("block", block(4.9))], engine=engine)
    assert (said(result.found), said(result.set_in)) == ([], [("insert", "block", 3.1, None)])
    pin = [("pin", Pos(0, 0, -2) * Cylinder(2.5, 4)), ("block", block(4.9))]
    assert said(clashes(pin, rules=()).found) == [
        ("pin", "block", 3.1, "a press fit, 0.05 deep? allow it in the sidecar")
    ]


#: Each maker's insert and the hole it gives for it, mm, and ISO 273's medium
#: clearance hole for the same thread: (thread, insert, hole, clearance).
MAKERS = [
    ("M2", 3.5, 3.2, 2.4),  # Albany County Fasteners
    ("M2", 3.6, 3.2, 2.4),  # ruthex
    ("M2.5", 4.0, 3.7, 2.9),
    ("M3", 4.6, 4.0, 3.4),  # ruthex, ACF: the least of them, 0.870
    ("M3", 5.0, 4.4, 3.4),  # ruthex's M3x5x4
    ("M4", 6.0, 5.3, 4.5),
    ("M4", 6.3, 5.6, 4.5),
    ("M5", 7.1, 6.4, 5.5),
    ("M6", 8.4, 7.6, 6.6),
    ("M8", 11.1, 10.2, 9.0),  # the clearance hole nearest an insert's: 0.811
]


@pytest.mark.parametrize(("thread", "across", "hole", "clearance"), MAKERS)
def test_a_maker_s_hole_sets_its_insert_in_and_a_clearance_hole_doesn_t(
    thread, across, hole, clearance
):
    rule = {"parts": "insert", "kind": "insert", "size": thread}
    bore = float(thread[1:])
    length = 2 * bore
    made = [("insert", insert(across, bore, length))]
    set_in = clashes([*made, ("block", block(hole, length, clearance))], [rule])
    assert said(set_in.found) == []
    assert said(set_in.set_in) == [("insert", "block", round(shell(across, hole, length), 1), None)]
    bare = clashes([*made, ("block", block(clearance, 0.0, clearance))], [rule])
    assert said(bare.found) == [
        ("insert", "block", round(shell(across, clearance, length), 1), DEEP)
    ]
    assert bare.set_in == ()


def test_the_makers_holes_and_the_clearance_holes_stand_either_side_of_the_line():
    # The guard: no maker's hole under 0.87 of its insert, no clearance hole over 0.82.
    assert min(hole / across for _, across, hole, _ in MAKERS) == pytest.approx(0.870, abs=5e-4)
    assert max(clear / across for _, across, _, clear in MAKERS) == pytest.approx(0.811, abs=5e-4)
    assert math.sqrt(1 - 0.3) == pytest.approx(0.837, abs=5e-4)


def test_an_insert_in_two_parts_drawn_in_one_place_is_set_into_both():
    # Two options of one part, both in the model, as printed machines are drawn:
    # each holds the insert. The two blocks, one drawn over the other, are the clash.
    parts = [("insert", insert()), ("block_a", block(4.6)), ("block_b", block(4.6))]
    result = clashes(parts)
    assert said(result.set_in) == [
        ("insert", "block_a", 12.1, None),
        ("insert", "block_b", 12.1, None),
    ]
    assert [(c.first, c.second) for c in result.found] == [("block_a", "block_b")]
    assert result.lines(with_inserts=True)[2:] == [
        "NOTE 1 insert set into its part, no clash",
        "SET insert into block_a  12.1 mm^3",
        "SET insert into block_b  12.1 mm^3",
    ]


def test_several_inserts_are_counted_each_once():
    parts = [("block", block(4.6) - Pos(10, 0, -2) * Cylinder(2.3, 4))]
    parts += [("insert_a", insert()), ("insert_b", Pos(10, 0, 0) * insert())]
    result = clashes(parts)
    assert result.lines() == [
        "no clashes (overlap over 0.05 mm^3)",
        "NOTE 2 inserts set into their parts, no clashes" + LISTS,
    ]


def test_an_insert_with_a_flange_is_measured_on_what_is_in_the_hole():
    # A flange 6.4 across and 0.5 thick on the block's face; the body, 5.0, in the
    # hole. The share is of the body's cylinder, the overlap's own radius.
    flanged = insert() + Pos(0, 0, 0.25) * (Cylinder(3.2, 0.5) - Cylinder(1.5, 1))
    result = clashes([("insert", flanged), ("block", block(4.6))])
    assert (said(result.found), said(result.set_in)) == ([], [("insert", "block", 12.1, None)])


# ---------------------------------------------------------------------------
# Not set in: a part over one end, a fastener, a pair.
# ---------------------------------------------------------------------------


def cover(into, hole=3.4):
    """A cover on the block, ``into`` down into the insert's top, the screw's hole in it."""
    return Pos(0, 0, 5 - into) * Box(30, 30, 10) - Cylinder(hole / 2, 40)


def test_a_part_over_one_end_of_an_insert_is_a_clash(engine):
    # The cover 0.5 down into the insert's face: pi (2.5^2 - 1.7^2) 0.5 = 5.28 mm^3,
    # over its last 0.5, not round its middle. The insert is set into its block.
    parts = [("insert", insert()), ("block", block(4.6)), ("cover", cover(0.5))]
    result = clashes(parts, allow=[["block", "cover"]], engine=engine)
    assert said(result.found) == [("insert", "cover", 5.3, None)]
    assert said(result.set_in) == [("insert", "block", 12.1, None)]


def test_however_thin_a_part_over_one_end_is_a_press_fit_at_most():
    # 0.05 down into it: thin as a knurl's skin, and still the next part along.
    parts = [("insert", insert()), ("block", block(4.6)), ("cover", cover(0.05))]
    result = clashes(parts, allow=[["block", "cover"]])
    assert said(result.found) == [
        ("insert", "cover", 0.5, "a press fit, 0.05 deep? allow it in the sidecar")
    ]


def test_an_insert_across_two_parts_is_set_into_the_one_round_its_middle():
    # A plate 1.5 thick on a block, the hole through both: the block is round the
    # insert from its start to 2.5 along, past its middle; the plate, over its last 1.5.
    lower = Pos(0, 0, -8.75) * Box(30, 30, 14.5) - Cylinder(1.7, 40)
    lower -= Pos(0, 0, -2.75) * Cylinder(2.3, 2.5)
    plate = Pos(0, 0, -0.75) * Box(30, 30, 1.5) - Cylinder(2.3, 40)
    result = clashes([("insert", insert()), ("block", lower), ("plate", plate)])
    assert said(result.set_in) == [("insert", "block", round(shell(5.0, 4.6, 2.5), 1), None)]
    assert said(result.found) == [("insert", "plate", round(shell(5.0, 4.6, 1.5), 1), None)]


def test_a_part_round_an_insert_s_first_end_only_is_no_part_it_is_set_into():
    # The other way up: a base 1.5 thick under the block, the hole through both. The
    # base is round the insert's first 1.5, short of its middle at 2.0; the block,
    # round the rest.
    base = Pos(0, 0, -9.25) * Box(30, 30, 13.5) - Cylinder(1.7, 40)
    base -= Pos(0, 0, -3.25) * Cylinder(2.3, 1.5)
    upper = Pos(0, 0, -1.25) * Box(30, 30, 2.5) - Cylinder(2.3, 40)
    result = clashes([("insert", insert()), ("base", base), ("block", upper)])
    assert said(result.set_in) == [("insert", "block", round(shell(5.0, 4.6, 2.5), 1), None)]
    assert said(result.found) == [("insert", "base", round(shell(5.0, 4.6, 1.5), 1), None)]


def test_a_fastener_round_an_insert_is_no_part_it_is_set_into():
    # An M5 nut drawn round the insert's middle, bored 4.8: a skin as thin as a
    # hole's, round its middle, and a fastener: a clash of the two, as it was.
    collar = Pos(0, 0, -3.2) * (hexagon(8, 2.4) - Cylinder(2.4, 10))
    rules = [INSERT, {"parts": "collar", "kind": "nut", "size": "M5"}]
    result = clashes([("insert", insert()), ("collar", collar)], rules)
    assert result.set_in == ()
    assert [(c.first, c.second) for c in result.found] == [("insert", "collar")]
    assert result.found[0].hint != DEEP


def test_an_insert_and_the_screw_in_it_are_a_pair_as_before():
    screw = Pos(0, 0, 2) * Cylinder(2.75, 3) + Pos(0, 0, -4) * Cylinder(1.5, 9)
    rules = [INSERT, {"parts": "screw", "kind": "screw", "head": "socket", "size": "M3"}]
    parts = [("insert", insert(bore=2.4)), ("block", block(4.6)), ("screw", screw)]
    result = clashes(parts, rules)
    assert (said(result.found), said(result.set_in)) == ([], [("insert", "block", 12.1, None)])


def test_an_insert_named_like_one_is_set_in_with_no_rule():
    parts = [("M3 heat set insert", insert()), ("block", block(4.6))]
    assembly = Assembly([Part(name, shape) for name, shape in parts])
    result = find_clashes(assembly, Config())
    assert said(result.set_in) == [("M3 heat set insert", "block", 12.1, None)]
    assert result.found == ()


# ---------------------------------------------------------------------------
# In every format, and in check.
# ---------------------------------------------------------------------------


def set_and_bare():
    """One insert set into its block, and one in a block with no hole for it."""
    return [
        ("insert_set", insert()),
        ("block", block(4.6)),
        ("insert_bare", Pos(50, 0, 0) * insert()),
        ("slab", Pos(50, 0, 0) * block(3.4, depth=0.0)),
    ]


def test_the_json_gives_the_inserts_set_in_apart():
    document = clashes(set_and_bare()).to_json()
    assert [entry["parts"] for entry in document["found"]] == [["insert_bare", "slab"]]
    assert document["found"][0]["hint"] == DEEP
    assert document["set_in"] == [
        {
            "parts": ["insert_set", "block"],
            "volume": 12.06,
            "point": [0.0, 0.0, -2.0],
            "state": None,
        }
    ]


def test_the_markdown_counts_them_and_lists_them_when_asked():
    result = clashes(set_and_bare())
    plain = result.markdown_text("m.step")
    assert f"| `insert_bare` | `slab` | 42.2 | {DEEP} |" in plain
    assert "- 1 insert set into its part, no clash" in plain
    assert "insert_set" not in plain
    asked = result.markdown_text("m.step", with_inserts=True)
    assert "| Insert | Set into | Overlap (mm^3) | |" in asked
    assert "| `insert_set` | `block` | 12.1 |  |" in asked


def test_check_counts_them_and_fails_on_none():
    parts = [("insert", insert()), ("block", block(4.6))]
    config = Config.from_dict({"fasteners": [INSERT], "checks": {"detect": False}})
    report = check(Assembly([Part(n, s) for n, s in parts]), config, clashes=True)
    assert report.exit_code == 0  # it was 1: the insert in its own hole
    lines = report.terminal_lines()
    at = lines.index("no clashes (overlap over 0.05 mm^3)")
    assert lines[at + 1] == "NOTE 1 insert set into its part, no clash" + LISTS
    assert report.to_json_dict()["clashes"]["set_in"][0]["parts"] == ["insert", "block"]
    assert "- 1 insert set into its part, no clash" in report.markdown()
    report.assert_all_pass()


def write_model(path, parts):
    shapes = []
    for name, shape in parts:
        shape.label = name
        shapes.append(shape)
    export_step(Compound(children=shapes), path)
    return path


def test_the_command_lists_them_with_inserts(tmp_path):
    model = write_model(tmp_path / "model.step", [("M3 insert", insert()), ("block", block(4.6))])
    plain = CliRunner().invoke(main, ["clashes", str(model)])
    assert plain.exit_code == 0
    assert plain.output.splitlines() == [
        "no clashes (overlap over 0.05 mm^3)",
        "NOTE 1 insert set into its part, no clash" + LISTS,
    ]
    asked = CliRunner().invoke(main, ["clashes", str(model), "--with-inserts"])
    assert asked.output.splitlines() == [
        "no clashes (overlap over 0.05 mm^3)",
        "NOTE 1 insert set into its part, no clash",
        "SET M3 insert into block  12.1 mm^3",
    ]
    page = CliRunner().invoke(main, ["clashes", str(model), "--with-inserts", "--md", "-"])
    assert page.exit_code == 0
    assert "| `M3 insert` | `block` | 12.1 |  |" in page.output
    assert "M3 insert" not in CliRunner().invoke(main, ["clashes", str(model), "--md", "-"]).stdout


def test_a_state_s_model_with_the_same_insert_says_it_once(tmp_path):
    parts = [("insert", insert()), ("block", block(4.6))]
    write_model(tmp_path / "open.step", parts)
    config = Config.from_dict(
        {
            "fasteners": [INSERT],
            "checks": {"detect": False},
            "states": {"open": {"model": "open.step"}},
        }
    )
    assembly = Assembly.from_step(write_model(tmp_path / "shut.step", parts))
    result = find_clashes(assembly, config, model_dir=tmp_path)
    assert said(result.set_in) == [("insert", "block", 12.1, None)]


# ---------------------------------------------------------------------------
# A nut, or a hex head, drawn into its trap.
# ---------------------------------------------------------------------------

#: #93's M3 nut, 5.5 across and 2.4 thick, in a pocket 5.4 across: between the two
#: hexes, (5.5^2 - 5.4^2) sqrt(3) / 2 = 0.944 mm^2, 2.4 deep.
PRESSED = (5.5**2 - 5.4**2) * math.sqrt(3) / 2 * 2.4


def test_a_nut_drawn_into_its_trap_is_said_as_check_notes_it(engine):
    config = Config.from_dict({"fasteners": [SCREW, NUT]})
    assembly = Assembly([Part(n, s) for n, s in pocket_parts(af=5.4)])
    report = check(assembly, config, kit="metric-home", engine=engine, clashes=True)
    nut = next(r for r in report.results if r.fastener.name == "nut")
    assert nut.verdict is Verdict.HELD
    assert nut.notes == ("drawn 2.3 mm^3 into its trap: a press fit, or a clash to fix",)
    assert said(report.clashes.found) == [("nut", "block", 2.3, TRAP)]
    assert f"CLASH nut into block  2.3 mm^3  ({TRAP})" in report.terminal_lines()
    assert f"{PRESSED:.1f}" == "2.3"


def test_a_hex_head_drawn_into_its_trap_is_said_too(engine):
    config = Config.from_dict({"fasteners": [HEX_BOLT, HEX_NUT]})
    assembly = Assembly([Part(n, s) for n, s in trapped(pocket=12.8)])
    found = find_clashes(assembly, config, engine=engine).found
    assert said(found) == [("bolt", "plate", 23.7, TRAP)]


def test_a_trapped_nut_drawn_into_another_part_is_a_clash_of_its_own():
    # A floor under the block, 0.3 up into the nut's face, the screw's hole, 3.4
    # across, on through it: the hex less the hole, (26.20 - 9.08) 0.3 = 5.14 mm^3.
    # Its trap is the block, and only the block's line says so.
    floor = Pos(0, 0, -16 - 5 + 0.3) * Box(30, 30, 10) - Cylinder(1.7, 40)
    parts = [*pocket_parts(af=5.4), ("floor", floor)]
    config = Config.from_dict({"fasteners": [SCREW, NUT], "allow": [["block", "floor"]]})
    found = find_clashes(Assembly([Part(n, s) for n, s in parts]), config).found
    assert said(found) == [("nut", "block", 2.3, TRAP), ("nut", "floor", 5.1, None)]
