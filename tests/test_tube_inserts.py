"""A tube pushed into a part is no threaded insert, though it is named one (issue #178).

Printer models name the PTFE tube pushed into a printed part an "insert". Since #84
a part named only ``insert`` is a fixed thread when its solid shows a bore, and a
tube has one: a Bowden tube 4 across and bored 2 was an M2 threaded insert, held,
in the summary's count. Since #158 an insert's overlap with the part it sits in is
no clash, so a tube drawn 0.2 into its hole all round was counted among the
inserts set into their parts, and its clash never listed.

Now an insert is a tube, passed over with a note, where:

- its name says tube, liner or sleeve too (``ptfe``, ``pfte``, ``teflon``,
  ``tube``, ``tubing``, ``liner``, ``bowden``, ``sleeve``), and gives no thread: no
  thread size, and no word that says threaded, beside which a tube word is about
  the part the insert goes into;
- or it is named only as an insert and its solid is more than six times as long as
  it is across. The longest threaded insert in PEM's bulletin of them is 4.8.

Passed over, it is a part like any other, and its overlap with the part it is
pushed into is a clash again. The shells' volumes below are pi (R^2 - r^2) L.
"""

import math

import pytest
from build123d import Box, Compound, Cylinder, Pos, export_step
from click.testing import CliRunner

from fastener_models import hex_nut, socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check, find_clashes
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.detect import INSERT_SLENDER_MAX, LONG_TUBE, NO_THREAD, TUBE, find, read_name
from wrenchroom.detect.geometry import read_shape
from wrenchroom.fasteners import Kind
from wrenchroom.report import Verdict

MM = 25.4


def tube(across=4.0, bore=2.0, length=80.0):
    """A tube along z, its middle at the origin: a printer's PTFE tube is 4 by 2."""
    return Cylinder(across / 2, length) - Cylinder(bore / 2, length + 1)


def cube(hole, side=20.0):
    """A block ``side`` each way with a hole ``hole`` across down through its middle."""
    return Box(side, side, side) - Cylinder(hole / 2, side + 1)


def shell(across, hole, length):
    return math.pi * ((across / 2) ** 2 - (hole / 2) ** 2) * length


def model(*parts):
    return Assembly([Part(name, shape) for name, shape in parts])


# ---------------------------------------------------------------------------
# The name says tube.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "basis"),
    [
        ("PTFE insert", "noun 'insert', word 'ptfe'"),  # the issue's three
        ("PTFE tube insert", "noun 'insert', word 'ptfe', word 'tube'"),
        ("bowden insert", "noun 'insert', word 'bowden'"),
        ("PFTE insert:1", "noun 'insert', word 'pfte'"),  # the Voron Legacy's, misspelt
        ("Teflon_Liner_Insert", "noun 'insert', word 'teflon', word 'liner'"),
        ("PTFE Tubing Insert (2)", "noun 'insert', word 'ptfe', word 'tubing'"),
        ("Bowden-Tube-Inserts", "noun 'inserts', word 'bowden', word 'tube'"),
        ("sleeve_insert", "noun 'insert', word 'sleeve'"),
        ("hotend liner insert", "noun 'insert', word 'liner'"),
        # brass and heat alone don't say threaded: a brass sleeve, a heat break's liner
        ("brass sleeve insert", "noun 'insert', word 'sleeve'"),
        ("heat break PTFE insert", "noun 'insert', word 'ptfe'"),
    ],
)
def test_an_insert_named_as_a_tube_is_one(name, basis):
    hint = read_name(name)
    assert (hint.kind, hint.tube, hint.needs_bore) == (Kind.INSERT, True, False)
    assert (hint.basis, hint.size, hint.not_covered) == (basis, None, None)


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("PTFE tube holder M3 insert", "M3"),  # a thread size: the holder's insert
        ("Bowden clamp #4-40 insert", "#4"),
        ("bowden clamp heat set insert", None),  # a word that says threaded
        ("bowden clamp heat-staked insert", None),
        ("bowden clamp heatset insert", None),
        ("tube clamp threaded insert", None),
        ("threaded sleeve insert", None),
        ("knurled sleeve insert", None),
        ("tapped tube insert", None),
        ("helicoil liner insert", None),
        ("tube thread insert", None),
    ],
)
def test_a_name_that_gives_a_thread_is_a_fixed_thread_whatever_tube_it_names(name, size):
    hint = read_name(name)
    assert (hint.kind, hint.tube, hint.needs_bore) == (Kind.INSERT, False, False)
    assert (hint.size.designation if hint.size else None) == size
    assert "word" not in hint.basis


