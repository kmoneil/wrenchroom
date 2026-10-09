"""The YAML sidecar: hand-written fastener descriptions, ignores and forced pairs.

Since M4, part names and geometry find fasteners the sidecar doesn't name
(``checks: {detect: false}`` turns that off). The sidecar stays authoritative: a rule
that matches a part describes it outright and detection leaves it alone, because the
human who wrote it has seen the model and the detector hasn't.

Two rules here are lessons the prototype paid for:

- A rule that matches no part is reported, never dropped. A glob that stops matching
  is usually a renamed part, and silence turns that into a fastener nobody checks.
  So is every other glob: an ignore, a state's removal, a rule's mate.
- Nothing is ignored silently. An unknown key is a loud error, because a sidecar
  section that did nothing would look exactly like one that worked.

Later rules override earlier ones for the same part, so a broad glob can set the
family and a narrow one the exception, in reading order.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from math import sqrt
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from wrenchroom.fasteners import AUTO, Fastener, Head, Kind, Size
from wrenchroom.tools.custom import CustomTools, parse_tools

if TYPE_CHECKING:
    from collections.abc import Iterable

    from wrenchroom.assembly import Assembly

_SUPPORTED_TOP = {
    "fasteners",
    "ignore",
    "pairs",
    "states",
    "checks",
    "tools",
    "allow",
    "build",
    "connectors",
}
_CONNECTOR_KEYS = {"parts", "axis", "travel", "grip", "latch", "mates", "receptacle", "state"}
_STATE_KEYS = {"remove", "base", "model"}
_STEP_KEYS = {"step", "add", "model"}
_CHECKS_KEYS = {"default_state", "try_states", "detect", "hand_room", "clashes"}
_RULE_KEYS = {
    "parts",
    "kind",
    "head",
    "size",
    "length",
    "tool",
    "axis",
    "socket",
    "mates",
    "state",
    "across_flats",
}

#: The ``add:`` glob that takes every part no other step adds, in whichever step has it.
CATCH_ALL = "*"


class ConfigError(ValueError):
    """A sidecar the checks must not run with; the message names the spot."""


@dataclass(frozen=True)
class Rule:
    """One ``fasteners:`` entry: a part glob and the description it applies."""

    parts: str
    kind: Kind
    head: Head | None = None
    size: Size | None = None
    length_mm: float | None = None
    tool: str | None = None
    axis: str | tuple[float, float, float] = AUTO
    socket_allowed: bool = True
    mates: tuple[str, ...] = ()
    state: str | None = None
    drive_af: float | None = None


@dataclass(frozen=True)
class StateDef:
    """One named state: parts off, and/or another model of the same parts.

    ``base`` chains states; the effective removals walk the chain, and the
    nearest ``model`` on the chain wins.
    """

    name: str
    remove: tuple[str, ...] = ()
    base: str | None = None
    model: str | None = None


class Grip(enum.StrEnum):
    """How a plug is gripped to pull it: two fingers either side, or a fist round it."""

    PINCH = "pinch"
    HAND = "hand"


@dataclass(frozen=True)
class ConnectorRule:
    """One ``connectors:`` entry: a part glob, and how its plug comes off.

    ``axis`` and ``travel`` are found from the geometry where they are None (``auto``),
    and so is ``receptacle``, a glob, the part it plugs into.
    """

    parts: str
    axis: tuple[float, float, float] | None = None
    travel_mm: float | None = None
    grip: Grip = Grip.PINCH
    latch: tuple[float, float, float] | None = None
    mates: tuple[str, ...] = ()
    receptacle: str | None = None
    state: str | None = None


@dataclass(frozen=True)
class ConnectorMatches:
    """What the ``connectors:`` rules found in an assembly, and what they didn't."""

    rules: dict[str, ConnectorRule]
    unmatched_rules: tuple[str, ...] = ()
    unmatched_mates: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class BuildStep:
    """One ``build:`` step: the parts it adds, and the model it is checked in.

    ``model`` is the mechanism as it sits during the step, as a state's is: None for
    the model as given.
    """

    name: str
    add: tuple[str, ...]
    model: str | None = None


