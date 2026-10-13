"""The pytest plugin: a design change that buries a bolt fails the test run (spec 10.5).

Name the model in the project's pytest configuration (``pytest.ini``, or
``[tool.pytest.ini_options]`` in ``pyproject.toml``); paths are relative to that file::

    [pytest]
    wrenchroom_model = cad/robot.step
    wrenchroom_config = cad/wrenchroom.yaml   # optional: default, wrenchroom.yaml beside the model
    wrenchroom_kit = metric-home              # optional
    wrenchroom_state = service                # optional: the run's default state
    wrenchroom_exact = false                  # optional: the exact engine

and ask for the report::

    def test_every_fastener_reachable(wrenchroom_report):
        wrenchroom_report.assert_all_pass()

``assert_all_pass`` fails with the report's summary and its FAIL and WARN lines,
exactly what ``wrenchroom check`` prints, so the reason is in the test output. The
run is at the sidecar's step (``checks: {step_deg: 5}``), as ``wrenchroom check``'s is.

A project whose model is a build script hands it over instead, with no STEP file
written (issue #212): it overrides two fixtures of this plugin's in its
``conftest.py``, the model and, where the sidecar's states or build steps name models
of their own, those by the names it gives them (``check()``'s ``models=``)::

    @pytest.fixture(scope="session")
    def wrenchroom_assembly():
        return Assembly.from_shapes(parts(lever=0))

    @pytest.fixture(scope="session")
    def wrenchroom_models():
        return {"lever-up.step": Assembly.from_shapes(parts(lever=20))}

The assembly given is the one checked, and no model file is read. ``wrenchroom_model``
is then optional: set, it is the name the report carries and the folder a sidecar and
a state's model are looked for in. Without it the sidecar is ``wrenchroom.yaml``
beside the pytest configuration file, or ``wrenchroom_config``.

Installing wrenchroom registers this plugin with pytest (the ``pytest11`` entry
point). It does nothing until a test asks for the fixture and imports nothing heavy
before then, so other test suites in the same environment pay nothing for it;
``-p no:wrenchroom`` turns it off. The model is checked once per session, however
many tests ask.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from wrenchroom.assembly import Assembly
    from wrenchroom.report import Report

#: The ini options, their help, and their defaults.
_OPTIONS = {
    "wrenchroom_model": ("The STEP file wrenchroom_report checks, relative to this file.", ""),
    "wrenchroom_config": (
        "The sidecar YAML, relative to this file; default: wrenchroom.yaml beside the model, "
        "or beside this file where an assembly is given and no model named.",
        "",
    ),
    "wrenchroom_kit": ("Which tool kit (wrenchroom tools --kit NAME lists one).", "metric-home"),
    "wrenchroom_state": ("The state the run takes as normal; default: the sidecar's.", ""),
}


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ini options; nothing else happens at startup."""
    for name, (help_text, default) in _OPTIONS.items():
        parser.addini(name, help_text, default=default)
    parser.addini(
        "wrenchroom_exact",
        "Use the exact OCP engine: slow, the referee for borderline results.",
        type="bool",
        default=False,
    )
    parser.addini(
        "wrenchroom_hand_room",
        "Also check room for a hand on each handle; default: the sidecar's setting.",
        type="bool",
        default=None,
    )


@pytest.fixture(scope="session")
def wrenchroom_assembly() -> Assembly | None:
    """The model to check, for a project that builds it: override this in ``conftest.py``.

    As it stands it gives none, and the STEP file ``wrenchroom_model`` names is read.
    """
    return None


@pytest.fixture(scope="session")
def wrenchroom_models() -> Mapping[str, Assembly]:
    """States' and build steps' models as assemblies, by the names the sidecar gives them.

    ``check()``'s ``models=``: override this in ``conftest.py`` beside
    ``wrenchroom_assembly``. As it stands it gives none, and each is read from its file.
    """
    return {}


@pytest.fixture(scope="session")
def wrenchroom_report(
    pytestconfig: pytest.Config,
    wrenchroom_assembly: Assembly | None,
    wrenchroom_models: Mapping[str, Assembly],
) -> Report:
    """The configured model checked once, as ``wrenchroom check`` would check it."""
    from wrenchroom.assembly import Assembly  # noqa: PLC0415  (heavy: OCP, on first use only)
    from wrenchroom.checker import check  # noqa: PLC0415
    from wrenchroom.config import Config, ConfigError  # noqa: PLC0415

    base = pytestconfig.inipath.parent if pytestconfig.inipath else pytestconfig.rootpath
    model_text = str(pytestconfig.getini("wrenchroom_model")).strip()
    given = wrenchroom_assembly
    if given is None and not model_text:
        pytest.fail(
            "the wrenchroom_report fixture needs wrenchroom_model set in the pytest "
            "configuration (pytest.ini, or [tool.pytest.ini_options] in pyproject.toml), "
            "or the wrenchroom_assembly fixture overridden in conftest.py to give the model",
            pytrace=False,
        )
    if given is not None and not isinstance(given, Assembly):
        pytest.fail(
            f"wrenchroom: the wrenchroom_assembly fixture must give an Assembly, got "
            f"{type(given).__name__} (Assembly.from_shapes makes one of shapes)",
            pytrace=False,
        )
    # A model named beside an assembly given is its name, and where to look: never read.
    model = base / model_text if model_text else None
    beside = model.parent if model is not None else base
    config_text = str(pytestconfig.getini("wrenchroom_config")).strip()
    config_path = base / config_text if config_text else beside / "wrenchroom.yaml"
    state = str(pytestconfig.getini("wrenchroom_state")).strip() or None
    try:
        if given is not None:
            assembly = given
        else:
            assert model is not None  # noqa: S101  (narrowing only: refused above)
            assembly = Assembly.from_step(model) if model.is_file() else _missing(model, "model")
        if config_text and not config_path.is_file():
            _missing(config_path, "config")
        config = Config.load(config_path) if config_path.is_file() else Config()
        return check(
            assembly,
            config,
            kit=str(pytestconfig.getini("wrenchroom_kit")).strip(),
            model=model.name if model is not None else "",
            state=state,
            model_dir=model.parent if model is not None else None,
            models=wrenchroom_models or None,
            engine="exact" if pytestconfig.getini("wrenchroom_exact") else "mesh",
            hand_room=pytestconfig.getini("wrenchroom_hand_room"),
        )
    except (ConfigError, ValueError, TypeError) as exc:
        pytest.fail(f"wrenchroom: {exc}", pytrace=False)


def _missing(path: Path, option: str) -> NoReturn:
    msg = f"no file at {path} (wrenchroom_{option} is relative to the pytest configuration file)"
    raise ValueError(msg)
