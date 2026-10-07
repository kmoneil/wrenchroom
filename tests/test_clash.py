"""A nut its own corners can't turn says so once; one drawn into a part is a clash (#63).

Every tool on a hex's flats tests the space the hex's corners sweep, so a part in
it read as each tool blocked by it: "spanner-13 blocked by block", though no
spanner reaches the block. Now the corner sweep is tried alone, before any tool,
and a part in it is named once: "the nut's corners hit block as it turns".

And a nut drawn into a part, a clash in the model, read as a reach problem, or as
"both ends are covered". Now, when nothing turns a fastener or its free face
can't be told, the parts that stopped it are asked whether its solid is drawn
into them: if so it is not-covered, "drawn into block (N mm^3): fix the model".

The cases, worked by hand: an M8 nut (af 13, its corners 7.505 from the axis
along x, 6.8 tall, bored r 4) on a plate, and a block at its +x corner.
"""

import math

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import MINOR, hex_bolt, hex_prism, socket_screw
from fixture_models import gland
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict, attempt_text

CORNER = 13 / math.sqrt(3)  # 7.505
HEX_AREA = math.sqrt(3) / 2 * 13**2  # 146.36 mm^2
NUT = {"parts": "nut", "kind": "nut", "size": "M8"}
FREE_FACE = "cannot tell the nut's free face: both ends are covered"


def plate():
    return Part("plate", Pos(0, 0, -5) * (Box(200, 200, 10) - Cylinder(4.6, 10)))


def nut_with(*others, bore=4.0):
    """The nut on the plate, with ``others`` round it."""
    return Assembly([Part("nut", hex_prism(13, 6.8) - Cylinder(bore, 30)), plate(), *others])


def block(into, z0=0.0, z1=20.0, name="block"):
    """A block 10 deep and 30 wide, its face ``into`` mm inside the corner circle."""
    return Part(name, Pos(CORNER - into + 5, 0, (z0 + z1) / 2) * Box(10, 30, z1 - z0))


def lid(into):
    """A block over the nut's whole top, ``into`` mm down into it."""
    return Part("lid", Pos(0, 0, 6.8 - into + 5) * Box(30, 30, 10))


def run(assembly, rules=(NUT,), engine="exact", **kwargs):
    config = Config.from_dict({"fasteners": list(rules), "checks": {"detect": False}})
    return check(assembly, config, engine=engine, **kwargs)


def result_of(report, name="nut"):
    (result,) = [r for r in report.results if r.fastener.name == name]
    return result


def fail_line(report, name="nut"):
    (line,) = [line for line in report.terminal_lines() if line.startswith(f"FAIL {name} ")]
    return line


# ---------------------------------------------------------------------------
# Its own corners.
# ---------------------------------------------------------------------------


def test_a_part_on_its_corner_circle_stops_the_nut_and_is_said_once(engine):
    # The block's face on the corner circle: the corner meets it as soon as the nut
    # turns. No spanner, socket or nut driver is tried: one attempt, one probe.
    report = run(nut_with(block(0.0)), engine=engine)
    result = result_of(report)
    assert (result.verdict, result.tool) == (Verdict.BLOCKED, "spanner-13")
    assert result.reason == "the nut's corners hit block as it turns"
    (attempt,) = result.attempts
    assert (attempt.way, attempt.blockers, len(attempt.probes)) == (
        "its corners, turning",
        ("block",),
        1,
    )
    assert attempt_text(attempt) == "spanner-13, its corners, turning: blocked; hit block"
    assert fail_line(report) == f"FAIL nut  spanner-13  blocked  {result.reason}"


@pytest.mark.parametrize("tool", ["socket-13", "nut-driver-13", "spanner-13"])
def test_the_corners_are_tried_with_the_tool_a_rule_names(tool):
    result = result_of(run(nut_with(block(0.0)), [{**NUT, "tool": tool}], kit="full"))
    ((way, tried),) = [(a.way, a.tool) for a in result.attempts]
    assert (way, tried, result.tool) == ("its corners, turning", tool, tool)
    assert result.reason == "the nut's corners hit block as it turns"


