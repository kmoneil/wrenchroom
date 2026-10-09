"""Connectors (M9): whether each plug comes off its receptacle.

A design serviced by unplugging things (a sealed box with leads, a motor on a plug, a
battery on a quick-disconnect) needs each plug to come off. It comes off by a straight
pull, not a turn: out of its receptacle, along its pull axis, far enough to be free.

- **Its receptacle** is the part it is plugged into: of the parts it touches, the one
  that holds it in the most directions (a header's shroud holds it in five; a board it
  rests on, or a neighbour beside it, in one). The sidecar's ``receptacle:`` names it
  where the geometry can't.
- **Its pull axis** is the one direction its receptacle leaves it free to move in,
  among the directions its faces face; ``axis:`` gives it where there are none or
  several.
- **Its travel** is how far it must move along the axis to be clear of its receptacle,
  plus :data:`TRAVEL_MARGIN`; ``travel:`` gives it.
- **Its pull path** is its own solid moved along the axis by its travel, tested against
  every other part but its receptacle, its pieces, its ``mates`` (its cable comes with
  it) and the ignored parts: a part in the way leaves it ``stuck``.

A part is a connector where the sidecar's ``connectors:`` names it, or where its name
is about a plug (``motor_plug``): a plug is the half that comes off. A name of a
connector family (XT30, XT60, XT90, JST, Deutsch DT) or a connector word (connector,
header, jack, receptacle) says nothing of which half comes off, and most such parts in
a model are the halves soldered to a board: such a part is listed, not checked, until
the sidecar names it.

Whether the fingers have room to grip it, and a thumb its latch, waits on figures
checked against real hands, as room for a hand does.
"""

from __future__ import annotations

import enum
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from build123d import Compound, GeomType, Location

from wrenchroom.detect.names import name_words
from wrenchroom.engine.exact import exact_overlap
from wrenchroom.engine.scene import HIT_MIN_VOLUME, Contact, shape_bounds
from wrenchroom.report import listed, md_code, md_text, shortlist
from wrenchroom.tools.fingers import FINGER_REACH
from wrenchroom.tools.sweep import CONTACT_OFFSET, HAND_LENGTH, Probe, axial_cylinder

if TYPE_CHECKING:
    from collections.abc import Sequence

    from build123d import Shape

    from wrenchroom.assembly import Part
    from wrenchroom.engine.scene import Engine, Scene

Vec = tuple[float, float, float]

#: Past its engaged length, how far a plug must come out to be free, mm: its contacts'
#: last grip, and a hand's slack.
TRAVEL_MARGIN = 3.0

#: Two parts this close, mm, touch: a plug drawn sitting in its receptacle.
TOUCH_MM = 0.05

#: A plug this far from its receptacle, mm, is out of it: how close its travel is found.
APART_MM = 0.01

#: The steps a plug is moved by, mm, to see which ways its receptacle lets it go: a
#: fit drawn tight stops it at the first, one drawn loose by the last.
PROBE_STEPS = (0.5, 2.0, 5.0)

#: How far apart two of a plug's face directions must be to count as two, degrees.
SAME_DIRECTION_DEG = 2.0

#: How many of the ways a receptacle lets a plug go a reason names.
_WAYS_SHOWN = 4

#: The longest step along a pull path, mm, at most half the plug's own length along
#: its axis: each position overlaps the one before, so nothing thin slips between.
PATH_STEP = 5.0


class ConnectorVerdict(enum.StrEnum):
    """Per connector: whether it comes off, and what stops it."""

    UNPLUGS = "unplugs"
    STUCK = "stuck"
    NO_GRIP = "no-grip"
    NO_LATCH = "no-latch-access"
    NOT_COVERED = "not-covered"


#: How each verdict reads in a count: the summary line's words.
_WORDS = {
    ConnectorVerdict.UNPLUGS: "unplug",
    ConnectorVerdict.STUCK: "stuck",
    ConnectorVerdict.NO_GRIP: "no grip",
    ConnectorVerdict.NO_LATCH: "no latch access",
    ConnectorVerdict.NOT_COVERED: "not covered",
}

