"""A screw named one size whose shank sits on no size is sized by its recess (issue #135).

#117 notes a screw whose name gives one size and whose solid is drawn as another,
where the solid's own size is plain: a hex drive's, or a shank drawn at a size. A
shank drawn 2.9 sits on neither M3's 3.0 nor #4's 2.845, and a Phillips, Torx or
slotted head has no hex to settle one, so a screw drawn as an M3 and named M5 kept
its name's size silently. Now, where the shank is no thread of the name's size:

- a Torx or cross recess's standard sizes it, where that leaves one size the shank
  could be the thread of, the name's own system first: taken as drawn, and noted;
- else nothing in the solid picks a size: the name's is kept, and the shank's
  disagreeing with it is said.
"""

import math

import pytest
from build123d import Box, Circle, Cylinder, Pos, RegularPolygon, extrude

from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.detect import find
from wrenchroom.fasteners import Size


def at(radius, degrees):
    a = math.radians(degrees)
    return Pos(radius * math.cos(a), radius * math.sin(a))


def cross(span):
    """A cross ``span`` across its wings, 0.6 wide, sunk 1.4 into a 2.4 head."""
    return Pos(0, 0, 1.7) * (Box(span, 0.6, 1.41) + Box(0.6, span, 1.41))


def torx(a):
    """ISO 10664's hexalobular recess, ``a`` point to point, sunk 1.4: lobes 0.1 A."""
    lobe, flute = 0.1 * a, 0.17 * a
    profile = Circle(a / 2 - lobe)
    for k in range(6):
        profile += at(a / 2 - lobe, 60 * k) * Circle(lobe)
    for k in range(6):
        profile -= at(0.37 * a + flute, 60 * k + 30) * Circle(flute)
    return Pos(0, 0, 1.0) * extrude(profile, 1.41)


def slot(width):
    """A slot ``width`` wide right across a 5.6 head, 1 deep."""
    return Pos(0, 0, 1.9) * Box(6, width, 1.01)


def hex_head(af):
    """A hex head ``af`` across flats, 2 high, no recess: its drive the hex."""
    return extrude(RegularPolygon(af / math.sqrt(3), 6), 2.0)


def screw(recess=None, shank=2.9, head=None):
    """A pan head 5.6 by 2.4, ``recess`` cut in its top, on a shank ``shank`` across."""
    top = head if head is not None else Pos(0, 0, 1.2) * Cylinder(2.8, 2.4)
    if recess is not None:
        top -= recess
    return top + Pos(0, 0, -3) * Cylinder(shank / 2, 6)


def found(name, shape):
    (fastener,) = find([Part(name, shape)]).fasteners
    return fastener


def drawn_as(solid, shown, named):
    return f"drawn as {solid} ({shown}), where its name says {named}: taken as drawn"


def kept(shank, named, could):
    return f"drawn with a {shank} shank, no {named}'s thread{could}: the name's {named} kept"


# ---------------------------------------------------------------------------
# Sized by its recess.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "named"),
    [
        ("M5x6 pan head phillips screw", "M5"),
        ("M2x6 pan head phillips screw", "M2"),
        ("#1 x 3/16 pan head phillips screw", "#1"),
    ],
)
def test_the_issue_s_phillips_screw_is_an_m3_by_its_cross_and_shank(name, named):
    # PH1 is an M2.5's, an M3's, a #2's to #4's; a 2.9 shank is only an M3's thread.
    fastener = found(name, screw(cross(3.2)))
    assert fastener.size == Size("M3", 3.0)
    assert fastener.notes == (drawn_as("an M3", "2.90 shank, a PH1 cross", named),)
    assert fastener.confidence == "low"
    assert fastener.basis.endswith(f"M3 measured (the name says {named})")


def test_one_named_for_its_own_size_is_quiet():
    fastener = found("M3x6 pan head phillips screw", screw(cross(3.2)))
    assert (fastener.size, fastener.notes) == (Size("M3", 3.0), ())
    assert "measured" not in fastener.basis


def issue_model():
    """The issue's four names on one M3 pan head Phillips, each through its plate."""
    names = [
        "M2x6 pan head phillips screw",
        "M5x6 pan head phillips screw",
        "#1 x 3/16 pan head phillips screw",
        "M3x6 pan head phillips screw",
    ]
    parts = []
    for i, name in enumerate(names):
        plate = Pos(0, 0, -5) * Box(30, 30, 10) - Cylinder(1.45, 30)
        parts += [Part(f"plate {i}", Pos(i * 100, 0, 0) * plate)]
        parts += [Part(name, Pos(i * 100, 0, 0) * screw(cross(3.2)))]
    return Assembly(parts)


def test_the_issue_s_model_lists_four_m3s_and_one_note_each():
    report = check(issue_model(), kit="metric-home")
    lines = report.terminal_lines()
    assert "  M3 phillips screw        driver-ph1     x4    all pass (driver straight in)" in lines
    notes = [line for line in lines if line.startswith("NOTE ") and "phillips" in line]
    assert notes == [
        f"NOTE {name} pan head phillips screw: {drawn_as('an M3', '2.90 shank, a PH1 cross', n)}"
        for name, n in (("#1 x 3/16", "#1"), ("M2x6", "M2"), ("M5x6", "M5"))
    ]  # the cross's own note, drawn for PH1 where the name's size takes another, is gone
    assert report.exit_code == 0


def test_a_torx_recess_sizes_it_by_its_standard():
    # ISO 14583's T10 is an M3's alone.
    fastener = found("M5x6 torx pan head screw", screw(torx(2.80)))
    assert fastener.size == Size("M3", 3.0)
    assert fastener.notes == (drawn_as("an M3", "2.90 shank, a T10 recess", "M5"),)
    report = check(Assembly([Part("M5x6 torx pan head screw", screw(torx(2.80)))]), kit="full")
    assert report.results[0].tool == "torx-key-T10"


