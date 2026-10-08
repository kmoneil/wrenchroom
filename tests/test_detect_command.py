"""`wrenchroom detect`: the sidecar it writes loads, describes what was found, and
holds whatever names a model throws at it.

The contract (spec 7.4): one entry per found part with its kind, head and size, its
axis and how sure detection was, in a file the config loader takes as it stands.
Kept beside the model, it must describe each part exactly as detection did: the
round trip below checks that every verdict, tool and way survives it.
"""

import fnmatch
import json

import numpy as np
import pytest
import yaml
from build123d import Box, Compound, Cylinder, Pos, export_step
from click.testing import CliRunner

from fastener_models import hex_bolt, hex_nut, socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import EXIT_NOT_COVERED, main
from wrenchroom.config import Config
from wrenchroom.detect.sidecar import glob_escape, sidecar_text
from wrenchroom.terminal import UNSAFE

ESC, RLO = chr(0x1B), chr(0x202E)


def export(tmp_path, parts, name="model.step"):
    shapes = []
    for part_name, shape in parts:
        shape.label = part_name
        shapes.append(shape)
    path = tmp_path / name
    export_step(Compound(children=shapes), str(path))
    return path


def plate():
    return Pos(0, 0, -5) * Box(400, 400, 10)


def model_parts():
    return [
        ("plate", plate()),
        ("frame_bolt", Pos(0, 0, 0) * hex_bolt("M8")),
        ("frame_nut", Pos(100, 0, 0) * hex_nut("M10")),
        ("ISO 4762 M6x20", Pos(-100, 0, 0) * socket_screw("M6")),
        ("DIN 7984 M5x8", Pos(0, 100, 0) * socket_screw("M5")),
    ]


def detected_yaml(tmp_path, parts):
    result = CliRunner().invoke(main, ["detect", str(export(tmp_path, parts))])
    assert result.exit_code == 0, result.output
    return result


def test_the_sidecar_loads_and_round_trips_the_verdicts(tmp_path):
    model = export(tmp_path, model_parts())
    assembly = Assembly.from_step(model)
    detected = check(assembly, Config(), model_dir=tmp_path)
    text = sidecar_text(detected, "model.step")
    config = Config.from_dict(yaml.safe_load(text))
    kept = check(assembly, config, model_dir=tmp_path)
    assert kept.unmatched_rules == ()
    # Everything is now described by the file, but for the commented-out one,
    # which detection finds again, and again can't check.
    sources = {r.fastener.name: r.fastener.source for r in kept.results}
    assert {n for n, source in sources.items() if source != "sidecar"} == {"DIN 7984 M5x8"}
    before = {r.fastener.name: (r.verdict, r.tool, r.how) for r in detected.results}
    after = {r.fastener.name: (r.verdict, r.tool, r.how) for r in kept.results}
    assert after == before


def test_each_rule_says_how_sure_and_what_found_it(tmp_path):
    output = detected_yaml(tmp_path, model_parts()).stdout
    for name in ("frame_bolt", "frame_nut", "ISO 4762 M6x20", "DIN 7984 M5x8"):
        comment = next(
            line for line in output.splitlines() if line.strip().startswith(f"# {name}:")
        )
        assert any(f"{level} confidence" in comment for level in ("high", "medium", "low"))
        assert "found by" in comment
    assert (
        "found 4 fasteners, 1 not covered"
        in CliRunner().invoke(main, ["detect", str(tmp_path / "model.step")]).stderr
    )


def test_a_fastener_the_kit_cannot_check_is_written_commented_out(tmp_path):
    # Kept as a live rule it would become a checked socket screw with the
    # socket-head table's key: a false "turns" for a low-head socket screw.
    output = detected_yaml(tmp_path, model_parts()).stdout
    assert "now not-covered: a low-head socket screw" in output
    assert "  # - parts: DIN 7984 M5x8" in output
    assert all(e["parts"] != "DIN 7984 M5x8" for e in yaml.safe_load(output)["fasteners"])


def test_detect_writes_a_torx_head_wherever_the_name_says_it(tmp_path):
    # Issue #19's reproduction: one solid, the drive word next to the noun or not.
    head = Pos(0, 0, 3) * Cylinder(5, 6) - Pos(0, 0, 4.5) * Cylinder(2.8, 3.01)
    screw = head + Pos(0, 0, -5) * Cylinder(3, 10)
    parts = [
        ("lid_torx_screw", screw),
        ("plate_0", Pos(0, 0, -3) * Box(60, 60, 6)),
        ("torx_lid_screw", Pos(100, 0, 0) * screw),
        ("plate_1", Pos(100, 0, -3) * Box(60, 60, 6)),
    ]
    output = detected_yaml(tmp_path, parts).stdout
    rules = {rule["parts"]: rule for rule in yaml.safe_load(output)["fasteners"]}
    assert rules["lid_torx_screw"]["head"] == rules["torx_lid_screw"]["head"] == "torx"
    assert "found by noun 'screw', drive 'torx'; solid: M6 measured" in output
    assert "now turns with torx-key-T30" not in output  # metric-home holds no Torx key
    assert "outline" not in output