#: Failures, worst first.
_WORST = {
    ConnectorVerdict.STUCK: 0,
    ConnectorVerdict.NO_GRIP: 1,
    ConnectorVerdict.NO_LATCH: 2,
    ConnectorVerdict.NOT_COVERED: 3,
}


@dataclass(frozen=True)
class ConnectorResult:
    """One connector's outcome.

    Attributes:
        name: The plug's part name.
        verdict: Whether it comes off.
        source: ``sidecar`` for one the sidecar names, ``name`` for one found by its name.
        receptacle: What it is plugged into, as found or named.
        axis: The way it comes off, a unit vector.
        travel: How far it must come, mm.
        blockers: What its pull path runs into, by name.
        reason: Why it is not covered, or what stops it beyond the parts in the way.
        state: The state it was checked in, where not the model as given.
        grip: How the fingers were tried on it, ``pinch`` or ``hand``; None where they
            weren't (hand room off).
        latch: The side its latch is pressed from, where it has one.
        probes: The fingers and thumb as tried, for the 3D view: the clear grip and
            thumb, or every position tried where none was clear.
    """

    name: str
    verdict: ConnectorVerdict
    source: str = "sidecar"
    receptacle: tuple[str, ...] = ()
    axis: Vec | None = None
    travel: float | None = None
    blockers: tuple[str, ...] = ()
    reason: str | None = None
    state: str | None = None
    grip: str | None = None
    latch: Vec | None = None
    probes: tuple[Probe, ...] = field(default=(), compare=False, repr=False)

    @property
    def passed(self) -> bool:
        """True when it comes off."""
        return self.verdict is ConnectorVerdict.UNPLUGS


