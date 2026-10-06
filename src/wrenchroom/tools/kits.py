"""Tool kits: which tools exist for a check (spec 5.3).

A kit is data, the sizes of each tool family it holds, and a check tries only those.
A fastener that needs a tool the kit lacks is `not-covered`, with the tool named and
the kit that has it, so a model full of M16 nuts checked with a home kit says what to
buy (or which ``--kit`` to name) rather than borrowing a spanner nobody owns.

Sizes are held by name, as tools are named (:mod:`wrenchroom.tools.sizes`): ``13``
for 13 mm, ``7/16in`` for 7/16 inch.

The kits, as the spec writes them (decided 2026-10-06, the owner choosing strict kits
over a home kit stretched to 24 mm):

- ``metric-home``, the default: ISO 2936 hex keys 1.5 to 10 mm; combination spanners
  5.5 to 19 mm and their stubbies; a 1/4" and 3/8" drive socket set, 5.5 to 19 mm,
  with stock extensions and a 72-tooth ratchet; Phillips 1 to 3 and slotted drivers.
- ``imperial-home``: the same in inch sizes, as US home sets come (checked 2026-10-06
  against Tekton, Craftsman, GearWrench and Eklind set listings, on what they all
  carry): the 13-piece ASME B18.3 key set 0.050 to 3/8 in, combination spanners 1/4
  to 3/4 in, 1/4" drive sockets 3/16 to 9/16 in and 3/8" drive 5/16 to 3/4 in, and
  the same drivers.
- ``full``: every size the tables describe, metric and inch (keys to 19 mm and 3/4
  in, spanners and sockets to 36 mm and 1-1/2 in). The rest of M6 adds the tools only
  this kit carries (ball-end and Torx keys, nut drivers).

A measured across-flats that is no tool's size (a 22.5 mm gland) stays not covered,
as it would at a bench.
"""

from __future__ import annotations

from dataclasses import dataclass

from wrenchroom.tools.ball_end import BALL_END_KEYS
from wrenchroom.tools.drivers import SHAFT_RADIUS
from wrenchroom.tools.hex_keys import ASME_B18_3, ISO_2936
from wrenchroom.tools.sizes import INCH_FLATS, INCH_KEYS, METRIC_FLATS, size_mm, size_name
from wrenchroom.tools.torx_keys import ISO_10664

_HOME_DRIVERS = ("ph1", "ph2", "ph3", "slotted")


@dataclass(frozen=True)
class Kit:
    """One named kit: the sizes of each tool family it holds, by name.

    Attributes:
        name: What ``--kit`` takes.
        summary: One line saying what is in it, for ``tools`` and errors.
        hex_keys: L-key sizes, each an ISO 2936 or ASME B18.3 row.
        spanners: Combination spanner sizes (ring end, and the same
            spanner's stubby).
        sockets: Socket sizes, on the drive set's ratchet and extensions.
        drivers: Screwdriver tips, by the names :data:`SHAFT_RADIUS` uses.
        torx_keys: Torx L-key sizes (``T30``); the full kit's alone.
        ball_end_keys: Ball-end hex key sizes; the full kit's alone.
    """

    name: str
    summary: str
    hex_keys: tuple[str, ...]
    spanners: tuple[str, ...]
    sockets: tuple[str, ...]
    drivers: tuple[str, ...]
    torx_keys: tuple[str, ...] = ()
    ball_end_keys: tuple[str, ...] = ()

    def holds(self, tool: str) -> bool:
        """True when a tool, named as the report names it (``spanner-13``), is in the kit."""
        family, _, size = tool.rpartition("-")
        sizes = {
            "hex-key": self.hex_keys,
            "spanner": self.spanners,
            "socket": self.sockets,
            "driver": self.drivers,
            "torx-key": self.torx_keys,
            "ball-end-key": self.ball_end_keys,
        }
        return size in sizes.get(family, ())


def _names(sizes_mm: tuple[float, ...]) -> tuple[str, ...]:
    return tuple(size_name(size) for size in sizes_mm)


