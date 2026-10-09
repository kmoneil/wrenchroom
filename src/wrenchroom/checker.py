"""The check loop: resolve each fastener's geometry, try its tools, record why.

The run is phased. First every fastener gets a frame (its unsigned axis and the
measurements around it); then screws and nuts are paired, forced pairs first,
coaxial ones found; then each fastener is tried in its state, retried in the
``try_states`` when it fails, with extraction checked on every screw that would
otherwise pass; last, joints are resolved: a fastener that only holds passes as
``held`` when its partner turns, and fails when it doesn't. Nothing is skipped
silently: whatever can't be resolved or has no tool in the kit is `not-covered`
with the reason in the report.

One deliberate divergence from the spec's scene rule: the pair partner STAYS in
the scene. It is physically there, and the bench's tail_too_long cell shows why
wholesale exclusion is wrong: a bolt's end past the socket's bore must still
block the socket. The cases partner-exclusion was invented for are handled where
they arise instead: the free-face probe is an annulus outside the bore, and the
socket carries a real bore for the bolt's end.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from itertools import compress
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from build123d import GeomType, Plane, Solid

from wrenchroom.assembly import Assembly, Part
from wrenchroom.config import Config, ConfigError, is_mate
from wrenchroom.detect import find
from wrenchroom.detect.geometry import read_shape, wide_end
from wrenchroom.engine import (
    DEFAULT_ENGINE,
    ENGINES,
    HIT_MIN_VOLUME,
    Engine,
    Scene,
    make_engine,
)
from wrenchroom.engine.exact import exact_overlap
from wrenchroom.engine.scene import boxes_overlap
from wrenchroom.fasteners import (
    HEX_AF_MIN,
    PHILLIPS_NUMBER,
    RECESS_AF_MAX,
    RECESS_LOOSE_MM,
    TORX_RECESS_A,
    TORX_SIZE,
    Fastener,
    Head,
    Kind,
    PassedOver,
    Size,
    hex_key_af,
    in_hex_band,
    in_recess_band,
    loosely_fits,
    no_such_head,
    phillips_by_span,
    spanner_af,
    standard_hex_afs,
    thread_minor_mm,
)
from wrenchroom.report import (
    EngineNote,
    FastenerResult,
    Report,
    StateModel,
    Verdict,
    bounded,
    listed,
)
from wrenchroom.tools.ball_end import BALL_END_KEYS, BallEndKey, ball_end_attempts
from wrenchroom.tools.custom import (
    ENDS,
    CustomDriver,
    CustomKey,
    CustomNutDriver,
    CustomSocket,
    CustomSpanner,
    CustomTool,
    CustomTools,
)
from wrenchroom.tools.drivers import SHAFT_RADIUS, driver_attempt
from wrenchroom.tools.fingers import HAND, finger_attempts
from wrenchroom.tools.hex_keys import HEX_KEYS, HexKey, hex_key_attempts
from wrenchroom.tools.kits import DEFAULT_KIT, Kit, kit_named, missing
from wrenchroom.tools.nut_drivers import NUT_DRIVERS, nut_driver_attempt
from wrenchroom.tools.sizes import FLATS, is_inch, size_mm, size_name, snap
from wrenchroom.tools.sockets import socket_attempts, socket_for
from wrenchroom.tools.spanners import (
    RING_CLEARANCE,
    corner_sweep,
    open_end_attempts,
    ring_attempts,
    spanner_for,
)
from wrenchroom.tools.sweep import (
    DEFAULT_STEP_DEG,
    Attempt,
    Mount,
    Probe,
    axial_annulus,
    axial_cylinder,
    radial_cylinder,
)
from wrenchroom.tools.torx_keys import ISO_10664

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from build123d import Axis, Face, Shape

    from wrenchroom.tools.nut_drivers import NutDriver
    from wrenchroom.tools.sockets import Socket
    from wrenchroom.tools.spanners import Spanner
    from wrenchroom.tools.torx_keys import TorxKey

#: How parallel a face normal must be to the axis to count as an end face.
_AXIAL = 0.99


#: A hex band shorter than this, mm, gives a ring nothing to grip.
_MIN_BAND = 0.5

#: How far out from each end of a nut whose ends are both clear the room is
#: probed, mm, nearest first: the end that meets nothing longer is the free face.
_ROOM_DEPTHS = (2.0, 5.0, 10.0, 25.0, 50.0)

#: A screw and a nut pair when their axes agree this closely (spec 7.3).
_PAIR_MAX_ANGLE_DEG = 0.5
_PAIR_MAX_OFFSET_MM = 0.3

_KEYED_HEADS = (Head.SOCKET, Head.BUTTON, Head.FLAT, Head.SHOULDER, Head.SET)

#: The keyed heads whose sockets are deep enough for a ball end: ISO 4762's and
#: ISO 7379's. A button head's (ISO 7380) or a countersunk head's (ISO 10642) is
#: about half as deep, barely deeper than the ball itself (issue #51).
_BALL_END_HEADS = (Head.SOCKET, Head.SHOULDER)

Vec = tuple[float, float, float]


class NotCovered(Exception):  # noqa: N818  (it is a verdict carrier, not an error suffix)
    """Raised inside the loop when a fastener can't be understood; becomes the verdict."""


class _BothEndsCovered(NotCovered):
    """A nut both of whose ends something sits against: a clash, it may be (issue #63)."""


def check(  # noqa: PLR0913  (one keyword per CLI option; bundling them would hide the API)
    assembly: Assembly,
    config: Config | None = None,
    *,
    kit: str = DEFAULT_KIT,
    step_deg: float = DEFAULT_STEP_DEG,
    model: str = "",
    only: str | None = None,
    state: str | None = None,
    model_dir: str | Path | None = None,
    engine: str = DEFAULT_ENGINE,
    hand_room: bool | None = None,
) -> Report:
    """Check every fastener the config names against the assembly.

    Args:
        assembly: The parts in their assembled positions.
        config: The sidecar; ``None`` means no fasteners, which still yields a
            valid (empty, passing) report.
        kit: Which tool kit (:mod:`wrenchroom.tools.kits`): only its tools are
            tried, and a fastener needing another is not covered.
        step_deg: Swing sampling step, degrees.
        model: The model's name for the report header.
        only: A glob narrowing which fasteners are checked, as ``--only``.
        state: Overrides the config's ``default_state`` for this run.
        model_dir: Where a state's alternate model files live; the CLI passes
            the model's own directory.
        engine: Which collision engine answers the queries: ``mesh`` (the
            default) or ``exact`` (OCP booleans, the referee).
        hand_room: Check room for the hand round each handle (spec 6.4);
            ``None`` takes the sidecar's ``checks: {hand_room: ...}``, off by
            default.

    Raises:
        ValueError: On a kit, state or engine that doesn't exist (a typo, not a
            model problem).
    """
    config = config or Config()
    hand = config.hand_room if hand_room is None else hand_room
    tools = _Tools(kit_named(kit), step_deg, hand, config.tools)
    if engine not in ENGINES:
        msg = f"unknown engine {engine!r}; available: {', '.join(ENGINES)}"
        raise ValueError(msg)
    default_state = state if state is not None else config.default_state
    if default_state is not None:
        config.state(default_state)  # raises on a typo
    matches = config.apply(assembly)
    fasteners, passed_over = _fasteners(assembly, config, matches.fasteners)
    # One fastener drawn twice, over itself, is a fault in the model, said once on
    # the first by name; the other isn't checked again (issue #94).
    space = _StateSpace(assembly, config, model_dir, make_engine(engine))
    twice = _drawn_twice(fasteners, assembly, space.engine)
    fasteners = [f for f in fasteners if f.name not in twice]
    twin = {kept: other for other, (kept, _) in twice.items()}
    # ``only`` narrows what is reported, not what is resolved (issue #46): pairs
    # are found over the whole model, and a chosen fastener's partner is checked
    # with it, so a narrowed verdict is the full run's.
    chosen = [
        f
        for f in fasteners
        if only is None or any(fnmatchcase(n, only) for n in (f.name, twin.get(f.name, f.name)))
    ]
    if only is not None:
        passed_over = tuple(p for p in passed_over if fnmatchcase(p.name, only))
    # A narrowing glob that picks nothing checks nothing: as with a sidecar rule
    # that matches nothing, that is how a renamed part hides, so the run says so
    # and exits 2 rather than passing (issue #20).
    only_warnings = (
        [f"only glob {only!r} matched no fastener (renamed part?)"]
        if only is not None and not chosen
        else []
    )
    # A mate that names nothing leaves its part in the scene, and the fastener
    # blocked by the very part it was told it may touch (issue #32).
    only_warnings += [
        f"rule {parts!r}: mate glob {glob!r} matched nothing (renamed part?)"
        for parts, glob in matches.unmatched_mates
    ]

    frames, failures = _frames(fasteners, assembly, twice)
    pairs, pair_warnings = _find_pairs(fasteners, frames, config)
    fasteners = _sized_by_partners(fasteners, pairs)
    reported = {f.name for f in chosen}
    checked = reported | {pairs[name] for name in reported if name in pairs}

    candidates: list[_Candidate] = []
    for fastener in fasteners:
        if fastener.name not in checked:
            continue
        if fastener.name in failures:
            candidates.append(_Candidate(fastener, reason=failures[fastener.name]))
            continue
        frame, partner = frames[fastener.name], pairs.get(fastener.name)
        candidates.append(
            _check_fastener(fastener, frame, space, config, default_state, tools, partner)
        )
    results = [
        replace(r, notes=(*r.fastener.notes, *_drive_notes(r.fastener), *r.notes))
        for r in _resolve_joints(candidates, pairs)
        if r.fastener.name in reported
    ]
    models = {None: StateModel(assembly), **space.models}
    return Report(
        model=model,
        kit=kit,
        engine=engine,
        results=tuple(results),
        unmatched_rules=tuple(
            rule.parts
            for rule in matches.unmatched_rules
            if not _surfaces_matched(rule.parts, assembly)
        ),
        unmatched_ignores=tuple(
            glob for glob in matches.unmatched_ignores if not _surfaces_matched(glob, assembly)
        ),
        surfaces=assembly.surfaces,
        warnings=tuple(
            only_warnings
            + pair_warnings
            + space.warnings
            + _surface_warnings(tuple(rule.parts for rule in matches.unmatched_rules), assembly)
        ),
        notes=(*space.notes, *_unused_tools(fasteners, tools)),
        engine_notes=_engine_notes(space.engine),
        passed_over=passed_over,
        default_state=default_state,
        hand_room=tools.hand_room,
        models=models,
        ignored=frozenset(
            part.name
            for state_model in models.values()
            for part in state_model.assembly
            if _ignored(config, part)
        ),
    )


#: Two fasteners sharing more than this fraction of each one's volume are one drawn
#: twice (issue #94): a screw drawn once for each of two optional parts, say.
_TWICE = 0.5


def _drawn_twice(
    fasteners: list[Fastener], assembly: Assembly, engine: Engine
) -> dict[str, tuple[str, float]]:
    """Fasteners drawn over another: each to (the one it's over, the volume in common).

    Their boxes go first, all at once, the engine's, which it keeps for the scenes:
    only two whose boxes share half of each are measured, by a boolean. Of two, the
    later by name is the one drawn over the other.
    """
    if len(fasteners) < 2:  # noqa: PLR2004  (a pair)
        return {}
    parts = [assembly[fastener.name] for fastener in fasteners]
    shapes = [part.shape for part in parts]
    corners = np.array([engine.part_box(part) for part in parts], dtype=float)
    low = np.maximum(corners[:, None, 0], corners[None, :, 0])
    high = np.minimum(corners[:, None, 1], corners[None, :, 1])
    shared = np.clip(high - low, 0.0, None).prod(axis=2)
    own = (corners[:, 1] - corners[:, 0]).prod(axis=1)
    near = np.triu(shared > _TWICE * np.maximum(own[:, None], own[None, :]), k=1)
    found: dict[str, tuple[str, float]] = {}
    for first, second in np.argwhere(near):
        kept, other = fasteners[first].name, fasteners[second].name
        if kept in found or other in found:
            continue
        common = exact_overlap(shapes[first], shapes[second])
        if common > _TWICE * max(shapes[first].volume, shapes[second].volume):
            found[other] = (kept, common)
    return found


def _frames(
    fasteners: list[Fastener], assembly: Assembly, twice: dict[str, tuple[str, float]]
) -> tuple[dict[str, _Frame], dict[str, str]]:
    """Each fastener's frame, or why it can't be understood: the first phase."""
    frames: dict[str, _Frame] = {}
    failures = {
        kept: f"drawn twice: {other} is drawn over it ({common:.1f} mm^3 in common): fix the model"
        for other, (kept, common) in twice.items()
    }
    for fastener in fasteners:
        if fastener.name in failures:
            continue
        if fastener.not_covered is not None:
            failures[fastener.name] = fastener.not_covered
            continue
        try:
            pieces = _pieces(assembly, fastener.name)
            frames[fastener.name] = _frame(assembly[fastener.name], fastener, pieces)
        except NotCovered as exc:
            failures[fastener.name] = str(exc)
    return frames, failures


def _surfaces_matched(glob: str, assembly: Assembly) -> tuple[str, ...]:
    """The parts drawn as surfaces a glob names, which no rule or ignore can reach (#104)."""
    return tuple(name for name in assembly.surfaces if fnmatchcase(name, glob))


