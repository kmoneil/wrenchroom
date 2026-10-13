"""Fixtures for every test module: the collision engines, each in turn.

A test that takes `engine` (or `scene_of`) runs once per engine. Whatever the
mesh engine answers in these hand-computed cases, the exact engine must answer
too: the analytic fixtures keep their margins well clear of the 0.2 mm the mesh
can be off by, so a split verdict here is a bug, not a tolerance.
"""

import os

import pytest
from OCP.OSD import OSD_ThreadPool

from wrenchroom.assembly import Part
from wrenchroom.engine import ENGINES, make_engine

#: pytest's own harness for running a project's tests, for the plugin's tests.
pytest_plugins = ["pytester"]


def pytest_configure():
    """Under the lanes' ``-n``, OCCT's thread pool is one thread to a worker.

    The exact engine asks OCCT to run each boolean on every core. In one process
    that buys a tenth of the time for half as much CPU again (the bench's exact
    check on 18 cores: 13.1 s for 14.7, and 26.5 CPU-seconds for 17.1). Where every
    core has a worker already it buys nothing, and costs the same. A boolean still
    takes its parallel road, with one thread to walk it. A run in one process is
    left alone: that is how the perf lane runs, and everyone who uses the tool.
    tests/test_suite_threads.py holds both halves.
    """
    if os.environ.get("PYTEST_XDIST_WORKER"):
        OSD_ThreadPool.DefaultPool_s(1)  # takes effect on the pool's first use only


@pytest.fixture(params=ENGINES)
def engine(request):
    """Each engine's name in turn, for check(..., engine=engine)."""
    return request.param


@pytest.fixture
def scene_of(engine):
    """Build a scene from name=shape keywords, on the engine under test."""

    def make(**shapes):
        return make_engine(engine).scene(Part(name, shape) for name, shape in shapes.items())

    return make
