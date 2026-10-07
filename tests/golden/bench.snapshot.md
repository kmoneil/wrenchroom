### wrenchroom: `bench.step`

**75 fasteners: 60 turn, 3 held, 11 blocked, 1 stuck, 0 not covered**

Kit `full`, ENGINE engine, wrenchroom VERSION.

Not checked: room for a hand (`checks: {hand_room: true}` turns it on); 22 parts named like a fastener, with no drive in the solid (passed over); parts the model doesn't have.

| Fasteners | Tool | Count | Outcome |
| --- | --- | ---: | --- |
| 1/4 nut | `spanner-7/16in` | 1 | all pass (ring, full length) |
| 1/4 socket screw | `hex-key-3/16in` | 1 | all pass (driver straight in) |
| 41 AF gland | `spanner-41` | 1 | all pass (ring, full length) |
| M10 hex screw | `spanner-16` | 3 | all pass (ring, full length) |
| M10 nut | `socket-16` | 2 | all pass (socket, 50 mm extension) |
| M10 nut | `spanner-16` | 1 | 1 of 1 fail |
| M16 nut | `spanner-24` | 6 | 1 of 6 fail |
| M4 button screw | `hex-key-2.5` | 5 | 2 of 5 fail |
| M4 insert | - | 1 | all pass (holds itself) |
| M4 phillips screw | `driver-ph2` | 2 | 1 of 2 fail |
| M5 button screw | `hex-key-3` | 1 | all pass (driver straight in) |
| M6 button screw | `hex-key-4` | 3 | all pass (driver straight in) |
| M6 carriage screw | - | 1 | all pass (holds itself) |
| M6 hex screw | `spanner-10` | 5 | all pass (ring, full length) |
| M6 nut | `nut-driver-10` | 1 | all pass (nut driver straight in) |
| M6 nut | `spanner-10` | 5 | all pass (ring, full length) |
| M6 shoulder screw | `hex-key-4` | 4 | all pass (driver straight in) |
| M6 socket screw | `ball-end-key-5` | 1 | all pass (ball end, 25 deg off the axis) |
| M6 socket screw | `hex-key-5` | 12 | 4 of 12 fail |
| M6 torx screw | `torx-key-T30` | 1 | all pass (short leg in) |
| M8 hex screw | `spanner-13` | 8 | 1 of 8 fail |
| M8 nut | `spanner-13` | 10 | 2 of 10 fail |

#### Failures

| Fastener | Tool | Verdict | In the way, or why |
| --- | --- | --- | --- |
| `channel_nut` | `spanner-13` | blocked | `channel_left`, `channel_right` |
| `flat_deep_screw` | `hex-key-2.5` | blocked | `flat_deep_lid`, `flat_deep_under` |
| `gland_rib_gland` | `spanner-24` | blocked | `only holds, and it has no nut` |
| `key_wall_near_screw` | `hex-key-5` | blocked | `key_wall_near_wall` |
| `pair_both_hold_bolt` | `spanner-13` | blocked | `only holds, and its partner pair_both_hold_nut does not turn` |
| `pair_both_hold_nut` | `spanner-13` | blocked | `only holds, and its partner pair_both_hold_bolt does not turn` |
| `phillips_shelf_screw` | `driver-ph2` | blocked | `phillips_shelf_shelf` |
| `tail_too_long_nut` | `spanner-16` | blocked | `tail_too_long_collar`, `tail_too_long_bolt` |
| `tapped_hold_screw` | `hex-key-5` | blocked | `only holds, and it has no nut` |
| `torus_deep_screw` | `hex-key-2.5` | blocked | `torus_deep_lid`, `torus_deep_under` |
| `twins_a_screw` | `hex-key-5` | blocked | `twins_wall` |
| `stuck_screw_screw` | `hex-key-5` | stuck | `stuck_screw_ceiling` |

#### Notes

- `undersize_nut`: hex drawn undersize: 12.60 across flats, 0.13 under the least its M8 standard allows (12.73); taken as size 13

#### Marginal

- `flat_graze_screw`: turns with `hex-key-2.5`, grazing `flat_graze_under`
- `torus_graze_screw`: turns with `hex-key-2.5`, grazing `torus_graze_under`

#### Passed over

- `nut_stubby_box_floor`: noun 'nut', words after it; its solid shows no hex, hex socket or cross a tool fits
- `nut_stubby_box_box`: noun 'nut', words after it; its solid shows no hex, hex socket or cross a tool fits
- `nut_deep_well_plate`: noun 'nut', words after it; its solid shows no hex, hex socket or cross a tool fits
- `nut_deep_well_block`: noun 'nut', words after it; its solid shows no hex, hex socket or cross a tool fits
- `glands_close_plate`: noun 'glands', words after it; its solid shows no hex, hex socket or cross a tool fits
- `glands_apart_plate`: noun 'glands', words after it; its solid shows no hex, hex socket or cross a tool fits
- `gland_rib_plate`: noun 'gland', words after it; its solid shows no hex, hex socket or cross a tool fits
- `gland_rib_rib`: noun 'gland', words after it; its solid shows no hex, hex socket or cross a tool fits
- `nyloc_two_bodies_plate`: noun 'nyloc', words after it; its solid shows no hex, hex socket or cross a tool fits
- `nyloc_two_bodies_dome`: noun 'nyloc', words after it; its solid shows no hex, hex socket or cross a tool fits
- and 12 more (the JSON lists every one)
