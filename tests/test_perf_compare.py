"""CI's speed check: scripts/perf_compare.py, and the perf job that runs it (issue #207).

The perf lane's budget is for a laptop; a hosted runner is two to four times slower
and varies by as much again, so CI times a change against its base by turns on the
runner the job got, and fails when the change takes half as long again a fastener.
Here each tree is a stand-in checkout: its ``.venv`` Python prints the perf script's
rows, the next total each run, so no bench is built or timed.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"


def _script(name):
    """One of scripts/, loaded as a module."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # a dataclass in it looks its module up by name
    spec.loader.exec_module(module)
    return module


compare = _script("perf_compare")

#: A stand-in for a checkout's Python: run as ``python scripts/perf.py --budget 0`` in
#: the checkout, it prints the rows perf.py prints, with the next of its plan's totals.
STAND_IN = """
import json, os, sys
from pathlib import Path

plan = json.loads(Path("plan.json").read_text())
runs = Path("runs")
done = len(runs.read_text().splitlines()) if runs.exists() else 0
with runs.open("a") as said:
    said.write(" ".join(sys.argv[1:]) + "\\n")
with open(os.environ["TURNS"], "a") as turns:
    turns.write(plan["name"] + "\\n")
if plan["rows"]:
    print(f"model            {plan['fasteners']} fasteners, 1434 parts (3 copies)")
    print(f"read + check     {plan['totals'][done]:.2f} s, budget 0 s: report only")
print("its summary: " + ("on" if "GITHUB_STEP_SUMMARY" in os.environ else "off"))
sys.exit(plan["code"])
"""


def checkout(root, name, totals, fasteners=549, code=0, rows=True):
    """A stand-in checkout at ``root`` whose perf runs take ``totals`` in turn."""
    (root / ".venv" / "bin").mkdir(parents=True)
    plan = {"name": name, "totals": totals, "fasteners": fasteners, "code": code, "rows": rows}
    (root / "plan.json").write_text(json.dumps(plan))
    python = root / ".venv" / "bin" / "python"
    python.write_text(f"#!{sys.executable}\n{STAND_IN}")
    python.chmod(0o755)
    return root


@pytest.fixture
def trees(tmp_path, monkeypatch):
    """Make the base and this tree: ``trees(base_plan, this_plan)``; the turns they
    took are read back with ``turns()``."""
    log = tmp_path / "turns"
    monkeypatch.setenv("TURNS", str(log))
    monkeypatch.delenv("WRENCHROOM_PERF_BASE", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    def make(base, this):
        base_root = checkout(tmp_path / "base", "base", **base)
        monkeypatch.setattr(compare, "REPO_ROOT", checkout(tmp_path / "this", "this", **this))
        return base_root

    make.turns = lambda: log.read_text().split()
    make.root = tmp_path
    return make


def run(base_root, *more):
    return compare.main(["--base", str(base_root), *more])


# ---------------------------------------------------------------------------
# What fails, and what doesn't.
# ---------------------------------------------------------------------------


def test_a_tree_as_fast_as_its_base_passes(trees, capsys):
    base = trees({"totals": [47.75, 46.10]}, {"totals": [46.80, 48.20]})
    assert run(base) == 0
    out = capsys.readouterr().out
    assert "this tree takes 1.02 times as long a fastener as its base: within 1.5" in out
    assert "fastest    84.0 ms a fastener" in out  # 46.10 s over 549


def test_a_tree_half_as_slow_again_fails(trees, capsys):
    base = trees({"totals": [30.0, 30.0]}, {"totals": [45.3, 46.0]})
    assert run(base) == 1
    assert "takes 1.51 times as long a fastener as its base: OVER 1.5" in capsys.readouterr().out


def test_at_the_factor_it_still_passes(trees, capsys):
    base = trees({"totals": [30.0, 30.0]}, {"totals": [45.0, 45.0]})
    assert run(base) == 0
    assert "1.50 times as long a fastener as its base: within 1.5" in capsys.readouterr().out


def test_the_factor_is_said(trees, capsys):
    base = trees({"totals": [30.0, 30.0]}, {"totals": [45.0, 45.0]})
    assert run(base, "--slower", "1.4") == 1
    assert "OVER 1.4" in capsys.readouterr().out


def test_with_no_factor_it_reports_only(trees, capsys):
    base = trees({"totals": [10.0, 10.0]}, {"totals": [90.0, 90.0]})
    assert run(base, "--slower", "0") == 0
    assert "9.00 times as long a fastener as its base: report only" in capsys.readouterr().out


def test_it_goes_by_the_time_a_fastener_so_a_bench_that_grew_is_allowed_for(trees, capsys):
    # 600 fasteners in 45 s takes 75 ms each, as 400 in 30 s does.
    base = trees(
        {"totals": [30.0, 30.0], "fasteners": 400}, {"totals": [45.0, 45.0], "fasteners": 600}
    )
    assert run(base) == 0
    assert "takes 1.00 times as long" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("base_totals", "this_totals", "ratio"),
    [([40.0, 30.0], [60.0, 31.0], "1.03"), ([31.0, 80.0], [30.0, 62.0], "0.97")],
)
def test_each_side_s_fastest_run_counts(trees, capsys, base_totals, this_totals, ratio):
    # A run the runner slowed is not the change: the fastest of each is what each
    # can do.
    base = trees({"totals": base_totals}, {"totals": this_totals})
    assert run(base) == 0
    assert f"takes {ratio} times as long" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# How the two trees are run.
