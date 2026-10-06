"""The HTML view: what it decides to show, that it shows where the check tested,
and that a name from the model can't get out of the page's data.

These tests read the data the page draws from (``view_data``), the page as
written (``html_text``) and the files it is built from. That the browser draws
the data as decided is tests/golden/test_view_browser.py's part.
"""

import base64
import hashlib
import html as html_lib
import importlib.util
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pytest
from build123d import Box, Compound, Pos, export_step
from click.testing import CliRunner

import wrenchroom.view
from fixture_models import screw_facing_wall, socket_screw
from wrenchroom.assembly import Assembly, Part
from wrenchroom.check import check
from wrenchroom.cli import main
from wrenchroom.config import Config
from wrenchroom.engine import ENGINES
from wrenchroom.engine.mesh import primitive_mesh
from wrenchroom.report import Report
from wrenchroom.terminal import UNSAFE, printable
from wrenchroom.view import COLOURS, LEGEND, html_text, view_data

VIEW = Path(wrenchroom.view.__file__).parent
REPO = Path(__file__).resolve().parent.parent
ESC = chr(0x1B)
RLO = chr(0x202E)

M6 = {"kind": "screw", "head": "socket", "size": "M6"}


def _checked(assembly, sidecar, engine="mesh", **kwargs):
    return check(assembly, Config.from_dict(sidecar), engine=engine, **kwargs)


def _fastener(data, name):
    (entry,) = [f for f in data["fasteners"] if f["name"] == name]
    return entry


def _part_names(data, indices):
    return [data["parts"][i]["name"] for i in indices]


# ---------------------------------------------------------------------------
# Colours and highlights.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", ENGINES)
def test_a_blocked_screw_is_red_and_highlights_its_wall(engine):
    report = _checked(screw_facing_wall(15.0), {"fasteners": [{"parts": "bolt", **M6}]}, engine)
    data = view_data(report)
    bolt = _fastener(data, "bolt")
    assert bolt["verdict"] == "blocked"
    assert bolt["colour"] == COLOURS["fails"]
    assert _part_names(data, bolt["highlight"]) == ["wall"]
    assert bolt["in_way"] == ["wall"]
    assert bolt["way_out"] is None
    # Three ways tried, each blocked at its engagement: one probe each, all hits.
    assert [a["text"] for a in bolt["attempts"]] == [
        "hex-key-5, driver straight in: blocked; hit wall",
        "hex-key-5, short leg in: blocked; hit wall",
        "hex-key-5, long leg in: blocked; hit wall",
    ]
    for attempt in bolt["attempts"]:
        assert _part_names(data, attempt["highlight"]) == ["wall"]
        assert [p["hit"] for p in attempt["probes"]] == [True]
        assert _part_names(data, attempt["probes"][0]["hits"]) == ["wall"]


@pytest.mark.parametrize("engine", ENGINES)
def test_a_screw_that_turns_is_green_and_highlights_nothing(engine):
    report = _checked(screw_facing_wall(40.0), {"fasteners": [{"parts": "bolt", **M6}]}, engine)
    data = view_data(report)
    bolt = _fastener(data, "bolt")
    assert bolt["verdict"] == "turns"
    assert bolt["colour"] == COLOURS["turns"]
    assert bolt["highlight"] == []
    assert bolt["in_way"] == []
    winning = bolt["attempts"][-1]
    assert winning["turns"]
    assert winning["text"].startswith("hex-key-5, short leg in: turns")
    # The engagement and every arm position the search proved are clear.
    assert winning["probes"]
    assert not any(p["hit"] for p in winning["probes"])


def test_every_verdict_has_its_colour_and_every_colour_its_legend_line():
    assert {key for key, _ in LEGEND} == set(COLOURS) - {"part", "background"}
    assert len(set(COLOURS.values())) == len(COLOURS)  # no two meanings share a colour
    for colour in COLOURS.values():
        assert re.fullmatch("#[0-9a-f]{6}", colour)


def _lidded():
    """A screw under a lid 15 above it: blocked with the lid on, free with it off."""
    lid = Pos(0, 0, 26 + 15 + 5) * Box(400, 400, 10)
    hose = Pos(0, 60, 30) * Box(10, 10, 10)
    return Assembly([Part("bolt", socket_screw()), Part("lid", lid), Part("hose", hose)])


