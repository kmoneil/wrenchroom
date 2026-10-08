"""Finding fasteners without a sidecar (M4): from part names, then from geometry.

Spec 5.2's order: names first, then geometry, then the sidecar, each overriding the
one before. A sidecar rule that matches a part describes it outright, so this
module only ever describes parts no rule covers (``check`` sees to that). M4 reads
parts whose names say something; telling an anonymous solid is a screw by its
shape alone is v1.1.

How a detected fastener is put together, field by field:

- **kind**: the name's. Geometry doesn't second-guess a nut for a screw.
- **head**: a drive the solid shows (a hex, a socket, a cross, a slot, a
  square neck) outranks the name; the name outranks a guess from the head's
  outline. Where the drive and the name disagree, the basis says what the name
  said and confidence is no more than medium, for a person to settle. Which
  keyed head a hex socket is in (socket, button, countersunk) only the outline
  says, so a keyed head the name gives stands; where a countersink or a
  standard's outline shows another, the basis says so and confidence is low
  (issue #81). A carriage bolt holds itself and is never checked, so a name
  alone never makes one: without a square neck in the solid it is not covered.
- **size**: a size the solid's drive settles outranks the name's; the name's
  outranks a measured shank or bore (which a thread drawn at its minor diameter
  can fool). Where the solid is drawn as another size, its drive and its shank
  or bore both saying so, or its shank alone with no drive, and no thread of
  the name's size could be drawn so, the solid's is taken, and noted, at low
  confidence (issue #117). A gland takes no size at all: its hex is not its
  thread's nut.
- **across flats**: measured, when the solid shows a hex or a socket.
- **length**: the name's, when it gives one.

A name whose fastener noun has ordinary words after it (``box_gland_vent``) is
only a candidate: it is taken when its solid shows a drive a tool fits, at no
more than medium confidence, and otherwise passed over, which every report says.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from wrenchroom.detect.geometry import SIZE_SNAP_MM, ShapeReading, looks_like, read_shape
from wrenchroom.detect.names import NameHint, ends_in_part_noun, read_name
from wrenchroom.fasteners import (
    Fastener,
    Head,
    Kind,
    PassedOver,
    in_hex_band,
    in_recess_band,
    loosely_fits,
    thread_minor_mm,
)
from wrenchroom.tools.fingers import HAND
from wrenchroom.tools.hex_keys import HEX_KEYS
from wrenchroom.tools.sizes import FLATS, snap

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from wrenchroom.assembly import Part
    from wrenchroom.fasteners import Size

__all__ = [
    "Found",
    "NameHint",
    "ShapeReading",
    "describe",
    "find",
    "find_fasteners",
    "read_name",
    "read_shape",
    "shows_drive",
]

#: Why a carriage bolt by name alone isn't trusted.
NO_SQUARE_NECK = (
    "named as a carriage bolt, but the solid shows no square neck; a carriage bolt "
    "is never checked, so say head: carriage in the sidecar if it is one"
)


#: Why a candidate name's part was passed over.
NO_DRIVE = "its solid shows no hex, hex socket or cross a tool fits"

#: Why a part named only as an insert, with no thread size, was passed over (issue #84).
NO_THREAD = (
    "named only as an insert, with no thread size or word such as threaded, and "
    "its solid shows no bore: an inlay, not a fixed thread"
)

#: Why a leadscrew's or a ball screw's nut, or the screw itself, is passed over (issue #117).
MOTION = (
    "named for a leadscrew or a ball screw, or the nut that runs on one: a motion "
    "part, which no tool turns"
)

#: Why a part named nothing a fastener is, whose solid looks like one, is listed (issue #95).
NOT_NAMED = "not named as a fastener, but its solid looks like one"

#: Why a nut whose solid is round isn't given its thread's spanner (issue #29).
NO_HEX = (
    "named as a nut, but its solid shows no hex for a spanner to grip; a fixed "
    "thread (a well nut, an insert) is kind: insert in the sidecar"
)


@dataclass(frozen=True)
class Found:
    """What detection made of the parts: the fasteners, and the parts passed over."""

    fasteners: tuple[Fastener, ...]
    passed_over: tuple[PassedOver, ...] = ()


def find(parts: Iterable[Part]) -> Found:
    """Every part whose name says it is a fastener, described from name and solid.

    A candidate name (a fastener noun with ordinary words after it) is taken
    only when its solid shows a drive; otherwise it is passed over, with why. A
    part named nothing a fastener is isn't checked, but one whose solid plainly
    looks like a fastener is passed over too, saying so (issue #95).
    """
    fasteners: list[Fastener] = []
    passed: list[PassedOver] = []
    for part in parts:
        hint = read_name(part.name)
        if hint is None:
            look = looks_like(part.shape)
            if look is not None:
                kind, what = look
                passed.append(PassedOver(part.name, kind, f"{NOT_NAMED}: {what}", named=False))
            continue
        reading = read_shape(part.shape, hint.kind, hint.head)
        missing = _missing(hint, reading)
        if missing is None:
            fasteners.append(describe(part, hint, reading))
        elif not ends_in_part_noun(part.name):  # a nut_plate is a plate (issue #75)
            reason = f"{hint.basis}; {missing}"
            passed.append(PassedOver(part.name, hint.kind, reason, motion=hint.motion))
    return Found(tuple(fasteners), tuple(passed))


def _missing(hint: NameHint, reading: ShapeReading) -> str | None:
    """What a name that needs its solid to say more found missing there; None if nothing.

    A candidate name needs a drive (issue #30); a bare insert, a bore (issue #84).
    A motion part is passed over whatever its solid shows (issue #117).
    """
    if hint.motion:
        return MOTION
    if hint.needs_drive and not shows_drive(reading):
        return NO_DRIVE
    if hint.needs_bore and reading.bore_mm is None:
        return NO_THREAD
    return None


def find_fasteners(parts: Iterable[Part]) -> Iterator[Fastener]:
    """The fasteners :func:`find` finds."""
    yield from find(parts).fasteners


def shows_drive(reading: ShapeReading) -> bool:
    """Whether a solid shows a drive a tool fits: what a candidate name is taken on.

    A hex a spanner fits (a nut, a gland, a hex head), a hex pocket a key fits,
    or a cross. Not a slot or a square, which a slotted block or a plain plate
    shows as readily as a fastener does.
    """
    if reading.head is Head.PHILLIPS:
        return True
    af = reading.drive_af
    if af is None:
        return False
    if reading.head in (None, Head.HEX):
        return snap(af, FLATS) is not None or any(in_hex_band(af, size) for size in FLATS)
    keys = tuple(HEX_KEYS)  # a socket drawn at its standard's most, or loosely (issue #82)
    return snap(af, keys) is not None or any(
        in_recess_band(af, key) or loosely_fits(af, key) for key in keys
    )


def describe(part: Part, hint: NameHint, reading: ShapeReading | None = None) -> Fastener:
    """One named fastener, its name's hint completed and checked by its solid."""
    reading = reading if reading is not None else read_shape(part.shape, hint.kind, hint.head)
    if hint.unless_hex and reading.drive_af is not None:
        # "nut_deep_well_nut": a nut deep in a well, as its hex says (issue #29).
        hint = replace(hint, kind=Kind.NUT)
    gland = not hint.socket_allowed
    # Turned by hand, a thumb screw needs no head: fingers grip whatever it is (#96).
    head, head_note, reason = (None, None, None) if hint.by_hand else _head(hint, reading)
    size, size_note = (None, None) if gland else _size(hint, reading)
    if hint.kind is Kind.NUT and reading.drive_af is None and not hint.by_hand:
        reason = reason or NO_HEX  # a round nut: nothing a spanner can grip
    not_covered = hint.not_covered or reason
    used = [head_note] if head_note else []
    if hint.unless_hex and hint.kind is Kind.NUT:
        used.append("a hex, so a nut")
    if reading.drive_af is not None:
        used.append(f"{reading.drive_af:g} across flats")
    notes = (_head_guess(reading, head),) if _head_guessed(hint, reading) else ()
    # A fixed thread's bore is a guess too: drawn at the tap drill, or the minor, it
    # can sit on another size (an M3 T-nut's 2.8 on #4's 2.845). Its screw outranks it.
    bored = hint.kind is Kind.INSERT and not reading.size_from_drive
    guessed = size is not None and hint.size is None and (reading.size_from_band or bored)
    if guessed and bored:
        used.append(f"{size.designation} by its bore alone")
    elif guessed and reading.head not in (None, Head.HEX):
        used.append(f"{size.designation} by its socket alone, drawn past its standard's most")
    elif guessed:
        used.append(f"{size.designation} by its hex's tolerance band alone")
    elif size is not None and size_note and hint.size is not None:
        used.append(f"{size.designation} measured (the name says {hint.size.designation})")
    elif size is not None and (reading.size_from_drive or hint.size is None):
        used.append(f"{size.designation} measured")
    basis = hint.basis + (f"; solid: {', '.join(used)}" if used else "")
    length, length_note = _length(hint, reading)
    notes = (*notes, *(note for note in (size_note, length_note) if note))
    return Fastener(
        name=part.name,
        kind=hint.kind,
        head=head,
        size=size,
        length_mm=length,
        socket_allowed=hint.socket_allowed,
        tool=HAND if hint.by_hand else None,
        drive_af=reading.drive_af,
        source="name+geometry" if used else "name",
        basis=basis,
        not_covered=not_covered,
        confidence=_confidence(hint, reading, head, size, not_covered or size_note),
        size_guessed=guessed,
        notes=notes,
    )


#: A name's length agrees with its solid's within this, mm, or this fraction of it.
LENGTH_SLACK_MM = 0.5
LENGTH_SLACK = 0.05


def _length(hint: NameHint, reading: ShapeReading) -> tuple[float | None, str | None]:
    """The length to report, and a note where the name's and the solid's disagree (#94).

    The solid's is what the check's way out meets, so where they disagree it is
    the one taken, and the note says what the name said: a screw named M3x12 and
    drawn 8 long, as one drawn twice under two names was.
    """
    named, drawn = hint.length_mm, reading.length_mm
    if named is None or drawn is None:
        return named, None
    if abs(named - drawn) <= max(LENGTH_SLACK_MM, LENGTH_SLACK * named):
        return named, None
    where = "overall" if reading.head in (Head.FLAT, Head.SET) else "under its head"
    note = f"drawn {drawn:.2f} long {where}, where its name says {named:g}: taken as drawn"
    return round(drawn, 2), note


def _head_guessed(hint: NameHint, reading: ShapeReading) -> bool:
    """A screw's head from its proportions alone: no name, drive or standard says it."""
    return (
        hint.kind is Kind.SCREW
        and not hint.by_hand
        and hint.head is None
        and reading.head is None
        and reading.head_guess is not None
        and reading.head_unmatched
    )


def _head_guess(reading: ShapeReading, head: Head | None) -> str:
    """The note a guessed head carries into the check's result (issue #48)."""
    across, high = reading.head_drawn or (0.0, 0.0)
    what = head.value if head is not None else "unknown"
    return (
        f"its head is a guess: drawn {across:.2f} across and {high:.2f} high, it fits no "
        f"standard head, so {what} by its proportions; set head: in the sidecar"
    )


def _confidence(
    hint: NameHint,
    reading: ShapeReading,
    head: Head | None,
    size: Size | None,
    doubted: str | None,
) -> str:
    """high, medium or low: see Fastener.confidence.

    ``doubted`` is a not-covered reason, or a note that the solid is drawn as
    another size than its name's (issue #117): either makes it low.
    """
    has_size = size is not None or reading.drive_af is not None
    headed = hint.kind is not Kind.SCREW or hint.by_hand or head is not None
    if doubted or not has_size or not headed:
        return "low"
    if _head_guessed(hint, reading) or reading.outline_head is not None:
        return "low"
    guessed_head = (
        hint.kind is Kind.SCREW and not hint.by_hand and reading.head is None and hint.head is None
    )
    shank_only = size is not None and hint.size is None and not reading.size_from_drive
    hexed = hint.unless_hex and hint.kind is Kind.NUT  # named an insert, solid a nut
    doubts = (guessed_head, shank_only, _disputed(hint, reading), hint.needs_drive, hexed)
    return "medium" if any(doubts) else "high"


def _disputed(hint: NameHint, reading: ShapeReading) -> bool:
    """The name says one head and the solid's drive shows another."""
    return None not in (hint.head, reading.head) and hint.head is not reading.head


def _head(hint: NameHint, reading: ShapeReading) -> tuple[Head | None, str | None, str | None]:
    """(head, what the solid said about it, a not-covered reason)."""
    if hint.kind is not Kind.SCREW:
        return None, None, None
    if reading.head is not None:
        named = hint.head.value if hint.head and _disputed(hint, reading) else None
        said = f" (the name says {named})" if named else ""
        return reading.head, _outline_said(reading) or reading.head.value + said, None
    if hint.head is Head.CARRIAGE:
        return None, None, NO_SQUARE_NECK
    if hint.head is not None:
        return hint.head, _outline_said(reading, hint.head), None
    if reading.head_guess is not None:
        note = f"{reading.head_guess.value} by its outline"
        if reading.head_standard:
            note += f", {reading.head_standard}'s"
        elif reading.head_unmatched:
            note += ", fitting no standard head"  # a guess from proportions alone
        return reading.head_guess, note, None
    return None, None, None


def _outline_said(reading: ShapeReading, head: Head | None = None) -> str | None:
    """What a countersink or a standard's outline says against the name's head (issue #81).

    The name's keyed head stands (``head``, the reading's own where a pocket showed
    a key goes in); this says what the outline shows instead, for a person to settle.
    """
    kept = head or reading.head
    if reading.outline_head is None or kept is None:
        return None
    return f"a {reading.outline_head.value} head's outline (the name's {kept.value} stands)"


def _size(hint: NameHint, reading: ShapeReading) -> tuple[Size | None, str | None]:
    """The size, and a note where the solid is drawn as another than its name's (#117)."""
    drawn = _drawn_as(hint, reading)
    if drawn is not None:
        return drawn
    if reading.size is not None and reading.size_from_drive:
        return reading.size, None
    return hint.size or reading.size, None


#: A nut's bore may be drawn this much over its thread, as a fraction of it: with
#: clearance, as printed parts' nuts are (an M3's at 3.4).
NUT_BORE_OVER = 1.15


def _drawn_as(hint: NameHint, reading: ShapeReading) -> tuple[Size, str] | None:
    """The size the solid is drawn as, where it isn't the name's, and the note (#117).

    A screw named M5x16 and drawn as an M3: whichever is right, the screw bought
    or the bill of materials is wrong, so it is said. The solid's size counts
    where its drive settles it, and the shank (a nut's bore) is drawn as that
    size too, or as no thread of the name's size could be; or where it has no
    drive and its shank alone is so drawn. A thread is drawn anywhere from its
    minor diameter to its nominal (a nut's bore with clearance over it), so a
    2.9 shank on an M3, or an M5's drawn at its minor that sits on #8, is the
    name's, and quiet. Taken as drawn, as a length is: the solid is what the
    check's tools and way out meet.
    """
    named, solid = hint.size, reading.size
    if named is None or solid is None or solid == named or hint.kind is Kind.INSERT:
        return None
    if reading.drive_af is not None and not reading.size_from_drive:
        return None  # a drive that settled nothing, or a band's guess, which a name outranks
    nut = hint.kind is Kind.NUT
    thread = reading.bore_mm if nut else reading.shank_mm
    if thread is not None:
        most = named.diameter_mm * NUT_BORE_OVER if nut else named.diameter_mm
        could_be = thread_minor_mm(named) - SIZE_SNAP_MM <= thread <= most + SIZE_SNAP_MM
        drawn_so = abs(thread - solid.diameter_mm) <= SIZE_SNAP_MM
        if could_be and not (reading.size_from_drive and drawn_so):
            return None
    elif not reading.size_from_drive:
        return None
    shown = [f"{thread:.2f} {'bore' if nut else 'shank'}"] if thread is not None else []
    if reading.drive_af is not None:
        hexed = nut or reading.head is Head.HEX
        shown.append(f"{reading.drive_af:.2f} {'hex' if hexed else 'socket'}")
    note = (
        f"drawn as {_an(solid.designation)} ({', '.join(shown)}), where its name says "
        f"{named.designation}: taken as drawn"
    )
    return solid, note


def _an(designation: str) -> str:
    """``an M3``, ``a #4``, ``a 1/4``: the article a size takes, read aloud."""
    return f"{'an' if designation.startswith('M') else 'a'} {designation}"
