"""Collision queries: does this tool solid run into any part, and which.

Two engines answer the same two calls, :meth:`Scene.hits` and :meth:`Scene.clear`,
and nothing outside this package may assume either one:

- ``mesh``, the default since M3: every part tessellated once, tools meshed from
  their primitives, overlap volumes from manifold3d booleans (``mesh.py``).
- ``exact``: OCP boolean intersections on the B-rep, correct and slow, kept
  forever behind ``--exact`` as the referee for borderline results (``exact.py``).

Both count a hit the same way, an overlap of more than :data:`HIT_MIN_VOLUME`
(``scene.py``), so they differ only by how closely a mesh follows a curved face.
"""

from wrenchroom.engine.exact import ExactEngine
from wrenchroom.engine.mesh import MeshEngine
from wrenchroom.engine.scene import HIT_MIN_VOLUME, Engine, Scene, Tool

__all__ = [
    "DEFAULT_ENGINE",
    "ENGINES",
    "HIT_MIN_VOLUME",
    "Engine",
    "ExactEngine",
    "MeshEngine",
    "Scene",
    "Tool",
    "make_engine",
]

_BY_NAME: dict[str, type[Engine]] = {
    MeshEngine.name: MeshEngine,
    ExactEngine.name: ExactEngine,
}

#: Every engine's name, the default first.
ENGINES = tuple(_BY_NAME)

#: What ``check`` uses unless told otherwise.
DEFAULT_ENGINE = MeshEngine.name


def make_engine(name: str = DEFAULT_ENGINE) -> Engine:
    """A fresh engine, by name, for one run.

    Raises:
        ValueError: On a name that isn't an engine.
    """
    engine_type = _BY_NAME.get(name)
    if engine_type is None:
        msg = f"unknown engine {name!r}; available: {', '.join(ENGINES)}"
        raise ValueError(msg)
    return engine_type()