LIDDED = {
    "fasteners": [{"parts": "bolt", **M6, "state": "lid-off"}],
    "states": {"lid-off": {"remove": ["lid"]}},
    "ignore": ["hose"],
}


def test_passing_in_another_state_is_amber_and_drawn_in_that_state():
    report = _checked(_lidded(), LIDDED)
    data = view_data(report)
    bolt = _fastener(data, "bolt")
    assert bolt["verdict"] == "turns"
    assert bolt["colour"] == COLOURS["elsewhere"]
    view = data["views"][bolt["view"]]
    assert view["state"] == "lid-off"
    assert "lid" not in _part_names(data, view["parts"])
    overview = data["views"][data["overview"]]
    assert overview["state"] is None
    assert set(_part_names(data, overview["parts"])) == {"bolt", "lid", "hose"}
    # The lid-off state is the same model less the lid: no part is drawn twice.
    assert len(data["parts"]) == 3


def test_a_state_the_run_takes_as_normal_is_not_amber():
    report = _checked(_lidded(), LIDDED | {"checks": {"default_state": "lid-off"}})
    data = view_data(report)
    bolt = _fastener(data, "bolt")
    assert bolt["colour"] == COLOURS["turns"]
    assert data["views"][data["overview"]]["state"] == "lid-off"
    assert bolt["view"] == data["overview"]


def test_ignored_parts_are_marked_and_fasteners_named():
    data = view_data(_checked(_lidded(), LIDDED))
    roles = {part["name"]: part["role"] for part in data["parts"]}
    assert roles == {"bolt": "fastener", "lid": "part", "hose": "ignored"}


def test_not_covered_is_grey_with_nothing_tried():
    assembly = Assembly([Part("slab_screw", Box(20, 20, 20))])
    report = _checked(assembly, {"fasteners": [{"parts": "slab*", **M6}]})
    data = view_data(report)
    entry = _fastener(data, "slab_screw")
    assert entry["verdict"] == "not-covered"
    assert entry["colour"] == COLOURS["not-covered"]
    assert entry["attempts"] == []
    assert entry["reason"] == "axis is auto but the part has no cylindrical face"


def test_a_stuck_screw_draws_its_way_out_and_highlights_what_is_in_it():
    # The screw turns (a driver fits straight in under nothing) but a beam 10
    # above the head, offset so the driver misses it, overlaps the way out.
    beam = Pos(0, 6, 26 + 10 + 2) * Box(60, 4, 4)
    sidecar = {"fasteners": [{"parts": "bolt", **M6, "length": 30}]}
    report = _checked(Assembly([Part("bolt", socket_screw()), Part("beam", beam)]), sidecar)
    (result,) = report.results
    assert result.verdict == "stuck", result
    data = view_data(report)
    bolt = _fastener(data, "bolt")
    assert bolt["colour"] == COLOURS["fails"]
    assert _part_names(data, bolt["highlight"]) == ["beam"]
    assert bolt["way_out"] is not None
    assert bolt["way_out"]["hit"]
    assert _part_names(data, bolt["way_out"]["hits"]) == ["beam"]


def test_the_list_puts_what_needs_a_person_first():
    walls = Assembly(
        [
            Part("a_bolt", socket_screw()),
            Part("b_bolt", Pos(500, 0, 0) * socket_screw()),
            Part("wall", Pos(0, 0, 26 + 15 + 5) * Box(100, 100, 10)),
        ]
    )
    data = view_data(_checked(walls, {"fasteners": [{"parts": "*_bolt", **M6}]}))
    assert [f["name"] for f in data["fasteners"]] == ["a_bolt", "b_bolt"]  # blocked first
    assert [f["verdict"] for f in data["fasteners"]] == ["blocked", "turns"]


# ---------------------------------------------------------------------------
# What is drawn is what was tested.
# ---------------------------------------------------------------------------


def _decoded(b64, dtype):
    return np.frombuffer(base64.b64decode(b64), dtype=dtype)


