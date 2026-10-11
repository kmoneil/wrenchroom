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

import math
from functools import cached_property, lru_cache
from typing import TYPE_CHECKING, ClassVar

import numpy as np
from build123d import Location, Shape
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
from OCP.collections import List_TopoDS_Shape
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

from wrenchroom.engine.scene import (
    HIT_MIN_VOLUME,
    Contact,
    Engine,
    PartOverlap,
    Tool,
    contact_of,
    pieces_near,
    shape_bounds,
)
from wrenchroom.solids import Bounds, ToolSolid, frame_location

if TYPE_CHECKING:
    from collections.abc import Callable

    from wrenchroom.assembly import Part
    from wrenchroom.solids import Primitive

#: A ball's surface for its volume, (36 pi)^(1/3) V^(2/3): no solid has less.
_BALL = (36 * math.pi) ** (1 / 3)

#: A piece of a boolean's answer smaller than this, mm^3, either way, is no sign the
#: answer is wrong: a tenth of the hit floor. A sliver of -0.0014 mm^3 came with
#: 18.2 mm^3 of true overlap on a public model, and the 18.2 is right.
_NOISE = HIT_MIN_VOLUME / 10


class ExactEngine(Engine):
    """Collision by OCP booleans: the overlap volume of tool and part, exactly."""

    name: ClassVar[str] = "exact"

    def __init__(self, *, second_opinion: bool = True) -> None:
        super().__init__()
        #: Whether a tool its booleans call clear of a part is held to the two
        #: meshes (:meth:`into`). Not for a mesh engine's own referee: it is asked
        #: where the meshes couldn't be sure, and theirs is no second opinion there.
        self.second_opinion = second_opinion
        #: Each placed piece's overlap volume with each part, measured once (a
        #: socket's mouth comes back on every extension). Keyed by the piece, its
        #: placement and the part's identity; the part is kept with its box.
        self.measured: dict[tuple[object, ...], float] = {}
        #: A mesh engine of its own, made on first need: what two parts' meshes
        #: share is what their boolean is held to (:meth:`shared`).
        self._meshes: Engine | None = None

    def query(self, tool: Tool) -> ExactQuery:
        """Prepare a tool; its OCP pieces are built only if a part is near them."""
        return ExactQuery(self, tool)

    def shared(self, first: Part, second: Part) -> PartOverlap | None:
        """What two parts share: their boolean, held to their meshes as the mesh engine holds it.

        No pair is cleared by its meshes here (:meth:`parts_apart` says False of
        every one), but a boolean is no surer for being asked by ``--exact``: where
        it comes back empty, or with what no solid could be, the meshes are the
        second opinion (issue #163), and both engines tell the same clashes.
        """
        return self._second().shared(first, second)

    def into(self, tool: Tool, part: Part, said: float, solid: Callable[[int], Shape]) -> bool:
        """Whether a tool the booleans call clear of a part is into it all the same.

        A tool's contact is a boolean a piece, and a boolean that comes back empty
        is a tool that passes (issue #169): a round shaft 13.2 mm^3 into a disc
        whose underside is split along a circle of the shaft's own radius read as
        clear. So a tool not a hit by its booleans' sum, ``said``, is held to what
        its meshes and the part's share, as two parts' clash is
        (:meth:`MeshEngine.into`). ``solid`` gives a piece's own solid, by its index.
        """
        return self.second_opinion and self._second().into(tool, part, said, solid)

    def _second(self) -> Engine:
        if self._meshes is None:
            from wrenchroom.engine.mesh import MeshEngine  # noqa: PLC0415  (it imports this)

            self._meshes = MeshEngine()
            self._meshes.unsure = self.unsure
        return self._meshes


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
        """The pieces' summed overlap with the part, as a contact; stops at a hit.

        Short of a hit, the sum is held to what the tool's meshes and the part's
        share (:meth:`ExactEngine.into`): a boolean that comes back empty is no
        proof the tool is clear.
        """
        total = 0.0
        for index in pieces_near(*self._boxes, self._engine.part_box(part)):
            total += self.overlap(int(index), part)
            if total > HIT_MIN_VOLUME:
                return Contact.HIT
        if self._engine.into(self._tool, part, total, self._piece):
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


