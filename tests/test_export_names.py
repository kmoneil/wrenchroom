"""A real CAD export's names and fixed threads (issue #84).

Four faults from one Fusion 360 export: ``Hexnut`` in one word was no nut, and
nothing said so; ``Logo_Insert``, a printed logo's inlay, was a fixed thread;
an M3 T-nut bored 2.8 was sized #4 by its bore, though its screw is M3; and the
screw into it, blocked, was said to fail because its partner "does not turn",
which a fixed thread never does. And a part with no name came out named
``=>[0:1:1:32]``, a label OCCT makes up.
"""

import pytest
from build123d import Box, Compound, Cylinder, Pos, export_step
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFDoc import XCAFDoc_DocumentTool

from fastener_models import hex_nut, socket_screw
from fixture_models import bolt_with_slotted_nut
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.detect import NO_THREAD, find, read_name
from wrenchroom.fasteners import Head, Kind
from wrenchroom.report import Verdict

# ---------------------------------------------------------------------------
# A describing word run into its noun.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind", "head"),
    [
        ("M3 Hexnut:1", Kind.NUT, None),
        ("hexnuts", Kind.NUT, None),
        ("HexNut M6", Kind.NUT, None),  # camelCase was always two words
        ("jamnut M8", Kind.NUT, None),
        ("flangenut", Kind.NUT, None),
        ("nylocnut", Kind.NUT, None),
        ("M6 Hexbolt", Kind.SCREW, Head.HEX),
        ("panscrew", Kind.SCREW, None),
        ("buttonscrew M4", Kind.SCREW, Head.BUTTON),
        ("weldnut", Kind.INSERT, None),  # "weld nut": a fixed thread
        ("cagenut M6", Kind.INSERT, None),
    ],
)
def test_a_word_run_into_its_noun_reads_as_the_two_words(name, kind, head):
    found = read_name(name)
    assert (found.kind, found.head, found.not_covered) == (kind, head, None)


@pytest.mark.parametrize(
    ("name", "basis"),
    [("locknut", "noun 'locknut'"), ("capscrew M6", "noun 'capscrew', M6")],
)
def test_a_noun_of_its_own_keeps_its_reading(name, basis):
    assert read_name(name).basis == basis


def test_a_hand_turned_noun_stays_one():
    found = read_name("wingnut")
    assert (found.kind.value, found.by_hand, found.not_covered) == ("nut", True, None)


@pytest.mark.parametrize("name", ["peanut", "walnut_trim", "coconut", "corkscrew", "thunderbolt"])
def test_only_a_word_that_describes_a_fastener_is_split_off(name):
    assert read_name(name) is None


def test_a_one_word_nut_is_found_and_checked():
    plate = Pos(0, 0, -5) * Box(100, 100, 10)
    stud = Pos(0, 0, 2.5) * Cylinder(3, 25)
    model = Assembly([Part("plate", plate), Part("stud", stud), Part("M6 Hexnut:1", hex_nut("M6"))])
    (result,) = check(model, Config()).results
    assert (result.fastener.name, result.fastener.kind) == ("M6 Hexnut:1", Kind.NUT)
    assert (result.verdict, result.tool) == (Verdict.TURNS, "spanner-10")


# ---------------------------------------------------------------------------
# "Insert" alone may be an inlay.
# ---------------------------------------------------------------------------


def _plaque():
    """A logo's inlay: a thin plate, no bore."""
    return Box(30, 12, 2)


def _bored():
    """A fixed thread's body: a block with an M4 bore."""
    return Box(8, 8, 6) - Cylinder(2.0, 10)


@pytest.mark.parametrize(
    ("name", "shape", "taken"),
    [
        ("Logo_Insert:1", _plaque, False),  # the issue's: nothing says thread
        ("badge_insert", _plaque, False),
        ("Logo_Insert:1", _bored, True),  # a bore is a thread's
        ("M3 insert", _plaque, True),  # a thread size says it
        ("heatset_insert", _plaque, True),  # so does a word
        ("threaded insert", _plaque, True),
        ("brass_insert", _plaque, True),
        ("panel_rivnut", _plaque, True),  # a fixed thread's own noun
    ],
)
def test_a_bare_insert_is_a_fixed_thread_only_with_something_to_say_so(name, shape, taken):
    found = find([Part(name, shape())])
    assert bool(found.fasteners) is taken
    if not taken:
        (passed,) = found.passed_over
        assert (passed.name, passed.kind) == (name, Kind.INSERT)
        assert passed.reason == f"noun 'insert'; {NO_THREAD}"


def test_a_bare_insert_ending_in_a_part_noun_is_not_listed():
    # "insert_plate" is a plate: as for a nut_plate, nothing is said (issue #75).
    assert find([Part("logo_insert_plate", _plaque())]).passed_over == ()


def test_a_knurled_insert_is_set_not_turned_by_hand():
    # "knurled" makes a nut a thumb nut; an insert is never turned at all.
    found = read_name("knurled insert M4")
    assert (found.kind, found.not_covered) == (Kind.INSERT, None)


# ---------------------------------------------------------------------------
# A fixed thread's bore alone is a guess its screw outranks.
# ---------------------------------------------------------------------------


