"""The bench with hand room on (spec 6.4), which it isn't by default.

Hand room only ever takes a pass away, or moves it to another tool, and says why.
On the bench it takes one: hand_tight's nut, the cell built for it (cells.py
works it by hand). And it moves one: nut_stubby_box's nut, whose stubby (Tekton's
101.6) puts the hand on its handle against the box, so the socket on a 50 mm
extension turns it instead.

Until the spanners took makers' lengths (issue #49), the prototype's formula made
them short, and put the hand where a real hand would not be: starting inside the
block beside pair_nut_held's nut (whose pass it took) and pair_both_hold's
pockets (whose bolt's and nut's reason it changed). With real lengths the hand
holds the handle's outer end, clear of them: those come out as with hand room
off.

One blocked either way says why differently: post_ring's nut, whose spanner gets
15 of the 30 deg it needs between two posts, and whose hand meets the roof over
it all along that arc. The reason names the roof alone: what stopped the hand
where the tool did best, not everything any hand touched round the sweep (issue
#52). Every other field of every fastener comes out as with hand room off, on
both engines.
"""

import pytest
from bench import check_bench

#: The passes hand room takes on the bench, and the reason each gives.
CHANGES = {
    "hand_tight_nut": "no room for a hand: the hand hits hand_tight_block on its best arc",
}

#: The passes hand room moves to another tool: (tool, how) with the hand.
MOVES = {
    "nut_stubby_box_nut": ("socket-10", "socket, 50 mm extension"),
}

#: The hand the formula's short spanners misplaced (issue #49): now as without it.
CLEARED = ("pair_nut_held_nut", "pair_both_hold_bolt", "pair_both_hold_nut")

#: Fasteners blocked either way whose reason hand room changes.
REASONS = {"post_ring_nut": "no room for a hand: the hand hits post_ring_roof on its best arc"}


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
    assert changed == set(CHANGES) | set(MOVES)
    for name, reason in CHANGES.items():
        assert bench_json[name]["verdict"] in {"turns", "held"}, name  # a pass, taken
        assert hand[name].verdict.value == "blocked", name
        assert hand[name].reason == reason, name
    for name, (tool, how) in MOVES.items():
        assert bench_json[name]["verdict"] == hand[name].verdict.value == "turns", name
        assert (hand[name].tool, hand[name].how) == (tool, how), name


def test_a_hand_stopped_says_what_stopped_it_where_the_tool_did_best(hand_report, bench_json):
    hand = {r.fastener.name: r for r in hand_report.results}
    for name, reason in REASONS.items():
        assert bench_json[name]["verdict"] == hand[name].verdict.value == "blocked", name
        assert bench_json[name]["reason"].startswith("only holds"), name
        assert hand[name].reason == reason, name
        assert len(hand[name].blockers) > 5  # a vacuity guard: the hand hit every post too


def test_a_real_length_s_hand_holds_the_handle_s_end(hand_report, bench_json):
    hand = {r.fastener.name: r for r in hand_report.results}
    for name in CLEARED:
        entry = bench_json[name]
        assert (hand[name].verdict.value, hand[name].reason) == (
            entry["verdict"],
            entry["reason"],
        ), name


def test_everything_else_is_the_same_report(hand_report, bench_json):
    document = hand_report.to_json_dict()
    assert document["hand_room"] is True
    for entry in document["fasteners"]:
        name = entry["name"]
        if name not in CHANGES and name not in MOVES and name not in REASONS:
            assert entry == bench_json[name], name


def test_the_note_stops_listing_hand_room(hand_report, bench_report):
    motion = sum(part.motion for part in hand_report.passed_over)
    named = sum(part.named for part in hand_report.passed_over) - motion
    alike = len(hand_report.passed_over) - named - motion
    assert alike == 3  # a vacuity guard: std's part7, part8 and part9 (issue #95)
    assert motion == 1  # misnamed's leadscrew nut (issue #117)
    assert hand_report.surfaces == ("shelled_decal",)  # issue #104
    assert hand_report.terminal_lines()[-1] == (
        f"NOTE not checked: {named} parts named like a fastener, "
        "with no drive or bore in the solid (passed over); 1 part named for a leadscrew "
        f"or a ball screw, which no tool turns (passed over); {alike} parts shaped like "
        "fasteners, not named as any (passed over); 1 part drawn as a surface, not a "
        "solid (left out); parts the model doesn't have"
    )
    assert "room for a hand" in bench_report.terminal_lines()[-1]
