"""The pytest plugin, run as a user runs it: a project with a pytest.ini, a model
and a test that asks for `wrenchroom_report`, under pytest's own `pytester`.

A design change that buries a bolt must fail that project's test run, saying why
in the output; a clean design must pass; a misconfiguration must say what to set.
"""

import json
import re
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

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
    result.stdout.fnmatch_lines(["*or the wrenchroom_assembly fixture overridden in conftest.py*"])


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


# ---------------------------------------------------------------------------
# A model the project builds, handed over with no STEP file (issue #212).
# ---------------------------------------------------------------------------

#: A conftest that gives the model: the screw under its wall, the gap filled in.
GIVEN = """
import pytest
from fixture_models import screw_facing_wall

BUILT = []

@pytest.fixture(scope="session")
def wrenchroom_assembly():
    BUILT.append(1)
    return screw_facing_wall({gap})

def pytest_sessionfinish(session):
    print("BUILT", len(BUILT), "TIMES")
"""

#: A test that shows what the report is, for the test here to read back.
SHOWN = """
import json

def test_show(wrenchroom_report):
    print("REPORT", json.dumps(wrenchroom_report.to_json_dict(), sort_keys=True))
    print("STATES", [result.state for result in wrenchroom_report.results])
"""

RENAMED = {"fasteners": [*SIDECAR["fasteners"], {"parts": "renamed_*", "kind": "screw"}]}
OPENED = {
    **SIDECAR,
    "states": {"open": {"model": "open.step"}},
    "checks": {"try_states": ["open"]},
}


@pytest.fixture
def built(pytester):
    """A project that builds its model: no STEP file, its sidecar beside pytest.ini."""

    def make(gap, ini=None, sidecar=SIDECAR, where="wrenchroom.yaml", conftest=GIVEN, more=""):
        if sidecar is not None:
            path = pytester.path / where
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(sidecar))
        pytester.makeini("[pytest]\n" + "\n".join(f"{k} = {v}" for k, v in (ini or {}).items()))
        pytester.makeconftest(conftest.replace("{gap}", str(gap)) + more)
        pytester.makepyfile(test_design=TEST_FILE)
        return pytester

    return make


def _shown(result, word):
    """What a test printed after ``word``; pytest's own progress may share the line."""
    (line,) = [line for line in result.stdout.lines if f"{word} " in line]
    return line[line.index(f"{word} ") + len(word) + 1 :]


def test_a_model_handed_over_is_checked_with_no_step_file(built):
    run = built(40.0)
    run.runpytest().assert_outcomes(passed=1)
    assert not list(run.path.rglob("*.step"))


def test_a_buried_bolt_in_a_model_handed_over_fails_the_run_saying_why(built):
    result = built(15.0).runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        [
            "*AssertionError: 1 fasteners: 0 turn, 0 held, 1 blocked, 0 stuck, 0 not covered",
            "*FAIL bolt  hex-key-5  blocked  wall*",
        ]
    )


def test_the_report_is_the_one_the_model_s_step_file_gets(built, project, pytester):
    # The same design each way, the model named alike: one report, to the letter.
    ini = {"wrenchroom_model": "cad/model.step"}
    given = built(15.0, ini, where="cad/wrenchroom.yaml")
    given.makepyfile(test_design=SHOWN)
    handed = _shown(given.runpytest("-s"), "REPORT")
    assert not list(given.path.rglob("*.step"))
    (given.path / "conftest.py").unlink()
    read = project(screw_facing_wall(15.0), ini)
    read.makepyfile(test_design=SHOWN)
    assert json.loads(_shown(read.runpytest("-s"), "REPORT")) == json.loads(handed)
    assert json.loads(handed)["model"] == "model.step"
    assert json.loads(handed)["summary"]["blocked"] == 1


@pytest.mark.parametrize(
    ("on_disk", "handed", "outcome"),
    [(15.0, 40.0, {"passed": 1}), (40.0, 15.0, {"failed": 1})],
    ids=["file-buried-given-clear", "file-clear-given-buried"],
)
def test_the_assembly_given_is_checked_whatever_file_the_model_names(
    built, on_disk, handed, outcome
):
    run = built(handed, {"wrenchroom_model": "cad/model.step"}, where="cad/wrenchroom.yaml")
    _export(screw_facing_wall(on_disk), run.path / "cad" / "model.step")
    run.runpytest().assert_outcomes(**outcome)


