"""Authentication feature: register, login, logout, session gating.

Satisfies specs/auth.md AC-1 through AC-10.
"""

import logging
import re

import bcrypt
from mysql.connector import errorcode

from src.db.connection import fun_get_connection

logger = logging.getLogger(__name__)

GENERIC_LOGIN_ERROR = "Invalid username or password"
MAX_PASSWORD_BYTES = 72
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def fun_register(username: str, email: str, phone: str, password: str) -> dict:
    """Register a new user after validating all fields.

    Hashes the password with bcrypt before storage. No PII is logged.
    Satisfies AC-1, AC-2, AC-3, AC-4.

    Args:
        username: Desired login identifier (must be unique, case-insensitive).
        email: User's email address (must be unique, valid format).
        phone: User's phone number (digits only).
        password: Plaintext password — hashed before storage, never logged.

    Returns:
        dict: {"ok": True} on success, or {"ok": False, "error": str} on failure.
    """
    username = username.strip() if username else ""
    email = email.strip() if email else ""
    phone = phone.strip() if phone else ""

    if not username:
        return {"ok": False, "error": "Username is required."}
    if not email:
        return {"ok": False, "error": "Email is required."}
    if not phone:
        return {"ok": False, "error": "Phone number is required."}
    if not password or not password.strip():
        return {"ok": False, "error": "Password is required."}

    if not EMAIL_RE.match(email):
        return {"ok": False, "error": "Please enter a valid email address."}
    if not phone.isdigit():
        return {"ok": False, "error": "Phone number must contain digits only."}
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return {"ok": False, "error": f"Password must be {MAX_PASSWORD_BYTES} characters or fewer."}

    password_hash = bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    try:
        conn = fun_get_connection()
    except Exception as exc:
        logger.error("DB connection error during registration: %s", type(exc).__name__)
        return {"ok": False, "error": "Service unavailable. Please try again."}

    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, email, phone, password_hash) "
            "VALUES (%s, %s, %s, %s)",
            (username, email, phone, password_hash),
        )
        conn.commit()
        return {"ok": True}
    except Exception as exc:
        conn.rollback()
        if getattr(exc, "errno", None) == errorcode.ER_DUP_ENTRY:
            msg = getattr(exc, "msg", "") or ""
            if "uq_users_username" in msg:
                return {"ok": False, "error": "That username is already taken."}
            if "uq_users_email" in msg:
                return {"ok": False, "error": "An account with that email already exists."}
            return {"ok": False, "error": "That username or email is already registered."}
        logger.error("Registration error: %s", type(exc).__name__)
        return {"ok": False, "error": "Registration failed. Please try again."}
    finally:
        cursor.close()
        conn.close()


def fun_login(username: str, password: str) -> dict:
    """Verify credentials and return session data on success.

    Returns an identical generic error for both wrong-password and
    unknown-username cases to prevent user enumeration. No PII is logged.
    Satisfies AC-5, AC-6, AC-10.

    Args:
        username: The user's login identifier.
        password: Plaintext password to verify against the stored bcrypt hash.

    Returns:
        dict: {"ok": True, "logged_in": True, "user_id": int, "username": str}
              on success, or {"ok": False, "error": str} on failure.
    """
    try:
        conn = fun_get_connection()
    except Exception as exc:
        logger.error("DB connection error during login: %s", type(exc).__name__)
        return {"ok": False, "error": "Service unavailable. Please try again."}

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, username, password_hash FROM users "
            "WHERE LOWER(username) = LOWER(%s)",
            (username,),
        )
        row = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if row is None:
        return {"ok": False, "error": GENERIC_LOGIN_ERROR}

    if not bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
        return {"ok": False, "error": GENERIC_LOGIN_ERROR}

    return {"ok": True, "logged_in": True, "user_id": row["id"], "username": row["username"]}


def fun_logout(session: dict) -> None:
    """Clear the session, logging the user out.

    Satisfies AC-8. Clears all session keys then sets logged_in=False
    so that fun_require_auth returns False for the same dict.

    Args:
        session: The mutable session dict to clear (e.g. st.session_state).

    Returns:
        None
    """
    session.clear()
    session["logged_in"] = False


def fun_require_auth(session: dict) -> bool:
    """Return True only if the session represents a fully authenticated user.

    Satisfies AC-7, AC-8, AC-9. Requires logged_in to be truthy AND
    user_id to be present and not None.

    Args:
        session: The session dict to inspect.

    Returns:
        bool: True if authenticated, False otherwise.
    """
    return bool(
        session.get("logged_in") and session.get("user_id") is not None
    )
