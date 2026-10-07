"""Parts that won't mesh closed: mended, cheaply referred, and said (issue #85).

On a real export, 10 of 44 parts fell back from the mesh engine to exact booleans,
silently: three invalid shells, and seven valid parts whose tessellation left a
face unmeshed or a hole a few hundredths wide. 204 booleans took 11 of the 12
seconds. Now a part is mended first (a closed face split in two, a small hole
filled); one that still won't close costs a boolean only for a tool piece at its
surface; a part's strays are its own faces', so one poorly met face doesn't make
every probe near the part a boolean; and the report says which parts were left
to the exact engine, and which are invalid B-reps.
"""

import json

import numpy as np
import pytest
from build123d import Box, Cylinder, Pos, Shape
from build123d.topology import downcast
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
from OCP.TopAbs import TopAbs_SHELL
from OCP.TopExp import TopExp_Explorer

import wrenchroom.engine.exact as exact_module
import wrenchroom.engine.mesh as mesh_module
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.engine import make_engine
from wrenchroom.engine.mesh import (
    HOLE_FILL_MM,
    MESH_TOLERANCE,
    MeshEngine,
    Strays,
    _filled,
    face_strays,
    mended_mesh,
)
from wrenchroom.engine.scene import Contact
from wrenchroom.report import EngineNote, Verdict
from wrenchroom.tools.sweep import axial_cylinder

# ---------------------------------------------------------------------------
# Small holes, filled.
# ---------------------------------------------------------------------------

#: A tetrahedron's corners, and its faces wound outward.
CORNERS = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
FACES = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])


@pytest.mark.parametrize("size", [0.05, 0.5, 1.9])
def test_a_small_hole_is_filled_and_the_solid_closed(size):
    # Each face keeps its own corners, as shape_triangles gives them; one is gone.
    vertices = np.vstack([CORNERS[face] * size for face in FACES[1:]])
    triangles = np.arange(len(vertices)).reshape(-1, 3)
    filled = _filled(vertices, triangles)
    assert filled is not None
    mesh, holes = filled
    assert mesh.volume() == pytest.approx(size**3 / 6, rel=1e-6)  # the fill is the lost face
    ((low, high, width),) = holes
    assert width == pytest.approx(size)
    assert np.allclose(low, 0.0)  # the lost face, in the z = 0 plane
    assert np.allclose(high, [size, size, 0.0])


def test_a_hole_too_wide_is_left_open():
    vertices = np.vstack([CORNERS[face] * (HOLE_FILL_MM + 0.1) for face in FACES[1:]])
    assert _filled(vertices, np.arange(len(vertices)).reshape(-1, 3)) is None


def test_an_edge_three_triangles_share_is_no_slip_to_fill():
    # Two tetrahedra glued along one edge only: that edge has four triangles.
    vertices = np.vstack([CORNERS[face] * 0.5 for face in FACES[1:]])
    other = vertices.copy()
    other[:, 2] *= -1  # mirrored below, sharing the edge on the x axis
    both = np.vstack([vertices, other[:, [0, 1, 2]]])
    assert _filled(both, np.arange(len(both)).reshape(-1, 3)) is None


def test_a_closed_mesh_needs_no_fill():
    vertices = np.vstack([CORNERS[face] for face in FACES])
    mesh, holes = _filled(vertices, np.arange(len(vertices)).reshape(-1, 3))
    assert (mesh.volume(), holes) == (pytest.approx(1 / 6), [])


# ---------------------------------------------------------------------------
# A face OCP won't mesh: split, then meshed.
# ---------------------------------------------------------------------------


def test_a_part_whose_face_wont_mesh_is_split_and_meshed(monkeypatch):
    # The issue's screws: a cone OCP leaves unmeshed until its closed faces are split.
    # Its triangles never come for the shape as given, only for the split one.
    real = mesh_module.shape_triangles
    split_shapes = []

    def only_split(shape, tolerance=MESH_TOLERANCE):
        return real(shape, tolerance) if shape in split_shapes else None

    real_split = mesh_module._split_closed  # noqa: SLF001  (the step under test)

    def split(shape):
        split_shapes.append(real_split(shape))
        return split_shapes[-1]

    monkeypatch.setattr(mesh_module, "shape_triangles", only_split)
    monkeypatch.setattr(mesh_module, "_split_closed", split)
    cylinder = Pos(0, 0, 10) * Cylinder(5, 20)
    mended = mended_mesh(cylinder)
    assert mended is not None
    mesh, meshed, holes = mended
    assert meshed is split_shapes[0]
    assert len(meshed.faces()) > len(cylinder.faces())  # its closed faces split
    assert mesh.volume() == pytest.approx(cylinder.volume, rel=0.02)
    assert holes == []


