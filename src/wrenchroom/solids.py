"""Tool solids as primitives: the few simple shapes every tool is made of.

A tool is cylinders along its axis, rings round it and arms out to one side, built
in a local frame (seat at the origin, axis +Z pointing out of the joint) and then
placed at a fastener. They are kept here as numbers rather than CAD shapes, so the
mesh engine can test them without the CAD kernel in the loop; the exact engine
asks for :meth:`ToolSolid.shape` and gets the same solids as OCP shapes, built the
way the sweeps built them before M3.

A tool's primitives must not overlap one another. Engines add up a part's overlap
with each primitive, so a region two primitives share would count twice (which
only ever errs toward a hit). Every tool stacks its pieces end to end, which keeps
this true.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
from build123d import Box, Cylinder, Plane, Pos, Rot

if TYPE_CHECKING:
    from build123d import Location, Shape

Vec = tuple[float, float, float]

#: An axis-aligned box as (min corner, max corner).
Bounds = tuple[Vec, Vec]

#: The bore of a ring is cut this much longer than the ring at each end, mm, so
#: the subtraction never leaves a skin on the end faces.
_BORE_OVERRUN = 0.1


@dataclass(frozen=True)
class AxialCylinder:
    """A cylinder on the axis, from ``z0`` to ``z1``: a shaft, a socket's body."""

    radius: float
    z0: float
    z1: float

    def shape(self) -> Shape:
        """The OCP solid, in the local frame."""
        return Pos(0, 0, (self.z0 + self.z1) / 2) * Cylinder(self.radius, self.z1 - self.z0)

    def local_bounds(self) -> Bounds:
        """The axis-aligned box of the solid, in the local frame."""
        r = self.radius
        return ((-r, -r, self.z0), (r, r, self.z1))


@dataclass(frozen=True)
class AxialRing:
    """A ring round the axis, from ``z0`` to ``z1``: a spanner's ring, a socket's mouth."""

    inner: float
    outer: float
    z0: float
    z1: float

    def shape(self) -> Shape:
        """The OCP solid, in the local frame: outer cylinder less a longer bore."""
        solid = AxialCylinder(self.outer, self.z0, self.z1).shape()
        bore = AxialCylinder(self.inner, self.z0 - _BORE_OVERRUN, self.z1 + _BORE_OVERRUN)
        return solid - bore.shape()

    def local_bounds(self) -> Bounds:
        """The axis-aligned box of the solid, in the local frame."""
        return AxialCylinder(self.outer, self.z0, self.z1).local_bounds()


@dataclass(frozen=True)
class RadialCylinder:
    """A cylinder along ``u(phi)`` at height ``z``, from ``r0`` to ``r1``: a key's arm."""

    radius: float
    r0: float
    r1: float
    z: float
    phi_deg: float

    def shape(self) -> Shape:
        """The OCP solid, in the local frame."""
        length = self.r1 - self.r0
        arm = Pos(self.r0 + length / 2, 0, self.z) * Rot(0, 90, 0) * Cylinder(self.radius, length)
        return Rot(0, 0, self.phi_deg) * arm

    def local_bounds(self) -> Bounds:
        """The axis-aligned box of the solid, in the local frame."""
        r = self.radius
        return _rotated_bounds((self.r0, -r, self.z - r), (self.r1, r, self.z + r), self.phi_deg)


@dataclass(frozen=True)
class RadialBox:
    """A box along ``u(phi)`` at height ``z``, from ``r0`` to ``r1``: a handle.

    ``width`` is across the handle (tangential), ``thickness`` along the axis.
    """

    width: float
    thickness: float
    r0: float
    r1: float
    z: float
    phi_deg: float

    def shape(self) -> Shape:
        """The OCP solid, in the local frame."""
        length = self.r1 - self.r0
        handle = Pos(self.r0 + length / 2, 0, self.z) * Box(length, self.width, self.thickness)
        return Rot(0, 0, self.phi_deg) * handle

    def local_bounds(self) -> Bounds:
        """The axis-aligned box of the solid, in the local frame."""
        w, t = self.width / 2, self.thickness / 2
        return _rotated_bounds((self.r0, -w, self.z - t), (self.r1, w, self.z + t), self.phi_deg)


