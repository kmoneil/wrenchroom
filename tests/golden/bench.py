"""Lays the cells on the grid, writes the STEPs and sidecars, defines the truth.

Cells sit 1000 mm apart so no tool reaches from one into the next (the longest
reach, a 50 mm spanner's handle, 0.85 of its 650, is 553).
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

import re
from collections import Counter
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
#: detection finds torx_open_screw, which no rule names; 45 since M6's hand_tight,
#: inch_pair, torx_wall, ball_tilt and nut_tube; and since M6's open end,
#: glands_close's two turn; 47 since issue #27's hex_band, 48 with #26's nut_gap,
#: 49 with #30's vented, 50 with #31's low_head, 52 with #29's rubber, 54 with
#: #28's one_part_lock, 55 with #33's big_gland, 59 with #25's grazes, 60 with
#: #40's pivot, 61 with the channel (a socket's wall round the hex), 68 with #50's
#: undersize, guessed, band_agrees and named_size, 70 with minor_bore, 73 with
#: #48's plain_pin, stepped_pin, minor_pin and odd_head (two), 77 with #47's
#: snug_dome, wide_dome, dome_rib, sunk_cap and flange_nut, 82 with #49's reach_13
#: and big_tube, 84 with #51's ball_button and ball_shoulder, 85 with #52's post_ring,
#: 87 with short_key and shop_spanner (a sidecar's own tools, spec 5.3), 88 with
#: #63's corner_touch (drawn_in's two clashes are the edges sidecar's alone), 94
#: with #81's chamfers, dome_tip, sunk_tip, named_head, w4762 and w4032, 99 with
#: #84's run_in, tee_hold's screw and T-nut, and badge's screw and boss insert (its
#: logo insert is passed over), 107 with #83's small, eight fasteners below M3 and at
#: #0, 110 with #82's w7380, w10642 and pan_t40, 114 with #95's std, four screws
#: named by thread and length alone, 118 with #96's grip, a set screw and three
#: fasteners turned by hand, 124 with #93's trap, three nuts their blocks hold and
#: their screws, 125 with #94's renamed (twice's three are the edges sidecar's).
FINAL_COUNTS = {
    "fasteners": 125,
    "turns": 97,
    "held": 8,
    "blocked": 19,
    "stuck": 1,
    "not_covered": 0,
}


def copy_prefix(copy):
    """What copy `copy` puts in front of every name: nothing for the first."""
    return f"r{copy}_" if copy else ""


def _chosen(cell, which):
    """Whether a cell is in a bench of ``which``: "all", "timed" or "untimed" cells."""
    return which == "all" or cell.timed == (which == "timed")


def summary_of(truth):
    """The report summary a truth table comes to: what a scaled bench must report."""
    verdicts = Counter(expected["verdict"] for expected in truth.values())
    counts = {"fasteners": len(truth)}
    counts.update({key: verdicts[key] for key in ("turns", "held", "blocked", "stuck")})
    counts["not_covered"] = verdicts["not-covered"]
    return counts


def sidecar_and_truth(copies=1, which="all"):
    """The sidecar and the truth table: static, no geometry built.

    Truth is keyed by full part name; each entry holds the expected JSON fields
    plus an optional "needs" (the milestone or issue it waits on). ``which``
    picks the cells: "all", or the perf bench's "timed" or "untimed" ones.
    """
    rules, truth, ignore, lids = [], {}, set(), []
    for copy in range(copies):
        prefix = copy_prefix(copy)
        for cell in CELLS:
            if not _chosen(cell, which):
                continue
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
        if which != "untimed":  # the twins are ordinary: timed with the rest
            rules.append(
                {"parts": f"{prefix}twins_*_screw", "kind": "screw", "head": "socket", "size": "M6"}
            )
            twins_truth = {
                "a_screw": {"verdict": "blocked", "blocked_by": ["wall"]},
                "b_screw": {"verdict": "turns"},
            }
            for role, expected in twins_truth.items():
                truth[f"{prefix}twins_{role}"] = _named_truth(expected, f"{prefix}twins")
        if any(c.name == "state_lid" and _chosen(c, which) for c in CELLS):
            lids.append(f"{prefix}state_lid_lid")
    sidecar = {
        "fasteners": rules,
        "ignore": sorted(ignore),
        "states": {
            "lid-off": {"remove": lids},
            "lever-up": {"model": "bench_lever-up.step"},
        },
        "checks": {"try_states": ["lever-up"]},
        "tools": _bench_tools(which),
    }
    return sidecar, truth


def _bench_tools(which):
    """The chosen cells' own tools (spec 5.3), each once, however many copies."""
    tools = {tool["name"]: tool for cell in CELLS if _chosen(cell, which) for tool in cell.tools}
    return list(tools.values())


def _named_truth(expected, name):
    """A cell's truth with its roles turned into full part names."""
    entry = dict(expected)
    for key in ("blocked_by", "stuck_on", "grazes", "deciding"):
        if key in entry:
            entry[key] = [f"{name}_{role}" for role in entry[key]]
    if "pair" in entry:
        entry["pair"] = f"{name}_{entry['pair']}"
    return entry


