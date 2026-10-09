"""The Markdown report: the terminal's content, safe to render in a GitHub comment.

A report pasted into a pull request is rendered, and the names in it come from the
model, which can come from anybody. Rendered raw, a name could post an image that
calls home when the comment is viewed, a link, emphasis, a forged table row, or a
cell split in two. Every name is written as a code span, so these tests render the
Markdown with a GFM-style parser (markdown-it's gfm-like preset: tables and
autolinks, as GitHub has them) and check what comes out, not what went in.
"""

import html
import json
import re

import numpy as np
import pytest
from build123d import Box, Compound, Pos, export_step
from click.testing import CliRunner
from markdown_it import MarkdownIt

from fixture_models import screw_facing_wall, socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.report import NO_TOOL, md_code, md_text
from wrenchroom.terminal import UNSAFE, printable

GFM = MarkdownIt("gfm-like")

#: Tags a name must never produce in the rendered comment.
INJECTED = re.compile(r"<(a|img|em|strong|script|del|h\d|li|ul|ol|blockquote|pre|iframe)\b")

#: The same, less what a whole report legitimately has (its heading, bold summary,
#: warning list and the Tools section's list), which `_assert_report_structure`
#: counts instead.
INJECTED_IN_REPORT = re.compile(r"<(a|img|em|script|del|ol|blockquote|pre|iframe)\b")


def _assert_report_structure(rendered, warnings, tools_apart=0):
    """``tools_apart``: the Tools section's lines under its table (M8): by hand, no
    tool needed, no tool yet."""
    assert not INJECTED_IN_REPORT.search(rendered), rendered
    assert len(re.findall(r"<h3\b", rendered)) == 1
    assert len(re.findall(r"<h[1256]\b", rendered)) == 0
    assert len(re.findall(r"<strong\b", rendered)) == 1
    assert len(re.findall(r"<li\b", rendered)) == warnings + tools_apart
    assert len(re.findall(r"<ul\b", rendered)) == (warnings > 0) + (tools_apart > 0)


ESC = chr(0x1B)
RLO = chr(0x202E)

#: Names that would each do something if written raw into a comment.
HOSTILE = [
    "![t](https://evil.example/t.png)",
    "[click](https://evil.example)",
    "www.evil.example",
    "https://evil.example/x",
    "someone@evil.example",
    "**bold** and _em_ and ~~gone~~",
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "a|b",
    "a\\|b",
    "trailing\\",
    "`",
    "``",
    "a`b``c",
    "`edge`",
    " lead",
    "trail ",
    " both ",
    "   ",
    "# heading",
    "- item",
    "> quote",
    "line\nbreak | x | y |",
    "bolt" + ESC + "]0;pwned" + chr(7),
    "shelf" + RLO + "gnp.exe",
    "&amp; &lt;",
    "café_螺丝 🔩",
]


def _cells(row_html):
    return re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.DOTALL)


def _body_rows(rendered):
    body = re.search(r"<tbody>(.*?)</tbody>", rendered, flags=re.DOTALL)
    assert body is not None, rendered
    return re.findall(r"<tr>(.*?)</tr>", body.group(1), flags=re.DOTALL)


def _code_text(cell_html):
    """The text of a cell that holds exactly one code span, unescaped."""
    match = re.fullmatch(r"<code>(.*)</code>", cell_html, flags=re.DOTALL)
    assert match is not None, cell_html
    return html.unescape(match.group(1))


# ---------------------------------------------------------------------------
# md_code and md_text on their own.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", HOSTILE)
def test_a_hostile_name_in_a_table_cell_renders_as_itself(name):
    table = f"| a | b |\n| --- | --- |\n| {md_code(name)} | after |\n"
    rendered = GFM.render(table)
    assert not INJECTED.search(rendered), rendered
    (row,) = _body_rows(rendered)
    cells = _cells(row)
    assert len(cells) == 2, "the name split its cell"
    assert cells[1] == "after"
    if printable(name).strip(" "):
        assert _code_text(cells[0]) == printable(name)


@pytest.mark.parametrize("name", HOSTILE)
def test_a_hostile_name_in_a_list_item_renders_as_itself(name):
    rendered = GFM.render(f"- before {md_code(name, in_table=False)} after\n")
    assert not INJECTED.search(rendered.replace("<ul>", "").replace("<li>", "")), rendered
    match = re.fullmatch(r"<ul>\n<li>before <code>(.*)</code> after</li>\n</ul>\n", rendered, re.S)
    assert match is not None, rendered
    if printable(name).strip(" "):
        assert html.unescape(match.group(1)) == printable(name)