def test_a_thread_size_the_tables_lack_is_a_thread_all_the_same():
    # M1 is no size the kit checks: not covered, as before, and no tube.
    hint = read_name("M1 PTFE insert")
    assert (hint.kind, hint.tube) == (Kind.INSERT, False)
    assert hint.not_covered is not None


@pytest.mark.parametrize("name", ["insert", "Logo_Insert:1", "boss_insert", "clamp insert"])
def test_an_insert_with_no_tube_word_still_waits_on_its_solid(name):
    hint = read_name(name)
    assert (hint.kind, hint.tube, hint.needs_bore) == (Kind.INSERT, False, True)


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("tube rivnut", Kind.INSERT),  # a fixed thread's own noun
        ("sleeve_well_nut", Kind.INSERT),
        ("bowden_tnut", Kind.INSERT),
        ("sleeve nut", Kind.NUT),
        ("bowden clamp screw", Kind.SCREW),
        ("tube clamp bolt M4x12", Kind.SCREW),
    ],
)
def test_a_tube_word_is_about_the_bare_word_insert_only(name, kind):
    hint = read_name(name)
    assert (hint.kind, hint.tube) == (kind, False)


@pytest.mark.parametrize(
    ("name", "kind", "basis"),
    [
        ("ISO 4762 PTFE insert", Kind.SCREW, "ISO 4762"),
        ("91290A115 PTFE insert", Kind.SCREW, "McMaster 91290A"),
        ("ISO 4032 tube insert", Kind.NUT, "ISO 4032"),
    ],
)
def test_a_standard_or_a_catalogue_number_outranks_the_word_insert_and_its_tube(name, kind, basis):
    # The fastener its standard names, as ever: no insert, so no tube.
    hint = read_name(name)
    assert (hint.kind, hint.tube, hint.needs_bore, hint.basis) == (kind, False, False, basis)


@pytest.mark.parametrize("name", ["PTFE tube", "Bowden Tube:1", "PTFE (1)", "teflon liner"])
def test_a_tube_named_as_nothing_a_fastener_is_stays_nothing(name):
    assert read_name(name) is None


# ---------------------------------------------------------------------------
# Passed over by its name, whatever its solid shows.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "shape",
    [
        lambda: tube(length=12),  # 3 times as long as across: a fixed thread's shape
        lambda: tube(length=86),  # the Voron Legacy's, 21.5 times
        lambda: Cylinder(2, 12),  # no bore at all
        lambda: tube(across=5, bore=3, length=4),  # a heat-set insert's very solid
    ],
)
def test_named_as_a_tube_it_is_passed_over_whatever_its_solid(shape):
    found = find([Part("PTFE insert", shape())])
    assert found.fasteners == ()
    (passed,) = found.passed_over
    assert (passed.name, passed.kind, passed.named) == ("PTFE insert", Kind.INSERT, True)
    assert (passed.tube, passed.motion) == (True, False)
    assert passed.reason == f"noun 'insert', word 'ptfe'; {TUBE}"


def test_the_note_says_how_to_say_it_is_a_thread_after_all():
    assert TUBE == (
        "named as a tube, a liner or a sleeve, which is pushed into its part: not a "
        "fixed thread (a rule with kind: insert says it is one)"
    )