def _surface_warnings(rules: tuple[str, ...], assembly: Assembly) -> list[str]:
    """A rule naming only parts drawn as surfaces, said as that, not as a rename (#104)."""
    said = []
    for glob in rules:
        names = _surfaces_matched(glob, assembly)
        if len(names) == 1:
            said.append(
                f"rule {glob!r} names only {names[0]}, drawn as a surface, not a solid: "
                "make it a solid to check it"
            )
        elif names:
            said.append(
                f"rule {glob!r} names only {listed(names)}, drawn as surfaces, not solids: "
                "make them solids to check them"
            )
    return said


def _ignored(config: Config, part: Part) -> bool:
    """An ignore glob takes the part out, by its own name or, for a piece, its leaf's."""
    return config.is_ignored(part.name) or (
        part.piece_of is not None and config.is_ignored(part.piece_of)
    )


def _fasteners(
    assembly: Assembly, config: Config, described: tuple[Fastener, ...]
) -> tuple[list[Fastener], tuple[PassedOver, ...]]:
    """The sidecar's fasteners, plus what detection finds among the parts it doesn't name.

    A rule that matches a part describes it outright: detection only ever sees
    parts no rule covers, and never an ignored one. What detection passed over
    (named like a fastener, no drive or bore in the solid) comes back with them.
    """
    found = list(described)
    passed: tuple[PassedOver, ...] = ()
    if config.detect:
        named = {f.name for f in described}
        detection = find(
            part
            for part in assembly
            if part.name not in named and part.piece_of is None and not config.is_ignored(part.name)
        )
        found += detection.fasteners
        passed = detection.passed_over
    found.sort(key=lambda f: f.name)
    return found, passed


# ---------------------------------------------------------------------------
# Frames: the unsigned measurements everything else reads.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Frame:
    """A part measured about its (possibly still unsigned) axis."""

    part: Part
    direction: Vec
    origin: Vec
    projections: tuple[float, ...]
    radials: tuple[float, ...]
    bore: float
    oriented: bool  # True when the fastener gave an explicit axis
    #: Which vertices lie on a flat parallel to the axis (a hex's): where the
    #: band is, when the part has any (issue #47).
    flats: tuple[bool, ...] = ()
    #: The part's planar and cylindrical faces, read once (:func:`_faces_of`).
    faces: tuple[_Face, ...] = ()
    #: Its other solids' vertices, as (projection, radial): a thumb screw's shank
    #: drawn apart from its knurled head (issue #96). Read only where its own solid
    #: can't tell which end is its head.
    pieces: tuple[tuple[float, float], ...] = ()

    @property
    def extent(self) -> float:
        return max(self.projections) - min(self.projections)

    def point_at(self, t: float) -> Vec:
        return _add(self.origin, _scale(self.direction, t))


@dataclass(frozen=True)
class _Face:
    """A planar or cylindrical face, read once: a point on it and its normal there."""

    face: Face
    plane: bool
    point: Vec
    normal: Vec


def _faces_of(part: Part) -> tuple[_Face, ...]:
    """Every planar and cylindrical face of a part, each read once for its frame.

    The point and normal are the face's own, at the middle of its parameters, not
    at its centroid: on a plane or a coaxial cylinder any point gives the same
    answer to the tests here, and a centroid is an integral over the face, which
    the frame's tests used to take again and again.
    """
    found = []
    for face in part.shape.faces():
        kind = face.geom_type
        if kind is GeomType.PLANE or kind is GeomType.CYLINDER:
            point: Vec = tuple(face.position_at(0.5, 0.5))  # type: ignore[assignment]
            normal: Vec = tuple(face.normal_at(0.5, 0.5))  # type: ignore[assignment]
            found.append(_Face(face, kind is GeomType.PLANE, point, normal))
    return tuple(found)


def _pieces(assembly: Assembly, name: str) -> tuple[Part, ...]:
    """The other solids of a part's leaf, which go with it (issue #28)."""
    return tuple(assembly[piece] for piece in assembly.pieces(name))


def _frame(part: Part, fastener: Fastener, pieces: tuple[Part, ...] = ()) -> _Frame:
    faces = _faces_of(part)
    axis = _largest_cylinder_axis(faces)
    direction = _axis_direction(axis, fastener)
    origin, vertices = _axis_frame(part, axis)
    projections = tuple(_dot(_sub(v, origin), direction) for v in vertices)
    radials = tuple(_radial(_sub(v, origin), direction) for v in vertices)
    others = [tuple(v) for piece in pieces for v in piece.shape.vertices()]
    return _Frame(
        part=part,
        direction=direction,
        origin=origin,
        projections=projections,
        radials=radials,
        bore=_bore_radius(faces, direction),
        oriented=isinstance(fastener.axis, tuple),
        flats=_on_flats(faces, origin, direction, vertices),
        faces=faces,
        pieces=tuple(
            (_dot(_sub(v, origin), direction), _radial(_sub(v, origin), direction))  # type: ignore[arg-type]
            for v in others
        ),
    )


def _on_flats(
    faces: tuple[_Face, ...], origin: Vec, direction: Vec, vertices: list[Vec]
) -> tuple[bool, ...]:
    """Which vertices lie on a planar face parallel to the axis, facing out: a hex's flats.

    None do unless at least three such faces stand round it (a hex, a square):
    one flat ground on a round part says nothing about where a spanner grips.
    A flat facing the axis is a key's pocket or a slot, which no spanner grips.
    """
    flats = []
    for face in faces:
        if not face.plane:
            continue
        out = _sub(face.point, origin)
        radial = _sub(out, _scale(direction, _dot(out, direction)))
        if abs(_dot(face.normal, direction)) < 1 - _AXIAL and _dot(face.normal, radial) > 0:
            flats.append(face.face)
    if len(flats) < 3:  # noqa: PLR2004  (a square has four, a hex six)
        return ()
    corners = {_vertex_key(tuple(v)) for face in flats for v in face.vertices()}
    return tuple(_vertex_key(v) in corners for v in vertices)


def _vertex_key(v: Vec) -> tuple[float, float, float]:
    return (round(v[0], 6), round(v[1], 6), round(v[2], 6))


def _largest_cylinder_axis(faces: tuple[_Face, ...]) -> Axis | None:
    cylinders = [face.face for face in faces if not face.plane]
    if not cylinders:
        return None
    return max(cylinders, key=lambda f: f.area).axis_of_rotation


def _axis_direction(axis: Axis | None, fastener: Fastener) -> Vec:
    if isinstance(fastener.axis, tuple):
        return fastener.axis
    if axis is None:
        raise NotCovered("axis is auto but the part has no cylindrical face")
    return tuple(axis.direction)  # type: ignore[return-value]


def _axis_frame(part: Part, axis: Axis | None) -> tuple[Vec, list[Vec]]:
    if axis is not None:
        origin: Vec = tuple(axis.position)  # type: ignore[assignment]
    else:
        center = part.shape.bounding_box().center()
        origin = (center.X, center.Y, center.Z)
    vertices = [tuple(v) for v in part.shape.vertices()]
    if not vertices:
        raise NotCovered("the part has no vertices to measure")
    return origin, vertices  # type: ignore[return-value]


def _band(
    projections: tuple[float, ...], radials: tuple[float, ...], flats: tuple[bool, ...] = ()
) -> tuple[float, float]:
    """Where a spanner or ring grips, along the axis: the flats' extent, if any.

    A part with no flats parallel to its axis falls back to its widest region.
    The flats are the hex, where the widest region need not be: a gland's dome
    or a flange nut's flange can be wider than the hex, and one about as wide
    used to stretch the band over itself (issue #47).
    """
    if any(flats):
        heights = [p for p, flat in zip(projections, flats, strict=True) if flat]
        return (min(heights), max(heights))
    widest = max(radials, default=0.0)
    heights = [p for p, r in zip(projections, radials, strict=True) if r > 0.75 * widest]
    if not heights:
        return (0.0, 0.0)
    return (min(heights), max(heights))


def _bore_radius(faces: tuple[_Face, ...], direction: Vec) -> float:
    """The smallest coaxial cylinder facing the axis: a nut's bore, a gland's cable way.

    0 if none. Only a face looking in is a bore: a gland's dome, outside, used to
    be taken for one, and leave no face to probe (issue #47).
    """
    radii = []
    for face in faces:
        if face.plane:
            continue
        axis, radius = face.face.axis_of_rotation, face.face.radius
        if axis is None or radius is None or abs(_dot(tuple(axis.direction), direction)) <= _AXIAL:
            continue
        out = _sub(face.point, tuple(axis.position))  # type: ignore[arg-type]
        radial = _sub(out, _scale(direction, _dot(out, direction)))
        if _dot(face.normal, radial) < 0:
            radii.append(radius)
    return min(radii, default=0.0)


# ---------------------------------------------------------------------------
# Pairs (spec 7.3): forced ones first, then coaxial screw and nut.
# ---------------------------------------------------------------------------


def _find_pairs(
    fasteners: list[Fastener],
    frames: dict[str, _Frame],
    config: Config,
) -> tuple[dict[str, str], list[str]]:
    names = {f.name for f in fasteners}
    pairs: dict[str, str] = {}
    warnings: list[str] = []
    for a, b in config.pairs:
        missing = [n for n in (a, b) if n not in names]
        if missing:
            warnings.append(f"forced pair [{a}, {b}] names no fastener: {', '.join(missing)}")
            continue
        pairs[a], pairs[b] = b, a
    screws = [f for f in fasteners if f.kind is Kind.SCREW and f.name in frames]
    nuts = [f for f in fasteners if f.kind is not Kind.SCREW and f.name in frames]
    for screw in screws:
        if screw.name in pairs:
            continue
        candidates = [
            (offset, nut.name)
            for nut in nuts
            if nut.name not in pairs
            and (offset := _coaxial_offset(frames[screw.name], frames[nut.name])) is not None
        ]
        if candidates:
            _, nut_name = min(candidates)
            pairs[screw.name], pairs[nut_name] = nut_name, screw.name
    return pairs, warnings


def _sized_by_partners(fasteners: list[Fastener], pairs: dict[str, str]) -> list[Fastener]:
    """A nut or fixed thread whose own reading gave no size, or guessed one, takes its screw's.

    A nut on an M8 bolt is M8. Its bore drawn at the minor diameter, or not at
    all, says nothing, and a hex drawn a little small sits in another size's
    band (an M8 at 12.6 in a 5/16's); the thread it runs on does say, and with
    it the system its spanner comes from (issue #50). So with a fixed thread,
    whose bore alone may sit on another size: an M3 T-nut bored 2.8 is #4's
    (issue #84). A gland keeps none: its thread is not its hex's.
    """
    by_name = {f.name: f for f in fasteners}
    sized = []
    for fastener in fasteners:
        partner = by_name.get(pairs.get(fastener.name, ""))
        if (
            fastener.kind in (Kind.NUT, Kind.INSERT)
            and (fastener.size is None or fastener.size_guessed)
            and fastener.socket_allowed
            and partner is not None
            and partner.kind is Kind.SCREW
            and partner.size is not None
            and partner.size != fastener.size
        ):
            nut = fastener.kind is Kind.NUT
            note = f"size {partner.size.designation} from its {'bolt' if nut else 'screw'}, "
            note += partner.name
            if fastener.size is not None:
                alone = "hex" if nut else "bore"
                note += f" (its {alone} alone said {fastener.size.designation})"
            basis = f"{fastener.basis}; {note}" if fastener.basis else note
            notes = (*fastener.notes, note)
            sized.append(
                replace(fastener, size=partner.size, basis=basis, size_guessed=False, notes=notes)
            )
        else:
            sized.append(fastener)
    return sized


def _coaxial_offset(screw: _Frame, nut: _Frame) -> float | None:
    """The axis separation when the nut sits on this screw's shank, else None."""
    alignment = abs(_dot(screw.direction, nut.direction))
    if alignment < math.cos(math.radians(_PAIR_MAX_ANGLE_DEG)):
        return None
    between = _sub(nut.origin, screw.origin)
    along = _dot(between, screw.direction)
    offset = math.sqrt(max(0.0, _dot(between, between) - along * along))
    if offset > _PAIR_MAX_OFFSET_MM:
        return None
    band_lo, band_hi = _band(nut.projections, nut.radials, nut.flats)
    nut_centre = _dot(_sub(nut.point_at((band_lo + band_hi) / 2), screw.origin), screw.direction)
    if not (min(screw.projections) - 1.0 <= nut_centre <= max(screw.projections) + 1.0):
        return None
    return offset


# ---------------------------------------------------------------------------
# States: which assembly, and what's off, when a fastener is reached.
# ---------------------------------------------------------------------------


