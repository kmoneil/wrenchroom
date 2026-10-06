"""Lays the cells on the grid, writes the STEPs and sidecars, defines the truth.

Cells sit 1000 mm apart so no tool reaches from one into the next (the longest
reach, a socket on a 250 extension plus a 180 ratchet handle, is under 500).
Nothing binary is committed: builders can't drift from the numbers a test
claims, a stored STEP can.

The `twins` group is built here rather than as a cell: it needs one solid
placed twice as instances of a shared product, which is exactly what issue #2
is about, and the ordinary cell path would hide that.

`copies` repeats the whole bench further along the grid (the M3 performance
case, and a check that a cell's answer doesn't depend on where it sits). Copy 0
keeps the plain names, so one copy is exactly the bench; copy k puts `r<k>_` in
front of every name, and its rules, mates, removals and truth follow.
"""

from pathlib import Path

import yaml
from build123d import Compound, Location, Pos, export_step
from cells import CELLS
from parts import plate, slab, socket_screw, state_lever_raised

from wrenchroom import __version__
from wrenchroom.assembly import Assembly
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import md_text

PITCH = 1000.0

#: The kit the bench is checked with: every tool the tables hold. Its 24 mm cells
#: (M16 nuts, glands) need tools the home kit lacks (spec 5.3, decided 2026-10-06);
#: test_kits_bench.py holds what metric-home makes of the bench.
KIT = "full"

#: Grid slots one copy of the bench takes: every cell, then the twins.
SLOTS = len(CELLS) + 1

#: The whole bench's verdict counts once every milestone and issue has landed:
#: the one-line summary of the truth. 37 since M4: the sidecar named 36, and
#: detection finds torx_open_screw, which no rule names; 41 since M6's hand_tight
#: and inch_pair.
FINAL_COUNTS = {
    "fasteners": 41,
    "turns": 28,
    "held": 2,
    "blocked": 10,
    "stuck": 1,
    "not_covered": 0,
}


def copy_prefix(copy):
    """What copy `copy` puts in front of every name: nothing for the first."""
    return f"r{copy}_" if copy else ""


def sidecar_and_truth(copies=1):
    """The sidecar and the truth table: static, no geometry built.

    Truth is keyed by full part name; each entry holds the expected JSON fields
    plus an optional "needs" (the milestone or issue it waits on).
    """
    rules, truth, ignore, lids = [], {}, set(), []
    for copy in range(copies):
        prefix = copy_prefix(copy)
        for cell in CELLS:
            name = f"{prefix}{cell.name}"
            for rule in cell.rules:
                entry = dict(rule)
                entry["parts"] = f"{name}_{entry['parts']}"
                if "mates" in entry:
                    entry["mates"] = [f"{name}_{m}" for m in entry["mates"]]
                rules.append(entry)
            ignore.update(cell.ignore)
            for role, expected in cell.truth.items():
                truth[f"{name}_{role}"] = _named_truth(expected, name)
        rules.append(
            {"parts": f"{prefix}twins_*_screw", "kind": "screw", "head": "socket", "size": "M6"}
        )
        twins_truth = {
            "a_screw": {"verdict": "blocked", "blocked_by": ["wall"]},
            "b_screw": {"verdict": "turns"},
        }
        for role, expected in twins_truth.items():
            truth[f"{prefix}twins_{role}"] = _named_truth(expected, f"{prefix}twins")
        lids.append(f"{prefix}state_lid_lid")
    sidecar = {
        "fasteners": rules,
        "ignore": sorted(ignore),
        "states": {
            "lid-off": {"remove": lids},
            "lever-up": {"model": "bench_lever-up.step"},
        },
        "checks": {"try_states": ["lever-up"]},
    }
    return sidecar, truth


def _named_truth(expected, name):
    """A cell's truth with its roles turned into full part names."""
    entry = dict(expected)
    for key in ("blocked_by", "stuck_on"):
        if key in entry:
            entry[key] = [f"{name}_{role}" for role in entry[key]]
    if "pair" in entry:
        entry["pair"] = f"{name}_{entry['pair']}"
    return entry


def build(raised=False, copies=1):
    """Build every cell's labelled parts in their grid places (geometry; slow-ish)."""
    shapes = []
    for copy in range(copies):
        prefix = copy_prefix(copy)
        for index, cell in enumerate(CELLS):
            at = _slot(copy * SLOTS + index)
            for role, shape in cell.build():
                raised_lever = raised and cell.name == "state_lever" and role == "lever"
                placed = at * (state_lever_raised() if raised_lever else shape)
                placed.label = f"{prefix}{cell.name}_{role}"
                shapes.append(placed)
        shapes += _twins(copy * SLOTS + len(CELLS), prefix)
    return shapes


