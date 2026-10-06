"""Ball-end hex keys: the long leg in at up to 25 degrees off the axis (spec 6.1).

A ball-end key is a hex key whose long leg ends in a ball, which turns a socket
screw with the leg tilted. It is tried after the plain key's three ways fail, and
only from the full kit: at each tilt from 10 degrees in 5 degree steps to the most
a ball end takes, the long leg goes in every 30 degrees round the axis, and the
key turns about its own tilted axis, its short arm swinging, on 60 degrees of free
swing, as a hex key does.

The search is coarser than the swing's, for time (measured 2026-10-06: every 15
degrees from 5, it added 3.4 s to the 500-fastener bench, past the 10 s target):
no 5 degree tilt, which moves the 154 mm leg's far end only 13 mm and is little
different from the straight long leg already tried; and 30 degrees round, which
at 25 degrees puts the leg's far end 34 mm apart between neighbours.

The figures, checked 2026-10-06 on the makers' own pages:

- The most tilt: 25 degrees, the spec's figure, which Bondhus ("inserts into screw
  at a 25 deg angle") and Wiha ("angles of up to 25 deg") both give; PB Swiss says
  30 and Eklind 35. The smallest errs safe: a key that needs 30 is not credited.
- The arms: Wera 950 SPKL, the longest of the two series read (Bondhus BL is
  shorter in both arms), so no ball-end key needs more room than the check asks.
  Sizes 3 to 10 mm, those whose arms were both read.
- The leg's section: the size's ISO 2936 key (its across-corners); the ball and
  the thinner neck behind it, which makers don't publish, are not drawn.

One attempt is reported per tilt: the direction that turned, or else the one that
came nearest, with its probes; the others' are not kept.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from wrenchroom.solids import frame_matrix
from wrenchroom.tools.hex_keys import HEX_RESEAT_DEG, ISO_2936
from wrenchroom.tools.sizes import size_name
from wrenchroom.tools.sweep import (
    CONTACT_OFFSET,
    DEFAULT_STEP_DEG,
    FULL_CIRCLE,
    Attempt,
    Mount,
    axial_cylinder,
    radial_cylinder,
    swing_attempt,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from wrenchroom.engine import Scene

#: The most a ball end turns a screw off its axis, degrees (Bondhus, Wiha).
MAX_TILT_DEG = 25.0

#: The tilts tried, degrees: every 5 from 10 up to the most.
TILTS = (10.0, 15.0, 20.0, 25.0)

#: The directions round the axis each tilt is tried in, every this many degrees.
ROUND_STEP_DEG = 30.0


@dataclass(frozen=True)
class BallEndKey:
    """One ball-end key, dimensions in mm: the ball on the long arm."""

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
        """The tool's name in a report: ``ball-end-key-5``."""
        return f"ball-end-key-{size_name(self.af)}"


def _key(af: float, long: float, short: float) -> BallEndKey:
    return BallEndKey(af, ISO_2936[af].across_corners, long, short)


#: Ball-end keys by across flats: Wera 950 SPKL arms, long and short, mm.
BALL_END_KEYS: dict[float, BallEndKey] = {
    key.af: key
    for key in (
        _key(3.0, 123, 21),
        _key(4.0, 137, 24),
        _key(5.0, 154, 27),
        _key(6.0, 172, 31),
        _key(8.0, 195, 37),
        _key(10.0, 224, 42),
    )
}


def tilted(mount: Mount, tilt_deg: float, round_deg: float) -> Mount:
    """The mount with its axis leant ``tilt_deg`` off, towards ``round_deg`` round it.

    The direction round the axis is measured in the mount's own frame, the one
    every tool at this seat is placed in.
    """
    frame = frame_matrix(mount.seat, mount.axis)
    x, y, z = frame[:3, 0], frame[:3, 1], frame[:3, 2]
    t, p = math.radians(tilt_deg), math.radians(round_deg)
    lean = math.cos(t) * z + math.sin(t) * (math.cos(p) * x + math.sin(p) * y)
    return Mount(seat=mount.seat, axis=(float(lean[0]), float(lean[1]), float(lean[2])))


def ball_end_attempts(
    mount: Mount,
    key: BallEndKey,
    scene: Scene,
    step_deg: float = DEFAULT_STEP_DEG,
) -> Iterator[Attempt]:
    """The ball end at each tilt, every way round, lazily: one attempt per tilt.

    At each tilt the first direction that turns is reported and the search stops;
    when none does, the direction with the most free swing (the first such) is
    reported in its place, which says how near the tilt came.
    """
    bend = CONTACT_OFFSET + key.long_mm
    directions = max(1, round(FULL_CIRCLE / ROUND_STEP_DEG))
    for tilt in TILTS:
        way = f"ball end, {tilt:g} deg off the axis"
        best: Attempt | None = None
        for index in range(directions):
            leant = tilted(mount, tilt, index * ROUND_STEP_DEG)
            attempt = swing_attempt(
                tool=key.name,
                way=way,
                scene=scene,
                engagement=leant.place(axial_cylinder(key.radius, CONTACT_OFFSET, bend)),
                arm_at=lambda phi, at=leant: at.place(
                    radial_cylinder(key.radius, 0.0, key.short_mm, bend, phi)
                ),
                required_deg=HEX_RESEAT_DEG,
                step_deg=step_deg,
            )
            if attempt.turns:
                yield attempt
                return
            if best is None or _nearer(attempt, best):
                best = attempt
        assert best is not None  # noqa: S101  (directions >= 1)
        yield best


def _nearer(attempt: Attempt, best: Attempt) -> bool:
    """Holds where the best didn't, or swings further."""
    return (attempt.holds, attempt.swing_deg) > (best.holds, best.swing_deg)
