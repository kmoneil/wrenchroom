"""Sockets, extensions and the ratchet: dimensions, currently approximations.

Replace with DIN 3124 rows when read out. As with the spanners, the sweep asks for
numbers by across-flats, so filling the real table changes no interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import TYPE_CHECKING

from wrenchroom.tools.sizes import size_name
from wrenchroom.tools.spanners import RING_CLEARANCE, corner_sweep
from wrenchroom.tools.sweep import (
    CONTACT_OFFSET,
    DEFAULT_STEP_DEG,
    Attempt,
    Mount,
    axial_annulus,
    axial_cylinder,
    hand_on_handle,
    radial_box,
    swing_attempt,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from wrenchroom.engine import Scene
    from wrenchroom.solids import ToolSolid

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


# ---------------------------------------------------------------------------
# The socket sweep (spec 6.2): socket, extension, ratchet. Not allowed when a
# cable or hose passes through the fastener (socket_allowed = False on the
# fastener); the caller enforces that, not this module.
# ---------------------------------------------------------------------------

#: Ratchet and extension bodies, mm. Approximations (catalogue-typical 1/4" and
#: 3/8" drive hardware): extension bar radius, ratchet head radius and depth,
#: handle reach and section.
EXTENSION_RADIUS = 6.0
RATCHET_HEAD_RADIUS = 17.0
RATCHET_HEAD_DEPTH = 12.0
RATCHET_HANDLE_REACH = 180.0
RATCHET_HANDLE_WIDTH = 16.0
RATCHET_HANDLE_THICKNESS = 10.0


def socket_wall(hex_af: float, outer_radius: float, hex_band: tuple[float, float]) -> ToolSolid:
    """A socket's wall round the hex, in the local frame, up to where its bore starts.

    From the hex's lower edge up to :data:`CONTACT_OFFSET` over the seat. A
    socket slides down over the hex it grips, so its wall stands beside the
    hex's flats over their whole height: a rib beside a nut, no taller than it,
    is in the way (it used to be missed, the socket drawn from the seat up).
    """
    _, band_bottom = hex_band
    return axial_annulus(
        hex_af / sqrt(3) + RING_CLEARANCE, outer_radius, band_bottom, CONTACT_OFFSET - band_bottom
    )


def socket_attempts(
    mount: Mount,
    socket: Socket,
    hex_af: float,
    hex_band: tuple[float, float],
    scene: Scene,
    step_deg: float = DEFAULT_STEP_DEG,
    hand_room: bool = False,
) -> Iterator[Attempt]:
    """The socket on the ratchet directly, then on each stock extension, lazily.

    The socket's wall stands round the hex over its height (``hex_band``, as the
    ring's), with the hex's own corner sweep inside it; above the seat it is
    hollow for :data:`BORE_DEPTH` (the bolt's end goes into it), solid above,
    then the extension, then the ratchet head whose handle needs only
    :data:`RATCHET_72_SWING_DEG` of free arc.
    """
    tool = f"socket-{size_name(socket.af)}"
    inner = hex_af / sqrt(3) + RING_CLEARANCE
    mouth = (
        corner_sweep(hex_af, hex_band)
        + socket_wall(hex_af, socket.outer_radius, hex_band)
        + axial_annulus(inner, socket.outer_radius, CONTACT_OFFSET, min(BORE_DEPTH, socket.length))
    )
    body_from = CONTACT_OFFSET + BORE_DEPTH
    body_to = CONTACT_OFFSET + socket.length
    body = axial_cylinder(socket.outer_radius, body_from, body_to) if body_to > body_from else None
    for extension in (0.0, *EXTENSION_LENGTHS):
        head_from = body_to + extension
        stack = mouth if body is None else mouth + body
        if extension:
            stack = stack + axial_cylinder(EXTENSION_RADIUS, body_to, head_from)
        stack = stack + axial_cylinder(
            RATCHET_HEAD_RADIUS, head_from, head_from + RATCHET_HEAD_DEPTH
        )
        way = "socket on ratchet" if not extension else f"socket, {extension:g} mm extension"
        handle_z = head_from + RATCHET_HEAD_DEPTH / 2
        yield swing_attempt(
            tool=tool,
            way=way,
            scene=scene,
            engagement=mount.place(stack),
            arm_at=lambda phi, z=handle_z: mount.place(
                radial_box(
                    RATCHET_HANDLE_WIDTH,
                    RATCHET_HANDLE_THICKNESS,
                    RATCHET_HEAD_RADIUS + 1,
                    RATCHET_HANDLE_REACH,
                    z,
                    phi,
                )
            ),
            required_deg=RATCHET_72_SWING_DEG,
            step_deg=step_deg,
            hand_at=(
                (
                    lambda phi, z=handle_z: mount.place(
                        hand_on_handle(z, RATCHET_HEAD_RADIUS + 1, RATCHET_HANDLE_REACH, phi)
                    )
                )
                if hand_room
                else None
            ),
        )
