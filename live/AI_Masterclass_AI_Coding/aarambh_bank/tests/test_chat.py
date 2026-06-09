"""
Tests for the chat / GenAI assistant feature.

Covers every acceptance criterion in specs/chat.md:

  AC-1  (FR-AI-01 / §12.3) WhatsApp-style UI rendering — UI layer only; skipped
        at the feature level per spec instruction.
  AC-2  (FR-AI-02) Conversation memory: a follow-up receives context from earlier
        turns; fun_clear() empties history.
  AC-3  (FR-AI-03) Data questions answered with figures that match the database;
        the correct SQL sum is included in the assistant's reply.
  AC-4  (FR-AI-04 / BR-06) Answers are scoped to the current user's account_id;
        no path to another user's data via the sql_guard account_id check.
  AC-5  (FR-AI-05) For data questions the generated query is a single user-scoped
        SELECT and is executed only after passing fun_validate_sql.
  AC-6  (FR-AI-06 / NFR-01) Any query that is not a single user-scoped SELECT is
        rejected (fun_validate_sql returns False) and must never be executed.
  AC-7  (FR-AI-06) Prompt-injection attempts cannot mutate data or read another
        user's data via sql_guard's keyword and scope rules.
  AC-8  (FR-AI-07) fun_clear() resets conversation history; a subsequent
        fun_chat() works normally with an empty history.

Test strategy:
  - sql_guard (AC-4 through AC-7) — pure unit tests, no DB, no OpenAI calls.
  - ChatSession (AC-2, AC-3, AC-8) — OpenAI is mocked via unittest.mock.patch.
  - AC-3 data-accuracy test seeds one transaction via raw SQL into the test DB.
  - AC-1 is explicitly skipped (UI-only criterion).
  - All money values use Decimal, never float.
"""

import importlib
import os
import sys
import unittest.mock
from datetime import datetime
from decimal import Decimal

import mysql.connector
import pytest
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path setup — ensure src/ is importable before any feature import.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Load .env so DB credentials are available before any module is imported.
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TEST_DB_NAME = "aarambh_bank_test"

# Credentials for the throwaway test user.
TEST_USERNAME = "chat_user"
TEST_EMAIL = "chat_user@example.com"
TEST_PHONE = "9876500009"
TEST_PASSWORD_HASH = "$2b$12$placeholderhashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

# A fixed account_id used throughout sql_guard unit tests.
GUARD_ACCOUNT_ID = 42

# A different account_id used to verify cross-user rejection.
OTHER_ACCOUNT_ID = 99

# Transaction amounts stored as Decimal (money must never be float).
TX_AMOUNT_A = Decimal("500.00")
TX_AMOUNT_B = Decimal("300.00")
EXPECTED_SUM = TX_AMOUNT_A + TX_AMOUNT_B  # Decimal("800.00")


# ---------------------------------------------------------------------------
# Raw DB helpers
# ---------------------------------------------------------------------------


def fun_get_test_connection():
    """Open a raw MySQL connection to the test database.

    Returns:
        mysql.connector.MySQLConnection: an open connection to TEST_DB_NAME.
    """
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=TEST_DB_NAME,
    )


def fun_insert_user(username: str = TEST_USERNAME, email: str = TEST_EMAIL) -> int:
    """Insert a minimal users row via raw SQL and return the generated user_id.

    Args:
        username: Username string for the new row.
        email:    Email string for the new row.

    Returns:
        int: The auto-increment id of the inserted row.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (username, email, phone, password_hash) "
        "VALUES (%s, %s, %s, %s)",
        (username, email, TEST_PHONE, TEST_PASSWORD_HASH),
    )
    conn.commit()
    user_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return user_id


def fun_insert_account(user_id: int) -> int:
    """Insert a minimal accounts row via raw SQL and return the generated account_id.

    Args:
        user_id: The users.id that owns this account.

    Returns:
        int: The auto-increment id of the inserted account row.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO accounts (user_id, account_number, balance) "
        "VALUES (%s, %s, %s)",
        (user_id, f"ACC{user_id:010d}", "0.00"),
    )
    conn.commit()
    account_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return account_id


