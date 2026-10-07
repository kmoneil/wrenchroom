"""Combination spanners as long as makers make them, and stubbies only where sold (#49).

Spanners to 36 mm came from the prototype's ``9*af + 45``, short of every maker
and shorter the bigger the size (36 mm: 369, where Gedore's 1 B is 460), and a
short spanner swings where a real one can't. Every size now has its maker's
length, the longest of a few makers' standard series. And every size had a
stubby at 0.55 of its length, to 50 mm, where stubbies are sold to 32 mm and 1-1/4
in at most: now a size has a stubby only where one is sold, at its maker's length.
"""

import pytest
from build123d import Box, Cylinder, Pos
from click.testing import CliRunner

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.report import Verdict
from wrenchroom.tools.kits import FULL, IMPERIAL_HOME, METRIC_HOME
from wrenchroom.tools.sizes import FLATS, METRIC_FLATS, inch_mm, size_mm
from wrenchroom.tools.spanners import FULL_LENGTHS, STUBBY_LENGTHS, spanner_for

# ---------------------------------------------------------------------------
# The tables.
# ---------------------------------------------------------------------------


def test_every_spanner_size_has_a_maker_s_length():
    assert set(FULL_LENGTHS) == set(FLATS)  # none left to the formula
    assert len(FULL_LENGTHS) == 60  # a vacuity guard: 35 metric sizes, 25 inch


@pytest.mark.parametrize(
    ("af", "length"),
    [
        (13.0, 206.1),  # GearWrench 81670
        (19.0, 278.6),  # GearWrench 81676
        (23.0, 328.0),  # Hazet 600N-23
        (29.0, 393.7),  # Tekton
        (36.0, 510.5),  # Tekton
        (41.0, 612.0),  # GearWrench 81841
        (inch_mm("5/32"), 77.0),  # Facom 39 short: no full length is made
        (inch_mm("3/4"), 279.4),  # Proto J1224ASD
        (inch_mm("1-1/2"), 514.4),  # Proto J1248
    ],
)
def test_the_lengths_are_the_makers(af, length):
    assert spanner_for(af).length == length


#: Gedore 1 B's nominal lengths (shop.gedore.com, read 2026-10-07), the issue's
#: anchors and the 41 to 50 this table used to hold.
GEDORE_1B = {19.0: 258.0, 30.0: 390.0, 36.0: 460.0, 41.0: 520.0, 46.0: 550.0, 50.0: 580.0}


def test_no_length_is_shorter_than_gedore_s():
    for af, length in GEDORE_1B.items():
        assert spanner_for(af).length >= length, af


def test_every_metric_length_is_longer_than_the_formula_was():
    # The formula erred short at every metric size; the shortfall grew with size.
    for af in METRIC_FLATS:
        assert spanner_for(af).length > 9 * af + 45, af
    assert spanner_for(36.0).length - (9 * 36 + 45) > 100


#: ISO 7738:2015 Table 1, the least a medium-series combination spanner is long, mm
#: (read 2026-10-07 in the standard's preview): a full-length spanner is no shorter.
ISO_7738_MEDIUM_MIN = {
    10.0: 110,
    13.0: 135,
    19.0: 185,
    24.0: 230,
    30.0: 285,
    36.0: 335,
    41.0: 380,
    46.0: 425,
    50.0: 460,
}

#: The same table's most a short-series spanner is long: a stubby is no longer.
ISO_7738_SHORT_MAX = {10.0: 109, 13.0: 134, 19.0: 184}


def test_the_lengths_sit_in_iso_7738_s_series():
    for af, least in ISO_7738_MEDIUM_MIN.items():
        assert spanner_for(af).length >= least, af
    for af, most in ISO_7738_SHORT_MAX.items():
        assert spanner_for(af).stubby_length <= most, af


def test_stubbies_are_only_the_sizes_sold():
    metric = sorted(af for af in STUBBY_LENGTHS if af in METRIC_FLATS)
    assert metric == [float(af) for af in range(6, 33)]  # 6 to 32 mm
    inch = sorted(af for af in STUBBY_LENGTHS if af not in METRIC_FLATS)
    assert inch[0] == inch_mm("1/4")
    assert inch[-1] == inch_mm("1-1/4")
    assert set(STUBBY_LENGTHS) <= set(FLATS)
    for af in (5.5, 33.0, 36.0, 41.0, 50.0, inch_mm("7/32"), inch_mm("1-5/16")):
        assert spanner_for(af).stubby_length is None, af