@dataclass(frozen=True)
class Config:
    """A parsed sidecar: rules in file order, ignore globs, forced pairs."""

    rules: tuple[Rule, ...] = ()
    ignore: tuple[str, ...] = ()
    pairs: tuple[tuple[str, str], ...] = ()
    states: tuple[StateDef, ...] = ()
    default_state: str | None = None
    try_states: tuple[str, ...] = ()
    #: Find fasteners the rules don't name, from part names and geometry (M4).
    #: On unless ``checks: {detect: false}`` says otherwise.
    detect: bool = True
    #: Check room for the hand round each handle (spec 6.4); off until tuned,
    #: so ``checks: {hand_room: true}`` (or ``--hand-room``) asks for it.
    hand_room: bool = False
    #: Look for parts drawn into each other over the whole model inside ``check``
    #: (M8); off at first, as a model drawn with shortcuts would fail every run, so
    #: ``checks: {clashes: true}`` (or ``--clashes``) asks for it.
    clashes: bool = False
    #: Pairs of part globs meant to overlap, never a clash: a press fit, a shaft in
    #: its bearing, a belt round its pulley.
    allow: tuple[tuple[str, str], ...] = ()
    #: The sidecar's own tools (spec 5.3), which join whatever kit is used.
    tools: CustomTools = field(default_factory=CustomTools)
    #: The build, in order (M8): each fastener is checked in the step that adds it,
    #: among the parts added by then. Empty when the sidecar has none.
    build: tuple[BuildStep, ...] = ()
    #: The plugs to check come off their receptacles (M9), in file order.
    connectors: tuple[ConnectorRule, ...] = ()
    source: str = "<none>"
    #: The folder the sidecar was read from, when it was read from a file: where a
    #: state's ``model:`` is looked for first (issue #73). None for a mapping.
    directory: Path | None = None

    @classmethod
    def load(cls, path: str | Path) -> Config:
        """Read and validate a sidecar file.

        Raises:
            ConfigError: On YAML that doesn't parse, keys this version doesn't
                know, or values outside the schema. The message carries the file
                and the rule index.
        """
        path = Path(path)
        try:
            raw = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            msg = f"{path}: not valid YAML: {exc}"
            raise ConfigError(msg) from exc
        config = cls.from_dict(raw if raw is not None else {}, source=str(path))
        return replace(config, directory=path.parent)

    @classmethod
    def from_dict(cls, raw: object, source: str = "<dict>") -> Config:
        """Validate an already-loaded mapping; the YAML-free path for tests and API."""
        if not isinstance(raw, dict):
            msg = f"{source}: the sidecar must be a mapping, got {type(raw).__name__}"
            raise ConfigError(msg)
        for key in raw:
            if key not in _SUPPORTED_TOP:
                msg = f"{source}: unknown key {key!r} (supported: {sorted(_SUPPORTED_TOP)})"
                raise ConfigError(msg)
        entries = _as_list(raw.get("fasteners", []), f"{source}: fasteners")
        rules = tuple(_parse_rule(entry, index, source) for index, entry in enumerate(entries))
        ignore = tuple(
            _as_str(glob, f"{source}: ignore[{i}]")
            for i, glob in enumerate(_as_list(raw.get("ignore", []), f"{source}: ignore"))
        )
        pairs = tuple(
            _parse_pair(entry, index, source)
            for index, entry in enumerate(_as_list(raw.get("pairs", []), f"{source}: pairs"))
        )
        allow = tuple(
            _parse_allow(entry, index, source)
            for index, entry in enumerate(_as_list(raw.get("allow", []), f"{source}: allow"))
        )
        states = _parse_states(raw.get("states", {}), source)
        build = _parse_build(raw["build"], source) if "build" in raw else ()
        connectors = tuple(
            _parse_connector(entry, index, source)
            for index, entry in enumerate(
                _as_list(raw.get("connectors", []), f"{source}: connectors")
            )
        )
        default_state, try_states, detect, hand_room, clashes = _parse_checks(
            raw.get("checks", {}), states, source
        )
        try:
            tools = parse_tools(raw.get("tools"), f"{source}: tools")
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        state_names = {state.name for state in states}
        for rule in (*rules, *connectors):
            if rule.state is not None and rule.state not in state_names:
                msg = f"{source}: rule {rule.parts!r} names unknown state {rule.state!r}"
                raise ConfigError(msg)
        return cls(
            rules=rules,
            ignore=ignore,
            pairs=pairs,
            states=states,
            default_state=default_state,
            try_states=try_states,
            detect=detect,
            hand_room=hand_room,
            clashes=clashes,
            allow=allow,
            tools=tools,
            build=build,
            connectors=connectors,
            source=source,
        )

    def state(self, name: str) -> StateDef:
        """The state by name; parsing already guaranteed it exists."""
        for state in self.states:
            if state.name == name:
                return state
        msg = f"unknown state {name!r}"
        raise ConfigError(msg)

    def state_removes(self, name: str) -> tuple[str, ...]:
        """The effective removal globs: the base chain's, then this state's own."""
        state = self.state(name)
        inherited = self.state_removes(state.base) if state.base else ()
        return (*inherited, *state.remove)

    def state_model(self, name: str) -> str | None:
        """The model this state uses: its own, else the nearest up the chain."""
        state = self.state(name)
        if state.model is not None:
            return state.model
        return self.state_model(state.base) if state.base else None

    def apply(self, assembly: Assembly) -> Matches:
        """Match the rules against an assembly's part names.

        Later rules override earlier ones for the same part. Every rule, ignore and
        mate glob that matched nothing is reported in the result; dropping one
        silently is how a renamed part stops being checked. (A mate is looked for
        only where its rule matched: an unmatched rule is reported already.)
        """
        by_part: dict[str, Rule] = {}
        unmatched_rules: list[Rule] = []
        unmatched_mates: list[tuple[str, str]] = []
        # A piece of a leaf drawn as several solids goes with its leaf (issue #28).
        names = [
            part.name
            for part in assembly
            if part.piece_of is None and not self.is_ignored(part.name)
        ]
        for rule in self.rules:
            hits = [name for name in names if fnmatchcase(name, rule.parts)]
            if not hits:
                unmatched_rules.append(rule)
            for name in hits:
                by_part[name] = rule
            unmatched_mates.extend(
                (rule.parts, glob)
                for glob in rule.mates
                if hits and not any(is_mate(name, (glob,)) for name in assembly.names)
            )
        fasteners = tuple(
            Fastener(
                name=name,
                kind=rule.kind,
                head=rule.head,
                size=rule.size,
                length_mm=rule.length_mm,
                axis=rule.axis,
                tool=rule.tool,
                socket_allowed=rule.socket_allowed,
                mates=rule.mates,
                state=rule.state,
                drive_af=rule.drive_af,
            )
            for name, rule in by_part.items()
        )
        unmatched_ignores = tuple(
            glob
            for glob in self.ignore
            if not any(fnmatchcase(name, glob) for name in assembly.names)
        )
        return Matches(
            fasteners=fasteners,
            unmatched_rules=tuple(unmatched_rules),
            unmatched_ignores=unmatched_ignores,
            unmatched_mates=tuple(unmatched_mates),
        )

    def apply_connectors(self, assembly: Assembly) -> ConnectorMatches:
        """Match the ``connectors:`` rules against an assembly's part names.

        As the fastener rules are matched: a later rule replaces an earlier one, whole,
        for a part both name; a piece of a part drawn as several solids goes with it;
        an ignored part is no connector; and a glob that matches nothing, a rule's or
        its mates', is reported.
        """
        names = [
            part.name
            for part in assembly
            if part.piece_of is None and not self.is_ignored(part.name)
        ]
        found: dict[str, ConnectorRule] = {}
        unmatched: list[str] = []
        mates: list[tuple[str, str]] = []
        for rule in self.connectors:
            hits = [name for name in names if fnmatchcase(name, rule.parts)]
            if not hits:
                unmatched.append(rule.parts)
            for name in hits:
                found[name] = rule
            mates.extend(
                (rule.parts, glob)
                for glob in rule.mates
                if hits and not any(is_mate(name, (glob,)) for name in assembly.names)
            )
        return ConnectorMatches(found, tuple(unmatched), tuple(mates))

    def is_ignored(self, name: str) -> bool:
        """True when a part name matches an ignore glob (wires, springs: pushed aside)."""
        return any(fnmatchcase(name, glob) for glob in self.ignore)

    def allows(self, first: str, second: str) -> bool:
        """Whether an ``allow:`` pair lets these two parts overlap, either way round."""
        return any(
            (fnmatchcase(first, a) and fnmatchcase(second, b))
            or (fnmatchcase(first, b) and fnmatchcase(second, a))
            for a, b in self.allow
        )

    def unmatched_allows(self, names: Iterable[str]) -> tuple[str, ...]:
        """Each ``allow:`` glob that names no part: a renamed part, as for a rule."""
        names = tuple(names)
        globs = dict.fromkeys(glob for pair in self.allow for glob in pair)
        return tuple(g for g in globs if not any(fnmatchcase(name, g) for name in names))


