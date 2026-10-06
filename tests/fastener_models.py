"""Fastener solids at standard proportions, for the detection tests.

Built from the standards tables (ISO 4762 key, ISO 4032 across-flats...) so a test
compares a reading against the table, never against the reader's own output.
"""

import math

from build123d import Axis, Box, Cone, Cylinder, Pos, RegularPolygon, extrude, fillet

from wrenchroom.fasteners import BUTTON_KEY_AF, HEX_AF, SOCKET_KEY_AF, Size

R3 = math.sqrt(3)

#: ISO 261 minor (root) diameters of external threads, mm: what some models draw.
MINOR = {"M3": 2.387, "M4": 3.242, "M5": 4.134, "M6": 4.917, "M8": 6.647, "M10": 8.376}


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
