"""Truth per fastener, the whole-bench counts, isolation and the round trip."""

import pytest
from bench import FINAL_COUNTS, KIT, build, check_bench, sidecar_and_truth
from cells import CELLS

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.config import Config


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