class _StateSpace:
    """Resolves state names to (assembly, removed parts), loading models lazily.

    It also owns the run's collision engine, so every scene in every state
    shares one cache of part boxes and meshes.
    """

    def __init__(
        self,
        assembly: Assembly,
        config: Config,
        model_dir: str | Path | None,
        engine: Engine,
    ) -> None:
        self._default = assembly
        self._config = config
        self._model_dir = None if model_dir is None else Path(model_dir)
        self._models: dict[str, Assembly] = {}
        self._warned: set[tuple[str, str]] = set()
        self._ignored: dict[str, bool] = {}
        # Per assembly (the assembly rides along, so its id can't be reused):
        # its parts, their boxes, the ones not ignored, and where each name is.
        self._scene_parts: dict[
            int,
            tuple[
                Assembly,
                tuple[tuple[Part, ...], np.ndarray, np.ndarray, np.ndarray, dict[str, list[int]]],
            ],
        ] = {}
        self.engine = engine
        self.warnings: list[str] = []
        #: What the state models differ in from the main model (issue #74).
        self.notes: list[str] = []
        #: Every state resolved so far, as the check saw it: kept for the report,
        #: whose HTML view draws a fastener in the state it was reached in.
        self.models: dict[str, StateModel] = {}

    def scene(self, assembly: Assembly, excluded: set[str] | frozenset[str]) -> Scene:
        """The obstacles: every part but the excluded and the ignored ones.

        The assembly's parts, boxes and ignored ones are gathered once
        (:meth:`_obstacles`); each fastener's scene masks out its own.
        """
        parts, low, high, kept, where = self._obstacles(assembly)
        mask = kept.copy()
        for name in excluded:
            mask[where.get(name, [])] = False
        return Scene(compress(parts, mask), self.engine, (low[mask], high[mask]))

    def _obstacles(
        self, assembly: Assembly
    ) -> tuple[tuple[Part, ...], np.ndarray, np.ndarray, np.ndarray, dict[str, list[int]]]:
        """An assembly's parts, their boxes, which aren't ignored, and where each name is."""
        cached = self._scene_parts.get(id(assembly))
        if cached is None or cached[0] is not assembly:
            parts = tuple(assembly)
            boxes = [self.engine.part_bounds(part) for part in parts]
            low = np.array([lo for lo, _ in boxes], dtype=float).reshape(-1, 3)
            high = np.array([hi for _, hi in boxes], dtype=float).reshape(-1, 3)
            kept = np.array([not self._is_ignored(part) for part in parts], dtype=bool)
            where: dict[str, list[int]] = {}
            for index, part in enumerate(parts):
                where.setdefault(part.name, []).append(index)
            cached = (assembly, (parts, low, high, kept, where))
            self._scene_parts[id(assembly)] = cached
        return cached[1]

    def _is_ignored(self, part: Part) -> bool:
        # Memoised: the ignore globs are tried once per name, not once per scene.
        ignored = self._ignored.get(part.name)
        if ignored is None:
            ignored = self._ignored[part.name] = _ignored(self._config, part)
        return ignored

    def resolve(self, state_name: str | None) -> tuple[Assembly, frozenset[str], bool]:
        """The assembly a state sees, its removed names, and whether it is the default."""
        if state_name is None:
            return self._default, frozenset(), True
        model = self._config.state_model(state_name)
        assembly = self._default if model is None else self._load(state_name, model)
        if model is not None and state_name not in self.models:
            self._compare(state_name, model, assembly)
        removed: set[str] = set()
        for glob in self._config.state_removes(state_name):
            hits = {name for name in assembly.names if fnmatchcase(name, glob)}
            if not hits and (state_name, glob) not in self._warned:
                self._warned.add((state_name, glob))
                self.warnings.append(
                    f"state {state_name!r}: remove glob {glob!r} matched nothing (renamed part?)"
                )
            removed |= hits
        self.models[state_name] = StateModel(assembly, frozenset(removed))
        return assembly, frozenset(removed), model is None

    def model_of(self, state_name: str) -> str | None:
        """The model file a state uses, its own or up its chain; None for the main model."""
        return self._config.state_model(state_name)

    def warn_absent(self, state_name: str, name: str) -> None:
        """A fastener a state's model doesn't have: not tried there, and the run fails.

        A renamed or dropped part in a state's export hid the fastener from that
        state, and its verdict stood with the default state's cause (issue #74).
        Each fastener is tried once in each state, so each is said once.
        """
        self.warnings.append(
            f"state {state_name!r}: its model {self.model_of(state_name)} has no part {name} "
            "(renamed?), so it wasn't tried there"
        )

    def _compare(self, state_name: str, model: str, assembly: Assembly) -> None:
        """Note a state's model whose parts aren't the main model's by name.

        A state's model is meant to be the same parts, moved: a name only one of
        them has is a renamed or dropped part, more often than not. Said, not
        failed for, since a state may also add or take away parts on purpose.
        """
        main = [name for name in self._default.names if not self._config.is_ignored(name)]
        theirs = [name for name in assembly.names if not self._config.is_ignored(name)]
        missing = tuple(name for name in main if name not in set(theirs))
        new = tuple(name for name in theirs if name not in set(main))
        said = []
        if missing:
            said.append(f"lacks {_count(missing, 'part')} of the main model's: {listed(missing)}")
        if new:
            said.append(f"has {_count(new, 'part')} the main model doesn't: {listed(new)}")
        if said:
            self.notes.append(f"state {state_name!r}: its model {model} {'; '.join(said)}")

    def _load(self, state_name: str, filename: str) -> Assembly:
        if filename not in self._models:
            self._models[filename] = Assembly.from_step(self._locate(state_name, filename))
        return self._models[filename]

    def _locate(self, state_name: str, filename: str) -> Path:
        """Where a state's model is: beside the sidecar, else beside the model (#73).

        A path in a config file is read as one beside it, as the pytest plugin's
        paths are; beside the model is where the CLI looked before, and still
        does when the sidecar's folder hasn't the file. An absolute path is taken
        as it is. A file found nowhere is said to be missing, apart from one found
        and not readable as STEP, which says that instead.
        """
        path = Path(filename)
        folders = [self._config.directory, self._model_dir]
        found = [path] if path.is_absolute() else [d / path for d in folders if d is not None]
        if not found:
            msg = f"state model {filename!r} needs a model directory to load from"
            raise ConfigError(msg)
        for candidate in dict.fromkeys(found):
            if candidate.exists():
                return candidate
        where = ", ".join(str(c.parent) for c in dict.fromkeys(found))
        owner = self._config.state(state_name)
        while owner.model is None and owner.base is not None:  # the state that names it
            owner = self._config.state(owner.base)
        msg = (
            f"state {state_name!r}: its model {filename} not found "
            f"({self._config.source}, states.{owner.name}.model; looked in {where})"
        )
        raise ConfigError(msg)


def _engine_notes(engine: Engine) -> tuple[EngineNote, ...]:
    """What the engine found of the parts it looked at closely, each said once.

    Which wouldn't mesh, and which are invalid B-reps (issue #85).
    """
    notes = []
    unmeshed = tuple(dict.fromkeys(engine.fallbacks))
    if unmeshed:
        notes.append(EngineNote("unmeshed", unmeshed))
    invalid = tuple(dict.fromkeys(engine.invalid))
    if invalid:
        notes.append(EngineNote("invalid", invalid))
    return tuple(notes)


def _count(names: tuple[str, ...], noun: str) -> str:
    """``1 part``, ``3 parts``."""
    return f"{len(names)} {noun}" + ("" if len(names) == 1 else "s")


# ---------------------------------------------------------------------------
# One fastener: its states in order, tools, extraction.
# ---------------------------------------------------------------------------


@dataclass
class _Candidate:
    """One fastener's raw outcome, before joints are resolved."""

    fastener: Fastener
    turns: bool = False
    stuck: bool = False
    hold: Attempt | None = None
    tool: str | None = None
    how: str | None = None
    swing_deg: float = 0.0
    blockers: tuple[str, ...] = ()
    stuck_on: tuple[str, ...] = ()
    attempts: tuple[Attempt, ...] = ()
    reason: str | None = None
    axis: Vec | None = None
    seat: Vec | None = None
    state: str | None = None
    extraction_blocked: tuple[str, ...] = field(default=())
    way_out: Probe | None = None
    #: What the hand ran into, when no attempt turns because the hand can't
    #: follow a tool that would: the spec's ``blocked (no room for a hand)``.
    no_hand_room: tuple[str, ...] = ()
    #: What the turning attempt only grazed (issue #25).
    grazes: tuple[str, ...] = ()
    #: The parts that bound the best arc any attempt found, when none turned.
    deciding: tuple[str, ...] = ()
    #: What the result should say of how it was checked (issue #47).
    notes: tuple[str, ...] = ()
    #: Its state's model has no part of its name (issue #74).
    absent: bool = False
    #: The part a nut sits trapped in, which holds it (issue #93).
    trapped_in: str | None = None


def _check_fastener(
    fastener: Fastener,
    frame: _Frame,
    space: _StateSpace,
    config: Config,
    default_state: str | None,
    tools: _Tools,
    partner: str | None = None,
) -> _Candidate:
    own_state = fastener.state if fastener.state is not None else default_state
    if fastener.kind is Kind.INSERT:
        # A fixed thread holds itself, and no tool comes at it from either end:
        # its axis, unsigned, is all there is to say (issue #29).
        return _Candidate(fastener, how="holds itself", axis=frame.direction, state=own_state)
    order: list[str | None] = [own_state]
    order += [s for s in config.try_states if s != own_state]
    first: _Candidate | None = None
    for index, state_name in enumerate(order):
        candidate = _try_in_state(fastener, frame, state_name, space, tools, partner)
        if candidate.absent and index > 0 and state_name is not None:
            space.warn_absent(state_name, fastener.name)  # a retry it can't have (#74)
        if first is None:
            first = candidate
        if candidate.reason is not None and index == 0:
            return candidate  # not understood; another state won't change that
        if candidate.turns and not candidate.stuck:
            return candidate
        if fastener.self_holding or candidate.trapped_in is not None:
            return candidate
    assert first is not None  # noqa: S101  (order always has at least own_state)
    return first


def _try_in_state(
    fastener: Fastener,
    default_frame: _Frame,
    state_name: str | None,
    space: _StateSpace,
    tools: _Tools,
    partner: str | None = None,
) -> _Candidate:
    assembly, removed, same_model = space.resolve(state_name)
    if fastener.name not in assembly.names:
        model = space.model_of(state_name) if state_name is not None else None
        whose = f", whose model {model} has no part of its name (renamed?)" if model else ""
        reason = f"not in state {state_name!r}{whose}"
        return _Candidate(fastener, reason=reason, state=state_name, absent=True)
    frame = default_frame
    if not same_model:  # parts may have moved: measure this model's own copy
        try:
            frame = _frame(assembly[fastener.name], fastener, _pieces(assembly, fastener.name))
        except NotCovered as exc:
            return _Candidate(fastener, reason=str(exc), state=state_name)
    mates = (
        {name for name in assembly.names if is_mate(name, fastener.mates)}
        if fastener.mates
        else set()
    )
    pieces = assembly.pieces(fastener.name)  # its other solids, which go with it
    scene = space.scene(assembly, {fastener.name, *mates, *pieces} | removed)
    oriented = _oriented(fastener, frame, scene, state_name, partner)
    if isinstance(oriented, _Candidate):
        return oriented
    mount, geometry = oriented
    if partner is not None and partner in assembly.names and partner not in removed:
        geometry = replace(geometry, through=_through(mount, assembly[partner]))
    candidate = _Candidate(fastener, axis=mount.axis, seat=mount.seat, state=state_name)
    if fastener.self_holding:
        candidate.how = "holds itself"
        return candidate
    _try_tools(candidate, frame, mount, geometry, scene, tools, partner)
    return candidate


def _oriented(
    fastener: Fastener, frame: _Frame, scene: Scene, state_name: str | None, partner: str | None
) -> tuple[Mount, _Geometry] | _Candidate:
    """Where a tool comes from, and the geometry it needs; else the fastener's verdict.

    A nut both of whose faces are covered may be in a trap, which holds it (issue
    #93), or drawn into a part, a clash (issue #63).
    """
    try:
        return _orient(frame, fastener, scene)
    except _BothEndsCovered as exc:
        candidate = _Candidate(fastener, axis=frame.direction, state=state_name)
        trap = _trapped_in(frame, fastener, scene)
        if trap is not None:
            _hold_in_trap(candidate, trap, frame, scene, partner)
            return candidate
        clash = _drawn_into(frame, fastener, scene, partner)
        return _Candidate(fastener, reason=clash or str(exc), state=state_name)
    except NotCovered as exc:
        return _Candidate(fastener, reason=str(exc), state=state_name)


def _try_tools(
    candidate: _Candidate,
    frame: _Frame,
    mount: Mount,
    geometry: _Geometry,
    scene: Scene,
    tools: _Tools,
    partner: str | None,
) -> None:
    """Each tool for the fastener in turn, then what the attempts say beyond a verdict."""
    fastener = candidate.fastener
    try:
        attempts_iter = _attempts_for(fastener, mount, geometry, scene, tools)
        _run_attempts(candidate, attempts_iter)
    except NotCovered as exc:  # also any a lazy attempt raises while running
        if not _in_trap(candidate, frame, scene, partner):  # no tool, and none needed (#93)
            candidate.reason = str(exc)
        return
    if not candidate.turns and _in_trap(candidate, frame, scene, partner):
        return
    if not candidate.turns:  # what stopped it may be drawn into it (issue #63)
        candidate.reason = _drawn_into(
            frame, fastener, scene, partner, candidate.blockers, toward=mount.axis
        )
        if candidate.reason is not None:
            candidate.tool = None  # no tool is the question until the model is fixed
            return
    candidate.notes = _attempt_notes(fastener, candidate, geometry)
    if fastener.kind is Kind.SCREW and (candidate.turns or candidate.hold):
        candidate.way_out = _way_out(fastener, frame, geometry, mount, scene)
        candidate.extraction_blocked = candidate.way_out.hits if candidate.way_out else ()
        if candidate.extraction_blocked:  # what's in its way out may be drawn into it (#94)
            blocked = candidate.extraction_blocked
            clash = _drawn_into(frame, fastener, scene, partner, blocked, toward=mount.axis)
            if clash is not None:
                candidate.reason, candidate.tool = clash, None
                return
        if candidate.turns and candidate.extraction_blocked:
            candidate.stuck = True
            candidate.stuck_on = candidate.extraction_blocked


