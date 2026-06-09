"""
Tests for the account feature (src/features/account.py).

Covers every acceptance criterion in specs/account.md:
  AC-1  A user with no account can create one; exactly one accounts row is
        created for that user.
  AC-2  A new account has a unique account_number and balance = 0.00
        (as Decimal).
  AC-3  A user who already has an account cannot create a second; no extra row
        is created (enforced by the UNIQUE constraint and in code).
  AC-4  The account number is displayed masked except the last 4 digits and is
        never written to logs.

Edge cases covered:
  - Concurrent/duplicate open attempt: second call returns ok=False, only one
    row exists (AC-3 / UNIQUE constraint handling).
  - account_number shorter than 4 characters raises ValueError in masking.
  - fun_create_account does not log the full account number (AC-4 / PII rule).
"""

import importlib
import logging
import os
import sys
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

TEST_USERNAME_A = "acctuser_a"
TEST_USERNAME_B = "acctuser_b"
TEST_EMAIL_A = "acctuser_a@example.com"
TEST_EMAIL_B = "acctuser_b@example.com"
TEST_PHONE = "9876543210"
TEST_PASSWORD_HASH = "$2b$12$placeholderhashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

MASK_SAMPLE_NUMBER = "1234567890"
MASK_EXPECTED_RESULT = "******7890"
MASK_EXACT_FOUR = "4321"
MASK_THREE_CHARS = "123"


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


def fun_count_accounts_for_user(user_id: int) -> int:
    """Return the number of accounts rows for the given user_id.

    Args:
        user_id: The user whose account rows are to be counted.

    Returns:
        int: Row count (expected to be 0 or 1 in normal operation).
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM accounts WHERE user_id = %s", (user_id,)
    )
    (count,) = cursor.fetchone()
    cursor.close()
    conn.close()
    return count


def fun_count_all_accounts() -> int:
    """Return the total number of rows in the accounts table.

    Returns:
        int: Total account row count.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM accounts")
    (count,) = cursor.fetchone()
    cursor.close()
    conn.close()
    return count


def fun_fetch_account_row(user_id: int) -> dict | None:
    """Fetch the accounts row for the given user_id.

    Args:
        user_id: The user whose account row is to be fetched.

    Returns:
        dict with column values, or None if no row found.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM accounts WHERE user_id = %s", (user_id,)
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


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
# Helper fixture: insert a minimal user row and return its id.
# ---------------------------------------------------------------------------


@pytest.fixture
def fun_make_user():
    """Factory fixture that inserts a minimal user row directly via SQL.

    Account tests need a real user_id FK but must not depend on the auth
    feature.  Returns a callable that accepts (username, email) and returns
    the auto-generated user id.

    Returns:
        callable: fun_insert(username, email) -> int
    """
    def fun_insert(username: str = TEST_USERNAME_A, email: str = TEST_EMAIL_A) -> int:
        """Insert a minimal user row and return its generated id.

        Args:
            username: Username for the new user row.
            email:    Email for the new user row.

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


# ---------------------------------------------------------------------------
# Module fixture: lazily import account feature after DB env is set.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fun_account():
    """Return the account feature module so tests can call feature functions.

    Returns:
        module: src.features.account
    """
    return importlib.import_module("src.features.account")


# ---------------------------------------------------------------------------
# Log-capture helpers (reused from auth tests pattern).
# ---------------------------------------------------------------------------


