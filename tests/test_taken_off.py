"""A fastener or a plug a state takes off isn't tried in that state (issue #250).

A state's ``remove:`` leaves parts out of its scenes. One of them a fastener or a plug
was still tried there, and passed: nothing of it was in its own way, and the parts
taken off with it weren't either. A screw can't be reached for undoing in a state it
is off in already. A retry passes over such a state; a fastener or plug whose own
state takes it off is not covered, as a sidecar mistake is.
"""

import pytest
from build123d import Box, Cylinder, Pos

from fastener_models import hex_prism
from wrenchroom.assembly import Assembly, Part
from wrenchroom.checker import check
from wrenchroom.config import Config
from wrenchroom.connectors import ConnectorVerdict
from wrenchroom.report import Verdict

M6_SOCKET = {"kind": "screw", "head": "socket", "size": "M6"}
SCREW = [{"parts": "guard_screw", **M6_SOCKET}]
OFF = "its own state 'guard-off' takes it off (remove glob 'guard*'), so it can't be reached there"


def socket_screw():
    """An M6 socket head screw, its seat at z = 6, its key's socket 5 across."""
    shank = Pos(0, 0, -10) * Cylinder(3, 20)
    return shank + Pos(0, 0, 3) * Cylinder(5, 6) - hex_prism(5, 3.01, 3)


def guarded(guard_z=6 + 15):
    """A screw in a plate under a guard whose underside is at ``guard_z``.

    At 15 over the seat no key gets on; the screw is blocked by the guard alone.
    """
    plate = Pos(0, 0, -5) * Box(600, 200, 10) - Pos(0, 0, -5) * Cylinder(3.2, 11)
    guard = Pos(0, 0, guard_z + 5) * Box(600, 200, 10)
    return Assembly(
        [Part("plate", plate), Part("guard", guard), Part("guard_screw", socket_screw())]
    )


def check_report(sidecar, engine="mesh", **kwargs):
    return check(guarded(), Config.from_dict(sidecar), kit="full", engine=engine, **kwargs)


def checked(sidecar, engine="mesh", **kwargs):
    (result,) = check_report(sidecar, engine, **kwargs).results
    return result


def test_the_screw_is_blocked_by_its_guard_alone(engine):
    # The ground truth the states below are tried against.
    result = check_report({"fasteners": SCREW}, engine).results[0]
    assert (result.verdict, result.blockers) == (Verdict.BLOCKED, ("guard",))
    sidecar = {
        "fasteners": SCREW,
        "states": {"open": {"remove": ["guard"]}},
        "checks": {"try_states": ["open"]},
    }
    result = check_report(sidecar, engine).results[0]
    assert (result.verdict, result.state) == (Verdict.TURNS, "open")


def test_a_retry_passes_over_a_state_that_takes_the_fastener_off(engine):
    # The issue's case: guard* takes the screw off with its guard. Tried there, the
    # screw turned in guard-off.
    sidecar = {
        "fasteners": SCREW,
        "states": {"guard-off": {"remove": ["guard*"]}},
        "checks": {"try_states": ["guard-off"]},
    }
    report = check_report(sidecar, engine)
    (result,) = report.results
    assert (result.verdict, result.state, result.blockers) == (Verdict.BLOCKED, None, ("guard",))
    assert report.warnings == ()  # passed over by design, not a part its model lacks
    assert report.exit_code == 1


def test_a_later_state_that_keeps_it_is_still_tried(engine):
    sidecar = {
        "fasteners": SCREW,
        "states": {"guard-off": {"remove": ["guard*"]}, "open": {"remove": ["guard"]}},
        "checks": {"try_states": ["guard-off", "open"]},
    }
    result = checked(sidecar, engine)
    assert (result.verdict, result.state) == (Verdict.TURNS, "open")


def test_a_state_takes_it_off_by_its_base_s_remove():
    # Its base takes the guard off and the screw with it: tried there, it would turn.
    sidecar = {
        "fasteners": SCREW,
        "states": {"bare": {"remove": ["guard*"]}, "deep": {"base": "bare"}},
        "checks": {"try_states": ["deep"]},
    }
    assert checked(sidecar).verdict is Verdict.BLOCKED
    sidecar["states"]["bare"]["remove"] = ["guard"]
    assert checked(sidecar).state == "deep"  # the guard alone off: tried there, and turns