def test_a_hex_head_s_corners_are_the_head_s():
    # An M8 hex bolt's head (af 13, 5.2 tall) on the plate, the block at a corner.
    bolt = Part("bolt", hex_bolt("M8"))
    assembly = Assembly([bolt, plate(), block(0.0, 0.0, 5.2)])
    rule = {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"}
    result = result_of(run(assembly, [rule]), "bolt")
    assert result.verdict is Verdict.BLOCKED
    assert result.reason == "the head's corners hit block as it turns"


def test_clear_of_its_corners_the_tools_are_tried_as_before():
    # 3 mm off the corner circle: the corners turn clear, the ring meets the block
    # (its outer r 12.4), and the open end, from the other side, turns it.
    result = result_of(run(nut_with(block(-3.0))))
    assert (result.verdict, result.how) == (Verdict.TURNS, "open end, full length")
    assert [a.way for a in result.attempts] == [
        "ring, full length",
        "ring, stubby",
        "open end, full length",
    ]


# ---------------------------------------------------------------------------
# Drawn into a part.
# ---------------------------------------------------------------------------


def test_a_part_drawn_into_its_side_is_a_clash(engine):
    # The block 1 mm past the corner, 3 tall at the nut's middle (z 1.9 to 4.9): the
    # corner's tip, 1 deep and 2 tan 60 = 3.46 wide, so 1.73 mm^2, 3 tall: 5.2 mm^3.
    report = run(nut_with(block(1.0, 1.9, 4.9)), engine=engine)
    result = result_of(report)
    assert (result.verdict, result.tool) == (Verdict.NOT_COVERED, None)
    assert result.reason == "drawn into block (5.2 mm^3): fix the model"
    assert [a.way for a in result.attempts] == ["its corners, turning"]  # kept, for explain
    assert fail_line(report) == f"FAIL nut  -  not-covered  {result.reason}"


def test_a_part_drawn_over_its_top_is_a_clash(engine):
    # The lid 1 mm down over the whole top: both ends covered, and the nut drawn
    # into the lid by its hex less its bore, 1 deep: 146.36 - 50.27 = 96.1 mm^3.
    result = result_of(run(nut_with(lid(1.0)), engine=engine))
    assert result.verdict is Verdict.NOT_COVERED
    volume = HEX_AREA - math.pi * 4**2
    assert result.reason == f"drawn into lid ({volume:.1f} mm^3): fix the model"
    assert f"{volume:.1f}" == "96.1"


def test_both_ends_covered_with_nothing_drawn_in_is_as_it_was():
    result = result_of(run(nut_with(lid(0.0))))
    assert (result.verdict, result.reason) == (Verdict.NOT_COVERED, FREE_FACE)


def test_a_screw_s_head_drawn_into_a_part_is_a_clash():
    # An M6 socket head (dk 10, 6 tall, a 5 mm key's hex 3 deep), a block over it
    # 0.5 mm down into it: no key gets in. Its head less the hex, 0.5 deep:
    # (78.54 - 21.65) * 0.5 = 28.4 mm^3. A clash, any drive.
    block_over = Part("lid", Pos(0, 0, 6 - 0.5 + 5) * Box(30, 30, 10))
    assembly = Assembly([Part("screw", socket_screw("M6")), plate(), block_over])
    rule = {"parts": "screw", "kind": "screw", "head": "socket", "size": "M6"}
    result = result_of(run(assembly, [rule]), "screw")
    volume = (math.pi * 5**2 - math.sqrt(3) / 2 * 5**2) * 0.5
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == f"drawn into lid ({volume:.1f} mm^3): fix the model"
    assert f"{volume:.1f}" == "28.4"


# ---------------------------------------------------------------------------
# What is no clash: a thread, its partner, a part nothing turning met.
# ---------------------------------------------------------------------------


def stud(radius):
    """A plain rod up the axis, no fastener, through the nut and into the plate."""
    return Part("stud", Pos(0, 0, -1.6) * Cylinder(radius, 16.8))  # z -10 to 6.8


@pytest.mark.parametrize(
    ("radius", "reason"),
    [
        # Drawn at M8's nominal (r 4) in a bore at its minor (r 3.32): the thread,
        # 94 mm^3 of overlap, all of it within 1.25 bores (r 4.15) of the axis.
        (4.0, FREE_FACE),
        # Drawn at r 4.5, past that: a clash, its whole overlap told.
        (4.5, "drawn into stud ({:.1f} mm^3): fix the model"),
    ],
    ids=["thread", "past_the_thread"],
)
def test_a_thread_through_its_bore_is_no_clash(radius, reason):
    bore = MINOR["M8"] / 2
    result = result_of(run(nut_with(stud(radius), lid(0.0), bore=bore)))
    volume = math.pi * (radius**2 - bore**2) * 6.8
    assert result.reason == reason.format(volume)


def test_its_partner_is_passed_over():
    # The same r 4.5 shank, a bolt's this time, paired with the nut: whatever the
    # joint's own two parts share, the partner is no clash.
    bolt = Part("bolt", Pos(0, 0, -15.2) * (hex_prism(13, 5.2) + Pos(0, 0, 13) * Cylinder(4.5, 16)))
    bore = MINOR["M8"] / 2
    rules = [NUT, {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"}]
    report = run(nut_with(bolt, lid(0.0), bore=bore), rules)
    result = result_of(report)
    assert (result.pair, result.reason) == ("bolt", FREE_FACE)


def test_only_what_stopped_it_is_asked():
    # A pin drawn wholly inside the nut (r 5.1 to 5.9, past the thread's reach, inside
    # the flats) stops no tool: the nut turns, and a clash that stops nothing changes
    # no verdict. Behind a wall nothing turns it, and the wall, not the pin, is
    # asked: the pin is never measured (a boolean on every fastener costs a fifth
    # of the 500-fastener budget, for clashes that change no verdict).
    pin = Part("pin", Pos(5.5, 0, 3.4) * Box(0.8, 0.8, 0.8))
    assert result_of(run(nut_with(pin))).verdict is Verdict.TURNS
    # 1.5 over the top: past the free-face probe (to 1.0), but no socket gets on.
    wall = Part("wall", Pos(0, 0, 6.8 + 1.5 + 5) * Box(30, 30, 10))
    hem = [Part(f"hem_{i}", Pos(*xy, 3.4) * Box(2, 2, 6.8)) for i, xy in enumerate(_ROUND)]
    result = result_of(run(nut_with(pin, wall, *hem)))
    assert result.verdict is Verdict.BLOCKED
    assert result.reason is None
    assert "wall" in result.blockers  # asked, and not drawn in
    assert "pin" not in result.blockers


#: Posts round the nut 10 out, every 60 deg, off its corners: no spanner swings.
_ROUND = [
    (10 * math.cos(math.radians(a)), 10 * math.sin(math.radians(a))) for a in range(30, 360, 60)
]


def screw_in_a_block(ceiling):
    """An M6 socket head screw in a block: its shank, drawn at the nominal r 3, in a
    tapped hole drawn at the minor (r 2.46), 185 mm^3 of overlap; the block closed
    over the head in a pocket ``ceiling`` high (the head is 6), so no key gets in."""
    block_ = Pos(0, 0, -5) * Box(40, 40, 30) - Pos(0, 0, ceiling / 2) * Cylinder(6, ceiling)
    block_ = block_ - Pos(0, 0, -10) * Cylinder(MINOR["M6"] / 2, 20)
    rule = {"parts": "screw", "kind": "screw", "head": "socket", "size": "M6"}
    assembly = Assembly([Part("screw", socket_screw("M6")), Part("block", block_)])
    return result_of(run(assembly, [rule]), "screw")


def test_a_shank_in_its_tapped_hole_is_no_clash():
    # The pocket 0.5 over the head: the block stops it and holds its thread, but
    # only the head is measured: blocked, no clash.
    result = screw_in_a_block(6.5)
    assert (result.verdict, result.reason) == (Verdict.BLOCKED, None)
    assert result.blockers == ("block",)


def test_a_head_drawn_in_is_told_by_the_head_alone():
    # The pocket 0.5 under the head's top: a clash, of the head less its key's hex,
    # 0.5 deep, 28.4 mm^3; the thread's 185 isn't added.
    result = screw_in_a_block(5.5)
    assert result.reason == "drawn into block (28.4 mm^3): fix the model"


def test_a_gland_s_stub_in_its_wall_is_no_clash():
    # A gland (af 24, hex z 0 to 8) whose thread stub (r 10, z -12 to 0) the wall's
    # hole (r 10.2) passes for its top 5.5 only: 1127 mm^3 of stub in the wall. A
    # rim on the wall round the hex (r 15 to 25) stops every spanner, so the wall is
    # asked; only the hex is measured, and the stub is in its hole: blocked.
    wall = Pos(0, 0, -5) * Box(200, 200, 10) - Cylinder(10.2, 11)
    wall = wall + Pos(0, 0, 4) * (Cylinder(25, 8) - Cylinder(15, 8))
    assembly = Assembly([Part("gland", gland()), Part("wall", wall)])
    rule = {"parts": "gland", "kind": "nut", "size": "M16", "socket": False, "axis": "+z"}
    result = result_of(run(assembly, [rule], kit="full"), "gland")
    assert (result.verdict, result.reason) == (Verdict.BLOCKED, None)
    assert "wall" in result.blockers


def test_the_whole_head_is_measured_not_its_key_s_hex_only():
    # An M6 socket head (dk 10, z 0 to 6, its key's hex z 3 to 6) under a cap drawn
    # 0.5 into its top and 0.5 into its side (the cap's wall from x 4.5): the top,
    # (78.54 - 21.65) * 0.5 = 28.44, and the side's segment, 25 acos(0.9) - 4.5
    # sqrt(4.75) = 1.468 mm^2 over z 0 to 5.5, 8.07: 36.5 mm^3. Over the key's hex
    # alone (the flats' band) it would be 32.1.
    cap = Pos(0, 0, 10.5) * Box(30, 30, 10) + Pos(9.5, 0, 7.75) * Box(10, 30, 15.5)
    assembly = Assembly([Part("screw", socket_screw("M6")), plate(), Part("cap", cap)])
    rule = {"parts": "screw", "kind": "screw", "head": "socket", "size": "M6"}
    result = result_of(run(assembly, [rule]), "screw")
    top = (math.pi * 25 - math.sqrt(3) / 2 * 25) * 0.5
    side = (25 * math.acos(0.9) - 4.5 * math.sqrt(25 - 4.5**2)) * 5.5
    assert result.reason == f"drawn into cap ({top + side:.1f} mm^3): fix the model"
    assert f"{top + side:.1f}" == "36.5"


def flanged():
    """An M8 nut with a broad flange: its hex (af 13, corners r 7.5) z 1.5 to 8 on a
    flange r 11, 1.5 thick, wider than the hex by more than a third, so the flange
    alone is its widest region; and bored r 4."""
    body = hex_prism(13, 6.5, 1.5) + Pos(0, 0, 0.75) * Cylinder(11, 1.5)
    return Part("nut", body - Cylinder(4, 30))


def segment(r, d):
    """The area of a circle of radius ``r`` past a chord ``d`` from its centre."""
    return r**2 * math.acos(d / r) - d * math.sqrt(r**2 - d**2)


@pytest.mark.parametrize(
    ("z0", "volume"),
    [
        # 1 mm into a corner of the hex, z 3 to 6, clear of the flange: the tip,
        # 1.73 mm^2, 3 tall: 5.2.
        (3.0, math.sqrt(3) * 3),
        # Down to the plate, z 0 to 6: the tip over z 1.5 to 6 (7.79), and the
        # flange's segment past the block's face (x 6.51), 55.79 mm^2, 1.5 thick
        # (83.68): 91.5.
        (0.0, math.sqrt(3) * 4.5 + segment(11, CORNER - 1) * 1.5),
    ],
    ids=["hex", "hex_and_flange"],
)
def test_a_flange_nut_s_hex_and_flange_are_both_measured(z0, volume):
    assembly = Assembly([flanged(), plate(), block(1.0, z0, 6.0)])
    result = result_of(run(assembly))
    assert result.reason == f"drawn into block ({volume:.1f} mm^3): fix the model"
    assert f"{volume:.1f}" in {"5.2", "91.5"}
