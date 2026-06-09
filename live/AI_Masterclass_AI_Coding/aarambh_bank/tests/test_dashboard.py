"""
Tests for the dashboard feature (src/features/dashboard.py).

Covers every acceptance criterion in specs/dashboard.md:
  AC-1  fun_get_dashboard_data returns data for an authenticated user;
        returns None (or raises) for an invalid user_id.
  AC-2  Returned dict contains username, masked_account_number, balance,
        phone, and email for the logged-in user.
  AC-3  recent_transactions contains the last 5 transactions, newest first.
  AC-4  Returned dict contains all keys needed for navigation links
        (deposit, withdraw, statement, chat).
  AC-5  After a deposit or withdrawal the new balance and transaction appear
        in the next call to fun_get_dashboard_data.
  AC-6  masked_account_number contains '*' characters, ends with the last 4
        digits of the real account number, and never equals the full number.

Edge cases covered:
  - User with account but zero transactions: recent_transactions is an empty
    list, not an error.
  - User with exactly 5 transactions: all 5 are returned.
  - User with more than 5 transactions: only the 5 newest are returned.
  - User with no account: fun_get_dashboard_data returns None.
"""

import importlib
import os
import sys
from datetime import datetime, timedelta
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

TEST_USERNAME = "dash_user"
TEST_EMAIL = "dash_user@example.com"
TEST_PHONE = "9123456780"
TEST_PASSWORD_HASH = "$2b$12$placeholderhashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

REQUIRED_DICT_KEYS = {
    "username",
    "email",
    "phone",
    "masked_account_number",
    "balance",
    "recent_transactions",
}

# Number of recent transactions the dashboard must show.
RECENT_TX_LIMIT = 5


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
    """Truncate all tables before every test in FK-safe order.

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
# Module fixture: lazily import dashboard feature after DB env is set.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fun_dashboard():
    """Return the dashboard feature module so tests can call feature functions.

    Returns:
        module: src.features.dashboard
    """
    return importlib.import_module("src.features.dashboard")


@pytest.fixture(scope="session")
def fun_account_module():
    """Return the account feature module for use in helper fixtures.

    Returns:
        module: src.features.account
    """
    return importlib.import_module("src.features.account")


# ---------------------------------------------------------------------------
# Helper fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def fun_make_user():
    """Factory fixture: insert a minimal user row via raw SQL, return user_id.

    Returns a callable fun_insert(username, email) -> int that inserts a row
    into the users table without depending on the auth feature.

    Returns:
        callable: fun_insert(username, email) -> int
    """
    def fun_insert(
        username: str = TEST_USERNAME,
        email: str = TEST_EMAIL,
        phone: str = TEST_PHONE,
    ) -> int:
        """Insert a minimal user row and return its generated id.

        Args:
            username: Username for the new row.
            email:    Email for the new row.
            phone:    Phone number for the new row.

        Returns:
            int: Auto-increment id of the inserted row.
        """
        conn = fun_get_test_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, email, phone, password_hash) "
            "VALUES (%s, %s, %s, %s)",
            (username, email, phone, TEST_PASSWORD_HASH),
        )
        conn.commit()
        user_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return user_id

    return fun_insert


@pytest.fixture
def fun_make_account(fun_account_module):
    """Factory fixture: call fun_create_account and return account dict.

    Returns a callable fun_open(user_id) -> dict{account_id, account_number}.

    Args:
        fun_account_module: The account feature module (injected by pytest).

    Returns:
        callable: fun_open(user_id) -> dict
    """
    def fun_open(user_id: int) -> dict:
        """Create an account for user_id and return {account_id, account_number}.

        Args:
            user_id: The user to create an account for.

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


