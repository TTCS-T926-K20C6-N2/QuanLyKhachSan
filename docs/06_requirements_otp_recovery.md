# OTP Password Recovery Requirements

**Revision:** OTP recovery requirements; supersedes the user-facing signed-link recovery flow for future Design/Implementation.  
**Status:** Approved scope and fixed policy values; exact technical design remains for the next stage.  
**Scope:** Password recovery by emailed six-digit OTP only.  
**Implementation status:** Not implemented by this document.

## 1. Purpose, baseline, and supersession

This document defines a six-digit email OTP flow for password recovery in the current Hotel Management application. It extends the current application and preserves Register, Login, Logout, Change Password, profile management, User/password hashing, sessions, Rooms, Room Types, rentals, and room-status functionality.

The current implementation was inspected before writing this revision:

- `app.py` currently provides `GET/POST /forgot-password` and `GET/POST /reset-password/<token>`.
- `auth_recovery.py` currently uses `itsdangerous.URLSafeTimedSerializer`, a dedicated reset salt, a 900-second expiry, Gmail SMTP through `smtplib`/`EmailMessage`, and a versioned signed token.
- `User` currently has `password_reset_version`, `set_password()`, `check_password()`, and `normalize_email()` uses trim plus case-folding.
- Current Login, Forgot Password, and Reset Password pages use the Hotel Management auth style and Flask-WTF CSRF fields.
- `.env.example` and README currently describe Gmail SMTP configuration. Existing recovery tests cover signed-link behavior.

**OLD_RECOVERY_FLOW: SIGNED_RESET_LINK**  
**NEW_RECOVERY_FLOW: EMAIL_OTP_6_DIGITS**  
**OLD_FLOW_STATUS: SUPERSEDED_BY_OTP_FLOW**

The supersession applies to the intended user-facing recovery flow after this OTP revision is approved for implementation. This Requirements-only stage SHALL NOT delete or alter current routes, helpers, templates, configuration, or tests. Future Design/Implementation SHALL identify which signed-link artifacts are replaced or retired and SHALL NOT leave two competing public recovery flows after completion unless a documented reason is approved.

`password_reset_version` SHALL NOT be removed during this stage. Future Design may retain or adapt it to identify the newest recovery generation, invalidate older OTPs, and prevent replay. This document does not decide its final schema or implementation.

## 2. Approved policy values

These values are approved and SHALL NOT be reopened as Design questions:

| Policy | Requirement |
|---|---|
| OTP format | Exactly six decimal digits, represented and processed as a fixed-length string; leading zero is valid. |
| OTP lifetime | Five minutes from issuance. Failed attempts SHALL NOT extend expiry. |
| Incorrect attempts | At most five incorrect code submissions for a challenge. The fifth incorrect attempt invalidates that code. |
| New-code behavior | Issuing a newer code invalidates every earlier code for the same account immediately. |
| Resend cooldown | At least 60 seconds between OTP sends for the same account/recovery flow. No email is sent during cooldown. |
| Send-rate limit | At most five OTP emails for one account during any 15-minute window. |
| Account enumeration | Public response behavior SHALL NOT reveal whether an email is registered. |
| Password completion | Reuse the current password validation and `User.set_password()`; do not auto-login; redirect to `/login`. |
| Recipient domain | Any valid email provider is allowed; no `@gmail.com` restriction. |
| Email service | Require a generic transactional email capability; do not select a provider in Requirements. |

Complex distributed rate-limit infrastructure is not required. The basic per-account send limit and cooldown above are requirements; a production-grade distributed limiter may be a future enhancement.

## 3. User flow requirements

The recovery flow SHALL work while the user is logged out and SHALL use the existing Hotel Management visual system. It SHALL NOT change ordinary Login, Register, Change Password, or session behavior.

### Step 1 — Request a code

The user enters their email on the Forgot Password page and chooses **Gửi mã xác nhận**. The application SHALL normalize the address using the current `normalize_email()` behavior before account lookup.

