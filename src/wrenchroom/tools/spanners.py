"""Combination spanners: makers' lengths, and the prototype's approximations for the rest.

The lengths, full and stubby, are makers' published figures, the longest of a
few makers' standard series at each size (a longer spanner needs more room, so
the longest errs safe). The head's sizes are APPROXIMATIONS, labelled per the
project rule, carried over from the prototype or fitted to makers' heads; keep
the function signatures, since the sweep only asks for numbers by across-flats.

The one physical constant that is not approximate: a 12-point ring goes on again
every 30 degrees, so 30 degrees of free swing turns the fastener. That constant
belongs to the sweep (m1-tool-sweeps) and is stated here only so nobody tunes a
table to compensate for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import TYPE_CHECKING

from wrenchroom.tools.sizes import inch_mm, size_name
from wrenchroom.tools.sweep import (
    DEFAULT_STEP_DEG,
    Attempt,
    Mount,
    axial_annulus,
    hand_on_handle,
    radial_box,
    swing_attempt,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from wrenchroom.engine import Scene
    from wrenchroom.solids import ToolSolid


#: The ring's bore clears the hex's corners by this much, mm. Approximation.
RING_CLEARANCE = 0.3


@dataclass(frozen=True)
class Spanner:
    """One combination spanner's numbers, all mm, derived from across-flats.

    ``open_width`` is the open end's head across its jaws, ``open_thickness`` the
    open end's along the axis.
    """

    af: float
    length: float
    head_thickness: float
    ring_outer_radius: float
    handle_width: float
    open_width: float = 0.0
    open_thickness: float = 0.0
    #: The stubby's length, or None where no stubby of the size is sold.
    stubby_length: float | None = None
    #: A custom spanner's own name (tools.custom); else ``spanner-<size>``.
    name: str | None = None

    @property
    def label(self) -> str:
        """The tool's name in a report: ``spanner-13``, or a custom one's own."""
        return self.name or f"spanner-{size_name(self.af)}"


#: Full-length combination spanners' overall lengths, mm, by across-flats in mm
#: (issue #49): at each size the longest of a few makers' standard series, read
#: 2026-10-07 from the makers' pages. GW, GearWrench long pattern (gearwrench.com,
#: "Overall Length"); TK, Tekton (its metric and inch spec tables,
#: images.tekton.com); HZ, Hazet 600N and 600NA (hazet.de); P, Proto J12xx ASD
#: (protoindustrial.com). Gedore 1 B and Stahlwille 13, also read, are shorter at
#: every size (Gedore's 19 is 258, its 41 to 50 the 520 to 580 this table used to
#: hold). No full length of 5/32, 3/16 or 7/32 in is made: Facom's 39 short series
#: (fabory.com) is the longest there is. Extra-long series (Hazet 600LG) are left
#: out: nobody's set is made of them.
FULL_LENGTHS: dict[float, float] = {
    5.5: 105.0,  # HZ
    6.0: 129.5,  # TK
    7.0: 138.3,  # GW, as to 22
    8.0: 147.3,
    9.0: 158.0,
    10.0: 166.2,
    11.0: 185.2,
    12.0: 196.5,
    13.0: 206.1,
    14.0: 222.0,
    15.0: 232.0,
    16.0: 241.9,
    17.0: 259.9,
    18.0: 269.3,
    19.0: 278.6,
    20.0: 289.6,
    21.0: 300.5,
    22.0: 318.0,
    23.0: 328.0,  # HZ
    24.0: 336.6,  # GW
    25.0: 356.5,  # GW
    26.0: 364.0,  # GW
    27.0: 380.0,  # HZ
    28.0: 406.4,  # GW
    29.0: 393.7,  # TK
    30.0: 431.8,  # GW
    31.0: 429.3,  # TK
    32.0: 441.0,  # GW
    33.0: 475.0,  # TK, as to 36
    34.0: 475.0,
    35.0: 475.0,
    36.0: 510.5,
    41.0: 612.0,  # GW
    46.0: 649.0,  # GW
    50.0: 650.2,  # TK
    **{
        inch_mm(size): length
        for size, length in {
            "5/32": 77.0,  # Facom 39 short, as to 7/32
            "3/16": 82.0,
            "7/32": 84.0,
            "1/4": 129.5,  # TK
            "9/32": 138.2,  # GW, as to 1/2
            "5/16": 147.3,
            "11/32": 158.0,
            "3/8": 166.1,
            "7/16": 185.2,
            "1/2": 206.0,
            "9/16": 225.4,  # P
            "5/8": 241.8,  # GW
            "11/16": 260.4,  # P, as to 13/16
            "3/4": 279.4,
            "13/16": 301.6,
            "7/8": 318.0,  # GW, as to 1
            "15/16": 336.6,
            "1": 356.5,
            "1-1/16": 387.4,  # P
            "1-1/8": 406.4,  # GW
            "1-1/4": 429.3,  # TK
            "1-5/16": 476.0,  # GW, as to 1-7/16
            "1-3/8": 507.0,
            "1-7/16": 536.0,
            "1-1/2": 514.4,  # P
        }.items()
    },
}

#: Stubby combination spanners' lengths, mm, by across-flats in mm, in the sizes
#: they are sold in (issue #49): the longer of Tekton's (6 to 32 mm, 1/4 to 1-1/4
#: in; its stubby spec tables, images.tekton.com) and Proto's short series (6 to 19
#: mm, 1/4 to 3/4 in; protoindustrial.com), read 2026-10-07. Common sets stop at 19
#: mm and 3/4 in, and nobody makes a stubby past 32 mm or 1-1/4 in; which a kit
#: holds is the kit's (:mod:`wrenchroom.tools.kits`).
STUBBY_LENGTHS: dict[float, float] = {
    6.0: 83.8,
    7.0: 85.7,  # Proto
    8.0: 91.4,
    9.0: 92.1,  # Proto
    10.0: 101.6,
    11.0: 106.7,
    12.0: 106.7,
    13.0: 111.8,
    14.0: 116.8,
    15.0: 124.5,
    16.0: 124.5,
    17.0: 132.1,
    18.0: 133.4,  # Proto
    19.0: 138.1,  # Proto
    20.0: 137.2,
    21.0: 149.9,
    22.0: 160.0,
    23.0: 170.2,
    24.0: 170.2,
    25.0: 180.3,
    26.0: 180.3,
    27.0: 190.5,
    28.0: 200.7,
    29.0: 210.8,
    30.0: 210.8,
    31.0: 221.0,
    32.0: 221.0,
    **{
        inch_mm(size): length
        for size, length in {
            "1/4": 83.8,
            "9/32": 85.7,  # Proto
            "5/16": 91.4,
            "11/32": 92.1,  # Proto
            "3/8": 101.6,
            "7/16": 106.7,
            "1/2": 111.8,
            "9/16": 116.8,
            "5/8": 124.5,
            "11/16": 132.1,
            "3/4": 138.1,  # Proto
            "13/16": 149.9,
            "7/8": 160.0,
            "15/16": 170.2,
            "1": 180.3,
            "1-1/16": 190.5,
            "1-1/8": 200.7,
            "1-1/4": 221.0,
        }.items()
    },
}


def spanner_for(af: float) -> Spanner:
    """The spanner for an across-flats size: makers' lengths, approximated heads.

    The full and stubby lengths are makers' (:data:`FULL_LENGTHS`,
    :data:`STUBBY_LENGTHS`); a size no maker publishes gets the prototype's
    ``9*af + 45``, which runs short of real spanners (issue #49), and no stubby.

    Approximations (labelled): head thickness ``0.3*af + 1.5``, ring outer radius
    ``0.8*af + 2``, handle width ``0.9*af + 2``. The open end's head width
    ``2.09*af + 1.9`` and thickness ``0.27*af + 2.2`` are fits to two makers'
    published heads (Stahlwille OPEN-BOX and Hazet 600N, 8 to 24 mm, read
    2026-10-06; widths within 1.1 mm of the fit, thicknesses within 1.0), inside
    ISO 3318:2016's maximum head width ``2.1*s + 7``.
    """
    return Spanner(
        af=af,
        length=FULL_LENGTHS.get(af, 9 * af + 45),
        head_thickness=0.3 * af + 1.5,
        ring_outer_radius=0.8 * af + 2,
        handle_width=0.9 * af + 2,
        open_width=2.09 * af + 1.9,
        open_thickness=0.27 * af + 2.2,
        stubby_length=STUBBY_LENGTHS.get(af),
    )


# ---------------------------------------------------------------------------
# The ring-end sweep (spec 6.2). Open end is M6; the ring covers most cases.
# ---------------------------------------------------------------------------

#: A 12-point ring goes on again every 30 degrees.
RING_RESEAT_DEG = 30.0

#: The ring keeps at least this much engagement thickness, mm, when the hex is
#: shorter than the ring: below it there is nothing to grip.
_MIN_GRIP = 0.4


def corner_sweep(hex_af: float, hex_band: tuple[float, float]) -> ToolSolid:
    """The ring of space the hex's own corners sweep as it turns, in the local frame.

    From its flats out to its corners (plus the ring's clearance), over the
    hex's height: anything in it stops the hex turning, whatever grips it. A
    ring's bore and a socket's mouth stand outside the corners and hide that
    space, so every tool on the flats tests it with its engagement; a part one
    mm off a flat (two glands side by side, a rib beside a nut) is in it.
    """
    band_top, band_bottom = hex_band
    return axial_annulus(
        hex_af / 2, hex_af / sqrt(3) + RING_CLEARANCE, band_bottom, band_top - band_bottom
    )


def _lengths(end: str, spanner: Spanner) -> list[tuple[str, float]]:
    """Each way an end is tried, at its length: full, and stubby where there is one."""
    lengths = [(f"{end}, full length", spanner.length)]
    if spanner.stubby_length is not None:
        lengths.append((f"{end}, stubby", spanner.stubby_length))
    return lengths


def ring_attempts(
    mount: Mount,
    spanner: Spanner,
    hex_af: float,
    hex_band: tuple[float, float],
    scene: Scene,
    step_deg: float = DEFAULT_STEP_DEG,
    hand_room: bool = False,
) -> Iterator[Attempt]:
    """The ring end at full length, then the stubby if there is one, lazily (and the hand).

    The ring is an annulus around the hex, centred on the hex band's mid-plane;
    the handle a box from the ring's edge out to 0.85 of the spanner's length.
    Turns over 30 degrees, holds at any one angle.

    ``hex_band`` is ``(top, bottom)`` in the local frame (seat at 0, both <= 0):
    where the hex actually is, which on a cable gland is below a dome nothing
    grips (bug C in the bench handoff). For a plain nut or a hex head the band's
    top is the seat and nothing changes. The engagement tests the hex's own
    :func:`corner_sweep` with the ring.
    """
    tool = spanner.label
    band_top, band_bottom = hex_band
    inner = hex_af / sqrt(3) + RING_CLEARANCE  # hex corner radius plus clearance
    thickness = min(spanner.head_thickness, (band_top - band_bottom) - _MIN_GRIP)
    mid_z = (band_top + band_bottom) / 2
    ring = axial_annulus(inner, spanner.ring_outer_radius, mid_z - thickness / 2, thickness)
    engagement = ring + corner_sweep(hex_af, hex_band)
    for way, length in _lengths("ring", spanner):
        yield swing_attempt(
            tool=tool,
            way=way,
            scene=scene,
            engagement=mount.place(engagement),
            arm_at=lambda phi, reach=0.85 * length: mount.place(
                radial_box(
                    spanner.handle_width,
                    thickness,
                    spanner.ring_outer_radius,
                    reach,
                    mid_z,
                    phi,
                )
            ),
            required_deg=RING_RESEAT_DEG,
            step_deg=step_deg,
            hand_at=(
                (
                    lambda phi, reach=0.85 * length: mount.place(
                        hand_on_handle(mid_z, spanner.ring_outer_radius, reach, phi)
                    )
                )
                if hand_room
                else None
            ),
        )


# ---------------------------------------------------------------------------
# The open-end sweep (spec 6.2): the jaw's outline, turned with its handle.
# ---------------------------------------------------------------------------

#: An open end with a 15 degree offset head, turned over each stroke, works in 30.
OPEN_RESEAT_DEG = 30.0

#: The jaw's arms reach this far past the hex's centre, as a fraction of its
#: across-flats. Approximation (no maker publishes it): enough to cover the flats
#: they grip (each 0.29 af either side of the centre) with a little to spare.
JAW_REACH = 0.5

#: Each arm's inner face stands this far off its flat, mm. Approximation.
JAW_CLEARANCE = 0.15


def open_jaw(spanner: Spanner, hex_af: float, thickness: float, z: float, phi: float) -> ToolSolid:
    """The open end's head at angle ``phi``: two arms either side of the hex, and the back.

    In the local frame the handle runs out along ``u(phi)``; the arms run from
    ``JAW_REACH * af`` past the centre to the throat (behind the hex's corner,
    as the ring's bore clears it), and the back from the throat to half the
    head's width, where the handle starts. The head's 15 degree offset to its
    handle is not drawn: jaw and handle lie in line, and the sweep tries every
    angle anyway.
    """
    throat = hex_af / sqrt(3) + RING_CLEARANCE
    back = max(spanner.open_width / 2, throat + 1.0)
    arm = (spanner.open_width - hex_af) / 2 - JAW_CLEARANCE
    offset = hex_af / 2 + JAW_CLEARANCE + arm / 2
    tip = -JAW_REACH * hex_af
    return (
        radial_box(arm, thickness, tip, throat, z, phi, offset)
        + radial_box(arm, thickness, tip, throat, z, phi, -offset)
        + radial_box(spanner.open_width, thickness, throat, back, z, phi)
    )


def open_end_attempts(
    mount: Mount,
    spanner: Spanner,
    hex_af: float,
    hex_band: tuple[float, float],
    scene: Scene,
    step_deg: float = DEFAULT_STEP_DEG,
    hand_room: bool = False,
) -> Iterator[Attempt]:
    """The open end at full length, then the stubby's if any, lazily (and the hand).

    The jaw grips two flats from the side, so unlike a ring it turns with its
    handle: every position tests the whole tool, jaw and handle together, and it
    turns on 30 degrees of contiguous free swing. Only the engaged positions are
    tested, not the slide on from the side, which stays inside the handle's own
    path. Same band and thickness rule as the ring.

    One thing is tested first, at no angle in particular: the hex's own
    :func:`corner_sweep`, which a neighbour 1 mm off the flats (two glands side
    by side) blocks whatever holds it.
    """
    tool = spanner.label
    band_top, band_bottom = hex_band
    thickness = min(spanner.open_thickness, (band_top - band_bottom) - _MIN_GRIP)
    mid_z = (band_top + band_bottom) / 2
    back = max(spanner.open_width / 2, hex_af / sqrt(3) + RING_CLEARANCE + 1.0)
    corners = corner_sweep(hex_af, hex_band)
    for way, length in _lengths("open end", spanner):
        yield swing_attempt(
            tool=tool,
            way=way,
            scene=scene,
            engagement=mount.place(corners),
            arm_at=lambda phi, reach=0.85 * length: mount.place(
                open_jaw(spanner, hex_af, thickness, mid_z, phi)
                + radial_box(spanner.handle_width, thickness, back, reach, mid_z, phi)
            ),
            required_deg=OPEN_RESEAT_DEG,
            step_deg=step_deg,
            hand_at=(
                (
                    lambda phi, reach=0.85 * length: mount.place(
                        hand_on_handle(mid_z, back, reach, phi)
                    )
                )
                if hand_room
                else None
            ),
        )
