# Room Reservation Design

**ROOM_RESERVATION_DESIGN_STATUS: PASS**  
**IMPLEMENTATION_READY: YES**

This is the Prompt 1 requirements and design artifact. It does not modify application code, tests, the database, or other feature documentation. Prompt 2 should implement this design on the current `main` branch and run the test plan below.

## Current behavior confirmed in the checked-out project

- `Room.status` and `Room.state` describe the room’s current physical occupancy. A new immediate rental changes them to `Đang thuê` / `occupied`; checkout changes them to `Phòng trống` / `empty` and clears the room’s displayed check-in and check-out times.
- `RoomRental` stores each rental’s room ID and room-number snapshot, naive `DateTime` start and expected checkout, duration in minutes, nightly rate, and total-price snapshot. It has no explicit active/completed status and checkout does not add an actual checkout timestamp.
- For an occupied card, rendering selects the newest rental matching both `room_id` and `room_number`, ordered by `rented_at DESC, id DESC`. The adjust route uses the same latest-row ordering and also requires the Room to be occupied. Therefore the current active rental is identified by current Room state plus that latest matching record; an old rental row alone does not make a room occupied. If an occupied room has no matching rental, the UI omits adjustment and a reservation must be rejected safely because its current checkout cannot be established.
- Immediate rent starts at `datetime.now()` rounded down to the minute. The adjust route compares against a similarly naive local `datetime.now()`. Rental form input uses `%Y-%m-%dT%H:%M` and is parsed into a naive `datetime`.
- The effective nightly rental price is `_room_display_values(room)["price"]`: the saved positive Room price, otherwise the existing room-type default. `_rental_amount` multiplies the rate by duration minutes / 1,440 and rounds to a whole đồng using `ROUND_HALF_UP`.
- Startup runs `db.create_all()` and then additive `ALTER TABLE` checks for older User columns. It does not delete or recreate `instance/hotel.db`. Room deletion currently rejects an occupied room and otherwise deletes it in one commit; `RoomRental.room_id` is nullable with `ON DELETE SET NULL`, while `room_number` keeps the historical snapshot.
- Occupied cards currently have `filter: grayscale(0.95) saturate(0.25)` and `opacity: 0.42` on the image. Empty cards have green styling and occupied cards currently have a muted rose-gray treatment. Status text already appears as text and also has red/green badge styles.

## Domain model and lifecycle

Reservations are a separate schedule. Never encode a reservation by changing `Room.status`, `Room.state`, `Room.check_in`, or `Room.check_out`; those fields continue to report only current occupancy. A room can remain occupied while one or more later reservations are booked, and an empty room stays empty when a future schedule is created.

Add a `RoomReservation` table with these fields:

| Field | Proposed type and meaning |
| --- | --- |
| `id` | Integer primary key |
| `room_id` | Nullable FK to `rooms.id`, `ON DELETE SET NULL`; nullable so cancelled/completed history survives room deletion |
| `room_number` | Required short text snapshot, following `RoomRental` history behavior |
| `guest_name` | Required trimmed text, maximum 120 characters |
| `guest_phone` | Required trimmed text, maximum 30 characters |
| `reserved_from`, `reserved_until` | Required naive `DateTime` interval endpoints |
| `duration_minutes` | Required integer snapshot of interval length in minutes |
| `nightly_rate` | Required integer snapshot of the effective Room rate at booking time |
| `total_price` | Required integer snapshot calculated with `_rental_amount` semantics |
| `status` | Required short text, default `booked`; allowed values `booked`, `cancelled`, `completed` |
| `created_at` | Required naive `DateTime`, set at creation |

Add an index for `(room_id, status, reserved_from)` and, if useful for the UI query, `(status, reserved_from)`. Do not constrain a Room to one reservation: many non-overlapping rows for the same room are valid. SQLite has no simple portable exclusion constraint for interval overlap, so route validation is authoritative in this MVP.

Customer identity is deliberately limited to required `guest_name` and `guest_phone`; there is no Customer table or account linkage. Reuse the existing Vietnamese phone rule (strip non-digits for validation, then accept `0` plus a supported 10-digit mobile prefix or `84` plus nine digits). Store the trimmed entered phone text as the current profile flow does, rather than silently changing its presentation.

