"""Fasteners from geometry (spec 7.2): what a named part's solid shows.

Every builder is read as built and again in seeded random poses far from the
origin; the readings must not move. Sizes and drives come from the standard
tables, never from the reader's own output.
"""

import math

import numpy as np
import pytest
from build123d import (
    Axis,
    Box,
    Cone,
    Cylinder,
    Location,
    Plane,
    Pos,
    RegularPolygon,
    Sphere,
    extrude,
    fillet,
)

import fixture_models as fm
from wrenchroom.detect.geometry import SIZE_SNAP_MM, read_shape
from wrenchroom.fasteners import (
    BUTTON_KEY_AF,
    HEX_AF,
    SOCKET_KEY_AF,
    Head,
    Kind,
    Size,
)

S, N = Kind.SCREW, Kind.NUT
R3 = math.sqrt(3)


def hex_prism(af, h, z0=0.0):
    return Pos(0, 0, z0) * extrude(RegularPolygon(af / R3, 6), h)


def socket_screw(size, length=20.0, pocket=True, shank=None):
    """ISO 4762 proportions (head dk = 1.5 d + 1, k = d), the table's key.

    ``shank`` draws the shank at another diameter (a thread's minor diameter).
    """
    d = Size.parse(size).diameter_mm
    dk, k, s = 1.5 * d + 1, d, SOCKET_KEY_AF[size]
    body = Pos(0, 0, -length / 2) * Cylinder((shank or d) / 2, length)
    screw = body + Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    return screw - hex_prism(s, k / 2 + 0.01, k / 2) if pocket else screw


def button_screw(size, length=16.0):
    d = Size.parse(size).diameter_mm
    dk, k, s = 1.75 * d, 0.55 * d, BUTTON_KEY_AF[size]
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    head = fillet(head.edges().sort_by(Axis.Z)[-1:], k * 0.45)
    return (
        head + Pos(0, 0, -length / 2) * Cylinder(d / 2, length) - hex_prism(s, k / 2 + 0.01, k / 2)
    )


def flat_screw(d=6.0, length=20.0, dk=12.0, s=4.0):
    """ISO 10642-ish: a 90 degree cone head, wide end up, hex socket in it."""
    k = (dk - d) / 2
    head = Pos(0, 0, k / 2) * Cone(d / 2, dk / 2, k)
    return (
        head + Pos(0, 0, -length / 2) * Cylinder(d / 2, length) - hex_prism(s, k / 2 + 0.01, k / 2)
    )


def slotted_screw(d=5.0, length=16.0, dk=8.5, k=3.3, width=1.2):
    """ISO 1207-ish cheese head with a slot running right across it."""
    screw = Pos(0, 0, -length / 2) * Cylinder(d / 2, length) + Pos(0, 0, k / 2) * Cylinder(
        dk / 2, k
    )
    return screw - Pos(0, 0, k - 0.8) * Box(dk + 2, width, 1.61)


def hex_bolt(size, length=25.0):
    d = Size.parse(size).diameter_mm
    return hex_prism(HEX_AF[size], 0.65 * d) + Pos(0, 0, -length / 2) * Cylinder(d / 2, length)


def hex_nut(size):
    d = Size.parse(size).diameter_mm
    return hex_prism(HEX_AF[size], 0.85 * d) - Cylinder(d / 2, 4 * d)


SOCKET_SIZES = ["M3", "M4", "M5", "M6", "M8", "M10", "M12"]
HEX_SIZES = ["M5", "M6", "M8", "M10", "M12", "M16", "M20", "M24"]


@pytest.mark.parametrize("size", SOCKET_SIZES)
def test_a_socket_head_shows_its_key_and_its_shank(size):
    reading = read_shape(socket_screw(size), S)
    assert reading.head is Head.SOCKET
    assert reading.drive_af == pytest.approx(SOCKET_KEY_AF[size])
    assert reading.size.designation == size


@pytest.mark.parametrize("size", ["M5", "M6", "M8", "M10"])
def test_a_button_head_is_low_and_rounded(size):
    reading = read_shape(button_screw(size), S)
    assert reading.head is Head.BUTTON
    assert reading.drive_af == pytest.approx(BUTTON_KEY_AF[size])


