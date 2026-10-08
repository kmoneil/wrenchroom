"""A clash on a screw's head is measured on all of its head (issue #116).

A clash (#63, #94) used to be measured on a fastener's hex and widest region along
its axis. On a socket head that is the whole head; on a button or pan head it is
the thin rim under the dome or crown, so a part drawn into the dome read as
blocking the key, and a head buried in a block read as a sliver of its volume. A
countersunk head's rim is thinner still, and the whole screw was measured, its
thread in a tapped hole drawn at the minor counted as a clash.

Now a screw's head is all of it but its shank: from its bearing face to its top,
and under the bearing face a countersunk cone, which flares out of the shank. The
shank, a cylinder its drawn radius from its tip to the bearing face, is left out,
as a thread is.

The heads, worked by hand:

- An ISO 7380-1 M4 button head (dk 7.6, k 2.2): a rim r 3.8, z 0 to 0.4, under a
  dome, a sphere of R (3.8^2 + 2.1^2) / 4.2 = 4.4881 whose apex would be at 2.5,
  cut flat at 2.2 (a flat r 1.61 round the socket), and a 2.5 hex socket 1.3 deep.
  A cap of height h is pi h^2 (3R - h) / 3; the dome, z 0.4 to 2.2, is the cap of
  2.1 less the cap of 0.3: 52.48 - 1.24 = 51.24. The rim, pi 3.8^2 0.4 = 18.15.
  The socket, 2.5^2 sqrt(3) / 2 = 5.413 mm^2 by 1.3, 7.04. The head: 62.35 mm^3.
"""

import math

import pytest
from build123d import Axis, Box, Cone, Cylinder, Pos, RegularPolygon, Rot, Sphere, extrude, fillet

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict

R = (3.8**2 + 2.1**2) / (2 * 2.1)  # 4.4881
SOCKET_AREA = math.sqrt(3) / 2 * 2.5**2  # 5.4127
M4_MINOR = 3.242  # ISO 261's, as the clash tests draw a tapped hole


def cap(h, radius=R):
    """A sphere's cap ``h`` high."""
    return math.pi * h**2 * (3 * radius - h) / 3


DOME = cap(2.1) - cap(0.3)  # z 0.4 to 2.2
RIM = math.pi * 3.8**2 * 0.4
HEAD = RIM + DOME - SOCKET_AREA * 1.3  # 62.35


def hexagon(af, h, z0=0.0):
    return Pos(0, 0, z0) * extrude(RegularPolygon(af / math.sqrt(3), 6), h)


def button(length=10.0):
    """The ISO 7380-1 M4 head above, on a 4 mm shank ``length`` long under z = 0."""
    rim = Pos(0, 0, 0.2) * Cylinder(3.8, 0.4)
    dome = (Pos(0, 0, 2.5 - R) * Sphere(R)) & (Pos(0, 0, 1.3) * Box(8, 8, 1.8))
    head = rim + dome - hexagon(2.5, 1.31, 2.2 - 1.3)
    return head + Pos(0, 0, -length / 2) * Cylinder(2, length)


BUTTON = {"kind": "screw", "head": "button", "size": "M4"}


def run(parts, rule, engine="exact"):
    config = Config.from_dict({"fasteners": [rule], "checks": {"detect": False}})
    report = check(Assembly([Part(name, shape) for name, shape in parts]), config, engine=engine)
    (result,) = [r for r in report.results if r.fastener.name == rule["parts"]]
    return result


def plate(hole=2.0):
    return Pos(0, 0, -5) * Box(30, 30, 10) - Cylinder(hole, 30)


def clash(name, volume):
    return f"drawn into {name} ({volume:.1f} mm^3): fix the model"


def test_the_hand_work():
    assert (round(R, 4), round(DOME, 2), round(RIM, 2), round(HEAD, 2)) == (
        4.4881,
        51.24,
        18.15,
        62.35,
    )
    assert button().volume == pytest.approx(HEAD + math.pi * 4 * 10, abs=0.05)


# ---------------------------------------------------------------------------
# A button head: its dome, and all of it buried.
# ---------------------------------------------------------------------------


def test_a_part_drawn_into_a_button_head_s_dome_is_a_clash(engine):
    # A cover 0.5 down onto the dome, its underside at z 1.7, clear of the rim: the
    # head over 1.7 is the cap of 0.8 less the cap of 0.3, less the socket's top
    # 0.5: 8.49 - 1.24 - 2.71 = 4.54 mm^3. It used to block the key, as a cover
    # clear of the head would.
    volume = cap(0.8) - cap(0.3) - SOCKET_AREA * 0.5
    cover = Pos(0, 0, 1.7 + 2) * Box(20, 20, 4)
    result = run(
        [("plate", plate()), ("screw", button()), ("cover", cover)],
        {"parts": "screw", **BUTTON},
        engine,
    )
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == clash("cover", volume)
    assert f"{volume:.1f}" == "4.5"


