# Design: Room Cleaning and Maintenance States

**Stage:** Requirements, business logic, data model, and UI design only  
**Source of truth:** Current local working tree  
**Implementation status:** Not implemented in this stage

## 1. Current behavior and scope

Room currently stores two independent fields: status (display text) and state (canonical UI value). The supported pairs are Phòng trống / empty and Đang thuê / occupied. There is no RoomServiceLog model. Checkout currently clears check_in and check_out and changes the Room directly from occupied to empty. The room list accepts all, empty, and occupied; invalid filters fall back to all. Status counts are ordered through ROOM_STATUS_ORDER and currently cover two statuses. Room creation defaults to empty. Room Update currently offers only empty and occupied and writes both fields from that choice.

The current rent route already requires both empty status and empty state. Reservation validation allows empty rooms and occupied rooms with a matching rental, while rejecting other operational states. Room deletion currently blocks occupied rooms and rooms with a booked reservation, then preserves non-booked reservation history by detaching it. It does not yet know about cleaning or maintenance. Room-Type Transfer changes only Room.type and does not restrict operational state. Home renders a textual status and a state-derived card class; it currently displays a total room count, not the room status summary.

This design adds actual cleaning and maintenance periods. It does not add a cleaning timer, reservation check-in, work orders, assignment, costs, or notifications. It does not change reservation overlap rules or implement a 60-minute scheduling buffer.

## 2. Canonical state mapping

Every Room transition must write the display status and canonical state together from this mapping. Routes must reject invalid or mismatched pairs instead of trusting either field alone.

| Display status | Canonical state | Card treatment |
| --- | --- | --- |
| Phòng trống | empty | Green |
| Đang thuê | occupied | Red |
| Dọn dẹp | cleaning | Yellow |
| Bảo trì | maintenance | Blue |

Text labels remain visible on cards, filters, and accessible names; color is supplementary. Images stay at normal brightness and opacity. Current Room.status (String(32)) and Room.state (String(24)) columns can hold these values. No Room columns or Room schema migration are needed.

## 3. State machine and transition effects

    Phòng trống --Cho thuê--> Đang thuê --Trả phòng--> Dọn dẹp --Hoàn tất dọn dẹp--> Phòng trống
         |                                                        |
         +--Cập nhật: Bảo trì--> Bảo trì <--Cập nhật: Bảo trì-----+
                                  |
                                  +--Hoàn tất bảo trì--> Dọn dẹp

| From | User action | To | Service-log effect |
| --- | --- | --- | --- |
| Empty | Rent | Occupied | Existing rental behavior; no service log |
| Occupied | Checkout | Cleaning | Create an open cleaning log at checkout time |
| Cleaning | Complete cleaning | Empty | Close its active cleaning log |
| Cleaning | Update and choose maintenance | Maintenance | Close cleaning log and create open maintenance log atomically |
| Empty | Update and choose maintenance | Maintenance | Create open maintenance log |
| Maintenance | Complete maintenance | Cleaning | Close maintenance log and create a new open cleaning log atomically |

Maintenance must never transition directly to empty. Occupied must never transition to maintenance through Room Update; checkout is required first. Cleaning cannot become occupied or empty by editing the generic form. Empty cannot become cleaning through Room Update. Cleaning ends only through the explicit cleaning-completion action. Maintenance ends only through the explicit maintenance-completion action, which starts cleaning.

On checkout, the route clears the room's current check_in and check_out fields as it does today, but sets status/state to Dọn dẹp / cleaning. The RoomRental row and its saved times and prices remain historical records. No timer automatically closes the cleaning period.

## 4. RoomServiceLog data and invariant

Add a new room_service_logs table; do not put repeated service timestamps on Room.

| Field | Proposed definition and use |
| --- | --- |
| id | Integer primary key |
| room_id | Nullable FK to rooms.id, ON DELETE SET NULL; set explicitly to NULL on eligible Room deletion as a SQLite-safe measure |
| room_number | Required snapshot; retained even after Room deletion or renumbering |
| service_type | Required string limited to cleaning or maintenance |
| started_at | Required naive local DateTime |
| ended_at | Nullable naive local DateTime; NULL means active |
| note | Optional text; mainly the maintenance reason |

Duration is derived from ended_at - started_at; no duration column is needed. Add a check for allowed service types and, if convenient, ended_at IS NULL OR ended_at >= started_at. Index room and service period fields for active/history lookups.

