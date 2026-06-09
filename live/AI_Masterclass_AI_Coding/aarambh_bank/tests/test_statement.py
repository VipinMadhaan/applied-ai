"""
Tests for the statement feature (src/features/statement.py).

Covers every acceptance criterion in specs/statement.md:
  AC-1  (FR-STMT-01) The history lists the user's transactions newest first
        with a correct running balance (balance_after per row).
  AC-2  (FR-STMT-02) Filtering by date range (from_date, to_date) returns only
        transactions within that range (inclusive).
  AC-3  (FR-STMT-02) Filtering by type ('CREDIT', 'DEBIT', or None for all)
        returns only matching rows.
  AC-4  (FR-STMT-03) fun_generate_csv(rows) produces a CSV string whose data
        rows contain the same records as the filtered view, with headers:
        date,type,amount,category,note,balance_after.
  AC-5  (FR-STMT-04) Only the requesting account's data is returned; there is
        no path to another account's transactions.

Edge cases covered:
  - No transactions in range -> rows is an empty list, not an error.
  - from_date > to_date -> {"ok": False, "error": ...} with a clear message.
  - from_date == to_date -> transactions on exactly that date are returned.
"""

import importlib
import os
import sys
from datetime import date, datetime
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

TEST_USERNAME = "stmt_user"
TEST_EMAIL = "stmt_user@example.com"
TEST_PHONE = "9876500003"
TEST_PASSWORD_HASH = "$2b$12$placeholderhashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

CSV_HEADER = "date,type,amount,category,note,balance_after"

AMOUNT_100 = Decimal("100.00")
AMOUNT_200 = Decimal("200.00")
AMOUNT_300 = Decimal("300.00")
AMOUNT_400 = Decimal("400.00")
AMOUNT_500 = Decimal("500.00")

# Three distinct timestamps for AC-1 ordering tests.
TS_OLDEST = datetime(2025, 1, 10, 9, 0, 0)
TS_MIDDLE = datetime(2025, 1, 15, 12, 0, 0)
TS_NEWEST = datetime(2025, 1, 20, 18, 0, 0)

# Five timestamps spread across three dates for AC-2 range filter tests.
TS_DATE_A_1 = datetime(2025, 3, 1, 8, 0, 0)
TS_DATE_A_2 = datetime(2025, 3, 1, 16, 0, 0)
TS_DATE_B_1 = datetime(2025, 3, 15, 10, 0, 0)
TS_DATE_B_2 = datetime(2025, 3, 15, 20, 0, 0)
TS_DATE_C_1 = datetime(2025, 3, 31, 12, 0, 0)

DATE_A = date(2025, 3, 1)
DATE_B = date(2025, 3, 15)
DATE_C = date(2025, 3, 31)


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
    """Insert a minimal user row via raw SQL and return the generated user_id.

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


def fun_insert_tx(
    account_id: int,
    tx_type: str,
    amount: Decimal,
    balance_after: Decimal,
    created_at: datetime,
    category: str | None = None,
    note: str | None = None,
) -> int:
    """Insert a transaction row directly via raw SQL and return the generated tx id.

    This helper bypasses the deposit/withdraw feature functions to give tests
    full control over created_at timestamps and balance_after values.

    Args:
        account_id:    The accounts.id that owns the transaction.
        tx_type:       'CREDIT' or 'DEBIT'.
        amount:        Decimal amount of the transaction.
        balance_after: Decimal running balance after this transaction.
        created_at:    Explicit datetime for the transaction (controls ordering).
        category:      Optional category string; stored as NULL when None.
        note:          Optional note string; stored as NULL when None.

    Returns:
        int: The auto-increment id of the inserted transaction row.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO transactions "
        "(account_id, type, amount, category, note, created_at, balance_after) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            account_id,
            tx_type,
            str(amount),
            category,
            note,
            created_at,
            str(balance_after),
        ),
    )
    conn.commit()
    tx_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return tx_id


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
# Module fixtures: lazily import feature modules after DB env is set.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fun_statement_module():
    """Return the statement feature module so tests can call its public functions.

    Returns:
        module: src.features.statement
    """
    return importlib.import_module("src.features.statement")


