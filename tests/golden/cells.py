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

from bd_warehouse.fastener import (
    ButtonHeadScrew,
    CounterSunkScrew,
    HexNut,
    SocketHeadCapScrew,
)
from build123d import (
    Axis,
    Box,
    Compound,
    Cone,
    Cylinder,
    Plane,
    Pos,
    RegularPolygon,
    Rot,
    Shell,
    Sphere,
    Torus,
    extrude,
)
from parts import (
    VENDOR_FLAT,
    button_screw,
    carriage_bolt,
    gland,
    hex_bolt,
    hex_nut,
    hex_prism,
    pan_phillips,
    plate,
    set_screw,
    slab,
    slot_block,
    socket_screw,
    thumb_screw,
    vendor_button_screw,
    vendor_flat_screw,
    vendor_socket_screw,
    wing_nut,
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
    #: The sidecar's own tools the cell needs (spec 5.3): the bench's sidecar holds
    #: each once, and like any custom tool it joins the kit for every cell.
    tools: tuple = ()


M6_SOCKET = {"kind": "screw", "head": "socket", "size": "M6"}

CELLS = []


def cell(name, rules=(), truth=None, ignore=(), timed=True, tools=()):
    def register(build):
        CELLS.append(
            Cell(name, build, tuple(rules), truth or {}, tuple(ignore), timed, tuple(tools))
        )
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
    """Inside 180 x 180 walls the full handle (166.2 long, reach 141.3 > half-width
    90) never turns; the stubby (Tekton's 101.6, reach 86.4, corner 86.6) swings all
    round. Before issue #49 both were the prototype's formula (reach 114.8 and 63.1),
    and this cell was drawn so that a maker's table would keep it."""
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
    (underside z 2.6, r 35) over the handle's last 90 mm, from r 51.3 on the full
    spanner (reach 141.3) and from the axis on the stubby (86.4), so it meets the
    block at every angle, 31.3 past the bore at the least; the socket's ratchet
    handle (z 36.5) hits the block whatever the extension, the tool itself blocked.
    The ring alone would turn, so the nut is blocked for want of a hand. The bolt
    below is in open air.
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
    {
        "screw": {
            "verdict": "turns",
            "tool": "ball-end-key-5",
            # Issue #51: a pass only a ball end reaches says so.
            "notes": [
                "only a ball end turns it (ball end, 25 deg off the axis): a ball end takes "
                "much less torque than a straight key, so tightening it to its torque, or "
                "breaking it loose, may need a straight key, which can't get in"
            ],
        }
    },
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


@cell(
    "pivot",
    [{"parts": "shoulder_screw", "kind": "screw", "head": "shoulder", "size": "M6"}],
    {"shoulder_screw": {"verdict": "turns", "tool": "hex-key-4", "how": "driver straight in"}},
)
def pivot():
    """An M6 shoulder screw (ISO 7379: head 13 by 5.5, 8 mm shoulder, 4 mm socket) as
    a lever's pivot, its thread in the plate (issue #40). The 4 mm key turns it in
    open air, where ISO 4762's M6 key would be 5. With no rule, "shoulder" in its
    name says the head, and detection reads its socket through ISO 7379's keys.
    """
    head = Pos(0, 0, 20 + 2.75) * Cylinder(6.5, 5.5)
    screw = head + Pos(0, 0, 10) * Cylinder(4, 20) + Pos(0, 0, -5) * Cylinder(3, 10)
    screw = screw - Pos(0, 0, 20) * hex_prism(4.0, 3.31, 5.5 - 3.3)
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("lever", Pos(0, 0, 10) * (Box(60, 30, 20) - Cylinder(4.1, 21))),
        ("shoulder_screw", screw),
    ]


@cell(
    "channel",
    [{"parts": "nut", "kind": "nut", "size": "M8"}],
    {"nut": {"verdict": "blocked", "tool": "spanner-13", "blocked_by": ["left", "right"]}},
)
def channel():
    """An M8 nut (af 13, 6.8 tall, its flats facing y) in a channel: ribs 4 high,
    their faces 2.0 off the flats (y = -8.5 and 8.5), lower than the nut. The hex's
    corners (7.5, 7.8 with the clearance) clear the ribs, so it could turn; but
    every tool on its flats stands wider. The ring (outer 12.4) and the open end
    (head 29.1 wide) meet a rib at every angle; the socket's wall round the hex (to
    r 9.0) meets both, at every extension; so does the full kit's nut driver's
    (r 9.2). The socket used to be drawn from the nut's top up, over the ribs, and
    turned it.
    """
    return [
        ("plate", plate()),
        ("nut", hex_nut(8, 13, 6.8)),
        ("left", Pos(0, -13.5, 2) * Box(80, 10, 4)),
        ("right", Pos(0, 13.5, 2) * Box(80, 10, 4)),
    ]


_M8_BOLT_RULE = {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"}
_M8_PAIR_TURNS = {
    "bolt": {"verdict": "turns", "tool": "spanner-13", "how": "ring, full length"},
    "nut": {"verdict": "turns", "tool": "spanner-13", "how": "ring, full length"},
}


@cell(
    "undersize",
    [_M8_BOLT_RULE, {"parts": "nut", "kind": "nut", "size": "M8", "across_flats": 12.6}],
    {
        **_M8_PAIR_TURNS,
        "nut": {
            **_M8_PAIR_TURNS["nut"],
            "notes": [
                "hex drawn undersize: 12.60 across flats, 0.13 under the least its M8 "
                "standard allows (12.73); taken as size 13"
            ],
        },
    },
)
def undersize():
    """An M8 nut drawn 12.6 across flats, 0.13 under ISO 4032's band of 12.73 to 13
    (issue #50), on an M8 bolt, room all round. The rule gives the size and the
    hex; with no rule, detection reads M8 from the bore. Either way the nut is a
    model drawn small: the 13 mm spanner turns it, the result says so. It used to
    be read as a 5/16 nut, 12.6 being in the band below 1/2 in, and turned with a
    1/2 in spanner (in metric-home, not at all); with the rule, it was "no tool's
    size".
    """
    return [
        ("plate", plate(holes=[(0, 0, 4.5)])),
        ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(8, 20, 13, 5.3)),
        ("nut", hex_nut(8, 12.6, 6.8)),
    ]


@cell("guessed", [_M8_BOLT_RULE, {"parts": "nut", "kind": "nut", "size": "M8"}], _M8_PAIR_TURNS)
def guessed():
    """The undersize nut with its bolt, both drawn at 6.8 (near M8's minor diameter),
    which is no standard size. With no rule, the bolt's 13 mm head says M8, and the
    nut's hex alone says 5/16, by the band below 1/2 in: a guess its bolt outranks.
    The nut takes the bolt's M8 and the 13 mm spanner, the result saying both.
    """
    return [
        ("plate", plate(holes=[(0, 0, 3.9)])),
        ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(6.8, 20, 13, 5.3)),
        ("nut", hex_nut(6.8, 12.6, 6.8)),
    ]


@cell("band_agrees", [_M8_BOLT_RULE, {"parts": "nut", "kind": "nut", "size": "M8"}], _M8_PAIR_TURNS)
def band_agrees():
    """guessed's pair with the nut drawn 12.8, inside M8's own band: the band's guess
    is its bolt's size, so the bolt has nothing to add and the result says nothing.
    """
    return [
        ("plate", plate(holes=[(0, 0, 3.9)])),
        ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(6.8, 20, 13, 5.3)),
        ("nut", hex_nut(6.8, 12.8, 6.8)),
    ]


@cell(
    "named_size",
    [{"parts": "m8_nut", "kind": "nut", "size": "M8"}],
    {"m8_nut": {"verdict": "turns", "tool": "spanner-13", "how": "ring, full length"}},
)
def named_size():
    """guessed's nut alone on its plate, no bolt, its name saying M8: with no rule,
    the name's size outranks the band's guess of 5/16, and the 13 mm spanner turns
    it, the result saying it is drawn small.
    """
    return [("plate", plate()), ("m8_nut", hex_nut(6.8, 12.6, 6.8))]


@cell("minor_bore", [_M8_BOLT_RULE, {"parts": "nut", "kind": "nut", "size": "M8"}], _M8_PAIR_TURNS)
def minor_bore():
    """An M8 nut bored at its thread's minor diameter (6.647), on an M8 bolt drawn
    at the nominal 8, as many a vendor's models are: the bolt is 0.68 into the nut
    all round. The free-face probe starts outside the thread's nominal radius, so
    the bolt no longer reads as covering both ends of the nut, which used to make
    it "cannot tell the nut's free face: both ends are covered".
    """
    return [
        ("plate", plate(holes=[(0, 0, 4.5)])),
        ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(8, 20, 13, 5.3)),
        ("nut", hex_nut(6.647, 13, 6.8)),
    ]


def _shoulder_screw(thread=None):
    """ISO 7379's M6 drawn plainly: a head 13 by 5.5 on z 0..5.5, no socket in it,
    the 8 mm shoulder 25 below it, and the thread 11 below that when drawn."""
    shape = Pos(0, 0, 2.75) * Cylinder(6.5, 5.5) + Pos(0, 0, -12.5) * Cylinder(4, 25)
    if thread is not None:
        shape = shape + Pos(0, 0, -30.5) * Cylinder(thread / 2, 11)
    return shape


_SHOULDER_RULE = {"parts": "bolt", "kind": "screw", "head": "shoulder", "size": "M6"}
_KEY_4_TURNS = {"verdict": "turns", "tool": "hex-key-4", "how": "driver straight in"}


@cell("plain_pin", [_SHOULDER_RULE], {"bolt": _KEY_4_TURNS})
def plain_pin():
    """A shoulder screw drawn as its head and shoulder alone, with no socket and a
    name that doesn't say shoulder (issue #48). With no rule, its head, 13 by 5.5,
    is ISO 7379's for the 8 mm shoulder under it, whose thread is M6: a 4 mm key.
    It used to be "button by its outline, fitting no standard head", M8 by its
    shank, and a 5 mm key.
    """
    return [("plate", plate(holes=[(0, 0, 4.1)])), ("bolt", _shoulder_screw())]


