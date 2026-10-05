# Auth Recovery Review & Testing

**Review scope:** Approved Forgot Password and Password Reset implementation only.  
**Inputs:** `01_requirements_auth_recovery.md`, `02_design_auth_recovery.md`, `03_implementation_plan_auth_recovery.md`, and current source/tests.  
**Review result:** PASS.  
**Real Gmail delivery:** Not tested; not required for this review gate.

## 1. Findings and review fixes

The implementation was checked against the current routes, model, templates, schema bootstrap, mail helper, environment sample, ignore rules, README, and tests.

Two narrow implementation hardening fixes were made during review:

1. Reset-request version issuance now uses an atomic SQL increment and refreshes the User before commit/token creation. This prevents concurrent requests from accidentally receiving tokens with the same version and preserves the rule that each newer request invalidates older links.
2. Reset URL construction now removes trailing base-path slashes and rejects query strings, fragments, and userinfo in `APP_BASE_URL`, while accepting only absolute HTTP(S) bases. Email/form input does not control the reset host.

Focused test coverage was added for a correctly signed token with malformed payload structure, SMTP failure after a reset version has already committed, and reset URL validation. The missing-mail-credentials test explicitly blanks its settings so it cannot use ambient credentials or make a real network call. No unrelated feature was changed during review.

## 2. Requirements and design traceability

| Approved behavior | Implementation evidence | Review result |
|---|---|---|
| Anonymous Forgot Password GET/POST | `forgot_password` route has no login guard; GET renders the form and POST handles normalized email. | PASS |
| Normalize and search registered address | Existing `normalize_email()` is used before querying the existing User model. | PASS |
| Known and unknown addresses share public result | Both valid-address paths flash the exact approved generic message and redirect to the same endpoint with 303; only a found User sends mail. | PASS |
| Anonymous reset GET/POST | `reset_password` route has no login guard and validates the token on both methods. | PASS |
| Signed token, dedicated salt, 900-second expiry | `URLSafeTimedSerializer`, dedicated reset salt, and `max_age=900`. | PASS |
| Payload binds account and reset version | Signed payload contains user ID, reset version, and purpose; validation checks structure, purpose, User existence, and current version. | PASS |
| New request invalidates older links | Atomic persistent version increment occurs before commit, token creation, and SMTP send. | PASS |
| SMTP failure keeps committed version and generic response | Mail helper handles delivery failure; route does not roll back a committed version; focused test verifies the prior token is invalid and generic response remains. | PASS |
| Successful reset is one-time and atomic | Existing `User.set_password()` creates the hash; conditional update matches the current version and updates hash plus incremented version in one transaction. Replay/version race is rejected; database errors roll back and render a safe error. | PASS |
| Password policy and completion | Reset requires 8+ characters and matching confirmation; success redirects to `/login` without creating a session. | PASS |
| Mail content and credential handling | Standard-library `EmailMessage`/`smtplib`, configured sender/recipient, STARTTLS support, 10-second timeout; no passwords or hashes in the message. | PASS |
| SQLite compatibility | `db.create_all()` handles fresh DB; current inspected-column migration adds `INTEGER NOT NULL DEFAULT 0` only when absent. Existing-record migration and repeat startup are tested. | PASS |
| Existing UI and main features | Login only gains a Forgot link; new templates reuse current auth classes/CSS. Full suite covers existing account and hotel flows. | PASS |

## 3. Security review

- Token is HMAC-signed by the configured Flask `SECRET_KEY` with salt `hotel-auth-password-reset-v1`; it expires after 900 seconds.
- Invalid signature, expiry, malformed payload, missing account, version mismatch, and replay map to the same safe reset-link message. No internal exception, ID, version, secret, or stack trace is rendered.
- No reset token or plaintext password field is stored. Token is carried only in the signed URL/email and is not logged by application code.
- Password update calls the existing scrypt `User.set_password()` method. Old password fails and new password succeeds in automated route-level checks.
- Neither current/new password nor password hash is logged or emailed. Mail failures log only a fixed diagnostic and exception class; credentials and token are omitted.
- Global Flask-WTF CSRF remains enabled. Both forms include `csrf_token()` and both POST routes reject missing CSRF in tests.
- `.env.example` has blank mail credential values; `.env` is ignored by `.gitignore`. No real Gmail credential was added.
- No global session revocation was introduced. Reset itself creates no authenticated `user_id` session; this follows the approved session limitation.
- Account-existence timing can differ because only known users trigger SMTP; response text/status/redirect are equivalent. Perfect timing equalization is outside the approved student-project requirement.

