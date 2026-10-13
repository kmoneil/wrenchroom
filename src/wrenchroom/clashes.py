"""Clashes: parts drawn into each other, anywhere in the model (M8).

Since issue #63, a fastener drawn into another part is reported, but only once
something has gone wrong with it. The same test over every pair of parts finds the
faults a model's own collision check misses when it tests only some pairs, as
hand-written ones do: the moving parts against the rest, never a bracket against its
own nut.

- Every pair of parts whose boxes overlap is measured. A clash is an overlap past
  the hit floor (:data:`HIT_MIN_VOLUME`), as a tool's hit is, and every clash told
  is measured exactly, so both engines tell the same ones, to the same volume. On
  the mesh engine, two parts' meshes first rule out the pairs they are sure of, by
  more than either mesh could stray (``MeshEngine.parts_apart``); the rest, a shaft
  in a bore of its own radius, a face on a face, go to a boolean.
- A boolean's answer is held to what the two meshes share (issue #163,
  ``MeshEngine.shared``): OCCT's comes back empty, or with what no solid could be,
  for parts drawn far into each other, and says nothing of it. Where the solids
  themselves bear the meshes out, the clash is told on the meshes' figure, and says
  so (:data:`BY_MESHES`). Two parts drawn in one place, one a solid the boolean
  fails on, are measured so without asking it (issue #179, :data:`NOT_ASKED`).
- A fastener is measured past its thread, as #63's test measures it
  (``checker._measured``): a screw in a hole drawn at its tap drill, a bolt in a nut
  bored at its minor diameter, overlap by design and are no clash. So is a fastener
  with its pair, its mates and its own pieces, an ignored part with anything, and
  any two parts the sidecar's ``allow:`` names.
- What a verdict says of a fastener's clash, the list says to the same volume
  (issue #156): a screw's whole head, a nut to its free end, and one fastener drawn
  twice, all the two solids share.
- Two shortcuts get a hint, not another verdict: a gland or grommet drawn into a
  cable (drawn without a bore?), and a press fit, an overlap a few hundredths thick.
  A nut or a hex head drawn into the trap that holds it is said as ``check`` notes
  it: a press fit, or a clash to fix.
- An insert set into its part is no clash (issue #158): a heat-set insert goes into
  a hole drawn smaller than its knurl, so overlapping the part it is melted into is
  what it is drawn to do. It is counted apart (:func:`_share`), and a clash only
  where the part is over one end of it, or takes up more of it than a hole drawn
  for an insert leaves.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, cast

import numpy as np

from wrenchroom import __version__
from wrenchroom.engine.scene import HIT_MIN_VOLUME
from wrenchroom.report import md_code, md_text, printable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from build123d import Shape, Solid

    from wrenchroom.assembly import Part
    from wrenchroom.engine.scene import Engine, PartOverlap, Triangles

#: An overlap thinner than this, mm (its volume over half its surface, which a thin
#: shell's thickness is), is as often a press fit as a fault: a pin drawn a few
#: hundredths into its hole. Said, as a hint.
PRESS_FIT_MM = 0.1

#: Two fasteners sharing more than this fraction of each one's volume are one drawn
#: twice (issue #94): a screw drawn once for each of two optional parts, say.
TWICE = 0.5

#: What a clash of one fastener drawn twice is said to be.
TWICE_HINT = "one fastener drawn twice"

#: An insert is set into a part that takes up no more than this share of the
#: insert's own cylinder, along the length the two share: a hole 0.84 of the insert
#: across, or more (1 - 0.84^2 = 0.29). Makers' holes are 0.86 to 0.93 of their
#: inserts (ruthex: 4.0 for 4.6, 4.4 for 5.0, 5.6 for 6.3, 6.4 for 7.1; Albany
#: County Fasteners' metric table: 3.2 for 3.5 up to 10.2 for 11.1; PEM's IUTB, inch
#: and metric: 0.127 in for 0.147, 0.158 for 0.179, 0.189 for 0.210, 4.01 mm for
#: 4.55, 5.67 for 6.17). A hole drawn for the screw alone, ISO 273's medium
#: clearance, is 0.68 to 0.81 of them (3.4 for 5.0, 9 for 11.1): no hole for the
#: insert at all. One sheet's inch rows don't fit (issue #167): Albany County
#: Fasteners gives 0.129 in for a 0.175 #4-40, 0.74 of it, and as little to #10,
#: where PEM gives 0.158 for a 0.179 one, and every other hole read for those
#: threads is 0.01 to 0.05 in over that sheet's. An insert drawn to it reads as one
#: with no hole drawn for it.
SET_IN_SHARE = 0.3

#: What a clash of a nut or a hex head with the trap that holds it is said to be:
#: ``check``'s own note of it (issue #93).
TRAP_HINT = "its trap: a press fit, or a clash to fix"

#: What a clash of an insert with a part round its middle is said to be, where the
#: part takes up more of it than a hole for an insert leaves.
DEEP_HINT = "deeper than a knurl: no hole drawn for the insert?"

#: What is said of a clash measured on the two parts' meshes (issue #163): its volume
#: is theirs, good to what a mesh is.
BY_MESHES = "measured on their meshes: the solids' boolean failed"

#: What is said of a clash measured on the meshes with the boolean not asked (issue
#: #179): two options of one part drawn over each other, one of them invalid as
#: exported or one a boolean has already failed on in the run.
NOT_ASKED = "measured on their meshes: drawn in one place, and one is a solid the boolean fails on"

#: Words in a part's name that say it is a cable, which a gland or grommet is drawn
#: round.
_CABLE_WORDS = frozenset({"cable", "cables", "wire", "wires", "cord", "lead", "leads"})

#: A part's name says it is a grommet, which a cable runs through as a gland's does.
_GROMMET_WORDS = frozenset({"grommet", "grommets"})


@dataclass(frozen=True)
class Clash:
    """Two parts drawn into each other past the hit floor.

    Attributes:
        first: The part drawn into the other: a fastener, else the smaller.
        second: The part it is drawn into.
        volume: How much they share, mm^3: of a fastener, its part past its thread.
        point: The middle of the overlap's box, mm: where to look.
        state: The state whose model it is in, where it isn't in the model as given.
        hint: What it may be: a shortcut rather than a fault (a press fit, a gland
            round its cable, a nut in its trap), or one fastener drawn twice.
        set_in: An insert set into its part, which is no clash: counted apart.
        by_meshes: Measured on the two parts' meshes, the solids' boolean having
            failed (issue #163): its volume is good to what the meshes are.
        unasked: Measured on the meshes with the boolean not asked: the two are
            drawn in one place, and one is a solid the boolean fails on (issue #179).
    """

    first: str
    second: str
    volume: float
    point: tuple[float, float, float]
    state: str | None = None
    hint: str | None = None
    #: The overlap itself, for the 3D view to draw: the solid, or measured on the
    #: meshes, its triangles. Not in the JSON.
    overlap: Shape | Triangles | None = field(default=None, compare=False, repr=False)
    set_in: bool = False
    by_meshes: bool = False
    unasked: bool = False


@dataclass(frozen=True)
class Along:
    """An insert's axis, and where along it its two ends are, mm from the origin."""

    origin: tuple[float, float, float]
    direction: tuple[float, float, float]
    low: float
    high: float


def _no_trap() -> str | None:
    return None


@dataclass(frozen=True)
class Measured:
    """A fastener as a clash measures it: its region, and of that, what is past its thread.

    Each a part of its own, so the engine measures it as it measures a part: on the
    mesh engine, by meshes first, booleans only where they can't be sure.

    Attributes:
        region: Where it is measured at all: a screw's head, a nut's body.
        past_thread: Of that, what lies past its thread, which decides.
        gland: A cable gland: a cable runs through it.
        insert: An insert's axis and ends: it may be set into a part (issue #158).
        trap: The part a nut or a hex head sits trapped in, if one, asked only of
            one drawn into a part.
    """

    region: Part
    past_thread: Part
    gland: bool = False
    insert: Along | None = None
    trap: Callable[[], str | None] = _no_trap


@dataclass(frozen=True)
class Clashes:
    """What a clash check found, in one model and its states' models.

    Attributes:
        found: Every clash, the model as given first, then each state's own.
        unmatched_allows: ``allow:`` globs that name no part: a renamed part, as an
            unmatched rule is, which fails the run.
        unmeasured: Fasteners not understood (no frame), measured as plain parts would
            be wrong, so not measured: said, never silent.
        set_in: Each insert set into a part, which is no clash and fails nothing
            (issue #158): counted, and listed when asked.
        unsure: Pairs of parts not measured at all: the solids' boolean gave what no
            solid could be, and one of the two has no closed mesh to measure on
            instead (issue #163). Said, never silent.
    """

    found: tuple[Clash, ...] = ()
    unmatched_allows: tuple[str, ...] = ()
    unmeasured: tuple[str, ...] = ()
    set_in: tuple[Clash, ...] = ()
    unsure: tuple[tuple[str, str], ...] = ()

    @property
    def exit_code(self) -> int:
        """2 for an allow glob naming nothing, 1 for a clash, else 0."""
        if self.unmatched_allows:
            return 2
        return 1 if self.found else 0

    @property
    def headline(self) -> str:
        """``2 clashes (overlap over 0.05 mm^3)``: how many, past what floor."""
        count = len(self.found)
        said = "no clashes" if not count else "1 clash" if count == 1 else f"{count} clashes"
        return f"{said} (overlap over {HIT_MIN_VOLUME} mm^3)"

    @property
    def set_in_said(self) -> str | None:
        """``5 inserts set into their parts, no clashes``: how many inserts, where any are."""
        count = len({clash.first for clash in self.set_in})
        if count == 1:
            return "1 insert set into its part, no clash"
        return f"{count} inserts set into their parts, no clashes" if count else None

    def lines(self, *, with_inserts: bool = False) -> list[str]:
        """The clashes as the terminal says them, safe to print.

        The count, a ``CLASH`` line each, a ``NOTE`` counting the inserts set into
        their parts (each a ``SET`` line of its own, ``with_inserts``), then a
        ``WARN`` for each allow glob naming nothing and a ``NOTE`` for the fasteners
        not measured, as ``check`` says its own.
        """
        lines = [self.headline]
        lines += [_line("CLASH", clash) for clash in self.found]
        if self.set_in_said is not None:
            how = "" if with_inserts else " (wrenchroom clashes --with-inserts lists them)"
            lines.append(f"NOTE {self.set_in_said}{how}")
        if with_inserts:
            lines += [_line("SET", clash) for clash in self.set_in]
        lines += [
            f"WARN allow matched nothing: {glob!r} (renamed part?)"
            for glob in self.unmatched_allows
        ]
        if self.unmeasured:
            names = ", ".join(self.unmeasured)
            lines.append(f"NOTE not measured for clashes, not understood as fasteners: {names}")
        if self.unsure:
            lines.append(f"NOTE {UNSURE}: {_pairs_said(self.unsure)}")
        return [printable(line) for line in lines]

    def to_json(self) -> dict[str, object]:
        """The clashes as the JSON report's ``clashes``."""
        return {
            "floor_mm3": HIT_MIN_VOLUME,
            "found": [
                {
                    "parts": [clash.first, clash.second],
                    "volume": round(clash.volume, 2),
                    "point": [round(c, 2) for c in clash.point],
                    "state": clash.state,
                    "hint": clash.hint,
                    "by_meshes": clash.by_meshes,
                    "unasked": clash.unasked,
                }
                for clash in self.found
            ],
            "unmatched_allows": list(self.unmatched_allows),
            "unmeasured": list(self.unmeasured),
            "set_in": [
                {
                    "parts": [clash.first, clash.second],
                    "volume": round(clash.volume, 2),
                    "point": [round(c, 2) for c in clash.point],
                    "state": clash.state,
                    "by_meshes": clash.by_meshes,
                }
                for clash in self.set_in
            ],
            "unsure": [list(pair) for pair in self.unsure],
        }

    def json_text(self, model: str = "", engine: str = "mesh") -> str:
        """The clashes as a JSON document of their own, as ``wrenchroom clashes`` writes it.

        With the model, the engine and the version, as ``check``'s says them.
        """
        document = {
            "schema": 1,
            "model": model,
            "engine": engine,
            "tool_version": __version__,
            "clashes": self.to_json(),
        }
        return json.dumps(document, indent=2) + "\n"

    def markdown_text(self, model: str = "", *, with_inserts: bool = False) -> str:
        """The clashes as a Markdown document of their own, for a CI summary."""
        title = "wrenchroom clashes"
        if model:
            title += f": {md_code(model, in_table=False)}"
        body = self.markdown(with_inserts=with_inserts)[3:]
        return "\n".join([f"### {title}", "", *body]) + "\n"

    def markdown(self, *, with_inserts: bool = False) -> list[str]:
        """The clashes as a Markdown section: a table, names in code spans.

        The inserts set into their parts are counted under it, and with
        ``with_inserts``, a table of their own.
        """
        lines = ["", "#### Clashes", "", md_text(self.headline) + "."]
        if self.found:
            lines += ["", "| Part | Into | Overlap (mm^3) | |", "| --- | --- | ---: | --- |"]
            lines += [_row(clash) for clash in self.found]
        if with_inserts and self.set_in:
            lines += ["", "| Insert | Set into | Overlap (mm^3) | |", "| --- | --- | ---: | --- |"]
            lines += [_row(clash) for clash in self.set_in]
        apart = [f"- {md_text(self.set_in_said)}"] if self.set_in_said else []
        apart += [
            f"- Allow matched nothing: {md_code(glob, in_table=False)} (renamed part?)"
            for glob in self.unmatched_allows
        ]
        if self.unmeasured:
            names = ", ".join(md_code(name, in_table=False) for name in self.unmeasured)
            apart.append(f"- Not measured for clashes, not understood as fasteners: {names}")
        if self.unsure:
            pairs = "; ".join(
                f"{md_code(a, in_table=False)} with {md_code(b, in_table=False)}"
                for a, b in self.unsure
            )
            apart.append(f"- {UNSURE[0].upper()}{UNSURE[1:]}: {pairs}")
        return lines + (["", *apart] if apart else [])


#: What is said of the pairs in :attr:`Clashes.unsure`.
UNSURE = "not measured, the solids' boolean failed and one has no closed mesh"


def _pairs_said(pairs: tuple[tuple[str, str], ...]) -> str:
    return "; ".join(f"{a} with {b}" for a, b in pairs)


def _line(word: str, clash: Clash) -> str:
    """``CLASH nut into lid  96.1 mm^3  in state open  (a press fit, 0.03 deep?)``."""
    said = [f"in state {clash.state}"] if clash.state else []
    said += [f"({clash.hint})"] if clash.hint else []
    said += [f"({_measure(clash)})"] if clash.by_meshes else []
    return "  ".join([f"{word} {clash.first} into {clash.second}", f"{clash.volume:.1f} mm^3"]) + (
        "".join(f"  {part}" for part in said)
    )


def _measure(clash: Clash) -> str:
    """What is said of a clash measured on the meshes: the boolean failed, or wasn't asked."""
    return NOT_ASKED if clash.unasked else BY_MESHES


def _row(clash: Clash) -> str:
    """A clash as a row of its Markdown table."""
    said = [f"in state {md_code(clash.state)}"] if clash.state else []
    said += [md_text(clash.hint)] if clash.hint else []
    said += [md_text(_measure(clash))] if clash.by_meshes else []
    return (
        f"| {md_code(clash.first)} | {md_code(clash.second)} | {clash.volume:.1f} "
        f"| {'; '.join(said)} |"
    )


def scan(
    parts: Sequence[Part],
    engine: Engine,
    fasteners: Mapping[str, Callable[[], Measured]],
    meant: Callable[[str, str], bool],
    state: str | None = None,
) -> list[Clash]:
    """Every clash among ``parts``: each pair whose boxes overlap, measured.

    ``fasteners`` measure each fastener past its thread, asked only where its whole
    solid isn't surely clear of the other part; ``meant`` says which two parts
    overlap by design (a pair, a mate, a piece, an ``allow:``). An insert set into
    its part comes back with them, marked (:attr:`Clash.set_in`): no clash.
    """
    if len(parts) < 2:  # noqa: PLR2004  (a pair)
        return []
    corners = np.array([engine.part_box(part) for part in parts], dtype=float)
    low = np.maximum(corners[:, None, 0], corners[None, :, 0])
    high = np.minimum(corners[:, None, 1], corners[None, :, 1])
    near = np.triu((high - low > 0).all(axis=2), k=1)
    found = []
    for first, second in np.argwhere(near):
        a, b = parts[first], parts[second]
        if meant(a.name, b.name):
            continue
        clash = _clash(a, b, engine, fasteners, state)
        if clash is not None:
            found.append(clash)
    told = _by_part(found, {part.name: part.piece_of or part.name for part in parts})
    return sorted(told, key=lambda clash: (clash.first, clash.second))


def _by_part(found: list[Clash], part_of: Mapping[str, str]) -> list[Clash]:
    """One clash to each two parts: a part drawn as several solids is told once (issue #210).

    Read from STEP such a part is measured solid by solid. Its solids' clashes with
    another part are one clash under the part's own name, their volumes together,
    which is what the same part handed over whole is told as. The largest of them
    says which way round it is, where to look and what it may be. An insert's share
    set into a part stays apart from a share of it that is a clash.
    """
    groups: dict[tuple[frozenset[str], bool], list[Clash]] = {}
    for clash in found:
        two = frozenset(part_of.get(name, name) for name in (clash.first, clash.second))
        groups.setdefault((two, clash.set_in), []).append(clash)
    told = []
    for group in groups.values():
        lead = max(group, key=_by_volume)
        told.append(
            replace(
                lead,
                first=part_of.get(lead.first, lead.first),
                second=part_of.get(lead.second, lead.second),
                volume=sum(clash.volume for clash in group),
                overlap=_overlaps(group, lead),
                by_meshes=any(clash.by_meshes for clash in group),
                unasked=any(clash.unasked for clash in group),
            )
        )
    return told


def _overlaps(group: list[Clash], lead: Clash) -> Shape | Triangles | None:
    """What several clashes of two parts share, as one thing to draw: all of it."""
    shared = [clash.overlap for clash in group if clash.overlap is not None]
    if len(shared) < 2:  # noqa: PLR2004  (several)
        return lead.overlap
    if all(isinstance(overlap, tuple) for overlap in shared):
        vertices, triangles, start = [], [], 0
        for points, faces in cast("list[Triangles]", shared):
            vertices.append(points)
            triangles.append(faces + start)
            start += len(points)
        return np.concatenate(vertices), np.concatenate(triangles)
    if not any(isinstance(overlap, tuple) for overlap in shared):
        from build123d import Compound  # noqa: PLC0415  (heavy: only where a clash is drawn)

        return Compound(cast("list[Shape]", shared))
    return lead.overlap  # measured two ways: the largest's, drawn as it was measured


def _clash(
    a: Part,
    b: Part,
    engine: Engine,
    fasteners: Mapping[str, Callable[[], Measured]],
    state: str | None,
) -> Clash | None:
    """Two parts' clash, if they overlap past the floor: a fastener's past its thread."""
    if engine.parts_apart(a, b):
        return None
    sides = [(x, y) for x, y in ((a, b), (b, a)) if x.name in fasteners]
    twice = _drawn_twice(a, b, engine, state) if len(sides) > 1 else None
    if twice is not None:
        return twice
    if sides:
        return _fastener_clash(sides, engine, fasteners, state)
    overlap = engine.shared(a, b)
    if overlap is None or overlap.volume <= HIT_MIN_VOLUME:
        return None
    first, second = sorted((a, b), key=_by_size)
    gland = _named(first.name, _GROMMET_WORDS)
    return _made(first, second, overlap, state, gland=gland)


def _fastener_clash(
    sides: list[tuple[Part, Part]],
    engine: Engine,
    fasteners: Mapping[str, Callable[[], Measured]],
    state: str | None,
) -> Clash | None:
    """A fastener drawn into a part past its thread: the larger, where two are fasteners.

    An insert in a part that is no fastener may be set into it, which is no clash
    (:func:`_share`); a nut in the trap that holds it is said so.
    """
    found = []
    for fastener, other in sides:
        measured = fasteners[fastener.name]()
        overlap = drawn_into(engine, measured, other)
        if overlap is None:
            continue
        hint, set_in = None, False
        if measured.insert is not None and len(sides) == 1:
            share = _share(measured.insert, overlap)
            set_in = share is not None and share <= SET_IN_SHARE
            hint = DEEP_HINT if share is not None and not set_in else None
        elif measured.trap() == other.name:
            hint = TRAP_HINT
        made = _made(fastener, other, overlap, state, gland=measured.gland, hint=hint)
        # Set in, it is no press fit to allow nor a fault to hint at: it is as drawn.
        found.append(replace(made, set_in=True, hint=None) if set_in else made)
    return max(found, key=_by_volume) if found else None


def drawn_into(engine: Engine, measured: Measured, other: Part) -> PartOverlap | None:
    """A fastener's overlap with a part it is drawn into past its thread; None where it isn't.

    What lies past its thread decides; what is told is all its measured region
    shares with the part. The one measure of it, for the list and for a verdict
    (issue #156).
    """
    past = measured.past_thread
    if engine.parts_apart(past, other):
        return None
    through = engine.shared(past, other)
    if through is None or through.volume <= HIT_MIN_VOLUME:
        return None
    return engine.shared(measured.region, other) or through


def _share(insert: Along, overlap: PartOverlap) -> float | None:
    """How much of an insert a part round its middle takes up; None for a part that isn't.

    A heat-set insert, a press nut, a rivnut: each goes into a hole drawn smaller
    than itself, and the part it is set into is drawn into its knurl all round, a
    skin of it. The overlap's own extent says both things. Along the insert's
    axis, it runs past the insert's middle: a part over one end only (the next
    part along, drawn into the insert's face) is one the insert runs into, not one
    it sits in. And of the insert's own cylinder along that length, its radius the
    overlap's, the overlap is this share: a hole 0.9 of the insert across leaves
    0.19 of it, one drawn for the screw alone, half.
    """
    points = overlap.corners()
    if not len(points):
        return None
    direction = np.array(insert.direction, dtype=float)
    out = points - np.array(insert.origin, dtype=float)
    along = out @ direction
    radius = np.linalg.norm(out - np.outer(along, direction), axis=1).max()
    low, high = along.min(), along.max()
    if not low < (insert.low + insert.high) / 2 < high:
        return None
    return overlap.volume / (math.pi * radius**2 * (high - low))


def _drawn_twice(a: Part, b: Part, engine: Engine, state: str | None) -> Clash | None:
    """Two fasteners that are one drawn twice, told as its verdict tells it (issue #156).

    All the two solids share, threads and all: over half of each (:data:`TWICE`),
    they are one fastener, and its shank drawn twice is as much the fault as its
    head. The later by name is the one drawn over the other, as ``check`` says it
    (issue #94).
    """
    overlap = engine.shared(a, b)
    if overlap is None or overlap.volume <= TWICE * max(_by_size(a)[0], _by_size(b)[0]):
        return None
    kept, other = sorted((a, b), key=_by_name)
    return _made(other, kept, overlap, state, hint=TWICE_HINT)


def _by_name(part: Part) -> str:
    return part.name


def _by_size(part: Part) -> tuple[float, str]:
    """Smaller first, by volume, then by name: the part drawn into the other."""
    return cast("Solid", part.shape).volume, part.name  # a solid, or a compound of them


def _by_volume(clash: Clash) -> float:
    return clash.volume


def _made(
    first: Part,
    second: Part,
    overlap: PartOverlap,
    state: str | None,
    *,
    gland: bool = False,
    hint: str | None = None,
) -> Clash:
    point = tuple((lo + hi) / 2 for lo, hi in zip(overlap.low, overlap.high, strict=True))
    return Clash(
        first.name,
        second.name,
        overlap.volume,
        (point[0], point[1], point[2]),
        state,
        hint or _hint(second, overlap, gland=gland),
        overlap.mesh if overlap.by_meshes else overlap.shape,
        by_meshes=overlap.by_meshes,
        unasked=overlap.unasked,
    )


def _hint(second: Part, overlap: PartOverlap, *, gland: bool) -> str | None:
    """A shortcut the clash may be: a gland round its cable, or a press fit."""
    if gland and _named(second.name, _CABLE_WORDS):
        return "a gland and its cable: drawn without a bore?"
    depth = 2 * overlap.volume / overlap.area if overlap.area > 0 else 0.0
    if depth < PRESS_FIT_MM:
        return f"a press fit, {depth:.2f} deep? allow it in the sidecar"
    return None


def _named(name: str, words: frozenset[str]) -> bool:
    """Whether a part's name has one of the words, as a word: ``cable_a``, ``Cable 2``."""
    return any(word in words for word in re.split(r"[^a-z]+", name.lower()))
