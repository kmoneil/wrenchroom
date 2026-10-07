# wrenchroom reference

How wrenchroom reads a model, which tools it tries and how, and what each report
says, in detail. The [README](../README.md) is the place to start; this is where the
rules and the figures behind them are written down.

- [Reading the model](#reading-the-model)
- [Finding fasteners](#finding-fasteners)
- [Which end a tool comes from](#which-end-a-tool-comes-from)
- [How each tool is tried](#how-each-tool-is-tried)
- [Verdicts, and what decided them](#verdicts-and-what-decided-them)
- [Pairs, extraction and states](#pairs-extraction-and-states)
- [Fixed threads](#fixed-threads)
- [Kits](#kits)
- [Your own tools](#your-own-tools)
- [Room for a hand](#room-for-a-hand)
- [The sidecar's globs](#the-sidecars-globs)
- [Reports](#reports)
- [Collision engines and speed](#collision-engines-and-speed)
- [Standards](#standards)
- [The golden bench](#the-golden-bench)

## Reading the model

`wrenchroom check model.step` reads a STEP assembly with its part names kept, and
repeats made unique. A part drawn as several solids, a nut and its washer, is one
part to a rule and to detection: its largest solid keeps the name and the rest go
with it. From Python, `Assembly.from_shapes([(name, shape), ...])` takes build123d
shapes as they are, each pair one part.

## Finding fasteners

No sidecar is needed for named parts. Fasteners are found from their part names (ISO
and DIN designations, McMaster-Carr numbers, descriptions such as `M6x20 SHCS` or
`hex nut M8`, code-CAD names such as `lift_link_bolt`) and completed from their
solids: the drive the model shows (a hex, a hex socket, a cross, a slot, a carriage
bolt's square neck) and the size that drive or the shank gives.

A head drawn as a plain cylinder is held to the standards' outlines for its size (an
M5 head 9.5 across and 2.75 high is ISO 7380-1's button head, not ISO 4762's socket
head), and where none fits, its head is a guess from its proportions: detection's
confidence is low, and the check says so (`NOTE screw: its head is a guess: ...`, and
`notes` in the JSON). A shoulder screw (`head: shoulder`, ISO 7379) takes the key its
thread sets, smaller than a cap screw's (an M6 on an 8 mm shoulder takes 4 mm);
`shoulder` in a name says so, and so does a plain head of ISO 7379's outline over its
shoulder (13 by 5.5 over 8 mm is an M6's); a shoulder drawn without its thread, or
with it at no size, is sized by ISO 7379's table.

A head word counts where it touches the noun (`lid_button_screw`), as elsewhere it may
describe something else (`button_panel_screw`); a drive word (`torx`, `hexalobular`,
`phillips`, `pozidriv`) can describe nothing else and counts anywhere
(`torx_lid_screw`). A name with ordinary words after its fastener noun
(`box_gland_vent`, `bolt_hole_cover`) is only a candidate: it is taken when its solid
shows a drive a tool fits (a hex, a hex socket, a cross), and otherwise passed over,
which every report lists, so a fastener is never missed without a word.

A hex drawn inside its nut standard's tolerance takes that spanner (an M8 nut at
12.8: ISO 4032 allows 12.73 to 13), the thread's own standard first where an inch and
a metric band overlap. A known thread keeps to its own system's tools: a hex drawn up
to 0.3 mm under its standard's band (an M8 nut at 12.6) takes that size, and the
report notes it (`NOTE nut: hex drawn undersize: ...`, and `notes` in the JSON); only
a hex exactly a size of the other system, and no size of its own, takes that, noted
too. A size from a band alone is a guess, which the name's size outranks, and a nut
takes the size of the bolt it runs on. Where no tool takes a hex, the reason names
the one that fits nearest: the smallest spanner that goes over it, or the largest key
that goes into it.

A sidecar rule still describes a part outright, `across_flats:` gives a hex its
measured size, and `checks: {detect: false}` turns detection off. With every
fastener rule removed, the golden bench's described fasteners are all found with the
right kind and size, each screw with its rule's head, and its plates, blocks and
studs named for their cells are passed over.

`wrenchroom detect model.step > wrenchroom.yaml` writes what it found as a sidecar to
correct and keep: one rule per fastener, and above each a comment with how sure
detection was, what found it, the axis it resolved and how the part fares now. Where
the name says one head and the solid's drive shows another, the drive wins and the
comment says what the name said. A fastener found but not understood (a set screw,
say) is written commented out with its reason, for you to complete, and so is a part
passed over. Kept as written, the file reproduces every verdict.

## Which end a tool comes from

Each fastener's seat and axis come from its geometry. A screw is turned from its
head. A nut is turned from the end nothing sits against, its bolt not counted even
where it is drawn into the nut, as a bolt at its nominal diameter is in a nut bored at
the thread's minor; or, drawn off its seat with its washer left out, from the end with
the more room. A rule's `axis:` (`+x` to `-z`, or `[x, y, z]`, pointing to where the
tool comes from) settles it outright.

## How each tool is tried

Real tools against the real parts:

- **Hex and Torx keys**: driver straight in, short leg in, long leg in. Ball-end keys
  (in the `full` kit) are tried when no straight key gets in: the long leg leant up
  to 25 degrees off the axis, Bondhus' and Wiha's figure, every way round, in socket
  heads and shoulder screws only (a button or countersunk head's socket is barely
  deeper than the ball). A pass only a ball end reaches says so, as a ball end takes
  much less torque than a straight key.
- **Combination spanners**: the ring, then the open end from the side, each at full
  length and then stubby, in the sizes stubbies are sold: 6 to 32 mm and 1/4 to
  1-1/4 in. The lengths are makers', the longest of a few makers' standard series at
  each size. Each needs 30 degrees of free swing.
- **Sockets** on a ratchet, then on each stock extension.
- **Phillips and slotted drivers**.
- **Nut drivers** (in the `full` kit), tried last, straight in, where nothing that
  swings can get down to a nut.

A tool on a hex's flats needs the room the hex's own corners sweep as it turns, and a
socket the room for its wall round the hex. A part in that first room stops the hex
whatever grips it, which is said once, before any tool is tried (`the nut's corners
hit block as it turns`).

A tool grips the hex where its flats are, not the part's widest region (a flange, or
a gland's dome), and a ring, socket or nut driver has to get on over whatever the
part has past its hex: a dome wider than their bore leaves only the open end, and the
report says so.

A rule's `tool:` picks the one tool tried, and it must fit (issue #72): of the kind
the drive takes (a spanner, socket or nut driver on a hex; a hex key in a hex socket;
a Torx key in a Torx recess; the driver of the right tip), at a size the fastener
takes, either the one the unforced check would choose (a given hex, else the thread's
standard one) or the hex the solid shows. One that doesn't fit is not covered, and
says so (`its tool: spanner-10 is 10 across flats, but the nut (M8) takes 13`); where
the model's hex really is another size, `across_flats:` in the rule says so. A tool
the tables don't hold says that instead.

A fastener nothing turns, or whose free face can't be told, is measured against the
parts that stopped it: drawn into one, it is a clash in the model, not covered, with
the shared volume (`drawn into lid (96.1 mm^3): fix the model`). Only its hex and its
widest region are measured, a nut's body and flange, a head, a gland's hex and dome:
a shank or stub in a tapped hole, or a bolt drawn at its nominal diameter in a nut
bored at its minor, is a thread, and its own bolt no clash. A clash that stops
nothing changes no verdict, and isn't looked for.

## Verdicts, and what decided them

Verdicts per fastener with every blocker named, led by the ones that decided it:
where a tool swings some of the arc it needs, the parts at each end of its best arc
(`explain` says `holds, best 15 of 30 deg, between post_a and post_b`), and with hand
room what stopped the hand along that arc.

A failure's line names each part once and three at most, the one hit at the most
positions first, then how many more (`only holds, and it has no nut; best arc between
post_a and post_b`; `no room for a hand: the hand hits deck_plate, deck_guard, rail
and 18 more on its best arc`). The JSON (`blocked_by`, `deciding`), `explain` and
the 3D view list them all.

An overlap above noise but under the 0.05 mm^3 floor is a graze: not a hit, but when
one decides a verdict the report says so (`NOTE marginal: ... the tool grazing ...`,
and `grazes` in the JSON).

## Pairs, extraction and states

- **Pairs.** A nut that only holds passes through its turning bolt, and the other way
  round. Screws and nuts pair when their axes agree; the sidecar's `pairs:` forces a
  pair geometry wouldn't make.
- **Extraction.** A screw that turns but can't come out along its axis is `stuck`.
- **States.** A state takes parts off (`remove:`), or is another model of the same
  parts with the mechanism moved (`model:`), and may build on another (`base:`). A
  rule's `state:` says a fastener is reached in that state; `checks: {try_states:
  [...]}` retries failures in each state in turn, and says where a fastener passed.
- **Narrowing.** `explain` and `check --only` narrow what is reported, not what is
  resolved: a fastener's pair is checked with it, so its verdict is the full run's.

## Fixed threads

`kind: insert`: a well nut, rivnut, threaded insert, cage, T-, press or weld nut holds
itself, like a carriage bolt. It is never given a tool and is reported as held, and
the screw into it is the one that must turn. Detection knows them by name (`rivnut`,
`threaded_insert`, `base_well_nut`; a word before "nut" counts only if the solid shows
no hex, so a nut deep in a well stays a nut), and a nut whose solid shows no hex is not
covered rather than given a spanner that couldn't grip it.

## Kits

A kit says which tools exist, and only those are tried (`--kit`; `wrenchroom tools
--kit NAME` lists them).

- `metric-home`, the default, is a home toolbox: hex keys 1.5 to 10 mm, combination
  spanners and 1/4" and 3/8" drive sockets 5.5 to 19 mm, Phillips 1 to 3 and slotted
  drivers.
- `imperial-home` is the same in inch sizes, as US home sets come: ASME B18.3 keys
  0.050 to 3/8 in, spanners 1/4 to 3/4 in, sockets 3/16 to 3/4 in.
- `full` holds every size the tables describe, both systems, its spanners and
  sockets reaching 50 mm for large cable glands (an M32 gland is commonly 41 across
  flats). It also has Torx keys T10 to T40 (ISO 10664 sizes, swept like hex keys; a
  Torx head takes the size ISO 14579 and its kin give its thread, M6 T30), ball-end
  keys 3 to 10 mm, and nut drivers 5.5 to 13 mm.

A fastener that needs a tool the kit lacks is not covered, and the reason names the
tool and the kits that have it (`needs spanner-24, which kit metric-home does not hold
(full has it)`).

Inch tools carry their unit (`spanner-7/16in`), and inch fasteners (`#10`, `1/4`,
`3/4`; UNC and UNF alike) take their ASME tools: socket, button and flat heads
(B18.3), nuts (B18.2.2, B18.6.3) and hex heads (B18.2.1), which part ways with their
nuts at 7/16 and 9/16.

## Your own tools

Tools a kit doesn't have (a long-series or short-arm key, a shop-made spanner, a
thin-wall socket, a long screwdriver) go in the sidecar's `tools:` list, each by the
numbers the built-in tables hold for its kind, and swept the same way. They join
whatever kit is used: a fastener of their kind and size tries the kit's own tools
first, then the sidecar's, in its order, and a rule's `tool:` may name one.
`wrenchroom tools --config wrenchroom.yaml` lists them after the kit's own.

```yaml
tools:
  - name: stubby-key-5          # the name reports give it; never a built-in's
    type: hex-key               # hex-key, torx-key, spanner, socket, nut-driver, driver
    across_flats: 5
    long: 60
    short: 20
  - name: shop-spanner-24
    type: spanner
    across_flats: 24
    length: 300                 # the head defaults to the built-in 24's
    ends: [ring]                # ring, open, or both (the default)
```

The kinds and their numbers, mm (optional ones, in brackets, default to the built-in
tool's for the size):

| Type | Numbers |
| --- | --- |
| `hex-key` | across_flats, long, short (across_corners) |
| `torx-key` | size, long, short (point_to_point) |
| `spanner` | across_flats, length (stubby, ends, head_thickness, ring_outer_radius, handle_width, open_width, open_thickness) |
| `socket` | across_flats (outer_radius, length) |
| `nut-driver` | across_flats (outer_radius, handle_radius, handle_length) |
| `driver` | tip (shaft_radius, shaft_length) |

Anything else in an entry is an error, as elsewhere in the sidecar.

## Room for a hand

`--hand-room`, or `checks: {hand_room: true}` in the sidecar: a hand of radius 35 mm
along each handle's last 90 mm, resting on it from the side the tool comes from, and
a fist round a driver's handle. Where the tool alone would turn and the hand can't
follow, the fastener is blocked, "no room for a hand", naming what the hand hit. Off
by default: the figures are not yet tuned against real hands, and L-key arms, turned
with the fingertips, get no hand. Every report ends by saying what it didn't check.

## The sidecar's globs

A sidecar glob that matches nothing (a rule's parts or mates, an ignore, a state's
removal, `--only`) is reported and fails the run: that is how a renamed part hides. A
rule's `mates:` (parts that travel with the fastener and leave its scene, such as a
washer or a nyloc's separate dome) take globs like the rest. A later rule replaces an
earlier one, whole, for the parts both match, so a broad glob can set the family and
a narrow one, written out in full, the exception.

## Reports

A terminal table, JSON (`--json FILE`), Markdown for a CI job summary or a PR comment
(`--md FILE`), and the 3D view (`--html FILE`). Exit codes for CI: 0 pass, 1 a
fastener fails, 2 not covered or a config error. A FILE of `-` writes that report to
stdout instead and moves the table to stderr, so it can be piped: `--json - | jq`,
`--md - >> "$GITHUB_STEP_SUMMARY"`. Only one report can go to stdout; a file really
named `-` is `./-`.

Names come from the model, so the terminal shows control characters written out and
the Markdown puts every name in a code span: a crafted part name can't steer a
terminal or post a link or an image in a comment.

The 3D view is one self-contained file that opens offline. The assembly is grey and
each fastener coloured by how it fared (green turns, blue held, amber passes only in
another state, red blocked or stuck, grey not covered). Click one, or pick it from the
list, to see every tool position that was tried, drawn translucent where the check put
it (orange where it hit something), with the parts in its way in magenta; a fastener
reached in another state is drawn in that state. `wrenchroom explain model.step NAME
--html f.html` writes the same view opened on one fastener, and `report.html#NAME`
opens any fastener directly. The page embeds three.js (r186, MIT) and its content
security policy lets it load nothing and run nothing but its own two scripts, so a
report of a private model can't send anything anywhere.

## Collision engines and speed

Collision checks run on meshes: each part tessellated once (0.2 mm), tools meshed
from their primitives, overlap volumes from manifold3d. The mesh engine decides alone
only beyond doubt (a hit whose overlap stays over the floor with the mesh's possible
error taken off, a clear wider than a part's mesh can stray) and asks the exact
engine, OCP boolean intersections on the B-rep, about the rest, so the two agree, a
key grazing a face included. `--exact` uses the exact engine throughout, slower. Both
engines give the golden bench the same report, field for field.

The golden bench scaled to over 500 fasteners is read and checked with the full kit
in under 10 s on a laptop, the target. Its graze cells, deliberate worst cases in
which the exact engine decides every position of a key grazing all the way round, are
kept out of that figure and timed apart. The bench is dense with fasteners that fail,
and a failing one tries every tool it has: open ends, and ball-end keys leant every
way round, cost most of that.

## Standards

Dimension tables cite their standards (ISO 2936, 4762, 7380-1, 10642, 4032, 7379,
10664, 14579; ASME B18.3, B18.2.1, B18.2.2, B18.6.3) with the date checked;
approximations are labelled as such. `wrenchroom tools --kit NAME` prints each table
with its citation.

## The golden bench

A golden bench of generated cells with hand-worked truth gates every change, on both
engines; its whole-report snapshot is byte-identical across Linux and macOS, 3.13 and
3.14. See [Development](../README.md#development).