@dataclass(frozen=True)
class Connectors:
    """Every connector a run checked, and what it couldn't.

    Attributes:
        results: Each connector's outcome, by name.
        unmatched_rules: ``connectors:`` globs that name no part: a renamed part, as an
            unmatched fastener rule is, which fails the run.
        unmatched_mates: ``(rule, glob)`` for each mate glob that names no part.
        named: Parts named like connectors that aren't checked: a name doesn't say
            which half comes off.
        grip_checked: Whether the fingers' room to grip, and a thumb's to press a latch,
            was checked (hand room on).
    """

    results: tuple[ConnectorResult, ...] = ()
    unmatched_rules: tuple[str, ...] = ()
    unmatched_mates: tuple[tuple[str, str], ...] = ()
    named: tuple[str, ...] = ()
    grip_checked: bool = False

    @property
    def summary(self) -> dict[str, int]:
        """The counts the headline and the JSON share."""
        counts = Counter(result.verdict for result in self.results)
        return {
            "connectors": len(self.results),
            **{verdict.value.replace("-", "_"): counts[verdict] for verdict in ConnectorVerdict},
        }

    @property
    def exit_code(self) -> int:
        """2 for a glob naming nothing or a connector not covered, 1 for one stuck, else 0."""
        if self.unmatched_rules or self.unmatched_mates or self.summary["not_covered"]:
            return 2
        return 1 if self.failures() else 0

    def failures(self) -> tuple[ConnectorResult, ...]:
        """Every connector that doesn't come off, worst first, then by name."""
        failed = [result for result in self.results if not result.passed]
        return tuple(sorted(failed, key=lambda r: (_WORST[r.verdict], r.name)))

    @property
    def headline(self) -> str:
        """``3 connectors: 2 unplug, 1 stuck, 0 not covered``.

        With the fingers checked, how many have no grip and no latch access too.
        """
        counts = self.summary
        fingers = {ConnectorVerdict.NO_GRIP, ConnectorVerdict.NO_LATCH}
        said = ", ".join(
            f"{counts[verdict.value.replace('-', '_')]} {word}"
            for verdict, word in _WORDS.items()
            if self.grip_checked or verdict not in fingers
        )
        noun = "connector" if counts["connectors"] == 1 else "connectors"
        return f"{counts['connectors']} {noun}: {said}"

    @property
    def named_count(self) -> str:
        """The parts named like connectors, as the not-checked line counts them."""
        if len(self.named) == 1:
            return "1 part named like a connector (passed over)"
        return f"{len(self.named)} parts named like connectors (passed over)"

    #: Why a part named like a connector isn't checked, and what to do.
    NAMED_WHY = "a name doesn't say which half comes off: list the plugs under connectors:"

    def lines(self) -> list[str]:
        """The connectors as the terminal says them, for the report's terminal lines.

        The counts, where any connector was checked or the sidecar names any; a ``FAIL``
        line for each that doesn't come off; a ``WARN`` for each glob naming nothing; a
        ``NOTE`` for the parts named like connectors that aren't checked. The report
        makes every line safe to print.
        """
        lines = [self.headline] if self.results or self.unmatched_rules else []
        for result in self.failures():
            lines.append(f"FAIL {result.name}  {result.verdict}  {_why(result)}")
        lines += [
            f"WARN connector rule matched nothing: {glob!r} (renamed part?)"
            for glob in self.unmatched_rules
        ]
        lines += [
            f"WARN connector rule {parts!r}: mate glob {glob!r} matched nothing (renamed part?)"
            for parts, glob in self.unmatched_mates
        ]
        if self.named:
            lines.append(
                f"NOTE {_named(len(self.named))}, not checked: {listed(self.named)} "
                f"({self.NAMED_WHY})"
            )
        return lines

    def to_json(self) -> dict[str, object]:
        """The connectors as the JSON report's ``connectors``: every name, no shortlists."""
        return {
            "summary": self.summary,
            "grip_checked": self.grip_checked,
            "results": [
                {
                    "name": result.name,
                    "source": result.source,
                    "verdict": result.verdict.value,
                    "receptacle": list(result.receptacle),
                    "axis": list(result.axis) if result.axis else None,
                    "travel": round(result.travel, 2) if result.travel is not None else None,
                    "blocked_by": list(result.blockers),
                    "reason": result.reason,
                    "state": result.state,
                    "grip": result.grip,
                    "latch": list(result.latch) if result.latch else None,
                }
                for result in self.results
            ],
            "unmatched_rules": list(self.unmatched_rules),
            "unmatched_mates": [
                {"rule": parts, "glob": glob} for parts, glob in self.unmatched_mates
            ],
            "named": list(self.named),
        }

    def markdown(self) -> list[str]:
        """The connectors as a Markdown section: the counts, the failures, the rest."""
        lines = ["", "#### Connectors"]
        if self.results or self.unmatched_rules:
            lines += ["", f"**{md_text(self.headline)}**"]
        failures = self.failures()
        if failures:
            lines += ["", "| Connector | Verdict | In the way, or why |", "| --- | --- | --- |"]
            for result in failures:
                lines.append(f"| {md_code(result.name)} | {result.verdict} | {_md_why(result)} |")
        apart = [
            f"- Connector rule matched nothing: {md_code(glob, in_table=False)} (renamed part?)"
            for glob in self.unmatched_rules
        ]
        apart += [
            f"- Connector rule {md_code(parts, in_table=False)}: mate glob "
            f"{md_code(glob, in_table=False)} matched nothing (renamed part?)"
            for parts, glob in self.unmatched_mates
        ]
        if self.named:
            shown, more = shortlist(self.named)
            names = ", ".join(md_code(name, in_table=False) for name in shown)
            apart.append(
                f"- {md_text(_named(len(self.named)).capitalize())}, not checked: {names}"
                + (f" and {more} more" if more else "")
                + f" ({md_text(self.NAMED_WHY)})"
            )
        return lines + (["", *apart] if apart else [])


def _named(count: int) -> str:
    """``1 part named like a connector``, ``3 parts named like connectors``."""
    return "1 part named like a connector" if count == 1 else f"{count} parts named like connectors"


def _why(result: ConnectorResult) -> str:
    """What a failure says: its reason, else what's in its way."""
    return result.reason or listed(result.blockers)


def _md_why(result: ConnectorResult) -> str:
    if result.reason:
        return md_code(result.reason)
    shown, more = shortlist(result.blockers)
    return ", ".join(md_code(name) for name in shown) + (f" and {more} more" if more else "")


