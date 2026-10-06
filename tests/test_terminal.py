"""Names from a model can't steer the terminal: the escaping, and every way out.

A crafted STEP file carries escape sequences and newlines in its part names
through the importer byte for byte (measured), so the guard has to be at the
output: `wrenchroom.terminal.printable`, applied to every line a person reads.
"""

import ast
import json
from pathlib import Path

import numpy as np
import pytest
from build123d import Box, Compound, Pos, export_step
from click.testing import CliRunner

import wrenchroom.cli
from fixture_models import socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.terminal import UNSAFE, printable

ESC = chr(0x1B)
BEL = chr(0x07)
RLO = chr(0x202E)  # right-to-left override
CSI8 = chr(0x9B)  # the one-byte control sequence introducer

#: The exact set of characters printable() must escape, spelled out here
#: independently of the regex it tests.
STEERING = (
    set(range(0x00, 0x20))
    | set(range(0x7F, 0xA0))
    | {0x061C, 0x200E, 0x200F, 0x2028, 0x2029}
    | set(range(0x202A, 0x202F))
    | set(range(0x2066, 0x206A))
)


# ---------------------------------------------------------------------------
# printable() itself.
# ---------------------------------------------------------------------------


def test_exactly_the_steering_characters_are_escaped_across_the_whole_bmp():
    escaped = set()
    for code in range(0x10000):
        if 0xD800 <= code <= 0xDFFF:
            continue  # surrogates are not characters
        if printable(chr(code)) != chr(code):
            escaped.add(code)
    assert escaped == STEERING


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        (ESC + "]0;pwned" + BEL, "\\x1b]0;pwned\\x07"),
        (ESC + "[2J", "\\x1b[2J"),
        ("a\r\nb", "a\\x0d\\x0ab"),
        ("tab\there", "tab\\x09here"),
        ("nul\x00", "nul\\x00"),
        ("del\x7f", "del\\x7f"),
        (CSI8 + "2J", "\\x9b2J"),
        ("shelf" + RLO + "txt.exe", "shelf\\u202etxt.exe"),
        ("isolate" + chr(0x2066) + "x" + chr(0x2069), "isolate\\u2066x\\u2069"),
        ("line" + chr(0x2028) + "sep", "line\\u2028sep"),
    ],
)
def test_each_kind_is_written_out_visibly(raw, shown):
    assert printable(raw) == shown


@pytest.mark.parametrize(
    "text",
    [
        "key_wall_near_screw",
        "ISO 4762 M6x20",
        "Schraube \u00d86 \u00d7 20",
        "café_螺丝",
        "back\\slash and \\x1b written out already",
        "emoji 🔩 and zero-width joiner 👩‍🔧",
        "",
    ],
)
def test_ordinary_names_pass_untouched(text):
    assert printable(text) == text


def test_random_text_comes_out_clean_and_stays_put():
    rng = np.random.default_rng(1729)
    alphabet = [*map(chr, sorted(STEERING)), "a", "Z", "0", " ", "_", "#", "\\", "é", "螺", "Ø"]
    for _ in range(500):
        text = "".join(rng.choice(alphabet, size=int(rng.integers(0, 40))))
        shown = printable(text)
        assert not UNSAFE.search(shown)
        assert printable(shown) == shown  # escaping twice changes nothing


# ---------------------------------------------------------------------------
# The report: terminal lines safe, JSON exact.
# ---------------------------------------------------------------------------

BOLT = "bolt" + ESC + "]0;pwned" + BEL
FORGED = "36 fasteners: 36 turn, 0 held, 0 blocked, 0 stuck, 0 not covered"
WALL = "wall\n" + FORGED + RLO


def hostile_model():
    """A screw under a close wall (blocked by it), both with hostile names."""
    wall = Pos(0, 0, 26 + 15 + 5) * Box(400, 400, 10)
    return Assembly([Part(BOLT, socket_screw()), Part(WALL, wall)])


SIDECAR = {"fasteners": [{"parts": "bolt*", "kind": "screw", "head": "socket", "size": "M6"}]}


def test_terminal_lines_cannot_steer_or_forge_a_line():
    report = check(hostile_model(), Config.from_dict(SIDECAR), engine="exact")
    lines = report.terminal_lines()
    assert not any(UNSAFE.search(line) for line in lines)
    assert FORGED not in [line.strip() for line in lines]  # no line of its own
    fail = next(line for line in lines if line.startswith("FAIL"))
    assert "\\x1b]0;pwned\\x07" in fail
    assert "wall\\x0a36 fasteners" in fail


def test_the_json_keeps_the_real_names():
    report = check(hostile_model(), Config.from_dict(SIDECAR), engine="exact")
    text = json.dumps(report.to_json_dict())
    assert ESC not in text  # the encoder writes \u001b itself
    (entry,) = json.loads(text)["fasteners"]
    assert entry["name"] == BOLT
    assert entry["blocked_by"] == [WALL]


# ---------------------------------------------------------------------------
# The CLI, end to end, through a real STEP file.
# ---------------------------------------------------------------------------


@pytest.fixture
def hostile_step(tmp_path):
    shapes = []
    for part in hostile_model():
        part.shape.label = part.name
        shapes.append(part.shape)
    export_step(Compound(children=shapes), str(tmp_path / "model.step"))
    (tmp_path / "wrenchroom.yaml").write_text(
        "fasteners:\n  - {parts: 'bolt*', kind: screw, head: socket, size: M6}\n"
    )
    names = Assembly.from_step(tmp_path / "model.step").names
    assert any(ESC in name for name in names), "the attack must survive the STEP round trip"
    return tmp_path / "model.step"


def _run(*args):
    # color=True: Click strips some ANSI codes when it thinks it isn't on a
    # terminal; the test must see what a real terminal would get.
    return CliRunner().invoke(main, list(args), color=True)


def _assert_safe(output):
    for line in output.splitlines():
        assert not UNSAFE.search(line), repr(line)
    assert FORGED not in [line.strip() for line in output.splitlines()]


def test_check_prints_nothing_that_steers(hostile_step, tmp_path):
    result = _run("check", str(hostile_step), "--json", str(tmp_path / "r.json"))
    assert result.exit_code == 1
    _assert_safe(result.output)
    assert "\\x1b]0;pwned\\x07" in result.output
    (entry,) = json.loads((tmp_path / "r.json").read_text())["fasteners"]
    assert ESC in entry["name"]  # the machine-readable report keeps the truth


def test_explain_prints_nothing_that_steers(hostile_step):
    names = Assembly.from_step(hostile_step).names
    bolt = next(name for name in names if name.startswith("bolt"))
    result = _run("explain", str(hostile_step), bolt)
    assert result.exit_code == 1
    _assert_safe(result.output)
    assert "hit wall\\x0a36 fasteners" in result.output


def test_an_error_naming_a_hostile_fastener_is_escaped_too(hostile_step):
    result = _run("explain", str(hostile_step), "ghost" + ESC + "[2J")
    assert result.exit_code == 2
    _assert_safe(result.output)


def test_nothing_in_the_cli_reaches_the_terminal_but_through_say():
    tree = ast.parse(Path(wrenchroom.cli.__file__).read_text())
    callers = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"echo", "secho", "print"}
            ) or (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print"):
                callers.append(function.name)
    assert callers == ["_say"]
