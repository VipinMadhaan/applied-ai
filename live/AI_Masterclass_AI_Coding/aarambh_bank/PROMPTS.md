# Prompts to build Aarambh Bank in Claude Code

Run these in order, inside the project folder, after `claude` starts.
Wait for each step to finish (tests green) before the next.

---

## 0. Orientation + scaffold
```
Read CLAUDE.md, CODING_STANDARDS.md, docs/BRD.docx, and every file in specs/.
Summarise the golden rules and the build order back to me in a few lines so I know you've understood.
Then create the project structure described in CLAUDE.md (any folders/files that don't exist yet).
Do not implement any feature yet.
```

Then verify the tooling is loaded:
```
/agents
/hooks
```
You should see test-writer, spec-reviewer, security-auditor, and the two hooks.

## 1. Database layer
```
Set up the database layer per the specs: src/db/connection.py (read MySQL config from environment)
and src/db/schema.sql with the users, accounts, and transactions tables exactly as defined in the specs
(money as DECIMAL(15,2), one account per user). Follow CODING_STANDARDS.md. Then create/verify the schema
against the database in my .env.
```

## 2. Auth (use the loop)
```
Build the auth feature from specs/auth.md.
First use the test-writer subagent to write pytest tests for every acceptance criterion.
Then implement auth in src/features/auth.py (and minimal UI wiring) until all tests pass.
Then run the spec-reviewer and security-auditor subagents and fix anything they flag.
```

## 3. Account
```
Build the account feature from specs/account.md using the same loop:
test-writer -> implement -> spec-reviewer -> security-auditor. Don't break auth tests.
```

## 4. Seed some demo data
```
/seed-data 5 6
```

## 5. Dashboard
```
Build the dashboard from specs/dashboard.md using the same loop. It must show name, masked account number,
balance, phone, email, and the last 5 transactions, with navigation to the other features.
```

## 6. Deposit
```
Build the deposit feature from specs/deposit.md using the same loop. Enforce atomic balance + transaction
writes and Decimal money.
```

## 7. Withdraw
```
Build the withdraw feature from specs/withdraw.md using the same loop. Enforce the no-overdraft rule and atomicity.
```

## 8. Statement
```
Build the statement feature from specs/statement.md using the same loop, including CSV download and filters.
```

## 9. Chat assistant
```
Build the GenAI chat assistant from specs/chat.md using the same loop.
Implement src/ai/openai_client.py (conversation memory), src/ai/prompts.py, and src/ai/sql_guard.py.
The assistant must only ever execute a single, user-scoped SELECT validated by sql_guard.
Pay special attention to the security-auditor on AC-5, AC-6, AC-7.
```

## 10. Styling pass (brand design system)
```
Apply the design system from CLAUDE.md across the whole app: solid Green #00E676, Purple #8A5CF6,
Pink #FF2D95, white background, black text. Card-based dashboard; WhatsApp-style chat (user right in green
bubbles, assistant left in white bubbles with a purple border). Make it polished and presentable.
```

## 11. End-to-end check
```
Run the full pytest suite and walk through the end-to-end user journey against success criteria SC-01..SC-07
in docs/BRD.docx. Report anything that fails. Then summarise how each BRD requirement maps to a spec and a passing test.
```
