"""Screws named only by thread and length, and unnamed parts that look like fasteners (#95).

CAD libraries and suppliers name a screw ``M3x16``, ``M3-0.5x16`` or ``1/4-20x1``,
and a real model mixes those in with fully named ones. Such a name is a screw
candidate: a stud, a rod or an insert is named so as readily, so it is taken on a
drive in its solid and passed over otherwise, saying so. A bare size (``M3``) says
nothing, and a name with a word of its own is about that word.

A part named nothing a fastener is (``Part7``) isn't checked, as detection reads
named parts only; but one whose solid plainly looks like a fastener is listed as
passed over, so a model of unnamed screws doesn't pass without a word.
"""

import json

import pytest
import yaml
from build123d import Box, Compound, Cone, Cylinder, Pos, export_step
from click.testing import CliRunner

from fastener_models import (
    MINOR,
    button_screw,
    flat_screw,
    hex_bolt,
    hex_nut,
    hex_prism,
    pan_phillips,
    slotted_screw,
    socket_screw,
)
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.detect import NO_DRIVE, NOT_NAMED, find, geometry, read_name
from wrenchroom.detect.geometry import looks_like
from wrenchroom.fasteners import Head, Kind, PassedOver
from wrenchroom.report import Report, Verdict

S, N = Kind.SCREW, Kind.NUT
TIMES = chr(0xD7)


# ---------------------------------------------------------------------------
# Names.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "size", "length", "said"),
    [
        ("M3x16", "M3", 16, "M3x16"),
        ("M3 x 16", "M3", 16, "M3 x 16"),
        ("M3X16", "M3", 16, "M3X16"),
        (f"M3{TIMES}16", "M3", 16, "M3x16"),
        ("M3*16", "M3", 16, "M3x16"),
        ("M3x16mm", "M3", 16, "M3x16mm"),
        ("M3-0.5x16", "M3", 16, "M3-0.5x16"),
        ("M3-0.5 x 16", "M3", 16, "M3-0.5 x 16"),
        ("M3x0.5x16", "M3", 16, "M3x0.5x16"),
        ("M6-1x20", "M6", 20, "M6-1x20"),
        ("M8-1.25 x 20", "M8", 20, "M8-1.25 x 20"),
        ("M2.5x6", "M2.5", 6, "M2.5x6"),
        ("1/4-20x1", "1/4", 25.4, "1/4-20x1"),
        ("#4-40 x 1/2", "#4", 12.7, "#4-40 x 1/2"),
        ('#10-32 x 3/8"', "#10", 9.525, '#10-32 x 3/8"'),
        # labels and instance markers round it change nothing
        ("M3x50:1", "M3", 50, "M3x50"),
        ("M3x16 v1", "M3", 16, "M3x16"),
        ("M3x16 (1) (1) (2):1", "M3", 16, "M3x16"),
        ("M3x16_2", "M3", 16, "M3x16"),
        ("M3x16 A2", "M3", 16, "M3x16"),
    ],
)
def test_a_thread_and_length_alone_is_a_screw_candidate(name, size, length, said):
    found = read_name(name)
    assert found is not None, name
    assert (found.kind, found.head, found.needs_drive) == (S, None, True)
    assert found.size.designation == size
    assert found.length_mm == pytest.approx(length)
    assert found.basis == f"thread and length {said}"
    assert found.not_covered is None


@pytest.mark.parametrize(
    "name",
    [
        "M3",  # a nut, an insert, a screw: a size alone says none of them
        "M3 v1",
        "M3x0.5",  # a pitch is no length
        "M6x1",
        "M10x1.25",
        "M3-0.5",
        "#10-32",
        "1/4x1",  # no pitch, no #: not an inch size at all
        "spacer M4x10",  # a word of its own: the name is about it
        "M3x16 standoff",
        "M6x20 plate",
        "M3x5x4",  # an insert's sizes: 5 is no M3's pitch
        "M3-2x10",  # nor 2
        "M3-16",
        "M3 Washer 7x0.5",
        "3mmx20mm_Shaft",
    ],
)
def test_a_bare_size_or_a_word_of_its_own_is_not(name):
    assert read_name(name) is None


@pytest.mark.parametrize(
    ("name", "head"),
    [
        ("M3x16 button", Head.BUTTON),
        ("socket M3x16", Head.SOCKET),
        ("M3x16 Phillips", Head.PHILLIPS),
        ("M3x16 hex", Head.HEX),
        ("M3x16 countersunk", Head.FLAT),
    ],
)
def test_a_head_word_beside_it_says_the_head(name, head):
    found = read_name(name)
    assert (found.kind, found.head, found.needs_drive) == (S, head, True)


