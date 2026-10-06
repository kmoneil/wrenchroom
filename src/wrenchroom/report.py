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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from wrenchroom import __version__
from wrenchroom.fasteners import Fastener

if TYPE_CHECKING:
    from wrenchroom.tools.sweep import Attempt


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
    attempts: tuple[Attempt, ...] = ()
    reason: str | None = None
    axis: tuple[float, float, float] | None = None
    seat: tuple[float, float, float] | None = None

    @property
    def passed(self) -> bool:
        """True when this fastener needs nothing further."""
        return self.verdict in PASSING


@dataclass(frozen=True)
class Report:
    """A whole run: results plus the sidecar's unmatched globs."""

    model: str
    kit: str
    results: tuple[FastenerResult, ...]
    unmatched_rules: tuple[str, ...] = ()
    unmatched_ignores: tuple[str, ...] = ()

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
        if self.summary["not_covered"] or self.unmatched_rules or self.unmatched_ignores:
            return 2
        if self.summary["blocked"] or self.summary["stuck"]:
            return 1
        return 0

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
            "tool_version": __version__,
            "summary": self.summary,
            "unmatched_rules": list(self.unmatched_rules),
            "unmatched_ignores": list(self.unmatched_ignores),
            "fasteners": [_result_json(result) for result in self.results],
        }

    def to_json(self, path: str | Path) -> None:
        """Write the JSON document to a file."""
        Path(path).write_text(json.dumps(self.to_json_dict(), indent=2) + "\n")

    # -------------------------------------------------------------- terminal

    def terminal_lines(self) -> list[str]:
        """The human output: summary, a table by type, a line per failure."""
        counts = self.summary
        lines = [
            f"{counts['fasteners']} fasteners: {counts['turns']} turn, "
            f"{counts['held']} held, {counts['blocked']} blocked, "
            f"{counts['stuck']} stuck, {counts['not_covered']} not covered"
        ]
        lines.extend(_group_table(self.results))
        for result in self.failures():
            what = result.reason or ", ".join(result.blockers) or "no tool found"
            tool = result.tool or "-"
            lines.append(f"FAIL {result.fastener.name}  {tool}  {result.verdict}  {what}")
        for glob in self.unmatched_rules:
            lines.append(f"WARN rule matched nothing: {glob!r} (renamed part?)")
        for glob in self.unmatched_ignores:
            lines.append(f"WARN ignore matched nothing: {glob!r}")
        return lines


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
        "source": "sidecar",
        "tool": result.tool,
        "verdict": result.verdict.value,
        "how": result.how,
        "swing_deg": result.swing_deg,
        "state": None,
        "pair": None,
        "blocked_by": list(result.blockers),
        "stuck_on": [],
        "reason": result.reason,
    }


def _describe(fastener: Fastener) -> str:
    bits = [fastener.size.designation if fastener.size else "?"]
    if fastener.head:
        bits.append(fastener.head.value)
    bits.append(fastener.kind.value)
    return " ".join(bits)


def _group_table(results: tuple[FastenerResult, ...]) -> list[str]:
    groups: dict[tuple[str, str], list[FastenerResult]] = {}
    for result in results:
        key = (_describe(result.fastener), result.tool or "-")
        groups.setdefault(key, []).append(result)
    lines = []
    for (what, tool), members in sorted(groups.items()):
        failed = [m for m in members if not m.passed]
        if failed:
            outcome = f"{len(failed)} of {len(members)} fail"
        else:
            ways = {m.how for m in members if m.how}
            hardest = max(ways, default="", key=len)
            outcome = f"all pass ({hardest})" if hardest else "all pass"
        lines.append(f"  {what:24} {tool:14} x{len(members):<4} {outcome}")
    return lines
