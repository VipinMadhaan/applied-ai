# CLAUDE.md — Aarambh Bank

> Project constitution. Read this every session before doing anything.
> This is a **spec-driven** project: **never write or change application code without an approved spec in `specs/`.**

## What this is

Aarambh Bank is a single-currency (INR) retail banking **demo / teaching app**: register, login, account summary dashboard, deposit, withdraw, bank statement, and a WhatsApp-style GenAI chat assistant with memory that answers questions about the user's own spending. It is also the flagship project for demonstrating the full Claude Code stack. The full business requirements are in **`docs/BRD.docx`** (Word document) — read it for any requirement detail or ID.

## Golden rules (non-negotiable)

1. **No code without a spec.** Every feature has a spec in `specs/<feature>.md` with numbered acceptance criteria. Code is written to satisfy a spec, nothing more.
2. **Money is `Decimal`, never `float`.** All amounts use Python `Decimal`; DB columns are `DECIMAL(15,2)`. Any `float` in money handling is a bug.
3. **Balance changes are atomic.** Updating a balance and writing its transaction row happen in a single DB transaction. Partial updates must be impossible.
4. **Secrets only via environment variables.** Never hardcode or log the OpenAI API key, DB password, or any secret.
5. **Never log PII.** Full account numbers, phone numbers, emails, and passwords are never written to logs. Account numbers are masked except the last 4 digits in the UI.
6. **The AI layer is read-only and user-scoped.** The chat assistant may only run a **single `SELECT`** scoped to the current user. Validate every LLM-generated query before executing it; reject anything that is not a single user-scoped `SELECT`. (Demo uses one `root` DB user, so this guard lives in code.)
7. **A user only ever touches their own data.** Enforce user scoping on every account, transaction, and chat query.

## Tech stack

- Python 3.x
- Streamlit (frontend, custom-styled to the design system below)
- MySQL (local), single `root` user for this demo
- bcrypt for password hashing; Streamlit `session_state` for sessions
- OpenAI API for the chat assistant (conversation memory + guarded text-to-SQL)
- pytest for unit + integration tests

## Project structure

> If any folder or file below does not exist yet, **create it as you implement, following this layout.**

```
aarambh-bank/
├── CLAUDE.md                # this file
├── CODING_STANDARDS.md      # naming + docstring rules (MUST follow)
├── docs/BRD.docx            # business requirements (source of truth, Word doc)
├── specs/                   # one spec per feature (auth, account, dashboard, ...)
├── src/
│   ├── db/                  # connection, schema, migrations
│   ├── features/            # auth.py, account.py, dashboard.py, deposit.py, withdraw.py, statement.py, chat.py
│   ├── ui/                  # streamlit pages + shared components/styles
│   └── ai/                  # OpenAI client, prompt building, SQL guard
├── tests/                   # pytest, mirrors src/features
├── seed/                    # demo data seeding logic
└── .claude/                 # agents, skills, hooks, settings
```

## Commands

- Run app: `streamlit run src/ui/app.py`
- Run tests: `pytest -q`
- Lint/format: `ruff check . && ruff format .`
- Seed demo data: invoke the `seed-data` skill — `/seed-data <users> <months>`

## Conventions

- **All code follows `CODING_STANDARDS.md`:** variables in `snake_case`, function names prefixed with `fun_`, constants in `UPPER_CASE`, and a docstring in every function.
- Organize code by feature; one module per feature under `src/features/`.
- Business logic is separate from Streamlit UI (UI calls feature functions; no SQL in UI files).
- Every public function has a docstring stating which spec / acceptance criteria it satisfies.
- Errors shown to the user are clear and jargon-free; internal errors are logged without PII.

## Design system (the UI must follow this)

- **Solid colours only, no gradients.** Green `#00E676`, Purple `#8A5CF6`, Pink `#FF2D95`.
- **White background. Black text everywhere** (labels, values, chat text).
- Green = positive/credits, success, primary action buttons, **user chat bubbles**.
- Purple = brand surfaces: sidebar, headers, section titles, nav highlights.
- Pink = accents: badges, active states, secondary highlights.
- Dashboard uses card-based summary tiles with rounded corners.
- Chat: assistant messages left in white bubbles with a purple border; user messages right in solid green bubbles; black text; input box + send at the bottom; "Clear chat" resets memory.
- Goal: polished, presentable, deployment-ready.

## Workflow (how we work each feature)

1. Confirm the spec in `specs/<feature>.md` is approved.
2. Use the **test-writer** subagent to turn its acceptance criteria into `pytest` tests.
3. Implement against the spec until tests pass.
4. Run the **spec-reviewer** subagent (implementation vs spec) and the **security-auditor** subagent (rules 2–6 above + CODING_STANDARDS.md).
5. Move to the next feature. Build order: auth → account → dashboard → deposit → withdraw → statement → chat.

## Definition of done (per feature)

- All acceptance criteria in the spec are met.
- Tests written from those criteria pass.
- spec-reviewer and security-auditor pass.
- No `float` in money paths, no secrets/PII in code or logs, AI queries guarded, CODING_STANDARDS.md followed.
