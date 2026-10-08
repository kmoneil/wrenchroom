"""Fasteners from part names: what a name says, and nothing it doesn't (spec 7.1).

Four kinds of evidence, strongest first:

1. A standard: ``ISO 4762``, ``DIN 912``, ``DIN EN ISO 4017``. Gives kind and head.
2. A McMaster-Carr part number: ``91290A115``. Its series gives kind and head.
3. A description: ``SHCS``, ``button head``, ``hex nut``, ``nyloc``, ``carriage bolt``.
4. A plain noun ending a code-CAD name: ``lift_link_0_bolt_bot`` is a bolt. That
   gives the kind and nothing else, but for a drive word (``torx``, ``phillips``)
   anywhere in the name, which gives the head: ``torx_lid_screw``.

Any of them may come with a thread size (``M6``, ``M6x20``, ``M6x1x20``,
``1/4-20 x 3/4``, ``#10-32``) and a length.

A name reads as a fastener when the word it is about, its last noun, is a
fastener noun, or when it carries a standard or a catalogue number. A name that
is a thread and a length and nothing else (``M3x16``, ``M3-0.5x16``,
``1/4-20x1``), as CAD libraries and suppliers name screws, is a screw candidate:
a stud, a rod or an insert is named so as readily, so its solid must show a
drive, as below (issue #95). A bare size (``M3``) says nothing. A fastener noun
with ordinary words after it is only a candidate (``needs_drive``): ``box_gland_vent``
may be a gland or a vent, ``bolt_hole_cover`` is a cover, and ``pair_nut_held_upper``
is about ``held``. Only its solid can say, by showing a drive (issue #30: such a
name used to be passed over without a word).

Whatever the name doesn't say stays None for geometry to fill in (spec 5.2: names,
then geometry, then the sidecar, each overriding the one before). A name that is
clearly a fastener the kit can't check (a set screw, an M1) comes back with
``not_covered`` and the reason, never as nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from wrenchroom.fasteners import Head, Kind, Size

_MM_PER_INCH = 25.4

#: The multiplication sign people type between size and length ("M6x20" with a
#: real times sign); built from its code point so this file stays plain ASCII.
_TIMES = chr(0xD7)


@dataclass(frozen=True)
class NameHint:
    """What a part's name says about it as a fastener.

    Attributes:
        kind: Screw or nut.
        head: The head, when the name says (a standard, a description, a
            modifier such as ``hex`` or ``carriage``).
        size: The thread size, when the name gives one the tables know.
        length_mm: Length under the head, when the name gives it.
        socket_allowed: False for a cable gland: a cable runs through it.
        basis: What in the name said so, for people (``ISO 4762``,
            ``McMaster 91290A``, ``SHCS``, ``noun 'bolt'``, ``M6x20``).
        not_covered: Set when the name is clearly a fastener the kit can't check,
            with the reason; the check reports it `not-covered`.
        needs_drive: The fastener noun has ordinary words after it
            (``box_gland_vent``): the part is a fastener only if its solid shows
            a drive, and is reported as passed over if it doesn't.
        unless_hex: An insert only by the word before "nut" ("well nut", which
            could as well be a nut deep in a well): a nut after all if its solid
            shows a hex, as a fixed thread's doesn't.
        needs_bore: An insert by the bare word alone (``Logo_Insert``), with no
            thread size and no word that says threaded: a decorative inlay as
            readily as a fixed thread, so a fastener only if its solid shows a
            bore, and passed over if it doesn't (issue #84).
    """

    kind: Kind
    head: Head | None = None
    size: Size | None = None
    length_mm: float | None = None
    socket_allowed: bool = True
    basis: str = ""
    not_covered: str | None = None
    needs_drive: bool = False
    unless_hex: bool = False
    needs_bore: bool = False


# ---------------------------------------------------------------------------
# The tables. Kind and head only: dimensions live in fasteners.py.
# ---------------------------------------------------------------------------

_S, _N = Kind.SCREW, Kind.NUT
_SET_SCREW = (
    "a set screw takes a smaller key than the socket-head table; name the tool in the sidecar"
)
_LOW_HEAD = (
    "a low-head socket screw takes a smaller key than ISO 4762; name the tool in the sidecar"
)

#: Standards to (kind, head, not-covered reason); kind None means "not a fastener"
#: (washers). Checked 2026-10-06 against ecomfasteners.com's DIN-to-ISO chart, the
#: ISO catalogue titles (ISO 1580, 7040, 7380, 14579, 14580, 14583) and supplier
#: pages (fasten.it for DIN 965 / ISO 7046, fabory for DIN 84 / ISO 1207,
#: engineeringhardware for DIN 6923 / ISO 4161). DIN 85 and DIN 982 are left out
#: until checked.
STANDARDS: dict[str, tuple[Kind | None, Head | None, str | None]] = {
    # socket heads
    "ISO 4762": (_S, Head.SOCKET, None),
    "DIN 912": (_S, Head.SOCKET, None),
    "ISO 7380": (_S, Head.BUTTON, None),
    "ISO 10642": (_S, Head.FLAT, None),
    "DIN 7991": (_S, Head.FLAT, None),
    "DIN 7984": (_S, Head.SOCKET, _LOW_HEAD),
    # hex heads, coarse and fine, full and part thread
    "ISO 4017": (_S, Head.HEX, None),
    "DIN 933": (_S, Head.HEX, None),
    "ISO 4014": (_S, Head.HEX, None),
    "DIN 931": (_S, Head.HEX, None),
    "ISO 8676": (_S, Head.HEX, None),
    "DIN 961": (_S, Head.HEX, None),
    "ISO 8765": (_S, Head.HEX, None),
    "DIN 960": (_S, Head.HEX, None),
    # cross recess: pan and countersunk alike take a Phillips driver
    "ISO 7045": (_S, Head.PHILLIPS, None),
    "DIN 7985": (_S, Head.PHILLIPS, None),
    "ISO 7046": (_S, Head.PHILLIPS, None),
    "DIN 965": (_S, Head.PHILLIPS, None),
    # slotted: cheese, pan, countersunk
    "ISO 1207": (_S, Head.SLOTTED, None),
    "DIN 84": (_S, Head.SLOTTED, None),
    "ISO 1580": (_S, Head.SLOTTED, None),
    "ISO 2009": (_S, Head.SLOTTED, None),
    "DIN 963": (_S, Head.SLOTTED, None),
    # hexalobular (Torx): the check says not-covered until the M6 kit
    "ISO 14579": (_S, Head.TORX, None),
    "ISO 14580": (_S, Head.TORX, None),
    "ISO 14583": (_S, Head.TORX, None),
    # carriage bolts hold themselves
    "DIN 603": (_S, Head.CARRIAGE, None),
    "ISO 8677": (_S, Head.CARRIAGE, None),
    "ISO 8678": (_S, Head.CARRIAGE, None),
    # set screws
    "ISO 4026": (_S, None, _SET_SCREW),
    "DIN 913": (_S, None, _SET_SCREW),
    "ISO 4027": (_S, None, _SET_SCREW),
    "DIN 914": (_S, None, _SET_SCREW),
    "ISO 4028": (_S, None, _SET_SCREW),
    "DIN 915": (_S, None, _SET_SCREW),
    "ISO 4029": (_S, None, _SET_SCREW),
    "DIN 916": (_S, None, _SET_SCREW),
    # nuts: plain, thin, nylon-insert, flange
    "ISO 4032": (_N, None, None),
    "DIN 934": (_N, None, None),
    "ISO 4035": (_N, None, None),
    "ISO 4036": (_N, None, None),
    "DIN 439": (_N, None, None),
    "ISO 7040": (_N, None, None),
    "ISO 10511": (_N, None, None),
    "DIN 985": (_N, None, None),
    "ISO 4161": (_N, None, None),
    "DIN 6923": (_N, None, None),
    # washers: not fasteners (spec 4), whatever size they carry
    "ISO 7089": (None, None, None),
    "ISO 7090": (None, None, None),
    "DIN 125": (None, None, None),
    "DIN 127": (None, None, None),
    "ISO 7093": (None, None, None),
    "DIN 9021": (None, None, None),
}

#: McMaster-Carr series (the part number up to its letter) to (kind, head). The
#: number after the letter picks a size and length that only their catalogue
#: knows, so geometry gives the size. Checked 2026-10-06 against product titles
#: quoted by resellers: 91290A111 "Black-Oxide Alloy Steel Socket Head Screw M3 x
#: 0.5 mm, 6 mm Long", 91292A110 "18-8 Stainless Steel Socket Head Screw", 92095A179
#: "Button Head Hex Drive Screw", 92125A284 "M8-1.25 x 20 flat socket", 93625A250
#: "Nylon-Insert Locknut M6-1", 90591A121 "M3 Hex Nut". The table grows by
#: adding checked rows, never guessed ones.
MCMASTER: dict[str, tuple[Kind, Head | None]] = {
    "91290A": (_S, Head.SOCKET),
    "91292A": (_S, Head.SOCKET),
    "92095A": (_S, Head.BUTTON),
    "92125A": (_S, Head.FLAT),
    "93625A": (_N, None),
    "90591A": (_N, None),
}

#: Nouns a name can be about. Each maps to the kind, plus a fixed head or a
#: not-covered reason where the noun settles it.
_SCREW_NOUNS = {"screw", "screws", "bolt", "bolts", "capscrew", "shcs", "bhcs", "fhcs"}
_NUT_NOUNS = {"nut", "nuts", "locknut", "nyloc", "nylock", "nylok"}
_GLAND_NOUNS = {"gland", "glands"}
_HAND_TURNED = {"wingnut", "thumbscrew", "thumbnut"}
#: Fixed threads (issue #29): set in a panel, never turned. As nouns, and as the
#: word just before "nut" ("well nut", "cage nut", "T-nut"); a lock or nylon word
#: anywhere keeps a nut a nut ("nylon insert lock nut" is a nyloc).
_INSERT_NOUNS = {
    "insert", "inserts", "wellnut", "rivnut", "rivnuts", "rivetnut", "nutsert",
    "plusnut", "tnut", "teenut",
}  # fmt: skip
_INSERT_WORDS = {
    "well", "rivet", "insert", "cage", "t", "tee", "press", "clinch", "clinching",
    "pem", "weld", "captive",
}  # fmt: skip
_LOCK_WORDS = {"lock", "locking", "nylon", "nyloc", "nylock", "nylok"}
#: An insert by these alone may be an inlay (a logo, a badge): it needs a thread
#: size, a word below, or a bore in its solid to be a fixed thread (issue #84).
_BARE_INSERTS = {"insert", "inserts"}
_THREAD_WORDS = {"threaded", "thread", "tapped", "heatset", "heat", "brass", "helicoil", "knurled"}
#: Fastener nouns a describing word is run into in one word ("hexnut", "jamnut",
#: "hexbolt", "nylocnut"): read as the two words they are (issue #84). Longest first.
_COMPOUND_NOUNS = ("screws", "screw", "bolts", "bolt", "nuts", "nut")
_SET_SCREW_NOUNS = {"setscrew", "grubscrew"}
#: Describing words that settle a fastener as one the kit can't check.
_HAND_WORDS = {"wing", "thumb", "knurled"}
_SET_WORDS = {"set", "grub"}
_BY_HAND = "turned by hand: there is no tool to check"

#: Every fastener noun to its kind.
_NOUN_KIND: dict[str, Kind] = {
    **dict.fromkeys(_SCREW_NOUNS | _SET_SCREW_NOUNS | {"thumbscrew"}, Kind.SCREW),
    **dict.fromkeys(_NUT_NOUNS | _GLAND_NOUNS | {"wingnut", "thumbnut"}, Kind.NUT),
    **dict.fromkeys(_INSERT_NOUNS, Kind.INSERT),
    "shoulder": Kind.SCREW,  # "M6x20 shoulder": the screw; "shoulder bolt": its head
}

#: Words that describe a fastener rather than name what the part is, and so are
#: passed over when looking for the last noun; several also say the head.
_HEAD_WORDS: dict[str, Head | None] = {
    "shcs": Head.SOCKET,
    "socket": Head.SOCKET,
    "allen": Head.SOCKET,
    "cap": Head.SOCKET,
    "bhcs": Head.BUTTON,
    "button": Head.BUTTON,
    "fhcs": Head.FLAT,
    "countersunk": Head.FLAT,
    "csk": Head.FLAT,
    "flat": Head.FLAT,
    "hex": Head.HEX,
    "hexagon": Head.HEX,
    "phillips": Head.PHILLIPS,
    "pozi": Head.PHILLIPS,
    "pozidriv": Head.PHILLIPS,
    "cross": Head.PHILLIPS,
    "ph": Head.PHILLIPS,
    "slotted": Head.SLOTTED,
    "torx": Head.TORX,
    "hexalobular": Head.TORX,
    "carriage": Head.CARRIAGE,
    "shoulder": Head.SHOULDER,
    "coach": Head.CARRIAGE,
    "pan": None,
    "cheese": None,
    "head": None,
    "machine": None,
    "flange": None,
    "flanged": None,
    "jam": None,
    "lock": None,
    "thin": None,
    "metric": None,
    # read with the noun: "wing nut", "set screw" (see _noun_hint)
    "wing": None,
    "thumb": None,
    "knurled": None,
    "set": None,
    "grub": None,
}

#: When several head words appear, the most specific wins: a drive beats a head
#: shape ("pan head phillips", "flat head torx"), and a carriage bolt is one
#: whatever else it says.
_HEAD_RANK = (
    Head.CARRIAGE,
    Head.SHOULDER,
    Head.TORX,
    Head.PHILLIPS,
    Head.SLOTTED,
    Head.BUTTON,
    Head.FLAT,
    Head.SOCKET,
    Head.HEX,
)

#: Drive names that describe nothing but a fastener's recess (and the keys and
#: bits that fit it), so in a fastener's name they say its head wherever they sit:
#: ``torx_lid_screw`` is a Torx screw for a lid. Every other head word names
#: other things too (a button panel, a cross member, a hex standoff, a mains
#: socket), and says the head only touching the noun (see _descriptors).
_DRIVE_WORDS = {"torx", "hexalobular", "phillips", "pozidriv", "pozi"}

#: Describing words that are the noun when they end the name.
_END_NOUNS = {"cap", "shoulder"}

#: Words that qualify where a part sits or what it is made of, never what it is.
_QUALIFIERS = {
    "top", "bot", "bottom", "upper", "lower", "left", "right", "front", "rear", "back",
    "inner", "outer", "mid", "middle", "center", "centre", "near", "far", "side",
    "high", "low", "lh", "rh", "first", "second", "third", "primary", "secondary",
    "copy", "mirror", "mirrored", "instance", "part", "assy", "std", "standard",
    "steel", "stainless", "ss", "zinc", "zp", "plated", "black", "oxide", "galv",
    "brass", "nylon", "aluminium", "aluminum", "titanium", "alloy",
    "a2", "a4", "iso", "din", "en", "ansi", "asme", "mm", "in", "inch",
}  # fmt: skip

# ---------------------------------------------------------------------------
# Reading.
# ---------------------------------------------------------------------------

#: Instance markers CAD packages and wrenchroom itself append: "name#2" (ours),
#: "name<3>" (SolidWorks), "name (1)" and "name:1" (Fusion and others).
_INSTANCE_SUFFIX = re.compile(r"(?:(?<=\S)#\d+|\s*<\d+>|\s*\(\d+\)|:\d+)\s*$")

_STANDARD = re.compile(
    r"(?<![A-Za-z])(?:DIN[\s_-]*EN[\s_-]*)?(ISO|DIN)[\s_-]*(\d{2,5})(?![0-9])", re.IGNORECASE
)
_MCMASTER = re.compile(r"(?<![0-9A-Za-z])(\d{4,5}A)\d{1,4}(?![0-9A-Za-z])", re.IGNORECASE)
#: ``M6``, ``M6x20``, ``M6x1x20``, and the pitch after a dash as suppliers write it,
#: ``M6-1x20``, ``M3-0.5 x 16``.
_METRIC = re.compile(
    r"(?<![A-Za-z0-9])M(\d+(?:[.,]\d+)?)(?:\s*-\s*(\d(?:[.,]\d{1,2})?)(?![0-9]))?"
    r"(?:\s*x\s*(\d+(?:[.,]\d+)?))?(?:\s*x\s*(\d+(?:[.,]\d+)?))?(?:\s*mm)?(?![0-9])",
    re.IGNORECASE,
)
_IMPERIAL = re.compile(
    r"(?<![A-Za-z0-9#/])(#\d{1,2}|\d{1,2}/\d{1,2})(?:\s*-\s*(\d{2,3}))?"
    r"(?:\s*x\s*(\d+(?:\s*-\s*\d+/\d+|/\d+|\.\d+)?|\.\d+)\s*(?:\"|in\b|inch\b)?)?",
    re.IGNORECASE,
)
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")
_TOKEN_SPLIT = re.compile(r"[^0-9A-Za-z]+")

#: Thread pitches (ISO 261, coarse and common fine), used only to tell "M6x1"
#: (a pitch) from "M6x10" (a length).
_PITCHES = {0.35, 0.4, 0.45, 0.5, 0.6, 0.7, 0.75, 0.8, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0}


def read_name(name: str) -> NameHint | None:
    """What this part name says about the part as a fastener, or None if nothing.

    Never raises: any string is a possible part name.
    """
    cleaned = _clean(name)
    standard = _standard_in(cleaned)
    catalogue = _mcmaster_in(cleaned)
    words = _words(cleaned)
    at = _last_noun(words)
    noun = words[at] if at is not None else None
    run = _descriptors(words, at)
    needs_drive = False
    if standard is not None:
        label, (kind, head, reason) = standard
        if kind is None:
            return None  # a washer, by its standard
        basis = [label]
    elif catalogue is not None:
        series, (kind, head) = catalogue
        reason = None
        basis = [f"McMaster {series}"]
    else:
        reading = _noun_reading(words, at)
        if reading is None:
            return _designation(cleaned, words, at)
        at, (kind, head, reason, word), needs_drive = reading
        noun, run = words[at], _descriptors(words, at)
        basis = [f"noun {word!r}" + (", words after it" if needs_drive else "")]
    if head is None:
        near = _head_from(run, kind)
        head = _head_from(run | (set(words) & _DRIVE_WORDS), kind)
        if head is not near:  # said by a drive word away from the noun: name it
            drive = next(w for w in words if w in _DRIVE_WORDS and _HEAD_WORDS[w] is head)
            basis.append(f"drive {drive!r}")
    socket_allowed = noun not in _GLAND_NOUNS
    size, length, size_text, size_reason = _size_in(cleaned)
    bare = kind is Kind.INSERT and noun in _BARE_INSERTS and not set(words) & _THREAD_WORDS
    if not socket_allowed:
        # A gland's thread says nothing about the hex a spanner grips (an M20
        # gland is commonly 24 across flats): geometry measures the hex.
        size, size_text, size_reason = None, None, None
    if size_text:
        basis.append(size_text)
    return NameHint(
        kind=kind,
        head=head,
        size=size,
        length_mm=length,
        socket_allowed=socket_allowed,
        basis=", ".join(basis),
        not_covered=reason or size_reason,
        needs_drive=needs_drive,
        unless_hex=kind is Kind.INSERT and word not in _INSERT_NOUNS,
        needs_bore=bare and size is None and size_reason is None,
    )


def _designation(text: str, words: list[str], at: int | None) -> NameHint | None:
    """A name that is a screw's thread and length and nothing else: ``M3x16`` (issue #95).

    Every other word in it describes (``M3x16 button``) or labels (``M3x16 v1``);
    a name with a word of its own is about that word (``spacer M4x10``, ``M3x16
    standoff``). A candidate, taken only on a drive in its solid: a stud, a rod
    or an insert is named by its thread and length as readily as a screw.
    """
    size, length, size_text, size_reason = _size_in(text)
    if at is not None or length is None or size_text is None:
        return None
    run = set(words)
    _, _, reason, _ = _noun_hint("screw", run) or (None, None, None, None)
    return NameHint(
        kind=Kind.SCREW,
        head=_head_from(run, Kind.SCREW),
        size=size,
        length_mm=length,
        basis=f"thread and length {size_text}",
        not_covered=reason or size_reason,
        needs_drive=True,
    )


def _clean(name: str) -> str:
    text = name.replace(_TIMES, "x").replace("*", "x")
    previous = None
    while previous != text:  # "bolt (2)#3": strip every trailing marker
        previous = text
        text = _INSTANCE_SUFFIX.sub("", text)
    return text.strip()


def _standard_in(text: str) -> tuple[str, tuple[Kind | None, Head | None, str | None]] | None:
    for match in _STANDARD.finditer(text):
        label = f"{match.group(1).upper()} {match.group(2)}"
        if label in STANDARDS:
            return label, STANDARDS[label]
    return None


def _mcmaster_in(text: str) -> tuple[str, tuple[Kind, Head | None]] | None:
    for match in _MCMASTER.finditer(text):
        series = match.group(1).upper()
        if series in MCMASTER:
            return series, MCMASTER[series]
    return None


#: Words that name a part that isn't a fastener. A name ending in one says what the
#: part is (nut_plate, gland_plate, box_wall), so a fastener noun before it makes
#: no candidate worth a note when its solid shows no drive (issue #75).
PART_NOUNS = frozenset(
    {
        "plate",
        "bracket",
        "wall",
        "cover",
        "boss",
        "block",
        "panel",
        "housing",
        "base",
        "frame",
        "mount",
        "rail",
        "beam",
        "bar",
        "sheet",
        "lid",
        "case",
        "enclosure",
        "shelf",
        "chassis",
        "ceiling",
        "floor",
        "rib",
        "slab",
        "deck",
    }
)


def ends_in_part_noun(name: str) -> bool:
    """Whether a part name's last word names a part that isn't a fastener."""
    words = _words(_clean(name))
    return bool(words) and words[-1] in PART_NOUNS


def _words(text: str) -> list[str]:
    """Lower-case words, split at punctuation, camelCase and a run-in noun; sizes left out."""
    stripped = _IMPERIAL.sub(" ", _METRIC.sub(" ", text))
    spaced = _CAMEL.sub(" ", stripped)
    words = [word.lower() for word in _TOKEN_SPLIT.split(spaced) if word]
    return [part for word in words for part in _unrun(word)]


def _unrun(word: str) -> tuple[str, ...]:
    """A describing word run into a fastener noun, as its two words: ``hexnut``.

    Only a word the reader knows before the noun counts (hex, jam, flange, lock,
    nyloc, cage, weld...), so ``peanut`` and ``corkscrew`` stay what they are,
    and a word that is a noun itself (``locknut``, ``wingnut``, ``capscrew``)
    keeps its own reading.
    """
    if word in _NOUN_KIND:
        return (word,)
    for noun in _COMPOUND_NOUNS:
        before = word.removesuffix(noun)
        if before != word and before and _runs_in(before):
            return (before, noun)
    return (word,)


def _runs_in(word: str) -> bool:
    """A word that describes a fastener and may be run into its noun."""
    return word in _HEAD_WORDS or word in _INSERT_WORDS | _LOCK_WORDS | _SET_WORDS | _HAND_WORDS


def _last_noun(words: list[str]) -> int | None:
    """Where the word the name is about sits: the last one that isn't a qualifier.

    ``cap`` describes a screw before it ("socket head cap screw") and is the
    thing itself at the end ("screw_cap", "end_cap").
    """
    for index in range(len(words) - 1, -1, -1):
        word = words[index]
        if word in _END_NOUNS and index == len(words) - 1:
            return index
        if _describes(word):
            continue
        if word.isdigit() or len(word) == 1 or re.fullmatch(r"[a-z]\d+", word):
            continue  # numbers, a/b, r1: labels, not nouns
        return index
    return None


def _noun_reading(
    words: list[str], at: int | None
) -> tuple[int, tuple[Kind, Head | None, str | None, str], bool] | None:
    """Where the fastener noun is, what it says, and whether ordinary words follow it.

    The word the name is about first; failing that, the last fastener noun
    before it, which then needs its solid to show a drive (issue #30).
    """
    end = len(words) if at is None else at
    earlier = next((i for i in range(end - 1, -1, -1) if words[i] in _NOUN_KIND), None)
    for index, needs_drive in ((at, False), (earlier, True)):
        if index is None:
            continue
        found = _noun_hint(words[index], _descriptors(words, index))
        if found is not None and _is_insert(words, index, found[0]):
            found = (Kind.INSERT, None, None, f"{words[index - 1]} {found[3]}")  # "well nut"
        if found is not None:
            return index, found, needs_drive
    return None


def _describes(word: str) -> bool:
    """A word that qualifies or describes rather than names what the part is."""
    return word in _QUALIFIERS or (word in _HEAD_WORDS and word not in _SCREW_NOUNS)


def _descriptors(words: list[str], at: int | None) -> set[str]:
    """The describing words touching the noun on either side, and only those.

    "pan head phillips screw", "Screw-Socket-Head": the run round the noun. Head
    words anywhere else belong to something else: in ``x_carriage_bolt`` from a
    printer, ``carriage`` is the printer's carriage, and a bolt mistaken for a
    carriage bolt would hold itself and never be checked. (That one still reads
    as a carriage bolt, ``x`` being a label; which is why self-holding also needs
    the geometry to show a square neck.) A drive word is the exception, read
    from anywhere (:data:`_DRIVE_WORDS`): there is nothing else it could describe.
    """
    if at is None:
        return set()
    run = {words[at]}
    for step in (-1, 1):
        index = at + step
        while 0 <= index < len(words) and _describes(words[index]):
            run.add(words[index])
            index += step
    return run


def _is_insert(words: list[str], at: int, kind: Kind) -> bool:
    """A nut named as a fixed thread by the word just before it: "well nut", "t_nut"."""
    before = words[at - 1] if at > 0 else None
    return kind is Kind.NUT and before in _INSERT_WORDS and not set(words) & _LOCK_WORDS


def _noun_hint(noun: str | None, run: set[str]) -> tuple[Kind, Head | None, str | None, str] | None:
    """(kind, head, not-covered reason, the noun) for a fastener noun, else None."""
    kind = _NOUN_KIND.get(noun or "")
    if noun is None or kind is None:
        return None
    if noun in _SET_SCREW_NOUNS or (kind is Kind.SCREW and run & _SET_WORDS):
        return kind, None, _SET_SCREW, noun
    if noun in _HAND_TURNED or (kind is not Kind.INSERT and run & _HAND_WORDS):
        return kind, None, _BY_HAND, noun  # never an insert: a knurled insert is set, not turned
    head = _HEAD_WORDS.get(noun) if kind is Kind.SCREW else None
    return kind, head, None, noun


def _head_from(run: set[str], kind: Kind) -> Head | None:
    if kind is Kind.NUT:
        return None
    said = {head for word in run if (head := _HEAD_WORDS.get(word)) is not None}
    return next((head for head in _HEAD_RANK if head in said), None)


def _size_in(text: str) -> tuple[Size | None, float | None, str | None, str | None]:
    """(size, length mm, the text that gave them, a not-covered reason)."""
    metric = _METRIC.search(text)
    if metric is not None:
        return _metric(metric)
    imperial = _IMPERIAL.search(text)
    if imperial is not None and (imperial.group(2) or imperial.group(1).startswith("#")):
        return _imperial(imperial)
    return None, None, None, None


def _metric(match: re.Match[str]) -> tuple[Size | None, float | None, str | None, str | None]:
    diameter = match.group(1).replace(",", ".")
    dashed = match.group(2)
    pitch = float(dashed.replace(",", ".")) if dashed else None
    numbers = [float(g.replace(",", ".")) for g in match.groups()[2:] if g]
    length = None
    if len(numbers) == 2:  # noqa: PLR2004  (M6x1x20: pitch then length)
        pitch, length = numbers
    elif numbers and not _is_pitch(numbers[0], float(diameter)):
        length = numbers[0]
    if pitch is not None and not _is_pitch(pitch, float(diameter)):
        length = None  # M3x5x4, an insert's sizes: no thread's pitch, so no screw's length
    text = match.group(0).strip()
    designation = f"M{float(diameter):g}"
    try:
        return Size.parse(designation), length, text, None
    except ValueError:
        reason = f"{designation} is outside the sizes the tables hold (M1.6 to M24)"
        return None, length, text, reason


def _is_pitch(value: float, diameter: float) -> bool:
    return value in _PITCHES and value <= diameter / 4


def _imperial(match: re.Match[str]) -> tuple[Size | None, float | None, str | None, str | None]:
    designation = match.group(1)
    length = _inches(match.group(3)) if match.group(3) else None
    text = match.group(0).strip()
    try:
        return Size.parse(designation), length, text, None
    except ValueError:
        return None, length, text, f"{designation} is outside the sizes the tables hold (#0 to 3/4)"


def _inches(text: str) -> float | None:
    """'3/4', '1.5', '.5', '1-1/2' (inches) to mm."""
    cleaned = re.sub(r"\s+", "", text)
    whole, _, rest = (
        cleaned.partition("-") if "/" in cleaned and "-" in cleaned else ("", "", cleaned)
    )
    try:
        value = Fraction(rest) + (int(whole) if whole else 0)
    except (ValueError, ZeroDivisionError):
        return None
    return round(float(value) * _MM_PER_INCH, 3)