`booked` means the schedule is still an active commitment and can block conflicting intervals. `cancelled` means it no longer blocks. `completed` is a historical fulfilled booking and no longer blocks. No status changes merely because the clock passes a reservation boundary. This MVP provides edit and cancel for booked reservations; it does not provide a check-in conversion or automatically mark a reservation completed. The `completed` value is reserved for a later explicit fulfillment flow.

## Time intervals and conflict rules

All comparisons use half-open intervals `[start, end)`. Require both datetimes to parse exactly from `datetime-local` `%Y-%m-%dT%H:%M`, require `reserved_from < reserved_until`, and require `reserved_from > current local time rounded down to the minute`. This makes a reservation starting in the current minute invalid as no longer a future booking. Reject malformed and past values with field-level Vietnamese errors.

Keep reservation and rental schedule datetimes naive and in the same server-local wall-clock convention already used by `rent_room` and `edit_room_rental`. Do not compare them to `_utc_now()`, which is a separate naive-UTC helper used for recovery challenges. Do not introduce timezone-aware `datetime` values in these routes. Store and compare the same minute precision produced by current HTML inputs.

For every mutation, resolve the Room, its latest matching rental when the Room is occupied, its effective current price, and all booked reservations from the database. Do not trust room status, checkout time, price, total, or reservation lists submitted by the browser.

**Reservation versus current rental:** when the room is occupied, its latest current rental must exist. Reject if the requested reservation overlaps `[rental.rented_at, rental.expected_checkout)`, using the same standard interval test. Since a new reservation must start in the future, the practical rejection condition is `reserved_from < expected_checkout`; equality is allowed. For example, a current checkout at 12:00 allows a reservation from 12:00 or later and rejects one starting at 10:00. For an empty room there is no current-rental interval to check.

**Reservation versus reservation:** only `booked` rows block. Two intervals overlap when `new_start < existing_end AND new_end > existing_start`. Reject the entire create/edit operation on overlap. Touching boundaries are allowed: an existing reservation ending at 12:00 does not overlap one beginning at 12:00. Exclude the edited reservation itself from its conflict query. `cancelled` and `completed` rows never block. Include booked rows whose interval is currently underway in conflict checks; status is not silently recalculated by time.

**Reusable room schedule rule:** implement a small server-side interval conflict helper that accepts a proposed `[start, end)` and returns relevant booked reservations that overlap it. Reservation creation/edit uses it. `rent_room` supplies `[started_at, expected_checkout)` and `edit_room_rental` supplies `[rental.rented_at, proposed_expected_checkout)`. The shared rule should compare half-open intervals consistently and may accept an excluded reservation ID for edits.

**Immediate rental:** before creating a `RoomRental`, reject when its current-to-proposed-checkout interval overlaps any booked reservation. A rental ending exactly at a reservation start is allowed; a rental ending after that start is rejected. The room’s empty status remains the existing prerequisite for immediate rent.

**Rental adjustment:** before changing the latest active rental checkout, reject an extension whose rental interval overlaps any booked reservation. A checkout exactly at the reservation start is allowed. Keep existing duration and price recalculation based on the original rental start and saved rental nightly rate. Shortening a rental before a later reservation remains allowed.

**Early checkout:** retain current checkout behavior. Do not delete, modify, cancel, or complete any reservation. The room becomes empty and its display times clear. `RoomRental` remains historical as currently implemented; this feature does not add actual-checkout fields.

## Price snapshots

At reservation create/edit, resolve the effective current Room rate on the server. Persist `nightly_rate`, `duration_minutes = int((reserved_until - reserved_from).total_seconds() // 60)`, and `total_price = _rental_amount(nightly_rate, duration_minutes)`. This matches RoomRental rounding and symmetry. Never reprice saved reservation history if the Room or RoomType price later changes. Show the rate and live estimate in the modal for convenience, but ignore any submitted client price or total and recompute on every POST.

## UI and reservation management MVP

**Occupied card action layout is exactly:**

```text
[ Trả phòng ] [ Đặt trước ]
[    Điều chỉnh thuê    ]
```

