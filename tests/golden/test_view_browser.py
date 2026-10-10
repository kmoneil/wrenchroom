"""M5's exit test, in the page itself: open the bench report, select each blocked
and stuck cell, and see it red with its blockers highlighted.

Two ways in. Node runs the page's own scripts (three.js and viewer.js) against a
small stand-in for the DOM: three's scene graph is real, so every material's
colour, opacity and visibility can be read, but nothing is drawn. Headless
Chrome opens the file as a person would and draws it with WebGL; the viewer
writes what it drew into #drawn, and a screenshot shows the colours on screen.

Neither tool is a Python dependency. Each test skips with its reason when its
tool is missing or can't start, except under CI (the CI variable set), where
that is a failure: the gate must not pass by skipping.
"""

import html
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from bench import FINAL_COUNTS, check_bench

from wrenchroom.view import COLOURS, html_text, view_data

HARNESS = Path(__file__).parent / "viewer_harness.cjs"
IN_CI = bool(os.environ.get("CI"))

#: Where Chrome or Chromium lives, by platform; WRENCHROOM_CHROME overrides.
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
CHROME_MAC = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _unavailable(reason):
    if IN_CI:
        pytest.fail(f"{reason}: CI must run this test")
    pytest.skip(reason)


#: When set (CI sets it), the bench report and the screenshots are copied here
#: for the job to upload: a person can open the report, or look at what Chrome drew.
ARTIFACTS = os.environ.get("WRENCHROOM_ARTIFACTS")


def _keep(path, name):
    if ARTIFACTS:
        Path(ARTIFACTS).mkdir(parents=True, exist_ok=True)
        shutil.copy(path, Path(ARTIFACTS) / name)


@pytest.fixture(scope="module")
def bench_page(bench_dir, tmp_path_factory):
    report = check_bench(bench_dir)
    path = tmp_path_factory.mktemp("view") / "bench.html"
    path.write_text(html_text(report), encoding="utf-8")
    _keep(path, "bench.html")
    return path, view_data(report)


def _failing(view):
    return [f for f in view["fasteners"] if f["verdict"] in {"blocked", "stuck"}]


def _hash(name):
    return "#" + urllib.parse.quote(name, safe="")


def _assert_drawn_as_decided(record, view, index):
    """One selection, as drawn: the fastener red, its blockers and only those
    highlighted and opaque, its tool positions drawn, the right state's parts."""
    entry = view["fasteners"][index]
    assert record["ready"], record
    assert record["selected"] == index
    assert record["isolated"] is None
    assert record["view"] == entry["view"]
    colours = {part: (colour, opacity) for part, colour, opacity in record["parts"]}
    assert set(colours) == set(view["views"][entry["view"]]["parts"])
    blocker = COLOURS["blocker"]
    assert {p for p, (colour, _) in colours.items() if colour == blocker} == set(entry["highlight"])
    ghosted = [o for p, (c, o) in colours.items() if c == COLOURS["part"] and p != entry["part"]]
    assert ghosted
    for part in entry["highlight"]:
        assert colours[part][1] >= 0.5  # plainly there...
        assert colours[part][1] > 3 * max(ghosted)  # ...and well above the ghosted rest
    assert colours[entry["part"]] == (COLOURS["fails"], 1)
    if any(a["probes"] for a in entry["attempts"]) or entry["way_out"] is not None:
        assert record["tools"]["hit"] > 0
    else:  # nothing in its joint turns, so no tool was tried (#134): none drawn
        assert record["tools"] == {"hit": 0, "clear": 0}


# ---------------------------------------------------------------------------
# Node: the page's scripts, three's real scene graph, no drawing.
# ---------------------------------------------------------------------------


