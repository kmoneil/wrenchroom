"""The bench with hand room on (spec 6.4), which it isn't by default.

Hand room only ever takes a pass away, and says why. On the bench it takes two:
hand_tight's nut, the cell built for it (cells.py works it by hand), and
pair_nut_held's nut. The second is a finding for the tuning hand room still needs:
the spanner's handle leaves its pocket through a slit no taller than the handle,
and the hand's 90 mm, from r 47.7 to the 137.7 reach, starts inside the block
(edge 60) where a real hand, holding the outer end, would not be. pair_both_hold's
bolt and nut, blocked already, are blocked for the same reason in their own
pockets: their reason changes from "only holds" to "no room for a hand". Every
other field of every fastener comes out exactly as with hand room off, on both
engines.
"""

import pytest
from bench import check_bench

#: The passes hand room takes on the bench, and the reason each gives.
CHANGES = {
    "hand_tight_nut": "no room for a hand (hand_tight_block in the way)",
    "pair_nut_held_nut": "no room for a hand (pair_nut_held_pocket in the way)",
}

#: Fasteners blocked either way whose reason hand room changes.
REASONS = {
    "pair_both_hold_bolt": "no room for a hand (pair_both_hold_pocket_high in the way)",
    "pair_both_hold_nut": "no room for a hand (pair_both_hold_pocket_low in the way)",
}


@pytest.fixture(scope="session")
def hand_report(bench_dir, bench_engine):
    return check_bench(bench_dir, engine=bench_engine, hand_room=True)


def test_hand_room_takes_exactly_these_passes_and_says_why(hand_report, bench_json):
    assert hand_report.hand_room
    hand = {r.fastener.name: r for r in hand_report.results}
    changed = {
        name
        for name, entry in bench_json.items()
        if (hand[name].verdict.value, hand[name].tool, hand[name].how)
        != (entry["verdict"], entry["tool"], entry["how"])
    }
    assert changed == set(CHANGES)
    for name, reason in CHANGES.items():
        assert bench_json[name]["verdict"] in {"turns", "held"}, name  # a pass, taken
        assert hand[name].verdict.value == "blocked", name
        assert hand[name].reason == reason, name


def test_some_already_blocked_now_say_it_is_the_hand(hand_report, bench_json):
    hand = {r.fastener.name: r for r in hand_report.results}
    for name, reason in REASONS.items():
        assert bench_json[name]["verdict"] == hand[name].verdict.value == "blocked", name
        assert bench_json[name]["reason"].startswith("only holds"), name
        assert hand[name].reason == reason, name


def test_everything_else_is_the_same_report(hand_report, bench_json):
    document = hand_report.to_json_dict()
    assert document["hand_room"] is True
    for entry in document["fasteners"]:
        name = entry["name"]
        if name in REASONS:
            assert {**entry, "reason": None} == {**bench_json[name], "reason": None}, name
        elif name not in CHANGES:
            assert entry == bench_json[name], name


def test_the_note_stops_listing_hand_room(hand_report, bench_report):
    assert hand_report.terminal_lines()[-1] == (
        f"NOTE not checked: {len(hand_report.passed_over)} parts named like a fastener, "
        "with no drive in the solid (passed over); parts the model doesn't have"
    )
    assert "room for a hand" in bench_report.terminal_lines()[-1]