def test_a_cone_head_with_a_socket_is_flat():
    reading = read_shape(flat_screw(), S)
    assert (reading.head, reading.drive_af, reading.size.designation) == (Head.FLAT, 4.0, "M6")


@pytest.mark.parametrize("size", HEX_SIZES)
def test_a_hex_head_shows_its_across_flats(size):
    reading = read_shape(hex_bolt(size), S)
    assert reading.head is Head.HEX
    assert reading.drive_af == pytest.approx(HEX_AF[size])
    assert reading.size.designation == size


@pytest.mark.parametrize("size", HEX_SIZES)
def test_a_nut_shows_its_hex_and_its_bore(size):
    reading = read_shape(hex_nut(size), N)
    assert reading.head is None  # a nut has no head
    assert reading.drive_af == pytest.approx(HEX_AF[size])
    assert reading.size.designation == size


def cross(arm=4.4, width=1.0, depth=2.0, top=3.1):
    """A cross recess: two slots at right angles, sunk ``depth`` from ``top``."""
    return Pos(0, 0, top - depth / 2) * (
        Box(arm, width, depth + 0.01) + Box(width, arm, depth + 0.01)
    )


def pan_phillips(d=4.0, length=12.0, dk=8.0, k=3.1):
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    head = fillet(head.edges().sort_by(Axis.Z)[-1:], 1.0)
    return head + Pos(0, 0, -length / 2) * Cylinder(d / 2, length) - cross(top=k)


def countersunk_phillips(d=4.0, length=12.0, dk=8.0):
    k = (dk - d) / 2
    head = Pos(0, 0, k / 2) * Cone(d / 2, dk / 2, k)
    return head + Pos(0, 0, -length / 2) * Cylinder(d / 2, length) - cross(top=k, depth=1.5)


def test_a_cross_recess_is_phillips():
    reading = read_shape(pan_phillips(), S)
    assert (reading.head, reading.drive_af, reading.size.designation) == (Head.PHILLIPS, None, "M4")


def test_a_cross_outranks_a_countersunk_outline():
    # ISO 7046: a countersunk head, driven by a Phillips driver, not a hex key.
    assert read_shape(countersunk_phillips(), S).head is Head.PHILLIPS


def test_a_cross_of_unequal_arms_is_not_a_cross():
    # One long slot crossed by a short one: the narrowest walls face one way.
    odd = Pos(0, 0, -6) * Cylinder(2, 12) + Pos(0, 0, 1.55) * Cylinder(4, 3.1)
    odd = odd - Pos(0, 0, 2.1) * (Box(6.0, 1.0, 2.01) + Box(1.6, 3.0, 2.01))
    assert read_shape(odd, S).head is not Head.PHILLIPS


def test_a_slot_across_the_head_is_slotted():
    assert read_shape(slotted_screw(), S).head is Head.SLOTTED


def test_a_head_with_no_drive_modelled_is_only_a_guess():
    plain = read_shape(socket_screw("M6", pocket=False), S)
    assert plain.head is None
    assert plain.head_guess is Head.SOCKET
    assert plain.drive_af is None
    assert plain.size.designation == "M6"


#: ISO 261 minor (root) diameters of external threads, mm: what some models draw.
MINOR = {"M3": 2.387, "M4": 3.242, "M5": 4.134, "M6": 4.917, "M8": 6.647, "M10": 8.376}


@pytest.mark.parametrize("size", sorted(MINOR))
def test_a_modelled_socket_names_the_size_whatever_the_shank(size):
    # Drawn at its minor diameter, an M5's shank is 0.03 from #8 and an M6's
    # 0.08 from M5: the key the socket takes settles it.
    assert read_shape(socket_screw(size, shank=MINOR[size]), S).size.designation == size