# ---------------------------------------------------------------------------
# Names: a plug is the half that comes off.
# ---------------------------------------------------------------------------

#: The words that name the half that comes off.
PLUG_WORDS = frozenset({"plug", "plugs"})

#: Words before "plug" that make it a plug turned in, or no connector at all.
_NOT_PULLED = frozenset({"drain", "spark", "threaded", "screw", "fill", "oil"})

#: Words that name a connector, or a half of one, without saying which.
CONNECTOR_WORDS = frozenset(
    {
        "connector",
        "connectors",
        "header",
        "headers",
        "jack",
        "jacks",
        "receptacle",
        "jst",
        "deutsch",
    }
)

#: Families named by a code: XT30, XT60 and XT90; Deutsch DT and DTP part numbers.
_FAMILY = re.compile(r"(?<![a-z0-9])(?:xt(?:30|60|90)|dtp?0[46](?:-\d+[ps])?)(?![0-9])", re.I)


class Named(enum.Enum):
    """What a part's name says of it as a connector."""

    PLUG = "plug"
    CONNECTOR = "connector"


def read_connector_name(name: str) -> Named | None:
    """Whether a name is about a plug, a connector of no stated half, or neither.

    About a plug when "plug" is the word the name is about, its last (``xt60_plug``,
    ``Motor Plug``), and nothing says it is turned in (``drain plug``). A connector
    word anywhere, or a family's code, makes a connector of no stated half.
    """
    words = name_words(name)
    if words and words[-1] in PLUG_WORDS and not _NOT_PULLED & set(words[:-1]):
        return Named.PLUG
    if CONNECTOR_WORDS & set(words) or _FAMILY.search(name):
        return Named.CONNECTOR
    return None


# ---------------------------------------------------------------------------
# Geometry: the receptacle, the pull axis, the travel, the path.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Seat:
    """How a plug sits: what it is plugged into, which way it comes off, and how far."""

    receptacle: tuple[Part, ...]
    axis: Vec
    travel: float


class Unclear(Exception):  # noqa: N818  (a verdict carrier, as NotCovered is)
    """Why a plug's seat can't be found: its verdict is not covered, with this reason."""


def plug_shape(parts: Sequence[Part]) -> Shape:
    """A plug as one shape: its part, and its other solids where it is drawn as several."""
    if len(parts) == 1:
        return parts[0].shape
    return Compound(children=[part.shape for part in parts])


def face_directions(shape: Shape) -> list[Vec]:
    """The ways a plug's faces face, each said once.

    Each flat face's outward normal, and each round face's axis both ways.
    """
    found: list[Vec] = []
    for face in shape.faces():
        if face.geom_type is GeomType.PLANE:
            centre = face.center()
            candidates = [_unit(tuple(face.normal_at(centre)))]
        elif face.geom_type is GeomType.CYLINDER and face.axis_of_rotation is not None:
            direction = _unit(tuple(face.axis_of_rotation.direction))
            candidates = [direction, _neg(direction)]
        else:
            continue
        for direction in candidates:
            if not any(
                _dot(direction, seen) > math.cos(math.radians(SAME_DIRECTION_DEG)) for seen in found
            ):
                found.append(direction)
    return found


def touching(shape: Shape, parts: Sequence[Part], engine: Engine) -> list[Part]:
    """The parts a plug touches: within :data:`TOUCH_MM`, boxes first."""
    low, high = shape_bounds(shape)
    near = []
    for part in parts:
        box = engine.part_box(part)
        if all(
            box[0][i] <= high[i] + TOUCH_MM and low[i] - TOUCH_MM <= box[1][i] for i in range(3)
        ):
            near.append(part)
    return [part for part in near if _distance(shape, part.shape) <= TOUCH_MM]