def test_a_rule_that_says_insert_makes_it_one():
    parts = model(("PTFE insert", tube(across=5, bore=3, length=4)), ("block", cube(4.6)))
    rule = {"parts": "PTFE insert", "kind": "insert", "size": "M3"}
    report = check(parts, Config.from_dict({"fasteners": [rule]}))
    (result,) = report.results
    assert (result.fastener.name, result.verdict) == ("PTFE insert", Verdict.HELD)
    assert report.passed_over == ()


def test_a_tube_word_ending_the_name_is_a_part_s_own_noun_already():
    # "insert tube": the noun has an ordinary word after it, and a tube shows no drive.
    found = find([Part("insert tube", tube(length=12))])
    assert found.fasteners == ()
    assert [part.tube for part in found.passed_over] == [True]


# ---------------------------------------------------------------------------
# Passed over by its solid: longer for its width than any fixed thread.
# ---------------------------------------------------------------------------


def test_a_fixed_thread_is_at_most_six_times_as_long_as_across():
    assert INSERT_SLENDER_MAX == 6.0


@pytest.mark.parametrize(
    ("length", "times"),
    [
        (86.0, "21.5"),  # the Voron Legacy's "PFTE insert", read as a bare insert
        (40.0, "10.0"),
        (30.8, "7.7"),  # the shortest PTFE tube in the five public models
        (24.4, "6.1"),  # just past the line
    ],
)
def test_a_bare_insert_longer_than_any_fixed_thread_is_a_tube(length, times):
    found = find([Part("feed_insert", tube(length=length))])
    assert found.fasteners == ()
    (passed,) = found.passed_over
    assert (passed.name, passed.kind, passed.tube) == ("feed_insert", Kind.INSERT, True)
    assert passed.reason == (
        "noun 'insert'; named only as an insert, with no thread size or word such as "
        f"threaded, and its solid is {times} times as long as it is across: a tube, not a "
        "fixed thread, whose makers' longest is under 6 (a rule with kind: insert says "
        "it is one)"
    )
    assert passed.reason == f"noun 'insert'; {LONG_TUBE.format(times=length / 4)}"


@pytest.mark.parametrize("length", [4.0, 12.0, 19.2, 23.6])
def test_a_bare_insert_no_longer_than_a_fixed_thread_is_one_by_its_bore(length):
    # 23.6 on 4 is 5.9 times: inside the line.
    found = find([Part("feed_insert", tube(length=length))])
    assert found.passed_over == ()
    (fastener,) = found.fasteners
    assert (fastener.kind, fastener.size.designation) == (Kind.INSERT, "M2")
    assert fastener.basis == "noun 'insert'; solid: M2 by its bore alone"


#: PEM's SI bulletin, threaded inserts for plastics, read 2026-10-11: the type, its
#: thread, its diameter, its longest length and its thread's minor diameter, in the
#: sheet's own units. STKB is thru-threaded and knurled, for moulding in, IBB blind,
#: ISB heat-staked.
PEM_LONGEST = [
    ("STKB", "2-56", 0.156 * MM, 0.750 * MM, 0.067 * MM, 4.81),
    ("STKB", "4-40", 0.188 * MM, 0.750 * MM, 0.086 * MM, 3.99),
    ("STKB", "6-32", 0.219 * MM, 0.750 * MM, 0.105 * MM, 3.42),
    ("STKB", "M3", 4.74, 18.0, 2.47, 3.80),
    ("STKB", "M4", 6.35, 18.0, 3.25, 2.83),
    ("STKB", "M5", 7.13, 18.0, 4.15, 2.52),
    ("IBB", "10-24", 0.281 * MM, 0.716 * MM, 0.146 * MM, 2.55),
    ("IBB", "M3", 4.78, 11.13, 2.47, 2.33),
    ("ISB", "M3", 4.62, 5.74, 2.47, 1.24),
    ("ISB", "M6", 8.58, 12.7, 4.94, 1.48),
]


