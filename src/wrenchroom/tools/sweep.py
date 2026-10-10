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

#: The hand on a turning tool's handle (spec 6.4), when hand room is checked: a
#: cylinder of this radius, mm, along the handle's last HAND_LENGTH mm (all of it, on
#: a shorter handle). The spec draws a capsule; square ends make this one a little
#: bigger at its corners, which errs toward finding no room. These are the spec's
#: figures, not yet tuned against real hands, which is why hand room is off unless a
#: sidecar or ``--hand-room`` asks for it.
#:
#: One placement differs from the spec's drawing, deliberately (2026-10-06): a hand
#: on a swinging handle rests on the side the tool came from, its underside on the
#: handle's mid-plane, rather than centred on the handle. Centred, a 35 mm hand round
#: a spanner lying 2.5 mm over the plate its nut sits on reaches 32 mm into the plate,
#: and every nut on a flat face would read "no room for a hand". On top, the face the
#: fastener sits on doesn't count, and a flange, ceiling or wall over the handle does.
#: A driver's hand stays a fist round its handle, which stands clear of everything.
#:
#: Two more choices, also deliberate: the hand stays on the handle, over its last
#: 90 mm but never nearer the axis than the handle starts (a stubby's short handle
#: gets a shorter hand, as fingers), so it never reaches back over the fastener and
#: a bolt's tail; and an L-key's arm gets no hand, being turned with the fingertips
#: at its end, which a 35 mm fist doesn't model (a key used as a driver does get one).
HAND_RADIUS = 35.0
HAND_LENGTH = 90.0


@dataclass(frozen=True)
class Mount:
    """Where a tool engages: the seat point and the axis pointing toward the tool."""

    seat: tuple[float, float, float]
    axis: tuple[float, float, float]

    def place(self, local: ToolSolid) -> ToolSolid:
        """Put a tool solid built in the local frame (seat at origin, axis +Z) here."""
        return local.placed(self.seat, self.axis)


