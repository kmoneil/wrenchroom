"""A hex drawn a little small takes its own thread's spanner, saying so (issue #50).

An M8 nut drawn 12.6 across flats is under ISO 4032's band (12.73 to 13), and
inside the band below 1/2 in that a 5/16 nut has (12.42 to 12.70). On an M8 bolt
it came out a 5/16 nut with a 1/2 in spanner; and where a hex fitted no tool,
the reason named the nearest one, which could be too small to go over it (an M6
nut at 9.6 was offered a 3/8 in spanner, 9.525). Now:

- a known thread keeps to its own system's tools: a hex up to UNDERSIZE_MM
  under its standard's band takes that size, and the result notes it; a hex
  that is exactly a size of the other system, and no size of its own, takes
  that, noted too;
- in detection, a bore that says M8 is not outranked by a band, and a size from
  a band alone is a guess, which a name or the nut's bolt outranks; a nut with
  no size takes its bolt's;
- a hex no tool takes names the one that fits nearest: the smallest spanner
  over it, the largest key into it, from the thread's own system first.
"""

import json
import re
from dataclasses import replace

import pytest
import yaml
from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import UNDERSIZE_MM, NotCovered, _resolve_af, _sized_by_partners, check
from wrenchroom.config import Config
from wrenchroom.detect.geometry import read_shape
from wrenchroom.detect.sidecar import sidecar_text
from wrenchroom.fasteners import HEX_AF_MIN, Fastener, Kind, Size, standard_hex_afs
from wrenchroom.report import PASSED_OVER_SHOWN, FastenerResult, Report, Verdict
from wrenchroom.tools.hex_keys import HEX_KEYS
from wrenchroom.tools.sizes import FLATS, inch_mm, is_inch, size_mm, size_name

KEYS = tuple(HEX_KEYS)


def nut_on_plate(af, bore=4.0):
    """A nut of `af` across flats, 6.8 tall, on a plate: room all round."""
    return Assembly(
        [
            Part("nut", hex_prism(af, 6.8) - Cylinder(bore, 30)),
            Part("plate", Pos(0, 0, -5) * Box(200, 200, 10)),
        ]
    )


def joint(nut_af, bore, *, bolt_af=13.0, shank=None, names=("bolt", "nut"), at=0.0):
    """A bolt up through a plate, its head below, and a nut on it: room all round.

    ``shank`` is the bolt's diameter, the nut's ``bore`` unless given; the bolt's
    head, ``bolt_af`` across flats, is what tells detection its size.
    """
    shank = bore if shank is None else shank
    bolt_name, nut_name = names
    plate = Pos(at, 0, -3) * (Box(80, 80, 6) - Cylinder(shank / 2 + 0.5, 6))
    bolt = Pos(at, 0, 4) * Cylinder(shank / 2, 20) + Pos(at, 0, -11.2) * hex_prism(bolt_af, 5.2)
    nut = Pos(at, 0, 0) * (hex_prism(nut_af, 6.4) - Cylinder(bore / 2, 30))
    return [Part(f"{nut_name}_plate", plate), Part(bolt_name, bolt), Part(nut_name, nut)]


def run(assembly, rules=(), kit="full", engine="mesh"):
    config = Config.from_dict({"fasteners": list(rules)} if rules else {})
    return check(assembly, config, kit=kit, engine=engine)


def by_name(report):
    return {result.fastener.name: result for result in report.results}


def undersize(af, size, tool):
    """The note an undersize hex's result carries."""
    least = min(HEX_AF_MIN.get(s, s) for s in standard_hex_afs(Size.parse(size)) if s >= af)
    return (
        f"hex drawn undersize: {af:.2f} across flats, {least - af:.2f} under the least its "
        f"{size} standard allows ({least:.2f}); taken as size {tool}"
    )


# ---------------------------------------------------------------------------
# The issue's reproduction: two joints, named as the issue names them.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def near():
    parts = [
        *joint(9.6, 6.0, bolt_af=10.0, names=("m6_bolt", "m6_nut")),
        *joint(12.6, 8.0, bolt_af=13.0, names=("m8_bolt", "m8_nut"), at=200.0),
    ]
    return Assembly(parts)


