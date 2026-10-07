"""The golden bench's cells: one mechanism each, truth worked out by hand.

Each cell's docstring is the hand-work: why the expected verdict is what it is,
computed from the tool tables (ISO 2936 5 mm key: long 85, short 33, shaft radius
2.835; contact offset 0.3; ring and socket from spanner_for / socket_for). Truth
changes only when the physics changes, never to match the tool's output.

A truth entry may carry "needs": the milestone or issue that must land before it
can pass; the test turns that into a strict xfail. Deciding gaps keep at least
1.5 mm of margin against table refinements; swing limits sit mid-band (22 deg for
a ring that turns at 30, 36 deg for a key that turns at 60) so 15 deg sampling
cannot change the answer.
"""

import math
from dataclasses import dataclass, field

from build123d import Box, Compound, Cylinder, Pos, Rot, Torus
from parts import (
    button_screw,
    carriage_bolt,
    gland,
    hex_bolt,
    hex_nut,
    pan_phillips,
    plate,
    slab,
    slot_block,
    socket_screw,
)


@dataclass(frozen=True)
class Cell:
    """One bench cell: parts (built fresh per call), sidecar rules, truth."""

    name: str
    build: object  # () -> list[(role, shape)]
    rules: tuple = ()
    truth: dict = field(default_factory=dict)
    ignore: tuple = ()
    #: In the perf bench's timed copies. False for a deliberate worst case (a key
    #: grazing at every angle, every position of which the exact engine decides),
    #: which the perf script times apart: the budget is for ordinary geometry.
    timed: bool = True


M6_SOCKET = {"kind": "screw", "head": "socket", "size": "M6"}

CELLS = []


def cell(name, rules=(), truth=None, ignore=(), timed=True):
    def register(build):
        CELLS.append(Cell(name, build, tuple(rules), truth or {}, tuple(ignore), timed))
        return build

    return register


# ---------------------------------------------------------------- 5.1 keys, drivers, spanners


@cell(
    "key_wall_near",
    [{"parts": "screw", **M6_SOCKET}],
    {"screw": {"verdict": "blocked", "tool": "hex-key-5", "blocked_by": ["wall"]}},
)
def key_wall_near():
    """Driver needs 200; short leg tops out at 0.3 + 33 + 2.835 = 36.1; long 88. All > 15."""
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", socket_screw()),
        ("wall", slab(6 + 15)),
    ]


@cell(
    "key_wall_far",
    [{"parts": "screw", **M6_SOCKET}],
    {"screw": {"verdict": "turns", "tool": "hex-key-5", "how": "short leg in"}},
)
def key_wall_far():
    """45 clears the short leg's 36.1 by 8.9; driver and long leg still blocked."""
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", socket_screw()),
        ("wall", slab(6 + 45)),
    ]


@cell(
    "key_open",
    [{"parts": "screw", **M6_SOCKET}],
    {"screw": {"verdict": "turns", "tool": "hex-key-5", "how": "driver straight in"}},
)
def key_open():
    """Nothing above: the driver wins first."""
    return [("plate", plate(holes=[(0, 0, 3)])), ("screw", socket_screw())]


@cell(
    "key_long_leg",
    [{"parts": "screw", "kind": "screw", "head": "button", "size": "M6"}],
    {"screw": {"verdict": "turns", "tool": "hex-key-4", "how": "long leg in"}},
)
def key_long_leg():
    """Head at the bottom of a bore d16 x 50; ceiling 110 up. The driver's handle
    (100.3..200.3) hits the ceiling; the short leg's arm at 29.3 hits the bore;
    the long leg (74) reaches out and swings at 74.3 +/- 2.3 with 20+ mm each way."""
    block = Pos(0, 0, 25) * Box(120, 120, 50) - Pos(0, 0, 25) * Cylinder(8, 51)
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", button_screw()),
        ("block", block),
        ("ceiling", slab(3.3 + 110)),
    ]


@cell(
    "hex_side_wall",
    [{"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"}],
    {"bolt": {"verdict": "turns", "tool": "spanner-13", "how": "ring, full length"}},
)
def hex_side_wall():
    """The ring (outer r 12.4) clears a wall 40 from the axis; the handle keeps
    about 200 deg of free circle away from it."""
    return [
        ("plate", plate(holes=[(0, 0, 4)])),
        ("bolt", hex_bolt(8, 25, 13, 5.3)),
        ("wall", Pos(45, 0, 30) * Box(10, 300, 60)),
    ]