Put checkout first at the left and reservation second at the right, equal width. Put adjustment on the next row at full width. Keep checkout as POST with CSRF and keep the current adjustment route. Add the `Đặt trước` trigger only to the occupied-card actions for this slice. Reservation routes and data model must accept a future reservation for an empty room too, so adding an empty-room trigger later requires no schema change.

Remove the occupied image grayscale, saturation, opacity, blur, and brightness effects entirely; use the normal fully visible image. Give empty cards a green border/accent/background treatment and occupied cards a clear red border/accent/background treatment. Retain explicit visible status text (`Phòng trống`, `Đang thuê`) and adequate text/button contrast; state must never depend on color alone.

Clicking `Đặt trước` opens a modal using the existing Rent modal styles. Show room number, guest name, phone, start and end `datetime-local` inputs, current nightly rate, duration, and estimated total. Include CSRF and the existing close/cancel/save button pattern. The backend supplies room number and price from the path/database. Preserve entered guest and time values and show safe field/service errors when validation fails.

For occupied cards, show at most the nearest upcoming `booked` reservation by `reserved_from`, formatted `dd/mm/YYYY HH:MM → dd/mm/YYYY HH:MM`. Upcoming summary means `reserved_from >= now` in local naive time. Do not show every row on the card. If a booked interval has already started but remains booked, it is not an upcoming summary; the reservation management view still shows it until the user edits or cancels/completes it.

For a small usable management flow, reuse the same per-room reservation modal to list all of that room’s booked schedules and allow Edit and Cancel. Editing reopens the same fields and reruns all conflict validation. Cancel is a POST + CSRF mutation that sets `status=cancelled` and preserves the row and price snapshot. The room card summary gives immediate visibility; the modal’s list permits inspection and management of multiple bookings without creating a large CRM/admin module. Cancelled history may be shown as a collapsed history list or omitted from the default modal; it must remain persisted.

Reservation-to-rental conversion is explicitly deferred. There is no `Nhận phòng` action in this MVP, no automatic RoomRental creation, and no automatic status promotion when the start time arrives. A future explicit check-in action may create the rental after validating that the room and schedule still permit it.

## Room deletion and room-type transfer

Reject deleting a Room while it has any `booked` reservation, with a clear message such as: `Không thể xóa phòng {number} vì còn lịch đặt trước đang hiệu lực. Hãy hủy hoặc hoàn tất lịch đặt trước trước.` Do not silently cascade-delete a booking. Cancelled/completed reservation history may remain after Room deletion because it stores the room-number snapshot. Since this project does not configure SQLite foreign-key enforcement explicitly, the delete transaction should explicitly set those historical rows’ `room_id` to `NULL` before deleting the Room; use a nullable FK with `ON DELETE SET NULL` as a database safeguard too. Do the check, history detachment, and room delete in one transaction. Preserve existing occupied-room deletion protection.

Selective Room-Type Transfer changes `Room.type` only. A reservation references the stable Room ID and snapshots its number, so transfers must not change reservation dates, status, customer snapshots, prices, or `room_id`. Include a regression test for this behavior.

## Additive database setup and transaction safety

Adding the model is a schema addition, not a database reset. The current app calls `db.create_all()` on startup; when the `room_reservations` table is absent, SQLAlchemy creates it while leaving all existing tables and rows in place. No migration needs to drop/recreate `instance/hotel.db`; do not delete the file or ask teammates to recreate local databases. Verify that startup adds the table to an existing database containing users, rooms, room types, rentals, OTP challenges, and uploaded files. Use a future versioned migration if an existing table must later be altered; `create_all()` does not retrofit columns into tables that already exist.

Reservation creation/edit validation completes before mutation. Then add/update the row and commit once. On `IntegrityError` or `SQLAlchemyError`, roll back and return a safe error; do not mutate Room or RoomRental for reservation operations. Cancellation and room deletion follow the same single-transaction / rollback rule. Schedule conflict reads and mutation should be kept in one request transaction. SQLite does not provide an exclusion constraint here, so concurrent simultaneous booking requests remain a race risk unless a later migration adds database-level serialization/constraints; for this MVP, handle database lock/commit errors safely and document this limitation.

## Authentication and request authority