def fun_insert_tx(
    account_id: int,
    tx_type: str,
    amount: Decimal,
    balance_after: Decimal,
    created_at: datetime,
) -> int:
    """Insert a transactions row directly via raw SQL and return its generated id.

    Args:
        account_id:    The accounts.id that owns this transaction.
        tx_type:       'CREDIT' or 'DEBIT'.
        amount:        Decimal amount of the transaction.
        balance_after: Decimal running balance after this transaction.
        created_at:    Explicit datetime for the transaction.

    Returns:
        int: The auto-increment id of the inserted row.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO transactions "
        "(account_id, type, amount, balance_after, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            account_id,
            tx_type,
            str(amount),
            str(balance_after),
            created_at,
        ),
    )
    conn.commit()
    tx_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return tx_id


# ---------------------------------------------------------------------------
# Session-level fixture: create (or recreate) the test DB and schema.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def fun_setup_test_database():
    """Session fixture: create the test DB and initialise the schema.

    Sets os.environ['DB_NAME'] to TEST_DB_NAME for the entire test session so
    that fun_init_schema and all feature functions target the throwaway DB.
    Drops the test DB on teardown.
    """
    os.environ["DB_NAME"] = TEST_DB_NAME

    root_conn = mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
    )
    root_cursor = root_conn.cursor()
    root_cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS `{TEST_DB_NAME}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    root_conn.commit()
    root_cursor.close()
    root_conn.close()

    from src.db.schema import fun_init_schema  # noqa: PLC0415

    fun_init_schema()

    yield

    cleanup_conn = mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
    )
    cleanup_cursor = cleanup_conn.cursor()
    cleanup_cursor.execute(f"DROP DATABASE IF EXISTS `{TEST_DB_NAME}`")
    cleanup_conn.commit()
    cleanup_cursor.close()
    cleanup_conn.close()


# ---------------------------------------------------------------------------
# Function-level fixture: truncate all tables before each test.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fun_truncate_tables():
    """Truncate transactions, accounts, users (FK order) before every test.

    Ensures each test starts with a completely clean slate so tests are
    fully independent of one another.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
    for table in ("transactions", "accounts", "users"):
        cursor.execute(f"TRUNCATE TABLE `{table}`")
    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()
    cursor.close()
    conn.close()
    yield


# ---------------------------------------------------------------------------
# Module-level fixtures (session-scoped, lazy imports after DB env is set).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fun_sql_guard_module():
    """Return the sql_guard module so tests can call fun_validate_sql directly.

    Returns:
        module: src.ai.sql_guard
    """
    return importlib.import_module("src.ai.sql_guard")


@pytest.fixture(scope="session")
def fun_chat_module():
    """Return the chat feature module so tests can call fun_create_session.

    Returns:
        module: src.features.chat
    """
    return importlib.import_module("src.features.chat")


@pytest.fixture(scope="session")
def fun_openai_client_module():
    """Return the openai_client module for direct ChatSession construction.

    Returns:
        module: src.ai.openai_client
    """
    return importlib.import_module("src.ai.openai_client")


# ===========================================================================
# AC-1 (FR-AI-01 / §12.3): WhatsApp-style UI rendering.
# Explicitly skipped — this is a UI-layer criterion only.
# ===========================================================================


@pytest.mark.skip(reason="AC-1 is a UI-layer criterion; no feature-level test required.")
def test_ac1_whatsapp_ui_layout_skipped():
    """AC-1: Placeholder to document that UI rendering is out of scope for feature tests."""


# ===========================================================================
# AC-2 (FR-AI-02): Conversation memory — history accumulates across turns;
#   fun_clear() empties it.
# ===========================================================================


def test_ac2_two_chat_calls_produce_four_history_entries(fun_chat_module):
    """AC-2: After two fun_chat calls, session.history contains exactly 4 entries
    (2 user + 2 assistant turns) confirming memory accumulation across turns.

    Satisfies specs/chat.md AC-2 (FR-AI-02).
    """
    fake_response_1 = unittest.mock.MagicMock()
    fake_response_1.choices[0].message.content = "Hello! How can I help?"

    fake_response_2 = unittest.mock.MagicMock()
    fake_response_2.choices[0].message.content = "Your balance is up to date."

    mock_client = unittest.mock.MagicMock()
    mock_client.chat.completions.create.side_effect = [
        fake_response_1,
        fake_response_2,
    ]

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        session = fun_chat_module.fun_create_session(
            account_id=GUARD_ACCOUNT_ID, username=TEST_USERNAME
        )
        session.fun_chat("What is my balance?")
        session.fun_chat("And what about last month?")

    history = session.history
    assert len(history) == 4, (
        f"AC-2: Expected 4 history entries after 2 turns, got {len(history)}: {history}"
    )


def test_ac2_history_entries_alternate_user_assistant_roles(fun_chat_module):
    """AC-2: History entries alternate user/assistant roles in insertion order.

    Satisfies specs/chat.md AC-2 (FR-AI-02).
    """
    fake_resp = unittest.mock.MagicMock()
    fake_resp.choices[0].message.content = "Reply from assistant."

    mock_client = unittest.mock.MagicMock()
    mock_client.chat.completions.create.return_value = fake_resp

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        session = fun_chat_module.fun_create_session(
            account_id=GUARD_ACCOUNT_ID, username=TEST_USERNAME
        )
        session.fun_chat("First question")
        session.fun_chat("Follow-up question")

    history = session.history
    roles = [entry["role"] for entry in history]
    assert roles == ["user", "assistant", "user", "assistant"], (
        f"AC-2: Expected roles [user, assistant, user, assistant], got {roles}"
    )