def holds_in(shape: Shape, part: Part, directions: Sequence[Vec], engine: Engine) -> set[int]:
    """Which of ``directions``, by index, a part stops the plug moving in.

    Stopped where the plug moved by one of :data:`PROBE_STEPS` overlaps the part by more
    than it does as drawn, past the hit floor. A plug drawn into its receptacle (pins in
    their sockets) overlaps it as drawn, and is held only by what moving adds.
    """
    query = engine.query(shape)
    drawn_in = query.contact(part) is Contact.HIT
    rest = exact_overlap(shape, part.shape) if drawn_in else 0.0
    held: set[int] = set()
    for index, direction in enumerate(directions):
        for step in PROBE_STEPS:
            moved = _moved(shape, _scale(direction, step))
            if drawn_in:
                if exact_overlap(moved, part.shape) > rest + HIT_MIN_VOLUME:
                    held.add(index)
                    break
            elif engine.query(moved).contact(part) is Contact.HIT:
                held.add(index)
                break
    return held


def find_receptacle(
    shape: Shape, near: Sequence[Part], directions: Sequence[Vec], engine: Engine
) -> tuple[Part, set[int]]:
    """Of the parts a plug touches, the one that holds it in the most directions.

    Raises:
        Unclear: When it touches nothing, nothing holds it in more than one direction
            (it rests on a part, it isn't plugged into one), or two hold it alike.
    """
    if not near:
        msg = (
            "it touches no part, so nothing it plugs into: "
            "say which way it comes off (axis:) and how far (travel:)"
        )
        raise Unclear(msg)
    held = [(part, holds_in(shape, part, directions, engine)) for part in near]
    held.sort(key=lambda found: -len(found[1]))
    best, ways = held[0]
    if len(ways) < 2:  # noqa: PLR2004  (a part beside it, or under it, holds it one way)
        names = listed(tuple(part.name for part in near))
        msg = (
            f"it only rests against {names}, plugged into none: "
            "say what it plugs into (receptacle:)"
        )
        raise Unclear(msg)
    if len(held) > 1 and len(held[1][1]) == len(ways):
        msg = (
            f"{best.name} and {held[1][0].name} hold it alike: "
            "say which it plugs into (receptacle:)"
        )
        raise Unclear(msg)
    return best, ways


def pull_axis(directions: Sequence[Vec], held: set[int], receptacle: str) -> Vec:
    """The one direction its receptacle leaves a plug free to move in.

    Raises:
        Unclear: When it is free in none, or in several.
    """
    free = [direction for index, direction in enumerate(directions) if index not in held]
    if len(free) == 1:
        return free[0]
    if not free:
        msg = (
            f"it can't come out of {receptacle} the way any of its faces faces: "
            "say which way it comes off (axis:)"
        )
        raise Unclear(msg)
    shown = free[:_WAYS_SHOWN]
    ways = ", ".join(said_direction(d) for d in shown) + (" ..." if len(free) > len(shown) else "")
    msg = f"{receptacle} lets it go {len(free)} ways ({ways}): say which way it comes off (axis:)"
    raise Unclear(msg)


def engaged_length(shape: Shape, receptacle: Sequence[Part], axis: Vec) -> float:
    """How far a plug must move along its axis before it is clear of its receptacle.

    Clear once :data:`APART_MM` from it, searched by halves to that, between nothing and
    its own length along the axis and the receptacle's together: past that it can't
    still be in.
    """
    whole = (
        Compound(children=[part.shape for part in receptacle])
        if len(receptacle) > 1
        else receptacle[0].shape
    )
    low, high = 0.0, _length_along(shape, axis) + _length_along(whole, axis)
    if _distance(shape, whole) > TOUCH_MM:
        return 0.0
    while high - low > APART_MM:
        middle = (low + high) / 2
        if _distance(_moved(shape, _scale(axis, middle)), whole) > APART_MM:
            high = middle
        else:
            low = middle
    return high


def pull_path(shape: Shape, axis: Vec, travel: float, scene: Scene) -> tuple[str, ...]:
    """What the plug runs into, moved along its axis by its travel: every part, in order.

    Tested at steps no longer than half its own length along the axis, nor
    :data:`PATH_STEP`, so each position overlaps the last and nothing thin slips
    between them.
    """
    step = min(PATH_STEP, max(_length_along(shape, axis) / 2, TOUCH_MM))
    count = max(1, math.ceil(travel / step))
    hits: list[str] = []
    for index in range(1, count + 1):
        moved = _moved(shape, _scale(axis, travel * index / count))
        hits.extend(name for name in scene.hits(moved) if name not in hits)
    return tuple(hits)


