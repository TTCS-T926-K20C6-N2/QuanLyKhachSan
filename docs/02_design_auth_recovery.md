# Auth Recovery Design

**Status:** Design for approved Auth Recovery requirements  
**Requirements source:** [`docs/01_requirements_auth_recovery.md`](01_requirements_auth_recovery.md)  
**Scope:** Forgot Password and email-based Reset Password only  
**Implementation:** Not performed in this phase

## 1. Design overview

Add two logged-out flows to the existing Flask authentication slice:

1. The Login page links to `/forgot-password`.
2. The forgot form normalizes the email, issues a short-lived signed token only when a matching User exists, requests Gmail SMTP delivery, and displays the same generic message for all submitted addresses.
3. The reset page validates the signed token before displaying the form. A successful POST updates the existing `User.password_hash` through `User.set_password()`, advances a persistent token version, commits atomically, and redirects to `/login` without logging the user in.

The design reuses the current User, SQLAlchemy database, CSRF protection, Flask secret key and Hotel Management auth visual baseline. It does not alter Register, Login authentication behavior, Change Password, Logout, or session architecture. Email verification remains optional/deferred and is not designed here.

## 2. Route design

All routes are available while logged out. If a user already has an unrelated session in the same browser, the routes do not clear or redesign that session. Both POST endpoints use the existing global Flask-WTF CSRF protection; invalid/missing CSRF follows the application's existing 400 CSRF response behavior.

| Route | Authentication | Input and validation | Success | Failure and status |
|---|---|---|---|---|
| `GET /forgot-password` | Not required | None | Render `forgot_password.html`, HTTP 200 | Normal Flask error handling |
| `POST /forgot-password` | Not required | CSRF token; email required and normalized via `normalize_email()`; lookup existing User | For an existing User, issue a versioned reset token and attempt email delivery. For every submitted address, flash/render the exact same generic notice: “Nếu email tồn tại trong hệ thống, hướng dẫn đặt lại mật khẩu sẽ được gửi.” Redirect to `/forgot-password` with 303 after POST (or equivalent Post/Redirect/Get response), HTTP 303. | Invalid/blank email can be rendered with the same field-level validation style without disclosing account existence; HTTP 200. Invalid CSRF: existing 400 behavior. Database/operational errors: rollback, safe generic service error (503 where request cannot be processed), no account-specific message. SMTP failure keeps the exact generic notice. |
| `GET /reset-password/<token>` | Not required | Validate signature, purpose salt, maximum age 900 seconds, payload shape, account existence and token version | Render `reset_password.html` without echoing token details; HTTP 200 | Invalid, expired, malformed, mismatched-version, or unknown-account token renders a generic invalid/expired link page or alert with Login/recovery navigation; no account disclosure, HTTP 400 (404 is also acceptable if consistently generic; choose 400 for invalid bearer input). No credential mutation. |
| `POST /reset-password/<token>` | Not required | CSRF; validate token again at submit time; new password and confirmation required; exact match; minimum 8 characters; recheck current version in the transaction | Atomically set password, increment token version, commit; flash success and redirect `/login` with 303. No session is created and no current session is automatically cleared. | Invalid/expired/replayed token is rejected with generic link message, HTTP 400; validation errors render form with field errors, HTTP 200; DB failure rolls back both password/version and returns safe service error, HTTP 503. No detailed signer/account failure is shown. |

For a syntactically valid email address that is not registered, the endpoint performs no mail operation and returns the same generic UI message and redirect as it does for a registered address. The documented generic message is displayed after the request; internal logs are reserved for failures, never for identifying whether an account was found.

## 3. Login page integration

Add one small `Quên mật khẩu?` link in the existing login card, pointing to `/forgot-password`. Keep the current email/password form, CSRF field, validation, Register link, branding, and styling unchanged. Keep `autocomplete="username"` and `autocomplete="current-password"` on existing inputs.

## 4. Page design

### 4.1 `templates/forgot_password.html`

- Title: `Quên mật khẩu | Quản lý Khách sạn`.
- Reuse the standalone auth page shell, `auth-card`, eyebrow brand, field, button, alert, and auth-switch patterns from `login.html`/`register.html`, loading `static/css/style.css`.
- Helper text: explain that the user can enter their registered email to request a reset link.
- One required `type="email"` field named `email`, prefill only the entered email (never a token/password), with accessible field-level validation.
- Submit label: `Gửi liên kết đặt lại mật khẩu`.
- Secondary navigation: `Quay lại đăng nhập` linking to `/login`.
- After POST, show the exact generic success message from the approved policy for both registered and unknown addresses. Use the existing success alert style and role semantics.

### 4.2 `templates/reset_password.html`

