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
as it would at a bench, unless it lies in a nut standard's band just below a
spanner size (an M8 nut drawn at 12.8 takes the 13: see fasteners.HEX_AF_MIN).
"""

from __future__ import annotations

from dataclasses import dataclass

from wrenchroom.tools.ball_end import BALL_END_KEYS
from wrenchroom.tools.drivers import SHAFT_RADIUS
from wrenchroom.tools.hex_keys import ASME_B18_3, HEX_KEYS, ISO_2936
from wrenchroom.tools.nut_drivers import NUT_DRIVERS
from wrenchroom.tools.sizes import INCH_FLATS, INCH_KEYS, METRIC_FLATS, size_mm, size_name
from wrenchroom.tools.sockets import EXTENSION_LENGTHS, socket_for
from wrenchroom.tools.spanners import spanner_for
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
        nut_drivers: Nut driver sizes; the full kit's alone.
    """

    name: str
    summary: str
    hex_keys: tuple[str, ...]
    spanners: tuple[str, ...]
    sockets: tuple[str, ...]
    drivers: tuple[str, ...]
    torx_keys: tuple[str, ...] = ()
    ball_end_keys: tuple[str, ...] = ()
    nut_drivers: tuple[str, ...] = ()

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
            "nut-driver": self.nut_drivers,
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
        "to 1-1/2 in, nut drivers 5.5 to 13 mm, every driver"
    ),
    hex_keys=_names(tuple(ISO_2936)) + _names(tuple(ASME_B18_3)),
    spanners=_names(METRIC_FLATS) + _inch(INCH_FLATS),
    sockets=_names(METRIC_FLATS) + _inch(INCH_FLATS),
    drivers=tuple(SHAFT_RADIUS),
    torx_keys=tuple(ISO_10664),
    ball_end_keys=_names(tuple(BALL_END_KEYS)),
    nut_drivers=_names(tuple(NUT_DRIVERS)),
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


# ---------------------------------------------------------------------------
# The listing `wrenchroom tools` prints: exactly what a check with the kit tries.
# ---------------------------------------------------------------------------


def listing(kit: Kit) -> list[str]:
    """The kit's tools and their dimensions, family by family, a blank line between."""
    lines = [f"kit {kit.name}: {kit.summary}"]
    for section in (
        _hex_keys(kit),
        _spanners(kit),
        _sockets(kit),
        _drivers(kit),
        _ball_end_keys(kit),
        _nut_drivers(kit),
        _torx_keys(kit),
    ):
        if section:
            lines += ["", *section]
    return lines


def _hex_keys(kit: Kit) -> list[str]:
    head = "hex keys (DIN ISO 2936:2016-10 and ASME B18.3; dimensions in mm):"
    rows = []
    for size in kit.hex_keys:
        key = HEX_KEYS[size_mm(size)]
        rows.append(
            f"  {key.name:<17} across flats {key.af:<7.4g} "
            f"long arm {key.long_mm:<6.4g} short arm {key.short_mm:.4g}"
        )
    return [head, *rows] if rows else []


def _spanners(kit: Kit) -> list[str]:
    head = (
        "combination spanners, ring and open end, full and stubby "
        "(approximate until DIN 3113 is read out; mm):"
    )
    rows = []
    for size in kit.spanners:
        spanner = spanner_for(size_mm(size))
        rows.append(
            f"  spanner-{size:<9} length {spanner.length:<6.4g} "
            f"ring outer r {spanner.ring_outer_radius:<5.3g} "
            f"open end {spanner.open_width:.3g} wide, stubby {spanner.stubby_length:.4g}"
        )
    return [head, *rows] if rows else []


def _sockets(kit: Kit) -> list[str]:
    extensions = "/".join(f"{e:g}" for e in EXTENSION_LENGTHS)
    head = (
        f"sockets on a 72-tooth ratchet, extensions {extensions} mm (approximate until DIN 3124):"
    )
    rows = []
    for size in kit.sockets:
        socket = socket_for(size_mm(size))
        rows.append(
            f"  socket-{size:<10} outer r {socket.outer_radius:<5.3g} length {socket.length:.4g}"
        )
    return [head, *rows] if rows else []


def _drivers(kit: Kit) -> list[str]:
    rows = [f"  driver-{drive:<9} shaft r {SHAFT_RADIUS[drive]:g}" for drive in kit.drivers]
    return ["drivers (shaft radii approximate, catalogue-typical):", *rows] if rows else []


def _ball_end_keys(kit: Kit) -> list[str]:
    rows = []
    for size in kit.ball_end_keys:
        ball = BALL_END_KEYS[size_mm(size)]
        rows.append(
            f"  {ball.name:<17} across flats {ball.af:<5g} "
            f"long arm {ball.long_mm:<6g} short arm {ball.short_mm:g}"
        )
    head = "ball-end keys (to 25 deg off the axis; Wera 950 SPKL arms; mm):"
    return [head, *rows] if rows else []


def _nut_drivers(kit: Kit) -> list[str]:
    rows = []
    for size in kit.nut_drivers:
        driver = NUT_DRIVERS[size_mm(size)]
        rows.append(
            f"  {driver.name:<17} socket outer r {driver.outer_radius:<5g} "
            f"handle r {driver.handle_radius:<5g} handle {driver.handle_length:g}"
        )
    head = "nut drivers (Wera 395 and Wiha 341, the larger; blade 125; mm):"
    return [head, *rows] if rows else []


def _torx_keys(kit: Kit) -> list[str]:
    rows = []
    for size in kit.torx_keys:
        torx = ISO_10664[size]
        rows.append(
            f"  {torx.name:<17} point to point {torx.point_to_point:<5g} "
            f"long arm {torx.long_mm:<6.4g} short arm {torx.short_mm:.4g}"
        )
    head = "Torx keys (ISO 10664 sizes; arms the longest of three makers' catalogues; mm):"
    return [head, *rows] if rows else []
