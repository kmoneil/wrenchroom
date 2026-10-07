"""The release: what scripts/release.py refuses, and how release.yml publishes.

PyPI's trusted publisher for wrenchroom names this repository, the workflow file
release.yml and the environment `pypi`; renaming either breaks publishing until
PyPI is changed to match, so both are pinned here. So is what keeps the publish
safe: it runs only for a `v*` tag, the token PyPI trusts exists only in the job
that uploads, and every action is pinned to a commit.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

import wrenchroom

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
RELEASE_YML = WORKFLOWS / "release.yml"


def _script(name):
    """One of scripts/, loaded as a module."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # a dataclass in it looks its module up by name
    spec.loader.exec_module(module)
    return module


release = _script("release")


# ---------------------------------------------------------------------------
# What scripts/release.py refuses.
# ---------------------------------------------------------------------------


def test_the_version_is_the_one_init_declares():
    text = (ROOT / "src" / "wrenchroom" / "__init__.py").read_text()
    assert release.package_version(text) == wrenchroom.__version__
    with pytest.raises(release.ReleaseError, match="no __version__"):
        release.package_version("version = '1'\n")


@pytest.mark.parametrize("version", ["0.1.0", "1.2.3", "0.2.0rc1", "0.2.0b2", "1.0.0.post1"])
def test_a_tag_naming_a_release_passes(version):
    release.check_tag(f"v{version}", version)


@pytest.mark.parametrize(
    ("tag", "version", "says"),
    [
        ("v0.1.1", "0.1.0", "does not name"),  # the wrong commit tagged
        ("0.1.0", "0.1.0", "does not name"),  # no v
        ("v0.1.0.dev0", "0.1.0.dev0", "not a release"),
        ("v0.1.0+local", "0.1.0+local", "not a release"),
    ],
)
def test_a_tag_that_isn_t_the_release_is_refused(tag, version, says):
    with pytest.raises(release.ReleaseError, match=says):
        release.check_tag(tag, version)


@pytest.mark.parametrize(
    "name",
    [
        "wrenchroom-0.1.0/_plans/SPEC.md",
        "wrenchroom-0.1.0/_tmp/scratch.py",
        "wrenchroom-0.1.0/_reviews/notes.md",
        "wrenchroom-0.1.0/_reports/r.json",
        "wrenchroom-0.1.0/examples/bracket.step",
        "wrenchroom-0.1.0/tests/model.STP",
        "wrenchroom-0.1.0/examples/report.html",
        "wrenchroom-0.1.0/examples/report.json",
    ],
)
def test_the_sdist_refuses_private_and_generated_files(name):
    with pytest.raises(release.ReleaseError, match="must not"):
        release.check_sdist(["wrenchroom-0.1.0/README.md", name])


def test_the_sdist_keeps_what_the_repository_tracks():
    release.check_sdist(
        [
            "wrenchroom-0.1.0/src/wrenchroom/view/template.html",
            "wrenchroom-0.1.0/src/wrenchroom/view/vendor/three.json",
            "wrenchroom-0.1.0/tests/golden/bench.snapshot.json",
            "wrenchroom-0.1.0/examples/bracket.py",
            "wrenchroom-0.1.0/.github/rulesets/main.json",
            "wrenchroom-0.1.0/docs/reference.md",
        ]
    )


def test_the_wheel_must_hold_its_licences_and_the_view_s_bundle():
    whole = [
        "wrenchroom/__init__.py",
        "wrenchroom/view/vendor/three.min.js",
        "wrenchroom-0.1.0.dist-info/licenses/LICENSE",
        "wrenchroom-0.1.0.dist-info/licenses/src/wrenchroom/view/vendor/three.LICENSE",
    ]
    release.check_wheel(whole)
    for missing in whole:
        with pytest.raises(release.ReleaseError, match="lacks"):
            release.check_wheel([name for name in whole if name != missing])


def test_the_bundle_the_wheel_must_hold_is_the_one_the_view_embeds():
    vendor = ROOT / "src" / "wrenchroom" / "view" / "vendor"
    for want in release.IN_WHEEL:
        if want.startswith("wrenchroom/"):
            assert (ROOT / "src" / want).exists(), want
    assert (vendor / "three.LICENSE").exists()