def test_tool_pieces_are_drawn_exactly_where_the_check_put_them():
    report = _checked(screw_facing_wall(40.0), {"fasteners": [{"parts": "bolt", **M6}]})
    (result,) = report.results
    data = view_data(report)
    attempts = _fastener(data, "bolt")["attempts"]
    compared = 0
    for attempt, drawn in zip(result.attempts, attempts, strict=True):
        assert len(attempt.probes) == len(drawn["probes"])
        for probe, entry in zip(attempt.probes, drawn["probes"], strict=True):
            matrices = _decoded(entry["m"], "<f4").reshape(-1, 3, 4)
            assert len(matrices) == len(probe.solid.primitives) == len(entry["s"])
            low, high = np.array(probe.solid.bounds()[0]), np.array(probe.solid.bounds()[1])
            points = []
            for shape_index, matrix in zip(entry["s"], matrices, strict=True):
                shape = data["shapes"][shape_index]
                vertices = _decoded(shape["p"], "<f4").reshape(-1, 3)
                placed = vertices @ matrix[:, :3].T + matrix[:, 3]
                points.append(placed)
            points = np.concatenate(points)
            # Never outside the tested solid's box by more than the polygon's
            # allowance, and reaching its far corners: the same solid, same place.
            assert np.all(points >= low - 0.05)
            assert np.all(points <= high + 0.05)
            assert np.allclose(points.min(axis=0), low, atol=0.6)
            assert np.allclose(points.max(axis=0), high, atol=0.6)
            compared += 1
    assert compared == sum(len(a.probes) for a in result.attempts) > 5


def test_a_tool_shape_is_written_once_however_often_it_is_placed():
    report = _checked(screw_facing_wall(40.0), {"fasteners": [{"parts": "bolt", **M6}]})
    data = view_data(report)
    used = [s for a in _fastener(data, "bolt")["attempts"] for p in a["probes"] for s in p["s"]]
    assert len(used) > len(set(used))  # the arm, placed at every angle, is one shape
    primitive = report.results[0].attempts[0].probes[0].solid.primitives[0]
    unit, _ = primitive_mesh(primitive, np.eye(4))
    assert unit is primitive_mesh(primitive, np.eye(4))[0]  # shared, as the view relies on


def test_part_triangles_round_trip_as_little_endian_float32():
    data = view_data(_checked(screw_facing_wall(40.0), {"fasteners": [{"parts": "bolt", **M6}]}))
    for part in data["parts"]:
        shape = data["shapes"][part["shape"]]
        vertices = _decoded(shape["p"], "<f4").reshape(-1, 3)
        triangles = _decoded(shape["i"], "<u4").reshape(-1, 3)
        assert len(triangles) > 0
        assert triangles.max() < len(vertices)
    wall = data["shapes"][data["parts"][1]["shape"]]
    vertices = _decoded(wall["p"], "<f4").reshape(-1, 3)
    assert np.allclose(vertices.min(axis=0), [-200, -200, 66], atol=1e-3)
    assert np.allclose(vertices.max(axis=0), [200, 200, 76], atol=1e-3)


# ---------------------------------------------------------------------------
# The page: names stay data, scripts are only its own, nothing loads.
# ---------------------------------------------------------------------------

HOSTILE = "</script><script>alert(1)</script><!-- " + ESC + "]0;x" + chr(7) + RLO + " &amp;"
HOSTILE_WALL = 'wall"><img src=x onerror=alert(2)> @DATA@ @VIEWER@'


def _hostile_report():
    wall = Pos(0, 0, 26 + 15 + 5) * Box(400, 400, 10)
    assembly = Assembly([Part(HOSTILE, socket_screw()), Part(HOSTILE_WALL, wall)])
    return _checked(assembly, {"fasteners": [{"parts": "</script>*", **M6}]}, model=HOSTILE)


class _RawText(HTMLParser):
    """The page's script and style elements, found as a browser's tokenizer finds
    them: one ends at the first ``</script`` (or ``</style``) in any case, whatever
    is inside, so a name that could close one would show up here as a broken page."""

    def __init__(self, page):
        super().__init__(convert_charrefs=False)
        self.found = []
        self._open = None
        self.feed(page)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._open = (tag, dict(attrs), [])

    def handle_data(self, data):
        if self._open is not None:
            self._open[2].append(data)

    def handle_endtag(self, tag):
        if self._open is not None and tag == self._open[0]:
            self.found.append((tag, self._open[1], "".join(self._open[2])))
            self._open = None


