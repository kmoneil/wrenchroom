"""Nut drivers: a socket on a screwdriver's shaft, turned in place (spec 6.3), full kit.

A nut driver is one clearance test, as a screwdriver is: its socket over the hex
(a mouth bored for the bolt's end, then solid), its shaft and its handle, straight
along the axis. A cable through the fastener rules it out, as it does a socket.

Dimensions, from two makers' own pages, read 2026-10-06 (Wera 395 and Wiha
SoftFinish 341), the larger of the two each time so the check never asks for less
room than a real one needs: the socket's (and the blade's) outside diameter, the
blade's length (125 mm, both), the handle's diameter (Wiha's; Wera gives none) and
length (Wiha's overall less its blade, longer than Wera's). The mouth's depth for a
bolt's end is the sockets' approximation, 15 mm: neither maker gives it.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import TYPE_CHECKING

from wrenchroom.tools.sizes import size_name
from wrenchroom.tools.sockets import BORE_DEPTH, socket_wall
from wrenchroom.tools.spanners import RING_CLEARANCE, corner_sweep
from wrenchroom.tools.sweep import (
    CONTACT_OFFSET,
    HAND_LENGTH,
    HAND_RADIUS,
    Attempt,
    Mount,
    axial_annulus,
    axial_cylinder,
    straight_attempt,
)

if TYPE_CHECKING:
    from wrenchroom.engine import Scene
    from wrenchroom.solids import ToolSolid

#: The blade, socket end to handle, mm: 125 on both makers' drivers.
BLADE_LENGTH = 125.0


@dataclass(frozen=True)
class NutDriver:
    """One nut driver, dimensions in mm."""

    af: float
    outer_radius: float
    handle_radius: float
    handle_length: float

    @property
    def name(self) -> str:
        """The tool's name in a report: ``nut-driver-10``."""
        return f"nut-driver-{size_name(self.af)}"


def _driver(
    af: float, wera_od: float, wiha_od: float, handle_d: float, handle_l: float
) -> NutDriver:
    return NutDriver(af, max(wera_od, wiha_od) / 2, handle_d / 2, handle_l)


#: Nut drivers by across flats: socket OD (Wera, Wiha), Wiha's handle diameter, and the
#: handle's length (Wiha's 236..249 overall less its 125 blade; Wera's are 98..112).
NUT_DRIVERS: dict[float, NutDriver] = {
    driver.af: driver
    for driver in (
        _driver(5.5, 8.1, 7.9, 30, 111),
        _driver(7.0, 11.0, 10.9, 36, 118),
        _driver(8.0, 12.1, 11.9, 36, 118),
        _driver(10.0, 14.1, 14.4, 36, 118),
        _driver(13.0, 18.1, 18.4, 41, 124),
    )
}


def nut_driver_solid(driver: NutDriver, hex_af: float, hex_band: tuple[float, float]) -> ToolSolid:
    """The whole driver in the local frame, from the hex up to the handle's end.

    The hex's corner sweep and the socket's wall round the hex (as a socket's),
    then the mouth, the solid socket and blade, and the handle.
    """
    inner = hex_af / sqrt(3) + RING_CLEARANCE
    mouth_to = CONTACT_OFFSET + BORE_DEPTH
    handle_from = CONTACT_OFFSET + BLADE_LENGTH
    return (
        corner_sweep(hex_af, hex_band)
        + socket_wall(hex_af, driver.outer_radius, hex_band)
        + axial_annulus(inner, driver.outer_radius, CONTACT_OFFSET, BORE_DEPTH)
        + axial_cylinder(driver.outer_radius, mouth_to, handle_from)
        + axial_cylinder(driver.handle_radius, handle_from, handle_from + driver.handle_length)
    )


def nut_driver_hand(driver: NutDriver) -> ToolSolid:
    """The fist round the handle's last HAND_LENGTH mm, as a screwdriver's (sweep.py)."""
    handle_to = CONTACT_OFFSET + BLADE_LENGTH + driver.handle_length
    return axial_cylinder(HAND_RADIUS, handle_to - HAND_LENGTH, handle_to)


def nut_driver_attempt(
    mount: Mount,
    driver: NutDriver,
    hex_af: float,
    hex_band: tuple[float, float],
    scene: Scene,
    hand_room: bool = False,
) -> Attempt:
    """One straight-in clearance test: clear, it turns."""
    return straight_attempt(
        tool=driver.name,
        way="nut driver straight in",
        scene=scene,
        solid=mount.place(nut_driver_solid(driver, hex_af, hex_band)),
        hand=mount.place(nut_driver_hand(driver)) if hand_room else None,
    )