@cell(
    "nut_stubby_box",
    [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M6"},
        {"parts": "nut", "kind": "nut", "size": "M6"},
    ],
    {
        "bolt": {"verdict": "turns", "tool": "spanner-10", "how": "ring, full length"},
        "nut": {"verdict": "turns", "tool": "spanner-10", "how": "ring, stubby"},
    },
)
def nut_stubby_box():
    """Inside 180 x 180 walls the full handle (reach 114.8 > half-width 90) never
    turns; the stubby (reach 63.1, corner 63.3) swings all round. A real stubby
    10 (100..115 long) also fits near the diagonals, so a table fix keeps this."""
    box = Pos(0, 0, 20) * Box(200, 200, 40) - Pos(0, 0, 20) * Box(180, 180, 41)
    return [
        ("floor", plate(holes=[(0, 0, 3)])),
        ("box", box),
        ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(6, 20, 10, 4.0)),
        ("nut", hex_nut(6, 10, 5.2)),
    ]


@cell(
    "nut_deep_well",
    [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M10"},
        {"parts": "nut", "kind": "nut", "size": "M10"},
    ],
    {
        "bolt": {"verdict": "turns", "tool": "spanner-16", "how": "ring, full length"},
        "nut": {"verdict": "turns", "tool": "socket-16", "how": "socket, 50 mm extension"},
    },
)
def nut_deep_well():
    """The ring (outer r 14.8) can't enter r 12.5; the socket (r 10.8) can; the
    ratchet head (r 17) sits inside the well without an extension and clear of
    its top (60) with 50 mm."""
    block = Pos(0, 0, 30) * Box(200, 200, 60) - Pos(0, 0, 30) * Cylinder(12.5, 61)
    return [
        ("plate", plate(holes=[(0, 0, 5)])),
        ("block", block),
        ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(10, 25, 16, 6.4)),
        ("nut", hex_nut(10, 16, 8.4)),
    ]


@cell(
    "phillips_open",
    [{"parts": "screw", "kind": "screw", "head": "phillips", "size": "M4"}],
    {"screw": {"verdict": "turns", "tool": "driver-ph2", "how": "driver straight in"}},
)
def phillips_open():
    """Open air: the driver turns in place."""
    return [("plate", plate(holes=[(0, 0, 2)])), ("screw", pan_phillips())]


@cell(
    "phillips_shelf",
    [{"parts": "screw", "kind": "screw", "head": "phillips", "size": "M4"}],
    {"screw": {"verdict": "blocked", "tool": "driver-ph2", "blocked_by": ["shelf"]}},
)
def phillips_shelf():
    """The driver is 200 mm of shaft and handle; the shelf is 50 up."""
    return [
        ("plate", plate(holes=[(0, 0, 2)])),
        ("screw", pan_phillips()),
        ("shelf", slab(3.1 + 50)),
    ]


@cell(
    "tapped_hold",
    [{"parts": "screw", **M6_SOCKET}],
    {"screw": {"verdict": "blocked", "tool": "hex-key-5"}},
)
def tapped_hold():
    """The M2 guard: holding must not pass a screw with no nut. The ceiling stops
    driver and long leg; the slot leaves the short leg's arm W = 36 deg < 60."""
    half_width = 2.835 + 60 * math.tan(math.radians(18))
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", socket_screw()),
        ("slot", slot_block(30, 48, 12, half_width)),
        ("ceiling", slab(51)),
    ]


# ---------------------------------------------------------------- 5.2 glands, ignores, mates


def _gland_pair(apart):
    a, b = -apart / 2, apart / 2

    def build():
        parts = [("plate", plate(w=300, d=200, holes=[(a, 0, 10), (b, 0, 10)]))]
        for tag, x in (("a", a), ("b", b)):
            parts.append((f"{tag}_gland", Pos(x, 0, 0) * gland()))
            parts.append((f"{tag}_cable", Pos(x, 0, 60) * Cylinder(4, 220)))
        return parts

    return build


GLAND_RULE = {"parts": "*_gland", "kind": "nut", "size": "M16", "socket": False}

CELLS.append(
    Cell(
        "glands_close",
        _gland_pair(32.0),
        (GLAND_RULE,),
        {
            # The neighbour's corner is 32 - 13.9 = 18.1 from the axis, inside the
            # ring's outer r 21.2: no ring. The socket (r 15.6) would fit and pass
            # falsely over the ignored cable: socket: false is what makes this right
            # (test_socket_flag_matters proves the flag is load-bearing). Until M6
            # that left both blocked. The open end (M6) is the side approach this
            # cell was waiting for (GOLDEN-BENCH section 6): handle pointing away
            # from the neighbour, the jaw (52 wide, tips 12 past the centre) stops
            # 6 short of its corner, and the arms' outer tip corners (r 28.6, 65 deg
            # off the line of centres) swing +/-15 deg while the neighbour spans
            # +/-23 deg at that radius; the gland's own corners (r 13.9, 14.2 with
            # the clearance) clear the neighbour's 18.1, so it can turn at all.
            "a_gland": {
                "verdict": "turns",
                "tool": "spanner-24",
                "how": "open end, full length",
            },
            "b_gland": {
                "verdict": "turns",
                "tool": "spanner-24",
                "how": "open end, full length",
            },
        },
        ("*_cable",),
    )
)