# ---------------------------------------------------------------------------


def test_the_trees_take_turns_base_first_each_running_its_own_perf_script(trees):
    base = trees({"totals": [1.0, 1.0, 1.0]}, {"totals": [1.0, 1.0, 1.0]})
    assert run(base, "--rounds", "3") == 0
    assert trees.turns() == ["base", "this"] * 3
    for side in ("base", "this"):
        said = (trees.root / side / "runs").read_text().splitlines()
        assert said == ["scripts/perf.py --budget 0"] * 3


def test_the_base_comes_from_the_environment(trees, monkeypatch):
    base = trees({"totals": [1.0, 1.0]}, {"totals": [1.0, 1.0]})
    monkeypatch.setenv("WRENCHROOM_PERF_BASE", str(base))
    assert compare.main([]) == 0
    assert trees.turns() == ["base", "this"] * 2


def test_with_no_base_it_says_how_to_give_one(trees, capsys):
    trees({"totals": [1.0]}, {"totals": [1.0]})
    with pytest.raises(SystemExit):
        compare.main([])
    assert "--base or $WRENCHROOM_PERF_BASE" in capsys.readouterr().err


def test_a_base_with_no_environment_says_to_sync_it(trees, tmp_path):
    trees({"totals": [1.0]}, {"totals": [1.0]})
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(SystemExit, match=r"Run `uv sync` in .*bare first"):
        run(bare)


def test_the_comparison_goes_to_the_job_summary_and_the_runs_tables_do_not(
    trees, tmp_path, monkeypatch, capsys
):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    base = trees({"totals": [30.0, 29.0]}, {"totals": [31.0, 30.0]})
    assert run(base) == 0
    out = capsys.readouterr().out
    assert "its summary: on" not in out
    assert out.count("its summary: off") == 4
    written = summary.read_text()
    assert written.count("### wrenchroom perf, against the base") == 1
    assert "| round 2 | 29.00 s | 30.00 s |" in written
    assert "takes 1.03 times as long a fastener as its base: within 1.5" in written


# ---------------------------------------------------------------------------
# A run that goes wrong fails, whichever side.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("side", ["base", "this"])
def test_wrong_verdict_counts_on_either_side_fail(trees, capsys, side):
    plans = {"base": {"totals": [1.0, 1.0]}, "this": {"totals": [1.0, 1.0]}}
    plans[side]["code"] = 1
    base = trees(plans["base"], plans["this"])
    assert run(base) == 1
    out = capsys.readouterr().out
    name = "base" if side == "base" else "this tree"
    assert f"{name} (" in out
    assert "its perf run exited 1: wrong verdict counts, or its output above says" in out
    # It stops there: nothing more is timed.
    assert trees.turns() == (["base"] if side == "base" else ["base", "this"])


def test_a_run_that_prints_no_times_fails(trees, capsys):
    base = trees({"totals": [1.0]}, {"totals": [1.0], "rows": False})
    assert run(base) == 1
    assert "its perf run printed no model or read + check row" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The rows read are the rows perf.py prints.
# ---------------------------------------------------------------------------


def perf_run(monkeypatch, read, checked, *argv):
    """perf.py's main, with ``read`` and ``checked`` seconds timed and nothing built."""
    perf = _script("perf")
    report = SimpleNamespace(summary={"fasteners": 549})
    timed = (report, 12.1, read, checked, [None] * 1434, {"fasteners": 549})
    monkeypatch.setattr(perf, "_timed", lambda copies, which, engine: timed)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return perf.main(list(argv))


def test_the_rows_it_reads_are_the_ones_perf_py_prints(monkeypatch, capsys):
    assert perf_run(monkeypatch, 2.13, 10.28, "--budget", "0") == 0
    out = capsys.readouterr().out
    assert compare.FASTENERS.search(out).group(1) == "549"
    assert compare.TOTAL.search(out).group(1) == "12.41"