- Title: `Đặt lại mật khẩu | Quản lý Khách sạn`.
- Reuse the same auth shell and styling; do not use `base.html`, which is the authenticated dashboard shell.
- Helper text: instruct the user to choose a new password; explain that a valid link expires after 15 minutes.
- Fields: `new_password` and `confirm_password`, both `type="password"`, both `autocomplete="new-password"`, required, minimum length 8.
- Accessible inline errors for missing fields, mismatch, and policy violation. Never refill password inputs after validation failure.
- Submit label: `Đặt lại mật khẩu`.
- Include `Quay lại đăng nhập`; it may also include a request-new-link action back to `/forgot-password` for an expired/invalid token.
- On success, redirect to Login and show a one-time success flash there. No automatic authentication.

## 5. Signed token design and one-time use

### 5.1 Mechanism

Use `itsdangerous.URLSafeTimedSerializer`, already available as a Flask dependency through the installed Flask stack. Instantiate it with the app's configured `SECRET_KEY` and a dedicated constant salt such as `hotel-auth-password-reset-v1`. Use a separate salt from any other signed tokens. The timestamped serializer signs the payload; itsdangerous timed loading validates signature and age.

Payload fields:

```text
uid: integer User.id
prv: integer User.password_reset_version
purpose: "password-reset"
```

The payload contains no password, password hash, or email. The numeric account ID is an identifier, not an authentication secret. The random signing secret protects payload integrity. Token transport uses the URL-safe encoded value; plaintext token is never persisted.

Set the validation maximum age to **900 seconds (15 minutes)**. The application SECRET_KEY is already resolved through `_secret_key()`; production requires it to be configured outside Development. For key rotation, old reset links naturally fail signature validation.

### 5.2 Version counter and issuance

Add `User.password_reset_version` as a non-null integer defaulting to `0`.

When a registered account submits a new reset request:

1. In a short database transaction, increment that User's `password_reset_version` and commit.
2. Generate a timed signed token carrying the new version.
3. Build the link and attempt mail delivery.

This intentionally invalidates all older links as soon as a newer request is issued, even if delivery of the newer email later fails. The UI stays generic. The version counter stores no token and gives a cheap persistent revocation check.

### 5.3 Validation and consume

On GET and again on POST, load the timed token with `max_age=900`, validate the required payload fields and purpose, load the User by ID, and compare payload version with the current User version. Any parsing/signature/age/account/version error is treated as one generic invalid-or-expired-link outcome. Never render the detailed exception or full token.

For POST, validation and password change must be one transaction. After successful validation and form checks, perform a conditional database update (or equivalent row lock) requiring both `id` and the token's current `password_reset_version`. Set `password_hash` using `User.set_password(new_password)`, increment `password_reset_version`, and commit. If the conditional update affects no row, another request already consumed or superseded the token; rollback/reject. If commit fails, rollback so neither password nor counter is partially applied.

The success increment makes the used token's embedded version stale. It also invalidates any other issued link. Concurrent POST attempts using the same version cannot both succeed: only one conditional update can match that version. SQLite serializes writes; implementation should still use the conditional version predicate to make the one-time invariant explicit.

### 5.4 Token and logging behavior

- Bad signature/tampering: reject generically, no database mutation.
- Expired token (>900 seconds): reject generically, no database mutation.
- User deleted or unknown `uid`: reject generically.
- Version mismatch: reject generically; token was superseded or consumed.
- Token replay after success: version mismatch; reject.
- Do not log the full token, token URL, password, SMTP password, or email body containing the token.
- Generic operational event logs may say `Password reset email delivery failed.` Do not log account-existence-dependent outcomes.

## 6. Database and migration design

Reuse the `users` table and add only:

```text
password_reset_version INTEGER NOT NULL DEFAULT 0
```

No `reset_token`, plaintext token, reset-password field, or second user table is added.

The project calls `db.create_all()` during app initialization, then inspects existing `users` columns and adds missing profile columns using `ALTER TABLE` in a transaction. Extend this same additive compatibility map for `password_reset_version` with `INTEGER NOT NULL DEFAULT 0` after `db.create_all()` and before querying/using User objects.

- **Fresh development/test database:** `db.create_all()` creates the column from the model. The compatibility check sees it and does nothing.
- **Existing SQLite database with users:** `ALTER TABLE users ADD COLUMN password_reset_version INTEGER NOT NULL DEFAULT 0` adds the column; existing rows read as version zero, so current users/passwords/sessions remain intact. SQLite applies the constant default to existing rows.
- **Repeated startup:** inspect the column first; run the DDL only when missing, making the operation idempotent.
- **Failure:** let initialization fail visibly rather than starting with a model/schema mismatch; do not remove or rebuild existing user data.
- No Alembic dependency is currently present; no schema migration framework is introduced for this one additive column.