def _slot(index):
    return Pos((index % 6) * PITCH, (index // 6) * PITCH, 0)


def _twins(index, prefix=""):
    """One screw solid placed twice as instances of one product; a wall over `a` only."""
    at = _slot(index)
    x, y = at.position.X, at.position.Y
    screw = socket_screw()
    a = screw.moved(Location((x - 100, y, 0)))
    b = screw.moved(Location((x + 100, y, 0)))
    a.label, b.label = f"{prefix}twins_a_screw", f"{prefix}twins_b_screw"
    pl = at * plate(w=300, holes=[(-100, 0, 3), (100, 0, 3)])
    pl.label = f"{prefix}twins_plate"
    wall = at * Pos(-100, 0, 0) * slab(6 + 15, w=100, d=100)
    wall.label = f"{prefix}twins_wall"
    return [a, b, pl, wall]


def edges_sidecar():
    """The config-edge sidecar (section 5.5), for the same STEP."""
    return {
        "fasteners": [
            {"parts": "gone_*", "kind": "screw"},
            # The torx_open screw is a plain socket head described as Torx: the
            # kit has no Torx key until M6, and the reason must say so.
            {"parts": "torx_open_screw", "kind": "screw", "head": "torx", "size": "M6"},
        ],
        "ignore": ["*_hose"],
    }


def write(directory, copies=1):
    """Write bench.step, bench_lever-up.step and both sidecars into a directory."""
    directory = Path(directory)
    sidecar, truth = sidecar_and_truth(copies)
    export_step(Compound(children=build(copies=copies)), str(directory / "bench.step"))
    raised = Compound(children=build(raised=True, copies=copies))
    export_step(raised, str(directory / "bench_lever-up.step"))
    (directory / "wrenchroom.yaml").write_text(yaml.safe_dump(sidecar, sort_keys=False))
    (directory / "bench_edges.yaml").write_text(yaml.safe_dump(edges_sidecar(), sort_keys=False))
    return truth


def canonical(document):
    """The snapshot form of a report: stable across runs and tool versions.

    Drops tool_version, sorts fasteners by name, rounds millimetres to 0.01 and
    degrees to 0.1, so the diff a PR shows is a change of behaviour, never noise.
    Drops the engine's name too: one snapshot holds for both engines, which is
    the strongest statement that they agree.
    """
    out = {k: v for k, v in document.items() if k not in ("tool_version", "engine")}
    out["fasteners"] = sorted(
        (_canonical_fastener(f) for f in document["fasteners"]), key=lambda f: f["name"]
    )
    return out


def canonical_markdown(report):
    """The Markdown report with its engine and version, which vary, as placeholders."""
    provenance = f", {report.engine} engine, wrenchroom {md_text(__version__)}."
    text = report.markdown()
    assert text.count(provenance) == 1, "the provenance line moved"
    return text.replace(provenance, ", ENGINE engine, wrenchroom VERSION.")


def _canonical_fastener(entry):
    out = dict(entry)
    for key in ("axis", "seat"):
        if out.get(key) is not None:
            out[key] = [_round_mm(c) for c in out[key]]
    if out.get("swing_deg") is not None:
        out["swing_deg"] = round(out["swing_deg"], 1)
    if out.get("length") is not None:
        out["length"] = _round_mm(out["length"])
    return out


def _round_mm(value):
    rounded = round(value, 2)
    return 0.0 if rounded == 0 else rounded  # no -0.0 in a committed snapshot


def stripped_sidecar():
    """The bench's sidecar with every fastener rule taken out: the M4 exit case.

    Ignores, states and checks stay; what the rules said (kinds, heads, sizes,
    mates, a fastener's own state) must now come from names and geometry.
    """
    sidecar, _ = sidecar_and_truth()
    return {key: value for key, value in sidecar.items() if key != "fasteners"}


def check_detected(directory, engine="mesh"):
    """The written bench checked with no fastener rules: detection finds them all."""
    directory = Path(directory)
    assembly = Assembly.from_step(directory / "bench.step")
    config = Config.from_dict(stripped_sidecar())
    return check(assembly, config, kit=KIT, model="bench.step", model_dir=directory, engine=engine)


def check_bench(directory, config_name="wrenchroom.yaml", engine="mesh", kit=KIT, hand_room=None):
    """Read the written bench back and check it, as a user would."""
    directory = Path(directory)
    assembly = Assembly.from_step(directory / "bench.step")
    config = Config.load(directory / config_name)
    return check(
        assembly,
        config,
        kit=kit,
        model="bench.step",
        model_dir=directory,
        engine=engine,
        hand_room=hand_room,
    )