def test_a_set_or_thumb_word_beside_it_says_so():
    assert (read_name("set M3x4").head, read_name("set M3x4").by_hand) == (Head.SET, False)
    assert (read_name("M3x16 thumb").head, read_name("M3x16 thumb").by_hand) == (None, True)


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("M30x100", "M30 is outside the sizes the tables hold"),
        ("#14-20x1", "#14 is outside the sizes the tables hold"),
    ],
)
def test_one_the_kit_cannot_check_still_says_why(name, reason):
    assert reason in read_name(name).not_covered


@pytest.mark.parametrize(
    ("name", "size", "length"),
    [
        ("bolt M3-0.5x16", "M3", 16),  # the dash pitch, after a noun as well
        ("SHCS M6-1 x 20", "M6", 20),
        ("bolt M6x1x20", "M6", 20),  # a real pitch between: the length after it
        ("insert M3x5x4", "M3", None),  # no pitch between: no screw's length
        ("bolt M3-2x10", "M3", None),
    ],
)
def test_a_pitch_is_read_after_a_dash_and_must_be_one(name, size, length):
    found = read_name(name)
    assert found.size.designation == size
    assert found.length_mm == length
    assert not found.needs_drive


def test_the_name_with_a_noun_is_read_as_before():
    found = read_name("M3x16 SHCS")
    assert (found.kind, found.head, found.needs_drive) == (S, Head.SOCKET, False)
    assert found.basis == "noun 'shcs', M3x16"


# ---------------------------------------------------------------------------
# Detection: taken on a drive, passed over without one.
# ---------------------------------------------------------------------------


def test_a_socket_screw_named_by_its_thread_is_taken_at_medium_confidence():
    (screw,) = find([Part("M3x16:1", socket_screw("M3", length=16))]).fasteners
    assert (screw.kind, screw.head, screw.size.designation) == (S, Head.SOCKET, "M3")
    assert screw.length_mm == 16
    assert screw.drive_af == pytest.approx(2.5)
    assert screw.basis.startswith("thread and length M3x16; solid: socket")
    assert screw.confidence == "medium"  # the name says only a thread


@pytest.mark.parametrize(
    ("name", "shape", "head"),
    [
        ("M8x25", lambda: hex_bolt("M8"), Head.HEX),
        ("M4x12", pan_phillips, Head.PHILLIPS),
        ("M5x16", lambda: button_screw("M5"), Head.BUTTON),
        ("1/4-20x1", lambda: socket_screw("1/4", length=25.4), Head.SOCKET),
    ],
)
def test_any_drive_a_tool_fits_takes_it(name, shape, head):
    (screw,) = find([Part(name, shape())]).fasteners
    assert screw.head is head


@pytest.mark.parametrize(
    "shape",
    [
        lambda: Cylinder(4, 100),  # a stud, a threaded rod
        lambda: Cylinder(2.5, 4) - Cylinder(1.6, 5),  # an insert, bored
        slotted_screw,  # a slot shows on too much else
        lambda: socket_screw("M3", pocket=False),  # a head with no drive drawn
    ],
)
def test_no_drive_is_passed_over_saying_so(shape):
    found = find([Part("M3x16", shape())])
    assert found.fasteners == ()
    assert found.passed_over == (PassedOver("M3x16", S, f"thread and length M3x16; {NO_DRIVE}"),)


def test_a_size_only_name_on_a_part_noun_stays_quiet():
    found = find([Part("M6x20 plate", Box(40, 40, 6) - Cylinder(3, 10))])
    assert found == type(found)((), ())


# ---------------------------------------------------------------------------
# Look-alikes: a solid that plainly is a fastener, under a name that says nothing.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("shape", "kind", "what"),
    [
        (lambda: socket_screw("M3", length=16), S, "M3 screw, a 2.5 hex socket"),
        (lambda: socket_screw("M8"), S, "M8 screw, a 6 hex socket"),
        (lambda: button_screw("M5"), S, "M5 screw, a 3 hex socket"),
        (flat_screw, S, "M6 screw, a 4 hex socket"),
        (lambda: socket_screw("1/4", length=25.4), S, "1/4 screw, a 4.76 hex socket"),
        (pan_phillips, S, "M4 screw, a cross in its head"),
        (lambda: hex_nut("M3"), N, "M3 nut, 5.5 across flats"),
        (lambda: hex_nut("M8"), N, "M8 nut, 13 across flats"),
        # a nut drawn at its minor diameter, and a nyloc's height (ISO 7040 M3: 4)
        (lambda: hex_prism(5.5, 2.4) - Cylinder(MINOR["M3"] / 2, 9), N, "M3 nut, 5.5 across flats"),
        (lambda: hex_prism(5.5, 4.0) - Cylinder(1.5, 10), N, "M3 nut, 5.5 across flats"),
        # drawn in its standard's band (ISO 4032 M8: 12.73 to 13)
        (lambda: hex_prism(12.8, 6.8) - Cylinder(4, 20), N, "M8 nut, 12.8 across flats"),
        # bored with clearance, and big: an M20's 30, 34.6 across corners
        (lambda: hex_prism(5.5, 2.4) - Cylinder(1.65, 10), N, "M3 nut, 5.5 across flats"),
        (lambda: hex_nut("M20"), N, "M20 nut, 30 across flats"),
    ],
)
def test_a_solid_that_plainly_is_a_fastener_looks_like_one(shape, kind, what):
    assert looks_like(shape()) == (kind, what)