@cell("stepped_pin", [_SHOULDER_RULE], {"bolt": _KEY_4_TURNS})
def stepped_pin():
    """plain_pin's screw stepped down to its M6 thread: the same head, the same key.
    It used to be a button head too, right by luck (an M6 button takes 4 mm).
    """
    return [("plate", plate(holes=[(0, 0, 4.1)])), ("bolt", _shoulder_screw(thread=6.0))]


@cell("minor_pin", [_SHOULDER_RULE], {"bolt": _KEY_4_TURNS})
def minor_pin():
    """stepped_pin's screw with its thread drawn at M6's minor diameter, 4.917,
    which is no size: the shoulder under its ISO 7379 head says M6.
    """
    return [("plate", plate(holes=[(0, 0, 4.1)])), ("bolt", _shoulder_screw(thread=4.917))]


_ODD_RULE = {"kind": "screw", "head": "button", "size": "M6"}


@cell(
    "odd_head",
    [{"parts": "screw", **_ODD_RULE}, {"parts": "button_screw", **_ODD_RULE}],
    {"screw": _KEY_4_TURNS, "button_screw": _KEY_4_TURNS},
)
def odd_head():
    """Two M6 screws whose plain heads, 12 by 3, fit no standard's (issue #48). With
    no rule, the first's proportions make it a button head, a guess: detection's
    confidence is low, and the check's result says so, where only detect's comment
    used to. The second's name says button: no guess, nothing to say.
    """
    screw = Pos(0, 0, 1.5) * Cylinder(6, 3) + Pos(0, 0, -10) * Cylinder(3, 20)
    return [
        ("plate", plate(holes=[(0, 0, 3.1), (100, 0, 3.1)])),
        ("screw", screw),
        ("button_screw", Pos(100, 0, 0) * screw),
    ]


def _domed_gland(dome):
    """A 15 mm hex on z 0..3 with a plain dome of diameter ``dome`` on 3..10, unbored."""
    return hex_prism(15, 3) + Pos(0, 0, 6.5) * Cylinder(dome / 2, 7)


_DOMED_RULE = {"parts": "gland", "kind": "nut", "socket": False, "across_flats": 15.0}


@cell(
    "snug_dome",
    [_DOMED_RULE],
    {"gland": {"verdict": "turns", "tool": "spanner-15", "how": "ring, full length"}},
)
def snug_dome():
    """A gland whose dome, 17.6 across, is wider than its hex's flats, and its
    corners (17.32), and inside the ring's bore round them (17.92): the ring goes on
    over it, and grips the hex below it (issue #47). It used to be "the bore leaves
    no face to probe for the free end", the dome taken for a bore.
    """
    return [("wall", plate()), ("gland", _domed_gland(17.6))]


@cell(
    "wide_dome",
    [_DOMED_RULE],
    {
        "gland": {
            "verdict": "turns",
            "tool": "spanner-15",
            "how": "open end, full length",
            "notes": [
                "no ring, socket or nut driver gets on: past its hex the part is 20.00 "
                "across, wider than their bore round the hex; only an open end grips it, "
                "from the side"
            ],
        }
    },
)
def wide_dome():
    """snug_dome's gland with a dome 20 across, wider than a ring's bore: no ring
    gets on over it, and the open end grips the hex from the side (issue #47).
    """
    return [("wall", plate()), ("gland", _domed_gland(20))]


@cell(
    "dome_rib",
    [_DOMED_RULE],
    {"gland": {"verdict": "blocked", "tool": "spanner-15", "blocked_by": ["rib"]}},
)
def dome_rib():
    """snug_dome's gland with a rib 1.5 high beside its hex, its face 3.5 off a flat
    (y = 11): inside the ring, which sits on the hex, 3 high, and meets it at
    every angle; the open end's jaw meets it too. Before issue #47 the band ran
    over the 17 dome (0 to 10), so the ring sat above the rib, and turned it.
    """
    return [
        ("wall", plate()),
        ("gland", _domed_gland(17)),
        ("rib", Pos(0, 15, 0.75) * Box(60, 8, 1.5)),
    ]


@cell(
    "sunk_cap",
    [{"parts": "cap_nut", "kind": "nut", "size": "M10"}],
    {
        "cap_nut": {
            "verdict": "blocked",
            "tool": "spanner-16",
            "blocked_by": ["cap_nut", "plate"],
        }
    },
)
def sunk_cap():
    """An M10 cap nut (a 16 hex 3 high, a dome 20 across over it, unbored) sunk in a
    counterbore 24 across and 3.5 deep. The open end's jaw can't get into the
    counterbore; the socket's wall (r 10.8) could, but neither it nor the ring
    gets on over the dome, wider than their bore round the hex (r 9.54): blocked,
    by the plate and by its own dome (issue #47). It used to turn with the socket,
    drawn round the dome as if the dome weren't there.
    """
    nut = hex_prism(16, 3, -3.5) + Pos(0, 0, 3) * Cylinder(10, 7)
    return [
        ("plate", plate() - Pos(0, 0, -1.75) * Cylinder(12, 3.5)),
        ("cap_nut", nut),
    ]


def _tube(inner, height=30.0):
    """A round wall round the cell's axis, ``inner`` to ``inner`` + 10, on the plate."""
    return Pos(0, 0, height / 2) * (Cylinder(inner + 10, height) - Cylinder(inner, height + 1))


@cell(
    "reach_13",
    [{"parts": "nut", "kind": "nut", "size": "M8"}],
    {"nut": {"verdict": "turns", "tool": "spanner-13", "how": "ring, stubby"}},
)
def reach_13():
    """An M8 nut on a stud inside a round wall 155 from its axis (issue #49). A real
    13 mm spanner (GearWrench's, 206.1 long) reaches 175.2 with its handle, and
    meets the wall at every angle; its stubby (Tekton's 111.8) reaches 95.0 and turns
    it. The prototype's formula made the spanner 162 long, reaching 137.7, which
    swung clear and was credited.
    """
    return [
        ("plate", plate(holes=[(0, 0, 4.5)])),
        ("stud", Pos(0, 0, 2.5) * Cylinder(4, 25)),
        ("nut", hex_nut(8, 13, 6.8)),
        ("wall", _tube(155)),
    ]


@cell(
    "big_tube",
    [{"parts": "gland", "kind": "nut", "size": "M24", "socket": False, "across_flats": 36.0}],
    {"gland": {"verdict": "blocked", "tool": "spanner-36", "blocked_by": ["wall"]}},
)
def big_tube():
    """A 36 mm gland inside a round wall 420 from its axis (issue #49). A real 36 mm
    spanner (Tekton's, 510.5 long) reaches 434 and meets the wall at every angle,
    ring and open end; no stubby is made past 32 mm, so nothing turns it. The
    formula's 369 (reach 314) used to swing clear, and so would Gedore's 1 B (460,
    reach 391): the longest maker's is the one held to.
    """
    gland = hex_prism(36, 10) + Pos(0, 0, 15) * Cylinder(17, 10)
    return [("plate", plate()), ("gland", gland), ("wall", _tube(420, 60))]


@cell(
    "flange_nut",
    [{"parts": "nut", "kind": "nut", "size": "M8"}],
    {"nut": {"verdict": "turns", "tool": "spanner-13", "how": "ring, full length"}},
)
def flange_nut():
    """An M8 flange nut (a 13 hex 6.5 high over a flange 20 across, 1.5 thick) on a
    stud: the flange is its widest region, which used to be its band; the ring
    grips its hex's flats now, and the flange, on the plate's side, is nothing a
    ring passes on its way on (issue #47).
    """
    nut = Pos(0, 0, 0.75) * Cylinder(10, 1.5) + hex_prism(13, 6.5, 1.5) - Cylinder(4, 30)
    return [
        ("plate", plate(holes=[(0, 0, 4.5)])),
        ("stud", Pos(0, 0, 2.5) * Cylinder(4, 25)),
        ("nut", nut),
    ]


@cell(
    "ball_button",
    [{"parts": "screw", "kind": "screw", "head": "button", "size": "M6"}],
    {"screw": {"verdict": "blocked", "tool": "hex-key-4", "blocked_by": ["ceiling"]}},
)
def ball_button():
    """ball_tilt's ceiling over an M6 button head (ISO 7380-1, a 4 mm key), its
    underside 20 over the head (issue #51). The plain key meets it whichever way.
    A ball end, leant 20 deg into the slot, would turn it, but a button head's
    socket is about half as deep as a socket head's, barely deeper than the ball,
    and no ball end is credited in it: blocked. It used to turn with one.
    """
    ceiling = slab(3.3 + 20) - Pos(32.25, 0, 3.3 + 25) * Box(55.5, 20, 12)
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", button_screw()),
        ("ceiling", ceiling),
    ]


@cell(
    "ball_shoulder",
    [{"parts": "screw", "kind": "screw", "head": "shoulder", "size": "M6"}],
    {
        "screw": {
            "verdict": "turns",
            "tool": "ball-end-key-4",
            "notes": [
                "only a ball end turns it (ball end, 20 deg off the axis): a ball end takes "
                "much less torque than a straight key, so tightening it to its torque, or "
                "breaking it loose, may need a straight key, which can't get in"
            ],
        }
    },
)
def ball_shoulder():
    """ball_tilt's ceiling over an M6 shoulder screw (ISO 7379: head 13 by 5.5, its
    4 mm socket as deep as a cap screw's), the underside 20 over its head. The plain
    key meets the ceiling whichever way; the ball end, leant 20 deg into the slot,
    turns it, and the result says only a ball end does (issue #51). The shank is
    short (18 under the head), so its way out stays under the ceiling.
    """
    screw = (
        Pos(0, 0, 2.75) * Cylinder(6.5, 5.5)
        + Pos(0, 0, -6) * Cylinder(4, 12)
        + Pos(0, 0, -15) * Cylinder(3, 6)
        - hex_prism(4.0, 3.31, 5.5 - 3.3)
    )
    ceiling = slab(5.5 + 20) - Pos(32.25, 0, 5.5 + 25) * Box(55.5, 20, 12)
    return [("plate", plate(holes=[(0, 0, 4.1)])), ("screw", screw), ("ceiling", ceiling)]


