"""Verdicts and the report: what happened, for people and for machines.

The verdict vocabulary is fixed by the spec and all five values exist from M1 even
though two (`held` beyond carriage bolts, `stuck`) only start appearing with M2's
pairs and extraction: the JSON contract should not grow new enum values release by
release.

Exit codes are the report's, not the CLI's: 0 everything passes, 1 a fastener
fails, 2 something not covered or a config problem (which includes a sidecar rule
that matched nothing, because that is how a renamed part hides).
"""

from __future__ import annotations

import enum
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from wrenchroom import __version__
from wrenchroom.fasteners import Fastener, PassedOver
from wrenchroom.terminal import printable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from wrenchroom.assembly import Assembly
    from wrenchroom.tools.sweep import Attempt, Probe


class Verdict(enum.StrEnum):
    """Per fastener: how it fared."""

    TURNS = "turns"
    HELD = "held"
    BLOCKED = "blocked"
    STUCK = "stuck"
    NOT_COVERED = "not-covered"


#: Verdicts that pass on their own. `held` passes only through its pair partner
#: from M2; a carriage bolt holds itself and passes alone.
PASSING = frozenset({Verdict.TURNS, Verdict.HELD})


@dataclass(frozen=True)
class FastenerResult:
    """One fastener's outcome, with every attempt kept for `explain`."""

    fastener: Fastener
    verdict: Verdict
    tool: str | None = None
    how: str | None = None
    swing_deg: float = 0.0
    blockers: tuple[str, ...] = ()
    stuck_on: tuple[str, ...] = ()
    attempts: tuple[Attempt, ...] = ()
    #: A screw's way out as tested, when extraction was checked: the head's
    #: circle swept its length, and what stood in it.
    way_out: Probe | None = None
    reason: str | None = None
    axis: tuple[float, float, float] | None = None
    seat: tuple[float, float, float] | None = None
    state: str | None = None
    pair: str | None = None
    #: What the attempt that decided the verdict only grazed: overlapped by no
    #: more than the hit floor, a tool rubbing along a face (issue #25).
    grazes: tuple[str, ...] = ()
    #: Caveats on how the verdict was reached, for a person to weigh: a hex drawn
    #: under its standard, a size taken from the bolt (issue #50).
    notes: tuple[str, ...] = ()
    #: Of the blockers, the parts that decided a blocked verdict: those at each
    #: end of the best arc any tool found (issue #52). ``blockers`` leads with them.
    deciding: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        """True when this fastener needs nothing further."""
        return self.verdict in PASSING

    @property
    def name(self) -> str:
        """The fastener's part name, as the JSON's ``name``."""
        return self.fastener.name

    @property
    def blocked_by(self) -> tuple[str, ...]:
        """What the tools ran into, as the JSON's ``blocked_by``."""
        return self.blockers

    @property
    def headline(self) -> str:
        """The verdict in a line, as ``explain`` opens: tool and way, state, partner."""
        header = f"{self.fastener.name}: {self.verdict}"
        if self.tool:
            header += f" with {self.tool}" + (f", {self.how}" if self.how else "")
        if self.state:
            header += f" (in state {self.state})"
        if self.pair:
            header += f"; paired with {self.pair}"
        if self.grazes:
            header += f"; grazing {', '.join(self.grazes)}"
        return header


def attempt_text(attempt: Attempt) -> str:
    """One attempt in a line, as ``explain`` lists them: tool, way, outcome, what it hit."""
    outcome = "turns" if attempt.turns else ("holds" if attempt.holds else "blocked")
    if attempt.no_hand_room:
        outcome += " (no room for a hand)"
    line = f"{attempt.tool}, {attempt.way}: {outcome}"
    if attempt.holds and not attempt.turns and attempt.required_deg:
        line += (
            f", best {attempt.swing_deg:g} of {attempt.required_deg:g} deg"
            if attempt.swing_deg
            else f", at one angle only ({attempt.required_deg:g} deg needed)"
        )
    elif attempt.swing_deg and not attempt.turns:
        line += f", swing {attempt.swing_deg:g} deg"
    if attempt.no_hand_room:  # the bounds are the hand's: say so, if they narrow it
        if attempt.bounds and set(attempt.bounds) != set(attempt.hand_blockers):
            line += f", the hand stopped by {', '.join(attempt.bounds)} on its best arc"
    elif attempt.bounds:
        line += f", {bounded(attempt.bounds)}"
    if attempt.blockers:
        line += f"; hit {', '.join(attempt.blockers)}"
    if attempt.hand_blockers:
        line += f"; the hand hit {', '.join(attempt.hand_blockers)}"
    if attempt.grazes and (attempt.turns or attempt.holds):
        line += f"; grazed {', '.join(attempt.grazes)}"
    return line


