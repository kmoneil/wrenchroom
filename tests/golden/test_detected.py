"""M4's exit test: the bench checked with no fastener rules at all.

The sidecar keeps its ignores and states; every fastener rule is taken out, so
names and geometry must find the bench's fasteners on their own. The bar (spec
14, named parts): at least 90% found with the right kind and size, and the rest
reported, never silently skipped. Measured when this landed: all 36, with the
verdicts of 34 matching the hand-worked truth. The two that differ need what
only a sidecar can say, and are pinned here so they stay explained:

- nyloc_two_bodies_nut: its nylon dome is a separate solid, which only the
  sidecar's `mates` makes part of it. Without that the dome covers the nut's
  free face, both ends read covered, and the nut is honestly not-covered.
- state_lid_screw: reached with the lid off, which only the sidecar's
  `state: lid-off` says. Without it the lid blocks the screw.
- pan_t40_torx_screw: an M8 pan head with a T40 recess, which only the sidecar's
  `across_flats:` says (issue #82). By its thread it needs a T45, which no kit holds.

Since issue #19 the tools agree too, and each screw's head is its rule's: a
verdict alone let torx_wall_screw pass turned by a hex key that can't drive it.

The whole detected report is snapshotted too (bench.detected.snapshot.json),
on both engines against the one file, so any change in what detection finds or
how shows up in review.
"""

import fnmatch
import json
from pathlib import Path

import pytest
from bench import canonical, check_detected, sidecar_and_truth

from wrenchroom.detect import read_name
from wrenchroom.detect.names import ends_in_part_noun

SNAPSHOT = Path(__file__).parent / "bench.detected.snapshot.json"

#: The verdicts that need the sidecar, and what they read without it.
NEEDS_THE_SIDECAR = {
    "nyloc_two_bodies_nut": "not-covered",
    "state_lid_screw": "blocked",
    "pan_t40_torx_screw": "not-covered",
}


@pytest.fixture(scope="module")
def detected(bench_dir, bench_engine):
    return check_detected(bench_dir, engine=bench_engine)


def _described():
    sidecar, truth = sidecar_and_truth()
    return sidecar["fasteners"], truth


def _rule(name, rules):
    matches = [rule for rule in rules if fnmatch.fnmatchcase(name, rule["parts"])]
    return matches[-1] if matches else None


def _right(fastener, rule):
    """Right kind, and right size: a gland's, which has no thread size by design,
    is right when its measured hex is the rule's (its across_flats, or the hex its
    size stands for: 24 for the M16 rules)."""
    if fastener.kind.value != rule.get("kind", "screw"):
        return False
    if not fastener.socket_allowed:
        hex_af = rule.get("across_flats", 24.0)
        return fastener.size is None and fastener.drive_af == pytest.approx(hex_af)
    return fastener.size is not None and fastener.size.designation == rule["size"]


def test_detection_finds_the_bench_with_no_rules(detected):
    rules, truth = _described()
    by_name = {result.fastener.name: result for result in detected.results}
    described = [name for name in truth if _rule(name, rules) is not None]
    right = [
        name
        for name in described
        if name in by_name and _right(by_name[name].fastener, _rule(name, rules))
    ]
    assert len(right) / len(described) >= 0.9  # the M4 bar
    assert sorted(right) == sorted(described)  # what it measured: all of them


def test_nothing_found_is_skipped_silently(detected):
    for result in detected.results:
        if result.verdict.value == "not-covered":
            assert result.reason, result.fastener.name


def test_every_detected_fastener_says_how_it_was_found(detected):
    for result in detected.results:
        assert result.fastener.source in {"name", "name+geometry"}
        assert result.fastener.basis


def test_verdicts_match_the_truth_but_where_the_sidecar_is_needed(detected):
    _, truth = _described()
    by_name = {result.fastener.name: result for result in detected.results}
    differ = {
        name: by_name[name].verdict.value
        for name, expected in truth.items()
        if name in by_name and by_name[name].verdict.value != expected["verdict"]
    }
    assert differ == NEEDS_THE_SIDECAR


def test_every_detected_screw_has_its_rule_s_head(detected):
    rules, truth = _described()
    by_name = {result.fastener.name: result.fastener for result in detected.results}
    screws = [name for name in truth if (rule := _rule(name, rules)) and "head" in rule]
    assert len(screws) > 20  # a vacuity guard: most of the bench is screws
    heads = {name: by_name[name].head.value for name in screws}
    assert heads == {name: _rule(name, rules)["head"] for name in screws}
    assert heads["torx_wall_screw"] == "torx"  # issue #19, by its name


