"""Truth per fastener, the whole-bench counts, isolation and the round trip."""

import shutil

import pytest
import yaml
from bench import FINAL_COUNTS, KIT, build, check_bench, sidecar_and_truth
from build123d import Compound, export_step
from cells import CELLS

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import md_text


def _truth_params():
    _, truth = sidecar_and_truth()  # static: no geometry built at collection
    return [pytest.param(name, expected, id=name) for name, expected in sorted(truth.items())]


def _expected_fields(expected):
    return {k: v for k, v in expected.items() if k != "needs"}


@pytest.mark.parametrize(("name", "expected"), _truth_params())
def test_truth(request, name, expected, bench_json):
    needs = expected.get("needs")
    if needs:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"waiting on {needs}"))
    entry = bench_json.get(name)
    assert entry is not None, f"{name} missing from the report"
    for key, want in _expected_fields(expected).items():
        got = entry[key]
        if isinstance(want, list):
            assert sorted(got) == sorted(want), f"{name}.{key}"
        else:
            assert got == want, f"{name}.{key}"


def test_whole_bench_counts(bench_report, bench_engine):
    assert bench_report.summary == FINAL_COUNTS
    assert bench_report.exit_code == 1  # the bench has deliberate failures
    assert bench_report.engine == bench_engine


def test_isolation_matches_the_full_bench(bench_json, bench_dir, bench_engine):
    """Each cell alone (from shapes, no STEP) must agree with the whole bench:
    a difference means a tool reaches across cells or the STEP path changes
    something. Twins are excluded: they exist to test the STEP path itself.
    The states and checks sections ride along so state cells isolate too; the
    lever retry loads the written lever-up model from bench_dir, same as the
    full run."""
    bench_sidecar, _ = sidecar_and_truth()
    differences = []
    for cell in CELLS:
        if not cell.truth:
            continue
        shapes = [(f"{cell.name}_{role}", shape) for role, shape in cell.build()]
        rules = []
        for rule in cell.rules:
            entry = dict(rule)
            entry["parts"] = f"{cell.name}_{entry['parts']}"
            if "mates" in entry:
                entry["mates"] = [f"{cell.name}_{m}" for m in entry["mates"]]
            rules.append(entry)
        config = Config.from_dict(
            {
                "fasteners": rules,
                "ignore": list(cell.ignore),
                "states": bench_sidecar["states"],
                "checks": bench_sidecar["checks"],
                "tools": bench_sidecar.get("tools", []),
            }
        )
        report = check(
            Assembly.from_shapes(shapes), config, kit=KIT, model_dir=bench_dir, engine=bench_engine
        )
        for result in report.results:
            alone = (result.verdict.value, result.tool, result.how)
            entry = bench_json[result.fastener.name]
            together = (entry["verdict"], entry["tool"], entry["how"])
            if alone != together:
                differences.append((result.fastener.name, alone, together))
    assert not differences


def test_round_trip_names(bench_dir):
    # A part of several solids reads as one per solid, the rest numbered after it
    # and marked as its pieces (issue #28): only one_part_lock's nut has two.
    expected, pieces = [], {}
    for shape in build():
        expected.append(shape.label)
        for k in range(2, len(shape.solids()) + 1):
            expected.append(f"{shape.label}#{k}")
            pieces[f"{shape.label}#{k}"] = shape.label
    assembly = Assembly.from_step(bench_dir / "bench.step")
    assert sorted(assembly.names) == sorted(expected)
    assert {p.name: p.piece_of for p in assembly if p.piece_of} == pieces
    assert pieces == {"one_part_lock_nut#2": "one_part_lock_nut"}