def test_a_cover_clear_of_the_head_blocks_it_as_before(engine):
    cover = Pos(0, 0, 2.2 + 2 + 2) * Box(20, 20, 4)
    result = run(
        [("plate", plate()), ("screw", button()), ("cover", cover)],
        {"parts": "screw", **BUTTON},
        engine,
    )
    assert (result.verdict, result.reason) == (Verdict.BLOCKED, None)
    assert result.blockers == ("cover",)


def test_a_head_buried_in_a_block_is_told_as_all_of_it(engine):
    # The head inside a 20 mm cube from z 0: all 62.35 mm^3 of it. Its rim alone,
    # which used to be measured, is 18.15.
    block = Pos(0, 0, 10) * Box(20, 20, 20)
    result = run(
        [("plate", plate()), ("screw", button()), ("block", block)],
        {"parts": "screw", **BUTTON},
        engine,
    )
    assert result.reason == clash("block", HEAD)
    assert f"{HEAD:.1f}" == "62.4"


def test_a_thread_in_its_tapped_hole_stays_out_of_a_buried_head(engine):
    # The same block, down to z -10, tapped at the minor (r 1.62) for the shank, which
    # is drawn at the nominal (r 2): 10 long, pi (4 - 2.63) 10 = 43.2 mm^3 of thread
    # in common, which isn't added. The head alone, 62.35.
    block = Pos(0, 0, 5) * Box(20, 20, 30) - Pos(0, 0, -5) * Cylinder(M4_MINOR / 2, 10)
    result = run([("screw", button()), ("block", block)], {"parts": "screw", **BUTTON}, engine)
    assert result.reason == clash("block", HEAD)


def test_a_head_drawn_without_its_shank_is_all_head(engine):
    # The button head alone, as a part whose shank is another solid draws its head
    # piece: all of it is head, 62.35 mm^3 buried, not its rim's 18.15.
    head = button() & (Pos(0, 0, 5) * Box(20, 20, 10))  # all of it over z = 0
    assert head.volume == pytest.approx(HEAD, abs=0.05)
    block = Pos(0, 0, 10) * Box(20, 20, 20)
    parts = [("plate", plate()), ("screw", head), ("block", block)]
    result = run(parts, {"parts": "screw", **BUTTON, "axis": "+z"}, engine)
    assert result.reason == clash("block", HEAD)


def button_down(length=10.0):
    """The button screw head down, drawn so: its head under z = 0 and its shank up,
    every round's axis still +z, so its head is the near end along its axis (turned
    over whole, its axes turn with it, and its head is the far end again)."""
    rim = Pos(0, 0, -0.2) * Cylinder(3.8, 0.4)
    dome = (Pos(0, 0, -(2.5 - R)) * Sphere(R)) & (Pos(0, 0, -1.3) * Box(8, 8, 1.8))
    head = rim + dome - hexagon(2.5, 1.31, -2.2 - 0.01)
    return head + Pos(0, 0, length / 2) * Cylinder(2, length)


@pytest.mark.parametrize("down", ["turned", "drawn"])
def test_a_head_pointing_down_is_measured_the_same(engine, down):
    # The buried case upside down, turned over whole or drawn so.
    if down == "turned":
        flip = Rot(180, 0, 0)
        parts = [("plate", flip * plate()), ("screw", flip * button())]
    else:
        plate_ = Pos(0, 0, 5) * Box(30, 30, 10) - Cylinder(2, 30)
        parts = [("plate", plate_), ("screw", button_down())]
    parts.append(("block", Pos(0, 0, -10) * Box(20, 20, 20)))
    result = run(parts, {"parts": "screw", **BUTTON}, engine)
    assert result.reason == clash("block", HEAD)


# ---------------------------------------------------------------------------
# A pan head's crown.
# ---------------------------------------------------------------------------


def pan(k=3.1, dk=8.0):
    """An M4 pan head 8 across and 3.1 high, its top edge rounded r 1 (the crown),
    a cross 4.4 by 1 sunk 2 into its top; the shank r 2, 12 under z = 0."""
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    head = fillet(head.edges().sort_by(Axis.Z)[-1:], 1.0)
    cross = Pos(0, 0, k - 1) * (Box(4.4, 1, 2.01) + Box(1, 4.4, 2.01))
    return head - cross + Pos(0, 0, -6) * Cylinder(2, 12)


