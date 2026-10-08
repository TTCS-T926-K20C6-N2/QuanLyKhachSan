# Rental Adjustment UX and Pricing Consistency

## Issue and fix

The rental adjustment modal used the room's current display price for its estimate, while the update route recalculated the saved total from the rental's original RoomRental.nightly_rate. If the room price changed after a rental began, the preview and saved total could use different rate bases. Edit mode now explicitly uses the rental snapshot for the displayed nightly rate and both the dialog and form JavaScript data attributes. New rental mode continues to use the current effective room price. The existing duration formula and backend _rental_amount rounding remain unchanged.

## Reservation schedule and checkout limits

Edit mode queries only the nearest reservation for the same room whose status is booked and whose start is at or after the current minute. Cancelled reservations are ignored. When present, the modal shows its start and end and sets the checkout input's max to the reservation start. Half-open interval validation remains authoritative on the server: checkout exactly at the reservation start is allowed, and checkout after it is rejected. The existing overlap error, open modal, and submitted checkout value are preserved on rejection.

The backend continues to require checkout strictly after max(current minute, rental start). Since datetime-local has minute precision, edit mode sets the input minimum to that boundary plus one minute. This communicates the strict rule without weakening server validation.

## Scope and files

- src/hotel_app/app.py: supplies the saved rental rate, nearest booked reservation, maximum checkout, and minute-aligned minimum to edit mode. Existing occupancy, datetime, minimum, overlap, and atomic update checks remain in place.
- src/hotel_app/templates/room_rent_dialog.html: displays the correct rate source, explains the saved-price basis in edit mode, shows the next booking, and sets edit-mode input limits.
- tests/test_room_rentals.py: covers saved versus current rate, new-rental pricing, nearest/cancelled reservation handling, no reservation, strict minimum, allowed boundary, rejected overlap, and no mutation on rejection.

No model, schema, reservation lifecycle, room state, or checkout behavior changed.

## Validation

- Baseline: 222 passed.
- Rental focused: 16 passed.
- Reservation focused: 35 passed.
- Full suite: 229 passed.
- python -m compileall src tests: passed.
- git diff --check: passed.
- Manual browser smoke: NOT_RUN; no browser surface was available.