@pytest.fixture(scope="session")
def fun_account_module():
    """Return the account feature module for account creation in helper fixtures.

    Returns:
        module: src.features.account
    """
    return importlib.import_module("src.features.account")


# ---------------------------------------------------------------------------
# Helper fixtures: user and account creation.
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
        return fun_insert_user(username=username, email=email)

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
# AC-1 (FR-STMT-01): The history lists the user's transactions newest first
#   with a correct running balance (balance_after per row).
# ===========================================================================


def test_ac1_transactions_sorted_newest_first(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-1: fun_get_statement returns rows sorted newest-first by created_at."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_OLDEST)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_200, Decimal("300.00"), TS_MIDDLE)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_300, Decimal("600.00"), TS_NEWEST)

    result = fun_statement_module.fun_get_statement(account_id)

    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    rows = result["rows"]
    assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"
    assert rows[0]["created_at"] == TS_NEWEST, (
        f"First row should be newest; got {rows[0]['created_at']}"
    )
    assert rows[1]["created_at"] == TS_MIDDLE, (
        f"Second row should be middle; got {rows[1]['created_at']}"
    )
    assert rows[2]["created_at"] == TS_OLDEST, (
        f"Third row should be oldest; got {rows[2]['created_at']}"
    )


def test_ac1_balance_after_per_row_matches_inserted_values(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-1: Each row's balance_after matches the value written to the DB on insert."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    balance_after_oldest = AMOUNT_100
    balance_after_middle = Decimal("300.00")
    balance_after_newest = Decimal("600.00")

    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, balance_after_oldest, TS_OLDEST)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_200, balance_after_middle, TS_MIDDLE)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_300, balance_after_newest, TS_NEWEST)

    result = fun_statement_module.fun_get_statement(account_id)

    assert result["ok"] is True
    rows = result["rows"]
    # Rows are newest-first, so index 0 is TS_NEWEST.
    assert Decimal(str(rows[0]["balance_after"])) == balance_after_newest
    assert Decimal(str(rows[1]["balance_after"])) == balance_after_middle
    assert Decimal(str(rows[2]["balance_after"])) == balance_after_oldest


def test_ac1_balance_after_is_decimal_not_float(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-1: The balance_after value in every returned row is Decimal, not float."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_OLDEST)

    result = fun_statement_module.fun_get_statement(account_id)

    assert result["ok"] is True
    for row in result["rows"]:
        assert isinstance(row["balance_after"], Decimal), (
            f"balance_after must be Decimal, got {type(row['balance_after']).__name__}"
        )
        assert not isinstance(row["balance_after"], float)


def test_ac1_amount_is_decimal_not_float(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-1: The amount value in every returned row is Decimal, not float."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(account_id, "DEBIT", AMOUNT_200, Decimal("300.00"), TS_OLDEST)

    result = fun_statement_module.fun_get_statement(account_id)

    assert result["ok"] is True
    for row in result["rows"]:
        assert isinstance(row["amount"], Decimal), (
            f"amount must be Decimal, got {type(row['amount']).__name__}"
        )
        assert not isinstance(row["amount"], float)


def test_ac1_row_has_required_keys(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-1: Every returned row contains the required keys per the module contract."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(
        account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_OLDEST,
        category="Salary", note="June pay"
    )

    result = fun_statement_module.fun_get_statement(account_id)

    assert result["ok"] is True
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    for key in ("type", "amount", "category", "note", "created_at", "balance_after"):
        assert key in row, f"Expected key '{key}' missing from row dict"


def test_ac1_no_transactions_returns_empty_list_not_error(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-1 / edge: An account with no transactions returns ok=True with an empty rows list."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_statement_module.fun_get_statement(account_id)

    assert result["ok"] is True, f"Expected ok=True for empty statement, got: {result}"
    assert result["rows"] == [], (
        f"Expected empty list for account with no transactions, got: {result['rows']}"
    )


# ===========================================================================
# AC-2 (FR-STMT-02): Filtering by date range (from_date, to_date) returns only
#   transactions within that range (inclusive).
# ===========================================================================


def test_ac2_date_range_filter_returns_only_matching_rows(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-2: Filtering by from_date/to_date returns only rows whose created_at date falls in range."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    # Five transactions spread across three distinct dates.
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_200, TS_DATE_A_2)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, Decimal("300.00"), TS_DATE_B_1)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_400, TS_DATE_B_2)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_500, TS_DATE_C_1)

    # Filter to DATE_B only: should return exactly the 2 rows on that date.
    result = fun_statement_module.fun_get_statement(
        account_id, from_date=DATE_B, to_date=DATE_B
    )

    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    rows = result["rows"]
    assert len(rows) == 2, (
        f"Expected 2 rows for DATE_B filter, got {len(rows)}: {rows}"
    )
    for row in rows:
        assert row["created_at"].date() == DATE_B, (
            f"Row date {row['created_at'].date()} not in filter range {DATE_B}"
        )


