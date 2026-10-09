# Design — Monthly income statistics (Scrum ID 13)

## 1. Story and acceptance criteria

**User Story 13:** “Là người dùng tôi muốn xem thống kê thu nhập.” An authenticated user opens “Thống kê thu nhập” to view the current server year as exactly 12 ordered month rows, each with that month’s total, plus a grand-total footer. The table has exactly two columns: **Tháng** and **Tổng tiền của tháng**. Empty months and an entirely empty year display 0 VNĐ.

This design is limited to current-year monthly reporting. ID 14 (user-selected year) and ID 15 (PDF export) are separate responsibilities and are not included. There is no year selector, date filter, chart, export, payment, or invoice flow.

## 2. Current-code assessment

- RoomRental in src/hotel_app/models.py stores rented_at, expected_checkout, duration_minutes, nightly_rate, and total_price. room_id is nullable and uses ON DELETE SET NULL, so rental history survives room deletion.
- RoomRental.total_price is the saved transaction amount. New rentals snapshot the current effective room rate; rental adjustment updates the same row’s duration, expected checkout, and total using its saved nightly_rate. It does not change rented_at or create another rental. Statistics must therefore read the latest total_price directly.
- The application contains no current income-statistics route, page, or reusable reporting aggregator. Its authenticated routes use the current_user() helper and redirect unauthenticated requests to login.
- Currency output currently uses Python’s {:,.0f} pattern followed by VNĐ (comma grouping). The report should use Vietnamese thousands grouping, e.g. 500.000 VNĐ, via a small report formatter such as format_vnd(value) that renders integer VND with periods. No currency library or float conversion is needed.
- The shared base template owns the sidebar. Existing .nav-link styles and the icon-chart SVG symbol can be reused. Existing .dashboard-panel and .panel-header styles establish the Hotel Management visual language. The room-type table is the closest existing semantic table pattern; new statistics table styles should be scoped to this page.
- There is no database-backed Income, Payment, or transaction ledger model. RoomReservation and RoomServiceLog are separate records and are not income sources.

## 3. Approved revenue recognition

Use approved Option A: recognize income when an actual RoomRental record is created. The transaction is assigned wholly to the year and month of RoomRental.rented_at, and its contribution is the saved RoomRental.total_price. This is the project’s simplified reporting convention; it represents saved rental transaction values, **not verified cash payments**.

A rental crossing a month or year boundary is counted exactly once in its start month/year. Do not prorate or split it. An adjustment changes the saved amount on the existing rental, so the report automatically shows the latest total once. Room status, room price, room-type price, reservations, service logs, and operating costs do not participate.

## 4. Year range and monthly aggregation

Determine report_year = datetime.now().year on the server, following the application’s existing naive local datetime.now() convention used for rental scheduling. Build naive boundaries compatible with SQLite’s stored DateTime values:

- year_start = datetime(report_year, 1, 1, 0, 0) (inclusive)
- year_end = datetime(report_year + 1, 1, 1, 0, 0) (exclusive)

Include rows only where RoomRental.rented_at >= year_start and RoomRental.rented_at < year_end. Thus January 1 at midnight is included; the prior year’s last minute and the next year’s January 1 are excluded. Do not use checkout date, browser time, or the current year as a hardcoded constant.

### Reusable aggregation interface

Add a module-level helper in app.py, consistent with the application’s existing helper placement:

    def get_monthly_income(year: int) -> dict:
        # result contains year, monthly_totals (keys 1..12), annual_total
        ...

Initialize an integer map with months 1 through 12 set to zero. Use one SQLite-compatible SQLAlchemy query that selects strftime('%m', RoomRental.rented_at) and SUM(RoomRental.total_price), filters by the inclusive/exclusive year range, and groups by that month expression. Convert each returned month to an integer and assign its sum into the initialized map. Since there is no join, every RoomRental row contributes once and detached historical rentals remain eligible. Avoid loading Room, RoomReservation, or RoomServiceLog rows.

Calculate annual_total = sum(monthly_totals.values()) from the twelve integer values. Return the reporting year, the complete month map, and the total. SQL aggregation is preferred over Python-loading every year rental: it is one SQLite-compatible query, performs the sum in the database, and avoids unrelated ORM objects. Missing month groups stay zero from initialization.

## 5. Route and authentication

Add one read-only route: GET /income-statistics, endpoint income_statistics. Follow the existing route pattern: call current_user(); redirect to url_for('login') when no user is logged in; otherwise compute report_year = datetime.now().year, call get_monthly_income(report_year), format values, and render the new page. Do not accept or use a year query parameter. No POST or financial mutation is needed.

## 6. Sidebar integration

Add one .nav-link labeled **Thống kê thu nhập** in base.html, pointing to url_for('income_statistics'). Reuse the existing chart/report icon symbol and current spacing, colors, and hover/focus treatment. Add request.endpoint == 'income_statistics' active styling and aria-current="page" using the established pattern. Keep the shared sidebar, account dropdown, responsive behavior, and keyboard navigation unchanged.

