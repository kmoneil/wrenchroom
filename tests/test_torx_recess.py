"""A Torx recess is read from its lobes (issue #124).

A Torx recess drawn as makers draw it, its lobes and flutes round, showed no flat
wall, so no recess was read: the head was guessed from its outline and a hex key
turned it. Now six round walls along the axis, the recess inside them, of one
radius, their own axes at one offset and 60 degrees apart, are a Torx recess, its
point to point A twice the offset and the radius, which names its size through
ISO 10664's bands (TORX_RECESS_A), as a rule's across_flats does (#82). A recess
with round or spline walls that is no Torx is unread, and no head is guessed.

The head throughout: an M4 with a button-shaped head 7.6 across and 2.2 high, the
recess 1.4 deep in its top. T25's A runs 4.451 to 4.566.
"""

import math

import pytest
from build123d import (
    Axis,
    Box,
    Circle,
    Cylinder,
    Face,
    Pos,
    RegularPolygon,
    Rot,
    Sphere,
    Spline,
    Wire,
    extrude,
    fillet,
    loft,
)

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.detect import NO_RECESS_READ, find
from wrenchroom.detect.geometry import _main_axis, _round_walls, read_shape
from wrenchroom.detect.sidecar import sidecar_text
from wrenchroom.fasteners import Head, Kind
from wrenchroom.report import Verdict

DEPTH, TOP = 1.4, 2.2
R = (3.8**2 + 1.8**2) / (2 * 1.8)


def head_with(recess):
    rim = Pos(0, 0, 0.2) * Cylinder(3.8, 0.4)
    dome = (Pos(0, 0, 2.2 - R) * Sphere(R)) & Pos(0, 0, 1.3) * Box(8, 8, 1.8)
    head = rim + dome
    if recess is not None:
        head = head - Pos(0, 0, TOP - DEPTH) * extrude(recess, DEPTH + 0.01)
    return head + Pos(0, 0, -5) * Cylinder(2, 10)


def at(radius, degrees):
    a = math.radians(degrees)
    return Pos(radius * math.cos(a), radius * math.sin(a))


def lobed(a, angles=range(0, 360, 60), radii=None):
    """A round core and round lobes, ``a`` point to point: the issue's recess."""
    lobe = 0.122 * a
    radii = radii or [lobe] * len(angles)
    profile = Circle(0.356 * a)
    for angle, radius in zip(angles, radii, strict=True):
        profile += at(a / 2 - radius, angle) * Circle(radius)
    return profile


def hexalobular(a):
    """ISO 10664's shape: six lobes, re = 0.1 A, and six flutes between, ri = 0.17 A."""
    lobe, flute = 0.1 * a, 0.17 * a
    profile = Circle(a / 2 - lobe)
    for k in range(6):
        profile += at(a / 2 - lobe, 60 * k) * Circle(lobe)
    for k in range(6):
        profile -= at(0.37 * a + flute, 60 * k + 30) * Circle(flute)
    return profile


def splined(a):
    """Six lobes drawn as one spline swept down: no cylinder in it."""
    points = []
    for k in range(72):
        t = math.radians(5 * k)
        r = 0.4 * a + 0.1 * a * math.cos(6 * t)
        points.append((r * math.cos(t), r * math.sin(t)))
    return Face(Wire([Spline(*points, periodic=True)]))


def reading(recess, named=None):
    return read_shape(head_with(recess), Kind.SCREW, named)


def checked(name, shape, kit="full", rules=None):
    plate = Pos(0, 0, -5) * Box(30, 30, 10) - Cylinder(2, 30)
    config = Config.from_dict({"fasteners": rules} if rules else {})
    report = check(Assembly([Part("plate", plate), Part(name, shape)]), config, kit=kit)
    (result,) = report.results
    return result


# ---------------------------------------------------------------------------
# Read as Torx.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("draw", [lobed, hexalobular], ids=["core and lobes", "iso 10664"])
@pytest.mark.parametrize("a", [2.80, 3.92, 4.50, 5.60, 6.74])  # T10, T20, T25, T30, T40
def test_a_recess_of_six_round_lobes_is_torx_by_its_point_to_point(draw, a):
    read = reading(draw(a))
    assert (read.head, read.head_guess, read.unread_recess) == (Head.TORX, None, False)
    assert read.torx_mm == pytest.approx(a, abs=1e-6)
    assert read.drive_af is None  # a hex's across flats is another thing


def test_the_issue_s_screw_takes_the_key_its_recess_names():
    # Turned with a 2.5 hex key before, its head guessed a button.
    result = checked("M4x10 screw", head_with(lobed(4.5)))
    assert (result.verdict, result.tool) == (Verdict.TURNS, "torx-key-T25")
    assert result.fastener.head is Head.TORX
    assert result.fastener.basis == (
        "noun 'screw', M4x10; solid: torx, a Torx recess 4.50 point to point"
    )


