"""A small bracket with four fasteners, two of them in trouble.

The README's worked example. Run it to write bracket.step beside it, then check it:

    python examples/bracket.py
    wrenchroom check examples/bracket.step

With --fixed it writes the bracket with both problems fixed instead.

The README's picture, docs/images/bracket-view.png, is this bracket's 3D view
(wrenchroom check examples/bracket.step --html examples/report.html), opened on
examples/report.html#rear_screw by headless Chrome at 1280 by 800.

It needs only build123d, which wrenchroom installs. Sizes are ISO's: an M6 socket
head cap screw (ISO 4762), M6 and M8 hex bolts (ISO 4017) and an M8 nut (ISO 4032).
"""

import math
import os
import sys
from pathlib import Path

from build123d import Box, Compound, Cylinder, Pos, RegularPolygon, Shape, export_step, extrude


def hex_prism(across_flats: float, height: float) -> Shape:
    """A hex standing on z = 0, its corners along x."""
    return extrude(RegularPolygon(across_flats / math.sqrt(3), 6), height)


def socket_head_screw(
    d: float = 6, length: float = 20, head_d: float = 10, head_h: float = 6, key: float = 5
) -> Shape:
    """ISO 4762: its shank down from z = 0, its head up, a hex socket in the top."""
    shank = Pos(0, 0, -length / 2) * Cylinder(d / 2, length)
    head = Pos(0, 0, head_h / 2) * Cylinder(head_d / 2, head_h)
    socket = Pos(0, 0, head_h / 2) * hex_prism(key, head_h / 2 + 0.01)
    return shank + head - socket


def hex_bolt(d: float, length: float, across_flats: float, head_h: float) -> Shape:
    """ISO 4017: its shank down from z = 0, its hex head up."""
    return Pos(0, 0, -length / 2) * Cylinder(d / 2, length) + hex_prism(across_flats, head_h)


def hex_nut(d: float, across_flats: float, height: float) -> Shape:
    """ISO 4032: a hex with a bore, standing on z = 0."""
    return hex_prism(across_flats, height) - Cylinder(d / 2, 4 * height)


def bracket(*, fixed: bool = False) -> list[tuple[str, Shape]]:
    """The parts, named as a CAD model names them; wrenchroom reads the names.

    ``fixed`` raises the shelf to 45 mm over the rear screw, room for the key's
    short leg to swing, and cuts a hole in the cover over the side bolt for it to
    come out through.
    """
    base = Pos(0, 0, -5) * Box(240, 120, 10)
    for x in (-80, -20, 40):
        base -= Pos(x, 0, -5) * Cylinder(3.3, 11)  # clearance holes for M6
    base -= Pos(90, 0, -5) * Cylinder(4.5, 11)  # and one for M8
    # A shelf 15 mm over the rear screw's head: a 5 mm key's short leg alone is 33.
    shelf = Pos(-20, 0, 6 + (45 if fixed else 15) + 3) * Box(60, 120, 6)
    # A cover 8 mm over the side bolt's head: a spanner turns it from the side, but a
    # 20 mm bolt can't come out under it.
    cover = Pos(40, 0, 4 + 8 + 3) * Box(40, 120, 6)
    if fixed:
        cover -= Pos(40, 0, 4 + 8 + 3) * Cylinder(7, 7)
    return [
        ("base", base),
        ("shelf", shelf),
        ("cover", cover),
        ("front_screw", Pos(-80, 0, 0) * socket_head_screw()),
        ("rear_screw", Pos(-20, 0, 0) * socket_head_screw()),
        ("side_bolt", Pos(40, 0, 0) * hex_bolt(6, 20, 10, 4)),
        ("clamp_bolt", Pos(90, 0, -10) * (hex_bolt(8, 30, 13, 5.3).mirror())),
        ("clamp_nut", Pos(90, 0, 0) * hex_nut(8, 13, 6.8)),
    ]


if __name__ == "__main__":
    parts = []
    for name, shape in bracket(fixed="--fixed" in sys.argv[1:]):
        shape.label = name
        parts.append(shape)
    out = Path(__file__).with_suffix(".step")
    export_step(Compound(children=parts), str(out))
    print(f"wrote {os.path.relpath(out)}")
