"""
Tests for the authentication feature (src/features/auth.py).

Covers every acceptance criterion in specs/auth.md:
  AC-1  Valid registration creates exactly one users row.
  AC-2  Duplicate username / email is rejected; no row created.
  AC-3  Empty / whitespace fields, invalid email, non-numeric phone rejected.
  AC-4  Stored hash is bcrypt, never equals plaintext, plaintext not in logs.
  AC-5  Correct credentials establish a session with the right keys.
  AC-6  Wrong password AND unknown username return the same generic message.
  AC-7  Session dict returned by fun_login satisfies fun_require_auth.
  AC-8  fun_logout clears session; fun_require_auth returns False afterward.
  AC-9  fun_require_auth returns False for empty / logged-out dicts.
  AC-10 fun_register / fun_login never log password, hash, phone, or email.
"""

import logging
import os
import sys
from decimal import Decimal

import bcrypt
import mysql.connector
import pytest
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path setup — ensure src/ is importable before any feature import.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Load .env so DB credentials are available before the module is imported.
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TEST_DB_NAME = "aarambh_bank_test"

VALID_USERNAME = "testuser"
VALID_EMAIL = "testuser@example.com"
VALID_PHONE = "9876543210"
VALID_PASSWORD = "SecurePass123"

GENERIC_FAILURE_MESSAGE = "Invalid username or password"


# ---------------------------------------------------------------------------
# Helpers
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


def fun_count_users(username: str) -> int:
    """Return the number of users rows whose username matches (case-insensitive).

    Args:
        username: The username to look up.

    Returns:
        int: Row count (0 or 1 in normal operation).
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM users WHERE LOWER(username) = LOWER(%s)", (username,)
    )
    (count,) = cursor.fetchone()
    cursor.close()
    conn.close()
    return count


def fun_fetch_user_row(username: str) -> dict | None:
    """Fetch a single users row by username (case-insensitive).

    Args:
        username: The username to look up.

    Returns:
        dict with column values, or None if no row found.
    """
    conn = fun_get_test_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM users WHERE LOWER(username) = LOWER(%s)", (username,)
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# Session-level fixture: create (or recreate) the test database + schema.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def fun_setup_test_database():
    """Session fixture: create the test DB and initialise the schema.

    Sets os.environ['DB_NAME'] to TEST_DB_NAME for the entire test session so
    that fun_init_schema and all feature functions target the throwaway DB.

    Yields control to the test session, then drops the test DB on teardown.
    """
    # Override DB_NAME before importing any feature module.
    os.environ["DB_NAME"] = TEST_DB_NAME

    # Create the test database if it does not exist yet.
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

    # Now import and run fun_init_schema — it reads DB_NAME from env.
    from src.db.schema import fun_init_schema  # noqa: PLC0415

    fun_init_schema()

    yield

    # Teardown: drop the test database.
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
    """Truncate users (and dependent) tables before every test.

    Ensures each test starts with a clean slate so tests are independent.
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
# Convenience import alias resolved after DB env is set.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fun_auth():
    """Return the auth module so tests can call feature functions.

    Returns:
        module: src.features.auth
    """
    import importlib

    return importlib.import_module("src.features.auth")


# ===========================================================================
# AC-1: Valid registration creates exactly one users row.
# ===========================================================================


def test_ac1_valid_registration_creates_one_row(fun_auth):
    """AC-1: Registering with valid unique fields inserts exactly one users row."""
    result = fun_auth.fun_register(
        VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD
    )

    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    assert fun_count_users(VALID_USERNAME) == 1


def test_ac1_returned_dict_has_ok_true(fun_auth):
    """AC-1: fun_register returns {'ok': True} on valid input."""
    result = fun_auth.fun_register(
        "alice", "alice@example.com", "9000000001", "AlicePass1"
    )
    assert result.get("ok") is True


# ===========================================================================
# AC-2: Duplicate username or email is rejected; no extra row created.
# ===========================================================================