A Room may have no more than one active service log (ended_at IS NULL). Every operation checks the database for active logs and verifies the type matches the Room state before transitioning. A cleaning Room must have exactly one active cleaning log; a maintenance Room must have exactly one active maintenance log. An empty or occupied Room must have no active service log. Missing, duplicate, or mismatched logs are integrity errors: show safe feedback and do not silently repair or transition the Room.

Use application validation on every mutation. Since the project uses SQLite and this is a new table created through db.create_all(), a SQLite partial unique index on non-null room_id where ended_at IS NULL is a practical additional guard. Keep application checks for understandable errors. If another database backend is supported, define its equivalent partial/filtered unique index; do not build a migration framework solely for this index. Normal-operation tests must prove duplicate active logs are rejected.

## 5. Route and form strategy

Keep existing routes where they match the operation and use two new completion routes:

- Existing POST /rooms/<room_number>/checkout: require an authenticated session and CSRF; validate occupied canonical state and absence of active service logs; atomically clear occupancy times, switch to cleaning, and create the active cleaning log.
- Existing GET/POST /rooms/<room_number>/edit: keep metadata editing, but make status choices depend on the current database state. The server—not submitted state, active-log ID, note timestamps, or reservation counts—determines the source state and legal transition.
- New POST /rooms/<room_number>/cleaning/complete: close the active cleaning log and switch to empty.
- New POST /rooms/<room_number>/maintenance/complete: close maintenance, create a new cleaning log, and switch to cleaning.
- Start maintenance through the existing Room Update form; do not add a redundant start endpoint.

The update form's transition control is restricted as follows:

- Empty: options are keep Phòng trống or chuyển sang Bảo trì.
- Cleaning: options are keep Dọn dẹp or chuyển sang Bảo trì.
- Maintenance: show Bảo trì as fixed/read-only; do not offer Empty or Cleaning. Completion uses its dedicated route.
- Occupied: Room Update is not offered in the card. Direct GET/POST access is rejected safely; checkout is required.

For an allowed transition to maintenance, show a small optional reason field and store its trimmed value in the new maintenance log's note (recommend a 500-character limit). The route maps the accepted display choice to both canonical fields; it never accepts a separate client-provided state. Keeping the current state may update normal room metadata without creating another log, but only when the active-log invariant for that state is satisfied. Room type changes remain independent of operational state and service history.

All operations require login, POST, and CSRF for mutations. Missing room numbers, invalid source state, no matching active service log, duplicate submission, or stale browser pages produce safe feedback and no mutation. SQLAlchemy failures roll back the Room update and every log insert/close together, then return the project's standard retry/error response.

## 6. Service transitions and atomicity

Capture one naive local timestamp (minute precision, matching existing room operations) per transition.

- Checkout: validate state and active logs; set status/state to cleaning; clear check-in/out; insert cleaning log; commit once.
- Cleaning completion: require one open cleaning log; set its end time; set status/state to empty; commit once.
- Start maintenance from cleaning: require one open cleaning log; set its end time; insert maintenance log with optional note; set status/state to maintenance; commit once.
- Start maintenance from empty: require no open log; insert maintenance log; set status/state to maintenance; clear stale occupancy times if present; commit once.
- Maintenance completion: require one open maintenance log; close it; insert cleaning log with the same transition timestamp; set status/state to cleaning; commit once.

On any database error, rollback the whole operation. Never commit a Room state change without its matching log operation. Never leave a cleaning/maintenance log open after the Room has left that state, or set the Room empty while its cleaning log remains open.

## 7. Room cards and update controls

The room-card actions are state-specific and keep text labels visible:

- **Empty:** [ Cho thuê ] [ Cập nhật ] then full-width [ Xóa phòng ]. Update may start maintenance.
- **Occupied:** keep exactly [ Trả phòng ] [ Đặt trước ] then full-width [ Điều chỉnh thuê ]. No generic update, delete, or second rent.
- **Cleaning:** [ Hoàn tất dọn dẹp ] [ Cập nhật ]. No rent, checkout, rental adjustment, or delete. Update may start maintenance.
- **Maintenance:** [ Hoàn tất bảo trì ] [ Cập nhật ]. No rent, checkout, rental adjustment, or delete. Update cannot move directly to another state.

Completion controls are POST forms with CSRF. Their server routes remain authoritative if a stale page shows an action that is no longer valid. Show an explicit status label and accessible room name for all four states. Do not dim, grayscale, blur, or desaturate cleaning/maintenance room images.

