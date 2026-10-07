"""Custom tools: a sidecar's own, in the shape of the built-in tables (spec 5.3).

The escape hatch for a tool wrenchroom doesn't ship: a long-series hex key, a
shop-made spanner, a thin-wall socket, a long screwdriver. Each is described in
the sidecar by the numbers the built-in tables hold for its kind, and swept the
same way::

    tools:
      - name: long-key-5          # how reports name it
        type: hex-key
        across_flats: 5
        long: 150
        short: 28

A custom tool joins whatever kit the check uses: a fastener that takes its kind
and size tries the kit's own tools first, then the custom ones, in the
sidecar's order; and a rule's ``tool:`` may name one outright. Its name is its
own, never a built-in family's (``spanner-13``), so a report can't be read as
meaning a tool the tables describe. Lengths are mm.

The kinds and their numbers (required, then optional with what they default to):

- ``hex-key``: ``across_flats``, ``long``, ``short``; ``across_corners`` (the
  hexagon's, ``across_flats`` times 2/sqrt(3)).
- ``torx-key``: ``size`` (``T30``), ``long``, ``short``; ``point_to_point``
  (ISO 10664's for the size, which must then be T10 to T40).
- ``spanner``: ``across_flats``, ``length``; ``stubby`` (none), ``ends``
  (``[ring, open]``), and the head: ``head_thickness``, ``ring_outer_radius``,
  ``handle_width``, ``open_width``, ``open_thickness`` (the built-in spanner's
  for the size).
- ``socket``: ``across_flats``; ``outer_radius``, ``length`` (the built-in
  socket's for the size).
- ``nut-driver``: ``across_flats``; ``outer_radius``, ``handle_radius``,
  ``handle_length`` (the built-in driver's for the size; ``outer_radius`` is
  required where there is none).
- ``driver``: ``tip`` (``ph1``, ``ph2``, ``ph3``, ``slotted``); ``shaft_radius``
  (the built-in's for the tip), ``shaft_length`` (100).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from wrenchroom.tools.drivers import SHAFT_LENGTH, SHAFT_RADIUS
from wrenchroom.tools.nut_drivers import NUT_DRIVERS, NutDriver
from wrenchroom.tools.sockets import Socket, socket_for
from wrenchroom.tools.spanners import Spanner, spanner_for
from wrenchroom.tools.torx_keys import ISO_10664

if TYPE_CHECKING:
    from collections.abc import Iterator


#: What a custom tool's name may be: letters, digits and ``. _ / + -``, starting
#: with a letter or digit; it is printed in every report and drawn in the view.
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+-]{0,63}")

#: The built-in families' names (``spanner-13``, ``hex-key-5/32in``): a custom
#: name never starts like one, or a report could mean either tool.
BUILT_IN_FAMILIES = (
    "hex-key-",
    "torx-key-",
    "ball-end-key-",
    "spanner-",
    "socket-",
    "nut-driver-",
    "driver-",
)

#: A spanner's ends, as ``ends:`` names them.
ENDS = ("ring", "open")


@dataclass(frozen=True)
class CustomKey:
    """A custom L-key, hex or Torx: what the L-key sweep reads (hex_keys.LKey)."""

    name: str
    kind: str  # "hex-key" or "torx-key"
    size: str  # the across-flats in mm for a hex key; T10.. for a Torx key
    af: float  # across flats, mm; 0 for a Torx key
    long_mm: float
    short_mm: float
    section: float  # across corners (hex) or point to point (Torx), mm

    @property
    def radius(self) -> float:
        """The swept shaft radius: half the section across its widest."""
        return self.section / 2


@dataclass(frozen=True)
class CustomSpanner:
    """A custom spanner: the built-in spanner's numbers, under its own name, and its ends."""

    name: str
    spanner: Spanner
    ends: tuple[str, ...] = ENDS


@dataclass(frozen=True)
class CustomSocket:
    """A custom socket, swept on the ratchet and extensions as the built-in ones are."""

    name: str
    socket: Socket


@dataclass(frozen=True)
class CustomNutDriver:
    """A custom nut driver, swept as the built-in ones are."""

    name: str
    driver: NutDriver


@dataclass(frozen=True)
class CustomDriver:
    """A custom screwdriver: its tip, shaft radius and shaft length."""

    name: str
    tip: str
    shaft_radius: float
    shaft_length: float


