"""A rule's mates (issue #32): globs, as every other part list, and never silent.

A mate leaves its fastener's scene. The case: a nyloc drawn as an M6 nut and a
separate nylon dome on its top face. Unless the dome is a mate, it covers the
nut's free face, both ends read covered, and the nut can't be checked.
"""

from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config, is_mate
from wrenchroom.report import Verdict

COVERED = "cannot tell the nut's free face: both ends are covered"


def nyloc(dome="lock_nut_dome", washers=()):
    """An M6 nut (af 10, 5.2 tall) on a plate, its dome (and any washers) on top."""
    parts = [
        Part("lock_nut", hex_prism(10, 5.2) - Cylinder(3, 20)),
        Part(dome, Pos(0, 0, 5.2 + 1.25) * (Cylinder(4.8, 2.5) - Cylinder(3, 3))),
        Part("plate", Pos(0, 0, -5) * Box(200, 200, 10)),
    ]
    parts += [Part(name, Pos(150 * (i + 1), 0, 0) * Box(5, 5, 5)) for i, name in enumerate(washers)]
    return Assembly(parts)


def run(assembly, mates, parts="lock_nut"):
    rule = {"parts": parts, "kind": "nut", "size": "M6", "mates": mates}
    config = Config.from_dict({"fasteners": [rule], "checks": {"detect": False}})
    return check(assembly, config, engine="exact")


def test_without_its_mate_the_dome_covers_the_nut():
    (result,) = run(nyloc(), []).results
    assert result.reason == COVERED


def test_a_mate_glob_takes_the_dome_out_of_the_scene():
    report = run(nyloc(), ["lock_nut_d*"])
    (result,) = report.results
    assert (result.verdict, result.tool) == (Verdict.TURNS, "spanner-10")
    assert report.warnings == ()
    assert report.exit_code == 0


def test_an_exact_name_still_names_its_part():
    (result,) = run(nyloc(), ["lock_nut_dome"]).results
    assert result.verdict is Verdict.TURNS


def test_a_name_that_reads_as_a_glob_still_matches_itself():
    # As a glob, "dome[1]" means "dome1"; as the name it always was, it means itself.
    (result,) = run(nyloc(dome="dome[1]"), ["dome[1]"]).results
    assert result.verdict is Verdict.TURNS


def test_a_mate_that_matches_nothing_fails_the_run_saying_so():
    report = run(nyloc(), ["link_a_*"])
    (result,) = report.results
    assert result.reason == COVERED  # the dome still in the way, as before
    assert report.warnings == (
        "rule 'lock_nut': mate glob 'link_a_*' matched nothing (renamed part?)",
    )
    assert report.exit_code == 2
    assert "WARN rule 'lock_nut': mate glob 'link_a_*' matched nothing" in "\n".join(
        report.terminal_lines()
    )


def test_each_unmatched_mate_is_named_once_and_a_matched_one_not_at_all():
    report = run(nyloc(), ["lock_nut_dome", "gone_*", "also_gone"])
    assert report.warnings == (
        "rule 'lock_nut': mate glob 'gone_*' matched nothing (renamed part?)",
        "rule 'lock_nut': mate glob 'also_gone' matched nothing (renamed part?)",
    )
    (result,) = report.results
    assert result.verdict is Verdict.TURNS


def test_a_rule_that_matches_nothing_is_reported_once_not_again_for_its_mates():
    report = run(nyloc(), ["gone_*"], parts="renamed_nut")
    assert report.unmatched_rules == ("renamed_nut",)
    assert report.warnings == ()


def test_the_config_reports_unmatched_mates_and_is_not_clean():
    rule = {"parts": "lock_nut", "kind": "nut", "size": "M6", "mates": ["lock_*_dome", "x*"]}
    matches = Config.from_dict({"fasteners": [rule]}).apply(nyloc())
    assert matches.unmatched_mates == (("lock_nut", "x*"),)
    assert not matches.clean
    clean = Config.from_dict({"fasteners": [{**rule, "mates": ["lock_*_dome"]}]})
    assert clean.apply(nyloc()).clean


def test_a_glob_can_name_several_mates():
    assert is_mate("w1", ("w*",))
    assert is_mate("w2", ("w*",))
    assert not is_mate("plate", ("w*",))
    assert not is_mate("w1", ())
    # Two washers matched by one glob: the warning stays quiet, and both leave.
    report = run(nyloc(washers=("lock_nut_w1", "lock_nut_w2")), ["lock_nut_*"])
    assert report.warnings == ()
    (result,) = report.results
    assert result.verdict is Verdict.TURNS


def test_a_mate_that_is_also_ignored_is_found_all_the_same():
    rule = {"parts": "lock_nut", "kind": "nut", "size": "M6", "mates": ["lock_nut_d*"]}
    config = {"fasteners": [rule], "ignore": ["lock_nut_dome"], "checks": {"detect": False}}
    report = check(nyloc(), Config.from_dict(config), engine="exact")
    assert report.warnings == ()
    assert report.unmatched_ignores == ()