def test_a_part_drawn_into_a_pan_head_s_crown_is_a_clash(engine):
    # A cover 0.5 down onto the top, its underside at z 2.6. The head's radius over
    # the fillet, u = z - 2.1 from 0 to 1, is 3 + sqrt(1 - u^2); its section's area
    # pi (10 - u^2 + 6 sqrt(1 - u^2)), from u 0.5 to 1:
    # pi [10u - u^3/3 + 3 (u sqrt(1 - u^2) + asin u)] = 20.58, less the cross's
    # 7.8 mm^2 by 0.5: 16.68 mm^3. Its widest region, the cylinder under the fillet,
    # stops at 2.1, under the cover, which used to block the driver.
    def antiderivative(u):
        return 10 * u - u**3 / 3 + 3 * (u * math.sqrt(1 - u**2) + math.asin(u))

    volume = math.pi * (antiderivative(1.0) - antiderivative(0.5)) - 7.8 * 0.5
    cover = Pos(0, 0, 2.6 + 2) * Box(20, 20, 4)
    rule = {"parts": "screw", "kind": "screw", "head": "phillips", "size": "M4"}
    result = run([("plate", plate()), ("screw", pan()), ("cover", cover)], rule, engine)
    assert result.reason == clash("cover", volume)
    assert f"{volume:.1f}" == "16.7"


# ---------------------------------------------------------------------------
# A countersunk head's cone, and its thread.
# ---------------------------------------------------------------------------


def countersunk():
    """An M6 countersunk head, 90 degrees: a cone from r 3 at z -3 to r 6 at z 0,
    no socket drawn; the shank r 3, 12 long under it."""
    return Pos(0, 0, -1.5) * Cone(3, 6, 3) + Pos(0, 0, -9) * Cylinder(3, 12)


FLAT = {"parts": "screw", "kind": "screw", "head": "flat", "size": "M6"}


def counterbored_block(bore, ceiling=1.0):
    """A block round the screw: a counterbore r ``bore`` from z -3 to the head's top,
    a pocket r 8 over it ``ceiling`` high and closed, so no key gets in; under the
    counterbore a hole tapped at the minor (r 2.46) for the shank."""
    block = Pos(0, 0, -6) * Box(40, 40, 30)
    block -= Pos(0, 0, -1.5) * Cylinder(bore, 3)
    block -= Pos(0, 0, ceiling / 2) * Cylinder(8, ceiling)
    return block - Pos(0, 0, -12) * Cylinder(4.917 / 2, 18)


@pytest.mark.parametrize(
    ("bore", "told"),
    [
        # A counterbore r 5 where the cone runs out to 6: the cone over r 5, z -1 to
        # 0, pi [(z + 6)^3 / 3 - 25 z] from -1 to 0 = pi (72 - 66.67) = 16.76 mm^3.
        (5.0, "16.8"),
        # r 3.5, half a millimetre over the shank: the cone over it from z -2.5,
        # pi [72 - (3.5^3 / 3 + 12.25 * 2.5)] = 85.08, all of it past the shank.
        (3.5, "85.1"),
    ],
)
def test_a_countersunk_head_s_cone_is_measured(engine, bore, told):
    # The shank's thread in the tapped hole, 12 long, isn't added.
    volume = math.pi * (6**3 / 3 - (bore**3 / 3 + bore**2 * (6 - bore)))
    result = run([("screw", countersunk()), ("block", counterbored_block(bore))], FLAT, engine)
    assert result.reason == clash("block", volume)
    assert f"{volume:.1f}" == told


def test_a_countersunk_screw_s_thread_is_no_clash(engine):
    # A counterbore r 6.1, clear of the cone: only the thread, drawn at the nominal
    # in a hole drawn at the minor, is in common. It used to be measured: the cone's
    # rim is too thin to be a region, and the whole screw stood in for it.
    result = run([("screw", countersunk()), ("block", counterbored_block(6.1))], FLAT, engine)
    assert (result.verdict, result.reason) == (Verdict.BLOCKED, None)
    assert result.blockers == ("block",)


# ---------------------------------------------------------------------------
# What stays out: a shoulder, which is shank.
# ---------------------------------------------------------------------------


def test_a_shoulder_is_shank_and_stays_out():
    # ISO 7379 M6 on an 8 mm shoulder: a head 13 by 5.5, the shoulder r 4 for 10
    # under it, the thread r 3 for 9 under that. Its hole drawn tight, r 3.9: pi
    # (16 - 15.21) 10 = 24.8 mm^3 of shoulder in common. A shoulder is no head: the
    # shank's widest radius sets what is left out. The block is closed 0.5 over the
    # head, in a pocket r 8, so the block itself stops the key and is asked.
    screw = Pos(0, 0, 2.75) * Cylinder(6.5, 5.5) - hexagon(4, 3.01, 2.5)
    screw += Pos(0, 0, -5) * Cylinder(4, 10) + Pos(0, 0, -14.5) * Cylinder(3, 9)
    block = Pos(0, 0, -5) * Box(40, 40, 30) - Pos(0, 0, 3) * Cylinder(8, 6)
    block -= Pos(0, 0, -5) * Cylinder(3.9, 10.01) + Pos(0, 0, -15) * Cylinder(2.46, 10.01)
    rule = {"parts": "screw", "kind": "screw", "head": "shoulder", "size": "M6"}
    result = run([("screw", screw), ("block", block)], rule)
    assert (result.verdict, result.reason) == (Verdict.BLOCKED, None)
    assert result.blockers == ("block",)
