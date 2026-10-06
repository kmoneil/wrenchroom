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
from bench import check_bench

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
    assert record["tools"]["hit"] > 0


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


def test_every_failure_is_drawn_red_with_its_blockers_in_node(bench_page):
    page, view = bench_page
    failing = _failing(view)
    assert len(failing) == 11
    with ThreadPoolExecutor(max_workers=4) as pool:
        loads = list(pool.map(lambda f: _node(page, _hash(f["name"]))[0], failing))
    for entry, load in zip(failing, loads, strict=True):
        index = view["fasteners"].index(entry)
        assert load["drawn"]["webgl"] is False  # Node has none, and the page says so
        _assert_drawn_as_decided(load["drawn"], view, index)
        assert load["panel"]["detail_hidden"] is False
        assert load["panel"]["list_hidden"] is True
        assert load["panel"]["headline"] == entry["headline"]
        assert load["panel"]["attempts"] == [a["text"] for a in entry["attempts"]]
        assert load["panel"]["in_way"].endswith(", ".join(entry["in_way"]))


def test_the_overview_colours_every_fastener_by_its_verdict_in_node(bench_page):
    page, view = bench_page
    (load,) = _node(page, "")
    record = load["drawn"]
    assert record["selected"] is None
    assert record["view"] == view["overview"]
    by_part = {part: colour for part, colour, _ in record["parts"]}
    colour_of = {f["name"]: f["colour"] for f in view["fasteners"]}
    assert set(by_part) == set(view["views"][view["overview"]]["parts"])
    for index, colour in by_part.items():
        part = view["parts"][index]
        assert colour == colour_of.get(part["name"], COLOURS["part"]), part["name"]
    assert record["tools"] == {"hit": 0, "clear": 0}
    assert load["panel"]["fasteners"] == len(view["fasteners"]) == 37
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


def _dump(chrome, tmp_path, page, hash_):
    profile = tmp_path / f"profile{abs(hash(hash_))}"
    stdout, stderr, done = _chrome_run(
        chrome, profile, page.as_uri() + hash_, ["--dump-dom"], lambda out: b"</html>" in out
    )
    found = re.search(r'<output id="drawn"[^>]*>(.*?)</output>', stdout, flags=re.DOTALL)
    if not done or found is None:
        return None, stderr[-2000:]
    return json.loads(html.unescape(found.group(1))), None


def test_every_failure_is_drawn_red_with_its_blockers_in_chrome(bench_page, tmp_path):
    chrome = _chrome()
    page, view = bench_page
    failing = _failing(view)
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(lambda f: _dump(chrome, tmp_path, page, _hash(f["name"])), failing))
    if runs[0][0] is None:
        _unavailable(f"Chrome would not open the page: {runs[0][1]}")
    for entry, (record, error) in zip(failing, runs, strict=True):
        assert record is not None, error
        assert record["webgl"] is True, record["error"]
        _assert_drawn_as_decided(record, view, view["fasteners"].index(entry))


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
    _keep(shot, f"{hash_.lstrip('#') or 'overview'}.png")
    return _magenta_and_red(shot)


def test_failures_show_red_and_their_blockers_magenta_on_screen(bench_page, tmp_path):
    chrome = _chrome()
    page, _ = bench_page
    shots = {
        hash_: _screenshot(chrome, tmp_path, page, hash_)
        for hash_ in ("", "#key_wall_near_screw", "#glands_close_a_gland")
    }
    # The overview: nothing is highlighted until a fastener is chosen.
    assert shots[""][0] == 0, shots
    # A screw under a wall: from above, the highlighted wall fills the frame.
    assert shots["#key_wall_near_screw"][0] > 2000, shots
    # Two glands too close: the chosen one red, its neighbour magenta, both in view.
    assert shots["#glands_close_a_gland"][0] > 300, shots
    assert shots["#glands_close_a_gland"][1] > 100, shots
