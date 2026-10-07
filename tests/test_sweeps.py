"""Tool sweeps against hand-computed scenes: the analytic cases, in memory.

Seat at the origin, axis +Z (toward the tool) throughout. Every boundary here is
computed in the test from the tool tables, never hardcoded from a prototype run.
Every test runs on both engines (the `scene_of` fixture, conftest.py).
"""

import math

import pytest
from build123d import Box, Cylinder, Pos

from wrenchroom.tools.hex_keys import ISO_2936, hex_key_attempts
from wrenchroom.tools.sockets import RATCHET_HEAD_RADIUS, socket_attempts, socket_for
from wrenchroom.tools.spanners import ring_attempts, spanner_for
from wrenchroom.tools.sweep import (
    CONTACT_OFFSET,
    Attempt,
    Mount,
    Probe,
    axial_cylinder,
    radial_cylinder,
    swing_attempt,
)

ORIGIN_MOUNT = Mount(seat=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0))


def run_until_turning(attempts):
    """Consume like the check loop will: stop at the first way that turns."""
    tried = []
    for attempt in attempts:
        tried.append(attempt)
        if attempt.turns:
            break
    return tried


def slab_above(gap, size=400, thick=10):
    """A wall facing the head: a big slab from z = gap upward."""
    return Pos(0, 0, gap + thick / 2) * Box(size, size, thick)


# ---------------------------------------------------------------------------
# The close-wall case: an M6 socket head (5 mm key) facing a wall along its axis.
# ---------------------------------------------------------------------------

KEY_5 = ISO_2936[5.0]
# Short leg in needs the leg along the axis plus the arm's own radius:
SHORT_LEG_CLEARANCE = CONTACT_OFFSET + KEY_5.short_mm + KEY_5.radius  # 36.135 mm


def test_a_close_wall_blocks_every_way_of_a_5mm_key(scene_of):
    scene = scene_of(wall=slab_above(15.0))
    tried = run_until_turning(hex_key_attempts(ORIGIN_MOUNT, KEY_5, scene))
    assert not any(a.turns for a in tried)
    assert all("wall" in a.blockers for a in tried)
    assert len(tried) == 3  # driver, short leg, long leg: all tried, all blocked


def test_the_boundary_flips_within_one_millimetre(scene_of):
    just_blocked = scene_of(wall=slab_above(SHORT_LEG_CLEARANCE - 0.5))
    tried = run_until_turning(hex_key_attempts(ORIGIN_MOUNT, KEY_5, just_blocked))
    assert not any(a.turns for a in tried)

    just_clear = scene_of(wall=slab_above(SHORT_LEG_CLEARANCE + 0.5))
    tried = run_until_turning(hex_key_attempts(ORIGIN_MOUNT, KEY_5, just_clear))
    winner = tried[-1]
    assert winner.turns
    assert winner.way == "short leg in"


def test_open_space_takes_the_driver_straight_in(scene_of):
    scene = scene_of(bystander=Pos(200, 0, 0) * Box(10, 10, 10))
    tried = run_until_turning(hex_key_attempts(ORIGIN_MOUNT, KEY_5, scene))
    assert tried[0].turns
    assert tried[0].way == "driver straight in"


# ---------------------------------------------------------------------------
# Ring spanner: the gland-spacing case, and holding between walls.
# ---------------------------------------------------------------------------

GLAND_AF = 22.0
GLAND_HEIGHT = 8.0
SPANNER_22 = spanner_for(GLAND_AF)


def gland_neighbour(distance):
    """The next gland's hex, as a cylinder of its circumradius, same height band."""
    circumradius = GLAND_AF / 3**0.5
    return Pos(distance, 0, -GLAND_HEIGHT / 2) * Cylinder(circumradius, GLAND_HEIGHT)


def ring_on_gland(scene):
    return run_until_turning(
        ring_attempts(ORIGIN_MOUNT, SPANNER_22, GLAND_AF, (0.0, -GLAND_HEIGHT), scene)
    )


def test_glands_25mm_apart_leave_no_room_for_a_ring(scene_of):
    # Ring outer radius 19.6; the neighbour's flank is 25 - 12.7 = 12.3 away.
    tried = ring_on_gland(scene_of(neighbour=gland_neighbour(25.0)))
    assert not any(a.turns for a in tried)
    assert all(a.blockers == ("neighbour",) for a in tried)
    assert not any(a.holds for a in tried)  # the ring itself cannot even get on


def test_glands_40mm_apart_take_the_ring(scene_of):
    tried = ring_on_gland(scene_of(neighbour=gland_neighbour(40.0)))
    winner = tried[-1]
    assert winner.turns
    assert winner.way == "ring, full length"
    assert "neighbour" in winner.blockers  # it blocked part of the arc, not enough


