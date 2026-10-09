"""Build order (M8): each fastener checked in the step of the build that adds it.

A sidecar's ``build:`` lists the steps, each adding parts. A fastener is checked in
the step that adds it, among the parts added by then, its joint in the step its last
member arrives in. A bolt put in before its nut need only go in; a nut put in before
its bolt is held by nothing, unless it is a fixed thread or its trap holds it. Every
part is added by one step exactly, else the build isn't checked and the run fails, as
for any sidecar problem.
"""

import json

import pytest
from build123d import Box, Compound, Cylinder, Pos, Rot, Sphere, export_step
from click.testing import CliRunner

from fastener_models import hex_prism
from fixture_models import bolt_with_slotted_nut, hex_bolt, hex_nut_shape, slotted_pocket
from wrenchroom.assembly import Assembly, Part
from wrenchroom.build import Step, plan
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import BuildStep, Config, ConfigError
from wrenchroom.report import Verdict

M6_SOCKET = {"kind": "screw", "head": "socket", "size": "M6"}
M8_HEX = {"kind": "screw", "head": "hex", "size": "M8"}
M8_NUT = {"kind": "nut", "size": "M8"}
JOINT = [{"parts": "bolt", **M8_HEX}, {"parts": "nut", **M8_NUT}]


def socket_screw(x=0.0, length=20.0):
    """An M6 socket head screw at x, its seat at z = 6, its key's socket 5 across."""
    shank = Pos(x, 0, -length / 2) * Cylinder(3, length)
    head = Pos(x, 0, 3) * Cylinder(5, 6)
    return shank + head - Pos(x, 0, 0) * hex_prism(5, 3.01, 3)


def plate(*xs, radius=3.2):
    """A plate 10 thick under z = 0, holes at each x."""
    body = Pos(0, 0, -5) * Box(600, 200, 10)
    for x in xs:
        body -= Pos(x, 0, -5) * Cylinder(radius, 11)
    return body


def slab(z, x=0.0, width=600.0):
    """A slab 10 thick whose underside is at z, centred on x."""
    return Pos(x, 0, z + 5) * Box(width, 200, 10)


def run(parts, rules, steps, engine="mesh", **sidecar):
    """Check parts given as (name, shape), the sidecar's rules and build ``steps``."""
    config = Config.from_dict({"fasteners": list(rules), "build": steps, **sidecar})
    assembly = Assembly([Part(name, shape) for name, shape in parts])
    return check(assembly, config, kit="full", engine=engine)


def built(report):
    """Each fastener in the build, as (verdict, step, checked_in)."""
    return {p.result.name: (p.result.verdict, p.step, p.checked_in) for p in report.build.placed}


def service(report):
    return {r.name: r.verdict for r in report.results}


def build_lines(report):
    """The terminal's build lines: the headline to its last FAIL or WARN."""
    lines = report.terminal_lines()
    start = next(i for i, line in enumerate(lines) if line.startswith("build: "))
    end = start + 1
    while end < len(lines) and lines[end].startswith(("  ", "FAIL ", "WARN build")):
        end += 1
    return lines[start:end]


# ---------------------------------------------------------------------------
# The sidecar.
# ---------------------------------------------------------------------------


def test_the_build_is_read_in_order():
    config = Config.from_dict(
        {
            "build": [
                {"step": "frame", "add": ["frame_*", "rail_*"]},
                {"step": "cover", "add": ["cover", "*"], "model": "cover_up.step"},
            ]
        }
    )
    assert config.build == (
        BuildStep("frame", ("frame_*", "rail_*")),
        BuildStep("cover", ("cover", "*"), "cover_up.step"),
    )


def test_no_build_is_none():
    assert Config.from_dict({}).build == ()


@pytest.mark.parametrize(
    ("build", "message"),
    [
        ({"step": "a"}, "build must be a list"),
        ([], "build: lists no steps"),
        (["frame"], r"build\[0\]: must be a mapping"),
        (
            [{"step": "a", "add": ["*"], "loose": ["x"]}],
            r"build\[0\]: unknown key\(s\) \['loose'\]",
        ),
        ([{"add": ["*"]}], r"build\[0\]: 'step' is required"),
        ([{"step": "a"}], r"build\[0\]: 'add' is required"),
        ([{"step": " ", "add": ["*"]}], r"build\[0\]: step needs a name"),
        ([{"step": 3, "add": ["*"]}], r"build\[0\]: step must be a string"),
        ([{"step": "a", "add": "frame"}], r"build\[0\]: add must be a list"),
        ([{"step": "a", "add": [3]}], r"build\[0\]: add\[0\] must be a string"),
        ([{"step": "a", "add": []}], r"build\[0\]: step 'a' adds nothing"),
        (
            [{"step": "a", "add": ["x"]}, {"step": "a", "add": ["y"]}],
            r"build\[1\]: step 'a' is named twice",
        ),
        (
            [{"step": "a", "add": ["*"]}, {"step": "b", "add": ["x", "*"]}],
            r"steps 'a' and 'b' both add '\*', the parts no other step adds: one step can",
        ),
    ],
)
def test_a_build_the_sidecar_can_t_mean_is_a_config_error(build, message):
    with pytest.raises(ConfigError, match=message):
        Config.from_dict({"build": build}, source="s.yaml")


