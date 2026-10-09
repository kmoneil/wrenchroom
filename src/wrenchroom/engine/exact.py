"""The exact engine: OCP boolean intersections on the B-rep.

Correct and slow (about 2 ms a boolean), kept forever behind ``--exact`` as the
referee for borderline results. A tool built from primitives is tested piece by
piece, each placed as the sweeps place it, and the overlaps summed, stopping once
they decide; a piece whose box misses the part's is never tested. A tool's pieces
never overlap one another (solids.py), so the sum is the whole tool's overlap,
the same number fusing the pieces first would give, without the fuse, which for a
four-piece open-end spanner cost more than the tests themselves.

Every boolean wrenchroom runs goes through :func:`common` and :func:`cut`, in
OCCT's non-destructive mode: in its default mode a boolean may raise the
tolerances of its inputs in place, and a STEP model's instances of one part share
one underlying shape, so measuring one instance changed what its twin measured
next, and a result depended on what was measured before it (issue #146).
"""

from __future__ import annotations

from functools import cached_property, lru_cache
from typing import TYPE_CHECKING, ClassVar

import numpy as np
from build123d import Location, Shape
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
from OCP.collections import List_TopoDS_Shape

from wrenchroom.engine.scene import (
    HIT_MIN_VOLUME,
    Contact,
    Engine,
    Tool,
    contact_of,
    pieces_near,
    shape_bounds,
)
from wrenchroom.solids import Bounds, ToolSolid, frame_location

if TYPE_CHECKING:
    from wrenchroom.assembly import Part
    from wrenchroom.solids import Primitive


class ExactEngine(Engine):
    """Collision by OCP booleans: the overlap volume of tool and part, exactly."""

    name: ClassVar[str] = "exact"

    def __init__(self) -> None:
        super().__init__()
        #: Each placed piece's overlap volume with each part, measured once (a
        #: socket's mouth comes back on every extension). Keyed by the piece, its
        #: placement and the part's identity; the part is kept with its box.
        self.measured: dict[tuple[object, ...], float] = {}

    def query(self, tool: Tool) -> ExactQuery:
        """Prepare a tool; its OCP pieces are built only if a part is near them."""
        return ExactQuery(self, tool)


class ExactQuery:
    """One tool, as OCP pieces built on first need, each with its own box."""

    def __init__(self, engine: ExactEngine, tool: Tool) -> None:
        self._engine = engine
        self._tool = tool
        self._pieces: dict[int, Shape] = {}

    @cached_property
    def bounds(self) -> Bounds:
        """The tool's box: from its primitives, or from OCP for a plain shape."""
        if isinstance(self._tool, ToolSolid):
            return self._tool.bounds()
        return shape_bounds(self._tool)

    @cached_property
    def _boxes(self) -> tuple[np.ndarray, np.ndarray]:
        """Each piece's box, as (n, 3) arrays of low and high corners."""
        if isinstance(self._tool, ToolSolid):
            return self._tool.piece_boxes()
        low, high = self.bounds
        return np.array([low], dtype=float), np.array([high], dtype=float)

    def overlap(self, index: int, part: Part) -> float:
        """One piece's overlap volume with the part, kept for the next tool that has it.

        A boolean is only as good as the B-rep: the part's validity is read the
        first time one is run on it, and an invalid part noted (issue #85).
        """
        tool = self._tool
        self._engine.part_valid(part)
        if not isinstance(tool, ToolSolid):
            return exact_overlap(part.shape, self._piece(index))
        key = (tool.primitives[index], tool.seat, tool.axis, id(part))
        measured = self._engine.measured.get(key)
        if measured is None:
            measured = exact_overlap(part.shape, self._piece(index))
            self._engine.measured[key] = measured
        return measured

    def _piece(self, index: int) -> Shape:
        if index not in self._pieces:
            tool = self._tool
            if isinstance(tool, ToolSolid):
                shape = _unit_shape(tool.primitives[index])
                if tool.seat is not None and tool.axis is not None:
                    shape = frame_location(tool.seat, tool.axis) * shape
                self._pieces[index] = shape
            else:
                self._pieces[index] = tool
        return self._pieces[index]

    def contact(self, part: Part) -> Contact:
        """The pieces' summed overlap with the part, as a contact; stops at a hit."""
        total = 0.0
        for index in pieces_near(*self._boxes, self._engine.part_box(part)):
            total += self.overlap(int(index), part)
            if total > HIT_MIN_VOLUME:
                return Contact.HIT
        return contact_of(total)

    def hits(self, part: Part) -> bool:
        """True when the pieces' summed overlap with the part passes the hit floor."""
        return self.contact(part) is Contact.HIT


@lru_cache(maxsize=4096)
def _unit_shape(primitive: Primitive) -> Shape:
    """A primitive's OCP solid in its local frame, built once however often it is placed."""
    return primitive.shape()


def exact_overlap(a: Shape, b: Shape) -> float:
    """The volume two OCP shapes share, mm^3; zero for a touch.

    Measured with both moved by one step, b's box centre to the origin (issue
    #107). OCP's tolerances are absolute, 1e-7 mm, but a boolean multiplies
    coordinates, and 35 m out such a product's last digit as a double is about
    2e-7: on Linux a key's arm 0.004 mm into a ring, 0.026 mm^3, measured 365
    mm^3 there. Near the origin an overlap measures as it does wherever its
    model sits.
    """
    low, high = shape_bounds(b)
    step = Location(tuple(-(lo + hi) / 2 for lo, hi in zip(low, high, strict=True)))
    shared = common(_moved(a, step), _moved(b, step))
    return 0.0 if shared is None else sum(solid.volume for solid in shared.solids())


def common(a: Shape, b: Shape) -> Shape | None:
    """What two shapes share, leaving both as they were; None where OCCT fails."""
    return _boolean(BRepAlgoAPI_Common(), a, b)


def cut(a: Shape, b: Shape) -> Shape | None:
    """``a`` less ``b``, leaving both as they were; None where OCCT fails."""
    return _boolean(BRepAlgoAPI_Cut(), a, b)


def _boolean(operation: BRepAlgoAPI_Common | BRepAlgoAPI_Cut, a: Shape, b: Shape) -> Shape | None:
    """One OCCT boolean in its non-destructive mode, which copies what it must change.

    Its result as OCCT gives it: build123d's cleaning, which only merges faces on
    one surface, would change no volume measured here.
    """
    arguments, tools = List_TopoDS_Shape(), List_TopoDS_Shape()
    arguments.Append(a.wrapped)
    tools.Append(b.wrapped)
    operation.SetArguments(arguments)
    operation.SetTools(tools)
    operation.SetNonDestructive(True)
    operation.SetRunParallel(True)
    operation.Build()
    return Shape.cast(operation.Shape()) if operation.IsDone() else None


def _moved(shape: Shape, step: Location) -> Shape:
    """The shape moved by a location, its geometry shared.

    build123d's moved copies the whole B-rep first and throws the copy away:
    0.15 ms on a bench part of 28 faces, where this takes 0.004.
    """
    return Shape.cast(shape.wrapped.Moved(step.wrapped))