@dataclass(frozen=True)
class StateModel:
    """The model as one state shows it: the assembly the check read, less what it took off."""

    assembly: Assembly
    removed: frozenset[str] = frozenset()

    @property
    def names(self) -> tuple[str, ...]:
        """The parts present in this state, in assembly order."""
        return tuple(name for name in self.assembly.names if name not in self.removed)


@dataclass(frozen=True)
class Report:
    """A whole run: results plus the sidecar's unmatched globs."""

    model: str
    kit: str
    results: tuple[FastenerResult, ...]
    #: The collision engine that answered: ``mesh`` by default, ``exact`` under
    #: ``--exact``. Recorded so a report says how it was computed.
    engine: str = "mesh"
    unmatched_rules: tuple[str, ...] = ()
    unmatched_ignores: tuple[str, ...] = ()
    #: Config-grade problems found while checking (a forced pair naming nothing,
    #: a state's remove glob matching nothing): reported, and the run exits 2.
    warnings: tuple[str, ...] = ()
    #: The state the run took as normal: ``--state``, else the sidecar's
    #: ``default_state``, else None (the model as given).
    default_state: str | None = None
    #: The geometry the run read, for the HTML view: the model as given (key
    #: None) and every state it resolved. Not part of the JSON, and not compared.
    models: Mapping[str | None, StateModel] = field(default_factory=dict, compare=False, repr=False)
    #: Every part the sidecar's ignore list takes out of the way (wires, hoses).
    ignored: frozenset[str] = field(default=frozenset(), compare=False, repr=False)
    #: Whether room for a hand round each handle was checked (spec 6.4).
    hand_room: bool = False
    #: Parts named like fasteners that detection didn't take (issue #30): a
    #: fastener noun with ordinary words after it, and no drive in the solid.
    #: Not failures, but every report lists them, so none goes unsaid.
    passed_over: tuple[PassedOver, ...] = ()

    @property
    def not_checked(self) -> str:
        """What the run could not see, said in every report (the prototype's lesson)."""
        unseen = ["parts the model doesn't have"]
        if self.passed_over:
            unseen.insert(0, _passed_over_count(self.passed_over))
        if not self.hand_room:
            unseen.insert(0, "room for a hand (checks: {hand_room: true} turns it on)")
        return "not checked: " + "; ".join(unseen)

    def failures(self) -> tuple[FastenerResult, ...]:
        """Everything that did not pass, worst first (not-covered last)."""
        failed = [r for r in self.results if not r.passed]
        order = {Verdict.BLOCKED: 0, Verdict.STUCK: 1, Verdict.NOT_COVERED: 2}
        return tuple(sorted(failed, key=lambda r: (order[r.verdict], r.fastener.name)))

    @property
    def summary(self) -> dict[str, int]:
        """The counts the summary line and the JSON share."""
        counts = {
            "fasteners": len(self.results),
            "turns": 0,
            "held": 0,
            "blocked": 0,
            "stuck": 0,
            "not_covered": 0,
        }
        for result in self.results:
            counts[result.verdict.value.replace("-", "_")] += 1
        return counts

    @property
    def exit_code(self) -> int:
        """0 all pass; 1 a fastener fails; 2 not covered or a config problem."""
        askew = self.unmatched_rules or self.unmatched_ignores or self.warnings
        if self.summary["not_covered"] or askew:
            return 2
        if self.summary["blocked"] or self.summary["stuck"]:
            return 1
        return 0

    def assert_all_pass(self) -> None:
        """Pass when ``wrenchroom check`` would exit 0; else fail saying why.

        "All pass" is the CLI's exit code 0: every fastener turns or is held,
        none is not covered, and the sidecar matched cleanly. The pytest
        plugin's fixture is a Report, so this is its assertion.

        Raises:
            AssertionError: With the summary line and every FAIL and WARN line,
                as ``wrenchroom check`` prints them (names made safe to print).
        """
        if self.exit_code == 0:
            return
        lines = self.terminal_lines()
        problems = [lines[0], *(line for line in lines if line.startswith(("FAIL ", "WARN ")))]
        raise AssertionError("\n".join(problems))

    # ------------------------------------------------------------------ JSON

    def to_json_dict(self) -> dict[str, object]:
        """The spec's JSON document."""
        return {
            # The schema number is the private-run contract (bench handoff section
            # 9): owners pin a wrenchroom version and diff reports over time, so
            # any breaking change to this document bumps it, with a changelog line.
            "schema": 1,
            "model": self.model,
            "kit": self.kit,
            "engine": self.engine,
            "tool_version": __version__,
            "summary": self.summary,
            "unmatched_rules": list(self.unmatched_rules),
            "unmatched_ignores": list(self.unmatched_ignores),
            "warnings": list(self.warnings),
            "hand_room": self.hand_room,
            "passed_over": [
                {"name": part.name, "kind": part.kind.value, "reason": part.reason}
                for part in self.passed_over
            ],
            "fasteners": [_result_json(result) for result in self.results],
        }

    def json_text(self) -> str:
        """The JSON document as text, as :meth:`to_json` writes it."""
        return json.dumps(self.to_json_dict(), indent=2) + "\n"

    def to_json(self, path: str | Path) -> None:
        """Write the JSON document to a file."""
        Path(path).write_text(self.json_text(), encoding="utf-8")

    # -------------------------------------------------------------- terminal

    def terminal_lines(self) -> list[str]:
        """The human output: summary, a table by type, a line per failure.

        Safe to print as it stands: names come from the model, so every line is
        passed through :func:`wrenchroom.terminal.printable` and none of them can
        steer a terminal or break into a second line.
        """
        lines = [_summary_text(self.summary)]
        lines.extend(
            f"  {group.what:24} {group.tool or '-':14} x{group.count:<4} {group.outcome}"
            for group in _groups(self.results)
        )
        for result in self.failures():
            names, reason = _why(result)
            what = reason or listed(names, result.attempts) or NO_TOOL
            tool = result.tool or "-"
            lines.append(f"FAIL {result.fastener.name}  {tool}  {result.verdict}  {what}")
        for glob in self.unmatched_rules:
            lines.append(f"WARN rule matched nothing: {glob!r} (renamed part?)")
        for glob in self.unmatched_ignores:
            lines.append(f"WARN ignore matched nothing: {glob!r}")
        lines.extend(f"WARN {warning}" for warning in self.warnings)
        shown = self.passed_over[:PASSED_OVER_SHOWN]
        lines.extend(f"NOTE passed over {part.name}: {part.reason}" for part in shown)
        if len(self.passed_over) > len(shown):
            more = len(self.passed_over) - len(shown)
            lines.append(f"NOTE and {more} more passed over (the JSON lists every one)")
        marginal = self.marginal()
        lines.extend(f"NOTE marginal: {_marginal_text(r)}" for r in marginal[:PASSED_OVER_SHOWN])
        if len(marginal) > PASSED_OVER_SHOWN:
            more = len(marginal) - PASSED_OVER_SHOWN
            lines.append(f"NOTE and {more} more marginal (the JSON lists every one)")
        noted = self.noted()
        lines.extend(f"NOTE {name}: {note}" for name, note in noted[:PASSED_OVER_SHOWN])
        if len(noted) > PASSED_OVER_SHOWN:
            more = len(noted) - PASSED_OVER_SHOWN
            lines.append(f"NOTE and {more} more (the JSON lists every note)")
        lines.append(f"NOTE {self.not_checked}")
        return [printable(line) for line in lines]

    def noted(self) -> tuple[tuple[str, str], ...]:
        """Every result's caveats, as (fastener, note), in result order."""
        return tuple((r.fastener.name, note) for r in self.results for note in r.notes)

    def marginal(self) -> tuple[FastenerResult, ...]:
        """The results whose deciding tool only grazed something: a verdict on a graze."""
        return tuple(result for result in self.results if result.grazes)

    # -------------------------------------------------------------- Markdown

    def markdown(self) -> str:
        """The terminal report as Markdown, for a CI job summary or a PR comment.

        The same content as :meth:`terminal_lines`: the summary, the table by
        type, the failures and the warnings. Names come from the model and a
        comment renders them, so every name is shown in a code span, where no
        link, image, emphasis or HTML can start, after :func:`printable` has
        written out anything that could steer a terminal; inside a table a pipe
        is escaped so a name can't split its cell. Text that names nothing from
        the model (kinds, sizes, ways) is backslash-escaped instead.
        """
        title = f"wrenchroom: {md_code(self.model, in_table=False)}" if self.model else "wrenchroom"
        lines = [
            f"### {title}",
            "",
            f"**{_summary_text(self.summary)}**",
            "",
            f"Kit {md_code(self.kit, in_table=False)}, {md_text(self.engine)} engine, "
            f"wrenchroom {md_text(__version__)}.",
            "",
            "Not checked: "
            + (
                ""
                if self.hand_room
                else "room for a hand (`checks: {hand_room: true}` turns it on); "
            )
            + (f"{md_text(_passed_over_count(self.passed_over))}; " if self.passed_over else "")
            + "parts the model doesn't have.",
        ]
        groups = _groups(self.results)
        if groups:
            lines += ["", "| Fasteners | Tool | Count | Outcome |", "| --- | --- | ---: | --- |"]
            lines.extend(
                f"| {md_text(group.what)} | {_md_tool(group.tool)} | {group.count} "
                f"| {md_text(group.outcome)} |"
                for group in groups
            )
        failures = self.failures()
        if failures:
            lines += [
                "",
                "#### Failures",
                "",
                "| Fastener | Tool | Verdict | In the way, or why |",
                "| --- | --- | --- | --- |",
            ]
            for result in failures:
                names, reason = _why(result)
                shown, more = shortlist(names, result.attempts)
                what = (
                    md_code(reason)
                    if reason
                    else ", ".join(md_code(name) for name in shown) + md_text(_more(more))
                    or NO_TOOL
                )
                lines.append(
                    f"| {md_code(result.fastener.name)} | {_md_tool(result.tool)} "
                    f"| {result.verdict} | {what} |"
                )
        warnings = [
            *(
                f"rule matched nothing: {md_code(glob, in_table=False)} (renamed part?)"
                for glob in self.unmatched_rules
            ),
            *(
                f"ignore matched nothing: {md_code(glob, in_table=False)}"
                for glob in self.unmatched_ignores
            ),
            *(md_code(warning, in_table=False) for warning in self.warnings),
        ]
        if warnings:
            lines += ["", "#### Warnings", ""]
            lines.extend(f"- {warning}" for warning in warnings)
        lines += _md_list(
            "Notes",
            [f"{md_code(name, in_table=False)}: {md_text(note)}" for name, note in self.noted()],
        )
        lines += _md_list(
            "Marginal",
            [
                f"{md_code(r.fastener.name, in_table=False)}: {r.verdict} with "
                f"{_md_tool(r.tool)}, grazing "
                + ", ".join(md_code(name, in_table=False) for name in r.grazes)
                for r in self.marginal()
            ],
        )
        lines += _md_list(
            "Passed over",
            [
                f"{md_code(part.name, in_table=False)}: {md_text(part.reason)}"
                for part in self.passed_over
            ],
        )
        return "\n".join(lines) + "\n"

    def to_markdown(self, path: str | Path) -> None:
        """Write the Markdown report to a file, as UTF-8 whatever the locale."""
        Path(path).write_text(self.markdown(), encoding="utf-8")

    # ------------------------------------------------------------------ HTML

    def to_html(self, path: str | Path, *, select: str | None = None) -> None:
        """Write the self-contained 3D view: see :mod:`wrenchroom.view`.

        Args:
            path: The file to write.
            select: A fastener to show selected when the file opens, as
                ``explain --html`` does.

        Raises:
            ValueError: When the report carries no geometry (it wasn't made by
                ``check``), or ``select`` names no fastener in it.
        """
        from wrenchroom.view import write_html  # noqa: PLC0415  (pulls the mesh engine)

        write_html(self, path, select=select)