def test_a_state_with_its_own_model_that_takes_it_off_is_passed_over():
    # Its model has the guard swung clear: the screw would turn there, but the state
    # takes it off.
    swung = guarded(guard_z=300)
    sidecar = {
        "fasteners": SCREW,
        "states": {"swung": {"model": "swung.step", "remove": ["guard_screw"]}},
        "checks": {"try_states": ["swung"]},
    }
    assert checked(sidecar, models={"swung.step": swung}).verdict is Verdict.BLOCKED
    sidecar["states"]["swung"].pop("remove")
    result = checked(sidecar, models={"swung.step": swung})
    assert (result.verdict, result.state) == (Verdict.TURNS, "swung")


def test_the_reason_names_the_glob_that_takes_it_off():
    sidecar = {
        "fasteners": [{**SCREW[0], "state": "guard-off"}],
        "states": {"guard-off": {"remove": ["guard", "*_screw"]}},
    }
    assert checked(sidecar).reason == (
        "its own state 'guard-off' takes it off (remove glob '*_screw'), "
        "so it can't be reached there"
    )


def test_a_fastener_whose_own_state_takes_it_off_is_not_covered(engine):
    sidecar = {
        "fasteners": [{**SCREW[0], "state": "guard-off"}],
        "states": {"guard-off": {"remove": ["guard*"]}, "open": {"remove": ["guard"]}},
        "checks": {"try_states": ["open"]},  # a retry doesn't make a sidecar mistake right
    }
    report = check_report(sidecar, engine)
    (result,) = report.results
    assert (result.verdict, result.reason, result.state) == (
        Verdict.NOT_COVERED,
        OFF,
        "guard-off",
    )
    assert report.exit_code == 2


def test_a_default_state_that_takes_it_off_leaves_it_not_covered():
    sidecar = {
        "fasteners": SCREW,
        "states": {"guard-off": {"remove": ["guard*"]}},
        "checks": {"default_state": "guard-off"},
    }
    result = checked(sidecar)
    assert (result.verdict, result.reason) == (Verdict.NOT_COVERED, OFF)
    # Given for the run, as --state gives it, the same.
    no_default = {"fasteners": SCREW, "states": sidecar["states"]}
    assert checked(no_default, state="guard-off").reason == OFF


def test_a_fastener_kept_by_its_own_state_is_tried_there():
    # Its guard off, the screw kept: its own state, tried, turns.
    sidecar = {
        "fasteners": [{**SCREW[0], "state": "open"}],
        "states": {"open": {"remove": ["guard"]}},
    }
    result = checked(sidecar)
    assert (result.verdict, result.state) == (Verdict.TURNS, "open")


# ---------------------------------------------------------------------------
# A plug.
# ---------------------------------------------------------------------------


def plugged():
    """A plug in its jack on a board, and a lid across its way out at z = 28."""
    jack = Pos(0, 0, 5) * Box(20, 12, 10) - Pos(0, 0, 6.5) * Box(16, 8, 7.01)
    return Assembly(
        [
            Part("board", Pos(0, 0, -1) * Box(200, 100, 2)),
            Part("jack", jack),
            Part("plug", Pos(0, 0, 13) * Box(16, 8, 20)),
            Part("lid", Pos(0, 0, 29) * Box(60, 60, 2)),
        ]
    )


def pulled(states, engine="mesh", **rule):
    sidecar = {"connectors": [{"parts": "plug", **rule}], "states": states}
    if "state" not in rule:
        sidecar["checks"] = {"try_states": list(states)}
    report = check(plugged(), Config.from_dict(sidecar), engine=engine)
    (result,) = report.connectors.results
    return result, report


@pytest.mark.parametrize(
    ("states", "verdict", "state"),
    [
        ({"open": {"remove": ["lid"]}}, ConnectorVerdict.UNPLUGS, "open"),
        ({"off": {"remove": ["lid", "plug"]}}, ConnectorVerdict.STUCK, None),
        (
            {"off": {"remove": ["lid", "plug"]}, "open": {"remove": ["lid"]}},
            ConnectorVerdict.UNPLUGS,
            "open",
        ),
    ],
)
def test_a_plug_is_not_pulled_in_a_state_that_takes_it_off(engine, states, verdict, state):
    result, report = pulled(states, engine)
    assert (result.verdict, result.state) == (verdict, state)
    assert report.warnings == ()


def test_a_plug_whose_own_state_takes_it_off_is_not_covered(engine):
    result, report = pulled({"off": {"remove": ["lid", "plu?"]}}, engine, state="off")
    assert (result.verdict, result.state) == (ConnectorVerdict.NOT_COVERED, "off")
    assert result.reason == (
        "its own state 'off' takes it off (remove glob 'plu?'), so it can't be reached there"
    )
    assert report.exit_code == 2
