"""A report names a part, never a piece of one (issue #210).

Read from STEP, a part drawn as several solids is its largest solid and ``name#2``
pieces, and a tool's scene holds each solid for itself. What stood in a tool's way
was named solid by solid, so a report said ``cover#2``, a name the model doesn't
have; and the clash list told a clash for each solid, where the same part handed
over whole is one line. A nut in a pocket whose two walls are two solids of one part
was not held by it, since no one solid stood on both sides of it.

A scene names the part now, once, whichever of its solids are met; the clash list
tells two parts' clash once, their solids' volumes together; and the view marks
every solid of a part named. The two readers say the same.
"""

import math

import pytest
from build123d import Box, Compound, Cylinder, Pos

from test_ring_way_on import PLATE, RING, attempt, cover, stud
from test_ring_way_on import RULES as RING_RULES
from test_ring_way_on import nut as m8_nut
from test_traps import NUT, SCREW, nut, screw
from test_whole_parts import SCREW as M6_SCREW
from test_whole_parts import as_step_reads, covered, socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check, find_clashes
from wrenchroom.clashes import Clash, _by_part
from wrenchroom.config import Config
from wrenchroom.engine import ENGINES, make_engine
from wrenchroom.engine import exact as exact_module
from wrenchroom.engine import mesh as mesh_module
from wrenchroom.engine.scene import Scene
from wrenchroom.report import Verdict
from wrenchroom.view import view_data

READERS = {"in-pieces": as_step_reads, "whole": Assembly.from_shapes}
EITHER = pytest.mark.parametrize("reader", list(READERS))
RULED = {"fasteners": [M6_SCREW]}


def over_twice():
    """A cover of two solids, both 10 over the screw's head: two bars side by side."""
    near, far = Pos(-8, 0, 38) * Box(14, 30, 4), Pos(8, 0, 38) * Box(14, 30, 4.5)
    return covered(Compound([near.solid(), far.solid()]))


# ---------------------------------------------------------------------------
# What stands in a tool's way.
# ---------------------------------------------------------------------------


@EITHER
@pytest.mark.parametrize("engine", ENGINES)
def test_a_part_in_the_way_is_named_once_whichever_solids_are(reader, engine):
    (result,) = check(READERS[reader](over_twice()), Config.from_dict(RULED), engine=engine).results
    assert (result.verdict, result.blocked_by) == (Verdict.BLOCKED, ("cover",))
    assert all("#" not in name for attempt in result.attempts for name in attempt.blockers)


@EITHER
def test_every_report_names_the_part(reader):
    report = check(READERS[reader](covered()), Config.from_dict(RULED))
    (entry,) = report.to_json_dict()["fasteners"]
    assert entry["blocked_by"] == ["cover"]
    said = "\n".join([*report.terminal_lines(), report.markdown()])
    assert "cover#2" not in said
    assert "FAIL bolt  hex-key-5  blocked  cover" in said


def test_the_two_readers_give_one_report_of_a_part_in_the_way():
    first, second = (
        check(read(over_twice()), Config.from_dict(RULED)).to_json_dict()
        for read in READERS.values()
    )
    assert first == second


def test_a_part_that_only_shares_the_name_is_named_for_itself():
    # Two parts named cover, the second numbered cover#2 as a piece would be: it is
    # the one over the screw, a part of its own, and it is what the report names.
    plate = Pos(0, 0, -5) * Box(200, 100, 10)
    aside, above = Pos(70, 0, 45) * Box(40, 80, 10), Pos(0, 0, 38) * Box(30, 30, 4)
    model = as_step_reads(
        [("plate", plate), ("bolt", socket_screw()), ("cover", aside), ("cover", above)]
    )
    assert [(part.name, part.piece_of) for part in model][2:] == [
        ("cover", None),
        ("cover#2", None),
    ]
    (result,) = check(model, Config.from_dict(RULED)).results
    assert result.blocked_by == ("cover#2",)


