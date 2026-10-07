"""Tool sizes and their names: millimetres, or inches written with "in".

A tool is named by the size the trade sells it under: a 13 mm spanner is
``spanner-13``, a 7/16 inch one ``spanner-7/16in``, the smallest inch key
``hex-key-0.050in``. Inch sizes carry their unit because some sit within hundredths
of a millimetre size (3/4 in is 19.05 mm, 3/8 in 9.525 mm), and a report has to say
which tool it means. Every table keeps millimetres; this module turns a size in
millimetres into its name, and a measured across-flats into the size it is.
"""

from __future__ import annotations

from fractions import Fraction

MM_PER_INCH = 25.4

#: Metric spanner and socket sizes as sold, mm: 3.2, 4 and 5 (M1.6's, M2's and
#: M2.5's hex; issue #83) and 4.5 between, sold beside them, 5.5 (M3's), then every
#: millimetre to 36 (M24's), then 41, 46 and 50, which large cable glands take (M32
#: commonly 41, M40 50) as M27, M30 and M33 nuts do (issue #33).
METRIC_FLATS: tuple[float, ...] = (
    3.2,
    4.0,
    4.5,
    5.0,
    5.5,
    *(float(af) for af in range(6, 37)),
    41.0,
    46.0,
    50.0,
)

#: Inch hex key sizes, ASME B18.3 (0.035 in to 3/4 in).
INCH_KEYS: tuple[str, ...] = (
    "0.035",
    "0.050",
    "1/16",
    "5/64",
    "3/32",
    "7/64",
    "1/8",
    "9/64",
    "5/32",
    "3/16",
    "7/32",
    "1/4",
    "5/16",
    "3/8",
    "7/16",
    "1/2",
    "9/16",
    "5/8",
    "3/4",
)

#: Inch spanner and socket sizes as sold (SAE), 5/32 in to 1-1/2 in: every size
#: the inch nut and head tables call for, and the odd sizes sets carry.
INCH_FLATS: tuple[str, ...] = (
    "5/32",
    "3/16",
    "7/32",
    "1/4",
    "9/32",
    "5/16",
    "11/32",
    "3/8",
    "7/16",
    "1/2",
    "9/16",
    "5/8",
    "11/16",
    "3/4",
    "13/16",
    "7/8",
    "15/16",
    "1",
    "1-1/16",
    "1-1/8",
    "1-1/4",
    "1-5/16",
    "1-3/8",
    "1-7/16",
    "1-1/2",
)

#: A measured across-flats is a tool's size when it lies this close to it, mm.
#: Models carry exact sizes; the nearest size wins, so 19.05 is 3/4 in, not 19.
SNAP_MM = 0.05


def inches(text: str) -> float:
    """An inch size as written in the trade, in inches: ``1-1/8`` is 1.125.

    Raises:
        ValueError: On text that isn't an inch size.
    """
    msg = f"not an inch size: {text!r}"
    whole, dash, rest = text.strip().partition("-")
    if dash and "/" not in rest:  # "1-" or "1-2": a whole and a fraction, or nothing
        raise ValueError(msg)
    try:
        if dash:
            return float(int(whole) + Fraction(rest))
        return float(Fraction(whole))
    except (ValueError, ZeroDivisionError):
        raise ValueError(msg) from None


def inch_mm(text: str) -> float:
    """An inch size, in mm: ``7/16`` is 11.1125."""
    return inches(text) * MM_PER_INCH


#: Every inch size there is a tool for, by its value in mm.
_INCH_BY_MM: dict[float, str] = {inch_mm(text): text for text in INCH_KEYS + INCH_FLATS}


#: Every hex size a spanner or socket comes in, metric and inch, mm.
FLATS: tuple[float, ...] = METRIC_FLATS + tuple(inch_mm(size) for size in INCH_FLATS)


def size_name(af: float) -> str:
    """A size in mm, as tools of that size are named: ``13``, ``5.5`` or ``7/16in``."""
    for mm, text in _INCH_BY_MM.items():
        if abs(mm - af) < 1e-9:  # noqa: PLR2004  (an exact table value, not a measurement)
            return f"{text}in"
    return f"{af:g}"


def is_inch(af: float) -> bool:
    """True for an inch tool size, in mm: 11.1125 (``7/16in``) is, 11 isn't."""
    return size_name(af).endswith("in")


def size_mm(name: str) -> float:
    """A size's name back to mm: ``7/16in`` is 11.1125, ``13`` is 13.

    Raises:
        ValueError: On a name that isn't a size.
    """
    if name.endswith("in"):
        return inch_mm(name[:-2])
    return float(name)


def snap(measured: float, sizes: tuple[float, ...]) -> float | None:
    """The size in ``sizes`` a measured across-flats is, or None when it is none of them.

    The nearest within :data:`SNAP_MM` wins, so an exact model size is never
    mistaken for a neighbour from the other system.
    """
    if not sizes:
        return None
    nearest = min(sizes, key=lambda size: abs(size - measured))
    return nearest if abs(nearest - measured) <= SNAP_MM else None
