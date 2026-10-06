"""Rebuild the three.js bundle the HTML view embeds, or check the committed one.

Usage::

    uv run python scripts/vendor_three.py           # rebuild src/wrenchroom/view/vendor/
    uv run python scripts/vendor_three.py --check   # rebuild in scratch; exit 1 if it differs

The view embeds three.js so a report opens offline, from a CI artifact or on a
machine with no network (decided 2026-10-06, over loading it from a CDN). three
r186 ships no minified build, and its two module files come to 2.2 MB, so the
bundle is made here: the npm tarball, checked against the registry's sha512
pinned below, bundled by a pinned esbuild from ``three-entry.js`` (the names the
viewer uses; the rest is shaken out) into one minified script that sets the
global ``THREE``. ``npx`` runs esbuild; nothing else here needs Node.

esbuild's output depends only on its inputs, so ``--check`` proves the committed
bundle is exactly what this script makes from the pinned versions. The nightly
workflow runs it.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY = Path(__file__).resolve().parent / "three-entry.js"
VENDOR = REPO_ROOT / "src" / "wrenchroom" / "view" / "vendor"

#: three.js on npm, and the tarball's integrity as the registry publishes it
#: (``npm view three@0.186.1 dist.integrity``), checked 2026-10-06.
THREE_VERSION = "0.186.1"
THREE_INTEGRITY = (
    "sha512-blFeqb49wRCSGUGj7gtpfnSGHy2lwDk94RhUmS1c/"
    "hTby70kvChbWpkJ4Pm1390LqzzvTmzgXKHPEafJwCb8jA=="
)
TARBALL = f"https://registry.npmjs.org/three/-/three-{THREE_VERSION}.tgz"

#: The bundler, pinned: a different esbuild may write different bytes.
ESBUILD_VERSION = "0.28.2"

HEADER = (
    f"/* three.js r{THREE_VERSION.split('.')[1]} ({THREE_VERSION}), MIT licence: see "
    f"three.LICENSE. Bundled by scripts/vendor_three.py with esbuild {ESBUILD_VERSION}. */\n"
)


def main(argv: list[str]) -> int:
    """Build into the vendor directory, or into scratch and compare."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="compare, don't write")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as scratch:
        built = _build(Path(scratch))
        if args.check:
            stale = [name for name, data in built.items() if _read(VENDOR / name) != data]
            if stale:
                print(f"the committed bundle differs from a fresh build: {', '.join(stale)}")
                return 1
            print(f"the committed bundle is exactly three {THREE_VERSION} by esbuild")
            return 0
        VENDOR.mkdir(parents=True, exist_ok=True)
        for name, data in built.items():
            (VENDOR / name).write_bytes(data)
            print(f"wrote {VENDOR / name} ({len(data):,} bytes)")
    return 0


def _build(scratch: Path) -> dict[str, bytes]:
    """Fetch, verify, unpack and bundle; the vendor files by name."""
    tarball = scratch / "three.tgz"
    with urllib.request.urlopen(TARBALL, timeout=60) as response:
        tarball.write_bytes(response.read())
    digest = "sha512-" + base64.b64encode(hashlib.sha512(tarball.read_bytes()).digest()).decode()
    if digest != THREE_INTEGRITY:
        msg = f"{TARBALL} does not match its pinned integrity: got {digest}"
        raise SystemExit(msg)
    modules = scratch / "node_modules"
    with tarfile.open(tarball) as archive:
        archive.extractall(modules, filter="data")
    (modules / "package").rename(modules / "three")
    shutil.copy(ENTRY, scratch / "entry.js")
    npx = shutil.which("npx")
    if npx is None:
        msg = "npx (Node.js) is needed to run esbuild"
        raise SystemExit(msg)
    out = scratch / "three.min.js"
    subprocess.run(
        [
            npx,
            "--yes",
            f"esbuild@{ESBUILD_VERSION}",
            "entry.js",
            "--bundle",
            "--format=iife",
            "--global-name=THREE",
            "--minify",
            "--legal-comments=none",
            "--target=es2020",
            f"--outfile={out.name}",
            "--log-level=warning",
        ],
        cwd=scratch,
        check=True,
    )
    bundle = HEADER.encode() + out.read_bytes()
    licence = (modules / "three" / "LICENSE").read_bytes()
    manifest = {
        "three": THREE_VERSION,
        "integrity": THREE_INTEGRITY,
        "esbuild": ESBUILD_VERSION,
        "sha256": hashlib.sha256(bundle).hexdigest(),
    }
    return {
        "three.min.js": bundle,
        "three.LICENSE": licence,
        "three.json": (json.dumps(manifest, indent=2) + "\n").encode(),
    }


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
