"""The README's examples run as written, and the docs' snippets and links hold.

Each console block in the README that shows output is run here and compared line
for line: ``wrenchroom ...`` through the CLI, ``python examples/bracket.py`` as a
reader runs it. Each block starts from the bracket as examples/bracket.py writes it,
unfixed. The JSON excerpt is the rear screw's entry; the Python example prints what
is shown under it; every sidecar snippet in the README and the reference parses;
every ``wrenchroom`` flag the docs name exists; the pytest ini names are the
plugin's; and every relative link, anchors included, lands.
"""

import contextlib
import io
import json
import os
import re
import runpy
import shlex
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

import wrenchroom as wr
from wrenchroom import pytest_plugin
from wrenchroom.cli import main
from wrenchroom.config import Config

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
REFERENCE = ROOT / "docs" / "reference.md"
DOCS = (README, REFERENCE)
RELEASING = ROOT / "docs" / "releasing.md"
EXAMPLE = ROOT / "examples" / "bracket.py"

#: A fenced block, indented or not: its indent, its language, its body.
FENCE = re.compile(r"^( *)```(\w*)\n(.*?)^\1```", re.MULTILINE | re.DOTALL)


def blocks(path, language):
    """Every fenced block of one language in a document, dedented."""
    found = []
    for match in FENCE.finditer(path.read_text()):
        if match.group(2) == language:
            indent = len(match.group(1))
            found.append("\n".join(line[indent:] for line in match.group(3).splitlines()))
    return found


def steps(block):
    """A console block's commands, each with the output shown under it."""
    runs = []
    for line in block.splitlines():
        if line.startswith("$ "):
            runs.append((line[2:], []))
        elif runs:
            runs[-1][1].append(line)
    return runs


def shown_runs():
    """The README's console blocks that show output: the ones a reader can compare."""
    return [
        pytest.param(block, id=block.splitlines()[0][2:])
        for block in blocks(README, "console")
        if any(output for _, output in steps(block))
    ]


@pytest.fixture(scope="module")
def bracket(tmp_path_factory):
    """examples/bracket.step as the example writes it, unfixed, built once."""
    directory = tmp_path_factory.mktemp("bracket")
    run_example(directory, [])
    return directory / "examples" / "bracket.step"


def run_example(directory, args):
    """``python examples/bracket.py ARGS``, run in ``directory``: what it prints."""
    (directory / "examples").mkdir(exist_ok=True)
    script = directory / "examples" / "bracket.py"
    shutil.copy(EXAMPLE, script)
    out = io.StringIO()
    argv, cwd = sys.argv, Path.cwd()
    try:
        sys.argv = [str(script), *args]
        os.chdir(directory)
        with contextlib.redirect_stdout(out):
            runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = argv
        os.chdir(cwd)
    return out.getvalue().splitlines()


def run_wrenchroom(directory, args):
    """``wrenchroom ARGS``, run in ``directory``: what a terminal shows."""
    cwd = Path.cwd()
    try:
        os.chdir(directory)
        result = CliRunner().invoke(main, args)
    finally:
        os.chdir(cwd)
    if result.exception and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result.output.splitlines()


@pytest.mark.parametrize("block", shown_runs())
def test_each_console_block_prints_what_it_shows(block, bracket, tmp_path):
    (tmp_path / "examples").mkdir()
    shutil.copy(bracket, tmp_path / "examples" / "bracket.step")
    for command, shown in steps(block):
        argv = shlex.split(command)
        if argv[0] == "wrenchroom":
            printed = run_wrenchroom(tmp_path, argv[1:])
        elif argv[:2] == ["python", "examples/bracket.py"]:
            printed = run_example(tmp_path, argv[2:])
        else:
            pytest.fail(f"the README shows output for {command!r}, which this test can't run")
        assert printed == shown, command


def test_every_shown_run_is_found():
    # Vacuity: the intro's check, the worked example's two runs, two explains and
    # the fix, at least.
    commands = [command for block in blocks(README, "console") for command, _ in steps(block)]
    shown = [param.values[0] for param in shown_runs()]
    assert len(shown) >= 5
    assert "python examples/bracket.py --fixed" in commands


def test_the_example_fails_then_passes_as_the_readme_says(bracket, tmp_path):
    # "The exit code is 1, because a fastener failed." ... "the exit code is 0".
    shutil.copytree(bracket.parent, tmp_path / "examples")
    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        assert CliRunner().invoke(main, ["check", "examples/bracket.step"]).exit_code == 1
        run_example(tmp_path, ["--fixed"])
        assert CliRunner().invoke(main, ["check", "examples/bracket.step"]).exit_code == 0
    finally:
        os.chdir(cwd)


def test_the_json_excerpt_is_the_rear_screw_s_entry(bracket):
    (excerpt,) = blocks(README, "json")
    report = wr.check(wr.Assembly.from_step(bracket), kit="metric-home")
    entries = {entry["name"]: entry for entry in report.to_json_dict()["fasteners"]}
    assert json.loads(excerpt) == entries["rear_screw"]