def test_detected_tools_match_the_truth_but_where_the_sidecar_is_needed(detected):
    _, truth = _described()
    by_name = {result.fastener.name: result for result in detected.results}
    named = {name: want["tool"] for name, want in truth.items() if "tool" in want}
    assert len(named) > 20  # a vacuity guard
    differ = {name for name, tool in named.items() if by_name[name].tool != tool}
    assert differ <= set(NEEDS_THE_SIDECAR)
    assert by_name["torx_wall_screw"].tool == "torx-key-T30"


def test_every_candidate_name_is_taken_on_its_solid_or_passed_over(detected):
    """Issue #30: a fastener noun with words after it. On the bench the one whose
    solid shows a drive is vented's gland; every other is a plate, block, stud,
    tube or dome, and none is taken; nor is badge's bare insert, with no bore
    (issue #84). Those passed over are listed by name, but not a name ending in a
    part's noun (gland_rib_plate, nut_gap_plate): it says what the part is, and a
    note would be noise (issue #75)."""
    names = detected.models[None].assembly.names
    candidates = {
        name
        for name in names
        if name not in detected.ignored
        and (hint := read_name(name))
        and (hint.needs_drive or hint.needs_bore)
    }
    assert len(candidates) > 15  # a vacuity guard: the bench is full of such names
    said = {name for name in candidates if not ends_in_part_noun(name)}
    assert len(candidates - said) > 5  # and of plates and blocks
    # Those taken on their solids: vented's gland by its hex, badge's boss insert by
    # its bore (issue #84), std's four screws named by thread and length by their
    # drives (issue #95); std's stud, named M8x60, shows none and is passed over.
    taken_on_solid = {"vented_gland_vent", "badge_boss_insert"}
    taken_on_solid |= {f"std_{role}" for role in ("M3x16", "M5-0.8x12", "M4x0.7x12", "#10-32x1")}
    assert "std_M8x60" in said - taken_on_solid
    named = {part.name for part in detected.passed_over if part.named and not part.motion}
    assert named == said - taken_on_solid
    taken = {r.fastener.name for r in detected.results}
    assert candidates & taken == taken_on_solid
    (gland,) = [r for r in detected.results if r.fastener.name == "vented_gland_vent"]
    assert (gland.tool, gland.fastener.confidence) == ("spanner-24", "medium")


def test_an_unnamed_part_that_looks_like_a_fastener_is_passed_over(detected, bench_report):
    """Issue #95: std's part7, part8 and part9, an M6 socket head screw, an M4 Phillips
    pan head and an M8 nut drawn in its band, each named nothing a fastener is, are
    said in both runs; std's row of standoff, collet, knob, spool, wheel and pin, and
    nothing else on the bench, looks like one."""
    said = "not named as a fastener, but its solid looks like one"
    for report in (detected, bench_report):
        alike = [(p.name, p.kind.value, p.reason) for p in report.passed_over if not p.named]
        assert alike == [
            ("std_part7", "screw", f"{said}: M6 screw, a 5 hex socket"),
            ("std_part8", "screw", f"{said}: M4 screw, a cross in its head"),
            ("std_part9", "nut", f"{said}: M8 nut, 12.8 across flats"),
        ]


def test_a_name_s_length_the_solid_disagrees_with_is_noted(detected):
    """Issue #94: renamed's screw, named M3x12 and drawn 8 long: noted, and the
    solid's length taken, in the detected run; its rule describes it outright."""
    (result,) = [r for r in detected.results if r.fastener.name == "renamed_M3x12_screw"]
    assert result.fastener.length_mm == 8.0
    assert result.notes == (
        "drawn 8.00 long under its head, where its name says 12: taken as drawn",
    )