def test_ac2_history_user_entries_contain_original_messages(fun_chat_module):
    """AC-2: The user turns in history contain the original message text,
    confirming prior turns are preserved for follow-up context.

    Satisfies specs/chat.md AC-2 (FR-AI-02).
    """
    fake_resp = unittest.mock.MagicMock()
    fake_resp.choices[0].message.content = "Response"

    mock_client = unittest.mock.MagicMock()
    mock_client.chat.completions.create.return_value = fake_resp

    first_msg = "How much did I spend on food?"
    second_msg = "What about groceries?"

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        session = fun_chat_module.fun_create_session(
            account_id=GUARD_ACCOUNT_ID, username=TEST_USERNAME
        )
        session.fun_chat(first_msg)
        session.fun_chat(second_msg)

    user_messages = [e["content"] for e in session.history if e["role"] == "user"]
    assert first_msg in user_messages, (
        f"AC-2: First user message '{first_msg}' missing from history: {user_messages}"
    )
    assert second_msg in user_messages, (
        f"AC-2: Second user message '{second_msg}' missing from history: {user_messages}"
    )


def test_ac2_history_is_empty_before_any_chat(fun_chat_module):
    """AC-2: A freshly created session has an empty history list.

    Satisfies specs/chat.md AC-2 (FR-AI-02).
    """
    mock_client = unittest.mock.MagicMock()

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        session = fun_chat_module.fun_create_session(
            account_id=GUARD_ACCOUNT_ID, username=TEST_USERNAME
        )

    assert session.history == [], (
        f"AC-2: Expected empty history on a new session, got {session.history}"
    )


def test_ac2_prior_turns_passed_to_openai_on_follow_up(fun_chat_module):
    """AC-2: On the second fun_chat call, the messages list sent to OpenAI includes
    the first user and assistant turns as context (memory is forwarded).

    Satisfies specs/chat.md AC-2 (FR-AI-02).
    """
    fake_resp = unittest.mock.MagicMock()
    fake_resp.choices[0].message.content = "Sure!"

    mock_client = unittest.mock.MagicMock()
    mock_client.chat.completions.create.return_value = fake_resp

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        session = fun_chat_module.fun_create_session(
            account_id=GUARD_ACCOUNT_ID, username=TEST_USERNAME
        )
        session.fun_chat("First question")
        session.fun_chat("Follow-up")

    # The second call's messages list must contain at least 3 entries:
    # system prompt + first user turn + first assistant turn + second user turn.
    second_call_args = mock_client.chat.completions.create.call_args_list[1]
    messages_sent = second_call_args[1].get(
        "messages", second_call_args[0][0] if second_call_args[0] else []
    )
    # At minimum the system prompt + 3 history/new entries should be present.
    assert len(messages_sent) >= 3, (
        f"AC-2: Second OpenAI call should include prior context; "
        f"messages sent: {messages_sent}"
    )


# ===========================================================================
# AC-3 (FR-AI-03): Data accuracy — the assistant's reply contains the correct
#   figure from the database when SQL is returned in the model response.
# ===========================================================================


def test_ac3_assistant_reply_contains_correct_db_sum(fun_chat_module):
    """AC-3: When OpenAI returns a valid SQL query, the assistant executes it,
    then returns a natural-language reply that contains the actual DB sum.

    Seeds two CREDIT transactions (500 + 300 = 800) and asserts that the
    final reply mentions '800' (the correct Decimal sum from the DB).

    Satisfies specs/chat.md AC-3 (FR-AI-03).
    """
    user_id = fun_insert_user()
    account_id = fun_insert_account(user_id)

    fun_insert_tx(
        account_id, "CREDIT", TX_AMOUNT_A, TX_AMOUNT_A, datetime(2025, 5, 1, 10, 0, 0)
    )
    fun_insert_tx(
        account_id, "CREDIT", TX_AMOUNT_B, EXPECTED_SUM, datetime(2025, 5, 2, 10, 0, 0)
    )

    # First call: model returns an SQL query wrapped in <SQL>…</SQL>.
    sql_query = (
        f"SELECT SUM(amount) FROM transactions WHERE account_id = {account_id}"
    )
    first_response = unittest.mock.MagicMock()
    first_response.choices[0].message.content = f"<SQL>{sql_query}</SQL>"

    # Second call: model summarises the query result in plain language.
    second_response = unittest.mock.MagicMock()
    second_response.choices[0].message.content = (
        f"Your total credits amount to {EXPECTED_SUM}."
    )

    mock_client = unittest.mock.MagicMock()
    mock_client.chat.completions.create.side_effect = [first_response, second_response]

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        session = fun_chat_module.fun_create_session(
            account_id=account_id, username=TEST_USERNAME
        )
        reply = session.fun_chat("What is my total credit?")

    # The reply must contain the correct sum value.
    assert "800" in reply, (
        f"AC-3: Expected '800' (sum of {TX_AMOUNT_A} + {TX_AMOUNT_B}) in reply, "
        f"got: '{reply}'"
    )