def test_the_engine_names_what_it_mended(monkeypatch):
    real = mesh_module.shape_triangles

    def first_refused(shape, tolerance=MESH_TOLERANCE):
        return None if shape.label == "wall" else real(shape, tolerance)

    monkeypatch.setattr(mesh_module, "shape_triangles", first_refused)
    wall = Box(10, 40, 40)
    wall.label = "wall"
    engine = MeshEngine()
    assert engine.part_mesh(Part("wall", wall)) is not None  # the split shape has no label
    assert (engine.repaired, engine.fallbacks, engine.invalid) == (["wall"], [], [])


# ---------------------------------------------------------------------------
# Strays, face by face.
# ---------------------------------------------------------------------------


def test_a_piece_is_held_to_the_strays_of_the_faces_near_it():
    # A plate with a round boss at one end: flat faces stray nowhere, the boss's
    # side 0.2 outward (convex). Far from the boss, nothing strays.
    plate = Box(100, 20, 4) + Pos(40, 0, 5) * Cylinder(5, 6)
    mesh_module.solid_mesh(plate)  # the triangulation the strays are read from
    strays = face_strays(plate)
    far = strays.within(np.array([-50.0, -10, 2]), np.array([-30.0, 10, 3]))
    near = strays.within(np.array([30.0, -10, 2]), np.array([50.0, 10, 9]))
    assert far == (0.0, 0.0)
    assert near[0] > 0.0  # the boss's round side may stand outside its mesh
    assert strays.overall() == near


def test_the_engine_holds_each_piece_to_the_faces_near_it():
    # A key end 0.1 into a plate's flat top, 150 from its one curved face, a bore
    # (concave: its true surface may stand inside the mesh, so an overlap may be
    # less than it measures). The overlap is 0.31 mm^3 over 6.9 mm^2 of surface.
    # Held to the bore's stray, here 0.036, it would need the referee (0.31 less
    # 0.056 * 6.9 is under the floor); held to the flat faces it is in, nothing
    # strays (0.31 less the key's own 0.02 * 6.9 is over it): a sure hit.
    plate = Box(200, 40, 10) - Pos(90, 0, 0) * Cylinder(5, 11)
    tool = axial_cylinder(1.0, -0.1, 30).placed((-60.0, 0.0, 5.0), (0.0, 0.0, 1.0))
    engine = MeshEngine()
    _, inward = engine.part_strays(Part("bore", plate)).overall()
    assert inward > 0.03  # a vacuity guard: the bore does stray inward
    assert engine.scene([Part("plate", plate)]).hits(tool) == ("plate",)
    assert engine.referred == 0


def test_uniform_strays_are_everywhere():
    strays = Strays.uniform(0.5, 0.25)
    assert strays.within(np.array([1e6, 0, 0]), np.array([1e6 + 1, 1, 1])) == (0.5, 0.25)


def test_a_filled_hole_strays_its_width_where_it_is():
    holes = [(np.array([0.0, 0, 0]), np.array([1.0, 1, 1]), 1.2)]
    strays = Strays(np.empty((0, 3)), np.empty((0, 3)), np.empty(0), np.empty(0)).with_holes(holes)
    assert strays.within(np.array([0.5, 0.5, 0.5]), np.array([2.0, 2, 2])) == (1.2, 1.2)
    assert strays.within(np.array([10.0, 10, 10]), np.array([12.0, 12, 12])) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# A part that won't close: booleans only at its surface.
# ---------------------------------------------------------------------------


def open_box(w, d, t, z_bottom):
    """A slab with no top face: an open shell made a solid, as a broken export is."""
    box = Pos(0, 0, z_bottom + t / 2) * Box(w, d, t)
    sewing = BRepBuilderAPI_Sewing(1e-6)
    for face in sorted(box.faces(), key=lambda f: f.center().Z)[:-1]:  # all but the top
        sewing.Add(face.wrapped)
    sewing.Perform()
    shell = downcast(TopExp_Explorer(sewing.SewedShape(), TopAbs_SHELL).Current())
    return Shape.cast(BRepBuilderAPI_MakeSolid(shell).Solid())


@pytest.fixture
def booleans(monkeypatch):
    count = {"n": 0}
    real = exact_module.exact_overlap

    def counted(a, b):
        count["n"] += 1
        return real(a, b)

    monkeypatch.setattr(exact_module, "exact_overlap", counted)
    return count


def slab_part():
    return Part("slab", open_box(100, 100, 20, 0))  # z 0 to 20, open at the top