@pytest.mark.parametrize(("kind", "thread", "across", "long", "bore", "times"), PEM_LONGEST)
def test_a_maker_s_longest_insert_is_still_a_fixed_thread(kind, thread, across, long, bore, times):
    assert round(long / across, 2) == times
    solid = tube(across=across, bore=bore, length=long)
    assert read_shape(solid, Kind.INSERT).slender == pytest.approx(long / across, abs=1e-6)
    found = find([Part("insert", solid)])
    assert found.passed_over == (), f"{kind} {thread}"
    assert [fastener.kind for fastener in found.fasteners] == [Kind.INSERT]


def test_the_line_stands_between_the_makers_longest_and_the_models_tubes():
    longest = max(long / across for _, _, across, long, _, _ in PEM_LONGEST)
    assert round(longest, 2) == 4.81  # 0.750 / 0.156
    assert longest * 1.2 < INSERT_SLENDER_MAX < 7.7 / 1.2  # a fifth to spare each way


@pytest.mark.parametrize(
    "name",
    ["M2 insert", "threaded insert", "heatset_insert", "brass_insert", "panel_rivnut"],
)
def test_a_name_that_says_thread_is_not_second_guessed_by_its_length(name):
    # 4 across and 40 long, ten times: the name gave the thread, or the noun did.
    found = find([Part(name, tube(length=40))])
    assert found.passed_over == ()
    assert [fastener.kind for fastener in found.fasteners] == [Kind.INSERT]


def test_a_bare_insert_with_no_bore_is_an_inlay_as_before_however_long():
    found = find([Part("feed_insert", Cylinder(2, 40))])
    (passed,) = found.passed_over
    assert passed.reason == f"noun 'insert'; {NO_THREAD}"
    assert passed.tube is False


def test_its_width_is_its_widest_and_its_length_along_its_bore():
    # A flange 8 across on a body 4 across and 30 long: 30 / 8, where the body alone
    # is 7.5 times.
    flanged = tube(length=30) + Pos(0, 0, 14.5) * (Cylinder(4, 1) - Cylinder(1, 2))
    assert read_shape(flanged, Kind.INSERT).slender == pytest.approx(3.75, abs=1e-6)
    assert read_shape(tube(length=30), Kind.INSERT).slender == pytest.approx(7.5, abs=1e-6)


def test_a_nut_s_reading_carries_it_and_a_screw_s_does_not():
    # An M6 nut 10 across flats and 5.2 tall: 5.2 over its corners, 10 / cos 30.
    across_corners = 10 / math.cos(math.radians(30))
    nut = read_shape(hex_nut("M6"), Kind.NUT)
    assert nut.slender == pytest.approx(5.2 / across_corners, abs=0.01)
    assert read_shape(socket_screw("M6"), Kind.SCREW).slender is None
    assert read_shape(Box(10, 10, 10), Kind.INSERT).slender is None  # no axis at all


# ---------------------------------------------------------------------------
# The issue's model: three tubes and a heat-set insert.
# ---------------------------------------------------------------------------

TUBES = ("PTFE insert", "PTFE tube insert", "bowden insert")


def issue_parts():
    """Each tube 4 by 2 and 80 long through a 20 mm cube whose hole is 3.6 across,
    and an M3 heat-set insert, 4.6 across and 5.7 long, in a hole 4.0 across."""
    parts = []
    for index, name in enumerate(TUBES):
        at = Pos(index * 100, 0, 0)
        parts += [(f"block {index}", at * cube(3.6)), (name, at * tube())]
    seat = Pos(900, 0, 10 - 2.85)
    block = Pos(900, 0, 0) * Box(20, 20, 20) - seat * Cylinder(2.0, 5.7)
    insert = seat * (Cylinder(2.3, 5.7) - Cylinder(1.25, 6))
    return [*parts, ("block 9", block), ("M3 heat-set insert", insert)]