CELLS.append(
    Cell(
        "glands_apart",
        _gland_pair(60.0),
        (GLAND_RULE,),
        {
            "a_gland": {"verdict": "turns", "tool": "spanner-24", "how": "ring, full length"},
            "b_gland": {"verdict": "turns", "tool": "spanner-24", "how": "ring, full length"},
        },
        ("*_cable",),
    )
)


@cell(
    "gland_rib",
    [{"parts": "gland", "kind": "nut", "size": "M16", "socket": False, "axis": "+z"}],
    {"gland": {"verdict": "blocked", "tool": "spanner-24", "blocked_by": ["rib"]}},
    ignore=["*_cable"],
)
def gland_rib():
    """The ring must sit on the hex (0..8 up), where the rib (top at 6, inner
    face 16 from the axis, ring outer r 21.2) is in the way; the dome above is
    round and grips nothing. Axis given on purpose: this tests placement alone.
    The open end (M6), handle away from the rib, holds at that one angle (tips
    at 12, short of 16) but swung 15 deg its arms' outer tips reach 18.3, into
    the rib: it holds, can't turn, and with no partner it stays blocked."""
    return [
        ("plate", plate(holes=[(0, 0, 10)])),
        ("gland", gland()),
        ("rib", Pos(22, 0, 3) * Box(12, 80, 6)),
        ("cable", Pos(0, 0, 60) * Cylinder(4, 220)),
    ]


@cell(
    "wire_across",
    [{"parts": "screw", **M6_SOCKET}],
    {"screw": {"verdict": "turns", "tool": "hex-key-5", "how": "driver straight in"}},
    ignore=["*_cable"],
)
def wire_across():
    """A cable lying 10 over the head pushes aside: ignored, so the driver wins."""
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", socket_screw()),
        ("cable", Pos(0, 0, 6 + 10 + 4) * Rot(90, 0, 0) * Cylinder(4, 300)),
    ]


@cell(
    "nyloc_two_bodies",
    [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M6"},
        {"parts": "nut", "kind": "nut", "size": "M6", "mates": ["do*"]},
    ],
    {
        "bolt": {"verdict": "turns", "tool": "spanner-10", "how": "ring, full length"},
        "nut": {"verdict": "turns", "tool": "spanner-10", "how": "ring, full length"},
    },
)
def nyloc_two_bodies():
    """A nyloc modelled as nut + separate nylon dome: the dome is a mate, so it
    leaves the nut's scene and the free face reads clear. The mate is named by a
    glob, as a sidecar may (issue #32: a glob used to match nothing, silently)."""
    dome = Pos(0, 0, 5.2 + 1.25) * (Cylinder(4.8, 2.5) - Cylinder(3, 3))
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(6, 20, 10, 4.0)),
        ("nut", hex_nut(6, 10, 5.2)),
        ("dome", dome),
    ]


@cell(
    "carriage_boxed",
    [
        {"parts": "bolt", "head": "carriage", "size": "M6"},
        {"parts": "nut", "kind": "nut", "size": "M6"},
    ],
    {
        "bolt": {"verdict": "held", "how": "holds itself"},
        "nut": {"verdict": "turns", "tool": "spanner-10", "how": "ring, full length"},
    },
)
def carriage_boxed():
    """The dome is sealed in a box and that is fine: a carriage bolt holds
    itself. Its nut, open underneath, does the turning."""
    box = Pos(0, 0, 25) * Box(70, 70, 50) - Pos(0, 0, 22.5) * Box(60, 60, 45)
    pl = plate(t=6) - Pos(0, 0, -3) * Box(6, 6, 7) - Pos(0, 0, -3) * Cylinder(3, 7)
    return [
        ("plate", pl),
        ("box", box),
        ("bolt", carriage_bolt()),
        ("nut", Pos(0, 0, -6) * Rot(180, 0, 0) * hex_nut(6, 10, 5.2)),
    ]


# ---------------------------------------------------------------- 5.3 pairs, extraction, states


def _pocket(half_angle_deg, z0, z1):
    half_width = 6.85 + 60 * math.tan(math.radians(half_angle_deg))
    return slot_block(z0, z1, 16, half_width)


