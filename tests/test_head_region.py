"""A head's clash region is one clean solid.

Since #116 a screw's head is measured as the screw less a rod, its shank's radius
and 0.05, from its tip to its bearing face. The rod's end lies in the bearing
face's plane, and the cut left its rim there: the bearing face in three pieces
round it, and the rim itself an edge inside a flat face, on nothing's boundary.

A part bored 0.1 over the screw, the usual clearance hole, has its bore along that
edge, and in a real assembly a few millionths of a millimetre off it, a part
placed a hair askew. OCCT then found the head and the part had nothing in common
at all. A button head drawn 15 mm^3 into the tab it holds down (a public printer
model's sensor) measured as clear of it: no clash in the list, and in a verdict,
a screw stuck behind a part it is drawn into.

Now the head's faces are merged after the cut, and it measures as the solid it is.

The volumes, by hand, each in a plate from 1.5 under the bearing face to 1.0 over
it, bored 0.1 over the screw (r 2.05):

- #116's M4 button head (test_head_clash.py): its rim, r 3.8 to z 0.4, pi (3.8^2 -
  2.05^2) 0.4 = 12.87, and its dome from 0.4 to 1.0, a sphere of 4.4881 about z
  -1.9881: pi [(R^2 - 2.05^2) 0.6 - (2.9881^3 - 2.3881^3) / 3] = 16.37. 29.23 mm^3.
- An ISO 4762 M4 socket head, 7 across: pi (3.5^2 - 2.05^2) 1 = 25.28 mm^3.

And the button head in a plate up to z 3.0, over its top: all of it past r 2.05,
which its dome comes in to at z 2.0044. The dome from 0.4, pi [(R^2 - 2.05^2)
1.6044 - (3.9925^3 - 2.3881^3) / 3] = 27.96, and the rim's 12.87: 40.83 mm^3.
"""

import itertools
import math

import pytest
from build123d import Box, Cylinder, GeomType, Pos, Rot

from fastener_models import socket_screw
from test_head_clash import BUTTON, R, button
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import _frame, _measured, check
from wrenchroom.config import Config
from wrenchroom.engine.exact import cut, exact_overlap, merged
from wrenchroom.fasteners import Fastener, Head, Kind, Size
from wrenchroom.report import Verdict

ROD = 2.05  # an M4's shank, drawn 2 round, and the 0.05 left out round it
BUTTON_IN_PLATE = math.pi * (
    (3.8**2 - ROD**2) * 0.4 + (R**2 - ROD**2) * 0.6 - (2.9881**3 - 2.3881**3) / 3
)
SOCKET_IN_PLATE = math.pi * (3.5**2 - ROD**2)

HEADS = {
    "button": (button, Head.BUTTON, BUTTON_IN_PLATE),
    "socket": (lambda: socket_screw("M4"), Head.SOCKET, SOCKET_IN_PLATE),
}

#: How far off the screw's axis the plate's bore is, how much over the rod's radius
#: it is drawn, and how far it leans, radians: none, and a few millionths, as one
#: part placed on another is. On macOS arm64 the head as cut read 0 mm^3 at an
#: offset of 3e-7 and a radius 1e-7 over, at either lean, and at 1e-7 off, 1e-7
#: under and leaning.
OFFSETS = (0.0, 1e-7, 3e-7, 1e-6, 3e-6, 1e-5)
OVER = (0.0, 1e-7, -1e-7, 1e-6)
LEANS = (0.0, 2e-6)


def plate(offset=0.0, over=0.0, lean=0.0, top=1.0):
    """A plate from z -1.5 to ``top``, bored at the rod's radius and ``over``, its
    bore ``offset`` off the axis and leaning ``lean``."""
    bored = Pos(0, 0, (top - 1.5) / 2) * Box(30, 30, top + 1.5) - Cylinder(ROD + over, 40)
    return Pos(offset, offset / 3, 0) * Rot(0, math.degrees(lean), 0) * bored


