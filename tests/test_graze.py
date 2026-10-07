"""Grazes: the engines agree on them, and a report says when one decides (issue #25).

A key's arm lying a few hundredths into a face overlaps it by a sliver whose
volume sits near the 0.05 mm^3 floor, and the two engines used to measure it
differently: the mesh engine passed a swing the exact engine blocked (a torus,
whose tessellation lies inside its curve) and blocked one it passed (a flat
face, the key's polygon standing outside its circle). The mesh engine now
decides alone only beyond doubt and refers the rest to an exact referee, so the
engines agree; and an overlap above noise but at or under the floor is a graze,
which the report names when it decides a verdict.

The cases are the issue's: an M4 button head, its 2.5 mm key's short leg in, a
lid stopping the driver and the long leg, and a part round the screw rising
``depth`` into the arm's underside at every angle.
"""

import json

import pytest
from build123d import Box, Cylinder, Pos, Sphere, Torus

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.engine import make_engine
from wrenchroom.engine.mesh import Strays, mesh_strays, solid_mesh
from wrenchroom.engine.scene import GRAZE_MIN_VOLUME, HIT_MIN_VOLUME, Contact, contact_of
from wrenchroom.report import PASSED_OVER_SHOWN, FastenerResult, Report, Verdict, attempt_text
from wrenchroom.tools.hex_keys import ISO_2936
from wrenchroom.tools.sweep import axial_cylinder

KEY = ISO_2936[2.5]
ARM_BOTTOM = 2.2 + 0.3 + KEY.short_mm - KEY.radius
RULE = {"parts": "screw", "kind": "screw", "head": "button", "size": "M4", "axis": [0, 0, 1]}


def torus(depth):
    return Pos(0, 0, ARM_BOTTOM + depth - 10) * Torus(40, 10)


def flat(depth):
    top = ARM_BOTTOM + depth
    return Pos(0, 0, top - 2) * (Cylinder(70, 4) - Cylinder(12, 4))


def model(under):
    return Assembly(
        [
            Part("base", Pos(0, 0, -3) * (Box(200, 200, 6) - Cylinder(2.2, 6))),
            Part("screw", Pos(0, 0, -6) * Cylinder(2, 12) + Pos(0, 0, 1.1) * Cylinder(3.8, 2.2)),
            Part("under", under),
            Part("lid", Pos(0, 0, 55) * Box(200, 200, 4)),
        ]
    )


def run(under, engine):
    config = Config.from_dict({"fasteners": [RULE], "checks": {"detect": False}})
    return check(model(under), config, kit="full", engine=engine)


# ---------------------------------------------------------------------------
# The rule for a contact.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("volume", "contact"),
    [
        (0.0, Contact.CLEAR),
        (GRAZE_MIN_VOLUME, Contact.CLEAR),  # noise: a tangent touch
        (0.001, Contact.GRAZE),
        (HIT_MIN_VOLUME, Contact.GRAZE),  # at the floor, still not a hit
        (0.0501, Contact.HIT),
        (10.0, Contact.HIT),
    ],
)
def test_contact_of_a_volume(volume, contact):
    assert contact_of(volume) is contact


def test_a_graze_is_clear_to_a_scene_but_named_by_it(engine):
    scene = make_engine(engine).scene([Part("under", flat(0.004))])
    arm = axial_cylinder(KEY.radius, 0, 40).placed(
        (0.0, 0.0, ARM_BOTTOM + KEY.radius), (1.0, 0.0, 0.0)
    )
    assert scene.contacts(arm) == ((), ("under",))
    assert scene.hits(arm) == ()
    assert scene.clear(arm)
    deep = make_engine(engine).scene([Part("under", flat(0.2))])
    assert deep.contacts(arm) == (("under",), ())
    assert not deep.clear(arm)


# ---------------------------------------------------------------------------
# The issue's cases: the same verdict on both engines, at every depth.
# ---------------------------------------------------------------------------

#: (part, depth, verdict, grazed): measured exactly, and now by both engines.
CASES = [
    *[(torus, d, Verdict.TURNS, True) for d in (0.005, 0.01, 0.02, 0.04, 0.06)],
    *[(torus, d, Verdict.BLOCKED, False) for d in (0.08, 0.12, 0.2)],
    *[(flat, d, Verdict.TURNS, True) for d in (0.001, 0.002, 0.004, 0.006)],
    *[(flat, d, Verdict.BLOCKED, False) for d in (0.008, 0.012)],
]