@pytest.mark.parametrize(
    ("name", "drawn"),
    [
        ("#1 x 3/16 pan head phillips screw", "a #4"),
        ("M5x6 pan head phillips screw", "an M3"),
        ("M2x6 pan head phillips screw", "an M3"),
    ],
)
def test_the_name_s_own_system_comes_first(name, drawn):
    # A 2.7 shank, on no size, could be an M3's thread (2.39 to 3) or a #4's (2.07 to
    # 2.845), both PH1: an inch name takes the #4, a metric one the M3.
    fastener = found(name, screw(cross(3.2), shank=2.7))
    assert fastener.size.designation == drawn.split()[1]
    named = name.split("x")[0].strip() if name.startswith("M") else "#1"
    assert fastener.notes == (drawn_as(drawn, "2.70 shank, a PH1 cross", named),)


# ---------------------------------------------------------------------------
# Kept, and said.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "recess",
    [slot(0.8), None],
    ids=["slotted", "plain"],
)
def test_a_head_that_says_no_size_keeps_the_name_s_and_says_so(recess):
    # A 2.9 shank is an M3's thread or an M3.5's (2.71 to 3.5): nothing says which.
    fastener = found("M5x6 pan head screw", screw(recess))
    assert fastener.size == Size("M5", 5.0)
    assert fastener.notes[-1] == kept("2.90", "M5", " (an M3's or an M3.5's)")
    assert fastener.confidence == "low"
    assert "measured" not in fastener.basis


def test_a_recess_two_sizes_take_keeps_the_name_s():
    # PH2 is an M3.5's, an M4's and an M5's; a 3.3 shank an M3.5's thread or an M4's.
    fastener = found("M5x6 pan head phillips screw", screw(cross(4.4), shank=3.3))
    assert fastener.size == Size("M5", 5.0)
    assert fastener.notes == (kept("3.30", "M5", " (an M3.5's or an M4's)"),)


def test_a_recess_no_size_it_takes_fits_keeps_the_name_s():
    # T20 is an M4's, and a 2.9 shank no M4's thread (3.14 to 4): the recess still
    # picks the key, the shank's sizes are said.
    fastener = found("M5x6 torx pan head screw", screw(torx(3.92)))
    assert fastener.size == Size("M5", 5.0)
    assert fastener.notes == (kept("2.90", "M5", " (an M3's or an M3.5's)"),)
    report = check(Assembly([Part("M5x6 torx pan head screw", screw(torx(3.92)))]), kit="full")
    assert report.results[0].tool == "torx-key-T20"


def test_a_shank_no_thread_could_be_says_none():
    # 1.0: under M1.6's minor (1.17) and #0's (1.13).
    fastener = found("M5x6 slotted pan head screw", screw(slot(0.8), shank=1.0))
    assert fastener.notes[-1] == kept("1.00", "M5", "")


def test_a_hex_that_settles_no_size_says_nothing_as_before():
    # A 7.3 hex is no standard's (M4's 7 to M5's least, 7.78), so it settles nothing,
    # and a name outranks it (#117): the shank on no size isn't weighed against it.
    fastener = found("M5x6 hex head screw", screw(head=hex_head(7.3)))
    assert (fastener.size, fastener.notes) == (Size("M5", 5.0), ())


@pytest.mark.parametrize(
    ("shank", "said"),
    [
        (3.10, None),  # 0.1 past M3's 3: drawn loose, the name's
        (3.15, None),
        (3.20, " (an M3.5's or an M4's)"),  # 0.2 past: no M3's, loosely or not
    ],
)
def test_a_shank_drawn_loose_past_the_name_s_nominal_is_the_name_s(shank, said):
    fastener = found("M3x6 slotted pan head screw", screw(slot(0.8), shank=shank))
    assert fastener.size == Size("M3", 3.0)
    assert fastener.notes == (() if said is None else (kept(f"{shank:.2f}", "M3", said),))


def test_only_the_name_s_size_is_given_a_shank_drawn_loose():
    # T10 is an M3's, but a 3.1 shank is past M3's thread: the loose allowance is the
    # name's M5's alone, which a 3.1 shank is no thread of either. No size is picked.
    fastener = found("M5x6 torx pan head screw", screw(torx(2.80), shank=3.1))
    assert fastener.notes == (kept("3.10", "M5", " (an M3.5's or an M4's)"),)


# ---------------------------------------------------------------------------
# Quiet: a thread of the name's size.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("shank", "name"),
    [
        (4.13, "M5x6 slotted pan head screw"),  # M5's minor, 4.134
        (5.04, "M5x6 slotted pan head screw"),  # at M5's nominal, within the snap
        (2.9, "M3x6 slotted pan head screw"),
        (2.9, "M3x6 torx pan head screw"),
    ],
)
def test_a_shank_its_name_s_thread_could_be_is_quiet(shank, name):
    recess = torx(2.80) if "torx" in name else slot(0.8)
    fastener = found(name, screw(recess, shank=shank))
    assert fastener.notes == ()
    assert fastener.size.designation == name[:2]


def test_a_nut_is_left_to_its_hex():
    # A nut's bore on no size: its hex settles it (#117), so nothing new is said.
    nut = extrude(RegularPolygon(8 / math.sqrt(3), 6), 4.0) - Cylinder(1.45, 10)
    fastener = found("M5 nut", nut)
    assert (fastener.size, fastener.notes) == (Size("M5", 5.0), ())