@cell(
    "pair_nut_held",
    [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"},
        {"parts": "nut", "kind": "nut", "size": "M8"},
    ],
    {
        "bolt": {"verdict": "turns", "tool": "spanner-13", "how": "ring, full length"},
        # A nut usually only needs holding: the slot leaves ~22 deg (holds, never
        # turns), the floor 12 below rules out every socket, and the head side
        # turns, so the joint passes once pairs land.
        "nut": {"verdict": "held", "tool": "spanner-13", "pair": "bolt"},
    },
)
def pair_nut_held():
    nut_face = -10 - 6.8
    pocket = _pocket(11, nut_face - 12, -10)
    pocket = pocket + Pos(0, 0, nut_face - 12 - 5) * Box(120, 120, 10)
    return [
        ("upper", plate(t=5, holes=[(0, 0, 4)])),
        ("lower", plate(t=5, z_top=-5, holes=[(0, 0, 4)])),
        ("bolt", hex_bolt(8, 25, 13, 5.3)),
        ("nut", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_nut(8, 13, 6.8)),
        ("pocket", pocket),
    ]


@cell(
    "pair_both_hold",
    [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"},
        {"parts": "nut", "kind": "nut", "size": "M8"},
    ],
    {
        # Each side only holds; a joint needs one side to turn, so both fail.
        "bolt": {"verdict": "blocked", "tool": "spanner-13"},
        "nut": {"verdict": "blocked", "tool": "spanner-13"},
    },
)
def pair_both_hold():
    nut_face = -10 - 6.8
    low = _pocket(11, nut_face - 12, -10) + Pos(0, 0, nut_face - 12 - 5) * Box(120, 120, 10)
    high = _pocket(11, 0, 5.3 + 12) + Pos(0, 0, 5.3 + 12 + 5) * Box(120, 120, 10)
    return [
        ("upper", plate(t=5, holes=[(0, 0, 4)])),
        ("lower", plate(t=5, z_top=-5, holes=[(0, 0, 4)])),
        ("bolt", hex_bolt(8, 25, 13, 5.3)),
        ("nut", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_nut(8, 13, 6.8)),
        ("pocket_low", low),
        ("pocket_high", high),
    ]


@cell(
    "stuck_screw",
    [{"parts": "screw", **M6_SOCKET}],
    {
        # Turns by the short leg (36.1 < 45) but drawn out 50 along its axis the
        # head rises into the ceiling at 45: reachable and still impossible.
        "screw": {"verdict": "stuck", "tool": "hex-key-5", "stuck_on": ["ceiling"]}
    },
)
def stuck_screw():
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", socket_screw(length=50)),
        ("ceiling", slab(6 + 45)),
    ]


@cell(
    "free_screw",
    [{"parts": "screw", **M6_SOCKET}],
    {"screw": {"verdict": "turns", "tool": "hex-key-5", "how": "short leg in"}},
)
def free_screw():
    """The ceiling at 60 clears extraction (50) by 10: guards against a false stuck."""
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", socket_screw(length=50)),
        ("ceiling", slab(6 + 60)),
    ]


@cell(
    "state_lid",
    [{"parts": "screw", **M6_SOCKET, "state": "lid-off"}],
    {
        "screw": {
            "verdict": "turns",
            "tool": "hex-key-5",
            "how": "driver straight in",
            "state": "lid-off",
        }
    },
)
def state_lid():
    """Reached with the lid off: the sidecar's lid-off state removes the lid."""
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", socket_screw()),
        ("lid", slab(6 + 15)),
    ]


@cell(
    "state_lever",
    [{"parts": "screw", **M6_SOCKET}],
    {
        "screw": {
            "verdict": "turns",
            "tool": "hex-key-5",
            "how": "driver straight in",
            "state": "lever-up",
        }
    },
)
def state_lever():
    """A bar lies 15 over the screw; bench_lever-up.step has it swung 80 deg up.
    try_states finds the screw reachable there and says so."""
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", socket_screw()),
        ("lever", Pos(0, 0, 6 + 15 + 5) * Box(220, 30, 10)),
    ]


def _collared_nut(bolt_length):
    def build():
        collar = Pos(0, 0, 4) * (Cylinder(40, 8) - Cylinder(12.6, 9))
        return [
            ("plate", plate(holes=[(0, 0, 5)])),
            ("collar", collar),
            ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(10, bolt_length, 16, 6.4)),
            ("nut", hex_nut(10, 16, 8.4)),
        ]

    return build