def _length_along(shape: Shape, axis: Vec) -> float:
    """A shape's extent along a direction, from its vertices."""
    projections = [_dot(tuple(vertex), axis) for vertex in shape.vertices()]
    if not projections:
        low, high = shape_bounds(shape)
        return math.dist(low, high)
    return max(projections) - min(projections)


def _distance(a: Shape, b: Shape) -> float:
    """The least distance between two shapes, measured near the origin (issue #107)."""
    low, high = shape_bounds(b)
    step = Location(tuple(-(lo + hi) / 2 for lo, hi in zip(low, high, strict=True)))
    return a.moved(step).distance_to(b.moved(step))


def _moved(shape: Shape, offset: Vec) -> Shape:
    return shape.moved(Location(offset))


def said_direction(direction: Vec) -> str:
    """A direction as the sidecar writes it: ``+z``, or ``[0.71, 0.71, 0]``."""
    for index, letter in enumerate("xyz"):
        if abs(abs(direction[index]) - 1) < 1e-6:  # noqa: PLR2004
            return ("+" if direction[index] > 0 else "-") + letter
    return "[" + ", ".join(f"{c:g}" for c in (round(c, 2) for c in direction)) + "]"


def _unit(vector: Sequence[float]) -> Vec:
    length = math.sqrt(sum(c * c for c in vector))
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def _neg(a: Vec) -> Vec:
    return (-a[0], -a[1], -a[2])


# ---------------------------------------------------------------------------
# Fingers: room to grip a plug, and to press its latch. Like room for a hand, the
# figures are a hand's, not a standard's, not yet checked against real hands and
# plugs: checked only with hand room on.
# ---------------------------------------------------------------------------

#: A finger pinching a plug: a cylinder this radius, mm, along the plug's side.
FINGER_RADIUS = 8.0

#: A thumb pressing a latch: a cylinder this radius and length, mm, out from the side.
THUMB_RADIUS = 9.0
THUMB_LENGTH = 40.0

#: A fist round a plug stands this far out from it all round, mm.
FIST_REACH = 30.0

#: Where round its axis a pinch is tried, degrees apart: each pair of fingers opposite.
GRIP_STEP_DEG = 15.0


@dataclass(frozen=True)
class Body:
    """A plug about its pull axis: where it starts and ends along it, and its outline.

    Attributes:
        foot: The point on the axis level with the plug's end in its receptacle.
        axis: The pull axis.
        length: Its length along the axis.
        exposed: How far up from its foot its receptacle reaches: where fingers start.
        points: Its surface, as points, from which how far it stands out any way is read.
    """

    foot: Vec
    axis: Vec
    length: float
    exposed: float
    points: tuple[Vec, ...]

    def reach(self, direction: Vec) -> float:
        """How far its body stands out from the axis toward a direction across it."""
        return max(_dot(_sub(point, self.foot), direction) for point in self.points)

    def radius(self) -> float:
        """How far its body stands out from the axis at most, any way round."""
        return max(
            math.dist(
                point, _add(self.foot, _scale(self.axis, _dot(_sub(point, self.foot), self.axis)))
            )
            for point in self.points
        )


def body_of(shape: Shape, axis: Vec, exposed: float) -> Body:
    """A plug about its axis, read from its surface tessellated to 0.1 mm."""
    vertices, _ = shape.tessellate(0.1)
    points = tuple((v.X, v.Y, v.Z) for v in vertices)
    along = [_dot(point, axis) for point in points]
    low, high = min(along), max(along)
    count = len(points)
    centre = (
        sum(p[0] for p in points) / count,
        sum(p[1] for p in points) / count,
        sum(p[2] for p in points) / count,
    )
    level = _dot(centre, axis)
    foot = _add(centre, _scale(axis, low - level))
    return Body((foot[0], foot[1], foot[2]), axis, high - low, exposed, points)


