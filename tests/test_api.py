"""The Python API as the spec shows it (10.4), run as written against a real file.

`import wrenchroom` stays light and resolves its public names on first use; the
example's every line must work, including the names it reads off a failure.
"""

import json
import pkgutil
import subprocess
import sys
import types

from build123d import Compound, export_step

import wrenchroom
from fixture_models import screw_facing_wall

SIDECAR = {"fasteners": [{"parts": "bolt", "kind": "screw", "head": "socket", "size": "M6"}]}


def test_the_spec_s_example_runs_as_written(tmp_path):
    shapes = []
    for part in screw_facing_wall(15.0):
        part.shape.label = part.name
        shapes.append(part.shape)
    export_step(Compound(children=shapes), str(tmp_path / "robot.step"))
    (tmp_path / "wrenchroom.yaml").write_text(json.dumps(SIDECAR))

    import wrenchroom as wr  # noqa: PLC0415  (the example's own first line)

    asm = wr.Assembly.from_step(tmp_path / "robot.step")
    cfg = wr.Config.load(tmp_path / "wrenchroom.yaml")
    report = wr.check(asm, cfg, kit="metric-home")
    seen = [(f.name, f.tool, f.verdict, f.blocked_by) for f in report.failures()]
    report.to_json(tmp_path / "report.json")
    report.to_html(tmp_path / "report.html")

    assert seen == [("bolt", "hex-key-5", wr.Verdict.BLOCKED, ("wall",))]
    document = json.loads((tmp_path / "report.json").read_text())
    (entry,) = document["fasteners"]
    assert (entry["name"], entry["blocked_by"]) == ("bolt", ["wall"])
    assert (tmp_path / "report.html").stat().st_size > 500_000  # three.js and the model


def test_every_public_name_resolves_to_what_it_names():
    for name in wrenchroom.__all__:
        value = getattr(wrenchroom, name)
        assert value is not None, name
        assert not isinstance(value, types.ModuleType), name


def test_no_submodule_shadows_a_public_name():
    """Loading a submodule sets it on the package under its own name, so a module
    called `check` would replace the `check` function after its first import
    (it did: `wr.check` became a module once anything imported it)."""
    submodules = {info.name for info in pkgutil.iter_modules(wrenchroom.__path__)}
    assert not submodules & set(wrenchroom.__all__)


def test_check_stays_the_function_after_its_module_is_imported():
    import wrenchroom.checker  # noqa: PLC0415  (the import that used to break it)

    assert wrenchroom.check is wrenchroom.checker.check
    assert callable(wrenchroom.check)
    report = wrenchroom.check(screw_facing_wall(40.0), engine="exact")
    again = wrenchroom.check(screw_facing_wall(40.0), engine="exact")
    assert report.summary == again.summary


def test_importing_wrenchroom_stays_light():
    code = (
        "import sys, wrenchroom; "
        "print(sorted(m for m in ('build123d', 'OCP', 'manifold3d') if m in sys.modules))"
    )
    done = subprocess.run(  # noqa: S603  (this interpreter, a fixed script)
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "[]"
