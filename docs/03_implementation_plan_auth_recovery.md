# Auth Recovery Implementation Plan

**Source of truth:** Current `main` source and [`01_requirements_auth_recovery.md`](01_requirements_auth_recovery.md) plus [`02_design_auth_recovery.md`](02_design_auth_recovery.md).  
**Scope:** Forgot Password, Gmail reset email, signed one-time Reset Password.  
**Plan status:** Ready for implementation; no application code is included here.

## 1. Existing architecture inspected

- `src/hotel_app/models.py` contains one shared `User`, `normalize_email()`, `User.set_password()` (Werkzeug scrypt), and `check_password()`.
- `src/hotel_app/app.py` builds a Flask app factory, initializes `db` and global Flask-WTF `csrf`, defines the current authentication routes, and calls `db.create_all()` at startup. Immediately afterward, it inspects `users` and performs additive `ALTER TABLE` statements for profile columns inside an engine transaction. This is the migration location for the new counter.
- Login/Register are standalone templates using `page-shell`, `auth-card`, `field`, `alert`, `auth-switch`, and `style.css`. `base.html` is the authenticated dashboard layout and is not appropriate for the logged-out recovery pages.
- Current `style.css` already provides the auth page components, form fields, buttons, focus states, validation errors, and success/error alerts. No CSS change is expected.
- Current environment configuration is assembled in `create_app()` from environment variables; there is no dotenv dependency or mail package. Python standard library SMTP is sufficient. `SECRET_KEY` is generated for Development/Testing if absent and required from the environment elsewhere.
- `.gitignore` already contains `.env`. Existing tests use `create_app`, temporary SQLite databases, Flask test client, and fixture-created Users.
- No Alembic or email-verification feature is present. Verification stays deferred.

## 2. File-by-file change plan

