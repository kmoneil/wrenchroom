### wrenchroom: `bench.step`

**168 fasteners: 126 turn, 11 held, 28 blocked, 3 stuck, 0 not covered**

Kit `full`, ENGINE engine, wrenchroom VERSION.

The model: 1 part drawn as a surface, not a solid, is left out, as nothing can meet it: `shelled_decal`.

Not checked: room for a hand (`checks: {hand_room: true}` turns it on); parts drawn into each other (`checks: {clashes: true}` turns it on); the build order (a `build:` list in the sidecar turns it on); 10 parts named like a fastener, with no drive or bore in the solid (passed over); 1 part named for a leadscrew or a ball screw, which no tool turns (passed over); 3 parts shaped like fasteners, not named as any (passed over); 1 part drawn as a surface, not a solid (left out); parts the model doesn't have.

| Fasteners | Tool | Count | Outcome |
| --- | --- | ---: | --- |
| #0 button screw | `hex-key-0.035in` | 1 | all pass (driver straight in) |
| #0 socket screw | `hex-key-0.050in` | 1 | all pass (driver straight in) |
| #1 phillips screw | `driver-ph0` | 1 | all pass (driver straight in) |
| #10 socket screw | `hex-key-5/32in` | 1 | all pass (driver straight in) |
| 1/4 nut | `spanner-7/16in` | 1 | all pass (ring, full length) |
| 1/4 socket screw | `hex-key-3/16in` | 1 | all pass (driver straight in) |
| 15 AF gland | `spanner-15` | 3 | 1 of 3 fail |
| 41 AF gland | `spanner-41` | 1 | all pass (ring, full length) |
| M1.6 nut | `spanner-3.2` | 1 | all pass (ring, full length) |
| M10 hex screw | `spanner-16` | 3 | all pass (ring, full length) |
| M10 nut | `socket-16` | 2 | all pass (socket, 50 mm extension) |
| M10 nut | `spanner-16` | 2 | 2 of 2 fail |
| M12 nut | `short-ring-18` | 1 | all pass (ring, full length) |
| M16 nut | `spanner-24` | 6 | 1 of 6 fail |
| M2 flat screw | `hex-key-1.3` | 1 | all pass (driver straight in) |
| M2 phillips screw | `driver-ph0` | 2 | all pass (driver straight in) |
| M2 socket screw | `hex-key-1.5` | 1 | all pass (driver straight in) |
| M2 torx screw | `torx-key-T6` | 1 | all pass (driver straight in) |
| M2.5 nut | `spanner-5` | 1 | all pass (ring, full length) |
| M24 nut | `spanner-36` | 1 | 1 of 1 fail |
| M3 button screw | `hex-key-2` | 1 | all pass (driver straight in) |
| M3 nut | - | 4 | all pass (held by its trap in trap\_stopped\_block) |
| M3 nut | `spanner-5.5` | 2 | 1 of 2 fail |
| M3 phillips screw | `driver-ph1` | 3 | all pass (driver straight in) |
| M3 screw | `hand` | 2 | all pass (fingers round its head) |
| M3 set screw | `hex-key-1.5` | 2 | 1 of 2 fail |
| M3 slotted screw | `driver-slotted` | 1 | all pass (driver straight in) |
| M3 socket screw | `hex-key-2.5` | 7 | 1 of 7 fail |
| M3 torx screw | `torx-key-T10` | 1 | all pass (driver straight in) |
| M4 button screw | `hex-key-2.5` | 6 | 2 of 6 fail |
| M4 flat screw | `hex-key-2.5` | 2 | all pass (driver straight in) |
| M4 insert | - | 2 | all pass (holds itself) |
| M4 phillips screw | `driver-ph1` | 1 | all pass (driver straight in) |
| M4 phillips screw | `driver-ph2` | 3 | 1 of 3 fail |
| M4 socket screw | `hex-key-3` | 2 | all pass (driver straight in) |
| M4 torx screw | `torx-key-T20` | 1 | all pass (driver straight in) |
| M4 torx screw | `torx-key-T25` | 1 | all pass (driver straight in) |
| M5 button screw | `hex-key-3` | 3 | all pass (driver straight in) |
| M5 nut | `spanner-8` | 1 | all pass (ring, full length) |
| M5 phillips screw | `driver-ph2` | 1 | all pass (driver straight in) |
| M5 socket screw | `hex-key-4` | 1 | all pass (driver straight in) |
| M6 button screw | `hex-key-4` | 4 | 1 of 4 fail |
| M6 carriage screw | - | 2 | 1 of 2 fail |
| M6 hex screw | `spanner-10` | 5 | all pass (ring, full length) |
| M6 insert | - | 1 | all pass (holds itself) |
| M6 nut | - | 1 | 1 of 1 fail |
| M6 nut | `hand` | 1 | all pass (fingers round it) |
| M6 nut | `nut-driver-10` | 1 | all pass (nut driver straight in) |
| M6 nut | `spanner-10` | 6 | all pass (open end, full length) |
| M6 shoulder screw | `ball-end-key-4` | 1 | all pass (ball end, 20 deg off the axis) |
| M6 shoulder screw | `hex-key-4` | 4 | all pass (driver straight in) |
| M6 socket screw | `ball-end-key-5` | 1 | all pass (ball end, 25 deg off the axis) |
| M6 socket screw | `hex-key-5` | 18 | 10 of 18 fail |
| M6 torx screw | `torx-key-T30` | 1 | all pass (short leg in) |
| M8 hex screw | - | 2 | 1 of 2 fail |
| M8 hex screw | `spanner-13` | 14 | 1 of 14 fail |
| M8 nut | - | 1 | 1 of 1 fail |
| M8 nut | `spanner-13` | 23 | 4 of 23 fail |
| M8 phillips screw | `driver-ph4` | 1 | all pass (driver straight in) |
| M8 socket screw | `stubby-key-6` | 1 | all pass (short leg in) |
| M8 torx screw | `torx-key-T40` | 1 | all pass (driver straight in) |