# ---------------------------------------------------------------------------
# The plan: which step adds each part.
# ---------------------------------------------------------------------------


def boxes(*names):
    return Assembly([Part(name, Pos(20 * i, 0, 0) * Box(5, 5, 5)) for i, name in enumerate(names)])


def test_each_part_is_added_by_the_step_whose_glob_names_it():
    steps = (BuildStep("a", ("frame_*",)), BuildStep("b", ("cover", "frame_x")))
    found = plan(steps, boxes("frame_1", "frame_2", "cover"), lambda _: False)
    assert found.steps == (Step("a", ("frame_1", "frame_2")), Step("b", ("cover",)))
    assert dict(found.added_in) == {"frame_1": 0, "frame_2": 0, "cover": 1}
    assert found.sound
    # frame_x names nothing: a renamed part, as an unmatched rule is.
    assert found.unmatched == (("b", "frame_x"),)


def test_the_catch_all_takes_every_part_no_other_step_adds():
    steps = (BuildStep("frame", ("*",)), BuildStep("cover", ("cover",)))
    found = plan(steps, boxes("a", "b", "cover"), lambda _: False)
    assert found.steps == (Step("frame", ("a", "b")), Step("cover", ("cover",)))
    assert (found.unplaced, found.twice, found.unmatched) == ((), (), ())


def test_a_part_two_globs_of_one_step_name_is_added_once():
    found = plan((BuildStep("a", ("x*", "*y")),), boxes("xy"), lambda _: False)
    assert (found.steps, found.twice) == ((Step("a", ("xy",)),), ())


def test_a_part_no_step_adds_and_one_two_steps_add_are_said():
    steps = (BuildStep("a", ("x", "y")), BuildStep("b", ("y",)), BuildStep("c", ("y",)))
    found = plan(steps, boxes("x", "y", "z"), lambda _: False)
    assert found.unplaced == ("z",)
    assert found.twice == (("y", ("a", "b", "c")),)
    assert not found.sound
    # A part added twice is in no step's parts: the plan isn't one to check.
    assert found.steps[0].parts == ("x",)


def test_an_ignored_part_need_not_be_added_and_its_glob_names_something():
    steps = (BuildStep("a", ("x", "cable")),)
    found = plan(steps, boxes("x", "cable", "hose"), lambda name: name in {"cable", "hose"})
    assert (found.unplaced, found.unmatched, found.steps) == ((), (), (Step("a", ("x",)),))
    assert "cable" not in found.added_in


def test_a_part_drawn_as_two_solids_comes_with_its_first():
    assembly = Assembly(
        [
            Part("x", Box(5, 5, 5)),
            Part("lock", Pos(20, 0, 0) * Box(5, 5, 5)),
            Part("lock#2", Pos(40, 0, 0) * Box(5, 5, 5), piece_of="lock"),
        ]
    )
    steps = (BuildStep("a", ("x",)), BuildStep("b", ("lock*",)))
    found = plan(steps, assembly, lambda _: False)
    assert found.steps[1] == Step("b", ("lock",))
    assert (found.added_in["lock#2"], found.unplaced, found.twice) == (1, (), ())


def test_a_glob_naming_only_a_surface_names_something():
    assembly = Assembly([Part("x", Box(5, 5, 5))], surfaces=("decal",))
    found = plan((BuildStep("a", ("x", "decal")),), assembly, lambda _: False)
    assert found.unmatched == ()


# ---------------------------------------------------------------------------
# A screw in its step: reachable then, buried later, or buried already.
# ---------------------------------------------------------------------------


def buried():
    """Two M6 screws under a cover 15 over their seats: no key gets on either."""
    return [
        ("plate", plate(-100, 100)),
        ("early", socket_screw(-100)),
        ("late", socket_screw(100)),
        ("cover", slab(6 + 15)),
    ]


BURIED_RULES = [{"parts": "early", **M6_SOCKET}, {"parts": "late", **M6_SOCKET}]
BURIED_STEPS = [
    {"step": "base", "add": ["plate", "early"]},
    {"step": "cover", "add": ["cover"]},
    {"step": "late", "add": ["late"]},
]