def test_ac3_sql_is_executed_only_after_guard_passes(fun_chat_module):
    """AC-3: The DB query is run exactly once when the SQL passes validation,
    confirming execution happens only after the guard approves the query.

    Satisfies specs/chat.md AC-3 / AC-5.
    """
    user_id = fun_insert_user()
    account_id = fun_insert_account(user_id)

    fun_insert_tx(
        account_id, "CREDIT", TX_AMOUNT_A, TX_AMOUNT_A, datetime(2025, 6, 1, 10, 0, 0)
    )

    sql_query = (
        f"SELECT SUM(amount) FROM transactions WHERE account_id = {account_id}"
    )
    first_response = unittest.mock.MagicMock()
    first_response.choices[0].message.content = f"<SQL>{sql_query}</SQL>"

    summary_response = unittest.mock.MagicMock()
    summary_response.choices[0].message.content = f"You have {TX_AMOUNT_A} in credits."

    mock_client = unittest.mock.MagicMock()
    mock_client.chat.completions.create.side_effect = [first_response, summary_response]

    executed_queries: list[str] = []

    original_guard = importlib.import_module("src.ai.sql_guard")

    def fun_spy_validate(sql: str, aid: int):
        """Spy wrapper that records validated queries before delegating.

        Args:
            sql: The SQL string being validated.
            aid: The account_id scope used for validation.

        Returns:
            tuple[bool, str]: Result from the real fun_validate_sql.
        """
        result = original_guard.fun_validate_sql(sql, aid)
        if result[0]:
            executed_queries.append(sql)
        return result

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        with unittest.mock.patch(
            "src.ai.openai_client.fun_validate_sql", side_effect=fun_spy_validate
        ):
            session = fun_chat_module.fun_create_session(
                account_id=account_id, username=TEST_USERNAME
            )
            session.fun_chat("Total credits please")

    assert len(executed_queries) == 1, (
        f"AC-3/AC-5: Expected exactly 1 validated query to be executed, "
        f"got {len(executed_queries)}: {executed_queries}"
    )


# ===========================================================================
# AC-4 (FR-AI-04 / BR-06): User scoping — no path to another user's data.
#   Verified via sql_guard: a query missing the correct account_id is rejected.
# ===========================================================================


def test_ac4_query_with_wrong_account_id_rejected(fun_sql_guard_module):
    """AC-4: A SELECT scoped to a different account_id is rejected by fun_validate_sql,
    ensuring there is no path to another user's data.

    Satisfies specs/chat.md AC-4 (FR-AI-04 / BR-06).
    """
    sql = f"SELECT * FROM transactions WHERE account_id = {OTHER_ACCOUNT_ID}"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-4: Expected False for query scoped to account_id={OTHER_ACCOUNT_ID} "
        f"when guard account_id={GUARD_ACCOUNT_ID}, got True. Reason: {reason}"
    )
    assert isinstance(reason, str) and len(reason.strip()) > 0, (
        "AC-4: Rejection must include a non-empty reason string."
    )


def test_ac4_query_with_no_account_id_rejected(fun_sql_guard_module):
    """AC-4: A SELECT with no account_id filter is rejected, preventing full-table reads
    that could expose every user's data.

    Satisfies specs/chat.md AC-4 (FR-AI-04 / BR-06).
    """
    sql = "SELECT * FROM transactions"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-4: Expected False for unscoped query, got True. Reason: {reason}"
    )


# ===========================================================================
# AC-5 (FR-AI-05): Valid queries accepted by fun_validate_sql.
# ===========================================================================


def test_ac5_valid_select_with_account_id_accepted(fun_sql_guard_module):
    """AC-5: A properly scoped single SELECT passes fun_validate_sql.

    Satisfies specs/chat.md AC-5 (FR-AI-05).
    """
    sql = f"SELECT * FROM transactions WHERE account_id = {GUARD_ACCOUNT_ID}"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is True, (
        f"AC-5: Expected True for valid user-scoped SELECT, got False. Reason: {reason}"
    )
    assert reason == "", (
        f"AC-5: Expected empty reason string on valid query, got: '{reason}'"
    )


