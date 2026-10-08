"""Fasteners from part names (spec 7.1): every evidence family, and the traps.

The bench's own part names are read in tests/golden/test_names_bench.py.
"""

import numpy as np
import pytest

from wrenchroom.detect.names import MCMASTER, STANDARDS, NameHint, read_name
from wrenchroom.fasteners import Head, Kind

S, N = Kind.SCREW, Kind.NUT
TIMES = chr(0xD7)


def hint(name):
    found = read_name(name)
    assert found is not None, f"{name!r} should read as a fastener"
    return found


# ---------------------------------------------------------------------------
# Standards and catalogue numbers.
# ---------------------------------------------------------------------------


def _standard_cases():
    for label, (kind, head, reason) in sorted(STANDARDS.items()):
        body, number = label.split()
        for spelling in (f"{body} {number}", f"{body}{number}", f"{body.lower()}_{number}"):
            yield pytest.param(f"{spelling} M6x20", kind, head, reason, id=f"{spelling}")
        if body == "ISO":
            yield pytest.param(
                f"DIN EN ISO {number} M6x20", kind, head, reason, id=f"DIN EN {label}"
            )


@pytest.mark.parametrize(("name", "kind", "head", "reason"), list(_standard_cases()))
def test_every_standard_reads_in_every_spelling(name, kind, head, reason):
    found = read_name(name)
    if kind is None:
        assert found is None  # a washer is not a fastener (spec 4)
        return
    assert found is not None
    assert (found.kind, found.head, found.not_covered) == (kind, head, reason)
    assert found.size.designation == "M6"
    assert found.length_mm == 20
    assert found.basis.startswith(("ISO ", "DIN "))


def test_a_standard_part_suffix_is_read_as_the_standard():
    assert hint("ISO 7380-1 M5x10").head is Head.BUTTON
    assert hint("ISO 7046-1 M4x10").head is Head.PHILLIPS


def test_an_unknown_standard_falls_back_to_the_words():
    assert hint("ISO 9999 hex bolt M8").head is Head.HEX
    assert read_name("ISO 9999 M8") is None


@pytest.mark.parametrize(("series", "expected"), sorted(MCMASTER.items()))
def test_every_mcmaster_series_reads_without_a_size(series, expected):
    found = hint(f"{series}115")
    assert (found.kind, found.head) == expected
    assert found.size is None  # the number after the letter is catalogue-only
    assert found.basis == f"McMaster {series}"


def test_mcmaster_numbers_are_whole_tokens():
    assert read_name("99999A115") is None  # an unknown series says nothing
    assert read_name("X91290A115Y") is None
    assert hint("bracket 91290A115 (2)").kind is S


# ---------------------------------------------------------------------------
# Descriptions and nouns.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind", "head"),
    [
        ("M6x20 SHCS", S, Head.SOCKET),
        ("BHCS M4x10", S, Head.BUTTON),
        ("FHCS_M5x16", S, Head.FLAT),
        ("Socket Head Cap Screw M6 x 20mm", S, Head.SOCKET),
        ("Screw-Socket-Head-M6x20", S, Head.SOCKET),
        ("button head screw", S, Head.BUTTON),
        ("countersunk screw M5", S, Head.FLAT),
        ("hex bolt M10x40", S, Head.HEX),
        ("hexagon head bolt", S, Head.HEX),
        ("pan head phillips screw M4x12", S, Head.PHILLIPS),
        ("flat head torx screw", S, Head.TORX),
        ("slotted cheese head screw", S, Head.SLOTTED),
        ("carriage bolt M8x50", S, Head.CARRIAGE),
        ("hex nut M8", N, None),
        ("nyloc M6", N, None),
        ("Nylock_M8", N, None),
        ("flange nut", N, None),
        ("locknut", N, None),
        ("lift_link_0_bolt_bot", S, None),
        ("hexNut_M8", N, None),
        ("mainFrameBolt", S, None),
        ("Bolt:1", S, None),
        ("Screw (3)", S, None),
        ("SHCS-M6x20<1>", S, Head.SOCKET),
        ("key_wall_near_screw#2", S, None),
    ],
)
def test_descriptions_and_nouns(name, kind, head):
    found = hint(name)
    assert (found.kind, found.head, found.not_covered) == (kind, head, None)


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("set screw M4x6", "set screw"),
        ("grub screw M5", "set screw"),
        ("setscrew_m3", "set screw"),
        ("DIN 913 M6x10", "set screw"),
        ("DIN 7984 M6x16", "low-head"),
        ("wing nut M6", "by hand"),
        ("thumb screw M4", "by hand"),
        ("knurled nut M3", "by hand"),
        ("ISO 4762 M1.2x3", "M1.2 is outside the sizes the tables hold (M1.6 to M24)"),
        ("hex bolt M30x100", "M30 is outside"),
        ("SHCS #5-40 x 1/4", "#5 is outside the sizes the tables hold (#0 to 3/4)"),
    ],
)
def test_a_fastener_the_kit_cannot_check_says_why(name, reason):
    assert reason in hint(name).not_covered