_POSTS = {"post_a": 340.0, "post_b": 35.0, **{f"post_{k}": 35.0 + 61.0 * k for k in range(1, 5)}}


@cell(
    "post_ring",
    [{"parts": "nut", "kind": "nut", "size": "M8", "socket": False}],
    {"nut": {"verdict": "blocked", "tool": "spanner-13", "deciding": ["post_a", "post_b"]}},
)
def post_ring():
    """An M8 nut on a stud ringed by six posts (r 8) 60 out (issue #52), 61 deg
    apart but for post_a and post_b, 55 apart. Between them the spanner swings 15
    deg of the 30 it needs, the best arc any way finds; elsewhere it fits at one
    angle. Every post is hit somewhere round the sweep, and blocked_by names all
    six, leading with the two that decided it: post_a and post_b. A roof 33 over the nut
    keeps a socket or nut driver off it, when detection, not the rule, describes it.
    """
    posts = [
        (name, Pos(60 * math.cos(math.radians(a)), 60 * math.sin(math.radians(a)), 10))
        for name, a in _POSTS.items()
    ]
    return [
        ("plate", plate(holes=[(0, 0, 4.5)])),
        ("stud", Pos(0, 0, 2.5) * Cylinder(4, 25)),
        ("nut", hex_nut(8, 13, 6.8)),
        ("roof", Pos(0, 0, 42) * Box(200, 200, 4)),
        *((name, at * Cylinder(8, 20)) for name, at in posts),
    ]


#: A short-arm 6 mm key: no other cell needs a 6 mm key, so it changes none of them
#: (a sidecar's own tool joins the kit for every fastener).
_STUBBY_KEY = {
    "name": "stubby-key-6",
    "type": "hex-key",
    "across_flats": 6,
    "long": 60,
    "short": 20,
}


@cell(
    "short_key",
    [{"parts": "screw", "kind": "screw", "head": "socket", "size": "M8", "tool": "stubby-key-6"}],
    {"screw": {"verdict": "turns", "tool": "stubby-key-6", "how": "short leg in"}},
    tools=[_STUBBY_KEY],
)
def short_key():
    """An M8 socket head under a slab 30 over it. ISO 2936's 6 mm key (short leg 38,
    long 96; 41.7 to swing short leg in) meets the slab whichever way, and so does the
    ball end; the sidecar's own short-arm key (spec 5.3: a 20 mm short leg, 60 long)
    turns it, short leg in, its long arm swinging 0.3 + 20 + 3.4 = 23.7 over the head.
    The rule names the key, as a rule may; with no rule (the detected run) the key is
    tried after the kit's own.
    """
    screw = socket_screw(d=8, length=20, dk=13, k=8, s=6, t=4)
    return [("plate", plate(holes=[(0, 0, 4.5)])), ("screw", screw), ("slab", slab(8 + 30))]


#: A short ring spanner of a size no other cell needs (18 mm).
_SHORT_RING = {
    "name": "short-ring-18",
    "type": "spanner",
    "across_flats": 18,
    "length": 100,
    "ends": ["ring"],
}


@cell(
    "shop_spanner",
    [{"parts": "nut", "kind": "nut", "size": "M12", "tool": "short-ring-18"}],
    {"nut": {"verdict": "turns", "tool": "short-ring-18", "how": "ring, full length"}},
    tools=[_SHORT_RING],
)
def shop_spanner():
    """An M12 nut on a stud inside a round wall 100 from its axis and 400 tall. The
    kit's 18 mm spanner (269.3 long, reach 229) and its stubby (133.4, reach 113) meet
    the wall at every angle; every socket, whatever its extension, stands inside it,
    the ratchet's handle meeting it; the sidecar's own 100 mm ring spanner (spec 5.3,
    reach 85) turns it. The rule names it, which keeps the timed bench from sweeping
    every kit tool round the wall first; the detected run, with no rules, tries them
    all and then it.
    """
    return [
        ("plate", plate(holes=[(0, 0, 6.5)])),
        ("stud", Pos(0, 0, 2.5) * Cylinder(6, 25)),
        ("nut", hex_nut(12, 18, 10.8)),
        ("wall", Pos(0, 0, 200) * (Cylinder(110, 400) - Cylinder(100, 401))),
    ]


#: An M8 nut's corner circle: 13 across flats, 13 / sqrt(3) from the axis.
_M8_CORNER = 13 / math.sqrt(3)


@cell(
    "corner_touch",
    [{"parts": "nut", "kind": "nut", "size": "M8"}],
    {"nut": {"verdict": "blocked", "tool": "spanner-13", "blocked_by": ["block"]}},
)
def corner_touch():
    """An M8 nut on a stud, a block's face on its corner circle (r 7.51), a corner
    against it (issue #63). The block is a bar 3 tall at the nut's middle (z 1.9 to
    4.9), so the corners' sweep must span the hex's height to meet it. Nothing
    reaches the block; the nut's own corners, turning, do, and whatever grips it
    can't turn it. The report says that once, rather than each spanner, socket and
    nut driver blocked by the block.
    """
    return [
        ("plate", plate(holes=[(0, 0, 4.5)])),
        ("stud", Pos(0, 0, 2.5) * Cylinder(4, 25)),
        ("nut", hex_nut(8, 13, 6.8)),
        ("block", Pos(_M8_CORNER + 5, 0, 3.4) * Box(10, 30, 3)),
    ]


#: ISO 261 minor diameters, as a tapped hole or a nut's bore is often drawn.
_M6_MINOR, _M8_MINOR = 4.917, 6.647


@cell("drawn_in", ignore=["*drawn_in_*"], timed=False)
def drawn_in():
    """Fasteners drawn into parts: clashes in the model, and threads that aren't
    (issue #63). A clash is not-covered, and the bench's own runs (described and
    detected) keep none, so they ignore the cell; the edges sidecar, which keeps no
    ignores, describes every fastener here. It checks no fastener the main run
    checks, so it stays out of the timed bench.

    Clashes: side_block, 3 tall, reaches 1 mm in at the side_nut's middle, past a
    corner; top_block sits 1 mm down over the top_nut's whole top; head_block 0.5 mm
    down over the head_screw's, so no key gets in; fat_stud, r 4.5, runs through
    the fat_nut's bore drawn at the minor (r 3.32), past a thread's reach (1.25
    bores, r 4.15); tapped_block holds the tapped_screw's shank in a hole drawn at
    the minor and is drawn 0.5 into its head, top and side, which alone is told.
    flange_block reaches 1 mm into a corner of the flange_nut's hex, down to the
    plate, past its flange (r 11, wider than the hex by more than a third): hex and
    flange are both told. None is a reach problem: the model is wrong. side_chip,
    wholly inside the side_nut, stops nothing, and isn't asked.

    No clash: the thread_stud, at M8's nominal r 4 in the thread_nut's minor bore,
    is its thread; the pair_bolt, its shank r 4.5 in the pair_nut's, is its
    partner. Both nuts are lidded, a lid on each top: their free face can't be told.
    """
    lid = Box(30, 30, 10)
    tapped = Pos(0, 0, 15) * Box(40, 40, 30) - Pos(0, 0, 22.75) * Cylinder(4.5, 5.5)
    tapped = tapped - Pos(0, 0, 10) * Cylinder(_M6_MINOR / 2, 20)
    pair_bolt = hex_prism(13, 5.2) + Pos(0, 0, 13) * Cylinder(4.5, 16)
    lidded = [(-50, -60), (50, -60), (0, -60)]
    flange_nut = hex_prism(13, 6.5, 1.5) + Pos(0, 0, 0.75) * Cylinder(11, 1.5) - Cylinder(4, 30)
    holes = [(-50, 0, 4.5), (50, 0, 4.5), (0, 60, 3.2), (-50, 60, 4.5)]
    return [
        ("plate", plate(holes=holes + [(x, y, 4.6) for x, y in lidded])),
        ("flange_stud", Pos(-50, 60, 2.5) * Cylinder(4, 25)),
        ("flange_nut", Pos(-50, 60, 0) * flange_nut),
        ("flange_block", Pos(-50 + _M8_CORNER - 1 + 5, 60, 3) * Box(10, 30, 6)),
        ("head_screw", Pos(0, 60, 0) * socket_screw()),
        ("head_block", Pos(0, 60, 6 - 0.5 + 5) * lid),
        ("side_stud", Pos(-50, 0, 2.5) * Cylinder(4, 25)),
        ("side_nut", Pos(-50, 0, 0) * hex_nut(8, 13, 6.8)),
        ("side_block", Pos(-50 + _M8_CORNER - 1 + 5, 0, 3.4) * Box(10, 30, 3)),
        ("side_chip", Pos(-50 - 5.5, 0, 3.4) * Box(0.8, 0.8, 0.8)),
        ("top_stud", Pos(50, 0, -2.1) * Cylinder(4, 15.8)),
        ("top_nut", Pos(50, 0, 0) * hex_nut(8, 13, 6.8)),
        ("top_block", Pos(50, 0, 6.8 - 1 + 5) * lid),
        ("tapped_block", Pos(50, 60, 0) * tapped),
        ("tapped_screw", Pos(50, 60, 20) * socket_screw()),
        ("thread_stud", Pos(-50, -60, -1.6) * Cylinder(4, 16.8)),
        ("thread_nut", Pos(-50, -60, 0) * hex_nut(_M8_MINOR, 13, 6.8)),
        ("thread_lid", Pos(-50, -60, 6.8 + 5) * lid),
        ("fat_stud", Pos(50, -60, -1.6) * Cylinder(4.5, 16.8)),
        ("fat_nut", Pos(50, -60, 0) * hex_nut(_M8_MINOR, 13, 6.8)),
        ("fat_lid", Pos(50, -60, 6.8 + 5) * lid),
        ("pair_bolt", Pos(0, -60, -15.2) * pair_bolt),
        ("pair_nut", Pos(0, -60, 0) * hex_nut(_M8_MINOR, 13, 6.8)),
        ("pair_lid", Pos(0, -60, 6.8 + 5) * lid),
    ]