@dataclass(frozen=True)
class Matches:
    """What a sidecar found in an assembly, and what it failed to find.

    ``unmatched_mates`` holds (the rule's parts glob, the mate glob) pairs.
    """

    fasteners: tuple[Fastener, ...]
    unmatched_rules: tuple[Rule, ...] = ()
    unmatched_ignores: tuple[str, ...] = ()
    unmatched_mates: tuple[tuple[str, str], ...] = ()

    @property
    def clean(self) -> bool:
        """True when every rule, ignore and mate glob matched something."""
        return not (self.unmatched_rules or self.unmatched_ignores or self.unmatched_mates)


def is_mate(name: str, mates: tuple[str, ...]) -> bool:
    """Whether a part is one of a fastener's mates: a glob, as every other part list.

    A name also matches itself exactly, as mates were exact names before they
    took globs: ``washer[1]`` still names the part called that, not ``washer1``.
    """
    return any(name == glob or fnmatchcase(name, glob) for glob in mates)


def _parse_rule(entry: object, index: int, source: str) -> Rule:
    where = f"{source}: fasteners[{index}]"
    if not isinstance(entry, dict):
        msg = f"{where}: must be a mapping"
        raise ConfigError(msg)
    unknown = set(entry) - _RULE_KEYS
    if unknown:
        msg = f"{where}: unknown key(s) {sorted(unknown)}"
        raise ConfigError(msg)
    if "parts" not in entry:
        msg = f"{where}: 'parts' is required"
        raise ConfigError(msg)
    head = _parse_enum(entry.get("head"), Head, f"{where}: head")
    kind = _parse_enum(entry.get("kind"), Kind, f"{where}: kind")
    if kind is None:
        # A head implies a screw; a bare rule is a screw too. Nuts say so.
        kind = Kind.SCREW
    size = None
    if "size" in entry:
        try:
            size = Size.parse(str(entry["size"]))
        except ValueError as exc:
            msg = f"{where}: {exc}"
            raise ConfigError(msg) from exc
    return Rule(
        parts=_as_str(entry["parts"], f"{where}: parts"),
        kind=kind,
        head=head,
        size=size,
        length_mm=_parse_length(entry.get("length"), where),
        tool=None if entry.get("tool") is None else str(entry["tool"]),
        axis=_parse_axis(entry.get("axis", AUTO), where),
        socket_allowed=_parse_bool(entry.get("socket", True), f"{where}: socket"),
        mates=tuple(
            _as_str(m, f"{where}: mates[{i}]")
            for i, m in enumerate(_as_list(entry.get("mates", []), f"{where}: mates"))
        ),
        state=None if entry.get("state") is None else str(entry["state"]),
        drive_af=_parse_positive(entry.get("across_flats"), f"{where}: across_flats"),
    )


