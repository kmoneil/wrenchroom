"""The HTML view: one self-contained file, the assembly in 3D with every verdict on it.

Spec 10.3. The file carries everything it needs: three.js (vendored, built by
``scripts/vendor_three.py``; ``vendor/three.json`` says from what), the viewer
script and the report's geometry as data. It opens from disk with no network,
and its content security policy allows no request at all, so a report of a
private model can't send anything anywhere, and nothing but its own two scripts
can run in it.

Every decision about what the view shows is made here, where the tests can see
it: each fastener's colour, which parts its failure highlights, which parts a
state takes away or moves, which tool positions to draw and how. ``viewer.js``
only draws what this module wrote and keeps the selection. What it draws is what
the check tested: parts are tessellated as the mesh engine tessellates them, and
each tool position is the very primitives a sweep placed, put in place through
the mesh engine's own :func:`~wrenchroom.engine.mesh.primitive_mesh`.

Names are the model's and can come from anybody. In the page they are text, never
markup: the data is JSON with ``<``, ``>`` and ``&`` escaped, so nothing in it can
close its script element, and ``viewer.js`` writes names with ``textContent``
only. What a person reads (each ``label``) has been through
:func:`~wrenchroom.terminal.printable`, as on the terminal; the real ``name``
stays alongside for matching.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from wrenchroom import __version__
from wrenchroom.engine.mesh import MESH_TOLERANCE, primitive_mesh, shape_triangles
from wrenchroom.report import Verdict, attempt_text
from wrenchroom.terminal import printable

if TYPE_CHECKING:
    from manifold3d import Manifold

    from wrenchroom.assembly import Part
    from wrenchroom.report import FastenerResult, Report, StateModel
    from wrenchroom.tools.sweep import Attempt, Probe

HERE = Path(__file__).parent
VENDOR = HERE / "vendor"

#: The version of the data the page reads; viewer.js checks it.
SCHEMA = 1

#: Every colour the view uses, by what it means (spec 10.3 for the fasteners).
COLOURS = {
    "turns": "#2e9e44",
    "held": "#2f6fd0",
    "elsewhere": "#e8a317",  # passes, but only in a state other than the run's own
    "fails": "#d62828",  # blocked or stuck
    "not-covered": "#7d828c",
    "part": "#c9cdd3",
    "blocker": "#c026d3",  # what stopped the selected fastener's tool
    "probe-hit": "#f26b1d",  # a tool position that ran into something
    "probe-clear": "#19a7b5",  # a tool position that was clear
    "background": "#f3f4f6",
}

#: What each colour means, in the legend's order.
LEGEND = (
    ("turns", "turns"),
    ("held", "held while its partner turns"),
    ("elsewhere", "passes only in another state"),
    ("fails", "blocked or stuck"),
    ("not-covered", "not covered"),
    ("blocker", "in the way of the selected one"),
    ("probe-hit", "a tool position that hit something"),
    ("probe-clear", "a tool position that was clear"),
)

#: The fastener list's order: what needs a person first.
_LIST_ORDER = {"fails": 0, "not-covered": 1, "elsewhere": 2, "held": 3, "turns": 4}

_ESCAPED = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}
_TOKEN = re.compile(r"@([A-Z_]+)@")


def colour_key(result: FastenerResult, default_state: str | None) -> str:
    """Which colour a fastener gets: its verdict, or amber when it passes elsewhere."""
    if result.verdict in {Verdict.BLOCKED, Verdict.STUCK}:
        return "fails"
    if result.verdict is Verdict.NOT_COVERED:
        return "not-covered"
    if result.state != default_state:
        return "elsewhere"
    return result.verdict.value


def write_html(report: Report, path: str | Path, *, select: str | None = None) -> None:
    """Write the view of ``report`` to ``path``; see :func:`html_text`."""
    Path(path).write_text(html_text(report, select=select), encoding="utf-8")


def html_text(report: Report, *, select: str | None = None) -> str:
    """The whole page: data, viewer and three.js, under a policy that allows nothing else.

    Raises:
        ValueError: When the report carries no geometry, or ``select`` names no
            fastener in it.
    """
    data = _script_json(view_data(report, select=select))
    three = (VENDOR / "three.min.js").read_text(encoding="ascii")
    viewer = (HERE / "viewer.js").read_text(encoding="ascii")
    style = (HERE / "viewer.css").read_text(encoding="ascii")
    licence = (VENDOR / "three.LICENSE").read_text(encoding="utf-8")
    if "--" in licence:
        msg = "the three.js licence can't sit in an HTML comment as it stands"
        raise ValueError(msg)
    policy = "; ".join(
        [
            "default-src 'none'",
            f"script-src {_hash(three)} {_hash(viewer)}",
            f"style-src {_hash(style)}",
            "base-uri 'none'",
            "form-action 'none'",
        ]
    )
    title = f"wrenchroom: {report.model}" if report.model else "wrenchroom"
    values = {
        "CSP": policy,
        "VERSION": __version__,
        "TITLE": html.escape(printable(title)),
        "STYLE": style,
        "DATA": data,
        "THREE_LICENCE": licence,
        "THREE": three,
        "VIEWER": viewer,
    }
    template = (HERE / "template.html").read_text(encoding="ascii")
    found = _TOKEN.findall(template)
    if set(found) != set(values):
        msg = f"template.html must hold every placeholder and no other; it holds {found}"
        raise ValueError(msg)
    # One pass: a value is never searched for placeholders, so data can't insert one.
    return _TOKEN.sub(lambda match: values[match.group(1)], template)


def _hash(text: str) -> str:
    digest = base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode()
    return f"'sha256-{digest}'"


def _script_json(data: dict[str, object]) -> str:
    """JSON that can sit inside a script element: nothing in it can end the element."""
    text = json.dumps(data, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return re.sub("[<>&]", lambda match: _ESCAPED[match.group()], text)


# ---------------------------------------------------------------------------
# The data: every decision the page shows, made here.
# ---------------------------------------------------------------------------


def view_data(report: Report, *, select: str | None = None) -> dict[str, object]:
    """What the page draws, as plain data; :func:`html_text` embeds it.

    Raises:
        ValueError: When the report carries no geometry, or ``select`` names no
            fastener in it.
    """
    if None not in report.models:
        msg = "this report carries no geometry to draw: make it with wrenchroom.check"
        raise ValueError(msg)
    names = {result.fastener.name for result in report.results}
    if select is not None and select not in names:
        msg = f"no fastener named {select!r} in the report"
        raise ValueError(msg)
    builder = _Builder(report)
    overview = builder.view(report.default_state)
    ordered = sorted(
        report.results,
        key=lambda r: (_LIST_ORDER[colour_key(r, report.default_state)], r.fastener.name),
    )
    fasteners = [builder.fastener(result) for result in ordered]
    counts = report.summary
    return {
        "schema": SCHEMA,
        "model": printable(report.model),
        "kit": report.kit,
        "engine": report.engine,
        "tool_version": __version__,
        "summary": counts,
        "summary_text": report.terminal_lines()[0],
        "colours": COLOURS,
        "legend": [[key, text] for key, text in LEGEND],
        "shapes": builder.shapes,
        "parts": builder.parts,
        "views": builder.views,
        "overview": overview,
        "fasteners": fasteners,
        "select": select,
    }


class _Builder:
    """Collects shapes, parts and views, each once, as fasteners ask for them."""

    def __init__(self, report: Report) -> None:
        self.report = report
        self.fastener_names = {result.fastener.name for result in report.results}
        self.shapes: list[dict[str, str]] = []
        self.parts: list[dict[str, object]] = []
        self.views: list[dict[str, object]] = []
        self._view_index: dict[str | None, int] = {}
        self._view_parts: dict[int, dict[str, int]] = {}
        self._part_index: dict[tuple[str, str], int] = {}
        self._part_key: dict[int, tuple[Part, tuple[str, str]]] = {}
        self._unit_index: dict[int, tuple[Manifold, int]] = {}

    # ------------------------------------------------------------- views

    def view(self, state: str | None) -> int:
        """The index of a state's view: the parts present in it, each drawn once."""
        model = self._model(state)
        key = state if model is not self.report.models[None] else None
        if key in self._view_index:
            return self._view_index[key]
        by_name: dict[str, int] = {}
        for part in model.assembly:
            if part.name not in model.removed:
                by_name[part.name] = self._part(part)
        index = len(self.views)
        self.views.append(
            {
                "state": key,
                "label": printable(key) if key is not None else "the model as given",
                "parts": list(by_name.values()),
            }
        )
        self._view_index[key] = index
        self._view_parts[index] = by_name
        return index

    def _model(self, state: str | None) -> StateModel:
        """A state as the check saw it; the model as given when it never resolved one."""
        return self.report.models.get(state) or self.report.models[None]

    def _part(self, part: Part) -> int:
        """A part's index; the same name and the same mesh in two states is one part."""
        cached = self._part_key.get(id(part))
        if cached is None:
            arrays = shape_triangles(part.shape, MESH_TOLERANCE)
            digest = _digest(arrays)
            # The part rides along so its id cannot be reused while cached.
            cached = (part, (part.name, digest))
            self._part_key[id(part)] = cached
            if cached[1] not in self._part_index:
                self._part_index[cached[1]] = len(self.parts)
                self.parts.append(
                    {
                        "name": part.name,
                        "label": printable(part.name),
                        "role": self._role(part.name),
                        "shape": None if arrays is None else self._shape(*arrays),
                    }
                )
        return self._part_index[cached[1]]

    def _role(self, name: str) -> str:
        if name in self.fastener_names:
            return "fastener"
        return "ignored" if name in self.report.ignored else "part"

    def _shape(self, vertices: np.ndarray, triangles: np.ndarray) -> int:
        self.shapes.append(
            {
                "p": _b64(vertices.astype("<f4")),
                "i": _b64(triangles.astype("<u4")),
            }
        )
        return len(self.shapes) - 1

    def _unit(self, unit: Manifold) -> int:
        """A tool unit mesh's index: one per shape and size, however often it's placed."""
        cached = self._unit_index.get(id(unit))
        if cached is None:
            mesh = unit.to_mesh()
            vertices = np.asarray(mesh.vert_properties)[:, :3]
            index = self._shape(vertices, np.asarray(mesh.tri_verts))
            cached = (unit, index)  # rides along, as in _part
            self._unit_index[id(unit)] = cached
        return cached[1]

    # --------------------------------------------------------- fasteners

    def fastener(self, result: FastenerResult) -> dict[str, object]:
        """One fastener: its verdict and colour, its attempts and what to highlight."""
        view = self.view(result.state)
        by_name = self._view_parts[view]
        failed = result.verdict in {Verdict.BLOCKED, Verdict.STUCK}
        in_way = result.stuck_on if result.verdict is Verdict.STUCK else result.blockers
        name = result.fastener.name
        way_out = result.way_out if result.way_out is not None and result.way_out.hits else None
        return {
            "name": name,
            "label": printable(name),
            "verdict": result.verdict.value,
            "colour": COLOURS[colour_key(result, self.report.default_state)],
            "headline": printable(result.headline),
            "reason": printable(result.reason) if result.reason else None,
            "in_way": [printable(n) for n in in_way] if failed else [],
            "highlight": _indices(in_way, by_name) if failed else [],
            "view": view,
            "part": by_name.get(name),
            "attempts": [self._attempt(attempt, by_name) for attempt in result.attempts],
            "way_out": None if way_out is None else self._probe(way_out, by_name),
        }

    def _attempt(self, attempt: Attempt, by_name: dict[str, int]) -> dict[str, object]:
        return {
            "text": printable(attempt_text(attempt)),
            "turns": attempt.turns,
            "highlight": _indices(attempt.blockers, by_name),
            "probes": [self._probe(probe, by_name) for probe in attempt.probes],
        }

    def _probe(self, probe: Probe, by_name: dict[str, int]) -> dict[str, object]:
        """One tool position: unit shapes and 3x4 placements, and whether it hit."""
        placement = probe.solid.matrix()
        shapes, matrices = [], []
        for primitive in probe.solid.primitives:
            unit, placed = primitive_mesh(primitive, placement)
            shapes.append(self._unit(unit))
            matrices.append(placed[:3, :])
        return {
            "hit": bool(probe.hits),
            "hits": _indices(probe.hits, by_name),
            "s": shapes,
            "m": _b64(np.array(matrices, dtype="<f4")),
        }


def _indices(names: tuple[str, ...], by_name: dict[str, int]) -> list[int]:
    return [by_name[name] for name in names if name in by_name]


def _digest(arrays: tuple[np.ndarray, np.ndarray] | None) -> str:
    if arrays is None:
        return ""
    vertices, triangles = arrays
    digest = hashlib.sha256(np.ascontiguousarray(vertices, dtype="<f8").tobytes())
    digest.update(np.ascontiguousarray(triangles, dtype="<i8").tobytes())
    return digest.hexdigest()


def _b64(array: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(array).tobytes()).decode("ascii")
