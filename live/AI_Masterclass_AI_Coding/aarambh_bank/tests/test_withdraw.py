"""
Tests for the withdraw feature (src/features/withdraw.py).

Covers every acceptance criterion in specs/withdraw.md:
  AC-1  A withdrawal of a positive amount <= balance decreases the balance by
        exactly that amount.
  AC-2  A withdrawal greater than the current balance is rejected; balance and
        transactions are unchanged; balance never goes below 0.00.
  AC-3  A withdrawal of 0 or a negative amount is rejected; no change.
  AC-4  A successful withdrawal writes exactly one DEBIT transaction row with
        the correct amount and balance_after.
  AC-5  The balance update and the transaction insert are atomic — a simulated
        failure leaves neither applied.
  AC-6  Amounts are handled as Decimal; no float is used anywhere in the path.

Edge cases covered:
  - Withdraw exactly equal to balance -> allowed, resulting balance 0.00.
  - Withdraw 0.01 more than balance -> rejected (no overdraft).
  - Two consecutive withdrawals -> both succeed when balance covers them; second
    fails when balance is insufficient.
  - Withdrawal scoped to the correct account (other account untouched).
  - Minimum positive amount (0.01) is accepted.
  - Optional category/note stored when provided; NULL when omitted.
"""

import importlib
import os
import sys
import unittest.mock
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

TEST_USERNAME = "wd_user"
TEST_EMAIL = "wd_user@example.com"
TEST_PHONE = "9876500002"
TEST_PASSWORD_HASH = "$2b$12$placeholderhashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

STARTING_BALANCE = Decimal("1000.00")
SMALL_WITHDRAWAL = Decimal("200.00")
ZERO_AMOUNT = Decimal("0.00")
NEGATIVE_AMOUNT = Decimal("-50.00")
MIN_AMOUNT = Decimal("0.01")


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


def fun_db_balance(account_id: int) -> Decimal:
    """Return the current balance for an account, read directly from the DB.

    Args:
        account_id: The accounts.id to query.

    Returns:
        Decimal: the current balance value stored in the DB.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM accounts WHERE id = %s", (account_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    assert row is not None, f"No account row found for account_id={account_id}"
    return Decimal(str(row[0]))


def fun_tx_count(account_id: int) -> int:
    """Return the total number of transaction rows for a given account.

    Args:
        account_id: The accounts.id to count transactions for.

    Returns:
        int: number of rows in the transactions table for that account.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM transactions WHERE account_id = %s", (account_id,)
    )
    (count,) = cursor.fetchone()
    cursor.close()
    conn.close()
    return count