- If the normalized email belongs to a User and the request is allowed by cooldown/rate policy, the system SHALL create a new password-reset OTP challenge and request delivery of one OTP message to that User's email.
- If the email is unknown, the system SHALL NOT send an email.
- A new allowed request for a known User SHALL make every previous challenge/code for that account unusable, even if delivery of the new message later fails.
- During cooldown or when the send limit is reached, the system SHALL send no email and SHALL provide a safe response that does not disclose account existence.
- The public response for known and unknown addresses SHALL be equivalent in message wording, redirect/render pattern, and externally visible status. Recommended exact message: **“Nếu email tồn tại trong hệ thống, mã xác nhận sẽ được gửi.”** The response SHALL NOT claim that an email was found or sent to an existing account.

### Step 2 — Verify the code

The user enters the code from email in a verification form and chooses **Xác nhận**. A challenge is eligible only when it:

- belongs to the intended password-reset request and User;
- is the newest/current challenge for that User;
- is within its five-minute lifetime;
- has not expired, been consumed, or been invalidated by a newer request;
- has not exceeded the five-incorrect-attempt limit.

The submitted code SHALL be validated as a six-character decimal string, including codes beginning with zero. A malformed or incorrect submission counts as an incorrect attempt. After the fifth incorrect attempt, the challenge SHALL become unusable and the user SHALL request a new code subject to cooldown/rate limits. A successful verification ends the incorrect-attempt counter for that challenge.

### Step 3 — Reset the password

Only successful OTP verification SHALL permit the user to reach/submit the password-reset step. The user enters **Mật khẩu mới** and **Xác nhận mật khẩu mới**. The application SHALL validate both fields using the current password policy, require them to match, and update the existing User through `User.set_password()`.

After a successful password update, the system SHALL consume the reset authorization, SHALL NOT automatically log the user in, and SHALL redirect to `/login` with success feedback. The old password SHALL no longer authenticate; the new password SHALL authenticate through the existing Login flow.

The OTP SHALL stop being accepted for verification immediately after successful verification. The system SHALL then grant a single-use, request-bound reset authorization sufficient for the legitimate user to complete password entry, including retrying form validation errors. That authorization SHALL be consumed atomically with successful password update and SHALL NOT allow a second password change. Exact mechanism and lifetime are Design decisions. Failed database commit SHALL NOT partially change password or leave reset authorization reusable after an uncertain completion.

## 4. Functional requirements

