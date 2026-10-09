"""Build order (M8): each fastener checked in the step of the build that puts it in.

``check`` answers whether the finished machine can be serviced: every fastener in the
model as given, or in a state with parts off. Whether it can be built is another
question. A sidecar's ``build:`` lists the steps in order, each adding parts, and each
fastener is checked in the step that adds it, among the parts added by then: that
step's own are there, as they go on before their fasteners, and the later steps' are
not.

- A fastener goes in and turns: a tool turns it, or holds it while its partner turns,
  and a screw's way in is clear (its way out, which ``stuck`` tests, the other way).
- A joint is checked in the step its last member arrives in. A bolt put in before its
  nut need only go in, held by its tool. A nut put in before its bolt is held by
  nothing till then, unless it is a fixed thread or sits in a trap: the sidecar's
  steps are wrong, and the run fails as for any sidecar problem (exit 2).
- Every part is added by one step exactly. A part in none, or in two, is a sidecar
  problem too, and the build isn't checked; ``add: ["*"]`` in one step takes every part
  no other step adds. An ``add:`` glob naming nothing is a renamed part, as an
  unmatched rule is.

A screw can pass in the build and fail in service, buried by a part put on after it,
or the other way round, where a state takes off for service a part put on before it:
the report says both. Whether a part itself fits in at its step is part removal run
backwards, which the build doesn't check.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING

from wrenchroom.config import CATCH_ALL
from wrenchroom.report import (
    NO_TOOL,
    Verdict,
    listed,
    md_code,
    md_text,
    printable,
    result_json,
    shortlist,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from wrenchroom.assembly import Assembly
    from wrenchroom.config import BuildStep
    from wrenchroom.report import FastenerResult


@dataclass(frozen=True)
class Step:
    """One step as the model has it: its name, the parts it adds, the model it is in.

    Attributes:
        name: The step's name, from the sidecar.
        parts: The parts it adds, in the model's order (a part drawn as several solids
            once: its other solids go with it).
        model: The mechanism as it sits during the step, as a state's model is; None
            for the model as given.
    """

    name: str
    parts: tuple[str, ...]
    model: str | None = None


@dataclass(frozen=True)
class Plan:
    """Which step adds each part: the sidecar's ``build:`` read against the model.

    Attributes:
        steps: The steps in order, each with the parts it adds.
        added_in: Each part's step, by index: every part a step adds, and each other
            solid of one drawn as several.
        unplaced: Parts no step adds.
        twice: Parts more than one step adds, each with those steps' names.
        unmatched: ``(step, glob)`` for each ``add:`` glob that names no part.
    """

    steps: tuple[Step, ...]
    added_in: Mapping[str, int]
    unplaced: tuple[str, ...] = ()
    twice: tuple[tuple[str, tuple[str, ...]], ...] = ()
    unmatched: tuple[tuple[str, str], ...] = ()

    @property
    def sound(self) -> bool:
        """Whether every part is added by one step exactly, so the build can be checked."""
        return not (self.unplaced or self.twice)


def plan(steps: tuple[BuildStep, ...], assembly: Assembly, ignored: Callable[[str], bool]) -> Plan:
    """Read the sidecar's steps against the model: which step adds each part.

    An ignored part is in no scene, so no step need add it, and one that does adds
    nothing. A glob is matched against every name the model has, ignored parts and
    surfaces among them: one naming only those adds nothing, and names something.

    Args:
        steps: The sidecar's ``build:``, in order.
        assembly: The model as given.
        ignored: Whether the sidecar's ignore list takes a part out, by its name.
    """
    leaves = [part.name for part in assembly if part.piece_of is None and not ignored(part.name)]
    adding: dict[str, list[int]] = {}
    for index, step in enumerate(steps):
        globs = [glob for glob in step.add if glob != CATCH_ALL]
        for name in leaves:
            if any(fnmatchcase(name, glob) for glob in globs):
                adding.setdefault(name, []).append(index)
    rest = next((index for index, step in enumerate(steps) if CATCH_ALL in step.add), None)
    if rest is not None:
        for name in leaves:
            adding.setdefault(name, [rest])
    added_in = {name: found[0] for name, found in adding.items()}
    for part in assembly:
        if part.piece_of is not None and part.piece_of in added_in:
            added_in[part.name] = added_in[part.piece_of]
    names = (*assembly.names, *assembly.surfaces)
    return Plan(
        steps=tuple(
            Step(
                step.name,
                tuple(name for name in leaves if adding.get(name) == [index]),
                step.model,
            )
            for index, step in enumerate(steps)
        ),
        added_in=added_in,
        unplaced=tuple(name for name in leaves if name not in adding),
        twice=tuple(
            (name, tuple(steps[index].name for index in adding[name]))
            for name in leaves
            if len(adding.get(name, ())) > 1
        ),
        unmatched=tuple(
            (step.name, glob)
            for step in steps
            for glob in step.add
            if glob != CATCH_ALL and not any(fnmatchcase(name, glob) for name in names)
        ),
    )


@dataclass(frozen=True)
class Placed:
    """One fastener in the build: the step that adds it, and how it fared there.

    Attributes:
        result: Its verdict in the build, as ``check`` says one.
        step: The step that adds it.
        checked_in: The step its verdict was reached in: its own, or, for one that
            went in before its partner, the step its partner arrives in, where the
            joint is checked.
    """

    result: FastenerResult
    step: str
    checked_in: str


#: The verdicts, as a step's line counts them: the summary line's words.
_COUNTED = (
    (Verdict.TURNS, "turn"),
    (Verdict.HELD, "held"),
    (Verdict.BLOCKED, "blocked"),
    (Verdict.STUCK, "stuck"),
    (Verdict.NOT_COVERED, "not covered"),
)

#: Failures in a step, worst first, as ``check``'s are ordered.
_WORST = {Verdict.BLOCKED: 0, Verdict.STUCK: 1, Verdict.NOT_COVERED: 2}


@dataclass(frozen=True)
class Build:
    """What a build check found: each fastener in its step, and what's wrong with the steps.

    Attributes:
        plan: The steps as the model has them, and the sidecar's problems with them.
        placed: Each fastener's verdict in the build, in the order the steps add them;
            none where the plan isn't sound.
    """

    plan: Plan
    placed: tuple[Placed, ...] = ()

    @property
    def exit_code(self) -> int:
        """2 for a problem with the steps or a fastener not covered, 1 for one failing, else 0."""
        verdicts = {placed.result.verdict for placed in self.placed}
        if not self.plan.sound or self.plan.unmatched or Verdict.NOT_COVERED in verdicts:
            return 2
        return 1 if self.failures() else 0

    def failures(self) -> tuple[Placed, ...]:
        """The fasteners that fail in the build: by the step they fail in, worst first."""
        order = {step.name: index for index, step in enumerate(self.plan.steps)}
        failed = [placed for placed in self.placed if not placed.result.passed]
        return tuple(
            sorted(
                failed,
                key=lambda p: (order[p.checked_in], _WORST[p.result.verdict], p.result.name),
            )
        )

    @property
    def headline(self) -> str:
        """``build: 4 steps, 38 fasteners; the first failure is in align``."""
        steps = _count(len(self.plan.steps), "step")
        if not self.plan.sound:
            return f"build: {steps}, not checked: every part must be added by one step exactly"
        said = f"build: {steps}, {_count(len(self.placed), 'fastener')}"
        failures = self.failures()
        return f"{said}; the first failure is in {failures[0].checked_in}" if failures else said

    def step_counts(self, step: str) -> dict[str, int]:
        """The verdicts of the fasteners a step adds, as the JSON's summary counts them."""
        counts = Counter(p.result.verdict for p in self.placed if p.step == step)
        return {
            "fasteners": sum(counts.values()),
            **{verdict.value.replace("-", "_"): counts[verdict] for verdict, _ in _COUNTED},
        }

    def _step_said(self, step: Step) -> str:
        """``12 fasteners: 11 turn, 1 blocked``: a step's fasteners, by verdict."""
        counts = Counter(p.result.verdict for p in self.placed if p.step == step.name)
        total = sum(counts.values())
        said = (
            f"{_count(total, 'fastener')}: "
            + ", ".join(
                f"{counts[verdict]} {word}" for verdict, word in _COUNTED if counts[verdict]
            )
            if total
            else "no fasteners"
        )
        return said + (f", in {step.model}" if step.model else "")

    def added(self, name: str) -> str | None:
        """The step that adds a part, by name; None for one no step adds."""
        index = self.plan.added_in.get(name)
        return None if index is None else self.plan.steps[index].name

    def why(self, placed: Placed) -> str:
        """What a failure says: its reason, else what's in the way, each with its step."""
        result = placed.result
        if result.reason:
            return result.reason
        stuck = result.verdict is Verdict.STUCK
        names = result.stuck_on if stuck else result.blockers
        if not names:
            return NO_TOOL
        shown, more = shortlist(names, result.attempts)
        said = ", ".join(self._with_step(name) for name in shown) + _more(more)
        return f"its way in is blocked: {said}" if stuck else said

    def told(self, name: str) -> str | None:
        """How a fastener fares in the build, in a line, as ``explain`` says it.

        ``added in base, turns with hex-key-5, driver straight in``, or for one that
        fails, why: ``added in late, blocked with hex-key-5: cover (added in cover)``.
        None for a fastener the build didn't check.
        """
        placed = next((p for p in self.placed if p.result.name == name), None)
        if placed is None:
            return None
        result = placed.result
        said = f"added in {placed.step}"
        if placed.checked_in != placed.step:
            said += f", checked in {placed.checked_in}"
        said += f", {result.verdict}" + (f" with {result.tool}" if result.tool else "")
        if not result.passed:
            return f"{said}: {self.why(placed)}"
        return f"{said}, {result.how}" if result.how else said

    def _with_step(self, name: str) -> str:
        step = self.added(name)
        return f"{name} (added in {step})" if step is not None else name

    def lines(self) -> list[str]:
        """The build as the terminal says it, for the report's terminal lines.

        The headline, a line per step, a ``FAIL`` line per fastener that fails, which
        names its step, and a ``WARN`` for each problem with the steps. Names come from
        the model and the sidecar: the report makes every line safe to print, as it
        does its own (a step's name is made so here only to line the steps up).
        """
        lines = [self.headline]
        if self.plan.sound:
            width = max(len(printable(step.name)) for step in self.plan.steps)
            lines += [
                f"  {printable(step.name):{width}}  {self._step_said(step)}"
                for step in self.plan.steps
            ]
        for placed in self.failures():
            result = placed.result
            added = f" (added in {placed.step})" if placed.step != placed.checked_in else ""
            lines.append(
                f"FAIL {placed.checked_in}: {result.name}{added}  {result.tool or '-'}  "
                f"{result.verdict}  {self.why(placed)}"
            )
        lines += [f"WARN build: {problem}" for problem in self._problems()]
        return lines

    def _problems(self) -> list[str]:
        """What's wrong with the steps: parts in none, parts in two, globs naming nothing."""
        problems = []
        if self.plan.unplaced:
            problems.append(
                f"no step adds {_count(len(self.plan.unplaced), 'part')}: "
                + listed(self.plan.unplaced)
            )
        by_steps: dict[tuple[str, ...], list[str]] = {}
        for name, steps in self.plan.twice:
            by_steps.setdefault(steps, []).append(name)
        for steps, names in by_steps.items():
            problems.append(
                f"steps {_and(steps)} each add {_count(len(names), 'part')}: "
                + listed(tuple(names))
            )
        problems += [
            f"step {step!r}: add glob {glob!r} matched nothing (renamed part?)"
            for step, glob in self.plan.unmatched
        ]
        return problems

    def to_json(self) -> dict[str, object]:
        """The build as the JSON report's ``build``: every name, no shortlists."""
        return {
            "checked": self.plan.sound,
            "steps": [
                {
                    "step": step.name,
                    "model": step.model,
                    "adds": list(step.parts),
                    "summary": self.step_counts(step.name),
                }
                for step in self.plan.steps
            ],
            "fasteners": [
                {**result_json(placed.result), "step": placed.step, "checked_in": placed.checked_in}
                for placed in self.placed
            ],
            "unplaced": list(self.plan.unplaced),
            "twice": [{"part": name, "steps": list(steps)} for name, steps in self.plan.twice],
            "unmatched": [{"step": step, "glob": glob} for step, glob in self.plan.unmatched],
        }

    def markdown(self) -> list[str]:
        """The build as a Markdown section: a row per step, then its failures."""
        lines = ["", "#### Build", "", f"**{md_text(self.headline)}.**"]
        if self.plan.sound:
            lines += ["", "| Step | Adds | Fasteners |", "| --- | ---: | --- |"]
            lines.extend(
                f"| {md_code(step.name)} | {_count(len(step.parts), 'part')} "
                f"| {md_text(self._step_said(step))} |"
                for step in self.plan.steps
            )
        failures = self.failures()
        if failures:
            lines += [
                "",
                "| Step | Fastener | Tool | Verdict | In the way, or why |",
                "| --- | --- | --- | --- | --- |",
            ]
            for placed in failures:
                result = placed.result
                added = (
                    f" (added in {md_code(placed.step)})"
                    if placed.step != placed.checked_in
                    else ""
                )
                tool = md_code(result.tool) if result.tool else "-"
                lines.append(
                    f"| {md_code(placed.checked_in)} | {md_code(result.name)}{added} | {tool} "
                    f"| {result.verdict} | {self._md_why(placed)} |"
                )
        problems = self._problems()
        if problems:
            lines += ["", *(f"- {md_code(problem, in_table=False)}" for problem in problems)]
        return lines

    def _md_why(self, placed: Placed) -> str:
        """:meth:`why` for a table: each name and step a code span, the rest plain."""
        result = placed.result
        if result.reason:
            return md_code(result.reason)
        stuck = result.verdict is Verdict.STUCK
        names = result.stuck_on if stuck else result.blockers
        if not names:
            return md_text(NO_TOOL)
        shown, more = shortlist(names, result.attempts)
        said = ", ".join(
            md_code(name) + (f" (added in {md_code(step)})" if (step := self.added(name)) else "")
            for name in shown
        ) + md_text(_more(more))
        return f"its way in is blocked: {said}" if stuck else said


def _count(count: int, noun: str) -> str:
    """``1 step``, ``3 steps``."""
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _more(count: int) -> str:
    return f" and {count} more" if count else ""


def _and(names: tuple[str, ...]) -> str:
    """``a and b``, ``a, b and c``."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
