"""Every bench fastener, checked alone, reads as it does in the full run (issue #46).

``explain NAME`` and ``check --only NAME`` narrow what is reported, never what is
resolved: a held nut's bolt, a pair's partner, are checked with it. So each of the
bench's fasteners, narrowed to itself, must come out field for field as in the
whole bench's check.
"""

from bench import KIT

from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.detect.sidecar import glob_escape


def test_every_fastener_narrowed_to_itself_reads_as_in_the_full_run(bench_dir):
    assembly = Assembly.from_step(bench_dir / "bench.step")
    config = Config.load(bench_dir / "wrenchroom.yaml")
    full = check(assembly, config, kit=KIT, model_dir=bench_dir)
    paired = [r for r in full.results if r.pair]
    assert len(paired) >= 6  # a vacuity guard: the bench's joints are what this is about
    differ = []
    for whole in full.results:
        name = whole.fastener.name
        narrowed = check(assembly, config, kit=KIT, model_dir=bench_dir, only=glob_escape(name))
        (alone,) = narrowed.results
        want = (whole.verdict, whole.tool, whole.how, whole.pair, whole.reason, whole.blockers)
        got = (alone.verdict, alone.tool, alone.how, alone.pair, alone.reason, alone.blockers)
        if got != want:
            differ.append((name, got, want))
    assert not differ
