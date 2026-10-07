"""A pass only a ball end reaches says so, and shallow sockets get no ball end (#51).

A ball end turns a socket screw with its leg leant over, but takes much less
torque than a straight key: a screw only a ball end reaches can be run in and
out, and maybe not tightened to its torque or broken loose. Such a pass used to
read like any other; now the result notes it. And a ball end was credited in any
keyed head, where a button head's socket (ISO 7380) or a countersunk head's (ISO
10642) is about half as deep as a socket head's, barely deeper than the ball:
only socket heads (ISO 4762) and shoulder screws (ISO 7379) take one now.

The worked case is the issue's: an M5 head under a roof 22 over the base, with
one opening off to the side, 20 degrees round from the axis, that only a key
leant over goes through.
"""

import json
import math

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.fasteners import Head
from wrenchroom.report import Verdict

#: The outlines of the M5 heads, (diameter, height), and the key each takes.
HEADS = {
    "socket": ((8.5, 5.0), 4.0),  # ISO 4762
    "button": ((9.5, 2.75), 3.0),  # ISO 7380-1
    "shoulder": ((10.0, 4.5), 3.0),  # ISO 7379, on its 6.5 shoulder: M5
}

NOTE = (
    "only a ball end turns it (ball end, 10 deg off the axis): a ball end takes much less "
    "torque than a straight key, so tightening it to its torque, or breaking it loose, may "
    "need a straight key, which can't get in"
)


def screw(head):
    """An M5 screw with a ``head`` outline and its key's socket, on z 0 up."""
    (diameter, height), key = HEADS[head]
    shape = Pos(0, 0, -6) * Cylinder(2.5, 12) + Pos(0, 0, height / 2) * Cylinder(
        diameter / 2, height
    )
    return shape - hex_prism(key, height * 0.6 + 0.01, height * 0.4)


def under_a_roof(head):
    """The screw on a base, a roof over it open only 20 degrees round from its axis."""
    height = HEADS[head][0][1]
    off = (22 - height) * math.tan(math.radians(20))
    roof = Pos(0, 0, 24) * (Box(120, 120, 4) - Pos(off, 0, 0) * Cylinder(7, 4))
    base = Pos(0, 0, -3) * (Box(120, 120, 6) - Cylinder(2.75, 6))
    return Assembly([Part("base", base), Part("screw", screw(head)), Part("roof", roof)])


def run(head, engine="mesh", kit="full", flat=False):
    shape_head = "flat" if flat else head
    rule = {"parts": "screw", "kind": "screw", "head": shape_head, "size": "M5"}
    rule["axis"] = [0, 0, 1]
    config = Config.from_dict({"checks": {"detect": False}, "fasteners": [rule]})
    return check(under_a_roof(head), config, kit=kit, engine=engine)


def test_a_socket_head_only_a_ball_end_reaches_turns_and_says_so(engine):
    report = run("socket", engine)
    (result,) = report.results
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "ball-end-key-4",
        "ball end, 10 deg off the axis",
    )
    assert result.notes == (NOTE,)
    assert f"NOTE screw: {NOTE}" in report.terminal_lines()
    assert f"- `screw`: {NOTE}" in report.markdown()
    assert json.loads(report.json_text())["fasteners"][0]["notes"] == [NOTE]
    assert report.exit_code == 0  # a note, not a failure


def test_a_shoulder_screw_s_socket_takes_a_ball_end_too():
    (result,) = run("shoulder").results
    assert (result.verdict, result.tool) == (Verdict.TURNS, "ball-end-key-3")
    assert result.notes[0].startswith("only a ball end turns it")


@pytest.mark.parametrize("flat", [False, True], ids=["button", "countersunk"])
def test_a_shallow_socket_gets_no_ball_end(engine, flat):
    # The button head (or, described as one, a countersunk head) used to turn with
    # ball-end-key-3 leant 10 deg.
    (result,) = run("button", engine, flat=flat).results
    assert (result.verdict, result.tool) == (Verdict.BLOCKED, "hex-key-3")
    assert result.blockers == ("roof",)
    assert not any(a.tool.startswith("ball-end-key") for a in result.attempts)
    assert result.notes == ()


def test_which_heads_take_a_ball_end():
    from wrenchroom.checker import _BALL_END_HEADS  # noqa: PLC0415

    assert set(_BALL_END_HEADS) == {Head.SOCKET, Head.SHOULDER}


def test_a_straight_key_s_pass_says_nothing():
    # No roof: the driver goes straight in.
    base = Pos(0, 0, -3) * (Box(120, 120, 6) - Cylinder(2.75, 6))
    assembly = Assembly([Part("base", base), Part("screw", screw("socket"))])
    rule = {"parts": "screw", "kind": "screw", "head": "socket", "size": "M5"}
    (result,) = check(assembly, Config.from_dict({"fasteners": [rule]}), kit="full").results
    assert (result.how, result.notes) == ("driver straight in", ())


def test_a_ball_end_that_fails_too_says_nothing_of_it():
    # The roof closed: every key, ball end included, meets it.
    base = Pos(0, 0, -3) * (Box(120, 120, 6) - Cylinder(2.75, 6))
    roof = Pos(0, 0, 24) * Box(120, 120, 4)
    assembly = Assembly([Part("base", base), Part("screw", screw("socket")), Part("roof", roof)])
    rule = {"parts": "screw", "kind": "screw", "head": "socket", "size": "M5"}
    (result,) = check(assembly, Config.from_dict({"fasteners": [rule]}), kit="full").results
    assert result.verdict is Verdict.BLOCKED
    assert any(a.tool.startswith("ball-end-key") for a in result.attempts)  # it was tried
    assert result.notes == ()


def test_metric_home_has_no_ball_end_to_reach_it():
    (result,) = run("socket", kit="metric-home").results
    assert (result.verdict, result.notes) == (Verdict.BLOCKED, ())
