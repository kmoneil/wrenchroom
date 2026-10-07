"""A nut's free face when both its ends are clear (issue #26).

A washer left out of the model, or a nut drawn a little off its seat, leaves
both ends clear at the 1 mm probe. The probes then reach further out from each
end in turn (2, 5, 10, 25, 50 mm), and the end with the more room is the free
face. The worked cases: an M6 nut (af 10, 5.2 tall) on an M6 bolt up through a
10 mm plate, `gap` mm above it; flipped, the same upside down.
"""

import pytest
from build123d import Box, Cylinder, Pos, Rot

from fixture_models import hex_bolt, hex_nut_shape
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.report import Verdict

NUT = {"parts": "nut", "kind": "nut", "size": "M6"}
NUT_H = 5.2


def lifted(gap, *, flip=False, ceiling=None, bolt_len=20.0):
    """The nut `gap` off a plate (top at z 0), its bolt's head under the plate.

    `ceiling`: a slab that far above the nut's top, bored for the bolt.
    """
    parts = {
        "plate": Pos(0, 0, -5) * Box(200, 200, 10) - Cylinder(3.5, 11),
        "bolt": Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(6, bolt_len, 10, 4.0),
        "nut": Pos(0, 0, gap) * hex_nut_shape(6, 10, NUT_H),
    }
    if ceiling is not None:
        bottom = gap + NUT_H + ceiling
        parts["ceiling"] = Pos(0, 0, bottom + 5) * Box(200, 200, 10) - Cylinder(3.5, 1000)
    turn = Rot(180, 0, 0) if flip else Rot(0, 0, 0)
    return Assembly([Part(name, turn * shape) for name, shape in parts.items()])


def run(assembly, engine="exact"):
    config = Config.from_dict({"fasteners": [NUT], "checks": {"detect": False}})
    (result,) = check(assembly, config, engine=engine).results
    return result


@pytest.mark.parametrize("gap", [1.5, 4.0, 8.0, 30.0])
@pytest.mark.parametrize("flip", [False, True])
def test_a_nut_off_its_seat_is_turned_from_the_end_away_from_the_plate(engine, gap, flip):
    # Issue #26: "cannot tell the nut's free face: both ends are clear".
    result = run(lifted(gap, flip=flip), engine)
    assert (result.verdict, result.tool) == (Verdict.TURNS, "spanner-10")
    up = -1.0 if flip else 1.0
    assert result.axis == pytest.approx((0, 0, up))
    assert result.seat[2] == pytest.approx(up * (gap + NUT_H))


def test_more_room_below_than_above_makes_the_bottom_the_free_face():
    # A ceiling 1.5 over the nut, the plate 30 under it: the tool comes from below.
    result = run(lifted(30.0, ceiling=1.5, bolt_len=60.0))
    assert result.axis == pytest.approx((0, 0, -1))
    assert result.seat[2] == pytest.approx(30.0)


def test_the_same_room_on_both_sides_is_not_covered_saying_so():
    result = run(lifted(3.0, ceiling=3.0))
    assert result.verdict is Verdict.NOT_COVERED
    assert (
        result.reason == "cannot tell the nut's free face: both ends are clear, with the same room"
    )


def test_open_on_both_sides_either_end_will_do():
    # 60 mm off the plate, past the furthest probe: the frame's own direction stands.
    result = run(lifted(60.0, bolt_len=100.0))
    assert (result.verdict, result.tool) == (Verdict.TURNS, "spanner-10")
    assert abs(result.axis[2]) == pytest.approx(1.0)


def test_both_ends_covered_is_still_not_covered():
    result = run(lifted(0.0, ceiling=0.0))
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == "cannot tell the nut's free face: both ends are covered"


def test_a_nut_on_its_seat_is_decided_by_the_first_probe_as_before():
    result = run(lifted(0.0))
    assert result.axis == pytest.approx((0, 0, 1))
    assert result.seat[2] == pytest.approx(NUT_H)


def test_the_furthest_probe_decides_against_the_frame_s_own_direction():
    # The plate 60 under the nut, a ceiling 30 over it: only the 50 mm probe
    # meets the ceiling, and the free face is the bottom, against the frame's +z.
    result = run(lifted(60.0, ceiling=30.0, bolt_len=100.0))
    assert result.axis == pytest.approx((0, 0, -1))
    assert result.seat[2] == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# A nut bored at its thread's minor diameter, on a bolt drawn at the nominal.
# ---------------------------------------------------------------------------

M8_MINOR = 6.647  # ISO 965-1's D1 for M8x1.25: a nut's bore as many models draw it


def minor_bored(*, flip=False):
    """An M8 nut (af 13, 6.8 tall) bored at M8's minor diameter, on a plate, and an
    M8 bolt drawn at 8 up through both: the bolt is 0.68 into the nut all round
    its bore, as a vendor's nut and bolt are."""
    parts = {
        "plate": Pos(0, 0, -5) * Box(200, 200, 10) - Cylinder(4.5, 11),
        "bolt": Pos(0, 0, -10) * Rot(180, 0, 0) * hex_bolt(8, 25, 13, 5.3),
        "nut": hex_nut_shape(M8_MINOR, 13, 6.8),
    }
    turn = Rot(180, 0, 0) if flip else Rot(0, 0, 0)
    return Assembly([Part(name, turn * shape) for name, shape in parts.items()])


def test_the_bolt_is_drawn_into_the_nut():
    # A vacuity guard: the case is the overlap.
    parts = {part.name: part.shape for part in minor_bored()}
    assert (parts["bolt"] & parts["nut"]).volume > 50


@pytest.mark.parametrize("flip", [False, True])
def test_a_nut_bored_at_its_minor_diameter_is_turned_from_its_free_end(engine, flip):
    # It used to be "cannot tell the nut's free face: both ends are covered".
    config = Config.from_dict(
        {"fasteners": [{"parts": "nut", "kind": "nut", "size": "M8"}], "checks": {"detect": False}}
    )
    (result,) = check(minor_bored(flip=flip), config, engine=engine).results
    assert (result.verdict, result.tool) == (Verdict.TURNS, "spanner-13")
    up = -1.0 if flip else 1.0
    assert result.axis == pytest.approx((0, 0, up))
    assert result.seat[2] == pytest.approx(up * 6.8)


def test_detected_the_same():
    # No rules: its hex says M8, and its bolt is found and paired.
    results = {r.fastener.name: r for r in check(minor_bored(), Config()).results}
    nut = results["nut"]
    assert (nut.fastener.size.designation, nut.verdict, nut.tool) == (
        "M8",
        Verdict.TURNS,
        "spanner-13",
    )
    assert nut.pair == "bolt"


def test_with_no_size_only_the_bore_says_where_the_thread_is():
    # Nothing tells the thread's radius: the bolt reads as covering both ends.
    config = Config.from_dict(
        {
            "fasteners": [{"parts": "nut", "kind": "nut", "across_flats": 13}],
            "checks": {"detect": False},
        }
    )
    (result,) = check(minor_bored(), config).results
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == "cannot tell the nut's free face: both ends are covered"