@pytest.mark.parametrize(
    ("under", "depth", "verdict", "grazed"),
    CASES,
    ids=[f"{u.__name__}-{d}" for u, d, _, _ in CASES],
)
def test_both_engines_agree_on_the_graze(engine, under, depth, verdict, grazed):
    (result,) = run(under(depth), engine).results
    assert (result.verdict, result.tool) == (verdict, "hex-key-2.5")
    assert result.grazes == (("under",) if grazed else ())
    if verdict is Verdict.TURNS:
        assert result.how == "short leg in"


def test_the_mesh_engine_refers_a_graze_and_decides_the_rest_alone():
    mesh = make_engine("mesh")
    config = Config.from_dict({"fasteners": [RULE], "checks": {"detect": False}})
    check(model(torus(0.06)), config, kit="full", engine="mesh")
    assert mesh.referred == 0  # a fresh engine: nothing referred yet
    scene = mesh.scene([Part("under", torus(0.06))])
    arm = axial_cylinder(KEY.radius, 0, 60).placed(
        (0.0, 0.0, ARM_BOTTOM + KEY.radius), (1.0, 0.0, 0.0)
    )
    assert scene.contacts(arm) == ((), ("under",))
    assert mesh.referred == 1  # within what the mesh may stray: the referee's
    far = axial_cylinder(KEY.radius, 0, 60).placed((0.0, 0.0, ARM_BOTTOM + 5), (1.0, 0.0, 0.0))
    assert scene.contacts(far) == ((), ())
    deep = axial_cylinder(KEY.radius, 0, 60).placed((0.0, 0.0, ARM_BOTTOM - 1), (1.0, 0.0, 0.0))
    assert scene.contacts(deep) == (("under",), ())
    assert mesh.referred == 1  # clear by a mile, and a hit beyond doubt: no referee


# ---------------------------------------------------------------------------
# How far a part's mesh can stray, and which way.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("shape", "outward", "inward"),
    [
        (Box(10, 10, 10), False, False),  # flat faces mesh exactly
        (Cylinder(5, 20), True, False),  # a shaft: the true part outside its mesh
        (Box(40, 40, 10) - Cylinder(6, 11), False, True),  # a hole: inside it
        (Sphere(10), True, False),
        (Torus(40, 10), True, True),  # a torus isn't told apart: both ways
    ],
    ids=["box", "shaft", "plate with a hole", "sphere", "torus"],
)
def test_a_part_strays_only_where_its_faces_curve_and_only_the_way_they_curve(
    shape, outward, inward
):
    assert solid_mesh(shape) is not None
    out, into = mesh_strays(shape)
    assert (out > 0, into > 0) == (outward, inward)
    assert out <= 0.25
    assert into <= 0.25


# ---------------------------------------------------------------------------
# The report.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def grazed_report():
    return run(flat(0.004), "exact")


def test_every_format_says_the_verdict_rests_on_a_graze(grazed_report):
    (result,) = grazed_report.results
    assert result.headline == "screw: turns with hex-key-2.5, short leg in; grazing under"
    (turning,) = [a for a in result.attempts if a.turns]
    assert attempt_text(turning).endswith("; grazed under")
    lines = grazed_report.terminal_lines()
    assert "NOTE marginal: screw turns with hex-key-2.5, the tool grazing under" in lines
    assert "#### Marginal" in grazed_report.markdown()
    assert "- `screw`: turns with `hex-key-2.5`, grazing `under`" in grazed_report.markdown()
    (entry,) = json.loads(grazed_report.json_text())["fasteners"]
    assert entry["grazes"] == ["under"]
    assert grazed_report.exit_code == 0  # a note, not a failure


def test_a_clean_verdict_says_nothing_of_grazes():
    report = run(flat(-0.5), "exact")  # 0.5 below the arm: clear all round
    (result,) = report.results
    assert (result.verdict, result.grazes) == (Verdict.TURNS, ())
    assert not any("marginal" in line for line in report.terminal_lines())
    assert "Marginal" not in report.markdown()
    assert json.loads(report.json_text())["fasteners"][0]["grazes"] == []


def test_a_blocked_verdict_carries_no_grazes():
    (result,) = run(flat(0.012), "exact").results
    assert (result.verdict, result.grazes) == (Verdict.BLOCKED, ())


