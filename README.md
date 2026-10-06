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

**`wrenchroom check` works on real STEP files, with fasteners described by hand, fast
enough for CI.** What exists today (M1 to M3):

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
- Pairs (a nut that only holds passes through its turning bolt), extraction (a
  screw that turns but can't come out is `stuck`), states (parts removed, another
  model of the mechanism, retries that say where a fastener passed), `explain`
  (every attempt for one fastener, with the blockers) and `tools` (the kit's
  dimensions, caveats inline) all work. `detect` exits 2 until M4 delivers it.
- Collision checks run on meshes: each part tessellated once (0.2 mm), tools meshed
  from their primitives, overlap volumes from manifold3d. The golden bench scaled to
  504 fasteners is read and checked in about 7 s on an Apple M5 Max laptop (the
  target is 10 s). `--exact` swaps in OCP boolean intersections on the B-rep: about
  five times slower, and the referee for anything within the mesh's 0.2 mm of a
  curved face. Both engines give the bench the same report, field for field.
- A golden bench of generated cells with hand-worked truth gates every change, on both
  engines; its whole-report snapshot is byte-identical across Linux and macOS, 3.13
  and 3.14.

## What it will do

```console
$ wrenchroom check bench.step    # the golden bench's own report, verbatim
36 fasteners: 23 turn, 2 held, 10 blocked, 1 stuck, 0 not covered
  M16 nut                  spanner-24     x5    3 of 5 fail
  M6 carriage screw        -              x1    all pass (holds itself)
  ...
FAIL glands_close_a_gland  spanner-24  blocked  glands_close_b_gland
FAIL key_wall_near_screw   hex-key-5   blocked  key_wall_near_wall
```

- **Any CAD.** STEP assemblies (AP203, AP214, AP242) from Fusion, Onshape, SolidWorks,
  FreeCAD, build123d, CadQuery; or shapes passed straight from Python.
- **Real tools at standard sizes**: hex and Torx keys, combination and stubby spanners,
  sockets on ratchets and extensions, screwdrivers, nut drivers.
- **The checks that matter**: the tool gets on; it can swing far enough to turn; a nut
  and its screw are a pair, one side turned and the other held; the screw can come out
  along its axis; retried with parts removed or the mechanism moved.
- **Every failure explained**: which tool, which way it was tried, what it hit.
- **Fast enough for CI**: 500 fasteners in under 10 seconds, with JSON output and exit
  codes, a terminal table, and (coming) a self-contained HTML 3D view.

## Development

Python 3.13+, managed with [uv](https://docs.astral.sh/uv/).

```console
$ uv sync
$ uv run python scripts/lanes.py          # the table of lanes
$ uv run python scripts/lanes.py gates    # ruff lint, ruff format, ty
$ uv run python scripts/lanes.py fast     # the unit suite, golden bench included
$ uv run python scripts/lanes.py golden   # only the bench: truth, counts, snapshot
$ uv run python scripts/lanes.py perf     # the bench at 500 fasteners, timed
```

The golden bench (`tests/golden/`) is a generated assembly of small cells, one
mechanism each, with every verdict worked out by hand; features that haven't landed
yet are strict xfails naming their milestone. It runs on both collision engines
against one snapshot, and again as three copies along the grid (a verdict mustn't
depend on where its cell sits). `scripts/perf.py` repeats it to 500 fasteners and
times it; CI reports that number on every push and fails if any verdict count moves.
`uv run python scripts/golden.py --out some-dir` writes `bench.step` and its sidecars
for you to open and check against; a nightly job re-runs the bench against upgraded
dependencies so a CAD-kernel update that moves a verdict shows up before it lands.

CI runs the same lanes by the same names; `scripts/lanes.py` is the only spelling of how
this project runs its checks.