def test_a_file_of_the_model_s_name_is_never_read(built):
    run = built(40.0, {"wrenchroom_model": "cad/model.step"}, where="cad/wrenchroom.yaml")
    (run.path / "cad" / "model.step").write_text("no STEP file at all")
    run.runpytest().assert_outcomes(passed=1)


def test_with_no_model_named_the_sidecar_is_the_one_beside_the_ini(built):
    # The guard that it is read: its rule that matches nothing is said.
    result = built(40.0, sidecar=RENAMED).runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*WARN rule matched nothing: 'renamed_*' (renamed part?)*"])


def test_with_a_model_named_the_sidecar_is_the_one_beside_it(built):
    ini = {"wrenchroom_model": "cad/model.step"}
    result = built(40.0, ini, RENAMED, where="cad/wrenchroom.yaml").runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*WARN rule matched nothing: 'renamed_*' (renamed part?)*"])
    # And one beside the ini is not it: with none beside the model, there is no rule.
    aside = built(40.0, ini, RENAMED, where="wrenchroom.yaml")
    (aside.path / "cad" / "wrenchroom.yaml").unlink()
    aside.runpytest().assert_outcomes(passed=1)


def test_an_explicit_config_path_is_used_for_a_model_handed_over(built):
    ini = {"wrenchroom_config": "conf/side.yaml"}
    result = built(40.0, ini, RENAMED, where="conf/side.yaml").runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*WARN rule matched nothing: 'renamed_*' (renamed part?)*"])
    missing = built(40.0, {"wrenchroom_config": "gone.yaml"}).runpytest()
    missing.assert_outcomes(errors=1)
    missing.stdout.fnmatch_lines(["*no file at *gone.yaml (wrenchroom_config is relative*"])


def test_the_kit_state_and_engine_come_from_the_ini_for_a_model_handed_over(built):
    lidded = {**SIDECAR, "states": {"lid-off": {"remove": ["wall"]}}}
    ini = {"wrenchroom_state": "lid-off", "wrenchroom_exact": "true", "wrenchroom_kit": "full"}
    run = built(15.0, ini, lidded)
    run.makepyfile(test_design=SHOWN)
    result = run.runpytest("-s")
    result.assert_outcomes(passed=1)
    report = json.loads(_shown(result, "REPORT"))
    assert (report["kit"], report["engine"], report["model"]) == ("full", "exact", "")
    assert _shown(result, "STATES") == "['lid-off']"


#: The models fixture, added to GIVEN: the state's model, open, or whatever is asked.
MODELS = """

@pytest.fixture(scope="session")
def wrenchroom_models():
    return {models}
"""


def test_a_state_s_model_is_handed_over_too(built):
    # Buried as drawn, and open in the state's model: reached there, with no file.
    more = MODELS.replace("{models}", '{"open.step": screw_facing_wall(40.0)}')
    run = built(15.0, sidecar=OPENED, more=more)
    run.makepyfile(test_design=SHOWN + TEST_FILE)
    result = run.runpytest("-s")
    result.assert_outcomes(passed=2)
    assert _shown(result, "STATES") == "['open']"
    assert not list(run.path.rglob("*.step"))


def test_a_state_s_model_not_handed_over_is_looked_for_as_a_file(built):
    result = built(15.0, sidecar=OPENED).runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*wrenchroom: state 'open': its model open.step not found*"])


@pytest.mark.parametrize("handed", [False, True], ids=["model-read", "model-handed-over"])
def test_a_state_s_model_on_disk_is_found_beside_the_model_named(built, handed):
    # The sidecar in conf/ and the state's model in cad/, beside the model the ini
    # names: looked for there, the model itself read from its file or handed over.
    ini = {"wrenchroom_model": "cad/model.step", "wrenchroom_config": "conf/side.yaml"}
    run = built(15.0, ini, OPENED, where="conf/side.yaml", conftest=GIVEN if handed else "")
    _export(screw_facing_wall(40.0), run.path / "cad" / "open.step")
    if not handed:
        _export(screw_facing_wall(15.0), run.path / "cad" / "model.step")
    run.makepyfile(test_design=SHOWN)
    result = run.runpytest("-s")
    result.assert_outcomes(passed=1)
    assert _shown(result, "STATES") == "['open']"


