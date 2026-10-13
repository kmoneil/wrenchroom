"""The bench as a build script hands it over: shapes, and no STEP file (issue #196).

The bench's parts go to ``from_shapes`` as they are built, and so do its lever-up
model's, which ``models=`` gives under the name the bench's sidecar has for it. No
file is written or read, and the sidecar, from a mapping, has no folder to look in.
The report is then the one the bench read from STEP gets, fastener for fastener, on
both engines, and so is the clash list: a state's model given is the state's model.

One figure differs, and not by the state: one_part_lock's nut, drawn as two solids,
is one whole part from shapes and its larger solid from STEP (issue #28), so its
seat is measured on the whole.
"""

import pytest
from bench import FINAL_COUNTS, KIT, build, canonical, sidecar_and_truth

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check, find_clashes
from wrenchroom.config import Config, ConfigError

LEVER_UP = "bench_lever-up.step"


@pytest.fixture(scope="module")
def shapes():
    """The bench and its lever-up model, each from its shapes as built."""
    main = Assembly.from_shapes((shape.label, shape) for shape in build())
    raised = Assembly.from_shapes((shape.label, shape) for shape in build(raised=True))
    return main, raised


@pytest.fixture(scope="module")
def config():
    sidecar, _ = sidecar_and_truth()
    return Config.from_dict(sidecar)


@pytest.fixture(scope="module")
def given(shapes, config, bench_engine):
    main, raised = shapes
    return check(
        main, config, kit=KIT, model="bench.step", models={LEVER_UP: raised}, engine=bench_engine
    )


def _by_name(report):
    return {entry["name"]: entry for entry in canonical(report.to_json_dict())["fasteners"]}


def test_the_bench_given_as_shapes_is_the_bench_read_from_step(given, bench_report):
    assert given.summary == bench_report.summary == FINAL_COUNTS
    assert (given.warnings, given.notes) == (bench_report.warnings, bench_report.notes)
    ours, theirs = _by_name(given), _by_name(bench_report)
    assert list(ours) == list(theirs)
    differing = {
        name: sorted(key for key in entry if entry[key] != theirs[name][key])
        for name, entry in ours.items()
        if entry != theirs[name]
    }
    assert differing == {"one_part_lock_nut": ["seat"]}
    # The whole part's end, its lock ring's, against the nut's own.
    assert (ours["one_part_lock_nut"]["seat"][2], theirs["one_part_lock_nut"]["seat"][2]) == (
        7.7,
        5.2,
    )


def test_its_lever_up_fastener_passes_in_the_model_given(given, shapes):
    # The guard: the state is reached, and in the assembly handed over.
    assert [r.name for r in given.results if r.state == "lever-up"] == ["state_lever_screw"]
    assert given.models["lever-up"].assembly is shapes[1]


def test_from_shapes_beside_its_lever_up_model_from_step_it_is_the_same_bench(
    shapes, config, given, bench_dir, bench_engine
):
    # Issue #199: the two readers in one run. The bench's parts of two solids
    # (one_part_lock's nut, halves's lid, lead and rod) are whole in the main model and
    # in pieces in the lever-up model, and no part of either is one the other lacks.
    report = check(
        shapes[0], config, kit=KIT, model="bench.step", model_dir=bench_dir, engine=bench_engine
    )
    assert (report.warnings, report.notes) == (given.warnings, given.notes)
    assert _by_name(report) == _by_name(given)


def test_from_step_beside_its_lever_up_model_from_shapes_it_is_the_same_bench(
    shapes, bench_report, bench_dir, bench_engine
):
    # And the other way about: in pieces in the main model, whole in the lever-up one.
    report = check(
        Assembly.from_step(bench_dir / "bench.step"),
        Config.load(bench_dir / "wrenchroom.yaml"),
        kit=KIT,
        model="bench.step",
        models={LEVER_UP: shapes[1]},
        engine=bench_engine,
    )
    assert (report.warnings, report.notes) == (bench_report.warnings, bench_report.notes)
    assert canonical(report.to_json_dict()) == canonical(bench_report.to_json_dict())


def test_with_the_model_not_given_there_is_nowhere_to_read_it_from(shapes, config):
    with pytest.raises(ConfigError, match=f"its model '{LEVER_UP}' needs a model directory"):
        check(shapes[0], config, kit=KIT)


def test_the_clash_list_given_as_shapes_is_the_one_read_from_step(
    shapes, config, bench_dir, bench_engine
):
    main, raised = shapes
    found = find_clashes(main, config, models={LEVER_UP: raised}, engine=bench_engine)
    by_step = find_clashes(
        Assembly.from_step(bench_dir / "bench.step"),
        Config.load(bench_dir / "wrenchroom.yaml"),
        model_dir=bench_dir,
        engine=bench_engine,
    )
    assert found.to_json() == by_step.to_json()
    assert found.lines() == by_step.lines()
    # state_clash's slider, into its wall in the lever-up model alone.
    assert [(c.first, c.second, round(c.volume, 1)) for c in found.found if c.state] == [
        ("state_clash_slider", "state_clash_wall", 200.0)
    ]
