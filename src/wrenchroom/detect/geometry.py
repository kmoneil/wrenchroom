"""Fasteners from geometry: what a named part's solid shows (spec 7.2).

For a part its name has already marked as a fastener (M4 reads named parts
only), this measures what the name may have left out:

- **the axis**: the common axis of its round faces;
- **the drive the model shows**: a hexagon round the axis (a hex head or a nut,
  whose across-flats a spanner grips), a hexagonal pocket in the head (whose
  across-flats is the key), a cross or a single slot, or a square neck under the
  head (a carriage bolt);
- **the thread size**: from the drive when the model shows one (a hex's or a
  socket's across-flats names its size through the standard tables), else from
  the shank's diameter (a screw) or the bore's (a nut), snapped to a standard
  size only when it sits within :data:`SIZE_SNAP_MM` of one.

Every field is reported only when the solid shows it plainly, and is None
otherwise, so whatever the name said stands. A head comes from a drive the model
shows; the head's outline alone (a plain cylinder, a dome, a countersink) is only
``head_guess``, worth using when the name says nothing. Which keyed head a hex
socket is in (socket, button, countersunk) is the outline's to say too, so a
head the name gives outranks it there as well (issue #81).

Makers' models are full of cones: a chamfer on each edge of the head, a
socket's countersunk mouth and drilled point, a chamfered tip. A countersunk
head is only the one cone that is the head itself (:func:`_countersunk`), and
the head's end and size are read from the screw's widest section
(:func:`wide_end`), never from a cone or the larger flat face (issue #81).

Flats are found as planar faces parallel to the axis. A face whose outward
normal points away from the axis is the outside of a prism (a hex head, a nut, a
square neck); one pointing toward it is the wall of a pocket or recess (a hex
socket, a slot). Distances are measured from the axis to each face's plane, so a
face split by other features still counts.

A cross recess is read from its wings (issue #115): four at right angles round
the axis, each a pair of walls facing each other at one offset, out along the
wing. Makers taper the walls a few degrees and slope the wings' ends, and some
fill between the wings with V faces; none of that matters. A Torx recess is read
from its lobes (issue #124): six round walls along the axis, of one radius, their
own axes at one offset and 60 degrees apart, the recess inside them. A recess with
walls that is no hex socket, Torx, cross or slot (a square's, or any round or
B-spline wall facing the axis) is ``unread_recess``, and the head isn't guessed
from its outline: a hex key fits none of them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from build123d import GeomType
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer

from wrenchroom.fasteners import (
    BUTTON_KEY_AF,
    FLAT_KEY_AF,
    HEAD_OUTLINE,
    HEAD_STANDARD,
    HEX_AF,
    IMPERIAL_SIZES,
    METRIC_SIZES,
    SET_KEY_AF,
    SHOULDER_KEY_AF,
    SHOULDER_OUTLINE,
    SHOULDER_THREAD,
    SOCKET_KEY_AF,
    Head,
    Kind,
    Size,
    in_hex_band,
    in_recess_band,
    loosely_fits,
    standard_hex_afs,
)

if TYPE_CHECKING:
    from build123d import Face, Shape, Vector, Vertex

Vec = tuple[float, float, float]

#: A measured thread diameter snaps to a standard size only this close to it,
#: mm. Models drawn at the nominal diameter land inside it. A thread drawn at its
#: minor diameter usually lands outside (an M6's 4.92 is 0.08 from M5), but not
#: always (an M5's 4.13 is 0.03 from #8): that is why a modelled drive, when
#: there is one, outranks the shank.
SIZE_SNAP_MM = 0.05

#: Faces count as parallel or perpendicular to the axis within this, as a cosine.
_PARALLEL = 0.999
_PERPENDICULAR = 0.02

#: A recess's walls lean off the axis by up to this, degrees: makers taper a cross
#: recess's, 4 and 6 degrees in the models of issue #115.
_WALL_TAPER_DEG = 10.0

#: A cross's walls sit at one offset from the axis within this, mm.
_CROSS_WALLS = 0.05

#: Flats at the same distance from the axis, within this, mm, belong to one prism.
_SAME_DISTANCE = 0.02

#: Two flat directions are the same within this many degrees.
_SAME_ANGLE_DEG = 1.0

#: A coaxial face's axis may sit this far off the part's axis, mm.
_COAXIAL_MM = 0.05

#: A recess's round walls that aren't cylinders: a spline drawn and swept.
_SPLINES = {GeomType.BSPLINE, GeomType.BEZIER, GeomType.EXTRUSION, GeomType.OFFSET}

#: Which table names the sizes a keyed head's socket fits.
_KEY_TABLES: dict[Head, dict[str, float]] = {
    Head.SOCKET: SOCKET_KEY_AF,
    Head.BUTTON: BUTTON_KEY_AF,
    Head.FLAT: FLAT_KEY_AF,
    Head.SHOULDER: SHOULDER_KEY_AF,
    Head.SET: SET_KEY_AF,
}

#: A head this much shallower than it is wide is a button, when no standard's
#: outline says which it is.
_BUTTON_RATIO = 0.45

#: A head drawn within this fraction of a standard's diameter and height is that
#: standard's head: models draw the maxima, or near them.
_OUTLINE_FIT = 0.12

#: A head is at least this many times as wide as its thread: ISO 7379's over its
#: shoulder, 13 over 8, is the narrowest (see :data:`_WIDE`), with room for a chamfer.
_HEAD_OVER_THREAD = 1.3

#: A point this far out, as a fraction of the screw's widest radius, is on its
#: head: any standard head is at least 1.5 times its thread (ISO 7379's over its
#: shoulder, 13 over 8, the narrowest), so the shank is never this far out.
_WIDE = 0.75

#: A countersunk head's cone, half its included angle, degrees: 82 to 120
#: degree heads (ASME B18.3's and ISO 10642's are 82 and 90), with room for a
#: model drawn loosely.
_COUNTERSINK_HALF_DEG = (35.0, 65.0)

#: A countersunk head's cone reaches the screw's widest radius within this
#: fraction of it, and runs at least this fraction of the way down to the shank.
_COUNTERSINK_RIM = 0.9
_COUNTERSINK_SPAN = 0.6

#: Surfaces a head's top is rounded by: a dome, a fillet.
_ROUNDED = {GeomType.TORUS, GeomType.SPHERE, GeomType.BSPLINE}

#: No fastener the tables hold is wider about its axis than this, mm: an M24 nut
#: is 41.6 across its corners. A wider part is no fastener's look-alike.
_FASTENER_WIDEST = 22.0

#: Nor has one more faces than this: bd_warehouse's M3x16 socket head screw, its
#: thread modelled, has 277. A printed part has hundreds, and is passed over
#: before the faces are read.
_FASTENER_FACES = 400

#: A look-alike nut's bore, as a fraction of its thread: from a thread drawn at its
#: minor diameter (an M3's 2.46 is 0.82 of it) to one drawn with clearance.
_NUT_BORE = (0.75, 1.15)

#: A look-alike nut is no thicker than this, as a fraction of its thread: ISO 7040's
#: nyloc is 1.33 of it at M3; a hex standoff, bored and the same across flats, is
#: longer.
_NUT_THICKEST = 1.5


@dataclass(frozen=True)
class ShapeReading:
    """What a fastener's solid shows.

    Attributes:
        axis: The fastener's axis, unsigned (which end is the head is the check's
            business), or None when no round face sets one.
        head: The head, from a drive the model shows (hex prism, hex pocket,
            cross, slot, square neck).
        head_guess: The head from its outline alone, when no drive is modelled.
        drive_af: Across flats of the drive the tool engages, mm: the outer hex
            of a hex head or nut, or the hex pocket of a keyed head.
        size: The thread size, from the drive or else the shank (screws) or
            the bore (nuts).
        size_from_drive: True when the drive settled the size, which a name's
            size does not outrank; a shank or bore measurement can be fooled by
            a thread drawn at its minor diameter, a drive can't.
        size_from_band: True when a hex's tolerance band alone gave the size,
            no exact drive or measured thread behind it: a name's size, or the
            bolt a nut runs on, outranks it (issue #50).
        head_standard: The standard whose head a keyed head's flat-topped
            outline fits (``ISO 7380-1``), when one alone does.
        head_unmatched: True when a flat-topped keyed head of a known size
            fits no standard's outline: its head is a guess from proportions.
        head_drawn: The head's diameter and height as drawn, mm, when its
            outline was read.
        outline_head: The head a countersink or a standard's outline shows,
            where the name gives another keyed head, which stands: a person
            should settle which is right (issue #81).
        bore_mm: A nut's or an insert's bore, the thinnest round facing its
            axis, as drawn, mm; None when it has none (issue #84).
        shank_mm: A screw's shank, the thinnest round on its axis facing out
            and narrower than its head, as drawn, mm; None when it has none (a
            tapping screw's cone, a thread modelled). A name's size it is no
            thread of is one the solid disagrees with (issue #117).
        length_mm: A screw's length as its standard gives one, as drawn, mm:
            under the head for a socket, button or hex head, overall for a
            countersunk head or a set screw; None for any other, a pan or a
            countersunk Phillips or Torx head looking alike to a drive (issue #94).
        cross_mm: A cross recess's span across its wings, as drawn, mm: its
            size (issue #115).
        torx_mm: A Torx recess's point to point, A, as drawn, mm: the size its
            ISO 10664 band names (issue #124).
        unread_recess: True when the solid shows a recess with walls that is no
            hex socket, Torx, cross or slot (a square's, a round or spline wall's
            facing the axis): no head is guessed for it.
    """

    axis: Vec | None = None
    head: Head | None = None
    head_guess: Head | None = None
    drive_af: float | None = None
    size: Size | None = None
    size_from_drive: bool = False
    head_standard: str | None = None
    head_unmatched: bool = False
    size_from_band: bool = False
    head_drawn: tuple[float, float] | None = None
    outline_head: Head | None = None
    bore_mm: float | None = None
    length_mm: float | None = None
    shank_mm: float | None = None
    cross_mm: float | None = None
    torx_mm: float | None = None
    unread_recess: bool = False


@dataclass(frozen=True)
class _Lobe:
    """A round wall of a recess: a cylinder along the axis, off it, the recess inside it."""

    angle_deg: float  # where its own axis lies round the main one, 0..360
    offset: float  # its own axis's distance from the main one
    radius: float


@dataclass(frozen=True)
class _Flat:
    """A planar face parallel to the axis: its direction round the axis and offset."""

    angle_deg: float  # direction of the outward normal round the axis, 0..360
    distance: float  # from the axis to the face's plane
    outward: bool  # normal points away from the axis


@dataclass(frozen=True)
class _Wall:
    """A planar face facing the axis and near parallel to it: a recess's wall."""

    angle_deg: float  # direction of its normal round the axis, 0..360
    offset: float  # from the axis to its middle, across it
    along: float  # its middle along it, measured one way round the axis
    reach: float  # its farthest point along it from the axis


def read_shape(shape: Shape, kind: Kind, named: Head | None = None) -> ShapeReading:
    """Measure a fastener's solid; ``kind`` comes from its name.

    ``named`` is the head the name says. A shoulder screw's (ISO 7379) is the one
    only a name can tell, whose socket head looks like any other: its pocket then
    settles the size through ISO 7379's keys, and a shank drawn as the shoulder
    alone is sized by the shoulder (issue #40). Any keyed head the name gives
    outranks the outline's, as the pocket says only that a key goes in; where a
    countersink or a standard's outline shows another, ``outline_head`` says so
    (issue #81).
    """
    axis = _main_axis(shape)
    if axis is None:
        return ShapeReading()
    origin, direction = axis
    faces = list(shape.faces())
    rounds = _coaxial_rounds(faces, origin, direction)
    flats = _flats(faces, origin, direction)
    outer = [f for f in flats if f.outward]
    inner = [f for f in flats if not f.outward]
    hex_outer = _regular(outer, 6)
    head: Head | None = None
    drive_af: float | None = None
    if kind is not Kind.SCREW:  # a nut or an insert: its bore gives the size
        bores = [r for r, convex in rounds if not convex]
        size, settled, banded = _settle(_snap(bores), None, hex_outer)
        return ShapeReading(
            direction,
            None,
            None,
            hex_outer,
            size,
            settled,
            size_from_band=banded,
            bore_mm=2 * min(bores) if bores else None,
        )
    convex = [r for r, outside in rounds if outside]
    walls = _walls(faces, origin, direction)
    span = torx = None
    shank = _snap(convex)  # the thinnest
    shoulder = named is Head.SHOULDER
    pocket = _regular(inner, 6)
    profile = _Profile.of(shape, origin, direction)
    lobes, splined = _round_walls(faces, (origin, direction), profile.widest)
    outline = _Outline(None)
    if hex_outer is not None and (pocket is None or hex_outer > pocket):
        head, drive_af = Head.HEX, hex_outer
    elif _regular(outer, 4) is not None:
        head = Head.CARRIAGE  # a square neck: it holds itself
    elif pocket is not None:
        head, outline = _socket_head(faces, (origin, direction), convex, profile, shank, named)
        drive_af = pocket
    else:
        head, span, torx = _recess(walls, inner, lobes)
    # A recess a hex key fits no better (#115), its walls flat or round (#124).
    unread = head is None and (bool(walls) or bool(lobes) or splined)
    if head is None and not unread:
        outline = _keyed_head(faces, origin, direction, convex, profile, shank)
    if shoulder or outline.head is Head.SHOULDER:  # by its name, or by its outline
        shank = _shoulder_shank(convex, shank, outline.shoulder)
    guess = None if head is not None else outline.head
    size, settled, banded = _settle(shank, head, drive_af)
    kept = head or named  # the head the outline is held to: the drive's or the name's
    disputed = outline.evident and kept in _KEY_TABLES and not shoulder
    disputed = disputed and outline.head is not kept
    return ShapeReading(
        direction,
        head,
        guess,
        drive_af,
        size,
        # A key's size says the thread only through its head's table, which is in doubt.
        settled and not disputed,
        outline.standard if outline.head in (kept, guess) else None,
        outline.unmatched,
        size_from_band=banded,
        head_drawn=outline.drawn,
        outline_head=outline.head if disputed else None,
        length_mm=_length(profile, head),
        shank_mm=_shank(convex, profile, head),
        cross_mm=span,
        torx_mm=torx,
        unread_recess=unread,
    )


def _recess(
    walls: list[_Wall], inner: list[_Flat], lobes: list[_Lobe]
) -> tuple[Head | None, float | None, float | None]:
    """A drive recessed in a head that is no hex socket: (head, cross span, Torx A).

    A cross, read from its wings (issue #115); a slot; a Torx recess, read from its
    lobes (issue #124). None when it is none of them.
    """
    if (span := _cross_span(walls)) is not None:
        return Head.PHILLIPS, span, None
    if _is_slot(inner):
        return Head.SLOTTED, None, None
    if (torx := _torx_point(lobes)) is not None:
        return Head.TORX, None, torx
    return None, None, None


#: Heads whose standard's length is the screw's under them, and overall (issue #94).
_UNDER_HEAD = (Head.SOCKET, Head.BUTTON, Head.HEX)
_OVERALL = (Head.FLAT, Head.SET)


def _shank(convex: list[float], profile: _Profile, head: Head | None) -> float | None:
    """A screw's shank as drawn, mm: the thinnest round under its head (issue #117).

    A set screw has no head: its thread is all of it.
    """
    under = [r for r in convex if head is Head.SET or r < _WIDE * profile.widest]
    return 2 * min(under) if under else None


def _length(profile: _Profile, head: Head | None) -> float | None:
    """A screw's length as its head's standard measures it, as drawn: see ShapeReading."""
    if not profile.along or head not in (*_UNDER_HEAD, *_OVERALL):
        return None
    overall = max(profile.along) - min(profile.along)
    return overall if head in _OVERALL else overall - profile.head()[1]


def looks_like(shape: Shape) -> tuple[Kind, str] | None:
    """What a solid looks like, if it is plainly a fastener: (kind, what), else None.

    For a part named nothing a fastener is (``Part7``), which detection doesn't
    check (named parts only), so a model of unnamed screws doesn't pass without a
    word (issue #95). Only the plainest count: a screw is a head at one end of a
    shank of a standard size, with a hex socket its size's key goes into or a
    cross in the head; a nut is a hex its size's spanner fits, round a bore of
    that size, no thicker than a nut. A slot, a square or a hex head over a
    shank show on spacers, fittings and printed parts as readily, and don't
    count.
    """
    if _more_faces_than(shape, _FASTENER_FACES):
        return None
    axis = _main_axis(shape)
    if axis is None:
        return None
    origin, direction = axis
    profile = _Profile.of(shape, origin, direction)
    if profile.widest > _FASTENER_WIDEST:
        return None
    faces = list(shape.faces())
    rounds = _coaxial_rounds(faces, origin, direction)
    flats = _flats(faces, origin, direction)
    inner = [f for f in flats if not f.outward]
    screw = _screw_like(rounds, inner, _walls(faces, origin, direction), profile)
    if screw is not None:
        return Kind.SCREW, screw
    nut = _nut_like(rounds, [f for f in flats if f.outward], profile)
    return (Kind.NUT, nut) if nut is not None else None


def _screw_like(
    rounds: list[tuple[float, bool]], inner: list[_Flat], walls: list[_Wall], profile: _Profile
) -> str | None:
    """A screw its solid plainly shows, said in a few words; else None."""
    shank = _snap([r for r, convex in rounds if convex])
    if shank is None or wide_end(profile.along, profile.out) == 0:
        return None
    if shank.diameter_mm / 2 >= _WIDE * profile.widest:
        return None  # no head wider than the shank
    pocket = _regular(inner, 6)
    keys = {table[d] for table in _KEY_TABLES.values() if (d := shank.designation) in table}
    if pocket is not None and any(
        in_recess_band(pocket, key) or loosely_fits(pocket, key) for key in keys
    ):
        return f"{shank.designation} screw, a {round(pocket, 2):g} hex socket"
    if _cross_span(walls) is not None:
        return f"{shank.designation} screw, a cross in its head"
    return None


def _nut_like(
    rounds: list[tuple[float, bool]], outer: list[_Flat], profile: _Profile
) -> str | None:
    """A nut its solid plainly shows, said in a few words; else None."""
    hexagon = _regular(outer, 6)
    bores = [2 * r for r, convex in rounds if not convex]
    if hexagon is None or not bores:
        return None
    thick = max(profile.along) - min(profile.along)
    low, high = _NUT_BORE
    for designation, diameter in {**METRIC_SIZES, **IMPERIAL_SIZES}.items():
        fits = any(
            abs(af - hexagon) <= _SAME_DISTANCE or in_hex_band(hexagon, af)
            for af in standard_hex_afs(Size(designation, diameter))
        )
        bored = low * diameter <= min(bores) <= high * diameter
        if fits and bored and thick <= _NUT_THICKEST * diameter:
            return f"{designation} nut, {round(hexagon, 2):g} across flats"
    return None


def _more_faces_than(shape: Shape, most: int) -> bool:
    """Whether a solid has more than ``most`` faces, counted without reading one."""
    explorer = TopExp_Explorer(shape.wrapped, TopAbs_FACE)
    count = 0
    while explorer.More():
        count += 1
        if count > most:
            return True
        explorer.Next()
    return False


# ---------------------------------------------------------------------------
# The axis and the round faces on it.
# ---------------------------------------------------------------------------


def _main_axis(shape: Shape) -> tuple[Vec, Vec] | None:
    """(a point on it, its unit direction): the cylinders' axis with most area."""
    totals: list[tuple[float, Vec, Vec]] = []
    for face in shape.faces():
        if face.geom_type is not GeomType.CYLINDER or face.axis_of_rotation is None:
            continue
        axis = face.axis_of_rotation
        point, direction = _vec(axis.position), _unit(_vec(axis.direction))
        for index, (area, p, d) in enumerate(totals):
            if abs(_dot(d, direction)) > _PARALLEL and _off_axis(point, p, d) < _COAXIAL_MM:
                totals[index] = (area + face.area, p, d)
                break
        else:
            totals.append((face.area, point, direction))
    if not totals:
        return None
    _, point, direction = max(totals, key=lambda t: t[0])
    return point, direction


@dataclass(frozen=True)
class _Profile:
    """A solid's vertices measured about its axis: how far along it, how far out."""

    along: tuple[float, ...]
    out: tuple[float, ...]

    @classmethod
    def of(cls, shape: Shape, origin: Vec, direction: Vec) -> _Profile:
        points = [_vec(v) for v in shape.vertices()]
        along = tuple(_dot(_sub(p, origin), direction) for p in points)
        return cls(along, tuple(_off_axis(p, origin, direction) for p in points))

    @property
    def widest(self) -> float:
        return max(self.out, default=0.0)

    def head(self) -> tuple[float, float]:
        """(radius, height) of the head: the widest section, and how far it runs.

        From the head's end to the far side of its wide region: the underside
        of a socket or button head, chamfers and all, where the widest cylinder
        alone misses a chamfered head's edges and a domed head (ISO 7380-1 drawn
        as one revolved profile, as bd_warehouse draws it) has none (issue #81).
        """
        end = wide_end(self.along, self.out)
        wide = [a for a, r in zip(self.along, self.out, strict=True) if r > _WIDE * self.widest]
        if end == 0 or not wide:
            return self.widest, max(wide, default=0.0) - min(wide, default=0.0)
        top = max(self.along) if end > 0 else min(self.along)
        under = min(wide) if end > 0 else max(wide)
        return self.widest, abs(top - under)


def wide_end(along: tuple[float, ...], out: tuple[float, ...]) -> int:
    """Which end of a screw its head is at: +1 the far end along the axis, -1 the near.

    A screw's head is its widest section, so its end is the one the wide region
    reaches (issue #81), not the end with the larger flat face: a domed head's
    only flat may be a ring round its socket, smaller than a chamfered tip's
    end. ``along`` and ``out`` are the solid's points, how far along the axis
    and how far out from it. 0 when the wide region reaches both ends alike (a
    plain pin) or there are no points.
    """
    widest = max(out, default=0.0)
    wide = [a for a, r in zip(along, out, strict=True) if r > _WIDE * widest]
    if not wide:
        return 0
    below, above = min(wide) - min(along), max(along) - max(wide)
    if abs(below - above) <= _SAME_DISTANCE:
        return 0
    return 1 if above < below else -1


def _socket_head(
    faces: list[Face],
    axis: tuple[Vec, Vec],
    convex: list[float],
    profile: _Profile,
    shank: Size | None,
    named: Head | None,
) -> tuple[Head | None, _Outline]:
    """The head a hex socket is in, and its outline.

    None at all, a set screw's (issue #96). Else a keyed head the name gives, and
    failing that the outline's; a head is no set screw's, whatever the name says.
    """
    if _headless(profile):
        return Head.SET, _Outline(None)
    outline = _keyed_head(faces, *axis, convex, profile, shank)
    keyed = named in _KEY_TABLES and named is not Head.SET
    return (named if keyed else outline.head), outline


def _headless(profile: _Profile) -> bool:
    """No end wider than the thread: a set screw's, its socket in the thread (issue #96).

    Its widest region reaches both ends; or, a dog, cup or cone point narrowing
    its far end, its wide end is no wider than the half of it away from that end:
    any standard head is at least :data:`_HEAD_OVER_THREAD` times its thread, and
    reaches less than half the screw's length.
    """
    end = wide_end(profile.along, profile.out)
    if end == 0:
        return True
    middle = (min(profile.along) + max(profile.along)) / 2
    far = [
        out
        for along, out in zip(profile.along, profile.out, strict=True)
        if (along < middle if end > 0 else along > middle)
    ]
    return profile.widest < _HEAD_OVER_THREAD * max(far, default=0.0)


def _coaxial_rounds(faces: list[Face], origin: Vec, direction: Vec) -> list[tuple[float, bool]]:
    """(radius, convex) for every cylinder on the axis; convex is outside, not a bore."""
    found = []
    for face in faces:
        if face.geom_type is not GeomType.CYLINDER or face.axis_of_rotation is None:
            continue
        axis = face.axis_of_rotation
        if abs(_dot(_unit(_vec(axis.direction)), direction)) < _PARALLEL:
            continue
        if _off_axis(_vec(axis.position), origin, direction) > _COAXIAL_MM:
            continue
        radius = face.radius
        if radius is None:
            continue
        centre = _vec(face.center())
        normal = _vec(face.normal_at(face.center()))
        radial = _radial_from(centre, origin, direction)
        found.append((radius, _dot(normal, radial) > 0))
    return found


def _snap(radii: list[float]) -> Size | None:
    """The thinnest diameter, as a standard size if it sits on one."""
    if not radii:
        return None
    diameter = 2 * min(radii)
    table = {**METRIC_SIZES, **IMPERIAL_SIZES}
    designation, nominal = min(table.items(), key=lambda item: abs(item[1] - diameter))
    if abs(nominal - diameter) > SIZE_SNAP_MM:
        return None
    return Size(designation, nominal)


def _shoulder_shank(convex: list[float], shank: Size | None, shoulder: float | None) -> Size | None:
    """A shoulder screw's thread size, from its shank.

    The thinnest round, when the thread is drawn at a size; the shoulder's own
    ISO 7379 thread when the shoulder alone is drawn (issue #40), or when the
    thread is drawn at no size and the outline gave the shoulder (issue #48).
    """
    thread = _shoulder_thread(convex) or shank
    if thread is None and shoulder is not None:
        return Size.parse(SHOULDER_THREAD[shoulder])
    return thread


def _shoulder_thread(radii: list[float]) -> Size | None:
    """A shoulder screw drawn as its head and one shank: the shank is the shoulder.

    With the thread drawn too, the thinnest round is the thread and stands; with
    the shoulder alone (head and one diameter), its ISO 7379 thread is the size.
    """
    distinct = sorted({round(r, 3) for r in radii})
    if len(distinct) != 2:  # noqa: PLR2004  (the head, and the shoulder alone)
        return None
    diameter = 2 * distinct[0]
    for shoulder, thread in SHOULDER_THREAD.items():
        if abs(shoulder - diameter) <= SIZE_SNAP_MM:
            return Size.parse(thread)
    return None


def _settle(
    measured: Size | None, head: Head | None, drive_af: float | None
) -> tuple[Size | None, bool, bool]:
    """The size, whether a modelled drive settled it, and whether a band alone did.

    A drive's across-flats names its sizes through the standard tables (a hex
    or nut through ISO 4032/4017, anywhere in the standard's band below its
    size, so an M8 nut drawn at 12.8 is still M8; a keyed head through its key
    table). One size: that's it. Several (an ISO 4762 14 mm key fits M16 and
    M18): the measured diameter picks between them, or nothing does. None: the
    measurement stands alone. A band is weaker than an exact size: it settles
    the size only when the bore or shank gives none, or agrees, so an M8 nut
    drawn 12.6 across flats (in 5/16's band for 1/2 in) on an M8 bore stays M8;
    and a size from a band alone is no more than a guess, which a name or a
    nut's bolt outranks (issue #50). A socket is drawn from its key up to its
    standard's most, which is its key's as surely as the key's own size (an ISO
    7380-1 M5's 3.08 is its 3 mm key's), and a little past that, drawn loosely,
    the key's as a band is a nut's: a guess (issue #82). Unlike a nut's bore, a
    shank thinner than every size its socket allows is no rival to it: a thread
    drawn at its minor diameter (an M3's 2.46 is M2.5's 2.5 within the snap).
    """
    if drive_af is None:
        return measured, False, False
    hexagon = head in (None, Head.HEX)
    table = HEX_AF if hexagon else _KEY_TABLES.get(head, {})
    exact = [d for d, af in table.items() if abs(af - drive_af) < _SAME_DISTANCE]
    if not exact and not hexagon:  # drawn above its key: 4.0 is the 4 mm key's, not 5/32's
        exact = [d for d, af in table.items() if in_recess_band(drive_af, af)]
    banded = [
        d
        for d, af in table.items()
        if (in_hex_band(drive_af, af) if hexagon else loosely_fits(drive_af, af))
    ]
    candidates = exact or banded
    if not candidates:
        return measured, False, False
    if measured is not None and measured.designation in candidates:
        return measured, True, False
    thinner = not hexagon and all(
        measured is not None and measured.diameter_mm < Size.parse(d).diameter_mm
        for d in candidates
    )
    if measured is not None and not exact and not thinner:
        return measured, False, False
    if len(candidates) == 1:
        return Size.parse(candidates[0]), bool(exact), not exact
    return None, False, False


# ---------------------------------------------------------------------------
# Flats: hexagons, squares, crosses, slots.
# ---------------------------------------------------------------------------


def _flats(faces: list[Face], origin: Vec, direction: Vec) -> list[_Flat]:
    x_dir = _any_perpendicular(direction)
    y_dir = _cross(direction, x_dir)
    flats = []
    for face in faces:
        if face.geom_type is not GeomType.PLANE:
            continue
        centre = _vec(face.center())
        normal = _unit(_vec(face.normal_at(face.center())))
        if abs(_dot(normal, direction)) > _PERPENDICULAR:
            continue
        signed = _dot(_sub(centre, origin), normal)  # >0: the normal points away
        angle = math.degrees(math.atan2(_dot(normal, y_dir), _dot(normal, x_dir))) % 360
        flats.append(_Flat(angle, abs(signed), signed > 0))
    return flats


def _regular(flats: list[_Flat], sides: int) -> float | None:
    """Across flats of a regular ``sides``-gon round the axis, or None.

    Looks for ``sides`` distinct directions, evenly spaced, all at one distance:
    a hexagon's six faces, or a square's four. The face pieces of other
    features at other distances don't disturb it.
    """
    for anchor in flats:
        ring = [f for f in flats if abs(f.distance - anchor.distance) <= _SAME_DISTANCE]
        angles = _distinct_angles([f.angle_deg for f in ring])
        if len(angles) != sides:
            continue
        step = 360.0 / sides
        if all(
            _angle_gap(a, angles[0]) % step < _SAME_ANGLE_DEG
            or step - _angle_gap(a, angles[0]) % step < _SAME_ANGLE_DEG
            for a in angles
        ):
            return 2 * anchor.distance
    return None


def _walls(faces: list[Face], origin: Vec, direction: Vec) -> list[_Wall]:
    """Every recess wall: a planar face facing the axis, leaning off it by a taper at most."""
    x_dir = _any_perpendicular(direction)
    y_dir = _cross(direction, x_dir)
    most = math.sin(math.radians(_WALL_TAPER_DEG))
    found = []
    for face in faces:
        if face.geom_type is not GeomType.PLANE:
            continue
        normal = _unit(_vec(face.normal_at(face.center())))
        axial = _dot(normal, direction)
        if abs(axial) > most:
            continue
        across = _unit(
            _sub(normal, (direction[0] * axial, direction[1] * axial, direction[2] * axial))
        )
        middle = _sub(_vec(face.center()), origin)
        signed = _dot(middle, across)
        if signed >= 0:
            continue  # facing away from the axis: an outside
        along = _cross(direction, across)  # the wall's own way, which flips with its facing
        reach = max(abs(_dot(_sub(_vec(v), origin), along)) for v in face.vertices())
        angle = math.degrees(math.atan2(_dot(across, y_dir), _dot(across, x_dir))) % 360
        found.append(_Wall(angle, -signed, _dot(middle, along), reach))
    return found


def _round_walls(
    faces: list[Face], axis: tuple[Vec, Vec], widest: float
) -> tuple[list[_Lobe], bool]:
    """A recess's round walls along the axis: its cylinders, and whether any spline.

    A cylinder whose own axis lies along the main one and off it, the recess inside
    it, and inside the part's widest radius, is a round wall of a recess: a Torx
    recess's lobe, a pin hole. Not the flute between two lobes, outside it, nor a
    scallop in a knurled rim, whose middle is past the rim. A spline face along the
    axis, looking at it where it is, is a round wall drawn some other way (``True``).
    """
    origin, direction = axis
    x_dir = _any_perpendicular(direction)
    y_dir = _cross(direction, x_dir)
    most = math.sin(math.radians(_WALL_TAPER_DEG))
    lobes, splined = [], False
    for face in faces:
        kind = face.geom_type
        if kind in _SPLINES:
            point = _vec(face.position_at(0.5, 0.5))
            normal = _unit(_vec(face.normal_at(0.5, 0.5)))
            looks = _dot(normal, _radial_from(point, origin, direction)) < 0
            splined = splined or (abs(_dot(normal, direction)) <= most and looks)
            continue
        own_axis = face.axis_of_rotation if kind is GeomType.CYLINDER else None
        if own_axis is None or abs(_dot(_unit(_vec(own_axis.direction)), direction)) < _PARALLEL:
            continue
        own = _radial_from(_vec(own_axis.position), origin, direction)
        offset = math.sqrt(_dot(own, own))
        # Read through the surface: build123d's radius is None for a trimmed cylinder,
        # as a boolean leaves a lobe cut into a head.
        radius = BRepAdaptor_Surface(face.wrapped).Cylinder().Radius()
        if offset <= _COAXIAL_MM or offset + radius > widest:
            continue  # on the axis (a bore, a counterbore), or in the part's rim
        point = _vec(face.position_at(0.5, 0.5))
        out = _sub(_radial_from(point, origin, direction), own)  # from its own axis
        if _dot(_vec(face.normal_at(0.5, 0.5)), out) >= 0:
            continue  # the part inside it: a flute, a boss
        angle = math.degrees(math.atan2(_dot(own, y_dir), _dot(own, x_dir))) % 360
        lobes.append(_Lobe(angle, offset, radius))
    return lobes, splined


def _torx_point(lobes: list[_Lobe]) -> float | None:
    """A Torx recess's point to point, A, if its six lobes are there; else None.

    Six round walls, the recess inside them, of one radius, their axes at one offset
    from the main one and 60 degrees apart: A is twice the offset and the radius.
    The flutes between them, and a core drawn round the axis, don't matter.
    """
    for anchor in lobes:
        ring = [
            lobe
            for lobe in lobes
            if abs(lobe.offset - anchor.offset) <= _SAME_DISTANCE
            and abs(lobe.radius - anchor.radius) <= _SAME_DISTANCE
        ]
        angles = _distinct_angles([lobe.angle_deg for lobe in ring])
        if len(angles) == 6 and all(  # noqa: PLR2004  (a Torx recess's six lobes)
            min(_angle_gap(a, angles[0]) % 60, 60 - _angle_gap(a, angles[0]) % 60) < _SAME_ANGLE_DEG
            for a in angles
        ):
            return 2 * (anchor.offset + anchor.radius)
    return None


def _cross_span(walls: list[_Wall]) -> float | None:
    """A cross recess's span across its wings, or None when the walls make no cross.

    Four wings at right angles round the axis (issue #115): a wing is a pair of
    walls facing each other at one offset, their middles out along the wing past
    that offset, so the walls of a square socket or a slot, centred on the axis,
    make none, and nor do V faces between wings, which face each other across it.
    Whatever closes the wings' ends or fills between them is not a wall here. The
    span is the farthest the wings' walls reach, one way and the other, added.
    """
    for anchor in walls:
        spans = []
        for turn in (0.0, 90.0):
            line = (anchor.angle_deg + turn) % 180
            on = [
                w
                for w in walls
                if _same_line(w.angle_deg, line) and abs(w.offset - anchor.offset) <= _CROSS_WALLS
            ]
            reaches = [_wing(on, line, side) for side in (1, -1)]
            if None in reaches:
                break
            spans.append(sum(r for r in reaches if r is not None))
        else:
            return max(spans)
    return None


def _same_line(angle: float, line: float) -> bool:
    """Whether a direction round the axis lies on a line through it, either way."""
    gap = _angle_gap(angle % 180, line)
    return gap < _SAME_ANGLE_DEG or gap > 180 - _SAME_ANGLE_DEG


def _wing(on: list[_Wall], line: float, side: int) -> float | None:
    """How far out a wing reaches on one side of the axis, or None if there is none.

    ``on`` are walls facing along ``line``, one way or the other; a wing on
    ``side`` has walls facing both ways out on that side, past their offset.
    """
    facing: dict[int, list[_Wall]] = {}
    for wall in on:
        sign = 1 if _angle_gap(wall.angle_deg, line) < 90 else -1  # noqa: PLR2004
        if wall.along * sign * side > wall.offset:  # "along" flips with the facing
            facing.setdefault(sign, []).append(wall)
    if len(facing) != 2:  # noqa: PLR2004  (a wall facing each way)
        return None
    return max(wall.reach for walls in facing.values() for wall in walls)


def _is_slot(inner: list[_Flat]) -> bool:
    """One slot: its narrowest pair of walls faces one way only."""
    by_axis = _offsets_by_axis(inner)
    if not by_axis:
        return False
    narrowest = min(min(offsets) for offsets in by_axis.values())
    holders = [
        angle for angle, offsets in by_axis.items() if min(offsets) - narrowest < _SAME_DISTANCE
    ]
    return len(holders) == 1


def _offsets_by_axis(inner: list[_Flat]) -> dict[float, list[float]]:
    """Inward flats grouped by the line their normal lies on (0..180), with offsets."""
    groups: dict[float, list[float]] = {}
    for flat in inner:
        line = flat.angle_deg % 180
        key = next((k for k in groups if _angle_gap(k, line) < _SAME_ANGLE_DEG), line)
        offsets = groups.setdefault(key, [])
        if all(abs(o - flat.distance) > _SAME_DISTANCE for o in offsets):
            offsets.append(flat.distance)
    return {k: sorted(v) for k, v in groups.items()}


# ---------------------------------------------------------------------------
# A keyed head's outline: socket, button or flat.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Outline:
    """What a keyed head's outline says: the head, and how sure that is."""

    head: Head | None
    standard: str | None = None
    unmatched: bool = False
    drawn: tuple[float, float] | None = None
    shoulder: float | None = None

    @property
    def evident(self) -> bool:
        """Shown plainly, a countersink or a standard's outline; not proportions alone."""
        return self.head is Head.FLAT or self.standard is not None


def _keyed_head(
    faces: list[Face],
    origin: Vec,
    direction: Vec,
    convex: list[float],
    profile: _Profile,
    shank: Size | None,
) -> _Outline:
    """Countersunk if the head is a countersink; else the standard head its outline fits.

    A flat-topped head is compared with each standard's head for the shank's
    size: a button head drawn flat, 9.5 across and 2.75 high for M5, is ISO
    7380-1's, not ISO 4762's 8.5 by 5 (issue #31). A shoulder screw's head goes
    with its shoulder, the widest round under the head, not its thread: 13 by
    5.5 over an 8 mm shoulder is ISO 7379's (issue #48). Failing that, and for a
    rounded top, the proportions decide: a head much shallower than it is wide
    is a button.
    """
    if _countersunk(faces, origin, direction, convex, profile.widest):
        return _Outline(Head.FLAT)
    rounded = any(face.geom_type in _ROUNDED for face in faces)
    radius, height = profile.head()
    drawn = (2 * radius, height)
    shoulder = _shoulder_under(convex, radius)
    flat = not rounded and radius > 0
    compared = flat and (shank is not None or shoulder is not None)
    if flat:
        fits = [
            head
            for head, table in HEAD_OUTLINE.items()
            if shank is not None
            and (standard := table.get(shank.designation))
            and _fits(drawn, standard)
        ]
        if shoulder is not None and _fits(drawn, SHOULDER_OUTLINE[shoulder]):
            fits.append(Head.SHOULDER)
        if len(fits) == 1:
            metric = fits[0] is Head.SHOULDER or (shank is not None and shank.is_metric)
            under = shoulder if fits[0] is Head.SHOULDER else None
            return _Outline(fits[0], HEAD_STANDARD[fits[0], metric], drawn=drawn, shoulder=under)
    low = radius > 0 and height / (2 * radius) < _BUTTON_RATIO
    return _Outline(Head.BUTTON if low else Head.SOCKET, unmatched=compared, drawn=drawn)


def _shoulder_under(convex: list[float], head_radius: float) -> float | None:
    """The widest round under a head, as an ISO 7379 shoulder's diameter; else None."""
    under = [r for r in convex if r < head_radius - SIZE_SNAP_MM]
    if not under:
        return None
    diameter = 2 * max(under)
    return next((s for s in SHOULDER_OUTLINE if abs(s - diameter) <= SIZE_SNAP_MM), None)


def _fits(measured: tuple[float, float], drawn: tuple[float, float]) -> bool:
    """A head's (diameter, height) within :data:`_OUTLINE_FIT` of a standard's."""
    return all(abs(m - d) <= _OUTLINE_FIT * d for m, d in zip(measured, drawn, strict=True))


def _countersunk(
    faces: list[Face], origin: Vec, direction: Vec, convex: list[float], widest: float
) -> bool:
    """Whether a cone on the screw is a countersunk head (issue #81).

    The head's cone runs under the head from the shank out to the screw's
    widest radius, at 82 to 120 degrees, facing out. A chamfer on a head's edge
    is a cone too, as are a socket's countersunk mouth and drilled point and a
    chamfered tip, and each fails one of those: a chamfer spans a sliver of the
    way, a socket's cones face in, a tip's stops at the shank.
    """
    shank = min(convex, default=0.0)
    for face in faces:
        if face.geom_type is not GeomType.CONE or face.axis_of_rotation is None:
            continue
        axis = face.axis_of_rotation
        if abs(_dot(_unit(_vec(axis.direction)), direction)) < _PARALLEL:
            continue
        if _off_axis(_vec(axis.position), origin, direction) > _COAXIAL_MM:
            continue
        # Its half angle from its ends: how far out it runs against how far along.
        points = [_vec(v) for v in face.vertices()]
        radii = [_off_axis(p, origin, direction) for p in points]
        heights = [_dot(_sub(p, origin), direction) for p in points]
        inner, outer = min(radii, default=0.0), max(radii, default=0.0)
        rise = max(heights, default=0.0) - min(heights, default=0.0)
        low, high = _COUNTERSINK_HALF_DEG
        if not low <= math.degrees(math.atan2(outer - inner, rise)) <= high:
            continue
        centre = _vec(face.center())
        if _dot(_vec(face.normal_at(face.center())), _radial_from(centre, origin, direction)) <= 0:
            continue  # facing in: a socket's mouth or point
        if outer >= _COUNTERSINK_RIM * widest and widest - inner >= _COUNTERSINK_SPAN * (
            widest - shank
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Small vector helpers.
# ---------------------------------------------------------------------------


def _vec(v: Vector | Vertex) -> Vec:
    return (float(v.X), float(v.Y), float(v.Z))


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a: Vec) -> Vec:
    length = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / length, a[1] / length, a[2] / length)


def _radial_from(point: Vec, origin: Vec, direction: Vec) -> Vec:
    offset = _sub(point, origin)
    along = _dot(offset, direction)
    return _sub(offset, (direction[0] * along, direction[1] * along, direction[2] * along))


def _off_axis(point: Vec, origin: Vec, direction: Vec) -> float:
    radial = _radial_from(point, origin, direction)
    return math.sqrt(_dot(radial, radial))


def _any_perpendicular(direction: Vec) -> Vec:
    helper = (1.0, 0.0, 0.0) if abs(direction[0]) < 0.9 else (0.0, 1.0, 0.0)  # noqa: PLR2004
    return _unit(_cross(direction, helper))


def _distinct_angles(angles: list[float]) -> list[float]:
    distinct: list[float] = []
    for angle in sorted(angles):
        if all(_angle_gap(angle, d) >= _SAME_ANGLE_DEG for d in distinct):
            distinct.append(angle)
    return distinct


def _angle_gap(a: float, b: float) -> float:
    """The unsigned gap between two angles, 0..180 degrees."""
    gap = abs(a - b) % 360
    return min(gap, 360 - gap)
