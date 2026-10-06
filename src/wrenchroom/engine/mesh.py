"""The mesh engine, the default: meshes for parts and tools, manifold3d booleans.

Every part is tessellated once, on first need; every tool is meshed from its
primitives; a hit is an overlap volume, measured by manifold3d.

manifold3d was chosen over python-fcl by benchmark (2026-10-06). Replaying the
686 tool-part tests the golden bench makes, manifold3d agreed with the exact
engine on every one at about 0.1 ms a test. python-fcl was twice as fast and
missed 10 real hits, every one a probe lying wholly inside a plate: a surface BVH
finds no crossing triangles there. manifold3d measures overlap volume, the
quantity the exact engine already thresholds, so both engines share one rule for
a hit.

How far a mesh can be from the solid it stands for:

- A part is tessellated by OCP to :data:`MESH_TOLERANCE` (0.2 mm, the spec's
  figure) and :data:`MESH_ANGLE`. Flat faces come out exact. A curved face's mesh
  lies up to 0.2 mm inside the true surface: a round part reads up to 0.2 mm
  small, a round hole up to 0.2 mm tight.
- A tool's round faces are polygons drawn round the true circle, never more than
  :data:`TOOL_FACET` outside it, so a mesh tool is never smaller than the real
  one. A ring's bore is drawn inside its circle, for the same reason.

So the engines can disagree only where a tool comes within about 0.2 mm of a
curved part, and there the exact engine (``--exact``) is the referee. A part that
won't mesh into a closed solid (an open shell, a broken export) is tested with the
exact engine instead and named in :attr:`MeshEngine.fallbacks`.
"""

from __future__ import annotations

import math
from functools import cached_property, lru_cache
from typing import TYPE_CHECKING, ClassVar

import numpy as np
from build123d.topology import downcast
from manifold3d import Error, Manifold, Mesh64
from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.Poly import Poly_Triangulation
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location

from wrenchroom.engine.exact import exact_overlap
from wrenchroom.engine.scene import HIT_MIN_VOLUME, Engine, Tool, boxes_overlap, shape_bounds
from wrenchroom.solids import (
    AxialCylinder,
    AxialRing,
    RadialBox,
    RadialCylinder,
    ToolSolid,
    transform_bounds,
)

if TYPE_CHECKING:
    from build123d import Shape

    from wrenchroom.assembly import Part
    from wrenchroom.solids import Bounds, Primitive

#: Chord deviation for tessellating parts, mm. The spec's default.
MESH_TOLERANCE = 0.2

#: Angular deflection for tessellating parts, radians: keeps small radii (an M3
#: shank) from coming out as a handful of sides when 0.2 mm alone would allow it.
MESH_ANGLE = 0.5

#: How far a tool's polygon may stand outside its true circle, mm.
TOOL_FACET = 0.02

#: A ring's bore is cut this much longer than the ring at each end, mm, as the
#: OCP version of the ring is (solids.AxialRing).
_BORE_OVERRUN = 0.1

#: Fewest sides any tool circle gets, however small.
_MIN_SEGMENTS = 8


class MeshEngine(Engine):
    """Collision by mesh booleans: each part meshed once, on first need."""

    name: ClassVar[str] = "mesh"

    def __init__(self, tolerance: float = MESH_TOLERANCE) -> None:
        super().__init__()
        self.tolerance = tolerance
        self._meshes: dict[int, tuple[Part, Manifold | None]] = {}
        #: Parts that would not mesh into a closed solid; tested exactly instead.
        self.fallbacks: list[str] = []

    @property
    def meshed(self) -> tuple[str, ...]:
        """Every part tessellated so far, in the order it was first needed."""
        return tuple(part.name for part, _ in self._meshes.values())

    def query(self, tool: Tool) -> MeshQuery:
        """Prepare a tool; its pieces are meshed only when a part is near them."""
        return MeshQuery(self, tool)

    def part_mesh(self, part: Part) -> Manifold | None:
        """The part as a closed mesh, built once; None when it won't close."""
        cached = self._meshes.get(id(part))
        if cached is None:
            mesh = solid_mesh(part.shape, self.tolerance)
            if mesh is None:
                self.fallbacks.append(part.name)
            # The part rides along so its id cannot be reused while cached.
            cached = (part, mesh)
            self._meshes[id(part)] = cached
        return cached[1]