#### Tools

41 tools this model needs (kit full): 11 hex keys, 2 ball-end keys, 6 Torx keys, 13 spanners, 1 socket, 1 nut driver, 5 drivers, 2 others.

| Tool | Fasteners | |
| --- | ---: | --- |
| `hex-key-0.035in` | 1 | not in metric-home; only `small_inch_button_screw` |
| `hex-key-0.050in` | 1 | not in metric-home; only `small_inch_socket_screw` |
| `hex-key-1.3` | 1 | not in metric-home; only `small_flat_screw` |
| `hex-key-1.5` | 2 | only `grip_set_screw`, `small_socket_screw` |
| `hex-key-2` | 1 | only `dome_tip_screw` |
| `hex-key-2.5` | 12 |  |
| `hex-key-3` | 5 |  |
| `hex-key-5/32in` | 1 | not in metric-home; only `std_#10-32x1` |
| `hex-key-4` | 8 |  |
| `hex-key-3/16in` | 1 | not in metric-home; only `inch_pair_screw` |
| `hex-key-5` | 11 |  |
| `ball-end-key-4` | 1 | not in metric-home; no straight key gets in at `ball_shoulder_screw` |
| `ball-end-key-5` | 1 | not in metric-home; no straight key gets in at `ball_tilt_screw` |
| `torx-key-T6` | 1 | not in metric-home; only `small_torx_screw` |
| `torx-key-T10` | 1 | not in metric-home; only `unsized_M5x6_torx_screw` |
| `torx-key-T20` | 1 | not in metric-home; only `lobed_recess_fluted_screw` |
| `torx-key-T25` | 1 | not in metric-home; only `lobed_recess_plain_screw` |
| `torx-key-T30` | 1 | not in metric-home; only `torx_wall_screw` |
| `torx-key-T40` | 1 | not in metric-home; only `pan_t40_torx_screw` |
| `spanner-3.2` | 1 | not in metric-home; only `small_tiny_nut` |
| `spanner-5` | 1 | not in metric-home; only `small_little_nut` |
| `spanner-5.5` | 1 | only `misnamed_M5_nut` |
| `spanner-8` | 1 | only `w4032_nut` |
| `spanner-10` | 10 | 2 at once on a joint |
| `spanner-10, stubby` | 1 | no full-length spanner swings at `nut_stubby_box_nut` |
| `spanner-7/16in` | 1 | not in metric-home; only `inch_pair_nut` |
| `spanner-13` | 31 | 2 at once on a joint |
| `spanner-13, stubby` | 1 | no full-length spanner swings at `reach_13_nut` |
| `spanner-15` | 2 | only `snug_dome_gland`, `wide_dome_gland` |
| `spanner-16` | 3 |  |
| `spanner-24` | 5 | not in metric-home |
| `spanner-41` | 1 | not in metric-home; only `big_gland_gland` |
| `socket-16` | 2 | only `nut_deep_well_nut`, `tail_in_socket_nut` |
| `nut-driver-10` | 1 | not in metric-home; only `nut_tube_nut` |
| `driver-ph0` | 3 | not in metric-home |
| `driver-slotted` | 1 | only `unsized_M5x6_slotted_screw` |
| `driver-ph1` | 4 |  |
| `driver-ph2` | 3 |  |
| `driver-ph4` | 1 | not in metric-home; only `ph4_screw` |
| `stubby-key-6` | 1 | not in metric-home; only `short_key_screw` |
| `short-ring-18` | 1 | not in metric-home; only `shop_spanner_nut` |