- **FR-OTP-001 — Request screen:** The application SHALL provide a Forgot Password state with an email input and action labelled **Gửi mã xác nhận**. Exact route and navigation are Design decisions.
- **FR-OTP-002 — Normalize and lookup:** Submitted email SHALL be normalized by the current `normalize_email()` rule and looked up against the existing User model/database.
- **FR-OTP-003 — Registered-account send:** For a registered account and allowed request, the system SHALL generate and request delivery of one six-digit OTP to the email stored for that User. It SHALL not send to a caller-supplied alternate recipient.
- **FR-OTP-004 — Unknown-account handling:** An unknown address SHALL trigger no message. The public result SHALL remain equivalent to the result for a registered address.
- **FR-OTP-005 — Verify code:** The application SHALL provide a code-entry state with a **Mã xác nhận** field and **Xác nhận** action. A correct current code authorizes the reset step; an incorrect, expired, used, superseded, or exhausted challenge does not.
- **FR-OTP-006 — OTP string semantics:** OTP SHALL be represented as exactly six decimal characters. Leading-zero values SHALL remain valid end to end, including storage, delivery, form submission, and comparison.
- **FR-OTP-007 — Reset password:** After verification, the reset state SHALL accept new password and confirmation, enforce current password validation and matching confirmation, and update the shared User through `User.set_password()`.
- **FR-OTP-008 — Completion:** On successful reset, the system SHALL consume the one-use authorization, SHALL NOT create an authenticated session, and SHALL redirect to `/login`. Existing Login SHALL accept the new password and reject the old password.
- **FR-OTP-009 — Generic email response:** For syntactically valid requests, known and unknown emails SHALL have equivalent public message, response status, and navigation. Preferred wording is the exact message in Section 3.
- **FR-OTP-010 — Cooldown:** The system SHALL prevent another OTP send for the same account/recovery flow until 60 seconds have elapsed since the preceding send/issuance event selected during Design. A blocked resend sends no email and does not reveal account existence.
- **FR-OTP-011 — Rolling send limit:** The system SHALL prevent more than five OTP email sends for the same account in any 15-minute window. The limit applies across resend/new-code requests and cannot be bypassed by restarting the recovery flow.
- **FR-OTP-012 — Newest challenge:** Creating a newer allowed OTP challenge SHALL immediately invalidate prior challenges for that account, whether or not the newest email is ultimately delivered.
- **FR-OTP-013 — Provider failure:** Provider outage, timeout, invalid provider credential, quota rejection, and network failure SHALL NOT crash the application or return HTTP 500 solely because delivery failed. The password SHALL remain unchanged. Public behavior SHALL not reveal account existence or provider diagnostics. Retry SHALL remain subject to cooldown and send limit.
- **FR-OTP-014 — Email content:** The transactional message SHALL identify the Hotel Management password-reset action, contain the six-digit code, state that it expires in five minutes, and tell the recipient to ignore it if unrequested. It SHALL contain no password, password hash, or application secret.
- **FR-OTP-015 — Provider neutrality:** Delivery SHALL be through a generic transactional-email capability. Recipient addresses from Gmail, ICTU/school, Outlook, and other valid providers SHALL be supported. The system SHALL make no inbox-placement guarantee and SHALL not require spam-filter bypass.
- **FR-OTP-016 — Additive compatibility:** The OTP extension SHALL reuse the existing User, email normalization, password hash methods, SQLAlchemy database, CSRF protection, and Hotel Management auth style. It SHALL NOT alter Register/Login/Logout/Change Password/Profile/session behavior or Rooms/Room Types/rentals/status features.
- **FR-OTP-017 — Old-flow supersession:** The future completed OTP feature SHALL have one clear public recovery flow. The current signed-link route/helper/test behavior is marked `SUPERSEDED_BY_OTP_FLOW`; its removal/replacement is deferred to Design/Implementation and is prohibited in this Requirements-only stage.

## 5. Security and privacy requirements

- **SEC-OTP-001 — Generation:** Each OTP SHALL be generated using a cryptographically secure random-number generator over the full six-digit decimal range, preserving leading zeros.
- **SEC-OTP-002 — Protected storage/comparison:** Persistent storage SHALL NOT contain the raw OTP. The system SHALL store only a secure verifier/digest representation suitable for a six-digit low-entropy secret; Design SHALL select a representation that protects against practical offline guessing if the database alone is exposed.
- **SEC-OTP-003 — No OTP leakage:** OTP SHALL NOT be written to application logs, analytics, URLs, path segments, query parameters, or browser-visible links. It may appear only in the message to the intended recipient and the user's verification form submission.
- **SEC-OTP-004 — Expiry:** OTP becomes invalid exactly five minutes after issuance. Failed submissions SHALL NOT refresh or extend expiry.
- **SEC-OTP-005 — Attempt control:** No more than five incorrect attempts are allowed per challenge. The fifth incorrect attempt invalidates that challenge; further submissions cannot verify it.
- **SEC-OTP-006 — Replacement/replay:** A newer code invalidates older codes. A code/verified authorization SHALL be single-use; after successful verification the code cannot authorize again, and after successful password reset the associated reset authorization cannot be reused.
- **SEC-OTP-007 — Enumeration:** Forgot Password, verification, resend/cooldown, and provider-failure responses SHALL not disclose whether an account exists or expose provider/account lookup details.
- **SEC-OTP-008 — CSRF:** All state-changing form submissions for requesting, resending, verifying, and resetting SHALL use the existing Flask-WTF CSRF protection.
- **SEC-OTP-009 — Password handling:** Passwords SHALL continue to be stored only through the current password-hashing mechanism. Plaintext current/new/confirmation passwords SHALL NOT be stored, logged, or emailed.
- **SEC-OTP-010 — Provider credentials:** Transactional provider credentials/API keys SHALL be supplied outside source code and SHALL NOT be committed to Git, `.env.example`, tests, or documentation. The current Gmail SMTP settings remain unchanged during this Requirements stage.
- **SEC-OTP-011 — Abuse/spam safeguards:** Send cooldown, rolling send limit, single-recipient transactional content, and send-only-for-registered-account behavior SHALL be enforced. Messages SHALL contain no marketing content and shall not be repeatedly sent unnecessarily.