The `User` model's Python/SQLAlchemy default should also be zero so newly created users have a consistent initial counter.

## 7. Mail delivery design

Use Python standard library `email.message.EmailMessage` and `smtplib`; current `requirements.txt` has Flask and related dependencies but no mail package, so no dependency is justified.

Configuration read from environment (with Flask app config for tests):

```text
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_FROM=
APP_BASE_URL=http://127.0.0.1:5000
```

`MAIL_USERNAME` is the sender account; `MAIL_PASSWORD` is a Google App Password or other supported secure SMTP credential. `MAIL_FROM` is the displayed sender address and must be configured, with no sender address hard-coded in source. Use SMTP STARTTLS on port 587 when TLS is enabled, then authenticate and send. Use a bounded connection timeout. `.env` is already ignored by `.gitignore`; `.env.example` should list names with blank/sample values only. Do not create `.env` or place credentials in Git.

`APP_BASE_URL` should be configurable. Prefer it for reset link construction so an untrusted request Host header cannot change the emailed origin. Development default can be `http://127.0.0.1:5000`; production must configure its trusted HTTPS base URL. Do not hard-code a production hostname.

### Email content

- Subject: `Đặt lại mật khẩu - Hotel Management`
- Plain-text body: a reset was requested for the account; show the absolute secure reset URL; state that it expires after 15 minutes; tell the recipient to ignore the message if they did not request it.
- Do not include old/new passwords, password hash, or profile details.

Recipient may use Gmail, school email, Outlook, or another valid provider. There is no `@gmail.com` restriction.

### SMTP failure and enumeration

Catch expected connection/authentication/timeout/send exceptions at the mail boundary; do not crash the Flask request. Log a safe fixed message (`Password reset email delivery failed.`) and exception category without token, credentials, message body, or account-dependent response. For both known and unknown addresses, preserve the exact generic success wording, status/redirect pattern, and UI. Only a known account attempts delivery. A successful HTTP response means the request was handled, not that SMTP delivery is guaranteed.

No Redis, database rate-limit schema, Celery, or background worker is added. More complete rate limiting is a future enhancement and does not block design or first implementation.

## 8. Session behavior

Do not add global session revocation, session versioning for login sessions, or new session storage. A reset does not authenticate the browser performing the reset. If the browser already has a session for an unrelated/current account, preserve current behavior; do not clear it as a side effect of a reset for a different account. Other users' sessions need not be revoked. The existing Change Password flow is unchanged.

## 9. Module boundaries and project structure

Keep the implementation merge-friendly. Add focused token/mail helpers, preferably in a small `src/hotel_app/auth_recovery.py` (token creation/validation and reset transaction) and `src/hotel_app/mail.py` (SMTP configuration and send). This separation is justified because SMTP failures and signer errors need isolated testing; do not add repository/service/DTO layers. Keep route registration and integration in existing `app.py` only when implementation begins. Follow PEP 8.

No source files are changed by this design artifact.

## 10. Test design

Add focused tests, using Flask's test client and monkeypatched mail transport so normal tests never send actual email. Test signed token age with a controllable clock or serializer timestamp; never wait 15 minutes in real time.

| Test ID | Scenario and expected result |
|---|---|
| FR-01 | `GET /forgot-password` returns 200 and renders email field and current auth styling. |
| FR-02 | Registered email POST shows the exact generic message and requests one email to normalized recipient. |
| FR-03 | Unknown email POST shows exactly the same user-facing message, status, and redirect behavior; no email is sent. |
| FR-04 | Whitespace/case variants resolve to the same normalized User. |
| FR-05 | Valid unexpired signed token opens reset form. |
| FR-06 | Altered signature/payload is rejected without mutation. |
| FR-07 | Token older than 900 seconds is rejected without mutation. |
| FR-08 | Issuing a second reset request invalidates the first token. |
| FR-09 | Successful reset makes the used token unusable and invalidates other outstanding links. |
| FR-10 | Mismatched confirmation is rejected; hash/version remain unchanged. |
| FR-11 | Successful password is stored as a scrypt hash, not plaintext. |
| FR-12 | Prior password fails Login after reset. |
| FR-13 | New password succeeds through existing Login. |
| FR-14 | Reset success redirects to `/login` and creates no `user_id` session for a logged-out client. |
| FR-15 | Missing/invalid CSRF rejects both POST routes using existing behavior. |
| FR-16 | SMTP unavailable, invalid App Password, timeout, or connection error does not crash the request and does not change generic response for a known email. |
| FR-17 | Database stores no plaintext password or reset token; inspect schema to confirm no token column. |
| FR-18 | Conditional version consume permits at most one successful reset for a token, including competing submissions. |
| DB-01 | Fresh schema creates version at zero; existing SQLite schema is upgraded once, preserving existing users and password hashes. |
| COMPAT-01 | Existing full suite passes with `python -m pytest`; Login, Register, Logout, Change Password, profile, room and room-type/rental features remain working. |