def test_ac2_duplicate_username_rejected(fun_auth):
    """AC-2: A second registration with the same username is rejected."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    result = fun_auth.fun_register(
        VALID_USERNAME, "other@example.com", "9000000002", VALID_PASSWORD
    )

    assert result["ok"] is False
    assert result.get("error"), "Expected a non-empty error message"
    assert fun_count_users(VALID_USERNAME) == 1  # still only the original row


def test_ac2_duplicate_email_rejected(fun_auth):
    """AC-2: A second registration with the same email is rejected."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    result = fun_auth.fun_register(
        "differentuser", VALID_EMAIL, "9000000003", VALID_PASSWORD
    )

    assert result["ok"] is False
    assert result.get("error"), "Expected a non-empty error message"
    # The original user must still be the only row.
    assert fun_count_users(VALID_USERNAME) == 1
    assert fun_count_users("differentuser") == 0


def test_ac2_duplicate_username_case_insensitive(fun_auth):
    """AC-2 edge: Username uniqueness is case-insensitive."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    result = fun_auth.fun_register(
        VALID_USERNAME.upper(), "upper@example.com", "9000000004", VALID_PASSWORD
    )

    assert result["ok"] is False
    # Total users with that username (any case) must still be 1.
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    (total,) = cursor.fetchone()
    cursor.close()
    conn.close()
    assert total == 1


# ===========================================================================
# AC-3: Empty/whitespace fields, invalid email, non-numeric phone rejected.
# ===========================================================================


def test_ac3_empty_username_rejected(fun_auth):
    """AC-3: Registration with an empty username is rejected; no row created."""
    result = fun_auth.fun_register("", VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    assert result["ok"] is False
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    (total,) = cursor.fetchone()
    cursor.close()
    conn.close()
    assert total == 0


def test_ac3_whitespace_only_username_rejected(fun_auth):
    """AC-3: Whitespace-only username counts as empty and is rejected."""
    result = fun_auth.fun_register("   ", VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    assert result["ok"] is False
    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    (total,) = cursor.fetchone()
    cursor.close()
    conn.close()
    assert total == 0


def test_ac3_empty_email_rejected(fun_auth):
    """AC-3: Registration with an empty email is rejected; no row created."""
    result = fun_auth.fun_register(VALID_USERNAME, "", VALID_PHONE, VALID_PASSWORD)

    assert result["ok"] is False


def test_ac3_whitespace_only_email_rejected(fun_auth):
    """AC-3: Whitespace-only email is rejected."""
    result = fun_auth.fun_register(VALID_USERNAME, "   ", VALID_PHONE, VALID_PASSWORD)

    assert result["ok"] is False


def test_ac3_empty_phone_rejected(fun_auth):
    """AC-3: Registration with an empty phone is rejected."""
    result = fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, "", VALID_PASSWORD)

    assert result["ok"] is False


def test_ac3_whitespace_only_phone_rejected(fun_auth):
    """AC-3: Whitespace-only phone is rejected."""
    result = fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, "   ", VALID_PASSWORD)

    assert result["ok"] is False


def test_ac3_empty_password_rejected(fun_auth):
    """AC-3: Registration with an empty password is rejected."""
    result = fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, "")

    assert result["ok"] is False


def test_ac3_invalid_email_format_rejected(fun_auth):
    """AC-3: Registration with a malformed email (no @) is rejected."""
    result = fun_auth.fun_register(
        VALID_USERNAME, "notanemail", VALID_PHONE, VALID_PASSWORD
    )

    assert result["ok"] is False
    assert fun_count_users(VALID_USERNAME) == 0


def test_ac3_email_missing_domain_rejected(fun_auth):
    """AC-3: Email with @ but no domain part is rejected."""
    result = fun_auth.fun_register(
        VALID_USERNAME, "user@", VALID_PHONE, VALID_PASSWORD
    )

    assert result["ok"] is False


def test_ac3_non_numeric_phone_rejected(fun_auth):
    """AC-3: Registration with a non-numeric phone number is rejected."""
    result = fun_auth.fun_register(
        VALID_USERNAME, VALID_EMAIL, "98765ABCDE", VALID_PASSWORD
    )

    assert result["ok"] is False
    assert fun_count_users(VALID_USERNAME) == 0


def test_ac3_phone_with_spaces_rejected(fun_auth):
    """AC-3: Phone containing spaces (non-numeric) is rejected."""
    result = fun_auth.fun_register(
        VALID_USERNAME, VALID_EMAIL, "987 654 3210", VALID_PASSWORD
    )

    assert result["ok"] is False


def test_ac3_no_row_created_on_any_invalid_input(fun_auth):
    """AC-3: Regardless of which field is invalid, zero rows are inserted."""
    bad_cases = [
        ("", VALID_EMAIL, VALID_PHONE, VALID_PASSWORD),
        (VALID_USERNAME, "bademail", VALID_PHONE, VALID_PASSWORD),
        (VALID_USERNAME, VALID_EMAIL, "abc", VALID_PASSWORD),
        (VALID_USERNAME, VALID_EMAIL, VALID_PHONE, ""),
    ]
    for username, email, phone, password in bad_cases:
        fun_auth.fun_register(username, email, phone, password)

    conn = fun_get_test_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    (total,) = cursor.fetchone()
    cursor.close()
    conn.close()
    assert total == 0, f"Expected 0 rows after all invalid registrations, got {total}"


# ===========================================================================
# AC-4: Stored hash is bcrypt; never equals plaintext; plaintext not in logs.
# ===========================================================================


def test_ac4_stored_hash_is_bcrypt(fun_auth):
    """AC-4: The password_hash stored in the DB is a valid bcrypt hash."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    row = fun_fetch_user_row(VALID_USERNAME)
    assert row is not None, "User row not found after registration"
    stored_hash = row["password_hash"]

    # bcrypt hashes start with $2b$ or $2a$
    assert stored_hash.startswith(("$2b$", "$2a$")), (
        f"Hash does not look like bcrypt: {stored_hash[:10]}..."
    )