def _inch(sizes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{size}in" for size in sizes)


def _between(sizes: tuple[str, ...], low: str, high: str) -> tuple[str, ...]:
    """The inch sizes from ``low`` to ``high`` inclusive, in table order."""
    lo, hi = size_mm(f"{low}in"), size_mm(f"{high}in")
    return tuple(size for size in _inch(sizes) if lo - 1e-9 <= size_mm(size) <= hi + 1e-9)


_METRIC_HOME_FLATS = _names(tuple(af for af in METRIC_FLATS if af <= 19))  # noqa: PLR2004

METRIC_HOME = Kit(
    name="metric-home",
    summary=(
        "ISO 2936 hex keys 1.5 to 10 mm, combination spanners 5.5 to 19 mm with stubbies, "
        "1/4 and 3/8 in drive sockets 5.5 to 19 mm, Phillips 1 to 3 and slotted drivers"
    ),
    hex_keys=_names(tuple(af for af in ISO_2936 if af <= 10)),  # noqa: PLR2004
    spanners=_METRIC_HOME_FLATS,
    sockets=_METRIC_HOME_FLATS,
    drivers=_HOME_DRIVERS,
)

_QUARTER_DRIVE = _between(INCH_FLATS, "3/16", "9/16")
_THREE_EIGHTHS_DRIVE = _between(INCH_FLATS, "5/16", "3/4")

IMPERIAL_HOME = Kit(
    name="imperial-home",
    summary=(
        "ASME B18.3 hex keys 0.050 to 3/8 in, combination spanners 1/4 to 3/4 in with "
        "stubbies, 1/4 in drive sockets 3/16 to 9/16 in and 3/8 in drive 5/16 to 3/4 in, "
        "Phillips 1 to 3 and slotted drivers"
    ),
    hex_keys=_between(INCH_KEYS, "0.050", "3/8"),
    spanners=tuple(
        size for size in _between(INCH_FLATS, "1/4", "3/4") if size not in {"9/32in", "11/32in"}
    ),
    sockets=tuple(dict.fromkeys(_QUARTER_DRIVE + _THREE_EIGHTHS_DRIVE)),
    drivers=_HOME_DRIVERS,
)

FULL = Kit(
    name="full",
    summary=(
        "every size the tables hold: hex keys 1.5 to 19 mm and 0.050 to 3/4 in, ball-end "
        "keys 3 to 10 mm, Torx keys T10 to T40, spanners and sockets 5.5 to 36 mm and 5/32 "
        "to 1-1/2 in, every driver"
    ),
    hex_keys=_names(tuple(ISO_2936)) + _names(tuple(ASME_B18_3)),
    spanners=_names(METRIC_FLATS) + _inch(INCH_FLATS),
    sockets=_names(METRIC_FLATS) + _inch(INCH_FLATS),
    drivers=tuple(SHAFT_RADIUS),
    torx_keys=tuple(ISO_10664),
    ball_end_keys=_names(tuple(BALL_END_KEYS)),
)

#: Every kit by name, the default first.
KITS: dict[str, Kit] = {kit.name: kit for kit in (METRIC_HOME, IMPERIAL_HOME, FULL)}

#: What a check uses unless told otherwise.
DEFAULT_KIT = METRIC_HOME.name


def kit_named(name: str) -> Kit:
    """The kit called ``name``.

    Raises:
        ValueError: On a name that isn't a kit (a typo, not a model problem).
    """
    kit = KITS.get(name)
    if kit is None:
        msg = f"unknown kit {name!r}; available: {', '.join(KITS)}"
        raise ValueError(msg)
    return kit


def missing(tools: tuple[str, ...], kit: Kit) -> str:
    """Why a fastener that needs one of ``tools`` is not covered by ``kit``.

    Names the tools and, when another kit holds one, that kit: the reason a
    person reads is what to get or which ``--kit`` to name.
    """
    needs = " or ".join(tools)
    elsewhere = [other.name for other in KITS.values() if any(other.holds(t) for t in tools)]
    if not elsewhere:
        hint = "; no kit has it"
    elif len(elsewhere) == 1:
        hint = f" ({elsewhere[0]} has it)"
    else:
        hint = f" ({', '.join(elsewhere[:-1])} and {elsewhere[-1]} have it)"
    return f"needs {needs}, which kit {kit.name} does not hold{hint}"