@pytest.mark.parametrize(
    "shape",
    [
        lambda: hex_bolt("M8"),  # a hex over a shank: fittings and collets too
        slotted_screw,
        lambda: socket_screw("M3", pocket=False),  # no drive
        lambda: Cylinder(1.5, 6) - hex_prism(1.5, 1.5, 1.5),  # a set screw: no head (#96)
        lambda: socket_screw("M3", shank=MINOR["M3"]),  # 2.39 snaps to nothing
        # a socket its shank's key doesn't go into: an M3 shank, a 4 mm pocket
        lambda: socket_screw("M3") - hex_prism(4.0, 1.5, 1.5),
        lambda: hex_prism(5.5, 10) - Cylinder(1.5, 20),  # an M3 hex standoff, 10 long
        lambda: hex_prism(10, 6) - Cylinder(2, 20),  # a collet: a 10 hex, a 4 mm bore
        lambda: hex_prism(22.5, 8) - Cylinder(5, 30),  # no spanner's size
        lambda: Cylinder(10, 3) - Cylinder(3.2, 5),  # a washer
        lambda: Cylinder(4, 100),  # a rod
        lambda: Box(40, 40, 10) - Cylinder(3, 20),  # a plate with a hole
        lambda: Box(10, 10, 10),  # nothing round at all
        # a socket in a collar barely wider than its shank, its tip chamfered so the
        # collar's end is the wide one: no head
        lambda: (
            Pos(0, 0, 1.5) * Cylinder(1.8, 3)
            + Pos(0, 0, -7.75) * Cylinder(1.5, 15.5)
            + Pos(0, 0, -15.75) * Cone(1.0, 1.5, 0.5)
            - hex_prism(2.5, 1.5, 1.5)
        ),
        # a socket screw's outline, 50 across: no fastener the tables hold
        lambda: (
            Pos(0, 0, 3) * Cylinder(25, 6)
            + Pos(0, 0, -10) * Cylinder(1.5, 20)
            - hex_prism(2.5, 2.01, 4)
        ),
        # a spool, a flange at each end, a socket in one: wide at both ends, no head
        lambda: (
            Cylinder(1.5, 10)
            + Pos(0, 0, -4.25) * Cylinder(5, 1.5)
            + Pos(0, 0, 4.25) * Cylinder(5, 1.5)
            - hex_prism(2.5, 1.51, 3.5)
        ),
    ],
)
def test_nothing_else_looks_like_one(shape):
    assert looks_like(shape()) is None


def test_a_part_with_many_faces_is_not_read(monkeypatch):
    screw = socket_screw("M3")
    assert looks_like(screw) is not None
    monkeypatch.setattr(geometry, "_FASTENER_FACES", len(screw.faces()) - 1)
    assert looks_like(screw) is None


def test_an_unnamed_look_alike_is_passed_over_saying_what_it_looks_like():
    found = find(
        [
            Part("Part7", socket_screw("M3", length=16)),
            Part("Body12", Pos(50, 0, 0) * hex_nut("M3")),
            Part("bracket", Pos(-50, 0, 0) * (Box(40, 40, 10) - Cylinder(3, 20))),
        ]
    )
    assert found.fasteners == ()
    assert found.passed_over == (
        PassedOver("Part7", S, f"{NOT_NAMED}: M3 screw, a 2.5 hex socket", named=False),
        PassedOver("Body12", N, f"{NOT_NAMED}: M3 nut, 5.5 across flats", named=False),
    )
    assert NOT_NAMED == "not named as a fastener, but its solid looks like one"


# ---------------------------------------------------------------------------
# The check, the reports and detect.
# ---------------------------------------------------------------------------


def plate(x):
    return Pos(x, 0, -5) * Box(30, 30, 10) - Pos(x, 0, 0) * Cylinder(1.5, 30)