def _node(page, arg):
    """The viewer's states for one load (a hash) or a click-through (--walk)."""
    node = shutil.which("node")
    if node is None:
        _unavailable("node is not installed")
    done = subprocess.run(  # noqa: S603  (a resolved path and our own files; no shell)
        [node, str(HARNESS), str(page), arg],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, (done.returncode, done.stderr)
    return json.loads(done.stdout)


def test_the_harness_ends_a_script_as_a_browser_does(bench_page, tmp_path):
    # A browser ends a script at "</script" in any case, whatever follows it up to
    # ">" (CodeQL's js/bad-tag-filter). Written that way, the page reads the same.
    # No "</script>" can sit inside a script's body: it would end it there too.
    page, _ = bench_page
    text = page.read_text(encoding="utf-8")
    assert text.count("</script>") == 3  # three.js and viewer.js, and the data
    variant = tmp_path / "variant.html"
    variant.write_text(
        text.replace("</script>", "</SCRIPT >", 1).replace("</script>", '</script x="y">'),
        encoding="utf-8",
    )
    assert _node(variant, "") == _node(page, "")


def test_every_failure_is_drawn_red_with_its_blockers_in_node(bench_page):
    page, view = bench_page
    failing = _failing(view)
    assert len(failing) == FINAL_COUNTS["blocked"] + FINAL_COUNTS["stuck"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        loads = list(pool.map(lambda f: _node(page, _hash(f["name"]))[0], failing))
    for entry, load in zip(failing, loads, strict=True):
        index = view["fasteners"].index(entry)
        assert load["drawn"]["webgl"] is False  # Node has none, and the page says so
        _assert_drawn_as_decided(load["drawn"], view, index)
        assert load["panel"]["detail_hidden"] is False
        assert load["panel"]["list_hidden"] is True
        assert load["panel"]["headline"] == entry["headline"]
        tried = [a["text"] for a in entry["attempts"]] or ["None: nothing was tried."]  # #134's
        assert load["panel"]["attempts"] == tried
        if entry["in_way"]:
            assert load["panel"]["in_way"].endswith(", ".join(entry["in_way"]))
        else:  # nothing in its joint turns: nothing is in its way, and no line says so
            assert load["panel"]["in_way"] is None


def test_the_panel_lists_the_tools_the_report_needs_in_node(bench_page):
    """M8: the tools list in the side panel, a line a tool, then those needing none."""
    page, view = bench_page
    (load,) = _node(page, "")
    tools = view["tools"]
    assert load["panel"]["tools_summary"] == tools["header"]
    lines = [
        f"{use['tool']} x{use['count']}" + (f" {'; '.join(use['said'])}" if use["said"] else "")
        for use in tools["uses"]
    ]
    assert load["panel"]["tools"] == [*lines, *tools["apart"]]
    assert len(tools["uses"]) > 30  # a vacuity guard: the bench needs many tools
    assert "spanner-13 x31 2 at once on a joint" in load["panel"]["tools"]
    assert load["panel"]["tools"][-1].startswith("blocked, once reached: hex-key-1.5 x1, ")


def test_the_overview_colours_every_fastener_by_its_verdict_in_node(bench_page):
    # And each plug by its own (M9): pull_shelf's stuck, red; the rest come off, green.
    page, view = bench_page
    (load,) = _node(page, "")
    record = load["drawn"]
    assert record["selected"] is None
    assert record["view"] == view["overview"]
    by_part = {part: colour for part, colour, _ in record["parts"]}
    colour_of = {f["name"]: f["colour"] for f in view["fasteners"]}
    colour_of |= {p["name"]: p["colour"] for p in view["connectors"]["found"]}
    assert {p["name"]: p["colour"] for p in view["connectors"]["found"]} == {
        "pull_shelf_plug": COLOURS["fails"],
        **{f"pull_{cell}_plug": COLOURS["turns"] for cell in ("cable", "latch", "open", "tight")},
        # byname's two, found by their names, "plug" first in each (issue #157).
        "byname_plug_motor": COLOURS["turns"],
        "byname_plug_fan_2": COLOURS["turns"],
    }
    assert set(by_part) == set(view["views"][view["overview"]]["parts"])
    for index, colour in by_part.items():
        part = view["parts"][index]
        owner = part["owner"] or part["name"]  # a piece is coloured as its fastener
        assert colour == colour_of.get(owner, COLOURS["part"]), part["name"]
    assert record["tools"] == {"hit": 0, "clear": 0}
    assert load["panel"]["fasteners"] == len(view["fasteners"]) == FINAL_COUNTS["fasteners"]
    assert load["panel"]["detail_hidden"] is True


@pytest.mark.parametrize(
    ("name", "state", "absent"),
    [("state_lever_screw", "lever-up", None), ("state_lid_screw", "lid-off", "state_lid_lid")],
)
def test_a_fastener_reached_in_another_state_is_drawn_in_it_in_node(
    bench_page, name, state, absent
):
    page, view = bench_page
    (load,) = _node(page, _hash(name))
    record = load["drawn"]
    index = [f["name"] for f in view["fasteners"]].index(name)
    entry = view["fasteners"][index]
    assert record["selected"] == index
    assert view["views"][entry["view"]]["state"] == state
    assert record["view"] == entry["view"] != view["overview"]
    drawn = {part for part, _, _ in record["parts"]}
    assert drawn == set(view["views"][entry["view"]]["parts"])
    assert drawn != set(view["views"][view["overview"]]["parts"])
    names = {view["parts"][part]["name"] for part in drawn}
    if absent:
        assert absent not in names
    colours = {part: colour for part, colour, _ in record["parts"]}
    assert colours[entry["part"]] == COLOURS["elsewhere"]
    assert record["tools"]["clear"] > 0


def test_a_fastener_s_piece_is_drawn_as_it_in_node(bench_page):
    # Issue #28: one_part_lock's nut is two solids, the nut and its dome. Both are
    # painted as the fastener, selected or not; the bench's other parts are not.
    page, view = bench_page
    name = "one_part_lock_nut"
    index = [f["name"] for f in view["fasteners"]].index(name)
    entry = view["fasteners"][index]
    piece = [p["name"] for p in view["parts"]].index(f"{name}#2")
    for load in (_node(page, _hash(name))[0], _node(page, "")[0]):
        drawn = {part: (colour, opacity) for part, colour, opacity in load["drawn"]["parts"]}
        assert drawn[piece] == drawn[entry["part"]]
        assert drawn[piece][0] == entry["colour"]
    selected = {part: opacity for part, _, opacity in _node(page, _hash(name))[0]["drawn"]["parts"]}
    assert selected[piece] == 1  # not ghosted as another part would be


def test_an_unknown_hash_shows_everything_and_says_so_in_node(bench_page):
    page, _ = bench_page
    (load,) = _node(page, "#no_such_fastener")
    assert load["drawn"]["selected"] is None
    assert load["panel"]["status"] == "No fastener named no_such_fastener."


def test_clicking_through_the_list_selects_each_in_turn_in_node(bench_page):
    page, view = bench_page
    walk = _node(page, "--walk")
    count = len(view["fasteners"])
    assert [step["drawn"]["selected"] for step in walk[: count + 1]] == [None, *range(count)]
    last = view["fasteners"][-1]
    isolating = walk[count + 1 : -1]
    assert [step["drawn"]["isolated"] for step in isolating] == list(range(len(last["attempts"])))
    for step, attempt in zip(isolating, last["attempts"], strict=True):
        drawn = step["drawn"]["tools"]
        pieces = sum(len(p["s"]) for p in attempt["probes"])
        assert drawn["hit"] + drawn["clear"] == pieces
    assert walk[-1]["drawn"]["selected"] is None


@pytest.fixture(scope="module")
def clash_page(tmp_path_factory):
    """A bracket 10 on a side, 1 into a frame 20 on a side, and a block apart: checked
    for clashes, 100 mm^3 between the two (M8)."""
    from build123d import Box, Pos  # noqa: PLC0415  (only this fixture builds geometry)

    from wrenchroom.assembly import Assembly, Part  # noqa: PLC0415
    from wrenchroom.checker import check  # noqa: PLC0415
    from wrenchroom.config import Config  # noqa: PLC0415

    parts = [
        Part("frame", Pos(14, 0, 0) * Box(20, 20, 20)),
        Part("bracket", Box(10, 10, 10)),
        Part("apart", Pos(0, 60, 0) * Box(10, 10, 10)),
    ]
    report = check(Assembly(parts), Config(), clashes=True)
    path = tmp_path_factory.mktemp("clash") / "clash.html"
    path.write_text(html_text(report), encoding="utf-8")
    _keep(path, "clash.html")
    return path, view_data(report)


def test_the_clashes_are_listed_in_node(clash_page):
    page, _ = clash_page
    (load,) = _node(page, "")
    panel = load["panel"]
    assert (panel["clash_list_hidden"], panel["clash_hidden"]) == (False, True)
    assert panel["clashes_summary"] == "1 clash (overlap over 0.05 mm^3)"
    assert panel["clashes"] == ["bracket into frame100.0 mm^3"]  # the name, then the volume
    assert (load["drawn"]["clash"], load["drawn"]["overlaps"]) == (None, 0)


def test_a_clash_is_drawn_with_its_two_parts_and_its_overlap_in_node(clash_page):
    page, view = clash_page
    (load,) = _node(page, "#clash:0")
    drawn, panel = load["drawn"], load["panel"]
    assert (drawn["clash"], drawn["selected"], drawn["overlaps"]) == (0, None, 1)
    names = [part["name"] for part in view["parts"]]
    colours = {names[part]: (colour, opacity) for part, colour, opacity in drawn["parts"]}
    assert colours["bracket"] == colours["frame"] == (COLOURS["blocker"], 0.7)
    assert colours["apart"][1] < 0.5  # ghosted
    assert (panel["list_hidden"], panel["detail_hidden"], panel["clash_hidden"]) == (
        True,
        True,
        False,
    )
    assert panel["clash"] == ["bracket into frame", "100.0 mm^3 drawn into each other.", None, None]


def test_a_clash_hash_naming_no_clash_shows_everything_in_node(clash_page):
    page, _ = clash_page
    (load,) = _node(page, "#clash:7")
    assert (load["drawn"]["clash"], load["drawn"]["selected"]) == (None, None)
    assert load["panel"]["status"] == "No fastener named clash:7."


def test_a_page_with_no_clashes_looked_for_lists_none_in_node(bench_page):
    page, _ = bench_page
    (load,) = _node(page, "#clash:0")
    assert load["panel"]["clash_list_hidden"] is True
    assert load["drawn"]["clash"] is None


@pytest.fixture(scope="module")
def plug_page(tmp_path_factory):
    """Two plugs in their shrouds, checked with hand room (M9): one under a bar 4 over
    it, stuck; one hemmed in all round, no room for fingers. The bar is narrow, so the
    plug under it shows from the view's side."""
    from build123d import Box, Pos  # noqa: PLC0415  (only this fixture builds geometry)

    from wrenchroom.assembly import Assembly, Part  # noqa: PLC0415
    from wrenchroom.checker import check  # noqa: PLC0415
    from wrenchroom.config import Config  # noqa: PLC0415

    def shroud(x):
        return Pos(x, 0, 5) * Box(20, 12, 10) - Pos(x, 0, 6.5) * Box(16, 8, 7.01)

    parts = [
        Part("board", Pos(50, 0, -1) * Box(300, 100, 2)),
        Part("a_jack", shroud(0)),
        Part("a_plug", Pos(0, 0, 13) * Box(16, 8, 20)),
        Part("bar", Pos(0, 0, 30) * Box(80, 10, 6)),
        Part("b_jack", shroud(100)),
        Part("b_plug", Pos(100, 0, 13) * Box(16, 8, 20)),
        Part("left", Pos(85, 0, 15) * Box(10, 12, 30)),
        Part("right", Pos(115, 0, 15) * Box(10, 12, 30)),
        Part("near", Pos(100, -12, 15) * Box(60, 10, 30)),
        Part("far", Pos(100, 12, 15) * Box(60, 10, 30)),
    ]
    sidecar = {"connectors": [{"parts": "*_plug"}], "checks": {"hand_room": True}}
    report = check(Assembly(parts), Config.from_dict(sidecar))
    path = tmp_path_factory.mktemp("plug") / "plug.html"
    path.write_text(html_text(report), encoding="utf-8")
    _keep(path, "plug.html")
    return path, view_data(report)


def test_the_plugs_are_listed_and_coloured_in_node(plug_page):
    page, view = plug_page
    (load,) = _node(page, "")
    panel, drawn = load["panel"], load["drawn"]
    assert (panel["plug_list_hidden"], panel["plug_hidden"]) == (False, True)
    assert panel["plugs_summary"] == (
        "2 connectors: 0 unplug, 1 stuck, 1 no grip, 0 no latch access, 0 not covered"
    )
    assert panel["plugs"] == ["a_plugstuck", "b_plugno-grip"]  # the name, then the verdict
    assert (drawn["plug"], drawn["tools"]) == (None, {"hit": 0, "clear": 0})
    # In the overview each plug is drawn in its verdict's colour, as a fastener is.
    names = [part["name"] for part in view["parts"]]
    colours = {names[part]: colour for part, colour, _ in drawn["parts"]}
    assert colours["a_plug"] == colours["b_plug"] == COLOURS["fails"]
    assert colours["bar"] == COLOURS["part"]


def test_a_stuck_plug_is_drawn_where_it_stops_in_node(plug_page):
    page, view = plug_page
    (load,) = _node(page, "#plug:0")
    drawn, panel = load["drawn"], load["panel"]
    assert (drawn["plug"], drawn["selected"], drawn["clash"]) == (0, None, None)
    assert drawn["tools"] == {"hit": 1, "clear": 0}  # itself at the end of its pull
    names = [part["name"] for part in view["parts"]]
    colours = {names[part]: (colour, opacity) for part, colour, opacity in drawn["parts"]}
    assert colours["a_plug"] == (COLOURS["fails"], 1)
    assert colours["bar"] == (COLOURS["blocker"], 0.7)
    assert colours["a_jack"] == (COLOURS["part"], 1)  # its receptacle, as it is
    assert colours["b_plug"][1] < 0.5  # ghosted
    assert (panel["list_hidden"], panel["detail_hidden"], panel["plug_hidden"]) == (
        True,
        True,
        False,
    )
    assert panel["plug"] == ["a_plug", "stuck", None, "In its way out: bar", None]


def test_a_plug_with_no_room_for_fingers_is_drawn_with_every_finger_tried_in_node(plug_page):
    page, _ = plug_page
    (load,) = _node(page, "#plug:1")
    assert load["drawn"]["tools"] == {"hit": 24, "clear": 1}  # 12 pairs, and its pull
    assert load["panel"]["plug"][3] == "In the fingers' way: far, near, left, right"


def test_a_plug_hash_naming_no_plug_shows_everything_in_node(plug_page):
    page, _ = plug_page
    (load,) = _node(page, "#plug:5")
    assert (load["drawn"]["plug"], load["drawn"]["selected"]) == (None, None)
    assert load["panel"]["status"] == "No fastener named plug:5."


def test_a_page_with_no_plugs_lists_none_in_node(clash_page):
    page, _ = clash_page
    (load,) = _node(page, "#plug:0")
    assert load["panel"]["plug_list_hidden"] is True
    assert load["drawn"]["plug"] is None


# ---------------------------------------------------------------------------
# Chrome: the page opened from disk and drawn with WebGL.
# ---------------------------------------------------------------------------


def _chrome():
    chosen = os.environ.get("WRENCHROOM_CHROME")
    if chosen:
        return chosen
    for name in CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    if Path(CHROME_MAC).exists():
        return CHROME_MAC
    _unavailable("no Chrome or Chromium found (set WRENCHROOM_CHROME)")
    return None


#: How long one Chrome run may take, s, before the test gives up on it.
CHROME_SECONDS = 120

#: A PNG's last chunk: a screenshot ending in it has been written whole.
PNG_END = b"IEND\xaeB`\x82"


def _chrome_run(chrome, profile, url, action, finished):
    """Run headless Chrome until ``finished(stdout so far)`` says its work is
    done, then stop it; returns (stdout, stderr, finished).

    Chrome on a macOS runner can write its whole result and then never exit
    (seen in CI on 2026-10-06, with CVDisplayLink errors on stderr), so the test
    waits for the result, not for the exit.
    """
    argv = [
        chrome,
        "--headless=new",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        f"--user-data-dir={profile}",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--window-size=1280,800",
        "--hide-scrollbars",
        "--virtual-time-budget=10000",
        *action,
        url,
    ]
    if sys.platform.startswith("linux"):
        argv.insert(1, "--no-sandbox")  # hosted Linux runners refuse Chrome's sandbox
    out = bytearray()
    done = False
    with tempfile.TemporaryFile() as err:
        # S603: a resolved path and our own files; no shell.
        with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=err) as process:  # noqa: S603
            assert process.stdout is not None
            deadline = time.monotonic() + CHROME_SECONDS
            while not done and time.monotonic() < deadline:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                chunk = os.read(process.stdout.fileno(), 1 << 16) if ready else b""
                out += chunk
                done = finished(bytes(out))
                if ready and not chunk:  # end of output: Chrome has exited
                    break
            if process.poll() is None:
                process.kill()
        err.seek(0)
        stderr = err.read().decode(errors="replace")
    return out.decode(errors="replace"), stderr, done


def _dump(chrome, tmp_path, page, hash_, attempt=1):
    """What the page says it drew at a hash: (record, None), or (None, what went wrong)."""
    profile = tmp_path / f"profile{abs(hash(hash_))}-{attempt}"
    started = time.monotonic()
    stdout, stderr, done = _chrome_run(
        chrome, profile, page.as_uri() + hash_, ["--dump-dom"], lambda out: b"</html>" in out
    )
    found = re.search(r'<output id="drawn"[^>]*>(.*?)</output>', stdout, flags=re.DOTALL)
    if done and found is not None:
        return json.loads(html.unescape(found.group(1))), None
    seconds = time.monotonic() - started
    if done:
        what = f"the page came without its #drawn record after {seconds:.0f} s"
    elif seconds >= CHROME_SECONDS:
        what = f"no whole page in {CHROME_SECONDS} s ({len(stdout)} characters of it)"
    else:
        what = f"Chrome stopped after {seconds:.0f} s, {len(stdout)} characters into the page"
    return None, f"try {attempt}: {what}; its stderr ends:\n{stderr[-1500:]}"


def _drawn(chrome, tmp_path, page, hashes):
    """Each hash's (record, error), four Chromes at a time.

    On a hosted macOS runner, one of 22 Chromes drawing in software four at a time
    now and then delivers no page, its stderr full of GPU process errors (issue
    #113). A run that delivers none is tried once more, alone, after the rest: a
    page that doesn't draw fails both times, and says so twice.
    """
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(lambda hash_: _dump(chrome, tmp_path, page, hash_), hashes))
    if all(record is None for record, _ in runs):
        _unavailable(f"Chrome would not open the page: {runs[0][1]}")
    for index, (record, error) in enumerate(runs):
        if record is None:
            again, second = _dump(chrome, tmp_path, page, hashes[index], attempt=2)
            runs[index] = (again, None if again is not None else f"{error}\n{second}")
    return runs


