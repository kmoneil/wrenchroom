"""Tool kits: which tools exist for a check (spec 5.3).

A kit is data, the sizes of each tool family it holds, and a check tries only those.
A fastener that needs a tool the kit lacks is `not-covered`, with the tool named and
the kit that has it, so a model full of M16 nuts checked with a home kit says what to
buy (or which ``--kit`` to name) rather than borrowing a spanner nobody owns.

The kits, as the spec writes them (decided 2026-10-06, the owner choosing strict kits
over a home kit stretched to 24 mm):

- ``metric-home``, the default: ISO 2936 hex keys 1.5 to 10 mm; combination spanners
  5.5 to 19 mm and their stubbies; a 1/4" and 3/8" drive socket set, 5.5 to 19 mm,
  with stock extensions and a 72-tooth ratchet; Phillips 1 to 3 and slotted drivers.
- ``full``: every size the tables describe (keys to 19 mm, spanners and sockets to
  36 mm, M24's hex). The rest of M6 adds the imperial sizes and the tools only this
  kit carries (ball-end and Torx keys, nut drivers).

Spanner and socket sizes are whole millimetres plus 5.5 (M3's hex), the sizes the
trade sells; a measured across-flats that lands between them (a 22.5 mm gland) is no
tool's size and stays not covered, as it would at a bench.
"""

from __future__ import annotations

from dataclasses import dataclass

from wrenchroom.tools.drivers import SHAFT_RADIUS
from wrenchroom.tools.hex_keys import ISO_2936

#: Metric spanner and socket sizes as sold, mm: 5.5, then every millimetre to 36.
METRIC_FLATS: tuple[float, ...] = (5.5, *(float(af) for af in range(6, 37)))


@dataclass(frozen=True)
class Kit:
    """One named kit: the sizes of each tool family it holds.

    Attributes:
        name: What ``--kit`` takes.
        summary: One line saying what is in it, for ``tools`` and errors.
        hex_keys: L-key sizes, across flats, mm; each an ISO 2936 row.
        spanners: Combination spanner sizes, across flats, mm (ring end, and
            the same spanner's stubby).
        sockets: Socket sizes, across flats, mm, on the drive set's ratchet
            and extensions.
        drivers: Screwdriver tips, by the names :data:`SHAFT_RADIUS` uses.
    """

    name: str
    summary: str
    hex_keys: tuple[float, ...]
    spanners: tuple[float, ...]
    sockets: tuple[float, ...]
    drivers: tuple[str, ...]

    def holds(self, tool: str) -> bool:
        """True when a tool, named as the report names it (``spanner-13``), is in the kit."""
        family, _, size = tool.rpartition("-")
        if family == "driver":
            return size in self.drivers
        sizes = {"hex-key": self.hex_keys, "spanner": self.spanners, "socket": self.sockets}
        try:
            return family in sizes and float(size) in sizes[family]
        except ValueError:
            return False


METRIC_HOME = Kit(
    name="metric-home",
    summary=(
        "ISO 2936 hex keys 1.5 to 10 mm, combination spanners 5.5 to 19 mm with stubbies, "
        "1/4 and 3/8 in drive sockets 5.5 to 19 mm, Phillips 1 to 3 and slotted drivers"
    ),
    hex_keys=tuple(af for af in ISO_2936 if af <= 10),  # noqa: PLR2004  (the spec's range)
    spanners=tuple(af for af in METRIC_FLATS if af <= 19),  # noqa: PLR2004
    sockets=tuple(af for af in METRIC_FLATS if af <= 19),  # noqa: PLR2004
    drivers=("ph1", "ph2", "ph3", "slotted"),
)

FULL = Kit(
    name="full",
    summary=(
        "every size the tables hold: ISO 2936 hex keys 1.5 to 19 mm, spanners and "
        "sockets 5.5 to 36 mm, every driver"
    ),
    hex_keys=tuple(ISO_2936),
    spanners=METRIC_FLATS,
    sockets=METRIC_FLATS,
    drivers=tuple(SHAFT_RADIUS),
)

#: Every kit by name, the default first.
KITS: dict[str, Kit] = {kit.name: kit for kit in (METRIC_HOME, FULL)}

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