def test_a_screw_buried_by_a_later_step_turns_in_its_own(engine):
    report = run(buried(), BURIED_RULES, BURIED_STEPS, engine)
    assert service(report) == {"early": Verdict.BLOCKED, "late": Verdict.BLOCKED}
    assert built(report) == {
        "early": (Verdict.TURNS, "base", "base"),
        "late": (Verdict.BLOCKED, "late", "late"),
    }
    late = next(p.result for p in report.build.placed if p.result.name == "late")
    assert late.blockers == ("cover",)
    assert build_lines(report) == [
        "build: 3 steps, 2 fasteners; the first failure is in late",
        "  base   1 fastener: 1 turn",
        "  cover  no fasteners",
        "  late   1 fastener: 1 blocked",
        "FAIL late: late  hex-key-5  blocked  cover (added in cover)",
    ]
    assert (report.build.exit_code, report.exit_code) == (1, 1)


def test_the_build_s_failure_fails_a_run_whose_service_passes():
    # The cover taken off for service: the late screw turns there, but went in after it.
    sidecar = {
        "states": {"cover-off": {"remove": ["cover"]}},
        "checks": {"default_state": "cover-off"},
    }
    report = run(buried(), BURIED_RULES, BURIED_STEPS, **sidecar)
    assert set(service(report).values()) == {Verdict.TURNS}
    assert report.summary["blocked"] == 0
    assert built(report)["late"] == (Verdict.BLOCKED, "late", "late")
    assert report.exit_code == 1
    with pytest.raises(AssertionError, match="FAIL late: late  hex-key-5  blocked"):
        report.assert_all_pass()


def test_a_build_that_passes_passes():
    steps = [{"step": "base", "add": ["plate", "early", "late"]}, {"step": "cover", "add": ["*"]}]
    report = run(
        buried(),
        BURIED_RULES,
        steps,
        checks={"default_state": "cover-off"},
        states={"cover-off": {"remove": ["cover"]}},
    )
    assert built(report) == {
        "early": (Verdict.TURNS, "base", "base"),
        "late": (Verdict.TURNS, "base", "base"),
    }
    assert build_lines(report)[0] == "build: 2 steps, 2 fasteners"
    assert (report.build.exit_code, report.exit_code) == (0, 0)
    report.assert_all_pass()


def way_in():
    """Two M6x50 screws, each under a ceiling 45 over its seat: the short leg turns
    each (36.1 < 45), and neither comes out past its ceiling."""
    return [
        ("plate", plate(-150, 150)),
        ("under", socket_screw(-150, 50)),
        ("over", socket_screw(150, 50)),
        ("under_ceiling", slab(6 + 45, -150, 200)),
        ("over_ceiling", slab(6 + 45, 150, 200)),
    ]


def test_a_screw_whose_way_in_is_blocked_is_stuck_in_its_step(engine):
    rules = [{"parts": name, **M6_SOCKET} for name in ("under", "over")]
    steps = [
        {"step": "first", "add": ["plate", "under_ceiling", "under", "over"]},
        {"step": "second", "add": ["over_ceiling"]},
    ]
    report = run(way_in(), rules, steps, engine)
    assert service(report) == {"over": Verdict.STUCK, "under": Verdict.STUCK}
    assert built(report) == {
        "under": (Verdict.STUCK, "first", "first"),
        "over": (Verdict.TURNS, "first", "first"),
    }
    assert build_lines(report)[-1] == (
        "FAIL first: under  hex-key-5  stuck  its way in is blocked: under_ceiling (added in first)"
    )


def test_the_headline_names_the_first_step_a_fastener_fails_in():
    # Each screw after its own ceiling: by step, not by the steps' names or the screws'.
    rules = [{"parts": name, **M6_SOCKET} for name in ("under", "over")]
    steps = [
        {"step": "b_second", "add": ["plate", "under_ceiling", "under"]},
        {"step": "a_first", "add": ["over_ceiling", "over"]},
    ]
    report = run(way_in(), rules, steps)
    assert built(report) == {
        "under": (Verdict.STUCK, "b_second", "b_second"),
        "over": (Verdict.STUCK, "a_first", "a_first"),
    }
    assert [p.result.name for p in report.build.placed] == ["under", "over"]
    lines = build_lines(report)
    assert lines[0] == "build: 2 steps, 2 fasteners; the first failure is in b_second"
    assert [line.split(":")[0] for line in lines[3:]] == ["FAIL b_second", "FAIL a_first"]


# ---------------------------------------------------------------------------
# Joints: checked when their last member arrives.
# ---------------------------------------------------------------------------


