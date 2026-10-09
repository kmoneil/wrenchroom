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
    """Screw (turned by its head), nut, or insert.

    An insert is a fixed thread: a well nut, a rivnut, a threaded insert, a cage,
    T-, press or weld nut. It holds itself, like a carriage bolt: never turned,
    never given a tool, and the screw into it is the one that must turn.
    """

    SCREW = "screw"
    NUT = "nut"
    INSERT = "insert"


class Head(enum.StrEnum):
    """How the turned end is shaped, which decides the tools worth trying.

    ``CARRIAGE`` is the self-holding one: a square neck in a square hole. It is never
    turned and never extracted; its nut does all the work. ``SHOULDER`` is a socket
    head shoulder screw (ISO 7379): a hex socket, but a smaller key than a socket
    head cap screw of its thread takes, and a shoulder wider than the thread. ``SET``
    is a set screw (ISO 4026 to 4029): no head at all, a hex socket in one end of
    the thread, and a smaller key again (issue #96).
    """

    SOCKET = "socket"
    BUTTON = "button"
    FLAT = "flat"
    HEX = "hex"
    TORX = "torx"
    PHILLIPS = "phillips"
    SLOTTED = "slotted"
    CARRIAGE = "carriage"
    SHOULDER = "shoulder"
    SET = "set"


