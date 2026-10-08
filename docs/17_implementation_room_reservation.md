# Room Reservation Implementation

## Summary

Implemented the approved design in `docs/16_design_room_reservation.md`. Future schedules use a new `room_reservations` table and never modify the current occupancy fields on Room. The table is added by the existing startup `db.create_all()` path; the app does not rebuild the SQLite database.

## Model and storage

`RoomReservation` stores nullable `room_id` (`ON DELETE SET NULL`), `room_number` snapshot, `guest_name`, `guest_phone`, naive `reserved_from` / `reserved_until`, `duration_minutes`, `nightly_rate`, `total_price`, `status`, and `created_at`. Status values are `booked`, `cancelled`, and `completed`. Only `booked` blocks room schedules; status does not change automatically with time. A Room can have multiple non-overlapping reservations.

The effective price comes from the server-side room display price (saved positive Room price, otherwise the existing room-type default). Creation and edits snapshot rate, duration, and total using `_rental_amount` rounding. Editing refreshes the price snapshot; cancellations retain the row and original snapshot. Name and phone are trimmed and validated, and the existing Vietnamese phone rule is shared with profile validation.

## Routes and schedule validation

- `GET/POST /rooms/<room_number>/reserve`: opens the room reservation modal, validates and creates a booking.
- `GET/POST /rooms/<room_number>/reservations/<reservation_id>/edit`: opens the same modal in edit mode and revalidates conflicts, excluding the edited row.
- `POST /rooms/<room_number>/reservations/<reservation_id>/cancel`: changes `booked` to `cancelled` without deleting history. All mutation endpoints require login and Flask-WTF CSRF.

The shared `_intervals_overlap` helper uses half-open intervals: `start_a < end_b and end_a > start_b`. Adjacent boundaries are allowed. Booked reservations are loaded by room and filtered through this common overlap rule; cancelled and completed rows do not block. Datetimes remain naive local wall time, parsed at minute precision to match the current rental flows. Reservations must start after the current minute and end after they start.

When an occupied Room is reserved, the latest matching rental must exist and the proposed booking cannot overlap its current rental interval. The current rental is identified using the existing occupied Room state and latest rental ordered by `rented_at`, then ID. An occupied Room without a matching rental is rejected safely. Reservation create/edit does not change Room status, state, check-in/out, or any RoomRental row.

`rent_room` now rejects immediate rental intervals that overlap a booked reservation; ending exactly at the reservation start is allowed. `edit_room_rental` applies the same rule to the original rental start and proposed checkout, while keeping current duration and price recalculation. Rejected edits leave rental and Room checkout values unchanged. Early checkout remains unchanged and does not alter reservation rows.

## Room UI and management

Occupied cards now show actions in this order: first row `Trả phòng` then `Đặt trước`, second row full-width `Điều chỉnh thuê`. First-row controls use equal grid columns. Empty cards retain green styling; occupied cards use red styling and keep visible status text. The occupied image grayscale/opacity treatment was removed.

The existing Rent dialog styling is reused for the reservation modal. It shows room number and current rate, guest name/phone, reservation start/end, a client-side duration and total preview, field errors, CSRF, and the confirmation action. Submitted prices are ignored. The same modal lists booked schedules for that room and offers Edit and Cancel. Room cards show only the nearest upcoming booked reservation; no empty summary is added when none exists. The route also accepts empty rooms for future expansion, although this UI adds the trigger only to occupied cards.

Room deletion is rejected while any `booked` reservation is linked to the Room. Cancelled/completed history is retained with `room_id` set to `NULL` and its room-number snapshot intact in the same transaction as deletion. Selective Room-Type Transfer changes only `Room.type`; reservation IDs and history remain linked and unchanged.

## Transactions and scope

Reservation create/edit/cancel validate before mutation and commit once. SQLAlchemy failures roll back and return safe feedback. Reservation create/edit do not mutate Room or RoomRental. Room deletion checks booked rows, detaches historical rows, and deletes in one transaction. The database schema change is additive: the existing `db.create_all()` adds a missing table and preserves existing users, rooms, room types, rentals, OTP data, and uploaded files. No migration package or database reset was added.

No notifications, email/SMS confirmation, scheduler, automatic checkout, or automatic check-in were implemented. `NOTIFICATIONS_IMPLEMENTED = NO`. Reservation-to-rental conversion remains future work.

## Files changed

- `src/hotel_app/models.py`
- `src/hotel_app/app.py`
- `src/hotel_app/templates/room_management.html`
- `src/hotel_app/templates/room_reservation_dialog.html` (new)
- `src/hotel_app/static/css/hotel.css`
- `tests/test_room_reservations.py` (new)
- `tests/test_room_types.py` (occupied action assertions updated)

## Verification

- Baseline: `python -m pytest --basetemp=.pytest_tmp -p no:cacheprovider` — 187 passed.
- Focused reservation suite: `python -m pytest tests/test_room_reservations.py --basetemp=.pytest_tmp -p no:cacheprovider` — 35 passed.
- Focused rental suite: `python -m pytest tests/test_room_rentals.py --basetemp=.pytest_tmp -p no:cacheprovider` — 9 passed.
- Room-type/room regression suite: `python -m pytest tests/test_room_types.py --basetemp=.pytest_tmp -p no:cacheprovider` — 100 passed.
- Full suite: `python -m pytest --basetemp=.pytest_tmp -p no:cacheprovider` — 222 passed.
- `python -m compileall src tests` — passed.
- `git diff --check` — passed.
- Manual browser smoke: `NOT_RUN`; this session has no browser surface available.

**SCHEMA_CHANGED: YES — additive `room_reservations` table only**
**EXISTING_DATA_PRESERVED: YES**
**CURRENT_FEATURE_REGRESSION: NO**
**READY_FOR_GIT_COMMIT: YES**
**READY_FOR_PUSH: NO**