@pytest.mark.parametrize(
    "name",
    [
        "nutmeg",
        "screwdriver",
        "socket_wrench",
        "hex_key",
        "end_cap",
        "washer M6",
        "DIN 125 M6",
        "ISO 7089 M8",
        "standoff_m3",
        "spacer M4x10",
        "pair_both_hold_pocket_low",
        "",
        "   ",
        "#",
        "M",
        "ISO",
        "M6",
    ],
)
def test_things_that_are_not_fasteners(name):
    assert read_name(name) is None


@pytest.mark.parametrize(
    ("name", "kind", "noun"),
    [
        # A fastener noun with ordinary words after it: a cover, a boss, a plate,
        # a hole circle, a pocket block, or a gland after all. Only the solid can
        # say, so each is a candidate, never a fastener by its name alone (#30).
        ("bolt_hole_cover", S, "bolt"),
        ("screw_boss", S, "screw"),
        ("nut_plate", N, "nut"),
        ("bolt_circle", S, "bolt"),
        ("pair_nut_held_upper", N, "nut"),
        ("nut_stubby_box_box", N, "nut"),
        ("box_gland_vent", N, "gland"),
        ("box_gland_base", N, "gland"),
        ("box_gland_cable_front", N, "gland"),
        ("panel_screw_long", S, "screw"),
        ("torx_lid_screw_long", S, "screw"),
        ("bolt_nut_plate", N, "nut"),  # the last fastener noun before the words
    ],
)
def test_a_noun_with_words_after_it_is_a_candidate(name, kind, noun):
    found = hint(name)
    assert (found.kind, found.needs_drive) == (kind, True)
    assert found.basis.startswith(f"noun {noun!r}, words after it")


def test_a_candidate_keeps_what_its_name_says():
    gland = hint("box_gland_vent")
    assert not gland.socket_allowed  # a gland still takes no socket
    assert gland.size is None
    torx = hint("torx_lid_screw_long M6x20")
    assert (torx.head, torx.size.designation) == (Head.TORX, "M6")
    assert torx.basis == "noun 'screw', words after it, drive 'torx', M6x20"
    set_screw = hint("screw_set_box")
    assert "set screw" in set_screw.not_covered  # a set screw holder, or a set screw


@pytest.mark.parametrize(
    "name",
    ["frame_bolt", "box_gland_front_L", "frame_bolt_upper", "lift_link_0_bolt_bot", "hex nut M8"],
)
def test_a_noun_followed_only_by_labels_is_a_fastener_outright(name):
    assert not hint(name).needs_drive


def test_a_head_word_away_from_the_noun_says_nothing():
    # The words describing the bolt are the ones touching it; elsewhere they
    # describe something else (a cross member, a flat plate, a side wall).
    for name in ("cross_member_bolt", "flat_plate_screw", "hex_side_wall_bolt", "socket_tail_bolt"):
        assert hint(name).head is None, name


#: Every head word but the drive words, each of which names something else too.
NOT_DRIVES = [
    "shcs", "socket", "allen", "cap", "bhcs", "button", "fhcs", "countersunk", "csk",
    "flat", "hex", "hexagon", "cross", "ph", "slotted", "carriage", "coach",
]  # fmt: skip


@pytest.mark.parametrize("word", NOT_DRIVES)
def test_no_other_head_word_is_read_away_from_the_noun(word):
    # A button panel's screw, a ph sensor's, a slotted plate's: not their heads.
    found = hint(f"{word}_panel_screw")
    assert found.head is None, word
    assert found.basis == "noun 'screw'"