type CustomTool = CustomKey | CustomSpanner | CustomSocket | CustomNutDriver | CustomDriver


@dataclass(frozen=True)
class CustomTools:
    """A sidecar's custom tools, in its order, and what the check asks of them."""

    tools: tuple[CustomTool, ...] = ()
    by_name: dict[str, CustomTool] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        self.by_name.update({tool.name: tool for tool in self.tools})

    def __contains__(self, name: object) -> bool:
        return name in self.by_name

    def __len__(self) -> int:
        return len(self.tools)

    def hex_keys(self, af: float) -> tuple[CustomKey, ...]:
        """The custom hex keys of an across-flats size."""
        return tuple(
            t
            for t in self.tools
            if isinstance(t, CustomKey) and t.kind == "hex-key" and _same(t.af, af)
        )

    def torx_keys(self, size: str) -> tuple[CustomKey, ...]:
        """The custom Torx keys of a size (``T30``)."""
        return tuple(
            t
            for t in self.tools
            if isinstance(t, CustomKey) and t.kind == "torx-key" and t.size == size
        )

    def spanners(self, af: float) -> tuple[CustomSpanner, ...]:
        """The custom spanners of an across-flats size."""
        return tuple(
            t for t in self.tools if isinstance(t, CustomSpanner) and _same(t.spanner.af, af)
        )

    def sockets(self, af: float) -> tuple[CustomSocket, ...]:
        """The custom sockets of an across-flats size."""
        return tuple(
            t for t in self.tools if isinstance(t, CustomSocket) and _same(t.socket.af, af)
        )

    def nut_drivers(self, af: float) -> tuple[CustomNutDriver, ...]:
        """The custom nut drivers of an across-flats size."""
        return tuple(
            t for t in self.tools if isinstance(t, CustomNutDriver) and _same(t.driver.af, af)
        )

    def drivers(self, tip: str) -> tuple[CustomDriver, ...]:
        """The custom screwdrivers with a tip (``ph2``, ``slotted``)."""
        return tuple(t for t in self.tools if isinstance(t, CustomDriver) and t.tip == tip)

    def key_sizes(self) -> tuple[float, ...]:
        """Every custom hex key's across-flats: sizes a measured socket may be."""
        return tuple(t.af for t in self.tools if isinstance(t, CustomKey) and t.kind == "hex-key")

    def flat_sizes(self) -> tuple[float, ...]:
        """Every custom spanner's, socket's and nut driver's across-flats."""
        sizes = (_flat_af(tool) for tool in self.tools)
        return tuple(af for af in sizes if af is not None)


def _flat_af(tool: CustomTool) -> float | None:
    if isinstance(tool, CustomSpanner):
        return tool.spanner.af
    if isinstance(tool, CustomSocket):
        return tool.socket.af
    if isinstance(tool, CustomNutDriver):
        return tool.driver.af
    return None


def _same(a: float, b: float) -> bool:
    """Two across-flats sizes, in mm, are one: a tool's size as written and as measured."""
    return abs(a - b) < 1e-6  # noqa: PLR2004  (sizes as written, not measured)


# ---------------------------------------------------------------------------
# Reading the sidecar's ``tools:``.
# ---------------------------------------------------------------------------

_KEYS: dict[str, tuple[set[str], set[str]]] = {
    # kind: (required keys, optional keys), beside name and type
    "hex-key": ({"across_flats", "long", "short"}, {"across_corners"}),
    "torx-key": ({"size", "long", "short"}, {"point_to_point"}),
    "spanner": (
        {"across_flats", "length"},
        {
            "stubby",
            "ends",
            "head_thickness",
            "ring_outer_radius",
            "handle_width",
            "open_width",
            "open_thickness",
        },
    ),
    "socket": ({"across_flats"}, {"outer_radius", "length"}),
    "nut-driver": ({"across_flats"}, {"outer_radius", "handle_radius", "handle_length"}),
    "driver": ({"tip"}, {"shaft_radius", "shaft_length"}),
}


def parse_tools(raw: object, where: str) -> CustomTools:
    """A sidecar's ``tools:`` list, validated.

    Raises:
        ValueError: On anything this version can't read, the message saying
            where (``tools[2]``) and what.
    """
    if raw is None:
        return CustomTools()
    if not isinstance(raw, list):
        msg = f"{where}: must be a list of tools"
        raise ValueError(msg)  # noqa: TRY004  (the caller turns it into a ConfigError)
    tools: list[CustomTool] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        tool = _parse_tool(entry, f"{where}[{index}]")
        if tool.name in seen:
            msg = f"{where}[{index}]: a second tool named {tool.name!r}"
            raise ValueError(msg)
        seen.add(tool.name)
        tools.append(tool)
    return CustomTools(tuple(tools))


