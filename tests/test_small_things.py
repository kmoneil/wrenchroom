"""Issue #33's small things: big spanners, a gland's label, the kernel kept quiet.

1. The full kit's spanners and sockets reach 50 mm (41, 46 and 50 after 36), which
   large cable glands take: an M32 gland is commonly 41 across flats. A hex
   larger than every spanner says so.
2. A gland found by its name has no thread size by design, and was listed as
   "? nut"; it is now "24 AF gland", by the hex it was measured by.
3. OCP printed its own error for a bad STEP file to stdout, in colour, after
   wrenchroom's; it is now kept quiet and folded into wrenchroom's error.
"""

import pytest
from build123d import Box, Compound, Cylinder, Pos, export_step
from click.testing import CliRunner
from OCP.Message import Message

from fixture_models import gland
from wrenchroom.assembly import Assembly, Part, _kernel_lines, _kernel_quiet
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.tools.kits import FULL, IMPERIAL_HOME, METRIC_HOME
from wrenchroom.tools.sizes import METRIC_FLATS
from wrenchroom.tools.spanners import LARGE_LENGTHS, spanner_for

# ---------------------------------------------------------------------------
# 1. Spanners above 36 mm.
# ---------------------------------------------------------------------------


def test_the_metric_sizes_go_on_to_50():
    assert METRIC_FLATS[-4:] == (36.0, 41.0, 46.0, 50.0)
    for size in ("41", "46", "50"):
        assert size in FULL.spanners
        assert size in FULL.sockets
        assert size not in METRIC_HOME.spanners
        assert size not in IMPERIAL_HOME.spanners


def test_the_big_spanners_are_as_long_as_a_maker_makes_them():
    # Gedore 1 B, to DIN 3113: 41 is 520 long, 46 550, 50 580.
    assert LARGE_LENGTHS == {41.0: 520.0, 46.0: 550.0, 50.0: 580.0}
    for af, length in LARGE_LENGTHS.items():
        assert spanner_for(af).length == length
        assert length > 9 * af + 45  # longer than the formula: the safe side
    assert spanner_for(36.0).length == 9 * 36 + 45  # below, the formula as before


def big_gland_on_wall(af=41.0):
    """An M32-class gland: a hex of `af` across flats through a wall, room all round."""
    wall = Pos(0, 0, -5) * Box(300, 300, 10) - Cylinder(16.2, 11)
    body = gland(af=af, hex_h=10.0, dome_r=17.0, dome_h=20.0, stub_r=16.0, stub_h=14.0)
    return Assembly([Part("big_gland", body), Part("wall", wall)])


def test_a_41_mm_gland_takes_the_41_mm_spanner():
    # It used to be "41.00 mm across flats is no tool's size".
    (result,) = check(big_gland_on_wall(), kit="full").results
    assert (result.verdict, result.tool, result.how) == (
        Verdict.TURNS,
        "spanner-41",
        "ring, full length",
    )


def test_the_home_kit_names_the_big_spanner_it_lacks():
    (result,) = check(big_gland_on_wall(), kit="metric-home").results
    assert result.reason == "needs spanner-41, which kit metric-home does not hold (full has it)"


def test_a_hex_larger_than_every_spanner_says_so():
    rule = {"parts": "big_gland", "kind": "nut", "socket": False, "across_flats": 60}
    (result,) = check(
        big_gland_on_wall(), Config.from_dict({"fasteners": [rule]}), kit="full"
    ).results
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == (
        "60.00 mm across flats is larger than any spanner the tables hold "
        "(spanner-50 the largest); set tool: in the sidecar"
    )


# ---------------------------------------------------------------------------
# 2. A gland's label.
# ---------------------------------------------------------------------------


def test_a_gland_with_no_size_is_listed_by_its_hex():
    report = check(big_gland_on_wall(24.0), kit="full")
    assert report.terminal_lines()[1].startswith("  24 AF gland ")
    assert "24 AF gland" in report.markdown()


def test_a_nut_with_no_size_and_a_hex_is_listed_by_its_hex_as_a_nut():
    rule = {"parts": "big_gland", "kind": "nut", "across_flats": 41}
    report = check(big_gland_on_wall(), Config.from_dict({"fasteners": [rule]}), kit="full")
    assert report.terminal_lines()[1].startswith("  41 AF nut ")


def test_a_size_still_names_itself():
    rule = {"parts": "big_gland", "kind": "nut", "size": "M24", "socket": False, "across_flats": 41}
    report = check(big_gland_on_wall(), Config.from_dict({"fasteners": [rule]}), kit="full")
    assert report.terminal_lines()[1].startswith("  M24 nut ")


