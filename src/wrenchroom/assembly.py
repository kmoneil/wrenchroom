"""Parts, names and assembled positions: the input side of every check.

An assembly is the parts, each a solid with a name, in their assembled positions.
Nothing here knows about fasteners or tools; this module answers only "what solids are
there and what are they called".

Names are load-bearing: fastener detection starts from them (sidecar globs now, name
patterns at M4), so a STEP import that lost or mangled names would quietly turn every
downstream match off. The import keeps names and makes repeats unique by appending
``#2``, ``#3``, in document order.

The STEP path reads through XCAF itself rather than build123d's importer, and the
reason is issue #2: a part placed twice as instances of one shared product has ONE
product name and TWO instance names, and build123d names components after the product,
so one instance vanished into the other. Here the instance name (the file's
NEXT_ASSEMBLY_USAGE_OCCURRENCE name, which is what CAD packages put the per-placement
name in) wins, the product name is the fallback, and the nearest ancestor's name after
that.

A leaf drawn as several solids (a nut and its washer as one part) is split one part
per solid, as collision wants, but it is still one thing to a person: its largest
solid keeps the leaf's name, and each other solid is a piece of it
(:attr:`Part.piece_of`). A fastener rule and detection see the leaf, never a piece,
and a fastener's pieces leave its scene with it (issue #28).

A leaf drawn as a surface has no solid. A closed shell bounds a volume as a solid does,
and is taken as that solid. An open shell or loose faces bound nothing a tool could meet:
the part is left out, and its name kept in :attr:`Assembly.surfaces`, for every report
to say (issue #104). It used to be dropped without a word.

Units are millimetres internally. OCP's STEP reader converts from the file's declared
units on import, so nothing here rescales.
"""

from __future__ import annotations

import re
import tempfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from build123d import Compound, Shape, Solid
from build123d.topology import downcast  # the same table build123d's own importer uses
from OCP.collections import Sequence_TDF_Label
from OCP.IFSelect import IFSelect_RetDone
from OCP.Message import Message, Message_Gravity, Message_PrinterOStream
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCP.ShapeFix import ShapeFix_Solid
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label
from OCP.TDocStd import TDocStd_Document
from OCP.TopLoc import TopLoc_Location
from OCP.XCAFDoc import XCAFDoc_DocumentTool

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from OCP.XCAFDoc import XCAFDoc_ShapeTool

#: The name given to a solid that arrived with no name at all. It still gets the
#: ``#2`` treatment, so several anonymous solids stay distinguishable.
UNNAMED = "unnamed"

#: The names OCCT makes up for what has none, reading a STEP file or writing one
#: (which FreeCAD, CadQuery and build123d files then carry): a reference's target
#: entry, and a shape's type. None says what the part is.
_PLACEHOLDER = re.compile(r"=>\[[0-9:]+\]|SOLID|COMPSOLID|COMPOUND|ASSEMBLY")


@dataclass(frozen=True)
class Part:
    """One named solid in its assembled position.

    Attributes:
        name: Unique within the assembly; the STEP product or instance name, a
            build123d label, or whatever was passed to ``from_shapes``.
        shape: The geometry, usually one solid. A part handed over as a multi-solid
            shape is kept whole: the caller grouped it, the caller meant it.
        piece_of: For a leaf read as several solids, the part its largest solid
            became, on every other solid: one part split for collision, never a
            fastener of its own. None for every other part.
    """

    name: str
    shape: Shape
    piece_of: str | None = None