def _parse_connector(entry: object, index: int, source: str) -> ConnectorRule:
    where = f"{source}: connectors[{index}]"
    if not isinstance(entry, dict):
        msg = f"{where}: must be a mapping"
        raise ConfigError(msg)
    unknown = set(entry) - _CONNECTOR_KEYS
    if unknown:
        msg = f"{where}: unknown key(s) {sorted(unknown)}"
        raise ConfigError(msg)
    if "parts" not in entry:
        msg = f"{where}: 'parts' is required"
        raise ConfigError(msg)
    axis = _parse_axis(entry.get("axis", AUTO), where)
    travel = entry.get("travel", AUTO)
    latch = entry.get("latch")
    if latch == AUTO:
        msg = f"{where}: latch is the side its release is pressed from: +x style, or [x, y, z]"
        raise ConfigError(msg)
    latch_side = None if latch is None else _parse_axis(latch, f"{where}: latch")
    return ConnectorRule(
        parts=_as_str(entry["parts"], f"{where}: parts"),
        axis=axis if isinstance(axis, tuple) else None,
        travel_mm=None if travel == AUTO else _parse_positive(travel, f"{where}: travel"),
        grip=_parse_enum(entry.get("grip"), Grip, f"{where}: grip") or Grip.PINCH,
        latch=latch_side if not isinstance(latch_side, str) else None,
        mates=tuple(
            _as_str(m, f"{where}: mates[{i}]")
            for i, m in enumerate(_as_list(entry.get("mates", []), f"{where}: mates"))
        ),
        receptacle=None
        if entry.get("receptacle") is None
        else _as_str(entry["receptacle"], f"{where}: receptacle"),
        state=None if entry.get("state") is None else str(entry["state"]),
    )