def _scripts(page):
    return [(attrs, body) for tag, attrs, body in _RawText(page).found if tag == "script"]


def _page_data(page):
    (body,) = [body for attrs, body in _scripts(page) if attrs.get("id") == "wrenchroom-data"]
    return json.loads(body)


def test_a_hostile_name_stays_inside_the_data():
    report = _hostile_report()
    assert report.results[0].verdict == "blocked"
    page = html_text(report)
    scripts = _scripts(page)
    data_attrs = {"type": "application/json", "id": "wrenchroom-data"}
    assert [attrs for attrs, _ in scripts] == [data_attrs, {}, {}]
    (_, body), *_ = scripts
    assert "<" not in body
    assert ">" not in body
    assert "&" not in body
    data = json.loads(body)
    assert data["fasteners"][0]["name"] == HOSTILE  # exact, for matching
    assert data["parts"][1]["name"] == HOSTILE_WALL
    assert data["fasteners"][0]["label"] == printable(HOSTILE)  # safe, for reading
    assert not UNSAFE.search(data["fasteners"][0]["label"])
    assert not UNSAFE.search(data["model"])


def test_a_hostile_model_name_is_escaped_in_the_title():
    page = html_text(_hostile_report())
    title = re.search(r"<title>(.*?)</title>", page, flags=re.DOTALL)
    assert title is not None
    assert "<" not in title.group(1)
    assert html_lib.unescape(title.group(1)) == printable(f"wrenchroom: {HOSTILE}")


def test_placeholders_in_names_are_never_filled():
    page = html_text(_hostile_report())
    assert page.count('id="wrenchroom-data"') == 1
    assert len(_scripts(page)) == 3
    data = _page_data(page)
    assert data["parts"][1]["name"] == HOSTILE_WALL  # "@DATA@ @VIEWER@" kept as written
    assert "@VIEWER@" not in page.split('id="wrenchroom-data">')[0]


def _policy(page):
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', page)
    assert meta is not None
    return dict(part.strip().split(" ", 1) for part in meta.group(1).split(";"))


def _sha(text):
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def test_the_policy_runs_only_the_page_s_own_scripts_and_loads_nothing():
    page = html_text(_hostile_report())
    policy = _policy(page)
    assert policy["default-src"] == "'none'"
    assert policy["base-uri"] == "'none'"
    assert policy["form-action"] == "'none'"
    executable = [body for attrs, body in _scripts(page) if attrs.get("type") is None]
    assert len(executable) == 2
    assert sorted(policy["script-src"].split()) == sorted(_sha(body) for body in executable)
    (style,) = [body for tag, _, body in _RawText(page).found if tag == "style"]
    assert policy["style-src"] == _sha(style)
    assert set(policy) == {"default-src", "script-src", "style-src", "base-uri", "form-action"}


def test_the_template_has_no_inline_handlers_and_names_no_network():
    template = (VIEW / "template.html").read_text()
    assert not re.search(r"\son\w+=", template)
    for source in (template, (VIEW / "viewer.js").read_text(), (VIEW / "viewer.css").read_text()):
        assert "http:" not in source
        assert "https:" not in source
        assert "url(" not in source
        assert "innerHTML" not in source
        assert "insertAdjacentHTML" not in source
        assert "document.write" not in source


def test_the_page_is_the_same_every_time():
    report = _checked(screw_facing_wall(15.0), {"fasteners": [{"parts": "bolt", **M6}]})
    assert html_text(report) == html_text(report)


def test_select_is_written_for_the_page_to_open_on():
    report = _checked(screw_facing_wall(15.0), {"fasteners": [{"parts": "bolt", **M6}]})
    assert view_data(report)["select"] is None
    assert view_data(report, select="bolt")["select"] == "bolt"
    with pytest.raises(ValueError, match="no fastener named 'nut'"):
        view_data(report, select="nut")