@pytest.mark.parametrize("kit", ["full", "metric-home"])
def test_the_issue_s_nuts_take_their_own_spanners(near, engine, kit):
    results = by_name(run(near, kit=kit, engine=engine))
    rows = {
        name: (r.fastener.size.designation, r.tool, r.verdict, r.pair)
        for name, r in results.items()
    }
    assert rows == {
        "m6_bolt": ("M6", "spanner-10", Verdict.TURNS, "m6_nut"),
        "m6_nut": ("M6", "spanner-10", Verdict.TURNS, "m6_bolt"),
        "m8_bolt": ("M8", "spanner-13", Verdict.TURNS, "m8_nut"),
        "m8_nut": ("M8", "spanner-13", Verdict.TURNS, "m8_bolt"),
    }
    assert results["m6_nut"].notes == (
        "hex drawn undersize: 9.60 across flats, 0.18 under the least its M6 standard "
        "allows (9.78); taken as size 10",
    )
    assert results["m8_nut"].notes == (
        "hex drawn undersize: 12.60 across flats, 0.13 under the least its M8 standard "
        "allows (12.73); taken as size 13",
    )
    assert results["m6_bolt"].notes == results["m8_bolt"].notes == ()


def test_the_issue_s_report_says_so(near):
    report = run(near)
    lines = report.terminal_lines()
    assert f"NOTE m8_nut: {undersize(12.6, 'M8', '13')}" in lines
    assert f"NOTE m6_nut: {undersize(9.6, 'M6', '10')}" in lines
    markdown = report.markdown()
    assert "#### Notes" in markdown
    assert f"- `m8_nut`: {undersize(12.6, 'M8', '13')}" in markdown
    entries = {entry["name"]: entry for entry in json.loads(report.json_text())["fasteners"]}
    assert entries["m8_nut"]["notes"] == [undersize(12.6, "M8", "13")]
    assert entries["m8_bolt"]["notes"] == []
    assert report.exit_code == 0  # a note, not a failure


# ---------------------------------------------------------------------------
# Detection: what outranks a band.
# ---------------------------------------------------------------------------


def test_a_bore_that_says_m8_is_not_outranked_by_a_band():
    # 12.6 is in the 5/16 nut's band, which used to win over the bore.
    reading = read_shape(hex_prism(12.6, 6.4) - Cylinder(4.0, 30), Kind.NUT)
    assert reading.size.designation == "M8"
    assert (reading.size_from_drive, reading.size_from_band) == (False, False)


def test_a_nut_with_an_m8_bore_is_m8_on_its_bolt(engine):
    # Plain names: the bore says M8, so the bolt has nothing to add.
    nut = by_name(run(Assembly(joint(12.6, 8.0)), engine=engine))["nut"]
    assert (nut.fastener.size.designation, nut.tool) == ("M8", "spanner-13")
    assert nut.notes == (undersize(12.6, "M8", "13"),)


def test_a_nut_with_an_m8_bore_is_m8_alone():
    nut = hex_prism(12.6, 6.4) - Cylinder(4.0, 30)
    assembly = Assembly([Part("nut", nut), Part("plate", Pos(0, 0, -5) * Box(200, 200, 10))])
    (result,) = run(assembly).results
    assert (result.fastener.size.designation, result.tool) == ("M8", "spanner-13")
    assert result.fastener.size_guessed is False
    assert result.notes == (undersize(12.6, "M8", "13"),)


def test_a_nut_whose_band_alone_gave_its_size_takes_its_bolt_s(engine):
    # Both drawn at 6.8, no standard size: the bolt's 13 mm head says M8; the nut's
    # hex, alone, says 5/16 by the band below 1/2 in.
    results = by_name(run(Assembly(joint(12.6, 6.8)), engine=engine))
    nut, bolt = results["nut"], results["bolt"]
    assert bolt.fastener.size.designation == "M8"
    assert (nut.fastener.size.designation, nut.tool, nut.verdict) == (
        "M8",
        "spanner-13",
        Verdict.TURNS,
    )
    assert nut.notes == (
        "size M8 from its bolt, bolt (its hex alone said 5/16)",
        undersize(12.6, "M8", "13"),
    )
    assert nut.fastener.basis.endswith(
        "5/16 by its hex's tolerance band alone; "
        "size M8 from its bolt, bolt (its hex alone said 5/16)"
    )
    assert nut.fastener.size_guessed is False  # settled now