def test_nothing_steering_survives_into_the_markdown():
    for name in HOSTILE:
        assert not UNSAFE.search(md_code(name))
        assert not UNSAFE.search(md_text(name))


def test_an_empty_name_is_shown_as_empty_quotes():
    assert md_code("") == '""'


#: Characters Markdown or a GFM table reads specially, plus a few ordinary ones
#: and two steering ones, drawn from for the property cases below.
_ALPHABET = [*"`|\\*_[]()!<>#~:/.@&- ", "a", "w", "é", ESC, "\n"]


def _random_names(seed, count=400):
    rng = np.random.default_rng(seed)
    return ["".join(rng.choice(_ALPHABET, size=int(rng.integers(1, 24)))) for _ in range(count)]


def test_random_names_render_exactly_in_a_table():
    names = _random_names(1729, count=1000)
    # Vacuity guard: the family must actually contain the cases that matter.
    assert sum("`" in n for n in names) > 250
    assert sum("|" in n for n in names) > 250
    assert sum("\\|" in n for n in names) > 10
    assert sum(n.startswith(("`", " ")) or n.endswith(("`", " ")) for n in names) > 120
    rows = "".join(f"| {md_code(name)} | {index} |\n" for index, name in enumerate(names))
    rendered = GFM.render("| name | n |\n| --- | --- |\n" + rows)
    assert not INJECTED.search(rendered)
    got = _body_rows(rendered)
    assert len(got) == len(names)
    checked = 0
    for index, (name, row) in enumerate(zip(names, got, strict=True)):
        cells = _cells(row)
        assert len(cells) == 2, (name, row)
        assert cells[1] == str(index)
        if printable(name).strip(" "):
            assert _code_text(cells[0]) == printable(name), name
            checked += 1
    assert checked > 900


def test_random_names_render_exactly_outside_a_table():
    for name in _random_names(2718, count=200):
        rendered = GFM.render(f"x {md_code(name, in_table=False)} y\n")
        assert not INJECTED.search(rendered)
        match = re.fullmatch(r"<p>x <code>(.*)</code> y</p>\n", rendered, re.S)
        assert match is not None, (name, rendered)
        if printable(name).strip(" "):
            assert html.unescape(match.group(1)) == printable(name)


def test_md_text_shows_wrenchroom_s_own_words_literally():
    rng = np.random.default_rng(31)
    plain = [*"*_[]()!<>#~`\\|-", "a", " ", "6"]
    for _ in range(300):
        text = "a" + "".join(rng.choice(plain, size=int(rng.integers(0, 20)))) + "a"
        rendered = GFM.render(md_text(text) + "\n")
        assert not INJECTED.search(rendered), (text, rendered)
        match = re.fullmatch(r"<p>(.*)</p>\n", rendered, re.S)
        assert match is not None, (text, rendered)
        assert html.unescape(match.group(1)) == text


def test_md_text_shows_wrenchroom_s_own_words_literally_in_a_table():
    rng = np.random.default_rng(32)
    plain = [*"*_[]()!<>#~`\\|-", "a", " ", "6"]
    texts = [
        "a" + "".join(rng.choice(plain, size=int(rng.integers(0, 20)))) + "a" for _ in range(300)
    ]
    assert sum("|" in text for text in texts) > 100  # vacuity guard: pipes are the point
    rows = "".join(f"| {md_text(text)} | {index} |\n" for index, text in enumerate(texts))
    rendered = GFM.render("| what | n |\n| --- | --- |\n" + rows)
    assert not INJECTED.search(rendered)
    got = _body_rows(rendered)
    assert len(got) == len(texts)
    for index, (text, row) in enumerate(zip(texts, got, strict=True)):
        cells = _cells(row)
        assert len(cells) == 2, (text, row)
        assert cells[1] == str(index)
        assert html.unescape(cells[0]) == text


# ---------------------------------------------------------------------------
# The report.
# ---------------------------------------------------------------------------