@cell("wrong_tool", ignore=["*wrong_tool_*"], timed=False)
def wrong_tool():
    """Fasteners whose rules name a tool that can't drive them (issue #72), and two
    whose tool fits only as the rule or the solid says. Each misfit is not covered,
    saying why, and nothing is swept. Not covered fails a run, so the bench's own runs
    ignore the cell and the edges sidecar describes it, as for drawn_in.

    The M8 nuts (13 across flats): size_nut's spanner-10, the wrong size; kind_nut's
    hex-key-5, the wrong kind; custom_nut's shop-spanner-23, the sidecar's own tool at
    the wrong size; unknown_nut's spanner-99, which no table holds, and says so.
    drawn_nut is named M10 (16 by ISO 4032) and drawn 15: its spanner-15 fits the
    solid, so it is swept. The M6 screws: button_screw's spanner-10 on a button head,
    slot_screw's slotted driver in a socket head, torx_screw's T99, which no table
    holds; and the M4 phillips_screw's PH1, where it takes PH2.
    """
    nuts = {"size": -120, "kind": -60, "custom": 0, "unknown": 60, "drawn": 120}
    screws = {"button": -120, "slot": -60, "torx": 0, "phillips": 60}
    holes = [(x, -40, 5.0) for x in nuts.values()] + [(x, 40, 3.3) for x in screws.values()]
    parts = [("plate", plate(w=320, d=160, holes=holes))]
    for name, x in nuts.items():
        nut = hex_nut(8, 13, 6.8) if name != "drawn" else hex_prism(15, 8) - Cylinder(5, 40)
        parts += [
            (f"{name}_stud", Pos(x, -40, 2.5) * Cylinder(4, 25)),
            (f"{name}_nut", Pos(x, -40, 0) * nut),
        ]
    parts += [
        ("button_screw", Pos(screws["button"], 40, 0) * button_screw()),
        ("slot_screw", Pos(screws["slot"], 40, 0) * socket_screw()),
        ("torx_screw", Pos(screws["torx"], 40, 0) * socket_screw()),
        ("phillips_screw", Pos(screws["phillips"], 40, 0) * pan_phillips()),
    ]
    return parts


# ---------------------------------------------------------------- issue #81: real solids
#
# Fasteners as makers and bd_warehouse draw them, with names that say no head: the
# solid has to. A maker chamfers every edge, countersinks a socket's mouth, leaves
# the drill's point at its bottom and chamfers the tip; none of those cones is a
# countersunk head, and a domed head's flat ring is no larger than its tip's end.


@cell(
    "chamfers",
    [{"parts": "screw", "kind": "screw", "head": "socket", "size": "M4"}],
    {"screw": {"verdict": "turns", "tool": "hex-key-3", "how": "driver straight in"}},
)
def chamfers():
    """An ISO 4762 M4 as a maker draws it (7 by 4, a 3 mm socket 2 deep), on a plate,
    nothing above: the 3 mm key goes straight in. Its eleven cones (the head's two
    chamfers, the socket's mouth and point, the tip) used to make it countersunk,
    and so M5, whose countersunk head a 3 mm key fits.
    """
    return [("plate", plate(holes=[(0, 0, 2.2)])), ("screw", vendor_socket_screw("M4"))]


@cell(
    "dome_tip",
    [{"parts": "screw", "kind": "screw", "head": "button", "size": "M3"}],
    {"screw": {"verdict": "turns", "tool": "hex-key-2", "how": "driver straight in"}},
)
def dome_tip():
    """An ISO 7380-1 M3x8 as a maker draws it: a spherical dome cut flat round its
    2 mm socket (a ring of 2.2 mm^2), the tip chamfered to a 5.2 mm^2 end, in a
    plate 10 thick with a floor 3 below. Taking the larger flat end for the head
    put the head at the tip, 8 down in the plate's hole: the key, coming up from
    there, met the floor within 3 mm. The head is the wide end: from the dome's top
    at 1.65 the key goes straight in.
    """
    return [
        ("plate", plate(holes=[(0, 0, 1.7)])),
        ("floor", slab(-10 - 3 - 10)),
        ("screw", vendor_button_screw("M3", length=8.0)),
    ]


def _countersunk_plate(d, dk, gap=0.7):
    """A plate with a 90 degree countersink a flat head sits in, ``gap`` clear all round."""
    sink = (dk - d) / 2 + gap
    hole = Pos(0, 0, -sink / 2 + 0.005) * Cone(d / 2, d / 2 + sink, sink + 0.01)
    return plate() - hole - Pos(0, 0, -5) * Cylinder(d / 2 + gap, 12)


@cell(
    "sunk_tip",
    [{"parts": "screw", "kind": "screw", "head": "flat", "size": "M4"}],
    {"screw": {"verdict": "turns", "tool": "hex-key-2.5", "how": "driver straight in"}},
)
def sunk_tip():
    """An ISO 10642 M4 as a maker draws it, its 90 degree countersink under a rim
    band, flush in a countersunk plate: still countersunk, which only its own cone
    says (shank to rim, at 90 degrees, facing out), past the socket's two cones and
    the tip's. The 2.5 mm key goes straight in.
    """
    d, dk, _, _ = VENDOR_FLAT["M4"]
    top = (dk - d) / 2 + 0.05 * dk  # the countersink and the rim band
    return [
        ("plate", _countersunk_plate(d, dk)),
        ("screw", Pos(0, 0, -top) * vendor_flat_screw("M4")),
    ]


@cell(
    "named_head",
    [{"parts": "bhcs", "kind": "screw", "head": "button", "size": "M4"}],
    {"bhcs": {"verdict": "turns", "tool": "hex-key-2.5", "how": "driver straight in"}},
)
def named_head():
    """A screw named a button head (BHCS) and drawn with ISO 4762's M4 outline,
    7 by 4, round ISO 7380-1's M4 socket, 2.5. Which keyed head a socket sits in
    is the outline's guess and the name's word, and the name's stands: a button
    head, M4, its 2.5 mm key straight in. Taken by its outline, it was a socket
    head, and 2.5 is ISO 4762's M3.
    """
    return [("plate", plate(holes=[(0, 0, 2.2)])), ("bhcs", vendor_socket_screw("M4", key=2.5))]


@cell(
    "w4762",
    [{"parts": "screw", "kind": "screw", "head": "socket", "size": "M5"}],
    {"screw": {"verdict": "turns", "tool": "hex-key-4", "how": "driver straight in"}},
)
def w4762():
    """bd_warehouse's ISO 4762 M5x16, its head's top edge rounded, on a plate,
    nothing above: the 4 mm key goes straight in."""
    screw = SocketHeadCapScrew(size="M5-0.8", length=16, fastener_type="iso4762", simple=True)
    return [("plate", plate(holes=[(0, 0, 2.75)])), ("screw", screw)]


@cell(
    "w4032",
    [{"parts": "nut", "kind": "nut", "size": "M5"}],
    {"nut": {"verdict": "turns", "tool": "spanner-8", "how": "ring, full length"}},
)
def w4032():
    """bd_warehouse's ISO 4032 M5 nut, its corners chamfered, on a stud up through a
    plate: the free face is the top, and the ring goes on from above."""
    nut = HexNut(size="M5-0.8", fastener_type="iso4032", simple=True)
    return [
        ("plate", plate(holes=[(0, 0, 2.75)])),
        ("stud", Pos(0, 0, 2.5) * Cylinder(2.5, 25)),
        ("nut", nut),
    ]


# ---------------------------------------------------------------- issue #84: a real export's names


@cell(
    "run_in",
    [{"parts": "hexnut", "kind": "nut", "size": "M6"}],
    {"hexnut": {"verdict": "turns", "tool": "spanner-10", "how": "ring, full length"}},
)
def run_in():
    """An M6 nut named in one word, as CAD exports write "Hexnut", on a stud up
    through a plate: the ring goes on from above. Detection used to find no noun
    in the name, and say nothing.
    """
    return [
        ("plate", plate(holes=[(0, 0, 3.5)])),
        ("stud", Pos(0, 0, 2.5) * Cylinder(3, 25)),
        ("hexnut", hex_nut(6, 10, 5.2)),
    ]


@cell(
    "badge",
    [
        {"parts": "screw", "kind": "screw", "head": "socket", "size": "M4"},
        {"parts": "boss_insert", "kind": "insert", "size": "M4"},
    ],
    {
        "screw": {"verdict": "turns", "tool": "hex-key-3", "how": "driver straight in"},
        "boss_insert": {"verdict": "held", "how": "holds itself", "pair": "screw"},
    },
)
def badge():
    """A logo inlaid in a plate and named an insert, as a printed part's inlay is:
    a plaque 30 by 12 by 2, no bore. No thread size, no word that says threaded,
    and no bore: not a fixed thread, so passed over, saying so. It used to be
    taken for one, and held. 60 along, boss_insert is named as barely, but its
    solid shows a bore (3.24, an M4's minor): a fixed thread, which an M4 socket
    head screws into, its 3 mm key straight in.
    """
    plaque = Pos(0, 0, -1) * Box(30, 12, 2)
    boss = Pos(60, 0, -3) * (Cylinder(3, 6) - Cylinder(1.62, 6.01))
    board = plate(holes=[(60, 0, 2.2)]) - plaque - Pos(60, 0, -3) * Cylinder(3, 6)
    screw = Pos(60, 0, 0) * socket_screw(d=4, length=12, dk=7, k=4, s=3, t=2)
    return [("plate", board), ("insert", plaque), ("boss_insert", boss), ("screw", screw)]


