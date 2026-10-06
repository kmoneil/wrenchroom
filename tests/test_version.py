"""The version is single-sourced: the package and the distribution must agree."""

from importlib.metadata import version

import wrenchroom


def test_version_matches_distribution():
    assert wrenchroom.__version__ == version("wrenchroom")