| File | Why / exact responsibility | Symbols and dependencies | Ordering / risks / tests |
|---|---|---|---|
| `src/hotel_app/models.py` | Add `User.password_reset_version`, integer, non-null, Python default 0 and SQL/server default 0 where supported by current SQLAlchemy style. Keep existing `User.set_password()` as the sole reset hashing path. No token field/model. | `User`; SQLAlchemy only. | Step 1. Existing User constructors and Register need no explicit change because the default supplies 0. Test default and persisted value in fresh and upgraded DB. |
| `src/hotel_app/app.py` | Extend startup schema compatibility map with `password_reset_version INTEGER NOT NULL DEFAULT 0`, guarded by the existing inspected column set. Add only recovery routes, mail/config values, and the Forgot link context if needed. Leave existing route bodies and unrelated Room endpoints alone. | `create_app`, current `db.create_all()`/`inspect`/`text` startup migration, `forgot_password`, `reset_password`, `url_for`, existing `csrf`, `flash`, `redirect`, `render_template`, `request`, `normalize_email`, `User`. | Steps 1, 4, 5. Risk: route placement/error-handler fallthrough and preserving logged-out access; test CSRF, statuses, generic response, and full suite. Do not rename any current endpoints. |
| `src/hotel_app/auth_recovery.py` **new** | Isolate token serialization/validation and atomic reset operation to keep large `app.py` focused. | Proposed functions below; import `User`/`db` only inside the reset helper or accept the model/session dependency to avoid importing `app.py`. Flask app config passed in; `itsdangerous` already comes through Flask. | Step 2. No import from `app.py` at module load and no circular import. Unit/route tests exercise lifecycle and transaction rollback. |
| `src/hotel_app/mail.py` **new** | Own settings validation, message composition and SMTP transport via `EmailMessage` + `smtplib`; make the transport easy to monkeypatch. | Proposed `send_password_reset_email(...)`; standard library only. Configuration passed as values or read from Flask `current_app.config`; avoid global app imports. | Step 3. Tests replace SMTP transport, never call Gmail. Catch SMTP/auth/TLS/timeout/network errors at this boundary and raise a sanitized delivery exception or return a failure result. |
| `src/hotel_app/templates/login.html` | Add one `Quên mật khẩu?` link to `url_for('forgot_password')` in the existing auth card. | Existing `login` endpoint; existing `auth-switch` styling. | Step 6. Do not alter Login form, CSRF, Register link, validation, or `username`/`current-password` autocomplete. Test rendered link. |
| `src/hotel_app/templates/forgot_password.html` **new** | Logged-out request form with email, CSRF, generic success notice, field validation, Login navigation. Reuse auth page markup and `style.css`. | `forgot_password` endpoint; `csrf_token()`, existing classes. Email `autocomplete="email"`. | Step 6. Test GET, fields, CSRF, exact generic message, style hooks. |
| `src/hotel_app/templates/reset_password.html` **new** | Reset form shown only after valid token; safe invalid/expired state may use same template or generic error panel. | `reset_password` endpoint; `csrf_token()`, existing classes. Both password inputs `autocomplete="new-password"`, minlength 8. | Step 6. Never echo/refill passwords or show token exception details. Test fields, error accessibility, invalid-link behavior. |
| `src/hotel_app/static/css/style.css` | No planned change; current auth styles cover pages. | Existing auth selectors. | Step 7 check only. Change only if implementation reveals a concrete visual gap; if changed, add the smallest selector and inspect Login/Register for regression. |
| `src/hotel_app/static/css/hotel.css` | No change; dashboard styles do not own the standalone authentication pages. | None. | No step beyond confirming auth pages do not depend on dashboard styling. |
| `.env.example` | Add blank mail credential variables and safe development defaults for server/port/TLS/base URL. Never include real email/App Password. | `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, `APP_BASE_URL`. | Step 8. Review diff for secret-like values. |
| `.gitignore` | No change expected; `.env` is already ignored. | Existing `.env` entry. | Step 8 check only. Verify with `git check-ignore .env`; do not change unrelated rules. |
| `README.md` | Small setup section: configure local Gmail sender using supported account security/App Password, copy `.env.example` to `.env`, fill local `MAIL_*` values, run using existing F5 workflow. No actual credentials/tutorial. | Env keys and current VS Code run instructions. | Step 8. Do not change the existing F5 URL/launch behavior. |
| `tests/test_auth_recovery.py` **new** | Focused route, token, mail, CSRF, migration, and compatibility tests using current fixtures/test-client style. | Existing `app`, `client`, `db`, `User`, and helper functions; monkeypatch SMTP. | Steps 9–10. No live Gmail. Do not weaken existing tests. |
| `requirements.txt` | No change. `itsdangerous` is available through Flask and mail uses standard library. | Existing dependencies only. | Verify no dependency is added. |

No changes are planned to `extensions.py`, `base.html`, `hotel.css`, current test files, or unrelated application routes.

## 3. Model and existing SQLite migration

### Model

Add one `User` column equivalent in intent to:

```text
password_reset_version: Integer, nullable=False, default=0, database default 0
```

The default keeps every current User constructor valid, including Register, demo seeding, and test fixtures. Reuse `User.set_password()`; do not create `ResetToken`, a second account model/table, or any plaintext token/password field.

### Startup migration

Use the existing startup sequence in `create_app()`:

1. `db.create_all()` creates the new column for fresh databases.
2. Inspect `users` columns.
3. In the existing `db.engine.begin()` transaction, add `password_reset_version INTEGER NOT NULL DEFAULT 0` only if absent.
4. Continue existing seeding only after schema compatibility completes.

Existing `instance/hotel.db` is preserved. SQLite adds the integer column with value/default zero for prior records; no user row or password hash is deleted or rebuilt. Repeated startup is idempotent because the column is inspected first. If the DDL fails, the transaction rolls back and app initialization must fail visibly; do not continue with an ORM/schema mismatch and do not silently delete/recreate the DB. No Alembic is introduced.

## 4. Helper/module contracts

### `src/hotel_app/auth_recovery.py`

| Helper | Input | Output | Side effects | Errors |
|---|---|---|---|---|
| `generate_password_reset_token(user, secret_key)` | Persisted User with ID/current version; configured `SECRET_KEY` | URL-safe timed signed token with `uid`, `prv`, and purpose | None | Configuration/programming errors; never log generated token |
| `validate_password_reset_token(token, secret_key, user_loader)` | Token, key, and lookup callback or SQLAlchemy User model | Matching User on valid token; a single generic invalid result (`None`/typed result) otherwise | Read-only account lookup | Catch `BadSignature`, `SignatureExpired`, malformed payload/type/value issues; do not expose error detail |
| `reset_password_for_token(user_id, token_version, new_password)` | Account ID, validated expected version, password meeting route policy | Success indicator / updated User | Conditional version-checked update, calls `User.set_password`, increments version, commits atomically | On DB failure rollback and raise sanitized persistence error; stale version returns rejected result |

Serializer settings: `URLSafeTimedSerializer(SECRET_KEY, salt="hotel-auth-password-reset-v1")`; deserialize with `max_age=900`. Require payload `purpose == "password-reset"`, integer user ID/version, and exact current version. Keep helpers independent of Flask route functions; do not import `app.py`.

### `src/hotel_app/mail.py`

| Helper | Input | Output | Side effects | Errors |
|---|---|---|---|---|
| `send_password_reset_email(recipient, reset_url, config)` | Recipient from normalized existing User, absolute trusted reset URL, mail configuration | Sent/failed result | Builds plain-text `EmailMessage`; SMTP connect with bounded timeout; STARTTLS on port 587 when enabled; authenticates and sends | Convert SMTP authentication, SMTP protocol, TLS, DNS/network, timeout, and unexpected transport failures into a sanitized delivery result/exception; never include credentials/token/body in error text or logs |

Subject: `Đặt lại mật khẩu - Hotel Management`. Body: request notice, reset URL, 15-minute expiry, ignore-if-unrequested instruction. No passwords, hash, or unrelated account data.

## 5. Token issuance, expiration, replay and transaction order

### Forgot request for an existing account

1. Normalize using existing trim + `casefold()` behavior and find User.
2. If no User, skip token creation and email. Continue to the exact same generic message and redirect.
3. If User exists, increment `password_reset_version` and commit that increment first.
4. Generate a token containing the incremented version and build URL using configured trusted `APP_BASE_URL` (default development base `http://127.0.0.1:5000`), not an untrusted Host header.
5. Attempt SMTP delivery.
6. Whether delivery succeeds or fails, keep the increment committed. On failure, old tokens remain invalid, log a safe fixed diagnostic, and still show the approved generic response. This is the chosen policy: a mail outage can require the user to submit a fresh request; it cannot resurrect an older potentially compromised link.