@cell(
    "tee_hold",
    [{"parts": "screw", **M6_SOCKET}, {"parts": "tnut", "kind": "insert", "size": "M6"}],
    {
        "screw": {"verdict": "blocked", "tool": "hex-key-5"},
        "tnut": {"verdict": "held", "how": "holds itself", "pair": "screw"},
    },
)
def tee_hold():
    """tapped_hold's M6 socket head screw, into a T-nut under the plate. As there,
    the key only holds it: the ceiling stops driver and long leg, and the slot
    leaves the short leg 36 deg of the 60 it needs. A T-nut never turns, so the
    screw must, which the reason says, not that its partner failed. Detected, the
    T-nut is bored 5.0, M6's tap drill and M5's diameter: its bore alone says M5,
    and the screw's M6 outranks it.
    """
    half_width = 2.835 + 60 * math.tan(math.radians(18))
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", socket_screw()),
        ("tnut", Pos(0, 0, -12) * (Box(20, 10, 4) - Cylinder(2.5, 5))),
        ("slot", slot_block(30, 48, 12, half_width)),
        ("ceiling", slab(51)),
    ]


# ---------------------------------------------------------------- issue #83: below M3

#: The small cell's fasteners: role -> (where, its rule, its truth). 160 apart, so the
#: longest spanner here (the 5 mm's 123) swings clear of its neighbours.
_SMALL = {
    "socket_screw": ((-240, 100), {"head": "socket", "size": "M2"}, "hex-key-1.5"),
    "tiny_nut": ((-80, 100), {"kind": "nut", "size": "M1.6"}, "spanner-3.2"),
    "little_nut": ((80, 100), {"kind": "nut", "size": "M2.5"}, "spanner-5"),
    "flat_screw": ((240, 100), {"head": "flat", "size": "M2"}, "hex-key-1.3"),
    "inch_socket_screw": ((-240, -100), {"head": "socket", "size": "#0"}, "hex-key-0.050in"),
    "inch_button_screw": ((-80, -100), {"head": "button", "size": "#0"}, "hex-key-0.035in"),
    "torx_screw": ((80, -100), {"head": "torx", "size": "M2"}, "torx-key-T6"),
    "phillips_screw": ((240, -100), {"head": "phillips", "size": "M2"}, "driver-ph0"),
}


def _small_how(tool):
    return "ring, full length" if tool.startswith("spanner") else "driver straight in"


@cell(
    "small",
    [{"parts": role, "kind": "screw", **rule} for role, (_, rule, _) in _SMALL.items()],
    {
        role: {"verdict": "turns", "tool": tool, "how": _small_how(tool)}
        for role, (_, _, tool) in _SMALL.items()
    },
)
def small():
    """Eight fasteners below M3 and at #0, each open above and taking its new tool
    (issue #83): ISO 4762's M2 (a 1.5 key, which metric-home holds), ISO 4032's M1.6
    and M2.5 nuts on studs (3.2 and 5 mm spanners), ISO 10642's M2 flush in its
    countersink (ISO 2936's 1.3 key), ASME B18.3's #0 socket and button heads (0.050
    and 0.035 in keys), an M2 Torx (T6) and an M2 Phillips pan head (PH0). Each used
    to be not covered: "M2 is outside the sizes the kit covers".
    """
    at = {role: where for role, (where, _, _) in _SMALL.items()}
    holes = [(*at[role], r) for role, r in (("socket_screw", 1.2), ("tiny_nut", 1.0))]
    holes += [(*at[role], r) for role, r in (("little_nut", 1.45), ("inch_socket_screw", 1.0))]
    holes += [(*at[role], r) for role, r in (("inch_button_screw", 1.0), ("torx_screw", 1.2))]
    holes += [(*at["phillips_screw"], 1.2)]
    d, dk, _, _ = VENDOR_FLAT["M2"]
    sunk = (dk - d) / 2 + 0.05 * dk  # the countersink and the rim band
    countersink = Pos(*at["flat_screw"], 0) * (_countersunk_plate(d, dk) - plate())
    board = plate(w=640, d=360, holes=holes) - countersink
    head = Pos(0, 0, 1) * Cylinder(1.9, 2) - Pos(0, 0, 1.5) * Cylinder(0.875, 1.01)
    pan = Pos(0, 0, 0.8) * Cylinder(2.0, 1.6)
    cross = Pos(0, 0, 1.2) * (Box(2.2, 0.45, 0.81) + Box(0.45, 2.2, 0.81))
    shank = Pos(0, 0, -3) * Cylinder(1.0, 6)
    return [
        ("plate", board),
        ("socket_screw", Pos(*at["socket_screw"], 0) * vendor_socket_screw("M2", length=6.0)),
        ("tiny_stud", Pos(*at["tiny_nut"], 2.5) * Cylinder(0.8, 15)),
        ("tiny_nut", Pos(*at["tiny_nut"], 0) * hex_nut(1.6, 3.2, 1.3)),
        ("little_stud", Pos(*at["little_nut"], 2.5) * Cylinder(1.25, 15)),
        ("little_nut", Pos(*at["little_nut"], 0) * hex_nut(2.5, 5.0, 2.0)),
        ("flat_screw", Pos(*at["flat_screw"], -sunk) * vendor_flat_screw("M2", length=6.0)),
        ("inch_socket_screw", Pos(*at["inch_socket_screw"], 0) * vendor_socket_screw("#0", 6.0)),
        ("inch_button_screw", Pos(*at["inch_button_screw"], 0) * vendor_button_screw("#0", 6.0)),
        ("torx_screw", Pos(*at["torx_screw"], 0) * (head + shank)),
        ("phillips_screw", Pos(*at["phillips_screw"], 0) * (pan - cross + shank)),
    ]


# ---------------------------------------------------------------- issue #82: sockets as drawn


@cell(
    "w7380",
    [{"parts": "screw", "kind": "screw", "head": "button", "size": "M5", "across_flats": 3.08}],
    {"screw": {"verdict": "turns", "tool": "hex-key-3", "how": "driver straight in"}},
)
def w7380():
    """bd_warehouse's ISO 7380-1 M5x16, its socket drawn 3.08, the standard's most for
    a 3 mm key, on a plate: the key goes in, straight. A socket is a little larger
    than its key, and 3.08 used to be no tool's size."""
    screw = ButtonHeadScrew(size="M5-0.8", length=16, fastener_type="iso7380_1", simple=True)
    return [("plate", plate(holes=[(0, 0, 2.75)])), ("screw", screw)]


@cell(
    "w10642",
    [{"parts": "screw", "kind": "screw", "head": "flat", "size": "M4", "across_flats": 2.6}],
    {"screw": {"verdict": "turns", "tool": "hex-key-2.5", "how": "driver straight in"}},
)
def w10642():
    """bd_warehouse's ISO 10642 M4x12 (DIN 7991's, in fact), flush in a countersunk
    plate, its socket drawn 2.60: 0.02 past ISO 10642's most for a 2.5 mm key, within
    the clearance a loosely drawn model gets. The key goes in, and a note says so."""
    screw = CounterSunkScrew(size="M4-0.7", length=12, fastener_type="iso10642", simple=True)
    return [("plate", _countersunk_plate(4.0, 7.42)), ("screw", screw)]


@cell(
    "pan_t40",
    [{"parts": "torx_screw", "kind": "screw", "head": "torx", "size": "M8", "across_flats": 6.75}],
    {"torx_screw": {"verdict": "turns", "tool": "torx-key-T40", "how": "driver straight in"}},
)
def pan_t40():
    """An M8 pan head with a T40 recess, as some makers sell it, where ISO 14583 says
    T45: across_flats gives the recess's point to point, 6.75, which is T40's (ISO
    10664's gauges, 6.673 to 6.814), and the full kit's T40 goes in straight. By its
    thread alone it needs a T45 key, which no kit holds. The recess is drawn round,
    as code-CAD draws one; only the sidecar can say its size.
    """
    head = Pos(0, 0, 2.4) * Cylinder(8, 4.8) - Pos(0, 0, 3.3) * Cylinder(3.375, 3.01)
    return [
        ("plate", plate(holes=[(0, 0, 4.5)])),
        ("torx_screw", head + Pos(0, 0, -8) * Cylinder(4, 16)),
    ]


# ---------------------------------------------------------------- issue #95: a thread and length

#: The std cell's screws: role -> (where, its rule, its tool). Named by thread and
#: length alone, as CAD libraries and suppliers name them; the cell's name is a
#: qualifier, so each part name is that and nothing else.
_STD = {
    "M3x16": ((-240, 0), {"head": "socket", "size": "M3"}, "hex-key-2.5"),
    "M5-0.8x12": ((-80, 0), {"head": "button", "size": "M5"}, "hex-key-3"),
    "M4x0.7x12": ((80, 0), {"head": "phillips", "size": "M4"}, "driver-ph2"),
    "#10-32x1": ((240, 0), {"head": "socket", "size": "#10"}, "hex-key-5/32in"),
}


