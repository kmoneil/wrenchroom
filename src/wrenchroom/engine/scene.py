"""The engine interface: a scene of parts, two queries, one rule for a hit.

A hit is an overlap of more than :data:`HIT_MIN_VOLUME` between the tool and a
part, whichever engine measures it. A tangent touch is not a hit (both engines
measure zero volume for it), which is why tools start 0.3 mm off the seat rather
than on it.

An engine lives for one run and caches per part: a part's box is computed once
however many fasteners' scenes it sits in. Parts are keyed by identity, never by
name, so the same name in another state's model (the lever raised) is another
part with its own geometry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar, Protocol

import numpy as np
from build123d import Shape
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

from wrenchroom.solids import Bounds, ToolSolid

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from wrenchroom.assembly import Part

#: Overlap volume in mm^3 below which an intersection is numerical noise, not a
#: collision. The spec's figure; both engines measure volume, so both use it.
HIT_MIN_VOLUME = 0.05

#: Bounding boxes grown by this much, mm, before the overlap prefilter; covers
#: a kernel finding an intersection a hair outside a tight box.
BOX_MARGIN = 0.1

#: What the queries accept: a tool built from primitives (every tool the sweeps
#: make), or any OCP shape (slower on the mesh engine: it is tessellated first).
Tool = ToolSolid | Shape


class Query(Protocol):
    """One tool, prepared by an engine for testing against parts one at a time."""

    @property
    def bounds(self) -> Bounds:
        """The tool's axis-aligned box; parts outside it are never tested."""
        ...

    def hits(self, part: Part) -> bool:
        """True when the tool overlaps the part by more than HIT_MIN_VOLUME."""
        ...


class Engine(ABC):
    """Answers collision queries for one run, caching what it learns per part."""

    #: The name ``--exact`` and ``check(engine=...)`` select it by.
    name: ClassVar[str]

    def __init__(self) -> None:
        self._bounds: dict[int, tuple[Part, Bounds]] = {}

    def scene(self, parts: Iterable[Part]) -> Scene:
        """The obstacles for one fastener's check, queried through this engine."""
        return Scene(parts, self)

    def part_bounds(self, part: Part) -> Bounds:
        """The part's axis-aligned box, computed once per part per run."""
        cached = self._bounds.get(id(part))
        if cached is None:
            # The part rides along so its id cannot be reused while cached.
            cached = (part, shape_bounds(part.shape))
            self._bounds[id(part)] = cached
        return cached[1]

    @abstractmethod
    def query(self, tool: Tool) -> Query:
        """Prepare one tool solid for testing against the scene's parts."""


class Scene:
    """The obstacles for one fastener's check: parts a tool is not allowed to meet.

    Build it once per fastener and state (the check loop drops the fastener
    itself, its mates and the ignored parts before handing the rest here) and
    query it for every tool position.
    """

    def __init__(self, parts: Iterable[Part], engine: Engine) -> None:
        self.parts: tuple[Part, ...] = tuple(parts)
        self.engine = engine
        boxes = [engine.part_bounds(part) for part in self.parts]
        self._low = np.array([low for low, _ in boxes], dtype=float).reshape(-1, 3)
        self._high = np.array([high for _, high in boxes], dtype=float).reshape(-1, 3)

    def hits(self, tool: Tool) -> tuple[str, ...]:
        """Every part the tool solid overlaps, by name, in assembly order."""
        return tuple(self._scan(tool, stop_at_first=False))

    def clear(self, tool: Tool) -> bool:
        """True when the tool overlaps nothing; stops at the first offender."""
        return not any(self._scan(tool, stop_at_first=True))

    def _scan(self, tool: Tool, stop_at_first: bool) -> Iterator[str]:
        query = self.engine.query(tool)
        for index in self._near(query.bounds):
            part = self.parts[index]
            if query.hits(part):
                yield part.name
                if stop_at_first:
                    return

    def _near(self, bounds: Bounds) -> np.ndarray:
        """Indices of parts whose boxes overlap the tool's, with the margin."""
        low, high = np.asarray(bounds[0]), np.asarray(bounds[1])
        near = (self._low - BOX_MARGIN <= high) & (low - BOX_MARGIN <= self._high)
        return np.flatnonzero(near.all(axis=1))


def shape_bounds(shape: Shape) -> Bounds:
    """An axis-aligned box sure to hold the shape, for the prefilter.

    OCP's quick box, from the B-rep's own curves and surfaces, never from a
    triangulation (which lies inside curved faces). It can be a little loose
    (0.66 mm at most on the bench's parts, usually exact) and that is fine: a
    loose box costs a test, never a missed hit. The tight box costs 30 times
    as much and was most of the time in a large scene.
    """
    topo = shape.wrapped
    if topo is None:
        msg = "an empty shape has no box"
        raise ValueError(msg)
    box = Bnd_Box()
    BRepBndLib.Add_s(topo, box, False)
    low, high = box.CornerMin(), box.CornerMax()
    return (low.X(), low.Y(), low.Z()), (high.X(), high.Y(), high.Z())


def boxes_overlap(a: Bounds, b: Bounds, margin: float = BOX_MARGIN) -> bool:
    """Axis-aligned overlap with a safety margin; the cheap gate before a boolean."""
    (a_min, a_max), (b_min, b_max) = a, b
    return all(a_min[i] - margin <= b_max[i] and b_min[i] - margin <= a_max[i] for i in range(3))