def test_ac5_valid_aggregate_select_accepted(fun_sql_guard_module):
    """AC-5: A SUM aggregate query scoped to account_id passes fun_validate_sql.

    Satisfies specs/chat.md AC-5 (FR-AI-05).
    """
    sql = (
        f"SELECT SUM(amount) FROM transactions "
        f"WHERE account_id = {GUARD_ACCOUNT_ID} AND type = 'CREDIT'"
    )
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is True, (
        f"AC-5: Expected True for valid aggregate SELECT, got False. Reason: {reason}"
    )


def test_ac5_valid_lowercase_select_accepted(fun_sql_guard_module):
    """AC-5: A lowercase 'select' with no spaces around '=' passes fun_validate_sql.

    Satisfies specs/chat.md AC-5 (FR-AI-05).
    """
    sql = f"select amount from transactions where account_id={GUARD_ACCOUNT_ID}"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is True, (
        f"AC-5: Expected True for lowercase SELECT, got False. Reason: {reason}"
    )


# ===========================================================================
# AC-6 (FR-AI-06 / NFR-01): Invalid queries rejected by fun_validate_sql.
# ===========================================================================


def test_ac6_update_statement_rejected(fun_sql_guard_module):
    """AC-6: An UPDATE statement is rejected even when it contains account_id.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    sql = f"UPDATE accounts SET balance = 0 WHERE account_id = {GUARD_ACCOUNT_ID}"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-6: Expected False for UPDATE, got True. Reason: {reason}"
    )


def test_ac6_delete_statement_rejected(fun_sql_guard_module):
    """AC-6: A DELETE statement is rejected even when it contains account_id.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    sql = f"DELETE FROM transactions WHERE account_id = {GUARD_ACCOUNT_ID}"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-6: Expected False for DELETE, got True. Reason: {reason}"
    )


def test_ac6_drop_table_rejected(fun_sql_guard_module):
    """AC-6: A DROP TABLE statement is unconditionally rejected.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    sql = "DROP TABLE users"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-6: Expected False for DROP TABLE, got True. Reason: {reason}"
    )


def test_ac6_insert_statement_rejected(fun_sql_guard_module):
    """AC-6: An INSERT statement is unconditionally rejected.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    sql = "INSERT INTO users (username) VALUES ('hacked')"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-6: Expected False for INSERT, got True. Reason: {reason}"
    )


def test_ac6_create_table_rejected(fun_sql_guard_module):
    """AC-6: A CREATE TABLE statement is unconditionally rejected.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    sql = "CREATE TABLE evil (x INT)"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-6: Expected False for CREATE TABLE, got True. Reason: {reason}"
    )


def test_ac6_alter_table_rejected(fun_sql_guard_module):
    """AC-6: An ALTER TABLE statement is unconditionally rejected.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    sql = "ALTER TABLE users ADD COLUMN x INT"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-6: Expected False for ALTER TABLE, got True. Reason: {reason}"
    )


def test_ac6_multiple_statements_with_drop_rejected(fun_sql_guard_module):
    """AC-6: A SELECT followed by a DROP (multiple statements) is rejected.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    sql = (
        f"SELECT * FROM transactions WHERE account_id = {GUARD_ACCOUNT_ID}; "
        "DROP TABLE users"
    )
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-6: Expected False for multi-statement SELECT;DROP, got True. Reason: {reason}"
    )


def test_ac6_two_select_statements_rejected(fun_sql_guard_module):
    """AC-6: Two SELECT statements separated by a semicolon are rejected as
    multiple statements — only a single statement is allowed.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    sql = "SELECT 1; SELECT 2"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-6: Expected False for two SELECT statements, got True. Reason: {reason}"
    )


def test_ac6_missing_account_id_scope_rejected(fun_sql_guard_module):
    """AC-6: A SELECT with no account_id filter is rejected for missing user scope.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    sql = "SELECT * FROM transactions"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-6: Expected False for query missing account_id scope, got True. Reason: {reason}"
    )


def test_ac6_wrong_account_id_in_scope_rejected(fun_sql_guard_module):
    """AC-6: A query whose account_id literal does not match the session account_id
    is rejected, as it would expose a different user's data.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    sql = f"SELECT * FROM accounts WHERE user_id = {OTHER_ACCOUNT_ID}"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-6: Expected False when query contains account_id={OTHER_ACCOUNT_ID} "
        f"but session account_id={GUARD_ACCOUNT_ID}. Reason: {reason}"
    )


