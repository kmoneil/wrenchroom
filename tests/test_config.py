"""The sidecar: the spec's example (names generic) loads, matches, fails loudly."""

import pytest
from build123d import Box

from wrenchroom.assembly import Assembly, Part
from wrenchroom.config import Config, ConfigError
from wrenchroom.fasteners import AUTO, Head, Kind

SPEC_EXAMPLE = """
fasteners:
  - parts: "bracket_*_bolt_*"
    kind: screw
    head: socket
    size: M6
    length: 50
    tool: hex-key-5
    axis: auto
  - parts: "bracket_*_nut_*"
    kind: nut
    size: M6
  - parts: "fender_bolt_*"
    head: carriage
ignore:
  - "wire_*"
  - "*_spring_*"
pairs:
  - [swing_arm_bolt_0, swing_arm_nut_0]
"""


def assembly_of(*names):
    box = Box(5, 5, 5)
    return Assembly(Part(name, box) for name in names)


@pytest.fixture
def spec_config(tmp_path):
    path = tmp_path / "wrenchroom.yaml"
    path.write_text(SPEC_EXAMPLE)
    return Config.load(path)


def test_spec_example_loads(spec_config):
    assert len(spec_config.rules) == 3
    first = spec_config.rules[0]
    assert first.kind is Kind.SCREW
    assert first.head is Head.SOCKET
    assert first.size.designation == "M6"
    assert first.length_mm == 50
    assert first.tool == "hex-key-5"
    assert first.axis == AUTO
    assert spec_config.ignore == ("wire_*", "*_spring_*")
    assert spec_config.pairs == (("swing_arm_bolt_0", "swing_arm_nut_0"),)


def test_head_implies_screw_and_bare_nut_says_so(spec_config):
    assert spec_config.rules[2].kind is Kind.SCREW  # carriage head, no kind given
    assert spec_config.rules[1].kind is Kind.NUT


def test_apply_matches_globs_and_reports_what_missed(spec_config):
    assembly = assembly_of(
        "bracket_left_bolt_0",
        "bracket_left_bolt_1",
        "bracket_left_nut_0",
        "wire_main",
        "frame_left",
    )
    matches = spec_config.apply(assembly)
    names = sorted(f.name for f in matches.fasteners)
    assert names == ["bracket_left_bolt_0", "bracket_left_bolt_1", "bracket_left_nut_0"]
    assert [r.parts for r in matches.unmatched_rules] == ["fender_bolt_*"]
    assert matches.unmatched_ignores == ("*_spring_*",)
    assert not matches.clean


def test_clean_when_everything_matches(spec_config):
    assembly = assembly_of(
        "bracket_a_bolt_0", "bracket_a_nut_0", "fender_bolt_0", "wire_x", "big_spring_1"
    )
    assert spec_config.apply(assembly).clean


def test_ignored_parts_cannot_be_fasteners():
    config = Config.from_dict({"fasteners": [{"parts": "wire_*"}], "ignore": ["wire_*"]})
    matches = config.apply(assembly_of("wire_bolt_0"))
    assert matches.fasteners == ()
    assert [r.parts for r in matches.unmatched_rules] == ["wire_*"]


def test_later_rule_overrides_earlier_for_the_same_part():
    config = Config.from_dict(
        {
            "fasteners": [
                {"parts": "bolt_*", "head": "socket"},
                {"parts": "bolt_special", "head": "hex"},
            ]
        }
    )
    matches = config.apply(assembly_of("bolt_special", "bolt_plain"))
    by_name = {f.name: f for f in matches.fasteners}
    assert by_name["bolt_special"].head is Head.HEX
    assert by_name["bolt_plain"].head is Head.SOCKET


def test_axis_spellings():
    config = Config.from_dict(
        {
            "fasteners": [
                {"parts": "a", "axis": "-z"},
                {"parts": "b", "axis": [0, 3, 4]},
            ]
        }
    )
    a, b = config.rules
    assert a.axis == (0.0, 0.0, -1.0)
    assert b.axis == (0.0, 0.6, 0.8)  # normalised


def test_socket_false_for_glands():
    config = Config.from_dict({"fasteners": [{"parts": "*_gland_*", "socket": False}]})
    assert config.rules[0].socket_allowed is False


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ({"states": {"open": {"base": "missing"}}}, "is not a state"),
        ({"states": {"a": {"base": "b"}, "b": {"base": "a"}}}, "loops"),
        ({"states": {"open": {"lid": []}}}, "unknown key"),
        ({"checks": {"default_state": "ghost"}}, "is not a state"),
        ({"checks": {"try_states": ["ghost"]}}, "unknown state"),
        ({"fasteners": [{"parts": "a", "state": "service"}]}, "unknown state"),
        ({"typo": []}, "unknown key"),
        ({"fasteners": [{"kind": "screw"}]}, "'parts' is required"),
        ({"fasteners": [{"parts": "a", "size": "M7"}]}, "unknown fastener size"),
        ({"fasteners": [{"parts": "a", "head": "philips"}]}, "not one of"),
        ({"fasteners": [{"parts": "a", "axis": [0, 0, 0]}]}, "zero vector"),
        ({"fasteners": [{"parts": "a", "length": -3}]}, "positive number"),
        ({"fasteners": [{"parts": "a", "socket": "no"}]}, "true or false"),
        ({"pairs": [["only-one"]]}, "two-item list"),
        ([1, 2], "must be a mapping"),
    ],
)
def test_bad_sidecars_fail_loudly(raw, match):
    with pytest.raises(ConfigError, match=match):
        Config.from_dict(raw)


def test_unparseable_yaml_names_the_file(tmp_path):
    path = tmp_path / "wrenchroom.yaml"
    path.write_text("fasteners: [unclosed")
    with pytest.raises(ConfigError, match="not valid YAML"):
        Config.load(path)


def test_empty_file_is_an_empty_config(tmp_path):
    path = tmp_path / "wrenchroom.yaml"
    path.write_text("")
    config = Config.load(path)
    assert config.rules == ()
    assert config.apply(assembly_of("anything")).clean