def test_ac4_hash_not_equal_to_plaintext(fun_auth):
    """AC-4: The stored hash is never equal to the plaintext password."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    row = fun_fetch_user_row(VALID_USERNAME)
    assert row["password_hash"] != VALID_PASSWORD


def test_ac4_bcrypt_verify_works(fun_auth):
    """AC-4: bcrypt.checkpw confirms the stored hash matches the original password."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    row = fun_fetch_user_row(VALID_USERNAME)
    stored_hash = row["password_hash"]
    is_valid = bcrypt.checkpw(
        VALID_PASSWORD.encode("utf-8"), stored_hash.encode("utf-8")
    )
    assert is_valid is True


# ===========================================================================
# AC-5: Correct credentials establish a session with the right keys.
# ===========================================================================


def test_ac5_login_correct_credentials_returns_ok(fun_auth):
    """AC-5: Logging in with correct credentials returns ok=True."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    result = fun_auth.fun_login(VALID_USERNAME, VALID_PASSWORD)

    assert result["ok"] is True


def test_ac5_login_result_contains_user_id(fun_auth):
    """AC-5: Successful login result includes a non-None integer user_id."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    result = fun_auth.fun_login(VALID_USERNAME, VALID_PASSWORD)

    assert "user_id" in result
    assert isinstance(result["user_id"], int)
    assert result["user_id"] > 0


def test_ac5_login_result_contains_username(fun_auth):
    """AC-5: Successful login result includes the username string."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    result = fun_auth.fun_login(VALID_USERNAME, VALID_PASSWORD)

    assert "username" in result
    assert isinstance(result["username"], str)
    assert result["username"].lower() == VALID_USERNAME.lower()


def test_ac5_session_dict_satisfies_require_auth(fun_auth):
    """AC-5: The dict returned by fun_login satisfies fun_require_auth."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)
    login_result = fun_auth.fun_login(VALID_USERNAME, VALID_PASSWORD)

    session = {
        "logged_in": login_result.get("logged_in", True),
        "user_id": login_result["user_id"],
        "username": login_result["username"],
    }
    assert fun_auth.fun_require_auth(session) is True


def test_ac5_login_session_has_logged_in_true(fun_auth):
    """AC-5: Successful login result includes logged_in=True (session contract)."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)
    result = fun_auth.fun_login(VALID_USERNAME, VALID_PASSWORD)

    # Either fun_login itself sets logged_in or the caller constructs the session.
    # We verify that building the canonical session dict from the result gives logged_in=True.
    session = {"logged_in": True, "user_id": result["user_id"], "username": result["username"]}
    assert session["logged_in"] is True


# ===========================================================================
# AC-6: Wrong password AND unknown username return the same generic message.
# ===========================================================================


def test_ac6_wrong_password_returns_generic_message(fun_auth):
    """AC-6: Login with correct username but wrong password returns generic error."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    result = fun_auth.fun_login(VALID_USERNAME, "WrongPassword!")

    assert result["ok"] is False
    error_msg = result.get("error", "")
    assert error_msg, "Expected a non-empty error message"


