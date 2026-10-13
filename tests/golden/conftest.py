"""The bench is built once per session and checked once per engine; tests read that.

`bench_report` and `bench_json` are parametrised over the engines, so every
truth, count and snapshot test runs on both: the mesh engine is the default,
and the exact engine is the referee it must agree with.

Each engine's report is kept for the session once it is made. pytest holds one value
of a parametrised fixture at a time, and the lanes run the suite a file at a time
(`--dist loadfile`), where a session goes mesh, exact and mesh again with every file:
left to the fixture alone, the bench would be checked on both engines for each.
"""

from functools import cache

import pytest
from bench import LEVER_UP, check_bench, sidecar_and_truth, write

from wrenchroom.assembly import Assembly
from wrenchroom.engine import ENGINES


@pytest.fixture(scope="session")
def bench_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("bench")
    write(directory)
    return directory


@pytest.fixture(scope="session")
def bench_models(bench_dir):
    """The bench's lever-up model read once, as ``check(models=)`` takes it.

    A check reads a state's model when a fastener that fails is tried in it. A test
    that checks the bench over and over, each fastener or each cell alone, would read
    the one file each time, a second apiece: most of what such a test took.
    """
    return {LEVER_UP: Assembly.from_step(bench_dir / LEVER_UP)}


@pytest.fixture(scope="session")
def bench_truth():
    return sidecar_and_truth()[1]


@pytest.fixture(scope="session", params=ENGINES)
def bench_engine(request):
    return request.param


@pytest.fixture(scope="session")
def bench_reports(bench_dir):
    """The bench's report on the engine named, checked the first time it is asked for."""
    return cache(lambda engine: check_bench(bench_dir, engine=engine))


@pytest.fixture(scope="session")
def bench_report(bench_reports, bench_engine):
    return bench_reports(bench_engine)


@pytest.fixture(scope="session")
def bench_json(bench_report):
    return {entry["name"]: entry for entry in bench_report.to_json_dict()["fasteners"]}
