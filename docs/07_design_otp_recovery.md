# OTP Password Recovery Design

**Stage:** Design only  
**Requirements:** [06_requirements_otp_recovery.md](06_requirements_otp_recovery.md)  
**Status:** Ready for implementation; no application code is changed by this design.

## 1. Current baseline reviewed

The current `app.py` exposes `GET/POST /forgot-password` and `GET/POST /reset-password/<token>`. `auth_recovery.py` signs reset tokens with `itsdangerous`, gives them a 15-minute lifetime, constructs reset URLs from `APP_BASE_URL`, and sends mail through Gmail SMTP. `User` already has `password_reset_version`, `set_password()`, `check_password()`, and the existing `normalize_email()` function.

Application startup calls `db.create_all()` and applies idempotent additive SQLite changes to the existing `users` table. Flask-WTF CSRF is enabled globally. Auth templates use the Hotel Management styling, and the recovery tests currently exercise the signed-link flow and mocked SMTP. `.env.example` and README document Gmail SMTP settings. Implementation must replace those recovery-specific assumptions while preserving ordinary authentication and hotel features.

## 2. Routes and user flow

The final public recovery flow has three steps, all available while logged out:

| Route | Behavior |
|---|---|
| `GET/POST /forgot-password` | Accept and normalize an email, apply per-account send policy, and request one OTP delivery. Always show the same generic response for known, unknown, cooldown, rate-limited, and provider-failure cases. |
| `GET/POST /verify-reset-code` | Accept a six-character OTP for the challenge id held in the Flask session. Successful verification changes the challenge to verified and redirects to password reset. |
| `GET/POST /reset-password` | Require a verified, current, unconsumed challenge and its unexpired reset authorization. Validate new password and confirmation, then update and consume atomically. |

No email, OTP, challenge id, or reset credential appears in a URL. Every POST uses the existing CSRF protection. The request response wording is: **“Nếu email tồn tại trong hệ thống, mã xác nhận sẽ được gửi.”** The same response type, message, and navigation are used for every syntactically valid address, including cooldown/rate-limit and provider failures. Do not return account-specific wait durations on the request page. Once recovery is established, a resend countdown may be shown because the user has already entered that flow; it must not change the generic request result.

## 3. Challenge persistence

Add a dedicated SQLAlchemy model/table named `PasswordResetChallenge`. Do not add temporary OTP fields to `User`.

| Proposed field | Type and purpose |
|---|---|
| `id` | Integer primary key; random-unpredictability is unnecessary because the id is only used server-side in the session. |
| `user_id` | Non-null foreign key to `users.id`, indexed. |
| `reset_version` | Non-null integer snapshot of `User.password_reset_version`; unique together with `user_id` so one generation has one challenge. |
| `otp_digest` | Non-null fixed-length string containing the HMAC-SHA256 hex digest; never the raw code. |
| `created_at` | UTC timestamp for issuance/attempt accounting. |
| `expires_at` | UTC timestamp exactly five minutes after issuance. |
| `failed_attempts` | Non-null integer, default 0; fifth incorrect or malformed submission locks the challenge. |
| `delivery_status` | Short string: `pending`, `sent`, or `failed`. Only `sent` can be verified. `sent` means provider accepted the request, not inbox delivery. |
| `verified_at` | Nullable UTC timestamp. When set, the OTP is no longer usable. |
| `authorization_expires_at` | Nullable UTC timestamp set to ten minutes after successful verification. |
| `consumed_at` | Nullable UTC timestamp set atomically with successful password update. |

No provider message id is needed. Avoid storing email, request body, or raw OTP redundantly; `user_id` resolves the recipient. Store timestamps in UTC using the existing project’s datetime convention and compare consistently. A database enum is unnecessary: challenge state is derived from timestamps, delivery status, attempt count, expiry, and the User’s current version.

State interpretation:

- **CREATED/PENDING:** row committed before provider call; cannot verify.
- **SENT:** provider accepted the request and `delivery_status` is `sent`; usable only if all other validity checks pass.
- **DELIVERY_FAILED:** delivery status `failed`; counts as a send attempt but cannot verify.
- **EXPIRED:** current time is at or after `expires_at`, or after `authorization_expires_at` for a verified reset authorization.
- **LOCKED:** `failed_attempts >= 5`.
- **VERIFIED:** `verified_at` exists; OTP is permanently invalid, and bounded reset authorization is active until expiry.
- **CONSUMED:** `consumed_at` exists; no further verification or reset is allowed.
- **SUPERSEDED:** challenge `reset_version` differs from the User’s current `password_reset_version`.

A challenge is eligible for OTP verification only when it is `SENT`, current-version, unexpired, unlocked, unverified, and unconsumed. Reset authorization is eligible only when it is current-version, verified, before its authorization expiry, and unconsumed.

## 4. OTP generation and keyed digest

Generate a code with `secrets.randbelow(1_000_000)` and format as `f"{value:06d}"`. This covers `000000` through `999999`; leading zeroes remain part of the string throughout form handling and email delivery.

Use HMAC-SHA256 keyed by the existing Flask `SECRET_KEY`. A separate `OTP_HMAC_KEY` adds another secret deployment step without meaningful benefit for this project. Define a versioned, unambiguous byte encoding such as:

```text
HMAC-SHA256(
  key=SECRET_KEY,
  message="password-reset-otp:v1:{challenge_id}:{user_id}:{reset_version}:{otp}"
)
```

Store the hex digest only. For verification, recompute with the stored challenge context and submitted six-digit string, then compare with `hmac.compare_digest`. Reject malformed values and count them as incorrect attempts. Never log the code or digest. Rotating `SECRET_KEY` invalidates outstanding OTPs and reset authorizations, which is an acceptable recovery-safe consequence.

## 5. Request, cooldown, and rate-limit transaction

For a valid form POST:

1. Apply CSRF validation and existing `normalize_email()` before lookup.
2. Unknown email: make no challenge, provider call, or fake User; return the generic public response.
3. Known email: use a short database transaction to evaluate all `PasswordResetChallenge.created_at` rows for that user in the preceding 15 minutes, regardless of delivery status. Enforce no send attempt in the previous 60 seconds and fewer than five attempts in that rolling window.
4. If allowed, increment `User.password_reset_version`, create a challenge for that generation with status `pending`, digest and timestamps, and commit before making the network request. That version increment immediately supersedes every older challenge, even if delivery later fails. The created row is the durable send-attempt record.
5. Call the provider outside the database transaction. On accepted response, update status to `sent`; on any failure, update it to `failed`. Both outcomes count against cooldown and the rolling limit.
6. Return the same generic request result. No provider diagnostic or existence-specific cooldown response is shown.

The per-user transaction must serialize competing issuance decisions as far as SQLite permits; perform the count, version increment, and challenge insert together under the database write transaction. On an SQLite lock/transaction error, fail closed for that request and keep the public response generic. Do not send when the attempt row could not be committed. Provider calls stay outside the transaction to avoid holding a write lock over network I/O. A process interruption after commit leaves a pending, unusable challenge that still counts toward limits; the next allowed code supersedes it.

The chosen policy deliberately counts provider attempts that fail, including timeout, DNS/network, invalid API key, quota rejection, malformed response, and provider 4xx/5xx. This prevents retry storms and quota abuse. A retry is allowed only after the cooldown and while below the rolling limit.

## 6. Brevo provider boundary and email

Brevo Transactional Email API is the sole primary provider for OTP recovery. The recipient is the registered `User.email`; the sender is a configured Brevo-authorized/verified sender. Recipients may use any valid email domain and do not need to be added manually by the requesting user. Email delivery is not anonymous and inbox placement is not guaranteed.

Keep the boundary minimal: add a small `send_password_reset_otp(recipient, otp, config)` provider function in the existing `auth_recovery.py`, replacing its SMTP/token responsibilities. This avoids a new layer hierarchy and keeps route logic independent of Brevo HTTP details. The function returns a simple accepted/failed result and catches provider/network/configuration/response errors. The rest of authentication code must not construct Brevo HTTP requests.