class _LogCapture(logging.Handler):
    """Custom log handler that records all emitted log records.

    Used to inspect log output for PII leakage (account number).
    """

    def __init__(self):
        """Initialise the handler with an empty records list."""
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Append each emitted log record to self.records.

        Args:
            record: The log record emitted by a logger.
        """
        self.records.append(record)

    def fun_all_messages(self) -> list[str]:
        """Return a list of all formatted log messages captured so far.

        Returns:
            list[str]: Formatted log message strings.
        """
        return [self.format(r) for r in self.records]


def fun_attach_log_capture() -> _LogCapture:
    """Attach a _LogCapture handler to the root logger and return it.

    Returns:
        _LogCapture: The handler instance now collecting log output.
    """
    handler = _LogCapture()
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)
    return handler


def fun_detach_log_capture(handler: _LogCapture) -> None:
    """Remove the given _LogCapture handler from the root logger.

    Args:
        handler: The handler instance to remove.
    """
    logging.getLogger().removeHandler(handler)


# ===========================================================================
# AC-1: A user with no account can create one; exactly one accounts row is
#        created for that user.
# ===========================================================================


def test_ac1_create_account_returns_ok_true(fun_account, fun_make_user):
    """AC-1: fun_create_account returns ok=True for a user with no account."""
    user_id = fun_make_user()
    result = fun_account.fun_create_account(user_id)

    assert result["ok"] is True, f"Expected ok=True, got: {result}"


def test_ac1_create_account_inserts_exactly_one_row(fun_account, fun_make_user):
    """AC-1: After fun_create_account succeeds, exactly one accounts row exists for that user."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)

    assert fun_count_accounts_for_user(user_id) == 1


def test_ac1_result_contains_account_id_and_number(fun_account, fun_make_user):
    """AC-1: Successful result dict contains non-None account_id and account_number."""
    user_id = fun_make_user()
    result = fun_account.fun_create_account(user_id)

    assert result["ok"] is True
    assert result.get("account_id") is not None, "account_id missing from result"
    assert isinstance(result["account_id"], int)
    assert result["account_id"] > 0
    assert result.get("account_number"), "account_number missing or empty in result"


def test_ac1_get_account_returns_row_after_creation(fun_account, fun_make_user):
    """AC-1: fun_get_account returns a dict (not None) after an account is created."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)

    account = fun_account.fun_get_account(user_id)

    assert account is not None, "Expected a dict, got None"
    assert account["user_id"] == user_id


def test_ac1_get_account_returns_none_before_creation(fun_account, fun_make_user):
    """AC-1: fun_get_account returns None for a user who has no account yet."""
    user_id = fun_make_user()

    account = fun_account.fun_get_account(user_id)

    assert account is None


def test_ac1_total_accounts_table_has_one_row(fun_account, fun_make_user):
    """AC-1: The accounts table contains exactly one row after a single creation."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)

    assert fun_count_all_accounts() == 1


# ===========================================================================
# AC-2: A new account has a unique account_number and balance = 0.00
#        (as Decimal).
# ===========================================================================


def test_ac2_initial_balance_is_decimal_zero(fun_account, fun_make_user):
    """AC-2: The balance returned by fun_get_account is Decimal('0.00'), not float."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)

    account = fun_account.fun_get_account(user_id)

    assert account is not None
    balance = account["balance"]
    assert isinstance(balance, Decimal), (
        f"balance must be Decimal, got {type(balance).__name__}"
    )
    assert balance == Decimal("0.00"), f"Expected Decimal('0.00'), got {balance!r}"


def test_ac2_balance_is_not_float(fun_account, fun_make_user):
    """AC-2: The balance field is never a float (golden rule: money is Decimal)."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)

    account = fun_account.fun_get_account(user_id)

    assert not isinstance(account["balance"], float), (
        "balance must NOT be float — use Decimal"
    )


def test_ac2_account_number_is_non_empty_string(fun_account, fun_make_user):
    """AC-2: The account_number in the DB row is a non-empty string."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)

    account = fun_account.fun_get_account(user_id)

    assert account is not None
    assert isinstance(account["account_number"], str)
    assert len(account["account_number"]) > 0


def test_ac2_two_users_get_different_account_numbers(fun_account, fun_make_user):
    """AC-2: Two different users receive distinct account_number values."""
    user_id_a = fun_make_user(TEST_USERNAME_A, TEST_EMAIL_A)
    user_id_b = fun_make_user(TEST_USERNAME_B, TEST_EMAIL_B)

    fun_account.fun_create_account(user_id_a)
    fun_account.fun_create_account(user_id_b)

    account_a = fun_account.fun_get_account(user_id_a)
    account_b = fun_account.fun_get_account(user_id_b)

    assert account_a is not None
    assert account_b is not None
    assert account_a["account_number"] != account_b["account_number"], (
        "Two different users must not share the same account_number"
    )


def test_ac2_two_users_both_have_zero_balance(fun_account, fun_make_user):
    """AC-2: Every newly created account has balance = Decimal('0.00')."""
    user_id_a = fun_make_user(TEST_USERNAME_A, TEST_EMAIL_A)
    user_id_b = fun_make_user(TEST_USERNAME_B, TEST_EMAIL_B)

    fun_account.fun_create_account(user_id_a)
    fun_account.fun_create_account(user_id_b)

    account_a = fun_account.fun_get_account(user_id_a)
    account_b = fun_account.fun_get_account(user_id_b)

    assert account_a["balance"] == Decimal("0.00")
    assert account_b["balance"] == Decimal("0.00")


def test_ac2_db_row_balance_stored_correctly(fun_account, fun_make_user):
    """AC-2: The raw DB row for a new account also records balance = 0.00."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)

    row = fun_fetch_account_row(user_id)

    assert row is not None
    assert row["balance"] == Decimal("0.00")


