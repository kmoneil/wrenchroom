"""A cross recess drawn as makers draw it, and the names they give it (issue #115).

A cross used to be read only as two slots with square ends, each arm showing two
wall offsets (its sides and its end). A Phillips recess as CAD libraries and makers
draw it has wings whose walls taper a few degrees and whose ends slope down to the
centre, often with V faces between the wings; none of that was read, and the head
fell to its outline's guess, a button head, which passed with a hex key.

Now a cross is four wings at right angles round the axis, each a pair of walls
facing each other at one offset, out along the wing; its size is the wings' span. A
recess with walls that is no hex socket, cross or slot isn't guessed a keyed head.
Names: ``cross recessed`` and ``Type I`` say Phillips anywhere, ASME's B18 standards
are standards, and the bare numbered sizes Fusion writes beside one (``1-42``) are
sizes.

The models: pan heads 5.6 across and 2.4 high (an M3's, ISO 7045's), each wing a
block cut by planes, so its faces are planes, as a STEP's are (a loft's are
B-spline surfaces, even where flat).
"""

import math

import pytest
from build123d import Box, Cylinder, Plane, Pos, RegularPolygon, Rot, extrude

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.detect import NO_RECESS_READ, find, read_name, read_shape
from wrenchroom.detect.geometry import looks_like
from wrenchroom.fasteners import Head, Kind, Size
from wrenchroom.report import Verdict

TOP = 2.4


def cut_past(solid, point, normal):
    """The solid less everything past a plane through ``point``, ``normal`` out of it."""
    return solid - Plane(origin=point, z_dir=normal) * Pos(0, 0, 50) * Box(100, 100, 100)


def wing(reach=1.6, floor=0.4, width=0.6, depth=1.4, taper=0.0):
    """One wing along +x, from the axis out: ``reach`` at the top, ``floor`` at its
    floor (less, its end sloping in), its walls ``width`` apart at the top, leaning
    in by ``taper`` degrees each."""
    block = Pos(reach / 2, 0, TOP - depth / 2 + 0.005) * Box(reach, width, depth + 0.01)
    lean = math.tan(math.radians(taper))
    for side in (1, -1):
        block = cut_past(block, (0, side * width / 2, TOP), (0, side, -lean))
    return cut_past(block, (reach, 0, TOP), (1, 0, -(reach - floor) / depth))


def cross(turns=(0, 90, 180, 270), **wing_args):
    """Wings round the axis at ``turns`` degrees: four at right angles, a cross."""
    found = None
    for turn in turns:
        piece = Rot(0, 0, turn) * wing(**wing_args)
        found = piece if found is None else found + piece
    return found


def vee(half=0.75, depth=1.0, taper=6.0):
    """Faces filling between the wings: a square turned 45 degrees, its corners out
    ``half`` along the wings, its faces facing the axis between them (two of them at
    right angles, as a wing's would), leaning in by ``taper``, ``depth`` deep."""
    block = Pos(0, 0, TOP - depth / 2 + 0.005) * Box(2 * half, 2 * half, depth + 0.01)
    lean = math.tan(math.radians(taper))
    for turn in (45, 135, 225, 315):
        out = (math.cos(math.radians(turn)), math.sin(math.radians(turn)))
        at = half / 2**0.5
        block = cut_past(block, (at * out[0], at * out[1], TOP), (*out, -lean))
    return block


def pinwheel(reach=1.6, width=0.6, depth=1.4):
    """Four wings round the axis, each from the axis out along +x turned, and from
    the axis's line ``width`` to one side: a pinwheel, no wing centred on its line."""
    found = None
    for turn in (0, 90, 180, 270):
        piece = Rot(0, 0, turn) * (
            Pos(reach / 2, width / 2, TOP - depth / 2 + 0.005) * Box(reach, width, depth + 0.01)
        )
        found = piece if found is None else found + piece
    return found


def screw(recess=None, shank=3.0):
    head = Pos(0, 0, TOP / 2) * Cylinder(2.8, TOP)
    if recess is not None:
        head -= recess
    return head + Pos(0, 0, -3) * Cylinder(shank / 2, 6)


def reading(recess, **kwargs):
    return read_shape(screw(recess, **kwargs), Kind.SCREW)