def test_walls_leaving_15_degrees_hold_but_do_not_turn(scene_of):
    # Two walls flanking the handle: free only around phi = 0, one 15 deg step.
    reach = 0.85 * SPANNER_22.length + 10
    # The back wall starts outside the ring itself (outer radius 19.6), or it would
    # block the engagement rather than the swing.
    scene = scene_of(
        left=Pos(reach / 2, 40, -GLAND_HEIGHT / 2) * Box(reach, 10, 30),
        right=Pos(reach / 2, -40, -GLAND_HEIGHT / 2) * Box(reach, 10, 30),
        back=Pos(-(reach + 25) / 2, 0, -GLAND_HEIGHT / 2) * Box(reach - 25, 200, 30),
    )
    tried = list(ring_attempts(ORIGIN_MOUNT, SPANNER_22, GLAND_AF, (0.0, -GLAND_HEIGHT), scene))
    assert not any(a.turns for a in tried)
    assert any(a.holds for a in tried)
    assert all(a.swing_deg < 30 for a in tried)


# ---------------------------------------------------------------------------
# Socket: a well too narrow for the ratchet head needs an extension.
# ---------------------------------------------------------------------------


def test_a_deep_well_needs_an_extension(scene_of):
    socket = socket_for(16.0)  # M10 nut
    assert socket.outer_radius < 14 < RATCHET_HEAD_RADIUS  # the well admits only the socket
    well = Pos(0, 0, 30) * Box(200, 200, 60) - Pos(0, 0, 30) * Cylinder(14, 61)
    scene = scene_of(well=well)
    band = (0.0, -8.0)  # an M10 nut's height below the seat
    tried = run_until_turning(socket_attempts(ORIGIN_MOUNT, socket, 16.0, band, scene))
    winner = tried[-1]
    assert winner.turns
    assert winner.way == "socket, 50 mm extension"
    assert tried[0].way == "socket on ratchet"
    assert not tried[0].turns


# ---------------------------------------------------------------------------
# The swing search itself.
# ---------------------------------------------------------------------------


def arm_probe(phi_deg):
    """A thin radial arm at z = 50, reaching to 100 mm."""
    return ORIGIN_MOUNT.place(radial_cylinder(2, 10, 100, 50, phi_deg))


def quarter_wall_at(phi_from, phi_to):
    """Obstacles filling the given angular range at the arm's height."""
    shapes = {}
    for index, phi in enumerate(range(int(phi_from), int(phi_to), 10)):
        rad = math.radians(phi)
        shapes[f"post_{index}"] = Pos(60 * math.cos(rad), 60 * math.sin(rad), 50) * Box(12, 12, 20)
    return shapes


def test_a_free_arc_across_zero_counts_whole(scene_of):
    # Posts from 60 to 300 degrees: the free arc is 300..360..60, through zero.
    scene = scene_of(**quarter_wall_at(60, 300))
    attempt = swing_attempt(
        tool="probe",
        way="probe",
        scene=scene,
        engagement=ORIGIN_MOUNT.place(axial_cylinder(1, 20, 30)),
        arm_at=arm_probe,
        required_deg=60.0,
    )
    assert attempt.turns
    assert attempt.swing_deg >= 60


def test_blocked_everywhere_neither_turns_nor_holds(scene_of):
    scene = scene_of(**quarter_wall_at(0, 360))
    attempt = swing_attempt(
        tool="probe",
        way="probe",
        scene=scene,
        engagement=ORIGIN_MOUNT.place(axial_cylinder(1, 20, 30)),
        arm_at=arm_probe,
        required_deg=60.0,
    )
    assert not attempt.turns
    assert not attempt.holds
    assert attempt.swing_deg == 0
    assert attempt.blockers  # names collected


def test_a_blocked_engagement_fails_without_sweeping(scene_of):
    scene = scene_of(cap=Pos(0, 0, 27) * Box(50, 50, 10))
    engagement = ORIGIN_MOUNT.place(axial_cylinder(1, 20, 30))
    attempt = swing_attempt(
        tool="probe",
        way="probe",
        scene=scene,
        engagement=engagement,
        arm_at=arm_probe,
        required_deg=60.0,
    )
    probes = (Probe(engagement, ("cap",)),)  # the engagement alone: no arm was tried
    assert attempt == Attempt("probe", "probe", False, False, 0.0, ("cap",), probes)


def test_fully_free_turns_and_stops_at_the_required_arc(scene_of):
    # The search stops as soon as the required arc is proven; swing_deg is what
    # was proven, not the whole free circle. That early stop is the speed story.
    attempt = swing_attempt(
        tool="probe",
        way="probe",
        scene=scene_of(far=Pos(500, 0, 0) * Box(10, 10, 10)),
        engagement=ORIGIN_MOUNT.place(axial_cylinder(1, 20, 30)),
        arm_at=arm_probe,
        required_deg=60.0,
    )
    assert attempt.turns
    assert attempt.swing_deg == pytest.approx(60.0)
