# OTP Password Recovery Implementation

**Status:** Implemented and verified locally  
**Requirements:** [06_requirements_otp_recovery.md](06_requirements_otp_recovery.md)  
**Design:** [07_design_otp_recovery.md](07_design_otp_recovery.md)

## Implementation summary

Replaced public signed reset links with an email OTP workflow. Login and registration behavior and the Hotel Management auth styling remain in place. Recovery routes are:

- `GET/POST /forgot-password` — normalizes an email, records an allowed send attempt, and redirects with the same generic response for valid known/unknown requests.
- `GET/POST /verify-reset-code` — verifies the code associated with the challenge id in the Flask session.
- `POST /resend-reset-code` — resends for the session’s known recovery account subject to the same cooldown and rolling limit.
- `GET/POST /reset-password` — requires a verified and unconsumed challenge and redirects to `/login` after success without logging the user in.
- `GET/POST /reset-password/<token>` — removed; it returns 404.

The `PasswordResetChallenge` table stores the User id, reset generation, keyed digest, UTC timestamps, attempt count, delivery state, verification/authorization state, and consumption timestamp. The raw OTP is not stored. `User.password_reset_version` remains and invalidates older challenges. OTPs are generated with `secrets.randbelow`, keyed with HMAC-SHA256 using the Flask `SECRET_KEY`, and compared with `hmac.compare_digest`.

The Brevo adapter uses Python standard-library HTTPS to call `POST https://api.brevo.com/v3/smtp/email`, with a finite timeout and backend-only API key header. Provider failures are logged without API key, OTP, request body, recipient, or provider body. A challenge is saved as pending before provider I/O and marked sent/failed afterward. Failed sends count toward cooldown and the five-attempt rolling 15-minute limit but cannot verify.

The existing startup `db.create_all()` path creates the new table additively. Existing SQLite users, password hashes, ids, reset version, rooms, room types, rentals and status data are preserved. Challenge retention cleanup runs lazily during a new allowed request and retains recent rows needed for rate accounting.

## Configuration and legacy cleanup

`.env.example` now contains only blank Brevo credentials/configuration. README explains backend-only Brevo setup, sender verification, local `.env` handling, and that ordinary users do not configure email credentials. Repository search found the old Gmail SMTP and `APP_BASE_URL` settings only in the prior recovery implementation/configuration and historical documentation/tests; active recovery config and code no longer use them. No local `.env` was read or changed.

Removed signed-token generation/validation, reset URL building, SMTP sending, the token route, old reset-link wording, and signed-link tests. `MAIL_FROM` remains as the verified sender address. No third-party mail SDK or HTTP dependency was added.

## Verification

- Baseline before implementation: **155 passed**.
- Focused OTP tests: **26 passed**.
- Full suite: **161 passed**.
- `python -m compileall src tests`: passed.
- `git diff --check`: passed (Git reported only its normal LF-to-CRLF working-copy notices).
- Brevo API call: not executed; provider HTTP is mocked in automated tests.
- Real API key: not added. Real email: not sent.

## Deviations from Design

- Persisted SQLite timestamps use a single naive-UTC convention because SQLite `DateTime` does not preserve timezone offsets in this project; all values are created and compared as UTC.
- The resend action is available from the verification page. When there is no session challenge, it safely redirects to Forgot Password for email entry.

**CURRENT_FEATURE_REGRESSION: NO**  
**OTP_RECOVERY_IMPLEMENTATION_STATUS: PASS**  
**READY_FOR_REAL_BREVO_TEST: YES**  
**NEXT_ACTION: Review + Final Delivery + Real Brevo Smoke Test**