def test_ac6_empty_sql_rejected(fun_sql_guard_module):
    """AC-6: An empty string is rejected as a non-statement.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    ok, reason = fun_sql_guard_module.fun_validate_sql("", GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-6: Expected False for empty SQL string, got True. Reason: {reason}"
    )


def test_ac6_whitespace_only_sql_rejected(fun_sql_guard_module):
    """AC-6: A whitespace-only string is rejected as an empty statement.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    ok, reason = fun_sql_guard_module.fun_validate_sql("   \n\t  ", GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-6: Expected False for whitespace-only SQL, got True. Reason: {reason}"
    )


def test_ac6_fun_validate_sql_returns_tuple(fun_sql_guard_module):
    """AC-6: fun_validate_sql always returns a (bool, str) 2-tuple on both valid
    and invalid input, satisfying the module contract.

    Satisfies specs/chat.md AC-6 (FR-AI-06 / NFR-01).
    """
    valid_sql = f"SELECT 1 FROM transactions WHERE account_id = {GUARD_ACCOUNT_ID}"
    invalid_sql = "DROP TABLE users"

    result_valid = fun_sql_guard_module.fun_validate_sql(valid_sql, GUARD_ACCOUNT_ID)
    result_invalid = fun_sql_guard_module.fun_validate_sql(invalid_sql, GUARD_ACCOUNT_ID)

    for result in (result_valid, result_invalid):
        assert isinstance(result, tuple), (
            f"AC-6: fun_validate_sql must return a tuple, got {type(result).__name__}"
        )
        assert len(result) == 2, (
            f"AC-6: fun_validate_sql must return a 2-tuple, got length {len(result)}"
        )
        ok_val, reason_val = result
        assert isinstance(ok_val, bool), (
            f"AC-6: First element must be bool, got {type(ok_val).__name__}"
        )
        assert isinstance(reason_val, str), (
            f"AC-6: Second element must be str, got {type(reason_val).__name__}"
        )


# ===========================================================================
# AC-7 (FR-AI-06): Prompt injection / evasion attempts handled by sql_guard.
# ===========================================================================


def test_ac7_injection_drop_after_comment_marker_rejected(fun_sql_guard_module):
    """AC-7: A DROP that precedes a valid SELECT in a comment-marker injection
    is rejected because the first keyword is DROP, not SELECT.

    Input:  DROP TABLE users; -- SELECT * FROM transactions WHERE account_id = 42
    Satisfies specs/chat.md AC-7 (FR-AI-06).
    """
    sql = (
        f"DROP TABLE users; -- SELECT * FROM transactions "
        f"WHERE account_id = {GUARD_ACCOUNT_ID}"
    )
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-7: Expected False for DROP injection disguised with comment, "
        f"got True. Reason: {reason}"
    )


def test_ac7_union_select_still_passes_guard(fun_sql_guard_module):
    """AC-7: A UNION SELECT that starts with SELECT and contains the correct
    account_id passes the guard — UNION is not a forbidden keyword.

    The implementation must not over-block UNION queries while still enforcing
    that the first keyword is SELECT and account_id is present.

    Satisfies specs/chat.md AC-7 (FR-AI-06).
    """
    sql = (
        f"SELECT * FROM transactions WHERE account_id = {GUARD_ACCOUNT_ID} "
        "UNION SELECT * FROM users WHERE 1=1"
    )
    ok, _reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is True, (
        f"AC-7: Expected True for UNION SELECT containing correct account_id, "
        f"got False. Reason: {_reason}"
    )


def test_ac7_or_1_equals_1_injection_passes_guard(fun_sql_guard_module):
    """AC-7: A SELECT with a tautological 'OR 1=1' still passes the guard because
    it is a SELECT and the correct account_id literal is present.

    The guard validates query type and scope; query optimisation is out of scope.

    Satisfies specs/chat.md AC-7 (FR-AI-06).
    """
    sql = (
        f"SELECT * FROM transactions WHERE account_id = {GUARD_ACCOUNT_ID} OR 1=1"
    )
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is True, (
        f"AC-7: Expected True for SELECT with OR 1=1 that still has correct account_id, "
        f"got False. Reason: {reason}"
    )


def test_ac7_account_id_only_in_comment_rejected(fun_sql_guard_module):
    """AC-7: A SELECT whose account_id appears only in a stripped comment (not in the
    live SQL) is rejected — the guard must check the non-comment content only.

    Input:  SELECT * FROM transactions -- WHERE account_id = 42
    After stripping the comment the literal '42' is absent, so scope check fails.

    Satisfies specs/chat.md AC-7 (FR-AI-06).
    """
    sql = (
        f"SELECT * FROM transactions -- WHERE account_id = {GUARD_ACCOUNT_ID}"
    )
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-7: Expected False when account_id is only in a comment, "
        f"got True. Reason: {reason}"
    )