CELLS.append(
    Cell(
        "tail_in_socket",
        _collared_nut(30),
        (
            {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M10"},
            {"parts": "nut", "kind": "nut", "size": "M10"},
        ),
        {
            "bolt": {"verdict": "turns", "tool": "spanner-16", "how": "ring, full length"},
            # The collar stops the ring (r 14.8); the socket fits (r 10.8) and the
            # bolt's end, 11.6 past the nut, goes into the 15 mm bore.
            "nut": {"verdict": "turns", "tool": "socket-16", "how": "socket on ratchet"},
        },
    )
)

CELLS.append(
    Cell(
        "tail_too_long",
        _collared_nut(60),
        (
            {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M10"},
            {"parts": "nut", "kind": "nut", "size": "M10"},
        ),
        {
            "bolt": {"verdict": "turns", "tool": "spanner-16", "how": "ring, full length"},
            # 41.6 of tail: no socket swallows it. The M2 guard for "a nut's own
            # bolt isn't an obstacle": the partner leaves the ring's way, but its
            # end past the socket's bore still counts.
            "nut": {"verdict": "blocked", "blocked_by": ["collar", "bolt"]},
        },
    )
)


# ---------------------------------------------------------------- 5.5 config edges


@cell(
    "torx_open",
    truth={"screw": {"verdict": "turns", "tool": "hex-key-5", "how": "driver straight in"}},
)
def torx_open():
    """No rule names this screw in the main sidecar: detection finds it (its name
    ends in "screw") and its solid shows a 5 mm hex socket, so it turns by the
    key. Its name says torx too, but a drive the solid shows outranks the name;
    detect's comment says the two disagree. bench_edges.yaml describes it as
    head: torx, and a rule outranks detection: there it takes the full kit's T30
    Torx key (test_config_edges)."""
    return [("plate", plate(holes=[(0, 0, 3)])), ("screw", socket_screw())]


# ---------------------------------------------------------------- M6 cells


@cell(
    "hand_tight",
    [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M6"},
        {"parts": "nut", "kind": "nut", "size": "M6"},
    ],
    {
        "bolt": {"verdict": "turns", "tool": "spanner-10", "how": "ring, full length"},
        "nut": {"verdict": "turns", "tool": "spanner-10", "how": "ring, full length"},
    },
)
def hand_tight():
    """A nut a spanner reaches and a hand can't follow (GOLDEN-BENCH section 6, M6).

    A block 300 tall sits 6.8 over the nut (underside at z 12), bored r 20 round it.
    Hand room off (the bench's way): the ring (z 0.35..4.85, outer r 10) and its
    handle pass under the block, so the nut turns, ring, full length; the bolt turns
    from below. Hand room on (test_hand_room_bench.py): the hand rests on the handle
    (underside z 2.6, r 35) over the handle's last 90 mm, from r 24.75 on the full
    spanner and from the axis on the stubby, so it meets the block at every angle,
    4.75 past the bore at the least; the socket's ratchet handle (z 36.5) hits the
    block whatever the extension, the tool itself blocked. The ring alone would turn,
    so the nut is blocked for want of a hand. The bolt below is in open air.
    """
    block = Pos(0, 0, 12 + 150) * Box(300, 300, 300) - Pos(0, 0, 12 + 150) * Cylinder(20, 301)
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("block", block),
        ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(6, 20, 10, 4.0)),
        ("nut", hex_nut(6, 10, 5.2)),
    ]


#: One inch, mm.
IN = 25.4


@cell(
    "inch_pair",
    [
        {"parts": "screw", "kind": "screw", "head": "socket", "size": "1/4"},
        {"parts": "nut", "kind": "nut", "size": "1/4"},
    ],
    {
        "screw": {"verdict": "turns", "tool": "hex-key-3/16in", "how": "driver straight in"},
        "nut": {"verdict": "turns", "tool": "spanner-7/16in", "how": "ring, full length"},
    },
)
def inch_pair():
    """An inch joint for the inch tools (GOLDEN-BENCH section 6, M6).

    A 1/4-20 x 1 socket head cap screw (ASME B18.3: head 0.375 across, 0.250 tall,
    3/16 socket) head-up on a plate, its 1/4 hex nut (ASME B18.2.2: 7/16 across
    flats, 7/32 thick) under the plate. Nothing is above the screw or below the
    nut: the 3/16 key goes straight in as a driver, and the 7/16 ring swings full
    circle, full length. Under metric-home neither has a tool (test_kits_bench.py);
    under imperial-home both turn as here.
    """
    return [
        ("plate", plate(holes=[(0, 0, 0.27 * IN / 2)])),
        (
            "screw",
            socket_screw(
                d=0.25 * IN, length=1.0 * IN, dk=0.375 * IN, k=0.25 * IN, s=3 / 16 * IN, t=0.12 * IN
            ),
        ),
        ("nut", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_nut(0.25 * IN, 7 / 16 * IN, 7 / 32 * IN)),
    ]


