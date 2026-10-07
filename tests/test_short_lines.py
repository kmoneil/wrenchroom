"""A FAIL line names a few parts, most in the way first, and each once (#64).

With hand room, a FAIL line gave its parts twice: "no room for a hand (A, B, C in
the way); best arc bounded by A, B, C", the same list both times, and on a large
model the lines ran to 800 characters. Now a reason names the parts once, the
"only holds" reason carries its best arc, and a line or reason names at most
NAMES_SHOWN parts, the one hit at the most probed positions first, then "and N
more". The JSON's blocked_by and deciding, explain and the HTML view keep every
one.
"""

import json

import pytest

from test_deciding import NUT, ring_of_posts
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.fasteners import Fastener, Kind
from wrenchroom.report import (
    NAMES_SHOWN,
    FastenerResult,
    Report,
    Verdict,
    bounded,
    listed,
    shortlist,
)
from wrenchroom.solids import ToolSolid
from wrenchroom.tools.sweep import Attempt, Probe

NOWHERE = ToolSolid(())


def tried(*hits_per_probe):
    """One attempt whose probes hit these parts, probe by probe."""
    probes = tuple(Probe(NOWHERE, hits) for hits in hits_per_probe)
    names = tuple(dict.fromkeys(name for hits in hits_per_probe for name in hits))
    return Attempt("hex-key-5", "short leg in", False, False, 0.0, names, probes)


def test_the_part_hit_most_comes_first_and_the_rest_are_counted():
    attempt = tried(("a",), ("b", "c"), ("c",), ("d", "c"), ("e",), ("d",))
    names = ("a", "b", "c", "d", "e")
    assert NAMES_SHOWN == 3
    assert shortlist(names, (attempt,)) == (("c", "d", "a"), 2)  # c 3 hits, d 2, then a
    assert listed(names, (attempt,)) == "c, d, a and 2 more"
    assert listed(("a", "b"), (attempt,)) == "a, b"  # a tie keeps first-seen order
    assert listed(names) == "a, b, c and 2 more"  # with no attempts, as given


@pytest.mark.parametrize(
    ("bounds", "text"),
    [
        (("a", "b"), "between a and b"),
        (("a",), "bounded by a"),
        (("a", "b", "c", "d"), "bounded by a, b, c and 1 more"),
    ],
)
def test_a_best_arc_s_ends(bounds, text):
    assert bounded(bounds) == text


def blocked(names, attempts=()):
    result = FastenerResult(
        Fastener("nut", Kind.NUT),
        Verdict.BLOCKED,
        tool="spanner-13",
        blockers=names,
        attempts=attempts,
    )
    return Report(model="m", kit="full", results=(result,))


def test_a_long_list_on_a_fail_line_is_cut_most_hit_first():
    attempt = tried(("p1",), ("p2",), ("p5", "p2"), ("p5",), ("p5",), ("p3",), ("p4",))
    report = blocked(("p1", "p2", "p3", "p4", "p5"), (attempt,))
    (fail,) = [line for line in report.terminal_lines() if line.startswith("FAIL")]
    assert fail == "FAIL nut  spanner-13  blocked  p5, p2, p1 and 2 more"
    assert "| `p5`, `p2`, `p1` and 2 more |" in report.markdown()
    entry = json.loads(report.json_text())["fasteners"][0]
    assert entry["blocked_by"] == ["p1", "p2", "p3", "p4", "p5"]  # the JSON keeps every one


def test_a_short_list_is_as_it_was():
    (fail,) = [line for line in blocked(("a", "b")).terminal_lines() if line.startswith("FAIL")]
    assert fail == "FAIL nut  spanner-13  blocked  a, b"


def test_a_hand_stopped_is_named_once():
    # Issue #64's own case: the posts round a nut, under a roof, with hand room.
    config = Config.from_dict({"fasteners": [NUT], "checks": {"hand_room": True}})
    report = check(ring_of_posts(), config, kit="full")
    (result,) = report.results
    assert result.reason == "no room for a hand: the hand hits roof on its best arc"
    (fail,) = [line for line in report.terminal_lines() if line.startswith("FAIL")]
    assert fail == f"FAIL nut  spanner-13  blocked  {result.reason}"
    assert fail.count("roof") == 1
    entry = json.loads(report.json_text())["fasteners"][0]
    assert entry["reason"] == result.reason
    assert len(entry["blocked_by"]) > NAMES_SHOWN  # every post and the roof, in the JSON


def test_the_only_holds_reason_carries_its_best_arc_once():
    report = check(ring_of_posts(), Config.from_dict({"fasteners": [NUT]}), kit="full")
    (result,) = report.results
    first, second = result.deciding
    assert result.reason == f"only holds, and it has no nut; best arc between {first} and {second}"
    (fail,) = [line for line in report.terminal_lines() if line.startswith("FAIL")]
    assert fail.endswith(result.reason)
    assert fail.count("best arc") == 1