def test_detect_writes_the_bolt_s_size_and_the_hex_as_drawn():
    # Kept as written, the sidecar gives the same verdict, by the same note.
    assembly = Assembly(joint(12.6, 6.8))
    text = sidecar_text(run(assembly), "model.step")
    rules = {rule["parts"]: rule for rule in yaml.safe_load(text)["fasteners"]}
    assert rules["nut"] == {"parts": "nut", "kind": "nut", "size": "M8", "across_flats": 12.6}
    assert "size M8 from its bolt, bolt (its hex alone said 5/16)" in text
    nut = by_name(check(assembly, Config.from_dict(yaml.safe_load(text))))["nut"]
    assert (nut.verdict, nut.tool) == (Verdict.TURNS, "spanner-13")
    assert nut.notes == (undersize(12.6, "M8", "13"),)


def test_with_no_bolt_a_band_s_guess_stands_saying_so():
    nut = hex_prism(12.6, 6.8) - Cylinder(3.4, 30)
    assembly = Assembly([Part("nut", nut), Part("plate", Pos(0, 0, -5) * Box(200, 200, 10))])
    (result,) = run(assembly).results
    assert (result.fastener.size.designation, result.tool) == ("5/16", "spanner-1/2in")
    assert result.fastener.size_guessed is True
    assert result.fastener.confidence == "medium"
    assert result.fastener.basis.endswith("5/16 by its hex's tolerance band alone")
    assert result.notes == ()


def test_a_name_s_size_outranks_a_band_s_guess():
    nut = hex_prism(12.6, 6.8) - Cylinder(3.4, 30)
    assembly = Assembly([Part("nut_m8", nut), Part("plate", Pos(0, 0, -5) * Box(200, 200, 10))])
    (result,) = run(assembly).results
    assert (result.fastener.size.designation, result.tool) == ("M8", "spanner-13")
    assert result.fastener.size_guessed is False
    assert result.notes == (undersize(12.6, "M8", "13"),)


def test_a_nut_with_no_size_takes_its_bolt_s():
    # 7.85 is in 8 mm's band (M5) and 5/16 in's (#6): the nut's own reading has no
    # size. The bolt's 8 mm head says M5; 7.85 is in its band, so no undersize.
    results = by_name(run(Assembly(joint(7.85, 4.4, bolt_af=8.0))))
    nut = results["nut"]
    assert results["bolt"].fastener.size.designation == "M5"
    assert (nut.fastener.size.designation, nut.tool) == ("M5", "spanner-8")
    assert nut.notes == ("size M5 from its bolt, bolt",)


# ---------------------------------------------------------------------------
# _sized_by_partners: which nut takes which bolt's size.
# ---------------------------------------------------------------------------

M8 = Size.parse("M8")
M5 = Size.parse("M5")
INCH = Size.parse("5/16")


def bolt(size=M8, kind=Kind.SCREW):
    return Fastener("bolt", kind, size=size)


def nut(size=None, *, guessed=False, socket_allowed=True, basis=""):
    return Fastener(
        "nut",
        Kind.NUT,
        size=size,
        size_guessed=guessed,
        socket_allowed=socket_allowed,
        basis=basis,
    )


def sized(*fasteners):
    pairs = {"bolt": "nut", "nut": "bolt"}
    after, notes = _sized_by_partners(list(fasteners), pairs)
    return {f.name: f for f in after}, notes


@pytest.mark.parametrize(
    ("the_nut", "taken"),
    [
        (nut(), True),
        (nut(INCH, guessed=True), True),
        (nut(INCH), False),  # measured, or from the sidecar: a nut of its own size
        (nut(M8, guessed=True), False),  # agrees already: nothing to say
        (nut(socket_allowed=False), False),  # a gland: its thread is not its hex's
    ],
    ids=["no size", "guessed", "measured", "agrees", "gland"],
)
def test_which_nut_takes_its_bolt_s_size(the_nut, taken):
    after, notes = sized(bolt(), the_nut)
    assert (after["nut"].size == M8) is (taken or the_nut.size == M8)
    assert ("nut" in notes) is taken
    assert after["bolt"] == bolt()  # the bolt never changes


def test_a_bolt_with_no_size_gives_none():
    after, notes = sized(bolt(None), nut())
    assert (after["nut"].size, notes) == (None, {})


def test_a_nut_paired_with_a_nut_takes_nothing():
    after, notes = sized(bolt(kind=Kind.NUT), nut())
    assert (after["nut"].size, notes) == (None, {})


