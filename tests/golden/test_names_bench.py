"""The bench's part names, read with no sidecar: its own rules are the truth.

The parts the bench's sidecar calls fasteners must be found with the right kind,
and no other part may be: not a plate, not a wall, not the pocket block named
"pair_nut_held_upper" (a nut word, but the name is about "held").
"""

import fnmatch

from bench import edges_sidecar, sidecar_and_truth
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
    wrong = []
    found_count = 0
    for name in _bench_names():
        rule = _rule_for(name, rules)
        found = read_name(name)
        if rule is None:
            if found is not None:
                wrong.append((name, "read as a fastener", found))
            continue
        want = Kind(rule.get("kind", "screw"))
        if found is None or found.kind is not want:
            wrong.append((name, f"want {want}", found))
            continue
        found_count += 1
        if "gland" in name:
            assert not found.socket_allowed, name
    assert not wrong
    assert found_count == 37  # the bench's 36 fasteners and the edges file's torx screw
