"""The engine interface: a scene of parts, two queries, one rule for a hit.

A hit is an overlap of more than :data:`HIT_MIN_VOLUME` between the tool and a
part, whichever engine measures it. A tangent touch is not a hit (both engines
measure zero volume for it), which is why tools start 0.3 mm off the seat rather
than on it. An overlap above :data:`GRAZE_MIN_VOLUME` but no more than the floor
is a graze: not a hit, but a tool rubbing along a face, which a report says when
it decides a verdict (issue #25). Both engines measure a graze exactly (the mesh
engine asks its exact referee whenever a mesh can't be sure), so they find the
same ones.

An engine lives for one run and caches per part: a part's box is computed once
however many fasteners' scenes it sits in. Parts are keyed by identity, never by
name, so the same name in another state's model (the lever raised) is another
part with its own geometry.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar, Protocol

import numpy as np
from build123d import Shape
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_IN

from wrenchroom.solids import Bounds, ToolSolid

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from wrenchroom.assembly import Part

#: Overlap volume in mm^3 below which an intersection is numerical noise, not a
#: collision. The spec's figure; both engines measure volume, so both use it.
HIT_MIN_VOLUME = 0.05

#: Overlap volume in mm^3 above which an overlap at or under the hit floor is a
#: graze, not numerical noise: a tangent touch measures zero, or near it.
GRAZE_MIN_VOLUME = 1e-4


class Contact(enum.Enum):
    """How a tool meets a part: not at all, grazing it, or running into it."""

    CLEAR = "clear"
    GRAZE = "graze"
    HIT = "hit"


def contact_of(volume: float) -> Contact:
    """The contact an exactly measured overlap volume is."""
    if volume > HIT_MIN_VOLUME:
        return Contact.HIT
    return Contact.GRAZE if volume > GRAZE_MIN_VOLUME else Contact.CLEAR


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

    def contact(self, part: Part) -> Contact:
        """How the tool meets the part: a hit beyond HIT_MIN_VOLUME, a graze, or clear."""
        ...


class Engine(ABC):
    """Answers collision queries for one run, caching what it learns per part."""

    #: The name ``--exact`` and ``check(engine=...)`` select it by.
    name: ClassVar[str]

    def __init__(self) -> None:
        self._bounds: dict[int, tuple[Part, Bounds]] = {}
        self._box_arrays: dict[int, tuple[Part, np.ndarray]] = {}
        self._valid: dict[int, tuple[Part, bool]] = {}
        self._classifiers: dict[int, tuple[Part, BRepClass3d_SolidClassifier]] = {}
        #: Parts that would not mesh into a closed solid: none but a mesh engine's.
        self.fallbacks: list[str] = []
        #: Parts found invalid B-reps (BRepCheck), by name, in the order met: read
        #: only where the engine leans on the B-rep itself, a boolean or a repaired
        #: or missing mesh, so collisions with them are approximate (issue #85).
        self.invalid: list[str] = []

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

    def part_box(self, part: Part) -> np.ndarray:
        """The part's box as a (2, 3) array of low and high corners, kept per part."""
        cached = self._box_arrays.get(id(part))
        if cached is None:
            cached = (part, np.array(self.part_bounds(part), dtype=float))
            self._box_arrays[id(part)] = cached
        return cached[1]

    def share_validity(self, other: Engine) -> None:
        """Read and note validity in ``other``'s lists: a referee and its engine, one run."""
        self._valid = other._valid
        self.invalid = other.invalid

    def part_valid(self, part: Part) -> bool:
        """Whether the part is a valid B-rep, checked once per part; an invalid one is noted."""
        cached = self._valid.get(id(part))
        if cached is None:
            topo = part.shape.wrapped
            cached = (part, topo is not None and BRepCheck_Analyzer(topo).IsValid())
            self._valid[id(part)] = cached
            if not cached[1]:
                self.invalid.append(part.name)
        return cached[1]

    def inside(self, part: Part, point: np.ndarray) -> bool:
        """Whether a point lies inside the part, by OCP's classifier, built once per part."""
        cached = self._classifiers.get(id(part))
        if cached is None:
            cached = (part, BRepClass3d_SolidClassifier(part.shape.wrapped))
            self._classifiers[id(part)] = cached
        classifier = cached[1]
        classifier.Perform(gp_Pnt(*(float(c) for c in point)), 1e-6)
        return classifier.State() == TopAbs_IN

    @abstractmethod
    def query(self, tool: Tool) -> Query:
        """Prepare one tool solid for testing against the scene's parts."""


class Scene:
    """The obstacles for one fastener's check: parts a tool is not allowed to meet.

    Build it once per fastener and state (the check loop drops the fastener
    itself, its mates and the ignored parts before handing the rest here) and
    query it for every tool position.
    """

    def __init__(
        self,
        parts: Iterable[Part],
        engine: Engine,
        boxes: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> None:
        """``boxes``, when given, are the parts' (n, 3) low and high corners, in order.

        A check builds a scene per fastener from the same parts less a few, so it
        keeps the whole assembly's boxes once and masks them, rather than
        gathering every part's box again for each.
        """
        self.parts: tuple[Part, ...] = tuple(parts)
        self.engine = engine
        if boxes is None:
            found = [engine.part_bounds(part) for part in self.parts]
            low = np.array([lo for lo, _ in found], dtype=float).reshape(-1, 3)
            high = np.array([hi for _, hi in found], dtype=float).reshape(-1, 3)
            boxes = (low, high)
        self._low, self._high = boxes

    def hits(self, tool: Tool) -> tuple[str, ...]:
        """Every part the tool solid overlaps, by name, in assembly order."""
        return self.contacts(tool)[0]

    def contacts(self, tool: Tool) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """(the parts the tool overlaps, the parts it only grazes), each in assembly order."""
        hits: list[str] = []
        grazes: list[str] = []
        for name, contact in self._scan(tool, stop_at_first=False):
            (hits if contact is Contact.HIT else grazes).append(name)
        return tuple(hits), tuple(grazes)

    def clear(self, tool: Tool) -> bool:
        """True when the tool overlaps nothing (a graze is clear); stops at the first hit."""
        return not any(c is Contact.HIT for _, c in self._scan(tool, stop_at_first=True))

    def _scan(self, tool: Tool, stop_at_first: bool) -> Iterator[tuple[str, Contact]]:
        """Each part the tool meets, and how; with ``stop_at_first``, up to the first hit."""
        query = self.engine.query(tool)
        for index in self._near(query.bounds):
            part = self.parts[index]
            contact = query.contact(part)
            if contact is not Contact.CLEAR:
                yield part.name, contact
                if stop_at_first and contact is Contact.HIT:
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


def pieces_near(lows: np.ndarray, highs: np.ndarray, box: np.ndarray) -> np.ndarray:
    """Indices of the (n, 3) boxes that overlap a (2, 3) box, with the margin."""
    near = (lows - BOX_MARGIN <= box[1]) & (box[0] - BOX_MARGIN <= highs)
    return np.flatnonzero(near.all(axis=1))


def boxes_overlap(a: Bounds, b: Bounds, margin: float = BOX_MARGIN) -> bool:
    """Axis-aligned overlap with a safety margin; the cheap gate before a boolean."""
    (a_min, a_max), (b_min, b_max) = a, b
    return all(a_min[i] - margin <= b_max[i] and b_min[i] - margin <= a_max[i] for i in range(3))