class Assembly:
    """The parts, each a solid with a name, in their assembled positions.

    Build one with :meth:`from_step`, :meth:`from_shapes` or :meth:`from_compound`;
    the constructor itself takes already-unique parts and is what the three share.
    """

    def __init__(self, parts: Iterable[Part], surfaces: Iterable[str] = ()) -> None:
        self.parts: tuple[Part, ...] = tuple(parts)
        #: The leaves drawn as surfaces, open shells or loose faces, which bound no
        #: solid: left out, nothing meeting them, but named for every report to say
        #: (issue #104).
        self.surfaces: tuple[str, ...] = tuple(surfaces)
        if not self.parts:
            msg = "an assembly needs at least one part"
            raise ValueError(msg)
        counts = Counter(part.name for part in self.parts)
        repeated = sorted(name for name, count in counts.items() if count > 1)
        if repeated:
            msg = f"part names must be unique; repeated: {', '.join(repeated)}"
            raise ValueError(msg)
        self._pieces: dict[str, tuple[str, ...]] = {}
        for part in self.parts:
            if part.piece_of is not None:
                self._pieces[part.piece_of] = (*self._pieces.get(part.piece_of, ()), part.name)

    @classmethod
    def from_step(cls, path: str | Path) -> Assembly:
        """Read a STEP file, keeping part names and making repeats unique.

        Args:
            path: The STEP file (AP203, AP214 or AP242).

        Returns:
            The assembly, one part per leaf solid, in document order.

        Raises:
            ValueError: If the file cannot be read or contains no solids.
        """
        return cls(*_parts(_read_step(Path(path)), source=str(path)))

    @classmethod
    def from_shapes(cls, shapes: Iterable[tuple[str, Shape]]) -> Assembly:
        """Build an assembly from ``(name, shape)`` pairs, as from a build script.

        Each pair is one part, kept whole even if the shape holds several solids.
        Repeated names get ``#2``, ``#3`` appended in order, same as the STEP path. A
        shape with no solid is taken as the solids its closed shells bound, if any,
        and is otherwise a surface.
        """
        named = (_whole(name, shape) for name, shape in shapes)
        return cls(*_parts(named, source="from_shapes"))

    @classmethod
    def from_compound(cls, compound: Compound) -> Assembly:
        """Build an assembly from a build123d ``Compound`` with labelled children."""
        return cls(*_parts(_leaves(compound), source=compound.label or "compound"))

    @property
    def names(self) -> tuple[str, ...]:
        """Every part name, in order."""
        return tuple(part.name for part in self.parts)

    def pieces(self, name: str) -> tuple[str, ...]:
        """The other solids of the leaf part ``name`` is, in order: often none."""
        return self._pieces.get(name, ())

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


#: (name, shape, leaf): a leaf of several solids gives one per solid, all with one
#: leaf key, so the uniquing pass can mark the pieces; None for a whole part, and
#: :data:`_SURFACE` for a leaf with no solid.
_Named = tuple[str, Shape, object | None]

#: The leaf key of a leaf drawn as a surface (issue #104).
_SURFACE = object()


def _split(name: str, shape: Shape) -> Iterator[_Named]:
    """One per solid; a leaf of several solids gives its largest first, keyed together.

    A leaf with no solid gives the solids its closed shells bound, if it has any,
    and is otherwise a surface (issue #104).
    """
    solids = shape.solids()
    if len(solids) == 1:
        yield name, shape, None
        return
    solids = solids or _bounded(shape)
    if len(solids) == 1:
        yield name, solids[0], None
    elif solids:
        leaf = object()
        for solid in sorted(solids, key=lambda solid: -solid.volume):
            yield name, solid, leaf
    elif shape.faces():
        yield name, shape, _SURFACE


def _whole(name: str, shape: Shape) -> _Named:
    """A shape kept whole, as from_shapes keeps it; one with no solid as ``_split`` reads it."""
    if shape.solids():
        return name, shape, None
    solids = _bounded(shape)
    if not solids:
        return name, shape, _SURFACE
    return name, solids[0] if len(solids) == 1 else Compound(solids), None


def _bounded(shape: Shape) -> list[Solid]:
    """The solids a shape's closed shells bound: a shell with no free edge is one."""
    solids = []
    for shell in shape.shells():
        bounds = ShapeAnalysis_FreeBounds(shell.wrapped)
        if bounds.GetClosedWires().NbChildren() or bounds.GetOpenWires().NbChildren():
            continue
        solid = Solid(ShapeFix_Solid().SolidFromShell(shell.wrapped))
        if solid.is_valid and solid.volume > 0:
            solids.append(solid)
    return solids


def _parts(named: Iterable[_Named], source: str) -> tuple[Iterator[Part], tuple[str, ...]]:
    """The parts, uniquely named, and the names of the leaves drawn as surfaces."""
    named = list(named)
    surfaces = tuple(name for name, _, leaf in named if leaf is _SURFACE)
    solid = [entry for entry in named if entry[2] is not _SURFACE]
    if not solid and surfaces:
        shown = ", ".join(surfaces[:_SURFACES_SHOWN])
        more = len(surfaces) - _SURFACES_SHOWN
        shown += f" and {more} more" if more > 0 else ""
        msg = f"no solids found in {source}: {len(surfaces)} parts are surfaces only ({shown})"
        raise ValueError(msg)
    return _unique(solid, source), surfaces


#: How many surfaces' names a model of nothing else names before "and N more".
_SURFACES_SHOWN = 3


def _leaves(shape: Shape, inherited: str = "") -> Iterator[_Named]:
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
    yield from _split(label or UNNAMED, shape)


def _unique(named: Iterable[_Named], source: str) -> Iterator[Part]:
    """Yield parts with repeats renamed ``name#2``, ``name#3`` in arrival order.

    A leaf's first solid (its largest) is the part; the rest are its pieces.
    """
    seen: Counter[str] = Counter()
    firsts: dict[object, str] = {}
    empty = True
    for name, shape, leaf in named:
        empty = False
        seen[name] += 1
        unique_name = name if seen[name] == 1 else f"{name}#{seen[name]}"
        piece_of = None
        if leaf is not None and leaf in firsts:
            piece_of = firsts[leaf]
        elif leaf is not None:
            firsts[leaf] = unique_name
        yield Part(name=unique_name, shape=shape, piece_of=piece_of)
    if empty:
        msg = f"no solids found in {source}"
        raise ValueError(msg)