def slotted(**kwargs):
    """The M8 bolt (it turns) down into its nut in a slotted pocket (it only holds)."""
    return [(part.name, part.shape) for part in bolt_with_slotted_nut(**kwargs)]


def test_a_bolt_before_its_nut_is_checked_when_the_nut_comes(engine):
    steps = [
        {"step": "first", "add": ["upper", "lower", "pocket", "bolt"]},
        {"step": "second", "add": ["nut"]},
    ]
    report = run(slotted(), JOINT, steps, engine)
    assert built(report) == {
        "bolt": (Verdict.TURNS, "first", "second"),
        "nut": (Verdict.HELD, "second", "second"),
    }
    assert build_lines(report)[0] == "build: 2 steps, 2 fasteners"
    assert report.build.told("bolt") == (
        "added in first, checked in second, turns with spanner-13, ring, full length"
    )
    assert (
        report.build.told("nut") == "added in second, held with spanner-13, open end, full length"
    )
    assert report.build.told("upper") is None
    # Each step counts the fasteners it adds, wherever their joint is checked.
    steps_json = report.to_json_dict()["build"]["steps"]
    assert [(s["step"], s["summary"]["fasteners"], s["summary"]["turns"]) for s in steps_json] == [
        ("first", 1, 1),
        ("second", 1, 0),
    ]
    assert build_lines(report)[1:] == [
        "  first   1 fastener: 1 turn",
        "  second  1 fastener: 1 held",
    ]


def test_a_nut_before_its_bolt_is_held_by_nothing(engine):
    steps = [
        {"step": "first", "add": ["upper", "lower", "pocket", "nut"]},
        {"step": "second", "add": ["bolt"]},
    ]
    report = run(slotted(), JOINT, steps, engine)
    assert built(report) == {
        "nut": (Verdict.NOT_COVERED, "first", "first"),
        "bolt": (Verdict.TURNS, "second", "second"),
    }
    nut = next(p.result for p in report.build.placed if p.result.name == "nut")
    assert nut.reason == "put in before its bolt bolt (added in second), held by nothing till then"
    assert (nut.pair, nut.tool) == ("bolt", None)
    assert build_lines(report)[-1] == (
        "FAIL first: nut  -  not-covered  put in before its bolt bolt (added in second), "
        "held by nothing till then"
    )
    # A sidecar problem: the steps are wrong, and the run fails as for any.
    assert (report.build.exit_code, report.exit_code) == (2, 2)


def test_a_nut_not_understood_before_its_bolt_says_why_it_isn_t():
    # A ball where its nut should be, paired by the sidecar: not understood, which is
    # its verdict in the build too, in its own step, before anything of its bolt.
    parts = [(n, s) if n != "nut" else ("nut", Pos(0, 0, -14) * Sphere(4)) for n, s in slotted()]
    steps = [
        {"step": "first", "add": ["upper", "lower", "pocket", "nut"]},
        {"step": "second", "add": ["bolt"]},
    ]
    report = run(parts, JOINT, steps, pairs=[["bolt", "nut"]])
    assert built(report) == {
        "nut": (Verdict.NOT_COVERED, "first", "first"),
        "bolt": (Verdict.TURNS, "second", "second"),
    }
    nut = next(p.result for p in report.build.placed if p.result.name == "nut")
    assert nut.reason == "axis is auto but the part has no cylindrical face"


def test_a_fixed_thread_before_its_screw_holds_itself():
    rules = [{"parts": "bolt", **M8_HEX}, {"parts": "nut", "kind": "insert", "size": "M8"}]
    steps = [
        {"step": "first", "add": ["upper", "lower", "pocket", "nut"]},
        {"step": "second", "add": ["bolt"]},
    ]
    report = run(slotted(), rules, steps)
    assert built(report) == {
        "nut": (Verdict.HELD, "first", "second"),
        "bolt": (Verdict.TURNS, "second", "second"),
    }


def test_a_fixed_thread_sunk_in_its_part_holds_itself_in_the_build():
    # A heat-set insert flush in its block, its screw on top: both its ends are
    # covered, which says nothing of a fixed thread, never turned (issue #29).
    block = Pos(0, 0, -10) * Box(40, 40, 20) - Pos(0, 0, -4) * Cylinder(2.4, 8.01)
    insert = Pos(0, 0, -4) * (Cylinder(2.35, 8) - Cylinder(1.5, 8.01))
    screw = Pos(0, 0, -6) * Cylinder(1.5, 12) + Pos(0, 0, 1.5) * Cylinder(2.75, 3)
    screw -= Pos(0, 0, 1.7) * hex_prism(2.5, 1.31)
    rules = [
        {"parts": "screw", "kind": "screw", "head": "socket", "size": "M3"},
        {"parts": "insert", "kind": "insert", "size": "M3"},
    ]
    steps = [{"step": "first", "add": ["block", "insert"]}, {"step": "second", "add": ["screw"]}]
    report = run([("block", block), ("insert", insert), ("screw", screw)], rules, steps)
    assert built(report) == {
        "insert": (Verdict.HELD, "first", "second"),
        "screw": (Verdict.TURNS, "second", "second"),
    }
    assert report.build.told("insert") == "added in first, checked in second, held, holds itself"