def _result_json(result: FastenerResult) -> dict[str, object]:
    fastener = result.fastener
    return {
        "name": fastener.name,
        "kind": fastener.kind.value,
        "head": fastener.head.value if fastener.head else None,
        "size": fastener.size.designation if fastener.size else None,
        "length": fastener.length_mm,
        "axis": list(result.axis) if result.axis else None,
        "seat": list(result.seat) if result.seat else None,
        "source": fastener.source,
        "tool": result.tool,
        "verdict": result.verdict.value,
        "how": result.how,
        "swing_deg": result.swing_deg,
        "state": result.state,
        "pair": result.pair,
        "blocked_by": list(result.blockers),
        "deciding": list(result.deciding),
        "stuck_on": list(result.stuck_on),
        "reason": result.reason,
        "grazes": list(result.grazes),
        "notes": list(result.notes),
    }


#: What a failure says when nothing was in the way and nothing explains it.
NO_TOOL = "no tool found"

#: How many passed-over parts the terminal and Markdown name; the JSON has all.
PASSED_OVER_SHOWN = 10


def _md_list(heading: str, items: list[str]) -> list[str]:
    """A capped Markdown list under its heading, or nothing when there is nothing."""
    if not items:
        return []
    lines = ["", f"#### {heading}", ""]
    lines.extend(f"- {item}" for item in items[:PASSED_OVER_SHOWN])
    if len(items) > PASSED_OVER_SHOWN:
        lines.append(f"- and {len(items) - PASSED_OVER_SHOWN} more (the JSON lists every one)")
    return lines