@cell(
    "torx_wall",
    [{"parts": "screw", "kind": "screw", "head": "torx", "size": "M6"}],
    {"screw": {"verdict": "turns", "tool": "torx-key-T30", "how": "short leg in"}},
)
def torx_wall():
    """An M6 Torx socket head (ISO 14579: T30) under a wall 40 over its head (GOLDEN-
    BENCH section 6, M6). No driver (200 long); the T30's short leg (26, the longest
    of three makers' keys) bends at 26.3 and its long arm (r 2.8) tops out at 29.1,
    10.9 under the wall, so it swings free; the long leg (122) can't go in. The
    recess is drawn as its point-to-point circle, which the solid can't show as
    any drive: with no rule, detection reads Torx from the name, "wall" between
    the drive word and the noun (issue #19; it used to fall back to the outline's
    socket head and a 5 mm key). metric-home and imperial-home hold no Torx key
    (test_kits_bench.py).
    """
    head = Pos(0, 0, 3) * Cylinder(5, 6) - Pos(0, 0, 4.5) * Cylinder(5.6 / 2, 3.01)
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", head + Pos(0, 0, -10) * Cylinder(3, 20)),
        ("wall", slab(6 + 40)),
    ]


@cell(
    "ball_tilt",
    [{"parts": "screw", **M6_SOCKET}],
    {"screw": {"verdict": "turns", "tool": "ball-end-key-5"}},
)
def ball_tilt():
    """A socket head reached only leant off its axis (GOLDEN-BENCH section 6, M6).

    A ceiling (underside 20 over the head, 10 thick) is slotted from x 4.5 outward.
    Straight up, the 5 mm key meets it whichever way (as a driver, short leg 33,
    long leg 85): blocked under metric-home. The full kit's ball end (leg 154,
    r 2.835) leant 20 deg towards the slot passes the ceiling's underside 7.28 off
    the axis, its lower edge (r/cos 20 = 3.02) at 4.26, inside the solid edge at
    4.5; leant 25 deg, 9.33 off and its edge at 6.2, 1.7 clear, and 17.1 at the
    top. Its short arm swings at 140 up, over everything. Truth names the tool, not
    the tilt, so a key-table refinement can't flip it.
    """
    ceiling = slab(6 + 20) - Pos(32.25, 0, 6 + 25) * Box(55.5, 20, 12)
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", socket_screw()),
        ("ceiling", ceiling),
    ]


@cell(
    "nut_tube",
    [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M6"},
        {"parts": "nut", "kind": "nut", "size": "M6"},
    ],
    {
        "bolt": {"verdict": "turns", "tool": "spanner-10", "how": "ring, full length"},
        "nut": {"verdict": "turns", "tool": "nut-driver-10", "how": "nut driver straight in"},
    },
)
def nut_tube():
    """A nut at the foot of a tube only a nut driver gets down (GOLDEN-BENCH section 6,
    M6). The tube's bore is r 11 for its first 100, r 40 above. The ring (outer r 10)
    fits the bore but its handle meets the wall at every angle; the open end's jaw
    (+/-11.4) is wider than the bore. The socket (r 7.2) and extension (r 6) fit, but
    the ratchet head (r 17) only clears the narrow bore from the 75 mm extension up
    (head 105.5..117.5), and there its 180 handle meets the r 40 wall: no swing. The
    10 mm nut driver (socket and blade r 7.2, Wiha's larger) stays inside r 11; its
    handle (r 18, from 130.5) and the fist round it (r 35, hand room on) inside r 40:
    it turns. The bolt, head below the plate, turns in open air. metric-home has no
    nut driver: there the nut is blocked by the tube (test_kits_bench.py).
    """
    tube = (
        Pos(0, 0, 200) * Box(200, 200, 400)
        - Pos(0, 0, 50) * Cylinder(11, 100.02)
        - Pos(0, 0, 250.5) * Cylinder(40, 301)
    )
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("tube", tube),
        ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(6, 20, 10, 4.0)),
        ("nut", hex_nut(6, 10, 5.2)),
    ]


# ---------------------------------------------------------------- issue cells


@cell(
    "hex_band",
    [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"},
        {"parts": "nut", "kind": "nut", "size": "M8"},
    ],
    {
        "bolt": {"verdict": "turns", "tool": "spanner-13", "how": "ring, full length"},
        "nut": {"verdict": "turns", "tool": "spanner-13", "how": "ring, full length"},
    },
)
def hex_band():
    """An M8 nut drawn 12.8 across flats, inside ISO 4032's band of 12.73 to 13
    (issue #27), on an M8 bolt whose head is under the plate, room all round. The
    rule names the size, so the main run takes the table's 13; with no rule,
    detection measures the hex and the band gives it the 13 mm spanner too. It
    used to be "12.80 mm across flats is no tool's size".
    """
    return [
        ("plate", plate(holes=[(0, 0, 4.5)])),
        ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(8, 20, 13, 5.3)),
        ("nut", hex_nut(8, 12.8, 6.8)),
    ]