# ---------------------------------------------------------------------------
# The solid: what a cross is, and what isn't one.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "recess",
    [
        # The issue's: two slots 3.2 by 0.6, 1.4 deep, square ends; the same with
        # their ends sloping in from 3.2 at the top to 0.8 at the floor.
        Pos(0, 0, TOP - 0.7) * (Box(3.2, 0.6, 1.41) + Box(0.6, 3.2, 1.41)),
        cross(),
        cross(taper=4.0),  # SO-101's wings: walls tapering 4 degrees, ends sloping
        cross(taper=6.0) + vee(),  # Voron Legacy's: 6 degrees, V faces between wings
        cross(taper=9.5),  # leaning less than 10 degrees: walls still
        Rot(0, 0, 17) * cross(taper=4.0),  # turned about the axis
    ],
    ids=["square_ends", "sloped_ends", "tapered_4", "tapered_6_vees", "tapered_9.5", "turned"],
)
def test_a_cross_is_four_wings_at_right_angles(recess):
    read = reading(recess)
    assert read.head is Head.PHILLIPS
    assert read.cross_mm == pytest.approx(3.2, abs=0.01)
    assert not read.unread_recess


def test_a_screw_turned_any_way_is_read_the_same():
    body = Rot(30, 40, 0) * screw(cross(taper=6.0) + vee())
    read = read_shape(body, Kind.SCREW)
    assert (read.head, read.cross_mm) == (Head.PHILLIPS, pytest.approx(3.2, abs=0.01))
    flipped = Rot(180, 0, 0) * screw(cross(taper=4.0))
    assert read_shape(flipped, Kind.SCREW).head is Head.PHILLIPS


def test_the_span_is_the_wings_reach_at_the_top():
    assert reading(cross(reach=2.2, floor=0.5)).cross_mm == pytest.approx(4.4, abs=0.01)
    # Wings of two reaches: the span is each side's farthest, added.
    lopsided = cross(turns=(0, 180)) + cross(turns=(90, 270), reach=2.0, floor=0.5)
    assert reading(lopsided).cross_mm == pytest.approx(4.0, abs=0.01)


@pytest.mark.parametrize(
    ("recess", "head", "unread"),
    [
        # A slot right across the head: its walls are centred on the axis.
        (Pos(0, 0, TOP - 0.7) * Box(7, 0.6, 1.41), Head.SLOTTED, False),
        # A square socket, Robertson's: walls on the axis, two ways round. No wings.
        (Pos(0, 0, TOP - 0.7) * Box(1.5, 1.5, 1.41), None, True),
        # Three wings, a T: no cross.
        (cross(turns=(0, 90, 180)), None, True),
        # Two slots at 60 degrees, not 90.
        (cross(turns=(0, 60, 180, 240)), None, True),
        # Four wings, two of them wider: walls at two offsets, no cross; the narrow
        # pair one slot, as any slot is.
        (cross(turns=(0, 180)) + cross(turns=(90, 270), width=0.9), Head.SLOTTED, False),
        # Walls leaning more than 10 degrees: a cone of a recess, no walls at all.
        (cross(taper=11.0), Head.BUTTON, False),
        # Two wings, one line: a slot, sloping at its ends.
        (cross(turns=(0, 180)), Head.SLOTTED, False),
        # Four wings off the axis, a pinwheel as Torq-set's are: each wing a slot
        # with one wall on the axis's line, so no wing has walls facing both ways.
        (pinwheel(), None, True),
    ],
    ids=[
        "slot",
        "square",
        "three_wings",
        "sixty_degrees",
        "two_widths",
        "leaning_11",
        "two_wings",
        "pinwheel",
    ],
)
def test_what_is_no_cross(recess, head, unread):
    read = reading(recess)
    assert read.cross_mm is None
    assert (read.head or read.head_guess, read.unread_recess) == (head, unread)


def test_a_hex_socket_is_a_hex_socket_still():
    socket = Pos(0, 0, TOP - 1.3) * extrude(RegularPolygon(2.5 / 3**0.5, 6), 1.31)
    read = reading(socket)
    assert (read.head, read.drive_af, read.cross_mm, read.unread_recess) == (
        Head.BUTTON,
        pytest.approx(2.5),
        None,
        False,
    )


