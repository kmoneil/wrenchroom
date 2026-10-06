# wrenchroom

**wrenchroom checks that a real hand tool can reach, turn and remove every fastener in a
mechanical assembly.** Give it a STEP file (from any CAD) or a list of shapes from a
Python CAD library, and it reports, fastener by fastener, which tool gets on, whether it
can swing far enough to turn, whether the screw can come out, and what is in the way when
it can't. It runs from the command line, from Python, and in CI.

A collision check says the parts fit. It doesn't say the thing can be put together or
taken apart. The classic failure is a bolt nobody can get a tool on, found when the parts
arrive. One real design review found, among other things, four socket head bolts 16.4 mm
from a wall: the 5 mm hex key they need is 28 mm long on its short leg. The fix was cheap
once seen (hex heads a spanner turns sideways); seen late it would have been a re-order.
Every one of those findings was invisible to the collision check.

## Status

**Scaffold; nothing works yet.** What exists today:

- The package installs, `wrenchroom --help` shows the four commands (`check`, `detect`,
  `explain`, `tools`), and each exits 2 ("not covered") until it is delivered.
- The dependency stack is locked and proven on CPython 3.13 and 3.14, Linux and macOS:
  build123d with headless OCP for STEP and tessellation, trimesh and manifold3d for the
  mesh collision engine to come.

## What it will do

```console
$ wrenchroom check robot.step
213 fasteners: 180 turn, 25 held by a turning partner, 6 blocked, 2 not covered

controller_box_gland_blade_R   spanner-22   blocked   controller_box_gland_blade_L, deck_floor
...
```

- **Any CAD.** STEP assemblies (AP203, AP214, AP242) from Fusion, Onshape, SolidWorks,
  FreeCAD, build123d, CadQuery; or shapes passed straight from Python.
- **Real tools at standard sizes**: hex and Torx keys, combination and stubby spanners,
  sockets on ratchets and extensions, screwdrivers, nut drivers.
- **The checks that matter**: the tool gets on; it can swing far enough to turn; a nut
  and its screw are a pair, one side turned and the other held; the screw can come out
  along its axis; retried with parts removed or the mechanism moved.
- **Every failure explained**: which tool, which way it was tried, what it hit.
- **Fast enough for CI**: the target is 500 fasteners in under 10 seconds, with JSON
  output and exit codes, plus a terminal table and a self-contained HTML 3D view.

## Development

Python 3.13+, managed with [uv](https://docs.astral.sh/uv/).

```console
$ uv sync
$ uv run python scripts/lanes.py          # the table of lanes
$ uv run python scripts/lanes.py gates    # ruff lint, ruff format, ty
$ uv run python scripts/lanes.py fast     # the unit suite
```

CI runs the same lanes by the same names; `scripts/lanes.py` is the only spelling of how
this project runs its checks.
