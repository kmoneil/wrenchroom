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
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wrenchroom.detect.geometry import ShapeReading, read_shape
from wrenchroom.detect.names import NameHint, read_name
from wrenchroom.fasteners import Fastener, Head, Kind

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from wrenchroom.assembly import Part
    from wrenchroom.fasteners import Size

__all__ = ["NameHint", "ShapeReading", "describe", "find_fasteners", "read_name", "read_shape"]

#: Why a carriage bolt by name alone isn't trusted.
NO_SQUARE_NECK = (
    "named as a carriage bolt, but the solid shows no square neck; a carriage bolt "
    "is never checked, so say head: carriage in the sidecar if it is one"
)


def find_fasteners(parts: Iterable[Part]) -> Iterator[Fastener]:
    """Every part whose name says it is a fastener, described from name and solid."""
    for part in parts:
        hint = read_name(part.name)
        if hint is not None:
            yield describe(part, hint)


def describe(part: Part, hint: NameHint) -> Fastener:
    """One named fastener, its name's hint completed and checked by its solid."""
    reading = read_shape(part.shape, hint.kind)
    gland = not hint.socket_allowed
    head, head_note, reason = _head(hint, reading)
    size = None if gland else _size(hint, reading)
    not_covered = hint.not_covered or reason
    used = [head_note] if head_note else []
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
    return "medium" if guessed_head or shank_only or _disputed(hint, reading) else "high"


def _disputed(hint: NameHint, reading: ShapeReading) -> bool:
    """The name says one head and the solid's drive shows another."""
    return None not in (hint.head, reading.head) and hint.head is not reading.head


def _head(hint: NameHint, reading: ShapeReading) -> tuple[Head | None, str | None, str | None]:
    """(head, what the solid said about it, a not-covered reason)."""
    if hint.kind is Kind.NUT:
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
        return reading.head_guess, f"{reading.head_guess.value} by its outline", None
    return None, None, None


def _size(hint: NameHint, reading: ShapeReading) -> Size | None:
    if reading.size is not None and reading.size_from_drive:
        return reading.size
    return hint.size or reading.size
