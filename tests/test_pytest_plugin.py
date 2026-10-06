"""The pytest plugin, run as a user runs it: a project with a pytest.ini, a model
and a test that asks for `wrenchroom_report`, under pytest's own `pytester`.

A design change that buries a bolt must fail that project's test run, saying why
in the output; a clean design must pass; a misconfiguration must say what to set.
"""

import json
import subprocess
import sys
from importlib.metadata import entry_points

import pytest
from build123d import Compound, export_step

from fixture_models import gland_on_wall, screw_facing_wall
from wrenchroom.checker import check
from wrenchroom.config import Config

SIDECAR = {"fasteners": [{"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}]}

TEST_FILE = """
def test_every_fastener_reachable(wrenchroom_report):
    wrenchroom_report.assert_all_pass()
"""


def _export(assembly, path):
    shapes = []
    for part in assembly:
        part.shape.label = part.name
        shapes.append(part.shape)
    path.parent.mkdir(parents=True, exist_ok=True)
    export_step(Compound(children=shapes), str(path))


@pytest.fixture
def project(pytester):
    """A project with its model in cad/; returns a function writing pytest.ini."""
    cad = pytester.path / "cad"

    def make(assembly, ini, sidecar=SIDECAR):
        _export(assembly, cad / "model.step")
        if sidecar is not None:
            (cad / "wrenchroom.yaml").write_text(json.dumps(sidecar))  # JSON is YAML
        pytester.makeini("[pytest]\n" + "\n".join(f"{k} = {v}" for k, v in ini.items()))
        pytester.makepyfile(test_design=TEST_FILE)
        return pytester

    return make


def test_the_plugin_is_registered_with_pytest():
    plugins = {e.name: e.value for e in entry_points(group="pytest11")}
    assert plugins.get("wrenchroom") == "wrenchroom.pytest_plugin"


def test_loading_the_plugin_imports_nothing_heavy():
    code = (
        "import sys, wrenchroom.pytest_plugin; "
        "print(sorted(m for m in ('build123d', 'OCP', 'manifold3d', 'numpy') if m in sys.modules))"
    )
    done = subprocess.run(  # noqa: S603  (this interpreter, a fixed script)
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "[]"


def test_a_clean_design_passes(project):
    run = project(screw_facing_wall(40.0), {"wrenchroom_model": "cad/model.step"})
    result = run.runpytest()
    result.assert_outcomes(passed=1)


def test_a_buried_bolt_fails_the_run_saying_why(project):
    run = project(screw_facing_wall(15.0), {"wrenchroom_model": "cad/model.step"})
    result = run.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        [
            "*AssertionError: 1 fasteners: 0 turn, 0 held, 1 blocked, 0 stuck, 0 not covered",
            "*FAIL bolt  hex-key-5  blocked  wall*",
        ]
    )


def test_the_message_is_what_check_prints(tmp_path):
    report = check(screw_facing_wall(15.0), Config.from_dict(SIDECAR), engine="exact")
    with pytest.raises(AssertionError) as raised:
        report.assert_all_pass()
    lines = report.terminal_lines()
    assert str(raised.value).splitlines() == [lines[0], *(x for x in lines if x.startswith("FAIL"))]
    clean = check(screw_facing_wall(40.0), Config.from_dict(SIDECAR), engine="exact")
    clean.assert_all_pass()  # returns quietly


def test_a_rule_that_matches_nothing_fails_too(project):
    sidecar = {"fasteners": [*SIDECAR["fasteners"], {"parts": "renamed_*", "kind": "screw"}]}
    run = project(screw_facing_wall(40.0), {"wrenchroom_model": "cad/model.step"}, sidecar)
    result = run.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*WARN rule matched nothing: 'renamed_*' (renamed part?)*"])


def test_the_kit_comes_from_the_ini(project):
    rule = {"fasteners": [{"parts": "gland", "kind": "nut", "size": "M16", "socket": False}]}
    home = project(gland_on_wall(), {"wrenchroom_model": "cad/model.step"}, rule)
    result = home.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*needs spanner-24, which kit metric-home does not hold*"])
    full = project(
        gland_on_wall(), {"wrenchroom_model": "cad/model.step", "wrenchroom_kit": "full"}, rule
    )
    full.runpytest().assert_outcomes(passed=1)


def test_the_state_and_engine_come_from_the_ini(project):
    lidded = {
        **SIDECAR,
        "states": {"lid-off": {"remove": ["wall"]}},
    }
    ini = {
        "wrenchroom_model": "cad/model.step",
        "wrenchroom_state": "lid-off",
        "wrenchroom_exact": "true",
    }
    run = project(screw_facing_wall(15.0), ini, lidded)
    run.makeconftest(
        """
import pytest

@pytest.fixture(autouse=True)
def _show(wrenchroom_report):
    print("ENGINE", wrenchroom_report.engine, "STATE", wrenchroom_report.default_state)
"""
    )
    result = run.runpytest("-s")
    result.assert_outcomes(passed=1)  # the wall is off in lid-off
    result.stdout.fnmatch_lines(["*ENGINE exact STATE lid-off*"])


def test_an_explicit_config_path_is_used(project):
    run = project(screw_facing_wall(40.0), {}, sidecar=None)
    (run.path / "elsewhere.yaml").write_text(json.dumps(SIDECAR))
    run.makeini("[pytest]\nwrenchroom_model = cad/model.step\nwrenchroom_config = elsewhere.yaml\n")
    run.makeconftest(
        """
import pytest

@pytest.fixture(autouse=True)
def _show(wrenchroom_report):
    print("RULES FROM", " ".join(r.fastener.source for r in wrenchroom_report.results))
"""
    )
    result = run.runpytest("-s")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*RULES FROM sidecar"])


def test_paths_are_relative_to_the_ini_file_not_the_working_directory(project, monkeypatch):
    run = project(screw_facing_wall(15.0), {"wrenchroom_model": "cad/model.step"})
    monkeypatch.chdir(run.mkdir("somewhere_else"))
    result = run.runpytest(str(run.path))
    result.assert_outcomes(failed=1)  # found the model (and so failed on the bolt)
    result.stdout.fnmatch_lines(["*FAIL bolt  hex-key-5  blocked  wall*"])


def test_no_model_configured_says_what_to_set(project):
    run = project(screw_facing_wall(40.0), {})
    result = run.runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*needs wrenchroom_model set in the pytest configuration*"])


def test_a_missing_model_or_config_says_where_it_looked(project):
    run = project(screw_facing_wall(40.0), {"wrenchroom_model": "cad/nope.step"})
    result = run.runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        ["*wrenchroom: no file at *nope.step (wrenchroom_model is relative*"]
    )
    run.makeini("[pytest]\nwrenchroom_model = cad/model.step\nwrenchroom_config = gone.yaml\n")
    result = run.runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*no file at *gone.yaml (wrenchroom_config is relative*"])


def test_a_bad_kit_or_sidecar_is_reported_as_such(project):
    run = project(
        screw_facing_wall(40.0), {"wrenchroom_model": "cad/model.step", "wrenchroom_kit": "mars"}
    )
    result = run.runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*wrenchroom: unknown kit 'mars'*"])


def test_the_model_is_checked_once_per_session(project):
    run = project(screw_facing_wall(40.0), {"wrenchroom_model": "cad/model.step"})
    run.makepyfile(
        test_more="""
def test_again(wrenchroom_report):
    wrenchroom_report.assert_all_pass()

def test_and_again(wrenchroom_report):
    assert wrenchroom_report.summary["fasteners"] == 1
"""
    )
    run.makeconftest(
        """
import wrenchroom.checker

calls = []
original = wrenchroom.checker.check

def counting(*args, **kwargs):
    calls.append(1)
    return original(*args, **kwargs)

wrenchroom.checker.check = counting

def pytest_sessionfinish(session):
    print("CHECKED", len(calls), "TIMES")
"""
    )
    result = run.runpytest("-s")
    result.assert_outcomes(passed=3)
    result.stdout.fnmatch_lines(["*CHECKED 1 TIMES*"])


def test_the_plugin_can_be_turned_off(project):
    run = project(screw_facing_wall(40.0), {"wrenchroom_model": "cad/model.step"})
    result = run.runpytest("-p", "no:wrenchroom")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*fixture 'wrenchroom_report' not found*"])
