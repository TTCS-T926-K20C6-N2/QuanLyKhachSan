# Occupied Room UI Implementation

## Changes

- Updated `src/hotel_app/templates/room_management.html` so available rooms show **Cho thuê**, **Cập nhật**, and full-width **Xóa phòng** actions.
- Occupied rooms with an active rental show only **Điều chỉnh thuê** and the existing POST checkout form with its CSRF token and confirmation prompt. Rooms remain visible with the occupied status.
- Updated `src/hotel_app/static/css/hotel.css` to desaturate and soften the occupied room image while keeping status and controls legible, and to wrap action text on narrow cards.
- Added coverage for state-specific action visibility and the rent → checkout → available UI lifecycle, including rejection of checkout without CSRF.
- Checkout routes, database schema, and rental business logic were not changed.

## Verification

- Baseline before implementation: 171 passed.
- Focused room UI tests: 101 passed.
- Full suite: 173 passed.
- `python -m compileall src tests`: passed.
- `git diff --check`: passed.
- Manual browser smoke check: not performed in this environment.
