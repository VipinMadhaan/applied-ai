"""Account feature: open a bank account for a logged-in user.

Satisfies specs/account.md AC-1 through AC-4.
"""

import logging
import secrets

from mysql.connector import errorcode

from src.db.connection import fun_get_connection

logger = logging.getLogger(__name__)

ACCOUNT_NUMBER_LENGTH = 12
MAX_GENERATION_ATTEMPTS = 10


def fun_generate_account_number() -> str:
    """Generate a cryptographically random numeric account number.

    Uses the secrets module (CSPRNG) so account numbers cannot be predicted
    from observing prior values.

    Returns:
        str: A random string of ACCOUNT_NUMBER_LENGTH decimal digits.
    """
    return "".join(secrets.choice("0123456789") for _ in range(ACCOUNT_NUMBER_LENGTH))


def fun_create_account(user_id: int) -> dict:
    """Create a bank account for a user who does not yet have one.

    Pre-checks for an existing account, then inserts with a generated unique
    account number, retrying only on account_number collision. The full
    account number is never written to logs. Satisfies AC-1, AC-2, AC-3.

    Args:
        user_id: Primary key of the authenticated user.

    Returns:
        dict: {"ok": True, "account_id": int, "account_number": str} on success,
              or {"ok": False, "error": str} on failure.
              Callers MUST pass account_number through fun_mask_account_number
              before rendering it in any UI.
    """
    existing = fun_get_account(user_id)
    if existing is not None:
        return {"ok": False, "error": "You already have a bank account."}

    try:
        conn = fun_get_connection()
    except Exception as exc:
        logger.error("DB connection error creating account: %s", type(exc).__name__)
        return {"ok": False, "error": "Service unavailable. Please try again."}

    cursor = conn.cursor()
    try:
        for _ in range(MAX_GENERATION_ATTEMPTS):
            account_number = fun_generate_account_number()
            try:
                cursor.execute(
                    "INSERT INTO accounts (user_id, account_number) VALUES (%s, %s)",
                    (user_id, account_number),
                )
                conn.commit()
                account_id = cursor.lastrowid
                return {"ok": True, "account_id": account_id, "account_number": account_number}
            except Exception as exc:
                conn.rollback()
                if getattr(exc, "errno", None) == errorcode.ER_DUP_ENTRY:
                    # Re-check to distinguish user_id collision (race) from
                    # account_number collision — avoids fragile constraint-name parsing.
                    if fun_get_account(user_id) is not None:
                        return {"ok": False, "error": "You already have a bank account."}
                    continue
                logger.error("Account creation error: %s", type(exc).__name__)
                return {"ok": False, "error": "Account creation failed. Please try again."}
        logger.error(
            "Exhausted %d attempts generating unique account number",
            MAX_GENERATION_ATTEMPTS,
        )
        return {"ok": False, "error": "Account creation failed. Please try again."}
    finally:
        cursor.close()
        conn.close()


def fun_get_account(user_id: int) -> dict | None:
    """Return the accounts row for the given user, or None if no account exists.

    The balance is returned as Decimal (never float). Returns None for both
    "no account" and connection/query errors — callers that need to distinguish
    service failures should wrap calls in try/except at the UI layer.
    Satisfies AC-1, AC-2.

    Args:
        user_id: Primary key of the authenticated user.

    Returns:
        dict with keys id, user_id, account_number, balance (Decimal), created_at;
        or None if no account exists or a DB error occurs.
    """
    try:
        conn = fun_get_connection()
    except Exception as exc:
        logger.error("DB connection error fetching account: %s", type(exc).__name__)
        return None

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, user_id, account_number, balance, created_at "
            "FROM accounts WHERE user_id = %s",
            (user_id,),
        )
        return cursor.fetchone()
    except Exception as exc:
        logger.error("Account query error: %s", type(exc).__name__)
        return None
    finally:
        cursor.close()
        conn.close()


def fun_mask_account_number(account_number: str) -> str:
    """Mask all but the last 4 characters of an account number with '*'.

    Satisfies AC-4. Must be called by any UI code before rendering an account
    number; the raw value returned by fun_create_account / fun_get_account is
    never displayed directly.

    Args:
        account_number: The full account number string (must be >= 4 chars).

    Returns:
        str: Account number with all but the last 4 characters replaced by '*'.

    Raises:
        ValueError: If account_number has fewer than 4 characters.
    """
    if len(account_number) < 4:
        raise ValueError(
            f"account_number must be at least 4 characters, got {len(account_number)}"
        )
    return "*" * (len(account_number) - 4) + account_number[-4:]
