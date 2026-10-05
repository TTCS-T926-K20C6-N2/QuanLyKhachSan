# Auth Recovery Final Delivery

**Feature:** Forgot Password and email-based Reset Password  
**Delivery status:** Code and automated verification PASS  
**Real Gmail delivery:** NOT VERIFIED; local sender credentials are not configured in this environment.

## 1. Delivered behavior

- Login includes a `Quên mật khẩu?` link to the Forgot Password flow.
- Anonymous `GET/POST /forgot-password` normalizes email, increments the registered User's reset version atomically, commits it before mail delivery, and always returns the approved generic message for syntactically valid addresses.
- Anonymous `GET/POST /reset-password/<token>` validates a dedicated-salt `itsdangerous.URLSafeTimedSerializer` token with a 900-second maximum age, account binding, purpose, and current version.
- Reset uses the existing `User.set_password()` scrypt hashing behavior. A conditional update commits the password hash and incremented reset version together, preventing replay. Success redirects to `/login` without creating a session.
- Gmail SMTP uses `smtplib` and `EmailMessage`, STARTTLS configuration, a bounded timeout, and safe failure handling. No credential or reset token is logged or persisted.
- `User.password_reset_version` is non-null with default zero. Existing SQLite databases receive an additive, idempotent column migration without rebuilding tables.
- Forgot and reset pages reuse the current Hotel Management auth styling. Email verification remains deferred.

## 2. Routes and public responses

| Route | Behavior |
|---|---|
| `GET /forgot-password` | Displays the email request form. |
| `POST /forgot-password` | For a validly submitted email, known and unknown addresses receive the same message: “Nếu email tồn tại trong hệ thống, hướng dẫn đặt lại mật khẩu sẽ được gửi.” Only a matching User triggers mail delivery. |
| `GET /reset-password/<token>` | Displays reset form for a valid, current token; invalid/expired/replayed links receive a generic safe error. |
| `POST /reset-password/<token>` | Validates CSRF, token/version and password confirmation; atomically updates hash/version, then redirects to `/login` without auto-login. |

## 3. Security and privacy

- Passwords are hashed with the existing scrypt method; no plaintext password is stored or emailed.
- Reset tokens are signed, purpose-bound, expire after 900 seconds, and are not stored in the database.
- A newer reset request invalidates prior links even when SMTP delivery fails. A successful reset invalidates the used link and other outstanding links.
- CSRF protection remains active for both POST forms.
- Known/unknown email response message, status, redirect pattern, and rendered result match. SMTP timing may differ because only known accounts cause a send attempt.
- `.env.example` contains blank credential placeholders; `.env` is ignored. No real SMTP credential was found in the reviewed changes. No application dependency was added.
- No global session revocation or advanced rate limiting was added, in line with approved policy.

## 4. Final verification

- Focused recovery tests: **20 passed, 0 failed**.
- Full suite: **153 passed, 0 failed**.
- `python -m compileall src tests`: **PASS**.
- `git diff --check`: **PASS**.
- Flask test-client smoke: `/login` 200; `/forgot-password` 200; invalid reset token 400 with safe UI; unknown-email submission 200 with generic response.
- SQLite migration tests preserve a legacy User ID, email, and password hash, set reset version to zero, and verify repeat startup. No project `instance/hotel.db` existed in this workspace, so no runtime database was created or altered during final delivery.
- `.env` is ignored and absent here. Mail credential availability was checked without reading or printing values; `MAIL_USERNAME`, `MAIL_PASSWORD`, and `MAIL_FROM` are not configured.
- VS Code F5 launch configuration was not changed. Local route smoke used the Flask test client; an interactive F5 browser session was not launched during this final step.
- No real Gmail network request was made. Automated mail tests use mocks.

## 5. Remaining manual Gmail verification

`MANUAL_GMAIL_TEST: BLOCKED_BY_LOCAL_CREDENTIALS`  
`REAL_GMAIL_DELIVERY_STATUS: NOT_VERIFIED`

To complete the real delivery check:

1. Copy `.env.example` to local `.env`.
2. Configure an authorized Gmail sender and a supported secure SMTP credential (App Password where available) in `MAIL_USERNAME`, `MAIL_PASSWORD`, and `MAIL_FROM`; keep `.env` untracked.
3. Set `APP_BASE_URL` to the local app origin and run the existing VS Code F5 configuration.
4. Use an existing test account at an inbox the tester can access; request a reset, verify the message and 15-minute link, reset, confirm the old password fails/new password works, and confirm the same link is rejected on reuse.
5. Optionally request two links in sequence and verify the earlier link is rejected. Do not put credentials, passwords, or token URLs in logs or reports.

The manual newer-request invalidation flow was not run; automated tests verify it.

## 6. Regression and Git readiness

Existing Login, Register, Logout, Change Password, Profile, Home, Room, Room Type, and rental behaviors remain covered by the passing full suite. `tests/test_room_types.py` contains the separate approved baseline assertion update from `room-legend` to current `status-summary`; its ordering assertion remains intact.

Expected Auth Recovery files and the baseline repair are the only code/config changes reviewed. The requirements, design, implementation-plan, review, and final-delivery documents are present. No unexpected application deletions were found. No `git add`, commit, push, merge, or PR was performed.

**AUTH_RECOVERY_FINAL_DELIVERY_STATUS: PASS**  
**READY_FOR_GIT_COMMIT: YES**  
**READY_FOR_TEAM_MERGE: YES**