def test_with_neither_size_nor_hex_it_is_still_a_question_mark():
    rule = {"parts": "big_gland", "kind": "screw", "head": "torx"}
    report = check(big_gland_on_wall(), Config.from_dict({"fasteners": [rule]}), kit="full")
    assert report.terminal_lines()[1].startswith("  ? torx screw ")


# ---------------------------------------------------------------------------
# 3. The CAD kernel kept quiet.
# ---------------------------------------------------------------------------


@pytest.fixture
def bad_step(tmp_path):
    path = tmp_path / "bad.step"
    path.write_text("ISO-10303-21;\nGARBAGE;\n")
    return path


def test_a_bad_step_file_prints_nothing_and_says_why(bad_step, capfd):
    printers = Message.DefaultMessenger_s().Printers().Size()
    with pytest.raises(ValueError, match=r"cannot read .*bad\.step as STEP \(") as caught:
        Assembly.from_step(bad_step)
    assert "Undefined Parsing" in str(caught.value)
    assert "****" not in str(caught.value)
    out, err = capfd.readouterr()  # the C++ side writes to the file descriptors
    assert (out, err) == ("", "")
    assert Message.DefaultMessenger_s().Printers().Size() == printers  # put back


def test_a_good_step_file_prints_nothing_either(tmp_path, capfd):
    shape = Box(10, 10, 10)
    shape.label = "block"
    export_step(Compound(children=[shape]), str(tmp_path / "ok.step"))
    capfd.readouterr()
    assert Assembly.from_step(tmp_path / "ok.step").names == ("block",)
    assert capfd.readouterr() == ("", "")


def test_the_cli_keeps_stdout_clean_for_a_bad_file(bad_step, capfd):
    # Under --json -, kernel text on stdout would corrupt the piped report.
    result = CliRunner().invoke(main, ["check", str(bad_step), "--json", "-"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "cannot read" in result.stderr
    assert "Undefined Parsing" in result.stderr
    assert capfd.readouterr().out == ""


def test_the_kernel_s_messages_are_kept_whatever_is_raised():
    printers = Message.DefaultMessenger_s().Printers().Size()
    with pytest.raises(RuntimeError), _kernel_quiet():
        raise RuntimeError
    assert Message.DefaultMessenger_s().Printers().Size() == printers


@pytest.mark.parametrize(
    ("raw", "lines"),
    [
        (
            "**** ERR StepFile : Undefined Parsing: Line 3: x    ****\n\n",
            ["Undefined Parsing: Line 3: x"],
        ),
        ("*** FAIL Reader : bad header ***", ["bad header"]),
        ("Parsing: kept whole", ["Parsing: kept whole"]),
        ("\n  \n", []),
    ],
)
def test_the_kernel_s_decoration_is_taken_off(raw, lines):
    assert _kernel_lines(raw) == lines


def test_the_kernel_is_heard_only_inside_the_block():
    with _kernel_quiet() as heard:
        Message.DefaultMessenger_s().Send("**** WARNING Test : only a test ****")
    assert heard == ["only a test"]


def test_while_quiet_the_kernel_has_only_wrenchroom_s_printer():
    # In this process the C++ stream is flushed only at exit, so stdout can't be
    # read here; what the messenger prints to while quiet can.
    messenger = Message.DefaultMessenger_s()
    before = messenger.Printers().Size()
    assert before >= 1  # the kernel's own, to stdout
    with _kernel_quiet():
        during = list(messenger.Printers())
    assert len(during) == 1
    assert messenger.Printers().Size() == before


@pytest.mark.parametrize(
    "argv",
    [
        [
            "-c",
            "import sys; from wrenchroom.assembly import Assembly; Assembly.from_step(sys.argv[1])",
        ],
        ["-c", "from wrenchroom.cli import main; main()", "check"],
    ],
)
def test_a_bad_step_file_leaves_stdout_empty_in_a_process_of_its_own(bad_step, argv, tmp_path):
    # The process exits, the C++ stream is flushed: anything it held shows here.
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    done = subprocess.run(  # noqa: S603  (our own interpreter and module; no shell)
        [sys.executable, *argv, str(bad_step)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=tmp_path,
    )
    assert done.returncode != 0
    assert done.stdout == ""
    assert "StepFile" not in done.stderr  # the kernel's own words, undecorated or not
    assert "Undefined Parsing" in done.stderr
