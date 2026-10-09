"""The bench's clashes (M8): every pair of its parts drawn into each other, both engines.

The bench's own sidecar ignores the cells drawn as faults on purpose, so its clashes
are M8's own two: press_fit's rod the sidecar doesn't allow, and state_clash's
slider, into its wall in bench_lever-up.step alone. Its threads in their holes,
drawn at a tap drill or at a minor diameter, a bolt in its nut and every mate, are
none. The edges sidecar keeps the faults: each drawn-in cell's fastener is a clash,
measured as #63's "drawn into" measures it.
"""

import pytest
from bench import edges_sidecar

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check, find_clashes
from wrenchroom.config import Config

PRESS_FIT = "a press fit, 0.03 deep? allow it in the sidecar"


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
    # gives (drawn_in's 5.2, 96.1 and 28.4, twice's 8.9, cap_dome's 524.3 and 67.0,
    # set_core's 3.9), and press_fit's two rods, allowed only by the bench's own.
    config = Config.from_dict(edges_sidecar(), source="edges")
    found = find_clashes(bench_model, config, model_dir=bench_dir, engine=bench_engine)
    assert said(found) == [
        ("cap_dome_buried_nut", "cap_dome_buried_cover", 524.3, None, None),
        ("cap_dome_dome_nut", "cap_dome_dome_cover", 67.0, None, None),
        ("domed_button_buried_screw", "domed_button_buried_block", 18.1, None, None),
        ("domed_flat_cone_screw", "domed_flat_cone_block", 128.2, None, None),
        ("domed_flat_thread_screw", "domed_flat_thread_block", 111.4, None, None),
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
        ("twice_dup_screw", "twice_dup_M3x12_screw", 64.2, None, None),
        ("twice_side_screw", "twice_side_box", 8.9, None, None),
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
