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
shows; the head's outline alone (a plain cylinder, a dome, a cone) is only
``head_guess``, worth using when the name says nothing.

Flats are found as planar faces parallel to the axis. A face whose outward
normal points away from the axis is the outside of a prism (a hex head, a nut, a
square neck); one pointing toward it is the wall of a pocket or recess (a hex
socket, the arms of a cross, a slot). Distances are measured from the axis to
each face's plane, so a face split by other features still counts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from build123d import GeomType

from wrenchroom.fasteners import (
    BUTTON_KEY_AF,
    FLAT_KEY_AF,
    HEX_AF,
    IMPERIAL_SIZES,
    METRIC_SIZES,
    SOCKET_KEY_AF,
    Head,
    Kind,
    Size,
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

#: Flats at the same distance from the axis, within this, mm, belong to one prism.
_SAME_DISTANCE = 0.02

#: Two flat directions are the same within this many degrees.
_SAME_ANGLE_DEG = 1.0

#: A coaxial face's axis may sit this far off the part's axis, mm.
_COAXIAL_MM = 0.05

#: Which table names the sizes a keyed head's socket fits.
_KEY_TABLES: dict[Head, dict[str, float]] = {
    Head.SOCKET: SOCKET_KEY_AF,
    Head.BUTTON: BUTTON_KEY_AF,
    Head.FLAT: FLAT_KEY_AF,
}

#: A head this much shallower than it is wide, with a rounded top, is a button.
_BUTTON_RATIO = 0.45


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
    """

    axis: Vec | None = None
    head: Head | None = None
    head_guess: Head | None = None
    drive_af: float | None = None
    size: Size | None = None
    size_from_drive: bool = False


@dataclass(frozen=True)
class _Flat:
    """A planar face parallel to the axis: its direction round the axis and offset."""

    angle_deg: float  # direction of the outward normal round the axis, 0..360
    distance: float  # from the axis to the face's plane
    outward: bool  # normal points away from the axis


def read_shape(shape: Shape, kind: Kind) -> ShapeReading:
    """Measure a fastener's solid; ``kind`` comes from its name."""
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
    if kind is Kind.NUT:
        bore = _snap([r for r, convex in rounds if not convex])
        size, settled = _settle(bore, None, hex_outer)
        return ShapeReading(direction, None, None, hex_outer, size, settled)
    shank = _snap([r for r, convex in rounds if convex])  # the thinnest
    pocket = _regular(inner, 6)
    if hex_outer is not None and (pocket is None or hex_outer > pocket):
        head, drive_af = Head.HEX, hex_outer
    elif _regular(outer, 4) is not None:
        head = Head.CARRIAGE  # a square neck: it holds itself
    elif pocket is not None:
        head, drive_af = _keyed_head(faces, origin, direction), pocket
    elif _is_cross(inner):
        head = Head.PHILLIPS
    elif _is_slot(inner):
        head = Head.SLOTTED
    guess = None if head is not None else _keyed_head(faces, origin, direction)
    size, settled = _settle(shank, head, drive_af)
    return ShapeReading(direction, head, guess, drive_af, size, settled)


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


def _settle(
    measured: Size | None, head: Head | None, drive_af: float | None
) -> tuple[Size | None, bool]:
    """The size, letting a modelled drive outrank the shank or bore; and whether it did.

    A drive's across-flats names its sizes through the standard tables (a hex
    or nut through ISO 4032/4017, a keyed head through its key table). One
    size: that's it. Several (an ISO 4762 14 mm key fits M16 and M18): the
    measured diameter picks between them, or nothing does. None: the
    measurement stands alone.
    """
    if drive_af is None:
        return measured, False
    table = HEX_AF if head in (None, Head.HEX) else _KEY_TABLES.get(head, {})
    candidates = [d for d, af in table.items() if abs(af - drive_af) < _SAME_DISTANCE]
    if not candidates:
        return measured, False
    if measured is not None and measured.designation in candidates:
        return measured, True
    if len(candidates) == 1:
        return Size.parse(candidates[0]), True
    return None, False


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


def _is_cross(inner: list[_Flat]) -> bool:
    """Two slots crossing at right angles: both directions show the same two offsets."""
    by_axis = _offsets_by_axis(inner)
    if len(by_axis) != 2:  # noqa: PLR2004  (a cross has two arms)
        return False
    (a_angle, a_offsets), (b_angle, b_offsets) = by_axis.items()
    square = abs(_angle_gap(a_angle, b_angle) - 90) < _SAME_ANGLE_DEG
    return square and len(a_offsets) == 2 and _same_offsets(a_offsets, b_offsets)  # noqa: PLR2004


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


def _same_offsets(a: list[float], b: list[float]) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= _SAME_DISTANCE for x, y in zip(a, b, strict=True))


# ---------------------------------------------------------------------------
# A keyed head's outline: socket, button or flat.
# ---------------------------------------------------------------------------


def _keyed_head(faces: list[Face], origin: Vec, direction: Vec) -> Head:
    """Countersunk if the head is a cone, button if low and rounded, else socket."""
    kinds = {face.geom_type for face in faces}
    if GeomType.CONE in kinds:
        return Head.FLAT
    rounded = bool(kinds & {GeomType.TORUS, GeomType.SPHERE, GeomType.BSPLINE})
    radius, height = _head_size(faces, origin, direction)
    if rounded and radius > 0 and height / (2 * radius) < _BUTTON_RATIO:
        return Head.BUTTON
    return Head.SOCKET


def _head_size(faces: list[Face], origin: Vec, direction: Vec) -> tuple[float, float]:
    """(radius, axial height) of the widest coaxial cylinder: the head's band."""
    best = (0.0, 0.0)
    for face in faces:
        if face.geom_type is not GeomType.CYLINDER or face.axis_of_rotation is None:
            continue
        if abs(_dot(_unit(_vec(face.axis_of_rotation.direction)), direction)) < _PARALLEL:
            continue
        radius = face.radius
        if radius is None or radius <= best[0]:
            continue
        heights = [_dot(_sub(_vec(v), origin), direction) for v in face.vertices()]
        best = (radius, max(heights) - min(heights) if heights else 0.0)
    return best


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
