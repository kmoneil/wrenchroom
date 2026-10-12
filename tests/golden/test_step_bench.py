"""The whole bench at another step: every swing in it is sampled at the step it records.

Issue #184 has a report say the step it was run at. That is only worth saying if every
tool's swing, each way, took it: one that fell back to the default would make the
record wrong for its fasteners, and nothing in a report run at 15 could tell.
"""

from bench import check_bench

from wrenchroom.tools import sweep
from wrenchroom.tools.sweep import checked_step

RIM = "a fingertip on its rim"

#: Tools the bench swings, and each way: the kit's and the sidecar's own two.
SWUNG = {
    ("hex-key", "short leg in"),
    ("hex-key", "long leg in"),
    ("torx-key", "short leg in"),
    ("ball-end-key", "ball end"),
    ("spanner", "ring"),
    ("spanner", "open end"),
    ("socket", "socket on ratchet"),
    ("socket", "socket"),  # on an extension
    ("hand", RIM),
    ("stubby-key", "short leg in"),
    ("short-ring", "ring"),
}


def test_every_swing_on_the_bench_is_sampled_at_the_step_asked(bench_dir, monkeypatch):
    sampled = []

    def spy(step_deg):
        sampled.append(step_deg)
        return checked_step(step_deg)

    monkeypatch.setattr(sweep, "checked_step", spy)
    report = check_bench(bench_dir, step_deg=30.0)
    assert set(sampled) == {30.0}
    assert report.step_deg == 30.0
    assert report.to_json_dict()["step_deg"] == 30.0
    # Not vacuous: hundreds of swings, by every tool the bench has that swings.
    assert len(sampled) > 500
    swung = {
        (attempt.tool.rsplit("-", 1)[0], attempt.way.split(",")[0])
        for result in report.results
        for attempt in result.attempts
        if attempt.required_deg or attempt.way == RIM
    }
    assert swung >= SWUNG
