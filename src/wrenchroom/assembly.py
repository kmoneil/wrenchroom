"""Parts, names and assembled positions: the input side of every check.

An assembly is the parts, each a solid with a name, in their assembled positions.
Nothing here knows about fasteners or tools; this module answers only "what solids are
there and what are they called".

Names are load-bearing: fastener detection starts from them (sidecar globs now, name
patterns at M4), so a STEP import that lost or mangled names would quietly turn every
downstream match off. The import keeps the STEP product and instance names and makes
repeats unique by appending ``#2``, ``#3``, in document order. Verified against a
build123d round-trip: labels survive on leaf solids, duplicates arrive duplicated.

Units are millimetres internally. OCP's STEP reader converts from the file's declared
units on import, so nothing here rescales.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from build123d import Compound, Shape, import_step

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

#: The name given to a solid that arrived with no name at all. It still gets the
#: ``#2`` treatment, so several anonymous solids stay distinguishable.
UNNAMED = "unnamed"


@dataclass(frozen=True)
class Part:
    """One named solid in its assembled position.

    Attributes:
        name: Unique within the assembly; the STEP product or instance name, a
            build123d label, or whatever was passed to ``from_shapes``.
        shape: The geometry, usually one solid. A part handed over as a multi-solid
            shape is kept whole: the caller grouped it, the caller meant it.
    """

    name: str
    shape: Shape


class Assembly:
    """The parts, each a solid with a name, in their assembled positions.

    Build one with :meth:`from_step`, :meth:`from_shapes` or :meth:`from_compound`;
    the constructor itself takes already-unique parts and is what the three share.
    """

    def __init__(self, parts: Iterable[Part]) -> None:
        self.parts: tuple[Part, ...] = tuple(parts)
        if not self.parts:
            msg = "an assembly needs at least one part"
            raise ValueError(msg)
        counts = Counter(part.name for part in self.parts)
        repeated = sorted(name for name, count in counts.items() if count > 1)
        if repeated:
            msg = f"part names must be unique; repeated: {', '.join(repeated)}"
            raise ValueError(msg)

    @classmethod
    def from_step(cls, path: str | Path) -> Assembly:
        """Read a STEP file, keeping part names and making repeats unique.

        Args:
            path: The STEP file (AP203, AP214 or AP242).

        Returns:
            The assembly, one part per leaf solid, in document order.

        Raises:
            ValueError: If the file contains no solids.
        """
        shape = import_step(str(path))
        return cls(_unique(_leaves(shape), source=str(path)))

    @classmethod
    def from_shapes(cls, shapes: Iterable[tuple[str, Shape]]) -> Assembly:
        """Build an assembly from ``(name, shape)`` pairs, as from a build script.

        Each pair is one part, kept whole even if the shape holds several solids.
        Repeated names get ``#2``, ``#3`` appended in order, same as the STEP path.
        """
        named = ((name, shape) for name, shape in shapes)
        return cls(_unique(named, source="from_shapes"))

    @classmethod
    def from_compound(cls, compound: Compound) -> Assembly:
        """Build an assembly from a build123d ``Compound`` with labelled children."""
        return cls(_unique(_leaves(compound), source=compound.label or "compound"))

    @property
    def names(self) -> tuple[str, ...]:
        """Every part name, in order."""
        return tuple(part.name for part in self.parts)

    def __iter__(self) -> Iterator[Part]:
        return iter(self.parts)

    def __len__(self) -> int:
        return len(self.parts)

    def __getitem__(self, name: str) -> Part:
        for part in self.parts:
            if part.name == name:
                return part
        msg = f"no part named {name!r}"
        raise KeyError(msg)


def _leaves(shape: Shape, inherited: str = "") -> Iterator[tuple[str, Shape]]:
    """Walk to the leaf solids, carrying the nearest label down to unlabelled ones.

    A leaf with several solids and no labelled children yields one part per solid
    under the same name (the spec's rule: each leaf solid becomes a part); the
    uniquing pass then tells them apart.
    """
    label = shape.label or inherited
    children = list(shape.children)
    if children:
        for child in children:
            yield from _leaves(child, label)
        return
    label = label or UNNAMED
    solids = shape.solids()
    if len(solids) <= 1:
        if solids:
            yield label, shape
        return
    for solid in solids:
        yield label, solid


def _unique(named: Iterable[tuple[str, Shape]], source: str) -> Iterator[Part]:
    """Yield parts with repeats renamed ``name#2``, ``name#3`` in arrival order."""
    seen: Counter[str] = Counter()
    empty = True
    for name, shape in named:
        empty = False
        seen[name] += 1
        unique_name = name if seen[name] == 1 else f"{name}#{seen[name]}"
        yield Part(name=unique_name, shape=shape)
    if empty:
        msg = f"no solids found in {source}"
        raise ValueError(msg)
