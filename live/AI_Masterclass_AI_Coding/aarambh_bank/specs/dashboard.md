# Spec: Login Dashboard / Account Summary

| | |
|---|---|
| Feature | Summary dashboard shown after login |
| Traces to BRD | FR-DASH-01…05, FR-ACC-04, NFR-03 |
| Status | Draft — awaiting approval |
| Depends on | auth, account, transactions |

## 1. Overview
Immediately after login the user sees a summary dashboard: their name, masked account number, current balance, phone, and email, plus their most recent transactions and quick navigation to the other features.

## 2. Behaviour
- Render after successful login (landing page for an authenticated user).
- Show: account holder name, masked account number (last 4 only), current balance, registered phone, email.
- Show the most recent transactions (last 5) with type, amount, date.
- Provide quick actions / nav to Deposit, Withdraw, Statement, Chat Assistant.
- All figures are live and reflect the latest state after any deposit/withdraw.
- If the user has no account yet, prompt them to open one (see account spec).

## 3. Acceptance Criteria
- **AC-1** (FR-DASH-01) After login the dashboard is the first screen shown.
- **AC-2** (FR-DASH-02) Dashboard shows name, masked account number, current balance, phone, and email for the logged-in user.
- **AC-3** (FR-DASH-03) Dashboard lists the last 5 transactions (type, amount, date), newest first.
- **AC-4** (FR-DASH-04) Dashboard offers navigation to Deposit, Withdraw, Statement, and Chat Assistant.
- **AC-5** (FR-DASH-05) After a deposit or withdrawal, the displayed balance and recent transactions update to reflect it.
- **AC-6** (FR-ACC-04 / NFR-03) The full account number is never shown or logged; only the last 4 digits appear.

## 4. Edge cases
- New user with an account but zero transactions — show an empty-state message, not an error.

## 5. Out of scope
- Charts/analytics on the dashboard (the chat assistant covers analysis).
