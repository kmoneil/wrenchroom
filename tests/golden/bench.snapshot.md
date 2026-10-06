### wrenchroom: `bench.step`

**39 fasteners: 26 turn, 2 held, 10 blocked, 1 stuck, 0 not covered**

Kit `full`, ENGINE engine, wrenchroom VERSION.

Not checked: room for a hand (`checks: {hand_room: true}` turns it on); parts the model doesn't have.

| Fasteners | Tool | Count | Outcome |
| --- | --- | ---: | --- |
| M10 hex screw | `spanner-16` | 3 | all pass (ring, full length) |
| M10 nut | `socket-16` | 2 | all pass (socket, 50 mm extension) |
| M10 nut | `spanner-16` | 1 | 1 of 1 fail |
| M16 nut | `spanner-24` | 5 | 3 of 5 fail |
| M4 phillips screw | `driver-ph2` | 2 | 1 of 2 fail |
| M6 button screw | `hex-key-4` | 1 | all pass (long leg in) |
| M6 carriage screw | - | 1 | all pass (holds itself) |
| M6 hex screw | `spanner-10` | 3 | all pass (ring, full length) |
| M6 nut | `spanner-10` | 4 | all pass (ring, full length) |
| M6 socket screw | `hex-key-5` | 12 | 4 of 12 fail |
| M8 hex screw | `spanner-13` | 3 | 1 of 3 fail |
| M8 nut | `spanner-13` | 2 | 1 of 2 fail |

#### Failures

| Fastener | Tool | Verdict | In the way, or why |
| --- | --- | --- | --- |
| `gland_rib_gland` | `spanner-24` | blocked | `gland_rib_rib` |
| `glands_close_a_gland` | `spanner-24` | blocked | `glands_close_b_gland` |
| `glands_close_b_gland` | `spanner-24` | blocked | `glands_close_a_gland` |
| `key_wall_near_screw` | `hex-key-5` | blocked | `key_wall_near_wall` |
| `pair_both_hold_bolt` | `spanner-13` | blocked | `only holds, and its partner pair_both_hold_nut does not turn` |
| `pair_both_hold_nut` | `spanner-13` | blocked | `only holds, and its partner pair_both_hold_bolt does not turn` |
| `phillips_shelf_screw` | `driver-ph2` | blocked | `phillips_shelf_shelf` |
| `tail_too_long_nut` | `spanner-16` | blocked | `tail_too_long_collar`, `tail_too_long_bolt` |
| `tapped_hold_screw` | `hex-key-5` | blocked | `only holds, and it has no nut` |
| `twins_a_screw` | `hex-key-5` | blocked | `twins_wall` |
| `stuck_screw_screw` | `hex-key-5` | stuck | `stuck_screw_ceiling` |
