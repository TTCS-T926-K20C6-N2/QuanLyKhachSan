# Implementation — Monthly income statistics (Scrum ID 13)

Implemented the current-year, read-only income report using saved RoomRental transaction totals. The report attributes each rental to the month of rented_at, aggregates total_price in a SQLite-compatible grouped query, includes twelve months even when empty, and calculates the annual total from those month sums. The year range is inclusive at January 1 and exclusive at the next January 1. Detached rentals remain eligible; reservations and room service logs are not queried.

The authenticated GET /income-statistics route always uses the server's current year and ignores year query parameters. The page adds one sidebar link and renders a semantic two-column table with twelve month rows, a grand-total footer, and integer VND formatting with Vietnamese dot separators. Styling is scoped to the report table. No model or schema changes were made; the feature does not represent verified cash payments.

ID 14 year selection and ID 15 PDF export remain outside this implementation.

## Verification

- Baseline before implementation: 301 passed.
- Focused income-statistics tests: 7 passed.
- Full suite: 308 passed.
- `python -m compileall src tests`: passed.
- `git diff --check`: passed (Git reported existing-style LF/CRLF normalization warnings).
- Manual browser smoke test: not run; no browser or app surface was available.
