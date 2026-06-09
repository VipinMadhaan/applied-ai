"""Dashboard feature: retrieve all data needed to render the account summary page.

Satisfies specs/dashboard.md AC-1 through AC-6.
"""

import logging
from decimal import Decimal

from src.db.connection import fun_get_connection
from src.features.account import fun_mask_account_number

logger = logging.getLogger(__name__)

RECENT_TX_LIMIT = 5


def fun_get_dashboard_data(user_id: int) -> dict | None:
    """Return all data required to render the dashboard for the given user.

    Fetches the user profile, account summary, and the most recent transactions
    in a single DB round-trip per query. The account number is masked before
    being included in the return value — the full number is never exposed to
    callers. Satisfies AC-1, AC-2, AC-3, AC-4, AC-5, AC-6.

    Args:
        user_id: Primary key of the authenticated user.

    Returns:
        dict with keys:
            username             (str)
            email                (str)
            phone                (str)
            masked_account_number (str)  last 4 visible, rest '*'
            balance              (Decimal)
            recent_transactions  (list[dict])  up to 5, newest first.
                each dict: type, amount (Decimal), category, note,
                           created_at, balance_after (Decimal)
        Returns None if the user does not exist or has no account.
    """
    try:
        conn = fun_get_connection()
    except Exception as exc:
        logger.error("DB connection error in dashboard: %s", type(exc).__name__)
        return None

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, username, email, phone FROM users WHERE id = %s",
            (user_id,),
        )
        user = cursor.fetchone()
        if not user:
            return None

        cursor.execute(
            "SELECT id, account_number, balance FROM accounts WHERE user_id = %s",
            (user_id,),
        )
        account = cursor.fetchone()
        if not account:
            return None

        cursor.execute(
            "SELECT type, amount, category, note, created_at, balance_after "
            "FROM transactions "
            "WHERE account_id = %s "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT %s",
            (account["id"], RECENT_TX_LIMIT),
        )
        recent_transactions = cursor.fetchall()

    except Exception as exc:
        logger.error("Dashboard query error: %s", type(exc).__name__)
        return None
    finally:
        cursor.close()
        conn.close()

    # Explicitly cast money fields to Decimal regardless of driver/connector variant.
    # WARNING: this dict contains PII (email, phone) — callers must never log it.
    safe_txs = []
    for tx in recent_transactions:
        safe_txs.append({
            **tx,
            "amount": Decimal(str(tx["amount"])),
            "balance_after": Decimal(str(tx["balance_after"])),
        })

    return {
        "username": user["username"],
        "email": user["email"],
        "phone": user["phone"],
        "masked_account_number": fun_mask_account_number(account["account_number"]),
        "balance": Decimal(str(account["balance"])),
        "recent_transactions": safe_txs,
    }
