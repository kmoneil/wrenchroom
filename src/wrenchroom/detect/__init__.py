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
  said and confidence is no more than medium, for a person to settle. A carriage
  bolt holds itself and is never checked, so a name alone never makes one:
  without a square neck in the solid it is not covered.
- **size**: a size the solid's drive settles outranks the name's; the name's
  outranks a measured shank or bore (which a thread drawn at its minor diameter
  can fool). A gland takes no size at all: its hex is not its thread's nut.
- **across flats**: measured, when the solid shows a hex or a socket.
- **length**: the name's, when it gives one.

A name whose fastener noun has ordinary words after it (``box_gland_vent``) is
only a candidate: it is taken when its solid shows a drive a tool fits, at no
more than medium confidence, and otherwise passed over, which every report says.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from wrenchroom.detect.geometry import ShapeReading, read_shape
from wrenchroom.detect.names import NameHint, read_name
from wrenchroom.fasteners import Fastener, Head, Kind, PassedOver, in_hex_band
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
    only when its solid shows a drive; otherwise it is passed over, with why.
    """
    fasteners: list[Fastener] = []
    passed: list[PassedOver] = []
    for part in parts:
        hint = read_name(part.name)
        if hint is None:
            continue
        reading = read_shape(part.shape, hint.kind)
        if hint.needs_drive and not shows_drive(reading):
            passed.append(PassedOver(part.name, hint.kind, f"{hint.basis}; {NO_DRIVE}"))
        else:
            fasteners.append(describe(part, hint, reading))
    return Found(tuple(fasteners), tuple(passed))


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
    return snap(af, tuple(HEX_KEYS)) is not None


def describe(part: Part, hint: NameHint, reading: ShapeReading | None = None) -> Fastener:
    """One named fastener, its name's hint completed and checked by its solid."""
    reading = reading if reading is not None else read_shape(part.shape, hint.kind)
    if hint.unless_hex and reading.drive_af is not None:
        # "nut_deep_well_nut": a nut deep in a well, as its hex says (issue #29).
        hint = replace(hint, kind=Kind.NUT)
    gland = not hint.socket_allowed
    head, head_note, reason = _head(hint, reading)
    size = None if gland else _size(hint, reading)
    if hint.kind is Kind.NUT and reading.drive_af is None:
        reason = reason or NO_HEX  # a round nut: nothing a spanner can grip
    not_covered = hint.not_covered or reason
    used = [head_note] if head_note else []
    if hint.unless_hex and hint.kind is Kind.NUT:
        used.append("a hex, so a nut")
    if reading.drive_af is not None:
        used.append(f"{reading.drive_af:g} across flats")
    if size is not None and (reading.size_from_drive or hint.size is None):
        used.append(f"{size.designation} measured")
    basis = hint.basis + (f"; solid: {', '.join(used)}" if used else "")
    return Fastener(
        name=part.name,
        kind=hint.kind,
        head=head,
        size=size,
        length_mm=hint.length_mm,
        socket_allowed=hint.socket_allowed,
        drive_af=reading.drive_af,
        source="name+geometry" if used else "name",
        basis=basis,
        not_covered=not_covered,
        confidence=_confidence(hint, reading, head, size, not_covered),
    )


def _confidence(
    hint: NameHint,
    reading: ShapeReading,
    head: Head | None,
    size: Size | None,
    not_covered: str | None,
) -> str:
    """high, medium or low: see Fastener.confidence."""
    has_size = size is not None or reading.drive_af is not None
    if not_covered or not has_size or (hint.kind is Kind.SCREW and head is None):
        return "low"
    guessed_head = hint.kind is Kind.SCREW and reading.head is None and hint.head is None
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
        return reading.head, reading.head.value + said, None
    if hint.head is Head.CARRIAGE:
        return None, None, NO_SQUARE_NECK
    if hint.head is not None:
        return hint.head, None, None
    if reading.head_guess is not None:
        note = f"{reading.head_guess.value} by its outline"
        if reading.head_standard:
            note += f", {reading.head_standard}'s"
        elif reading.head_unmatched:
            note += ", fitting no standard head"  # a guess from proportions alone
        return reading.head_guess, note, None
    return None, None, None


def _size(hint: NameHint, reading: ShapeReading) -> Size | None:
    if reading.size is not None and reading.size_from_drive:
        return reading.size
    return hint.size or reading.size