def test_a_plain_head_is_guessed_by_its_outline_as_before():
    read = reading(None)
    assert (read.head, read.head_guess, read.unread_recess) == (None, Head.BUTTON, False)


def test_a_flat_on_a_head_s_side_is_no_recess():
    # A head with a flat milled on its side, 2.4 from the axis, as an anti-rotation
    # head has: a planar face near parallel to the axis, facing away from it. No
    # recess, so the outline guesses the head as before.
    body = screw() - Pos(2.4 + 5, 0, 1.2) * Box(10, 10, 2.41)
    read = read_shape(body, Kind.SCREW)
    assert (read.head, read.head_guess, read.unread_recess) == (None, Head.BUTTON, False)


# ---------------------------------------------------------------------------
# Detection and the check.
# ---------------------------------------------------------------------------


def plate():
    return Pos(0, 0, -5) * Box(30, 30, 10) - Cylinder(1.5, 30)


def test_the_issue_s_sloped_cross_takes_a_phillips_driver():
    # It used to be guessed a button head, "M3 button screw hex-key-2 all pass".
    model = Assembly([Part("plate", plate()), Part("M3x6 screw", screw(cross()))])
    (result,) = check(model).results
    assert (result.fastener.head, result.tool) == (Head.PHILLIPS, "driver-ph1")
    assert result.notes == ()
    assert result.fastener.basis == (
        "noun 'screw', M3x6; solid: phillips, a cross 3.20 across its wings"
    )


def test_a_recess_no_tool_fits_is_not_covered_not_guessed():
    # A square socket, and no name for its head: no key is guessed for it.
    model = Assembly(
        [Part("plate", plate()), Part("M3 screw", screw(Pos(0, 0, 1.7) * Box(1.5, 1.5, 1.41)))]
    )
    (result,) = check(model).results
    assert (result.verdict, result.tool, result.reason) == (
        Verdict.NOT_COVERED,
        None,
        NO_RECESS_READ,
    )
    assert NO_RECESS_READ == (
        "its head shows a recess that is no hex socket, Torx, cross or slot; say head: in "
        "the sidecar, or name its drive"
    )
    assert result.fastener.confidence == "low"


def test_a_name_s_head_outranks_an_unread_recess():
    square = Pos(0, 0, 1.7) * Box(1.5, 1.5, 1.41)
    (fastener,) = find([Part("M3 phillips screw", screw(square))]).fasteners
    assert (fastener.head, fastener.not_covered) == (Head.PHILLIPS, None)


def test_a_part_named_nothing_with_a_cross_is_said():
    assert looks_like(screw(cross(taper=6.0) + vee())) == (
        Kind.SCREW,
        "M3 screw, a cross in its head",
    )


# ---------------------------------------------------------------------------
# Names.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "head", "size", "length", "basis"),
    [
        (
            "Pan Head Screw DIN EN ISO 7045 - M3 x 6 - H Steel 4.6 Plain v1",
            Head.PHILLIPS,
            "M3",
            6.0,
            "ISO 7045, M3 x 6",
        ),
        (
            "Type I Cross Recessed Pan Head Machine Screw ANSI B18.6.3 - #4-40 x 1/4 v1",
            Head.PHILLIPS,
            "#4",
            6.35,
            "ASME B18.6.3, drive 'type i', #4-40 x 1/4",
        ),
        (
            "Cross Recessed Pan Head Screw #4-40 x 1/4",
            Head.PHILLIPS,
            "#4",
            6.35,
            "noun 'screw', drive 'cross recessed', #4-40 x 1/4",
        ),
        (
            "Type I Cross Recessed Fillister Head Tapping Screw ANSI B18.6.4 1-42 x 0.1875 "
            "Type AB Steel Grade 2 Plain v1",
            Head.PHILLIPS,
            "#1",
            4.762,
            "ASME B18.6.4, drive 'type i', #1-42 x 0.1875",
        ),
        (
            "Type I Cross Recessed Fillister Head Tapping Screw ANSI B18.6.4 0-48 x 0.1875 "
            "Type AB Steel Grade 2 Plain v1",
            Head.PHILLIPS,
            "#0",
            4.762,
            "ASME B18.6.4, drive 'type i', #0-48 x 0.1875",
        ),
    ],
    ids=["iso_7045", "b18_6_3", "cross_recessed", "b18_6_4_1_42", "b18_6_4_0_48"],
)
def test_fusion_s_fastener_names(name, head, size, length, basis):
    hint = read_name(name)
    assert hint is not None
    assert (hint.kind, hint.head, hint.size, hint.length_mm, hint.basis) == (
        Kind.SCREW,
        head,
        Size.parse(size),
        length,
        basis,
    )
    assert not hint.needs_drive