This ordering makes every newer accepted reset request revoke old links. It avoids an open database transaction during network I/O.

### Validation order

1. Deserialize/verify signature with dedicated salt and `max_age=900`.
2. Reject signature error, expiry, malformed encoding or non-dictionary payload through one safe generic result.
3. Validate payload purpose and integer `uid`/`prv` fields.
4. Load User by ID; unknown user is generic rejection.
5. Compare payload version with persisted `password_reset_version`; mismatch means superseded/used token.
6. GET may render the form only after checks. POST repeats all checks immediately before update.

No detailed error is shown or logged; never log the complete token or URL.

### Reset success

Validate token, password presence/minimum 8, and confirmation match. In one DB transaction, perform a conditional update that only matches the User ID and still-current token version, use `User.set_password(new_password)`, increment `password_reset_version`, then commit. If the conditional update matches no row, treat token as expired/replayed/superseded. If any database operation/commit fails, rollback and leave both password hash and version unchanged; show safe service error. After commit, flash success and redirect to `/login`; do not create or clear a session. The version increment invalidates the token immediately and invalidates every other outstanding link.

## 6. Route plan

| Endpoint and methods | Authentication | GET | POST / validation and helpers | CSRF / response / error handling |
|---|---|---|---|---|
| `forgot_password` — `/forgot-password`, GET/POST | Anonymous allowed | Render `forgot_password.html`, empty email/errors. | Read email, normalize with `normalize_email()`. If blank, render accessible field error without lookup. If User exists, increment and commit version, call `generate_password_reset_token`, build trusted URL, call `send_password_reset_email`. Unknown account skips mail. | Global Flask-WTF CSRF applies. All valid submitted email addresses receive exact message `Nếu email tồn tại trong hệ thống, hướng dẫn đặt lại mật khẩu sẽ được gửi.` with same redirect/render shape. Use Post/Redirect/Get to `/forgot-password`; invalid CSRF follows existing 400. Mail error does not alter response. DB issue rolls back its DB work and shows generic service error; no account-specific wording. |
| `reset_password` — `/reset-password/<token>`, GET/POST | Anonymous allowed | Call token validator; valid token renders reset form. Invalid/expired/replay renders generic safe error and links to Login/Forgot Password; no DB mutation. | Revalidate token, validate new and confirm passwords (min 8 and equality), call atomic `reset_password_for_token`. On success flash generic success and redirect `/login`; no login. | Global CSRF applies. Validation mismatch renders field errors without changing DB. Invalid token response is generic (400 per Design). Missing/invalid CSRF follows existing 400. DB failure rolls back and safely reports temporary failure (503 where service unavailable). |

