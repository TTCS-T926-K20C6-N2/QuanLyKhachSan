# Fix minimum room rental duration

## Root cause

New rentals only required checkout to be later than the server-generated start time. Rental adjustments required checkout to be later than the current time, but did not enforce a minimum total stay. The checkout field allowed a one-minute interval.

## Rule and validation

- `MIN_STAY_MINUTES` is a rental-specific 60-minute rule, separate from the 60-minute cleaning buffer.
- New rentals validate checkout against the actual server-side start time; posted start values are ignored.
- Adjustments validate the total duration from the saved `RoomRental.rented_at`, while preserving the rule that checkout must be in the future.
- The datetime-local checkout field receives the 60-minute minimum. On adjustment, its minimum is the later of the stay minimum and the next minute after the current minute.
- Invalid requests keep the dialog open, preserve the submitted checkout value, and do not mutate room or rental records. If a booked reservation and cleaning buffer leave no valid 60-minute rental window, the request is rejected clearly.

## Unchanged behavior

- Rental pricing remains `nightly_rate * duration_minutes / 1440` with the existing rounding. New rentals use the current room price; adjustments use the saved rental rate.
- Reservation conflict rules and the 60-minute cleaning buffer are unchanged and independent of the minimum stay.
- Existing short rentals remain historical records. Active legacy rentals can be extended to a valid total duration without rewriting their start time.
- No schema, reservation, cleaning, maintenance, session, or OTP expiry changes were made.

## Verification

- Baseline before changes: 286 passed.
- Rental-focused: `python -m pytest tests/test_room_rentals.py --basetemp=.pytest_tmp -p no:cacheprovider` — 33 passed.
- Full suite: `python -m pytest --basetemp=.pytest_tmp -p no:cacheprovider` — 301 passed.
- `python -m compileall src tests` and `git diff --check` passed.
