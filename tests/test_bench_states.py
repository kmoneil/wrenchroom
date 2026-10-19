"""A state on a bench (issue #249): service done to a part off the machine.

A build step's ``bench:`` says it is done off the machine (issue #235). Service has
the same thing: fasteners only ever seen to with a part off and on the bench. A
state's ``bench:`` names a bench the build has, and its scene is the parts the
build's steps on that bench add, and no others: the machine isn't there. A fastener
or plug the bench hasn't isn't tried there, as one a state takes off isn't (#250).
"""

import json

import pytest
from build123d import Box, Compound, Cylinder, Pos, export_step
from click.testing import CliRunner

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check, find_clashes
from wrenchroom.cli import main
from wrenchroom.config import Config, ConfigError
from wrenchroom.connectors import ConnectorVerdict
from wrenchroom.report import Verdict

M6_SOCKET = {"kind": "screw", "head": "socket", "size": "M6"}
SCREWS = [{"parts": "*screw", **M6_SOCKET}]
STEPS = [
    {"step": "frame", "add": ["frame"]},
    {"step": "drive", "bench": "drives", "add": ["plate", "screw"]},
    {"step": "late", "add": ["frame_screw"]},
]
ON_THE_BENCH = {"drive-bench": {"bench": "drives"}}


def socket_screw(x=0.0):
    """An M6 socket head screw at x, its seat at z = 6, its key's socket 5 across."""
    shank = Pos(x, 0, -10) * Cylinder(3, 20)
    return shank + Pos(x, 0, 3) * Cylinder(5, 6) - Pos(x, 0, 0) * hex_prism(5, 3.01, 3)


def plate(*xs):
    """A plate 10 thick under z = 0, an M6 clearance hole at each x."""
    body = Pos(0, 0, -5) * Box(600, 200, 10)
    for x in xs:
        body -= Pos(x, 0, -5) * Cylinder(3.2, 11)
    return body


def slab(z, x=0.0, width=600.0):
    """A slab 10 thick whose underside is at z, centred on x: 15 over a seat at 21."""
    return Pos(x, 0, z + 5) * Box(width, 200, 10)


def machine():
    """A drive's plate and screw, built on the bench, and a frame the machine has over it.

    The frame is 15 over both screws' seats: in the machine no key gets on either. The
    screw on the plate is the drive's, put in on bench drives; frame_screw, the
    machine's, goes in last, in the machine, through the same plate.
    """
    return [
        ("frame", slab(6 + 15)),
        ("plate", plate(0, 200)),
        ("screw", socket_screw(0)),
        ("frame_screw", socket_screw(200)),
    ]


def model(parts):
    return Assembly([Part(name, shape) for name, shape in parts])


def run(parts=None, states=None, steps=None, engine="mesh", rules=None, checks=None, **kwargs):
    """Check the parts with the bench state retried, unless ``checks`` says otherwise."""
    states = ON_THE_BENCH if states is None else states
    sidecar = {
        "fasteners": SCREWS if rules is None else rules,
        "build": STEPS if steps is None else steps,
        "states": states,
        "checks": {"try_states": list(states)} if checks is None else checks,
    }
    parts = machine() if parts is None else parts
    return check(model(parts), Config.from_dict(sidecar), kit="full", engine=engine, **kwargs)


def told(report):
    """Each fastener's verdict and the state it was reached in."""
    return {r.name: (r.verdict, r.state) for r in report.results}


# ---------------------------------------------------------------------------
# The sidecar.
# ---------------------------------------------------------------------------


def test_a_state_s_bench_is_its_own_else_its_base_s():
    config = Config.from_dict(
        {
            "build": [
                {"step": "a", "bench": "drives", "add": ["*"]},
                {"step": "b", "bench": "boards", "add": ["x"]},
            ],
            "states": {
                "drive-bench": {"bench": "drives"},
                "motor-off": {"base": "drive-bench", "remove": ["motor"]},
                "board-bench": {"base": "drive-bench", "bench": "boards"},
                "plain": {"remove": ["lid"]},
            },
        }
    )
    assert [config.state_bench(s.name) for s in config.states] == [
        "drives",
        "drives",
        "boards",
        None,
    ]
    assert config.state("drive-bench").bench == "drives"
    assert config.state("motor-off").bench is None  # its own: none; its base's is read