def trapped():
    """An M3 socket screw down a 16 deep block into an M3 nut in a hex pocket
    in its underside (issue #93's pocket): the block holds the nut."""
    block = Pos(0, 0, -8) * Box(30, 30, 16) - Pos(0, 0, -8) * Cylinder(1.7, 17)
    block -= Pos(0, 0, -16) * hex_prism(5.6, 2.6)
    screw = Pos(0, 0, -8) * Cylinder(1.5, 16) + Pos(0, 0, 1.5) * Cylinder(2.75, 3)
    screw -= Pos(0, 0, 1.7) * hex_prism(2.5, 1.31)
    return [
        ("block", block),
        ("screw", screw),
        ("nut", Pos(0, 0, -16) * hex_nut_shape(3, 5.5, 2.4)),
    ]


def test_a_nut_its_trap_holds_may_come_before_its_screw(engine):
    rules = [
        {"parts": "screw", "kind": "screw", "head": "socket", "size": "M3"},
        {"parts": "nut", "kind": "nut", "size": "M3"},
    ]
    steps = [{"step": "first", "add": ["block", "nut"]}, {"step": "second", "add": ["screw"]}]
    report = run(trapped(), rules, steps, engine)
    assert built(report) == {
        "nut": (Verdict.HELD, "first", "second"),
        "screw": (Verdict.TURNS, "second", "second"),
    }
    nut = next(p.result for p in report.build.placed if p.result.name == "nut")
    assert nut.how == "held by its trap in block"


def held_head():
    """The slotted joint the other way up: the bolt's head in the slotted pocket, a
    spanner on it holding (22 deg) and never turning, a floor 12 under it with a hole
    17 across for the head's way out; its nut on top, open, turning."""
    head_face = -10 - 5.3
    floor = Pos(0, 0, head_face - 12 - 5) * (Box(120, 120, 10) - Cylinder(8.5, 11))
    return [
        ("upper", Pos(0, 0, -2.5) * Box(200, 200, 5) - Cylinder(4.5, 12)),
        ("lower", Pos(0, 0, -7.5) * Box(200, 200, 5) - Cylinder(4.5, 12)),
        ("bolt", Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(8.0, 25.0, 13.0, 5.3)),
        ("nut", hex_nut_shape(8.0, 13.0, 6.8)),
        ("pocket", slotted_pocket(11, head_face - 12, -10) + floor),
    ]


def test_a_bolt_held_in_its_step_waits_for_its_nut_to_turn(engine):
    # Checked alone in its own step, the bolt would only hold, with no nut to turn.
    steps = [
        {"step": "first", "add": ["upper", "lower", "pocket", "bolt"]},
        {"step": "second", "add": ["nut"]},
    ]
    report = run(held_head(), JOINT, steps, engine)
    assert built(report) == {
        "bolt": (Verdict.HELD, "first", "second"),
        "nut": (Verdict.TURNS, "second", "second"),
    }
    assert service(report) == {"bolt": Verdict.HELD, "nut": Verdict.TURNS}


def boxed_bolt():
    """An M8 bolt, head up, its nut open below; a ceiling 30 over the head, inside the
    bolt's 40: a ring turns the head under it, and the bolt can't come out past it."""
    return [
        ("plate", plate(0, radius=4.5)),
        ("bolt", hex_bolt(8.0, 40.0, 13.0, 5.3)),
        ("nut", Pos(0, 0, -10 - 6.8) * hex_nut_shape(8.0, 13.0, 6.8)),
        ("ceiling", slab(5.3 + 30)),
    ]


def test_a_bolt_whose_way_in_is_blocked_fails_in_its_step_not_its_nut_s():
    steps = [
        {"step": "first", "add": ["plate", "ceiling", "bolt"]},
        {"step": "second", "add": ["nut"]},
    ]
    report = run(boxed_bolt(), JOINT, steps)
    assert service(report)["bolt"] is Verdict.STUCK
    assert built(report) == {
        "bolt": (Verdict.STUCK, "first", "first"),
        "nut": (Verdict.TURNS, "second", "second"),
    }
    assert build_lines(report)[-1] == (
        "FAIL first: bolt  spanner-13  stuck  its way in is blocked: ceiling (added in first)"
    )


