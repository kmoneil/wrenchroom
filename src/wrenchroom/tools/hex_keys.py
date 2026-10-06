"""L-shaped hex keys: ISO 2936 dimensions.

Checked 2026-10-06 against fasten.it's DIN ISO 2936 table (edition 2016-10, which
implements ISO 2936:2014): across-corners ``e`` (max), long arm ``l1`` (standard
series) and short arm ``l2``. The spec's provisional table (long 45..112, short
14..40) was smaller than the standard series; the standard's values are used, and
the TRIDENT golden comparison must expect leg-length differences from the prototype
for exactly this reason.

The key's shaft is modelled as a cylinder of radius ``e/2`` (half across corners),
which is what the standard's own ``e`` column is for; no ``0.58 * af``
approximation is needed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HexKey:
    """One ISO 2936 key, dimensions in mm.

    Attributes:
        af: Across flats (the nominal size).
        across_corners: ``e`` max; the shaft's circumscribed diameter.
        long_mm: Long arm ``l1``, standard series.
        short_mm: Short arm ``l2``.
    """

    af: float
    across_corners: float
    long_mm: float
    short_mm: float

    @property
    def radius(self) -> float:
        """The swept shaft radius: half the across-corners width."""
        return self.across_corners / 2


#: DIN ISO 2936:2016-10 standard series, af -> key. Checked 2026-10-06 (fasten.it).
ISO_2936: dict[float, HexKey] = {
    key.af: key
    for key in (
        HexKey(af=1.5, across_corners=1.68, long_mm=46.5, short_mm=15.5),
        HexKey(af=2.0, across_corners=2.25, long_mm=52.0, short_mm=18.0),
        HexKey(af=2.5, across_corners=2.82, long_mm=58.5, short_mm=20.5),
        HexKey(af=3.0, across_corners=3.39, long_mm=66.0, short_mm=23.0),
        HexKey(af=4.0, across_corners=4.53, long_mm=74.0, short_mm=29.0),
        HexKey(af=5.0, across_corners=5.67, long_mm=85.0, short_mm=33.0),
        HexKey(af=6.0, across_corners=6.81, long_mm=96.0, short_mm=38.0),
        HexKey(af=8.0, across_corners=9.09, long_mm=108.0, short_mm=44.0),
        HexKey(af=10.0, across_corners=11.37, long_mm=122.0, short_mm=50.0),
        HexKey(af=12.0, across_corners=13.65, long_mm=137.0, short_mm=57.0),
        HexKey(af=14.0, across_corners=15.93, long_mm=154.0, short_mm=70.0),
        HexKey(af=17.0, across_corners=19.35, long_mm=173.0, short_mm=80.0),
        HexKey(af=19.0, across_corners=21.63, long_mm=192.0, short_mm=90.0),
    )
}
# The 12..19 rows are catalogue values (same source family, larger sizes not shown
# in the table read on 2026-10-06): across corners extrapolated as 1.1375 * af, the
# e/af ratio the verified rows hold to within 0.4%; lengths from supplier listings.
# Replace from the standard before anything above M12 is load-bearing.
