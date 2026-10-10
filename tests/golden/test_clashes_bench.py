"""The bench's clashes (M8): every pair of its parts drawn into each other, both engines.

The bench's own sidecar ignores the cells drawn as faults on purpose, so its clashes
are M8's own two: press_fit's rod the sidecar doesn't allow, and state_clash's
slider, into its wall in bench_lever-up.step alone. Its threads in their holes,
drawn at a tap drill or at a minor diameter, a bolt in its nut and every mate, are
none. The edges sidecar keeps the faults: each drawn-in cell's fastener is a clash,
measured as #63's "drawn into" measures it, and every clash a verdict tells is in
the list, to the volume (issue #156).
"""

import re

import pytest
from bench import edges_sidecar

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check, find_clashes
from wrenchroom.config import Config

PRESS_FIT = "a press fit, 0.03 deep? allow it in the sidecar"
TWICE = "one fastener drawn twice"


@pytest.fixture(scope="module")
def bench_model(bench_dir):
    return Assembly.from_step(bench_dir / "bench.step")


def said(found):
    return [(c.first, c.second, round(c.volume, 1), c.state, c.hint) for c in found.found]


def test_the_bench_s_clashes_are_the_two_drawn_for_them(bench_dir, bench_model, bench_engine):
    config = Config.load(bench_dir / "wrenchroom.yaml")
    found = find_clashes(bench_model, config, model_dir=bench_dir, engine=bench_engine)
    assert said(found) == [
        ("press_fit_pressed_rod", "press_fit_block", 3.8, None, PRESS_FIT),
        ("state_clash_slider", "state_clash_wall", 200.0, "lever-up", None),
    ]
    assert (found.unmatched_allows, found.unmeasured, found.exit_code) == ((), (), 1)
    # The cells whose threads sit in holes at their minor or a tap drill: none.
    names = {name for clash in found.found for name in (clash.first, clash.second)}
    for cell in ("minor_bore", "tapped_hold", "tee_hold", "badge", "trap", "head_trap"):
        assert not any(name.startswith(f"{cell}_") for name in names), cell


def test_the_edges_bench_s_faults_are_each_a_clash(bench_dir, bench_model, bench_engine):
    # No ignores and no states: every drawn-in cell's fault, the volumes its cell
    # gives (drawn_in's 5.2, 96.1 and 28.4, twice's 8.9 and its screw drawn twice,
    # all 120.8 of it, cap_dome's 524.3 and 67.0, set_core's 3.9, domed's heads,
    # 62.4, 4.5, 16.7 and 16.8, stud_dome's two domes), and press_fit's two rods,
    # allowed only by the bench's own. domed's flat_thread, a countersunk screw's
    # thread in its tapped hole, is none: it was 111.4, its whole screw measured
    # (issue #156), as its cone was 128.2 and its buried button head 18.1, the rim.
    config = Config.from_dict(edges_sidecar(), source="edges")
    found = find_clashes(bench_model, config, model_dir=bench_dir, engine=bench_engine)
    assert said(found) == [
        ("cap_dome_buried_nut", "cap_dome_buried_cover", 524.3, None, None),
        ("cap_dome_dome_nut", "cap_dome_dome_cover", 67.0, None, None),
        ("domed_button_buried_screw", "domed_button_buried_block", 62.4, None, None),
        ("domed_button_dome_screw", "domed_button_dome_cover", 4.5, None, None),
        ("domed_flat_cone_screw", "domed_flat_cone_block", 16.8, None, None),
        ("domed_pan_screw", "domed_pan_cover", 16.7, None, None),
        ("drawn_in_fat_nut", "drawn_in_fat_stud", 196.6, None, None),
        ("drawn_in_flange_nut", "drawn_in_flange_block", 91.5, None, None),
        ("drawn_in_head_screw", "drawn_in_head_block", 28.4, None, None),
        ("drawn_in_side_nut", "drawn_in_side_block", 5.2, None, None),
        ("drawn_in_side_nut", "drawn_in_side_chip", 0.5, None, None),
        ("drawn_in_tapped_screw", "drawn_in_tapped_block", 110.5, None, None),
        ("drawn_in_top_nut", "drawn_in_top_block", 96.1, None, None),
        ("press_fit_allowed_rod", "press_fit_block", 3.8, None, PRESS_FIT),
        ("press_fit_pressed_rod", "press_fit_block", 3.8, None, PRESS_FIT),
        ("set_core_screw", "set_core_hub", 3.9, None, None),
        ("stud_dome_open_nut", "stud_dome_open_cover", 67.0, None, None),
        ("stud_dome_shut_nut", "stud_dome_shut_cover", 67.0, None, None),
        ("twice_dup_screw", "twice_dup_M3x12_screw", 120.8, None, TWICE),
        ("twice_side_screw", "twice_side_box", 8.9, None, None),
    ]


DRAWN_INTO = re.compile(r"drawn into (.+) \(([\d.]+) mm\^3\): fix the model")
DRAWN_TWICE = re.compile(r"drawn twice: (.+) is drawn over it \(([\d.]+) mm\^3 in common\)")


def test_every_clash_a_verdict_tells_is_in_the_list_to_the_volume(
    bench_dir, bench_model, bench_engine
):
    """Issue #156: one measure for both. Each "drawn into" a verdict of the edges
    bench tells, and its "drawn twice", is a line of the same run's clash list, the
    same two parts and the same volume: the list measures a fastener to the end the
    check does. The list has more: a clash that stops no tool gets no verdict."""
    config = Config.from_dict(edges_sidecar(), source="edges")
    report = check(
        bench_model, config, kit="full", model_dir=bench_dir, engine=bench_engine, clashes=True
    )
    listed = {(c.first, c.second): f"{c.volume:.1f}" for c in report.clashes.found}
    told = {}
    for result in report.results:
        name, reason = result.fastener.name, result.reason or ""
        into, twice = DRAWN_INTO.fullmatch(reason), DRAWN_TWICE.match(reason)
        if into:
            told[name, into[1]] = into[2]
        if twice:  # said on the first by name, of the one drawn over it
            told[twice[1], name] = twice[2]
    assert len(told) == 16  # the guard: every drawn-in cell's verdict is read
    assert {pair: listed.get(pair) for pair in told} == told
    # What the list alone tells: drawn_in's chip (a second part its nut is drawn
    # into, which stops no tool), press_fit's rods (no fasteners), stud_dome's
    # open nut, which turns.
    assert sorted(set(listed) - set(told)) == [
        ("drawn_in_side_nut", "drawn_in_side_chip"),
        ("press_fit_allowed_rod", "press_fit_block"),
        ("press_fit_pressed_rod", "press_fit_block"),
        ("stud_dome_open_nut", "stud_dome_open_cover"),
    ]


def test_the_bench_checked_with_clashes_says_them_and_nothing_else_moves(
    bench_dir, bench_model, bench_report
):
    # The same check, clashes on: its verdicts are the bench's, its exit still 1.
    config = Config.load(bench_dir / "wrenchroom.yaml")
    on = check(bench_model, config, kit="full", model_dir=bench_dir, clashes=True)
    assert [r.verdict for r in on.results] == [r.verdict for r in bench_report.results]
    assert len(on.clashes.found) == 2
    assert on.exit_code == 1
    assert "CLASH state_clash_slider into state_clash_wall  200.0 mm^3  in state lever-up" in (
        on.terminal_lines()
    )