@cell(
    "std",
    [{"parts": role, "kind": "screw", **rule} for role, (_, rule, _) in _STD.items()],
    {
        role: {"verdict": "turns", "tool": tool, "how": "driver straight in"}
        for role, (_, _, tool) in _STD.items()
    },
)
def std():
    """Four screws named by thread and length alone (issue #95): ISO 4762's M3x16
    (a 2.5 key), ISO 7380-1's M5 button head (3), an M4 Phillips pan head (PH2) and
    ASME B18.3's #10 socket head (5/32 in), each open above. Detection used to pass
    every one over without a word. Each name is now a screw candidate, taken on the
    drive its solid shows. Beside them, a stud named M8x60 shows no drive, as a
    stud or an insert named by its thread doesn't: passed over, saying so. And
    part7, an M6 socket head screw named nothing a fastener is: not checked, but
    passed over as a look-alike, so it isn't missed without a word; and part8, an
    M4 Phillips pan head, and part9, an M8 nut drawn 12.8 across (in ISO 4032's band),
    the same. In a row along y -120, what no look-alike is: a hex standoff (an M3
    nut's hex, 10 long), a collet (a 10 hex round a 4 bore), a knob 50 across with a
    2.5 socket over an M3 shank, a spool (a 2.5 socket in one of its two flanges), a
    wheel (an M3 head's outline, its socket 4 across), a pin socketed in a collar no
    wider than a head would be, and two names no screw's: an M4x10 spacer, and an
    M3x5x4 insert's sizes.
    """
    at = {role: where for role, (where, _, _) in _STD.items()}
    holes = [(*at["M3x16"], 1.6), (*at["M5-0.8x12"], 2.6), (*at["M4x0.7x12"], 2.1)]
    holes += [(*at["#10-32x1"], 2.5), (-160, 120, 4.1), (160, 120, 3.1)]
    inch = 25.4
    d, dk, s = 0.190 * inch, 0.312 * inch, 0.15625 * inch  # ASME B18.3 #10: 5/32 key
    return [
        ("plate", plate(w=640, d=360, holes=holes)),
        ("M3x16", Pos(*at["M3x16"], 0) * vendor_socket_screw("M3", length=16.0)),
        ("M5-0.8x12", Pos(*at["M5-0.8x12"], 0) * vendor_button_screw("M5", length=12.0)),
        ("M4x0.7x12", Pos(*at["M4x0.7x12"], 0) * pan_phillips()),
        ("#10-32x1", Pos(*at["#10-32x1"], 0) * socket_screw(d, inch, dk, d, s, 0.6 * d)),
        ("M8x60", Pos(-160, 120, 20) * Cylinder(4, 60)),
        ("part7", Pos(160, 120, 0) * socket_screw()),
        *((name, Pos(-288 + 64 * i, -120, 0) * shape) for i, (name, shape) in enumerate(_others())),
    ]


def _others():
    """std's row of parts, each on the plate's top: (name, shape) in its local frame."""
    knob = (
        Pos(0, 0, 19) * Cylinder(25, 6)
        - hex_prism(2.5, 2.01, 20)
        + Pos(0, 0, 8) * Cylinder(1.5, 16)
    )
    spool = Pos(0, 0, 5) * Cylinder(1.5, 10) + Pos(0, 0, 0.75) * Cylinder(5, 1.5)
    spool = spool + Pos(0, 0, 9.25) * Cylinder(5, 1.5) - hex_prism(2.5, 1.51, 8.5)
    wheel = Pos(0, 0, 9.5) * Cylinder(2.75, 3) - hex_prism(4.0, 1.31, 9.7)
    wheel += Pos(0, 0, 4) * Cylinder(1.5, 8)
    pin = Pos(0, 0, 0.25) * Cone(1.0, 1.5, 0.5) + Pos(0, 0, 8) * Cylinder(1.5, 15)
    pin = pin + Pos(0, 0, 17) * Cylinder(1.8, 3) - hex_prism(2.5, 1.51, 17)
    return [
        ("part8", Pos(0, 0, 12) * pan_phillips()),
        ("part9", hex_prism(12.8, 6.8) - Cylinder(4, 20)),
        ("standoff", hex_prism(5.5, 10) - Cylinder(1.5, 25)),
        ("collet", hex_prism(10, 6) - Cylinder(2, 15)),
        ("knob", knob),
        ("spool", spool),
        ("wheel", wheel),
        ("pin", pin),
        ("M4x10 spacer", Pos(0, 0, 5) * (Cylinder(2.5, 10) - Cylinder(2.1, 11))),
        ("M3x5x4", Pos(0, 0, 2.5) * (Cylinder(2.3, 5) - Cylinder(1.6, 6))),
    ]


# ---------------------------------------------------------------- issue #96: set screws, by hand

_GRIP_HOW = {"set_screw": "short leg in", "thumb_screw": "fingers round its head"}
_GRIP_HOW |= {"wheel_thumbscrew": "a fingertip on its rim", "wing_nut": "fingers round it"}


@cell(
    "grip",
    [
        {"parts": "set_screw", "kind": "screw", "head": "set", "size": "M3", "length": 4},
        {"parts": "thumb_screw", "kind": "screw", "size": "M3", "tool": "hand"},
        {"parts": "wheel_thumbscrew", "kind": "screw", "size": "M3", "tool": "hand"},
        {"parts": "wing_nut", "kind": "nut", "size": "M6", "tool": "hand"},
    ],
    {
        role: {
            "verdict": "turns",
            "tool": "hex-key-1.5" if role == "set_screw" else "hand",
            "how": how,
        }
        for role, how in _GRIP_HOW.items()
    },
)
def grip():
    """Issue #96: what isn't turned with a head's key or a spanner.

    An M3x4 set screw (ISO 4026: a 1.5 key, where ISO 4762's M3 takes 2.5) in a
    pulley's hub, socket out, 3.5 down its tapped hole (drawn at the 2.5 tap drill),
    10 over the plate: the key goes in along the hole, short leg first, as a driver's
    handle (14 round) meets the plate; and the screw backs out the same way. A thumb
    screw (an 8 across, 3 high knurled head) on a washer named for it, in the open:
    fingers round its head. A thumb wheel shut in a block but for a window on +x, 9
    high and 12 wide: no room for fingers round it, but a fingertip on its rim
    through the window turns it. An M6 wing nut (22 across its wings) on a stud,
    over a nylon washer named for it: fingers round it, the stud's end between them.
    The washers are named after their fasteners and are none themselves, nor is a
    spacer whose name's aside gives its screw's standard.
    """
    hub = Pos(-240, 0, 10) * (Cylinder(10, 12) - Cylinder(2.5, 13))
    hub -= Pos(-240 + 6.25, 0, 10) * Rot(0, 90, 0) * Cylinder(1.25, 7.5)
    block = Box(40, 40, 20) - Cylinder(5, 4) - Pos(0, 0, -6) * Cylinder(1.6, 9)
    block -= Pos(0, 0, 6) * Cylinder(4.6, 9) + Pos(12.5, 0, 0) * Box(25, 12, 9)
    washer = Cylinder(4, 1) - Cylinder(1.6, 2)
    return [
        ("plate", plate(w=640, d=360, holes=[(-80, 0, 1.6), (240, 0, 3.2)])),
        ("shaft", Pos(-240, 0, 15) * Cylinder(2.5, 30)),
        ("pulley", hub),
        ("set_screw", Pos(-240 + 6.5, 0, 10) * Rot(0, 90, 0) * set_screw()),
        ("washer_for_m3_screw", Pos(-80, 0, 0.5) * washer),
        ("thumb_screw", Pos(-80, 0, 1) * thumb_screw()),
        ("block", Pos(80, 0, 10) * block),
        ("wheel_thumbscrew", Pos(80, 0, 8.5) * thumb_screw(length=8.0)),
        ("stud", Pos(240, 0, 5) * Cylinder(3, 30)),
        ("nylon_washer (wingnut)", Pos(240, 0, 0.5) * (Cylinder(6, 1) - Cylinder(3.2, 2))),
        ("wing_nut", Pos(240, 0, 1) * wing_nut()),
        ("spacer (ISO 4762 M6 screw)", Pos(0, 120, 5) * (Cylinder(5, 10) - Cylinder(3.2, 11))),
    ]


# ---------------------------------------------------------------- issue #93: nut traps

#: An ISO 4762 M3 screw and an ISO 4032 M3 nut, as the issue draws them.
_M3_SOCKET = {"kind": "screw", "head": "socket", "size": "M3"}
_M3_NUT = {"kind": "nut", "size": "M3"}


@cell(
    "trap",
    [
        *({"parts": f"{where}_screw", **_M3_SOCKET} for where in ("slot", "pocket", "stopped")),
        *({"parts": f"{where}_nut", **_M3_NUT} for where in ("slot", "pocket", "stopped")),
    ],
    {
        "slot_screw": {"verdict": "turns", "tool": "hex-key-2.5", "pair": "slot_nut"},
        "slot_nut": {"verdict": "held", "pair": "slot_screw"},
        "pocket_screw": {"verdict": "turns", "tool": "hex-key-2.5", "pair": "pocket_nut"},
        "pocket_nut": {"verdict": "held", "pair": "pocket_screw"},
        "stopped_screw": {"verdict": "blocked", "tool": "hex-key-2.5", "pair": "stopped_nut"},
        "stopped_nut": {"verdict": "held", "pair": "stopped_screw"},
    },
)
def trap():
    """Nuts in traps, as printed parts hold them (issue #93): an M3x16 socket head
    screw down through a 16 deep block into an M3 nut (5.5 across flats, 2.4 thick).
    In slot, the nut sits in a slot 5.7 wide and 2.6 tall, open on +x, both its faces
    covered; in pocket, in a hex pocket 5.6 across flats in the block's underside,
    0.05 off each flat. Turning, the nut's corners (3.18 from its axis) meet the slot's
    walls, or the pocket's, on opposite sides: the block holds it, and its screw, open
    above, turns. They used to be not covered (both faces covered) and blocked (the
    corners hit the block). In stopped, the pocket again, under tee_hold's slotted guide
    and ceiling at M3's scale: the 2.5 key only holds its screw (the ceiling at 33 stops
    the driver and the long leg; the slot, 18 degrees each way at 60 out, leaves the
    short leg's arm, at 23.8, 36 of the 60 it needs). A trapped nut never turns, so
    the screw must, which its reason says.
    """
    screw = socket_screw(d=3, length=16, dk=5.5, k=3, s=2.5, t=1.3)
    nut = hex_nut(3, 5.5, 2.4)
    parts = []
    for where, x in (("slot", -200), ("pocket", 0), ("stopped", 200)):
        block = Pos(x, 0, -8) * Box(30, 30, 16) - Pos(x, 0, -8) * Cylinder(1.7, 17)
        if where == "slot":
            block -= Pos(x + 6.7, 0, -8) * Box(20, 5.7, 2.6)
            held = Pos(x, 0, -9.2) * nut
        else:
            block -= Pos(x, 0, -16) * hex_prism(5.6, 2.6)
            held = Pos(x, 0, -16) * nut
        parts += [(f"{where}_block", block), (f"{where}_screw", Pos(x, 0, 0) * screw)]
        parts.append((f"{where}_nut", held))
    half_width = 2.82 / 2 + 60 * math.tan(math.radians(18))  # the 2.5 key's shaft, 2.82 round
    stop = [("guide", Pos(200, 0, 0) * slot_block(15, 30, 8, half_width))]
    return [*parts, *stop, ("ceiling", Pos(200, 0, 0) * slab(33, w=130, d=130))]