def model():
    """The issue's eight names, each an ISO 4762 M3x16 in its own plate, 100 apart."""
    names = [
        "M3x16",
        "M3 x 16",
        "M3-0.5x16",
        "M3x0.5x16",
        "ISO 4762 M3x16",
        "DIN 912 M3x16",
        "91292A115",
        "Part7",
    ]
    parts = []
    for i, name in enumerate(names):
        parts.append(Part(f"plate {i}", plate(100 * i)))
        parts.append(Part(name, Pos(100 * i, 0, 0) * socket_screw("M3", length=16)))
    return Assembly(parts)


@pytest.fixture(scope="module")
def report():
    return check(model(), kit="full")


def test_every_named_screw_turns_and_the_unnamed_one_is_said(report):
    turns = {r.fastener.name: (r.verdict, r.tool) for r in report.results}
    named = ("M3x16", "M3 x 16", "M3-0.5x16", "M3x0.5x16", "ISO 4762 M3x16", "DIN 912 M3x16")
    assert turns == dict.fromkeys((*named, "91292A115"), (Verdict.TURNS, "hex-key-2.5"))
    assert [(p.name, p.named) for p in report.passed_over] == [("Part7", False)]
    assert report.exit_code == 0  # a note, not a failure


def test_the_terminal_says_the_look_alike_and_counts_it(report):
    lines = report.terminal_lines()
    assert f"NOTE passed over Part7: {NOT_NAMED}: M3 screw, a 2.5 hex socket" in lines
    assert lines[-1] == (
        "NOTE not checked: room for a hand (checks: {hand_room: true} turns it on); "
        "1 part shaped like a fastener, not named as one (passed over); "
        "parts the model doesn't have"
    )


def test_the_json_says_which_were_named(report):
    (entry,) = json.loads(report.json_text())["passed_over"]
    assert entry == {
        "name": "Part7",
        "kind": "screw",
        "reason": f"{NOT_NAMED}: M3 screw, a 2.5 hex socket",
        "named": False,
    }


def test_the_markdown_counts_it(report):
    text = report.markdown()
    assert "1 part shaped like a fastener, not named as one (passed over); " in text
    assert f"- `Part7`: {NOT_NAMED}: M3 screw, a 2.5 hex socket" in text


def test_named_and_unnamed_are_counted_apart():
    passed = (
        PassedOver("bolt_hole_cover", S, "why"),
        PassedOver("Part7", S, "why", named=False),
        PassedOver("Part8", S, "why", named=False),
    )
    text = Report(model="m", kit="full", results=(), passed_over=passed).not_checked
    assert (
        "1 part named like a fastener, with no drive or bore in the solid (passed over); "
        "2 parts shaped like fasteners, not named as any (passed over); "
    ) in text


def test_detect_false_looks_at_nothing():
    report = check(model(), Config.from_dict({"checks": {"detect": False}}))
    assert report.passed_over == ()


def test_a_rule_naming_the_look_alike_checks_it():
    rule = {"parts": "Part7", "kind": "screw", "head": "socket", "size": "M3"}
    report = check(model(), Config.from_dict({"fasteners": [rule]}), kit="full")
    assert "Part7" in [r.fastener.name for r in report.results]
    assert report.passed_over == ()


def test_an_ignored_look_alike_is_not_said():
    report = check(model(), Config.from_dict({"ignore": ["Part7"]}), kit="full")
    assert report.passed_over == ()


def test_only_narrows_the_look_alikes_too():
    assert check(model(), kit="full", only="M3*").passed_over == ()


def _export(tmp_path, assembly):
    shapes = []
    for part in assembly:
        part.shape.label = part.name
        shapes.append(part.shape)
    path = tmp_path / "model.step"
    export_step(Compound(children=shapes), str(path))
    return path


def test_detect_writes_the_size_names_as_rules_and_the_look_alike_commented_out(tmp_path):
    result = CliRunner().invoke(main, ["detect", str(_export(tmp_path, model())), "--kit", "full"])
    assert result.exit_code == 0, result.output
    text = result.stdout
    rules = {rule["parts"]: rule for rule in yaml.safe_load(text)["fasteners"]}
    assert rules["M3x16"] == {
        "parts": "M3x16",
        "kind": "screw",
        "head": "socket",
        "size": "M3",
        "length": 16.0,
    }
    assert rules["M3-0.5x16"]["size"] == "M3"
    assert "Part7" not in rules
    assert f"  # Part7: passed over: {NOT_NAMED}: M3 screw, a 2.5 hex socket" in text
    assert "  # - parts: Part7\n  #   kind: screw\n" in text