def _marginal_text(result: FastenerResult) -> str:
    """A verdict decided by a graze, in a line: the tool only rubbing what it names."""
    tool = f" with {result.tool}" if result.tool else ""
    grazed = ", ".join(result.grazes)
    return f"{result.fastener.name} {result.verdict}{tool}, the tool grazing {grazed}"


def _passed_over_count(passed: tuple[PassedOver, ...]) -> str:
    noun = "part" if len(passed) == 1 else "parts"
    return f"{len(passed)} {noun} named like a fastener, with no drive in the solid (passed over)"


def _summary_text(counts: dict[str, int]) -> str:
    return (
        f"{counts['fasteners']} fasteners: {counts['turns']} turn, "
        f"{counts['held']} held, {counts['blocked']} blocked, "
        f"{counts['stuck']} stuck, {counts['not_covered']} not covered"
    )


#: How many parts a FAIL line or a reason names before "and N more": the JSON's
#: blocked_by and deciding, explain and the HTML view have every one (issue #64).
NAMES_SHOWN = 3


def shortlist(
    names: tuple[str, ...], attempts: tuple[Attempt, ...] = ()
) -> tuple[tuple[str, ...], int]:
    """At most :data:`NAMES_SHOWN` of ``names``, and how many more there are.

    The part hit at the most probed positions comes first, then first-seen
    order: the part most in the way, not the first one any probe touched.
    """
    hits = Counter(name for attempt in attempts for probe in attempt.probes for name in probe.hits)
    ordered = sorted(names, key=lambda name: -hits[name])
    return tuple(ordered[:NAMES_SHOWN]), max(0, len(ordered) - NAMES_SHOWN)