#: Directions round a nut its trap is looked for in, every 30 degrees: a part its
#: corners meet in two opposite ones holds it (issue #93).
_TRAP_DIRECTIONS = 12

#: The radius of each direction's probe, mm, at most: thin, to say where round the
#: nut a part is, and no taller than the hex, to meet only what is beside it.
_TRAP_PROBE = 0.5


def _in_trap(candidate: _Candidate, frame: _Frame, scene: Scene, partner: str | None) -> bool:
    """Whether a nut nothing turns sits in a trap, which then holds it (issue #93).

    Asked once nothing turns it: its corners' own attempt, which every tool on a
    hex tries first, says what the ring round it met, where it ran; where it
    didn't (the kit has no tool for it, a rule named another), the ring is asked.
    A trap is the model's, whatever the kit.
    """
    corners = next((a for a in candidate.attempts if a.way == _CORNERS_WAY), None)
    met = corners.blockers if corners is not None else None
    trap = _trapped_in(frame, candidate.fastener, scene, met)
    if trap is None:
        return False
    _hold_in_trap(candidate, trap, frame, scene, partner)
    return True


def _hold_in_trap(
    candidate: _Candidate, trap: str, frame: _Frame, scene: Scene, partner: str | None
) -> None:
    """Held by the part it sits trapped in (issue #93), and noted if drawn into it.

    Drawn into its trap, a nut is in a press fit as often as a clash: said, not failed.
    """
    candidate.trapped_in, candidate.tool = trap, None
    candidate.how = f"held by its trap in {trap}"
    candidate.blockers = candidate.deciding = ()  # held by it, not blocked: in every kit
    candidate.notes = tuple(
        f"drawn {volume:.1f} mm^3 into its trap: a press fit, or a clash to fix"
        for _, volume in _clashes(frame, candidate.fastener, scene, partner, (trap,))
    )


def _trapped_in(
    frame: _Frame, fastener: Fastener, scene: Scene, met: tuple[str, ...] | None = None
) -> str | None:
    """The part a nut sits trapped in, if one: a hex pocket, or a slot its width (issue #93).

    A nut's corners, turning, sweep a ring round it from its flats out. A part
    they meet on two opposite sides stops it turning whatever grips it, and it
    needn't turn: the part holds it, as a fixed thread holds itself, and its
    screw must turn. A part on one side only, a rib a corner touches, is no
    trap: the nut is blocked by its corners, as before. Asked only where a nut's
    corners are stopped, or both its faces are covered, as a nut's in a side slot
    are, and then only round it where something is in the ring. ``met`` is what the
    ring met, where the check has asked already: the corners' own attempt.
    """
    if fastener.kind is not Kind.NUT:
        return None
    af = fastener.drive_af or (spanner_af(fastener.size) if fastener.size else None)
    if af is None:
        return None
    low, high = _band(frame.projections, frame.radials, frame.flats)
    mount = Mount(seat=frame.point_at(high), axis=frame.direction)
    if met is None:
        met = scene.hits(mount.place(corner_sweep(af, (0.0, low - high))))
    if not met:
        return None
    inner, outer = af / 2, af / math.sqrt(3) + RING_CLEARANCE
    radius = min(_TRAP_PROBE, (high - low) / 2)
    sides: dict[str, set[int]] = {}
    for index in range(_TRAP_DIRECTIONS):
        phi = index * 360.0 / _TRAP_DIRECTIONS
        probe = mount.place(radial_cylinder(radius, inner, outer, (low - high) / 2, phi))
        for name in scene.hits(probe):
            sides.setdefault(name, set()).add(index)
    half = _TRAP_DIRECTIONS // 2
    return next(
        (
            name
            for name in met
            if any(
                (index + half) % _TRAP_DIRECTIONS in sides.get(name, ())
                for index in sides.get(name, ())
            )
        ),
        None,
    )


def _blocked_reason(candidate: _Candidate) -> str | None:
    """Why nothing turns or holds it, beyond the parts in the way, when there is more."""
    corners = next((a for a in candidate.attempts if a.way == _CORNERS_WAY), None)
    if corners is not None:  # said once, not by every tool (issue #63)
        hex_ = "nut" if candidate.fastener.kind is Kind.NUT else "head"
        hit = listed(corners.blockers, candidate.attempts)
        return f"the {hex_}'s corners hit {hit} as it turns"
    if candidate.no_hand_room:
        # What stopped the hand where the tool's arc was best, if known (#52);
        # named once, and a few at most (#64).
        hand = candidate.deciding or candidate.no_hand_room
        where = " on its best arc" if candidate.deciding else ""
        return f"no room for a hand: the hand hits {listed(hand, candidate.attempts)}{where}"
    return None


#: How far from the axis a thread drawn at its nominal diameter reaches into a bore
#: drawn at its minor, as a multiple of the bore's radius: 1.2 for M3 to M24
#: (ISO 724's D1 against D). Inside that, an overlap is a thread, not a clash.
_THREAD_REACH = 1.25

#: A widest region thinner than this along the axis (a countersunk head's rim) is
#: no region: the whole part is measured for a clash instead.
_REGION_MIN = 0.1

#: How far past its drawn radius a screw's shank is left out of its clash region, mm:
#: a thread drawn at its nominal in a hole drawn at its minor overlaps inside it.
_SHANK_SLACK = 0.05

#: A set screw of no stated size is taken as drawn at its nominal, this many times
#: its minor: no coarse thread's is more (M1.6's 1.37, #0's 1.38; issue #122).
_NOMINAL_PAST_MINOR = 1.4


def _measured(frame: _Frame, fastener: Fastener, toward: Vec | None = None) -> tuple[Shape, Shape]:
    """What of a fastener a clash is measured on, and what of that is past its thread.

    A screw's head, all of it past its shank (:func:`_head_region`), where the
    check has found the end a tool comes from, ``toward``. Else its hex
    and its widest region along the axis, and what lies between: a nut's body,
    flange and all, a gland's hex. A nut's, or a gland's, runs on from there to
    its end on the tool's side, ``toward``: a cap nut's dome, a nyloc's collar, a
    gland's dome (issue #123). A shank or a gland's stub sits in its hole, often
    drawn at the nominal diameter in a tapped hole drawn at the minor: a thread,
    never measured. Nor, for deciding, is what lies within :data:`_THREAD_REACH`
    of a bore, along the bore's length: a cap nut's bore is blind, and its dome's
    top is measured. The widest region alone would miss a hex on a flange wider
    than it by a third, the hex alone a flange. A set screw is all thread: its
    core (:func:`_set_core`).
    """
    if fastener.kind is Kind.SCREW and fastener.head is Head.SET:
        core = _set_core(frame, fastener)
        return core, core
    hex_low, hex_high = _band(frame.projections, frame.radials, frame.flats)
    wide_low, wide_high = _band(frame.projections, frame.radials)
    low, high = min(hex_low, wide_low), max(hex_high, wide_high)
    region = _head_region(frame, fastener, (low, high), toward)
    if region is None:
        if fastener.kind is Kind.NUT and toward is not None:  # to its free end (#123)
            if _dot(toward, frame.direction) > 0:
                high = max(frame.projections)
            else:
                low = min(frame.projections)
        if high - low < _REGION_MIN:
            low, high = min(frame.projections), max(frame.projections)
        plane = Plane(origin=frame.point_at(low), z_dir=frame.direction)
        cylinder = Solid.make_cylinder(max(frame.radials) + 1.0, high - low, plane)
        region = frame.part.shape & cylinder
    if region is None:  # the region is the part's own, so never empty; for the types
        region = frame.part.shape
    if frame.bore <= 0:
        return region, region
    bore_low, bore_high = _bore_extent(frame) or (low, high)
    under = Plane(origin=frame.point_at(bore_low - 1.0), z_dir=frame.direction)
    thread = Solid.make_cylinder(frame.bore * _THREAD_REACH, bore_high - bore_low + 2.0, under)
    return region, region - thread


def _bore_extent(frame: _Frame) -> tuple[float, float] | None:
    """Where along its axis a fastener's bore runs: its faces' extent (issue #123)."""
    along = [
        _dot(_sub(tuple(vertex), frame.origin), frame.direction)
        for face in frame.faces
        if not face.plane
        and face.face.radius is not None
        and abs(face.face.radius - frame.bore) < _ON
        and _dot(face.normal, _radial_of(face.point, frame)) < 0
        for vertex in face.face.vertices()
    ]
    return (min(along), max(along)) if along else None


def _from_its_bolt(frame: _Frame, bolt: Part) -> Vec:
    """The way out of a nut's free end, away from its bolt's head (issue #123).

    Where no tool has found it, both its ends covered: a bolt's middle lies on its
    head's side of its nut, which is where the nut bears.
    """
    ends = [_dot(_sub(tuple(v), frame.origin), frame.direction) for v in bolt.shape.vertices()]
    middle = (min(frame.projections) + max(frame.projections)) / 2
    return frame.direction if (min(ends) + max(ends)) / 2 < middle else _neg(frame.direction)


def _set_core(frame: _Frame, fastener: Fastener) -> Shape:
    """A set screw's core, for a clash: all of it inside its thread (issue #122).

    A set screw has no head and no shank: it is all thread, drawn at its nominal
    in a hole drawn at its minor, as any thread is. The ring between, its whole
    length, is the thread, no clash, as a screw's shank isn't (#116); inside its
    minor diameter is the screw itself, and a part drawn there is drawn into it.
    """
    drawn = max(frame.radials)
    if fastener.size is not None:
        minor = thread_minor_mm(fastener.size) / 2
    else:
        minor = drawn / _NOMINAL_PAST_MINOR
    low, high = min(frame.projections), max(frame.projections)
    plane = Plane(origin=frame.point_at(low - 1.0), z_dir=frame.direction)
    core = Solid.make_cylinder(min(minor, drawn) - _SHANK_SLACK, high - low + 2.0, plane)
    found = frame.part.shape & core
    return found if found is not None else core  # for the types: the core is its own


def _head_region(
    frame: _Frame, fastener: Fastener, band: tuple[float, float], toward: Vec | None
) -> Shape | None:
    """A screw's head, for a clash: all of it but its shank (issue #116).

    From its bearing face, the far side of its hex and widest region from its
    end, the one a tool comes from (``toward``), to its top, whatever its
    profile: a button head's dome, a pan head's crown, which its widest region,
    the rim under them, leaves out; a flange; and under the bearing face, a
    countersunk head's cone, which flares out of the shank. The shank is a
    cylinder its drawn radius (the widest past the bearing face: a shoulder's, a
    thread's) from its tip up to the bearing face, and is left out, as a thread
    is. A head drawn with no shank (a part's head piece, its shank another
    solid) is all head. None for a set screw, which has no head, and a nut.
    """
    if fastener.kind is not Kind.SCREW or fastener.head is Head.SET or toward is None:
        return None
    end = 1 if _dot(toward, frame.direction) > 0 else -1  # the head is the tool's end
    pairs = zip(frame.projections, frame.radials, strict=True)
    if end > 0:  # the head at the far end along the axis
        bearing, tip = band[0], min(frame.projections)
        shank = [r for p, r in pairs if p < bearing - _ON]
    else:
        bearing, tip = band[1], max(frame.projections)
        shank = [r for p, r in pairs if p > bearing + _ON]
    if not shank:  # a head drawn alone: all of it is head
        return frame.part.shape
    start = tip - 1.0 if end > 0 else bearing  # from past the tip to the bearing face
    plane = Plane(origin=frame.point_at(start), z_dir=frame.direction)
    rod = Solid.make_cylinder(max(shank) + _SHANK_SLACK, abs(bearing - tip) + 1.0, plane)
    return frame.part.shape - rod


def _drawn_into(
    frame: _Frame,
    fastener: Fastener,
    scene: Scene,
    partner: str | None,
    among: tuple[str, ...] | None = None,
    *,
    toward: Vec | None = None,
) -> str | None:
    """The parts a fastener's own solid is drawn into, past the hit floor: a clash.

    A nut drawn into the part beside it isn't a reach problem, and no tool choice fixes
    it: the model does (issue #63). Only asked once something has gone wrong,
    both its ends covered or nothing turning it, and then only of the parts that
    stopped it, so the booleans are few: asked of every fastener, they cost a
    fifth of the 500-fastener budget, for clashes that change no verdict.
    A thread is no clash (:func:`_measured`), and its pair's partner is passed
    over. A part overlapping the measured region past the thread is a clash, and
    its whole overlap with that region is the volume told.
    """
    found = _clashes(frame, fastener, scene, partner, among, toward)
    if not found:
        return None
    total = sum(volume for _, volume in found)
    names = tuple(name for name, _ in found)
    return f"drawn into {listed(names)} ({total:.1f} mm^3): fix the model"


