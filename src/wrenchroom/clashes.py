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
- A fastener is measured past its thread, as #63's test measures it
  (``checker._measured``): a screw in a hole drawn at its tap drill, a bolt in a nut
  bored at its minor diameter, overlap by design and are no clash. So is a fastener
  with its pair, its mates and its own pieces, an ignored part with anything, and
  any two parts the sidecar's ``allow:`` names.
- Two shortcuts get a hint, not another verdict: a gland or grommet drawn into a
  cable (drawn without a bore?), and a press fit, an overlap a few hundredths thick.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import numpy as np

from wrenchroom import __version__
from wrenchroom.engine.exact import exact_common, exact_overlap
from wrenchroom.engine.scene import HIT_MIN_VOLUME
from wrenchroom.report import md_code, md_text, printable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from build123d import Shape, Solid

    from wrenchroom.assembly import Part
    from wrenchroom.engine.scene import Engine, PartOverlap

#: An overlap thinner than this, mm (its volume over half its surface, which a thin
#: shell's thickness is), is as often a press fit as a fault: a pin drawn a few
#: hundredths into its hole. Said, as a hint.
PRESS_FIT_MM = 0.1

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
        hint: A shortcut it may be, rather than a fault: a press fit, a gland round its
            cable.
    """

    first: str
    second: str
    volume: float
    point: tuple[float, float, float]
    state: str | None = None
    hint: str | None = None
    #: The overlap itself, for the 3D view to draw; not in the JSON.
    overlap: Shape | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Measured:
    """A fastener as a clash measures it: its region, and of that, what is past its thread.

    Each a part of its own, so the engine measures it as it measures a part: on the
    mesh engine, by meshes first, booleans only where they can't be sure.

    Attributes:
        region: Where it is measured at all: a screw's head, a nut's body.
        past_thread: Of that, what lies past its thread, which decides.
        gland: A cable gland: a cable runs through it.
    """

    region: Part
    past_thread: Part
    gland: bool = False


@dataclass(frozen=True)
class Clashes:
    """What a clash check found, in one model and its states' models.

    Attributes:
        found: Every clash, the model as given first, then each state's own.
        unmatched_allows: ``allow:`` globs that name no part: a renamed part, as an
            unmatched rule is, which fails the run.
        unmeasured: Fasteners not understood (no frame), measured as plain parts would
            be wrong, so not measured: said, never silent.
    """

    found: tuple[Clash, ...] = ()
    unmatched_allows: tuple[str, ...] = ()
    unmeasured: tuple[str, ...] = ()

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

    def lines(self) -> list[str]:
        """The clashes as the terminal says them, safe to print.

        The count, a ``CLASH`` line each, then a ``WARN`` for each allow glob naming
        nothing and a ``NOTE`` for the fasteners not measured, as ``check`` says its
        own.
        """
        lines = [self.headline]
        for clash in self.found:
            said = [f"in state {clash.state}"] if clash.state else []
            said += [f"({clash.hint})"] if clash.hint else []
            lines.append(
                "  ".join([f"CLASH {clash.first} into {clash.second}", f"{clash.volume:.1f} mm^3"])
                + "".join(f"  {part}" for part in said)
            )
        lines += [
            f"WARN allow matched nothing: {glob!r} (renamed part?)"
            for glob in self.unmatched_allows
        ]
        if self.unmeasured:
            names = ", ".join(self.unmeasured)
            lines.append(f"NOTE not measured for clashes, not understood as fasteners: {names}")
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
                }
                for clash in self.found
            ],
            "unmatched_allows": list(self.unmatched_allows),
            "unmeasured": list(self.unmeasured),
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

    def markdown_text(self, model: str = "") -> str:
        """The clashes as a Markdown document of their own, for a CI summary."""
        title = "wrenchroom clashes"
        if model:
            title += f": {md_code(model, in_table=False)}"
        return "\n".join([f"### {title}", "", *self.markdown()[3:]]) + "\n"

    def markdown(self) -> list[str]:
        """The clashes as a Markdown section: a table, names in code spans."""
        lines = ["", "#### Clashes", "", md_text(self.headline) + "."]
        if self.found:
            lines += ["", "| Part | Into | Overlap (mm^3) | |", "| --- | --- | ---: | --- |"]
            for clash in self.found:
                said = [f"in state {md_code(clash.state)}"] if clash.state else []
                said += [md_text(clash.hint)] if clash.hint else []
                lines.append(
                    f"| {md_code(clash.first)} | {md_code(clash.second)} | {clash.volume:.1f} "
                    f"| {'; '.join(said)} |"
                )
        apart = [
            f"- Allow matched nothing: {md_code(glob, in_table=False)} (renamed part?)"
            for glob in self.unmatched_allows
        ]
        if self.unmeasured:
            names = ", ".join(md_code(name, in_table=False) for name in self.unmeasured)
            apart.append(f"- Not measured for clashes, not understood as fasteners: {names}")
        return lines + (["", *apart] if apart else [])


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
    overlap by design (a pair, a mate, a piece, an ``allow:``).
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
    return sorted(found, key=lambda clash: (clash.first, clash.second))


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
    if sides:
        return _fastener_clash(sides, engine, fasteners, state)
    overlap = exact_common(a.shape, b.shape)
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
    """A fastener drawn into a part past its thread: the larger, where two are fasteners."""
    found = []
    for fastener, other in sides:
        measured = fasteners[fastener.name]()
        past = measured.past_thread
        if engine.parts_apart(past, other):
            continue
        if exact_overlap(past.shape, other.shape) <= HIT_MIN_VOLUME:
            continue
        overlap = exact_common(measured.region.shape, other.shape)
        if overlap is not None:
            found.append(_made(fastener, other, overlap, state, gland=measured.gland))
    return max(found, key=_by_volume) if found else None


def _by_size(part: Part) -> tuple[float, str]:
    """Smaller first, by volume, then by name: the part drawn into the other."""
    return cast("Solid", part.shape).volume, part.name  # a solid, or a compound of them


def _by_volume(clash: Clash) -> float:
    return clash.volume


def _made(
    first: Part, second: Part, overlap: PartOverlap, state: str | None, *, gland: bool
) -> Clash:
    point = tuple((lo + hi) / 2 for lo, hi in zip(overlap.low, overlap.high, strict=True))
    return Clash(
        first.name,
        second.name,
        overlap.volume,
        (point[0], point[1], point[2]),
        state,
        _hint(second, overlap, gland=gland),
        overlap.shape,
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