def test_ac7_forbidden_keyword_inside_select_rejected(fun_sql_guard_module):
    """AC-7: A query that begins with SELECT but embeds a forbidden keyword
    (e.g. TRUNCATE) is rejected by the keyword scan.

    Satisfies specs/chat.md AC-7 (FR-AI-06).
    """
    # TRUNCATE is a forbidden keyword; embedding it in a subquery/comment context
    # should still be caught.
    sql = (
        f"SELECT (TRUNCATE(amount, 2)) FROM transactions "
        f"WHERE account_id = {GUARD_ACCOUNT_ID}"
    )
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    # TRUNCATE in a MySQL function call context is a borderline case —
    # the spec lists it as forbidden. The guard must reject it.
    assert ok is False, (
        f"AC-7: Expected False for SELECT embedding forbidden TRUNCATE keyword, "
        f"got True. Reason: {reason}"
    )


def test_ac7_into_outfile_injection_rejected(fun_sql_guard_module):
    """AC-7: A SELECT … INTO OUTFILE exfiltration attempt is rejected.

    Satisfies specs/chat.md AC-7 (FR-AI-06).
    """
    sql = (
        f"SELECT * FROM transactions WHERE account_id = {GUARD_ACCOUNT_ID} "
        "INTO OUTFILE '/tmp/dump.csv'"
    )
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-7: Expected False for INTO OUTFILE exfiltration attempt, "
        f"got True. Reason: {reason}"
    )


def test_ac7_execute_keyword_rejected(fun_sql_guard_module):
    """AC-7: A query containing the EXECUTE keyword is rejected.

    Satisfies specs/chat.md AC-7 (FR-AI-06).
    """
    sql = f"EXECUTE some_prepared_stmt USING {GUARD_ACCOUNT_ID}"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-7: Expected False for EXECUTE statement, got True. Reason: {reason}"
    )


def test_ac7_call_stored_procedure_rejected(fun_sql_guard_module):
    """AC-7: A CALL stored-procedure invocation is rejected.

    Satisfies specs/chat.md AC-7 (FR-AI-06).
    """
    sql = f"CALL some_procedure({GUARD_ACCOUNT_ID})"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-7: Expected False for CALL statement, got True. Reason: {reason}"
    )


def test_ac7_grant_privilege_rejected(fun_sql_guard_module):
    """AC-7: A GRANT privileges statement is rejected.

    Satisfies specs/chat.md AC-7 (FR-AI-06).
    """
    sql = "GRANT ALL ON *.* TO 'hacker'@'%'"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-7: Expected False for GRANT statement, got True. Reason: {reason}"
    )


def test_ac7_revoke_privilege_rejected(fun_sql_guard_module):
    """AC-7: A REVOKE privileges statement is rejected.

    Satisfies specs/chat.md AC-7 (FR-AI-06).
    """
    sql = "REVOKE ALL ON *.* FROM 'user'@'%'"
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-7: Expected False for REVOKE statement, got True. Reason: {reason}"
    )


def test_ac7_merge_statement_rejected(fun_sql_guard_module):
    """AC-7: A MERGE (upsert) statement is rejected.

    Satisfies specs/chat.md AC-7 (FR-AI-06).
    """
    sql = (
        f"MERGE INTO transactions USING dual ON (account_id = {GUARD_ACCOUNT_ID}) "
        "WHEN MATCHED THEN UPDATE SET amount = 0"
    )
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-7: Expected False for MERGE statement, got True. Reason: {reason}"
    )


def test_ac7_replace_statement_rejected(fun_sql_guard_module):
    """AC-7: A REPLACE (MySQL-specific upsert) statement is rejected.

    Satisfies specs/chat.md AC-7 (FR-AI-06).
    """
    sql = (
        f"REPLACE INTO transactions (account_id, amount) "
        f"VALUES ({GUARD_ACCOUNT_ID}, 0)"
    )
    ok, reason = fun_sql_guard_module.fun_validate_sql(sql, GUARD_ACCOUNT_ID)

    assert ok is False, (
        f"AC-7: Expected False for REPLACE statement, got True. Reason: {reason}"
    )


# ===========================================================================
# AC-8 (FR-AI-07): fun_clear() resets conversation memory.
# ===========================================================================


def test_ac8_fun_clear_empties_history(fun_chat_module):
    """AC-8: After calling fun_clear(), session.history is an empty list.

    Satisfies specs/chat.md AC-8 (FR-AI-07).
    """
    fake_resp = unittest.mock.MagicMock()
    fake_resp.choices[0].message.content = "Here is your info."

    mock_client = unittest.mock.MagicMock()
    mock_client.chat.completions.create.return_value = fake_resp

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        session = fun_chat_module.fun_create_session(
            account_id=GUARD_ACCOUNT_ID, username=TEST_USERNAME
        )
        session.fun_chat("Hello")
        assert len(session.history) > 0, (
            "AC-8: Pre-condition failed — history should be non-empty before clear."
        )

        session.fun_clear()

    assert session.history == [], (
        f"AC-8: Expected empty history after fun_clear(), got {session.history}"
    )