def test_the_rows_a_runner_printed_are_read():
    # The perf job's log on ubuntu-latest at 0.8.2.dev0.
    out = (
        "machine          x86_64 Linux, Python 3.13.12\n"
        "model            549 fasteners, 1434 parts (3 copies of the bench)\n"
        "engine           mesh\n"
        "read + check     47.75 s, budget 0 s: report only\n"
    )
    assert compare.FASTENERS.search(out).group(1) == "549"
    assert compare.TOTAL.search(out).group(1) == "47.75"


# ---------------------------------------------------------------------------
# The perf job runs it against the base.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("checked", "code", "said"), [(12.9, 0, "PASS"), (13.1, 1, "OVER")])
def test_the_laptop_budget_is_15_s(monkeypatch, capsys, checked, code, said):
    lanes = {lane.name: lane for lane in _script("lanes").LANES}
    assert lanes["perf"].steps == (("python", "scripts/perf.py"),)
    assert perf_run(monkeypatch, 2.0, checked) == code
    assert f"budget 15 s: {said}" in capsys.readouterr().out


def test_ci_s_perf_job_compares_with_its_base():
    lanes = {lane.name: lane for lane in _script("lanes").LANES}
    assert lanes["perf-compare"].steps == (("python", "scripts/perf_compare.py"),)
    job = yaml.safe_load(CI_YML.read_text())["jobs"]["perf"]
    steps = job["steps"]
    assert steps[0]["with"]["fetch-depth"] == 0  # the base's commit is fetched
    (base,) = [step for step in steps if "worktree add" in step.get("run", "")]
    assert base["env"] == {
        "EVENT": "${{ github.event_name }}",
        "PR_BASE": "${{ github.event.pull_request.base.sha }}",
        "BEFORE": "${{ github.event.before }}",
    }
    assert 'git worktree add --detach "$RUNNER_TEMP/base" "$base"' in base["run"]
    assert 'uv sync --frozen --python 3.13 --project "$RUNNER_TEMP/base"' in base["run"]
    (compared,) = [step for step in steps if "perf-compare" in step.get("run", "")]
    assert compared["run"] == "uv run --frozen python scripts/lanes.py perf-compare"
    assert compared["env"] == {"WRENCHROOM_PERF_BASE": "${{ runner.temp }}/base"}
    assert steps.index(base) < steps.index(compared)
    # On Linux; a macOS runner varies as much within a job, and reports one run.
    assert base["if"] == compared["if"] == "matrix.os == 'ubuntu-latest'"
    (reported,) = [step for step in steps if "perf-report" in step.get("run", "")]
    assert reported == {
        "if": "matrix.os != 'ubuntu-latest'",
        "run": "uv run --frozen python scripts/lanes.py perf-report",
    }


def base_step():
    steps = yaml.safe_load(CI_YML.read_text())["jobs"]["perf"]["steps"]
    (step,) = [step for step in steps if "worktree add" in step.get("run", "")]
    return step["run"]


@pytest.mark.parametrize(
    ("event", "base"),
    [("pull_request", "a1" * 20), ("push", "b2" * 20), ("workflow_dispatch", "c3" * 20)],
)
def test_the_base_is_a_pr_s_base_a_push_s_previous_main_or_where_a_branch_left(
    tmp_path, event, base
):
    # The step's own script, as a runner runs it, with git and uv stood in for.
    stubs, calls = tmp_path / "bin", tmp_path / "calls"
    stubs.mkdir()
    for tool in ("git", "uv"):
        stub = stubs / tool
        stub.write_text(
            f'#!/bin/sh\necho "{tool} $*" >> "{calls}"\n'
            f'[ "$1" = merge-base ] && echo {"c3" * 20}\nexit 0\n'
        )
        stub.chmod(0o755)
    env = {
        "PATH": f"{stubs}:/usr/bin:/bin",
        "EVENT": event,
        "PR_BASE": "a1" * 20,
        "BEFORE": "b2" * 20,
        "RUNNER_TEMP": str(tmp_path),
    }
    shell = ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", base_step()]
    subprocess.run(shell, env=env, check=True)  # noqa: S603  (the repo's own workflow)
    said = calls.read_text().splitlines()
    assert said[-2:] == [
        f"git worktree add --detach {tmp_path}/base {base}",
        f"uv sync --frozen --python 3.13 --project {tmp_path}/base",
    ]
    assert ("git merge-base origin/main HEAD" in said) == (event == "workflow_dispatch")
