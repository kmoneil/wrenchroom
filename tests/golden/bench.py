"""Lays the cells on the grid, writes the STEPs and sidecars, defines the truth.

Cells sit 1000 mm apart so no tool reaches from one into the next (the longest
reach, a socket on a 250 extension plus a 180 ratchet handle, is under 500).
Nothing binary is committed: builders can't drift from the numbers a test
claims, a stored STEP can.

The `twins` group is built here rather than as a cell: it needs one solid
placed twice as instances of a shared product, which is exactly what issue #2
is about, and the ordinary cell path would hide that.
"""

from pathlib import Path

import yaml
from build123d import Compound, Location, Pos, export_step
from cells import CELLS
from parts import plate, slab, socket_screw, state_lever_raised

from wrenchroom.assembly import Assembly
from wrenchroom.check import check
from wrenchroom.config import Config

PITCH = 1000.0

#: The whole bench's verdict counts once every milestone and issue has landed
#: (GOLDEN-BENCH.md section 5.6): the one-line summary of the truth.
FINAL_COUNTS = {
    "fasteners": 36,
    "turns": 23,
    "held": 2,
    "blocked": 10,
    "stuck": 1,
    "not_covered": 0,
}


def sidecar_and_truth():
    """The sidecar and the truth table: static, no geometry built.

    Truth is keyed by full part name; each entry holds the expected JSON fields
    plus an optional "needs" (the milestone or issue it waits on).
    """
    rules, truth = [], {}
    ignore = set()
    for cell in CELLS:
        for rule in cell.rules:
            entry = dict(rule)
            entry["parts"] = f"{cell.name}_{entry['parts']}"
            if "mates" in entry:
                entry["mates"] = [f"{cell.name}_{m}" for m in entry["mates"]]
            rules.append(entry)
        ignore.update(cell.ignore)
        for role, expected in cell.truth.items():
            entry = dict(expected)
            if "blocked_by" in entry:
                entry["blocked_by"] = [f"{cell.name}_{b}" for b in entry["blocked_by"]]
            if "stuck_on" in entry:
                entry["stuck_on"] = [f"{cell.name}_{s}" for s in entry["stuck_on"]]
            if "pair" in entry:
                entry["pair"] = f"{cell.name}_{entry['pair']}"
            truth[f"{cell.name}_{role}"] = entry
    rules.append({"parts": "twins_*_screw", "kind": "screw", "head": "socket", "size": "M6"})
    truth["twins_a_screw"] = {
        "verdict": "blocked",
        "blocked_by": ["twins_wall"],
        "needs": "issue-2",
    }
    truth["twins_b_screw"] = {"verdict": "turns", "needs": "issue-2"}
    sidecar = {
        "fasteners": rules,
        "ignore": sorted(ignore),
        "states": {
            "lid-off": {"remove": ["state_lid_lid"]},
            "lever-up": {"model": "bench_lever-up.step"},
        },
        "checks": {"try_states": ["lever-up"]},
    }
    return sidecar, truth


def build(raised=False):
    """Build every cell's labelled parts in their grid places (geometry; slow-ish)."""
    shapes = []
    for index, cell in enumerate(CELLS):
        at = Pos((index % 6) * PITCH, (index // 6) * PITCH, 0)
        for role, shape in cell.build():
            raised_lever = raised and cell.name == "state_lever" and role == "lever"
            placed = at * (state_lever_raised() if raised_lever else shape)
            placed.label = f"{cell.name}_{role}"
            shapes.append(placed)
    shapes += _twins(len(CELLS))
    return shapes


def _twins(index):
    """One screw solid placed twice as instances of one product; a wall over `a` only."""
    at = Pos((index % 6) * PITCH, (index // 6) * PITCH, 0)
    x, y = at.position.X, at.position.Y
    screw = socket_screw()
    a = screw.moved(Location((x - 100, y, 0)))
    b = screw.moved(Location((x + 100, y, 0)))
    a.label, b.label = "twins_a_screw", "twins_b_screw"
    pl = at * plate(w=300, holes=[(-100, 0, 3), (100, 0, 3)])
    pl.label = "twins_plate"
    wall = at * Pos(-100, 0, 0) * slab(6 + 15, w=100, d=100)
    wall.label = "twins_wall"
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


def write(directory):
    """Write bench.step, bench_lever-up.step and both sidecars into a directory."""
    directory = Path(directory)
    sidecar, truth = sidecar_and_truth()
    export_step(Compound(children=build()), str(directory / "bench.step"))
    export_step(Compound(children=build(raised=True)), str(directory / "bench_lever-up.step"))
    (directory / "wrenchroom.yaml").write_text(yaml.safe_dump(sidecar, sort_keys=False))
    (directory / "bench_edges.yaml").write_text(yaml.safe_dump(edges_sidecar(), sort_keys=False))
    return truth


def canonical(document):
    """The snapshot form of a report: stable across runs and tool versions.

    Drops tool_version, sorts fasteners by name, rounds millimetres to 0.01 and
    degrees to 0.1, so the diff a PR shows is a change of behaviour, never noise.
    """
    out = {k: v for k, v in document.items() if k != "tool_version"}
    out["fasteners"] = sorted(
        (_canonical_fastener(f) for f in document["fasteners"]), key=lambda f: f["name"]
    )
    return out


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


def check_bench(directory, config_name="wrenchroom.yaml"):
    """Read the written bench back and check it, as a user would."""
    directory = Path(directory)
    assembly = Assembly.from_step(directory / "bench.step")
    config = Config.load(directory / config_name)
    return check(assembly, config, model="bench.step", model_dir=directory)