def merged(shape: Shape) -> Shape:
    """The shape with each surface's faces merged into one, the edges between them gone.

    A boolean leaves a face it split in its pieces. A head cut from its shank by a
    rod has its bearing face in three, round the rod's rim, and that rim is an
    edge inside a flat face, on nothing's boundary. The next boolean meets it all
    the same: where another part's bore lies along it, a few millionths of a
    millimetre off (a hole drawn 0.1 over the screw, in a part an assembly placed
    a hair askew), OCCT finds the two have nothing in common at all, though the
    head is drawn 15 mm^3 into the part. Merged, the head is the solid it would be
    drawn as, and measures as one. The volume is the same; the shape given is left
    as it was.
    """
    unify = ShapeUpgrade_UnifySameDomain(shape.wrapped, True, True, False)
    unify.Build()
    result = unify.Shape()
    return shape if result.IsNull() else Shape.cast(result)


def exact_common(a: Shape, b: Shape) -> PartOverlap | None:
    """What two OCP shapes share: its volume, surface and box; None where it has no volume.

    Measured near the origin, as :func:`exact_overlap` is, and its box moved back.
    """
    return measured_common(a, b)[0]


def measured_common(a: Shape, b: Shape) -> tuple[PartOverlap | None, bool]:
    """What two OCP shapes share, as :func:`exact_common` gives it, and whether a solid could be it.

    OCCT's boolean fails without saying so (issue #163). Some of its failures show
    in the answer itself: a piece with a volume under nothing, a solid turned
    inside out (two housings drawn in one place, on a public model, came back as
    one piece of -236 mm^3), or a piece with less surface than a ball of its
    volume, which no solid has (an insert in its part: 7.57 mm^3 inside 5.7 mm^2,
    where a ball of that has 18.6). Such an answer is given with False: it is not
    to be taken, whatever its volume. So is an operation OCCT itself calls failed.
    An empty answer shows nothing either way, and is given with True: only the two
    parts' meshes can say it is wrong.
    """
    low, high = shape_bounds(b)
    middle = tuple((lo + hi) / 2 for lo, hi in zip(low, high, strict=True))
    step = Location(tuple(-c for c in middle))
    shared = common(_moved(a, step), _moved(b, step))
    if shared is None:
        return None, False
    solids = shared.solids()
    sound = all(
        possible(piece.volume, piece.area) for piece in solids if abs(piece.volume) > _NOISE
    )
    volume = sum(piece.volume for piece in solids)
    if volume <= 0:
        return None, sound
    corners = [shape_bounds(piece) for piece in solids]
    low = tuple(min(c[0][i] for c in corners) + middle[i] for i in range(3))
    high = tuple(max(c[1][i] for c in corners) + middle[i] for i in range(3))
    area = sum(piece.area for piece in solids)
    where = _moved(shared, Location(middle))  # back where the parts are
    box = (low[0], low[1], low[2]), (high[0], high[1], high[2])
    return PartOverlap(volume, area, *box, where), sound


def possible(volume: float, area: float) -> bool:
    """Whether a solid could have this volume, mm^3, inside this surface, mm^2.

    Not one with no volume or less, and not one with less surface than a ball of
    its volume, the least any solid has (a thousandth is given for rounding).
    """
    return volume > 0 and area >= 0.999 * _BALL * volume ** (2 / 3)


def _moved(shape: Shape, step: Location) -> Shape:
    """The shape moved by a location, its geometry shared.

    build123d's moved copies the whole B-rep first and throws the copy away:
    0.15 ms on a bench part of 28 faces, where this takes 0.004.
    """
    return Shape.cast(shape.wrapped.Moved(step.wrapped))
