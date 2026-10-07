"""wrenchroom checks that a real hand tool can reach, turn and remove every fastener.

Give it a STEP file from any CAD program, or shapes from a Python CAD library, and it
reports, fastener by fastener, which tool gets on, whether it can swing far enough to
turn, whether the screw can come out, and what is in the way when it can't.

This package grows milestone by milestone; what exists is tested, what doesn't says so.
"""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wrenchroom.assembly import Assembly, Part
    from wrenchroom.checker import check
    from wrenchroom.config import Config
    from wrenchroom.report import Report, Verdict

__version__ = "0.1.0"

__all__ = ["Assembly", "Config", "Part", "Report", "Verdict", "__version__", "check"]

# `import wrenchroom` must stay light. Assembly pulls build123d, which pulls OCP
# (OpenCascade, seconds of import time); loading that to print `--help` or a version
# would make the CLI feel broken. So the public names resolve lazily on first touch.
_LAZY = {
    "Assembly": "wrenchroom.assembly",
    "Part": "wrenchroom.assembly",
    "Config": "wrenchroom.config",
    "check": "wrenchroom.checker",
    "Report": "wrenchroom.report",
    "Verdict": "wrenchroom.report",
}


def __getattr__(name: str) -> object:
    """Resolve the heavy public names on first use rather than at import."""
    module_name = _LAZY.get(name)
    if module_name is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    return getattr(importlib.import_module(module_name), name)