Do not put `login_required` on these routes. Do not change existing Login route logic or any Room route. Only add the Forgot Password link in `login.html`.

## 7. Templates, UI and CSS

- `login.html`: add only `Quên mật khẩu?` linking to `url_for('forgot_password')`; preserve Register link, inputs, CSRF, validation and current autocomplete.
- `forgot_password.html`: title `Quên mật khẩu | Quản lý Khách sạn`, short project-specific help, one email field with `autocomplete="email"`, CSRF field, `Gửi liên kết đặt lại mật khẩu`, `Quay lại đăng nhập`, existing alert/validation classes, exact generic response.
- `reset_password.html`: title `Đặt lại mật khẩu | Quản lý Khách sạn`, 15-minute helper, fields `new_password` and `confirm_password`, both `autocomplete="new-password"`, minlength 8, accessible errors, `Đặt lại mật khẩu`, navigation to Login and optionally Forgot Password.
- Reuse `page-shell`, `auth-card`, `eyebrow`, `intro`, `field`, `field-error`, `alert`, `alert-success`, `alert-error`, `auth-switch`, and `style.css`. Do not use dashboard `base.html` for these anonymous pages.
- Expected CSS changes: **none**. If a necessary visual gap is found, add only a narrowly scoped selector to `style.css`; no redesign or CodeGym styles.

## 8. Environment and README plan

Expose these runtime settings through app config and/or pass an explicit config mapping to the mail helper:

```text
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_FROM=
APP_BASE_URL=http://127.0.0.1:5000
```

No actual sender username or credential is a code default. `MAIL_PASSWORD` is a Google App Password or other supported secure SMTP credential, never a normal Gmail password embedded in source. Production config must provide a trusted HTTPS `APP_BASE_URL` and production `SECRET_KEY`. `.env.example` receives empty credential fields and safe non-secret defaults only. `.gitignore` already ignores `.env`; make no change unless `git check-ignore .env` contradicts the current file.

Add a concise README section: configure an authorized Gmail sender and supported account security/App Password; copy `.env.example` to local `.env`; fill mail settings locally; start with the existing VS Code F5 workflow. Do not put credentials or a long provider tutorial in README. Local development stays at `http://127.0.0.1:5000/login`.

## 9. Focused automated test plan

Create `tests/test_auth_recovery.py`, using existing fixture conventions (`app`, `client`, temporary SQLite, `User`, CSRF extraction). Monkeypatch `smtplib.SMTP`/mail transport and its `send_message`; automated tests never contact Gmail.

### Forgot page and enumeration

1. Anonymous `GET /forgot-password` is 200; email field, CSRF, current auth style and Login link render.
2. Login page contains one Forgot Password link to `/forgot-password` and retains Register link and existing input/autocomplete behavior.
3. Known normalized account request increments persisted version, invokes sender once for canonical recipient, and displays exact generic text.
4. Unknown address invokes no sender and displays the exact same message and same general redirect/status pattern as known address.
5. Uppercase/whitespace email resolves via existing `normalize_email()`.
6. Forgot POST without valid CSRF returns existing CSRF rejection and does not issue token/send email.