def test_every_stubby_is_shorter_than_its_full_length():
    for af, stubby in STUBBY_LENGTHS.items():
        assert stubby < spanner_for(af).length, af


def test_a_size_no_maker_publishes_keeps_the_formula_and_no_stubby():
    odd = spanner_for(12.5)
    assert (odd.length, odd.stubby_length) == (9 * 12.5 + 45, None)


# ---------------------------------------------------------------------------
# The kits.
# ---------------------------------------------------------------------------


def _stubbies(kit):
    return [size for size in kit.spanners if spanner_for(size_mm(size)).stubby_length]


def test_the_home_kits_have_stubbies_to_19_mm_and_3_4_in_and_full_to_32_and_1_1_4():
    assert max(size_mm(s) for s in _stubbies(METRIC_HOME)) == 19.0
    assert min(size_mm(s) for s in _stubbies(METRIC_HOME)) == 6.0  # none for 5.5
    assert max(size_mm(s) for s in _stubbies(IMPERIAL_HOME)) == inch_mm("3/4")
    full = [size_mm(s) for s in _stubbies(FULL)]
    assert max(s for s in full if s in METRIC_FLATS) == 32.0
    assert max(s for s in full if s not in METRIC_FLATS) == inch_mm("1-1/4")


def test_the_tools_command_lists_each_length_and_says_where_there_is_no_stubby():
    output = CliRunner().invoke(main, ["tools", "--kit", "full"]).output
    rows = {line.split()[0]: line for line in output.splitlines() if "spanner-" in line}
    assert "length 278.6" in rows["spanner-19"]
    assert rows["spanner-19"].endswith("stubby 138.1")
    assert rows["spanner-36"].endswith("no stubby")
    assert rows["spanner-5.5"].endswith("no stubby")


# ---------------------------------------------------------------------------
# In the check: a wall round the fastener, where the length decides.
# ---------------------------------------------------------------------------


def walled(fastener, inner, height=30.0):
    """The fastener on a plate, a round wall ``inner`` from its axis."""
    wall = Pos(0, 0, height / 2) * (Cylinder(inner + 10, height) - Cylinder(inner, height + 1))
    return Assembly(
        [
            Part("plate", Pos(0, 0, -5) * Box(1000, 1000, 10)),
            Part("fastener", fastener),
            Part("wall", wall),
        ]
    )


NUT = {"parts": "fastener", "kind": "nut", "size": "M8"}


def run(assembly, rule, engine="mesh"):
    config = Config.from_dict({"fasteners": [rule], "checks": {"detect": False}})
    (result,) = check(assembly, config, kit="full", engine=engine).results
    return result


@pytest.mark.parametrize(
    ("inner", "how"),
    [
        (
            155.0,
            "ring, stubby",
        ),  # the full handle (reach 175.2) meets it; the formula's 137.7 didn't
        (185.0, "ring, full length"),
    ],
)
def test_a_13_mm_spanner_turns_as_far_as_it_really_reaches(engine, inner, how):
    nut = hex_prism(13, 6.8) - Cylinder(4, 30)
    result = run(walled(nut, inner), NUT, engine)
    assert (result.verdict, result.tool, result.how) == (Verdict.TURNS, "spanner-13", how)


@pytest.mark.parametrize(
    ("af", "verdict", "ways"),
    [
        (32.0, Verdict.TURNS, ["ring, full length", "ring, stubby"]),
        (33.0, Verdict.BLOCKED, ["ring, full length", "open end, full length"]),
    ],
)
def test_past_32_mm_there_is_no_stubby_to_fall_back_on(af, verdict, ways):
    # A gland in a wall 300 off: the full length meets it (32: 441, reach 375; 33:
    # 475, reach 404); 32's stubby (221, reach 188) turns it, and 33 has none.
    gland = hex_prism(af, 10) + Pos(0, 0, 15) * Cylinder(af / 2 - 1, 10)
    rule = {"parts": "fastener", "kind": "nut", "socket": False, "across_flats": af}
    result = run(walled(gland, 300.0, 60.0), rule)
    assert result.verdict is verdict
    assert [a.way for a in result.attempts] == ways