# ===========================================================================
# AC-3: A user who already has an account cannot create a second; no extra row
#        is created (enforced by UNIQUE constraint and in code).
# ===========================================================================


def test_ac3_second_create_returns_ok_false(fun_account, fun_make_user):
    """AC-3: Calling fun_create_account a second time for the same user returns ok=False."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)

    result = fun_account.fun_create_account(user_id)

    assert result["ok"] is False, (
        f"Expected ok=False on duplicate create, got: {result}"
    )


def test_ac3_second_create_includes_error_message(fun_account, fun_make_user):
    """AC-3: The rejection result from a duplicate create contains a non-empty error string."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)

    result = fun_account.fun_create_account(user_id)

    assert result.get("error"), "Expected a non-empty error message in rejection result"


def test_ac3_only_one_row_exists_after_two_attempts(fun_account, fun_make_user):
    """AC-3: After two fun_create_account calls for the same user, exactly one row exists."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)
    fun_account.fun_create_account(user_id)

    assert fun_count_accounts_for_user(user_id) == 1, (
        "Duplicate create must not insert a second row"
    )


def test_ac3_total_table_count_stays_one_after_duplicate(fun_account, fun_make_user):
    """AC-3: The total accounts table count is still 1 after a duplicate attempt."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)
    fun_account.fun_create_account(user_id)

    assert fun_count_all_accounts() == 1


def test_ac3_first_create_still_ok_after_second_attempt(fun_account, fun_make_user):
    """AC-3: The originally created account row is unaffected by the rejected second attempt."""
    user_id = fun_make_user()
    first_result = fun_account.fun_create_account(user_id)
    fun_account.fun_create_account(user_id)  # should be rejected

    account = fun_account.fun_get_account(user_id)

    assert account is not None
    assert account["account_number"] == first_result["account_number"]
    assert account["balance"] == Decimal("0.00")


def test_ac3_multiple_duplicate_attempts_still_one_row(fun_account, fun_make_user):
    """AC-3 edge: Three creation attempts for the same user still yield exactly one row."""
    user_id = fun_make_user()
    for _ in range(3):
        fun_account.fun_create_account(user_id)

    assert fun_count_accounts_for_user(user_id) == 1


def test_ac3_different_user_can_create_after_first_user(fun_account, fun_make_user):
    """AC-3: A second distinct user is still allowed to create their own account."""
    user_id_a = fun_make_user(TEST_USERNAME_A, TEST_EMAIL_A)
    user_id_b = fun_make_user(TEST_USERNAME_B, TEST_EMAIL_B)

    fun_account.fun_create_account(user_id_a)
    result_b = fun_account.fun_create_account(user_id_b)

    assert result_b["ok"] is True, (
        "A different user must be able to open their own account"
    )
    assert fun_count_accounts_for_user(user_id_a) == 1
    assert fun_count_accounts_for_user(user_id_b) == 1


# ===========================================================================
# AC-4: The account number is displayed masked except the last 4 digits and is
#        never written to logs.
# ===========================================================================