@dataclass(frozen=True)
class Fingers:
    """How the fingers fared on a plug: whether they grip it, what they met, where.

    Attributes:
        gripped: Some position was clear.
        met: What they met where none was, the part met at the most positions first.
        probes: Each finger as tried: the clear position's, or every one tried.
    """

    gripped: bool
    met: tuple[str, ...]
    probes: tuple[Probe, ...]


def pinch(body: Body, scene: Scene) -> Fingers:
    """Two fingers either side of the plug, tried every :data:`GRIP_STEP_DEG` round it.

    Each a cylinder :data:`FINGER_RADIUS` round, along the plug's side, touching it,
    from just past its receptacle to :data:`FINGER_REACH` beyond its end, as the
    fingers round a knob reach. Any one position both are clear at grips it. Else
    what they met, the part met at the most positions first.
    """
    met: Counter[str] = Counter()
    tried: list[Probe] = []
    z_from, z_to = body.exposed + CONTACT_OFFSET, body.length + FINGER_REACH
    steps = round(180 / GRIP_STEP_DEG)
    for step in range(steps):
        phi = math.radians(step * GRIP_STEP_DEG)
        pair: list[Probe] = []
        for side in (phi, phi + math.pi):
            direction = _across(body.axis, side)
            seat = _add(body.foot, _scale(direction, body.reach(direction) + FINGER_RADIUS))
            finger = axial_cylinder(FINGER_RADIUS, z_from, z_to).placed(seat, body.axis)
            pair.append(Probe(finger, scene.hits(finger)))
        hits = tuple(dict.fromkeys(name for probe in pair for name in probe.hits))
        if not hits:
            return Fingers(gripped=True, met=(), probes=tuple(pair))
        met.update(hits)
        tried += pair
    return Fingers(False, tuple(name for name, _ in met.most_common()), tuple(tried))


def fist(body: Body, scene: Scene) -> Fingers:
    """A fist round the plug: :data:`FIST_REACH` out from it all round, a hand's length.

    From just past its receptacle along the axis, the plug and its cable inside, as a
    hand round a handle is (sweep.py's figures).
    """
    radius = body.radius() + FIST_REACH
    z_from = body.exposed + CONTACT_OFFSET
    hand = axial_cylinder(radius, z_from, z_from + HAND_LENGTH).placed(body.foot, body.axis)
    hits = scene.hits(hand)
    return Fingers(not hits, hits, (Probe(hand, hits),))


def thumb(body: Body, side: Vec, scene: Scene) -> Probe:
    """A thumb pressing the plug's latch from ``side``, and what it meets.

    A cylinder :data:`THUMB_RADIUS` round and :data:`THUMB_LENGTH` long, out from the
    plug's surface that way: halfway up what stands out of its receptacle, or, on a
    plug standing out less than a thumb is across, a thumb's radius clear of it.
    """
    across = _sub(side, _scale(body.axis, _dot(side, body.axis)))
    direction = _unit(across) if math.hypot(*across) > 1e-6 else side  # noqa: PLR2004
    height = max((body.exposed + body.length) / 2, body.exposed + THUMB_RADIUS + CONTACT_OFFSET)
    seat = _add(
        _add(body.foot, _scale(body.axis, height)),
        _scale(direction, body.reach(direction) + CONTACT_OFFSET),
    )
    pressing = axial_cylinder(THUMB_RADIUS, 0.0, THUMB_LENGTH).placed(seat, direction)
    return Probe(pressing, scene.hits(pressing))


def _across(axis: Vec, phi: float) -> Vec:
    """The direction ``phi`` round an axis, across it, from a fixed start."""
    start = (1.0, 0.0, 0.0) if abs(axis[0]) < 0.9 else (0.0, 1.0, 0.0)  # noqa: PLR2004
    first = _unit(_cross(axis, start))
    second = _cross(axis, first)
    return _add(_scale(first, math.cos(phi)), _scale(second, math.sin(phi)))


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
