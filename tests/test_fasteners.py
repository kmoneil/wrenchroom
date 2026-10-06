"""Sizes parse to the right millimetres and the vocabulary holds its rules."""

import pytest

from wrenchroom.fasteners import Fastener, Head, Kind, Size


@pytest.mark.parametrize(
    ("text", "designation", "mm"),
    [
        ("M6", "M6", 6.0),
        ("m6", "M6", 6.0),
        ("M3.5", "M3.5", 3.5),
        ("#10", "#10", 4.826),
        ("#10-32", "#10", 4.826),
        ("1/4", "1/4", 6.35),
        ("1/4-20", "1/4", 6.35),
        ("5/16", "5/16", 7.938),
        ("M24", "M24", 24.0),
    ],
)
def test_size_parses(text, designation, mm):
    size = Size.parse(text)
    assert size.designation == designation
    assert size.diameter_mm == pytest.approx(mm, abs=0.001)


@pytest.mark.parametrize("text", ["M7", "M99", "#3", "2/7", "", "6mm"])
def test_unknown_sizes_are_errors(text):
    with pytest.raises(ValueError, match="unknown fastener size"):
        Size.parse(text)


def test_metric_flag():
    assert Size.parse("M6").is_metric
    assert not Size.parse("1/4").is_metric


def test_carriage_holds_itself():
    bolt = Fastener(name="fender_bolt_0", kind=Kind.SCREW, head=Head.CARRIAGE)
    assert bolt.self_holding
    plain = Fastener(name="lid_bolt_0", kind=Kind.SCREW, head=Head.SOCKET)
    assert not plain.self_holding