# ---------------------------------------------------------------------------
# The XCAF walk behind from_step.
# ---------------------------------------------------------------------------


def _read_step(path: Path) -> Iterator[_Named]:
    """Yield (name, shape) per leaf, instance names winning over product names."""
    doc = TDocStd_Document(TCollection_ExtendedString("XCAF"))
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    with _kernel_quiet() as heard:
        status = reader.ReadFile(str(path))
        if status == IFSelect_RetDone:
            reader.Transfer(doc)
    if status != IFSelect_RetDone:
        said = "; ".join(heard)
        msg = f"cannot read {path} as STEP" + (f" ({said})" if said else "")
        raise ValueError(msg)
    roots = Sequence_TDF_Label()
    shape_tool.GetFreeShapes(roots)
    for index in range(1, roots.Length() + 1):
        yield from _walk_label(shape_tool, roots.Value(index), TopLoc_Location(), "")


@contextmanager
def _kernel_quiet() -> Iterator[list[str]]:
    """Hold the CAD kernel's own messages, and hand back what it said, cleaned.

    OCP's STEP reader reports a bad file on its default messenger, which prints
    to stdout in colour: past wrenchroom's own output, and into a report piped
    from stdout (issue #33). While the block runs, the messenger's printers are
    set aside for one writing to a file; after it, the list holds each message.
    """
    messenger = Message.DefaultMessenger_s()
    saved = list(messenger.Printers())
    for printer in saved:
        messenger.RemovePrinter(printer)
    heard: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        log = Path(directory) / "kernel.log"
        capture = Message_PrinterOStream(str(log), False, Message_Gravity.Message_Warning)
        messenger.AddPrinter(capture)
        try:
            yield heard
        finally:
            messenger.RemovePrinter(capture)
            del capture  # closes the file
            for printer in saved:
                messenger.AddPrinter(printer)
            text = log.read_text(errors="replace") if log.exists() else ""
            heard.extend(_kernel_lines(text))


def _kernel_lines(text: str) -> list[str]:
    """The kernel's messages without its decoration: "**** ERR StepFile : ... ****"."""
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"^\*+\s*(?:ERR|FAIL|WARNING|WARN|INFO)?\s*\w*\s*:\s*|\s*\*+$", "", raw)
        line = " ".join(line.split())
        if line:
            lines.append(line)
    return lines


def _walk_label(
    shape_tool: XCAFDoc_ShapeTool,
    label: TDF_Label,
    location: TopLoc_Location,
    inherited: str,
    instance: str = "",
) -> Iterator[_Named]:
    """Walk one product label, carrying the accumulated placement and names.

    ``instance`` is the component (NAUO) name of the reference that brought us
    here. At a leaf it OUTRANKS the product's own name: two placements of one
    shared product have one product name between them and their real names on
    the instances, and product-name-first is exactly issue #2. For a
    subassembly it only joins the inheritance chain, so leaves inside keep
    their own names.
    """
    if shape_tool.IsAssembly_s(label):
        name = instance or _label_name(label) or inherited
        components = Sequence_TDF_Label()
        shape_tool.GetComponents_s(label, components)
        for index in range(1, components.Length() + 1):
            component = components.Value(index)
            placed = location.Multiplied(shape_tool.GetLocation_s(component))
            target = component
            if shape_tool.IsReference_s(component):
                target = TDF_Label()
                shape_tool.GetReferredShape_s(component, target)
            yield from _walk_label(
                shape_tool, target, placed, name, instance=_label_name(component)
            )
        return
    name = instance or _label_name(label) or inherited
    topo = shape_tool.GetShape_s(label).Moved(location)
    yield from _split(name or UNNAMED, Shape.cast(downcast(topo)))  # no solid: no part


def _label_name(label: TDF_Label) -> str:
    """A label's name, or "" for none: a name OCCT made up for a nameless one counts as none.

    A reference with no name of its own is named by its target's entry,
    ``=>[0:1:1:32]``, and the shape it refers to by its type, ``SOLID`` or
    ``ASSEMBLY`` (issue #84): no name a person gave. The part then takes its
    assembly's name, as any nameless leaf does: a subassembly's own body is
    called after the subassembly.
    """
    attribute = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        name = TCollection_AsciiString(attribute.Get()).ToCString()
        return "" if _PLACEHOLDER.fullmatch(name) else name
    return ""
