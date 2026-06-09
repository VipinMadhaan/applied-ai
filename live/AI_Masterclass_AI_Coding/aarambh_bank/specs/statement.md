# Spec: Bank Statement

| | |
|---|---|
| Feature | View and download transaction history |
| Traces to BRD | FR-STMT-01…04 |
| Status | Draft — awaiting approval |
| Depends on | auth, account, transactions |

## 1. Overview
A logged-in user views their transaction history, newest first, with a running balance, can filter by date range and type, and can download the statement as CSV (PDF optional).

## 2. Behaviour
- List transactions for the user's account, newest first, showing date, type, amount, category/note, and running balance.
- Filter by date range (from/to) and by type (credit/debit/all).
- Download the (filtered) statement as CSV; PDF is optional/nice-to-have.
- Only the logged-in user's transactions are ever shown.

## 3. Acceptance Criteria
- **AC-1** (FR-STMT-01) The history lists the user's transactions newest first with a correct running balance.
- **AC-2** (FR-STMT-02) Filtering by date range returns only transactions within that range.
- **AC-3** (FR-STMT-02) Filtering by type returns only matching credits or debits.
- **AC-4** (FR-STMT-03) The user can download the current (filtered) view as a CSV containing the same rows.
- **AC-5** (FR-STMT-04) Only the logged-in user's data is shown; there is no path to another user's transactions.

## 4. Edge cases
- No transactions in range — show an empty statement, not an error.
- from-date after to-date — validate and show a clear message.

## 5. Out of scope
- Scheduled/emailed statements, multi-account statements.