def region(name):
    """A head's clash region, measured from its head's end, +z."""
    draw, head, _ = HEADS[name]
    fastener = Fastener(name="screw", kind=Kind.SCREW, head=head, size=Size.parse("M4"))
    return _measured(_frame(Part("screw", draw()), fastener), fastener, (0.0, 0.0, 1.0))[0]


BUTTON_PAST_THE_ROD = math.pi * (
    (3.8**2 - ROD**2) * 0.4 + (R**2 - ROD**2) * 1.6044 - (3.9925**3 - 2.3881**3) / 3
)


def test_the_hand_work():
    assert (f"{BUTTON_IN_PLATE:.2f}", f"{SOCKET_IN_PLATE:.2f}") == ("29.23", "25.28")
    assert f"{BUTTON_PAST_THE_ROD:.2f}" == "40.83"
    assert math.sqrt(R**2 - ROD**2) - (R - 2.5) == pytest.approx(2.0044, abs=1e-4)


@pytest.mark.parametrize(("name", "across"), [("button", 3.8), ("socket", 3.5)])
def test_a_head_s_bearing_face_is_one_face(name, across):
    # The head's underside, in the plane z = 0: one disc its rim's radius, where the
    # cut left three faces, the rod's rim between them.
    under = [
        face
        for face in region(name).faces()
        if face.geom_type is GeomType.PLANE and abs(face.center().Z) < 1e-6
    ]
    assert [round(face.area, 2) for face in under] == [round(math.pi * across**2, 2)]


@pytest.mark.parametrize("name", HEADS)
def test_a_plate_bored_at_the_rod_s_radius_measures_the_head_drawn_into_it(name):
    # Every plate of the family: the head's part in it, whatever hair its bore is off.
    head, volume = region(name), HEADS[name][2]
    read = {
        placed: exact_overlap(head, plate(*placed))
        for placed in itertools.product(OFFSETS, OVER, LEANS)
    }
    assert len(read) == 48
    assert {placed: got for placed, got in read.items() if abs(got - volume) > 0.01} == {}


def test_merging_keeps_the_volume_and_the_shape_given():
    # A block with a post on it, 2 round, the post cut away by a rod 2.5 round whose
    # end is in the block's top: the top is left in three, as a head's underside is.
    block = Box(10, 10, 10) + Pos(0, 0, 7.5) * Cylinder(2, 5)
    split = cut(block, Pos(0, 0, 8) * Cylinder(2.5, 6))
    assert len(split.faces()) == 8
    one = merged(split)
    assert len(one.faces()) == 6
    assert one.volume == pytest.approx(1000.0)
    assert len(split.faces()) == 8  # as it was given


# ---------------------------------------------------------------------------
# In a check: the screw is drawn into the plate, not stuck behind it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("offset", "over"), [(0.0, 0.0), (3e-7, 1e-7), (1e-6, 0.0)])
def test_a_button_head_in_a_plate_bored_for_it_is_a_clash(engine, offset, over):
    # A plate to z 3.0, over the head's top. The key goes down its bore, and the
    # head can't come out through it: its way out meets the plate, which it is
    # drawn into. With its bore a hair off the axis the plate measured as clear of
    # the head, and the screw was stuck behind it.
    base = Pos(0, 0, -6.5) * Box(30, 30, 10) - Cylinder(2.0, 40)
    parts = [("base", base), ("screw", button()), ("plate", plate(offset, over, top=3.0))]
    config = Config.from_dict(
        {"fasteners": [{"parts": "screw", **BUTTON}], "checks": {"detect": False}}
    )
    report = check(Assembly([Part(n, s) for n, s in parts]), config, engine=engine)
    (result,) = report.results
    assert (result.verdict, result.reason) == (
        Verdict.NOT_COVERED,
        "drawn into plate (40.8 mm^3): fix the model",
    )