def _parse_tool(entry: object, where: str) -> CustomTool:
    if not isinstance(entry, dict):
        msg = f"{where}: must be a mapping"
        raise ValueError(msg)  # noqa: TRY004
    name = _name(entry.get("name"), where)
    where = f"{where} ({name})"
    kind = entry.get("type")
    if kind not in _KEYS:
        msg = f"{where}: type must be one of {', '.join(_KEYS)}, got {kind!r}"
        raise ValueError(msg)
    required, optional = _KEYS[kind]
    missing = sorted(required - set(entry))
    if missing:
        msg = f"{where}: a {kind} needs {', '.join(missing)}"
        raise ValueError(msg)
    unknown = sorted(set(entry) - required - optional - {"name", "type"})
    if unknown:
        msg = f"{where}: unknown key(s) for a {kind}: {', '.join(unknown)}"
        raise ValueError(msg)
    return _BUILDERS[kind](name, entry, where)


def _name(value: object, where: str) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        msg = (
            f"{where}: name must be 1 to 64 letters, digits and . _ / + -, starting "
            f"with a letter or digit, got {value!r}"
        )
        raise ValueError(msg)
    if value.startswith(BUILT_IN_FAMILIES):
        msg = (
            f"{where}: {value!r} is named like a built-in tool; give a custom tool "
            "a name of its own (long-key-5, shop-spanner-24)"
        )
        raise ValueError(msg)
    return value


def _mm(entry: dict, key: str, where: str, default: float | None = None) -> float:
    value = entry.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        msg = f"{where}: {key} must be a positive number of mm, got {value!r}"
        raise ValueError(msg)
    if not math.isfinite(value):
        msg = f"{where}: {key} must be finite, got {value!r}"
        raise ValueError(msg)
    return float(value)


def _hex_key(name: str, entry: dict, where: str) -> CustomKey:
    af = _mm(entry, "across_flats", where)
    section = _mm(entry, "across_corners", where, af * 2 / math.sqrt(3))
    if section < af:
        msg = f"{where}: across_corners ({section:g}) is less than across_flats ({af:g})"
        raise ValueError(msg)
    long, short = _arms(entry, where)
    return CustomKey(name, "hex-key", f"{af:g}", af, long, short, section)


def _torx_key(name: str, entry: dict, where: str) -> CustomKey:
    size = entry.get("size")
    if not isinstance(size, str) or not re.fullmatch(r"T\d{1,2}", size):
        msg = f"{where}: size must be a Torx size such as T30, got {size!r}"
        raise ValueError(msg)
    table = ISO_10664.get(size)
    if "point_to_point" not in entry and table is None:
        msg = f"{where}: ISO 10664 has no {size} in these tables; give point_to_point"
        raise ValueError(msg)
    default = table.point_to_point if table is not None else None
    section = _mm(entry, "point_to_point", where, default)
    long, short = _arms(entry, where)
    return CustomKey(name, "torx-key", size, 0.0, long, short, section)


def _arms(entry: dict, where: str) -> tuple[float, float]:
    """An L-key's long and short arms; a short one longer than the long is a typo (#75)."""
    long, short = _mm(entry, "long", where), _mm(entry, "short", where)
    if short > long:
        msg = f"{where}: short ({short:g}) is longer than long ({long:g}): swapped?"
        raise ValueError(msg)
    return long, short


def _spanner(name: str, entry: dict, where: str) -> CustomSpanner:
    af = _mm(entry, "across_flats", where)
    base = spanner_for(af)
    ends = entry.get("ends", list(ENDS))
    if (
        not isinstance(ends, list)
        or not ends
        or any(end not in ENDS for end in ends)
        or len(set(ends)) != len(ends)
    ):
        msg = f"{where}: ends must be a list of ring and open, got {ends!r}"
        raise ValueError(msg)
    spanner = replace(
        base,
        length=_mm(entry, "length", where),
        stubby_length=_mm(entry, "stubby", where) if "stubby" in entry else None,
        head_thickness=_mm(entry, "head_thickness", where, base.head_thickness),
        ring_outer_radius=_mm(entry, "ring_outer_radius", where, base.ring_outer_radius),
        handle_width=_mm(entry, "handle_width", where, base.handle_width),
        open_width=_mm(entry, "open_width", where, base.open_width),
        open_thickness=_mm(entry, "open_thickness", where, base.open_thickness),
        name=name,
    )
    if spanner.stubby_length is not None and spanner.stubby_length >= spanner.length:
        msg = f"{where}: stubby ({spanner.stubby_length:g}) is no shorter than length"
        raise ValueError(msg)
    return CustomSpanner(name, spanner, tuple(end for end in ENDS if end in ends))


