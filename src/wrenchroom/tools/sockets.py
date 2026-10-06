"""Sockets, extensions and the ratchet: dimensions, currently approximations.

Replace with DIN 3124 rows when read out. As with the spanners, the sweep asks for
numbers by across-flats, so filling the real table changes no interface.
"""

from __future__ import annotations

from dataclasses import dataclass

#: How deep a socket is hollow from its mouth, mm: the bolt's end goes into it.
#: Approximation (prototype).
BORE_DEPTH = 15.0

#: Stock extension lengths, mm, as sold in 1/4" and 3/8" drive sets. Catalogue
#: values (common set contents), checked against no standard: extensions are not
#: standardised the way the sockets are.
EXTENSION_LENGTHS = (50.0, 75.0, 100.0, 150.0, 250.0)

#: A 72-tooth ratchet advances every 5 degrees. Physical constant of the tooth
#: count, not an approximation; the kit says which ratchet it carries.
RATCHET_72_SWING_DEG = 5.0


@dataclass(frozen=True)
class Socket:
    """One socket's numbers, all mm."""

    af: float
    outer_radius: float
    length: float


def socket_for(af: float) -> Socket:
    """The socket for an across-flats size.

    Approximations (labelled, prototype): outer radius ``0.6*af + 1.2``, length
    ``max(25, 1.4*af + 14)``; replace with DIN 3124.
    """
    return Socket(af=af, outer_radius=0.6 * af + 1.2, length=max(25.0, 1.4 * af + 14.0))
