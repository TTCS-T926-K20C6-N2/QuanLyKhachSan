# Cleaning Buffer Scheduling Implementation

## Policy

`CLEANING_BUFFER_MINUTES = 60` is the shared scheduling gap between guest stays. It is separate from actual operational state: a Room in `cleaning` is being serviced now, while the buffer reserves schedule time between guest intervals. There is no `MIN_STAY_MINUTES` in the current application, so no new minimum stay policy was added.

The shared `intervals_conflict_with_cleaning_buffer` helper leaves the existing raw half-open overlap helper intact. Two intervals are compatible when either stay ends at least 60 minutes before the other starts; equality is allowed. Reservation comparisons query every `booked` row for the Room and exclude the edited reservation ID. Cancelled and completed rows do not participate.

## Covered operations

- Reservation create and edit enforce the buffer before and after other booked reservations, including insertion between two bookings. Active rentals also require the full gap before the reservation. Raw overlaps remain conflicts.
- New rentals and rental adjustments are checked against all booked reservations. The adjustment maximum and new-rental maximum use the next effective booking start minus 60 minutes. Both forms show the effective latest checkout and the preparation hint; backend validation remains authoritative. Rental adjustment continues to use the saved `RoomRental.nightly_rate`.
- After checkout, the cleaning log's `started_at` is the actual checkout time. New checkout logs carry an internal `__checkout__` note marker so the latest actual checkout can be distinguished from a cleaning period opened after maintenance. For existing unmarked logs, readiness falls back to the latest cleaning log after the latest rental, then to the rental's scheduled checkout if no log exists.
- Once a Room is empty, readiness is the later of actual checkout plus 60 minutes and the end time of the latest completed service after that checkout. Early manual cleaning completion therefore does not shorten the scheduling buffer. The UI can show the resulting “Sẵn sàng lúc” time, and rent/reservation routes reject earlier starts. No timer changes operational state.
- Checkout is never blocked by a nearby booking. If the next booked reservation is less than 60 minutes away, checkout succeeds, the booking stays booked, and the room list shows a warning. Maintenance still blocks use until staff complete maintenance and cleaning; no separate maintenance buffer was added.
- Existing short-gap legacy bookings are not changed at startup. They remain readable; new or edited schedules that conflict with them are rejected.

## Files changed

- `src/hotel_app/app.py` — constant, buffer checks, readiness calculation, rental limits, and checkout warning
- `src/hotel_app/templates/room_rent_dialog.html` — next booking, latest checkout, buffer hint, and readiness text
- `tests/test_cleaning_buffer.py` — focused buffer, readiness, and legacy compatibility coverage
- `tests/test_room_rentals.py` and `tests/test_room_reservations.py` — intentionally changed old adjacency expectations to require a 60-minute gap

## Validation

Baseline before edits: 249 passed. Final validation ran sequentially:

1. `python -m pytest tests/test_cleaning_buffer.py --basetemp=.pytest_tmp -p no:cacheprovider` — 36 passed
2. `python -m pytest tests/test_room_rentals.py --basetemp=.pytest_tmp -p no:cacheprovider` — 18 passed
3. `python -m pytest tests/test_room_reservations.py --basetemp=.pytest_tmp -p no:cacheprovider` — 35 passed
4. `python -m pytest tests/test_room_service_states.py --basetemp=.pytest_tmp -p no:cacheprovider` — 18 passed
5. `python -m pytest tests/test_room_types.py --basetemp=.pytest_tmp -p no:cacheprovider` — 100 passed
6. `python -m pytest --basetemp=.pytest_tmp -p no:cacheprovider` — 285 passed
7. `python -m compileall src tests` — passed
8. `git diff --check` — passed

Manual browser smoke test: NOT_RUN; no browser surfaces were available. No changes were pushed.