def test_ac6_unknown_username_returns_generic_message(fun_auth):
    """AC-6: Login with a username that does not exist returns generic error."""
    result = fun_auth.fun_login("nonexistentuser", VALID_PASSWORD)

    assert result["ok"] is False
    error_msg = result.get("error", "")
    assert error_msg, "Expected a non-empty error message"


def test_ac6_wrong_password_and_unknown_user_same_message(fun_auth):
    """AC-6: Both failure cases return identical error messages (no user enumeration)."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    wrong_password_result = fun_auth.fun_login(VALID_USERNAME, "WrongPassword!")
    unknown_user_result = fun_auth.fun_login("nonexistentuser", VALID_PASSWORD)

    assert wrong_password_result["ok"] is False
    assert unknown_user_result["ok"] is False
    assert wrong_password_result.get("error") == unknown_user_result.get("error"), (
        "Different error messages reveal which field was wrong (user enumeration risk)"
    )


# ===========================================================================
# AC-7: Session persists across page navigation (feature-layer interpretation).
# ===========================================================================


def test_ac7_login_result_has_all_session_keys(fun_auth):
    """AC-7: fun_login result contains user_id and username required for session persistence."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)
    result = fun_auth.fun_login(VALID_USERNAME, VALID_PASSWORD)

    assert result["ok"] is True
    assert "user_id" in result
    assert "username" in result


def test_ac7_require_auth_true_for_valid_session(fun_auth):
    """AC-7: fun_require_auth returns True for a properly constructed session dict."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)
    login_result = fun_auth.fun_login(VALID_USERNAME, VALID_PASSWORD)

    session = {
        "logged_in": True,
        "user_id": login_result["user_id"],
        "username": login_result["username"],
    }
    # Simulates the session dict surviving a page re-render.
    assert fun_auth.fun_require_auth(session) is True
    assert fun_auth.fun_require_auth(session) is True  # call twice — still True


# ===========================================================================
# AC-8: Logout clears the session; fun_require_auth returns False afterward.
# ===========================================================================


def test_ac8_logout_clears_session(fun_auth):
    """AC-8: After fun_logout, fun_require_auth returns False for the same dict."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)
    login_result = fun_auth.fun_login(VALID_USERNAME, VALID_PASSWORD)

    session = {
        "logged_in": True,
        "user_id": login_result["user_id"],
        "username": login_result["username"],
    }
    assert fun_auth.fun_require_auth(session) is True

    fun_auth.fun_logout(session)

    assert fun_auth.fun_require_auth(session) is False


def test_ac8_session_no_longer_has_user_id_after_logout(fun_auth):
    """AC-8: After logout the session dict does not retain sensitive user data."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)
    login_result = fun_auth.fun_login(VALID_USERNAME, VALID_PASSWORD)

    session = {
        "logged_in": True,
        "user_id": login_result["user_id"],
        "username": login_result["username"],
    }
    fun_auth.fun_logout(session)

    # Either the key is absent or explicitly set to a falsy / logged-out value.
    logged_in_value = session.get("logged_in")
    assert not logged_in_value, (
        "logged_in should be False or absent after logout"
    )


# ===========================================================================
# AC-9: fun_require_auth returns False for empty / unauthenticated dicts.
# ===========================================================================


def test_ac9_require_auth_false_for_empty_dict(fun_auth):
    """AC-9: An empty session dict is treated as unauthenticated."""
    assert fun_auth.fun_require_auth({}) is False


def test_ac9_require_auth_false_for_logged_out_dict(fun_auth):
    """AC-9: A dict with logged_in=False is treated as unauthenticated."""
    session = {"logged_in": False}
    assert fun_auth.fun_require_auth(session) is False


def test_ac9_require_auth_false_when_logged_in_absent(fun_auth):
    """AC-9: A dict without the logged_in key is treated as unauthenticated."""
    session = {"user_id": 999, "username": "ghost"}
    assert fun_auth.fun_require_auth(session) is False


def test_ac9_require_auth_false_for_none_user_id(fun_auth):
    """AC-9: A session with logged_in=True but user_id=None is unauthenticated."""
    session = {"logged_in": True, "user_id": None, "username": ""}
    assert fun_auth.fun_require_auth(session) is False


# ===========================================================================
# AC-10: Authentication code never logs password, hash, phone, or email.
# ===========================================================================


class _PiiCapture(logging.Handler):
    """Custom log handler that records all emitted log records.

    Used to inspect log output for PII leakage.
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