Use Python standard-library `urllib.request` for the single JSON HTTPS endpoint unless implementation finds a concrete maintainability or testability obstacle. This avoids a new runtime dependency or large SDK. Set bounded connection/read timeout, send the API key only in the provider-required backend request header, parse success status and response safely, and treat non-success or malformed responses as failure. Tests mock this boundary; they never call Brevo. Log only safe metadata such as operation name and exception class/status category. Never log API key, OTP, body, or recipient/account existence. Do not return provider errors to the browser.

Proposed future environment configuration (blank values only in tracked examples):

```dotenv
EMAIL_PROVIDER=brevo
BREVO_API_KEY=
MAIL_FROM=
MAIL_FROM_NAME=Hotel Management
```

`BREVO_API_KEY` stays in local `.env`/deployment secrets and never enters source, templates, browser JavaScript, URL, logs, tests, or committed `.env.example`. `MAIL_FROM` must be verified/authorized in Brevo. The recovery requester never supplies sender details. Do not retain Gmail SMTP as a production fallback. `APP_BASE_URL` is no longer needed by recovery once reset URLs are removed; remove it from recovery configuration unless another inspected feature is found to use it.

Use subject **“Mã xác nhận đặt lại mật khẩu - Hotel Management”**. Plain-text content identifies the requested password reset, includes the six-digit OTP, says it is valid for five minutes, and advises ignoring the message if unrequested. Include no reset URL, password, hash, or secret. Send one recipient per request; use stable verified sender identity and transactional-only content. Do not send marketing or repeatedly send to unknown addresses, and do not try to bypass recipient spam controls.

## 7. Verification and reset authorization

Keep only `password_reset_challenge_id` in the Flask session; never keep the OTP in session. Starting a new recovery request clears any old recovery session keys. The challenge id is not a credential exposed in a URL and is checked against persisted state on every route.

`POST /verify-reset-code` loads the session challenge and associated User, confirms current reset generation, `sent` status, five-minute expiry, fewer than five failures, and not verified/consumed. Compare the submitted code’s keyed digest in constant time. For each malformed or wrong code, atomically increment `failed_attempts`; the fifth failure makes the challenge locked. On success set `verified_at` and `authorization_expires_at = now + 10 minutes` in one commit, then redirect to `/reset-password`. From that instant, no further OTP verification can succeed. The verified challenge remains unconsumed so the user can correct password form validation errors.

`GET/POST /reset-password` require the session challenge, existing User, current reset generation, `verified_at`, unexpired authorization, and no `consumed_at`. POST also requires CSRF, current password policy, and matching new-password confirmation. In one transaction call `User.set_password(new_password)`, increment `User.password_reset_version` to invalidate every outstanding recovery generation, set `consumed_at`, and commit. Clear only recovery-related session keys; redirect to `/login` with success feedback and do not create an authenticated session. The old OTP, challenge, and authorization then fail all subsequent requests; ordinary existing sessions are not globally revoked.

If a password form is invalid, preserve the verified authorization while it remains within ten minutes. If verification, reset authorization, or persistence is invalid/expired, clear recovery keys and direct the user to request a fresh code. Do not unnecessarily clear a normal authenticated session. Logout clears recovery keys if present.

## 8. Database failure and atomicity

The password hash update, reset-version increment, and challenge consumption are one SQLAlchemy transaction. Commit succeeds for all three or rolls back all three. On commit failure, call rollback, do not report success, and show a safe service error; do not disclose exception details. The challenge remains available for a retry only if the database confirms it was not consumed; implementation should reload state after rollback and fail closed if completion status is uncertain. No email failure path changes a password.

## 9. Migration and stale challenge cleanup

Add the new model and rely on the app’s existing `db.create_all()` startup path to create the missing challenge table on both fresh and existing databases. This is additive and idempotent; no `users`, rooms, rentals, or room-types table is dropped, recreated, or reset. Existing User ids, password hashes, `password_reset_version`, and all hotel records stay intact. Do not reset `instance/hotel.db` or run a destructive migration.