@pytest.mark.parametrize(
    ("states", "build", "message"),
    [
        (
            {"s": {"bench": "drive"}},
            STEPS,
            r"states\[s\]: bench 'drive' is no build step's bench; the nearest: drives",
        ),
        (
            {"s": {"bench": "zzz"}},
            [*STEPS, {"step": "box", "bench": "boards", "add": ["box"]}],
            r"states\[s\]: bench 'zzz' is no build step's bench; "
            r"the build's benches: drives, boards$",
        ),
        (
            {"s": {"bench": "drives"}},
            [{"step": "all", "add": ["*"]}],
            r"states\[s\]: bench 'drives' is no build step's bench; no build step is on a bench",
        ),
        (
            {"s": {"bench": "drives"}},
            None,
            r"states\[s\]: bench 'drives' needs a build: whose steps on that bench say "
            r"which parts are on it",
        ),
        ({"s": {"bench": " "}}, STEPS, r"states\[s\]: bench needs a name"),
        ({"s": {"bench": None}}, STEPS, r"states\[s\]: bench must be a string"),
        ({"s": {"bench": ["drives"]}}, STEPS, r"states\[s\]: bench must be a string"),
        # One up a chain is checked as its own is.
        (
            {"s": {"bench": "drivs"}, "t": {"base": "s"}},
            STEPS,
            r"states\[s\]: bench 'drivs' is no build step's bench; the nearest: drives",
        ),
    ],
)
def test_a_bench_the_build_hasn_t_is_a_config_error(states, build, message):
    sidecar = {"states": states, **({"build": build} if build is not None else {})}
    with pytest.raises(ConfigError, match=message):
        Config.from_dict(sidecar, source="w.yaml")


# ---------------------------------------------------------------------------
# The bench's scene.
# ---------------------------------------------------------------------------


def test_a_screw_blocked_in_the_machine_turns_on_its_bench(engine):
    report = run(engine=engine)
    assert told(report)["screw"] == (Verdict.TURNS, "drive-bench")
    assert {r.name: r.how for r in report.results}["screw"] == "driver straight in"
    assert report.models["drive-bench"].removed == frozenset({"frame", "frame_screw"})
    assert report.warnings == ()
    assert report.notes == ()


def test_a_fastener_the_bench_hasn_t_is_not_tried_there(engine):
    # frame_screw is the machine's: with the frame off it would turn there, in the air.
    report = run(engine=engine)
    assert told(report)["frame_screw"] == (Verdict.BLOCKED, None)
    by_name = {r.name: r for r in report.results}
    assert by_name["frame_screw"].blockers == ("frame",)
    assert report.warnings == ()  # passed over by design, not a part a model lacks
    assert report.exit_code == 1


def test_a_fastener_whose_own_state_is_a_bench_it_isn_t_on_is_not_covered(engine):
    rules = [
        {"parts": "screw", **M6_SOCKET, "state": "drive-bench"},
        {"parts": "frame_screw", **M6_SOCKET, "state": "drive-bench"},
    ]
    report = run(engine=engine, rules=rules, checks={})
    by_name = {r.name: r for r in report.results}
    assert (by_name["screw"].verdict, by_name["screw"].state) == (Verdict.TURNS, "drive-bench")
    assert (by_name["frame_screw"].verdict, by_name["frame_screw"].reason) == (
        Verdict.NOT_COVERED,
        "its own state 'drive-bench' is on bench drives, and no step on that bench adds it",
    )
    assert report.exit_code == 2


def test_a_default_state_on_a_bench_leaves_the_machine_s_fasteners_not_covered():
    report = run(checks={"default_state": "drive-bench"})
    assert told(report) == {
        "screw": (Verdict.TURNS, "drive-bench"),
        "frame_screw": (Verdict.NOT_COVERED, "drive-bench"),
    }


