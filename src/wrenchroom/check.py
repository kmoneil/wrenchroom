"""The check loop: resolve each fastener's geometry, try its tools, record why.

For each fastener: build its scene (everything except itself, its mates and the
ignored parts), resolve where the tool engages (seat and axis), pick the tools its
head and size call for, and run their attempts lazily until one turns. Nothing is
skipped silently: a fastener that can't be resolved or has no tool in the kit is
`not-covered` with the reason in the report.

M1 scope: verdicts `turns`, `blocked`, `not-covered`, plus `held` for the
self-holding carriage head. Pairs, extraction and states arrive with M2 and slot
into this loop rather than around it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING

from build123d import GeomType

from wrenchroom.assembly import Assembly, Part
from wrenchroom.config import Config
from wrenchroom.engine import Scene
from wrenchroom.fasteners import (
    AUTO,
    PHILLIPS_NUMBER,
    Fastener,
    Head,
    Kind,
    hex_key_af,
    spanner_af,
)
from wrenchroom.report import FastenerResult, Report, Verdict
from wrenchroom.tools.drivers import SHAFT_RADIUS, driver_attempt
from wrenchroom.tools.hex_keys import ISO_2936, hex_key_attempts
from wrenchroom.tools.sockets import socket_attempts, socket_for
from wrenchroom.tools.spanners import ring_attempts, spanner_for
from wrenchroom.tools.sweep import DEFAULT_STEP_DEG, Attempt, Mount, axial_cylinder

if TYPE_CHECKING:
    from collections.abc import Iterator

    from build123d import Axis

#: The one kit M1 ships. imperial-home and full arrive with M6.
KITS = ("metric-home",)

Vec = tuple[float, float, float]


class NotCovered(Exception):  # noqa: N818  (it is a verdict carrier, not an error suffix)
    """Raised inside the loop when a fastener can't be understood; becomes the verdict."""


def check(
    assembly: Assembly,
    config: Config | None = None,
    *,
    kit: str = "metric-home",
    step_deg: float = DEFAULT_STEP_DEG,
    model: str = "",
    only: str | None = None,
) -> Report:
    """Check every fastener the config names against the assembly.

    Args:
        assembly: The parts in their assembled positions.
        config: The sidecar; ``None`` means no fasteners, which still yields a
            valid (empty, passing) report.
        kit: Tool kit name; only ``metric-home`` exists until M6.
        step_deg: Swing sampling step, degrees.
        model: The model's name for the report header.
        only: A glob narrowing which fasteners are checked, as ``--only``.

    Raises:
        ValueError: On a kit that doesn't exist (a typo, not a model problem).
    """
    if kit not in KITS:
        msg = f"unknown kit {kit!r}; available: {', '.join(KITS)}"
        raise ValueError(msg)
    config = config or Config()
    matches = config.apply(assembly)
    fasteners = sorted(matches.fasteners, key=lambda f: f.name)
    if only is not None:
        fasteners = [f for f in fasteners if fnmatchcase(f.name, only)]
    results = tuple(_check_one(assembly, config, fastener, step_deg) for fastener in fasteners)
    return Report(
        model=model,
        kit=kit,
        results=results,
        unmatched_rules=tuple(rule.parts for rule in matches.unmatched_rules),
        unmatched_ignores=matches.unmatched_ignores,
    )


def _check_one(
    assembly: Assembly, config: Config, fastener: Fastener, step_deg: float
) -> FastenerResult:
    part = assembly[fastener.name]
    scene = _scene_for(assembly, config, fastener)
    try:
        mount, geometry = _resolve(part, fastener, scene)
    except NotCovered as exc:
        return FastenerResult(fastener, Verdict.NOT_COVERED, reason=str(exc))
    if fastener.self_holding:
        return FastenerResult(
            fastener,
            Verdict.HELD,
            how="holds itself",
            axis=mount.axis,
            seat=mount.seat,
        )
    try:
        attempts_iter = _attempts_for(fastener, mount, geometry, scene, step_deg)
    except NotCovered as exc:
        return FastenerResult(
            fastener, Verdict.NOT_COVERED, reason=str(exc), axis=mount.axis, seat=mount.seat
        )
    tried: list[Attempt] = []
    for attempt in attempts_iter:
        tried.append(attempt)
        if attempt.turns:
            return FastenerResult(
                fastener,
                Verdict.TURNS,
                tool=attempt.tool,
                how=attempt.way,
                swing_deg=attempt.swing_deg,
                blockers=attempt.blockers,
                attempts=tuple(tried),
                axis=mount.axis,
                seat=mount.seat,
            )
    blockers: list[str] = []
    for attempt in tried:
        for name in attempt.blockers:
            if name not in blockers:
                blockers.append(name)
    return FastenerResult(
        fastener,
        Verdict.BLOCKED,
        tool=tried[0].tool if tried else None,
        swing_deg=max((a.swing_deg for a in tried), default=0.0),
        blockers=tuple(blockers),
        attempts=tuple(tried),
        axis=mount.axis,
        seat=mount.seat,
    )