@pytest.fixture
def fun_insert_tx():
    """Factory fixture: insert a transaction row directly via raw SQL.

    Returns a callable that accepts all transaction fields and returns the
    generated transaction id. Uses raw SQL to avoid coupling tests to any
    deposit/withdraw feature implementation.

    Returns:
        callable: fun_insert(account_id, tx_type, amount, category, note,
                             created_at, balance_after) -> int
    """
    def fun_insert(
        account_id: int,
        tx_type: str,
        amount: Decimal,
        category: str,
        note: str,
        created_at: datetime,
        balance_after: Decimal,
    ) -> int:
        """Insert one transaction row and return its auto-increment id.

        Args:
            account_id:    FK to accounts.id.
            tx_type:       'CREDIT' or 'DEBIT'.
            amount:        Transaction amount as Decimal.
            category:      Category string (nullable).
            note:          Note string (nullable).
            created_at:    Explicit timestamp for ordering tests.
            balance_after: Account balance after this transaction as Decimal.

        Returns:
            int: The auto-increment id of the inserted row.
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

    return fun_insert


# ===========================================================================
# AC-1 (FR-DASH-01): fun_get_dashboard_data returns data for authenticated
#   user; returns None for invalid / non-existent user_id.
# ===========================================================================


def test_ac1_dashboard_returns_dict_for_valid_user(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-1: fun_get_dashboard_data returns a dict (not None) for a valid user with an account."""
    user_id = fun_make_user()
    fun_make_account(user_id)

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None, (
        "Expected a dict for a valid authenticated user, got None"
    )
    assert isinstance(result, dict)


def test_ac1_dashboard_returns_none_for_nonexistent_user_id(fun_dashboard):
    """AC-1: fun_get_dashboard_data returns None when the user_id does not exist."""
    result = fun_dashboard.fun_get_dashboard_data(999999)

    assert result is None, (
        "Expected None for an invalid/non-existent user_id, got a non-None value"
    )


def test_ac1_dashboard_returns_none_for_zero_user_id(fun_dashboard):
    """AC-1: fun_get_dashboard_data returns None for user_id=0 (invalid)."""
    result = fun_dashboard.fun_get_dashboard_data(0)

    assert result is None


def test_ac1_dashboard_returns_none_for_negative_user_id(fun_dashboard):
    """AC-1: fun_get_dashboard_data returns None for a negative user_id."""
    result = fun_dashboard.fun_get_dashboard_data(-1)

    assert result is None


# ===========================================================================
# AC-2 (FR-DASH-02): Returned dict contains name, masked_account_number,
#   balance, phone, and email.
# ===========================================================================