def _parse_allow(entry: object, index: int, source: str) -> tuple[str, str]:
    where = f"{source}: allow[{index}]"
    match entry:
        case [str() as first, str() as second]:
            return (first, second)
        case _:
            msg = f"{where}: an allowed overlap is a two-item list of part globs [a, b]"
            raise ConfigError(msg)


def _parse_pair(entry: object, index: int, source: str) -> tuple[str, str]:
    where = f"{source}: pairs[{index}]"
    match entry:
        case [screw, nut]:
            return (str(screw), str(nut))
        case _:
            msg = f"{where}: a pair is a two-item list [screw, nut]"
            raise ConfigError(msg)


def _parse_axis(value: object, where: str) -> str | tuple[float, float, float]:
    named = {
        "+x": (1.0, 0.0, 0.0),
        "-x": (-1.0, 0.0, 0.0),
        "+y": (0.0, 1.0, 0.0),
        "-y": (0.0, -1.0, 0.0),
        "+z": (0.0, 0.0, 1.0),
        "-z": (0.0, 0.0, -1.0),
    }
    if value == AUTO:
        return AUTO
    if isinstance(value, str):
        if value in named:
            return named[value]
        msg = f"{where}: axis must be auto, one of {sorted(named)}, or [x, y, z]"
        raise ConfigError(msg)
    match value:
        case [raw_x, raw_y, raw_z]:
            components: list[float] = []
            for raw in (raw_x, raw_y, raw_z):
                if isinstance(raw, bool) or not isinstance(raw, int | float):
                    msg = f"{where}: axis components must be numbers"
                    raise ConfigError(msg)
                components.append(float(raw))
            x, y, z = components
            norm = sqrt(x * x + y * y + z * z)
            if norm == 0:
                msg = f"{where}: axis must not be the zero vector"
                raise ConfigError(msg)
            return (x / norm, y / norm, z / norm)
        case _:
            msg = f"{where}: axis must be auto, +x style, or [x, y, z]"
            raise ConfigError(msg)


