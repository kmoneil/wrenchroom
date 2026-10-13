"""Each cell of the bench checked alone reads as it does in the whole bench.

In a file of its own: it is the longest test the bench has but one, and the lanes
run a file to a process, so here it runs beside test_bench.py and not after it.
"""

from bench import KIT, sidecar_and_truth
from cells import CELLS

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.config import Config


def test_isolation_matches_the_full_bench(bench_json, bench_models, bench_engine):
    """Each cell alone (from shapes, no STEP) must agree with the whole bench:
    a difference means a tool reaches across cells or the STEP path changes
    something. Twins are excluded: they exist to test the STEP path itself.
    The states and checks sections ride along so state cells isolate too; the
    lever retry is in the written lever-up model, the one the full run reads,
    here read the once and given to each cell's check."""
    bench_sidecar, _ = sidecar_and_truth()
    differences, states = [], set()
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
            Assembly.from_shapes(shapes), config, kit=KIT, models=bench_models, engine=bench_engine
        )
        for result in report.results:
            states.add(result.state)
            alone = (result.verdict.value, result.tool, result.how)
            entry = bench_json[result.fastener.name]
            together = (entry["verdict"], entry["tool"], entry["how"])
            if alone != together:
                differences.append((result.fastener.name, alone, together))
    assert not differences
    assert "lever-up" in states  # the guard: a cell's retry was in the model given