def test_an_unpaired_nut_takes_nothing():
    after, notes = _sized_by_partners([bolt(), nut()], {})
    assert (after[1].size, notes) == (None, {})


def test_the_basis_says_where_the_size_came_from():
    after, notes = sized(bolt(M5), nut(INCH, guessed=True, basis="noun 'nut'"))
    note = "size M5 from its bolt, bolt (its hex alone said 5/16)"
    assert notes == {"nut": (note,)}
    assert after["nut"].basis == f"noun 'nut'; {note}"
    assert (after["nut"].size, after["nut"].size_guessed) == (M5, False)
    after, _ = sized(bolt(), nut())
    assert after["nut"].basis == "size M8 from its bolt, bolt"


# ---------------------------------------------------------------------------
# The sidecar's across_flats: the steps, one by one.
# ---------------------------------------------------------------------------


def run_rule(af, size, kit="full"):
    rule = {"parts": "nut", "kind": "nut", "across_flats": af, **({"size": size} if size else {})}
    (result,) = run(nut_on_plate(af, bore=3.0), [rule], kit=kit).results
    return result


@pytest.mark.parametrize(
    ("size", "af", "tool"),
    [
        ("M6", 9.6, "10"),
        ("M8", 12.6, "13"),
        ("M8", 12.72, "13"),  # 0.01 under the band
        ("M8", 12.44, "13"),  # 0.29 under: still a model drawn small
        ("M10", 15.6, "16"),  # ISO 4032's 16
        ("M10", 16.6, "17"),  # DIN 934's 17: the 16 doesn't go over it
        ("M12", 18.5, "19"),  # DIN 934's 19 again, not ISO's 18
        ("5/16", 12.3, "1/2in"),  # an inch thread, its own inch spanner
    ],
)
def test_a_hex_a_little_under_its_band_takes_its_own_size_with_a_note(size, af, tool):
    result = run_rule(af, size)
    assert (result.verdict, result.tool) == (Verdict.TURNS, f"spanner-{tool}")
    assert result.notes == (undersize(af, size, tool),)
    assert size_mm(tool) > af  # the spanner goes over it


@pytest.mark.parametrize("af", [13.0, 12.8, 12.73])
def test_a_hex_in_its_band_says_nothing(af):
    result = run_rule(af, "M8")
    assert (result.tool, result.notes) == ("spanner-13", ())


@pytest.mark.parametrize(
    ("af", "size", "reason"),
    [
        (
            12.42,  # 0.31 under M8's band: more than a model drawn small
            "M8",
            "12.42 mm across flats is no tool's size: the smallest that fits, spanner-13, "
            "is 0.58 larger; set across_flats: or tool: in the sidecar",
        ),
        (
            13.1,  # over the band: no spanner of 13 goes over it
            "M8",
            "13.10 mm across flats is no tool's size: the smallest that fits, spanner-14, "
            "is 0.90 larger; set across_flats: or tool: in the sidecar",
        ),
        (
            9.4,  # under M6's 10 by 0.38; 3/8 in (9.525) would go over it, but is inch
            "M6",
            "9.40 mm across flats is no tool's size: the smallest that fits, spanner-10, "
            "is 0.60 larger; set across_flats: or tool: in the sidecar",
        ),
        (
            13.3,  # no size of either system: a 14 is nearer, but the thread is inch
            "1/2",
            "13.30 mm across flats is no tool's size: the smallest that fits, "
            "spanner-9/16in, is 0.99 larger; set across_flats: or tool: in the sidecar",
        ),
        (
            55.0,
            None,
            "55.00 mm across flats is larger than any spanner the tables hold "
            "(spanner-50 the largest); set tool: in the sidecar",
        ),
    ],
)
def test_too_far_under_or_over_is_not_covered_naming_a_tool_that_fits(af, size, reason):
    result = run_rule(af, size)
    assert result.verdict is Verdict.NOT_COVERED
    assert result.reason == reason


def test_how_far_under_is_drawn_small():
    assert UNDERSIZE_MM == 0.3
    assert run_rule(12.73 - UNDERSIZE_MM + 0.01, "M8").tool == "spanner-13"
    assert run_rule(12.73 - UNDERSIZE_MM - 0.01, "M8").verdict is Verdict.NOT_COVERED


