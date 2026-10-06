# OTP Password Recovery — Final Review

**Review scope:** OTP implementation, security controls, SQLite compatibility, Brevo adapter, auth UI/templates, README/configuration, focused and regression tests.  
**Implementation:** [08_implementation_otp_recovery.md](08_implementation_otp_recovery.md)

## Final flow

`/forgot-password` accepts a registered email and redirects to `/verify-reset-code`; successful OTP verification permits `/reset-password`; success redirects to `/login` without auto-login. Resending uses `POST /resend-reset-code`. The old `/reset-password/<token>` route and direct signed-link helpers are gone.

The request page uses one generic message. Unknown addresses create no User, challenge, or provider request. Brevo sends to the registered `User.email` using a configured, provider-verified `MAIL_FROM` sender. The standard-library adapter calls `POST https://api.brevo.com/v3/smtp/email`, passes `BREVO_API_KEY` in the API header, uses a finite timeout, and does not log the key, OTP, payload, recipient, or provider body. Provider acceptance means accepted by Brevo; it does not guarantee inbox delivery.

The six-digit OTP is generated with `secrets`, stored only as a challenge/user/generation-bound HMAC-SHA256 digest, and compared with `hmac.compare_digest`. It expires after five minutes, locks on the fifth wrong attempt, and is unusable after verification. The verified challenge grants a ten-minute, one-use reset authorization held through the challenge id in Flask session. Password update, generation increment, and challenge consumption share a database transaction.

Cooldown is 60 seconds and the rolling limit is five send attempts per User per 15 minutes. Failed provider attempts count and remain unusable. The boundary review confirmed a request exactly 60 seconds later is allowed; an attempt exactly 15 minutes old is outside the rolling window and no longer blocks. Expired/terminal challenge cleanup is lazy and does not remove rows needed for the rate window.

## Storage and migration

`PasswordResetChallenge` is an additive table created through the existing `db.create_all()` startup path. Existing user IDs, password hashes, reset versions, rooms, room types, rentals, and room status values are preserved. Existing startup migration behavior is idempotent; the application does not drop or recreate `users` and does not reset `instance/hotel.db`.

## Configuration and deliverability

The tracked `.env.example` has blank `BREVO_API_KEY` and `MAIL_FROM` fields and no Gmail SMTP or `APP_BASE_URL` recovery settings. `.env` is ignored by Git (`git check-ignore .env` returned `.env`) and is absent in this workspace. No Brevo environment credentials are configured. No real API request or email was attempted.

README explains that a normal user enters their registered email and six-digit code, valid for five minutes; only the backend operator configures a Brevo API key and verified sender. Never commit `.env` or credentials. Only registered accounts can trigger sends; messages are single-recipient and transactional, with the approved cooldown and rate limits. Recipient spam filtering is still possible.

## Verification results

- Baseline before implementation: **155 passed**.
- Focused Auth Recovery tests: **27 passed**.
- Full test suite: **162 passed**.
- `python -m compileall src tests`: passed.
- `git diff --check`: passed; Git emitted only normal line-ending conversion notices.
- Migration tests cover legacy User id/hash/version and repeated startup, plus room, room type, rental, and room status preservation.
- Security search found no runtime signed-link/SMTP recovery code, OTP logging, or real provider secret. Old SMTP/APP_BASE_URL references remain only in historical design documents; active app code, `.env.example`, and README no longer use them.

### Local smoke test

An isolated local Flask smoke run rendered Login, Forgot Password, Verify OTP and Register pages; checked the forgot link, OTP input attributes and resend control; posted a registered test address and reached verification; confirmed direct reset is blocked before verification and the old token URL is 404; then authenticated the test account and opened Rooms and Room Types. It used a temporary database and blank provider credentials, so no external call/email was made.

The interactive browser provider was unavailable in this environment (`cua` reported no browser), so the requested visual click-through in a browser could not be performed. The route/render smoke checks passed, but this final review records the manual-browser item as incomplete rather than claiming a visual test.

## Small review fixes

- Changed the rolling-window query to exclude a send attempt exactly 15 minutes old, and added an exact-boundary test.
- Clarified in README that normal users enter their registered email and six-digit code and do not configure Brevo.

## Known limitations

- Delivery depends on Brevo availability and account/sender configuration; provider acceptance is not proof of Inbox placement.
- Recipient-side Spam/Junk filtering remains possible.
- Abuse controls are local SQLite/database controls, not a distributed limiter; there is no Redis, global multi-instance rate limit, or background mail queue.
- No production high-availability email/recovery design is included.

**REAL_BREVO_CREDENTIALS_AVAILABLE: NO**  
**REAL_DELIVERY_ATTEMPTED: NO**  
**CURRENT_FEATURE_REGRESSION: NO**  
**OTP_RECOVERY_FINAL_DELIVERY_STATUS: FAIL — visual browser smoke could not be performed here.**  
**READY_FOR_GIT_COMMIT: NO — complete the requested browser click-through first.**  
**READY_FOR_TEAM_MERGE: NO**
