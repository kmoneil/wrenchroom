"""Fasteners: what a tool turns, and the vocabulary for describing one.

A fastener is something a tool turns: a screw or bolt (by its head), or a nut.
Washers, well nuts, inserts and hand-set studs aren't turned and aren't modelled.

This module is pure data: kinds, heads, sizes, and the ``Fastener`` record the checks
consume. Where a fastener comes from (sidecar now; names and geometry at M4) is
``config.py`` and later ``detect.py``; what gets done to it is ``checker.py``.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field

from wrenchroom.tools.sizes import inch_mm


class Kind(enum.StrEnum):
    """Screw (turned by its head) or nut."""

    SCREW = "screw"
    NUT = "nut"


class Head(enum.StrEnum):
    """How the turned end is shaped, which decides the tools worth trying.

    ``CARRIAGE`` is the self-holding one: a square neck in a square hole. It is never
    turned and never extracted; its nut does all the work.
    """

    SOCKET = "socket"
    BUTTON = "button"
    FLAT = "flat"
    HEX = "hex"
    TORX = "torx"
    PHILLIPS = "phillips"
    SLOTTED = "slotted"
    CARRIAGE = "carriage"


#: Metric thread designations accepted, with the nominal diameter in mm. The coarse
#: series M3..M24 the spec names, plus M3.5 which ISO 262 keeps in the first-choice
#: list. A size outside this table is a config error, not a guess.
METRIC_SIZES: dict[str, float] = {
    "M3": 3.0,
    "M3.5": 3.5,
    "M4": 4.0,
    "M5": 5.0,
    "M6": 6.0,
    "M8": 8.0,
    "M10": 10.0,
    "M12": 12.0,
    "M14": 14.0,
    "M16": 16.0,
    "M18": 18.0,
    "M20": 20.0,
    "M22": 22.0,
    "M24": 24.0,
}

#: Imperial sizes: numbered gauges (ASME B18.6.3: major diameter 0.060 + 0.013 per
#: gauge, in inches) and fractional designations. UNC/UNF pitch is ignored for tool
#: choice, so "1/4" covers 1/4-20 and 1/4-28 alike.
_GAUGES = (2, 4, 6, 8, 10, 12)
_FRACTIONS = ("1/4", "5/16", "3/8", "7/16", "1/2", "9/16", "5/8", "3/4")
_MM_PER_INCH = 25.4

IMPERIAL_SIZES: dict[str, float] = {
    **{f"#{g}": round((0.060 + 0.013 * g) * _MM_PER_INCH, 3) for g in _GAUGES},
    **{f: round(int(f.split("/")[0]) / int(f.split("/")[1]) * _MM_PER_INCH, 3) for f in _FRACTIONS},
}

_THREAD_SUFFIX = re.compile(r"[- ]\d+$")  # "1/4-20", "#10-32": the pitch half


@dataclass(frozen=True)
class Size:
    """A thread size: the designation as written, and the nominal diameter in mm."""

    designation: str
    diameter_mm: float

    @classmethod
    def parse(cls, text: str) -> Size:
        """Parse "M6", "#10", "1/4", with any UNC/UNF pitch suffix dropped.

        Raises:
            ValueError: If the designation is not in the accepted tables; the message
                carries the designation so a config error names its line.
        """
        cleaned = _THREAD_SUFFIX.sub("", text.strip())
        metric = cleaned.upper()
        if metric in METRIC_SIZES:
            return cls(metric, METRIC_SIZES[metric])
        if cleaned in IMPERIAL_SIZES:
            return cls(cleaned, IMPERIAL_SIZES[cleaned])
        msg = f"unknown fastener size {text!r}"
        raise ValueError(msg)

    @property
    def is_metric(self) -> bool:
        """True for M-designations."""
        return self.designation.startswith("M")


#: An axis is either "work it out from the geometry" or a given direction pointing
#: out of the joint toward where the tool comes from.
AUTO = "auto"


@dataclass(frozen=True)
class Fastener:
    """One fastener as described, before any geometry has been resolved.

    The axis and seat are resolved against the part's shape when the check runs;
    here ``axis`` is the description: :data:`AUTO` or a unit direction.

    Attributes:
        name: The part's unique name in the assembly.
        kind: Screw or nut.
        head: The head shape, or ``None`` when not stated (geometry may fill it in
            at M4; until then an unstated head on a screw is `not-covered`).
        size: Thread size, or ``None`` when not stated.
        length_mm: Length under the head when the model doesn't show it.
        axis: :data:`AUTO` or a unit (x, y, z) pointing toward the tool.
        tool: A forced tool name, else chosen from head and size.
        socket_allowed: False for fasteners with a cable through them (glands):
            a socket cannot pass over a cable.
        mates: Globs for the parts that travel with this fastener (washers, a
            carriage bolt's spacer) and leave its scene.
        state: The named state this fastener is reached in, or ``None`` for the
            run's default state.
        drive_af: Across flats of the drive, mm, when it is known rather than
            looked up: measured from the solid (detection) or given in the
            sidecar (``across_flats``). It outranks the size's table entry, so a
            gland's 24 mm hex or a DIN-sized nut gets the spanner it really takes.
        source: Where this description came from: ``sidecar``, ``name``, or
            ``name+geometry``.
        basis: What said so, for people (``ISO 4762, M6x20; solid: socket 5``).
        not_covered: Set when detection found a fastener the kit can't check,
            with the reason (a set screw, a carriage bolt with no square neck).
        confidence: How sure detection is, for a detected fastener: ``high``
            (kind, head and size each stated by the name or shown by a drive in
            the solid), ``medium`` (something rests on a head's outline or a
            measured shank, or the name and the solid's drive disagree on the
            head), ``low`` (something is missing). Empty from a sidecar.
    """

    name: str
    kind: Kind
    head: Head | None = None
    size: Size | None = None
    length_mm: float | None = None
    axis: str | tuple[float, float, float] = AUTO
    tool: str | None = None
    socket_allowed: bool = True
    mates: tuple[str, ...] = field(default=())
    state: str | None = None
    drive_af: float | None = None
    source: str = "sidecar"
    basis: str = ""
    not_covered: str | None = None
    confidence: str = ""

    @property
    def self_holding(self) -> bool:
        """A carriage bolt holds itself: never turned, never extracted."""
        return self.head is Head.CARRIAGE


# ---------------------------------------------------------------------------
# Drive tables: which tool size a head takes. Metric only until the imperial
# kit (M6). A size missing from a table is a statement: that head does not
# come in that size, and the checker says `not-covered` rather than guessing.
#
# Values marked "catalogue" are common across supplier catalogues but not yet
# read out of the standard document itself; replace the marker when checked.
# ---------------------------------------------------------------------------

#: ISO 4762 socket head cap screws: thread -> hexagon socket across-flats, mm.
#: Checked 2026-10-06 against engineersedge.com's ISO 4762 table.
SOCKET_KEY_AF: dict[str, float] = {
    "M3": 2.5,
    "M4": 3.0,
    "M5": 4.0,
    "M6": 5.0,
    "M8": 6.0,
    "M10": 8.0,
    "M12": 10.0,
    "M14": 12.0,  # catalogue
    "M16": 14.0,
    "M18": 14.0,  # catalogue
    "M20": 17.0,
    "M22": 17.0,  # catalogue
    "M24": 19.0,
}

#: ISO 7380-1 button head screws: thread -> socket across-flats, mm.
#: Checked 2026-10-06 against trfastenings.com's ISO 7380 table (M3..M12).
BUTTON_KEY_AF: dict[str, float] = {
    "M3": 2.0,
    "M4": 2.5,
    "M5": 3.0,
    "M6": 4.0,
    "M8": 5.0,
    "M10": 6.0,
    "M12": 8.0,
    "M16": 10.0,  # catalogue
}

#: ISO 10642 countersunk (flat) head screws: thread -> socket across-flats, mm.
#: Checked 2026-10-06 against accu-components.com product pages (M3..M12) and
#: engineersedge.com's ISO 10642 note; the spec's own M8 -> 5 example agrees.
FLAT_KEY_AF: dict[str, float] = {
    "M3": 2.0,
    "M4": 2.5,
    "M5": 3.0,
    "M6": 4.0,
    "M8": 5.0,
    "M10": 6.0,
    "M12": 8.0,
    "M14": 10.0,  # catalogue
    "M16": 10.0,  # catalogue
    "M20": 12.0,  # catalogue
}


def _inch(rows: dict[str, str]) -> dict[str, float]:
    """An inch table, size -> tool size as written (``5/32``), in mm."""
    return {size: inch_mm(tool) for size, tool in rows.items()}


# Inch heads, ASME B18.3 (socket, button and flat countersunk heads), checked
# 2026-10-06 against the Unbrako Engineering Guide (Form 5519, citing ANSI B18.3)
# and fasten.it's ASME B18.3 tables 1A, 2A and 3: the two agree on every key. A flat
# head takes the button head's key, smaller than a socket head's (#10: 1/8 against
# 5/32), whatever some supplier pages say. No #12 socket head screw is standard.
SOCKET_KEY_AF.update(
    _inch(
        {
            "#2": "5/64",
            "#4": "3/32",
            "#6": "7/64",
            "#8": "9/64",
            "#10": "5/32",
            "1/4": "3/16",
            "5/16": "1/4",
            "3/8": "5/16",
            "7/16": "3/8",
            "1/2": "3/8",
            "9/16": "7/16",
            "5/8": "1/2",
            "3/4": "5/8",
        }
    )
)
BUTTON_KEY_AF.update(
    _inch(
        {
            "#2": "0.050",
            "#4": "1/16",
            "#6": "5/64",
            "#8": "3/32",
            "#10": "1/8",
            "1/4": "5/32",
            "5/16": "3/16",
            "3/8": "7/32",
            "1/2": "5/16",
            "5/8": "3/8",
        }
    )
)
FLAT_KEY_AF.update(
    _inch(
        {
            "#2": "0.050",
            "#4": "1/16",
            "#6": "5/64",
            "#8": "3/32",
            "#10": "1/8",
            "1/4": "5/32",
            "5/16": "3/16",
            "3/8": "7/32",
            "7/16": "1/4",
            "1/2": "5/16",
            "5/8": "3/8",
            "3/4": "1/2",
        }
    )
)

#: ISO 4032 hex nuts and ISO 4017 hex head bolts: thread -> across-flats, mm.
#: Checked 2026-10-06 against wermac.org's DIN/ISO nut table. Note the ISO/DIN
#: split: DIN 934 gives M10 -> 17, M12 -> 19, M14 -> 22, M22 -> 32; these are the
#: ISO values, and a DIN-dimensioned model will need the sidecar's `tool:` until
#: detection learns to measure the hex instead of trusting the thread.
HEX_AF: dict[str, float] = {
    "M3": 5.5,
    "M4": 7.0,
    "M5": 8.0,
    "M6": 10.0,
    "M8": 13.0,
    "M10": 16.0,
    "M12": 18.0,
    "M14": 21.0,
    "M16": 24.0,
    "M18": 27.0,  # catalogue
    "M20": 30.0,
    "M22": 34.0,  # catalogue
    "M24": 36.0,
}

# Inch nuts: ASME B18.2.2 hex nuts (1/4 and up) and ASME B18.6.3 machine screw nuts
# (#4 to #10), basic width across flats. Checked 2026-10-06: Engineers Edge and
# torqbolt agree for B18.2.2; Engineers Edge, torqbolt and Aspen Fasteners product
# pages for B18.6.3 (Aspen's #8 maximum, 0.334, sits below its own basic size and is
# taken for a typo).
HEX_AF.update(
    _inch(
        {
            "#4": "1/4",
            "#6": "5/16",
            "#8": "11/32",
            "#10": "3/8",
            "1/4": "7/16",
            "5/16": "1/2",
            "3/8": "9/16",
            "7/16": "11/16",
            "1/2": "3/4",
            "9/16": "7/8",
            "5/8": "15/16",
            "3/4": "1-1/8",
        }
    )
)

#: Hex head bolts and screws: thread -> across-flats, mm. Metric heads take their
#: nut's spanner (ISO 4017 and 4032 agree). Inch heads, ASME B18.2.1 (checked
#: 2026-10-06, fasten.it's B18.2.1 table 6, AFT Fasteners, Portland Bolt), do not
#: always: a 7/16 head is 5/8 where its nut is 11/16, a 9/16 head 13/16 where its
#: nut is 7/8.
HEX_HEAD_AF: dict[str, float] = {
    **{size: af for size, af in HEX_AF.items() if size.startswith("M")},
    **_inch(
        {
            "1/4": "7/16",
            "5/16": "1/2",
            "3/8": "9/16",
            "7/16": "5/8",
            "1/2": "3/4",
            "9/16": "13/16",
            "5/8": "15/16",
            "3/4": "1-1/8",
        }
    ),
}

_KEY_TABLES: dict[Head, dict[str, float]] = {
    Head.SOCKET: SOCKET_KEY_AF,
    Head.BUTTON: BUTTON_KEY_AF,
    Head.FLAT: FLAT_KEY_AF,
}


def hex_key_af(head: Head, size: Size) -> float | None:
    """The hex key a head takes, in across-flats mm, or None when there isn't one.

    None means "no hex key applies": a hex head takes a spanner, a Phillips a
    driver, and a size absent from its head's table has no standard key, which
    the caller reports as `not-covered` rather than rounding to a neighbour.
    """
    table = _KEY_TABLES.get(head)
    if table is None:
        return None
    return table.get(size.designation)


def spanner_af(size: Size, *, head: bool = False) -> float | None:
    """The across-flats a nut (or with ``head``, a hex head) presents to a spanner, mm."""
    return (HEX_HEAD_AF if head else HEX_AF).get(size.designation)


#: Hexalobular (Torx) socket heads: thread -> Torx size. ISO 14579 (socket head cap),
#: ISO 14580 (cheese), ISO 14581 (countersunk) and ISO 14583 (pan) agree, M12 being
#: in ISO 14579 only; checked 2026-10-06 against fasteners.eu and fasten.it. Some
#: suppliers sell M8 pan heads as T40; the standards say T45.
TORX_SIZE: dict[str, str] = {
    "M3": "T10",
    "M4": "T20",
    "M5": "T25",
    "M6": "T30",
    "M8": "T45",
    "M10": "T50",
    "M12": "T55",
}

#: Phillips driver number by thread. Approximation (catalogue-typical pairings;
#: no ISO or ASME table maps thread to recess number across head styles).
PHILLIPS_NUMBER: dict[str, int] = {
    "M3": 1,
    "M3.5": 2,
    "M4": 2,
    "M5": 2,
    "M6": 3,
    "M8": 3,
    "#2": 1,
    "#4": 1,
    "#6": 2,
    "#8": 2,
    "#10": 2,
    "#12": 3,
    "1/4": 3,
}
