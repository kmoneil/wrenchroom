"""Fixtures for every test module: the collision engines, each in turn.

A test that takes `engine` (or `scene_of`) runs once per engine. Whatever the
mesh engine answers in these hand-computed cases, the exact engine must answer
too: the analytic fixtures keep their margins well clear of the 0.2 mm the mesh
can be off by, so a split verdict here is a bug, not a tolerance.
"""

import pytest

from wrenchroom.assembly import Part
from wrenchroom.engine import ENGINES, make_engine

#: pytest's own harness for running a project's tests, for the plugin's tests.
pytest_plugins = ["pytester"]


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