@pytest.mark.parametrize(
    ("name", "kind", "head", "basis"),
    [
        # Issue #19: a drive word anywhere in the name says the head.
        ("torx_lid_screw", S, Head.TORX, "noun 'screw', drive 'torx'"),
        ("hexalobular_cover_screw", S, Head.TORX, "noun 'screw', drive 'hexalobular'"),
        ("phillips_panel_screw", S, Head.PHILLIPS, "noun 'screw', drive 'phillips'"),
        ("pozidriv_hinge_bolt", S, Head.PHILLIPS, "noun 'bolt', drive 'pozidriv'"),
        ("pozi_hinge_screw", S, Head.PHILLIPS, "noun 'screw', drive 'pozi'"),
        ("Torx-Lid-Screw-M6x20", S, Head.TORX, "noun 'screw', drive 'torx', M6x20"),
        ("torxLidScrew", S, Head.TORX, "noun 'screw', drive 'torx'"),
        ("lid_screw_2_torx", S, Head.TORX, "noun 'screw', drive 'torx'"),  # past a label
        # A drive beats a head shape wherever it sits: a button-head Torx screw.
        ("torx_lid_button_screw", S, Head.TORX, "noun 'screw', drive 'torx'"),
        # Touching the noun, the run says it already, and the basis stays as it was.
        ("lid_torx_screw", S, Head.TORX, "noun 'screw'"),
        ("lid_button_screw", S, Head.BUTTON, "noun 'screw'"),
        # A standard's head stands; a nut has no head to say.
        ("ISO 4762 torx_lid M6x20", S, Head.SOCKET, "ISO 4762, M6x20"),
        ("torx_lid_nut", N, None, "noun 'nut'"),
    ],
)
def test_a_drive_word_says_the_head_wherever_it_sits(name, kind, head, basis):
    found = hint(name)
    assert (found.kind, found.head, found.basis) == (kind, head, basis)


def test_a_carriage_word_touching_the_noun_still_reads_as_carriage():
    # The limit of reading names: a printer's x_carriage_bolt looks exactly like
    # a carriage bolt. The check must not let a name alone make a fastener
    # self-holding; geometry has to show the square neck (detection wiring).
    assert hint("x_carriage_bolt").head is Head.CARRIAGE


def test_a_gland_takes_no_socket_and_no_size_from_its_thread():
    found = hint("cable_gland_M20")
    assert found.kind is N
    assert not found.socket_allowed
    assert found.size is None  # an M20 gland's hex is not an M20 nut's


# ---------------------------------------------------------------------------
# Sizes and lengths.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "size", "length"),
    [
        ("bolt M6", "M6", None),
        ("bolt M6x20", "M6", 20),
        ("bolt M6 x 20mm", "M6", 20),
        ("bolt M6 X 20", "M6", 20),
        (f"bolt M6{TIMES}20", "M6", 20),
        ("bolt M6*20", "M6", 20),
        ("bolt M6x1x20", "M6", 20),
        ("bolt M6x1.0x20", "M6", 20),
        ("bolt M10x1.25x30", "M10", 30),
        ("nut M8x1", "M8", None),
        ("nut M10x1.25", "M10", None),
        ("bolt M3x3", "M3", 3),
        ("bolt M3.5x10", "M3.5", 10),
        ("bolt M3,5x10", "M3.5", 10),
        ("bolt m8x25", "M8", 25),
        ("SHCS 1/4-20 x 3/4", "1/4", 19.05),
        ('BHCS #10-32 x 1/2"', "#10", 12.7),
        ("SHCS #4-40 x 1/4", "#4", 6.35),
        ("bolt 5/16-18 x 1-1/2", "5/16", 38.1),
        ("bolt 3/8-16 x 1.5", "3/8", 38.1),
        ("screw #6", "#6", None),
    ],
)
def test_sizes_and_lengths(name, size, length):
    found = hint(name)
    assert found.size.designation == size
    assert found.length_mm == (pytest.approx(length) if length else None)


def test_a_bare_fraction_is_not_a_size():
    # "1/2" alone could be anything; an imperial size needs its pitch or a #.
    assert hint("bolt 1/2").size is None


# ---------------------------------------------------------------------------
# Properties.
# ---------------------------------------------------------------------------

SAMPLES = [
    "ISO 4762 M6x20",
    "hex nut M8",
    "lift_link_0_bolt_bot",
    "91290A115",
    "carriage bolt M8x50",
    "cable_gland_M20",
    "set screw M4x6",
]


@pytest.mark.parametrize("suffix", ["#2", "<3>", " (1)", ":1", " (2)#3"])
@pytest.mark.parametrize("name", SAMPLES)
def test_instance_markers_change_nothing(name, suffix):
    assert read_name(name + suffix) == read_name(name)


def test_any_string_is_answered_and_never_raises():
    rng = np.random.default_rng(912)
    odd = [TIMES, chr(0x1B), chr(0x202E), chr(0xE9), chr(0x87BA), "\n", "\t"]
    alphabet = [*"abcxyzMSHCnutbolscrew0123456789 _-.#/:()<>xX*", *odd]
    for _ in range(3000):
        name = "".join(rng.choice(alphabet, size=int(rng.integers(0, 30))))
        found = read_name(name)
        assert found is None or isinstance(found, NameHint)
        assert read_name(name) == found  # and the same answer every time


def test_every_table_key_is_spelled_as_the_reader_spells_it():
    for label in STANDARDS:
        body, number = label.split()
        assert body in {"ISO", "DIN"}
        assert number.isdigit()
    for series in MCMASTER:
        assert series[:-1].isdigit()
        assert series.endswith("A")