#: Metric thread designations accepted, with the nominal diameter in mm. The coarse
#: series M3..M24 the spec names, M1.6 to M2.5 below it (issue #83: printers,
#: electronics and small mechanisms are full of them; ISO 4762 and ISO 4032 start
#: at M1.6), and M3.5, which ISO 262 keeps in the first-choice list. A size outside
#: this table is a config error, not a guess.
METRIC_SIZES: dict[str, float] = {
    "M1.6": 1.6,
    "M2": 2.0,
    "M2.5": 2.5,
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
_GAUGES = (0, 1, 2, 3, 4, 6, 8, 10, 12)
_FRACTIONS = ("1/4", "5/16", "3/8", "7/16", "1/2", "9/16", "5/8", "3/4")
_MM_PER_INCH = 25.4

IMPERIAL_SIZES: dict[str, float] = {
    **{f"#{g}": round((0.060 + 0.013 * g) * _MM_PER_INCH, 3) for g in _GAUGES},
    **{f: round(int(f.split("/")[0]) / int(f.split("/")[1]) * _MM_PER_INCH, 3) for f in _FRACTIONS},
}

_THREAD_SUFFIX = re.compile(r"[- ]\d+$")  # "1/4-20", "#10-32": the pitch half

#: ASME B1.1's UNC threads per inch (#0 has none: its UNF 80).
_UNC_TPI = {
    "#0": 80, "#1": 64, "#2": 56, "#3": 48, "#4": 40, "#6": 32, "#8": 32, "#10": 24,
    "#12": 24, "1/4": 20, "5/16": 18, "3/8": 16, "7/16": 14, "1/2": 13, "9/16": 12,
    "5/8": 11, "3/4": 10,
}  # fmt: skip

#: Each size's coarse pitch, mm: ISO 261's coarse series, and ASME B1.1's UNC. Coarse
#: is the largest pitch a size comes in, so it gives the smallest minor diameter, the
#: least a thread may be drawn at.
COARSE_PITCH_MM: dict[str, float] = {
    "M1.6": 0.35,
    "M2": 0.4,
    "M2.5": 0.45,
    "M3": 0.5,
    "M3.5": 0.6,
    "M4": 0.7,
    "M5": 0.8,
    "M6": 1.0,
    "M8": 1.25,
    "M10": 1.5,
    "M12": 1.75,
    "M14": 2.0,
    "M16": 2.0,
    "M18": 2.5,
    "M20": 2.5,
    "M22": 2.5,
    "M24": 3.0,
    **{size: round(_MM_PER_INCH / tpi, 4) for size, tpi in _UNC_TPI.items()},
}

#: An external thread's minor diameter is its major less this many pitches: ISO 724's
#: d3, the root of the bolt's thread (d1 less a sixth of the triangle's height H).
_MINOR_PITCHES = 1.226869


def thread_minor_mm(size: Size) -> float:
    """The least diameter a thread of this size is drawn at: its bolt's minor, mm.

    A thread is drawn anywhere from there (a cosmetic thread at its minor) to its
    nominal (issue #117).
    """
    return size.diameter_mm - _MINOR_PITCHES * COARSE_PITCH_MM[size.designation]


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
            measured shank, the name and the solid's drive disagree on the
            head, or the name has words after its fastener noun), ``low``
            (something is missing, a head is guessed from its proportions
            alone, fitting no standard's outline, or the solid is drawn as
            another size than its name's). Empty from a sidecar.
        size_guessed: True when detection had the size from a hex's tolerance
            band alone, which can't tell an M8 nut drawn small from a 5/16 one:
            the bolt a nut runs on outranks it (issue #50).
        notes: What a person should know of how this description was reached,
            which a check's result repeats: a head guessed (issue #48), a size
            taken from the bolt (issue #50), a size or length drawn other than
            the name's (issues #94, #117).
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
    size_guessed: bool = False
    notes: tuple[str, ...] = ()

    @property
    def self_holding(self) -> bool:
        """A carriage bolt or an insert holds itself: never turned, never extracted."""
        return self.head is Head.CARRIAGE or self.kind is Kind.INSERT


@dataclass(frozen=True)
class PassedOver:
    """A part named like a fastener that detection didn't take, and why.

    Its fastener noun has ordinary words after it (``box_gland_vent``), so only
    its solid could make it a fastener, and the solid shows no drive. Reported,
    never dropped: that is how a fastener goes unchecked without a word. Or it is
    named nothing a fastener is (``Part7``), and its solid looks like one
    (``named`` False, issue #95): detection checks named parts only. Or it is
    named for a leadscrew, a ball screw or the nut that runs on one, which no
    tool turns (``motion``, issue #117).
    """

    name: str
    kind: Kind
    reason: str
    named: bool = True
    motion: bool = False


# ---------------------------------------------------------------------------
# Drive tables: which tool size a head takes. Metric only until the imperial
# kit (M6). A size missing from a table is a statement: that head does not
# come in that size, and the checker says `not-covered` rather than guessing.
#
# Every row is a standard's, named in its table's comment or beside the row; a row a
# standard doesn't hold, but a withdrawn one or the trade does, says which (issue #102).
# ---------------------------------------------------------------------------

#: ISO 4762 socket head cap screws: thread -> hexagon socket across-flats, mm.
#: Checked 2026-10-06 against engineersedge.com's ISO 4762 table; M1.6 to M2.5 read
#: 2026-10-07 from ISO 4762:2004's own Table 1 (the iTeh preview), M12 to M24 from
#: Fuller Fasteners' copy of it. M18 and M22 are not in ISO 4762 at all: they are
#: DIN 912's (withdrawn, fasten.it's table, read 2026-10-07), the same keys as M16's
#: and M20's, and screws of those sizes are still sold to it (issue #102).
SOCKET_KEY_AF: dict[str, float] = {
    "M1.6": 1.5,
    "M2": 1.5,
    "M2.5": 2.0,
    "M3": 2.5,
    "M4": 3.0,
    "M5": 4.0,
    "M6": 5.0,
    "M8": 6.0,
    "M10": 8.0,
    "M12": 10.0,
    "M14": 12.0,  # ISO 4762's, bracketed: a non-preferred size
    "M16": 14.0,
    "M18": 14.0,  # DIN 912's: ISO 4762 has no M18
    "M20": 17.0,
    "M22": 17.0,  # DIN 912's: ISO 4762 has no M22
    "M24": 19.0,
}

#: ISO 7380-1 button head screws: thread -> socket across-flats, mm.
#: Checked 2026-10-06 against trfastenings.com's ISO 7380 table (M3..M12), and every
#: row 2026-10-07 against ISO 7380-1:2011's own table (the iTeh preview). Every
#: edition starts at M3 (2011 and 2022): there is no M2 or M2.5 button head.
BUTTON_KEY_AF: dict[str, float] = {
    "M3": 2.0,
    "M4": 2.5,
    "M5": 3.0,
    "M6": 4.0,
    "M8": 5.0,
    "M10": 6.0,
    "M12": 8.0,
    "M16": 10.0,
}

#: ISO 7379 hexagon socket head shoulder screws: thread -> socket across flats, and
#: shoulder diameter -> thread, mm, as fasten.it's ISO 7379 table gives them (read
#: 2026-10-06; Ganter's sheet confirms 6.5 on M5, 13 on M10, 25 on M20). An M6
#: shoulder screw takes a 4 mm key on an 8 mm shoulder, where ISO 4762's M6 takes 5
#: and an 8 mm shank would say M8 (issue #40). Makers sell other shoulders on these
#: threads; only the standard's are read here, and the sidecar says the rest.
SHOULDER_KEY_AF: dict[str, float] = {
    "M5": 3.0,
    "M6": 4.0,
    "M8": 5.0,
    "M10": 6.0,
    "M12": 8.0,
    "M16": 10.0,
    "M20": 12.0,
}
SHOULDER_THREAD: dict[float, str] = {
    6.5: "M5",
    8.0: "M6",
    10.0: "M8",
    13.0: "M10",
    16.0: "M12",
    20.0: "M16",
    25.0: "M20",
}

#: ISO 10642 countersunk (flat) head screws: thread -> socket across-flats, mm.
#: Checked 2026-10-06 against accu-components.com product pages (M3..M12) and
#: engineersedge.com's ISO 10642 note; the spec's own M8 -> 5 example agrees. M2 and
#: M2.5 came in with ISO 10642:2019 (its foreword, read 2026-10-07); their keys are
#: from fasten.it's and Westfield's copies of its table: M2 takes ISO 2936's 1.3.
#: ISO 4026 to 4029 hexagon socket set screws (flat, cone, dog and cup point, DIN 913
#: to 916): thread -> socket across-flats, mm. One key for every point; read
#: 2026-10-08 from fasten.it's DIN EN ISO 4026 table (2004), the issue's M3 to M10
#: agreeing. ISO 4026 runs M1.6 to M24 and has no M14, M18 or M22.
SET_KEY_AF: dict[str, float] = {
    "M1.6": 0.7,
    "M2": 0.9,
    "M2.5": 1.3,
    "M3": 1.5,
    "M4": 2.0,
    "M5": 2.5,
    "M6": 3.0,
    "M8": 4.0,
    "M10": 5.0,
    "M12": 6.0,
    "M16": 8.0,
    "M20": 10.0,
    "M24": 12.0,
}

FLAT_KEY_AF: dict[str, float] = {
    "M2": 1.3,
    "M2.5": 1.5,
    "M3": 2.0,
    "M4": 2.5,
    "M5": 3.0,
    "M6": 4.0,
    "M8": 5.0,
    "M10": 6.0,
    "M12": 8.0,
    "M14": 10.0,  # ISO 10642:2004's own table (the iTeh preview), as M16 and M20
    "M16": 10.0,
    "M20": 12.0,
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
            "#0": "0.050",
            "#1": "1/16",
            "#2": "5/64",
            "#3": "5/64",
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
            "#0": "0.035",
            "#1": "0.050",
            "#2": "0.050",
            "#3": "1/16",
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
            "#0": "0.035",
            "#1": "0.050",
            "#2": "0.050",
            "#3": "1/16",
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
# Inch set screws, ASME B18.3 Table 5A (fasten.it's copy, 2003, read 2026-10-08):
# smaller keys than the heads take. Monster Bolts' key chart agrees from #0 to 3/8,
# and Albany County Fasteners' set screw chart on #8, #10, 1/4, 3/8 and 1/2.
SET_KEY_AF.update(
    _inch(
        {
            "#0": "0.028",
            "#1": "0.035",
            "#2": "0.035",
            "#3": "0.050",
            "#4": "0.050",
            "#6": "1/16",
            "#8": "5/64",
            "#10": "3/32",
            "1/4": "1/8",
            "5/16": "5/32",
            "3/8": "3/16",
            "7/16": "7/32",
            "1/2": "1/4",
            "5/8": "5/16",
            "3/4": "3/8",
        }
    )
)

#: ISO 4032 hex nuts and ISO 4017 hex head bolts: thread -> across-flats, mm.
#: Checked 2026-10-06 against wermac.org's DIN/ISO nut table. Note the ISO/DIN
#: split: DIN 934 gives M10 -> 17, M12 -> 19, M14 -> 22, M22 -> 32; these are the
#: ISO values, and a DIN-dimensioned model will need the sidecar's `tool:` until
#: detection learns to measure the hex instead of trusting the thread. M1.6 to M2.5
#: read 2026-10-07 from ISO 4032:2012's and ISO 4017:2022's own tables (iTeh
#: previews); ISO 4032:2023 keeps every nut below M5 in an informative annex.
HEX_AF: dict[str, float] = {
    "M1.6": 3.2,
    "M2": 4.0,
    "M2.5": 5.0,
    "M3": 5.5,
    "M4": 7.0,
    "M5": 8.0,
    "M6": 10.0,
    "M8": 13.0,
    "M10": 16.0,
    "M12": 18.0,
    "M14": 21.0,
    "M16": 24.0,
    "M18": 27.0,  # ISO 4017:2022 Table 1 (iTeh preview, read 2026-10-08), as ISO 4032
    "M20": 30.0,
    "M22": 34.0,  # the same
    "M24": 36.0,
}

# Inch nuts: ASME B18.2.2 hex nuts (1/4 and up) and ASME B18.6.3 machine screw nuts
# (#0 to #10), basic width across flats. Checked 2026-10-06 (#0 to #3 2026-10-07):
# Engineers Edge and torqbolt agree for B18.2.2; Engineers Edge, torqbolt and Aspen
# Fasteners product pages for B18.6.3 (Aspen's #8 maximum, 0.334, sits below its own
# basic size and is taken for a typo).
HEX_AF.update(
    _inch(
        {
            "#0": "5/32",
            "#1": "5/32",
            "#2": "3/16",
            "#3": "3/16",
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

#: Keyed heads' outlines, thread -> (head diameter, head height), mm, as their
#: standards give them (the maxima): what a plain cylinder drawn for a head is
#: compared with, to tell a button head from a socket head with no drive in the
#: model (issue #31). ISO 4762 socket heads and ISO 7380-1 button heads: fasten.it's
#: tables, and Engineers Edge's ISO 7380 chart for the button heads' heights, read
#: 2026-10-06; M1.6 to M2.5 from ISO 4762:2004's own Table 1, 2026-10-07. Inch
#: socket heads, ASME B18.3: AFT Fasteners' table, 2026-10-06; #0 to #3 from the
#: Unbrako guide and fasten.it's table 1A, which agree, 2026-10-07.
#: No inch button-head table was to be had that agreed with itself, so an inch head
#: is held to the socket head's alone.
HEAD_OUTLINE: dict[Head, dict[str, tuple[float, float]]] = {
    Head.SOCKET: {
        "M1.6": (3.0, 1.6),
        "M2": (3.8, 2.0),
        "M2.5": (4.5, 2.5),
        "M3": (5.5, 3.0),
        "M4": (7.0, 4.0),
        "M5": (8.5, 5.0),
        "M6": (10.0, 6.0),
        "M8": (13.0, 8.0),
        "M10": (16.0, 10.0),
        "M12": (18.0, 12.0),
        "M14": (21.0, 14.0),
        "M16": (24.0, 16.0),
        "M20": (30.0, 20.0),
        "M24": (36.0, 24.0),
        **{
            size: (dk * _MM_PER_INCH, k * _MM_PER_INCH)
            for size, (dk, k) in {
                "#0": (0.096, 0.060),
                "#1": (0.118, 0.073),
                "#2": (0.140, 0.086),
                "#3": (0.161, 0.099),
                "#4": (0.183, 0.112),
                "#6": (0.226, 0.138),
                "#8": (0.270, 0.164),
                "#10": (0.312, 0.190),
                "1/4": (0.375, 0.250),
                "5/16": (0.469, 0.312),
                "3/8": (0.562, 0.375),
                "7/16": (0.656, 0.438),
                "1/2": (0.750, 0.500),
                "5/8": (0.938, 0.625),
                "3/4": (1.125, 0.750),
            }.items()
        },
    },
    Head.BUTTON: {
        "M3": (5.7, 1.65),
        "M4": (7.6, 2.2),
        "M5": (9.5, 2.75),
        "M6": (10.5, 3.3),
        "M8": (14.0, 4.4),
        "M10": (17.5, 5.5),
        "M12": (21.0, 6.6),
        "M16": (28.0, 8.8),
    },
}

#: ISO 7379 shoulder screws' heads, shoulder diameter -> (head diameter, head
#: height), mm, the maxima, as fasten.it's ISO 7379 table gives them (read
#: 2026-10-07; McMaster's ISO 7379 listing agrees but for the 8 mm shoulder's
#: height, 6, inside the fit). A shoulder screw's head goes with its shoulder, the
#: widest round under it, not with its thread: a plain head 13 across and 5.5
#: high over an 8 mm shoulder is an M6 shoulder screw's (issue #48).
SHOULDER_OUTLINE: dict[float, tuple[float, float]] = {
    6.5: (10.0, 4.5),
    8.0: (13.0, 5.5),
    10.0: (16.0, 7.0),
    13.0: (18.0, 9.0),
    16.0: (24.0, 11.0),
    20.0: (30.0, 14.0),
    25.0: (36.0, 16.0),
}

#: The standards the outlines above come from, for a basis to name.
HEAD_STANDARD: dict[tuple[Head, bool], str] = {
    (Head.SOCKET, True): "ISO 4762",
    (Head.SOCKET, False): "ASME B18.3",
    (Head.BUTTON, True): "ISO 7380-1",
    (Head.SHOULDER, True): "ISO 7379",
}


#: DIN 934's across flats where it parts from ISO 4032 (torqbolt.com's DIN 934
#: table, read 2026-10-06): the spanner a nut drawn to DIN takes.
DIN_HEX_AF: dict[str, float] = {"M10": 17.0, "M12": 19.0, "M14": 22.0, "M22": 32.0}

#: The smallest across flats a nut standard allows a hex of each spanner size, mm,
#: keyed by that size. A spanner fits a hex anywhere from here up to its own size,
#: so a model drawn inside the band (an M8 nut at 12.8) takes it. Metric: ISO 4032
#: and DIN 934 (torqbolt.com's tables, read 2026-10-06; product grade A to M16, B
#: above, hence the wider bands). Inch: ASME B18.2.2 hex nuts (amesweb.info) and
#: B18.6.3 machine screw nuts (torqbolt.com), read the same day; where both give a
#: size, the smaller minimum. Hex heads are held to their nut's band: ISO 4014/4017
#: and ASME B18.2.1 share the sizes, and their own minimums weren't to be had. A
#: size with no row (a hex key, 13/16 in) has no band: only its own size fits.
HEX_AF_MIN: dict[float, float] = {
    3.2: 3.02,  # ISO 4032:2012, product grade A (issue #83)
    4.0: 3.82,
    5.0: 4.82,
    5.5: 5.32,
    6.0: 5.82,
    7.0: 6.78,
    8.0: 7.78,
    10.0: 9.78,
    11.0: 10.73,
    13.0: 12.73,
    16.0: 15.73,
    17.0: 16.73,
    18.0: 17.73,
    19.0: 18.67,
    21.0: 20.67,
    22.0: 21.67,
    24.0: 23.67,
    27.0: 26.16,
    30.0: 29.16,
    32.0: 31.0,
    34.0: 33.0,
    36.0: 35.0,
    41.0: 40.0,
    46.0: 45.0,
    50.0: 49.0,
    **{
        inch_mm(size): minimum * _MM_PER_INCH
        for size, minimum in {
            "5/32": 0.150,
            "3/16": 0.180,
            "1/4": 0.241,
            "5/16": 0.302,
            "11/32": 0.332,
            "3/8": 0.362,
            "7/16": 0.423,
            "1/2": 0.489,
            "9/16": 0.545,
            "5/8": 0.607,
            "11/16": 0.675,
            "3/4": 0.736,
            "7/8": 0.861,
            "15/16": 0.922,
            "1-1/8": 1.088,
            "1-5/16": 1.269,
            "1-1/2": 1.450,
        }.items()
    },
}


def in_hex_band(measured: float, af: float) -> bool:
    """Whether a measured hex lies in a nut standard's band for the spanner size ``af``."""
    minimum = HEX_AF_MIN.get(af)
    return minimum is not None and minimum - 1e-6 <= measured <= af + 1e-6


#: The most a hexagon socket may be across flats, by the key that goes into it, mm
#: (issue #82). A key goes into a socket, so a socket is never smaller than its key
#: and the standards draw it a little larger: ISO 4762:2004's s max, which ISO
#: 7380-1 and ISO 10642 share (1.5 to 10 from its own Table 1, 12 to 19 from Fuller
#: Fasteners' copy, read 2026-10-07; the 1.3, ISO 10642's M2, from Westfield's);
#: ISO 7379's, tighter from 5 mm up, sit inside these. Inch: ASME B18.3's J max
#: (amesweb, Engineers Edge's gauge table agreeing). A model drawn at the most, as
#: bd_warehouse draws every socket, takes the key.
RECESS_AF_MAX: dict[float, float] = {
    1.3: 1.36,
    1.5: 1.58,
    2.0: 2.08,
    2.5: 2.58,
    3.0: 3.08,
    4.0: 4.095,
    5.0: 5.14,
    6.0: 6.14,
    8.0: 8.175,
    10.0: 10.175,
    12.0: 12.212,
    14.0: 14.212,
    17.0: 17.23,
    19.0: 19.275,
    **{
        inch_mm(key): most * _MM_PER_INCH
        for key, most in {
            "0.035": 0.0355,
            "0.050": 0.0510,
            "1/16": 0.0635,
            "5/64": 0.0791,
            "3/32": 0.0952,
            "7/64": 0.1111,
            "1/8": 0.1270,
            "9/64": 0.1426,
            "5/32": 0.1587,
            "3/16": 0.1900,
            "7/32": 0.2217,
            "1/4": 0.2530,
            "5/16": 0.3160,
            "3/8": 0.3790,
            "7/16": 0.4420,
            "1/2": 0.5050,
            "9/16": 0.5680,
            "5/8": 0.6310,
            "3/4": 0.7570,
        }.items()
    },
}

#: How far past its standards' most a socket may be drawn and still take its key,
#: mm: a model drawn loosely (issue #82), which the result's notes say. bd_warehouse's
#: ISO 10642 M4, 2.60 (DIN 7991's most), is 0.02 past ISO 10642's 2.58.
RECESS_LOOSE_MM = 0.15


def in_recess_band(measured: float, key: float) -> bool:
    """Whether a measured socket is one the key ``key`` goes into, by the standards."""
    return key - 1e-6 <= measured <= RECESS_AF_MAX.get(key, key) + 1e-6


def loosely_fits(measured: float, key: float) -> bool:
    """Whether a socket the key goes into is drawn past the standards, but within reason."""
    top = RECESS_AF_MAX.get(key, key)
    return top + 1e-6 < measured <= top + RECESS_LOOSE_MM + 1e-6


#: A Torx recess's point to point, A, by size: from the GO gauge's least to the NO GO
#: gauge's most, mm. ISO 10664:2014 sets no tolerance on the recess itself, only the
#: gauges that must and mustn't go in (its Tables 3 and 4, read 2026-10-07; the 2005
#: edition agrees, and gives T45's GO): a recess between them takes the size (issue
#: #82). The nominal A of every size sits inside its own band.
TORX_RECESS_A: dict[str, tuple[float, float]] = {
    "T6": (1.695, 1.785),
    "T8": (2.335, 2.425),
    "T10": (2.761, 2.852),
    "T15": (3.295, 3.385),
    "T20": (3.879, 3.970),
    "T25": (4.451, 4.566),
    "T27": (5.009, 5.126),
    "T30": (5.543, 5.659),
    "T40": (6.673, 6.814),
    "T45": (7.841, 7.983),
    "T50": (8.857, 8.999),
    "T55": (11.245, 11.412),
}


def standard_hex_afs(size: Size) -> set[float]:
    """Every across flats a standard gives this thread's hex: its nut, DIN nut and head."""
    found = {spanner_af(size), spanner_af(size, head=True), DIN_HEX_AF.get(size.designation)}
    return {af for af in found if af is not None}


_KEY_TABLES: dict[Head, dict[str, float]] = {
    Head.SOCKET: SOCKET_KEY_AF,
    Head.BUTTON: BUTTON_KEY_AF,
    Head.FLAT: FLAT_KEY_AF,
    Head.SHOULDER: SHOULDER_KEY_AF,
    Head.SET: SET_KEY_AF,
}


#: The standard each keyed head's key table is read from, by head and metric or inch,
#: and the Torx screws': what a size its table lacks is said to be missing from.
KEY_STANDARD: dict[tuple[Head, bool], str] = {
    (Head.SOCKET, True): "ISO 4762",
    (Head.SOCKET, False): "ASME B18.3",
    (Head.BUTTON, True): "ISO 7380-1",
    (Head.BUTTON, False): "ASME B18.3",
    (Head.FLAT, True): "ISO 10642",
    (Head.FLAT, False): "ASME B18.3",
    (Head.SHOULDER, True): "ISO 7379",
    (Head.SET, True): "ISO 4026",
    (Head.SET, False): "ASME B18.3",
    (Head.TORX, True): "ISO 14579",
}


def no_such_head(head: Head, size: Size) -> str:
    """Why a head of this size has no key: its standard has none (issue #83).

    ``ISO 7380-1 has no M2 button head``: the standard is the reason, not the kit.
    Where no table of the head's system is held (an inch shoulder or Torx screw),
    there is no standard to name, and it says so as it always has.
    """
    standard = KEY_STANDARD.get((head, size.is_metric))
    if standard is not None and head is Head.SET:
        return f"{standard} has no {size.designation} set screw"
    if standard is not None:
        return f"{standard} has no {size.designation} {head.value} head"
    if head is Head.TORX:
        return f"no Torx size for a {size.designation} head"
    return f"no standard key for a {size.designation} {head.value} head"


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
#: suppliers sell M8 pan heads as T40; the standards say T45. All four start at M2
#: (their own tables, read 2026-10-07): no M1.6 Torx screw is standard.
TORX_SIZE: dict[str, str] = {
    "M2": "T6",
    "M2.5": "T8",
    "M3": "T10",
    "M4": "T20",
    "M5": "T25",
    "M6": "T30",
    "M8": "T45",
    "M10": "T50",
    "M12": "T55",
}

#: Phillips recess number by thread. The ISO cross-recess standards agree size for size
#: across head styles: ISO 7045 (pan), 7046-1 and 7046-2 (countersunk) and 7047 (raised
#: countersunk), each 2011's Table 1, read from the iTeh previews 2026-10-07 (ISO 7046-2
#: starts at M2). M8 and M10 take PH4 (issue #101). Inch: ASME B18.6.3 Type I, pan and
#: flat countersunk alike, as the suppliers' copies give it.
PHILLIPS_NUMBER: dict[str, int] = {
    "M1.6": 0,
    "M2": 0,
    "M2.5": 1,
    "M3": 1,
    "M3.5": 2,
    "M4": 2,
    "M5": 2,
    "M6": 3,
    "M8": 4,
    "M10": 4,
    "#0": 0,
    "#1": 0,
    "#2": 1,
    "#3": 1,
    "#4": 1,
    "#6": 2,
    "#8": 2,
    "#10": 2,
    "#12": 3,
    "1/4": 3,
}

#: A cross recess's m, its diameter at the head's face, by Phillips number, mm: the
#: least and most the cross-recessed product standards give, types H and Z both, read
#: from fasten.it's copies 2026-10-08 (issue #125): ISO 7045 (pan, M1.6 to M10), ISO
#: 7046 (countersunk, both head forms, M2 to M10), ISO 7049 and 7050 (pan and
#: countersunk tapping screws, ST2.2 to ST9.5). The numbers' ranges don't meet: a span
#: drawn between two is neither's.
PHILLIPS_SPAN: dict[int, tuple[float, float]] = {
    0: (1.6, 2.1),
    1: (2.5, 3.2),
    2: (3.9, 5.2),
    3: (6.2, 6.9),
    4: (8.5, 10.1),
}


def phillips_by_span(span: float) -> int | None:
    """The Phillips number whose recesses are this span across their wings, if one."""
    return next(
        (n for n, (least, most) in PHILLIPS_SPAN.items() if least - 1e-6 <= span <= most + 1e-6),
        None,
    )