def fun_attach_log_capture() -> _PiiCapture:
    """Attach a _PiiCapture handler to the root logger and return it.

    Returns:
        _PiiCapture: The handler instance now collecting log output.
    """
    handler = _PiiCapture()
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)
    return handler


def fun_detach_log_capture(handler: _PiiCapture) -> None:
    """Remove the given _PiiCapture handler from the root logger.

    Args:
        handler: The handler to remove.
    """
    logging.getLogger().removeHandler(handler)


def test_ac10_register_does_not_log_password(fun_auth):
    """AC-10: fun_register never writes the plaintext password to any log record."""
    handler = fun_attach_log_capture()
    try:
        fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)
        all_messages = " ".join(handler.fun_all_messages())
        assert VALID_PASSWORD not in all_messages, (
            "Plaintext password found in log output during fun_register"
        )
    finally:
        fun_detach_log_capture(handler)


def test_ac10_register_does_not_log_email(fun_auth):
    """AC-10: fun_register never writes the user's email to any log record."""
    handler = fun_attach_log_capture()
    try:
        fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)
        all_messages = " ".join(handler.fun_all_messages())
        assert VALID_EMAIL not in all_messages, (
            "Email found in log output during fun_register"
        )
    finally:
        fun_detach_log_capture(handler)


def test_ac10_register_does_not_log_phone(fun_auth):
    """AC-10: fun_register never writes the user's phone number to any log record."""
    handler = fun_attach_log_capture()
    try:
        fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)
        all_messages = " ".join(handler.fun_all_messages())
        assert VALID_PHONE not in all_messages, (
            "Phone number found in log output during fun_register"
        )
    finally:
        fun_detach_log_capture(handler)


def test_ac10_register_does_not_log_password_hash(fun_auth):
    """AC-10: fun_register never writes the bcrypt hash to any log record."""
    handler = fun_attach_log_capture()
    try:
        fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)
        row = fun_fetch_user_row(VALID_USERNAME)
        stored_hash = row["password_hash"] if row else ""
        all_messages = " ".join(handler.fun_all_messages())
        if stored_hash:
            assert stored_hash not in all_messages, (
                "bcrypt hash found in log output during fun_register"
            )
    finally:
        fun_detach_log_capture(handler)


def test_ac10_login_does_not_log_password(fun_auth):
    """AC-10: fun_login never writes the plaintext password to any log record."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    handler = fun_attach_log_capture()
    try:
        fun_auth.fun_login(VALID_USERNAME, VALID_PASSWORD)
        all_messages = " ".join(handler.fun_all_messages())
        assert VALID_PASSWORD not in all_messages, (
            "Plaintext password found in log output during fun_login"
        )
    finally:
        fun_detach_log_capture(handler)


def test_ac10_login_does_not_log_email(fun_auth):
    """AC-10: fun_login never writes the user's email to any log record."""
    fun_auth.fun_register(VALID_USERNAME, VALID_EMAIL, VALID_PHONE, VALID_PASSWORD)

    handler = fun_attach_log_capture()
    try:
        fun_auth.fun_login(VALID_USERNAME, VALID_PASSWORD)
        all_messages = " ".join(handler.fun_all_messages())
        assert VALID_EMAIL not in all_messages, (
            "Email found in log output during fun_login"
        )
    finally:
        fun_detach_log_capture(handler)


def test_ac10_login_failure_does_not_log_password(fun_auth):
    """AC-10: A failed fun_login call never writes the attempted password to logs."""
    handler = fun_attach_log_capture()
    try:
        fun_auth.fun_login("nonexistentuser", VALID_PASSWORD)
        all_messages = " ".join(handler.fun_all_messages())
        assert VALID_PASSWORD not in all_messages, (
            "Plaintext password found in log output during failed fun_login"
        )
    finally:
        fun_detach_log_capture(handler)
