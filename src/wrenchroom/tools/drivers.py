"""Screwdrivers and driver handles: a shaft, a handle, no swing needed.

A driver turns in place, so the whole attempt is one clearance test: shaft from
the seat along the axis, handle after it. The shaft radii are approximations
(labelled): typical PH/slotted driver shafts from supplier catalogues, not a
standard; replace if a real failure ever lands within a millimetre of one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wrenchroom.tools.sweep import (
    CONTACT_OFFSET,
    HAND_LENGTH,
    HAND_RADIUS,
    Attempt,
    Mount,
    axial_cylinder,
    straight_attempt,
)

if TYPE_CHECKING:
    from wrenchroom.engine import Scene
    from wrenchroom.solids import ToolSolid

#: Shaft length, mm, before the handle begins. Approximation: a standard-length
#: driver; stubby drivers can come later as another way.
SHAFT_LENGTH = 100.0

#: Handle radius and length, mm. Approximation (prototype).
HANDLE_RADIUS = 14.0
HANDLE_LENGTH = 100.0

#: Shaft radius, mm, by drive. Approximation: catalogue-typical shaft diameters, the
#: largest of Wera's, Wiha's and PB Swiss's (PH0, M1.6 and M2's, from their pages
#: read 2026-10-07: PB Swiss's 4 mm, the others' 3; issue #83).
SHAFT_RADIUS: dict[str, float] = {
    "ph0": 2.0,
    "ph1": 2.5,
    "ph2": 3.0,
    "ph3": 4.0,
    "slotted": 3.0,
}


def driver_solid(shaft_radius: float, shaft_length: float = SHAFT_LENGTH) -> ToolSolid:
    """The local-frame driver: shaft then handle, starting off the seat."""
    shaft = axial_cylinder(shaft_radius, CONTACT_OFFSET, CONTACT_OFFSET + shaft_length)
    handle_from = CONTACT_OFFSET + shaft_length
    handle = axial_cylinder(HANDLE_RADIUS, handle_from, handle_from + HANDLE_LENGTH)
    return shaft + handle


def driver_hand(shaft_length: float = SHAFT_LENGTH) -> ToolSolid:
    """The fist round the handle's last HAND_LENGTH mm, in the local frame."""
    handle_to = CONTACT_OFFSET + shaft_length + HANDLE_LENGTH
    return axial_cylinder(HAND_RADIUS, handle_to - HAND_LENGTH, handle_to)


def driver_attempt(
    mount: Mount,
    scene: Scene,
    shaft_radius: float,
    tool: str,
    hand_room: bool = False,
    shaft_length: float = SHAFT_LENGTH,
) -> Attempt:
    """One straight-in clearance test for a driver of the given shaft (and its hand)."""
    return straight_attempt(
        tool=tool,
        way="driver straight in",
        scene=scene,
        solid=mount.place(driver_solid(shaft_radius, shaft_length)),
        hand=mount.place(driver_hand(shaft_length)) if hand_room else None,
    )