def test_the_bench_has_its_earlier_steps_parts_and_no_other_bench_s_or_the_machine_s():
    # Bench a: a cover first, then screw_a under it. Bench b: screw_b, under its own
    # cover put on after it (cover_b, a later step on b: on the bench, as it ends up),
    # and under the machine's cover_m, added last.
    parts = [
        ("plate", plate(-200, 0, 200)),
        ("cover_a", slab(6 + 15, x=-200, width=100)),
        ("screw_a", socket_screw(-200)),
        ("screw_b", socket_screw(0)),
        ("cover_b", slab(6 + 15, x=0, width=100)),
        ("screw_m", socket_screw(200)),
        ("cover_m", slab(6 + 15, x=200, width=100)),
    ]
    steps = [
        {"step": "base", "add": ["plate"]},
        {"step": "a cover", "bench": "a", "add": ["cover_a"]},
        {"step": "a screw", "bench": "a", "add": ["screw_a"]},
        {"step": "b screw", "bench": "b", "add": ["screw_b"]},
        {"step": "b cover", "bench": "b", "add": ["cover_b"]},
        {"step": "machine", "add": ["screw_m", "cover_m"]},
    ]
    states = {"on-a": {"bench": "a"}, "on-b": {"bench": "b"}}
    report = run(parts, states, steps)
    assert report.models["on-a"].removed == {"plate", "screw_b", "cover_b", "screw_m", "cover_m"}
    assert report.models["on-b"].removed == {"plate", "cover_a", "screw_a", "screw_m", "cover_m"}
    assert told(report) == {
        "screw_a": (Verdict.BLOCKED, None),  # its own bench's cover is over it
        "screw_b": (Verdict.BLOCKED, None),
        "screw_m": (Verdict.BLOCKED, None),
    }
    # The covers off, each on its bench: screw_a and screw_b turn there; screw_m is
    # on neither bench and isn't tried on one.
    off = {name: {**state, "remove": ["cover_*"]} for name, state in states.items()}
    assert told(run(parts, off, steps)) == {
        "screw_a": (Verdict.TURNS, "on-a"),
        "screw_b": (Verdict.TURNS, "on-b"),
        "screw_m": (Verdict.BLOCKED, None),
    }


def test_remove_and_base_combine_with_a_bench():
    # A cover on the drive, over the screw, put on on the bench.
    parts = [*machine(), ("cover", slab(6 + 20, width=100))]
    steps = [{**STEPS[0]}, {**STEPS[1], "add": ["plate", "screw", "cover"]}, STEPS[2]]
    covered = run(parts, steps=steps)
    assert told(covered)["screw"] == (Verdict.BLOCKED, None)
    by_name = {r.name: r for r in covered.results}
    assert set(by_name["screw"].blockers) == {"frame", "cover"}  # in the machine
    states = {"drive-bench": {"bench": "drives", "remove": ["cover"]}}
    assert told(run(parts, states, steps))["screw"] == (Verdict.TURNS, "drive-bench")
    # The bench from its base, the cover off by its own remove:.
    chained = {
        "drive-bench": {"bench": "drives"},
        "uncovered": {"base": "drive-bench", "remove": ["cover"]},
    }
    report = run(parts, chained, steps)
    assert told(report)["screw"] == (Verdict.TURNS, "uncovered")
    assert report.models["uncovered"].removed == {"frame", "frame_screw", "cover"}
    # And the other way round: the base takes the cover off, the state is on the bench.
    turned = {
        "uncovered": {"remove": ["cover"]},
        "drive-bench": {"base": "uncovered", "bench": "drives"},
    }
    assert told(run(parts, turned, steps, checks={"try_states": ["drive-bench"]}))["screw"] == (
        Verdict.TURNS,
        "drive-bench",
    )


def test_a_part_no_step_adds_is_on_no_bench():
    # stray is in no step: the build says so, and it isn't on the bench either.
    parts = [*machine(), ("stray", slab(6 + 20, width=100))]
    report = run(parts)
    assert told(report)["screw"] == (Verdict.TURNS, "drive-bench")
    assert "stray" in report.models["drive-bench"].removed
    assert report.build.plan.unplaced == ("stray",)


def test_an_ignored_part_is_in_no_scene_on_the_bench_either():
    parts = [*machine(), ("lead", slab(6 + 20, width=100))]
    sidecar = {
        "fasteners": SCREWS,
        "ignore": ["lead"],
        "build": STEPS,
        "states": ON_THE_BENCH,
        "checks": {"try_states": ["drive-bench"]},
    }
    report = check(model(parts), Config.from_dict(sidecar), kit="full")
    assert told(report)["screw"] == (Verdict.TURNS, "drive-bench")


# ---------------------------------------------------------------------------
# The bench's model.
# ---------------------------------------------------------------------------


def lever(z):
    """A lever on the drive, its underside at z: 15 over the screw's seat at 21."""
    return ("lever", slab(z, width=60))


def with_lever(z):
    return [*machine(), lever(z)]


