"""A fastener noun with ordinary words after it: taken on its solid, never silent (#30).

``box_gland_vent`` may be a gland or a vent; ``bolt_hole_marker`` is a marker. Such a
name is a candidate, and its solid decides: a drive a tool fits (a hex a spanner
fits, a hex pocket a key fits, a cross) makes it a fastener, at no more than medium
confidence; anything else and it is passed over, which every report, the JSON and
``detect``'s sidecar all say. A slot or a square is never enough: a slotted block
or a plain plate shows one as readily as a fastener.

A name whose last word is a part's own noun (``nut_plate``, ``screw_boss``,
``bolt_hole_cover``) says what the part is: passed over, it isn't listed, as the
note would be noise (issue #75). Its solid still decides, so one showing a drive is
still taken.
"""

import json

import pytest
import yaml
from build123d import Box, Compound, Cylinder, Pos, export_step
from click.testing import CliRunner

from fastener_models import hex_bolt, hex_nut, hex_prism, pan_phillips, socket_screw
from fixture_models import gland
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.detect import NO_DRIVE, find, read_name, read_shape, shows_drive
from wrenchroom.detect.names import ends_in_part_noun
from wrenchroom.fasteners import Head, Kind, PassedOver
from wrenchroom.report import PASSED_OVER_SHOWN, Report, Verdict


def plate():
    return Pos(0, 0, -5) * Box(200, 200, 10) - Cylinder(10.2, 11)


def holed_square():
    """A plain square plate with a round hole: its outline reads as a square neck."""
    return Box(40, 40, 10) - Cylinder(3, 20)


def slotted_block():
    """A round block, bored, with a slot across its top: it reads as a slotted head."""
    return Cylinder(20, 10) - Cylinder(3, 20) - Pos(0, 0, 4) * Box(4, 60, 3)


# ---------------------------------------------------------------------------
# What a solid must show.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("shape", "kind", "head"),
    [
        (lambda: hex_nut("M8"), Kind.NUT, None),
        (gland, Kind.NUT, None),
        (lambda: hex_bolt("M8"), Kind.SCREW, Head.HEX),
        (lambda: socket_screw("M6"), Kind.SCREW, Head.SOCKET),
        (pan_phillips, Kind.SCREW, Head.PHILLIPS),
    ],
)
def test_a_drive_a_tool_fits_confirms_a_candidate(shape, kind, head):
    reading = read_shape(shape(), kind)
    assert reading.head is head
    assert shows_drive(reading)


@pytest.mark.parametrize(
    ("shape", "kind", "head"),
    [
        (holed_square, Kind.SCREW, Head.CARRIAGE),  # a plate's outline, a "square neck"
        (slotted_block, Kind.SCREW, Head.SLOTTED),  # a slot in any block
        (lambda: Cylinder(5, 20), Kind.SCREW, None),
        (lambda: Cylinder(5, 20) - Cylinder(2, 30), Kind.NUT, None),
        (lambda: hex_prism(22.5, 8) - Cylinder(5, 30), Kind.NUT, None),  # no tool's size
        (lambda: hex_prism(200, 8) - Cylinder(5, 30), Kind.NUT, None),  # a hex plate
    ],
)
def test_nothing_else_does(shape, kind, head):
    reading = read_shape(shape(), kind)
    assert reading.head is head
    assert not shows_drive(reading)


# ---------------------------------------------------------------------------
# Detection.
# ---------------------------------------------------------------------------


def test_a_candidate_with_a_drive_is_taken_at_medium_confidence():
    found = find([Part("box_gland_vent", gland())])
    (fastener,) = found.fasteners
    assert found.passed_over == ()
    assert (fastener.kind, fastener.socket_allowed) == (Kind.NUT, False)
    assert fastener.drive_af == pytest.approx(24.0)
    assert fastener.basis == "noun 'gland', words after it; solid: 24 across flats"
    assert fastener.confidence == "medium"


def test_the_same_part_named_outright_is_high():
    (fastener,) = find([Part("box_gland", gland())]).fasteners
    assert fastener.confidence == "high"


