"""Collision queries: does this tool solid run into any part, and which.

This is the exact engine: OCP boolean intersections, correct and slow, kept forever
behind ``--exact`` as the referee for borderline results. The mesh/BVH engine (M3)
implements the same two calls, and nothing outside this module may assume booleans.

A hit is an intersection of more than :data:`HIT_MIN_VOLUME`; a tangent touch is not
a hit (OCP returns nothing for it, measured), which is why tools start 0.3 mm off
the seat rather than on it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wrenchroom.assembly import Part

if TYPE_CHECKING:
    from collections.abc import Iterable

    from build123d import Shape

#: Overlap volume in mm^3 below which an intersection is numerical noise, not a
#: collision. The spec's figure for exact engines.
HIT_MIN_VOLUME = 0.05

#: Bounding boxes grown by this much, mm, before the overlap prefilter; covers
#: the exact kernel finding an intersection a hair outside a tight box.
_BOX_MARGIN = 0.1

_Box = tuple[tuple[float, float, float], tuple[float, float, float]]


class Scene:
    """The obstacles for one fastener's check: parts a tool is not allowed to meet.

    Build it once per fastener (the check loop drops the fastener itself, its
    mates and the ignored parts before handing the rest here) and query it for
    every tool position.
    """

    def __init__(self, parts: Iterable[Part]) -> None:
        self.parts: tuple[Part, ...] = tuple(parts)
        self._boxes: tuple[_Box, ...] = tuple(_box_of(part.shape) for part in self.parts)

    def hits(self, tool: Shape) -> tuple[str, ...]:
        """Every part the tool solid overlaps, by name, in assembly order."""
        return tuple(self._scan(tool, stop_at_first=False))

    def clear(self, tool: Shape) -> bool:
        """True when the tool overlaps nothing; stops at the first offender."""
        return not any(self._scan(tool, stop_at_first=True))

    def _scan(self, tool: Shape, stop_at_first: bool) -> Iterable[str]:
        tool_box = _box_of(tool)
        for part, box in zip(self.parts, self._boxes, strict=True):
            if not _boxes_overlap(box, tool_box):
                continue
            pieces = part.shape.intersect(tool)
            if pieces is None:
                continue
            if sum(piece.volume for piece in pieces) > HIT_MIN_VOLUME:
                yield part.name
                if stop_at_first:
                    return


def _box_of(shape: Shape) -> _Box:
    bound = shape.bounding_box()
    return (tuple(bound.min), tuple(bound.max))


def _boxes_overlap(a: _Box, b: _Box, margin: float = _BOX_MARGIN) -> bool:
    """Axis-aligned overlap with a safety margin; the cheap gate before a boolean."""
    (a_min, a_max), (b_min, b_max) = a, b
    return all(a_min[i] - margin <= b_max[i] and b_min[i] - margin <= a_max[i] for i in range(3))
