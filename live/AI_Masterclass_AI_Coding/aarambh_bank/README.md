# Aarambh Bank — GenAI Banking Application (Demo / Training Build)

A spec-driven banking demo built with Claude Code: register, login, account summary dashboard,
deposit, withdraw, bank statement, and a WhatsApp-style GenAI chat assistant with memory.
Frontend in Streamlit, MySQL database, OpenAI for the chat assistant.

## What's in this repo (the bootstrap)
- `CLAUDE.md` — project constitution (read every session).
- `CODING_STANDARDS.md` — naming + docstring rules.
- `docs/BRD.docx` — full business requirements (source of truth).
- `specs/` — one spec per feature, each with numbered acceptance criteria.
- `.claude/` — subagents (test-writer, spec-reviewer, security-auditor), the `seed-data` skill, hooks, and settings.
- `src/`, `tests/`, `seed/` — Claude Code fills these in as you build.

## Prerequisites
- Python 3.x
- MySQL running locally, with a database you can use (default name `aarambh_bank`)
- An OpenAI API key
- Claude Code installed

## Setup
1. Create and activate a virtual environment, then install deps:
   ```
   python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in your values (OpenAI key + MySQL creds). Never commit `.env`.
3. Create the database:
   ```
   mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS aarambh_bank;"
   ```

## Hooks note
The hooks in `.claude/hooks/` are bash scripts. Make sure they are executable:
```
chmod +x .claude/hooks/*.sh
```
On Windows, run Claude Code from WSL or Git Bash so the hooks can execute.

## Build it
Open Claude Code in this folder (`claude`) and follow the prompts in `PROMPTS.md`, in order.
Verify the tooling loaded with `/agents` (3 subagents) and `/hooks` (2 hooks).

## Run it
```
streamlit run src/ui/app.py
```

## Seed demo data
In Claude Code: `/seed-data 5 6`  (5 users, 6 months of history)