def _socket(name: str, entry: dict, where: str) -> CustomSocket:
    af = _mm(entry, "across_flats", where)
    base = socket_for(af)
    socket = replace(
        base,
        outer_radius=_mm(entry, "outer_radius", where, base.outer_radius),
        length=_mm(entry, "length", where, base.length),
        name=name,
    )
    if socket.outer_radius <= af / math.sqrt(3):
        msg = f"{where}: outer_radius ({socket.outer_radius:g}) is inside the hex's corners"
        raise ValueError(msg)
    return CustomSocket(name, socket)


def _nut_driver(name: str, entry: dict, where: str) -> CustomNutDriver:
    af = _mm(entry, "across_flats", where)
    base = NUT_DRIVERS.get(af)
    if base is None and "outer_radius" not in entry:
        msg = f"{where}: no built-in nut driver is {af:g} mm; give outer_radius"
        raise ValueError(msg)
    driver = NutDriver(
        af,
        _mm(entry, "outer_radius", where, base.outer_radius if base else None),
        _mm(entry, "handle_radius", where, base.handle_radius if base else 18.0),
        _mm(entry, "handle_length", where, base.handle_length if base else 118.0),
        label=name,
    )
    if driver.outer_radius <= af / math.sqrt(3):
        msg = f"{where}: outer_radius ({driver.outer_radius:g}) is inside the hex's corners"
        raise ValueError(msg)
    return CustomNutDriver(name, driver)


def _driver(name: str, entry: dict, where: str) -> CustomDriver:
    tip = entry.get("tip")
    if tip not in SHAFT_RADIUS:
        msg = f"{where}: tip must be one of {', '.join(SHAFT_RADIUS)}, got {tip!r}"
        raise ValueError(msg)
    radius = _mm(entry, "shaft_radius", where, SHAFT_RADIUS[tip])
    length = _mm(entry, "shaft_length", where, SHAFT_LENGTH)
    return CustomDriver(name, tip, radius, length)


_BUILDERS = {
    "hex-key": _hex_key,
    "torx-key": _torx_key,
    "spanner": _spanner,
    "socket": _socket,
    "nut-driver": _nut_driver,
    "driver": _driver,
}


# ---------------------------------------------------------------------------
# The listing `wrenchroom tools --sidecar` adds.
# ---------------------------------------------------------------------------


def listing(tools: CustomTools, source: str) -> Iterator[str]:
    """The custom tools and their numbers, one a line, after the kit's own."""
    if not tools:
        return
    yield f"custom tools, from {source} (tried after the kit's own; mm):"
    for tool in tools.tools:
        yield f"  {tool.name:<17} {_describe(tool)}"


def _describe(tool: CustomTool) -> str:
    if isinstance(tool, CustomKey):
        if tool.kind == "torx-key":
            return f"Torx key {tool.size}, long {tool.long_mm:g}, short {tool.short_mm:g}"
        return f"hex key {tool.size}, long {tool.long_mm:g}, short {tool.short_mm:g}"
    if isinstance(tool, CustomSpanner):
        s = tool.spanner
        stubby = f", stubby {s.stubby_length:g}" if s.stubby_length else ""
        return f"spanner {s.af:g}, {' and '.join(tool.ends)} end, length {s.length:g}{stubby}"
    if isinstance(tool, CustomSocket):
        s = tool.socket
        return f"socket {s.af:g}, outer r {s.outer_radius:g}, length {s.length:g}"
    if isinstance(tool, CustomNutDriver):
        return f"nut driver {tool.driver.af:g}, outer r {tool.driver.outer_radius:g}"
    return f"driver {tool.tip}, shaft r {tool.shaft_radius:g}, length {tool.shaft_length:g}"