LEVER_STEPS = [
    STEPS[0],
    {"step": "drive", "bench": "drives", "add": ["plate", "screw", "lever"]},
    STEPS[2],
]


def test_a_state_on_a_bench_is_in_the_last_bench_step_s_model(engine):
    # In the model as given the lever is clear; the bench's last step has it over the
    # screw, the bench as it ends up.
    steps = [
        STEPS[0],
        {"step": "drive", "bench": "drives", "add": ["plate", "screw"], "model": "up.step"},
        {"step": "lever", "bench": "drives", "add": ["lever"], "model": "down.step"},
        STEPS[2],
    ]
    models = {"up.step": model(with_lever(300)), "down.step": model(with_lever(6 + 15))}
    report = run(with_lever(300), steps=steps, engine=engine, models=models)
    assert told(report)["screw"] == (Verdict.BLOCKED, None)
    assert {r.name: r for r in report.results}["screw"].blockers == ("frame",)
    lowered = report.models["drive-bench"].assembly
    assert lowered is not report.models[None].assembly
    # The other way round, the bench's last step has the lever up: the screw turns.
    flipped = [
        steps[0],
        {**steps[1], "model": "down.step"},
        {**steps[2], "model": "up.step"},
        steps[3],
    ]
    assert told(run(with_lever(300), steps=flipped, engine=engine, models=models))["screw"] == (
        Verdict.TURNS,
        "drive-bench",
    )


def test_a_bench_s_last_step_without_a_model_is_as_drawn():
    steps = [
        STEPS[0],
        {"step": "drive", "bench": "drives", "add": ["plate", "screw"], "model": "down.step"},
        {"step": "lever", "bench": "drives", "add": ["lever"]},
        STEPS[2],
    ]
    models = {"down.step": model(with_lever(6 + 15))}
    report = run(with_lever(300), steps=steps, models=models)
    assert told(report)["screw"] == (Verdict.TURNS, "drive-bench")


def test_a_state_s_own_model_outranks_its_bench_s():
    steps = [STEPS[0], {**LEVER_STEPS[1], "model": "down.step"}, STEPS[2]]
    models = {"down.step": model(with_lever(6 + 15)), "up.step": model(with_lever(300))}
    states = {"drive-bench": {"bench": "drives", "model": "up.step"}}
    report = run(with_lever(6 + 15), states, steps, models=models)
    assert told(report)["screw"] == (Verdict.TURNS, "drive-bench")
    # One up its chain outranks it too.
    chained = {"up": {"model": "up.step"}, "drive-bench": {"base": "up", "bench": "drives"}}
    report = run(
        with_lever(6 + 15), chained, steps, models=models, checks={"try_states": ["drive-bench"]}
    )
    assert told(report)["screw"] == (Verdict.TURNS, "drive-bench")


def test_the_machine_s_parts_in_the_bench_s_model_are_left_out():
    # The way three projects did it by hand: the drive moved 2 m down in a model of
    # its own, the machine's parts where they are. Now the frame in it is no obstacle
    # wherever it is drawn: here, over the screw moved down with it.
    down = [(n, Pos(0, 0, -2000) * s) for n, s in machine()]
    steps = [STEPS[0], {**STEPS[1], "model": "drives.step"}, STEPS[2]]
    report = run(steps=steps, models={"drives.step": model(down)})
    assert told(report) == {
        "screw": (Verdict.TURNS, "drive-bench"),
        "frame_screw": (Verdict.BLOCKED, None),
    }
    assert not any(note.startswith("state ") for note in report.notes), report.notes


def test_a_part_only_the_bench_s_model_has_stays():
    # A stand the drive sits on, on the bench: only its model has it, over the screw.
    stand = ("stand", slab(6 + 15, width=60))
    steps = [STEPS[0], {**STEPS[1], "model": "drives.step"}, STEPS[2]]
    report = run(steps=steps, models={"drives.step": model([*machine(), stand])})
    assert told(report)["screw"] == (Verdict.BLOCKED, None)
    assert "stand" not in report.models["drive-bench"].removed
    assert (
        "state 'drive-bench': its model drives.step has 1 part the main model doesn't: stand"
        in report.notes
    )