def test_the_view_marks_every_solid_of_a_part_in_the_way():
    # And of no other: a shelf of two solids, well aside, is in nobody's way.
    shelf = Compound(
        [(Pos(-80, 0, 60) * Box(10, 10, 10)).solid(), (Pos(-80, 30, 60) * Box(5, 5, 5)).solid()]
    )
    report = check(as_step_reads([*covered(), ("shelf", shelf)]), Config.from_dict(RULED))
    view = view_data(report)
    assert "shelf#2" in [part["name"] for part in view["parts"]]
    names = [part["name"] for part in view["parts"]]
    (drawn,) = view["fasteners"]
    assert drawn["in_way"] == ["cover"]
    assert sorted(names[index] for index in drawn["highlight"]) == ["cover", "cover#2"]


# ---------------------------------------------------------------------------
# The scene itself.
# ---------------------------------------------------------------------------


def scene_of(parts, engine="mesh"):
    return Scene(parts, make_engine(engine))


@pytest.mark.parametrize("engine", ENGINES)
def test_a_scene_names_a_part_once_for_any_of_its_solids(engine):
    left, right = Pos(-10, 0, 0) * Box(10, 10, 10), Pos(10, 0, 0) * Box(10, 10, 10)
    parts = [Part("rail", left), Part("rail#2", right, piece_of="rail"), Part("post", left)]
    scene = scene_of(parts, engine)
    both = Box(40, 4, 4)  # through both rails, and the post where the first is
    assert scene.contacts(both) == (("rail", "post"), ())
    assert scene.hits(Pos(10, 0, 0) * Box(4, 4, 4)) == ("rail",)  # its piece alone
    assert scene.hits(Pos(0, 30, 0) * Box(4, 4, 4)) == ()


@pytest.mark.parametrize("engine", ENGINES)
def test_a_part_one_solid_of_which_is_overlapped_is_overlapped_not_grazed(engine):
    # A bar a hair into the near rail (a graze) and well into the far one (a hit): the
    # part is overlapped, and not named among what is only grazed.
    near, far = Pos(-10, 0, 0) * Box(10, 10, 10), Pos(10, 0, 0) * Box(10, 10, 10)
    parts = [Part("rail", near), Part("rail#2", far, piece_of="rail")]
    grazing = Pos(-18.999, 0, 0) * Box(8, 4, 4)  # 0.001 into the near rail's face
    scene = scene_of(parts, engine)
    assert scene.contacts(grazing) == ((), ("rail",))
    bar = Compound([grazing.solid(), (Pos(10, 0, 0) * Box(4, 4, 4)).solid()])
    assert scene.contacts(bar) == (("rail",), ())


def test_a_scene_names_a_part_that_only_shares_a_name_for_itself():
    left, right = Pos(-10, 0, 0) * Box(10, 10, 10), Pos(10, 0, 0) * Box(10, 10, 10)
    scene = scene_of([Part("rail", left), Part("rail#2", right)])
    assert scene.hits(Box(40, 4, 4)) == ("rail", "rail#2")


# ---------------------------------------------------------------------------
# A trap of two solids.
# ---------------------------------------------------------------------------


def two_jaws():
    """An M3 nut in a slot its own width, test_traps.py's, whose two walls are two solids.

    A block over it for its screw to come through, and the jaws, one part: a wall
    each side of the nut, 5.7 apart. Its corners meet the jaws on opposite sides, and
    no one solid of them on both.
    """
    top = Pos(0, 0, -3.35) * Box(30, 30, 6.7) - Cylinder(1.7, 40)
    near, far = Pos(0, 7.85, -8) * Box(30, 10, 2.6), Pos(0, -7.85, -8) * Box(30, 10, 2.6)
    jaws = Compound([near.solid(), far.solid()])
    return [("block", top), ("jaws", jaws), ("screw", screw()), ("nut", Pos(0, 0, -9.2) * nut(0))]


