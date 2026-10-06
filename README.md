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

**`wrenchroom check` works on real STEP files, finds fasteners by their names and
solids, is fast enough for CI, and shows its answers in 3D.** What exists today (M1
to M5):

- `wrenchroom check model.step` reads a STEP assembly (names kept, repeats made
  unique), takes fastener descriptions from a `wrenchroom.yaml` sidecar, resolves each
  fastener's seat and axis from its geometry (a nut is turned from the end nothing sits
  against, or, drawn off its seat with its washer left out, from the end with the more
  room), and tries real tools against the real
  parts: metric hex keys (driver straight in, short leg, long leg), combination
  spanners (the ring, then the open end from the side, each full and stubby), sockets
  on a ratchet with stock extensions, Phillips and slotted drivers. Verdicts per fastener with every blocker named; terminal table, JSON
  (`--json FILE`), Markdown for a CI job summary or a PR comment (`--md FILE`), exit
  codes for CI (0 pass, 1 a fastener fails, 2 not covered or config error). A FILE of
  `-` writes that report to stdout instead and moves the table to stderr, so it can be
  piped: `--json - | jq`, `--md - >> "$GITHUB_STEP_SUMMARY"`. Only one report can go
  to stdout; a file really named `-` is `./-`. Names come from the
  model, so the terminal shows control characters written out and the Markdown puts
  every name in a code span: a crafted part name can't steer a terminal or post a
  link or an image in a comment.
- A kit says which tools exist, and only those are tried (`--kit`; `wrenchroom tools
  --kit NAME` lists them). `metric-home`, the default, is a home toolbox: hex keys
  1.5 to 10 mm, combination spanners and 1/4" and 3/8" drive sockets 5.5 to 19 mm,
  Phillips 1 to 3 and slotted drivers. `imperial-home` is the same in inch sizes, as
  US home sets come: ASME B18.3 keys 0.050 to 3/8 in, spanners 1/4 to 3/4 in, sockets
  3/16 to 3/4 in. `full` holds every size the tables describe, both systems. A
  fastener that needs a tool the kit lacks is not covered, and the reason names the
  tool and the kits that have it (`needs spanner-24, which kit metric-home does not
  hold (full has it)`). `full` also has Torx keys T10 to T40 (ISO 10664 sizes, swept
  like hex keys; a Torx head takes the size ISO 14579 and its kin give its thread,
  M6 T30), ball-end keys 3 to 10 mm, tried when no straight key gets in (the long leg
  leant up to 25 degrees off the axis, Bondhus' and Wiha's figure, every way round),
  and nut drivers 5.5 to 13 mm, tried last, straight in, where nothing that swings
  can get down to a nut. Inch tools carry their unit (`spanner-7/16in`), and inch
  fasteners (`#10`, `1/4`, `3/4`; UNC and UNF alike) take their ASME tools: socket,
  button and flat heads (B18.3), nuts (B18.2.2, B18.6.3) and hex heads (B18.2.1),
  which part ways with their nuts at 7/16 and 9/16.
- Room for the hand (`--hand-room`, or `checks: {hand_room: true}` in the sidecar):
  a hand of radius 35 mm along each handle's last 90 mm, resting on it from the side
  the tool comes from, and a fist round a driver's handle. Where the tool alone would
  turn and the hand can't follow, the fastener is blocked, "no room for a hand",
  naming what the hand hit. Off by default: the spec's figures are not yet tuned
  against real hands, and L-key arms, turned with the fingertips, get no hand. Every
  report ends by saying what it didn't check.
- `--html FILE` writes the 3D view: one self-contained file that opens
  offline. The assembly is grey and each fastener coloured by how it fared (green
  turns, blue held, amber passes only in another state, red blocked or stuck, grey
  not covered). Click one, or pick it from the list, to see every tool position that
  was tried, drawn translucent where the check put it (orange where it hit
  something), with the parts in its way in magenta; a fastener reached in another
  state is drawn in that state. `wrenchroom explain model.step NAME --html f.html`
  writes the same view opened on one fastener, and `report.html#NAME` opens any
  fastener directly. The page embeds three.js (r186, MIT) and its content security
  policy lets it load nothing and run nothing but its own two scripts, so a report
  of a private model can't send anything anywhere.
- Dimension tables cite their standards (ISO 2936, 4762, 7380-1, 10642, 4032) with the
  date checked; approximations are labelled as such.
- A sidecar glob that matches nothing (a rule's parts or mates, an ignore, a state's
  removal, `--only`) is reported and fails the run: that is how a renamed part hides.
  A rule's `mates:` (parts that travel with the fastener and leave its scene, such as
  a washer or a nyloc's separate dome) take globs like the rest.
- Pairs (a nut that only holds passes through its turning bolt), extraction (a
  screw that turns but can't come out is `stuck`), states (parts removed, another
  model of the mechanism, retries that say where a fastener passed), `explain`
  (every attempt for one fastener, with the blockers) and `tools` (the kit's
  dimensions, caveats inline) all work.
- Fixed threads (`kind: insert`): a well nut, rivnut, threaded insert, cage, T-,
  press or weld nut holds itself, like a carriage bolt. It is never given a tool and
  is reported as held, and the screw into it is the one that must turn. Detection
  knows them by name (`rivnut`, `threaded_insert`, `base_well_nut`; a word before
  "nut" counts only if the solid shows no hex, so a nut deep in a well stays a nut),
  and a nut whose solid shows no hex is not covered rather than given a spanner that
  couldn't grip it.