@pytest.mark.parametrize("size", HEX_SIZES)
def test_a_nut_with_a_tapped_bore_is_sized_by_its_hex(size):
    d = Size.parse(size).diameter_mm
    tapped = hex_prism(HEX_AF[size], 0.85 * d) - Cylinder(0.84 * d / 2, 4 * d)
    assert read_shape(tapped, N).size.designation == size


@pytest.mark.parametrize("size", ["M16", "M18"])
def test_a_shared_key_size_is_settled_by_the_shank(size):
    # ISO 4762: a 14 mm key fits both M16 and M18; the shank tells them apart.
    assert SOCKET_KEY_AF["M16"] == SOCKET_KEY_AF["M18"] == 14.0
    assert read_shape(socket_screw(size), S).size.designation == size


def test_a_shared_key_size_with_no_shank_to_tell_is_no_size():
    assert read_shape(socket_screw("M16", shank=13.0), S).size is None


def test_a_pocketless_shank_at_its_minor_diameter_can_mislead():
    # The limit, said plainly: with no drive modelled, an M5 drawn at its minor
    # diameter (4.134) sits 0.03 from #8 and reads as #8. A size in the name is
    # the remedy, and the wiring must let it stand against this.
    assert read_shape(Cylinder(MINOR["M5"] / 2, 20), S).size.designation == "#8"
    assert read_shape(Cylinder(MINOR["M6"] / 2, 20), S).size is None


@pytest.mark.parametrize(
    ("diameter", "expected"),
    [
        (6.0, "M6"),
        (6.0 + SIZE_SNAP_MM * 0.9, "M6"),
        (6.0 - SIZE_SNAP_MM * 0.9, "M6"),
        (6.0 + SIZE_SNAP_MM * 1.1, None),
        (4.5, None),
        (6.35, "1/4"),
        (4.826, "#10"),
        (7.938, "5/16"),
        (8.0, "M8"),
    ],
)
def test_the_snap_window(diameter, expected):
    reading = read_shape(Cylinder(diameter / 2, 20), S)
    got = reading.size.designation if reading.size else None
    assert got == expected


def test_shapes_with_no_round_face_say_nothing():
    for shape in (Box(10, 10, 10), hex_prism(10, 5)):
        assert read_shape(shape, S).axis is None


def test_a_ball_says_nothing():
    reading = read_shape(Sphere(5), S)
    assert reading.head is None
    assert reading.drive_af is None


# ---------------------------------------------------------------------------
# Pose: the reading is the solid's, not its placement's.
# ---------------------------------------------------------------------------


def _poses(count, seed):
    rng = np.random.default_rng(seed)
    poses = []
    for _ in range(count):
        z = rng.normal(size=3)
        z /= np.linalg.norm(z)
        origin = tuple(float(c) for c in rng.uniform(-2e4, 2e4, size=3))
        poses.append(Location(Plane(origin=origin, z_dir=tuple(float(c) for c in z))))
    return poses


POSED = [
    ("socket M6", lambda: socket_screw("M6"), S),
    ("button M8", lambda: button_screw("M8"), S),
    ("flat M6", flat_screw, S),
    ("hex M10", lambda: hex_bolt("M10"), S),
    ("nut M12", lambda: hex_nut("M12"), N),
    ("slotted", slotted_screw, S),
    ("fixture nut", fm.hex_nut, N),
]


@pytest.mark.parametrize(("label", "build", "kind"), POSED, ids=[p[0] for p in POSED])
def test_a_reading_does_not_depend_on_pose(label, build, kind):
    shape = build()
    home = read_shape(shape, kind)
    for pose in _poses(8, seed=4017):
        moved = read_shape(pose * shape, kind)
        assert (moved.head, moved.head_guess, moved.size) == (
            home.head,
            home.head_guess,
            home.size,
        ), label
        assert (
            moved.drive_af == pytest.approx(home.drive_af, abs=1e-6)
            if home.drive_af
            else moved.drive_af is None
        )
        trsf = pose.wrapped.Transformation()
        carried = np.array([trsf.Value(row, 3) for row in (1, 2, 3)])  # where +Z went
        assert abs(abs(float(np.array(moved.axis) @ carried)) - 1) < 1e-9, label