def test_a_bench_s_model_lacking_one_of_its_parts_says_so_and_no_other():
    # Its model lacks the lever, a bench part, and the frame, the machine's: only the
    # lever is said.
    steps = [STEPS[0], {**LEVER_STEPS[1], "model": "drives.step"}, STEPS[2]]
    bare = [(n, s) for n, s in with_lever(300) if n not in {"lever", "frame"}]
    report = run(with_lever(300), steps=steps, models={"drives.step": model(bare)})
    said = [note for note in report.notes if note.startswith("state ")]
    assert said == [
        "state 'drive-bench': its model drives.step lacks 1 part of bench drives's: lever"
    ]
    # A state with no bench, in the same model, is said to lack both.
    plain = {"same": {"model": "drives.step"}}
    report = run(with_lever(300), plain, steps=steps, models={"drives.step": model(bare)})
    said = [note for note in report.notes if note.startswith("state ")]
    assert said == [
        "state 'same': its model drives.step lacks 2 parts of the main model's: frame, lever"
    ]


def test_a_bench_s_model_found_nowhere_names_the_step_that_names_it(tmp_path):
    steps = [STEPS[0], {**STEPS[1], "model": "gone.step"}, STEPS[2]]
    sidecar = {
        "fasteners": SCREWS,
        "build": steps,
        "states": ON_THE_BENCH,
        "checks": {"try_states": ["drive-bench"]},
    }
    config = Config.from_dict(sidecar, source="w.yaml")
    with pytest.raises(
        ConfigError,
        match=r"state 'drive-bench': its model gone.step not found \(w.yaml, build\[1\].model; ",
    ):
        check(model(machine()), config, kit="full", model_dir=tmp_path)


# ---------------------------------------------------------------------------
# Parts drawn as several solids.
# ---------------------------------------------------------------------------


def in_pieces(named):
    """The assembly a STEP file of these parts gives, with no file written: a part of
    several solids is its largest, and its pieces."""
    shapes = []
    for name, shape in named:
        shape.label = name
        shapes.append(shape)
    return Assembly.from_compound(Compound(children=shapes))


READERS = pytest.mark.parametrize(
    "reader", [in_pieces, Assembly.from_shapes], ids=["in-pieces", "whole"]
)


def two_solids(*shapes):
    return Compound([shape.solid() for shape in shapes])


@READERS
def test_a_machine_part_of_two_solids_is_off_the_bench_whole(reader):
    # Two bars over the screw, one part: each alone keeps the key off.
    frame = two_solids(slab(6 + 15, x=-5, width=10), slab(6 + 15, x=5, width=10))
    parts = [("frame", frame), *machine()[1:]]
    sidecar = {
        "fasteners": SCREWS,
        "build": STEPS,
        "states": ON_THE_BENCH,
        "checks": {"try_states": ["drive-bench"]},
    }
    report = check(reader(parts), Config.from_dict(sidecar), kit="full")
    assert told(report)["screw"] == (Verdict.TURNS, "drive-bench")


@READERS
def test_a_bench_part_of_two_solids_is_on_the_bench_whole(reader):
    cover = two_solids(slab(6 + 15, x=-5, width=10), slab(6 + 15, x=5, width=10))
    parts = [*machine(), ("cover", cover)]
    steps = [STEPS[0], {**STEPS[1], "add": ["plate", "screw", "cover"]}, STEPS[2]]
    sidecar = {
        "fasteners": SCREWS,
        "build": steps,
        "states": ON_THE_BENCH,
        "checks": {"try_states": ["drive-bench"]},
    }
    report = check(reader(parts), Config.from_dict(sidecar), kit="full")
    by_name = {r.name: r for r in report.results}
    assert (by_name["screw"].verdict, by_name["screw"].state) == (Verdict.BLOCKED, None)
    sidecar["states"] = {"drive-bench": {"bench": "drives", "remove": ["cover"]}}
    report = check(reader(parts), Config.from_dict(sidecar), kit="full")
    assert told(report)["screw"] == (Verdict.TURNS, "drive-bench")


def test_a_bench_s_model_in_pieces_beside_a_whole_main_model():
    frame = two_solids(slab(6 + 15, x=-5, width=10), slab(6 + 15, x=5, width=10))
    steps = [STEPS[0], {**STEPS[1], "model": "drives.step"}, STEPS[2]]
    bench_model = in_pieces([("frame", frame), *machine()[1:]])
    assert "frame#2" in bench_model.names
    report = run(steps=steps, models={"drives.step": bench_model})
    assert told(report)["screw"] == (Verdict.TURNS, "drive-bench")
    assert {"frame", "frame#2"} <= report.models["drive-bench"].removed


