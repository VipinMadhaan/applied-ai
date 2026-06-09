---
name: seed-data
description: Generate realistic demo data for Aarambh Bank — N users each with M months of categorized transactions — so the dashboard and chat assistant have something to show. Invoke as /seed-data <users> <months> (defaults 5 users, 6 months). Use when setting up a demo or when tests need populated data.
argument-hint: [users] [months]
---
Seed the Aarambh Bank database with demo data.

Arguments: $1 = number of users (default 5), $2 = months of history (default 6).

Procedure:
1. Read CLAUDE.md, CODING_STANDARDS.md, and specs/ for the data model and rules (Decimal money, DECIMAL(15,2), atomic transactions, one account per user).
2. Implement/refresh seed/seed.py (following CODING_STANDARDS.md: snake_case, fun_ prefixed functions, UPPER_CASE constants, docstrings) so it:
   - Creates $1 demo users (with username, email, phone, bcrypt-hashed password) and one account each.
   - For each account, generates $2 months of transactions across realistic categories: food, transport, shopping, bills, entertainment, and a monthly salary CREDIT.
   - Keeps each account's running balance internally consistent and never negative; sets balance_after correctly.
   - Is resettable/idempotent: support clearing existing demo data before re-seeding so re-runs do not corrupt or duplicate.
   - Uses Decimal for all amounts; performs writes within DB transactions.
3. Run the seed script against the configured database and report how many users and transactions were created.

Print a short summary at the end (users created, transactions per account, total rows).
