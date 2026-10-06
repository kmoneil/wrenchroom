"""The YAML sidecar: hand-written fastener descriptions, ignores and forced pairs.

Since M4, part names and geometry find fasteners the sidecar doesn't name
(``checks: {detect: false}`` turns that off). The sidecar stays authoritative: a rule
that matches a part describes it outright and detection leaves it alone, because the
human who wrote it has seen the model and the detector hasn't.

Two rules here are lessons the prototype paid for:

- A rule that matches no part is reported, never dropped. A glob that stops matching
  is usually a renamed part, and silence turns that into a fastener nobody checks.
- Nothing is ignored silently. An unknown key is a loud error, because a sidecar
  section that did nothing would look exactly like one that worked.

Later rules override earlier ones for the same part, so a broad glob can set the
family and a narrow one the exception, in reading order.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from fnmatch import fnmatchcase
from math import sqrt
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from wrenchroom.fasteners import AUTO, Fastener, Head, Kind, Size

if TYPE_CHECKING:
    from wrenchroom.assembly import Assembly

_SUPPORTED_TOP = {"fasteners", "ignore", "pairs", "states", "checks"}
_STATE_KEYS = {"remove", "base", "model"}
_CHECKS_KEYS = {"default_state", "try_states", "detect"}
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
    source: str = "<none>"

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
        return cls.from_dict(raw if raw is not None else {}, source=str(path))

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
        states = _parse_states(raw.get("states", {}), source)
        default_state, try_states, detect = _parse_checks(raw.get("checks", {}), states, source)
        state_names = {state.name for state in states}
        for rule in rules:
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

        Later rules override earlier ones for the same part. Every rule and ignore
        glob that matched nothing is reported in the result; dropping one silently
        is how a renamed part stops being checked.
        """
        by_part: dict[str, Rule] = {}
        unmatched_rules: list[Rule] = []
        names = [name for name in assembly.names if not self.is_ignored(name)]
        for rule in self.rules:
            hits = [name for name in names if fnmatchcase(name, rule.parts)]
            if not hits:
                unmatched_rules.append(rule)
            for name in hits:
                by_part[name] = rule
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
        )

    def is_ignored(self, name: str) -> bool:
        """True when a part name matches an ignore glob (wires, springs: pushed aside)."""
        return any(fnmatchcase(name, glob) for glob in self.ignore)


@dataclass(frozen=True)
class Matches:
    """What a sidecar found in an assembly, and what it failed to find."""

    fasteners: tuple[Fastener, ...]
    unmatched_rules: tuple[Rule, ...] = ()
    unmatched_ignores: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        """True when every rule and ignore glob matched something."""
        return not self.unmatched_rules and not self.unmatched_ignores


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
) -> tuple[str | None, tuple[str, ...], bool]:
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
    return default_state, try_states, detect