def test_a_candidate_with_no_drive_is_passed_over_saying_why():
    found = find([Part("bolt_hole_marker", holed_square()), Part("frame_bolt", hex_bolt("M8"))])
    assert [f.name for f in found.fasteners] == ["frame_bolt"]
    assert found.passed_over == (
        PassedOver("bolt_hole_marker", Kind.SCREW, f"noun 'bolt', words after it; {NO_DRIVE}"),
    )
    assert NO_DRIVE == "its solid shows no hex, hex socket or cross a tool fits"


def test_a_name_with_no_fastener_noun_is_neither():
    found = find([Part("cover", holed_square()), Part("nutmeg", hex_nut("M8"))])
    assert found == type(found)((), ())


# ---------------------------------------------------------------------------
# The report: every format says what was passed over.
# ---------------------------------------------------------------------------


def model():
    """A gland named box_gland_vent through a wall, and two candidates with no drive."""
    return Assembly(
        [
            Part("box_gland_vent", gland()),
            Part("wall", plate()),
            Part("bolt_hole_marker", Pos(300, 0, 0) * holed_square()),
            Part("screw_post", Pos(-300, 0, 0) * Cylinder(5, 20)),
        ]
    )


@pytest.fixture(scope="module")
def report():
    return check(model(), kit="full")


def test_the_gland_is_checked_and_the_rest_passed_over(report):
    (result,) = report.results
    assert (result.fastener.name, result.verdict, result.tool) == (
        "box_gland_vent",
        Verdict.TURNS,
        "spanner-24",
    )
    assert [p.name for p in report.passed_over] == ["bolt_hole_marker", "screw_post"]
    assert report.exit_code == 0  # a note, not a failure


def test_the_terminal_names_each_and_counts_them_under_not_checked(report):
    lines = report.terminal_lines()
    assert f"NOTE passed over bolt_hole_marker: noun 'bolt', words after it; {NO_DRIVE}" in lines
    assert f"NOTE passed over screw_post: noun 'screw', words after it; {NO_DRIVE}" in lines
    assert lines[-1] == (
        "NOTE not checked: room for a hand (checks: {hand_room: true} turns it on); "
        "2 parts named like a fastener, with no drive in the solid (passed over); "
        "parts the model doesn't have"
    )


def test_the_json_lists_them(report):
    document = json.loads(report.json_text())
    assert document["passed_over"] == [
        {
            "name": "bolt_hole_marker",
            "kind": "screw",
            "reason": f"noun 'bolt', words after it; {NO_DRIVE}",
        },
        {
            "name": "screw_post",
            "kind": "screw",
            "reason": f"noun 'screw', words after it; {NO_DRIVE}",
        },
    ]
    assert document["schema"] == 1  # a key added, nothing broken


def test_the_markdown_lists_them(report):
    text = report.markdown()
    assert "#### Passed over" in text
    assert "- `bolt_hole_marker`: noun 'bolt', words after it; its solid shows no hex" in text
    assert "2 parts named like a fastener, with no drive in the solid (passed over); " in text


def test_a_long_list_is_cut_in_the_terminal_and_markdown_but_not_the_json():
    passed = tuple(PassedOver(f"bolt_{i:02}_cover", Kind.SCREW, "why") for i in range(13))
    long = Report(model="m.step", kit="full", results=(), passed_over=passed)
    lines = long.terminal_lines()
    assert sum(line.startswith("NOTE passed over ") for line in lines) == PASSED_OVER_SHOWN == 10
    assert "NOTE and 3 more passed over (the JSON lists every one)" in lines
    assert "- and 3 more (the JSON lists every one)" in long.markdown()
    assert len(json.loads(long.json_text())["passed_over"]) == 13


def test_one_part_is_counted_in_the_singular():
    one = Report(
        model="m", kit="full", results=(), passed_over=(PassedOver("a_nut_x", Kind.NUT, "why"),)
    )
    assert (
        "1 part named like a fastener, with no drive in the solid (passed over)" in one.not_checked
    )


def test_nothing_passed_over_says_nothing_new():
    report = check(Assembly([Part("frame_bolt", hex_bolt("M8"))]), kit="full")
    assert report.passed_over == ()
    assert not any("passed over" in line for line in report.terminal_lines())
    assert "Passed over" not in report.markdown()


