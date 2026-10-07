"""Notes the report makes of the run, and notes said once for many (issue #75).

- A sidecar's own tool that no fastener in the model takes, by its kind and size,
  and no rule names, is noted: written with the wrong size, most often. Not one the
  kit's own tool turned first: that one is taken, and waits its turn.
- A note many fasteners share (twenty nuts drawn undersize alike) is said once,
  naming a few of them, the way a FAIL line names its parts; the JSON keeps each
  fastener's own.
"""

import json

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism, socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.fasteners import Fastener, Kind
from wrenchroom.report import FastenerResult, Report, Verdict, md_code

PLATE = Part("plate", Pos(0, 0, -5) * Box(400, 400, 10))
M6_SOCKET = {"parts": "screw*", "kind": "screw", "head": "socket", "size": "M6"}


def screws(count=1):
    """M6 socket head screws (a 5 mm key) on a plate, 40 apart."""
    return [Part(f"screw{i}", Pos(40 * i, 0, 0) * socket_screw("M6")) for i in range(count)]


def run(parts, tools, rules=(M6_SOCKET,)):
    config = Config.from_dict({"fasteners": list(rules), "tools": list(tools)})
    return check(Assembly([*parts, PLATE]), config, kit="full")


# ---------------------------------------------------------------------------
# A custom tool nothing takes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "said"),
    [
        (
            {"name": "unused-key", "type": "hex-key", "across_flats": 7, "long": 80, "short": 20},
            "a 7 mm hex key",
        ),
        (
            {"name": "shop-24", "type": "spanner", "across_flats": 24, "length": 300},
            "a 24 mm spanner",
        ),
        (
            # 7/16 in, given in mm as every custom tool's size is.
            {"name": "inch-ring", "type": "spanner", "across_flats": 11.1125, "length": 150},
            "a 7/16in spanner",
        ),
        (
            {"name": "t30", "type": "torx-key", "size": "T30", "long": 80, "short": 20},
            "a T30 Torx key",
        ),
        ({"name": "long-ph2", "type": "driver", "tip": "ph2"}, "a PH2 Phillips driver"),
        ({"name": "long-slot", "type": "driver", "tip": "slotted"}, "a slotted driver"),
    ],
)
def test_a_custom_tool_no_fastener_takes_is_noted(tool, said):
    report = run(screws(), [tool])
    note = f"tool {tool['name']}: no fastener here takes {said}"
    assert report.notes == (note,)
    assert f"NOTE {note}" in report.terminal_lines()
    assert json.loads(report.json_text())["notes"] == [note]
    assert report.exit_code == 0  # noted, not failed


def test_one_the_kit_s_own_tool_beat_is_still_taken():
    # A short 5 mm key: the screws take a 5 mm key, the kit's own turns them first,
    # and the custom one waits its turn. Taken, so not noted.
    stubby = {"name": "stubby-key-5", "type": "hex-key", "across_flats": 5, "long": 60, "short": 20}
    report = run(screws(), [stubby])
    assert report.results[0].tool == "hex-key-5"
    assert report.notes == ()


def test_one_a_rule_names_is_taken_whatever_its_size():
    seven = {"name": "seven", "type": "hex-key", "across_flats": 7, "long": 80, "short": 20}
    rules = [{**M6_SOCKET, "tool": "seven"}]
    assert run(screws(), [seven], rules).notes == ()


def test_a_nut_s_spanner_and_socket_are_taken_by_the_nut():
    nut = Part("nut", hex_prism(13, 6.8) - Cylinder(4, 30))
    tools = [
        {"name": "ring-13", "type": "spanner", "across_flats": 13, "length": 150},
        {"name": "deep-13", "type": "socket", "across_flats": 13},
        {"name": "ring-14", "type": "spanner", "across_flats": 14, "length": 150},
    ]
    rules = [{"parts": "nut", "kind": "nut", "size": "M8"}]
    report = run([nut], tools, rules)
    assert report.notes == ("tool ring-14: no fastener here takes a 14 mm spanner",)


# ---------------------------------------------------------------------------
# Notes said once for many.
# ---------------------------------------------------------------------------


def noted(*pairs):
    """A report whose results carry these (name, note) pairs, one result a name."""
    by_name: dict[str, list[str]] = {}
    for name, note in pairs:
        by_name.setdefault(name, []).append(note)
    results = tuple(
        FastenerResult(Fastener(name, Kind.NUT), Verdict.TURNS, notes=tuple(notes))
        for name, notes in by_name.items()
    )
    return Report(model="m", kit="full", results=results)


UNDER = "hex drawn undersize: 9.60 across flats, 0.18 under the least its M6 standard allows"


def test_one_note_many_share_is_one_line():
    report = noted(*((f"frame_nut_{i}", UNDER) for i in range(20)), ("lid_nut", "other"))
    lines = [
        line for line in report.terminal_lines() if line.startswith("NOTE frame") or "other" in line
    ]
    assert lines == [
        f"NOTE frame_nut_0, frame_nut_1, frame_nut_2 and 17 more: {UNDER}",
        "NOTE lid_nut: other",
    ]
    assert len(report.noted()) == 21  # every one, each its own, as the JSON keeps them
    entries = json.loads(report.json_text())["fasteners"]
    assert sum(entry["notes"] == [UNDER] for entry in entries) == 20


def test_the_notes_that_differ_now_have_room():
    # Twenty alike used to fill the three lines shown; now they take one.
    pairs = [(f"n{i}", UNDER) for i in range(20)] + [("a", "one"), ("b", "two")]
    lines = noted(*pairs).terminal_lines()
    assert "NOTE a: one" in lines
    assert "NOTE b: two" in lines
    assert not any(line.startswith("NOTE and") for line in lines)


def test_a_note_said_once_names_its_fasteners_in_the_markdown_too():
    report = noted(("a_nut", UNDER), ("b_nut", UNDER), ("c_nut", "c alone"))
    text = report.markdown()
    names = ", ".join(md_code(n, in_table=False) for n in ("a_nut", "b_nut"))
    assert f"\n- {names}: hex drawn undersize" in text
    assert f"\n- {md_code('c_nut', in_table=False)}: c alone" in text


def test_a_single_note_reads_as_it_did():
    (line,) = [line for line in noted(("undersize_nut", UNDER)).terminal_lines() if "under" in line]
    assert line == f"NOTE undersize_nut: {UNDER}"
