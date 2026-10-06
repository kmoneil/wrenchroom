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
    expected = sorted(shape.label for shape in build())
    assembly = Assembly.from_step(bench_dir / "bench.step")
    assert sorted(assembly.names) == expected


def test_socket_false_is_load_bearing():
    """glands_close with socket: true would turn by socket-24 over the ignored
    cable: the flag is what keeps the cell honest."""
    glands_close = next(cell for cell in CELLS if cell.name == "glands_close")
    shapes = [(f"glands_close_{role}", shape) for role, shape in glands_close.build()]
    config = Config.from_dict(
        {
            "fasteners": [
                {"parts": "glands_close_*_gland", "kind": "nut", "size": "M16", "socket": True}
            ],
            "ignore": ["*_cable"],
        }
    )
    report = check(Assembly.from_shapes(shapes), config, kit=KIT)
    for result in report.results:
        assert result.verdict.value == "turns"
        assert result.tool == "socket-24"


def test_config_edges(bench_dir):
    """The edges sidecar: unmatched rule and ignore reported, exit 2; the rule
    calling torx_open's screw a Torx head outranks detection, so it takes the
    full kit's T30 straight in (open above), and metric-home has no Torx key."""
    report = check_bench(bench_dir, config_name="bench_edges.yaml")
    assert report.unmatched_rules == ("gone_*",)
    assert report.unmatched_ignores == ("*_hose",)
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