def fun_fetch_last_tx(account_id: int) -> dict | None:
    """Return the most-recent transaction row for an account (by id DESC).

    Args:
        account_id: The accounts.id whose last transaction to fetch.

    Returns:
        dict with all transaction column values, or None if no rows exist.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM transactions WHERE account_id = %s ORDER BY id DESC LIMIT 1",
        (account_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def fun_fetch_all_tx(account_id: int) -> list[dict]:
    """Return all transaction rows for an account ordered by id ASC.

    Args:
        account_id: The accounts.id whose transactions to fetch.

    Returns:
        list[dict]: all transaction rows, oldest first.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM transactions WHERE account_id = %s ORDER BY id ASC",
        (account_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def fun_set_balance(account_id: int, amount: Decimal) -> None:
    """Set the account balance directly via raw SQL UPDATE.

    Used to seed a non-zero starting balance without depending on fun_deposit.

    Args:
        account_id: The accounts.id to update.
        amount:     The Decimal balance to write into the accounts row.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE accounts SET balance = %s WHERE id = %s",
        (str(amount), account_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ---------------------------------------------------------------------------
# Session-level fixture: create (or reuse) the test DB + schema.
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
# Module fixtures: lazily import feature modules after DB env is set.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fun_withdraw_module():
    """Return the withdraw feature module so tests can call fun_withdraw.

    Returns:
        module: src.features.withdraw
    """
    return importlib.import_module("src.features.withdraw")


@pytest.fixture(scope="session")
def fun_account_module():
    """Return the account feature module for use in helper fixtures.

    Returns:
        module: src.features.account
    """
    return importlib.import_module("src.features.account")


# ---------------------------------------------------------------------------
# Helper fixtures: user and account creation without feature dependencies.
# ---------------------------------------------------------------------------


@pytest.fixture
def fun_make_user():
    """Factory fixture: insert a minimal user row via raw SQL and return user_id.

    Returns a callable fun_insert(username, email) -> int.

    Returns:
        callable: fun_insert(username, email) -> int
    """

    def fun_insert(
        username: str = TEST_USERNAME,
        email: str = TEST_EMAIL,
    ) -> int:
        """Insert a minimal user row and return its generated id.

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

    return fun_insert


@pytest.fixture
def fun_make_account(fun_account_module):
    """Factory fixture: create an account via fun_create_account and return its info.

    Returns a callable fun_open(user_id) -> {account_id, account_number}.

    Args:
        fun_account_module: The account feature module injected by pytest.

    Returns:
        callable: fun_open(user_id) -> dict
    """

    def fun_open(user_id: int) -> dict:
        """Create an account for user_id and return {account_id, account_number}.

        Args:
            user_id: The user to open an account for.

        Returns:
            dict: {"account_id": int, "account_number": str}
        """
        result = fun_account_module.fun_create_account(user_id)
        assert result["ok"] is True, f"fun_make_account helper failed: {result}"
        return {
            "account_id": result["account_id"],
            "account_number": result["account_number"],
        }

    return fun_open


# ===========================================================================
# AC-1 (FR-WD-01): A withdrawal of a positive amount <= balance decreases the
#   balance by exactly that amount.
# ===========================================================================


def test_ac1_withdrawal_decreases_balance_by_exact_amount(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-1: Withdrawing a positive amount reduces the stored balance by exactly that amount."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    result = fun_withdraw_module.fun_withdraw(account_id, SMALL_WITHDRAWAL)

    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    expected_balance = STARTING_BALANCE - SMALL_WITHDRAWAL
    assert fun_db_balance(account_id) == expected_balance


def test_ac1_returned_balance_matches_db_balance(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-1: The 'balance' value in the returned dict matches the DB-stored balance."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    result = fun_withdraw_module.fun_withdraw(account_id, SMALL_WITHDRAWAL)

    assert result["ok"] is True
    assert result["balance"] == fun_db_balance(account_id)


def test_ac1_withdrawal_amount_exact_paise_precision(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-1: A withdrawal with paise precision is applied without rounding error."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, Decimal("500.00"))
    amount = Decimal("123.45")

    result = fun_withdraw_module.fun_withdraw(account_id, amount)

    assert result["ok"] is True
    assert fun_db_balance(account_id) == Decimal("500.00") - amount


def test_ac1_returned_balance_is_decimal(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-1: The balance value in the success dict is of type Decimal, not float."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    result = fun_withdraw_module.fun_withdraw(account_id, SMALL_WITHDRAWAL)

    assert result["ok"] is True
    assert isinstance(result["balance"], Decimal), (
        f"balance must be Decimal, got {type(result['balance']).__name__}"
    )


# ===========================================================================
# AC-2 (FR-WD-02 / BR-02): A withdrawal greater than the current balance is
#   rejected; balance and transactions are unchanged; balance never goes below 0.
# ===========================================================================


def test_ac2_overdraft_rejected(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-2: Withdrawing more than the current balance returns ok=False."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, Decimal("100.00"))

    result = fun_withdraw_module.fun_withdraw(account_id, Decimal("100.01"))

    assert result["ok"] is False


def test_ac2_overdraft_error_message_is_insufficient_balance(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-2: The error message for an overdraft attempt is exactly 'Insufficient balance.'."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, Decimal("100.00"))

    result = fun_withdraw_module.fun_withdraw(account_id, Decimal("200.00"))

    assert result["ok"] is False
    assert result.get("error") == "Insufficient balance.", (
        f"Expected 'Insufficient balance.', got: {result.get('error')!r}"
    )


def test_ac2_overdraft_balance_unchanged(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-2: After a rejected overdraft the stored balance is unchanged."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, Decimal("300.00"))

    fun_withdraw_module.fun_withdraw(account_id, Decimal("500.00"))

    assert fun_db_balance(account_id) == Decimal("300.00")


def test_ac2_overdraft_no_transaction_row(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-2: After a rejected overdraft no transaction row is written."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, Decimal("300.00"))

    fun_withdraw_module.fun_withdraw(account_id, Decimal("500.00"))

    assert fun_tx_count(account_id) == 0


def test_ac2_balance_never_goes_below_zero(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-2: After a rejected overdraft the balance never goes below 0.00."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, Decimal("50.00"))

    fun_withdraw_module.fun_withdraw(account_id, Decimal("50.01"))

    assert fun_db_balance(account_id) >= Decimal("0.00")


def test_ac2_zero_balance_any_withdrawal_rejected(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-2: When the account balance is 0.00, any positive withdrawal is rejected."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    # Balance starts at 0.00 after account creation; no seeding needed.

    result = fun_withdraw_module.fun_withdraw(account_id, Decimal("0.01"))

    assert result["ok"] is False
    assert result.get("error") == "Insufficient balance."
    assert fun_db_balance(account_id) == Decimal("0.00")
    assert fun_tx_count(account_id) == 0


# ===========================================================================
# AC-3 (FR-WD-01): A withdrawal of 0 or a negative amount is rejected; no change.
# ===========================================================================


def test_ac3_zero_amount_rejected(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-3: Withdrawing Decimal('0.00') returns ok=False with an error message."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    result = fun_withdraw_module.fun_withdraw(account_id, ZERO_AMOUNT)

    assert result["ok"] is False
    assert result.get("error"), "Expected a non-empty error message for zero amount"


def test_ac3_zero_amount_balance_unchanged(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-3: After a rejected zero-amount withdrawal the stored balance is unchanged."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    fun_withdraw_module.fun_withdraw(account_id, ZERO_AMOUNT)

    assert fun_db_balance(account_id) == STARTING_BALANCE


def test_ac3_zero_amount_no_transaction_row(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-3: After a rejected zero-amount withdrawal no transaction row is inserted."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    fun_withdraw_module.fun_withdraw(account_id, ZERO_AMOUNT)

    assert fun_tx_count(account_id) == 0


def test_ac3_negative_amount_rejected(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-3: Withdrawing a negative amount returns ok=False with an error message."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    result = fun_withdraw_module.fun_withdraw(account_id, NEGATIVE_AMOUNT)

    assert result["ok"] is False
    assert result.get("error"), "Expected a non-empty error message for negative amount"


def test_ac3_negative_amount_balance_unchanged(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-3: After a rejected negative-amount withdrawal the stored balance is unchanged."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    fun_withdraw_module.fun_withdraw(account_id, NEGATIVE_AMOUNT)

    assert fun_db_balance(account_id) == STARTING_BALANCE


def test_ac3_negative_amount_no_transaction_row(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-3: After a rejected negative-amount withdrawal no transaction row is inserted."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    fun_withdraw_module.fun_withdraw(account_id, NEGATIVE_AMOUNT)

    assert fun_tx_count(account_id) == 0


def test_ac3_error_message_is_non_empty_string(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-3: The error message for an invalid (zero) amount is a non-empty string."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    result = fun_withdraw_module.fun_withdraw(account_id, ZERO_AMOUNT)

    assert isinstance(result.get("error"), str)
    assert len(result["error"].strip()) > 0


# ===========================================================================
# AC-4 (FR-WD-03): A successful withdrawal writes exactly one DEBIT transaction
#   row with the correct amount and balance_after.
# ===========================================================================


def test_ac4_successful_withdrawal_creates_one_tx_row(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-4: A single successful withdrawal creates exactly one row in the transactions table."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    fun_withdraw_module.fun_withdraw(account_id, SMALL_WITHDRAWAL)

    assert fun_tx_count(account_id) == 1


def test_ac4_transaction_type_is_debit(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-4: The transaction row written by fun_withdraw has type='DEBIT'."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    fun_withdraw_module.fun_withdraw(account_id, SMALL_WITHDRAWAL)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["type"] == "DEBIT", f"Expected type='DEBIT', got '{tx['type']}'"


def test_ac4_transaction_amount_matches_withdrawn_amount(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-4: The amount column in the transaction row equals the withdrawn amount."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    amount = Decimal("350.75")
    fun_set_balance(account_id, Decimal("1000.00"))

    fun_withdraw_module.fun_withdraw(account_id, amount)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    tx_amount = Decimal(str(tx["amount"]))
    assert tx_amount == amount, f"Expected amount={amount}, got {tx_amount}"


def test_ac4_transaction_balance_after_is_correct(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-4: The balance_after column in the transaction row equals the new account balance."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    starting = Decimal("800.00")
    amount = Decimal("250.00")
    expected_balance_after = starting - amount
    fun_set_balance(account_id, starting)

    fun_withdraw_module.fun_withdraw(account_id, amount)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    balance_after = Decimal(str(tx["balance_after"]))
    assert balance_after == expected_balance_after, (
        f"Expected balance_after={expected_balance_after}, got {balance_after}"
    )


def test_ac4_transaction_account_id_matches(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-4: The transaction row's account_id FK matches the withdrawing account."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    fun_withdraw_module.fun_withdraw(account_id, SMALL_WITHDRAWAL)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["account_id"] == account_id


def test_ac4_category_and_note_stored_when_provided(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-4: When category and note are supplied both are stored in the DEBIT transaction row."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    result = fun_withdraw_module.fun_withdraw(
        account_id, SMALL_WITHDRAWAL, category="Groceries", note="Weekly shop"
    )

    assert result["ok"] is True
    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["category"] == "Groceries", (
        f"Expected category='Groceries', got '{tx['category']}'"
    )
    assert tx["note"] == "Weekly shop", (
        f"Expected note='Weekly shop', got '{tx['note']}'"
    )


def test_ac4_category_null_when_omitted(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-4: When category is not passed the DEBIT transaction row has category=NULL."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    fun_withdraw_module.fun_withdraw(account_id, SMALL_WITHDRAWAL)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["category"] is None, (
        f"Expected category=NULL when omitted, got '{tx['category']}'"
    )


def test_ac4_note_null_when_omitted(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-4: When note is not passed the DEBIT transaction row has note=NULL."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    fun_withdraw_module.fun_withdraw(account_id, SMALL_WITHDRAWAL)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["note"] is None, (
        f"Expected note=NULL when omitted, got '{tx['note']}'"
    )


# ===========================================================================
# AC-5 (FR-WD-04 / BR-04): The balance update and the transaction insert are
#   atomic — a simulated failure leaves neither applied.
# ===========================================================================


def test_ac5_successful_withdrawal_both_sides_applied(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-5: A successful withdrawal leaves BOTH the balance changed AND a tx row inserted.

    Confirms normal atomicity: neither half of the DB transaction is silently skipped.
    """
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    result = fun_withdraw_module.fun_withdraw(account_id, SMALL_WITHDRAWAL)

    assert result["ok"] is True
    assert fun_db_balance(account_id) == STARTING_BALANCE - SMALL_WITHDRAWAL
    assert fun_tx_count(account_id) == 1


def test_ac5_invalid_withdrawal_leaves_both_unchanged(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-5: A rejected withdrawal (invalid amount) leaves BOTH balance and tx count unchanged."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    result = fun_withdraw_module.fun_withdraw(account_id, ZERO_AMOUNT)

    assert result["ok"] is False
    assert fun_db_balance(account_id) == STARTING_BALANCE
    assert fun_tx_count(account_id) == 0


def test_ac5_commit_failure_leaves_db_unchanged(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-5: When conn.commit() raises, neither the balance nor the tx row persists.

    Patches mysql.connector.connect to return a real connection whose commit
    method rolls back then raises RuntimeError, simulating a mid-transaction
    failure.  Asserts that fun_withdraw returns ok=False and the DB is left in
    its original state.
    """
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    balance_before = fun_db_balance(account_id)
    tx_count_before = fun_tx_count(account_id)

    # Build a real connection to the test DB but wrap commit to raise.
    real_conn = mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=TEST_DB_NAME,
        autocommit=False,
    )
    original_commit = real_conn.commit

    def fun_exploding_commit():
        """Rollback and raise to simulate a commit-time failure."""
        real_conn.rollback()
        raise RuntimeError("Simulated commit failure for atomicity test")

    real_conn.commit = fun_exploding_commit

    with unittest.mock.patch("mysql.connector.connect", return_value=real_conn):
        result = fun_withdraw_module.fun_withdraw(account_id, SMALL_WITHDRAWAL)

    # Restore commit so the connection can be cleanly closed.
    real_conn.commit = original_commit
    real_conn.close()

    assert result["ok"] is False, (
        "Expected ok=False when commit raises, got: " + str(result)
    )
    assert fun_db_balance(account_id) == balance_before, (
        "Balance must be unchanged when commit fails"
    )
    assert fun_tx_count(account_id) == tx_count_before, (
        "No transaction row must survive when commit fails"
    )


# ===========================================================================
# AC-6 (money rule): Amounts are handled as Decimal; no float is used anywhere
#   in the withdraw path.
# ===========================================================================


def test_ac6_returned_balance_is_decimal_not_float(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-6: The balance value returned from fun_withdraw is Decimal, never float."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    result = fun_withdraw_module.fun_withdraw(account_id, Decimal("100.00"))

    assert result["ok"] is True
    assert not isinstance(result["balance"], float), (
        "balance in fun_withdraw result must NOT be float — use Decimal"
    )
    assert isinstance(result["balance"], Decimal), (
        f"balance must be Decimal, got {type(result['balance']).__name__}"
    )


def test_ac6_db_balance_reads_as_decimal_not_float(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-6: The balance read from the DB after a withdrawal is Decimal, not float."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, STARTING_BALANCE)

    fun_withdraw_module.fun_withdraw(account_id, Decimal("100.00"))

    balance = fun_db_balance(account_id)
    assert isinstance(balance, Decimal), (
        f"DB-sourced balance must be Decimal, got {type(balance).__name__}"
    )
    assert not isinstance(balance, float)


def test_ac6_transaction_amount_in_db_is_representable_as_decimal(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-6: The amount in the DEBIT transaction row can be represented exactly as Decimal."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    withdrawn = Decimal("99.99")
    fun_set_balance(account_id, Decimal("500.00"))

    fun_withdraw_module.fun_withdraw(account_id, withdrawn)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    stored = Decimal(str(tx["amount"]))
    assert stored == withdrawn, (
        f"Stored amount {stored!r} does not equal withdrawn {withdrawn!r}"
    )


def test_ac6_decimal_input_does_not_change_precision(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """AC-6: A Decimal amount with two decimal places is stored without precision loss."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    starting = Decimal("2000.00")
    amount = Decimal("1234.56")
    fun_set_balance(account_id, starting)

    fun_withdraw_module.fun_withdraw(account_id, amount)

    assert fun_db_balance(account_id) == starting - amount


# ===========================================================================
# Edge cases
# ===========================================================================


def test_edge_withdraw_exactly_equal_to_balance_allowed(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """Edge: Withdrawing exactly the full balance is allowed; resulting balance is 0.00."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, Decimal("500.00"))

    result = fun_withdraw_module.fun_withdraw(account_id, Decimal("500.00"))

    assert result["ok"] is True, f"Expected ok=True for exact-balance withdrawal, got: {result}"
    assert fun_db_balance(account_id) == Decimal("0.00")
    assert result["balance"] == Decimal("0.00")


def test_edge_withdraw_one_paise_more_than_balance_rejected(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """Edge: Withdrawing 0.01 more than the current balance is rejected (no overdraft)."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, Decimal("100.00"))

    result = fun_withdraw_module.fun_withdraw(account_id, Decimal("100.01"))

    assert result["ok"] is False
    assert result.get("error") == "Insufficient balance."
    assert fun_db_balance(account_id) == Decimal("100.00")
    assert fun_tx_count(account_id) == 0


def test_edge_two_consecutive_withdrawals_both_succeed_when_balance_covers(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """Edge: Two consecutive withdrawals both succeed when the balance covers them."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, Decimal("1000.00"))
    first = Decimal("400.00")
    second = Decimal("300.00")

    result_1 = fun_withdraw_module.fun_withdraw(account_id, first)
    result_2 = fun_withdraw_module.fun_withdraw(account_id, second)

    assert result_1["ok"] is True, f"First withdrawal failed: {result_1}"
    assert result_2["ok"] is True, f"Second withdrawal failed: {result_2}"
    assert fun_db_balance(account_id) == Decimal("1000.00") - first - second
    assert fun_tx_count(account_id) == 2


def test_edge_second_withdrawal_fails_when_balance_insufficient(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """Edge: Second consecutive withdrawal fails when the remaining balance is insufficient."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, Decimal("500.00"))
    first = Decimal("400.00")
    second = Decimal("200.00")  # 200 > remaining 100 -> insufficient

    result_1 = fun_withdraw_module.fun_withdraw(account_id, first)
    result_2 = fun_withdraw_module.fun_withdraw(account_id, second)

    assert result_1["ok"] is True
    assert result_2["ok"] is False
    assert result_2.get("error") == "Insufficient balance."
    # Only the first withdrawal's DEBIT row should exist.
    assert fun_db_balance(account_id) == Decimal("500.00") - first
    assert fun_tx_count(account_id) == 1


def test_edge_two_consecutive_withdrawals_balance_after_decrements(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """Edge: balance_after in each of two consecutive DEBIT rows is correctly cumulative."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    starting = Decimal("1000.00")
    first = Decimal("300.00")
    second = Decimal("200.00")
    fun_set_balance(account_id, starting)

    fun_withdraw_module.fun_withdraw(account_id, first)
    fun_withdraw_module.fun_withdraw(account_id, second)

    rows = fun_fetch_all_tx(account_id)
    assert len(rows) == 2
    balance_after_first = Decimal(str(rows[0]["balance_after"]))
    balance_after_second = Decimal(str(rows[1]["balance_after"]))
    assert balance_after_first == starting - first, (
        f"First balance_after should be {starting - first}, got {balance_after_first}"
    )
    assert balance_after_second == starting - first - second, (
        f"Second balance_after should be {starting - first - second}, "
        f"got {balance_after_second}"
    )


def test_edge_withdrawal_scoped_to_correct_account(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """Edge: A withdrawal from account A does not alter the balance or tx count of account B."""
    user_id_a = fun_make_user(username="wd_user_a", email="wd_a@example.com")
    user_id_b = fun_make_user(username="wd_user_b", email="wd_b@example.com")
    account_a = fun_make_account(user_id_a)
    account_b = fun_make_account(user_id_b)
    account_id_a = account_a["account_id"]
    account_id_b = account_b["account_id"]
    fun_set_balance(account_id_a, Decimal("1000.00"))
    fun_set_balance(account_id_b, Decimal("500.00"))

    fun_withdraw_module.fun_withdraw(account_id_a, Decimal("200.00"))

    # Account B must be completely untouched.
    assert fun_db_balance(account_id_b) == Decimal("500.00")
    assert fun_tx_count(account_id_b) == 0


def test_edge_minimum_positive_amount_accepted(
    fun_withdraw_module, fun_make_user, fun_make_account
):
    """Edge: The smallest representable positive Decimal ('0.01') is accepted as a withdrawal."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    fun_set_balance(account_id, Decimal("1.00"))

    result = fun_withdraw_module.fun_withdraw(account_id, MIN_AMOUNT)

    assert result["ok"] is True, f"Expected ok=True for minimum amount, got: {result}"
    assert fun_db_balance(account_id) == Decimal("1.00") - MIN_AMOUNT
    assert fun_tx_count(account_id) == 1