## 4. Database and mail review

`User.password_reset_version` is an Integer, non-null, Python default 0, and server default 0. Existing User construction and Register need not pass the field explicitly. No second User model, token table, or plaintext token column exists.

On fresh databases, SQLAlchemy creates the column. On a database with an existing `users` table, startup inspects columns and uses an additive `ALTER TABLE` with default zero. The compatibility test verifies existing ID, email, and password hash survive and version reads as zero, then recreates the app to verify idempotence. No database deletion/rebuild was used.

Mail configuration names are consistent across application config and `.env.example`: `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, and `APP_BASE_URL`. The helper uses SMTP STARTTLS when configured, a bounded timeout, login/send, and context-managed shutdown. It catches authentication, connection, TLS, timeout/network, configuration, and other ordinary delivery exceptions without propagating them into a 500 response. Missing credentials leave app startup and Login/Home unaffected; Forgot Password stays generic and logs a safe delivery diagnostic.

## 5. UI, accessibility, and baseline repair

Login preserves its form, Register link, current inputs/autocomplete, validation, and branding; it adds only `Quên mật khẩu?`. Forgot and reset templates use the current standalone Hotel Management auth shell and `style.css`, with labels linked to their input IDs, CSRF fields, existing alert/error classes, and appropriate autocomplete (`email` and `new-password`). No CSS change or CodeGym visual was introduced.

The separate baseline repair in `tests/test_room_types.py` is valid: current `room_management.html` renders `class="status-summary"` before `id="open-room-dialog"`, and the test still checks this ordering. The assertion was not reverted or weakened.

## 6. Automated test review

Focused recovery tests cover anonymous GETs, Login link, CSRF, normalized known address, unknown-address equivalence, token signature/payload/age/account/version checks, old-link invalidation, successful reset/replay, hash/login behavior, validation, database rollback, SMTP success/failure/missing config, and existing SQLite migration.

Expiration is deterministic: the test advances the signing clock beyond 900 seconds without sleeping. SMTP is mocked at the standard-library transport boundary; no automated test makes a network call or requires Gmail credentials.

Results after review fixes:

- `python -m pytest tests/test_auth_recovery.py -q`: **20 passed, 0 failed**.
- `python -m pytest`: **153 passed, 0 failed** (133 existing tests plus 20 recovery tests).
- `python -m compileall src tests`: PASS.
- `git diff --check`: PASS.
- No repository linter/formatter configuration was present; no lint dependency was installed.

## 7. Diff classification and remaining limitations

**EXPECTED:** Auth routes/config and schema field in `app.py`/`models.py`; helper module; Login link and two templates; recovery tests; safe `.env.example` and README setup notes.  
**BASELINE_REPAIR:** `tests/test_room_types.py`, the user-authorized stale UI assertion update.  
**REVIEW DOCUMENTATION:** This file; prior requirement, design, and implementation-plan documents remain unchanged.  
**UNEXPECTED:** None. No unrelated application deletion was found in the tracked diff. No push, merge, or PR was performed.

Limitations:

- Real Gmail SMTP delivery has not been exercised; local sender configuration is still needed for a manual smoke test.
- Complex rate limiting remains deferred by policy.
- Existing sessions are not globally revoked after reset, as approved.
- A newer reset request intentionally invalidates prior links even when SMTP fails; the user may submit another request.

## 8. Review gate

**AUTH_RECOVERY_REVIEW_STATUS: PASS** — requirements traceability, signed 900-second token, one-time/version lifecycle, hashing, enumeration-safe public response, CSRF, SMTP failure handling, additive/idempotent SQLite migration, UI compatibility, and regression tests are verified.

**READY_FOR_FINAL_DELIVERY: YES**

**NEXT_ACTION: Final Delivery Auth Recovery**
