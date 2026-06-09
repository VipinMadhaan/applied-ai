# Spec: Withdraw

| | |
|---|---|
| Feature | Withdraw funds from the user's account |
| Traces to BRD | FR-WD-01…04, BR-02, BR-03, BR-04 |
| Status | Draft — awaiting approval |
| Depends on | auth, account, `transactions` table |

## 1. Overview
A logged-in user withdraws a positive amount, provided sufficient balance. No overdraft. Balance decreases and a DEBIT transaction is recorded atomically.

## 2. Behaviour
- User enters an amount (and optional category/note).
- Amount must be > 0.00; otherwise reject and make no change.
- If amount > current balance, reject ("Insufficient balance"); make no change.
- On success: balance -= amount and a DEBIT row is written, in a single DB transaction.
- All money uses Decimal.

## 3. Acceptance Criteria
- **AC-1** (FR-WD-01) A withdrawal of a positive amount ≤ balance decreases the balance by exactly that amount.
- **AC-2** (FR-WD-02 / BR-02) A withdrawal greater than the current balance is rejected; balance and transactions are unchanged; balance never goes below 0.00.
- **AC-3** (FR-WD-01) A withdrawal of 0 or a negative amount is rejected; no change.
- **AC-4** (FR-WD-03) A successful withdrawal writes exactly one DEBIT transaction with the correct amount and `balance_after`.
- **AC-5** (FR-WD-04 / BR-04) The balance update and the transaction insert are atomic — a failure leaves neither applied.
- **AC-6** (money rule) Amounts are handled as Decimal; no float is used anywhere in the path.

## 4. Edge cases
- Withdraw exactly equal to balance — allowed, resulting balance 0.00.
- Concurrent withdrawals — the atomic transaction must prevent overdraft.

## 5. Out of scope
- Overdraft facilities, daily limits, fees.