Implementation acceptance requires the full command `python -m pytest` after implementation. This document has not run tests because no implementation was requested in this turn.

## 11. Local development and F5

Keep the existing VS Code F5 behavior: Flask starts and the browser opens `/login`. The new Login link makes Forgot Password reachable. In development, `APP_BASE_URL` may be `http://127.0.0.1:5000`; reset links then point to `/reset-password/<token>`. Production uses an explicitly configured trusted HTTPS base URL. No change to launch configuration is planned unless implementation discovers an existing configuration gap.

## 12. Requirements traceability

| Requirement | Design elements | Planned tests |
|---|---|---|
| FR-AUTH-FORGOT-001 | `GET/POST /forgot-password`, `forgot_password.html`, CSRF | FR-01, FR-15 |
| FR-AUTH-FORGOT-002 | Existing `normalize_email()` before lookup | FR-04 |
| FR-AUTH-FORGOT-003 | Existing User lookup and Gmail SMTP sender | FR-02, FR-16 |
| FR-AUTH-FORGOT-004 / SEC-AUTH-ENUM-001 | Exact generic message and same response for both cases | FR-02, FR-03, FR-16 |
| FR-AUTH-FORGOT-005 / SEC-AUTH-ABUSE-001 | Complex rate limiting deferred; future enhancement | Scope decision; no blocker test |
| FR-AUTH-FORGOT-006 | Version increment on issuance invalidates earlier token | FR-08 |
| FR-AUTH-FORGOT-007 | Request does not change hash or authenticate | FR-02, FR-03 |
| FR-AUTH-RESET-001 | `GET/POST /reset-password/<token>`, reset template | FR-05 |
| FR-AUTH-RESET-002 / SEC-AUTH-RESET-001 | URLSafeTimedSerializer, dedicated salt, payload binding, version validation | FR-06, FR-18 |
| FR-AUTH-RESET-003 / SEC-AUTH-TOKEN-002 | `max_age=900`, single-use version advance | FR-07, FR-08, FR-09 |
| FR-AUTH-RESET-004 | New/confirm fields and existing 8-character Register minimum | FR-10 |
| FR-AUTH-RESET-005 / SEC-AUTH-PASSWORD-001 | `User.set_password()`, transaction; no plaintext storage/mail | FR-11, FR-17 |
| FR-AUTH-RESET-006 | Flash success, redirect `/login`, no auto-login | FR-14 |
| FR-AUTH-RESET-007 | No global session-revocation mechanism; leave other sessions alone | FR-14, COMPAT-01 |
| FR-AUTH-RESET-008 | Existing User credentials updated | FR-12, FR-13 |
| FR-AUTH-MAIL-001 / SEC-AUTH-MAIL-001 | smtplib + EmailMessage, Gmail settings from environment | FR-02, FR-16 |
| FR-AUTH-MAIL-002 | Minimal plain-text message and action link only | FR-17 |
| FR-AUTH-MAIL-003 | Safe caught exceptions, generic response, no partial password update | FR-16 |
| FR-AUTH-MAIL-004 | Accept recipient regardless of provider/domain | FR-02 |
| SEC-AUTH-CSRF-001 | Existing Flask-WTF global protection | FR-15 |
| SEC-AUTH-LOG-001 | Redacted fixed failure log; no token/password/SMTP secret | FR-16 |
| SEC-AUTH-URL-001 | Trusted configurable APP_BASE_URL | FR-02 |
| NFR-AUTH-COMPAT-001/002, NFR-AUTH-UI-001/002 | Shared User and hash method; additive route/link; current UI and autocomplete | FR-01, FR-11 through FR-15, COMPAT-01 |

Email verification (`FR-AUTH-VERIFY-*`) is optional/deferred and deliberately has no implementation design in this slice.

## 13. Design gate and next action

**AUTH_RECOVERY_DESIGN_STATUS: PASS** — routes, inputs/CSRF/status behavior, current UI integration, signed 15-minute token, one-time use, additive SQLite migration, Gmail SMTP settings, secret handling, generic enumeration-safe response, SMTP failure behavior, session scope, and test plan are defined. No existing feature is intentionally removed.

**IMPLEMENTATION_READY: YES** — subject to creating/assigning backlog tracking as required by the Requirements document and configuring local sender credentials outside Git.

**NEXT_ACTION: Implementation Plan Auth Recovery**