@EITHER
@pytest.mark.parametrize("engine", ENGINES)
def test_a_nut_is_held_by_a_slot_whose_walls_are_two_solids_of_one_part(reader, engine):
    report = check(
        READERS[reader](two_jaws()),
        Config.from_dict({"fasteners": [SCREW, NUT]}),
        kit="metric-home",
        engine=engine,
    )
    by_name = {result.fastener.name: result for result in report.results}
    assert by_name["nut"].verdict is Verdict.HELD
    assert by_name["nut"].how == "held by its trap in jaws"
    assert by_name["screw"].verdict is Verdict.TURNS


# ---------------------------------------------------------------------------
# What a nut is on.
# ---------------------------------------------------------------------------


@EITHER
@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize(("underside", "on"), [(13.4 - 0.3, False), (13.4 + 0.3, True)])
def test_a_stud_that_is_a_piece_of_its_plate_is_cleared_as_a_stud(reader, engine, underside, on):
    # tests/test_ring_way_on.py's stud welded to its plate (issue #143), the two drawn
    # as two solids of one part: the stud, the plate's piece, is what runs up through
    # the nut, and its end, at 8, is what the ring clears, at 13.4.
    welded = Compound([PLATE.solid(), stud().solid()])
    parts = [("plate", welded), ("nut", m8_nut()), ("cover", cover(underside))]
    config = Config.from_dict({"fasteners": RING_RULES[:1], "checks": {"detect": False}})
    (result,) = check(READERS[reader](parts), config, engine=engine).results
    assert attempt(result, RING).turns is on


# ---------------------------------------------------------------------------
# The clash list.
# ---------------------------------------------------------------------------


def two_into_the_head():
    """Two pads of one cover, each over half the screw's head and 1 down into it.

    The head is pi 5.5^2 = 95.0 mm^2: 47.5 mm^3 into each pad, 95.0 into the cover.
    """
    plate = Pos(0, 0, -5) * Box(200, 100, 10)
    near, far = Pos(-10, 0, 27) * Box(20, 30, 4), Pos(10.5, 0, 27) * Box(21, 30, 4)
    cover = Compound([near.solid(), far.solid()])
    return [("plate", plate), ("bolt", socket_screw()), ("cover", cover)]


def listed(found):
    return [(clash.first, clash.second, round(clash.volume, 1)) for clash in found.found]


@EITHER
@pytest.mark.parametrize("engine", ENGINES)
def test_a_part_s_solids_clashes_are_one_clash_their_volumes_together(reader, engine):
    found = find_clashes(
        READERS[reader](two_into_the_head()), Config.from_dict(RULED), engine=engine
    )
    assert listed(found) == [("bolt", "cover", 95.0)]
    assert found.lines()[:2] == [
        "1 clash (overlap over 0.05 mm^3)",
        "CLASH bolt into cover  95.0 mm^3",
    ]


@EITHER
def test_the_verdict_says_the_part_and_the_list_s_volume(reader):
    # Issue #156, for a part in pieces: what the check says is drawn into is the list's.
    report = check(READERS[reader](two_into_the_head()), Config.from_dict(RULED), clashes=True)
    (result,) = report.results
    assert (result.verdict, result.reason) == (
        Verdict.NOT_COVERED,
        "drawn into cover (95.0 mm^3): fix the model",
    )
    assert listed(report.clashes) == [("bolt", "cover", 95.0)]
    assert report.clashes.to_json()["found"][0]["parts"] == ["bolt", "cover"]


def test_two_parts_that_share_a_name_are_two_clashes():
    plate = Pos(0, 0, -5) * Box(200, 100, 10)
    near, far = Pos(-10, 0, 27) * Box(20, 30, 4), Pos(10.5, 0, 27) * Box(21, 30, 4)
    model = as_step_reads(
        [("plate", plate), ("bolt", socket_screw()), ("cover", near), ("cover", far)]
    )
    found = find_clashes(model, Config.from_dict(RULED))
    assert listed(found) == [("bolt", "cover", 47.5), ("bolt", "cover#2", 47.5)]


