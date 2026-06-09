# Spec: Account Creation

| | |
|---|---|
| Feature | Open a bank account for a logged-in user |
| Traces to BRD | FR-ACC-01…04, BR-01 |
| Status | Draft — awaiting approval |
| Depends on | auth (logged-in session), `users` table |

## 1. Overview
A logged-in user can open exactly one bank account. Each account has a unique account number and starts at a 0.00 balance. A user cannot create a second account.

## 2. Data
`accounts` table:

| Column | Type | Notes |
|---|---|---|
| id | INT PK AUTO_INCREMENT | |
| user_id | INT, FK -> users.id, UNIQUE | one account per user |
| account_number | VARCHAR, UNIQUE, NOT NULL | system-generated |
| balance | DECIMAL(15,2), NOT NULL, default 0.00 | |
| created_at | DATETIME, default now | |

## 3. Behaviour
- On first login (or via "Open Account"), if the user has no account, one is created.
- account_number is generated unique (e.g. zero-padded sequence or random unique string).
- Opening balance is 0.00.
- If the user already has an account, "Open Account" is unavailable / rejected.
- In the UI the account number is masked except the last 4 digits.

## 4. Acceptance Criteria
- **AC-1** (FR-ACC-01) A user with no account can create one; exactly one `accounts` row is created for that user.
- **AC-2** (FR-ACC-02) A new account has a unique `account_number` and `balance` = 0.00.
- **AC-3** (FR-ACC-03) A user who already has an account cannot create a second; no extra row is created (enforced by the UNIQUE constraint and in code).
- **AC-4** (FR-ACC-04) The account number is displayed masked except the last 4 digits and is never written to logs.

## 5. Edge cases
- Concurrent open attempts — rely on UNIQUE(user_id); handle the DB error gracefully.
- account_number collision — regenerate on unique-constraint violation.

## 6. Out of scope
- Closing accounts, multiple accounts, account types.