@cell(
    "nut_gap",
    [{"parts": "nut", "kind": "nut", "size": "M8"}],
    {"nut": {"verdict": "turns", "tool": "spanner-13", "how": "ring, full length"}},
)
def nut_gap():
    """An M8 nut drawn 1.5 off its plate, as when its washer is left out (issue #26),
    on a stud up through the plate. Both ends read clear at the 1 mm probe; probed
    2 out, the bottom meets the plate and the top is still clear, so the top is the
    free face and the ring goes on from above. It used to be "cannot tell the nut's
    free face: both ends are clear".
    """
    return [
        ("plate", plate(holes=[(0, 0, 4.5)])),
        ("stud", Pos(0, 0, 2.5) * Cylinder(4, 25)),
        ("nut", Pos(0, 0, 1.5) * hex_nut(8, 13, 6.8)),
    ]


@cell(
    "vented",
    [{"parts": "gland_vent", "kind": "nut", "size": "M16", "socket": False}],
    {"gland_vent": {"verdict": "turns", "tool": "spanner-24", "how": "ring, full length"}},
    ignore=["*_cable"],
)
def vented():
    """A gland whose name has a word after its noun, "gland_vent" (issue #30), alone
    on a plate with its cable. With no rule, detection reads it as a candidate, and
    its 24 mm hex makes it a gland; the ring turns it in open air. A name like this
    used to be passed over without a word.
    """
    return [
        ("plate", plate(holes=[(0, 0, 10)])),
        ("gland_vent", gland()),
        ("cable", Pos(0, 0, 60) * Cylinder(4, 220)),
    ]


@cell(
    "low_head",
    [{"parts": "screw", "kind": "screw", "head": "button", "size": "M5"}],
    {"screw": {"verdict": "turns", "tool": "hex-key-3", "how": "driver straight in"}},
)
def low_head():
    """An M5 button head drawn as a plain cylinder, flat-topped with no recess, at
    ISO 7380-1's 9.5 across and 2.75 high (issue #31), in open air. The rule names
    it; with no rule its name says no head, and its outline, held to the standards'
    for its M5 shank, fits ISO 7380-1's and not ISO 4762's 8.5 by 5: a button head,
    the 3 mm key. It used to be read as a socket head and given the 4 mm key.
    """
    return [
        ("plate", plate(holes=[(0, 0, 2.75)])),
        ("screw", Pos(0, 0, -8) * Cylinder(2.5, 16) + Pos(0, 0, 1.375) * Cylinder(4.75, 2.75)),
    ]


@cell(
    "rubber",
    [
        {"parts": "screw", "kind": "screw", "head": "button", "size": "M4"},
        {"parts": "well_nut", "kind": "insert", "size": "M4"},
    ],
    {
        "screw": {"verdict": "turns", "tool": "hex-key-2.5", "how": "driver straight in"},
        "well_nut": {"verdict": "held", "how": "holds itself", "pair": "screw"},
    },
)
def rubber():
    """An M4 button head (ISO 7380-1, drawn flat: 7.6 by 2.2) through a 3 mm panel
    into a rubber well nut, a flanged sleeve with no flats, set in a 2 mm wall
    (issue #29). The well nut is a fixed thread: it holds itself, takes no tool,
    and pairs with the screw, which turns with its 2.5 mm key in open air. Read as
    a hex nut by its name, it used to "turn" with spanner-7, which can't grip it.
    """
    wall = Pos(0, 0, -1) * (Box(80, 80, 2) - Cylinder(4.5, 2))
    flange = Pos(0, 0, 0.75) * (Cylinder(5.5, 1.5) - Cylinder(2, 1.5))
    body = Pos(0, 0, -5) * (Cylinder(4.4, 10) - Cylinder(2, 10))
    panel = Pos(0, 0, 3) * (Box(80, 80, 3) - Cylinder(2.2, 3))
    screw = Pos(0, 0, -1.5) * Cylinder(2, 12) + Pos(0, 0, 5.6) * Cylinder(3.8, 2.2)
    return [("wall", wall), ("well_nut", flange + body), ("panel", panel), ("screw", screw)]


@cell(
    "one_part_lock",
    [
        {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M6"},
        {"parts": "nut", "kind": "nut", "size": "M6"},
    ],
    {
        "bolt": {"verdict": "turns", "tool": "spanner-10", "how": "ring, full length"},
        "nut": {"verdict": "turns", "tool": "spanner-10", "how": "ring, full length"},
    },
)
def one_part_lock():
    """nyloc_two_bodies drawn as one part of two solids, the nut and its nylon dome
    (issue #28). Read from STEP it is split one part per solid; the nut, the larger,
    keeps the name and the dome is a piece of it, so no rule or mate is needed: the
    dome leaves the nut's scene with it and the free face reads clear. It used to be
    two fasteners, the dome a sizeless "nut" that wasn't covered.
    """
    dome = Pos(0, 0, 5.2 + 1.25) * (Cylinder(4.8, 2.5) - Cylinder(3, 3))
    nut = hex_nut(6, 10, 5.2)
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(6, 20, 10, 4.0)),
        ("nut", Compound([dome.solid(), nut.solid()])),  # the dome first, as drawn
    ]


