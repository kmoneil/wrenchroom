"""A graze 35 m from the origin measures as it does at it (issue #107).

The scaled bench's third flat_graze sat at (3000, 35000) mm, and on Linux the
exact engine measured one probe, hex-key-2.5's arm at 15 deg 0.004 mm into the
ring, as 365 mm^3: the whole arm inside the ring. The same pair moved 1 mm, or
1000 down, measured 0.026 mm^3, as did every other probe. Far out, OCP's boolean
can turn on a coordinate's last digit; near the origin it doesn't, so that is
where the exact engine measures (engine/exact.py). The pair is rebuilt here to
the last digit, the seat's height as the bench's STEP gave it. Where it never
failed (macOS) this passes either way.
"""

import pytest
from bench import PITCH
from build123d import Pos
from cells import CELLS

from wrenchroom.engine.exact import exact_overlap
from wrenchroom.solids import RadialCylinder, frame_location

FAR = (3 * PITCH, 35 * PITCH, 0.0)


def test_the_graze_that_measured_365_mm3_measures_0_026():
    (cell,) = (c for c in CELLS if c.name == "flat_graze")
    ring = Pos(*FAR) * dict(cell.build())["under"]
    seat = (FAR[0], FAR[1], 2.1999999999999993)
    arm = RadialCylinder(radius=1.41, r0=0.0, r1=58.5, z=20.8, phi_deg=15.0)
    placed = frame_location(seat, (0.0, 0.0, 1.0)) * arm.shape()
    assert exact_overlap(ring, placed) == pytest.approx(0.026328, abs=1e-5)