## 6. OTP state and persistence requirements

The implementation needs persistent or server-controlled state sufficient to associate a challenge and verified authorization with a User/recovery generation and enforce:

- a protected OTP verifier (never plaintext);
- issuance/expiry timestamps;
- incorrect-attempt count and invalidated/consumed state;
- newest challenge/reset generation association;
- last send time for the 60-second cooldown;
- send timestamps/count for the rolling five-per-15-minute limit;
- successful verification state and one-use password-reset authorization state.

Requirements do not prescribe a table, model, columns, cache, session representation, transaction arrangement, or migration. Design SHALL inspect the current `password_reset_version` and existing SQLite additive-migration pattern and decide whether to reuse/extend that version field, add minimal OTP state, or use another appropriately safe server-controlled approach. No second User model or authentication database is permitted.

## 7. Email provider and current mail configuration

The conceptual capability is:

```text
Flask application -> Transactional Email Provider -> User's recipient email
```

Possible providers include Brevo, Resend, SendGrid, or another transactional email provider. Requirements do not select one. No recipient-domain restriction is permitted.

The repository currently has Gmail SMTP-oriented settings: `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, and `MAIL_FROM`, plus `APP_BASE_URL`. They SHALL NOT be changed in this stage. Future Design SHALL decide whether they remain as a backward-compatible option, are replaced by provider API configuration, or are deprecated. Provider credentials/API keys must remain outside Git. Email delivery depends on provider acceptance and recipient filtering; delivery to the inbox is not guaranteed.

## 8. Compatibility, UI, and session constraints

- Keep existing Hotel Management branding and auth visual system. Do not copy CodeGym design.
- Keep Login/Register/Logout/Change Password/Profile behavior and current password autocomplete compatibility.
- Keep current Flask session architecture; recovery remains available while logged out and reset does not automatically log in.
- Keep current User and password hashing methods; no `email_verified` work is included.
- Preserve Room CRUD, Room Types, rentals, room status/count/filter features, and all existing tests.
- Do not introduce OAuth, Google Login, JWT, SMS, phone verification, TOTP, MFA for normal Login, mandatory Redis, Celery/background queues, email verification, production HA, or spam-filter bypass.

## 9. Testable acceptance criteria

1. The Forgot Password state accepts an email and presents **Gửi mã xác nhận**.
2. A normalized registered email can request one OTP email when outside cooldown and send limit.
3. Unknown email causes no outbound email.
4. Known and unknown email requests return equivalent public message, response status, and navigation, including no account-existence wording.
5. Generated OTP is exactly six decimal characters; an OTP beginning with zero is delivered and accepted correctly.
6. A correct current OTP verifies and allows the reset step.
7. Wrong OTP is rejected without changing password; each failure increments the challenge attempt count.
8. The fifth incorrect attempt invalidates the challenge; later attempts cannot verify it.
9. OTP expires after five minutes; failed attempts do not extend the expiry; expired code cannot reach/reset password.
10. A newer code invalidates an older code immediately.
11. A verified code cannot be used for a second verification; reset authorization permits at most one successful password change.
12. A successful reset uses `User.set_password()`, stores a hash rather than plaintext, makes the old password fail, and makes the new password succeed through existing Login.
13. Successful reset does not auto-login and redirects to `/login`.
14. A resend inside 60 seconds sends no message and returns a non-disclosing safe response.
15. A sixth OTP send inside a rolling 15-minute window is blocked; restarting the recovery flow does not reset the limit.
16. Provider authentication failure, unavailability, timeout, quota/network error, and missing configuration do not cause HTTP 500 or change the password; public response remains non-disclosing.
17. Database/server state contains no raw OTP; OTP is absent from logs, URLs, query parameters, and reset links.
18. Email contains Hotel Management identity, the code, five-minute expiry, and ignore-if-unrequested guidance; contains no password, hash, or application secret.
19. CSRF remains enforced on all recovery POST forms.
20. Only the intended User email receives the recovery code; valid non-Gmail addresses are supported.
21. Existing Login, Register, Logout, Change Password, Profile, Home, Room CRUD, Room Types, rentals, and room-status tests/features remain healthy.
22. The current signed-link flow is not deleted during Requirements, but future completed OTP implementation has one clear public recovery path and no unexplained competing link flow.

## 10. Open questions for Design/business confirmation

Approved values are fixed as in Section 2. The following are genuine Design/provider choices, not blockers to this Requirements document:

1. Which transactional email provider will be selected for the project/demo environment?
2. Should the existing Gmail SMTP settings remain as a backward-compatible fallback, be adapted behind the provider abstraction, or be deprecated in favor of an API provider?
3. What minimal persistent/server-controlled OTP challenge and reset-authorization representation best fits the current SQLite/SQLAlchemy bootstrap?
4. What lifetime and binding mechanism should apply to the post-verification one-use reset authorization, while allowing legitimate password-form correction and preventing another reset?
5. For cooldown/rate counting, does a send attempt consume quota before provider delivery is confirmed? Recommended for abuse safety: count challenge issuance/send attempts so provider failures cannot be used to bypass limits; Design should settle transaction ordering.
6. What precise user-facing generic notice should be used during cooldown/rate-limit blocks while keeping known/unknown account responses indistinguishable? The base request wording in Section 3 is approved.
7. Which safe operational event details may be logged for provider failures without recording OTP, recipient existence, credentials, or message body?
8. Which old signed-link helpers/routes/templates/tests/config are removed or adapted during implementation, and how will the implementation preserve a single public recovery entry point?

## 11. Traceability and gate

| Area | Requirement IDs |
|---|---|
| OTP request/verify/reset flow | FR-OTP-001 through FR-OTP-009 |
| Cooldown, send limit, replacement, provider failure | FR-OTP-010 through FR-OTP-015 |
| Compatibility and old-link supersession | FR-OTP-016 and FR-OTP-017 |
| OTP generation/storage/expiry/attempt/replay security | SEC-OTP-001 through SEC-OTP-006 |
| Enumeration, CSRF, password and provider credential security | SEC-OTP-007 through SEC-OTP-011 |

**CURRENT_FEATURE_REGRESSION: NO** — this document changes no application code; current features and current signed-link implementation remain in place at this stage.

**OLD_RECOVERY_FLOW: SIGNED_RESET_LINK**  
**NEW_RECOVERY_FLOW: EMAIL_OTP_6_DIGITS**  
**OLD_FLOW_STATUS: SUPERSEDED_BY_OTP_FLOW**

**OTP_RECOVERY_REQUIREMENTS_STATUS: PASS** — user flow, supersession, fixed OTP security values, abuse limits, provider-neutral email capability, testable acceptance criteria, and compatibility constraints are documented.

**IMPLEMENTATION_READY: NO** — proceed to Design first; select provider/config compatibility and define challenge/reset authorization persistence and lifecycle before implementation.

**NEXT_ACTION: Design OTP Recovery**