## 7. Page and table design

Create src/hotel_app/templates/income_statistics.html extending base.html. Use the shared dashboard panel/header styles, the heading **Thống kê thu nhập**, and a server-rendered subtitle **Năm YYYY**. The only data table has semantic thead, tbody, and tfoot sections. It has exactly two columns in each section: month label and right-aligned formatted amount. Render the body in order from **Tháng 1** through **Tháng 12**, always with exactly 12 rows. Render the annual sum as a two-cell **Tổng cộng** footer row, not as another column. Use table header scope, clear focus/contrast, and a responsive overflow wrapper only if the viewport requires it. Do not add charts or controls.

Format each integer VND amount with dot thousands separators and the VNĐ suffix, including 0 VNĐ. The footer is the sum of the displayed twelve values. The empty-year case renders the same year subtitle, all twelve zero rows, and a zero footer.

## 8. Explicit exclusions and safeguards

- **Reservations:** RoomReservation in any status is excluded, including booked, cancelled, and completed rows. Do not convert reservations to rentals or alter reservation timing.
- **Operational status:** Income is independent of current room state. Checkout’s Occupied → Cleaning transition remains unchanged and does not add income.
- **Deleted rooms:** Do not join Room; nullable RoomRental.room_id must not prevent historical rows from counting.
- **Adjustments:** Read current saved RoomRental.total_price once. Never add an adjustment as a second transaction; do not alter rented_at.
- **Financial scope:** No payment verification, invoices, service charges, pricing recalculation, or schema/model changes.
- **Access:** The page is authenticated and read-only. Use semantic table headers and the established accessible active-menu link convention.

## 9. Prompt 2 implementation file plan

Expected implementation changes, and only for Scrum 13:

1. src/hotel_app/app.py — aggregation helper, current-year authenticated GET route, and a report-scoped VND formatter if kept alongside app helpers.
2. src/hotel_app/templates/base.html — one sidebar link with active state.
3. src/hotel_app/templates/income_statistics.html — new two-column, twelve-row report page.
4. src/hotel_app/static/css/hotel.css — narrowly scoped table styling and responsive wrapper, reusing existing panel language.
5. tests/test_income_statistics.py — focused aggregation, route, authorization, and rendering regression tests.

No model, migration, existing rental/reservation code, CSS for other pages, or unrelated tests should change.

## 10. Prompt 2 test plan

Use deterministic server-time mocking for the current-year route and exact date boundaries. Create actual RoomRental rows with explicit rented_at and saved total_price values. Cover:

1. The report always renders 12 body rows ordered January–December; missing months are 0 VNĐ.
2. A year with no rentals still renders 12 zero rows and a zero annual footer.
3. The route chooses the server’s current year, not a browser or query-string year.
4. One rental contributes to its rented_at month; multiple same-month rentals sum; different months remain separate.
5. The annual footer equals the sum of all monthly values; each rental is counted once.
6. The saved total_price, not Room.price, is used. Updating a rental’s saved amount changes that same month’s contribution once.
7. A rental with room_id = NULL remains included.
8. Previous-year December 31 at 23:59 is excluded; January 1 at 00:00 is included; current-year December 31 at 23:59 is included; next-year January 1 at 00:00 is excluded.
9. Month-crossing and year-crossing rentals are wholly attributed to the rented_at period.
10. Booked, cancelled, and completed reservations do not contribute. RoomServiceLog does not contribute. Changing current room state does not affect a rental’s contribution.
11. Anonymous GET redirects to login; authenticated GET returns 200. Sidebar entry and active state are present only as expected.
12. The report table has exactly two columns, 12 body rows, a two-cell grand-total footer, current-year text, and correctly formatted zero/nonzero VND amounts.
13. Shared base layout and responsive table behavior remain intact.

## 11. Regression risks

Risk is **LOW** if implementation remains read-only and uses only RoomRental.rented_at and RoomRental.total_price. The main risks are an inclusive upper-year boundary, omitting zero months, accidentally joining to Room, counting reservations, or rendering an adjustment twice. The query and tests above directly guard these cases. No schema migration is expected; the existing hotel.db remains unchanged.

## 12. Handoff to ID 14 and ID 15

ID 14 may reuse get_monthly_income(year) for another explicitly selected year in a later Scrum. ID 13 itself must always call it with the server’s current year and expose no year-selection interface. ID 15 may later reuse the same monthly result/annual total as export input, but this design adds no export route, button, PDF dependency, or output format.

## 13. Current verification context

The current working tree includes newer uncommitted changes, including the minimum rental-duration work. They were left untouched. Its latest full regression run before this design-only task reported **301 passed**. No application code or existing tests are changed by this design task.