def test_every_failure_is_drawn_red_with_its_blockers_in_chrome(bench_page, tmp_path):
    chrome = _chrome()
    page, view = bench_page
    failing = _failing(view)
    runs = _drawn(chrome, tmp_path, page, [_hash(f["name"]) for f in failing])
    for entry, (record, error) in zip(failing, runs, strict=True):
        assert record is not None, error
        assert record["webgl"] is True, record["error"]
        _assert_drawn_as_decided(record, view, view["fasteners"].index(entry))


#: A page as Chrome dumps it once the viewer has drawn.
DRAWN_PAGE = '<html><output id="drawn">{&quot;ready&quot;: true}</output></html>'


def _stand_in_chrome(monkeypatch, pages):
    """Chrome stood in for: each run at a hash gives that hash's next (page, done).

    Returns the (hash, profile) of each run, in the order they were run.
    """
    runs = []

    def run(chrome, profile, url, action, finished):
        hash_ = "#" + url.partition("#")[2]
        runs.append((hash_, profile))
        page, done = pages[hash_].pop(0)
        return page, "ERROR: Invalid mailbox.", done

    monkeypatch.setattr(sys.modules[__name__], "_chrome_run", run)
    return runs


def test_a_run_that_delivers_no_page_is_tried_once_more_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(sys.modules[__name__], "IN_CI", True)  # nothing may skip
    runs = _stand_in_chrome(
        monkeypatch,
        {
            "#a": [("<html><body>", False), (DRAWN_PAGE, True)],
            "#b": [(DRAWN_PAGE, True)],
            "#c": [("<html></html>", True), ("<html>", False)],
        },
    )
    drawn = _drawn("chrome", tmp_path, tmp_path / "bench.html", ["#a", "#b", "#c"])
    assert drawn[:2] == [({"ready": True}, None), ({"ready": True}, None)]
    record, error = drawn[2]
    assert record is None
    assert error.startswith("try 1: the page came without its #drawn record after 0 s")
    assert "try 2: Chrome stopped after 0 s, 6 characters into the page" in error
    assert error.count("Invalid mailbox") == 2  # each try's stderr, said
    assert sorted(hash_ for hash_, _ in runs[:3]) == ["#a", "#b", "#c"]
    assert [hash_ for hash_, _ in runs[3:]] == ["#a", "#c"]  # again, after the rest
    # A killed Chrome can leave its profile locked: a second try gets its own.
    assert len({profile for _, profile in runs}) == len(runs)