def _clashes(
    frame: _Frame,
    fastener: Fastener,
    scene: Scene,
    partner: str | None,
    among: tuple[str, ...] | None,
    toward: Vec | None = None,
) -> list[tuple[str, float]]:
    """Each part the fastener is drawn into, past its thread, and by how much (mm^3)."""
    part, engine = frame.part, scene.engine
    box = engine.part_bounds(part)
    if toward is None and fastener.kind is Kind.NUT and partner is not None:
        bolt = next((p for p in scene.parts if p.name == partner), None)
        toward = _from_its_bolt(frame, bolt) if bolt is not None else None
    region, past_thread = _measured(frame, fastener, toward)
    found: list[tuple[str, float]] = []
    for other in scene.parts:
        if other.name == partner or (among is not None and other.name not in among):
            continue
        if not boxes_overlap(box, engine.part_bounds(other)):
            continue
        if exact_overlap(past_thread, other.shape) > HIT_MIN_VOLUME:
            found.append((other.name, exact_overlap(region, other.shape)))
    return found


def _attempt_notes(
    fastener: Fastener, candidate: _Candidate, geometry: _Geometry
) -> tuple[str, ...]:
    """What the attempts leave a person to know: a body no ring gets over, a ball end only."""
    notes = []
    # Only its own body puts the part's name among an attempt's blockers: the
    # scene never holds the part itself.
    if any(attempt.blockers == (fastener.name,) for attempt in candidate.attempts):
        notes.append(
            f"no ring, socket or nut driver gets on: past its hex the part is "
            f"{2 * geometry.cap_radius:.2f} across, wider than their bore round the hex; "
            "only an open end grips it, from the side"
        )
    if candidate.turns and (candidate.tool or "").startswith("ball-end-key"):
        notes.append(
            f"only a ball end turns it ({candidate.how}): a ball end takes much less "
            "torque than a straight key, so tightening it to its torque, or breaking it "
            "loose, may need a straight key, which can't get in"
        )
    return tuple(notes)


def _run_attempts(candidate: _Candidate, attempts_iter: Iterator[Attempt]) -> None:
    tried: list[Attempt] = []
    blockers: list[str] = []
    for attempt in _tried_iter(attempts_iter, tried):
        for name in attempt.blockers:
            if name not in blockers:
                blockers.append(name)
        if attempt.holds and candidate.hold is None and not attempt.turns:
            candidate.hold = attempt
        if attempt.turns:
            candidate.turns = True
            candidate.tool = attempt.tool
            candidate.how = attempt.way
            candidate.swing_deg = attempt.swing_deg
            candidate.blockers = attempt.blockers
            candidate.grazes = attempt.grazes
            break
    candidate.attempts = tuple(tried)
    if not candidate.turns:
        candidate.tool = (
            candidate.hold.tool if candidate.hold else (tried[0].tool if tried else None)
        )
        candidate.swing_deg = max((a.swing_deg for a in tried), default=0.0)
        candidate.no_hand_room = _hand_blockers(tried)
        hand = candidate.no_hand_room
        every = tuple(blockers) + tuple(n for n in hand if n not in blockers)
        candidate.deciding = _deciding(tried)
        rest = tuple(n for n in every if n not in candidate.deciding)
        candidate.blockers = candidate.deciding + rest


def _deciding(tried: list[Attempt]) -> tuple[str, ...]:
    """What bounds the best arc any attempt found: the first attempt with the most swing.

    Every probe's hits are blockers, most of them far round the sweep, changing
    nothing; the two ends of the best arc are what kept it short (issue #52).
    """
    bounded = [attempt for attempt in tried if attempt.bounds]
    if not bounded:
        return ()
    best = max(bounded, key=lambda attempt: attempt.swing_deg)
    return best.bounds


def _hand_blockers(tried: list[Attempt]) -> tuple[str, ...]:
    """What the hand hit, over every attempt the hand alone stopped; first-seen order."""
    hand: list[str] = []
    for attempt in tried:
        if attempt.no_hand_room:
            hand.extend(name for name in attempt.hand_blockers if name not in hand)
    return tuple(hand)


def _tried_iter(attempts_iter: Iterator[Attempt], tried: list[Attempt]) -> Iterator[Attempt]:
    """Yield attempts while recording them; the record outlives the early stop."""
    for attempt in attempts_iter:
        tried.append(attempt)
        yield attempt


def _way_out(
    fastener: Fastener,
    frame: _Frame,
    geometry: _Geometry,
    mount: Mount,
    scene: Scene,
) -> Probe | None:
    """The screw's way out, head's circle swept its length past the seat, and what's in it.

    None when there is no length to sweep.
    """
    length = fastener.length_mm
    if length is None:
        length = frame.extent - geometry.band_height
    if length <= 0:
        return None
    radius = geometry.circumradius
    if fastener.head is Head.SET:
        # No head: it backs out through its own tapped hole, which a thread drawn
        # at its minor diameter fills to within the thread's reach (issue #96).
        radius /= _THREAD_REACH
    swept = mount.place(axial_cylinder(radius, 0.0, length))
    return Probe(swept, scene.hits(swept))


# ---------------------------------------------------------------------------
# Joints: a fastener that only holds needs a partner that turns.
# ---------------------------------------------------------------------------


def _resolve_joints(candidates: list[_Candidate], pairs: dict[str, str]) -> list[FastenerResult]:
    by_name = {candidate.fastener.name: candidate for candidate in candidates}
    results = []
    for candidate in candidates:
        partner_name = pairs.get(candidate.fastener.name)
        partner = by_name.get(partner_name) if partner_name else None
        results.append(_finish(candidate, partner_name, partner))
    return results


def _partner_turns(partner: _Candidate | None) -> bool:
    return partner is not None and partner.turns and not partner.stuck


def _alone(partner_name: str | None, partner: _Candidate | None) -> str:
    """Why a fastener that only holds has nothing to turn against it.

    A fixed thread or a carriage bolt never turns, by design: the fastener on it
    is the one that must (issue #84), which is said as such, not as a partner
    that failed.
    """
    if partner_name is None:
        return "it has no nut"
    if partner is not None and partner.fastener.kind is Kind.INSERT:
        return f"it screws into a fixed thread ({partner_name}), so it must turn"
    if partner is not None and partner.fastener.head is Head.CARRIAGE:
        return f"its bolt ({partner_name}) holds itself, so it must turn"
    if partner is not None and partner.trapped_in is not None:
        return (
            f"its nut ({partner_name}) is held by its trap in {partner.trapped_in}, so it must turn"
        )
    return f"its partner {partner_name} does not turn"


def _finish(
    candidate: _Candidate, partner_name: str | None, partner: _Candidate | None
) -> FastenerResult:
    fastener = candidate.fastener
    verdict = Verdict.BLOCKED
    tool, how, reason = candidate.tool, candidate.how, candidate.reason
    grazes = candidate.grazes
    stuck_on: tuple[str, ...] = ()
    if candidate.reason is not None:
        verdict, how = Verdict.NOT_COVERED, None
    elif fastener.self_holding or candidate.trapped_in is not None:
        verdict, tool = Verdict.HELD, None
    elif candidate.stuck:
        verdict, stuck_on = Verdict.STUCK, candidate.stuck_on
    elif candidate.turns:
        verdict = Verdict.TURNS
    elif candidate.hold is not None and _partner_turns(partner):
        tool, how, grazes = candidate.hold.tool, candidate.hold.way, candidate.hold.grazes
        if candidate.extraction_blocked:
            verdict, stuck_on = Verdict.STUCK, candidate.extraction_blocked
        else:
            verdict = Verdict.HELD
    elif candidate.hold is not None:
        how = None
        reason = "only holds, and " + _alone(partner_name, partner)
        if candidate.deciding:  # what kept its best arc short (issues #52, #64)
            reason += f"; best arc {bounded(candidate.deciding, candidate.attempts)}"
    else:
        how = None
        reason = _blocked_reason(candidate)
    return FastenerResult(
        fastener,
        verdict,
        tool=tool,
        how=how,
        swing_deg=candidate.swing_deg,
        blockers=candidate.blockers,
        stuck_on=stuck_on,
        attempts=candidate.attempts,
        way_out=candidate.way_out,
        reason=reason,
        axis=candidate.axis,
        seat=candidate.seat,
        state=candidate.state,
        pair=partner_name,
        grazes=grazes if verdict in {Verdict.TURNS, Verdict.STUCK, Verdict.HELD} else (),
        notes=candidate.notes,
        deciding=candidate.deciding if verdict is Verdict.BLOCKED else (),
    )


# ---------------------------------------------------------------------------
# Orientation and the geometry the tools need.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Geometry:
    """What resolution learned about the part beyond the mount.

    ``band_top`` and ``band_bottom`` are the widest region's faces in the local
    frame (seat at 0, axis +z, both <= 0): a plain nut's whole body, a hex head's
    depth, a gland's hex between its dome and its thread stub. Spanner and ring
    placement use the band, never the part's overall extent, because the part's
    top may be a dome nothing grips.
    """

    band_top: float
    band_bottom: float
    circumradius: float
    bore_radius: float
    #: How far the part reaches from the axis past its band, toward the seat:
    #: what a ring or socket must pass to get on (a gland's dome; issue #47).
    cap_radius: float = 0.0
    #: The part's own name, for an attempt its own body stops.
    part_name: str = ""
    #: The drive's across-flats as the solid shows it (a hex, a hex socket), read only
    #: where a rule names a tool, which may fit it (issue #72); None elsewhere.
    drawn_af: float | None = None
    #: How far past the seat the bolt through it reaches, along the axis: what a
    #: ring must clear before it comes in from the side (issue #121). 0 for none.
    through: float = 0.0

    @property
    def band_height(self) -> float:
        return self.band_top - self.band_bottom


def _orient(frame: _Frame, fastener: Fastener, scene: Scene) -> tuple[Mount, _Geometry]:
    direction = frame.direction
    projections = frame.projections
    if not frame.oriented and _is_flipped(frame, fastener, scene):
        direction = _neg(direction)
        projections = tuple(-p for p in projections)
    top = max(projections)
    seat = _add(frame.origin, _scale(direction, top))
    band_lo, band_hi = _band(projections, frame.radials, frame.flats)
    past = [r for p, r in zip(projections, frame.radials, strict=True) if p > band_hi + _ON]
    return (
        Mount(seat=seat, axis=direction),
        _Geometry(
            band_top=band_hi - top,
            band_bottom=band_lo - top,
            circumradius=max(frame.radials, default=0.0),
            bore_radius=frame.bore,
            cap_radius=max(past, default=0.0),
            part_name=frame.part.name,
            drawn_af=_drawn_af(frame, fastener),
        ),
    )


def _through(mount: Mount, bolt: Part) -> float:
    """How far past the seat a fastener's partner reaches along its axis, 0 if not past.

    A nut's bolt sticks out of its free face, and a ring comes down over its
    end (issue #121). A hex head's partner, its nut, is on the far side: 0.
    """
    ends = [_dot(_sub(tuple(v), mount.seat), mount.axis) for v in bolt.shape.vertices()]
    return max([0.0, *ends])


def _drawn_af(frame: _Frame, fastener: Fastener) -> float | None:
    """The drive the solid shows, for a rule's forced tool to be held to (issue #72).

    Read only for a fastener whose rule names a tool, since a rule otherwise says
    what its part is outright: reading every solid again would cost a check of a
    model with many described fasteners for nothing.
    """
    if fastener.tool is None or fastener.drive_af is not None:
        return None
    return read_shape(frame.part.shape, fastener.kind, fastener.head).drive_af


def _is_flipped(frame: _Frame, fastener: Fastener, scene: Scene) -> bool:
    """Does the axis point into the joint instead of out of it?"""
    if fastener.kind is Kind.SCREW and fastener.head is Head.SET:
        return _socket_is_at_bottom(frame)
    if fastener.kind is Kind.SCREW:
        return _head_is_at_bottom(frame)
    thread = fastener.size.diameter_mm / 2 if fastener.size is not None else 0.0
    return _free_face_is_at_bottom(frame, scene, thread)


def _head_is_at_bottom(frame: _Frame) -> bool:
    """A screw's head end is its wide end (issue #81).

    Not the end with the larger flat face, as it was: a domed head's only flat is
    a ring round its socket, smaller than a chamfered tip's end, and the key was
    tried from inside the part the screw threads into.
    """
    end = wide_end(frame.projections, frame.radials)
    if end == 0 and frame.pieces:  # a head drawn apart from its shank (issue #96)
        along, out = zip(*frame.pieces, strict=True)
        end = wide_end((*frame.projections, *along), (*frame.radials, *out))
    if end == 0:
        raise NotCovered("cannot tell the head end: both ends look alike")
    return end < 0


def _socket_is_at_bottom(frame: _Frame) -> bool:
    """A set screw is turned from the end its socket is in (issue #96).

    It has no head to say: the socket's walls, flats parallel to the axis facing
    it, sit nearer one end than the other.
    """
    walls = [
        _dot(_sub(face.point, frame.origin), frame.direction)
        for face in frame.faces
        if face.plane
        and abs(_dot(face.normal, frame.direction)) < 1 - _AXIAL
        and _dot(face.normal, _radial_of(face.point, frame)) < 0
    ]
    if not walls:
        raise NotCovered("cannot tell which end its socket is in: no socket in the solid")
    middle = (min(frame.projections) + max(frame.projections)) / 2
    lower = [wall < middle for wall in walls]
    if any(lower) and not all(lower):
        raise NotCovered("cannot tell which end its socket is in: both ends look alike")
    return all(lower)


def _radial_of(point: Vec, frame: _Frame) -> Vec:
    """The direction from the frame's axis out to a point, unnormalised."""
    out = _sub(point, frame.origin)
    return _sub(out, _scale(frame.direction, _dot(out, frame.direction)))