def test_a_state_s_model_handed_over_goes_with_a_model_read_from_its_file(project):
    run = project(screw_facing_wall(15.0), {"wrenchroom_model": "cad/model.step"}, OPENED)
    run.makeconftest(
        "import pytest\nfrom fixture_models import screw_facing_wall\n"
        + MODELS.replace("{models}", '{"open.step": screw_facing_wall(40.0)}')
    )
    run.makepyfile(test_design=SHOWN)
    result = run.runpytest("-s")
    result.assert_outcomes(passed=1)
    assert _shown(result, "STATES") == "['open']"


@pytest.mark.parametrize(
    ("models", "said"),
    [
        (
            '{"shut.step": screw_facing_wall(40.0)}',
            "*wrenchroom: unknown model 'shut.step' in models*",
        ),
        (
            '{"open.step": "open.step"}',
            "*wrenchroom: models[[]'open.step'[]] must be an Assembly, got str*",
        ),
    ],
    ids=["a-name-the-sidecar-lacks", "no-assembly"],
)
def test_a_model_handed_over_wrongly_is_refused_as_check_refuses_it(built, models, said):
    result = built(40.0, sidecar=OPENED, more=MODELS.replace("{models}", models)).runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines([said])


@pytest.mark.parametrize(
    ("given", "kind"),
    [("[1, 2]", "list"), ("'cad/model.step'", "str"), ("screw_facing_wall", "function")],
)
def test_something_that_is_no_assembly_is_refused_saying_what_makes_one(built, given, kind):
    conftest = GIVEN.replace("screw_facing_wall({gap})", given)
    result = built(40.0, conftest=conftest).runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        [
            f"*wrenchroom: the wrenchroom_assembly fixture must give an Assembly, got {kind} "
            "(Assembly.from_shapes makes one of shapes)*"
        ]
    )


def test_the_model_is_built_once_per_session(built):
    run = built(40.0)
    run.makepyfile(
        test_more="""
def test_again(wrenchroom_report):
    wrenchroom_report.assert_all_pass()

def test_and_again(wrenchroom_report):
    assert wrenchroom_report.summary["fasteners"] == 1
"""
    )
    result = run.runpytest("-s")
    result.assert_outcomes(passed=3)
    result.stdout.fnmatch_lines(["*BUILT 1 TIMES*"])


def test_a_project_that_never_asks_for_the_report_never_builds_its_model(built):
    run = built(40.0)
    run.makepyfile(test_design="def test_other():\n    assert True\n")
    result = run.runpytest("-s")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*BUILT 0 TIMES*"])


#: The project's own build script, as the README's conftest imports it: a screw, and
#: a lever 15 over its head as drawn, swung clear when it is up.
ROBOT = """
from build123d import Box, Cylinder, Pos


def parts(lever):
    bolt = Pos(0, 0, 10) * Cylinder(3, 20) + Pos(0, 0, 23) * Cylinder(5.5, 6)
    arm = Pos(20 * lever, 0, 46) * Box(60, 60, 10)
    return [("bolt", bolt), ("lever", arm)]
"""


def test_the_conftest_the_readme_shows_hands_a_model_and_its_state_s_over(pytester):
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    (conftest,) = [
        block
        for block in re.findall(r"```python\n(.*?)```", readme, re.DOTALL)
        if "def wrenchroom_assembly" in block
    ]
    assert "def wrenchroom_models" in conftest
    sidecar = {
        **SIDECAR,
        "states": {"lever-up": {"model": "lever-up.step"}},
        "checks": {"try_states": ["lever-up"]},
    }
    (pytester.path / "wrenchroom.yaml").write_text(json.dumps(sidecar))
    pytester.makeini("[pytest]\n")
    pytester.makepyfile(robot=ROBOT, test_design=SHOWN + TEST_FILE)
    pytester.makeconftest(conftest)
    pytester.syspathinsert()
    result = pytester.runpytest("-s")
    result.assert_outcomes(passed=2)
    assert _shown(result, "STATES") == "['lever-up']"