def test_socket_false_is_load_bearing():
    """gland_rib with socket: true would turn by socket-24 over the ignored cable,
    where with socket: false the ring and the open end both fail at the rib: the
    flag is what keeps the cell honest. (glands_close showed this until M6's open
    end turned it from the side, before any socket is tried.)"""
    gland_rib = next(cell for cell in CELLS if cell.name == "gland_rib")
    shapes = [(f"gland_rib_{role}", shape) for role, shape in gland_rib.build()]
    rule = {"parts": "gland_rib_gland", "kind": "nut", "size": "M16", "axis": "+z"}
    verdicts = {}
    for socket in (True, False):
        config = Config.from_dict(
            {"fasteners": [{**rule, "socket": socket}], "ignore": ["*_cable"]}
        )
        (result,) = check(Assembly.from_shapes(shapes), config, kit=KIT).results
        verdicts[socket] = (result.verdict.value, result.tool)
    assert verdicts == {True: ("turns", "socket-24"), False: ("blocked", "spanner-24")}


def test_config_edges(bench_dir):
    """The edges sidecar: unmatched rule, ignore and mate reported, exit 2; the
    rule calling torx_open's screw a Torx head outranks detection, so it takes
    the full kit's T30 straight in (open above), and metric-home has no Torx key."""
    report = check_bench(bench_dir, config_name="bench_edges.yaml")
    assert report.unmatched_rules == ("gone_*",)
    assert report.unmatched_ignores == ("*_hose",)
    assert report.warnings == (
        "rule 'torx_open_screw': mate glob 'gone_washer_*' matched nothing (renamed part?)",
    )
    (torx,) = [r for r in report.results if r.fastener.name == "torx_open_screw"]
    assert (torx.verdict.value, torx.tool, torx.how) == (
        "turns",
        "torx-key-T30",
        "driver straight in",
    )
    assert report.exit_code == 2
    home = check_bench(bench_dir, config_name="bench_edges.yaml", kit="metric-home")
    (torx,) = [r for r in home.results if r.fastener.name == "torx_open_screw"]
    assert torx.reason == "needs torx-key-T30, which kit metric-home does not hold (full has it)"


@pytest.fixture(scope="module")
def edges_report(bench_dir, bench_engine):
    return check_bench(bench_dir, config_name="bench_edges.yaml", engine=bench_engine)


FREE_FACE = "cannot tell the nut's free face: both ends are covered"


def test_a_nut_drawn_into_a_part_is_a_clash(edges_report):
    """Issue #63: drawn_in's fasteners, which only the edges sidecar keeps (the
    bench's own runs ignore them, a clash being not-covered). Each clash names what
    it is drawn into, with no tool, and the model to fix; the volumes, by hand:

    - side: the corner's tip 1 deep, 1.73 mm^2, 3 tall: 5.2 mm^3;
    - top: the hex less its bore, 1 deep: 146.36 - 50.27 = 96.1;
    - head: the head less its key's hex, 0.5 deep: (78.54 - 21.65) * 0.5 = 28.4;
    - fat: the stud past the minor bore over the nut: pi (4.5^2 - 3.32^2) 6.8 = 196.6;
    - tapped: the head alone, its top (28.4) and its side, pi (5^2 - 4.5^2) 5.5 =
      82.1: 110.5; the shank's 186 in its tapped hole, a thread, isn't told;
    - flange: the hex's tip over z 1.5 to 6, 1.73 * 4.5 = 7.79, and the flange's
      segment past x 6.51, 121 acos(6.51 / 11) - 6.51 sqrt(121 - 6.51^2) = 55.79
      mm^2, 1.5 thick, 83.68: 91.5.

    The thread_nut's stud is its thread and the pair_nut's bolt its partner: no
    clash, and the lid over each leaves only the free face untold. The side_chip,
    in the side_nut, stops nothing and isn't named."""
    by_name = {r.fastener.name: r for r in edges_report.results}
    clashes = {
        name: (r.verdict.value, r.tool, r.reason)
        for name, r in by_name.items()
        if name.startswith("drawn_in_")
    }
    assert clashes == {
        "drawn_in_side_nut": (
            "not-covered",
            None,
            "drawn into drawn_in_side_block (5.2 mm^3): fix the model",
        ),
        "drawn_in_top_nut": (
            "not-covered",
            None,
            "drawn into drawn_in_top_block (96.1 mm^3): fix the model",
        ),
        "drawn_in_head_screw": (
            "not-covered",
            None,
            "drawn into drawn_in_head_block (28.4 mm^3): fix the model",
        ),
        "drawn_in_fat_nut": (
            "not-covered",
            None,
            "drawn into drawn_in_fat_stud (196.6 mm^3): fix the model",
        ),
        "drawn_in_tapped_screw": (
            "not-covered",
            None,
            "drawn into drawn_in_tapped_block (110.5 mm^3): fix the model",
        ),
        "drawn_in_flange_nut": (
            "not-covered",
            None,
            "drawn into drawn_in_flange_block (91.5 mm^3): fix the model",
        ),
        "drawn_in_thread_nut": ("not-covered", None, FREE_FACE),
        "drawn_in_pair_nut": ("not-covered", None, FREE_FACE),
        "drawn_in_pair_bolt": ("turns", "spanner-13", None),
    }
    assert by_name["drawn_in_pair_nut"].pair == "drawn_in_pair_bolt"
    lines = edges_report.terminal_lines()
    assert "FAIL drawn_in_top_nut  -  not-covered  drawn into drawn_in_top_block" in "\n".join(
        lines
    )
    # The corner the block only touches is no clash: corner_touch's nut is blocked.
    assert by_name["corner_touch_nut"].verdict.value == "blocked"