def _free_face_is_at_bottom(frame: _Frame, scene: Scene, thread_radius: float = 0.0) -> bool:
    """A nut's free face is the end no other part sits against.

    Two lessons are built in (bugs A and B in the bench handoff). The probe is an
    annulus, not a disc: the nut's own bolt sticks out of the free side, and a
    disc would read it as covered; the annulus starts just outside the bore,
    which anything threaded through the nut must fit inside, and outside the
    thread's nominal radius too: a nut is often drawn bored at its thread's minor
    diameter and its bolt at the nominal, overlapping, and the bolt read as
    covering both ends. And the probes sit
    at the ends of the widest region (the hex), not of the whole part: a gland's
    thread stub and dome extend past its hex on both sides, so the part's own
    extremes read as free air.

    Both ends clear is a nut drawn off its seat, or with its washer left out
    (issue #26): the probes reach further out from each end in turn
    (:data:`_ROOM_DEPTHS`), and the end with the more room is the free face, the
    other being where the plate is. Open on both sides, either end will do and
    the frame's own direction stands; the same room on both is not covered.
    """
    outer = max(frame.radials) * 0.95
    inner = max(frame.bore, thread_radius) + 0.5
    if inner >= outer:
        raise NotCovered("the bore leaves no face to probe for the free end")
    band_lo, band_hi = _band(frame.projections, frame.radials, frame.flats)
    plane_top = Mount(seat=frame.point_at(band_hi), axis=frame.direction)
    plane_bottom = Mount(seat=frame.point_at(band_lo), axis=_neg(frame.direction))
    top_free = scene.clear(plane_top.place(axial_annulus(inner, outer, 0.1, 1.0)))
    bottom_free = scene.clear(plane_bottom.place(axial_annulus(inner, outer, 0.1, 1.0)))
    if top_free != bottom_free:
        return bottom_free
    if not top_free:
        raise _BothEndsCovered("cannot tell the nut's free face: both ends are covered")
    for depth in _ROOM_DEPTHS:
        top_room = scene.clear(plane_top.place(axial_annulus(inner, outer, 0.1, depth)))
        bottom_room = scene.clear(plane_bottom.place(axial_annulus(inner, outer, 0.1, depth)))
        if top_room != bottom_room:
            return bottom_room
        if not top_room:
            raise NotCovered(
                "cannot tell the nut's free face: both ends are clear, with the same room"
            )
    return False


# ---------------------------------------------------------------------------
# Tool selection: the kit's tools only.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Tools:
    """What a fastener may be tried with: the kit's tools, swung in ``step_deg`` steps."""

    kit: Kit
    step_deg: float
    hand_room: bool = False
    #: The sidecar's own tools (spec 5.3): they join whatever kit is used.
    custom: CustomTools = field(default_factory=CustomTools)

    def need(self, *wanted: str) -> tuple[str, ...]:
        """Those of ``wanted`` the kit or the sidecar holds, in order; not covered when none.

        Raises:
            NotCovered: When the kit holds none of them, naming them and the kit
                that does.
        """
        held = tuple(tool for tool in wanted if self.kit.holds(tool) or tool in self.custom)
        if not held:
            raise NotCovered(missing(wanted, self.kit))
        return held


def _attempts_for(
    fastener: Fastener,
    mount: Mount,
    geometry: _Geometry,
    scene: Scene,
    tools: _Tools,
) -> Iterator[Attempt]:
    if fastener.tool is not None:
        return _forced_attempts(fastener, mount, geometry, scene, tools)
    if fastener.kind is Kind.NUT or fastener.head is Head.HEX:
        return _hex_flats_attempts(fastener, mount, geometry, scene, tools)
    if fastener.head in _KEYED_HEADS:
        return _keyed_attempts(fastener, mount, scene, tools)
    if fastener.head is Head.PHILLIPS:
        return _drivers(f"ph{_phillips(fastener)[0]}", mount, scene, tools)
    if fastener.head is Head.SLOTTED:
        return _drivers("slotted", mount, scene, tools)
    if fastener.head is Head.TORX:
        return _torx_attempts(fastener, mount, scene, tools)
    raise NotCovered("head unknown: name it in the sidecar")


def _by_hand(
    fastener: Fastener, mount: Mount, geometry: _Geometry, scene: Scene, tools: _Tools
) -> Iterator[Attempt]:
    """A thumb screw or wing nut: no tool, but room for fingers at its grip (issue #96).

    The grip is its widest region, from its end down; over a nut's end the fingers
    leave its bolt alone, as anything threaded through it must fit its bore.
    """
    nut = fastener.kind is Kind.NUT
    thread = fastener.size.diameter_mm / 2 if fastener.size is not None else 0.0
    bolt = max(geometry.bore_radius, thread) + 0.5 if nut else 0.0
    return finger_attempts(
        mount,
        scene,
        geometry.circumradius,
        -geometry.band_bottom,
        bolt,
        nut=nut,
        step_deg=tools.step_deg,
        hand_room=tools.hand_room,
    )


def _drivers(tip: str, mount: Mount, scene: Scene, tools: _Tools) -> Iterator[Attempt]:
    """The kit's driver for a tip, then the sidecar's own, each straight in.

    Which the kit and sidecar hold is decided here, before the lazy attempts
    are handed back (see :func:`_hex_flats_attempts`).
    """
    customs = tools.custom.drivers(tip)
    held = tools.need(f"driver-{tip}", *(custom.name for custom in customs))
    return _drivers_held(held, tip, customs, mount, scene, tools)


def _drivers_held(
    held: tuple[str, ...],
    tip: str,
    customs: tuple[CustomDriver, ...],
    mount: Mount,
    scene: Scene,
    tools: _Tools,
) -> Iterator[Attempt]:
    if f"driver-{tip}" in held:
        yield driver_attempt(mount, scene, SHAFT_RADIUS[tip], f"driver-{tip}", tools.hand_room)
    for custom in customs:
        if custom.name in held:
            yield _custom_driver(custom, mount, scene, tools)


def _custom_driver(custom: CustomDriver, mount: Mount, scene: Scene, tools: _Tools) -> Attempt:
    radius, length = custom.shaft_radius, custom.shaft_length
    return driver_attempt(mount, scene, radius, custom.name, tools.hand_room, length)


def _phillips(fastener: Fastener) -> tuple[int, str | None]:
    """The Phillips number a cross takes, and a note where it is drawn for another.

    Its span across its wings, as drawn or as a rule's ``across_flats:`` gives it,
    decides where it sits in one number's range (:data:`PHILLIPS_SPAN`, issue #125),
    as a socket's across flats decides its key: the driver must fit the recess
    drawn. Drawn for another number than its thread's standard gives, it is taken as
    drawn, and noted. Else, or drawn between two numbers' ranges, the thread's
    number, by ISO 7045 and ASME B18.6.3.
    """
    span, size = fastener.drive_af, fastener.size
    by_size = PHILLIPS_NUMBER.get(size.designation) if size is not None else None
    drawn = phillips_by_span(span) if span is not None else None
    if drawn is not None:
        if by_size is None or by_size == drawn:
            return drawn, None
        assert size is not None  # noqa: S101  (by_size came from it)
        return drawn, (
            f"cross drawn for PH{drawn} ({span:.2f} across its wings), where "
            f"{'an' if size.designation.startswith('M') else 'a'} {size.designation}'s "
            f"standard gives PH{by_size}: taken as drawn"
        )
    if by_size is not None:
        return by_size, None
    between = f"a cross {span:.2f} across its wings is no Phillips number's, and " if span else ""
    if size is None:
        raise NotCovered(f"{between}size unknown: name it in the sidecar")
    raise NotCovered(
        f"{between}ISO 7045 and ASME B18.6.3 give no Phillips number for {size.designation}"
    )


def _known_size(fastener: Fastener) -> Size:
    """The size, which a table lookup needs: metric or inch, but known."""
    if fastener.size is None:
        raise NotCovered("size unknown: name it in the sidecar")
    return fastener.size


#: How far under its standard's band a hex may be drawn and still take its own
#: thread's spanner, mm: a model drawn a few tenths small (issue #50), which the
#: result's notes say.
UNDERSIZE_MM = 0.3


def _given_af(
    fastener: Fastener, sizes: tuple[float, ...], family: str, *, bands: bool = False
) -> float | None:
    """The drive's across-flats when measured or given, as a tool size; else None."""
    return _resolve_af(fastener, sizes, family, bands=bands)[0]


def _resolve_af(
    fastener: Fastener, sizes: tuple[float, ...], family: str, *, bands: bool = False
) -> tuple[float | None, str | None]:
    """The drive's across-flats as a tool size, and a note when it was a stretch.

    A measurement is a tool's size within a few hundredths of a millimetre:
    11.11 is a 7/16 in hex and must not become a "spanner-11.11". With
    ``bands`` (a hex a spanner grips), a hex inside a nut standard's band below
    a spanner size takes that spanner: an M8 nut drawn at 12.8 is in ISO 4032's
    12.73 to 13 (issue #27). A known thread keeps to its own system's tools: an
    M8 nut drawn at 12.6 never gets an inch spanner for being nearer one (issue
    #50). In order:

    1. the thread's own standard size, exact or in its band;
    2. the same, drawn up to :data:`UNDERSIZE_MM` under its band: taken, with a
       note saying so;
    3. any tool size of the thread's system the hex exactly is;
    4. the one band of the thread's system that holds it;
    5. a tool size of the other system the hex exactly is: taken, with a note.

    Where two bands hold it and nothing decides (7.85 is in 8 mm's and 5/16
    in's), or none does, it is not covered, and the reason says what fits, or
    names the tool that fits nearest: the smallest spanner over the hex, the
    largest key into a socket, from the thread's own system first.
    """
    if fastener.drive_af is None:
        return None, None
    measured, size = fastener.drive_af, fastener.size
    ours = sizes if size is None else tuple(s for s in sizes if is_inch(s) is not size.is_metric)
    if family == "hex-key":
        return _resolve_key(measured, size, ours, sizes)
    found = _af_among(measured, size, ours, family, bands=bands)
    if found is not None:
        return found
    other = snap(measured, sizes)
    if other is None or size is None:
        raise NotCovered(_no_fit(measured, ours, sizes, family))
    return other, (
        f"hex drawn {measured:.2f} across flats, {'an inch' if is_inch(other) else 'a metric'} "
        f"size, its thread {size.designation}; taken as size {size_name(other)}"
    )


def _af_among(
    measured: float, size: Size | None, sizes: tuple[float, ...], family: str, *, bands: bool
) -> tuple[float, str | None] | None:
    """Steps 1 to 4 of :func:`_resolve_af`, among ``sizes``: None when none takes it."""
    snapped = snap(measured, sizes)
    fits = [s for s in sizes if in_hex_band(measured, s)] if bands else []
    own = standard_hex_afs(size) if bands and size is not None else set()
    ours = [s for s in sizes if s in own and (s == snapped or s in fits)]
    if len(ours) == 1:
        return ours[0], None
    floors = {s: HEX_AF_MIN.get(s, s) for s in sizes if s in own}
    under = [s for s, low in floors.items() if low - UNDERSIZE_MM <= measured < low]
    if len(under) == 1 and size is not None:
        tool, low = under[0], floors[under[0]]
        return tool, (
            f"hex drawn undersize: {measured:.2f} across flats, {low - measured:.2f} under "
            f"the least its {size.designation} standard allows ({low:.2f}); "
            f"taken as size {size_name(tool)}"
        )
    if snapped is not None:
        return snapped, None
    if len(fits) == 1:
        return fits[0], None
    if fits:
        names = " or ".join(f"{family}-{size_name(s)}" for s in fits)
        raise NotCovered(f"{measured:.2f} mm across flats fits {names}: set tool: in the sidecar")
    return None


def _resolve_key(
    measured: float, size: Size | None, ours: tuple[float, ...], sizes: tuple[float, ...]
) -> tuple[float, str | None]:
    """A hex socket's across-flats as a key size, and a note when it was a stretch.

    A key goes into a socket, so a socket is never smaller than its key, and the
    standards draw it a little larger (:data:`RECESS_AF_MAX`): bd_warehouse draws
    every socket at that most, ISO 7380-1's M4 at 2.58 for a 2.5 key (issue #82).
    In order, from the thread's own system (``ours``) first, as for a hex:

    1. a key the socket exactly is, as before (within a few hundredths);
    2. the one key whose standard socket holds it;
    3. the largest key it fits, drawn up to :data:`RECESS_LOOSE_MM` past the
       most: taken, with a note saying so;
    4. a key of the other system it exactly is: taken, with a note.

    Otherwise not covered, naming the largest key that goes in.
    """
    snapped = snap(measured, ours)
    if snapped is not None:
        return snapped, None
    held = [key for key in ours if in_recess_band(measured, key)]
    if len(held) == 1:
        return held[0], None
    loose = [key for key in ours if loosely_fits(measured, key)]
    if not held and loose:
        key = max(loose)
        most = RECESS_AF_MAX.get(key, key)
        return key, (
            f"socket drawn loose: {measured:.2f} across flats, {measured - most:.2f} past the "
            f"most the standards allow a {size_name(key)} key's ({most:g}); "
            f"taken as size {size_name(key)}"
        )
    other = snap(measured, sizes)
    if held or other is None or size is None:
        raise NotCovered(_no_fit(measured, ours, sizes, "hex-key"))
    return other, (
        f"hex drawn {measured:.2f} across flats, {'an inch' if is_inch(other) else 'a metric'} "
        f"size, its thread {size.designation}; taken as size {size_name(other)}"
    )


