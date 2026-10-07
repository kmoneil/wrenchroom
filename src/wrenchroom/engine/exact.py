"""The exact engine: OCP boolean intersections on the B-rep.

Correct and slow (about 2 ms a boolean), kept forever behind ``--exact`` as the
referee for borderline results. A tool built from primitives is tested piece by
piece, each placed as the sweeps place it, and the overlaps summed, stopping once
they decide; a piece whose box misses the part's is never tested. A tool's pieces
never overlap one another (solids.py), so the sum is the whole tool's overlap,
the same number fusing the pieces first would give, without the fuse, which for a
four-piece open-end spanner cost more than the tests themselves.
"""

from __future__ import annotations

from functools import cached_property, lru_cache
from typing import TYPE_CHECKING, ClassVar

import numpy as np

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
    from build123d import Shape

    from wrenchroom.assembly import Part
    from wrenchroom.solids import Primitive


class ExactEngine(Engine):
    """Collision by OCP booleans: the overlap volume of tool and part, exactly."""

    name: ClassVar[str] = "exact"

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
            total += exact_overlap(part.shape, self._piece(int(index)))
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
    """The volume two OCP shapes share, mm^3; zero for a touch."""
    pieces = a.intersect(b)
    if pieces is None:
        return 0.0
    return sum(piece.volume for piece in pieces)