@pytest.mark.parametrize(
    ("z0", "z1", "contact", "booleans_run"),
    [
        (5.0, 15.0, Contact.HIT, 0),  # wholly inside, clear of every face: one point says so
        (40.0, 60.0, Contact.CLEAR, 0),  # wholly above: nothing near, no boolean
        (-5.0, 5.0, Contact.HIT, 1),  # through the bottom face: the referee measures it
    ],
)
def test_a_piece_clear_of_an_unclosed_parts_surface_costs_no_boolean(
    booleans, z0, z1, contact, booleans_run
):
    engine = MeshEngine()
    part = slab_part()
    tool = axial_cylinder(2.0, z0, z1).placed((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert engine.part_mesh(part) is None
    assert engine.query(tool).contact(part) is contact
    assert booleans["n"] == booleans_run
    assert engine.fallbacks == ["slab"]


def test_a_piece_through_a_side_face_is_measured_exactly(booleans):
    # Only a face's own neighbourhood costs a boolean. (Where a face is missing,
    # as on this slab's top, nothing is near, and one point decides: one reason a
    # collision with an invalid part is only approximate.)
    engine = MeshEngine()
    tool = axial_cylinder(2.0, 5, 15).placed((50.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert engine.query(tool).contact(slab_part()) is Contact.HIT
    assert booleans["n"] == 1


# ---------------------------------------------------------------------------
# Said in every report.
# ---------------------------------------------------------------------------


def model():
    """key_wall_far: an M6 socket head, a wall 45 above it, here an open shell."""
    head = Pos(0, 0, 3) * Cylinder(5, 6)
    shank = Pos(0, 0, -10) * Cylinder(3, 20)
    plate = Pos(0, 0, -5) * Box(200, 200, 10) - Cylinder(3.2, 12)
    pocket = Pos(0, 0, 4.5) * Box(5, 5, 3.01)  # a square pocket
    return Assembly(
        [
            Part("plate", plate),
            Part("screw", head + shank - pocket),
            Part("lid", open_box(300, 300, 10, 6 + 45)),
        ]
    )


RULE = {"parts": "screw", "kind": "screw", "head": "socket", "size": "M6"}


@pytest.mark.parametrize("engine", ["mesh", "exact"])
def test_both_engines_agree_on_a_broken_part_and_say_what_they_found(engine):
    report = check(model(), Config.from_dict({"fasteners": [RULE]}), engine=engine)
    (result,) = report.results
    assert (result.verdict, result.tool, result.how) == (Verdict.TURNS, "hex-key-5", "short leg in")
    invalid = EngineNote("invalid", ("lid",))
    if engine == "mesh":
        assert report.engine_notes == (EngineNote("unmeshed", ("lid",)), invalid)
    else:
        assert report.engine_notes == (invalid,)  # the exact engine meshes nothing


def test_the_notes_read_the_same_in_every_format():
    report = check(model(), Config.from_dict({"fasteners": [RULE]}))
    lines = report.terminal_lines()
    assert (
        "NOTE 1 part didn't mesh into a closed solid, even mended, so a tool near one is "
        "checked exactly, more slowly: lid"
    ) in lines
    assert (
        "NOTE 1 part is invalid as exported, so a collision with one is approximate: lid" in lines
    )
    document = json.loads(report.json_text())
    assert document["engine_notes"] == [
        {
            "kind": "unmeshed",
            "note": "1 part didn't mesh into a closed solid, even mended, so a tool near one "
            "is checked exactly, more slowly",
            "parts": ["lid"],
        },
        {
            "kind": "invalid",
            "note": "1 part is invalid as exported, so a collision with one is approximate",
            "parts": ["lid"],
        },
    ]
    assert (
        "The engine: 1 part is invalid as exported, so a collision with one is approximate: `lid`."
        in (report.markdown())
    )


def test_a_run_with_nothing_broken_says_nothing():
    clean = Assembly([Part("screw", model()["screw"].shape), Part("plate", model()["plate"].shape)])
    report = check(clean, Config.from_dict({"fasteners": [RULE]}))
    assert report.engine_notes == ()
    assert not any("mesh" in line or "invalid" in line for line in report.terminal_lines())


def test_a_note_counts_its_parts():
    note = EngineNote("invalid", tuple(f"shell{i}" for i in range(9)))
    assert note.text == "9 parts are invalid as exported, so a collision with one is approximate"


def test_the_mesh_engine_s_referee_notes_into_the_same_list():
    engine = make_engine("mesh")
    assert engine.referee.invalid is engine.invalid