def _no_fit(measured: float, ours: tuple[float, ...], sizes: tuple[float, ...], family: str) -> str:
    """Why no tool takes a hex, naming the one that fits nearest: never one that doesn't.

    A spanner or socket goes over the hex, so it fits when no smaller; a key
    goes into a socket, so it fits when no larger. The thread's own system
    (``ours``) is looked in first, then every size.
    """
    key = family == "hex-key"

    def fitting_in(among: tuple[float, ...]) -> list[float]:
        return [s for s in among if (s <= measured if key else s >= measured)]

    fitting = fitting_in(ours) or fitting_in(sizes)
    if not fitting:
        extreme = min(sizes) if key else max(sizes)
        return (
            f"{measured:.2f} mm across flats is {'smaller' if key else 'larger'} than any "
            f"{family} the tables hold ({family}-{size_name(extreme)} the "
            f"{'smallest' if key else 'largest'}); set tool: in the sidecar"
        )
    best = max(fitting) if key else min(fitting)
    return (
        f"{measured:.2f} mm across flats is no tool's size: the "
        f"{'largest' if key else 'smallest'} that fits, {family}-{size_name(best)}, is "
        f"{abs(best - measured):.2f} {'smaller' if key else 'larger'}; "
        "set across_flats: or tool: in the sidecar"
    )


def _drive_notes(fastener: Fastener) -> tuple[str, ...]:
    """What a result should say about how its drive was sized, as the attempts sized it.

    A hex drawn undersize, a socket or a Torx recess drawn loose, or either at the
    other system's size: see :func:`_resolve_af` and :func:`_torx_size`.
    """
    if fastener.tool is not None or fastener.drive_af is None:
        return ()
    if fastener.head in (Head.TORX, Head.PHILLIPS):
        sized = _torx_size if fastener.head is Head.TORX else _phillips
        try:
            note = sized(fastener)[1]
        except NotCovered:
            return ()
        return (note,) if note else ()
    if fastener.kind is Kind.NUT or fastener.head is Head.HEX:
        sizes, family, bands = FLATS, "spanner", True
    elif fastener.head in _KEYED_HEADS:
        sizes, family, bands = tuple(HEX_KEYS), "hex-key", False
    else:
        return ()
    try:
        _, note = _resolve_af(fastener, sizes, family, bands=bands)
    except NotCovered:
        return ()
    return (note,) if note else ()


def _keyed_attempts(
    fastener: Fastener, mount: Mount, scene: Scene, tools: _Tools
) -> Iterator[Attempt]:
    af = _key_af(fastener, tools)
    key = HEX_KEYS.get(af)
    ball = BALL_END_KEYS.get(af) if key and fastener.head in _BALL_END_HEADS else None
    customs = tools.custom.hex_keys(af)
    wanted = [k.name for k in (key, ball) if k is not None] + [c.name for c in customs]
    held = tools.need(*wanted)
    return _keys(held, key, ball, customs, mount, scene, tools)


def _key_af(fastener: Fastener, tools: _Tools) -> float:
    """A hex socket's across-flats as a key size: given or measured, else its head's."""
    af = _given_af(fastener, (*HEX_KEYS, *tools.custom.key_sizes()), "hex-key")
    if af is None:
        if fastener.head is None or fastener.size is None:
            raise NotCovered("head or size unknown: name them in the sidecar")
        size = _known_size(fastener)
        af = hex_key_af(fastener.head, size)
        if af is None:
            raise NotCovered(no_such_head(fastener.head, size))
        if af not in HEX_KEYS and not tools.custom.hex_keys(af):
            # Its standard's key, whose L-key no table here holds: an M1.6 set screw's 0.7
            raise NotCovered(missing((f"hex-key-{size_name(af)}",), tools.kit))
    return af


def _keys(
    held: tuple[str, ...],
    key: HexKey | None,
    ball: BallEndKey | None,
    customs: tuple[CustomKey, ...],
    mount: Mount,
    scene: Scene,
    tools: _Tools,
) -> Iterator[Attempt]:
    """The plain key's ways, the ball end's (full kit), then the sidecar's own keys."""
    if key is not None and key.name in held:
        yield from hex_key_attempts(mount, key, scene, tools.step_deg, tools.hand_room)
    if ball is not None and ball.name in held:
        yield from ball_end_attempts(mount, ball, scene, tools.step_deg)
    for custom in customs:
        if custom.name in held:
            yield from hex_key_attempts(mount, custom, scene, tools.step_deg, tools.hand_room)


def _torx_attempts(
    fastener: Fastener, mount: Mount, scene: Scene, tools: _Tools
) -> Iterator[Attempt]:
    """A Torx head: the key its recess or its thread takes, swept as a hex key."""
    torx, _ = _torx_size(fastener)
    key = ISO_10664.get(torx)
    customs = tools.custom.torx_keys(torx)
    if key is None and not customs:
        raise NotCovered(missing((f"torx-key-{torx}",), tools.kit))
    held = tools.need(*([key.name] if key else []), *(custom.name for custom in customs))
    return _torx_keys(held, (*([key] if key else []), *customs), mount, scene, tools)


def _torx_size(fastener: Fastener) -> tuple[str, str | None]:
    """The Torx size a head takes, and a note when it was a stretch.

    A recess's point to point, given as ``across_flats:``, decides it (issue #82):
    the size whose ISO 10664 recess holds it (:data:`TORX_RECESS_A`), or the
    largest it is drawn loosely past, by up to :data:`RECESS_LOOSE_MM`, noted. An
    M8 pan head drawn for T40, as some makers sell it, takes T40, where the
    standards say T45. Else the thread's size, by ISO 14579 and its kin.
    """
    measured = fastener.drive_af
    if measured is None:
        size = _known_size(fastener)
        torx = TORX_SIZE.get(size.designation)
        if torx is None:
            raise NotCovered(no_such_head(Head.TORX, size))
        return torx, None
    held = [t for t, (least, most) in TORX_RECESS_A.items() if least <= measured <= most]
    if held:
        return held[0], None
    loose = [
        t for t, (_, most) in TORX_RECESS_A.items() if most < measured <= most + RECESS_LOOSE_MM
    ]
    if loose:
        torx, most = loose[-1], TORX_RECESS_A[loose[-1]][1]
        return torx, (
            f"Torx recess drawn loose: {measured:.2f} point to point, {measured - most:.2f} past "
            f"the most ISO 10664 allows a {torx} ({most:.3f}); taken as {torx}"
        )
    under = [t for t, (least, _) in TORX_RECESS_A.items() if least <= measured]
    nearest = f"; the largest that fits, {under[-1]}" if under else ""
    raise NotCovered(
        f"{measured:.2f} mm point to point is no Torx recess's size{nearest}; "
        "set tool: in the sidecar"
    )


def _torx_keys(
    held: tuple[str, ...],
    keys: tuple[TorxKey | CustomKey, ...],
    mount: Mount,
    scene: Scene,
    tools: _Tools,
) -> Iterator[Attempt]:
    """The kit's Torx key, then the sidecar's own of the size, each swept as an L-key."""
    for key in keys:
        if key.name in held:
            yield from hex_key_attempts(mount, key, scene, tools.step_deg, tools.hand_room)


def _hex_flats_attempts(
    fastener: Fastener,
    mount: Mount,
    geometry: _Geometry,
    scene: Scene,
    tools: _Tools,
) -> Iterator[Attempt]:
    """Rings, then sockets, those the kit holds; every not-covered reason decided first.

    The reasons are raised here, before the lazy attempts are handed back: one
    raised inside a generator would surface only while the attempts ran, past
    the code that turns it into a verdict (an M3.5 nut, which has no ISO 4032
    row, used to crash the whole check that way).
    """
    af = _flats_af(fastener, tools)
    if geometry.band_height <= _MIN_BAND:
        raise NotCovered("could not measure the hex's height")
    wanted = [f"spanner-{size_name(af)}"]
    if fastener.socket_allowed:  # a cable through it rules out anything that covers it
        wanted.append(f"socket-{size_name(af)}")
        if af in NUT_DRIVERS:
            wanted.append(NUT_DRIVERS[af].name)
    wanted += [custom.name for custom in _custom_flats(af, fastener.socket_allowed, tools)]
    held = tools.need(*wanted)
    return _hex_flats_tools(held, mount, af, geometry, scene, tools)


def _flats_af(fastener: Fastener, tools: _Tools) -> float:
    """The hex's across-flats as a spanner size: given or measured, else its thread's."""
    af = _given_af(fastener, (*FLATS, *tools.custom.flat_sizes()), "spanner", bands=True)
    if af is None:
        size = _known_size(fastener)
        af = spanner_af(size, head=fastener.kind is Kind.SCREW)
        if af is None:
            raise NotCovered(f"no across-flats for {size.designation}")
    return af


def _custom_flats(af: float, socket_allowed: bool, tools: _Tools) -> list[CustomTool]:
    """The sidecar's own spanners, sockets and nut drivers of a size, in its order."""
    covering = tools.custom.sockets(af) + tools.custom.nut_drivers(af) if socket_allowed else ()
    of_size = set(tools.custom.spanners(af)) | set(covering)
    return [tool for tool in tools.custom.tools if tool in of_size]


def _hex_flats_tools(
    held: tuple[str, ...],
    mount: Mount,
    af: float,
    geometry: _Geometry,
    scene: Scene,
    tools: _Tools,
) -> Iterator[Attempt]:
    """Each tool held, the kit's then the sidecar's own; a ring, socket or driver if on.

    First the hex's own corner sweep, alone: something in it stops the hex
    turning whatever grips it, which is said once (:data:`_CORNERS_WAY`), not as
    every tool blocked (issue #63).
    """
    corners = mount.place(corner_sweep(af, (geometry.band_top, geometry.band_bottom)))
    hits = scene.hits(corners)
    if hits:
        yield Attempt(held[0], _CORNERS_WAY, False, False, 0.0, hits, (Probe(corners, hits),))
        return
    spanner = spanner_for(af)
    if spanner.label in held:
        yield from _spanner_ends(spanner, ENDS, mount, af, geometry, scene, tools)
    socket = socket_for(af)
    if socket.label in held:
        yield from _socket_on(socket, mount, af, geometry, scene, tools)
    driver = NUT_DRIVERS.get(af)
    if driver is not None and driver.name in held:
        yield from _nut_driver_on(driver, mount, af, geometry, scene, tools)
    for custom in tools.custom.tools:
        if custom.name not in held:
            continue
        if isinstance(custom, CustomSpanner):
            yield from _spanner_ends(custom.spanner, custom.ends, mount, af, geometry, scene, tools)
        elif isinstance(custom, CustomSocket):
            yield from _socket_on(custom.socket, mount, af, geometry, scene, tools)
        elif isinstance(custom, CustomNutDriver):
            yield from _nut_driver_on(custom.driver, mount, af, geometry, scene, tools)


def _spanner_ends(
    spanner: Spanner,
    ends: tuple[str, ...],
    mount: Mount,
    af: float,
    geometry: _Geometry,
    scene: Scene,
    tools: _Tools,
) -> Iterator[Attempt]:
    """A combination spanner's ring, if it gets on, then its open end."""
    step, hand = tools.step_deg, tools.hand_room
    band = (geometry.band_top, geometry.band_bottom)
    if "ring" in ends:
        if _gets_over(geometry, af):
            yield from ring_attempts(
                mount, spanner, af, band, scene, step, hand, through=geometry.through
            )
        else:  # the ways a ring would try: no stubby where none is made (issue #49)
            ways = _RING_WAYS if spanner.stubby_length is not None else _RING_WAYS[:1]
            yield from _cannot_get_on(mount, af, geometry, spanner.label, ways)
    if "open" in ends:
        yield from open_end_attempts(mount, spanner, af, band, scene, step, hand)


def _socket_on(
    socket: Socket, mount: Mount, af: float, geometry: _Geometry, scene: Scene, tools: _Tools
) -> Iterator[Attempt]:
    """A socket on the ratchet and its extensions, if it gets on."""
    if not _gets_over(geometry, af):
        yield from _cannot_get_on(mount, af, geometry, socket.label, (_SOCKET_WAY,))
        return
    band = (geometry.band_top, geometry.band_bottom)
    yield from socket_attempts(mount, socket, af, band, scene, tools.step_deg, tools.hand_room)


def _nut_driver_on(
    driver: NutDriver, mount: Mount, af: float, geometry: _Geometry, scene: Scene, tools: _Tools
) -> Iterator[Attempt]:
    """A nut driver straight in, if it gets on."""
    if not _gets_over(geometry, af):
        yield from _cannot_get_on(mount, af, geometry, driver.name, (_DRIVER_WAY,))
        return
    band = (geometry.band_top, geometry.band_bottom)
    yield nut_driver_attempt(mount, driver, af, band, scene, tools.hand_room)


#: The way an attempt says the hex's own corners were stopped, turning (issue #63).
_CORNERS_WAY = "its corners, turning"

#: The ways each covering tool tries, as their sweeps name them.
_RING_WAYS = ("ring, full length", "ring, stubby")
_SOCKET_WAY = "socket on ratchet"
_DRIVER_WAY = "nut driver straight in"

#: Points this far past the band are past it, mm: not the band's own edge.
_ON = 1e-6