def test_a_report_with_no_geometry_says_so():
    bare = Report(model="m.step", kit="metric-home", results=())
    with pytest.raises(ValueError, match="no geometry"):
        bare.to_html("never-written.html")


# ---------------------------------------------------------------------------
# The files the page is built from.
# ---------------------------------------------------------------------------


def test_the_vendored_bundle_is_the_one_its_manifest_describes():
    manifest = json.loads((VIEW / "vendor" / "three.json").read_text())
    bundle = (VIEW / "vendor" / "three.min.js").read_bytes()
    assert hashlib.sha256(bundle).hexdigest() == manifest["sha256"]
    assert manifest["three"] == "0.186.1"
    assert bundle.startswith(b"/* three.js r186 (0.186.1), MIT licence")
    assert b"var THREE=" in bundle[:400]
    licence = (VIEW / "vendor" / "three.LICENSE").read_text()
    assert licence.startswith("The MIT License")
    assert "three.js authors" in licence
    vendor_script = REPO / "scripts" / "vendor_three.py"
    spec = importlib.util.spec_from_file_location("vendor_three", vendor_script)
    assert spec is not None
    assert spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert manifest["three"] == script.THREE_VERSION
    assert manifest["esbuild"] == script.ESBUILD_VERSION
    assert manifest["integrity"] == script.THREE_INTEGRITY


@pytest.mark.parametrize("name", ["vendor/three.min.js", "viewer.js", "viewer.css"])
def test_inlined_files_cannot_end_their_element(name):
    text = (VIEW / name).read_bytes()
    assert text.isascii()
    for closing in (b"</script", b"</style", b"<!--", b"<script"):
        assert closing not in text.lower()


def test_every_three_name_the_viewer_uses_is_in_the_bundle():
    used = set(re.findall(r"THREE\.(\w+)", (VIEW / "viewer.js").read_text()))
    entry = (REPO / "scripts" / "three-entry.js").read_text()
    exported = set(re.findall(r"^\s+(\w+),$", entry, flags=re.MULTILINE)) | {"OrbitControls"}
    assert used
    assert used <= exported
    bundle = (VIEW / "vendor" / "three.min.js").read_text()
    for name in exported:
        assert re.search(rf"\b{name}:\(\)=>", bundle), name


def test_the_three_licence_travels_in_every_page():
    page = html_text(_checked(screw_facing_wall(15.0), {"fasteners": [{"parts": "bolt", **M6}]}))
    licence = (VIEW / "vendor" / "three.LICENSE").read_text()
    assert licence in page


# ---------------------------------------------------------------------------
# The CLI.
# ---------------------------------------------------------------------------


@pytest.fixture
def exported(tmp_path):
    shapes = []
    for part in screw_facing_wall(15.0):
        part.shape.label = part.name
        shapes.append(part.shape)
    export_step(Compound(children=shapes), str(tmp_path / "model.step"))
    (tmp_path / "wrenchroom.yaml").write_text(json.dumps({"fasteners": [{"parts": "bolt", **M6}]}))
    return tmp_path / "model.step"


def test_check_html_writes_the_view_and_keeps_the_exit_code(exported, tmp_path):
    out = tmp_path / "report.html"
    result = CliRunner().invoke(main, ["check", str(exported), "--html", str(out)])
    assert result.exit_code == 1
    data = _page_data(out.read_text())
    assert data["model"] == "model.step"
    assert data["select"] is None
    assert [f["name"] for f in data["fasteners"]] == ["bolt"]


def test_explain_html_opens_on_the_fastener(exported, tmp_path):
    out = tmp_path / "bolt.html"
    result = CliRunner().invoke(main, ["explain", str(exported), "bolt", "--html", str(out)])
    assert result.exit_code == 1
    assert "tried hex-key-5, driver straight in: blocked" in result.output
    data = _page_data(out.read_text())
    assert data["select"] == "bolt"
    assert {part["name"] for part in data["parts"]} == {"bolt", "wall"}


def test_check_and_explain_offer_html():
    for command in ("check", "explain"):
        assert "--html" in CliRunner().invoke(main, [command, "--help"]).output