@dataclass(frozen=True)
class Probe:
    """One tool position tested, and every part it ran into: what the HTML view draws.

    Attributes:
        solid: The tool solid as placed for the test.
        hits: The parts it overlapped, in assembly order; empty when it was clear.
        grazes: The parts it only grazed: overlapped by no more than the hit floor.
    """

    solid: ToolSolid
    hits: tuple[str, ...]
    grazes: tuple[str, ...] = ()


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
        probes: Every position tested, in order: the engagement (or the whole
            tool, for one that turns in place) first, then each arm position the
            swing search tried, each followed by the hand there when hand room
            is checked.
        hand_blockers: What the hand ran into, where the tool itself was clear.
        no_hand_room: The tool alone would turn (or hold) this way, and the
            hand can't follow it: the spec's ``blocked (no room for a hand)``.
        grazes: What the tool only grazed at positions it was clear at: an
            overlap no more than the hit floor, a key rubbing along a face.
            A report says so when the attempt decides a verdict (issue #25).
        bounds: When the swing found some free arc but not enough, what stood
            at each end of the best one: the parts that decided it, out of all
            the blockers (issue #52). The hand's, where only the hand was
            stopped; and where the tool alone would turn or hold and the hand
            can't follow it, what the hand ran into along the tool's best arc.
        required_deg: The arc the tool needs to turn, for a swing search.
    """

    tool: str
    way: str
    turns: bool
    holds: bool
    swing_deg: float
    blockers: tuple[str, ...]
    probes: tuple[Probe, ...] = ()
    hand_blockers: tuple[str, ...] = ()
    no_hand_room: bool = False
    grazes: tuple[str, ...] = ()
    bounds: tuple[str, ...] = ()
    required_deg: float = 0.0


def swing_attempt(  # noqa: PLR0913  (keyword-only: one per thing a swing tries)
    *,
    tool: str,
    way: str,
    scene: Scene,
    engagement: ToolSolid | None,
    arm_at: Callable[[float], ToolSolid],
    required_deg: float,
    step_deg: float = DEFAULT_STEP_DEG,
    hand_at: Callable[[float], ToolSolid] | None = None,
    way_at: Callable[[float], ToolSolid] | None = None,
) -> Attempt:
    """Try an engagement solid, then search the arm's swing.

    The engagement (the part of the tool on the fastener, the same at every
    angle: a ring, a key's leg) must be clear or the attempt fails outright with
    its blockers. Then the arm is sampled around the circle: `turns` needs
    ``required_deg`` of contiguous free arc, `holds` needs any one free position.
    A tool whose grip turns with its handle (an open-end jaw) has no separate
    engagement: ``engagement`` is None and ``arm_at`` is the whole tool. With
    ``hand_at``, a position is free only when the hand there is clear too; the
    hand is tested only where the arm is, so a check without hand room costs
    exactly what it did. With ``way_at``, the arm is clear at a position only
    where the way it came there is clear too: a ring's handle, come down the
    axis with it (issue #143). That way is tested only where the arm is clear,
    and drawn only where it is what stopped the tool.
    """
    blockers: list[str] = []
    hand_blockers: list[str] = []
    grazed: list[str] = []
    probes: list[Probe] = []
    if engagement is not None:
        engagement_hits, engagement_grazes = scene.contacts(engagement)
        probes.append(Probe(engagement, engagement_hits, engagement_grazes))
        if engagement_hits:
            return Attempt(tool, way, False, False, 0.0, engagement_hits, tuple(probes))
        _note(grazed, engagement_grazes)

    samples = max(1, round(FULL_CIRCLE / step_deg))
    arm_hits: dict[int, tuple[str, ...]] = {}
    hand_hits: dict[int, tuple[str, ...]] = {}

    def arm_is_clear(index: int) -> bool:
        if index not in arm_hits:
            hits, grazes = _arm_contacts(scene, arm_at, way_at, index * step_deg, probes)
            _note(blockers, hits)
            _note(grazed, () if hits else grazes)  # a graze where the arm was clear
            arm_hits[index] = hits
        return not arm_hits[index]

    def is_free(index: int) -> bool:
        if not arm_is_clear(index):
            return False
        if hand_at is None:
            return True
        if index not in hand_hits:
            hand = hand_at(index * step_deg)
            hits = scene.hits(hand)
            probes.append(Probe(hand, hits))
            _note(hand_blockers, hits)
            hand_hits[index] = hits
        return not hand_hits[index]

    best, end = _longest_run(is_free, samples, step_deg, required_deg)
    swing = _swing(best, samples, step_deg)
    turns = swing >= required_deg
    holds = best >= 1
    no_hand_room = False
    bounds = () if turns else _bounds(best, end, samples, arm_hits, hand_hits)
    if hand_at is not None and not turns:
        alone, alone_end = _longest_run(arm_is_clear, samples, step_deg, required_deg)
        alone_turns = _swing(alone, samples, step_deg) >= required_deg
        no_hand_room = alone_turns or (alone >= 1 and not holds)
        # Where the tool alone would do, what stopped the hand along its best arc.
        bounds = _hand_bounds(alone, alone_end, samples, hand_hits) if no_hand_room else bounds
    return Attempt(
        tool,
        way,
        turns,
        holds,
        swing,
        tuple(blockers),
        tuple(probes),
        tuple(hand_blockers),
        no_hand_room,
        tuple(grazed),
        bounds,
        required_deg,
    )


def _arm_contacts(
    scene: Scene,
    arm_at: Callable[[float], ToolSolid],
    way_at: Callable[[float], ToolSolid] | None,
    phi: float,
    probes: list[Probe],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """What the arm at an angle hit and grazed, and the way it came there, where it is clear.

    The arm is drawn always, its way only where it hit something.
    """
    arm = arm_at(phi)
    hits, grazes = scene.contacts(arm)
    probes.append(Probe(arm, hits, grazes))
    if hits or way_at is None:
        return hits, grazes
    way = way_at(phi)
    way_hits, way_grazes = scene.contacts(way)
    if way_hits:
        probes.append(Probe(way, way_hits, way_grazes))
    return way_hits, (*grazes, *way_grazes)


def _hand_bounds(
    run: int, end: int, samples: int, hand_hits: dict[int, tuple[str, ...]]
) -> tuple[str, ...]:
    """What the hand ran into along the tool's best arc, the ``run`` positions to ``end``."""
    found: list[str] = []
    for k in range(run):
        _note(found, hand_hits.get((end - k) % samples, ()))
    return tuple(found)


def _bounds(
    best: int,
    end: int,
    samples: int,
    arm_hits: dict[int, tuple[str, ...]],
    hand_hits: dict[int, tuple[str, ...]],
) -> tuple[str, ...]:
    """What stopped the best arc at each end: the arm's hits there, else the hand's."""
    if best < 1:
        return ()
    bounds: list[str] = []
    for index in ((end - best) % samples, (end + 1) % samples):
        _note(bounds, arm_hits.get(index) or hand_hits.get(index, ()))
    return tuple(bounds)


def _note(seen: list[str], hits: tuple[str, ...]) -> None:
    for name in hits:
        if name not in seen:
            seen.append(name)


def _longest_run(
    is_free: Callable[[int], bool], samples: int, step_deg: float, required_deg: float
) -> tuple[int, int]:
    """The longest run of free positions, and the position it ends at.

    The search stops as soon as the required arc is proven. The circle is walked
    twice so a run across 0 degrees counts whole; the second lap stops at the
    first blocked position, having nothing more to add. Short of the required
    arc, every position has been tried, and the ones either side of the longest
    run, which stopped it, were among them.
    """
    run = 0
    best = 0
    end = 0
    for position in range(2 * samples):
        if not is_free(position % samples):
            run = 0
            if position >= samples:
                break  # second lap adds nothing once a wall is seen again
            continue
        run = min(run + 1, samples)
        if run > best:
            best, end = run, position % samples
        if run == samples or (run - 1) * step_deg >= required_deg:
            break
    return best, end


def _swing(best: int, samples: int, step_deg: float) -> float:
    """The arc ``best`` consecutive free positions prove, degrees."""
    return FULL_CIRCLE if best == samples else max(0.0, (best - 1) * step_deg)


def straight_attempt(
    *, tool: str, way: str, scene: Scene, solid: ToolSolid, hand: ToolSolid | None = None
) -> Attempt:
    """Try a tool that turns in place: clear means it turns, blocked means it doesn't.

    With ``hand``, the hand round the handle must be clear too.
    """
    hits, grazes = scene.contacts(solid)
    probes = [Probe(solid, hits, grazes)]
    hand_hits: tuple[str, ...] = ()
    if not hits and hand is not None:
        hand_hits = scene.hits(hand)
        probes.append(Probe(hand, hand_hits))
    ok = not hits and not hand_hits
    return Attempt(
        tool,
        way,
        ok,
        ok,
        FULL_CIRCLE if ok else 0.0,
        hits,
        tuple(probes),
        hand_hits,
        no_hand_room=bool(hand_hits),
        grazes=() if hits else grazes,
    )


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


def hand_on_handle(z: float, start: float, reach: float, phi_deg: float) -> ToolSolid:
    """The hand on a handle from ``start`` to ``reach`` from the axis, lying at height ``z``.

    It covers the handle's last HAND_LENGTH mm, or all of a shorter one, and rests
    on it from the side the tool came from: its underside on the handle's
    mid-plane, so the face the fastener sits on is never in its way.
    """
    near = max(start, reach - HAND_LENGTH)
    return radial_cylinder(HAND_RADIUS, near, reach, z + HAND_RADIUS, phi_deg)


def radial_box(
    width: float,
    thickness: float,
    r_from: float,
    r_to: float,
    z: float,
    phi_deg: float,
    offset: float = 0.0,
) -> ToolSolid:
    """A box along ``u(phi)``: a handle, a jaw's arm.

    ``width`` is tangential, ``thickness`` axial, ``offset`` a sideways shift off
    the line through the axis.
    """
    return ToolSolid((RadialBox(width, thickness, r_from, r_to, z, phi_deg, offset),))


def axial_annulus(inner: float, outer: float, z_from: float, thickness: float) -> ToolSolid:
    """A ring around the local axis, ``thickness`` long from ``z_from``."""
    return ToolSolid((AxialRing(inner, outer, z_from, z_from + thickness),))