def test_a_name_s_size_the_solid_disagrees_with_is_noted(detected):
    """Issue #117: misnamed's three M3s, each named M5, are taken as drawn and say
    so, at low confidence; the Phillips takes the PH1 that fits its cross, not an
    M5's PH2. The leadscrew's nut is passed over, in both runs."""
    by_name = {r.fastener.name: r for r in detected.results}
    said = {
        "misnamed_M5x16_screw": "3.00 shank, 2.50 socket",
        "misnamed_M5x12_phillips_screw": "3.00 shank",
        "misnamed_M5_nut": "3.00 bore, 5.50 hex",
    }
    for name, shown in said.items():
        result = by_name[name]
        assert (result.fastener.size.designation, result.fastener.confidence) == ("M3", "low")
        assert result.notes == (
            f"drawn as an M3 ({shown}), where its name says M5: taken as drawn",
        )
    assert by_name["misnamed_M5x12_phillips_screw"].tool == "driver-ph1"


def test_a_leadscrew_s_nut_is_passed_over_in_both_runs(detected, bench_report):
    for report in (detected, bench_report):
        motion = [(p.name, p.kind.value) for p in report.passed_over if p.motion]
        assert motion == [("misnamed_leadscrew_nut", "nut")]
        assert "misnamed_leadscrew_nut" not in {r.fastener.name for r in report.results}


def test_the_detected_report_matches_its_snapshot(detected):
    got = canonical(detected.to_json_dict())
    want = json.loads(SNAPSHOT.read_text())
    assert got == want, (
        "the detected report moved; if the change is meant, run "
        "`uv run python scripts/golden.py --update` and review the diff"
    )


def test_a_nut_drawn_small_says_so_and_where_its_size_came_from(detected):
    """Issue #50: the bore says M8 (undersize), or the bolt does (guessed), or the
    name does (named_size); where the band's guess is the bolt's size (band_agrees)
    there is nothing to say."""
    notes = {result.fastener.name: result.notes for result in detected.results}
    small = (
        "hex drawn undersize: 12.60 across flats, 0.13 under the least its M8 standard "
        "allows (12.73); taken as size 13"
    )
    assert notes["undersize_nut"] == (small,)
    bolt = "size M8 from its bolt, guessed_bolt (its hex alone said 5/16)"
    assert notes["guessed_nut"] == (bolt, small)
    assert notes["named_size_m8_nut"] == (small,)
    assert notes["band_agrees_nut"] == ()
    # Issue #84: a T-nut's bore alone is a guess too, which its screw outranks.
    screw = "size M6 from its screw, tee_hold_screw (its bore alone said M5)"
    assert notes["tee_hold_tnut"] == (screw,)
    noted = {name for name, said in notes.items() if said}
    assert noted == {
        "undersize_nut",
        "guessed_nut",
        "named_size_m8_nut",
        "tee_hold_tnut",
        "badge_boss_insert",  # sized by its screw too
        "w10642_screw",  # its socket drawn loose (issue #82)
        "odd_head_screw",
        "wide_dome_gland",
        "sunk_cap_cap_nut",
        "ball_tilt_screw",
        "ball_shoulder_screw",
        "renamed_M3x12_screw",  # drawn 8 long (issue #94)
        "misnamed_M5x16_screw",  # drawn as M3s (issue #117)
        "misnamed_M5x12_phillips_screw",
        "misnamed_M5_nut",
        "cross_drawn_m4_screw",  # its cross drawn for PH1 (issue #125)
    }


def test_shoulder_screws_drawn_plainly_and_a_head_that_fits_nothing(detected):
    """Issue #48: the shoulder screws are ISO 7379's by their outlines, M6 by their
    shoulder, with ISO 7379's 4 mm key; the odd head is a guess, and says so."""
    by_name = {result.fastener.name: result for result in detected.results}
    for name in ("plain_pin_bolt", "stepped_pin_bolt", "minor_pin_bolt"):
        result = by_name[name]
        assert (result.fastener.head.value, result.fastener.size.designation) == (
            "shoulder",
            "M6",
        )
        assert (result.tool, result.notes) == ("hex-key-4", ())
    odd = by_name["odd_head_screw"]
    assert (odd.fastener.head.value, odd.fastener.confidence, odd.tool) == (
        "button",
        "low",
        "hex-key-4",
    )
    assert odd.notes == (
        "its head is a guess: drawn 12.00 across and 3.00 high, it fits no standard "
        "head, so button by its proportions; set head: in the sidecar",
    )
    # Its name says button: no guess (medium, as its size rests on its shank).
    named = by_name["odd_head_button_screw"]
    assert (named.tool, named.notes, named.fastener.confidence) == ("hex-key-4", (), "medium")