BOLT = "bolt`|**x** <b>" + ESC + "[2J"
WALL = "![t](https://evil.example/t.png) www.evil.example\n| forged | row |"
SIDECAR = {
    "fasteners": [
        {"parts": "bolt*", "kind": "screw", "head": "socket", "size": "M6"},
        {"parts": "slab_screw*", "kind": "screw", "head": "socket", "size": "M6"},
        {"parts": "no_such_part_*", "kind": "screw"},
    ],
    "ignore": ["no_such_hose_[x]*"],
    "pairs": [["bolt*", "ghost www.evil.example"]],
}


def hostile_model():
    """A blocked screw under a wall, both hostile names; a box claimed as a screw."""
    wall = Pos(0, 0, 26 + 15 + 5) * Box(400, 400, 10)
    slab = Pos(1000, 0, 0) * Box(20, 20, 20)
    return Assembly(
        [
            Part(BOLT, socket_screw()),
            Part(WALL, wall),
            Part("slab_screw ![x](https://evil.example/s.png)", slab),
        ]
    )


@pytest.fixture(scope="module")
def hostile_report():
    return check(hostile_model(), Config.from_dict(SIDECAR), engine="exact")


def test_the_hostile_report_renders_without_injection(hostile_report):
    rendered = GFM.render(hostile_report.markdown())
    # No tool yet: 2; and the blocked one's tool, once reached (#136), its name a span.
    _assert_report_structure(rendered, warnings=3, tools_apart=2)
    assert re.findall(r"<h4>(.*?)</h4>", rendered) == ["Tools", "Failures", "Warnings"]


def test_every_failure_is_one_row_of_four_cells_naming_it_exactly(hostile_report):
    rendered = GFM.render(hostile_report.markdown())
    failures = re.search(r"<h4>Failures</h4>\s*<table>(.*?)</table>", rendered, re.S)
    assert failures is not None
    rows = _body_rows(failures.group(1))
    assert len(rows) == len(hostile_report.failures()) == 2
    for result, row in zip(hostile_report.failures(), rows, strict=True):
        name, tool, verdict, what = _cells(row)
        assert _code_text(name) == printable(result.fastener.name)
        assert verdict == result.verdict.value
        if result.tool:
            assert _code_text(tool) == result.tool
        if result.reason:
            assert _code_text(what) == printable(result.reason)
        else:
            spans = re.findall(r"<code>(.*?)</code>", what, re.S)
            assert [html.unescape(s) for s in spans] == [printable(b) for b in result.blockers]


def test_the_blocked_bolt_names_the_wall_and_the_box_gives_its_reason(hostile_report):
    by_name = {r.fastener.name: r for r in hostile_report.results}
    assert by_name[BOLT].verdict == "blocked"
    assert by_name[BOLT].blockers == (WALL,)
    slab = next(r for name, r in by_name.items() if name.startswith("slab_screw"))
    assert slab.verdict == "not-covered"
    assert "no cylindrical face" in (slab.reason or "")


def test_warnings_are_listed_with_their_globs_shown_exactly(hostile_report):
    text = hostile_report.markdown()
    rendered = GFM.render(text)
    items = re.search(r"<h4>Warnings</h4>\s*<ul>(.*?)</ul>", rendered, re.S)
    assert items is not None
    lines = re.findall(r"<li>(.*?)</li>", items.group(1), re.S)
    assert len(lines) == 3
    assert lines[0] == "rule matched nothing: <code>no_such_part_*</code> (renamed part?)"
    assert lines[1] == "ignore matched nothing: <code>no_such_hose_[x]*</code>"
    assert html.unescape(lines[2]) == (
        "<code>forced pair [bolt*, ghost www.evil.example] names no fastener: "
        "bolt*, ghost www.evil.example</code>"
    )


def test_markdown_says_what_the_terminal_says(hostile_report):
    """Same summary, same groups, same failures, same warnings, in the same order."""
    terminal = hostile_report.terminal_lines()
    rendered = GFM.render(hostile_report.markdown())
    summary = re.search(r"<p><strong>(.*?)</strong></p>", rendered)
    assert summary is not None
    assert summary.group(1) == terminal[0]
    tables = re.findall(r"<table>(.*?)</table>", rendered, re.S)
    groups = [_cells(row) for row in _body_rows(tables[0])]
    group_lines = [line for line in terminal[1:] if line.startswith("  ")]
    assert len(groups) == len(group_lines)
    for (what, tool, count, outcome), line in zip(groups, group_lines, strict=True):
        tool_text = _code_text(tool) if tool != "-" else "-"
        assert line.split() == [*what.split(), tool_text, f"x{count}", *outcome.split()]
    fail_lines = [line for line in terminal if line.startswith("FAIL ")]
    fail_rows = [_cells(row) for row in _body_rows(tables[1])]
    assert len(fail_rows) == len(fail_lines)
    for (name, tool, verdict, _), line in zip(fail_rows, fail_lines, strict=True):
        tool_text = _code_text(tool) if tool != "-" else "-"
        assert line.startswith(f"FAIL {_code_text(name)}  {tool_text}  {verdict}  ")
    assert sum(line.startswith("WARN ") for line in terminal) == 3