def test_a_run_out_of_time_says_how_much_page_it_had(monkeypatch, tmp_path):
    _stand_in_chrome(monkeypatch, {"#a": [("<html><body>", False)]})
    monkeypatch.setattr(sys.modules[__name__], "CHROME_SECONDS", 0)
    record, error = _dump("chrome", tmp_path, tmp_path / "bench.html", "#a")
    assert record is None
    assert error.startswith("try 1: no whole page in 0 s (12 characters of it)")


def test_a_chrome_that_opens_no_page_at_all_is_unavailable(monkeypatch, tmp_path):
    runs = _stand_in_chrome(monkeypatch, {"#a": [("", False)], "#b": [("", False)]})
    monkeypatch.setattr(sys.modules[__name__], "IN_CI", False)
    with pytest.raises(pytest.skip.Exception, match="Chrome would not open the page"):
        _drawn("chrome", tmp_path, tmp_path / "bench.html", ["#a", "#b"])
    assert sorted(hash_ for hash_, _ in runs) == ["#a", "#b"]  # no Chrome to try again
    monkeypatch.setattr(sys.modules[__name__], "IN_CI", True)
    _stand_in_chrome(monkeypatch, {"#a": [("", False)]})
    with pytest.raises(pytest.fail.Exception, match="CI must run this test"):
        _drawn("chrome", tmp_path, tmp_path / "bench.html", ["#a"])