@cell(
    "big_gland",
    [{"parts": "gland", "kind": "nut", "socket": False, "across_flats": 41}],
    {"gland": {"verdict": "turns", "tool": "spanner-41", "how": "ring, full length"}},
    ignore=["*_cable"],
)
def big_gland():
    """An M32-class cable gland, 41 across flats, through a plate with its cable
    (issue #33): the full kit's 41 mm spanner (Gedore's 1 B length, 520) turns it
    in open air. The rule gives the hex, as a gland's thread says nothing of it,
    so the report lists it as "41 AF gland"; with no rule detection measures the
    same. It used to be "41.00 mm across flats is no tool's size".
    """
    return [
        ("plate", plate(w=300, d=300, holes=[(0, 0, 16.2)])),
        # The bore (15) is no thread size, as a gland's isn't: the hex alone sizes it.
        ("gland", gland(af=41, h=10, dome_r=17, dome_h=20, stub_r=16, stub_h=14, bore=7.5)),
        ("cable", Pos(0, 0, 80) * Cylinder(7, 300)),
    ]


# Issue #25's grazes: an M4 button head (k 2.2) whose 2.5 mm key's short leg goes
# in (the driver and the long leg stop at a lid 53 up). The long arm (r 1.41) lies
# with its underside at 2.2 + 0.3 + 20.5 - 1.41 = 21.59, and a part round the
# screw rises `depth` into it at every angle, so the overlap alone decides: the
# exact overlap at one position, measured, against the 0.05 mm^3 floor. The mesh
# engine used to differ from --exact on both: passing the torus at 0.08 (its
# tessellation lies inside the curved face), blocking the flat at 0.004 (the
# key's polygon stands outside its circle). It now refers both to its referee.
_ARM_BOTTOM = 2.2 + 0.3 + 20.5 - 1.41
_GRAZE_RULE = {"parts": "screw", "kind": "screw", "head": "button", "size": "M4", "axis": "+z"}


def _graze(under):
    return [
        ("base", Pos(0, 0, -3) * (Box(200, 200, 6) - Cylinder(2.2, 6))),
        ("screw", Pos(0, 0, -6) * Cylinder(2, 12) + Pos(0, 0, 1.1) * Cylinder(3.8, 2.2)),
        ("under", under),
        ("lid", Pos(0, 0, 55) * Box(200, 200, 4)),
    ]


def _torus(depth):
    return Pos(0, 0, _ARM_BOTTOM + depth - 10) * Torus(40, 10)


def _flat(depth):
    top = _ARM_BOTTOM + depth
    return Pos(0, 0, top - 2) * (Cylinder(70, 4) - Cylinder(12, 4))


_GRAZED = {"verdict": "turns", "tool": "hex-key-2.5", "how": "short leg in", "grazes": ["under"]}
_RUN_INTO = {"verdict": "blocked", "tool": "hex-key-2.5", "blocked_by": ["lid", "under"]}


@cell("torus_graze", [_GRAZE_RULE], {"screw": _GRAZED}, timed=False)
def torus_graze():
    """A torus (R 40, r 10) 0.02 into the arm: 0.0047 mm^3, a graze: it turns, and
    the report says the key grazes the torus. The torus's mesh lies inside its
    curve there and shows no overlap at all: only the gap check, refusing to call
    a part clear within what its mesh may leave out, finds the graze."""
    return _graze(_torus(0.02))


@cell("torus_deep", [_GRAZE_RULE], {"screw": _RUN_INTO}, timed=False)
def torus_deep():
    """The same torus 0.08 in: 0.075 mm^3, a hit at every angle: blocked. The mesh
    engine used to pass it."""
    return _graze(_torus(0.08))


@cell("flat_graze", [_GRAZE_RULE], {"screw": _GRAZED}, timed=False)
def flat_graze():
    """A flat ring (r 12 to 70) 0.004 into the arm: 0.026 mm^3, a graze: it turns.
    The mesh engine used to block it."""
    return _graze(_flat(0.004))


@cell("flat_deep", [_GRAZE_RULE], {"screw": _RUN_INTO}, timed=False)
def flat_deep():
    """The flat ring 0.008 in: 0.074 mm^3, a hit at every angle: blocked."""
    return _graze(_flat(0.008))
