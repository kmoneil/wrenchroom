### wrenchroom: `bench.step`

**107 fasteners: 83 turn, 5 held, 18 blocked, 1 stuck, 0 not covered**

Kit `full`, ENGINE engine, wrenchroom VERSION.

Not checked: room for a hand (`checks: {hand_room: true}` turns it on); 9 parts named like a fastener, with no drive or bore in the solid (passed over); parts the model doesn't have.

| Fasteners | Tool | Count | Outcome |
| --- | --- | ---: | --- |
| #0 button screw | `hex-key-0.035in` | 1 | all pass (driver straight in) |
| #0 socket screw | `hex-key-0.050in` | 1 | all pass (driver straight in) |
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
| M2 phillips screw | `driver-ph0` | 1 | all pass (driver straight in) |
| M2 socket screw | `hex-key-1.5` | 1 | all pass (driver straight in) |
| M2 torx screw | `torx-key-T6` | 1 | all pass (driver straight in) |
| M2.5 nut | `spanner-5` | 1 | all pass (ring, full length) |
| M24 nut | `spanner-36` | 1 | 1 of 1 fail |
| M3 button screw | `hex-key-2` | 1 | all pass (driver straight in) |
| M4 button screw | `hex-key-2.5` | 6 | 2 of 6 fail |
| M4 flat screw | `hex-key-2.5` | 1 | all pass (driver straight in) |
| M4 insert | - | 2 | all pass (holds itself) |
| M4 phillips screw | `driver-ph2` | 2 | 1 of 2 fail |
| M4 socket screw | `hex-key-3` | 2 | all pass (driver straight in) |
| M5 button screw | `hex-key-3` | 1 | all pass (driver straight in) |
| M5 nut | `spanner-8` | 1 | all pass (ring, full length) |
| M5 socket screw | `hex-key-4` | 1 | all pass (driver straight in) |
| M6 button screw | `hex-key-4` | 4 | 1 of 4 fail |
| M6 carriage screw | - | 1 | all pass (holds itself) |
| M6 hex screw | `spanner-10` | 5 | all pass (ring, full length) |
| M6 insert | - | 1 | all pass (holds itself) |
| M6 nut | `nut-driver-10` | 1 | all pass (nut driver straight in) |
| M6 nut | `spanner-10` | 6 | all pass (ring, full length) |
| M6 shoulder screw | `ball-end-key-4` | 1 | all pass (ball end, 20 deg off the axis) |
| M6 shoulder screw | `hex-key-4` | 4 | all pass (driver straight in) |
| M6 socket screw | `ball-end-key-5` | 1 | all pass (ball end, 25 deg off the axis) |
| M6 socket screw | `hex-key-5` | 13 | 5 of 13 fail |
| M6 torx screw | `torx-key-T30` | 1 | all pass (short leg in) |
| M8 hex screw | `spanner-13` | 8 | 1 of 8 fail |
| M8 nut | `spanner-13` | 14 | 4 of 14 fail |
| M8 socket screw | `stubby-key-6` | 1 | all pass (short leg in) |

#### Failures

| Fastener | Tool | Verdict | In the way, or why |
| --- | --- | --- | --- |
| `ball_button_screw` | `hex-key-4` | blocked | `ball_button_ceiling` |
| `big_tube_gland` | `spanner-36` | blocked | `big_tube_wall` |
| `channel_nut` | `spanner-13` | blocked | `channel_left`, `channel_right` |
| `corner_touch_nut` | `spanner-13` | blocked | `the nut's corners hit corner_touch_block as it turns` |
| `dome_rib_gland` | `spanner-15` | blocked | `only holds, and it has no nut; best arc bounded by dome_rib_rib` |
| `flat_deep_screw` | `hex-key-2.5` | blocked | `flat_deep_under`, `flat_deep_lid` |
| `gland_rib_gland` | `spanner-24` | blocked | `only holds, and it has no nut; best arc bounded by gland_rib_rib` |
| `key_wall_near_screw` | `hex-key-5` | blocked | `key_wall_near_wall` |
| `pair_both_hold_bolt` | `spanner-13` | blocked | `only holds, and its partner pair_both_hold_nut does not turn; best arc bounded by pair_both_hold_pocket_high` |
| `pair_both_hold_nut` | `spanner-13` | blocked | `only holds, and its partner pair_both_hold_bolt does not turn; best arc bounded by pair_both_hold_pocket_low` |
| `phillips_shelf_screw` | `driver-ph2` | blocked | `phillips_shelf_shelf` |
| `post_ring_nut` | `spanner-13` | blocked | `only holds, and it has no nut; best arc between post_ring_post_a and post_ring_post_b` |
| `sunk_cap_cap_nut` | `spanner-16` | blocked | `sunk_cap_plate`, `sunk_cap_cap_nut` |
| `tail_too_long_nut` | `spanner-16` | blocked | `tail_too_long_collar`, `tail_too_long_bolt` |
| `tapped_hold_screw` | `hex-key-5` | blocked | `only holds, and it has no nut; best arc bounded by tapped_hold_slot` |
| `tee_hold_screw` | `hex-key-5` | blocked | `only holds, and it screws into a fixed thread (tee_hold_tnut), so it must turn; best arc bounded by tee_hold_slot` |
| `torus_deep_screw` | `hex-key-2.5` | blocked | `torus_deep_under`, `torus_deep_lid` |
| `twins_a_screw` | `hex-key-5` | blocked | `twins_wall` |
| `stuck_screw_screw` | `hex-key-5` | stuck | `stuck_screw_ceiling` |

#### Notes

- `ball_shoulder_screw`: only a ball end turns it (ball end, 20 deg off the axis): a ball end takes much less torque than a straight key, so tightening it to its torque, or breaking it loose, may need a straight key, which can't get in
- `ball_tilt_screw`: only a ball end turns it (ball end, 25 deg off the axis): a ball end takes much less torque than a straight key, so tightening it to its torque, or breaking it loose, may need a straight key, which can't get in
- `sunk_cap_cap_nut`, `wide_dome_gland`: no ring, socket or nut driver gets on: past its hex the part is 20.00 across, wider than their bore round the hex; only an open end grips it, from the side
- `undersize_nut`: hex drawn undersize: 12.60 across flats, 0.13 under the least its M8 standard allows (12.73); taken as size 13

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
