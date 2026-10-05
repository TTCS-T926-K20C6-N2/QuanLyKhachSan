# Authentication Recovery Requirements

**Status:** Requirements updated with approved Auth Recovery Policy  
**Scope:** Email verification, forgot password, password reset, and authentication email delivery  
**Baseline reviewed:** Current repository source, templates, configuration example, README, and tests  
**Implementation status:** Not implemented by this document

## 1. Purpose and traceability

This document specifies requirements for adding account email verification and password recovery to the current Hotel Management application. It supplements the existing Login/Register requirements and does not replace them.

- `SOURCE_STATUS: NOT_IN_ORIGINAL_BACKLOG` — the README identifies Login as SCRUM-21 / PB-01; no supplied backlog records Forgot Password or this extension.
- `APPROVAL_REQUIRED: YES` — the extension is approved by the user for Requirements/Design progression; backlog tracking must still be assigned before implementation. No Jira item is inferred here.
- `TEAM_REQUESTED_EXTENSION: YES` — requested in the user-provided task prompt.
- No existing `docs/01_requirements.md`, `docs/requirements_decisions.md`, or `docs/product_backlog.md` was present in the repository when reviewed.

## 2. Current baseline and compatibility

The current application uses Flask, Flask-SQLAlchemy, SQLite, Jinja templates, Flask sessions, Flask-WTF CSRF protection, and Werkzeug password hashing. `User` is the shared persistent account model, with `id`, `email`, `password_hash`, and profile fields. `normalize_email` strips surrounding whitespace and applies `casefold()`. Registration rejects duplicate normalized emails, requires a password of at least eight characters, requires matching confirmation, stores a scrypt hash, and redirects to Login. A newly registered account can currently log in immediately. Login establishes a session containing `user_id`; login failures use a generic invalid-credentials message. Change Password verifies the current password and uses the existing hash setter.

There is no current email-verification or password-recovery route, token storage, or mail configuration. The current login and registration templates use the Hotel Management visual identity. Any future pages must follow the current Login/Register/base templates and `style.css`/`hotel.css`; CodeGym references are functional only and must not be copied visually.

Compatibility requirements:

- **NFR-AUTH-COMPAT-001:** The extension SHALL use the existing `User`, database, email normalization, password-hashing, and session mechanisms. It SHALL NOT create a second user model or authentication database.
- **NFR-AUTH-COMPAT-002:** Existing Login, Register, Logout, account/profile, Change Password, and hotel features SHALL remain usable and retain their current behavior except where an explicit approved verification policy requires a narrowly scoped change.
- **NFR-AUTH-COMPAT-003:** Email verification is not required in this phase. The current Register flow SHALL NOT change, and Login SHALL NOT be blocked by verification state. Verification may be proposed later as a separate extension.
- **NFR-AUTH-UI-001:** New authentication pages and links SHALL follow the current Hotel Management UI. They SHALL NOT imitate CodeGym branding or page composition.
- **NFR-AUTH-UI-002:** Password fields SHALL use browser-compatible autocomplete semantics. Implementing browser password-manager functionality is out of scope.

## 3. Functional requirements

### 3.1 Email verification

**Phase status: OPTIONAL / DEFERRED.** Email verification is not part of the currently approved implementation scope. The requirements below are retained for a possible future extension and SHALL NOT change current Register or Login behavior in this phase.

- **FR-AUTH-VERIFY-001 — Verification state:** The system SHALL persist whether each account email is verified. Verification state SHALL belong to the existing User account. The specific schema representation is an implementation/design decision.
- **FR-AUTH-VERIFY-002 — Verification email:** When registration is configured to require or offer verification, the system SHALL request delivery of a verification link to the normalized email address submitted for that account.
- **FR-AUTH-VERIFY-003 — Token validation:** A verification link SHALL identify its intended account using an unguessable, integrity-protected verification token. A valid token SHALL verify only the matching account.
- **FR-AUTH-VERIFY-004 — One-time use:** A successfully consumed verification token SHALL NOT verify another account or cause repeat side effects if visited again.
- **FR-AUTH-VERIFY-005 — Invalid and expired links:** Invalid, tampered, expired, or already-used links SHALL NOT change account verification state. The user SHALL receive a clear recovery path, such as requesting a fresh verification email, without exposing account data unnecessarily.
- **FR-AUTH-VERIFY-006 — Resend:** The system SHALL support a user-initiated resend flow for accounts requiring verification, subject to the approved rate policy. Responses SHALL avoid revealing whether an email is registered.
- **FR-AUTH-VERIFY-007 — Login policy:** If verification is implemented as a future extension, it SHALL NOT block Login unless a later policy explicitly changes this decision.

Acceptance criteria:

1. In the current phase, registration continues without requiring verification or sending a verification email.
2. A valid, unexpired token marks only the corresponding User as verified, and the state persists after application restart.
3. An unknown, tampered, expired, or consumed token does not verify an account or alter unrelated account state.
4. Reusing a successfully consumed token produces a safe informational outcome and no new side effect.
5. A resend request follows the chosen rate policy and has a response that does not disclose account existence.
6. Login for existing and newly registered accounts remains available under the current flow, regardless of any deferred verification state.

