# Spec: Authentication

| | |
|---|---|
| Feature | Authentication (register, login, logout, session) |
| Traces to BRD | FR-AUTH-01…06, NFR-01, NFR-03, BR-05 |
| Status | Draft — awaiting approval |
| Depends on | Database connection + `users` table |

## 1. Overview

A visitor can register an account with a username, email, phone number, and password. A registered user can log in, stay logged in across pages for the session, and log out. All banking and chat features require an authenticated session. Passwords are stored only as bcrypt hashes. No PII or secret is ever logged.

## 2. Data

`users` table:

| Column | Type | Notes |
|---|---|---|
| id | INT PK AUTO_INCREMENT | |
| username | VARCHAR, UNIQUE, NOT NULL | login identifier |
| email | VARCHAR, UNIQUE, NOT NULL | |
| phone | VARCHAR, NOT NULL | shown on dashboard |
| password_hash | VARCHAR, NOT NULL | bcrypt hash only |
| created_at | DATETIME, default now | |

## 3. Behaviour

**Register**
- Visitor submits username, email, phone, password.
- All fields required and non-empty; email must be a valid format; phone must be digits (basic check).
- Username and email must be unique.
- Password is hashed with bcrypt before storage; the plaintext is never stored or logged.
- On success, the user is created and routed to login (or auto-logged-in — see AC-7).

**Login**
- User submits username + password.
- On match, a session is established (`session_state`) holding the user id and a logged-in flag.
- On no match (unknown user OR wrong password), show one **generic** message ("Invalid username or password") — never reveal which field was wrong.

**Logout**
- Clears the session; user returns to the login screen.

**Session gating**
- Any page other than register/login requires a logged-in session; unauthenticated access redirects to login.

## 4. Acceptance Criteria

> These become the test cases (one or more tests each). IDs map back to FR-AUTH.

- **AC-1** (FR-AUTH-01) Registering with valid, unique username/email/phone/password creates exactly one `users` row.
- **AC-2** (FR-AUTH-01) Registering with a username or email that already exists is rejected with a clear message; no row is created.
- **AC-3** (FR-AUTH-01) Registering with any empty field, invalid email, or non-numeric phone is rejected; no row is created.
- **AC-4** (FR-AUTH-02) The stored `password_hash` is a bcrypt hash; it is never equal to the plaintext password, and the plaintext never appears in logs.
- **AC-5** (FR-AUTH-03) Logging in with correct credentials establishes a session identifying that user.
- **AC-6** (FR-AUTH-03) Logging in with a wrong password OR an unknown username both return the **same** generic failure message (no user enumeration).
- **AC-7** (FR-AUTH-04) After a successful login, the session persists across page navigation until logout or expiry.
- **AC-8** (FR-AUTH-05) Logout clears the session; protected pages are no longer accessible afterward.
- **AC-9** (FR-AUTH-06) Accessing any protected page (dashboard, deposit, withdraw, statement, chat) without a session redirects to login.
- **AC-10** (BR-05 / NFR-03) Authentication code never logs the password, hash, phone, or email.

## 5. Edge cases

- Duplicate registration attempts (race) — rely on the UNIQUE constraint; handle the DB error gracefully.
- Whitespace-only fields count as empty.
- Case sensitivity: usernames compared case-insensitively for uniqueness and login (decide and apply consistently).

## 6. Out of scope (this spec)

- Password reset / "forgot password".
- Email or phone verification (OTP).
- Multi-factor auth, account lockout after N failures.
- (These can become future specs if needed.)

## 7. Test notes

- Use a throwaway test database/schema; do not run against demo data.
- Cover each acceptance criterion with at least one test; include the negative cases (AC-2, AC-3, AC-6, AC-9).
- Assert on behaviour and stored state, not on implementation details.
