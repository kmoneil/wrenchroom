"""Small analytic assemblies with hand-computable answers, shared across tests.

Everything is built here rather than stored as binary fixtures: a STEP file in the
repo can drift from the numbers a test claims about it, a builder cannot. Tests
that need a real file export one of these to tmp_path.
"""

import math

from build123d import Box, Cylinder, Pos, RegularPolygon, extrude

from wrenchroom.assembly import Assembly, Part

#: M6 socket head proportions, mm: shank r3 x 20, head r5.5 x 6 (ISO 4762-ish).
SHANK_RADIUS = 3.0
SHANK_LENGTH = 20.0
HEAD_RADIUS = 5.5
HEAD_HEIGHT = 6.0

#: The M6 nut: across flats 10, height 5.
NUT_AF = 10.0
NUT_HEIGHT = 5.0


def socket_screw():
    """An M6 socket head screw standing head-up: seat at z = 26, axis +z."""
    shank = Pos(0, 0, SHANK_LENGTH / 2) * Cylinder(SHANK_RADIUS, SHANK_LENGTH)
    head_z = SHANK_LENGTH + HEAD_HEIGHT / 2
    head = Pos(0, 0, head_z) * Cylinder(HEAD_RADIUS, HEAD_HEIGHT)
    return shank + head


SEAT_Z = SHANK_LENGTH + HEAD_HEIGHT


def screw_facing_wall(gap):
    """A wall `gap` mm above the screw's head."""
    wall = Pos(0, 0, SEAT_Z + gap + 5) * Box(400, 400, 10)
    return Assembly([Part("bolt", socket_screw()), Part("wall", wall)])


def hex_nut():
    """An M6 hex nut, af 10, sitting on z = 0..5 with its bore vertical."""
    hexagon = RegularPolygon(NUT_AF / math.sqrt(3), 6)
    return extrude(hexagon, NUT_HEIGHT) - Cylinder(3.0, 4 * NUT_HEIGHT)


def nut_on_plate():
    """The nut on a plate: the free face is up, the plate rules the bottom out."""
    plate = Pos(0, 0, -5) * Box(200, 200, 10)
    return Assembly([Part("nut", hex_nut()), Part("plate", plate)])