def _scene_for(assembly: Assembly, config: Config, fastener: Fastener) -> Scene:
    excluded = {fastener.name, *fastener.mates}
    parts = (
        part for part in assembly if part.name not in excluded and not config.is_ignored(part.name)
    )
    return Scene(parts)


# ---------------------------------------------------------------------------
# Geometry resolution: seat, axis, and the hex sizes the spanner path needs.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Geometry:
    """What resolution learned about the part beyond the mount."""

    hex_height: float
    circumradius: float


def _resolve(part: Part, fastener: Fastener, scene: Scene) -> tuple[Mount, _Geometry]:
    direction = _axis_direction(part, fastener)
    origin, vertices = _axis_frame(part, direction)
    projections = [_dot(_sub(v, origin), direction) for v in vertices]
    radials = [_radial(_sub(v, origin), direction) for v in vertices]
    if fastener.axis == AUTO:
        direction, projections = _orient(
            part, fastener, scene, origin, direction, projections, radials
        )
    top = max(projections)
    seat = _add(origin, _scale(direction, top))
    hex_height = _hex_height(projections, radials, top)
    return (
        Mount(seat=seat, axis=direction),
        _Geometry(hex_height=hex_height, circumradius=max(radials, default=0.0)),
    )


def _largest_cylinder_axis(part: Part) -> Axis | None:
    cylinders = part.shape.faces().filter_by(GeomType.CYLINDER)
    if not cylinders:
        return None
    return max(cylinders, key=lambda f: f.area).axis_of_rotation


def _axis_direction(part: Part, fastener: Fastener) -> Vec:
    if isinstance(fastener.axis, tuple):
        return fastener.axis
    axis = _largest_cylinder_axis(part)
    if axis is None:
        raise NotCovered("axis is auto but the part has no cylindrical face")
    return tuple(axis.direction)  # type: ignore[return-value]


def _axis_frame(part: Part, direction: Vec) -> tuple[Vec, list[Vec]]:
    axis = _largest_cylinder_axis(part)
    if axis is not None:
        origin: Vec = tuple(axis.position)  # type: ignore[assignment]
    else:
        center = part.shape.bounding_box().center()
        origin = (center.X, center.Y, center.Z)
    vertices = [tuple(v) for v in part.shape.vertices()]
    if not vertices:
        raise NotCovered("the part has no vertices to measure")
    return origin, vertices  # type: ignore[return-value]


def _orient(
    part: Part,
    fastener: Fastener,
    scene: Scene,
    origin: Vec,
    direction: Vec,
    projections: list[float],
    radials: list[float],
) -> tuple[Vec, list[float]]:
    """Point the axis out of the joint: out of a head, out of a nut's free face."""
    if fastener.kind is Kind.SCREW:
        flipped = _head_is_at_bottom(part, direction)
    else:
        flipped = _free_face_is_at_bottom(scene, origin, direction, projections, radials)
    if flipped:
        return _neg(direction), [-p for p in projections]
    return direction, projections


def _head_is_at_bottom(part: Part, direction: Vec) -> bool:
    """A screw's head end is the extreme planar face with the larger area."""
    planes = [
        face
        for face in part.shape.faces().filter_by(GeomType.PLANE)
        if abs(_dot(tuple(face.normal_at(face.center())), direction)) > _AXIAL
    ]
    if len(planes) < 2:  # noqa: PLR2004  (two ends make a comparison)
        raise NotCovered("cannot tell the head end: no planar face at each end")
    by_height = sorted(planes, key=lambda f: _dot(tuple(f.center()), direction))
    bottom, top = by_height[0], by_height[-1]
    if bottom.area == top.area:
        raise NotCovered("cannot tell the head end: both ends look alike")
    return bottom.area > top.area


def _free_face_is_at_bottom(
    scene: Scene,
    origin: Vec,
    direction: Vec,
    projections: list[float],
    radials: list[float],
) -> bool:
    """A nut's free face is the end no other part sits against."""
    radius = max(radials) * 0.95
    top, bottom = max(projections), min(projections)
    plane_top = Mount(seat=_add(origin, _scale(direction, top)), axis=direction)
    plane_bottom = Mount(seat=_add(origin, _scale(direction, bottom)), axis=_neg(direction))
    top_free = scene.clear(plane_top.place(axial_cylinder(radius, 0.1, 1.1)))
    bottom_free = scene.clear(plane_bottom.place(axial_cylinder(radius, 0.1, 1.1)))
    if top_free == bottom_free:
        raise NotCovered(
            "cannot tell the nut's free face: both ends are " + ("clear" if top_free else "covered")
        )
    return bottom_free


def _hex_height(projections: list[float], radials: list[float], top: float) -> float:
    """The axial extent of the widest region: a nut's body, a hex head's depth."""
    widest = max(radials, default=0.0)
    heights = [p for p, r in zip(projections, radials, strict=True) if r > 0.75 * widest]
    if not heights:
        return 0.0
    return min(top - min(heights), top - min(projections))


