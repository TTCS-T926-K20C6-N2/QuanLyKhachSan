# Independent review and handoff — Monthly income statistics (Scrum ID 13)

## Review scope and conclusion

Reviewed the approved design, implementation note, route/helper, navigation, page template, scoped CSS, RoomRental model fields, and income tests. The implementation matches ID 13. No reproducible implementation defect was found, so application source was left unchanged. Review-only test coverage was expanded in tests/test_income_statistics.py.

ID 13 shows the authenticated user the current server year with twelve ordered months, exactly two table columns, and an annual total. No selected-year interface or export feature is present.

## Acceptance criteria

| Criterion | Review result |
|---|---|
| Menu “Thống kê thu nhập” links to the report endpoint and has active/aria-current state | PASS |
| Report year comes from server-side datetime.now().year; ?year=2020 cannot override it | PASS |
| Exactly 12 month rows, January through December | PASS |
| Exactly two columns: “Tháng” and “Tổng tiền của tháng” | PASS |
| Grand total is shown in a two-cell footer | PASS |

The template extends the shared base.html, uses its existing chart icon, keeps the existing navigation and account dropdown, and applies report-only table CSS.

## Revenue and aggregation audit

- Source is only RoomRental; recognition date is rented_at; amount is the currently saved integer total_price.
- get_monthly_income(year) in src/hotel_app/app.py builds naive local year bounds and runs one SQLAlchemy query using SQLite strftime('%m', rented_at) and SUM(total_price). Start is inclusive at January 1; the next January 1 is exclusive.
- The grouped month strings are converted to integer keys. Months 1–12 are prefilled with integer zero; the annual sum is calculated from those twelve values.
- The query has no join and does not reference Room, RoomReservation, RoomServiceLog, room state, room price, nightly rate, or duration. Therefore a rental row is counted once, and detached rental history remains eligible.
- Rental revenue is attributed wholly to the start month/year. Checkout does not split or add revenue. Updating the same rental’s saved total replaces its previous contribution in reporting.
- Formatting stays scoped to format_vnd and the report template: 0 VNĐ, 500.000 VNĐ, 1.500.000 VNĐ, and 12.345.678 VNĐ. Other pages’ comma formatting is not changed.
- Report values are saved rental transaction totals, not verified cash collection.

## Test coverage matrix

The matrix reflects assertions in the final review run. “PASS” means the named automated test passed; source inspection is noted where the assertion is structural.

| # | Requirement | Test | Covered | Result |
|---:|---|---|:---:|:---:|
| 1 | Exactly 12 months | test_statistics_route_is_authenticated_and_renders_current_year_only; empty-page test | YES | PASS |
| 2 | Month ordering | test_statistics_route_is_authenticated_and_renders_current_year_only | YES | PASS |
| 3 | Empty-month zero fill | test_empty_year_contains_twelve_zero_months; empty-page test | YES | PASS |
| 4 | Empty-year zero total | Empty-year test; empty-page test | YES | PASS |
| 5 | Annual grand total | Aggregation and integrated 2026 tests | YES | PASS |
| 6 | Rental counted in its rented month | Aggregation and boundary tests | YES | PASS |
| 7 | Multiple same-month rentals sum | test_monthly_aggregation_sums_saved_rental_totals_once | YES | PASS |
| 8 | Different months remain separate | Integrated 2026 test | YES | PASS |
| 9 | No duplicate rental counting | Annual sum and adjustment assertions | YES | PASS |
| 10 | Saved total_price, not room price/state | Integrated test links a 500,000 rental to a 9,000,000 occupied room | YES | PASS |
| 11 | Same-rental adjustment reflected | Detached/adjustment test; integrated 2026 update | YES | PASS |
| 12 | Detached rental included | test_detached_rental_and_adjusted_saved_total_are_counted_once | YES | PASS |
| 13 | Previous year excluded | Boundary and integrated 2026 tests | YES | PASS |
| 14 | January 1 included | Boundary test | YES | PASS |
| 15 | December 31 included | Boundary test | YES | PASS |
| 16 | Next-year January 1 excluded | Boundary and integrated 2026 tests | YES | PASS |
| 17 | Cross-month rental stays in start month | Aggregation test’s October 31 rental checks October and November | YES | PASS |
| 18 | Cross-year rental stays in start year | Same cross-month/year assertion | YES | PASS |
| 19 | Reservations excluded | Reservation/service-log test; integrated future reservation | YES | PASS |
| 20 | Authentication required | Authenticated route test | YES | PASS |
| 21 | Authenticated GET returns 200 | Authenticated route test | YES | PASS |
| 22 | Current server year displayed | Frozen-clock route test | YES | PASS |
| 23 | Year query ignored | Frozen-clock request with ?year=2033 still renders 2034 | YES | PASS |
| 24 | Sidebar label and route link | Rendered route test; template review | YES | PASS |
| 25 | Active menu state | Rendered aria-current="page" assertion | YES | PASS |
| 26 | Exactly two table columns | Header count, each body row cell count, footer cell count | YES | PASS |
| 27 | Exactly 12 body rows | Rendered table assertions | YES | PASS |
| 28 | Grand-total footer | Footer row/amount assertions | YES | PASS |
| 29 | VND formatting | Formatter asserts 0, 500,000, 1,500,000, 12,345,678; route renders formatted value | YES | PASS |
| 30 | Shared layout intact | Rendered dashboard-shell and topbar; full regression suite | YES | PASS |