### 3.2 Forgot Password

- **FR-AUTH-FORGOT-001 — Request form:** The system SHALL provide `GET /forgot-password` and a CSRF-protected form accepting an email address.
- **FR-AUTH-FORGOT-002 — Normalize and process:** Submitted email SHALL be normalized using the existing trim-and-casefold rule before account lookup. A request SHALL NOT modify the account password.
- **FR-AUTH-FORGOT-003 — Recovery email:** If a registered account exists for the normalized email, the system SHALL request delivery of a password-reset link to that account's email. Email verification is not required for recovery in this phase.
- **FR-AUTH-FORGOT-004 — Non-disclosing response:** Every syntactically handled request SHALL receive the same externally visible message, whether or not an account exists: “Nếu email tồn tại trong hệ thống, hướng dẫn đặt lại mật khẩu sẽ được gửi.” The response SHALL NOT reveal account existence.
- **FR-AUTH-FORGOT-005 — Abuse controls:** Complex Redis- or database-backed rate limiting is not required for this phase and SHALL NOT block Design. Basic protections may be selected during Design; stronger rate limiting is a future enhancement.
- **FR-AUTH-FORGOT-006 — Resubmission:** A user may submit another request. Creating a new reset request SHALL invalidate or supersede previous outstanding reset tokens for that account.
- **FR-AUTH-FORGOT-007 — No password change:** Merely submitting a forgot-password request SHALL never change the password or authenticate the requester.

Acceptance criteria:

1. `GET /forgot-password` returns a form containing an email field.
2. A valid POST requires a valid CSRF token and normalizes email using the existing rule.
3. Existing and nonexistent email submissions receive the same public success response; no response confirms account existence.
4. An eligible existing account causes a reset email request to its normalized recipient; a nonexistent account causes no mail to an arbitrary recipient.
5. Submitting a request does not change the password hash or create an authenticated session.
6. Repeated requests do not require a Redis/database rate-limit subsystem; previous outstanding tokens are handled according to the reset-token policy.

### 3.3 Reset Password

- **FR-AUTH-RESET-001 — Reset form:** A valid reset link SHALL open a form accepting a new password and its confirmation.
- **FR-AUTH-RESET-002 — Token and account binding:** The reset token SHALL be securely signed, bound to one account and one reset request, and validated before a password update. Unknown, tampered, expired, or consumed tokens SHALL be rejected without changing credentials. Plaintext token values SHALL NOT be stored.
- **FR-AUTH-RESET-003 — Expiration and one-time use:** Reset tokens SHALL expire 15 minutes after issuance and SHALL be usable at most once. A successful reset SHALL consume the token so it cannot be reused.
- **FR-AUTH-RESET-004 — Password validation:** The system SHALL require the new password and confirmation to match and SHALL enforce the current Register minimum of eight characters.
- **FR-AUTH-RESET-005 — Secure update:** On a valid submission, the system SHALL update the existing User's password hash using the current Werkzeug scrypt hashing mechanism. Plaintext passwords SHALL NOT be persisted or sent by email.
- **FR-AUTH-RESET-006 — Completion:** After successful reset, the system SHALL redirect the user to Login and SHALL NOT automatically log the user in.
- **FR-AUTH-RESET-007 — Session handling:** This phase SHALL NOT add complex session revocation. Existing sessions for other users need not be revoked after a reset. The current Change Password session flow SHALL remain unchanged.
- **FR-AUTH-RESET-008 — Existing credentials:** After successful reset, the new password SHALL authenticate the account and the prior password SHALL no longer authenticate it.

Acceptance criteria:

1. A valid unexpired token displays the reset form for its associated account without revealing unnecessary account details.
2. Invalid, altered, expired, or consumed tokens cannot update the password.
3. A mismatched confirmation and a password below the approved minimum are rejected without changing the hash.
4. A successful reset persists a scrypt password hash that is not equal to the submitted plaintext.
5. After success, the token cannot be reused, the prior password fails, the new password succeeds, and the user is redirected to Login without an authenticated session being created.
6. Other outstanding reset links for that account are rejected after a successful password reset.
7. No session-revocation subsystem is introduced; Change Password behavior remains as in the current baseline.

### 3.4 Authentication email delivery

- **FR-AUTH-MAIL-001 — Delivery capability:** The Flask application SHALL be able to request delivery of verification and reset messages through an email-delivery service using Gmail SMTP as the planned provider and the intended recipient address.
- **FR-AUTH-MAIL-002 — Message content:** Authentication emails SHALL contain only the relevant action link and user guidance. They SHALL NOT contain current, new, or temporary plaintext passwords.
- **FR-AUTH-MAIL-003 — Delivery failure:** Mail-delivery failures SHALL be handled without corrupting account credentials. The forgot-password response remains generic; retry/operational handling may be decided during Design.
- **FR-AUTH-MAIL-004 — Supported recipients:** The system SHALL accept valid recipient addresses across email providers. Registration SHALL NOT be restricted to `@gmail.com` unless that business rule is explicitly approved.

