# Room Operational States Implementation

## Summary

Implemented the approved lifecycle from `docs/19_design_room_service_states.md`. Room's existing status/state columns remain the canonical current state. The additive `room_service_logs` table records cleaning and maintenance periods, and startup `db.create_all()` creates it without rebuilding existing data.

## State and service history

- Supported pairs: Phòng trống / `empty`, Đang thuê / `occupied`, Dọn dẹp / `cleaning`, and Bảo trì / `maintenance`.
- `RoomServiceLog` snapshots the room number, service kind, minute precision naive local start/end times, and optional note. Its nullable room foreign key uses `ON DELETE SET NULL`; deletion also explicitly detaches historical logs.
- SQLite has a partial unique index allowing at most one active log per room, plus checks for the service kind and valid period. Transition helpers enforce the matching active log invariant.
- Checkout changes occupied to cleaning atomically, clears check-in/out, and retains rental and reservation history. Completing cleaning closes its log and makes the room empty.
- Empty or cleaning rooms can enter maintenance. Cleaning to maintenance closes the cleaning period and opens maintenance in one transaction. Injected commit failure coverage confirms the previous cleaning state and log remain intact after rollback. Completing maintenance closes it and opens cleaning at the same minute.

## UI, reservations, and operations

- Room list filters and status counts cover all four states. Cleaning and maintenance cards have distinct badge/card colors and only show their valid service completion and update controls. Empty cards keep rental, update, and delete controls; occupied cards keep the current rental actions.
- Room Update allows empty → maintenance and cleaning → maintenance; maintenance remains in maintenance while metadata can be edited. Optional maintenance notes are limited to 500 characters. Occupied rooms cannot be changed through the general update form.
- New reservations are rejected for cleaning or maintenance. Existing booked reservations remain attached and can still be edited or cancelled. Maintenance cards and the transition flash show effective booked reservations whose end is after the current minute.
- Only canonical empty rooms can be deleted. Active service states and occupied rooms are rejected. Deleting an empty room detaches closed service, rental, and reservation history while preserving their snapshots. Room-Type Transfer changes only the room type and preserves operational state and service history.
- No automatic timer, cleaning duration/buffer, popup, automatic check-in, or automatic state transition was added.

## Files changed

- `src/hotel_app/models.py`
- `src/hotel_app/app.py`
- `src/hotel_app/templates/room_management.html`
- `src/hotel_app/templates/room_form_fields.html`
- `src/hotel_app/static/css/hotel.css`
- `tests/test_room_service_states.py`
- Existing rental, reservation, and room-type tests updated for the new checkout and state rules
- `docs/17_implementation_room_reservation.md` corrected to describe checkout entering cleaning

## Tests and validation

Baseline before edits: 231 passed. Focused service lifecycle tests cover checkout and cleaning completion, empty-to-maintenance, cleaning-to-maintenance, maintenance-to-cleaning, missing active log rejection, the partial unique index, reservation preservation/blocking, Room-Type Transfer, and detached service history. Existing rental, reservation, and room-type assertions were updated for checkout's new cleaning state and occupied state control.

Validation was run sequentially in this order:

1. `python -m pytest tests/test_room_service_states.py --basetemp=.pytest_tmp -p no:cacheprovider` — 18 passed.
2. `python -m pytest tests/test_room_rentals.py --basetemp=.pytest_tmp -p no:cacheprovider` — 18 passed.
3. `python -m pytest tests/test_room_reservations.py --basetemp=.pytest_tmp -p no:cacheprovider` — 35 passed.
4. `python -m pytest tests/test_room_types.py --basetemp=.pytest_tmp -p no:cacheprovider` — 100 passed.
5. `python -m pytest --basetemp=.pytest_tmp -p no:cacheprovider` — 249 passed.
6. `python -m compileall src tests` — passed.
7. `git diff --check` — passed.

Manual browser smoke test: NOT_RUN (no browser surfaces were available).