def test_a_passing_report_has_no_failures_or_warnings_sections():
    report = check(
        screw_facing_wall(40.0),
        Config.from_dict({"fasteners": [SIDECAR["fasteners"][0] | {"parts": "bolt"}]}),
        model="ok.step",
        engine="exact",
    )
    assert report.exit_code == 0
    text = report.markdown()
    assert "#### Failures" not in text
    assert "#### Warnings" not in text
    assert text.startswith("### wrenchroom: `ok.step`\n\n**1 fasteners: 1 turn, 0 held")
    rendered = GFM.render(text)
    (row,) = _body_rows(rendered)
    assert _cells(row) == [
        "M6 socket screw",
        "<code>hex-key-5</code>",
        "1",
        "all pass (short leg in)",
    ]


def test_an_empty_report_is_just_its_summary():
    no_fasteners = Config.from_dict({"checks": {"detect": False}})
    report = check(screw_facing_wall(40.0), no_fasteners, engine="exact")
    assert report.summary["fasteners"] == 0
    lines = report.markdown().splitlines()
    assert lines[:4] == [
        "### wrenchroom",
        "",
        "**0 fasteners: 0 turn, 0 held, 0 blocked, 0 stuck, 0 not covered**",
        "",
    ]
    assert len(lines) == 7
    assert lines[4].startswith("Kit `metric-home`, exact engine, wrenchroom ")
    assert lines[6] == (
        "Not checked: room for a hand (`checks: {hand_room: true}` turns it on); "
        "parts drawn into each other (`checks: {clashes: true}` turns it on); "
        "parts the model doesn't have."
    )
    assert "<table>" not in GFM.render(report.markdown())


def test_a_failure_with_no_blocker_and_no_reason_says_no_tool_found(hostile_report):
    from dataclasses import replace  # noqa: PLC0415

    (blocked,) = [r for r in hostile_report.results if r.verdict == "blocked"]
    bare = replace(hostile_report, results=(replace(blocked, blockers=()),))
    (row,) = _body_rows(re.findall(r"<table>(.*?)</table>", GFM.render(bare.markdown()), re.S)[1])
    assert _cells(row)[3] == NO_TOOL


# ---------------------------------------------------------------------------
# The CLI: --md writes the same report beside the terminal one.
# ---------------------------------------------------------------------------


@pytest.fixture
def hostile_step(tmp_path):
    shapes = []
    for part in hostile_model():
        part.shape.label = part.name
        shapes.append(part.shape)
    export_step(Compound(children=shapes), str(tmp_path / "model.step"))
    sidecar = {key: SIDECAR[key] for key in ("fasteners", "ignore")}
    (tmp_path / "wrenchroom.yaml").write_text(json.dumps(sidecar))  # JSON is YAML
    return tmp_path / "model.step"


def test_check_md_writes_the_report_and_keeps_the_exit_code(hostile_step, tmp_path):
    md_path = tmp_path / "report.md"
    result = CliRunner().invoke(main, ["check", str(hostile_step), "--md", str(md_path)])
    assert result.exit_code == 2  # a rule matched nothing, and the box is not covered
    text = md_path.read_text()
    assert not any(UNSAFE.search(line) for line in text.splitlines())
    assert text.startswith("### wrenchroom: `model.step`\n")
    rendered = GFM.render(text)
    _assert_report_structure(rendered, warnings=2, tools_apart=2)  # no tool yet; once reached
    summary = re.search(r"<p><strong>(.*?)</strong></p>", rendered)
    assert summary is not None
    assert summary.group(1) == result.output.splitlines()[0]


def test_check_md_is_offered():
    result = CliRunner().invoke(main, ["check", "--help"])
    assert "--md" in result.output
