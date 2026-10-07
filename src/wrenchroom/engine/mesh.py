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
A part that won't mesh into a closed solid is mended first (issue #85): real CAD's
tessellation slips, a face OCP won't mesh (a maker's countersink, its seam at an odd
parameter) and a hole a few hundredths across, are cured by splitting closed faces
in two and filling small holes; such a part is named in :attr:`MeshEngine.repaired`.
One that still won't close (an open shell, a broken export) is the referee's, and
named in :attr:`MeshEngine.fallbacks`; but only a tool piece near its surface costs
a boolean, the rest being wholly inside or out, which one point tells.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import TYPE_CHECKING, ClassVar

import numpy as np
from build123d import Shape
from build123d.topology import downcast
from manifold3d import Error, Manifold, Mesh64
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp_Face
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere
from OCP.gp import gp_Pnt, gp_Vec
from OCP.Poly import Poly_Triangulation
from OCP.ShapeFix import ShapeFix_Shape
from OCP.ShapeUpgrade import ShapeUpgrade_ShapeDivideClosed
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location

from wrenchroom.engine.exact import ExactEngine, ExactQuery
from wrenchroom.engine.scene import (
    BOX_MARGIN,
    HIT_MIN_VOLUME,
    Contact,
    Engine,
    Tool,
    contact_of,
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

#: A hole in a part's mesh no wider than this, mm, is the tessellator's slip, and is
#: filled to close the mesh (issue #85): the toolhead's cowlings each had one 0.08
#: across, one also two of 0.9 and 1.2. The filled part may stand off its mesh by
#: as much, which its strays then say.
HOLE_FILL_MM = 2.0

#: Positions closer than this, mm, are one vertex when a mesh is welded to find holes.
_WELD_MM = 1e-6


class MeshEngine(Engine):
    """Collision by mesh booleans: each part meshed once, on first need."""

    name: ClassVar[str] = "mesh"

    def __init__(self, tolerance: float = MESH_TOLERANCE) -> None:
        super().__init__()
        self.tolerance = tolerance
        self._meshes: dict[int, tuple[Part, Manifold | None, Strays]] = {}
        #: Parts whose mesh closed only once mended: a face split, small holes filled.
        #: (:attr:`fallbacks` are the parts that wouldn't close even mended.)
        self.repaired: list[str] = []
        self._surfaces: dict[int, tuple[Part, tuple[np.ndarray, np.ndarray]]] = {}
        #: The exact engine, asked whenever a mesh can't be sure. What it finds of the
        #: parts' validity is this engine's too: one list says which are invalid.
        self.referee = ExactEngine()
        self.referee.share_validity(self)
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

    def part_strays(self, part: Part) -> Strays:
        """How far the part may stand outside its mesh, and inside it, face by face (Strays)."""
        return self._cached(part)[2]

    def part_surface(self, part: Part) -> tuple[np.ndarray, np.ndarray]:
        """A part's surface as boxes, (n, 3) lows and highs, built once (:func:`surface_boxes`)."""
        cached = self._surfaces.get(id(part))
        if cached is None:
            cached = (part, surface_boxes(part.shape, self.tolerance))
            self._surfaces[id(part)] = cached
        return cached[1]

    def _cached(self, part: Part) -> tuple[Part, Manifold | None, Strays]:
        cached = self._meshes.get(id(part))
        if cached is None:
            arrays = shape_triangles(part.shape, self.tolerance)
            mesh = None if arrays is None else _manifold(*arrays)
            strays = Strays.uniform(self.tolerance, self.tolerance)
            if mesh is not None:
                strays = face_strays(part.shape, self.tolerance)  # its triangulation, just made
            else:
                self.part_valid(part)  # the mend and the referee lean on its B-rep
                mended = mended_mesh(part.shape, self.tolerance, arrays)
                if mended is None:
                    self.fallbacks.append(part.name)
                else:
                    mesh, meshed, holes = mended
                    strays = face_strays(meshed, self.tolerance).with_holes(holes)
                    self.repaired.append(part.name)
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
        within what the mesh could have left out. Each piece is held to the strays
        of the part's faces near it alone (issue #85). Anything else is the
        referee's to decide, exactly as ``--exact`` would, graze or not.
        """
        mesh = self._engine.part_mesh(part)
        if mesh is None:
            return self._refer_unclosed(part)
        strays = self._engine.part_strays(part)
        volume = doubt = 0.0
        near: list[tuple[_Measure, float]] = []
        for index in pieces_near(self._lows, self._highs, self._engine.part_box(part)):
            measure = self._measure(int(index), mesh, part)
            if measure is None:  # a plain OCP tool shape that would not mesh
                return self._refer(part)
            outward, inward = strays.within(self._lows[index], self._highs[index])
            volume += measure.volume
            doubt += (inward + TOOL_FACET) * measure.area
            if volume - doubt > HIT_MIN_VOLUME:
                return Contact.HIT
            near.append((measure, outward))
        if volume <= 0 and all(out <= 0 or m.gap(mesh, out) >= out for m, out in near):
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

    def _refer_unclosed(self, part: Part) -> Contact:
        """A part with no closed mesh: booleans, but only for the pieces at its surface.

        A piece whose box comes within reach of none of the part's triangles (a
        face that wouldn't mesh counts as its whole box) has no surface in it, so
        lies wholly inside the part or wholly outside: one point classifies it,
        where a boolean against a heavy part costs tens of milliseconds (issue
        #85). The rest the referee measures, exactly as ``--exact`` would.
        """
        self._engine.referred += 1
        lows, highs = self._engine.part_surface(part)
        reach = self._engine.tolerance + BOX_MARGIN
        total = 0.0
        for index in pieces_near(self._lows, self._highs, self._engine.part_box(part)):
            low, high = self._lows[index], self._highs[index]
            near = bool(((lows - reach <= high) & (low - reach <= highs)).all(axis=1).any())
            piece = None if near else self._piece(int(index))
            if piece is None:
                total += self._referee.overlap(int(index), part)
            elif self._engine.inside(part, (low + high) / 2):
                total += piece.volume()  # all of it inside
            if total > HIT_MIN_VOLUME:
                return Contact.HIT
        return contact_of(total)

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
    return None if arrays is None else _manifold(*arrays)


def _manifold(vertices: np.ndarray, triangles: np.ndarray) -> Manifold | None:
    """Triangles as a closed manifold3d solid, welded by position; None if they aren't one."""
    mesh = Mesh64(
        vert_properties=np.ascontiguousarray(vertices),
        tri_verts=np.ascontiguousarray(triangles.astype(np.uint64)),
    )
    mesh.merge()  # faces share edge nodes by position; weld them into one solid
    manifold = Manifold(mesh)
    if manifold.status() != Error.NoError or manifold.volume() <= 0:
        return None
    return manifold


def mended_mesh(
    shape: Shape,
    tolerance: float = MESH_TOLERANCE,
    arrays: tuple[np.ndarray, np.ndarray] | None = None,
) -> tuple[Manifold, Shape, list[_Hole]] | None:
    """A part that won't mesh closed as it is, mended: (its mesh, what was meshed, its holes).

    Two slips OCP's tessellator makes on real CAD, cured in turn (issue #85): a
    face it won't mesh at all, which a maker's countersink or chamfered tip, a
    full cone with its seam at an odd parameter, can be: splitting every closed
    face in two (and ShapeFix after) gives it faces it meshes. And a hole of a
    few edges where neighbouring faces' edges didn't meet, filled where it is no
    wider than :data:`HOLE_FILL_MM`. None when neither closes it. ``arrays`` are
    the shape's triangles, where they have just been made.
    """
    filled = None if arrays is None else _filled(*arrays)
    if filled is not None:
        return filled[0], shape, filled[1]
    split = _split_closed(shape)
    arrays = shape_triangles(split, tolerance)
    filled = None if arrays is None else _filled(*arrays)
    return None if filled is None else (filled[0], split, filled[1])


def _split_closed(shape: Shape) -> Shape:
    """The shape with every closed face split in two, then ShapeFix'd: faces OCP meshes."""
    divide = ShapeUpgrade_ShapeDivideClosed(shape.wrapped)
    divide.SetNbSplitPoints(1)
    divide.Perform()
    fix = ShapeFix_Shape(divide.Result())
    fix.Perform()
    return Shape.cast(downcast(fix.Shape()))


#: A filled hole: its box's low and high corners, and its width, mm.
_Hole = tuple[np.ndarray, np.ndarray, float]


def _filled(vertices: np.ndarray, triangles: np.ndarray) -> tuple[Manifold, list[_Hole]] | None:
    """Triangles closed into a solid, small holes filled: (the solid, the holes it had).

    The holes are the loops of edges only one triangle has. Each is filled with a
    fan from its centre, running the loop the other way round, so the fill faces
    out as its neighbours do. None where an edge has three triangles or more, a
    loop branches, or a hole is wider than :data:`HOLE_FILL_MM`: no small slip.
    """
    closed = _manifold(vertices, triangles)
    if closed is not None:
        return closed, []
    keys = np.round(vertices / _WELD_MM).astype(np.int64)
    _, first, index = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    points, tris = vertices[first], index.reshape(-1)[triangles]
    tris = tris[
        (tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 2] != tris[:, 0])
    ]
    loops = _boundary_loops(tris)
    if not loops:
        return None
    holes = [
        (
            points[loop].min(axis=0),
            points[loop].max(axis=0),
            float(np.ptp(points[loop], axis=0).max()),
        )
        for loop in loops
    ]
    if max(width for _, _, width in holes) > HOLE_FILL_MM:
        return None
    centres = np.array([points[loop].mean(axis=0) for loop in loops])
    fans = [
        (loop[(i + 1) % len(loop)], loop[i], len(points) + n)
        for n, loop in enumerate(loops)
        for i in range(len(loop))
    ]
    mesh = _manifold(np.vstack([points, centres]), np.vstack([tris, np.array(fans)]))
    return None if mesh is None else (mesh, holes)


def _boundary_loops(tris: np.ndarray) -> list[list[int]]:
    """The loops of edges one triangle alone has, each in its triangles' direction.

    Empty where the mesh can't be mended by filling: an edge with three or more
    triangles, or a vertex two boundary edges leave.
    """
    directed = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    _, where, counts = np.unique(
        np.sort(directed, axis=1), axis=0, return_inverse=True, return_counts=True
    )
    if (counts > 2).any():  # noqa: PLR2004  (two triangles to an edge, no more)
        return []
    following: dict[int, int] = {}
    for start, end in directed[counts[where.reshape(-1)] == 1].tolist():
        if start in following:
            return []
        following[start] = end
    loops: list[list[int]] = []
    seen: set[int] = set()
    for start in following:
        if start in seen:
            continue
        loop, vertex = [], start
        while vertex not in seen:
            seen.add(vertex)
            loop.append(vertex)
            vertex = following.get(vertex, -1)
            if vertex == -1:
                return []
        if vertex != start:
            return []
        loops.append(loop)
    return loops


def surface_boxes(shape: Shape, tolerance: float = MESH_TOLERANCE) -> tuple[np.ndarray, np.ndarray]:
    """Where a part's surface is, as boxes: each triangle's, or a face's that won't mesh.

    (n, 3) lows and highs. The true surface lies within ``tolerance`` of a face's
    triangles, and within a face's own box when it has none.
    """
    topo = shape.wrapped
    if topo is None:
        return np.empty((0, 3)), np.empty((0, 3))
    BRepTools.Clean_s(topo)
    BRepMesh_IncrementalMesh(topo, tolerance, False, MESH_ANGLE, False)
    lows: list[np.ndarray] = []
    highs: list[np.ndarray] = []
    explorer = TopExp_Explorer(topo, TopAbs_FACE)
    while explorer.More():
        face = downcast(explorer.Current())
        explorer.Next()
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is None:
            box = Bnd_Box()
            BRepBndLib.Add_s(face, box, False)
            low, high = box.CornerMin(), box.CornerMax()
            lows.append(np.array([[low.X(), low.Y(), low.Z()]]))
            highs.append(np.array([[high.X(), high.Y(), high.Z()]]))
            continue
        nodes, tris = _face_arrays(triangulation, location)
        corners = nodes[tris]
        lows.append(corners.min(axis=1))
        highs.append(corners.max(axis=1))
    if not lows:
        return np.empty((0, 3)), np.empty((0, 3))
    return np.vstack(lows), np.vstack(highs)


@dataclass(frozen=True)
class Strays:
    """How far a part's true surface may stand off its mesh, face by face, mm.

    One row per face that may stray (a curved one, or a filled hole): its box,
    and how far its true surface may stand outside the mesh and inside it. A
    tool piece is held to the faces near it alone, so one face the tessellator
    met its tolerance poorly on (0.8 mm on the issue's cowlings, where 0.2 was
    asked) leaves the rest of the part sure (issue #85).
    """

    lows: np.ndarray
    highs: np.ndarray
    outward: np.ndarray
    inward: np.ndarray

    @classmethod
    def uniform(cls, outward: float, inward: float) -> Strays:
        """The same strays everywhere: one face as big as all space."""
        far = np.full((1, 3), np.inf)
        return cls(-far, far, np.array([outward]), np.array([inward]))

    def within(self, low: np.ndarray, high: np.ndarray) -> tuple[float, float]:
        """(outward, inward): the most any face near the box ``low``..``high`` may stray."""
        if not len(self.outward):
            return 0.0, 0.0
        reach = np.maximum(self.outward, self.inward)[:, None] + BOX_MARGIN
        near = ((self.lows - reach <= high) & (low - reach <= self.highs)).all(axis=1)
        if not near.any():
            return 0.0, 0.0
        return float(self.outward[near].max()), float(self.inward[near].max())

    def overall(self) -> tuple[float, float]:
        """(outward, inward) over the whole part."""
        far = np.full(3, np.inf)
        return self.within(-far, far)

    def with_holes(self, holes: list[tuple[np.ndarray, np.ndarray, float]]) -> Strays:
        """These strays and filled holes', each its own width both ways."""
        if not holes:
            return self
        lows = np.vstack([self.lows, *(low[None] for low, _, _ in holes)])
        highs = np.vstack([self.highs, *(high[None] for _, high, _ in holes)])
        widths = np.array([width for _, _, width in holes])
        return Strays(
            lows,
            highs,
            np.concatenate([self.outward, widths]),
            np.concatenate([self.inward, widths]),
        )


def mesh_strays(shape: Shape, tolerance: float = MESH_TOLERANCE) -> tuple[float, float]:
    """(outward, inward): how far a part's true surface may stand outside its mesh, and inside.

    The most over the whole part of :func:`face_strays`.
    """
    return face_strays(shape, tolerance).overall()


def face_strays(shape: Shape, tolerance: float = MESH_TOLERANCE) -> Strays:
    """How far a part's true surface may stand off its mesh, face by face.

    Read from the triangulation :func:`solid_mesh` just made: a flat face's mesh
    is exact; a curved face's lies within its achieved deflection, inside the
    true surface where the face is convex (a shaft: the true part stands outside
    the mesh) and outside it where concave (a bore: the true part stands inside).
    A face whose curvature isn't told here (a torus, a spline) counts both ways.
    Most parts are plates and blocks with holes, and have nothing outward: no
    overlap on the mesh is then no overlap at all.
    """
    topo = shape.wrapped
    if topo is None:
        return Strays.uniform(tolerance, tolerance)
    rows: list[tuple[float, ...]] = []
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
        box = Bnd_Box()
        BRepBndLib.Add_s(face, box, False)
        low, high = box.CornerMin(), box.CornerMax()
        rows.append(
            (
                low.X(),
                low.Y(),
                low.Z(),
                high.X(),
                high.Y(),
                high.Z(),
                stray if convex is not False else 0.0,
                stray if convex is not True else 0.0,
            )
        )
    table = np.array(rows, dtype=float).reshape(-1, 8)
    return Strays(table[:, 0:3], table[:, 3:6], table[:, 6], table[:, 7])


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
