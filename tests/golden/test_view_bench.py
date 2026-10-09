"""M5's exit test, on the data the page draws: the bench report shows every
blocked and stuck cell in red, with its blockers highlighted.

Run on both engines. Whether a browser then draws these decisions is
test_view_browser.py's part; this file holds the decisions themselves to the
bench's hand-worked truth, and holds every drawn tool position to what the check
recorded.
"""

import pytest
from bench import FINAL_COUNTS

from wrenchroom.view import COLOURS, view_data

#: The cells that pass only in a state other than the run's own (it has none):
#: the lid-off screw, by its own rule, and the lever screw, by try_states.
ELSEWHERE = {"state_lid_screw", "state_lever_screw"}


@pytest.fixture(scope="session")
def bench_view(bench_report):
    return view_data(bench_report)


def _fasteners(view):
    return {entry["name"]: entry for entry in view["fasteners"]}


def _names(view, indices):
    return [view["parts"][index]["name"] for index in indices]


def test_every_blocked_and_stuck_cell_is_red_with_its_blockers(bench_view, bench_truth, bench_json):
    drawn = _fasteners(bench_view)
    failing = {n: t for n, t in bench_truth.items() if t["verdict"] in {"blocked", "stuck"}}
    assert len(failing) == FINAL_COUNTS["blocked"] + FINAL_COUNTS["stuck"]
    for name, truth in failing.items():
        entry = drawn[name]
        assert entry["verdict"] == truth["verdict"], name
        assert entry["colour"] == COLOURS["fails"], name
        key = "stuck_on" if truth["verdict"] == "stuck" else "blocked_by"
        highlighted = _names(bench_view, entry["highlight"])
        # A part its own body stops names itself, and is drawn as itself (#47).
        others = sorted(n for n in bench_json[name][key] if n != name)
        assert sorted(highlighted) == others, name
        if key in truth:  # hand-worked: the blockers a person would name
            assert sorted(highlighted) == sorted(n for n in truth[key] if n != name), name
        # Each highlighted part is drawn in the fastener's view...
        assert set(entry["highlight"]) <= set(bench_view["views"][entry["view"]]["parts"]), name
        # ...and a drawn tool position ran into it.
        probes = [p for a in entry["attempts"] for p in a["probes"]]
        if entry["way_out"] is not None:
            probes.append(entry["way_out"])
        hit = {index for probe in probes for index in probe["hits"]}
        assert set(entry["highlight"]) <= hit, name
        if not probes:  # nothing in its joint turns, so no tool was tried (#134)
            assert bench_json[name]["reason"].endswith(": nothing in the joint turns"), name
            continue
        assert any(probe["hit"] for probe in probes), name


def test_the_hand_worked_blockers_are_not_vacuous(bench_truth):
    named = [t for t in bench_truth.values() if t.get("blocked_by") or t.get("stuck_on")]
    assert len(named) >= 6  # 8 until M6's open end turned glands_close's two


def test_nothing_that_passes_is_red(bench_view):
    for entry in bench_view["fasteners"]:
        if entry["verdict"] in {"turns", "held"}:
            want = "elsewhere" if entry["name"] in ELSEWHERE else entry["verdict"]
            assert entry["colour"] == COLOURS[want], entry["name"]
            assert entry["highlight"] == [], entry["name"]
        assert entry["verdict"] != "not-covered"


def test_the_lever_screw_is_drawn_with_the_lever_raised(bench_view):
    drawn = _fasteners(bench_view)
    views = bench_view["views"]
    overview = views[bench_view["overview"]]
    lever_view = views[drawn["state_lever_screw"]["view"]]
    assert lever_view["state"] == "lever-up"
    names = [part["name"] for part in bench_view["parts"]]

    def lever(view):
        (index,) = [i for i in view["parts"] if names[i] == "state_lever_lever"]
        return index

    assert lever(lever_view) != lever(overview)  # the raised lever is its own part
    # Everything else in the lever-up model is the same part, drawn once.
    assert len(set(lever_view["parts"]) - set(overview["parts"])) == 1


def test_the_lid_screw_is_drawn_with_the_lid_off(bench_view):
    drawn = _fasteners(bench_view)
    lid_view = bench_view["views"][drawn["state_lid_screw"]["view"]]
    assert lid_view["state"] == "lid-off"
    assert "state_lid_lid" not in _names(bench_view, lid_view["parts"])
    overview = bench_view["views"][bench_view["overview"]]
    assert "state_lid_lid" in _names(bench_view, overview["parts"])


def test_every_part_is_drawn_and_marked(bench_view, bench_report):
    overview = bench_view["views"][bench_view["overview"]]
    names = _names(bench_view, overview["parts"])
    assert sorted(names) == sorted(bench_report.models[None].assembly.names)
    roles = {part["name"]: part["role"] for part in bench_view["parts"]}
    # A fastener's pieces (issue #28: a leaf of several solids) are drawn as it.
    assembly = bench_report.models[None].assembly
    fastener_names = {r.fastener.name for r in bench_report.results}
    pieces = {part.name for part in assembly if part.piece_of in fastener_names}
    assert pieces == {"one_part_lock_nut#2"}
    assert {n for n, role in roles.items() if role == "fastener"} == fastener_names | pieces
    owners = {part["name"]: part["owner"] for part in bench_view["parts"] if part["owner"]}
    assert owners == {"one_part_lock_nut#2": "one_part_lock_nut"}
    assert {n for n, role in roles.items() if role == "ignored"} == set(bench_report.ignored)
    assert bench_report.ignored  # the bench ignores its hoses and wires
    assert all(part["shape"] is not None for part in bench_view["parts"])


def test_attempts_record_every_position_they_tested(bench_report):
    """The probes are the attempt, position by position: its blockers are their
    hits in order, an engagement that hits stops it, and nothing turns on a hit."""
    checked = 0
    for result in bench_report.results:
        for attempt in result.attempts:
            assert attempt.probes, (result.fastener.name, attempt)
            seen = []
            for probe in attempt.probes:
                for name in probe.hits:
                    if name not in seen:
                        seen.append(name)
            assert tuple(seen) == attempt.blockers, (result.fastener.name, attempt.way)
            if attempt.probes[0].hits:
                assert len(attempt.probes) == 1
                assert not attempt.turns
                assert not attempt.holds
            if attempt.turns and attempt.way == "driver straight in":
                assert len(attempt.probes) == 1
                assert not attempt.probes[0].hits
            checked += 1
        if result.way_out is not None and result.verdict == "stuck":
            assert result.way_out.hits == result.stuck_on
    assert checked > 50