def listed(names: tuple[str, ...], attempts: tuple[Attempt, ...] = ()) -> str:
    """``a, b, c and 4 more``: :func:`shortlist`'s, as a line says it."""
    shown, more = shortlist(names, attempts)
    return ", ".join(shown) + _more(more)


def bounded(bounds: tuple[str, ...], attempts: tuple[Attempt, ...] = ()) -> str:
    """``between a and b``, or ``bounded by a`` (one part both sides), or by several."""
    if len(bounds) == 2:  # noqa: PLR2004  (one each side)
        return f"between {bounds[0]} and {bounds[1]}"
    return f"bounded by {listed(bounds, attempts)}"


def _more(count: int) -> str:
    return f" and {count} more" if count else ""


def _why(result: FastenerResult) -> tuple[tuple[str, ...], str | None]:
    """What a failure ran into (stuck: what's in its way out), or the reason it has.

    A fastener with deciding parts always has a reason too (a tool that holds, or
    a hand that can't follow it), and the line adds them to it (issue #52).
    """
    names = result.stuck_on if result.verdict is Verdict.STUCK else result.blockers
    return names, result.reason


def _describe(fastener: Fastener) -> str:
    """The table's "what": ``M8 hex screw``; with no size, the hex it was measured by.

    A gland found by its name has no size by design (its thread says nothing of
    the hex a spanner grips), so it is ``24 AF gland``, not ``? nut`` (issue #33).
    """
    kind = fastener.kind.value
    if fastener.size is not None:
        size = fastener.size.designation
    elif fastener.drive_af is not None:
        size = f"{fastener.drive_af:g} AF"
        kind = kind if fastener.socket_allowed else "gland"
    else:
        size = "?"
    bits = [size]
    if fastener.head:
        bits.append(fastener.head.value)
    bits.append(kind)
    return " ".join(bits)