def test_a_bolt_in_already_is_not_stuck_behind_a_part_its_nut_s_step_adds():
    # The ceiling comes with the nut: the bolt went in before it, so its way out is
    # service's to say.
    steps = [
        {"step": "first", "add": ["plate", "bolt"]},
        {"step": "second", "add": ["nut", "ceiling"]},
    ]
    report = run(boxed_bolt(), JOINT, steps)
    assert built(report) == {
        "bolt": (Verdict.TURNS, "first", "second"),
        "nut": (Verdict.TURNS, "second", "second"),
    }


def test_a_bolt_held_with_its_way_in_blocked_is_stuck_in_its_own_step():
    # The head boxed in under a lid 12 over it, inside the bolt's 25: a spanner holds
    # it, and it can't have gone in past the lid. Its nut, only held too, fails then.
    steps = [
        {"step": "first", "add": ["upper", "lower", "pocket", "pocket_high", "bolt"]},
        {"step": "second", "add": ["nut"]},
    ]
    report = run(slotted(head_boxed=True), JOINT, steps)
    assert built(report) == {
        "bolt": (Verdict.STUCK, "first", "first"),
        "nut": (Verdict.BLOCKED, "second", "second"),
    }
    bolt = next(p.result for p in report.build.placed if p.result.name == "bolt")
    assert (bolt.tool, bolt.stuck_on) == ("spanner-13", ("pocket_high",))


def test_a_bolt_failing_once_whole_says_the_step_it_was_added_in():
    # held_head's bolt goes in held; its nut comes boxed in a slotted pocket of its
    # own, held too: neither turns, in the nut's step, where the joint is checked.
    nut_box = slotted_pocket(11, 0, 6.8 + 12) + Pos(0, 0, 6.8 + 12 + 5) * Box(120, 120, 10)
    steps = [
        {"step": "first", "add": ["upper", "lower", "pocket", "bolt"]},
        {"step": "second", "add": ["nut", "nut_box"]},
    ]
    report = run([*held_head(), ("nut_box", nut_box)], JOINT, steps)
    assert built(report) == {
        "bolt": (Verdict.BLOCKED, "first", "second"),
        "nut": (Verdict.BLOCKED, "second", "second"),
    }
    lines = build_lines(report)
    assert any(
        line.startswith("FAIL second: bolt (added in first)  spanner-13  blocked") for line in lines
    )


# ---------------------------------------------------------------------------
# A step's own model.
# ---------------------------------------------------------------------------


def lever(tmp_path, lever_z):
    """A screw on a plate and a lever over it, written to ``lever_<z>.step``."""
    shapes = {
        "plate": plate(0),
        "screw": socket_screw(),
        "lever": Pos(0, 0, lever_z + 5) * Box(60, 30, 10),
    }
    for name, shape in shapes.items():
        shape.label = name
    path = tmp_path / f"lever_{lever_z:g}.step"
    export_step(Compound(children=list(shapes.values())), str(path))
    return path


def test_a_step_with_its_own_model_is_checked_in_it(tmp_path):
    # Over the screw in the model as given; swung clear of it while it goes in.
    model = lever(tmp_path, 6 + 15)
    lever(tmp_path, 300)
    rules = [{"parts": "screw", **M6_SOCKET}]
    steps = [
        {"step": "base", "add": ["plate", "lever"]},
        {"step": "screw", "add": ["screw"], "model": "lever_300.step"},
    ]
    config = Config.from_dict({"fasteners": rules, "build": steps})
    report = check(Assembly.from_step(model), config, kit="full", model_dir=tmp_path)
    assert service(report) == {"screw": Verdict.BLOCKED}
    assert built(report) == {"screw": (Verdict.TURNS, "screw", "screw")}
    assert build_lines(report)[1:] == [
        "  base   no fasteners",
        "  screw  1 fastener: 1 turn, in lever_300.step",
    ]
    assert report.to_json_dict()["build"]["steps"][1]["model"] == "lever_300.step"


def test_a_step_s_model_found_nowhere_is_a_config_error(tmp_path):
    model = lever(tmp_path, 6 + 15)
    steps = [{"step": "base", "add": ["*"], "model": "gone.step"}]
    config = Config.from_dict(
        {"fasteners": [{"parts": "screw", **M6_SOCKET}], "build": steps}, source="w.yaml"
    )
    with pytest.raises(
        ConfigError,
        match=r"build step 'base': its model gone.step not found "
        r"\(w.yaml, build\[0\].model; looked in ",
    ):
        check(Assembly.from_step(model), config, model_dir=tmp_path)


