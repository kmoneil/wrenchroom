"""Small analytic assemblies with hand-computable answers, shared across tests.

Everything is built here rather than stored as binary fixtures: a STEP file in the
repo can drift from the numbers a test claims about it, a builder cannot. Tests
that need a real file export one of these to tmp_path.
"""

import math

from build123d import Box, Cylinder, Pos, RegularPolygon, Rot, extrude

from wrenchroom.assembly import Assembly, Part

#: M6 socket head proportions, mm: shank r3 x 20, head r5.5 x 6 (ISO 4762-ish).
SHANK_RADIUS = 3.0
SHANK_LENGTH = 20.0
HEAD_RADIUS = 5.5
HEAD_HEIGHT = 6.0

#: The M6 nut: across flats 10, height 5.
NUT_AF = 10.0
NUT_HEIGHT = 5.0


def socket_screw(length=SHANK_LENGTH):
    """An M6 socket head screw standing head-up: seat at length + 6, axis +z."""
    shank = Pos(0, 0, length / 2) * Cylinder(SHANK_RADIUS, length)
    head = Pos(0, 0, length + HEAD_HEIGHT / 2) * Cylinder(HEAD_RADIUS, HEAD_HEIGHT)
    return shank + head


SEAT_Z = SHANK_LENGTH + HEAD_HEIGHT


def screw_facing_wall(gap, length=SHANK_LENGTH):
    """A wall `gap` mm above the screw's head."""
    wall = Pos(0, 0, length + HEAD_HEIGHT + gap + 5) * Box(400, 400, 10)
    return Assembly([Part("bolt", socket_screw(length)), Part("wall", wall)])


def hex_nut():
    """An M6 hex nut, af 10, sitting on z = 0..5 with its bore vertical."""
    hexagon = RegularPolygon(NUT_AF / math.sqrt(3), 6)
    return extrude(hexagon, NUT_HEIGHT) - Cylinder(3.0, 4 * NUT_HEIGHT)


def nut_on_plate():
    """The nut on a plate: the free face is up, the plate rules the bottom out."""
    plate = Pos(0, 0, -5) * Box(200, 200, 10)
    return Assembly([Part("nut", hex_nut()), Part("plate", plate)])


def hex_bolt(d, length, af, head_h):
    """A hex head bolt, head on z = 0..head_h, shank hanging below."""
    hexagon = RegularPolygon(af / math.sqrt(3), 6)
    return extrude(hexagon, head_h) + Pos(0, 0, -length / 2) * Cylinder(d / 2, length)


def nut_with_bolt_through(af=10.0, nut_h=5.2, bolt_d=6.0, bolt_len=20.0):
    """Bug A's shape: a plate, a bolt up through it, the nut on top with the
    bolt's end sticking out of its free face."""
    plate = Pos(0, 0, -5) * Box(200, 200, 10) - Cylinder(bolt_d / 2 + 0.5, 11)
    bolt = Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(bolt_d, bolt_len, 10, 4.0)
    hexagon = RegularPolygon(af / math.sqrt(3), 6)
    nut = extrude(hexagon, nut_h) - Cylinder(bolt_d / 2, 4 * nut_h)
    return Assembly([Part("plate", plate), Part("bolt", bolt), Part("nut", nut)])


def gland(af=24.0, hex_h=8.0, dome_r=10.0, dome_h=14.0, stub_r=10.0, stub_h=12.0):
    """Bug B and C's shape: a cable gland, hex between a dome above and a
    thread stub below, bored through."""
    hexagon = RegularPolygon(af / math.sqrt(3), 6)
    body = extrude(hexagon, hex_h)
    dome = Pos(0, 0, hex_h + dome_h / 2) * Cylinder(dome_r, dome_h)
    stub = Pos(0, 0, -stub_h / 2) * Cylinder(stub_r, stub_h)
    return body + dome + stub - Pos(0, 0, 5) * Cylinder(4.5, 100)


def gland_on_wall(rib=False):
    """The gland through a wall, optionally with a rib beside its hex (bug C:
    the ring must be placed on the hex band, where the rib is in the way)."""
    wall = Pos(0, 0, -5) * Box(200, 200, 10) - Cylinder(10.2, 11)
    parts = [Part("gland", gland()), Part("wall", wall)]
    if rib:
        parts.append(Part("rib", Pos(22, 0, 3) * Box(12, 80, 6)))
    return Assembly(parts)


def slotted_pocket(half_angle_deg, z0, z1, pocket_r=16.0, edge=60.0, arm_half_width=6.85):
    """A block with a round pocket about the axis and one slot out to its edge,
    sized to leave an arm of the given half-width `2 * half_angle_deg` of swing
    (default: a 13 af spanner handle's half-width)."""
    half_width = arm_half_width + edge * math.tan(math.radians(half_angle_deg))
    h = z1 - z0
    blk = Pos(0, 0, z0 + h / 2) * Box(120, 120, h)
    blk = blk - Pos(0, 0, z0 + h / 2) * Cylinder(pocket_r, h + 1)
    return blk - Pos(edge / 2 + 1, 0, z0 + h / 2) * Box(edge + 2, 2 * half_width, h + 1)


def bolt_with_slotted_nut(head_boxed=False):
    """An M8 bolt down through two plates; its nut below in a slotted pocket that
    lets a ring hold (~22 deg) but never turn, with a floor too close for sockets.
    With head_boxed the head sits in the same kind of pocket under a lid, so
    neither side can turn."""
    nut_face = -10 - 6.8
    pocket = slotted_pocket(11, nut_face - 12, -10)
    pocket = pocket + Pos(0, 0, nut_face - 12 - 5) * Box(120, 120, 10)
    parts = [
        Part("upper", Pos(0, 0, -2.5) * Box(200, 200, 5) - Cylinder(4.5, 12)),
        Part("lower", Pos(0, 0, -7.5) * Box(200, 200, 5) - Cylinder(4.5, 12)),
        Part("bolt", hex_bolt(8.0, 25.0, 13.0, 5.3)),
        Part("nut", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_nut_shape(8.0, 13.0, 6.8)),
        Part("pocket", pocket),
    ]
    if head_boxed:
        high = slotted_pocket(11, 0, 5.3 + 12) + Pos(0, 0, 5.3 + 12 + 5) * Box(120, 120, 10)
        parts.append(Part("pocket_high", high))
    return Assembly(parts)


def hex_nut_shape(d, af, m):
    """An ISO 4032-ish nut solid on z = 0..m."""
    hexagon = RegularPolygon(af / math.sqrt(3), 6)
    return extrude(hexagon, m) - Cylinder(d / 2, 4 * m)