@dataclass(frozen=True)
class _Group:
    """One row of the table by type: what, the tool, how many, how they fared."""

    what: str
    tool: str | None
    count: int
    outcome: str


def _groups(results: tuple[FastenerResult, ...]) -> list[_Group]:
    groups: dict[tuple[str, str], list[FastenerResult]] = {}
    for result in results:
        key = (_describe(result.fastener), result.tool or "")
        groups.setdefault(key, []).append(result)
    rows = []
    for (what, tool), members in sorted(groups.items()):
        failed = [m for m in members if not m.passed]
        if failed:
            outcome = f"{len(failed)} of {len(members)} fail"
        else:
            ways = {m.how for m in members if m.how}
            hardest = max(ways, default="", key=len)
            outcome = f"all pass ({hardest})" if hardest else "all pass"
        rows.append(_Group(what, tool or None, len(members), outcome))
    return rows


# ---------------------------------------------------------------------------
# Markdown escaping: what a GitHub comment renders can't be steered by a name.
# ---------------------------------------------------------------------------

#: The characters that can open something in CommonMark or GFM inline text: an
#: escape, code, emphasis, strikethrough, a link or image, HTML, an entity, a cell
#: boundary. Each is one CommonMark lets a backslash escape.
_MD_SPECIAL = re.compile(r"([\\`*_~\[\]!<>&|])")


def md_text(text: str) -> str:
    """Plain text for Markdown: every character that could open something escaped.

    For text wrenchroom writes itself (kinds, sizes, ways, counts), placed
    mid-line, where nothing should be read as Markdown. A name from the model
    goes through :func:`md_code` instead: escaping alone doesn't stop a GitHub
    comment from turning ``www.example.com`` into a link.
    """
    return _MD_SPECIAL.sub(r"\\\1", printable(text))


def md_code(text: str, *, in_table: bool = True) -> str:
    r"""Text shown exactly, in a code span: how every name from the model is written.

    Nothing inside a code span is Markdown, so no link, image, emphasis or HTML
    can start there. The fence is one backtick longer than the longest run in
    the text, so the text can't close it; the text is padded with a space when
    an edge would otherwise be misread (a backtick against the fence, or a space
    at both ends, which a renderer strips). In a table a pipe is escaped as
    ``\|``, which GitHub turns back into a pipe inside the span, so a name can't
    split its cell.
    """
    shown = printable(text)
    if not shown:
        return '""'
    longest = max((len(run) for run in re.findall("`+", shown)), default=0)
    fence = "`" * (longest + 1)
    edges = shown[0] + shown[-1]
    if "`" in edges or (shown[0] == " " and shown[-1] == " " and shown.strip(" ")):
        shown = f" {shown} "
    if in_table:
        shown = shown.replace("|", "\\|")
    return f"{fence}{shown}{fence}"


def _md_tool(tool: str | None) -> str:
    return md_code(tool) if tool else "-"