def test_ac2_result_contains_all_required_keys(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-2: fun_get_dashboard_data result contains all required top-level keys."""
    user_id = fun_make_user()
    fun_make_account(user_id)

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    for key in REQUIRED_DICT_KEYS:
        assert key in result, f"Required key '{key}' missing from dashboard data"


def test_ac2_username_matches_registered_value(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-2: The 'username' field matches the name stored at registration."""
    user_id = fun_make_user(username="dashtest_alice", email="dashtest_alice@example.com")
    fun_make_account(user_id)

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    assert result["username"] == "dashtest_alice"


def test_ac2_email_matches_registered_value(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-2: The 'email' field matches the email stored at registration."""
    user_id = fun_make_user(
        username="dashtest_bob", email="dashtest_bob@example.com"
    )
    fun_make_account(user_id)

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    assert result["email"] == "dashtest_bob@example.com"


def test_ac2_phone_matches_registered_value(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-2: The 'phone' field matches the phone stored at registration."""
    user_id = fun_make_user(
        username="dashtest_carol",
        email="dashtest_carol@example.com",
        phone="9000000099",
    )
    fun_make_account(user_id)

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    assert result["phone"] == "9000000099"


def test_ac2_balance_is_decimal_zero_for_new_account(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-2: balance is Decimal('0.00') for a newly opened account with no transactions."""
    user_id = fun_make_user()
    fun_make_account(user_id)

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    assert isinstance(result["balance"], Decimal), (
        f"balance must be Decimal, got {type(result['balance']).__name__}"
    )
    assert result["balance"] == Decimal("0.00")


def test_ac2_balance_is_not_float(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-2: balance is never a float (golden rule: money is Decimal)."""
    user_id = fun_make_user()
    fun_make_account(user_id)

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    assert not isinstance(result["balance"], float), (
        "balance must NOT be float — use Decimal"
    )


# ===========================================================================
# AC-3 (FR-DASH-03): recent_transactions contains up to 5 transactions,
#   newest first.
# ===========================================================================


def test_ac3_no_transactions_returns_empty_list(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-3 / edge case: A user with zero transactions gets an empty list, not an error."""
    user_id = fun_make_user()
    fun_make_account(user_id)

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    assert isinstance(result["recent_transactions"], list)
    assert len(result["recent_transactions"]) == 0


def test_ac3_exactly_five_transactions_all_returned(
    fun_dashboard, fun_make_user, fun_make_account, fun_insert_tx
):
    """AC-3 / edge case: Exactly 5 transactions — all 5 are returned."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    base_time = datetime(2026, 1, 1, 10, 0, 0)
    for i in range(5):
        fun_insert_tx(
            account_id=account_id,
            tx_type="CREDIT",
            amount=Decimal("100.00"),
            category="Salary",
            note=f"tx {i + 1}",
            created_at=base_time + timedelta(seconds=i),
            balance_after=Decimal(f"{(i + 1) * 100}.00"),
        )

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    assert len(result["recent_transactions"]) == 5


def test_ac3_more_than_five_transactions_only_five_newest_returned(
    fun_dashboard, fun_make_user, fun_make_account, fun_insert_tx
):
    """AC-3 / edge case: 7 transactions inserted — only the 5 newest are returned."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    base_time = datetime(2026, 1, 1, 10, 0, 0)
    for i in range(7):
        fun_insert_tx(
            account_id=account_id,
            tx_type="CREDIT",
            amount=Decimal("50.00"),
            category="Test",
            note=f"tx {i + 1}",
            created_at=base_time + timedelta(seconds=i),
            balance_after=Decimal(f"{(i + 1) * 50}.00"),
        )

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    txs = result["recent_transactions"]
    assert len(txs) == RECENT_TX_LIMIT, (
        f"Expected {RECENT_TX_LIMIT} transactions, got {len(txs)}"
    )


def test_ac3_transactions_are_ordered_newest_first(
    fun_dashboard, fun_make_user, fun_make_account, fun_insert_tx
):
    """AC-3: Returned transactions are sorted newest (highest created_at) first."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    base_time = datetime(2026, 2, 1, 9, 0, 0)
    for i in range(7):
        fun_insert_tx(
            account_id=account_id,
            tx_type="CREDIT",
            amount=Decimal("10.00"),
            category="Order",
            note=f"seq {i}",
            created_at=base_time + timedelta(seconds=i * 10),
            balance_after=Decimal(f"{(i + 1) * 10}.00"),
        )

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    txs = result["recent_transactions"]
    assert len(txs) == RECENT_TX_LIMIT

    # Verify descending order of created_at.
    timestamps = [tx["created_at"] for tx in txs]
    assert timestamps == sorted(timestamps, reverse=True), (
        "recent_transactions must be ordered newest first (descending created_at)"
    )


def test_ac3_oldest_two_transactions_excluded_when_seven_exist(
    fun_dashboard, fun_make_user, fun_make_account, fun_insert_tx
):
    """AC-3: When 7 transactions exist the 2 oldest notes do not appear in the result."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    base_time = datetime(2026, 3, 1, 8, 0, 0)
    notes = [f"note_{i}" for i in range(7)]
    for i, note in enumerate(notes):
        fun_insert_tx(
            account_id=account_id,
            tx_type="CREDIT",
            amount=Decimal("20.00"),
            category="Test",
            note=note,
            created_at=base_time + timedelta(seconds=i),
            balance_after=Decimal(f"{(i + 1) * 20}.00"),
        )

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    returned_notes = [tx["note"] for tx in result["recent_transactions"]]

    # Oldest two (index 0 and 1) must NOT be present.
    assert "note_0" not in returned_notes, "Oldest transaction must be excluded"
    assert "note_1" not in returned_notes, "Second oldest transaction must be excluded"

    # Newest five (index 2..6) MUST be present.
    for i in range(2, 7):
        assert f"note_{i}" in returned_notes, (
            f"Transaction note_{i} should be in the 5 newest"
        )


def test_ac3_transaction_dict_contains_required_fields(
    fun_dashboard, fun_make_user, fun_make_account, fun_insert_tx
):
    """AC-3: Each transaction dict contains at minimum type, amount, and created_at."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(
        account_id=account_id,
        tx_type="DEBIT",
        amount=Decimal("75.00"),
        category="Shopping",
        note="test purchase",
        created_at=datetime(2026, 4, 1, 12, 0, 0),
        balance_after=Decimal("925.00"),
    )

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    txs = result["recent_transactions"]
    assert len(txs) == 1

    tx = txs[0]
    for field in ("type", "amount", "created_at"):
        assert field in tx, f"Transaction dict missing required field: '{field}'"


def test_ac3_transaction_amount_is_decimal_not_float(
    fun_dashboard, fun_make_user, fun_make_account, fun_insert_tx
):
    """AC-3: amount in each transaction dict is Decimal, never float."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    fun_insert_tx(
        account_id=account_id,
        tx_type="CREDIT",
        amount=Decimal("250.50"),
        category="Transfer",
        note="decimal check",
        created_at=datetime(2026, 4, 2, 10, 0, 0),
        balance_after=Decimal("250.50"),
    )

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    tx = result["recent_transactions"][0]
    assert isinstance(tx["amount"], Decimal), (
        f"Transaction amount must be Decimal, got {type(tx['amount']).__name__}"
    )
    assert not isinstance(tx["amount"], float), "Transaction amount must NOT be float"


# ===========================================================================
# AC-4 (FR-DASH-04): Returned dict contains all keys required to render
#   navigation (deposit, withdraw, statement, chat).
# ===========================================================================


def test_ac4_result_dict_has_all_required_keys_for_navigation(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-4: fun_get_dashboard_data result dict contains all keys the UI needs to render."""
    user_id = fun_make_user()
    fun_make_account(user_id)

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    # All keys required for the UI to render the full dashboard including nav.
    for key in REQUIRED_DICT_KEYS:
        assert key in result, (
            f"Key '{key}' missing — UI cannot render navigation without it"
        )


def test_ac4_result_is_a_mapping_not_a_list(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-4: fun_get_dashboard_data returns a dict (mapping), not a list or scalar."""
    user_id = fun_make_user()
    fun_make_account(user_id)

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert isinstance(result, dict), (
        f"Expected dict, got {type(result).__name__}"
    )


# ===========================================================================
# AC-5 (FR-DASH-05): After a deposit/withdrawal the balance and recent
#   transactions update in the next call.
# ===========================================================================


def test_ac5_new_transaction_appears_in_subsequent_call(
    fun_dashboard, fun_make_user, fun_make_account, fun_insert_tx
):
    """AC-5: A transaction inserted after the first call appears in the second call."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    # First call — no transactions yet.
    result_before = fun_dashboard.fun_get_dashboard_data(user_id)
    assert result_before is not None
    assert len(result_before["recent_transactions"]) == 0

    # Insert a deposit and update the account balance via raw SQL.
    deposit_amount = Decimal("500.00")
    new_balance = Decimal("500.00")
    fun_insert_tx(
        account_id=account_id,
        tx_type="CREDIT",
        amount=deposit_amount,
        category="Deposit",
        note="first deposit",
        created_at=datetime(2026, 5, 1, 11, 0, 0),
        balance_after=new_balance,
    )
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE accounts SET balance = %s WHERE id = %s",
        (str(new_balance), account_id),
    )
    conn.commit()
    cursor.close()
    conn.close()

    # Second call — must reflect the inserted transaction.
    result_after = fun_dashboard.fun_get_dashboard_data(user_id)
    assert result_after is not None
    assert len(result_after["recent_transactions"]) == 1


def test_ac5_balance_updates_after_transaction_insert(
    fun_dashboard, fun_make_user, fun_make_account, fun_insert_tx
):
    """AC-5: balance in the returned dict reflects the updated account balance."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    result_before = fun_dashboard.fun_get_dashboard_data(user_id)
    assert result_before is not None
    assert result_before["balance"] == Decimal("0.00")

    new_balance = Decimal("1500.00")
    fun_insert_tx(
        account_id=account_id,
        tx_type="CREDIT",
        amount=Decimal("1500.00"),
        category="Salary",
        note="monthly salary",
        created_at=datetime(2026, 5, 2, 9, 0, 0),
        balance_after=new_balance,
    )
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE accounts SET balance = %s WHERE id = %s",
        (str(new_balance), account_id),
    )
    conn.commit()
    cursor.close()
    conn.close()

    result_after = fun_dashboard.fun_get_dashboard_data(user_id)
    assert result_after is not None
    assert result_after["balance"] == Decimal("1500.00"), (
        f"Expected Decimal('1500.00'), got {result_after['balance']!r}"
    )


def test_ac5_updated_balance_is_decimal_not_float(
    fun_dashboard, fun_make_user, fun_make_account, fun_insert_tx
):
    """AC-5: balance after a transaction update is still Decimal, never float."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    new_balance = Decimal("300.00")
    fun_insert_tx(
        account_id=account_id,
        tx_type="CREDIT",
        amount=new_balance,
        category="Test",
        note="decimal type check",
        created_at=datetime(2026, 5, 3, 14, 0, 0),
        balance_after=new_balance,
    )
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE accounts SET balance = %s WHERE id = %s",
        (str(new_balance), account_id),
    )
    conn.commit()
    cursor.close()
    conn.close()

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    assert isinstance(result["balance"], Decimal), (
        f"balance must be Decimal after update, got {type(result['balance']).__name__}"
    )
    assert not isinstance(result["balance"], float)


def test_ac5_withdrawal_reduces_balance_in_subsequent_call(
    fun_dashboard, fun_make_user, fun_make_account, fun_insert_tx
):
    """AC-5: A DEBIT transaction and updated balance are reflected in the next call."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    account_id = account["account_id"]

    # Seed an initial balance via raw SQL.
    initial_balance = Decimal("2000.00")
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE accounts SET balance = %s WHERE id = %s",
        (str(initial_balance), account_id),
    )
    conn.commit()
    cursor.close()
    conn.close()

    # Insert a withdrawal.
    withdrawal_amount = Decimal("400.00")
    balance_after_withdrawal = Decimal("1600.00")
    fun_insert_tx(
        account_id=account_id,
        tx_type="DEBIT",
        amount=withdrawal_amount,
        category="ATM",
        note="cash withdrawal",
        created_at=datetime(2026, 5, 4, 15, 0, 0),
        balance_after=balance_after_withdrawal,
    )
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE accounts SET balance = %s WHERE id = %s",
        (str(balance_after_withdrawal), account_id),
    )
    conn.commit()
    cursor.close()
    conn.close()

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    assert result["balance"] == Decimal("1600.00")
    assert len(result["recent_transactions"]) == 1
    assert result["recent_transactions"][0]["type"] == "DEBIT"


# ===========================================================================
# AC-6 (FR-ACC-04 / NFR-03): masked_account_number shows only last 4 digits.
# ===========================================================================


def test_ac6_masked_account_number_contains_stars(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-6: masked_account_number contains at least one '*' character."""
    user_id = fun_make_user()
    fun_make_account(user_id)

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    masked = result["masked_account_number"]
    assert "*" in masked, (
        f"masked_account_number must contain '*' characters, got: '{masked}'"
    )


def test_ac6_masked_account_number_ends_with_last_four_digits(
    fun_dashboard, fun_make_user, fun_make_account, fun_account_module
):
    """AC-6: masked_account_number ends with the last 4 digits of the real account number."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    real_account_number = account["account_number"]

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    masked = result["masked_account_number"]
    assert masked.endswith(real_account_number[-4:]), (
        f"Masked '{masked}' does not end with last 4 of '{real_account_number}'"
    )


def test_ac6_masked_account_number_does_not_equal_full_number(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-6: masked_account_number never equals the full unmasked account number."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    real_account_number = account["account_number"]

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    masked = result["masked_account_number"]
    # Only meaningful when account number is longer than 4 digits (always true here).
    if len(real_account_number) > 4:
        assert masked != real_account_number, (
            "masked_account_number must never equal the full account number"
        )


def test_ac6_masked_account_number_prefix_is_all_stars(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-6: Every character before the last 4 in masked_account_number is '*'."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    real_account_number = account["account_number"]

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    masked = result["masked_account_number"]
    prefix = masked[: len(real_account_number) - 4]
    assert all(ch == "*" for ch in prefix), (
        f"Prefix of masked number must be all '*', got: '{prefix}'"
    )


def test_ac6_masked_length_equals_full_account_number_length(
    fun_dashboard, fun_make_user, fun_make_account
):
    """AC-6: Length of masked_account_number equals length of the full account number."""
    user_id = fun_make_user()
    account = fun_make_account(user_id)
    real_account_number = account["account_number"]

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    masked = result["masked_account_number"]
    assert len(masked) == len(real_account_number), (
        f"Masked length {len(masked)} != real length {len(real_account_number)}"
    )


# ===========================================================================
# Edge cases
# ===========================================================================


def test_edge_user_with_no_account_returns_none(fun_dashboard, fun_make_user):
    """Edge case: A user who exists but has no account gets None from fun_get_dashboard_data."""
    user_id = fun_make_user()

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is None, (
        "A user with no account must receive None, not a partial dict"
    )


def test_edge_zero_transactions_recent_transactions_is_list(
    fun_dashboard, fun_make_user, fun_make_account
):
    """Edge case: recent_transactions is an empty list (not None, not error) for zero txs."""
    user_id = fun_make_user()
    fun_make_account(user_id)

    result = fun_dashboard.fun_get_dashboard_data(user_id)

    assert result is not None
    assert result["recent_transactions"] is not None, (
        "recent_transactions must be a list, not None"
    )
    assert isinstance(result["recent_transactions"], list)


def test_edge_data_is_scoped_to_requesting_user(
    fun_dashboard, fun_make_user, fun_make_account, fun_insert_tx
):
    """Edge case / AC-7 scoping: Two users each only see their own data."""
    user_id_a = fun_make_user(
        username="scope_user_a", email="scope_a@example.com"
    )
    user_id_b = fun_make_user(
        username="scope_user_b", email="scope_b@example.com"
    )
    account_a = fun_make_account(user_id_a)
    account_b = fun_make_account(user_id_b)

    # Insert transactions only for user A.
    fun_insert_tx(
        account_id=account_a["account_id"],
        tx_type="CREDIT",
        amount=Decimal("999.00"),
        category="Scope",
        note="only user A",
        created_at=datetime(2026, 6, 1, 10, 0, 0),
        balance_after=Decimal("999.00"),
    )

    result_a = fun_dashboard.fun_get_dashboard_data(user_id_a)
    result_b = fun_dashboard.fun_get_dashboard_data(user_id_b)

    assert result_a is not None
    assert result_b is not None

    # User A sees their transaction; user B sees none.
    assert len(result_a["recent_transactions"]) == 1
    assert len(result_b["recent_transactions"]) == 0

    # Usernames are correctly scoped.
    assert result_a["username"] == "scope_user_a"
    assert result_b["username"] == "scope_user_b"