class MeshQuery:
    """One tool: a mesh per primitive, built lazily, each with its own box."""

    def __init__(self, engine: MeshEngine, tool: Tool) -> None:
        self._engine = engine
        self._tool = tool
        self._built: dict[int, Manifold | None] = {}
        if isinstance(tool, ToolSolid):
            matrix = tool.matrix()
            self._primitives: tuple[Primitive, ...] = tool.primitives
            self._matrix = matrix
            self._boxes = [transform_bounds(p.local_bounds(), matrix) for p in tool.primitives]
        else:
            self._primitives = ()
            self._matrix = np.eye(4)
            self._boxes = [shape_bounds(tool)]

    @cached_property
    def bounds(self) -> Bounds:
        """The box round every piece of the tool."""
        lows = np.min([low for low, _ in self._boxes], axis=0)
        highs = np.max([high for _, high in self._boxes], axis=0)
        return (
            (float(lows[0]), float(lows[1]), float(lows[2])),
            (float(highs[0]), float(highs[1]), float(highs[2])),
        )

    @cached_property
    def _shape(self) -> Shape:
        """The tool as one OCP shape, for parts (or tools) that would not mesh."""
        if isinstance(self._tool, ToolSolid):
            return self._tool.shape()
        return self._tool

    def hits(self, part: Part) -> bool:
        """True when the tool's pieces overlap the part by more than HIT_MIN_VOLUME.

        The pieces don't overlap one another (solids.py), so their overlaps with
        the part add up to the whole tool's; the sum stops once it decides.
        """
        mesh = self._engine.part_mesh(part)
        if mesh is None:
            return exact_overlap(part.shape, self._shape) > HIT_MIN_VOLUME
        part_box = self._engine.part_bounds(part)
        total = 0.0
        for index, box in enumerate(self._boxes):
            if not boxes_overlap(box, part_box):
                continue
            piece = self._piece(index)
            if piece is None:  # a plain OCP tool shape that would not mesh
                return exact_overlap(part.shape, self._shape) > HIT_MIN_VOLUME
            total += (mesh ^ piece).volume()
            if total > HIT_MIN_VOLUME:
                return True
        return False

    def _piece(self, index: int) -> Manifold | None:
        if index not in self._built:
            if self._primitives:
                unit, placed = primitive_mesh(self._primitives[index], self._matrix)
                self._built[index] = unit.transform(np.ascontiguousarray(placed[:3, :]))
            else:
                shape = self._tool
                assert not isinstance(shape, ToolSolid)  # noqa: S101  (narrowing only)
                self._built[index] = solid_mesh(shape, self._engine.tolerance)
        return self._built[index]


# ---------------------------------------------------------------------------
# Parts: OCP tessellation into a closed manifold3d solid.
# ---------------------------------------------------------------------------


def solid_mesh(shape: Shape, tolerance: float = MESH_TOLERANCE) -> Manifold | None:
    """Tessellate an OCP shape into a closed manifold3d solid; None if it isn't one.

    Any triangulation already on the shape is dropped first, so the result
    depends only on the tolerance, never on what meshed the shape before.
    """
    arrays = shape_triangles(shape, tolerance)
    if arrays is None:
        return None
    vertices, triangles = arrays
    mesh = Mesh64(
        vert_properties=np.ascontiguousarray(vertices),
        tri_verts=np.ascontiguousarray(triangles.astype(np.uint64)),
    )
    mesh.merge()  # faces share edge nodes by position; weld them into one solid
    manifold = Manifold(mesh)
    if manifold.status() != Error.NoError or manifold.volume() <= 0:
        return None
    return manifold


def shape_triangles(
    shape: Shape, tolerance: float = MESH_TOLERANCE
) -> tuple[np.ndarray, np.ndarray] | None:
    """An OCP shape's triangles as placed, face by face: vertices (n, 3), indices (m, 3).

    Each face keeps its own vertices, so an edge between two faces appears once
    per face; :func:`solid_mesh` welds them, the HTML view draws them as they
    are (a sharp edge stays sharp). Triangles wind outward. None when a face
    would not mesh, which leaves a hole. The shape's earlier triangulation is
    dropped first, as :func:`solid_mesh` says.
    """
    topo = shape.wrapped
    if topo is None:
        return None
    BRepTools.Clean_s(topo)
    BRepMesh_IncrementalMesh(topo, tolerance, False, MESH_ANGLE, False)
    vertices: list[np.ndarray] = []
    triangles: list[np.ndarray] = []
    offset = 0
    explorer = TopExp_Explorer(topo, TopAbs_FACE)
    while explorer.More():
        face = downcast(explorer.Current())
        explorer.Next()
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is None:
            return None  # a face OCP could not mesh leaves a hole
        nodes, tris = _face_arrays(triangulation, location)
        if face.Orientation() == TopAbs_REVERSED:
            tris = tris[:, [0, 2, 1]]
        vertices.append(nodes)
        triangles.append(tris + offset)
        offset += len(nodes)
    if not triangles:
        return None
    return np.concatenate(vertices), np.concatenate(triangles)


