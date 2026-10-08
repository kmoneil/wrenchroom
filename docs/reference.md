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
with it. A part with no name of its own takes its assembly's: the names OCCT makes
up for one (`=>[0:1:1:32]`, `SOLID`, `ASSEMBLY`) say nothing of what it is. From Python, `Assembly.from_shapes([(name, shape), ...])` takes build123d
shapes as they are, each pair one part.

A part drawn as a surface, not a solid, is read for what it bounds. A closed shell, as
some exporters write a solid, is the solid it bounds. An open shell or loose faces
bound nothing a tool could meet, so the part is left out, and every report says so and
names it (`NOTE 2 parts drawn as surfaces, not solids, are left out, as nothing can
meet them: ...`, `surfaces` in the JSON, and the `not checked` line). A sidecar rule
naming only such a part says that, and fails the run, rather than "renamed part?"; an
ignore naming one is satisfied (issue #104).

## Finding fasteners

No sidecar is needed for named parts. Fasteners are found from their part names (ISO
and DIN designations, McMaster-Carr numbers, descriptions such as `M6x20 SHCS` or
`hex nut M8`, `M3 Hexnut` with the words run together, code-CAD names such as
`lift_link_bolt`) and completed from their
solids: the drive the model shows (a hex, a hex socket, a cross, a slot, a carriage
bolt's square neck) and the size that drive or the shank gives.

A head drawn as a plain cylinder is held to the standards' outlines for its size (an
M5 head 9.5 across and 2.75 high is ISO 7380-1's button head, not ISO 4762's socket
head), and where none fits, its head is a guess from its proportions: detection's
confidence is low, and the check says so (`NOTE screw: its head is a guess: ...`, and
`notes` in the JSON). A head is countersunk only where its own cone runs from the
shank out to its rim at 82 to 120 degrees: the chamfers, socket mouths, drill points
and chamfered tips makers' models are full of are cones too, and none of them makes
a head countersunk. Which keyed head (socket, button, countersunk) a hex socket sits
in is the outline's to say, so where the name gives one (`M3x16 BHCS`, `ISO 4762`),
the name's stands; where a countersink or a standard's outline shows another, the
comment `detect` writes says so, at low confidence. A shoulder screw (`head: shoulder`, ISO 7379) takes the key its
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
which every report lists, so a fastener is never missed without a word. Not a name
whose last word is a part's own noun (`nut_plate`, `gland_plate`, `screw_boss`,
`box_wall`): it says what the part is, so it isn't listed, though a solid showing a
drive is still taken (issue #75).

A name that is a thread and a length and nothing else (`M3x16`, `M3 x 16`,
`M3-0.5x16`, `M3x0.5x16`, `1/4-20x1`, `#4-40 x 1/2`), as CAD libraries and suppliers
name screws, is a screw candidate the same way: a stud, a rod or an insert is named
so as readily, so it is taken on a drive in its solid and passed over otherwise. A
bare size (`M3`) says nothing, and a name with a word of its own is about that word
(`spacer M4x10`, `M3x16 standoff`). A part named nothing a fastener is (`Part7`)
isn't checked, but one whose solid plainly looks like a fastener is listed as passed
over too (`NOTE passed over Part7: not named as a fastener, but its solid looks like
one: M3 screw, a 2.5 hex socket`): a hex socket its size's key goes into, or a cross,
in a head at one end of a shank of a standard size, or a nut's hex round a bore of
its size. So a model of unnamed screws doesn't pass without a word (issue #95).

A name is about its own phrase: a phrase in brackets or after `for` says what the
part goes with (`Nylon Washer (Thumbscrew)`, `Washer for M3 screw`), so a part whose
own noun isn't a fastener's is none, and isn't listed (issue #96).

A leadscrew, a ball screw, and the nut that runs on one (`Leadscrew Nut`, `Lead Screw
Nut`, `Ball Screw`, `T8 nut`, `Tr8x8 nut`, `trapezoidal nut`, `ACME nut`,
`anti-backlash nut`) move a part, and no tool turns them: passed over whatever the
solid shows, listed, and failing nothing (issue #117). `T8` says so of a nut only: a
`T8 screw` is a Torx screw as readily.

A set screw (`ISO 4026` to `4029`, `DIN 913` to `916`, `set screw`, `grub screw`) is
`head: set`: no head, a hex socket in one end of its thread, turned from that end
with the key its own standard gives (M3 1.5, M6 3, where a socket head cap screw takes
2.5 and 5), and backing out through its own tapped hole. A hex socket in a solid with
no head is a set screw whatever its name says. A thumb screw, a wing nut or a knurled
nut is turned by hand (`tool: hand`): no head is guessed for it, and its room is room
for fingers (below).

A hex drawn inside its nut standard's tolerance takes that spanner (an M8 nut at
12.8: ISO 4032 allows 12.73 to 13), the thread's own standard first where an inch and
a metric band overlap. A known thread keeps to its own system's tools: a hex drawn up
to 0.3 mm under its standard's band (an M8 nut at 12.6) takes that size, and the
report notes it (`NOTE nut: hex drawn undersize: ...`, and `notes` in the JSON); only
a hex exactly a size of the other system, and no size of its own, takes that, noted
too. A size from a band alone is a guess, which the name's size outranks, and a nut
takes the size of the bolt it runs on. A hex socket is drawn a little larger than
its key, as the standards allow (ISO 4762 draws a 2.5 mm key's 2.52 to 2.58, ASME
B18.3 a 5/32 in's to 0.1587 in): one drawn up to that most takes the key, and one
drawn up to 0.15 mm past it, loosely, takes it with a note (`NOTE screw: socket drawn
loose: ...`). Where no tool takes a hex, the reason names the one that fits nearest:
the smallest spanner that goes over it, or the largest key that goes into it.

A Torx head takes the size its thread's standard gives (M6 T30), unless its rule's
`across_flats:` gives the recess's point to point: then the size whose ISO 10664
recess holds it (an M8 pan head drawn for T40, as some makers sell them, where the
standards say T45).

A sidecar rule still describes a part outright, `across_flats:` gives a hex its
measured size, and `checks: {detect: false}` turns detection off. With every
fastener rule removed, the golden bench's described fasteners are all found with the
right kind and size, each screw with its rule's head, and its plates, blocks and
studs named for their cells are passed over.

`wrenchroom detect model.step > wrenchroom.yaml` writes what it found as a sidecar to
correct and keep: one rule per fastener, and above each a comment with how sure
detection was, what found it, the axis it resolved and how the part fares now. Where
the name says one head and the solid's drive shows another, the drive wins and the
comment says what the name said. A fastener found but not understood (a low-head
socket screw, say) is written commented out with its reason, for you to complete, and
so is a part passed over. Kept as written, the file reproduces every verdict.

## Which end a tool comes from

Each fastener's seat and axis come from its geometry. A screw is turned from its
head, which is its wide end: not the end with the larger flat face, which on a domed
head can be the tip's. A nut is turned from the end nothing sits against, its bolt not counted even
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
- **By hand**, for a thumb screw, a wing nut, a knurled nut (`tool: hand`, which every
  kit has): fingers round its grip, its widest part, then a fingertip on its rim from
  any one side, as a thumb wheel is turned through a window. Each is tried in place,
  as a driver is.

A tool on a hex's flats needs the room the hex's own corners sweep as it turns, and a
socket the room for its wall round the hex. A part in that first room stops the hex
whatever grips it, which is said once, before any tool is tried (`the nut's corners
hit block as it turns`).

A nut whose corners, turning, meet one part on two opposite sides sits in a trap: a
hex pocket, or a slot its own width open to one side, as printed parts hold nuts. No
tool could turn it, and none needs to: it is held (`held by its trap in block`), as a
fixed thread is, from whichever end, and its screw must turn (issue #93). One drawn
into its trap is held all the same, and noted, a press fit being as likely as a
clash. A part on one side only stops the nut turning, and blocks it, as above.

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
the tables don't hold says that instead. `tool: hand` says the fastener is turned by
hand.

A fastener nothing turns, or whose free face can't be told, is measured against the
parts that stopped it, and a screw against what its way out meets: drawn into one, it
is a clash in the model, not covered, with the shared volume (`drawn into lid (96.1
mm^3): fix the model`), not a reach problem nor an order to take things apart in
(issue #94). Only its hex and its
widest region are measured, a nut's body and flange, a head, a gland's hex and dome:
a shank or stub in a tapped hole, or a bolt drawn at its nominal diameter in a nut
bored at its minor, is a thread, and its own bolt no clash. A clash that stops
nothing changes no verdict, and isn't looked for.

A fastener drawn twice, over itself (most of each one's volume in common), as a model
drawing two optional parts in place can have it, is one fault: said once, on the
first by name (`drawn twice: M3x8 SHCS is drawn over it (120.8 mm^3 in common): fix
the model`), and the other isn't checked again, nor counted. A name's length that
the solid disagrees with by more than half a millimetre or 5% (`M3x12` drawn 8 long)
is noted, and the solid's length, which the way out meets, is the one taken: under
the head for a socket, button or hex head, overall for a countersunk head or a set
screw. A Phillips or Torx head's length isn't compared, as its standard measures a
pan head under the head and a countersunk one overall, and the drive looks the same.

A name's thread size is noted the same way where the solid is drawn as another size
(issue #117): a screw named `M5x16 SHCS` and drawn as an M3, its 2.5 socket and its
3 mm shank both an M3's, is checked as the M3 it is drawn as, noted (`NOTE M5x16
SHCS: drawn as an M3 (3.00 shank, 2.50 socket), where its name says M5: taken as
drawn`), and detected at low confidence, the comment `detect` writes saying what the
name said. Likewise a nut
by its hex and its bore, and a screw with no hex or socket (a Phillips) by its shank
alone, which used to take its name's size and a driver that doesn't fit its cross. A
thread is drawn anywhere from its minor diameter (ISO 724's, on its coarse pitch) to
its nominal, and a nut's bore up to 1.15 of it, with clearance: drawn so, it could be
the name's size, and is quiet (a 2.9 shank on an M3, an M5 drawn at its minor). So is
a hex in a nut standard's band alone, a drive that fits two sizes, and an insert's
bore, which the name outranks as before.

## Verdicts, and what decided them

Verdicts per fastener with every blocker named, led by the ones that decided it:
where a tool swings some of the arc it needs, the parts at each end of its best arc
(`explain` says `holds, best 15 of 30 deg, between post_a and post_b`), and with hand
room what stopped the hand along that arc.

A note many fasteners share (twenty nuts drawn undersize alike) is one line, naming
a few of them and how many more, as a failure's line does; the JSON keeps each
fastener's own (issue #75).

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
  `model:` path is read as one beside the sidecar, as a path in a config file
  usually is, then beside the model if the sidecar's folder hasn't it (issue #73);
  an absolute one is taken as it is. One found nowhere is an error naming the state,
  the sidecar entry and where it was looked for. A
  rule's `state:` says a fastener is reached in that state; `checks: {try_states:
  [...]}` retries failures in each state in turn, and says where a fastener passed.
  A state's model is the same parts, moved, and matched by name (issue #74): a
  fastener its model lacks isn't tried there, which fails the run (`state
  'lever-up': its model bench_lever-up.step has no part state_lever_screw (renamed?),
  so it wasn't tried there`), and a fastener whose own state it is is not covered,
  naming the model. Any other part name only one of the two models has is noted.
- **Narrowing.** `explain` and `check --only` narrow what is reported, not what is
  resolved: a fastener's pair is checked with it, so its verdict is the full run's.

## Fixed threads

`kind: insert`: a well nut, rivnut, threaded insert, cage, T-, press or weld nut holds
itself, like a carriage bolt. It is never given a tool and is reported as held, and
the screw into it is the one that must turn, and is told so when it can't
(`only holds, and it screws into a fixed thread (MB T-Nut:1), so it must turn`).
Detection knows them by name (`rivnut`, `threaded_insert`, `base_well_nut`; a word
before "nut" counts only if the solid shows no hex, so a nut deep in a well stays a
nut), and a nut whose solid shows no hex is not covered rather than given a spanner
that couldn't grip it. "Insert" alone may be a logo's inlay: with no thread size in
the name, no word such as threaded or heat-set, and no bore in the solid, it is
passed over, and the report says so. A fixed thread's size from its bore alone is a
guess (an M3 T-nut bored 2.8 is #4's size), and the screw into it outranks it, as a
nut's bolt does.

## Kits

A kit says which tools exist, and only those are tried (`--kit`; `wrenchroom tools
--kit NAME` lists them).

- `metric-home`, the default, is a home toolbox: hex keys 1.5 to 10 mm, combination
  spanners and 1/4" and 3/8" drive sockets 5.5 to 19 mm, Phillips 1 to 3 and slotted
  drivers.
- `imperial-home` is the same in inch sizes, as US home sets come: ASME B18.3 keys
  0.050 to 3/8 in, spanners 1/4 to 3/4 in, sockets 3/16 to 3/4 in.
- `full` holds every size the tables describe, both systems, its spanners and
  sockets running from 3.2 mm (an M1.6 nut's) to 50 mm for large cable glands (an
  M32 gland is commonly 41 across flats). It also has ISO 2936's 1.3 mm key and ASME
  B18.3's 0.035 in, Torx keys T6 to T40 (ISO 10664 sizes, swept like hex keys; a
  Torx head takes the size ISO 14579 and its kin give its thread, M6 T30), PH0 and PH4
  drivers (a Phillips head takes the number ISO 7045 and its kin give its thread: M8 and
  M10 PH4), ball-end keys 3 to 10 mm, and nut drivers 4 to 13 mm.

The tables run from M1.6 and #0: the screws, nuts and drives of printers, electronics
and small mechanisms. Where a standard has no such head, the reason says so (`ISO
7380-1 has no M2 button head`: button heads start at M3).

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

Anything else in an entry is an error, as elsewhere in the sidecar, and so is a key
whose short arm is longer than its long one (swapped, most likely). A tool of a kind
and size no fastener in the model takes, and no rule names, is noted (`tool
unused-key: no fastener here takes a 7 mm hex key`): written with the wrong size,
most often. One the kit's own tool beat to it is taken, and not noted.

## Room for a hand

`--hand-room`, or `checks: {hand_room: true}` in the sidecar: a hand of radius 35 mm
along each handle's last 90 mm, resting on it from the side the tool comes from, and
a fist round a driver's handle. Where the tool alone would turn and the hand can't
follow, the fastener is blocked, "no room for a hand", naming what the hand hit. Off
by default: the figures are not yet tuned against real hands, and L-key arms, turned
with the fingertips, get no hand. Every report ends by saying what it didn't check.

A fastener turned by hand is checked for its fingers whether or not hand room is: a
ring 12 mm thick round its grip and the fingers 25 mm over its end, leaving a nut's
bolt alone; or a fingertip 8 mm across reaching 30 mm out from its rim, level with
the grip's middle or resting on what the grip sits on. With hand room, the hand behind
the fingers must be clear too. These figures are untuned as well.

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
engines give the golden bench the same report, field for field. A mesh's possible
error is each face's own: one face the tessellator met its tolerance poorly on leaves
the rest of the part sure.

Real CAD doesn't always tessellate into a closed solid. A part that won't is mended
first: a face OCP won't mesh (a maker's countersink, its seam at an odd parameter) is
split, and a hole up to 2 mm across, where neighbouring faces' edges didn't meet, is
filled. One that still won't close (an open shell, a broken export) is left to the
exact engine, but only a tool at its surface costs a boolean; the rest is wholly
inside it or out, which one point tells. Every report says which parts that was, and
which parts are invalid B-reps as exported, whose collisions are approximate (`NOTE 1
part didn't mesh into a closed solid ...`, and `engine_notes` in the JSON).

The golden bench scaled to over 500 fasteners is read and checked with the full kit
in under 10 s on a laptop, the target. Its graze cells, deliberate worst cases in
which the exact engine decides every position of a key grazing all the way round, are
kept out of that figure and timed apart. The bench is dense with fasteners that fail,
and a failing one tries every tool it has: open ends, and ball-end keys leant every
way round, cost most of that.

## Standards

Dimension tables cite their standards (ISO 2936, 4762, 7380-1, 10642, 4032, 4017,
7379, 7045, 10664, 14579; ASME B18.3, B18.2.1, B18.2.2, B18.6.3) with the date checked;
approximations are labelled as such. `wrenchroom tools --kit NAME` prints each table
with its citation.

## The golden bench

A golden bench of generated cells with hand-worked truth gates every change, on both
engines; its whole-report snapshot is byte-identical across Linux and macOS, 3.13 and
3.14. See [Development](../README.md#development).