# ---------------------------------------------------------------- issue #94: drawn twice, drawn in


def _m3x8():
    """ISO 4762 M3x8: a 5.5 by 3 head, a 2.5 socket 1.3 deep, the shank under z = 0."""
    return socket_screw(d=3, length=8, dk=5.5, k=3, s=2.5, t=1.3)


@cell("twice", ignore=["*twice_*"], timed=False)
def twice():
    """Drawing faults, which a sidecar rule describes as readily as a name (issue #94).
    Not-covered, so only the edges sidecar keeps them, as drawn_in's.

    In side, a box 10 on a side drawn 1 into the side of an M3x8's head (clear of its
    socket): the key goes in straight and turns it, and the box is in its way out. Its
    overlap with the head, by hand: the head's segment past x 1.75, 2.75^2 acos(1.75
    / 2.75) - 1.75 sqrt(2.75^2 - 1.75^2) = 2.957 mm^2, 3 high: 8.9 mm^3. It used to be
    stuck, the box in its way out, sending a reader looking for an order to take it
    apart in. In dup, the same M3x8 drawn twice in one hole, once named M3x12: the
    whole screw in common, the head's 71.27 less its socket's 7.04 and the shank's
    56.55, 120.8 mm^3. Each used to pass, and count. In clean, neither: it turns.
    """
    parts = []
    for where, x in (("side", -100), ("dup", 0), ("clean", 100)):
        parts.append(
            (f"{where}_plate", Pos(x, 0, -5) * Box(30, 30, 10) - Pos(x, 0, 0) * Cylinder(1.5, 30))
        )
        parts.append((f"{where}_screw", Pos(x, 0, 0) * _m3x8()))
    parts.append(("side_box", Pos(-100 + 2.75 - 1 + 5, 0, 5) * Box(10, 10, 10)))
    parts.append(("dup_M3x12_screw", _m3x8()))
    return parts


@cell(
    "renamed",
    [{"parts": "M3x12_screw", **_M3_SOCKET}],
    {"M3x12_screw": {"verdict": "turns", "tool": "hex-key-2.5", "how": "driver straight in"}},
)
def renamed():
    """An M3 socket head screw named M3x12 and drawn 8 long under its head (issue #94),
    as a screw copied and renamed in a CAD tree is, open above. Described, it turns;
    detected, its name's 12 is noted against the solid's 8, which is the length taken.
    """
    return [("plate", plate(holes=[(0, 0, 1.6)])), ("M3x12_screw", _m3x8())]


# ---------------------------------------------------------------- issue #103: the 5.5's length


@cell(
    "reach_55",
    [{"parts": "nut", "kind": "nut", "size": "M3"}],
    {"nut": {"verdict": "blocked", "tool": "spanner-5.5", "blocked_by": ["wall", "shelf"]}},
)
def reach_55():
    """An M3 nut on a stud, a shelf 10 over it and a ring wall round it from 97 out.
    The shelf leaves no room for a socket on its ratchet or a nut driver; the spanner
    lies flat under it, its handle reaching 0.85 of its length from the nut. Elora's
    5.5, 123 long, reaches 104.6 and meets the wall at every angle (5.5 has no
    stubby). As Hazet's 105, the length it used to have, it reached 89.3 and swung
    clear (issue #103)."""
    wall = Pos(0, 0, 6.2) * (Cylinder(107, 12.4) - Cylinder(97, 12.5))
    return [
        ("plate", plate(w=300, d=300, holes=[(0, 0, 1.6)])),
        ("stud", Pos(0, 0, 2) * Cylinder(1.5, 8)),
        ("nut", hex_nut(3, 5.5, 2.4)),
        ("wall", wall),
        ("shelf", slab(2.4 + 10)),
    ]


# ---------------------------------------------------------------- issue #101: PH4


def _m8_pan_phillips():
    """ISO 7045 M8x16: a pan head 16 across and 6 high, a PH4 cross 4 deep in its top."""
    head = Pos(0, 0, 3) * Cylinder(8, 6)
    cross = Pos(0, 0, 4) * (Box(9.0, 1.8, 4.01) + Box(1.8, 9.0, 4.01))
    return head - cross + Pos(0, 0, -8) * Cylinder(4, 16)


@cell(
    "ph4",
    [{"parts": "screw", "kind": "screw", "head": "phillips", "size": "M8"}],
    {"screw": {"verdict": "turns", "tool": "driver-ph4", "how": "driver straight in"}},
)
def ph4():
    """An M8 Phillips pan head, open above: ISO 7045 gives it PH4, which the full kit's
    driver, 10 round, fits. It used to take a PH3 (issue #101)."""
    return [("plate", plate(holes=[(0, 0, 4.5)])), ("screw", _m8_pan_phillips())]


# ---------------------------------------------------------------- issue #104: surfaces


@cell(
    "shelled",
    [{"parts": "screw", **M6_SOCKET}],
    {"screw": {"verdict": "blocked", "tool": "hex-key-5", "blocked_by": ["ceiling"]}},
)
def shelled():
    """key_wall_near's screw and ceiling, the ceiling exported as a closed shell, not a
    solid, as some exporters write one: taken as the solid it bounds, it stops the key
    as before (driver 200, short leg 36.1, long 88, all past its 15). The reader used
    to drop it, and the key turned the screw through it. Beside them a decal drawn as
    one face, an open shell: nothing can meet it, so it's left out, and the report
    says so (issue #104).
    """
    decal = Pos(60, 0, 0.5) * Box(20, 20, 1)
    return [
        ("plate", plate(holes=[(0, 0, 3)])),
        ("screw", socket_screw()),
        ("ceiling", Shell(slab(6 + 15).faces())),
        ("decal", Shell(decal.faces().sort_by(Axis.Z)[-1:])),
    ]


# ---------------------------------------------------------------- issue #117: a name's size


@cell(
    "misnamed",
    [
        {"parts": "M5x16_screw", **_M3_SOCKET},
        {"parts": "M5x12_phillips_screw", "kind": "screw", "head": "phillips", "size": "M3"},
        {"parts": "M5_nut", **_M3_NUT},
    ],
    {
        "M5x16_screw": {"verdict": "turns", "tool": "hex-key-2.5", "how": "driver straight in"},
        "M5x12_phillips_screw": {
            "verdict": "turns",
            "tool": "driver-ph1",
            "how": "driver straight in",
        },
        "M5_nut": {"verdict": "turns", "tool": "spanner-5.5", "how": "ring, full length"},
    },
)
def misnamed():
    """Three M3s under M5 names, open above, and a leadscrew's nut (issue #117).

    An ISO 4762 M3x16, its 2.5 socket and 3 shank both an M3's; an M3 pan head
    Phillips, 5.6 across, a 3 shank and no hex; an M3 nut, 5.5 across and bored 3,
    on a stud. Described as M3s, the key, the PH1 driver and the 5.5 ring each go
    straight on. Detected, each is taken as drawn and noted: no M5 is drawn so, its
    minor being 4.02. The screw and nut were checked as M3s before, silently; the
    Phillips was an M5 by its name, and took a PH2 that doesn't fit a PH1 cross.
    The leadscrew nut, a T8's flanged and bored 8, is no fastener a tool turns: it
    is passed over, in both runs, and fails nothing.
    """
    nut_x, lead_x = 20.0, 60.0
    flange = Pos(lead_x, 0, 1.75) * Cylinder(11, 3.5)
    body = Pos(lead_x, 0, 3.5 + 5.5) * Cylinder(5, 11)
    return [
        ("plate", plate(holes=[(-60, 0, 1.6), (-20, 0, 1.6), (nut_x, 0, 1.6), (lead_x, 0, 4)])),
        ("M5x16_screw", Pos(-60, 0, 0) * socket_screw(d=3, length=16, dk=5.5, k=3, s=2.5, t=1.3)),
        ("M5x12_phillips_screw", Pos(-20, 0, 0) * pan_phillips(d=3, length=12, dk=5.6, k=2.4)),
        ("stud", Pos(nut_x, 0, 2) * Cylinder(1.5, 8)),
        ("M5_nut", Pos(nut_x, 0, 0) * hex_nut(3, 5.5, 2.4)),
        ("leadscrew_nut", flange + body - Pos(lead_x, 0, 0) * Cylinder(4, 40)),
    ]


# ---------------------------------------------------------------- issue #116: all of a head

#: An ISO 7380-1 M4 button head's dome: the sphere through its rim (r 3.8 at z 0.4)
#: whose apex would be at 2.5, cut flat at 2.2 round its socket.
_DOME_R = (3.8**2 + 2.1**2) / (2 * 2.1)


def _button_m4():
    """An ISO 7380-1 M4x10 button head: a rim r 3.8, z 0 to 0.4, under the dome, a
    2.5 socket 1.3 deep; the shank r 2 under z = 0."""
    rim = Pos(0, 0, 0.2) * Cylinder(3.8, 0.4)
    dome = (Pos(0, 0, 2.5 - _DOME_R) * Sphere(_DOME_R)) & (Pos(0, 0, 1.3) * Box(8, 8, 1.8))
    socket = Pos(0, 0, 0.9) * extrude(RegularPolygon(2.5 / math.sqrt(3), 6), 1.31)
    return rim + dome - socket + Pos(0, 0, -5) * Cylinder(2, 10)


def _countersunk_m6():
    """An M6 countersunk head, 90 degrees, r 3 at z -3 to r 6 at z 0, no socket
    drawn; the shank r 3, 12 under it."""
    return Pos(0, 0, -1.5) * Cone(3, 6, 3) + Pos(0, 0, -9) * Cylinder(3, 12)


