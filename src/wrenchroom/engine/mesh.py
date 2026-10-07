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

So a mesh can be wrong only where a tool comes within those strays of a part,
and there the mesh engine doesn't decide: it asks the exact engine, its referee,
which ``--exact`` uses for everything (issue #25: on a graze along an arm the two
used to disagree both ways, the mesh passing a swing the exact engine blocked).
It decides alone only beyond doubt: a hit whose overlap stays over the floor with
the strays taken off every face of it, or a clear whose gap is wider than a part
can stray. Grazes are measured by the referee too, so both engines find the same.
A part that won't mesh into a closed solid (an open shell, a broken export) is
tested by the referee and named in :attr:`MeshEngine.fallbacks`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import TYPE_CHECKING, ClassVar

import numpy as np
from build123d.topology import downcast
from manifold3d import Error, Manifold, Mesh64
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp_Face
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere
from OCP.gp import gp_Pnt, gp_Vec
from OCP.Poly import Poly_Triangulation
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location

from wrenchroom.engine.exact import ExactEngine, ExactQuery
from wrenchroom.engine.scene import (
    HIT_MIN_VOLUME,
    Contact,
    Engine,
    Tool,
    pieces_near,
    shape_bounds,
)
from wrenchroom.solids import (
    AxialCylinder,
    AxialRing,
    RadialBox,
    RadialCylinder,
    ToolSolid,
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
        self._meshes: dict[int, tuple[Part, Manifold | None, tuple[float, float]]] = {}
        #: Parts that would not mesh into a closed solid; tested exactly instead.
        self.fallbacks: list[str] = []
        #: The exact engine, asked whenever a mesh can't be sure.
        self.referee = ExactEngine()
        #: How many tool-part tests the referee decided, for perf reports and tests.
        self.referred = 0
        #: Each placed piece's overlap with each part, measured once: the same
        #: piece comes back attempt after attempt (a socket's mouth on every
        #: extension, a ring's for the stubby). Keyed by the piece and its
        #: placement, and the part's identity (its mesh is kept, so is the part).
        self.measured: dict[tuple[object, ...], _Measure] = {}

    @property
    def meshed(self) -> tuple[str, ...]:
        """Every part tessellated so far, in the order it was first needed."""
        return tuple(part.name for part, _, _ in self._meshes.values())

    def query(self, tool: Tool) -> MeshQuery:
        """Prepare a tool; its pieces are meshed only when a part is near them."""
        return MeshQuery(self, tool)

    def part_mesh(self, part: Part) -> Manifold | None:
        """The part as a closed mesh, built once; None when it won't close."""
        return self._cached(part)[1]

    def part_strays(self, part: Part) -> tuple[float, float]:
        """How far the part may stand outside its mesh, and inside it, mm (see mesh_strays)."""
        return self._cached(part)[2]

    def _cached(self, part: Part) -> tuple[Part, Manifold | None, tuple[float, float]]:
        cached = self._meshes.get(id(part))
        if cached is None:
            mesh = solid_mesh(part.shape, self.tolerance)
            strays = (self.tolerance, self.tolerance)
            if mesh is None:
                self.fallbacks.append(part.name)
            else:
                strays = mesh_strays(part.shape, self.tolerance)  # its triangulation, just made
            # The part rides along so its id cannot be reused while cached.
            cached = (part, mesh, strays)
            self._meshes[id(part)] = cached
        return cached


class MeshQuery:
    """One tool: a mesh per primitive, built lazily, each with its own box."""

    def __init__(self, engine: MeshEngine, tool: Tool) -> None:
        self._engine = engine
        self._tool = tool
        self._built: dict[int, Manifold | None] = {}
        if isinstance(tool, ToolSolid):
            self._primitives: tuple[Primitive, ...] = tool.primitives
            self._matrix = tool.matrix()
            self._lows, self._highs = tool.piece_boxes()
        else:
            self._primitives = ()
            self._matrix = np.eye(4)
            low, high = shape_bounds(tool)
            self._lows, self._highs = np.array([low], dtype=float), np.array([high], dtype=float)

    @cached_property
    def bounds(self) -> Bounds:
        """The box round every piece of the tool."""
        lows, highs = self._lows.min(axis=0), self._highs.max(axis=0)
        return (
            (float(lows[0]), float(lows[1]), float(lows[2])),
            (float(highs[0]), float(highs[1]), float(highs[2])),
        )

    @cached_property
    def _referee(self) -> ExactQuery:
        """The tool as the exact engine tests it, piece by piece, for marginal parts."""
        return self._engine.referee.query(self._tool)

    def contact(self, part: Part) -> Contact:
        """How the tool meets the part, decided on meshes only where they can't be wrong.

        The pieces don't overlap one another (solids.py), so their overlaps with
        the part add up to the whole tool's. The part's mesh may stand inside its
        true surface (on a convex face) or outside it (a concave one, a hole),
        each by no more than :func:`mesh_strays` says; the tool's only outside,
        by :data:`TOOL_FACET`. So a hit is sure when the summed overlap, less
        what the mesh could have added over its whole surface, still passes the
        floor; and a clear is sure when no piece overlaps the mesh nor comes
        within what the mesh could have left out. Anything else is the referee's
        to decide, exactly as ``--exact`` would, graze or not.
        """
        mesh = self._engine.part_mesh(part)
        if mesh is None:
            return self._refer(part)
        outward, inward = self._engine.part_strays(part)
        volume = area = 0.0
        near: list[_Measure] = []
        for index in pieces_near(self._lows, self._highs, self._engine.part_box(part)):
            measure = self._measure(int(index), mesh, part)
            if measure is None:  # a plain OCP tool shape that would not mesh
                return self._refer(part)
            volume += measure.volume
            area += measure.area
            if volume - (inward + TOOL_FACET) * area > HIT_MIN_VOLUME:
                return Contact.HIT
            near.append(measure)
        if volume <= 0 and (outward <= 0 or all(m.gap(mesh, outward) >= outward for m in near)):
            return Contact.CLEAR
        return self._refer(part)

    def _measure(self, index: int, mesh: Manifold, part: Part) -> _Measure | None:
        """One piece's overlap with the part: volume and surface, kept for next time."""
        key = None
        if self._primitives and isinstance(self._tool, ToolSolid):
            key = (self._primitives[index], self._tool.seat, self._tool.axis, id(part))
            cached = self._engine.measured.get(key)
            if cached is not None:
                return cached
        piece = self._piece(index)
        if piece is None:
            return None
        overlap = mesh ^ piece
        volume = overlap.volume()
        measure = _Measure(piece, volume, overlap.surface_area() if volume > 0 else 0.0)
        if key is not None:
            self._engine.measured[key] = measure
        return measure

    def hits(self, part: Part) -> bool:
        """True when the tool overlaps the part by more than HIT_MIN_VOLUME."""
        return self.contact(part) is Contact.HIT

    def _refer(self, part: Part) -> Contact:
        self._engine.referred += 1
        return self._referee.contact(part)

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


@dataclass
class _Measure:
    """One placed piece against one part: what its mesh overlap came to."""

    piece: Manifold
    volume: float
    area: float
    _gaps: dict[float, float] | None = None

    def gap(self, mesh: Manifold, reach: float) -> float:
        """The gap to the part's mesh, looked for out to ``reach``; asked once a reach."""
        if self._gaps is None:
            self._gaps = {}
        if reach not in self._gaps:
            self._gaps[reach] = mesh.min_gap(self.piece, reach)
        return self._gaps[reach]


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


def mesh_strays(shape: Shape, tolerance: float = MESH_TOLERANCE) -> tuple[float, float]:
    """(outward, inward): how far a part's true surface may stand outside its mesh, and inside.

    Read from the triangulation :func:`solid_mesh` just made, face by face: a
    flat face's mesh is exact; a curved face's lies within its achieved
    deflection, inside the true surface where the face is convex (a shaft: the
    true part stands outside the mesh) and outside it where concave (a bore: the
    true part stands inside). A face whose curvature isn't told here (a torus,
    a spline) counts both ways. Most parts are plates and blocks with holes, and
    have nothing outward: no overlap on the mesh is then no overlap at all.
    """
    topo = shape.wrapped
    outward = inward = 0.0
    if topo is None:
        return tolerance, tolerance
    explorer = TopExp_Explorer(topo, TopAbs_FACE)
    while explorer.More():
        face = downcast(explorer.Current())
        explorer.Next()
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() == GeomAbs_Plane:
            continue
        triangulation = BRep_Tool.Triangulation_s(face, TopLoc_Location())
        deflection = triangulation.Deflection() if triangulation is not None else 0.0
        stray = deflection if deflection > 0 else tolerance
        convex = _convex(face, surface)
        if convex is not False:
            outward = max(outward, stray)
        if convex is not True:
            inward = max(inward, stray)
    return outward, inward


def _convex(face: object, surface: BRepAdaptor_Surface) -> bool | None:
    """Whether a cylinder, cone or sphere face bulges out of its solid; None for others."""
    kind = surface.GetType()
    if kind not in (GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Sphere):
        return None
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    point, normal = gp_Pnt(), gp_Vec()
    BRepGProp_Face(face).Normal((u0 + u1) / 2, (v0 + v1) / 2, point, normal)
    if kind == GeomAbs_Sphere:
        centre = surface.Sphere().Location()
    else:
        axis = surface.Cylinder().Axis() if kind == GeomAbs_Cylinder else surface.Cone().Axis()
        origin, direction = axis.Location(), axis.Direction()
        along = gp_Vec(origin, point).Dot(gp_Vec(direction))
        centre = origin.Translated(gp_Vec(direction).Multiplied(along))
    return gp_Vec(centre, point).Dot(normal) > 0


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