def test_a_rule_s_tool_that_can_t_drive_its_fastener_is_not_covered(edges_report):
    """Issue #72: wrong_tool's fasteners, which only the edges sidecar keeps. Each
    misfit is not covered and nothing is swept; a tool no table holds says so; the
    nut drawn 15 under an M10 rule takes the spanner-15 its rule names."""
    by_name = {r.fastener.name: r for r in edges_report.results}
    hint = "; give its rule across_flats: {0} if its hex really is {0}"
    misfits = {
        "size_nut": "its tool: spanner-10 is 10 across flats, but the nut (M8) takes 13"
        + hint.format(10),
        "kind_nut": "its tool: hex-key-5 is a hex key, which doesn't fit the nut (M8)",
        "custom_nut": "its tool: shop-spanner-23 is 23 across flats, but the nut (M8) takes 13"
        + hint.format(23),
        "unknown_nut": "needs spanner-99, which kit full does not hold; no kit has it",
        "button_screw": (
            "its tool: spanner-10 is a spanner, which doesn't fit the button head (M6)"
        ),
        "slot_screw": (
            "its tool: driver-slotted is a slotted driver, which doesn't fit the socket head (M6)"
        ),
        "torx_screw": "no Torx key T99: the tables hold T10 to T40",
        "phillips_screw": "its tool: driver-ph1 is PH1, but the Phillips head (M4) takes PH2",
    }
    for role, reason in misfits.items():
        result = by_name[f"wrong_tool_{role}"]
        assert (result.verdict.value, result.attempts, result.reason) == (
            "not-covered",
            (),
            reason,
        ), role
    drawn = by_name["wrong_tool_drawn_nut"]
    assert (drawn.verdict.value, drawn.tool) == ("turns", "spanner-15")


