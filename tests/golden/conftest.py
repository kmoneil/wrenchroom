"""The bench is built once per session and checked once per engine; tests read that.

`bench_report` and `bench_json` are parametrised over the engines, so every
truth, count and snapshot test runs on both: the mesh engine is the default,
and the exact engine is the referee it must agree with.
"""

import pytest
from bench import check_bench, sidecar_and_truth, write

from wrenchroom.engine import ENGINES


@pytest.fixture(scope="session")
def bench_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("bench")
    write(directory)
    return directory


@pytest.fixture(scope="session")
def bench_truth():
    return sidecar_and_truth()[1]


@pytest.fixture(scope="session", params=ENGINES)
def bench_engine(request):
    return request.param


@pytest.fixture(scope="session")
def bench_report(bench_dir, bench_engine):
    return check_bench(bench_dir, engine=bench_engine)


@pytest.fixture(scope="session")
def bench_json(bench_report):
    return {entry["name"]: entry for entry in bench_report.to_json_dict()["fasteners"]}
