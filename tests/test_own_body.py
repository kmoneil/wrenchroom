"""A fastener is never in its own way (issue #221).

A ring, socket or nut driver goes on along the axis, over whatever the part has past
its hex, and a dome or a washer drawn with it wider than their bore keeps them off
(issue #47). Those attempts named the part itself as what they hit, so a nut drawn
with its washer on its outer face read ``blocked  wall, M8 nut``: as if drawn into
itself, and with the real obstacle, the wall the open end meets, in a longer list.
Since issue #210 a fastener of several solids is read whole from STEP too, so the
STEP reading said it as well.

Now such an attempt has no blockers and says how wide the part is past its hex:
``doesn't get on: past its hex the part is 16.00 across``. The note says so as
before; and where nothing else is in the way (a socket the rule names), the reason
says it in the note's place.

The worked nut: an M8, a 13 hex 6.8 high bored 8 on an 8 stud, its washer 16 across
and 1.6 thick on its outer face, 0.05 clear, as two solids of one part; a square tube
round it, 15 out, that keeps the open end from swinging.
"""

import json

import pytest
from build123d import Align, Box, Compound, Cylinder, Pos, RegularPolygon, export_step, extrude
from click.testing import CliRunner

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.report import Verdict, attempt_text

NUT = "M8 nut"
KEPT_OFF = "past its hex the part is 16.00 across"
SENTENCE = (
    f"no ring, socket or nut driver gets on: {KEPT_OFF}, wider than their bore round the "
    "hex; only an open end grips it, from the side"
)
COVERING = ("ring, full length", "ring, stubby", "socket on ratchet")


def parts(*, washer=True, wall=True):
    """The issue's nut on its stud, with its washer and in its tube unless left out."""
    hexnut = extrude(RegularPolygon(13 / 3**0.5, 6), 6.8) - Cylinder(
        4, 6.8, align=(Align.CENTER, Align.CENTER, Align.MIN)
    )
    ring = Pos(0, 0, 6.85 + 0.8) * (Cylinder(8, 1.6) - Cylinder(4.2, 1.6))
    nut = Compound([hexnut.solid(), ring.solid()]) if washer else hexnut
    found = [
        ("plate", Pos(0, 0, -2.5) * Box(80, 80, 5)),
        (NUT, nut),
        ("stud", Pos(0, 0, 10) * Cylinder(4, 30)),
    ]
    if wall:
        found.append(("wall", Pos(0, 0, 10) * (Box(40, 40, 20) - Box(30, 30, 20))))
    return found


def in_pieces(named):
    """The assembly a STEP file of these parts gives, with no file written."""
    shapes = []
    for name, shape in named:
        shape.label = name
        shapes.append(shape)
    return Assembly.from_compound(Compound(children=shapes))


READERS = {"in-pieces": in_pieces, "whole": Assembly.from_shapes}
EITHER = pytest.mark.parametrize("reader", list(READERS))


def run(named, reader="whole", engine="mesh", rules=None):
    """The report on these parts, by detection unless ``rules`` are given."""
    config = Config.from_dict(rules) if rules is not None else None
    return check(READERS[reader](named), config, engine=engine)


def forced(tool):
    return {"fasteners": [{"parts": NUT, "kind": "nut", "size": "M8", "tool": tool}]}


def fail_lines(report):
    return [line for line in report.terminal_lines() if line.startswith("FAIL ")]


@EITHER
def test_both_readers_have_the_nut_whole(reader):
    # The premise: in pieces, its washer is a piece of it, made whole as a fastener.
    assembly = READERS[reader](parts())
    pieces = {part.name: part.piece_of for part in assembly}
    assert pieces.get(f"{NUT}#2") == (NUT if reader == "in-pieces" else None)


@EITHER
def test_a_nut_drawn_with_its_washer_is_blocked_by_the_wall_alone(reader, engine):
    report = run(parts(), reader, engine)
    (result,) = report.results
    assert (result.verdict, result.tool) == (Verdict.BLOCKED, "spanner-13")
    assert (result.blocked_by, result.deciding, result.reason) == (("wall",), (), None)
    assert fail_lines(report) == [f"FAIL {NUT}  spanner-13  blocked  wall"]
    assert result.notes == (SENTENCE,)
    assert f"NOTE {NUT}: {SENTENCE}" in report.terminal_lines()