#: The panel's width, px (viewer.css): its legend and list have swatches of every
#: colour, so only the 3D view, left of it, is counted.
PANEL_PX = 380


def _magenta_and_red(png):
    """Pixels of the blocker's hue and of the failure's in the 3D view, by hue band.

    Shading changes a colour's brightness, not its hue; the bands are wide
    enough to take a translucent tool position drawn over a part, which pulls
    red toward the tool's orange and magenta toward red.
    """
    from PIL import Image  # noqa: PLC0415  (only this test reads an image)

    with Image.open(png) as image:
        hsv = np.asarray(image.convert("HSV"), dtype=float)
    hsv = hsv[:, : hsv.shape[1] - PANEL_PX - 10]
    degrees = hsv[..., 0] * 360 / 255
    coloured = (hsv[..., 1] >= 100) & (hsv[..., 2] >= 60)  # not greys, edges or shade
    magenta = coloured & (degrees >= 280) & (degrees <= 335)
    red = coloured & ((degrees <= 15) | (degrees >= 345))
    return int(magenta.sum()), int(red.sum())


def _screenshot(chrome, tmp_path, page, hash_):
    shot = tmp_path / f"shot{abs(hash(hash_))}.png"
    _, stderr, done = _chrome_run(
        chrome,
        tmp_path / f"shot-profile{abs(hash(hash_))}",
        page.as_uri() + hash_,
        [f"--screenshot={shot}"],
        lambda _: shot.exists() and shot.read_bytes().endswith(PNG_END),
    )
    if not done:
        _unavailable(f"Chrome would not take a screenshot: {stderr[-2000:]}")
    # Kept under a name an artifact can carry (no colon: #clash:0), each page's apart.
    name = re.sub(r'[":<>|*?\r\n]', "-", hash_.lstrip("#")) or "overview"
    _keep(shot, f"{name}.png" if page.stem == "bench" else f"{page.stem}-{name}.png")
    return _magenta_and_red(shot)