# ---------------------------------------------------------------------------
# Tool selection.
# ---------------------------------------------------------------------------

#: How parallel a face normal must be to the axis to count as an end face.
_AXIAL = 0.99

_KEYED_HEADS = (Head.SOCKET, Head.BUTTON, Head.FLAT)


def _attempts_for(
    fastener: Fastener,
    mount: Mount,
    geometry: _Geometry,
    scene: Scene,
    step_deg: float,
) -> Iterator[Attempt]:
    if fastener.tool is not None:
        return _forced_attempts(fastener, mount, geometry, scene, step_deg)
    if fastener.size is None:
        raise NotCovered("size unknown: name it in the sidecar")
    if not fastener.size.is_metric:
        raise NotCovered("imperial sizes need the imperial kit (M6)")
    if fastener.kind is Kind.NUT or fastener.head is Head.HEX:
        return _hex_flats_attempts(fastener, mount, geometry, scene, step_deg)
    if fastener.head in _KEYED_HEADS:
        return _keyed_attempts(fastener, mount, scene, step_deg)
    if fastener.head is Head.PHILLIPS:
        number = PHILLIPS_NUMBER.get(fastener.size.designation)
        if number is None:
            raise NotCovered(f"no Phillips number for {fastener.size.designation}")
        return iter(
            [driver_attempt(mount, scene, SHAFT_RADIUS[f"ph{number}"], f"driver-ph{number}")]
        )
    if fastener.head is Head.SLOTTED:
        return iter([driver_attempt(mount, scene, SHAFT_RADIUS["slotted"], "driver-slotted")])
    if fastener.head is Head.TORX:
        raise NotCovered("Torx keys arrive with the full kit (M6)")
    raise NotCovered("head unknown: name it in the sidecar")


def _keyed_attempts(
    fastener: Fastener, mount: Mount, scene: Scene, step_deg: float
) -> Iterator[Attempt]:
    if fastener.head is None or fastener.size is None:
        raise NotCovered("head or size unknown: name them in the sidecar")
    af = hex_key_af(fastener.head, fastener.size)
    if af is None or af not in ISO_2936:
        raise NotCovered(
            f"no standard key for a {fastener.size.designation} {fastener.head.value} head"
        )
    return hex_key_attempts(mount, ISO_2936[af], scene, step_deg)


def _hex_flats_attempts(
    fastener: Fastener,
    mount: Mount,
    geometry: _Geometry,
    scene: Scene,
    step_deg: float,
) -> Iterator[Attempt]:
    if fastener.size is None:
        raise NotCovered("size unknown: name it in the sidecar")
    af = spanner_af(fastener.size)
    if af is None:
        raise NotCovered(f"no across-flats for {fastener.size.designation}")
    if geometry.hex_height <= 0:
        raise NotCovered("could not measure the hex's height")
    yield from ring_attempts(mount, spanner_for(af), af, geometry.hex_height, scene, step_deg)
    if fastener.socket_allowed:
        yield from socket_attempts(mount, socket_for(af), af, scene, step_deg)


def _forced_attempts(
    fastener: Fastener,
    mount: Mount,
    geometry: _Geometry,
    scene: Scene,
    step_deg: float,
) -> Iterator[Attempt]:
    """A sidecar `tool:` name, e.g. hex-key-5, spanner-10, socket-13, driver-ph2."""
    name = fastener.tool or ""
    family, _, size_text = name.rpartition("-")
    if family == "hex-key":
        key = ISO_2936.get(_as_float(size_text, name))
        if key is None:
            raise NotCovered(f"no ISO 2936 key sized {size_text}")
        return hex_key_attempts(mount, key, scene, step_deg)
    if family == "spanner":
        af = _as_float(size_text, name)
        if geometry.hex_height <= 0:
            raise NotCovered("could not measure the hex's height")
        return ring_attempts(mount, spanner_for(af), af, geometry.hex_height, scene, step_deg)
    if family == "socket":
        af = _as_float(size_text, name)
        return socket_attempts(mount, socket_for(af), af, scene, step_deg)
    if family == "driver":
        radius = SHAFT_RADIUS.get(size_text)
        if radius is None:
            raise NotCovered(f"unknown driver {size_text!r}")
        return iter([driver_attempt(mount, scene, radius, name)])
    raise NotCovered(f"unknown tool {name!r}")


def _as_float(text: str, tool: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise NotCovered(f"unknown tool {tool!r}") from None


# ---------------------------------------------------------------------------
# Small vector helpers; tuples in, tuples out, no numpy needed at this size.
# ---------------------------------------------------------------------------


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def _neg(a: Vec) -> Vec:
    return (-a[0], -a[1], -a[2])


def _radial(offset: Vec, direction: Vec) -> float:
    along = _dot(offset, direction)
    return math.sqrt(max(0.0, _dot(offset, offset) - along * along))