Primitive = AxialCylinder | AxialRing | RadialCylinder | RadialBox


@dataclass(frozen=True)
class ToolSolid:
    """One tool position: primitives in the local frame, and where that frame sits.

    Built local (``seat`` and ``axis`` None) by the sweep's builders, joined with
    ``+``, then placed once at a fastener with :meth:`placed`.
    """

    primitives: tuple[Primitive, ...]
    seat: Vec | None = None
    axis: Vec | None = None

    def __add__(self, other: ToolSolid) -> ToolSolid:
        if self.is_placed or other.is_placed:
            msg = "join tool solids in the local frame, before placing them"
            raise ValueError(msg)
        return ToolSolid(self.primitives + other.primitives)

    @property
    def is_placed(self) -> bool:
        """True once the solid has been put at a seat."""
        return self.seat is not None

    def placed(self, seat: Vec, axis: Vec) -> ToolSolid:
        """The same primitives with their local frame put at ``seat``, +Z along ``axis``."""
        if self.is_placed:
            msg = "a tool solid is placed once, from the local frame"
            raise ValueError(msg)
        return ToolSolid(self.primitives, seat, axis)

    def matrix(self) -> np.ndarray:
        """The 4x4 placement, local to assembly; identity while unplaced."""
        if self.seat is None or self.axis is None:
            return _IDENTITY
        return frame_matrix(self.seat, self.axis)

    def shape(self) -> Shape:
        """The whole tool as one OCP shape: the primitives fused, then placed."""
        shapes = [primitive.shape() for primitive in self.primitives]
        if not shapes:
            msg = "a tool solid needs at least one primitive"
            raise ValueError(msg)
        whole = shapes[0]
        for shape in shapes[1:]:
            whole = whole + shape
        if self.seat is None or self.axis is None:
            return whole
        return frame_location(self.seat, self.axis) * whole

    def bounds(self) -> Bounds:
        """The axis-aligned box of the placed tool: every primitive's box, carried over.

        Never smaller than the true solid's box (a rotated box's box can only
        grow), which is all a prefilter needs.
        """
        boxes = [transform_bounds(p.local_bounds(), self.matrix()) for p in self.primitives]
        lows = np.min([lo for lo, _ in boxes], axis=0)
        highs = np.max([hi for _, hi in boxes], axis=0)
        return _vec(lows), _vec(highs)


# ---------------------------------------------------------------------------
# Frames: one placement, read the same way by both engines.
# ---------------------------------------------------------------------------

_IDENTITY = np.eye(4)
_IDENTITY.flags.writeable = False


@lru_cache(maxsize=4096)
def frame_location(seat: Vec, axis: Vec) -> Location:
    """The OCP placement of a local frame: origin at the seat, +Z along the axis."""
    return Plane(origin=seat, z_dir=axis).location


@lru_cache(maxsize=4096)
def frame_matrix(seat: Vec, axis: Vec) -> np.ndarray:
    """The same placement as a 4x4 matrix, read out of :func:`frame_location`.

    Taken from the OCP transformation rather than recomputed, so the mesh
    engine's tools sit exactly where the exact engine's do, x direction and all.
    """
    trsf = frame_location(seat, axis).wrapped.Transformation()
    matrix = np.eye(4)
    for row in range(3):
        for col in range(4):
            matrix[row, col] = trsf.Value(row + 1, col + 1)
    matrix.flags.writeable = False
    return matrix


def transform_bounds(bounds: Bounds, matrix: np.ndarray) -> Bounds:
    """The axis-aligned box round a box's eight corners after a transform."""
    (x0, y0, z0), (x1, y1, z1) = bounds
    corners = np.array(
        [[x, y, z, 1.0] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)],
    )
    moved = corners @ matrix.T
    return _vec(moved[:, :3].min(axis=0)), _vec(moved[:, :3].max(axis=0))


def _rotated_bounds(low: Vec, high: Vec, phi_deg: float) -> Bounds:
    """The box round ``low..high`` turned by ``phi_deg`` about the local +Z."""
    c, s = math.cos(math.radians(phi_deg)), math.sin(math.radians(phi_deg))
    turn = np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
    return transform_bounds((low, high), turn)


def _vec(values: np.ndarray) -> Vec:
    return (float(values[0]), float(values[1]), float(values[2]))