def test_only_narrows_what_is_passed_over_too():
    report = check(model(), kit="full", only="bolt_*")
    assert [p.name for p in report.passed_over] == ["bolt_hole_marker"]


def test_detect_false_passes_nothing_over():
    report = check(model(), Config.from_dict({"checks": {"detect": False}}))
    assert report.passed_over == ()


def test_a_rule_naming_a_candidate_describes_it_outright():
    rule = {"parts": "bolt_hole_marker", "kind": "screw", "head": "socket", "size": "M6"}
    report = check(model(), Config.from_dict({"fasteners": [rule]}), kit="full")
    assert "bolt_hole_marker" in [r.fastener.name for r in report.results]
    assert [p.name for p in report.passed_over] == ["screw_post"]


# ---------------------------------------------------------------------------
# detect: written commented out, for a person to decide.
# ---------------------------------------------------------------------------


def _export(tmp_path, assembly):
    shapes = []
    for part in assembly:
        part.shape.label = part.name
        shapes.append(part.shape)
    path = tmp_path / "model.step"
    export_step(Compound(children=shapes), str(path))
    return path


def test_detect_writes_each_passed_over_part_commented_out(tmp_path):
    result = CliRunner().invoke(main, ["detect", str(_export(tmp_path, model())), "--kit", "full"])
    assert result.exit_code == 0, result.output
    text = result.stdout
    assert f"  # bolt_hole_marker: passed over: noun 'bolt', words after it; {NO_DRIVE}" in text
    assert "  # - parts: bolt_hole_marker\n  #   kind: screw\n" in text
    # As written, only the gland is a rule; uncommented, the cover is one too.
    rules = yaml.safe_load(text)["fasteners"]
    assert [rule["parts"] for rule in rules] == ["box_gland_vent"]
    uncommented = text.replace(
        "  # - parts: bolt_hole_marker", "  - parts: bolt_hole_marker"
    ).replace("  #   kind: screw", "    kind: screw", 1)
    names = [rule["parts"] for rule in yaml.safe_load(uncommented)["fasteners"]]
    assert names == ["box_gland_vent", "bolt_hole_marker"]


def test_detect_with_only_passed_over_parts_says_so(tmp_path):
    assembly = Assembly([Part("bolt_hole_marker", holed_square())])
    text = CliRunner().invoke(main, ["detect", str(_export(tmp_path, assembly))]).stdout
    assert "fasteners: []  # none taken; the parts passed over follow" in text
    assert yaml.safe_load(text)["fasteners"] == []
    assert "# - parts: bolt_hole_marker" in text


def test_a_hostile_candidate_name_steers_nothing():
    name = "bolt" + chr(0x1B) + "]0;pwned" + chr(0x07) + "_hole_cover"
    assert read_name(name).needs_drive
    passed = (PassedOver(name, Kind.SCREW, "why"),)
    report = Report(model="m", kit="full", results=(), passed_over=passed)
    (line,) = [line for line in report.terminal_lines() if line.startswith("NOTE passed over")]
    assert "\\x1b]0;pwned\\x07" in line
    assert chr(0x1B) not in report.markdown()


@pytest.mark.parametrize("name", ["nut_plate", "screw_boss", "bolt_hole_cover", "GlandPlate"])
def test_a_name_ending_in_a_part_noun_is_passed_over_without_a_word(name):
    found = find([Part(name, holed_square())])
    assert (found.fasteners, found.passed_over) == ((), ())


def test_a_name_ending_in_a_part_noun_is_still_taken_when_its_solid_shows_a_drive():
    # A nut plate drawn as a nut, a hex and its bore: the solid decides, as before.
    found = find([Part("nut_plate", hex_nut("M8"))])
    ((nut,), passed) = found.fasteners, found.passed_over
    assert (nut.name, nut.kind, passed) == ("nut_plate", Kind.NUT, ())


@pytest.mark.parametrize(
    ("name", "ends"),
    [
        ("nut_plate", True),
        ("box_wall", True),
        ("screw_post", False),
        ("bolt_hole_marker", False),
        ("nut", False),
        ("plate_nut", False),
        ("", False),
    ],
)
def test_which_names_end_in_a_part_noun(name, ends):
    assert ends_in_part_noun(name) is ends
