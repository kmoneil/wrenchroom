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