def build(raised=False, copies=1, which="all"):
    """Build every chosen cell's labelled parts in their grid places (geometry; slow-ish)."""
    shapes = []
    for copy in range(copies):
        prefix = copy_prefix(copy)
        for index, cell in enumerate(CELLS):
            if not _chosen(cell, which):
                continue
            at = _slot(copy * SLOTS + index)
            for role, shape in cell.build():
                raised_lever = raised and cell.name == "state_lever" and role == "lever"
                placed = at * (state_lever_raised() if raised_lever else shape)
                placed.label = f"{prefix}{cell.name}_{role}"
                shapes.append(placed)
        if which != "untimed":
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
            # rule outranks the solid's 5 mm hex, so it takes the T30 Torx key.
            # Its mate names a washer the model doesn't have: reported (#32).
            {
                "parts": "torx_open_screw",
                "kind": "screw",
                "head": "torx",
                "size": "M6",
                "mates": ["gone_washer_*"],
            },
            # drawn_in's nuts and screw, which the bench's own sidecar ignores: each is
            # drawn into a block, a clash (issue #63), and a clash is not-covered.
            {"parts": "drawn_in_*_nut", "kind": "nut", "size": "M8"},
            {"parts": "drawn_in_*_screw", "kind": "screw", "head": "socket", "size": "M6"},
            {"parts": "drawn_in_pair_bolt", "kind": "screw", "head": "hex", "size": "M8"},
            # twice's screws, which the bench's own sidecar ignores too (issue #94).
            {"parts": "twice_*screw", "kind": "screw", "head": "socket", "size": "M3"},
            # wrong_tool's fasteners, each with a tool its rule names (issue #72).
            *(_wrong_tool(role, rule) for role, rule in WRONG_TOOL.items()),
        ],
        "ignore": ["*_hose"],
        # wrong_tool's custom_nut names it; no bench fastener takes a 23 mm spanner,
        # so it changes nothing else in the edges run.
        "tools": [
            {"name": "shop-spanner-23", "type": "spanner", "across_flats": 23, "length": 200},
            # No bench fastener takes a 7 mm key, nor does a rule name it: noted (#75).
            {"name": "unused-key-7", "type": "hex-key", "across_flats": 7, "long": 80, "short": 20},
        ],
    }


#: wrong_tool's fasteners: each rule, and the tool it names.
_M8_NUT = {"kind": "nut", "size": "M8"}
_M6_SCREW = {"kind": "screw", "size": "M6"}
WRONG_TOOL = {
    "size_nut": {**_M8_NUT, "tool": "spanner-10"},
    "kind_nut": {**_M8_NUT, "tool": "hex-key-5"},
    "custom_nut": {**_M8_NUT, "tool": "shop-spanner-23"},
    "unknown_nut": {**_M8_NUT, "tool": "spanner-99"},
    "drawn_nut": {"kind": "nut", "size": "M10", "tool": "spanner-15"},
    "button_screw": {**_M6_SCREW, "head": "button", "tool": "spanner-10"},
    "slot_screw": {**_M6_SCREW, "head": "socket", "tool": "driver-slotted"},
    "torx_screw": {**_M6_SCREW, "head": "torx", "tool": "torx-key-T99"},
    "phillips_screw": {"kind": "screw", "head": "phillips", "size": "M4", "tool": "driver-ph1"},
}


def _wrong_tool(role, rule):
    return {"parts": f"wrong_tool_{role}", **rule}


def write(directory, copies=1, which="all"):
    """Write bench.step, bench_lever-up.step and both sidecars into a directory."""
    directory = Path(directory)
    sidecar, truth = sidecar_and_truth(copies, which)
    export_step(Compound(children=build(copies=copies, which=which)), str(directory / "bench.step"))
    raised = Compound(children=build(raised=True, copies=copies, which=which))
    export_step(raised, str(directory / "bench_lever-up.step"))
    (directory / "wrenchroom.yaml").write_text(yaml.safe_dump(sidecar, sort_keys=False))
    (directory / "bench_edges.yaml").write_text(yaml.safe_dump(edges_sidecar(), sort_keys=False))
    return truth


def canonical(document):
    """The snapshot form of a report: stable across runs and tool versions.

    Drops tool_version, sorts fasteners by name, rounds millimetres to 0.01 and
    degrees to 0.1, so the diff a PR shows is a change of behaviour, never noise.
    Drops the engine's name too: one snapshot holds for both engines, which is
    the strongest statement that they agree. And what the engine found of parts
    it looked at closely (issue #85), which only the engine decides.
    """
    dropped = ("tool_version", "engine", "engine_notes")
    out = {k: v for k, v in document.items() if k not in dropped}
    out["fasteners"] = sorted(
        (_canonical_fastener(f) for f in document["fasteners"]), key=lambda f: f["name"]
    )
    return out


def canonical_markdown(report):
    """The Markdown report with its engine and version, which vary, as placeholders.

    What the engine found of the parts (issue #85) goes: it is the engine's own.
    """
    provenance = f", {report.engine} engine, wrenchroom {md_text(__version__)}."
    text = re.sub(r"The engine: [^\n]*\n\n", "", report.markdown())
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
