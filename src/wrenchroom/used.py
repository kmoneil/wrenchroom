"""The tools a model needs: each tool the check found a fastener turned or held with.

Every check records the tool each fastener ended up needing; this lists them, one
line per tool, with how many fasteners need it and whether the default kit holds
it. A tool is **unusual** by definition, not by guess, and an unusual line names
its fasteners:

- the default kit (:data:`~wrenchroom.tools.kits.DEFAULT_KIT`) doesn't hold it;
- only one or two fasteners need it (:data:`FEW`);
- it is the only way one is reached where the kit's ordinary tool can't: a ball end,
  where no straight key gets in, or a stubby, where a full-length spanner can't swing.

A stubby spanner is its own line, the tool a person reaches for. A held fastener
counts its holding tool, and a joint whose bolt and nut take the same tool needs two
of it at once, which the line says. A fastener turned by hand, or held by itself or
its trap, needs no tool; a blocked or not-covered one has none yet. Each is counted
apart, so every fastener is in the list somewhere.

A blocked fastener is often blocked only as the model stands, before anything comes
off, and its tool is known: the tools blocked fasteners would need once reached are
listed apart (issue #136), not counted as reached, and one that only they need is
said, so a person packing from the list has it. A not-covered one has no tool to name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from wrenchroom.report import Verdict, listed, md_code, md_text, shortlist
from wrenchroom.tools.fingers import HAND
from wrenchroom.tools.kits import DEFAULT_KIT, kit_named
from wrenchroom.tools.sizes import size_mm

if TYPE_CHECKING:
    from collections.abc import Callable

    from wrenchroom.report import FastenerResult, Report

#: A tool so few fasteners need is worth knowing about: one or two.
FEW = 2

#: How a stubby spanner's way reads in a result.
STUBBY = "stubby"

#: The families in the order a person would lay them out, and how a count says each.
_FAMILIES = (
    ("hex-key", "hex key", "hex keys"),
    ("ball-end-key", "ball-end key", "ball-end keys"),
    ("torx-key", "Torx key", "Torx keys"),
    ("spanner", "spanner", "spanners"),
    ("socket", "socket", "sockets"),
    ("nut-driver", "nut driver", "nut drivers"),
    ("driver", "driver", "drivers"),
)

#: A verdict whose tool turns or holds the fastener: a stuck one turns, and only its
#: way out is in the way, so it needs its tool as much as any.
_WITH_A_TOOL = (Verdict.TURNS, Verdict.HELD, Verdict.STUCK)


@dataclass(frozen=True)
class ToolUse:
    """One tool the model needs, and every fastener that needs it.

    Attributes:
        tool: Its name as a report gives it (``spanner-13``); a stubby spanner's
            with ``, stubby``.
        fasteners: The fasteners turned or held with it, in report order.
        at_once: The most of it one joint needs at the same time: 2 where a bolt
            and its nut both take it, else 1.
        in_default_kit: Whether the default kit holds it.
        only_way: The fasteners it alone reaches: a ball end's, a stubby's.
        states: The states its fasteners are reached in; None is the model as given.
    """

    tool: str
    fasteners: tuple[str, ...]
    at_once: int
    in_default_kit: bool
    only_way: tuple[str, ...] = ()
    states: tuple[str | None, ...] = (None,)

    @property
    def unusual(self) -> tuple[str, ...]:
        """Why a person should know about it, as the JSON's codes; empty if ordinary.

        ``outside_default_kit``; ``only_way``, the only tool reaching some fastener;
        ``few``, one or two fasteners need it (said only where ``only_way`` isn't,
        which names its fasteners already).
        """
        why = []
        if not self.in_default_kit:
            why.append("outside_default_kit")
        if self.only_way:
            why.append("only_way")
        elif len(self.fasteners) <= FEW:
            why.append("few")
        return tuple(why)

    def said(self, names: Callable[[tuple[str, ...]], str] = listed) -> tuple[str, ...]:
        """What its line says after the count, each a short clause.

        Why it is unusual, its fasteners named through ``names`` (code spans in
        Markdown), and how many of it a joint needs at once.
        """
        why = []
        if "outside_default_kit" in self.unusual:
            why.append(f"not in {DEFAULT_KIT}")
        if self.only_way:
            ball = _family(self.tool) == "ball-end-key"
            reach = "no straight key gets in" if ball else "no full-length spanner swings"
            why.append(f"{reach} at {names(self.only_way)}")
        elif "few" in self.unusual:
            why.append(f"only {names(self.fasteners)}")
        if self.at_once > 1:
            why.append(f"{self.at_once} at once on a joint")
        return tuple(why)


@dataclass(frozen=True)
class ToolsUsed:
    """The tools a checked model needs, and the fasteners that need none or have none.

    Attributes:
        kit: The kit the check ran with.
        uses: One per tool, family by family, smallest first.
        by_hand: Fasteners turned by hand (``tool: hand``).
        no_tool: Fasteners held by themselves or their traps.
        without: Fasteners with no tool yet: blocked or not covered, by name, with
            their verdicts.
        blocked: The tools blocked fasteners would need once reached, each with its
            fasteners, family by family, smallest first (issue #136).
    """

    kit: str
    uses: tuple[ToolUse, ...]
    by_hand: tuple[str, ...] = ()
    no_tool: tuple[str, ...] = ()
    without: tuple[tuple[str, Verdict], ...] = ()
    blocked: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def families(self) -> str:
        """``3 hex keys, 2 spanners, 1 driver``: how many of each family, in order."""
        counts: dict[str, int] = {}
        for use in self.uses:
            family = _family(use.tool)
            counts[family] = counts.get(family, 0) + 1
        said = []
        for family, one, many in (*_FAMILIES, ("", "other", "others")):
            if family in counts:
                said.append(f"{counts[family]} {one if counts[family] == 1 else many}")
        return ", ".join(said)

    def lines(self) -> list[str]:
        """The list as ``wrenchroom tools --used`` prints it."""
        tools = "1 tool" if len(self.uses) == 1 else f"{len(self.uses)} tools"
        lines = [f"{tools} this model needs (kit {self.kit}): {self.families or 'none'}"]
        for use in self.uses:
            said = use.said()
            tail = f"   {'; '.join(said)}" if said else ""
            lines.append(f"  {use.tool:22} x{len(use.fasteners):<4}{tail}".rstrip())
        lines.extend(self.apart())
        return lines

    def markdown(self) -> list[str]:
        """The list as the Markdown report's Tools section: a table, then the rest.

        Names come from the model, so each is a code span, as everywhere in the
        Markdown report; the words round them are this module's own.
        """
        lines = ["", "#### Tools", "", md_text(self.lines()[0]) + "."]
        if self.uses:
            lines += ["", "| Tool | Fasteners | |", "| --- | ---: | --- |"]
            lines.extend(
                f"| {md_code(use.tool)} | {len(use.fasteners)} | {'; '.join(use.said(_md))} |"
                for use in self.uses
            )
        apart = self.apart(
            lambda names: _md(names, in_table=False), lambda tool: md_code(tool, in_table=False)
        )
        if apart:
            lines += ["", *(f"- {line[0].upper()}{line[1:]}" for line in apart)]
        return lines

    def apart(
        self, names: Callable[[tuple[str, ...]], str] = listed, tool: Callable[[str], str] = str
    ) -> list[str]:
        """The fasteners that need no tool, or have none yet, a line each kind.

        Then the tools blocked ones would need once reached, each with how many need
        it, and those no fastener reached needs named: only blocked fasteners need it.
        """
        lines = []
        if self.by_hand:
            lines.append(f"by hand: {len(self.by_hand)} ({names(self.by_hand)})")
        if self.no_tool:
            lines.append(f"no tool needed: {len(self.no_tool)}, held by themselves or a trap")
        if self.without:
            counts: dict[str, int] = {}
            for _, verdict in self.without:
                counts[verdict.value] = counts.get(verdict.value, 0) + 1
            said = ", ".join(f"{count} {verdict}" for verdict, count in counts.items())
            lines.append(f"no tool yet: {said} (wrenchroom check says why)")
        if self.blocked:
            once = []
            for each, fasteners in self.blocked:
                only = f" (only blocked fasteners need it: {names(fasteners)})"
                once.append(f"{tool(each)} x{len(fasteners)}{'' if self.reached(each) else only}")
            lines.append(f"blocked, once reached: {', '.join(once)}")
        return lines

    def reached(self, tool: str) -> bool:
        """Whether a fastener the check reached needs this tool, as its line names it."""
        return any(use.tool == tool for use in self.uses)

    def to_json(self) -> dict[str, object]:
        """The list as the JSON report's ``tools_used``."""
        return {
            "default_kit": DEFAULT_KIT,
            "tools": [
                {
                    "tool": use.tool,
                    "count": len(use.fasteners),
                    "fasteners": list(use.fasteners),
                    "at_once": use.at_once,
                    "in_default_kit": use.in_default_kit,
                    "unusual": list(use.unusual),
                    "states": list(use.states),
                }
                for use in self.uses
            ],
            "by_hand": list(self.by_hand),
            "no_tool": list(self.no_tool),
            "without": [{"name": name, "verdict": v.value} for name, v in self.without],
            "blocked_tools": [
                {
                    "tool": tool,
                    "count": len(fasteners),
                    "fasteners": list(fasteners),
                    "only_blocked": not self.reached(tool),
                }
                for tool, fasteners in self.blocked
            ],
        }


def tools_used(report: Report) -> ToolsUsed:
    """The tools ``report``'s fasteners were turned or held with, and those with none."""
    default = kit_named(DEFAULT_KIT)
    by_tool: dict[str, list[FastenerResult]] = {}
    by_hand, no_tool, without = [], [], []
    blocked: dict[str, list[str]] = {}
    for result in report.results:
        name = result.fastener.name
        if result.verdict not in _WITH_A_TOOL:
            without.append((name, result.verdict))
            if result.verdict is Verdict.BLOCKED and result.tool not in (None, HAND):
                blocked.setdefault(result.tool or "", []).append(name)
        elif result.tool == HAND:
            by_hand.append(name)
        elif result.tool is None:
            no_tool.append(name)
        else:
            by_tool.setdefault(_tool_of(result), []).append(result)
    tool_of = {r.fastener.name: tool for tool, results in by_tool.items() for r in results}
    uses = []
    for tool, results in by_tool.items():
        joint = any(tool_of.get(r.pair or "") == tool for r in results)
        uses.append(
            ToolUse(
                tool=tool,
                fasteners=tuple(r.fastener.name for r in results),
                at_once=2 if joint else 1,
                in_default_kit=default.holds(tool.partition(",")[0]),
                only_way=tuple(r.fastener.name for r in results if _only_way(r)),
                states=tuple(sorted({r.state for r in results}, key=lambda s: s or "")),
            )
        )
    uses.sort(key=lambda use: _order(use.tool))
    once = sorted(
        ((tool, tuple(names)) for tool, names in blocked.items()), key=lambda t: _order(t[0])
    )
    return ToolsUsed(
        report.kit, tuple(uses), tuple(by_hand), tuple(no_tool), tuple(without), tuple(once)
    )


def _md(names: tuple[str, ...], *, in_table: bool = True) -> str:
    """A few names as code spans, then how many more, as the Markdown report lists."""
    shown, more = shortlist(names)
    more_text = f" and {more} more" if more else ""
    return ", ".join(md_code(name, in_table=in_table) for name in shown) + md_text(more_text)


def _tool_of(result: FastenerResult) -> str:
    """The tool a person reaches for: a stubby spanner apart from a full-length one."""
    tool = result.tool or ""
    return f"{tool}, {STUBBY}" if STUBBY in (result.how or "") else tool


def _only_way(result: FastenerResult) -> bool:
    """Whether only an unusual tool reaches it: a ball end, or a stubby."""
    return (result.tool or "").startswith("ball-end-key") or STUBBY in (result.how or "")


def _family(tool: str) -> str:
    """``spanner`` for ``spanner-13`` (and its stubby); '' for a sidecar's own tool."""
    family = tool.partition(",")[0].rpartition("-")[0]
    return family if family in {f for f, _, _ in _FAMILIES} else ""


def _order(tool: str) -> tuple[int, float, str]:
    """Family by family, as :data:`_FAMILIES` lays them out, then smallest first."""
    family = _family(tool)
    families = [f for f, _, _ in _FAMILIES]
    rank = families.index(family) if family else len(families)
    size_text = tool.partition(",")[0].rpartition("-")[2]
    try:
        size = size_mm(size_text.lstrip("Tph"))
    except ValueError:
        size = 0.0
    return rank, size, tool