def test_its_recess_outranks_its_thread_s_table():
    # ISO 14583's M4 takes T20; a T25 recess drawn takes T25, as a rule's would.
    result = checked("M4x10 torx pan head screw", head_with(hexalobular(4.5)))
    assert result.tool == "torx-key-T25"
    result = checked("M4x10 torx pan head screw", head_with(hexalobular(3.92)))
    assert result.tool == "torx-key-T20"


def test_a_recess_between_two_sizes_says_so():
    # 4.40: past T20's 3.970 by more than the loose 0.15, short of T25's 4.451 (#82).
    result = checked("M4x10 screw", head_with(lobed(4.4)))
    assert result.reason == (
        "4.40 mm point to point is no Torx recess's size; the largest that fits, T20; "
        "set tool: in the sidecar"
    )


def test_a_name_s_head_gives_way_to_the_recess_drawn():
    result = checked("M4x10 BHCS", head_with(lobed(4.5)))
    assert (result.fastener.head, result.tool) == (Head.TORX, "torx-key-T25")
    assert "torx (the name says button)" in result.fastener.basis
    assert result.fastener.confidence == "medium"


def test_turned_over_and_head_down_it_reads_the_same():
    screw = Pos(4, -7, 3) * Rot(30, 40, 10) * Rot(180, 0, 0) * head_with(hexalobular(4.5))
    read = read_shape(screw, Kind.SCREW)
    assert (read.head, read.torx_mm) == (Head.TORX, pytest.approx(4.5))


def test_metric_home_holds_no_torx_key_and_says_so():
    result = checked("M4x10 screw", head_with(lobed(4.5)), kit="metric-home")
    assert result.reason == "needs torx-key-T25, which kit metric-home does not hold (full has it)"


def test_a_name_that_is_only_a_size_is_taken_on_its_torx_recess():
    # "M4x10" names no noun: a candidate, taken where its solid shows a drive (#95).
    found = find([Part("M4x10", head_with(lobed(4.5)))])
    (fastener,) = found.fasteners
    assert (fastener.head, fastener.drive_af) == (Head.TORX, pytest.approx(4.5))


# ---------------------------------------------------------------------------
# No Torx, and not guessed.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "recess",
    [
        pytest.param(lobed(4.5, angles=range(0, 360, 72)), id="five lobes"),
        pytest.param(lobed(4.5, angles=range(0, 300, 60)), id="a lobe missing"),
        pytest.param(lobed(4.5, angles=[0, 50, 120, 180, 240, 300]), id="uneven"),
        pytest.param(lobed(4.5, radii=[0.55, 0.45] * 3), id="two radii"),
        pytest.param(
            Circle(1.6)
            + sum((at(1.7, 60 * k) * Circle(0.55 - 0.1 * (k % 2)) for k in range(6)), Circle(0.1)),
            id="two radii, one offset",
        ),
        pytest.param(at(1.5, 0) * Circle(0.5) + at(1.5, 180) * Circle(0.5), id="pin holes"),
        pytest.param(splined(4.5), id="spline lobes"),
    ],
)
def test_round_walls_that_are_no_torx_leave_the_head_unread(recess):
    read = reading(recess)
    assert (read.head, read.head_guess, read.torx_mm) == (None, None, None)
    assert read.unread_recess


def test_an_unread_round_recess_is_not_covered_and_says_why():
    result = checked("M4x10 screw", head_with(splined(4.5)))
    assert (result.verdict, result.reason) == (Verdict.NOT_COVERED, NO_RECESS_READ)


def test_the_spline_recess_is_drawn_with_no_cylinder():
    kinds = {face.geom_type.name for face in head_with(splined(4.5)).faces()}
    assert "BSPLINE" in kinds or "EXTRUSION" in kinds


# ---------------------------------------------------------------------------
# Not recesses: read as before.
# ---------------------------------------------------------------------------


def test_a_hex_socket_with_round_corners_is_a_socket():
    # Its six corner fillets are round walls at 60 degrees: the hex is read first.
    pocket = Pos(0, 0, 4 - 2) * extrude(RegularPolygon(3 / math.sqrt(3), 6), 2.01)
    pocket = fillet(pocket.edges().filter_by(Axis.Z), 0.2)
    screw = Pos(0, 0, 2) * Cylinder(3.5, 4) - pocket + Pos(0, 0, -5) * Cylinder(2, 10)
    read = read_shape(screw, Kind.SCREW)
    assert (read.head, read.drive_af, read.torx_mm) == (Head.SOCKET, pytest.approx(3.0), None)


