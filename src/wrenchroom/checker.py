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
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING

from build123d import GeomType

from wrenchroom.assembly import Assembly, Part
from wrenchroom.config import Config, ConfigError, is_mate
from wrenchroom.detect import find
from wrenchroom.engine import DEFAULT_ENGINE, ENGINES, Engine, Scene, make_engine
from wrenchroom.fasteners import (
    PHILLIPS_NUMBER,
    TORX_SIZE,
    Fastener,
    Head,
    Kind,
    PassedOver,
    Size,
    hex_key_af,
    in_hex_band,
    spanner_af,
    standard_hex_afs,
)
from wrenchroom.report import FastenerResult, Report, StateModel, Verdict
from wrenchroom.tools.ball_end import BALL_END_KEYS, BallEndKey, ball_end_attempts
from wrenchroom.tools.drivers import SHAFT_RADIUS, driver_attempt
from wrenchroom.tools.hex_keys import HEX_KEYS, HexKey, hex_key_attempts
from wrenchroom.tools.kits import DEFAULT_KIT, Kit, kit_named, missing
from wrenchroom.tools.nut_drivers import NUT_DRIVERS, nut_driver_attempt
from wrenchroom.tools.sizes import FLATS, size_mm, size_name, snap
from wrenchroom.tools.sockets import socket_attempts, socket_for
from wrenchroom.tools.spanners import open_end_attempts, ring_attempts, spanner_for
from wrenchroom.tools.sweep import (
    DEFAULT_STEP_DEG,
    Attempt,
    Mount,
    Probe,
    axial_annulus,
    axial_cylinder,
)
from wrenchroom.tools.torx_keys import ISO_10664

if TYPE_CHECKING:
    from collections.abc import Iterator

    from build123d import Axis

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

_KEYED_HEADS = (Head.SOCKET, Head.BUTTON, Head.FLAT)

Vec = tuple[float, float, float]


class NotCovered(Exception):  # noqa: N818  (it is a verdict carrier, not an error suffix)
    """Raised inside the loop when a fastener can't be understood; becomes the verdict."""


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
    tools = _Tools(kit_named(kit), step_deg, config.hand_room if hand_room is None else hand_room)
    if engine not in ENGINES:
        msg = f"unknown engine {engine!r}; available: {', '.join(ENGINES)}"
        raise ValueError(msg)
    default_state = state if state is not None else config.default_state
    if default_state is not None:
        config.state(default_state)  # raises on a typo
    matches = config.apply(assembly)
    fasteners, passed_over = _fasteners(assembly, config, matches.fasteners, only)
    # A narrowing glob that picks nothing checks nothing: as with a sidecar rule
    # that matches nothing, that is how a renamed part hides, so the run says so
    # and exits 2 rather than passing (issue #20).
    only_warnings = (
        [f"only glob {only!r} matched no fastener (renamed part?)"]
        if only is not None and not fasteners
        else []
    )
    # A mate that names nothing leaves its part in the scene, and the fastener
    # blocked by the very part it was told it may touch (issue #32).
    only_warnings += [
        f"rule {parts!r}: mate glob {glob!r} matched nothing (renamed part?)"
        for parts, glob in matches.unmatched_mates
    ]

    space = _StateSpace(assembly, config, model_dir, make_engine(engine))
    frames: dict[str, _Frame] = {}
    failures: dict[str, str] = {}
    for fastener in fasteners:
        if fastener.not_covered is not None:
            failures[fastener.name] = fastener.not_covered
            continue
        try:
            frames[fastener.name] = _frame(assembly[fastener.name], fastener)
        except NotCovered as exc:
            failures[fastener.name] = str(exc)
    pairs, pair_warnings = _find_pairs(fasteners, frames, config)

    candidates: list[_Candidate] = []
    for fastener in fasteners:
        if fastener.name in failures:
            candidates.append(_Candidate(fastener, reason=failures[fastener.name]))
            continue
        candidates.append(
            _check_fastener(fastener, frames[fastener.name], space, config, default_state, tools)
        )
    results = _resolve_joints(candidates, pairs)
    models = {None: StateModel(assembly), **space.models}
    return Report(
        model=model,
        kit=kit,
        engine=engine,
        results=tuple(results),
        unmatched_rules=tuple(rule.parts for rule in matches.unmatched_rules),
        unmatched_ignores=matches.unmatched_ignores,
        warnings=tuple(only_warnings + pair_warnings + space.warnings),
        passed_over=passed_over,
        default_state=default_state,
        hand_room=tools.hand_room,
        models=models,
        ignored=frozenset(
            name
            for state_model in models.values()
            for name in state_model.assembly.names
            if config.is_ignored(name)
        ),
    )