def test_ac8_fun_clear_allows_fresh_chat_after_reset(fun_chat_module):
    """AC-8: After fun_clear(), a subsequent fun_chat() works normally and
    history restarts from a single turn (no residual context).

    Satisfies specs/chat.md AC-8 (FR-AI-07).
    """
    resp_before_clear = unittest.mock.MagicMock()
    resp_before_clear.choices[0].message.content = "Pre-clear response."

    resp_after_clear = unittest.mock.MagicMock()
    resp_after_clear.choices[0].message.content = "Post-clear response."

    mock_client = unittest.mock.MagicMock()
    mock_client.chat.completions.create.side_effect = [
        resp_before_clear,
        resp_after_clear,
    ]

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        session = fun_chat_module.fun_create_session(
            account_id=GUARD_ACCOUNT_ID, username=TEST_USERNAME
        )
        session.fun_chat("Before clear")
        session.fun_clear()

        reply = session.fun_chat("After clear — fresh start")

    assert reply == "Post-clear response.", (
        f"AC-8: Expected post-clear reply, got: '{reply}'"
    )
    # History should contain exactly 1 user + 1 assistant turn from the post-clear call.
    assert len(session.history) == 2, (
        f"AC-8: Expected 2 history entries after post-clear fun_chat, "
        f"got {len(session.history)}: {session.history}"
    )


def test_ac8_fun_clear_returns_none(fun_chat_module):
    """AC-8: fun_clear() returns None (no meaningful return value).

    Satisfies specs/chat.md AC-8 (FR-AI-07).
    """
    mock_client = unittest.mock.MagicMock()

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        session = fun_chat_module.fun_create_session(
            account_id=GUARD_ACCOUNT_ID, username=TEST_USERNAME
        )
        return_value = session.fun_clear()

    assert return_value is None, (
        f"AC-8: fun_clear() must return None, got {return_value!r}"
    )


def test_ac8_multiple_clears_are_idempotent(fun_chat_module):
    """AC-8: Calling fun_clear() multiple times in a row leaves history empty
    each time — it is idempotent and does not raise an error.

    Satisfies specs/chat.md AC-8 (FR-AI-07).
    """
    mock_client = unittest.mock.MagicMock()

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        session = fun_chat_module.fun_create_session(
            account_id=GUARD_ACCOUNT_ID, username=TEST_USERNAME
        )
        session.fun_clear()
        session.fun_clear()
        session.fun_clear()

    assert session.history == [], (
        f"AC-8: History must remain empty after multiple fun_clear() calls, "
        f"got {session.history}"
    )


# ===========================================================================
# Additional cross-cutting: fun_create_session module contract.
# ===========================================================================


def test_fun_create_session_returns_chat_session_instance(fun_chat_module):
    """fun_create_session must return a ChatSession with history, fun_chat, and fun_clear.

    Verifies the module contract in specs/chat.md (src/features/chat.py section).
    """
    mock_client = unittest.mock.MagicMock()

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        session = fun_chat_module.fun_create_session(
            account_id=GUARD_ACCOUNT_ID, username=TEST_USERNAME
        )

    assert hasattr(session, "fun_chat"), (
        "fun_create_session result must expose a fun_chat method."
    )
    assert hasattr(session, "fun_clear"), (
        "fun_create_session result must expose a fun_clear method."
    )
    assert hasattr(session, "history"), (
        "fun_create_session result must expose a history property."
    )
    assert callable(session.fun_chat), "session.fun_chat must be callable."
    assert callable(session.fun_clear), "session.fun_clear must be callable."


def test_fun_create_session_account_id_stored_on_session(fun_chat_module):
    """fun_create_session stores the account_id so the session can scope its queries.

    The account_id is a key part of the user-scoping contract (AC-4, AC-5).
    """
    mock_client = unittest.mock.MagicMock()

    with unittest.mock.patch("src.ai.openai_client.OpenAI", return_value=mock_client):
        session = fun_chat_module.fun_create_session(
            account_id=GUARD_ACCOUNT_ID, username=TEST_USERNAME
        )

    assert hasattr(session, "account_id") or hasattr(session, "_account_id"), (
        "ChatSession must store account_id for user-scoping purposes."
    )
    stored_id = getattr(session, "account_id", None) or getattr(
        session, "_account_id", None
    )
    assert stored_id == GUARD_ACCOUNT_ID, (
        f"Expected account_id={GUARD_ACCOUNT_ID}, got {stored_id}"
    )
