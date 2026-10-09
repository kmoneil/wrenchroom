"""Fastener and furniture builders for the golden bench.

Standard proportions, threads not modelled, all dimensions mm. Everything here is
generic: round numbers and ISO/DIN proportions, never anybody's design.
"""

import math

from build123d import Axis, Box, Cone, Cylinder, Pos, RegularPolygon, Rot, Sphere, extrude, fillet

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


def pan_phillips(d=4, length=12, dk=8, k=3.1, span=4.4):
    """ISO 7045-ish pan head with a cross recess ``span`` across: PH2's, an M4's, unless
    said (the span picks the driver, issue #125)."""
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    head = fillet(head.edges().sort_by(Axis.Z)[-1:], 1.0)
    shank = Pos(0, 0, -length / 2) * Cylinder(d / 2, length)
    cross = Pos(0, 0, k - 1) * (Box(span, 1, 2.01) + Box(1, span, 2.01))
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
    half-width w clears when h = w + edge * tan(W / 2).
    """
    h = z1 - z0
    blk = Pos(0, 0, z0 + h / 2) * Box(size, size, h)
    blk = blk - Pos(0, 0, z0 + h / 2) * Cylinder(pocket_r, h + 1)
    return blk - Pos(edge / 2 + 1, 0, z0 + h / 2) * Box(edge + 2, 2 * half_width, h + 1)


def state_lever_raised():
    """The state_lever cell's bar in its other position: swung 80 deg up about
    a pivot at (-100, 0, 26) in cell coordinates."""
    return Pos(-100, 0, 26) * Rot(0, -80, 0) * Pos(100, 0, 0) * Box(220, 30, 10)


# ---------------------------------------------------------------------------
# Fasteners as makers' models draw them (issue #81): every edge a tool or a
# thread meets is chamfered, a socket's mouth is countersunk and its bottom is
# the drill's point. Each of those is a cone, and none is a countersunk head.
# ISO dimensions throughout: ISO 4762's head (dk, k) and key, ISO 7380-1's,
# ISO 10642's.
# ---------------------------------------------------------------------------

#: The makers' builders' sizes, mm: ISO 4762's and ISO 7380-1's (d, dk, k, s, t).
VENDOR_SOCKET = {
    "M2": (2.0, 3.8, 2.0, 1.5, 1.0),  # issue #83
    "#0": (0.060 * 25.4, 0.096 * 25.4, 0.060 * 25.4, 0.050 * 25.4, 0.025 * 25.4),  # ASME B18.3
    "M3": (3.0, 5.5, 3.0, 2.5, 1.3),
    "M4": (4.0, 7.0, 4.0, 3.0, 2.0),
    "M5": (5.0, 8.5, 5.0, 4.0, 2.5),
    "M6": (6.0, 10.0, 6.0, 5.0, 3.0),
    "M8": (8.0, 13.0, 8.0, 6.0, 4.0),
    "M10": (10.0, 16.0, 10.0, 8.0, 5.0),
}
VENDOR_BUTTON = {
    "#0": (0.060 * 25.4, 0.114 * 25.4, 0.032 * 25.4, 0.035 * 25.4, 0.020 * 25.4),  # issue #83
    "M3": (3.0, 5.7, 1.65, 2.0, 1.04),
    "M4": (4.0, 7.6, 2.2, 2.5, 1.3),
    "M5": (5.0, 9.5, 2.75, 3.0, 1.56),
    "M6": (6.0, 10.5, 3.3, 4.0, 2.08),
    "M8": (8.0, 14.0, 4.4, 5.0, 2.6),
}
#: ISO 10642's (d, dk, s, t): dk about 2 d, the head's height the countersink's.
VENDOR_FLAT = {
    "M2": (2.0, 4.0, 1.3, 0.8),  # ISO 10642:2019's M2, its 1.3 key (issue #83)
    "M3": (3.0, 6.0, 2.0, 1.1),
    "M4": (4.0, 8.0, 2.5, 1.5),
    "M5": (5.0, 10.0, 3.0, 1.9),
    "M6": (6.0, 12.0, 4.0, 2.2),
    "M8": (8.0, 16.0, 5.0, 3.0),
}


def _chamfered_shank(d, length, tip):
    """The shank below z = 0, its tip chamfered ``tip`` mm at 45 degrees."""
    shank = Pos(0, 0, -(length - tip) / 2) * Cylinder(d / 2, length - tip)
    return shank + Pos(0, 0, -length + tip / 2) * Cone(d / 2 - tip, d / 2, tip)


def _drilled_socket(s, t, top, mouth):
    """A hex socket ``t`` deep from ``top``: mouth countersunk, bottom the drill's point.

    The drill is about the key's width; its point is ISO's 118 degrees.
    """
    point = (s / 2) / math.tan(math.radians(59))
    socket = hex_prism(s, t + 0.01, top - t)
    socket += Pos(0, 0, top - t - point / 2) * Cone(0, s / 2, point)
    corner = s / R3
    return socket + Pos(0, 0, top - mouth / 2 + 0.005) * Cone(corner, corner + mouth, mouth + 0.01)


def vendor_socket_screw(size, length=12.0, key=None):
    """An ISO 4762 head as a maker draws it: chamfered top and under-head edges.

    ``key`` draws its socket for another key than ISO 4762's.
    """
    d, dk, k, s, t = VENDOR_SOCKET[size]
    s = key or s
    edge = round(0.03 * dk, 2)
    head = Pos(0, 0, edge / 2) * Cone(dk / 2 - edge, dk / 2, edge)
    head += Pos(0, 0, k / 2) * Cylinder(dk / 2, k - 2 * edge)
    head += Pos(0, 0, k - edge / 2) * Cone(dk / 2, dk / 2 - edge, edge)
    screw = head + _chamfered_shank(d, length, 0.15 * d)
    return screw - _drilled_socket(s, t, k, 0.1 * s)


def vendor_button_screw(size, length=12.0):
    """An ISO 7380-1 head as a maker draws it: a spherical dome on a short band.

    The dome is cut flat round the socket, a ring smaller than the chamfered
    tip's end face: the larger flat end is the tip, not the head.
    """
    d, dk, k, s, t = VENDOR_BUTTON[size]
    mouth = 0.05 * s
    band, top = 0.15 * k, s / R3 + mouth + 0.25  # the band's height, the flat ring's radius
    # The sphere through the band's rim and the flat ring's edge, centred on the axis.
    centre = ((dk / 2) ** 2 + band**2 - top**2 - k**2) / (2 * (band - k))
    sphere = Pos(0, 0, centre) * Sphere(math.hypot(dk / 2, band - centre))
    dome = sphere & Pos(0, 0, (band + k) / 2) * Cylinder(dk / 2, k - band)
    head = Pos(0, 0, band / 2) * Cylinder(dk / 2, band) + dome
    screw = head + _chamfered_shank(d, length, 0.07 * d)
    return screw - _drilled_socket(s, t, k, mouth)


def vendor_flat_screw(size, length=12.0):
    """An ISO 10642 head as a maker draws it: a 90 degree countersink under a rim band."""
    d, dk, s, t = VENDOR_FLAT[size]
    rim, cone = 0.05 * dk, (dk - d) / 2  # the countersink's height, at 90 degrees
    head = Pos(0, 0, cone / 2) * Cone(d / 2, dk / 2, cone)
    head += Pos(0, 0, cone + rim / 2) * Cylinder(dk / 2, rim)
    screw = head + _chamfered_shank(d, length, 0.15 * d)
    return screw - _drilled_socket(s, t, cone + rim, 0.1 * s)


def set_screw(d=3.0, length=4.0, s=1.5, t=1.5):
    """ISO 4026-ish: no head, the socket in its top at z = 0, the body below."""
    return Pos(0, 0, -length / 2) * Cylinder(d / 2, length) - hex_prism(s, t + 0.01, -t)


def thumb_screw(dk=8.0, k=3.0, d=3.0, length=10.0):
    """A knurled-head thumb screw, drawn plain: a disc on z = 0..k over the shank."""
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k)
    return head + Pos(0, 0, -length / 2) * Cylinder(d / 2, length)


def wing_nut(d=6.0, hub=10.0, height=6.0, span=22.0, wing=2.5):
    """A DIN 315-ish wing nut on z = 0..height: a hub bored ``d``, two wings ``span`` across."""
    body = Pos(0, 0, height / 2) * Cylinder(hub / 2, height)
    body += Pos(0, 0, height / 2 + 0.5) * Box(span, wing, height - 1)
    return body - Pos(0, 0, height / 2) * Cylinder(d / 2, height + 1)