def test_the_python_example_prints_what_is_shown(bracket, tmp_path):
    (code,) = [block for block in blocks(README, "python") if "import wrenchroom as wr" in block]
    text = README.read_text()
    after = text[text.index(code) + len(code) :]
    after = after[after.index("```") + 3 :]  # past the code's own closing fence
    shown = FENCE.search(after)
    assert shown is not None
    assert shown.group(2) == "text"
    (tmp_path / "examples").mkdir()
    shutil.copy(bracket, tmp_path / "examples" / "bracket.step")
    out = io.StringIO()
    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        with contextlib.redirect_stdout(out):
            exec(compile(code, "README.md", "exec"), {})  # noqa: S102  (the README's own code)
    finally:
        os.chdir(cwd)
    assert out.getvalue().splitlines() == shown.group(3).splitlines()


def sidecars():
    """Every sidecar snippet: the README's start ``# wrenchroom.yaml``; the reference's
    YAML is all sidecar."""
    found = [block for block in blocks(README, "yaml") if block.startswith("# wrenchroom.yaml")]
    return found + blocks(REFERENCE, "yaml")


@pytest.mark.parametrize("snippet", sidecars())
def test_each_sidecar_snippet_is_a_sidecar_wrenchroom_reads(snippet):
    Config.from_dict(yaml.safe_load(snippet))


def test_the_sidecar_snippets_are_found():
    assert len(sidecars()) >= 3  # the README's full one and its tools; the reference's
    (full,) = [s for s in sidecars() if "states:" in s]
    config = Config.from_dict(yaml.safe_load(full))
    assert {state.name for state in config.states} == {"lid-off", "lever-up"}
    assert config.try_states == ("lid-off",)


def test_the_ci_workflow_is_yaml_and_its_commands_take_their_flags():
    (workflow,) = [b for b in blocks(README, "yaml") if b.startswith("# .github/workflows/")]
    steps_ = yaml.safe_load(workflow)["jobs"]["wrenchroom"]["steps"]
    runs = [step["run"] for step in steps_ if "run" in step]
    assert any(run.startswith("wrenchroom check") for run in runs)


#: A ``wrenchroom COMMAND`` as the docs write it, up to the end of its code.
COMMAND = re.compile(r"wrenchroom (check|explain|detect|tools)\b([^`\n]*)")


#: Flags the docs name that belong to the docs' own scripts, not to wrenchroom.
NOT_WRENCHROOM = {"--fixed": "examples/bracket.py", "--out": "scripts/golden.py"}


def test_every_flag_the_docs_name_is_one_the_command_takes():
    named = []
    for path in DOCS:
        for command, rest in COMMAND.findall(path.read_text()):
            takes = {opt for param in main.commands[command].params for opt in param.opts}
            for flag in re.findall(r"(?<!\S)--[a-z-]+", rest):
                named.append(flag)
                assert flag in takes, f"{path.name}: wrenchroom {command} {flag}"
    assert len(named) >= 5


def test_every_flag_the_docs_mention_is_wrenchroom_s_or_a_script_s():
    every = {opt for command in main.commands.values() for p in command.params for opt in p.opts}
    for path in DOCS:
        mentioned = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", path.read_text()))
        assert mentioned, path.name
        unknown = mentioned - every - NOT_WRENCHROOM.keys()
        assert not unknown, f"{path.name}: {sorted(unknown)}"
    for flag, script in NOT_WRENCHROOM.items():
        assert flag in (ROOT / script).read_text(), script


def test_the_pytest_settings_shown_are_the_plugin_s():
    class Recorder:
        def __init__(self):
            self.names = set()

        def addini(self, name, *args, **kwargs):
            self.names.add(name)

    recorder = Recorder()
    pytest_plugin.pytest_addoption(recorder)
    (ini,) = blocks(README, "ini")
    shown = set(re.findall(r"\bwrenchroom_\w+", ini))
    assert shown == recorder.names


def _slug(heading):
    """A heading's anchor, as GitHub makes it."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _anchors(path):
    return {_slug(m.group(1)) for m in re.finditer(r"^#+ (.+)$", path.read_text(), re.MULTILINE)}


#: This repository's own files as the README links them: on GitHub, at main.
REPO_URL = re.compile(
    r"https://(?:github\.com/kmoneil/wrenchroom/blob|raw\.githubusercontent\.com/"
    r"kmoneil/wrenchroom)/main/([^#]+)(?:#(.+))?"
)


def _links(doc):
    return re.findall(r"\]\(([^)\s]+)\)", doc.read_text())


@pytest.mark.parametrize("doc", [*DOCS, RELEASING], ids=lambda path: path.name)
def test_every_link_into_the_repository_lands(doc):
    checked = 0
    for link in _links(doc):
        if found := REPO_URL.fullmatch(link):
            path, anchor = ROOT / found.group(1), found.group(2)
        elif link.startswith(("http://", "https://")):
            continue
        else:
            target, _, anchor = link.partition("#")
            path = (doc.parent / target).resolve() if target else doc
        assert path.exists(), link
        if anchor:
            assert anchor in _anchors(path), link
        checked += 1
    assert checked


def test_the_readme_links_nothing_pypi_cannot_follow():
    # The README is the PyPI page too, where a relative link goes nowhere: its own
    # files are linked on GitHub, which the test above holds to the checkout.
    relative = [link for link in _links(README) if not link.startswith(("https://", "#"))]
    assert not relative
    assert sum(bool(REPO_URL.fullmatch(link)) for link in _links(README)) >= 5