def _gets_over(geometry: _Geometry, af: float) -> bool:
    """Whether a ring's or socket's bore, round the hex's corners, passes the part past it.

    A ring or socket goes on along the axis, over whatever the part has between
    its hex and its free end: a gland's dome wider than that bore keeps them off,
    and only an open end, from the side, grips the hex (issue #47).
    """
    return geometry.cap_radius <= af / math.sqrt(3) + RING_CLEARANCE + _ON


def _cannot_get_on(
    mount: Mount, af: float, geometry: _Geometry, tool: str, ways: tuple[str, ...]
) -> Iterator[Attempt]:
    """Each way a covering tool would try, failed on the part's own body past its hex."""
    inner = af / math.sqrt(3) + RING_CLEARANCE
    path = mount.place(
        axial_annulus(inner, geometry.cap_radius, geometry.band_top, -geometry.band_top)
    )
    own = (geometry.part_name,)
    for way in ways:
        yield Attempt(tool, way, False, False, 0.0, own, (Probe(path, own),))


def _forced_attempts(
    fastener: Fastener,
    mount: Mount,
    geometry: _Geometry,
    scene: Scene,
    tools: _Tools,
) -> Iterator[Attempt]:
    """A sidecar `tool:` name: hex-key-5, spanner-10, socket-7/16in, driver-ph2.

    A forced tool must still be in the kit: the sidecar picks which tool, the
    kit says which tools there are.
    """
    name = fastener.tool or ""
    if name == HAND:  # turned by hand: room for fingers, not a tool (issue #96)
        return _by_hand(fastener, mount, geometry, scene, tools)
    misfit = _forced_misfit(fastener, name, tools, geometry.drawn_af)
    if misfit is not None:
        raise NotCovered(misfit)
    custom = tools.custom.by_name.get(name)
    if custom is not None:
        return _forced_custom(custom, mount, geometry, scene, tools)
    for family_attempts in (_forced_key, _forced_flats, _forced_driver):
        attempts = family_attempts(name, mount, geometry, scene, tools)
        if attempts is not None:
            return attempts
    raise NotCovered(f"unknown tool {name!r}")


#: A head's drive (flats, key, torx, phillips, slotted) and what it's called in a reason.
_HEAD_DRIVES = {
    Head.HEX: ("flats", "hex head"),
    Head.SOCKET: ("key", "socket head"),
    Head.BUTTON: ("key", "button head"),
    Head.FLAT: ("key", "countersunk head"),
    Head.SHOULDER: ("key", "shoulder screw's head"),
    Head.SET: ("key", "set screw"),
    Head.TORX: ("torx", "Torx head"),
    Head.PHILLIPS: ("phillips", "Phillips head"),
    Head.SLOTTED: ("slotted", "slotted head"),
}

#: The tool families a rule's ``tool:`` names, by the drive each fits: a hex's flats,
#: a hex socket, a Torx recess; and what each is called in a reason.
_TOOL_FAMILIES = {
    "spanner": ("flats", "a spanner"),
    "socket": ("flats", "a socket"),
    "nut-driver": ("flats", "a nut driver"),
    "hex-key": ("key", "a hex key"),
    "torx-key": ("torx", "a Torx key"),
}

#: A drive, or what a tool fits: its kind (flats, key, torx, phillips, slotted), its
#: size (across flats in mm, a Torx or Phillips size; None when not known), its words.
_Drive = tuple[str, float | str | None, str]


def _forced_misfit(
    fastener: Fastener, name: str, tools: _Tools, drawn_af: float | None
) -> str | None:
    """Why a rule's ``tool:`` can't drive its fastener, if it can't (issue #72).

    The sidecar picks which tool, but it must be one the fastener takes: the kind
    its drive takes, at a size it takes, either the one the unforced check would
    choose (a given hex, else the thread's standard one) or the hex the solid shows.
    Unchecked, a typo passed (spanner-10 on a 13 mm hex) and a key was swept into a
    nut's bore. A tool the tables don't hold is left to say so itself, and where no
    size is known only the kind is held to.
    """
    tool, drive = _tool_drive(name, tools), _fastener_drive(fastener, tools)
    if tool is None or drive is None:
        return None
    (tool_kind, tool_size, called), (kind, size, what) = tool, drive
    if tool_kind != kind:
        return f"its tool: {name} is {called}, which doesn't fit {what}"
    drawn = _drawn_size(kind, fastener, tools, drawn_af)
    takes = [s for s in (size, drawn) if s is not None]
    if tool_size is None or not takes or any(_same_size(tool_size, s) for s in takes):
        return None
    if isinstance(tool_size, float):
        mine, theirs = size_name(tool_size), size_name(float(takes[0]))
        also = f", its hex drawn {size_name(drawn)}" if isinstance(drawn, float) and size else ""
        return (
            f"its tool: {name} is {mine} across flats, but {what} takes {theirs}{also}; "
            f"give its rule across_flats: {mine} if its hex really is {mine}"
        )
    return f"its tool: {name} is {str(tool_size).upper()}, but {what} takes {str(takes[0]).upper()}"


def _drawn_size(
    kind: str, fastener: Fastener, tools: _Tools, drawn_af: float | None
) -> float | None:
    """The tool size the solid's own hex resolves to, as an unforced check would take it."""
    if drawn_af is None or kind not in {"flats", "key"}:
        return None
    drawn = replace(fastener, drive_af=drawn_af)
    size = _quietly(_flats_af if kind == "flats" else _key_af, drawn, tools)
    return None if size is None or size == _drive_size(kind, fastener, tools) else size


def _same_size(a: float | str, b: float | str) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, abs_tol=0.01)
    return str(a).lower() == str(b).lower()


def _tool_drive(name: str, tools: _Tools) -> _Drive | None:
    """What a tool fits, by its name or the sidecar's own; None for no tool known."""
    custom = tools.custom.by_name.get(name)
    if custom is not None:
        return _custom_drive(custom)
    family, _, size_text = name.rpartition("-")
    if family == "driver":
        return _tip_drive(size_text) if size_text in SHAFT_RADIUS else None
    if family not in _TOOL_FAMILIES:
        return None
    kind, called = _TOOL_FAMILIES[family]
    if kind == "torx":
        return (kind, size_text, called) if size_text in ISO_10664 else None
    try:
        af = size_mm(size_text)
    except ValueError:
        return None  # not a size: the forced tool is reported unknown
    tables = {"hex-key": HEX_KEYS, "nut-driver": NUT_DRIVERS}.get(family, FLATS)
    return (kind, af, called) if af in tables else None  # else the table says so


def _unused_tools(fasteners: list[Fastener], tools: _Tools) -> list[str]:
    """The sidecar's own tools no fastener here takes and no rule names (issue #75).

    Not one that was never tried: the kit's own tool goes first, and a custom one
    of the same size waits behind it. One of a kind and size no fastener takes is
    one written wrong, most often its size, and a run that never says so would
    leave it looking used. Noted, not failed: one sidecar may serve several models.
    """
    named = {fastener.tool for fastener in fasteners if fastener.tool}
    drives = [drive for f in fasteners if (drive := _fastener_drive(f, tools)) is not None]
    unused = []
    for custom in tools.custom.tools:
        kind, size, called = _custom_drive(custom)
        taken = any(
            k == kind and (size is None or s is None or _same_size(size, s)) for k, s, _ in drives
        )
        if custom.name not in named and not taken:
            unused.append(f"tool {custom.name}: no fastener here takes {_sized(called, size)}")
    return unused


def _sized(called: str, size: float | str | None) -> str:
    """A tool as a sentence names it with its size: ``a 7 mm hex key``, ``a T30 Torx key``."""
    if size is None:
        return called
    noun = called.removeprefix("a ")
    if isinstance(size, float):
        return f"a {size_name(size)}{'' if is_inch(size) else ' mm'} {noun}"
    return f"a {str(size).upper()} {noun}"


def _tip_drive(tip: str) -> _Drive:
    """What a driver of a tip fits: a slot, or a Phillips recess of its number."""
    if tip == "slotted":
        return "slotted", None, "a slotted driver"
    return "phillips", tip, "a Phillips driver"


def _custom_drive(custom: CustomTool) -> _Drive:
    """What a sidecar's own tool fits."""
    if isinstance(custom, CustomKey):
        torx = custom.kind == "torx-key"
        return ("torx", custom.size, "a Torx key") if torx else ("key", custom.af, "a hex key")
    if isinstance(custom, CustomSpanner):
        return "flats", custom.spanner.af, "a spanner"
    if isinstance(custom, CustomSocket):
        return "flats", custom.socket.af, "a socket"
    if isinstance(custom, CustomDriver):
        return _tip_drive(custom.tip)
    return "flats", custom.driver.af, "a nut driver"


def _fastener_drive(fastener: Fastener, tools: _Tools) -> _Drive | None:
    """What drives a fastener, and at what size if known; None when its head isn't."""
    if fastener.kind is Kind.NUT:
        kind, what = "flats", "nut"
    elif fastener.head in _HEAD_DRIVES:
        kind, what = _HEAD_DRIVES[fastener.head]
    else:
        return None
    return kind, _drive_size(kind, fastener, tools), _called(f"the {what}", fastener.size)


def _drive_size(kind: str, fastener: Fastener, tools: _Tools) -> float | str | None:
    """The size the unforced check would choose for a drive; None where it couldn't."""
    if kind == "flats":
        return _quietly(_flats_af, fastener, tools)
    if kind == "key":
        return _quietly(_key_af, fastener, tools)
    if kind not in ("torx", "phillips"):
        return None
    try:
        if kind == "torx":
            return _torx_size(fastener)[0]  # its recess's, where given (issue #82)
        return f"ph{_phillips(fastener)[0]}"  # its cross's, where drawn (issue #125)
    except NotCovered:
        return None


def _called(what: str, size: Size | None) -> str:
    return what if size is None else f"{what} ({size.designation})"


def _quietly(
    size_of: Callable[[Fastener, _Tools], float], fastener: Fastener, tools: _Tools
) -> float | None:
    """A drive's size, or None where the unforced check couldn't say one."""
    try:
        return size_of(fastener, tools)
    except NotCovered:
        return None


def _forced_custom(
    custom: CustomTool, mount: Mount, geometry: _Geometry, scene: Scene, tools: _Tools
) -> Iterator[Attempt]:
    """A sidecar's own tool, named by a rule's ``tool:``: swept as its kind is."""
    if isinstance(custom, CustomKey):
        return hex_key_attempts(mount, custom, scene, tools.step_deg, tools.hand_room)
    if isinstance(custom, CustomDriver):
        return iter([_custom_driver(custom, mount, scene, tools)])
    if geometry.band_height <= _MIN_BAND:
        raise NotCovered("could not measure the hex's height")
    if isinstance(custom, CustomSpanner):
        af = custom.spanner.af
    elif isinstance(custom, CustomSocket):
        af = custom.socket.af
    else:
        af = custom.driver.af
    return _hex_flats_tools((custom.name,), mount, af, geometry, scene, tools)


def _forced_key(
    name: str, mount: Mount, geometry: _Geometry, scene: Scene, tools: _Tools
) -> Iterator[Attempt] | None:
    """hex-key-5, hex-key-5/32in, torx-key-T30; None for another family."""
    del geometry  # the keys need only the mount
    family, _, size_text = name.rpartition("-")
    if family == "hex-key":
        key = HEX_KEYS.get(_tool_mm(size_text, name))
        if key is None:
            raise NotCovered(f"no ISO 2936 or ASME B18.3 key sized {size_text}")
        tools.need(key.name)
        return hex_key_attempts(mount, key, scene, tools.step_deg, tools.hand_room)
    if family == "torx-key":
        torx_key = ISO_10664.get(size_text)
        if torx_key is None:
            raise NotCovered(f"no Torx key {size_text}: the tables hold T10 to T40")
        tools.need(name)
        return hex_key_attempts(mount, torx_key, scene, tools.step_deg, tools.hand_room)
    return None


def _forced_flats(
    name: str, mount: Mount, geometry: _Geometry, scene: Scene, tools: _Tools
) -> Iterator[Attempt] | None:
    """spanner-13, socket-7/16in, nut-driver-10; None for another family."""
    family, _, size_text = name.rpartition("-")
    if family not in {"spanner", "socket", "nut-driver"}:
        return None
    if geometry.band_height <= _MIN_BAND:
        raise NotCovered("could not measure the hex's height")
    if family == "nut-driver":
        nut_driver = NUT_DRIVERS.get(_tool_mm(size_text, name))
        if nut_driver is None:
            raise NotCovered(f"no nut driver sized {size_text}: the tables hold 5.5 to 13")
        tools.need(name)
        return _hex_flats_tools((name,), mount, nut_driver.af, geometry, scene, tools)
    af = _tool_mm(size_text, name)
    tools.need(name)
    return _hex_flats_tools((name,), mount, af, geometry, scene, tools)


def _forced_driver(
    name: str, mount: Mount, geometry: _Geometry, scene: Scene, tools: _Tools
) -> Iterator[Attempt] | None:
    """driver-ph2, driver-slotted; None for another family."""
    del geometry  # a driver needs only the mount
    family, _, size_text = name.rpartition("-")
    if family != "driver":
        return None
    radius = SHAFT_RADIUS.get(size_text)
    if radius is None:
        raise NotCovered(f"unknown driver {size_text!r}")
    tools.need(name)
    return iter([driver_attempt(mount, scene, radius, name, tools.hand_room)])


def _tool_mm(text: str, tool: str) -> float:
    """A tool name's size in mm: ``13``, ``7/16in``; not covered when it isn't one."""
    try:
        return size_mm(text)
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