def test_the_tubes_are_passed_over_and_the_heat_set_insert_is_held():
    report = check(model(*issue_parts()), Config())
    assert [(r.fastener.name, r.verdict) for r in report.results] == [
        ("M3 heat-set insert", Verdict.HELD)
    ]
    assert [(part.name, part.tube) for part in report.passed_over] == [
        (name, True) for name in TUBES
    ]
    lines = report.terminal_lines()
    assert lines[0] == "1 fasteners: 0 turn, 1 held, 0 blocked, 0 stuck, 0 not covered"
    assert lines[1].split() == ["M3", "insert", "-", "x1", "all", "pass", "(holds", "itself)"]
    assert f"NOTE passed over PTFE insert: noun 'insert', word 'ptfe'; {TUBE}" in lines
    assert (
        "3 parts named as inserts that are tubes or liners, not fixed threads (passed over)"
        in lines[-1]
    )
    assert "no drive or bore" not in lines[-1]  # they have bores: not that sentence
    assert "shaped like" not in lines[-1]  # and are named: not that one either
    assert report.exit_code == 0


def test_one_tube_is_said_in_the_singular_beside_the_other_kinds():
    parts = [
        ("PTFE insert", tube(length=12)),
        ("Logo_Insert", Pos(50, 0, 0) * Box(30, 12, 2)),
        ("lead screw nut", Pos(100, 0, 0) * hex_nut("M8")),
    ]
    last = check(model(*parts), Config()).terminal_lines()[-1]
    assert (
        "1 part named like a fastener, with no drive or bore in the solid (passed over); "
        "1 part named for a leadscrew or a ball screw, which no tool turns (passed over); "
        "1 part named as an insert that is a tube or a liner, not a fixed thread (passed over)"
    ) in last
    assert "shaped like" not in last  # each is counted once, under its own words


def test_the_json_and_the_markdown_list_them_with_why():
    report = check(model(*issue_parts()), Config())
    document = report.to_json_dict()
    assert document["passed_over"][0] == {
        "name": "PTFE insert",
        "kind": "insert",
        "reason": f"noun 'insert', word 'ptfe'; {TUBE}",
        "named": True,
    }
    assert [entry["name"] for entry in document["fasteners"]] == ["M3 heat-set insert"]
    page = report.markdown()
    assert "`bowden insert`: noun 'insert', word 'bowden'; named as a tube" in page


# ---------------------------------------------------------------------------
# Its overlap with the part it is pushed into is a clash again.
# ---------------------------------------------------------------------------


def said(found):
    return [(c.first, c.second, round(c.volume, 1), c.hint) for c in found]


def test_a_tube_drawn_into_its_hole_is_a_clash_not_an_insert_set_in(engine):
    # 0.2 into the hole all round over the cube's 20: pi (2^2 - 1.8^2) 20 = 47.75.
    # The heat-set insert's skin is pi (2.3^2 - 2.0^2) 5.7 = 23.10, 0.24 of it: set in.
    result = find_clashes(model(*issue_parts()), Config(), engine=engine)
    assert said(result.found) == [
        ("PTFE insert", "block 0", 47.8, None),
        ("PTFE tube insert", "block 1", 47.8, None),
        ("bowden insert", "block 2", 47.8, None),
    ]
    assert said(result.set_in) == [("M3 heat-set insert", "block 9", 23.1, None)]
    assert f"{shell(4.0, 3.6, 20):.2f}" == "47.75"
    assert f"{shell(4.6, 4.0, 5.7):.2f}" == "23.10"
    assert result.exit_code == 1
    assert result.lines(with_inserts=True) == [
        "3 clashes (overlap over 0.05 mm^3)",
        "CLASH PTFE insert into block 0  47.8 mm^3",
        "CLASH PTFE tube insert into block 1  47.8 mm^3",
        "CLASH bowden insert into block 2  47.8 mm^3",
        "NOTE 1 insert set into its part, no clash",
        "SET M3 heat-set insert into block 9  23.1 mm^3",
    ]


def test_a_long_tube_named_only_an_insert_is_a_clash_too():
    result = find_clashes(model(("feed_insert", tube()), ("block", cube(3.6))), Config())
    assert said(result.found) == [("feed_insert", "block", 47.8, None)]
    assert result.set_in == ()


