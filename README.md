# wrenchroom

**wrenchroom checks that a real hand tool can reach, turn and remove every fastener in a
mechanical assembly.** Give it a STEP file (from any CAD) or a list of shapes from a
Python CAD library, and it reports, fastener by fastener, which tool gets on, whether it
can swing far enough to turn, whether the screw can come out, and what is in the way when
it can't. It runs from the command line, from Python, and in CI.

A collision check says the parts fit. It doesn't say the thing can be put together or
taken apart. The classic failure is a bolt nobody can get a tool on, found when the parts
arrive: a socket head screw 15 mm under a wall needs a 5 mm hex key whose short leg alone
is 33 mm. The fix is cheap seen early (a hex head a spanner turns from the side) and a
re-order seen late, and a collision check can't see it either way.

## Status

**`wrenchroom check` works on real STEP files, with fasteners described by hand.**
What exists today (M1):

- `wrenchroom check model.step` reads a STEP assembly (names kept, repeats made
  unique), takes fastener descriptions from a `wrenchroom.yaml` sidecar, resolves each
  fastener's seat and axis from its geometry, and tries real tools against the real
  parts: metric hex keys (driver straight in, short leg, long leg), ring spanners (full
  and stubby), sockets on a ratchet with stock extensions, Phillips and slotted
  drivers. Verdicts per fastener with every blocker named; terminal table, JSON
  (`--json`), exit codes for CI (0 pass, 1 a fastener fails, 2 not covered or config
  error).
- Dimension tables cite their standards (ISO 2936, 4762, 7380-1, 10642, 4032) with the
  date checked; approximations are labelled as such.
- A sidecar rule that matches nothing is reported and fails the run: that is how a
  renamed part hides.
- `detect`, `explain` and `tools` exist and exit 2 ("not covered") until their
  milestones deliver them. Pairs, extraction and states are next (M2).

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
$ uv run python scripts/lanes.py fast     # the unit suite, golden bench included
$ uv run python scripts/lanes.py golden   # only the bench: truth, counts, snapshot
```

The golden bench (`tests/golden/`) is a generated assembly of small cells, one
mechanism each, with every verdict worked out by hand; features that haven't landed
yet are strict xfails naming their milestone. `uv run python scripts/golden.py --out
some-dir` writes `bench.step` and its sidecars for you to open and check against; a
nightly job re-runs the bench against upgraded dependencies so a CAD-kernel update
that moves a verdict shows up before it lands.

CI runs the same lanes by the same names; `scripts/lanes.py` is the only spelling of how
this project runs its checks.