## 8. Status summary, filters, and visual semantics

Extend room-page filter values to all, empty, occupied, cleaning, and maintenance; invalid values continue to fall back to all. Extend ROOM_STATUS_ORDER, status_by_filter, and the status-summary links/counts to all four canonical pairs. Counts should be based on valid status/state pairs so a mismatch is not silently counted as a valid operational state. The total count remains all Room rows. Keep status text beside color dots.

Use existing green empty and red occupied treatments. Cleaning is yellow (the current stylesheet already has partial amber cleaning rules and a cleaning legend dot); add complete card/status-summary styling. Add blue maintenance card, status, and legend-dot styling. Verify state class hooks on both room_management.html and home.html. Keep images fully visible and maintain contrast for labels and action controls. The home page currently displays textual Room state and total rooms but no status-summary links; preserve its state labels and color treatment, while the four clickable filters/counts belong on the room management page.

## 9. Reservations and scheduled availability

Existing RoomReservation rows and their status, guest fields, room-number snapshot, and price snapshot survive checkout, cleaning, entry to maintenance, maintenance completion, and cleaning completion. Operational changes must never cancel, delete, transfer, or rewrite bookings.

Entering maintenance is allowed even when booked future reservations exist: equipment damage takes operational priority. Do not silently cancel or auto-move bookings. Before confirming the transition and on the maintenance Room card, show a clear warning with the number of still-effective booked reservations (exclude cancelled/completed; use a consistent future/current schedule rule). The warning informs staff but is not a blocker.

Reject new reservation creation for a Room in maintenance, including direct GET/POST route attempts; explain that availability cannot be promised before a maintenance completion time is known. Cleaning remains unavailable for new reservations as it is today. Preserve the existing occupied-room booking rule and reservation overlap validation. Existing bookings remain in storage even if the room becomes unavailable.

Do not auto-open the next booking after checkout. Checkout lands in cleaning. A future enhancement may show the next booking only after cleaning completion makes the Room empty. Reservation check-in is not implemented; future check-in must be rejected unless the Room is operationally ready (empty, with no active service log). Reservation-to-RoomRental conversion is later work.

## 10. Rentals, deletion, and Room-Type Transfer

New rentals remain allowed only when both Room fields are exactly Phòng trống / empty; enforce this in GET and POST handlers, not only by hiding the button. Cleaning, maintenance, occupied, and inconsistent combinations are rejected. Existing rental adjustment and checkout rules remain scoped to the occupied Room and its current RoomRental.

Delete only a canonical empty Room with no active service log. Reject deletion while occupied, cleaning, maintenance, or in any mismatched state. Retain the existing protection against any booked reservation. Closed RoomServiceLog history survives deletion: set room_id = NULL in the delete transaction and keep the room_number snapshot. Do not rely only on SQLite foreign-key enforcement. Preserve existing rental/reservation history behavior and snapshot fields.

Selective Room-Type Transfer remains allowed during cleaning or maintenance because Room type is independent metadata. It must update only Room.type; status/state, active service log, service history, rentals, and reservations remain unchanged.

## 11. Database and legacy compatibility

The current startup path calls db.create_all(); the Room schema has enough capacity and needs no added column. Add only the new RoomServiceLog table and its indexes/constraints. This is additive: preserve the existing hotel.db, rooms, room types, rentals, reservations, OTP records, and uploaded images. Do not recreate the database. Existing legacy Rooms with the two canonical pairs remain valid and require no backfill. Seed rooms continue to start empty. No time-zone-aware values are introduced; use the current naive local operational datetime convention.

There is no current SQLite foreign-key PRAGMA registration in the application source. Therefore, explicitly detach closed service history before Room deletion even with ON DELETE SET NULL. Keep the RoomServiceLog room-number snapshot non-null so history remains readable after deletion.

## 12. Current assumptions and implementation inventory

Prompt 2 must update or review every current two-state assumption found in the working tree:

- src/hotel_app/models.py: Room currently defaults to empty; add RoomServiceLog only.
- src/hotel_app/app.py: room-status order/count/filter maps; list/home contexts; rent and reservation state validation; checkout; Room Update status validation and canonical mapping; delete guard/history detachment; new completion routes; maintenance reservation warning; legacy/import assumptions.
- src/hotel_app/templates/room_management.html: status summary, state class/label, action branches, maintenance warning, completion forms.
- src/hotel_app/templates/home.html: keep textual state and state-derived class meaningful for four values.
- src/hotel_app/templates/room_form_fields.html and room_form.html: dynamic legal transition choices, fixed maintenance state, optional maintenance note and warning.
- src/hotel_app/templates/room_reservation_dialog.html: maintenance must not open or submit a new booking; preserve existing edit/cancel behavior for bookings.
- src/hotel_app/static/css/hotel.css: full yellow cleaning and blue maintenance status/card/legend treatment; no image fading.
- Tests: tests/test_room_rentals.py, tests/test_room_reservations.py, tests/test_room_types.py, and preferably a focused tests/test_room_service_states.py; inspect tests/test_login.py and tests/conftest.py helpers for home cards and status fixtures.
- Documentation: add an implementation record (next available number) and update/add a short correction to docs/17_implementation_room_reservation.md, whose current wording says early checkout is unchanged. That statement becomes stale when checkout starts cleaning. Keep docs/16_design_room_reservation.md as the historical approved reservation design; explain the later operational-state integration in the new implementation record.

Useful current state-only assumptions include: the two-value ROOM_STATUS_ORDER; room filters accepting only empty/occupied; rent requiring empty; checkout changing to empty; the update form and route accepting only empty/occupied and mapping every non-occupied status to empty; delete guarding only occupied; reservation validation allowing only empty or occupied; the room-card action template having only empty and occupied branches; and the occupied summary class logic. Cleaning colors exist only partially in CSS; maintenance colors do not. Tests assert old checkout-to-empty behavior and two-state counts/actions and will need intentional updates.

## 13. Prompt 2 test plan

Add/update tests for:

1. Empty -> rent -> occupied still works; backend rent rejects cleaning, maintenance, and occupied.
2. Checkout changes occupied to cleaning, clears check-in/out, preserves rental history, and creates exactly one active cleaning log.
3. Cleaning completion closes that log and changes to empty; no timer completes it.
4. Cleaning -> maintenance closes cleaning and creates maintenance with the same timestamp; optional note is saved.
5. Empty -> maintenance creates maintenance history.
6. Maintenance completion closes its log and creates cleaning; it never goes directly to empty.
7. Invalid/mismatched transitions, wrong completion state, missing active log, duplicate submission, and inconsistent fields fail without mutation.
8. Normal route operations never create two active logs for a Room; SQLite partial unique index rejects a direct duplicate if adopted.
9. Injected SQLAlchemy failure rolls back Room and log inserts/ends atomically for checkout, maintenance transitions, and completion.
10. Exact action order/presence/absence for all four states.
11. All five filters, invalid-filter fallback, canonical counts, visible labels, four state classes/colors, and undimmed images.
12. Existing booked reservations survive each service transition; maintenance warns with the correct count and does not cancel/move them.
13. New reservation attempts during maintenance are rejected at GET and POST; cleaning remains unavailable; existing reservation edits/cancels and occupied booking conflicts continue to work.
14. Delete rejects occupied, cleaning, maintenance, active logs, and any booked reservation; empty deletion retains prior rules and closed service history survives detached with its room number.
15. Room-Type Transfer during cleaning/maintenance changes only type and keeps service and reservation history intact.
16. Existing database startup adds the table without resetting room, rental, reservation, user, or uploaded-image data.

Run focused service, rental, reservation, room-type, and full suites in sequence; run python -m compileall src tests and git diff --check. Manual browser smoke should verify checkout -> cleaning -> completion and both maintenance paths if a browser is available.

## 14. Regression risks and scope exclusions

The largest regression risk is any handler that treats every non-occupied status as empty; this currently exists in Room Update's mapping. Checkout tests and early-checkout/reservation tests currently expect empty and must be revised. Ensure new state labels do not accidentally expose rent, delete, checkout, or rental-adjustment actions. Keep Room status and state synchronized through one canonical map. Do not change reservation overlap or add a 60-minute buffer: CLEANING_BUFFER_MINUTES = 60 is a future scheduling rule, distinct from the actual cleaning state. Do not auto-open bookings after checkout or add automatic check-in, timers, background jobs, notifications, employee assignment, maintenance costs, parts, or work orders.

**ROOM_SERVICE_STATE_DESIGN_STATUS: PASS**  
**IMPLEMENTATION_READY: YES — proceed with Prompt 2 using this design**