### Tokens and reset

7. Valid signed, current-version token GET returns reset fields and `autocomplete="new-password"`.
8. Tampered and malformed tokens are safely rejected without DB mutation.
9. Expired token (>900 seconds using controllable timestamp/serializer; no real waiting) is rejected.
10. Token referencing nonexistent User is rejected generically.
11. Version-mismatched token is rejected.
12. Request A then request B: A is rejected, B remains valid.
13. Valid reset with matching 8+ character passwords succeeds, calls existing hash behavior, increments version and redirects to `/login`.
14. Reset client has no new authenticated `user_id` session; an existing unrelated session is not globally revoked/cleared.
15. Old password fails Login and new password succeeds via unchanged Login route.
16. Reusing successful token fails; all older outstanding tokens fail.
17. Empty/missing password, mismatch, and below-minimum password preserve original hash/version.
18. Reset POST without valid CSRF is rejected.
19. No plaintext password or token is persisted; model/database has no reset token column.
20. Inject commit/update failure: rollback leaves both password hash and version unchanged, safe response returned.

### SMTP and migration

21. Mock auth failure, timeout, SMTP connection/TLS, DNS/network failure, and unexpected mail exception: no request crash/500; generic message stays identical; response/log capture contains no token, password, SMTP password, or account-existence disclosure.
22. Mock verifies configured Gmail host, port 587, STARTTLS, configured sender/recipient and subject/body contents; no real delivery.
23. Fresh database has version default zero.
24. Existing SQLite users table without column is upgraded; existing IDs, emails, password hashes and profile data survive, all old rows read version zero; second app startup is a no-op migration.

After focused tests, run the entire existing suite with `python -m pytest`. Do not delete, skip, or weaken existing tests to make the new feature pass.

## 10. Regression and manual verification

Full automated suite must pass. In addition to current tests, smoke-check:

- Login, Register, Logout, Change Password, Update Personal Information/Profile.
- Home, Rooms, Room CRUD, Room Types, rent/edit rental, and room status/count/filter behavior.
- Current session behavior and VS Code F5 opening `/login` remain unchanged.
- `git diff` contains only intended recovery changes; inspect for accidental deletion/rename, especially any feature introduced on main.

Separate manual Gmail smoke test only after automated tests pass:

1. Configure a local development sender in ignored `.env` without recording its value in logs/reports.
2. Use an existing test recipient, submit Forgot Password, and confirm the mail arrives.
3. Open the link, set a new password, verify old password fails and new password succeeds.
4. Reopen the same link and verify it is rejected.

Automated tests must never send a real email. Manual test report must not contain real credentials or reset links.

## 11. Ordered implementation sequence