def test_a_step_s_model_lacking_parts_says_so_and_its_fastener_is_not_covered(tmp_path):
    model = lever(tmp_path, 300)
    shapes = {"plate": plate(0), "jig": Pos(200, 0, 0) * Box(10, 10, 10)}
    for name, shape in shapes.items():
        shape.label = name
    export_step(Compound(children=list(shapes.values())), str(tmp_path / "half.step"))
    steps = [
        {"step": "base", "add": ["plate", "lever"]},
        {"step": "screw", "add": ["screw"], "model": "half.step"},
    ]
    config = Config.from_dict({"fasteners": [{"parts": "screw", **M6_SOCKET}], "build": steps})
    report = check(Assembly.from_step(model), config, kit="full", model_dir=tmp_path)
    (placed,) = report.build.placed
    assert placed.result.verdict is Verdict.NOT_COVERED
    assert placed.result.reason == (
        "not in step 'screw', whose model half.step has no part of its name (renamed?)"
    )
    assert (
        "build step 'screw': its model half.step lacks 2 parts added by then: screw, lever; "
        "has 1 part the main model doesn't: jig"
    ) in report.notes


# ---------------------------------------------------------------------------
# The steps wrong: the build isn't checked.
# ---------------------------------------------------------------------------


def test_a_part_in_no_step_leaves_the_build_unchecked():
    steps = [{"step": "base", "add": ["plate", "early", "late"]}]
    report = run(buried(), BURIED_RULES, steps)
    assert report.build.placed == ()
    assert build_lines(report) == [
        "build: 1 step, not checked: every part must be added by one step exactly",
        "WARN build: no step adds 1 part: cover",
    ]
    assert (report.build.exit_code, report.exit_code) == (2, 2)
    assert "the build order (its steps must add every part once)" in report.not_checked


def test_parts_two_steps_add_are_said_together():
    steps = [
        {"step": "first", "add": ["plate", "early", "late", "cover"]},
        {"step": "again", "add": ["early", "late"]},
        {"step": "more", "add": ["cover", "gone"]},
    ]
    report = run(buried(), BURIED_RULES, steps)
    assert build_lines(report) == [
        "build: 3 steps, not checked: every part must be added by one step exactly",
        "WARN build: steps first and again each add 2 parts: early, late",
        "WARN build: steps first and more each add 1 part: cover",
        "WARN build: step 'more': add glob 'gone' matched nothing (renamed part?)",
    ]


def test_a_glob_naming_nothing_fails_a_build_that_is_checked():
    steps = [*BURIED_STEPS[:2], {"step": "late", "add": ["late", "gone_*"]}]
    report = run(buried(), BURIED_RULES, steps)
    assert len(report.build.placed) == 2
    assert build_lines(report)[-1] == (
        "WARN build: step 'late': add glob 'gone_*' matched nothing (renamed part?)"
    )
    assert (report.build.exit_code, report.exit_code) == (2, 2)


# ---------------------------------------------------------------------------
# What the report says of the build.
# ---------------------------------------------------------------------------


def test_only_narrows_the_build_as_it_narrows_the_check():
    steps = [
        {"step": "first", "add": ["upper", "lower", "pocket", "nut"]},
        {"step": "second", "add": ["bolt"]},
    ]
    config = Config.from_dict({"fasteners": JOINT, "build": steps})
    report = check(bolt_with_slotted_nut(), config, kit="full", only="bolt")
    # The nut is checked with its bolt, as its partner, and not reported.
    assert built(report) == {"bolt": (Verdict.TURNS, "second", "second")}
    assert report.build.exit_code == 0


def test_the_json_has_the_build_step_by_step():
    document = run(buried(), BURIED_RULES, BURIED_STEPS).to_json_dict()
    build = document["build"]
    assert build["checked"] is True
    assert build["steps"] == [
        {
            "step": "base",
            "model": None,
            "adds": ["plate", "early"],
            "summary": {
                "fasteners": 1,
                "turns": 1,
                "held": 0,
                "blocked": 0,
                "stuck": 0,
                "not_covered": 0,
            },
        },
        {
            "step": "cover",
            "model": None,
            "adds": ["cover"],
            "summary": {
                "fasteners": 0,
                "turns": 0,
                "held": 0,
                "blocked": 0,
                "stuck": 0,
                "not_covered": 0,
            },
        },
        {
            "step": "late",
            "model": None,
            "adds": ["late"],
            "summary": {
                "fasteners": 1,
                "turns": 0,
                "held": 0,
                "blocked": 1,
                "stuck": 0,
                "not_covered": 0,
            },
        },
    ]
    late = build["fasteners"][1]
    assert (late["name"], late["verdict"], late["blocked_by"]) == ("late", "blocked", ["cover"])
    assert (late["step"], late["checked_in"], late["state"]) == ("late", "late", None)
    assert (build["unplaced"], build["twice"], build["unmatched"]) == ([], [], [])
    json.dumps(document)  # it is JSON