@pytest.mark.parametrize(
    ("af", "size", "tool", "system"),
    [
        (19.05, "M12", "3/4in", "an inch"),  # over DIN's 19, under 20's band
        (inch_mm("7/16"), "M6", "7/16in", "an inch"),
        (13.0, "5/16", "13", "a metric"),  # 1/2 in's band ends at 12.70
    ],
)
def test_a_hex_exactly_the_other_system_s_size_takes_it_with_a_note(af, size, tool, system):
    result = run_rule(af, size)
    assert (result.verdict, result.tool) == (Verdict.TURNS, f"spanner-{tool}")
    assert result.notes == (
        f"hex drawn {af:.2f} across flats, {system} size, its thread {size}; taken as size {tool}",
    )


def test_with_no_thread_the_nearest_system_still_decides():
    # Nothing to keep to: 12.6 is in 1/2 in's band, and that is the spanner.
    result = run_rule(12.6, None)
    assert (result.tool, result.notes) == ("spanner-1/2in", ())


def test_a_forced_tool_has_no_notes():
    rule = {"parts": "nut", "kind": "nut", "size": "M8", "across_flats": 12.6, "tool": "spanner-13"}
    (result,) = run(nut_on_plate(12.6, bore=3.0), [rule]).results
    assert (result.tool, result.notes) == ("spanner-13", ())


def test_metric_home_turns_the_undersize_nut():
    # The issue's other half: the inch spanner was not in the kit.
    result = run_rule(12.6, "M8", kit="metric-home")
    assert (result.verdict, result.tool) == (Verdict.TURNS, "spanner-13")


# ---------------------------------------------------------------------------
# Keys: no band, but the thread's system and the hint.
# ---------------------------------------------------------------------------


def socket_head(key_af, size="M10"):
    """A round head with a hex pocket of ``key_af``, on a shank of ``size``."""
    d = Size.parse(size).diameter_mm
    head = Pos(0, 0, d / 2) * Cylinder(0.75 * d + 0.5, d)
    return Pos(0, 0, -10) * Cylinder(d / 2, 20) + head - hex_prism(key_af, d / 2 + 0.01, d / 2)


def run_key(af, size):
    rule = {"parts": "screw", "kind": "screw", "head": "socket", "size": size, "across_flats": af}
    plate = Part("plate", Pos(0, 0, -5) * Box(200, 200, 10))
    (result,) = run(Assembly([Part("screw", socket_head(af, size)), plate]), [rule]).results
    return result


def test_a_key_of_the_other_system_s_exact_size_takes_it_with_a_note():
    result = run_key(inch_mm("5/16"), "M10")
    assert (result.verdict, result.tool) == (Verdict.TURNS, "hex-key-5/16in")
    assert result.notes == (
        "hex drawn 7.94 across flats, an inch size, its thread M10; taken as size 5/16in",
    )


def test_a_key_of_its_own_size_says_nothing():
    result = run_key(8.0, "M10")
    assert (result.tool, result.notes) == ("hex-key-8", ())


# ---------------------------------------------------------------------------
# Every hint, swept: it names a tool that fits, of the thread's system first,
# the nearest such; and every tool taken is of the thread's system or says not.
# ---------------------------------------------------------------------------

HINT = re.compile(r"the (smallest|largest) that fits, (?:spanner|hex-key)-(\S+), is ([\d.]+) ")
THREADS = [None, "M5", "M8", "M10", "M12", "#6", "5/16", "1/2"]


def resolve(af, thread, sizes, family, bands):
    fastener = Fastener("x", Kind.NUT, size=thread and Size.parse(thread), drive_af=af)
    try:
        return _resolve_af(fastener, sizes, family, bands=bands), None
    except NotCovered as error:
        return (None, None), str(error)


def sweep(sizes):
    low, high = min(sizes) - 1.0, max(sizes) + 1.0
    return [round(low + 0.013 * step, 3) for step in range(int((high - low) / 0.013))]


