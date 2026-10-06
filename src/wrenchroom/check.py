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
from wrenchroom.config import Config, ConfigError
from wrenchroom.detect import find_fasteners
from wrenchroom.engine import DEFAULT_ENGINE, ENGINES, Engine, Scene, make_engine
from wrenchroom.fasteners import (
    PHILLIPS_NUMBER,
    Fastener,
    Head,
    Kind,
    Size,
    hex_key_af,
    spanner_af,
)
from wrenchroom.report import FastenerResult, Report, StateModel, Verdict
from wrenchroom.tools.drivers import SHAFT_RADIUS, driver_attempt
from wrenchroom.tools.hex_keys import ISO_2936, hex_key_attempts
from wrenchroom.tools.sockets import socket_attempts, socket_for
from wrenchroom.tools.spanners import ring_attempts, spanner_for
from wrenchroom.tools.sweep import (
    DEFAULT_STEP_DEG,
    Attempt,
    Mount,
    Probe,
    axial_annulus,
    axial_cylinder,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from build123d import Axis

#: The one kit M1 ships. imperial-home and full arrive with M6.
KITS = ("metric-home",)

#: How parallel a face normal must be to the axis to count as an end face.
_AXIAL = 0.99

#: A measured across-flats lands on a tool size within this, mm.
_AF_SNAP = 0.05

#: A hex band shorter than this, mm, gives a ring nothing to grip.
_MIN_BAND = 0.5

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
    kit: str = "metric-home",
    step_deg: float = DEFAULT_STEP_DEG,
    model: str = "",
    only: str | None = None,
    state: str | None = None,
    model_dir: str | Path | None = None,
    engine: str = DEFAULT_ENGINE,
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
        state: Overrides the config's ``default_state`` for this run.
        model_dir: Where a state's alternate model files live; the CLI passes
            the model's own directory.
        engine: Which collision engine answers the queries: ``mesh`` (the
            default) or ``exact`` (OCP booleans, the referee).

    Raises:
        ValueError: On a kit, state or engine that doesn't exist (a typo, not a
            model problem).
    """
    if kit not in KITS:
        msg = f"unknown kit {kit!r}; available: {', '.join(KITS)}"
        raise ValueError(msg)
    if engine not in ENGINES:
        msg = f"unknown engine {engine!r}; available: {', '.join(ENGINES)}"
        raise ValueError(msg)
    config = config or Config()
    default_state = state if state is not None else config.default_state
    if default_state is not None:
        config.state(default_state)  # raises on a typo
    matches = config.apply(assembly)
    fasteners = _fasteners(assembly, config, matches.fasteners, only)

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
            _check_fastener(fastener, frames[fastener.name], space, config, default_state, step_deg)
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
        warnings=tuple(pair_warnings + space.warnings),
        default_state=default_state,
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
) -> list[Fastener]:
    """The sidecar's fasteners, plus what detection finds among the parts it doesn't name.

    A rule that matches a part describes it outright: detection only ever sees
    parts no rule covers, and never an ignored one.
    """
    found = list(described)
    if config.detect:
        named = {f.name for f in described}
        found += find_fasteners(
            part for part in assembly if part.name not in named and not config.is_ignored(part.name)
        )
    found.sort(key=lambda f: f.name)
    if only is not None:
        found = [f for f in found if fnmatchcase(f.name, only)]
    return found


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


def _check_fastener(
    fastener: Fastener,
    frame: _Frame,
    space: _StateSpace,
    config: Config,
    default_state: str | None,
    step_deg: float,
) -> _Candidate:
    own_state = fastener.state if fastener.state is not None else default_state
    order: list[str | None] = [own_state]
    order += [s for s in config.try_states if s != own_state]
    first: _Candidate | None = None
    for index, state_name in enumerate(order):
        candidate = _try_in_state(fastener, frame, state_name, space, step_deg)
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
    step_deg: float,
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
    scene = space.scene(assembly, {fastener.name, *fastener.mates} | removed)
    try:
        mount, geometry = _orient(frame, fastener, scene)
    except NotCovered as exc:
        return _Candidate(fastener, reason=str(exc), state=state_name)
    candidate = _Candidate(fastener, axis=mount.axis, seat=mount.seat, state=state_name)
    if fastener.self_holding:
        candidate.how = "holds itself"
        return candidate
    try:
        attempts_iter = _attempts_for(fastener, mount, geometry, scene, step_deg)
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
        candidate.blockers = tuple(blockers)


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
    if top_free == bottom_free:
        raise NotCovered(
            "cannot tell the nut's free face: both ends are " + ("clear" if top_free else "covered")
        )
    return bottom_free


# ---------------------------------------------------------------------------
# Tool selection.
# ---------------------------------------------------------------------------


def _attempts_for(
    fastener: Fastener,
    mount: Mount,
    geometry: _Geometry,
    scene: Scene,
    step_deg: float,
) -> Iterator[Attempt]:
    if fastener.tool is not None:
        return _forced_attempts(fastener, mount, geometry, scene, step_deg)
    if fastener.kind is Kind.NUT or fastener.head is Head.HEX:
        return _hex_flats_attempts(fastener, mount, geometry, scene, step_deg)
    if fastener.head in _KEYED_HEADS:
        return _keyed_attempts(fastener, mount, scene, step_deg)
    if fastener.head is Head.PHILLIPS:
        size = _metric_size(fastener)
        number = PHILLIPS_NUMBER.get(size.designation)
        if number is None:
            raise NotCovered(f"no Phillips number for {size.designation}")
        return iter(
            [driver_attempt(mount, scene, SHAFT_RADIUS[f"ph{number}"], f"driver-ph{number}")]
        )
    if fastener.head is Head.SLOTTED:
        return iter([driver_attempt(mount, scene, SHAFT_RADIUS["slotted"], "driver-slotted")])
    if fastener.head is Head.TORX:
        raise NotCovered("Torx keys arrive with the full kit (M6)")
    raise NotCovered("head unknown: name it in the sidecar")


def _metric_size(fastener: Fastener) -> Size:
    """The size, which a table lookup needs: known, and metric until M6's kit."""
    if fastener.size is None:
        raise NotCovered("size unknown: name it in the sidecar")
    if not fastener.size.is_metric:
        raise NotCovered("imperial sizes need the imperial kit (M6)")
    return fastener.size