def test_drawn_thin_it_is_hinted_a_press_fit():
    # A hole 3.9 across: a skin 0.05 thick, pi (2^2 - 1.95^2) 20 = 12.41 mm^3.
    result = find_clashes(model(("PTFE insert", tube()), ("block", cube(3.9))), Config())
    hint = "a press fit, 0.05 deep? allow it in the sidecar"
    assert said(result.found) == [("PTFE insert", "block", 12.4, hint)]
    assert f"{shell(4.0, 3.9, 20):.2f}" == "12.41"


def test_drawn_to_its_hole_it_is_no_clash():
    result = find_clashes(model(("PTFE insert", tube()), ("block", cube(4.0))), Config())
    assert (result.found, result.set_in) == ((), ())


def test_allowed_it_is_no_clash_as_any_press_fit_is():
    config = Config.from_dict({"allow": [["PTFE insert", "block"]]})
    result = find_clashes(model(("PTFE insert", tube()), ("block", cube(3.6))), config)
    assert (result.found, result.set_in, result.exit_code) == ((), (), 0)


def test_a_rule_that_says_insert_sets_it_in_again():
    # 0.19 of its own cylinder: 1 - 0.9^2. The rule is the owner's word for it.
    rule = {"parts": "PTFE insert", "kind": "insert", "size": "M2"}
    config = Config.from_dict({"fasteners": [rule]})
    result = find_clashes(model(("PTFE insert", tube()), ("block", cube(3.6))), config)
    assert result.found == ()
    assert said(result.set_in) == [("PTFE insert", "block", 47.8, None)]


def test_check_with_clashes_fails_on_the_tube_and_holds_the_insert():
    report = check(model(*issue_parts()), Config(), clashes=True)
    assert report.exit_code == 1  # it was 0: three clashes hidden as inserts set in
    lines = report.terminal_lines()
    assert "3 clashes (overlap over 0.05 mm^3)" in lines
    assert "CLASH PTFE insert into block 0  47.8 mm^3" in lines
    assert [r.fastener.name for r in report.results] == ["M3 heat-set insert"]


# ---------------------------------------------------------------------------
# From a STEP file, by the commands.
# ---------------------------------------------------------------------------


def write_model(path, parts):
    shapes = []
    for name, shape in parts:
        shape.label = name
        shapes.append(shape)
    export_step(Compound(children=shapes), path)
    return path


def test_the_commands_tell_the_issue_s_model_right(tmp_path):
    step = write_model(tmp_path / "tube.step", issue_parts())
    checked = CliRunner().invoke(main, ["check", str(step)])
    assert checked.exit_code == 0
    assert checked.output.splitlines()[:2] == [
        "1 fasteners: 0 turn, 1 held, 0 blocked, 0 stuck, 0 not covered",
        "  M3 insert                -              x1    all pass (holds itself)",
    ]
    assert "M2 insert" not in checked.output  # it was "M2 insert x3"
    listed = CliRunner().invoke(main, ["clashes", str(step), "--with-inserts"])
    assert listed.exit_code == 1
    assert listed.output.splitlines() == [
        "3 clashes (overlap over 0.05 mm^3)",
        "CLASH PTFE insert into block 0  47.8 mm^3",
        "CLASH PTFE tube insert into block 1  47.8 mm^3",
        "CLASH bowden insert into block 2  47.8 mm^3",
        "NOTE 1 insert set into its part, no clash",
        "SET M3 heat-set insert into block 9  23.1 mm^3",
    ]


def test_detect_writes_it_commented_out_as_any_part_passed_over(tmp_path):
    step = write_model(tmp_path / "tube.step", issue_parts())
    text = CliRunner().invoke(main, ["detect", str(step)]).stdout
    assert "# PTFE insert: passed over: noun 'insert', word 'ptfe'; named as a tube" in text
    assert "  # - parts: PTFE insert\n  #   kind: insert\n" in text
    assert "- parts: M3 heat-set insert\n" in text  # the real one, a rule as it stands