Use lazy cleanup with deterministic retention: during an allowed new OTP request, delete that user’s expired, consumed, failed, and superseded challenge rows after calculating the rolling-window count. Retain recent failed send rows until they leave the 15-minute rate window so deleting them cannot bypass limits. For bounded total growth, opportunistically delete terminal/expired rows older than 24 hours in the request maintenance path, after quota evaluation. Active and recently counted rows remain. No worker or scheduler is required. Also ignore any stale session challenge by revalidating DB state on every route.

## 10. Legacy artifacts disposition

| Existing artifact | Disposition during Implementation |
|---|---|
| `generate_password_reset_token()` and `validate_password_reset_token()` | **REMOVE** after OTP routes/tests are proven; they have no role in OTP recovery. |
| `_reset_url()` and signed token URL behavior | **REMOVE**; no recovery URL is sent. |
| `GET/POST /reset-password/<token>` | **REPLACE** with `GET/POST /reset-password`. Do not leave two public reset mechanisms. |
| Existing forgot/reset templates | **REPLACE/ADAPT** to request, OTP verify, and reset states using current Hotel Management styling and CSRF. |
| Signed-link-focused tests | **REPLACE** with the OTP and regression test plan below. |
| Gmail SMTP code and `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD` | **REMOVE** from the recovery path; no Gmail fallback. |
| `MAIL_FROM` | **KEEP** as the configured verified Brevo sender address. |
| `APP_BASE_URL` | **REMOVE** from recovery config because no reset URL exists, unless another feature uses it. |
| `User.password_reset_version` | **KEEP** and reuse as the account recovery generation and post-reset invalidation counter. |

Do not perform any of these removals in this Design stage.

## 11. Test design

Revise `tests/test_auth_recovery.py` to mock `send_password_reset_otp` or the provider HTTP boundary. Automated tests must never send real email. Cover:

- Forgot page render, CSRF on request/verify/reset, known and unknown email behavior and response equivalence.
- Six decimal digit generation, leading-zero preservation, secure generator use, keyed HMAC context and constant-time comparison, and absence of plaintext OTP in the database.
- Provider accepted response, timeout/network/auth/quota/4xx/5xx/malformed response, generic public behavior, no crash/password change, and no API key or OTP in logs/responses.
- 60-second cooldown and rolling five-attempt/15-minute limit, including failures consuming quota and restarting the flow not resetting quota.
- Wrong and malformed OTP attempts one through five, lockout at five, exact five-minute expiry, successful verification, and superseding request invalidating old OTP.
- OTP replay blocked after verification; ten-minute reset authorization expiry; validation mismatch and current password rules; successful reset, challenge consumption, no auto-login, old password rejected and new password accepted through Login.
- Database rollback for password/version/consumption updates and safe retry/error behavior.
- Additive/idempotent startup migration on existing and fresh databases, preserving User ids/password hashes/password_reset_version, rooms, room types, rentals, and status data.
- Login, Register, Logout, Change Password, Profile and existing room/room-type/rent/status regression coverage.

No test may inspect or depend on real provider credentials. Provider HTTP should be mockable at the small adapter boundary. Keep tests consistent with existing Flask app factory, SQLAlchemy, SQLite, Jinja, Flask-WTF and PEP 8 conventions.

## 12. Decisions and implementation gate

All twelve required design decisions are finalized: Brevo API; keyed HMAC with `SECRET_KEY`; dedicated challenge table; `password_reset_version` invalidation; five incorrect attempts; 60-second cooldown; five send attempts per rolling 15 minutes; failed provider attempts count; OTP invalid immediately at verification; server-side session authorization; ten-minute post-verification window; and removal/replacement of signed-link recovery with no Gmail SMTP fallback.

**OPEN_QUESTIONS: NONE**  
**CURRENT_FEATURE_REGRESSION: NO** — no application code or current feature was changed in this Design stage.  
**OTP_RECOVERY_DESIGN_STATUS: PASS**  
**IMPLEMENTATION_READY: YES**  
**NEXT_ACTION: Implementation + Tests**