def test_the_view_draws_both_solids_and_all_of_the_overlap():
    report = check(as_step_reads(two_into_the_head()), Config.from_dict(RULED), clashes=True)
    view = view_data(report)
    names = [part["name"] for part in view["parts"]]
    (clash,) = view["clashes"]["found"]
    assert clash["label"] == "bolt into cover"
    assert sorted(names[index] for index in clash["parts"]) == ["bolt", "cover", "cover#2"]
    whole = view_data(
        check(Assembly.from_shapes(two_into_the_head()), Config.from_dict(RULED), clashes=True)
    )
    assert clash["volume"] == whole["clashes"]["found"][0]["volume"] == "95.0"


@pytest.mark.parametrize("engine", ENGINES)
def test_a_clash_measured_on_the_meshes_for_any_solid_says_so(engine, monkeypatch):
    # Every boolean made to come back empty (issue #163): the two pads' clashes are
    # told on the meshes, and so is the one clash they make.
    for module in (mesh_module, exact_module):
        monkeypatch.setattr(module, "measured_common", lambda a, b: (None, True))
    found = find_clashes(as_step_reads(two_into_the_head()), Config.from_dict(RULED), engine=engine)
    (clash,) = found.found
    assert (clash.first, clash.second, clash.by_meshes) == ("bolt", "cover", True)
    assert clash.volume == pytest.approx(95.0, rel=0.05)


# ---------------------------------------------------------------------------
# _by_part, by itself.
# ---------------------------------------------------------------------------

PART_OF = {"pin": "pin", "pin#2": "pin", "block": "block", "block#2": "block", "rod": "rod"}


def clash(first, second, volume, **more):
    return Clash(first, second, volume, (volume, 0.0, 0.0), **more)


def test_one_clash_to_two_parts_the_largest_saying_the_rest():
    found = [
        clash("pin", "block", 2.0, hint="small"),
        clash("block#2", "pin#2", 5.0, hint="large", unasked=True),
        clash("pin#2", "block", 1.0, by_meshes=True),
        clash("rod", "block", 4.0),
    ]
    told = {(c.first, c.second): c for c in _by_part(found, PART_OF)}
    assert set(told) == {("block", "pin"), ("rod", "block")}
    merged = told["block", "pin"]
    assert (merged.volume, merged.point, merged.hint) == (8.0, (5.0, 0.0, 0.0), "large")
    assert (merged.by_meshes, merged.unasked) == (True, True)
    assert told["rod", "block"] == clash("rod", "block", 4.0)


def test_an_insert_s_share_set_in_stays_apart_from_its_clash():
    found = [clash("pin", "block", 2.0, set_in=True), clash("pin", "block#2", 3.0)]
    told = sorted(_by_part(found, PART_OF), key=lambda c: c.set_in)
    assert [(c.first, c.second, c.volume, c.set_in) for c in told] == [
        ("pin", "block", 3.0, False),
        ("pin", "block", 2.0, True),
    ]


def test_a_name_no_part_has_is_left_as_it_is():
    # A fastener's measured region goes by the fastener's name, which is the part's.
    (only,) = _by_part([clash("bolt", "pin#2", 1.0)], PART_OF)
    assert (only.first, only.second) == ("bolt", "pin")


def test_what_is_drawn_of_several_overlaps_is_all_of_them():
    import numpy as np  # noqa: PLC0415

    one = (np.zeros((3, 3)), np.array([[0, 1, 2]]))
    two = (np.ones((4, 3)), np.array([[0, 1, 2], [1, 2, 3]]))
    found = [clash("pin", "block", 2.0, overlap=one), clash("pin#2", "block", 1.0, overlap=two)]
    (merged,) = _by_part(found, PART_OF)
    vertices, triangles = merged.overlap
    assert (len(vertices), triangles.tolist()) == (7, [[0, 1, 2], [3, 4, 5], [4, 5, 6]])
    solids = [Box(1, 1, 1), Pos(5, 0, 0) * Box(2, 1, 1)]
    found = [
        clash("pin", "block", 2.0, overlap=solids[1]),
        clash("pin#2", "block", 1.0, overlap=solids[0]),
    ]
    (merged,) = _by_part(found, PART_OF)
    assert merged.overlap.volume == pytest.approx(3.0)
    assert math.isclose(merged.volume, 3.0)