def test_ac4_mask_ten_digit_number(fun_account):
    """AC-4: fun_mask_account_number('1234567890') returns '******7890'."""
    result = fun_account.fun_mask_account_number(MASK_SAMPLE_NUMBER)

    assert result == MASK_EXPECTED_RESULT, (
        f"Expected '{MASK_EXPECTED_RESULT}', got '{result}'"
    )


def test_ac4_mask_preserves_last_four_digits(fun_account):
    """AC-4: The last 4 characters of the account number are never masked."""
    account_number = "9988776655"
    result = fun_account.fun_mask_account_number(account_number)

    assert result.endswith("6655"), (
        f"Last 4 digits must be visible, got: '{result}'"
    )


def test_ac4_mask_replaces_leading_digits_with_stars(fun_account):
    """AC-4: All digits except the last 4 are replaced with '*'."""
    account_number = "1234567890"
    result = fun_account.fun_mask_account_number(account_number)
    prefix = result[: len(account_number) - 4]

    assert all(ch == "*" for ch in prefix), (
        f"All non-trailing digits must be '*', prefix was: '{prefix}'"
    )


def test_ac4_mask_exactly_four_chars_returns_all_visible(fun_account):
    """AC-4: A 4-character account number is returned unchanged (nothing to mask)."""
    result = fun_account.fun_mask_account_number(MASK_EXACT_FOUR)

    assert result == MASK_EXACT_FOUR, (
        f"A 4-char number has no prefix to mask; expected '{MASK_EXACT_FOUR}', got '{result}'"
    )


def test_ac4_mask_fewer_than_four_chars_raises_value_error(fun_account):
    """AC-4: fun_mask_account_number raises ValueError for account_number shorter than 4 chars."""
    with pytest.raises(ValueError):
        fun_account.fun_mask_account_number(MASK_THREE_CHARS)


def test_ac4_mask_empty_string_raises_value_error(fun_account):
    """AC-4: fun_mask_account_number raises ValueError for an empty string."""
    with pytest.raises(ValueError):
        fun_account.fun_mask_account_number("")


def test_ac4_mask_result_length_equals_input_length(fun_account):
    """AC-4: The masked result has the same total length as the original account number."""
    account_number = "12345678901234"
    result = fun_account.fun_mask_account_number(account_number)

    assert len(result) == len(account_number), (
        f"Masked length {len(result)} != original length {len(account_number)}"
    )


def test_ac4_create_account_does_not_log_full_account_number(fun_account, fun_make_user):
    """AC-4: fun_create_account never writes the full account number to any log record."""
    user_id = fun_make_user()

    handler = fun_attach_log_capture()
    try:
        result = fun_account.fun_create_account(user_id)
        full_account_number = result.get("account_number", "")
        all_messages = " ".join(handler.fun_all_messages())

        assert full_account_number, "Need a real account_number to test log suppression"
        assert full_account_number not in all_messages, (
            "Full account number found in log output during fun_create_account — PII leak"
        )
    finally:
        fun_detach_log_capture(handler)


def test_ac4_get_account_account_number_matches_masked_pattern(fun_account, fun_make_user):
    """AC-4: The account_number from fun_get_account can be correctly masked by fun_mask_account_number."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)

    account = fun_account.fun_get_account(user_id)
    account_number = account["account_number"]

    # The account number must be long enough to mask (>= 4 chars).
    assert len(account_number) >= 4, (
        f"account_number '{account_number}' is too short to mask"
    )

    masked = fun_account.fun_mask_account_number(account_number)

    # Verify only the last 4 are visible.
    assert masked.endswith(account_number[-4:])
    assert "*" in masked  # at least the leading portion is starred


def test_ac4_masked_number_does_not_reveal_full_number(fun_account, fun_make_user):
    """AC-4: The masked output returned by fun_mask_account_number never equals the full number."""
    user_id = fun_make_user()
    fun_account.fun_create_account(user_id)

    account = fun_account.fun_get_account(user_id)
    account_number = account["account_number"]

    # Only applicable if account_number is longer than 4 digits.
    if len(account_number) > 4:
        masked = fun_account.fun_mask_account_number(account_number)
        assert masked != account_number, (
            "Masked output must not equal the full unmasked account number"
        )
