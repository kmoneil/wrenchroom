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
exactly what ``wrenchroom check`` prints, so the reason is in the test output.

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
    from pathlib import Path

    from wrenchroom.report import Report

#: The ini options, their help, and their defaults.
_OPTIONS = {
    "wrenchroom_model": ("The STEP file wrenchroom_report checks, relative to this file.", ""),
    "wrenchroom_config": (
        "The sidecar YAML, relative to this file; default: wrenchroom.yaml beside the model.",
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
def wrenchroom_report(pytestconfig: pytest.Config) -> Report:
    """The configured model checked once, as ``wrenchroom check`` would check it."""
    from wrenchroom.assembly import Assembly  # noqa: PLC0415  (heavy: OCP, on first use only)
    from wrenchroom.checker import check  # noqa: PLC0415
    from wrenchroom.config import Config, ConfigError  # noqa: PLC0415

    base = pytestconfig.inipath.parent if pytestconfig.inipath else pytestconfig.rootpath
    model_text = str(pytestconfig.getini("wrenchroom_model")).strip()
    if not model_text:
        pytest.fail(
            "the wrenchroom_report fixture needs wrenchroom_model set in the pytest "
            "configuration (pytest.ini, or [tool.pytest.ini_options] in pyproject.toml)",
            pytrace=False,
        )
    model = base / model_text
    config_text = str(pytestconfig.getini("wrenchroom_config")).strip()
    config_path = base / config_text if config_text else model.parent / "wrenchroom.yaml"
    state = str(pytestconfig.getini("wrenchroom_state")).strip() or None
    try:
        assembly = Assembly.from_step(model) if model.is_file() else _missing(model, "model")
        if config_text and not config_path.is_file():
            _missing(config_path, "config")
        config = Config.load(config_path) if config_path.is_file() else Config()
        return check(
            assembly,
            config,
            kit=str(pytestconfig.getini("wrenchroom_kit")).strip(),
            model=model.name,
            state=state,
            model_dir=model.parent,
            engine="exact" if pytestconfig.getini("wrenchroom_exact") else "mesh",
            hand_room=pytestconfig.getini("wrenchroom_hand_room"),
        )
    except (ConfigError, ValueError) as exc:
        pytest.fail(f"wrenchroom: {exc}", pytrace=False)


def _missing(path: Path, option: str) -> NoReturn:
    msg = f"no file at {path} (wrenchroom_{option} is relative to the pytest configuration file)"
    raise ValueError(msg)
