"""Measuring never changes a part: every boolean runs non-destructively (issue #146).

OCCT's booleans, in their default mode, may raise the tolerances of their inputs in
place. A STEP model's instances of one part share one underlying shape, each with
its own location, so measuring one instance changed what its twin measured next:
on a real model, an insert measured empty past its thread once its twin had been
measured, and the two engines, which measure in different orders, disagreed.
wrenchroom's booleans now all go through ``common`` and ``cut``, in OCCT's
non-destructive mode.
"""

import math

import pytest
from build123d import Box, Cylinder, Location, Pos, RegularPolygon, Shape, extrude
from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_EDGE, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

from fastener_models import hex_prism, socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.engine.exact import common, cut, exact_overlap


def tolerances(shape):
    """The largest tolerance of any edge or vertex of the shape."""
    found = 0.0
    for kind, cast in ((TopAbs_EDGE, TopoDS.Edge), (TopAbs_VERTEX, TopoDS.Vertex)):
        explorer = TopExp_Explorer(shape.wrapped, kind)
        while explorer.More():
            found = max(found, BRep_Tool.Tolerance_s(cast(explorer.Current())))
            explorer.Next()
    return found


def instanced(shape, x=50.0):
    """Another instance of the shape, as a STEP model's: its geometry shared, moved."""
    return Shape.cast(shape.wrapped.Moved(Location((x, 0, 0)).wrapped))


def sleeve():
    return Cylinder(2.5, 5) - Cylinder(1.5, 6)


def near_bore():
    """A rod 1e-7 over the sleeve's bore: a boolean with it raises tolerances."""
    return Pos(0, 0, -3) * Cylinder(1.5000001, 7)


def test_a_destructive_boolean_changes_a_twin_this_case_is_one():
    # The guard: build123d's own boolean, in OCCT's default mode, changes the twin.
    a = sleeve()
    twin = instanced(a)
    before = tolerances(twin)
    _ = a & near_bore()
    assert tolerances(twin) > before


@pytest.mark.parametrize("measure", [common, cut, exact_overlap])
def test_a_boolean_leaves_its_inputs_and_their_twins_as_they_were(measure):
    a, b = sleeve(), near_bore()
    twins = instanced(a), instanced(b, x=-50.0)
    before = [tolerances(shape) for shape in (a, b, *twins)]
    measure(a, b)
    assert [tolerances(shape) for shape in (a, b, *twins)] == before


def test_their_answers_are_the_booleans():
    a, b = Box(10, 10, 10), Pos(5, 5, 5) * Box(10, 10, 10)
    assert common(a, b).volume == pytest.approx(125)
    assert cut(a, b).volume == pytest.approx(875)
    assert exact_overlap(a, b) == pytest.approx(125)
    assert exact_overlap(a, Pos(20, 0, 0) * Box(1, 1, 1)) == 0.0
    assert exact_overlap(a, Pos(10, 0, 0) * Box(10, 10, 10)) == 0.0  # a touch


def clashing_model():
    """Three fasteners measured for a clash, each a way the checker measures one.

    A nut drawn 1 into a block at its corner (its body less its thread); a set
    screw in a hole drawn inside its minor (its core); a socket head with a lid 0.5
    down into it (its head less its shank). Each 300 from the next.
    """
    corner = 13 / math.sqrt(3)
    nut = hex_prism(13, 6.8) - Cylinder(4.0, 30)
    plate = Pos(0, 0, -5) * (Box(200, 200, 10) - Cylinder(4.6, 10))
    block = Pos(corner - 1.0 + 5, 0, 3.4) * Box(10, 30, 3)
    key = extrude(RegularPolygon(1.5 / math.sqrt(3), 6), 1.51)
    set_screw = Pos(0, 0, -2) * Cylinder(1.5, 4) - Pos(0, 0, -1.5) * key
    hub = Pos(0, 0, -10) * Box(30, 30, 20) - Pos(0, 0, -10) * Cylinder(1.0, 21)
    hub += Pos(0, 0, 5.5) * Box(30, 30, 10)
    screw_plate = Pos(0, 0, -5) * (Box(200, 200, 10) - Cylinder(3.2, 10))
    lid = Pos(0, 0, 6 - 0.5 + 5) * Box(30, 30, 10)
    shapes = {
        "nut": nut,
        "plate": plate,
        "block": block,
        "set": Pos(300, 0, 0) * set_screw,
        "hub": Pos(300, 0, 0) * hub,
        "screw": Pos(600, 0, 0) * socket_screw("M6"),
        "screw_plate": Pos(600, 0, 0) * screw_plate,
        "lid": Pos(600, 0, 0) * lid,
    }
    return Assembly([Part(name, shape) for name, shape in shapes.items()])


RULES = [
    {"parts": "nut", "kind": "nut", "size": "M8"},
    {"parts": "set", "kind": "screw", "head": "set", "size": "M3"},
    {"parts": "screw", "kind": "screw", "head": "socket", "size": "M6"},
]


@pytest.mark.parametrize("engine", ["mesh", "exact"])
def test_a_check_runs_no_destructive_boolean_on_any_part(monkeypatch, engine):
    assembly = clashing_model()
    # The parts' edges: a boolean's result shares what it didn't change with its
    # inputs, so a region cut from a part still holds the part's own edges, which a
    # destructive boolean on the region would change.
    edges = [edge.wrapped for part in assembly for edge in part.shape.edges()]
    touched = []
    original = Shape._bool_op  # noqa: SLF001  (build123d's one way into a boolean, spied on)

    def spy(self, args, tools, operation):
        for shape in (self, *args, *tools):
            for edge in shape.edges():
                touched.extend(e for e in edges if edge.wrapped.IsPartner(e))
        return original(self, args, tools, operation)

    monkeypatch.setattr(Shape, "_bool_op", spy)
    config = Config.from_dict({"fasteners": RULES, "checks": {"detect": False}})
    report = check(assembly, config, engine=engine, kit="full")
    assert touched == []
    # The guard: each fastener was measured for a clash, the way it is measured.
    reasons = {result.fastener.name: result.reason for result in report.results}
    assert all(reasons[name].startswith("drawn into ") for name in ("nut", "set", "screw"))