- No sidecar needed for named parts. Fasteners are found from their part names (ISO
  and DIN designations, McMaster-Carr numbers, descriptions such as `M6x20 SHCS` or
  `hex nut M8`, code-CAD names such as `lift_link_bolt`) and completed from their
  solids: the drive the model shows (a hex, a hex socket, a cross, a slot, a carriage
  bolt's square neck) and the size that drive or the shank gives. A head drawn as a
  plain cylinder is held to the standards' outlines for its size (an M5 head 9.5 across
  and 2.75 high is ISO 7380-1's button head, not ISO 4762's socket head), and where
  none fits, the basis says its head is a guess. A head word counts
  where it touches the noun (`lid_button_screw`), as elsewhere it may describe
  something else (`button_panel_screw`); a drive word (`torx`, `hexalobular`,
  `phillips`, `pozidriv`) can describe nothing else and counts anywhere
  (`torx_lid_screw`). A hex drawn inside its nut standard's tolerance takes that
  spanner (an M8 nut at 12.8: ISO 4032 allows 12.73 to 13), the thread's own standard
  first where an inch and a metric band overlap; outside every band the reason names
  the nearest tool. A sidecar rule still describes a part outright, `across_flats:`
  gives a hex its measured size, and `checks: {detect: false}` turns detection off.
  A name with ordinary words after its fastener noun (`box_gland_vent`, `bolt_hole_cover`)
  is only a candidate: it is taken when its solid shows a drive a tool fits (a hex, a
  hex socket, a cross), and otherwise passed over, which every report lists, so a
  fastener is never missed without a word. With every fastener rule removed, the
  golden bench's 51 are all found with the right kind and size, each screw with its
  rule's head, and its 21 plates, blocks and studs named for their cells are passed over.
- `wrenchroom detect model.step > wrenchroom.yaml` writes what it found as a sidecar to
  correct and keep: one rule per fastener, and above each a comment with how sure
  detection was, what found it, the axis it resolved and how the part fares now.
  Where the name says one head and the solid's drive shows another, the drive wins
  and the comment says what the name said. A
  fastener found but not understood (a set screw, say) is written commented out with
  its reason, for you to complete, and so is a part passed over. Kept as written, the
  file reproduces every verdict.
- Collision checks run on meshes: each part tessellated once (0.2 mm), tools meshed
  from their primitives, overlap volumes from manifold3d. The golden bench scaled to
  520 fasteners is read and checked with the full kit in about 9.0 s on an Apple M5
  Max laptop (the target is 10 s). The bench is dense with fasteners that fail, and
  a failing one tries every tool it has: open ends, and ball-end keys leant every way
  round, cost most of that. `--exact` swaps in OCP boolean intersections on the
  B-rep, slower, and the referee for anything within the mesh's 0.2 mm of a curved
  face. Both engines give the bench the same report, field for field.
- A golden bench of generated cells with hand-worked truth gates every change, on both
  engines; its whole-report snapshot is byte-identical across Linux and macOS, 3.13
  and 3.14.

## From Python, and in pytest

```python
import wrenchroom as wr

asm = wr.Assembly.from_step("robot.step")  # or wr.Assembly.from_shapes([(name, shape), ...])
cfg = wr.Config.load("wrenchroom.yaml")  # optional
report = wr.check(asm, cfg, kit="metric-home")
for f in report.failures():
    print(f.name, f.tool, f.verdict, f.blocked_by)
report.to_json("report.json")
report.to_html("report.html")
report.to_markdown("report.md")
```

In CI, the pytest plugin fails the build when a design change buries a fastener.
Installing wrenchroom registers it; name the model in the project's pytest settings
(paths relative to that file) and ask for the report:

```ini
[pytest]
wrenchroom_model = cad/robot.step
; optional: wrenchroom_config (default: wrenchroom.yaml beside the model),
; wrenchroom_kit, wrenchroom_state, wrenchroom_exact = true
```

```python
def test_every_fastener_reachable(wrenchroom_report):
    wrenchroom_report.assert_all_pass()
```

A failure prints what `wrenchroom check` prints: the summary and a line per problem.
The model is checked once per session; the plugin loads nothing until a test asks
for it, and `-p no:wrenchroom` turns it off.

## What it will do

```console
$ wrenchroom check bench.step --kit full    # the golden bench's own report, verbatim
37 fasteners: 24 turn, 2 held, 10 blocked, 1 stuck, 0 not covered
  M16 nut                  spanner-24     x5    3 of 5 fail
  M6 carriage screw        -              x1    all pass (holds itself)
  ...
FAIL glands_close_a_gland  spanner-24  blocked  glands_close_b_gland
FAIL key_wall_near_screw  hex-key-5  blocked  key_wall_near_wall
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
  codes, a terminal table, Markdown to post, and a self-contained HTML 3D view.

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

The bench's HTML report is tested in the page itself: Node runs the page's own
scripts against a stand-in DOM (three's scene graph is real, so every colour can be
read), and headless Chrome opens the file and draws it with WebGL. Both come with
CI's runners; locally each test skips, saying why, if its tool is missing. The
three.js bundle in `src/wrenchroom/view/vendor/` is built by
`scripts/vendor_three.py` from a pinned npm tarball (its sha512 checked) and a pinned
esbuild; `uv run python scripts/lanes.py vendor-check` rebuilds it and compares byte
for byte, and the nightly job does the same.

CI runs the same lanes by the same names; `scripts/lanes.py` is the only spelling of how
this project runs its checks.

`main` is protected: changes land by pull request, rebased, with `gates`, every `fast` row
and both `perf` rows green, and no new high-severity CodeQL alert. The rule lives in
`.github/rulesets/main.json`, exported from GitHub; change both together. Security
reports go through [SECURITY.md](SECURITY.md).
