"""Fingers round a fastener turned by hand: a thumb screw, a wing nut (issue #96).

No tool fits one, but it still needs room, for the fingers that grip its widest part
(a knurled head, the wings) and turn it. Two ways are tried, each in place, as a
driver is. First the fingers round it: a ring a fingertip thick round the grip, as
deep as the grip, and the fingers over its end, must be clear. Then a fingertip on
its rim from any one side, rolling it, as a thumb wheel in a window is turned: a
fingertip reaching straight out from the rim must be clear somewhere round it. With
hand room checked, the hand behind the fingers must be clear too. The fingers leave
a nut's bolt alone: what comes out through its bore is no finger's business, as it
is no socket's.

The figures are a hand's, not a standard's, and like the hand on a tool's handle
(sweep.py) they are approximations, not yet tuned against real hands: a fingertip is
about 15 mm wide and 12 thick, pinching a knurled head the fingers reach about 25 mm
over its end before the hand begins, and a fingertip pressing a rim is about 8 mm
across and 30 long before the hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wrenchroom.tools.sweep import (
    CONTACT_OFFSET,
    FULL_CIRCLE,
    HAND_LENGTH,
    HAND_RADIUS,
    Attempt,
    Mount,
    Probe,
    axial_annulus,
    axial_cylinder,
    hand_on_handle,
    radial_cylinder,
    straight_attempt,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from wrenchroom.engine import Scene
    from wrenchroom.solids import ToolSolid

#: What a by-hand fastener's result names as its tool, and a rule's ``tool:`` may.
HAND = "hand"

#: A fingertip's thickness round the grip, mm.
FINGER_MM = 12.0

#: How far over the fastener's end the fingers reach before the hand, mm.
FINGER_REACH = 25.0

#: A fingertip pressing a rim, rolling it: its radius, and how far out from the rim
#: it runs before the hand, mm.
FINGERTIP_RADIUS = 4.0
FINGER_LENGTH = 30.0


def finger_solid(grip_radius: float, grip_depth: float, bore_radius: float) -> ToolSolid:
    """The fingers, in the local frame: round the grip, then over the fastener's end.

    ``grip_radius`` is how far out the grip reaches, ``grip_depth`` how far it runs
    down from the end (the seat), and ``bore_radius`` what the fingers leave free
    over the end: a nut's bolt, 0 for a screw.
    """
    inner = grip_radius + CONTACT_OFFSET
    outer = inner + FINGER_MM
    depth = max(grip_depth - CONTACT_OFFSET, CONTACT_OFFSET)
    ring = axial_annulus(inner, outer, -depth, depth)
    return ring + _over(bore_radius, outer, CONTACT_OFFSET, FINGER_REACH)


def hand_over(grip_radius: float, bore_radius: float) -> ToolSolid:
    """The hand above the fingers, in the local frame: checked only with hand room."""
    reach = max(HAND_RADIUS, grip_radius + CONTACT_OFFSET + FINGER_MM)
    return _over(bore_radius, reach, CONTACT_OFFSET + FINGER_REACH, HAND_LENGTH)


def _over(bore_radius: float, radius: float, z_from: float, length: float) -> ToolSolid:
    """Over the end: a disc over a screw's, a ring round a nut's bolt."""
    if bore_radius <= 0:
        return axial_cylinder(radius, z_from, z_from + length)
    return axial_annulus(bore_radius, radius, z_from, length)


def finger_attempts(
    mount: Mount,
    scene: Scene,
    grip_radius: float,
    grip_depth: float,
    bore_radius: float,
    *,
    nut: bool,
    step_deg: float,
    hand_room: bool = False,
) -> Iterator[Attempt]:
    """The fingers round the grip, then a fingertip on its rim: each one in-place test."""
    what = "it" if nut else "its head"
    yield straight_attempt(
        tool=HAND,
        way=f"fingers round {what}",
        scene=scene,
        solid=mount.place(finger_solid(grip_radius, grip_depth, bore_radius)),
        hand=mount.place(hand_over(grip_radius, bore_radius)) if hand_room else None,
    )
    yield rim_attempt(mount, scene, grip_radius, grip_depth, step_deg, hand_room=hand_room)


def rim_attempt(
    mount: Mount,
    scene: Scene,
    grip_radius: float,
    grip_depth: float,
    step_deg: float,
    *,
    hand_room: bool = False,
) -> Attempt:
    """A fingertip on the rim from any one side, every ``step_deg`` round: the first clear.

    At two heights: level with the middle of the grip, as through a window onto a
    wheel; and resting on what the grip sits on, as on a knurled head flat on a
    plate, which a fingertip thicker than the head still presses. Blocked all
    round, it names everything any fingertip met, and the hand's blockers where
    only the hand was stopped.
    """
    way = "a fingertip on its rim"
    start = grip_radius + CONTACT_OFFSET
    middle = -grip_depth / 2
    resting = -grip_depth + CONTACT_OFFSET + FINGERTIP_RADIUS
    heights = (middle, resting) if resting > middle else (middle,)
    steps = max(1, round(FULL_CIRCLE / step_deg))
    blockers: list[str] = []
    hand_blockers: list[str] = []
    probes: list[Probe] = []
    for height in heights:
        for index in range(steps):
            phi = index * FULL_CIRCLE / steps
            finger = radial_cylinder(FINGERTIP_RADIUS, start, start + FINGER_LENGTH, height, phi)
            reach = start + FINGER_LENGTH
            hand = hand_on_handle(height, reach, reach + HAND_LENGTH, phi)  # on the finger
            attempt = straight_attempt(
                tool=HAND,
                way=way,
                scene=scene,
                solid=mount.place(finger),
                hand=mount.place(hand) if hand_room else None,
            )
            if attempt.turns:
                return attempt
            probes.extend(attempt.probes)
            blockers.extend(name for name in attempt.blockers if name not in blockers)
            hand_blockers.extend(n for n in attempt.hand_blockers if n not in hand_blockers)
    return Attempt(
        HAND,
        way,
        turns=False,
        holds=False,
        swing_deg=0.0,
        blockers=tuple(blockers),
        probes=tuple(probes),
        hand_blockers=tuple(hand_blockers),
        no_hand_room=bool(hand_blockers),
    )