@pytest.mark.parametrize("scallops", [True, False], ids=["scalloped rim", "studded rim"])
def test_a_knurled_rim_is_no_recess(scallops):
    # Twelve round cuts into the rim, or twelve round studs on it: outside, not a recess.
    head = Pos(0, 0, 1.5) * Cylinder(4, 3)
    for k in range(12):
        knurl = at(4.2 if scallops else 4.0, 30 * k) * Pos(0, 0, 1.5) * Cylinder(0.4, 3)
        head = head - knurl if scallops else head + knurl
    read = read_shape(head + Pos(0, 0, -5) * Cylinder(2, 10), Kind.SCREW)
    assert (read.head, read.torx_mm, read.unread_recess) == (None, None, False)


def test_a_round_pocket_on_the_axis_is_no_recess_wall():
    # A plain hole in the head's top, on its axis: no drive, and no wall a key fits
    # no better than any. The head is guessed by its outline, as a plain head is.
    read = reading(Circle(1.2))
    assert (read.head, read.head_guess, read.unread_recess) == (None, Head.BUTTON, False)


def test_a_spline_cone_leaning_well_off_the_axis_is_no_recess_wall():
    # A cone drawn by a loft, a countersink's 45 degrees: spline faces facing the
    # axis but leaning far off it, as no lobe does.
    sections = [(TOP + 0.01, 1.5), (TOP - 0.4, 0.8), (TOP - 1.2, 0.3)]  # curved: a spline
    cone = loft([Pos(0, 0, z) * Circle(r) for z, r in sections])
    rim = Pos(0, 0, 0.2) * Cylinder(3.8, 0.4)
    dome = (Pos(0, 0, 2.2 - R) * Sphere(R)) & Pos(0, 0, 1.3) * Box(8, 8, 1.8)
    screw = rim + dome - cone + Pos(0, 0, -5) * Cylinder(2, 10)
    assert "BSPLINE" in {face.geom_type.name for face in screw.faces()}  # a guard
    read = read_shape(screw, Kind.SCREW)
    assert (read.head, read.unread_recess) == (None, False)


def test_a_plain_head_is_guessed_by_its_outline_as_before():
    read = reading(None)
    assert (read.head, read.head_guess, read.unread_recess) == (None, Head.BUTTON, False)


@pytest.mark.parametrize(("a", "written"), [(4.5, True), (3.92, False)])
def test_detect_writes_a_recess_its_thread_s_table_wouldn_t_give(a, written):
    # An M4's ISO 14583 recess is T20: one drawn T20 needs no across_flats, one
    # drawn T25 does, so the sidecar checks what the solid showed.
    plate = Pos(0, 0, -5) * Box(30, 30, 10) - Cylinder(2, 30)
    parts = [Part("plate", plate), Part("M4x10 screw", head_with(hexalobular(a)))]
    report = check(Assembly(parts), Config.from_dict({}), kit="full")
    text = sidecar_text(report, "model.step")
    assert ("across_flats:" in text) is written
    assert ("across_flats: 4.5" in text) is written
    assert "head: torx" in text


def test_the_flutes_between_the_lobes_are_no_lobes():
    # ISO 10664's shape: six lobes 0.1 A round at 0.4 A off the axis, and six flutes
    # 0.17 A round at 0.54 A, the part inside them. Only the lobes are round walls.
    a = 4.5
    screw = head_with(hexalobular(a))
    origin, direction = _main_axis(screw)
    lobes, splined = _round_walls(list(screw.faces()), (origin, direction), 3.8)
    assert not splined
    assert {(round(w.offset, 6), round(w.radius, 6)) for w in lobes} == {(0.4 * a, 0.1 * a)}
    assert len({round(w.angle_deg, 3) % 360 for w in lobes}) == 6


def test_a_recess_cut_as_the_issue_cuts_it_is_read_whatever_its_cylinders_are():
    # The issue's: a core and six lobes as solid cylinders, joined and cut from the
    # head. Booleans leave some lobes trimmed cylinders, whose radius build123d
    # doesn't give: read through the surface, all six are lobes.
    recess = Pos(0, 0, 1.5) * Cylinder(1.6, 1.4)
    for k in range(6):
        recess += at(1.7, 60 * k) * Pos(0, 0, 1.5) * Cylinder(0.55, 1.4)
    rim = Pos(0, 0, 0.2) * Cylinder(3.8, 0.4)
    dome = (Pos(0, 0, 2.2 - R) * Sphere(R)) & Pos(0, 0, 1.3) * Box(8, 8, 1.8)
    screw = rim + dome - recess + Pos(0, 0, -5) * Cylinder(2, 10)
    lobes = [f for f in screw.faces() if f.geom_type.name == "CYLINDER" and f.center().Z > 0.9]
    assert any(f.radius is None for f in lobes)  # a guard: some are trimmed
    read = read_shape(screw, Kind.SCREW)
    assert (read.head, read.torx_mm) == (Head.TORX, pytest.approx(4.5))
