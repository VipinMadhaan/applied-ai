# Spec: Deposit

| | |
|---|---|
| Feature | Deposit funds into the user's account |
| Traces to BRD | FR-DEP-01…04, BR-03, BR-04 |
| Status | Draft — awaiting approval |
| Depends on | auth, account, `transactions` table |

## 1. Overview
A logged-in user deposits a positive amount. The balance increases and a CREDIT transaction is recorded atomically.

## 2. Data
`transactions` table (shared with withdraw/statement):

| Column | Type | Notes |
|---|---|---|
| id | INT PK AUTO_INCREMENT | |
| account_id | INT, FK -> accounts.id | |
| type | ENUM('CREDIT','DEBIT') | |
| amount | DECIMAL(15,2), NOT NULL | > 0 |
| category | VARCHAR, nullable | for analytics |
| note | VARCHAR, nullable | |
| created_at | DATETIME, default now | |
| balance_after | DECIMAL(15,2), NOT NULL | running balance |

## 3. Behaviour
- User enters an amount (and optional category/note).
- Amount must be > 0.00; otherwise reject with a clear message and make no change.
- On success: balance += amount and a CREDIT row is written, in a single DB transaction.
- `balance_after` records the new balance.
- All money uses Decimal.

## 4. Acceptance Criteria
- **AC-1** (FR-DEP-01) A deposit of a positive amount increases the balance by exactly that amount.
- **AC-2** (FR-DEP-02) A deposit of 0 or a negative amount is rejected; balance and transactions are unchanged.
- **AC-3** (FR-DEP-03) A successful deposit writes exactly one CREDIT transaction with the correct amount and `balance_after`.
- **AC-4** (FR-DEP-03 / BR-04) The balance update and the transaction insert are atomic — a failure leaves neither applied.
- **AC-5** (FR-DEP-04) An optional category and note are stored when provided.
- **AC-6** (money rule) Amounts are handled as Decimal; no float is used anywhere in the path.

## 5. Edge cases
- Non-numeric / blank amount — reject with a clear message.
- Very large amount within DECIMAL(15,2) range — accepted.

## 6. Out of scope
- Deposit limits, holds/clearing, external funding sources.
