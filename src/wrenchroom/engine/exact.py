"""The exact engine: OCP boolean intersections on the B-rep.

Correct and slow (about 2 ms a boolean), kept forever behind ``--exact`` as the
referee for borderline results. A tool built from primitives is fused into one
OCP shape exactly as the sweeps built it before the mesh engine existed, so this
engine reproduces those results unchanged.
"""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, ClassVar

from wrenchroom.engine.scene import HIT_MIN_VOLUME, Engine, Tool, shape_bounds
from wrenchroom.solids import Bounds, ToolSolid

if TYPE_CHECKING:
    from build123d import Shape

    from wrenchroom.assembly import Part


class ExactEngine(Engine):
    """Collision by OCP booleans: the overlap volume of tool and part, exactly."""

    name: ClassVar[str] = "exact"

    def query(self, tool: Tool) -> ExactQuery:
        """Prepare a tool; its OCP shape is built only if a part is near it."""
        return ExactQuery(tool)


class ExactQuery:
    """One tool, as an OCP shape built on first need."""

    def __init__(self, tool: Tool) -> None:
        self._tool = tool

    @cached_property
    def bounds(self) -> Bounds:
        """The tool's box: from its primitives, or from OCP for a plain shape."""
        if isinstance(self._tool, ToolSolid):
            return self._tool.bounds()
        return shape_bounds(self._tool)

    @cached_property
    def shape(self) -> Shape:
        """The tool as one OCP shape."""
        if isinstance(self._tool, ToolSolid):
            return self._tool.shape()
        return self._tool

    def hits(self, part: Part) -> bool:
        """True when the boolean intersection's volume passes the hit floor."""
        return exact_overlap(part.shape, self.shape) > HIT_MIN_VOLUME


def exact_overlap(a: Shape, b: Shape) -> float:
    """The volume two OCP shapes share, mm^3; zero for a touch."""
    pieces = a.intersect(b)
    if pieces is None:
        return 0.0
    return sum(piece.volume for piece in pieces)
