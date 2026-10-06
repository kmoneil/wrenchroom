"""Combination spanners: dimensions, currently the prototype's approximations.

Every function here is an APPROXIMATION, labelled per the project rule, carried
over from the prototype that found TRIDENT's real failures with them. Replace with
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

from wrenchroom.tools.sweep import (
    DEFAULT_STEP_DEG,
    Attempt,
    Mount,
    axial_annulus,
    radial_box,
    swing_attempt,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from wrenchroom.engine import Scene

#: A stubby spanner is about 0.55 of the full length. Approximation (prototype).
STUBBY_FACTOR = 0.55

#: The ring's bore clears the hex's corners by this much, mm. Approximation.
RING_CLEARANCE = 0.3


@dataclass(frozen=True)
class Spanner:
    """One combination spanner's numbers, all mm, derived from across-flats."""

    af: float
    length: float
    head_thickness: float
    ring_outer_radius: float
    handle_width: float

    @property
    def stubby_length(self) -> float:
        """The stubby version's length."""
        return self.length * STUBBY_FACTOR


def spanner_for(af: float) -> Spanner:
    """The spanner for an across-flats size, from the prototype's approximations.

    Approximations (labelled): length ``9*af + 45``, head thickness ``0.3*af + 1.5``,
    ring outer radius ``0.8*af + 2``, handle width ``0.9*af + 2``. Replace with
    DIN 3113 rows; until then these err slightly large on length for small sizes,
    which errs safe (reports less swing room than a real spanner would find).
    """
    return Spanner(
        af=af,
        length=9 * af + 45,
        head_thickness=0.3 * af + 1.5,
        ring_outer_radius=0.8 * af + 2,
        handle_width=0.9 * af + 2,
    )


# ---------------------------------------------------------------------------
# The ring-end sweep (spec 6.2). Open end is M6; the ring covers most cases.
# ---------------------------------------------------------------------------

#: A 12-point ring goes on again every 30 degrees.
RING_RESEAT_DEG = 30.0

#: The ring keeps at least this much engagement thickness, mm, when the hex is
#: shorter than the ring: below it there is nothing to grip.
_MIN_GRIP = 0.4


def ring_attempts(
    mount: Mount,
    spanner: Spanner,
    hex_af: float,
    hex_height: float,
    scene: Scene,
    step_deg: float = DEFAULT_STEP_DEG,
) -> Iterator[Attempt]:
    """The ring end at full length, then the stubby, lazily.

    The ring is an annulus around the hex, centred on the hex's mid-plane (the
    hex runs from the seat down into the joint by ``hex_height``); the handle a
    box from the ring's edge out to 0.85 of the spanner's length. Turns over
    30 degrees, holds at any one angle.
    """
    tool = f"spanner-{spanner.af:g}"
    inner = hex_af / sqrt(3) + RING_CLEARANCE  # hex corner radius plus clearance
    thickness = min(spanner.head_thickness, hex_height - _MIN_GRIP)
    mid_z = -hex_height / 2
    ring = axial_annulus(inner, spanner.ring_outer_radius, mid_z - thickness / 2, thickness)
    for way, length in (
        ("ring, full length", spanner.length),
        ("ring, stubby", spanner.stubby_length),
    ):
        yield swing_attempt(
            tool=tool,
            way=way,
            scene=scene,
            engagement=mount.place(ring),
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
        )