| Step | Files | Changes | Tests/checks | Dependencies | Stop condition |
|---|---|---|---|---|---|
| 1. Model + schema | `models.py`, `app.py` startup block | Add version field/default and additive existing-DB migration. | Focused fresh DB and legacy DB migration tests; inspect existing data preserved. | Current `User`, current `db.create_all()` and inspected-column startup pattern. | Stop if model differs, startup migration cannot be made idempotent, or migration alters/deletes user data. |
| 2. Token helpers | New `auth_recovery.py` | Add serializer, token generation/validation, atomic consume/reset helper. | Unit tests for signature, payload, max age, version, replay, rollback/concurrency. | Step 1 schema; current Flask SECRET_KEY; existing `User.set_password()`. | Stop if `User.set_password()` is absent/changed or production signing secret is missing/unsafe. |
| 3. Mail helper/config | New `mail.py`, `app.py` config mapping, `.env.example` | Add stdlib EmailMessage/smtplib with STARTTLS and bounded timeout; runtime env settings. | Mocked success and all expected failure classes; inspect no secrets in logs. | Token/link helper and approved config key names. | Stop if mail configuration requires adding an unapproved dependency or credentials would be hard-coded. |
| 4. Forgot route | `app.py` | Add logged-out GET/POST, generic response, normalize, increment/commit before token/email. | Known/unknown equivalence, normalization, version increment, failure generic behavior, CSRF. | Steps 1–3. | Stop if enumeration-safe behavior cannot be maintained or email failure makes route disclose account state. |
| 5. Reset route | `app.py` | Add anonymous GET/POST, revalidate token, password validation, atomic update, Login redirect without session creation. | Token GET/POST, expiry/replay, password and CSRF tests, no auto-login. | Steps 1–3. | Stop on unresolved transaction race/partial update or source architecture conflict. |
| 6. UI | `login.html`, new `forgot_password.html`, new `reset_password.html` | Add one Login link and two auth pages with current classes. | Rendered link/forms/CSRF/autocomplete/accessibility checks. | Route endpoint names. | Stop if change requires redesigning Login/Register or CodeGym styling. |
| 7. Minimal CSS check | `style.css` only if strictly required | Prefer no change; add minimal selector only for verified gap. | Visual check of existing and new auth pages. | Step 6. | Stop rather than redesign if broad CSS restructuring is proposed. |
| 8. Local docs/config | `.env.example`, `README.md`, `.gitignore` check | Add blank/safe environment names and concise Gmail/F5 setup. Keep `.env` ignored. | `git check-ignore .env`; review diff for secret; confirm README F5 instructions unchanged. | Step 3 names. | Stop if any real credential appears or `.env` would be tracked. |
| 9. Focused tests | New `tests/test_auth_recovery.py` | Implement the scenarios in Section 9 with SMTP mocks. | Focused test file; no live Gmail. | Steps 1–8. | Stop on any failing new test; do not weaken existing tests. |
| 10. Full regression | All current tests and changed files | Run `python -m pytest`; inspect `git diff` and feature-specific smoke checks. | Login/Register/Logout/Change Password/Profile/Rooms/Room Types/Rentals/status and complete suite. | Step 9. | Stop and report any pre-existing or new failures; do not silently fix unrelated functionality. |
| 11. Manual Gmail smoke | Local ignored `.env`, running F5 app | Perform real test delivery and full reset/replay check. | Manual checklist above; do not disclose secret/link in report. | Automated suite passes and owner-configured sender available. | Stop on credential/provider issue; do not commit `.env` or claim delivery success. |

## 12. Stop conditions and security review

Stop implementation and report before guessing if `User.set_password()` no longer exists, current architecture conflicts with Requirements/Design, SQLite cannot be migrated safely, reset password policy is unclear, production `SECRET_KEY` is missing/unsafe, source has unresolved merge conflicts, or baseline routes/full tests are already broken before changes. Record baseline failures and do not fix unrelated behavior as part of this feature.

Before implementation review, confirm:

- [ ] Password is never emailed or logged.
- [ ] SMTP password is never logged or committed.
- [ ] Reset token is never persisted plaintext and full token/URL is never logged.
- [ ] Token is signed with dedicated salt and `max_age=900`.
- [ ] Current `password_reset_version` is checked.
- [ ] New request invalidates prior links, including if mail subsequently fails.
- [ ] Successful reset invalidates used token and other outstanding tokens.
- [ ] CSRF protects both POST routes.
- [ ] Unknown account is not disclosed; known/unknown responses match.
- [ ] Existing scrypt hashing through `User.set_password()` is retained.
- [ ] `.env` remains ignored by Git.
- [ ] Existing Login/Register/Logout/Change Password/Profile/room behavior remains intact.

## 13. Git and merge safety

Do not push, merge, or modify other feature branches automatically. Implementation should touch only the files listed in Section 2 as needed. At final review, inspect `git diff` for intended additions and accidental deletions/renames; do not overwrite current `main` work. No Git mutation is part of this plan.

## 14. Gate

**AUTH_RECOVERY_IMPLEMENTATION_PLAN_STATUS: PASS** — affected files, schema migration, token lifecycle, mail configuration/error handling, routes/templates, test plan, implementation order, stop conditions, and regression protection are concrete. No unresolved policy blocker remains.

**IMPLEMENTATION_READY: YES** — proceed with the ordered implementation only after confirming the working tree/source baseline and preserving all current-main features.

**NEXT_ACTION: Implement Auth Recovery**