### Coverage gap addressed during review

The prior seven tests covered the core rules but did not put the exact five-record 2026 scenario in one integration test or assert all rendered row/footer cell counts. Added test_integrated_2026_report_updates_rental_once_and_ignores_reservation and strengthened the route/table assertions. Expanded formatter checks to include 1,500,000 and 12,345,678, plus an occupied room whose current room price differs from saved rental total. No unresolved meaningful coverage gap remains in the reviewed acceptance scope.

## Regression, persistence, and visual review

- Tests use the existing app fixture with a tmp_path SQLite database. The persistent instance/hotel.db is not used or recreated.
- models.py is unchanged for this Scrum; no schema migration, payment model, or financial table was added.
- Full regression covers login/OTP, rental and minimum stay, adjustment, reservations, service-state flows, room types, and UI tests. All passed. No business-operation source was changed for this review.
- CSS selectors are namespaced under .income-statistics__...; no Home or Room Management card rules were changed by this review.
- No bugs were found or fixed.
- Browser visual smoke was unavailable and remains NOT_RUN. Code review can pass, but formal visual acceptance still needs a person to open the report on desktop and a narrow/mobile viewport, confirm the amounts and labels are not clipped, scroll only if the table overflows, and check the sidebar active state.

## Handoff

### ID 14 — selected reporting year

The reusable module-level helper is get_monthly_income(year) in src/hotel_app/app.py. It accepts an integer calendar year and returns {"year": int, "monthly_totals": {1..12: int}, "annual_total": int}. A later ID 14 implementation can reuse it after separately defining its selected-year UX and validation. ID 13 always calls the helper with the current server year and must remain without year-selection controls or request parsing.

### ID 15 — PDF export

The report route builds monthly_rows for all twelve months from the helper result and the helper returns annual_total. A later exporter can consume the same month map and total. This review adds no PDF code, route, dependency, or export control.

## Verification evidence

- Pre-ID 13 baseline: 301 passed.
- Pre-review implementation report: 7 focused / 308 full passed.
- Independent review focused suite: 8 passed.
- Independent review full suite: 309 passed.
- python -m compileall src tests: passed.
- git diff --check: passed. Git emitted LF/CRLF normalization warnings for existing working-tree files; no whitespace error was reported.
- Browser smoke: NOT_RUN; no browser or app surface was available.

## Final acceptance

**Code/test review: PASS.** ID 13 satisfies the original acceptance criteria and regression checks. No implementation defect was found. Formal visual acceptance remains pending a manual browser check; IDs 14 and 15 remain for their respective owners.
