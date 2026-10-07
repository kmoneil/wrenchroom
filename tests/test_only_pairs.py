"""``--only`` and ``explain`` narrow what is reported, never what is resolved (#46).

A nut that only holds passes through its turning bolt: it is ``held``. Narrowed
to the nut alone, the check used to leave its bolt out, find no pair, and call it
blocked, "only holds, and it has no nut", contradicting the full run. Pairs are
now found over the whole model and a chosen fastener's partner is checked with
it, so a narrowed verdict is the full run's.
"""

import pytest
from build123d import Compound, export_step
from click.testing import CliRunner

from fixture_models import bolt_with_slotted_nut
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.report import Verdict

PAIR = [
    {"parts": "bolt", "kind": "screw", "head": "hex", "size": "M8"},
    {"parts": "nut", "kind": "nut", "size": "M8"},
]


def run(only=None, engine="exact", **config):
    return check(
        bolt_with_slotted_nut(),
        Config.from_dict({"fasteners": PAIR, **config}),
        engine=engine,
        only=only,
    )


def fields(result):
    return (result.verdict, result.tool, result.how, result.pair, result.reason, result.blockers)


def test_the_full_run_holds_the_nut_while_its_bolt_turns(engine):
    by_name = {r.fastener.name: r for r in run(engine=engine).results}
    assert (by_name["nut"].verdict, by_name["nut"].pair) == (Verdict.HELD, "bolt")
    assert by_name["bolt"].verdict is Verdict.TURNS


@pytest.mark.parametrize("name", ["nut", "bolt"])
def test_narrowed_to_one_it_reads_as_in_the_full_run(engine, name):
    full = {r.fastener.name: r for r in run(engine=engine).results}
    narrowed = run(name, engine=engine)
    (result,) = narrowed.results  # its partner was checked, not reported
    assert fields(result) == fields(full[name])
    assert narrowed.exit_code == 0


def test_a_forced_pair_with_one_side_left_out_raises_no_warning():
    report = run("bolt", pairs=[["bolt", "nut"]])
    assert report.warnings == ()
    (result,) = report.results
    assert result.pair == "nut"


def _exported(tmp_path, rename=None):
    shapes = []
    for part in bolt_with_slotted_nut():
        part.shape.label = (rename or {}).get(part.name, part.name)
        shapes.append(part.shape)
    export_step(Compound(children=shapes), str(tmp_path / "model.step"))
    return tmp_path / "model.step"


def test_explain_tells_the_full_run_s_story(tmp_path):
    model = _exported(tmp_path)
    (tmp_path / "wrenchroom.yaml").write_text(
        "fasteners:\n"
        "  - {parts: bolt, kind: screw, head: hex, size: M8}\n"
        "  - {parts: nut, kind: nut, size: M8}\n"
    )
    result = CliRunner().invoke(main, ["explain", str(model), "nut"])
    assert result.exit_code == 0
    assert result.stdout.splitlines()[0].startswith("nut: held with spanner-13")
    assert "paired with bolt" in result.stdout.splitlines()[0]
    assert "it has no nut" not in result.stdout


def test_explain_finds_a_name_that_reads_as_a_glob(tmp_path):
    # "nut[1]" as a glob means "nut1"; explain means the part of that name.
    model = _exported(tmp_path, rename={"nut": "nut[1]"})
    (tmp_path / "wrenchroom.yaml").write_text(
        "fasteners:\n"
        "  - {parts: bolt, kind: screw, head: hex, size: M8}\n"
        "  - {parts: 'nut[[]1[]]', kind: nut, size: M8}\n"
    )
    result = CliRunner().invoke(main, ["explain", str(model), "nut[1]"])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("nut[1]: held")