def _face_arrays(
    triangulation: Poly_Triangulation, location: TopLoc_Location
) -> tuple[np.ndarray, np.ndarray]:
    """One face's nodes (placed) and triangles (zero-based), as arrays."""
    node = triangulation.Node
    count = triangulation.NbNodes()
    points = []
    for i in range(1, count + 1):
        p = node(i)
        points.append((p.X(), p.Y(), p.Z()))
    nodes = np.array(points, dtype=np.float64).reshape(-1, 3)
    if not location.IsIdentity():
        trsf = location.Transformation()
        rotation = np.array([[trsf.Value(r, c) for c in (1, 2, 3)] for r in (1, 2, 3)])
        shift = np.array([trsf.Value(r, 4) for r in (1, 2, 3)])
        nodes = nodes @ rotation.T + shift
    triangle = triangulation.Triangle
    tris = np.array(
        [triangle(i).Get() for i in range(1, triangulation.NbTriangles() + 1)],
        dtype=np.int64,
    ).reshape(-1, 3)
    return nodes, tris - 1


# ---------------------------------------------------------------------------
# Tools: each primitive as a unit mesh (cached) and where it goes.
# ---------------------------------------------------------------------------


def _segments(radius: float) -> int:
    """Sides for a circle of this radius, so no side strays over TOOL_FACET from it.

    Sized for the inscribed case (a side's midpoint inside the circle by the
    sagitta), which needs at least as many sides as the circumscribed case.
    """
    if radius <= TOOL_FACET:
        return _MIN_SEGMENTS
    return max(_MIN_SEGMENTS, math.ceil(math.pi / math.acos(1 - TOOL_FACET / radius)))


@lru_cache(maxsize=1024)
def _cylinder(radius: float, height: float) -> Manifold:
    """A cylinder on +Z from 0 to ``height``, its polygon drawn round the circle."""
    sides = _segments(radius)
    return Manifold.cylinder(height, radius / math.cos(math.pi / sides), circular_segments=sides)


@lru_cache(maxsize=1024)
def _ring(inner: float, outer: float, height: float) -> Manifold:
    """A ring on +Z from 0 to ``height``: outer drawn round, bore drawn inside."""
    bore = Manifold.cylinder(
        height + 2 * _BORE_OVERRUN, inner, circular_segments=_segments(inner)
    ).translate((0.0, 0.0, -_BORE_OVERRUN))
    return _cylinder(outer, height) - bore


@lru_cache(maxsize=1024)
def _cube(x: float, y: float, z: float) -> Manifold:
    """A box from the origin to ``(x, y, z)``."""
    return Manifold.cube((x, y, z))


def primitive_mesh(primitive: Primitive, placement: np.ndarray) -> tuple[Manifold, np.ndarray]:
    """A tool primitive as a shared unit mesh and the 4x4 that puts it in the assembly.

    The unit mesh is cached and shared by every primitive of its shape and size;
    ``placement`` is the tool's own (:meth:`ToolSolid.matrix`). The collision
    test and the HTML view both place pieces through here, so what the view
    draws is what was tested.
    """
    unit, local = _unit_mesh(primitive)
    return unit, placement @ local


def _unit_mesh(primitive: Primitive) -> tuple[Manifold, np.ndarray]:
    """A primitive's cached unit mesh, and the 4x4 that puts it in the local frame."""
    match primitive:
        case AxialCylinder(radius=radius, z0=z0, z1=z1):
            return _cylinder(radius, z1 - z0), _translate(0.0, 0.0, z0)
        case AxialRing(inner=inner, outer=outer, z0=z0, z1=z1):
            return _ring(inner, outer, z1 - z0), _translate(0.0, 0.0, z0)
        case RadialCylinder(radius=radius, r0=r0, r1=r1, z=z, phi_deg=phi):
            local = _turn_z(phi) @ _translate(r0, 0.0, z) @ _Z_TO_X
            return _cylinder(radius, r1 - r0), local
        case RadialBox(
            width=width, thickness=thickness, r0=r0, r1=r1, z=z, phi_deg=phi, offset=offset
        ):
            local = _turn_z(phi) @ _translate(r0, offset - width / 2, z - thickness / 2)
            return _cube(r1 - r0, width, thickness), local
    msg = f"no mesh for {primitive!r}"
    raise TypeError(msg)


#: A quarter turn about +Y: carries the +Z axis onto +X.
_Z_TO_X = np.array(
    [[0.0, 0.0, 1.0, 0.0], [0.0, 1.0, 0.0, 0.0], [-1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
)


def _translate(x: float, y: float, z: float) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, 3] = (x, y, z)
    return matrix


def _turn_z(phi_deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(phi_deg)), math.sin(math.radians(phi_deg))
    return np.array([[c, -s, 0.0, 0.0], [s, c, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0, 0, 0, 1]])
