"""The sidecar ``wrenchroom detect`` writes: what was found, for a person to correct.

One rule per detected fastener, each loadable as it stands: a rule here describes
its part outright, so once the file is kept beside the model, detection leaves those
parts alone. A fastener detection found but couldn't understand is written
commented out, because a rule can't say "not covered". Everything that isn't a rule
field (how sure detection was, what found the part, the axis the check resolved,
how it fares now) goes in a comment above it, because the loader refuses keys it
doesn't know.

Names come from the model, so neither the rules nor the comments may trust them. A
name in a comment goes through :func:`wrenchroom.terminal.printable`: a newline in it
would otherwise end the comment and start YAML of its own. A name in a rule is
quoted by the YAML writer, written in plain Unicode only when it holds nothing that
could steer a terminal or editor (a bidirectional override passes the writer's own
check), and has its glob characters escaped so the rule matches that part alone.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml

from wrenchroom import __version__
from wrenchroom.fasteners import Fastener, Head, Kind, hex_key_af, spanner_af
from wrenchroom.terminal import UNSAFE, printable

if TYPE_CHECKING:
    from wrenchroom.report import FastenerResult, Report

_HEADER = """\
# wrenchroom sidecar, written by `wrenchroom detect {model}` (wrenchroom {version}).
#
# One rule per fastener found by its name and solid. Check each, correct what is
# wrong, and keep this file beside the model as wrenchroom.yaml: a rule describes
# its part outright, and detection leaves that part alone from then on. A rule's
# comment says how sure detection was, what found the part, the axis the check
# resolved (pointing to where the tool comes from; set `axis:` if it's wrong) and
# how the part fares now.
"""

_GLOB = re.compile(r"([\[\]*?])")

#: A measured across-flats this close to the table's needs no rule of its own, mm.
_SAME_AF = 0.01


def sidecar_text(report: Report, model: str) -> str:
    """The sidecar for every detected fastener in a report, as YAML text."""
    found = sorted(
        (r for r in report.results if r.fastener.source != "sidecar"),
        key=lambda r: r.fastener.name,
    )
    text = _HEADER.format(model=printable(model), version=__version__)
    if not found:
        return text + "\nfasteners: []  # nothing in the model is named like a fastener\n"
    blocks = [_block(result) for result in found]
    return text + "\nfasteners:\n" + "\n".join(blocks)


def glob_escape(name: str) -> str:
    """A glob matching exactly this name: ``[``, ``]``, ``*`` and ``?`` bracketed."""
    return _GLOB.sub(r"[\1]", name)


def _block(result: FastenerResult) -> str:
    fastener = result.fastener
    comments = [
        f"{fastener.name}: {fastener.confidence or 'low'} confidence; found by {fastener.basis}",
        f"axis {_axis(result.axis)}; now {_verdict(result)}",
    ]
    lines = [f"  # {printable(comment)}" for comment in comments]
    entry: dict[str, object] = {"parts": glob_escape(fastener.name), "kind": fastener.kind.value}
    if fastener.head is not None:
        entry["head"] = fastener.head.value
    if fastener.size is not None:
        entry["size"] = fastener.size.designation
    if fastener.length_mm is not None:
        entry["length"] = fastener.length_mm
    if fastener.drive_af is not None and not _table_agrees(fastener):
        entry["across_flats"] = round(fastener.drive_af, 3)
    if not fastener.socket_allowed:
        entry["socket"] = False
    plain = not any(UNSAFE.search(str(value)) for value in entry.values())
    dumped = yaml.safe_dump([entry], sort_keys=False, allow_unicode=plain, width=1000)
    if result.fastener.not_covered is not None:
        # A rule can't say "not covered": kept as written, it would turn this
        # into a checked fastener (a set screw into a socket screw with the
        # wrong key). So it is written commented out, for a person to complete.
        lines.append("  # not covered: fill in what is missing, then uncomment")
        lines += [f"  # {line}" for line in dumped.splitlines()]
    else:
        lines += [f"  {line}" for line in dumped.splitlines()]
    return "\n".join(lines) + "\n"


def _table_agrees(fastener: Fastener) -> bool:
    """True when the size's table gives the measured across-flats anyway."""
    if fastener.size is None or fastener.drive_af is None:
        return False
    if fastener.kind is Kind.NUT or fastener.head is Head.HEX:
        expected = spanner_af(fastener.size)
    elif fastener.head is not None:
        expected = hex_key_af(fastener.head, fastener.size)
    else:
        return False
    return expected is not None and abs(expected - fastener.drive_af) < _SAME_AF


def _axis(axis: tuple[float, float, float] | None) -> str:
    if axis is None:
        return "unresolved"
    for index, letter in enumerate("xyz"):
        if abs(abs(axis[index]) - 1) < 1e-6:  # noqa: PLR2004
            return ("+" if axis[index] > 0 else "-") + letter
    return "[" + ", ".join(f"{c:.4f}" for c in axis) + "]"


def _verdict(result: FastenerResult) -> str:
    text = result.verdict.value
    if result.tool:
        text += f" with {result.tool}" + (f", {result.how}" if result.how else "")
    if result.reason:
        text += f": {result.reason}"
    elif result.blockers and not result.passed:
        text += f"; blocked by {', '.join(result.blockers)}"
    return text
