"""Build the release files and prove them, before anything goes to PyPI.

Usage::

    uv run python scripts/release.py      # or: scripts/lanes.py release-check

1. Under a tag (GitHub sets ``GITHUB_REF_TYPE=tag`` and ``GITHUB_REF_NAME``), the tag
   must name the package's own version, ``v`` and all, and the version must be one
   PyPI should get: no ``.dev``, no ``+local``. A mismatch is a release of the wrong
   code under the right name, and PyPI never takes a version twice to fix it.
2. ``uv build`` writes the sdist and the wheel into ``dist/``, emptied first.
3. The sdist holds nothing private or generated (the gitignored working directories,
   a STEP file an example wrote), and the wheel holds what the package needs at run
   time: its licences and the 3D view's three.js bundle.
4. The wheel is installed into a fresh environment, away from this checkout, and run
   the way the README's worked example runs it: ``--version`` names the version, and
   the example bracket checks to the README's verdicts, its 3D view written.

Exits non-zero, naming the first thing wrong. ``release.yml`` runs this before it
publishes, and by hand (``workflow_dispatch``) it is the whole run: a dry run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST = REPO_ROOT / "dist"
INIT = REPO_ROOT / "src" / "wrenchroom" / "__init__.py"
EXAMPLE = REPO_ROOT / "examples" / "bracket.py"

#: A version PyPI should get: a release, a pre-release or a post-release (PEP 440),
#: never a development or a local one.
RELEASE_VERSION = re.compile(r"\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?")

#: What the sdist must never hold: the gitignored working directories, where plans
#: and private material live, any model (the repository tracks none), and what the
#: examples write when run.
NOT_IN_SDIST = re.compile(
    r"(^|/)(_plans|_tmp|_reviews|_reports)(/|$)"
    r"|\.(step|stp)$"
    r"|(^|/)examples/[^/]+\.(html|json|md)$",
    re.IGNORECASE,
)

#: What the wheel must hold, by the end of each path.
IN_WHEEL = (
    "wrenchroom/__init__.py",
    "wrenchroom/view/vendor/three.min.js",
    "licenses/LICENSE",
    "licenses/src/wrenchroom/view/vendor/three.LICENSE",
)

#: The README's worked example, as the summary a check of it must come to.
EXAMPLE_SUMMARY = {
    "fasteners": 5,
    "turns": 3,
    "held": 0,
    "blocked": 1,
    "stuck": 1,
    "not_covered": 0,
}


class ReleaseError(Exception):
    """The first thing wrong with a release; its message says what."""


def package_version(init_text: str) -> str:
    """The version ``__init__.py`` declares, the one the build stamps."""
    found = re.search(r'^__version__ = "([^"]+)"$', init_text, re.MULTILINE)
    if found is None:
        msg = "src/wrenchroom/__init__.py declares no __version__"
        raise ReleaseError(msg)
    return found.group(1)


def check_tag(tag: str, version: str) -> None:
    """The tag must be ``v`` and the version, and the version one PyPI should get."""
    if tag != f"v{version}":
        msg = f"tag {tag} does not name the package's version {version} (want v{version})"
        raise ReleaseError(msg)
    if RELEASE_VERSION.fullmatch(version) is None:
        msg = f"version {version} is not a release: no .dev or +local goes to PyPI"
        raise ReleaseError(msg)


def check_sdist(names: list[str]) -> None:
    """Nothing private or generated in the sdist."""
    bad = sorted(name for name in names if NOT_IN_SDIST.search(name))
    if bad:
        msg = f"the sdist holds what it must not: {', '.join(bad)}"
        raise ReleaseError(msg)


def check_wheel(names: list[str]) -> None:
    """The wheel holds its licences and the view's bundle."""
    missing = [want for want in IN_WHEEL if not any(name.endswith(want) for name in names)]
    if missing:
        msg = f"the wheel lacks {', '.join(missing)}"
        raise ReleaseError(msg)


def _run(argv: list[str], cwd: Path, expect: int = 0) -> str:
    """Run a command, failing the release on any other exit code; its stdout."""
    print(f"[release] {' '.join(argv)}", flush=True)
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    if done.returncode != expect:
        msg = (
            f"{' '.join(argv)} exited {done.returncode}, not {expect}:\n"
            f"{done.stdout[-2000:]}{done.stderr[-2000:]}"
        )
        raise ReleaseError(msg)
    return done.stdout


def _uv() -> str:
    uv = shutil.which("uv")
    if uv is None:
        msg = "uv is not on PATH"
        raise ReleaseError(msg)
    return uv


def build() -> tuple[Path, Path]:
    """Write the sdist and the wheel into an emptied dist/: their paths."""
    shutil.rmtree(DIST, ignore_errors=True)
    _run([_uv(), "build", "--out-dir", str(DIST)], REPO_ROOT)
    sdists, wheels = sorted(DIST.glob("*.tar.gz")), sorted(DIST.glob("*.whl"))
    if len(sdists) != 1 or len(wheels) != 1:
        msg = f"expected one sdist and one wheel in dist/, found {sdists + wheels}"
        raise ReleaseError(msg)
    return sdists[0], wheels[0]


def smoke(wheel: Path, version: str) -> None:
    """Install the wheel where this checkout can't be seen, and run the example."""
    with tempfile.TemporaryDirectory(prefix="wrenchroom-release-") as scratch:
        work = Path(scratch)
        venv = work / "venv"
        _run([_uv(), "venv", "--python", "3.13", str(venv)], work)
        python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        _run([_uv(), "pip", "install", "--python", str(python), str(wheel)], work)
        cli = python.parent / ("wrenchroom.exe" if sys.platform == "win32" else "wrenchroom")
        said = _run([str(cli), "--version"], work).strip()
        if said != f"wrenchroom, version {version}":
            msg = f"the installed wheel says {said!r}, not version {version}"
            raise ReleaseError(msg)
        (work / "examples").mkdir()
        shutil.copy(EXAMPLE, work / "examples" / "bracket.py")
        _run([str(python), "examples/bracket.py"], work)
        # A fastener fails in the example, so the check exits 1, as the README says.
        args = ["check", "examples/bracket.step", "--json", "report.json"]
        _run([str(cli), *args, "--html", "report.html"], work, expect=1)
        summary = json.loads((work / "report.json").read_text())["summary"]
        if summary != EXAMPLE_SUMMARY:
            msg = f"the example checks to {summary}, not {EXAMPLE_SUMMARY}"
            raise ReleaseError(msg)
        if "three" not in (work / "report.html").read_text(encoding="utf-8"):
            msg = "the example's 3D view has no three.js in it"
            raise ReleaseError(msg)


def main() -> int:
    """Check the tag, build, check the files, run the wheel; 0 when all is well."""
    try:
        version = package_version(INIT.read_text(encoding="utf-8"))
        if os.environ.get("GITHUB_REF_TYPE") == "tag":
            check_tag(os.environ["GITHUB_REF_NAME"], version)
        sdist, wheel = build()
        with tarfile.open(sdist) as archive:
            check_sdist(archive.getnames())
        with zipfile.ZipFile(wheel) as archive:
            check_wheel(archive.namelist())
        smoke(wheel, version)
    except ReleaseError as exc:
        print(f"[release] FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"[release] wrenchroom {version}: {sdist.name} and {wheel.name} are ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
