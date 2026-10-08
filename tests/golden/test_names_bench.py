"""The bench's part names, read with no sidecar: its own rules are the truth.

The parts the bench's sidecar calls fasteners must be found with the right kind,
and no other part may be: not a plate, not a wall, not the pocket block named
"pair_nut_held_upper" (a nut word, but the name is about "held"). A name with
words after its fastener noun is only a candidate, for its solid to decide
(issue #30): vented's "gland_vent" is the one the sidecar calls a fastener.
"""

import fnmatch

from bench import FINAL_COUNTS, WRONG_TOOL, edges_sidecar, sidecar_and_truth
from cells import CELLS

from wrenchroom.detect.names import read_name
from wrenchroom.fasteners import Kind


def _bench_names():
    names = [f"{cell.name}_{role}" for cell in CELLS for role, _ in cell.build()]
    return [*names, "twins_a_screw", "twins_b_screw", "twins_plate", "twins_wall"]


def _rule_for(name, rules):
    matches = [rule for rule in rules if fnmatch.fnmatchcase(name, rule["parts"])]
    return matches[-1] if matches else None


def test_the_bench_names_read_as_its_sidecar_says():
    sidecar, _ = sidecar_and_truth()
    rules = sidecar["fasteners"] + edges_sidecar()["fasteners"]
    wrong, candidates, by_word = [], [], []
    found_count = 0
    for name in _bench_names():
        rule = _rule_for(name, rules)
        found = read_name(name)
        if found is not None and found.needs_drive:
            candidates.append(name)
        if rule is None:  # a candidate waits on its solid: a drive, or a bare insert's bore
            # A leadscrew's nut is passed over by its name alone (issue #117).
            if found is not None and not (found.needs_drive or found.needs_bore or found.motion):
                wrong.append((name, "read as a fastener", found))
            continue
        want = Kind(rule.get("kind", "screw"))
        if found is not None and found.unless_hex and want is Kind.NUT:
            by_word.append(name)  # "well nut" by its name; its hex makes it a nut
        elif found is None or found.kind is not want:
            wrong.append((name, f"want {want}", found))
            continue
        found_count += 1
        if "gland" in name:
            assert not found.socket_allowed, name
    assert not wrong
    # vented's gland, and std's four screws named by thread and length alone (#95).
    assert [name for name in candidates if _rule_for(name, rules)] == [
        "vented_gland_vent",
        "std_M3x16",
        "std_M5-0.8x12",
        "std_M4x0.7x12",
        "std_#10-32x1",
    ]
    # Issue #29: a nut deep in a well reads as a well nut by its name alone; its
    # solid's hex settles it (test_inserts.py, and the detected bench).
    assert by_word == ["nut_deep_well_nut"]
    # The sidecar's fasteners (FINAL_COUNTS less the torx screw only detection finds),
    # the edges file's torx screw, and drawn_in's six nuts, two screws and bolt,
    # wrong_tool's nine, twice's four screws (issue #94) and domed's six (issue #116),
    # which the sidecar ignores.
    assert found_count == FINAL_COUNTS["fasteners"] + 9 + len(WRONG_TOOL) + 4 + 6
    assert len(WRONG_TOOL) == 9