def test_confidence_reflects_the_evidence(tmp_path):
    output = detected_yaml(tmp_path, model_parts()).stdout
    lines = {
        line.split(":")[0].strip("# "): line
        for line in output.splitlines()
        if " confidence" in line
    }
    assert "high confidence" in lines["ISO 4762 M6x20"]  # standard, socket, settled size
    assert "low confidence" in lines["DIN 7984 M5x8"]  # not covered


def test_a_model_with_nothing_named_like_a_fastener_writes_an_empty_sidecar(tmp_path):
    result = detected_yaml(
        tmp_path, [("plate", plate()), ("wall", Pos(0, 0, 50) * Box(10, 10, 10))]
    )
    assert yaml.safe_load(result.stdout)["fasteners"] == []
    assert "found 0 fasteners" in result.stderr


def test_an_unreadable_model_exits_2(tmp_path):
    bad = tmp_path / "bad.step"
    bad.write_text("not a step file")
    assert CliRunner().invoke(main, ["detect", str(bad)]).exit_code == EXIT_NOT_COVERED


# ---------------------------------------------------------------------------
# Hostile and awkward names: the rule matches that part alone, the file stays YAML.
# ---------------------------------------------------------------------------

AWKWARD = [
    ESC + "]0;pwned\x07 bolt",
    "x\n  - parts: '*'\n    kind: nut\n# bolt",
    "shelf" + RLO + " bolt",
    "bolt[1]",
    "* bolt",
    "bolt?",
    "here: # not a comment bolt",
    "'quoted' \"bolt\"",
    "caf\u00e9_bolt",
    "\u87ba\u4e1d_bolt",
]


@pytest.mark.parametrize("name", AWKWARD, ids=repr)
def test_an_awkward_name_writes_a_rule_for_that_part_alone(tmp_path, name):
    parts = [("plate", plate()), (name, hex_bolt("M8")), ("bolt1", Pos(200, 0, 0) * hex_bolt("M8"))]
    assembly = Assembly([Part(n, s) for n, s in parts])
    report = check(assembly, Config())
    text = sidecar_text(report, "model.step")
    assert not any(UNSAFE.search(line) for line in text.splitlines()), (
        "steering characters in the file"
    )
    assert name in {r.fastener.name for r in report.results}, "the name must read as a bolt"
    rules = yaml.safe_load(text)["fasteners"]
    assert [r["parts"] for r in rules if fnmatch.fnmatchcase(name, r["parts"])] == [
        glob_escape(name)
    ]
    matched = [n for n in assembly.names if fnmatch.fnmatchcase(n, glob_escape(name))]
    assert matched == [name]


def test_readable_names_stay_readable(tmp_path):
    report = check(Assembly([Part("café_bolt", hex_bolt("M8")), Part("plate", plate())]), Config())
    assert "café_bolt" in sidecar_text(report, "m.step")


def test_glob_escape_matches_exactly_the_name():
    rng = np.random.default_rng(603)
    alphabet = list("ab_-[]*?!^.x")
    for _ in range(2000):
        name = "".join(rng.choice(alphabet, size=int(rng.integers(1, 12))))
        pattern = glob_escape(name)
        assert fnmatch.fnmatchcase(name, pattern), (name, pattern)
        other = name + "x"
        assert not fnmatch.fnmatchcase(other, pattern), (other, pattern)


def test_the_bench_detect_output_round_trips(bench_dir_any):
    # The whole bench: detect, load, check again; every verdict the same.
    assembly = Assembly.from_step(bench_dir_any / "bench.step")
    stripped = json.loads(json.dumps({"states": {}}))
    detected = check(assembly, Config.from_dict(stripped), model_dir=bench_dir_any)
    config = Config.from_dict(yaml.safe_load(sidecar_text(detected, "bench.step")))
    kept = check(assembly, config, model_dir=bench_dir_any)
    assert kept.unmatched_rules == ()
    before = {r.fastener.name: (r.verdict, r.tool, r.how) for r in detected.results}
    after = {r.fastener.name: (r.verdict, r.tool, r.how) for r in kept.results}
    assert after == before


@pytest.fixture(scope="module")
def bench_dir_any(tmp_path_factory):
    import sys  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    sys.path.insert(0, str(Path(__file__).parent / "golden"))
    from bench import write  # noqa: PLC0415

    directory = tmp_path_factory.mktemp("bench_for_detect")
    write(directory)
    return directory
