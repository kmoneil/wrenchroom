"""Fastener and furniture builders for the golden bench (GOLDEN-BENCH.md section 4).

Standard proportions, threads not modelled, all dimensions mm. Everything here is
generic: round numbers and ISO/DIN proportions, never anybody's design.
"""

import math

from build123d import Axis, Box, Cylinder, Pos, RegularPolygon, Rot, extrude, fillet

R3 = math.sqrt(3)


def hex_prism(af, h, z0=0.0):
    return Pos(0, 0, z0) * extrude(RegularPolygon(af / R3, 6), h)


def socket_screw(d=6, length=20, dk=10, k=6, s=5, t=3):
    """ISO 4762-ish: shank below z = 0, head above, hex socket in the top."""
    shank = Pos(0, 0, -length / 2) * Cylinder(d / 2, length)
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    return shank + head - hex_prism(s, t + 0.01, k - t)


def button_screw(d=6, length=16, dk=10.5, k=3.3, s=4, t=2.3):
    """ISO 7380-1-ish button head, top edge rounded."""
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    head = fillet(head.edges().sort_by(Axis.Z)[-1:], 1.5)
    shank = Pos(0, 0, -length / 2) * Cylinder(d / 2, length)
    return head + shank - hex_prism(s, t + 0.01, k - t)


def pan_phillips(d=4, length=12, dk=8, k=3.1):
    """ISO 7045-ish pan head with a PH2 cross recess."""
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    head = fillet(head.edges().sort_by(Axis.Z)[-1:], 1.0)
    shank = Pos(0, 0, -length / 2) * Cylinder(d / 2, length)
    cross = Pos(0, 0, k - 1) * (Box(4.4, 1, 2.01) + Box(1, 4.4, 2.01))
    return head + shank - cross


def hex_bolt(d, length, s, k):
    """ISO 4017-ish: head on z = 0..k, shank hanging below."""
    return hex_prism(s, k) + Pos(0, 0, -length / 2) * Cylinder(d / 2, length)


def hex_nut(d, s, m):
    """ISO 4032-ish: body on z = 0..m, bored through."""
    return hex_prism(s, m) - Cylinder(d / 2, 4 * m)


def carriage_bolt(d=6, length=20, dk=16, k=3.9, v=6, f=4):
    """DIN 603-ish: dome, square neck, shank."""
    dome = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    dome = fillet(dome.edges().sort_by(Axis.Z)[-1:], 3.0)
    neck = Pos(0, 0, -f / 2) * Box(v, v, f)
    shank = Pos(0, 0, -f - (length - f) / 2) * Cylinder(d / 2, length - f)
    return dome + neck + shank


def gland(af=24, h=8, dome_r=10, dome_h=14, stub_r=10, stub_h=12, bore=4.5):
    """A generic M20-class cable gland: hex on the wall, dome above, stub below."""
    body = hex_prism(af, h)
    dome = Pos(0, 0, h + dome_h / 2) * Cylinder(dome_r, dome_h)
    dome = fillet(dome.edges().sort_by(Axis.Z)[-1:], 3.0)
    stub = Pos(0, 0, -stub_h / 2) * Cylinder(stub_r, stub_h)
    return body + dome + stub - Pos(0, 0, 5) * Cylinder(bore, 100)


def plate(w=200, d=200, t=10, holes=(), z_top=0.0):
    """A base plate with its top face at z_top and through-holes where asked."""
    p = Pos(0, 0, z_top - t / 2) * Box(w, d, t)
    for x, y, r in holes:
        p = p - Pos(x, y, z_top - t / 2) * Cylinder(r, t + 1)
    return p


def slab(z_bottom, w=300, d=300, t=10):
    """A ceiling, wall-above or shelf: a flat slab whose underside is z_bottom."""
    return Pos(0, 0, z_bottom + t / 2) * Box(w, d, t)


def slot_block(z0, z1, pocket_r, half_width, edge=60.0, size=120.0):
    """A block with a round pocket about the axis and one slot out to its edge.

    The slot's half-width sets the handle swing it leaves free: a handle of
    half-width w clears when h = w + edge * tan(W / 2) (GOLDEN-BENCH section 4).
    """
    h = z1 - z0
    blk = Pos(0, 0, z0 + h / 2) * Box(size, size, h)
    blk = blk - Pos(0, 0, z0 + h / 2) * Cylinder(pocket_r, h + 1)
    return blk - Pos(edge / 2 + 1, 0, z0 + h / 2) * Box(edge + 2, 2 * half_width, h + 1)


def state_lever_raised():
    """The state_lever cell's bar in its other position: swung 80 deg up about
    a pivot at (-100, 0, 26) in cell coordinates."""
    return Pos(-100, 0, 26) * Rot(0, -80, 0) * Pos(100, 0, 0) * Box(220, 30, 10)