def _parse_positive(value: object, where: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return float(value)
    msg = f"{where} must be a positive number of millimetres"
    raise ConfigError(msg)


def _parse_length(value: object, where: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return float(value)
    msg = f"{where}: length must be a positive number of millimetres"
    raise ConfigError(msg)


def _parse_bool(value: object, where: str) -> bool:
    if isinstance(value, bool):
        return value
    msg = f"{where}: must be true or false"
    raise ConfigError(msg)


def _parse_enum[E: enum.Enum](value: object, enum_type: type[E], where: str) -> E | None:
    if value is None:
        return None
    try:
        return enum_type(str(value))
    except ValueError:
        values = [member.value for member in enum_type]
        msg = f"{where}: {value!r} is not one of {values}"
        raise ConfigError(msg) from None


def _as_list(value: object, where: str) -> list[Any]:
    if isinstance(value, list):
        return value
    msg = f"{where} must be a list"
    raise ConfigError(msg)


def _as_str(value: object, where: str) -> str:
    if isinstance(value, str):
        return value
    msg = f"{where} must be a string"
    raise ConfigError(msg)


def _parse_states(raw: object, source: str) -> tuple[StateDef, ...]:
    where = f"{source}: states"
    if not isinstance(raw, dict):
        msg = f"{where} must be a mapping of state names"
        raise ConfigError(msg)
    states = []
    for name, entry in raw.items():
        state_where = f"{where}[{name}]"
        if not isinstance(entry, dict):
            msg = f"{state_where}: must be a mapping"
            raise ConfigError(msg)
        unknown = set(entry) - _STATE_KEYS
        if unknown:
            msg = f"{state_where}: unknown key(s) {sorted(unknown)}"
            raise ConfigError(msg)
        states.append(
            StateDef(
                name=str(name),
                remove=tuple(
                    _as_str(g, f"{state_where}: remove[{i}]")
                    for i, g in enumerate(
                        _as_list(entry.get("remove", []), f"{state_where}: remove")
                    )
                ),
                base=None if entry.get("base") is None else str(entry["base"]),
                model=None if entry.get("model") is None else str(entry["model"]),
            )
        )
    names = {state.name for state in states}
    for state in states:
        if state.base is not None and state.base not in names:
            msg = f"{where}[{state.name}]: base {state.base!r} is not a state"
            raise ConfigError(msg)
    _reject_base_cycles(states, where)
    return tuple(states)


def _parse_build(raw: object, source: str) -> tuple[BuildStep, ...]:
    """The ``build:`` steps, in order: each named once, each adding parts.

    Which parts each adds is the model's business, so it is checked against the model
    (:func:`wrenchroom.build.plan`); here, only that the list says something.
    """
    where = f"{source}: build"
    entries = _as_list(raw, where)
    if not entries:
        msg = f"{where}: lists no steps (leave it out for no build)"
        raise ConfigError(msg)
    steps: list[BuildStep] = []
    for index, entry in enumerate(entries):
        step = _parse_step(entry, f"{where}[{index}]")
        if any(earlier.name == step.name for earlier in steps):
            msg = f"{where}[{index}]: step {step.name!r} is named twice"
            raise ConfigError(msg)
        steps.append(step)
    catching = [step.name for step in steps if CATCH_ALL in step.add]
    if len(catching) > 1:
        msg = (
            f"{where}: steps {catching[0]!r} and {catching[1]!r} both add {CATCH_ALL!r}, "
            "the parts no other step adds: one step can"
        )
        raise ConfigError(msg)
    return tuple(steps)


def _parse_step(entry: object, where: str) -> BuildStep:
    """One ``build:`` step: a name, the globs of the parts it adds, maybe a model."""
    if not isinstance(entry, dict):
        msg = f"{where}: must be a mapping"
        raise ConfigError(msg)
    unknown = set(entry) - _STEP_KEYS
    if unknown:
        msg = f"{where}: unknown key(s) {sorted(unknown)}"
        raise ConfigError(msg)
    for key in ("step", "add"):
        if key not in entry:
            msg = f"{where}: {key!r} is required"
            raise ConfigError(msg)
    name = _as_str(entry["step"], f"{where}: step")
    if not name.strip():
        msg = f"{where}: step needs a name"
        raise ConfigError(msg)
    add = tuple(
        _as_str(glob, f"{where}: add[{i}]")
        for i, glob in enumerate(_as_list(entry["add"], f"{where}: add"))
    )
    if not add:
        msg = f"{where}: step {name!r} adds nothing"
        raise ConfigError(msg)
    model = entry.get("model")
    return BuildStep(name, add, None if model is None else str(model))


def _reject_base_cycles(states: list[StateDef], where: str) -> None:
    by_name = {state.name: state for state in states}
    for state in states:
        seen = {state.name}
        base = state.base
        while base is not None:
            if base in seen:
                msg = f"{where}: base chain through {state.name!r} loops"
                raise ConfigError(msg)
            seen.add(base)
            base = by_name[base].base


def _parse_checks(
    raw: object, states: tuple[StateDef, ...], source: str
) -> tuple[str | None, tuple[str, ...], bool, bool, bool]:
    where = f"{source}: checks"
    if not isinstance(raw, dict):
        msg = f"{where} must be a mapping"
        raise ConfigError(msg)
    unknown = set(raw) - _CHECKS_KEYS
    if unknown:
        msg = f"{where}: unknown key(s) {sorted(unknown)}"
        raise ConfigError(msg)
    names = {state.name for state in states}
    default_state = None if raw.get("default_state") is None else str(raw["default_state"])
    if default_state is not None and default_state not in names:
        msg = f"{where}: default_state {default_state!r} is not a state"
        raise ConfigError(msg)
    try_states = tuple(
        _as_str(s, f"{where}: try_states[{i}]")
        for i, s in enumerate(_as_list(raw.get("try_states", []), f"{where}: try_states"))
    )
    for name in try_states:
        if name not in names:
            msg = f"{where}: try_states names unknown state {name!r}"
            raise ConfigError(msg)
    detect = _parse_bool(raw.get("detect", True), f"{where}: detect")
    hand_room = _parse_bool(raw.get("hand_room", False), f"{where}: hand_room")
    clashes = _parse_bool(raw.get("clashes", False), f"{where}: clashes")
    return default_state, try_states, detect, hand_room, clashes
