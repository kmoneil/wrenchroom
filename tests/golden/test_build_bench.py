"""The bench's build (M8): each build cell's fastener in the step that adds it, both engines.

bench_build.yaml is the bench's own sidecar with a build: the build cells' steps,
first, second and third, then rest, which adds every other part. Checked with
``only="build_*"``, the build cells' fasteners alone are tried, each in its step;
what the bench's other cells make of a build is the unit tests', not the bench's.
"""

import pytest
from bench import KIT, REST, build_sidecar
from cells import BUILD_STEPS, CELLS

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.config import Config

STEPS = [*BUILD_STEPS, REST]
ONLY = "build_*"


def _truth_params():
    _, truth = build_sidecar()  # static: no geometry built at collection
    return [pytest.param(name, expected, id=name) for name, expected in sorted(truth.items())]


@pytest.fixture(scope="module")
def bench_model(bench_dir):
    return Assembly.from_step(bench_dir / "bench.step")


def _check(bench_dir, bench_model, engine, sidecar=None, only=ONLY):
    config = (
        Config.load(bench_dir / "bench_build.yaml")
        if sidecar is None
        else Config.from_dict(sidecar, source="build")
    )
    return check(bench_model, config, kit=KIT, model_dir=bench_dir, engine=engine, only=only)


@pytest.fixture(scope="module")
def built(bench_dir, bench_model, bench_engine):
    return _check(bench_dir, bench_model, bench_engine)


@pytest.fixture(scope="module")
def built_json(built):
    return {entry["name"]: entry for entry in built.to_json_dict()["build"]["fasteners"]}


@pytest.mark.parametrize(("name", "expected"), _truth_params())
def test_build_truth(name, expected, built_json):
    entry = built_json.get(name)
    assert entry is not None, f"{name} missing from the build"
    for key, want in expected.items():
        got = entry[key]
        if isinstance(want, list):
            assert sorted(got) == sorted(want), f"{name}.{key}"
        else:
            assert got == want, f"{name}.{key}"


def test_every_build_cell_fastener_has_its_truth(built_json):
    # Not one checked without a truth, nor one with a truth left unchecked: in the
    # order the steps add them, by name in each.
    _, truth = build_sidecar()
    assert list(built_json) == [
        *sorted(name for name, entry in truth.items() if entry["step"] == "first"),
        *sorted(name for name, entry in truth.items() if entry["step"] == "second"),
        *sorted(name for name, entry in truth.items() if entry["step"] == "third"),
    ]
    assert len(truth) == 10


def test_the_build_is_said_step_by_step(built):
    # The loose nut, put in before its bolt, fails the run as a sidecar problem does.
    lines = built.terminal_lines()
    start = lines.index("build: 4 steps, 10 fasteners; the first failure is in first")
    assert lines[start : start + 8] == [
        "build: 4 steps, 10 fasteners; the first failure is in first",
        "  first   6 fasteners: 2 turn, 2 held, 1 stuck, 1 not covered",
        "  second  3 fasteners: 3 turn",
        "  third   1 fastener: 1 blocked",
        "  rest    no fasteners",  # its own, every other cell's: not chosen
        "FAIL first: build_way_in_under_screw  hex-key-5  stuck  its way in is blocked: "
        "build_way_in_under (added in first)",
        "FAIL first: build_ahead_loose_nut  -  not-covered  put in before its bolt "
        "build_ahead_loose_bolt (added in second), held by nothing till then",
        "FAIL third: build_buried_late_screw  hex-key-5  blocked  build_buried_cover "
        "(added in second)",
    ]
    assert built.build.exit_code == 2
    assert built.exit_code == 2


def test_the_json_counts_each_step_s_fasteners_by_the_step_that_adds_them(built):
    # The trapped nut and build_behind's bolt, checked in second, count in first.
    steps = {entry["step"]: entry["summary"] for entry in built.to_json_dict()["build"]["steps"]}
    assert steps["first"] == {
        "fasteners": 6,
        "turns": 2,
        "held": 2,
        "blocked": 0,
        "stuck": 1,
        "not_covered": 1,
    }
    assert steps["second"] == {
        "fasteners": 3,
        "turns": 3,
        "held": 0,
        "blocked": 0,
        "stuck": 0,
        "not_covered": 0,
    }
    assert steps[REST]["fasteners"] == 0


def test_the_steps_add_what_the_cells_say(built):
    # Each build cell's roles in its steps, every other part of the bench in rest.
    adds = {step.name: step.parts for step in built.build.plan.steps}
    assert list(adds) == STEPS
    for cell in CELLS:
        for step, roles in cell.steps.items():
            assert {f"{cell.name}_{role}" for role in roles} <= set(adds[step]), cell.name
    assert "key_wall_near_screw" in adds[REST]
    # A part drawn as two solids comes in once, its other solid with it (issue #28).
    assert "one_part_lock_nut" in adds[REST]
    assert "one_part_lock_nut#2" not in adds[REST]
    plan = built.build.plan
    assert plan.added_in["one_part_lock_nut#2"] == plan.added_in["one_part_lock_nut"]
    # Ignored parts and the surface no step need add, and none does.
    assert "shelled_decal" not in plan.added_in
    assert (plan.unplaced, plan.twice, plan.unmatched) == ((), (), ())


def test_service_is_the_bench_s_own_whatever_the_build(built, bench_json):
    # The build changes nothing of the check itself: each verdict is the bench's.
    for result in built.results:
        entry = bench_json[result.name]
        assert (result.verdict.value, result.tool) == (entry["verdict"], entry["tool"])


def test_a_bench_with_no_step_adding_the_rest_is_not_built(bench_dir, bench_model, bench_engine):
    # Without rest, every other part of the bench is in no step: said, not checked.
    sidecar, _ = build_sidecar()
    sidecar["build"] = sidecar["build"][:-1]
    report = _check(bench_dir, bench_model, bench_engine, sidecar)
    assert report.build.placed == ()
    assert "key_wall_near_plate" in report.build.plan.unplaced
    lines = report.terminal_lines()
    assert "build: 3 steps, not checked: every part must be added by one step exactly" in lines
    (warn,) = [line for line in lines if line.startswith("WARN build: no step adds")]
    count = len(report.build.plan.unplaced)
    assert warn.startswith(f"WARN build: no step adds {count} parts: ")
    assert warn.endswith(f" and {count - 3} more")
    assert report.exit_code == 2


def test_a_bench_part_two_steps_add_is_not_built(bench_dir, bench_model, bench_engine):
    sidecar, _ = build_sidecar()
    sidecar["build"][0]["add"].append("build_buried_cover")  # second adds it too
    report = _check(bench_dir, bench_model, bench_engine, sidecar)
    assert report.build.plan.twice == (("build_buried_cover", ("first", "second")),)
    assert "WARN build: steps first and second each add 1 part: build_buried_cover" in (
        report.terminal_lines()
    )
    assert (report.build.placed, report.exit_code) == ((), 2)


def test_a_bench_step_glob_naming_nothing_fails_the_built_run(bench_dir, bench_model, bench_engine):
    # Renamed, a part's glob names nothing: said, and the run fails, the build checked.
    sidecar, _ = build_sidecar()
    sidecar["build"][1]["add"].append("build_gone_*")
    report = _check(bench_dir, bench_model, bench_engine, sidecar, only="build_buried_*")
    assert report.build.plan.unmatched == (("second", "build_gone_*"),)
    assert "WARN build: step 'second': add glob 'build_gone_*' matched nothing (renamed part?)" in (
        report.terminal_lines()
    )
    assert len(report.build.placed) == 2
    assert report.exit_code == 2