def test_failures_show_red_and_their_blockers_magenta_on_screen(bench_page, tmp_path):
    chrome = _chrome()
    page, _ = bench_page
    shots = {
        hash_: _screenshot(chrome, tmp_path, page, hash_)
        for hash_ in ("", "#key_wall_near_screw", "#gland_rib_gland")
    }
    # The overview: nothing is highlighted until a fastener is chosen.
    assert shots[""][0] == 0, shots
    # A screw under a wall: from above, the highlighted wall fills the frame.
    assert shots["#key_wall_near_screw"][0] > 2000, shots
    # A gland beside a rib: the gland red, the rib in its way magenta, both in view.
    # The open end's fan of 24 positions, drawn over it, hides most of the low rib,
    # and the view frames the whole fan: since the spanners took makers' lengths
    # (issue #49; the 24 mm is 336.6 where the formula said 261) it frames a longer
    # one, and draws the rib and gland smaller. CI measured 39 magenta and 386 to 388
    # red pixels on Linux and macOS (2026-10-07; 129 and 617 before); the floors keep
    # about 2.5 times margin under those.
    assert shots["#gland_rib_gland"][0] > 15, shots
    assert shots["#gland_rib_gland"][1] > 150, shots


def test_a_clash_shows_its_overlap_red_and_its_parts_magenta_on_screen(clash_page, tmp_path):
    # The bracket and frame see-through magenta, the overlap between them red and
    # drawn over them; the overview has neither until a clash is chosen. CI measured
    # 412608 magenta and 101941 red pixels on Linux and macOS alike (2026-10-09); drawn
    # first, under the parts, the overlap was 5 red pixels. The floors keep about 2.5
    # times margin under those.
    chrome = _chrome()
    page, _ = clash_page
    overview = _screenshot(chrome, tmp_path, page, "")
    chosen = _screenshot(chrome, tmp_path, page, "#clash:0")
    assert overview == (0, 0), overview
    assert chosen[0] > 160_000, chosen
    assert chosen[1] > 40_000, chosen


def test_a_stuck_plug_shows_red_and_what_stops_it_magenta_on_screen(plug_page, tmp_path):
    # The overview draws the stuck plug red under its bar (the other hides in its
    # channel) and nothing magenta; chosen, the bar over it is magenta. Under a shelf
    # instead, both were hidden, and the shelf's magenta tinted the plug (2026-10-09).
    chrome = _chrome()
    page, _ = plug_page
    overview = _screenshot(chrome, tmp_path, page, "")
    chosen = _screenshot(chrome, tmp_path, page, "#plug:0")
    assert overview[0] == 0, overview
    assert overview[1] > 50, overview
    assert chosen[0] > 2000, chosen