Acceptance criteria:

1. Verification and reset messages are addressed to the email belonging to the matching User.
2. Message content contains the appropriate action link and no plaintext password.
3. A mail failure does not change a password, mark an email verified, or expose account existence through a differentiated forgot-password response.

## 4. Security and operational requirements

- **SEC-AUTH-RESET-001 — Reset token security:** Reset tokens SHALL be securely signed, have sufficient entropy to resist guessing, be bound to one user and purpose, and be validated against tampering. Plaintext token values SHALL NOT be stored. Token format and signing mechanism are finalized in Design.
- **SEC-AUTH-VERIFY-001 — Verification token security:** Verification tokens SHALL be cryptographically unpredictable, purpose-bound, time-limited, and single-use.
- **SEC-AUTH-TOKEN-002 — Expiration/replay:** Verification and reset links SHALL NOT remain valid indefinitely. Expired or consumed tokens SHALL have no effect.
- **SEC-AUTH-ENUM-001 — Account enumeration:** Forgot-password and resend-verification responses SHALL not reveal whether an account exists or is eligible.
- **SEC-AUTH-PASSWORD-001 — Plaintext prohibition:** The system SHALL NOT store, log, email, or otherwise disclose plaintext passwords. Passwords SHALL continue to be stored only as hashes.
- **SEC-AUTH-LOG-001 — Sensitive logging:** The system SHALL NOT log passwords or complete verification/reset bearer tokens. Logs may record non-secret event metadata needed for operations.
- **SEC-AUTH-CSRF-001 — CSRF:** All state-changing form submissions, including forgot-password requests, resend requests, and password reset, SHALL require CSRF protection consistent with the existing Flask-WTF approach.
- **SEC-AUTH-MAIL-001 — Mail credential security:** Gmail sender credentials SHALL not be hard-coded or committed. They SHALL be provided outside source code through environment configuration. `.env.example` SHALL contain placeholders only, never real credentials or App Passwords.
- **SEC-AUTH-URL-001 — Link origin:** Development links MAY use `http://127.0.0.1:5000`. Non-development reset/verification URLs SHALL use a configurable trusted base URL and SHALL not rely on a hard-coded production domain or an untrusted Host header.
- **SEC-AUTH-ABUSE-001 — Sending abuse:** Rate limiting beyond simple safeguards is a future enhancement. Redis/database-backed rate limiting is not a prerequisite for Requirements or Design in this phase.

Candidate future mail settings (not a configuration decision or implementation in this document): `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`.

## 5. Scope exclusions

This requirements extension excludes OAuth/Google login, JWT, Redis, SMS/phone verification, social login, admin password reset, multi-factor authentication, production mail infrastructure, and background job queues. It does not implement SMTP, change existing source, add dependencies, or redesign authentication UI.

## 6. Requirement coverage and gates

| Area | Requirements |
|---|---|
| Email verification (deferred) | FR-AUTH-VERIFY-001 through FR-AUTH-VERIFY-007 |
| Forgot Password | FR-AUTH-FORGOT-001 through FR-AUTH-FORGOT-007 |
| Reset Password | FR-AUTH-RESET-001 through FR-AUTH-RESET-008 |
| Mail delivery | FR-AUTH-MAIL-001 through FR-AUTH-MAIL-004 |
| Security | SEC-AUTH-RESET-001, SEC-AUTH-VERIFY-001, SEC-AUTH-TOKEN-002, SEC-AUTH-ENUM-001, SEC-AUTH-PASSWORD-001, SEC-AUTH-LOG-001, SEC-AUTH-CSRF-001, SEC-AUTH-MAIL-001, SEC-AUTH-URL-001, SEC-AUTH-ABUSE-001 |

**CURRENT_FEATURE_REGRESSION:** NO — this is a requirements-only artifact. Existing behavior has been recorded as the compatibility baseline; no implementation has been made.

**AUTH_RECOVERY_REQUIREMENTS_STATUS: PASS** — Forgot Password, Reset Password, email delivery, password/token security, testable acceptance criteria, compatibility constraints, and approved policy are documented. Redis/database rate limiting is not a blocker for Design. Backlog tracking is still required before implementation.

**EMAIL_VERIFICATION_STATUS: OPTIONAL** — not required in this phase; Register and Login remain unchanged. It may be added later as a separate extension.

## 7. AUTH_EXTENSION_OPEN_QUESTIONS

### Blocking before implementation

No policy questions remain blocking for Design. Backlog item/identifier, Gmail sender account ownership, production base URL configuration, and mail-failure operations must be settled before implementation/deployment, but do not block Design.

### Non-blocking / design decisions

1. If verification is proposed later, should registration show a pending-verification message and offer resend?
2. Should a separate security notification email be sent after successful password reset?
3. Which basic safeguards, if any, should complement the generic response before a future rate-limit enhancement?
4. What retry and operational alert/logging policy applies to email delivery failures?

## 8. Next action

**NEXT_ACTION: Design Auth Recovery** using the approved policy above. Design should preserve the current main-branch authentication UI and shared account model. Email verification remains deferred, and rate limiting is a future enhancement.