def _counterbored(bore):
    """A block round a countersunk M6: a counterbore r ``bore`` from z -3 up, a
    pocket r 8 over it 1 high and closed, and a hole tapped at the minor under it."""
    block = Pos(0, 0, -6) * Box(40, 40, 30) - Pos(0, 0, -1.5) * Cylinder(bore, 3)
    block -= Pos(0, 0, 0.5) * Cylinder(8, 1)
    return block - Pos(0, 0, -12) * Cylinder(_M6_MINOR / 2, 18)


@cell("domed", ignore=["*domed_*"], timed=False)
def domed():
    """Heads whose widest region isn't all of them (issue #116): a clash is measured
    on the whole head, from its bearing face to its top, and its shank is left out.
    Clashes are not-covered, so only the edges sidecar keeps them, as drawn_in's.

    An ISO 7380-1 M4 button head (its rim 18.15 mm^3, its dome 51.24, its socket
    7.04: 62.35 in all) three ways: buried, a block over it from z 0, all 62.35 in
    common, where its rim alone, which used to be measured, is 18.15; dome, a cover
    0.5 down onto its dome, clear of its rim, the cap of 0.8 less the cap of 0.3 and
    the socket's top 0.5, 8.49 - 1.24 - 2.71 = 4.54, which used to block the key;
    clear, the cover 2 over it, which blocks the key, as before.

    An M4 pan head 8 by 3.1, its top edge rounded r 1, a cover 0.5 down onto its
    crown: pi [10u - u^3/3 + 3 (u sqrt(1 - u^2) + asin u)] from u 0.5 to 1, 20.58,
    less the cross's 7.8 mm^2 by 0.5: 16.68. Its widest region stops under the
    fillet, at 2.1, and the cover used to block the driver.

    An M6 countersunk head, 90 degrees, in a block closed 1 over it, its shank in a
    hole tapped at the minor: cone, the counterbore r 5 where the cone runs out to
    6, pi (72 - 66.67) = 16.76 in common, the thread's 75 not added; thread, the
    counterbore r 6.1, clear of the cone, only the thread in common, and blocked.
    The thread used to be measured: the cone's rim is too thin to be a region.
    """
    cover = Box(20, 20, 4)
    plate_ = Pos(0, 0, -5) * Box(30, 30, 10)
    cases = ("buried", "dome", "clear", "pan", "cone", "thread")
    xs = dict(zip(cases, range(-250, 300, 100), strict=True))
    parts = []
    for case in ("buried", "dome", "clear"):
        x = xs[case]
        parts.append((f"button_{case}_plate", Pos(x, 0, 0) * (plate_ - Cylinder(2, 30))))
        parts.append((f"button_{case}_screw", Pos(x, 0, 0) * _button_m4()))
    parts.append(("button_buried_block", Pos(xs["buried"], 0, 10) * Box(20, 20, 20)))
    parts.append(("button_dome_cover", Pos(xs["dome"], 0, 1.7 + 2) * cover))
    parts.append(("button_clear_cover", Pos(xs["clear"], 0, 2.2 + 2 + 2) * cover))
    parts.append(("pan_plate", Pos(xs["pan"], 0, 0) * (plate_ - Cylinder(2, 30))))
    parts.append(("pan_screw", Pos(xs["pan"], 0, 0) * pan_phillips(d=4, length=12, dk=8, k=3.1)))
    parts.append(("pan_cover", Pos(xs["pan"], 0, 2.6 + 2) * cover))
    for case, bore in (("cone", 5.0), ("thread", 6.1)):
        parts.append((f"flat_{case}_screw", Pos(xs[case], 0, 0) * _countersunk_m6()))
        parts.append((f"flat_{case}_block", Pos(xs[case], 0, 0) * _counterbored(bore)))
    return parts


# ---------------------------------------------------------------- issue #115: cross recesses


def _cut_past(solid, point, normal):
    """The solid less everything past a plane through ``point``, ``normal`` out of it."""
    return solid - Plane(origin=point, z_dir=normal) * Pos(0, 0, 50) * Box(100, 100, 100)


def _wing(top, reach, floor, width, depth, taper):
    """A cross recess's wing along +x, planes all: ``reach`` out at the top, its end
    sloping in to ``floor`` at its floor ``depth`` down, its walls ``width`` apart at
    the top and leaning in ``taper`` degrees."""
    block = Pos(reach / 2, 0, top - depth / 2 + 0.005) * Box(reach, width, depth + 0.01)
    lean = math.tan(math.radians(taper))
    for side in (1, -1):
        block = _cut_past(block, (0, side * width / 2, top), (0, side, -lean))
    return _cut_past(block, (reach, 0, top), (1, 0, -(reach - floor) / depth))


def _cross_screw(d, dk, k, span, width, depth, taper, vees=0.0):
    """A pan head ``dk`` by ``k`` on a shank ``d``, a cross recess in its top: four
    wings ``span`` across, and with ``vees`` faces between them, a square turned 45
    degrees whose corners reach that far out along the wings."""
    recess = None
    for turn in (0, 90, 180, 270):
        piece = Rot(0, 0, turn) * _wing(k, span / 2, span / 8, width, depth, taper)
        recess = piece if recess is None else recess + piece
    if vees:
        block = Pos(0, 0, k - depth / 2) * Box(2 * vees, 2 * vees, depth)
        for turn in (45, 135, 225, 315):
            out = (math.cos(math.radians(turn)), math.sin(math.radians(turn)))
            at, lean = vees / 2**0.5, math.tan(math.radians(taper))
            block = _cut_past(block, (at * out[0], at * out[1], k), (*out, -lean))
        recess = recess + block
    head = Pos(0, 0, k / 2) * Cylinder(dk / 2, k) - recess
    return head + Pos(0, 0, -5) * Cylinder(d / 2, 10)


#: The Fusion name of the cross cell's tapping screw, as SO-101's are named.
FUSION_TAPPING = (
    "Type I Cross Recessed Fillister Head Tapping Screw ANSI B18.6.4 1-42 x 0.1875 Type AB"
)


@cell(
    "cross",
    [
        {"parts": "M3x6_screw", "kind": "screw", "head": "phillips", "size": "M3"},
        {"parts": "M2_self_tapping_screw", "kind": "screw", "head": "phillips", "size": "M2"},
        {"parts": FUSION_TAPPING, "kind": "screw", "head": "phillips", "size": "#1"},
    ],
    {
        "M3x6_screw": {"verdict": "turns", "tool": "driver-ph1", "how": "driver straight in"},
        "M2_self_tapping_screw": {
            "verdict": "turns",
            "tool": "driver-ph0",
            "how": "driver straight in",
        },
        FUSION_TAPPING: {"verdict": "turns", "tool": "driver-ph0", "how": "driver straight in"},
    },
)
def cross():
    """Cross recesses drawn as makers draw them, open above (issue #115). Described,
    each turns with the driver its thread's standard gives, straight in: PH1 for
    the M3 (ISO 7045), PH0 for the M2 and the #1 (ASME B18.6.3).

    The M3, the issue's: a pan head 5.6 by 2.4, its wings 3.2 across and 0.6 wide,
    1.4 deep, their ends sloping in. The M2, as the Voron Legacy's: wings 2.4 across,
    0.33 wide, walls leaning 6 degrees, V faces between them. The #1 as SO-101's,
    under its Fusion name: wings 1.6 across, 0.31 wide, leaning 4 degrees. Detected,
    each used to be no cross: the M3's head was guessed a button and turned with a
    hex key, the M2's was not covered, there being no M2 button head, and the #1
    was passed over, its name's noun followed by words and no drive read in it.
    """
    return [
        ("plate", plate(holes=[(-60, 0, 1.6), (0, 0, 1.1), (60, 0, 1.0)])),
        ("M3x6_screw", Pos(-60, 0, 0) * _cross_screw(3, 5.6, 2.4, 3.2, 0.6, 1.4, 0)),
        (
            "M2_self_tapping_screw",
            Pos(0, 0, 0) * _cross_screw(2, 3.8, 1.6, 2.4, 0.33, 1.0, 6, vees=0.75),
        ),
        (FUSION_TAPPING, Pos(60, 0, 0) * _cross_screw(1.854, 3.3, 1.5, 1.6, 0.31, 0.8, 4)),
    ]


@cell(
    "ring_way_on",
    [
        {"parts": "*_bolt", "kind": "screw", "head": "hex", "size": "M8"},
        {"parts": "*_nut", "kind": "nut", "size": "M8"},
    ],
    {
        "tight_nut": {"verdict": "turns", "tool": "spanner-13", "how": "open end, full length"},
        "roomy_nut": {"verdict": "turns", "tool": "spanner-13", "how": "ring, full length"},
        "tight_bolt": {"verdict": "turns", "tool": "spanner-13", "how": "ring, full length"},
        "roomy_bolt": {"verdict": "turns", "tool": "spanner-13", "how": "ring, full length"},
    },
)
def ring_way_on():
    """A ring gets on along the axis, over the bolt's end (issue #121). Two M8 joints,
    each a bolt up through the plate, its head under it, and a 13 nut 6.5 high on top,
    the bolt's end 1.5 past it, at z 8. A 13 ring, 5.4 thick, clears the bolt's end at
    13.4. Over the tight nut a cover's underside is 3 above it, at 9.5: no ring gets
    on, and the open end turns it from the side, under the cover. Over the roomy nut
    it is 10 above, at 16.5: the ring turns it. The tight nut used to turn with the
    ring too. Each bolt's ring comes up from under the plate, its nut on the far side.
    The joints stand 300 apart, past a 13 spanner's reach.
    """
    parts = [("plate", plate(w=400, t=10, holes=[(-150, 0, 4.5), (150, 0, 4.5)]))]
    for tag, x, gap in (("tight", -150, 3.0), ("roomy", 150, 10.0)):
        parts += [
            (f"{tag}_bolt", Pos(x, 0, -10) * Rot(180, 0, 0) * hex_bolt(8, 18, 13, 5.3)),
            (f"{tag}_nut", Pos(x, 0, 0) * hex_nut(8, 13, 6.5)),
            (f"{tag}_cover", Pos(x, 0, 0) * slab(6.5 + gap, w=60, d=60)),
        ]
    return parts