@pytest.mark.parametrize("count", [PASSED_OVER_SHOWN, PASSED_OVER_SHOWN + 1])
def test_a_long_list_of_marginal_verdicts_is_cut(grazed_report, count):
    (result,) = grazed_report.results
    many = tuple(
        FastenerResult(
            result.fastener, result.verdict, tool=result.tool, how=result.how, grazes=("under",)
        )
        for _ in range(count)
    )
    lines = Report(model="m", kit="full", results=many).terminal_lines()
    assert sum(line.startswith("NOTE marginal:") for line in lines) == PASSED_OVER_SHOWN
    cut = [line for line in lines if line.startswith("NOTE and")]
    assert cut == (
        []
        if count == PASSED_OVER_SHOWN
        else ["NOTE and 1 more marginal (the JSON lists every one)"]
    )


def test_a_key_that_grazes_but_cannot_swing_far_enough_carries_no_grazes(engine):
    # The flat ring 0.004 into the arm everywhere, and a wall round the screw at the
    # arm's height with a 40 degree gap: the arm is clear (grazing) at 345, 0 and 15
    # degrees only, 30 of the 60 a hex key needs. Blocked, and no graze reported.
    wall = Pos(0, 0, ARM_BOTTOM + 1.4) * (Cylinder(40, 4) - Cylinder(30, 5)) - Pos(
        35, 0, ARM_BOTTOM + 1.4
    ) * Box(12, 2 * 35 * 0.364, 6)
    assembly = model(flat(0.004))
    assembly = Assembly([*assembly.parts, Part("wall", wall)])
    config = Config.from_dict({"fasteners": [RULE], "checks": {"detect": False}})
    (result,) = check(assembly, config, kit="full", engine=engine).results
    assert result.verdict is Verdict.BLOCKED
    assert any(attempt.grazes for attempt in result.attempts)  # it did graze
    assert result.grazes == ()


# ---------------------------------------------------------------------------
# Each stray bounds its own side: what the mesh may leave out, and add.
# ---------------------------------------------------------------------------


def _with_strays(monkeypatch, outward, inward):
    from wrenchroom.engine.mesh import MeshEngine  # noqa: PLC0415

    strays = Strays.uniform(outward, inward)
    monkeypatch.setattr(MeshEngine, "part_strays", lambda self, part: strays)
    return make_engine("mesh")


def test_a_gap_inside_the_outward_stray_is_referred(monkeypatch):
    # A key end 0.05 over a block's face, inside the boxes' 0.1 margin: flat faces,
    # which a mesh draws exactly. Told the part may stand 0.5 outside its mesh,
    # the engine can't call it clear alone.
    part = Part("block", Box(10, 10, 10))
    tool = axial_cylinder(2, 5.05, 8).placed((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    loose = _with_strays(monkeypatch, 0.5, 0.0)
    assert loose.scene([part]).contacts(tool) == ((), ())
    assert loose.referred == 1
    tight = _with_strays(monkeypatch, 0.0, 0.5)  # the inward stray is no help here
    assert tight.scene([part]).contacts(tool) == ((), ())
    assert tight.referred == 0


@pytest.mark.parametrize(("inward", "referred"), [(0.0, 1), (5.0, 1)])
def test_a_thin_overlap_is_a_sure_hit_only_net_of_both_strays(monkeypatch, inward, referred):
    # A 4 mm square end 0.03 into a block's face: 0.48 mm^3 by the mesh, and the
    # overlap's faces some 32 mm^2. Less the key's 0.02 facet over them it is under
    # the floor, so even with no inward stray the referee decides (a hit, exactly).
    part = Part("block", Box(10, 10, 10))
    tool = axial_cylinder(2.0, 4.97, 8).placed((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    engine = _with_strays(monkeypatch, 0.0, inward)
    assert engine.scene([part]).contacts(tool) == (("block",), ())
    assert engine.referred == referred


def test_a_deep_overlap_is_a_sure_hit_whatever_the_strays(monkeypatch):
    part = Part("block", Box(10, 10, 10))
    tool = axial_cylinder(2.0, 3.0, 8).placed((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    engine = _with_strays(monkeypatch, 0.2, 0.2)
    assert engine.scene([part]).contacts(tool) == (("block",), ())
    assert engine.referred == 0