- Require the current session-authenticated user for reservation create, edit, and cancel routes, matching current room actions.
- Use POST and Flask-WTF CSRF for all mutations; preserve global CSRF protection.
- Resolve the Room, current rental, price, and conflicting reservations from the database on each POST.
- Do not trust hidden room number, displayed price, JS total, claimed occupancy, checkout, or submitted reservation collection.
- Do not add email/SMS notifications, schedulers, push alerts, background jobs, automatic checkout, or automatic check-in. `NOTIFICATIONS_IMPLEMENTED = NO`.

## Prompt 2 acceptance test plan

1. Create a reservation beginning at/after an occupied rental checkout; reject overlap with that rental; allow exact checkout boundary.
2. Reject `reserved_from >= reserved_until`, malformed input, and a start in the past; accept a valid future interval.
3. Create for an occupied room and prove `Room.status`, `Room.state`, `Room.check_in`, `Room.check_out`, and the existing `RoomRental` row remain unchanged.
4. Create a reservation and prove the nightly-rate, duration, and total snapshots use server-side effective room price and the current `_rental_amount` rounding. Change Room price afterward and prove saved snapshots remain unchanged.
5. Allow multiple non-overlapping reservations; reject overlapping booked intervals; allow adjacent boundaries; prove cancelled and completed reservations do not block.
6. Prove nearest upcoming booked reservation selection for the card and multiple schedules; cancelled rows do not appear as the upcoming summary.
7. Prove `rent_room` rejects a proposed checkout overlapping a booked reservation and allows checkout exactly at or before its start.
8. Prove `edit_room_rental` rejects extension into a booked reservation and allows a checkout at the reservation boundary; verify existing rental price calculation remains unchanged.
9. Prove early checkout clears Room occupancy as before and leaves future reservation rows untouched.
10. Require login and CSRF for create/edit/cancel; reject invalid or missing Room safely; simulate a failed reservation commit and verify rollback leaves Room and RoomRental unchanged.
11. Verify booked reservations prevent Room deletion; cancelled/completed history survives room deletion with `room_id=NULL` and its room-number snapshot intact.
12. Transfer a Room’s type and prove reservation history/room linkage remains unchanged. Rerun existing rental, checkout, room-type-transfer, and complete project suites.
13. Structural UI test: occupied action DOM order is checkout then reservation on row one and full-width adjustment on row two; checkout remains POST + CSRF; reservation trigger and modal fields/CSRF/room/rate/errors render; nearest schedule appears.
14. Structural/style test: empty card remains green, occupied card remains red, visible text status remains, occupied image has no grayscale/saturation/opacity/blur/brightness reduction, and the image renders at normal opacity/filter.

## Regression risks and implementation boundaries

- The existing active-rental inference depends on occupied Room state and the latest matching rental row, not a rental status column. Keep the scope local; do not redesign rental history. Safely reject an occupied room whose active/latest record cannot be found.
- Existing rentable cards and modal use expected checkout but do not store actual checkout. Do not infer reservation fulfillment or current rental completion from the wall clock.
- Keep reservation overlaps scoped by stable `room_id`, not the room-number snapshot or mutable room type.
- Keep current rental amount rounding, current form styling, CSRF, checkout, profile/auth, OTP recovery, and selective room-type transfer behavior unchanged apart from the explicitly required schedule guard and occupied-card visual/action updates.
- Manual smoke should cover occupied A: reserve after checkout; reject overlapping time; then create a second adjacent/non-overlapping reservation; verify room remains red/occupied, image normal, actions in the approved order, nearest schedule visible, edit/cancel frees a slot, and early checkout leaves the schedule intact.

## Prompt 2 scope boundary

Expected implementation will add the `RoomReservation` model/table, reservation routes and modal/list, reusable overlap validation, guards in rent/adjust/delete flows, and focused tests. Expected implementation files include `src/hotel_app/models.py`, `src/hotel_app/app.py`, `src/hotel_app/templates/room_management.html`, the appropriate existing rental/modal template, `src/hotel_app/static/css/hotel.css`, and `tests/test_room_rentals.py` plus focused room UI tests. This Prompt 1 deliverable creates this design document only.

**NOTIFICATIONS_IMPLEMENTED: NO**  
**ROOM_RESERVATION_DESIGN_STATUS: PASS**  
**IMPLEMENTATION_READY: YES**