@pytest.mark.parametrize(
    ("family", "sizes", "bands"),
    [("spanner", FLATS, True), ("hex-key", KEYS, False)],
)
@pytest.mark.parametrize("thread", THREADS)
def test_every_hint_names_a_tool_that_fits_and_the_thread_s_own_first(family, sizes, bands, thread):
    over = family == "spanner"  # a spanner goes over the hex, a key into it
    metric = None if thread is None else Size.parse(thread).is_metric
    hints = 0
    for af in sweep(sizes):
        _, reason = resolve(af, thread, sizes, family, bands)
        match = reason and HINT.search(reason)
        if not match:
            continue
        hints += 1
        tool = size_mm(match[2])
        assert match[1] == ("smallest" if over else "largest")
        assert (tool >= af) if over else (tool <= af), reason
        assert float(match[3]) == pytest.approx(abs(tool - af), abs=0.006)
        ours = [s for s in sizes if metric is None or is_inch(s) is not metric]
        fitting = [s for s in ours if (s >= af if over else s <= af)]
        if fitting:  # its own system's, and none of it nearer
            assert tool == (min(fitting) if over else max(fitting)), reason
    assert hints > 100  # a vacuity guard: the sweep met plenty of hexes no tool takes


@pytest.mark.parametrize(
    ("family", "sizes", "bands"),
    [("spanner", FLATS, True), ("hex-key", KEYS, False)],
)
@pytest.mark.parametrize("thread", [t for t in THREADS if t])
def test_every_tool_taken_keeps_to_the_thread_s_system_or_says_why(family, sizes, bands, thread):
    size = Size.parse(thread)
    taken = undersized = crossed = 0
    for af in sweep(sizes):
        (tool, note), _ = resolve(af, thread, sizes, family, bands)
        if tool is None:
            continue
        taken += 1
        if is_inch(tool) is size.is_metric:  # the other system's tool
            crossed += 1
            assert note is not None
            system = "an inch" if is_inch(tool) else "a metric"
            assert note == (
                f"hex drawn {af:.2f} across flats, {system} size, its thread {thread}; "
                f"taken as size {size_name(tool)}"
            )
            assert abs(tool - af) <= 0.05  # only an exact size crosses
        elif note is not None:
            assert note.startswith("hex drawn undersize")
            undersized += 1
            assert bands
            assert tool > af
            assert HEX_AF_MIN.get(tool, tool) - UNDERSIZE_MM <= af
            assert tool in standard_hex_afs(size)
    assert taken > 20
    assert crossed > 0
    assert undersized > 0 or not bands or not standard_hex_afs(size)


# ---------------------------------------------------------------------------
# A long list of notes is cut, as the other lists are.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", [PASSED_OVER_SHOWN, PASSED_OVER_SHOWN + 1])
def test_a_long_list_of_notes_is_cut(count):
    fastener = Fastener("nut", Kind.NUT, size=M8)
    many = tuple(
        FastenerResult(
            replace(fastener, name=f"nut{index}"),
            Verdict.TURNS,
            tool="spanner-13",
            how="ring, full length",
            notes=(f"note {index}",),
        )
        for index in range(count)
    )
    report = Report(model="m", kit="full", results=many)
    lines = report.terminal_lines()
    assert sum(line.startswith("NOTE nut") for line in lines) == PASSED_OVER_SHOWN
    cut = [line for line in lines if line.startswith("NOTE and")]
    more = count > PASSED_OVER_SHOWN
    assert cut == (["NOTE and 1 more (the JSON lists every note)"] if more else [])
    markdown = report.markdown()
    assert markdown.count("- `nut") == PASSED_OVER_SHOWN
    assert ("- and 1 more (the JSON lists every one)" in markdown) is more
    entries = json.loads(report.json_text())["fasteners"]
    assert [entry["notes"] for entry in entries] == [[f"note {i}"] for i in range(count)]


def test_two_notes_on_one_result_are_two_lines():
    result = FastenerResult(
        Fastener("nut", Kind.NUT, size=M8), Verdict.TURNS, tool="spanner-13", notes=("a", "b")
    )
    report = Report(model="m", kit="full", results=(result,))
    assert [line for line in report.terminal_lines() if line.startswith("NOTE nut")] == [
        "NOTE nut: a",
        "NOTE nut: b",
    ]
    assert "- `nut`: a\n- `nut`: b" in report.markdown()


def test_no_notes_say_nothing():
    result = FastenerResult(Fastener("nut", Kind.NUT, size=M8), Verdict.TURNS, tool="spanner-13")
    report = Report(model="m", kit="full", results=(result,))
    assert not any(line.startswith("NOTE nut") for line in report.terminal_lines())
    assert "Notes" not in report.markdown()