def _fasteners(
    assembly: Assembly, config: Config, described: tuple[Fastener, ...], only: str | None
) -> tuple[list[Fastener], tuple[PassedOver, ...]]:
    """The sidecar's fasteners, plus what detection finds among the parts it doesn't name.

    A rule that matches a part describes it outright: detection only ever sees
    parts no rule covers, and never an ignored one. What detection passed over
    (named like a fastener, no drive in the solid) comes back with them.
    """
    found = list(described)
    passed: tuple[PassedOver, ...] = ()
    if config.detect:
        named = {f.name for f in described}
        detection = find(
            part for part in assembly if part.name not in named and not config.is_ignored(part.name)
        )
        found += detection.fasteners
        passed = detection.passed_over
    found.sort(key=lambda f: f.name)
    if only is not None:
        found = [f for f in found if fnmatchcase(f.name, only)]
        passed = tuple(p for p in passed if fnmatchcase(p.name, only))
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

    @property
    def extent(self) -> float:
        return max(self.projections) - min(self.projections)

    def point_at(self, t: float) -> Vec:
        return _add(self.origin, _scale(self.direction, t))


def _frame(part: Part, fastener: Fastener) -> _Frame:
    direction = _axis_direction(part, fastener)
    origin, vertices = _axis_frame(part, direction)
    projections = tuple(_dot(_sub(v, origin), direction) for v in vertices)
    radials = tuple(_radial(_sub(v, origin), direction) for v in vertices)
    return _Frame(
        part=part,
        direction=direction,
        origin=origin,
        projections=projections,
        radials=radials,
        bore=_bore_radius(part, direction),
        oriented=isinstance(fastener.axis, tuple),
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


def _band(projections: tuple[float, ...], radials: tuple[float, ...]) -> tuple[float, float]:
    """The widest region's extent along the axis: where a spanner or ring grips."""
    widest = max(radials, default=0.0)
    heights = [p for p, r in zip(projections, radials, strict=True) if r > 0.75 * widest]
    if not heights:
        return (0.0, 0.0)
    return (min(heights), max(heights))


def _bore_radius(part: Part, direction: Vec) -> float:
    """The smallest coaxial cylinder: a nut's bore, a gland's cable way; 0 if none."""
    radii = [
        radius
        for face in part.shape.faces().filter_by(GeomType.CYLINDER)
        if (axis := face.axis_of_rotation) is not None
        and abs(_dot(tuple(axis.direction), direction)) > _AXIAL
        and (radius := face.radius) is not None
    ]
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
    nuts = [f for f in fasteners if f.kind is Kind.NUT and f.name in frames]
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
    band_lo, band_hi = _band(nut.projections, nut.radials)
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
        self.engine = engine
        self.warnings: list[str] = []
        #: Every state resolved so far, as the check saw it: kept for the report,
        #: whose HTML view draws a fastener in the state it was reached in.
        self.models: dict[str, StateModel] = {}

    def scene(self, assembly: Assembly, excluded: set[str] | frozenset[str]) -> Scene:
        """The obstacles: every part but the excluded and the ignored ones."""
        return self.engine.scene(
            part for part in assembly if part.name not in excluded and not self._is_ignored(part)
        )

    def _is_ignored(self, part: Part) -> bool:
        # Memoised: the ignore globs are tried once per name, not once per scene.
        ignored = self._ignored.get(part.name)
        if ignored is None:
            ignored = self._ignored[part.name] = self._config.is_ignored(part.name)
        return ignored

    def resolve(self, state_name: str | None) -> tuple[Assembly, frozenset[str], bool]:
        """The assembly a state sees, its removed names, and whether it is the default."""
        if state_name is None:
            return self._default, frozenset(), True
        model = self._config.state_model(state_name)
        assembly = self._default if model is None else self._load(model)
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

    def _load(self, filename: str) -> Assembly:
        if filename not in self._models:
            if self._model_dir is None:
                msg = f"state model {filename!r} needs a model directory to load from"
                raise ConfigError(msg)
            self._models[filename] = Assembly.from_step(self._model_dir / filename)
        return self._models[filename]


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


def _check_fastener(
    fastener: Fastener,
    frame: _Frame,
    space: _StateSpace,
    config: Config,
    default_state: str | None,
    tools: _Tools,
) -> _Candidate:
    own_state = fastener.state if fastener.state is not None else default_state
    order: list[str | None] = [own_state]
    order += [s for s in config.try_states if s != own_state]
    first: _Candidate | None = None
    for index, state_name in enumerate(order):
        candidate = _try_in_state(fastener, frame, state_name, space, tools)
        if first is None:
            first = candidate
        if candidate.reason is not None and index == 0:
            return candidate  # not understood; another state won't change that
        if candidate.turns and not candidate.stuck:
            return candidate
        if fastener.self_holding:
            return candidate
    assert first is not None  # noqa: S101  (order always has at least own_state)
    return first


def _try_in_state(
    fastener: Fastener,
    default_frame: _Frame,
    state_name: str | None,
    space: _StateSpace,
    tools: _Tools,
) -> _Candidate:
    assembly, removed, same_model = space.resolve(state_name)
    if fastener.name not in assembly.names:
        return _Candidate(fastener, reason=f"not present in state {state_name!r}", state=state_name)
    frame = default_frame
    if not same_model:  # parts may have moved: measure this model's own copy
        try:
            frame = _frame(assembly[fastener.name], fastener)
        except NotCovered as exc:
            return _Candidate(fastener, reason=str(exc), state=state_name)
    mates = {name for name in assembly.names if is_mate(name, fastener.mates)}
    scene = space.scene(assembly, {fastener.name, *mates} | removed)
    try:
        mount, geometry = _orient(frame, fastener, scene)
    except NotCovered as exc:
        return _Candidate(fastener, reason=str(exc), state=state_name)
    candidate = _Candidate(fastener, axis=mount.axis, seat=mount.seat, state=state_name)
    if fastener.self_holding:
        candidate.how = "holds itself"
        return candidate
    try:
        attempts_iter = _attempts_for(fastener, mount, geometry, scene, tools)
        _run_attempts(candidate, attempts_iter)
    except NotCovered as exc:  # also any a lazy attempt raises while running
        candidate.reason = str(exc)
        return candidate
    if fastener.kind is Kind.SCREW and (candidate.turns or candidate.hold):
        candidate.way_out = _way_out(fastener, frame, geometry, mount, scene)
        candidate.extraction_blocked = candidate.way_out.hits if candidate.way_out else ()
        if candidate.turns and candidate.extraction_blocked:
            candidate.stuck = True
            candidate.stuck_on = candidate.extraction_blocked
    return candidate


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
            break
    candidate.attempts = tuple(tried)
    if not candidate.turns:
        candidate.tool = (
            candidate.hold.tool if candidate.hold else (tried[0].tool if tried else None)
        )
        candidate.swing_deg = max((a.swing_deg for a in tried), default=0.0)
        candidate.no_hand_room = _hand_blockers(tried)
        hand = candidate.no_hand_room
        candidate.blockers = tuple(blockers) + tuple(n for n in hand if n not in blockers)


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
    swept = mount.place(axial_cylinder(geometry.circumradius, 0.0, length))
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


def _finish(
    candidate: _Candidate, partner_name: str | None, partner: _Candidate | None
) -> FastenerResult:
    fastener = candidate.fastener
    verdict = Verdict.BLOCKED
    tool, how, reason = candidate.tool, candidate.how, candidate.reason
    stuck_on: tuple[str, ...] = ()
    if candidate.reason is not None:
        verdict, how = Verdict.NOT_COVERED, None
    elif fastener.self_holding:
        verdict, tool = Verdict.HELD, None
    elif candidate.stuck:
        verdict, stuck_on = Verdict.STUCK, candidate.stuck_on
    elif candidate.turns:
        verdict = Verdict.TURNS
    elif candidate.hold is not None and _partner_turns(partner):
        tool, how = candidate.hold.tool, candidate.hold.way
        if candidate.extraction_blocked:
            verdict, stuck_on = Verdict.STUCK, candidate.extraction_blocked
        else:
            verdict = Verdict.HELD
    elif candidate.hold is not None:
        how = None
        reason = "only holds, and " + (
            f"its partner {partner_name} does not turn" if partner_name else "it has no nut"
        )
    else:
        how = None
        if candidate.no_hand_room:
            reason = f"no room for a hand ({', '.join(candidate.no_hand_room)} in the way)"
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
    band_lo, band_hi = _band(projections, frame.radials)
    return (
        Mount(seat=seat, axis=direction),
        _Geometry(
            band_top=band_hi - top,
            band_bottom=band_lo - top,
            circumradius=max(frame.radials, default=0.0),
            bore_radius=frame.bore,
        ),
    )


def _is_flipped(frame: _Frame, fastener: Fastener, scene: Scene) -> bool:
    """Does the axis point into the joint instead of out of it?"""
    if fastener.kind is Kind.SCREW:
        return _head_is_at_bottom(frame.part, frame.direction)
    return _free_face_is_at_bottom(frame, scene)


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


def _free_face_is_at_bottom(frame: _Frame, scene: Scene) -> bool:
    """A nut's free face is the end no other part sits against.

    Two lessons are built in (bugs A and B in the bench handoff). The probe is an
    annulus, not a disc: the nut's own bolt sticks out of the free side, and a
    disc would read it as covered; the annulus starts just outside the bore,
    which anything threaded through the nut must fit inside. And the probes sit
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
    inner = frame.bore + 0.5
    if inner >= outer:
        raise NotCovered("the bore leaves no face to probe for the free end")
    band_lo, band_hi = _band(frame.projections, frame.radials)
    plane_top = Mount(seat=frame.point_at(band_hi), axis=frame.direction)
    plane_bottom = Mount(seat=frame.point_at(band_lo), axis=_neg(frame.direction))
    top_free = scene.clear(plane_top.place(axial_annulus(inner, outer, 0.1, 1.0)))
    bottom_free = scene.clear(plane_bottom.place(axial_annulus(inner, outer, 0.1, 1.0)))
    if top_free != bottom_free:
        return bottom_free
    if not top_free:
        raise NotCovered("cannot tell the nut's free face: both ends are covered")
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

    def need(self, *wanted: str) -> tuple[str, ...]:
        """Those of ``wanted`` the kit holds, in order; not covered when it holds none.

        Raises:
            NotCovered: When the kit holds none of them, naming them and the kit
                that does.
        """
        held = tuple(tool for tool in wanted if self.kit.holds(tool))
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
        size = _known_size(fastener)
        number = PHILLIPS_NUMBER.get(size.designation)
        if number is None:
            raise NotCovered(f"no Phillips number for {size.designation}")
        (tool,) = tools.need(f"driver-ph{number}")
        radius = SHAFT_RADIUS[f"ph{number}"]
        return iter([driver_attempt(mount, scene, radius, tool, tools.hand_room)])
    if fastener.head is Head.SLOTTED:
        (tool,) = tools.need("driver-slotted")
        radius = SHAFT_RADIUS["slotted"]
        return iter([driver_attempt(mount, scene, radius, tool, tools.hand_room)])
    if fastener.head is Head.TORX:
        return _torx_attempts(fastener, mount, scene, tools)
    raise NotCovered("head unknown: name it in the sidecar")


def _known_size(fastener: Fastener) -> Size:
    """The size, which a table lookup needs: metric or inch, but known."""
    if fastener.size is None:
        raise NotCovered("size unknown: name it in the sidecar")
    return fastener.size


def _given_af(
    fastener: Fastener, sizes: tuple[float, ...], family: str, *, bands: bool = False
) -> float | None:
    """The drive's across-flats when measured or given, as a tool size; else None.

    A measurement is the tool size nearest it, within a few hundredths of a
    millimetre: 11.11 is a 7/16 in hex and must not become a "spanner-11.11", and
    19.05 is 3/4 in, not 19 mm. With ``bands`` (a hex a spanner grips), a hex
    inside a nut standard's band below a spanner size also takes that spanner:
    an M8 nut drawn at 12.8 is in ISO 4032's 12.73 to 13 (issue #27). In order:
    the thread's own standard size, exact or in its band (an M8 nut at 12.73 is
    in 13's band, though a few hundredths from 1/2 in); then any tool size the
    measurement is; then the one band that holds it. Where two bands hold it and
    nothing decides (7.85 is in 8 mm's and 5/16 in's), or none does, it is not
    covered, and the reason says what fits or names the nearest.
    """
    if fastener.drive_af is None:
        return None
    measured = fastener.drive_af
    snapped = snap(measured, sizes)
    fits = [size for size in sizes if in_hex_band(measured, size)] if bands else []
    own = standard_hex_afs(fastener.size) if bands and fastener.size is not None else set()
    ours = [size for size in sizes if size in own and (size == snapped or size in fits)]
    if len(ours) == 1:
        return ours[0]
    if snapped is not None:
        return snapped
    if len(fits) == 1:
        return fits[0]
    if fits:
        names = " or ".join(f"{family}-{size_name(size)}" for size in fits)
        raise NotCovered(f"{measured:.2f} mm across flats fits {names}: set tool: in the sidecar")
    nearest = min(sizes, key=lambda size: abs(size - measured))
    side = "larger" if nearest > measured else "smaller"
    raise NotCovered(
        f"{measured:.2f} mm across flats is no tool's size: the nearest, "
        f"{family}-{size_name(nearest)}, is {abs(nearest - measured):.2f} {side}; "
        "set across_flats: or tool: in the sidecar"
    )


def _keyed_attempts(
    fastener: Fastener, mount: Mount, scene: Scene, tools: _Tools
) -> Iterator[Attempt]:
    af = _given_af(fastener, tuple(HEX_KEYS), "hex-key")
    if af is None:
        if fastener.head is None or fastener.size is None:
            raise NotCovered("head or size unknown: name them in the sidecar")
        size = _known_size(fastener)
        af = hex_key_af(fastener.head, size)
        if af is None or af not in HEX_KEYS:
            head = fastener.head.value
            raise NotCovered(f"no standard key for a {size.designation} {head} head")
    key = HEX_KEYS[af]
    ball = BALL_END_KEYS.get(af)
    held = tools.need(key.name, *([ball.name] if ball else []))
    return _keys(held, key, ball, mount, scene, tools)


def _keys(
    held: tuple[str, ...],
    key: HexKey,
    ball: BallEndKey | None,
    mount: Mount,
    scene: Scene,
    tools: _Tools,
) -> Iterator[Attempt]:
    """The plain key's three ways, then (full kit) the ball end leant off the axis."""
    if key.name in held:
        yield from hex_key_attempts(mount, key, scene, tools.step_deg, tools.hand_room)
    if ball is not None and ball.name in held:
        yield from ball_end_attempts(mount, ball, scene, tools.step_deg)


def _torx_attempts(
    fastener: Fastener, mount: Mount, scene: Scene, tools: _Tools
) -> Iterator[Attempt]:
    """A Torx head: the key its thread takes (ISO 14579 and kin), swept as a hex key."""
    size = _known_size(fastener)
    torx = TORX_SIZE.get(size.designation)
    if torx is None:
        raise NotCovered(f"no Torx size for a {size.designation} head")
    key = ISO_10664.get(torx)
    if key is None:
        raise NotCovered(missing((f"torx-key-{torx}",), tools.kit))
    tools.need(key.name)
    return hex_key_attempts(mount, key, scene, tools.step_deg, tools.hand_room)


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
    af = _given_af(fastener, FLATS, "spanner", bands=True)
    if af is None:
        size = _known_size(fastener)
        af = spanner_af(size, head=fastener.kind is Kind.SCREW)
        if af is None:
            raise NotCovered(f"no across-flats for {size.designation}")
    if geometry.band_height <= _MIN_BAND:
        raise NotCovered("could not measure the hex's height")
    band = (geometry.band_top, geometry.band_bottom)
    wanted = [f"spanner-{size_name(af)}"]
    if fastener.socket_allowed:  # a cable through it rules out anything that covers it
        wanted.append(f"socket-{size_name(af)}")
        if af in NUT_DRIVERS:
            wanted.append(NUT_DRIVERS[af].name)
    held = tools.need(*wanted)
    return _hex_flats_tools(held, mount, af, band, scene, tools)


def _hex_flats_tools(
    held: tuple[str, ...],
    mount: Mount,
    af: float,
    band: tuple[float, float],
    scene: Scene,
    tools: _Tools,
) -> Iterator[Attempt]:
    step, hand = tools.step_deg, tools.hand_room
    if f"spanner-{size_name(af)}" in held:
        yield from ring_attempts(mount, spanner_for(af), af, band, scene, step, hand)
        yield from open_end_attempts(mount, spanner_for(af), af, band, scene, step, hand)
    if f"socket-{size_name(af)}" in held:
        yield from socket_attempts(mount, socket_for(af), af, scene, step, hand)
    driver = NUT_DRIVERS.get(af)
    if driver is not None and driver.name in held:
        yield nut_driver_attempt(mount, driver, af, scene, hand)


def _spanner_ends(
    mount: Mount, af: float, band: tuple[float, float], scene: Scene, tools: _Tools
) -> Iterator[Attempt]:
    """A combination spanner, both ends: the ring first, then the open end."""
    spanner = spanner_for(af)
    yield from ring_attempts(mount, spanner, af, band, scene, tools.step_deg, tools.hand_room)
    yield from open_end_attempts(mount, spanner, af, band, scene, tools.step_deg, tools.hand_room)


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
    for family_attempts in (_forced_key, _forced_flats, _forced_driver):
        attempts = family_attempts(name, mount, geometry, scene, tools)
        if attempts is not None:
            return attempts
    raise NotCovered(f"unknown tool {name!r}")


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
    if family == "spanner":
        af = _tool_mm(size_text, name)
        if geometry.band_height <= _MIN_BAND:
            raise NotCovered("could not measure the hex's height")
        tools.need(name)
        band = (geometry.band_top, geometry.band_bottom)
        return _spanner_ends(mount, af, band, scene, tools)
    if family == "socket":
        af = _tool_mm(size_text, name)
        tools.need(name)
        return socket_attempts(mount, socket_for(af), af, scene, tools.step_deg, tools.hand_room)
    if family == "nut-driver":
        nut_driver = NUT_DRIVERS.get(_tool_mm(size_text, name))
        if nut_driver is None:
            raise NotCovered(f"no nut driver sized {size_text}: the tables hold 5.5 to 13")
        tools.need(name)
        af = nut_driver.af
        return iter([nut_driver_attempt(mount, nut_driver, af, scene, tools.hand_room)])
    return None


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