@pytest.mark.parametrize(
    ("name", "head"),
    [
        ("cross-recessed screw", Head.PHILLIPS),
        ("CrossRecessed lid screw", Head.PHILLIPS),
        ("cross recess pan screw", Head.PHILLIPS),
        ("M3x8 Type I screw", Head.PHILLIPS),
        ("lid screw, type I", Head.PHILLIPS),
        ("Type IA screw", None),  # ASME's Pozidriv-alike: not said here
        ("Type AB tapping screw", None),  # a tapping screw's thread
        ("cross_member_screw", None),  # a cross member: "cross" alone touches no noun
        ("recessed cross screw", Head.PHILLIPS),  # "cross" touching the noun, as before
        ("Type I nut", None),  # a nut takes no head
    ],
)
def test_cross_recessed_and_type_i_say_phillips_anywhere(name, head):
    hint = read_name(name)
    assert hint is not None
    assert hint.head is head


@pytest.mark.parametrize(
    ("name", "kind", "head", "basis"),
    [
        ("Machine Screw ANSI B18.6.3", Kind.SCREW, None, "ASME B18.6.3"),
        ("Tapping Screw ASME B18.6.4", Kind.SCREW, None, "ASME B18.6.4"),
        ("Hex Bolt ANSI/ASME B18.2.1 1/4-20 x 1", Kind.SCREW, Head.HEX, "ASME B18.2.1, 1/4-20 x 1"),
        # B18.2.1 holds square and lobed heads too: "hex" says the head, not the standard.
        ("Bolt ANSI B18.2.1 1/4-20 x 1", Kind.SCREW, None, "ASME B18.2.1, 1/4-20 x 1"),
        ("Hex Nut ASME B18.2.2 5/16-18", Kind.NUT, None, "ASME B18.2.2, 5/16-18"),
        (
            "Button Head Screw ASME_B18.3 #10-32 x 1/2",
            Kind.SCREW,
            Head.BUTTON,
            "ASME B18.3, #10-32 x 1/2",
        ),
        ("part_ansi_b18_6_3", Kind.SCREW, None, "ASME B18.6.3"),
    ],
)
def test_asme_standards_are_standards(name, kind, head, basis):
    hint = read_name(name)
    assert hint is not None
    assert (hint.kind, hint.head, hint.basis) == (kind, head, basis)


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("Tapping Screw ANSI B18.6.4 1-42 x 0.25", "#1"),
        ("Tapping Screw ANSI B18.6.4 0-48 x 0.25", "#0"),
        ("Machine Screw ANSI B18.6.3 4-40 x 0.25", "#4"),
        ("Machine Screw ANSI B18.6.3 10-32 x 0.5", "#10"),
        ("Tapping Screw ANSI B18.6.4 8-15 x 0.5", "#8"),  # type A's
        ("Machine Screw ANSI B18.6.3 #4-40 x 0.25", "#4"),  # marked already
        ("Machine Screw ANSI B18.6.3 4-41 x 0.25", None),  # no #4 thread
        ("Machine Screw ANSI B18.6.3 5-40 x 0.25", None),  # #5: no size the tables hold
        ("Machine Screw 4-40 x 0.25", None),  # bare, and no ASME standard beside it
        ("Machine Screw ANSI B18.6.3 rev 2-56a", None),  # in a word
    ],
)
def test_a_bare_numbered_size_beside_an_asme_standard(name, size):
    hint = read_name(name)
    assert hint is not None
    assert hint.size == (Size.parse(size) if size else None)