def _screw_into_tnut(size, bore, tnut_name="MB T-Nut:1"):
    """A socket screw down through a plate into a T-nut bored ``bore`` below it."""
    plate = Pos(0, 0, -5) * Box(100, 100, 10) - Cylinder(4, 12)
    tnut = Pos(0, 0, -12) * (Box(20, 10, 4) - Cylinder(bore / 2, 5))
    return Assembly(
        [Part("plate", plate), Part(f"{size} screw", socket_screw(size)), Part(tnut_name, tnut)]
    )


@pytest.mark.parametrize(
    ("size", "bore", "alone"),
    [
        ("M3", 2.8, "#4"),  # the issue's: 2.8 is #4's 2.845 within 0.05
        ("M5", 4.2, "#8"),  # M5's tap drill on #8's 4.166
        ("M6", 5.0, "M5"),  # M6's tap drill is M5's diameter
    ],
)
def test_a_tnut_takes_its_screws_size_over_its_bore(size, bore, alone):
    report = check(_screw_into_tnut(size, bore), Config())
    by_name = {r.fastener.name: r for r in report.results}
    tnut = by_name["MB T-Nut:1"]
    assert (tnut.verdict, tnut.fastener.kind) == (Verdict.HELD, Kind.INSERT)
    assert tnut.fastener.size.designation == size
    note = f"size {size} from its screw, {size} screw (its bore alone said {alone})"
    assert note in tnut.notes
    assert tnut.fastener.basis.endswith(f"solid: {alone} by its bore alone; {note}")
    assert by_name[f"{size} screw"].verdict is Verdict.TURNS


def test_a_tnut_whose_name_gives_its_size_keeps_it():
    report = check(_screw_into_tnut("M5", 4.2, tnut_name="M5 T-Nut"), Config())
    (tnut,) = [r for r in report.results if r.fastener.kind is Kind.INSERT]
    assert tnut.fastener.size.designation == "M5"
    assert tnut.notes == ()


# ---------------------------------------------------------------------------
# What a fastener that only holds is told when its partner holds itself.
# ---------------------------------------------------------------------------


def test_a_screw_into_a_fixed_thread_must_turn_and_is_told_so(engine):
    rules = [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"},
        {"parts": "nut", "kind": "insert", "size": "M8"},
    ]
    report = check(
        bolt_with_slotted_nut(head_boxed=True),
        Config.from_dict({"fasteners": rules}),
        engine=engine,
    )
    (bolt,) = [r for r in report.results if r.fastener.name == "bolt"]
    assert bolt.verdict is Verdict.BLOCKED
    assert bolt.reason.startswith(
        "only holds, and it screws into a fixed thread (nut), so it must turn"
    )


def test_a_nut_on_a_carriage_bolt_must_turn_and_is_told_so(engine):
    # The nut's slot lets a ring hold it, never turn it; a carriage bolt holds itself.
    rules = [
        {"parts": "bolt", "kind": "screw", "head": "carriage", "size": "M8"},
        {"parts": "nut", "kind": "nut", "size": "M8"},
    ]
    report = check(bolt_with_slotted_nut(), Config.from_dict({"fasteners": rules}), engine=engine)
    by_name = {r.fastener.name: r for r in report.results}
    assert by_name["bolt"].verdict is Verdict.HELD
    assert by_name["nut"].verdict is Verdict.BLOCKED
    assert by_name["nut"].reason.startswith(
        "only holds, and its bolt (bolt) holds itself, so it must turn"
    )


# ---------------------------------------------------------------------------
# Names OCCT makes up are no names.
# ---------------------------------------------------------------------------


def _unnamed_components(path):
    """A STEP as OCCT writes an assembly whose components have no names of their own.

    OCCT writes each component's instance as ``=>[0:1:1:3]``, its product as
    ``SOLID``, and the assembly between as ``ASSEMBLY``; only the top is named.
    """
    doc = TDocStd_Document(TCollection_ExtendedString("XCAF"))
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    body = Compound([Box(10, 10, 10), Pos(30, 0, 0) * Box(5, 5, 5)])
    label = tool.AddShape(body.wrapped, True)
    TDataStd_Name.Set_s(label, TCollection_ExtendedString("carriage"))
    writer = STEPCAFControl_Writer()
    writer.Transfer(doc, STEPControl_AsIs)
    writer.Write(str(path))
    text = path.read_text()
    assert "'=>[0:1:1:3]'" in text  # a vacuity guard: OCCT wrote its placeholders
    assert "PRODUCT('SOLID'" in text
    return path


def test_a_part_with_no_name_takes_its_assemblys(tmp_path):
    names = Assembly.from_step(_unnamed_components(tmp_path / "unnamed.step")).names
    assert names == ("carriage", "carriage#2")


@pytest.mark.parametrize("name", ["Solid", "solid_bracket", "ASSEMBLY_JIG", "=>[x]"])
def test_a_name_only_like_a_placeholder_is_a_name(tmp_path, name):
    box = Box(5, 5, 5)
    box.label = name
    top = Compound(children=[box])
    top.label = "top"
    path = tmp_path / "named.step"
    export_step(top, path)
    assert Assembly.from_step(path).names == (name,)