def _given_af(fastener: Fastener) -> float | None:
    """The drive's across-flats when measured or given, on a metric size; else None.

    A measurement lands on a whole or half millimetre within :data:`_AF_SNAP`
    or it is no metric tool's size: a 7/16" hex measures 11.11 and must not
    become a "spanner-11.11".
    """
    if fastener.drive_af is None:
        return None
    snapped = round(fastener.drive_af * 2) / 2
    if abs(snapped - fastener.drive_af) > _AF_SNAP:
        raise NotCovered(
            f"{fastener.drive_af:.2f} across flats is no metric tool size; "
            "imperial sizes need the imperial kit (M6)"
        )
    return snapped


def _keyed_attempts(
    fastener: Fastener, mount: Mount, scene: Scene, step_deg: float
) -> Iterator[Attempt]:
    af = _given_af(fastener)
    if af is None:
        if fastener.head is None or fastener.size is None:
            raise NotCovered("head or size unknown: name them in the sidecar")
        size = _metric_size(fastener)
        af = hex_key_af(fastener.head, size)
        if af is None or af not in ISO_2936:
            head = fastener.head.value
            raise NotCovered(f"no standard key for a {size.designation} {head} head")
    if af not in ISO_2936:
        raise NotCovered(f"no ISO 2936 key is {af:g} across flats")
    return hex_key_attempts(mount, ISO_2936[af], scene, step_deg)


def _hex_flats_attempts(
    fastener: Fastener,
    mount: Mount,
    geometry: _Geometry,
    scene: Scene,
    step_deg: float,
) -> Iterator[Attempt]:
    """Rings, then sockets; every not-covered reason decided before they run.

    The reasons are raised here, before the lazy attempts are handed back: one
    raised inside a generator would surface only while the attempts ran, past
    the code that turns it into a verdict (an M3.5 nut, which has no ISO 4032
    row, used to crash the whole check that way).
    """
    af = _given_af(fastener)
    if af is None:
        size = _metric_size(fastener)
        af = spanner_af(size)
        if af is None:
            raise NotCovered(f"no across-flats for {size.designation}")
    if geometry.band_height <= _MIN_BAND:
        raise NotCovered("could not measure the hex's height")
    band = (geometry.band_top, geometry.band_bottom)
    return _hex_flats_tools(fastener.socket_allowed, mount, af, band, scene, step_deg)


def _hex_flats_tools(
    socket_allowed: bool,
    mount: Mount,
    af: float,
    band: tuple[float, float],
    scene: Scene,
    step_deg: float,
) -> Iterator[Attempt]:
    yield from ring_attempts(mount, spanner_for(af), af, band, scene, step_deg)
    if socket_allowed:
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
        if geometry.band_height <= _MIN_BAND:
            raise NotCovered("could not measure the hex's height")
        band = (geometry.band_top, geometry.band_bottom)
        return ring_attempts(mount, spanner_for(af), af, band, scene, step_deg)
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