def test_the_json_says_what_is_wrong_with_the_steps():
    steps = [
        {"step": "a", "add": ["plate", "early", "late", "gone"]},
        {"step": "b", "add": ["late"]},
    ]
    build = run(buried(), BURIED_RULES, steps).to_json_dict()["build"]
    assert build["checked"] is False
    assert build["fasteners"] == []
    assert build["unplaced"] == ["cover"]
    assert build["twice"] == [{"part": "late", "steps": ["a", "b"]}]
    assert build["unmatched"] == [{"step": "a", "glob": "gone"}]


def test_a_report_with_no_build_says_none():
    config = Config.from_dict({"fasteners": BURIED_RULES})
    report = check(Assembly([Part(n, s) for n, s in buried()]), config, kit="full")
    assert report.build is None
    assert report.to_json_dict()["build"] is None
    assert "the build order (a build: list in the sidecar turns it on)" in report.not_checked
    assert not any(line.startswith("build: ") for line in report.terminal_lines())
    markdown = report.markdown()
    assert "#### Build" not in markdown
    assert "the build order (a `build:` list in the sidecar turns it on)" in markdown


def test_a_checked_build_says_what_it_did_not_see():
    report = run(buried(), BURIED_RULES, BURIED_STEPS)
    assert "whether each part fits in at its build step" in report.not_checked
    assert "the build order" not in report.not_checked
    assert "whether each part fits in at its build step" in report.markdown()


def test_the_markdown_has_a_row_per_step_and_the_build_s_failures():
    markdown = run(buried(), BURIED_RULES, BURIED_STEPS).markdown()
    section = markdown[markdown.index("#### Build") :]
    assert section.splitlines()[:13] == [
        "#### Build",
        "",
        "**build: 3 steps, 2 fasteners; the first failure is in late.**",
        "",
        "| Step | Adds | Fasteners |",
        "| --- | ---: | --- |",
        "| `base` | 2 parts | 1 fastener: 1 turn |",
        "| `cover` | 1 part | no fasteners |",
        "| `late` | 1 part | 1 fastener: 1 blocked |",
        "",
        "| Step | Fastener | Tool | Verdict | In the way, or why |",
        "| --- | --- | --- | --- | --- |",
        "| `late` | `late` | `hex-key-5` | blocked | `cover` (added in `cover`) |",
    ]


def test_names_and_steps_from_outside_can_t_steer_the_terminal_or_the_markdown():
    esc, rlo = "\x1b[2J", chr(0x202E)
    parts = [
        (f"pl{esc}ate", plate(-100, 100)),
        (f"la|te{rlo}", socket_screw(100)),
        ("co`ver", slab(6 + 15)),
    ]
    rules = [{"parts": "la*", **M6_SOCKET}]
    steps = [{"step": f"ba{esc}se", "add": ["pl*", "co*"]}, {"step": "la`te|", "add": ["la*"]}]
    report = run(parts, rules, steps)
    lines = build_lines(report)
    assert lines[-1] == (
        "FAIL la`te|: la|te\\u202e  hex-key-5  blocked  co`ver (added in ba\\x1b[2Jse)"
    )
    assert "\x1b" not in "".join(report.terminal_lines())
    markdown = report.markdown()
    assert (
        "| ``la`te\\|`` | `la\\|te\\u202e` | `hex-key-5` | blocked "
        "| ``co`ver`` (added in `ba\\x1b[2Jse`) |"
    ) in markdown


def test_explain_says_how_the_fastener_fares_in_the_build(tmp_path):
    shapes = []
    for name, shape in buried():
        shape.label = name
        shapes.append(shape)
    export_step(Compound(children=shapes), str(tmp_path / "m.step"))
    sidecar = {"fasteners": BURIED_RULES, "build": BURIED_STEPS}
    (tmp_path / "wrenchroom.yaml").write_text(json.dumps(sidecar))
    runner = CliRunner()
    late = runner.invoke(main, ["explain", str(tmp_path / "m.step"), "late", "--kit", "full"])
    assert "  in the build: added in late, blocked with hex-key-5: cover (added in cover)" in (
        late.output.splitlines()
    )
    early = runner.invoke(main, ["explain", str(tmp_path / "m.step"), "early", "--kit", "full"])
    assert "  in the build: added in base, turns with hex-key-5, driver straight in" in (
        early.output.splitlines()
    )