# ---------------------------------------------------------------------------
# A plug, the clash list, the command line.
# ---------------------------------------------------------------------------


def jack(x):
    return Pos(x, 0, 5) * Box(20, 12, 10) - Pos(x, 0, 6.5) * Box(16, 8, 7.01)


def boards():
    """A plug in its jack on a board built on bench boards, and the machine's own plug
    beside it; the machine's lid crosses both pulls."""
    return [
        ("board", Pos(0, 0, -1) * Box(400, 100, 2)),
        ("jack", jack(0)),
        ("plug", Pos(0, 0, 13) * Box(16, 8, 20)),
        ("panel_jack", jack(100)),
        ("panel_plug", Pos(100, 0, 13) * Box(16, 8, 20)),
        ("lid", Pos(0, 0, 29) * Box(400, 60, 2)),
    ]


def test_a_plug_comes_off_on_its_bench_and_one_the_bench_hasn_t_isn_t_pulled_there():
    # The machine's plug is given its axis and travel, so it would come off in the
    # air with its jack and lid gone.
    sidecar = {
        "connectors": [{"parts": "plug"}, {"parts": "panel_plug", "axis": "+z", "travel": 10}],
        "build": [
            {"step": "boards", "bench": "boards", "add": ["board", "jack", "plug"]},
            {"step": "rest", "add": ["*"]},
        ],
        "states": {"board-bench": {"bench": "boards"}},
        "checks": {"try_states": ["board-bench"]},
    }
    report = check(model(boards()), Config.from_dict(sidecar))
    pulled = {c.name: (c.verdict, c.state) for c in report.connectors.results}
    assert pulled == {
        "panel_plug": (ConnectorVerdict.STUCK, None),
        "plug": (ConnectorVerdict.UNPLUGS, "board-bench"),
    }
    sidecar["connectors"][1]["state"] = "board-bench"
    report = check(model(boards()), Config.from_dict(sidecar))
    (panel,) = [c for c in report.connectors.results if c.name == "panel_plug"]
    assert (panel.verdict, panel.reason) == (
        ConnectorVerdict.NOT_COVERED,
        "its own state 'board-bench' is on bench boards, and no step on that bench adds it",
    )


def test_the_machine_s_parts_in_a_bench_s_model_draw_no_clash():
    # The bench's model has the frame drawn into the plate and both screws, and the
    # lever into the plate, aside: only the lever, a bench part, is a clash there.
    sunk = [("frame", slab(-5)), *machine()[1:], ("lever", slab(-5, x=-150, width=60))]
    steps = [STEPS[0], {**LEVER_STEPS[1], "model": "drives.step"}, STEPS[2]]
    sidecar = {"fasteners": SCREWS, "build": steps, "states": ON_THE_BENCH}
    clashes = find_clashes(
        model(with_lever(300)), Config.from_dict(sidecar), models={"drives.step": model(sunk)}
    )
    assert [(c.first, c.second, c.state) for c in clashes.found] == [
        ("lever", "plate", "drive-bench")
    ]


def test_the_command_line_reads_a_state_s_bench(tmp_path):
    shapes = []
    for name, shape in machine():
        shape.label = name
        shapes.append(shape)
    export_step(Compound(children=shapes), str(tmp_path / "drive.step"))
    (tmp_path / "wrenchroom.yaml").write_text(
        json.dumps(
            {
                "fasteners": [{"parts": "screw", **M6_SOCKET}],
                "ignore": ["frame_screw"],
                "build": [*STEPS[:2], {"step": "late", "add": ["*"]}],
                "states": ON_THE_BENCH,
                "checks": {"try_states": ["drive-bench"]},
            }
        )
    )
    result = CliRunner().invoke(
        main, ["check", str(tmp_path / "drive.step"), "--kit", "full", "--json", "-"]
    )
    assert result.exit_code == 0, result.output
    (screw,) = json.loads(result.stdout)["fasteners"]
    assert (screw["verdict"], screw["state"]) == ("turns", "drive-bench")
    (tmp_path / "wrenchroom.yaml").write_text(
        json.dumps({"build": STEPS, "states": {"s": {"bench": "drive"}}})
    )
    result = CliRunner().invoke(main, ["check", str(tmp_path / "drive.step")])
    assert result.exit_code == 2
    assert "bench 'drive' is no build step's bench; the nearest: drives" in result.output
