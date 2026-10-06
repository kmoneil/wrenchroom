"""L-shaped hex keys: ISO 2936 dimensions.

Checked 2026-10-06 against fasten.it's DIN ISO 2936 table (edition 2016-10, which
implements ISO 2936:2014): across-corners ``e`` (max), long arm ``l1`` (standard
series) and short arm ``l2``. The spec's provisional table (long 45..112, short
14..40) was smaller than the standard series; the standard's values are used, and
the prototype comparison must expect leg-length differences from it
for exactly this reason.

The key's shaft is modelled as a cylinder of radius ``e/2`` (half across corners),
which is what the standard's own ``e`` column is for; no ``0.58 * af``
approximation is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from wrenchroom.tools.drivers import driver_attempt
from wrenchroom.tools.sizes import MM_PER_INCH, inch_mm, size_name
from wrenchroom.tools.sweep import (
    CONTACT_OFFSET,
    DEFAULT_STEP_DEG,
    Attempt,
    Mount,
    axial_cylinder,
    radial_cylinder,
    swing_attempt,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from wrenchroom.engine import Scene


@dataclass(frozen=True)
class HexKey:
    """One hex L-key, ISO 2936 or ASME B18.3, dimensions in mm.

    Attributes:
        af: Across flats (the nominal size).
        across_corners: ``e`` (``Y``) max; the shaft's circumscribed diameter.
        long_mm: Long arm ``l1`` (``C``), the standard (short-arm) series.
        short_mm: Short arm ``l2`` (``B``).
    """

    af: float
    across_corners: float
    long_mm: float
    short_mm: float

    @property
    def radius(self) -> float:
        """The swept shaft radius: half the across-corners width."""
        return self.across_corners / 2

    @property
    def name(self) -> str:
        """The tool's name in a report: ``hex-key-5``, ``hex-key-5/32in``."""
        return f"hex-key-{size_name(self.af)}"


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


def _inch_key(size: str, corners: float, short: float, long: float) -> HexKey:
    """An ASME B18.3 key from its inch row: Y max, B max, C max (short-arm series)."""
    return HexKey(
        af=inch_mm(size),
        across_corners=corners * MM_PER_INCH,
        long_mm=long * MM_PER_INCH,
        short_mm=short * MM_PER_INCH,
    )


#: ASME B18.3 hexagon keys, inch series, af (mm) -> key: across corners Y max, short
#: arm B max, long arm C max (short-arm series), all from the inch rows. Checked
#: 2026-10-06: the American Fastener hex wrench sheet and amesweb (citing
#: ASME B18.3-2003) agree row for row, as do Engineers Edge and the Unbrako
#: Engineering Guide (citing ANSI B18.3) on W, B and C. For 3/8 and up Engineers
#: Edge gives a slightly larger Y (3/8: .4300 against .4285); the larger is used,
#: which errs toward a fatter key. Maxima throughout, where ISO 2936 above gives
#: the standard series' nominal lengths: a longer leg or arm only asks for more
#: room, so the maxima err safe.
ASME_B18_3: dict[float, HexKey] = {
    key.af: key
    for key in (
        _inch_key("0.050", 0.0560, 0.625, 1.750),
        _inch_key("1/16", 0.0701, 0.656, 1.844),
        _inch_key("5/64", 0.0880, 0.703, 1.969),
        _inch_key("3/32", 0.1058, 0.750, 2.094),
        _inch_key("7/64", 0.1238, 0.797, 2.219),
        _inch_key("1/8", 0.1418, 0.844, 2.344),
        _inch_key("9/64", 0.1593, 0.891, 2.469),
        _inch_key("5/32", 0.1774, 0.938, 2.594),
        _inch_key("3/16", 0.2135, 1.031, 2.844),
        _inch_key("7/32", 0.2490, 1.125, 3.094),
        _inch_key("1/4", 0.2845, 1.219, 3.344),
        _inch_key("5/16", 0.3570, 1.344, 3.844),
        _inch_key("3/8", 0.4300, 1.469, 4.344),
        _inch_key("7/16", 0.5018, 1.594, 4.844),
        _inch_key("1/2", 0.5735, 1.719, 5.344),
        _inch_key("9/16", 0.6452, 1.844, 5.844),
        _inch_key("5/8", 0.7169, 1.969, 6.344),
        _inch_key("3/4", 0.8603, 2.219, 7.344),
    )
}

#: Every key there is, metric and inch, by across flats in mm.
HEX_KEYS: dict[float, HexKey] = {**ISO_2936, **ASME_B18_3}


# ---------------------------------------------------------------------------
# The sweep (spec 6.1). Tried in order; the first way that turns wins.
#
# Engagement depth, DECIDED 2026-10-06 (was decide-hex-engagement-depth): the
# inserted leg starts at the seat (the head's outer face) and runs its full
# length along the axis, ignoring the depth the key sinks into the socket.
# That errs safe -- it demands more axial room than reality by about the
# socket's depth -- and it is what the prototype did, so the prototype
# comparison agrees on this point. Revisit when a real model fails a check that
# a human with the key in hand says is fine; the fix then is to subtract the
# ISO 4762 socket depth ``t`` here and nowhere else.
# ---------------------------------------------------------------------------

#: A hex goes on again every sixth of a turn.
HEX_RESEAT_DEG = 60.0


class LKey(Protocol):
    """What the L-key sweep reads of a key, hex or Torx (torx_keys.py)."""

    @property
    def name(self) -> str:
        """The tool's name in a report."""
        ...

    @property
    def radius(self) -> float:
        """The swept shaft radius, mm."""
        ...

    @property
    def long_mm(self) -> float:
        """The long arm, mm."""
        ...

    @property
    def short_mm(self) -> float:
        """The short arm, mm."""
        ...


def hex_key_attempts(
    mount: Mount,
    key: LKey,
    scene: Scene,
    step_deg: float = DEFAULT_STEP_DEG,
    hand_room: bool = False,
) -> Iterator[Attempt]:
    """Every way to try one key, lazily, in the spec's order.

    Driver straight in first (cheapest and strongest), then the short leg in
    with the long arm swinging, then the long leg in with the short arm.
    The caller stops consuming at the first attempt that turns. With
    ``hand_room``, the key used as a driver must leave room for the fist round
    its handle; the arms, turned with the fingertips, are left alone (sweep.py).
    """
    tool = key.name
    yield driver_attempt(mount, scene, key.radius, tool, hand_room)
    legs = (
        ("short leg in", key.short_mm, key.long_mm),
        ("long leg in", key.long_mm, key.short_mm),
    )
    for way, leg, arm in legs:
        bend_z = CONTACT_OFFSET + leg
        yield swing_attempt(
            tool=tool,
            way=way,
            scene=scene,
            engagement=mount.place(axial_cylinder(key.radius, CONTACT_OFFSET, bend_z)),
            arm_at=lambda phi, z=bend_z, length=arm: mount.place(
                radial_cylinder(key.radius, 0.0, length, z, phi)
            ),
            required_deg=HEX_RESEAT_DEG,
            step_deg=step_deg,
        )
