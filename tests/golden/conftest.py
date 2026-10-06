"""The bench is built and checked once per session; every test reads from that."""

import pytest
from bench import check_bench, sidecar_and_truth, write


@pytest.fixture(scope="session")
def bench_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("bench")
    write(directory)
    return directory


@pytest.fixture(scope="session")
def bench_truth():
    return sidecar_and_truth()[1]


@pytest.fixture(scope="session")
def bench_report(bench_dir):
    return check_bench(bench_dir)


@pytest.fixture(scope="session")
def bench_json(bench_report):
    return {entry["name"]: entry for entry in bench_report.to_json_dict()["fasteners"]}
