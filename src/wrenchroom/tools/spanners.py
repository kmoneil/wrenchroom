"""Combination spanners: dimensions, currently the prototype's approximations.

Every function here is an APPROXIMATION, labelled per the project rule, carried
over from the prototype that found real failures with them. Replace with
DIN 3113 / ISO 3318 / ISO 7738 tables when those are read out; keep the function
signatures, since the sweep only asks for numbers by across-flats.

The one physical constant that is not approximate: a 12-point ring goes on again
every 30 degrees, so 30 degrees of free swing turns the fastener. That constant
belongs to the sweep (m1-tool-sweeps) and is stated here only so nobody tunes a
table to compensate for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import TYPE_CHECKING

from wrenchroom.tools.sizes import size_name
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

#: A stubby spanner is about 0.55 of the full length. Approximation (prototype).
STUBBY_FACTOR = 0.55

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

    @property
    def stubby_length(self) -> float:
        """The stubby version's length."""
        return self.length * STUBBY_FACTOR


#: Lengths of the spanners above 36 mm, which the formula below would make some
#: 100 mm short (and so err towards passing): Gedore's 1 B combination spanners,
#: to DIN 3113 and ISO 3318, as published (read 2026-10-06).
LARGE_LENGTHS: dict[float, float] = {41.0: 520.0, 46.0: 550.0, 50.0: 580.0}


def spanner_for(af: float) -> Spanner:
    """The spanner for an across-flats size, from the prototype's approximations.

    Approximations (labelled): length ``9*af + 45``, head thickness ``0.3*af + 1.5``,
    ring outer radius ``0.8*af + 2``, handle width ``0.9*af + 2``. Replace with
    DIN 3113 rows; until then these err slightly large on length for small sizes,
    which errs safe (reports less swing room than a real spanner would find).

    The open end's head width ``2.09*af + 1.9`` and thickness ``0.27*af + 2.2``
    are fits to two makers' published heads (Stahlwille OPEN-BOX and Hazet 600N,
    8 to 24 mm, read 2026-10-06; widths within 1.1 mm of the fit, thicknesses
    within 1.0), inside ISO 3318:2016's maximum head width ``2.1*s + 7``.

    Above 36 mm the length is a maker's (:data:`LARGE_LENGTHS`).
    """
    return Spanner(
        af=af,
        length=LARGE_LENGTHS.get(af, 9 * af + 45),
        head_thickness=0.3 * af + 1.5,
        ring_outer_radius=0.8 * af + 2,
        handle_width=0.9 * af + 2,
        open_width=2.09 * af + 1.9,
        open_thickness=0.27 * af + 2.2,
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


def ring_attempts(
    mount: Mount,
    spanner: Spanner,
    hex_af: float,
    hex_band: tuple[float, float],
    scene: Scene,
    step_deg: float = DEFAULT_STEP_DEG,
    hand_room: bool = False,
) -> Iterator[Attempt]:
    """The ring end at full length, then the stubby, lazily (with the hand, if asked).

    The ring is an annulus around the hex, centred on the hex band's mid-plane;
    the handle a box from the ring's edge out to 0.85 of the spanner's length.
    Turns over 30 degrees, holds at any one angle.

    ``hex_band`` is ``(top, bottom)`` in the local frame (seat at 0, both <= 0):
    where the hex actually is, which on a cable gland is below a dome nothing
    grips (bug C in the bench handoff). For a plain nut or a hex head the band's
    top is the seat and nothing changes. The engagement tests the hex's own
    :func:`corner_sweep` with the ring.
    """
    tool = f"spanner-{size_name(spanner.af)}"
    band_top, band_bottom = hex_band
    inner = hex_af / sqrt(3) + RING_CLEARANCE  # hex corner radius plus clearance
    thickness = min(spanner.head_thickness, (band_top - band_bottom) - _MIN_GRIP)
    mid_z = (band_top + band_bottom) / 2
    ring = axial_annulus(inner, spanner.ring_outer_radius, mid_z - thickness / 2, thickness)
    engagement = ring + corner_sweep(hex_af, hex_band)
    for way, length in (
        ("ring, full length", spanner.length),
        ("ring, stubby", spanner.stubby_length),
    ):
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
    """The open end at full length, then the stubby's, lazily (with the hand, if asked).

    The jaw grips two flats from the side, so unlike a ring it turns with its
    handle: every position tests the whole tool, jaw and handle together, and it
    turns on 30 degrees of contiguous free swing. Only the engaged positions are
    tested, not the slide on from the side, which stays inside the handle's own
    path. Same band and thickness rule as the ring.

    One thing is tested first, at no angle in particular: the hex's own
    :func:`corner_sweep`, which a neighbour 1 mm off the flats (two glands side
    by side) blocks whatever holds it.
    """
    tool = f"spanner-{size_name(spanner.af)}"
    band_top, band_bottom = hex_band
    thickness = min(spanner.open_thickness, (band_top - band_bottom) - _MIN_GRIP)
    mid_z = (band_top + band_bottom) / 2
    back = max(spanner.open_width / 2, hex_af / sqrt(3) + RING_CLEARANCE + 1.0)
    corners = corner_sweep(hex_af, hex_band)
    for way, length in (
        ("open end, full length", spanner.length),
        ("open end, stubby", spanner.stubby_length),
    ):
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