@EITHER
def test_the_ring_and_socket_say_they_don_t_get_on_and_hit_nothing(reader):
    (result,) = run(parts(), reader).results
    assert [attempt_text(attempt) for attempt in result.attempts] == [
        f"spanner-13, ring, full length: blocked; doesn't get on: {KEPT_OFF}",
        f"spanner-13, ring, stubby: blocked; doesn't get on: {KEPT_OFF}",
        "spanner-13, open end, full length: blocked; hit wall",
        "spanner-13, open end, stubby: blocked; hit wall",
        f"socket-13, socket on ratchet: blocked; doesn't get on: {KEPT_OFF}",
    ]
    for attempt in result.attempts:
        assert NUT not in attempt.blockers
        covering = attempt.way in COVERING
        assert attempt.kept_off == (KEPT_OFF if covering else "")
        if covering:  # where the tool would go on, drawn: it meets the nut's own washer
            assert [probe.hits for probe in attempt.probes] == [(NUT,)]


def test_without_its_washer_the_ring_gets_on_and_meets_the_stud():
    # The same nut with its washer left off, as the issue says: the ring is tried, and
    # its way down meets the stud. Nothing kept it off, so no attempt says so.
    (result,) = run(parts(washer=False)).results
    assert (result.verdict, set(result.blocked_by)) == (Verdict.BLOCKED, {"wall", "stud"})
    assert result.notes == ()
    assert not any(attempt.kept_off for attempt in result.attempts)


@EITHER
def test_with_nothing_else_in_its_way_it_turns_by_the_open_end(reader):
    # Its own shape alone changes nothing: the open end turns it, and the note stays.
    (result,) = run(parts(wall=False), reader).results
    assert (result.verdict, result.how) == (Verdict.TURNS, "open end, full length")
    assert (result.blocked_by, result.reason, result.notes) == ((), None, (SENTENCE,))


@EITHER
@pytest.mark.parametrize("wall", [True, False], ids=["walled", "open"])
def test_a_socket_its_own_shape_keeps_off_fails_for_that_reason(reader, wall):
    # Nothing in the way but the nut itself, which is no blocker: the reason says why,
    # where "no tool found" would otherwise, and the note doesn't say it again.
    report = run(parts(wall=wall), reader, rules=forced("socket-13"))
    (result,) = report.results
    assert (result.verdict, result.tool) == (Verdict.BLOCKED, "socket-13")
    assert (result.blocked_by, result.deciding) == ((), ())
    assert (result.reason, result.notes) == (SENTENCE, ())
    assert fail_lines(report) == [f"FAIL {NUT}  socket-13  blocked  {SENTENCE}"]
    assert not [line for line in report.terminal_lines() if line.startswith(f"NOTE {NUT}")]
    entry = report.to_json_dict()["fasteners"][0]
    assert (entry["blocked_by"], entry["reason"], entry["notes"]) == ([], SENTENCE, [])
    markdown = report.markdown()
    assert f"| `{NUT}` | `socket-13` | blocked | `{SENTENCE}` |" in markdown
    assert "#### Notes" not in markdown


def test_a_spanner_named_for_it_is_blocked_by_the_wall_with_the_note():
    # A rule's spanner tries its ring, kept off, and its open end, at the wall: the
    # wall is in the way, so the reason is none and the note says why the ring isn't.
    (result,) = run(parts(), rules=forced("spanner-13")).results
    assert (result.verdict, result.blocked_by, result.reason) == (
        Verdict.BLOCKED,
        ("wall",),
        None,
    )
    assert result.notes == (SENTENCE,)


def test_explain_from_step_says_the_ring_doesn_t_get_on(tmp_path):
    """The issue's own run: the parts written to STEP, then ``explain``."""
    shapes = []
    for name, shape in parts():
        shape.label = name
        shapes.append(shape)
    step = tmp_path / "self.step"
    export_step(Compound(children=shapes), str(step))
    out = CliRunner().invoke(main, ["explain", str(step), NUT])
    assert out.exit_code == 1, out.output
    assert out.output.splitlines()[2:] == [
        f"  tried spanner-13, ring, full length: blocked; doesn't get on: {KEPT_OFF}",
        f"  tried spanner-13, ring, stubby: blocked; doesn't get on: {KEPT_OFF}",
        "  tried spanner-13, open end, full length: blocked; hit wall",
        "  tried spanner-13, open end, stubby: blocked; hit wall",
        f"  tried socket-13, socket on ratchet: blocked; doesn't get on: {KEPT_OFF}",
    ]
    checked = CliRunner().invoke(main, ["check", str(step), "--json", "-"])
    (entry,) = json.loads(checked.stdout)["fasteners"]
    assert (entry["name"], entry["blocked_by"]) == (NUT, ["wall"])