- By hand: 3 (`grip_thumb_screw`, `grip_wheel_thumbscrew`, `grip_wing_nut`)
- No tool needed: 9, held by themselves or a trap
- No tool yet: 28 blocked (wrenchroom check says why)
- Blocked, once reached: `hex-key-1.5` x1, `hex-key-2.5` x3, `hex-key-4` x1, `hex-key-5` x7, `spanner-5.5` x1, `spanner-13` x5, `spanner-15` x1, `spanner-16` x2, `spanner-24` x1, `spanner-36` x1 (only blocked fasteners need it: `big_tube_gland`), `driver-ph2` x1

#### Failures

| Fastener | Tool | Verdict | In the way, or why |
| --- | --- | --- | --- |
| `ball_button_screw` | `hex-key-4` | blocked | `ball_button_ceiling` |
| `big_tube_gland` | `spanner-36` | blocked | `big_tube_wall` |
| `build_buried_early_screw` | `hex-key-5` | blocked | `build_buried_cover` |
| `build_buried_late_screw` | `hex-key-5` | blocked | `build_buried_cover` |
| `carriage_trap_bolt` | - | blocked | `holds itself, and its nut (carriage_trap_nut) is held by its trap in carriage_trap_base: nothing in the joint turns` |
| `carriage_trap_nut` | - | blocked | `held by its trap in carriage_trap_base, and its bolt (carriage_trap_bolt) holds itself: nothing in the joint turns` |
| `channel_nut` | `spanner-13` | blocked | `channel_left`, `channel_right` |
| `corner_touch_nut` | `spanner-13` | blocked | `the nut's corners hit corner_touch_block as it turns` |
| `dome_rib_gland` | `spanner-15` | blocked | `only holds, and it has no nut; best arc bounded by dome_rib_rib` |
| `flat_deep_screw` | `hex-key-2.5` | blocked | `flat_deep_under`, `flat_deep_lid` |
| `gland_rib_gland` | `spanner-24` | blocked | `only holds, and it has no nut; best arc bounded by gland_rib_rib` |
| `head_trap_both_bolt` | - | blocked | `held by its trap in head_trap_plate, and its nut (head_trap_both_nut) is held by its trap in head_trap_base: nothing in the joint turns` |
| `head_trap_both_nut` | - | blocked | `held by its trap in head_trap_base, and its bolt (head_trap_both_bolt) is held by its trap in head_trap_plate: nothing in the joint turns` |
| `key_wall_near_screw` | `hex-key-5` | blocked | `key_wall_near_wall` |
| `pair_both_hold_bolt` | `spanner-13` | blocked | `only holds, and its partner pair_both_hold_nut does not turn; best arc bounded by pair_both_hold_pocket_high` |
| `pair_both_hold_nut` | `spanner-13` | blocked | `only holds, and its partner pair_both_hold_bolt does not turn; best arc bounded by pair_both_hold_pocket_low` |
| `phillips_shelf_screw` | `driver-ph2` | blocked | `phillips_shelf_shelf` |
| `post_ring_nut` | `spanner-13` | blocked | `only holds, and it has no nut; best arc between post_ring_post_a and post_ring_post_b` |
| `reach_55_nut` | `spanner-5.5` | blocked | `reach_55_wall`, `reach_55_shelf` |
| `set_sunk_screw` | `hex-key-1.5` | blocked | `set_sunk_hub` |
| `shelled_screw` | `hex-key-5` | blocked | `shelled_ceiling` |
| `sunk_cap_cap_nut` | `spanner-16` | blocked | `sunk_cap_plate`, `sunk_cap_cap_nut` |
| `tail_too_long_nut` | `spanner-16` | blocked | `tail_too_long_collar`, `tail_too_long_bolt` |
| `tapped_hold_screw` | `hex-key-5` | blocked | `only holds, and it has no nut; best arc bounded by tapped_hold_slot` |
| `tee_hold_screw` | `hex-key-5` | blocked | `only holds, and it screws into a fixed thread (tee_hold_tnut), so it must turn; best arc bounded by tee_hold_slot` |
| `torus_deep_screw` | `hex-key-2.5` | blocked | `torus_deep_under`, `torus_deep_lid` |
| `trap_stopped_screw` | `hex-key-2.5` | blocked | `only holds, and its nut (trap_stopped_nut) is held by its trap in trap_stopped_block, so it must turn; best arc bounded by trap_guide` |
| `twins_a_screw` | `hex-key-5` | blocked | `twins_wall` |
| `build_way_in_over_screw` | `hex-key-5` | stuck | `build_way_in_over` |
| `build_way_in_under_screw` | `hex-key-5` | stuck | `build_way_in_under` |
| `stuck_screw_screw` | `hex-key-5` | stuck | `stuck_screw_ceiling` |

