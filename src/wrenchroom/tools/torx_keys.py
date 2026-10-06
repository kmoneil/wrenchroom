"""Torx (hexalobular) L-keys, T10 to T40: the full kit's (spec 5.3, 6.1).

A Torx key is swept exactly as a hex key is (hex_keys.py): driver straight in, short
leg in, long leg in, turning on 60 degrees of free swing (six lobes, the spec's
figure). Only its numbers differ.

The key's section is the recess's point-to-point size ``A`` from ISO 10664:2014
Table 1, checked 2026-10-06 against the standard's sample pages and two independent
copies; a key's tip sits within the recess's go-gauge, so the recess's nominal ``A``
errs on the fat side.

No standard sets Torx key lengths (makers borrow ISO 2936's, or not). The arms here
are the longest any of three makers sells, each read from its own catalogue on
2026-10-06: Wera 967 SPKL, Bondhus TORX long series, Eklind TORX long series. No real
key then asks for less room than the check does: a longer leg needs more room to go
in, a longer arm more to swing.
"""

from __future__ import annotations

from dataclasses import dataclass

from wrenchroom.tools.sizes import MM_PER_INCH


@dataclass(frozen=True)
class TorxKey:
    """One Torx L-key, dimensions in mm.

    Attributes:
        size: ``T10``, ``T30``...
        point_to_point: ISO 10664 ``A``, across the lobes: the swept section.
        long_mm: Long arm.
        short_mm: Short arm.
    """

    size: str
    point_to_point: float
    long_mm: float
    short_mm: float

    @property
    def radius(self) -> float:
        """The swept shaft radius: half the point-to-point size."""
        return self.point_to_point / 2

    @property
    def name(self) -> str:
        """The tool's name in a report: ``torx-key-T30``."""
        return f"torx-key-{self.size}"


def _key(size: str, a: float, arms: tuple[tuple[float, float], ...]) -> TorxKey:
    """A key from its ISO 10664 ``A`` and each maker's (long, short): the longest of each."""
    return TorxKey(size, a, max(long for long, _ in arms), max(short for _, short in arms))


#: Each maker's arms, (long, short) mm, in the order Wera 967 SPKL, Bondhus long,
#: Eklind long (published in inches).
ISO_10664: dict[str, TorxKey] = {
    key.size: key
    for key in (
        _key("T10", 2.80, ((85, 17), (80, 19), (3.38 * MM_PER_INCH, 0.66 * MM_PER_INCH))),
        _key("T15", 3.35, ((90, 18), (84, 20), (3.57 * MM_PER_INCH, 0.71 * MM_PER_INCH))),
        _key("T20", 3.95, ((96, 19), (91, 20), (3.79 * MM_PER_INCH, 0.75 * MM_PER_INCH))),
        _key("T25", 4.50, ((104, 21), (98, 22), (3.94 * MM_PER_INCH, 0.80 * MM_PER_INCH))),
        _key("T27", 5.10, ((112, 22), (106, 24), (4.17 * MM_PER_INCH, 0.85 * MM_PER_INCH))),
        _key("T30", 5.60, ((122, 24), (116, 26), (4.50 * MM_PER_INCH, 0.94 * MM_PER_INCH))),
        _key("T40", 6.75, ((132, 27), (125, 28), (4.88 * MM_PER_INCH, 1.03 * MM_PER_INCH))),
    )
}