def test_ac2_date_range_filter_is_inclusive_on_both_ends(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-2: The date range filter is inclusive: rows on exactly from_date or to_date are returned."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_200, TS_DATE_B_1)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, Decimal("300.00"), TS_DATE_C_1)

    # from_date=DATE_A, to_date=DATE_B should include both boundary dates.
    result = fun_statement_module.fun_get_statement(
        account_id, from_date=DATE_A, to_date=DATE_B
    )

    assert result["ok"] is True
    rows = result["rows"]
    assert len(rows) == 2, (
        f"Expected 2 rows (DATE_A and DATE_B), got {len(rows)}: {rows}"
    )
    returned_dates = {row["created_at"].date() for row in rows}
    assert DATE_A in returned_dates, f"DATE_A {DATE_A} not in returned dates {returned_dates}"
    assert DATE_B in returned_dates, f"DATE_B {DATE_B} not in returned dates {returned_dates}"


def test_ac2_rows_outside_range_are_excluded(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-2: Transactions outside the requested date range do not appear in results."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_200, TS_DATE_B_1)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, Decimal("300.00"), TS_DATE_C_1)

    # Filter to DATE_B only; DATE_A and DATE_C must be excluded.
    result = fun_statement_module.fun_get_statement(
        account_id, from_date=DATE_B, to_date=DATE_B
    )

    assert result["ok"] is True
    rows = result["rows"]
    for row in rows:
        assert row["created_at"].date() not in (DATE_A, DATE_C), (
            f"Row from {row['created_at'].date()} should have been excluded"
        )


def test_ac2_no_transactions_in_range_returns_empty_list(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-2 / edge: A date range with no matching transactions returns ok=True and empty rows list."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1)

    # Request a future range with no transactions.
    future_date = date(2099, 1, 1)
    result = fun_statement_module.fun_get_statement(
        account_id, from_date=future_date, to_date=future_date
    )

    assert result["ok"] is True, (
        f"Expected ok=True for empty date range, got: {result}"
    )
    assert result["rows"] == [], (
        f"Expected empty list for date range with no transactions, got: {result['rows']}"
    )


def test_ac2_from_date_equals_to_date_returns_that_days_transactions(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-2 / edge: When from_date == to_date, only transactions on that exact date are returned."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_200, TS_DATE_A_2)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, Decimal("300.00"), TS_DATE_B_1)

    result = fun_statement_module.fun_get_statement(
        account_id, from_date=DATE_A, to_date=DATE_A
    )

    assert result["ok"] is True
    rows = result["rows"]
    assert len(rows) == 2, (
        f"Expected 2 rows for single-day filter on DATE_A, got {len(rows)}: {rows}"
    )
    for row in rows:
        assert row["created_at"].date() == DATE_A, (
            f"Row date {row['created_at'].date()} does not match single-day filter {DATE_A}"
        )


def test_ac2_from_date_greater_than_to_date_returns_error(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-2 / edge: When from_date > to_date the function returns ok=False with a clear error."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_statement_module.fun_get_statement(
        account_id, from_date=DATE_C, to_date=DATE_A
    )

    assert result["ok"] is False, (
        f"Expected ok=False when from_date > to_date, got: {result}"
    )
    assert "error" in result, "Expected an 'error' key in the failure response"
    assert isinstance(result["error"], str), "Error value must be a string"
    assert len(result["error"].strip()) > 0, "Error message must not be empty"


def test_ac2_error_message_is_clear_when_dates_inverted(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-2 / edge: The error message for from_date > to_date is informative (not a bare exception)."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result = fun_statement_module.fun_get_statement(
        account_id, from_date=DATE_C, to_date=DATE_A
    )

    assert result["ok"] is False
    # The message should mention date or range context — not an internal stack trace string.
    error_lower = result["error"].lower()
    date_keywords = ("date", "from", "to", "range", "before", "after", "invalid")
    assert any(kw in error_lower for kw in date_keywords), (
        f"Error message '{result['error']}' does not contain any date-related keyword"
    )


# ===========================================================================
# AC-3 (FR-STMT-02): Filtering by type ('CREDIT', 'DEBIT', or None for all)
#   returns only matching rows.
# ===========================================================================


def test_ac3_filter_by_credit_returns_only_credits(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-3: Filtering with tx_type='CREDIT' returns only CREDIT rows."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    # 2 CREDITs + 3 DEBITs.
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_200, Decimal("300.00"), TS_DATE_A_2)
    fun_insert_tx(account_id, "DEBIT", AMOUNT_100, AMOUNT_200, TS_DATE_B_1)
    fun_insert_tx(account_id, "DEBIT", AMOUNT_100, AMOUNT_100, TS_DATE_B_2)
    fun_insert_tx(account_id, "DEBIT", AMOUNT_100, Decimal("0.00"), TS_DATE_C_1)

    result = fun_statement_module.fun_get_statement(account_id, tx_type="CREDIT")

    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    rows = result["rows"]
    assert len(rows) == 2, f"Expected 2 CREDIT rows, got {len(rows)}: {rows}"
    for row in rows:
        assert row["type"] == "CREDIT", (
            f"Expected type='CREDIT', got '{row['type']}'"
        )


def test_ac3_filter_by_debit_returns_only_debits(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-3: Filtering with tx_type='DEBIT' returns only DEBIT rows."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    # 2 CREDITs + 3 DEBITs.
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_200, Decimal("300.00"), TS_DATE_A_2)
    fun_insert_tx(account_id, "DEBIT", AMOUNT_100, AMOUNT_200, TS_DATE_B_1)
    fun_insert_tx(account_id, "DEBIT", AMOUNT_100, AMOUNT_100, TS_DATE_B_2)
    fun_insert_tx(account_id, "DEBIT", AMOUNT_100, Decimal("0.00"), TS_DATE_C_1)

    result = fun_statement_module.fun_get_statement(account_id, tx_type="DEBIT")

    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    rows = result["rows"]
    assert len(rows) == 3, f"Expected 3 DEBIT rows, got {len(rows)}: {rows}"
    for row in rows:
        assert row["type"] == "DEBIT", (
            f"Expected type='DEBIT', got '{row['type']}'"
        )


def test_ac3_filter_by_none_returns_all_rows(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-3: Passing tx_type=None (default) returns all rows regardless of type."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    # 2 CREDITs + 3 DEBITs = 5 total.
    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1)
    fun_insert_tx(account_id, "CREDIT", AMOUNT_200, Decimal("300.00"), TS_DATE_A_2)
    fun_insert_tx(account_id, "DEBIT", AMOUNT_100, AMOUNT_200, TS_DATE_B_1)
    fun_insert_tx(account_id, "DEBIT", AMOUNT_100, AMOUNT_100, TS_DATE_B_2)
    fun_insert_tx(account_id, "DEBIT", AMOUNT_100, Decimal("0.00"), TS_DATE_C_1)

    result = fun_statement_module.fun_get_statement(account_id, tx_type=None)

    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    rows = result["rows"]
    assert len(rows) == 5, f"Expected 5 rows when tx_type=None, got {len(rows)}: {rows}"


def test_ac3_credit_filter_excludes_debits(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-3: When filtering for CREDIT, no DEBIT rows appear in the result."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1)
    fun_insert_tx(account_id, "DEBIT", AMOUNT_100, Decimal("0.00"), TS_DATE_B_1)

    result = fun_statement_module.fun_get_statement(account_id, tx_type="CREDIT")

    assert result["ok"] is True
    for row in result["rows"]:
        assert row["type"] != "DEBIT", (
            "A DEBIT row appeared in a CREDIT-filtered result"
        )


def test_ac3_debit_filter_excludes_credits(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-3: When filtering for DEBIT, no CREDIT rows appear in the result."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1)
    fun_insert_tx(account_id, "DEBIT", AMOUNT_100, Decimal("0.00"), TS_DATE_B_1)

    result = fun_statement_module.fun_get_statement(account_id, tx_type="DEBIT")

    assert result["ok"] is True
    for row in result["rows"]:
        assert row["type"] != "CREDIT", (
            "A CREDIT row appeared in a DEBIT-filtered result"
        )


# ===========================================================================
# AC-4 (FR-STMT-03): fun_generate_csv(rows) produces a CSV string with headers
#   date,type,amount,category,note,balance_after and one data row per input row.
# ===========================================================================


def test_ac4_csv_has_correct_header_line(fun_statement_module):
    """AC-4: The first line of the generated CSV is the required header string."""
    rows = [
        {
            "type": "CREDIT",
            "amount": AMOUNT_100,
            "category": "Salary",
            "note": "June",
            "created_at": datetime(2025, 6, 1, 10, 0, 0),
            "balance_after": AMOUNT_100,
        }
    ]

    csv_output = fun_statement_module.fun_generate_csv(rows)

    first_line = csv_output.splitlines()[0]
    assert first_line == CSV_HEADER, (
        f"Expected header '{CSV_HEADER}', got '{first_line}'"
    )


def test_ac4_csv_row_count_equals_input_rows_plus_header(fun_statement_module):
    """AC-4: The total CSV line count is len(rows) + 1 (one header line plus one data line each)."""
    rows = [
        {
            "type": "CREDIT",
            "amount": AMOUNT_100,
            "category": "Salary",
            "note": "June",
            "created_at": datetime(2025, 6, 1, 10, 0, 0),
            "balance_after": AMOUNT_100,
        },
        {
            "type": "DEBIT",
            "amount": AMOUNT_200,
            "category": "Food",
            "note": "Lunch",
            "created_at": datetime(2025, 6, 2, 12, 0, 0),
            "balance_after": Decimal("300.00"),
        },
        {
            "type": "DEBIT",
            "amount": AMOUNT_100,
            "category": None,
            "note": None,
            "created_at": datetime(2025, 6, 3, 9, 0, 0),
            "balance_after": AMOUNT_200,
        },
    ]

    csv_output = fun_statement_module.fun_generate_csv(rows)

    lines = [line for line in csv_output.splitlines() if line]
    assert len(lines) == len(rows) + 1, (
        f"Expected {len(rows) + 1} lines (header + {len(rows)} data), got {len(lines)}"
    )


def test_ac4_csv_data_rows_contain_amount_and_type(fun_statement_module):
    """AC-4: Each data row in the CSV contains the expected amount and type values."""
    rows = [
        {
            "type": "CREDIT",
            "amount": Decimal("750.50"),
            "category": "Salary",
            "note": "Bonus",
            "created_at": datetime(2025, 5, 15, 11, 0, 0),
            "balance_after": Decimal("750.50"),
        },
        {
            "type": "DEBIT",
            "amount": Decimal("200.25"),
            "category": "Rent",
            "note": "May rent",
            "created_at": datetime(2025, 5, 16, 9, 0, 0),
            "balance_after": Decimal("550.25"),
        },
    ]

    csv_output = fun_statement_module.fun_generate_csv(rows)

    assert "CREDIT" in csv_output, "CREDIT type not found in CSV output"
    assert "DEBIT" in csv_output, "DEBIT type not found in CSV output"
    assert "750.50" in csv_output, "Amount 750.50 not found in CSV output"
    assert "200.25" in csv_output, "Amount 200.25 not found in CSV output"


def test_ac4_csv_data_rows_contain_date_from_created_at(fun_statement_module):
    """AC-4: The date column in each CSV data row uses created_at.date() as its value."""
    tx_date = date(2025, 7, 4)
    rows = [
        {
            "type": "CREDIT",
            "amount": AMOUNT_100,
            "category": None,
            "note": None,
            "created_at": datetime(2025, 7, 4, 15, 30, 0),
            "balance_after": AMOUNT_100,
        }
    ]

    csv_output = fun_statement_module.fun_generate_csv(rows)

    assert str(tx_date) in csv_output, (
        f"Expected date '{tx_date}' in CSV, but it was not found"
    )


def test_ac4_csv_empty_rows_list_returns_header_only(fun_statement_module):
    """AC-4 / edge: Calling fun_generate_csv([]) returns a CSV with only the header line."""
    csv_output = fun_statement_module.fun_generate_csv([])

    lines = [line for line in csv_output.splitlines() if line]
    assert len(lines) == 1, (
        f"Expected exactly 1 line (header only) for empty input, got {len(lines)}: {lines}"
    )
    assert lines[0] == CSV_HEADER, (
        f"Expected header '{CSV_HEADER}', got '{lines[0]}'"
    )


def test_ac4_csv_balance_after_in_data_rows(fun_statement_module):
    """AC-4: The balance_after value appears in each CSV data row."""
    balance_after_value = Decimal("1234.56")
    rows = [
        {
            "type": "CREDIT",
            "amount": balance_after_value,
            "category": None,
            "note": None,
            "created_at": datetime(2025, 8, 1, 8, 0, 0),
            "balance_after": balance_after_value,
        }
    ]

    csv_output = fun_statement_module.fun_generate_csv(rows)

    assert "1234.56" in csv_output, (
        f"Expected balance_after '1234.56' in CSV output, not found in: {csv_output}"
    )


def test_ac4_csv_is_string_type(fun_statement_module):
    """AC-4: fun_generate_csv always returns a str, not bytes or any other type."""
    rows = [
        {
            "type": "CREDIT",
            "amount": AMOUNT_100,
            "category": None,
            "note": None,
            "created_at": datetime(2025, 1, 1, 0, 0, 0),
            "balance_after": AMOUNT_100,
        }
    ]

    csv_output = fun_statement_module.fun_generate_csv(rows)

    assert isinstance(csv_output, str), (
        f"Expected fun_generate_csv to return str, got {type(csv_output).__name__}"
    )


def test_ac4_csv_matches_filtered_view_rows(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-4: The CSV data rows produced from fun_get_statement rows match the statement records."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(
        account_id, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1,
        category="Salary", note="April"
    )
    fun_insert_tx(
        account_id, "DEBIT", AMOUNT_200, Decimal("300.00"), TS_DATE_B_1,
        category="Groceries", note="Weekly shop"
    )

    result = fun_statement_module.fun_get_statement(account_id)
    assert result["ok"] is True
    stmt_rows = result["rows"]

    csv_output = fun_statement_module.fun_generate_csv(stmt_rows)

    lines = [line for line in csv_output.splitlines() if line]
    # Header + 2 data rows.
    assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}"
    assert "CREDIT" in csv_output
    assert "DEBIT" in csv_output
    assert "100.00" in csv_output
    assert "200.00" in csv_output


# ===========================================================================
# AC-5 (FR-STMT-04): Only the requesting account's data is returned; there is
#   no path to another account's transactions.
# ===========================================================================


def test_ac5_statement_returns_only_own_account_transactions(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-5: fun_get_statement for account A never includes transactions belonging to account B."""
    user_id_a = fun_make_user(username="stmt_user_a", email="stmt_a@example.com")
    user_id_b = fun_make_user(username="stmt_user_b", email="stmt_b@example.com")
    account_a = fun_make_account(user_id_a)
    account_b = fun_make_account(user_id_b)
    account_id_a = account_a["account_id"]
    account_id_b = account_b["account_id"]

    # Insert distinct recognisable amounts for each account.
    fun_insert_tx(account_id_a, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1)
    fun_insert_tx(account_id_b, "CREDIT", AMOUNT_500, AMOUNT_500, TS_DATE_B_1)

    result = fun_statement_module.fun_get_statement(account_id_a)

    assert result["ok"] is True
    rows = result["rows"]
    assert len(rows) == 1, (
        f"Expected 1 row for account A, got {len(rows)}: {rows}"
    )
    assert Decimal(str(rows[0]["amount"])) == AMOUNT_100, (
        "Account A's statement must only contain its own transaction (amount=100)"
    )


def test_ac5_account_b_transactions_not_in_account_a_statement(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-5: Transactions inserted for account B do not appear when querying account A."""
    user_id_a = fun_make_user(username="stmt_ua", email="stmt_ua@example.com")
    user_id_b = fun_make_user(username="stmt_ub", email="stmt_ub@example.com")
    account_a = fun_make_account(user_id_a)
    account_b = fun_make_account(user_id_b)
    account_id_a = account_a["account_id"]
    account_id_b = account_b["account_id"]

    # Only insert transactions for account B; account A should have none.
    fun_insert_tx(account_id_b, "CREDIT", AMOUNT_300, AMOUNT_300, TS_DATE_A_1)
    fun_insert_tx(account_id_b, "DEBIT", AMOUNT_100, AMOUNT_200, TS_DATE_B_1)

    result = fun_statement_module.fun_get_statement(account_id_a)

    assert result["ok"] is True
    assert result["rows"] == [], (
        f"Account A must have no rows when only account B has transactions; "
        f"got {result['rows']}"
    )


def test_ac5_account_a_transactions_not_in_account_b_statement(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-5: Transactions for account A do not leak into account B's statement."""
    user_id_a = fun_make_user(username="stmt_uc", email="stmt_uc@example.com")
    user_id_b = fun_make_user(username="stmt_ud", email="stmt_ud@example.com")
    account_a = fun_make_account(user_id_a)
    account_b = fun_make_account(user_id_b)
    account_id_a = account_a["account_id"]
    account_id_b = account_b["account_id"]

    fun_insert_tx(account_id_a, "CREDIT", AMOUNT_200, AMOUNT_200, TS_DATE_A_1)
    fun_insert_tx(account_id_a, "CREDIT", AMOUNT_400, Decimal("600.00"), TS_DATE_A_2)

    result = fun_statement_module.fun_get_statement(account_id_b)

    assert result["ok"] is True
    assert result["rows"] == [], (
        f"Account B must have no rows when only account A has transactions; "
        f"got {result['rows']}"
    )


def test_ac5_each_account_sees_only_its_own_transaction_count(
    fun_statement_module, fun_make_user, fun_make_account
):
    """AC-5: After inserting different numbers of transactions for two accounts, each account's
    statement returns only its own count."""
    user_id_a = fun_make_user(username="stmt_ue", email="stmt_ue@example.com")
    user_id_b = fun_make_user(username="stmt_uf", email="stmt_uf@example.com")
    account_a = fun_make_account(user_id_a)
    account_b = fun_make_account(user_id_b)
    account_id_a = account_a["account_id"]
    account_id_b = account_b["account_id"]

    # 3 transactions for A, 1 for B.
    fun_insert_tx(account_id_a, "CREDIT", AMOUNT_100, AMOUNT_100, TS_DATE_A_1)
    fun_insert_tx(account_id_a, "CREDIT", AMOUNT_100, AMOUNT_200, TS_DATE_A_2)
    fun_insert_tx(account_id_a, "DEBIT", AMOUNT_100, AMOUNT_100, TS_DATE_B_1)
    fun_insert_tx(account_id_b, "CREDIT", AMOUNT_500, AMOUNT_500, TS_DATE_C_1)

    result_a = fun_statement_module.fun_get_statement(account_id_a)
    result_b = fun_statement_module.fun_get_statement(account_id_b)

    assert result_a["ok"] is True
    assert result_b["ok"] is True
    assert len(result_a["rows"]) == 3, (
        f"Account A should have 3 rows, got {len(result_a['rows'])}"
    )
    assert len(result_b["rows"]) == 1, (
        f"Account B should have 1 row, got {len(result_b['rows'])}"
    )