def test_a_state_model_missing_a_fastener_fails_the_run(bench_dir, tmp_path):
    """Issue #74, as reported: the bench with state_lever_screw renamed in its
    lever-up model. The screw passes only with the lever up; renamed there, it isn't
    tried there, which fails the run, and the rename is noted."""
    for name in ("bench.step", "wrenchroom.yaml"):
        shutil.copy(bench_dir / name, tmp_path / name)
    shapes = []
    for part in Assembly.from_step(bench_dir / "bench_lever-up.step"):
        renamed = part.name == "state_lever_screw"
        part.shape.label = f"{part.name}_renamed" if renamed else part.name
        shapes.append(part.shape)
    export_step(Compound(children=shapes), str(tmp_path / "bench_lever-up.step"))
    report = check_bench(tmp_path)
    (screw,) = [r for r in report.results if r.fastener.name == "state_lever_screw"]
    assert (screw.verdict.value, screw.blocked_by) == ("blocked", ("state_lever_lever",))
    assert report.warnings == (
        "state 'lever-up': its model bench_lever-up.step has no part state_lever_screw "
        "(renamed?), so it wasn't tried there",
    )
    (note,) = report.notes
    assert note == (
        "state 'lever-up': its model bench_lever-up.step lacks 1 part of the main model's: "
        "state_lever_screw; has 1 part the main model doesn't: state_lever_screw_renamed"
    )
    assert report.exit_code == 2
    lines = report.terminal_lines()
    assert f"WARN {report.warnings[0]}" in lines
    assert f"NOTE {note}" in lines
    assert f"- {md_text(note)}" in report.markdown()
    # With lever-up its own state (the rule says so), the screw is not covered,
    # naming the model, and nothing warns twice.
    sidecar = yaml.safe_load((tmp_path / "wrenchroom.yaml").read_text())
    for rule in sidecar["fasteners"]:
        if rule["parts"] == "state_lever_screw":
            rule["state"] = "lever-up"
    (tmp_path / "wrenchroom.yaml").write_text(yaml.safe_dump(sidecar, sort_keys=False))
    own = check_bench(tmp_path)
    (screw,) = [r for r in own.results if r.fastener.name == "state_lever_screw"]
    assert (screw.verdict.value, screw.reason) == (
        "not-covered",
        "not in state 'lever-up', whose model bench_lever-up.step has no part of its name "
        "(renamed?)",
    )
    assert own.warnings == ()


def test_a_nut_its_corners_cannot_turn_says_so_once(bench_report, bench_json):
    """Issue #63: corner_touch's nut, stopped by its own corners, not by a tool. One
    attempt, the corners' sweep, and one reason; not every tool blocked by the block.
    (Not in the truth table: the reason names the block, which a copy renames.)"""
    entry = bench_json["corner_touch_nut"]
    assert entry["reason"] == "the nut's corners hit corner_touch_block as it turns"
    (result,) = [r for r in bench_report.results if r.fastener.name == "corner_touch_nut"]
    assert [(a.way, a.blockers) for a in result.attempts] == [
        ("its corners, turning", ("corner_touch_block",))
    ]
    (fail,) = [line for line in bench_report.terminal_lines() if "corner_touch_nut" in line]
    assert fail == f"FAIL corner_touch_nut  spanner-13  blocked  {entry['reason']}"


def test_the_undersize_nut_is_noted_in_every_format(bench_report, bench_json):
    """Issue #50: the one note on the described bench, as each report gives it."""
    note = (
        "hex drawn undersize: 12.60 across flats, 0.13 under the least its M8 standard "
        "allows (12.73); taken as size 13"
    )
    lines = bench_report.terminal_lines()
    assert [line for line in lines if "hex drawn" in line] == [f"NOTE undersize_nut: {note}"]
    markdown = bench_report.markdown()
    assert "\n#### Notes\n\n" in markdown
    assert f"\n- `undersize_nut`: {note}\n" in markdown.split("#### Notes")[1]
    noted = {name for name, entry in bench_json.items() if entry["notes"]}
    # And #47's own bodies, and #51's pass only a ball end reaches.
    assert noted == {
        "undersize_nut",
        "wide_dome_gland",
        "sunk_cap_cap_nut",
        "ball_tilt_screw",
        "ball_shoulder_screw",
    }


def test_a_blocked_nut_names_the_posts_that_decided_it(bench_report, bench_json):
    """Issue #52: post_ring's nut, hit by all six posts, decided by two."""
    entry = bench_json["post_ring_nut"]
    deciding = entry["deciding"]
    assert sorted(deciding) == ["post_ring_post_a", "post_ring_post_b"]
    assert entry["blocked_by"][:2] == deciding
    assert len(entry["blocked_by"]) == 6
    (fail,) = [line for line in bench_report.terminal_lines() if "post_ring_nut" in line]
    assert fail.endswith(
        f"only holds, and it has no nut; best arc between {deciding[0]} and {deciding[1]}"
    )
