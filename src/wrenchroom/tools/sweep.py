"""The sweep: placing tool solids at a seat and searching for free swing.

Shared by every tool family. A tool is built in a local frame (seat at the origin,
axis along +Z, pointing out of the joint toward the tool) and mapped to the
assembly by the fastener's :class:`Mount`. ``u(phi)`` is the local direction
``(cos phi, sin phi, 0)``; which global direction ``phi = 0`` lands on is arbitrary
and doesn't matter, because every search covers the full circle.

Swing is sampled every ``step_deg`` (default 15). ``k`` consecutive free positions
prove a swing of ``(k - 1) * step_deg``: the handle moves from the first free
position to the last. The search stops as soon as the required arc is proven (so
``swing_deg`` is what was proven, not the whole free circle), and a free arc
across 0 degrees counts whole: the scan walks the circle twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from wrenchroom.solids import AxialCylinder, AxialRing, RadialBox, RadialCylinder, ToolSolid

if TYPE_CHECKING:
    from collections.abc import Callable

    from wrenchroom.engine import Scene

#: Every tool starts this far off the seat, mm: contact tolerance, and the reason
#: a tangent touch not counting as a hit (engine.py) is safe.
CONTACT_OFFSET = 0.3

#: Swing sample spacing, degrees, unless the caller says otherwise.
DEFAULT_STEP_DEG = 15.0

FULL_CIRCLE = 360.0


@dataclass(frozen=True)
class Mount:
    """Where a tool engages: the seat point and the axis pointing toward the tool."""

    seat: tuple[float, float, float]
    axis: tuple[float, float, float]

    def place(self, local: ToolSolid) -> ToolSolid:
        """Put a tool solid built in the local frame (seat at origin, axis +Z) here."""
        return local.placed(self.seat, self.axis)


@dataclass(frozen=True)
class Attempt:
    """One way one tool was tried, and how it went. The unit `explain` prints.

    Attributes:
        tool: The tool's name, e.g. ``hex-key-5``.
        way: How it was tried, e.g. ``short leg in``.
        turns: The tool can rotate the fastener this way.
        holds: The tool can sit on it at one angle and stop it turning.
        swing_deg: The largest free arc proven before the search stopped; 360
            for a straight-in driver that turns in place.
        blockers: Every part any probed position ran into, first-seen order.
    """

    tool: str
    way: str
    turns: bool
    holds: bool
    swing_deg: float
    blockers: tuple[str, ...]


def swing_attempt(
    *,
    tool: str,
    way: str,
    scene: Scene,
    engagement: ToolSolid,
    arm_at: Callable[[float], ToolSolid],
    required_deg: float,
    step_deg: float = DEFAULT_STEP_DEG,
) -> Attempt:
    """Try an engagement solid, then search the arm's swing.

    The engagement (the part of the tool on the fastener) must be clear or the
    attempt fails outright with its blockers. Then the arm is sampled around the
    circle: `turns` needs ``required_deg`` of contiguous free arc, `holds` needs
    any one free position.
    """
    blockers: list[str] = []
    engagement_hits = scene.hits(engagement)
    if engagement_hits:
        return Attempt(tool, way, False, False, 0.0, tuple(engagement_hits))

    samples = max(1, round(FULL_CIRCLE / step_deg))
    free: dict[int, bool] = {}

    def is_free(index: int) -> bool:
        if index not in free:
            hits = scene.hits(arm_at(index * step_deg))
            for name in hits:
                if name not in blockers:
                    blockers.append(name)
            free[index] = not hits
        return free[index]

    run = 0
    best = 0
    for position in range(2 * samples):
        if not is_free(position % samples):
            run = 0
            if position >= samples:
                break  # second lap adds nothing once a wall is seen again
            continue
        run = min(run + 1, samples)
        best = max(best, run)
        if run == samples or (run - 1) * step_deg >= required_deg:
            break

    swing = FULL_CIRCLE if best == samples else max(0.0, (best - 1) * step_deg)
    turns = swing >= required_deg
    holds = best >= 1
    return Attempt(tool, way, turns, holds, swing, tuple(blockers))


def straight_attempt(*, tool: str, way: str, scene: Scene, solid: ToolSolid) -> Attempt:
    """Try a tool that turns in place: clear means it turns, blocked means it doesn't."""
    hits = scene.hits(solid)
    ok = not hits
    return Attempt(tool, way, ok, ok, FULL_CIRCLE if ok else 0.0, tuple(hits))


# ---------------------------------------------------------------------------
# Local-frame builders, shared vocabulary for the tool families.
# ---------------------------------------------------------------------------


def axial_cylinder(radius: float, z_from: float, z_to: float) -> ToolSolid:
    """A cylinder along the local axis from ``z_from`` to ``z_to``."""
    return ToolSolid((AxialCylinder(radius, z_from, z_to),))


def radial_cylinder(
    radius: float, r_from: float, r_to: float, z: float, phi_deg: float
) -> ToolSolid:
    """A cylinder along ``u(phi)`` at height ``z``, spanning the radial interval."""
    return ToolSolid((RadialCylinder(radius, r_from, r_to, z, phi_deg),))


def radial_box(
    width: float, thickness: float, r_from: float, r_to: float, z: float, phi_deg: float
) -> ToolSolid:
    """A box along ``u(phi)``: a handle. ``width`` is tangential, ``thickness`` axial."""
    return ToolSolid((RadialBox(width, thickness, r_from, r_to, z, phi_deg),))


def axial_annulus(inner: float, outer: float, z_from: float, thickness: float) -> ToolSolid:
    """A ring around the local axis, ``thickness`` long from ``z_from``."""
    return ToolSolid((AxialRing(inner, outer, z_from, z_from + thickness),))