#### Connectors

**5 connectors: 4 unplug, 1 stuck, 0 not covered**

| Connector | Verdict | In the way, or why |
| --- | --- | --- |
| `plug_shelf_plug` | stuck | `plug_shelf_shelf` |

#### Notes

- `ball_shoulder_screw`: only a ball end turns it (ball end, 20 deg off the axis): a ball end takes much less torque than a straight key, so tightening it to its torque, or breaking it loose, may need a straight key, which can't get in
- `ball_tilt_screw`: only a ball end turns it (ball end, 25 deg off the axis): a ball end takes much less torque than a straight key, so tightening it to its torque, or breaking it loose, may need a straight key, which can't get in
- `cross_drawn_m4_screw`: cross drawn for PH1 (3.00 across its wings), where an M4's standard gives PH2: taken as drawn
- `sunk_cap_cap_nut`, `wide_dome_gland`: no ring, socket or nut driver gets on: past its hex the part is 20.00 across, wider than their bore round the hex; only an open end grips it, from the side
- `undersize_nut`: hex drawn undersize: 12.60 across flats, 0.13 under the least its M8 standard allows (12.73); taken as size 13
- `w10642_screw`: socket drawn loose: 2.60 across flats, 0.02 past the most the standards allow a 2.5 key's (2.58); taken as size 2.5

#### Marginal

- `flat_graze_screw`: turns with `hex-key-2.5`, grazing `flat_graze_under`
- `torus_graze_screw`: turns with `hex-key-2.5`, grazing `torus_graze_under`

#### Passed over

- `nut_stubby_box_box`: noun 'nut', words after it; its solid shows no hex, hex socket or cross a tool fits
- `nyloc_two_bodies_dome`: noun 'nyloc', words after it; its solid shows no hex, hex socket or cross a tool fits
- `pair_nut_held_upper`: noun 'nut', words after it; its solid shows no hex, hex socket or cross a tool fits
- `pair_nut_held_lower`: noun 'nut', words after it; its solid shows no hex, hex socket or cross a tool fits
- `pair_nut_held_pocket`: noun 'nut', words after it; its solid shows no hex, hex socket or cross a tool fits
- `nut_tube_tube`: noun 'nut', words after it; its solid shows no hex, hex socket or cross a tool fits
- `nut_gap_stud`: noun 'nut', words after it; its solid shows no hex, hex socket or cross a tool fits
- `flange_nut_stud`: noun 'nut', words after it; its solid shows no hex, hex socket or cross a tool fits
- `badge_insert`: noun 'insert'; named only as an insert, with no thread size or word such as threaded, and its solid shows no bore: an inlay, not a fixed thread
- `std_M8x60`: thread and length M8x60; its solid shows no hex, hex socket or cross a tool fits
- and 4 more (the JSON lists every one)