def test_the_example_summary_is_the_readme_s():
    readme = (ROOT / "README.md").read_text()
    counts = release.EXAMPLE_SUMMARY
    line = (
        f"{counts['fasteners']} fasteners: {counts['turns']} turn, {counts['held']} held, "
        f"{counts['blocked']} blocked, {counts['stuck']} stuck, "
        f"{counts['not_covered']} not covered"
    )
    assert f"$ wrenchroom check examples/bracket.step\n{line}\n" in readme


# ---------------------------------------------------------------------------
# How release.yml publishes.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(RELEASE_YML.read_text())


def test_it_runs_for_a_version_tag_and_by_hand(workflow):
    on = workflow[True]  # YAML 1.1 reads the key "on" as true
    assert on == {"push": {"tags": ["v*"]}, "workflow_dispatch": None}


def test_nothing_is_granted_but_what_each_job_needs(workflow):
    assert workflow["permissions"] == {}
    jobs = workflow["jobs"]
    assert jobs["build"]["permissions"] == {"contents": "read"}
    assert jobs["publish"]["permissions"] == {"id-token": "write"}
    assert jobs["github-release"]["permissions"] == {"contents": "write"}
    # The token PyPI trusts exists in one job only.
    minting = [name for name, job in jobs.items() if "id-token" in job.get("permissions", {})]
    assert minting == ["publish"]


def test_it_publishes_as_pypi_s_trusted_publisher_expects(workflow):
    # PyPI's pending publisher: repository kmoneil/wrenchroom, workflow release.yml,
    # environment pypi.
    assert RELEASE_YML.name == "release.yml"
    publish = workflow["jobs"]["publish"]
    assert publish["environment"]["name"] == "pypi"
    assert publish["if"] == "github.ref_type == 'tag'"
    assert publish["needs"] == "build"
    uses = [step["uses"].split("@")[0] for step in publish["steps"]]
    assert uses == ["actions/download-artifact", "pypa/gh-action-pypi-publish"]
    # No token: trusted publishing alone.
    assert "with" not in publish["steps"][-1]


def test_it_builds_and_proves_before_anything_is_published(workflow):
    build = workflow["jobs"]["build"]
    runs = [step.get("run") for step in build["steps"] if "run" in step]
    assert "uv run --frozen python scripts/lanes.py release-check" in runs
    assert workflow["jobs"]["github-release"]["needs"] == "publish"
    assert workflow["jobs"]["github-release"]["if"] == "github.ref_type == 'tag'"


def test_the_lane_it_runs_exists():
    (lane,) = [lane for lane in _script("lanes").LANES if lane.name == "release-check"]
    assert lane.steps == (("python", "scripts/release.py"),)


#: A value somebody other than the workflow chooses (a tag or branch name, an event's
#: text, a dispatch input), spliced into a shell script.
SPLICED = re.compile(r"\$\{\{\s*(github|inputs)\.")


def test_no_step_splices_somebody_s_text_into_its_shell():
    # ${{ }} inside run: is pasted into the script before the shell sees it, so a tag
    # named `v1;curl ...` would run; such values go in through env instead. The
    # workflow's own matrix is its own text, and may.
    runs = 0
    for path in WORKFLOWS.glob("*.yml"):
        flow = yaml.safe_load(path.read_text())
        for job in flow["jobs"].values():
            for step in job.get("steps", []):
                runs += "run" in step
                assert not SPLICED.search(step.get("run", "")), (path.name, step["run"])
    assert runs > 10
    assert SPLICED.search("echo ${{ github.ref_name }}")
    assert not SPLICED.search("uv python install ${{ matrix.python }}")


#: A third-party action pinned to a commit, the tag in a trailing comment.
PINNED = re.compile(r"^\s*-?\s*uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+(\.\d+)*$")


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit(path):
    lines = [line for line in path.read_text().splitlines() if "uses:" in line]
    assert lines
    for line in lines:
        assert PINNED.match(line), f"{path.name}: {line.strip()}"
